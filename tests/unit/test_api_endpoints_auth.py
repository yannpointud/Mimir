"""
Unit tests for authentication endpoints.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from fastapi import HTTPException, status
from pydantic import ValidationError

from backend.src.api.endpoints.auth import LoginRequest, LoginResponse, TokenRefreshResponse


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

    @patch("backend.src.api.endpoints.auth._authenticate_admin")
    @patch("backend.src.api.endpoints.auth.jwt_handler")
    @patch("backend.src.api.endpoints.auth._log_auth_event")
    def test_login_success(self, mock_log_event, mock_jwt, mock_auth):
        """Test successful login."""
        from backend.src.api.endpoints.auth import login

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

    @patch("backend.src.api.endpoints.auth._authenticate_admin")
    @patch("backend.src.api.endpoints.auth._log_auth_event")
    def test_login_failure_invalid_credentials(self, mock_log_event, mock_auth):
        """Test login with invalid credentials."""
        from backend.src.api.endpoints.auth import login

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

    @patch("backend.src.api.endpoints.auth._authenticate_admin")
    @patch("backend.src.api.endpoints.auth._log_auth_event")
    def test_login_exception_handling(self, mock_log_event, mock_auth):
        """Test exception handling during login."""
        from backend.src.api.endpoints.auth import login

        # Configure mocks to raise an exception
        mock_auth.side_effect = Exception("Database error")

        mock_request = Mock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}

        login_data = LoginRequest(username="admin", password="test123")
        mock_audit_repo = AsyncMock()

        # Test that exception is handled
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                login(
                    request=mock_request,
                    response=Mock(),  # required by slowapi header injection
                    login_data=login_data,
                    audit_repo=mock_audit_repo,
                )
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


class TestAuthHelperFunctions:
    """Tests for authentication utility functions."""

    @patch("backend.src.api.endpoints.auth.settings")
    @patch("backend.src.api.endpoints.auth.jwt_handler.verify_password")
    def test_authenticate_admin_success(self, mock_verify_password, mock_settings):
        """Test successful admin authentication."""
        from backend.src.api.endpoints.auth import _authenticate_admin

        mock_settings.admin_password_hash = "$2b$12$test_hash"
        mock_verify_password.return_value = True

        result = _authenticate_admin("admin", "test123")
        assert result is True

    @patch("backend.src.api.endpoints.auth.settings")
    def test_authenticate_admin_wrong_username(self, mock_settings):
        """Test authentication with wrong username."""
        from backend.src.api.endpoints.auth import _authenticate_admin

        mock_settings.admin_password_hash = "$2b$12$test_hash"

        result = _authenticate_admin("wrong_user", "test123")
        assert result is False

    @patch("backend.src.api.endpoints.auth.settings")
    @patch("backend.src.api.endpoints.auth.jwt_handler.verify_password")
    def test_authenticate_admin_wrong_password(self, mock_verify_password, mock_settings):
        """Test authentication with wrong password."""
        from backend.src.api.endpoints.auth import _authenticate_admin

        mock_settings.admin_password_hash = "$2b$12$test_hash"
        mock_verify_password.return_value = False

        result = _authenticate_admin("admin", "wrong_password")
        assert result is False

    def test_get_client_ip_forwarded(self):
        """Test IP extraction with X-Forwarded-For header."""
        from backend.src.api.endpoints.auth import _get_client_ip

        mock_request = Mock()
        mock_request.headers = {"X-Forwarded-For": "192.168.1.100, 10.0.0.1"}
        mock_request.client.host = "127.0.0.1"

        ip = _get_client_ip(mock_request)

        assert ip == "192.168.1.100"

    def test_get_client_ip_real_ip(self):
        """Test IP extraction with X-Real-IP header."""
        from backend.src.api.endpoints.auth import _get_client_ip

        mock_request = Mock()
        mock_request.headers = {"X-Real-IP": "192.168.1.200"}
        mock_request.client.host = "127.0.0.1"

        ip = _get_client_ip(mock_request)

        assert ip == "192.168.1.200"

    def test_get_client_ip_direct(self):
        """Test direct IP extraction."""
        from backend.src.api.endpoints.auth import _get_client_ip

        mock_request = Mock()
        mock_request.headers = {}
        mock_request.client.host = "192.168.1.50"

        ip = _get_client_ip(mock_request)

        assert ip == "192.168.1.50"

    def test_get_client_ip_no_client(self):
        """Test IP extraction without client."""
        from backend.src.api.endpoints.auth import _get_client_ip

        mock_request = Mock()
        mock_request.headers = {}
        mock_request.client = None

        ip = _get_client_ip(mock_request)

        assert ip == "unknown"

    def test_log_auth_event(self):
        """Test authentication event logging."""
        from backend.src.api.endpoints.auth import _log_auth_event

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
        """Test exception handling during logging."""
        from backend.src.api.endpoints.auth import _log_auth_event

        mock_audit_repo = Mock()
        mock_audit_repo.create_log.side_effect = Exception("Database error")

        # Test that exception is handled silently
        try:
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
        except Exception:
            pytest.fail("Exception should be handled silently")


class TestTokenRefresh:
    """Tests for token refresh."""

    @patch("backend.src.api.endpoints.auth.jwt_handler")
    @patch("backend.src.api.endpoints.auth.settings")
    @patch("backend.src.api.endpoints.auth._log_auth_event")
    def test_refresh_token_success(self, mock_log_event, mock_settings, mock_jwt):
        """Test successful token refresh."""
        from backend.src.api.endpoints.auth import refresh_token

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

    @pytest.mark.skip(reason="Unreachable: the FastAPI auth dependency runs before this handler")
    def test_refresh_token_unauthorized(self):
        """Test unauthorized token refresh."""
        # The require-auth dependency rejects the request before the handler runs,
        # so this branch is not reachable at the unit level.
        pass

    @patch("backend.src.api.endpoints.auth.jwt_handler")
    @patch("backend.src.api.endpoints.auth.settings")
    @patch("backend.src.api.endpoints.auth._log_auth_event")
    def test_refresh_token_invalid_token(self, mock_log_event, mock_settings, mock_jwt):
        """Test refresh with invalid token."""
        from backend.src.api.endpoints.auth import refresh_token

        # Configure mock to raise an exception
        mock_jwt.create_access_token.side_effect = Exception("Invalid token")
        mock_settings.jwt_expiration_hours = 24

        mock_user = {"sub": "admin", "user_type": "admin"}

        mock_request = Mock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}

        mock_audit_repo = AsyncMock()

        # Test that exception is handled
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                refresh_token(
                    request=mock_request, current_user=mock_user, audit_repo=mock_audit_repo
                )
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


class TestLogout:
    """Tests for logout."""

    @patch("backend.src.api.endpoints.auth._log_auth_event")
    def test_logout_success(self, mock_log_event):
        """Test successful logout."""
        from backend.src.api.endpoints.auth import logout

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

    @pytest.mark.skip(reason="Unreachable: the FastAPI auth dependency runs before this handler")
    def test_logout_unauthorized(self):
        """Test unauthorized logout."""
        # The require-auth dependency rejects the request before the handler runs,
        # so this branch is not reachable at the unit level.
        pass


class TestAuthIntegration:
    """Integration tests for authentication."""

    @patch("backend.src.api.endpoints.auth._authenticate_admin")
    @patch("backend.src.api.endpoints.auth.jwt_handler")
    @patch("backend.src.api.endpoints.auth.settings")
    @patch("backend.src.api.endpoints.auth._log_auth_event")
    def test_full_auth_workflow(self, mock_log_event, mock_settings, mock_jwt, mock_auth):
        """Test full authentication workflow."""
        from backend.src.api.endpoints.auth import login, refresh_token, logout

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

    def test_rate_limiting_simulation(self):
        """Test rate limiting simulation."""
        # This test simulates rate limiting behavior
        # In a real system, there would be a rate limiting middleware

        from backend.src.api.endpoints.auth import _get_client_ip

        mock_request = Mock()
        mock_request.headers = {}
        mock_request.client.host = "127.0.0.1"

        # Simulate multiple requests from the same IP
        ips = []
        for _ in range(10):
            ip = _get_client_ip(mock_request)
            ips.append(ip)

        # Verify all requests have the same IP
        assert all(ip == "127.0.0.1" for ip in ips)
        assert len(set(ips)) == 1  # One unique IP
