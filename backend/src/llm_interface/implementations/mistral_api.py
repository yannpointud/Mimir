"""
Mistral AI API Implementation
Provides integration with Mistral AI's API for text generation and embeddings
"""

import asyncio
import aiohttp
import logging
import time
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from ..interfaces import (
    AbstractLLMService,
    GenerationResponse,
    EmbeddingResponse,
    LLMAPIError,
    LLMRateLimitError,
    LLMInvalidRequestError
)
from ...monitoring.logger import setup_logger

logger = setup_logger(__name__)

class MistralAPIService(AbstractLLMService):
    """
    Mistral AI API implementation with retry logic and error handling
    """

    def __init__(self,
                 api_key: str,
                 model: str = "mistral-small-latest",
                 embedding_model: str = "mistral-embed",
                 base_url: str = "https://api.mistral.ai/v1",
                 max_retries: int = 3,
                 retry_delay: float = 1.0):
        """
        Initialize Mistral API service

        Args:
            api_key: Mistral API key
            model: Model for text generation
            embedding_model: Model for embeddings
            base_url: Mistral API base URL
            max_retries: Maximum retry attempts
            retry_delay: Initial delay between retries (exponential backoff)
        """
        self.api_key = api_key
        self._model = model
        self._embedding_model = embedding_model
        self.base_url = base_url
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Session will be created when needed
        self._session: Optional[aiohttp.ClientSession] = None

        logger.info(f"Mistral API service initialized with model: {model}")

    def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60, connect=10)
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                timeout=timeout
            )
        return self._session

    async def _make_request(self,
                           endpoint: str,
                           payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make HTTP request with retry logic and comprehensive error handling

        Args:
            endpoint: API endpoint
            payload: Request payload

        Returns:
            Response JSON

        Raises:
            LLMAPIError: API communication issues
            LLMRateLimitError: Rate limiting
            LLMInvalidRequestError: Invalid request
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                session = self._get_session()

                logger.debug(f"Making request to {url}, attempt {attempt + 1}")

                logger.debug(f"Sending request to Mistral API ({payload.get('model')}) at {time.time_ns()}")
                async with session.post(url, json=payload) as response:
                    response_text = await response.text()

                    # Handle different HTTP status codes
                    if response.status == 200:
                        data = await response.json()
                        logger.debug(f"Request successful: {url}")
                        return data

                    elif response.status == 429:
                        # Rate limiting
                        retry_after = int(response.headers.get('Retry-After', 60))
                        error_msg = f"Rate limit exceeded. Retry after {retry_after}s"
                        logger.warning(error_msg)

                        if attempt < self.max_retries:
                            await asyncio.sleep(min(retry_after, 60))  # Cap at 60s
                            continue
                        else:
                            raise LLMRateLimitError(error_msg)

                    elif response.status == 400:
                        # Bad request
                        error_msg = f"Invalid request: {response_text}"
                        logger.error(error_msg)
                        raise LLMInvalidRequestError(error_msg)

                    elif response.status == 401:
                        # Authentication error
                        error_msg = "Authentication failed: Invalid API key"
                        logger.error(error_msg)
                        raise LLMAPIError(error_msg)

                    elif response.status >= 500:
                        # Server error - retry
                        error_msg = f"Server error {response.status}: {response_text}"
                        logger.error(error_msg)
                        last_exception = LLMAPIError(error_msg)

                        if attempt < self.max_retries:
                            delay = self.retry_delay * (2 ** attempt)  # Exponential backoff
                            logger.info(f"Retrying in {delay}s...")
                            await asyncio.sleep(delay)
                            continue
                        else:
                            raise last_exception

                    else:
                        # Other client errors
                        error_msg = f"HTTP {response.status}: {response_text}"
                        logger.error(error_msg)
                        raise LLMAPIError(error_msg)

            except aiohttp.ClientError as e:
                error_msg = f"Network error: {str(e)}"
                logger.error(error_msg)
                last_exception = LLMAPIError(error_msg)

                if attempt < self.max_retries:
                    delay = self.retry_delay * (2 ** attempt)
                    logger.info(f"Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    continue
                else:
                    raise last_exception

            except (LLMAPIError, LLMRateLimitError, LLMInvalidRequestError):
                # Re-lever les exceptions LLM spécifiques sans transformation
                raise

            except Exception as e:
                error_msg = f"Unexpected error: {str(e)}"
                logger.error(error_msg)
                raise LLMAPIError(error_msg)

        # Should not reach here
        if last_exception:
            raise last_exception
        else:
            raise LLMAPIError("Request failed after all retry attempts")

    async def generate(self,
                      prompt: str,
                      system_prompt: Optional[str] = None,
                      max_tokens: Optional[int] = None,
                      temperature: float = 0.1,
                      session_id: Optional[str] = None,
                      rag_debug = None,
                      **kwargs) -> GenerationResponse:
        """
        Generate text using Mistral API

        Args:
            prompt: User input prompt
            system_prompt: Optional system instruction
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0 to 1.0)
            **kwargs: Additional model parameters

        Returns:
            GenerationResponse with generated text and metadata
        """
        start_time = time.time()

        # Build messages array
        messages = []
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })
        messages.append({
            "role": "user",
            "content": prompt
        })

        # Build request payload
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            **kwargs  # Allow additional parameters
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        logger.info(f"Generating text with model: {self._model}")

        # Log LLM request if RAG debug is enabled
        if rag_debug and session_id:
            full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            rag_debug.log_llm_request(
                session_id=session_id,
                model=self._model,
                full_prompt=full_prompt,
                user_question=prompt,
                parameters={"temperature": temperature, "max_tokens": max_tokens, **kwargs}
            )

        try:
            response = await self._make_request("chat/completions", payload)

            # Extract response data
            choice = response["choices"][0]
            content = choice["message"]["content"]
            finish_reason = choice.get("finish_reason", "unknown")

            # Usage information
            usage = response.get("usage", {})
            usage_tokens = usage.get("total_tokens", 0)

            duration_ms = (time.time() - start_time) * 1000

            logger.info(
                f"Text generation successful: {usage_tokens} tokens, "
                f"{duration_ms:.1f}ms, finish: {finish_reason}",
                extra={'extra_fields': {
                    'model': self._model,
                    'tokens': usage_tokens,
                    'duration_ms': duration_ms,
                    'finish_reason': finish_reason,
                    'type': 'text_generation'
                }}
            )

            # Log LLM response if RAG debug is enabled
            if rag_debug and session_id:
                rag_debug.log_llm_response(
                    session_id=session_id,
                    response=content,
                    tokens_used=usage_tokens,
                    duration_ms=duration_ms,
                    finish_reason=finish_reason
                )

            return GenerationResponse(
                content=content,
                model=self._model,
                usage_tokens=usage_tokens,
                finish_reason=finish_reason
            )

        except (LLMAPIError, LLMRateLimitError, LLMInvalidRequestError):
            # Re-raise LLM-specific exceptions
            raise
        except Exception as e:
            error_msg = f"Text generation failed: {str(e)}"
            logger.error(error_msg)
            raise LLMAPIError(error_msg)

    async def generate_stream(self,
                             prompt: str,
                             system_prompt: Optional[str] = None,
                             max_tokens: Optional[int] = None,
                             temperature: float = 0.1,
                             session_id: Optional[str] = None,
                             rag_debug = None,
                             **kwargs):
        """
        Generate text using Mistral API with streaming support.
        Yields chunks as they arrive from the API.

        Args:
            prompt: User input prompt
            system_prompt: Optional system instruction
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0 to 1.0)
            session_id: Optional session ID for logging
            rag_debug: Optional RAG debug service
            **kwargs: Additional model parameters

        Yields:
            str: Text chunks as they are generated
        """
        import json
        start_time = time.time()

        # Build messages array
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Build request payload with stream enabled
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            **kwargs
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        logger.info(f"Starting streaming generation with model: {self._model}")

        # Log LLM request if RAG debug is enabled
        if rag_debug and session_id:
            full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            rag_debug.log_llm_request(
                session_id=session_id,
                model=self._model,
                full_prompt=full_prompt,
                user_question=prompt,
                parameters={"temperature": temperature, "max_tokens": max_tokens, "stream": True, **kwargs}
            )

        url = f"{self.base_url}/chat/completions"
        session = self._get_session()

        total_tokens = 0
        full_content = ""
        finish_reason = "unknown"

        try:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise LLMAPIError(f"Streaming failed: HTTP {response.status} - {error_text}")

                # Read stream line by line
                async for line in response.content:
                    line = line.decode('utf-8').strip()

                    if not line or line == "data: [DONE]":
                        continue

                    if line.startswith("data: "):
                        json_str = line[6:]  # Remove "data: " prefix

                        try:
                            chunk_data = json.loads(json_str)

                            # Extract delta content
                            if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
                                choice = chunk_data["choices"][0]
                                delta = choice.get("delta", {})
                                content = delta.get("content", "")

                                if content:
                                    full_content += content
                                    yield content

                                # Check for finish
                                if choice.get("finish_reason"):
                                    finish_reason = choice["finish_reason"]

                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse streaming chunk: {json_str}")
                            continue

            duration_ms = (time.time() - start_time) * 1000

            logger.info(
                f"Streaming generation completed: {len(full_content)} chars, "
                f"{duration_ms:.1f}ms, finish: {finish_reason}"
            )

            # Log LLM response if RAG debug is enabled
            if rag_debug and session_id:
                rag_debug.log_llm_response(
                    session_id=session_id,
                    response=full_content,
                    tokens_used=total_tokens,
                    duration_ms=duration_ms,
                    finish_reason=finish_reason
                )

        except (LLMAPIError, LLMRateLimitError, LLMInvalidRequestError):
            raise
        except Exception as e:
            error_msg = f"Streaming generation failed: {str(e)}"
            logger.error(error_msg)
            raise LLMAPIError(error_msg)

    async def embed(self, texts: List[str], session_id: Optional[str] = None, rag_debug = None) -> EmbeddingResponse:
        """
        Generate embeddings using Mistral API with batching support

        Args:
            texts: List of texts to embed

        Returns:
            EmbeddingResponse with embeddings and metadata
        """
        if not texts:
            raise LLMInvalidRequestError("No texts provided for embedding")

        from ...config import settings
        batch_size = settings.embedding_batch_size

        start_time = time.time()
        all_embeddings = []
        total_usage_tokens = 0

        # Si le nombre de textes est inférieur ou égal à la taille du batch, pas besoin de batching
        if len(texts) <= batch_size:
            logger.info(f"Generating embeddings for {len(texts)} texts (single batch)")
            return await self._embed_batch(texts, start_time, session_id=session_id, rag_debug=rag_debug)

        # Traitement par batches
        total_batches = (len(texts) + batch_size - 1) // batch_size
        logger.info(f"Generating embeddings for {len(texts)} texts in {total_batches} batches (size: {batch_size})")

        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            batch_num = (i // batch_size) + 1

            # Rate limiting: Mistral embeddings ont une limite de 1 req/s
            if batch_num > 1:  # Pas de délai pour le premier batch
                logger.debug(f"Rate limiting: waiting 1s before batch {batch_num}")
                await asyncio.sleep(1.0)

            logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch_texts)} texts)")

            try:
                batch_response = await self._embed_batch(batch_texts, session_id=session_id, rag_debug=rag_debug)
                all_embeddings.extend(batch_response.embeddings)
                total_usage_tokens += batch_response.usage_tokens

                logger.debug(f"Batch {batch_num} completed: {len(batch_response.embeddings)} embeddings, {batch_response.usage_tokens} tokens")

            except Exception as e:
                error_msg = f"Embedding batch {batch_num}/{total_batches} failed: {str(e)}"
                logger.error(error_msg)
                raise LLMAPIError(error_msg)

        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            f"All batches completed: {len(all_embeddings)} embeddings, "
            f"{total_usage_tokens} tokens, {duration_ms:.1f}ms",
            extra={'extra_fields': {
                'model': self._embedding_model,
                'embedding_count': len(all_embeddings),
                'tokens': total_usage_tokens,
                'duration_ms': duration_ms,
                'batch_count': total_batches,
                'type': 'embedding_generation_batched'
            }}
        )

        return EmbeddingResponse(
            embeddings=all_embeddings,
            model=self._embedding_model,
            usage_tokens=total_usage_tokens
        )

    async def _embed_batch(self, texts: List[str], start_time: float = None, session_id: Optional[str] = None, rag_debug = None) -> EmbeddingResponse:
        """
        Generate embeddings for a single batch of texts

        Args:
            texts: List of texts to embed (should be <= batch_size)
            start_time: Optional start time for timing calculation

        Returns:
            EmbeddingResponse for this batch
        """
        if start_time is None:
            start_time = time.time()

        payload = {
            "model": self._embedding_model,
            "input": texts,
            "encoding_format": "float"
        }

        try:
            response = await self._make_request("embeddings", payload)

            # Extract embeddings
            embeddings_data = response["data"]
            embeddings = [item["embedding"] for item in embeddings_data]

            # Usage information
            usage = response.get("usage", {})
            usage_tokens = usage.get("total_tokens", 0)

            duration_ms = (time.time() - start_time) * 1000

            # Log pour batch unique
            if len(embeddings) == len(texts):
                logger.info(
                    f"Embedding generation successful: {len(embeddings)} embeddings, "
                    f"{usage_tokens} tokens, {duration_ms:.1f}ms",
                    extra={'extra_fields': {
                        'model': self._embedding_model,
                        'embedding_count': len(embeddings),
                        'tokens': usage_tokens,
                        'duration_ms': duration_ms,
                        'type': 'embedding_generation'
                    }}
                )

            return EmbeddingResponse(
                embeddings=embeddings,
                model=self._embedding_model,
                usage_tokens=usage_tokens
            )

        except (LLMAPIError, LLMRateLimitError, LLMInvalidRequestError):
            # Re-raise LLM-specific exceptions
            raise
        except Exception as e:
            error_msg = f"Embedding generation failed: {str(e)}"
            logger.error(error_msg)
            raise LLMAPIError(error_msg)

    async def health_check(self) -> bool:
        """
        Check if Mistral API is available

        Returns:
            True if service is healthy, False otherwise
        """
        try:
            # Simple test with minimal request
            test_payload = {
                "model": self._model,
                "messages": [{"role": "user", "content": "test"}],
                "max_tokens": 1,
                "temperature": 0.0
            }

            await self._make_request("chat/completions", test_payload)
            logger.debug("Mistral API health check passed")
            return True

        except Exception as e:
            logger.warning(f"Mistral API health check failed: {str(e)}")
            return False

    @property
    def model_name(self) -> str:
        """Return the text generation model identifier"""
        return self._model

    @property
    def embedding_dimension(self) -> int:
        """Return the embedding vector dimension for Mistral embeddings"""
        # Mistral embeddings are 1024-dimensional
        return 1024

    async def close(self):
        """Close the HTTP session"""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("Mistral API session closed")

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()