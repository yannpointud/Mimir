"""
Unit tests for document management endpoints.
"""

import pytest

from mimir.shared.errors import NotFoundError
import asyncio
import tempfile
from unittest.mock import Mock, patch, AsyncMock, mock_open
from datetime import datetime
from pathlib import Path
from fastapi import HTTPException, status, UploadFile

from mimir.api.endpoints.documents import (
    list_documents,
    get_document,
    upload_document,
    delete_document,
    toggle_document_preservation,
    reprocess_document,
    get_document_stats,
)


@patch(
    "mimir.shared.models.DocumentResponse.from_orm",
    side_effect=lambda obj: Mock(
        id=getattr(obj, "id", 1),
        filename=getattr(obj, "filename", "test.pdf"),
        status=getattr(obj, "status", "indexed"),
        path=getattr(obj, "path", "/test"),
        preserve=getattr(obj, "preserve", False),
        file_hash=getattr(obj, "file_hash", "a" * 64),
        error_message=getattr(obj, "error_message", None),
        chunk_count=getattr(obj, "chunk_count", 5),
        created_at=getattr(obj, "created_at", datetime.utcnow()),
        indexed_at=getattr(obj, "indexed_at", datetime.utcnow()),
    ),
)
class TestDocumentEndpoints:
    """Tests for document endpoints."""

    def create_mock_document(self, **kwargs):
        """Create a mock document with all required attributes."""
        mock_doc = Mock()

        # Default values
        defaults = {
            "id": 1,
            "filename": "test.pdf",
            "path": "/uploads/test.pdf",
            "preserve": False,
            "file_hash": "a" * 64,  # 64-character hexadecimal hash
            "status": "indexed",
            "error_message": None,
            "chunk_count": 5,
            "created_at": datetime.utcnow(),
            "indexed_at": datetime.utcnow(),
        }

        # Merge with provided kwargs
        defaults.update(kwargs)

        # Assign all attributes
        for key, value in defaults.items():
            setattr(mock_doc, key, value)

        return mock_doc

    @pytest.fixture
    def mock_doc_repo(self):
        """Mock document repository."""
        return Mock()

    @pytest.fixture
    def mock_audit_repo(self):
        """Mock audit repository."""
        return Mock()

    @pytest.fixture
    def mock_current_user(self):
        """Mock authenticated user."""
        return {"sub": "admin", "user_type": "admin"}

    @pytest.fixture
    def mock_pagination(self):
        """Mock pagination parameters."""
        mock_pagination = Mock()
        mock_pagination.offset = 0
        mock_pagination.limit = 20
        return mock_pagination


class TestListDocumentsEndpoint(TestDocumentEndpoints):
    """Tests for the document listing endpoint."""

    @patch("mimir.api.endpoints.documents.DocumentListResponse")
    def test_list_documents_success(self, mock_doc_list_response, mock_doc_repo, mock_pagination):
        """Test successful document listing."""

        # Configure mocks with all required attributes
        mock_doc1 = self.create_mock_document(
            id=1,
            filename="doc1.pdf",
            status="indexed",
            path="/uploads/doc1.pdf",
            preserve=False,
            file_hash="b" * 64,
            chunk_count=5,
        )

        mock_doc2 = self.create_mock_document(
            id=2,
            filename="doc2.txt",
            status="indexing",
            path="/uploads/doc2.txt",
            preserve=True,
            file_hash="c" * 64,
            chunk_count=0,
            indexed_at=None,
        )

        mock_documents = [mock_doc1, mock_doc2]
        mock_doc_repo.get_all_paginated.return_value = (mock_documents, 2)

        # Mock response to avoid inconsistent Pydantic validation
        mock_response = Mock()
        mock_response.documents = []  # Will be populated after DocumentResponse.from_orm()
        mock_response.total_count = 2
        mock_response.pagination = {"offset": 0, "limit": 20, "has_more": False}
        mock_doc_list_response.return_value = mock_response

        # Call the function
        result = asyncio.run(
            list_documents(
                pagination=mock_pagination, status_filter=None, search=None, doc_repo=mock_doc_repo
            )
        )

        # Assertions
        assert result == mock_response
        mock_doc_list_response.assert_called_once()

    @patch("mimir.api.endpoints.documents.DocumentListResponse")
    def test_list_documents_with_filters(
        self, mock_doc_list_response, mock_doc_repo, mock_pagination
    ):
        """Test listing with filters."""

        # Configure mocks
        mock_documents = [self.create_mock_document(id=1, filename="doc1.pdf", status="indexed")]
        mock_doc_repo.get_all_paginated.return_value = (mock_documents, 1)

        # Mock response
        mock_response = Mock()
        mock_response.documents = []
        mock_response.total_count = 1
        mock_doc_list_response.return_value = mock_response

        # Call the function
        result = asyncio.run(
            list_documents(
                pagination=mock_pagination,
                status_filter="indexed",
                search="doc1",
                doc_repo=mock_doc_repo,
            )
        )

        # Assertions
        assert result == mock_response
        mock_doc_repo.get_all_paginated.assert_called_once_with(
            offset=0, limit=20, filters={"status": "indexed"}, search="doc1"
        )

    @patch("mimir.api.endpoints.documents.DocumentListResponse")
    def test_list_documents_pagination(self, mock_doc_list_response, mock_doc_repo):
        """Test listing with pagination."""

        # Configure mocks
        mock_pagination = Mock()
        mock_pagination.offset = 20
        mock_pagination.limit = 10

        mock_documents = [
            self.create_mock_document(id=i, filename=f"doc{i}.pdf") for i in range(21, 31)
        ]
        mock_doc_repo.get_all_paginated.return_value = (mock_documents, 50)

        # Mock response
        mock_response = Mock()
        mock_response.documents = []
        mock_response.total_count = 50
        mock_response.pagination = {"offset": 20, "limit": 10, "has_more": True}
        mock_doc_list_response.return_value = mock_response

        # Call the function
        result = asyncio.run(
            list_documents(
                pagination=mock_pagination, status_filter=None, search=None, doc_repo=mock_doc_repo
            )
        )

        # Assertions
        assert result == mock_response


class TestGetDocumentEndpoint(TestDocumentEndpoints):
    """Tests for the document retrieval endpoint."""

    def test_get_document_success(self, mock_doc_repo):
        """Test successful document retrieval."""

        # Configure mock
        mock_document = self.create_mock_document(id=1, filename="test.pdf", status="indexed")
        mock_doc_repo.get_by_id.return_value = mock_document

        # Call the function
        asyncio.run(get_document(document_id=1, doc_repo=mock_doc_repo))

        # Assertions
        mock_doc_repo.get_by_id.assert_called_once_with(1)
        # Result will be converted by DocumentResponse.from_orm()

    def test_get_document_not_found(self, mock_doc_repo):
        """Test document not found retrieval."""

        # Configure mock
        mock_doc_repo.get_by_id.return_value = None

        # Test that exception is raised
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(get_document(document_id=999, doc_repo=mock_doc_repo))

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert "999" in str(exc_info.value.detail)


class TestUploadDocumentEndpoint(TestDocumentEndpoints):
    """Tests for the document upload endpoint."""

    @pytest.fixture
    def mock_upload_file(self):
        """Mock uploaded file."""
        mock_file = Mock(spec=UploadFile)
        mock_file.filename = "test.pdf"
        mock_file.size = 1024 * 1024  # 1MB
        return mock_file

    @pytest.fixture
    def temp_upload_dir(self):
        """Temporary directory for upload tests."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir

    @patch("mimir.api.endpoints.documents.settings")
    @patch("mimir.services.document_upload.Path")
    @patch("mimir.services.document_upload.hashlib.sha256")
    @patch("mimir.services.document_upload.validate_filename")
    @patch("mimir.services.document_upload.sanitize_filename")
    def test_upload_document_success(
        self,
        mock_sanitize,
        mock_validate,
        mock_sha256,
        mock_path,
        mock_settings,
        mock_upload_file,
        mock_doc_repo,
        mock_audit_repo,
        mock_current_user,
    ):
        """Test successful document upload."""

        # Configure mocks
        mock_settings.max_file_size_mb = 10
        mock_settings.supported_file_extensions = {".pdf", ".txt", ".docx"}
        mock_settings.upload_dir = "/uploads"

        mock_validate.return_value = True
        mock_sanitize.return_value = "test.pdf"

        mock_upload_file.read = AsyncMock(return_value=b"file_content")

        mock_hash = Mock()
        mock_hash.hexdigest.return_value = "abc123def456"
        mock_sha256.return_value = mock_hash

        mock_doc_repo.get_by_hash.return_value = None  # No duplicate
        mock_document = self.create_mock_document(id=1, filename="test.pdf")
        mock_doc_repo.create.return_value = mock_document

        # Configure path mock to handle different use cases
        def path_side_effect(path_arg):
            if str(path_arg) == "test.pdf":  # For Path(safe_filename) - name must match
                mock_file_path = Mock()
                mock_file_path.suffix.lower.return_value = ".pdf"
                return mock_file_path
            elif str(path_arg) == "/uploads":  # For Path(settings.upload_dir)
                mock_upload_dir = Mock()
                mock_upload_dir.mkdir = Mock()
                # Configure / operator to return a valid file path
                mock_file_path = Mock()
                mock_file_path.__str__ = Mock(return_value="/uploads/abc123def456_test.pdf")
                mock_upload_dir.__truediv__ = Mock(return_value=mock_file_path)
                return mock_upload_dir
            else:  # Other cases
                mock_other_path = Mock()
                mock_other_path.mkdir = Mock()
                return mock_other_path

        mock_path.side_effect = path_side_effect

        # Mock ingestion processor
        mock_ingestion_processor = Mock()
        mock_ingestion_processor.queue_document.return_value = True

        # Call the function
        with patch("builtins.open", mock_open()):
            asyncio.run(
                upload_document(
                    request=Mock(),  # required by slowapi decorator
                    response=Mock(),  # required by slowapi header injection
                    file=mock_upload_file,
                    preserve=False,
                    current_user=mock_current_user,
                    doc_repo=mock_doc_repo,
                    audit_repo=mock_audit_repo,
                    ingestion_processor=mock_ingestion_processor,
                )
            )

        # Assertions
        mock_validate.assert_called_once_with("test.pdf")
        mock_sanitize.assert_called_once_with("test.pdf")
        mock_doc_repo.get_by_hash.assert_called_once_with("abc123def456")
        mock_doc_repo.create.assert_called_once()
        mock_audit_repo.create_log.assert_called_once()

    def test_upload_document_no_filename(self, mock_doc_repo, mock_audit_repo, mock_current_user):
        """Test upload without filename."""

        mock_file = Mock(spec=UploadFile)
        mock_file.filename = None

        # Test that exception is raised
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                upload_document(
                    request=Mock(),  # required by slowapi decorator
                    response=Mock(),  # required by slowapi header injection
                    file=mock_file,
                    preserve=False,
                    current_user=mock_current_user,
                    doc_repo=mock_doc_repo,
                    audit_repo=mock_audit_repo,
                )
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "No filename" in str(exc_info.value.detail)

    @patch("mimir.services.document_upload.validate_filename")
    def test_upload_document_invalid_filename(
        self, mock_validate, mock_upload_file, mock_doc_repo, mock_audit_repo, mock_current_user
    ):
        """Test upload with invalid filename."""

        mock_validate.return_value = False

        # Test that exception is raised
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                upload_document(
                    request=Mock(),  # required by slowapi decorator
                    response=Mock(),  # required by slowapi header injection
                    file=mock_upload_file,
                    preserve=False,
                    current_user=mock_current_user,
                    doc_repo=mock_doc_repo,
                    audit_repo=mock_audit_repo,
                )
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid filename" in str(exc_info.value.detail)

    @patch("mimir.api.endpoints.documents.settings")
    @patch("mimir.services.document_upload.validate_filename")
    def test_upload_document_file_too_large(
        self,
        mock_validate,
        mock_settings,
        mock_upload_file,
        mock_doc_repo,
        mock_audit_repo,
        mock_current_user,
    ):
        """Test upload with file too large."""

        mock_settings.max_file_size_mb = 5
        mock_validate.return_value = True
        mock_upload_file.size = 10 * 1024 * 1024  # 10MB

        # Test that exception is raised
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                upload_document(
                    request=Mock(),  # required by slowapi decorator
                    response=Mock(),  # required by slowapi header injection
                    file=mock_upload_file,
                    preserve=False,
                    current_user=mock_current_user,
                    doc_repo=mock_doc_repo,
                    audit_repo=mock_audit_repo,
                )
            )

        assert exc_info.value.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert "File too large" in str(exc_info.value.detail)

    @patch("mimir.api.endpoints.documents.settings")
    @patch("mimir.services.document_upload.validate_filename")
    @patch("mimir.services.document_upload.sanitize_filename")
    def test_upload_document_unsupported_extension(
        self,
        mock_sanitize,
        mock_validate,
        mock_settings,
        mock_upload_file,
        mock_doc_repo,
        mock_audit_repo,
        mock_current_user,
    ):
        """Test upload with unsupported extension."""

        mock_settings.max_file_size_mb = 10
        mock_settings.supported_file_extensions = {".pdf", ".txt"}
        mock_validate.return_value = True
        mock_sanitize.return_value = "test.xyz"

        # Test that exception is raised
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                upload_document(
                    request=Mock(),  # required by slowapi decorator
                    response=Mock(),  # required by slowapi header injection
                    file=mock_upload_file,
                    preserve=False,
                    current_user=mock_current_user,
                    doc_repo=mock_doc_repo,
                    audit_repo=mock_audit_repo,
                )
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "Unsupported file type" in str(exc_info.value.detail)

    @patch("mimir.api.endpoints.documents.settings")
    @patch("mimir.services.document_upload.validate_filename")
    @patch("mimir.services.document_upload.sanitize_filename")
    def test_upload_document_empty_file(
        self,
        mock_sanitize,
        mock_validate,
        mock_settings,
        mock_upload_file,
        mock_doc_repo,
        mock_audit_repo,
        mock_current_user,
    ):
        """Test upload with empty file."""

        mock_settings.max_file_size_mb = 10
        mock_settings.supported_file_extensions = {".pdf"}
        mock_validate.return_value = True
        mock_sanitize.return_value = "test.pdf"
        mock_upload_file.read = AsyncMock(return_value=b"")  # Empty file

        # Test that exception is raised
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                upload_document(
                    request=Mock(),  # required by slowapi decorator
                    response=Mock(),  # required by slowapi header injection
                    file=mock_upload_file,
                    preserve=False,
                    current_user=mock_current_user,
                    doc_repo=mock_doc_repo,
                    audit_repo=mock_audit_repo,
                )
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "Empty file" in str(exc_info.value.detail)

    @patch("mimir.api.endpoints.documents.settings")
    @patch("mimir.services.document_upload.validate_filename")
    @patch("mimir.services.document_upload.sanitize_filename")
    @patch("mimir.services.document_upload.hashlib.sha256")
    def test_upload_document_duplicate(
        self,
        mock_sha256,
        mock_sanitize,
        mock_validate,
        mock_settings,
        mock_upload_file,
        mock_doc_repo,
        mock_audit_repo,
        mock_current_user,
    ):
        """Test upload with duplicate file."""

        mock_settings.max_file_size_mb = 10
        mock_settings.supported_file_extensions = {".pdf"}
        mock_validate.return_value = True
        mock_sanitize.return_value = "test.pdf"
        mock_upload_file.read = AsyncMock(return_value=b"file_content")

        mock_hash = Mock()
        mock_hash.hexdigest.return_value = "abc123def456"
        mock_sha256.return_value = mock_hash

        # Existing document with same hash
        existing_doc = self.create_mock_document(filename="existing.pdf")
        mock_doc_repo.get_by_hash.return_value = existing_doc

        # Test that exception is raised
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                upload_document(
                    request=Mock(),  # required by slowapi decorator
                    response=Mock(),  # required by slowapi header injection
                    file=mock_upload_file,
                    preserve=False,
                    current_user=mock_current_user,
                    doc_repo=mock_doc_repo,
                    audit_repo=mock_audit_repo,
                )
            )

        assert exc_info.value.status_code == status.HTTP_409_CONFLICT
        assert "already exists" in str(exc_info.value.detail)


class TestDeleteDocumentEndpoint(TestDocumentEndpoints):
    """Tests for the document deletion endpoint."""

    def test_delete_document_success(self, mock_doc_repo, mock_audit_repo, mock_current_user):
        """Test successful document deletion."""

        # Configure mocks
        mock_document = Mock(
            id=1, filename="test.pdf", path="/uploads/abc123_test.pdf", preserve=False
        )
        mock_doc_repo.get_by_id.return_value = mock_document
        mock_doc_repo.delete.return_value = True

        with (
            patch("mimir.api.endpoints.documents.os.path.exists") as mock_exists,
            patch("mimir.api.endpoints.documents.os.remove") as mock_remove,
        ):
            mock_exists.return_value = True

            # Call the function
            result = asyncio.run(
                delete_document(
                    document_id=1,
                    force=False,
                    current_user=mock_current_user,
                    doc_repo=mock_doc_repo,
                    audit_repo=mock_audit_repo,
                )
            )

        # Assertions
        assert result.success is True
        assert "test.pdf" in result.message
        mock_doc_repo.delete.assert_called_once_with(1, force=False)
        mock_remove.assert_called_once_with("/uploads/abc123_test.pdf")
        mock_audit_repo.create_log.assert_called_once()

    def test_delete_document_not_found(self, mock_doc_repo, mock_audit_repo, mock_current_user):
        """Test deletion of non-existent document."""

        # Configure mock
        mock_doc_repo.get_by_id.return_value = None

        # Test that exception is raised
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                delete_document(
                    document_id=999,
                    force=False,
                    current_user=mock_current_user,
                    doc_repo=mock_doc_repo,
                    audit_repo=mock_audit_repo,
                )
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_document_protected_without_force(
        self, mock_doc_repo, mock_audit_repo, mock_current_user
    ):
        """Test deletion of protected document without force."""

        # Configure mocks
        mock_document = Mock(id=1, filename="protected.pdf", preserve=True)
        mock_doc_repo.get_by_id.return_value = mock_document

        # Test that exception is raised
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                delete_document(
                    document_id=1,
                    force=False,
                    current_user=mock_current_user,
                    doc_repo=mock_doc_repo,
                    audit_repo=mock_audit_repo,
                )
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "protected" in str(exc_info.value.detail)

    def test_delete_document_protected_with_force(
        self, mock_doc_repo, mock_audit_repo, mock_current_user
    ):
        """Test deletion of protected document with force."""

        # Configure mocks
        mock_document = Mock(
            id=1, filename="protected.pdf", path="/uploads/abc123_protected.pdf", preserve=True
        )
        mock_doc_repo.get_by_id.return_value = mock_document
        mock_doc_repo.delete.return_value = True

        with (
            patch("mimir.api.endpoints.documents.os.path.exists") as mock_exists,
            patch("mimir.api.endpoints.documents.os.remove"),
        ):
            mock_exists.return_value = True

            # Call the function
            result = asyncio.run(
                delete_document(
                    document_id=1,
                    force=True,
                    current_user=mock_current_user,
                    doc_repo=mock_doc_repo,
                    audit_repo=mock_audit_repo,
                )
            )

        # Assertions
        assert result.success is True
        mock_doc_repo.delete.assert_called_once_with(1, force=True)

    def test_delete_document_database_failure(
        self, mock_doc_repo, mock_audit_repo, mock_current_user
    ):
        """Test deletion with database failure."""

        # Configure mocks
        mock_document = Mock(id=1, filename="test.pdf", preserve=False)
        mock_doc_repo.get_by_id.return_value = mock_document
        mock_doc_repo.delete.return_value = False  # Failure

        # Test that exception is raised
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                delete_document(
                    document_id=1,
                    force=False,
                    current_user=mock_current_user,
                    doc_repo=mock_doc_repo,
                    audit_repo=mock_audit_repo,
                )
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


class TestToggleDocumentPreservationEndpoint(TestDocumentEndpoints):
    """Tests for the preservation toggle endpoint."""

    def test_toggle_document_preservation_success(
        self, mock_doc_repo, mock_audit_repo, mock_current_user
    ):
        """Test successful preservation toggle."""

        # Configure mocks
        mock_document = self.create_mock_document(id=1, filename="test.pdf")
        mock_doc_repo.get_by_id.return_value = mock_document

        updated_doc = self.create_mock_document(id=1, filename="test.pdf", preserve=True)
        mock_doc_repo.update_preserve_status.return_value = updated_doc

        # Call the function
        asyncio.run(
            toggle_document_preservation(
                document_id=1,
                preserve=True,
                current_user=mock_current_user,
                doc_repo=mock_doc_repo,
                audit_repo=mock_audit_repo,
            )
        )

        # Assertions
        mock_doc_repo.update_preserve_status.assert_called_once_with(1, True)
        mock_audit_repo.create_log.assert_called_once()

    def test_toggle_document_preservation_not_found(
        self, mock_doc_repo, mock_audit_repo, mock_current_user
    ):
        """Test toggle on non-existent document."""

        mock_doc_repo.update_preserve_status.side_effect = NotFoundError("Document 999 not found")

        with pytest.raises(NotFoundError):
            asyncio.run(
                toggle_document_preservation(
                    document_id=999,
                    preserve=True,
                    current_user=mock_current_user,
                    doc_repo=mock_doc_repo,
                    audit_repo=mock_audit_repo,
                )
            )
        mock_audit_repo.create_log.assert_not_called()


class TestReprocessDocumentEndpoint(TestDocumentEndpoints):
    """Tests for the document reprocessing endpoint."""

    def test_reprocess_document_success(self, mock_doc_repo, mock_audit_repo, mock_current_user):
        """Test successful document reprocessing."""

        # Configure mocks
        mock_document = Mock(id=1, filename="test.pdf")
        mock_doc_repo.get_by_id.return_value = mock_document

        # Mock ingestion processor
        mock_ingestion_processor = Mock()
        mock_ingestion_processor.queue_document.return_value = True

        # Call the function
        result = asyncio.run(
            reprocess_document(
                document_id=1,
                current_user=mock_current_user,
                doc_repo=mock_doc_repo,
                audit_repo=mock_audit_repo,
                ingestion_processor=mock_ingestion_processor,
            )
        )

        # Assertions
        assert result.success is True
        assert "test.pdf" in result.message
        assert "reprocessing" in result.message
        mock_doc_repo.update_status.assert_called_once_with(1, "pending", error_message=None)
        mock_audit_repo.create_log.assert_called_once()

    def test_reprocess_document_not_found(self, mock_doc_repo, mock_audit_repo, mock_current_user):
        """Test reprocessing of non-existent document."""

        # Configure mock
        mock_doc_repo.get_by_id.return_value = None

        # Test that exception is raised
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                reprocess_document(
                    document_id=999,
                    current_user=mock_current_user,
                    doc_repo=mock_doc_repo,
                    audit_repo=mock_audit_repo,
                )
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestGetDocumentStatsEndpoint(TestDocumentEndpoints):
    """Tests for the document statistics endpoint."""

    @patch("mimir.api.endpoints.documents.settings")
    def test_get_document_stats_success(self, mock_settings, mock_doc_repo):
        """Test successful statistics retrieval."""

        # Configure mocks
        mock_settings.upload_dir = "/uploads"
        mock_settings.supported_file_extensions = {".pdf", ".txt", ".docx"}
        mock_settings.max_file_size_mb = 10

        # Corrected to match keys used by production code
        mock_stats = {
            "total_documents": 25,
            "count_pending": 0,
            "count_indexing": 3,
            "count_indexed": 20,
            "count_error": 2,
            "total_chunks": 150,
            "protected_documents": 5,
        }
        mock_doc_repo.get_statistics.return_value = mock_stats

        # Mock vector store
        mock_vector_store = Mock()
        mock_vector_store.get_stats.return_value = {
            "total_vectors": 150,
            "active_vectors": 140,
            "deleted_vectors": 10,
            "total_documents": 25,
            "memory_usage_mb": 12.5,
        }
        mock_vector_store.health_check.return_value = True

        # Call the function
        result = asyncio.run(
            get_document_stats(doc_repo=mock_doc_repo, vector_store=mock_vector_store)
        )

        # Assertions
        assert result.total_documents == 25
        assert result.by_status.indexed == 20
        assert result.by_status.indexing == 3
        assert result.by_status.error == 2
        assert result.total_chunks == 150
        assert result.preserved_documents == 5
        assert result.storage_info.upload_directory == "/uploads"
        assert result.storage_info.max_file_size_mb == 10


class TestDocumentIntegration(TestDocumentEndpoints):
    """Integration tests for document endpoints."""

    def test_full_document_lifecycle(self, mock_doc_repo, mock_audit_repo, mock_current_user):
        """Test full document lifecycle (simplified version)."""

        # Mock created document
        mock_document = self.create_mock_document(
            id=1,
            filename="document.pdf",
            path="/uploads/abc123def456_document.pdf",
            preserve=False,
            status="pending",
        )

        # Configure repo returns
        mock_doc_repo.get_by_id.return_value = mock_document
        mock_doc_repo.update_preserve_status.return_value = self.create_mock_document(
            id=1, filename="document.pdf", preserve=True
        )
        mock_doc_repo.delete.return_value = True

        # Required mock ingestion processor
        mock_ingestion_processor = Mock()
        mock_ingestion_processor.queue_document.return_value = True

        # Required mock vector store for delete_document
        mock_vector_store = Mock()
        mock_vector_store.delete.return_value = True

        # 1. Document retrieval (skip upload as too complex to mock)
        get_result = asyncio.run(get_document(document_id=1, doc_repo=mock_doc_repo))

        # 2. Preservation toggle
        preserve_result = asyncio.run(
            toggle_document_preservation(
                document_id=1,
                preserve=True,
                current_user=mock_current_user,
                doc_repo=mock_doc_repo,
                audit_repo=mock_audit_repo,
            )
        )

        # 3. Reprocessing
        reprocess_result = asyncio.run(
            reprocess_document(
                document_id=1,
                current_user=mock_current_user,
                doc_repo=mock_doc_repo,
                audit_repo=mock_audit_repo,
                ingestion_processor=mock_ingestion_processor,
            )
        )

        # 4. Forced deletion (because protected)
        with (
            patch("mimir.api.endpoints.documents.os.path.exists") as mock_exists,
            patch("mimir.api.endpoints.documents.os.remove"),
        ):
            mock_exists.return_value = True
            mock_document.preserve = True  # Document now protected

            delete_result = asyncio.run(
                delete_document(
                    document_id=1,
                    force=True,
                    current_user=mock_current_user,
                    doc_repo=mock_doc_repo,
                    audit_repo=mock_audit_repo,
                    vector_store=mock_vector_store,
                )
            )

        # Full cycle assertions
        assert get_result is not None  # Retrieval successful
        assert preserve_result is not None  # Preservation successful
        assert reprocess_result.success is True  # Reprocessing successful
        assert delete_result.success is True  # Deletion successful

        # Verify audit calls (3 actions: preserve, reprocess, delete)
        assert mock_audit_repo.create_log.call_count == 3

    def test_document_upload_and_stats_workflow(
        self, mock_doc_repo, mock_audit_repo, mock_current_user
    ):
        """Test upload and statistics workflow."""

        # Corrected to match keys used by production code
        mock_stats = {
            "total_documents": 1,
            "count_pending": 1,
            "count_indexing": 0,
            "count_indexed": 0,
            "count_error": 0,
            "total_chunks": 0,
            "protected_documents": 0,
        }
        mock_doc_repo.get_statistics.return_value = mock_stats

        # Mock vector store
        mock_vector_store = Mock()
        mock_vector_store.get_stats.return_value = {
            "total_vectors": 0,
            "active_vectors": 0,
            "deleted_vectors": 0,
            "total_documents": 0,
            "memory_usage_mb": 0,
        }
        mock_vector_store.health_check.return_value = True

        with patch("mimir.api.endpoints.documents.settings") as mock_settings:
            mock_settings.upload_dir = "/uploads"
            mock_settings.supported_file_extensions = {".pdf", ".txt"}
            mock_settings.max_file_size_mb = 10

            # Retrieve statistics
            stats_result = asyncio.run(
                get_document_stats(doc_repo=mock_doc_repo, vector_store=mock_vector_store)
            )

        # Assertions
        assert stats_result.total_documents == 1
        assert stats_result.by_status.pending == 1
        assert stats_result.total_chunks == 0
        assert stats_result.storage_info.max_file_size_mb == 10

    @patch("mimir.api.endpoints.documents.FileResponse")
    def test_download_document_success(self, mock_file_response, mock_doc_repo):
        """Test successful document download."""
        # Mock document
        mock_doc = self.create_mock_document(
            id=1, filename="test_document.pdf", path="/uploads/test_document.pdf"
        )
        mock_doc_repo.get_by_id.return_value = mock_doc

        # Mock file exists
        with patch("os.path.exists", return_value=True):
            from mimir.api.endpoints.documents import download_document

            asyncio.run(download_document(document_id=1, doc_repo=mock_doc_repo))

        # Assertions
        mock_doc_repo.get_by_id.assert_called_once_with(1)
        mock_file_response.assert_called_once()

        # Verify FileResponse arguments
        call_args = mock_file_response.call_args
        assert call_args[1]["path"] == "/uploads/test_document.pdf"
        assert call_args[1]["media_type"] == "application/pdf"
        assert "test_document.pdf" in call_args[1]["filename"]

    def test_download_document_not_found(self, mock_doc_repo):
        """Test document download - document not found."""
        mock_doc_repo.get_by_id.return_value = None

        from mimir.api.endpoints.documents import download_document

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(download_document(document_id=999, doc_repo=mock_doc_repo))

        assert exc_info.value.status_code == 404
        assert "Document with ID 999 not found" in str(exc_info.value.detail)

    def test_download_document_file_not_found(self, mock_doc_repo):
        """Test document download - physical file not found."""
        # Mock document with non-existent path
        mock_doc = self.create_mock_document(id=1, filename="missing.pdf", path="/missing/file.pdf")
        mock_doc_repo.get_by_id.return_value = mock_doc

        # Mock file doesn't exist
        with patch("os.path.exists", return_value=False):
            from mimir.api.endpoints.documents import download_document

            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(download_document(document_id=1, doc_repo=mock_doc_repo))

        assert exc_info.value.status_code == 404
        assert "Original document file not found on disk" in str(exc_info.value.detail)

    @patch("mimir.api.endpoints.documents.FileResponse")
    def test_download_document_unknown_extension(self, mock_file_response, mock_doc_repo):
        """Test document download - unknown extension."""
        # Mock document with unknown extension
        mock_doc = self.create_mock_document(
            id=1,
            filename="test.xyz",  # Unsupported extension
            path="/uploads/test.xyz",
        )
        mock_doc_repo.get_by_id.return_value = mock_doc

        # Mock file exists
        with patch("os.path.exists", return_value=True):
            from mimir.api.endpoints.documents import download_document

            asyncio.run(download_document(document_id=1, doc_repo=mock_doc_repo))

        # Verify default mime type is used
        call_args = mock_file_response.call_args
        assert call_args[1]["media_type"] == "application/octet-stream"


class TestUploadQueueFullCleanup:
    """On queue-full 503, the pending DB record and the stored
    file must be rolled back, otherwise any retry of the same file hits 409
    (get_by_hash matches the orphaned pending record) and is never ingested."""

    @patch("mimir.api.endpoints.documents.settings")
    def test_upload_queue_full_deletes_record_and_file(self, mock_settings):
        """queue_document() == False -> 503 + record deleted + file removed."""
        import hashlib

        with tempfile.TemporaryDirectory() as temp_dir:
            mock_settings.max_file_size_mb = 10
            mock_settings.supported_file_extensions = {".pdf"}
            mock_settings.upload_dir = temp_dir

            content = b"queue full test content"
            file_hash = hashlib.sha256(content).hexdigest()
            expected_path = Path(temp_dir) / f"{file_hash}_test.pdf"

            mock_file = Mock(spec=UploadFile)
            mock_file.filename = "test.pdf"
            mock_file.size = len(content)
            mock_file.read = AsyncMock(return_value=content)

            mock_doc_repo = Mock()
            mock_doc_repo.get_by_hash.return_value = None
            mock_doc_repo.create.return_value = Mock(id=7)

            mock_ingestion = Mock()
            mock_ingestion.queue_document.return_value = False  # Queue is full
            mock_ingestion.get_queue_size.return_value = 100

            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(
                    upload_document(
                        request=Mock(),  # required by slowapi decorator
                        response=Mock(),  # required by slowapi header injection
                        file=mock_file,
                        preserve=False,
                        current_user={"sub": "admin", "user_type": "admin"},
                        doc_repo=mock_doc_repo,
                        audit_repo=Mock(),
                        ingestion_processor=mock_ingestion,
                    )
                )

            assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            mock_doc_repo.delete.assert_called_once_with(7, force=True)
            assert not expected_path.exists(), "stored file must be removed on queue-full rejection"
