# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_entra_group_admin.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Entra group-to-platform-admin mapping in JWT-trust mode.

With ``JWT_TRUST_ENTRA_GROUP_ADMIN_ENABLED=true`` a user token whose final
``groups`` list contains a group object ID listed in ``JWT_TRUST_ADMIN_GROUPS``
yields a principal with ``is_admin=True`` and ``"platform_admin"`` in its
roles (the atomic admin mapping of #5902). The grant is fail-closed:

- the flag is off by default;
- only tokens from an Entra issuer whose path tenant equals ``tid`` qualify;
- app-only service-principal tokens never qualify;
- group names never match, only object IDs.
"""

# Standard
import logging

# Third-Party
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base
from mcpgateway.utils.trusted_claims import extract_trusted_principal

TENANT = "11111111-2222-3333-4444-555555555555"
ENTRA_ISSUER = f"https://login.microsoftonline.com/{TENANT}/v2.0"
ADMIN_GROUP = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OTHER_GROUP = "99999999-8888-7777-6666-555555555555"
USER_OID = "0f0f0f0f-1111-2222-3333-444444444444"
USER_SUB = "pairwise-subject-for-user"


@pytest.fixture
def db():
    """Empty in-memory SQLite session; the admin mapping needs no table rows."""
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def group_admin_on(monkeypatch):
    """Enable the feature with one admin group."""
    monkeypatch.setattr(settings, "jwt_trust_entra_group_admin_enabled", True)
    monkeypatch.setattr(settings, "jwt_trust_admin_groups", [ADMIN_GROUP])


def _user_payload(**overrides) -> dict:
    """Entra user token: pairwise ``sub`` differs from ``oid``."""
    payload = {
        "sub": USER_SUB,
        "oid": USER_OID,
        "iss": ENTRA_ISSUER,
        "tid": TENANT,
        "jti": "group-admin-jti-1",
        "exp": 9999999999,
        "groups": [ADMIN_GROUP],
    }
    payload.update(overrides)
    return payload


class TestGroupAdminGrant:
    """A user in a listed Entra group becomes a platform admin."""

    def test_listed_group_grants_both_admin_tracks(self, db, group_admin_on):
        principal = extract_trusted_principal(_user_payload(), settings, db)
        assert principal.is_admin is True
        assert "platform_admin" in principal.roles

    def test_group_match_is_case_insensitive(self, db, group_admin_on):
        principal = extract_trusted_principal(_user_payload(groups=[ADMIN_GROUP.upper()]), settings, db)
        assert principal.is_admin is True

    def test_any_listed_group_suffices(self, db, monkeypatch):
        monkeypatch.setattr(settings, "jwt_trust_entra_group_admin_enabled", True)
        monkeypatch.setattr(settings, "jwt_trust_admin_groups", [OTHER_GROUP, ADMIN_GROUP])
        principal = extract_trusted_principal(_user_payload(groups=["unrelated", ADMIN_GROUP]), settings, db)
        assert principal.is_admin is True

    def test_grant_does_not_duplicate_platform_admin_role(self, db, group_admin_on):
        principal = extract_trusted_principal(_user_payload(is_admin=True), settings, db)
        assert principal.roles.count("platform_admin") == 1

    def test_grant_is_logged_without_group_ids(self, db, group_admin_on, caplog):
        with caplog.at_level(logging.INFO, logger="mcpgateway.utils.trusted_claims"):
            extract_trusted_principal(_user_payload(), settings, db)
        assert any("Entra group admin" in record.getMessage() for record in caplog.records)
        assert all(ADMIN_GROUP not in record.getMessage() for record in caplog.records)


class TestGroupAdminDeny:
    """Every deny path leaves the principal non-admin."""

    def test_flag_off_by_default(self, db, monkeypatch):
        monkeypatch.setattr(settings, "jwt_trust_admin_groups", [ADMIN_GROUP])
        assert settings.jwt_trust_entra_group_admin_enabled is False
        principal = extract_trusted_principal(_user_payload(), settings, db)
        assert principal.is_admin is False
        assert "platform_admin" not in principal.roles

    def test_unlisted_group_denied(self, db, group_admin_on):
        principal = extract_trusted_principal(_user_payload(groups=[OTHER_GROUP]), settings, db)
        assert principal.is_admin is False
        assert "platform_admin" not in principal.roles

    def test_no_groups_denied(self, db, group_admin_on):
        payload = _user_payload()
        del payload["groups"]
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.is_admin is False

    def test_empty_allowlist_denies_everyone(self, db, monkeypatch):
        monkeypatch.setattr(settings, "jwt_trust_entra_group_admin_enabled", True)
        monkeypatch.setattr(settings, "jwt_trust_admin_groups", [])
        principal = extract_trusted_principal(_user_payload(groups=[ADMIN_GROUP, ""]), settings, db)
        assert principal.is_admin is False

    def test_group_name_does_not_match(self, db, monkeypatch):
        monkeypatch.setattr(settings, "jwt_trust_entra_group_admin_enabled", True)
        monkeypatch.setattr(settings, "jwt_trust_admin_groups", [ADMIN_GROUP])
        principal = extract_trusted_principal(_user_payload(groups=["Platform Admins"]), settings, db)
        assert principal.is_admin is False

    def test_admin_group_in_roles_claim_does_not_grant(self, db, group_admin_on):
        payload = _user_payload(roles=[ADMIN_GROUP])
        del payload["groups"]
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.is_admin is False

    def test_groups_claim_must_be_a_list(self, db, group_admin_on):
        principal = extract_trusted_principal(_user_payload(groups=ADMIN_GROUP), settings, db)
        assert principal.is_admin is False

    def test_explicit_false_admin_claim_does_not_block_group_grant(self, db, group_admin_on):
        """The group grant ORs with the admin claim; a false claim is not a veto."""
        principal = extract_trusted_principal(_user_payload(is_admin=False), settings, db)
        assert principal.is_admin is True


class TestGroupAdminIssuerScope:
    """Only Entra tokens with a consistent tenant qualify."""

    @pytest.mark.parametrize(
        "issuer",
        [
            "https://login.example.com/tenant-1/v2.0",
            "https://idp.example.com/realms/corp",
            "http://login.microsoftonline.com/" + TENANT + "/v2.0",
            "https://login.microsoftonline.com.evil.example/" + TENANT + "/v2.0",
            "https://evil.example/login.microsoftonline.com/" + TENANT + "/v2.0",
        ],
    )
    def test_non_entra_issuer_denied(self, db, group_admin_on, issuer):
        principal = extract_trusted_principal(_user_payload(iss=issuer), settings, db)
        assert principal.is_admin is False

    def test_missing_issuer_denied(self, db, group_admin_on):
        payload = _user_payload()
        del payload["iss"]
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.is_admin is False

    def test_missing_tid_denied(self, db, group_admin_on):
        payload = _user_payload()
        del payload["tid"]
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.is_admin is False

    def test_tid_issuer_mismatch_denied(self, db, group_admin_on):
        principal = extract_trusted_principal(_user_payload(tid="99999999-0000-0000-0000-000000000000"), settings, db)
        assert principal.is_admin is False

    @pytest.mark.parametrize(
        "issuer",
        [
            f"https://login.microsoftonline.com/{TENANT}/v2.0",
            f"https://login.microsoftonline.us/{TENANT}/v2.0",
            f"https://sts.windows.net/{TENANT}/",
        ],
    )
    def test_entra_issuer_hosts_accepted(self, db, group_admin_on, issuer):
        principal = extract_trusted_principal(_user_payload(iss=issuer), settings, db)
        assert principal.is_admin is True


class TestGroupAdminServicePrincipalExclusion:
    """App-only service principals never receive the group grant."""

    def test_idtyp_app_denied(self, db, group_admin_on):
        principal = extract_trusted_principal(_user_payload(idtyp="app"), settings, db)
        assert principal.is_admin is False
        assert "platform_admin" not in principal.roles

    def test_sub_equal_oid_denied(self, db, group_admin_on):
        """A v1 app-only token has no idtyp but its sub equals its oid."""
        principal = extract_trusted_principal(_user_payload(sub=USER_OID), settings, db)
        assert principal.is_admin is False

    def test_graph_resolved_service_principal_groups_denied(self, db, group_admin_on):
        """Groups injected by the app-only Graph lookup do not grant admin."""
        principal = extract_trusted_principal(_user_payload(idtyp="app", sub=USER_OID, groups=[ADMIN_GROUP]), settings, db)
        assert principal.is_admin is False

    def test_user_idtyp_still_granted(self, db, group_admin_on):
        principal = extract_trusted_principal(_user_payload(idtyp="user"), settings, db)
        assert principal.is_admin is True

    def test_service_principal_with_explicit_admin_claim_keeps_claim_behavior(self, db, group_admin_on):
        """The exclusion applies to the group grant only, not to the admin claim."""
        principal = extract_trusted_principal(_user_payload(idtyp="app", is_admin=True), settings, db)
        assert principal.is_admin is True
