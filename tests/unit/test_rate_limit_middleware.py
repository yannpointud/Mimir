"""
Tests for the rate limiting module (SEC-03).
"""

import pytest  # noqa: F401
from unittest.mock import Mock, patch
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from src.api.middleware.rate_limit import (
    get_client_identifier,
    configure_rate_limiting,
    limiter,
)


class TestGetClientIdentifier:
    """Tests for the get_client_identifier function."""

    def test_authenticated_user_identifier(self):
        """Test identifier for authenticated user."""
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.jwt_payload = {
            'sub': 'user123',
            'user_type': 'user'
        }

        result = get_client_identifier(request)

        assert result == "user:user:user123"

    def test_authenticated_admin_identifier(self):
        """Test identifier for authenticated admin."""
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.jwt_payload = {
            'sub': 'admin456',
            'user_type': 'admin'
        }

        result = get_client_identifier(request)

        assert result == "user:admin:admin456"

    def test_no_user_id_in_payload(self):
        """Test identifier when no user_id in payload."""
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.jwt_payload = {
            'user_type': 'user'
            # No 'sub'
        }

        with patch('src.api.middleware.rate_limit.get_remote_address') as mock_get_ip:
            mock_get_ip.return_value = "192.168.1.1"
            result = get_client_identifier(request)

        assert result == "192.168.1.1"

    def test_no_jwt_payload(self):
        """Test identifier for unauthenticated user."""
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.jwt_payload = None

        with patch('src.api.middleware.rate_limit.get_remote_address') as mock_get_ip:
            mock_get_ip.return_value = "10.0.0.1"
            result = get_client_identifier(request)

        assert result == "10.0.0.1"

    def test_no_jwt_payload_in_state(self):
        """Test identifier when state exists but no jwt_payload."""
        # Create a mock with empty state (more realistic for FastAPI)
        request = Mock()
        request.state = Mock()
        request.state.jwt_payload = None

        with patch('src.api.middleware.rate_limit.get_remote_address') as mock_get_ip:
            mock_get_ip.return_value = "172.16.0.1"
            result = get_client_identifier(request)

        assert result == "172.16.0.1"


class TestConfigureRateLimiting:
    """Tests for the configure_rate_limiting setup function."""

    def test_no_asgi_middleware_registered(self):
        """configure_rate_limiting must NOT register any ASGI middleware (D-10)."""
        app = FastAPI()
        middleware_count_before = len(app.user_middleware)

        configure_rate_limiting(app)

        assert len(app.user_middleware) == middleware_count_before

    def test_limiter_attached_to_app_state(self):
        """The shared limiter singleton is attached to app.state."""
        app = FastAPI()

        configure_rate_limiting(app)

        assert app.state.limiter is limiter

    def test_limiter_constructor_configuration(self):
        """The limiter has headers injection enabled (required for Retry-After)."""
        assert limiter._headers_enabled is True


class TestRateLimitHandler:
    """Functional tests for the 429 exception handler."""

    def _build_app(self) -> FastAPI:
        """Build a minimal app with a tightly limited route."""
        app = FastAPI()
        configure_rate_limiting(app)

        # With headers_enabled=True, slowapi requires a `response` parameter
        # on decorated routes that do not return a Response object themselves
        @app.get("/limited")
        @limiter.limit("1/minute")
        async def limited(request: Request, response: Response):
            return {"ok": True}

        return app

    def test_429_returns_error_response_with_retry_after(self):
        """Exceeding the limit returns the project ErrorResponse JSON + Retry-After."""
        app = self._build_app()

        # Re-enable the limiter locally (the autouse conftest fixture disabled it)
        limiter.enabled = True
        limiter.reset()
        try:
            client = TestClient(app)

            first = client.get("/limited")
            assert first.status_code == 200

            second = client.get("/limited")
            assert second.status_code == 429

            body = second.json()
            assert body["success"] is False
            assert body["error_code"] == "HTTP_429"
            assert "1 per 1 minute" in body["error_message"]
            assert body["details"]["path"] == "/limited"
            assert "timestamp" in body

            # Retry-After is injected by the limiter (headers_enabled=True)
            assert "Retry-After" in second.headers
            assert int(second.headers["Retry-After"]) >= 0
        finally:
            limiter.enabled = False
            limiter.reset()

    def test_disabled_limiter_never_blocks(self):
        """With the limiter disabled (kill-switch), repeated calls all pass."""
        app = self._build_app()
        client = TestClient(app)

        # The autouse fixture keeps limiter.enabled = False here
        for _ in range(3):
            response = client.get("/limited")
            assert response.status_code == 200
