"""
Tests unitaires pour le pattern Repository
Vérifie les opérations CRUD et la logique métier
"""

import pytest
from datetime import datetime  # noqa: F401
from sqlalchemy.exc import IntegrityError  # noqa: F401

from src.database.repository import DocumentRepository, ConfigurationRepository, AuditLogRepository  # noqa: F401


class TestDocumentRepository:
    """Tests du DocumentRepository"""
    
    def test_create_document(self, test_repositories, sample_document_data):
        """Test de création d'un document"""
        repo = test_repositories['document']
        
        doc = repo.create(
            filename=sample_document_data["filename"],
            file_hash=sample_document_data["file_hash"],
            path=sample_document_data["path"],
            preserve=sample_document_data["preserve"]
        )
        
        assert doc.id is not None
        assert doc.filename == sample_document_data["filename"]
        assert doc.file_hash == sample_document_data["file_hash"]
        assert doc.status == "pending"
        assert doc.preserve == sample_document_data["preserve"]
    
    def test_create_document_duplicate_hash(self, test_repositories, sample_document_data):
        """Test de création avec hash dupliqué"""
        repo = test_repositories['document']
        
        # Premier document
        repo.create(
            filename=sample_document_data["filename"],
            file_hash=sample_document_data["file_hash"]
        )
        
        # Tentative de duplication
        with pytest.raises(ValueError, match="already exists"):
            repo.create(
                filename="different_name.pdf",
                file_hash=sample_document_data["file_hash"]
            )
    
    def test_get_by_id(self, test_repositories, sample_document_data):
        """Test de récupération par ID"""
        repo = test_repositories['document']
        
        created_doc = repo.create(
            filename=sample_document_data["filename"],
            file_hash=sample_document_data["file_hash"]
        )
        
        retrieved_doc = repo.get_by_id(created_doc.id)
        
        assert retrieved_doc is not None
        assert retrieved_doc.id == created_doc.id
        assert retrieved_doc.filename == created_doc.filename
        
        # Test avec ID inexistant
        assert repo.get_by_id(99999) is None

    def test_get_by_ids_batches_and_maps(self, test_repositories, sample_document_data):
        """Batch retrieval returns an {id: Document} mapping for existing ids."""
        repo = test_repositories['document']

        doc_a = repo.create(filename="a.pdf", file_hash="a" * 64)
        doc_b = repo.create(filename="b.pdf", file_hash="b" * 64)
        doc_c = repo.create(filename="c.pdf", file_hash="c" * 64)

        # Request two of the three ids plus one that does not exist.
        result = repo.get_by_ids([doc_a.id, doc_c.id, 99999])

        assert set(result.keys()) == {doc_a.id, doc_c.id}
        assert result[doc_a.id].filename == "a.pdf"
        assert result[doc_c.id].filename == "c.pdf"
        # A document not requested is absent; a missing id is not an error.
        assert doc_b.id not in result
        assert 99999 not in result

    def test_get_by_ids_empty_input(self, test_repositories):
        """An empty id list yields an empty mapping without querying."""
        repo = test_repositories['document']
        assert repo.get_by_ids([]) == {}

    def test_get_by_hash(self, test_repositories, sample_document_data):
        """Test de récupération par hash"""
        repo = test_repositories['document']
        
        created_doc = repo.create(
            filename=sample_document_data["filename"],
            file_hash=sample_document_data["file_hash"]
        )
        
        retrieved_doc = repo.get_by_hash(sample_document_data["file_hash"])
        
        assert retrieved_doc is not None
        assert retrieved_doc.id == created_doc.id
        
        # Test avec hash inexistant
        assert repo.get_by_hash("nonexistent_hash") is None
    
    def test_get_by_status(self, test_repositories, sample_document_data):
        """Test de récupération par statut"""
        repo = test_repositories['document']
        
        # Créer plusieurs documents avec différents statuts
        doc1 = repo.create("file1.pdf", "hash1")
        doc2 = repo.create("file2.pdf", "hash2")
        doc3 = repo.create("file3.pdf", "hash3")
        
        repo.update_status(doc2.id, "indexed", chunk_count=10)
        repo.update_status(doc3.id, "error", error_message="Test error")
        
        # Vérifications
        pending_docs = repo.get_by_status("pending")
        indexed_docs = repo.get_by_status("indexed")
        error_docs = repo.get_by_status("error")
        
        assert len(pending_docs) == 1
        assert pending_docs[0].id == doc1.id
        
        assert len(indexed_docs) == 1
        assert indexed_docs[0].id == doc2.id
        
        assert len(error_docs) == 1
        assert error_docs[0].id == doc3.id
    
    def test_update_status(self, test_repositories, sample_document_data):
        """Test de mise à jour de statut"""
        repo = test_repositories['document']
        
        doc = repo.create(
            filename=sample_document_data["filename"],
            file_hash=sample_document_data["file_hash"]
        )
        
        # Mise à jour vers indexed
        repo.update_status(doc.id, "indexed", chunk_count=15)
        
        updated_doc = repo.get_by_id(doc.id)
        assert updated_doc.status == "indexed"
        assert updated_doc.chunk_count == 15
        assert updated_doc.indexed_at is not None
        assert updated_doc.error_message is None
        
        # Mise à jour vers error
        repo.update_status(doc.id, "error", error_message="Processing failed")
        
        updated_doc = repo.get_by_id(doc.id)
        assert updated_doc.status == "error"
        assert updated_doc.error_message == "Processing failed"
    
    def test_update_status_nonexistent(self, test_repositories):
        """Test de mise à jour d'un document inexistant"""
        repo = test_repositories['document']
        
        with pytest.raises(ValueError, match="not found"):
            repo.update_status(99999, "indexed")
    
    def test_delete_document(self, test_repositories, sample_document_data):
        """Test de suppression de document"""
        repo = test_repositories['document']
        
        doc = repo.create(
            filename=sample_document_data["filename"],
            file_hash=sample_document_data["file_hash"]
        )
        
        # Suppression réussie
        assert repo.delete(doc.id) is True
        assert repo.get_by_id(doc.id) is None
        
        # Tentative de suppression d'un document inexistant
        assert repo.delete(99999) is False
    
    def test_delete_protected_document(self, test_repositories, sample_document_data):
        """Test de suppression d'un document protégé"""
        repo = test_repositories['document']
        
        doc = repo.create(
            filename=sample_document_data["filename"],
            file_hash=sample_document_data["file_hash"],
            preserve=True
        )
        
        # Suppression bloquée
        with pytest.raises(ValueError, match="protected"):
            repo.delete(doc.id)
        
        # Suppression forcée
        assert repo.delete(doc.id, force=True) is True
        assert repo.get_by_id(doc.id) is None
    
    def test_get_all_with_pagination(self, test_repositories):
        """Test de récupération avec pagination"""
        repo = test_repositories['document']
        
        # Créer plusieurs documents
        for i in range(5):
            repo.create(f"file{i}.pdf", f"hash{i}")
        
        # Test pagination
        all_docs = repo.get_all()
        assert len(all_docs) == 5
        
        limited_docs = repo.get_all(limit=2)
        assert len(limited_docs) == 2
        
        offset_docs = repo.get_all(limit=2, offset=2)
        assert len(offset_docs) == 2
        
        # Test tri
        asc_docs = repo.get_all(order_by="filename", desc_order=False)
        desc_docs = repo.get_all(order_by="filename", desc_order=True)
        
        assert asc_docs[0].filename != desc_docs[0].filename
    
    def test_get_statistics(self, test_repositories):
        """Test des statistiques"""
        repo = test_repositories['document']
        
        # État initial
        stats = repo.get_statistics()
        assert stats['total_documents'] == 0
        assert stats['count_pending'] == 0
        
        # Ajouter des documents
        doc1 = repo.create("file1.pdf", "hash1")
        doc2 = repo.create("file2.pdf", "hash2", preserve=True)  # noqa: F841
        doc3 = repo.create("file3.pdf", "hash3")
        
        repo.update_status(doc1.id, "indexed", chunk_count=10)
        repo.update_status(doc3.id, "error")
        
        stats = repo.get_statistics()
        assert stats['total_documents'] == 3
        assert stats['count_pending'] == 1
        assert stats['count_indexed'] == 1
        assert stats['count_error'] == 1
        assert stats['total_chunks'] == 10
        assert stats['protected_documents'] == 1


class TestConfigurationRepository:
    """Tests du ConfigurationRepository"""
    
    def test_get_set_configuration(self, test_repositories):
        """Test de get/set configuration"""
        repo = test_repositories['config']
        
        # Test get inexistant
        assert repo.get("nonexistent") is None
        assert repo.get_value("nonexistent") is None
        assert repo.get_value("nonexistent", "default") == "default"
        
        # Test set nouveau
        config = repo.set("test_key", "test_value")
        assert config.key == "test_key"
        assert config.value == "test_value"
        
        # Test get existant
        retrieved = repo.get("test_key")
        assert retrieved is not None
        assert retrieved.value == "test_value"
        assert repo.get_value("test_key") == "test_value"
        
        # Test update existant
        updated = repo.set("test_key", "updated_value")
        assert updated.value == "updated_value"
        assert repo.get_value("test_key") == "updated_value"
    
    def test_delete_configuration(self, test_repositories):
        """Test de suppression de configuration"""
        repo = test_repositories['config']
        
        # Créer une config
        repo.set("test_key", "test_value")
        
        # Suppression réussie
        assert repo.delete("test_key") is True
        assert repo.get("test_key") is None
        
        # Suppression inexistante
        assert repo.delete("nonexistent") is False
    
    def test_get_all_configurations(self, test_repositories):
        """Test de récupération de toutes les configurations"""
        repo = test_repositories['config']
        
        # État initial
        all_configs = repo.get_all()
        assert len(all_configs) == 0
        
        # Ajouter des configurations
        repo.set("key1", "value1")
        repo.set("key2", "value2")
        repo.set("key3", "value3")
        
        all_configs = repo.get_all()
        assert len(all_configs) == 3
        
        # Vérifier le tri par clé
        keys = [config.key for config in all_configs]
        assert keys == sorted(keys)


class TestAuditLogRepository:
    """Tests du AuditLogRepository"""
    
    def test_create_log(self, test_repositories):
        """Test de création de log d'audit"""
        repo = test_repositories['audit']
        
        log = repo.create_log(
            user_type="admin",
            action="login",
            details="Successful login",
            ip_address="192.168.1.1",
            success=True
        )
        
        assert log.id is not None
        assert log.user_type == "admin"
        assert log.action == "login"
        assert log.details == "Successful login"
        assert log.ip_address == "192.168.1.1"
        assert log.success is True
    
    def test_get_logs_with_filters(self, test_repositories):
        """Test de récupération avec filtres"""
        repo = test_repositories['audit']
        
        # Créer différents logs
        repo.create_log("admin", "login", "Admin login")
        repo.create_log("user", "chat", "User question")
        repo.create_log("admin", "upload", "Document upload")
        repo.create_log("system", "startup", "System start")
        
        # Test sans filtres
        all_logs = repo.get_logs()
        assert len(all_logs) == 4
        
        # Test filtre par user_type
        admin_logs = repo.get_logs(user_type="admin")
        assert len(admin_logs) == 2
        assert all(log.user_type == "admin" for log in admin_logs)
        
        # Test filtre par action
        login_logs = repo.get_logs(action="login")
        assert len(login_logs) == 1
        assert login_logs[0].action == "login"
        
        # Test pagination
        limited_logs = repo.get_logs(limit=2)
        assert len(limited_logs) == 2
        
        offset_logs = repo.get_logs(limit=2, offset=2)
        assert len(offset_logs) == 2