# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/sso/test_preprovisioned_idp_auth.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Validate API-provisioned SSO users through external IdP bearer authentication.

Run serially against externally started gateways and HTTPS Keycloak. The
disabled-gateway case needs a second gateway sharing the first gateway's DB.
See tests/live_gateway/README.md for startup configuration and teardown rules.
"""

# Standard
import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, ExitStack
from dataclasses import dataclass, field
import os
import time
from typing import Any, cast
from urllib.parse import quote
from uuid import uuid4

# Third-Party
import httpx
import httpx2
import jwt
from mcp import ClientSession, MCPError
from mcp.client.streamable_http import streamable_http_client
import pytest
from sqlalchemy import create_engine, text

# First-Party
from mcpgateway.utils.streamable_http_compat import ErrorResponseHook

# Local
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]
PROVISION_PATH = "/v1/admin/users/sso"
IDENTITY_TTL = 2


def _request(client: httpx.Client, method: str, path: str, *, expected: tuple[int, ...] = (200,), **kwargs: Any) -> httpx.Response:
    """Require an API response with the expected status."""
    response = client.request(method, path, **kwargs)
    assert response.status_code in expected, f"{method} {path}: HTTP {response.status_code}: {response.text}"
    return response


def _object(response: httpx.Response) -> dict[str, Any]:
    """Read a JSON object from a successful API response."""
    body = response.json()
    assert isinstance(body, dict)
    return cast(dict[str, Any], body)


def _user_path(email: str) -> str:
    """Return the admin user resource path for a unique fixture email."""
    return f"/v1/auth/email/admin/users/{quote(email, safe='')}"


def _role_path(email: str) -> str:
    """Return the role-assignment collection for a fixture user."""
    return f"/v1/rbac/users/{quote(email, safe='')}/roles"


def _clear_roles(admin: httpx.Client, email: str) -> tuple[str, ...]:
    """Remove automatic onboarding and membership grants before assigning test roles."""
    assignments = _request(admin, "GET", _role_path(email)).json()
    scope_ids = []
    for assignment in assignments:
        role_id = assignment.get("role_id") or assignment["roleId"]
        scope_id = assignment.get("scope_id") or assignment.get("scopeId")
        params = {"scope": assignment["scope"]}
        if scope_id:
            params["scope_id"] = scope_id
            scope_ids.append(scope_id)
        _request(admin, "DELETE", f"{_role_path(email)}/{role_id}", params=params)
    assert _request(admin, "GET", _role_path(email)).json() == []
    return tuple(scope_ids)


@dataclass(frozen=True)
class IdP:
    """HTTPS Keycloak client configuration for an externally started test stack."""

    url: str
    issuer: str
    realm: str
    client_id: str
    client_secret: str = field(repr=False)
    provider_id: str


@dataclass(frozen=True)
class User:
    """Unique Keycloak identity and optional API-provisioned gateway account."""

    email: str
    token: str = field(repr=False)
    created_at: str | None
    provider_id: str
    personal_team_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Resources:
    """Non-personal team, protected tool, virtual server, and minimal DB roles."""

    team_id: str
    tool_id: str
    tool_name: str
    server_id: str
    reader_role_id: str
    transport_role_id: str


@pytest.fixture(scope="module", name="idp")
def idp_fixture(request: pytest.FixtureRequest) -> IdP:
    """Require serial execution and explicit TLS/cache settings for live verification."""
    assert not hasattr(request.config, "workerinput"), "Run this shared-provider suite serially, without xdist"
    assert not getattr(request.config.option, "numprocesses", None), "Run without -n: shared Keycloak/provider mutations require serial teardown"
    if os.getenv("SSO_API_TOKEN_AUTH_ENABLED", "false").lower() != "true":
        pytest.skip("Export SSO_API_TOKEN_AUTH_ENABLED=true for both gateways and pytest")
    url = os.getenv("KEYCLOAK_URL", "http://localhost:8180").rstrip("/")
    internal = os.getenv("KEYCLOAK_INTERNAL_URL", url).rstrip("/")
    if not url.startswith("https://") or not internal.startswith("https://"):
        pytest.skip("This suite requires HTTPS Keycloak and a trusted TLS certificate")
    assert os.getenv("EXTERNAL_IDENTITY_CACHE_TTL") == str(IDENTITY_TTL), "Set EXTERNAL_IDENTITY_CACHE_TTL=2 in both gateways and pytest"
    assert os.getenv("AUTH_CACHE_ENABLED", "true").lower() == "false", "Set AUTH_CACHE_ENABLED=false to isolate the external-identity TTL"
    assert os.getenv("SSO_ALLOW_PROVIDER_LINKING", "false").lower() == "false", "Provider-mismatch coverage requires SSO_ALLOW_PROVIDER_LINKING=false"
    assert os.getenv("SSO_TEST_DATABASE_URL"), "Set SSO_TEST_DATABASE_URL to the isolated shared gateway database for fixture cleanup"
    realm = os.getenv("KEYCLOAK_REALM", "mcp-gateway")
    config = IdP(
        url,
        f"{internal}/realms/{realm}",
        realm,
        os.getenv("KEYCLOAK_CLIENT_ID", "mcp-gateway"),
        os.getenv("KEYCLOAK_CLIENT_SECRET", "keycloak-dev-secret"),
        os.getenv("SSO_TEST_PROVIDER_ID", "keycloak"),
    )  # pragma: allowlist secret
    try:
        response = httpx.get(f"{url}/realms/{realm}/.well-known/openid-configuration", timeout=10)
    except httpx.ConnectError:
        pytest.skip("HTTPS Keycloak is unreachable")
    assert response.status_code == 200, "The configured Keycloak realm must expose OIDC discovery"
    assert response.json()["issuer"].rstrip("/") == config.issuer, "Public and gateway URLs must resolve the same issuer"
    return config


@pytest.fixture(scope="module", name="admin")
def admin_fixture(idp: IdP) -> Iterator[httpx.Client]:
    """Use the existing administrator to create fixtures through gateway APIs."""
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
    with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30) as client:
        schema = _object(_request(client, "GET", "/openapi.json"))
        assert PROVISION_PATH in schema["paths"], "Start the primary gateway with SSO_USER_PROVISIONING_API_ENABLED=true"
        provider = _object(_request(client, "GET", f"/v1/auth/sso/admin/providers/{idp.provider_id}"))
        assert provider["issuer"].rstrip("/") == idp.issuer
        yield client


@pytest.fixture(scope="module", name="keycloak_admin")
def keycloak_admin_fixture(idp: IdP) -> Iterator[httpx.Client]:
    """Authenticate to the Keycloak admin API without a browser session."""
    response = httpx.post(
        f"{idp.url}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": os.getenv("KEYCLOAK_ADMIN", "admin"),
            "password": os.getenv("KEYCLOAK_ADMIN_PASSWORD", "changeme"),  # pragma: allowlist secret
        },
        timeout=20,
    )
    assert response.status_code == 200, "Keycloak administrator authentication failed"
    with httpx.Client(base_url=f"{idp.url}/admin/realms/{idp.realm}/", headers={"Authorization": f"Bearer {response.json()['access_token']}"}, timeout=20) as client:
        yield client


@pytest.fixture(scope="module", name="trusted_provider")
def trusted_provider_fixture(admin: httpx.Client, keycloak_admin: httpx.Client, idp: IdP) -> Iterator[str]:
    """Configure the bootstrapped provider and a unique audience mapper, then restore both."""
    path = f"/v1/auth/sso/admin/providers/{idp.provider_id}"
    original = _object(_request(admin, "GET", path))
    providers = _request(admin, "GET", "/v1/auth/sso/admin/providers").json()
    collisions = [
        provider["id"]
        for provider in providers
        if provider["id"] != idp.provider_id and provider.get("is_enabled") and provider.get("trusted_for_api_auth") and str(provider.get("issuer") or "").rstrip("/") == idp.issuer
    ]
    assert collisions == [], "Use one enabled, API-trusted provider per Keycloak issuer"
    restore = {
        "is_enabled": original["is_enabled"],
        "auto_create_users": original["auto_create_users"],
        "trusted_for_api_auth": original.get("trusted_for_api_auth", False),
        "api_audience": original.get("api_audience") or "",
        "trusted_domains": original.get("trusted_domains") or [],
        "team_mapping": original.get("team_mapping") or {},
        "provider_metadata": original.get("provider_metadata") or {},
    }
    clients = _request(keycloak_admin, "GET", "clients", params={"clientId": idp.client_id}).json()
    assert len(clients) == 1, "Keycloak clientId must identify one test client"
    mapper_path = f"clients/{clients[0]['id']}/protocol-mappers/models"
    audience = f"preprovisioned-{uuid4().hex}"
    mapper = {
        "name": audience,
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "config": {"included.custom.audience": audience, "access.token.claim": "true", "id.token.claim": "false"},
    }
    with ExitStack() as cleanup:
        response = _request(keycloak_admin, "POST", mapper_path, expected=(201,), json=mapper)
        mapper_id = response.headers["Location"].rsplit("/", 1)[-1]
        cleanup.callback(_request, keycloak_admin, "DELETE", f"{mapper_path}/{mapper_id}", expected=(204, 404))
        cleanup.callback(_request, admin, "PUT", path, json=restore)
        metadata = {**restore["provider_metadata"], "sync_roles": False, "role_mappings": {}, "default_role": ""}
        _request(
            admin,
            "PUT",
            path,
            json={
                "is_enabled": True,
                "auto_create_users": False,
                "trusted_for_api_auth": True,
                "api_audience": audience,
                "trusted_domains": [],
                "team_mapping": {},
                "provider_metadata": metadata,
            },
        )
        yield audience


@pytest.fixture(scope="module", name="gateway_users")
def gateway_users_fixture() -> list[str]:
    """Track API-created users for role cleanup before resource deletion."""
    return []


def _delete_fixture_user(admin: httpx.Client, email: str) -> None:
    """Delete only this fixture's membership history, then delete its account through the API."""
    assert email.startswith("preprov-") and email.endswith("@example.com")
    database_url = os.getenv("SSO_TEST_DATABASE_URL", "")
    assert database_url, "Set SSO_TEST_DATABASE_URL to the isolated shared gateway database for fixture-history cleanup"
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            stored_email = cast(str | None, connection.execute(text("SELECT email FROM email_users WHERE email = :email"), {"email": email}).scalar_one_or_none())
            assert stored_email == email, "Cleanup database must contain the account created through this test gateway"
            connection.execute(
                text("DELETE FROM email_team_member_history WHERE user_email = :email " "AND team_member_id IN (SELECT id FROM email_team_members WHERE user_email = :email)"), {"email": email}
            )
    finally:
        engine.dispose()
    _request(admin, "DELETE", _user_path(email), expected=(200, 204, 404))


@pytest.fixture(scope="module", name="resources")
def resources_fixture(admin: httpx.Client, user_factory: Callable[..., User], gateway_users: list[str], idp: IdP, trusted_provider: str) -> Iterator[Resources]:  # pylint: disable=unused-argument
    """Create a non-personal team and a public virtual server containing one team-only tool.

    The user_factory dependency keeps account deletion after resource cleanup.
    """
    suffix = uuid4().hex[:12]
    with ExitStack() as cleanup:
        team = _object(_request(admin, "POST", "/v1/teams/", expected=(200, 201), json={"name": f"preprov-team-{suffix}", "visibility": "private"}))
        assert team["is_personal"] is False
        cleanup.callback(_request, admin, "DELETE", f"/v1/teams/{team['id']}", expected=(200, 204, 404))
        roles = []
        for label, permissions in (("reader", ["tools.read"]), ("transport", ["servers.use"])):
            role = _object(_request(admin, "POST", "/v1/rbac/roles", expected=(200, 201), json={"name": f"preprov-{label}-{suffix}", "scope": "global", "permissions": permissions}))
            roles.append(role["id"])
            cleanup.callback(_request, admin, "DELETE", f"/v1/rbac/roles/{role['id']}", expected=(200, 204, 404))
        tool = _object(
            _request(
                admin,
                "POST",
                "/v1/tools",
                json={
                    "tool": {
                        "name": f"preprov-tool-{suffix}",
                        "url": "https://example.com/healthz",
                        "integration_type": "REST",
                        "request_type": "GET",
                        "visibility": "team",
                        "input_schema": {"type": "object", "properties": {}},
                    },
                    "team_id": team["id"],
                },
            )
        )
        assert (tool.get("team_id") or tool.get("teamId")) == team["id"]
        cleanup.callback(_request, admin, "DELETE", f"/v1/tools/{tool['id']}", expected=(200, 204, 404))
        server = _object(
            _request(
                admin,
                "POST",
                "/v1/servers",
                expected=(201,),
                json={
                    "server": {
                        "name": f"preprov-server-{suffix}",
                        "associated_tools": [tool["id"]],
                        "oauth_enabled": True,
                        "oauth_config": {"authorization_servers": [idp.issuer], "resource": trusted_provider},
                    },
                    "visibility": "public",
                },
            )
        )
        cleanup.callback(_request, admin, "DELETE", f"/v1/servers/{server['id']}", expected=(200, 204, 404))

        def clear_fixture_roles() -> None:
            """Release role references while keeping users until team history cleanup completes."""
            for email in gateway_users:
                _clear_roles(admin, email)

        cleanup.callback(clear_fixture_roles)
        yield Resources(team["id"], tool["id"], tool["name"], server["id"], roles[0], roles[1])


@pytest.fixture(scope="module", name="user_factory")
def user_factory_fixture(admin: httpx.Client, keycloak_admin: httpx.Client, idp: IdP, trusted_provider: str, gateway_users: list[str]) -> Iterator[Callable[..., User]]:
    """Create unique verified IdP users and optional matching gateway accounts, then delete them."""
    with ExitStack() as cleanup:

        def create(*, provision: bool = True, active: bool = True, provider_id: str | None = None) -> User:
            """Mint one IdP token without browser login or gateway JIT creation."""
            email = f"preprov-{uuid4().hex}@example.com"
            password = f"Test!{uuid4().hex}9a"
            response = _request(
                keycloak_admin,
                "POST",
                "users",
                expected=(201,),
                json={
                    "username": email,
                    "email": email,
                    "emailVerified": True,
                    "enabled": True,
                    "firstName": "Preprovisioned",
                    "lastName": "Test",
                    "credentials": [{"type": "password", "value": password, "temporary": False}],
                },
            )
            kc_id = response.headers["Location"].rsplit("/", 1)[-1]
            cleanup.callback(_request, keycloak_admin, "DELETE", f"users/{kc_id}", expected=(204, 404))
            bound_provider = provider_id or idp.provider_id
            created_at = None
            personal_team_ids: tuple[str, ...] = ()
            if provision:
                cleanup.callback(_delete_fixture_user, admin, email)
                body = _object(_request(admin, "POST", PROVISION_PATH, expected=(201,), json={"email": email, "auth_provider": bound_provider, "is_active": active}))
                assert body["is_admin"] is False
                assert body["email_verified"] is False
                created_at = body["created_at"]
                gateway_users.append(email)
                personal_team_ids = _clear_roles(admin, email)
            response = httpx.post(
                f"{idp.url}/realms/{idp.realm}/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": idp.client_id,
                    "client_secret": idp.client_secret,
                    "username": email,
                    "password": password,
                    "scope": "openid profile email",
                },
                timeout=20,
            )
            assert response.status_code == 200, "Unique Keycloak user must obtain an access token"
            token = response.json()["access_token"]
            claims = jwt.decode(token, options={"verify_signature": False})
            assert claims["iss"].rstrip("/") == idp.issuer
            audience = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
            assert trusted_provider in audience
            assert claims["email_verified"] is True
            assert claims["exp"] > time.time() + IDENTITY_TTL + 30
            return User(email, token, created_at, bound_provider, personal_team_ids)

        yield create


def _grant_access(admin: httpx.Client, user: User, resources: Resources, *, read: bool = True, transport: bool = True, membership: bool = True) -> None:
    """Grant explicit DB transport/read permissions and optional non-personal membership."""
    assert resources.team_id not in user.personal_team_ids
    if membership:
        _request(admin, "POST", f"/v1/teams/{resources.team_id}/members", expected=(201,), json={"email": user.email, "role": "member"})
    _clear_roles(admin, user.email)
    role_ids = ([resources.transport_role_id] if transport else []) + ([resources.reader_role_id] if read else [])
    for role_id in role_ids:
        _request(admin, "POST", _role_path(user.email), json={"role_id": role_id, "scope": "global"})


def _rest_tools(user: User, *, base_url: str = BASE_URL) -> httpx.Response:
    """List tools through REST with the unchanged IdP-issued bearer token."""
    return httpx.get(f"{base_url}/v1/tools", headers={"Authorization": f"Bearer {user.token}"}, params={"limit": 1000}, timeout=20)


def _tool_ids(response: httpx.Response) -> set[str]:
    """Extract tool IDs from the REST list response."""
    assert response.status_code == 200, f"GET /v1/tools: HTTP {response.status_code}"
    body = response.json()
    tools = body if isinstance(body, list) else body.get("tools", body.get("data", []))
    return {tool["id"] for tool in tools}


@asynccontextmanager
async def _mcp_session(user: User, resources: Resources, *, base_url: str = BASE_URL) -> AsyncIterator[ClientSession]:
    """Initialize a real MCP session and preserve authorization error statuses."""
    url = f"{base_url}/servers/{resources.server_id}/mcp/"
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {user.token}"}, timeout=httpx2.Timeout(20), follow_redirects=True) as client:
        error_hook = ErrorResponseHook().install(client)
        try:
            async with streamable_http_client(url, http_client=client) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=20) as session:
                    await session.initialize()
                    yield session
        except Exception as error:
            status_error = error_hook.to_http_status_error(error)
            if status_error is not None:
                raise status_error from error
            raise


async def _mcp_tools(user: User, resources: Resources, *, base_url: str = BASE_URL) -> set[str]:
    """List the fixture virtual server's tools through a real MCP session."""
    async with _mcp_session(user, resources, base_url=base_url) as session:
        try:
            result = await session.list_tools()
        except MCPError as error:
            assert "permission" in str(error).lower() or "access denied" in str(error).lower(), "MCP denial must identify authorization"
            return set()
        return {tool.name for tool in result.tools}


def _assert_access(user: User, resources: Resources, *, base_url: str = BASE_URL) -> None:
    """Assert REST resource visibility and MCP tools/list with the same token."""
    assert resources.tool_id in _tool_ids(_rest_tools(user, base_url=base_url))
    assert resources.tool_name in asyncio.run(_mcp_tools(user, resources, base_url=base_url))


async def _assert_execution_denied(user: User, resources: Resources) -> None:
    """Require a tools.execute denial for a user who can establish MCP and list tools."""
    async with _mcp_session(user, resources) as session:
        try:
            result = await session.call_tool(resources.tool_name, arguments={})
        except MCPError as error:
            assert "permission" in str(error).lower() or "access denied" in str(error).lower()
            return
        assert result.is_error is True
        detail = " ".join(str(getattr(content, "text", "")) for content in result.content).lower()
        assert "permission" in detail or "access denied" in detail, "The call must fail authorization before contacting the fixture URL"


def _expire_identity(user: User) -> None:
    """Wait beyond the configured cache window while the original token remains valid."""
    claims = jwt.decode(user.token, options={"verify_signature": False})
    assert claims["exp"] > time.time() + IDENTITY_TTL + 10
    time.sleep(IDENTITY_TTL + 0.25)


def _assert_existing_account(admin: httpx.Client, user: User) -> None:
    """Assert stable account creation time and provider binding after bearer authentication."""
    stored = _object(_request(admin, "GET", _user_path(user.email)))
    assert stored["email"] == user.email
    assert stored["created_at"] == user.created_at
    assert stored["auth_provider"] == user.provider_id
    assert stored["is_admin"] is False


def test_preprovisioned_user_authenticates_without_browser_or_jit(admin: httpx.Client, user_factory: Callable[..., User], resources: Resources) -> None:
    """An API-provisioned account accesses REST and MCP with JIT creation disabled."""
    user = user_factory()
    _grant_access(admin, user, resources)
    _assert_access(user, resources)
    _assert_existing_account(admin, user)


def test_idp_token_alone_cannot_create_gateway_user(admin: httpx.Client, user_factory: Callable[..., User]) -> None:
    """A valid IdP token cannot JIT-create a missing account when auto_create_users is false."""
    user = user_factory(provision=False)
    assert _rest_tools(user).status_code == 401
    _request(admin, "GET", _user_path(user.email), expected=(404,))


def test_valid_token_requires_db_role(admin: httpx.Client, user_factory: Callable[..., User], resources: Resources) -> None:
    """Team membership and a valid token do not replace tools.read permission."""
    user = user_factory()
    _grant_access(admin, user, resources, read=False, transport=False)
    assert _rest_tools(user).status_code == 403
    with pytest.raises(httpx2.HTTPStatusError) as denial:
        asyncio.run(_mcp_tools(user, resources))
    assert denial.value.response.status_code == 403


def test_mcp_execution_requires_db_permission(admin: httpx.Client, user_factory: Callable[..., User], resources: Resources) -> None:
    """MCP discovery and team membership do not replace the DB tools.execute permission."""
    user = user_factory()
    _grant_access(admin, user, resources)
    _assert_access(user, resources)
    asyncio.run(_assert_execution_denied(user, resources))


def test_role_revocation_denies_same_token_after_cache_expiry(admin: httpx.Client, user_factory: Callable[..., User], resources: Resources) -> None:
    """Revoking the DB reader role denies the same unexpired token after the cache window."""
    user = user_factory()
    _grant_access(admin, user, resources)
    _assert_access(user, resources)
    for role_id in (resources.reader_role_id, resources.transport_role_id):
        _request(admin, "DELETE", f"{_role_path(user.email)}/{role_id}", params={"scope": "global"})
    _expire_identity(user)
    assert _rest_tools(user).status_code == 403
    with pytest.raises(httpx2.HTTPStatusError) as denial:
        asyncio.run(_mcp_tools(user, resources))
    assert denial.value.response.status_code == 403


def test_team_removal_hides_tool_from_same_token(admin: httpx.Client, user_factory: Callable[..., User], resources: Resources) -> None:
    """Removing non-personal team membership hides its resource after the identity cache expires."""
    user = user_factory()
    _grant_access(admin, user, resources)
    _assert_access(user, resources)
    _request(admin, "DELETE", f"/v1/teams/{resources.team_id}/members/{quote(user.email, safe='')}")
    _expire_identity(user)
    assert resources.tool_id not in _tool_ids(_rest_tools(user))
    assert resources.tool_name not in asyncio.run(_mcp_tools(user, resources))


def test_inactive_preprovisioned_user_denied(user_factory: Callable[..., User]) -> None:
    """An IdP-issued token does not authenticate an inactive pre-provisioned account."""
    assert _rest_tools(user_factory(active=False)).status_code == 401


def test_deactivated_account_denies_cached_token(admin: httpx.Client, user_factory: Callable[..., User], resources: Resources) -> None:
    """Deactivation denies a previously accepted token without changing provider configuration."""
    user = user_factory()
    _grant_access(admin, user, resources)
    _assert_access(user, resources)
    _request(admin, "PATCH", _user_path(user.email), json={"is_active": False})
    _expire_identity(user)
    assert _rest_tools(user).status_code == 401


def test_provider_mismatch_preserves_binding(admin: httpx.Client, user_factory: Callable[..., User]) -> None:
    """A verified token from Keycloak cannot link an account bound to another issuer."""
    provider_id = f"mismatch-{uuid4().hex[:12]}"
    _request(
        admin,
        "POST",
        "/v1/auth/sso/admin/providers",
        json={
            "id": provider_id,
            "name": provider_id,
            "display_name": "Mismatch fixture",
            "provider_type": "oidc",
            "client_id": "mismatch-client",
            "client_secret": uuid4().hex,
            "authorization_url": "https://mismatch.example.com/authorize",
            "token_url": "https://mismatch.example.com/token",  # nosec B105 - Fixture endpoint URL.
            "userinfo_url": "https://mismatch.example.com/userinfo",
            "issuer": "https://mismatch.example.com",
            "is_enabled": True,
            "auto_create_users": False,
        },
    )
    try:
        user = user_factory(provider_id=provider_id)
        assert _rest_tools(user).status_code == 401
        _assert_existing_account(admin, user)
    finally:
        _request(admin, "DELETE", f"/v1/auth/sso/admin/providers/{provider_id}")


def test_existing_user_authenticates_with_provisioning_disabled(admin: httpx.Client, user_factory: Callable[..., User], resources: Resources) -> None:
    """A second gateway hides provisioning but authenticates the same API-created account."""
    disabled_url = os.getenv("SSO_PROVISIONING_DISABLED_BASE_URL", "").rstrip("/")
    if not disabled_url:
        pytest.skip("Provide SSO_PROVISIONING_DISABLED_BASE_URL for a second gateway sharing the primary database and IdP configuration")
    user = user_factory()
    _grant_access(admin, user, resources)
    _assert_access(user, resources)
    response = httpx.post(f"{disabled_url}{PROVISION_PATH}", content=b"{", timeout=20)
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    _assert_access(user, resources, base_url=disabled_url)
    _assert_existing_account(admin, user)
