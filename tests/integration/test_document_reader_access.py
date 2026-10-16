"""
Integration tests for document access control.

Every chat user may read what an answer cites: the indexed passages of a
document (GET /documents/{id}/full) and its original file
(GET /documents/{id}/download). Listing, statistics and every mutation of the
document base stay behind the router-level require_admin guard.
"""

import pytest
from fastapi.testclient import TestClient

from mimir.auth.middleware import require_admin

UNKNOWN_DOCUMENT_ID = 987654321


@pytest.fixture(scope="module", autouse=True)
def initialized_database():
    """Ensure database tables exist: TestClient without a `with` block does not
    run the app lifespan, so init_database() is never called."""
    from mimir.database.connection import init_database

    init_database()


class TestReaderRoutesArePublic:
    """The reader routes answer anonymous requests: an unknown document yields
    404 from the endpoint itself, never 401/403 from an auth guard."""

    def test_reader_router_has_no_auth_guard(self):
        from mimir.api.endpoints.documents import reader_router

        guard_callables = [dep.dependency for dep in reader_router.dependencies]
        assert require_admin not in guard_callables

    @pytest.mark.parametrize(
        "route",
        [
            f"/api/v1/documents/{UNKNOWN_DOCUMENT_ID}/full",
            f"/api/v1/documents/{UNKNOWN_DOCUMENT_ID}/download",
        ],
    )
    def test_reader_routes_reached_anonymously(self, test_app, route):
        client = TestClient(test_app)
        response = client.get(route)
        assert response.status_code == 404


class TestManagementRoutesStayAdminOnly:
    """The management router keeps its default-deny guard."""

    def test_management_router_has_router_level_guard(self):
        from mimir.api.endpoints.documents import router

        guard_callables = [dep.dependency for dep in router.dependencies]
        assert require_admin in guard_callables

    @pytest.mark.parametrize(
        "method,route",
        [
            ("GET", "/api/v1/documents/"),
            ("GET", f"/api/v1/documents/{UNKNOWN_DOCUMENT_ID}"),
            ("GET", "/api/v1/documents/stats/overview"),
            ("DELETE", f"/api/v1/documents/{UNKNOWN_DOCUMENT_ID}"),
            ("PATCH", f"/api/v1/documents/{UNKNOWN_DOCUMENT_ID}/preserve?preserve=true"),
            ("POST", f"/api/v1/documents/{UNKNOWN_DOCUMENT_ID}/reprocess"),
            ("POST", "/api/v1/documents/maintenance/validate-consistency"),
        ],
    )
    def test_management_routes_reject_anonymous_access(self, test_app, method, route):
        client = TestClient(test_app)
        response = client.request(method, route)
        assert response.status_code in (401, 403)
