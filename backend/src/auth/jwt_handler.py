"""
JWT token handling for authentication.

This module provides functionality for creating and validating JWT tokens,
as well as password hashing/verification using bcrypt.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import logging
from jose import JWTError, jwt
from passlib.context import CryptContext
from src.config import settings

logger = logging.getLogger(__name__)


class JWTHandler:
    """Handles JWT token creation, validation, and password operations."""

    def __init__(self):
        """Initialize JWT handler with configuration from settings."""
        self.secret_key = settings.jwt_secret_key
        self.algorithm = settings.jwt_algorithm
        self.expiration_hours = settings.jwt_expiration_hours
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

        # Validate configuration
        if not self.secret_key or len(self.secret_key) < 32:
            raise ValueError("JWT secret key must be at least 32 characters long")

    def create_access_token(
        self,
        data: Dict[str, Any],
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        Create a JWT access token.

        Args:
            data: Dictionary with claims to encode in the token
            expires_delta: Optional custom expiration time

        Returns:
            str: The encoded JWT token
        """
        to_encode = data.copy()

        # Set expiration time
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(hours=self.expiration_hours)

        to_encode.update({
            "exp": expire,
            "iat": datetime.utcnow(),
            "type": "access"
        })

        try:
            encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
            logger.debug(f"Created JWT token with expiration: {expire}")
            return encoded_jwt
        except Exception as e:
            logger.error(f"Failed to create JWT token: {e}")
            raise

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Verify and decode a JWT token.

        Args:
            token: The JWT token to verify

        Returns:
            Dict containing the token payload if valid, None otherwise
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
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
        except jwt.JWTClaimsError:
            logger.warning("JWT token has invalid claims")
            return None
        except JWTError as e:
            logger.warning(f"JWT token validation failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during token verification: {e}")
            return None

    def hash_password(self, password: str) -> str:
        """
        Hash a password using bcrypt.

        Args:
            password: The plain text password

        Returns:
            str: The hashed password
        """
        if not password:
            raise ValueError("Password cannot be empty")

        return self.pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        Verify a password against its hash.

        Args:
            plain_password: The plain text password
            hashed_password: The hashed password to verify against

        Returns:
            bool: True if password matches, False otherwise
        """
        if not plain_password or not hashed_password:
            return False

        try:
            return self.pwd_context.verify(plain_password, hashed_password)
        except Exception as e:
            logger.error(f"Password verification error: {e}")
            return False

    def get_token_expiry(self, token: str) -> Optional[datetime]:
        """
        Get the expiration time of a token.

        Args:
            token: The JWT token

        Returns:
            datetime: The expiration time if valid, None otherwise
        """
        payload = self.verify_token(token)
        if payload and "exp" in payload:
            return datetime.utcfromtimestamp(payload["exp"])
        return None


# Global JWT handler instance
jwt_handler = JWTHandler()