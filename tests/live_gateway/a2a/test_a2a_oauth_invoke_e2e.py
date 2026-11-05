# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_oauth_invoke_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks that an OAuth-protected A2A agent is invoked with a client-credentials token (#7382).

Loopback servers play the identity provider and the remote agent. The gateway registers
the agent over HTTP, stores the client secret encrypted, and invokes the agent through
``POST /a2a/{name}/invoke``.
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
from urllib.parse import parse_qs

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]

CLIENT_SECRET = "oauth-e2e-client-secret-value"  # pragma: allowlist secret
ISSUED_TOKEN = "e2e-issued-access-token"  # pragma: allowlist secret
OK_AGENT = "oauth-e2e-agent"
FAIL_AGENT = "oauth-e2e-failing-idp"
DISABLED_AGENT = "oauth-e2e-disabled"
PRIVATE_AGENT = "oauth-e2e-private"


def _free_port():
    """Return an ephemeral loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class _Recorder:
    """Thread-safe record of requests a fake server received."""

    def __init__(self):
        self.lock = threading.Lock()
        self.token_requests = []
        self.agent_requests = []

    def clear(self):
        """Forget every recorded request."""
        with self.lock:
            self.token_requests.clear()
            self.agent_requests.clear()


def _serve(handler_factory):
    """Start a loopback server on a daemon thread."""
    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), handler_factory)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _make_idp_handler(recorder):
    """Build an identity-provider handler: ``/token`` issues a token, ``/broken`` returns 500."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            """Answer a token request."""
            length = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(length).decode())
            with recorder.lock:
                recorder.token_requests.append({"path": self.path, "form": form, "authorization": self.headers.get("Authorization")})
            status, body = (200, {"access_token": ISSUED_TOKEN, "token_type": "Bearer", "expires_in": 3600}) if self.path == "/token" else (500, {"error": "server_error"})
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            """Silence request logging."""

    return Handler


def _make_agent_handler(recorder):
    """Build an agent handler that records its Authorization header and answers 200."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            """Record the call and answer."""
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            with recorder.lock:
                recorder.agent_requests.append({"authorization": self.headers.get("Authorization")})
            payload = json.dumps({"response": "ok", "status": "success"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            """Silence request logging."""

    return Handler


@pytest.fixture(scope="module")
def servers():
    """Run the fake identity provider and agent; yield their URLs and the shared recorder."""
    recorder = _Recorder()
    idp = _serve(_make_idp_handler(recorder))
    agent = _serve(_make_agent_handler(recorder))
    yield f"http://127.0.0.1:{idp.server_address[1]}", f"http://127.0.0.1:{agent.server_address[1]}", recorder
    idp.shutdown()
    agent.shutdown()


@pytest.fixture(scope="module")
def gateway(tmp_path_factory, servers):
    """Start an authenticated gateway with OAuth agents registered; yield its URL and signing key."""
    idp_url, agent_url, _recorder = servers
    tmp_path = tmp_path_factory.mktemp("a2a-oauth-gateway")
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
    admin_headers = make_auth_headers(make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key, algorithm="HS256"))
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
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(base_url=base, headers=admin_headers, timeout=20, trust_env=False) as client:
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

                def register(name, token_path, visibility="public", team_id=None):
                    body = {
                        "agent": {
                            "name": name,
                            "description": "OAuth invoke e2e",
                            "endpoint_url": f"{agent_url}/invoke",
                            "agent_type": "generic",
                            "protocol_version": "1.0",
                            "auth_type": "oauth",
                            "oauth_config": {"grant_type": "client_credentials", "token_url": f"{idp_url}{token_path}", "client_id": "cid", "client_secret": CLIENT_SECRET, "scopes": ["read"]},
                        },
                        "visibility": visibility,
                    }
                    if team_id:
                        body["team_id"] = team_id
                    response = client.post("/a2a", json=body)
                    assert response.status_code in (200, 201), response.text
                    return response.json()

                register(OK_AGENT, "/token")
                register(FAIL_AGENT, "/broken")
                disabled = register(DISABLED_AGENT, "/token")
                assert client.post(f"/a2a/{disabled['id']}/state", params={"activate": "false"}).status_code == 200
                register(PRIVATE_AGENT, "/token", visibility="private")
            yield base, signing_key
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _invoke(gateway, name, *, token="admin", scopes=None, teams=None, email="admin@example.com", is_admin=True):
    """POST an invocation. ``token=None`` sends no credential."""
    base, key = gateway
    headers = {}
    if token:
        headers = make_auth_headers(make_test_jwt(email, is_admin=is_admin, teams=teams, secret=key, algorithm="HS256", scopes=scopes))
    with httpx.Client(base_url=base, timeout=30, trust_env=False) as client:
        return client.post(f"/a2a/{name}/invoke", json={"parameters": {"query": "hi"}}, headers=headers)


def test_invocation_forwards_issued_bearer_token_and_reuses_it(gateway, servers):
    """The gateway decrypts the stored secret, gets one token, forwards it as a bearer, and reuses it."""
    _idp, _agent, recorder = servers
    recorder.clear()

    for _ in range(3):
        response = _invoke(gateway, OK_AGENT)
        assert response.status_code == 200, response.text

    assert len(recorder.token_requests) == 1
    request = recorder.token_requests[0]
    assert request["form"]["grant_type"] == ["client_credentials"]
    assert CLIENT_SECRET in json.dumps(request)
    assert [call["authorization"] for call in recorder.agent_requests] == [f"Bearer {ISSUED_TOKEN}"] * 3


def test_callers_gateway_token_is_not_forwarded(gateway, servers):
    """The caller's own gateway bearer never reaches the agent; only the issued token does."""
    _idp, _agent, recorder = servers
    recorder.clear()

    assert _invoke(gateway, OK_AGENT).status_code == 200

    assert [call["authorization"] for call in recorder.agent_requests] == [f"Bearer {ISSUED_TOKEN}"]


def test_token_acquisition_failure_sends_no_request_to_agent(gateway, servers):
    """When the identity provider fails, the invocation fails and the agent is never called."""
    _idp, _agent, recorder = servers
    recorder.clear()

    response = _invoke(gateway, FAIL_AGENT)

    assert response.status_code >= 400
    assert recorder.token_requests
    assert recorder.agent_requests == []
    assert CLIENT_SECRET not in response.text


def test_no_token_returns_401_without_side_effects(gateway, servers):
    """An unauthenticated call acquires no token and calls no agent."""
    _idp, _agent, recorder = servers
    recorder.clear()

    assert _invoke(gateway, OK_AGENT, token=None).status_code == 401

    assert recorder.token_requests == [] and recorder.agent_requests == []


@pytest.mark.parametrize("permission", ["a2a.read", "a2a.create"])
def test_token_without_a2a_invoke_returns_403_without_side_effects(gateway, servers, permission):
    """A token scoped to another permission acquires no token and calls no agent."""
    _idp, _agent, recorder = servers
    recorder.clear()

    assert _invoke(gateway, OK_AGENT, scopes={"permissions": [permission]}).status_code == 403

    assert recorder.token_requests == [] and recorder.agent_requests == []


def test_disabled_agent_acquires_no_token(gateway, servers):
    """A disabled OAuth agent is not invoked and no token is requested."""
    _idp, _agent, recorder = servers
    recorder.clear()

    assert _invoke(gateway, DISABLED_AGENT).status_code >= 400

    assert recorder.token_requests == [] and recorder.agent_requests == []


def test_other_users_private_agent_acquires_no_token(gateway, servers):
    """A non-admin user cannot invoke another user's private OAuth agent, and no token is requested."""
    _idp, _agent, recorder = servers
    recorder.clear()

    response = _invoke(gateway, PRIVATE_AGENT, email="stranger@example.com", is_admin=False, teams=["other-team"])

    assert response.status_code in (403, 404)
    assert recorder.token_requests == [] and recorder.agent_requests == []
