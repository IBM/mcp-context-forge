# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_trusted_claims.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the trust-mode claims extraction module (issue #5899).

extract_trusted_principal maps a verified external-IdP JWT payload to a
VirtualPrincipal per the pinned contract. user_id is required and opaque; a
missing mapped claim is an extraction error and never defaults to email.
email is optional: the AuditTrail path writes the "unknown" sentinel string
(never None) while ObservabilityTrace.user_email accepts None. External group
IDs feed the group-mapping resolver and never reach token_teams; resolver
role names merge with claim roles before server-side roles-table resolution.
"""

# Standard
import logging
from datetime import datetime, timezone

# Third-Party
from fastapi import HTTPException
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import AuditTrail, Base, EmailTeam, EmailUser, ExternalGroupMapping, ObservabilityTrace, Role
from mcpgateway.utils.trusted_claims import detect_overage_marker, extract_revocation_id, extract_trusted_principal

ISSUER = "https://login.example.com/tenant-1/v2.0"
TENANT = "tenant-1"
CALLER_ID = "oid-9f8e7d6c"
CALLER_EMAIL = "trust.user@example.com"


def _base_payload(**overrides):
    """Minimal trust-eligible payload: mapped user_id claim plus jti."""
    payload = {
        "sub": CALLER_ID,
        "iss": ISSUER,
        "tid": TENANT,
        "jti": "trusted-jti-1",
        "exp": 9999999999,
    }
    payload.update(overrides)
    return payload


def _permissions_for_roles(db, role_names) -> set:
    """Resolve role names to the permission set via the server-side roles table.

    Mirrors the trust-mode resolution rule: permissions come from the roles
    table only; unknown role names contribute nothing.
    """
    permissions = set()
    for name in role_names:
        role = db.query(Role).filter(Role.name == name, Role.is_active.is_(True)).first()
        if role is None:
            continue
        permissions.update(role.get_effective_permissions())
    return permissions


@pytest.fixture
def db():
    """In-memory SQLite session seeded with teams, roles, and mapping rows.

    Roles: developer (grants a2a.invoke), viewer (no permissions).
    Mapping rows: entra-group-guid-1 -> team-a with cf_role=developer;
    entra-group-guid-2 -> team-b with cf_role NULL.
    """
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    owner = EmailUser(
        email="owner@example.com",
        password_hash="hash",  # pragma: allowlist secret
        full_name="Owner",
        is_admin=False,
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(owner)
    session.add(EmailTeam(id="team-a", name="Team A", slug="team-a", created_by=owner.email, is_personal=False, visibility="private"))
    session.add(EmailTeam(id="team-b", name="Team B", slug="team-b", created_by=owner.email, is_personal=False, visibility="private"))
    session.add(Role(name="developer", scope="team", permissions=["a2a.invoke"], created_by=owner.email, is_system_role=True, is_active=True))
    session.add(Role(name="viewer", scope="team", permissions=[], created_by=owner.email, is_system_role=True, is_active=True))
    session.add(ExternalGroupMapping(issuer=ISSUER, tenant=TENANT, external_group_id="entra-group-guid-1", cf_team_id="team-a", cf_role="developer"))
    session.add(ExternalGroupMapping(issuer=ISSUER, tenant=TENANT, external_group_id="entra-group-guid-2", cf_team_id="team-b", cf_role=None))
    session.commit()
    try:
        yield session
    finally:
        session.close()


class TestExtractionContract:
    """The pinned virtual-principal contract, field by field."""

    def test_full_claim_token_yields_complete_principal(self, db):
        """Happy path: every claim present yields a complete principal."""
        payload = _base_payload(
            email=CALLER_EMAIL,
            name="Trust User",
            teams=["team-x"],
            roles=["viewer"],
            is_admin=False,
            groups=["entra-group-guid-1"],
        )
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.user_id == CALLER_ID
        assert principal.email == CALLER_EMAIL
        assert principal.full_name == "Trust User"
        assert principal.teams == ["team-x", "team-a"]
        assert principal.roles == ["viewer", "developer"]
        assert principal.is_admin is False
        assert principal.auth_provider == ISSUER
        assert principal.token_use == "trusted"

    def test_missing_user_id_claim_raises_never_defaults_to_email(self, db):
        """A missing user_id-mapped claim is an extraction error (401)."""
        payload = _base_payload(email=CALLER_EMAIL)
        del payload["sub"]
        with pytest.raises(HTTPException) as exc_info:
            extract_trusted_principal(payload, settings, db)
        assert exc_info.value.status_code == 401

    def test_email_absent_yields_principal_with_email_none(self, db):
        """A missing email claim yields email=None; identity stays intact."""
        payload = _base_payload()
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.user_id == CALLER_ID
        assert principal.email is None

    def test_audit_path_writes_unknown_sentinel_never_none(self, db):
        """AuditTrail.user_id is nullable=False: the sentinel string lands there."""
        assert AuditTrail.__table__.c.user_id.nullable is False
        payload = _base_payload()
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.email is None
        assert principal.audit_identity == "unknown"
        assert principal.audit_identity is not None
        db.add(AuditTrail(action="read", resource_type="tool", user_id=principal.audit_identity, success=True))
        db.commit()

    def test_observability_trace_user_email_accepts_none(self, db):
        """ObservabilityTrace.user_email is nullable and accepts None."""
        assert ObservabilityTrace.__table__.c.user_email.nullable is True
        payload = _base_payload()
        principal = extract_trusted_principal(payload, settings, db)
        db.add(ObservabilityTrace(name="GET /tools", start_time=datetime.now(timezone.utc), status="ok", user_email=principal.email))
        db.commit()

    def test_nested_dotted_path_roles_resolves(self, db, monkeypatch):
        """Keycloak-style nested path realm_access.roles resolves."""
        monkeypatch.setattr(settings, "jwt_claim_roles", "realm_access.roles")
        payload = _base_payload(realm_access={"roles": ["developer"]})
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.roles == ["developer"]

    def test_teams_claim_normalizes_list_of_dicts(self, db):
        """Teams claim accepts list of {id, name} mirroring normalize_token_teams."""
        payload = _base_payload(teams=[{"id": "team-x", "name": "Team X"}, "team-y"])
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.teams == ["team-x", "team-y"]

    def test_unknown_role_name_ignored_with_warning(self, db, caplog):
        """Unknown role names are skipped (fail-closed) with a WARNING log."""
        payload = _base_payload(roles=["developer", "no-such-role"])
        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.trusted_claims"):
            principal = extract_trusted_principal(payload, settings, db)
        assert principal.roles == ["developer"]
        assert any("no-such-role" in record.message for record in caplog.records)

    def test_resolver_cf_role_developer_without_roles_claim(self, db):
        """No roles claim + mapping row cf_role=developer -> developer permission set."""
        payload = _base_payload(groups=["entra-group-guid-1"])
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.roles == ["developer"]
        assert principal.teams == ["team-a"]
        assert "a2a.invoke" in _permissions_for_roles(db, principal.roles)

    def test_unmapped_groups_yield_empty_teams_public_only(self, db):
        """All external groups unmapped -> teams is [] (public-only, authenticated)."""
        payload = _base_payload(groups=["unmapped-group"])
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.teams == []
        assert principal.roles == []
        assert principal.user_id == CALLER_ID

    def test_revocation_claim_default_jti(self, db):
        """Default revocation claim jti is accepted."""
        principal = extract_trusted_principal(_base_payload(), settings, db)
        assert principal.user_id == CALLER_ID

    def test_revocation_claim_uti_supported(self, db, monkeypatch):
        """An Entra trust root may configure uti as the revocation claim."""
        monkeypatch.setattr(settings, "jwt_trust_revocation_claim", "uti")
        payload = _base_payload(uti="entra-uti-1")
        del payload["jti"]
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.user_id == CALLER_ID

    def test_missing_revocation_claim_rejected_401(self, db):
        """A trust-eligible token without the configured revocation claim is rejected."""
        payload = _base_payload()
        del payload["jti"]
        with pytest.raises(HTTPException) as exc_info:
            extract_trusted_principal(payload, settings, db)
        assert exc_info.value.status_code == 401


class TestOverageMarker:
    """detect_overage_marker flags the Entra group-overage token shapes."""

    def test_claim_names_containing_groups(self):
        assert detect_overage_marker({"_claim_names": {"groups": "src1"}}) is True

    def test_hasgroups_key(self):
        assert detect_overage_marker({"hasgroups": True}) is True

    def test_groups_src_key(self):
        assert detect_overage_marker({"groups:src1": "https://graph.example.com"}) is True

    def test_string_typed_groups_claim(self):
        assert detect_overage_marker({"groups": "src1"}) is True

    def test_inline_groups_list_is_not_overage(self):
        assert detect_overage_marker({"groups": ["guid-1", "guid-2"]}) is False

    def test_no_groups_markers(self):
        assert detect_overage_marker({"sub": "oid-1"}) is False


class TestRevocationExtractor:
    """extract_revocation_id honors the configured revocation claim."""

    def test_default_jti(self):
        assert extract_revocation_id({"jti": "tok-1"}, settings) == "tok-1"

    def test_uti_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "jwt_trust_revocation_claim", "uti")
        assert extract_revocation_id({"uti": "entra-uti-9"}, settings) == "entra-uti-9"

    def test_missing_configured_claim_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            extract_revocation_id({"sub": "oid-1"}, settings)
        assert exc_info.value.status_code == 401
