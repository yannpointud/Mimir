"""
Administrative endpoints.

This module provides endpoints for system administration,
configuration management, and monitoring.
"""

from typing import Any
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Query,
    UploadFile,
    File,
    Form,
    Request,
    Response,
)
from datetime import datetime, timedelta
import logging


from src.auth.middleware import require_admin
from src.database.repository import (
    ConfigurationRepository,
    AuditLogRepository,
    UsageRepository,
    DocumentRepository,
)
from src.api.dependencies import (
    get_configuration_repository,
    get_audit_log_repository,
    get_usage_repository,
    get_vector_store,
    get_ingestion_processor,
    get_bm25_store,
    get_document_repository,
)
from src.api.middleware.rate_limit import limiter, get_client_identifier
from src.cache.lru_cache import cache_service, chat_cache_service
from src.email_service.smtp_client import email_service
from src.rag_core.implementations.faiss_store import FaissVectorStore
from src.rag_core.implementations.bm25_store import Bm25LexicalStore
from src.shared.models import (
    AdminCacheStats,
    AdminConfigurationResponse,
    AdminDocumentList,
    AdminDocumentStats,
    AdminDocumentSummary,
    AdminUploadResponse,
    ApplicationConfig,
    AuditLogEntry,
    AuditLogFilters,
    AuditLogPage,
    BaseResponse,
    CacheGlobalStats,
    CacheStatsResponse,
    DailyModelUsage,
    DocumentStatusCounts,
    ModelUsageToday,
    PaginationModel,
    UploadedDocument,
    UsageResponse,
)
from src.shared.constants import MASKED_VALUE, mask_secrets
from src.api.responses import rejection_to_http
from src.services import index_maintenance
from src.services.document_upload import DocumentUpload, UploadPolicy
from src.services.errors import RequestRejectedError
from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["administration"],
    # Default-deny guard (same pattern as documents.py): every /admin route
    # requires an authenticated admin even if an endpoint forgets to declare
    # its own require_admin dependency.
    dependencies=[Depends(require_admin)],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Admin privileges required"},
    },
)


@router.get("/system-info", response_model=dict[str, Any])
async def get_system_info(current_user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    """Get comprehensive system information."""
    try:
        import psutil
        import platform
        import sys

        # System information
        system_info = {
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "python_version": sys.version,
            },
            "hardware": {
                "cpu_count": psutil.cpu_count(),
                "cpu_percent": psutil.cpu_percent(),
                "memory": {
                    "total": psutil.virtual_memory().total,
                    "available": psutil.virtual_memory().available,
                    "used": psutil.virtual_memory().used,
                    "percent": psutil.virtual_memory().percent,
                },
                "disk": {
                    "total": psutil.disk_usage("/").total,
                    "free": psutil.disk_usage("/").free,
                    "used": psutil.disk_usage("/").used,
                    "percent": psutil.disk_usage("/").percent,
                },
            },
            "application": {
                "version": settings.api_version,
                "environment": "production" if settings.is_production else "development",
                "data_directory": settings.data_dir,
                "upload_directory": settings.upload_dir,
                "database_url": settings.database_url.replace(
                    settings.database_url.split("/")[-1], "***"
                )
                if hasattr(settings, "database_url")
                else "not configured",
            },
            "services": {
                "llm_provider": settings.llm_provider,
                "vector_store": settings.vector_store_type,
                "cache_enabled": True,  # Always enabled in this implementation
                "email_configured": email_service.get_configuration_status()["configured"],
                "watch_folder": getattr(settings, "watch_folder", "not configured"),
            },
            "timestamp": datetime.utcnow(),
        }

        logger.debug("System information retrieved successfully")
        return system_info

    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Error retrieving system info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve system information",
        ) from e


@router.get("/cache/stats", response_model=CacheStatsResponse)
async def get_cache_stats(
    current_user: dict[str, Any] = Depends(require_admin),
) -> CacheStatsResponse:
    """Get cache service statistics."""
    try:
        main_cache_stats = cache_service.get_stats()
        chat_cache_stats = chat_cache_service.get_stats()

        # Adapt data for the frontend
        def adapt_cache_stats(stats: dict[str, Any]) -> AdminCacheStats:
            # Add 'utilization' expected by the frontend
            return AdminCacheStats(**stats, utilization=stats.get("utilization_percent", 0.0))

        # Compute global stats for the frontend
        total_requests = main_cache_stats["total_requests"] + chat_cache_stats["total_requests"]
        total_hits = main_cache_stats["hits"] + chat_cache_stats["hits"]
        hit_ratio = (total_hits / max(1, total_requests)) if total_requests > 0 else 0.0

        return CacheStatsResponse(
            main_cache=adapt_cache_stats(main_cache_stats),
            chat_cache=adapt_cache_stats(chat_cache_stats),
            global_stats=CacheGlobalStats(
                total_requests=total_requests,
                hit_ratio=hit_ratio,
                total_hits=total_hits,
                total_misses=main_cache_stats["misses"] + chat_cache_stats["misses"],
            ),
            timestamp=datetime.utcnow(),
        )

    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Error retrieving cache stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve cache statistics",
        ) from e


@router.post("/cache/clear", response_model=BaseResponse)
async def clear_cache(
    cache_type: str = Query("all", description="Cache type to clear (all, main, chat)"),
    current_user: dict[str, Any] = Depends(require_admin),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> BaseResponse:
    """Clear cache entries."""
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
                "admin_user": current_user["sub"],
            },
        )

        total_cleared = sum(cleared_counts.values())
        logger.info(
            f"Cache cleared by admin {current_user['sub']}: {cache_type}, {total_cleared} entries"
        )

        return BaseResponse(
            success=True,
            message=f"Cache cleared successfully. Removed {total_cleared} entries from {cache_type} cache(s).",
            timestamp=datetime.utcnow(),
        )

    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Error clearing cache: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to clear cache"
        ) from e


@router.get("/configuration", response_model=AdminConfigurationResponse)
async def get_configuration(
    current_user: dict[str, Any] = Depends(require_admin),
    config_repo: ConfigurationRepository = Depends(get_configuration_repository),
) -> AdminConfigurationResponse:
    """Get system configuration settings, with every secret masked server-side."""
    try:
        # Get all configuration from database
        db_config = config_repo.get_all()

        # Combine with application settings (sensitive values masked below)
        app_config = {
            "api_version": settings.api_version,
            "max_chunk_size": settings.max_chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "embedding_dimension": settings.embedding_dimension,
            "cache_max_size": getattr(settings, "cache_max_size", 100),
            "cache_ttl_seconds": getattr(settings, "cache_ttl_seconds", 3600),
            "supported_file_extensions": list(getattr(settings, "supported_file_extensions", [])),
            "max_file_size_mb": getattr(settings, "max_file_size_mb", 100),
            "jwt_expiration_hours": settings.jwt_expiration_hours,
            # LLM Configuration (with sensitive data)
            "llm_provider": settings.llm_provider,
            "mistral_api_key": settings.mistral_api_key,
            "mistral_model": settings.mistral_model,
            "mistral_embedding_model": settings.mistral_embedding_model,
        }

        # Server-side masking: secrets must never leave the backend in clear text
        return AdminConfigurationResponse(
            database_config=mask_secrets({item.key: item.value for item in db_config}),
            application_config=ApplicationConfig(**mask_secrets(app_config)),
            timestamp=datetime.utcnow(),
        )

    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Error retrieving configuration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve configuration",
        ) from e


@router.put("/configuration", response_model=BaseResponse)
async def update_configuration(
    config_updates: dict[str, str],
    current_user: dict[str, Any] = Depends(require_admin),
    config_repo: ConfigurationRepository = Depends(get_configuration_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> BaseResponse:
    """Update system configuration settings."""
    try:
        # Drop any masked value resubmitted by the frontend: a mask must never
        # overwrite the real secret nor trigger the allow-list validation
        config_updates = {k: v for k, v in config_updates.items() if v != MASKED_VALUE}

        # Validate configuration keys (only allow certain keys to be updated)
        allowed_keys = {
            "maintenance_mode",
            "max_concurrent_ingestions",
            "ingestion_retry_limit",
            "email_escalation_enabled",
            "chat_rate_limit_per_minute",
            "auto_delete_failed_documents",
            "vector_search_threshold",
            # Hot-reloadable daily spend cap: BudgetGuard._effective_cap
            # reads this key from the configuration table before falling back
            # to settings.daily_budget_eur.
            "daily_budget_eur",
        }

        invalid_keys = set(config_updates.keys()) - allowed_keys
        if invalid_keys:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid configuration keys: {list(invalid_keys)}",
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
            additional_data={"updates": config_updates, "admin_user": current_user["sub"]},
        )

        logger.info(f"Configuration updated by admin {current_user['sub']}: {updated_items}")

        return BaseResponse(
            success=True,
            message=f"Configuration updated successfully. {len(updated_items)} items changed.",
            timestamp=datetime.utcnow(),
        )

    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Error updating configuration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update configuration",
        ) from e


@router.get("/audit-log", response_model=AuditLogPage)
async def get_audit_log(
    pagination: PaginationModel = Depends(),
    action_filter: str | None = Query(None, description="Filter by action type"),
    user_type_filter: str | None = Query(None, description="Filter by user type"),
    success_filter: bool | None = Query(None, description="Filter by success status"),
    days_back: int = Query(7, ge=1, le=90, description="Number of days to look back"),
    current_user: dict[str, Any] = Depends(require_admin),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> AuditLogPage:
    """Get audit log entries with filtering.

    The audit log exposes admin usernames, configuration update values and
    client IPs: it must never be readable anonymously (explicit guard kept
    in addition to the router-level default-deny).
    """
    try:
        # Build filters
        filters: dict[str, Any] = {}
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
            offset=pagination.offset, limit=pagination.limit, filters=filters
        )

        # Convert to response format
        log_entries = [
            AuditLogEntry(
                id=entry.id,
                timestamp=entry.created_at,
                user_type=entry.user_type,
                action=entry.action,
                details=entry.details,
                ip_address=entry.ip_address,
                success=entry.success,
                # additional_data is accepted by create_log for compatibility
                # but not persisted on the AuditLog model; guard the read so a
                # missing column cannot turn the audit-log GET into a 500.
                additional_data=getattr(entry, "additional_data", None),
            )
            for entry in entries
        ]

        return AuditLogPage(
            entries=log_entries,
            total=total_count,
            offset=pagination.offset,
            limit=pagination.limit,
            has_more=pagination.offset + len(log_entries) < total_count,
            filters=AuditLogFilters(
                action=action_filter,
                user_type=user_type_filter,
                success=success_filter,
                days_back=days_back,
            ),
            timestamp=datetime.utcnow(),
        )

    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Error retrieving audit log: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve audit log"
        ) from e


@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    days_back: int = Query(30, ge=1, le=90, description="Number of days of history to return"),
    current_user: dict[str, Any] = Depends(require_admin),
    usage_repo: UsageRepository = Depends(get_usage_repository),
    config_repo: ConfigurationRepository = Depends(get_configuration_repository),
) -> UsageResponse:
    """Get today's per-model LLM spend, the daily history, and today's spend
    vs the daily budget cap, for the admin cost dashboard.

    Internal cost data must never be readable anonymously (explicit guard
    kept in addition to the router-level default-deny, same convention as
    get_audit_log). ``days_back`` is bounded to cap the query window. The
    cap is the settings default or the hot Admin override.
    """
    try:
        today_by_model = usage_repo.get_today_by_model()
        history = usage_repo.get_daily_history(days_back)
        ledger = usage_repo.get_today_ledger()

        # Effective daily cap: mirror BudgetGuard._effective_cap() so the
        # dashboard gauge always matches the cap the gate actually enforces
        # (hot Admin override for 'daily_budget_eur' wins over the .env
        # default). Returning the raw settings value here would show a stale
        # cap while requests are already being rejected with 429
        # budget_exceeded against the override.
        override = config_repo.get("daily_budget_eur")
        effective_cap = float(override.value) if override is not None else settings.daily_budget_eur

        return UsageResponse(
            today_by_model=[ModelUsageToday(**row) for row in today_by_model],
            history=[DailyModelUsage(**row) for row in history],
            spent_today_eur=ledger.spent_eur if ledger else 0.0,
            daily_budget_eur=effective_cap,
            timestamp=datetime.utcnow(),
        )

    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Error retrieving usage data: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve usage data",
        ) from e


@router.post("/maintenance", response_model=BaseResponse)
async def toggle_maintenance_mode(
    enabled: bool = Query(..., description="Enable or disable maintenance mode"),
    message: str | None = Query(None, description="Optional maintenance message"),
    current_user: dict[str, Any] = Depends(require_admin),
    config_repo: ConfigurationRepository = Depends(get_configuration_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> BaseResponse:
    """Toggle system maintenance mode."""
    try:
        # Update maintenance mode configuration
        config_repo.set("maintenance_mode", "true" if enabled else "false")

        if message:
            config_repo.set("maintenance_message", message)

        # Log maintenance mode change
        audit_repo.create_log(
            user_type="admin",
            action="maintenance_mode_toggle",
            details=f"Maintenance mode {'enabled' if enabled else 'disabled'}"
            + (f": {message}" if message else ""),
            ip_address="system",
            success=True,
            additional_data={
                "enabled": enabled,
                "message": message,
                "admin_user": current_user["sub"],
            },
        )

        status_word = "enabled" if enabled else "disabled"
        logger.info(f"Maintenance mode {status_word} by admin {current_user['sub']}")

        return BaseResponse(
            success=True,
            message=f"Maintenance mode {status_word} successfully"
            + (f": {message}" if message else ""),
            timestamp=datetime.utcnow(),
        )

    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Error toggling maintenance mode: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to toggle maintenance mode",
        ) from e


@router.post("/test-email", response_model=BaseResponse)
async def test_email_service(
    test_email: str = Query(..., description="Email address to send test message to"),
    current_user: dict[str, Any] = Depends(require_admin),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> BaseResponse:
    """Test email service configuration."""
    try:
        # Send test email
        success = await email_service.send_notification_email(
            to_email=test_email,
            subject="Mimir Email Service Test",
            message="This is a test email from the Mimir system. If you receive this, email service is working correctly.",
            is_html=False,
        )

        # Log test email attempt
        audit_repo.create_log(
            user_type="admin",
            action="email_service_test",
            details=f"Test email sent to {test_email}",
            ip_address="system",
            success=success,
            additional_data={"test_email": test_email, "admin_user": current_user["sub"]},
        )

        if success:
            return BaseResponse(
                success=True,
                message=f"Test email sent successfully to {test_email}",
                timestamp=datetime.utcnow(),
            )
        else:
            return BaseResponse(
                success=False,
                message="Failed to send test email. Check email service configuration.",
                timestamp=datetime.utcnow(),
            )

    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Email service test error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Email service test failed"
        ) from e


# ============= DOCUMENT MANAGEMENT ENDPOINTS =============
# Document endpoints added for frontend consistency


@router.get("/documents", response_model=AdminDocumentList)
async def admin_list_documents(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    status_filter: str | None = Query(None, description="Filter by document status"),
    search: str | None = Query(None, description="Search in filenames"),
    current_user: dict[str, Any] = Depends(require_admin),
) -> AdminDocumentList:
    """List documents via admin interface."""
    # Import here to avoid circular imports
    from src.database.repository import DocumentRepository

    # Use a new repository instance
    from src.database.connection import get_db_session

    db = next(get_db_session())
    doc_repo = DocumentRepository(db)

    try:
        # Compute offset
        offset = (page - 1) * limit

        # Retrieve documents with filters
        documents = doc_repo.get_all(offset=offset, limit=limit, order_by="created_at")

        # Count total (simple approximation)
        total = len(doc_repo.get_all())

        return AdminDocumentList(
            documents=[
                AdminDocumentSummary(
                    id=doc.id,
                    filename=doc.filename,
                    status=doc.status,
                    created_at=doc.created_at.isoformat() if doc.created_at else None,
                    file_size=getattr(doc, "file_size", 0),
                    preserve=getattr(doc, "preserve", False),
                )
                for doc in documents
            ],
            total=total,
            page=page,
            limit=limit,
            total_pages=(total + limit - 1) // limit if total > 0 else 0,
        )
    finally:
        db.close()


@router.get("/documents/stats", response_model=AdminDocumentStats)
async def admin_document_stats(
    current_user: dict[str, Any] = Depends(require_admin),
) -> AdminDocumentStats:
    """Get document statistics via admin interface."""
    from src.database.repository import DocumentRepository
    from src.database.connection import get_db_session

    db = next(get_db_session())
    doc_repo = DocumentRepository(db)

    try:
        stats = doc_repo.get_statistics()
        return AdminDocumentStats(
            total_documents=stats.get("total_documents", 0),
            by_status=DocumentStatusCounts(
                pending=stats.get("count_pending", 0),
                indexing=stats.get("count_indexing", 0),
                indexed=stats.get("count_indexed", 0),
                error=stats.get("count_error", 0),
            ),
            by_type=stats.get("by_type", {}),
            total_size_mb=stats.get("total_size_mb", 0),
            timestamp=datetime.utcnow(),
        )
    finally:
        db.close()


@router.post("/documents/upload", response_model=AdminUploadResponse)
# Same upload limit as /documents/upload: this duplicated admin
# route would otherwise be a trivial bypass of the upload rate limit.
# `request` is required by slowapi (import-time error without it) and
# `response` lets slowapi inject the X-RateLimit-* headers on the returned
# model (it only adds them itself to a Response object).
@limiter.limit(
    lambda: f"{settings.rate_limit_upload_per_minute}/minute", key_func=get_client_identifier
)
async def admin_upload_document(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    preserve: bool = Form(False),
    current_user: dict[str, Any] = Depends(require_admin),
    ingestion_processor=Depends(get_ingestion_processor),
) -> AdminUploadResponse:
    """Upload document via admin interface.

    Shares the /documents/upload pipeline, but accepts any extension, writes
    no audit event, uses its own database session and removes the stored
    file on an unexpected error.
    """
    from src.database.repository import DocumentRepository
    from src.database.connection import get_db_session

    upload = DocumentUpload(file, _admin_upload_policy())
    try:
        upload.check_name_and_size()
    except RequestRejectedError as e:
        raise rejection_to_http(e) from e

    db = next(get_db_session())
    doc_repo = DocumentRepository(db)
    try:
        document = await upload.run(doc_repo, ingestion_processor, preserve, current_user)
        return AdminUploadResponse(
            success=True,
            message="Document uploaded successfully",
            document=UploadedDocument(
                id=document.id,
                filename=document.filename,
                status=document.status,
                created_at=document.created_at.isoformat() if document.created_at else None,
            ),
            timestamp=datetime.utcnow(),
        )
    except RequestRejectedError as e:
        # Intentional client errors (e.g. 409 duplicate) keep their status
        raise rejection_to_http(e) from e
    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Upload error: {e}")
        upload.discard_stored_file()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Upload failed"
        ) from e
    finally:
        db.close()


def _admin_upload_policy() -> UploadPolicy:
    return UploadPolicy(
        upload_dir=settings.upload_dir,
        max_file_size_mb=settings.max_file_size_mb,
        invalid_filename_detail="Invalid file type or filename",
        prepare_dir_first=True,
    )


# ============= CONFIG ALIAS ENDPOINTS =============
# Aliases for frontend consistency


@router.get("/config", response_model=AdminConfigurationResponse)
async def get_config_alias(
    current_user: dict[str, Any] = Depends(require_admin),
    config_repo: ConfigurationRepository = Depends(get_configuration_repository),
) -> AdminConfigurationResponse:
    """Alias for /configuration - for frontend consistency."""
    return await get_configuration(current_user, config_repo)


@router.put("/config", response_model=BaseResponse)
async def update_config_alias(
    config_updates: dict[str, str],
    current_user: dict[str, Any] = Depends(require_admin),
    config_repo: ConfigurationRepository = Depends(get_configuration_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> BaseResponse:
    """Alias for /configuration - for frontend consistency."""
    return await update_configuration(config_updates, current_user, config_repo, audit_repo)


@router.get("/metrics/chat", response_model=dict[str, Any])
async def get_chat_metrics(current_user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    """Get chat system metrics for monitoring dashboard.

    Returns real-time metrics including:
    - Request volume in last hour
    - Average response time
    - Success rate
    - Error count
    - Active sessions estimate
    - Token usage statistics
    - Performance status assessment
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

    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Failed to get chat metrics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve chat metrics",
        ) from e


@router.get("/analytics/usage", response_model=dict[str, Any])
async def get_usage_analytics(
    current_user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Get comprehensive usage analytics for dashboard.

    Returns analytics data including:
    - Usage trends over multiple time periods
    - Document processing statistics
    - System resource utilization
    - User activity patterns
    - Growth metrics and comparisons
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

    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Failed to get usage analytics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve usage analytics",
        ) from e


@router.get("/logs", response_model=dict[str, Any])
async def get_system_logs(
    level: str | None = Query(None, description="Log level filter (ALL, DEBUG, INFO, WARN, ERROR)"),
    source: str | None = Query(None, description="Source filter (ALL, backend, frontend)"),
    module: str | None = Query(None, description="Module name filter"),
    search: str | None = Query(None, description="Text search in message"),
    since: str | None = Query(None, description="ISO timestamp to filter logs since"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of logs to return"),
    current_user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Get filtered system logs from backend and frontend sources.

    This endpoint provides unified access to both backend application logs
    and frontend logs with advanced filtering capabilities.
    """
    try:
        # Import log reader utility
        from ...utils.logs_reader import get_logs, get_logs_summary

        # Get filtered logs
        logs, total_count = get_logs(
            level=level, source=source, module=module, search=search, since=since, limit=limit
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
                "limit": limit,
            },
            "summary": summary,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

        logger.info(
            f"System logs retrieved: {len(logs)} logs returned (filtered from {total_count} total)"
        )
        return response

    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        logger.error(f"Failed to get system logs: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve system logs",
        ) from e


@router.post("/vector-store/rebuild", response_model=BaseResponse)
async def rebuild_vector_store(
    current_user: dict[str, Any] = Depends(require_admin),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    vector_store: FaissVectorStore = Depends(get_vector_store),
    bm25_store: Bm25LexicalStore = Depends(get_bm25_store),
    document_repo: DocumentRepository = Depends(get_document_repository),
) -> BaseResponse:
    """Force complete rebuild of the FAISS vector index.

    Optimizes FAISS (dropping deleted entries and orphan chunks of documents
    missing from ``document_repo``), persists it, resyncs the BM25 lexical
    index from the optimized FAISS snapshot so no ghost chunk survives, and
    clears the caches. ``vector_store`` and ``bm25_store`` are the shared
    singletons used by the chat and documents endpoints.
    """
    try:
        rebuild = await index_maintenance.rebuild_indexes(vector_store, bm25_store, document_repo)
        index_maintenance.record_rebuild(audit_repo, rebuild, current_user["sub"])
        return BaseResponse(success=True, message=rebuild.message(), timestamp=datetime.utcnow())

    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        # Full detail goes to the logs only; the client gets a generic
        # message (exception text may contain file paths or FAISS internals).
        logger.error(f"Failed to rebuild vector index: {str(e)}")
        index_maintenance.record_rebuild_failure(audit_repo, e, current_user["sub"])
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Vector index rebuild failed"
        ) from e
