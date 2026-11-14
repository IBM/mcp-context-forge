# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_fetch_card_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks for ``POST /a2a/fetch-card`` against an isolated gateway subprocess.

A loopback HTTP server plays the remote agent. The gateway allows loopback through
``SSRF_ALLOW_LOCALHOST`` so the full route, RBAC and outbound-policy stack runs.
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

V1_CARD = {
    "name": "e2e-v1",
    "version": "1",
    "supportedInterfaces": [{"url": "http://127.0.0.1:9/rpc", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
    "capabilities": {"streaming": True},
    "securitySchemes": {"bearerAuth": {"httpAuthSecurityScheme": {"scheme": "bearer"}}},
    "securityRequirements": [{"schemes": {"bearerAuth": {}}}],
}
LEGACY_CARD = {"name": "e2e-legacy", "url": "http://127.0.0.1:9/rpc", "protocolVersion": "0.3.0", "capabilities": {"streaming": False}}


def _free_port():
    """Return an ephemeral loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class _AgentHandler(BaseHTTPRequestHandler):
    """Serve the cards under test on fixed paths."""

    def do_GET(self):  # noqa: N802
        """Route a GET to the card behind that path."""
        routes = {
            "/v1/.well-known/agent-card.json": (200, V1_CARD),
            "/legacy/.well-known/agent.json": (200, LEGACY_CARD),
            "/secure/.well-known/agent-card.json": (401, None),
            "/malformed/.well-known/agent-card.json": (200, {"name": "x", "url": "http://127.0.0.1:9/rpc", "capabilities": "invalid"}),
        }
        status, body = routes.get(self.path, (404, None))
        self.send_response(status)
        if status == 401:
            self.send_header("WWW-Authenticate", 'Bearer realm="a2a"')
        self.send_header("Content-Type", "application/json")
        payload = json.dumps(body).encode() if body is not None else b"{}"
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        """Silence request logging."""


@pytest.fixture(scope="module")
def agent_server():
    """Run the fake remote agent on loopback."""
    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), _AgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def gateway(tmp_path_factory):
    """Start an authenticated gateway; yield its base URL and the signing key."""
    tmp_path = tmp_path_factory.mktemp("a2a-fetch-card-gateway")
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
        "PLUGINS_ENABLED": "false",
        "OBSERVABILITY_ENABLED": "false",
        "LOG_LEVEL": "ERROR",
        "PYTHONUNBUFFERED": "1",
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
            deadline = time.monotonic() + 60
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15, trust_env=False) as probe:
                while time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text()[-5000:]
                    try:
                        if probe.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail(f"Gateway startup timed out: {log_path.read_text()[-5000:]}")
            yield f"http://127.0.0.1:{port}", signing_key
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _post(gateway, body, *, token=True, scopes=None, prefix=""):
    """POST a fetch-card request, optionally with a scoped token."""
    base, key = gateway
    headers = {}
    if token:
        headers = make_auth_headers(make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=key, algorithm="HS256", scopes=scopes))
    with httpx.Client(base_url=base, timeout=15, trust_env=False) as client:
        return client.post(f"{prefix}/a2a/fetch-card", json=body, headers=headers)


@pytest.mark.parametrize("prefix", ["", "/v1"])
def test_fetches_v1_card_on_both_aliases(gateway, agent_server, prefix):
    """A 1.0 card comes back normalized with a suggested agent."""
    response = _post(gateway, {"baseUrl": f"{agent_server}/v1"}, prefix=prefix)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "found" and body["detectedVersion"] == "1.0"
    assert body["suggestedAgent"]["auth_type"] == "bearer"


def test_fetches_legacy_card(gateway, agent_server):
    """A 0.3 card falls back to the pre-1.0 path and is converted."""
    response = _post(gateway, {"baseUrl": f"{agent_server}/legacy"})

    body = response.json()
    assert response.status_code == 200 and body["outcome"] == "found" and body["detectedVersion"] == "0.3"
    assert body["card"]["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
    assert body["rawCard"]["url"] == LEGACY_CARD["url"]


def test_absent_card_reports_no_card(gateway, agent_server):
    """A reachable host without a card reports no_card."""
    response = _post(gateway, {"baseUrl": f"{agent_server}/nothing"})

    assert response.status_code == 200 and response.json()["outcome"] == "no_card"


def test_malformed_card_reports_no_card(gateway, agent_server):
    """A card with wrongly typed nested fields reports no_card, not a 500."""
    response = _post(gateway, {"baseUrl": f"{agent_server}/malformed"})

    assert response.status_code == 200 and response.json()["outcome"] == "no_card"


def test_protected_card_reports_auth_required(gateway, agent_server):
    """A 401 from the agent reports auth_required with the scheme name only."""
    response = _post(gateway, {"baseUrl": f"{agent_server}/secure"})

    body = response.json()
    assert body["outcome"] == "auth_required" and body["authScheme"] == "Bearer"
    assert "realm" not in response.text


def test_closed_port_reports_unreachable(gateway):
    """A refused connection reports unreachable."""
    response = _post(gateway, {"baseUrl": f"http://127.0.0.1:{_free_port()}"})

    assert response.status_code == 200 and response.json()["outcome"] == "unreachable"


def test_blocked_address_reports_unreachable(gateway):
    """A cloud-metadata address is refused by the outbound policy and looks like any unreachable host."""
    response = _post(gateway, {"baseUrl": "http://169.254.169.254"})

    assert response.status_code == 200 and response.json()["outcome"] == "unreachable"


@pytest.mark.parametrize("prefix", ["", "/v1"])
def test_unsafe_path_returns_422(gateway, agent_server, prefix):
    """A traversal path is a client error on both aliases."""
    for path in ("../etc/passwd", "/%2e%2e/x"):
        assert _post(gateway, {"baseUrl": agent_server, "path": path}, prefix=prefix).status_code == 422


def test_base_url_with_query_returns_422(gateway, agent_server):
    """A base URL with a query is a client error."""
    assert _post(gateway, {"baseUrl": f"{agent_server}/?a=b"}).status_code == 422


def test_no_token_returns_401(gateway, agent_server):
    """An unauthenticated call is rejected."""
    assert _post(gateway, {"baseUrl": agent_server}, token=False).status_code == 401


@pytest.mark.parametrize("permission", ["a2a.read", "a2a.invoke"])
def test_token_without_a2a_create_returns_403(gateway, agent_server, permission):
    """A token scoped to another a2a permission cannot fetch a card."""
    response = _post(gateway, {"baseUrl": agent_server}, scopes={"permissions": [permission]})

    assert response.status_code == 403
