"""
FAISS vector store: dense similarity search with crash-safe persistence.

Chunks are never removed from the FAISS index in place: a deletion marks their
metadata as deleted, and optimize() rebuilds a compact index once enough of
them accumulate. A chunk_id is the position of its vector in the index and of
its entry in ``metadata``.
"""

import json
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from pydantic import BaseModel

from mimir.config import settings
from mimir.monitoring.logger import setup_logger
from mimir.rag_core.interfaces import (
    AbstractVectorStore,
    Chunk,
    SearchResult,
    VectorStoreConnectionError,
    VectorStoreOperationError,
)

logger = setup_logger(__name__)

# FAISS distances carry float32 noise (~1e-7) that depends on the SIMD build of
# the host CPU. Similarity scores are rounded so that ranking and threshold
# checks give the same result on every machine.
_SIMILARITY_DECIMALS = 6

# Share of deleted chunks above which a deletion compacts the index
_OPTIMIZE_DELETED_RATIO = 0.25

# Errors FAISS (RuntimeError), the file system and the metadata validation
# (ValueError, including pydantic's ValidationError) raise on persistence.
_PERSISTENCE_ERRORS = (RuntimeError, OSError, ValueError)


class MetadataPayload(BaseModel):
    """Versioned JSON payload of the chunk metadata.

    schema_version is required: a payload silently defaulting it would defeat
    the schema validation done on load().
    """

    schema_version: int
    metadata: list[dict[str, Any]]
    document_to_chunks: dict[str, list[int]]
    stats: dict[str, Any]
    saved_at: str


class FaissVectorStore(AbstractVectorStore):
    """Thread-safe FAISS FlatL2 store persisted as index.bin plus metadata.json."""

    def __init__(
        self,
        dimension: int,
        index_path: str,
        metadata_path: str,
        similarity_threshold: float = 0.5,
        index_type: str = "FlatL2",
    ):
        """Load the index from disk, or create an empty one when none exists.

        Only "FlatL2" is built; ``index_type`` is a label reported in the stats.

        Raises:
            VectorStoreConnectionError: If an existing index cannot be loaded.
                The store never starts empty over an unreadable index: the next
                persist would overwrite it.
        """
        self.dimension = dimension
        self.index_path = Path(index_path)
        self.metadata_path = Path(metadata_path)
        self.similarity_threshold = similarity_threshold
        self.index_type = index_type
        self._lock = threading.RLock()

        # faiss ships no type stubs: the index object is untyped
        self.index: Any = None
        self.metadata: list[dict[str, Any]] = []
        self.document_to_chunks: dict[str, list[int]] = {}
        self._stats: dict[str, Any] = {
            "total_vectors": 0,
            "total_documents": 0,
            "last_updated": None,
        }

        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        if self.index_path.exists() and self.metadata_path.exists():
            self.load()
        else:
            self._create_new_index()

        logger.info(
            f"FAISS vector store initialized: {self.index_type}, "
            f"dim={dimension}, threshold={similarity_threshold}"
        )

    def _create_new_index(self) -> None:
        with self._lock:
            self.index = faiss.IndexFlatL2(self.dimension)
            self.metadata = []
            self.document_to_chunks = {}
            self._update_stats()
            logger.info(f"Created new {self.index_type} index with dimension {self.dimension}")

    def upsert(self, chunks: list[Chunk]) -> bool:
        """Add the chunks, replacing every existing chunk of their documents.

        Raises:
            VectorStoreOperationError: If an embedding has the wrong dimension
        """
        if not chunks:
            logger.warning("No chunks provided for upsert")
            return True

        start_time = time.time()
        with self._lock:
            for chunk in chunks:
                if chunk.embedding is None or len(chunk.embedding) != self.dimension:
                    raise VectorStoreOperationError(
                        f"Invalid embedding dimension: expected {self.dimension}, "
                        f"got {len(chunk.embedding) if chunk.embedding is not None else 'None'}"
                    )

            for document_id in {chunk.document_id for chunk in chunks}:
                if document_id in self.document_to_chunks:
                    self.delete(document_id)

            start_idx = self.index.ntotal
            self.index.add(np.array([chunk.embedding for chunk in chunks], dtype=np.float32))
            indexed_at = datetime.utcnow().isoformat()
            for offset, chunk in enumerate(chunks):
                chunk_id = start_idx + offset
                self.metadata.append(
                    {
                        "chunk_id": chunk_id,
                        "document_id": chunk.document_id,
                        "text": chunk.text,
                        "source": chunk.source,
                        "chunk_index": chunk.chunk_index,
                        "total_chunks": chunk.total_chunks,
                        "preserve": chunk.preserve,
                        "indexed_at": indexed_at,
                        "metadata": chunk.metadata,
                    }
                )
                self.document_to_chunks.setdefault(chunk.document_id, []).append(chunk_id)
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

    def query(
        self,
        vector: np.ndarray,
        top_k: int = 5,
        filter_dict: dict[str, Any] | None = None,
        similarity_floor: float | None = None,
    ) -> list[SearchResult]:
        """Most similar active chunks, best first.

        ``similarity_floor`` replaces the store's similarity_threshold; hybrid
        retrieval passes 0.0 to get the raw candidate pool for RRF.

        Raises:
            VectorStoreOperationError: If the vector has the wrong dimension
        """
        if self.index is None or self.index.ntotal == 0:
            logger.warning("Vector store is empty")
            return []

        start_time = time.time()
        threshold = self.similarity_threshold if similarity_floor is None else similarity_floor
        with self._lock:
            query_vector = np.array(vector, dtype=np.float32)
            if len(query_vector) != self.dimension:
                raise VectorStoreOperationError(
                    f"Query vector dimension mismatch: expected {self.dimension}, "
                    f"got {len(query_vector)}"
                )

            # Over-fetch so that filtered and deleted chunks still leave top_k results
            k = min(top_k * 2, self.index.ntotal)
            distances, indices = self.index.search(query_vector.reshape(1, -1), k)

            results = []
            for distance, idx in zip(distances[0], indices[0], strict=True):
                if idx < 0 or idx >= len(self.metadata):
                    continue
                # Normalized vectors: squared L2 distance maps to cosine similarity
                similarity = round(max(0.0, 1.0 - float(distance) / 2), _SIMILARITY_DECIMALS)
                meta = self.metadata[idx]
                if similarity < threshold or meta.get("deleted", False):
                    continue
                if filter_dict and not self._matches_filter(meta, filter_dict):
                    continue
                results.append(
                    SearchResult(
                        chunk_id=meta["chunk_id"],
                        document_id=meta["document_id"],
                        text=meta["text"],
                        source=meta["source"],
                        similarity_score=similarity,
                        chunk_index=meta["chunk_index"],
                        total_chunks=meta["total_chunks"],
                        metadata=meta.get("metadata", {}),
                    )
                )

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

    @staticmethod
    def _matches_filter(metadata: dict[str, Any], filter_dict: dict[str, Any]) -> bool:
        return all(key in metadata and metadata[key] == value for key, value in filter_dict.items())

    def delete(self, document_id: str) -> bool:
        """Mark every chunk of a document as deleted; False if it has none.

        The index is compacted (and persisted) once more than a quarter of its
        chunks are deleted.
        """
        with self._lock:
            if document_id not in self.document_to_chunks:
                logger.warning(f"Document {document_id} not found for deletion")
                return False

            deleted_at = datetime.utcnow().isoformat()
            chunk_ids = self.document_to_chunks.pop(document_id)
            for chunk_id in chunk_ids:
                self.metadata[chunk_id]["deleted"] = True
                self.metadata[chunk_id]["deleted_at"] = deleted_at
            self._update_stats()
            logger.info(
                f"Marked {len(chunk_ids)} chunks as deleted for document: {document_id}",
                extra={
                    "extra_fields": {
                        "document_id": document_id,
                        "deleted_count": len(chunk_ids),
                        "type": "vector_delete",
                    }
                },
            )

            if self._deleted_ratio() > _OPTIMIZE_DELETED_RATIO:
                logger.info("Triggering automatic optimization after deletion")
                self.optimize()
            return True

    def _deleted_count(self) -> int:
        return sum(1 for meta in self.metadata if meta.get("deleted", False))

    def _deleted_ratio(self) -> float:
        return self._deleted_count() / len(self.metadata) if self.metadata else 0.0

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            deleted_vectors = self._deleted_count()
            return {
                "total_vectors": self.index.ntotal if self.index else 0,
                "active_vectors": len(self.metadata) - deleted_vectors,
                "deleted_vectors": deleted_vectors,
                "total_documents": len(self.document_to_chunks),
                "index_type": self.index_type,
                "dimension": self.dimension,
                "similarity_threshold": self.similarity_threshold,
                "last_updated": self._stats.get("last_updated"),
                "memory_usage_mb": self._estimate_memory_usage(),
            }

    def get_corpus_version(self) -> str:
        """Token scoping cache entries: changes on every upsert and delete."""
        with self._lock:
            return self._stats.get("last_updated") or "none"

    def snapshot_active_chunks(self) -> list[dict[str, Any]]:
        """Copy of the active chunk metadata, taken under the lock.

        The BM25 store rebuilds itself from this snapshot, possibly in another
        thread, without racing a concurrent upsert or delete.
        """
        with self._lock:
            return [dict(m) for m in self.metadata if not m.get("deleted", False)]

    def _estimate_memory_usage(self) -> float:
        """Rough memory estimate in MB: float32 vectors plus ~1KB of metadata each."""
        if not self.index:
            return 0.0
        vector_memory = self.index.ntotal * self.dimension * 4
        metadata_memory = len(self.metadata) * 1000
        return (vector_memory + metadata_memory) / (1024 * 1024)

    def health_check(self) -> bool:
        """Run a probe search; any failure is reported as unhealthy."""
        try:
            with self._lock:
                if self.index is None:
                    return False
                if self.index.ntotal > 0:
                    probe = np.random.rand(1, self.dimension).astype(np.float32)
                    self.index.search(probe, 1)
                return True
        except Exception as e:  # noqa: BLE001 - health probe: any failure is reported as unhealthy
            logger.error(f"Vector store health check failed: {e}")
            return False

    @staticmethod
    def _atomic_write(target_path: Path, writer: Callable[[str], object]) -> None:
        """Write a file through a temp file of the same directory, fsync, then rename.

        No reader ever observes a partially written file, and the directory is
        fsynced so a power loss cannot roll the rename back.
        """
        target_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(target_path.parent), suffix=".tmp")
        os.close(fd)
        try:
            writer(tmp_path)
            read_fd = os.open(tmp_path, os.O_RDONLY)
            try:
                os.fsync(read_fd)
            finally:
                os.close(read_fd)
            os.replace(tmp_path, str(target_path))
            dir_fd = os.open(str(target_path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except BaseException:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def persist(self) -> bool:
        """Write the index, then the metadata, each atomically and under the lock.

        A crash between the two writes only leaves the index ahead of the
        metadata (orphan vectors), never metadata pointing beyond the index.

        Raises:
            VectorStoreConnectionError: If a file cannot be written
        """
        with self._lock:
            start_time = time.time()
            payload = MetadataPayload(
                schema_version=1,
                metadata=self.metadata,
                document_to_chunks=self.document_to_chunks,
                stats=self._stats,
                saved_at=datetime.utcnow().isoformat(),
            )
            try:
                self._atomic_write(self.index_path, lambda p: faiss.write_index(self.index, p))
                self._atomic_write(
                    self.metadata_path,
                    lambda p: Path(p).write_bytes(payload.model_dump_json().encode("utf-8")),
                )
            except _PERSISTENCE_ERRORS as e:
                raise VectorStoreConnectionError(f"Failed to persist vector store: {e}") from e

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

    def load(self) -> bool:
        """Read the index and the validated metadata from disk.

        Raises:
            VectorStoreConnectionError: If a file is missing, unreadable or invalid
        """
        with self._lock:
            start_time = time.time()
            try:
                index = faiss.read_index(str(self.index_path))
                with open(self.metadata_path, encoding="utf-8") as f:
                    payload = MetadataPayload.model_validate(json.load(f))
            except _PERSISTENCE_ERRORS as e:
                raise VectorStoreConnectionError(f"Failed to load vector store: {e}") from e

            self.index = index
            self.metadata = payload.metadata
            self.document_to_chunks = payload.document_to_chunks
            self._stats = payload.stats
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

    def _update_stats(self) -> None:
        self._stats.update(
            {
                "total_vectors": self.index.ntotal if self.index else 0,
                "total_documents": len(self.document_to_chunks),
                "last_updated": datetime.utcnow().isoformat(),
            }
        )

    def clean_orphans(
        self, existing_document_ids: set[str], create_backup: bool = True
    ) -> dict[str, Any]:
        """Delete the chunks of documents absent from ``existing_document_ids`` and persist."""
        with self._lock:
            start_time = time.time()
            initial_stats = self._chunk_stats()
            logger.info(f"Starting orphan cleanup - Initial state: {initial_stats}")
            if create_backup:
                self._create_backup(datetime.utcnow().strftime("%Y%m%d_%H%M%S"))

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
                    "final_stats": initial_stats,
                }

            logger.info(
                f"Found {len(orphaned_chunks)} orphaned chunks from {len(orphaned_docs)} documents"
            )
            cleaned_count = self._mark_orphans_deleted(orphaned_chunks, orphaned_docs)
            optimization_triggered = self._deleted_ratio() > _OPTIMIZE_DELETED_RATIO
            if optimization_triggered:
                self.optimize()
            else:
                self.persist()

            duration_ms = (time.time() - start_time) * 1000
            result = {
                "orphaned_chunks_found": len(orphaned_chunks),
                "orphaned_documents": len(orphaned_docs),
                "cleaned_chunks": cleaned_count,
                "optimization_triggered": optimization_triggered,
                "duration_ms": duration_ms,
                "initial_stats": initial_stats,
                "final_stats": self._chunk_stats(),
            }
            logger.info(
                f"Orphan cleanup completed in {duration_ms:.1f}ms: "
                f"cleaned {cleaned_count} chunks from {len(orphaned_docs)} orphaned documents",
                extra={"extra_fields": {"cleanup_result": result, "type": "orphan_cleanup"}},
            )
            return result

    def _chunk_stats(self) -> dict[str, int]:
        deleted_chunks = self._deleted_count()
        return {
            "total_chunks": len(self.metadata),
            "active_chunks": len(self.metadata) - deleted_chunks,
            "deleted_chunks": deleted_chunks,
            "total_documents": len(self.document_to_chunks),
        }

    def _find_orphans(
        self, existing_document_ids: set[str]
    ) -> tuple[list[dict[str, Any]], set[str]]:
        orphaned_chunks = [
            meta
            for meta in self.metadata
            if meta.get("document_id")
            and meta["document_id"] not in existing_document_ids
            and not meta.get("deleted", False)
        ]
        return orphaned_chunks, {meta["document_id"] for meta in orphaned_chunks}

    def _mark_orphans_deleted(
        self, orphaned_chunks: list[dict[str, Any]], orphaned_docs: set[str]
    ) -> int:
        deleted_at = datetime.utcnow().isoformat()
        for meta in orphaned_chunks:
            meta["deleted"] = True
            meta["deleted_at"] = deleted_at
            meta["deletion_reason"] = "orphan_cleanup"
        for doc_id in orphaned_docs:
            self.document_to_chunks.pop(doc_id, None)
        return len(orphaned_chunks)

    def _create_backup(self, timestamp: str) -> None:
        """Copy the index and metadata files aside, keeping the newest backups only."""
        if self.index_path.exists():
            shutil.copy2(self.index_path, self.index_path.with_suffix(f".backup_{timestamp}"))
        if self.metadata_path.exists():
            shutil.copy2(self.metadata_path, self.metadata_path.with_suffix(f".backup_{timestamp}"))
        self._rotate_backups()
        logger.info(f"Backup created: {timestamp}")

    def _rotate_backups(self) -> None:
        backup_dir = self.index_path.parent
        removed = 0
        for pattern in ("index*.backup_*", "metadata*.backup_*"):
            backups = sorted(
                backup_dir.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True
            )
            for old_backup in backups[settings.faiss_max_backups :]:
                old_backup.unlink()
                removed += 1
        if removed:
            logger.info(
                f"Backup rotation: removed {removed} old backup files "
                f"(max_backups={settings.faiss_max_backups})"
            )

    def optimize(self) -> None:
        """Rebuild a compact index without the deleted chunks, then persist it."""
        with self._lock:
            deleted_count = self._deleted_count()
            if not self.index or self.index.ntotal == 0 or deleted_count == 0:
                logger.info("No deleted vectors to remove - optimization not needed")
                return

            logger.info(
                f"Starting index optimization - removing {deleted_count} deleted vectors "
                f"out of {len(self.metadata)}"
            )
            active_entries = [
                meta
                for position, meta in enumerate(self.metadata)
                if not meta.get("deleted", False) and position < self.index.ntotal
            ]
            new_index = faiss.IndexFlatL2(self.dimension)
            # Map each surviving chunk's old id (still referenced by
            # document_to_chunks) to its new position; the old id must be read
            # before meta["chunk_id"] is overwritten.
            id_remap = {}
            if active_entries:
                vectors = [self.index.reconstruct(meta["chunk_id"]) for meta in active_entries]
                new_index.add(np.array(vectors, dtype=np.float32))
                for position, meta in enumerate(active_entries):
                    id_remap[meta["chunk_id"]] = position
                    meta["chunk_id"] = position

            old_total = self.index.ntotal
            self.index = new_index
            self.metadata = active_entries
            # Documents left without any surviving chunk are dropped
            self.document_to_chunks = {
                doc_id: remapped
                for doc_id, old_ids in self.document_to_chunks.items()
                if (remapped := [id_remap[cid] for cid in old_ids if cid in id_remap])
            }
            self.persist()
            logger.info(
                f"Index optimization completed: {old_total} → {self.index.ntotal} vectors "
                f"({deleted_count} deleted vectors removed)"
            )

    def rebuild_vector_store(
        self,
        existing_document_ids: set[str],
        force_rebuild: bool = False,
        cleanup_orphans: bool = True,
    ) -> dict[str, Any]:
        """Optionally delete orphan chunks, then compact the index.

        Args:
            existing_document_ids: Ids of the documents still in the database
            force_rebuild: Compact even when no chunk is deleted
            cleanup_orphans: Delete the chunks of unknown documents first
        """
        with self._lock:
            start_time = time.time()
            logger.info(
                f"Starting vector store rebuild (force={force_rebuild}, "
                f"cleanup_orphans={cleanup_orphans})"
            )
            initial_stats = self.get_stats()
            cleanup_result = (
                self.clean_orphans(existing_document_ids, create_backup=True)
                if cleanup_orphans
                else None
            )

            deleted_count = self._deleted_count()
            if not force_rebuild and deleted_count == 0:
                logger.info("Rebuild not needed - no deleted chunks found")
                return {
                    "rebuild_performed": False,
                    "reason": "no_deleted_chunks",
                    "cleanup_result": cleanup_result,
                    "duration_ms": (time.time() - start_time) * 1000,
                    "initial_stats": initial_stats,
                    "final_stats": self.get_stats(),
                }

            self.optimize()
            duration_ms = (time.time() - start_time) * 1000
            result = {
                "rebuild_performed": True,
                "cleanup_result": cleanup_result,
                "deleted_chunks_removed": deleted_count,
                "duration_ms": duration_ms,
                "initial_stats": initial_stats,
                "final_stats": self.get_stats(),
            }
            logger.info(
                f"Vector store rebuild completed in {duration_ms:.1f}ms: "
                f"removed {deleted_count} deleted chunks",
                extra={"extra_fields": {"rebuild_result": result, "type": "vector_rebuild"}},
            )
            return result

    def get_document_chunks(self, document_id: str) -> list[Chunk]:
        """Active chunks of a document with their vectors, in document order."""
        with self._lock:
            chunk_ids = self.document_to_chunks.get(document_id, [])
            chunks = [
                Chunk(
                    text=meta.get("text", ""),
                    embedding=self.index.reconstruct(chunk_id),
                    document_id=document_id,
                    chunk_index=meta.get("chunk_index", 0),
                    total_chunks=len(chunk_ids),
                    source=meta.get("source", ""),
                    metadata=meta.get("metadata", {}),
                    preserve=meta.get("preserve", False),
                )
                for chunk_id in chunk_ids
                if not (meta := self.metadata[chunk_id]).get("deleted", False)
            ]
        chunks.sort(key=lambda chunk: chunk.chunk_index)
        return chunks
