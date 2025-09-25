"""
Document management endpoints.

This module provides endpoints for uploading, managing, and monitoring
documents in the RAG system.
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from datetime import datetime
import logging
import os
import hashlib
import urllib.parse
from pathlib import Path

from src.auth.middleware import require_admin, get_current_user
from src.database.connection import get_db_session
from src.database.repository import DocumentRepository, AuditLogRepository
from src.api.dependencies import get_document_repository, get_audit_log_repository, get_ingestion_processor, get_vector_store
from src.shared.models import (
    DocumentResponse, DocumentListResponse, BaseResponse,
    DocumentWithChunksResponse, ChunkResponse,
    PaginationModel, validate_filename, sanitize_filename
)
from src.ingestion.extractors import ExtractorFactory
from src.ingestion.queue_manager import TaskPriority
from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
    dependencies=[Depends(require_admin)],  # All document endpoints require admin
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Admin privileges required"},
        404: {"description": "Document not found"},
    }
)


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    pagination: PaginationModel = Depends(),
    status_filter: Optional[str] = Query(None, description="Filter by document status"),
    search: Optional[str] = Query(None, description="Search in filenames"),
    doc_repo: DocumentRepository = Depends(get_document_repository)
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
            offset=pagination.offset,
            limit=pagination.limit,
            filters=filters,
            search=search
        )

        # Convert to response models
        document_responses = [
            DocumentResponse.from_orm(doc) for doc in documents
        ]

        logger.debug(f"Listed {len(document_responses)} documents (total: {total_count})")

        return DocumentListResponse(
            documents=document_responses,
            total_count=total_count,
            pagination={
                "offset": pagination.offset,
                "limit": pagination.limit,
                "total": total_count,
                "has_more": pagination.offset + len(document_responses) < total_count
            }
        )

    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve documents"
        )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: int,
    doc_repo: DocumentRepository = Depends(get_document_repository)
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
            detail=f"Document with ID {document_id} not found"
        )

    return DocumentResponse.from_orm(document)


@router.get("/{document_id}/full", response_model=DocumentWithChunksResponse)
async def get_document_with_chunks(
    document_id: int,
    doc_repo: DocumentRepository = Depends(get_document_repository),
    vector_store = Depends(get_vector_store)
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
    document = doc_repo.get_by_id(document_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found"
        )

    # Récupérer les chunks depuis le vector store
    chunk_responses = []
    try:
        # Récupérer tous les chunks pour ce document depuis le vector store
        # Le vector store stocke les chunks avec document_id comme métadonnée
        all_chunks = vector_store.get_document_chunks(str(document_id))

        # Convertir en ChunkResponse - utiliser le chunk_index original pour cohérence
        chunk_indexes = []
        for i, chunk in enumerate(all_chunks):
            # Les chunks du vector store ont toujours un chunk_index cohérent
            # Plus de fallback artificiel qui causait des incohérences
            chunk_indexes.append(chunk.chunk_index)
            chunk_responses.append(ChunkResponse(
                id=i,  # Index temporaire car pas d'ID réel
                document_id=document_id,
                chunk_index=chunk.chunk_index,  # Toujours présent dans les métadonnées FAISS
                text=chunk.text,
                metadata=chunk.metadata if hasattr(chunk, 'metadata') else {}
            ))

        # Logging pour validation de cohérence
        if chunk_indexes:
            logger.info(f"Document {document_id} chunks loaded: {len(chunk_indexes)} chunks, chunk_indexes: {chunk_indexes[:10]}")
        else:
            logger.warning(f"Document {document_id}: Aucun chunk trouvé dans le vector store")
    except Exception as e:
        logger.warning(f"Could not retrieve chunks for document {document_id}: {e}")
        # Continuer sans chunks si erreur

    # Lire le contenu original du fichier si possible
    content = None
    file_size = None
    mime_type = None

    if document.path and os.path.exists(document.path):
        try:
            file_size = os.path.getsize(document.path)

            # Déterminer le type MIME basé sur l'extension
            file_ext = Path(document.path).suffix.lower()
            mime_type_mapping = {
                '.txt': 'text/plain',
                '.pdf': 'application/pdf',
                '.doc': 'application/msword',
                '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                '.md': 'text/markdown',
                '.html': 'text/html'
            }
            mime_type = mime_type_mapping.get(file_ext, 'application/octet-stream')

            # Utiliser l'ExtractorFactory pour lire le contenu (comme lors de l'indexation)
            extractor_factory = ExtractorFactory()
            try:
                content = extractor_factory.extract_text(document.path)
                logger.debug(f"Successfully extracted text from {document.path} ({len(content) if content else 0} characters)")
            except Exception as extraction_error:
                logger.warning(f"Could not extract text from {document.path}: {extraction_error}")
                content = None

        except Exception as e:
            logger.warning(f"Could not read file metadata for document {document_id}: {e}")

    # Créer la réponse avec tous les détails
    return DocumentWithChunksResponse(
        id=document.id,
        filename=document.filename,
        path=document.path,
        preserve=document.preserve,
        file_hash=document.file_hash,
        status=document.status,
        error_message=document.error_message,
        chunk_count=document.chunk_count,
        created_at=document.created_at,
        indexed_at=document.indexed_at,
        chunks=chunk_responses,
        content=content,
        file_size=file_size,
        mime_type=mime_type
    )


@router.get("/{document_id}/download")
async def download_document(
    document_id: int,
    doc_repo: DocumentRepository = Depends(get_document_repository)
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
            detail=f"Document with ID {document_id} not found"
        )

    # Vérifier que le fichier existe
    if not document.path or not os.path.exists(document.path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original document file not found on disk"
        )

    # Déterminer le type MIME
    file_ext = Path(document.path).suffix.lower()
    mime_type_mapping = {
        '.txt': 'text/plain',
        '.pdf': 'application/pdf',
        '.doc': 'application/msword',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.md': 'text/markdown',
        '.html': 'text/html',
        '.csv': 'text/csv',
        '.json': 'application/json',
        '.xml': 'application/xml'
    }
    media_type = mime_type_mapping.get(file_ext, 'application/octet-stream')

    # Encoder le nom de fichier pour les caractères Unicode (accents français, etc.)
    encoded_filename = urllib.parse.quote(document.filename.encode('utf-8'))

    # Retourner le fichier pour affichage dans le navigateur
    return FileResponse(
        path=document.path,
        media_type=media_type,
        filename=document.filename,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}"}
    )


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    preserve: bool = Form(False, description="Protect document from automatic deletion"),
    priority: str = Form("normal", description="Processing priority (urgent, high, normal, low)"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    doc_repo: DocumentRepository = Depends(get_document_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    ingestion_processor = Depends(get_ingestion_processor)
) -> DocumentResponse:
    """
    Upload a new document for processing.

    Args:
        file: Uploaded file
        preserve: Whether to protect from deletion
        priority: Processing priority
        current_user: Current authenticated user
        doc_repo: Document repository
        audit_repo: Audit log repository
        ingestion_processor: Ingestion processor service

    Returns:
        DocumentResponse: Created document information
    """
    try:
        # Validate file
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No filename provided"
            )

        # Validate filename
        if not validate_filename(file.filename):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid filename"
            )

        # Sanitize filename
        safe_filename = sanitize_filename(file.filename)

        # Check file size
        if file.size and file.size > settings.max_file_size_mb * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size: {settings.max_file_size_mb}MB"
            )

        # Check file extension
        file_ext = Path(safe_filename).suffix.lower()
        if file_ext not in settings.supported_file_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type: {file_ext}"
            )

        # Read and save file
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty file"
            )

        # Calculate file hash for deduplication
        file_hash = hashlib.sha256(content).hexdigest()

        # Check for duplicate
        existing_doc = doc_repo.get_by_hash(file_hash)
        if existing_doc:
            logger.warning(f"Duplicate file upload attempted: {safe_filename}")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"File already exists: {existing_doc.filename}"
            )

        # Save file to upload directory
        upload_dir = Path(settings.upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)

        file_path = upload_dir / f"{file_hash}_{safe_filename}"
        with open(file_path, "wb") as f:
            f.write(content)

        # Create document record
        document = doc_repo.create(
            filename=safe_filename,
            path=str(file_path),
            file_hash=file_hash,
            preserve=preserve
        )

        # Log upload event
        audit_repo.create_log(
            user_type="admin",
            action="document_upload",
            details=f"File uploaded: {safe_filename}",
            ip_address="system",
            success=True,
            additional_data={
                "document_id": document.id,
                "filename": safe_filename,
                "file_size": len(content),
                "preserve": preserve,
                "priority": priority
            }
        )

        # Queue document for processing with the ingestion processor
        try:
            # Map string priority to TaskPriority enum
            priority_mapping = {
                "urgent": TaskPriority.URGENT,
                "high": TaskPriority.HIGH,
                "normal": TaskPriority.NORMAL,
                "low": TaskPriority.LOW
            }
            task_priority = priority_mapping.get(priority.lower(), TaskPriority.NORMAL)

            # Queue the document for processing
            queued = ingestion_processor.queue_document(
                file_path=file_path,
                document_id=str(document.id),
                priority=task_priority,
                preserve=preserve,
                metadata={"uploaded_by": current_user.get("username", "unknown")}
            )

            if not queued:
                # Queue is full - return 503 Service Unavailable
                logger.warning(
                    f"Ingestion queue is full, cannot queue document: {safe_filename}",
                    extra={'extra_fields': {
                        'document_id': document.id,
                        'filename': safe_filename,
                        'queue_size': ingestion_processor.get_queue_size(),
                        'type': 'queue_full_upload'
                    }}
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Ingestion queue is full. The system is currently processing many documents. Please try again later."
                )

            logger.info(f"Document queued for processing: {safe_filename} (ID: {document.id})")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error queuing document for processing: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to queue document for processing"
            )

        logger.info(f"Document uploaded successfully: {safe_filename} (ID: {document.id})")

        return DocumentResponse.from_orm(document)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document upload error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document upload failed"
        )


@router.delete("/{document_id}", response_model=BaseResponse)
async def delete_document(
    document_id: int,
    force: bool = Query(False, description="Force delete protected documents"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    doc_repo: DocumentRepository = Depends(get_document_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    vector_store = Depends(get_vector_store)
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

    Returns:
        BaseResponse: Operation result
    """
    try:
        document = doc_repo.get_by_id(document_id)
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document with ID {document_id} not found"
            )

        # Check if document is protected
        if document.preserve and not force:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Document is protected from deletion. Use force=true to override."
            )

        filename = document.filename
        file_path = document.path

        # Delete from database
        success = doc_repo.delete(document_id, force=force)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete document from database"
            )

        # Delete physical file
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.debug(f"Deleted file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to delete file {file_path}: {e}")
                # Continue - database deletion was successful

        # Remove from vector store
        try:
            vector_deleted = vector_store.delete(str(document_id))
            if vector_deleted:
                logger.info(f"Document chunks removed from vector store: {filename} (ID: {document_id})")
                
                # Déclencher un nettoyage des orphelins si nécessaire
                # (après plusieurs suppressions, il peut y avoir des incohérences)
                try:
                    stats = vector_store.get_stats()
                    deleted_ratio = stats.get('deleted_vectors', 0) / max(stats.get('total_vectors', 1), 1)
                    
                    # Si plus de 20% de chunks supprimés, déclencher nettoyage préventif
                    if deleted_ratio > 0.20:
                        logger.info(f"Triggering orphan cleanup after deletion (deleted ratio: {deleted_ratio:.2%})")
                        cleanup_result = vector_store.clean_orphans(create_backup=False)
                        logger.info(f"Orphan cleanup completed: {cleanup_result.get('cleaned_chunks', 0)} orphans removed")
                except Exception as cleanup_error:
                    logger.warning(f"Orphan cleanup after deletion failed: {cleanup_error}")
                    # Ne pas faire échouer la suppression si le nettoyage échoue
                    
            else:
                logger.warning(f"Failed to remove document chunks from vector store: {filename}")
        except Exception as e:
            logger.error(f"Error removing document from vector store: {e}")
            # Continue with deletion even if vector store removal fails

        # Log deletion event
        audit_repo.create_log(
            user_type="admin",
            action="document_delete",
            details=f"Document deleted: {filename}",
            ip_address="system",
            success=True,
            additional_data={
                "document_id": document_id,
                "filename": filename,
                "forced": force
            }
        )

        logger.info(f"Document deleted successfully: {filename} (ID: {document_id})")

        return BaseResponse(
            success=True,
            message=f"Document '{filename}' deleted successfully",
            timestamp=datetime.utcnow()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document deletion error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document deletion failed"
        )


@router.patch("/{document_id}/preserve", response_model=DocumentResponse)
async def toggle_document_preservation(
    document_id: int,
    preserve: bool = Query(..., description="New preservation status"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    doc_repo: DocumentRepository = Depends(get_document_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository)
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
                detail=f"Document with ID {document_id} not found"
            )

        # Update preservation status
        updated_doc = doc_repo.update_preserve_status(document_id, preserve)

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
                "preserve": preserve
            }
        )

        logger.info(f"Document preservation toggled: {document.filename} -> {preserve}")

        return DocumentResponse.from_orm(updated_doc)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document preservation toggle error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update document preservation status"
        )


@router.post("/{document_id}/reprocess", response_model=BaseResponse)
async def reprocess_document(
    document_id: int,
    priority: str = Query("normal", description="Processing priority"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    doc_repo: DocumentRepository = Depends(get_document_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    ingestion_processor = Depends(get_ingestion_processor)
) -> BaseResponse:
    """
    Queue document for reprocessing.

    Args:
        document_id: Document ID to reprocess
        priority: Processing priority
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
                detail=f"Document with ID {document_id} not found"
            )

        # Reset document status for reprocessing
        doc_repo.update_status(document_id, "pending", error_message=None)

        # Queue document for reprocessing with specified priority
        try:
            # Map string priority to TaskPriority enum
            priority_mapping = {
                "urgent": TaskPriority.URGENT,
                "high": TaskPriority.HIGH,
                "normal": TaskPriority.NORMAL,
                "low": TaskPriority.LOW
            }
            task_priority = priority_mapping.get(priority.lower(), TaskPriority.NORMAL)

            # Queue the document for reprocessing
            queued = ingestion_processor.queue_document(
                file_path=document.path,
                document_id=str(document_id),
                priority=task_priority,
                preserve=document.preserve,
                metadata={"reprocessed_by": current_user.get("username", "unknown")}
            )

            if not queued:
                # Queue is full - return 503 Service Unavailable
                logger.warning(
                    f"Ingestion queue is full, cannot queue document for reprocessing: {document.filename}",
                    extra={'extra_fields': {
                        'document_id': document_id,
                        'filename': document.filename,
                        'queue_size': ingestion_processor.get_queue_size(),
                        'type': 'queue_full_reprocess'
                    }}
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Ingestion queue is full. The system is currently processing many documents. Please try reprocessing later."
                )

            logger.info(f"Document queued for reprocessing: {document.filename} (ID: {document_id})")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error queuing document for reprocessing: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to queue document for reprocessing"
            )

        # Log reprocessing request
        audit_repo.create_log(
            user_type="admin",
            action="document_reprocess",
            details=f"Document queued for reprocessing: {document.filename}",
            ip_address="system",
            success=True,
            additional_data={
                "document_id": document_id,
                "filename": document.filename,
                "priority": priority
            }
        )

        logger.info(f"Document queued for reprocessing: {document.filename} (ID: {document_id})")

        return BaseResponse(
            success=True,
            message=f"Document '{document.filename}' queued for reprocessing",
            timestamp=datetime.utcnow()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document reprocessing error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue document for reprocessing"
        )


@router.get("/stats/overview", response_model=Dict[str, Any])
async def get_document_stats(
    doc_repo: DocumentRepository = Depends(get_document_repository),
    vector_store = Depends(get_vector_store)
) -> Dict[str, Any]:
    """
    Get document statistics overview with vector store health.

    Args:
        doc_repo: Document repository
        vector_store: Vector store service

    Returns:
        dict: Document statistics with vector store info
    """
    try:
        # Statistiques de la base de données
        db_stats = doc_repo.get_statistics()
        
        # Statistiques du vector store
        vector_stats = vector_store.get_stats()

        return {
            "total_documents": db_stats.get("total_documents", 0),
            "by_status": {
                "pending": db_stats.get("count_pending", 0),
                "indexing": db_stats.get("count_indexing", 0),
                "indexed": db_stats.get("count_indexed", 0),
                "error": db_stats.get("count_error", 0)
            },
            "total_chunks": db_stats.get("total_chunks", 0),
            "preserved_documents": db_stats.get("protected_documents", 0),
            "vector_store": {
                "total_vectors": vector_stats.get("total_vectors", 0),
                "active_vectors": vector_stats.get("active_vectors", 0),
                "deleted_vectors": vector_stats.get("deleted_vectors", 0),
                "total_documents": vector_stats.get("total_documents", 0),
                "memory_usage_mb": vector_stats.get("memory_usage_mb", 0),
                "health_status": vector_store.health_check()
            },
            "storage_info": {
                "upload_directory": settings.upload_dir,
                "supported_extensions": list(settings.supported_file_extensions),
                "max_file_size_mb": settings.max_file_size_mb
            },
            "timestamp": datetime.utcnow()
        }

    except Exception as e:
        logger.error(f"Error getting document stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve document statistics"
        )


@router.post("/maintenance/cleanup-orphans", response_model=Dict[str, Any])
async def cleanup_orphan_chunks(
    force_rebuild: bool = Query(False, description="Force vector store rebuild after cleanup"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    vector_store = Depends(get_vector_store),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository)
) -> Dict[str, Any]:
    """
    Nettoie manuellement les chunks orphelins du vector store.
    
    Args:
        force_rebuild: Force la reconstruction du vector store après nettoyage
        current_user: Utilisateur authentifié
        vector_store: Service vector store
        audit_repo: Repository d'audit
        
    Returns:
        Dict: Résultats du nettoyage
    """
    try:
        logger.info(f"Manual orphan cleanup initiated by {current_user.get('username', 'unknown')}")
        
        # Exécuter le nettoyage des orphelins
        cleanup_result = vector_store.clean_orphans(create_backup=True)
        
        # Reconstruction forcée si demandée
        rebuild_result = None
        if force_rebuild:
            rebuild_result = vector_store.rebuild_vector_store(
                force_rebuild=True, 
                cleanup_orphans=False  # Déjà fait
            )
        
        # Logger l'événement d'audit
        audit_repo.create_log(
            user_type="admin",
            action="maintenance_orphan_cleanup",
            details=f"Manual orphan cleanup: {cleanup_result.get('cleaned_chunks', 0)} orphans cleaned",
            ip_address="system",
            success=True,
            additional_data={
                "cleanup_result": cleanup_result,
                "rebuild_result": rebuild_result,
                "force_rebuild": force_rebuild,
                "initiated_by": current_user.get("username", "unknown")
            }
        )
        
        logger.info(
            f"Manual orphan cleanup completed: {cleanup_result.get('cleaned_chunks', 0)} orphans cleaned",
            extra={'extra_fields': {
                'cleanup_result': cleanup_result,
                'rebuild_result': rebuild_result,
                'type': 'manual_orphan_cleanup'
            }}
        )
        
        return {
            "success": True,
            "message": f"Cleanup completed: {cleanup_result.get('cleaned_chunks', 0)} orphan chunks removed",
            "cleanup_result": cleanup_result,
            "rebuild_result": rebuild_result,
            "timestamp": datetime.utcnow()
        }
        
    except Exception as e:
        logger.error(f"Manual orphan cleanup failed: {e}")
        
        # Logger l'échec
        audit_repo.create_log(
            user_type="admin",
            action="maintenance_orphan_cleanup",
            details=f"Manual orphan cleanup failed: {str(e)}",
            ip_address="system",
            success=False,
            additional_data={
                "error": str(e),
                "initiated_by": current_user.get("username", "unknown")
            }
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Orphan cleanup failed: {str(e)}"
        )


@router.post("/maintenance/rebuild-vectorstore", response_model=Dict[str, Any])
async def rebuild_vector_store(
    force_rebuild: bool = Query(False, description="Force rebuild even without deleted chunks"),
    cleanup_orphans: bool = Query(True, description="Clean orphans before rebuild"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    vector_store = Depends(get_vector_store),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository)
) -> Dict[str, Any]:
    """
    Reconstruit manuellement le vector store.
    
    Args:
        force_rebuild: Force la reconstruction même sans chunks supprimés
        cleanup_orphans: Nettoie les orphelins avant reconstruction
        current_user: Utilisateur authentifié
        vector_store: Service vector store
        audit_repo: Repository d'audit
        
    Returns:
        Dict: Résultats de la reconstruction
    """
    try:
        logger.info(f"Manual vector store rebuild initiated by {current_user.get('username', 'unknown')}")
        
        # Exécuter la reconstruction
        rebuild_result = vector_store.rebuild_vector_store(
            force_rebuild=force_rebuild,
            cleanup_orphans=cleanup_orphans
        )
        
        # Logger l'événement d'audit
        audit_repo.create_log(
            user_type="admin",
            action="maintenance_vectorstore_rebuild",
            details=f"Manual vector store rebuild: performed={rebuild_result.get('rebuild_performed', False)}",
            ip_address="system",
            success=True,
            additional_data={
                "rebuild_result": rebuild_result,
                "force_rebuild": force_rebuild,
                "cleanup_orphans": cleanup_orphans,
                "initiated_by": current_user.get("username", "unknown")
            }
        )
        
        logger.info(
            f"Manual vector store rebuild completed: performed={rebuild_result.get('rebuild_performed', False)}",
            extra={'extra_fields': {
                'rebuild_result': rebuild_result,
                'type': 'manual_vectorstore_rebuild'
            }}
        )
        
        return {
            "success": True,
            "message": "Vector store rebuild completed" if rebuild_result.get('rebuild_performed') else "Rebuild not needed",
            "rebuild_result": rebuild_result,
            "timestamp": datetime.utcnow()
        }
        
    except Exception as e:
        logger.error(f"Manual vector store rebuild failed: {e}")
        
        # Logger l'échec
        audit_repo.create_log(
            user_type="admin",
            action="maintenance_vectorstore_rebuild",
            details=f"Manual vector store rebuild failed: {str(e)}",
            ip_address="system",
            success=False,
            additional_data={
                "error": str(e),
                "initiated_by": current_user.get("username", "unknown")
            }
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vector store rebuild failed: {str(e)}"
        )


@router.post("/maintenance/validate-consistency", response_model=Dict[str, Any])
async def validate_vector_store_consistency(
    fix_issues: bool = Query(False, description="Automatically fix detected issues"),
    save_report: bool = Query(True, description="Save detailed report to file"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    doc_repo: DocumentRepository = Depends(get_document_repository),
    vector_store = Depends(get_vector_store),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository)
) -> Dict[str, Any]:
    """
    Valide la cohérence entre SQLite et FAISS avec correction optionnelle.
    
    Args:
        fix_issues: Corriger automatiquement les problèmes détectés
        save_report: Sauvegarder le rapport détaillé
        current_user: Utilisateur authentifié
        doc_repo: Repository des documents
        vector_store: Service vector store
        audit_repo: Repository d'audit
        
    Returns:
        Dict: Résultats de la validation
    """
    try:
        logger.info(f"Consistency validation initiated by {current_user.get('username', 'unknown')}")
        
        # Import du validateur
        from src.rag_core.implementations.validation_utils import VectorStoreValidator
        
        # Créer le validateur et exécuter la validation
        validator = VectorStoreValidator(vector_store, doc_repo)
        validation_result = validator.validate_consistency(fix_issues=fix_issues)
        
        # Sauvegarder le rapport si demandé
        report_path = None
        if save_report:
            try:
                from pathlib import Path
                import json
                
                # Créer le répertoire de rapports
                reports_dir = Path(settings.upload_dir).parent / "reports" / "validation"
                reports_dir.mkdir(parents=True, exist_ok=True)
                
                # Nom du fichier avec timestamp
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                report_filename = f"consistency_validation_{timestamp}.json"
                report_path = reports_dir / report_filename
                
                # Sauvegarder
                with open(report_path, 'w', encoding='utf-8') as f:
                    json.dump(validation_result, f, indent=2, default=str)
                
                logger.info(f"Validation report saved to {report_path}")
                
            except Exception as e:
                logger.warning(f"Failed to save validation report: {e}")
                # Ne pas faire échouer la validation si la sauvegarde échoue
        
        # Logger l'événement d'audit
        audit_repo.create_log(
            user_type="admin",
            action="maintenance_consistency_validation",
            details=f"Consistency validation: {validation_result.get('issues_found', {}).get('total_issues', 0)} issues found",
            ip_address="system",
            success=True,
            additional_data={
                "validation_result": {
                    "total_issues": validation_result.get('issues_found', {}).get('total_issues', 0),
                    "consistency_score": validation_result.get('consistency_score', 0),
                    "fixes_applied": len(validation_result.get('fixes_applied', [])),
                    "duration_seconds": validation_result.get('duration_seconds', 0)
                },
                "fix_issues": fix_issues,
                "report_saved": report_path is not None,
                "initiated_by": current_user.get("username", "unknown")
            }
        )
        
        # Formater la réponse
        issues_found = validation_result.get('issues_found', {})
        total_issues = issues_found.get('total_issues', 0)
        consistency_score = validation_result.get('consistency_score', 1.0)
        
        logger.info(
            f"Consistency validation completed: {total_issues} issues found, "
            f"score: {consistency_score:.2%}, fixes applied: {len(validation_result.get('fixes_applied', []))}",
            extra={'extra_fields': {
                'validation_result': validation_result,
                'type': 'consistency_validation'
            }}
        )
        
        return {
            "success": True,
            "message": f"Validation completed: {total_issues} issues found (consistency score: {consistency_score:.1%})",
            "validation_result": validation_result,
            "report_path": str(report_path) if report_path else None,
            "timestamp": datetime.utcnow()
        }
        
    except Exception as e:
        logger.error(f"Consistency validation failed: {e}")
        
        # Logger l'échec
        audit_repo.create_log(
            user_type="admin",
            action="maintenance_consistency_validation",
            details=f"Consistency validation failed: {str(e)}",
            ip_address="system",
            success=False,
            additional_data={
                "error": str(e),
                "initiated_by": current_user.get("username", "unknown")
            }
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Consistency validation failed: {str(e)}"
        )