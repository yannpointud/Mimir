"""
Oracle (d): ids and order of the retrieval results, dense and hybrid.

For the ten fixed questions over the fixed corpus, pinned:

- store level: the raw dense ranking of FaissVectorStore.query (default
  threshold and raw pool) and the lexical ranking of Bm25LexicalStore.query;
- pipeline level, for the dense-only and hybrid modes of RagService: the
  candidate list handed to the retrieval debug log (before source filtering)
  and the final ordered sources of the done event.

Chunks are identified by (document_id, chunk_index, chunk_id); scores are
rounded to absorb float noise.
"""

import asyncio
from typing import Any

import pytest

from mimir.config import settings
from mimir.database.connection import db_manager
from mimir.database.repository import DocumentRepository
from tests.oracle.harness import QUESTIONS, assert_snapshot, fake_embedding


def _hit(result) -> list[Any]:
    return [
        str(result.document_id),
        int(result.chunk_index),
        int(result.chunk_id),
        round(float(result.similarity_score), 4),
    ]


def _candidates(env) -> list[list[Any]]:
    recorded = env.rag_debug.last("log_vector_search")
    assert recorded is not None, "retrieval debug log was not called"
    args, kwargs = recorded
    results = kwargs["search_results"] if "search_results" in kwargs else args[1]
    return [_hit(r) for r in results]


def _pipeline(env, question: str, hybrid: bool) -> dict[str, Any]:
    saved = settings.hybrid_search_enabled
    settings.hybrid_search_enabled = hybrid
    env.rag_debug.calls.clear()
    session = db_manager.get_session()
    try:

        async def _collect():
            events = []
            async for event in env.rag_service.answer_stream(
                question=question,
                context_limit=5,
                include_sources=True,
                session_id="oracle-ranking",
                document_repository=DocumentRepository(session),
                reservation=None,
                corpus_version=None,
            ):
                events.append(event)
            return events

        events = asyncio.run(_collect())
    finally:
        session.close()
        settings.hybrid_search_enabled = saved
    done = next(e for e in events if e["type"] == "done")
    return {
        "candidates": _candidates(env),
        "sources": [
            [s["document_id"], s["chunk_index"], round(s["similarity_score"], 4)]
            for s in done["sources"]
        ],
        "confidence_score": done["confidence_score"],
    }


@pytest.mark.parametrize("index", range(len(QUESTIONS)))
def test_retrieval_ranking_for_fixed_questions(oracle_corpus_env, index):
    env = oracle_corpus_env
    question = QUESTIONS[index]
    vector = fake_embedding(question)
    by_chunk_id = {
        meta["chunk_id"]: [str(meta["document_id"]), int(meta["chunk_index"])]
        for meta in env.vector_store.snapshot_active_chunks()
    }
    result = {
        "question": question,
        "store_dense_default_threshold": [
            _hit(r) for r in env.vector_store.query(vector, top_k=10)
        ],
        "store_dense_raw_pool": [
            _hit(r) for r in env.vector_store.query(vector, top_k=10, similarity_floor=0.0)
        ],
        "store_bm25": [
            by_chunk_id.get(chunk_id, ["?", -1]) + [int(chunk_id), round(float(score), 4)]
            for chunk_id, score in env.bm25_store.query(question, 10)
        ],
        "pipeline_dense": _pipeline(env, question, hybrid=False),
        "pipeline_hybrid": _pipeline(env, question, hybrid=True),
    }
    assert_snapshot(f"retrieval_question_{index:02d}", result)
