"""
Rate limiting middleware.

This module provides rate limiting functionality to protect
the API from abuse and ensure fair usage.
"""

from typing import Dict, Any, Optional
from fastapi import Request, HTTPException, status
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import logging

from src.config import settings

logger = logging.getLogger(__name__)


def get_client_identifier(request: Request) -> str:
    """
    Get client identifier for rate limiting.

    Uses IP address by default, but can be enhanced to use
    authenticated user ID for more sophisticated limiting.

    Args:
        request: FastAPI request object

    Returns:
        str: Client identifier
    """
    # Check if user is authenticated
    if hasattr(request.state, 'jwt_payload') and request.state.jwt_payload:
        user_id = request.state.jwt_payload.get('sub')
        user_type = request.state.jwt_payload.get('user_type')
        if user_id:
            return f"user:{user_type}:{user_id}"

    # Fall back to IP address
    return get_remote_address(request)


# Create limiter instance
limiter = Limiter(
    key_func=get_client_identifier,
    default_limits=["100/hour"]  # Global default limit
)


def configure_rate_limiting(app):
    """
    Configure rate limiting for the FastAPI application.

    Args:
        app: FastAPI application instance
    """
    # Add SlowAPI middleware
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    # Custom rate limit exceeded handler
    @app.exception_handler(RateLimitExceeded)
    async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
        """Custom handler for rate limit exceeded errors."""
        client_id = get_client_identifier(request)
        logger.warning(f"Rate limit exceeded for client: {client_id}, endpoint: {request.url.path}")

        response_data = {
            "error": "Rate limit exceeded",
            "detail": f"Too many requests. Limit: {exc.detail}",
            "retry_after": exc.retry_after,
            "type": "rate_limit_error"
        }

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=response_data,
            headers={"Retry-After": str(exc.retry_after)}
        )

    logger.info("Rate limiting configured successfully")


# Rate limiting decorators for different endpoint types
def chat_rate_limit():
    """Rate limit for chat endpoints."""
    rate = getattr(settings, 'chat_rate_limit_per_minute', 20)
    return limiter.limit(f"{rate}/minute")


def admin_rate_limit():
    """Rate limit for admin endpoints (more permissive)."""
    rate = getattr(settings, 'admin_rate_limit_per_minute', 100)
    return limiter.limit(f"{rate}/minute")


def upload_rate_limit():
    """Rate limit for file upload endpoints."""
    rate = getattr(settings, 'upload_rate_limit_per_hour', 50)
    return limiter.limit(f"{rate}/hour")


def auth_rate_limit():
    """Rate limit for authentication endpoints (stricter)."""
    rate = getattr(settings, 'auth_rate_limit_per_minute', 5)
    return limiter.limit(f"{rate}/minute")


def health_rate_limit():
    """Rate limit for health check endpoints (very permissive)."""
    return limiter.limit("300/minute")


# Rate limiting based on user type
def user_type_rate_limit(request: Request) -> str:
    """
    Dynamic rate limit based on user type.

    Args:
        request: FastAPI request object

    Returns:
        str: Rate limit string
    """
    # Check if user is authenticated
    if hasattr(request.state, 'jwt_payload') and request.state.jwt_payload:
        user_type = request.state.jwt_payload.get('user_type')

        if user_type == 'admin':
            return "200/minute"  # More permissive for admins
        elif user_type == 'user':
            return "50/minute"   # Standard rate for authenticated users

    # Anonymous users
    return "20/minute"


# Exemptions for certain endpoints
def is_exempt_endpoint(request: Request) -> bool:
    """
    Check if endpoint should be exempt from rate limiting.

    Args:
        request: FastAPI request object

    Returns:
        bool: True if endpoint is exempt
    """
    exempt_paths = [
        "/health",
        "/api/v1/health",
        "/docs",
        "/openapi.json",
        "/redoc"
    ]

    path = request.url.path
    return any(path.startswith(exempt_path) for exempt_path in exempt_paths)


class ConditionalRateLimiter:
    """
    Conditional rate limiter that can apply different limits
    based on request context.
    """

    def __init__(self, default_limit: str = "60/minute"):
        self.default_limit = default_limit

    def __call__(self, request: Request) -> str:
        """
        Determine rate limit for request.

        Args:
            request: FastAPI request object

        Returns:
            str: Rate limit string
        """
        # Check for exemptions
        if is_exempt_endpoint(request):
            return "1000/minute"  # Very high limit for exempt endpoints

        # Use user-type based limiting
        return user_type_rate_limit(request)


# Global conditional limiter instance
conditional_limiter = ConditionalRateLimiter()