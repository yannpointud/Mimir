#!/usr/bin/env python
"""One-off corpus ingestion for the RAGAS baseline (dev/ops helper).

Ingests every file under ``data/generated_documents/`` through the REAL
IngestionProcessor pipeline (extract -> chunk -> embed -> FAISS upsert -> BM25
rebuild), exactly like an admin upload, so both the dense (FAISS) and lexical
(BM25) indexes are populated for the hybrid retrieval measurements.

Run from the repository root:
    python scripts/ingest_corpus.py

Requires MISTRAL_API_KEY in backend/.env (loaded here, never printed). Embeddings
are batched by MistralAPIService; the free-tier 1 call/sec limit is respected by
the SDK's 429/Retry-After handling.
"""

import asyncio
import hashlib
import os
import shutil
import sys
from pathlib import Path

# Load backend/.env before importing settings (read relative to the cwd)
_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _REPO_ROOT / "backend"

from dotenv import dotenv_values

# Load backend/.env into the process environment BEFORE importing settings,
# so MISTRAL_API_KEY (and friends) are available. The key is never logged.
for _k, _v in dotenv_values(str(_BACKEND / ".env")).items():
    if _v is not None and _k not in os.environ:
        os.environ[_k] = _v

from mimir.config import settings
from mimir.database.connection import init_database, db_manager
from mimir.ingestion.processor import IngestionProcessor
from mimir.ingestion.chunking import ChunkingConfig
from mimir.api.dependencies import (
    get_llm_service,
    get_vector_store,
    get_document_repository,
    get_bm25_store,
)

SOURCE_DIR = _REPO_ROOT / "data" / "generated_documents"


async def main() -> int:
    if not settings.mistral_api_key:
        print("ERROR: MISTRAL_API_KEY is not set (backend/.env). Cannot embed.")
        return 1

    files = sorted(
        p for p in SOURCE_DIR.iterdir() if p.suffix.lower() in {".pdf", ".docx", ".txt", ".md"}
    )
    if not files:
        print(f"ERROR: no ingestable documents found in {SOURCE_DIR}")
        return 1
    print(f"Found {len(files)} documents to ingest from {SOURCE_DIR}")

    init_database()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    llm_service = get_llm_service()
    vector_store = get_vector_store()
    bm25_store = get_bm25_store()

    chunking_config = ChunkingConfig(
        chunk_size=settings.max_chunk_size,
        overlap=settings.chunk_overlap,
    )

    with db_manager.get_session_context() as session:
        document_repo = get_document_repository(session)

        processor = IngestionProcessor(
            llm_service=llm_service,
            vector_store=vector_store,
            document_repository=document_repo,
            chunking_config=chunking_config,
            max_file_size_mb=settings.max_file_size_mb,
            max_chunks_per_doc=settings.max_chunks_per_doc,
            bm25_store=bm25_store,
        )
        await processor.start()

        queued = 0
        for src in files:
            content = src.read_bytes()
            file_hash = hashlib.sha256(content).hexdigest()
            if document_repo.get_by_hash(file_hash):
                print(f"  skip (already ingested): {src.name}")
                continue
            dest = upload_dir / f"{file_hash}_{src.name}"
            shutil.copyfile(src, dest)
            document = document_repo.create(
                filename=src.name,
                path=str(dest),
                file_hash=file_hash,
                preserve=False,
            )
            if processor.queue_document(
                file_path=str(dest),
                document_id=str(document.id),
                metadata={"source": "ingest_corpus.py"},
            ):
                queued += 1
                print(f"  queued [{queued}]: {src.name} (doc_id={document.id})")

        print(f"Queued {queued} documents; waiting for the worker to drain...")
        # Poll until the queue is empty and stays empty (embedding is batched).
        idle_ticks = 0
        for _ in range(600):  # hard ceiling ~10 min
            await asyncio.sleep(1.0)
            size = processor.get_queue_size()
            if size == 0:
                idle_ticks += 1
                if idle_ticks >= 3:
                    break
            else:
                idle_ticks = 0
                print(f"  queue size: {size}")

        await processor.stop(timeout=30.0)

    # Report final index state.
    stats = vector_store.get_stats() if hasattr(vector_store, "get_stats") else {}
    ntotal = getattr(getattr(vector_store, "index", None), "ntotal", "?")
    print("--- Ingestion complete ---")
    print(f"FAISS vectors (index.ntotal): {ntotal}")
    print(f"FAISS stats: {stats}")
    if bm25_store is not None:
        bm_count = getattr(bm25_store, "size", lambda: "?")
        try:
            print(f"BM25 documents: {bm_count() if callable(bm_count) else bm_count}")
        except Exception as e:  # noqa: BLE001 - CLI report: the count is informational only
            print(f"BM25 count unavailable: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
