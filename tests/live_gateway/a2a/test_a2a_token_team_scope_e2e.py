# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_token_team_scope_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks that a token narrowed to Team A cannot mutate a Team B A2A agent.

The identity behind the narrowed token owns the agent, so only the token's signed
``teams`` claim can stop the request. The gateway runs as an isolated subprocess with
a private SQLite DB. Authentication, RBAC, token scoping and visibility run as in production.
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
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]

OWNER_EMAIL = "admin@example.com"
ORIGINAL_ENDPOINT = "http://127.0.0.1:9/original"
ATTACKER_ENDPOINT = "http://127.0.0.1:9/attacker"


def _free_port():
    """Return an ephemeral loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _bearer(signing_key, teams):
    """Return Authorization headers for the owner with the given signed ``teams`` claim."""
    return make_auth_headers(make_test_jwt(OWNER_EMAIL, secret=signing_key, algorithm="HS256", is_admin=True, teams=teams))


@pytest.fixture(scope="module")
def scope_gateway(tmp_path_factory):
    """Start an authenticated gateway with Team A and Team B.

    Yields the base URL, the signing key, and the IDs of both teams.
    """
    tmp_path = tmp_path_factory.mktemp("a2a-token-scope-gateway")
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
        "PLATFORM_ADMIN_EMAIL": OWNER_EMAIL,
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
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(gateway_port)],
            cwd=tmp_path,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            base_url = f"http://127.0.0.1:{gateway_port}"
            with httpx.Client(base_url=base_url, headers=_bearer(signing_key, None), timeout=15, trust_env=False) as client:
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

                team_ids = {}
                for label in ("a", "b"):
                    response = client.post("/teams/", json={"name": f"scope-team-{label}", "description": f"Team {label.upper()}"})
                    assert response.status_code in (200, 201), response.text
                    team_ids[label] = response.json()["id"]

            yield {"base_url": base_url, "key": signing_key, "team_a": team_ids["a"], "team_b": team_ids["b"]}
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.fixture
def team_b_agent(scope_gateway):
    """Create a fresh team-visible agent in Team B, owned by the token's identity."""
    headers = _bearer(scope_gateway["key"], [scope_gateway["team_b"]])
    with httpx.Client(base_url=scope_gateway["base_url"], headers=headers, timeout=15, trust_env=False) as client:
        response = client.post(
            "/a2a",
            json={
                "agent": {"name": f"team-b-agent-{secrets.token_hex(4)}", "description": "Team B agent", "endpoint_url": ORIGINAL_ENDPOINT, "agent_type": "generic"},
                "team_id": scope_gateway["team_b"],
                "visibility": "team",
            },
        )
        assert response.status_code in (200, 201), response.text
        return response.json()["id"]


def _request(gateway, method, path, teams, **kwargs):
    """Send one request with a token whose signed ``teams`` claim is ``teams``."""
    with httpx.Client(base_url=gateway["base_url"], headers=_bearer(gateway["key"], teams), timeout=15, trust_env=False) as client:
        return client.request(method, path, **kwargs)


def _stored_agent(gateway, agent_id):
    """Read the agent with a token scoped to its own team."""
    response = _request(gateway, "GET", f"/a2a/{agent_id}", [gateway["team_b"]])
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("teams_key", ["team_a", None])
def test_update_outside_token_team_scope_is_denied(scope_gateway, team_b_agent, teams_key):
    """PUT with a Team-A-only or public-only token returns 403 and leaves the agent unchanged."""
    teams = [scope_gateway[teams_key]] if teams_key else []
    response = _request(scope_gateway, "PUT", f"/a2a/{team_b_agent}", teams, json={"endpoint_url": ATTACKER_ENDPOINT, "visibility": "public"})

    assert response.status_code == 403, response.text
    stored = _stored_agent(scope_gateway, team_b_agent)
    assert stored["endpointUrl"] == ORIGINAL_ENDPOINT
    assert stored["visibility"] == "team"


def test_state_change_outside_token_team_scope_is_denied(scope_gateway, team_b_agent):
    """POST /state with a Team-A-only token returns 403 and keeps the agent enabled."""
    response = _request(scope_gateway, "POST", f"/a2a/{team_b_agent}/state?activate=false", [scope_gateway["team_a"]])

    assert response.status_code == 403, response.text
    assert _stored_agent(scope_gateway, team_b_agent)["enabled"] is True


def test_delete_outside_token_team_scope_is_denied(scope_gateway, team_b_agent):
    """DELETE with a Team-A-only token returns 403 and keeps the agent."""
    response = _request(scope_gateway, "DELETE", f"/a2a/{team_b_agent}", [scope_gateway["team_a"]])

    assert response.status_code == 403, response.text
    assert _stored_agent(scope_gateway, team_b_agent)["id"] == team_b_agent


def test_update_inside_token_team_scope_is_allowed(scope_gateway, team_b_agent):
    """The same identity succeeds when its token is scoped to the agent's team."""
    response = _request(scope_gateway, "PUT", f"/a2a/{team_b_agent}", [scope_gateway["team_b"]], json={"description": "updated by Team B token"})

    assert response.status_code == 200, response.text
    assert _stored_agent(scope_gateway, team_b_agent)["description"] == "updated by Team B token"


def test_read_outside_token_team_scope_keeps_not_found(scope_gateway, team_b_agent):
    """A read with a Team-A-only token returns 404, so a hidden agent looks the same as a missing one."""
    hidden = _request(scope_gateway, "GET", f"/a2a/{team_b_agent}", [scope_gateway["team_a"]])
    missing = _request(scope_gateway, "GET", f"/a2a/{'0' * 32}", [scope_gateway["team_a"]])

    assert hidden.status_code == missing.status_code == 404
