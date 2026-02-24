"""
Administrative endpoints.

This module provides endpoints for system administration,
configuration management, and monitoring.
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from datetime import datetime, timedelta
import logging
import time
from pathlib import Path

from src.auth.middleware import require_admin, get_current_user
from src.database.repository import ConfigurationRepository, AuditLogRepository
from src.api.dependencies import get_configuration_repository, get_audit_log_repository
from src.cache.lru_cache import cache_service, chat_cache_service
from src.email_service.smtp_client import email_service
from src.shared.models import BaseResponse, PaginationModel
from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["administration"],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Admin privileges required"},
    }
)


@router.get("/system-info", response_model=Dict[str, Any])
async def get_system_info(
    current_user: Dict[str, Any] = Depends(require_admin)
) -> Dict[str, Any]:
    """
    Get comprehensive system information.

    Args:
        current_user: Current authenticated admin user

    Returns:
        dict: System information and statistics
    """
    try:
        import psutil
        import platform
        import sys
        from pathlib import Path

        # System information
        system_info = {
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "python_version": sys.version
            },
            "hardware": {
                "cpu_count": psutil.cpu_count(),
                "cpu_percent": psutil.cpu_percent(),
                "memory": {
                    "total": psutil.virtual_memory().total,
                    "available": psutil.virtual_memory().available,
                    "used": psutil.virtual_memory().used,
                    "percent": psutil.virtual_memory().percent
                },
                "disk": {
                    "total": psutil.disk_usage('/').total,
                    "free": psutil.disk_usage('/').free,
                    "used": psutil.disk_usage('/').used,
                    "percent": psutil.disk_usage('/').percent
                }
            },
            "application": {
                "version": settings.api_version,
                "environment": "production" if settings.is_production else "development",
                "data_directory": settings.data_dir,
                "upload_directory": settings.upload_dir,
                "database_url": settings.database_url.replace(settings.database_url.split('/')[-1], "***") if hasattr(settings, 'database_url') else "not configured"
            },
            "services": {
                "llm_provider": settings.llm_provider,
                "vector_store": settings.vector_store_type,
                "cache_enabled": True,  # Always enabled in this implementation
                "email_configured": email_service.get_configuration_status()["configured"],
                "watch_folder": getattr(settings, 'watch_folder', 'not configured')
            },
            "timestamp": datetime.utcnow()
        }

        logger.debug("System information retrieved successfully")
        return system_info

    except Exception as e:
        logger.error(f"Error retrieving system info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve system information"
        )


@router.get("/cache/stats", response_model=Dict[str, Any])
async def get_cache_stats() -> Dict[str, Any]:
    """
    Get cache service statistics.

    Returns:
        dict: Cache statistics for all cache services
    """
    try:
        main_cache_stats = cache_service.get_stats()
        chat_cache_stats = chat_cache_service.get_stats()

        # Adapt data for the frontend
        def adapt_cache_stats(stats):
            adapted = stats.copy()
            # Add 'utilization' expected by the frontend
            adapted['utilization'] = stats.get('utilization_percent', 0.0)
            return adapted

        # Compute global stats for the frontend
        total_requests = main_cache_stats["total_requests"] + chat_cache_stats["total_requests"]
        total_hits = main_cache_stats["hits"] + chat_cache_stats["hits"]
        hit_ratio = (total_hits / max(1, total_requests)) if total_requests > 0 else 0.0

        return {
            "main_cache": adapt_cache_stats(main_cache_stats),
            "chat_cache": adapt_cache_stats(chat_cache_stats),
            "global_stats": {
                "total_requests": total_requests,
                "hit_ratio": hit_ratio,
                "total_hits": total_hits,
                "total_misses": main_cache_stats["misses"] + chat_cache_stats["misses"]
            },
            "timestamp": datetime.utcnow()
        }

    except Exception as e:
        logger.error(f"Error retrieving cache stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve cache statistics"
        )


@router.post("/cache/clear", response_model=BaseResponse)
async def clear_cache(
    cache_type: str = Query("all", description="Cache type to clear (all, main, chat)"),
    current_user: Dict[str, Any] = Depends(require_admin),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository)
) -> BaseResponse:
    """
    Clear cache entries.

    Args:
        cache_type: Type of cache to clear
        current_user: Current authenticated admin user
        audit_repo: Audit log repository

    Returns:
        BaseResponse: Operation result
    """
    try:
        cleared_counts = {}

        if cache_type in ["all", "main"]:
            main_stats_before = cache_service.get_stats()
            cache_service.invalidate_all()
            cleared_counts["main_cache"] = main_stats_before["size"]

        if cache_type in ["all", "chat"]:
            chat_stats_before = chat_cache_service.get_stats()
            chat_cache_service.invalidate_all()
            cleared_counts["chat_cache"] = chat_stats_before["size"]

        # Log cache clear action
        audit_repo.create_log(
            user_type="admin",
            action="cache_clear",
            details=f"Cache cleared: {cache_type}",
            ip_address="system",
            success=True,
            additional_data={
                "cache_type": cache_type,
                "cleared_entries": cleared_counts,
                "admin_user": current_user["sub"]
            }
        )

        total_cleared = sum(cleared_counts.values())
        logger.info(f"Cache cleared by admin {current_user['sub']}: {cache_type}, {total_cleared} entries")

        return BaseResponse(
            success=True,
            message=f"Cache cleared successfully. Removed {total_cleared} entries from {cache_type} cache(s).",
            timestamp=datetime.utcnow()
        )

    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear cache"
        )


@router.get("/configuration", response_model=Dict[str, Any])
async def get_configuration(
    config_repo: ConfigurationRepository = Depends(get_configuration_repository)
) -> Dict[str, Any]:
    """
    Get system configuration settings.

    Args:
        config_repo: Configuration repository

    Returns:
        dict: Current configuration settings
    """
    try:
        # Get all configuration from database
        db_config = config_repo.get_all()

        # Combine with application settings (including masked sensitive ones)
        app_config = {
            "api_version": settings.api_version,
            "max_chunk_size": settings.max_chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "embedding_dimension": settings.embedding_dimension,
            "cache_max_size": getattr(settings, 'cache_max_size', 100),
            "cache_ttl_seconds": getattr(settings, 'cache_ttl_seconds', 3600),
            "supported_file_extensions": list(getattr(settings, 'supported_file_extensions', [])),
            "max_file_size_mb": getattr(settings, 'max_file_size_mb', 100),
            "jwt_expiration_hours": settings.jwt_expiration_hours,
            # LLM Configuration (with sensitive data)
            "llm_provider": settings.llm_provider,
            "mistral_api_key": settings.mistral_api_key,  # Will be masked by frontend
            "mistral_model": settings.mistral_model,
            "mistral_embedding_model": settings.mistral_embedding_model,
        }

        return {
            "database_config": {item.key: item.value for item in db_config},
            "application_config": app_config,
            "timestamp": datetime.utcnow()
        }

    except Exception as e:
        logger.error(f"Error retrieving configuration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve configuration"
        )


@router.put("/configuration", response_model=BaseResponse)
async def update_configuration(
    config_updates: Dict[str, str],
    current_user: Dict[str, Any] = Depends(require_admin),
    config_repo: ConfigurationRepository = Depends(get_configuration_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository)
) -> BaseResponse:
    """
    Update system configuration settings.

    Args:
        config_updates: Dictionary of configuration updates
        current_user: Current authenticated admin user
        config_repo: Configuration repository
        audit_repo: Audit log repository

    Returns:
        BaseResponse: Operation result
    """
    try:
        # Validate configuration keys (only allow certain keys to be updated)
        allowed_keys = {
            "maintenance_mode",
            "max_concurrent_ingestions",
            "ingestion_retry_limit",
            "email_escalation_enabled",
            "chat_rate_limit_per_minute",
            "auto_delete_failed_documents",
            "vector_search_threshold"
        }

        invalid_keys = set(config_updates.keys()) - allowed_keys
        if invalid_keys:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid configuration keys: {list(invalid_keys)}"
            )

        # Update each configuration item
        updated_items = []
        for key, value in config_updates.items():
            config_repo.set(key, value)
            updated_items.append(f"{key}={value}")

        # Log configuration changes
        audit_repo.create_log(
            user_type="admin",
            action="config_update",
            details=f"Configuration updated: {', '.join(updated_items)}",
            ip_address="system",
            success=True,
            additional_data={
                "updates": config_updates,
                "admin_user": current_user["sub"]
            }
        )

        logger.info(f"Configuration updated by admin {current_user['sub']}: {updated_items}")

        return BaseResponse(
            success=True,
            message=f"Configuration updated successfully. {len(updated_items)} items changed.",
            timestamp=datetime.utcnow()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating configuration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update configuration"
        )


@router.get("/audit-log", response_model=Dict[str, Any])
async def get_audit_log(
    pagination: PaginationModel = Depends(),
    action_filter: Optional[str] = Query(None, description="Filter by action type"),
    user_type_filter: Optional[str] = Query(None, description="Filter by user type"),
    success_filter: Optional[bool] = Query(None, description="Filter by success status"),
    days_back: int = Query(7, ge=1, le=90, description="Number of days to look back"),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository)
) -> Dict[str, Any]:
    """
    Get audit log entries with filtering.

    Args:
        pagination: Pagination parameters
        action_filter: Optional action filter
        user_type_filter: Optional user type filter
        success_filter: Optional success status filter
        days_back: Number of days to look back
        audit_repo: Audit log repository

    Returns:
        dict: Audit log entries with metadata
    """
    try:
        # Build filters
        filters = {}
        if action_filter:
            filters["action"] = action_filter
        if user_type_filter:
            filters["user_type"] = user_type_filter
        if success_filter is not None:
            filters["success"] = success_filter

        # Date range filter
        since_date = datetime.utcnow() - timedelta(days=days_back)
        filters["since_date"] = since_date

        # Get audit log entries
        entries, total_count = audit_repo.get_logs_paginated(
            offset=pagination.offset,
            limit=pagination.limit,
            filters=filters
        )

        # Convert to response format
        log_entries = []
        for entry in entries:
            log_entries.append({
                "id": entry.id,
                "timestamp": entry.created_at,
                "user_type": entry.user_type,
                "action": entry.action,
                "details": entry.details,
                "ip_address": entry.ip_address,
                "success": entry.success,
                "additional_data": entry.additional_data
            })

        return {
            "entries": log_entries,
            "total": total_count,
            "offset": pagination.offset,
            "limit": pagination.limit,
            "has_more": pagination.offset + len(log_entries) < total_count,
            "filters": {
                "action": action_filter,
                "user_type": user_type_filter,
                "success": success_filter,
                "days_back": days_back
            },
            "timestamp": datetime.utcnow()
        }

    except Exception as e:
        logger.error(f"Error retrieving audit log: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve audit log"
        )


@router.post("/maintenance", response_model=BaseResponse)
async def toggle_maintenance_mode(
    enabled: bool = Query(..., description="Enable or disable maintenance mode"),
    message: Optional[str] = Query(None, description="Optional maintenance message"),
    current_user: Dict[str, Any] = Depends(require_admin),
    config_repo: ConfigurationRepository = Depends(get_configuration_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository)
) -> BaseResponse:
    """
    Toggle system maintenance mode.

    Args:
        enabled: Whether to enable maintenance mode
        message: Optional maintenance message
        current_user: Current authenticated admin user
        config_repo: Configuration repository
        audit_repo: Audit log repository

    Returns:
        BaseResponse: Operation result
    """
    try:
        # Update maintenance mode configuration
        config_repo.set("maintenance_mode", "true" if enabled else "false")

        if message:
            config_repo.set("maintenance_message", message)

        # Log maintenance mode change
        audit_repo.create_log(
            user_type="admin",
            action="maintenance_mode_toggle",
            details=f"Maintenance mode {'enabled' if enabled else 'disabled'}" + (f": {message}" if message else ""),
            ip_address="system",
            success=True,
            additional_data={
                "enabled": enabled,
                "message": message,
                "admin_user": current_user["sub"]
            }
        )

        status_word = "enabled" if enabled else "disabled"
        logger.info(f"Maintenance mode {status_word} by admin {current_user['sub']}")

        return BaseResponse(
            success=True,
            message=f"Maintenance mode {status_word} successfully" + (f": {message}" if message else ""),
            timestamp=datetime.utcnow()
        )

    except Exception as e:
        logger.error(f"Error toggling maintenance mode: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to toggle maintenance mode"
        )


@router.post("/test-email", response_model=BaseResponse)
async def test_email_service(
    test_email: str = Query(..., description="Email address to send test message to"),
    current_user: Dict[str, Any] = Depends(require_admin),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository)
) -> BaseResponse:
    """
    Test email service configuration.

    Args:
        test_email: Email address to send test to
        current_user: Current authenticated admin user
        audit_repo: Audit log repository

    Returns:
        BaseResponse: Test result
    """
    try:
        # Send test email
        success = await email_service.send_notification_email(
            to_email=test_email,
            subject="Mimir Email Service Test",
            message="This is a test email from the Mimir system. If you receive this, email service is working correctly.",
            is_html=False
        )

        # Log test email attempt
        audit_repo.create_log(
            user_type="admin",
            action="email_service_test",
            details=f"Test email sent to {test_email}",
            ip_address="system",
            success=success,
            additional_data={
                "test_email": test_email,
                "admin_user": current_user["sub"]
            }
        )

        if success:
            return BaseResponse(
                success=True,
                message=f"Test email sent successfully to {test_email}",
                timestamp=datetime.utcnow()
            )
        else:
            return BaseResponse(
                success=False,
                message="Failed to send test email. Check email service configuration.",
                timestamp=datetime.utcnow()
            )

    except Exception as e:
        logger.error(f"Email service test error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Email service test failed"
        )


# ============= DOCUMENT MANAGEMENT ENDPOINTS =============
# Document endpoints added for frontend consistency

@router.get("/documents", response_model=Dict[str, Any])
async def admin_list_documents(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    status_filter: Optional[str] = Query(None, description="Filter by document status"),
    search: Optional[str] = Query(None, description="Search in filenames"),
    current_user: Dict[str, Any] = Depends(require_admin)
) -> Dict[str, Any]:
    """List documents via admin interface."""
    # Import here to avoid circular imports
    from src.database.repository import DocumentRepository
    from src.api.dependencies import get_document_repository

    # Use a new repository instance
    from src.database.connection import get_db_session
    db = next(get_db_session())
    doc_repo = DocumentRepository(db)

    try:
        # Compute offset
        offset = (page - 1) * limit

        # Retrieve documents with filters
        documents = doc_repo.get_all(
            offset=offset,
            limit=limit,
            order_by='created_at'
        )

        # Count total (simple approximation)
        total = len(doc_repo.get_all())

        return {
            "documents": [{
                "id": doc.id,
                "filename": doc.filename,
                "status": doc.status,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "file_size": getattr(doc, 'file_size', 0),
                "preserve": getattr(doc, 'preserve', False)
            } for doc in documents],
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": (total + limit - 1) // limit if total > 0 else 0
        }
    finally:
        db.close()


@router.get("/documents/stats", response_model=Dict[str, Any])
async def admin_document_stats(
    current_user: Dict[str, Any] = Depends(require_admin)
) -> Dict[str, Any]:
    """Get document statistics via admin interface."""
    from src.database.repository import DocumentRepository
    from src.database.connection import get_db_session

    db = next(get_db_session())
    doc_repo = DocumentRepository(db)

    try:
        stats = doc_repo.get_statistics()
        return {
            "total_documents": stats.get("total_documents", 0),
            "by_status": {
                "pending": stats.get("count_pending", 0),
                "indexing": stats.get("count_indexing", 0),
                "indexed": stats.get("count_indexed", 0),
                "error": stats.get("count_error", 0)
            },
            "by_type": stats.get("by_type", {}),
            "total_size_mb": stats.get("total_size_mb", 0),
            "timestamp": datetime.utcnow()
        }
    finally:
        db.close()


@router.post("/documents/upload", response_model=Dict[str, Any])
async def admin_upload_document(
    file: UploadFile = File(...),
    preserve: bool = Form(False),
    current_user: Dict[str, Any] = Depends(require_admin)
) -> Dict[str, Any]:
    """Upload document via admin interface."""
    from src.database.repository import DocumentRepository
    from src.database.connection import get_db_session
    from src.shared.models import validate_filename, sanitize_filename
    import shutil

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided"
        )

    # Validate the file
    if not validate_filename(file.filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type or filename"
        )

    db = next(get_db_session())
    doc_repo = DocumentRepository(db)

    try:
        # Create upload directory if needed
        upload_dir = Path(settings.upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize the filename
        clean_filename = sanitize_filename(file.filename)
        file_path = upload_dir / clean_filename

        # Save the file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Compute the hash
        import hashlib
        with open(file_path, "rb") as f:
            file_hash = hashlib.md5(f.read()).hexdigest()

        # Create the database record
        document = doc_repo.create(
            filename=clean_filename,
            file_hash=file_hash,
            path=str(file_path),
            preserve=preserve
        )

        return {
            "success": True,
            "message": "Document uploaded successfully",
            "document": {
                "id": document.id,
                "filename": document.filename,
                "status": document.status,
                "created_at": document.created_at.isoformat() if document.created_at else None
            },
            "timestamp": datetime.utcnow()
        }

    except Exception as e:
        logger.error(f"Upload error: {e}")
        # Clean up the file on error
        if 'file_path' in locals() and file_path.exists():
            file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )
    finally:
        db.close()


# ============= CONFIG ALIAS ENDPOINTS =============
# Aliases for frontend consistency

@router.get("/config", response_model=Dict[str, Any])
async def get_config_alias(
    config_repo: ConfigurationRepository = Depends(get_configuration_repository)
) -> Dict[str, Any]:
    """Alias for /configuration - for frontend consistency."""
    return await get_configuration(config_repo)


@router.put("/config", response_model=BaseResponse)
async def update_config_alias(
    config_updates: Dict[str, Any],
    current_user: Dict[str, Any] = Depends(require_admin),
    config_repo: ConfigurationRepository = Depends(get_configuration_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository)
) -> BaseResponse:
    """Alias for /configuration - for frontend consistency."""


@router.get("/metrics/chat", response_model=Dict[str, Any])
async def get_chat_metrics(
    current_user: Dict[str, Any] = Depends(require_admin)
) -> Dict[str, Any]:
    """
    Get chat system metrics for monitoring dashboard.

    Returns real-time metrics including:
    - Request volume in last hour
    - Average response time
    - Success rate
    - Error count
    - Active sessions estimate
    - Token usage statistics
    - Performance status assessment

    Args:
        current_user: Current authenticated admin user

    Returns:
        Dict containing chat metrics and performance indicators

    Raises:
        HTTPException: If user lacks admin privileges
    """
    try:
        # Import log_parser module to extract real metrics
        from ...utils.log_parser import get_chat_metrics

        # Get all metrics from logs
        metrics = get_chat_metrics()

        # Add timestamp
        metrics["timestamp"] = datetime.utcnow().isoformat() + "Z"

        logger.info("Chat metrics retrieved successfully from logs")
        return metrics

    except Exception as e:
        logger.error(f"Failed to get chat metrics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve chat metrics"
        )


@router.get("/analytics/usage", response_model=Dict[str, Any])
async def get_usage_analytics(
    current_user: Dict[str, Any] = Depends(require_admin)
) -> Dict[str, Any]:
    """
    Get comprehensive usage analytics for dashboard.

    Returns analytics data including:
    - Usage trends over multiple time periods
    - Document processing statistics
    - System resource utilization
    - User activity patterns
    - Growth metrics and comparisons

    Args:
        current_user: Current authenticated admin user

    Returns:
        Dict containing comprehensive usage analytics

    Raises:
        HTTPException: If user lacks admin privileges
    """
    try:
        # Import log_parser module to extract analytics
        from ...utils.log_parser import get_usage_analytics

        # Get all analytics from logs and database
        analytics = get_usage_analytics()

        # Add timestamp
        analytics["timestamp"] = datetime.utcnow().isoformat() + "Z"

        logger.info("Usage analytics retrieved successfully from logs and database")
        return analytics

    except Exception as e:
        logger.error(f"Failed to get usage analytics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve usage analytics"
        )


@router.get("/logs", response_model=Dict[str, Any])
async def get_system_logs(
    level: Optional[str] = Query(None, description="Log level filter (ALL, DEBUG, INFO, WARN, ERROR)"),
    source: Optional[str] = Query(None, description="Source filter (ALL, backend, frontend)"),
    module: Optional[str] = Query(None, description="Module name filter"),
    search: Optional[str] = Query(None, description="Text search in message"),
    since: Optional[str] = Query(None, description="ISO timestamp to filter logs since"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of logs to return"),
    current_user: Dict[str, Any] = Depends(require_admin)
) -> Dict[str, Any]:
    """
    Get filtered system logs from backend and frontend sources.

    This endpoint provides unified access to both backend application logs
    and frontend logs with advanced filtering capabilities.

    Query Parameters:
        level: Filter by log level (ALL, DEBUG, INFO, WARN, ERROR)
        source: Filter by source (ALL, backend, frontend)
        module: Filter by module name (partial match)
        search: Search text in log messages
        since: ISO timestamp to get logs since that time
        limit: Maximum number of logs to return (1-200)

    Returns:
        Dict containing filtered logs, count info, and metadata

    Raises:
        HTTPException: If log retrieval fails
    """
    try:
        # Import log reader utility
        from ...utils.logs_reader import get_logs, get_logs_summary

        # Get filtered logs
        logs, total_count = get_logs(
            level=level,
            source=source,
            module=module,
            search=search,
            since=since,
            limit=limit
        )

        # Get summary info
        summary = get_logs_summary()

        response = {
            "logs": logs,
            "total_count": total_count,
            "returned_count": len(logs),
            "has_more": total_count > limit,
            "filters_applied": {
                "level": level or "ALL",
                "source": source or "ALL",
                "module": module,
                "search": search,
                "since": since,
                "limit": limit
            },
            "summary": summary,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

        logger.info(f"System logs retrieved: {len(logs)} logs returned (filtered from {total_count} total)")
        return response

    except Exception as e:
        logger.error(f"Failed to get system logs: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve system logs"
        )


@router.post("/vector-store/rebuild", response_model=BaseResponse)
async def rebuild_vector_store(
    current_user: Dict[str, Any] = Depends(require_admin),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository)
) -> BaseResponse:
    """
    Force complete rebuild of the FAISS vector index.

    This will:
    1. Get vector store instance from dependencies
    2. Force optimization/rebuild to remove deleted entries
    3. Persist the rebuilt index to disk
    4. Clear related caches

    Args:
        current_user: Current authenticated admin user
        audit_repo: Audit log repository

    Returns:
        BaseResponse: Operation result with statistics

    Raises:
        HTTPException: If rebuild fails
    """
    try:
        # Import dependencies here to avoid circular imports
        from src.api.dependencies import get_vector_store

        # Get vector store instance (this will be injected manually)
        from src.database.connection import get_db_session
        from src.rag_core.implementations.faiss_store import FaissVectorStore
        from src.config import settings

        # Create vector store instance manually
        import os
        data_dir = settings.data_dir
        vector_store = FaissVectorStore(
            dimension=settings.embedding_dimension,
            index_path=os.path.join(data_dir, "faiss", "index.bin"),
            metadata_path=os.path.join(data_dir, "faiss", "metadata.pkl"),
            similarity_threshold=settings.similarity_threshold
        )

        # Get stats before rebuild
        stats_before = vector_store.get_stats()
        start_time = time.time()

        # Force rebuild with orphan cleanup
        rebuild_result = vector_store.rebuild_vector_store(force_rebuild=True, cleanup_orphans=True)

        # Get stats after rebuild
        stats_after = vector_store.get_stats()
        duration_ms = rebuild_result.get('duration_ms', (time.time() - start_time) * 1000)

        # Clear related caches to ensure fresh data
        from src.cache.lru_cache import cache_service, chat_cache_service
        cache_service.invalidate_all()
        chat_cache_service.invalidate_all()

        # Extract cleanup and rebuild information
        cleanup_result = rebuild_result.get('cleanup_result', {})
        orphans_cleaned = cleanup_result.get('cleaned_chunks', 0) if cleanup_result else 0
        deleted_removed = rebuild_result.get('deleted_chunks_removed', 0)
        rebuild_performed = rebuild_result.get('rebuild_performed', False)

        # Log rebuild action
        audit_repo.create_log(
            user_type="admin",
            action="vector_index_rebuild",
            details=f"FAISS index rebuilt - vectors: {stats_before['total_vectors']} → {stats_after['total_vectors']}, orphans cleaned: {orphans_cleaned}",
            ip_address="system",
            success=True,
            additional_data={
                "stats_before": stats_before,
                "stats_after": stats_after,
                "duration_ms": duration_ms,
                "rebuild_result": rebuild_result,
                "admin_user": current_user["sub"]
            }
        )

        logger.info(
            f"FAISS index rebuilt by admin {current_user['sub']}: "
            f"{stats_before['total_vectors']} → {stats_after['total_vectors']} vectors, "
            f"cleaned {orphans_cleaned} orphans, removed {deleted_removed} deleted chunks in {duration_ms:.1f}ms"
        )

        # Create informative message
        message_parts = [f"Vector index rebuilt successfully."]
        if orphans_cleaned > 0:
            message_parts.append(f"Cleaned {orphans_cleaned} orphaned chunks.")
        if deleted_removed > 0:
            message_parts.append(f"Removed {deleted_removed} deleted chunks.")
        if rebuild_performed:
            message_parts.append(f"Optimized from {stats_before['total_vectors']} to {stats_after['total_vectors']} vectors.")
        message_parts.append(f"Completed in {duration_ms:.0f}ms.")

        return BaseResponse(
            success=True,
            message=" ".join(message_parts),
            timestamp=datetime.utcnow()
        )

    except Exception as e:
        error_msg = f"Failed to rebuild vector index: {str(e)}"
        logger.error(error_msg)

        # Log failed rebuild attempt
        try:
            audit_repo.create_log(
                user_type="admin",
                action="vector_index_rebuild",
                details=f"FAISS index rebuild failed: {str(e)}",
                ip_address="system",
                success=False,
                additional_data={
                    "error": str(e),
                    "admin_user": current_user["sub"]
                }
            )
        except:
            pass  # Don't fail on audit log error

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_msg
        )