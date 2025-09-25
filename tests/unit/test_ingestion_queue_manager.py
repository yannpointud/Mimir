"""
Tests unitaires pour les modèles de tâches d'ingestion
"""

import pytest
import time
from datetime import datetime

from src.ingestion.queue_manager import (
    IngestionTask, TaskPriority
)


class TestTaskPriority:
    """Tests pour l'énumération TaskPriority"""

    def test_priority_values(self):
        """Test des valeurs de priorité"""
        assert TaskPriority.URGENT.value == 1
        assert TaskPriority.HIGH.value == 2
        assert TaskPriority.NORMAL.value == 3
        assert TaskPriority.LOW.value == 4

    def test_priority_ordering(self):
        """Test de l'ordre des priorités"""
        assert TaskPriority.URGENT < TaskPriority.HIGH
        assert TaskPriority.HIGH < TaskPriority.NORMAL
        assert TaskPriority.NORMAL < TaskPriority.LOW


class TestIngestionTask:
    """Tests pour la classe IngestionTask"""

    def test_task_creation(self):
        """Test de création d'une tâche"""
        task = IngestionTask(
            file_path="/test/file.txt",
            document_id="doc123",
            priority=TaskPriority.HIGH
        )

        assert task.file_path == "/test/file.txt"
        assert task.document_id == "doc123"
        assert task.priority == TaskPriority.HIGH
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

    def test_task_priority_conversion(self):
        """Test de conversion de priorité depuis int"""
        task = IngestionTask(
            file_path="/test/file.txt",
            document_id="doc123",
            priority=2  # Should become TaskPriority.HIGH
        )

        assert task.priority == TaskPriority.HIGH
        assert isinstance(task.priority, TaskPriority)

    def test_task_comparison(self):
        """Test de comparaison des tâches pour la priority queue"""
        task_urgent = IngestionTask(
            file_path="/urgent.txt",
            document_id="urgent",
            priority=TaskPriority.URGENT
        )

        time.sleep(0.001)  # Assurer une différence de temps

        task_normal = IngestionTask(
            file_path="/normal.txt",
            document_id="normal",
            priority=TaskPriority.NORMAL
        )

        # URGENT doit être prioritaire sur NORMAL
        assert task_urgent < task_normal

        # Test avec même priorité - l'ancienne tâche a priorité
        task_normal2 = IngestionTask(
            file_path="/normal2.txt",
            document_id="normal2",
            priority=TaskPriority.NORMAL
        )

        assert task_normal < task_normal2

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
            document_id="doc",
            priority=TaskPriority.LOW
        )

        original_priority = task.priority
        task.increment_retry()

        assert task.retry_count == 1
        # La priorité doit s'améliorer (valeur plus faible)
        assert task.priority.value < original_priority.value

    def test_retry_priority_cap(self):
        """Test que la priorité ne dépasse pas URGENT"""
        task = IngestionTask(
            file_path="/test.txt",
            document_id="doc",
            priority=TaskPriority.URGENT
        )

        task.increment_retry()

        # Doit rester URGENT
        assert task.priority == TaskPriority.URGENT