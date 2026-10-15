"""
Integration test for two-index synchronization on deletion.

Proves that a document deletion, routed through the SINGLE-WRITER paths, removes
the document's chunks from BOTH the dense (FAISS) and the lexical (BM25) index,
and that an exact-term (identifier/acronym) query still recovers the correct
REMAINING document afterwards.

Fully synthetic: fake, deterministic embeddings (no Mistral call), real
FaissVectorStore + real Bm25LexicalStore + real IngestionProcessor pipeline for
ingestion, and the real ``delete_document`` endpoint function for deletion.
"""

import hashlib
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest

from src.ingestion.processor import IngestionProcessor
from src.ingestion.queue_manager import IngestionTask
from src.ingestion.chunking import ChunkingConfig
from src.llm_interface.interfaces import EmbeddingResponse
from src.cost.budget_guard import BudgetReservation
from src.rag_core.implementations.faiss_store import FaissVectorStore
from src.rag_core.implementations.bm25_store import Bm25LexicalStore
from src.api.endpoints.documents import delete_document

# Dense embedding dimension used by the synthetic corpus (small, arbitrary).
_DIM = 16

# Two documents, each carrying a distinct EXACT identifier the dense path would
# tend to miss but the lexical path must recover.
_DOC_A_ID = "1"
_DOC_A_TERM = "JIRA-4521"
_DOC_A_TEXT = "Le ticket JIRA-4521 concerne la migration du serveur applicatif principal."

_DOC_B_ID = "2"
_DOC_B_TERM = "ACME-9999"
_DOC_B_TEXT = "Le rapport ACME-9999 documente la procedure de sauvegarde hebdomadaire."


def _fake_embedding(text: str) -> list:
    """Deterministic fake embedding derived from the text hash (no Mistral)."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # Repeat the digest bytes to fill the dimension, scale to a small range.
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
    guard.reserve.return_value = BudgetReservation(today="2026-07-13", estimate_eur=0.001)
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
    """Return the set of document_ids the BM25 index returns for an exact term."""
    hits = bm25_store.query(term, top_k=50)
    return {vector_store.metadata[chunk_id]["document_id"] for chunk_id, _ in hits}


def _docs_from_faiss(vector_store):
    """Return the set of document_ids FAISS still returns (non-deleted chunks)."""
    results = vector_store.query(
        vector=np.zeros(_DIM, dtype=np.float32), top_k=100, similarity_floor=0.0
    )
    return {r.document_id for r in results}


@pytest.mark.asyncio
async def test_delete_syncs_both_indexes_and_keeps_exact_term_for_remaining_doc(
    processor, vector_store, bm25_store, document_repository, temp_dir
):
    """Deleting a document removes it from BOTH indexes and
    an exact-term query still finds the correct remaining document."""
    # --- Ingest two documents through the real single-writer pipeline. ---
    await _ingest(processor, temp_dir, _DOC_A_ID, _DOC_A_TEXT)
    await _ingest(processor, temp_dir, _DOC_B_ID, _DOC_B_TEXT)

    # Both indexes see both documents; exact terms resolve to the right doc.
    assert _DOC_A_ID in _docs_from_bm25(vector_store, bm25_store, _DOC_A_TERM)
    assert _DOC_B_ID in _docs_from_bm25(vector_store, bm25_store, _DOC_B_TERM)
    assert {_DOC_A_ID, _DOC_B_ID}.issubset(_docs_from_faiss(vector_store))

    # --- Delete document A through the real endpoint (single-writer delete). ---
    doc_a = Mock()
    doc_a.preserve = False
    doc_a.filename = "doc_1.txt"
    doc_a.path = str(temp_dir / "already_removed.txt")  # nonexistent -> skip file delete
    document_repository.get_by_id.return_value = doc_a
    document_repository.delete.return_value = True
    audit_repo = Mock()

    await delete_document(
        document_id=int(_DOC_A_ID),
        force=False,
        current_user={"sub": "admin"},
        doc_repo=document_repository,
        audit_repo=audit_repo,
        vector_store=vector_store,
        bm25_store=bm25_store,
    )

    # --- Dense index: document A gone, document B remains. ---
    faiss_docs = _docs_from_faiss(vector_store)
    assert _DOC_A_ID not in faiss_docs
    assert _DOC_B_ID in faiss_docs

    # --- Lexical index: A's exact term no longer resolves to A. ---
    assert _DOC_A_ID not in _docs_from_bm25(vector_store, bm25_store, _DOC_A_TERM)

    # --- Criterion 3 core: the REMAINING document is still found by its exact
    # identifier via the lexical index. ---
    assert _DOC_B_ID in _docs_from_bm25(vector_store, bm25_store, _DOC_B_TERM)
