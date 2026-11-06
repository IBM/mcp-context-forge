# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/test_oauth_token_retrieval.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box OAuth token retrieval checks against isolated gateway processes.
"""

# Standard
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
from sqlalchemy import select

# First-Party
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEAM = "oauth-retrieval-team"
_GATEWAY = "oauth-retrieval-gateway"


@dataclass(frozen=True, slots=True)
class TokenGateway:
    """Connection details for an isolated gateway."""

    url: str
    signing_key: str

    def headers(self, user: str, permissions: list[str] | None = None) -> dict[str, str]:
        """Create a token for a seeded user with an optional permission ceiling."""
        team = "oauth-other-team" if user == "outsider" else _TEAM
        token = make_test_jwt(
            f"{user}@example.com",
            teams=[team],
            scopes={"permissions": permissions} if permissions is not None else None,
            secret=self.signing_key,
            algorithm="HS256",
        )
        return make_auth_headers(token)


def _seed() -> None:
    """Seed users, real role assignments, and encrypted tokens in the subprocess database."""
    # First-Party
    from mcpgateway.db import EmailTeam, EmailTeamMember, EmailUser, Gateway, OAuthToken, Role, SessionLocal, UserRole

    with SessionLocal() as db:
        for user in ("owner", "other", "empty", "viewer", "platform_viewer", "team_admin", "outsider"):
            db.add(EmailUser(email=f"{user}@example.com", full_name=user, is_admin=False, is_active=True))
        db.flush()
        for team in (_TEAM, "oauth-other-team"):
            db.add(EmailTeam(id=team, name=team, slug=team, created_by="owner@example.com"))
        db.flush()
        for user in ("owner", "other", "empty", "viewer", "platform_viewer", "team_admin", "outsider"):
            team = "oauth-other-team" if user == "outsider" else _TEAM
            email = f"{user}@example.com"
            role_name = user if user in {"viewer", "platform_viewer", "team_admin"} else "developer"
            role = db.execute(select(Role).where(Role.name == role_name, Role.is_active.is_(True))).scalar_one()
            db.add(EmailTeamMember(team_id=team, user_email=email, role="member"))
            db.add(UserRole(user_email=email, role_id=role.id, scope=role.scope, scope_id=team if role.scope == "team" else None, granted_by="admin@example.com"))
        db.add(
            Gateway(
                id=_GATEWAY,
                name="OAuth retrieval",
                slug="oauth-retrieval",
                url="https://provider.example/mcp",
                capabilities={},
                enabled=False,
                auth_type="oauth",
                oauth_config={"grant_type": "authorization_code", "client_id": "test-client"},
                team_id=_TEAM,
                owner_email="owner@example.com",
                visibility="team",
            )
        )
        db.flush()
        for user in ("owner", "other", "viewer", "platform_viewer", "team_admin", "outsider"):
            db.add(
                OAuthToken(
                    gateway_id=_GATEWAY,
                    user_id=user,
                    app_user_email=f"{user}@example.com",
                    access_token=f"access-for-{user}",
                    refresh_token=f"refresh-for-{user}",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    scopes=["files.read"],
                )
            )
        db.commit()


@contextmanager
def _running_gateway(directory: Path, enabled: bool) -> Iterator[TokenGateway]:
    """Run a gateway with isolated settings, storage, and signing keys."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    signing_key = secrets.token_urlsafe(48)
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(_REPO_ROOT),
        "DATABASE_URL": f"sqlite:///{directory / 'gateway.db'}",
        "CACHE_TYPE": "memory",
        "REDIS_URL": "",
        "JWT_SECRET_KEY": signing_key,
        "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
        "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32),
        "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
        "AUTH_REQUIRED": "true",
        "REQUIRE_USER_IN_DB": "true",
        "MCPGATEWAY_ADMIN_API_ENABLED": "false",
        "MCPGATEWAY_UI_ENABLED": "false",
        "MCPGATEWAY_A2A_ENABLED": "false",
        "PLUGINS_ENABLED": "false",
        "OBSERVABILITY_ENABLED": "false",
        "OAUTH_TOKEN_RETRIEVAL_ENABLED": str(enabled).lower(),
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
            gateway = TokenGateway(f"http://127.0.0.1:{port}", signing_key)
            with httpx.Client(base_url=gateway.url, timeout=5, trust_env=False) as client:
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
            subprocess.run(
                [sys.executable, "-c", "from tests.live_gateway.test_oauth_token_retrieval import _seed; _seed()"],
                cwd=directory,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=30,
            )
            yield gateway
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.fixture(scope="module")
def token_gateway(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TokenGateway]:
    """Start the feature-enabled gateway once for the module."""
    with _running_gateway(tmp_path_factory.mktemp("oauth-token-live"), True) as gateway:
        yield gateway


def _get(gateway: TokenGateway, headers: dict[str, str] | None = None) -> httpx.Response:
    """Request the seeded gateway's token through the real HTTP middleware stack."""
    with httpx.Client(base_url=gateway.url, timeout=15, trust_env=False) as client:
        return client.get(f"/oauth/token/{_GATEWAY}", headers=headers)


def test_disabled_feature_returns_503(tmp_path: Path) -> None:
    """An authorized caller receives 503 when token retrieval is disabled."""
    with _running_gateway(tmp_path, False) as gateway:
        response = _get(gateway, gateway.headers("owner"))
    assert response.status_code == 503, response.text


def test_unauthenticated_request_is_denied(token_gateway: TokenGateway) -> None:
    """Authentication runs before token retrieval."""
    assert _get(token_gateway).status_code == 401


@pytest.mark.parametrize("user", ["owner", "other", "team_admin"])
def test_returns_only_callers_token(token_gateway: TokenGateway, user: str) -> None:
    """Each caller receives their own access token and non-sensitive metadata."""
    response = _get(token_gateway, token_gateway.headers(user))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"gateway_id", "access_token", "token_type", "expires_at", "scopes"}
    assert payload["gateway_id"] == _GATEWAY
    assert payload["access_token"] == f"access-for-{user}"
    assert payload["token_type"] == "Bearer"
    assert payload["scopes"] == ["files.read"]
    assert datetime.fromisoformat(payload["expires_at"]).replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
    assert "no-store" in response.headers["cache-control"]
    assert "refresh-for-" not in response.text


def test_missing_token_returns_404(token_gateway: TokenGateway) -> None:
    """A caller with no token cannot retrieve another user's stored token."""
    response = _get(token_gateway, token_gateway.headers("empty"))
    assert response.status_code == 404, response.text
    assert "access-for-" not in response.text


@pytest.mark.parametrize("user", ["viewer", "platform_viewer", "outsider"])
def test_viewer_and_wrong_team_are_denied(token_gateway: TokenGateway, user: str) -> None:
    """Read-only roles and other teams cannot retrieve stored tokens."""
    response = _get(token_gateway, token_gateway.headers(user))
    assert response.status_code == 403, response.text
    assert "access-for-" not in response.text


@pytest.mark.parametrize("permission", ["gateways.read", "gateways.update", "tokens.create"])
def test_unrelated_api_token_permission_is_denied(token_gateway: TokenGateway, permission: str) -> None:
    """Unrelated permissions cannot disclose a provider token."""
    response = _get(token_gateway, token_gateway.headers("owner", [permission]))
    assert response.status_code == 403, response.text
    assert "access-for-" not in response.text


def test_gateway_token_read_api_token_can_retrieve(token_gateway: TokenGateway) -> None:
    """An authorized developer can retrieve their token with a gateways.token_read API scope."""
    response = _get(token_gateway, token_gateway.headers("owner", ["gateways.token_read"]))
    assert response.status_code == 200, response.text
    assert response.json()["access_token"] == "access-for-owner"


@pytest.mark.parametrize("user", ["viewer", "platform_viewer"])
def test_viewer_cannot_elevate_permissions_with_api_token_scopes(token_gateway: TokenGateway, user: str) -> None:
    """Explicit token scopes cannot grant provider-token access to a viewer."""
    response = _get(token_gateway, token_gateway.headers(user, ["gateways.token_read"]))
    assert response.status_code == 403, response.text
    assert "access-for-" not in response.text
