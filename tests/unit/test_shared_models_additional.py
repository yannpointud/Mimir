"""
Tests unitaires supplémentaires pour le module shared/models.py

Ces tests couvrent les modèles Pydantic et leurs validations.
"""

import pytest
from pydantic import ValidationError
from datetime import datetime

from mimir.shared.models import (
    PaginationModel,
    BaseResponse,
    DocumentResponse,
    DocumentListResponse,
    DocumentStatus,
    UserType,
    ErrorResponse,
    HealthCheckResponse,
    DocumentBase,
    DocumentCreate,
    ConfigurationBase,
    FileUploadValidation,
)


class TestPaginationModel:
    """Tests pour PaginationModel."""

    def test_pagination_default_values(self):
        """Test des valeurs par défaut."""
        pagination = PaginationModel()

        # Les vrais champs du modèle PaginationModel
        assert pagination.limit == 50
        assert pagination.offset == 0
        assert pagination.order_by == "created_at"
        assert pagination.desc_order is True

    def test_pagination_custom_values(self):
        """Test avec valeurs personnalisées."""
        pagination = PaginationModel(limit=25, offset=10, order_by="filename", desc_order=False)

        assert pagination.limit == 25
        assert pagination.offset == 10
        assert pagination.order_by == "filename"
        assert pagination.desc_order is False

    def test_pagination_validation_min_limit(self):
        """Test de validation limite minimale."""
        with pytest.raises(ValidationError):
            PaginationModel(limit=0)

        with pytest.raises(ValidationError):
            PaginationModel(limit=-1)

    def test_pagination_validation_max_limit(self):
        """Test de validation limite maximale."""
        with pytest.raises(ValidationError):
            PaginationModel(limit=1001)

        # Limite maximale autorisée devrait passer
        pagination = PaginationModel(limit=1000)
        assert pagination.limit == 1000

    def test_pagination_validation_min_offset(self):
        """Test de validation offset minimal."""
        with pytest.raises(ValidationError):
            PaginationModel(offset=-1)

        # Offset 0 devrait être valide
        pagination = PaginationModel(offset=0)
        assert pagination.offset == 0

    def test_pagination_edge_cases(self):
        """Test des cas limites."""
        # Limite minimale
        pagination = PaginationModel(limit=1, offset=0)
        assert pagination.limit == 1
        assert pagination.offset == 0

        # Grande offset
        pagination = PaginationModel(limit=10, offset=1000)
        assert pagination.offset == 1000


class TestBaseResponse:
    """Tests pour BaseResponse."""

    def test_base_response_success(self):
        """Test de réponse de base avec succès."""
        response = BaseResponse(success=True, message="Operation completed")

        assert response.success is True
        assert response.message == "Operation completed"
        assert isinstance(response.timestamp, datetime)

    def test_base_response_error(self):
        """Test de réponse de base avec erreur."""
        response = BaseResponse(success=False, message="Operation failed")

        assert response.success is False
        assert response.message == "Operation failed"

    def test_base_response_minimal(self):
        """Test de réponse minimale."""
        response = BaseResponse()

        # Valeurs par défaut
        assert response.success is True
        assert response.message is None
        assert isinstance(response.timestamp, datetime)


class TestDocumentModels:
    """Tests pour les modèles de documents."""

    def test_document_base_creation(self):
        """Test de création DocumentBase - CORRIGÉ: DocumentBase n'a pas file_hash."""
        doc = DocumentBase(filename="test.pdf", path="/uploads/test.pdf", preserve=True)

        assert doc.filename == "test.pdf"
        assert doc.path == "/uploads/test.pdf"
        assert doc.preserve is True

    def test_document_create_with_optional_fields(self):
        """Test DocumentCreate avec champs requis - CORRIGÉ: file_hash requis."""
        doc = DocumentCreate(
            filename="test.pdf",
            file_hash="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        )

        assert doc.filename == "test.pdf"
        assert doc.file_hash == "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        assert doc.preserve is False  # valeur par défaut

    def test_document_create_invalid_hash(self):
        """Test DocumentCreate avec hash non hexadécimal"""
        with pytest.raises(ValueError, match="Hash must be hexadecimal"):
            DocumentCreate(
                filename="test.pdf",
                file_hash="ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ",
            )

    def test_validate_filename_valid(self):
        """Test validation de nom de fichier valide"""
        from mimir.shared.models import validate_filename

        assert validate_filename("test.pdf") is True
        assert validate_filename("document_2024.txt") is True
        assert validate_filename("file-name.md") is True

    def test_validate_filename_absolute_path(self):
        """Test validation avec chemin absolu - doit échouer"""
        from mimir.shared.models import validate_filename

        assert validate_filename("/absolute/path/file.pdf") is False
        assert validate_filename("C:\\Windows\\file.txt") is False

    def test_validate_filename_relative_path(self):
        """Test validation avec chemin relatif - doit échouer"""
        from mimir.shared.models import validate_filename

        assert validate_filename("../../../etc/passwd") is False
        assert validate_filename("subdir/../file.txt") is False

    def test_validate_filename_dangerous_chars(self):
        """Test validation avec caractères dangereux"""
        from mimir.shared.models import validate_filename

        assert validate_filename("file<script>.pdf") is False
        assert validate_filename("file|pipe.txt") is False
        assert validate_filename("file*wildcard.doc") is False

    def test_validate_filename_length(self):
        """Test validation de la longueur du nom"""
        from mimir.shared.models import validate_filename

        # Nom vide
        assert validate_filename("") is False
        # Nom trop long (> 255 caractères)
        assert validate_filename("a" * 256) is False
        # Nom de longueur limite acceptable
        assert validate_filename("a" * 255) is True

    def test_document_response_with_orm_data(self):
        """Test DocumentResponse avec vrais champs ORM - CORRIGÉ."""
        response = DocumentResponse(
            id=1,
            filename="test.pdf",
            path="/uploads/test.pdf",
            file_hash="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            status=DocumentStatus.INDEXED,
            chunk_count=5,
            preserve=False,
            created_at=datetime.now(),
        )

        assert response.id == 1
        assert response.filename == "test.pdf"
        assert response.status == DocumentStatus.INDEXED
        assert response.chunk_count == 5

    def test_document_list_response(self):
        """Test DocumentListResponse - CORRIGÉ: vraie structure."""
        response = DocumentListResponse(
            success=True,
            message="Documents retrieved",
            documents=[],
            total_count=2,
            pagination={"page": 1, "size": 10},
        )

        assert response.success is True
        assert response.documents == []
        assert response.total_count == 2
        assert response.pagination["page"] == 1

    def test_document_list_response_pagination_info(self):
        """Test des informations de pagination - CORRIGÉ."""
        response = DocumentListResponse(
            success=True,
            documents=[],
            total_count=150,
            pagination={"page": 3, "size": 25, "total_pages": 6},
        )

        assert response.total_count == 150
        assert response.pagination["page"] == 3
        assert response.pagination["size"] == 25
        assert response.pagination["total_pages"] == 6


class TestValidationModels:
    """Tests pour les modèles de validation."""

    def test_file_upload_validation_success(self):
        """Test de validation d'upload réussie."""
        # FileUploadValidation peut ne pas avoir ces champs exacts
        validation = FileUploadValidation(allowed_extensions=[".pdf", ".docx", ".txt"])

        assert ".pdf" in validation.allowed_extensions

    def test_error_response(self):
        """Test du modèle ErrorResponse."""
        error = ErrorResponse(
            error_code="VALIDATION_ERROR",
            error_message="Invalid input provided",
            details={"field": "filename", "issue": "too_long"},
        )

        assert error.error_code == "VALIDATION_ERROR"
        assert error.error_message == "Invalid input provided"
        assert error.details["field"] == "filename"

    def test_health_check_response(self):
        """Test du modèle HealthCheckResponse."""
        health = HealthCheckResponse(
            success=True, status="healthy", checks={"database": {"healthy": True}}
        )

        assert health.success is True
        assert health.status == "healthy"
        assert health.checks["database"]["healthy"] is True


class TestEnumModels:
    """Tests pour les modèles d'énumération."""

    def test_document_status_enum(self):
        """Test de l'énumération DocumentStatus - CORRIGÉ: vraies valeurs."""
        assert hasattr(DocumentStatus, "PENDING")
        assert hasattr(DocumentStatus, "INDEXING")
        assert hasattr(DocumentStatus, "INDEXED")
        assert hasattr(DocumentStatus, "ERROR")

        # Test des valeurs
        assert DocumentStatus.PENDING == "pending"
        assert DocumentStatus.INDEXING == "indexing"
        assert DocumentStatus.INDEXED == "indexed"
        assert DocumentStatus.ERROR == "error"

    def test_user_type_enum(self):
        """Test de l'énumération UserType - CORRIGÉ: vraies valeurs."""
        assert hasattr(UserType, "ADMIN")
        assert hasattr(UserType, "USER")
        assert hasattr(UserType, "SYSTEM")

        # Test des valeurs
        assert UserType.ADMIN == "admin"
        assert UserType.USER == "user"
        assert UserType.SYSTEM == "system"


class TestModelSerialization:
    """Tests pour la sérialisation des modèles."""

    def test_model_serialization(self):
        """Test de sérialisation des modèles."""
        pagination = PaginationModel(limit=25, offset=10)

        # Utiliser model_dump au lieu de dict (Pydantic V2)
        data = pagination.model_dump()

        assert data["limit"] == 25
        assert data["offset"] == 10
        assert data["order_by"] == "created_at"
        assert data["desc_order"] is True

    def test_response_model_validation(self):
        """Test de validation des modèles de réponse."""
        # Données valides pour BaseResponse
        response = BaseResponse(success=True, message="Success")
        assert response.success is True
        assert response.message == "Success"

    def test_configuration_models(self):
        """Test des modèles de configuration."""
        config_base = ConfigurationBase(key="api_key", value="secret_value")

        assert config_base.key == "api_key"
        assert config_base.value == "secret_value"


class TestEdgeCases:
    """Tests des cas limites."""

    def test_extreme_pagination_values(self):
        """Test avec valeurs extrêmes de pagination."""
        # Limite maximale
        pagination = PaginationModel(limit=1000, offset=999999)
        assert pagination.limit == 1000
        assert pagination.offset == 999999

        # Limite minimale
        pagination = PaginationModel(limit=1, offset=0)
        assert pagination.limit == 1
        assert pagination.offset == 0

    def test_boundary_conditions(self):
        """Test des conditions aux limites."""
        # Exactement à la limite maximale
        pagination = PaginationModel(limit=1000)
        assert pagination.limit == 1000

        # Exactement à la limite minimale
        pagination = PaginationModel(limit=1)
        assert pagination.limit == 1

    def test_empty_data_handling(self):
        """Test de gestion des données vides."""
        # Response avec message vide
        response = BaseResponse(message="")
        assert response.message == ""

        # BaseResponse minimale
        response = BaseResponse()
        assert response.success is True
        assert response.message is None
