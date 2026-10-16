"""
Integration tests of the repositories against a real SQLite database.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from mimir.database.models import Base
from mimir.database.repository import (
    AuditLogRepository,
    ConfigurationRepository,
    DocumentRepository,
)
from mimir.shared.models import DocumentStatus


@pytest.fixture
def session(tmp_path):
    """Session on a fresh file-backed SQLite database."""
    engine = create_engine(f"sqlite:///{tmp_path / 'integration.db'}")
    Base.metadata.create_all(bind=engine)
    db_session = sessionmaker(bind=engine)()
    yield db_session
    db_session.close()
    engine.dispose()


class TestDocumentRepositoryIntegration:
    def test_document_crud_operations(self, session):
        repo = DocumentRepository(session)
        first = repo.create(
            filename="integration_test_1.pdf", file_hash="hash1234567890", path="/test/path1.pdf"
        )
        second = repo.create(
            filename="integration_test_2.txt",
            file_hash="hash0987654321",
            path="/test/path2.txt",
            preserve=True,
        )
        for doc in (first, second):
            assert doc.id is not None
            assert doc.status == DocumentStatus.PENDING

        assert repo.get_by_id(first.id).filename == "integration_test_1.pdf"
        assert repo.get_by_hash("hash1234567890").id == first.id

        repo.update_status(first.id, DocumentStatus.INDEXING)
        assert repo.get_by_id(first.id).status == DocumentStatus.INDEXING

        assert len(repo.get_all(limit=10)) == 2
        stats = repo.get_statistics()
        assert stats["total_documents"] == 2
        assert stats["count_pending"] == 1
        assert stats["count_indexing"] == 1

    def test_missing_documents(self, session):
        repo = DocumentRepository(session)
        assert repo.get_by_id(99999) is None
        assert repo.get_by_hash("nonexistent_hash") is None
        with pytest.raises(ValueError):
            repo.update_status(99999, DocumentStatus.INDEXED)

    def test_duplicate_hash_is_rejected(self, session):
        repo = DocumentRepository(session)
        repo.create(filename="first.pdf", file_hash="duplicate_hash", path="/test/first.pdf")
        with pytest.raises(ValueError, match="already exists"):
            repo.create(filename="other.pdf", file_hash="duplicate_hash", path="/test/other.pdf")

    def test_create_commits_immediately(self, session):
        """A later rollback does not undo a document the repository created."""
        repo = DocumentRepository(session)
        document = repo.create(
            filename="rollback_test.pdf", file_hash="rollback_hash", path="/test/rollback.pdf"
        )
        session.rollback()
        assert repo.get_by_id(document.id) is not None


class TestConfigurationRepositoryIntegration:
    def test_set_and_update_values(self, session):
        repo = ConfigurationRepository(session)
        configs = {
            "maintenance_mode": "false",
            "max_concurrent_ingestions": "3",
            "email_notifications": "true",
            "debug_mode": "false",
        }
        for key, value in configs.items():
            repo.set(key, value)

        assert repo.get_value("maintenance_mode") == "false"
        repo.set("maintenance_mode", "true")
        assert repo.get_value("maintenance_mode") == "true"
        assert {config.key for config in repo.get_all()} == set(configs)

    def test_defaults_and_string_storage(self, session):
        repo = ConfigurationRepository(session)
        assert repo.get_value("missing_key", default="default_value") == "default_value"
        assert repo.get_value("another_missing_key") is None

        repo.set("integer_value", "42")
        repo.set("float_value", "3.14")
        assert repo.get_value("integer_value") == "42"
        assert repo.get_value("float_value") == "3.14"

    def test_setting_a_key_twice_updates_it(self, session):
        repo = ConfigurationRepository(session)
        repo.set("unique_key_test", "value1")
        repo.set("unique_key_test", "value2")
        assert repo.get_value("unique_key_test") == "value2"
        assert [c.key for c in repo.get_all()].count("unique_key_test") == 1


class TestAuditLogRepositoryIntegration:
    def test_creation_and_filters(self, session):
        repo = AuditLogRepository(session)
        entries = [
            ("admin", "login_success", True, {"browser": "Chrome"}),
            ("admin", "document_upload", True, {"file_size": 1024000}),
            ("system", "cleanup_task", False, {"error": "Permission denied"}),
        ]
        for user_type, action, success, data in entries:
            log_entry = repo.create_log(
                user_type=user_type,
                action=action,
                details=f"{action} details",
                ip_address="192.168.1.100",
                success=success,
                additional_data=data,
            )
            assert log_entry.id is not None
            assert log_entry.created_at is not None

        all_logs = repo.get_logs(offset=0, limit=10)
        assert len(all_logs) == 3
        assert [
            log.action for log in repo.get_logs(action="login_success", offset=0, limit=10)
        ] == ["login_success"]
        assert len(repo.get_logs(user_type="admin", offset=0, limit=10)) == 2
        assert [log.action for log in all_logs if not log.success] == ["cleanup_task"]

    def test_created_at_is_today(self, session):
        repo = AuditLogRepository(session)
        repo.create_log(
            user_type="admin",
            action="test_action",
            details="Date check",
            ip_address="127.0.0.1",
            success=True,
        )
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        created_at = repo.get_logs(offset=0, limit=10)[0].created_at
        assert today <= created_at < today + timedelta(days=1)

    def test_invalid_user_type_violates_the_check_constraint(self, session):
        repo = AuditLogRepository(session)
        with pytest.raises(IntegrityError):
            repo.create_log(
                user_type="invalid_user_type",
                action="test_action",
                details="Invalid user type",
                ip_address="127.0.0.1",
                success=True,
            )


class TestCrossRepositoryIntegration:
    def test_document_and_audit_entry_in_one_session(self, session):
        doc_repo = DocumentRepository(session)
        audit_repo = AuditLogRepository(session)
        document = doc_repo.create(
            filename="transaction_test.pdf", file_hash="transaction_hash", path="/test/t.pdf"
        )
        audit_repo.create_log(
            user_type="admin",
            action="document_creation",
            details=f"Created document {document.filename}",
            ip_address="127.0.0.1",
            success=True,
            additional_data={"document_id": document.id},
        )

        assert doc_repo.get_by_id(document.id) is not None
        assert len(audit_repo.get_logs(action="document_creation", offset=0, limit=10)) == 1
