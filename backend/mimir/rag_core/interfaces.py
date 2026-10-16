"""
Abstract interfaces for vector storage and retrieval
Provides base classes for implementing different vector store providers
"""

from abc import ABC, abstractmethod
from typing import Any, Protocol
from dataclasses import dataclass
import numpy as np

from mimir.shared.errors import RetrievalError


@dataclass
class Chunk:
    """Represents a text chunk with embedding"""

    text: str
    embedding: np.ndarray
    document_id: str
    chunk_index: int
    total_chunks: int
    source: str
    metadata: dict[str, Any]
    preserve: bool = False


@dataclass
class SearchResult:
    """Result from vector similarity search"""

    chunk_id: int
    document_id: str
    text: str
    source: str
    similarity_score: float
    chunk_index: int
    total_chunks: int
    metadata: dict[str, Any]


class VectorStoreException(RetrievalError):
    """Base exception for vector store operations"""

    pass


class VectorStoreConnectionError(VectorStoreException):
    """Vector store connection/persistence errors"""

    pass


class VectorStoreOperationError(VectorStoreException):
    """Vector store operation errors"""

    pass


class AbstractVectorStore(ABC):
    """
    Abstract base class for vector storage systems
    Provides interface for storing and querying vector embeddings
    """

    @abstractmethod
    def upsert(self, chunks: list[Chunk]) -> bool:
        """Insert or update chunks in the vector store

        Raises:
            VectorStoreOperationError: If upsert operation fails
        """
        pass

    @abstractmethod
    def query(
        self,
        vector: np.ndarray,
        top_k: int = 5,
        filter_dict: dict[str, Any] | None = None,
        similarity_floor: float | None = None,
    ) -> list[SearchResult]:
        """Search for similar vectors, ordered by similarity.

        ``similarity_floor`` overrides the store's own minimum similarity (0.0
        returns the raw ranking used by hybrid fusion).

        Raises:
            VectorStoreOperationError: If query operation fails
        """
        pass

    @abstractmethod
    def delete(self, document_id: str) -> bool:
        """Delete all chunks for a document

        Raises:
            VectorStoreOperationError: If delete operation fails
        """
        pass

    @abstractmethod
    def get_stats(self) -> dict[str, Any]:
        """
        Get vector store statistics

        Returns:
            Dictionary with store statistics (vector count, size, etc.)
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """Check if vector store is healthy and accessible"""
        pass

    @abstractmethod
    def persist(self) -> bool:
        """Persist current state to disk

        Raises:
            VectorStoreConnectionError: If persistence fails
        """
        pass

    @abstractmethod
    def load(self) -> bool:
        """Load state from disk

        Raises:
            VectorStoreConnectionError: If loading fails
        """
        pass

    @abstractmethod
    def get_corpus_version(self) -> str:
        """
        Token that changes on every corpus mutation (upsert, delete)

        Returns:
            Version string used to scope cache entries to a corpus state
        """
        pass

    @abstractmethod
    def snapshot_active_chunks(self) -> list[dict[str, Any]]:
        """
        Copy of the metadata of every non-deleted chunk

        Returns:
            One dict per active chunk (chunk_id, document_id, text, source,
            chunk_index, total_chunks, metadata), safe to read while the store
            keeps changing
        """
        pass


class LexicalIndex(Protocol):
    """Lexical index rebuilt from the vector store's active chunks.

    Not an AbstractVectorStore: it is queried with raw text and rebuilt as a
    whole rather than upserted chunk by chunk.
    """

    def rebuild(self, active_chunks: list[dict[str, Any]]) -> None:
        """Replace the whole index with the given chunks (keys 'text' and 'chunk_id')."""
        ...

    def query(self, question: str, top_k: int = 50) -> list[tuple[int, float]]:
        """Return (chunk_id, score) pairs by descending relevance."""
        ...

    def load(self) -> bool:
        """Load the persisted index; False when none exists on disk."""
        ...
