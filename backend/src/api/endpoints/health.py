"""
Health check endpoints.

This module provides system health monitoring endpoints for
checking the status of various system components.
"""

from datetime import datetime
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session
from sqlalchemy import text
import logging

from src.database.connection import get_db_session
from src.shared.models import HealthCheckResponse
from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/health",
    tags=["health"],
    responses={
        503: {"description": "Service unavailable - one or more components unhealthy"},
    }
)


@router.get("/", response_model=HealthCheckResponse)
async def health_check(
    response: Response,
    db: Session = Depends(get_db_session)
) -> HealthCheckResponse:
    """
    Comprehensive health check of all system components.

    Returns:
        HealthCheckResponse: Overall system health status
    """
    try:
        health_status = {
            "status": "healthy",
            "timestamp": datetime.utcnow(),
            "version": settings.api_version,
            "environment": "production" if settings.is_production else "development",
            "checks": {}
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
            name for name, check in health_status["checks"].items()
            if not check.get("healthy", False)
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

    except Exception as e:
        logger.error(f"Health check error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Health check failed due to internal error"
        )


@router.get("/database", response_model=Dict[str, Any])
async def database_health(
    db: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    Database-specific health check.

    Returns:
        dict: Database health information
    """
    return await _check_database_health(db)


@router.get("/cache", response_model=Dict[str, Any])
async def cache_health() -> Dict[str, Any]:
    """
    Cache service health check.

    Returns:
        dict: Cache health information
    """
    return await _check_cache_health()


@router.get("/disk-usage", response_model=Dict[str, Any])
async def disk_usage() -> Dict[str, Any]:
    """
    Disk usage information for data directories.

    Returns:
        dict: Disk usage statistics
    """
    import shutil
    import os

    try:
        data_dirs = {
            "data_dir": settings.data_dir,
            "upload_dir": settings.upload_dir,
            "faiss_index_dir": os.path.dirname(settings.faiss_index_path)
        }

        usage_info = {}

        for name, path in data_dirs.items():
            try:
                if os.path.exists(path):
                    total, used, free = shutil.disk_usage(path)
                    usage_info[name] = {
                        "path": path,
                        "total_gb": round(total / (1024**3), 2),
                        "used_gb": round(used / (1024**3), 2),
                        "free_gb": round(free / (1024**3), 2),
                        "usage_percent": round((used / total) * 100, 1)
                    }
                else:
                    usage_info[name] = {
                        "path": path,
                        "error": "Directory does not exist"
                    }
            except Exception as e:
                usage_info[name] = {
                    "path": path,
                    "error": str(e)
                }

        return {
            "healthy": True,
            "disk_usage": usage_info,
            "timestamp": datetime.utcnow()
        }

    except Exception as e:
        logger.error(f"Disk usage check error: {e}")
        return {
            "healthy": False,
            "error": str(e),
            "timestamp": datetime.utcnow()
        }


async def _check_database_health(db: Session) -> Dict[str, Any]:
    """Check database connectivity and basic operations."""
    try:
        # Test basic query
        result = db.execute(text("SELECT 1 as test_value"))
        test_value = result.scalar()

        if test_value != 1:
            raise Exception("Database query returned unexpected result")

        # Test document table access
        from src.database.models import Document
        doc_count = db.query(Document).count()

        return {
            "healthy": True,
            "connection": "ok",
            "document_count": doc_count,
            "response_time_ms": 0  # Could measure actual response time
        }

    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {
            "healthy": False,
            "connection": "failed",
            "error": str(e)
        }


async def _check_vector_store_health() -> Dict[str, Any]:
    """Check vector store (FAISS) health."""
    try:
        # This would check if FAISS index is accessible
        # For now, just check if index files exist (pure file-existence
        # check, no FAISS lock acquired -- keeps this coroutine non-blocking)
        import os

        index_exists = os.path.exists(settings.faiss_index_path)

        # Tolerate the migration window: metadata is considered present if
        # EITHER the current JSON file OR the legacy pickle file exists, to
        # avoid a false "inconsistent" report right after an index exists
        # but metadata.json has not been written yet (see faiss_store.py
        # legacy_metadata_path / ROB-02 migration).
        legacy_metadata_path = os.path.splitext(settings.faiss_metadata_path)[0] + '.pkl'
        metadata_exists = (
            os.path.exists(settings.faiss_metadata_path)
            or os.path.exists(legacy_metadata_path)
        )

        if index_exists and metadata_exists:
            return {
                "healthy": True,
                "index_file": "exists",
                "metadata_file": "exists"
            }
        elif not index_exists and not metadata_exists:
            # New installation - no index yet is OK
            return {
                "healthy": True,
                "index_file": "not_initialized",
                "metadata_file": "not_initialized",
                "note": "Vector store not initialized yet - normal for new installation"
            }
        else:
            return {
                "healthy": False,
                "index_file": "exists" if index_exists else "missing",
                "metadata_file": "exists" if metadata_exists else "missing",
                "error": "Inconsistent vector store state"
            }

    except Exception as e:
        logger.error(f"Vector store health check failed: {e}")
        return {
            "healthy": False,
            "error": str(e)
        }


async def _check_llm_health() -> Dict[str, Any]:
    """Check LLM API connectivity."""
    try:
        # This would test actual LLM API connection
        # For now, just check if API key is configured
        llm_configured = bool(settings.mistral_api_key)

        return {
            "healthy": llm_configured,
            "api_configured": llm_configured,
            "provider": settings.llm_provider,
            "model": settings.mistral_model if llm_configured else None,
            "note": "API key configured" if llm_configured else "API key not configured"
        }

    except Exception as e:
        logger.error(f"LLM health check failed: {e}")
        return {
            "healthy": False,
            "error": str(e)
        }


async def _check_cache_health() -> Dict[str, Any]:
    """Check cache service health."""
    try:
        from src.cache.lru_cache import cache_service, chat_cache_service

        # Test cache operations
        test_key = "health_check_test"
        test_value = "test_data"

        cache_service.set(test_key, test_value, ttl=5)
        retrieved_value = cache_service.get(test_key)

        if retrieved_value != test_value:
            raise Exception("Cache test failed - value mismatch")

        # Clean up test key
        cache_service.delete(test_key)

        # Get cache statistics
        cache_stats = cache_service.get_stats()
        chat_cache_stats = chat_cache_service.get_stats()

        return {
            "healthy": True,
            "test": "passed",
            "main_cache": cache_stats,
            "chat_cache": chat_cache_stats
        }

    except Exception as e:
        logger.error(f"Cache health check failed: {e}")
        return {
            "healthy": False,
            "error": str(e)
        }


async def _check_email_health() -> Dict[str, Any]:
    """Check email service configuration."""
    try:
        from src.email_service.smtp_client import email_service

        config_status = email_service.get_configuration_status()

        return {
            "healthy": config_status["configured"],
            "configuration": config_status,
            "note": "Email service configured" if config_status["configured"] else "Email service not configured"
        }

    except Exception as e:
        logger.error(f"Email health check failed: {e}")
        return {
            "healthy": False,
            "error": str(e)
        }