# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_upstream_connect_mode_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

E2E proofs for the migrated upstream federation connect path
(``MCP_CLIENT_CONNECT_MODE``, ``mcpgateway/services/upstream_session_registry.py``
+ ``mcpgateway/utils/mcp_proxy_client.py`` on ``mcp==2.0.0b2``).

One live upstream from the docker-compose ``testing`` profile is required
(probed at module setup; the whole module skips with a readable reason when
it is unreachable):

- ``fast_time_server`` (legacy) at ``E2E_LEGACY_UPSTREAM_URL``
  (default ``http://localhost:8888/mcp``)

The gateways under test are launched from the worktree source as real uvicorn
subprocesses (own sqlite DB, own JWT secret, SSRF localhost allowances) — the
compose stack's gateway containers are intentionally NOT used.

The strict 2026-07-28 variant (``fast_time_2026_server``) was dropped from the
compose testing profile; the strict-upstream behavior matrix and the wire-level
negotiation proofs that depended on it were removed with it.

Empirical outcome of the negotiation modes against the legacy upstream
(mcp 2.0.0b2, verified by wire capture):

- ``auto`` vs legacy: ``server/discover`` errors, legacy fallback by
  design; the federated call succeeds.
- ``legacy`` vs legacy: succeeds — the pre-migration behavior is fully
  intact under the rollback flag.
"""

# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterator
import uuid

# Third-Party
import httpx
import httpx2
import pytest

# First-Party
from tests.helpers.auth import make_auth_headers, make_legacy_test_jwt

pytestmark = pytest.mark.e2e

TEST_JWT_SECRET = "T3stJwtS3cr3t!XyZ#9kPqR@vW2mN8hL"  # pragma: allowlist secret
TEST_JWT_ALGORITHM = "HS256"
TEST_ADMIN_EMAIL = "admin@example.com"

LEGACY_UPSTREAM_URL = os.environ.get("E2E_LEGACY_UPSTREAM_URL", "http://localhost:8888/mcp")

GATEWAY_STARTUP_DEADLINE_SECONDS = 120.0
TOOL_SYNC_DEADLINE_SECONDS = 90.0
POLL_INTERVAL_SECONDS = 0.5

LEGACY_VERSION = "2025-11-25"


def _health_url(mcp_url: str) -> str:
    """Derive the upstream ``/health`` URL from its ``/mcp`` URL."""
    return mcp_url.rstrip("/").removesuffix("/mcp") + "/health"


def _auth_headers() -> dict[str, str]:
    """Mint an admin-bypass JWT for the source-run gateways."""
    return make_auth_headers(
        make_legacy_test_jwt(
            TEST_ADMIN_EMAIL,
            is_admin=True,
            teams=None,
            expires_in_minutes=60,
            secret=TEST_JWT_SECRET,
            algorithm=TEST_JWT_ALGORITHM,
            include_email_claim=True,
        )
    )


@pytest.fixture(scope="module", autouse=True)
def _real_dns_for_live_calls() -> Iterator[None]:
    """Restore the real DNS resolver for this module's live localhost calls.

    The session-wide deterministic-DNS stub in ``tests/conftest.py`` only
    recognises hostnames passed as ``str``; anyio (httpx2's backend) encodes
    the host to ``bytes`` before calling ``socket.getaddrinfo``, so the stub
    rewrites ``localhost`` to a stub public IP and every async connect times
    out. E2E tests need real resolution.
    """
    # First-Party
    from tests import conftest

    socket.getaddrinfo = conftest._REAL_GETADDRINFO  # pylint: disable=protected-access
    yield
    socket.getaddrinfo = conftest._stub_getaddrinfo  # pylint: disable=protected-access


@pytest.fixture(scope="module", autouse=True)
def require_live_upstreams() -> None:
    """Skip the whole module unless the compose legacy upstream is reachable."""
    health = _health_url(LEGACY_UPSTREAM_URL)
    try:
        response = httpx.get(health, timeout=3.0)
        reachable = response.status_code == 200
    except httpx.HTTPError:
        reachable = False
    if not reachable:
        pytest.skip(
            f"docker-compose testing upstream (legacy) not reachable at {health} — start the 'testing' compose profile or point E2E_LEGACY_UPSTREAM_URL at a live server",
            allow_module_level=True,
        )


@dataclass
class GatewayHandle:
    """A source-run gateway subprocess plus its admin API coordinates."""

    mode: str
    base_url: str
    headers: dict[str, str]
    process: subprocess.Popen
    workdir: str


def _gateway_env(db_path: str, mode: str) -> dict[str, str]:
    """Curated environment for the source-run gateway (no .env leakage)."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "VIRTUAL_ENV": os.environ.get("VIRTUAL_ENV", ""),
        "DATABASE_URL": f"sqlite:///{db_path}",
        "JWT_SECRET_KEY": TEST_JWT_SECRET,
        "AUTH_ENCRYPTION_SECRET": "T3stEncS3cr3t!XyZ#9kPqR@vW2mN8hL",  # pragma: allowlist secret
        "AUTH_REQUIRED": "true",
        "REQUIRE_USER_IN_DB": "false",
        "REQUIRE_JTI": "false",
        "MCPGATEWAY_UI_ENABLED": "false",
        "MCPGATEWAY_ADMIN_API_ENABLED": "true",
        "PLUGINS_ENABLED": "false",
        "OBSERVABILITY_ENABLED": "false",
        "CACHE_TYPE": "memory",
        "LOG_LEVEL": "WARNING",
        "SSRF_ALLOW_LOCALHOST": "true",
        "SSRF_ALLOW_PRIVATE_NETWORKS": "true",
        "SSRF_DNS_FAIL_CLOSED": "false",
        "MCP_CLIENT_CONNECT_MODE": mode,
        # Stateful downstream sessions are required so the gateway issues an
        # mcp-session-id on initialize; the POOLED UpstreamSessionRegistry
        # path (#4205) keys on that downstream session id and is bypassed
        # entirely when the transport runs stateless (the default).
        "USE_STATEFUL_SESSIONS": "true",
    }
    return env


def _wait_for_gateway(handle: GatewayHandle) -> None:
    """Bounded readiness poll: TCP accept first, then authenticated /gateways."""
    deadline = time.monotonic() + GATEWAY_STARTUP_DEADLINE_SECONDS
    with httpx.Client(base_url=handle.base_url, headers=handle.headers, timeout=5.0) as client:
        while time.monotonic() < deadline:
            if handle.process.poll() is not None:
                raise RuntimeError(f"gateway subprocess (mode={handle.mode}) exited early with code {handle.process.returncode}")
            try:
                if client.get("/gateways").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"gateway (mode={handle.mode}) at {handle.base_url} not ready within {GATEWAY_STARTUP_DEADLINE_SECONDS}s")


def _launch_gateway(mode: str, port: int) -> GatewayHandle:
    """Launch ``uvicorn mcpgateway.main:app`` from the worktree venv."""
    workdir = tempfile.mkdtemp(prefix=f"mcp-e2e-connect-{mode}-")
    db_path = os.path.join(workdir, "mcp.db")
    log_file = open(os.path.join(workdir, "gateway.log"), "w", encoding="utf-8")  # noqa: SIM115
    handle = GatewayHandle(
        mode=mode,
        base_url=f"http://127.0.0.1:{port}",
        headers=_auth_headers(),
        process=subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=workdir,
            env=_gateway_env(db_path, mode),
            stdout=log_file,
            stderr=subprocess.STDOUT,
        ),
        workdir=workdir,
    )
    try:
        _wait_for_gateway(handle)
    except Exception:
        handle.process.kill()
        handle.process.wait(timeout=10)
        raise
    return handle


@pytest.fixture(scope="module")
def gateway_auto(unused_tcp_port_factory) -> Iterator[GatewayHandle]:
    """Source-run gateway with the default ``MCP_CLIENT_CONNECT_MODE=auto``."""
    handle = _launch_gateway("auto", unused_tcp_port_factory())
    yield handle
    handle.process.terminate()
    handle.process.wait(timeout=15)


@pytest.fixture(scope="module")
def gateway_legacy(unused_tcp_port_factory) -> Iterator[GatewayHandle]:
    """Source-run gateway with ``MCP_CLIENT_CONNECT_MODE=legacy`` (rollback)."""
    handle = _launch_gateway("legacy", unused_tcp_port_factory())
    yield handle
    handle.process.terminate()
    handle.process.wait(timeout=15)


@dataclass
class Federation:
    """A registered upstream plus the virtual server exposing its tools."""

    gateway_id: str
    server_id: str
    tool_names: list[str]


def _register_upstream(handle: GatewayHandle, upstream_url: str, name: str) -> Federation:
    """Register an upstream, wait for tool sync, and wrap it in a virtual server."""
    with httpx.Client(base_url=handle.base_url, headers=handle.headers, timeout=30.0) as client:
        response = client.post("/gateways", json={"name": name, "url": upstream_url, "transport": "STREAMABLEHTTP"})
        assert response.status_code == 200, f"gateway registration failed for {name}: {response.status_code} {response.text[:500]}"
        gateway_id = response.json()["id"]

        synced: list[dict[str, Any]] = []
        deadline = time.monotonic() + TOOL_SYNC_DEADLINE_SECONDS
        while time.monotonic() < deadline:
            tools = client.get("/tools").json()
            synced = [t for t in tools if t.get("gatewayId") == gateway_id or t.get("gateway_id") == gateway_id]
            if synced:
                break
            time.sleep(POLL_INTERVAL_SECONDS)
        assert synced, f"no tools synced from {name} within {TOOL_SYNC_DEADLINE_SECONDS}s"

        server_name = f"{name}-vs"
        response = client.post("/servers", json={"server": {"name": server_name, "description": f"e2e virtual server for {name}", "associated_tools": [t["id"] for t in synced]}})
        assert response.status_code in (200, 201), f"virtual server creation failed for {name}: {response.status_code} {response.text[:500]}"
        payload = response.json()
        server_id = payload.get("id") or payload.get("server", {}).get("id")
        assert server_id, f"no server id in POST /servers response: {payload}"

        return Federation(gateway_id=gateway_id, server_id=server_id, tool_names=[t["name"] for t in synced])


@pytest.fixture(scope="module")
def gateway_auto_legacy_federation(gateway_auto: GatewayHandle) -> Federation:
    """Federate the legacy upstream through the auto-mode gateway (module-scoped)."""
    return _register_upstream(gateway_auto, LEGACY_UPSTREAM_URL, f"e2e-legacy-{uuid.uuid4().hex[:8]}")


@pytest.fixture(scope="module")
def gateway_legacy_legacy_federation(gateway_legacy: GatewayHandle) -> Federation:
    """Federate the legacy upstream through the legacy-mode gateway (module-scoped)."""
    return _register_upstream(gateway_legacy, LEGACY_UPSTREAM_URL, f"e2e-legacy-legacy-{uuid.uuid4().hex[:8]}")


def _time_tool_name(tool_names: list[str]) -> str:
    """Pick the federated ``get_system_time`` tool (name may be gateway-prefixed/sanitized)."""
    for name in tool_names:
        if "get" in name and "system" in name and "time" in name:
            return name
    raise AssertionError(f"no get_system_time tool among {tool_names}")


def _read_jsonrpc(response: httpx2.Response) -> dict[str, Any]:
    """Read a JSON-RPC response body from either a JSON or an SSE-framed reply."""
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        for line in response.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise AssertionError(f"SSE response carried no data frame: {response.text[:300]}")
    return response.json()


async def _call_federated_time_tool(handle: GatewayHandle, federation: Federation) -> dict[str, Any]:
    """Drive a real downstream MCP session into the virtual server and call the tool.

    The downstream leg speaks the legacy streamable-HTTP handshake with an
    explicit ``mcp-session-id``, so the gateway routes the upstream call
    through the POOLED UpstreamSessionRegistry path (#4205, keyed on the
    downstream session id).

    NOTE: ``params._meta`` is deliberately omitted from ``tools/call``. The
    migrated streamable HTTP transport crashes on any request that carries
    ``_meta`` — ``streamablehttp_transport.py`` ``call_tool`` does
    ``ctx.meta.model_dump()``, but in mcp 2.0.0b2 ``RequestParamsMeta`` is a
    TypedDict, so SDK-built clients (which always stamp ``"_meta": {}``) get
    ``AttributeError: 'dict' object has no attribute 'model_dump'`` (reported
    as a migration bug). Omitting ``_meta`` is protocol-legal and keeps this
    test focused on the upstream connect-mode path under test.
    """
    url = f"{handle.base_url}/servers/{federation.server_id}/mcp"
    base_headers = {
        **handle.headers,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    async with httpx2.AsyncClient(timeout=httpx2.Timeout(60.0, connect=10.0)) as client:
        # 1. Legacy initialize handshake; capture the downstream session id.
        response = await client.post(
            url,
            headers=base_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": LEGACY_VERSION, "capabilities": {}, "clientInfo": {"name": "e2e-downstream", "version": "0.1"}},
            },
        )
        assert response.status_code == 200, f"downstream initialize failed: {response.status_code} {response.text[:300]}"
        session_id = response.headers.get("mcp-session-id")
        assert session_id, f"gateway issued no mcp-session-id: {dict(response.headers)}"
        negotiated = _read_jsonrpc(response)["result"]["protocolVersion"]
        session_headers = {**base_headers, "mcp-session-id": session_id, "MCP-Protocol-Version": negotiated}

        # 2. Initialized notification.
        response = await client.post(url, headers=session_headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert response.status_code in (200, 202), f"initialized notification failed: {response.status_code} {response.text[:300]}"

        # 3. Discover the federated time tool on this virtual server.
        response = await client.post(url, headers=session_headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        assert response.status_code == 200, f"tools/list failed: {response.status_code} {response.text[:300]}"
        tools = _read_jsonrpc(response)["result"]["tools"]
        tool_name = _time_tool_name([t["name"] for t in tools])

        # 4. Call it through the pooled upstream path (no _meta — see docstring).
        response = await client.post(
            url,
            headers=session_headers,
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": tool_name, "arguments": {}}},
        )
        assert response.status_code == 200, f"tools/call failed: {response.status_code} {response.text[:300]}"
        body = _read_jsonrpc(response)
        assert "result" in body, f"tools/call returned a JSON-RPC error: {body}"
        return body["result"]


def _assert_tool_call_ok(result: Any) -> None:
    """Assert a federated tools/call returned a non-error payload (dict or SDK result)."""
    if isinstance(result, dict):
        assert not result.get("isError"), f"federated tool call returned isError: {result}"
        assert result.get("content"), f"federated tool call returned no content: {result}"
        return
    is_error = getattr(result, "is_error", getattr(result, "isError", False))
    assert not is_error, f"federated tool call returned isError: {result}"
    content = getattr(result, "content", None) or []
    assert content, f"federated tool call returned no content: {result}"


# ---------------------------------------------------------------------------
# Federated tool-call proofs through the POOLED upstream registry path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAutoModeGateway:
    """Default (``MCP_CLIENT_CONNECT_MODE=auto``) federation proofs."""

    async def test_auto_mode_federated_call_legacy_upstream_succeeds(self, gateway_auto: GatewayHandle, gateway_auto_legacy_federation: Federation) -> None:
        """(b) Auto mode against a legacy 2025-11-25 upstream: the
        ``server/discover`` probe errors and the legacy initialize fallback
        keeps the federation path working."""
        result = await _call_federated_time_tool(gateway_auto, gateway_auto_legacy_federation)
        _assert_tool_call_ok(result)


@pytest.mark.asyncio
class TestLegacyModeGateway:
    """Rollback (``MCP_CLIENT_CONNECT_MODE=legacy``) federation proofs."""

    async def test_legacy_mode_federated_call_legacy_upstream_succeeds(self, gateway_legacy: GatewayHandle, gateway_legacy_legacy_federation: Federation) -> None:
        """(c.1) Legacy mode against the legacy upstream succeeds — the
        pre-migration behavior is fully intact under the rollback flag."""
        result = await _call_federated_time_tool(gateway_legacy, gateway_legacy_legacy_federation)
        _assert_tool_call_ok(result)
