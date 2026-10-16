"""Hybrid retrieval unit tests.

Two concerns are proven here:

1. Raw pool: FaissVectorStore.query(similarity_floor=0.0) returns the UNFILTERED
   candidate pool (cosine below the 0.5 threshold survives), while the default
   query() keeps its exact dense-only filtering. RRF needs the raw ranking, not a
   subset already truncated by the cosine threshold.

2. Hybrid branch of RagService: with hybrid_search_enabled=True and a bm25_store,
   dense + BM25 pools are fused via RRF and filtered with the DEDICATED
   rrf_score_threshold -- never the cosine 0.5 floor -- so a hybrid answer never
   returns zero sources as a pure threshold artifact. With
   the flag OFF the pipeline stays on the dense-only path.

Mock/synthetic only: no real Mistral call, no real embeddings.
"""

import asyncio
import math
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

from mimir.rag_core.implementations.faiss_store import FaissVectorStore
from mimir.rag_core.interfaces import Chunk, SearchResult
from mimir.services.rag_service import _process_question_with_rag_stream


def _unit(angle_cos: float) -> np.ndarray:
    """Return a 2D unit vector whose cosine with [1, 0] equals ``angle_cos``.

    For two unit vectors the FAISS L2 distance d satisfies d = 2 - 2*cos, and the
    store maps it to similarity = 1 - d/2 = cos. So this fixes the exact cosine
    similarity a query [1, 0] will see for the chunk.
    """
    return np.array([angle_cos, math.sqrt(max(0.0, 1.0 - angle_cos**2))], dtype=np.float32)


class TestSimilarityFloorRawPool:
    """FaissVectorStore.query(similarity_floor=...) — raw pool vs default filter."""

    def _store(self, tmp_path):
        store = FaissVectorStore(
            dimension=2,
            index_path=str(tmp_path / "hybrid.index"),
            metadata_path=str(tmp_path / "hybrid.json"),
            similarity_threshold=0.5,
            index_type="FlatL2",
        )
        chunks = [
            # cosine 1.0 with the query -> always kept
            Chunk(
                text="exact match",
                embedding=_unit(1.0),
                document_id="doc_hi",
                chunk_index=0,
                total_chunks=1,
                source="hi.txt",
                metadata={},
            ),
            # cosine 0.3 with the query -> below the 0.5 cosine threshold
            Chunk(
                text="weak dense but exact term",
                embedding=_unit(0.3),
                document_id="doc_lo",
                chunk_index=0,
                total_chunks=1,
                source="lo.txt",
                metadata={},
            ),
        ]
        assert store.upsert(chunks) is True
        return store

    def test_default_query_filters_below_threshold(self, tmp_path):
        store = self._store(tmp_path)
        query_vec = np.array([1.0, 0.0], dtype=np.float32)

        results = store.query(query_vec, top_k=10)

        # Only the cosine=1.0 chunk survives the default 0.5 threshold.
        assert len(results) == 1
        assert results[0].source == "hi.txt"

    def test_similarity_floor_zero_returns_raw_pool(self, tmp_path):
        store = self._store(tmp_path)
        query_vec = np.array([1.0, 0.0], dtype=np.float32)

        results = store.query(query_vec, top_k=10, similarity_floor=0.0)

        # Both chunks come back: the weak-cosine one is exactly what RRF must be
        # able to re-rank via BM25.
        sources = {r.source for r in results}
        assert sources == {"hi.txt", "lo.txt"}

    def test_default_query_byte_identical_without_floor(self, tmp_path):
        """query() with no similarity_floor must behave exactly as before."""
        store = self._store(tmp_path)
        query_vec = np.array([1.0, 0.0], dtype=np.float32)

        a = store.query(query_vec, top_k=10)
        b = store.query(query_vec, top_k=10, similarity_floor=None)

        assert [r.source for r in a] == [r.source for r in b]
        assert len(a) == 1


class TestGetBm25StoreSingleton:
    """dependencies.get_bm25_store() — lazy singleton, same shape as vector store."""

    def test_returns_singleton(self):
        # Import via the same `src.` namespace dependencies.py uses, otherwise the
        # instance and the class resolve to two distinct module objects
        # (src.* vs mimir.*) and isinstance would spuriously fail.
        from mimir.api import dependencies
        from mimir.rag_core.implementations.bm25_store import Bm25LexicalStore

        # Reset any previously created instance so the test is order-independent.
        dependencies._bm25_store = None
        first = dependencies.get_bm25_store()
        second = dependencies.get_bm25_store()

        assert isinstance(first, Bm25LexicalStore)
        assert first is second


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
    """Common mock harness for the streaming pipeline tests."""
    mock_llm_service = AsyncMock()
    mock_vector_store = Mock()
    mock_document_repository = Mock()
    mock_rag_debug = Mock()

    mock_rag_debug.log_user_request = Mock()
    mock_rag_debug.log_vector_search = Mock()
    mock_rag_debug.log_context_building = Mock()
    mock_rag_debug.log_llm_generation = Mock()

    # No fuzzy filename pre-inclusion matches (keeps the pipeline on the pure
    # dense/hybrid retrieval path).
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
    mock_llm_service.generate_stream = _fake_generate_stream("Réponse ", "synthétique.")
    return mock_llm_service, mock_vector_store, mock_document_repository, mock_rag_debug


async def _drain_result(**kwargs):
    """Drain the streaming pipeline into an answer()-shaped result dict.

    Mirrors the RAGAS adapter: answer = concatenated chunk events, sources +
    confidence_score come from the terminal done event.
    """
    answer_parts, sources, confidence = [], [], 0.0
    async for event in _process_question_with_rag_stream(**kwargs):
        etype = event.get("type")
        if etype == "chunk":
            answer_parts.append(event.get("content", ""))
        elif etype == "done":
            sources = event.get("sources", [])
            confidence = event.get("confidence_score", 0.0)
    return {"answer": "".join(answer_parts), "sources": sources, "confidence_score": confidence}


class TestHybridBranch:
    """Hybrid retrieval branch of _process_question_with_rag_stream."""

    def test_hybrid_returns_non_empty_fused_sources(self):
        """RRF fusion of dense+BM25 pools must yield sources filtered on the RRF
        scale -- never wiped to zero by the cosine 0.5 threshold."""
        llm, vs, docs, dbg = _base_mocks()

        # Dense pool: both chunks have cosine < 0.5, so the dense path alone would
        # drop everything. In the raw (similarity_floor=0.0) pool they survive.
        dense_pool = [
            _sr(1, "10", "dense and lexical hit", "a.txt", 0.42),
            _sr(2, "11", "dense only hit", "b.txt", 0.40),
        ]
        vs.query.return_value = dense_pool
        # chunk_id 3 is lexical-only: reconstructed from the FAISS metadata.
        vs.snapshot_active_chunks.return_value = [
            {
                "chunk_id": 1,
                "document_id": "10",
                "text": "dense and lexical hit",
                "source": "a.txt",
                "chunk_index": 0,
                "total_chunks": 1,
                "metadata": {},
            },
            {
                "chunk_id": 2,
                "document_id": "11",
                "text": "dense only hit",
                "source": "b.txt",
                "chunk_index": 0,
                "total_chunks": 1,
                "metadata": {},
            },
            {
                "chunk_id": 3,
                "document_id": "12",
                "text": "lexical only exact term",
                "source": "c.txt",
                "chunk_index": 0,
                "total_chunks": 1,
                "metadata": {},
            },
        ]

        mock_bm25 = Mock()
        mock_bm25.query.return_value = [(1, 5.0), (3, 4.0)]

        with patch("mimir.services.rag_service.settings") as mock_settings:
            # Only override the hybrid knobs; keep the rest realistic.
            mock_settings.hybrid_search_enabled = True
            mock_settings.rrf_k = 60
            mock_settings.rrf_score_threshold = 0.015
            mock_settings.similarity_threshold = 0.5
            mock_settings.dynamic_filter_percentage = 0.15
            mock_settings.max_sources = 5
            mock_settings.min_sources = 1
            mock_settings.confidence_algorithm = "weighted"
            mock_settings.filename_pre_inclusion = False

            result = asyncio.run(
                _drain_result(
                    question="terme exact JIRA-4521",
                    context_limit=5,
                    include_sources=True,
                    session_id="hybrid_1",
                    llm_service=llm,
                    vector_store=vs,
                    document_repository=docs,
                    rag_debug=dbg,
                    bm25_store=mock_bm25,
                )
            )

        # BM25 was actually consulted, and sources are non-empty (never zero by
        # threshold artifact).
        assert mock_bm25.query.called
        assert isinstance(result, dict)
        assert len(result["sources"]) >= 1
        assert result["confidence_score"] > 0.0
        # The dense query must have been asked for the RAW pool.
        _, kwargs = vs.query.call_args
        assert kwargs.get("similarity_floor") == 0.0

    def test_flag_off_is_dense_only_and_ignores_bm25(self):
        """hybrid_search_enabled=False: BM25 store never touched; result equals a
        plain dense-only call (byte-identical behavior guard)."""
        llm, vs, docs, dbg = _base_mocks()
        vs.query.return_value = []

        mock_bm25 = Mock()

        with patch("mimir.services.rag_service.settings") as mock_settings:
            mock_settings.hybrid_search_enabled = False
            mock_settings.rrf_k = 60
            mock_settings.rrf_score_threshold = 0.015
            mock_settings.similarity_threshold = 0.5
            mock_settings.dynamic_filter_percentage = 0.15
            mock_settings.max_sources = 5
            mock_settings.min_sources = 1
            mock_settings.confidence_algorithm = "weighted"
            mock_settings.filename_pre_inclusion = False

            result = asyncio.run(
                _drain_result(
                    question="question dense",
                    context_limit=5,
                    include_sources=True,
                    session_id="dense_1",
                    llm_service=llm,
                    vector_store=vs,
                    document_repository=docs,
                    rag_debug=dbg,
                    bm25_store=mock_bm25,
                )
            )

        mock_bm25.query.assert_not_called()
        assert isinstance(result, dict)
        assert result["sources"] == []
        # Dense query never asks for the raw pool.
        _, kwargs = vs.query.call_args
        assert "similarity_floor" not in kwargs

    def test_hybrid_degrades_to_dense_when_bm25_unbuilt(self):
        """Prime directive: with hybrid enabled but the BM25 index not yet
        built, bm25_store.query() raises; the engine MUST degrade to dense-only and
        still answer, never surface the exception as a broken (confidence 0) reply."""
        from mimir.rag_core.interfaces import VectorStoreOperationError

        llm, vs, docs, dbg = _base_mocks()

        dense_pool = [
            _sr(1, "10", "dense hit one", "a.txt", 0.42),
            _sr(2, "11", "dense hit two", "b.txt", 0.40),
        ]
        vs.query.return_value = dense_pool
        vs.snapshot_active_chunks.return_value = [
            {
                "chunk_id": 1,
                "document_id": "10",
                "text": "dense hit one",
                "source": "a.txt",
                "chunk_index": 0,
                "total_chunks": 1,
                "metadata": {},
            },
            {
                "chunk_id": 2,
                "document_id": "11",
                "text": "dense hit two",
                "source": "b.txt",
                "chunk_index": 0,
                "total_chunks": 1,
                "metadata": {},
            },
        ]

        mock_bm25 = Mock()
        mock_bm25.query.side_effect = VectorStoreOperationError("BM25 index not built")

        with patch("mimir.services.rag_service.settings") as mock_settings:
            mock_settings.hybrid_search_enabled = True
            mock_settings.rrf_k = 60
            mock_settings.rrf_score_threshold = 0.015
            mock_settings.similarity_threshold = 0.5
            mock_settings.dynamic_filter_percentage = 0.15
            mock_settings.max_sources = 5
            mock_settings.min_sources = 1
            mock_settings.confidence_algorithm = "weighted"
            mock_settings.filename_pre_inclusion = False

            result = asyncio.run(
                _drain_result(
                    question="question hybride sans index bm25",
                    context_limit=5,
                    include_sources=True,
                    session_id="degrade_1",
                    llm_service=llm,
                    vector_store=vs,
                    document_repository=docs,
                    rag_debug=dbg,
                    bm25_store=mock_bm25,
                )
            )

        # BM25 was attempted and failed, but the engine still answered from the
        # dense pool (graceful degradation) with real sources + confidence.
        assert mock_bm25.query.called
        assert isinstance(result, dict)
        assert len(result["sources"]) >= 1
        assert result["confidence_score"] > 0.0
