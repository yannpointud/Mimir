"""
Abstract interfaces for LLM services
Provides base classes for implementing different LLM providers
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

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

class LLMException(Exception):
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
    async def generate(self,
                      prompt: str,
                      system_prompt: str | None = None,
                      max_tokens: int | None = None,
                      temperature: float = 0.1,
                      **kwargs) -> GenerationResponse:
        """
        Generate text response from prompt

        Args:
            prompt: User input prompt
            system_prompt: Optional system instruction
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0 to 1.0)
            **kwargs: Additional model-specific parameters

        Returns:
            GenerationResponse with generated text and metadata

        Raises:
            LLMAPIError: API communication issues
            LLMRateLimitError: Rate limiting exceeded
            LLMInvalidRequestError: Invalid request parameters
        """
        pass

    @abstractmethod
    async def embed(self, texts: list[str]) -> EmbeddingResponse:
        """
        Generate embeddings for list of texts

        Args:
            texts: List of texts to embed

        Returns:
            EmbeddingResponse with embeddings and metadata

        Raises:
            LLMAPIError: API communication issues
            LLMRateLimitError: Rate limiting exceeded
            LLMInvalidRequestError: Invalid request parameters
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if LLM service is available

        Returns:
            True if service is healthy, False otherwise
        """
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