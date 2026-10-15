"""
Unit tests for the shared secret masking module.

Verifies that mask_secrets fully masks all sensitive configuration keys
with the shared MASKED_VALUE constant, without mutating the input dict.
"""

import pytest  # noqa: F401

from src.shared.constants import MASKED_VALUE, SENSITIVE_CONFIG_KEYS, mask_secrets


class TestMaskSecrets:
    """Tests for mask_secrets, MASKED_VALUE and SENSITIVE_CONFIG_KEYS."""

    def test_masks_all_sensitive_keys_with_non_empty_values(self):
        """Every key in SENSITIVE_CONFIG_KEYS with a truthy value is replaced by MASKED_VALUE."""
        config = {
            "mistral_api_key": "sk-real-mistral-key",
            "smtp_password": "smtp-secret",
            "jwt_secret_key": "super-secret-jwt-key-32-chars-long",
            "admin_password_hash": "$2b$12$somerealhashvalue",
            "admin_password": "ClearTextAdminPwd42!",
        }

        result = mask_secrets(config)

        for key in SENSITIVE_CONFIG_KEYS:
            assert result[key] == MASKED_VALUE, f"Key '{key}' should be masked"
        # No original secret value must survive in the result
        for original_value in config.values():
            assert original_value not in result.values()

    def test_non_sensitive_keys_are_unchanged(self):
        """Keys not in SENSITIVE_CONFIG_KEYS keep their original values."""
        config = {
            "llm_provider": "mistral",
            "maintenance_mode": False,
            "max_chunk_size": 1000,
            "mistral_api_key": "sk-real-key",
        }

        result = mask_secrets(config)

        assert result["llm_provider"] == "mistral"
        assert result["maintenance_mode"] is False
        assert result["max_chunk_size"] == 1000
        assert result["mistral_api_key"] == MASKED_VALUE

    def test_empty_or_none_sensitive_values_are_not_masked(self):
        """Falsy sensitive values stay visible so missing config remains detectable."""
        config = {
            "mistral_api_key": "",
            "smtp_password": None,
            "jwt_secret_key": "actual-secret-key",
        }

        result = mask_secrets(config)

        assert result["mistral_api_key"] == ""
        assert result["smtp_password"] is None
        assert result["jwt_secret_key"] == MASKED_VALUE

    def test_mask_secrets_returns_a_copy_without_mutating_input(self):
        """The input dict must not be mutated; a new dict is returned."""
        config = {
            "mistral_api_key": "sk-real-key",
            "llm_provider": "mistral",
        }
        snapshot = dict(config)

        result = mask_secrets(config)

        assert config == snapshot, "Input dict must not be mutated"
        assert result is not config, "A new dict must be returned"

    def test_masked_value_constant_is_exact(self):
        """MASKED_VALUE is exactly ***MASKED*** (total mask)."""
        assert MASKED_VALUE == "***MASKED***"

    def test_sensitive_config_keys_contains_exactly_the_known_secrets(self):
        """SENSITIVE_CONFIG_KEYS covers exactly the known secret keys."""
        assert frozenset({
            "mistral_api_key",
            "smtp_password",
            "jwt_secret_key",
            "admin_password_hash",
            "admin_password",
        }) == SENSITIVE_CONFIG_KEYS
