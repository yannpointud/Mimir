#!/usr/bin/env python3
"""
Replayable SIGKILL-during-persist harness (crash-safe persistence proof).

Spawns a child process that repeatedly upserts and persists to a shared
FAISS index/metadata pair on disk, then sends a real SIGKILL to it at a
randomized, jittered moment landing inside various persist() write windows.
After each kill, the parent instantiates a fresh FaissVectorStore on the
SAME on-disk paths (triggering load()) and asserts the reloaded pair is
coherent: metadata length must never exceed index.ntotal.

This invariant follows directly from the crash-safe write order used by
FaissVectorStore.persist() (index written and atomically replaced BEFORE metadata,
inside the same lock): a crash mid-write can only ever leave the index ahead
of the metadata (harmless orphan vectors, cleaned by existing
clean_orphans()/optimize() machinery), never metadata pointing beyond the
index (which would collide with the next upsert()'s start_idx computation
and corrupt chunk_id references).

All K iterations share ONE dedicated temp dir (continuing on the same
index/metadata files across iterations, like a real process being
repeatedly killed and restarted), cleaned once at the end of the script.
Rerunning the script from scratch creates a fresh temp dir each time, so
it is idempotent and replayable without residual state.

Exit code 0: all K iterations reloaded a coherent pair.
Exit code 1: at least one iteration reloaded an incoherent pair or raised.

Usage: python3 scripts/faiss_kill9_persist.py
"""

import multiprocessing
import os
import random
import shutil
import signal
import sys
import tempfile
import time

import numpy as np

# Add backend to PATH (this is a scripts/ dev-test script, not part of the
# pytest suite -- same sys.path pattern as scripts/test_log_levels.py).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from src.rag_core.implementations.faiss_store import FaissVectorStore  # noqa: E402
from src.rag_core.interfaces import Chunk  # noqa: E402

DIMENSION = 64
ITERATIONS = 15
CHUNKS_PER_ROUND = 10


def _random_chunk(document_id: str) -> Chunk:
    """Build a single Chunk with a random float32 embedding of DIMENSION size."""
    embedding = np.random.rand(DIMENSION).astype(np.float32)
    return Chunk(
        text=f"kill9 test chunk for {document_id}",
        embedding=embedding,
        document_id=document_id,
        chunk_index=0,
        total_chunks=1,
        source="kill9_test",
        metadata={},
    )


def _child_persist_loop(index_path: str, metadata_path: str, iteration: int) -> None:
    """Continuously upsert+persist until this process is killed.

    Runs in a separate OS process (spawned via multiprocessing) so the
    parent can send it a real SIGKILL mid-write. Each round writes a new
    batch of chunks under a unique document_id (prefixed with the iteration
    number) so successive kill-9 iterations never collide with each other's
    document IDs.
    """
    store = FaissVectorStore(
        dimension=DIMENSION,
        index_path=index_path,
        metadata_path=metadata_path,
    )
    round_counter = 0
    while True:
        chunks = [
            _random_chunk(f"iter{iteration}_round{round_counter}_chunk{i}")
            for i in range(CHUNKS_PER_ROUND)
        ]
        store.upsert(chunks)
        store.persist()
        round_counter += 1
        # Small sleep so the parent's jittered kill lands in varied windows
        # across upsert()/persist() rather than always the same phase.
        time.sleep(0.005)


def _run_iteration(iteration: int, index_path: str, metadata_path: str) -> tuple:
    """Run one kill-9 iteration against the shared on-disk pair.

    Returns (coherent: bool, detail: str).
    """
    ctx = multiprocessing.get_context("fork")
    child = ctx.Process(
        target=_child_persist_loop,
        args=(index_path, metadata_path, iteration),
    )
    child.start()

    # Randomized jitter so consecutive iterations land in different write
    # windows (varied points inside upsert()/persist()'s critical section).
    time.sleep(random.uniform(0.01, 0.05))

    # Real SIGKILL -- not SIGTERM -- gives the child zero chance to run any
    # cleanup code, which is exactly the crash scenario persistence must survive.
    os.kill(child.pid, signal.SIGKILL)
    child.join(timeout=5)

    # Moment of truth: reload a fresh store instance from the same on-disk
    # paths. This is the same code path a real server restart takes.
    try:
        reloaded = FaissVectorStore(
            dimension=DIMENSION,
            index_path=index_path,
            metadata_path=metadata_path,
        )
    except Exception as e:
        return False, f"iteration {iteration}: reload raised {e!r}"

    metadata_len = len(reloaded.metadata)
    index_total = reloaded.index.ntotal if reloaded.index else 0

    # Core invariant: metadata must never point beyond the index.
    # Index-ahead-of-metadata (orphan vectors) is expected and harmless;
    # metadata-ahead-of-index is the corruption this harness exists to catch.
    if metadata_len > index_total:
        return False, (
            f"iteration {iteration}: CORRUPTION -- metadata_len={metadata_len} "
            f"> index.ntotal={index_total}"
        )

    return True, (
        f"iteration {iteration}: OK (metadata_len={metadata_len}, index.ntotal={index_total})"
    )


def main() -> int:
    work_dir = tempfile.mkdtemp(prefix="faiss_kill9_")
    try:
        index_path = os.path.join(work_dir, "index.bin")
        metadata_path = os.path.join(work_dir, "metadata.json")

        # Establish an initial coherent state (v1) before any kill, so every
        # iteration's child has a valid base pair to build on.
        seed_store = FaissVectorStore(
            dimension=DIMENSION,
            index_path=index_path,
            metadata_path=metadata_path,
        )
        seed_store.upsert([_random_chunk("seed_doc")])
        seed_store.persist()

        results = []
        for i in range(ITERATIONS):
            coherent, detail = _run_iteration(i, index_path, metadata_path)
            results.append(coherent)
            print(detail)

        failures = sum(1 for c in results if not c)
        if failures:
            print(f"\nFAILED: {failures}/{ITERATIONS} iterations reloaded an incoherent pair.")
            return 1

        print(f"\nSUCCESS: all {ITERATIONS} iterations reloaded a coherent index/metadata pair.")
        return 0
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
