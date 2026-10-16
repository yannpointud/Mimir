"""
Administration endpoints: system information, caches, configuration, audit
trail, AI usage, logs and index maintenance.
"""

import logging
import platform
import sys
from datetime import timedelta
from typing import Any

import psutil
from fastapi import APIRouter, Depends, HTTPException, Query, status

from mimir.api.dependencies import (
    get_audit_log_repository,
    get_bm25_store,
    get_configuration_repository,
    get_document_repository,
    get_usage_repository,
    get_vector_store,
)
from mimir.auth.middleware import require_admin
from mimir.cache.lru_cache import cache_service, chat_cache_service
from mimir.config import settings
from mimir.database.repository import (
    AuditLogRepository,
    ConfigurationRepository,
    DocumentRepository,
    UsageRepository,
)
from mimir.email_service.smtp_client import email_service
from mimir.rag_core.implementations.bm25_store import Bm25LexicalStore
from mimir.rag_core.implementations.faiss_store import FaissVectorStore
from mimir.services import index_maintenance
from mimir.shared.clock import utc_now
from mimir.shared.constants import MASKED_VALUE, mask_secrets
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
from mimir.utils.logs_reader import get_logs, get_logs_summary

logger = logging.getLogger(__name__)

# Configuration keys an admin may update: only the daily spend cap is read at
# runtime (BudgetGuard reads it before falling back to settings.daily_budget_eur).
_WRITABLE_CONFIG_KEYS = frozenset({"daily_budget_eur"})

router = APIRouter(
    prefix="/admin",
    tags=["administration"],
    # Default-deny: every /admin route requires an admin, even one that forgets
    # to declare require_admin itself.
    dependencies=[Depends(require_admin)],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Admin privileges required"},
    },
)


@router.get("/system-info", response_model=dict[str, Any])
def get_system_info(current_user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    """Platform, hardware and application information."""
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
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
                "total": memory.total,
                "available": memory.available,
                "used": memory.used,
                "percent": memory.percent,
            },
            "disk": {
                "total": disk.total,
                "free": disk.free,
                "used": disk.used,
                "percent": disk.percent,
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
        "timestamp": utc_now(),
    }


def _cache_stats(stats: dict[str, Any]) -> AdminCacheStats:
    return AdminCacheStats(**stats, utilization=stats.get("utilization_percent", 0.0))


@router.get("/cache/stats", response_model=CacheStatsResponse)
async def get_cache_stats(
    current_user: dict[str, Any] = Depends(require_admin),
) -> CacheStatsResponse:
    """Statistics of the embedding and chat caches."""
    main_stats = cache_service.get_stats()
    chat_stats = chat_cache_service.get_stats()
    total_requests = main_stats["total_requests"] + chat_stats["total_requests"]
    total_hits = main_stats["hits"] + chat_stats["hits"]
    return CacheStatsResponse(
        main_cache=_cache_stats(main_stats),
        chat_cache=_cache_stats(chat_stats),
        global_stats=CacheGlobalStats(
            total_requests=total_requests,
            hit_ratio=total_hits / total_requests if total_requests else 0.0,
            total_hits=total_hits,
            total_misses=main_stats["misses"] + chat_stats["misses"],
        ),
        timestamp=utc_now(),
    )


@router.post("/cache/clear", response_model=BaseResponse)
def clear_cache(
    cache_type: str = Query("all", description="Cache type to clear (all, main, chat)"),
    current_user: dict[str, Any] = Depends(require_admin),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> BaseResponse:
    """Clear the main cache, the chat cache or both."""
    cleared_counts = {}
    if cache_type in ("all", "main"):
        cleared_counts["main_cache"] = cache_service.get_stats()["size"]
        cache_service.invalidate_all()
    if cache_type in ("all", "chat"):
        cleared_counts["chat_cache"] = chat_cache_service.get_stats()["size"]
        chat_cache_service.invalidate_all()

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
        timestamp=utc_now(),
    )


@router.get("/config", response_model=AdminConfigurationResponse)
def get_configuration(
    current_user: dict[str, Any] = Depends(require_admin),
    config_repo: ConfigurationRepository = Depends(get_configuration_repository),
) -> AdminConfigurationResponse:
    """Database and application configuration, every secret masked server-side."""
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
    return AdminConfigurationResponse(
        database_config=mask_secrets({item.key: item.value for item in config_repo.get_all()}),
        application_config=ApplicationConfig(**mask_secrets(app_config)),
        timestamp=utc_now(),
    )


@router.put("/config", response_model=BaseResponse)
def update_configuration(
    config_updates: dict[str, str],
    current_user: dict[str, Any] = Depends(require_admin),
    config_repo: ConfigurationRepository = Depends(get_configuration_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> BaseResponse:
    """Update the writable configuration keys."""
    # A masked value resubmitted by the frontend must neither overwrite the real
    # secret nor trip the allow-list check.
    config_updates = {k: v for k, v in config_updates.items() if v != MASKED_VALUE}
    invalid_keys = set(config_updates) - _WRITABLE_CONFIG_KEYS
    if invalid_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid configuration keys: {list(invalid_keys)}",
        )

    updated_items = []
    for key, value in config_updates.items():
        config_repo.set(key, value)
        updated_items.append(f"{key}={value}")

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
        timestamp=utc_now(),
    )


@router.get("/audit-log", response_model=AuditLogPage)
def get_audit_log(
    pagination: PaginationModel = Depends(),
    action_filter: str | None = Query(None, description="Filter by action type"),
    user_type_filter: str | None = Query(None, description="Filter by user type"),
    success_filter: bool | None = Query(None, description="Filter by success status"),
    days_back: int = Query(7, ge=1, le=90, description="Number of days to look back"),
    current_user: dict[str, Any] = Depends(require_admin),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> AuditLogPage:
    """Filtered audit trail (admin usernames, configuration values, client IPs)."""
    filters: dict[str, Any] = {"since_date": utc_now() - timedelta(days=days_back)}
    if action_filter:
        filters["action"] = action_filter
    if user_type_filter:
        filters["user_type"] = user_type_filter
    if success_filter is not None:
        filters["success"] = success_filter

    entries, total_count = audit_repo.get_logs_paginated(
        offset=pagination.offset, limit=pagination.limit, filters=filters
    )
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
        timestamp=utc_now(),
    )


@router.get("/usage", response_model=UsageResponse)
def get_usage(
    days_back: int = Query(30, ge=1, le=90, description="Number of days of history to return"),
    current_user: dict[str, Any] = Depends(require_admin),
    usage_repo: UsageRepository = Depends(get_usage_repository),
    config_repo: ConfigurationRepository = Depends(get_configuration_repository),
) -> UsageResponse:
    """Today's LLM spend per model, the daily history and the effective daily cap."""
    ledger = usage_repo.get_today_ledger()
    # Same effective cap as BudgetGuard: the admin override wins over the
    # settings default, so the gauge matches the cap the gate enforces.
    override = config_repo.get("daily_budget_eur")
    return UsageResponse(
        today_by_model=[ModelUsageToday(**row) for row in usage_repo.get_today_by_model()],
        history=[DailyModelUsage(**row) for row in usage_repo.get_daily_history(days_back)],
        spent_today_eur=ledger.spent_eur if ledger else 0.0,
        daily_budget_eur=float(override.value) if override else settings.daily_budget_eur,
        timestamp=utc_now(),
    )


@router.post("/test-email", response_model=BaseResponse)
async def test_email_service(
    test_email: str = Query(..., description="Email address to send test message to"),
    current_user: dict[str, Any] = Depends(require_admin),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> BaseResponse:
    """Send a test email through the configured SMTP server."""
    sent = await email_service.send_notification_email(
        to_email=test_email,
        subject="Mimir Email Service Test",
        message="This is a test email from the Mimir system. If you receive this, email service is working correctly.",
        is_html=False,
    )
    audit_repo.create_log(
        user_type="admin",
        action="email_service_test",
        details=f"Test email sent to {test_email}",
        ip_address="system",
        success=sent,
    )
    message = (
        f"Test email sent successfully to {test_email}"
        if sent
        else "Failed to send test email. Check email service configuration."
    )
    return BaseResponse(success=sent, message=message, timestamp=utc_now())


@router.get("/logs", response_model=dict[str, Any])
def get_system_logs(
    level: str | None = Query(None, description="Log level filter (ALL, DEBUG, INFO, WARN, ERROR)"),
    source: str | None = Query(None, description="Source filter (ALL, backend, frontend)"),
    module: str | None = Query(None, description="Module name filter"),
    search: str | None = Query(None, description="Text search in message"),
    since: str | None = Query(None, description="ISO timestamp to filter logs since"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of logs to return"),
    current_user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Backend and frontend log entries, filtered."""
    logs, total_count = get_logs(
        level=level, source=source, module=module, search=search, since=since, limit=limit
    )
    return {
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
        "summary": get_logs_summary(),
        "timestamp": utc_now().isoformat() + "Z",
    }


@router.post("/vector-store/rebuild", response_model=BaseResponse)
async def rebuild_vector_store(
    current_user: dict[str, Any] = Depends(require_admin),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    vector_store: FaissVectorStore = Depends(get_vector_store),
    bm25_store: Bm25LexicalStore = Depends(get_bm25_store),
    document_repo: DocumentRepository = Depends(get_document_repository),
) -> BaseResponse:
    """Rebuild the FAISS index without deleted and orphan chunks, then resync BM25.

    A failure is recorded in the audit trail before it propagates.
    """
    try:
        rebuild = await index_maintenance.rebuild_indexes(vector_store, bm25_store, document_repo)
    except Exception as e:
        index_maintenance.record_rebuild_failure(audit_repo, e, current_user["sub"])
        raise
    index_maintenance.record_rebuild(audit_repo, rebuild, current_user["sub"])
    return BaseResponse(success=True, message=rebuild.message(), timestamp=utc_now())
