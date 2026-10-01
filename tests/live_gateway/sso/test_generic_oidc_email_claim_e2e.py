# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/sso/test_generic_oidc_email_claim_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

E2E tests for the email claim of generic OIDC SSO providers.

The local user record is keyed on email, and authenticate_or_create_user() refuses
an identity without one. The generic-OIDC branch of SSOService._normalize_user_info()
read only the ``email`` claim, so a provider that does not release it (an IdP whose
``email`` scope is not granted to the client) failed every login with
``user_creation_failed`` after a successful token exchange. The fix resolves the
email from ``provider_metadata["email_claim"]`` when configured, otherwise from the
first of email, preferred_username, upn, unique_name and mail that contains ``@``.

This suite runs the real browser flow against a Keycloak-backed gateway:
/auth/sso/login/{id} -> Keycloak login form -> /auth/sso/callback/{id}. A generic
provider (``provider_type=oidc``) is registered against the Keycloak realm, and the
realm's ``email`` client scope is removed from the mcp-gateway client for the
duration of the fallback tests, so Keycloak really omits the ``email`` claim.

Requirements:
    - ContextForge running with SSO_ENABLED=true, RATE_LIMITING_ENABLED=false and SECURE_COOKIES=false
      (the docker-compose defaults). The /auth/sso/* endpoints are limited to 10 requests per minute when
      rate limiting is on, which this suite exceeds. The SSO session-binding cookie is marked Secure when
      SECURE_COOKIES is true, so it is not sent back over plain http and every callback fails.
    - Keycloak with the mcp-gateway realm imported (default: http://localhost:8180)
    - The mcp-gateway client must have the ``email`` client scope as a default scope (the realm
      export does). The suite skips itself if it does not, rather than guess how to restore it.
    - playwright installed: pip install playwright

Usage:
    pytest tests/live_gateway/sso/test_generic_oidc_email_claim_e2e.py -v -s --tb=short
"""

# Future
from __future__ import annotations

# Standard
from contextlib import suppress
import html
import logging
import os
import re
from typing import Any, Generator
from urllib.parse import parse_qs, quote, urlparse
import uuid

# Third-Party
import httpx
import pytest

pw = pytest.importorskip("playwright", reason="playwright is not installed – pip install playwright")
# Third-Party
from playwright.sync_api import APIRequestContext, Playwright  # noqa: E402

# Local
from ..helpers.mcp_test_helpers import BASE_URL, JWT_SECRET, skip_no_gateway  # noqa: E402
from tests.helpers.auth import make_playwright_api_context, make_test_jwt  # noqa: E402

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.e2e, skip_no_gateway]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8180")
KEYCLOAK_INTERNAL_URL = os.getenv("KEYCLOAK_INTERNAL_URL", "http://keycloak:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "mcp-gateway")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "mcp-gateway")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "keycloak-dev-secret")  # pragma: allowlist secret — e2e Keycloak fixture, not a real credential
KEYCLOAK_ADMIN_USER = os.getenv("KEYCLOAK_ADMIN", "admin")
KEYCLOAK_ADMIN_PASSWORD = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "changeme")  # pragma: allowlist secret — e2e Keycloak fixture, not a real credential
KEYCLOAK_TEST_PASSWORD = "changeme"  # pragma: allowlist secret — password given to the users this suite creates
# The browser-facing origin the gateway registers as its OAuth redirect URI. It must be an origin the
# gateway allows (ALLOWED_ORIGINS) and is the one the realm export whitelists for the mcp-gateway client.
GATEWAY_PUBLIC_URL = os.getenv("GATEWAY_PUBLIC_URL", "http://localhost:8080")

# The gateway calls Keycloak's token, userinfo and jwks endpoints itself, so those use the internal URL;
# only the authorization endpoint is opened by the "browser" (this test).
KEYCLOAK_ISSUER = f"{KEYCLOAK_INTERNAL_URL}/realms/{KEYCLOAK_REALM}"
KEYCLOAK_AUTH_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/auth"
KEYCLOAK_TOKEN_URL = f"{KEYCLOAK_ISSUER}/protocol/openid-connect/token"
KEYCLOAK_USERINFO_URL = f"{KEYCLOAK_ISSUER}/protocol/openid-connect/userinfo"
KEYCLOAK_JWKS_URL = f"{KEYCLOAK_ISSUER}/protocol/openid-connect/certs"
# The test process reaches Keycloak through its public URL (the internal one is a docker-network name).
KEYCLOAK_PUBLIC_TOKEN_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
KEYCLOAK_PUBLIC_USERINFO_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/userinfo"

GENERIC_PROVIDER_ID = "oidc-email-claim-e2e"
PINNED_PROVIDER_ID = "oidc-email-claim-pinned-e2e"
PREFIX = "e2e-email-claim"


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------
def _keycloak_reachable() -> bool:
    try:
        resp = httpx.get(f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/.well-known/openid-configuration", timeout=5)
        return resp.status_code == 200
    except Exception as exc:
        # Standard
        import warnings

        warnings.warn(f"_keycloak_reachable probe failed: {type(exc).__name__}: {exc}", stacklevel=2)
        return False


skip_no_keycloak = pytest.mark.skipif(not _keycloak_reachable(), reason=f"Keycloak not reachable at {KEYCLOAK_URL}")
pytestmark.append(skip_no_keycloak)


# ---------------------------------------------------------------------------
# Keycloak admin helpers
# ---------------------------------------------------------------------------
class _KeycloakAdmin:
    """Thin Keycloak admin API client scoped to the mcp-gateway realm and client."""

    def __init__(self) -> None:
        resp = httpx.post(
            f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
            data={"grant_type": "password", "client_id": "admin-cli", "username": KEYCLOAK_ADMIN_USER, "password": KEYCLOAK_ADMIN_PASSWORD},
            timeout=10,
        )
        assert resp.status_code == 200, f"Keycloak admin login failed: {resp.status_code} {resp.text}"
        self.headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        self.base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
        clients = self.get("/clients", params={"clientId": KEYCLOAK_CLIENT_ID})
        assert clients and isinstance(clients, list), f"Keycloak client {KEYCLOAK_CLIENT_ID} not found"
        self.client_uuid = clients[0]["id"]

    def get(self, path: str, **kwargs: Any) -> Any:
        resp = httpx.get(f"{self.base}{path}", headers=self.headers, timeout=10, **kwargs)
        assert resp.status_code == 200, f"GET {path} failed: {resp.status_code} {resp.text}"
        return resp.json()

    def send(self, method: str, path: str, expected: tuple[int, ...] = (200, 201, 204), **kwargs: Any) -> httpx.Response:
        resp = httpx.request(method, f"{self.base}{path}", headers=self.headers, timeout=10, **kwargs)
        assert resp.status_code in expected, f"{method} {path} failed: {resp.status_code} {resp.text}"
        return resp

    def email_scope_is_default(self) -> bool:
        return any(s["name"] == "email" for s in self.get(f"/clients/{self.client_uuid}/default-client-scopes"))

    def _email_scope_id(self) -> str:
        return next(s["id"] for s in self.get("/client-scopes") if s["name"] == "email")

    def remove_email_default_scope(self) -> None:
        self.send("DELETE", f"/clients/{self.client_uuid}/default-client-scopes/{self._email_scope_id()}")

    def restore_email_default_scope(self) -> None:
        self.send("PUT", f"/clients/{self.client_uuid}/default-client-scopes/{self._email_scope_id()}")

    def add_redirect_uris(self, uris: list[str]) -> None:
        client = self.get(f"/clients/{self.client_uuid}")
        client["redirectUris"] = sorted(set(client.get("redirectUris", [])) | set(uris))
        self.send("PUT", f"/clients/{self.client_uuid}", json=client)

    def remove_redirect_uris(self, uris: list[str]) -> None:
        client = self.get(f"/clients/{self.client_uuid}")
        client["redirectUris"] = [u for u in client.get("redirectUris", []) if u not in uris]
        self.send("PUT", f"/clients/{self.client_uuid}", json=client)

    def create_user(self, username: str, email: str) -> str:
        resp = self.send(
            "POST",
            "/users",
            json={
                "username": username,
                "email": email,
                "emailVerified": True,
                "enabled": True,
                "firstName": "E2E",
                "lastName": "EmailClaim",
                "credentials": [{"type": "password", "value": KEYCLOAK_TEST_PASSWORD, "temporary": False}],
            },
        )
        return resp.headers["Location"].rsplit("/", 1)[-1]

    def delete_user(self, user_id: str) -> None:
        self.send("DELETE", f"/users/{user_id}", expected=(200, 204, 404))


def _callback_uri(provider_id: str) -> str:
    return f"{GATEWAY_PUBLIC_URL}/auth/sso/callback/{provider_id}"


def _userinfo_claims(username: str) -> dict[str, Any]:
    """Claims Keycloak releases to the mcp-gateway client for ``username`` -- the same request the gateway makes."""
    token = httpx.post(
        KEYCLOAK_PUBLIC_TOKEN_URL,
        data={
            "grant_type": "password",
            "client_id": KEYCLOAK_CLIENT_ID,
            "client_secret": KEYCLOAK_CLIENT_SECRET,
            "username": username,
            "password": KEYCLOAK_TEST_PASSWORD,
            "scope": "openid profile",
        },
        timeout=10,
    )
    assert token.status_code == 200, f"Keycloak token request failed: {token.status_code} {token.text}"
    info = httpx.get(KEYCLOAK_PUBLIC_USERINFO_URL, headers={"Authorization": f"Bearer {token.json()['access_token']}"}, timeout=10)
    assert info.status_code == 200, f"Keycloak userinfo failed: {info.status_code} {info.text}"
    return info.json()


def _page_text(resp: httpx.Response) -> str:
    """Visible text of a Keycloak HTML page, so a rejected login shows Keycloak's own error message."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", resp.text)).strip()[-300:]


class _LoginResult:
    def __init__(self, location: str, cookie_names: set[str]):
        self.location = location
        self.cookie_names = cookie_names

    @property
    def succeeded(self) -> bool:
        return "error=" not in self.location and self.location.startswith("/admin") and "jwt_token" in self.cookie_names


def _browser_login(provider_id: str, username: str) -> _LoginResult:
    """Run the authorization-code flow like a browser would and return where the gateway callback redirects."""
    with httpx.Client(follow_redirects=False, timeout=15) as gateway, httpx.Client(follow_redirects=False, timeout=15) as keycloak:
        start = gateway.get(f"{BASE_URL}/auth/sso/login/{provider_id}", params={"redirect_uri": _callback_uri(provider_id)})
        assert start.status_code == 200, f"SSO login initiation failed: {start.status_code} {start.text}"
        assert "sso_session_id" in gateway.cookies, "The login route must set the sso_session_id binding cookie"

        form = keycloak.get(start.json()["authorization_url"])
        assert form.status_code == 200, f"Keycloak did not show a login form: {form.status_code} {_page_text(form)}"
        action = re.search(r'<form[^>]*\baction="([^"]+)"', form.text)
        assert action, "Keycloak login form not found"
        # Keycloak marks its login-session cookies Secure. A browser still sends them to http://localhost, but an
        # RFC 6265 cookie jar does not, so send them explicitly.
        session_cookies = "; ".join(f"{c.name}={c.value}" for c in keycloak.cookies.jar)
        submitted = keycloak.post(html.unescape(action.group(1)), data={"username": username, "password": KEYCLOAK_TEST_PASSWORD}, headers={"Cookie": session_cookies})
        assert submitted.status_code == 302, f"Keycloak login was not accepted: {submitted.status_code} {_page_text(submitted)}"
        callback = urlparse(submitted.headers["location"])
        assert callback.path.endswith(f"/auth/sso/callback/{provider_id}"), f"Unexpected Keycloak redirect: {submitted.headers['location']}"
        assert parse_qs(callback.query).get("code"), f"Keycloak redirect carries no authorization code: {submitted.headers['location']}"

        finished = gateway.get(f"{BASE_URL}{callback.path}?{callback.query}")
        assert finished.status_code == 302, f"SSO callback should redirect, got {finished.status_code}: {finished.text[:300]}"
        return _LoginResult(finished.headers["location"], set(gateway.cookies.keys()))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def keycloak_admin() -> _KeycloakAdmin:
    return _KeycloakAdmin()


@pytest.fixture(scope="module")
def admin_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Admin API context using a gateway-issued JWT."""
    ctx = make_playwright_api_context(playwright, BASE_URL, make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=JWT_SECRET))
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="module")
def keycloak_redirect_uris(keycloak_admin: _KeycloakAdmin) -> Generator[None, None, None]:
    """Register the callback URLs of the providers this suite creates on the mcp-gateway client."""
    uris = [_callback_uri(GENERIC_PROVIDER_ID), _callback_uri(PINNED_PROVIDER_ID)]
    keycloak_admin.add_redirect_uris(uris)
    yield
    with suppress(Exception):
        _KeycloakAdmin().remove_redirect_uris(uris)


@pytest.fixture(scope="class")
def email_scope_removed(keycloak_admin: _KeycloakAdmin) -> Generator[None, None, None]:
    """Remove the ``email`` scope from the client's default scopes for one test class, then put it back."""
    if not keycloak_admin.email_scope_is_default():
        pytest.skip(
            f"The {KEYCLOAK_CLIENT_ID} client has no default 'email' scope, so the suite cannot restore it afterwards. "
            "If an earlier run was interrupted, add the 'email' client scope back to the client's default scopes."
        )
    keycloak_admin.remove_email_default_scope()
    yield
    # The admin token from setup may have expired; log in again.
    _KeycloakAdmin().restore_email_default_scope()


def _provider_fixture(provider_id: str, provider_metadata: dict[str, Any]):
    @pytest.fixture(scope="module")
    def fixture(admin_api: APIRequestContext, keycloak_redirect_uris: None) -> Generator[str, None, None]:
        # A leftover from an interrupted run would make the create below fail with a conflict.
        admin_api.delete(f"/auth/sso/admin/providers/{provider_id}")
        resp = admin_api.post(
            "/auth/sso/admin/providers",
            data={
                "id": provider_id,
                "name": provider_id,
                "display_name": provider_id,
                "provider_type": "oidc",
                "client_id": KEYCLOAK_CLIENT_ID,
                "client_secret": KEYCLOAK_CLIENT_SECRET,
                "authorization_url": KEYCLOAK_AUTH_URL,
                "token_url": KEYCLOAK_TOKEN_URL,
                "userinfo_url": KEYCLOAK_USERINFO_URL,
                "issuer": KEYCLOAK_ISSUER,
                "jwks_uri": KEYCLOAK_JWKS_URL,
                "scope": "openid profile",
                "auto_create_users": True,
                "provider_metadata": provider_metadata,
            },
        )
        assert resp.status in (200, 201), f"Failed to create generic OIDC provider {provider_id}: {resp.status} {resp.text()}"
        yield provider_id
        with suppress(Exception):
            admin_api.delete(f"/auth/sso/admin/providers/{provider_id}")

    return fixture


generic_provider = _provider_fixture(GENERIC_PROVIDER_ID, {})
# email_claim names a claim Keycloak never releases: the operator's explicit choice must win over the conventional fallbacks.
pinned_provider = _provider_fixture(PINNED_PROVIDER_ID, {"email_claim": "corp_mail"})


@pytest.fixture
def keycloak_user(keycloak_admin: _KeycloakAdmin) -> Generator[Any, None, None]:
    """Factory for a Keycloak user that is deleted, together with its gateway record, after the test."""
    created: list[str] = []

    def make(username: str, email: str) -> None:
        created.append(keycloak_admin.create_user(username, email))

    yield make
    for user_id in created:
        with suppress(Exception):
            keycloak_admin.delete_user(user_id)


@pytest.fixture
def gateway_user_cleanup(admin_api: APIRequestContext) -> Generator[list[str], None, None]:
    """Emails whose gateway user record is deleted after the test."""
    emails: list[str] = []
    yield emails
    for email in emails:
        with suppress(Exception):
            admin_api.delete(f"/auth/email/admin/users/{quote(email)}")


def _gateway_user(admin_api: APIRequestContext, email: str) -> dict[str, Any] | None:
    resp = admin_api.get(f"/auth/email/admin/users/{quote(email)}")
    if resp.status == 404:
        return None
    assert resp.status == 200, f"Unexpected status reading gateway user {email}: {resp.status} {resp.text()}"
    return resp.json()


def _unique(kind: str) -> str:
    return f"{PREFIX}-{kind}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("email_scope_removed")
class TestGenericOidcWithoutEmailClaim:
    """Keycloak withholds the ``email`` claim (the client has no ``email`` scope)."""

    def test_precondition_keycloak_omits_email_claim(self, keycloak_user):
        """Positive control: without it the tests below could pass for a reason unrelated to the fix."""
        username = f"{_unique('probe')}@example.com"
        keycloak_user(username, username)
        claims = _userinfo_claims(username)
        assert "email" not in claims, f"Keycloak must not release an email claim in this fixture, got {sorted(claims)}"
        assert claims["preferred_username"] == username

    def test_login_provisions_user_from_preferred_username(self, admin_api, generic_provider, keycloak_user, gateway_user_cleanup):
        """The login succeeds and the local user is keyed on the address in preferred_username."""
        email = f"{_unique('alt')}@example.com"
        gateway_user_cleanup.append(email)
        keycloak_user(email, email)

        result = _browser_login(generic_provider, email)

        assert result.succeeded, f"Login without an email claim should succeed, redirected to {result.location} with cookies {sorted(result.cookie_names)}"
        user = _gateway_user(admin_api, email)
        assert user is not None, "The gateway user must be keyed on the preferred_username address"
        assert user["auth_provider"] == generic_provider
        assert user["is_admin"] is False

    def test_username_without_address_is_denied(self, admin_api, generic_provider, keycloak_user, gateway_user_cleanup):
        """No claim holds an address: the login fails closed and no user is created."""
        username = _unique("plain")
        email = f"{username}@example.com"
        gateway_user_cleanup.append(email)
        keycloak_user(username, email)

        result = _browser_login(generic_provider, username)

        assert not result.succeeded
        assert result.location.endswith("/admin/login?error=user_creation_failed"), f"Expected the user_creation_failed redirect, got {result.location}"
        assert "jwt_token" not in result.cookie_names, "A denied login must not set the auth cookie"
        assert _gateway_user(admin_api, email) is None, "A denied login must not create the user under the withheld address"
        assert _gateway_user(admin_api, username) is None, "A bare username must never become a user identity"

    def test_configured_email_claim_is_authoritative(self, admin_api, pinned_provider, keycloak_user, gateway_user_cleanup):
        """email_claim names a claim that is absent: the address in preferred_username must not be used instead."""
        email = f"{_unique('pinned')}@example.com"
        gateway_user_cleanup.append(email)
        keycloak_user(email, email)

        result = _browser_login(pinned_provider, email)

        assert not result.succeeded
        assert result.location.endswith("/admin/login?error=user_creation_failed"), f"Expected the user_creation_failed redirect, got {result.location}"
        assert _gateway_user(admin_api, email) is None, "A configured email_claim must not fall back to other claims"


class TestGenericOidcWithEmailClaim:
    """Regression control: when Keycloak does release ``email``, it still wins over the fallbacks."""

    def test_email_claim_takes_precedence_over_preferred_username(self, admin_api, keycloak_admin, generic_provider, keycloak_user, gateway_user_cleanup):
        assert keycloak_admin.email_scope_is_default(), "The email scope must be back in the client's default scopes before this test"
        uid = uuid.uuid4().hex[:8]
        username = f"{PREFIX}-pref-{uid}@example.com"
        email = f"{PREFIX}-real-{uid}@example.com"
        gateway_user_cleanup.extend([username, email])
        keycloak_user(username, email)

        result = _browser_login(generic_provider, username)

        assert result.succeeded, f"Login with an email claim should succeed, redirected to {result.location}"
        user = _gateway_user(admin_api, email)
        assert user is not None and user["auth_provider"] == generic_provider, "The user must be keyed on the email claim"
        assert _gateway_user(admin_api, username) is None, "preferred_username must not be used when an email claim exists"
