"""
Authentication middleware for FastAPI routes.

This module provides middleware and dependency functions for protecting routes
with JWT authentication.
"""

from fastapi import HTTPException, status, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import logging

from .jwt_handler import jwt_handler

logger = logging.getLogger(__name__)


class JWTBearer(HTTPBearer):
    """Custom JWT Bearer token extractor with validation."""

    def __init__(self, auto_error: bool = True):
        super().__init__(auto_error=auto_error)

    def make_not_authenticated_error(self) -> HTTPException:
        """Error raised when the Authorization header is missing or not Bearer.

        FastAPI >= 0.122 answers this case with 401 + WWW-Authenticate. Keep the
        403 this API has always returned: the frontend treats any 401 as an
        expired session and redirects to the login page.
        """
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated")

    async def __call__(self, request: Request) -> HTTPAuthorizationCredentials | None:
        """
        Extract and validate JWT token from Authorization header.

        Args:
            request: The FastAPI request object

        Returns:
            HTTPAuthorizationCredentials: The validated credentials

        Raises:
            HTTPException: If token is invalid or missing
        """
        credentials = await super().__call__(request)

        if credentials:
            if credentials.scheme != "Bearer":
                logger.warning(f"Invalid authentication scheme: {credentials.scheme}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authentication scheme. Expected 'Bearer'",
                )

            # Validate the token
            payload = jwt_handler.verify_token(credentials.credentials)
            if not payload:
                logger.warning("Invalid JWT token received")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
                )

            # Store payload in request state for access in endpoints
            request.state.jwt_payload = payload
            request.state.user_type = payload.get("user_type", "user")

            logger.debug(f"Authentication successful for user_type: {payload.get('user_type')}")

        return credentials


# Global security instance
security = JWTBearer()


async def get_current_user(
    request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """
    Dependency to get the current authenticated user from JWT payload.

    Args:
        request: FastAPI request object
        credentials: JWT credentials from security dependency

    Returns:
        dict: User information from JWT payload

    Raises:
        HTTPException: If authentication fails
    """
    payload = getattr(request.state, "jwt_payload", None)
    if not payload:
        logger.error("JWT payload not found in request state")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )

    return {
        "user_type": payload.get("user_type", "user"),
        "sub": payload.get("sub"),
        "exp": payload.get("exp"),
        "iat": payload.get("iat"),
    }


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Dependency that requires admin user type.

    Args:
        current_user: Current user from get_current_user dependency

    Returns:
        dict: Admin user information

    Raises:
        HTTPException: If user is not admin
    """
    if current_user.get("user_type") != "admin":
        logger.warning(f"Access denied - user type: {current_user.get('user_type')}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required"
        )

    return current_user


# Optional authentication (doesn't raise error if no token)
optional_security = JWTBearer(auto_error=False)


async def get_optional_user(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(optional_security)
) -> dict | None:
    """
    Optional dependency to get user info if authenticated.

    Args:
        request: FastAPI request object
        credentials: Optional JWT credentials

    Returns:
        dict or None: User information if authenticated, None otherwise
    """
    if not credentials:
        return None

    payload = getattr(request.state, "jwt_payload", None)
    if not payload:
        return None

    return {
        "user_type": payload.get("user_type", "user"),
        "sub": payload.get("sub"),
        "exp": payload.get("exp"),
        "iat": payload.get("iat"),
    }
