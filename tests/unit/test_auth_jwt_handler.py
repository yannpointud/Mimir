"""
Unit tests for the auth/jwt_handler.py module

These tests cover JWT token management and password hashing.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from freezegun import freeze_time
from jose import jwt
from backend.src.auth.jwt_handler import JWTHandler


class TestJWTHandlerInit:
    """Tests for JWTHandler initialization."""

    def test_init_with_valid_config(self):
        """Test initialization with valid configuration."""
        with patch('backend.src.auth.jwt_handler.settings') as mock_settings:
            mock_settings.jwt_secret_key = "a" * 32
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expiration_hours = 24

            handler = JWTHandler()

            assert handler.secret_key == "a" * 32
            assert handler.algorithm == "HS256"
            assert handler.expiration_hours == 24
            assert handler.pwd_context is not None

    def test_init_with_short_secret_key(self):
        """Test initialization with a secret key that is too short."""
        with patch('backend.src.auth.jwt_handler.settings') as mock_settings:
            mock_settings.jwt_secret_key = "short"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expiration_hours = 24

            with pytest.raises(ValueError, match="JWT secret key must be at least 32 characters long"):
                JWTHandler()

    def test_init_with_empty_secret_key(self):
        """Test initialization with an empty secret key."""
        with patch('backend.src.auth.jwt_handler.settings') as mock_settings:
            mock_settings.jwt_secret_key = ""
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expiration_hours = 24

            with pytest.raises(ValueError, match="JWT secret key must be at least 32 characters long"):
                JWTHandler()


class TestCreateAccessToken:
    """Tests for JWT access token creation."""

    @pytest.fixture
    def jwt_handler(self):
        """Fixture for JWTHandler with valid configuration."""
        with patch('backend.src.auth.jwt_handler.settings') as mock_settings:
            mock_settings.jwt_secret_key = "a" * 32
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expiration_hours = 24
            return JWTHandler()

    @freeze_time("2023-01-01 12:00:00")
    def test_create_token_with_default_expiration(self, jwt_handler):
        """Test token creation with default expiration."""
        data = {"user_id": 123, "username": "testuser"}

        token = jwt_handler.create_access_token(data)

        assert isinstance(token, str)
        assert len(token) > 0

        # Decode the token to verify its content
        payload = jwt.decode(token, jwt_handler.secret_key, algorithms=[jwt_handler.algorithm])
        assert payload["user_id"] == 123
        assert payload["username"] == "testuser"
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "iat" in payload

    @freeze_time("2023-01-01 12:00:00")
    def test_create_token_with_custom_expiration(self, jwt_handler):
        """Test token creation with custom expiration."""
        data = {"user_id": 123}
        custom_expiration = timedelta(hours=1)

        token = jwt_handler.create_access_token(data, expires_delta=custom_expiration)

        payload = jwt.decode(token, jwt_handler.secret_key, algorithms=[jwt_handler.algorithm])
        expected_exp = datetime.utcnow() + custom_expiration
        actual_exp = datetime.utcfromtimestamp(payload["exp"])

        # Verify expiration is correct (with a few seconds tolerance)
        assert abs((actual_exp - expected_exp).total_seconds()) < 5

    def test_create_token_with_empty_data(self, jwt_handler):
        """Test token creation with empty data."""
        token = jwt_handler.create_access_token({})

        payload = jwt.decode(token, jwt_handler.secret_key, algorithms=[jwt_handler.algorithm])
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "iat" in payload

    @patch('backend.src.auth.jwt_handler.jwt.encode')
    def test_create_token_encoding_error(self, mock_encode, jwt_handler):
        """Test error handling during token encoding."""
        mock_encode.side_effect = Exception("Encoding failed")

        with pytest.raises(Exception, match="Encoding failed"):
            jwt_handler.create_access_token({"user_id": 123})


class TestVerifyToken:
    """Tests for JWT token verification."""

    @pytest.fixture
    def jwt_handler(self):
        """Fixture for JWTHandler with valid configuration."""
        with patch('backend.src.auth.jwt_handler.settings') as mock_settings:
            mock_settings.jwt_secret_key = "a" * 32
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expiration_hours = 24
            return JWTHandler()

    def test_verify_valid_token(self, jwt_handler):
        """Test verification of a valid token."""
        data = {"user_id": 123, "username": "testuser"}
        token = jwt_handler.create_access_token(data)

        payload = jwt_handler.verify_token(token)

        assert payload is not None
        assert payload["user_id"] == 123
        assert payload["username"] == "testuser"
        assert payload["type"] == "access"

    def test_verify_invalid_signature(self, jwt_handler):
        """Test verification with invalid signature."""
        # Create a token with a different key
        fake_secret = "b" * 32
        data = {"user_id": 123, "type": "access"}
        fake_token = jwt.encode(data, fake_secret, algorithm="HS256")

        payload = jwt_handler.verify_token(fake_token)

        assert payload is None

    def test_verify_expired_token(self, jwt_handler):
        """Test verification of an expired token."""
        with freeze_time("2023-01-01 12:00:00"):
            data = {"user_id": 123}
            token = jwt_handler.create_access_token(data, expires_delta=timedelta(seconds=1))

        # Advance time to expire the token
        with freeze_time("2023-01-01 12:01:00"):
            payload = jwt_handler.verify_token(token)
            assert payload is None

    def test_verify_invalid_token_type(self, jwt_handler):
        """Test verification with invalid token type."""
        data = {"user_id": 123, "type": "refresh"}
        token = jwt.encode(data, jwt_handler.secret_key, algorithm=jwt_handler.algorithm)

        payload = jwt_handler.verify_token(token)

        assert payload is None

    def test_verify_malformed_token(self, jwt_handler):
        """Test verification of a malformed token."""
        malformed_token = "invalid.token.format"

        payload = jwt_handler.verify_token(malformed_token)

        assert payload is None

    def test_verify_token_without_type(self, jwt_handler):
        """Test verification of a token without type."""
        data = {"user_id": 123}
        token = jwt.encode(data, jwt_handler.secret_key, algorithm=jwt_handler.algorithm)

        payload = jwt_handler.verify_token(token)

        assert payload is None

    @patch('backend.src.auth.jwt_handler.jwt.decode')
    def test_verify_token_unexpected_error(self, mock_decode, jwt_handler):
        """Test unexpected error handling during verification."""
        mock_decode.side_effect = Exception("Unexpected error")

        payload = jwt_handler.verify_token("some_token")

        assert payload is None


class TestPasswordOperations:
    """Tests for password operations."""

    @pytest.fixture
    def jwt_handler(self):
        """Fixture for JWTHandler with valid configuration."""
        with patch('backend.src.auth.jwt_handler.settings') as mock_settings:
            mock_settings.jwt_secret_key = "a" * 32
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expiration_hours = 24
            return JWTHandler()

    def test_hash_password_valid(self, jwt_handler):
        """Test hashing a valid password."""
        password = "testpassword123"

        hashed = jwt_handler.hash_password(password)

        assert isinstance(hashed, str)
        assert len(hashed) > 0
        assert hashed != password  # Hash must not be the plaintext password
        assert hashed.startswith("$2b$")  # bcrypt format

    def test_hash_password_empty(self, jwt_handler):
        """Test hashing an empty password."""
        with pytest.raises(ValueError, match="Password cannot be empty"):
            jwt_handler.hash_password("")

    def test_hash_password_none(self, jwt_handler):
        """Test hashing a None password."""
        with pytest.raises(ValueError, match="Password cannot be empty"):
            jwt_handler.hash_password(None)

    def test_verify_password_valid(self, jwt_handler):
        """Test verification of a valid password."""
        password = "testpassword123"
        hashed = jwt_handler.hash_password(password)

        is_valid = jwt_handler.verify_password(password, hashed)

        assert is_valid is True

    def test_verify_password_invalid(self, jwt_handler):
        """Test verification of an invalid password."""
        password = "testpassword123"
        wrong_password = "wrongpassword"
        hashed = jwt_handler.hash_password(password)

        is_valid = jwt_handler.verify_password(wrong_password, hashed)

        assert is_valid is False

    def test_verify_password_empty_plain(self, jwt_handler):
        """Test verification with empty plaintext password."""
        hashed = jwt_handler.hash_password("testpassword")

        is_valid = jwt_handler.verify_password("", hashed)

        assert is_valid is False

    def test_verify_password_empty_hash(self, jwt_handler):
        """Test verification with empty hash."""
        is_valid = jwt_handler.verify_password("password", "")

        assert is_valid is False

    def test_verify_password_none_values(self, jwt_handler):
        """Test verification with None values."""
        assert jwt_handler.verify_password(None, "hash") is False
        assert jwt_handler.verify_password("password", None) is False
        assert jwt_handler.verify_password(None, None) is False

    @patch('backend.src.auth.jwt_handler.CryptContext.verify')
    def test_verify_password_exception(self, mock_verify, jwt_handler):
        """Test exception handling during verification."""
        mock_verify.side_effect = Exception("Verification failed")

        is_valid = jwt_handler.verify_password("password", "hash")

        assert is_valid is False


class TestGetTokenExpiry:
    """Tests for extracting token expiration date."""

    @pytest.fixture
    def jwt_handler(self):
        """Fixture for JWTHandler with valid configuration."""
        with patch('backend.src.auth.jwt_handler.settings') as mock_settings:
            mock_settings.jwt_secret_key = "a" * 32
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expiration_hours = 24
            return JWTHandler()

    @freeze_time("2023-01-01 12:00:00")
    def test_get_token_expiry_valid(self, jwt_handler):
        """Test expiry extraction from a valid token."""
        data = {"user_id": 123}
        token = jwt_handler.create_access_token(data)

        expiry = jwt_handler.get_token_expiry(token)

        assert expiry is not None
        assert isinstance(expiry, datetime)
        expected_expiry = datetime.utcnow() + timedelta(hours=24)
        assert abs((expiry - expected_expiry).total_seconds()) < 5

    def test_get_token_expiry_invalid_token(self, jwt_handler):
        """Test expiry extraction from an invalid token."""
        invalid_token = "invalid.token"

        expiry = jwt_handler.get_token_expiry(invalid_token)

        assert expiry is None

    def test_get_token_expiry_expired_token(self, jwt_handler):
        """Test expiry extraction from an expired token."""
        with freeze_time("2023-01-01 12:00:00"):
            data = {"user_id": 123}
            token = jwt_handler.create_access_token(data, expires_delta=timedelta(seconds=1))

        # Token is expired, but we can still extract its expiration date
        with freeze_time("2023-01-01 12:01:00"):
            expiry = jwt_handler.get_token_expiry(token)
            assert expiry is None  # verify_token returns None for expired token


class TestJWTHandlerIntegration:
    """Integration tests for JWTHandler."""

    @pytest.fixture
    def jwt_handler(self):
        """Fixture for JWTHandler with valid configuration."""
        with patch('backend.src.auth.jwt_handler.settings') as mock_settings:
            mock_settings.jwt_secret_key = "a" * 32
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expiration_hours = 24
            return JWTHandler()

    def test_full_authentication_flow(self, jwt_handler):
        """Test full authentication flow."""
        # Create and hash a password
        password = "userpassword123"
        hashed_password = jwt_handler.hash_password(password)

        # Verify the password
        assert jwt_handler.verify_password(password, hashed_password) is True

        # Create a token
        user_data = {"user_id": 123, "username": "testuser"}
        token = jwt_handler.create_access_token(user_data)

        # Verify the token
        payload = jwt_handler.verify_token(token)
        assert payload is not None
        assert payload["user_id"] == 123
        assert payload["username"] == "testuser"

        # Get the expiration
        expiry = jwt_handler.get_token_expiry(token)
        assert expiry is not None
        assert expiry > datetime.utcnow()

    def test_password_hash_uniqueness(self, jwt_handler):
        """Test that the same password produces different hashes."""
        password = "samepassword"

        hash1 = jwt_handler.hash_password(password)
        hash2 = jwt_handler.hash_password(password)

        # Hashes must be different (random salt)
        assert hash1 != hash2

        # But both must be verifiable
        assert jwt_handler.verify_password(password, hash1) is True
        assert jwt_handler.verify_password(password, hash2) is True

    def test_token_uniqueness(self, jwt_handler):
        """Test that tokens created at different times are unique."""
        data = {"user_id": 123}

        # Use future dates to avoid expiration
        future_date = datetime.now() + timedelta(hours=1)

        with freeze_time(future_date):
            token1 = jwt_handler.create_access_token(data)

        with freeze_time(future_date + timedelta(seconds=1)):
            token2 = jwt_handler.create_access_token(data)

        # Tokens must be different (different timestamps)
        assert token1 != token2

        # But both must be valid
        assert jwt_handler.verify_token(token1) is not None
        assert jwt_handler.verify_token(token2) is not None
