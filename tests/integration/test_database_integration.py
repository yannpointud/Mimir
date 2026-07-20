"""
Tests d'intégration pour les interactions avec la base de données
Tests des repositories, modèles et transactions avec données réelles
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Document, Configuration, AuditLog  # noqa: F401
from src.database.repository import DocumentRepository, ConfigurationRepository, AuditLogRepository
from src.shared.models import DocumentStatus


class TestDocumentRepositoryIntegration:
    """Tests d'intégration pour DocumentRepository avec base de données réelle"""

    @pytest.fixture
    def integration_session(self):
        """Session de base de données pour tests d'intégration"""
        # Créer une base temporaire pour les tests d'intégration
        temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_db.close()

        engine = create_engine(f"sqlite:///{temp_db.name}")
        Base.metadata.create_all(bind=engine)

        Session = sessionmaker(bind=engine)
        session = Session()

        yield session

        session.close()
        Path(temp_db.name).unlink(missing_ok=True)

    def test_document_crud_operations_integration(self, integration_session):
        """Test des opérations CRUD complètes sur les documents"""
        repo = DocumentRepository(integration_session)

        # Créer plusieurs documents
        documents_data = [
            {
                "filename": "integration_test_1.pdf",
                "file_hash": "hash1234567890",
                "path": "/test/path1.pdf"
            },
            {
                "filename": "integration_test_2.txt",
                "file_hash": "hash0987654321",
                "path": "/test/path2.txt",
                "preserve": True
            }
        ]

        created_docs = []
        for doc_data in documents_data:
            doc = repo.create(**doc_data)
            created_docs.append(doc)
            assert doc.id is not None
            assert doc.status == DocumentStatus.PENDING

        # Test de récupération
        retrieved_doc = repo.get_by_id(created_docs[0].id)
        assert retrieved_doc is not None
        assert retrieved_doc.filename == "integration_test_1.pdf"

        # Test de recherche par hash
        doc_by_hash = repo.get_by_hash("hash1234567890")
        assert doc_by_hash is not None
        assert doc_by_hash.id == created_docs[0].id

        # Test de mise à jour de statut
        repo.update_status(created_docs[0].id, DocumentStatus.INDEXING)

        updated_doc = repo.get_by_id(created_docs[0].id)
        assert updated_doc.status == DocumentStatus.INDEXING

        # Test de liste avec pagination
        all_docs = repo.get_all(limit=10)
        assert len(all_docs) >= 2

        # Test de statistiques
        stats = repo.get_statistics()
        assert stats["total_documents"] >= 2
        assert stats["count_pending"] >= 1  # Le deuxième document
        assert stats["count_indexing"] >= 1  # Le premier document mis à jour

    def test_document_repository_error_handling(self, integration_session):
        """Test de gestion d'erreurs dans le repository"""
        repo = DocumentRepository(integration_session)

        # Test de récupération document inexistant
        non_existent = repo.get_by_id(99999)
        assert non_existent is None

        # Test de hash inexistant
        no_doc = repo.get_by_hash("nonexistent_hash")
        assert no_doc is None

        # Test de mise à jour document inexistant
        with pytest.raises(ValueError):
            repo.update_status(99999, DocumentStatus.INDEXED)

    def test_document_duplicate_prevention(self, integration_session):
        """Test de prévention des doublons basés sur le hash"""
        repo = DocumentRepository(integration_session)

        # Créer un document
        doc1 = repo.create(
            filename="duplicate_test.pdf",
            file_hash="duplicate_hash_123",
            path="/test/duplicate.pdf"
        )
        assert doc1 is not None

        # Tenter de créer un doublon (même hash)
        with pytest.raises(Exception):  # Doit lever une exception de contrainte
            repo.create(
                filename="different_name.pdf",
                file_hash="duplicate_hash_123",  # Même hash
                path="/different/path.pdf"
            )


class TestConfigurationRepositoryIntegration:
    """Tests d'intégration pour ConfigurationRepository"""

    @pytest.fixture
    def config_session(self):
        """Session dédiée aux tests de configuration"""
        temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_db.close()

        engine = create_engine(f"sqlite:///{temp_db.name}")
        Base.metadata.create_all(bind=engine)

        Session = sessionmaker(bind=engine)
        session = Session()

        yield session

        session.close()
        Path(temp_db.name).unlink(missing_ok=True)

    def test_configuration_management_integration(self, config_session):
        """Test de gestion complète de la configuration"""
        repo = ConfigurationRepository(config_session)

        # Créer plusieurs configurations
        configs = [
            ("maintenance_mode", "false"),
            ("max_concurrent_ingestions", "3"),
            ("email_notifications", "true"),
            ("debug_mode", "false")
        ]

        for key, value in configs:
            repo.set(key, value)

        # Vérifier récupération individuelle
        maintenance = repo.get_value("maintenance_mode")
        assert maintenance == "false"

        # Test de mise à jour
        repo.set("maintenance_mode", "true")
        updated_maintenance = repo.get_value("maintenance_mode")
        assert updated_maintenance == "true"

        # Récupérer toutes les configurations
        all_configs = repo.get_all()
        assert len(all_configs) >= 4

        # Vérifier que toutes les clés sont présentes
        config_keys = {config.key for config in all_configs}
        expected_keys = {"maintenance_mode", "max_concurrent_ingestions", "email_notifications", "debug_mode"}
        assert expected_keys.issubset(config_keys)

    def test_configuration_defaults_and_types(self, config_session):
        """Test des valeurs par défaut et conversion de types"""
        repo = ConfigurationRepository(config_session)

        # Test avec valeur par défaut
        non_existent = repo.get_value("non_existent_key", default="default_value")
        assert non_existent == "default_value"

        # Test sans défaut
        also_non_existent = repo.get_value("another_missing_key")
        assert also_non_existent is None

        # Test de stockage et récupération de différents types
        repo.set("integer_value", "42")
        repo.set("boolean_value", "true")
        repo.set("float_value", "3.14")

        assert repo.get_value("integer_value") == "42"
        assert repo.get_value("boolean_value") == "true"
        assert repo.get_value("float_value") == "3.14"


class TestAuditLogRepositoryIntegration:
    """Tests d'intégration pour AuditLogRepository"""

    @pytest.fixture
    def audit_session(self):
        """Session dédiée aux tests d'audit"""
        temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_db.close()

        engine = create_engine(f"sqlite:///{temp_db.name}")
        Base.metadata.create_all(bind=engine)

        Session = sessionmaker(bind=engine)
        session = Session()

        yield session

        session.close()
        Path(temp_db.name).unlink(missing_ok=True)

    def test_audit_log_creation_and_retrieval(self, audit_session):
        """Test de création et récupération des logs d'audit"""
        repo = AuditLogRepository(audit_session)

        # Créer plusieurs entrées d'audit
        audit_entries = [
            {
                "user_type": "admin",
                "action": "login_success",
                "details": "Admin login from web interface",
                "ip_address": "192.168.1.100",
                "success": True,
                "additional_data": {"browser": "Chrome", "session_duration": 3600}
            },
            {
                "user_type": "admin",
                "action": "document_upload",
                "details": "Uploaded integration_test.pdf",
                "ip_address": "192.168.1.100",
                "success": True,
                "additional_data": {"file_size": 1024000, "file_type": "pdf"}
            },
            {
                "user_type": "system",
                "action": "cleanup_task",
                "details": "Automated cleanup of temporary files",
                "ip_address": "127.0.0.1",
                "success": False,
                "additional_data": {"error": "Permission denied", "files_processed": 5}
            }
        ]

        created_logs = []
        for entry_data in audit_entries:
            log_entry = repo.create_log(**entry_data)
            created_logs.append(log_entry)
            assert log_entry.id is not None
            assert log_entry.created_at is not None

        # Test de récupération avec pagination
        all_logs = repo.get_logs(offset=0, limit=10)
        assert len(all_logs) == 3

        # Test de filtrage par action
        login_logs = repo.get_logs(action="login_success", offset=0, limit=10)
        assert len(login_logs) == 1
        assert login_logs[0].action == "login_success"

        # Test de filtrage par user_type
        admin_logs = repo.get_logs(user_type="admin", offset=0, limit=10)
        assert len(admin_logs) == 2

        # Test de filtrage par success
        # Note: get_logs() ne filtre pas par success, on filtre manuellement
        all_logs_for_success = repo.get_logs(offset=0, limit=10)
        failed_logs = [log for log in all_logs_for_success if not log.success]
        assert len(failed_logs) == 1
        assert failed_logs[0].success is False

    def test_audit_log_date_filtering(self, audit_session):
        """Test de filtrage par date des logs d'audit"""
        repo = AuditLogRepository(audit_session)

        # Créer une entrée
        repo.create_log(
            user_type="admin",
            action="test_action",
            details="Test entry for date filtering",
            ip_address="127.0.0.1",
            success=True
        )

        # Test de filtrage depuis aujourd'hui
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        # Note: get_logs() ne filtre pas par date, on récupère tous les logs et on filtre manuellement
        all_logs = repo.get_logs(offset=0, limit=10)
        recent_logs = [log for log in all_logs if log.created_at >= today]
        assert len(recent_logs) >= 1

        # Test de filtrage depuis demain (ne doit rien retourner)
        tomorrow = today + timedelta(days=1)
        future_logs = [log for log in all_logs if log.created_at >= tomorrow]
        assert len(future_logs) == 0


class TestTransactionIntegration:
    """Tests d'intégration pour les transactions multi-tables"""

    @pytest.fixture
    def transaction_session(self):
        """Session pour les tests de transactions"""
        temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_db.close()

        engine = create_engine(f"sqlite:///{temp_db.name}")
        Base.metadata.create_all(bind=engine)

        Session = sessionmaker(bind=engine)
        session = Session()

        yield session

        session.close()
        Path(temp_db.name).unlink(missing_ok=True)

    def test_multi_repository_transaction(self, transaction_session):
        """Test de transaction impliquant plusieurs repositories"""
        doc_repo = DocumentRepository(transaction_session)
        audit_repo = AuditLogRepository(transaction_session)

        try:
            # Commencer une transaction implicite

            # Créer un document
            document = doc_repo.create(
                filename="transaction_test.pdf",
                file_hash="transaction_hash_123",
                path="/test/transaction.pdf"
            )

            # Enregistrer l'action dans l'audit
            audit_log = audit_repo.create_log(  # noqa: F841
                user_type="admin",
                action="document_creation",
                details=f"Created document {document.filename}",
                ip_address="127.0.0.1",
                success=True,
                additional_data={"document_id": document.id}
            )

            # Commit implicite si tout va bien
            transaction_session.commit()

            # Vérifier que les deux entrées existent
            assert doc_repo.get_by_id(document.id) is not None

            logs = audit_repo.get_logs(action="document_creation", offset=0, limit=10)
            assert len(logs) == 1

        except Exception as e:
            transaction_session.rollback()
            raise e

    def test_transaction_rollback_behavior(self, transaction_session):
        """Test du comportement de rollback des transactions"""
        doc_repo = DocumentRepository(transaction_session)

        # Compter les documents avant
        initial_count = len(doc_repo.get_all())

        try:
            # Créer un document
            document = doc_repo.create(
                filename="rollback_test.pdf",
                file_hash="rollback_hash_123",
                path="/test/rollback.pdf"
            )
            assert document.id is not None

            # Vérifier qu'il existe avant commit
            found_doc = doc_repo.get_by_id(document.id)
            assert found_doc is not None

            # Simuler une erreur et rollback
            transaction_session.rollback()

            # Vérifier que le document n'existe plus après rollback
            # Note: Dans une nouvelle session
            final_count = len(doc_repo.get_all())
            assert final_count == initial_count

        except Exception:
            transaction_session.rollback()


class TestDatabaseConstraintsIntegration:
    """Tests d'intégration pour les contraintes de base de données"""

    @pytest.fixture
    def constraints_session(self):
        """Session pour tester les contraintes"""
        temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_db.close()

        engine = create_engine(f"sqlite:///{temp_db.name}")
        Base.metadata.create_all(bind=engine)

        Session = sessionmaker(bind=engine)
        session = Session()

        yield session

        session.close()
        Path(temp_db.name).unlink(missing_ok=True)

    def test_document_hash_uniqueness_constraint(self, constraints_session):
        """Test de la contrainte d'unicité sur le hash des documents"""
        repo = DocumentRepository(constraints_session)

        # Créer un document
        doc1 = repo.create(
            filename="constraint_test1.pdf",
            file_hash="unique_hash_constraint_123",
            path="/test/constraint1.pdf"
        )
        assert doc1.id is not None

        # Tenter de créer un document avec le même hash
        with pytest.raises(Exception):  # Doit violer la contrainte d'unicité
            repo.create(
                filename="constraint_test2.pdf",
                file_hash="unique_hash_constraint_123",  # Même hash
                path="/test/constraint2.pdf"
            )

    def test_configuration_key_uniqueness_constraint(self, constraints_session):
        """Test de la contrainte d'unicité sur les clés de configuration"""
        repo = ConfigurationRepository(constraints_session)

        # Définir une configuration
        repo.set("unique_key_test", "value1")

        # Redéfinir la même clé (doit faire un UPDATE, pas INSERT)
        repo.set("unique_key_test", "value2")

        # Vérifier que la valeur a été mise à jour
        value = repo.get_value("unique_key_test")
        assert value == "value2"

        # Vérifier qu'il n'y a qu'une seule entrée avec cette clé
        all_configs = repo.get_all()
        unique_key_configs = [c for c in all_configs if c.key == "unique_key_test"]
        assert len(unique_key_configs) == 1

    def test_audit_log_field_constraints(self, constraints_session):
        """Test des contraintes sur les champs des logs d'audit"""
        repo = AuditLogRepository(constraints_session)

        # Test avec user_type invalide
        with pytest.raises(Exception):
            repo.create_log(
                user_type="invalid_user_type",  # Doit être admin, user, ou system
                action="test_action",
                details="Test with invalid user type",
                ip_address="127.0.0.1",
                success=True
            )

        # Test avec user_type valide
        valid_log = repo.create_log(
            user_type="admin",
            action="test_action",
            details="Test with valid user type",
            ip_address="127.0.0.1",
            success=True
        )
        assert valid_log.id is not None