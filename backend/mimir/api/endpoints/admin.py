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
)
from datetime import datetime, timedelta
import logging


from mimir.auth.middleware import require_admin
from mimir.database.repository import (
    ConfigurationRepository,
    AuditLogRepository,
    UsageRepository,
    DocumentRepository,
)
from mimir.api.dependencies import (
    get_configuration_repository,
    get_audit_log_repository,
    get_usage_repository,
    get_vector_store,
    get_bm25_store,
    get_document_repository,
)
from mimir.cache.lru_cache import cache_service, chat_cache_service
from mimir.email_service.smtp_client import email_service
from mimir.rag_core.implementations.faiss_store import FaissVectorStore
from mimir.rag_core.implementations.bm25_store import Bm25LexicalStore
from mimir.shared.models import (
    AdminCacheStats,
    AdminConfigurationResponse,
    ApplicationConfig,
    AuditLogEntry,
    AuditLogFilters,
    AuditLogPage,
    BaseResponse,
    CacheGlobalStats,
    CacheStatsResponse,
    DailyModelUsage,
    ModelUsageToday,
    PaginationModel,
    UsageResponse,
)
from mimir.shared.constants import MASKED_VALUE, mask_secrets
from mimir.services import index_maintenance
from mimir.config import settings

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
                ),
            },
            "services": {
                "email_configured": email_service.get_configuration_status()["configured"],
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


@router.get("/config", response_model=AdminConfigurationResponse)
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
            "supported_file_extensions": sorted(settings.supported_file_extensions),
            "max_file_size_mb": settings.max_file_size_mb,
            "jwt_expiration_hours": settings.jwt_expiration_hours,
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


@router.put("/config", response_model=BaseResponse)
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

        # Only keys the application reads at runtime may be updated: the daily
        # spend cap, which BudgetGuard reads before falling back to
        # settings.daily_budget_eur.
        allowed_keys = {"daily_budget_eur"}

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
        from mimir.utils.logs_reader import get_logs, get_logs_summary

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
