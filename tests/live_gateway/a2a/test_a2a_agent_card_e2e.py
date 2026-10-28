# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_agent_card_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box A2A agent card checks against an isolated gateway subprocess.

The Rust sidecar serves ``GetExtendedAgentCard`` by calling the gateway's
trusted internal card endpoint. These tests call that endpoint the same way:
shared-secret trust header, forwarded auth context, loopback client. The
gateway uses a private SQLite DB and registers real agents over HTTP.
"""

# Standard
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.auth_context import _expected_internal_mcp_runtime_auth_header_for_secret, encode_internal_mcp_auth_context

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]

V1_AGENT = "card-e2e-v1"
LEGACY_AGENT = "card-e2e-v03"
OAUTH_AGENT = "card-e2e-oauth"
CLIENT_SECRET = "card-e2e-client-secret-value"  # pragma: allowlist secret


def _free_port():
    """Return an ephemeral loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.fixture(scope="module")
def card_gateway(tmp_path_factory):
    """Start an authenticated gateway with a v1, a v0.3, and an OAuth-secured agent registered."""
    tmp_path = tmp_path_factory.mktemp("a2a-card-gateway")
    gateway_port = _free_port()
    signing_key = secrets.token_urlsafe(48)
    encryption_secret = secrets.token_urlsafe(48)
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), *[str(Path(path).resolve()) for path in os.getenv("PYTHONPATH", "").split(os.pathsep) if path]]),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'gateway.db'}",
        "CACHE_TYPE": "memory",
        "REDIS_URL": "",
        "JWT_SECRET_KEY": signing_key,
        "AUTH_ENCRYPTION_SECRET": encryption_secret,
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

                agents = [
                    {"name": V1_AGENT, "protocol_version": "1.0", "capabilities": {"streaming": True, "skills": [{"id": "echo", "name": "Echo", "description": "Echo", "tags": ["t"]}]}},
                    {"name": LEGACY_AGENT, "protocol_version": "0.3", "capabilities": {"streaming": True}},
                    {
                        "name": OAUTH_AGENT,
                        "protocol_version": "1.0",
                        "auth_type": "oauth",
                        "oauth_config": {"grant_type": "client_credentials", "token_url": "https://auth.example.com/token", "client_id": "cid", "client_secret": CLIENT_SECRET, "scopes": ["read"]},
                    },
                ]
                for agent in agents:
                    agent.update(description="Agent card e2e", endpoint_url="http://127.0.0.1:9/invoke", agent_type="generic")
                    response = client.post("/a2a", json={"agent": agent, "visibility": "public"})
                    assert response.status_code in (200, 201), response.text

                trust_headers = {
                    "x-contextforge-mcp-runtime": "rust",
                    "x-contextforge-mcp-runtime-auth": _expected_internal_mcp_runtime_auth_header_for_secret(encryption_secret),
                    "x-contextforge-auth-context": encode_internal_mcp_auth_context({"email": "admin@example.com", "teams": None, "is_admin": True, "is_authenticated": True}),
                }
                yield gateway_port, trust_headers, client
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _fetch_card(card_gateway, agent_name, *, headers=None, trusted=True):
    """POST to the internal card endpoint the way the sidecar does."""
    port, trust_headers, _client = card_gateway
    request_headers = {**(trust_headers if trusted else {}), **(headers or {})}
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15, trust_env=False) as sidecar:
        return sidecar.post(f"/_internal/a2a/agents/{agent_name}/card", json={}, headers=request_headers)


def test_v1_agent_card_has_1_0_shape(card_gateway):
    """A 1.x agent serves the A2A 1.0 card."""
    response = _fetch_card(card_gateway, V1_AGENT)

    assert response.status_code == 200, response.text
    card = response.json()
    assert card["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
    assert card["capabilities"]["extendedAgentCard"] is True
    assert card["capabilities"]["streaming"] is True
    assert card["skills"][0]["id"] == "echo"
    for removed in ("url", "protocolVersion", "supportsAuthenticatedExtendedCard"):
        assert removed not in card
    assert "stateTransitionHistory" not in card["capabilities"]


def test_v03_agent_card_keeps_legacy_shape(card_gateway):
    """A 0.x agent serves the legacy card."""
    response = _fetch_card(card_gateway, LEGACY_AGENT)

    assert response.status_code == 200, response.text
    card = response.json()
    assert card["protocolVersion"] == "0.3"
    assert card["supportsAuthenticatedExtendedCard"] is True
    assert "supportedInterfaces" not in card


def test_legacy_caller_gets_legacy_card_for_v1_agent(card_gateway):
    """A caller that declares A2A-Version 0.3 keeps the legacy shape for a 1.x agent."""
    response = _fetch_card(card_gateway, V1_AGENT, headers={"A2A-Version": "0.3"})

    assert response.status_code == 200, response.text
    card = response.json()
    assert "url" in card
    assert "supportedInterfaces" not in card


def test_v1_caller_gets_v1_card_for_v1_agent(card_gateway):
    """A caller that declares A2A-Version 1.0 gets the 1.0 shape."""
    response = _fetch_card(card_gateway, V1_AGENT, headers={"A2A-Version": "1.0"})

    assert response.status_code == 200, response.text
    assert "supportedInterfaces" in response.json()


def test_oauth_agent_card_exposes_scheme_without_credentials(card_gateway):
    """The card carries the derived OAuth scheme and never a credential value."""
    response = _fetch_card(card_gateway, OAUTH_AGENT)

    assert response.status_code == 200, response.text
    card = response.json()
    flows = card["securitySchemes"]["oauth2Auth"]["oauth2SecurityScheme"]["flows"]
    assert flows["clientCredentials"]["tokenUrl"] == "https://auth.example.com/token"
    assert card["securityRequirements"] == [{"schemes": {"oauth2Auth": {}}}]
    assert CLIENT_SECRET not in response.text


def test_card_endpoint_rejects_untrusted_caller(card_gateway):
    """Without the runtime trust headers the internal card endpoint is closed."""
    response = _fetch_card(card_gateway, V1_AGENT, trusted=False)

    assert response.status_code == 403


def test_unknown_agent_card_returns_404(card_gateway):
    """A trusted caller asking for a missing agent gets 404."""
    response = _fetch_card(card_gateway, "card-e2e-missing")

    assert response.status_code == 404
