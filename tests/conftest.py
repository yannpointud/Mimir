"""
Configuration pytest pour les tests Mimir
Fixtures communes et configuration des tests
"""

import pytest
import tempfile
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys

# Ajout du backend au PATH
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../backend'))

from src.config import Settings
from src.database.models import Base
from src.database.connection import DatabaseManager
from src.database.repository import create_repositories


@pytest.fixture(scope="session")
def test_settings():
    """Configuration de test avec base de données temporaire"""
    with tempfile.TemporaryDirectory() as temp_dir:
        test_db_path = Path(temp_dir) / "test.db"
        
        # Configuration de test
        test_config = {
            "database_url": f"sqlite:///{test_db_path}",
            "sqlite_wal_mode": False,  # Simplicité pour les tests
            "mistral_api_key": "test_key",
            "jwt_secret_key": "test_secret_key",
            "admin_password_hash": "$2b$12$test_hash",
            "data_dir": str(Path(temp_dir) / "data"),
            "upload_dir": str(Path(temp_dir) / "uploads"),
            "watch_folder": str(Path(temp_dir) / "watch"),
            "cache_enabled": False,  # Désactivé pour tests
            "log_level": "DEBUG"
        }
        
        yield Settings(**test_config)


@pytest.fixture(scope="session")
def test_engine(test_settings):
    """Moteur de base de données de test"""
    engine = create_engine(
        test_settings.database_url_sync,
        echo=False,
        connect_args={"check_same_thread": False}
    )
    
    # Création des tables
    Base.metadata.create_all(bind=engine)
    
    yield engine
    
    # Nettoyage
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def test_session(test_engine):
    """Session de test avec rollback automatique"""
    connection = test_engine.connect()
    transaction = connection.begin()
    
    session = sessionmaker(bind=connection)()
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def test_repositories(test_session):
    """Repositories de test"""
    return create_repositories(test_session)


@pytest.fixture
def sample_document_data():
    """Données de test pour les documents"""
    return {
        "filename": "test_document.pdf",
        "file_hash": "a1b2c3d4e5f6789012345678901234567890123456789012345678901234567890",
        "path": "/test/path/test_document.pdf",
        "preserve": False
    }


@pytest.fixture
def sample_config_data():
    """Données de test pour la configuration"""
    return {
        "key": "test_setting",
        "value": "test_value"
    }


@pytest.fixture
def sample_audit_data():
    """Données de test pour l'audit"""
    return {
        "user_type": "admin",
        "action": "test_action",
        "details": "Test action details",
        "ip_address": "127.0.0.1",
        "success": True
    }


# Fixtures pour les tests d'API (futures)
@pytest.fixture
def test_app():
    """Application FastAPI de test"""
    from src.config import settings
    
    # Override des settings pour les tests
    original_values = {}
    test_values = {
        'cache_enabled': False,
        'log_level': 'DEBUG'
    }
    
    # Sauvegarde et override
    for key, value in test_values.items():
        original_values[key] = getattr(settings, key)
        setattr(settings, key, value)
    
    from main import app
    
    yield app
    
    # Restauration
    for key, value in original_values.items():
        setattr(settings, key, value)


# Utilitaires de test

def create_test_file(directory: Path, filename: str, content: str = "test content") -> Path:
    """Crée un fichier de test"""
    file_path = directory / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)
    return file_path


def assert_model_dict_subset(model_dict: dict, expected_subset: dict):
    """Vérifie qu'un dictionnaire de modèle contient les clés/valeurs attendues"""
    for key, expected_value in expected_subset.items():
        assert key in model_dict, f"Key '{key}' not found in model dict"
        assert model_dict[key] == expected_value, f"Expected {key}={expected_value}, got {model_dict[key]}"