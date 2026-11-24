# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_protocol_binding_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box check that a stored A2A ``protocol_binding`` decides the wire body (#7383).

Starts an isolated gateway subprocess on a private SQLite DB and registers
agents whose endpoints end in ``/`` against a local stub. The stub records the
raw request bodies it receives. No existing gateway, Redis or credentials are used.
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

HTTP_JSON_AGENT = "binding-http-json-agent"
LEGACY_AGENT = "binding-legacy-agent"


class BodyCaptureHandler(BaseHTTPRequestHandler):
    """Record inbound POST bodies keyed by path and return a minimal JSON response."""

    captured = []

    def do_POST(self):
        """Capture the JSON body and answer 200."""
        length = int(self.headers.get("Content-Length") or 0)
        type(self).captured.append((self.path, json.loads(self.rfile.read(length) or b"{}")))
        body = b'{"response": "ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Keep the stub quiet."""


def _free_port():
    """Return an ephemeral loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.fixture(scope="module")
def isolated_gateway(tmp_path_factory):
    """Start an authenticated gateway and register two trailing-slash agents against the stub."""
    tmp_path = tmp_path_factory.mktemp("a2a-binding-gateway")

    BodyCaptureHandler.captured = []
    stub = ThreadingHTTPServer(("127.0.0.1", 0), BodyCaptureHandler)
    stub_worker = threading.Thread(target=stub.serve_forever, daemon=True)
    stub_worker.start()

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

                base = f"http://127.0.0.1:{stub.server_port}"
                for name, extra in ((HTTP_JSON_AGENT, {"protocol_binding": "http_json"}), (LEGACY_AGENT, {})):
                    response = client.post(
                        "/a2a",
                        json={
                            "agent": {"name": name, "description": "Body-capture agent", "endpoint_url": f"{base}/{name}/", "agent_type": "generic", **extra},
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
            stub.shutdown()
            stub.server_close()
            stub_worker.join(timeout=5)


def _invoke_and_capture(client, name):
    """Invoke the agent through the gateway and return the body the stub received."""
    BodyCaptureHandler.captured.clear()
    response = client.post(f"/a2a/{name}/invoke", json={"parameters": {"query": "hello"}})
    assert response.status_code == 200, response.text
    assert len(BodyCaptureHandler.captured) == 1
    path, body = BodyCaptureHandler.captured[0]
    assert path == f"/{name}/"
    return body


def test_http_json_binding_sends_plain_body_to_trailing_slash_endpoint(isolated_gateway):
    """An http_json agent gets the non-JSON-RPC body even though its URL ends in '/'."""
    body = _invoke_and_capture(isolated_gateway, HTTP_JSON_AGENT)

    assert "jsonrpc" not in body
    assert "method" not in body
    assert body["parameters"] == {"query": "hello"}
    assert "interaction_type" in body


def test_agent_without_binding_keeps_jsonrpc_heuristic(isolated_gateway):
    """An agent with no stored binding still falls back to JSON-RPC for a trailing slash."""
    body = _invoke_and_capture(isolated_gateway, LEGACY_AGENT)

    assert body.get("jsonrpc") == "2.0"
    assert "method" in body
