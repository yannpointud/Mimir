"""
Tests pour les dépendances FastAPI.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock  # noqa: F401
from sqlalchemy.orm import Session

from src.api.dependencies import (
    get_document_repository,
    get_configuration_repository,
    get_audit_log_repository,
    get_cache_service,
    get_chat_cache_service,
    get_email_service,
    get_jwt_handler,
    get_llm_service,
    get_vector_store,
    get_ingestion_processor,
    set_ingestion_processor,
    _llm_service,  # noqa: F401
    _vector_store,  # noqa: F401
    _ingestion_processor  # noqa: F401
)


class TestRepositoryDependencies:
    """Tests pour les dépendances de repository."""

    @patch('src.api.dependencies.DocumentRepository')
    def test_get_document_repository(self, mock_repo_class):
        """Test obtention du repository de documents."""
        mock_db = Mock(spec=Session)
        mock_repo_instance = Mock()
        mock_repo_class.return_value = mock_repo_instance

        result = get_document_repository(mock_db)

        assert result == mock_repo_instance
        mock_repo_class.assert_called_once_with(mock_db)

    @patch('src.api.dependencies.ConfigurationRepository')
    def test_get_configuration_repository(self, mock_repo_class):
        """Test obtention du repository de configuration."""
        mock_db = Mock(spec=Session)
        mock_repo_instance = Mock()
        mock_repo_class.return_value = mock_repo_instance

        result = get_configuration_repository(mock_db)

        assert result == mock_repo_instance
        mock_repo_class.assert_called_once_with(mock_db)

    @patch('src.api.dependencies.AuditLogRepository')
    def test_get_audit_log_repository(self, mock_repo_class):
        """Test obtention du repository d'audit log."""
        mock_db = Mock(spec=Session)
        mock_repo_instance = Mock()
        mock_repo_class.return_value = mock_repo_instance

        result = get_audit_log_repository(mock_db)

        assert result == mock_repo_instance
        mock_repo_class.assert_called_once_with(mock_db)


class TestServiceDependencies:
    """Tests pour les dépendances de services."""

    @patch('src.api.dependencies.cache_service')
    def test_get_cache_service(self, mock_cache_service):
        """Test obtention du service de cache."""
        result = get_cache_service()

        assert result == mock_cache_service

    @patch('src.api.dependencies.chat_cache_service')
    def test_get_chat_cache_service(self, mock_chat_cache_service):
        """Test obtention du service de cache chat."""
        result = get_chat_cache_service()

        assert result == mock_chat_cache_service

    @patch('src.api.dependencies.email_service')
    def test_get_email_service(self, mock_email_service):
        """Test obtention du service email."""
        result = get_email_service()

        assert result == mock_email_service

    @patch('src.api.dependencies.jwt_handler')
    def test_get_jwt_handler(self, mock_jwt_handler):
        """Test obtention du handler JWT."""
        result = get_jwt_handler()

        assert result == mock_jwt_handler


class TestLLMServiceSingleton:
    """Tests pour le singleton LLM service."""

    def setup_method(self):
        """Reset du singleton avant chaque test."""
        import src.api.dependencies
        src.api.dependencies._llm_service = None

    @patch('src.api.dependencies.settings')
    @patch('src.api.dependencies.MistralAPIService')
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
            retry_delay=1.0
        )

    @patch('src.api.dependencies.settings')
    @patch('src.api.dependencies.MistralAPIService')
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
        import src.api.dependencies
        src.api.dependencies._vector_store = None

    @patch('src.api.dependencies.settings')
    @patch('src.api.dependencies.FaissVectorStore')
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
            index_type="FlatL2"
        )

    @patch('src.api.dependencies.settings')
    @patch('src.api.dependencies.FaissVectorStore')
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
        import src.api.dependencies
        src.api.dependencies._ingestion_processor = None

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


class TestGlobalStateConsistency:
    """Tests pour la cohérence de l'état global."""

    def setup_method(self):
        """Reset de tous les singletons."""
        import src.api.dependencies
        src.api.dependencies._llm_service = None
        src.api.dependencies._vector_store = None
        src.api.dependencies._ingestion_processor = None

    @patch('src.api.dependencies.settings')
    @patch('src.api.dependencies.MistralAPIService')
    @patch('src.api.dependencies.FaissVectorStore')
    def test_multiple_services_independent(self, mock_faiss_class, mock_mistral_class, mock_settings):
        """Test indépendance des différents singletons."""
        # Mock des settings
        mock_settings.mistral_api_key = "test_key"
        mock_settings.mistral_model = "test_model"
        mock_settings.mistral_embedding_model = "test_embedding"
        mock_settings.embedding_dimension = 768
        mock_settings.faiss_index_path = "/path/to/index"
        mock_settings.faiss_metadata_path = "/path/to/metadata"
        mock_settings.similarity_threshold = 0.7

        mock_llm = Mock()
        mock_vector = Mock()
        mock_processor = Mock()

        mock_mistral_class.return_value = mock_llm
        mock_faiss_class.return_value = mock_vector

        # Créer les services
        llm = get_llm_service()
        vector = get_vector_store()
        set_ingestion_processor(mock_processor)
        processor = get_ingestion_processor()

        # Vérifier qu'ils sont différents
        assert llm != vector
        assert llm != processor
        assert vector != processor

        # Vérifier les instances
        assert llm == mock_llm
        assert vector == mock_vector
        assert processor == mock_processor