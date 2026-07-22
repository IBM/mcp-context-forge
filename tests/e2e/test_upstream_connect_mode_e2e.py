# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_upstream_connect_mode_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

E2E proofs for the migrated upstream federation connect path
(``MCP_CLIENT_CONNECT_MODE``, ``mcpgateway/services/upstream_session_registry.py``
+ ``mcpgateway/utils/mcp_proxy_client.py`` on ``mcp==2.0.0b2``).

Two live upstreams from the docker-compose ``testing`` profile are required
(probed at module setup; the whole module skips with a readable reason when
they are unreachable):

- ``fast_time_2026_server`` (strict modern-era) at ``E2E_STRICT_UPSTREAM_URL``
  (default ``http://localhost:8887/mcp``)
- ``fast_time_server`` (legacy) at ``E2E_LEGACY_UPSTREAM_URL``
  (default ``http://localhost:8888/mcp``)

The gateways under test are launched from the worktree source as real uvicorn
subprocesses (own sqlite DB, own JWT secret, SSRF localhost allowances) — the
compose stack's gateway containers are intentionally NOT used.

Strict-server behavior matrix (locked empirically via curl, 2026-07-22;
image ``cfex-mcp-fast-time-server`` — STRICT modern-only, the legacy
handshake path is fully removed. The interop gaps originally found here
were fixed upstream; see
https://github.com/IBM/contextforge-examples/issues/11):

- ``/version`` reports ``mcp_versions: ["2026-07-28"]`` only, ``strict: true``.
- ``initialize`` proposing ANY version (``2025-11-25``, ``2026-07-28``,
  ``2025-06-18``) -> JSON-RPC ``-32602`` "Unsupported protocol version"
  (``supported: ["2026-07-28"]``). Modern mode is handshake-less.
- ``server/discover`` with the SEP-2575 namespaced ``_meta`` envelope
  (``io.modelcontextprotocol/protocolVersion`` etc.) -> HTTP 200
  DiscoverResult with ``supportedVersions: ["2026-07-28"]``, ``serverInfo``
  in the spec-canonical ``_meta.io.modelcontextprotocol/serverInfo`` slot
  (plus a top-level copy for mcp_types SDK interop), and the
  ``cacheScope: "private"`` / ``ttlMs: 0`` directives the 2026-07-28 wire
  requires — stateless, no session required.
- Legacy upstream (8888): unchanged — ``server/discover`` errors, legacy
  ``initialize`` at 2025-11-25 is accepted, calls succeed in both connect
  modes.

Empirical outcome of the negotiation modes against these upstreams
(mcp 2.0.0b2, verified by wire capture):

- ``auto`` vs strict: SUCCEEDS. The ``server/discover`` probe returns a
  valid DiscoverResult, the SDK adopts 2026-07-28, and federated tool
  calls through the pooled registry path work end-to-end — the headline
  proof of the ``mcp.client.Client`` migration.
- ``auto`` vs legacy: ``server/discover`` errors, legacy fallback by
  design; the federated call succeeds.
- ``legacy`` vs legacy: succeeds — the pre-migration behavior is fully
  intact under the rollback flag.
- ``legacy`` vs strict: FAILS, and this failure IS the correct end state
  for the rollback mode against a modern-only upstream: legacy mode
  proposes exactly ``2025-11-25`` in ``initialize`` and never sends
  ``server/discover``, so the modern-only image rejects the handshake with
  ``-32602``, surfaced by the gateway as HTTP 502 at registration.
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
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
import pytest

# First-Party
from tests.helpers.auth import make_auth_headers, make_legacy_test_jwt

pytestmark = pytest.mark.e2e

TEST_JWT_SECRET = "e2e-upstream-connect-mode-jwt-secret-32bytes"  # pragma: allowlist secret
TEST_JWT_ALGORITHM = "HS256"
TEST_ADMIN_EMAIL = "admin@example.com"

STRICT_UPSTREAM_URL = os.environ.get("E2E_STRICT_UPSTREAM_URL", "http://localhost:8887/mcp")
LEGACY_UPSTREAM_URL = os.environ.get("E2E_LEGACY_UPSTREAM_URL", "http://localhost:8888/mcp")

GATEWAY_STARTUP_DEADLINE_SECONDS = 120.0
TOOL_SYNC_DEADLINE_SECONDS = 90.0
POLL_INTERVAL_SECONDS = 0.5

MODERN_VERSION = "2026-07-28"
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
    """Skip the whole module unless both compose upstreams are reachable."""
    for label, mcp_url in (("strict 2026-07-28", STRICT_UPSTREAM_URL), ("legacy", LEGACY_UPSTREAM_URL)):
        health = _health_url(mcp_url)
        try:
            response = httpx.get(health, timeout=3.0)
            reachable = response.status_code == 200
        except httpx.HTTPError:
            reachable = False
        if not reachable:
            pytest.skip(
                f"docker-compose testing upstream ({label}) not reachable at {health} — "
                "start the 'testing' compose profile or point "
                f"{'E2E_STRICT_UPSTREAM_URL' if label.startswith('strict') else 'E2E_LEGACY_UPSTREAM_URL'} at a live server",
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
        "AUTH_ENCRYPTION_SECRET": "e2e-upstream-connect-mode-salt",  # pragma: allowlist secret
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
    """Federate the legacy upstream through the auto-mode gateway (module-scoped).

    The strict upstream is deliberately NOT registered here: with the
    modern-only image (sha256:2f085782) registration fails with HTTP 502, so
    strict-upstream scenarios register inside the test body instead.
    """
    return _register_upstream(gateway_auto, LEGACY_UPSTREAM_URL, f"e2e-legacy-{uuid.uuid4().hex[:8]}")


@pytest.fixture(scope="module")
def gateway_legacy_legacy_federation(gateway_legacy: GatewayHandle) -> Federation:
    """Federate the legacy upstream through the legacy-mode gateway (module-scoped).

    See ``gateway_auto_legacy_federation`` for why the strict upstream is
    not registered at fixture scope.
    """
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
# Strict-server behavior matrix (curl-locked facts as executable assertions)
# ---------------------------------------------------------------------------


class TestStrictServerBehaviorMatrix:
    """Raw probes against the strict upstream pinning the negotiation contract."""

    def _initialize(self, version: str) -> httpx.Response:
        return httpx.post(
            STRICT_UPSTREAM_URL,
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "e2e-matrix", "version": "0.1"}}},
            timeout=10.0,
        )

    def test_initialize_rejected_for_every_version(self) -> None:
        """Strict upstream (modern-only, sha256:2f085782) rejects ``initialize``
        for EVERY proposed version — legacy 2025-11-25, modern 2026-07-28
        (modern mode is handshake-less), and older 2025-06-18 alike."""
        for version in (LEGACY_VERSION, MODERN_VERSION, "2025-06-18"):
            body = self._initialize(version).json()
            assert body["error"]["code"] == -32602, f"initialize at {version} must be rejected: {body}"
            assert body["error"]["data"]["requested"] == version
            assert body["error"]["data"]["supported"] == [MODERN_VERSION]

    def test_initialize_rejects_2026_07_28(self) -> None:
        """Strict upstream rejects initialize even at the modern version (handshake-less era)."""
        body = self._initialize(MODERN_VERSION).json()
        assert body["error"]["code"] == -32602
        assert body["error"]["data"]["supported"] == [MODERN_VERSION]

    def test_initialize_rejects_2025_06_18(self) -> None:
        """Strict upstream rejects older handshake versions (no fallback negotiation)."""
        body = self._initialize("2025-06-18").json()
        assert body["error"]["code"] == -32602
        assert body["error"]["data"]["supported"] == [MODERN_VERSION]

    def test_server_discover_stateless_modern(self) -> None:
        """Strict upstream answers a namespaced server/discover statelessly at 2026-07-28."""
        response = httpx.post(
            STRICT_UPSTREAM_URL,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": MODERN_VERSION,
                "MCP-Method": "server/discover",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "server/discover",
                "params": {
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": MODERN_VERSION,
                        "io.modelcontextprotocol/clientInfo": {"name": "e2e-matrix", "version": "0.1"},
                        "io.modelcontextprotocol/clientCapabilities": {},
                    }
                },
            },
            timeout=10.0,
        )
        assert response.status_code == 200
        result = response.json()["result"]
        assert result["supportedVersions"] == [MODERN_VERSION]
        # Spec-canonical shape (draft spec schema/draft/schema.ts): serverInfo
        # lives in the namespaced _meta envelope. The fixed image ALSO emits a
        # top-level serverInfo for mcp_types (SDK 2.0.0b2) interop, and the
        # required 2026-07-28 cache directives.
        assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "fast-time-server"
        assert result["serverInfo"]["name"] == "fast-time-server"  # SDK-interop copy (issue #11)
        assert result["cacheScope"] == "private"
        assert result["ttlMs"] == 0


# ---------------------------------------------------------------------------
# Federated tool-call proofs through the POOLED upstream registry path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAutoModeGateway:
    """Default (``MCP_CLIENT_CONNECT_MODE=auto``) federation proofs."""

    async def test_auto_mode_federated_call_strict_upstream_succeeds(self, gateway_auto: GatewayHandle) -> None:
        """(a) HEADLINE proof: a tool call federated through the POOLED
        registry path to the strict 2026-07-28 upstream SUCCEEDS in default
        auto mode, negotiated at the modern version.

        (Was xfail(strict=True) pending the contextforge-examples#11 image
        fix; it XPASSed when the fixed image landed.)
        """
        federation = _register_upstream(gateway_auto, STRICT_UPSTREAM_URL, f"e2e-strict-auto-{uuid.uuid4().hex[:8]}")
        result = await _call_federated_time_tool(gateway_auto, federation)
        _assert_tool_call_ok(result)

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

    async def test_legacy_mode_registration_strict_upstream_fails_unsupported_version(self, gateway_legacy: GatewayHandle) -> None:
        """(c.2) Legacy mode against the STRICT upstream — REAL behavior.

        Legacy mode proposes exactly ``2025-11-25`` in ``initialize`` and
        never probes ``server/discover``; the modern-only strict image
        (sha256:2f085782) rejects every handshake version with ``-32602``.
        The gateway surfaces this at registration time as HTTP 502 with an
        "Unsupported protocol version" message.

        This is asserted as the PERMANENT contract (not an issue #11 xfail):
        the rollback mode speaks only the legacy handshake, so failing to
        federate a modern-only upstream is the correct end state for legacy
        mode — there is no fixed image under which this registration should
        start succeeding.
        """
        with httpx.Client(base_url=gateway_legacy.base_url, headers=gateway_legacy.headers, timeout=30.0) as client:
            response = client.post(
                "/gateways",
                json={"name": f"e2e-strict-legacy-{uuid.uuid4().hex[:8]}", "url": STRICT_UPSTREAM_URL, "transport": "STREAMABLEHTTP"},
            )
        assert response.status_code == 502, f"strict-upstream registration in legacy mode must fail with 502: {response.status_code} {response.text[:300]}"
        assert "Unsupported protocol version" in response.json()["message"]


# ---------------------------------------------------------------------------
# Wire-level negotiation proofs (direct SDK client, recorded HTTP frames)
# ---------------------------------------------------------------------------


class _WireRecorder:
    """httpx2 event hooks recording (request, response) JSON-RPC frames."""

    def __init__(self) -> None:
        self.frames: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self._pending_request_body: str = ""

    def factory(self, headers: dict[str, str] | None = None) -> httpx2.AsyncClient:
        async def on_request(request: httpx2.Request) -> None:
            self._pending_request_body = request.content.decode(errors="replace") if request.content else ""

        async def on_response(response: httpx2.Response) -> None:
            await response.aread()
            try:
                req = json.loads(self._pending_request_body) if self._pending_request_body else {}
            except ValueError:
                req = {"_raw": self._pending_request_body[:200]}
            try:
                res = json.loads(response.text) if response.text else {}
            except ValueError:
                res = {"_status": response.status_code, "_raw": response.text[:200]}
            self.frames.append((req, res))

        return httpx2.AsyncClient(
            headers=headers or {},
            timeout=httpx2.Timeout(30.0, connect=10.0),
            event_hooks={"request": [on_request], "response": [on_response]},
        )

    def request_methods(self) -> list[str]:
        return [req.get("method", "") for req, _ in self.frames]


@pytest.mark.asyncio
class TestWireLevelNegotiation:
    """Direct SDK-client wire captures against the strict upstream, proving
    exactly how each connect mode negotiates — the observable rollback proof."""

    async def test_auto_mode_probes_server_discover_first(self) -> None:
        """Auto mode's first frame to the strict upstream is a ``server/discover``
        probe stamped at 2026-07-28 — the modern negotiation path is exercised
        and (post issue #11) completes successfully."""
        recorder = _WireRecorder()
        async with recorder.factory() as http_client:
            async with Client(streamable_http_client(STRICT_UPSTREAM_URL, http_client=http_client), mode="auto"):
                pass
        methods = recorder.request_methods()
        assert methods, "no frames recorded"
        assert methods[0] == "server/discover", f"auto mode must probe server/discover first, got {methods}"
        discover_request = recorder.frames[0][0]
        assert discover_request["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] == MODERN_VERSION
        discover_response = recorder.frames[0][1]
        assert "result" in discover_response, f"strict server must answer the probe, got {discover_response}"

    async def test_legacy_mode_never_probes_server_discover(self) -> None:
        """Legacy mode sends NO ``server/discover`` frame; its first and only
        handshake is ``initialize`` proposing exactly 2025-11-25 — the
        observable rollback proof for ``MCP_CLIENT_CONNECT_MODE=legacy``.

        Against the modern-only strict image (sha256:2f085782) that handshake
        is now rejected with ``-32602`` (``supported: ["2026-07-28"]``); the
        client session is expected to raise. The rollback proof — no modern
        probe is ever attempted — holds regardless.
        """
        recorder = _WireRecorder()
        async with recorder.factory() as http_client:
            try:
                async with Client(streamable_http_client(STRICT_UPSTREAM_URL, http_client=http_client), mode="legacy") as client:
                    await client.call_tool("get_system_time", {})
            except Exception:  # noqa: BLE001 — the strict image rejects the legacy handshake; frames are what matter
                pass
        methods = recorder.request_methods()
        assert "server/discover" not in methods, f"legacy mode must never probe server/discover, got {methods}"
        assert methods[0] == "initialize", f"legacy mode must initialize first, got {methods}"
        initialize_request = recorder.frames[0][0]
        assert initialize_request["params"]["protocolVersion"] == LEGACY_VERSION
        initialize_response = recorder.frames[0][1]
        assert initialize_response["error"]["code"] == -32602, f"modern-only strict image must reject the legacy handshake, got {initialize_response}"
        assert initialize_response["error"]["data"]["supported"] == [MODERN_VERSION]

    async def test_auto_mode_negotiates_modern_version_with_strict_upstream(self) -> None:
        """Auto mode adopts 2026-07-28 with the strict upstream
        (``discover_result`` set, no legacy initialize fallback) — the shipped
        behavior since the contextforge-examples#11 image fix."""
        recorder = _WireRecorder()
        async with recorder.factory() as http_client:
            async with Client(streamable_http_client(STRICT_UPSTREAM_URL, http_client=http_client), mode="auto") as client:
                session = client.session
                assert session.discover_result is not None, "auto mode fell back to legacy initialize — modern negotiation did not complete"
                assert session.protocol_version == MODERN_VERSION
