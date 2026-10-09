# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/sso/test_sso_user_provisioning_api.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box SSO provisioning checks against an externally started gateway.

SSO_PROVISIONING_TEST_MODE=enabled requires the endpoint and fails if absent;
disabled requires it absent; auto skips cases incompatible with the running
configuration. No IdP login or external IdP service is needed.
"""

# Standard
import os
from urllib.parse import quote
from uuid import uuid4

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]
PATH = "/v1/admin/users/sso"


@pytest.fixture(scope="module")
def admin_client():
    """Authenticate API calls using the stack's configured platform administrator."""
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
    with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30) as client:
        yield client


@pytest.fixture(scope="module")
def provisioning_enabled(admin_client):
    """Probe registration without swallowing authentication or expected-mode failures."""
    mode = os.getenv("SSO_PROVISIONING_TEST_MODE", "auto")
    assert mode in {"auto", "enabled", "disabled"}, "SSO_PROVISIONING_TEST_MODE must be auto, enabled, or disabled"
    response = admin_client.get("/openapi.json")
    assert response.status_code == 200, response.text
    enabled = PATH in response.json()["paths"]
    if mode != "auto":
        assert enabled == (mode == "enabled"), f"Provisioning registration does not match requested {mode} configuration"
    return enabled


@pytest.fixture(scope="module")
def provider(admin_client, provisioning_enabled):
    """Create and remove an enabled configured provider through the existing API."""
    if not provisioning_enabled:
        pytest.skip("SSO provisioning is not enabled on this gateway")
    provider_id = f"provisioning-{uuid4().hex[:12]}"
    response = admin_client.post(
        "/v1/auth/sso/admin/providers",
        json={
            "id": provider_id,
            "name": provider_id,
            "display_name": "Provisioning test provider",
            "provider_type": "oidc",
            "client_id": "provisioning-test-client",
            "client_secret": "provisioning-test-value",  # pragma: allowlist secret
            "authorization_url": "https://example.com/authorize",
            "token_url": "https://example.com/token",
            "userinfo_url": "https://example.com/userinfo",
            "auto_create_users": False,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_enabled"] is True
    try:
        yield provider_id
    finally:
        response = admin_client.delete(f"/v1/auth/sso/admin/providers/{provider_id}")
        assert response.status_code == 200, response.text


@pytest.fixture
def created_users(admin_client):
    """Remove only users uniquely created by the current test."""
    emails: list[str] = []
    yield emails
    for email in emails:
        response = admin_client.delete(f"/v1/auth/email/admin/users/{quote(email, safe='')}")
        assert response.status_code in {200, 204, 404}, response.text


def test_disabled_post_before_auth_or_parsing(provisioning_enabled):
    """Default/disabled configuration hides POST independently of credentials and body."""
    if provisioning_enabled:
        pytest.skip("This case requires a disabled provisioning configuration")
    for headers in ({}, {"Authorization": "Bearer invalid"}, {"Cookie": "jwt_token=invalid"}):
        for body in (b"{", b'{"password":null}', b"[]"):
            response = httpx.post(f"{BASE_URL}{PATH}", content=body, headers=headers, timeout=10)
            assert response.status_code == 404
            assert response.json() == {"detail": "Not Found"}


def test_create_duplicate_and_password_login(admin_client, provider, created_users):
    """A real service creates passwordless users and leaves duplicate targets unchanged."""
    email = f"provisioning-{uuid4().hex}@example.com"
    response = admin_client.post(PATH, json={"email": email, "auth_provider": provider, "full_name": "Provisioned User"})
    assert response.status_code == 201, response.text
    created_users.append(email)
    user = response.json()
    assert user["auth_provider"] == provider
    assert user["is_admin"] is False
    assert user["email_verified"] is False
    assert user["password_change_required"] is False
    assert "password_hash" not in user
    response = admin_client.post(PATH, json={"email": email, "auth_provider": provider, "is_admin": True, "full_name": "Changed"})
    assert response.status_code == 409, response.text
    response = admin_client.get(f"/v1/auth/email/admin/users/{quote(email, safe='')}")
    assert response.status_code == 200, response.text
    assert response.json() == user
    response = httpx.post(f"{BASE_URL}/v1/auth/email/login", json={"email": email, "password": "NoLocalPassword!9"}, timeout=30)  # pragma: allowlist secret
    assert response.status_code in {401, 403}, response.text


def test_enabled_deny_paths(admin_client, provider):
    """Registered provisioning rejects anonymous, scoped, CSRF, and password requests."""
    payload = {"email": f"denied-{uuid4().hex}@example.com", "auth_provider": provider}
    response = httpx.post(f"{BASE_URL}{PATH}", json=payload, timeout=10)
    assert response.status_code == 401, response.text
    restricted = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, scopes={"permissions": ["tools.read"]}, secret=JWT_SECRET)
    response = httpx.post(f"{BASE_URL}{PATH}", json=payload, headers={"Authorization": f"Bearer {restricted}"}, timeout=10)
    assert response.status_code == 403, response.text
    response = admin_client.post(PATH, json={**payload, "password": None})
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "password not allowed for SSO users"
    # Cookie auth with a valid admin identity must still satisfy the per-route CSRF dependency.
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET, extra_payload={"token_use": "session"})
    response = httpx.post(
        f"{BASE_URL}{PATH}",
        content=b"{",
        headers={
            "Cookie": f"jwt_token={token}",
            "Content-Type": "text/plain",
            "Accept": "text/html",
            "Origin": BASE_URL,
        },
        timeout=10,
    )
    assert response.status_code == 403, response.text
    assert "CSRF" in response.json()["detail"]


def test_non_admin_cannot_provision(admin_client, provider, created_users):
    """A provisioned ordinary user's real token cannot create an administrator."""
    email = f"nonadmin-{uuid4().hex}@example.com"
    response = admin_client.post(PATH, json={"email": email, "auth_provider": provider})
    assert response.status_code == 201, response.text
    created_users.append(email)
    token = make_test_jwt(email, teams=None, secret=JWT_SECRET, extra_payload={"token_use": "session"})
    response = httpx.post(
        f"{BASE_URL}{PATH}", json={"email": f"denied-{uuid4().hex}@example.com", "auth_provider": provider, "is_admin": True}, headers={"Authorization": f"Bearer {token}"}, timeout=10
    )
    assert response.status_code == 403, response.text
