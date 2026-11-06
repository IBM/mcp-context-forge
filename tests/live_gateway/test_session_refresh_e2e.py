# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/test_session_refresh_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Exercise session refresh over HTTP against an isolated gateway.
"""

# Standard
from collections.abc import Iterator
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from uuid import UUID

# Third-Party
import httpx
import jwt
import pytest

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", params=[("true", "true"), ("false", "false")], ids=["cached-batched", "uncached-unbatched"])
def refresh_gateway(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, str]]:
    """Run a gateway with an isolated database and generated login credentials.

    Args:
        request: Fixture parameters for authentication caching and batching.
        tmp_path_factory: Factory for isolated database and log paths.

    Yields:
        The gateway URL and the bootstrap administrator password.
    """
    directory = tmp_path_factory.mktemp("session-refresh-gateway")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    password = secrets.token_urlsafe(32)
    cache_enabled, batch_queries = request.param
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(_REPO_ROOT),
        "DATABASE_URL": f"sqlite:///{directory / 'gateway.db'}",
        "CACHE_TYPE": "memory",
        "REDIS_URL": "",
        "JWT_SECRET_KEY": secrets.token_urlsafe(48),
        "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
        "PLATFORM_ADMIN_EMAIL": "admin@example.com",
        "PLATFORM_ADMIN_PASSWORD": password,
        "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
        "AUTH_REQUIRED": "true",
        "REQUIRE_USER_IN_DB": "true",
        "AUTH_CACHE_ENABLED": cache_enabled,
        "AUTH_CACHE_BATCH_QUERIES": batch_queries,
        "EMAIL_AUTH_ENABLED": "true",
        "MCPGATEWAY_ADMIN_API_ENABLED": "false",
        "MCPGATEWAY_UI_ENABLED": "false",
        "MCPGATEWAY_A2A_ENABLED": "false",
        "LLMCHAT_ENABLED": "false",
        "PLUGINS_ENABLED": "false",
        "OBSERVABILITY_ENABLED": "false",
        "RATE_LIMITING_ENABLED": "false",
        "APP_DOMAIN": base_url,
        "SECURE_COOKIES": "false",
        "LOG_LEVEL": "ERROR",
    }
    log_path = directory / "gateway.log"
    with log_path.open("w") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=directory,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=base_url, timeout=15, trust_env=False) as client:
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
            yield base_url, password
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.parametrize("cookie_auth", [False, True], ids=["bearer", "cookie"])
def test_refresh_preserves_uuid_and_rotates_session(refresh_gateway: tuple[str, str], cookie_auth: bool) -> None:
    """Refresh a UUID-subject session and reject replay of its predecessor.

    Args:
        refresh_gateway: The isolated gateway URL and login password.
        cookie_auth: Use session cookies instead of a bearer header.
    """
    base_url, password = refresh_gateway
    with httpx.Client(base_url=base_url, timeout=15, trust_env=False) as client:
        login = client.post("/v1/auth/login", json={"email": "admin@example.com", "password": password})
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        csrf_token = client.cookies["mcpgateway_csrf_token"]
        original = jwt.decode(token, options={"verify_signature": False})
        assert str(UUID(original["sub"])) == original["sub"]
        client.cookies.clear()
        bearer = {"Authorization": f"Bearer {token}"}
        for _ in range(2):
            profile = client.get("/v1/auth/email/me", headers=bearer)
            assert profile.status_code == 200, profile.text
        headers = bearer
        if cookie_auth:
            client.cookies.set("jwt_token", token)
            client.cookies.set("mcpgateway_csrf_token", csrf_token)
            assert client.post("/v1/auth/refresh").status_code == 403
            headers = {"X-CSRF-Token": csrf_token, "Origin": base_url}
        refreshed = client.post("/v1/auth/refresh", headers=headers)
        assert refreshed.status_code == 200, refreshed.text
        new_token = refreshed.json()["access_token"]
        rotated = jwt.decode(new_token, options={"verify_signature": False})
        assert rotated["sub"] == original["sub"]
        assert rotated["jti"] != original["jti"]
        assert refreshed.json()["csrf_token"]
        if cookie_auth:
            assert refreshed.cookies["jwt_token"] == new_token
        client.cookies.clear()
        assert client.get("/v1/auth/validate", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200
        assert client.post("/v1/auth/refresh", headers=bearer).status_code == 401
        assert client.post("/v1/auth/refresh").status_code == 401
        assert client.post("/v1/auth/refresh", headers={"Authorization": "Bearer invalid-session"}).status_code == 401
