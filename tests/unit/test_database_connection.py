"""
Tests of the SQLite engine and session management, against real database files.
"""

import sqlite3

import pytest
from sqlalchemy import inspect, text

from mimir import config
from mimir.database.connection import (
    DatabaseManager,
    configure_sqlite_performance,
    get_db_session,
    init_database,
    reset_database,
)
from mimir.database.models import Configuration


@pytest.fixture
def manager(tmp_path):
    manager = DatabaseManager()
    manager.configure(f"sqlite:///{tmp_path / 'test.db'}")
    manager.create_tables()
    yield manager
    manager.engine.dispose()


def _journal_mode(path) -> str:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        connection.close()


class TestConfigureSqlitePerformance:
    def test_wal_mode_is_enabled(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config.settings, "sqlite_wal_mode", True)
        connection = sqlite3.connect(tmp_path / "wal.db")
        configure_sqlite_performance(connection, None)
        connection.close()
        assert _journal_mode(tmp_path / "wal.db") == "wal"

    def test_wal_mode_can_be_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config.settings, "sqlite_wal_mode", False)
        connection = sqlite3.connect(tmp_path / "plain.db")
        configure_sqlite_performance(connection, None)
        connection.close()
        assert _journal_mode(tmp_path / "plain.db") == "delete"

    def test_other_drivers_are_left_untouched(self):
        configure_sqlite_performance(object(), None)


class TestDatabaseManager:
    def test_engine_is_configured_lazily_from_settings(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config.settings, "database_url", f"sqlite:///{tmp_path / 'lazy.db'}")
        manager = DatabaseManager()
        assert str(manager.engine.url).endswith("lazy.db")
        manager.engine.dispose()

    def test_create_tables(self, manager):
        assert "configuration" in inspect(manager.engine).get_table_names()

    def test_session_context_commits_on_success(self, manager):
        with manager.get_session_context() as session:
            session.add(Configuration(key="k", value="v"))
        with manager.get_session_context() as session:
            assert session.query(Configuration).filter_by(key="k").one().value == "v"

    def test_session_context_rolls_back_on_error(self, manager):
        with pytest.raises(RuntimeError), manager.get_session_context() as session:
            session.add(Configuration(key="k", value="v"))
            session.flush()
            raise RuntimeError("boom")
        with manager.get_session_context() as session:
            assert session.query(Configuration).count() == 0

    def test_reconfigure_switches_database(self, manager, tmp_path):
        manager.configure(f"sqlite:///{tmp_path / 'other.db'}")
        assert inspect(manager.engine).get_table_names() == []

    def test_health_check(self, manager, tmp_path):
        assert manager.health_check() is True
        manager.configure(f"sqlite:///{tmp_path / 'missing_dir' / 'db.sqlite'}")
        assert manager.health_check() is False


class TestModuleFunctions:
    def test_get_db_session_commits(self, isolated_db_manager):
        dependency = get_db_session()
        session = next(dependency)
        session.add(Configuration(key="from_dependency", value="1"))
        with pytest.raises(StopIteration):
            next(dependency)
        with isolated_db_manager.get_session_context() as check:
            assert check.query(Configuration).filter_by(key="from_dependency").count() == 1

    def test_init_database_creates_directories_and_tables(
        self, isolated_db_manager, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config.settings, "data_dir", str(tmp_path / "data"))
        monkeypatch.setattr(config.settings, "upload_dir", str(tmp_path / "data" / "documents"))
        monkeypatch.setattr(
            config.settings, "faiss_index_path", str(tmp_path / "data" / "faiss" / "index.bin")
        )
        init_database()
        assert (tmp_path / "data" / "documents").is_dir()
        assert "documents" in inspect(isolated_db_manager.engine).get_table_names()

    def test_reset_database_recreates_empty_tables(self, isolated_db_manager):
        with isolated_db_manager.get_session_context() as session:
            session.add(Configuration(key="k", value="v"))
        reset_database()
        with isolated_db_manager.get_session_context() as session:
            assert session.execute(text("SELECT COUNT(*) FROM configuration")).scalar() == 0

    def test_reset_database_is_refused_in_production(self, monkeypatch):
        monkeypatch.setattr(config.settings, "environment", "production")
        with pytest.raises(RuntimeError, match="not allowed in production"):
            reset_database()
