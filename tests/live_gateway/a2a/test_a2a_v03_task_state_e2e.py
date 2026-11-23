# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_v03_task_state_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box check of the task-state wire format sent to an A2A v0.3 agent.

The gateway runs as a subprocess with a private SQLite DB. A local capture
server acts as a v0.3 JSON-RPC agent. The test invokes the agent through the
gateway with v1 task states and reads the JSON-RPC body that the agent receives.
No existing gateway, Redis instance, or credentials are used.
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
AGENT_NAME = "v03-task-state-e2e-agent"


class BodyCaptureHandler(BaseHTTPRequestHandler):
    """Record inbound JSON-RPC bodies and return a minimal JSON-RPC result."""

    captured = []

    def do_POST(self):
        """Capture the request body and answer 200 with a JSON-RPC result."""
        length = int(self.headers.get("Content-Length") or 0)
        request = json.loads(self.rfile.read(length) or b"{}")
        type(self).captured.append(request)
        body = json.dumps({"jsonrpc": "2.0", "id": request.get("id", 1), "result": {"kind": "message", "messageId": "reply-1", "role": "agent", "parts": [{"kind": "text", "text": "ok"}]}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Keep the capture server quiet."""


def _free_port():
    """Return an ephemeral loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.fixture(scope="module")
def v03_agent_gateway(tmp_path_factory):
    """Start an authenticated gateway with a registered v0.3 JSON-RPC agent."""
    tmp_path = tmp_path_factory.mktemp("a2a-v03-state-gateway")

    BodyCaptureHandler.captured = []
    capture_server = ThreadingHTTPServer(("127.0.0.1", 0), BodyCaptureHandler)
    capture_worker = threading.Thread(target=capture_server.serve_forever, daemon=True)
    capture_worker.start()

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
        "PLUGINS_ENABLED": "false",
        "OBSERVABILITY_ENABLED": "false",
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
                            "description": "Body-capture agent for v0.3 task-state tests",
                            "endpoint_url": f"http://127.0.0.1:{capture_server.server_port}/invoke",
                            "agent_type": "jsonrpc",
                            "protocol_version": "0.3.0",
                        },
                        "visibility": "public",
                    },
                )
                assert response.status_code in (200, 201), response.text

                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            capture_server.shutdown()
            capture_server.server_close()
            capture_worker.join(timeout=5)


@pytest.mark.parametrize(
    ("v1_state", "v03_state"),
    [("TASK_STATE_INPUT_REQUIRED", "input-required"), ("TASK_STATE_AUTH_REQUIRED", "auth-required")],
)
def test_v03_agent_receives_hyphenated_task_state(v03_agent_gateway, v1_state, v03_state):
    """The v0.3 agent receives the hyphenated wire value for a v1 task state."""
    client = v03_agent_gateway
    BodyCaptureHandler.captured.clear()

    response = client.post(
        f"/a2a/{AGENT_NAME}/invoke",
        json={
            "parameters": {
                "method": "message/send",
                "params": {
                    "message": {"messageId": "state-e2e-1", "role": "ROLE_USER", "parts": [{"text": "state check"}]},
                    "task": {"id": "task-1", "status": {"state": v1_state}},
                    "status": {"state": v1_state},
                },
            }
        },
    )
    assert response.status_code == 200, response.text

    assert len(BodyCaptureHandler.captured) == 1
    params = BodyCaptureHandler.captured[0]["params"]
    assert params["task"]["status"]["state"] == v03_state
    assert params["status"]["state"] == v03_state
