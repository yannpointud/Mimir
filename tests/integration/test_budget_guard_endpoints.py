"""
Integration tests for budget-gated chat endpoints (COST-01, plan 03-05).

Covers the two must-have truths for this plan:
  - A budget-exhausted /chat/stream returns a real HTTP 429 with a body
    distinguishable from the slowapi rate-limit 429 (error_code
    "budget_exceeded" vs "HTTP_429"), BEFORE any SSE byte.
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
    """Yields a function that overrides get_rag_service with a RagService built
    from the given mock LLM and a stub vector store, so the RAG pipeline never
    hits a real Mistral API nor a real FAISS index.

    Since plan 04-04 the chat routes reach the pipeline exclusively through
    Depends(get_rag_service) (the llm_service/vector_store collaborators live
    inside the injected RagService), so overriding get_llm_service /
    get_vector_store alone no longer reaches the pipeline -- the override must
    target get_rag_service. The real budget_guard / usage_tracker /
    rag_debug singletons are kept so the reservation is still settled and the
    llm_usage rows are still written to the isolated temporary database."""
    from main import app
    from src.api.dependencies import (
        get_rag_service, get_rag_debug_service, get_budget_guard,
        get_usage_tracker, get_chat_cache_service,
    )
    from src.services.rag_service import RagService

    mock_store = Mock()
    mock_store.query = Mock(return_value=[])

    def _apply(mock_llm):
        rag_service = RagService(
            llm_service=mock_llm,
            vector_store=mock_store,
            rag_debug=get_rag_debug_service(),
            budget_guard=get_budget_guard(),
            usage_tracker=get_usage_tracker(),
            chat_cache=get_chat_cache_service(),
        )
        app.dependency_overrides[get_rag_service] = lambda: rag_service

    yield _apply

    app.dependency_overrides.pop(get_rag_service, None)


class _SpyBudgetGuard:
    """A BudgetGuard stand-in that counts reserve/release/finalize so a stream
    cache hit can be proven to release the reservation without charging it.
    reserve() returns a truthy sentinel so the route proceeds past the gate."""

    def __init__(self):
        self.reserve_calls = 0
        self.release_calls = 0
        self.finalize_calls = 0

    def reserve(self, category):
        self.reserve_calls += 1
        return object()

    def release(self, reservation):
        self.release_calls += 1

    def finalize(self, reservation, cost_eur):
        self.finalize_calls += 1


def _mock_llm_counting():
    """A mock LLM whose embed/generate_stream increment call counters -- zero
    real Mistral calls. Returns (mock_llm, counters)."""
    counters = {"embed": 0, "generate_stream": 0}

    async def fake_embed(*args, **kwargs):
        counters["embed"] += 1
        return EmbeddingResponse(
            embeddings=[[0.0] * settings.embedding_dimension],
            model="mistral-embed",
            usage_tokens=10,
            prompt_tokens=10,
            completion_tokens=0,
        )

    async def fake_generate_stream(*args, usage_out=None, **kwargs):
        counters["generate_stream"] += 1
        if usage_out is not None:
            usage_out.update(
                {"prompt_tokens": 15, "completion_tokens": 8, "total_tokens": 23}
            )
        yield "mocked "
        yield "answer"

    mock_llm = Mock()
    mock_llm.embed = fake_embed
    mock_llm.generate_stream = fake_generate_stream
    mock_llm.model_name = "mistral-small-latest"
    return mock_llm, counters


def _mock_llm_erroring():
    """A mock LLM whose embed raises, forcing the streaming pipeline down its
    error path (the client receives a generic error event, no done). Returns
    (mock_llm, counters)."""
    counters = {"embed": 0}

    async def fake_embed(*args, **kwargs):
        counters["embed"] += 1
        raise RuntimeError("forced pipeline failure")

    async def fake_generate_stream(*args, usage_out=None, **kwargs):
        # Never reached: embed raises first. Present so the attribute exists.
        if False:
            yield ""

    mock_llm = Mock()
    mock_llm.embed = fake_embed
    mock_llm.generate_stream = fake_generate_stream
    mock_llm.model_name = "mistral-small-latest"
    return mock_llm, counters


def _drain_stream(client, question):
    """POST a /chat/stream question and return the full SSE body as text."""
    with client.stream(
        "POST",
        CHAT_STREAM_ROUTE,
        json={"question": question, "include_sources": True},
    ) as response:
        assert response.status_code == 200
        return "".join(chunk for chunk in response.iter_text())


@pytest.fixture
def apply_stream_rag(isolated_db_manager):
    """Yields a builder that overrides get_rag_service and get_budget_guard
    with a RagService (given mock LLM) and a spy budget guard, sharing the
    singleton chat cache with the route's read. Returns (spy, cache, store).

    The spy budget guard is used both by the route (reserve/release) and by
    the RagService (finalize), so a hit that releases (never finalizes) can be
    distinguished from a miss that finalizes."""
    from main import app
    from src.api.dependencies import (
        get_rag_service, get_budget_guard, get_rag_debug_service,
        get_usage_tracker, get_chat_cache_service,
    )
    from src.services.rag_service import RagService

    cache = get_chat_cache_service()
    cache.invalidate_all()
    cache.reset_stats()
    spy = _SpyBudgetGuard()
    app.dependency_overrides[get_budget_guard] = lambda: spy

    def _apply(mock_llm, corpus_version="v1"):
        mock_store = Mock()
        mock_store.query = Mock(return_value=[])
        mock_store.get_corpus_version = Mock(return_value=corpus_version)
        rag_service = RagService(
            llm_service=mock_llm,
            vector_store=mock_store,
            rag_debug=get_rag_debug_service(),
            budget_guard=spy,
            usage_tracker=get_usage_tracker(),
            chat_cache=cache,
        )
        app.dependency_overrides[get_rag_service] = lambda: rag_service
        return spy, cache, mock_store

    yield _apply

    app.dependency_overrides.pop(get_rag_service, None)
    app.dependency_overrides.pop(get_budget_guard, None)
    cache.invalidate_all()
    cache.reset_stats()


class TestStreamCacheBudgetInteraction:
    """COST-03 budget interaction: a /chat/stream cache hit releases the
    reservation and spends nothing (no finalize, no Mistral call), while a
    fresh question still reserves and finalizes normally (T-4-05-04)."""

    def test_cache_hit_releases_without_charging(self, client, apply_stream_rag):
        mock_llm, counters = _mock_llm_counting()
        spy, _cache, _store = apply_stream_rag(mock_llm)

        question = "budget cache-hit question"

        # First call: a miss that runs the pipeline and finalizes.
        _drain_stream(client, question)
        generate_after_first = counters["generate_stream"]
        finalize_after_first = spy.finalize_calls
        release_after_first = spy.release_calls
        assert generate_after_first == 1

        # Second identical call: a cache hit.
        _drain_stream(client, question)

        # No Mistral generate call happened on the hit.
        assert counters["generate_stream"] == generate_after_first
        # The hit released its reservation but never finalized (no charge).
        assert spy.release_calls == release_after_first + 1
        assert spy.finalize_calls == finalize_after_first

        # A fresh, different question still reserves and charges normally.
        _drain_stream(client, "a different fresh question")
        assert counters["generate_stream"] == generate_after_first + 1
        assert spy.finalize_calls == finalize_after_first + 1


class TestStreamCacheErrorNeverCached:
    """WR-05: an error response is never cached -- the next identical question
    re-runs the pipeline instead of being served a cached error (T-4-05-05)."""

    def test_error_response_is_not_cached(self, client, apply_stream_rag):
        mock_llm, counters = _mock_llm_erroring()
        _spy, cache, _store = apply_stream_rag(mock_llm)

        question = "question that triggers a pipeline error"

        # First call: the pipeline errors, the client gets a generic error
        # event and no done event.
        body = _drain_stream(client, question)
        assert '"type": "error"' in body
        assert "Une erreur interne est survenue." in body
        assert '"type": "done"' not in body
        assert counters["embed"] == 1

        # No entry was written for this question (error path never caches).
        assert cache.get_stream_response(question, "v1") is None

        # Second identical call: a MISS that re-runs the pipeline (embed again).
        _drain_stream(client, question)
        assert counters["embed"] == 2


class TestBudgetExceededGate:
    """A budget-exhausted /chat/stream returns a distinct 429
    (error_code budget_exceeded) BEFORE any SSE byte (T-03-01)."""

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
        response = client.post(CHAT_STREAM_ROUTE, json={"question": "test question"})

        assert response.status_code == 429
        body = response.json()
        assert body["error_code"] == "budget_exceeded"
        assert body["error_code"] != "HTTP_429"


class TestNormalStreamUsageRecording:
    """A normal (non-cache-hit) /chat/stream call whose final SSE chunk carries
    real usage records exactly two llm_usage rows -- embedding + chat -- both
    estimated=False, and finalizes the reservation instead of leaking it
    (T-03-12 happy path)."""

    def test_normal_stream_call_records_embedding_and_chat_rows(
        self, client, apply_mocked_llm
    ):
        # stream_usage set so the final SSE chunk carries real usage: the chat
        # row is priced from real tokens (estimated=False), not the finally
        # fallback estimate.
        apply_mocked_llm(_mock_llm(
            stream_usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}
        ))

        with client.stream(
            "POST",
            CHAT_STREAM_ROUTE,
            json={"question": "unique-stream-usage-question", "include_sources": True},
        ) as response:
            assert response.status_code == 200
            body = "".join(chunk for chunk in response.iter_text())

        assert '"type": "done"' in body

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
