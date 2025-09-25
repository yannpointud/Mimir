"""
Tests unitaires pour le module api/middleware/cors.py

Ces tests couvrent la configuration du middleware CORS.
"""

import pytest
from unittest.mock import Mock, patch, call

from backend.src.api.middleware.cors import configure_cors_middleware


class TestConfigureCorsMiddleware:
    """Tests pour la fonction configure_cors_middleware."""

    def test_configure_cors_production(self):
        """Test de configuration CORS en production."""
        mock_app = Mock()

        with patch('backend.src.api.middleware.cors.settings') as mock_settings:
            mock_settings.is_production = True
            mock_settings.allowed_origins = None  # Pas d'origines personnalisées

            configure_cors_middleware(mock_app)

            # Vérifier que add_middleware a été appelé
            mock_app.add_middleware.assert_called_once()
            args, kwargs = mock_app.add_middleware.call_args

            # Vérifier les arguments
            from fastapi.middleware.cors import CORSMiddleware
            assert args[0] == CORSMiddleware

            # Vérifier les origines autorisées en production
            allowed_origins = kwargs['allow_origins']
            assert "https://localhost" in allowed_origins
            assert "https://127.0.0.1" in allowed_origins
            assert "https://localhost:3000" in allowed_origins

            # Vérifier d'autres paramètres
            assert kwargs['allow_credentials'] is True
            assert "GET" in kwargs['allow_methods']
            assert "POST" in kwargs['allow_methods']
            assert "Authorization" in kwargs['allow_headers']
            assert kwargs['max_age'] == 600

    def test_configure_cors_production_with_custom_origins(self):
        """Test de configuration CORS en production avec origines personnalisées."""
        mock_app = Mock()

        with patch('backend.src.api.middleware.cors.settings') as mock_settings:
            mock_settings.is_production = True
            mock_settings.allowed_origins = "https://example.com,https://app.example.com"

            configure_cors_middleware(mock_app)

            args, kwargs = mock_app.add_middleware.call_args
            allowed_origins = kwargs['allow_origins']

            # Vérifier que les origines personnalisées sont ajoutées
            assert "https://example.com" in allowed_origins
            assert "https://app.example.com" in allowed_origins
            # Et que les origines par défaut sont toujours là
            assert "https://localhost" in allowed_origins

    def test_configure_cors_production_without_custom_origins_attr(self):
        """Test en production sans attribut allowed_origins."""
        mock_app = Mock()

        with patch('backend.src.api.middleware.cors.settings') as mock_settings:
            mock_settings.is_production = True
            # Pas d'attribut allowed_origins

            configure_cors_middleware(mock_app)

            args, kwargs = mock_app.add_middleware.call_args
            allowed_origins = kwargs['allow_origins']

            # Seules les origines par défaut doivent être présentes
            assert "https://localhost" in allowed_origins
            assert len(allowed_origins) == 3  # Les 3 origines par défaut

    def test_configure_cors_development(self):
        """Test de configuration CORS en développement."""
        mock_app = Mock()

        with patch('backend.src.api.middleware.cors.settings') as mock_settings:
            mock_settings.is_production = False

            configure_cors_middleware(mock_app)

            args, kwargs = mock_app.add_middleware.call_args
            allowed_origins = kwargs['allow_origins']

            # Vérifier les origines de développement
            assert "http://localhost:3000" in allowed_origins
            assert "http://localhost:3001" in allowed_origins
            assert "http://127.0.0.1:3000" in allowed_origins
            assert "http://127.0.0.1:3001" in allowed_origins
            assert "http://localhost:8080" in allowed_origins
            assert "http://127.0.0.1:8080" in allowed_origins

            # Vérifier qu'il n'y a pas d'origines HTTPS en dev
            https_origins = [origin for origin in allowed_origins if origin.startswith("https://")]
            assert len(https_origins) == 0

    def test_configure_cors_allowed_methods(self):
        """Test des méthodes HTTP autorisées."""
        mock_app = Mock()

        with patch('backend.src.api.middleware.cors.settings') as mock_settings:
            mock_settings.is_production = False

            configure_cors_middleware(mock_app)

            args, kwargs = mock_app.add_middleware.call_args
            allowed_methods = kwargs['allow_methods']

            expected_methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
            for method in expected_methods:
                assert method in allowed_methods

    def test_configure_cors_allowed_headers(self):
        """Test des headers autorisés."""
        mock_app = Mock()

        with patch('backend.src.api.middleware.cors.settings') as mock_settings:
            mock_settings.is_production = False

            configure_cors_middleware(mock_app)

            args, kwargs = mock_app.add_middleware.call_args
            allowed_headers = kwargs['allow_headers']

            expected_headers = [
                "Accept",
                "Accept-Language",
                "Content-Language",
                "Content-Type",
                "Authorization",
                "X-Requested-With",
                "X-Request-ID"
            ]

            for header in expected_headers:
                assert header in allowed_headers

    def test_configure_cors_expose_headers(self):
        """Test des headers exposés."""
        mock_app = Mock()

        with patch('backend.src.api.middleware.cors.settings') as mock_settings:
            mock_settings.is_production = False

            configure_cors_middleware(mock_app)

            args, kwargs = mock_app.add_middleware.call_args
            expose_headers = kwargs['expose_headers']

            assert "X-Request-ID" in expose_headers
            assert "X-Response-Time" in expose_headers

    def test_configure_cors_credentials(self):
        """Test de la configuration allow_credentials."""
        mock_app = Mock()

        with patch('backend.src.api.middleware.cors.settings') as mock_settings:
            mock_settings.is_production = False

            configure_cors_middleware(mock_app)

            args, kwargs = mock_app.add_middleware.call_args

            assert kwargs['allow_credentials'] is True

    def test_configure_cors_max_age(self):
        """Test de la configuration max_age."""
        mock_app = Mock()

        with patch('backend.src.api.middleware.cors.settings') as mock_settings:
            mock_settings.is_production = False

            configure_cors_middleware(mock_app)

            args, kwargs = mock_app.add_middleware.call_args

            assert kwargs['max_age'] == 600  # 10 minutes

    def test_configure_cors_logging_production(self):
        """Test du logging en mode production."""
        mock_app = Mock()

        with patch('backend.src.api.middleware.cors.settings') as mock_settings:
            with patch('backend.src.api.middleware.cors.logger') as mock_logger:
                mock_settings.is_production = True
                mock_settings.allowed_origins = None

                configure_cors_middleware(mock_app)

                # Vérifier que le message de production a été loggé
                mock_logger.info.assert_called_once()
                log_message = mock_logger.info.call_args[0][0]
                assert "CORS configured for production" in log_message
                assert "allowed origins" in log_message

    def test_configure_cors_logging_development(self):
        """Test du logging en mode développement."""
        mock_app = Mock()

        with patch('backend.src.api.middleware.cors.settings') as mock_settings:
            with patch('backend.src.api.middleware.cors.logger') as mock_logger:
                mock_settings.is_production = False

                configure_cors_middleware(mock_app)

                # Vérifier que le message de développement a été loggé
                mock_logger.info.assert_called_once()
                log_message = mock_logger.info.call_args[0][0]
                assert "CORS configured for development" in log_message
                assert "permissive settings" in log_message

    def test_configure_cors_custom_origins_parsing(self):
        """Test du parsing des origines personnalisées."""
        mock_app = Mock()

        with patch('backend.src.api.middleware.cors.settings') as mock_settings:
            mock_settings.is_production = True
            # Test avec espaces et virgules
            mock_settings.allowed_origins = "https://site1.com, https://site2.com ,https://site3.com"

            configure_cors_middleware(mock_app)

            args, kwargs = mock_app.add_middleware.call_args
            allowed_origins = kwargs['allow_origins']

            # Les origines doivent être parsées correctement
            assert "https://site1.com" in allowed_origins
            assert " https://site2.com " in allowed_origins  # Espaces préservés
            assert "https://site3.com" in allowed_origins

    def test_configure_cors_empty_custom_origins(self):
        """Test avec origines personnalisées vides."""
        mock_app = Mock()

        with patch('backend.src.api.middleware.cors.settings') as mock_settings:
            mock_settings.is_production = True
            mock_settings.allowed_origins = ""  # Chaîne vide

            configure_cors_middleware(mock_app)

            args, kwargs = mock_app.add_middleware.call_args
            allowed_origins = kwargs['allow_origins']

            # Seules les origines par défaut doivent être présentes
            assert len(allowed_origins) == 3  # 3 origines par défaut


class TestCorsIntegration:
    """Tests d'intégration pour le middleware CORS."""

    def test_cors_middleware_integration_with_fastapi(self):
        """Test d'intégration avec une vraie app FastAPI."""
        from fastapi import FastAPI

        app = FastAPI()

        with patch('backend.src.api.middleware.cors.settings') as mock_settings:
            mock_settings.is_production = False

            # La configuration ne devrait pas lever d'erreur
            configure_cors_middleware(app)

            # Vérifier que le middleware a été ajouté
            assert len(app.user_middleware) > 0

    def test_cors_different_environments(self):
        """Test de la différence entre environnements."""
        mock_app_prod = Mock()
        mock_app_dev = Mock()

        # Configuration production
        with patch('backend.src.api.middleware.cors.settings') as mock_settings:
            mock_settings.is_production = True
            mock_settings.allowed_origins = None

            configure_cors_middleware(mock_app_prod)

        # Configuration développement
        with patch('backend.src.api.middleware.cors.settings') as mock_settings:
            mock_settings.is_production = False

            configure_cors_middleware(mock_app_dev)

        # Comparer les configurations
        prod_kwargs = mock_app_prod.add_middleware.call_args[1]
        dev_kwargs = mock_app_dev.add_middleware.call_args[1]

        prod_origins = prod_kwargs['allow_origins']
        dev_origins = dev_kwargs['allow_origins']

        # Vérifier les différences
        assert any(origin.startswith("https://") for origin in prod_origins)
        assert all(origin.startswith("http://") for origin in dev_origins)
        assert len(dev_origins) > len(prod_origins)  # Plus d'origines en dev

    def test_cors_configuration_immutability(self):
        """Test que la configuration ne modifie pas les settings."""
        mock_app = Mock()
        original_settings = Mock()
        original_settings.is_production = False

        with patch('backend.src.api.middleware.cors.settings', original_settings):
            configure_cors_middleware(mock_app)

            # Les settings ne doivent pas être modifiés
            assert original_settings.is_production is False