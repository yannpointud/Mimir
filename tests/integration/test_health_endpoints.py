"""
Integration tests for the liveness/readiness split.

Proves that:
  - GET /api/v1/health/live is a pure process probe: it stays 200 even when a
    dependency (Mistral) is down, because it performs no dependency I/O.
  - GET /api/v1/health/ready aggregates the cheap in-process dependency checks
    and returns 503 the moment any dependency (including the LLM API) is
    unhealthy.
  - The pre-existing GET /api/v1/health/ contract is unchanged (canary): it
    still returns a `checks` dict with the original five component keys that
    the admin StatusBar.jsx consumes.

No real Mistral network request is issued anywhere in this file: the LLM check
is patched with an AsyncMock (free-tier constraint).
"""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


LIVE_ROUTE = "/api/v1/health/live"
READY_ROUTE = "/api/v1/health/ready"
FULL_HEALTH_ROUTE = "/api/v1/health/"

# Module path of the LLM helper as referenced by the route handlers.
LLM_HEALTH_TARGET = "src.api.endpoints.health._check_llm_health"
DB_HEALTH_TARGET = "src.api.endpoints.health._check_database_health"
VS_HEALTH_TARGET = "src.api.endpoints.health._check_vector_store_health"

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def initialized_database():
    """Ensure database tables exist: tests that use TestClient without a
    `with` block never run the app lifespan, so init_database() is needed."""
    from src.database.connection import init_database

    init_database()


@pytest.fixture
def client():
    """TestClient with the app lifespan active (database, services)."""
    from main import app

    with TestClient(app) as client:
        yield client


def _healthy():
    """Return a minimal healthy check payload."""
    return {"healthy": True}


def _unhealthy():
    """Return a minimal unhealthy check payload (simulated Mistral outage)."""
    return {"healthy": False, "error": "simulated outage"}


def test_live_stays_200_when_mistral_down(client):
    """Liveness must be immune to dependency outages: even with the LLM check
    mocked unhealthy, /live returns 200 {"status": "alive"} because it performs
    no dependency I/O."""
    with patch(LLM_HEALTH_TARGET, new=AsyncMock(return_value=_unhealthy())):
        response = client.get(LIVE_ROUTE)

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_ready_200_when_all_dependencies_healthy(client):
    """Readiness returns 200 with status "ready" and an empty unhealthy list
    when every dependency check reports healthy."""
    with (
        patch(LLM_HEALTH_TARGET, new=AsyncMock(return_value=_healthy())),
        patch(VS_HEALTH_TARGET, new=AsyncMock(return_value=_healthy())),
        patch(DB_HEALTH_TARGET, new=AsyncMock(return_value=_healthy())),
    ):
        response = client.get(READY_ROUTE)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["unhealthy"] == []
    assert set(body["checks"].keys()) == {"database", "vector_store", "llm_api"}


def test_ready_503_when_mistral_down(client):
    """A Mistral outage (LLM check unhealthy) must fail /ready with 503 and list
    "llm_api" among the unhealthy components."""
    with (
        patch(LLM_HEALTH_TARGET, new=AsyncMock(return_value=_unhealthy())),
        patch(VS_HEALTH_TARGET, new=AsyncMock(return_value=_healthy())),
        patch(DB_HEALTH_TARGET, new=AsyncMock(return_value=_healthy())),
    ):
        response = client.get(READY_ROUTE)

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert "llm_api" in body["unhealthy"]


def test_full_health_contract_unchanged(client):
    """Canary: the pre-existing comprehensive /health/ endpoint still returns a
    `checks` dict carrying the original five component keys consumed by
    StatusBar.jsx. The LLM check is patched healthy to avoid any real Mistral
    dependency during the assertion."""
    with patch(LLM_HEALTH_TARGET, new=AsyncMock(return_value=_healthy())):
        response = client.get(FULL_HEALTH_ROUTE)

    body = response.json()
    assert "checks" in body
    assert set(body["checks"].keys()) == {
        "database",
        "vector_store",
        "llm_api",
        "cache",
        "email_service",
    }
