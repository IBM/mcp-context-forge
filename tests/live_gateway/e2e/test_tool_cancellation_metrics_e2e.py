# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_tool_cancellation_metrics_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box check that a cancelled tool call is not recorded as a tool failure.

Starts a private gateway subprocess and a local REST upstream. Each test
registers its own REST tool on its own virtual server. The upstream signals
when a request arrives, then blocks until the test releases it, or answers
HTTP 503 on demand. The tests cancel a blocked call on each path that delivers
a cancel to ``invoke_tool`` under MCP Python SDK 2.x:

- ``/rpc`` with ``notifications/cancelled``;
- ``/mcp`` 2026-07-28 SSE (``_meta.progressToken``) with a client disconnect;
- ``/mcp`` 2025-11-25 stateful session with ``notifications/cancelled``.

Each cancellation must log one INFO ``invocation cancelled`` record and record
no failure metric. An upstream 503 must still log ERROR and record one failure.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import contextlib
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Iterator
import uuid

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.plugins._helpers import create_virtual_server

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]
_UPSTREAM_BLOCK_SECONDS = 30
_ARRIVAL_TIMEOUT = 10
_OUTCOME_TIMEOUT = 15
MODERN = "2026-07-28"
LEGACY = "2025-11-25"
MODERN_META = {"io.modelcontextprotocol/protocolVersion": MODERN, "io.modelcontextprotocol/clientCapabilities": {}}


class _ProbeUpstream(BaseHTTPRequestHandler):
    """Signal each request's arrival, then block until ``release`` is set or answer HTTP 503 when ``fail`` is set."""

    arrived = threading.Event()
    release = threading.Event()
    fail = False

    def do_GET(self):
        """Set ``arrived``, then answer HTTP 503 or block until released and answer HTTP 200."""
        self.arrived.set()
        if self.fail:
            status, body = 503, b'{"error": "upstream unavailable"}'
        else:
            self.release.wait(timeout=_UPSTREAM_BLOCK_SECONDS)
            status, body = 200, b'{"late": true}'
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format, *args):
        """Keep the fixture HTTP server quiet."""


@dataclass
class _Gateway:
    """A running isolated gateway and its upstream."""

    base_url: str
    token: str
    log_path: Path
    upstream_url: str


@dataclass
class _Probe:
    """One REST tool on its own virtual server."""

    name: str
    tool_id: str
    server_id: str


def _port() -> int:
    """Reserve an ephemeral loopback port number.

    Returns:
        A free TCP port on 127.0.0.1.
    """
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture(name="gateway", scope="module")
def fixture_gateway(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Gateway]:
    """Start the probe upstream and a private gateway that writes metrics immediately and logs JSON at INFO.

    Yields:
        The running gateway.
    """
    tmp = tmp_path_factory.mktemp("cancellation")
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _ProbeUpstream)
    upstream.daemon_threads = True
    upstream_worker = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_worker.start()
    port = _port()
    signing_key = secrets.token_urlsafe(48)
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), *[str(Path(path).resolve()) for path in os.getenv("PYTHONPATH", "").split(os.pathsep) if path]]),
        "DATABASE_URL": f"sqlite:///{tmp / 'gateway.db'}",
        "CACHE_TYPE": "memory",
        "REDIS_URL": "",
        "JWT_SECRET_KEY": signing_key,
        "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
        "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32),
        "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
        "PLATFORM_ADMIN_EMAIL": "admin@example.com",
        "AUTH_REQUIRED": "true",
        "REQUIRE_USER_IN_DB": "false",
        "MCPGATEWAY_ADMIN_API_ENABLED": "true",
        "MCPGATEWAY_UI_ENABLED": "false",
        "MCPGATEWAY_A2A_ENABLED": "false",
        "MCPGATEWAY_TOOL_CANCELLATION_ENABLED": "true",
        "USE_STATEFUL_SESSIONS": "true",
        "SSRF_ALLOW_LOCALHOST": "true",
        "PLUGINS_ENABLED": "false",
        "METRICS_BUFFER_ENABLED": "false",
        "METRICS_CACHE_ENABLED": "false",
        "FILELOCK_NAME": f"cancellation-{uuid.uuid4().hex}.lock",
        "PRIMARY_WORKER_LOCK_PATH": str(tmp / "primary.lock"),
        "LOG_LEVEL": "INFO",
        "LOG_FORMAT": "json",
        "PYTHONUNBUFFERED": "1",
    }
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key, algorithm="HS256")
    base_url = f"http://127.0.0.1:{port}"
    log_path = tmp / "gateway.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=tmp,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            with _gateway_client(base_url, token) as client:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text(encoding="utf-8")[-5000:]
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail(f"Gateway startup timed out: {log_path.read_text(encoding='utf-8')[-5000:]}")
            yield _Gateway(base_url=base_url, token=token, log_path=log_path, upstream_url=f"http://127.0.0.1:{upstream.server_port}/probe")
        finally:
            _ProbeUpstream.release.set()
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            upstream.shutdown()
            upstream.server_close()
            upstream_worker.join(timeout=5)


@pytest.fixture(name="probe")
def fixture_probe(gateway: _Gateway) -> Iterator[_Probe]:
    """Reset the upstream and register a fresh REST tool on its own virtual server.

    Yields:
        The tool and its virtual server.
    """
    _ProbeUpstream.arrived.clear()
    _ProbeUpstream.release.clear()
    _ProbeUpstream.fail = False
    name = f"cancellation_probe_{uuid.uuid4().hex[:8]}"
    with _gateway_client(gateway.base_url, gateway.token) as client:
        response = client.post(
            "/tools",
            json={
                "tool": {"name": name, "description": "Cancellation metrics probe", "integration_type": "REST", "url": gateway.upstream_url, "request_type": "GET", "visibility": "public"},
                "team_id": None,
            },
        )
        assert response.status_code == 200, response.text
        tool = response.json()
        server_id = None
        try:
            server_id = create_virtual_server(client, name=f"{name}_server", tool_ids=[tool["id"]])
            yield _Probe(name=tool["name"], tool_id=tool["id"], server_id=server_id)
        finally:
            _ProbeUpstream.release.set()
            if server_id:
                client.delete(f"/servers/{server_id}")
            client.delete(f"/tools/{tool['id']}")


def _gateway_client(base_url: str, token: str) -> httpx.Client:
    """Return an authenticated client for the isolated gateway.

    Args:
        base_url: Gateway base URL.
        token: Admin bearer token.

    Returns:
        A new ``httpx.Client``.
    """
    return httpx.Client(base_url=base_url, headers=make_auth_headers(token), timeout=_UPSTREAM_BLOCK_SECONDS + 15, trust_env=False)


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
    """Build a modern JSON-RPC request carrying the ``_meta`` envelope.

    Args:
        method: JSON-RPC method.
        params: Request params without ``_meta``.
        request_id: JSON-RPC id.

    Returns:
        The JSON-RPC request body.
    """
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": {**(params or {}), "_meta": MODERN_META}}


def _tool_metrics(client: httpx.Client, probe: _Probe) -> dict[str, Any]:
    """Read the tool's execution metrics through the virtual server tool listing.

    Args:
        client: Authenticated gateway client.
        probe: Tool and virtual server to read.

    Returns:
        The tool's ``metrics`` mapping.
    """
    response = client.get(f"/servers/{probe.server_id}/tools", params={"include_metrics": "true"})
    assert response.status_code == 200, response.text
    tool = next(entry for entry in response.json() if entry["id"] == probe.tool_id)
    metrics: dict[str, Any] = tool["metrics"]
    return metrics


def _log_offset(log_path: Path) -> int:
    """Return the current end of the gateway log, so a test reads only the records it produced.

    Args:
        log_path: Gateway log file.

    Returns:
        The log size in bytes.
    """
    return log_path.stat().st_size


def _tool_log_levels(log_path: Path, offset: int, message: str) -> list[str]:
    """Return the level of each gateway log record after ``offset`` whose message ends with ``message``.

    Args:
        log_path: Gateway log file.
        offset: Byte offset to read from.
        message: Log message suffix to match.

    Returns:
        The matching records' level names, in log order.
    """
    with log_path.open("rb") as log_file:
        log_file.seek(offset)
        text = log_file.read().decode("utf-8", errors="replace")
    levels: list[str] = []
    for line in text.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and str(record.get("message", "")).endswith(message):
            levels.append(str(record.get("levelname") or record.get("level")))
    return levels


def _wait_for(predicate: Callable[[], object], *, timeout: float, description: str) -> None:
    """Poll ``predicate`` until it returns true or ``timeout`` seconds pass.

    Args:
        predicate: Zero-argument callable to poll.
        timeout: Deadline in seconds.
        description: Condition name for the failure message.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    pytest.fail(f"Timed out waiting for {description}")


def _wait_for_arrival() -> None:
    """Fail unless the upstream request arrives, which proves ``invoke_tool`` is awaiting the upstream."""
    assert _ProbeUpstream.arrived.wait(timeout=_ARRIVAL_TIMEOUT), "the tool call did not reach the upstream"


def _assert_cancellation_recorded(gateway: _Gateway, probe: _Probe, offset: int) -> dict[str, Any]:
    """Assert one INFO cancellation record, no failure record and no failure metric for the probe tool.

    The upstream stays blocked until the call outcome is logged. A client
    disconnect reaches the gateway asynchronously, so an earlier release lets the
    upstream answer before the cancel lands.

    Args:
        gateway: Running gateway.
        probe: Cancelled tool.
        offset: Log offset taken before the call.

    Returns:
        The tool's ``metrics`` mapping.
    """
    cancelled = f"Tool '{probe.name}' invocation cancelled"
    failed = f"Tool '{probe.name}' invocation failed"
    _wait_for(lambda: _tool_log_levels(gateway.log_path, offset, cancelled) or _tool_log_levels(gateway.log_path, offset, failed), timeout=_OUTCOME_TIMEOUT, description="the call outcome log")
    _ProbeUpstream.release.set()
    assert not _tool_log_levels(gateway.log_path, offset, failed)
    assert _tool_log_levels(gateway.log_path, offset, cancelled) == ["INFO"]
    with _gateway_client(gateway.base_url, gateway.token) as client:
        metrics = _tool_metrics(client, probe)
    assert metrics["failedExecutions"] == 0, metrics
    return metrics


def test_rpc_cancel_records_cancellation(gateway: _Gateway, probe: _Probe):
    """A ``/rpc`` ``tools/call`` cancelled by ``notifications/cancelled`` answers -32800, logs INFO and records no execution."""
    offset = _log_offset(gateway.log_path)
    call_responses: list[httpx.Response] = []

    def call_slow_tool() -> None:
        """Send the ``tools/call`` that the test cancels."""
        with _gateway_client(gateway.base_url, gateway.token) as caller:
            call_responses.append(caller.post("/rpc", json={"jsonrpc": "2.0", "id": "r1", "method": "tools/call", "params": {"name": probe.name, "arguments": {}}}))

    caller_thread = threading.Thread(target=call_slow_tool, daemon=True)
    caller_thread.start()
    _wait_for_arrival()
    with _gateway_client(gateway.base_url, gateway.token) as client:
        cancel = client.post("/rpc", json={"jsonrpc": "2.0", "id": "r1-cancel", "method": "notifications/cancelled", "params": {"requestId": "r1", "reason": "client gave up"}})
    assert cancel.status_code == 200, cancel.text
    caller_thread.join(timeout=_UPSTREAM_BLOCK_SECONDS)
    assert not caller_thread.is_alive(), "the cancelled tools/call did not return"

    cancelled_payload = call_responses[0].json()
    assert cancelled_payload["error"]["code"] == -32800, cancelled_payload
    metrics = _assert_cancellation_recorded(gateway, probe, offset)
    assert metrics["totalExecutions"] == 0, metrics


async def _stream_until_arrival(url: str, headers: dict[str, str], body: dict[str, Any]) -> None:
    """Open a streamed POST, then close the stream and client once the upstream request arrives.

    The SDK defers SSE response headers, so the stream opens in a task that the
    arrival cancels. Cancelling it closes the connection, which the gateway sees
    as a client disconnect.

    Args:
        url: Streamable HTTP endpoint.
        headers: Request headers.
        body: JSON-RPC request body.
    """

    async with httpx.AsyncClient(timeout=_UPSTREAM_BLOCK_SECONDS + 15, trust_env=False) as client:

        async def hold_stream() -> httpx.Response:
            """Read the streamed response until cancelled."""
            async with client.stream("POST", url, headers=headers, json=body) as response:
                await response.aread()
                return response

        stream_task = asyncio.create_task(hold_stream())
        arrival = asyncio.create_task(asyncio.to_thread(_ProbeUpstream.arrived.wait, _ARRIVAL_TIMEOUT))
        await asyncio.wait({stream_task, arrival}, return_when=asyncio.FIRST_COMPLETED)
        assert not stream_task.done(), f"the stream ended before the upstream request arrived: {stream_task.result().text}"
        assert await arrival, "the tool call did not reach the upstream"
        stream_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stream_task


def test_mcp_2026_sse_disconnect_records_cancellation(gateway: _Gateway, probe: _Probe):
    """A 2026-07-28 ``/mcp`` SSE ``tools/call`` whose client disconnects logs INFO and records no failure."""
    offset = _log_offset(gateway.log_path)
    headers = {**_headers(gateway.token, "tools/call"), "Mcp-Name": probe.name}
    body = _request("tools/call", {"name": probe.name, "arguments": {}})
    body["params"]["_meta"] = {**MODERN_META, "progressToken": "p1"}

    asyncio.run(_stream_until_arrival(f"{gateway.base_url}/servers/{probe.server_id}/mcp/", headers, body))
    _assert_cancellation_recorded(gateway, probe, offset)


def test_mcp_2025_stateful_notifications_cancelled_records_cancellation(gateway: _Gateway, probe: _Probe):
    """A 2025-11-25 stateful ``/mcp`` ``tools/call`` cancelled by ``notifications/cancelled`` answers -32800, logs INFO and records no failure."""
    offset = _log_offset(gateway.log_path)
    url = f"/servers/{probe.server_id}/mcp/"
    with _gateway_client(gateway.base_url, gateway.token) as client:
        initialize = client.post(
            url,
            headers=_headers(gateway.token, None, None),
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": LEGACY, "capabilities": {}, "clientInfo": {"name": "cancellation-probe", "version": "1"}}},
        )
        assert initialize.status_code == 200, initialize.text
        session_headers = {**_headers(gateway.token, None, LEGACY), "Mcp-Session-Id": initialize.headers["mcp-session-id"]}
        initialized = client.post(url, headers=session_headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert initialized.status_code == 202, initialized.text

        call_responses: list[httpx.Response] = []

        def call_slow_tool() -> None:
            """Send the ``tools/call`` that the test cancels."""
            with _gateway_client(gateway.base_url, gateway.token) as caller:
                call_responses.append(caller.post(url, headers=session_headers, json={"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": probe.name, "arguments": {}}}))

        caller_thread = threading.Thread(target=call_slow_tool, daemon=True)
        caller_thread.start()
        _wait_for_arrival()
        cancel = client.post(url, headers=session_headers, json={"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 7}})
        assert cancel.status_code == 202, cancel.text
        caller_thread.join(timeout=_UPSTREAM_BLOCK_SECONDS)
        assert not caller_thread.is_alive(), "the cancelled tools/call did not return"

    cancelled_payload = call_responses[0].json()
    assert cancelled_payload["error"]["code"] == -32800, cancelled_payload
    _assert_cancellation_recorded(gateway, probe, offset)


def test_rpc_upstream_503_records_failure(gateway: _Gateway, probe: _Probe):
    """A ``/rpc`` ``tools/call`` whose upstream answers HTTP 503 logs ERROR and records one failed execution."""
    offset = _log_offset(gateway.log_path)
    _ProbeUpstream.fail = True
    with _gateway_client(gateway.base_url, gateway.token) as client:
        failed = client.post("/rpc", json={"jsonrpc": "2.0", "id": "r4", "method": "tools/call", "params": {"name": probe.name, "arguments": {}}})
        _wait_for_arrival()
        assert failed.status_code == 200, failed.text
        assert failed.json()["result"]["isError"] is True, failed.text
        failure = f"Tool '{probe.name}' invocation failed"
        _wait_for(lambda: _tool_log_levels(gateway.log_path, offset, failure), timeout=_OUTCOME_TIMEOUT, description="the failure log")
        assert _tool_log_levels(gateway.log_path, offset, failure) == ["ERROR"]
        metrics = _tool_metrics(client, probe)
    assert metrics["totalExecutions"] == 1, metrics
    assert metrics["failedExecutions"] == 1, metrics
