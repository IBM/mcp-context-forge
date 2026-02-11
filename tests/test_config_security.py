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

# First-Party
from mcpgateway.config import get_settings


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
    with pytest.raises(SystemExit) as cm:
        get_settings(environment="production", jwt_secret_key="", auth_encryption_secret="secure-test-secret-32-characters-min")
    # Ensure application exits with code 1
    assert cm.value.code == 1


def test_fail_closed_production_missing_auth_secret():
    """Verify that production startup fails if AUTH_ENCRYPTION_SECRET is unconfigured."""
    with pytest.raises(SystemExit) as cm:
        get_settings(environment="production", jwt_secret_key="secure-test-secret-32-characters-min", auth_encryption_secret="UNCONFIGURED")
    assert cm.value.code == 1


def test_fail_closed_production_weak_secret():
    """Verify that production startup fails if weak secrets are detected."""
    with pytest.raises(SystemExit) as cm:
        get_settings(environment="production", jwt_secret_key="my-test-key", require_strong_secrets=True)
    assert cm.value.code == 1


def test_proceed_development_mode():
    """Ensure development environment allows startup with warnings for local testing."""
    # Development mode should return settings object instead of exiting
    cfg = get_settings(environment="development", jwt_secret_key="my-test-key", auth_encryption_secret="UNCONFIGURED")

    # Validation status should be SUCCESS to allow development flow
    status = cfg.get_security_status()
    assert status["status"] == "SUCCESS"
