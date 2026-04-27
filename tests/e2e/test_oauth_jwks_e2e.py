# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_oauth_jwks_e2e.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

E2E tests for OAuth access token verification via JWKS on virtual server MCP endpoints.

Exercises the issuer-based token routing in _auth_jwt() and the JWKS verification flow
in _try_oauth_access_token() / verify_oauth_access_token() against a real ContextForge +
Keycloak docker-compose stack.

Requirements:
    - ContextForge running with docker-compose --profile sso (default: http://localhost:8080)
    - Keycloak running (default: http://localhost:8180) with mcp-gateway realm imported
    - playwright installed: pip install playwright

Usage:
    docker compose --profile sso up -d
    pytest tests/e2e/test_oauth_jwks_e2e.py -v -s --tb=short
"""

# Future
from __future__ import annotations

# Standard
from contextlib import suppress
import logging
import os
from typing import Any, Generator
import uuid

# Third-Party
import pytest

pw = pytest.importorskip("playwright", reason="playwright is not installed – pip install playwright")
# Third-Party
from playwright.sync_api import APIRequestContext, Playwright  # noqa: E402

# First-Party
from mcpgateway.utils.create_jwt_token import _create_jwt_token  # noqa: E402

# Local
from .helpers.mcp_test_helpers import BASE_URL, JWT_SECRET, skip_no_gateway, TEST_PASSWORD  # noqa: E402

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.e2e, skip_no_gateway]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8180")
KEYCLOAK_INTERNAL_URL = os.getenv("KEYCLOAK_INTERNAL_URL", "http://keycloak:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "mcp-gateway")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "mcp-gateway")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "keycloak-dev-secret")
# Issuer in JWTs depends on how Keycloak is accessed. When accessed via docker-internal
# URL (keycloak:8080), the issuer matches what the gateway can reach for OIDC discovery.
KEYCLOAK_ISSUER = f"{KEYCLOAK_INTERNAL_URL}/realms/{KEYCLOAK_REALM}"
KEYCLOAK_TOKEN_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
KEYCLOAK_TEST_USER = "admin@example.com"
KEYCLOAK_TEST_PASSWORD = "changeme"  # pragma: allowlist secret — e2e Keycloak fixture, not a real credential
OAUTH_PREFIX = "oauth-jwks"
# Shared with the rest of the e2e suite so this test can't drift from the
# gateway's ≥32-char JWT_SECRET_KEY minimum; overriding via the env var
# still works for non-default deployments.
_JWT_SECRET = JWT_SECRET


# ---------------------------------------------------------------------------
# Skip condition: Keycloak must be reachable
# ---------------------------------------------------------------------------
def _keycloak_reachable() -> bool:
    try:
        # Third-Party
        import httpx

        resp = httpx.get(f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/.well-known/openid-configuration", timeout=5)
        return resp.status_code == 200
    except Exception as exc:
        # Surface the real reason so a missing dependency (e.g. httpx not
        # installed in CI) or a config error is not silently hidden as
        # "Keycloak not reachable".
        # Standard
        import warnings

        warnings.warn(f"_keycloak_reachable probe failed: {type(exc).__name__}: {exc}", stacklevel=2)
        return False


skip_no_keycloak = pytest.mark.skipif(not _keycloak_reachable(), reason=f"Keycloak not reachable at {KEYCLOAK_URL}")
pytestmark.append(skip_no_keycloak)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_jwt(email: str, is_admin: bool = False, teams=None) -> str:
    return _create_jwt_token(
        {"sub": email},
        user_data={"email": email, "is_admin": is_admin, "auth_provider": "local"},
        teams=teams,
        secret=_JWT_SECRET,
    )


def _api_context(playwright: Playwright, token: str) -> APIRequestContext:
    return playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )


def _get_keycloak_token(email: str, password: str = KEYCLOAK_TEST_PASSWORD) -> str:
    """Obtain an access token from Keycloak via Resource Owner Password Credentials grant.

    Uses docker exec to request the token from inside the docker network so that the
    JWT issuer claim matches the internal URL (keycloak:8080) that the gateway can reach
    for OIDC discovery. Falls back to the external URL if docker exec fails.
    """
    # Standard
    import subprocess

    # Request token from inside the gateway container so issuer = keycloak:8080
    cmd = [
        "docker",
        "compose",
        "exec",
        "-T",
        "gateway",
        "curl",
        "-sf",
        "-X",
        "POST",
        f"{KEYCLOAK_INTERNAL_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token",
        "-d",
        f"grant_type=password&client_id={KEYCLOAK_CLIENT_ID}&client_secret={KEYCLOAK_CLIENT_SECRET}" f"&username={email}&password={password}&scope=openid+profile+email",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
    if result.returncode == 0 and result.stdout.strip():
        # Standard
        import json

        data = json.loads(result.stdout)
        token = data.get("access_token")
        if token:
            return token

    # Fallback: request from host (issuer may differ)
    # Third-Party
    import httpx

    resp = httpx.post(
        KEYCLOAK_TOKEN_URL,
        data={
            "grant_type": "password",
            "client_id": KEYCLOAK_CLIENT_ID,
            "client_secret": KEYCLOAK_CLIENT_SECRET,
            "username": email,
            "password": password,
            "scope": "openid profile email",
        },
        timeout=10,
    )
    assert resp.status_code == 200, f"Keycloak token request failed: {resp.status_code} {resp.text}"
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def admin_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Admin API context using CF-issued JWT."""
    token = _make_jwt(KEYCLOAK_TEST_USER, is_admin=True)
    ctx = _api_context(playwright, token)
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="module")
def cf_test_user(admin_api: APIRequestContext) -> str:
    """Ensure the Keycloak test user exists in ContextForge DB."""
    email = KEYCLOAK_TEST_USER
    resp = admin_api.post(
        "/auth/email/admin/users",
        data={
            "email": email,
            "password": TEST_PASSWORD,
            "full_name": "OAuth JWKS Test User",
            "is_admin": False,
            "is_active": True,
            "password_change_required": False,
        },
    )
    if resp.status not in (200, 201, 409):
        pytest.fail(f"Failed to create CF user {email}: {resp.status} {resp.text()}")
    logger.info("CF user %s ready", email)
    return email


@pytest.fixture(scope="module")
def oauth_server(admin_api: APIRequestContext) -> Generator[dict[str, Any], None, None]:
    """Create a virtual server with oauth_enabled=True pointing to Keycloak."""
    uid = uuid.uuid4().hex[:8]
    name = f"{OAUTH_PREFIX}-server-{uid}"
    payload = {
        "server": {
            "name": name,
            "description": "OAuth JWKS E2E test server",
            "oauth_enabled": True,
            "oauth_config": {
                "authorization_servers": [KEYCLOAK_ISSUER],
                # Keycloak's default access tokens put the client_id (and
                # "account") in the aud claim, not the MCP resource URL.
                # Declaring it here as an extra accepted audience lets the
                # enforced aud check pass without requiring a custom
                # Keycloak audience mapper for the E2E stack.
                "client_id": KEYCLOAK_CLIENT_ID,
            },
        },
        "visibility": "public",
    }
    resp = admin_api.post("/servers", data=payload)
    assert resp.status in (200, 201), f"Failed to create OAuth server: {resp.status} {resp.text()}"
    server = resp.json()
    logger.info("Created OAuth server: %s (id=%s)", name, server["id"])

    yield {"id": server["id"], "name": name}

    with suppress(Exception):
        admin_api.delete(f"/servers/{server['id']}")


@pytest.fixture(scope="module")
def non_oauth_server(admin_api: APIRequestContext) -> Generator[dict[str, Any], None, None]:
    """Create a virtual server WITHOUT oauth_enabled."""
    uid = uuid.uuid4().hex[:8]
    name = f"{OAUTH_PREFIX}-no-oauth-{uid}"
    payload = {
        "server": {
            "name": name,
            "description": "Non-OAuth E2E test server",
        },
        "visibility": "public",
    }
    resp = admin_api.post("/servers", data=payload)
    assert resp.status in (200, 201), f"Failed to create non-OAuth server: {resp.status} {resp.text()}"
    server = resp.json()
    logger.info("Created non-OAuth server: %s (id=%s)", name, server["id"])

    yield {"id": server["id"], "name": name}

    with suppress(Exception):
        admin_api.delete(f"/servers/{server['id']}")


@pytest.fixture(scope="module")
def wrong_issuer_server(admin_api: APIRequestContext) -> Generator[dict[str, Any], None, None]:
    """Create a virtual server with oauth_enabled but a different issuer allowlist."""
    uid = uuid.uuid4().hex[:8]
    name = f"{OAUTH_PREFIX}-wrong-issuer-{uid}"
    payload = {
        "server": {
            "name": name,
            "description": "OAuth server with wrong issuer",
            "oauth_enabled": True,
            "oauth_config": {
                "authorization_servers": ["https://other-idp.example.com"],
            },
        },
        "visibility": "public",
    }
    resp = admin_api.post("/servers", data=payload)
    assert resp.status in (200, 201), f"Failed to create wrong-issuer server: {resp.status} {resp.text()}"
    server = resp.json()
    logger.info("Created wrong-issuer server: %s (id=%s)", name, server["id"])

    yield {"id": server["id"], "name": name}

    with suppress(Exception):
        admin_api.delete(f"/servers/{server['id']}")


# ---------------------------------------------------------------------------
# MCP JSON-RPC helper
# ---------------------------------------------------------------------------
_INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "method": "initialize",
    "id": 1,
    "params": {
        "capabilities": {},
        "protocolVersion": "2025-03-26",
        "clientInfo": {"name": "oauth-jwks-test", "version": "1.0"},
    },
}


def _mcp_request(playwright: Playwright, server_id: str, token: str) -> int:
    """Send an MCP initialize request to a virtual server and return the HTTP status code."""
    ctx = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        resp = ctx.post(f"/servers/{server_id}/mcp", data=_INITIALIZE_REQUEST)
        return resp.status
    finally:
        ctx.dispose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestOAuthJWKSVerification:
    """E2E tests for OAuth access token verification via JWKS."""

    def test_valid_keycloak_jwt_accepted(self, playwright: Playwright, oauth_server: dict, cf_test_user: str):
        """Valid Keycloak JWT on oauth_enabled server is accepted."""
        kc_token = _get_keycloak_token(cf_test_user)
        status = _mcp_request(playwright, oauth_server["id"], kc_token)
        assert status != 401, "Valid Keycloak JWT should not be rejected"
        assert status != 403, "Valid Keycloak JWT should not be forbidden"
        logger.info("Valid Keycloak JWT accepted (status=%d)", status)

    def test_non_oauth_server_rejects_keycloak_jwt(self, playwright: Playwright, non_oauth_server: dict, cf_test_user: str):
        """Keycloak JWT on a server without oauth_enabled is rejected."""
        kc_token = _get_keycloak_token(cf_test_user)
        status = _mcp_request(playwright, non_oauth_server["id"], kc_token)
        assert status == 401, f"Non-OAuth server should reject IdP token, got {status}"

    def test_wrong_issuer_rejected(self, playwright: Playwright, wrong_issuer_server: dict, cf_test_user: str):
        """Keycloak JWT is rejected when issuer is not in the server's allowlist."""
        kc_token = _get_keycloak_token(cf_test_user)
        status = _mcp_request(playwright, wrong_issuer_server["id"], kc_token)
        assert status == 401, f"Wrong issuer should be rejected, got {status}"

    def test_invalid_token_rejected(self, playwright: Playwright, oauth_server: dict):
        """Garbage token is rejected."""
        status = _mcp_request(playwright, oauth_server["id"], "not-a-valid-jwt-token")
        assert status == 401, f"Invalid token should be rejected, got {status}"

    def test_user_not_in_cf_rejected(self, playwright: Playwright, oauth_server: dict):
        """Keycloak JWT for a user not registered in ContextForge is rejected."""
        # newuser@example.com exists in Keycloak but NOT registered in CF
        kc_token = _get_keycloak_token("newuser@example.com")
        status = _mcp_request(playwright, oauth_server["id"], kc_token)
        assert status in (401, 403), f"Unregistered user should be rejected, got {status}"
