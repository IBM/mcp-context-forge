# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_trust_role_merge.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Trust-path group-to-role merge tests (issue #6272).

Every test in this file exercises the trusted-claims merge (#5899) through
the trust branch in get_current_user (#5900).

Real-entry-point conversion (#6753 / F4): the tests previously patched
``verify_jwt_token_cached`` with a pre-decoded payload and derived
permissions manually from the roles table. They now mint externally-signed
RS256 tokens from Task 9's local OIDC issuer key and drive the FULL
decorator chain — ``get_current_user`` (real ingress dispatch ->
``_maybe_verify_external`` -> JWKS verification -> claims-derived
principal) -> ``get_current_user_with_permissions`` (the RBAC decorator
dependency) -> ``check_permission_inline`` with the real PermissionService.
ONLY the OIDC discovery/JWKS network fetch is mocked.

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

# Third-Party
from fastapi.security import HTTPAuthorizationCredentials
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent, Base, EmailTeam, EmailUser, ExternalGroupMapping, Role, SSOProvider
from mcpgateway.middleware.rbac import check_permission_inline, get_current_user_with_permissions
from mcpgateway.services import sso_service
from mcpgateway.services.a2a_service import A2AAgentNotFoundError, A2AAgentService
from mcpgateway.services.permission_service import PermissionService
from mcpgateway.utils import verify_credentials as vc
from mcpgateway.utils.trusted_claims import resolve_external_groups_to_teams
from tests.live_gateway.helpers.local_oidc_issuer import generate_signing_key, mint_token

ISSUER = "https://login.example.com/tenant-1/v2.0"
JWKS_URI = "https://login.example.com/tenant-1/jwks.json"
AUDIENCE = "api://trust-role-merge-tests"
PROVIDER_ID = "local-oidc-test"
TENANT = "tenant-1"
CALLER = "trust.user@example.com"


def _exp(hours: int = 1) -> float:
    """Expiry timestamp for the minted fixtures."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp()


@pytest.fixture(scope="module")
def ext_signing_key():
    """RSA keypair shared by this module's externally-signed fixtures.

    Generated once per module via Task 9's local OIDC issuer harness; tokens
    are minted per test with distinct claim sets.
    """
    return generate_signing_key()


def _seed_trust_root_provider(db) -> None:
    """Insert (idempotently) the SSO provider row that makes ISSUER a trust root."""
    if db.query(SSOProvider).filter(SSOProvider.id == PROVIDER_ID).first() is not None:
        return
    db.add(
        SSOProvider(
            id=PROVIDER_ID,
            name=PROVIDER_ID,
            display_name="Local OIDC Test Issuer",
            provider_type="oidc",
            is_enabled=True,
            client_id="trust-role-merge-tests",
            client_secret_encrypted="unused-on-this-path",  # pragma: allowlist secret
            authorization_url=f"{ISSUER}/authorize",
            token_url=f"{ISSUER}/token",
            userinfo_url=f"{ISSUER}/userinfo",
            issuer=ISSUER,
            trusted_for_api_auth=True,
            api_audience=AUDIENCE,
        )
    )
    db.commit()


def _install_external_jwks(monkeypatch, signing_key) -> None:
    """Mock ONLY the OIDC discovery/JWKS network fetch for ISSUER.

    Signature, audience, expiry, and issuer checks in
    ``verify_oauth_access_token`` still run for real against the module RSA
    key, as do the dispatch, provider resolution, and claim mapping.
    """

    async def _fake_discover(issuer: str):
        if issuer.rstrip("/") == ISSUER.rstrip("/"):
            return {"issuer": ISSUER, "jwks_uri": JWKS_URI}
        return None

    class _StaticJWKClient:
        """Stand-in for the PyJWKClient cache entry: serves the test key."""

        def get_signing_key_from_jwt(self, _token):
            return SimpleNamespace(key=signing_key.public_key())

    monkeypatch.setattr(vc, "_discover_oidc_metadata", _fake_discover)
    monkeypatch.setitem(vc._oauth_jwks_client_cache, JWKS_URI, _StaticJWKClient())


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


async def _drive_trust_chain(monkeypatch: pytest.MonkeyPatch, db, signing_key, groups: list[str], roles_claim: Optional[list[str]] = None):
    """Drive the REAL trust ingress with an externally-signed RS256 token.

    The token carries the given groups and, when roles_claim is not None, a
    roles claim. Only the OIDC discovery/JWKS network fetch is mocked: the
    token flows through ``get_current_user`` (ingress dispatch -> JWKS
    verification -> claims-derived principal) and then
    ``get_current_user_with_permissions`` — the RBAC decorator dependency —
    so the returned user context is exactly what ``@require_permission``
    receives on a live route. The funnel's internal sessions are re-pointed
    at the test database so the group resolver and the roles table see the
    seeded rows.

    Returns (user, user_context, request).
    """
    monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
    monkeypatch.setattr(settings, "sso_api_token_auth_enabled", True)
    monkeypatch.setattr(settings, "auth_cache_enabled", False)
    monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

    session_test = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr("mcpgateway.auth.SessionLocal", session_test)
    monkeypatch.setattr("mcpgateway.db.SessionLocal", session_test)

    @contextlib.contextmanager
    def _fresh_db_session():
        session = session_test()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr("mcpgateway.auth.fresh_db_session", _fresh_db_session)

    # The autouse conftest fixture replaces PermissionService with an
    # always-allow mock; restore the real service so check_permission_inline
    # exercises the actual roles-table resolution (the point of this file).
    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", PermissionService)

    _seed_trust_root_provider(db)
    _install_external_jwks(monkeypatch, signing_key)
    sso_service.invalidate_trusted_provider_cache()
    await vc.invalidate_external_identity_cache()

    claims = {
        "iss": ISSUER,
        "sub": CALLER,
        "email": CALLER,
        "tid": TENANT,
        "aud": AUDIENCE,
        "groups": groups,
        "jti": f"trusted-jti-{'-'.join(groups)}",
        "exp": _exp(),
        "iat": datetime.now(timezone.utc).timestamp(),
    }
    if roles_claim is not None:
        claims["roles"] = roles_claim
    token = mint_token(claims, signing_key)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)  # pragma: allowlist secret
    request = SimpleNamespace(
        state=SimpleNamespace(db=db),
        cookies={},
        headers={"user-agent": "pytest"},
        client=None,
    )

    user = await get_current_user(credentials=credentials, request=request)
    user_context = await get_current_user_with_permissions(request=request, credentials=credentials)
    return user, user_context, request


class TestTrustRoleMerge:
    """Mapping cf_role merges into the principal's roles on the trust path."""

    @pytest.mark.asyncio
    async def test_mapping_role_grants_a2a_invoke(self, monkeypatch, db, ext_signing_key):
        """cf_role=developer + no roles claim -> a2a.invoke granted.

        The resolver supplies the role name; the merged roles resolve
        against the roles table to a permission set that contains
        a2a.invoke, so the real decorator chain
        (get_current_user_with_permissions -> check_permission_inline)
        grants the permission.
        """
        team_ids, role_names = resolve_external_groups_to_teams(ISSUER, TENANT, ["entra-group-guid-1"], db)
        assert team_ids == ["team-a"]
        assert role_names == ["developer"]

        user, ctx, request = await _drive_trust_chain(monkeypatch, db, ext_signing_key, ["entra-group-guid-1"])
        assert request.state.token_teams == ["team-a"]
        assert "developer" in user.roles
        # The claims-derived role reached the decorator's user context...
        assert ctx["token_use"] == "trusted"
        assert ctx["token_teams"] == ["team-a"]
        assert "developer" in ctx["roles"]
        # ...and the real PermissionService grants a2a.invoke through the
        # server-side roles table.
        assert await check_permission_inline(ctx, "a2a.invoke", db=db) is True

    @pytest.mark.asyncio
    async def test_null_role_denies_a2a_invoke(self, monkeypatch, db, ext_signing_key):
        """cf_role=NULL + no roles claim -> denied (no role granted).

        The mapping row grants team membership only. The merged roles list
        is empty, so the permission set is empty and the real decorator
        chain denies a2a.invoke (403 at the route layer).
        """
        team_ids, role_names = resolve_external_groups_to_teams(ISSUER, TENANT, ["entra-group-guid-2"], db)
        assert team_ids == ["team-b"]
        assert role_names == []

        user, ctx, request = await _drive_trust_chain(monkeypatch, db, ext_signing_key, ["entra-group-guid-2"])
        assert request.state.token_teams == ["team-b"]
        assert user.roles == []
        assert ctx["roles"] == []
        assert await check_permission_inline(ctx, "a2a.invoke", db=db) is False

    @pytest.mark.asyncio
    async def test_token_roles_merge_with_mapping_role(self, monkeypatch, db, ext_signing_key):
        """cf_role=developer + token roles=["viewer"] -> ["developer", "viewer"].

        The merge is additive: roles already present in the token's roles
        claim are preserved, and the resolver-supplied role name is added.
        """
        user, ctx, request = await _drive_trust_chain(monkeypatch, db, ext_signing_key, ["entra-group-guid-1"], roles_claim=["viewer"])
        assert request.state.token_teams == ["team-a"]
        assert set(user.roles) == {"developer", "viewer"}
        assert set(ctx["roles"]) == {"developer", "viewer"}
        # The merged set still grants a2a.invoke through the roles table.
        assert await check_permission_inline(ctx, "a2a.invoke", db=db) is True

    @pytest.mark.asyncio
    async def test_resolved_role_without_permissions_denies(self, monkeypatch, db, ext_signing_key):
        """token roles=["viewer"] + team mapping (cf_role NULL) -> denied.

        Pins the boundary the merge tests rely on: a role name that
        RESOLVES to an active roles-table row but carries no permissions
        grants nothing. The viewer role is server-side valid (it stays in
        the merged roles list), yet the real decorator chain denies
        a2a.invoke. This isolates Layer 2 (role permissions) from the
        public-only suppression, because the token still maps to team-b.
        Green by design: this row covers behavior fixed by the scope-exact
        composition (#6744) and decorator forwarding (#6749) layers, so the
        conversion lands it green rather than red-first.
        """
        user, ctx, request = await _drive_trust_chain(monkeypatch, db, ext_signing_key, ["entra-group-guid-2"], roles_claim=["viewer"])
        assert request.state.token_teams == ["team-b"]
        assert user.roles == ["viewer"]
        assert ctx["roles"] == ["viewer"]
        assert await check_permission_inline(ctx, "a2a.invoke", db=db) is False


class TestE2EGroupRoleGrant:
    """AC-e2e-group-role-grant: a mapping row drives both layers of the gate."""

    @pytest.mark.asyncio
    async def test_e2e_group_role_grant(self, monkeypatch, db, ext_signing_key):
        """Full flow: mapping row + trust JWT -> invoke passes; no mapping -> denied.

        1. Mapping row: Entra-Group-GUID-1 -> CF-Team-A, cf_role=developer.
        2. Externally-signed RS256 trust token with groups=[Entra-Group-GUID-1],
           no roles claim, through the real ingress + decorator chain.
        3. Invoke of Agent-A (visibility=team, team=CF-Team-A) passes: the
           caller is in the agent's team (Layer 1) and the merged developer
           role grants a2a.invoke through the real PermissionService
           (Layer 2).
        4. A token with groups=[Entra-Group-GUID-Unmapped] (no mapping row)
           is denied at both layers: 404 at the visibility gate (the caller
           is in no team) and denied at the permission gate (no role
           granted).
        """
        service = A2AAgentService()
        agent_a = db.query(A2AAgent).filter(A2AAgent.slug == "agent-a").one()

        # Steps 1-3: mapped group grants team membership and the invoke role.
        user, ctx, request = await _drive_trust_chain(monkeypatch, db, ext_signing_key, ["entra-group-guid-1"])
        assert ctx["email"] == CALLER
        token_teams = ctx["token_teams"]
        assert token_teams == ["team-a"]
        assert await service._check_agent_access(db, agent_a, CALLER, token_teams) is True
        assert await check_permission_inline(ctx, "a2a.invoke", db=db) is True

        # Step 4: an unmapped group fails closed at both layers.
        user, ctx, request = await _drive_trust_chain(monkeypatch, db, ext_signing_key, ["entra-group-guid-unmapped"])
        token_teams = ctx["token_teams"]
        assert token_teams == []
        with pytest.raises(A2AAgentNotFoundError):
            await service.get_agent(db, agent_a.id, user_email=CALLER, token_teams=token_teams)
        assert await check_permission_inline(ctx, "a2a.invoke", db=db) is False
