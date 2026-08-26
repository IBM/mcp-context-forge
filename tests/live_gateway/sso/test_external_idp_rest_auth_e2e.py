# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/sso/test_external_idp_rest_auth_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

E2E tests for external-IdP bearer tokens on REST endpoints (issue #6396).

get_current_user() (mcpgateway/auth.py) -- the dependency behind
get_current_user_with_permissions() and therefore every REST endpoint that
uses it (/tools, /gateways, /servers, /rpc, etc.) -- only ever verified
tokens with the internal JWT secret. A bearer token from a provider with
trusted_for_api_auth=True and a matching SSO_API_TOKEN_AUTH_ENABLED was
rejected with 401 on all of these endpoints even though the external-IdP
verification path (verify_credentials_cached -> _maybe_verify_external)
worked correctly on its own. This suite exercises the fix end to end
against a real Keycloak-backed gateway: a trusted, correctly-audienced
token is accepted and correctly team-scoped on GET /tools, while an
untrusted/misconfigured token is still rejected.

Requirements:
    - ContextForge running with docker-compose --profile sso, started with
      SSO_API_TOKEN_AUTH_ENABLED=true in the environment (default: http://localhost:8080)
    - Keycloak running (default: http://localhost:8180) with the mcp-gateway realm imported
    - playwright installed: pip install playwright

Usage:
    SSO_API_TOKEN_AUTH_ENABLED=true docker compose --profile sso up -d
    pytest tests/live_gateway/sso/test_external_idp_rest_auth_e2e.py -v -s --tb=short
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

# Local
from tests.helpers.auth import make_playwright_api_context, make_test_jwt  # noqa: E402

from ..helpers.mcp_test_helpers import BASE_URL, JWT_SECRET, skip_no_gateway  # noqa: E402

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
# Matches how the gateway reaches Keycloak for OIDC discovery -- the trusted
# SSOProvider's `issuer` is derived from SSO_KEYCLOAK_BASE_URL (defaults to
# the same docker-internal URL), so tokens must be minted against that same
# issuer for resolve_trusted_provider_by_issuer() to match.
KEYCLOAK_ISSUER = f"{KEYCLOAK_INTERNAL_URL}/realms/{KEYCLOAK_REALM}"
KEYCLOAK_TOKEN_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
KEYCLOAK_TEST_PASSWORD = "changeme"  # pragma: allowlist secret — e2e Keycloak fixture, not a real credential
# Realm-seeded users (infra/keycloak/realm-export.json): viewer@example.com is a
# member of the /Viewers group, newuser@example.com belongs to no group. Reusing
# two distinct real accounts (rather than editing a single token's claims, which
# would require the realm's signing key) is how a live token-based test represents
# "group present" vs. "group absent".
KEYCLOAK_GROUP_MEMBER = os.getenv("KEYCLOAK_VIEWER_EMAIL", "viewer@example.com")
KEYCLOAK_NO_GROUP_USER = os.getenv("KEYCLOAK_NEWUSER_EMAIL", "newuser@example.com")
# Short group name as it appears in the access token's `groups` claim (the
# realm's group-membership mapper is configured with full.path=false).
KEYCLOAK_VIEWERS_GROUP = "Viewers"
# Keycloak's built-in "account" client scope adds "account" to every access
# token's `aud` claim by default, with no custom audience mapper required.
TRUSTED_PROVIDER_ID = "keycloak"
TRUSTED_API_AUDIENCE = "account"
PREFIX = "ext-idp-rest"


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------
def _keycloak_reachable() -> bool:
    try:
        # Third-Party
        import httpx

        resp = httpx.get(f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/.well-known/openid-configuration", timeout=5)
        return resp.status_code == 200
    except Exception as exc:
        # Standard
        import warnings

        warnings.warn(f"_keycloak_reachable probe failed: {type(exc).__name__}: {exc}", stacklevel=2)
        return False


def _api_token_auth_enabled() -> bool:
    """Best-effort check that the operator started the stack with the flag on.

    SSO_API_TOKEN_AUTH_ENABLED is a container-startup env var (see
    docker-compose.yml), not something a test can flip at runtime. There is
    no endpoint that reflects it back, so this reads the same env var name
    from the pytest process's own environment as a documented convention:
    export it before both `docker compose --profile sso up` and `pytest`.
    """
    return os.getenv("SSO_API_TOKEN_AUTH_ENABLED", "false").strip().lower() in ("1", "true", "yes")


skip_no_keycloak = pytest.mark.skipif(not _keycloak_reachable(), reason=f"Keycloak not reachable at {KEYCLOAK_URL}")
skip_no_api_token_auth = pytest.mark.skipif(
    not _api_token_auth_enabled(),
    reason="SSO_API_TOKEN_AUTH_ENABLED not set in the test environment — start the sso profile with SSO_API_TOKEN_AUTH_ENABLED=true and export it for pytest too",
)
pytestmark.extend([skip_no_keycloak, skip_no_api_token_auth])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_cf_jwt(email: str, is_admin: bool = False) -> str:
    # Shared with the rest of the e2e suite so this token can't drift from
    # the gateway's configured JWT_SECRET_KEY.
    return make_test_jwt(email, is_admin=is_admin, secret=JWT_SECRET)


def _api_context(playwright: Playwright, token: str) -> APIRequestContext:
    return make_playwright_api_context(playwright, BASE_URL, token)


def _get_keycloak_token(email: str, password: str = KEYCLOAK_TEST_PASSWORD) -> str:
    """Obtain an access token from Keycloak via Resource Owner Password Credentials grant.

    Requests the token from inside the gateway container so the JWT `iss` claim
    matches the internal URL (keycloak:8080) the gateway used for OIDC discovery
    when the trusted SSOProvider row was bootstrapped. Falls back to the host URL
    if docker exec is unavailable.
    """
    # Standard
    import subprocess

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

    # Fallback: request from host (issuer may differ; only useful for manual debugging)
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


def _rest_request(playwright: Playwright, path: str, token: str | None) -> Any:
    """Issue a GET request against a REST endpoint with an optional bearer token."""
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    ctx = playwright.request.new_context(base_url=BASE_URL, extra_http_headers=headers)
    try:
        return ctx.get(path)
    finally:
        ctx.dispose()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def admin_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Admin API context using a CF-issued JWT (internal path, unaffected by this fix)."""
    token = _make_cf_jwt("admin@example.com", is_admin=True)
    ctx = _api_context(playwright, token)
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="module")
def scoped_team(admin_api: APIRequestContext) -> Generator[dict[str, Any], None, None]:
    """A dedicated CF team used to prove team-scoped visibility, not just plain 200/401."""
    uid = uuid.uuid4().hex[:8]
    name = f"{PREFIX}-team-{uid}"
    resp = admin_api.post("/teams/", data={"name": name, "description": "External-IdP REST auth E2E team", "visibility": "private"})
    assert resp.status in (200, 201), f"Failed to create team: {resp.status} {resp.text()}"
    team = resp.json()
    team_id = team.get("id") or team.get("team", {}).get("id")
    logger.info("Created team: %s (id=%s)", name, team_id)

    yield {"id": team_id, "name": name}

    with suppress(Exception):
        admin_api.delete(f"/teams/{team_id}")


@pytest.fixture(scope="module")
def team_scoped_tool(admin_api: APIRequestContext, scoped_team: dict[str, Any]) -> Generator[dict[str, Any], None, None]:
    """A tool visible only to members of `scoped_team` -- proves real RBAC scoping, not a static grant."""
    uid = uuid.uuid4().hex[:8]
    name = f"{PREFIX}-tool-{uid}"
    payload = {
        "tool": {
            "name": name,
            "url": "https://example.com/healthz",
            "description": "External-IdP REST auth E2E marker tool",
            "integration_type": "REST",
            "request_type": "GET",
            "visibility": "team",
        },
        "team_id": scoped_team["id"],
    }
    resp = admin_api.post("/tools", data=payload)
    assert resp.status in (200, 201), f"Failed to create team-scoped tool: {resp.status} {resp.text()}"
    tool = resp.json()
    logger.info("Created team-scoped tool: %s (id=%s, team=%s)", name, tool["id"], scoped_team["id"])

    yield tool

    with suppress(Exception):
        admin_api.delete(f"/tools/{tool['id']}")


@pytest.fixture(scope="module")
def trusted_keycloak_provider(admin_api: APIRequestContext, scoped_team: dict[str, Any]) -> Generator[None, None, None]:
    """Opt the bootstrapped `keycloak` SSOProvider into trusted_for_api_auth for this suite.

    Restores the provider's prior trusted_for_api_auth flag on teardown. Group ->
    team mapping is dynamic (SSOService._apply_team_mapping runs on every
    authenticate_or_create_user() call, including via the external-IdP path), so
    this is also where the /Viewers -> scoped_team mapping is wired up.
    """
    original = admin_api.get(f"/auth/sso/admin/providers/{TRUSTED_PROVIDER_ID}")
    assert original.status == 200, f"keycloak SSOProvider not found — is SSO_KEYCLOAK_ENABLED=true? {original.status} {original.text()}"
    original_trusted = bool(original.json().get("trusted_for_api_auth"))

    resp = admin_api.put(
        f"/auth/sso/admin/providers/{TRUSTED_PROVIDER_ID}",
        data={
            "trusted_for_api_auth": True,
            "api_audience": TRUSTED_API_AUDIENCE,
            "team_mapping": {KEYCLOAK_VIEWERS_GROUP: {"team_id": scoped_team["id"], "role": "member"}},
        },
    )
    assert resp.status == 200, f"Failed to opt keycloak provider into trusted_for_api_auth: {resp.status} {resp.text()}"

    yield

    with suppress(Exception):
        admin_api.put(f"/auth/sso/admin/providers/{TRUSTED_PROVIDER_ID}", data={"trusted_for_api_auth": original_trusted})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestExternalIdPRestAuth:
    """E2E: trusted external-IdP bearer tokens on REST endpoints (#6396)."""

    def test_trusted_group_member_sees_scoped_tool(self, playwright: Playwright, trusted_keycloak_provider: None, team_scoped_tool: dict[str, Any]):
        """A trusted, correctly-audienced token for a /Viewers member gets 200 with the scoped tool visible.

        Before the fix, get_current_user() never reached external-IdP verification, so
        this request 401'd unconditionally regardless of trusted_for_api_auth.
        """
        token = _get_keycloak_token(KEYCLOAK_GROUP_MEMBER)
        resp = _rest_request(playwright, "/tools", token)
        assert resp.status == 200, f"Trusted external-IdP token should be accepted on GET /tools, got {resp.status}: {resp.text()}"
        tool_ids = {t["id"] for t in resp.json()}
        assert team_scoped_tool["id"] in tool_ids, "Group member should see the team-scoped tool granted via SSO team_mapping"

    def test_trusted_non_member_sees_zero_matching_tools(self, playwright: Playwright, trusted_keycloak_provider: None, team_scoped_tool: dict[str, Any]):
        """Same trusted provider, a user in no mapped group: still 200 (authenticated), but the
        team-scoped tool is absent -- proving team-scoping is real RBAC enforcement, not a
        blanket grant for any trusted-issuer token.
        """
        token = _get_keycloak_token(KEYCLOAK_NO_GROUP_USER)
        resp = _rest_request(playwright, "/tools", token)
        assert resp.status == 200, f"Trusted external-IdP token should be accepted on GET /tools, got {resp.status}: {resp.text()}"
        tool_ids = {t["id"] for t in resp.json()}
        assert team_scoped_tool["id"] not in tool_ids, "Non-member should not see a tool scoped to a team they were never mapped into"

    def test_wrong_audience_rejected(self, playwright: Playwright, admin_api: APIRequestContext, trusted_keycloak_provider: None):
        """A validly-signed, trusted-issuer token whose `aud` doesn't match api_audience is rejected."""
        resp = admin_api.put(
            f"/auth/sso/admin/providers/{TRUSTED_PROVIDER_ID}",
            data={"trusted_for_api_auth": True, "api_audience": "not-a-real-audience"},
        )
        assert resp.status == 200, f"Failed to set wrong api_audience: {resp.status} {resp.text()}"
        try:
            token = _get_keycloak_token(KEYCLOAK_GROUP_MEMBER)
            resp = _rest_request(playwright, "/tools", token)
            assert resp.status == 401, f"Token with non-matching audience should be rejected, got {resp.status}"
        finally:
            admin_api.put(
                f"/auth/sso/admin/providers/{TRUSTED_PROVIDER_ID}",
                data={"trusted_for_api_auth": True, "api_audience": TRUSTED_API_AUDIENCE},
            )

    def test_no_token_rejected(self, playwright: Playwright, trusted_keycloak_provider: None):
        """No Authorization header at all is still a plain 401."""
        resp = _rest_request(playwright, "/tools", None)
        assert resp.status == 401, f"Unauthenticated request should be rejected, got {resp.status}"
