"""
Pytest configuration for Mimir tests
Common fixtures and test configuration
"""

import pytest
import tempfile
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys

# Add backend to PATH
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../backend'))

from src.config import Settings
from src.database.models import Base
from src.database.connection import DatabaseManager
from src.database.repository import create_repositories


@pytest.fixture(scope="session")
def test_settings():
    """Test configuration with temporary database"""
    with tempfile.TemporaryDirectory() as temp_dir:
        test_db_path = Path(temp_dir) / "test.db"
        
        # Test configuration
        test_config = {
            "database_url": f"sqlite:///{test_db_path}",
            "sqlite_wal_mode": False,  # Keep it simple for tests
            "mistral_api_key": "test_key",
            "jwt_secret_key": "test_secret_key",
            "admin_password_hash": "$2b$12$test_hash",
            "data_dir": str(Path(temp_dir) / "data"),
            "upload_dir": str(Path(temp_dir) / "uploads"),
            "watch_folder": str(Path(temp_dir) / "watch"),
            "cache_enabled": False,  # Disabled for tests
            "log_level": "DEBUG"
        }
        
        yield Settings(**test_config)


@pytest.fixture(scope="session")
def test_engine(test_settings):
    """Test database engine"""
    engine = create_engine(
        test_settings.database_url_sync,
        echo=False,
        connect_args={"check_same_thread": False}
    )
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    yield engine
    
    # Cleanup
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def test_session(test_engine):
    """Test session with automatic rollback"""
    connection = test_engine.connect()
    transaction = connection.begin()
    
    session = sessionmaker(bind=connection)()
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def test_repositories(test_session):
    """Test repositories"""
    return create_repositories(test_session)


@pytest.fixture
def sample_document_data():
    """Test data for documents"""
    return {
        "filename": "test_document.pdf",
        "file_hash": "a1b2c3d4e5f6789012345678901234567890123456789012345678901234567890",
        "path": "/test/path/test_document.pdf",
        "preserve": False
    }


@pytest.fixture
def sample_config_data():
    """Test data for configuration"""
    return {
        "key": "test_setting",
        "value": "test_value"
    }


@pytest.fixture
def sample_audit_data():
    """Test data for audit"""
    return {
        "user_type": "admin",
        "action": "test_action",
        "details": "Test action details",
        "ip_address": "127.0.0.1",
        "success": True
    }


@pytest.fixture(autouse=True)
def disable_rate_limiter():
    """
    Disable the slowapi rate limiter for every test (autouse).

    The limiter uses an in-process memory:// storage shared by the whole
    pytest run. Without this fixture, existing tests that chain login/chat/
    upload calls would receive unexpected 429 responses as soon as the
    per-route decorators are applied, making the suite flaky.

    Tests that specifically exercise the 429 path re-enable the limiter
    locally (limiter.enabled = True + limiter.reset()) inside their own body.
    Teardown restores the original enabled flag and resets the in-memory
    counters so no state leaks between tests.
    """
    from src.api.middleware.rate_limit import limiter

    original_enabled = limiter.enabled
    limiter.enabled = False

    yield

    limiter.enabled = original_enabled
    limiter.reset()


# Fixtures for API tests (future)
@pytest.fixture
def test_app():
    """Test FastAPI application"""
    from src.config import settings
    
    # Override settings for tests
    original_values = {}
    test_values = {
        'cache_enabled': False,
        'log_level': 'DEBUG'
    }
    
    # Save and override
    for key, value in test_values.items():
        original_values[key] = getattr(settings, key)
        setattr(settings, key, value)
    
    from main import app
    
    yield app
    
    # Restore
    for key, value in original_values.items():
        setattr(settings, key, value)


# Test utilities

def create_test_file(directory: Path, filename: str, content: str = "test content") -> Path:
    """Create a test file"""
    file_path = directory / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)
    return file_path


def assert_model_dict_subset(model_dict: dict, expected_subset: dict):
    """Verify that a model dictionary contains the expected key/value pairs"""
    for key, expected_value in expected_subset.items():
        assert key in model_dict, f"Key '{key}' not found in model dict"
        assert model_dict[key] == expected_value, f"Expected {key}={expected_value}, got {model_dict[key]}"