"""
Rate limiting for the API.

Rate limiting is applied EXCLUSIVELY through per-route decorators
(@limiter.limit on login/chat/upload). There is deliberately NO ASGI
middleware and NO default limit: the slowapi ASGI middleware runs before
FastAPI dependency resolution (so the JWT key would be unavailable)
and breaks SSE streaming responses. Do not "fix" this by re-adding
the slowapi middleware — only decorated routes are limited, by design.
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import logging

from src.config import settings
from src.shared.models import ErrorResponse

logger = logging.getLogger(__name__)


def get_client_identifier(request: Request) -> str:
    """Get client identifier for rate limiting.

    Uses IP address by default, but can be enhanced to use
    authenticated user ID for more sophisticated limiting.
    """
    # Check if user is authenticated
    if hasattr(request.state, "jwt_payload") and request.state.jwt_payload:
        user_id = request.state.jwt_payload.get("sub")
        user_type = request.state.jwt_payload.get("user_type")
        if user_id:
            return f"user:{user_type}:{user_id}"

    # Fall back to IP address
    return get_remote_address(request)


# Create limiter instance. No default_limits: without an ASGI middleware a
# default limit would never apply to undecorated routes anyway — ONLY
# decorated routes are rate limited (intended scope, see module docstring).
limiter = Limiter(
    key_func=get_client_identifier,
    headers_enabled=True,  # required, otherwise _inject_headers is a no-op
    enabled=settings.rate_limit_enabled,  # .env kill-switch, also used by tests
)


def configure_rate_limiting(app):
    """Configure rate limiting for the FastAPI application.

    Registers the limiter on app.state and the 429 exception handler.
    Deliberately registers NO ASGI middleware (see module docstring).
    """
    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        """
        Handler for rate limit exceeded errors.

        Must RETURN a response, never raise: a raised HTTPException would be
        routed to the global HTTPException handler in main.py, which drops
        exc.headers and would lose Retry-After. Note that RateLimitExceeded
        in slowapi 0.1.9 only exposes .limit and .detail (no .retry_after);
        the Retry-After header is computed and injected by the limiter.
        """
        client_id = get_client_identifier(request)
        logger.warning(f"Rate limit exceeded for client: {client_id}, endpoint: {request.url.path}")

        response = JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=ErrorResponse(
                error_code="HTTP_429",
                error_message=f"Too many requests. Limit: {exc.detail}",
                details={"path": str(request.url.path)},
            ).model_dump(mode="json"),
        )
        # Inject Retry-After and X-RateLimit-* headers from the window state
        # recorded by the limit check (request.state.view_rate_limit)
        return request.app.state.limiter._inject_headers(response, request.state.view_rate_limit)

    logger.info("Rate limiting configured successfully")
