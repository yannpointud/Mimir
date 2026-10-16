"""
Tests pour les dépendances FastAPI.
"""

import pytest
from unittest.mock import Mock, patch

from mimir.api.dependencies import (
    get_llm_service,
    get_vector_store,
    get_ingestion_processor,
    set_ingestion_processor,
)


class TestLLMServiceSingleton:
    """Tests pour le singleton LLM service."""

    def setup_method(self):
        """Reset du singleton avant chaque test."""
        import mimir.api.dependencies

        mimir.api.dependencies._llm_service = None

    @patch("mimir.api.dependencies.settings")
    @patch("mimir.api.dependencies.MistralAPIService")
    def test_get_llm_service_first_call(self, mock_mistral_class, mock_settings):
        """Test première création du service LLM."""
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
        """Test comportement singleton - même instance retournée."""
        mock_service_instance = Mock()
        mock_mistral_class.return_value = mock_service_instance

        # Premier appel
        result1 = get_llm_service()
        # Deuxième appel
        result2 = get_llm_service()

        assert result1 == result2
        assert result1 == mock_service_instance
        # La classe ne doit être instanciée qu'une seule fois
        mock_mistral_class.assert_called_once()


class TestVectorStoreSingleton:
    """Tests pour le singleton vector store."""

    def setup_method(self):
        """Reset du singleton avant chaque test."""
        import mimir.api.dependencies

        mimir.api.dependencies._vector_store = None

    @patch("mimir.api.dependencies.settings")
    @patch("mimir.api.dependencies.FaissVectorStore")
    def test_get_vector_store_first_call(self, mock_faiss_class, mock_settings):
        """Test première création du vector store."""
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
        """Test comportement singleton du vector store."""
        mock_store_instance = Mock()
        mock_faiss_class.return_value = mock_store_instance

        # Premier appel
        result1 = get_vector_store()
        # Deuxième appel
        result2 = get_vector_store()

        assert result1 == result2
        assert result1 == mock_store_instance
        # La classe ne doit être instanciée qu'une seule fois
        mock_faiss_class.assert_called_once()


class TestIngestionProcessorManagement:
    """Tests pour la gestion du processeur d'ingestion."""

    def setup_method(self):
        """Reset du processeur avant chaque test."""
        import mimir.api.dependencies

        mimir.api.dependencies._ingestion_processor = None

    def test_get_ingestion_processor_not_initialized(self):
        """Test erreur quand processeur non initialisé."""
        with pytest.raises(RuntimeError, match="Ingestion processor not initialized"):
            get_ingestion_processor()

    def test_set_and_get_ingestion_processor(self):
        """Test définition et récupération du processeur."""
        mock_processor = Mock()

        # Définir le processeur
        set_ingestion_processor(mock_processor)

        # Le récupérer
        result = get_ingestion_processor()

        assert result == mock_processor

    def test_set_ingestion_processor_overwrite(self):
        """Test écrasement du processeur existant."""
        mock_processor1 = Mock()
        mock_processor2 = Mock()

        # Premier processeur
        set_ingestion_processor(mock_processor1)
        result1 = get_ingestion_processor()
        assert result1 == mock_processor1

        # Écrasement
        set_ingestion_processor(mock_processor2)
        result2 = get_ingestion_processor()
        assert result2 == mock_processor2

    def test_ingestion_processor_none_value(self):
        """Test définition du processeur à None."""
        mock_processor = Mock()

        # D'abord définir un processeur
        set_ingestion_processor(mock_processor)
        assert get_ingestion_processor() == mock_processor

        # Puis le remettre à None
        set_ingestion_processor(None)

        with pytest.raises(RuntimeError, match="Ingestion processor not initialized"):
            get_ingestion_processor()
