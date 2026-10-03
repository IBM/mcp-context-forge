# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_tool_cancellation_metrics_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box check that a cancelled tool call is not recorded as a tool failure.

Starts a private gateway subprocess and registers a REST tool that points at a
local HTTP server. The first upstream request blocks until the test cancels the
``/rpc`` ``tools/call`` with ``notifications/cancelled``. The test asserts the
JSON-RPC -32800 response, an INFO cancellation log, and no recorded execution.
A second call gets HTTP 503 upstream. It proves that a real failure still
records a failed execution and an ERROR log.
"""

# Future
from __future__ import annotations

# Standard
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
from typing import Any, Callable

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.plugins._helpers import create_virtual_server

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]
_TOOL_NAME = "cancellation_metrics_probe"
_CALL_ID = "cancellation-metrics-probe-call"
_UPSTREAM_BLOCK_SECONDS = 30


class _BlockThenFailHandler(BaseHTTPRequestHandler):
    """Block the first request until ``release`` is set, then answer each later request with HTTP 503."""

    requests: list[str] = []
    release = threading.Event()

    def do_GET(self):
        """Record the request, then block (first request) or fail with HTTP 503 (later requests)."""
        self.requests.append(self.path)
        if len(self.requests) == 1:
            self.release.wait(timeout=_UPSTREAM_BLOCK_SECONDS)
            status, body = 200, b'{"late": true}'
        else:
            status, body = 503, b'{"error": "upstream unavailable"}'
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format, *args):
        """Keep the fixture HTTP server quiet."""


@pytest.fixture
def isolated_gateway(tmp_path):
    """Start a private gateway subprocess that writes metrics immediately and logs at INFO.

    Yields:
        A tuple of the gateway base URL, the admin bearer token, and the gateway log path.
    """
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    signing_key = secrets.token_urlsafe(48)
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), *[str(Path(path).resolve()) for path in os.getenv("PYTHONPATH", "").split(os.pathsep) if path]]),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'gateway.db'}",
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
        "SSRF_ALLOW_LOCALHOST": "true",
        "PLUGINS_ENABLED": "false",
        "METRICS_BUFFER_ENABLED": "false",
        "METRICS_CACHE_ENABLED": "false",
        "LOG_LEVEL": "INFO",
        "LOG_FORMAT": "json",
        "PYTHONUNBUFFERED": "1",
    }
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key, algorithm="HS256")
    base_url = f"http://127.0.0.1:{port}"
    log_path = tmp_path / "gateway.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=tmp_path,
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
            yield base_url, token, log_path
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _gateway_client(base_url: str, token: str) -> httpx.Client:
    """Return an authenticated client for the isolated gateway.

    Args:
        base_url: Gateway base URL.
        token: Admin bearer token.

    Returns:
        A new ``httpx.Client``.
    """
    return httpx.Client(base_url=base_url, headers=make_auth_headers(token), timeout=_UPSTREAM_BLOCK_SECONDS + 15, trust_env=False)


def _tool_metrics(client: httpx.Client, *, server_id: str, tool_id: str) -> dict[str, Any]:
    """Read the tool's execution metrics through the virtual server tool listing.

    Args:
        client: Authenticated gateway client.
        server_id: Virtual server that exposes the tool.
        tool_id: Tool to read metrics for.

    Returns:
        The tool's ``metrics`` mapping.
    """
    response = client.get(f"/servers/{server_id}/tools", params={"include_metrics": "true"})
    assert response.status_code == 200, response.text
    tool = next(entry for entry in response.json() if entry["id"] == tool_id)
    metrics: dict[str, Any] = tool["metrics"]
    return metrics


def _tool_log_levels(log_path: Path, message: str) -> list[str]:
    """Return the level of each gateway log record whose message ends with ``message``.

    Args:
        log_path: Gateway log file.
        message: Log message suffix to match.

    Returns:
        The matching records' level names, in log order.
    """
    levels: list[str] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
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


def test_cancelled_tool_call_records_no_failure_but_real_failure_does(isolated_gateway):
    """A cancelled call logs INFO and records no execution; a later real failure records a failed execution."""
    base_url, token, log_path = isolated_gateway
    _BlockThenFailHandler.requests.clear()
    _BlockThenFailHandler.release.clear()
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _BlockThenFailHandler)
    upstream.daemon_threads = True
    worker = threading.Thread(target=upstream.serve_forever, daemon=True)
    worker.start()
    tool_id = None
    server_id = None
    with _gateway_client(base_url, token) as client:
        try:
            response = client.post(
                "/tools",
                json={
                    "tool": {
                        "name": _TOOL_NAME,
                        "description": "Cancellation metrics probe",
                        "integration_type": "REST",
                        "url": f"http://127.0.0.1:{upstream.server_port}/probe",
                        "request_type": "GET",
                        "visibility": "public",
                    },
                    "team_id": None,
                },
            )
            assert response.status_code == 200, response.text
            tool = response.json()
            tool_id = tool["id"]
            server_id = create_virtual_server(client, name=f"{_TOOL_NAME}_server", tool_ids=[tool_id])

            call_responses: list[httpx.Response] = []

            def call_slow_tool() -> None:
                """Send the ``tools/call`` that the test cancels."""
                with _gateway_client(base_url, token) as caller:
                    call_responses.append(
                        caller.post("/rpc", json={"jsonrpc": "2.0", "id": _CALL_ID, "method": "tools/call", "params": {"name": tool["name"], "arguments": {}}}),
                    )

            caller_thread = threading.Thread(target=call_slow_tool, daemon=True)
            caller_thread.start()
            _wait_for(lambda: len(_BlockThenFailHandler.requests) == 1, timeout=30, description="the upstream request")

            cancel = client.post(
                "/rpc",
                json={"jsonrpc": "2.0", "id": "cancellation-metrics-probe-cancel", "method": "notifications/cancelled", "params": {"requestId": _CALL_ID, "reason": "client gave up"}},
            )
            assert cancel.status_code == 200, cancel.text
            caller_thread.join(timeout=_UPSTREAM_BLOCK_SECONDS)
            assert not caller_thread.is_alive(), "the cancelled tools/call did not return"
            _BlockThenFailHandler.release.set()

            cancelled_payload = call_responses[0].json()
            assert cancelled_payload["error"]["code"] == -32800, cancelled_payload
            assert cancelled_payload["error"]["data"]["requestId"] == _CALL_ID
            _wait_for(lambda: _tool_log_levels(log_path, f"Tool '{tool['name']}' invocation cancelled"), timeout=10, description="the cancellation log")
            assert _tool_log_levels(log_path, f"Tool '{tool['name']}' invocation cancelled") == ["INFO"]
            assert not _tool_log_levels(log_path, f"Tool '{tool['name']}' invocation failed")
            cancelled_metrics = _tool_metrics(client, server_id=server_id, tool_id=tool_id)
            assert cancelled_metrics["totalExecutions"] == 0, cancelled_metrics
            assert cancelled_metrics["failedExecutions"] == 0, cancelled_metrics

            failed = client.post("/rpc", json={"jsonrpc": "2.0", "id": "cancellation-metrics-probe-failure", "method": "tools/call", "params": {"name": tool["name"], "arguments": {}}})
            assert failed.status_code == 200, failed.text
            assert failed.json()["result"]["isError"] is True, failed.text
            _wait_for(lambda: _tool_log_levels(log_path, f"Tool '{tool['name']}' invocation failed"), timeout=10, description="the failure log")
            assert _tool_log_levels(log_path, f"Tool '{tool['name']}' invocation failed") == ["ERROR"]
            failed_metrics = _tool_metrics(client, server_id=server_id, tool_id=tool_id)
            assert failed_metrics["totalExecutions"] == 1, failed_metrics
            assert failed_metrics["failedExecutions"] == 1, failed_metrics
        finally:
            _BlockThenFailHandler.release.set()
            try:
                if server_id:
                    client.delete(f"/servers/{server_id}")
                if tool_id:
                    client.delete(f"/tools/{tool_id}")
            finally:
                upstream.shutdown()
                upstream.server_close()
                worker.join(timeout=5)
