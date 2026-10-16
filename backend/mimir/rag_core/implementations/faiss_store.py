"""
FAISS Vector Store Implementation
Provides high-performance vector similarity search using Facebook AI Similarity Search (FAISS)
"""

import faiss
import numpy as np
import pickle
import threading
import time
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from datetime import datetime

from pydantic import BaseModel

from mimir.rag_core.interfaces import (
    AbstractVectorStore,
    Chunk,
    SearchResult,
    VectorStoreConnectionError,
    VectorStoreOperationError,
)
from mimir.monitoring.logger import setup_logger

logger = setup_logger(__name__)

# FAISS distances carry float32 noise (~1e-7) that depends on the SIMD build of
# the host CPU. Similarity scores are rounded so that ranking and threshold
# checks give the same result on every machine.
_SIMILARITY_DECIMALS = 6


class MetadataPayload(BaseModel):
    """Versioned JSON payload for FAISS metadata persistence.

    Replaces the previous unvalidated pickle format: JSON deserialization
    cannot execute arbitrary code, and the pydantic model validates the
    schema (required fields, types, version) on load.

    Note: schema_version is intentionally required (no default). This is a
    security-relevant validation control (ASVS V5 Input Validation, unsafe
    deserialization) -- a payload silently defaulting a missing version field would
    defeat the purpose of schema validation on load(). Callers writing new
    payloads (persist()) always pass schema_version=1 explicitly.
    """

    schema_version: int
    metadata: list[dict[str, Any]]
    document_to_chunks: dict[str, list[int]]
    stats: dict[str, Any]
    saved_at: str


class FaissVectorStore(AbstractVectorStore):
    """
    FAISS-based vector store implementation with persistence and thread safety
    """

    def __init__(
        self,
        dimension: int,
        index_path: str,
        metadata_path: str,
        similarity_threshold: float = 0.5,
        index_type: str = "FlatL2",
    ):
        """Initialize FAISS vector store.

        Only the "FlatL2" ``index_type`` is built; the value is otherwise a
        passthrough label used for logging/tests.
        """
        self.dimension = dimension
        self.index_path = Path(index_path)
        # Normalize metadata path to JSON (write target), regardless of the
        # extension passed via config (.pkl or .json); derive the legacy
        # pickle path as a fallback for transparent migration on load().
        self.metadata_path = Path(metadata_path).with_suffix(".json")
        self.legacy_metadata_path = Path(metadata_path).with_suffix(".pkl")
        # Set to True when load() migrated from the legacy pickle; the next
        # successful persist() then retires the .pkl (renamed .pkl.migrated)
        # so the unsafe pickle.load() path can never run again.
        self._legacy_pickle_pending_retirement = False
        self.similarity_threshold = similarity_threshold
        self.index_type = index_type

        # Thread safety
        self._lock = threading.RLock()

        # FAISS index and metadata storage. faiss ships no type stubs, so the
        # index object is untyped; _initialize_index() sets it below.
        self.index: Any = None
        self.metadata: list[dict[str, Any]] = []
        self.document_to_chunks: dict[str, list[int]] = {}  # document_id -> chunk_ids

        # Statistics
        self._stats: dict[str, Any] = {
            "total_vectors": 0,
            "total_documents": 0,
            "last_updated": None,
        }

        # Create directories if needed
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize or load index
        self._initialize_index()

        logger.info(
            f"FAISS vector store initialized: {self.index_type}, "
            f"dim={dimension}, threshold={similarity_threshold}"
        )

    def _initialize_index(self):
        """Initialize or load existing FAISS index"""
        try:
            # Recognize both the current JSON metadata format and the legacy
            # pickle format: without the OR on legacy_metadata_path, a legacy
            # install (index + .pkl, no .json yet) would fall through to
            # _create_new_index() and WIPE the existing index.
            if self.index_path.exists() and (
                self.metadata_path.exists() or self.legacy_metadata_path.exists()
            ):
                # Load existing index
                logger.info("Loading existing FAISS index...")
                self.load()
            else:
                # Create new index
                logger.info(f"Creating new FAISS index: {self.index_type}")
                self._create_new_index()

        except Exception as e:  # noqa: BLE001 - startup fallback: an unreadable index starts empty
            logger.error(f"Failed to initialize FAISS index: {str(e)}")
            # Fallback: create new index
            self._create_new_index()

    def _create_new_index(self):
        with self._lock:
            try:
                # Simple brute-force search (good for small datasets).
                # This is the only index type ever configured in production
                # (dependencies.py hardcodes "FlatL2"); the other unreachable
                # branches were removed as dead code.
                self.index = faiss.IndexFlatL2(self.dimension)

                # Reset metadata
                self.metadata = []
                self.document_to_chunks = {}
                self._update_stats()

                logger.info(f"Created new {self.index_type} index with dimension {self.dimension}")

            except Exception as e:  # noqa: BLE001 - any failure becomes VectorStoreConnectionError
                error_msg = f"Failed to create FAISS index: {str(e)}"
                logger.error(error_msg)
                raise VectorStoreConnectionError(error_msg) from e

    def upsert(self, chunks: list[Chunk]) -> bool:
        """Insert or update chunks in the vector store

        Raises:
            VectorStoreOperationError: If upsert operation fails
        """
        if not chunks:
            logger.warning("No chunks provided for upsert")
            return True

        start_time = time.time()

        with self._lock:
            try:
                # For true UPSERT: delete existing chunks for these documents first
                document_ids_to_upsert = set()
                for chunk in chunks:
                    document_ids_to_upsert.add(chunk.document_id)

                # Delete existing chunks for all documents being upserted
                for document_id in document_ids_to_upsert:
                    if document_id in self.document_to_chunks:
                        self.delete(document_id)
                        logger.debug(
                            f"Deleted existing chunks for document {document_id} before upsert"
                        )

                # Convert embeddings to float32 numpy array
                embeddings = []
                chunk_metadata = []

                for chunk in chunks:
                    # Validate embedding
                    if chunk.embedding is None or len(chunk.embedding) != self.dimension:
                        raise VectorStoreOperationError(
                            f"Invalid embedding dimension: expected {self.dimension}, "
                            f"got {len(chunk.embedding) if chunk.embedding is not None else 'None'}"
                        )

                    embedding = np.array(chunk.embedding, dtype=np.float32)
                    embeddings.append(embedding)

                    # Prepare metadata
                    metadata: dict[str, Any] = {
                        "document_id": chunk.document_id,
                        "text": chunk.text,  # No truncation - already handled by chunking
                        "source": chunk.source,
                        "chunk_index": chunk.chunk_index,
                        "total_chunks": chunk.total_chunks,
                        "preserve": chunk.preserve,
                        "indexed_at": datetime.utcnow().isoformat(),
                        "metadata": chunk.metadata,
                    }
                    chunk_metadata.append(metadata)

                # Convert to numpy array
                embeddings_array = np.array(embeddings, dtype=np.float32)

                # Add to FAISS index
                start_idx = self.index.ntotal
                self.index.add(embeddings_array)

                # Update metadata
                for i, meta in enumerate(chunk_metadata):
                    chunk_id = start_idx + i
                    meta["chunk_id"] = chunk_id
                    self.metadata.append(meta)

                    # Track document -> chunks mapping
                    document_id = meta["document_id"]
                    if document_id not in self.document_to_chunks:
                        self.document_to_chunks[document_id] = []
                    self.document_to_chunks[document_id].append(chunk_id)

                # Update statistics
                self._update_stats()

                duration_ms = (time.time() - start_time) * 1000

                logger.info(
                    f"Upserted {len(chunks)} chunks in {duration_ms:.1f}ms. "
                    f"Total vectors: {self.index.ntotal}",
                    extra={
                        "extra_fields": {
                            "chunk_count": len(chunks),
                            "duration_ms": duration_ms,
                            "total_vectors": self.index.ntotal,
                            "type": "vector_upsert",
                        }
                    },
                )

                return True

            except Exception as e:  # noqa: BLE001 - any failure becomes VectorStoreOperationError
                error_msg = f"Failed to upsert chunks: {str(e)}"
                logger.error(error_msg)
                raise VectorStoreOperationError(error_msg) from e

    def query(
        self,
        vector: np.ndarray,
        top_k: int = 5,
        filter_dict: dict[str, Any] | None = None,
        similarity_floor: float | None = None,
    ) -> list[SearchResult]:
        """Search for similar vectors, ordered by similarity.

        ``similarity_floor`` overrides the minimum similarity a result must
        reach to be kept. When None (default) the store's own
        similarity_threshold is used -- byte-identical to the pre-hybrid
        behavior. Hybrid retrieval passes similarity_floor=0.0 to obtain the RAW
        candidate pool, so RRF can re-rank chunks that the cosine threshold would
        otherwise drop.

        Raises:
            VectorStoreOperationError: If query operation fails
        """
        if self.index is None or self.index.ntotal == 0:
            logger.warning("Vector store is empty")
            return []

        start_time = time.time()

        with self._lock:
            try:
                # Validate query vector
                query_vector = np.array(vector, dtype=np.float32)
                if len(query_vector) != self.dimension:
                    raise VectorStoreOperationError(
                        f"Query vector dimension mismatch: expected {self.dimension}, "
                        f"got {len(query_vector)}"
                    )

                # Ensure vector is 2D for FAISS
                if query_vector.ndim == 1:
                    query_vector = query_vector.reshape(1, -1)

                # Search
                k = min(top_k * 2, self.index.ntotal)  # Get more results for filtering
                distances, indices = self.index.search(query_vector, k)

                # Process results
                results = []
                for dist, idx in zip(distances[0], indices[0], strict=False):
                    # Skip invalid indices
                    if idx < 0 or idx >= len(self.metadata):
                        continue

                    # Normalized vectors: squared L2 distance maps to cosine similarity
                    similarity = round(max(0.0, 1.0 - float(dist) / 2), _SIMILARITY_DECIMALS)

                    # Apply similarity threshold. Default (similarity_floor is
                    # None) keeps the exact dense-only semantics; hybrid mode
                    # passes similarity_floor=0.0 to keep the raw pool intact for
                    # RRF fusion.
                    threshold = (
                        self.similarity_threshold if similarity_floor is None else similarity_floor
                    )
                    if similarity < threshold:
                        continue

                    # Get metadata
                    meta = self.metadata[idx]

                    # Skip deleted chunks (fix for ghost chunks issue)
                    if meta.get("deleted", False):
                        continue

                    # Apply filters if provided
                    if filter_dict and not self._matches_filter(meta, filter_dict):
                        continue

                    # Create search result
                    result = SearchResult(
                        chunk_id=meta["chunk_id"],
                        document_id=meta["document_id"],
                        text=meta["text"],
                        source=meta["source"],
                        similarity_score=similarity,
                        chunk_index=meta["chunk_index"],
                        total_chunks=meta["total_chunks"],
                        metadata=meta.get("metadata", {}),
                    )
                    results.append(result)

                # Highest similarity first; chunk_id breaks ties deterministically
                # before the pool is cut to top_k.
                results.sort(key=lambda r: (-r.similarity_score, r.chunk_id))
                results = results[:top_k]

                duration_ms = (time.time() - start_time) * 1000

                logger.debug(
                    f"Query returned {len(results)} results in {duration_ms:.1f}ms",
                    extra={
                        "extra_fields": {
                            "results_count": len(results),
                            "duration_ms": duration_ms,
                            "top_k": top_k,
                            "type": "vector_query",
                        }
                    },
                )

                return results

            except Exception as e:  # noqa: BLE001 - any failure becomes VectorStoreOperationError
                error_msg = f"Failed to query vectors: {str(e)}"
                logger.error(error_msg)
                raise VectorStoreOperationError(error_msg) from e

    def _matches_filter(self, metadata: dict[str, Any], filter_dict: dict[str, Any]) -> bool:
        for key, value in filter_dict.items():
            if key not in metadata:
                return False
            if metadata[key] != value:
                return False
        return True

    def delete(self, document_id: str) -> bool:
        """Delete all chunks for a document

        Note: FAISS doesn't support efficient deletion, so we mark as deleted
        and rebuild index periodically or on demand
        """
        with self._lock:
            try:
                if document_id not in self.document_to_chunks:
                    logger.warning(f"Document {document_id} not found for deletion")
                    return False

                chunk_ids = self.document_to_chunks[document_id]

                # Mark chunks as deleted in metadata
                deleted_count = 0
                for chunk_id in chunk_ids:
                    if chunk_id < len(self.metadata):
                        self.metadata[chunk_id]["deleted"] = True
                        self.metadata[chunk_id]["deleted_at"] = datetime.utcnow().isoformat()
                        deleted_count += 1

                # Remove from document mapping
                del self.document_to_chunks[document_id]

                # Update statistics
                self._update_stats()

                logger.info(
                    f"Marked {deleted_count} chunks as deleted for document: {document_id}",
                    extra={
                        "extra_fields": {
                            "document_id": document_id,
                            "deleted_count": deleted_count,
                            "type": "vector_delete",
                        }
                    },
                )

                # Check if we should trigger optimization (when >25% of vectors are deleted)
                deleted_count = sum(1 for meta in self.metadata if meta.get("deleted", False))
                total_count = len(self.metadata)

                if total_count > 0 and (deleted_count / total_count) > 0.25:
                    logger.info(
                        f"Triggering automatic optimization: {deleted_count}/{total_count} vectors deleted"
                    )
                    try:
                        self.optimize()
                    except Exception as e:  # noqa: BLE001 - best effort: the delete already succeeded
                        logger.warning(f"Automatic optimization failed: {e}")
                        # Don't fail the delete operation if optimization fails

                return True

            except Exception as e:  # noqa: BLE001 - any failure becomes VectorStoreOperationError
                error_msg = f"Failed to delete document {document_id}: {str(e)}"
                logger.error(error_msg)
                raise VectorStoreOperationError(error_msg) from e

    def get_stats(self) -> dict[str, Any]:
        """Get vector store statistics"""
        with self._lock:
            active_vectors = sum(1 for meta in self.metadata if not meta.get("deleted", False))
            deleted_vectors = sum(1 for meta in self.metadata if meta.get("deleted", False))

            return {
                "total_vectors": self.index.ntotal if self.index else 0,
                "active_vectors": active_vectors,
                "deleted_vectors": deleted_vectors,
                "total_documents": len(self.document_to_chunks),
                "index_type": self.index_type,
                "dimension": self.dimension,
                "similarity_threshold": self.similarity_threshold,
                "last_updated": self._stats.get("last_updated"),
                "memory_usage_mb": self._estimate_memory_usage(),
            }

    def get_corpus_version(self) -> str:
        """Return a cheap corpus-version token used to scope cache entries.

        This is the ISO-8601 `last_updated` timestamp already bumped by
        `_update_stats()` at the end of every `upsert()` and `delete()`, i.e.
        on every corpus mutation. Any ingestion or deletion therefore changes
        this token, which implicitly invalidates all corpus-versioned cache
        entries without any extra bookkeeping. Read under the same
        lock as `get_stats()`, but without assembling the full stats dict.

        Returns:
            str: The corpus version token, or "none" if never mutated.
        """
        with self._lock:
            return self._stats.get("last_updated") or "none"

    def snapshot_active_chunks(self) -> list[dict[str, Any]]:
        """Return a lock-safe snapshot of the non-deleted chunk metadata.

        Used by the BM25 lexical store to rebuild itself from the FAISS
        source of truth. Copies each metadata dict under the store lock so the
        BM25 rebuild — which may run off the event loop via asyncio.to_thread —
        iterates a stable snapshot and can never hit a "list changed size during
        iteration" race with a concurrent upsert/delete.
        """
        with self._lock:
            return [dict(m) for m in self.metadata if not m.get("deleted", False)]

    def _estimate_memory_usage(self) -> float:
        """Estimate memory usage in MB"""
        if not self.index:
            return 0.0

        # Rough estimation: vectors + metadata
        vector_memory = self.index.ntotal * self.dimension * 4  # float32 = 4 bytes
        metadata_memory = len(self.metadata) * 1000  # ~1KB per metadata entry
        return (vector_memory + metadata_memory) / (1024 * 1024)

    def health_check(self) -> bool:
        """Check if vector store is healthy and accessible"""
        try:
            with self._lock:
                # Check if index exists
                if self.index is None:
                    return False

                # Check if we can perform a basic operation
                if self.index.ntotal > 0:
                    # Try a simple query
                    test_vector = np.random.rand(self.dimension).astype(np.float32)
                    test_vector = test_vector.reshape(1, -1)
                    self.index.search(test_vector, 1)

                return True

        except Exception as e:  # noqa: BLE001 - health probe: any failure is reported as unhealthy
            logger.error(f"Vector store health check failed: {str(e)}")
            return False

    def _atomic_write(self, target_path: Path, writer) -> None:
        """Write a file atomically: temp file in the same directory, fsync,
        then os.replace().

        This guarantees that no reader ever observes a partially-written
        file: the temp file is fully written and durably flushed to disk
        BEFORE the atomic rename replaces the target path.

        Args:
            target_path: Final destination path
            writer: Callable receiving the temp file path (str) and writing
                the full content to it (synchronously, closing any handle
                it opens itself)
        """
        target_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(target_path.parent), suffix=".tmp")
        os.close(fd)
        try:
            writer(tmp_path)

            # Reopen the temp file read-only to fsync its content to disk
            # BEFORE the rename, guaranteeing durability ahead of os.replace.
            read_fd = os.open(tmp_path, os.O_RDONLY)
            try:
                os.fsync(read_fd)
            finally:
                os.close(read_fd)

            os.replace(tmp_path, str(target_path))

            # Make the rename itself durable: fsync the parent directory so
            # a power loss cannot roll back the rename (or reorder the index
            # rename after the metadata rename). A kill -9 preserves the page
            # cache, so only a power cut exercises this path.
            dir_fd = os.open(str(target_path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception:  # noqa: BLE001 - remove the temp file on any failure, then re-raise
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def persist(self) -> bool:
        """Persist current state to disk atomically.

        Writes the FAISS index FIRST, then the JSON metadata, each via a
        temp-file-same-dir + fsync + os.replace sequence, inside the same
        lock. This ordering is crash-safe: an interruption between the two
        atomic replaces only ever leaves the index ahead of the metadata
        (harmless orphan vectors), never metadata pointing beyond the index
        (which would corrupt chunk_id references on the next upsert).
        """
        try:
            with self._lock:
                start_time = time.time()

                # 1. Index FIRST (safe crash window: orphan vectors only)
                self._atomic_write(self.index_path, lambda p: faiss.write_index(self.index, p))

                # 2. Metadata SECOND, versioned JSON
                payload = MetadataPayload(
                    schema_version=1,
                    metadata=self.metadata,
                    document_to_chunks=self.document_to_chunks,
                    stats=self._stats,
                    saved_at=datetime.utcnow().isoformat(),
                )
                self._atomic_write(
                    self.metadata_path,
                    lambda p: Path(p).write_bytes(payload.model_dump_json().encode("utf-8")),
                )

                # Retire the legacy pickle after the first successful JSON
                # persist following a migration: rename it so the unsafe
                # pickle.load() fallback can never be re-executed.
                if self._legacy_pickle_pending_retirement and self.legacy_metadata_path.exists():
                    try:
                        retired_path = str(self.legacy_metadata_path) + ".migrated"
                        os.replace(str(self.legacy_metadata_path), retired_path)
                        self._legacy_pickle_pending_retirement = False
                        logger.info(f"Legacy pickle metadata retired: {retired_path}")
                    except OSError as rename_error:
                        # Non-fatal: persist() itself succeeded; retirement
                        # will be retried on the next persist() call.
                        logger.warning(f"Could not retire legacy pickle metadata: {rename_error}")

                duration_ms = (time.time() - start_time) * 1000

                logger.info(
                    f"Persisted FAISS index and metadata in {duration_ms:.1f}ms",
                    extra={
                        "extra_fields": {
                            "vectors": self.index.ntotal,
                            "duration_ms": duration_ms,
                            "type": "vector_persist",
                        }
                    },
                )

                return True

        except Exception as e:  # noqa: BLE001 - any failure becomes VectorStoreConnectionError
            error_msg = f"Failed to persist vector store: {str(e)}"
            logger.error(error_msg)
            raise VectorStoreConnectionError(error_msg) from e

    def load(self) -> bool:
        """Load state from disk.

        Reads metadata.json (validated via MetadataPayload) if present;
        otherwise transparently migrates a legacy metadata.pkl (read once,
        NOT deleted, NOT rewritten here -- the next successful persist()
        call writes it out as JSON and renames the .pkl to .pkl.migrated
        so the pickle.load() path can never run again). Raises if neither
        file exists.
        """
        try:
            with self._lock:
                start_time = time.time()

                # Load FAISS index
                self.index = faiss.read_index(str(self.index_path))

                # Load metadata: JSON-first, legacy pickle fallback
                if self.metadata_path.exists():
                    with open(self.metadata_path, encoding="utf-8") as f:
                        raw = json.load(f)
                    payload = MetadataPayload.model_validate(raw)
                elif self.legacy_metadata_path.exists():
                    logger.warning(
                        f"Migrating legacy pickle metadata: {self.legacy_metadata_path} "
                        f"(will be written as JSON on next persist(), then the .pkl "
                        f"is renamed to .pkl.migrated)"
                    )
                    with open(self.legacy_metadata_path, "rb") as f:
                        legacy = pickle.load(f)
                    # Schedule retirement of the pickle after the next
                    # successful persist() (see persist()).
                    self._legacy_pickle_pending_retirement = True
                    payload = MetadataPayload(
                        schema_version=1,
                        metadata=legacy.get("metadata", []),
                        document_to_chunks=legacy.get("document_to_chunks", {}),
                        stats=legacy.get("stats", {}),
                        saved_at=legacy.get("saved_at", datetime.utcnow().isoformat()),
                    )
                else:
                    raise VectorStoreConnectionError(
                        f"No metadata file found at {self.metadata_path} or {self.legacy_metadata_path}"
                    )

                self.metadata = payload.metadata
                self.document_to_chunks = payload.document_to_chunks
                self._stats = payload.stats

                # Update statistics
                self._update_stats()

                duration_ms = (time.time() - start_time) * 1000

                logger.info(
                    f"Loaded FAISS index with {self.index.ntotal} vectors in {duration_ms:.1f}ms",
                    extra={
                        "extra_fields": {
                            "vectors": self.index.ntotal,
                            "documents": len(self.document_to_chunks),
                            "duration_ms": duration_ms,
                            "type": "vector_load",
                        }
                    },
                )

                return True

        except Exception as e:  # noqa: BLE001 - any failure becomes VectorStoreConnectionError
            error_msg = f"Failed to load vector store: {str(e)}"
            logger.error(error_msg)
            raise VectorStoreConnectionError(error_msg) from e

    def _update_stats(self):
        self._stats.update(
            {
                "total_vectors": self.index.ntotal if self.index else 0,
                "total_documents": len(self.document_to_chunks),
                "last_updated": datetime.utcnow().isoformat(),
            }
        )

    def clean_orphans(
        self, existing_document_ids: set[str] | None = None, create_backup: bool = True
    ) -> dict[str, Any]:
        """Clean orphaned chunks whose documents no longer exist in the database.

        Raises:
            VectorStoreOperationError: If cleanup fails
        """
        with self._lock:
            try:
                start_time = time.time()
                initial_stats = self._chunk_stats()
                logger.info(f"Starting orphan cleanup - Initial state: {initial_stats}")

                if create_backup:
                    self._backup_before_cleanup()

                # If no document_ids provided, retrieve from DB
                if existing_document_ids is None:
                    existing_document_ids = self._get_existing_document_ids()

                orphaned_chunks, orphaned_docs = self._find_orphans(existing_document_ids)
                if not orphaned_chunks:
                    logger.info("No orphaned chunks found")
                    return {
                        "orphaned_chunks_found": 0,
                        "orphaned_documents": 0,
                        "cleaned_chunks": 0,
                        "optimization_triggered": False,
                        "duration_ms": (time.time() - start_time) * 1000,
                        "initial_stats": initial_stats,
                        "final_stats": initial_stats,  # No change
                    }

                logger.info(
                    f"Found {len(orphaned_chunks)} orphaned chunks from {len(orphaned_docs)} documents"
                )
                cleaned_count = self._mark_orphans_deleted(orphaned_chunks, orphaned_docs)
                optimization_triggered = self._optimize_after_cleanup()

                # Save changes
                try:
                    self.persist()
                    logger.info("Orphan cleanup changes persisted successfully")
                except Exception as e:  # noqa: BLE001 - any failure becomes VectorStoreOperationError
                    logger.error(f"Failed to persist cleanup changes: {e}")
                    raise VectorStoreOperationError(f"Cleanup persistence failed: {e}") from e

                final_stats = self._chunk_stats()
                duration_ms = (time.time() - start_time) * 1000
                result = {
                    "orphaned_chunks_found": len(orphaned_chunks),
                    "orphaned_documents": len(orphaned_docs),
                    "cleaned_chunks": cleaned_count,
                    "optimization_triggered": optimization_triggered,
                    "duration_ms": duration_ms,
                    "initial_stats": initial_stats,
                    "final_stats": final_stats,
                }

                logger.info(
                    f"Orphan cleanup completed in {duration_ms:.1f}ms: "
                    f"cleaned {cleaned_count} chunks from {len(orphaned_docs)} orphaned documents",
                    extra={"extra_fields": {"cleanup_result": result, "type": "orphan_cleanup"}},
                )

                return result

            except Exception as e:  # noqa: BLE001 - any failure becomes VectorStoreOperationError
                error_msg = f"Orphan cleanup failed: {str(e)}"
                logger.error(error_msg)
                raise VectorStoreOperationError(error_msg) from e

    def _chunk_stats(self) -> dict[str, int]:
        """Chunk and document counts reported before and after an orphan cleanup."""
        return {
            "total_chunks": len(self.metadata),
            "active_chunks": sum(1 for meta in self.metadata if not meta.get("deleted", False)),
            "deleted_chunks": sum(1 for meta in self.metadata if meta.get("deleted", False)),
            "total_documents": len(self.document_to_chunks),
        }

    def _backup_before_cleanup(self) -> None:
        """Back up the index before an orphan cleanup; a failure never blocks it."""
        backup_timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        try:
            self._create_backup(backup_timestamp)
            logger.info(f"Backup created: {backup_timestamp}")
        except Exception as e:  # noqa: BLE001 - best effort: no backup failure may block the cleanup
            logger.warning(f"Backup creation failed: {e}")

    def _find_orphans(self, existing_document_ids: set) -> tuple[list[dict[str, Any]], set]:
        """Active chunks whose document is not in existing_document_ids, and their documents."""
        orphaned_chunks = []
        orphaned_docs = set()
        for meta in self.metadata:
            doc_id = meta.get("document_id")
            # Skip chunks already marked as deleted
            if doc_id and doc_id not in existing_document_ids and not meta.get("deleted", False):
                orphaned_chunks.append(meta)
                orphaned_docs.add(doc_id)
        return orphaned_chunks, orphaned_docs

    def _mark_orphans_deleted(
        self, orphaned_chunks: list[dict[str, Any]], orphaned_docs: set
    ) -> int:
        """Mark orphaned chunks as deleted and drop their documents' mapping."""
        cleaned_count = 0
        for meta in orphaned_chunks:
            if not meta.get("deleted", False):
                meta["deleted"] = True
                meta["deleted_at"] = datetime.utcnow().isoformat()
                meta["deletion_reason"] = "orphan_cleanup"
                cleaned_count += 1

        for doc_id in orphaned_docs:
            if doc_id in self.document_to_chunks:
                del self.document_to_chunks[doc_id]
                logger.debug(f"Removed orphaned document mapping: {doc_id}")
        return cleaned_count

    def _optimize_after_cleanup(self) -> bool:
        """Optimize the index when more than 25% of its chunks are deleted."""
        total_chunks_after = len(self.metadata)
        deleted_chunks_after = sum(1 for meta in self.metadata if meta.get("deleted", False))
        if total_chunks_after > 0 and (deleted_chunks_after / total_chunks_after) > 0.25:
            logger.info(
                f"Triggering optimization after cleanup: {deleted_chunks_after}/{total_chunks_after} chunks deleted"
            )
            try:
                self.optimize()
                return True
            except Exception as e:  # noqa: BLE001 - best effort: the cleanup itself already succeeded
                # Don't fail the cleanup if optimization fails
                logger.warning(f"Optimization failed after cleanup: {e}")
        return False

    def _create_backup(self, timestamp: str):
        """Create a FAISS backup with timestamp and rotate old backups"""
        try:
            import shutil

            backup_index_path = self.index_path.with_suffix(f".backup_{timestamp}")

            if self.index_path.exists():
                shutil.copy2(self.index_path, backup_index_path)

            # Tolerate the migration window: back up metadata.json if it
            # exists, else fall back to the legacy metadata.pkl. The rotation
            # glob "metadata*.backup_*" already matches both derived suffixes.
            if self.metadata_path.exists():
                backup_metadata_path = self.metadata_path.with_suffix(f".backup_{timestamp}")
                shutil.copy2(self.metadata_path, backup_metadata_path)
            elif self.legacy_metadata_path.exists():
                backup_metadata_path = self.legacy_metadata_path.with_suffix(f".backup_{timestamp}")
                shutil.copy2(self.legacy_metadata_path, backup_metadata_path)
            else:
                backup_metadata_path = None

            logger.debug(f"Backup created: {backup_index_path}, {backup_metadata_path}")

            # Rotate old backups
            self._rotate_backups()

        except Exception as e:  # noqa: BLE001 - log any failure, then re-raise unchanged
            logger.error(f"Backup creation failed: {e}")
            raise

    def _rotate_backups(self):
        """Remove old backups beyond the configured max_backups limit"""
        try:
            from mimir.config import settings

            max_backups = settings.faiss_max_backups if settings else 4

            backup_dir = self.index_path.parent

            # Collect index backups sorted by modification time (newest first)
            index_backups = sorted(
                backup_dir.glob("index*.backup_*"), key=lambda f: f.stat().st_mtime, reverse=True
            )

            # Collect metadata backups sorted by modification time (newest first)
            metadata_backups = sorted(
                backup_dir.glob("metadata*.backup_*"), key=lambda f: f.stat().st_mtime, reverse=True
            )

            # Remove excess backups
            removed = 0
            for old_backup in index_backups[max_backups:]:
                old_backup.unlink()
                removed += 1
            for old_backup in metadata_backups[max_backups:]:
                old_backup.unlink()
                removed += 1

            if removed > 0:
                logger.info(
                    f"Backup rotation: removed {removed} old backup files (max_backups={max_backups})"
                )

        except Exception as e:  # noqa: BLE001 - best effort: the backup itself already exists
            logger.warning(f"Backup rotation failed: {e}")

    def _get_existing_document_ids(self) -> set:
        """Retrieve existing document_ids from the database."""
        try:
            # Dynamic import to avoid circular dependencies
            from mimir.database.connection import DatabaseManager
            from mimir.database.repository import DocumentRepository

            # Use get_session() directly rather than get_db_session() which is a generator
            db_manager = DatabaseManager()
            session = db_manager.get_session()
            try:
                doc_repo = DocumentRepository(session)
                documents = doc_repo.get_all()  # Retrieve all documents
                return {str(doc.id) for doc in documents}
            finally:
                session.close()

        except Exception as e:  # noqa: BLE001 - fallback contract: use the ids of the FAISS mapping
            logger.error(f"Failed to get existing document IDs from database: {e}")
            # Fallback: use IDs present in the FAISS mapping
            return set(self.document_to_chunks.keys())

    def optimize(self):
        """
        Optimize the index by removing deleted entries (rebuild)
        This is an expensive operation and should be done periodically
        """
        with self._lock:
            if not self.index or self.index.ntotal == 0:
                logger.info("No vectors to optimize")
                return

            # Count deleted vectors
            deleted_count = sum(1 for meta in self.metadata if meta.get("deleted", False))

            if deleted_count == 0:
                logger.info("No deleted vectors to remove - optimization not needed")
                return

            logger.info(
                f"Starting index optimization - removing {deleted_count} deleted vectors out of {len(self.metadata)}"
            )

            # Extract active (non-deleted) entries
            active_entries = []
            active_vectors = []

            for i, meta in enumerate(self.metadata):
                if not meta.get("deleted", False):
                    active_entries.append(meta)
                    # Get the vector from FAISS
                    if i < self.index.ntotal:
                        vector = self.index.reconstruct(i)
                        active_vectors.append(vector)

            # Create new index
            new_index = faiss.IndexFlatL2(self.dimension)

            # Map each surviving chunk's OLD id (still referenced by
            # document_to_chunks) to its NEW compacted position. The old id MUST
            # be captured BEFORE meta['chunk_id'] is overwritten below: these ids
            # double as direct indices into self.metadata in delete(), so
            # rebuilding the mapping by comparing stale ids against reassigned
            # ones would attribute chunks to the wrong document (silent
            # cross-document data loss).
            id_remap = {}
            if active_vectors:
                # Add all active vectors to new index
                vectors_array = np.array(active_vectors, dtype=np.float32)
                new_index.add(vectors_array)

                # Update chunk IDs in metadata to match new index positions
                for i, meta in enumerate(active_entries):
                    id_remap[meta["chunk_id"]] = i
                    meta["chunk_id"] = i

            # Replace old index and metadata
            old_total = self.index.ntotal
            self.index = new_index
            self.metadata = active_entries

            # Rebuild the document mapping against the new positions. Chunk ids
            # absent from id_remap belonged to vectors removed in this rebuild
            # and are dropped; documents left without any surviving chunk are
            # pruned entirely.
            new_mapping = {}
            for doc_id, old_chunk_ids in self.document_to_chunks.items():
                remapped = [id_remap[cid] for cid in old_chunk_ids if cid in id_remap]
                if remapped:
                    new_mapping[doc_id] = remapped
            self.document_to_chunks = new_mapping

            # Save optimized index
            try:
                self.persist()
                logger.info(
                    f"Index optimization completed: {old_total} → {self.index.ntotal} vectors "
                    f"({deleted_count} deleted vectors removed)"
                )
            except Exception as e:  # noqa: BLE001 - any failure becomes VectorStoreOperationError
                logger.error(f"Failed to save optimized index: {e}")
                raise VectorStoreOperationError(f"Index optimization save failed: {e}") from e

    def rebuild_vector_store(
        self,
        force_rebuild: bool = False,
        cleanup_orphans: bool = True,
        existing_document_ids: set | None = None,
    ) -> dict[str, Any]:
        """Completely rebuild the vector store with optional orphan cleanup.

        Args:
            force_rebuild: Force rebuild even without deleted chunks
            cleanup_orphans: Clean orphaned chunks before rebuild
            existing_document_ids: Document ids known to the database, forwarded
                to clean_orphans(). When None, clean_orphans() queries the
                database itself.
        """
        with self._lock:
            try:
                start_time = time.time()

                logger.info(
                    f"Starting vector store rebuild (force={force_rebuild}, cleanup_orphans={cleanup_orphans})"
                )

                # Initial statistics
                initial_stats = self.get_stats()

                # Orphan cleanup if requested
                cleanup_result = None
                if cleanup_orphans:
                    try:
                        cleanup_result = self.clean_orphans(
                            existing_document_ids=existing_document_ids, create_backup=True
                        )
                        logger.info(
                            f"Orphan cleanup completed: {cleanup_result['cleaned_chunks']} chunks cleaned"
                        )
                    except Exception as e:  # noqa: BLE001 - best effort: the rebuild goes on without cleanup
                        logger.warning(f"Orphan cleanup failed during rebuild: {e}")
                        # Continue rebuild even if cleanup fails

                # Check if rebuild is needed
                deleted_count = sum(1 for meta in self.metadata if meta.get("deleted", False))
                total_count = len(self.metadata)

                rebuild_needed = force_rebuild or (total_count > 0 and deleted_count > 0)

                if not rebuild_needed:
                    logger.info("Rebuild not needed - no deleted chunks found")
                    duration_ms = (time.time() - start_time) * 1000
                    return {
                        "rebuild_performed": False,
                        "reason": "no_deleted_chunks",
                        "cleanup_result": cleanup_result,
                        "duration_ms": duration_ms,
                        "initial_stats": initial_stats,
                        "final_stats": self.get_stats(),
                    }

                # Execute optimization (rebuild)
                self.optimize()

                # Final statistics
                final_stats = self.get_stats()
                duration_ms = (time.time() - start_time) * 1000

                result = {
                    "rebuild_performed": True,
                    "cleanup_result": cleanup_result,
                    "deleted_chunks_removed": deleted_count,
                    "duration_ms": duration_ms,
                    "initial_stats": initial_stats,
                    "final_stats": final_stats,
                }

                logger.info(
                    f"Vector store rebuild completed in {duration_ms:.1f}ms: "
                    f"removed {deleted_count} deleted chunks",
                    extra={"extra_fields": {"rebuild_result": result, "type": "vector_rebuild"}},
                )

                return result

            except Exception as e:  # noqa: BLE001 - any failure becomes VectorStoreOperationError
                error_msg = f"Vector store rebuild failed: {str(e)}"
                logger.error(error_msg)
                raise VectorStoreOperationError(error_msg) from e

    def get_document_chunks(self, document_id: str) -> list[Chunk]:
        """Get all chunks for a specific document"""
        try:
            with self._lock:
                chunk_ids = self.document_to_chunks.get(document_id, [])
                chunks = []

                for chunk_id in chunk_ids:
                    # Find metadata for this chunk
                    for i, meta in enumerate(self.metadata):
                        if (
                            meta.get("chunk_id") == chunk_id
                            and not meta.get("deleted", False)
                            and meta.get("document_id") == document_id
                        ):
                            # Retrieve the vector from FAISS
                            if i < self.index.ntotal:
                                vector = self.index.reconstruct(i)

                                # Create the Chunk object
                                chunk = Chunk(
                                    text=meta.get("text", ""),
                                    embedding=vector,
                                    document_id=document_id,
                                    chunk_index=meta.get("chunk_index", 0),
                                    total_chunks=len(chunk_ids),
                                    source=meta.get("source", ""),
                                    metadata=meta.get("metadata", {}),
                                    preserve=meta.get("preserve", False),
                                )
                                chunks.append(chunk)
                            break

                # Sort by chunk_index
                chunks.sort(key=lambda x: x.chunk_index)

                logger.debug(f"Retrieved {len(chunks)} chunks for document {document_id}")
                return chunks

        except Exception as e:  # noqa: BLE001 - fallback contract: no chunks on any failure
            logger.error(f"Failed to get chunks for document {document_id}: {e}")
            return []
