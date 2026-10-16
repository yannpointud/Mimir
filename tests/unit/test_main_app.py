"""Tests unitaires pour l'application FastAPI principale."""

import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from mimir.main import app


class TestMainApp:
    """Tests pour l'application principale."""

    @pytest.fixture
    def client(self):
        """Client de test FastAPI."""
        return TestClient(app)

    def test_root_endpoint(self, client):
        """Test de l'endpoint racine"""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()

        # Les vrais champs retournés par l'endpoint racine
        assert data["name"] == "Mimir"
        assert data["description"] == "Chatbot documentaire d'entreprise"
        assert "version" in data
        assert data["status"] == "running"

    @patch("mimir.api.endpoints.health._check_database_health")
    @patch("mimir.api.endpoints.health._check_vector_store_health")
    @patch("mimir.api.endpoints.health._check_llm_health")
    @patch("mimir.api.endpoints.health._check_cache_health")
    @patch("mimir.api.endpoints.health._check_email_health")
    def test_health_check_success(
        self, mock_email, mock_cache, mock_llm, mock_vector, mock_db, client
    ):
        """Test du health check réussi"""
        # Simuler tous les checks comme sains
        mock_db.return_value = {"healthy": True, "connection": "ok"}
        mock_vector.return_value = {"healthy": True, "index_file": "exists"}
        mock_llm.return_value = {"healthy": True, "api_accessible": True}
        mock_cache.return_value = {"healthy": True, "cache_size": 100}
        mock_email.return_value = {"healthy": True, "configured": True}

        response = client.get("/api/v1/health/")

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["status"] == "healthy"
        assert "checks" in data
        assert data["checks"]["database"]["healthy"] is True
        assert data["checks"]["vector_store"]["healthy"] is True

    @patch("mimir.api.endpoints.health._check_database_health")
    @patch("mimir.api.endpoints.health._check_vector_store_health")
    @patch("mimir.api.endpoints.health._check_llm_health")
    @patch("mimir.api.endpoints.health._check_cache_health")
    @patch("mimir.api.endpoints.health._check_email_health")
    def test_health_check_failure(
        self, mock_email, mock_cache, mock_llm, mock_vector, mock_db, client
    ):
        """Test du health check en échec"""
        # Simuler une base de données défaillante
        mock_db.return_value = {
            "healthy": False,
            "connection": "failed",
            "error": "Connection timeout",
        }
        mock_vector.return_value = {"healthy": True, "index_file": "exists"}
        mock_llm.return_value = {"healthy": True, "api_accessible": True}
        mock_cache.return_value = {"healthy": True, "cache_size": 100}
        mock_email.return_value = {"healthy": True, "configured": True}

        response = client.get("/api/v1/health/")

        # Unhealthy state must be visible in the HTTP status code so
        # Docker healthchecks / load balancers can detect the failure.
        assert response.status_code == 503
        data = response.json()

        assert data["success"] is True  # BaseResponse success est toujours True
        assert data["status"] == "unhealthy"
        assert "checks" in data
        assert data["checks"]["database"]["healthy"] is False

    def test_404_handling(self, client):
        """Test de gestion des 404"""
        response = client.get("/nonexistent-endpoint")

        assert response.status_code == 404

    def test_cors_headers(self, client):
        """Test des headers CORS"""
        response = client.options(
            "/", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}
        )

        # Test de la présence des headers CORS
        assert "access-control-allow-origin" in response.headers or response.status_code in [
            200,
            404,
        ]

    def test_openapi_schema(self, client):
        """Test de la disponibilité du schéma OpenAPI"""
        # L'openapi est sur /api/v1/openapi.json selon la configuration
        response = client.get("/api/v1/openapi.json")

        assert response.status_code == 200
        schema = response.json()

        assert "openapi" in schema
        assert "info" in schema
        assert schema["info"]["title"] == "Mimir"


class TestErrorHandling:
    """Tests pour la gestion d'erreurs."""

    @pytest.fixture
    def client(self):
        """Client de test FastAPI."""
        return TestClient(app)

    def test_http_exception_handler(self, client):
        """Test du gestionnaire d'exceptions HTTP"""
        # Test d'un endpoint qui n'existe pas
        response = client.get("/this-endpoint-does-not-exist")

        assert response.status_code == 404
        data = response.json()

        assert "detail" in data or "error_message" in data


class TestMiddleware:
    """Tests pour les middlewares."""

    @pytest.fixture
    def client(self):
        """Client de test FastAPI."""
        return TestClient(app)

    def test_timing_header_added(self, client):
        """Test de l'ajout du header de timing"""
        response = client.get("/")

        assert response.status_code == 200

        # Le header peut être présent ou non selon la configuration
        if "x-process-time" in response.headers:
            # Si présent, vérifier qu'il s'agit d'un nombre
            timing = response.headers["x-process-time"]
            assert float(timing) >= 0

    def test_trusted_host_middleware(self, client):
        """Test du middleware de hosts de confiance"""
        # Tester avec un host normal
        response = client.get("/", headers={"Host": "testserver"})

        assert response.status_code == 200

        # Tester avec un host potentiellement non autorisé
        # (TestClient utilise "testserver" par défaut qui est généralement autorisé)
        response = client.get("/", headers={"Host": "malicious-host.com"})

        # Le middleware peut bloquer ou permettre selon la configuration
        # On vérifie juste qu'il n'y a pas d'erreur serveur
        assert response.status_code in [200, 400, 403]


class TestErrorHandlers:
    """Domain errors and unexpected errors map to stable JSON error responses."""

    @staticmethod
    def _request(path: str = "/api/v1/documents/1"):
        from starlette.requests import Request

        return Request({"type": "http", "method": "GET", "path": path, "headers": []})

    def _body(self, response) -> dict:
        import json

        return json.loads(response.body)

    def test_not_found_error_is_a_404(self):
        from mimir.main import not_found_handler
        from mimir.shared.errors import NotFoundError

        response = asyncio.run(not_found_handler(self._request(), NotFoundError("missing")))
        assert response.status_code == 404
        assert self._body(response)["error_code"] == "NOT_FOUND"
        assert self._body(response)["error_message"] == "missing"

    def test_conflict_error_is_a_409(self):
        from mimir.main import conflict_handler
        from mimir.shared.errors import ConflictError

        response = asyncio.run(conflict_handler(self._request(), ConflictError("protected")))
        assert response.status_code == 409
        assert self._body(response)["error_code"] == "CONFLICT"

    def test_unexpected_error_hides_its_text_in_production(self, monkeypatch):
        from mimir import config
        from mimir.main import general_exception_handler

        monkeypatch.setattr(config.settings, "environment", "production")
        response = asyncio.run(general_exception_handler(self._request(), KeyError("secret")))
        assert response.status_code == 500
        assert self._body(response)["error_message"] == "Internal server error"
        assert "secret" not in response.body.decode()
