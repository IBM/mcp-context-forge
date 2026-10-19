# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_subscriptions_listen.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box proofs for MCP 2026-07-28 ``subscriptions/listen`` (#6571).

Each module fixture starts its own gateway subprocess on SQLite with
``CACHE_TYPE=memory``. Two of them federate an SDK ``MCPServer`` upstream whose
``grow`` tool adds a tool at runtime and announces it on its own listen bus:

- ``gateway_polling`` finds upstream changes through the scheduled auto-refresh.
- ``gateway_listener`` finds them through the modern upstream listener.
- ``gateway_noauth`` runs with ``MCP_REQUIRE_AUTH=false`` for the OAuth deny path.

``test_listen_cross_worker_delivery`` runs against the compose stack instead.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager, ExitStack
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from typing import Any
import uuid

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.cache.catalog_change_bus import COALESCE_SECONDS

# Local
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = pytest.mark.e2e

_ROOT = Path(__file__).resolve().parents[3]
MODERN = "2026-07-28"
LEGACY = "2025-11-25"
SUBSCRIPTION_ID = "io.modelcontextprotocol/subscriptionId"
MODERN_META = {"io.modelcontextprotocol/protocolVersion": MODERN, "io.modelcontextprotocol/clientCapabilities": {}}
ALL_KINDS = {"toolsListChanged": True, "promptsListChanged": True, "resourcesListChanged": True}
# Wire form of the snapshot pinned by test_legacy_capabilities_unchanged (unit suite).
LEGACY_CAPABILITIES = {"logging": {}, "prompts": {"listChanged": False}, "resources": {"subscribe": False, "listChanged": False}, "tools": {"listChanged": False}, "completions": {}}
POLL_WINDOW = 62
LISTENER_WINDOW = 10
LISTENER_DEBOUNCE_SECONDS = 5.0

_UPSTREAM = '''
import sys
from pathlib import Path
from mcp.server.mcpserver import Context, MCPServer
import uvicorn
mcp = MCPServer("listen-upstream")
def probe() -> str:
    """Answer a probe."""
    return "ok"
@mcp.tool()
async def grow(name: str, ctx: Context) -> str:
    """Add a tool named name and announce the change."""
    mcp.add_tool(probe, name=name, description="Added at runtime.")
    await ctx.notify_tools_changed()
    return name
app = mcp.streamable_http_app(stateless_http=True, json_response=True)
methods = Path(sys.argv[2])
async def recorder(scope, receive, send):
    if scope["type"] == "http":
        with methods.open("a") as out:
            out.write(dict(scope["headers"]).get(b"mcp-method", b"-").decode() + "\\n")
    await app(scope, receive, send)
uvicorn.run(recorder, host="127.0.0.1", port=int(sys.argv[1]), log_level="error")
'''


@dataclass
class _Stack:
    """One running gateway, with its upstream when it has one."""

    base: str
    key: str
    token: str
    server_id: str
    gateway_id: str = ""
    upstream_url: str = ""
    upstream_methods: Path | None = None


def _port() -> int:
    """Reserve an ephemeral loopback port number."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait(predicate: Callable[[], bool], description: str, timeout: float = 30) -> None:
    """Poll a condition within a bounded deadline."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    pytest.fail(f"Timed out waiting for {description}")


def _stop(process: subprocess.Popen[Any]) -> None:
    """Terminate a child process and reap its exit status."""
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _ready(url: str, process: subprocess.Popen[Any]) -> bool:
    """Return whether an HTTP process responds, failing on an early exit."""
    assert process.poll() is None, "Server exited before readiness"
    try:
        return httpx.get(url, timeout=1, trust_env=False).status_code < 500
    except httpx.TransportError:
        return False


def _admin(stack: _Stack) -> httpx.Client:
    """Return an admin REST client for a stack."""
    return httpx.Client(base_url=stack.base, headers={"Authorization": f"Bearer {stack.token}"}, timeout=30, trust_env=False)


@contextmanager
def _start(tmp: Path, overrides: dict[str, str], *, upstream: bool) -> Iterator[_Stack]:
    """Start a gateway subprocess, optionally federating the growing upstream.

    Args:
        tmp: Private directory for the database, lock files, and logs.
        overrides: Gateway environment entries specific to the fixture.
        upstream: Whether to start and register the SDK upstream.

    Yields:
        _Stack: The running stack with a public virtual server.
    """
    with ExitStack() as stack:
        upstream_url, methods = "", None
        if upstream:
            upstream_port = _port()
            methods = tmp / "upstream-methods.log"
            methods.touch()
            upstream_log = stack.enter_context((tmp / "upstream.log").open("w", encoding="utf-8"))
            process = subprocess.Popen([sys.executable, "-c", _UPSTREAM, str(upstream_port), str(methods)], stdout=upstream_log, stderr=subprocess.STDOUT, cwd=tmp)
            stack.callback(_stop, process)
            _wait(lambda: _ready(f"http://127.0.0.1:{upstream_port}/", process), "MCP upstream")
            upstream_url = f"http://127.0.0.1:{upstream_port}/mcp"
        key = secrets.token_urlsafe(48)
        port = _port()
        env = {
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(_ROOT),
            "DATABASE_URL": f"sqlite:///{tmp / 'gateway.db'}",
            "CACHE_TYPE": "memory",
            "REDIS_URL": "",
            "JWT_SECRET_KEY": key,
            "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
            "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32),
            "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
            "PLATFORM_ADMIN_EMAIL": "admin@example.com",
            "AUTH_REQUIRED": "true",
            "MCP_REQUIRE_AUTH": "true",
            "REQUIRE_USER_IN_DB": "false",
            "MCPGATEWAY_ADMIN_API_ENABLED": "true",
            "MCPGATEWAY_UI_ENABLED": "false",
            "MCPGATEWAY_A2A_ENABLED": "false",
            "SSRF_ALLOW_LOCALHOST": "true",
            "PLUGINS_ENABLED": "false",
            "OBSERVABILITY_ENABLED": "false",
            "RATE_LIMITING_ENABLED": "false",
            "HEALTH_CHECK_INTERVAL": "1",
            "AUTO_REFRESH_SERVERS": "false",
            "GATEWAY_MODERN_LISTENERS_ENABLED": "false",
            "FILELOCK_NAME": f"listen-{uuid.uuid4().hex}.lock",
            "PRIMARY_WORKER_LOCK_PATH": str(tmp / "primary.lock"),
            "LOG_LEVEL": "INFO",
            "PYTHONUNBUFFERED": "1",
            **overrides,
        }
        gateway_log = stack.enter_context((tmp / "gateway.log").open("w", encoding="utf-8"))
        gateway = subprocess.Popen([sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(port)], env=env, cwd=tmp, stdout=gateway_log, stderr=subprocess.STDOUT)
        stack.callback(_stop, gateway)
        _wait(lambda: _ready(f"http://127.0.0.1:{port}/health", gateway), "gateway readiness", timeout=90)
        token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=key)
        running = _Stack(base=f"http://127.0.0.1:{port}", key=key, token=token, server_id="", upstream_url=upstream_url, upstream_methods=methods)
        with _admin(running) as client:
            if upstream:
                response = client.post("/gateways", json={"name": "listen-upstream", "url": upstream_url, "transport": "STREAMABLEHTTP", "visibility": "public"})
                assert response.status_code in (200, 201), response.text
                running.gateway_id = response.json()["id"]
            response = client.post("/servers", json={"server": {"name": "listen-server"}, "visibility": "public"})
            assert response.status_code in (200, 201), response.text
            running.server_id = response.json()["id"]
        yield running


@pytest.fixture(scope="module")
def gateway_polling(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Stack]:
    """Gateway that finds upstream changes only through the scheduled auto-refresh.

    The fixture waits for the first scheduled refresh, so a later upstream change
    is found only on a following 60 s tick. ``GATEWAY_AUTO_REFRESH_INTERVAL``
    carries the 60 s interval because the per-server PUT is not persisted
    (see ``test_put_refresh_interval_seconds_is_persisted``).
    """
    with _start(tmp_path_factory.mktemp("polling"), {"AUTO_REFRESH_SERVERS": "true", "GATEWAY_AUTO_REFRESH_INTERVAL": "60"}, upstream=True) as stack:
        with _admin(stack) as client:
            response = client.put(f"/gateways/{stack.gateway_id}", json={"refresh_interval_seconds": 60})
            assert response.status_code == 200, response.text
            _wait(lambda: client.get(f"/gateways/{stack.gateway_id}").json().get("lastRefreshAt") is not None, "first scheduled refresh")
        yield stack


@pytest.fixture(scope="module")
def gateway_listener(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Stack]:
    """Gateway that finds upstream changes only through the modern upstream listener."""
    with _start(tmp_path_factory.mktemp("listener"), {"GATEWAY_MODERN_LISTENERS_ENABLED": "true"}, upstream=True) as stack:
        yield stack


@pytest.fixture(scope="module")
def gateway_noauth(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Stack]:
    """Gateway that lets unauthenticated callers reach /mcp."""
    with _start(tmp_path_factory.mktemp("noauth"), {"MCP_REQUIRE_AUTH": "false"}, upstream=False) as stack:
        yield stack


def _headers(token: str | None, method: str | None, protocol: str | None = MODERN) -> dict[str, str]:
    """Build Streamable HTTP request headers.

    Args:
        token: Bearer token, or None to omit Authorization.
        method: ``Mcp-Method`` value, or None to omit it.
        protocol: ``MCP-Protocol-Version`` value, or None to omit it.

    Returns:
        dict[str, str]: Header mapping.
    """
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if method:
        headers["Mcp-Method"] = method
    if protocol:
        headers["MCP-Protocol-Version"] = protocol
    return headers


def _request(method: str, params: dict[str, Any] | None = None, request_id: int = 1) -> dict[str, Any]:
    """Build a modern JSON-RPC request carrying the ``_meta`` envelope."""
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": {**(params or {}), "_meta": MODERN_META}}


def _payload(response: httpx.Response) -> dict[str, Any] | None:
    """Decode the first JSON body or SSE data frame of a response."""
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        for line in response.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:])
        return None
    return response.json() if response.content else None


def _call(stack: _Stack, path: str, token: str | None, method: str, params: dict[str, Any] | None = None) -> tuple[int, dict[str, Any] | None]:
    """Send one modern request and return its status and first message."""
    response = httpx.post(stack.base + path, headers=_headers(token, method), json=_request(method, params), timeout=30, trust_env=False)
    return response.status_code, _payload(response)


def _listen_once(stack: _Stack, path: str, token: str | None, notifications: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    """Open a listen stream and return its status and first message, then close it."""
    body = _request("subscriptions/listen", {"notifications": notifications})
    with httpx.stream("POST", stack.base + path, headers=_headers(token, "subscriptions/listen"), json=body, timeout=30, trust_env=False) as response:
        if not response.headers.get("content-type", "").startswith("text/event-stream"):
            response.read()
            return response.status_code, _payload(response)
        for line in response.iter_lines():
            if line.startswith("data:"):
                return response.status_code, json.loads(line[5:])
    return response.status_code, None


@asynccontextmanager
async def _listening(base: str, path: str, token: str, notifications: dict[str, Any] | None = None) -> AsyncIterator[tuple[dict[str, Any], asyncio.Queue[dict[str, Any]]]]:
    """Hold a listen stream open and queue every frame after the acknowledgement.

    Args:
        base: Gateway base URL.
        path: MCP endpoint path.
        token: Bearer token.
        notifications: Requested filter; defaults to tools only.

    Yields:
        tuple: The acknowledgement and the queue of later frames.
    """
    body = _request("subscriptions/listen", {"notifications": notifications or {"toolsListChanged": True}})
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=None), trust_env=False) as client:
        async with client.stream("POST", base + path, headers=_headers(token, "subscriptions/listen"), json=body) as response:
            assert response.status_code == 200, (response.status_code, await response.aread())
            frames: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

            async def pump() -> None:
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        frames.put_nowait(json.loads(line[5:]))

            task = asyncio.create_task(pump())
            try:
                ack = await asyncio.wait_for(frames.get(), 10)
                assert ack["method"] == "notifications/subscriptions/acknowledged", ack
                assert ack["params"]["_meta"][SUBSCRIPTION_ID] == 1, ack
                yield ack, frames
            finally:
                task.cancel()


async def _next_event(frames: asyncio.Queue[dict[str, Any]], method: str, deadline: float) -> dict[str, Any]:
    """Return the next frame with the given method before a monotonic deadline."""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail(f"No {method} before the deadline")
        try:
            frame = await asyncio.wait_for(frames.get(), remaining)
        except asyncio.TimeoutError:
            pytest.fail(f"No {method} before the deadline")
        if frame.get("method") == method:
            assert frame["params"]["_meta"][SUBSCRIPTION_ID] == 1, frame
            return frame


async def _grow(stack: _Stack) -> str:
    """Add a uniquely named tool on the upstream and return its name."""
    # Third-Party
    from mcp import Client  # pylint: disable=import-outside-toplevel

    name = f"grown{uuid.uuid4().hex[:10]}"
    async with Client(stack.upstream_url) as client:
        result = await client.call_tool("grow", {"name": name})
    assert not result.is_error, result
    return name


def _listed(stack: _Stack, name: str) -> bool:
    """Return whether the gateway catalog lists a tool whose name contains ``name``."""
    with _admin(stack) as client:
        tools = client.get("/tools").json()
    if isinstance(tools, dict):
        tools = tools["tools"]
    return any(name in tool["name"] for tool in tools)


def _scoped_token(stack: _Stack, permissions: list[str]) -> str:
    """Mint a non-admin public-only token capped to the given permissions."""
    scopes = {"server_id": None, "permissions": permissions, "ip_restrictions": [], "time_restrictions": {}}
    return make_test_jwt(f"scoped-{uuid.uuid4().hex[:8]}@example.com", teams=[], scopes=scopes, secret=stack.key)


def _create_tool(client: httpx.Client) -> str:
    """Create a REST tool through the admin API and return its id."""
    response = client.post("/tools", json={"tool": {"name": f"listen-probe-{uuid.uuid4().hex[:8]}", "url": "https://example.com/probe", "integration_type": "REST", "request_type": "GET"}})
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


async def test_listen_on_mcp_gets_tools_list_changed_after_admin_create(gateway_listener: _Stack) -> None:
    """The ack carries the subscription id; an admin create yields a stamped tools/list_changed within 3 s."""
    async with _listening(gateway_listener.base, "/mcp/", gateway_listener.token) as (ack, frames):
        assert ack["params"]["notifications"] == {"toolsListChanged": True}
        with _admin(gateway_listener) as client:
            _create_tool(client)
        await _next_event(frames, "notifications/tools/list_changed", time.monotonic() + 3)


async def test_listen_on_server_scoped_path_gets_event(gateway_listener: _Stack) -> None:
    """A stream on /servers/{id}/mcp receives catalog changes too."""
    async with _listening(gateway_listener.base, f"/servers/{gateway_listener.server_id}/mcp/", gateway_listener.token) as (_, frames):
        with _admin(gateway_listener) as client:
            _create_tool(client)
        await _next_event(frames, "notifications/tools/list_changed", time.monotonic() + 3)


def test_listen_ack_omits_resource_subscriptions(gateway_listener: _Stack) -> None:
    """Requested resourceSubscriptions never appear in the ack filter."""
    status, ack = _listen_once(gateway_listener, "/mcp/", gateway_listener.token, {"toolsListChanged": True, "resourceSubscriptions": ["file:///a"]})
    assert status == 200, ack
    assert ack["params"]["notifications"] == {"toolsListChanged": True}, ack


def test_modern_discover_omits_resources_subscribe(gateway_listener: _Stack) -> None:
    """server/discover advertises listChanged and omits resources.subscribe."""
    status, payload = _call(gateway_listener, "/mcp/", gateway_listener.token, "server/discover")
    assert status == 200, payload
    capabilities = payload["result"]["capabilities"]
    assert capabilities["tools"]["listChanged"] is True, capabilities
    assert "subscribe" not in capabilities.get("resources", {}), capabilities


def test_listen_unauthenticated_401(gateway_listener: _Stack) -> None:
    """A listen request without a token is rejected."""
    status, payload = _listen_once(gateway_listener, "/mcp/", None, ALL_KINDS)
    assert status == 401, payload


def test_listen_expired_token_401(gateway_listener: _Stack) -> None:
    """A listen request with an expired token is rejected."""
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=gateway_listener.key, extra_payload={"exp": int(time.time()) - 60})
    status, payload = _listen_once(gateway_listener, "/mcp/", token, ALL_KINDS)
    assert status == 401, payload


def test_listen_without_servers_use_403(gateway_listener: _Stack) -> None:
    """A principal without servers.use cannot listen on a server-scoped path."""
    token = make_test_jwt(f"nouse-{uuid.uuid4().hex[:8]}@example.com", teams=[], secret=gateway_listener.key)
    status, payload = _listen_once(gateway_listener, f"/servers/{gateway_listener.server_id}/mcp/", token, ALL_KINDS)
    assert status == 403, payload


def test_listen_unknown_server_404(gateway_listener: _Stack) -> None:
    """A listen request on a nonexistent server is 404."""
    status, payload = _listen_once(gateway_listener, f"/servers/{uuid.uuid4().hex}/mcp/", gateway_listener.token, ALL_KINDS)
    assert status == 404, payload


def test_listen_invisible_or_disabled_server_matches_tools_list(gateway_listener: _Stack) -> None:
    """Listen on an invisible or disabled server has the same outcome as tools/list there."""
    with _admin(gateway_listener) as client:
        response = client.post("/servers", json={"server": {"name": f"listen-private-{uuid.uuid4().hex[:8]}"}, "visibility": "private"})
        assert response.status_code in (200, 201), response.text
        private_id = response.json()["id"]
        response = client.post("/servers", json={"server": {"name": f"listen-disabled-{uuid.uuid4().hex[:8]}"}, "visibility": "public"})
        assert response.status_code in (200, 201), response.text
        disabled_id = response.json()["id"]
        assert client.post(f"/servers/{disabled_id}/state", params={"activate": "false"}).status_code == 200
    public_only = make_test_jwt("admin@example.com", is_admin=True, teams=[], secret=gateway_listener.key)
    for server_id, token in ((private_id, public_only), (disabled_id, gateway_listener.token)):
        path = f"/servers/{server_id}/mcp/"
        list_status, listed = _call(gateway_listener, path, token, "tools/list")
        listen_status, listened = _listen_once(gateway_listener, path, token, {"toolsListChanged": True})
        assert listen_status == list_status, (server_id, listed, listened)
        assert (listened or {}).get("error") == (listed or {}).get("error"), (server_id, listed, listened)


def test_listen_token_scoped_tools_only_ack_has_only_tools(gateway_listener: _Stack) -> None:
    """A token capped to tools.read gets only toolsListChanged in the ack."""
    token = _scoped_token(gateway_listener, ["tools.read", "servers.use"])
    status, ack = _listen_once(gateway_listener, "/mcp/", token, ALL_KINDS)
    assert status == 200, ack
    assert ack["params"]["notifications"] == {"toolsListChanged": True}, ack


def test_listen_all_kinds_denied_matches_tools_list_error(gateway_listener: _Stack) -> None:
    """With every requested kind denied, listen fails exactly as tools/list does."""
    token = _scoped_token(gateway_listener, ["servers.use"])
    list_status, listed = _call(gateway_listener, "/mcp/", token, "tools/list")
    listen_status, listened = _listen_once(gateway_listener, "/mcp/", token, ALL_KINDS)
    assert "error" in listed, listed
    assert listen_status == list_status
    assert listened["error"] == listed["error"], (listed, listened)


def test_listen_oauth_server_unauth_401_when_require_auth_false(gateway_noauth: _Stack) -> None:
    """Anonymous listen works on /mcp but an oauth_enabled server still demands a token."""
    with _admin(gateway_noauth) as client:
        server = {"name": f"listen-oauth-{uuid.uuid4().hex[:8]}", "oauth_enabled": True, "oauth_config": {"authorization_servers": ["https://auth.example.com"]}}
        response = client.post("/servers", json={"server": server, "visibility": "public"})
        assert response.status_code in (200, 201), response.text
        oauth_id = response.json()["id"]
    status, ack = _listen_once(gateway_noauth, "/mcp/", None, {"toolsListChanged": True})
    assert status == 200, ack
    status, payload = _listen_once(gateway_noauth, f"/servers/{oauth_id}/mcp/", None, {"toolsListChanged": True})
    assert status == 401, payload


def test_legacy_client_capabilities_and_listen_unchanged(gateway_listener: _Stack) -> None:
    """A 2025-11-25 client sees the pre-listen capabilities and gets -32601 for listen."""
    initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": LEGACY, "capabilities": {}, "clientInfo": {"name": "legacy", "version": "1"}}}
    response = httpx.post(gateway_listener.base + "/mcp/", headers=_headers(gateway_listener.token, None, None), json=initialize, timeout=30, trust_env=False)
    assert response.status_code == 200, response.text
    result = _payload(response)["result"]
    assert result["protocolVersion"] == LEGACY
    assert result["capabilities"] == LEGACY_CAPABILITIES
    headers = _headers(gateway_listener.token, None, LEGACY)
    if session_id := response.headers.get("mcp-session-id"):
        headers["Mcp-Session-Id"] = session_id
    listen = {"jsonrpc": "2.0", "id": 2, "method": "subscriptions/listen", "params": {"notifications": {"toolsListChanged": True}}}
    response = httpx.post(gateway_listener.base + "/mcp/", headers=headers, json=listen, timeout=30, trust_env=False)
    assert _payload(response)["error"]["code"] == -32601, response.text


@pytest.mark.xfail(strict=True, reason="GatewayUpdate accepts refresh_interval_seconds but GatewayService.update_gateway never writes it (pre-existing on main)")
def test_put_refresh_interval_seconds_is_persisted(gateway_polling: _Stack) -> None:
    """The per-server refresh interval set in the fixture reads back."""
    with _admin(gateway_polling) as client:
        assert client.get(f"/gateways/{gateway_polling.gateway_id}").json().get("refreshIntervalSeconds") == 60


def test_scheduled_polling_picks_up_modern_upstream_change(gateway_polling: _Stack) -> None:
    """The scheduled refresh lists a new upstream tool within one 60 s interval."""
    name = asyncio.run(_grow(gateway_polling))
    _wait(lambda: _listed(gateway_polling, name), f"scheduled refresh to list {name}", timeout=POLL_WINDOW)


def test_manual_refresh_picks_up_modern_upstream_change(gateway_polling: _Stack) -> None:
    """A manual refresh lists a new upstream tool at once."""
    name = asyncio.run(_grow(gateway_polling))
    with _admin(gateway_polling) as client:
        response = client.post(f"/gateways/{gateway_polling.gateway_id}/tools/refresh")
    assert response.status_code == 200, response.text
    assert _listed(gateway_polling, name)


async def test_scheduled_refresh_reaches_downstream_listen(gateway_polling: _Stack) -> None:
    """A scheduled refresh that finds an upstream change reaches a downstream listen stream."""
    async with _listening(gateway_polling.base, "/mcp/", gateway_polling.token) as (_, frames):
        name = await _grow(gateway_polling)
        deadline = time.monotonic() + POLL_WINDOW
        while True:
            await _next_event(frames, "notifications/tools/list_changed", deadline)
            if await asyncio.to_thread(_listed, gateway_polling, name):
                return


def _wait_upstream_listen(stack: _Stack) -> None:
    """Wait for the modern listener to hold its upstream stream and for a quiet debounce window.

    NotificationService drops a listener event that arrives within
    ``LISTENER_DEBOUNCE_SECONDS`` of the previous enqueue once that refresh has run
    (see ``test_listener_second_change_within_debounce_is_refreshed``), so each
    test starts outside that window.
    """
    assert stack.upstream_methods is not None
    _wait(lambda: "subscriptions/listen" in stack.upstream_methods.read_text(encoding="utf-8"), "modern listener to reach the upstream", timeout=45)
    time.sleep(LISTENER_DEBOUNCE_SECONDS)


def test_modern_listener_picks_up_upstream_change_without_polling(gateway_listener: _Stack) -> None:
    """The modern listener lists a new upstream tool within seconds, with polling off."""
    _wait_upstream_listen(gateway_listener)
    name = asyncio.run(_grow(gateway_listener))
    _wait(lambda: _listed(gateway_listener, name), f"listener refresh to list {name}", timeout=LISTENER_WINDOW)


async def test_listener_refresh_reaches_downstream_listen(gateway_listener: _Stack) -> None:
    """A listener-driven refresh reaches a downstream listen stream within seconds."""
    await asyncio.to_thread(_wait_upstream_listen, gateway_listener)
    async with _listening(gateway_listener.base, "/mcp/", gateway_listener.token) as (_, frames):
        name = await _grow(gateway_listener)
        deadline = time.monotonic() + LISTENER_WINDOW
        while True:
            await _next_event(frames, "notifications/tools/list_changed", deadline)
            if await asyncio.to_thread(_listed, gateway_listener, name):
                return


@pytest.mark.xfail(strict=True, reason="NotificationService._enqueue_refresh drops an event inside the debounce window when the earlier refresh already ran; no trailing refresh")
def test_listener_second_change_within_debounce_is_refreshed(gateway_listener: _Stack) -> None:
    """A second upstream change seconds after a listener refresh is still listed."""
    _wait_upstream_listen(gateway_listener)
    first = asyncio.run(_grow(gateway_listener))
    _wait(lambda: _listed(gateway_listener, first), f"listener refresh to list {first}", timeout=LISTENER_WINDOW)
    second = asyncio.run(_grow(gateway_listener))
    _wait(lambda: _listed(gateway_listener, second), f"listener refresh to list {second}", timeout=LISTENER_WINDOW)


@skip_no_gateway
async def test_listen_cross_worker_delivery() -> None:
    """Deliver every create to one listen stream across workers through Redis.

    The compose stack runs several replicas and workers behind nginx
    ``least_conn`` with ``CACHE_TYPE=redis``. Each create uses a fresh client
    with no keep-alive, so most creates land on another worker than the stream.
    A broken Redis fan-out drops those events and fails this test. Creates are
    spaced ``2 * COALESCE_SECONDS`` apart so each one yields its own event.
    """
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
    created: list[str] = []
    received = 0
    try:
        async with _listening(BASE_URL, "/mcp/", token) as (_, frames):
            for _ in range(5):
                with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}", "Connection": "close"}, timeout=30) as client:
                    created.append(_create_tool(client))
                await asyncio.sleep(2 * COALESCE_SECONDS)
            deadline = time.monotonic() + 10
            while received < 6 and time.monotonic() < deadline:
                try:
                    frame = await asyncio.wait_for(frames.get(), deadline - time.monotonic())
                except asyncio.TimeoutError:
                    break
                received += frame.get("method") == "notifications/tools/list_changed"
    finally:
        with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30) as client:
            for tool_id in created:
                client.delete(f"/tools/{tool_id}")
    assert received == 5, f"expected one tools/list_changed per create, got {received}"
