"""
Edge cases of database/repository.py
Error handling, edge cases and less common features
"""

from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from mimir.database.repository import (
    AuditLogRepository,
    BaseRepository,
    ConfigurationRepository,
    DocumentRepository,
    create_repositories,
)
from mimir.shared.clock import utc_now
from mimir.shared.errors import NotFoundError


class TestBaseRepository:
    """BaseRepository tests"""

    def test_handle_db_error(self):
        mock_session = Mock()
        repo = BaseRepository(mock_session)

        # SQLAlchemyError
        error = SQLAlchemyError("Database error")
        repo._handle_db_error(error, "test operation")

        # Check that rollback is called
        mock_session.rollback.assert_called_once()


class TestDocumentRepositoryErrorHandling:
    """DocumentRepository error handling"""

    def test_create_sqlalchemy_error(self, test_repositories):
        repo = test_repositories["document"]

        with (
            patch.object(repo.session, "commit", side_effect=SQLAlchemyError("DB Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.create("test.pdf", "hash123")

    def test_get_by_id_sqlalchemy_error(self, test_repositories):
        repo = test_repositories["document"]

        with (
            patch.object(repo.session, "query", side_effect=SQLAlchemyError("Query Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.get_by_id(1)

    def test_get_by_hash_sqlalchemy_error(self, test_repositories):
        repo = test_repositories["document"]

        with (
            patch.object(repo.session, "query", side_effect=SQLAlchemyError("Query Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.get_by_hash("hash123")

    def test_get_by_status_sqlalchemy_error(self, test_repositories):
        repo = test_repositories["document"]

        with (
            patch.object(repo.session, "query", side_effect=SQLAlchemyError("Query Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.get_by_status("pending")

    def test_get_all_sqlalchemy_error(self, test_repositories):
        repo = test_repositories["document"]

        with (
            patch.object(repo.session, "query", side_effect=SQLAlchemyError("Query Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.get_all()

    def test_update_status_document_not_found(self, test_repositories):
        repo = test_repositories["document"]

        with pytest.raises(NotFoundError, match="Document 999 not found"):
            repo.update_status(999, "indexed")

    def test_update_status_sqlalchemy_error(self, test_repositories, sample_document_data):
        repo = test_repositories["document"]

        # Create a document
        doc = repo.create(
            filename=sample_document_data["filename"], file_hash=sample_document_data["file_hash"]
        )

        with (
            patch.object(repo.session, "commit", side_effect=SQLAlchemyError("Update Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.update_status(doc.id, "indexed")

    def test_delete_sqlalchemy_error(self, test_repositories, sample_document_data):
        repo = test_repositories["document"]

        # Create a document
        doc = repo.create(
            filename=sample_document_data["filename"], file_hash=sample_document_data["file_hash"]
        )

        with (
            patch.object(repo.session, "commit", side_effect=SQLAlchemyError("Delete Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.delete(doc.id)

    def test_get_statistics_sqlalchemy_error(self, test_repositories):
        repo = test_repositories["document"]

        with (
            patch.object(repo.session, "query", side_effect=SQLAlchemyError("Stats Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.get_statistics()


class TestDocumentRepositoryStatusUpdates:
    """DocumentRepository edge cases"""

    def test_update_status_with_indexed_timestamp(self, test_repositories, sample_document_data):
        repo = test_repositories["document"]

        # Create a document
        doc = repo.create(
            filename=sample_document_data["filename"], file_hash=sample_document_data["file_hash"]
        )

        # Update to indexed with chunk_count
        repo.update_status(doc.id, "indexed", chunk_count=10)

        # Read back and check
        updated_doc = repo.get_by_id(doc.id)
        assert updated_doc.status == "indexed"
        assert updated_doc.chunk_count == 10
        assert updated_doc.indexed_at is not None

    def test_update_status_with_error_message(self, test_repositories, sample_document_data):
        repo = test_repositories["document"]

        # Create a document
        doc = repo.create(
            filename=sample_document_data["filename"], file_hash=sample_document_data["file_hash"]
        )

        # Update to error with a message
        error_msg = "File processing failed"
        repo.update_status(doc.id, "error", error_message=error_msg)

        # Read back and check
        updated_doc = repo.get_by_id(doc.id)
        assert updated_doc.status == "error"
        assert updated_doc.error_message == error_msg

    def test_delete_document_not_found(self, test_repositories):
        repo = test_repositories["document"]

        result = repo.delete(999)
        assert result is False

    def test_get_statistics_with_chunks(self, test_repositories, sample_document_data):
        repo = test_repositories["document"]

        # Create documents with different statuses
        doc1 = repo.create(
            filename="doc1.pdf",
            file_hash="hash1",
        )
        doc2 = repo.create(
            filename="doc2.pdf",
            file_hash="hash2",
        )

        # Update with chunks
        repo.update_status(doc1.id, "indexed", chunk_count=5)
        repo.update_status(doc2.id, "indexed", chunk_count=10)

        # Create a protected document
        repo.create(filename="protected.pdf", file_hash="hash3", preserve=True)

        stats = repo.get_statistics()

        # Check the statistics
        assert stats["total_documents"] == 3
        assert stats["count_pending"] == 1  # protected doc
        assert stats["count_indexed"] == 2
        assert stats["total_chunks"] == 15  # 5 + 10
        assert stats["protected_documents"] == 1


class TestConfigurationRepositoryErrorHandling:
    """ConfigurationRepository error handling"""

    def test_get_sqlalchemy_error(self, test_repositories):
        repo = test_repositories["config"]

        with (
            patch.object(repo.session, "query", side_effect=SQLAlchemyError("Query Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.get("test_key")

    def test_set_sqlalchemy_error(self, test_repositories):
        repo = test_repositories["config"]

        with (
            patch.object(repo.session, "commit", side_effect=SQLAlchemyError("Commit Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.set("test_key", "test_value")

    def test_delete_sqlalchemy_error(self, test_repositories):
        repo = test_repositories["config"]

        # Create a configuration first
        repo.set("test_key", "test_value")

        with (
            patch.object(repo.session, "commit", side_effect=SQLAlchemyError("Delete Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.delete("test_key")

    def test_get_all_sqlalchemy_error(self, test_repositories):
        repo = test_repositories["config"]

        with (
            patch.object(repo.session, "query", side_effect=SQLAlchemyError("Query Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.get_all()

    def test_get_value_with_default(self, test_repositories):
        repo = test_repositories["config"]

        # Missing key
        value = repo.get_value("nonexistent", "default_value")
        assert value == "default_value"

        # Existing key
        repo.set("existing_key", "existing_value")
        value = repo.get_value("existing_key", "default_value")
        assert value == "existing_value"


class TestAuditLogRepositoryErrorHandling:
    """AuditLogRepository error handling"""

    def test_create_log_sqlalchemy_error(self, test_repositories):
        repo = test_repositories["audit"]

        with (
            patch.object(repo.session, "commit", side_effect=SQLAlchemyError("Commit Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.create_log("admin", "test_action")

    def test_get_logs_sqlalchemy_error(self, test_repositories):
        repo = test_repositories["audit"]

        with (
            patch.object(repo.session, "query", side_effect=SQLAlchemyError("Query Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.get_logs()

    def test_cleanup_old_logs_sqlalchemy_error(self, test_repositories):
        repo = test_repositories["audit"]

        with patch.object(repo.session, "query") as mock_query:
            mock_query.return_value.filter.return_value.delete.side_effect = SQLAlchemyError(
                "Delete Error"
            )

            with pytest.raises(SQLAlchemyError):
                repo.cleanup_old_logs(30)


class TestAuditLogRepositoryQueries:
    """AuditLogRepository edge cases"""

    def test_cleanup_old_logs_success(self, test_repositories):
        repo = test_repositories["audit"]

        # Create old and recent logs
        old_date = utc_now() - timedelta(days=100)

        # Create a recent log
        repo.create_log("admin", "recent_action")

        # Create an old log (by changing its date)
        old_log = repo.create_log("admin", "old_action")
        old_log.created_at = old_date
        repo.session.commit()

        # Delete the logs older than 90 days
        deleted_count = repo.cleanup_old_logs(90)

        # Check that one log was deleted
        assert deleted_count == 1

        # Check that the recent log still exists
        remaining_logs = repo.get_logs()
        assert len(remaining_logs) == 1
        assert remaining_logs[0].action == "recent_action"

    def test_cleanup_old_logs_no_deletion(self, test_repositories):
        repo = test_repositories["audit"]

        # Create a recent log only
        repo.create_log("admin", "recent_action")

        # Delete the logs older than 90 days
        deleted_count = repo.cleanup_old_logs(90)

        # Check that no log was deleted
        assert deleted_count == 0

    def test_create_log_with_all_parameters(self, test_repositories):
        repo = test_repositories["audit"]

        log = repo.create_log(
            user_type="admin",
            action="complex_action",
            details="Detailed description",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 Test",
            success=False,
        )

        assert log.user_type == "admin"
        assert log.action == "complex_action"
        assert log.details == "Detailed description"
        assert log.ip_address == "192.168.1.100"
        assert log.user_agent == "Mozilla/5.0 Test"
        assert log.success is False

    def test_get_logs_with_partial_action_match(self, test_repositories):
        repo = test_repositories["audit"]

        # Create logs with different actions
        repo.create_log("admin", "login_success")
        repo.create_log("admin", "login_failure")
        repo.create_log("admin", "logout")

        # Search the logs containing "login"
        login_logs = repo.get_logs(action="login")

        # Should find the 2 logs containing "login"
        assert len(login_logs) == 2
        assert all("login" in log.action for log in login_logs)


class TestCreateRepositoriesFactory:
    """create_repositories factory tests"""

    def test_create_repositories_success(self, test_session):
        repositories = create_repositories(test_session)

        assert "document" in repositories
        assert "config" in repositories
        assert "audit" in repositories

        assert isinstance(repositories["document"], DocumentRepository)
        assert isinstance(repositories["config"], ConfigurationRepository)
        assert isinstance(repositories["audit"], AuditLogRepository)

        # Check that they all use the same session
        assert repositories["document"].session is test_session
        assert repositories["config"].session is test_session
        assert repositories["audit"].session is test_session
