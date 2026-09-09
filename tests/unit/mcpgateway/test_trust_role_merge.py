# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_trust_role_merge.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Trust-path group-to-role merge tests (issue #6272).

Every test in this file exercises the trusted-claims merge (#5899) through
the trust branch in get_current_user (#5900). Until those land, the default
funnel rejects the trust-mode token with 401 and each test fails, so all
tests carry pytest.mark.xfail(strict=True). strict=True turns any premature
XPASS into a suite failure. WO-B.8 (#5900) removes the markers when the
trust branch lands.

Merge semantics under test (per #6272):
- The resolver resolve_external_groups_to_teams returns (team_ids, role_names).
  A mapping row with cf_role set contributes its role name to role_names.
- The trusted-claims module merges role_names into the principal's roles
  list before server-side resolution. Roles already present in the token's
  roles claim are preserved (the merge is additive).
- Permissions come from the server-side roles table only. Unknown role
  names are ignored. A principal with no roles has no permissions:
  @require_permission("a2a.invoke") answers 403.
"""

# Standard
import contextlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, patch

# Third-Party
from fastapi.security import HTTPAuthorizationCredentials
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent, Base, EmailTeam, EmailUser, ExternalGroupMapping, Role
from mcpgateway.services.a2a_service import A2AAgentNotFoundError, A2AAgentService
from mcpgateway.utils.trusted_claims import resolve_external_groups_to_teams

ISSUER = "https://login.example.com/tenant-1/v2.0"
TENANT = "tenant-1"
CALLER = "trust.user@example.com"
XFAIL_REASON_MERGE = "Requires trusted_claims module from #5899 and trust branch from #5900"
XFAIL_REASON_TRUST = "Requires trust branch from #5900"


def _exp(hours: int = 1) -> float:
    """Expiry timestamp for mocked JWT payloads."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp()


def _permissions_for_roles(db, role_names) -> set:
    """Resolve role names to the permission set via the server-side roles table.

    Mirrors the trust-mode resolution rule of #6272: permissions come from
    the roles table only; unknown role names are ignored.
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
    """In-memory SQLite session seeded with teams, roles, agents, and mappings.

    Layout: CF-Team-A and CF-Team-B. Agent-A (visibility=team, team=CF-Team-A).
    Roles: developer (grants a2a.invoke), viewer (no permissions).
    Mapping rows: Entra-Group-GUID-1 -> CF-Team-A with cf_role=developer;
    Entra-Group-GUID-2 -> CF-Team-B with cf_role NULL.
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
    session.add(EmailTeam(id="team-a", name="CF-Team-A", slug="cf-team-a", created_by=owner.email, is_personal=False, visibility="private"))
    session.add(EmailTeam(id="team-b", name="CF-Team-B", slug="cf-team-b", created_by=owner.email, is_personal=False, visibility="private"))
    session.add(Role(name="developer", scope="team", permissions=["a2a.invoke"], created_by=owner.email, is_system_role=True, is_active=True))
    session.add(Role(name="viewer", scope="team", permissions=[], created_by=owner.email, is_system_role=True, is_active=True))
    session.add(
        A2AAgent(
            name="agent-a",
            slug="agent-a",
            endpoint_url="https://agent-a.example.com",
            agent_type="generic",
            protocol_version="1.0",
            capabilities={},
            config={},
            enabled=True,
            team_id="team-a",
            owner_email=owner.email,
            visibility="team",
            tags=[],
        )
    )
    session.add(ExternalGroupMapping(issuer=ISSUER, tenant=TENANT, external_group_id="entra-group-guid-1", cf_team_id="team-a", cf_role="developer"))
    session.add(ExternalGroupMapping(issuer=ISSUER, tenant=TENANT, external_group_id="entra-group-guid-2", cf_team_id="team-b", cf_role=None))
    session.commit()
    try:
        yield session
    finally:
        session.close()


async def _drive_trust_funnel(monkeypatch: pytest.MonkeyPatch, db, groups: list[str], roles_claim: Optional[list[str]] = None):
    """Drive get_current_user with a trust-mode JWT carrying the given claims.

    The token carries the given groups and, when roles_claim is not None, a
    roles claim. The funnel's internal sessions are re-pointed at the test
    database so the group resolver sees the seeded mapping rows. Returns
    (user, request).
    """
    monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
    monkeypatch.setattr(settings, "auth_cache_enabled", False)
    monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

    session_test = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr("mcpgateway.auth.SessionLocal", session_test)

    @contextlib.contextmanager
    def _fresh_db_session():
        session = session_test()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr("mcpgateway.auth.fresh_db_session", _fresh_db_session)

    jwt_payload = {
        "sub": CALLER,
        "token_use": "trusted",
        "iss": ISSUER,
        "tid": TENANT,
        "groups": groups,
        "jti": "trusted_jti_role_merge",
        "exp": _exp(),
    }
    if roles_claim is not None:
        jwt_payload["roles"] = roles_claim
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="trusted_jwt_token")  # pragma: allowlist secret
    request = SimpleNamespace(state=SimpleNamespace())

    with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
        with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
            # No local user record exists for the virtual principal.
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=None):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    user = await get_current_user(credentials=credentials, request=request)
    return user, request


@pytest.mark.xfail(strict=True, reason=XFAIL_REASON_MERGE)
class TestTrustRoleMerge:
    """Mapping cf_role merges into the principal's roles on the trust path."""

    @pytest.mark.asyncio
    async def test_mapping_role_grants_a2a_invoke(self, monkeypatch, db):
        """cf_role=developer + no roles claim -> a2a.invoke granted.

        The resolver supplies the role name; the merged roles resolve
        against the roles table to a permission set that contains
        a2a.invoke, so @require_permission("a2a.invoke") passes.
        """
        team_ids, role_names = resolve_external_groups_to_teams(ISSUER, TENANT, ["entra-group-guid-1"], db)
        assert team_ids == ["team-a"]
        assert role_names == ["developer"]

        user, request = await _drive_trust_funnel(monkeypatch, db, ["entra-group-guid-1"])
        assert request.state.token_teams == ["team-a"]
        assert "developer" in user.roles
        assert "a2a.invoke" in _permissions_for_roles(db, user.roles)

    @pytest.mark.asyncio
    async def test_null_role_denies_a2a_invoke(self, monkeypatch, db):
        """cf_role=NULL + no roles claim -> 403 (no role granted).

        The mapping row grants team membership only. The merged roles list
        is empty, so the permission set is empty and
        @require_permission("a2a.invoke") answers 403.
        """
        team_ids, role_names = resolve_external_groups_to_teams(ISSUER, TENANT, ["entra-group-guid-2"], db)
        assert team_ids == ["team-b"]
        assert role_names == []

        user, request = await _drive_trust_funnel(monkeypatch, db, ["entra-group-guid-2"])
        assert request.state.token_teams == ["team-b"]
        assert user.roles == []
        assert "a2a.invoke" not in _permissions_for_roles(db, user.roles)

    @pytest.mark.asyncio
    async def test_token_roles_merge_with_mapping_role(self, monkeypatch, db):
        """cf_role=developer + token roles=["viewer"] -> ["developer", "viewer"].

        The merge is additive: roles already present in the token's roles
        claim are preserved, and the resolver-supplied role name is added.
        """
        user, request = await _drive_trust_funnel(monkeypatch, db, ["entra-group-guid-1"], roles_claim=["viewer"])
        assert request.state.token_teams == ["team-a"]
        assert set(user.roles) == {"developer", "viewer"}
        # The merged set still grants a2a.invoke through the roles table.
        assert "a2a.invoke" in _permissions_for_roles(db, user.roles)


@pytest.mark.xfail(strict=True, reason=XFAIL_REASON_TRUST)
class TestE2EGroupRoleGrant:
    """AC-e2e-group-role-grant: a mapping row drives both layers of the gate."""

    @pytest.mark.asyncio
    async def test_e2e_group_role_grant(self, monkeypatch, db):
        """Full flow: mapping row + trust JWT -> invoke passes; no mapping -> denied.

        1. Mapping row: Entra-Group-GUID-1 -> CF-Team-A, cf_role=developer.
        2. Trust-mode JWT with groups=[Entra-Group-GUID-1], no roles claim.
        3. Invoke of Agent-A (visibility=team, team=CF-Team-A) passes: the
           caller is in the agent's team (Layer 1) and the merged developer
           role grants a2a.invoke (Layer 2).
        4. A token with groups=[Entra-Group-GUID-Unmapped] (no mapping row)
           is denied at both layers: 404 at the visibility gate (the caller
           is in no team) and 403 at the permission gate (no role granted).
        """
        service = A2AAgentService()
        agent_a = db.query(A2AAgent).filter(A2AAgent.slug == "agent-a").one()

        # Steps 1-3: mapped group grants team membership and the invoke role.
        user, request = await _drive_trust_funnel(monkeypatch, db, ["entra-group-guid-1"])
        token_teams = request.state.token_teams
        assert token_teams == ["team-a"]
        assert await service._check_agent_access(db, agent_a, CALLER, token_teams) is True
        assert "a2a.invoke" in _permissions_for_roles(db, user.roles)

        # Step 4: an unmapped group fails closed at both layers.
        user, request = await _drive_trust_funnel(monkeypatch, db, ["entra-group-guid-unmapped"])
        token_teams = request.state.token_teams
        assert token_teams == []
        with pytest.raises(A2AAgentNotFoundError):
            await service.get_agent(db, agent_a.id, user_email=CALLER, token_teams=token_teams)
        assert "a2a.invoke" not in _permissions_for_roles(db, user.roles)
