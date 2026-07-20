"""
Unit tests for the admin document upload endpoint (phase 02, it. 2).

Covers the input-validation parity with /documents/upload (WR-01: max file
size and empty-file rejection) added by the review-fix pass.
"""

import asyncio
import tempfile

import pytest
from unittest.mock import Mock, AsyncMock, patch
from fastapi import HTTPException, status, UploadFile

from backend.src.api.endpoints.admin import admin_upload_document


@pytest.fixture
def mock_upload_file():
    """Mock uploaded file with a valid name and a small size."""
    mock_file = Mock(spec=UploadFile)
    mock_file.filename = "test.pdf"
    mock_file.size = 1024  # 1KB
    return mock_file


@pytest.fixture
def temp_upload_dir():
    """Real temporary directory used as upload_dir."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


def _run_admin_upload(mock_file, ingestion_processor=None):
    """Call the endpoint function directly (same pattern as documents tests)."""
    return asyncio.run(admin_upload_document(
        request=Mock(),  # required by slowapi decorator
        response=Mock(),  # required by slowapi header injection
        file=mock_file,
        preserve=False,
        current_user={"username": "admin", "user_type": "admin"},
        ingestion_processor=ingestion_processor or Mock()
    ))


class TestAdminUploadInputValidation:
    """WR-01: size and empty-file guards, parity with /documents/upload."""

    @patch('backend.src.api.endpoints.admin.settings')
    def test_admin_upload_file_too_large_returns_413(
        self, mock_settings, mock_upload_file
    ):
        """A file above max_file_size_mb is rejected with 413 before read()."""
        mock_settings.max_file_size_mb = 5
        mock_upload_file.size = 10 * 1024 * 1024  # 10MB > 5MB limit
        mock_upload_file.read = AsyncMock(
            side_effect=AssertionError("read() must not be called for oversized files")
        )

        with pytest.raises(HTTPException) as exc_info:
            _run_admin_upload(mock_upload_file)

        assert exc_info.value.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert "File too large" in str(exc_info.value.detail)

    @patch('src.database.repository.DocumentRepository')
    @patch('src.database.connection.get_db_session')
    @patch('backend.src.api.endpoints.admin.settings')
    def test_admin_upload_empty_file_returns_400(
        self, mock_settings, mock_get_db_session, mock_repo_cls,
        mock_upload_file, temp_upload_dir
    ):
        """An empty file is rejected with 400 and never persisted."""
        mock_settings.max_file_size_mb = 10
        mock_settings.upload_dir = temp_upload_dir
        mock_get_db_session.return_value = iter([Mock()])
        mock_repo = Mock()
        mock_repo_cls.return_value = mock_repo

        mock_upload_file.read = AsyncMock(return_value=b"")  # Empty file

        with pytest.raises(HTTPException) as exc_info:
            _run_admin_upload(mock_upload_file)

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "Empty file" in str(exc_info.value.detail)
        mock_repo.create.assert_not_called()


class TestAdminUploadQueueFullCleanup:
    """WR-03 (it. 2): on queue-full 503, the pending DB record and the stored
    file must be rolled back, otherwise any retry of the same file hits 409
    (get_by_hash matches the orphaned pending record) and is never ingested."""

    @patch('src.database.repository.DocumentRepository')
    @patch('src.database.connection.get_db_session')
    @patch('backend.src.api.endpoints.admin.settings')
    def test_admin_upload_queue_full_deletes_record_and_file(
        self, mock_settings, mock_get_db_session, mock_repo_cls,
        mock_upload_file, temp_upload_dir
    ):
        """queue_document() == False -> 503 + record deleted + file removed."""
        import hashlib
        from pathlib import Path

        mock_settings.max_file_size_mb = 10
        mock_settings.upload_dir = temp_upload_dir
        mock_get_db_session.return_value = iter([Mock()])

        content = b"admin queue full test content"
        mock_upload_file.read = AsyncMock(return_value=content)
        file_hash = hashlib.sha256(content).hexdigest()
        expected_path = Path(temp_upload_dir) / f"{file_hash}_test.pdf"

        mock_repo = Mock()
        mock_repo.get_by_hash.return_value = None
        mock_repo.create.return_value = Mock(id=3)
        mock_repo_cls.return_value = mock_repo

        mock_ingestion = Mock()
        mock_ingestion.queue_document.return_value = False  # Queue is full
        mock_ingestion.get_queue_size.return_value = 100

        with pytest.raises(HTTPException) as exc_info:
            _run_admin_upload(mock_upload_file, ingestion_processor=mock_ingestion)

        assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        mock_repo.delete.assert_called_once_with(3, force=True)
        assert not expected_path.exists(), \
            "stored file must be removed on queue-full rejection"
