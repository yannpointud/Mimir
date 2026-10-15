"""
Tests pour l'authentification middleware.

Ce module teste les composants d'authentification JWT, incluant
les tokens bearer, les dépendances utilisateur et les vérifications admin.
"""

import pytest
from unittest.mock import Mock, patch
from fastapi import HTTPException, status, Request
from fastapi.security import HTTPAuthorizationCredentials

from backend.src.auth.middleware import (
    JWTBearer,
    get_current_user,
    require_admin,
    get_optional_user,
)


class TestJWTBearer:
    """Tests pour la classe JWTBearer."""

    def test_init_default(self):
        """Test d'initialisation par défaut."""
        bearer = JWTBearer()
        assert bearer.auto_error is True

    def test_init_custom(self):
        """Test d'initialisation avec paramètres personnalisés."""
        bearer = JWTBearer(auto_error=False)
        assert bearer.auto_error is False

    @pytest.mark.asyncio
    async def test_call_valid_bearer_token(self):
        """Test avec un token Bearer valide."""
        mock_request = Mock(spec=Request)
        mock_request.state = Mock()

        with patch("fastapi.security.HTTPBearer.__call__") as mock_parent_call:
            mock_credentials = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="valid_token"
            )
            mock_parent_call.return_value = mock_credentials

            with patch("backend.src.auth.middleware.jwt_handler") as mock_jwt_handler:
                mock_payload = {"user_type": "admin", "exp": 1234567890}
                mock_jwt_handler.verify_token.return_value = mock_payload

                bearer = JWTBearer()
                result = await bearer(mock_request)

                assert result == mock_credentials
                assert mock_request.state.jwt_payload == mock_payload
                assert mock_request.state.user_type == "admin"

    @pytest.mark.asyncio
    async def test_call_invalid_scheme(self):
        """Test avec un schéma d'authentification invalide."""
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
        """Test avec un token invalide."""
        mock_request = Mock(spec=Request)

        with patch("fastapi.security.HTTPBearer.__call__") as mock_parent_call:
            mock_credentials = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="invalid_token"
            )
            mock_parent_call.return_value = mock_credentials

            with patch("backend.src.auth.middleware.jwt_handler") as mock_jwt_handler:
                mock_jwt_handler.verify_token.return_value = None

                bearer = JWTBearer()

                with pytest.raises(HTTPException) as exc_info:
                    await bearer(mock_request)

                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                assert "Invalid or expired token" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_call_no_credentials(self):
        """Test sans credentials."""
        mock_request = Mock(spec=Request)

        with patch("fastapi.security.HTTPBearer.__call__") as mock_parent_call:
            mock_parent_call.return_value = None

            bearer = JWTBearer()
            result = await bearer(mock_request)

            assert result is None

    @pytest.mark.asyncio
    async def test_call_jwt_handler_exception(self):
        """Test avec exception du JWT handler."""
        mock_request = Mock(spec=Request)

        with patch("fastapi.security.HTTPBearer.__call__") as mock_parent_call:
            mock_credentials = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="some_token"
            )
            mock_parent_call.return_value = mock_credentials

            with patch("backend.src.auth.middleware.jwt_handler") as mock_jwt_handler:
                mock_jwt_handler.verify_token.side_effect = Exception("JWT processing error")

                bearer = JWTBearer()

                with pytest.raises(Exception) as exc_info:
                    await bearer(mock_request)

                assert str(exc_info.value) == "JWT processing error"


class TestGetCurrentUser:
    """Tests pour la fonction get_current_user."""

    @pytest.mark.asyncio
    async def test_get_current_user_valid_token(self):
        """Test avec un token valide."""
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

        # get_current_user retourne seulement certains champs du payload
        expected = {"user_type": "admin", "sub": "admin123", "exp": 1234567890, "iat": 1234567800}
        assert result == expected

    @pytest.mark.asyncio
    async def test_get_current_user_invalid_token(self):
        """Test avec un token invalide."""
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
    """Tests pour la fonction require_admin."""

    @pytest.mark.asyncio
    async def test_require_admin_valid_admin(self):
        """Test avec un utilisateur admin valide."""
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
        """Test avec un utilisateur non admin."""
        current_user = {"user_type": "user", "sub": "user123", "exp": 1234567890, "iat": 1234567800}

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_admin_missing_user_type(self):
        """Test avec user_type manquant."""
        current_user = {"sub": "user123", "exp": 1234567890, "iat": 1234567800}

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_admin_none_user_type(self):
        """Test avec user_type None."""
        current_user = {"user_type": None, "sub": "user123", "exp": 1234567890, "iat": 1234567800}

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_admin_empty_user_type(self):
        """Test avec user_type vide."""
        current_user = {"user_type": "", "sub": "user123", "exp": 1234567890, "iat": 1234567800}

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_admin_case_sensitive(self):
        """Test que la vérification admin est sensible à la casse."""
        current_user = {
            "user_type": "Admin",  # Casse différente
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
        """Test avec un dictionnaire utilisateur malformé."""
        current_user = {}

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in exc_info.value.detail


class TestMiddlewareIntegration:
    """Tests d'intégration pour les middleware d'authentification."""

    @pytest.mark.asyncio
    async def test_full_authentication_flow_success(self):
        """Test du flux complet d'authentification réussi."""
        mock_request = Mock(spec=Request)
        mock_request.state = Mock()

        with patch("fastapi.security.HTTPBearer.__call__") as mock_parent_call:
            mock_credentials = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="valid_admin_token"
            )
            mock_parent_call.return_value = mock_credentials

            with patch("backend.src.auth.middleware.jwt_handler") as mock_jwt_handler:
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
        """Test du flux complet avec utilisateur non admin."""
        mock_request = Mock(spec=Request)
        mock_request.state = Mock()

        with patch("fastapi.security.HTTPBearer.__call__") as mock_parent_call:
            mock_credentials = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="valid_user_token"
            )
            mock_parent_call.return_value = mock_credentials

            with patch("backend.src.auth.middleware.jwt_handler") as mock_jwt_handler:
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
        """Test du comportement de logging."""
        mock_request = Mock(spec=Request)

        with patch("fastapi.security.HTTPBearer.__call__") as mock_parent_call:
            mock_credentials = HTTPAuthorizationCredentials(
                scheme="Basic", credentials="some_token"
            )
            mock_parent_call.return_value = mock_credentials

            with patch("backend.src.auth.middleware.logger") as mock_logger:
                bearer = JWTBearer()

                with pytest.raises(HTTPException):
                    await bearer(mock_request)

                mock_logger.warning.assert_called_once()
                call_args = mock_logger.warning.call_args[0][0]
                assert "Invalid authentication scheme" in call_args


class TestGetOptionalUser:
    """Tests pour la fonction get_optional_user."""

    @pytest.mark.asyncio
    async def test_get_optional_user_no_credentials(self):
        """Test avec credentials None - doit retourner None."""
        mock_request = Mock(spec=Request)

        result = await get_optional_user(mock_request, None)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_optional_user_no_payload(self):
        """Test avec payload absent - doit retourner None."""
        mock_request = Mock(spec=Request)
        mock_request.state = type("State", (), {})()  # Créer un objet sans attribut jwt_payload

        mock_credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="some_token")

        result = await get_optional_user(mock_request, mock_credentials)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_optional_user_valid_token(self):
        """Test avec token valide - doit retourner les infos user."""
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
