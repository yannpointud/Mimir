"""
Abstract interfaces for LLM services
Provides base classes for implementing different LLM providers
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from mimir.shared.errors import LLMError


@dataclass
class GenerationResponse:
    """Response from LLM generation"""

    content: str
    model: str
    usage_tokens: int
    finish_reason: str
    # Split token counts, needed to bill input/output separately (cost accounting).
    # Defaulted so existing callers/tests constructing GenerationResponse without
    # these fields keep working.
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class EmbeddingResponse:
    """Response from embedding generation"""

    embeddings: list[list[float]]
    model: str
    usage_tokens: int
    # Split token counts for cost accounting. Embeddings have no completion
    # tokens, so completion_tokens stays 0 for this response type.
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMException(LLMError):
    """Base exception for LLM operations"""

    pass


class LLMAPIError(LLMException):
    """API-related errors (network, authentication, etc.)"""

    pass


class LLMRateLimitError(LLMException):
    """Rate limiting errors"""

    pass


class LLMInvalidRequestError(LLMException):
    """Invalid request errors (malformed prompt, etc.)"""

    pass


class AbstractLLMService(ABC):
    """
    Abstract base class for LLM services
    Provides interface for text generation and embedding creation
    """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.1,
        **kwargs,
    ) -> GenerationResponse:
        """Generate text response from prompt

        Raises:
            LLMAPIError: API communication issues
            LLMRateLimitError: Rate limiting exceeded
            LLMInvalidRequestError: Invalid request parameters
        """
        pass

    @abstractmethod
    def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.1,
        session_id: str | None = None,
        rag_debug: Any = None,
        usage_out: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream the generated text chunk by chunk.

        ``usage_out``, when given, is filled with the real token usage
        (prompt_tokens, completion_tokens, total_tokens) once the provider
        reports it; it is left empty otherwise.

        Raises:
            LLMAPIError: API communication issues
        """

    @abstractmethod
    async def embed(
        self, texts: list[str], session_id: str | None = None, rag_debug: Any = None
    ) -> EmbeddingResponse:
        """Generate embeddings for list of texts

        Raises:
            LLMAPIError: API communication issues
            LLMRateLimitError: Rate limiting exceeded
            LLMInvalidRequestError: Invalid request parameters
        """
        pass

    async def close(self) -> None:
        """Release network resources held by the service (none by default)."""
        return None

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if LLM service is available"""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier"""
        pass

    @property
    @abstractmethod
    def embedding_dimension(self) -> int:
        """Return the embedding vector dimension"""
        pass
