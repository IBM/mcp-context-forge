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
    - ContextForge running (default: http://localhost:8080) with SSO_ENABLED=true,
      SSO_KEYCLOAK_ENABLED=true and SSO_API_TOKEN_AUTH_ENABLED=true
    - Keycloak with the mcp-gateway realm imported (infra/keycloak/realm-export.json)
    - playwright installed: pip install playwright. pyproject.toml disables the plugin by
      default (-p no:playwright), so pass -p playwright to pytest.
    - The four positive tests (a trusted token for a group member and for a non-member, on
      GET /tools and POST /rpc) also need an https Keycloak. verify_oauth_access_token accepts
      only an https issuer and jwks_uri, and the Keycloak of the sso compose profile is plain
      http, so these four tests skip against it.

Usage, deny paths only (sso compose profile):
    SSO_API_TOKEN_AUTH_ENABLED=true docker compose --profile sso up -d
    SSO_API_TOKEN_AUTH_ENABLED=true pytest -p playwright tests/live_gateway/sso/test_external_idp_rest_auth_e2e.py -v -rs

Usage, all nine tests (https Keycloak in Docker, gateway from this checkout on the host).
Run from the repository root. Keep the certificate under $HOME: some Docker runtimes on macOS
(for example Rancher Desktop and Colima) share only $HOME with the container VM by default.

    mkdir -p ~/kc-tls
    openssl req -x509 -newkey rsa:2048 -nodes -days 7 -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" -keyout ~/kc-tls/tls.key -out ~/kc-tls/tls.crt
    chmod 644 ~/kc-tls/tls.key
    docker run -d --name kc-tls -p 8543:8443 \
        -e KEYCLOAK_ADMIN=admin -e KEYCLOAK_ADMIN_PASSWORD=changeme \
        -e KC_HTTPS_CERTIFICATE_FILE=/opt/tls/tls.crt -e KC_HTTPS_CERTIFICATE_KEY_FILE=/opt/tls/tls.key \
        -v ~/kc-tls:/opt/tls:ro \
        -v "$PWD/infra/keycloak/realm-export.json:/opt/keycloak/data/import/realm-export.json:ro" \
        quay.io/keycloak/keycloak:26.1 start-dev --import-realm

    # Settings for both the gateway and pytest. JWT_SECRET_KEY (and the other secrets the
    # gateway needs, for example from `make init-secrets-patch-env`) must be the same in both.
    export SSL_CERT_FILE=~/kc-tls/tls.crt
    export SSO_ENABLED=true SSO_KEYCLOAK_ENABLED=true SSO_API_TOKEN_AUTH_ENABLED=true
    export SSO_KEYCLOAK_BASE_URL=https://localhost:8543 SSO_KEYCLOAK_REALM=mcp-gateway
    export SSO_KEYCLOAK_CLIENT_ID=mcp-gateway SSO_KEYCLOAK_CLIENT_SECRET=keycloak-dev-secret
    export MCPGATEWAY_ADMIN_API_ENABLED=true
    export KEYCLOAK_URL=https://localhost:8543 KEYCLOAK_INTERNAL_URL=https://localhost:8543

    uv run uvicorn mcpgateway.main:app --host 127.0.0.1 --port 8080 &
    pytest -p playwright tests/live_gateway/sso/test_external_idp_rest_auth_e2e.py -v -rs

    The suite changes the bootstrapped keycloak provider and adds an audience mapper to the
    Keycloak client; its fixtures restore both on teardown.
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
# The imported realm gives its users no client roles, so Keycloak's built-in
# audience resolution puts no `aud` in their access tokens. The keycloak_audience_mapper
# fixture adds this audience through the Keycloak admin API for the duration of the suite.
KEYCLOAK_ADMIN_USER = os.getenv("KEYCLOAK_ADMIN", "admin")
KEYCLOAK_ADMIN_PASSWORD = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "changeme")  # pragma: allowlist secret — e2e Keycloak fixture, not a real credential
AUDIENCE_MAPPER_NAME = "ext-idp-rest-e2e-audience"
TRUSTED_PROVIDER_ID = "keycloak"
TRUSTED_API_AUDIENCE = "forge-rest-e2e"
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

# External-IdP verification only accepts an https issuer/jwks_uri (verify_oauth_access_token
# rejects any other scheme as an SSRF defense), so a token from the plain-http Keycloak of the
# default compose stack is always rejected. Positive-path tests need an https Keycloak.
skip_no_https_issuer = pytest.mark.skipif(
    not KEYCLOAK_ISSUER.startswith("https://"),
    reason="external-IdP verification requires an https issuer -- run Keycloak with TLS and set KEYCLOAK_URL/KEYCLOAK_INTERNAL_URL, SSO_KEYCLOAK_BASE_URL and SSL_CERT_FILE accordingly",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_cf_jwt(email: str, is_admin: bool = False) -> str:
    # Shared with the rest of the e2e suite so this token can't drift from
    # the gateway's configured JWT_SECRET_KEY. teams=None gives admin tokens the
    # unrestricted (admin bypass) scope; a token with no "teams" claim is public-only
    # and cannot create the team-scoped resources these fixtures need.
    return make_test_jwt(email, is_admin=is_admin, teams=None, secret=JWT_SECRET)


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

    # Fallback: request from the host. The issuer matches the gateway's only when KEYCLOAK_URL
    # equals KEYCLOAK_INTERNAL_URL, as in the https setup in the module docstring.
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


class _Response:
    """Status and body read before the request context is disposed (a disposed Playwright response cannot be read)."""

    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body

    def text(self) -> str:
        return self._body

    def json(self) -> Any:
        # Standard
        import json

        return json.loads(self._body)


def _rpc_request(playwright: Playwright, token: str | None, method: str = "tools/list") -> _Response:
    """Issue a JSON-RPC POST against /rpc with an optional bearer token."""
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    ctx = playwright.request.new_context(base_url=BASE_URL, extra_http_headers=headers)
    try:
        resp = ctx.post("/rpc", data={"jsonrpc": "2.0", "id": 1, "method": method, "params": {}})
        return _Response(resp.status, resp.text())
    finally:
        ctx.dispose()


def _rest_request(playwright: Playwright, path: str, token: str | None) -> _Response:
    """Issue a GET request against a REST endpoint with an optional bearer token."""
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    ctx = playwright.request.new_context(base_url=BASE_URL, extra_http_headers=headers)
    try:
        resp = ctx.get(path)
        return _Response(resp.status, resp.text())
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


def _keycloak_admin_session() -> tuple[str, dict[str, str], str]:
    """Return (mcp-gateway client UUID, auth headers, admin API base URL) for the Keycloak admin API."""
    # Third-Party
    import httpx

    resp = httpx.post(
        f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
        data={"grant_type": "password", "client_id": "admin-cli", "username": KEYCLOAK_ADMIN_USER, "password": KEYCLOAK_ADMIN_PASSWORD},
        timeout=10,
    )
    assert resp.status_code == 200, f"Keycloak admin login failed: {resp.status_code} {resp.text}"
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    clients = httpx.get(f"{base}/clients", params={"clientId": KEYCLOAK_CLIENT_ID}, headers=headers, timeout=10)
    assert clients.status_code == 200 and clients.json(), f"Keycloak client {KEYCLOAK_CLIENT_ID} not found: {clients.status_code} {clients.text}"
    return clients.json()[0]["id"], headers, base


@pytest.fixture(scope="module")
def keycloak_audience_mapper() -> Generator[None, None, None]:
    """Add TRUSTED_API_AUDIENCE to the `aud` claim of access tokens minted for the mcp-gateway client."""
    # Third-Party
    import httpx

    client_uuid, headers, base = _keycloak_admin_session()
    mappers_url = f"{base}/clients/{client_uuid}/protocol-mappers/models"
    for existing in httpx.get(mappers_url, headers=headers, timeout=10).json():
        if existing["name"] == AUDIENCE_MAPPER_NAME:  # left behind by an interrupted run
            httpx.delete(f"{mappers_url}/{existing['id']}", headers=headers, timeout=10)
    resp = httpx.post(
        mappers_url,
        headers=headers,
        timeout=10,
        json={
            "name": AUDIENCE_MAPPER_NAME,
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "config": {"included.custom.audience": TRUSTED_API_AUDIENCE, "access.token.claim": "true", "id.token.claim": "false"},
        },
    )
    assert resp.status_code == 201, f"Failed to create Keycloak audience mapper: {resp.status_code} {resp.text}"

    yield

    with suppress(Exception):
        # The admin token from setup may have expired; log in again.
        client_uuid, headers, base = _keycloak_admin_session()
        mappers_url = f"{base}/clients/{client_uuid}/protocol-mappers/models"
        for existing in httpx.get(mappers_url, headers=headers, timeout=10).json():
            if existing["name"] == AUDIENCE_MAPPER_NAME:
                httpx.delete(f"{mappers_url}/{existing['id']}", headers=headers, timeout=10)


@pytest.fixture(scope="module")
def trusted_keycloak_provider(admin_api: APIRequestContext, scoped_team: dict[str, Any], keycloak_audience_mapper: None) -> Generator[None, None, None]:
    """Opt the bootstrapped `keycloak` SSOProvider into trusted_for_api_auth for this suite.

    Restores the provider's prior trusted_for_api_auth, api_audience and team_mapping on teardown. Group ->
    team mapping is dynamic (SSOService._apply_team_mapping runs on every
    authenticate_or_create_user() call, including via the external-IdP path), so
    this is also where the /Viewers -> scoped_team mapping is wired up.
    """
    original = admin_api.get(f"/auth/sso/admin/providers/{TRUSTED_PROVIDER_ID}")
    assert original.status == 200, f"keycloak SSOProvider not found — is SSO_KEYCLOAK_ENABLED=true? {original.status} {original.text()}"
    original_body = original.json()
    original_trusted = bool(original_body.get("trusted_for_api_auth"))
    # Provider updates preserve omitted fields and drop null values, so a null
    # original is restored as "" / {} -- the empty equivalents the update accepts.
    original_audience = original_body.get("api_audience") or ""
    original_team_mapping = original_body.get("team_mapping") or {}

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

    # One PUT restores every field this fixture changed, so the provider is never left
    # trusted with a stale audience or a mapping to the (about to be deleted) test team.
    with suppress(Exception):
        restore = admin_api.put(
            f"/auth/sso/admin/providers/{TRUSTED_PROVIDER_ID}",
            data={"trusted_for_api_auth": original_trusted, "api_audience": original_audience, "team_mapping": original_team_mapping},
        )
        if restore.status != 200:
            logger.warning("Failed to restore keycloak provider: %s %s", restore.status, restore.text())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestExternalIdPRestAuth:
    """E2E: trusted external-IdP bearer tokens on REST endpoints (#6396)."""

    @skip_no_https_issuer
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

    @skip_no_https_issuer
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


class TestExternalIdPRpcAuth:
    """E2E: trusted external-IdP bearer tokens on POST /rpc (#6396).

    /rpc shares get_current_user_with_permissions with the REST routes, so it must accept
    the same tokens and apply the same team scoping and deny behavior.
    """

    @staticmethod
    def _listed_tool_names(resp: _Response) -> set[str]:
        body = resp.json()
        assert "error" not in body, f"tools/list returned a JSON-RPC error: {body}"
        return {t["name"] for t in body["result"]["tools"]}

    @skip_no_https_issuer
    def test_trusted_group_member_lists_scoped_tool_via_rpc(self, playwright: Playwright, trusted_keycloak_provider: None, team_scoped_tool: dict[str, Any]):
        """A trusted token for a /Viewers member gets a JSON-RPC result on POST /rpc with the team-scoped tool listed."""
        token = _get_keycloak_token(KEYCLOAK_GROUP_MEMBER)
        resp = _rpc_request(playwright, token)
        assert resp.status == 200, f"Trusted external-IdP token should be accepted on POST /rpc, got {resp.status}: {resp.text()}"
        assert team_scoped_tool["name"] in self._listed_tool_names(resp), "Group member should see the team-scoped tool via tools/list"

    @skip_no_https_issuer
    def test_trusted_non_member_does_not_list_scoped_tool_via_rpc(self, playwright: Playwright, trusted_keycloak_provider: None, team_scoped_tool: dict[str, Any]):
        """A trusted token for a user in no mapped group is authenticated on POST /rpc but does not see the team-scoped tool."""
        token = _get_keycloak_token(KEYCLOAK_NO_GROUP_USER)
        resp = _rpc_request(playwright, token)
        assert resp.status == 200, f"Trusted external-IdP token should be accepted on POST /rpc, got {resp.status}: {resp.text()}"
        assert team_scoped_tool["name"] not in self._listed_tool_names(resp), "Non-member should not see a tool scoped to a team they were never mapped into"

    def test_wrong_audience_rejected_on_rpc(self, playwright: Playwright, admin_api: APIRequestContext, trusted_keycloak_provider: None):
        """A validly-signed, trusted-issuer token whose `aud` doesn't match api_audience is rejected on POST /rpc."""
        resp = admin_api.put(
            f"/auth/sso/admin/providers/{TRUSTED_PROVIDER_ID}",
            data={"trusted_for_api_auth": True, "api_audience": "not-a-real-audience"},
        )
        assert resp.status == 200, f"Failed to set wrong api_audience: {resp.status} {resp.text()}"
        try:
            token = _get_keycloak_token(KEYCLOAK_GROUP_MEMBER)
            resp = _rpc_request(playwright, token)
            assert resp.status == 401, f"Token with non-matching audience should be rejected on POST /rpc, got {resp.status}"
        finally:
            admin_api.put(
                f"/auth/sso/admin/providers/{TRUSTED_PROVIDER_ID}",
                data={"trusted_for_api_auth": True, "api_audience": TRUSTED_API_AUDIENCE},
            )

    def test_untrusted_issuer_rejected_on_rpc(self, playwright: Playwright, trusted_keycloak_provider: None):
        """A token from an issuer that is not a trusted provider is rejected on POST /rpc, even with a matching audience.

        The SSO admin endpoints are rate limited (10 requests/minute), so this deny path avoids
        toggling provider settings and uses a locally signed token instead.
        """
        # Standard
        from datetime import datetime, timedelta, timezone

        # Third-Party
        import jwt

        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {"iss": "https://untrusted-idp.example.com", "sub": KEYCLOAK_GROUP_MEMBER, "email": KEYCLOAK_GROUP_MEMBER, "aud": TRUSTED_API_AUDIENCE, "iat": now, "exp": now + timedelta(minutes=5)},
            "an-untrusted-idp-signing-key-of-sufficient-length",  # pragma: allowlist secret — throwaway key for a token that must be rejected
            algorithm="HS256",
        )
        resp = _rpc_request(playwright, token)
        assert resp.status == 401, f"Token from an untrusted issuer should be rejected on POST /rpc, got {resp.status}"

    def test_no_token_rejected_on_rpc(self, playwright: Playwright, trusted_keycloak_provider: None):
        """No Authorization header at all is still a plain 401 on POST /rpc."""
        resp = _rpc_request(playwright, None)
        assert resp.status == 401, f"Unauthenticated POST /rpc should be rejected, got {resp.status}"
