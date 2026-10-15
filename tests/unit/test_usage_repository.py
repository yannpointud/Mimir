"""
Unit tests for UsageRepository: CRUD, dashboard aggregates, and retention
for llm_usage / llm_budget_ledger.

Uses the standard conftest.py `test_repositories` fixture (single-connection,
rollback-only transaction) -- appropriate here since these tests exercise
CRUD/aggregate correctness, not concurrency (see test_budget_concurrency.py
for the anti-TOCTOU proof, which needs independent connections instead).
"""

from datetime import datetime, timedelta

from src.database.models import LlmUsage


class TestCreateUsageEntryAndTodayByModel:
    """Covers create_usage_entry() + get_today_by_model() aggregation."""

    def test_create_and_aggregate_two_rows_same_model(self, test_repositories):
        usage_repo = test_repositories["usage"]

        usage_repo.create_usage_entry(
            call_type="chat",
            model="mistral-small-latest",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_eur=0.01,
            estimated=False,
            session_id="sess-1",
        )
        usage_repo.create_usage_entry(
            call_type="chat",
            model="mistral-small-latest",
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
            cost_eur=0.02,
            estimated=False,
            session_id="sess-2",
        )
        usage_repo.create_usage_entry(
            call_type="embedding",
            model="mistral-embed",
            prompt_tokens=500,
            completion_tokens=0,
            total_tokens=500,
            cost_eur=0.005,
            estimated=False,
            session_id="doc:1",
        )

        rows = usage_repo.get_today_by_model()
        by_model = {row["model"]: row for row in rows}

        assert by_model["mistral-small-latest"]["calls"] == 2
        assert by_model["mistral-small-latest"]["prompt_tokens"] == 300
        assert by_model["mistral-small-latest"]["completion_tokens"] == 150
        assert by_model["mistral-small-latest"]["total_tokens"] == 450
        assert round(by_model["mistral-small-latest"]["cost_eur"], 4) == 0.03

        assert by_model["mistral-embed"]["calls"] == 1
        assert by_model["mistral-embed"]["total_tokens"] == 500


class TestGetDailyHistory:
    """Covers get_daily_history() spanning multiple dates."""

    def test_history_groups_by_date_and_model(self, test_repositories, test_session):
        usage_repo = test_repositories["usage"]

        usage_repo.create_usage_entry(
            call_type="chat",
            model="mistral-small-latest",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            cost_eur=0.001,
            estimated=False,
        )
        old_entry = usage_repo.create_usage_entry(
            call_type="chat",
            model="mistral-small-latest",
            prompt_tokens=20,
            completion_tokens=10,
            total_tokens=30,
            cost_eur=0.002,
            estimated=False,
        )
        # Backdate one entry to prove multi-date grouping in the history.
        old_entry.created_at = datetime.utcnow() - timedelta(days=2)
        test_session.commit()

        history = usage_repo.get_daily_history(days_back=7)
        dates = {row["date"] for row in history}

        assert len(dates) == 2
        assert sum(row["calls"] for row in history) == 2


class TestGetTodayLedger:
    """Covers get_today_ledger() None-vs-present."""

    def test_none_when_absent_then_present_after_reserve(self, test_repositories):
        usage_repo = test_repositories["usage"]
        today = datetime.utcnow().strftime("%Y-%m-%d")

        assert usage_repo.get_today_ledger() is None

        accepted = usage_repo.reserve(today, estimate_eur=1.0, cap_eur=20.0)
        assert accepted is True

        ledger = usage_repo.get_today_ledger()
        assert ledger is not None
        assert ledger.date == today
        assert ledger.spent_eur == 1.0


class TestCleanupOldUsage:
    """Covers cleanup_old_usage() retention (90-day default, aligned with audit_log)."""

    def test_deletes_only_rows_past_cutoff(self, test_repositories, test_session):
        usage_repo = test_repositories["usage"]

        recent = usage_repo.create_usage_entry(
            call_type="chat",
            model="mistral-small-latest",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            cost_eur=0.0001,
            estimated=False,
        )
        old = usage_repo.create_usage_entry(
            call_type="chat",
            model="mistral-small-latest",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            cost_eur=0.0001,
            estimated=False,
        )
        old.created_at = datetime.utcnow() - timedelta(days=91)
        test_session.commit()

        # Capture ids before cleanup: the deleted row's ORM instance gets
        # expired on commit, so its attributes can no longer be read after.
        recent_id, old_id = recent.id, old.id

        deleted_count = usage_repo.cleanup_old_usage(days_to_keep=90)

        assert deleted_count == 1
        remaining_ids = {row.id for row in test_session.query(LlmUsage).all()}
        assert recent_id in remaining_ids
        assert old_id not in remaining_ids
