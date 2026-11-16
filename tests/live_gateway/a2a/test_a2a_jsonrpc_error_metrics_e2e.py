# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_jsonrpc_error_metrics_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box check that a JSON-RPC error over HTTP 200 is counted as a failed A2A
invocation. The gateway runs as a subprocess with a private SQLite database and
a local stub agent; no existing gateway, Redis instance, or credentials are
used.
"""

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

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_NAME = "jsonrpc-error-e2e-agent"
ERROR_BODY = {"jsonrpc": "2.0", "id": "req-1", "error": {"code": -32000, "message": "agent rejected the task"}}


class ErrorAgentHandler(BaseHTTPRequestHandler):
    """Answer every invocation with a JSON-RPC error over HTTP 200."""

    def do_POST(self):
        """Return the fixed JSON-RPC error envelope."""
        body = json.dumps(ERROR_BODY).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Keep the stub server quiet."""


def _free_port():
    """Return an ephemeral loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.fixture(scope="module")
def isolated_a2a_gateway(tmp_path_factory):
    """Start a gateway and register an agent that returns a JSON-RPC error."""
    tmp_path = tmp_path_factory.mktemp("a2a-jsonrpc-error-gateway")
    agent_server = ThreadingHTTPServer(("127.0.0.1", 0), ErrorAgentHandler)
    agent_worker = threading.Thread(target=agent_server.serve_forever, daemon=True)
    agent_worker.start()

    gateway_port = _free_port()
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
        "MCPGATEWAY_A2A_ENABLED": "true",
        "SSRF_ALLOW_LOCALHOST": "true",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
        "PLUGINS_ENABLED": "false",
        "METRICS_BUFFER_FLUSH_INTERVAL": "5",
        "METRICS_CACHE_ENABLED": "false",
        "LOG_LEVEL": "ERROR",
        "PYTHONUNBUFFERED": "1",
    }
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key, algorithm="HS256")
    log_path = tmp_path / "gateway.log"
    with log_path.open("w") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(gateway_port)],
            cwd=tmp_path,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{gateway_port}", headers=make_auth_headers(token), timeout=15, trust_env=False) as client:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text()[-5000:]
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail(f"Gateway startup timed out: {log_path.read_text()[-5000:]}")

                response = client.post(
                    "/a2a",
                    json={
                        "agent": {
                            "name": AGENT_NAME,
                            "description": "JSON-RPC error agent for metrics tests",
                            "endpoint_url": f"http://127.0.0.1:{agent_server.server_port}/invoke",
                            "agent_type": "generic",
                        },
                        "visibility": "public",
                    },
                )
                assert response.status_code in (200, 201), response.text
                registered = response.json()
                assert registered.get("endpointUrl") == f"http://127.0.0.1:{agent_server.server_port}/invoke", registered

                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            agent_server.shutdown()
            agent_server.server_close()
            agent_worker.join(timeout=5)


def test_jsonrpc_error_is_counted_as_failed_invocation(isolated_a2a_gateway):
    """The caller sees the envelope, and the aggregate metric records a failure."""
    client = isolated_a2a_gateway

    response = client.post(f"/a2a/{AGENT_NAME}/invoke", json={"parameters": {"prompt": "fail"}})
    assert response.status_code == 200, response.text
    assert response.json() == ERROR_BODY

    deadline = time.monotonic() + 20
    a2a_metrics = {}
    while time.monotonic() < deadline:
        data = client.get("/metrics").json()
        a2a_metrics = data.get("a2aAgents") or {}
        if a2a_metrics.get("totalInteractions", 0) >= 1:
            break
        time.sleep(0.5)
    else:
        pytest.fail(f"A2A metric was not flushed: {a2a_metrics!r}")

    assert a2a_metrics["successfulInteractions"] == 0
    assert a2a_metrics["failedInteractions"] == 1
    assert a2a_metrics["successRate"] == 0.0
