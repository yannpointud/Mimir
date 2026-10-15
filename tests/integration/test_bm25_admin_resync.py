"""
Integration test for the admin "Rebuild Index" BM25 resync.

Proves that the admin ``POST /admin/vector-store/rebuild`` handler resyncs the
BM25 lexical index from the freshly-optimized FAISS snapshot, so a manual
rebuild leaves NO ghost/orphan chunk in the lexical index (anti-ghost).

Ghost scenario reproduced here: a document is dropped from FAISS only (its
chunks marked deleted) WITHOUT the paired BM25 sync, leaving the lexical index
pointing at chunks FAISS no longer serves. The admin rebuild must both optimize
FAISS and rebuild BM25 from the resulting active-chunk snapshot, removing the
ghost.

Fully synthetic: fake deterministic embeddings (no Mistral call), a real
FaissVectorStore + real Bm25LexicalStore + real IngestionProcessor for ingestion,
and the real ``rebuild_vector_store`` endpoint function for the admin rebuild.
"""

import hashlib
import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np  # noqa: F401
import pytest

from src.ingestion.processor import IngestionProcessor
from src.ingestion.queue_manager import IngestionTask
from src.ingestion.chunking import ChunkingConfig
from src.llm_interface.interfaces import EmbeddingResponse
from src.cost.budget_guard import BudgetReservation
from src.rag_core.implementations.faiss_store import FaissVectorStore
from src.rag_core.implementations.bm25_store import Bm25LexicalStore
from src.api.endpoints.admin import rebuild_vector_store

# Dense embedding dimension used by the synthetic corpus (small, arbitrary).
_DIM = 16

# Two documents, each carrying a distinct EXACT identifier the lexical path must
# resolve; document A will become the ghost.
_DOC_A_ID = "1"
_DOC_A_TERM = "JIRA-4521"
_DOC_A_TEXT = "Le ticket JIRA-4521 concerne la migration du serveur applicatif principal."

_DOC_B_ID = "2"
_DOC_B_TERM = "ACME-9999"
_DOC_B_TEXT = "Le rapport ACME-9999 documente la procedure de sauvegarde hebdomadaire."


def _fake_embedding(text: str) -> list:
    """Deterministic fake embedding derived from the text hash (no Mistral)."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = (digest * ((_DIM // len(digest)) + 1))[:_DIM]
    return [(b / 255.0) for b in raw]


class _FakeLLMService:
    """Fake LLM service returning deterministic embeddings, one per input text."""

    async def embed(self, texts):
        return EmbeddingResponse(
            embeddings=[_fake_embedding(t) for t in texts],
            model="fake-embed",
            usage_tokens=len(texts),
            prompt_tokens=len(texts),
            completion_tokens=0,
        )


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def vector_store(temp_dir):
    return FaissVectorStore(
        dimension=_DIM,
        index_path=str(temp_dir / "faiss" / "index.bin"),
        metadata_path=str(temp_dir / "faiss" / "metadata.json"),
        similarity_threshold=0.0,
        index_type="FlatL2",
    )


@pytest.fixture
def bm25_store(temp_dir):
    return Bm25LexicalStore(index_path=str(temp_dir / "bm25" / "index"))


@pytest.fixture
def document_repository():
    repo = Mock()
    repo.update_status.return_value = None
    return repo


@pytest.fixture
def budget_guard():
    guard = Mock()
    guard.reserve.return_value = BudgetReservation(today="2026-07-14", estimate_eur=0.001)
    guard.finalize.return_value = None
    guard.release.return_value = None
    return guard


@pytest.fixture
def usage_tracker():
    tracker = Mock()
    tracker.record.return_value = 0.001
    return tracker


@pytest.fixture
def processor(vector_store, bm25_store, document_repository, budget_guard, usage_tracker):
    return IngestionProcessor(
        llm_service=_FakeLLMService(),
        vector_store=vector_store,
        document_repository=document_repository,
        chunking_config=ChunkingConfig(chunk_size=1000, overlap=120),
        max_file_size_mb=1,
        max_chunks_per_doc=100,
        budget_guard=budget_guard,
        usage_tracker=usage_tracker,
        bm25_store=bm25_store,
    )


async def _ingest(processor, temp_dir, doc_id, text):
    """Run the real ingestion pipeline for one synthetic document."""
    file_path = temp_dir / f"doc_{doc_id}.txt"
    file_path.write_text(text, encoding="utf-8")
    task = IngestionTask(file_path=str(file_path), document_id=doc_id, metadata={})
    success = await processor._process_document_pipeline(task)
    assert success is True, f"ingestion pipeline failed for doc {doc_id}"


def _docs_from_bm25(vector_store, bm25_store, term):
    """Return the set of document_ids BM25 returns for an exact term, restricted
    to POSITIVE-score hits.

    bm25s always returns ``k`` corpus docs even when none match (score 0.0), so a
    score filter is required to tell "the term's text is in the corpus" from "the
    term matched nothing but bm25s padded the result".
    """
    hits = bm25_store.query(term, top_k=50)
    return {
        vector_store.metadata[chunk_id]["document_id"]
        for chunk_id, score in hits
        if score > 0.0
    }


@pytest.mark.asyncio
async def test_admin_rebuild_resyncs_bm25_and_leaves_no_ghost(
    processor, vector_store, bm25_store, temp_dir
):
    """After a manual admin rebuild, the BM25 lexical index
    reflects the optimized FAISS snapshot exactly, so a ghost chunk (dropped from
    FAISS but not from BM25) no longer resolves."""
    # --- Ingest two documents through the real single-writer pipeline. ---
    await _ingest(processor, temp_dir, _DOC_A_ID, _DOC_A_TEXT)
    await _ingest(processor, temp_dir, _DOC_B_ID, _DOC_B_TEXT)

    # Both documents resolve via BM25 exact terms after ingestion.
    assert _DOC_A_ID in _docs_from_bm25(vector_store, bm25_store, _DOC_A_TERM)
    assert _DOC_B_ID in _docs_from_bm25(vector_store, bm25_store, _DOC_B_TERM)

    # --- Manufacture a BM25 ghost: mark document A's chunks deleted in FAISS
    # ONLY (no paired BM25 sync), so the lexical index keeps pointing at chunks
    # FAISS will drop on its next optimize. This is exactly the stale state a
    # FAISS-only admin rebuild leaves behind. We set the flag
    # directly rather than via delete() to avoid delete()'s automatic
    # optimization compacting FAISS immediately (which would resync the mapping
    # and dissolve the ghost before the admin rebuild under test runs). ---
    marked = 0
    for meta in vector_store.metadata:
        if meta["document_id"] == _DOC_A_ID:
            meta["deleted"] = True
            marked += 1
    assert marked > 0, "expected at least one FAISS chunk for document A"
    # Ghost present: A's text is still in the lexical corpus (positive-score hit)
    # and BM25 still carries one more chunk than FAISS now serves as active.
    assert _DOC_A_ID in _docs_from_bm25(vector_store, bm25_store, _DOC_A_TERM), (
        "precondition: BM25 must still carry the ghost before the admin rebuild"
    )
    assert len(bm25_store._chunk_ids) > len(vector_store.snapshot_active_chunks()), (
        "precondition: the ghost means BM25 holds a chunk FAISS no longer serves"
    )

    # --- Run the real admin rebuild endpoint handler. It must optimize FAISS AND
    # resync BM25 from the resulting active-chunk snapshot. Both documents still
    # exist in the database: only the FAISS/BM25 indexes diverged. The orphan
    # cleanup must take that list from the injected repository, never from the
    # process-global database, whose content depends on whatever earlier tests
    # left behind. ---
    audit_repo = Mock()
    audit_repo.create_log.return_value = None
    document_repo = Mock()
    document_repo.get_all.return_value = [Mock(id=int(_DOC_A_ID)), Mock(id=int(_DOC_B_ID))]

    with patch.object(vector_store, "_get_existing_document_ids") as global_db_lookup:
        response = await rebuild_vector_store(
            current_user={"sub": "admin"},
            audit_repo=audit_repo,
            vector_store=vector_store,
            bm25_store=bm25_store,
            document_repo=document_repo,
        )
    assert response.success is True
    global_db_lookup.assert_not_called()
    document_repo.get_all.assert_called_once()

    # --- Anti-ghost core: after the rebuild the BM25 corpus matches the
    # optimized FAISS snapshot exactly (structural proof: no extra ghost chunk),
    # document A's text is gone from the lexical corpus (no positive-score hit),
    # and document B stays recoverable by its exact identifier. A FAISS-only
    # rebuild would leave A's ghost chunk in BM25 and fail all three. ---
    active_after = vector_store.snapshot_active_chunks()
    assert set(bm25_store._chunk_ids) == {c["chunk_id"] for c in active_after}, (
        "ghost chunk survived the admin rebuild — BM25 was not resynced"
    )
    assert _DOC_A_ID not in _docs_from_bm25(vector_store, bm25_store, _DOC_A_TERM), (
        "document A's text still resolves in BM25 after rebuild — ghost survived"
    )
    assert _DOC_B_ID in _docs_from_bm25(vector_store, bm25_store, _DOC_B_TERM)
