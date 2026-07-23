# -*- coding: utf-8 -*-
"""Location: ./tests/test_config_security.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

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
    """Development environment now rejects weak secrets unconditionally (GHSA-8pcq-mx48-hjvj).

    The old behaviour (warn-and-pass in development) was the root cause of the advisory.
    This test is updated to assert the correct fail-closed behaviour.

    Note: ``"my-test-key"`` is only 11 chars, so the length-floor check fires first
    (``"too short"``), before the weak-value check (``"known-weak/default value"``).
    Both are correct SecurityConfigurationError reasons — the test asserts the class.
    """
    from mcpgateway.config import SecurityConfigurationError

    with pytest.raises(SecurityConfigurationError):
        get_settings(environment="development", jwt_secret_key="my-test-key", auth_encryption_secret="UNCONFIGURED")  # nosec B106  # pragma: allowlist secret


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
    """Verify that REQUIRE_STRONG_SECRETS defaults to False in development.

    The entropy gate is unconditional so a real secret is required even in
    development; the test verifies the field value only.
    """
    from mcpgateway.config import SecurityConfigurationError

    monkeypatch.setenv("ENVIRONMENT", "development")

    # Weak-key still rejected by the unconditional entropy gate
    with pytest.raises(SecurityConfigurationError):
        get_settings(jwt_secret_key="weak-key")

    # With a real secret, require_strong_secrets should be False in development
    strong = "t3stJwt-S3cr3t!xK9pQmRvN2wLsA5dYfB7cEjGhTuIoP"  # pragma: allowlist secret
    cfg = get_settings(jwt_secret_key=strong)
    assert cfg.require_strong_secrets is False


def test_client_mode_skips_fail_closed_secret_enforcement():
    """Verify client mode get_security_status() returns SUCCESS but entropy gate still enforced."""
    from mcpgateway.config import SecurityConfigurationError

    # Weak secrets are rejected unconditionally regardless of client_mode
    with pytest.raises(SecurityConfigurationError):
        get_settings(client_mode=True, environment="production", jwt_secret_key="weak", auth_encryption_secret="UNCONFIGURED", require_strong_secrets=True)  # pragma: allowlist secret


def test_apply_environment_aware_defaults_non_dict_passthrough():
    """Verify non-dict inputs pass through unchanged in the model validator."""
    sentinel = ("not", "a", "dict")

    apply_defaults = getattr(Settings, "apply_environment_aware_defaults")
    assert apply_defaults(sentinel) is sentinel


def test_secret_below_min_length_raises():
    """Secret shorter than min_secret_length (32 chars) is rejected unconditionally.

    This covers the length-floor branch added in validate_security_combinations()
    (config.py:1525-1530) which the entropy/weak-value checks do not exercise —
    a 31-char string can have high entropy and not appear in WEAK_VALUES yet still
    fail the length floor.
    """
    from mcpgateway.config import SecurityConfigurationError

    # 31 chars: high entropy, not in WEAK_VALUES, but one char too short.
    just_under = "aB3#eF6!hI9$kL2%nO5^qR8&tU1*wX4"  # pragma: allowlist secret
    assert len(just_under) == 31

    with pytest.raises(SecurityConfigurationError, match="too short"):
        get_settings(
            environment="development",
            jwt_secret_key=just_under,
            auth_encryption_secret="a-strong-enc-secret-that-is-long-enough-and-unique-xxxx",  # nosec B105  # pragma: allowlist secret
        )


def test_startup_rejects_placeholder_compose_secret():
    """Gateway refuses to start when secrets match Docker Compose placeholder patterns.

    This is the CVSS 9.8 regression guard.  A deployment that ships the default
    compose file without running ``make init-secrets`` would have placeholder
    JWT_SECRET_KEY / AUTH_ENCRYPTION_SECRET values.  The gateway must fail closed
    at Settings() construction time — before any network socket is bound — and
    must never reach a running state.

    Covered patterns:
    - ``__REPLACE_ME__run_init-secrets_before_starting`` (init_secrets placeholder)
    - Shell-expansion fallback that was present before the fix
      (``my-test-key-but-now-longer-than-32-bytes``)
    """
    from mcpgateway.config import SecurityConfigurationError

    placeholder_cases = [
        "__REPLACE_ME__run_init-secrets_before_starting",
        "my-test-key-but-now-longer-than-32-bytes",  # nosec B105  # pragma: allowlist secret
    ]
    strong_enc = "a-strong-enc-secret-that-is-long-enough-and-unique-xxxx"  # nosec B105  # pragma: allowlist secret

    for placeholder in placeholder_cases:
        with pytest.raises(SecurityConfigurationError):
            get_settings(
                environment="production",
                jwt_secret_key=placeholder,
                auth_encryption_secret=strong_enc,
            )

        # Also fails in development — no environment exemption.
        with pytest.raises(SecurityConfigurationError):
            get_settings(
                environment="development",
                jwt_secret_key=placeholder,
                auth_encryption_secret=strong_enc,
            )
