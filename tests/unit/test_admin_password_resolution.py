"""
Unit tests for the startup resolution of ADMIN_PASSWORD.

Covers resolve_admin_password: the no-op path, the override of
ADMIN_PASSWORD_HASH, the strength gate (raise in production, warn elsewhere)
and the guarantee that the clear-text password never reaches the logs.
"""

import logging

import pytest

from mimir.auth.jwt_handler import jwt_handler
from mimir.config import Settings
from mimir.security.admin_password import resolve_admin_password
from mimir.security.startup_validation import (
    DEFAULT_ADMIN_PASSWORD,
    validate_production_secrets,
)

STRONG_PASSWORD = "Xk7!vRq2Pw#tLm9Z"
WEAK_PASSWORD = "short"
RESOLVER_LOGGER_NAME = "mimir.security.admin_password"


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
            "faiss_index_path": str(tmp_path / "faiss" / "index.bin"),
            "faiss_metadata_path": str(tmp_path / "faiss" / "metadata.json"),
        }
        base.update(overrides)
        return Settings(**base)

    return _make


@pytest.fixture
def resolver_caplog(caplog):
    """Capture resolver logs despite propagate=False on project loggers."""
    resolver_logger = logging.getLogger(RESOLVER_LOGGER_NAME)
    resolver_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger=RESOLVER_LOGGER_NAME):
            yield caplog
    finally:
        resolver_logger.removeHandler(caplog.handler)


class TestResolveAdminPassword:
    """Resolution rules of ADMIN_PASSWORD into admin_password_hash."""

    def test_empty_admin_password_leaves_hash_untouched(self, make_settings):
        """Test 1: no ADMIN_PASSWORD -> the configured hash is preserved."""
        configured_hash = jwt_handler.hash_password("AnotherPassword42")
        settings = make_settings(admin_password_hash=configured_hash)

        resolve_admin_password(settings)

        assert settings.admin_password_hash == configured_hash

    def test_admin_password_overrides_the_configured_hash(self, make_settings):
        """Test 2: ADMIN_PASSWORD wins over ADMIN_PASSWORD_HASH."""
        configured_hash = jwt_handler.hash_password("AnotherPassword42")
        settings = make_settings(
            admin_password=STRONG_PASSWORD,
            admin_password_hash=configured_hash,
        )

        resolve_admin_password(settings)

        assert settings.admin_password_hash != configured_hash
        assert jwt_handler.verify_password(STRONG_PASSWORD, settings.admin_password_hash)

    def test_production_weak_password_refuses_startup(self, make_settings):
        """Test 3: production + weak ADMIN_PASSWORD -> RuntimeError, hash unchanged."""
        configured_hash = jwt_handler.hash_password("AnotherPassword42")
        settings = make_settings(
            environment="production",
            admin_password=WEAK_PASSWORD,
            admin_password_hash=configured_hash,
        )

        with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
            resolve_admin_password(settings)

        assert settings.admin_password_hash == configured_hash

    def test_development_weak_password_warns_and_applies(self, make_settings, resolver_caplog):
        """Test 4: development + weak ADMIN_PASSWORD -> warning, still applied."""
        settings = make_settings(
            environment="development",
            admin_password=WEAK_PASSWORD,
        )

        resolve_admin_password(settings)

        warning_records = [
            record
            for record in resolver_caplog.records
            if record.name == RESOLVER_LOGGER_NAME and record.levelno == logging.WARNING
        ]
        assert len(warning_records) == 1
        assert jwt_handler.verify_password(WEAK_PASSWORD, settings.admin_password_hash)

    def test_clear_text_password_never_reaches_the_logs(self, make_settings, resolver_caplog):
        """Test 5: neither the password nor the derived hash is ever logged."""
        settings = make_settings(admin_password=STRONG_PASSWORD)

        resolve_admin_password(settings)

        assert STRONG_PASSWORD not in resolver_caplog.text
        assert settings.admin_password_hash not in resolver_caplog.text

    def test_weak_password_error_message_hides_the_password(self, make_settings):
        """Test 6: the production refusal names the rules, never the value."""
        settings = make_settings(
            environment="production",
            admin_password=WEAK_PASSWORD,
        )

        with pytest.raises(RuntimeError) as exc_info:
            resolve_admin_password(settings)

        assert WEAK_PASSWORD not in str(exc_info.value)


class TestResolutionFeedsProductionValidation:
    """The default-secret check must see the hash resolution produced (ordering)."""

    def test_default_password_via_admin_password_is_still_rejected(self, make_settings):
        """Setting ADMIN_PASSWORD to the known default cannot bypass the default-secret check."""
        settings = make_settings(
            # Resolution runs outside production so the strength gate only warns:
            # this isolates the default-secret check, which is what the test targets.
            environment="development",
            jwt_secret_key="custom-production-secret-key-well-over-32-characters",
            admin_password=DEFAULT_ADMIN_PASSWORD,
            # A perfectly valid custom hash: only the resolution can reintroduce
            # the default, which is exactly what this test guards against.
            admin_password_hash=jwt_handler.hash_password("AnotherPassword42"),
        )

        resolve_admin_password(settings)

        settings.environment = "production"
        with pytest.raises(RuntimeError, match="ADMIN_PASSWORD_HASH"):
            validate_production_secrets(settings)
