"""
Tests unitaires pour l'interface LLM et l'implémentation Mistral API - Version corrigée
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
    """Tests pour l'interface abstraite LLMService"""

    def test_abstract_class_cannot_be_instantiated(self):
        """L'interface abstraite ne peut pas être instanciée"""
        with pytest.raises(TypeError):
            AbstractLLMService()


class TestGenerationResponse:
    """Tests pour la classe GenerationResponse"""

    def test_generation_response_creation(self):
        """Test de création d'une réponse de génération"""
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
    """Tests pour la classe EmbeddingResponse"""

    def test_embedding_response_creation(self):
        """Test de création d'une réponse d'embedding"""
        embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        response = EmbeddingResponse(embeddings=embeddings, model="mistral-embed", usage_tokens=20)

        assert response.embeddings == embeddings
        assert response.model == "mistral-embed"
        assert response.usage_tokens == 20


class TestLLMExceptions:
    """Tests pour les exceptions LLM"""

    def test_llm_exception_hierarchy(self):
        """Test de la hiérarchie des exceptions"""
        assert issubclass(LLMAPIError, LLMException)
        assert issubclass(LLMRateLimitError, LLMException)
        assert issubclass(LLMInvalidRequestError, LLMException)

    def test_exception_messages(self):
        """Test des messages d'exception"""
        exc = LLMAPIError("API connection failed")
        assert str(exc) == "API connection failed"

        exc = LLMRateLimitError("Rate limit exceeded")
        assert str(exc) == "Rate limit exceeded"


class TestMistralAPIService:
    """Tests pour l'implémentation MistralAPIService"""

    @pytest.fixture
    def mistral_service(self):
        """Instance MistralAPIService pour les tests"""
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
        """Test avec configuration personnalisée"""
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
        """Test de génération réussie"""
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
        """Test d'embedding réussi"""
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
        """Test de health check réussi"""
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
        """Test de health check en échec"""
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
        # Patch asyncio.sleep pour éviter d'attendre réellement
        with (
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch("aiohttp.ClientSession.post") as mock_post,
        ):
            mock_response = AsyncMock()
            mock_response.status = 429
            mock_response.headers = {"Retry-After": "1"}  # Court délai
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
            # Vérifier que sleep a été appelé pour les retries
            assert mock_sleep.call_count > 0

    @pytest.mark.asyncio
    async def test_invalid_request_error(self, mistral_service):
        """Test d'erreur de requête invalide"""
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
        """Test du mécanisme de retry"""
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # Premier appel : erreur de connexion
                raise aiohttp.ClientConnectionError("Connection failed")
            else:
                # Deuxième appel : succès
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
            with patch(
                "asyncio.sleep", new_callable=AsyncMock
            ):  # Mock sleep pour accélérer les tests
                response = await mistral_service.generate("test")

                assert response.content == "Success"
                assert call_count == 2  # Premier échec, puis succès

    def test_embedding_dimension_property(self, mistral_service):
        """Test de la propriété embedding_dimension"""
        # La dimension dépend du modèle d'embedding utilisé
        dimension = mistral_service.embedding_dimension
        assert isinstance(dimension, int)
        assert dimension > 0

    @pytest.mark.asyncio
    async def test_generate_with_system_prompt(self, mistral_service):
        """Test de génération avec prompt système"""
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

            # Vérifier que les paramètres ont été envoyés
            call_args = mock_post.call_args
            json_data = call_args[1]["json"]

            # Vérifier la structure des messages avec système
            assert len(json_data["messages"]) == 2
            assert json_data["messages"][0]["role"] == "system"
            assert json_data["messages"][1]["role"] == "user"
            assert json_data["max_tokens"] == 100
            assert json_data["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_empty_texts_validation(self, mistral_service):
        """Test de validation pour liste de textes vide"""
        with pytest.raises(LLMInvalidRequestError):
            await mistral_service.embed([])


# Tests d'intégration avec l'API Mistral réelle supprimés
# Ces tests nécessitent une vraie clé API et ne peuvent pas être exécutés en CI/CD
