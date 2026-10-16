"""
JWT token handling for authentication.

This module provides functionality for creating and validating JWT tokens,
as well as password hashing/verification using Argon2 (with Bcrypt kept as a
legacy verification-only hasher for pre-migration credentials).
"""

from datetime import datetime, timedelta
from typing import Any
import logging
import jwt  # PyJWT
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher
from mimir.config import settings

logger = logging.getLogger(__name__)


class JWTHandler:
    """Handles JWT token creation, validation, and password operations."""

    def __init__(self):
        self.secret_key = settings.jwt_secret_key
        self.algorithm = settings.jwt_algorithm
        self.expiration_hours = settings.jwt_expiration_hours
        # Argon2 is FIRST so new hashes are always Argon2; Bcrypt stays only to verify
        # legacy hashes issued before this migration (no silent downgrade).
        self.pwd_context = PasswordHash((Argon2Hasher(), BcryptHasher()))

        # Validate configuration
        if not self.secret_key or len(self.secret_key) < 32:
            raise ValueError("JWT secret key must be at least 32 characters long")

    def create_access_token(
        self, data: dict[str, Any], expires_delta: timedelta | None = None
    ) -> str:
        """Create a JWT access token."""
        to_encode = data.copy()

        # Set expiration time
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(hours=self.expiration_hours)

        to_encode.update({"exp": expire, "iat": datetime.utcnow(), "type": "access"})

        try:
            encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
            logger.debug(f"Created JWT token with expiration: {expire}")
            return encoded_jwt
        except Exception as e:  # noqa: BLE001 - log any failure, then re-raise unchanged
            logger.error(f"Failed to create JWT token: {e}")
            raise

    def verify_token(self, token: str) -> dict[str, Any] | None:
        """Verify and decode a JWT token."""
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                # PyJWT validates "iat" as a not-before claim by default (unlike the
                # previous jose-based implementation). Disabled to preserve prior
                # behavior and avoid rejecting legitimate tokens under clock skew
                # between servers -- exp is still enforced, so this is not a security
                # regression (python-jose -> PyJWT migration).
                options={"verify_iat": False},
            )

            # Validate token type
            if payload.get("type") != "access":
                logger.warning("Invalid token type")
                return None

            logger.debug("Successfully verified JWT token")
            return payload

        except jwt.ExpiredSignatureError:
            logger.warning("JWT token has expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"JWT token validation failed: {e}")
            return None
        except Exception as e:  # noqa: BLE001 - fail closed: any other error rejects the token (401)
            logger.error(f"Unexpected error during token verification: {e}")
            return None

    def hash_password(self, password: str) -> str:
        """Hash a password using Argon2 (current default hasher)."""
        if not password:
            raise ValueError("Password cannot be empty")

        return self.pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash."""
        if not plain_password or not hashed_password:
            return False

        try:
            return self.pwd_context.verify(plain_password, hashed_password)
        except Exception as e:  # noqa: BLE001 - fail closed: any error denies the password
            logger.error(f"Password verification error: {e}")
            return False

    def get_token_expiry(self, token: str) -> datetime | None:
        """Get the expiration time of a token."""
        payload = self.verify_token(token)
        if payload and "exp" in payload:
            return datetime.utcfromtimestamp(payload["exp"])
        return None


# Global JWT handler instance
jwt_handler = JWTHandler()
