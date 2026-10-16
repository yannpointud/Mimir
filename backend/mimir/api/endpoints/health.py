"""
Health check endpoints.

This module provides system health monitoring endpoints for
checking the status of various system components.
"""

import logging
import os
import shutil
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from mimir.cache.lru_cache import cache_service, chat_cache_service
from mimir.config import settings
from mimir.database.connection import get_db_session
from mimir.database.models import Document
from mimir.email_service.smtp_client import email_service
from mimir.shared.clock import utc_now
from mimir.shared.models import HealthCheckResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/health",
    tags=["health"],
    responses={
        503: {"description": "Service unavailable - one or more components unhealthy"},
    },
)


@router.get("/", response_model=HealthCheckResponse)
async def health_check(
    response: Response, db: Session = Depends(get_db_session)
) -> HealthCheckResponse:
    """Comprehensive health check of all system components."""
    health_status: dict[str, Any] = {
        "status": "healthy",
        "timestamp": utc_now(),
        "version": settings.api_version,
        "environment": "production" if settings.is_production else "development",
        "checks": {},
    }

    # Database health check
    db_healthy = await _check_database_health(db)
    health_status["checks"]["database"] = db_healthy

    # Vector store health check (placeholder for now)
    vector_store_healthy = await _check_vector_store_health()
    health_status["checks"]["vector_store"] = vector_store_healthy

    # LLM API health check (placeholder for now)
    llm_healthy = await _check_llm_health()
    health_status["checks"]["llm_api"] = llm_healthy

    # Cache health check
    cache_healthy = await _check_cache_health()
    health_status["checks"]["cache"] = cache_healthy

    # Email service health check
    email_healthy = await _check_email_health()
    health_status["checks"]["email_service"] = email_healthy

    # Determine overall health
    unhealthy_checks = [
        name for name, check in health_status["checks"].items() if not check.get("healthy", False)
    ]

    if unhealthy_checks:
        health_status["status"] = "unhealthy"
        health_status["unhealthy_components"] = unhealthy_checks

    # Log health check results
    if health_status["status"] == "healthy":
        logger.debug("Health check passed - all systems operational")
    else:
        logger.warning(f"Health check failed - unhealthy components: {unhealthy_checks}")

    # Propagate an unhealthy state through the HTTP status code so
    # Docker healthchecks / reverse proxies / load balancers that rely
    # on the status code (not the body) can detect the failure.
    if health_status["status"] != "healthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthCheckResponse(**health_status)


@router.get("/database", response_model=dict[str, Any])
async def database_health(db: Session = Depends(get_db_session)) -> dict[str, Any]:
    """Database-specific health check."""
    return await _check_database_health(db)


@router.get("/cache", response_model=dict[str, Any])
async def cache_health() -> dict[str, Any]:
    """Cache service health check."""
    return await _check_cache_health()


@router.get("/disk-usage", response_model=dict[str, Any])
def disk_usage() -> dict[str, Any]:
    """Disk usage of the data directories."""
    data_dirs = {
        "data_dir": settings.data_dir,
        "upload_dir": settings.upload_dir,
        "faiss_index_dir": os.path.dirname(settings.faiss_index_path),
    }
    usage_info: dict[str, Any] = {}
    for name, path in data_dirs.items():
        try:
            total, used, free = shutil.disk_usage(path)
        except OSError as e:
            usage_info[name] = {"path": path, "error": str(e)}
            continue
        usage_info[name] = {
            "path": path,
            "total_gb": round(total / (1024**3), 2),
            "used_gb": round(used / (1024**3), 2),
            "free_gb": round(free / (1024**3), 2),
            "usage_percent": round((used / total) * 100, 1),
        }
    return {"healthy": True, "disk_usage": usage_info, "timestamp": utc_now()}


async def _check_database_health(db: Session) -> dict[str, Any]:
    """Run a query on the documents table; a database error is reported as unhealthy."""
    try:
        doc_count = db.query(Document).count()
    except SQLAlchemyError as e:
        logger.error(f"Database health check failed: {e}")
        return {"healthy": False, "connection": "failed", "error": str(e)}
    return {"healthy": True, "connection": "ok", "document_count": doc_count}


async def _check_vector_store_health() -> dict[str, Any]:
    """Check that the FAISS files are both present or both absent.

    A pure file-existence check: it takes no FAISS lock and stays non-blocking.
    """
    index_exists = os.path.exists(settings.faiss_index_path)
    metadata_exists = os.path.exists(settings.faiss_metadata_path)
    if index_exists and metadata_exists:
        return {"healthy": True, "index_file": "exists", "metadata_file": "exists"}
    if not index_exists and not metadata_exists:
        return {
            "healthy": True,
            "index_file": "not_initialized",
            "metadata_file": "not_initialized",
            "note": "Vector store not initialized yet - normal for new installation",
        }
    return {
        "healthy": False,
        "index_file": "exists" if index_exists else "missing",
        "metadata_file": "exists" if metadata_exists else "missing",
        "error": "Inconsistent vector store state",
    }


async def _check_llm_health() -> dict[str, Any]:
    """Report whether the LLM API key is configured (no live API call)."""
    llm_configured = bool(settings.mistral_api_key)
    return {
        "healthy": llm_configured,
        "api_configured": llm_configured,
        "provider": "mistral",
        "model": settings.mistral_model if llm_configured else None,
        "note": "API key configured" if llm_configured else "API key not configured",
    }


async def _check_cache_health() -> dict[str, Any]:
    """Write, read back and delete a probe entry in the main cache."""
    test_key = "health_check_test"
    cache_service.set(test_key, "test_data", ttl=5)
    round_trip_ok = cache_service.get(test_key) == "test_data"
    cache_service.delete(test_key)
    return {
        "healthy": round_trip_ok,
        "test": "passed" if round_trip_ok else "value mismatch",
        "main_cache": cache_service.get_stats(),
        "chat_cache": chat_cache_service.get_stats(),
    }


async def _check_email_health() -> dict[str, Any]:
    """Report whether the SMTP settings are complete."""
    config_status = email_service.get_configuration_status()
    return {
        "healthy": config_status["configured"],
        "configuration": config_status,
        "note": "Email service configured"
        if config_status["configured"]
        else "Email service not configured",
    }


@router.get("/live")
async def liveness() -> dict[str, str]:
    """Liveness probe.

    Pure process check: returns 200 as long as the ASGI worker can execute
    Python. It performs no dependency I/O (no DB session, no FAISS, no Mistral)
    so a downstream outage (including a Mistral rate-limit/outage) can never
    fail this probe. This is the target of the container HEALTHCHECK.
    """
    return {"status": "alive"}


@router.get("/ready")
async def readiness(response: Response, db: Session = Depends(get_db_session)) -> dict[str, Any]:
    """
    Readiness probe.

    Aggregates the cheap in-process dependency checks (database, vector store,
    LLM API configuration) by reusing the existing `_check_*_health` helpers.
    Sets HTTP 503 when any dependency is unhealthy so proxies / load balancers
    stop routing traffic until the process is ready.

    `_check_llm_health` only reads `bool(settings.mistral_api_key)` and issues
    no live Mistral call, so readiness stays cheap and cannot amplify probe
    traffic into free-tier API load. A Mistral failure surfaces only through
    `llm_api` here and never affects `/live`.

    The payload carries only component names + boolean health + a coarse status
    (no secret values, no connection strings) to avoid information disclosure.

    Returns:
        dict: {"status": "ready"|"not_ready", "checks": {...}, "unhealthy": [...]}
    """
    checks = {
        "database": await _check_database_health(db),
        "vector_store": await _check_vector_store_health(),
        "llm_api": await _check_llm_health(),
    }

    unhealthy = [name for name, check in checks.items() if not check.get("healthy", False)]

    if unhealthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "not_ready" if unhealthy else "ready",
        "checks": checks,
        "unhealthy": unhealthy,
    }
