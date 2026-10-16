"""
Unit tests of the ingestion task models
"""

from datetime import datetime

from mimir.ingestion.queue_manager import IngestionTask


class TestIngestionTask:
    """IngestionTask tests"""

    def test_task_creation(self):
        task = IngestionTask(file_path="/test/file.txt", document_id="doc123")

        assert task.file_path == "/test/file.txt"
        assert task.document_id == "doc123"
        assert task.retry_count == 0
        assert task.max_retries == 3
        assert isinstance(task.created_at, datetime)
        assert task.metadata == {}

    def test_task_with_metadata(self):
        metadata = {"user": "admin", "batch": "morning"}
        task = IngestionTask(file_path="/test/file.txt", document_id="doc123", metadata=metadata)

        assert task.metadata == metadata

    def test_can_retry(self):
        task = IngestionTask(file_path="/test.txt", document_id="doc", max_retries=2)

        assert task.can_retry() is True

        task.retry_count = 1
        assert task.can_retry() is True

        task.retry_count = 2
        assert task.can_retry() is False

    def test_increment_retry(self):
        task = IngestionTask(file_path="/test.txt", document_id="doc")

        task.increment_retry()

        assert task.retry_count == 1
