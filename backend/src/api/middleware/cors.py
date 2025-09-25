"""
CORS middleware configuration.

This module provides CORS (Cross-Origin Resource Sharing) middleware
configuration for the Mimir API.
"""

from fastapi.middleware.cors import CORSMiddleware
from src.config import settings
import logging

logger = logging.getLogger(__name__)


def configure_cors_middleware(app):
    """
    Configure CORS middleware for the FastAPI application.

    Args:
        app: FastAPI application instance
    """
    # CORS configuration based on environment
    if settings.is_production:
        # Production: restrictive CORS
        allowed_origins = [
            "https://localhost",
            "https://127.0.0.1",
            "https://localhost:3000",  # React dev server (if running on HTTPS)
        ]

        # Add custom allowed origins from settings if available
        if hasattr(settings, 'allowed_origins') and settings.allowed_origins:
            allowed_origins.extend(settings.allowed_origins.split(','))

        logger.info(f"CORS configured for production - allowed origins: {allowed_origins}")
    else:
        # Development: permissive CORS
        allowed_origins = [
            "http://localhost:3000",  # React dev server
            "http://localhost:3001",  # Alternative React port
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
            "http://localhost:8080",  # Vue.js default
            "http://127.0.0.1:8080",
        ]

        logger.info("CORS configured for development - permissive settings")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Accept-Language",
            "Content-Language",
            "Content-Type",
            "Authorization",
            "X-Requested-With",
            "X-Request-ID",
        ],
        expose_headers=[
            "X-Request-ID",
            "X-Response-Time",
        ],
        max_age=600,  # 10 minutes
    )