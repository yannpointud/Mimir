"""
Concurrency load test proving that concurrent searches against a FAISS
vector store remain safe (no exceptions, no corruption) while an ingestion
(upsert + persist) is actively writing to the SAME singleton instance.

This is the capstone proof for the offload work (asyncio.to_thread
call sites) and the atomic persist work (index-then-metadata crash-safe
writes): it exercises both together under
real concurrent load, sharing ONE FaissVectorStore instance between the
simulated writer and N concurrent readers -- instantiating a separate store
per task would mask exactly the kind of duplicate-instance bug that was
fixed in admin.py (an endpoint building its own FaissVectorStore).

This test is also the base reused by the milestone validation script
(scripts/validate_milestone.sh), so its structure (shared singleton, write contention during
reads, fresh-reload proof) should remain stable for future extension.
"""

import asyncio
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.rag_core.implementations.faiss_store import FaissVectorStore
from src.rag_core.interfaces import Chunk

DIMENSION = 128
INGESTION_BATCHES = 5
CHUNKS_PER_BATCH = 20
N_READERS = 20
QUERIES_PER_READER = 5


@pytest.fixture
def temp_dir():
    """Temporary directory for the store's on-disk files, cleaned after the test."""
    d = tempfile.mkdtemp(prefix="faiss_concurrency_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


def _random_chunk(document_id: str) -> Chunk:
    """Build a single Chunk with a random float32 embedding of DIMENSION size."""
    embedding = np.random.rand(DIMENSION).astype(np.float32)
    return Chunk(
        text=f"concurrency test chunk for {document_id}",
        embedding=embedding,
        document_id=document_id,
        chunk_index=0,
        total_chunks=1,
        source="concurrency_test",
        metadata={},
    )


@pytest.mark.asyncio
@pytest.mark.stress
async def test_concurrent_queries_during_ingestion(temp_dir):
    """Concurrent queries + an active ingestion on ONE shared instance must
    raise nothing, leave get_stats() internally consistent, and a fresh
    reload from disk must reflect the same state.
    """
    index_path = temp_dir / "concurrency_index.bin"
    metadata_path = temp_dir / "concurrency_metadata.json"

    # ONE shared instance for writer AND readers -- see module docstring:
    # a store-per-task would hide the exact admin.py-style bug fixed earlier.
    store = FaissVectorStore(
        dimension=DIMENSION,
        index_path=str(index_path),
        metadata_path=str(metadata_path),
    )

    async def simulated_ingestion():
        """Writer coroutine: several upsert+persist rounds, active for the
        whole test duration, to guarantee real write contention against the
        concurrent readers below (a read-only test would prove nothing)."""
        for batch in range(INGESTION_BATCHES):
            chunks = [_random_chunk(f"batch{batch}_doc{i}") for i in range(CHUNKS_PER_BATCH)]
            await asyncio.to_thread(store.upsert, chunks)
            await asyncio.to_thread(store.persist)

    async def concurrent_query():
        """Reader coroutine: repeated queries against the shared instance
        while the writer above may be mid-upsert/mid-persist."""
        for _ in range(QUERIES_PER_READER):
            vector = np.random.rand(DIMENSION).astype(np.float32)
            await asyncio.to_thread(store.query, vector, 5)

    writer = asyncio.create_task(simulated_ingestion())
    readers = [asyncio.create_task(concurrent_query()) for _ in range(N_READERS)]

    # Primary assertion: nothing raises even under real write contention.
    await asyncio.gather(writer, *readers)

    # Internal consistency after the load: vector count matches metadata
    # length, no negative/mismatched counters.
    stats = store.get_stats()
    assert stats["total_vectors"] == len(store.metadata)
    assert stats["active_vectors"] + stats["deleted_vectors"] == stats["total_vectors"]
    assert stats["total_vectors"] == INGESTION_BATCHES * CHUNKS_PER_BATCH

    # Fresh load() from disk (JSON metadata format) via a NEW
    # instance on the SAME paths -- proves the on-disk pair is coherent, not
    # just the in-memory state of the instance that just wrote it.
    reloaded_store = FaissVectorStore(
        dimension=DIMENSION,
        index_path=str(index_path),
        metadata_path=str(metadata_path),
    )
    reloaded_stats = reloaded_store.get_stats()
    assert reloaded_stats["total_vectors"] == stats["total_vectors"]
    assert len(reloaded_store.metadata) == len(store.metadata)
