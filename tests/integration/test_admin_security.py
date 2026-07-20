"""
Integration tests for admin configuration endpoint security (SEC-01).

Proves that both GET config routes reject non-admin access, that all secrets
are masked server-side with ***MASKED***, and that the PUT guard ignores
masked values resubmitted by the frontend.
"""

import pytest
from fastapi.testclient import TestClient

from src.auth.jwt_handler import jwt_handler
from src.config import settings
from src.shared.constants import MASKED_VALUE


CONFIG_ROUTES = [
    "/api/v1/admin/configuration",
    "/api/v1/admin/config",
]


@pytest.fixture(scope="module", autouse=True)
def initialized_database():
    """Ensure database tables exist: TestClient without a `with` block does not
    run the app lifespan, so init_database() is never called."""
    from src.database.connection import init_database
    init_database()


@pytest.fixture
def secret_settings():
    """Inject known sentinel secrets so masking is provable regardless of the
    local environment (save/override/restore pattern from conftest test_app)."""
    sentinels = {
        "mistral_api_key": "sk-test-secret-sentinel-12345",
        "smtp_password": "smtp-test-sentinel-98765",
    }
    original_values = {}
    for key, value in sentinels.items():
        original_values[key] = getattr(settings, key)
        setattr(settings, key, value)

    yield sentinels

    for key, value in original_values.items():
        setattr(settings, key, value)


@pytest.fixture
def admin_token():
    """JWT token with admin user_type."""
    return jwt_handler.create_access_token({"sub": "admin", "user_type": "admin"})


@pytest.fixture
def user_token():
    """JWT token with non-admin user_type."""
    return jwt_handler.create_access_token({"sub": "testuser", "user_type": "user"})


class TestAdminConfigAccessControl:
    """Access control on both GET config routes (D-04)."""

    @pytest.mark.parametrize("route", CONFIG_ROUTES)
    def test_get_without_auth_header_returns_403(self, test_app, route):
        """Without Authorization header, HTTPBearer rejects with 403."""
        client = TestClient(test_app)
        response = client.get(route)
        assert response.status_code == 403

    @pytest.mark.parametrize("route", CONFIG_ROUTES)
    def test_get_with_invalid_token_returns_401(self, test_app, route):
        """An invalid JWT token is rejected with 401."""
        client = TestClient(test_app)
        response = client.get(route, headers={"Authorization": "Bearer invalid-token"})
        assert response.status_code == 401

    @pytest.mark.parametrize("route", CONFIG_ROUTES)
    def test_get_with_non_admin_token_returns_403(self, test_app, route, user_token):
        """A valid non-admin token is rejected with 403 by require_admin."""
        client = TestClient(test_app)
        response = client.get(route, headers={"Authorization": f"Bearer {user_token}"})
        assert response.status_code == 403

    @pytest.mark.parametrize("route", CONFIG_ROUTES)
    def test_get_with_admin_token_returns_200(self, test_app, route, admin_token):
        """A valid admin token gets the configuration."""
        client = TestClient(test_app)
        response = client.get(route, headers={"Authorization": f"Bearer {admin_token}"})
        assert response.status_code == 200


class TestAdminConfigSecretMasking:
    """Server-side masking of secrets in admin responses (D-01, D-02)."""

    @pytest.mark.parametrize("route", CONFIG_ROUTES)
    def test_mistral_api_key_is_masked_in_response(
        self, test_app, route, admin_token, secret_settings
    ):
        """The mistral_api_key value in the 200 body is the total mask."""
        client = TestClient(test_app)
        response = client.get(route, headers={"Authorization": f"Bearer {admin_token}"})
        assert response.status_code == 200

        app_config = response.json()["application_config"]
        assert app_config["mistral_api_key"] == MASKED_VALUE

    @pytest.mark.parametrize("route", CONFIG_ROUTES)
    def test_real_secret_values_never_appear_in_response_text(
        self, test_app, route, admin_token, secret_settings
    ):
        """No real secret value from settings appears anywhere in the raw body."""
        client = TestClient(test_app)
        response = client.get(route, headers={"Authorization": f"Bearer {admin_token}"})
        assert response.status_code == 200

        assert MASKED_VALUE in response.text
        # Sentinel secrets injected by the fixture must never leak
        for sentinel_value in secret_settings.values():
            assert sentinel_value not in response.text
        # Real environment secrets must never leak either
        if settings.admin_password_hash:
            assert settings.admin_password_hash not in response.text
        if settings.jwt_secret_key:
            assert settings.jwt_secret_key not in response.text


class TestAdminConfigPutGuard:
    """PUT guard against masked value resubmission (D-03) and PUT alias fix."""

    def test_put_with_masked_value_is_ignored_and_returns_200(
        self, test_app, admin_token, secret_settings
    ):
        """A masked value resubmitted by the frontend is filtered out BEFORE the
        allow-list check (without the filter, mistral_api_key would trigger a 400),
        and the effective configuration is unchanged."""
        client = TestClient(test_app)
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Read current state to resubmit an allowed key without changing it
        before = client.get("/api/v1/admin/configuration", headers=headers)
        assert before.status_code == 200
        db_config_before = before.json()["database_config"]
        maintenance_value = db_config_before.get("maintenance_mode", "false")
        api_key_before = settings.mistral_api_key

        response = client.put(
            "/api/v1/admin/configuration",
            headers=headers,
            json={
                "maintenance_mode": str(maintenance_value),
                "mistral_api_key": MASKED_VALUE,
            },
        )
        # 200 proves the masked key was filtered before the allow-list
        # (mistral_api_key is not an allowed key: unfiltered it would be a 400)
        assert response.status_code == 200
        assert response.json()["success"] is True

        # The real secret was not overwritten by the mask
        assert settings.mistral_api_key == api_key_before

        # Effective configuration unchanged, still masked in the response
        after = client.get("/api/v1/admin/configuration", headers=headers)
        assert after.status_code == 200
        if settings.mistral_api_key:
            assert after.json()["application_config"]["mistral_api_key"] == MASKED_VALUE
            assert settings.mistral_api_key not in after.text

    def test_put_config_alias_returns_valid_base_response(self, test_app, admin_token):
        """PUT /config alias now delegates and returns a valid BaseResponse
        (its body used to be empty, returning None)."""
        client = TestClient(test_app)
        headers = {"Authorization": f"Bearer {admin_token}"}

        response = client.put(
            "/api/v1/admin/config",
            headers=headers,
            json={"mistral_api_key": MASKED_VALUE},
        )
        assert response.status_code == 200
        data = response.json()
        assert data is not None
        assert data["success"] is True
        assert "message" in data
        assert "timestamp" in data
