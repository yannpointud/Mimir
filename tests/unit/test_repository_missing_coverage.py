"""
Tests pour couvrir les lignes manquantes dans database/repository.py
Couvre la gestion d'erreurs, cas limites et fonctionnalités non testées
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from sqlalchemy.exc import SQLAlchemyError

from mimir.shared.errors import NotFoundError

from mimir.database.repository import (
    DocumentRepository,
    ConfigurationRepository,
    AuditLogRepository,
    BaseRepository,
    create_repositories,
)


class TestBaseRepository:
    """Tests pour BaseRepository"""

    def test_handle_db_error(self):
        """Test gestion des erreurs de base de données"""
        mock_session = Mock()
        repo = BaseRepository(mock_session)

        # Test avec SQLAlchemyError
        error = SQLAlchemyError("Database error")
        repo._handle_db_error(error, "test operation")

        # Vérifier que rollback est appelé
        mock_session.rollback.assert_called_once()


class TestDocumentRepositoryErrorHandling:
    """Tests pour gestion d'erreurs DocumentRepository"""

    def test_create_sqlalchemy_error(self, test_repositories):
        """Test création avec erreur SQLAlchemy"""
        repo = test_repositories["document"]

        with (
            patch.object(repo.session, "commit", side_effect=SQLAlchemyError("DB Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.create("test.pdf", "hash123")

    def test_get_by_id_sqlalchemy_error(self, test_repositories):
        """Test get_by_id avec erreur SQLAlchemy"""
        repo = test_repositories["document"]

        with (
            patch.object(repo.session, "query", side_effect=SQLAlchemyError("Query Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.get_by_id(1)

    def test_get_by_hash_sqlalchemy_error(self, test_repositories):
        """Test get_by_hash avec erreur SQLAlchemy"""
        repo = test_repositories["document"]

        with (
            patch.object(repo.session, "query", side_effect=SQLAlchemyError("Query Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.get_by_hash("hash123")

    def test_get_by_status_sqlalchemy_error(self, test_repositories):
        """Test get_by_status avec erreur SQLAlchemy"""
        repo = test_repositories["document"]

        with (
            patch.object(repo.session, "query", side_effect=SQLAlchemyError("Query Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.get_by_status("pending")

    def test_get_all_sqlalchemy_error(self, test_repositories):
        """Test get_all avec erreur SQLAlchemy"""
        repo = test_repositories["document"]

        with (
            patch.object(repo.session, "query", side_effect=SQLAlchemyError("Query Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.get_all()

    def test_update_status_document_not_found(self, test_repositories):
        """Test update_status avec document inexistant"""
        repo = test_repositories["document"]

        with pytest.raises(NotFoundError, match="Document 999 not found"):
            repo.update_status(999, "indexed")

    def test_update_status_sqlalchemy_error(self, test_repositories, sample_document_data):
        """Test update_status avec erreur SQLAlchemy"""
        repo = test_repositories["document"]

        # Créer un document
        doc = repo.create(
            filename=sample_document_data["filename"], file_hash=sample_document_data["file_hash"]
        )

        with (
            patch.object(repo.session, "commit", side_effect=SQLAlchemyError("Update Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.update_status(doc.id, "indexed")

    def test_delete_sqlalchemy_error(self, test_repositories, sample_document_data):
        """Test delete avec erreur SQLAlchemy"""
        repo = test_repositories["document"]

        # Créer un document
        doc = repo.create(
            filename=sample_document_data["filename"], file_hash=sample_document_data["file_hash"]
        )

        with (
            patch.object(repo.session, "commit", side_effect=SQLAlchemyError("Delete Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.delete(doc.id)

    def test_get_statistics_sqlalchemy_error(self, test_repositories):
        """Test get_statistics avec erreur SQLAlchemy"""
        repo = test_repositories["document"]

        with (
            patch.object(repo.session, "query", side_effect=SQLAlchemyError("Stats Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.get_statistics()


class TestDocumentRepositoryMissingCoverage:
    """Tests pour couvrir les lignes manquantes DocumentRepository"""

    def test_update_status_with_indexed_timestamp(self, test_repositories, sample_document_data):
        """Test update_status avec timestamp indexed_at"""
        repo = test_repositories["document"]

        # Créer un document
        doc = repo.create(
            filename=sample_document_data["filename"], file_hash=sample_document_data["file_hash"]
        )

        # Mettre à jour vers indexed avec chunk_count
        repo.update_status(doc.id, "indexed", chunk_count=10)

        # Récupérer et vérifier
        updated_doc = repo.get_by_id(doc.id)
        assert updated_doc.status == "indexed"
        assert updated_doc.chunk_count == 10
        assert updated_doc.indexed_at is not None

    def test_update_status_with_error_message(self, test_repositories, sample_document_data):
        """Test update_status avec message d'erreur"""
        repo = test_repositories["document"]

        # Créer un document
        doc = repo.create(
            filename=sample_document_data["filename"], file_hash=sample_document_data["file_hash"]
        )

        # Mettre à jour vers error avec message
        error_msg = "File processing failed"
        repo.update_status(doc.id, "error", error_message=error_msg)

        # Récupérer et vérifier
        updated_doc = repo.get_by_id(doc.id)
        assert updated_doc.status == "error"
        assert updated_doc.error_message == error_msg

    def test_delete_document_not_found(self, test_repositories):
        """Test delete avec document inexistant"""
        repo = test_repositories["document"]

        result = repo.delete(999)
        assert result is False

    def test_get_statistics_with_chunks(self, test_repositories, sample_document_data):
        """Test get_statistics avec calcul des chunks"""
        repo = test_repositories["document"]

        # Créer des documents avec différents statuts
        doc1 = repo.create(
            filename="doc1.pdf",
            file_hash="hash1",
        )
        doc2 = repo.create(
            filename="doc2.pdf",
            file_hash="hash2",
        )

        # Mettre à jour avec chunks
        repo.update_status(doc1.id, "indexed", chunk_count=5)
        repo.update_status(doc2.id, "indexed", chunk_count=10)

        # Créer un document protégé
        repo.create(filename="protected.pdf", file_hash="hash3", preserve=True)

        stats = repo.get_statistics()

        # Vérifier les statistiques
        assert stats["total_documents"] == 3
        assert stats["count_pending"] == 1  # protected doc
        assert stats["count_indexed"] == 2
        assert stats["total_chunks"] == 15  # 5 + 10
        assert stats["protected_documents"] == 1


class TestConfigurationRepositoryErrorHandling:
    """Tests pour gestion d'erreurs ConfigurationRepository"""

    def test_get_sqlalchemy_error(self, test_repositories):
        """Test get avec erreur SQLAlchemy"""
        repo = test_repositories["config"]

        with (
            patch.object(repo.session, "query", side_effect=SQLAlchemyError("Query Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.get("test_key")

    def test_set_sqlalchemy_error(self, test_repositories):
        """Test set avec erreur SQLAlchemy"""
        repo = test_repositories["config"]

        with (
            patch.object(repo.session, "commit", side_effect=SQLAlchemyError("Commit Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.set("test_key", "test_value")

    def test_delete_sqlalchemy_error(self, test_repositories):
        """Test delete avec erreur SQLAlchemy"""
        repo = test_repositories["config"]

        # Créer une config d'abord
        repo.set("test_key", "test_value")

        with (
            patch.object(repo.session, "commit", side_effect=SQLAlchemyError("Delete Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.delete("test_key")

    def test_get_all_sqlalchemy_error(self, test_repositories):
        """Test get_all avec erreur SQLAlchemy"""
        repo = test_repositories["config"]

        with (
            patch.object(repo.session, "query", side_effect=SQLAlchemyError("Query Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.get_all()

    def test_get_value_with_default(self, test_repositories):
        """Test get_value avec valeur par défaut"""
        repo = test_repositories["config"]

        # Test avec clé inexistante
        value = repo.get_value("nonexistent", "default_value")
        assert value == "default_value"

        # Test avec clé existante
        repo.set("existing_key", "existing_value")
        value = repo.get_value("existing_key", "default_value")
        assert value == "existing_value"


class TestAuditLogRepositoryErrorHandling:
    """Tests pour gestion d'erreurs AuditLogRepository"""

    def test_create_log_sqlalchemy_error(self, test_repositories):
        """Test create_log avec erreur SQLAlchemy"""
        repo = test_repositories["audit"]

        with (
            patch.object(repo.session, "commit", side_effect=SQLAlchemyError("Commit Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.create_log("admin", "test_action")

    def test_get_logs_sqlalchemy_error(self, test_repositories):
        """Test get_logs avec erreur SQLAlchemy"""
        repo = test_repositories["audit"]

        with (
            patch.object(repo.session, "query", side_effect=SQLAlchemyError("Query Error")),
            pytest.raises(SQLAlchemyError),
        ):
            repo.get_logs()

    def test_cleanup_old_logs_sqlalchemy_error(self, test_repositories):
        """Test cleanup_old_logs avec erreur SQLAlchemy"""
        repo = test_repositories["audit"]

        with patch.object(repo.session, "query") as mock_query:
            mock_query.return_value.filter.return_value.delete.side_effect = SQLAlchemyError(
                "Delete Error"
            )

            with pytest.raises(SQLAlchemyError):
                repo.cleanup_old_logs(30)


class TestAuditLogRepositoryMissingCoverage:
    """Tests pour couvrir les lignes manquantes AuditLogRepository"""

    def test_cleanup_old_logs_success(self, test_repositories):
        """Test cleanup_old_logs avec succès"""
        repo = test_repositories["audit"]

        # Créer des logs anciens et récents
        old_date = datetime.utcnow() - timedelta(days=100)

        # Créer un log récent
        repo.create_log("admin", "recent_action")

        # Créer un log ancien (simulé en modifiant la date)
        old_log = repo.create_log("admin", "old_action")
        old_log.created_at = old_date
        repo.session.commit()

        # Nettoyer les logs de plus de 90 jours
        deleted_count = repo.cleanup_old_logs(90)

        # Vérifier qu'un log a été supprimé
        assert deleted_count == 1

        # Vérifier que le log récent existe toujours
        remaining_logs = repo.get_logs()
        assert len(remaining_logs) == 1
        assert remaining_logs[0].action == "recent_action"

    def test_cleanup_old_logs_no_deletion(self, test_repositories):
        """Test cleanup_old_logs sans suppression"""
        repo = test_repositories["audit"]

        # Créer un log récent seulement
        repo.create_log("admin", "recent_action")

        # Nettoyer les logs de plus de 90 jours
        deleted_count = repo.cleanup_old_logs(90)

        # Vérifier qu'aucun log n'a été supprimé
        assert deleted_count == 0

    def test_create_log_with_all_parameters(self, test_repositories):
        """Test create_log avec tous les paramètres"""
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
        """Test get_logs avec correspondance partielle d'action"""
        repo = test_repositories["audit"]

        # Créer des logs avec différentes actions
        repo.create_log("admin", "login_success")
        repo.create_log("admin", "login_failure")
        repo.create_log("admin", "logout")

        # Rechercher les logs contenant "login"
        login_logs = repo.get_logs(action="login")

        # Devrait trouver les 2 logs avec "login"
        assert len(login_logs) == 2
        assert all("login" in log.action for log in login_logs)


class TestCreateRepositoriesFactory:
    """Tests pour la fonction factory create_repositories"""

    def test_create_repositories_success(self, test_session):
        """Test création réussie de tous les repositories"""
        repositories = create_repositories(test_session)

        assert "document" in repositories
        assert "config" in repositories
        assert "audit" in repositories

        assert isinstance(repositories["document"], DocumentRepository)
        assert isinstance(repositories["config"], ConfigurationRepository)
        assert isinstance(repositories["audit"], AuditLogRepository)

        # Vérifier que tous utilisent la même session
        assert repositories["document"].session is test_session
        assert repositories["config"].session is test_session
        assert repositories["audit"].session is test_session
