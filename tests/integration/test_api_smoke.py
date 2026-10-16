"""
Smoke tests of the main API routes: mounting, auth guards and validation.
"""

import json

from fastapi.testclient import TestClient


def _sse_events(body):
    """Parse an SSE response body into the list of decoded `data:` events."""
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


class TestApiSmoke:
    def test_health(self, test_app):
        response = TestClient(test_app).get("/health")

        # 503 when the services are not configured, as in the test environment
        assert response.status_code in (200, 503)
        data = response.json()
        assert isinstance(data["success"], bool)
        assert data["status"] in ("healthy", "unhealthy")
        assert isinstance(data["timestamp"], str)

    def test_root(self, test_app):
        response = TestClient(test_app).get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Mimir"
        assert data["status"] == "running"
        assert isinstance(data["version"], str)
        assert "description" in data

    def test_chat_stream_is_a_well_formed_sse_stream(self, test_app):
        response = TestClient(test_app).post(
            "/api/v1/chat/stream",
            json={
                "question": "Quelle est la fonction principale du système ?",
                "context_limit": 3,
                "include_sources": True,
            },
        )

        assert response.status_code == 200
        events = _sse_events(response.text)
        assert events[0]["type"] == "start"
        assert events[0]["session_id"]
        assert events[-1]["type"] in {"done", "error"}

    def test_protected_routes_require_a_token(self, test_app):
        client = TestClient(test_app)
        assert client.get("/api/v1/documents/").status_code == 403
        assert client.get("/api/v1/admin/system-info").status_code == 403


class TestApiErrors:
    def test_empty_question_is_rejected(self, test_app):
        response = TestClient(test_app).post(
            "/api/v1/chat/stream", json={"question": "", "context_limit": 5}
        )
        assert response.status_code == 422
        assert "detail" in response.json()

    def test_missing_question_is_rejected(self, test_app):
        response = TestClient(test_app).post("/api/v1/chat/stream", json={"context_limit": 5})
        assert response.status_code == 422
        assert "detail" in response.json()

    def test_unknown_route_is_404(self, test_app):
        assert TestClient(test_app).get("/api/v1/nonexistent").status_code == 404
