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

# Standard
from pathlib import Path

# Third-Party
import pytest
from pydantic import ValidationError

# First-Party
from mcpgateway.config import SecurityConfigurationError, Settings


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
        assert s.jwt_trust_entra_group_admin_enabled is False
        assert s.jwt_trust_admin_groups == []


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


class TestClaimTeamsGroupClaimCollision:
    """JWT_CLAIM_TEAMS must not alias the claim the external group-mapping resolver consumes.

    In trust mode the resolver reads ``sso_entra_groups_claim`` for external
    group IDs and maps them to ContextForge teams. If ``jwt_claim_teams``
    names the same claim, raw external group IDs land in native ContextForge
    team memberships before mapping (finding F9). Startup validation must
    reject the collision with ``SecurityConfigurationError``.
    """

    def test_claim_teams_cannot_alias_group_mapping_source(self):
        with pytest.raises(SecurityConfigurationError) as exc_info:
            _settings(jwt_trust_mode="jwt-trust", jwt_claim_teams="groups", sso_entra_groups_claim="groups")
        message = str(exc_info.value)
        assert "JWT_CLAIM_TEAMS" in message
        assert "SSO_ENTRA_GROUPS_CLAIM" in message

    def test_distinct_team_and_group_claims_accepted(self):
        s = _settings(jwt_trust_mode="jwt-trust", jwt_claim_teams="teams", sso_entra_groups_claim="groups")
        assert s.jwt_claim_teams == "teams"
        assert s.sso_entra_groups_claim == "groups"

    def test_collision_inert_when_trust_mode_disabled(self):
        # Outside trust mode jwt_claim_teams is not consumed, so an aliased
        # value is dead config and must not fail startup.
        s = _settings(jwt_trust_mode="db", jwt_claim_teams="groups", sso_entra_groups_claim="groups")
        assert s.jwt_trust_mode == "db"


class TestComposeDeclaresTrustFlags:
    """The supported Compose stacks declare the trust flags, commented and default-off."""

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[3]

    def test_compose_declares_trust_flags(self):
        text = (self._repo_root() / "docker-compose.yml").read_text(encoding="utf-8")
        assert "JWT_TRUST_MODE" in text
        assert "SSO_API_TOKEN_AUTH_ENABLED" in text

    def test_compose_trust_flags_default_off(self):
        text = (self._repo_root() / "docker-compose.yml").read_text(encoding="utf-8")
        assert "# - JWT_TRUST_MODE=db" in text
        assert "# - SSO_API_TOKEN_AUTH_ENABLED=false" in text

    def test_sso_compose_declares_trust_flags(self):
        text = (self._repo_root() / "docker-compose.sso.yml").read_text(encoding="utf-8")
        assert "# - JWT_TRUST_MODE=db" in text
        # The SSO profile deliberately enables external-IdP API tokens; trust mode stays commented/off.
        assert "- SSO_API_TOKEN_AUTH_ENABLED=true" in text


class TestEntraGroupAdminConfig:
    """Startup contract for the Entra group-to-admin feature flag."""

    GROUP = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def test_enabled_in_trust_mode_with_groups_boots(self):
        s = _settings(jwt_trust_mode="jwt-trust", jwt_trust_entra_group_admin_enabled=True, jwt_trust_admin_groups=[self.GROUP])
        assert s.jwt_trust_admin_groups == [self.GROUP]

    def test_groups_parse_from_csv_and_json(self):
        other = "99999999-8888-7777-6666-555555555555"
        csv = _settings(jwt_trust_admin_groups=f"{self.GROUP}, {other}")
        assert csv.jwt_trust_admin_groups == [self.GROUP, other]
        js = _settings(jwt_trust_admin_groups=f'["{self.GROUP}"]')
        assert js.jwt_trust_admin_groups == [self.GROUP]

    def test_flag_requires_trust_mode(self):
        with pytest.raises(ValidationError) as exc_info:
            _settings(jwt_trust_mode="db", jwt_trust_entra_group_admin_enabled=True, jwt_trust_admin_groups=[self.GROUP])
        assert "jwt_trust_entra_group_admin_enabled" in str(exc_info.value)
        assert "jwt-trust" in str(exc_info.value)

    def test_flag_requires_non_empty_groups(self):
        with pytest.raises(ValidationError) as exc_info:
            _settings(jwt_trust_mode="jwt-trust", jwt_trust_entra_group_admin_enabled=True, jwt_trust_admin_groups=[])
        assert "jwt_trust_admin_groups" in str(exc_info.value)

    def test_flag_rejects_group_names(self):
        with pytest.raises(ValidationError) as exc_info:
            _settings(jwt_trust_mode="jwt-trust", jwt_trust_entra_group_admin_enabled=True, jwt_trust_admin_groups=["Platform Admins"])
        assert "object ID" in str(exc_info.value)

    def test_groups_without_flag_are_inert(self):
        s = _settings(jwt_trust_admin_groups=["not-a-guid"])
        assert s.jwt_trust_entra_group_admin_enabled is False
