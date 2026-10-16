"""
Admin password resolution at startup.

Lets an operator supply the admin password in clear text via ADMIN_PASSWORD
instead of pre-computing an ADMIN_PASSWORD_HASH by hand. Hand-crafting a hash
requires a local Python/argon2 toolchain, which a container deployment does
not have; this closes that gap without changing how the hash is consumed.

The clear-text password is read once, hashed, and never logged. The resolved
hash lives in memory only: it is NOT written back to .env (unwritable from the
container) nor persisted, so every start re-derives it from the environment.
"""

from mimir.auth.jwt_handler import jwt_handler
from mimir.auth.password_utils import validate_password_strength
from mimir.monitoring.logger import setup_logger

logger = setup_logger(__name__)

__all__ = ["resolve_admin_password"]


def resolve_admin_password(settings) -> None:
    """Derive settings.admin_password_hash from ADMIN_PASSWORD when it is set.

    Must run before validate_production_secrets so the default-secret checks apply to
    the hash the application will actually use.

    Resolution rules:
    - ADMIN_PASSWORD empty (the default): no-op, the deployment keeps whatever
      ADMIN_PASSWORD_HASH it was configured with.
    - ADMIN_PASSWORD set: it wins over ADMIN_PASSWORD_HASH, being the more
      explicit operator intent.

    The password must satisfy the same strength rules the password-change
    endpoint enforces, so a value set through the environment cannot be weaker
    than one set through the UI.

    Raises:
        RuntimeError: In production, when ADMIN_PASSWORD fails the strength
            rules. The message lists the failed rules only, never the password.
    """
    password = getattr(settings, "admin_password", "")
    if not password:
        return

    strength = validate_password_strength(password)
    if not strength["valid"]:
        joined_errors = "; ".join(strength["errors"])
        if settings.is_production:
            raise RuntimeError(
                f"Refusing to start in production: ADMIN_PASSWORD is too weak ({joined_errors})"
            )
        # Same posture as the default-secret checks: outside production, warn and continue.
        logger.warning(
            f"ADMIN_PASSWORD does not meet the strength requirements "
            f"(non-production only): {joined_errors}"
        )

    settings.admin_password_hash = jwt_handler.hash_password(password)
    logger.info("Admin password hash derived from ADMIN_PASSWORD at startup")
