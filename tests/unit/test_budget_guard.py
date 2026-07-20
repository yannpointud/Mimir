"""
Unit tests for BudgetGuard: reserve/finalize/release with own committed
sessions, and the hot Admin > Configuration cap override (COST-01).

BudgetGuard opens its OWN session per operation via
db_manager.get_session_context() (not the conftest.py `test_session`
fixture, which wraps everything in a single rollback-only transaction and
would never actually see BudgetGuard's independently-committed writes).
Mirrors the `isolated_db_manager` fixture from
tests/performance/test_budget_concurrency.py: redirect the global db_manager
singleton to a fresh temporary SQLite file for the test's lifetime, so no
synthetic ledger/config rows leak into the developer's real database.
"""
import shutil
import tempfile
from pathlib import Path

import pytest

from src import config as config_module
from src.config import settings
from src.cost.budget_guard import BudgetGuard, BudgetExceededError, BudgetReservation
from src.database.connection import db_manager
from src.database.models import Base, LlmBudgetLedger
from src.database.repository import ConfigurationRepository


@pytest.fixture
def isolated_db_manager():
    """Redirect the global db_manager singleton to a fresh temporary SQLite
    file for this test's lifetime, then restore the original engine."""
    temp_dir = tempfile.mkdtemp(prefix="budget_guard_test_")
    temp_db_path = Path(temp_dir) / "budget_guard_test.db"

    original_engine = db_manager._engine
    original_session_factory = db_manager._session_factory
    original_async_engine = db_manager._async_engine
    original_async_session_factory = db_manager._async_session_factory
    original_database_url = config_module.settings.database_url

    config_module.settings.database_url = f"sqlite:///{temp_db_path}"
    db_manager._engine = None
    db_manager._session_factory = None
    db_manager._async_engine = None
    db_manager._async_session_factory = None
    db_manager._initialize_database()
    Base.metadata.create_all(bind=db_manager.engine)

    yield db_manager

    db_manager.engine.dispose()
    config_module.settings.database_url = original_database_url
    db_manager._engine = original_engine
    db_manager._session_factory = original_session_factory
    db_manager._async_engine = original_async_engine
    db_manager._async_session_factory = original_async_session_factory
    shutil.rmtree(temp_dir, ignore_errors=True)


def _get_today_ledger(today: str):
    session = db_manager.get_session()
    try:
        return session.query(LlmBudgetLedger).filter_by(date=today).first()
    finally:
        session.close()


class TestReserve:
    def test_reserve_success_returns_reservation_with_chat_estimate(self, isolated_db_manager):
        guard = BudgetGuard()

        reservation = guard.reserve("chat")

        assert reservation is not None
        assert isinstance(reservation, BudgetReservation)
        assert reservation.estimate_eur == settings.budget_reservation_chat_eur

    def test_reserve_embedding_uses_embedding_estimate(self, isolated_db_manager):
        guard = BudgetGuard()

        reservation = guard.reserve("embedding")

        assert reservation is not None
        assert reservation.estimate_eur == settings.budget_reservation_embedding_eur

    def test_reserve_past_cap_returns_none(self, isolated_db_manager):
        guard = BudgetGuard()

        # Lower the effective cap (via the hot config override) below a
        # single chat estimate so the very first reservation is rejected.
        session = db_manager.get_session()
        try:
            ConfigurationRepository(session).set(
                "daily_budget_eur", str(settings.budget_reservation_chat_eur / 2)
            )
        finally:
            session.close()

        reservation = guard.reserve("chat")

        assert reservation is None


class TestFinalize:
    def test_finalize_applies_real_minus_estimate_delta(self, isolated_db_manager):
        guard = BudgetGuard()
        reservation = guard.reserve("chat")
        assert reservation is not None

        actual_cost_eur = reservation.estimate_eur + 0.05
        guard.finalize(reservation, actual_cost_eur)

        ledger = _get_today_ledger(reservation.today)
        assert ledger is not None
        assert ledger.spent_eur == pytest.approx(actual_cost_eur)


class TestRelease:
    def test_release_subtracts_the_estimate(self, isolated_db_manager):
        guard = BudgetGuard()
        reservation = guard.reserve("chat")
        assert reservation is not None

        guard.release(reservation)

        ledger = _get_today_ledger(reservation.today)
        assert ledger is not None
        assert ledger.spent_eur == pytest.approx(0.0)


class TestHotConfigOverride:
    def test_config_table_override_beats_settings_default(self, isolated_db_manager):
        """A cap override set via the Admin > Configuration table must be
        used instead of settings.daily_budget_eur, even though the .env
        default (20.0) would otherwise happily accept the reservation."""
        guard = BudgetGuard()

        # First reservation succeeds under the generous .env default cap.
        first = guard.reserve("chat")
        assert first is not None

        # Now set a hot override lower than what's already been spent plus
        # another estimate -- if the override were ignored (falling back to
        # the default 20.0), this second reservation would still succeed.
        session = db_manager.get_session()
        try:
            ConfigurationRepository(session).set(
                "daily_budget_eur", str(first.estimate_eur)
            )
        finally:
            session.close()

        second = guard.reserve("chat")

        assert second is None


def test_budget_exceeded_error_is_an_exception_subclass():
    """BudgetExceededError must be importable and usable as a normal
    exception (ingestion fail-closed path raises it directly)."""
    assert issubclass(BudgetExceededError, Exception)
    with pytest.raises(BudgetExceededError):
        raise BudgetExceededError("Daily budget exceeded")
