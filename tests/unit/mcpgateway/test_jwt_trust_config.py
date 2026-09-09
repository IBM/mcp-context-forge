# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_jwt_trust_config.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for JWT-trust mode configuration surface.

Covers the settings added for issue #5898: trust mode toggle, claim
mapping, overage policy, and the revocation-claim contract. The startup
validators must reject empty claim names and a trust mode without a
revocation claim.
"""

# Third-Party
import pytest
from pydantic import ValidationError

# First-Party
from mcpgateway.config import Settings


def _settings(**overrides) -> Settings:
    """Build Settings isolated from the process environment."""
    return Settings(environment="development", _env_file=None, **overrides)


class TestJwtTrustDefaults:
    """Default values preserve current behavior."""

    def test_defaults(self):
        s = _settings()
        assert s.jwt_trust_mode == "db"
        assert s.jwt_claim_user_id == "sub"
        assert s.jwt_claim_email == "email"
        assert s.jwt_claim_teams == "teams"
        assert s.jwt_claim_roles == "roles"
        assert s.jwt_claim_admin == "is_admin"
        assert s.jwt_trust_overage_policy == "fail_closed"
        assert s.jwt_trust_revocation_claim == "jti"


class TestJwtTrustModeBoot:
    """Trust mode with valid config boots cleanly."""

    def test_trust_mode_valid_config_boots(self):
        s = _settings(jwt_trust_mode="jwt-trust", jwt_trust_revocation_claim="jti")
        assert s.jwt_trust_mode == "jwt-trust"
        assert s.jwt_trust_revocation_claim == "jti"


class TestJwtTrustClaimValidation:
    """Empty claim names are rejected at startup."""

    def test_empty_jwt_claim_user_id_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            _settings(jwt_trust_mode="jwt-trust", jwt_claim_user_id="")
        assert "jwt_claim_user_id" in str(exc_info.value)
        assert "must not be empty" in str(exc_info.value)

    def test_unknown_claim_name_rejected_with_setting_name(self):
        with pytest.raises(ValidationError) as exc_info:
            _settings(jwt_trust_mode="jwt-trust", jwt_claim_teams="")
        assert "jwt_claim_teams" in str(exc_info.value)
        assert "must not be empty" in str(exc_info.value)


class TestJwtTrustRevocationRequirement:
    """Trust mode without a revocation claim is rejected at startup."""

    def test_trust_mode_without_revocation_claim_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            _settings(jwt_trust_mode="jwt-trust", jwt_trust_revocation_claim="")
        message = str(exc_info.value)
        assert "jwt_trust_revocation_claim" in message
        assert "must not be empty" in message
