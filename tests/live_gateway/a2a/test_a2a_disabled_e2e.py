# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_disabled_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks for a gateway started with ``MCPGATEWAY_A2A_ENABLED=false``.

The gateway runs as a subprocess with a private SQLite DB. Every A2A route
answers authenticated callers with the typed ``a2a_disabled`` 404 and
unauthenticated callers with 401. ``/auth/email/me`` reports ``features.a2a``.
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

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]
DISABLED_BODY = {"detail": {"error": "a2a_disabled", "message": "A2A is disabled on this gateway"}}
A2A_ROUTES = [
    ("GET", "/v1/a2a"),
    ("GET", "/v1/a2a/agent-1"),
    ("GET", "/v1/a2a/agent-1/card"),
    ("POST", "/v1/a2a/agent-1/invoke"),
    ("GET", "/v1/a2a/agent-1/tasks"),
    ("GET", "/admin/a2a"),
    ("GET", "/admin/a2a/agent-1"),
    ("GET", "/admin/a2a/ids"),
    ("GET", "/admin/a2a/search"),
    ("GET", "/admin/a2a/partial"),
    ("POST", "/admin/a2a"),
    ("POST", "/admin/a2a/agent-1/test"),
]


def _free_port():
    """Return an ephemeral loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.fixture(scope="module")
def disabled_gateway(tmp_path_factory):
    """Start a gateway with A2A disabled; yield (admin client, anonymous client, user client, token client factory)."""
    tmp_path = tmp_path_factory.mktemp("a2a-disabled-gateway")
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
        "MCPGATEWAY_A2A_ENABLED": "false",
        "PLUGINS_ENABLED": "false",
        "OBSERVABILITY_ENABLED": "false",
        "LOG_LEVEL": "ERROR",
        "PYTHONUNBUFFERED": "1",
    }
    admin_token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key, algorithm="HS256")
    user_password = f"Aa1!{secrets.token_urlsafe(24)}"
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
            with (
                httpx.Client(base_url=base_url, headers=make_auth_headers(admin_token), timeout=15, trust_env=False) as admin,
                httpx.Client(base_url=base_url, timeout=15, trust_env=False) as anonymous,
                httpx.Client(base_url=base_url, timeout=15, trust_env=False) as user,
            ):
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text()[-5000:]
                    try:
                        if admin.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail(f"Gateway startup timed out: {log_path.read_text()[-5000:]}")
                created = admin.post("/auth/email/admin/users", json={"email": "user@example.com", "password": user_password, "full_name": "Plain User", "is_admin": False})
                assert created.status_code in (200, 201), created.text
                login = user.post("/auth/email/login", json={"email": "user@example.com", "password": user_password})
                assert login.status_code == 200, login.text
                user.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
                extra_clients = []

                def client_for(**jwt_kwargs):
                    """Return a client for a signed token issued to the non-admin DB user."""
                    token = make_test_jwt("user@example.com", secret=signing_key, algorithm="HS256", **jwt_kwargs)
                    client = httpx.Client(base_url=base_url, headers=make_auth_headers(token), timeout=15, trust_env=False)
                    extra_clients.append(client)
                    return client

                try:
                    yield admin, anonymous, user, client_for
                finally:
                    for client in extra_clients:
                        client.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.parametrize("method,path", A2A_ROUTES)
def test_a2a_routes_return_typed_404_for_admin(disabled_gateway, method, path):
    """Authenticated admin callers get the typed a2a_disabled 404 on every A2A route."""
    admin, _anonymous, _user, _client_for = disabled_gateway
    response = admin.request(method, path)
    assert response.status_code == 404, response.text
    assert response.json() == DISABLED_BODY


@pytest.mark.parametrize("method,path", A2A_ROUTES)
def test_a2a_routes_reject_anonymous_callers(disabled_gateway, method, path):
    """Unauthenticated callers get 401, so only authenticated callers learn A2A is off."""
    _admin, anonymous, _user, _client_for = disabled_gateway
    assert anonymous.request(method, path).status_code == 401


def test_metrics_reset_a2a_returns_typed_404(disabled_gateway):
    """Resetting A2A metrics reports the typed a2a_disabled 404."""
    admin, _anonymous, _user, _client_for = disabled_gateway
    response = admin.post("/metrics/reset", params={"entity": "a2a"})
    assert response.status_code == 404, response.text
    assert response.json() == DISABLED_BODY


def test_openapi_omits_a2a_operations(disabled_gateway):
    """The OpenAPI schema lists no A2A operation when A2A is disabled."""
    admin, _anonymous, _user, _client_for = disabled_gateway
    response = admin.get("/openapi.json")
    assert response.status_code == 200
    assert not [path for path in response.json()["paths"] if path in ("/v1/a2a", "/a2a") or path.startswith(("/v1/a2a/", "/a2a/"))]


def test_me_reports_a2a_flag_for_non_admin(disabled_gateway):
    """A non-admin caller reads features.a2a == false from /auth/email/me."""
    _admin, _anonymous, user, _client_for = disabled_gateway
    response = user.get("/auth/email/me")
    assert response.status_code == 200, response.text
    assert response.json()["features"] == {"a2a": False}


ADMIN_A2A_ROUTES = [route for route in A2A_ROUTES if route[1].startswith("/admin/")]


@pytest.mark.parametrize("method,path", ADMIN_A2A_ROUTES)
def test_admin_a2a_routes_check_rbac_before_disabled_state(disabled_gateway, method, path):
    """A plain user holds a2a.read, so GET routes reach the disabled check. Other routes deny with 403."""
    _admin, _anonymous, user, _client_for = disabled_gateway
    expected = 404 if method == "GET" else 403
    assert user.request(method, path).status_code == expected


@pytest.mark.parametrize("method,path", ADMIN_A2A_ROUTES)
def test_admin_a2a_routes_deny_wrong_permission_token(disabled_gateway, method, path):
    """A token scoped to unrelated permissions is denied on the admin A2A routes."""
    _admin, _anonymous, _user, client_for = disabled_gateway
    client = client_for(teams=[], scopes={"permissions": ["tools.read"]})
    assert client.request(method, path).status_code == 403


@pytest.mark.parametrize(
    "jwt_kwargs",
    [
        {"teams": [], "scopes": {"permissions": ["tools.read"]}},
        {"extra_payload": {"token_use": "session"}, "auth_provider": "sso", "include_user_data": True},
    ],
    ids=["scoped-api-token", "sso-session-token"],
)
def test_me_reports_a2a_flag_for_scoped_and_sso_tokens(disabled_gateway, jwt_kwargs):
    """Scoped API tokens and SSO session tokens read features.a2a from /auth/email/me."""
    _admin, _anonymous, _user, client_for = disabled_gateway
    response = client_for(**jwt_kwargs).get("/auth/email/me")
    assert response.status_code == 200, response.text
    assert response.json()["features"] == {"a2a": False}
