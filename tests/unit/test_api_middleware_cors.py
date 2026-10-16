"""
Unit tests of api/middleware/cors.py

Tests of the CORS middleware configuration.
"""

from unittest.mock import Mock, patch

from mimir.api.middleware.cors import configure_cors_middleware


class TestConfigureCorsMiddleware:
    """configure_cors_middleware tests."""

    def test_configure_cors_production(self):
        """Test de configuration CORS en production."""
        mock_app = Mock()

        with patch("mimir.api.middleware.cors.settings") as mock_settings:
            mock_settings.is_production = True
            mock_settings.allowed_origins = None  # No custom origins

            configure_cors_middleware(mock_app)

            # Check that add_middleware was called
            mock_app.add_middleware.assert_called_once()
            args, kwargs = mock_app.add_middleware.call_args

            # Check the arguments
            from fastapi.middleware.cors import CORSMiddleware

            assert args[0] == CORSMiddleware

            # Check the origins allowed in production
            allowed_origins = kwargs["allow_origins"]
            assert "https://localhost" in allowed_origins
            assert "https://127.0.0.1" in allowed_origins
            assert "https://localhost:3000" in allowed_origins

            # Check other parameters
            assert kwargs["allow_credentials"] is True
            assert "GET" in kwargs["allow_methods"]
            assert "POST" in kwargs["allow_methods"]
            assert "Authorization" in kwargs["allow_headers"]
            assert kwargs["max_age"] == 600

    def test_configure_cors_production_with_custom_origins(self):
        mock_app = Mock()

        with patch("mimir.api.middleware.cors.settings") as mock_settings:
            mock_settings.is_production = True
            mock_settings.allowed_origins = "https://example.com,https://app.example.com"

            configure_cors_middleware(mock_app)

            kwargs = mock_app.add_middleware.call_args.kwargs
            allowed_origins = kwargs["allow_origins"]

            # Check that the custom origins are added
            assert "https://example.com" in allowed_origins
            assert "https://app.example.com" in allowed_origins
            # And the default origins are still there
            assert "https://localhost" in allowed_origins

    def test_configure_cors_development(self):
        mock_app = Mock()

        with patch("mimir.api.middleware.cors.settings") as mock_settings:
            mock_settings.is_production = False

            configure_cors_middleware(mock_app)

            kwargs = mock_app.add_middleware.call_args.kwargs
            allowed_origins = kwargs["allow_origins"]

            # Check the development origins
            assert "http://localhost:3000" in allowed_origins
            assert "http://localhost:3001" in allowed_origins
            assert "http://127.0.0.1:3000" in allowed_origins
            assert "http://127.0.0.1:3001" in allowed_origins
            assert "http://localhost:8080" in allowed_origins
            assert "http://127.0.0.1:8080" in allowed_origins

            # Check that there is no HTTPS origin in development
            https_origins = [origin for origin in allowed_origins if origin.startswith("https://")]
            assert len(https_origins) == 0

    def test_configure_cors_allowed_methods(self):
        mock_app = Mock()

        with patch("mimir.api.middleware.cors.settings") as mock_settings:
            mock_settings.is_production = False

            configure_cors_middleware(mock_app)

            kwargs = mock_app.add_middleware.call_args.kwargs
            allowed_methods = kwargs["allow_methods"]

            expected_methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
            for method in expected_methods:
                assert method in allowed_methods

    def test_configure_cors_allowed_headers(self):
        mock_app = Mock()

        with patch("mimir.api.middleware.cors.settings") as mock_settings:
            mock_settings.is_production = False

            configure_cors_middleware(mock_app)

            kwargs = mock_app.add_middleware.call_args.kwargs
            allowed_headers = kwargs["allow_headers"]

            expected_headers = [
                "Accept",
                "Accept-Language",
                "Content-Language",
                "Content-Type",
                "Authorization",
                "X-Requested-With",
                "X-Request-ID",
            ]

            for header in expected_headers:
                assert header in allowed_headers

    def test_configure_cors_expose_headers(self):
        mock_app = Mock()

        with patch("mimir.api.middleware.cors.settings") as mock_settings:
            mock_settings.is_production = False

            configure_cors_middleware(mock_app)

            kwargs = mock_app.add_middleware.call_args.kwargs
            expose_headers = kwargs["expose_headers"]

            assert "X-Request-ID" in expose_headers
            assert "X-Response-Time" in expose_headers

    def test_configure_cors_credentials(self):
        mock_app = Mock()

        with patch("mimir.api.middleware.cors.settings") as mock_settings:
            mock_settings.is_production = False

            configure_cors_middleware(mock_app)

            kwargs = mock_app.add_middleware.call_args.kwargs

            assert kwargs["allow_credentials"] is True

    def test_configure_cors_max_age(self):
        mock_app = Mock()

        with patch("mimir.api.middleware.cors.settings") as mock_settings:
            mock_settings.is_production = False

            configure_cors_middleware(mock_app)

            kwargs = mock_app.add_middleware.call_args.kwargs

            assert kwargs["max_age"] == 600  # 10 minutes

    def test_configure_cors_logging_production(self):
        mock_app = Mock()

        with (
            patch("mimir.api.middleware.cors.settings") as mock_settings,
            patch("mimir.api.middleware.cors.logger") as mock_logger,
        ):
            mock_settings.is_production = True
            mock_settings.allowed_origins = None

            configure_cors_middleware(mock_app)

            # Check that the production message was logged
            mock_logger.info.assert_called_once()
            log_message = mock_logger.info.call_args[0][0]
            assert "CORS configured for production" in log_message
            assert "allowed origins" in log_message

    def test_configure_cors_logging_development(self):
        mock_app = Mock()

        with (
            patch("mimir.api.middleware.cors.settings") as mock_settings,
            patch("mimir.api.middleware.cors.logger") as mock_logger,
        ):
            mock_settings.is_production = False

            configure_cors_middleware(mock_app)

            # Check that the development message was logged
            mock_logger.info.assert_called_once()
            log_message = mock_logger.info.call_args[0][0]
            assert "CORS configured for development" in log_message
            assert "permissive settings" in log_message

    def test_configure_cors_custom_origins_parsing(self):
        mock_app = Mock()

        with patch("mimir.api.middleware.cors.settings") as mock_settings:
            mock_settings.is_production = True
            # Spaces and commas
            mock_settings.allowed_origins = (
                "https://site1.com, https://site2.com ,https://site3.com"
            )

            configure_cors_middleware(mock_app)

            kwargs = mock_app.add_middleware.call_args.kwargs
            allowed_origins = kwargs["allow_origins"]

            # The origins must be parsed correctly
            assert "https://site1.com" in allowed_origins
            assert " https://site2.com " in allowed_origins  # Spaces kept
            assert "https://site3.com" in allowed_origins

    def test_configure_cors_empty_custom_origins(self):
        mock_app = Mock()

        with patch("mimir.api.middleware.cors.settings") as mock_settings:
            mock_settings.is_production = True
            mock_settings.allowed_origins = ""  # Empty string

            configure_cors_middleware(mock_app)

            kwargs = mock_app.add_middleware.call_args.kwargs
            allowed_origins = kwargs["allow_origins"]

            # Only the default origins must be present
            assert len(allowed_origins) == 3  # 3 default origins


class TestCorsIntegration:
    """Integration tests of the CORS middleware."""

    def test_cors_middleware_integration_with_fastapi(self):
        from fastapi import FastAPI

        app = FastAPI()

        with patch("mimir.api.middleware.cors.settings") as mock_settings:
            mock_settings.is_production = False

            # The configuration should not raise
            configure_cors_middleware(app)

            # Check that the middleware was added
            assert len(app.user_middleware) > 0

    def test_cors_different_environments(self):
        mock_app_prod = Mock()
        mock_app_dev = Mock()

        # Configuration production
        with patch("mimir.api.middleware.cors.settings") as mock_settings:
            mock_settings.is_production = True
            mock_settings.allowed_origins = None

            configure_cors_middleware(mock_app_prod)

        # Development configuration
        with patch("mimir.api.middleware.cors.settings") as mock_settings:
            mock_settings.is_production = False

            configure_cors_middleware(mock_app_dev)

        # Compare the configurations
        prod_kwargs = mock_app_prod.add_middleware.call_args[1]
        dev_kwargs = mock_app_dev.add_middleware.call_args[1]

        prod_origins = prod_kwargs["allow_origins"]
        dev_origins = dev_kwargs["allow_origins"]

        # Check the differences
        assert any(origin.startswith("https://") for origin in prod_origins)
        assert all(origin.startswith("http://") for origin in dev_origins)
        assert len(dev_origins) > len(prod_origins)  # Plus d'origines en dev
