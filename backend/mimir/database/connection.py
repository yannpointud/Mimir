"""
SQLite engine and session management.
"""

import logging
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from mimir import config
from mimir.database.models import Base

logger = logging.getLogger(__name__)


def configure_sqlite_performance(dbapi_connection: Any, connection_record: Any) -> None:
    """Configure SQLite for performance and concurrency (WAL mode and related pragmas)."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        if config.settings.sqlite_wal_mode:
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=10000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA mmap_size=268435456")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


class DatabaseManager:
    """Owns the engine and session factory of the application database.

    The engine is created on first use from ``settings.database_url``;
    ``configure()`` points the manager at another database (tests, scripts).
    """

    def __init__(self) -> None:
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    def configure(self, database_url: str) -> None:
        """Create the engine for ``database_url``, disposing the previous one."""
        if self._engine is not None:
            self._engine.dispose()
        engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_recycle=3600,
            connect_args={"check_same_thread": False, "timeout": 20},
        )
        event.listen(engine, "connect", configure_sqlite_performance)
        self._engine = engine
        self._session_factory = sessionmaker(
            bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
        )
        logger.info(f"Database engine configured: {database_url}")

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self.configure(config.settings.database_url)
        assert self._engine is not None
        return self._engine

    def get_session(self) -> Session:
        """Create a new session; the caller closes it."""
        if self._session_factory is None:
            self.configure(config.settings.database_url)
        assert self._session_factory is not None
        return self._session_factory()

    @contextmanager
    def get_session_context(self) -> Generator[Session]:
        """Session committed on success, rolled back on error, always closed."""
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_tables(self) -> None:
        Base.metadata.create_all(bind=self.engine)

    def drop_tables(self) -> None:
        Base.metadata.drop_all(bind=self.engine)

    def health_check(self) -> bool:
        """Run ``SELECT 1``; any database error is reported as unhealthy."""
        try:
            with self.get_session_context() as session:
                session.execute(text("SELECT 1"))
        except SQLAlchemyError as e:
            logger.error(f"Database health check failed: {e}")
            return False
        return True


db_manager = DatabaseManager()


def get_db_session() -> Generator[Session]:
    """FastAPI dependency: one session per request, committed on success."""
    with db_manager.get_session_context() as session:
        yield session


def init_database() -> None:
    """Create the data directories and the tables, then check connectivity."""
    config.settings.ensure_directories()
    db_manager.create_tables()
    if not db_manager.health_check():
        raise RuntimeError("Database health check failed after initialization")
    logger.info("Database initialization completed successfully")


def reset_database() -> None:
    """Drop and recreate every table. Refused in production."""
    if config.settings.is_production:
        raise RuntimeError("Database reset not allowed in production")
    logger.warning("Resetting database - all data will be lost!")
    db_manager.drop_tables()
    db_manager.create_tables()
