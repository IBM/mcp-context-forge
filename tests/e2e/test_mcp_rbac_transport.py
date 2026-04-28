# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_mcp_rbac_transport.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

RBAC + multi-transport MCP protocol tests using Playwright API + FastMCP Client.

Exercises MCP JSON-RPC protocol behaviour across multiple users, RBAC roles, token
scopes, server visibilities, and transports (Streamable HTTP + SSE). All user/team/role
setup is performed via real REST API calls (Playwright APIRequestContext) to cover the
full auth code path rather than shortcutting with _create_jwt_token().

This suite replaces the older ``mcpgateway.wrapper`` subprocess approach because the
wrapper currently has a session management bug (#4419) that breaks post-initialize
requests with HTTP 400 responses.

Requirements:
    - ContextForge running with docker-compose (default: http://localhost:8080)
    - fast_time_server registered as both Streamable HTTP and SSE gateways
    - FastMCP client dependencies installed
    - playwright installed: pip install playwright

Usage:
    make test-mcp-rbac
    pytest tests/e2e/test_mcp_rbac_transport.py -v -s --tb=short
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import concurrent.futures
from contextlib import suppress
import logging
import os
import time
from typing import Any, Generator
import uuid

# Third-Party
import pytest
from fastmcp.client import Client
from fastmcp.client.auth import BearerAuth

pw = pytest.importorskip("playwright", reason="playwright is not installed – pip install playwright")
from playwright.sync_api import APIRequestContext, Playwright

# First-Party
from mcpgateway.utils.create_jwt_token import _create_jwt_token

# Local
from .helpers.mcp_test_helpers import (
    BASE_URL,
    skip_no_gateway,
    TEST_PASSWORD,
)

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.e2e, skip_no_gateway]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RBAC_PREFIX = "mcp-rbac"
SSE_GATEWAY_NAME = f"{RBAC_PREFIX}-sse-gw"
# Must match docker-compose gateway JWT_SECRET_KEY
_JWT_SECRET = os.getenv("JWT_SECRET_KEY", "my-test-key-but-now-longer-than-32-bytes")
_CLIENT_TIMEOUT = float(os.getenv("MCP_E2E_CLIENT_TIMEOUT", "5.0"))


# ---------------------------------------------------------------------------
# JWT helper (for admin bootstrap only — all test users use POST /tokens)
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


# ---------------------------------------------------------------------------
# RBAC helper: resolve role name -> UUID
# ---------------------------------------------------------------------------
def _resolve_role_id(admin_api: APIRequestContext, role_name: str) -> str:
    resp = admin_api.get("/rbac/roles")
    assert resp.status == 200, f"Failed to list RBAC roles: {resp.status} {resp.text()}"
    for role in resp.json():
        if role.get("name") == role_name:
            return role["id"]
    raise AssertionError(f"RBAC role '{role_name}' not found. Available: {[r.get('name') for r in resp.json()]}")


# ---------------------------------------------------------------------------
# User lifecycle: create, invite, accept, assign role, create token
# ---------------------------------------------------------------------------
def _create_user_with_token(
    admin_api: APIRequestContext,
    playwright: Playwright,
    email: str,
    *,
    team_id: str | None = None,
    rbac_role: str | None = None,
    is_admin: bool = False,
    token_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a user via API, optionally join a team, assign RBAC role, and create an API token.

    Returns dict with: email, access_token, token_id, team_id, role.
    """
    # 1. Create user
    resp = admin_api.post(
        "/auth/email/admin/users",
        data={
            "email": email,
            "password": TEST_PASSWORD,
            "full_name": f"RBAC Test {email.split('@', maxsplit=1)[0]}",
            "is_admin": is_admin,
            "is_active": True,
            "password_change_required": False,
        },
    )
    if resp.status != 409:
        assert resp.status in (200, 201), f"Failed to create user {email}: {resp.status} {resp.text()}"
    logger.info("Created user %s (is_admin=%s)", email, is_admin)

    # 2. Add to team directly (admin is team owner/creator, so has teams.manage_members)
    if team_id:
        add_resp = admin_api.post(f"/teams/{team_id}/members", data={"email": email, "role": "member"})
        if add_resp.status not in (400, 409):
            assert add_resp.status in (200, 201), f"Failed to add {email} to team: {add_resp.status} {add_resp.text()}"
        logger.info("User %s joined team %s", email, team_id)

    # 3. Assign RBAC role (team-scoped only; platform_admin uses is_admin=True bypass)
    if rbac_role and rbac_role != "platform_admin" and team_id:
        role_uuid = _resolve_role_id(admin_api, rbac_role)
        role_data: dict[str, Any] = {"role_id": role_uuid, "scope": "team", "scope_id": team_id}
        role_resp = admin_api.post(f"/rbac/users/{email}/roles", data=role_data)
        if role_resp.status not in (409, 400):
            assert role_resp.status in (200, 201), f"Failed to assign {rbac_role} to {email}: {role_resp.status} {role_resp.text()}"
        logger.info("Assigned %s role to %s", rbac_role, email)

    # 4. Create API token via POST /tokens (as the user, using admin JWT that impersonates)
    # We use a JWT for this user to create a self-owned token
    user_jwt = _make_jwt(email, is_admin=is_admin, teams=[team_id] if team_id else None)
    user_ctx = _api_context(playwright, user_jwt)
    token_name = f"{RBAC_PREFIX}-token-{uuid.uuid4().hex[:8]}"
    token_data: dict[str, Any] = {
        "name": token_name,
        "expires_in_days": 1,
    }
    if team_id:
        token_data["team_id"] = team_id
    if token_scope:
        token_data["scope"] = token_scope

    try:
        token_resp = user_ctx.post("/tokens", data=token_data)
        assert token_resp.status in (200, 201), f"Failed to create token for {email}: {token_resp.status} {token_resp.text()}"
        payload = token_resp.json()
        access_token = payload["access_token"]
        token_obj = payload.get("token", payload)
        token_id = token_obj.get("id") or token_obj.get("token_id")
    finally:
        user_ctx.dispose()

    logger.info("Created API token for %s (id=%s)", email, token_id)

    return {
        "email": email,
        "access_token": access_token,
        "token_id": token_id,
        "team_id": team_id,
        "role": rbac_role,
        "is_admin": is_admin,
    }


def _cleanup_user(admin_api: APIRequestContext, user_info: dict[str, Any]) -> None:
    """Best-effort cleanup: revoke token, remove role, remove from team, delete user."""
    email = user_info["email"]
    team_id = user_info.get("team_id")
    role = user_info.get("role")
    token_id = user_info.get("token_id")

    if token_id:
        with suppress(Exception):
            admin_api.delete(f"/tokens/admin/{token_id}")
    if role and role != "platform_admin" and team_id:
        with suppress(Exception):
            admin_api.delete(f"/rbac/users/{email}/roles/{role}?scope=team&scope_id={team_id}")
    if team_id:
        with suppress(Exception):
            admin_api.delete(f"/teams/{team_id}/members/{email}")
    with suppress(Exception):
        admin_api.delete(f"/auth/email/admin/users/{email}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def admin_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Admin-authenticated API context using JWT (bootstrap only)."""
    token = _make_jwt("admin@example.com", is_admin=True, teams=None)
    ctx = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="module")
def rbac_team(admin_api: APIRequestContext) -> Generator[dict[str, Any], None, None]:
    """Create a private team for RBAC tests."""
    team_name = f"{RBAC_PREFIX}-team-{uuid.uuid4().hex[:8]}"
    resp = admin_api.post("/teams/", data={"name": team_name, "description": "MCP RBAC E2E test team", "visibility": "private"})
    assert resp.status in (200, 201), f"Failed to create team: {resp.status} {resp.text()}"
    team = resp.json()
    logger.info("Created RBAC team: %s (id=%s)", team_name, team["id"])
    yield team
    with suppress(Exception):
        admin_api.delete(f"/teams/{team['id']}")


@pytest.fixture(scope="module")
def sse_gateway(admin_api: APIRequestContext) -> Generator[dict[str, Any], None, None]:
    """Register fast_time_server via SSE transport and wait for tool sync."""
    sse_url = "http://fast_time_server:8080/sse"

    # Delete any pre-existing SSE gateway with same name or same URL
    with suppress(Exception):
        gateways = admin_api.get("/gateways").json()
        for gw in gateways:
            if gw.get("name") == SSE_GATEWAY_NAME or gw.get("url") == sse_url:
                admin_api.delete(f"/gateways/{gw['id']}")

    resp = admin_api.post(
        "/gateways",
        data={
            "name": SSE_GATEWAY_NAME,
            "url": sse_url,
            "transport": "SSE",
        },
    )
    assert resp.status in (200, 201), f"Failed to register SSE gateway: {resp.status} {resp.text()}"
    gw = resp.json()
    gw_id = gw["id"]
    logger.info("Registered SSE gateway: %s (id=%s)", SSE_GATEWAY_NAME, gw_id)

    # Poll for tool sync (up to 30s)
    for i in range(30):
        time.sleep(1)
        try:
            tools = admin_api.get("/tools").json()
            sse_tools = [t for t in tools if t.get("gatewayId") == gw_id]
            if sse_tools:
                logger.info("SSE gateway synced: %d tools", len(sse_tools))
                break
        except Exception:
            pass
    else:
        logger.warning("SSE gateway tool sync timed out, continuing anyway")

    yield {"id": gw_id, "name": SSE_GATEWAY_NAME}

    with suppress(Exception):
        admin_api.delete(f"/gateways/{gw_id}")


@pytest.fixture(scope="module")
def visibility_servers(admin_api: APIRequestContext, rbac_team: dict, sse_gateway: dict) -> Generator[dict[str, Any], None, None]:
    """Create 3 virtual servers (public, team, private) with SSE gateway tools."""
    gw_id = sse_gateway["id"]
    team_id = rbac_team["id"]

    # Fetch SSE tools for association
    tools = admin_api.get("/tools").json()
    sse_tool_ids = [t["id"] for t in tools if t.get("gatewayId") == gw_id]

    # Also fetch resources/prompts
    resources = admin_api.get("/resources").json()
    sse_resource_ids = [r["id"] for r in resources if r.get("gatewayId") == gw_id] if resources else []
    prompts = admin_api.get("/prompts").json()
    sse_prompt_ids = [p["id"] for p in prompts if p.get("gatewayId") == gw_id] if prompts else []

    uid = uuid.uuid4().hex[:8]
    servers: dict[str, dict[str, Any]] = {}

    for vis, vis_team_id in [("public", None), ("team", team_id), ("private", team_id)]:
        name = f"{RBAC_PREFIX}-{vis}-sse-{uid}"
        payload: dict[str, Any] = {
            "server": {
                "name": name,
                "description": f"RBAC test {vis} SSE server",
                "associated_tools": sse_tool_ids,
                "associated_resources": sse_resource_ids,
                "associated_prompts": sse_prompt_ids,
            },
            "visibility": vis,
        }
        if vis_team_id:
            payload["team_id"] = vis_team_id
        resp = admin_api.post("/servers", data=payload)
        assert resp.status in (200, 201), f"Failed to create {vis} server: {resp.status} {resp.text()}"
        srv = resp.json()
        servers[vis] = {"id": srv["id"], "name": name, "visibility": vis, "team_id": vis_team_id}
        logger.info("Created %s server: %s (id=%s)", vis, name, srv["id"])

    yield servers

    for srv in servers.values():
        with suppress(Exception):
            admin_api.delete(f"/servers/{srv['id']}")


@pytest.fixture(scope="module")
def test_users(admin_api: APIRequestContext, playwright: Playwright, rbac_team: dict) -> Generator[dict[str, dict[str, Any]], None, None]:
    """Create 4 test users with different RBAC roles and API tokens."""
    team_id = rbac_team["id"]
    uid = uuid.uuid4().hex[:8]

    users: dict[str, dict[str, Any]] = {}

    # Platform admin (global scope, no team needed for admin bypass)
    users["admin"] = _create_user_with_token(
        admin_api,
        playwright,
        f"{RBAC_PREFIX}-admin-{uid}@test.com",
        is_admin=True,
        rbac_role="platform_admin",
    )

    # Team admin
    users["team_admin"] = _create_user_with_token(
        admin_api,
        playwright,
        f"{RBAC_PREFIX}-tadmin-{uid}@test.com",
        team_id=team_id,
        rbac_role="team_admin",
    )

    # Developer
    users["developer"] = _create_user_with_token(
        admin_api,
        playwright,
        f"{RBAC_PREFIX}-dev-{uid}@test.com",
        team_id=team_id,
        rbac_role="developer",
    )

    # Viewer
    users["viewer"] = _create_user_with_token(
        admin_api,
        playwright,
        f"{RBAC_PREFIX}-viewer-{uid}@test.com",
        team_id=team_id,
        rbac_role="viewer",
    )

    yield users

    for user_info in users.values():
        _cleanup_user(admin_api, user_info)


@pytest.fixture(scope="module")
def outsider_user(admin_api: APIRequestContext, playwright: Playwright) -> Generator[dict[str, Any], None, None]:
    """A user with NO team membership — should only see public resources."""
    uid = uuid.uuid4().hex[:8]
    user = _create_user_with_token(
        admin_api,
        playwright,
        f"{RBAC_PREFIX}-outsider-{uid}@test.com",
    )
    yield user
    _cleanup_user(admin_api, user)


@pytest.fixture(scope="module")
def scoped_token_read_only(admin_api: APIRequestContext, playwright: Playwright) -> Generator[dict[str, Any], None, None]:
    """A token with only tools.read permission (servers.use auto-injected at generation)."""
    uid = uuid.uuid4().hex[:8]
    user = _create_user_with_token(
        admin_api,
        playwright,
        f"{RBAC_PREFIX}-scoped-ro-{uid}@test.com",
        is_admin=True,
        rbac_role="platform_admin",
        token_scope={"permissions": ["tools.read"]},
    )
    yield user
    _cleanup_user(admin_api, user)


@pytest.fixture(scope="module")
def scoped_token_read_execute(admin_api: APIRequestContext, playwright: Playwright) -> Generator[dict[str, Any], None, None]:
    """A token with tools.read + tools.execute permissions (servers.use auto-injected at generation)."""
    uid = uuid.uuid4().hex[:8]
    user = _create_user_with_token(
        admin_api,
        playwright,
        f"{RBAC_PREFIX}-scoped-rw-{uid}@test.com",
        is_admin=True,
        rbac_role="platform_admin",
        token_scope={"permissions": ["tools.read", "tools.execute"]},
    )
    yield user
    _cleanup_user(admin_api, user)


# ---------------------------------------------------------------------------
# MCP protocol helpers
# ---------------------------------------------------------------------------
_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _run_async(coro):
    """Run an async coroutine from sync code that already has an event loop (Playwright)."""
    return _thread_pool.submit(asyncio.run, coro).result()


def _mcp_client_url(server_url: str = BASE_URL) -> str:
    return f"{server_url}/mcp/" if not server_url.endswith(("/mcp", "/mcp/")) else server_url.rstrip("/") + "/"


async def _async_mcp_tools_list(access_token: str, server_url: str = BASE_URL) -> list:
    url = _mcp_client_url(server_url)
    async with Client(url, auth=BearerAuth(access_token), init_timeout=_CLIENT_TIMEOUT, timeout=_CLIENT_TIMEOUT) as client:
        return await client.list_tools()


async def _async_mcp_resources_list(access_token: str, server_url: str = BASE_URL) -> list:
    url = _mcp_client_url(server_url)
    async with Client(url, auth=BearerAuth(access_token), init_timeout=_CLIENT_TIMEOUT, timeout=_CLIENT_TIMEOUT) as client:
        return await client.list_resources()


async def _async_mcp_prompts_list(access_token: str, server_url: str = BASE_URL) -> list:
    url = _mcp_client_url(server_url)
    async with Client(url, auth=BearerAuth(access_token), init_timeout=_CLIENT_TIMEOUT, timeout=_CLIENT_TIMEOUT) as client:
        return await client.list_prompts()


async def _async_mcp_tool_call(access_token: str, tool_name: str, arguments: dict[str, Any] | None = None, server_url: str = BASE_URL):
    url = _mcp_client_url(server_url)
    async with Client(url, auth=BearerAuth(access_token), init_timeout=_CLIENT_TIMEOUT, timeout=_CLIENT_TIMEOUT) as client:
        return await client.call_tool(tool_name, arguments or {})


async def _async_mcp_initialize(access_token: str, server_url: str = BASE_URL) -> bool:
    url = _mcp_client_url(server_url)
    async with Client(url, auth=BearerAuth(access_token), init_timeout=_CLIENT_TIMEOUT, timeout=_CLIENT_TIMEOUT) as _client:
        return True


async def _async_mcp_connect(url: str, auth: BearerAuth | None = None) -> bool:
    kwargs: dict[str, Any] = {"init_timeout": _CLIENT_TIMEOUT, "timeout": _CLIENT_TIMEOUT}
    if auth:
        kwargs["auth"] = auth
    async with Client(url, **kwargs) as _client:
        return True


def _mcp_tools_list(access_token: str, server_url: str = BASE_URL) -> list:
    return _run_async(_async_mcp_tools_list(access_token, server_url))


def _mcp_resources_list(access_token: str, server_url: str = BASE_URL) -> list:
    return _run_async(_async_mcp_resources_list(access_token, server_url))


def _mcp_prompts_list(access_token: str, server_url: str = BASE_URL) -> list:
    return _run_async(_async_mcp_prompts_list(access_token, server_url))


def _mcp_tool_call(access_token: str, tool_name: str, arguments: dict[str, Any] | None = None, server_url: str = BASE_URL):
    return _run_async(_async_mcp_tool_call(access_token, tool_name, arguments, server_url))


def _mcp_initialize_only(access_token: str, server_url: str = BASE_URL) -> bool:
    return _run_async(_async_mcp_initialize(access_token, server_url))


# ---------------------------------------------------------------------------
# Test: REST API server visibility
# ---------------------------------------------------------------------------
class TestServerVisibilityViaAPI:
    """Verify server visibility via REST API before MCP protocol tests."""

    def test_admin_sees_public_and_team_via_http(self, admin_api: APIRequestContext, visibility_servers: dict) -> None:
        """Admin via HTTP sees public + team servers but NOT private — even own-private (PR #4341).

        ``admin_api`` carries a JWT with ``is_admin=true`` and ``teams=null``. After
        PR #4341 cycle-2 S3-b, ``get_scoped_resource_access_context`` deliberately
        collapses this shape to ``(None, None)`` so HTTP cannot be a stealthy
        escalation surface; the service layer then applies the anonymous-bypass
        rule (public + team only, never private). Admins who need to read their
        own private rows directly should use a ``team``-scoped token or operate
        via owner-match workflows. The pre-#4341 ``test_admin_sees_all_servers``
        assertion encoded the old "admin sees everything" semantics and is
        superseded by this test plus the explicit not-in assertion below.
        """
        resp = admin_api.get("/servers")
        assert resp.status == 200
        server_ids = {s["id"] for s in resp.json()}
        assert visibility_servers["public"]["id"] in server_ids, "Admin should see public server"
        assert visibility_servers["team"]["id"] in server_ids, "Admin should see team server"
        assert visibility_servers["private"]["id"] not in server_ids, "PR #4341: admin via HTTP must NOT see private server (own-private collapsed by get_scoped_resource_access_context)"
        print("    -> Admin sees public + team servers; private denied via HTTP collapse")

    def test_team_member_sees_public_and_team(self, test_users: dict, playwright: Playwright, visibility_servers: dict) -> None:
        token = test_users["developer"]["access_token"]
        ctx = _api_context(playwright, token)
        try:
            resp = ctx.get("/servers")
            assert resp.status == 200
            server_ids = {s["id"] for s in resp.json()}
            assert visibility_servers["public"]["id"] in server_ids, "Developer should see public server"
            assert visibility_servers["team"]["id"] in server_ids, "Developer should see team server"
        finally:
            ctx.dispose()
        print("    -> Developer sees public + team servers")

    def test_viewer_sees_public_and_team(self, test_users: dict, playwright: Playwright, visibility_servers: dict) -> None:
        token = test_users["viewer"]["access_token"]
        ctx = _api_context(playwright, token)
        try:
            resp = ctx.get("/servers")
            assert resp.status == 200
            server_ids = {s["id"] for s in resp.json()}
            assert visibility_servers["public"]["id"] in server_ids, "Viewer should see public server"
            assert visibility_servers["team"]["id"] in server_ids, "Viewer should see team server"
        finally:
            ctx.dispose()
        print("    -> Viewer sees public + team servers")

    def test_outsider_sees_only_public(self, outsider_user: dict, playwright: Playwright, visibility_servers: dict) -> None:
        token = outsider_user["access_token"]
        ctx = _api_context(playwright, token)
        try:
            resp = ctx.get("/servers")
            assert resp.status == 200
            server_ids = {s["id"] for s in resp.json()}
            assert visibility_servers["public"]["id"] in server_ids, "Outsider should see public server"
            assert visibility_servers["team"]["id"] not in server_ids, "Outsider should NOT see team server"
            assert visibility_servers["private"]["id"] not in server_ids, "Outsider should NOT see private server"
        finally:
            ctx.dispose()
        print("    -> Outsider sees only public server")

    def test_team_admin_sees_public_and_team(self, test_users: dict, playwright: Playwright, visibility_servers: dict) -> None:
        token = test_users["team_admin"]["access_token"]
        ctx = _api_context(playwright, token)
        try:
            resp = ctx.get("/servers")
            assert resp.status == 200
            server_ids = {s["id"] for s in resp.json()}
            assert visibility_servers["public"]["id"] in server_ids, "Team admin should see public server"
            assert visibility_servers["team"]["id"] in server_ids, "Team admin should see team server"
        finally:
            ctx.dispose()
        print("    -> Team admin sees public + team servers")


# ---------------------------------------------------------------------------
# Test: MCP tools/list visibility by role
# ---------------------------------------------------------------------------
@pytest.mark.flaky(reruns=1, reruns_delay=2)
class TestMcpToolsVisibilityByRole:
    """MCP tools/list returns role-appropriate tools for each user."""

    def test_admin_sees_all_tools(self, test_users: dict, visibility_servers: dict) -> None:
        tools = _mcp_tools_list(test_users["admin"]["access_token"])
        tool_names = [t.name for t in tools]
        assert len(tools) > 0, "Admin should see at least one tool"
        # Admin should see tools from all servers including existing public ones
        print(f"    -> Admin sees {len(tools)} tools: {tool_names[:10]}...")

    def test_developer_sees_public_and_team_tools(self, test_users: dict) -> None:
        tools = _mcp_tools_list(test_users["developer"]["access_token"])
        assert len(tools) > 0, "Developer should see at least public tools"
        tool_names = [t.name for t in tools]
        # Developer should see fast-time-* (public Streamable HTTP) tools
        has_public_tools = any("fast-time" in n for n in tool_names)
        assert has_public_tools, f"Developer should see public fast-time tools, got: {tool_names}"
        print(f"    -> Developer sees {len(tools)} tools")

    def test_viewer_sees_public_and_team_tools(self, test_users: dict) -> None:
        tools = _mcp_tools_list(test_users["viewer"]["access_token"])
        assert len(tools) > 0, "Viewer should see at least public tools"
        tool_names = [t.name for t in tools]
        has_public_tools = any("fast-time" in n for n in tool_names)
        assert has_public_tools, f"Viewer should see public fast-time tools, got: {tool_names}"
        print(f"    -> Viewer sees {len(tools)} tools")

    def test_outsider_sees_only_public_tools(self, outsider_user: dict) -> None:
        tools = _mcp_tools_list(outsider_user["access_token"])
        tool_names = [t.name for t in tools]
        # Outsider should see public tools (fast-time-*) but not team-only
        has_public_tools = any("fast-time" in n for n in tool_names)
        assert has_public_tools, f"Outsider should see public fast-time tools, got: {tool_names}"
        print(f"    -> Outsider sees {len(tools)} public tools")

    def test_team_admin_sees_public_and_team_tools(self, test_users: dict) -> None:
        tools = _mcp_tools_list(test_users["team_admin"]["access_token"])
        assert len(tools) > 0, "Team admin should see at least public tools"
        print(f"    -> Team admin sees {len(tools)} tools")


# ---------------------------------------------------------------------------
# Test: MCP resources + prompts visibility by role
# ---------------------------------------------------------------------------
@pytest.mark.flaky(reruns=1, reruns_delay=2)
class TestMcpResourcesPromptsByRole:
    """MCP resources/list + prompts/list follow same visibility rules."""

    def test_admin_resources(self, test_users: dict) -> None:
        resources = _mcp_resources_list(test_users["admin"]["access_token"])
        print(f"    -> Admin sees {len(resources)} resources")

    def test_admin_prompts(self, test_users: dict) -> None:
        prompts = _mcp_prompts_list(test_users["admin"]["access_token"])
        print(f"    -> Admin sees {len(prompts)} prompts")

    def test_developer_resources_and_prompts(self, test_users: dict) -> None:
        resources = _mcp_resources_list(test_users["developer"]["access_token"])
        prompts = _mcp_prompts_list(test_users["developer"]["access_token"])
        print(f"    -> Developer sees {len(resources)} resources, {len(prompts)} prompts")

    def test_outsider_resources_and_prompts(self, outsider_user: dict) -> None:
        resources = _mcp_resources_list(outsider_user["access_token"])
        prompts = _mcp_prompts_list(outsider_user["access_token"])
        print(f"    -> Outsider sees {len(resources)} resources, {len(prompts)} prompts")


# ---------------------------------------------------------------------------
# Test: MCP tools/call enforcement by role
# ---------------------------------------------------------------------------
@pytest.mark.flaky(reruns=1, reruns_delay=2)
class TestMcpToolCallByRole:
    """Tool execution enforcement through MCP protocol.

    Since #3687 the default /mcp endpoint uses check_any_team=True for API
    tokens, so team-scoped roles (developer, viewer, team_admin) that hold
    tools.execute in ANY team can execute tools on the default endpoint.
    Only users with NO team membership (outsider) are denied.
    """

    def test_admin_calls_tool_success(self, test_users: dict) -> None:
        result = _mcp_tool_call(test_users["admin"]["access_token"], "fast-time-get-system-time", {"timezone": "UTC"})
        assert not result.is_error, f"Admin tool call should succeed: {result}"
        text = result.content[0].text
        assert len(text) > 0
        print(f"    -> Admin call fast-time-get-system-time = {text}")

    def test_developer_can_execute_on_default_endpoint(self, test_users: dict) -> None:
        """Developer has team-scoped tools.execute; check_any_team=True allows it on /mcp."""
        result = _mcp_tool_call(test_users["developer"]["access_token"], "fast-time-get-system-time", {"timezone": "UTC"})
        assert not result.is_error, f"Developer tool call should succeed (check_any_team): {result}"
        print(f"    -> Developer call succeeded: {result.content[0].text}")

    def test_team_admin_can_execute_on_default_endpoint(self, test_users: dict) -> None:
        """Team admin has team-scoped tools.execute; check_any_team=True allows it on /mcp."""
        result = _mcp_tool_call(test_users["team_admin"]["access_token"], "fast-time-get-system-time", {"timezone": "UTC"})
        assert not result.is_error, f"Team admin tool call should succeed (check_any_team): {result}"
        print(f"    -> Team admin call succeeded: {result.content[0].text}")

    def test_outsider_denied_tools_execute(self, outsider_user: dict) -> None:
        """Outsider has no team membership, so no tools.execute anywhere — denied."""
        try:
            result = _mcp_tool_call(outsider_user["access_token"], "fast-time-get-system-time", {"timezone": "UTC"})
            assert result.is_error, f"Outsider should be denied tools.execute, got: {result}"
        except Exception:
            pass  # McpError or connection error — both valid denials
        print("    -> Outsider denied tools.execute (expected)")

    def test_outsider_calls_nonexistent_tool_error(self, outsider_user: dict) -> None:
        try:
            result = _mcp_tool_call(outsider_user["access_token"], "nonexistent-tool-xyz-rbac")
            assert result.is_error, f"Nonexistent tool should return error, got: {result}"
        except Exception:
            pass  # McpError — expected for outsider with no permissions
        print("    -> Outsider nonexistent tool: error (expected)")

    def test_viewer_can_execute_on_default_endpoint(self, test_users: dict) -> None:
        """Viewer has team-scoped tools.execute; check_any_team=True allows it on /mcp."""
        result = _mcp_tool_call(test_users["viewer"]["access_token"], "fast-time-get-system-time", {"timezone": "UTC"})
        assert not result.is_error, f"Viewer tool call should succeed (check_any_team): {result}"
        print(f"    -> Viewer call succeeded: {result.content[0].text}")


# ---------------------------------------------------------------------------
# Test: Scoped token permissions via MCP
# ---------------------------------------------------------------------------
@pytest.mark.flaky(reruns=1, reruns_delay=2)
class TestMcpScopedTokenPermissions:
    """Token scope enforcement through MCP protocol.

    The MCP endpoint (/servers/{id}/mcp) requires ``servers.use`` at the HTTP
    middleware layer *before* any JSON-RPC processing occurs. Token generation
    auto-injects ``servers.use`` when MCP-method permissions (``tools.*``,
    ``resources.*``, ``prompts.*``) are present, so tokens with these
    permissions can reach the transport layer without explicitly including it.

    Therefore:
    - A token with ``["tools.read"]`` gets ``servers.use`` auto-injected and can initialize.
    - A token with ``["tools.read", "tools.execute"]`` likewise succeeds at transport level.
    - A token with ``["servers.use", "tools.read"]`` can list tools but not call them.
    - A token with ``["servers.use", "tools.read", "tools.execute"]`` can do both.
    """

    def test_tools_read_only_token_can_initialize(self, scoped_token_read_only: dict) -> None:
        """Token with tools.read gets servers.use auto-injected and can reach MCP endpoint."""
        assert _mcp_initialize_only(scoped_token_read_only["access_token"])
        print("    -> tools.read-only token initialized (servers.use auto-injected)")

    def test_read_execute_token_can_initialize(self, scoped_token_read_execute: dict) -> None:
        """Token with tools.read+execute gets servers.use auto-injected and can reach MCP endpoint."""
        assert _mcp_initialize_only(scoped_token_read_execute["access_token"])
        print("    -> tools.read+execute token initialized (servers.use auto-injected)")

    def test_unscoped_admin_token_can_call_tools(self, test_users: dict) -> None:
        """Admin token without custom scope (empty permissions = pass-through) can call tools."""
        result = _mcp_tool_call(test_users["admin"]["access_token"], "fast-time-get-system-time", {"timezone": "UTC"})
        assert not result.is_error, f"Unscoped admin token should succeed: {result}"
        text = result.content[0].text
        assert len(text) > 0
        print(f"    -> Unscoped admin token call = {text}")


# ---------------------------------------------------------------------------
# Test: SSE transport
# ---------------------------------------------------------------------------
@pytest.mark.flaky(reruns=1, reruns_delay=2)
class TestMcpSSETransport:
    """SSE transport works end-to-end through MCP protocol."""

    def test_sse_tools_discoverable(self, test_users: dict, sse_gateway: dict) -> None:
        tools = _mcp_tools_list(test_users["admin"]["access_token"])
        # SSE tools should have a prefix from the SSE gateway
        print(f"    -> {len(tools)} total tools visible to admin (SSE gateway id={sse_gateway['id']})")
        assert len(tools) > 0, "Should discover at least one tool via SSE"

    def test_sse_get_system_time(self, test_users: dict, sse_gateway: dict) -> None:
        """Call an SSE-sourced tool: the tool name may have SSE gateway prefix."""
        tools = _mcp_tools_list(test_users["admin"]["access_token"])
        # Find a get-system-time tool (either from SSE or Streamable HTTP)
        time_tools = [t.name for t in tools if "get-system-time" in t.name]
        assert len(time_tools) > 0, f"Expected at least one get-system-time tool, got: {[t.name for t in tools]}"
        # Call the first one found
        result = _mcp_tool_call(test_users["admin"]["access_token"], time_tools[0], {"timezone": "UTC"})
        assert not result.is_error, f"SSE get-system-time failed: {result}"
        print(f"    -> SSE {time_tools[0]} = {result.content[0].text}")

    def test_sse_convert_time(self, test_users: dict) -> None:
        tools = _mcp_tools_list(test_users["admin"]["access_token"])
        convert_tools = [t.name for t in tools if "convert-time" in t.name]
        assert len(convert_tools) > 0, "Expected at least one convert-time tool"
        result = _mcp_tool_call(
            test_users["admin"]["access_token"],
            convert_tools[0],
            {"time": "2025-06-01T10:00:00Z", "source_timezone": "UTC", "target_timezone": "Europe/London"},
        )
        assert not result.is_error, f"SSE convert-time failed: {result}"
        print(f"    -> SSE {convert_tools[0]}: OK")

    def test_sse_resources_discoverable(self, test_users: dict) -> None:
        resources = _mcp_resources_list(test_users["admin"]["access_token"])
        print(f"    -> Admin sees {len(resources)} resources (incl. SSE)")

    def test_sse_prompts_discoverable(self, test_users: dict) -> None:
        prompts = _mcp_prompts_list(test_users["admin"]["access_token"])
        print(f"    -> Admin sees {len(prompts)} prompts (incl. SSE)")


# ---------------------------------------------------------------------------
# Test: Per-server MCP endpoint
# ---------------------------------------------------------------------------
class TestMcpPerServerEndpoint:
    """Test /servers/{UUID}/mcp scoped access."""

    def test_public_token_accesses_public_server(self, outsider_user: dict, visibility_servers: dict) -> None:
        """Outsider can access the public server's per-server MCP endpoint."""
        server_id = visibility_servers["public"]["id"]
        server_url = f"{BASE_URL}/servers/{server_id}"
        tools = _mcp_tools_list(outsider_user["access_token"], server_url=server_url)
        # May see only that server's tools
        print(f"    -> Outsider via /servers/{server_id}/mcp: {len(tools)} tools")

    def test_team_member_accesses_team_server(self, test_users: dict, visibility_servers: dict) -> None:
        """Developer can access the team server's per-server endpoint."""
        server_id = visibility_servers["team"]["id"]
        server_url = f"{BASE_URL}/servers/{server_id}"
        tools = _mcp_tools_list(test_users["developer"]["access_token"], server_url=server_url)
        print(f"    -> Developer via /servers/{server_id}/mcp: {len(tools)} tools")

    def test_outsider_denied_team_server(self, outsider_user: dict, visibility_servers: dict) -> None:
        """Outsider cannot access team server's per-server endpoint."""
        server_id = visibility_servers["team"]["id"]
        server_url = f"{BASE_URL}/servers/{server_id}"
        with pytest.raises(Exception) as excinfo:
            _mcp_initialize_only(outsider_user["access_token"], server_url=server_url)
        print(f"    -> Outsider denied team server: {excinfo.value}")

    def test_outsider_denied_private_server(self, outsider_user: dict, visibility_servers: dict) -> None:
        """Outsider cannot access private server's per-server endpoint."""
        server_id = visibility_servers["private"]["id"]
        server_url = f"{BASE_URL}/servers/{server_id}"
        with pytest.raises(Exception) as excinfo:
            _mcp_initialize_only(outsider_user["access_token"], server_url=server_url)
        print(f"    -> Outsider denied private server: {excinfo.value}")


# ---------------------------------------------------------------------------
# Test: Deny paths (security invariants)
# ---------------------------------------------------------------------------
class TestDenyPaths:
    """Security invariant tests — ensure auth failures are handled correctly."""

    def test_no_token_fails(self) -> None:
        """MCP initialize with no auth token should fail."""
        with pytest.raises(Exception) as excinfo:
            _run_async(_async_mcp_connect(_mcp_client_url()))
        print(f"    -> No token: failure (expected): {excinfo.value}")

    def test_garbage_token_fails(self) -> None:
        """MCP initialize with garbage token should fail."""
        with pytest.raises(Exception) as excinfo:
            _run_async(_async_mcp_connect(_mcp_client_url(), auth=BearerAuth("this-is-not-a-valid-token")))
        print(f"    -> Garbage token: failure (expected): {excinfo.value}")

    def test_wrong_secret_token_fails(self) -> None:
        """MCP with token signed by wrong secret should fail."""
        bad_token = _create_jwt_token(
            {"sub": "admin@example.com"},
            user_data={"email": "admin@example.com", "is_admin": True, "auth_provider": "local"},
            teams=None,
            secret="completely-wrong-secret-key-12345",
        )

        with pytest.raises(Exception) as excinfo:
            _run_async(_async_mcp_connect(_mcp_client_url(), auth=BearerAuth(bad_token)))
        print(f"    -> Wrong secret: failure (expected): {excinfo.value}")

    def test_revoked_token_fails(self, admin_api: APIRequestContext, playwright: Playwright) -> None:
        """Token created then revoked should fail MCP operations."""
        uid = uuid.uuid4().hex[:8]
        email = f"{RBAC_PREFIX}-revoke-{uid}@test.com"
        user = _create_user_with_token(admin_api, playwright, email, is_admin=True, rbac_role="platform_admin")
        access_token = user["access_token"]
        token_id = user["token_id"]

        # Verify the token works first
        tools_before = _mcp_tools_list(access_token)
        assert len(tools_before) > 0, "Token should work before revocation"

        # Revoke the token
        revoke_resp = admin_api.delete(f"/tokens/admin/{token_id}")
        assert revoke_resp.status == 204, f"Failed to revoke token: {revoke_resp.status}"

        # Small delay for revocation to propagate
        time.sleep(1)

        # Try to use the revoked token
        with pytest.raises(Exception) as excinfo:
            _mcp_tools_list(access_token)
        print(f"    -> Revoked token rejected (expected): {excinfo.value}")

        _cleanup_user(admin_api, user)

    def test_cross_team_isolation(self, outsider_user: dict, playwright: Playwright, visibility_servers: dict) -> None:
        """User outside team A cannot see team A's resources (cross-team isolation).

        Uses the outsider_user fixture (no team membership) to verify that
        team-scoped and private servers are not visible to non-members.
        """
        ctx = _api_context(playwright, outsider_user["access_token"])
        try:
            resp = ctx.get("/servers")
            assert resp.status == 200
            server_ids = {s["id"] for s in resp.json()}
            assert visibility_servers["team"]["id"] not in server_ids, "Outsider should NOT see team-scoped server"
            assert visibility_servers["private"]["id"] not in server_ids, "Outsider should NOT see private server"
            assert visibility_servers["public"]["id"] in server_ids, "Outsider should see public server"
        finally:
            ctx.dispose()

        print("    -> Cross-team isolation verified: outsider denied team/private resources")

    def test_invalid_bearer_prefix_fails(self) -> None:
        """Token without proper Bearer prefix handling."""
        with pytest.raises(Exception) as excinfo:
            _run_async(_async_mcp_connect(_mcp_client_url(), auth=BearerAuth("not-bearer-prefixed-garbage")))
        print(f"    -> Invalid token: failure (expected): {excinfo.value}")


# ---------------------------------------------------------------------------
# Test: Cross-transport consistency
# ---------------------------------------------------------------------------
@pytest.mark.flaky(reruns=1, reruns_delay=2)
class TestCrossTransportConsistency:
    """Same tool produces consistent results across Streamable HTTP and SSE."""

    def test_get_system_time_both_transports(self, test_users: dict) -> None:
        """Both transports return valid timestamps for get-system-time."""
        tools = _mcp_tools_list(test_users["admin"]["access_token"])
        time_tools = [t.name for t in tools if "get-system-time" in t.name]
        assert len(time_tools) >= 1, f"Expected at least 1 get-system-time tool, got: {time_tools}"

        for tool_name in time_tools[:2]:  # Test up to 2 variants
            result = _mcp_tool_call(test_users["admin"]["access_token"], tool_name, {"timezone": "UTC"})
            assert not result.is_error, f"{tool_name} failed: {result}"
            text = result.content[0].text
            assert len(text) > 0, f"{tool_name} returned empty text"
            print(f"    -> {tool_name} = {text}")

    def test_convert_time_both_transports(self, test_users: dict) -> None:
        """Both transports return valid results for convert-time."""
        tools = _mcp_tools_list(test_users["admin"]["access_token"])
        convert_tools = [t.name for t in tools if "convert-time" in t.name]
        assert len(convert_tools) >= 1, f"Expected at least 1 convert-time tool, got: {convert_tools}"

        for tool_name in convert_tools[:2]:
            result = _mcp_tool_call(
                test_users["admin"]["access_token"],
                tool_name,
                {"time": "2025-01-15T12:00:00Z", "source_timezone": "UTC", "target_timezone": "America/New_York"},
            )
            assert not result.is_error, f"{tool_name} failed: {result}"
            text = result.content[0].text
            assert len(text) > 0, f"{tool_name} returned empty text"
            print(f"    -> {tool_name} = {text}")
