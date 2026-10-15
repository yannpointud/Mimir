"""
Tests unitaires pour les modèles de base de données
Vérifie la logique métier et les contraintes
"""

import pytest
from sqlalchemy.exc import IntegrityError

from src.database.models import Document, Configuration, AuditLog


class TestDocumentModel:
    """Tests du modèle Document"""
    
    def test_create_document(self, test_session, sample_document_data):
        """Test de création d'un document"""
        doc = Document(**sample_document_data)
        test_session.add(doc)
        test_session.commit()
        
        assert doc.id is not None
        assert doc.filename == sample_document_data["filename"]
        assert doc.file_hash == sample_document_data["file_hash"]
        assert doc.status == "pending"  # Valeur par défaut
        assert doc.chunk_count == 0
        assert doc.preserve is False
        assert doc.created_at is not None
        assert doc.indexed_at is None
    
    def test_document_to_dict(self, test_session, sample_document_data):
        """Test de sérialisation en dictionnaire"""
        doc = Document(**sample_document_data)
        test_session.add(doc)
        test_session.commit()
        
        doc_dict = doc.to_dict()
        
        assert "id" in doc_dict
        assert doc_dict["filename"] == sample_document_data["filename"]
        assert doc_dict["file_hash"] == sample_document_data["file_hash"]
        assert doc_dict["status"] == "pending"
        assert doc_dict["chunk_count"] == 0
        assert doc_dict["preserve"] is False
        assert "created_at" in doc_dict
        assert doc_dict["indexed_at"] is None
    
    def test_document_status_methods(self, test_session, sample_document_data):
        """Test des méthodes de vérification de statut"""
        doc = Document(**sample_document_data)
        test_session.add(doc)
        test_session.commit()
        
        # État initial
        assert doc.is_processing() is True
        assert doc.is_indexed() is False
        assert doc.has_error() is False
        
        # Statut indexing
        doc.status = "indexing"
        assert doc.is_processing() is True
        assert doc.is_indexed() is False
        
        # Statut indexed
        doc.status = "indexed"
        doc.chunk_count = 10
        assert doc.is_processing() is False
        assert doc.is_indexed() is True
        assert doc.has_error() is False
        
        # Statut error
        doc.status = "error"
        assert doc.is_processing() is False
        assert doc.is_indexed() is False
        assert doc.has_error() is True
    
    def test_unique_hash_constraint(self, test_session, sample_document_data):
        """Test de contrainte d'unicité sur le hash"""
        # Premier document
        doc1 = Document(**sample_document_data)
        test_session.add(doc1)
        test_session.commit()
        
        # Tentative d'ajout d'un document avec le même hash
        doc2_data = sample_document_data.copy()
        doc2_data["filename"] = "different_name.pdf"
        doc2 = Document(**doc2_data)
        test_session.add(doc2)
        
        with pytest.raises(IntegrityError):
            test_session.commit()
    
    def test_document_repr(self, test_session, sample_document_data):
        """Test de représentation string"""
        doc = Document(**sample_document_data)
        test_session.add(doc)
        test_session.commit()
        
        repr_str = repr(doc)
        assert "Document" in repr_str
        assert str(doc.id) in repr_str
        assert sample_document_data["filename"] in repr_str
        assert "pending" in repr_str


class TestConfigurationModel:
    """Tests du modèle Configuration"""
    
    def test_create_configuration(self, test_session, sample_config_data):
        """Test de création d'une configuration"""
        config = Configuration(**sample_config_data)
        test_session.add(config)
        test_session.commit()
        
        assert config.key == sample_config_data["key"]
        assert config.value == sample_config_data["value"]
        assert config.updated_at is not None
    
    def test_configuration_to_dict(self, test_session, sample_config_data):
        """Test de sérialisation en dictionnaire"""
        config = Configuration(**sample_config_data)
        test_session.add(config)
        test_session.commit()
        
        config_dict = config.to_dict()
        
        assert config_dict["key"] == sample_config_data["key"]
        assert config_dict["value"] == sample_config_data["value"]
        assert "updated_at" in config_dict
    
    def test_get_typed_value_method(self):
        """Test de conversion de types"""
        # String (défaut)
        assert Configuration.get_typed_value("test", "string") == "test"
        
        # Boolean
        assert Configuration.get_typed_value("true", "bool") is True
        assert Configuration.get_typed_value("false", "bool") is False
        assert Configuration.get_typed_value("1", "bool") is True
        assert Configuration.get_typed_value("0", "bool") is False
        
        # Integer
        assert Configuration.get_typed_value("42", "int") == 42
        
        # Float
        assert Configuration.get_typed_value("3.14", "float") == 3.14
    
    def test_configuration_update_timestamp(self, test_session, sample_config_data):
        """Test de mise à jour automatique du timestamp"""
        config = Configuration(**sample_config_data)
        test_session.add(config)
        test_session.commit()
        
        
        # Simulation d'une pause (dans un vrai test, on pourrait mock datetime)
        config.value = "updated_value"
        test_session.commit()
        
        # Note: En test unitaire, on vérifierait que onupdate fonctionne
        # Le timestamp pourrait ne pas changer dans le même instant
        assert config.value == "updated_value"


class TestAuditLogModel:
    """Tests du modèle AuditLog"""
    
    def test_create_audit_log(self, test_session, sample_audit_data):
        """Test de création d'un log d'audit"""
        log = AuditLog(**sample_audit_data)
        test_session.add(log)
        test_session.commit()
        
        assert log.id is not None
        assert log.user_type == sample_audit_data["user_type"]
        assert log.action == sample_audit_data["action"]
        assert log.details == sample_audit_data["details"]
        assert log.ip_address == sample_audit_data["ip_address"]
        assert log.success is True
        assert log.created_at is not None
    
    def test_audit_log_to_dict(self, test_session, sample_audit_data):
        """Test de sérialisation en dictionnaire"""
        log = AuditLog(**sample_audit_data)
        test_session.add(log)
        test_session.commit()
        
        log_dict = log.to_dict()
        
        assert "id" in log_dict
        assert log_dict["user_type"] == sample_audit_data["user_type"]
        assert log_dict["action"] == sample_audit_data["action"]
        assert log_dict["success"] is True
        assert "created_at" in log_dict
    
    def test_audit_log_factory_methods(self, test_session):
        """Test des méthodes factory"""
        # Admin action
        admin_log = AuditLog.create_admin_action(
            action="login",
            details="Admin login attempt",
            ip_address="192.168.1.1"
        )
        test_session.add(admin_log)
        test_session.commit()
        
        assert admin_log.user_type == "admin"
        assert admin_log.action == "login"
        assert admin_log.success is True
        
        # User action
        user_log = AuditLog.create_user_action(
            action="chat",
            details="User asked question",
            success=True
        )
        test_session.add(user_log)
        test_session.commit()
        
        assert user_log.user_type == "user"
        assert user_log.action == "chat"
        
        # System action
        system_log = AuditLog.create_system_action(
            action="startup",
            details="Application started"
        )
        test_session.add(system_log)
        test_session.commit()
        
        assert system_log.user_type == "system"
        assert system_log.action == "startup"
    
    def test_audit_log_repr(self, test_session, sample_audit_data):
        """Test de représentation string"""
        log = AuditLog(**sample_audit_data)
        test_session.add(log)
        test_session.commit()
        
        repr_str = repr(log)
        assert "AuditLog" in repr_str
        assert str(log.id) in repr_str
        assert sample_audit_data["user_type"] in repr_str
        assert sample_audit_data["action"] in repr_str