# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_server_create_nested_team_override.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway black-box reproduction of HackerOne report 4110271.

Claim: a Team A token holding ``servers.create`` can create a server row in Team B and
set a Team B member as owner by sending ``team_id``/``owner_email`` inside the nested
``server`` object of ``POST /v1/servers`` while the top-level ``team_id`` names Team A.

Every account, team, role and API token is created through the HTTP API of a private
gateway subprocess (see ``isolated_gateway``). Alice and Bob log in with a password and
mint their own API tokens through ``POST /tokens``. No Docker stack is required.
"""

# Future
from __future__ import annotations

# Standard
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
import json
import socket
import subprocess
import threading
import time
from typing import Any, Iterator
import uuid

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.e2e.test_candidate_credential_handshake import _DualStackThreadingHTTPServer, _GatewayFixture, isolated_gateway  # noqa: F401  pylint: disable=unused-import

pytestmark = pytest.mark.e2e

_PASSWORD = "E2eNestedTeam!42"  # pragma: allowlist secret
_KINDS = ("servers", "tools", "resources", "prompts")
_ALICE_PERMISSIONS = [f"{kind}.{action}" for kind in _KINDS for action in ("create", "read", "update")] + ["gateways.create", "gateways.read"]
_BOB_PERMISSIONS = [f"{kind}.{action}" for kind in _KINDS for action in ("create", "read")]


def _api(client: httpx.Client, method: str, path: str, *, expected: tuple[int, ...] = (200, 201), **kwargs: Any) -> Any:
    """Send an API request, assert its status and return the JSON body."""
    response = client.request(method, path, **kwargs)
    assert response.status_code in expected, f"{method} {path} returned {response.status_code}: {response.text[:500]}"
    return response.json() if response.content else None


def _grant(admin: httpx.Client, email: str, permissions: list[str], *, team_id: str) -> None:
    """Create a team-scoped role holding ``permissions`` and grant it to ``email``."""
    role = _api(admin, "POST", "/rbac/roles", json={"name": f"nested-role-{uuid.uuid4().hex[:8]}", "scope": "team", "permissions": permissions})
    _api(admin, "POST", f"/rbac/users/{email}/roles", json={"role_id": role["id"], "scope": "team", "scope_id": team_id})


def _login(base_url: str, email: str) -> str:
    """Log in with email and password and return the session JWT."""
    with httpx.Client(base_url=base_url, timeout=30, trust_env=False) as anon:
        return _api(anon, "POST", "/auth/email/login", json={"email": email, "password": _PASSWORD})["access_token"]


def _mint_api_token(base_url: str, email: str, team_id: str, permissions: list[str]) -> httpx.Client:
    """Return a client that authenticates with a product-issued API token scoped to ``team_id``."""
    with httpx.Client(base_url=base_url, headers=make_auth_headers(_login(base_url, email)), timeout=30, trust_env=False) as session:
        created = _api(session, "POST", "/tokens", json={"name": f"nested-{uuid.uuid4().hex[:6]}", "team_id": team_id, "expires_in_days": 1, "scope": {"permissions": permissions}})
    return httpx.Client(base_url=base_url, headers=make_auth_headers(created["access_token"]), timeout=30, trust_env=False)


class _World:
    """Teams A and B, Alice (A only), Bob (B only), and their API-token clients."""

    def __init__(self, gateway: _GatewayFixture) -> None:
        """Provision both tenants through the admin API."""
        self.admin, _token, self.base_url, self.signing_key = gateway
        suffix = uuid.uuid4().hex[:8]
        self.team_a = _api(self.admin, "POST", "/teams/", json={"name": f"team-a-{suffix}", "visibility": "private"})["id"]
        self.team_b = _api(self.admin, "POST", "/teams/", json={"name": f"team-b-{suffix}", "visibility": "private"})["id"]
        self.alice = f"alice-{suffix}@example.com"
        self.bob = f"bob-{suffix}@example.com"
        for email, team_id in ((self.alice, self.team_a), (self.bob, self.team_b)):
            _api(
                self.admin,
                "POST",
                "/auth/email/admin/users",
                expected=(201,),
                json={"email": email, "password": _PASSWORD, "full_name": email.split("-")[0], "is_admin": False, "is_active": True, "password_change_required": False},
            )
            _api(self.admin, "POST", f"/teams/{team_id}/members", json={"email": email, "role": "member"})
        _grant(self.admin, self.alice, _ALICE_PERMISSIONS, team_id=self.team_a)
        _grant(self.admin, self.bob, _BOB_PERMISSIONS, team_id=self.team_b)
        self.alice_client = _mint_api_token(self.base_url, self.alice, self.team_a, _ALICE_PERMISSIONS)
        self.bob_client = _mint_api_token(self.base_url, self.bob, self.team_b, _BOB_PERMISSIONS)

    def close(self) -> None:
        """Close the token clients."""
        self.alice_client.close()
        self.bob_client.close()

    def admin_view(self, server_id: str) -> dict[str, Any]:
        """Return the stored server as the platform admin sees it."""
        return _api(self.admin, "GET", f"/v1/servers/{server_id}")


@pytest.fixture
def world(isolated_gateway: _GatewayFixture) -> Any:  # noqa: F811  pylint: disable=redefined-outer-name
    """Provision the two-tenant world and tear down its clients."""
    built = _World(isolated_gateway)
    yield built
    built.close()


def test_positive_control_alice_creates_in_team_a(world: _World) -> None:
    """Step 2: a well-formed A create lands in A, owned by Alice."""
    body = {"server": {"name": "ctl-a", "team_id": world.team_a, "owner_email": world.alice}, "team_id": world.team_a, "visibility": "team"}
    created = _api(world.alice_client, "POST", "/v1/servers", expected=(201,), json=body)
    stored = world.admin_view(created["id"])
    assert stored["teamId"] == world.team_a
    assert stored["ownerEmail"] == world.alice


def test_denial_control_direct_team_b_create_is_refused(world: _World) -> None:
    """Step 3: top-level team B with the A token is denied and writes nothing."""
    body = {"server": {"name": "ctl-b", "team_id": world.team_b, "owner_email": world.bob}, "team_id": world.team_b, "visibility": "team"}
    _api(world.alice_client, "POST", "/v1/servers", expected=(403,), json=body)
    names = [s["name"] for s in _api(world.admin, "GET", "/v1/servers", params={"include_inactive": True, "limit": 0})]
    assert "ctl-b" not in names


def test_nested_team_and_owner_override_is_rejected(world: _World) -> None:
    """Steps 4-5: top-level A with nested B/Bob must not write a Team B row.

    Passing means the gateway is not vulnerable. Failing reproduces the report.
    """
    body = {"server": {"name": "nested-foreign-team", "team_id": world.team_b, "owner_email": world.bob}, "team_id": world.team_a, "visibility": "team"}
    response = world.alice_client.post("/v1/servers", json=body)
    servers = _api(world.admin, "GET", "/v1/servers", params={"include_inactive": True, "limit": 0})
    leaked = [s for s in servers if s["name"] == "nested-foreign-team"]
    reads = {}
    if response.status_code == 201:
        new_id = response.json()["id"]
        reads = {"alice_get": world.alice_client.get(f"/v1/servers/{new_id}").status_code, "bob_get": world.bob_client.get(f"/v1/servers/{new_id}").status_code}
    detail = f"status={response.status_code} rows={[(s.get('teamId'), s.get('ownerEmail'), s.get('createdBy')) for s in leaked]} team_b={world.team_b} reads={reads}"
    assert not any(s.get("teamId") == world.team_b or s.get("ownerEmail") == world.bob for s in leaked), f"VULNERABLE: {detail}"


def test_read_only_token_cannot_create(world: _World) -> None:
    """Step 7: a read-only A token is refused and creates nothing."""
    read_only = _mint_api_token(world.base_url, world.alice, world.team_a, ["servers.read"])
    with read_only:
        body = {"server": {"name": "ro-attempt"}, "team_id": world.team_a, "visibility": "team"}
        assert read_only.post("/v1/servers", json=body).status_code == 403


def _nested_body(kind: str, name: str, world: _World) -> dict[str, Any]:
    """Build the attack body: top-level Team A, nested Team B and Bob, for ``kind``."""
    nested = {"name": name, "team_id": world.team_b, "owner_email": world.bob, "visibility": "team"}
    if kind == "tools":
        return {"tool": {**nested, "url": "http://example.com/api", "integration_type": "REST", "request_type": "GET", "input_schema": {"type": "object", "properties": {}}}, "team_id": world.team_a}
    if kind == "servers":
        return {"server": nested, "team_id": world.team_a, "visibility": "team"}
    if kind == "resources":
        return {"resource": {**nested, "uri": f"file:///{name}.txt", "content": "x"}, "team_id": world.team_a, "visibility": "team"}
    return {"prompt": {**nested, "template": "hello", "arguments": []}, "team_id": world.team_a, "visibility": "team"}


@pytest.mark.parametrize("kind", ["tools", "resources", "prompts"])
def test_sibling_create_routes_reject_nested_team_override(world: _World, kind: str) -> None:
    """The same nested override against tools, resources and prompts must not write a Team B row."""
    name = f"nested-{kind}-{uuid.uuid4().hex[:6]}"
    response = world.alice_client.post(f"/v1/{kind}", json=_nested_body(kind, name, world))
    rows = [r for r in _api(world.admin, "GET", f"/v1/{kind}", params={"include_inactive": True, "limit": 0}) if r.get("name") == name or r.get("uri", "").endswith(f"{name}.txt")]
    detail = f"{kind}: status={response.status_code} rows={[(r.get('teamId'), r.get('ownerEmail'), r.get('createdBy')) for r in rows]} team_b={world.team_b}"
    assert not any(r.get("teamId") == world.team_b or r.get("ownerEmail") == world.bob for r in rows), f"VULNERABLE {detail}"
    if response.status_code == 403:
        assert not rows, f"refused request still wrote a row: {detail}"
        return
    assert response.status_code in (200, 201), f"unexpected status: {detail} body={response.text[:300]}"
    assert [(r.get("teamId"), r.get("ownerEmail")) for r in rows] == [(world.team_a, world.alice)], detail


@pytest.mark.parametrize("kind", ["servers", "resources", "prompts"])
@pytest.mark.parametrize("keep_top_level_team", [True, False], ids=["top-level-team-a", "nested-only"])
def test_session_token_cannot_use_nested_team_override(world: _World, kind: str, keep_top_level_team: bool) -> None:
    """A password-login session token follows the same rule as an API token."""
    body = _nested_body(kind, f"session-{kind}-{uuid.uuid4().hex[:6]}", world)
    if not keep_top_level_team:
        body.pop("team_id")
    name = body[kind[:-1]]["name"]
    with httpx.Client(base_url=world.base_url, headers=make_auth_headers(_login(world.base_url, world.alice)), timeout=30, trust_env=False) as session:
        response = session.post(f"/v1/{kind}", json=body)
    rows = [r for r in _api(world.admin, "GET", f"/v1/{kind}", params={"include_inactive": True, "limit": 0}) if r.get("name") == name]
    detail = f"{kind}: status={response.status_code} rows={[(r.get('teamId'), r.get('ownerEmail')) for r in rows]} team_b={world.team_b}"
    assert not any(r.get("teamId") == world.team_b or r.get("ownerEmail") == world.bob for r in rows), f"VULNERABLE {detail}"


# ---------------------------------------------------------------------------
# Update routes: moving or probing a Team B row from a Team A token
# ---------------------------------------------------------------------------
def _create_as(client: httpx.Client, kind: str, name: str, team_id: str, owner: str) -> dict[str, Any]:
    """Create a team-visible ``kind`` row the legitimate way and return the response body."""
    if kind == "servers":
        body = {"server": {"name": name}, "team_id": team_id, "visibility": "team"}
    elif kind == "resources":
        body = {"resource": {"name": name, "uri": f"file:///{name}.txt", "content": "x"}, "team_id": team_id, "visibility": "team"}
    else:
        body = {"prompt": {"name": name, "template": "hello", "arguments": []}, "team_id": team_id, "visibility": "team"}
    return _api(client, "POST", f"/v1/{kind}", json=body)


def _stored(world: _World, kind: str, row_id: str) -> dict[str, Any]:
    """Return one row as the platform admin sees it, found through the list route."""
    rows = _api(world.admin, "GET", f"/v1/{kind}", params={"include_inactive": True, "limit": 0})
    return next(r for r in rows if r["id"] == row_id)


def _update_body(kind: str, name: str, team_id: str) -> dict[str, Any]:
    """Build a flat update body that names ``team_id`` and keeps visibility team."""
    body: dict[str, Any] = {"team_id": team_id, "visibility": "team", "name": name}
    if kind == "resources":
        body["uri"] = f"file:///{name}.txt"
    return body


@pytest.mark.parametrize("kind", ["servers", "resources", "prompts"])
def test_update_cannot_move_row_to_foreign_team(world: _World, kind: str) -> None:
    """Alice owns a Team A row. A PUT naming Team B must not re-home it."""
    name = f"move-{kind}-{uuid.uuid4().hex[:6]}"
    created = _create_as(world.alice_client, kind, name, world.team_a, world.alice)
    response = world.alice_client.put(f"/v1/{kind}/{created['id']}", json=_update_body(kind, name, world.team_b))
    stored = _stored(world, kind, created["id"])
    assert stored["teamId"] == world.team_a, f"VULNERABLE {kind}: status={response.status_code} teamId={stored['teamId']} team_b={world.team_b}"
    assert response.status_code in (400, 403, 404, 422), f"{kind}: unexpected status {response.status_code}: {response.text[:200]}"


@pytest.mark.parametrize("kind", ["servers", "resources", "prompts"])
def test_update_does_not_leak_foreign_team_names(world: _World, kind: str) -> None:
    """A PUT naming Team B and a name that exists only in Team B must not answer 409 (existence oracle)."""
    victim_name = f"bob-secret-{kind}-{uuid.uuid4().hex[:6]}"
    _create_as(world.bob_client, kind, victim_name, world.team_b, world.bob)
    mine = f"mine-{kind}-{uuid.uuid4().hex[:6]}"
    created = _create_as(world.alice_client, kind, mine, world.team_a, world.alice)
    probe = world.alice_client.put(f"/v1/{kind}/{created['id']}", json=_update_body(kind, victim_name, world.team_b))
    control = world.alice_client.put(f"/v1/{kind}/{created['id']}", json=_update_body(kind, f"absent-{uuid.uuid4().hex[:6]}", world.team_b))
    assert probe.status_code == control.status_code, f"ORACLE {kind}: existing-in-B={probe.status_code} absent={control.status_code} body={probe.text[:200]}"


# ---------------------------------------------------------------------------
# Discovery path: a malicious upstream MCP server names the team and owner
# ---------------------------------------------------------------------------
_EVIL_RESOURCE = "evil-discovered-resource"
_EVIL_PROMPT = "evil-discovered-prompt"
_EVIL_TOOL = "evil-discovered-tool"


def _evil_handler(team_b: str, bob: str) -> type[BaseHTTPRequestHandler]:
    """Return a handler for an upstream whose list results carry ``team_id`` and ``owner_email`` for Team B."""
    foreign = {"team_id": team_b, "owner_email": bob, "visibility": "team"}
    results: dict[str, dict[str, Any]] = {
        "tools/list": {"tools": [{"name": _EVIL_TOOL, "description": "d", "inputSchema": {"type": "object", "properties": {}}, **foreign}]},
        "resources/list": {"resources": [{"uri": "file:///evil.txt", "name": _EVIL_RESOURCE, "content": "x", **foreign}]},
        "resources/templates/list": {"resourceTemplates": []},
        "prompts/list": {"prompts": [{"name": _EVIL_PROMPT, "description": "d", "template": "hi", "arguments": [], **foreign}]},
    }

    class _Evil(BaseHTTPRequestHandler):
        """Answer the MCP handshake and the list calls."""

        def do_POST(self) -> None:  # noqa: N802
            """Dispatch one JSON-RPC message."""
            message = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            method, msg_id = message.get("method"), message.get("id")
            if msg_id is None:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if method == "server/discover":
                result: dict[str, Any] = {
                    "resultType": "complete",
                    "supportedVersions": ["2026-07-28"],
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                    "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "evil", "version": "1"}},
                }
            elif method == "initialize":
                result = {
                    "protocolVersion": (message.get("params") or {}).get("protocolVersion", "2025-03-26"),
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                    "serverInfo": {"name": "evil", "version": "1"},
                }
            elif method in results:
                result = {"resultType": "complete", "ttlMs": 0, "cacheScope": "private", **results[method]}
            else:
                result = {}
            payload = json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            """Refuse the server-initiated SSE stream."""
            self.send_response(405)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            """Silence request logging."""

    return _Evil


@contextmanager
def _evil_upstream(team_b: str, bob: str) -> Iterator[str]:
    """Serve the malicious upstream on localhost and yield its MCP URL."""
    server = _DualStackThreadingHTTPServer(("::", 0), _evil_handler(team_b, bob))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://localhost:{server.server_address[1]}/mcp"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.fixture
def lifecycle(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Start the next gateway subprocess with ``GATEWAY_ASYNC_LIFECYCLE_ENABLED`` set to the parameter."""
    real_popen = subprocess.Popen

    def popen(args: Any, **kwargs: Any) -> Any:
        if kwargs.get("env") is not None:
            kwargs["env"] = {**kwargs["env"], "GATEWAY_ASYNC_LIFECYCLE_ENABLED": request.param}
        return real_popen(args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", popen)
    return request.param


@pytest.mark.parametrize("lifecycle", ["false", "true"], indirect=True, ids=["sync-registration", "async-registration"])
def test_discovered_entities_cannot_pick_foreign_team(lifecycle: str, world: _World) -> None:  # pylint: disable=unused-argument
    """Alice registers an upstream that names Team B and Bob. Discovered rows must stay in Team A."""
    with _evil_upstream(world.team_b, world.bob) as url:
        response = world.alice_client.post(
            "/gateways", json={"name": f"evil-{uuid.uuid4().hex[:6]}", "url": url, "transport": "STREAMABLEHTTP", "visibility": "team", "team_id": world.team_a, "auth_type": "none"}, timeout=60
        )
        assert response.status_code in (200, 201, 202), f"gateway registration failed {response.status_code}: {response.text[:400]}"
        wanted = {"resources": _EVIL_RESOURCE, "prompts": _EVIL_PROMPT, "tools": _EVIL_TOOL}
        found: dict[str, list[dict[str, Any]]] = {kind: [] for kind in wanted}
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and not all(found.values()):
            for kind, needle in wanted.items():
                if found[kind]:
                    continue
                rows = _api(world.admin, "GET", f"/v1/{kind}", params={"include_inactive": True, "limit": 0})
                found[kind] = [r for r in rows if needle in (r.get("name") or "") or needle in (r.get("originalName") or "")]
            time.sleep(4)
    assert any(found.values()), "discovery produced no rows, so this test proves nothing (stub or gateway handshake problem)"
    print("DISCOVERED", {k: [(r.get("name"), r.get("teamId"), r.get("ownerEmail"), r.get("visibility")) for r in v] for k, v in found.items()}, "team_a", world.team_a, "team_b", world.team_b)
    leaked = {kind: [(r.get("teamId"), r.get("ownerEmail")) for r in rows if r.get("teamId") == world.team_b or r.get("ownerEmail") == world.bob] for kind, rows in found.items()}
    assert not any(leaked.values()), f"VULNERABLE discovery: leaked={leaked} found={ {k: len(v) for k, v in found.items()} }"


# ---------------------------------------------------------------------------
# Public-only token (no team membership needed): same override, no Team A at all
# ---------------------------------------------------------------------------
def _public_body(kind: str, name: str, nested: dict[str, Any]) -> dict[str, Any]:
    """Build a public create body for ``kind`` with ``nested`` merged into the inner object."""
    inner = {"name": name, "visibility": "public", **nested}
    if kind == "servers":
        return {"server": inner, "visibility": "public"}
    if kind == "tools":
        return {"tool": {**inner, "url": "http://example.com/api", "integration_type": "REST", "request_type": "GET", "input_schema": {"type": "object", "properties": {}}}}
    if kind == "resources":
        return {"resource": {**inner, "uri": f"file:///{name}.txt", "content": "x"}, "visibility": "public"}
    return {"prompt": {**inner, "template": "hello", "arguments": []}, "visibility": "public"}


@pytest.mark.parametrize("kind", ["servers", "tools", "resources", "prompts"])
def test_public_only_token_cannot_forge_team_or_owner(world: _World, kind: str) -> None:
    """A public-only token (``teams: []``) may create public rows but must not name a team or owner."""
    drifter = f"drifter-{uuid.uuid4().hex[:8]}@example.com"
    _api(
        world.admin,
        "POST",
        "/auth/email/admin/users",
        expected=(201,),
        json={"email": drifter, "password": _PASSWORD, "full_name": "drifter", "is_admin": False, "is_active": True, "password_change_required": False},
    )
    role = _api(world.admin, "POST", "/rbac/roles", json={"name": f"drifter-{uuid.uuid4().hex[:6]}", "scope": "global", "permissions": [f"{kind}.create", f"{kind}.read"]})
    _api(world.admin, "POST", f"/rbac/users/{drifter}/roles", json={"role_id": role["id"], "scope": "global", "scope_id": None})
    token = make_test_jwt(drifter, teams=[], secret=world.signing_key, algorithm="HS256", include_email_claim=True)
    with httpx.Client(base_url=world.base_url, headers=make_auth_headers(token), timeout=30, trust_env=False) as drifter_client:
        control_name = f"ctl-{kind}-{uuid.uuid4().hex[:6]}"
        control = drifter_client.post(f"/v1/{kind}", json=_public_body(kind, control_name, {}))
        assert control.status_code in (200, 201), f"control public create failed {control.status_code}: {control.text[:300]}"
        name = f"forge-{kind}-{uuid.uuid4().hex[:6]}"
        response = drifter_client.post(f"/v1/{kind}", json=_public_body(kind, name, {"team_id": world.team_b, "owner_email": world.bob}))
    rows = [r for r in _api(world.admin, "GET", f"/v1/{kind}", params={"include_inactive": True, "limit": 0}) if r.get("name") == name or str(r.get("uri", "")).endswith(f"{name}.txt")]
    detail = f"{kind}: status={response.status_code} rows={[(r.get('teamId'), r.get('ownerEmail'), r.get('visibility'), r.get('createdBy')) for r in rows]} team_b={world.team_b}"
    assert not any(r.get("teamId") == world.team_b or r.get("ownerEmail") == world.bob for r in rows), f"VULNERABLE {detail}"
