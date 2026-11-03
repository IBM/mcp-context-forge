# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_test_endpoint_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks for ``POST /v1/a2a/{agent_id}/test``.

The gateway runs as a subprocess with a private SQLite DB. A local HTTP server
stands in for a reachable agent. The test drives success, unknown agent, missing
permission, hidden private agent, and an unreachable agent whose error body must
not echo upstream text.
"""

# Standard
from http.server import BaseHTTPRequestHandler, HTTPServer
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
UNREACHABLE_ENDPOINT = "http://127.0.0.1:9/invoke"


def _free_port():
    """Return an ephemeral loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class _EchoAgent(BaseHTTPRequestHandler):
    """Reply to any POST with the received JSON body."""

    received = []

    def do_POST(self):  # noqa: N802
        """Record the request body and answer 200."""
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        _EchoAgent.received.append(json.loads(body or b"{}"))
        payload = json.dumps({"reply": "pong"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        """Silence request logging."""


@pytest.fixture(scope="module")
def echo_agent():
    """Serve a reachable agent endpoint; yield its URL."""
    server = HTTPServer(("127.0.0.1", _free_port()), _EchoAgent)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/invoke"
    server.shutdown()


@pytest.fixture(scope="module")
def test_gateway(tmp_path_factory, echo_agent):
    """Start a gateway; yield (admin, other-user, reader-only clients, reachable id, unreachable id, private id)."""
    tmp_path = tmp_path_factory.mktemp("a2a-test-endpoint-gateway")
    port = _free_port()
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
        "SSRF_ALLOW_PRIVATE_NETWORKS": "true",
        "PLUGINS_ENABLED": "false",
        "OBSERVABILITY_ENABLED": "false",
        "LOG_LEVEL": "ERROR",
        "PYTHONUNBUFFERED": "1",
    }
    tokens = {
        "admin": make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key, algorithm="HS256"),
        "other": make_test_jwt("other@example.com", is_admin=False, teams=[], scopes={"permissions": ["a2a.invoke"]}, secret=signing_key, algorithm="HS256"),
        "reader": make_test_jwt("reader@example.com", is_admin=False, teams=[], scopes={"permissions": ["a2a.read"]}, secret=signing_key, algorithm="HS256"),
    }
    log_path = tmp_path / "gateway.log"
    with log_path.open("w") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=tmp_path,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            base_url = f"http://127.0.0.1:{port}"
            clients = {name: httpx.Client(base_url=base_url, headers=make_auth_headers(token), timeout=15, trust_env=False) for name, token in tokens.items()}
            try:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text()[-5000:]
                    try:
                        if clients["admin"].get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail(f"Gateway startup timed out: {log_path.read_text()[-5000:]}")

                role = clients["admin"].post("/rbac/roles", json={"name": "a2a-tester", "description": "Invoke A2A agents", "scope": "global", "permissions": ["a2a.read", "a2a.invoke"]})
                assert role.status_code == 200, role.text
                for email in ("other@example.com", "reader@example.com"):
                    user = {"email": email, "password": f"Aa1!{secrets.token_urlsafe(24)}", "full_name": email, "is_admin": False}
                    created_user = clients["admin"].post("/auth/email/admin/users", json=user)
                    assert created_user.status_code == 201, created_user.text
                    granted = clients["admin"].post(f"/rbac/users/{email}/roles", json={"role_id": role.json()["id"], "scope": "global"})
                    assert granted.status_code == 200, granted.text

                def register(name, endpoint, visibility):
                    agent = {"name": name, "endpoint_url": endpoint, "agent_type": "generic", "protocol_version": "1.0"}
                    created = clients["admin"].post("/a2a", json={"agent": agent, "visibility": visibility})
                    assert created.status_code in (200, 201), created.text
                    return created.json()["id"]

                reachable = register("test-e2e-reachable", echo_agent, "public")
                unreachable = register("test-e2e-unreachable", UNREACHABLE_ENDPOINT, "public")
                private = register("test-e2e-private", echo_agent, "private")
                yield clients["admin"], clients["other"], clients["reader"], reachable, unreachable, private
            finally:
                for client in clients.values():
                    client.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_reachable_agent_default_and_custom_message(test_gateway):
    """A reachable agent returns 200 and receives the default, then the custom, message."""
    admin, _other, _reader, reachable, _unreachable, _private = test_gateway
    default = admin.post(f"/v1/a2a/{reachable}/test")
    assert default.status_code == 200, default.text
    body = default.json()
    assert body["success"] is True and body["agent_name"] == "test-e2e-reachable" and "test_timestamp" in body

    custom = admin.post(f"/v1/a2a/{reachable}/test", json={"query": "hello"})
    assert custom.status_code == 200, custom.text
    assert any("hello" in json.dumps(received) for received in _EchoAgent.received)


def test_unknown_agent_is_404_with_fixed_message(test_gateway):
    """An unknown ID returns the fixed not_found envelope."""
    admin = test_gateway[0]
    response = admin.post("/v1/a2a/does-not-exist/test")
    assert response.status_code == 404
    assert response.json()["detail"] == {"success": False, "error": "A2A agent not found", "error_type": "not_found", "agent_id": "does-not-exist"}


def test_token_without_invoke_permission_is_403(test_gateway):
    """A token scoped to a2a.read cannot test an agent."""
    _admin, _other, reader, reachable, _unreachable, _private = test_gateway
    assert reader.post(f"/v1/a2a/{reachable}/test").status_code == 403


def test_unauthenticated_is_401(test_gateway):
    """A request without credentials is rejected."""
    _admin, _other, _reader, reachable, _unreachable, _private = test_gateway
    base_url = str(test_gateway[0].base_url)
    with httpx.Client(base_url=base_url, timeout=15, trust_env=False) as anonymous:
        assert anonymous.post(f"/v1/a2a/{reachable}/test").status_code == 401


def test_hidden_private_agent_matches_missing_agent(test_gateway):
    """A caller who cannot see a private agent gets the same 404 body as for a missing one."""
    _admin, other, _reader, _reachable, _unreachable, private = test_gateway
    hidden = other.post(f"/v1/a2a/{private}/test")
    missing = other.post("/v1/a2a/does-not-exist/test")
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json()["detail"]["error"] == missing.json()["detail"]["error"]
    assert hidden.json()["detail"]["error_type"] == "not_found"


def test_unreachable_agent_is_502_without_upstream_text(test_gateway):
    """An unreachable endpoint returns the fixed message with no host or port."""
    admin, _other, _reader, _reachable, unreachable, _private = test_gateway
    response = admin.post(f"/v1/a2a/{unreachable}/test")
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["error_type"] == "agent_error" and detail["error"] == "A2A agent invocation failed"
    assert "127.0.0.1" not in response.text and ":9" not in detail["error"]


def _register(admin, name, endpoint, agent_type="generic"):
    """Register a public agent and return its ID."""
    agent = {"name": name, "endpoint_url": endpoint, "agent_type": agent_type, "protocol_version": "1.0"}
    created = admin.post("/a2a", json={"agent": agent, "visibility": "public"})
    assert created.status_code in (200, 201), created.text
    return created.json()["id"]


def test_extra_body_field_is_422(test_gateway):
    """An unknown body field fails request validation."""
    admin, _other, _reader, reachable, _unreachable, _private = test_gateway
    response = admin.post(f"/v1/a2a/{reachable}/test", json={"query": "hi", "extra": 1})
    assert response.status_code == 422


def test_oversized_query_is_422(test_gateway):
    """A query over 4096 characters fails request validation."""
    admin, _other, _reader, reachable, _unreachable, _private = test_gateway
    response = admin.post(f"/v1/a2a/{reachable}/test", json={"query": "x" * 4097})
    assert response.status_code == 422


def test_disabled_agent_is_502_agent_disabled(test_gateway, echo_agent):
    """A disabled agent returns the fixed agent_disabled envelope."""
    admin = test_gateway[0]
    agent_id = _register(admin, "test-e2e-disabled", echo_agent)
    state = admin.post(f"/v1/a2a/{agent_id}/state", params={"activate": "false"})
    assert state.status_code == 200, state.text
    response = admin.post(f"/v1/a2a/{agent_id}/test")
    assert response.status_code == 502
    assert response.json()["detail"] == {"success": False, "error": "A2A agent is disabled", "error_type": "agent_disabled", "agent_id": agent_id}


def test_non_generic_agent_receives_extended_payload(test_gateway, echo_agent):
    """A non-generic agent receives message, test, and timestamp alongside query."""
    admin = test_gateway[0]
    agent_id = _register(admin, "test-e2e-custom", echo_agent, agent_type="custom")
    response = admin.post(f"/v1/a2a/{agent_id}/test", json={"query": "payload-check"})
    assert response.status_code == 200, response.text
    received = [item for item in _EchoAgent.received if "payload-check" in json.dumps(item)]
    assert received, _EchoAgent.received
    assert "message" in json.dumps(received[-1]) and "timestamp" in json.dumps(received[-1])


def test_admin_route_keeps_its_contract(test_gateway):
    """The admin route reports failure in the body and keeps the detailed 404 text."""
    admin = test_gateway[0]
    response = admin.post("/admin/a2a/does-not-exist/test", data={"test_message": "hi"})
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False and body["error_type"] == "not_found"
    assert "does-not-exist" in body["error"]
