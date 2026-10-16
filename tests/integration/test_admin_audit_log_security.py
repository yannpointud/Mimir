"""
Integration tests for admin audit-log endpoint security.

The audit log exposes admin usernames, configuration update values, client
IPs and 90 days of admin action history: it must never be readable without
an authenticated admin token. Also proves the router-level default-deny
guard on the /admin prefix.
"""

import pytest
from fastapi.testclient import TestClient

from mimir.auth.jwt_handler import jwt_handler


AUDIT_LOG_ROUTE = "/api/v1/admin/audit-log"


@pytest.fixture(scope="module", autouse=True)
def initialized_database():
    """Ensure database tables exist: TestClient without a `with` block does not
    run the app lifespan, so init_database() is never called."""
    from mimir.database.connection import init_database

    init_database()


@pytest.fixture
def admin_token():
    """JWT token with admin user_type."""
    return jwt_handler.create_access_token({"sub": "admin", "user_type": "admin"})


@pytest.fixture
def user_token():
    """JWT token with non-admin user_type."""
    return jwt_handler.create_access_token({"sub": "testuser", "user_type": "user"})


class TestAuditLogAccessControl:
    """Access control on GET /admin/audit-log."""

    def test_get_without_auth_header_returns_403(self, test_app):
        """Without Authorization header, HTTPBearer rejects with 403."""
        client = TestClient(test_app)
        response = client.get(AUDIT_LOG_ROUTE)
        assert response.status_code == 403

    def test_get_with_invalid_token_returns_401(self, test_app):
        """An invalid JWT token is rejected with 401."""
        client = TestClient(test_app)
        response = client.get(AUDIT_LOG_ROUTE, headers={"Authorization": "Bearer invalid-token"})
        assert response.status_code == 401

    def test_get_with_non_admin_token_returns_403(self, test_app, user_token):
        """A valid non-admin token is rejected with 403 by require_admin."""
        client = TestClient(test_app)
        response = client.get(AUDIT_LOG_ROUTE, headers={"Authorization": f"Bearer {user_token}"})
        assert response.status_code == 403

    def test_get_with_admin_token_passes_auth_guard(self, test_app, admin_token):
        """A valid admin token passes the auth guard (no 401/403).

        NOTE: this endpoint currently returns 500 with a valid token because
        of a pre-existing defect unrelated to authentication (the handler
        calls AuditLogRepository.get_logs_paginated(), which does not exist;
        the repository only exposes get_logs()). That defect is out of scope
        for the auth fix, so this test only proves the guard behavior.
        """
        client = TestClient(test_app)
        response = client.get(AUDIT_LOG_ROUTE, headers={"Authorization": f"Bearer {admin_token}"})
        assert response.status_code not in (401, 403)


class TestAuditLogRegression:
    """Regression coverage for the previously deferred audit-log 500.

    The handler calls AuditLogRepository.get_logs_paginated() and reads
    entry.additional_data; both were missing, so an authenticated admin GET
    returned 500 instead of the audit trail. These tests lock the fix.
    """

    def test_get_with_admin_token_returns_200_and_wellformed_body(self, test_app, admin_token):
        """An authenticated admin GET returns 200 with a paginated body."""
        client = TestClient(test_app)
        response = client.get(AUDIT_LOG_ROUTE, headers={"Authorization": f"Bearer {admin_token}"})
        assert response.status_code == 200
        body = response.json()
        assert "entries" in body and isinstance(body["entries"], list)
        assert "total" in body and isinstance(body["total"], int)
        assert "offset" in body and "limit" in body and "has_more" in body

    def test_get_with_filters_returns_200(self, test_app, admin_token):
        """Filtered admin GET (action + success) still returns 200."""
        client = TestClient(test_app)
        response = client.get(
            AUDIT_LOG_ROUTE,
            params={"action_filter": "login", "success_filter": True, "days_back": 30},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert isinstance(response.json()["entries"], list)


class TestAdminRouterDefaultDeny:
    """The /admin router carries a router-level require_admin dependency:
    no route under the prefix is reachable anonymously, even if an endpoint
    forgets its own require_admin declaration."""

    def test_admin_router_has_router_level_guard(self):
        """The APIRouter itself declares the require_admin dependency."""
        from mimir.api.endpoints.admin import router
        from mimir.auth.middleware import require_admin

        guard_callables = [dep.dependency for dep in router.dependencies]
        assert require_admin in guard_callables

    @pytest.mark.parametrize(
        "route",
        [
            "/api/v1/admin/system-info",
            "/api/v1/admin/configuration",
            "/api/v1/admin/audit-log",
            "/api/v1/admin/cache/stats",
        ],
    )
    def test_admin_routes_reject_anonymous_access(self, test_app, route):
        """A sample of /admin routes all reject anonymous GETs."""
        client = TestClient(test_app)
        response = client.get(route)
        assert response.status_code in (401, 403)
