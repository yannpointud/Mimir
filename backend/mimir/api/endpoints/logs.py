"""
Frontend logging endpoints.

This module provides endpoints for receiving and storing
frontend application logs for debugging and monitoring.
"""

import logging
from datetime import datetime
from typing import Any
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from mimir.monitoring.logger import frontend_logger

logger = logging.getLogger(__name__)


# Request models
class FrontendLogEntry(BaseModel):
    timestamp: str = Field(..., max_length=64, description="ISO timestamp of the log entry")
    level: str = Field(..., max_length=16, description="Log level (DEBUG, INFO, WARN, ERROR)")
    module: str = Field(..., max_length=128, description="Frontend module name")
    message: str = Field(..., max_length=4000, description="Log message")
    url: str | None = Field(None, max_length=2048, description="Current page URL")
    userAgent: str | None = Field(None, max_length=512, description="Browser user agent")
    timeSinceStart: str | None = Field(None, max_length=32, description="Time since app start")
    extra_data: dict[str, Any] | None = Field(None, description="Additional log data")


class LogResponse(BaseModel):
    status: str = Field(..., description="Status of log submission")
    message: str = Field(..., description="Response message")


# Router configuration
router = APIRouter(
    prefix="/logs",
    tags=["logging"],
    responses={
        400: {"description": "Invalid log data"},
        500: {"description": "Internal server error"},
    },
)


@router.post("/frontend", response_model=LogResponse)
async def receive_frontend_log(log_entry: FrontendLogEntry) -> LogResponse:
    """Receive and store a frontend log entry.

    This endpoint accepts log entries from the frontend application
    and writes them to the dedicated frontend.log file.
    """
    try:
        # Map frontend log levels to Python logging levels
        level_mapping = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARN": logging.WARNING,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }

        # Get Python logging level
        log_level = level_mapping.get(log_entry.level.upper(), logging.INFO)

        # Prepare extra fields for structured logging
        extra_fields = {
            "frontend_timestamp": log_entry.timestamp,
            "frontend_module": log_entry.module,
            "type": "frontend_log",
        }

        # Add optional fields if present
        if log_entry.url:
            extra_fields["url"] = log_entry.url
        if log_entry.userAgent:
            extra_fields["user_agent"] = log_entry.userAgent
        if log_entry.timeSinceStart:
            extra_fields["time_since_start"] = log_entry.timeSinceStart
        if log_entry.extra_data:
            extra_fields.update(log_entry.extra_data)

        # Log to frontend logger with structured data
        frontend_logger.log(
            log_level,
            f"[{log_entry.module}] {log_entry.message}",
            extra={"extra_fields": extra_fields},
        )

        return LogResponse(status="success", message="Log entry stored successfully")

    except Exception as e:  # noqa: BLE001 - API boundary: unexpected errors become a generic 500
        # Log the error to backend logger
        logger.error(f"Failed to process frontend log: {str(e)}")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process log entry"
        ) from e


@router.get("/frontend/health")
async def frontend_logging_health() -> dict[str, Any]:
    """Health check for frontend logging system."""
    try:
        # Check if frontend logger is properly configured
        handlers_count = len(frontend_logger.handlers)

        return {
            "status": "healthy",
            "frontend_logger_configured": handlers_count > 0,
            "handlers_count": handlers_count,
            "log_level": logging.getLevelName(frontend_logger.level),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    except Exception as e:  # noqa: BLE001 - health probe: any failure is reported as unhealthy
        logger.error(f"Frontend logging health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
