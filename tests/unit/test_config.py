"""
Tests of the application settings.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from mimir.config import Settings


def _settings(**overrides) -> Settings:
    """Settings built from defaults and overrides only, ignoring any .env file."""
    return Settings(_env_file=None, **overrides)


@pytest.fixture(autouse=True)
def _no_environment_overrides(monkeypatch):
    for name in ("ENVIRONMENT", "LOG_LEVEL", "API_PORT", "MAX_CHUNK_SIZE"):
        monkeypatch.delenv(name, raising=False)


class TestSettings:
    def test_defaults(self):
        settings = _settings()
        assert settings.api_version == "v1"
        assert settings.api_port == 8000
        assert settings.sqlite_wal_mode is True
        assert settings.max_chunk_size == 1000
        assert settings.chunk_overlap == 200
        assert settings.rate_limit_enabled is True
        assert settings.log_level == "INFO"
        assert settings.is_production is False

    def test_overrides(self):
        settings = _settings(api_port=9000, max_chunk_size=2000, log_level="DEBUG")
        assert settings.api_port == 9000
        assert settings.max_chunk_size == 2000
        assert settings.log_level == "DEBUG"

    def test_environment_variables_take_effect(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert _settings().is_production is True

    def test_unknown_keys_are_rejected(self):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            _settings(watch_folder="./data/watch")

    def test_out_of_range_values_are_rejected(self):
        with pytest.raises(ValidationError):
            _settings(similarity_threshold=1.5)
        with pytest.raises(ValidationError):
            _settings(max_sources=0)

    def test_construction_has_no_filesystem_side_effect(self, tmp_path):
        _settings(data_dir=str(tmp_path / "data"), upload_dir=str(tmp_path / "data" / "docs"))
        assert not (tmp_path / "data").exists()

    def test_ensure_directories(self, tmp_path):
        settings = _settings(
            data_dir=str(tmp_path / "data"),
            upload_dir=str(tmp_path / "data" / "documents"),
            database_url=f"sqlite:///{tmp_path / 'data' / 'sqlite' / 'mimir.db'}",
            faiss_index_path=str(tmp_path / "data" / "faiss" / "index.bin"),
        )
        settings.ensure_directories()
        for directory in ("data", "data/documents", "data/sqlite", "data/faiss"):
            assert Path(tmp_path, directory).is_dir()
