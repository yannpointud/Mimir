"""
BM25 lexical store implementation.

Second retrieval index living beside FaissVectorStore: a lexical BM25 index that
recovers exact terms (identifiers, acronyms) the dense embedding path tends to
miss. It is a *derived* artifact -- reconstructed in full from the source of
truth (FaissVectorStore's active chunks) at every mutation, exactly like
FaissVectorStore.optimize() rebuilds from non-deleted metadata.

Design constraints (locked):
- Persistence uses the native bm25s save/load API (JSON + .npy, allow_pickle=False):
  NO arbitrary-object deserialization, consistent with the removal of pickle
  from FaissVectorStore's metadata persistence.
- Atomic writes: bm25s.save() writes a directory; we save into a temp directory on
  the same filesystem then os.replace() it onto the target (atomic directory
  rename), mirroring the crash-safety intent of FaissVectorStore._atomic_write.
- Thread-safe/reentrant via an RLock, like FaissVectorStore.
- Does NOT implement AbstractVectorStore: the API is rebuild(active_chunks) /
  query(str) rather than upsert(chunks) / query(np.ndarray).
"""

import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import bm25s

from ..interfaces import (
    VectorStoreException,  # noqa: F401
    VectorStoreConnectionError,
    VectorStoreOperationError,
)
from ..tokenizer_fr import light_french_tokenizer
from ...monitoring.logger import setup_logger

logger = setup_logger(__name__)


class Bm25LexicalStore:
    """BM25 lexical index rebuilt from the FAISS source of truth.

    The same light French tokenizer is applied at index time and query time
    (otherwise tokens would never match). The index position -> real chunk_id
    mapping is kept in ``_chunk_ids`` and persisted through the native bm25s
    corpus (JSONL), so a save/load round-trip restores the mapping too.
    """

    def __init__(self, index_path: str):
        """Initialize the lexical store.

        Args:
            index_path: Directory path where the bm25s index is persisted.
        """
        self.index_path = Path(index_path)
        self._retriever: Optional[bm25s.BM25] = None
        # Corpus index position i -> real chunk_id (from FaissVectorStore metadata).
        self._chunk_ids: List[int] = []
        # True once rebuilt or loaded (distinguishes "never built" from
        # "built empty" so query() can raise only in the former case).
        self._built: bool = False

        # Thread safety (reentrant, like FaissVectorStore._lock).
        self._lock = threading.RLock()

    def rebuild(self, active_chunks: List[Dict[str, Any]]) -> None:
        """Rebuild the whole index from the currently active chunks.

        The corpus is expected to be modest in size (out of scope for HNSW /
        >1M vectors), so a full rebuild on every upsert/delete stays cheap.

        Args:
            active_chunks: List of dicts with keys 'text' and 'chunk_id', taken
                from FaissVectorStore's non-deleted metadata (source of truth).

        Raises:
            VectorStoreOperationError: If the index build/persist fails.
        """
        with self._lock:
            try:
                texts = [c["text"] for c in active_chunks]
                self._chunk_ids = [c["chunk_id"] for c in active_chunks]

                if not texts:
                    # Empty corpus: nothing to index, keep an in-memory empty
                    # store (query() returns []). Persist an empty marker so a
                    # later load() is consistent.
                    self._retriever = None
                    self._built = True
                    self._persist_empty()
                    logger.info("BM25 lexical index rebuilt with an empty corpus")
                    return

                corpus_tokens = light_french_tokenizer(texts)
                retriever = bm25s.BM25()
                retriever.index(corpus_tokens, show_progress=False)
                self._retriever = retriever
                self._built = True

                # Persist atomically (index dir + chunk_id corpus).
                self._persist(retriever)

                logger.info(
                    "BM25 lexical index rebuilt",
                    extra={"extra_fields": {"chunks": len(self._chunk_ids)}},
                )
            except Exception as e:
                error_msg = f"Failed to rebuild BM25 lexical index: {str(e)}"
                logger.error(error_msg)
                raise VectorStoreOperationError(error_msg)

    def query(self, question: str, top_k: int = 50) -> List[Tuple[int, float]]:
        """Query the lexical index for the most relevant chunks.

        Args:
            question: Raw query string (tokenized with the same tokenizer used
                at index time).
            top_k: Maximum number of results (clamped to the corpus size).

        Returns:
            List of (chunk_id, score) tuples sorted by descending relevance.

        Raises:
            VectorStoreOperationError: If the store was never built/loaded.
        """
        with self._lock:
            if not self._built:
                raise VectorStoreOperationError(
                    "BM25 lexical index queried before rebuild()/load()"
                )
            try:
                # Empty corpus or a query that tokenizes to nothing -> no hits.
                if not self._chunk_ids or self._retriever is None:
                    return []

                query_tokens = light_french_tokenizer([question])
                if not query_tokens[0]:
                    return []

                k = min(top_k, len(self._chunk_ids))
                if k <= 0:
                    return []

                results, scores = self._retriever.retrieve(
                    query_tokens, k=k, show_progress=False
                )
                # bm25s.retrieve returns integer corpus positions when no corpus
                # is attached (fresh rebuild) but the corpus objects themselves
                # when one was loaded (load_corpus=True). Resolve both shapes to
                # the real chunk_id.
                return [
                    (self._resolve_chunk_id(doc), float(score))
                    for doc, score in zip(results[0], scores[0])
                ]
            except Exception as e:
                error_msg = f"Failed to query BM25 lexical index: {str(e)}"
                logger.error(error_msg)
                raise VectorStoreOperationError(error_msg)

    def load(self) -> bool:
        """Load the persisted index (and chunk_id mapping) from disk.

        Returns:
            True if an index was loaded, False if none exists on disk.

        Raises:
            VectorStoreConnectionError: If a present index fails to load.
        """
        with self._lock:
            empty_marker = self.index_path / "empty.marker"
            params_file = self.index_path / "params.index.json"

            if not self.index_path.exists():
                return False

            # Empty index that was persisted with an empty corpus.
            if empty_marker.exists() and not params_file.exists():
                self._retriever = None
                self._chunk_ids = []
                self._built = True
                return True

            if not params_file.exists():
                return False

            try:
                retriever = bm25s.BM25.load(
                    str(self.index_path), load_corpus=True, allow_pickle=False
                )
                self._retriever = retriever
                self._chunk_ids = [
                    int(item["chunk_id"]) for item in (retriever.corpus or [])
                ]
                self._built = True
                logger.info(
                    "BM25 lexical index loaded",
                    extra={"extra_fields": {"chunks": len(self._chunk_ids)}},
                )
                return True
            except Exception as e:
                error_msg = f"Failed to load BM25 lexical index: {str(e)}"
                logger.error(error_msg)
                raise VectorStoreConnectionError(error_msg)

    def _resolve_chunk_id(self, doc: Any) -> int:
        """Map a bm25s retrieval result to a real chunk_id.

        A fresh (just-rebuilt) retriever returns integer corpus positions; a
        loaded retriever (load_corpus=True) returns the corpus objects
        ({"chunk_id": ...}) directly. Handle both.
        """
        if isinstance(doc, dict):
            return int(doc["chunk_id"])
        return self._chunk_ids[int(doc)]

    def _swap_dir_into_place(self, tmp_dir: str) -> None:
        """Move a freshly-built temp directory onto the target, crash-safely.

        A plain rmtree(target)+os.replace(tmp) leaves a long window with NO index
        on disk if the process dies mid-rmtree. Instead move the old
        directory aside first, then atomically move the new one in, then delete
        the backup. The only window with a missing target is the microsecond
        between the two os.replace() calls; a crash there is further covered by
        RagService's per-query dense-only fallback. On failure the old index is
        rolled back into place.
        """
        target = str(self.index_path)
        backup = target + ".old"
        # Clear any stale backup from a previously-crashed swap.
        if os.path.exists(backup):
            shutil.rmtree(backup, ignore_errors=True)
        had_old = self.index_path.exists()
        if had_old:
            os.replace(target, backup)  # atomic: target aside
        try:
            os.replace(tmp_dir, target)  # atomic: new in place
        except Exception:
            if had_old:
                os.replace(backup, target)  # roll back
            raise
        if had_old:
            shutil.rmtree(backup, ignore_errors=True)

    def _persist(self, retriever: bm25s.BM25) -> None:
        """Persist the index atomically via a temp dir + crash-safe swap.

        bm25s.save() writes a whole directory; we write it into a sibling temp
        directory on the same filesystem, then swap it onto the target (see
        _swap_dir_into_place). The chunk_id mapping rides along as the native
        bm25s corpus (JSONL), keeping allow_pickle=False (no arbitrary
        deserialization).
        """
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = tempfile.mkdtemp(
            dir=str(self.index_path.parent), suffix=".bm25.tmp"
        )
        try:
            corpus = [{"chunk_id": cid} for cid in self._chunk_ids]
            retriever.save(
                tmp_dir,
                corpus=corpus,
                allow_pickle=False,
                show_progress=False,
            )
            self._swap_dir_into_place(tmp_dir)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def _persist_empty(self) -> None:
        """Persist an empty-corpus marker directory (no bm25s index)."""
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = tempfile.mkdtemp(
            dir=str(self.index_path.parent), suffix=".bm25.tmp"
        )
        try:
            (Path(tmp_dir) / "empty.marker").write_text("empty\n", encoding="utf-8")
            self._swap_dir_into_place(tmp_dir)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
