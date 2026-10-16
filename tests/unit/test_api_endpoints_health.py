"""
Tests of the health endpoints and probes, against real resources where possible.
"""

import asyncio
from unittest.mock import Mock

import pytest
from fastapi import Response, status
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from mimir import config
from mimir.api.endpoints import health
from mimir.database.models import Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _healthy(**extra):
    async def probe(*args):
        return {"healthy": True, **extra}

    return probe


class TestHealthCheckEndpoint:
    @pytest.fixture
    def all_probes_healthy(self, monkeypatch):
        for name in (
            "_check_database_health",
            "_check_vector_store_health",
            "_check_llm_health",
            "_check_cache_health",
            "_check_email_health",
        ):
            monkeypatch.setattr(health, name, _healthy())

    def test_all_healthy_is_a_200(self, all_probes_healthy):
        response = Response()
        result = asyncio.run(health.health_check(response=response, db=Mock()))

        assert result.status == "healthy"
        assert response.status_code == status.HTTP_200_OK
        assert set(result.checks) == {
            "database",
            "vector_store",
            "llm_api",
            "cache",
            "email_service",
        }

    def test_one_unhealthy_component_is_a_503(self, all_probes_healthy, monkeypatch):
        async def unhealthy_database(db):
            return {"healthy": False, "error": "locked"}

        monkeypatch.setattr(health, "_check_database_health", unhealthy_database)
        response = Response()
        result = asyncio.run(health.health_check(response=response, db=Mock()))

        assert result.status == "unhealthy"
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


class TestDiskUsage:
    def test_existing_and_missing_directories(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config.settings, "data_dir", str(tmp_path))
        monkeypatch.setattr(config.settings, "upload_dir", str(tmp_path / "missing"))

        result = asyncio.run(health.disk_usage())

        assert result["healthy"] is True
        assert result["disk_usage"]["data_dir"]["total_gb"] > 0
        assert "No such file or directory" in result["disk_usage"]["upload_dir"]["error"]


class TestProbes:
    def test_database_probe(self, db_session):
        result = asyncio.run(health._check_database_health(db_session))
        assert result == {"healthy": True, "connection": "ok", "document_count": 0}

    def test_database_probe_reports_a_database_error(self):
        session = Mock()
        session.query.side_effect = OperationalError("SELECT", {}, Exception("locked"))

        result = asyncio.run(health._check_database_health(session))

        assert result["healthy"] is False
        assert result["connection"] == "failed"

    @pytest.mark.parametrize(
        ("files", "healthy", "index_state"),
        [
            (("index.bin", "metadata.json"), True, "exists"),
            ((), True, "not_initialized"),
            (("index.bin",), False, "exists"),
        ],
    )
    def test_vector_store_probe(self, tmp_path, monkeypatch, files, healthy, index_state):
        monkeypatch.setattr(config.settings, "faiss_index_path", str(tmp_path / "index.bin"))
        monkeypatch.setattr(config.settings, "faiss_metadata_path", str(tmp_path / "metadata.json"))
        for name in files:
            (tmp_path / name).write_text("x")

        result = asyncio.run(health._check_vector_store_health())

        assert result["healthy"] is healthy
        assert result["index_file"] == index_state

    @pytest.mark.parametrize(("api_key", "healthy"), [("key", True), ("", False)])
    def test_llm_probe(self, monkeypatch, api_key, healthy):
        monkeypatch.setattr(config.settings, "mistral_api_key", api_key)
        result = asyncio.run(health._check_llm_health())
        assert result["healthy"] is healthy
        assert result["provider"] == "mistral"

    def test_cache_probe_round_trip(self):
        result = asyncio.run(health._check_cache_health())
        assert result["healthy"] is True
        assert result["test"] == "passed"

    def test_cache_probe_reports_a_mismatch(self, monkeypatch):
        monkeypatch.setattr(health.cache_service, "get", Mock(return_value="other"))
        result = asyncio.run(health._check_cache_health())
        assert result["healthy"] is False

    @pytest.mark.parametrize("configured", [True, False])
    def test_email_probe(self, monkeypatch, configured):
        monkeypatch.setattr(
            health.email_service,
            "get_configuration_status",
            Mock(return_value={"configured": configured}),
        )
        result = asyncio.run(health._check_email_health())
        assert result["healthy"] is configured
