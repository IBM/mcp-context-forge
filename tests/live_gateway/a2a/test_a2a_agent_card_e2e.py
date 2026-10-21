# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_agent_card_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks for ``GET /v1/a2a/{agent_id}/card`` against an isolated gateway subprocess.

The gateway uses a private SQLite DB and real HTTP requests. Authentication,
RBAC, token scoping, and visibility run exactly as in production.
"""

# Standard
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
import uuid

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]

ADMIN_EMAIL = "admin@example.com"
OTHER_EMAIL = "other@example.com"


def _free_port():
    """Return an ephemeral loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _bearer(email, signing_key, **kwargs):
    """Return Authorization headers for a JWT signed with the gateway key."""
    return make_auth_headers(make_test_jwt(email, secret=signing_key, algorithm="HS256", **kwargs))


@pytest.fixture(scope="module")
def card_gateway(tmp_path_factory):
    """Start an authenticated gateway and seed agents of every visibility.

    Yields a namespace-like dict with the admin client, the signing key, and the
    IDs of the seeded agents and virtual server.
    """
    tmp_path = tmp_path_factory.mktemp("a2a-card-gateway")
    db_path = tmp_path / "gateway.db"
    gateway_port = _free_port()
    signing_key = secrets.token_urlsafe(48)
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), *[str(Path(path).resolve()) for path in os.getenv("PYTHONPATH", "").split(os.pathsep) if path]]),
        "DATABASE_URL": f"sqlite:///{db_path}",
        "CACHE_TYPE": "memory",
        "REDIS_URL": "",
        "JWT_SECRET_KEY": signing_key,
        "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
        "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32),
        "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
        "PLATFORM_ADMIN_EMAIL": ADMIN_EMAIL,
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
            admin_headers = _bearer(ADMIN_EMAIL, signing_key, is_admin=True, teams=None)
            with httpx.Client(base_url=base_url, headers=admin_headers, timeout=15, trust_env=False) as client:
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

                response = client.post("/auth/email/admin/users", json={"email": OTHER_EMAIL, "password": secrets.token_urlsafe(24), "full_name": "Other User"})
                assert response.status_code in (200, 201), response.text

                agent_ids = {}
                for visibility in ("public", "private"):
                    response = client.post(
                        "/v1/a2a",
                        json={
                            "agent": {
                                "name": f"card-{visibility}-agent",
                                "description": f"{visibility} agent",
                                "endpoint_url": "http://127.0.0.1:9/invoke",
                                "agent_type": "generic",
                                "capabilities": {"skills": [{"id": f"{visibility}-skill", "name": f"{visibility} skill"}]},
                            },
                            "visibility": visibility,
                        },
                    )
                    assert response.status_code in (200, 201), response.text
                    agent_ids[visibility] = response.json()["id"]

                response = client.post(
                    "/servers",
                    json={
                        "server": {"name": "card-public-server", "description": "A2A-exposing server", "associated_a2a_agents": list(agent_ids.values())},
                        "visibility": "public",
                    },
                )
                assert response.status_code in (200, 201), response.text
                server_id = response.json()["id"]

            connection = sqlite3.connect(db_path)
            try:
                other_team_id = connection.execute("SELECT team_id FROM email_team_members WHERE user_email = ?", (OTHER_EMAIL,)).fetchone()[0]
                connection.execute(
                    "INSERT INTO server_interfaces (id, server_id, protocol, binding, version, enabled, created_at, updated_at) "
                    "VALUES (?, ?, 'a2a', 'http://127.0.0.1:9/a2a', '1.0', 1, datetime('now'), datetime('now'))",
                    (str(uuid.uuid4()), server_id),
                )
                connection.commit()
            finally:
                connection.close()

            yield {"base_url": base_url, "key": signing_key, "agents": agent_ids, "server_id": server_id, "other_team_id": other_team_id}
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _get(gateway, path, headers=None):
    """Issue a GET against the gateway without environment proxies."""
    with httpx.Client(base_url=gateway["base_url"], timeout=15, trust_env=False) as client:
        return client.get(path, headers=headers or {})


def test_card_for_public_agent(card_gateway):
    """An authorized admin reads a standalone agent's card, and the response is not cacheable."""
    headers = _bearer(ADMIN_EMAIL, card_gateway["key"], is_admin=True, teams=None)
    response = _get(card_gateway, f"/v1/a2a/{card_gateway['agents']['public']}/card", headers)
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "card-public-agent"
    assert {part.strip() for part in response.headers["cache-control"].split(",")} >= {"private", "no-store"}


def test_card_falls_back_to_virtual_server(card_gateway):
    """A virtual server ID resolves to a server card that lists the skills of attached agents."""
    admin = _bearer(ADMIN_EMAIL, card_gateway["key"], is_admin=True, teams=None)
    response = _get(card_gateway, f"/v1/a2a/{card_gateway['server_id']}/card", admin)
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "card-public-server"
    assert {skill["id"] for skill in response.json()["skills"]} == {"public-skill", "private-skill"}


def test_server_card_hides_private_agent_skills_from_other_user(card_gateway):
    """A public-only caller sees a public server but never the skills of the admin's private agent."""
    other = _bearer(OTHER_EMAIL, card_gateway["key"], teams=[])
    response = _get(card_gateway, f"/v1/a2a/{card_gateway['server_id']}/card", other)
    assert response.status_code == 200, response.text
    assert "private-skill" not in {skill["id"] for skill in response.json()["skills"]}


def test_unknown_id_returns_404(card_gateway):
    """An unknown ID returns 404."""
    headers = _bearer(ADMIN_EMAIL, card_gateway["key"], is_admin=True, teams=None)
    assert _get(card_gateway, "/v1/a2a/does-not-exist/card", headers).status_code == 404


def test_private_agent_of_another_user_returns_404(card_gateway):
    """A non-owner gets a 404 that does not reveal the agent exists, for public-only and own-team tokens."""
    path = f"/v1/a2a/{card_gateway['agents']['private']}/card"
    for teams in ([], [card_gateway["other_team_id"]]):
        response = _get(card_gateway, path, _bearer(OTHER_EMAIL, card_gateway["key"], teams=teams))
        assert response.status_code == 404, response.text
        assert card_gateway["agents"]["private"] not in response.text


def test_missing_token_returns_401(card_gateway):
    """A request without a token is rejected."""
    assert _get(card_gateway, f"/v1/a2a/{card_gateway['agents']['public']}/card").status_code == 401


def test_token_without_a2a_read_returns_403(card_gateway):
    """A token whose scope omits a2a.read is rejected even for an admin identity."""
    headers = _bearer(ADMIN_EMAIL, card_gateway["key"], is_admin=True, teams=None, scopes={"permissions": ["tools.read"]})
    assert _get(card_gateway, f"/v1/a2a/{card_gateway['agents']['public']}/card", headers).status_code == 403
