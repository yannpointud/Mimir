"""
Startup validation of production secrets.

Fails fast when default secrets are detected in a production environment,
warns (and continues) in any other environment. Neither the secret value
nor the password hash is ever included in the error message or the logs;
only the environment variable names are reported.
"""

from src.auth.jwt_handler import jwt_handler
from src.monitoring.logger import setup_logger

logger = setup_logger(__name__)

# Exact default values from src/config.py — used for detection only.
DEFAULT_JWT_SECRET = "dev-secret-key-change-in-production-minimum-32-chars-long"
DEFAULT_ADMIN_PASSWORD = "Abc1234"

__all__ = ["validate_production_secrets"]


def validate_production_secrets(settings) -> None:
    """
    Refuse to start in production when default secrets are detected.

    Pure function taking settings as a parameter (testable without the app).
    Detection rules:
    - JWT_SECRET_KEY: direct comparison with the code default
    - ADMIN_PASSWORD_HASH: bcrypt verification of the default password
      against the effective hash, which also catches a hash regenerated
      with a different salt. The effective hash is
      settings.admin_password_hash; there is no DB override.

    Args:
        settings: Application Settings instance (src.config.Settings)

    Raises:
        RuntimeError: In production, when at least one default secret is
            detected. The message names only the offending variable(s),
            never their values.
    """
    issues = []

    if settings.jwt_secret_key == DEFAULT_JWT_SECRET:
        issues.append("JWT_SECRET_KEY")

    # bcrypt verification detects the default password even when the hash
    # was regenerated with another salt; string comparison would not.
    if jwt_handler.verify_password(DEFAULT_ADMIN_PASSWORD, settings.admin_password_hash):
        issues.append("ADMIN_PASSWORD_HASH")

    if not issues:
        return

    joined_names = ", ".join(issues)
    if settings.is_production:
        # Fail fast before any service initialization.
        raise RuntimeError(
            f"Refusing to start in production: default value detected for {joined_names}"
        )

    # Outside production, warn and let startup continue.
    logger.warning(f"Default secrets in use (non-production only): {joined_names}")
