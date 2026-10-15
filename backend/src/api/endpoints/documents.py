"""
Document management endpoints.

This module provides endpoints for uploading, managing, and monitoring
documents in the RAG system.
"""

from typing import Any
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    UploadFile,
    File,
    Form,
    Query,
    Request,
    Response,
)
from fastapi.responses import FileResponse
from datetime import datetime
import asyncio
import logging
import os
import urllib.parse
from pathlib import Path

from src.auth.middleware import require_admin, get_current_user
from src.api.middleware.rate_limit import limiter, get_client_identifier
from src.database.repository import DocumentRepository, AuditLogRepository
from src.api.dependencies import (
    get_document_repository,
    get_audit_log_repository,
    get_ingestion_processor,
    get_vector_store,
    get_bm25_store,
)
from src.api.responses import rejection_to_http
from src.shared.models import (
    ConsistencyValidationResponse,
    DocumentResponse,
    DocumentListResponse,
    DocumentStatsOverview,
    DocumentStatusCounts,
    BaseResponse,
    DocumentWithChunksResponse,
    PaginationModel,
    StorageInfo,
    VectorStoreOverview,
)
from src.services import index_maintenance
from src.services.document_deletion import delete_document_everywhere
from src.services.document_reader import build_document_view
from src.services.document_upload import DocumentUpload, UploadPolicy
from src.services.errors import RequestRejectedError
from src.config import settings

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
async def list_documents(
    pagination: PaginationModel = Depends(),
    status_filter: str | None = Query(None, description="Filter by document status"),
    search: str | None = Query(None, description="Search in filenames"),
    doc_repo: DocumentRepository = Depends(get_document_repository),
) -> DocumentListResponse:
    """
    List all documents with optional filtering and pagination.

    Args:
        pagination: Pagination parameters
        status_filter: Optional status filter
        search: Optional filename search
        doc_repo: Document repository

    Returns:
        DocumentListResponse: List of documents with pagination
    """
    try:
        # Build filters
        filters = {}
        if status_filter:
            filters["status"] = status_filter

        # Get documents with pagination
        documents, total_count = doc_repo.get_all_paginated(
            offset=pagination.offset, limit=pagination.limit, filters=filters, search=search
        )

        # Convert to response models
        document_responses = [DocumentResponse.from_orm(doc) for doc in documents]

        logger.debug(f"Listed {len(document_responses)} documents (total: {total_count})")

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

    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve documents"
        ) from e


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: int, doc_repo: DocumentRepository = Depends(get_document_repository)
) -> DocumentResponse:
    """
    Get specific document by ID.

    Args:
        document_id: Document ID
        doc_repo: Document repository

    Returns:
        DocumentResponse: Document details
    """
    document = doc_repo.get_by_id(document_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found",
        )

    return DocumentResponse.from_orm(document)


@reader_router.get("/{document_id}/full", response_model=DocumentWithChunksResponse)
async def get_document_with_chunks(
    document_id: int,
    doc_repo: DocumentRepository = Depends(get_document_repository),
    vector_store=Depends(get_vector_store),
) -> DocumentWithChunksResponse:
    """
    Get specific document by ID with all its chunks and content.

    Args:
        document_id: Document ID
        doc_repo: Document repository
        vector_store: Vector store for retrieving chunks

    Returns:
        DocumentWithChunksResponse: Document details with chunks
    """
    try:
        return await build_document_view(document_id, doc_repo, vector_store)
    except RequestRejectedError as e:
        raise rejection_to_http(e) from e


@reader_router.get("/{document_id}/download")
async def download_document(
    document_id: int, doc_repo: DocumentRepository = Depends(get_document_repository)
):
    """
    Download the original document file.

    Args:
        document_id: Document ID
        doc_repo: Document repository

    Returns:
        FileResponse: The original document file
    """
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
    ingestion_processor=Depends(get_ingestion_processor),
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
            invalid_filename_detail="Invalid filename",
            supported_extensions=settings.supported_file_extensions,
            warn_on_duplicate=True,
        ),
    )
    try:
        upload.check_name_and_size()
        document = await upload.run(
            doc_repo, ingestion_processor, preserve, current_user, audit_repo=audit_repo
        )
        logger.info(f"Document uploaded successfully: {upload.filename} (ID: {document.id})")
        return DocumentResponse.from_orm(document)

    except RequestRejectedError as e:
        raise rejection_to_http(e) from e
    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Document upload error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Document upload failed"
        ) from e


@router.delete("/{document_id}", response_model=BaseResponse)
async def delete_document(
    document_id: int,
    force: bool = Query(False, description="Force delete protected documents"),
    current_user: dict[str, Any] = Depends(get_current_user),
    doc_repo: DocumentRepository = Depends(get_document_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    vector_store=Depends(get_vector_store),
    bm25_store=Depends(get_bm25_store),
) -> BaseResponse:
    """
    Delete a document and its associated data.

    Args:
        document_id: Document ID to delete
        force: Force delete even if protected
        current_user: Current authenticated user
        doc_repo: Document repository
        audit_repo: Audit log repository
        vector_store: Vector store service
        bm25_store: BM25 lexical store; rebuilt from the FAISS source of truth
            after deletion so both indexes stay synchronized

    Returns:
        BaseResponse: Operation result
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
        return BaseResponse(
            success=True,
            message=f"Document '{filename}' deleted successfully",
            timestamp=datetime.utcnow(),
        )

    except RequestRejectedError as e:
        raise rejection_to_http(e) from e
    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Document deletion error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Document deletion failed"
        ) from e


@router.patch("/{document_id}/preserve", response_model=DocumentResponse)
async def toggle_document_preservation(
    document_id: int,
    preserve: bool = Query(..., description="New preservation status"),
    current_user: dict[str, Any] = Depends(get_current_user),
    doc_repo: DocumentRepository = Depends(get_document_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> DocumentResponse:
    """
    Toggle document preservation status.

    Args:
        document_id: Document ID
        preserve: New preservation status
        current_user: Current authenticated user
        doc_repo: Document repository
        audit_repo: Audit log repository

    Returns:
        DocumentResponse: Updated document
    """
    try:
        document = doc_repo.get_by_id(document_id)
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document with ID {document_id} not found",
            )

        # Update preservation status.
        # Known defect kept on purpose (docs/cleanup/DECISIONS.md, D0.4): the
        # repository has no update_preserve_status, so this AttributeError makes
        # the route answer 500, as pinned by the characterization oracle.
        updated_doc = doc_repo.update_preserve_status(document_id, preserve)  # type: ignore[attr-defined]

        # Log the change
        audit_repo.create_log(
            user_type="admin",
            action="document_preserve_toggle",
            details=f"Document preservation {'enabled' if preserve else 'disabled'}: {document.filename}",
            ip_address="system",
            success=True,
            additional_data={
                "document_id": document_id,
                "filename": document.filename,
                "preserve": preserve,
            },
        )

        logger.info(f"Document preservation toggled: {document.filename} -> {preserve}")

        return DocumentResponse.from_orm(updated_doc)

    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Document preservation toggle error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update document preservation status",
        ) from e


@router.post("/{document_id}/reprocess", response_model=BaseResponse)
async def reprocess_document(
    document_id: int,
    current_user: dict[str, Any] = Depends(get_current_user),
    doc_repo: DocumentRepository = Depends(get_document_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    ingestion_processor=Depends(get_ingestion_processor),
) -> BaseResponse:
    """
    Queue document for reprocessing.

    Args:
        document_id: Document ID to reprocess
        current_user: Current authenticated user
        doc_repo: Document repository
        audit_repo: Audit log repository
        ingestion_processor: Ingestion processor service

    Returns:
        BaseResponse: Operation result
    """
    try:
        document = doc_repo.get_by_id(document_id)
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document with ID {document_id} not found",
            )

        # Reset document status for reprocessing
        doc_repo.update_status(document_id, "pending", error_message=None)

        # Queue document for reprocessing
        try:
            # Queue the document for reprocessing
            queued = ingestion_processor.queue_document(
                file_path=document.path,
                document_id=str(document_id),
                preserve=document.preserve,
                metadata={"reprocessed_by": current_user.get("username", "unknown")},
            )

            if not queued:
                # Queue is full - return 503 Service Unavailable
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

            logger.info(
                f"Document queued for reprocessing: {document.filename} (ID: {document_id})"
            )

        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001 - API boundary: a queueing failure becomes a 500
            logger.error(f"Error queuing document for reprocessing: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to queue document for reprocessing",
            ) from e

        # Log reprocessing request
        audit_repo.create_log(
            user_type="admin",
            action="document_reprocess",
            details=f"Document queued for reprocessing: {document.filename}",
            ip_address="system",
            success=True,
            additional_data={"document_id": document_id, "filename": document.filename},
        )

        logger.info(f"Document queued for reprocessing: {document.filename} (ID: {document_id})")

        return BaseResponse(
            success=True,
            message=f"Document '{document.filename}' queued for reprocessing",
            timestamp=datetime.utcnow(),
        )

    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Document reprocessing error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue document for reprocessing",
        ) from e


@router.get("/stats/overview", response_model=DocumentStatsOverview)
async def get_document_stats(
    doc_repo: DocumentRepository = Depends(get_document_repository),
    vector_store=Depends(get_vector_store),
) -> DocumentStatsOverview:
    """
    Get document statistics overview with vector store health.

    Args:
        doc_repo: Document repository
        vector_store: Vector store service

    Returns:
        dict: Document statistics with vector store info
    """
    try:
        # Database statistics
        db_stats = doc_repo.get_statistics()

        # Vector store statistics -- both get_stats() and health_check()
        # acquire the FAISS RLock, so they are offloaded to a worker thread
        # to keep the event loop responsive
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
                supported_extensions=list(settings.supported_file_extensions),
                max_file_size_mb=settings.max_file_size_mb,
            ),
            timestamp=datetime.utcnow(),
        )

    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Error getting document stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve document statistics",
        ) from e


@router.post("/maintenance/validate-consistency", response_model=ConsistencyValidationResponse)
async def validate_vector_store_consistency(
    fix_issues: bool = Query(False, description="Automatically fix detected issues"),
    save_report: bool = Query(True, description="Save detailed report to file"),
    current_user: dict[str, Any] = Depends(get_current_user),
    doc_repo: DocumentRepository = Depends(get_document_repository),
    vector_store=Depends(get_vector_store),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> ConsistencyValidationResponse:
    """
    Validate consistency between SQLite and FAISS with optional auto-fix.

    Args:
        fix_issues: Automatically fix detected issues
        save_report: Save detailed report to file
        current_user: Authenticated user
        doc_repo: Document repository
        vector_store: Vector store service
        audit_repo: Audit log repository

    Returns:
        Dict: Validation results
    """
    try:
        return index_maintenance.validate_index_consistency(
            vector_store,
            doc_repo,
            audit_repo,
            fix_issues=fix_issues,
            report_dir=(
                Path(settings.upload_dir).parent / "reports" / "validation" if save_report else None
            ),
            initiated_by=current_user.get("username", "unknown"),
        )

    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Consistency validation failed: {e}")
        index_maintenance.record_validation_failure(
            audit_repo, e, current_user.get("username", "unknown")
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Consistency validation failed",
        ) from e
