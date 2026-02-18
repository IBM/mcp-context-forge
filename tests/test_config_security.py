# -*- coding: utf-8 -*-
"""Location: ./tests/test_config_security.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Eleni Kechrioti

Security enforcement unit tests for US-2 (Fail-Closed logic).
Verifies that the gateway terminates execution when critical secrets are
unconfigured or weak in production environments.
"""

# Standard
import pytest
import logging

# First-Party
from mcpgateway.config import get_settings, SecurityConfigurationError


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
        get_settings(environment="production", jwt_secret_key="", auth_encryption_secret="secure-test-secret-32-characters-min")


def test_fail_closed_production_missing_auth_secret():
    """Verify that production startup fails if AUTH_ENCRYPTION_SECRET is unconfigured."""
    with pytest.raises(SecurityConfigurationError):
        get_settings(environment="production", jwt_secret_key="secure-test-secret-32-characters-min", auth_encryption_secret="UNCONFIGURED")


def test_fail_closed_production_weak_secret():
    """Verify that production startup fails if weak secrets are detected."""
    with pytest.raises(SecurityConfigurationError):
        get_settings(environment="production", jwt_secret_key="my-test-key", require_strong_secrets=True)


def test_proceed_development_mode(caplog):
    """Ensure development environment allows startup with warnings for local testing."""
    with caplog.at_level(logging.WARNING):
        # Development mode should return settings object instead of exiting
        cfg = get_settings(environment="development", jwt_secret_key="my-test-key", auth_encryption_secret="UNCONFIGURED")

        # Validation status should be SUCCESS to allow development flow
        status = cfg.get_security_status()
        assert status["status"] == "SUCCESS"
        assert "DEV WARNING" in caplog.text
        assert "AUTH_ENCRYPTION_SECRET" in caplog.text or "UNCONFIGURED" in caplog.text


def test_environment_aware_default_production(monkeypatch):
    """Verify that REQUIRE_STRONG_SECRETS defaults to True in production."""
    # Simulate production environment via env var
    monkeypatch.setenv("ENVIRONMENT", "production")

    # In production, even without passing require_strong_secrets, it should be True
    with pytest.raises(SecurityConfigurationError):
        get_settings(jwt_secret_key="weak-key")


def test_environment_aware_default_development(monkeypatch):
    """Verify that REQUIRE_STRONG_SECRETS defaults to False in development."""
    # Simulate development environment
    monkeypatch.setenv("ENVIRONMENT", "development")

    # In development, it should proceed despite the weak key
    cfg = get_settings(jwt_secret_key="weak-key")
    assert cfg.require_strong_secrets is False
