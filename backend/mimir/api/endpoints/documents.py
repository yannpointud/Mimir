"""
Document management endpoints.

This module provides endpoints for uploading, managing, and monitoring
documents in the RAG system.
"""

import asyncio
import logging
import os
import urllib.parse
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse

from mimir.api.dependencies import (
    get_audit_log_repository,
    get_bm25_store,
    get_document_repository,
    get_ingestion_processor,
    get_vector_store,
)
from mimir.api.middleware.rate_limit import get_client_identifier, limiter
from mimir.api.responses import rejection_to_http
from mimir.auth.middleware import get_current_user, require_admin
from mimir.config import settings
from mimir.database.repository import AuditLogRepository, DocumentRepository
from mimir.ingestion.processor import IngestionProcessor
from mimir.rag_core.implementations.bm25_store import Bm25LexicalStore
from mimir.rag_core.implementations.faiss_store import FaissVectorStore
from mimir.services import index_maintenance
from mimir.services.document_deletion import delete_document_everywhere
from mimir.services.document_reader import build_document_view
from mimir.services.document_upload import DocumentUpload, UploadPolicy
from mimir.services.errors import RequestRejectedError
from mimir.shared.clock import utc_now
from mimir.shared.errors import NotFoundError
from mimir.shared.models import (
    BaseResponse,
    ConsistencyValidationResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentStatsOverview,
    DocumentStatusCounts,
    DocumentWithChunksResponse,
    PaginationModel,
    StorageInfo,
    VectorStoreOverview,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
    dependencies=[Depends(require_admin)],  # Default deny: management routes require admin
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Admin privileges required"},
        404: {"description": "Document not found"},
    },
)

# Read-only routes open to every chat user: the passages cited in an answer and
# the original file must be viewable without an admin account. Listing,
# statistics and every mutation stay on the admin router above.
reader_router = APIRouter(
    prefix="/documents",
    tags=["documents"],
    responses={
        404: {"description": "Document not found"},
    },
)


@router.get("/", response_model=DocumentListResponse)
def list_documents(
    pagination: PaginationModel = Depends(),
    status_filter: str | None = Query(None, description="Filter by document status"),
    search: str | None = Query(None, description="Search in filenames"),
    doc_repo: DocumentRepository = Depends(get_document_repository),
) -> DocumentListResponse:
    """List documents, filtered and paginated."""
    filters = {"status": status_filter} if status_filter else {}
    documents, total_count = doc_repo.get_all_paginated(
        offset=pagination.offset, limit=pagination.limit, filters=filters, search=search
    )
    document_responses = [DocumentResponse.model_validate(doc) for doc in documents]
    return DocumentListResponse(
        documents=document_responses,
        total_count=total_count,
        pagination={
            "offset": pagination.offset,
            "limit": pagination.limit,
            "total": total_count,
            "has_more": pagination.offset + len(document_responses) < total_count,
        },
    )


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: int, doc_repo: DocumentRepository = Depends(get_document_repository)
) -> DocumentResponse:
    """Get specific document by ID."""
    document = doc_repo.get_by_id(document_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found",
        )

    return DocumentResponse.model_validate(document)


@reader_router.get("/{document_id}/full", response_model=DocumentWithChunksResponse)
async def get_document_with_chunks(
    document_id: int,
    doc_repo: DocumentRepository = Depends(get_document_repository),
    vector_store: FaissVectorStore = Depends(get_vector_store),
) -> DocumentWithChunksResponse:
    """Get specific document by ID with all its chunks and content."""
    try:
        return await build_document_view(document_id, doc_repo, vector_store)
    except RequestRejectedError as e:
        raise rejection_to_http(e) from e


@reader_router.get("/{document_id}/download")
def download_document(
    document_id: int, doc_repo: DocumentRepository = Depends(get_document_repository)
) -> FileResponse:
    """Download the original document file."""
    document = doc_repo.get_by_id(document_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found",
        )

    # Verify the file exists
    if not document.path or not os.path.exists(document.path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Original document file not found on disk"
        )

    # Determine MIME type
    file_ext = Path(document.path).suffix.lower()
    mime_type_mapping = {
        ".txt": "text/plain",
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".md": "text/markdown",
        ".html": "text/html",
        ".csv": "text/csv",
        ".json": "application/json",
        ".xml": "application/xml",
    }
    media_type = mime_type_mapping.get(file_ext, "application/octet-stream")

    # Encode filename for Unicode characters (French accents, etc.)
    encoded_filename = urllib.parse.quote(document.filename.encode("utf-8"))

    # Return the file for display in the browser
    return FileResponse(
        path=document.path,
        media_type=media_type,
        filename=document.filename,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}"},
    )


@router.post("/upload", response_model=DocumentResponse)
# Rate limit per JWT user with IP fallback. The `request` parameter
# is REQUIRED by slowapi: without it the decorator raises at import time.
@limiter.limit(
    lambda: f"{settings.rate_limit_upload_per_minute}/minute", key_func=get_client_identifier
)
async def upload_document(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    preserve: bool = Form(False, description="Protect document from automatic deletion"),
    current_user: dict[str, Any] = Depends(get_current_user),
    doc_repo: DocumentRepository = Depends(get_document_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    ingestion_processor: IngestionProcessor = Depends(get_ingestion_processor),
) -> DocumentResponse:
    """
    Upload a new document for processing.

    ``request`` is required by the rate limiter and ``response`` lets slowapi
    inject the X-RateLimit-* headers on the returned model.
    """
    upload = DocumentUpload(
        file,
        UploadPolicy(
            upload_dir=settings.upload_dir,
            max_file_size_mb=settings.max_file_size_mb,
            supported_extensions=settings.supported_file_extensions,
        ),
    )
    try:
        upload.check_name_and_size()
        document = await upload.run(
            doc_repo, audit_repo, ingestion_processor, preserve, current_user
        )
    except RequestRejectedError as e:
        raise rejection_to_http(e) from e
    logger.info(f"Document uploaded successfully: {upload.filename} (ID: {document.id})")
    return DocumentResponse.model_validate(document)


@router.delete("/{document_id}", response_model=BaseResponse)
async def delete_document(
    document_id: int,
    force: bool = Query(False, description="Force delete protected documents"),
    current_user: dict[str, Any] = Depends(get_current_user),
    doc_repo: DocumentRepository = Depends(get_document_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    vector_store: FaissVectorStore = Depends(get_vector_store),
    bm25_store: Bm25LexicalStore = Depends(get_bm25_store),
) -> BaseResponse:
    """Delete a document and its associated data.

    The BM25 lexical index is rebuilt from the FAISS source of truth after
    deletion so both indexes stay synchronized.
    """
    try:
        filename = await delete_document_everywhere(
            document_id,
            force=force,
            doc_repo=doc_repo,
            audit_repo=audit_repo,
            vector_store=vector_store,
            bm25_store=bm25_store,
        )
    except RequestRejectedError as e:
        raise rejection_to_http(e) from e
    return BaseResponse(
        success=True,
        message=f"Document '{filename}' deleted successfully",
        timestamp=utc_now(),
    )


@router.patch("/{document_id}/preserve", response_model=DocumentResponse)
def toggle_document_preservation(
    document_id: int,
    preserve: bool = Query(..., description="New preservation status"),
    current_user: dict[str, Any] = Depends(get_current_user),
    doc_repo: DocumentRepository = Depends(get_document_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> DocumentResponse:
    """Protect a document from deletion, or remove that protection."""
    document = doc_repo.update_preserve_status(document_id, preserve)
    audit_repo.create_log(
        user_type="admin",
        action="document_preserve_toggle",
        details=f"Document preservation {'enabled' if preserve else 'disabled'}: {document.filename}",
        ip_address="system",
        success=True,
    )
    logger.info(f"Document preservation toggled: {document.filename} -> {preserve}")
    return DocumentResponse.model_validate(document)


@router.post("/{document_id}/reprocess", response_model=BaseResponse)
def reprocess_document(
    document_id: int,
    current_user: dict[str, Any] = Depends(get_current_user),
    doc_repo: DocumentRepository = Depends(get_document_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    ingestion_processor: IngestionProcessor = Depends(get_ingestion_processor),
) -> BaseResponse:
    """Queue a document for ingestion again."""
    document = doc_repo.get_by_id(document_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found",
        )
    if not document.path:
        raise NotFoundError(f"Document {document_id} has no stored file")

    doc_repo.update_status(document_id, "pending", error_message=None)
    queued = ingestion_processor.queue_document(
        file_path=document.path,
        document_id=str(document_id),
        metadata={"reprocessed_by": current_user["sub"]},
    )
    if not queued:
        logger.warning(
            f"Ingestion queue is full, cannot queue document for reprocessing: {document.filename}",
            extra={
                "extra_fields": {
                    "document_id": document_id,
                    "filename": document.filename,
                    "queue_size": ingestion_processor.get_queue_size(),
                    "type": "queue_full_reprocess",
                }
            },
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ingestion queue is full. The system is currently processing many documents. Please try reprocessing later.",
        )

    audit_repo.create_log(
        user_type="admin",
        action="document_reprocess",
        details=f"Document queued for reprocessing: {document.filename}",
        ip_address="system",
        success=True,
    )
    logger.info(f"Document queued for reprocessing: {document.filename} (ID: {document_id})")
    return BaseResponse(
        success=True,
        message=f"Document '{document.filename}' queued for reprocessing",
        timestamp=utc_now(),
    )


@router.get("/stats/overview", response_model=DocumentStatsOverview)
async def get_document_stats(
    doc_repo: DocumentRepository = Depends(get_document_repository),
    vector_store: FaissVectorStore = Depends(get_vector_store),
) -> DocumentStatsOverview:
    """Document statistics with the vector store health."""
    db_stats = doc_repo.get_statistics()
    # Both calls take the FAISS lock: run them off the event loop
    vector_stats = await asyncio.to_thread(vector_store.get_stats)
    health_status = await asyncio.to_thread(vector_store.health_check)
    return DocumentStatsOverview(
        total_documents=db_stats.get("total_documents", 0),
        by_status=DocumentStatusCounts(
            pending=db_stats.get("count_pending", 0),
            indexing=db_stats.get("count_indexing", 0),
            indexed=db_stats.get("count_indexed", 0),
            error=db_stats.get("count_error", 0),
        ),
        total_chunks=db_stats.get("total_chunks", 0),
        preserved_documents=db_stats.get("protected_documents", 0),
        vector_store=VectorStoreOverview(
            total_vectors=vector_stats.get("total_vectors", 0),
            active_vectors=vector_stats.get("active_vectors", 0),
            deleted_vectors=vector_stats.get("deleted_vectors", 0),
            total_documents=vector_stats.get("total_documents", 0),
            memory_usage_mb=vector_stats.get("memory_usage_mb", 0),
            health_status=health_status,
        ),
        storage_info=StorageInfo(
            upload_directory=settings.upload_dir,
            supported_extensions=sorted(settings.supported_file_extensions),
            max_file_size_mb=settings.max_file_size_mb,
        ),
        timestamp=utc_now(),
    )


@router.post("/maintenance/validate-consistency", response_model=ConsistencyValidationResponse)
async def validate_vector_store_consistency(
    fix_issues: bool = Query(False, description="Automatically fix detected issues"),
    save_report: bool = Query(True, description="Save detailed report to file"),
    current_user: dict[str, Any] = Depends(get_current_user),
    doc_repo: DocumentRepository = Depends(get_document_repository),
    vector_store: FaissVectorStore = Depends(get_vector_store),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> ConsistencyValidationResponse:
    """Check SQLite against FAISS, optionally fixing the inconsistencies.

    A failure is recorded in the audit trail before it propagates.
    """
    report_dir = (
        Path(settings.upload_dir).parent / "reports" / "validation" if save_report else None
    )
    try:
        # The validation scans the whole FAISS index: run it off the event loop
        return await asyncio.to_thread(
            index_maintenance.validate_index_consistency,
            vector_store,
            doc_repo,
            audit_repo,
            fix_issues=fix_issues,
            report_dir=report_dir,
            initiated_by=current_user["sub"],
        )
    except Exception as e:
        index_maintenance.record_validation_failure(audit_repo, e, current_user["sub"])
        raise
