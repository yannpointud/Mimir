"""
Integration tests for budget-gated chat endpoints (COST-01, plan 03-05).

Covers the two must-have truths for this plan:
  - Budget-exhausted /chat/ and /chat/stream both return a real HTTP 429
    with a body distinguishable from the slowapi rate-limit 429 (error_code
    "budget_exceeded" vs "HTTP_429"), BEFORE any LLM call or SSE byte.
  - Every completed chat records the embedding usage and the generation
    usage as llm_usage rows; a mid-stream disconnect (no final usage chunk)
    records the generation with estimated=True.

All tests are hermetic: dependency_overrides for get_llm_service /
get_vector_store / get_budget_guard, plus an isolated temporary SQLite
db_manager so BudgetGuard/UsageTracker (which open their own sessions via
the real db_manager singleton, not the test_session fixture) never touch
the developer's real database. Zero real Mistral API calls.
"""
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, AsyncMock

from src import config as config_module
from src.config import settings
from src.cost.budget_guard import BudgetGuard
from src.database.connection import db_manager
from src.database.models import Base, LlmUsage
from src.llm_interface.interfaces import EmbeddingResponse, GenerationResponse


CHAT_ROUTE = "/api/v1/chat/"
CHAT_STREAM_ROUTE = "/api/v1/chat/stream"


@pytest.fixture
def isolated_db_manager():
    """Redirect the global db_manager singleton to a fresh temporary SQLite
    file for this test's lifetime. BudgetGuard/UsageTracker open their own
    sessions via the real db_manager singleton (own-session-per-operation
    pattern, 03-04), so the standard test_session fixture (single
    rollback-only transaction) would never see their commits -- mirrors the
    isolated_db_manager fixture in tests/unit/test_budget_guard.py /
    test_usage_tracker.py."""
    temp_dir = tempfile.mkdtemp(prefix="chat_budget_endpoints_test_")
    temp_db_path = Path(temp_dir) / "chat_budget_endpoints_test.db"

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
def client(isolated_db_manager):
    """TestClient running the real app lifespan (database init) against the
    isolated temporary SQLite file."""
    from main import app
    with TestClient(app) as test_client:
        yield test_client


def _usage_rows():
    """All llm_usage rows in insertion order, from the isolated db_manager."""
    session = db_manager.get_session()
    try:
        return session.query(LlmUsage).order_by(LlmUsage.id.asc()).all()
    finally:
        session.close()


def _mock_llm(model="mistral-small-latest", embed_model="mistral-embed", stream_usage=None):
    """A Mock LLM service with deterministic, mocked embed/generate/
    generate_stream -- zero real Mistral API calls. Both models are present
    in settings.llm_price_table by default, so UsageTracker.record() prices
    them without falling back to the unpriced-model estimated=True path."""
    mock_llm = Mock()
    mock_llm.embed = AsyncMock(
        return_value=EmbeddingResponse(
            embeddings=[[0.0] * settings.embedding_dimension],
            model=embed_model,
            usage_tokens=10,
            prompt_tokens=10,
            completion_tokens=0,
        )
    )
    mock_llm.generate = AsyncMock(
        return_value=GenerationResponse(
            content="mocked answer",
            model=model,
            usage_tokens=30,
            finish_reason="stop",
            prompt_tokens=20,
            completion_tokens=10,
        )
    )
    mock_llm.model_name = model

    async def fake_generate_stream(*args, usage_out=None, **kwargs):
        if stream_usage is not None and usage_out is not None:
            usage_out.update(stream_usage)
        yield "mocked "
        yield "answer"

    mock_llm.generate_stream = fake_generate_stream
    return mock_llm


@pytest.fixture
def apply_mocked_llm():
    """Yields a function that overrides get_llm_service/get_vector_store
    with the given mock, so the RAG pipeline never hits a real Mistral API
    nor a real FAISS index."""
    from main import app
    from src.api.dependencies import get_llm_service, get_vector_store

    mock_store = Mock()
    mock_store.query = Mock(return_value=[])

    def _apply(mock_llm):
        app.dependency_overrides[get_llm_service] = lambda: mock_llm
        app.dependency_overrides[get_vector_store] = lambda: mock_store

    yield _apply

    app.dependency_overrides.pop(get_llm_service, None)
    app.dependency_overrides.pop(get_vector_store, None)


class TestBudgetExceededGate:
    """Budget-exhausted /chat/ and /chat/stream both return a distinct 429
    (error_code budget_exceeded) BEFORE any LLM call or SSE byte (T-03-01)."""

    @pytest.fixture(autouse=True)
    def _reject_every_reservation(self, isolated_db_manager):
        """Override get_budget_guard with a stub whose reserve() always
        returns None (budget exhausted), regardless of the real ledger."""
        from main import app
        from src.api.dependencies import get_budget_guard

        rejecting_guard = Mock(spec=BudgetGuard)
        rejecting_guard.reserve = Mock(return_value=None)
        rejecting_guard.finalize = Mock()
        rejecting_guard.release = Mock()

        app.dependency_overrides[get_budget_guard] = lambda: rejecting_guard

        yield

        app.dependency_overrides.pop(get_budget_guard, None)

    def test_chat_non_stream_returns_429_budget_exceeded(self, client):
        response = client.post(CHAT_ROUTE, json={"question": "test question"})

        assert response.status_code == 429
        body = response.json()
        assert body["error_code"] == "budget_exceeded"

    def test_chat_stream_returns_429_budget_exceeded_before_any_sse_byte(self, client):
        response = client.post(CHAT_STREAM_ROUTE, json={"question": "test question"})

        # A real HTTP 429, not a 200 with an SSE error event.
        assert response.status_code == 429
        body = response.json()
        assert body["error_code"] == "budget_exceeded"

    def test_budget_429_body_distinct_from_rate_limit_429_body(self, client):
        """The budget 429 body (top-level error_code "budget_exceeded") must
        differ from the slowapi rate-limit 429 body (top-level error_code
        "HTTP_429", see rate_limit.py's custom_rate_limit_handler)."""
        response = client.post(CHAT_ROUTE, json={"question": "test question"})

        assert response.status_code == 429
        body = response.json()
        assert body["error_code"] == "budget_exceeded"
        assert body["error_code"] != "HTTP_429"


class TestNonStreamUsageRecording:
    """A normal (non-cache-hit) /chat/ call records exactly two llm_usage
    rows -- embedding + chat -- both estimated=False, and finalizes the
    reservation instead of leaking it (T-03-12 for the non-stream path)."""

    def test_normal_chat_call_records_embedding_and_chat_rows(
        self, client, apply_mocked_llm
    ):
        apply_mocked_llm(_mock_llm())

        response = client.post(
            CHAT_ROUTE,
            json={"question": "unique-non-stream-question", "include_sources": True},
        )

        assert response.status_code == 200

        rows = _usage_rows()
        assert len(rows) == 2

        embedding_rows = [r for r in rows if r.call_type == "embedding"]
        chat_rows = [r for r in rows if r.call_type == "chat"]
        assert len(embedding_rows) == 1
        assert len(chat_rows) == 1

        assert embedding_rows[0].estimated is False
        assert chat_rows[0].estimated is False
        assert embedding_rows[0].model == "mistral-embed"
        assert chat_rows[0].model == "mistral-small-latest"


class TestStreamingUsageRecording:
    """A /chat/stream call whose mocked generate_stream never populates
    usage_out (simulating a disconnect / missing final usage chunk) records
    exactly one chat row with estimated=True (T-03-12)."""

    def test_stream_without_final_usage_chunk_records_one_estimated_chat_row(
        self, client, apply_mocked_llm
    ):
        # stream_usage=None: fake_generate_stream never touches usage_out,
        # simulating a stream that ends without the final SSE usage chunk.
        apply_mocked_llm(_mock_llm(stream_usage=None))

        with client.stream(
            "POST",
            CHAT_STREAM_ROUTE,
            json={"question": "unique-stream-question", "include_sources": True},
        ) as response:
            assert response.status_code == 200
            body = "".join(chunk for chunk in response.iter_text())

        assert '"type": "done"' in body

        rows = _usage_rows()
        chat_rows = [r for r in rows if r.call_type == "chat"]
        embedding_rows = [r for r in rows if r.call_type == "embedding"]

        assert len(chat_rows) == 1
        assert chat_rows[0].estimated is True
        assert len(embedding_rows) == 1
        assert embedding_rows[0].estimated is False

    def test_stream_with_final_usage_chunk_records_one_non_estimated_chat_row(
        self, client, apply_mocked_llm
    ):
        """Counterpart happy path: when the final SSE chunk DOES carry real
        usage, the chat row is estimated=False (proves the two branches of
        the finally block are mutually exclusive, exactly one row each)."""
        apply_mocked_llm(_mock_llm(
            stream_usage={"prompt_tokens": 15, "completion_tokens": 8, "total_tokens": 23}
        ))

        with client.stream(
            "POST",
            CHAT_STREAM_ROUTE,
            json={"question": "unique-stream-question-2", "include_sources": True},
        ) as response:
            assert response.status_code == 200
            "".join(chunk for chunk in response.iter_text())

        rows = _usage_rows()
        chat_rows = [r for r in rows if r.call_type == "chat"]

        assert len(chat_rows) == 1
        assert chat_rows[0].estimated is False
        assert chat_rows[0].prompt_tokens == 15
        assert chat_rows[0].completion_tokens == 8
