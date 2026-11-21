# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_rest_tool_gateway_delegation_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box test for REST tools that delegate to their gateway against a running gateway.

A REST tool delegates in two ways:

- ``endpoint`` stores a path. The gateway resolves it against the URL of the tool gateway at call time.
- ``auth_type: "inherit"`` sends the credential of the tool gateway. The tool stores no credential.

The test drives the full runtime path:

1. A stub upstream runs on the test host. ``/mcp`` serves a minimal MCP server that the gateway registers.
   ``/mcp/api/...`` serves REST paths. ``/mcp/api/secure/...`` answers 401 unless the request carries the gateway bearer token.
   The stub records every request.
2. A gateway is registered through ``POST /gateways`` with ``auth_type=bearer``.
3. REST tools are created through ``POST /tools`` and called through the hub endpoint (``{BASE_URL}/mcp/``).

Requirements:
    - ContextForge running with ``make testing-up`` (default: http://localhost:8080).
      The compose stack maps ``host.docker.internal`` to the host. Set ``MCP_DELEGATION_UPSTREAM_HOST``
      when the gateway reaches the host under another name.

Usage:
    pytest tests/live_gateway/mcp/test_rest_tool_gateway_delegation_e2e.py -v -s --tb=short
"""

# Future
from __future__ import annotations

# Standard
from collections import OrderedDict
import logging
import os
import secrets
import socket
import threading
import time
from typing import Any, Generator
import uuid

# Third-Party
import httpx
import httpx2
from mcp.server import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams, TextContent, Tool
import pytest
from starlette.responses import JSONResponse, PlainTextResponse
import uvicorn

# Local
from ..helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway
from tests.helpers.auth import make_test_jwt

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.e2e]

_SYNC_DEADLINE = float(os.getenv("MCP_E2E_GATEWAY_SYNC_DEADLINE", "30.0"))
_UPSTREAM_HOST = os.getenv("MCP_DELEGATION_UPSTREAM_HOST", "host.docker.internal")
_BIND_HOST = os.getenv("MCP_DELEGATION_STUB_BIND_HOST", "0.0.0.0")  # noqa: S104 - the compose gateway dials the host through host.docker.internal
_GATEWAY_TOKEN = "gateway-bearer-token-for-delegation-e2e"  # pragma: allowlist secret - stub upstream fixture, not a real credential
_REST_PREFIX = "/mcp/api"


# ---------------------------------------------------------------------------
# Stub infrastructure
# ---------------------------------------------------------------------------
def _free_port() -> int:
    """Return a currently-free TCP port on the host (small race acceptable)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _serve_uvicorn(app: Any, port: int, tag: str) -> tuple[uvicorn.Server, threading.Thread]:
    """Start ``app`` on ``port`` in a daemon thread and wait until ready."""
    config = uvicorn.Config(app, host=_BIND_HOST, port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name=f"stub-{tag}")
    thread.start()
    deadline = time.monotonic() + 15.0
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError(f"Stub '{tag}' exited before becoming ready")
        if time.monotonic() > deadline:
            raise RuntimeError(f"Stub '{tag}' did not become ready within 15s")
        time.sleep(0.05)
    return server, thread


def _stop_uvicorn(server: uvicorn.Server, thread: threading.Thread, tag: str) -> None:
    """Request a clean shutdown and join the stub thread."""
    server.should_exit = True
    thread.join(timeout=10.0)
    if thread.is_alive():
        logger.warning("Stub '%s' did not stop cleanly", tag)


class _RequestLog:
    """Thread-safe record of every REST request the stub received."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[OrderedDict[str, Any]] = []

    def record(self, record: OrderedDict[str, Any]) -> None:
        with self._lock:
            self._records.append(record)

    def snapshot(self) -> list[OrderedDict[str, Any]]:
        with self._lock:
            return list(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


def _make_upstream_app(log: _RequestLog) -> Any:
    """Build a stub upstream that serves one MCP server and a set of REST paths.

    Args:
        log: Receives one record per REST request.

    Returns:
        Any: ASGI application.
    """

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:  # noqa: ARG001
        return ListToolsResult(tools=[Tool(name="stub_echo", description="Echoes the message.", inputSchema={"type": "object", "properties": {"message": {"type": "string"}}})])

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:  # noqa: ARG001
        return CallToolResult(content=[TextContent(type="text", text=str((params.arguments or {}).get("message", "")))])

    server = Server("delegation-e2e-upstream", version="1.0.0", on_list_tools=list_tools, on_call_tool=call_tool)
    mcp_app = server.streamable_http_app(streamable_http_path="/mcp", transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await mcp_app(scope, receive, send)
            return
        if not scope["path"].startswith(_REST_PREFIX):
            await mcp_app(scope, receive, send)
            return

        chunks: list[bytes] = []
        more = True
        while more:
            message = await receive()
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = b"".join(chunks)
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope["headers"]}
        secure = scope["path"].startswith(f"{_REST_PREFIX}/secure")
        accepted = not secure or headers.get("authorization") == f"Bearer {_GATEWAY_TOKEN}"
        log.record(OrderedDict(method=scope["method"], path=scope["path"], query=scope.get("query_string", b"").decode(), headers=headers, body=body, accepted=accepted))
        if not accepted:
            await PlainTextResponse("unauthorized", status_code=401)(scope, receive, send)
            return
        await JSONResponse({"path": scope["path"], "echo": body.decode("utf-8", "replace")})(scope, receive, send)

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def admin_api() -> Generator[httpx.Client, None, None]:
    """Admin API client using a ContextForge-issued JWT."""
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
    with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30.0) as client:
        yield client


@pytest.fixture(scope="module")
def stub_upstream() -> Generator[dict[str, Any], None, None]:
    """Start the stub upstream on a host port."""
    log = _RequestLog()
    port = _free_port()
    server, thread = _serve_uvicorn(_make_upstream_app(log), port, "delegation-upstream")
    try:
        yield {"mcp_url": f"http://{_UPSTREAM_HOST}:{port}/mcp", "origin": f"http://{_UPSTREAM_HOST}:{port}", "log": log}
    finally:
        _stop_uvicorn(server, thread, "delegation-upstream")


def _register_gateway(admin_api: httpx.Client, url: str, **auth: Any) -> dict[str, Any]:
    """Register a public gateway and wait until it publishes its tool.

    Args:
        admin_api: Admin API client.
        url: MCP URL of the stub upstream.
        **auth: Authentication fields of the registration body.

    Returns:
        dict[str, Any]: The gateway ID and name.
    """
    name = f"delegation-e2e-{uuid.uuid4().hex[:8]}"
    resp = admin_api.post("/gateways", json={"name": name, "url": url, "transport": "STREAMABLEHTTP", "visibility": "public", **auth})
    assert resp.status_code in (200, 201), f"Failed to register gateway: {resp.status_code} {resp.text}"
    gateway_id = resp.json()["id"]
    deadline = time.monotonic() + _SYNC_DEADLINE
    while time.monotonic() < deadline:
        tools_resp = admin_api.get(f"/tools?limit=0&gateway_id={gateway_id}")
        if tools_resp.status_code == 200 and tools_resp.json():
            return {"id": gateway_id, "name": name}
        time.sleep(1.0)
    admin_api.delete(f"/gateways/{gateway_id}")
    raise AssertionError(f"Gateway {name} did not publish its tool within {_SYNC_DEADLINE}s")


@pytest.fixture(scope="module")
def bearer_gateway(admin_api: httpx.Client, stub_upstream: dict[str, Any]) -> Generator[dict[str, Any], None, None]:
    """Register a gateway that authenticates with a bearer token."""
    gateway = _register_gateway(admin_api, stub_upstream["mcp_url"], auth_type="bearer", auth_token=_GATEWAY_TOKEN)
    try:
        yield gateway
    finally:
        admin_api.delete(f"/gateways/{gateway['id']}")


@pytest.fixture(scope="module")
def unauthenticated_gateway(admin_api: httpx.Client, stub_upstream: dict[str, Any]) -> Generator[dict[str, Any], None, None]:
    """Register a gateway without credentials. A tool cannot inherit from it."""
    gateway = _register_gateway(admin_api, stub_upstream["mcp_url"])
    try:
        yield gateway
    finally:
        admin_api.delete(f"/gateways/{gateway['id']}")


@pytest.fixture(scope="module")
def outsider_world(admin_api: httpx.Client) -> Generator[dict[str, Any], None, None]:
    """Persisted developer of a team. The developer does not own the gateways of the module."""
    suffix = uuid.uuid4().hex[:8]
    password = f"Aa1!{secrets.token_urlsafe(24)}"
    email = f"delegation-dev-{suffix}@example.com"
    team_id: str | None = None
    developer_id: str | None = None
    created_user = False

    def _must(resp: httpx.Response, expected: tuple[int, ...], what: str) -> httpx.Response:
        assert resp.status_code in expected, f"{what} returned {resp.status_code}: {resp.text[:500]}"
        return resp

    try:
        _must(
            admin_api.post(
                "/auth/email/admin/users", json={"email": email, "password": password, "full_name": "Delegation Test", "is_admin": False, "is_active": True, "password_change_required": False}
            ),
            (201,),
            "create user",
        )
        created_user = True
        team_id = _must(admin_api.post("/teams/", json={"name": f"delegation-team-{suffix}", "visibility": "private"}), (200, 201), "create team").json()["id"]
        _must(admin_api.post(f"/teams/{team_id}/members", json={"email": email, "role": "member"}), (200, 201), "add the developer to the team")
        developer_id = next(row["id"] for row in _must(admin_api.get("/rbac/roles"), (200,), "list roles").json() if row["name"] == "developer")
        _must(admin_api.post(f"/rbac/users/{email}/roles", json={"role_id": developer_id, "scope": "team", "scope_id": team_id}), (200, 201), "grant developer")

        token = make_test_jwt(email, is_admin=False, teams=[team_id], secret=JWT_SECRET, include_email_claim=True)
        with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30.0) as client:
            yield {"client": client, "team_id": team_id}
    finally:
        if developer_id and team_id:
            admin_api.delete(f"/rbac/users/{email}/roles/{developer_id}", params={"scope": "team", "scope_id": team_id})
        if team_id:
            admin_api.delete(f"/teams/{team_id}/members/{email}")
        if created_user:
            admin_api.delete(f"/auth/email/admin/users/{email}")
        if team_id:
            admin_api.delete(f"/teams/{team_id}")


def _tool_body(name: str, **fields: Any) -> dict[str, Any]:
    """Return a ``POST /tools`` body for a REST tool."""
    tool = {"name": name, "integration_type": "REST", "request_type": "POST", "input_schema": {"type": "object", "properties": {"message": {"type": "string"}}}, **fields}
    return {"tool": tool, "team_id": None, "visibility": "private"}


@pytest.fixture
def rest_tool_factory(admin_api: httpx.Client) -> Generator[Any, None, None]:
    """Create REST tools through ``POST /tools`` and delete them at teardown."""
    created: list[str] = []

    def _create(name_prefix: str, **fields: Any) -> httpx.Response:
        resp = admin_api.post("/tools", json=_tool_body(f"{name_prefix}-{uuid.uuid4().hex[:8]}", **fields))
        if resp.status_code in (200, 201):
            created.append(resp.json()["id"])
        return resp

    try:
        yield _create
    finally:
        for tool_id in created:
            try:
                admin_api.delete(f"/tools/{tool_id}")
            except Exception:  # noqa: BLE001
                logger.warning("Failed to delete tool %s during teardown", tool_id)


@pytest.fixture
async def hub_client():
    """An MCP client session against the live hub endpoint (``/mcp/``)."""
    # Standard
    import asyncio  # noqa: PLC0415

    # Third-Party
    from mcp import ClientSession  # noqa: PLC0415
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client  # noqa: PLC0415

    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
    http_client = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"}, timeout=httpx2.Timeout(10.0))
    ready = asyncio.Event()
    release = asyncio.Event()
    holder: dict[str, Any] = {}

    async def _session_runner() -> None:
        try:
            async with streamable_http_client(f"{BASE_URL}/mcp/", http_client=http_client) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream, read_timeout_seconds=10.0) as session:
                    await session.initialize()
                    holder["session"] = session
                    ready.set()
                    await release.wait()
        except BaseException as exc:  # noqa: BLE001
            holder["error"] = exc
            ready.set()

    runner = asyncio.create_task(_session_runner())
    try:
        await ready.wait()
        if "error" in holder:
            raise holder["error"]
        yield holder["session"]
    finally:
        release.set()
        if "session" not in holder and not runner.done():
            runner.cancel()
        try:
            await runner
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Live tests
# ---------------------------------------------------------------------------
@skip_no_gateway
class TestEndpointDelegationLive:
    """An endpoint resolves against the URL of the tool gateway at call time."""

    async def test_endpoint_resolves_against_the_gateway_url(self, hub_client, bearer_gateway: dict[str, Any], rest_tool_factory: Any, stub_upstream: dict[str, Any]) -> None:
        """The upstream receives the call at the gateway path prefix plus the endpoint."""
        resp = rest_tool_factory("endpoint", endpoint="/api/orders", gateway_id=bearer_gateway["id"])
        assert resp.status_code in (200, 201), resp.text
        assert resp.json()["endpoint"] == "/api/orders"
        stub_upstream["log"].clear()

        result = await hub_client.call_tool(resp.json()["name"], {"message": "hello-endpoint"})

        assert result.is_error is False, f"tool call failed: {result.content}"
        record = stub_upstream["log"].snapshot()[-1]
        assert record["path"] == f"{_REST_PREFIX}/orders"
        assert b"hello-endpoint" in record["body"]

    async def test_endpoint_without_inherit_sends_no_gateway_credential(self, hub_client, bearer_gateway: dict[str, Any], rest_tool_factory: Any, stub_upstream: dict[str, Any]) -> None:
        """An endpoint moves the URL only. The gateway credential stays with the gateway."""
        resp = rest_tool_factory("endpoint-nocred", endpoint="/api/secure/orders", gateway_id=bearer_gateway["id"])
        assert resp.status_code in (200, 201), resp.text
        stub_upstream["log"].clear()

        result = await hub_client.call_tool(resp.json()["name"], {"message": "no-credential"})

        assert result.is_error is True, "the secure path accepted a call that carried no credential"
        record = stub_upstream["log"].snapshot()[-1]
        assert "authorization" not in record["headers"]
        assert _GATEWAY_TOKEN not in str(record["headers"])

    def test_endpoint_without_a_gateway_is_rejected(self, admin_api: httpx.Client) -> None:
        resp = admin_api.post("/tools", json=_tool_body(f"endpoint-nogw-{uuid.uuid4().hex[:8]}", endpoint="/api/orders"))

        assert resp.status_code == 422, f"expected 422, got {resp.status_code} {resp.text}"

    def test_endpoint_with_a_url_is_rejected(self, admin_api: httpx.Client, bearer_gateway: dict[str, Any], stub_upstream: dict[str, Any]) -> None:
        body = _tool_body(f"endpoint-url-{uuid.uuid4().hex[:8]}", endpoint="/api/orders", url=f"{stub_upstream['origin']}/x", gateway_id=bearer_gateway["id"])

        resp = admin_api.post("/tools", json=body)

        assert resp.status_code == 422, f"expected 422, got {resp.status_code} {resp.text}"

    @pytest.mark.parametrize("endpoint", ["/a/../b", "/a/%2e%2e/b", "//evil.example/x", "/a@evil.example", "relative/path", "/a\\b"])
    def test_unsafe_endpoint_is_rejected(self, admin_api: httpx.Client, bearer_gateway: dict[str, Any], endpoint: str) -> None:
        """An endpoint cannot leave the path space of the gateway."""
        resp = admin_api.post("/tools", json=_tool_body(f"endpoint-bad-{uuid.uuid4().hex[:8]}", endpoint=endpoint, gateway_id=bearer_gateway["id"]))

        assert resp.status_code == 422, f"expected 422 for {endpoint!r}, got {resp.status_code} {resp.text}"

    def test_endpoint_on_a_non_rest_tool_is_rejected(self, admin_api: httpx.Client, bearer_gateway: dict[str, Any]) -> None:
        body = _tool_body(f"endpoint-mcp-{uuid.uuid4().hex[:8]}", endpoint="/api/orders", gateway_id=bearer_gateway["id"], integration_type="MCP", request_type="SSE")

        resp = admin_api.post("/tools", json=body)

        assert resp.status_code == 422, f"expected 422, got {resp.status_code} {resp.text}"

    def test_unauthenticated_caller_cannot_register_an_endpoint_tool(self, bearer_gateway: dict[str, Any]) -> None:
        with httpx.Client(base_url=BASE_URL, timeout=30.0) as anonymous:
            resp = anonymous.post("/tools", json=_tool_body(f"endpoint-unauth-{uuid.uuid4().hex[:8]}", endpoint="/api/orders", gateway_id=bearer_gateway["id"]))

        assert resp.status_code == 401, f"expected 401, got {resp.status_code} {resp.text}"

    def test_caller_without_tool_permission_is_rejected(self, bearer_gateway: dict[str, Any]) -> None:
        token = make_test_jwt("nobody@example.com", is_admin=False, teams=[], scopes={"permissions": ["tools.read"]}, secret=JWT_SECRET)

        with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30.0) as limited:
            resp = limited.post("/tools", json=_tool_body(f"endpoint-noperm-{uuid.uuid4().hex[:8]}", endpoint="/api/orders", gateway_id=bearer_gateway["id"]))

        assert resp.status_code in (401, 403), f"expected a deny, got {resp.status_code} {resp.text}"


@skip_no_gateway
class TestCredentialInheritanceLive:
    """A tool with ``auth_type: "inherit"`` sends the credential of its gateway."""

    async def test_inherit_sends_the_gateway_credential(self, hub_client, bearer_gateway: dict[str, Any], rest_tool_factory: Any, stub_upstream: dict[str, Any]) -> None:
        resp = rest_tool_factory("inherit", url=f"{stub_upstream['origin']}{_REST_PREFIX}/secure/orders", auth_type="inherit", gateway_id=bearer_gateway["id"])
        assert resp.status_code in (200, 201), resp.text
        stub_upstream["log"].clear()

        result = await hub_client.call_tool(resp.json()["name"], {"message": "inherit"})

        assert result.is_error is False, f"tool call failed: {result.content}"
        record = stub_upstream["log"].snapshot()[-1]
        assert record["accepted"] is True
        assert record["headers"]["authorization"] == f"Bearer {_GATEWAY_TOKEN}"

    async def test_endpoint_and_inherit_combine(self, hub_client, bearer_gateway: dict[str, Any], rest_tool_factory: Any, stub_upstream: dict[str, Any]) -> None:
        """One tool takes both the URL and the credential from its gateway."""
        resp = rest_tool_factory("delegate-both", endpoint="/api/secure/orders", auth_type="inherit", gateway_id=bearer_gateway["id"])
        assert resp.status_code in (200, 201), resp.text
        stub_upstream["log"].clear()

        result = await hub_client.call_tool(resp.json()["name"], {"message": "both"})

        assert result.is_error is False, f"tool call failed: {result.content}"
        record = stub_upstream["log"].snapshot()[-1]
        assert record["path"] == f"{_REST_PREFIX}/secure/orders"
        assert record["accepted"] is True

    def test_credential_is_not_stored_or_returned(self, admin_api: httpx.Client, bearer_gateway: dict[str, Any], rest_tool_factory: Any, stub_upstream: dict[str, Any]) -> None:
        """No read of the tool returns the gateway credential."""
        resp = rest_tool_factory("inherit-mask", url=f"{stub_upstream['origin']}{_REST_PREFIX}/mask", auth_type="inherit", gateway_id=bearer_gateway["id"])
        assert resp.status_code in (200, 201), resp.text
        tool_id = resp.json()["id"]

        bodies = [resp.text, admin_api.get(f"/tools/{tool_id}").text, admin_api.get("/tools?limit=0").text]

        for body in bodies:
            assert _GATEWAY_TOKEN not in body, "the gateway credential leaked through the tool API"
        read = admin_api.get(f"/tools/{tool_id}").json()
        assert read["authType"] == "inherit"
        assert not read.get("auth", {}).get("authValue")

    def test_inherit_without_a_gateway_is_rejected(self, admin_api: httpx.Client, stub_upstream: dict[str, Any]) -> None:
        resp = admin_api.post("/tools", json=_tool_body(f"inherit-nogw-{uuid.uuid4().hex[:8]}", url=f"{stub_upstream['origin']}/x", auth_type="inherit"))

        assert resp.status_code == 422, f"expected 422, got {resp.status_code} {resp.text}"

    def test_inherit_from_a_gateway_without_credentials_is_rejected(self, admin_api: httpx.Client, unauthenticated_gateway: dict[str, Any], stub_upstream: dict[str, Any]) -> None:
        """A tool cannot inherit what the gateway does not hold."""
        body = _tool_body(f"inherit-nocred-{uuid.uuid4().hex[:8]}", url=f"{stub_upstream['origin']}/x", auth_type="inherit", gateway_id=unauthenticated_gateway["id"])

        resp = admin_api.post("/tools", json=body)

        assert resp.status_code == 400, f"expected 400, got {resp.status_code} {resp.text}"

    def test_inherit_on_a_non_rest_tool_is_rejected(self, admin_api: httpx.Client, bearer_gateway: dict[str, Any], stub_upstream: dict[str, Any]) -> None:
        body = _tool_body(f"inherit-mcp-{uuid.uuid4().hex[:8]}", url=f"{stub_upstream['origin']}/x", auth_type="inherit", gateway_id=bearer_gateway["id"], integration_type="MCP", request_type="SSE")

        resp = admin_api.post("/tools", json=body)

        assert resp.status_code == 422, f"expected 422, got {resp.status_code} {resp.text}"

    def test_non_owner_cannot_inherit_but_can_use_an_endpoint(self, outsider_world: dict[str, Any], bearer_gateway: dict[str, Any], stub_upstream: dict[str, Any]) -> None:
        """Visibility of a gateway does not grant its credential. The endpoint sends no credential, so visibility is enough."""
        client: httpx.Client = outsider_world["client"]
        team_fields = {"team_id": outsider_world["team_id"], "visibility": "team"}
        inherit = _tool_body(f"inherit-outsider-{uuid.uuid4().hex[:8]}", url=f"{stub_upstream['origin']}/x", auth_type="inherit", gateway_id=bearer_gateway["id"])
        endpoint = _tool_body(f"endpoint-outsider-{uuid.uuid4().hex[:8]}", endpoint="/api/orders", gateway_id=bearer_gateway["id"])

        denied = client.post("/tools", json={**inherit, **team_fields})
        allowed = client.post("/tools", json={**endpoint, **team_fields})
        try:
            assert denied.status_code == 403, f"expected 403 for a non-owner inheriting a credential, got {denied.status_code} {denied.text}"
            assert "User not found" not in denied.text, "the caller must exist so the ownership gate, not authentication, denies it"
            assert _GATEWAY_TOKEN not in denied.text + allowed.text
            assert allowed.status_code in (200, 201), f"a visible gateway must allow an endpoint tool, got {allowed.status_code} {allowed.text}"
        finally:
            if allowed.status_code in (200, 201):
                client.delete(f"/tools/{allowed.json()['id']}")
