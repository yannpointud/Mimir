"""
Authentication endpoints.

This module provides authentication endpoints for admin login
and token management.
"""

from datetime import timedelta
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
import logging

from pathlib import Path

from src.auth.jwt_handler import jwt_handler
from src.auth.middleware import get_current_user, require_admin
from src.auth.password_utils import validate_password_strength
from src.database.repository import AuditLogRepository
from src.api.dependencies import get_audit_log_repository
from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
    responses={
        401: {"description": "Authentication failed"},
        403: {"description": "Access forbidden"},
    }
)


class LoginRequest(BaseModel):
    """Request model for login."""
    username: str
    password: str


class LoginResponse(BaseModel):
    """Response model for successful login."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_type: str


class ChangePasswordRequest(BaseModel):
    """Request model for password change."""
    current_password: str
    new_password: str


class TokenRefreshResponse(BaseModel):
    """Response model for token refresh."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    login_data: LoginRequest,
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository)
) -> LoginResponse:
    """
    Authenticate admin user and return access token.

    Args:
        request: FastAPI request object for IP tracking
        login_data: Login credentials
        audit_repo: Audit log repository for logging attempts

    Returns:
        LoginResponse: Access token and user information
    """
    client_ip = _get_client_ip(request)

    try:
        # Validate credentials
        if not _authenticate_admin(login_data.username, login_data.password):
            # Log failed attempt
            await _log_auth_event(
                audit_repo=audit_repo,
                action="login_failed",
                username=login_data.username,
                ip_address=client_ip,
                success=False,
                details="Invalid credentials"
            )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"}
            )

        # Create access token
        token_data = {
            "sub": login_data.username,
            "user_type": "admin"
        }

        expires_delta = timedelta(hours=settings.jwt_expiration_hours)
        access_token = jwt_handler.create_access_token(
            data=token_data,
            expires_delta=expires_delta
        )

        # Log successful login
        await _log_auth_event(
            audit_repo=audit_repo,
            action="login_success",
            username=login_data.username,
            ip_address=client_ip,
            success=True,
            details="Admin login successful"
        )

        logger.info(f"Admin login successful - user: {login_data.username}, IP: {client_ip}")

        return LoginResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=settings.jwt_expiration_hours * 3600,  # Convert to seconds
            user_type="admin"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error for user {login_data.username}: {e}")

        # Log system error
        await _log_auth_event(
            audit_repo=audit_repo,
            action="login_error",
            username=login_data.username,
            ip_address=client_ip,
            success=False,
            details=f"System error: {str(e)}"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication system error"
        )


@router.post("/logout")
async def logout(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository)
) -> Dict[str, str]:
    """
    Logout current user (invalidate session).

    Note: Since JWT is stateless, this endpoint mainly serves to log the logout
    event. Client should discard the token.

    Args:
        request: FastAPI request object for IP tracking
        current_user: Current authenticated user
        audit_repo: Audit log repository

    Returns:
        dict: Logout confirmation message
    """
    client_ip = _get_client_ip(request)

    try:
        # Log logout event
        await _log_auth_event(
            audit_repo=audit_repo,
            action="logout",
            username=current_user.get("sub", "unknown"),
            ip_address=client_ip,
            success=True,
            details="User logout"
        )

        logger.info(f"User logout - user: {current_user.get('sub')}, IP: {client_ip}")

        return {"message": "Successfully logged out"}

    except Exception as e:
        logger.error(f"Logout error: {e}")
        return {"message": "Logged out (with errors)"}


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh_token(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository)
) -> TokenRefreshResponse:
    """
    Refresh access token for authenticated user.

    Args:
        request: FastAPI request object
        current_user: Current authenticated user from token
        audit_repo: Audit log repository

    Returns:
        TokenRefreshResponse: New access token
    """
    client_ip = _get_client_ip(request)

    try:
        # Create new token with same claims
        token_data = {
            "sub": current_user["sub"],
            "user_type": current_user["user_type"]
        }

        expires_delta = timedelta(hours=settings.jwt_expiration_hours)
        new_access_token = jwt_handler.create_access_token(
            data=token_data,
            expires_delta=expires_delta
        )

        # Log token refresh
        await _log_auth_event(
            audit_repo=audit_repo,
            action="token_refresh",
            username=current_user["sub"],
            ip_address=client_ip,
            success=True,
            details="Token refreshed successfully"
        )

        logger.debug(f"Token refreshed for user: {current_user['sub']}")

        return TokenRefreshResponse(
            access_token=new_access_token,
            token_type="bearer",
            expires_in=settings.jwt_expiration_hours * 3600
        )

    except Exception as e:
        logger.error(f"Token refresh error: {e}")

        await _log_auth_event(
            audit_repo=audit_repo,
            action="token_refresh_error",
            username=current_user.get("sub", "unknown"),
            ip_address=client_ip,
            success=False,
            details=f"Token refresh failed: {str(e)}"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token refresh failed"
        )


@router.get("/me")
async def get_current_user_info(
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get current authenticated user information.

    Args:
        current_user: Current authenticated user

    Returns:
        dict: User information
    """
    return {
        "username": current_user["sub"],
        "user_type": current_user["user_type"],
        "token_issued_at": current_user.get("iat"),
        "token_expires_at": current_user.get("exp")
    }


@router.post("/verify-admin")
async def verify_admin_access(
    admin_user: Dict[str, Any] = Depends(require_admin)
) -> Dict[str, str]:
    """
    Verify admin access (protected endpoint for testing admin auth).

    Args:
        admin_user: Admin user from require_admin dependency

    Returns:
        dict: Confirmation message
    """
    return {
        "message": "Admin access confirmed",
        "user": admin_user["sub"]
    }


@router.post("/change-password")
async def change_password(
    request: Request,
    data: ChangePasswordRequest,
    admin_user: Dict[str, Any] = Depends(require_admin),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository)
) -> Dict[str, str]:
    """
    Change admin password.

    Args:
        request: FastAPI request object for IP tracking
        data: Current and new password
        admin_user: Authenticated admin user
        audit_repo: Audit log repository

    Returns:
        dict: Success confirmation
    """
    client_ip = _get_client_ip(request)
    username = admin_user.get("sub", "admin")

    # Verify current password
    if not jwt_handler.verify_password(data.current_password, settings.admin_password_hash):
        await _log_auth_event(
            audit_repo=audit_repo,
            action="password_change_failed",
            username=username,
            ip_address=client_ip,
            success=False,
            details="Invalid current password"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mot de passe actuel incorrect"
        )

    # Validate new password strength
    validation = validate_password_strength(data.new_password)
    if not validation["valid"]:
        errors_text = ". ".join(validation["errors"])
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=errors_text
        )

    # Hash new password and persist
    new_hash = jwt_handler.hash_password(data.new_password)

    try:
        _update_env_file("ADMIN_PASSWORD_HASH", new_hash)
    except Exception as e:
        logger.error(f"Failed to update .env file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la mise à jour du fichier de configuration"
        )

    await _log_auth_event(
        audit_repo=audit_repo,
        action="password_changed",
        username=username,
        ip_address=client_ip,
        success=True,
        details="Admin password changed successfully"
    )

    logger.info(f"Admin password changed by user: {username}, IP: {client_ip}")

    return {"message": "Mot de passe modifié avec succès"}


def _update_env_file(key: str, value: str) -> None:
    """
    Update a key in the backend .env file and refresh in-memory settings.

    Args:
        key: Environment variable name
        value: New value
    """
    env_path = Path(__file__).resolve().parents[3] / ".env"

    lines = env_path.read_text(encoding="utf-8").splitlines()

    updated = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped == key:
            lines[i] = f"{key}={value}"
            updated = True
            break

    if not updated:
        lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Update in-memory settings
    if key == "ADMIN_PASSWORD_HASH":
        settings.admin_password_hash = value


def _authenticate_admin(username: str, password: str) -> bool:
    """
    Authenticate admin credentials against configured password.

    Args:
        username: Username to authenticate
        password: Password to verify

    Returns:
        bool: True if authentication successful
    """
    try:
        # For MVP, we use single admin account with configurable password
        expected_username = "admin"
        expected_password_hash = settings.admin_password_hash

        if username != expected_username:
            return False

        if not expected_password_hash:
            logger.error("Admin password hash not configured")
            return False

        # Verify password against hash
        return jwt_handler.verify_password(password, expected_password_hash)

    except Exception as e:
        logger.error(f"Authentication error: {e}")
        return False


def _get_client_ip(request: Request) -> str:
    """
    Extract client IP address from request.

    Args:
        request: FastAPI request object

    Returns:
        str: Client IP address
    """
    # Check for forwarded headers (when behind proxy)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # Fall back to direct client IP
    return request.client.host if request.client else "unknown"


async def _log_auth_event(
    audit_repo: AuditLogRepository,
    action: str,
    username: str,
    ip_address: str,
    success: bool,
    details: str = None
):
    """
    Log authentication event to audit log.

    Args:
        audit_repo: Audit log repository
        action: Action being performed
        username: Username involved
        ip_address: Client IP address
        success: Whether action was successful
        details: Additional details
    """
    try:
        audit_repo.create_log(
            user_type="admin",
            action=action,
            details=details,
            ip_address=ip_address,
            success=success,
            additional_data={
                "username": username,
                "timestamp": "auto"
            }
        )
    except Exception as e:
        logger.error(f"Failed to log auth event: {e}")
        # Don't raise exception - logging failures shouldn't break auth flow