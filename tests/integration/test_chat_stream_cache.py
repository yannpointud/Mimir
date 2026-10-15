"""
Integration tests for the corpus-aware SSE cache on /chat/stream.

Proves four behaviours:
  - Test 1 (hit replay): a repeated question is served from cache with an SSE
    event sequence indistinguishable from the fresh response (same event
    types in order, same concatenated answer, same sources, same final done
    payload) and makes NO Mistral generate call.
  - Test 2 (invalidation): after the corpus version changes (upsert/delete
    bumps last_updated), the same question MISSES and re-runs the pipeline --
    proving corpus_version is part of the server-derived key.
  - Test 3 (anti-partial): a mid-stream disconnect (generator closed before
    the done event) stores NO cache entry -- the write happens only after a
    successful done yield, never in except/finally.
  - Test 4 (no Mistral on hit): a cache hit records no new llm_usage rows and
    makes no generate call (the hit path spends nothing).

All tests are hermetic: a mock LLM (zero real Mistral calls), a stub vector
store with a controllable corpus version, and an isolated temporary SQLite
database. The chat route reaches the pipeline exclusively through
Depends(get_rag_service), so the override targets get_rag_service; the
route and the service share the singleton ChatCacheService so a write by the
service is visible to the route's read.
"""
import json
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock

from src import config as config_module
from src.config import settings
from src.database.connection import db_manager
from src.database.models import Base, LlmUsage
from src.llm_interface.interfaces import EmbeddingResponse


CHAT_STREAM_ROUTE = "/api/v1/chat/stream"


class _FakeResult:
    """Minimal SearchResult stand-in with the attributes the RAG pipeline
    reads, so the mock vector store can return a source-bearing hit."""

    def __init__(self, index: int = 0):
        self.similarity_score = 0.9
        self.document_id = "1"
        self.chunk_id = f"chunk_{index}"
        self.chunk_index = index
        self.total_chunks = 1
        self.source = "test.txt"
        self.text = "relevant chunk text"


def _make_mock_llm():
    """A mock LLM with call counters for embed and generate_stream -- zero
    real Mistral calls. Returns (mock_llm, embed_calls, gen_calls)."""
    embed_calls = {"n": 0}
    gen_calls = {"n": 0}

    async def fake_embed(*args, **kwargs):
        embed_calls["n"] += 1
        return EmbeddingResponse(
            embeddings=[[0.0] * settings.embedding_dimension],
            model="mistral-embed",
            usage_tokens=10,
            prompt_tokens=10,
            completion_tokens=0,
        )

    async def fake_generate_stream(*args, usage_out=None, **kwargs):
        gen_calls["n"] += 1
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
    return mock_llm, embed_calls, gen_calls


def _parse_sse_events(body: str):
    """Parse an SSE text body into a list of decoded JSON event dicts."""
    events = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:"):].strip()))
    return events


def _normalise_sequence(events):
    """Collapse consecutive chunk events into one logical 'chunk'.

    Returns (event_type_sequence, concatenated_answer, done_without_cached):
    the token-by-token chunk timing is intentionally ignored (replay sends the
    answer as a single chunk), and the `cached` flag on the done event is stripped since it
    legitimately differs between a fresh (False) and a replayed (True) hit.
    """
    types = []
    answer = ""
    done = None
    for ev in events:
        etype = ev.get("type")
        if etype == "chunk":
            answer += ev.get("content", "")
            if not types or types[-1] != "chunk":
                types.append("chunk")
        else:
            types.append(etype)
            if etype == "done":
                done = {k: v for k, v in ev.items() if k != "cached"}
    return types, answer, done


@pytest.fixture
def isolated_db_manager():
    """Redirect the global db_manager singleton to a fresh temporary SQLite
    file (BudgetGuard/UsageTracker open their own sessions via this singleton;
    mirrors test_budget_guard_endpoints.py)."""
    temp_dir = tempfile.mkdtemp(prefix="chat_stream_cache_test_")
    temp_db_path = Path(temp_dir) / "chat_stream_cache_test.db"

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


@pytest.fixture(autouse=True)
def _clear_stream_cache():
    """The ChatCacheService is a process-wide singleton; clear it around every
    test so cache state never leaks across tests."""
    from src.api.dependencies import get_chat_cache_service

    cache = get_chat_cache_service()
    cache.invalidate_all()
    cache.reset_stats()
    yield
    cache.invalidate_all()
    cache.reset_stats()


@pytest.fixture
def client(isolated_db_manager):
    """TestClient running the real app lifespan against the isolated db."""
    from main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def rag_with_mocks(isolated_db_manager):
    """Override get_rag_service with a RagService built from a mock LLM and a
    stub vector store whose corpus version is controllable. Yields
    (mock_store, embed_calls, gen_calls) so tests can steer the corpus version
    and assert Mistral call counts. Keeps the real budget_guard / usage_tracker
    / rag_debug singletons and the singleton chat cache (shared with the
    route's read)."""
    from main import app
    from src.api.dependencies import (
        get_rag_service, get_rag_debug_service, get_budget_guard,
        get_usage_tracker, get_chat_cache_service,
    )
    from src.services.rag_service import RagService

    mock_llm, embed_calls, gen_calls = _make_mock_llm()

    mock_store = Mock()
    mock_store.query = Mock(return_value=[_FakeResult()])
    mock_store.get_corpus_version = Mock(return_value="v1")

    rag_service = RagService(
        llm_service=mock_llm,
        vector_store=mock_store,
        rag_debug=get_rag_debug_service(),
        budget_guard=get_budget_guard(),
        usage_tracker=get_usage_tracker(),
        chat_cache=get_chat_cache_service(),
    )
    app.dependency_overrides[get_rag_service] = lambda: rag_service

    yield mock_store, embed_calls, gen_calls

    app.dependency_overrides.pop(get_rag_service, None)


def _usage_rows():
    session = db_manager.get_session()
    try:
        return session.query(LlmUsage).order_by(LlmUsage.id.asc()).all()
    finally:
        session.close()


def _stream_body(client, question):
    with client.stream(
        "POST",
        CHAT_STREAM_ROUTE,
        json={"question": question, "include_sources": True},
    ) as response:
        assert response.status_code == 200
        return "".join(chunk for chunk in response.iter_text())


class TestStreamCacheHitReplay:
    """Test 1: repeated question served from cache, indistinguishable SSE
    sequence, no Mistral generate call on the hit."""

    def test_second_call_replays_identical_sequence_without_mistral(
        self, client, rag_with_mocks
    ):
        _mock_store, _embed_calls, gen_calls = rag_with_mocks
        question = "What is Mimir stream cache?"

        fresh_body = _stream_body(client, question)
        gen_after_first = gen_calls["n"]

        cached_body = _stream_body(client, question)
        gen_after_second = gen_calls["n"]

        fresh_types, fresh_answer, fresh_done = _normalise_sequence(
            _parse_sse_events(fresh_body)
        )
        cached_types, cached_answer, cached_done = _normalise_sequence(
            _parse_sse_events(cached_body)
        )

        # Indistinguishable: same event-type sequence, same concatenated
        # answer, same final done payload (sources + confidence), ignoring the
        # cached flag and token-by-token chunk timing.
        assert fresh_types == cached_types
        assert fresh_answer == cached_answer
        assert fresh_done == cached_done

        # Sources are included in both responses.
        assert fresh_done is not None
        assert len(fresh_done["sources"]) >= 1
        assert cached_done["sources"] == fresh_done["sources"]

        # The done event on the hit is explicitly marked cached.
        cached_events = _parse_sse_events(cached_body)
        done_event = next(e for e in cached_events if e.get("type") == "done")
        assert done_event["cached"] is True

        # No Mistral generate call happened on the second (cached) request.
        assert gen_after_first == 1
        assert gen_after_second == 1


class TestStreamCacheInvalidation:
    """Test 2: a corpus version change invalidates the entry (implicit
    invalidation via the server-derived key)."""

    def test_corpus_version_change_forces_miss(self, client, rag_with_mocks):
        mock_store, _embed_calls, gen_calls = rag_with_mocks
        question = "Question invalidated by ingestion"

        _stream_body(client, question)
        assert gen_calls["n"] == 1

        # Simulate an ingestion/deletion bumping last_updated.
        mock_store.get_corpus_version.return_value = "v2"

        _stream_body(client, question)

        # The same question re-ran the pipeline: the old-version entry was not
        # served, proving corpus_version is in the key.
        assert gen_calls["n"] == 2


class TestStreamCacheNoBudgetOnHit:
    """Test 4: a cache hit records no new llm_usage rows and makes no generate
    call (the hit path spends nothing)."""

    def test_hit_records_no_new_usage_rows(self, client, rag_with_mocks):
        _mock_store, _embed_calls, gen_calls = rag_with_mocks
        question = "Question priced only once"

        _stream_body(client, question)
        rows_after_first = len(_usage_rows())
        gen_after_first = gen_calls["n"]

        _stream_body(client, question)
        rows_after_second = len(_usage_rows())

        # The hit added no usage rows and made no generate call.
        assert rows_after_second == rows_after_first
        assert gen_calls["n"] == gen_after_first


class TestStreamCacheAntiPartial:
    """Test 3: a mid-stream disconnect (generator closed before done) stores
    no cache entry -- the write happens only after a successful done yield."""

    @pytest.mark.asyncio
    async def test_disconnect_before_done_stores_no_entry(self, isolated_db_manager):
        from src.api.dependencies import (
            get_rag_debug_service, get_budget_guard, get_usage_tracker,
            get_chat_cache_service,
        )
        from src.services.rag_service import RagService

        cache = get_chat_cache_service()
        cache.invalidate_all()

        mock_llm, _embed_calls, _gen_calls = _make_mock_llm()
        mock_store = Mock()
        mock_store.query = Mock(return_value=[_FakeResult()])
        mock_store.get_corpus_version = Mock(return_value="v1")

        rag_service = RagService(
            llm_service=mock_llm,
            vector_store=mock_store,
            rag_debug=get_rag_debug_service(),
            budget_guard=get_budget_guard(),
            usage_tracker=get_usage_tracker(),
            chat_cache=cache,
        )

        question = "Question interrupted mid-stream"
        # A stub repository is enough: the pipeline falls back to the source
        # name when get_by_id returns None.
        document_repository = Mock()
        document_repository.get_by_id = Mock(return_value=None)
        document_repository.get_all = Mock(return_value=[])

        agen = rag_service.answer_stream(
            question=question,
            context_limit=5,
            include_sources=True,
            session_id="disconnect-session",
            document_repository=document_repository,
            reservation=None,
            corpus_version="v1",
        )

        # Consume the first event then close the generator before the done
        # event -- this raises GeneratorExit inside the pipeline, exactly like
        # a mid-stream client disconnect.
        first_event = await agen.__anext__()
        assert first_event["type"] in ("chunk", "start", "done")
        await agen.aclose()

        # No partial entry was written on the interrupted stream.
        assert cache.get_stream_response(question, "v1") is None
