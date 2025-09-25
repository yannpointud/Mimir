"""
Tests pour le middleware de limitation de taux.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from fastapi import Request
from slowapi.errors import RateLimitExceeded

from src.api.middleware.rate_limit import (
    get_client_identifier,
    chat_rate_limit,
    admin_rate_limit,
    upload_rate_limit,
    auth_rate_limit,
    health_rate_limit,
    user_type_rate_limit,
    is_exempt_endpoint,
    ConditionalRateLimiter,
    conditional_limiter
)


class TestGetClientIdentifier:
    """Tests pour la fonction get_client_identifier."""

    def test_authenticated_user_identifier(self):
        """Test identifier pour utilisateur authentifié."""
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.jwt_payload = {
            'sub': 'user123',
            'user_type': 'user'
        }

        result = get_client_identifier(request)

        assert result == "user:user:user123"

    def test_authenticated_admin_identifier(self):
        """Test identifier pour admin authentifié."""
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.jwt_payload = {
            'sub': 'admin456',
            'user_type': 'admin'
        }

        result = get_client_identifier(request)

        assert result == "user:admin:admin456"

    def test_no_user_id_in_payload(self):
        """Test identifier quand pas d'user_id dans le payload."""
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.jwt_payload = {
            'user_type': 'user'
            # Pas de 'sub'
        }

        with patch('src.api.middleware.rate_limit.get_remote_address') as mock_get_ip:
            mock_get_ip.return_value = "192.168.1.1"
            result = get_client_identifier(request)

        assert result == "192.168.1.1"

    def test_no_jwt_payload(self):
        """Test identifier pour utilisateur non authentifié."""
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.jwt_payload = None

        with patch('src.api.middleware.rate_limit.get_remote_address') as mock_get_ip:
            mock_get_ip.return_value = "10.0.0.1"
            result = get_client_identifier(request)

        assert result == "10.0.0.1"

    def test_no_jwt_payload_in_state(self):
        """Test identifier quand state existe mais pas de jwt_payload."""
        # Créer un mock avec state vide (plus réaliste pour FastAPI)
        request = Mock()
        request.state = Mock()
        request.state.jwt_payload = None

        with patch('src.api.middleware.rate_limit.get_remote_address') as mock_get_ip:
            mock_get_ip.return_value = "172.16.0.1"
            result = get_client_identifier(request)

        assert result == "172.16.0.1"


class TestRateLimitDecorators:
    """Tests pour les décorateurs de limitation de taux."""

    @patch('src.api.middleware.rate_limit.settings')
    def test_chat_rate_limit_default(self, mock_settings):
        """Test limite par défaut pour chat."""
        # Simuler absence de setting
        mock_settings.chat_rate_limit_per_minute = 20

        decorator = chat_rate_limit()

        # Vérifier que c'est bien un décorateur limiter
        assert hasattr(decorator, '__call__')

    @patch('src.api.middleware.rate_limit.settings')
    def test_admin_rate_limit_default(self, mock_settings):
        """Test limite par défaut pour admin."""
        mock_settings.admin_rate_limit_per_minute = 100

        decorator = admin_rate_limit()

        assert hasattr(decorator, '__call__')

    @patch('src.api.middleware.rate_limit.settings')
    def test_upload_rate_limit_default(self, mock_settings):
        """Test limite par défaut pour upload."""
        mock_settings.upload_rate_limit_per_hour = 50

        decorator = upload_rate_limit()

        assert hasattr(decorator, '__call__')

    @patch('src.api.middleware.rate_limit.settings')
    def test_auth_rate_limit_default(self, mock_settings):
        """Test limite par défaut pour auth."""
        mock_settings.auth_rate_limit_per_minute = 5

        decorator = auth_rate_limit()

        assert hasattr(decorator, '__call__')

    def test_health_rate_limit(self):
        """Test limite pour health check."""
        decorator = health_rate_limit()

        assert hasattr(decorator, '__call__')

    @patch('src.api.middleware.rate_limit.settings')
    def test_chat_rate_limit_custom_setting(self, mock_settings):
        """Test limite personnalisée pour chat."""
        mock_settings.chat_rate_limit_per_minute = 30

        # Le decorator utilise getattr avec une valeur par défaut
        with patch('src.api.middleware.rate_limit.getattr') as mock_getattr:
            mock_getattr.return_value = 30
            decorator = chat_rate_limit()

        mock_getattr.assert_called_once_with(mock_settings, 'chat_rate_limit_per_minute', 20)

    @patch('src.api.middleware.rate_limit.settings')
    def test_admin_rate_limit_missing_setting(self, mock_settings):
        """Test limite admin avec setting manquant."""
        # Simuler un setting manquant
        with patch('src.api.middleware.rate_limit.getattr') as mock_getattr:
            mock_getattr.return_value = 100  # Valeur par défaut
            decorator = admin_rate_limit()

        mock_getattr.assert_called_once_with(mock_settings, 'admin_rate_limit_per_minute', 100)


class TestUserTypeRateLimit:
    """Tests pour la fonction user_type_rate_limit."""

    def test_admin_user_rate(self):
        """Test limite pour utilisateur admin."""
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.jwt_payload = {
            'user_type': 'admin'
        }

        result = user_type_rate_limit(request)

        assert result == "200/minute"

    def test_regular_user_rate(self):
        """Test limite pour utilisateur régulier."""
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.jwt_payload = {
            'user_type': 'user'
        }

        result = user_type_rate_limit(request)

        assert result == "50/minute"

    def test_unknown_user_type(self):
        """Test limite pour type d'utilisateur inconnu."""
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.jwt_payload = {
            'user_type': 'unknown_type'
        }

        result = user_type_rate_limit(request)

        assert result == "20/minute"  # Anonyme par défaut

    def test_anonymous_user_rate(self):
        """Test limite pour utilisateur anonyme."""
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.jwt_payload = None

        result = user_type_rate_limit(request)

        assert result == "20/minute"

    def test_no_jwt_payload_user_rate(self):
        """Test limite pour request avec state vide."""
        # Créer un mock avec state vide (plus réaliste pour FastAPI)
        request = Mock()
        request.state = Mock()
        request.state.jwt_payload = None

        result = user_type_rate_limit(request)

        assert result == "20/minute"


class TestIsExemptEndpoint:
    """Tests pour la fonction is_exempt_endpoint."""

    def test_health_endpoint_exempt(self):
        """Test exemption pour endpoint health."""
        request = Mock(spec=Request)
        request.url = Mock()
        request.url.path = "/health"

        result = is_exempt_endpoint(request)

        assert result is True

    def test_api_health_endpoint_exempt(self):
        """Test exemption pour endpoint API health."""
        request = Mock(spec=Request)
        request.url = Mock()
        request.url.path = "/api/v1/health/status"

        result = is_exempt_endpoint(request)

        assert result is True

    def test_docs_endpoint_exempt(self):
        """Test exemption pour documentation."""
        request = Mock(spec=Request)
        request.url = Mock()
        request.url.path = "/docs"

        result = is_exempt_endpoint(request)

        assert result is True

    def test_openapi_endpoint_exempt(self):
        """Test exemption pour OpenAPI JSON."""
        request = Mock(spec=Request)
        request.url = Mock()
        request.url.path = "/openapi.json"

        result = is_exempt_endpoint(request)

        assert result is True

    def test_redoc_endpoint_exempt(self):
        """Test exemption pour ReDoc."""
        request = Mock(spec=Request)
        request.url = Mock()
        request.url.path = "/redoc"

        result = is_exempt_endpoint(request)

        assert result is True

    def test_non_exempt_endpoint(self):
        """Test endpoint non-exempté."""
        request = Mock(spec=Request)
        request.url = Mock()
        request.url.path = "/api/v1/chat"

        result = is_exempt_endpoint(request)

        assert result is False

    def test_partial_match_non_exempt(self):
        """Test que seuls les préfixes exacts sont exemptés."""
        request = Mock(spec=Request)
        request.url = Mock()
        request.url.path = "/api/healthcheck"  # Ne commence pas par "/health"

        result = is_exempt_endpoint(request)

        assert result is False


class TestConditionalRateLimiter:
    """Tests pour la classe ConditionalRateLimiter."""

    def test_default_limit_initialization(self):
        """Test initialisation avec limite par défaut."""
        limiter = ConditionalRateLimiter()

        assert limiter.default_limit == "60/minute"

    def test_custom_default_limit(self):
        """Test initialisation avec limite personnalisée."""
        limiter = ConditionalRateLimiter(default_limit="100/hour")

        assert limiter.default_limit == "100/hour"

    @patch('src.api.middleware.rate_limit.is_exempt_endpoint')
    def test_exempt_endpoint_high_limit(self, mock_is_exempt):
        """Test limite élevée pour endpoint exempté."""
        mock_is_exempt.return_value = True

        limiter = ConditionalRateLimiter()
        request = Mock(spec=Request)

        result = limiter(request)

        assert result == "1000/minute"

    @patch('src.api.middleware.rate_limit.is_exempt_endpoint')
    @patch('src.api.middleware.rate_limit.user_type_rate_limit')
    def test_non_exempt_endpoint_user_type_limit(self, mock_user_type, mock_is_exempt):
        """Test utilisation de limite par type d'utilisateur."""
        mock_is_exempt.return_value = False
        mock_user_type.return_value = "50/minute"

        limiter = ConditionalRateLimiter()
        request = Mock(spec=Request)

        result = limiter(request)

        assert result == "50/minute"
        mock_user_type.assert_called_once_with(request)

    def test_global_conditional_limiter_instance(self):
        """Test instance globale du conditional limiter."""
        assert conditional_limiter is not None
        assert isinstance(conditional_limiter, ConditionalRateLimiter)
        assert conditional_limiter.default_limit == "60/minute"