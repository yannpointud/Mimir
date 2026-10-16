"""
Integration tests for per-route rate limiting.

Proves that request N+1 beyond the configured limit returns 429 with a
Retry-After header on login, chat/stream and document upload, that a full
SSE stream under the limit passes through intact, and that the suite-wide
autouse fixture keeps the limiter disabled for every other test (canary).

The limiter counts a hit at wrapper entry, BEFORE the endpoint body runs,
so under-limit requests may legitimately return business-level statuses
(401 wrong password, 400 invalid file) while still consuming the quota.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from mimir.api.middleware.rate_limit import limiter
from mimir.auth.jwt_handler import jwt_handler
from mimir.config import settings
from mimir.llm_interface.interfaces import EmbeddingResponse

LOGIN_ROUTE = "/api/v1/auth/login"
CHAT_STREAM_ROUTE = "/api/v1/chat/stream"
UPLOAD_ROUTE = "/api/v1/documents/upload"

BAD_LOGIN_PAYLOAD = {"username": "admin", "password": "wrong-password"}


@pytest.fixture(scope="module", autouse=True)
def initialized_database():
    """Ensure database tables exist: tests that use TestClient without a
    `with` block never run the app lifespan, so init_database() is needed."""
    from mimir.database.connection import init_database

    init_database()


@pytest.fixture
def rate_limited_client():
    """Enable the limiter for this test only, with clean counters.

    Runs on top of the suite-wide autouse disable_rate_limiter fixture:
    setup re-enables the limiter and resets the in-memory counters; teardown
    disables it and resets again so no state leaks into other tests.
    The `with` block executes the app lifespan (database, services).
    """
    from mimir.main import app

    limiter.enabled = True
    limiter.reset()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        limiter.enabled = False
        limiter.reset()


@pytest.fixture
def admin_token():
    """JWT token with admin user_type (same helper as test_admin_security)."""
    return jwt_handler.create_access_token({"sub": "admin", "user_type": "admin"})


@pytest.fixture
def mocked_rag():
    """Override the RAG service via app.dependency_overrides so the chat tests
    never call the real Mistral API nor touch the real FAISS index. The mocked
    pipeline produces a complete, deterministic SSE stream (start -> chunk ->
    done).

    The chat routes reach the pipeline exclusively through
    Depends(get_rag_service) (the llm_service/vector_store collaborators live
    inside the injected RagService), so overriding get_llm_service /
    get_vector_store alone no longer reaches the pipeline -- the override must
    target get_rag_service with a RagService built from the mock LLM + stub
    vector store. The real budget_guard / usage_tracker / rag_debug / chat_cache
    singletons are kept so the reservation is still settled and the usage row is
    still written."""
    from mimir.api.dependencies import (
        get_budget_guard,
        get_chat_cache_service,
        get_rag_debug_service,
        get_rag_service,
        get_usage_tracker,
    )
    from mimir.main import app
    from mimir.services.rag_service import RagService

    mock_llm = Mock()
    mock_llm.embed = AsyncMock(
        return_value=EmbeddingResponse(
            embeddings=[[0.0] * settings.embedding_dimension],
            model="mock-embed",
            usage_tokens=1,
        )
    )
    # model_name is read directly by the streaming RAG pipeline to
    # record the chat usage row; a bare Mock() would return an unset child
    # Mock (not a str), which SQLAlchemy cannot bind as the `model` column.
    mock_llm.model_name = "mock-chat"

    async def fake_generate_stream(*args, **kwargs):
        yield "mocked answer"

    mock_llm.generate_stream = fake_generate_stream

    mock_store = Mock()
    mock_store.query = Mock(return_value=[])

    rag_service = RagService(
        llm_service=mock_llm,
        vector_store=mock_store,
        rag_debug=get_rag_debug_service(),
        budget_guard=get_budget_guard(),
        usage_tracker=get_usage_tracker(),
        chat_cache=get_chat_cache_service(),
    )
    app.dependency_overrides[get_rag_service] = lambda: rag_service

    yield

    app.dependency_overrides.pop(get_rag_service, None)


class TestLoginRateLimit:
    """N+1 -> 429 on POST /auth/login, keyed per IP, with Retry-After."""

    def test_login_n_plus_one_returns_429_with_retry_after(self, rate_limited_client, monkeypatch):
        """3 requests under a patched limit of 3 get the normal 401 refusal;
        the 4th gets 429 with a Retry-After header."""
        monkeypatch.setattr(settings, "rate_limit_login_per_minute", 3)

        for _ in range(3):
            response = rate_limited_client.post(LOGIN_ROUTE, json=BAD_LOGIN_PAYLOAD)
            # Under the limit: normal business refusal, never 429
            assert response.status_code == 401

        response = rate_limited_client.post(LOGIN_ROUTE, json=BAD_LOGIN_PAYLOAD)
        assert response.status_code == 429
        # Retry-After header must be present, case-insensitive check
        assert "retry-after" in {k.lower() for k in response.headers}


class TestChatRateLimit:
    """N+1 -> 429 on POST /chat/stream, keyed per JWT user with IP fallback."""

    def test_chat_stream_n_plus_one_returns_429(self, rate_limited_client, mocked_rag, monkeypatch):
        """2 streams under a patched limit of 2 return 200; the 3rd is
        rejected with 429 BEFORE any SSE byte is produced."""
        monkeypatch.setattr(settings, "rate_limit_chat_per_minute", 2)
        payload = {"question": "test question", "include_sources": True}

        for _ in range(2):
            response = rate_limited_client.post(CHAT_STREAM_ROUTE, json=payload)
            assert response.status_code == 200

        response = rate_limited_client.post(CHAT_STREAM_ROUTE, json=payload)
        assert response.status_code == 429
        assert "retry-after" in {k.lower() for k in response.headers}


class TestUploadRateLimit:
    """N+1 -> 429 on POST /documents/upload (the route UploadZone calls)."""

    def test_upload_n_plus_one_returns_429(self, rate_limited_client, admin_token, monkeypatch):
        """2 uploads under a patched limit of 2 get a business-level status
        (the hit is counted at wrapper entry, before the body); the 3rd gets
        429. An invalid extension is used on purpose so the request is
        rejected by validation (400) without writing any file to disk nor
        triggering real ingestion — the rate-limit proof is identical."""
        monkeypatch.setattr(settings, "rate_limit_upload_per_minute", 2)
        headers = {"Authorization": f"Bearer {admin_token}"}
        files = {"file": ("rate_limit_probe.exe", b"probe content", "text/plain")}

        for _ in range(2):
            response = rate_limited_client.post(UPLOAD_ROUTE, headers=headers, files=files)
            # Under the limit: business validation status, never 429
            assert response.status_code in (200, 201, 400, 409, 422)
            assert response.status_code != 429

        response = rate_limited_client.post(UPLOAD_ROUTE, headers=headers, files=files)
        assert response.status_code == 429
        assert "retry-after" in {k.lower() for k in response.headers}


class TestSseStreamUnderLimit:
    """Roadmap criterion: a full SSE stream under the limit passes intact."""

    def test_sse_stream_completes_under_default_limit(self, rate_limited_client, mocked_rag):
        """With the default chat limit (20/min, unpatched), a single stream
        returns 200 and is consumed to the very end: start event, generated
        chunk and done event all present, zero 429, zero truncation."""
        with rate_limited_client.stream(
            "POST",
            CHAT_STREAM_ROUTE,
            json={"question": "test question", "include_sources": True},
        ) as response:
            assert response.status_code == 200
            body = "".join(chunk for chunk in response.iter_text())

        assert '"type": "start"' in body
        assert '"type": "chunk"' in body
        assert "mocked answer" in body
        assert '"type": "done"' in body
        assert '"type": "error"' not in body


class TestLimiterDisabledCanary:
    """Non-regression canary: the autouse disable_rate_limiter fixture keeps
    the whole existing suite protected from unexpected 429 responses."""

    def test_six_logins_never_hit_429_when_limiter_disabled(self, test_app):
        """Without the rate_limited_client fixture the limiter is disabled by
        the autouse fixture: 6 consecutive logins (above the default limit of
        5/min) must never produce a 429."""
        client = TestClient(test_app)
        for _ in range(6):
            response = client.post(LOGIN_ROUTE, json=BAD_LOGIN_PAYLOAD)
            assert response.status_code == 401
            assert response.status_code != 429
