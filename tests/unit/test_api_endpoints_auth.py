"""
Unit tests for authentication endpoints.
"""

import pytest
from sqlalchemy.exc import OperationalError
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from fastapi import HTTPException, status
from pydantic import ValidationError

from mimir.api.endpoints.auth import LoginRequest, LoginResponse, TokenRefreshResponse


class TestAuthModels:
    """Tests for authentication models."""

    def test_login_request_model(self):
        """Test login request model."""
        request = LoginRequest(username="admin", password="test123")
        assert request.username == "admin"
        assert request.password == "test123"

    def test_login_response_model(self):
        """Test login response model."""
        response = LoginResponse(access_token="test_token", expires_in=3600, user_type="admin")
        assert response.access_token == "test_token"
        assert response.token_type == "bearer"
        assert response.expires_in == 3600
        assert response.user_type == "admin"

    def test_token_refresh_response_model(self):
        """Test token refresh response model."""
        response = TokenRefreshResponse(access_token="new_token", expires_in=3600)
        assert response.access_token == "new_token"
        assert response.token_type == "bearer"
        assert response.expires_in == 3600


class TestAuthEndpoints:
    """Tests for authentication endpoints."""

    @pytest.fixture
    def mock_audit_repo(self):
        """Mock audit repository."""
        return AsyncMock()

    @patch("mimir.api.endpoints.auth._authenticate_admin")
    @patch("mimir.api.endpoints.auth.jwt_handler")
    @patch("mimir.api.endpoints.auth._log_auth_event")
    def test_login_success(self, mock_log_event, mock_jwt, mock_auth):
        """Test successful login."""
        from mimir.api.endpoints.auth import login

        # Configure mocks
        mock_auth.return_value = True
        mock_jwt.create_access_token.return_value = "test_token"

        mock_request = Mock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}

        login_data = LoginRequest(username="admin", password="test123")
        mock_audit_repo = AsyncMock()

        # Call the function
        result = asyncio.run(
            login(
                request=mock_request,
                response=Mock(),  # required by slowapi header injection
                login_data=login_data,
                audit_repo=mock_audit_repo,
            )
        )

        # Assertions
        assert result.access_token == "test_token"
        assert result.token_type == "bearer"
        assert result.user_type == "admin"
        mock_auth.assert_called_once_with("admin", "test123")

    @patch("mimir.api.endpoints.auth._authenticate_admin")
    @patch("mimir.api.endpoints.auth._log_auth_event")
    def test_login_failure_invalid_credentials(self, mock_log_event, mock_auth):
        """Test login with invalid credentials."""
        from mimir.api.endpoints.auth import login

        # Configure mocks
        mock_auth.return_value = False

        mock_request = Mock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}

        login_data = LoginRequest(username="admin", password="wrong")
        mock_audit_repo = AsyncMock()

        # Test that exception is raised
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                login(
                    request=mock_request,
                    response=Mock(),  # required by slowapi header injection
                    login_data=login_data,
                    audit_repo=mock_audit_repo,
                )
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_validation_error_missing_fields(self):
        """Test validation with missing fields."""
        # The current LoginRequest model accepts empty strings
        # as it has no min_length constraint
        # This test verifies the current model behavior

        # These cases are valid according to the current model
        request1 = LoginRequest(username="", password="test123")
        assert request1.username == ""

        request2 = LoginRequest(username="admin", password="")
        assert request2.password == ""

        # The test should verify that fields are required (not None)
        with pytest.raises(ValidationError):
            LoginRequest()  # No fields provided


class TestAuthHelperFunctions:
    """Tests for authentication utility functions."""

    @patch("mimir.api.endpoints.auth.settings")
    @patch("mimir.api.endpoints.auth.jwt_handler.verify_password")
    def test_authenticate_admin_success(self, mock_verify_password, mock_settings):
        """Test successful admin authentication."""
        from mimir.api.endpoints.auth import _authenticate_admin

        mock_settings.admin_password_hash = "$2b$12$test_hash"
        mock_verify_password.return_value = True

        result = _authenticate_admin("admin", "test123")
        assert result is True

    @patch("mimir.api.endpoints.auth.settings")
    def test_authenticate_admin_wrong_username(self, mock_settings):
        """Test authentication with wrong username."""
        from mimir.api.endpoints.auth import _authenticate_admin

        mock_settings.admin_password_hash = "$2b$12$test_hash"

        result = _authenticate_admin("wrong_user", "test123")
        assert result is False

    @patch("mimir.api.endpoints.auth.settings")
    @patch("mimir.api.endpoints.auth.jwt_handler.verify_password")
    def test_authenticate_admin_wrong_password(self, mock_verify_password, mock_settings):
        """Test authentication with wrong password."""
        from mimir.api.endpoints.auth import _authenticate_admin

        mock_settings.admin_password_hash = "$2b$12$test_hash"
        mock_verify_password.return_value = False

        result = _authenticate_admin("admin", "wrong_password")
        assert result is False

    def test_log_auth_event(self):
        """Test authentication event logging."""
        from mimir.api.endpoints.auth import _log_auth_event

        mock_audit_repo = Mock()

        # Call the function
        asyncio.run(
            _log_auth_event(
                audit_repo=mock_audit_repo,
                action="login_success",
                username="admin",
                ip_address="127.0.0.1",
                success=True,
                details="Login successful",
            )
        )

        # Verify the repository was called
        mock_audit_repo.create_log.assert_called_once()

    def test_log_auth_event_exception(self):
        """An audit write failure is logged, not raised."""
        from mimir.api.endpoints.auth import _log_auth_event

        mock_audit_repo = Mock()
        mock_audit_repo.create_log.side_effect = OperationalError(
            "INSERT", {}, Exception("database is locked")
        )

        # A database failure of the audit write never locks the admin out
        asyncio.run(
            _log_auth_event(
                audit_repo=mock_audit_repo,
                action="login_failed",
                username="admin",
                ip_address="127.0.0.1",
                success=False,
                details="Login failed",
            )
        )
        mock_audit_repo.create_log.assert_called_once()


class TestTokenRefresh:
    """Tests for token refresh."""

    @patch("mimir.api.endpoints.auth.jwt_handler")
    @patch("mimir.api.endpoints.auth.settings")
    @patch("mimir.api.endpoints.auth._log_auth_event")
    def test_refresh_token_success(self, mock_log_event, mock_settings, mock_jwt):
        """Test successful token refresh."""
        from mimir.api.endpoints.auth import refresh_token

        # Configure mocks
        mock_user = {"sub": "admin", "user_type": "admin"}
        mock_jwt.create_access_token.return_value = "new_token"
        mock_settings.jwt_expiration_hours = 24

        mock_request = Mock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}

        mock_audit_repo = AsyncMock()

        # Call the function
        result = asyncio.run(
            refresh_token(request=mock_request, current_user=mock_user, audit_repo=mock_audit_repo)
        )

        # Assertions
        assert result.access_token == "new_token"
        assert result.token_type == "bearer"


class TestLogout:
    """Tests for logout."""

    @patch("mimir.api.endpoints.auth._log_auth_event")
    def test_logout_success(self, mock_log_event):
        """Test successful logout."""
        from mimir.api.endpoints.auth import logout

        # Configure mocks
        mock_user = {"sub": "admin", "user_type": "admin"}

        mock_request = Mock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}

        mock_audit_repo = AsyncMock()

        # Call the function
        result = asyncio.run(
            logout(request=mock_request, current_user=mock_user, audit_repo=mock_audit_repo)
        )

        # Assertions
        assert result["message"] == "Successfully logged out"


class TestAuthIntegration:
    """Integration tests for authentication."""

    @patch("mimir.api.endpoints.auth._authenticate_admin")
    @patch("mimir.api.endpoints.auth.jwt_handler")
    @patch("mimir.api.endpoints.auth.settings")
    @patch("mimir.api.endpoints.auth._log_auth_event")
    def test_full_auth_workflow(self, mock_log_event, mock_settings, mock_jwt, mock_auth):
        """Test full authentication workflow."""
        from mimir.api.endpoints.auth import login, refresh_token, logout

        # Configure mocks
        mock_auth.return_value = True
        mock_jwt.create_access_token.return_value = "test_token"
        mock_settings.jwt_expiration_hours = 24

        mock_request = Mock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}

        mock_audit_repo = AsyncMock()
        mock_user = {"sub": "admin", "user_type": "admin"}

        login_data = LoginRequest(username="admin", password="test123")

        # Test login
        login_result = asyncio.run(
            login(
                request=mock_request,
                response=Mock(),  # required by slowapi header injection
                login_data=login_data,
                audit_repo=mock_audit_repo,
            )
        )

        assert login_result.access_token == "test_token"

        # Test refresh
        refresh_result = asyncio.run(
            refresh_token(request=mock_request, current_user=mock_user, audit_repo=mock_audit_repo)
        )
        assert refresh_result.access_token == "test_token"

        # Test logout
        logout_result = asyncio.run(
            logout(request=mock_request, current_user=mock_user, audit_repo=mock_audit_repo)
        )

        assert logout_result["message"] == "Successfully logged out"
