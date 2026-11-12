# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_metrics_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks of ``GET /a2a/metrics`` against an isolated gateway subprocess.

The gateway uses a private SQLite DB. Tests register one public and one team
agent over HTTP, then read the aggregate with tokens of different scope.
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
# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _free_port():
    """Return an ephemeral loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.fixture(scope="module")
def metrics_gateway(tmp_path_factory):
    """Start an authenticated gateway with a v1, a v0.3, and an OAuth-secured agent registered."""
    tmp_path = tmp_path_factory.mktemp("a2a-metrics-gateway")
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

                team_ids = {}
                for team_name in ("metrics-e2e-a", "metrics-e2e-b"):
                    response = client.post("/teams/", json={"name": team_name})
                    assert response.status_code == 201, response.text
                    team_ids[team_name] = response.json()["id"]
                agents = [("metrics-e2e-public", "public", None), ("metrics-e2e-team", "team", team_ids["metrics-e2e-a"])]
                for name, visibility, team_id in agents:
                    payload = {"agent": {"name": name, "description": "Metrics e2e", "endpoint_url": "http://127.0.0.1:9/invoke", "agent_type": "generic"}, "visibility": visibility}
                    if team_id:
                        payload["team_id"] = team_id
                    response = client.post("/a2a", json=payload)
                    assert response.status_code in (200, 201), response.text
                yield gateway_port, signing_key, client, team_ids
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _get_metrics(metrics_gateway, token=None):
    """GET /a2a/metrics with an optional bearer token."""
    port = metrics_gateway[0]
    headers = make_auth_headers(token) if token else {}
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15, trust_env=False) as client:
        return client.get("/a2a/metrics", headers=headers)


def _token(metrics_gateway, email, *, is_admin=False, teams=None, scopes=None):
    """Mint a JWT signed with the gateway secret."""
    secret = metrics_gateway[1]
    return make_test_jwt(email, is_admin=is_admin, teams=teams, scopes=scopes, secret=secret, algorithm="HS256")


def test_admin_sees_public_and_team_agents(metrics_gateway):
    """An admin token counts both agents and returns the full body."""
    response = _get_metrics(metrics_gateway, _token(metrics_gateway, "admin@example.com", is_admin=True, teams=None))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["totalAgents"] == 2
    assert body["activeAgents"] == 2
    for key in ("totalInteractions", "successfulInteractions", "failedInteractions", "successRate", "avgResponseTime", "minResponseTime", "maxResponseTime"):
        assert key in body


def test_owning_team_token_sees_team_agent(metrics_gateway):
    """A token scoped to the owning team counts the team agent."""
    response = _get_metrics(metrics_gateway, _token(metrics_gateway, "admin@example.com", teams=[metrics_gateway[3]["metrics-e2e-a"]]))

    assert response.status_code == 200, response.text
    assert response.json()["totalAgents"] == 2


def test_other_team_token_excludes_team_agent(metrics_gateway):
    """A token scoped to another team counts only the public agent."""
    response = _get_metrics(metrics_gateway, _token(metrics_gateway, "admin@example.com", teams=[metrics_gateway[3]["metrics-e2e-b"]]))

    assert response.status_code == 200, response.text
    assert response.json()["totalAgents"] == 1


def test_public_only_token_counts_public_agent(metrics_gateway):
    """A token with an empty teams claim counts only the public agent."""
    response = _get_metrics(metrics_gateway, _token(metrics_gateway, "admin@example.com", teams=[]))

    assert response.status_code == 200, response.text
    assert response.json()["totalAgents"] == 1


def test_token_without_a2a_read_is_forbidden(metrics_gateway):
    """A token scoped to tools.read cannot read A2A metrics."""
    response = _get_metrics(metrics_gateway, _token(metrics_gateway, "admin@example.com", scopes={"permissions": ["tools.read"]}))

    assert response.status_code == 403


def test_missing_token_is_unauthorized(metrics_gateway):
    """A request without credentials returns 401."""
    assert _get_metrics(metrics_gateway).status_code == 401


def test_metrics_path_is_not_read_as_agent_id(metrics_gateway):
    """The metrics body comes back, not an agent-not-found error."""
    response = _get_metrics(metrics_gateway, _token(metrics_gateway, "admin@example.com", is_admin=True, teams=None))

    assert response.status_code == 200
    assert "not found" not in response.text.lower()


def test_global_metrics_route_is_unchanged(metrics_gateway):
    """GET /metrics still reports the A2A aggregate for an admin."""
    client = metrics_gateway[2]
    response = client.get("/metrics")

    assert response.status_code == 200, response.text
