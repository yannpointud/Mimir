"""
Tests unitaires pour les endpoints de santé système.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime
from fastapi import HTTPException, status, Response
from sqlalchemy.orm import Session

from backend.src.api.endpoints.health import router, health_check, database_health, cache_health, disk_usage


class TestHealthModels:
    """Tests pour les modèles de santé."""

    def test_health_check_response_structure(self):
        """Test de la structure de réponse de health check."""
        # Ce test vérifie que les réponses suivent la structure attendue
        # Les modèles Pydantic valideront automatiquement la structure
        pass  # Les modèles sont définis dans shared.models


class TestHealthCheckEndpoint:
    """Tests pour l'endpoint de health check principal."""

    @pytest.fixture
    def mock_db_session(self):
        """Mock session de base de données."""
        return Mock(spec=Session)

    @patch('backend.src.api.endpoints.health._check_database_health')
    @patch('backend.src.api.endpoints.health._check_vector_store_health')
    @patch('backend.src.api.endpoints.health._check_llm_health')
    @patch('backend.src.api.endpoints.health._check_cache_health')
    @patch('backend.src.api.endpoints.health._check_email_health')
    @patch('backend.src.api.endpoints.health.settings')
    def test_health_check_all_healthy(
        self, mock_settings, mock_email, mock_cache, mock_llm,
        mock_vector, mock_db, mock_db_session
    ):
        """Test health check avec tous les composants sains."""

        # Configuration des mocks
        mock_settings.api_version = "1.0.0"
        mock_settings.is_production = False

        mock_db.return_value = {"healthy": True, "connection": "ok"}
        mock_vector.return_value = {"healthy": True, "index_file": "exists"}
        mock_llm.return_value = {"healthy": True, "api_configured": True}
        mock_cache.return_value = {"healthy": True, "test": "passed"}
        mock_email.return_value = {"healthy": True, "configuration": {"configured": True}}

        # Appel de la fonction
        response = Response()
        result = asyncio.run(health_check(response=response, db=mock_db_session))

        # Vérifications
        assert result.status == "healthy"
        # Healthy state must keep the default 200 status code
        assert response.status_code == status.HTTP_200_OK
        assert result.version == "1.0.0"
        assert "database" in result.checks
        assert "vector_store" in result.checks
        assert "llm_api" in result.checks
        assert "cache" in result.checks
        assert "email_service" in result.checks

    @patch('backend.src.api.endpoints.health._check_database_health')
    @patch('backend.src.api.endpoints.health._check_vector_store_health')
    @patch('backend.src.api.endpoints.health._check_llm_health')
    @patch('backend.src.api.endpoints.health._check_cache_health')
    @patch('backend.src.api.endpoints.health._check_email_health')
    @patch('backend.src.api.endpoints.health.settings')
    def test_health_check_some_unhealthy(
        self, mock_settings, mock_email, mock_cache, mock_llm,
        mock_vector, mock_db, mock_db_session
    ):
        """Test health check avec certains composants défaillants."""

        # Configuration des mocks
        mock_settings.api_version = "1.0.0"
        mock_settings.is_production = True

        mock_db.return_value = {"healthy": False, "connection": "failed", "error": "Connection timeout"}
        mock_vector.return_value = {"healthy": True, "index_file": "exists"}
        mock_llm.return_value = {"healthy": False, "api_configured": False}
        mock_cache.return_value = {"healthy": True, "test": "passed"}
        mock_email.return_value = {"healthy": True, "configuration": {"configured": True}}

        # Appel de la fonction
        response = Response()
        result = asyncio.run(health_check(response=response, db=mock_db_session))

        # Vérifications
        assert result.status == "unhealthy"
        # Unhealthy state must be reported through the HTTP status code
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "database" in result.checks
        assert result.checks["database"]["healthy"] is False
        assert "llm_api" in result.checks
        assert result.checks["llm_api"]["healthy"] is False
        assert "vector_store" in result.checks
        assert result.checks["vector_store"]["healthy"] is True

    @patch('backend.src.api.endpoints.health._check_database_health')
    def test_health_check_exception_handling(self, mock_db, mock_db_session):
        """Test de gestion d'exception dans health check."""

        # Configuration du mock pour lever une exception
        mock_db.side_effect = Exception("Unexpected error")

        # Test que l'exception est gérée
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(health_check(response=Response(), db=mock_db_session))

        assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


class TestDatabaseHealthEndpoint:
    """Tests pour l'endpoint de santé base de données."""

    @pytest.fixture
    def mock_db_session(self):
        """Mock session de base de données."""
        return Mock(spec=Session)

    @patch('backend.src.api.endpoints.health._check_database_health')
    def test_database_health_success(self, mock_check, mock_db_session):
        """Test de santé base de données réussie."""

        # Configuration du mock
        expected_result = {
            "healthy": True,
            "connection": "ok",
            "document_count": 5,
            "response_time_ms": 10
        }
        mock_check.return_value = expected_result

        # Appel de la fonction
        result = asyncio.run(database_health(db=mock_db_session))

        # Vérifications
        assert result == expected_result
        assert result["healthy"] is True
        assert result["document_count"] == 5

    @patch('backend.src.api.endpoints.health._check_database_health')
    def test_database_health_failure(self, mock_check, mock_db_session):
        """Test de santé base de données en échec."""

        # Configuration du mock
        expected_result = {
            "healthy": False,
            "connection": "failed",
            "error": "Connection timeout"
        }
        mock_check.return_value = expected_result

        # Appel de la fonction
        result = asyncio.run(database_health(db=mock_db_session))

        # Vérifications
        assert result == expected_result
        assert result["healthy"] is False
        assert "error" in result


class TestCacheHealthEndpoint:
    """Tests pour l'endpoint de santé cache."""

    @patch('backend.src.api.endpoints.health._check_cache_health')
    def test_cache_health_success(self, mock_check):
        """Test de santé cache réussie."""

        # Configuration du mock
        expected_result = {
            "healthy": True,
            "test": "passed",
            "main_cache": {"size": 100, "hits": 80, "misses": 20},
            "chat_cache": {"size": 50, "hits": 40, "misses": 10}
        }
        mock_check.return_value = expected_result

        # Appel de la fonction
        result = asyncio.run(cache_health())

        # Vérifications
        assert result == expected_result
        assert result["healthy"] is True
        assert result["test"] == "passed"

    @patch('backend.src.api.endpoints.health._check_cache_health')
    def test_cache_health_failure(self, mock_check):
        """Test de santé cache en échec."""

        # Configuration du mock
        expected_result = {
            "healthy": False,
            "error": "Cache service unavailable"
        }
        mock_check.return_value = expected_result

        # Appel de la fonction
        result = asyncio.run(cache_health())

        # Vérifications
        assert result == expected_result
        assert result["healthy"] is False


class TestDiskUsageEndpoint:
    """Tests pour l'endpoint d'usage disque."""

    @patch('backend.src.api.endpoints.health.settings')
    @patch('shutil.disk_usage')
    @patch('os.path.exists')
    def test_disk_usage_success(self, mock_exists, mock_disk_usage, mock_settings):
        """Test d'usage disque réussi."""

        # Configuration des mocks
        mock_settings.data_dir = "/data"
        mock_settings.upload_dir = "/uploads"
        mock_settings.faiss_index_path = "/indexes/faiss.index"

        mock_exists.return_value = True
        mock_disk_usage.return_value = (1000000000000, 500000000000, 500000000000)  # 1TB total, 500GB used

        # Appel de la fonction
        result = asyncio.run(disk_usage())

        # Vérifications
        assert result["healthy"] is True
        assert "disk_usage" in result
        assert "data_dir" in result["disk_usage"]
        assert result["disk_usage"]["data_dir"]["total_gb"] == 931.32  # 1TB en GB
        assert result["disk_usage"]["data_dir"]["usage_percent"] == 50.0

    @patch('backend.src.api.endpoints.health.settings')
    @patch('os.path.exists')
    def test_disk_usage_directory_not_exists(self, mock_exists, mock_settings):
        """Test d'usage disque avec répertoire inexistant."""

        # Configuration des mocks
        mock_settings.data_dir = "/nonexistent"
        mock_settings.upload_dir = "/uploads"
        mock_settings.faiss_index_path = "/indexes/faiss.index"

        mock_exists.return_value = False

        # Appel de la fonction
        result = asyncio.run(disk_usage())

        # Vérifications
        assert result["healthy"] is True
        assert "disk_usage" in result
        assert "error" in result["disk_usage"]["data_dir"]
        assert result["disk_usage"]["data_dir"]["error"] == "Directory does not exist"

    @patch('os.path.dirname')
    @patch('backend.src.api.endpoints.health.settings')
    @patch('shutil.disk_usage')
    @patch('os.path.exists')
    def test_disk_usage_exception_handling(self, mock_exists, mock_disk_usage, mock_settings, mock_dirname):
        """Test de gestion d'exception pour usage disque."""

        # Configuration des mocks
        mock_settings.data_dir = "/data"
        mock_settings.upload_dir = "/uploads"
        mock_settings.faiss_index_path = "/indexes/faiss.index"

        # Exception déclenchée lors de os.path.dirname()
        mock_dirname.side_effect = Exception("Path error")

        # Appel de la fonction
        result = asyncio.run(disk_usage())

        # Vérifications
        assert result["healthy"] is False
        assert "error" in result


class TestHealthHelperFunctions:
    """Tests pour les fonctions utilitaires de santé."""

    @pytest.fixture
    def mock_db_session(self):
        """Mock session de base de données."""
        return Mock(spec=Session)

    @patch('backend.src.api.endpoints.health.text')
    def test_check_database_health_success(self, mock_text, mock_db_session):
        """Test de vérification santé base de données réussie."""
        from backend.src.api.endpoints.health import _check_database_health
        from backend.src.database.models import Document

        # Configuration des mocks
        mock_result = Mock()
        mock_result.scalar.return_value = 1
        mock_db_session.execute.return_value = mock_result
        mock_db_session.query.return_value.count.return_value = 10

        # Appel de la fonction
        result = asyncio.run(_check_database_health(mock_db_session))

        # Vérifications
        assert result["healthy"] is True
        assert result["connection"] == "ok"
        assert result["document_count"] == 10

    @patch('backend.src.api.endpoints.health.text')
    def test_check_database_health_query_failure(self, mock_text, mock_db_session):
        """Test de vérification santé base de données avec échec de requête."""
        from backend.src.api.endpoints.health import _check_database_health

        # Configuration des mocks
        mock_db_session.execute.side_effect = Exception("Connection failed")

        # Appel de la fonction
        result = asyncio.run(_check_database_health(mock_db_session))

        # Vérifications
        assert result["healthy"] is False
        assert result["connection"] == "failed"
        assert "error" in result

    @patch('backend.src.api.endpoints.health.settings')
    @patch('os.path.exists')
    def test_check_vector_store_health_initialized(self, mock_exists, mock_settings):
        """Test de vérification santé vector store initialisé."""
        from backend.src.api.endpoints.health import _check_vector_store_health

        # Configuration des mocks
        mock_settings.faiss_index_path = "/path/to/index"
        mock_settings.faiss_metadata_path = "/path/to/metadata"
        mock_exists.return_value = True

        # Appel de la fonction
        result = asyncio.run(_check_vector_store_health())

        # Vérifications
        assert result["healthy"] is True
        assert result["index_file"] == "exists"
        assert result["metadata_file"] == "exists"

    @patch('backend.src.api.endpoints.health.settings')
    @patch('os.path.exists')
    def test_check_vector_store_health_not_initialized(self, mock_exists, mock_settings):
        """Test de vérification santé vector store non initialisé."""
        from backend.src.api.endpoints.health import _check_vector_store_health

        # Configuration des mocks
        mock_settings.faiss_index_path = "/path/to/index"
        mock_settings.faiss_metadata_path = "/path/to/metadata"
        mock_exists.return_value = False

        # Appel de la fonction
        result = asyncio.run(_check_vector_store_health())

        # Vérifications
        assert result["healthy"] is True
        assert result["index_file"] == "not_initialized"
        assert "normal for new installation" in result["note"]

    @patch('backend.src.api.endpoints.health.settings')
    def test_check_llm_health_configured(self, mock_settings):
        """Test de vérification santé LLM avec API configurée."""
        from backend.src.api.endpoints.health import _check_llm_health

        # Configuration des mocks
        mock_settings.mistral_api_key = "test_api_key"
        mock_settings.llm_provider = "mistral"
        mock_settings.mistral_model = "mistral-small-latest"

        # Appel de la fonction
        result = asyncio.run(_check_llm_health())

        # Vérifications
        assert result["healthy"] is True
        assert result["api_configured"] is True
        assert result["provider"] == "mistral"
        assert result["model"] == "mistral-small-latest"

    @patch('backend.src.api.endpoints.health.settings')
    def test_check_llm_health_not_configured(self, mock_settings):
        """Test de vérification santé LLM sans API configurée."""
        from backend.src.api.endpoints.health import _check_llm_health

        # Configuration des mocks
        mock_settings.mistral_api_key = None
        mock_settings.llm_provider = "mistral"

        # Appel de la fonction
        result = asyncio.run(_check_llm_health())

        # Vérifications
        assert result["healthy"] is False
        assert result["api_configured"] is False
        assert "API key not configured" in result["note"]

    @patch('backend.src.cache.lru_cache.cache_service')
    @patch('backend.src.cache.lru_cache.chat_cache_service')
    def test_check_cache_health_success(self, mock_chat_cache, mock_cache):
        """Test de vérification santé cache réussie."""
        from backend.src.api.endpoints.health import _check_cache_health

        # Configuration des mocks
        mock_cache.get.return_value = "test_data"
        mock_cache.get_stats.return_value = {"hits": 100, "misses": 20}
        mock_chat_cache.get_stats.return_value = {"hits": 50, "misses": 10}

        # Appel de la fonction
        result = asyncio.run(_check_cache_health())

        # Vérifications
        assert result["healthy"] is True
        assert result["test"] == "passed"
        assert "main_cache" in result
        assert "chat_cache" in result

    @patch('src.cache.lru_cache.chat_cache_service')
    @patch('src.cache.lru_cache.cache_service')
    def test_check_cache_health_failure(self, mock_cache, mock_chat_cache):
        """Test de vérification santé cache en échec."""
        from backend.src.api.endpoints.health import _check_cache_health

        # Configuration du mock pour lever une exception lors du set (premier appel)
        mock_cache.set.side_effect = Exception("Cache unavailable")

        # Appel de la fonction
        result = asyncio.run(_check_cache_health())

        # Vérifications
        assert result["healthy"] is False
        assert "error" in result

    @patch('src.email_service.smtp_client.email_service')
    def test_check_email_health_configured(self, mock_email_service):
        """Test de vérification santé email configuré."""
        from backend.src.api.endpoints.health import _check_email_health

        # Configuration du mock
        mock_email_service.get_configuration_status.return_value = {
            "configured": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 587
        }

        # Appel de la fonction
        result = asyncio.run(_check_email_health())

        # Vérifications
        assert result["healthy"] is True
        assert result["configuration"]["configured"] is True
        assert "Email service configured" in result["note"]

    @patch('src.email_service.smtp_client.email_service')
    def test_check_email_health_not_configured(self, mock_email_service):
        """Test de vérification santé email non configuré."""
        from backend.src.api.endpoints.health import _check_email_health

        # Configuration du mock
        mock_email_service.get_configuration_status.return_value = {"configured": False}

        # Appel de la fonction
        result = asyncio.run(_check_email_health())

        # Vérifications
        assert result["healthy"] is False
        assert result["configuration"]["configured"] is False
        assert "Email service not configured" in result["note"]


class TestHealthIntegration:
    """Tests d'intégration pour les endpoints de santé."""

    @patch('backend.src.api.endpoints.health._check_database_health')
    @patch('backend.src.api.endpoints.health._check_vector_store_health')
    @patch('backend.src.api.endpoints.health._check_llm_health')
    @patch('backend.src.api.endpoints.health._check_cache_health')
    @patch('backend.src.api.endpoints.health._check_email_health')
    @patch('backend.src.api.endpoints.health.settings')
    def test_health_check_comprehensive_scenario(
        self, mock_settings, mock_email, mock_cache, mock_llm,
        mock_vector, mock_db
    ):
        """Test de scénario complet de health check."""

        # Configuration des mocks pour simulation réaliste
        mock_settings.api_version = "1.0.0"
        mock_settings.is_production = False

        # Base de données saine
        mock_db.return_value = {
            "healthy": True,
            "connection": "ok",
            "document_count": 25,
            "response_time_ms": 15
        }

        # Vector store initialisé
        mock_vector.return_value = {
            "healthy": True,
            "index_file": "exists",
            "metadata_file": "exists"
        }

        # LLM configuré
        mock_llm.return_value = {
            "healthy": True,
            "api_configured": True,
            "provider": "mistral",
            "model": "mistral-small-latest"
        }

        # Cache fonctionnel
        mock_cache.return_value = {
            "healthy": True,
            "test": "passed",
            "main_cache": {"hits": 150, "misses": 30},
            "chat_cache": {"hits": 80, "misses": 15}
        }

        # Email configuré
        mock_email.return_value = {
            "healthy": True,
            "configuration": {"configured": True}
        }

        mock_db_session = Mock()

        # Appel du health check
        result = asyncio.run(health_check(response=Response(), db=mock_db_session))

        # Vérifications complètes
        assert result.status == "healthy"
        assert len(result.checks) == 5
        assert all(check["healthy"] for check in result.checks.values())
        assert not hasattr(result, 'unhealthy_components')