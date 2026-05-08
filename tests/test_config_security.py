# -*- coding: utf-8 -*-
"""Location: ./tests/test_config_security.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Eleni Kechrioti

Security enforcement unit tests for US-2 (Fail-Closed logic).
Verifies that the gateway terminates execution when critical secrets are
unconfigured or weak in production environments.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.config import Settings, get_settings, SecurityConfigurationError


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """
    Clears the lru_cache for get_settings before each test to ensure
    fresh configuration evaluation.
    """
    get_settings.cache_clear()
    yield


def test_fail_closed_production_missing_jwt_secret():
    """Verify that production startup fails if JWT_SECRET_KEY is empty."""
    with pytest.raises(SecurityConfigurationError):
        get_settings(environment="production", jwt_secret_key="", auth_encryption_secret="secure-test-secret-32-characters-min")  # pragma: allowlist secret  # pragma: allowlist secret


def test_fail_closed_production_missing_auth_secret():
    """Verify that production startup fails if AUTH_ENCRYPTION_SECRET is unconfigured."""
    with pytest.raises(SecurityConfigurationError):
        get_settings(environment="production", jwt_secret_key="secure-test-secret-32-characters-min", auth_encryption_secret="UNCONFIGURED")  # pragma: allowlist secret  # pragma: allowlist secret


def test_fail_closed_production_weak_secret():
    """Verify that production startup fails if weak secrets are detected."""
    with pytest.raises(SecurityConfigurationError):
        get_settings(environment="production", jwt_secret_key="my-test-key", require_strong_secrets=True)


def test_require_strong_secrets_fails_closed_outside_production():
    """Verify explicit strong secret enforcement fails closed in any environment."""
    with pytest.raises(SecurityConfigurationError):
        get_settings(environment="staging", jwt_secret_key="my-test-key", require_strong_secrets=True)


def test_fail_closed_production_legacy_default_jwt_secret():
    """Verify that production startup fails for the documented default JWT secret."""
    with pytest.raises(SecurityConfigurationError):
        get_settings(
            environment="production",
            jwt_secret_key="my-test-key-but-now-longer-than-32-bytes",
            auth_encryption_secret="secure-test-secret-32-characters-min",  # pragma: allowlist secret
        )


def test_fail_closed_basic_auth_password_when_api_basic_auth_enabled():
    """Verify that default Basic auth credentials fail closed when API Basic auth is enabled."""
    with pytest.raises(SecurityConfigurationError):
        get_settings(
            environment="production",
            jwt_secret_key="secure-test-secret-32-characters-min",
            auth_encryption_secret="another-secure-test-secret-32-chars",  # pragma: allowlist secret
            mcpgateway_ui_enabled=False,
            api_allow_basic_auth=True,
            basic_auth_password="changeme",  # pragma: allowlist secret
        )


def test_proceed_development_mode():
    """Ensure development environment allows startup with warnings for local testing."""
    # Development mode should return settings object instead of exiting.
    cfg = get_settings(environment="development", jwt_secret_key="my-test-key", auth_encryption_secret="UNCONFIGURED")  # pragma: allowlist secret  # pragma: allowlist secret

    # Validation status should be SUCCESS to allow development flow.
    status = cfg.get_security_status()
    assert status["status"] == "SUCCESS"


def test_environment_aware_default_production(monkeypatch):
    """Verify that REQUIRE_STRONG_SECRETS defaults to True in production."""
    # Simulate production environment via env var
    monkeypatch.setenv("ENVIRONMENT", "production")

    # In production, even without passing require_strong_secrets, it should be True
    with pytest.raises(SecurityConfigurationError):
        get_settings(jwt_secret_key="weak-key")


def test_environment_aware_default_production_kwargs():
    """Verify production kwargs enable strong secret enforcement by default."""
    with pytest.raises(SecurityConfigurationError):
        get_settings(environment="production", jwt_secret_key="weak-key", auth_encryption_secret="secure-test-secret-32-characters-min")  # pragma: allowlist secret


def test_environment_aware_default_development(monkeypatch):
    """Verify that REQUIRE_STRONG_SECRETS defaults to False in development."""
    # Simulate development environment
    monkeypatch.setenv("ENVIRONMENT", "development")

    # In development, it should proceed despite the weak key
    cfg = get_settings(jwt_secret_key="weak-key")
    assert cfg.require_strong_secrets is False


def test_client_mode_skips_fail_closed_secret_enforcement():
    """Verify client mode bypasses server secret enforcement."""
    cfg = get_settings(client_mode=True, environment="production", jwt_secret_key="weak", auth_encryption_secret="UNCONFIGURED", require_strong_secrets=True)  # pragma: allowlist secret
    status = cfg.get_security_status()
    assert status["status"] == "SUCCESS"
    assert status["message"] == "Security validation skipped in client mode."


def test_apply_environment_aware_defaults_non_dict_passthrough():
    """Verify non-dict inputs pass through unchanged in the model validator."""
    sentinel = ("not", "a", "dict")

    apply_defaults = getattr(Settings, "apply_environment_aware_defaults")
    assert apply_defaults(sentinel) is sentinel
