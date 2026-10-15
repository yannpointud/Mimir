"""
Unit tests for production secrets startup validation.

Covers the pure validator (validate_production_secrets) and, in a later
task, the application startup fail-fast wiring in backend/main.py.
"""

import logging
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src.auth.jwt_handler import jwt_handler
from src.config import Settings
from src.security.startup_validation import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_JWT_SECRET,
    validate_production_secrets,
)

# Custom secret used to represent a properly configured production deployment
CUSTOM_JWT_SECRET = "custom-production-secret-key-well-over-32-characters"
VALIDATION_LOGGER_NAME = "src.security.startup_validation"


@pytest.fixture
def make_settings(tmp_path):
    """Build Settings instances with isolated directories (conftest pattern)."""

    def _make(**overrides):
        base = {
            "database_url": f"sqlite:///{tmp_path / 'test.db'}",
            "sqlite_wal_mode": False,
            "mistral_api_key": "test_key",
            "data_dir": str(tmp_path / "data"),
            "upload_dir": str(tmp_path / "uploads"),
            "watch_folder": str(tmp_path / "watch"),
            "faiss_index_path": str(tmp_path / "faiss" / "index.bin"),
            "faiss_metadata_path": str(tmp_path / "faiss" / "metadata.pkl"),
            "cache_enabled": False,
        }
        base.update(overrides)
        return Settings(**base)

    return _make


@pytest.fixture
def validation_caplog(caplog):
    """Capture validator logs despite propagate=False on project loggers.

    The project logger factory (src.monitoring.logger.setup_logger) sets
    propagate=False, so records never reach the root logger where pytest's
    caplog listens. Attaching caplog's handler directly to the module
    logger makes the records observable in tests.
    """
    validation_logger = logging.getLogger(VALIDATION_LOGGER_NAME)
    validation_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger=VALIDATION_LOGGER_NAME):
            yield caplog
    finally:
        validation_logger.removeHandler(caplog.handler)


class TestValidateProductionSecrets:
    """Pure validator behavior: RuntimeError in production, warning elsewhere."""

    def test_production_default_jwt_raises_naming_variable(self, make_settings):
        """Test 1: production + default JWT secret -> RuntimeError names JWT_SECRET_KEY."""
        custom_admin_hash = jwt_handler.hash_password("AnotherPassword42")
        settings = make_settings(
            environment="production",
            jwt_secret_key=DEFAULT_JWT_SECRET,
            admin_password_hash=custom_admin_hash,
        )

        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY") as exc_info:
            validate_production_secrets(settings)

        assert "ADMIN_PASSWORD_HASH" not in str(exc_info.value)

    def test_production_default_admin_password_rehashed_raises(self, make_settings):
        """Test 2: default admin password detected even with a fresh salt."""
        # Regenerate the hash of the default password with a different salt:
        # string comparison against the config default hash would miss this.
        rehashed_default = jwt_handler.hash_password(DEFAULT_ADMIN_PASSWORD)
        settings = make_settings(
            environment="production",
            jwt_secret_key=CUSTOM_JWT_SECRET,
            admin_password_hash=rehashed_default,
        )

        with pytest.raises(RuntimeError, match="ADMIN_PASSWORD_HASH") as exc_info:
            validate_production_secrets(settings)

        assert "JWT_SECRET_KEY" not in str(exc_info.value)

    def test_production_both_defaults_names_both_variables(self, make_settings):
        """Test 3: both defaults -> error message names both variables."""
        settings = make_settings(
            environment="production",
            jwt_secret_key=DEFAULT_JWT_SECRET,
            # No admin_password_hash override: config default is the Abc1234 hash
        )

        with pytest.raises(RuntimeError) as exc_info:
            validate_production_secrets(settings)

        message = str(exc_info.value)
        assert "JWT_SECRET_KEY" in message
        assert "ADMIN_PASSWORD_HASH" in message

    def test_production_custom_secrets_pass_silently(
        self, make_settings, validation_caplog
    ):
        """Test 4: production + custom secrets -> no raise, no warning."""
        custom_admin_hash = jwt_handler.hash_password("AnotherPassword42")
        settings = make_settings(
            environment="production",
            jwt_secret_key=CUSTOM_JWT_SECRET,
            admin_password_hash=custom_admin_hash,
        )

        validate_production_secrets(settings)

        warning_records = [
            record
            for record in validation_caplog.records
            if record.name == VALIDATION_LOGGER_NAME
            and record.levelno >= logging.WARNING
        ]
        assert warning_records == []

    def test_development_defaults_warn_and_continue(
        self, make_settings, validation_caplog
    ):
        """Test 5: development + defaults -> no raise, warning names variables."""
        settings = make_settings(
            environment="development",
            jwt_secret_key=DEFAULT_JWT_SECRET,
        )

        # Must not raise
        validate_production_secrets(settings)

        warning_records = [
            record
            for record in validation_caplog.records
            if record.name == VALIDATION_LOGGER_NAME
            and record.levelno == logging.WARNING
        ]
        assert len(warning_records) == 1
        assert "JWT_SECRET_KEY" in validation_caplog.text
        assert "ADMIN_PASSWORD_HASH" in validation_caplog.text

    def test_no_secret_values_leaked_in_message_or_logs(
        self, make_settings, validation_caplog
    ):
        """Test 6: neither the JWT secret value nor the hash ever appear anywhere."""
        # Production path: exception message must not leak values
        prod_settings = make_settings(
            environment="production",
            jwt_secret_key=DEFAULT_JWT_SECRET,
        )
        with pytest.raises(RuntimeError) as exc_info:
            validate_production_secrets(prod_settings)

        message = str(exc_info.value)
        assert prod_settings.jwt_secret_key not in message
        assert prod_settings.admin_password_hash not in message

        # Development path: warning logs must not leak values
        dev_settings = make_settings(
            environment="development",
            jwt_secret_key=DEFAULT_JWT_SECRET,
        )
        validate_production_secrets(dev_settings)

        assert dev_settings.jwt_secret_key not in validation_caplog.text
        assert dev_settings.admin_password_hash not in validation_caplog.text


class TestStartupFailFast:
    """Application startup wiring: the lifespan refuses to boot in production.

    Proves that a RuntimeError raised in the
    lifespan before yield propagates through `with TestClient(app)`.
    """

    def test_production_startup_refuses_default_secrets(self, monkeypatch, caplog):
        import src.config as config_module
        from backend.main import app

        # Production environment with default secrets (jwt pinned explicitly
        # so the test stays deterministic regardless of any local .env)
        monkeypatch.setattr(config_module.settings, "environment", "production")
        monkeypatch.setattr(
            config_module.settings, "jwt_secret_key", DEFAULT_JWT_SECRET
        )

        # Track init_database calls: the refusal must precede DB initialization
        init_db_mock = Mock()
        monkeypatch.setattr("backend.main.init_database", init_db_mock)

        # The "main" logger has propagate=False (setup_logger); attach caplog's
        # handler directly so its records are observable in this test.
        main_logger = logging.getLogger("main")
        main_logger.addHandler(caplog.handler)
        try:
            # Entering the TestClient context runs the lifespan and propagates the error
            with (
                caplog.at_level(logging.INFO, logger="main"),
                pytest.raises(RuntimeError, match="JWT_SECRET_KEY"),
                TestClient(app),
            ):
                pass
        finally:
            main_logger.removeHandler(caplog.handler)

        # Proof that the refusal happened before init_database()
        assert "Database initialized" not in caplog.text
        init_db_mock.assert_not_called()
