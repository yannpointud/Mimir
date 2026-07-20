"""
Integration tests for GET /admin/usage (phase 03, plan 03-07, COST-02).

Uses the isolated_db_manager fixture (same pattern as
tests/performance/test_budget_concurrency.py and tests/unit/test_budget_guard.py)
to redirect the global db_manager singleton to a fresh temporary SQLite file
for each test's lifetime, so synthetic usage/ledger rows never leak into the
developer's real database.
"""
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import config as config_module
from src.auth.jwt_handler import jwt_handler
from src.database.connection import db_manager
from src.database.models import Base, LlmBudgetLedger
from src.database.repository import UsageRepository


USAGE_ROUTE = "/api/v1/admin/usage"
CONFIG_ROUTE = "/api/v1/admin/configuration"


@pytest.fixture
def isolated_db_manager():
    """Redirect the global db_manager singleton to a fresh temporary SQLite
    file for this test's lifetime, then restore the original engine."""
    temp_dir = tempfile.mkdtemp(prefix="admin_usage_test_")
    temp_db_path = Path(temp_dir) / "admin_usage_test.db"

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


@pytest.fixture
def admin_token():
    """JWT token with admin user_type."""
    return jwt_handler.create_access_token({"sub": "admin", "user_type": "admin"})


@pytest.fixture
def user_token():
    """JWT token with non-admin user_type."""
    return jwt_handler.create_access_token({"sub": "testuser", "user_type": "user"})


def _seed_usage_and_ledger(today: str) -> None:
    """Seed a couple of llm_usage rows (two distinct models) and today's
    ledger row so the /admin/usage aggregates are non-trivial."""
    session = db_manager.get_session()
    try:
        usage_repo = UsageRepository(session)
        usage_repo.create_usage_entry(
            call_type="chat", model="mistral-large-latest",
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
            cost_eur=0.01, estimated=False, session_id="s1"
        )
        usage_repo.create_usage_entry(
            call_type="embedding", model="mistral-embed",
            prompt_tokens=200, completion_tokens=0, total_tokens=200,
            cost_eur=0.002, estimated=False, session_id="doc:1"
        )
        session.add(LlmBudgetLedger(date=today, spent_eur=0.012))
        session.commit()
    finally:
        session.close()


class TestGetUsageAccessControl:
    """GET /admin/usage exposes internal cost data: it must never be
    readable anonymously (T-03-02)."""

    def test_get_without_auth_header_returns_403(self, test_app, isolated_db_manager):
        client = TestClient(test_app)
        response = client.get(USAGE_ROUTE)
        assert response.status_code == 403

    def test_get_with_invalid_token_returns_401(self, test_app, isolated_db_manager):
        client = TestClient(test_app)
        response = client.get(
            USAGE_ROUTE, headers={"Authorization": "Bearer invalid-token"}
        )
        assert response.status_code == 401

    def test_get_with_non_admin_token_returns_403(self, test_app, isolated_db_manager, user_token):
        client = TestClient(test_app)
        response = client.get(
            USAGE_ROUTE, headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403


class TestGetUsageResponseShape:
    """An authenticated admin GET returns the dashboard payload."""

    def test_admin_get_returns_200_with_expected_keys(self, test_app, isolated_db_manager, admin_token):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        _seed_usage_and_ledger(today)

        client = TestClient(test_app)
        response = client.get(
            USAGE_ROUTE, headers={"Authorization": f"Bearer {admin_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        for key in ("today_by_model", "history", "spent_today_eur", "daily_budget_eur", "timestamp"):
            assert key in data

        assert len(data["today_by_model"]) == 2
        models = {row["model"] for row in data["today_by_model"]}
        assert models == {"mistral-large-latest", "mistral-embed"}
        assert data["spent_today_eur"] == pytest.approx(0.012)

    def test_admin_get_with_no_data_returns_zero_spend(self, test_app, isolated_db_manager, admin_token):
        """No usage rows yet today: spent_today_eur falls back to 0.0
        (get_today_ledger returns None)."""
        client = TestClient(test_app)
        response = client.get(
            USAGE_ROUTE, headers={"Authorization": f"Bearer {admin_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["today_by_model"] == []
        assert data["spent_today_eur"] == 0.0

    def test_daily_budget_eur_reflects_hot_admin_override(self, test_app, isolated_db_manager, admin_token):
        """GET /admin/usage must return the SAME effective cap that
        BudgetGuard._effective_cap() enforces: after a hot Admin override of
        daily_budget_eur, the dashboard gauge must show the override, not
        the stale .env default (otherwise the gauge contradicts the 429
        budget_exceeded behavior of the gate)."""
        client = TestClient(test_app)

        # Sanity: the override differs from the .env default.
        override_value = 5.0
        assert override_value != config_module.settings.daily_budget_eur

        put_response = client.put(
            CONFIG_ROUTE, json={"daily_budget_eur": str(override_value)},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert put_response.status_code == 200

        response = client.get(
            USAGE_ROUTE, headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        assert response.json()["daily_budget_eur"] == pytest.approx(override_value)

    def test_daily_budget_eur_falls_back_to_settings_without_override(self, test_app, isolated_db_manager, admin_token):
        """Without a hot override, the endpoint returns the .env default."""
        client = TestClient(test_app)
        response = client.get(
            USAGE_ROUTE, headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        assert response.json()["daily_budget_eur"] == pytest.approx(
            config_module.settings.daily_budget_eur
        )

    def test_days_back_above_range_returns_422(self, test_app, isolated_db_manager, admin_token):
        client = TestClient(test_app)
        response = client.get(
            USAGE_ROUTE, params={"days_back": 91},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 422

    def test_days_back_below_range_returns_422(self, test_app, isolated_db_manager, admin_token):
        client = TestClient(test_app)
        response = client.get(
            USAGE_ROUTE, params={"days_back": 0},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 422


class TestDailyBudgetEurAllowList:
    """daily_budget_eur must be accepted by the PUT /admin/configuration
    allow-list (the hot-reload source BudgetGuard._effective_cap reads),
    without weakening the existing invalid-key 400 behavior."""

    def test_put_daily_budget_eur_is_accepted_and_persisted(self, test_app, isolated_db_manager, admin_token):
        client = TestClient(test_app)
        response = client.put(
            CONFIG_ROUTE, json={"daily_budget_eur": "5.0"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # A subsequent read reflects the new value.
        get_response = client.get(
            CONFIG_ROUTE, headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert get_response.status_code == 200
        assert get_response.json()["database_config"]["daily_budget_eur"] == "5.0"

    def test_put_non_allow_listed_key_still_returns_400(self, test_app, isolated_db_manager, admin_token):
        client = TestClient(test_app)
        response = client.put(
            CONFIG_ROUTE, json={"not_a_real_key": "value"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 400
