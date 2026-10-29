"""Unit tests of the main FastAPI application."""

import asyncio
import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from mimir.main import app


class TestMainApp:
    """Main application tests."""

    @pytest.fixture
    def client(self):
        """Client de test FastAPI."""
        return TestClient(app)

    def test_root_endpoint(self, client):
        """Test de l'endpoint racine"""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()

        # The fields actually returned by the root endpoint
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
        # Make every check healthy
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
        # Simulate a failing database
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

        assert data["success"] is True  # BaseResponse success is always True
        assert data["status"] == "unhealthy"
        assert "checks" in data
        assert data["checks"]["database"]["healthy"] is False

    def test_404_handling(self, client):
        response = client.get("/nonexistent-endpoint")

        assert response.status_code == 404

    def test_cors_headers(self, client):
        response = client.options(
            "/", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}
        )

        # CORS headers are present
        assert "access-control-allow-origin" in response.headers or response.status_code in [
            200,
            404,
        ]

    def test_openapi_schema(self, client):
        # The OpenAPI schema is served at /api/v1/openapi.json
        response = client.get("/api/v1/openapi.json")

        assert response.status_code == 200
        schema = response.json()

        assert "openapi" in schema
        assert "info" in schema
        assert schema["info"]["title"] == "Mimir"


# Prints the status of each documentation route as the last stdout line
_DOCS_ROUTES_PROBE = """
import json
from fastapi.testclient import TestClient
from mimir.main import app

client = TestClient(app)
paths = ("/api/v1/openapi.json", "/docs", "/redoc")
print(json.dumps({path: client.get(path).status_code for path in paths}))
"""


class TestApiDocsExposure:
    """The OpenAPI schema and the interactive docs are closed in production."""

    def test_production_serves_neither_schema_nor_docs(self, tmp_path):
        # The routes are fixed when the app is built at import time: probe a
        # fresh interpreter started in production, away from the repo .env
        result = subprocess.run(
            [sys.executable, "-c", _DOCS_ROUTES_PROBE],
            cwd=tmp_path,
            env={**os.environ, "ENVIRONMENT": "production"},
            capture_output=True,
            text=True,
            check=True,
        )

        statuses = json.loads(result.stdout.strip().splitlines()[-1])
        assert statuses == {"/api/v1/openapi.json": 404, "/docs": 404, "/redoc": 404}


class TestErrorHandling:
    """Error handling tests."""

    @pytest.fixture
    def client(self):
        """Client de test FastAPI."""
        return TestClient(app)

    def test_http_exception_handler(self, client):
        # Endpoint that does not exist
        response = client.get("/this-endpoint-does-not-exist")

        assert response.status_code == 404
        data = response.json()

        assert "detail" in data or "error_message" in data


class TestMiddleware:
    """Middleware tests."""

    @pytest.fixture
    def client(self):
        """Client de test FastAPI."""
        return TestClient(app)

    def test_timing_header_added(self, client):
        response = client.get("/")

        assert response.status_code == 200

        # The header may or may not be present, depending on the configuration
        if "x-process-time" in response.headers:
            # If present, check it is a number
            timing = response.headers["x-process-time"]
            assert float(timing) >= 0

    def test_trusted_host_middleware(self, client):
        # Regular host
        response = client.get("/", headers={"Host": "testserver"})

        assert response.status_code == 200

        # Possibly unauthorized host
        # (TestClient uses "testserver" by default, which is usually allowed)
        response = client.get("/", headers={"Host": "malicious-host.com"})

        # The middleware may block or allow, depending on the configuration
        # Only check that there is no server error
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
