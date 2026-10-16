"""
Unit tests of the LLM interface and of the Mistral API implementation
"""

from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest

from mimir.llm_interface.implementations.mistral_api import MistralAPIService
from mimir.llm_interface.interfaces import (
    AbstractLLMService,
    EmbeddingResponse,
    GenerationResponse,
    LLMAPIError,
    LLMException,
    LLMInvalidRequestError,
    LLMRateLimitError,
)


class TestAbstractLLMService:
    """Tests of the abstract LLMService interface"""

    def test_abstract_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            AbstractLLMService()


class TestGenerationResponse:
    """GenerationResponse tests"""

    def test_generation_response_creation(self):
        response = GenerationResponse(
            content="Hello world",
            model="mistral-small-latest",
            usage_tokens=10,
            finish_reason="stop",
        )

        assert response.content == "Hello world"
        assert response.model == "mistral-small-latest"
        assert response.usage_tokens == 10
        assert response.finish_reason == "stop"


class TestEmbeddingResponse:
    """EmbeddingResponse tests"""

    def test_embedding_response_creation(self):
        embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        response = EmbeddingResponse(embeddings=embeddings, model="mistral-embed", usage_tokens=20)

        assert response.embeddings == embeddings
        assert response.model == "mistral-embed"
        assert response.usage_tokens == 20


class TestLLMExceptions:
    """LLM exception tests"""

    def test_llm_exception_hierarchy(self):
        assert issubclass(LLMAPIError, LLMException)
        assert issubclass(LLMRateLimitError, LLMException)
        assert issubclass(LLMInvalidRequestError, LLMException)

    def test_exception_messages(self):
        exc = LLMAPIError("API connection failed")
        assert str(exc) == "API connection failed"

        exc = LLMRateLimitError("Rate limit exceeded")
        assert str(exc) == "Rate limit exceeded"


class TestMistralAPIService:
    """MistralAPIService tests"""

    @pytest.fixture
    def mistral_service(self):
        """MistralAPIService instance"""
        return MistralAPIService(
            api_key="test_api_key", model="mistral-small-latest", embedding_model="mistral-embed"
        )

    def test_mistral_api_initialization(self):
        """Test d'initialisation de MistralAPIService"""
        service = MistralAPIService(api_key="test_key")

        assert service.api_key == "test_key"
        assert service.model_name == "mistral-small-latest"
        assert service._embedding_model == "mistral-embed"

    def test_mistral_api_custom_config(self):
        service = MistralAPIService(
            api_key="test_key",
            model="custom-model",
            embedding_model="custom-embed",
            max_retries=5,
            retry_delay=2.0,
        )

        assert service._model == "custom-model"
        assert service._embedding_model == "custom-embed"
        assert service.max_retries == 5
        assert service.retry_delay == 2.0

    @pytest.mark.asyncio
    async def test_generate_success(self, mistral_service):
        mock_response_data = {
            "choices": [
                {"message": {"content": "Hello, how can I help you?"}, "finish_reason": "stop"}
            ],
            "model": "mistral-small-latest",
            "usage": {"total_tokens": 15},
        }

        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_response_data)
            mock_response.raise_for_status = Mock()
            mock_post.return_value.__aenter__.return_value = mock_response

            response = await mistral_service.generate("Hello")

            assert isinstance(response, GenerationResponse)
            assert response.content == "Hello, how can I help you?"
            assert response.model == "mistral-small-latest"
            assert response.usage_tokens == 15
            assert response.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_embed_success(self, mistral_service):
        mock_response_data = {
            "data": [{"embedding": [0.1, 0.2, 0.3]}, {"embedding": [0.4, 0.5, 0.6]}],
            "model": "mistral-embed",
            "usage": {"total_tokens": 20},
        }

        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_response_data)
            mock_response.raise_for_status = Mock()
            mock_post.return_value.__aenter__.return_value = mock_response

            texts = ["Hello", "World"]
            response = await mistral_service.embed(texts)

            assert isinstance(response, EmbeddingResponse)
            assert response.embeddings == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
            assert response.model == "mistral-embed"
            assert response.usage_tokens == 20

    @pytest.mark.asyncio
    async def test_health_check_success(self, mistral_service):
        with patch.object(mistral_service, "_make_request") as mock_request:
            mock_request.return_value = {
                "choices": [{"message": {"content": "test"}}],
                "model": "mistral-small-latest",
                "usage": {"total_tokens": 5},
            }

            is_healthy = await mistral_service.health_check()

            assert is_healthy is True
            mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_failure(self, mistral_service):
        with patch.object(mistral_service, "_make_request") as mock_request:
            mock_request.side_effect = LLMAPIError("Connection failed")

            is_healthy = await mistral_service.health_check()

            assert is_healthy is False

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mistral_service):
        """Test de gestion d'erreurs API"""
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 401
            mock_response.json = AsyncMock(return_value={"error": {"message": "Invalid API key"}})
            mock_response.raise_for_status = Mock(
                side_effect=aiohttp.ClientResponseError(request_info=Mock(), history=(), status=401)
            )
            mock_post.return_value.__aenter__.return_value = mock_response

            with pytest.raises(LLMAPIError) as exc_info:
                await mistral_service.generate("test")

            assert "Invalid API key" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, mistral_service):
        """Test d'erreur de limite de taux"""
        # Patch asyncio.sleep to avoid real waits
        with (
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch("aiohttp.ClientSession.post") as mock_post,
        ):
            mock_response = AsyncMock()
            mock_response.status = 429
            mock_response.headers = {"Retry-After": "1"}  # Short delay
            mock_response.text = AsyncMock(
                return_value='{"error": {"message": "Rate limit exceeded"}}'
            )
            mock_response.json = AsyncMock(
                return_value={"error": {"message": "Rate limit exceeded"}}
            )
            mock_response.raise_for_status = Mock(
                side_effect=aiohttp.ClientResponseError(request_info=Mock(), history=(), status=429)
            )
            mock_post.return_value.__aenter__.return_value = mock_response

            with pytest.raises(LLMRateLimitError) as exc_info:
                await mistral_service.generate("test")

            assert "Rate limit exceeded" in str(exc_info.value)
            # Check that sleep was called for the retries
            assert mock_sleep.call_count > 0

    @pytest.mark.asyncio
    async def test_invalid_request_error(self, mistral_service):
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 400
            mock_response.json = AsyncMock(return_value={"error": {"message": "Invalid request"}})
            mock_response.raise_for_status = Mock(
                side_effect=aiohttp.ClientResponseError(request_info=Mock(), history=(), status=400)
            )
            mock_post.return_value.__aenter__.return_value = mock_response

            with pytest.raises(LLMInvalidRequestError) as exc_info:
                await mistral_service.generate("test")

            assert "Invalid request" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_connection_error(self, mistral_service):
        """Test d'erreur de connexion"""
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_post.side_effect = aiohttp.ClientConnectionError("Connection failed")

            with pytest.raises(LLMAPIError) as exc_info:
                await mistral_service.generate("test")

            assert "Connection failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_retry_mechanism(self, mistral_service):
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First call: connection error
                raise aiohttp.ClientConnectionError("Connection failed")
            else:
                # Second call: success
                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.text = AsyncMock(return_value='{"success": true}')
                mock_response.json = AsyncMock(
                    return_value={
                        "choices": [{"message": {"content": "Success"}, "finish_reason": "stop"}],
                        "model": "mistral-small-latest",
                        "usage": {"total_tokens": 10},
                    }
                )
                mock_response.raise_for_status = Mock()
                mock_response.__aenter__ = AsyncMock(return_value=mock_response)
                mock_response.__aexit__ = AsyncMock(return_value=None)
                return mock_response

        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_post.side_effect = side_effect
            with patch("asyncio.sleep", new_callable=AsyncMock):  # Mock sleep to speed the tests up
                response = await mistral_service.generate("test")

                assert response.content == "Success"
                assert call_count == 2  # First a failure, then a success

    def test_embedding_dimension_property(self, mistral_service):
        # The dimension depends on the embedding model
        dimension = mistral_service.embedding_dimension
        assert isinstance(dimension, int)
        assert dimension > 0

    @pytest.mark.asyncio
    async def test_generate_with_system_prompt(self, mistral_service):
        mock_response_data = {
            "choices": [{"message": {"content": "System response"}, "finish_reason": "stop"}],
            "model": "mistral-small-latest",
            "usage": {"total_tokens": 15},
        }

        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_response_data)
            mock_response.raise_for_status = Mock()
            mock_post.return_value.__aenter__.return_value = mock_response

            await mistral_service.generate(
                prompt="User prompt",
                system_prompt="You are a helpful assistant",
                max_tokens=100,
                temperature=0.7,
            )

            # Check that the parameters were sent
            call_args = mock_post.call_args
            json_data = call_args[1]["json"]

            # Check the message structure with a system prompt
            assert len(json_data["messages"]) == 2
            assert json_data["messages"][0]["role"] == "system"
            assert json_data["messages"][1]["role"] == "user"
            assert json_data["max_tokens"] == 100
            assert json_data["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_empty_texts_validation(self, mistral_service):
        with pytest.raises(LLMInvalidRequestError):
            await mistral_service.embed([])


# Integration tests against the real Mistral API removed
# These tests need a real API key and cannot run in CI/CD
