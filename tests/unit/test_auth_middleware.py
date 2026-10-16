"""
Authentication middleware tests.

Tests of the JWT authentication components, including
bearer tokens, user dependencies and admin checks.
"""

from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials

from mimir.auth.middleware import (
    JWTBearer,
    get_current_user,
    get_optional_user,
    require_admin,
)


class TestJWTBearer:
    """JWTBearer tests."""

    def test_init_default(self):
        bearer = JWTBearer()
        assert bearer.auto_error is True

    def test_init_custom(self):
        bearer = JWTBearer(auto_error=False)
        assert bearer.auto_error is False

    @pytest.mark.asyncio
    async def test_call_valid_bearer_token(self):
        mock_request = Mock(spec=Request)
        mock_request.state = Mock()

        with patch("fastapi.security.HTTPBearer.__call__") as mock_parent_call:
            mock_credentials = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="valid_token"
            )
            mock_parent_call.return_value = mock_credentials

            with patch("mimir.auth.middleware.jwt_handler") as mock_jwt_handler:
                mock_payload = {"user_type": "admin", "exp": 1234567890}
                mock_jwt_handler.verify_token.return_value = mock_payload

                bearer = JWTBearer()
                result = await bearer(mock_request)

                assert result == mock_credentials
                assert mock_request.state.jwt_payload == mock_payload
                assert mock_request.state.user_type == "admin"

    @pytest.mark.asyncio
    async def test_call_invalid_scheme(self):
        mock_request = Mock(spec=Request)

        with patch("fastapi.security.HTTPBearer.__call__") as mock_parent_call:
            mock_credentials = HTTPAuthorizationCredentials(
                scheme="Basic", credentials="some_token"
            )
            mock_parent_call.return_value = mock_credentials

            bearer = JWTBearer()

            with pytest.raises(HTTPException) as exc_info:
                await bearer(mock_request)

            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
            assert "Invalid authentication scheme. Expected 'Bearer'" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_call_invalid_token(self):
        mock_request = Mock(spec=Request)

        with patch("fastapi.security.HTTPBearer.__call__") as mock_parent_call:
            mock_credentials = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="invalid_token"
            )
            mock_parent_call.return_value = mock_credentials

            with patch("mimir.auth.middleware.jwt_handler") as mock_jwt_handler:
                mock_jwt_handler.verify_token.return_value = None

                bearer = JWTBearer()

                with pytest.raises(HTTPException) as exc_info:
                    await bearer(mock_request)

                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                assert "Invalid or expired token" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_call_no_credentials(self):
        mock_request = Mock(spec=Request)

        with patch("fastapi.security.HTTPBearer.__call__") as mock_parent_call:
            mock_parent_call.return_value = None

            bearer = JWTBearer()
            result = await bearer(mock_request)

            assert result is None

    @pytest.mark.asyncio
    async def test_call_jwt_handler_exception(self):
        mock_request = Mock(spec=Request)

        with patch("fastapi.security.HTTPBearer.__call__") as mock_parent_call:
            mock_credentials = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="some_token"
            )
            mock_parent_call.return_value = mock_credentials

            with patch("mimir.auth.middleware.jwt_handler") as mock_jwt_handler:
                mock_jwt_handler.verify_token.side_effect = Exception("JWT processing error")

                bearer = JWTBearer()

                with pytest.raises(Exception) as exc_info:
                    await bearer(mock_request)

                assert str(exc_info.value) == "JWT processing error"


class TestGetCurrentUser:
    """get_current_user tests."""

    @pytest.mark.asyncio
    async def test_get_current_user_valid_token(self):
        mock_request = Mock(spec=Request)
        mock_request.state = Mock()
        payload = {
            "username": "admin",
            "user_type": "admin",
            "exp": 1234567890,
            "sub": "admin123",
            "iat": 1234567800,
        }
        mock_request.state.jwt_payload = payload

        mock_credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_token")

        result = await get_current_user(mock_request, mock_credentials)

        # get_current_user returns only some fields of the payload
        expected = {"user_type": "admin", "sub": "admin123", "exp": 1234567890, "iat": 1234567800}
        assert result == expected

    @pytest.mark.asyncio
    async def test_get_current_user_invalid_token(self):
        mock_request = Mock(spec=Request)
        mock_request.state = Mock()
        mock_request.state.jwt_payload = None

        mock_credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="invalid_token"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(mock_request, mock_credentials)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Authentication required" in exc_info.value.detail


class TestRequireAdmin:
    """require_admin tests."""

    @pytest.mark.asyncio
    async def test_require_admin_valid_admin(self):
        current_user = {
            "user_type": "admin",
            "sub": "admin123",
            "exp": 1234567890,
            "iat": 1234567800,
        }

        result = await require_admin(current_user)
        assert result == current_user

    @pytest.mark.asyncio
    async def test_require_admin_non_admin(self):
        current_user = {"user_type": "user", "sub": "user123", "exp": 1234567890, "iat": 1234567800}

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_admin_missing_user_type(self):
        current_user = {"sub": "user123", "exp": 1234567890, "iat": 1234567800}

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_admin_none_user_type(self):
        current_user = {"user_type": None, "sub": "user123", "exp": 1234567890, "iat": 1234567800}

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_admin_empty_user_type(self):
        current_user = {"user_type": "", "sub": "user123", "exp": 1234567890, "iat": 1234567800}

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_admin_case_sensitive(self):
        current_user = {
            "user_type": "Admin",  # Different case
            "sub": "user123",
            "exp": 1234567890,
            "iat": 1234567800,
        }

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_admin_malformed_user(self):
        current_user = {}

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in exc_info.value.detail


class TestMiddlewareIntegration:
    """Integration tests of the authentication middleware."""

    @pytest.mark.asyncio
    async def test_full_authentication_flow_success(self):
        mock_request = Mock(spec=Request)
        mock_request.state = Mock()

        with patch("fastapi.security.HTTPBearer.__call__") as mock_parent_call:
            mock_credentials = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="valid_admin_token"
            )
            mock_parent_call.return_value = mock_credentials

            with patch("mimir.auth.middleware.jwt_handler") as mock_jwt_handler:
                mock_payload = {
                    "user_type": "admin",
                    "sub": "admin123",
                    "exp": 1234567890,
                    "iat": 1234567800,
                }
                mock_jwt_handler.verify_token.return_value = mock_payload

                # Test JWTBearer
                bearer = JWTBearer()
                credentials = await bearer(mock_request)
                assert credentials == mock_credentials
                assert mock_request.state.jwt_payload == mock_payload

                # Test get_current_user
                user = await get_current_user(mock_request, credentials)
                expected_user = {
                    "user_type": "admin",
                    "sub": "admin123",
                    "exp": 1234567890,
                    "iat": 1234567800,
                }
                assert user == expected_user

                # Test require_admin
                admin_user = await require_admin(user)
                assert admin_user == user

    @pytest.mark.asyncio
    async def test_full_authentication_flow_non_admin(self):
        mock_request = Mock(spec=Request)
        mock_request.state = Mock()

        with patch("fastapi.security.HTTPBearer.__call__") as mock_parent_call:
            mock_credentials = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="valid_user_token"
            )
            mock_parent_call.return_value = mock_credentials

            with patch("mimir.auth.middleware.jwt_handler") as mock_jwt_handler:
                mock_payload = {
                    "user_type": "user",
                    "sub": "user123",
                    "exp": 1234567890,
                    "iat": 1234567800,
                }
                mock_jwt_handler.verify_token.return_value = mock_payload

                # Test JWTBearer
                bearer = JWTBearer()
                credentials = await bearer(mock_request)
                assert mock_request.state.jwt_payload == mock_payload

                # Test get_current_user
                user = await get_current_user(mock_request, credentials)
                expected_user = {
                    "user_type": "user",
                    "sub": "user123",
                    "exp": 1234567890,
                    "iat": 1234567800,
                }
                assert user == expected_user

                # Test require_admin should fail
                with pytest.raises(HTTPException) as exc_info:
                    await require_admin(user)

                assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
                assert "Admin privileges required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_logging_behavior(self):
        mock_request = Mock(spec=Request)

        with patch("fastapi.security.HTTPBearer.__call__") as mock_parent_call:
            mock_credentials = HTTPAuthorizationCredentials(
                scheme="Basic", credentials="some_token"
            )
            mock_parent_call.return_value = mock_credentials

            with patch("mimir.auth.middleware.logger") as mock_logger:
                bearer = JWTBearer()

                with pytest.raises(HTTPException):
                    await bearer(mock_request)

                mock_logger.warning.assert_called_once()
                call_args = mock_logger.warning.call_args[0][0]
                assert "Invalid authentication scheme" in call_args


class TestGetOptionalUser:
    """get_optional_user tests."""

    @pytest.mark.asyncio
    async def test_get_optional_user_no_credentials(self):
        mock_request = Mock(spec=Request)

        result = await get_optional_user(mock_request, None)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_optional_user_no_payload(self):
        mock_request = Mock(spec=Request)
        mock_request.state = type(
            "State", (), {}
        )()  # Create an object without a jwt_payload attribute

        mock_credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="some_token")

        result = await get_optional_user(mock_request, mock_credentials)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_optional_user_valid_token(self):
        mock_request = Mock(spec=Request)
        mock_request.state = Mock()
        payload = {
            "username": "testuser",
            "user_type": "user",
            "exp": 1234567890,
            "sub": "user123",
            "iat": 1234567800,
        }
        mock_request.state.jwt_payload = payload

        mock_credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_token")

        result = await get_optional_user(mock_request, mock_credentials)

        expected = {"user_type": "user", "sub": "user123", "exp": 1234567890, "iat": 1234567800}
        assert result == expected
