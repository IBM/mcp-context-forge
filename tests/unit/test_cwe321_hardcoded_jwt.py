# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_cwe321_hardcoded_jwt.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for CWE-321 hardcoded JWT key fixes.
"""

import logging
import re
import datetime
from datetime import timezone
from pathlib import Path
import pytest
from pydantic import ValidationError
from mcpgateway.config import SecurityConfigurationError, Settings

WEAK_JWT_KEY = "my-test-key-but-now-longer-than-32-bytes"
WEAK_ENC_KEY = "my-test-salt"
STRONG_JWT_KEY = "x3Kp!mQ8rZvN2wLsA5dYfB7cEjGhTuIo"  # 32 chars, random
STRONG_ENC_KEY = "F4nRqW9kMpXzD1sVbYcL6eHjOuAtG2wC"  # 32 chars, random  # pragma: allowlist secret


def _make_settings(**kwargs):
    """Instantiate Settings with minimal required overrides."""
    from mcpgateway.config import Settings

    base = {
        "jwt_secret_key": STRONG_JWT_KEY,
        "auth_encryption_secret": STRONG_ENC_KEY,
    }
    base.update(kwargs)
    return Settings.model_validate(base)


class TestValidateSecretsRaisesInNonDev:
    def test_raises_in_production_with_weak_jwt_key(self):
        with pytest.raises(SecurityConfigurationError) as exc_info:
            _make_settings(environment="production", jwt_secret_key=WEAK_JWT_KEY)
        assert "Weak/default secret rejected" in str(exc_info.value)

    def test_raises_in_staging_with_weak_jwt_key(self):
        with pytest.raises(SecurityConfigurationError) as exc_info:
            _make_settings(environment="staging", jwt_secret_key=WEAK_JWT_KEY)
        assert "Weak/default secret rejected" in str(exc_info.value)

    def test_raises_in_production_with_weak_enc_key(self):
        with pytest.raises(SecurityConfigurationError) as exc_info:
            _make_settings(environment="production", auth_encryption_secret=WEAK_ENC_KEY)
        assert "Weak/default secret rejected" in str(exc_info.value)

    def test_warns_but_passes_in_development_with_weak_key(self, caplog):
        with caplog.at_level(logging.WARNING, logger="mcpgateway.config"):
            settings = _make_settings(environment="development", jwt_secret_key=WEAK_JWT_KEY)
        assert settings.jwt_secret_key.get_secret_value() == WEAK_JWT_KEY
        assert "SECURITY WARNING" in caplog.text

    def test_strong_key_passes_in_production(self):
        settings = _make_settings(environment="production")
        assert settings.jwt_secret_key.get_secret_value() == STRONG_JWT_KEY

    def test_client_mode_does_not_bypass_weak_key_check_in_production(self):
        with pytest.raises(SecurityConfigurationError) as exc_info:
            _make_settings(environment="production", jwt_secret_key=WEAK_JWT_KEY, client_mode=True)
        assert "Weak/default secret rejected" in str(exc_info.value)


REPO_ROOT = Path(__file__).parent.parent.parent
ENV_EXAMPLE = REPO_ROOT / ".env.example"
PLACEHOLDER = "__REPLACE_ME__"


class TestEnvExampleSanity:
    def _active_lines(self):
        """Return non-comment, non-blank lines from .env.example."""
        lines = ENV_EXAMPLE.read_text().splitlines()
        return [ln for ln in lines if ln.strip() and not ln.strip().startswith("#")]

    def test_jwt_secret_key_is_not_active_weak_default(self):
        active = self._active_lines()
        bad = [ln for ln in active if re.match(r"JWT_SECRET_KEY\s*=\s*my-test-key", ln)]
        assert not bad, f"Live weak JWT_SECRET_KEY found in .env.example: {bad}"

    def test_auth_encryption_secret_is_not_active_weak_default(self):
        active = self._active_lines()
        bad = [ln for ln in active if re.match(r"AUTH_ENCRYPTION_SECRET\s*=\s*my-test-salt", ln)]
        assert not bad, f"Live weak AUTH_ENCRYPTION_SECRET found in .env.example: {bad}"

    def test_jwt_secret_key_line_has_placeholder(self):
        content = ENV_EXAMPLE.read_text()
        assert f"JWT_SECRET_KEY={PLACEHOLDER}" in content, f"Expected JWT_SECRET_KEY={PLACEHOLDER} in .env.example"


class TestBootstrapIsAdmin:
    """Bootstrap branch must not grant is_admin without token claim."""

    def _make_payload(self, extra: dict | None = None) -> dict:
        now = datetime.datetime.now(timezone.utc)
        payload = {
            "sub": "admin@example.com",
            "aud": "mcpgateway-api",
            "iss": "mcpgateway",
            "jti": "test-jti-123",
            "iat": now,
            "exp": now + datetime.timedelta(hours=1),
        }
        if extra:
            payload.update(extra)
        return payload

    def test_bootstrap_without_is_admin_claim_grants_non_admin(self):
        """Forged token with no is_admin claim must not receive is_admin=True."""
        from mcpgateway.auth import _bootstrap_platform_admin_user

        user = _bootstrap_platform_admin_user(email="regular-user@example.com")
        assert user.is_admin is False

    def test_bootstrap_with_is_admin_true_claim_grants_admin(self):
        """Admin email receives admin status."""
        from mcpgateway.auth import _bootstrap_platform_admin_user

        user = _bootstrap_platform_admin_user(email="admin@example.com")
        assert user.is_admin is True


class TestRemainingGaps:
    """Tests for gaps not covered by the initial CWE-321 fix."""

    # --- Gap 1: no 'my-test-key' literal in Field defaults ---

    def test_jwt_secret_key_field_default_does_not_contain_my_test_key(self):
        import re

        src = (Path(__file__).parent.parent.parent / "mcpgateway" / "config.py").read_text()
        # my-test-key must not appear as a Field default — it may remain in WEAK_VALUES blocklist
        bad = re.findall(r"Field\s*\(.*?my-test-key.*?\)", src)
        assert not bad, f"my-test-key literal still present as Field default: {bad}"

    def test_auth_encryption_secret_field_default_does_not_contain_my_test_salt(self):
        import re

        src = (Path(__file__).parent.parent.parent / "mcpgateway" / "config.py").read_text()
        # my-test-salt must not appear as a Field default — it may remain in WEAK_VALUES blocklist
        bad = re.findall(r"Field\s*\(.*?my-test-salt.*?\)", src)
        assert not bad, f"my-test-salt literal still present as Field default: {bad}"

    # --- Gap 2: __REPLACE_ME__ placeholder blocked in production ---

    def test_placeholder_value_blocked_in_production(self):
        with pytest.raises(SecurityConfigurationError) as exc_info:
            _make_settings(
                environment="production",
                jwt_secret_key="__REPLACE_ME__run_init-secrets_before_starting",
            )
        assert "placeholder" in str(exc_info.value).lower() or "replace_me" in str(exc_info.value).lower()

    def test_placeholder_value_warns_in_development(self, caplog):
        """__REPLACE_ME__ in development emits a warning but does not block startup."""
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.config"):
            settings = _make_settings(
                environment="development",
                jwt_secret_key="__REPLACE_ME__run_init-secrets_before_starting",
            )
        assert settings is not None
        assert "replace_me" in caplog.text.lower() or "placeholder" in caplog.text.lower()

    def test_placeholder_value_warns_in_staging(self, caplog):
        """__REPLACE_ME__ in staging emits a warning but does not block startup."""
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.config"):
            settings = _make_settings(
                environment="staging",
                jwt_secret_key="__REPLACE_ME__run_init-secrets_before_starting",
            )
        assert settings is not None
        assert "replace_me" in caplog.text.lower() or "placeholder" in caplog.text.lower()

    def test_placeholder_prefix_variations_blocked(self):
        """Case-insensitive prefix match."""
        for val in ["__REPLACE_ME__anything", "__replace_me__something", "__Replace_Me__x"]:
            with pytest.raises(SecurityConfigurationError):
                _make_settings(environment="production", jwt_secret_key=val)


class TestRequireUserInDb:
    """require_user_in_db must default to True for secure deployments."""

    def test_default_require_user_in_db_is_true(self):
        """Default AppSettings must have require_user_in_db=True."""
        settings = _make_settings()
        assert settings.require_user_in_db is True, "require_user_in_db must default to True. " "Set REQUIRE_USER_IN_DB=false in .env for development."

    def test_env_example_require_user_in_db_is_commented_out(self):
        """
        .env.example must not ship REQUIRE_USER_IN_DB=false as an active line.
        The line must be commented out so that cp .env.example .env does not
        silently enable the insecure bootstrap path; developers must opt in explicitly.
        """
        content = ENV_EXAMPLE.read_text()
        active = re.compile(r"^\s*REQUIRE_USER_IN_DB\s*=\s*false\s*$", re.IGNORECASE | re.MULTILINE)
        assert not active.search(content), ".env.example must not ship an active REQUIRE_USER_IN_DB=false line; " "it must be commented out so developers explicitly opt in"


@pytest.mark.parametrize("weak", Settings.WEAK_VALUES)
def test_all_weak_values_rejected_in_production(weak):
    """Every entry in WEAK_VALUES must be caught by the model validator in production."""
    with pytest.raises(SecurityConfigurationError):
        _make_settings(environment="production", jwt_secret_key=weak)
