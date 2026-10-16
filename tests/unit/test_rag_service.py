"""
White-box unit tests for the RAG pipeline (RagService).

These tests drive answer_stream(), the single RAG pipeline, and assert its
base output contract (numbered answer chunks and a terminal done event) by
draining the SSE events into a result, as the RAGAS adapter does.

Mock-based: AsyncMock LLM service, Mock vector store / document repository /
rag_debug. No real Mistral API call, no real FAISS index.
"""

import asyncio
from unittest.mock import Mock, AsyncMock, patch

from mimir.rag_core.interfaces import SearchResult
from mimir.services.rag_service import _process_question_with_rag_stream


def _sr(chunk_id, document_id, text, source, score):
    return SearchResult(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        source=source,
        similarity_score=score,
        chunk_index=0,
        total_chunks=1,
        metadata={},
    )


def _fake_generate_stream(*chunks):
    """Return an async-generator function standing in for llm.generate_stream."""

    async def _gen(*args, **kwargs):
        for c in chunks:
            yield c

    return _gen


def _base_mocks():
    """Common mock harness on the pure dense retrieval path."""
    mock_llm_service = AsyncMock()
    mock_vector_store = Mock()
    mock_document_repository = Mock()
    mock_rag_debug = Mock()

    for name in (
        "log_user_request",
        "log_vector_search",
        "log_context_building",
        "log_llm_generation",
        "log_error",
    ):
        setattr(mock_rag_debug, name, Mock())

    # No fuzzy filename pre-inclusion matches (keeps the dense path pure).
    mock_document_repository.get_all.return_value = []
    mock_document_repository.get_by_ids.side_effect = lambda ids: {
        i: Mock(filename="doc.pdf") for i in ids
    }

    mock_llm_service.embed.return_value = AsyncMock(
        embeddings=[[0.1] * 1024],
        usage_tokens=10,
        model="mistral-embed",
        prompt_tokens=10,
        completion_tokens=0,
    )
    mock_llm_service.generate_stream = _fake_generate_stream("L'IA ", "est une technologie.")
    return mock_llm_service, mock_vector_store, mock_document_repository, mock_rag_debug


def _dense_settings(mock_settings):
    """Realistic dense-mode settings (hybrid + pre-inclusion off)."""
    mock_settings.hybrid_search_enabled = False
    mock_settings.rrf_k = 60
    mock_settings.rrf_score_threshold = 0.015
    mock_settings.similarity_threshold = 0.5
    mock_settings.dynamic_filter_percentage = 0.15
    mock_settings.max_sources = 5
    mock_settings.min_sources = 1
    mock_settings.confidence_algorithm = "weighted"
    mock_settings.filename_pre_inclusion = False


async def _drain(**kwargs):
    events = []
    async for event in _process_question_with_rag_stream(**kwargs):
        events.append(event)
    return events


class TestStreamPipelineContract:
    """Base output contract of the streaming RAG pipeline."""

    def test_pipeline_yields_answer_chunks_then_done(self):
        """The pipeline streams the answer as chunk events and ends with a done
        event carrying the numbered sources."""
        llm, vs, docs, dbg = _base_mocks()
        vs.query.return_value = [_sr(1, "10", "extrait pertinent", "a.txt", 0.80)]

        with patch("mimir.services.rag_service.settings") as mock_settings:
            _dense_settings(mock_settings)
            events = asyncio.run(
                _drain(
                    question="Qu'est-ce que l'IA ?",
                    context_limit=5,
                    include_sources=True,
                    session_id="session_123",
                    llm_service=llm,
                    vector_store=vs,
                    document_repository=docs,
                    rag_debug=dbg,
                )
            )

        types = [e["type"] for e in events]
        assert "done" in types
        # The answer is the concatenation of every chunk event's content.
        answer = "".join(e["content"] for e in events if e["type"] == "chunk")
        assert answer == "L'IA est une technologie."
        done = next(e for e in events if e["type"] == "done")
        assert set(done.keys()) == {"type", "sources", "confidence_score", "cached"}
        assert len(done["sources"]) == 1

    def test_pipeline_no_sources_done_empty(self):
        """With no vector hits the done event still fires with an empty sources
        list (byte-identical contract), never raising."""
        llm, vs, docs, dbg = _base_mocks()
        vs.query.return_value = []

        with patch("mimir.services.rag_service.settings") as mock_settings:
            _dense_settings(mock_settings)
            events = asyncio.run(
                _drain(
                    question="Test question",
                    context_limit=3,
                    include_sources=False,
                    session_id="session_123",
                    llm_service=llm,
                    vector_store=vs,
                    document_repository=docs,
                    rag_debug=dbg,
                )
            )

        done = next(e for e in events if e["type"] == "done")
        assert done["sources"] == []
