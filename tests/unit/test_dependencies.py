"""
FastAPI dependency tests.
"""

from unittest.mock import Mock, patch

import pytest

from mimir.api.dependencies import (
    get_ingestion_processor,
    get_llm_service,
    get_vector_store,
    set_ingestion_processor,
)


class TestLLMServiceSingleton:
    """LLM service singleton tests."""

    def setup_method(self):
        """Reset the singleton before each test."""
        import mimir.api.dependencies

        mimir.api.dependencies._llm_service = None

    @patch("mimir.api.dependencies.settings")
    @patch("mimir.api.dependencies.MistralAPIService")
    def test_get_llm_service_first_call(self, mock_mistral_class, mock_settings):
        mock_settings.mistral_api_key = "test_key"
        mock_settings.mistral_model = "test_model"
        mock_settings.mistral_embedding_model = "test_embedding"

        mock_service_instance = Mock()
        mock_mistral_class.return_value = mock_service_instance

        result = get_llm_service()

        assert result == mock_service_instance
        mock_mistral_class.assert_called_once_with(
            api_key="test_key",
            model="test_model",
            embedding_model="test_embedding",
            max_retries=3,
            retry_delay=1.0,
        )

    @patch("mimir.api.dependencies.settings")
    @patch("mimir.api.dependencies.MistralAPIService")
    def test_get_llm_service_singleton_behavior(self, mock_mistral_class, mock_settings):
        mock_service_instance = Mock()
        mock_mistral_class.return_value = mock_service_instance

        # First call
        result1 = get_llm_service()
        # Second call
        result2 = get_llm_service()

        assert result1 == result2
        assert result1 == mock_service_instance
        # The class must be instantiated only once
        mock_mistral_class.assert_called_once()


class TestVectorStoreSingleton:
    """Vector store singleton tests."""

    def setup_method(self):
        """Reset the singleton before each test."""
        import mimir.api.dependencies

        mimir.api.dependencies._vector_store = None

    @patch("mimir.api.dependencies.settings")
    @patch("mimir.api.dependencies.FaissVectorStore")
    def test_get_vector_store_first_call(self, mock_faiss_class, mock_settings):
        mock_settings.embedding_dimension = 768
        mock_settings.faiss_index_path = "/path/to/index"
        mock_settings.faiss_metadata_path = "/path/to/metadata"
        mock_settings.similarity_threshold = 0.7

        mock_store_instance = Mock()
        mock_faiss_class.return_value = mock_store_instance

        result = get_vector_store()

        assert result == mock_store_instance
        mock_faiss_class.assert_called_once_with(
            dimension=768,
            index_path="/path/to/index",
            metadata_path="/path/to/metadata",
            similarity_threshold=0.7,
            index_type="FlatL2",
        )

    @patch("mimir.api.dependencies.settings")
    @patch("mimir.api.dependencies.FaissVectorStore")
    def test_get_vector_store_singleton_behavior(self, mock_faiss_class, mock_settings):
        mock_store_instance = Mock()
        mock_faiss_class.return_value = mock_store_instance

        # First call
        result1 = get_vector_store()
        # Second call
        result2 = get_vector_store()

        assert result1 == result2
        assert result1 == mock_store_instance
        # The class must be instantiated only once
        mock_faiss_class.assert_called_once()


class TestIngestionProcessorManagement:
    """Ingestion processor management tests."""

    def setup_method(self):
        """Reset the processor before each test."""
        import mimir.api.dependencies

        mimir.api.dependencies._ingestion_processor = None

    def test_get_ingestion_processor_not_initialized(self):
        with pytest.raises(RuntimeError, match="Ingestion processor not initialized"):
            get_ingestion_processor()

    def test_set_and_get_ingestion_processor(self):
        mock_processor = Mock()

        # Set the processor
        set_ingestion_processor(mock_processor)

        # Read it back
        result = get_ingestion_processor()

        assert result == mock_processor

    def test_set_ingestion_processor_overwrite(self):
        mock_processor1 = Mock()
        mock_processor2 = Mock()

        # Premier processeur
        set_ingestion_processor(mock_processor1)
        result1 = get_ingestion_processor()
        assert result1 == mock_processor1

        # Overwrite
        set_ingestion_processor(mock_processor2)
        result2 = get_ingestion_processor()
        assert result2 == mock_processor2

    def test_ingestion_processor_none_value(self):
        mock_processor = Mock()

        # Set a processor first
        set_ingestion_processor(mock_processor)
        assert get_ingestion_processor() == mock_processor

        # Then set it back to None
        set_ingestion_processor(None)

        with pytest.raises(RuntimeError, match="Ingestion processor not initialized"):
            get_ingestion_processor()
