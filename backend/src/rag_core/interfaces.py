"""
Abstract interfaces for vector storage and retrieval
Provides base classes for implementing different vector store providers
"""

from abc import ABC, abstractmethod
from typing import Any
from dataclasses import dataclass
import numpy as np


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


class VectorStoreException(Exception):
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
        """
        Insert or update chunks in the vector store

        Args:
            chunks: List of chunks with embeddings to store

        Returns:
            True if successful, False otherwise

        Raises:
            VectorStoreOperationError: If upsert operation fails
        """
        pass

    @abstractmethod
    def query(
        self, vector: np.ndarray, top_k: int = 5, filter_dict: dict[str, Any] | None = None
    ) -> list[SearchResult]:
        """
        Search for similar vectors

        Args:
            vector: Query embedding vector
            top_k: Maximum number of results to return
            filter_dict: Optional metadata filters

        Returns:
            List of search results ordered by similarity

        Raises:
            VectorStoreOperationError: If query operation fails
        """
        pass

    @abstractmethod
    def delete(self, document_id: str) -> bool:
        """
        Delete all chunks for a document

        Args:
            document_id: Document identifier

        Returns:
            True if successful, False otherwise

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
        """
        Check if vector store is healthy and accessible

        Returns:
            True if healthy, False otherwise
        """
        pass

    @abstractmethod
    def persist(self) -> bool:
        """
        Persist current state to disk

        Returns:
            True if successful, False otherwise

        Raises:
            VectorStoreConnectionError: If persistence fails
        """
        pass

    @abstractmethod
    def load(self) -> bool:
        """
        Load state from disk

        Returns:
            True if successful, False otherwise

        Raises:
            VectorStoreConnectionError: If loading fails
        """
        pass
