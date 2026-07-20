"""
Shared constants for the Mimir application.

This module holds cross-layer constants and helpers that must be importable
by API endpoints without creating circular imports (same role as shared/models.py).
"""

__all__ = ["MASKED_VALUE", "SENSITIVE_CONFIG_KEYS", "mask_secrets"]

# Total mask applied to every secret value in admin responses (D-02):
# no character of the real secret is ever revealed.
MASKED_VALUE = "***MASKED***"

# Configuration keys whose values must never leave the backend in clear text (D-01).
SENSITIVE_CONFIG_KEYS = frozenset({
    "mistral_api_key",
    "smtp_password",
    "jwt_secret_key",
    "admin_password_hash",
})


def mask_secrets(config: dict) -> dict:
    """
    Return a copy of the config dict with all sensitive values fully masked.

    Falsy sensitive values (empty string, None) are left untouched so that
    a missing configuration remains visible to the administrator.

    Args:
        config: Configuration dictionary possibly containing secret values

    Returns:
        dict: New dictionary with sensitive truthy values replaced by MASKED_VALUE
    """
    return {
        k: (MASKED_VALUE if k in SENSITIVE_CONFIG_KEYS and v else v)
        for k, v in config.items()
    }
