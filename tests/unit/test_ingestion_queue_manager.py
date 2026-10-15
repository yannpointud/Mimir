"""
Tests unitaires pour les modèles de tâches d'ingestion
"""

from datetime import datetime

from src.ingestion.queue_manager import IngestionTask


class TestIngestionTask:
    """Tests pour la classe IngestionTask"""

    def test_task_creation(self):
        """Test de création d'une tâche"""
        task = IngestionTask(
            file_path="/test/file.txt",
            document_id="doc123"
        )

        assert task.file_path == "/test/file.txt"
        assert task.document_id == "doc123"
        assert task.retry_count == 0
        assert task.max_retries == 3
        assert isinstance(task.created_at, datetime)
        assert task.metadata == {}

    def test_task_with_metadata(self):
        """Test avec métadonnées"""
        metadata = {"user": "admin", "batch": "morning"}
        task = IngestionTask(
            file_path="/test/file.txt",
            document_id="doc123",
            metadata=metadata
        )

        assert task.metadata == metadata

    def test_can_retry(self):
        """Test de vérification de possibilité de retry"""
        task = IngestionTask(
            file_path="/test.txt",
            document_id="doc",
            max_retries=2
        )

        assert task.can_retry() is True

        task.retry_count = 1
        assert task.can_retry() is True

        task.retry_count = 2
        assert task.can_retry() is False

    def test_increment_retry(self):
        """Test d'incrémentation des retries"""
        task = IngestionTask(
            file_path="/test.txt",
            document_id="doc"
        )

        task.increment_retry()

        assert task.retry_count == 1
