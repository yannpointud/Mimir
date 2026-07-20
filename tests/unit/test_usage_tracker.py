"""
Unit tests for UsageTracker.record(): pricing -> persisted llm_usage row
(COST-01).

UsageTracker opens its OWN session per call via
db_manager.get_session_context() (not the conftest.py `test_session`
fixture). Mirrors the `isolated_db_manager` fixture from
tests/performance/test_budget_concurrency.py / test_budget_guard.py:
redirect the global db_manager singleton to a fresh temporary SQLite file
for the test's lifetime, so no synthetic usage rows leak into the
developer's real database.
"""
import shutil
import tempfile
from pathlib import Path

import pytest

from src import config as config_module
from src.config import settings
from src.cost.pricing import compute_cost_eur
from src.cost.usage_tracker import UsageTracker
from src.database.connection import db_manager
from src.database.models import Base, LlmUsage


@pytest.fixture
def isolated_db_manager():
    """Redirect the global db_manager singleton to a fresh temporary SQLite
    file for this test's lifetime, then restore the original engine."""
    temp_dir = tempfile.mkdtemp(prefix="usage_tracker_test_")
    temp_db_path = Path(temp_dir) / "usage_tracker_test.db"

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


def _get_latest_usage_row():
    session = db_manager.get_session()
    try:
        return session.query(LlmUsage).order_by(LlmUsage.id.desc()).first()
    finally:
        session.close()


class TestRecordPricedModel:
    def test_priced_model_writes_row_with_expected_cost_and_returns_it(self, isolated_db_manager):
        tracker = UsageTracker()
        model = next(iter(settings.llm_price_table.keys()))
        prompt_tokens, completion_tokens = 1000, 500

        expected_cost = compute_cost_eur(
            model, prompt_tokens, completion_tokens, settings.llm_price_table
        )

        cost = tracker.record(
            call_type="chat",
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated=False,
            session_id="sess-priced",
        )

        assert cost == pytest.approx(expected_cost)

        row = _get_latest_usage_row()
        assert row is not None
        assert row.model == model
        assert row.prompt_tokens == prompt_tokens
        assert row.completion_tokens == completion_tokens
        assert row.total_tokens == prompt_tokens + completion_tokens
        assert row.cost_eur == pytest.approx(expected_cost)
        assert row.estimated is False
        assert row.session_id == "sess-priced"

    def test_estimated_flag_persisted_verbatim_when_true(self, isolated_db_manager):
        tracker = UsageTracker()
        model = next(iter(settings.llm_price_table.keys()))

        tracker.record(
            call_type="chat",
            model=model,
            prompt_tokens=10,
            completion_tokens=5,
            estimated=True,
        )

        row = _get_latest_usage_row()
        assert row is not None
        assert row.estimated is True


class TestRecordUnpricedModel:
    def test_unpriced_chat_model_bills_flat_reservation_estimate_and_does_not_raise(
        self, isolated_db_manager, caplog
    ):
        """An unpriced model must be billed at the flat reservation estimate
        (NOT 0.0): finalize() applies actual - estimate, so a 0.0 cost here
        would refund the whole reservation and the daily cap would never
        accumulate for that model (T-03-04 free-bypass)."""
        tracker = UsageTracker()

        with caplog.at_level("ERROR"):
            cost = tracker.record(
                call_type="chat",
                model="totally-unpriced-model-xyz",
                prompt_tokens=42,
                completion_tokens=7,
                estimated=False,
            )

        assert cost == pytest.approx(settings.budget_reservation_chat_eur)
        assert cost > 0.0
        assert any("totally-unpriced-model-xyz" in message for message in caplog.messages)

        row = _get_latest_usage_row()
        assert row is not None
        assert row.model == "totally-unpriced-model-xyz"
        assert row.cost_eur == pytest.approx(settings.budget_reservation_chat_eur)
        # Forced to True even though the caller passed estimated=False --
        # the unpriced-model anomaly must be visibly flagged, never trusted
        # as a real fully-priced call.
        assert row.estimated is True
        assert row.prompt_tokens == 42
        assert row.completion_tokens == 7

    def test_unpriced_embedding_model_bills_embedding_flat_estimate(
        self, isolated_db_manager
    ):
        """The flat estimate is selected per call_type: an unpriced
        embedding call bills budget_reservation_embedding_eur."""
        tracker = UsageTracker()

        cost = tracker.record(
            call_type="embedding",
            model="totally-unpriced-embed-xyz",
            prompt_tokens=100,
            completion_tokens=0,
            estimated=False,
        )

        assert cost == pytest.approx(settings.budget_reservation_embedding_eur)

        row = _get_latest_usage_row()
        assert row is not None
        assert row.cost_eur == pytest.approx(settings.budget_reservation_embedding_eur)
        assert row.estimated is True
