# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_mcp_servers_test_endpoint_authz.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Authorization of the gateway connectivity test endpoints.

Invariant under test: the test endpoints need only ``gateways.read``, but a
request that carries a registered gateway's stored credential needs
``gateways.update`` on the gateway's own team plus ownership of the gateway.
A denied caller gets HTTP 403 and no request leaves the gateway.

Setup is deliberately real:
  * the real ``mcpgateway.main.app`` through ``TestClient``;
  * a temp SQLite DB (``SessionLocal``/``engine`` re-pointed in every module);
  * real RBAC: ``require_permission`` / ``PermissionService`` are not mocked;
  * roles come from ``bootstrap_default_roles``, users from
    ``EmailAuthService.create_user`` (personal team + ``default_user_role``);
  * real signed JWTs (``token_use`` and ``teams`` claims set as production does).

Only these things are stubbed or undone:
  0. The autouse allow-all ``MockPermissionService`` from tests/unit/mcpgateway/conftest.py is reverted
     to the real ``PermissionService`` on ``mcpgateway.middleware.rbac``.
  1. ``socket.getaddrinfo`` (via ``mcpgateway.common.validators.socket``): the
     synthetic host ``upstream.example.test`` resolves to public IP 93.184.215.14.
     The real ``_validate_gateway_test_target`` / ``SecurityValidator.validate_gateway_test_url`` still run.
  2. ``mcpgateway.services.gateway_service.ResilientHttpClient`` is replaced by
     a subclass that only injects ``httpx.MockTransport`` into ``client_args``.
     The real ResilientHttpClient, httpx request building and header/body
     encoding run; only the wire is replaced by a recorder.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import base64
from dataclasses import dataclass, field
import socket
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

# Third-Party
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
import mcpgateway.db as db_mod
from mcpgateway.services.gateway_service import STORED_CREDENTIAL_DENIED
from mcpgateway.services.permission_service import PermissionService as RealPermissionService
from mcpgateway.utils.create_jwt_token import _create_jwt_token
from mcpgateway.utils.retry_manager import ResilientHttpClient
from mcpgateway.utils.services_auth import encode_auth

SECRET = "SYNTHETIC-UPSTREAM-SECRET"  # pragma: allowlist secret
STORED_AUTH = f"Bearer {SECRET}"
HOST = "upstream.example.test"
GATEWAY_URL = f"https://{HOST}/mcp"
# 203.0.113.0/24 (TEST-NET-3) is is_private in Python and rejected by the real validator, so use the
# same public IP the repo-wide conftest stub uses (IANA example.com). No packet is ever sent to it.
DOC_IP = "93.184.215.14"
UPSTREAM_BODY = {"upstream": "reached", "marker": "UPSTREAM-RESPONSE"}
ENDPOINT = "/v1/mcp-servers/test"
ADMIN_ENDPOINT = "/admin/gateways/test"
HANDSHAKE = "/v1/mcp-servers/test-handshake"
DISCOVER_BODY = {"jsonrpc": "2.0", "id": 1, "result": {"supportedVersions": ["2026-07-28"]}}


def _redact(value: str) -> str:
    return value.replace(SECRET, SECRET[:9] + "***")


@dataclass
class Recorder:
    """Captures every request that would have left the gateway."""

    calls: List[Dict[str, Any]] = field(default_factory=list)
    response_body: Dict[str, Any] = field(default_factory=lambda: UPSTREAM_BODY)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(
            {
                "method": request.method,
                "url": str(request.url),
                "headers": dict(request.headers),
                "body": request.content.decode("utf-8", "replace"),
            }
        )
        return httpx.Response(200, json=self.response_body)

    def credentialed(self) -> List[Dict[str, Any]]:
        return [c for c in self.calls if c["headers"].get("authorization") == STORED_AUTH]

    def describe(self) -> str:
        if not self.calls:
            return "recorder: no outbound request"
        return "recorder: " + "; ".join(
            f"{c['method']} {c['url']} headers={_redact(str({k: v for k, v in c['headers'].items() if k in ('authorization', 'host', 'content-type')}))} body={c['body']}" for c in self.calls
        )


@dataclass
class Env:
    client: TestClient
    session_factory: Any
    recorder: Recorder
    team_ids: Dict[str, str]

    def token(self, email: str, kind: str = "session", *, teams: Optional[List[str]] = None, scopes: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        """Real signed JWT. Session: DB is authority for teams. API: embedded teams are authority."""
        payload = {"sub": email, "token_use": kind}
        team_claim = [self.team_ids[email]] if teams is None else teams
        auth_provider = "api_token" if kind == "api" else "local"
        tok = _create_jwt_token(payload, expires_in_minutes=60, user_data={"email": email, "is_admin": False, "auth_provider": auth_provider}, teams=team_claim, scopes=scopes)
        return {"Authorization": f"Bearer {tok}"}

    def admin_token(self) -> Dict[str, str]:
        payload = {"sub": "admin@example.com", "token_use": "session"}
        tok = _create_jwt_token(payload, expires_in_minutes=60, user_data={"email": "admin@example.com", "is_admin": True, "auth_provider": "local"}, teams=None)
        return {"Authorization": f"Bearer {tok}"}

    def post_test(self, headers, *, method="POST", base_url=GATEWAY_URL, path="/admin/mutate", body=None, endpoint=ENDPOINT):
        return self.client.post(endpoint, headers=headers, json={"method": method, "base_url": base_url, "path": path, "body": {"op": "mutate"} if body is None else body})

    def set_gateway(self, gateway_id: str, **fields: Any) -> None:
        """Update columns of an existing gateway row."""
        # First-Party
        from mcpgateway.db import Gateway as DbGateway

        with self.session_factory() as db:
            gateway = db.get(DbGateway, gateway_id)
            for key, value in fields.items():
                setattr(gateway, key, value)
            db.commit()

    def add_gateway(self, gateway_id: str, *, owner_email: str, visibility: str = "public", team_id: Optional[str] = None) -> str:
        """Register a bearer-credentialed gateway on its own path and return its URL."""
        # First-Party
        from mcpgateway.db import Gateway as DbGateway

        url = f"https://{HOST}/{gateway_id}"
        with self.session_factory() as db:
            db.add(
                DbGateway(
                    id=gateway_id,
                    name=gateway_id,
                    slug=gateway_id,
                    url=url,
                    description="synthetic",
                    transport="STREAMABLEHTTP",
                    capabilities={},
                    enabled=True,
                    reachable=True,
                    auth_type="bearer",
                    auth_value=encode_auth({"Authorization": STORED_AUTH}),
                    visibility=visibility,
                    owner_email=owner_email,
                    team_id=team_id,
                )
            )
            db.commit()
        return url


@pytest.fixture
def env(monkeypatch, tmp_path):
    # First-Party
    from mcpgateway.bootstrap_db import bootstrap_default_roles
    from mcpgateway.config import settings
    from mcpgateway.db import EmailTeam, Gateway as DbGateway, Role, UserRole
    import mcpgateway.main as main_mod
    from mcpgateway.services.email_auth_service import EmailAuthService
    from mcpgateway.services.role_service import RoleService

    engine = create_engine(f"sqlite:///{tmp_path / 'authz.db'}", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Re-point SessionLocal / engine in every already-imported mcpgateway module.
    original_sl, original_engine = db_mod.SessionLocal, db_mod.engine
    for name, mod in list(sys.modules.items()):
        if name.startswith("mcpgateway") and mod is not None:
            if getattr(mod, "SessionLocal", None) is original_sl:
                monkeypatch.setattr(mod, "SessionLocal", factory)
            if getattr(mod, "engine", None) is original_engine:
                monkeypatch.setattr(mod, "engine", engine)
    db_mod.Base.metadata.create_all(bind=engine)

    # tests/unit/mcpgateway/conftest.py has an autouse fixture that swaps rbac.PermissionService for an
    # allow-all mock. Undo it so RBAC is real in this module.
    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", RealPermissionService)

    monkeypatch.setattr(settings, "platform_admin_email", "admin@example.com")
    monkeypatch.setattr(settings, "auth_required", True)
    monkeypatch.setattr(settings, "gateway_test_allow_registered_only", True)  # shipped default

    # (1) DNS stub: synthetic host -> documentation IP. Validator itself is real.
    monkeypatch.setattr("mcpgateway.common.validators.socket.getaddrinfo", lambda host, port, *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (DOC_IP, port or 0))])

    # (2) Wire recorder: real ResilientHttpClient, MockTransport injected.
    recorder = Recorder()

    class _RecordingClient(ResilientHttpClient):
        def __init__(self, *args, client_args=None, **kwargs):
            client_args = dict(client_args or {})
            client_args["transport"] = httpx.MockTransport(recorder.handler)
            super().__init__(*args, client_args=client_args, **kwargs)

    monkeypatch.setattr("mcpgateway.services.gateway_service.ResilientHttpClient", _RecordingClient)

    team_ids: Dict[str, str] = {}

    async def seed():
        with factory() as db:
            auth = EmailAuthService(db)
            await auth.create_user("admin@example.com", "T3stAdm!nP@ss#Xz9kPqR", "Admin", is_admin=True, skip_password_validation=True)
        with engine.connect() as conn:
            await bootstrap_default_roles(conn)
        with factory() as db:
            auth = EmailAuthService(db)
            roles = RoleService(db)
            # Custom global role: read + update only (no execute/delete)
            upd = await roles.create_role(name="gw_updater", description="read+update", scope="global", permissions=["gateways.read", "gateways.update"], created_by="admin@example.com")
            for email in ("viewer@example.com", "updater@example.com", "norole@example.com"):
                await auth.create_user(email, "T3stUs3rP@ss#Xz9kPqR2", email, skip_password_validation=True)
                team = db.query(EmailTeam).filter(EmailTeam.created_by == email, EmailTeam.is_personal.is_(True)).first()
                team_ids[email] = team.id
            await roles.assign_role_to_user("updater@example.com", upd.id, "global", None, "admin@example.com")
            # norole: drop the default platform_viewer assignment
            pv = db.query(Role).filter(Role.name == "platform_viewer").first()
            db.query(UserRole).filter(UserRole.user_email == "norole@example.com", UserRole.role_id == pv.id).delete()
            db.add(
                DbGateway(
                    id="gw-public-1",
                    name="Public Upstream",
                    slug="public-upstream",
                    url=GATEWAY_URL,
                    description="synthetic",
                    transport="STREAMABLEHTTP",
                    capabilities={},
                    enabled=True,
                    reachable=True,
                    auth_type="bearer",
                    auth_value=encode_auth({"Authorization": STORED_AUTH}),
                    visibility="public",
                    owner_email="admin@example.com",
                    team_id=None,
                )
            )
            db.commit()

    asyncio.run(seed())
    # drop RBAC permission caches populated during seeding
    try:
        # First-Party
        from mcpgateway.cache.auth_cache import auth_cache  # noqa: F401

        auth_cache.invalidate_all() if hasattr(auth_cache, "invalidate_all") else None
    except Exception:  # noqa: BLE001  # nosec B110
        pass

    yield Env(TestClient(main_mod.app, raise_server_exceptions=False), factory, recorder, team_ids)
    engine.dispose()


@pytest.fixture
def teams(env):
    """Seed team A and team B with developers, an owner, and a team-only viewer.

    Returns:
        Dict with the ``a`` and ``b`` team IDs.
    """
    # First-Party
    from mcpgateway.db import Role, UserRole
    from mcpgateway.services.email_auth_service import EmailAuthService
    from mcpgateway.services.role_service import RoleService
    from mcpgateway.services.team_management_service import TeamManagementService

    ids: Dict[str, str] = {}

    async def seed():
        with env.session_factory() as db:
            auth = EmailAuthService(db)
            roles = RoleService(db)
            team_service = TeamManagementService(db)
            for email in ("dev-a1@example.com", "dev-a2@example.com", "owner-a@example.com", "dev-b@example.com", "teamviewer-a@example.com"):
                await auth.create_user(email, "T3stUs3rP@ss#Xz9kPqR2", email, skip_password_validation=True)
            team_a = await team_service.create_team("Team A", None, created_by="owner-a@example.com", visibility="private", skip_limits=True)
            team_b = await team_service.create_team("Team B", None, created_by="admin@example.com", visibility="private", skip_limits=True)
            ids["a"], ids["b"] = team_a.id, team_b.id
            developer = await roles.get_role_by_name("developer", scope="team")
            for email, team in (("dev-a1@example.com", team_a), ("dev-a2@example.com", team_a), ("dev-b@example.com", team_b), ("teamviewer-a@example.com", team_a)):
                await team_service.add_member_to_team(team.id, email, "member", invited_by="admin@example.com")
            for email, team in (("dev-a1@example.com", team_a), ("dev-a2@example.com", team_a), ("dev-b@example.com", team_b)):
                await roles.assign_role_to_user(email, developer.id, "team", team.id, "admin@example.com")
            # create_team() records the owner membership but grants no team-scoped RBAC role to the creator.
            team_admin = await roles.get_role_by_name("team_admin", scope="team")
            await roles.assign_role_to_user("owner-a@example.com", team_admin.id, "team", team_a.id, "admin@example.com")
            pv = db.query(Role).filter(Role.name == "platform_viewer").first()
            db.query(UserRole).filter(UserRole.user_email == "teamviewer-a@example.com", UserRole.role_id == pv.id).delete()
            db.commit()

    asyncio.run(seed())
    return ids


def _assert_denied(env: Env, r: httpx.Response) -> None:
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == STORED_CREDENTIAL_DENIED, r.text
    assert env.recorder.calls == [], env.recorder.describe()


def _assert_credentialed(env: Env, r: httpx.Response) -> None:
    assert r.status_code == 200, r.text
    assert r.json()["statusCode"] == 200 and r.json()["body"] == UPSTREAM_BODY, r.text
    assert env.recorder.credentialed(), env.recorder.describe()


# --------------------------------------------------------------------------- sanity


def test_non_owner_with_gateways_update_denied(env):
    """A global ``gateways.update`` holder who does not own the gateway gets 403."""
    _assert_denied(env, env.post_test(env.token("updater@example.com")))


def test_owner_with_gateways_update_reaches_upstream(env):
    """The owner with ``gateways.update`` gets 200 and the stored credential is attached."""
    url = env.add_gateway("gw-updater-owned", owner_email="updater@example.com")
    r = env.post_test(env.token("updater@example.com"), base_url=url)
    _assert_credentialed(env, r)
    assert len(env.recorder.calls) == 1 and env.recorder.calls[0]["method"] == "POST"


def test_sanity_platform_admin_reaches_upstream(env):
    _assert_credentialed(env, env.post_test(env.admin_token()))


# --------------------------------------------------------------------------- read-only caller


@pytest.mark.parametrize("token_kind", ["session", "api"])
@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_a_b_platform_viewer_cannot_send_credentialed_state_changing_request(env, method, token_kind):
    """A read-only caller is rejected and no stored credential leaves."""
    _assert_denied(env, env.post_test(env.token("viewer@example.com", token_kind), method=method))


def test_c_control_user_without_gateways_read_is_forbidden(env):
    r = env.post_test(env.token("norole@example.com"))
    assert r.status_code == 403, r.text
    assert env.recorder.calls == []


def test_d_unregistered_host_gets_no_credentials_default_config(env):
    """Default config (registered-only allowlist): unregistered host is refused, nothing leaves."""
    r = env.post_test(env.token("viewer@example.com"), base_url="https://other.example.test/mcp")
    assert r.status_code == 200 and r.json()["statusCode"] == 400, r.text  # service-level 400 in a 200 envelope
    assert env.recorder.calls == []


def test_d_unregistered_host_gets_no_credentials_even_when_allowlisted(env, monkeypatch):
    """Registered-only off + host allowlisted: request is sent, but WITHOUT the stored credential."""
    # First-Party
    from mcpgateway.config import settings

    monkeypatch.setattr(settings, "gateway_test_allow_registered_only", False)
    monkeypatch.setattr(settings, "gateway_test_allowed_hosts", ["other.example.test"])
    r = env.post_test(env.token("viewer@example.com"), base_url="https://other.example.test/mcp")
    assert r.status_code == 200, r.text
    assert len(env.recorder.calls) == 1
    assert env.recorder.credentialed() == []
    assert "authorization" not in env.recorder.calls[0]["headers"]


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_viewer_denied_even_for_get_on_mcp_path(env, method):
    _assert_denied(env, env.post_test(env.token("viewer@example.com"), method=method, path="", body={}))


@pytest.mark.parametrize(
    "auth_type,auth_value",
    [
        ("basic", encode_auth({"Authorization": "Basic " + base64.b64encode(f"user:{SECRET}".encode()).decode()})),
        ("authheaders", encode_auth({"X-Api-Key": SECRET})),
    ],
    ids=["basic", "authheaders"],
)
def test_viewer_denied_for_each_static_auth_type(env, auth_type, auth_value):
    env.set_gateway("gw-public-1", auth_type=auth_type, auth_value=auth_value)
    _assert_denied(env, env.post_test(env.token("viewer@example.com")))


def test_viewer_denied_for_oauth_client_credentials(env, monkeypatch):
    env.set_gateway("gw-public-1", auth_type="oauth", auth_value=None, oauth_config={"grant_type": "client_credentials", "client_id": "cid", "token_url": f"https://{HOST}/token"})
    get_access_token = AsyncMock(return_value="client-credentials-token")
    monkeypatch.setattr("mcpgateway.services.gateway_service.OAuthManager.get_access_token", get_access_token)
    _assert_denied(env, env.post_test(env.token("viewer@example.com")))
    get_access_token.assert_not_awaited()


def test_viewer_not_gated_for_oauth_authorization_code(env, monkeypatch):
    """The caller's own authorization-code token is not a stored gateway credential."""
    env.set_gateway("gw-public-1", auth_type="oauth", auth_value=None, oauth_config={"grant_type": "authorization_code", "client_id": "cid", "token_url": f"https://{HOST}/token"})
    monkeypatch.setattr("mcpgateway.services.token_storage_service.TokenStorageService.get_user_token", AsyncMock(return_value="user-own-token"))
    r = env.post_test(env.token("viewer@example.com"))
    assert r.status_code == 200, r.text
    assert [c["headers"].get("authorization") for c in env.recorder.calls] == ["Bearer user-own-token"]


def test_viewer_allowed_when_gateway_has_no_stored_credential(env):
    env.set_gateway("gw-public-1", auth_type=None, auth_value=None)
    r = env.post_test(env.token("viewer@example.com"))
    assert r.status_code == 200, r.text
    assert len(env.recorder.calls) == 1
    assert "authorization" not in env.recorder.calls[0]["headers"]


@pytest.mark.parametrize("scopes,expected_status", [(None, 200), ({"permissions": ["gateways.read"]}, 403)])
def test_api_token_scoped_to_gateways_read_is_denied(env, scopes, expected_status):
    """A ``gateways.read``-scoped API token is denied even for an owner with ``gateways.update``."""
    url = env.add_gateway("gw-updater-owned", owner_email="updater@example.com")
    r = env.post_test(env.token("updater@example.com", "api", scopes=scopes), base_url=url)
    if expected_status == 200:
        _assert_credentialed(env, r)
    else:
        _assert_denied(env, r)


# --------------------------------------------------------------------------- team scope


def test_team_developer_other_team_denied_owner_team_allowed(env, teams):
    team_url = env.add_gateway("gw-team-a", owner_email="dev-a1@example.com", visibility="team", team_id=teams["a"])
    public_url = env.add_gateway("gw-public-a", owner_email="dev-a1@example.com", team_id=teams["a"])

    _assert_credentialed(env, env.post_test(env.token("dev-a1@example.com", teams=[teams["a"]]), base_url=team_url))
    env.recorder.calls.clear()

    _assert_denied(env, env.post_test(env.token("dev-a2@example.com", teams=[teams["a"]]), base_url=team_url))
    _assert_denied(env, env.post_test(env.token("dev-b@example.com", teams=[teams["b"]]), base_url=public_url))

    # Layer 1 hides team A's gateway from team B, so the request leaves without its credential.
    r = env.post_test(env.token("dev-b@example.com", teams=[teams["b"]]), base_url=team_url)
    assert r.status_code == 200, r.text
    assert env.recorder.credentialed() == [], env.recorder.describe()


def test_team_owner_allowed_for_team_gateway_denied_for_public(env, teams):
    team_url = env.add_gateway("gw-team-a", owner_email="dev-a1@example.com", visibility="team", team_id=teams["a"])
    public_url = env.add_gateway("gw-public-a", owner_email="dev-a1@example.com", team_id=teams["a"])
    owner_token = env.token("owner-a@example.com", teams=[teams["a"]])

    _assert_credentialed(env, env.post_test(owner_token, base_url=team_url))
    env.recorder.calls.clear()

    _assert_denied(env, env.post_test(owner_token, base_url=public_url))


def test_team_viewer_role_denied(env, teams):
    team_url = env.add_gateway("gw-team-a", owner_email="dev-a1@example.com", visibility="team", team_id=teams["a"])
    _assert_denied(env, env.post_test(env.token("teamviewer-a@example.com", teams=[teams["a"]]), base_url=team_url))


def test_unrelated_team_developer_denied_for_no_team_gateway(env, teams):
    _assert_denied(env, env.post_test(env.token("dev-b@example.com", teams=[teams["b"]])))


# --------------------------------------------------------------------------- admin route


def test_admin_route_returns_real_403(main_app_with_admin_api, env):
    r = env.post_test(env.token("viewer@example.com"), endpoint=ADMIN_ENDPOINT)
    _assert_denied(env, r)


# --------------------------------------------------------------------------- handshake


def _handshake(env: Env, auth: Dict[str, str], **payload: Any) -> httpx.Response:
    """Post a handshake whose upstream answers ``server/discover``, so the SDK fallback never dials out."""
    env.recorder.response_body = DISCOVER_BODY
    return env.client.post(HANDSHAKE, headers=auth, json={"base_url": GATEWAY_URL, **payload})


def test_viewer_handshake_with_path_suffix_denied(env):
    _assert_denied(env, _handshake(env, env.token("viewer@example.com"), path="admin/x"))


def test_viewer_handshake_with_caller_headers_denied(env):
    _assert_denied(env, _handshake(env, env.token("viewer@example.com"), headers={"X-HTTP-Method-Override": "DELETE"}))


def test_viewer_bare_handshake_still_allowed(env):
    r = _handshake(env, env.token("viewer@example.com"))
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True, r.text


def test_viewer_candidate_only_handshake_not_gated(env):
    r = _handshake(env, env.token("viewer@example.com"), credential_mode="candidate_only", gateway_id="gw-public-1", headers={"Authorization": "Bearer cand"}, path="x")
    assert r.status_code == 200, r.text
    assert env.recorder.calls and env.recorder.credentialed() == [], env.recorder.describe()


def test_owner_handshake_with_path_suffix_allowed(env):
    url = env.add_gateway("gw-updater-owned", owner_email="updater@example.com")
    r = _handshake(env, env.token("updater@example.com"), base_url=url, path="admin/x")
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True, r.text
    assert env.recorder.credentialed(), env.recorder.describe()


def test_viewer_handshake_oauth_client_credentials_with_path_denied(env, monkeypatch):
    env.set_gateway("gw-public-1", auth_type="oauth", auth_value=None, oauth_config={"grant_type": "client_credentials", "client_id": "cid", "token_url": f"https://{HOST}/token"})
    get_access_token = AsyncMock(return_value="client-credentials-token")
    monkeypatch.setattr("mcpgateway.services.gateway_service.OAuthManager.get_access_token", get_access_token)
    _assert_denied(env, _handshake(env, env.token("viewer@example.com"), path="x"))
    get_access_token.assert_not_awaited()


def test_viewer_handshake_client_cert_only_with_path_denied(env):
    env.set_gateway("gw-public-1", auth_type=None, auth_value=None, ca_certificate="CA-PEM", client_cert="CERT-PEM", client_key="KEY-PEM")
    _assert_denied(env, _handshake(env, env.token("viewer@example.com"), path="x"))
