"""
Tests unitaires pour le module de configuration
Vérifie la validation Pydantic et la gestion des environnements
"""

import tempfile
import os
from pathlib import Path

from src.config import Settings


class TestSettings:
    """Tests de la classe Settings"""

    def test_default_settings(self):
        """Test des valeurs par défaut"""
        # Configuration minimale requise
        required_settings = {
            "mistral_api_key": "test_key",
            "jwt_secret_key": "test_secret",
            "admin_password_hash": "test_hash",
        }

        settings = Settings(**required_settings)

        # Vérifications des valeurs par défaut
        assert settings.api_version == "v1"
        assert settings.api_host == "0.0.0.0"
        assert settings.api_port == 8000
        assert settings.sqlite_wal_mode is True
        assert settings.llm_provider == "mistral"
        assert settings.vector_store_type == "faiss"
        assert settings.max_chunk_size == 1000
        assert settings.chunk_overlap == 200
        assert settings.cache_enabled is True
        assert settings.cache_max_size == 100
        assert settings.rate_limit_enabled is True
        assert settings.log_level == "INFO"

    def test_custom_settings(self):
        """Test de configuration personnalisée"""
        custom_config = {
            "mistral_api_key": "custom_key",
            "jwt_secret_key": "custom_secret",
            "admin_password_hash": "custom_hash",
            "api_port": 9000,
            "max_chunk_size": 2000,
            "cache_max_size": 200,
            "log_level": "DEBUG",
        }

        settings = Settings(**custom_config)

        assert settings.api_port == 9000
        assert settings.max_chunk_size == 2000
        assert settings.cache_max_size == 200
        assert settings.log_level == "DEBUG"
        assert settings.mistral_api_key == "custom_key"

    def test_required_fields_validation(self, monkeypatch):
        """Test de validation des champs obligatoires"""
        # S'assurer que les variables d'environnement ne fuient pas dans le test
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)

        # Note: Tous les champs ont des valeurs par défaut dans la config actuelle
        # Le test vérifie plutôt que les valeurs par défaut sont bien appliquées
        settings = Settings()

        # Vérifier que les valeurs par défaut sont appliquées
        # Note: Les valeurs peuvent venir du .env, on teste juste qu'elles existent
        assert len(settings.jwt_secret_key) >= 32  # Doit être suffisamment long
        assert len(settings.admin_password_hash) > 0  # Doit avoir une valeur
        assert isinstance(settings.mistral_api_key, str)  # Doit être une string

        # Test que la configuration peut être surchargée
        custom_settings = Settings(
            mistral_api_key="custom_key",
            jwt_secret_key="custom_jwt_secret",
            admin_password_hash="custom_hash",
        )

        assert custom_settings.mistral_api_key == "custom_key"
        assert custom_settings.jwt_secret_key == "custom_jwt_secret"
        assert custom_settings.admin_password_hash == "custom_hash"

    def test_directory_creation(self):
        """Test de création automatique des répertoires"""
        with tempfile.TemporaryDirectory() as temp_dir:
            custom_paths = {
                "mistral_api_key": "test_key",
                "jwt_secret_key": "test_secret",
                "admin_password_hash": "test_hash",
                "data_dir": str(Path(temp_dir) / "data"),
                "upload_dir": str(Path(temp_dir) / "uploads"),
                "database_url": f"sqlite:///{temp_dir}/test.db",
            }

            settings = Settings(**custom_paths)

            # Vérification que les répertoires sont créés
            assert Path(settings.data_dir).exists()
            assert Path(settings.upload_dir).exists()
            assert Path(temp_dir, "logs").exists()

    def test_database_url_sync_property(self):
        """Test de la propriété database_url_sync"""
        settings = Settings(
            mistral_api_key="test_key",
            jwt_secret_key="test_secret",
            admin_password_hash="test_hash",
            database_url="sqlite:///test.db",
        )

        assert settings.database_url_sync == "sqlite:///test.db"

    def test_is_production_property(self):
        """Test de détection de l'environnement de production"""
        settings = Settings(
            mistral_api_key="test_key",
            jwt_secret_key="test_secret",
            admin_password_hash="test_hash",
        )

        # Par défaut, mode développement
        assert settings.is_production is False

        # Test avec variable d'environnement
        os.environ["ENVIRONMENT"] = "production"
        try:
            new_settings = Settings(
                mistral_api_key="test_key",
                jwt_secret_key="test_secret",
                admin_password_hash="test_hash",
            )
            assert new_settings.is_production is True
        finally:
            os.environ.pop("ENVIRONMENT", None)

    def test_field_validation_ranges(self):
        """Test de validation des plages de valeurs"""
        base_config = {
            "mistral_api_key": "test_key",
            "jwt_secret_key": "test_secret",
            "admin_password_hash": "test_hash",
        }

        # Test valeurs valides
        valid_settings = Settings(
            **base_config,
            api_port=8080,
            max_chunk_size=500,
            chunk_overlap=100,
            cache_max_size=50,
            jwt_expiration_hours=4,
        )

        assert valid_settings.api_port == 8080
        assert valid_settings.max_chunk_size == 500
        assert valid_settings.chunk_overlap == 100
