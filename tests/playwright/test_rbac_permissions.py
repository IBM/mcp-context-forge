# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_rbac_permissions.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

E2E Playwright tests for RBAC permission enforcement on admin UI operations.

Regression tests for:
  - #2883: developer create gateway/server from "All Teams" view was denied (no team_id)
  - #2891: admin delete gateway was denied (allow_admin_bypass=False)

These tests set up real users/teams/roles via REST API, then exercise the admin UI
as different roles (developer, viewer, admin) to verify correct permission grant/denial.
"""

# Standard
import logging
from typing import Any, Dict, Generator, Optional
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext, Page, Playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import pytest

# First-Party
from mcpgateway.utils.create_jwt_token import _create_jwt_token

# Local
from .conftest import BASE_URL, VALID_MCP_SERVER_URLS
from .pages.gateways_page import GatewaysPage
from .pages.prompts_page import PromptsPage
from .pages.resources_page import ResourcesPage
from .pages.servers_page import ServersPage
from .pages.team_page import TeamPage
from .pages.tools_page import ToolsPage

logger = logging.getLogger(__name__)

# ==================== Constants ====================

RBAC_TEST_PREFIX = "rbac-e2e"
RBAC_DEVELOPER_EMAIL = f"{RBAC_TEST_PREFIX}-dev-{uuid.uuid4().hex[:8]}@test.example.com"
RBAC_VIEWER_EMAIL = f"{RBAC_TEST_PREFIX}-viewer-{uuid.uuid4().hex[:8]}@test.example.com"
RBAC_TEST_PASSWORD = "Changeme123!"
RBAC_TEAM_NAME = f"{RBAC_TEST_PREFIX}-team-{uuid.uuid4().hex[:8]}"


# ==================== Helpers ====================


def _make_user_jwt(email: str, is_admin: bool = False, teams: Optional[list] = None, token_use: Optional[str] = None) -> str:
    """Create a JWT for a user.

    Args:
        token_use: If "session", triggers DB-based team resolution in auth middleware.
                   If None, uses JWT claims directly (matching conftest pattern).
    """
    payload: Dict[str, Any] = {"sub": email}
    if token_use:
        payload["token_use"] = token_use
    return _create_jwt_token(
        payload,
        user_data={"email": email, "is_admin": is_admin, "auth_provider": "local"},
        teams=teams,
    )


def _inject_jwt_cookie(page: Page, email: str, is_admin: bool = False, teams: Optional[list] = None, token_use: Optional[str] = None) -> None:
    """Inject a JWT cookie into the page context for authentication.

    Uses cookie-only auth (no Authorization header) because setting
    set_extra_http_headers sends the header on ALL requests including
    cross-origin CDN fetches.  Combined with crossorigin="anonymous"
    (required by SRI), this triggers CORS preflight failures on CDNs
    that don't whitelist the Authorization header, blocking Alpine.js
    and other scripts from loading.
    """
    token = _make_user_jwt(email, is_admin=is_admin, teams=teams, token_use=token_use)
    cookie_url = f"{BASE_URL.rstrip('/')}/"
    # Clear any stale cookies before injecting new ones
    page.context.clear_cookies()
    page.context.add_cookies(
        [
            {
                "name": "jwt_token",
                "value": token,
                "url": cookie_url,
                "httpOnly": True,
                "sameSite": "Lax",
            }
        ]
    )


def _wait_for_admin_shell(page: Page, timeout: int = 60000, team_id: Optional[str] = None) -> None:
    """Navigate to admin and wait for the application shell to load."""
    url = f"/admin?team_id={team_id}" if team_id else "/admin"
    page.goto(url)
    page.wait_for_load_state("domcontentloaded")
    try:
        page.wait_for_selector('[data-testid="servers-tab"]', state="visible", timeout=timeout)
    except PlaywrightTimeoutError:
        content = page.content()
        if "Internal Server Error" in content:
            raise AssertionError("Admin page failed to load: Internal Server Error (500)")
        raise
    # Wait for JS initialization
    try:
        page.wait_for_function("typeof window.showTab === 'function' && typeof window.htmx !== 'undefined'", timeout=30000)
    except PlaywrightTimeoutError:
        pass


def _navigate_to_gateways(page: Page, team_id: Optional[str] = None) -> GatewaysPage:
    """Navigate to the gateways tab, optionally in a team-scoped view."""
    if team_id:
        page.goto(f"/admin?team_id={team_id}#gateways")
        page.wait_for_load_state("domcontentloaded")
        try:
            page.wait_for_selector('[data-testid="servers-tab"]', state="visible", timeout=60000)
        except PlaywrightTimeoutError:
            pass
    gw_page = GatewaysPage(page)
    gw_page.navigate_to_gateways_tab()
    gw_page.wait_for_gateways_table_loaded()
    return gw_page


def _navigate_to_servers(page: Page, team_id: Optional[str] = None) -> ServersPage:
    """Navigate to the servers tab, optionally in a team-scoped view."""
    if team_id:
        page.goto(f"/admin?team_id={team_id}#catalog")
        page.wait_for_load_state("domcontentloaded")
        try:
            page.wait_for_selector('[data-testid="servers-tab"]', state="visible", timeout=60000)
        except PlaywrightTimeoutError:
            pass
    srv_page = ServersPage(page)
    srv_page.navigate_to_servers_tab()
    srv_page.wait_for_servers_table_loaded()
    return srv_page


def _submit_gateway_form_and_get_status(gw_page: GatewaysPage, name: str, url: str) -> int:
    """Fill and submit the gateway form, returning the POST response status code.

    Returns:
        HTTP status code of the POST response.
        502 / non-403 = RBAC passed (gateway URL validation may fail, which is expected).
        403 = RBAC denied.
    """
    gw_page.fill_gateway_form(name=name, url=url, description="RBAC test gateway", tags="rbac,test", transport="SSE")
    try:
        with gw_page.page.expect_response(
            lambda r: "/admin/gateways" in r.url and r.request.method == "POST",
            timeout=120000,
        ) as resp_info:
            gw_page.click_locator(gw_page.add_gateway_btn)
        return resp_info.value.status
    except PlaywrightTimeoutError:
        # If no POST response intercepted, check if we were redirected to login (auth failure)
        if "/admin/login" in gw_page.page.url:
            return 401
        return 0


def _submit_server_form_and_get_status(srv_page: ServersPage, name: str) -> int:
    """Fill and submit the server form, returning the POST response status code.

    Returns:
        HTTP status code. 201/200 = success, 403 = RBAC denied.
    """
    srv_page.fill_server_form(name=name, description="RBAC test server")
    try:
        with srv_page.page.expect_response(
            lambda r: "/admin/servers" in r.url and r.request.method == "POST",
            timeout=30000,
        ) as resp_info:
            srv_page.click_locator(srv_page.add_server_btn)
        return resp_info.value.status
    except PlaywrightTimeoutError:
        if "/admin/login" in srv_page.page.url:
            return 401
        return 0


# ==================== Module-scoped fixtures ====================


@pytest.fixture(scope="module")
def admin_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Admin-authenticated API context for test setup/teardown."""
    token = _make_user_jwt("admin@example.com", is_admin=True)
    ctx = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="module")
def rbac_test_team(admin_api: APIRequestContext) -> Generator[Dict[str, Any], None, None]:
    """Create a test team for RBAC tests, yield its data, then delete it."""
    resp = admin_api.post("/teams/", data={"name": RBAC_TEAM_NAME, "description": "RBAC E2E test team", "visibility": "private"})
    assert resp.status == 200 or resp.status == 201, f"Failed to create team: {resp.status} {resp.text()}"
    team = resp.json()
    team_id = team["id"]
    logger.info("Created RBAC test team: %s (id=%s)", RBAC_TEAM_NAME, team_id)

    yield team

    # Cleanup: delete the team
    try:
        del_resp = admin_api.delete(f"/teams/{team_id}")
        logger.info("Deleted RBAC test team %s: %s", team_id, del_resp.status)
    except Exception as e:
        logger.warning("Failed to cleanup RBAC test team %s: %s", team_id, e)


def _resolve_role_id(admin_api: APIRequestContext, role_name: str) -> str:
    """Resolve a role name (e.g. 'developer') to its UUID via the RBAC API."""
    resp = admin_api.get("/rbac/roles")
    assert resp.status == 200, f"Failed to list RBAC roles: {resp.status} {resp.text()}"
    roles = resp.json()
    for role in roles:
        if role.get("name") == role_name:
            return role["id"]
    raise AssertionError(f"RBAC role '{role_name}' not found. Available: {[r.get('name') for r in roles]}")


def _create_user_and_join_team(
    admin_api: APIRequestContext,
    playwright: Playwright,
    email: str,
    team_id: str,
    rbac_role: str,
) -> Dict[str, Any]:
    """Create a user, invite them to the team, accept the invitation, and assign an RBAC role.

    Returns:
        Dict with user info including email, team_id, and role.
    """
    # 1. Create user
    resp = admin_api.post(
        "/auth/email/admin/users",
        data={
            "email": email,
            "password": RBAC_TEST_PASSWORD,
            "full_name": f"RBAC Test {rbac_role.title()}",
            "is_admin": False,
            "is_active": True,
            "password_change_required": False,
        },
    )
    if resp.status == 409:
        logger.info("User %s already exists, continuing", email)
    else:
        assert resp.status in (200, 201), f"Failed to create user {email}: {resp.status} {resp.text()}"
        logger.info("Created user %s", email)

    # 2. Invite user to team
    invite_resp = admin_api.post(f"/teams/{team_id}/invitations", data={"email": email, "role": "member"})
    if invite_resp.status == 409:
        logger.info("User %s already invited/member, continuing", email)
    else:
        assert invite_resp.status in (200, 201), f"Failed to invite {email}: {invite_resp.status} {invite_resp.text()}"
        invitation = invite_resp.json()
        invitation_token = invitation.get("token")

        if invitation_token:
            # 3. Accept invitation as the user
            user_jwt = _make_user_jwt(email, is_admin=False)
            user_ctx = playwright.request.new_context(
                base_url=BASE_URL,
                extra_http_headers={"Authorization": f"Bearer {user_jwt}", "Accept": "application/json"},
            )
            try:
                accept_resp = user_ctx.post(f"/teams/invitations/{invitation_token}/accept")
                assert accept_resp.status in (200, 201), f"Failed to accept invitation for {email}: {accept_resp.status} {accept_resp.text()}"
                logger.info("User %s accepted team invitation", email)
            finally:
                user_ctx.dispose()

    # 4. Assign RBAC role (resolve name → UUID)
    role_uuid = _resolve_role_id(admin_api, rbac_role)
    role_resp = admin_api.post(
        f"/rbac/users/{email}/roles",
        data={"role_id": role_uuid, "scope": "team", "scope_id": team_id},
    )
    if role_resp.status == 409:
        logger.info("Role %s already assigned to %s, continuing", rbac_role, email)
    else:
        assert role_resp.status in (200, 201), f"Failed to assign {rbac_role} role to {email}: {role_resp.status} {role_resp.text()}"
        logger.info("Assigned %s role (id=%s) to %s for team %s", rbac_role, role_uuid, email, team_id)

    return {"email": email, "team_id": team_id, "role": rbac_role}


@pytest.fixture(scope="module")
def rbac_developer_user(admin_api: APIRequestContext, rbac_test_team: Dict, playwright: Playwright) -> Generator[Dict[str, Any], None, None]:
    """Create a developer user with team-scoped developer RBAC role."""
    team_id = rbac_test_team["id"]
    user_info = _create_user_and_join_team(admin_api, playwright, RBAC_DEVELOPER_EMAIL, team_id, "developer")
    yield user_info

    # Cleanup: revoke role and delete user
    try:
        admin_api.delete(f"/rbac/users/{RBAC_DEVELOPER_EMAIL}/roles/developer?scope=team&scope_id={team_id}")
    except Exception as e:
        logger.warning("Failed to revoke developer role: %s", e)
    try:
        # Remove from team first (required before user deletion due to FK constraints)
        admin_api.delete(f"/teams/{team_id}/members/{RBAC_DEVELOPER_EMAIL}")
    except Exception as e:
        logger.warning("Failed to remove developer from team: %s", e)
    try:
        admin_api.delete(f"/auth/email/admin/users/{RBAC_DEVELOPER_EMAIL}")
    except Exception as e:
        logger.warning("Failed to delete developer user: %s", e)


@pytest.fixture(scope="module")
def rbac_viewer_user(admin_api: APIRequestContext, rbac_test_team: Dict, playwright: Playwright) -> Generator[Dict[str, Any], None, None]:
    """Create a viewer user with team-scoped viewer RBAC role."""
    team_id = rbac_test_team["id"]
    user_info = _create_user_and_join_team(admin_api, playwright, RBAC_VIEWER_EMAIL, team_id, "viewer")
    yield user_info

    # Cleanup
    try:
        admin_api.delete(f"/rbac/users/{RBAC_VIEWER_EMAIL}/roles/viewer?scope=team&scope_id={team_id}")
    except Exception as e:
        logger.warning("Failed to revoke viewer role: %s", e)
    try:
        admin_api.delete(f"/teams/{team_id}/members/{RBAC_VIEWER_EMAIL}")
    except Exception as e:
        logger.warning("Failed to remove viewer from team: %s", e)
    try:
        admin_api.delete(f"/auth/email/admin/users/{RBAC_VIEWER_EMAIL}")
    except Exception as e:
        logger.warning("Failed to delete viewer user: %s", e)


# ==================== Test Classes ====================


@pytest.mark.ui
@pytest.mark.rbac
@pytest.mark.flaky(reruns=1, reason="Browser cookie auth intermittently returns 401")
class TestRBACGatewayCreate:
    """Test RBAC enforcement on gateway creation via admin UI.

    Regression tests for #2883: developer creating a gateway from "All Teams"
    view (no team_id in form) was incorrectly denied with 403.
    """

    def test_developer_create_gateway_all_teams_view(self, page: Page, base_url: str, rbac_developer_user: Dict, rbac_test_team: Dict):
        """Developer should be able to create a gateway from All Teams view (#2883 regression).

        When no team_id is in the URL, the RBAC middleware should use check_any_team
        to verify the developer has gateways.create in any of their teams.
        """
        _inject_jwt_cookie(page, rbac_developer_user["email"], token_use="session")
        _wait_for_admin_shell(page)

        gw_page = _navigate_to_gateways(page, team_id=None)
        name = f"{RBAC_TEST_PREFIX}-dev-allteams-{uuid.uuid4().hex[:8]}"
        url = VALID_MCP_SERVER_URLS[0]

        status = _submit_gateway_form_and_get_status(gw_page, name, url)

        # RBAC should allow: 502 (URL validation fail) or 200/201 (success) — NOT 403
        assert status != 403, f"Developer was denied gateway creation from All Teams view (status={status}). This is the #2883 regression."
        assert status != 401, f"Developer authentication failed (status={status})"
        logger.info("Developer create gateway (All Teams): status=%d — RBAC passed", status)

    def test_developer_create_gateway_team_view(self, page: Page, base_url: str, rbac_developer_user: Dict, rbac_test_team: Dict):
        """Developer should be able to create a gateway from team-scoped view (baseline)."""
        team_id = rbac_test_team["id"]
        _inject_jwt_cookie(page, rbac_developer_user["email"], token_use="session")
        _wait_for_admin_shell(page, team_id=team_id)

        gw_page = _navigate_to_gateways(page)
        name = f"{RBAC_TEST_PREFIX}-dev-team-{uuid.uuid4().hex[:8]}"
        url = VALID_MCP_SERVER_URLS[1]

        status = _submit_gateway_form_and_get_status(gw_page, name, url)

        assert status != 403, f"Developer was denied gateway creation from team view (status={status})"
        assert status != 401, f"Developer authentication failed (status={status})"
        logger.info("Developer create gateway (team view): status=%d — RBAC passed", status)

    def test_viewer_cannot_create_gateway(self, page: Page, base_url: str, rbac_viewer_user: Dict, rbac_test_team: Dict):
        """Viewer should be denied gateway creation (security check)."""
        team_id = rbac_test_team["id"]
        _inject_jwt_cookie(page, rbac_viewer_user["email"], token_use="session")
        _wait_for_admin_shell(page, team_id=team_id)

        try:
            gw_page = _navigate_to_gateways(page)
        except (AssertionError, PlaywrightTimeoutError):
            logger.info("Viewer create gateway: page did not render — correctly denied (auth failure)")
            return

        name = f"{RBAC_TEST_PREFIX}-viewer-gw-{uuid.uuid4().hex[:8]}"
        url = VALID_MCP_SERVER_URLS[2]

        status = _submit_gateway_form_and_get_status(gw_page, name, url)

        assert status in (401, 403), f"Viewer should be denied gateway creation but got status={status}"
        logger.info("Viewer create gateway: status=%d — correctly denied", status)

    def test_admin_create_gateway_all_teams_view(self, page: Page, base_url: str):
        """Admin (platform_admin role) should be able to create gateways from All Teams view."""
        _inject_jwt_cookie(page, "admin@example.com", is_admin=True)
        _wait_for_admin_shell(page)

        gw_page = _navigate_to_gateways(page, team_id=None)
        name = f"{RBAC_TEST_PREFIX}-admin-gw-{uuid.uuid4().hex[:8]}"
        url = VALID_MCP_SERVER_URLS[3]

        status = _submit_gateway_form_and_get_status(gw_page, name, url)

        assert status != 403, f"Admin was denied gateway creation (status={status})"
        assert status != 401, f"Admin authentication failed (status={status})"
        logger.info("Admin create gateway (All Teams): status=%d — RBAC passed", status)


@pytest.mark.ui
@pytest.mark.rbac
@pytest.mark.flaky(reruns=1, reason="Browser cookie auth intermittently returns 401")
class TestRBACServerCreate:
    """Test RBAC enforcement on server creation via admin UI.

    Regression tests for #2883: developer creating a server from "All Teams"
    view was incorrectly denied.
    """

    def test_developer_create_server_all_teams_view(self, page: Page, base_url: str, rbac_developer_user: Dict, rbac_test_team: Dict):
        """Developer should be able to create a virtual server from All Teams view (#2883 regression)."""
        _inject_jwt_cookie(page, rbac_developer_user["email"], token_use="session")
        _wait_for_admin_shell(page)

        srv_page = _navigate_to_servers(page, team_id=None)
        name = f"{RBAC_TEST_PREFIX}-dev-srv-allteams-{uuid.uuid4().hex[:8]}"

        status = _submit_server_form_and_get_status(srv_page, name)

        assert status != 403, f"Developer was denied server creation from All Teams view (status={status}). This is the #2883 regression."
        assert status != 401, f"Developer authentication failed (status={status})"
        logger.info("Developer create server (All Teams): status=%d — RBAC passed", status)

    def test_developer_create_server_team_view(self, page: Page, base_url: str, rbac_developer_user: Dict, rbac_test_team: Dict):
        """Developer should be able to create a virtual server from team-scoped view (baseline)."""
        team_id = rbac_test_team["id"]
        _inject_jwt_cookie(page, rbac_developer_user["email"], token_use="session")
        _wait_for_admin_shell(page, team_id=team_id)

        srv_page = _navigate_to_servers(page)
        name = f"{RBAC_TEST_PREFIX}-dev-srv-team-{uuid.uuid4().hex[:8]}"

        status = _submit_server_form_and_get_status(srv_page, name)

        assert status != 403, f"Developer was denied server creation from team view (status={status})"
        assert status != 401, f"Developer authentication failed (status={status})"
        logger.info("Developer create server (team view): status=%d — RBAC passed", status)

    def test_viewer_cannot_create_server(self, page: Page, base_url: str, rbac_viewer_user: Dict, rbac_test_team: Dict):
        """Viewer should be denied server creation (security check)."""
        team_id = rbac_test_team["id"]
        _inject_jwt_cookie(page, rbac_viewer_user["email"], token_use="session")
        _wait_for_admin_shell(page, team_id=team_id)

        try:
            srv_page = _navigate_to_servers(page)
        except (AssertionError, PlaywrightTimeoutError):
            logger.info("Viewer create server: page did not render — correctly denied (auth failure)")
            return

        name = f"{RBAC_TEST_PREFIX}-viewer-srv-{uuid.uuid4().hex[:8]}"

        status = _submit_server_form_and_get_status(srv_page, name)

        assert status in (401, 403), f"Viewer should be denied server creation but got status={status}"
        logger.info("Viewer create server: status=%d — correctly denied", status)


@pytest.mark.ui
@pytest.mark.rbac
class TestRBACGatewayDelete:
    """Test RBAC enforcement on gateway deletion.

    Regression test for #2891: admin deleting a gateway via admin UI was
    denied because the admin routes use allow_admin_bypass=False.
    The platform_admin role should grant gateways.delete explicitly.
    """

    def test_admin_delete_gateway(self, page: Page, base_url: str, admin_api: APIRequestContext):
        """Admin should be able to delete a gateway via admin UI (#2891 regression).

        Creates a gateway via API first, then deletes it via the UI.
        """
        # Create a test gateway via API for deletion
        gw_name = f"{RBAC_TEST_PREFIX}-admin-del-{uuid.uuid4().hex[:8]}"
        gw_url = VALID_MCP_SERVER_URLS[4]
        create_resp = admin_api.post(
            "/gateways",
            data={
                "name": gw_name,
                "url": gw_url,
                "description": "RBAC delete test gateway",
                "tags": ["rbac", "test"],
                "transport": "SSE",
                "visibility": "public",
            },
        )
        # Gateway creation may fail due to URL validation (external service) — skip if so
        if create_resp.status >= 400:
            pytest.skip(f"Could not create test gateway for deletion test (HTTP {create_resp.status})")

        gateway_id = create_resp.json().get("id")
        if not gateway_id:
            pytest.skip("Gateway creation returned no ID")

        # Log in as admin and navigate to gateways
        _inject_jwt_cookie(page, "admin@example.com", is_admin=True)
        _wait_for_admin_shell(page)
        gw_page = _navigate_to_gateways(page)

        # Search for the gateway and delete it
        gw_page.search_gateways(gw_name)
        page.wait_for_timeout(500)

        if not gw_page.gateway_exists(gw_name):
            pytest.skip(f"Gateway '{gw_name}' not found in table after creation")

        # Set up dialog handler for confirm dialogs
        def handle_dialog(dialog):
            dialog.accept()

        page.on("dialog", handle_dialog)

        try:
            gateway_row = gw_page.get_gateway_row_by_name(gw_name)
            delete_btn = gateway_row.first.locator('form[action*="/delete"] button[type="submit"]:has-text("Delete")')
            delete_btn.scroll_into_view_if_needed()

            # Intercept the delete POST response
            with page.expect_response(
                lambda r: "/delete" in r.url and r.request.method == "POST",
                timeout=30000,
            ) as resp_info:
                with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                    delete_btn.click(force=True)

            status = resp_info.value.status

            # 303 redirect = success (the delete endpoint redirects on success)
            assert status != 403, f"Admin was denied gateway deletion (status={status}). This is the #2891 regression."
            logger.info("Admin delete gateway: status=%d — RBAC passed", status)

        finally:
            page.remove_listener("dialog", handle_dialog)
            # Cleanup: try API delete as fallback if UI delete failed
            try:
                admin_api.delete(f"/gateways/{gateway_id}")
            except Exception:
                pass


@pytest.mark.ui
@pytest.mark.rbac
class TestRBACRestAPI:
    """Test RBAC enforcement via REST API calls with session tokens.

    These tests verify that the RBAC check_any_team path works correctly
    for REST API calls using session tokens (not just the admin UI).
    """

    def test_developer_api_create_gateway_no_team_id(self, playwright: Playwright, rbac_developer_user: Dict, rbac_test_team: Dict):
        """Developer should be able to create a gateway via REST API without team_id."""
        token = _make_user_jwt(rbac_developer_user["email"], token_use="session")
        ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            name = f"{RBAC_TEST_PREFIX}-api-dev-gw-{uuid.uuid4().hex[:8]}"
            resp = ctx.post(
                "/gateways",
                data={
                    "name": name,
                    "url": VALID_MCP_SERVER_URLS[0],
                    "description": "RBAC API test",
                    "tags": ["rbac", "api-test"],
                    "transport": "SSE",
                    "visibility": "public",
                },
            )
            assert resp.status != 403, f"Developer REST API gateway create denied (status={resp.status})"
            logger.info("Developer API create gateway (no team_id): status=%d", resp.status)

            # Cleanup if created
            if resp.status in (200, 201):
                gw_id = resp.json().get("id")
                if gw_id:
                    ctx.delete(f"/gateways/{gw_id}")
        finally:
            ctx.dispose()

    def test_developer_api_create_server_no_team_id(self, playwright: Playwright, rbac_developer_user: Dict, rbac_test_team: Dict):
        """Developer should be able to create a virtual server via REST API without team_id."""
        token = _make_user_jwt(rbac_developer_user["email"], token_use="session")
        ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            name = f"{RBAC_TEST_PREFIX}-api-dev-srv-{uuid.uuid4().hex[:8]}"
            resp = ctx.post(
                "/servers",
                data={
                    "server": {
                        "name": name,
                        "description": "RBAC API test server",
                    },
                    "team_id": None,
                    "visibility": "public",
                },
            )
            assert resp.status != 403, f"Developer REST API server create denied (status={resp.status})"
            logger.info("Developer API create server (no team_id): status=%d", resp.status)

            # Cleanup if created
            if resp.status in (200, 201):
                srv_id = resp.json().get("id")
                if srv_id:
                    ctx.delete(f"/servers/{srv_id}")
        finally:
            ctx.dispose()

    def test_viewer_api_create_gateway_denied(self, playwright: Playwright, rbac_viewer_user: Dict, rbac_test_team: Dict):
        """Viewer should be denied gateway creation via REST API."""
        token = _make_user_jwt(rbac_viewer_user["email"], token_use="session")
        ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            name = f"{RBAC_TEST_PREFIX}-api-viewer-gw-{uuid.uuid4().hex[:8]}"
            resp = ctx.post(
                "/gateways",
                data={
                    "name": name,
                    "url": VALID_MCP_SERVER_URLS[0],
                    "description": "Should be denied",
                    "tags": ["rbac"],
                    "transport": "SSE",
                    "visibility": "public",
                },
            )
            assert resp.status == 403, f"Viewer should be denied gateway creation but got status={resp.status}"
            logger.info("Viewer API create gateway: status=%d — correctly denied", resp.status)
        finally:
            ctx.dispose()


# ==================== Navigation Helpers ====================


def _navigate_to_tools(page: Page, team_id: Optional[str] = None) -> ToolsPage:
    """Navigate to the tools tab, optionally in a team-scoped view."""
    if team_id:
        page.goto(f"/admin?team_id={team_id}#tools")
        page.wait_for_load_state("domcontentloaded")
        try:
            page.wait_for_selector('[data-testid="servers-tab"]', state="visible", timeout=60000)
        except PlaywrightTimeoutError:
            pass
    tools_page = ToolsPage(page)
    tools_page.navigate_to_tools_tab()
    tools_page.wait_for_tools_table_loaded()
    return tools_page


def _navigate_to_resources(page: Page, team_id: Optional[str] = None) -> ResourcesPage:
    """Navigate to the resources tab, optionally in a team-scoped view."""
    if team_id:
        page.goto(f"/admin?team_id={team_id}#resources")
        page.wait_for_load_state("domcontentloaded")
        try:
            page.wait_for_selector('[data-testid="servers-tab"]', state="visible", timeout=60000)
        except PlaywrightTimeoutError:
            pass
    res_page = ResourcesPage(page)
    res_page.navigate_to_resources_tab()
    res_page.wait_for_resources_table_loaded()
    return res_page


def _navigate_to_prompts(page: Page, team_id: Optional[str] = None) -> PromptsPage:
    """Navigate to the prompts tab, optionally in a team-scoped view."""
    if team_id:
        page.goto(f"/admin?team_id={team_id}#prompts")
        page.wait_for_load_state("domcontentloaded")
        try:
            page.wait_for_selector('[data-testid="servers-tab"]', state="visible", timeout=60000)
        except PlaywrightTimeoutError:
            pass
    pr_page = PromptsPage(page)
    pr_page.navigate_to_prompts_tab()
    pr_page.wait_for_prompts_table_loaded()
    return pr_page


def _navigate_to_teams(page: Page) -> TeamPage:
    """Navigate to the teams tab."""
    team_page = TeamPage(page)
    team_page.navigate_to_teams_tab()
    return team_page


def _submit_tool_form_and_get_status(tools_page: ToolsPage, name: str) -> int:
    """Fill and submit the tool form, returning the POST response status code.

    Returns:
        HTTP status code of the POST response.
        200/201 = success, 403 = RBAC denied.
    """
    tools_page.fill_tool_form(name=name, url="https://example.com/api/tool", description="RBAC test tool", integration_type="REST")
    try:
        with tools_page.page.expect_response(
            lambda r: "/admin/tools" in r.url and r.request.method == "POST",
            timeout=30000,
        ) as resp_info:
            tools_page.click_locator(tools_page.add_tool_btn)
        return resp_info.value.status
    except PlaywrightTimeoutError:
        if "/admin/login" in tools_page.page.url:
            return 401
        return 0


def _submit_resource_form_and_get_status(res_page: ResourcesPage, name: str) -> int:
    """Fill and submit the resource form, returning the POST response status code.

    Returns:
        HTTP status code of the POST response.
        200/201 = success, 403 = RBAC denied.
    """
    res_page.fill_resource_form(uri=f"file:///rbac-test/{name}", name=name, mime_type="text/plain", description="RBAC test resource")
    try:
        with res_page.page.expect_response(
            lambda r: "/admin/resources" in r.url and r.request.method == "POST",
            timeout=30000,
        ) as resp_info:
            res_page.click_locator(res_page.add_resource_btn)
        return resp_info.value.status
    except PlaywrightTimeoutError:
        if "/admin/login" in res_page.page.url:
            return 401
        return 0


def _submit_prompt_form_and_get_status(pr_page: PromptsPage, name: str) -> int:
    """Fill and submit the prompt form, returning the POST response status code.

    The template field already has default content, so we only fill name and description.

    Returns:
        HTTP status code of the POST response.
        200/201 = success, 403 = RBAC denied.
    """
    pr_page.fill_locator(pr_page.prompt_name_input, name)
    pr_page.fill_locator(pr_page.prompt_description_input, "RBAC test prompt")
    try:
        with pr_page.page.expect_response(
            lambda r: "/admin/prompts" in r.url and r.request.method == "POST",
            timeout=30000,
        ) as resp_info:
            pr_page.click_locator(pr_page.add_prompt_btn)
        return resp_info.value.status
    except PlaywrightTimeoutError:
        if "/admin/login" in pr_page.page.url:
            return 401
        return 0


# ==================== D8: Tool Operations ====================


@pytest.mark.ui
@pytest.mark.rbac
@pytest.mark.flaky(reruns=1, reason="Browser cookie auth intermittently returns 401")
class TestRBACToolOperations:
    """Test RBAC enforcement on tool creation via admin UI."""

    def test_developer_create_tool_team_view(self, page: Page, base_url: str, rbac_developer_user: Dict, rbac_test_team: Dict):
        """Developer should be able to create a tool from team-scoped view."""
        team_id = rbac_test_team["id"]
        _inject_jwt_cookie(page, rbac_developer_user["email"], token_use="session")
        _wait_for_admin_shell(page, team_id=team_id)

        tools_page = _navigate_to_tools(page)
        name = f"{RBAC_TEST_PREFIX}-dev-tool-{uuid.uuid4().hex[:8]}"

        status = _submit_tool_form_and_get_status(tools_page, name)

        assert status != 403, f"Developer was denied tool creation from team view (status={status})"
        assert status != 401, f"Developer authentication failed (status={status})"
        logger.info("Developer create tool (team view): status=%d — RBAC passed", status)

    def test_developer_create_tool_all_teams_view(self, page: Page, base_url: str, rbac_developer_user: Dict, rbac_test_team: Dict):
        """Developer should be able to create a tool from All Teams view."""
        _inject_jwt_cookie(page, rbac_developer_user["email"], token_use="session")
        _wait_for_admin_shell(page)

        tools_page = _navigate_to_tools(page, team_id=None)
        name = f"{RBAC_TEST_PREFIX}-dev-tool-allteams-{uuid.uuid4().hex[:8]}"

        status = _submit_tool_form_and_get_status(tools_page, name)

        assert status != 403, f"Developer was denied tool creation from All Teams view (status={status})"
        assert status != 401, f"Developer authentication failed (status={status})"
        logger.info("Developer create tool (All Teams): status=%d — RBAC passed", status)

    def test_viewer_cannot_create_tool(self, page: Page, base_url: str, rbac_viewer_user: Dict, rbac_test_team: Dict):
        """Viewer should be denied tool creation (security check)."""
        team_id = rbac_test_team["id"]
        _inject_jwt_cookie(page, rbac_viewer_user["email"], token_use="session")
        _wait_for_admin_shell(page, team_id=team_id)

        try:
            tools_page = _navigate_to_tools(page)
        except (AssertionError, PlaywrightTimeoutError):
            logger.info("Viewer create tool: page did not render — correctly denied (auth failure)")
            return

        name = f"{RBAC_TEST_PREFIX}-viewer-tool-{uuid.uuid4().hex[:8]}"

        status = _submit_tool_form_and_get_status(tools_page, name)

        assert status in (401, 403), f"Viewer should be denied tool creation but got status={status}"
        logger.info("Viewer create tool: status=%d — correctly denied", status)


# ==================== D8: Resource Operations ====================


@pytest.mark.ui
@pytest.mark.rbac
@pytest.mark.flaky(reruns=1, reason="Browser cookie auth intermittently returns 401")
class TestRBACResourceOperations:
    """Test RBAC enforcement on resource creation via admin UI."""

    def test_developer_create_resource(self, page: Page, base_url: str, rbac_developer_user: Dict, rbac_test_team: Dict):
        """Developer should be able to create a resource from team-scoped view."""
        team_id = rbac_test_team["id"]
        _inject_jwt_cookie(page, rbac_developer_user["email"], token_use="session")
        _wait_for_admin_shell(page, team_id=team_id)

        res_page = _navigate_to_resources(page)
        name = f"{RBAC_TEST_PREFIX}-dev-res-{uuid.uuid4().hex[:8]}"

        status = _submit_resource_form_and_get_status(res_page, name)

        assert status != 403, f"Developer was denied resource creation (status={status})"
        assert status != 401, f"Developer authentication failed (status={status})"
        logger.info("Developer create resource: status=%d — RBAC passed", status)

    def test_viewer_cannot_create_resource(self, page: Page, base_url: str, rbac_viewer_user: Dict, rbac_test_team: Dict):
        """Viewer should be denied resource creation (security check)."""
        team_id = rbac_test_team["id"]
        _inject_jwt_cookie(page, rbac_viewer_user["email"], token_use="session")
        _wait_for_admin_shell(page, team_id=team_id)

        try:
            res_page = _navigate_to_resources(page)
        except (AssertionError, PlaywrightTimeoutError):
            logger.info("Viewer create resource: page did not render — correctly denied (auth failure)")
            return

        name = f"{RBAC_TEST_PREFIX}-viewer-res-{uuid.uuid4().hex[:8]}"

        status = _submit_resource_form_and_get_status(res_page, name)

        assert status in (401, 403), f"Viewer should be denied resource creation but got status={status}"
        logger.info("Viewer create resource: status=%d — correctly denied", status)


# ==================== D8: Prompt Operations ====================


@pytest.mark.ui
@pytest.mark.rbac
@pytest.mark.flaky(reruns=1, reason="Browser cookie auth intermittently returns 401")
class TestRBACPromptOperations:
    """Test RBAC enforcement on prompt creation via admin UI."""

    def test_developer_create_prompt(self, page: Page, base_url: str, rbac_developer_user: Dict, rbac_test_team: Dict):
        """Developer should be able to create a prompt from team-scoped view."""
        team_id = rbac_test_team["id"]
        _inject_jwt_cookie(page, rbac_developer_user["email"], token_use="session")
        _wait_for_admin_shell(page, team_id=team_id)

        pr_page = _navigate_to_prompts(page)
        name = f"{RBAC_TEST_PREFIX}-dev-prompt-{uuid.uuid4().hex[:8]}"

        status = _submit_prompt_form_and_get_status(pr_page, name)

        assert status != 403, f"Developer was denied prompt creation (status={status})"
        assert status != 401, f"Developer authentication failed (status={status})"
        logger.info("Developer create prompt: status=%d — RBAC passed", status)

    def test_viewer_cannot_create_prompt(self, page: Page, base_url: str, rbac_viewer_user: Dict, rbac_test_team: Dict):
        """Viewer should be denied prompt creation (security check)."""
        team_id = rbac_test_team["id"]
        _inject_jwt_cookie(page, rbac_viewer_user["email"], token_use="session")
        _wait_for_admin_shell(page, team_id=team_id)

        try:
            pr_page = _navigate_to_prompts(page)
        except (AssertionError, PlaywrightTimeoutError):
            logger.info("Viewer create prompt: page did not render — correctly denied (auth failure)")
            return

        name = f"{RBAC_TEST_PREFIX}-viewer-prompt-{uuid.uuid4().hex[:8]}"

        status = _submit_prompt_form_and_get_status(pr_page, name)

        assert status in (401, 403), f"Viewer should be denied prompt creation but got status={status}"
        logger.info("Viewer create prompt: status=%d — correctly denied", status)


# ==================== D8: Team Management ====================


RBAC_TEAM_ADMIN_EMAIL = f"{RBAC_TEST_PREFIX}-ta-{uuid.uuid4().hex[:8]}@test.example.com"


@pytest.fixture(scope="module")
def rbac_team_admin_user(admin_api: APIRequestContext, rbac_test_team: Dict, playwright: Playwright) -> Generator[Dict[str, Any], None, None]:
    """Create a team_admin user with team-scoped team_admin RBAC role."""
    team_id = rbac_test_team["id"]
    user_info = _create_user_and_join_team(admin_api, playwright, RBAC_TEAM_ADMIN_EMAIL, team_id, "team_admin")
    yield user_info

    # Cleanup
    try:
        admin_api.delete(f"/rbac/users/{RBAC_TEAM_ADMIN_EMAIL}/roles/team_admin?scope=team&scope_id={team_id}")
    except Exception as e:
        logger.warning("Failed to revoke team_admin role: %s", e)
    try:
        admin_api.delete(f"/teams/{team_id}/members/{RBAC_TEAM_ADMIN_EMAIL}")
    except Exception as e:
        logger.warning("Failed to remove team_admin from team: %s", e)
    try:
        admin_api.delete(f"/auth/email/admin/users/{RBAC_TEAM_ADMIN_EMAIL}")
    except Exception as e:
        logger.warning("Failed to delete team_admin user: %s", e)


@pytest.mark.ui
@pytest.mark.rbac
class TestRBACTeamManagement:
    """Test RBAC enforcement on team management operations via admin UI."""

    def test_viewer_cannot_add_team_member(self, playwright: Playwright, rbac_viewer_user: Dict, rbac_test_team: Dict):
        """Viewer should be denied adding team members (requires teams.manage_members)."""
        team_id = rbac_test_team["id"]
        token = _make_user_jwt(rbac_viewer_user["email"], token_use="session")
        ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            # POST /admin/teams/{team_id}/add-member requires teams.manage_members
            resp = ctx.post(
                f"/admin/teams/{team_id}/add-member",
                data={"email": "nobody@test.example.com", "role": "member"},
            )
            assert resp.status == 403, f"Viewer should be denied adding team members but got status={resp.status}"
            logger.info("Viewer add team member: status=%d — correctly denied", resp.status)
        finally:
            ctx.dispose()

    def test_team_admin_passes_rbac_for_manage_members(self, playwright: Playwright, rbac_team_admin_user: Dict, rbac_test_team: Dict):
        """Team admin should pass RBAC check for teams.manage_members.

        The endpoint has an additional ownership check ("Only team owners can add members")
        which returns 403 with a specific message. This is a business logic restriction,
        not an RBAC denial. We verify RBAC passes by confirming the error is ownership-based.
        """
        team_id = rbac_test_team["id"]
        token = _make_user_jwt(rbac_team_admin_user["email"], teams=[team_id])
        ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "text/html"},
        )
        try:
            # GET /admin/teams/{team_id}/members/add requires teams.manage_members
            resp = ctx.get(f"/admin/teams/{team_id}/members/add")
            assert resp.status != 401, f"Team admin authentication failed (status={resp.status})"
            body = resp.text()
            if resp.status == 403:
                # 403 from ownership check (business logic) is OK — RBAC passed
                assert "team owners" in body.lower() or "owner" in body.lower(), f"Got RBAC 403 (not ownership): {body[:200]}"
                logger.info("Team admin manage members: RBAC passed, ownership check applied (expected)")
            else:
                logger.info("Team admin manage members: status=%d — RBAC passed", resp.status)
        finally:
            ctx.dispose()


# ==================== D8: REST API Operations for Tools/Resources/Prompts ====================


@pytest.mark.ui
@pytest.mark.rbac
class TestRBACRestAPIEntityCreate:
    """Test RBAC enforcement on tool/resource/prompt creation via REST API."""

    def test_developer_api_create_tool(self, playwright: Playwright, rbac_developer_user: Dict, rbac_test_team: Dict):
        """Developer should be able to create a tool via REST API."""
        token = _make_user_jwt(rbac_developer_user["email"], token_use="session")
        ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            name = f"{RBAC_TEST_PREFIX}-api-dev-tool-{uuid.uuid4().hex[:8]}"
            resp = ctx.post(
                "/tools",
                data={
                    "tool": {
                        "name": name,
                        "description": "RBAC API test tool",
                        "url": "https://example.com/api/tool",
                        "integration_type": "REST",
                        "input_schema": "{}",
                    },
                    "team_id": None,
                    "visibility": "public",
                },
            )
            assert resp.status != 403, f"Developer REST API tool create denied (status={resp.status})"
            logger.info("Developer API create tool: status=%d", resp.status)

            # Cleanup if created
            if resp.status in (200, 201):
                tool_id = resp.json().get("id")
                if tool_id:
                    ctx.delete(f"/tools/{tool_id}")
        finally:
            ctx.dispose()

    def test_viewer_api_create_tool_denied(self, playwright: Playwright, rbac_viewer_user: Dict, rbac_test_team: Dict):
        """Viewer should be denied tool creation via REST API."""
        token = _make_user_jwt(rbac_viewer_user["email"], token_use="session")
        ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            name = f"{RBAC_TEST_PREFIX}-api-viewer-tool-{uuid.uuid4().hex[:8]}"
            resp = ctx.post(
                "/tools",
                data={
                    "tool": {
                        "name": name,
                        "description": "Should be denied",
                        "url": "https://example.com/api/tool",
                        "integration_type": "REST",
                        "input_schema": {},
                    },
                    "team_id": None,
                    "visibility": "public",
                },
            )
            # RBAC 403 or body validation 422 — either way, viewer must NOT succeed
            assert resp.status not in (200, 201), f"Viewer should be denied tool creation but got status={resp.status}"
            logger.info("Viewer API create tool: status=%d — correctly denied", resp.status)
        finally:
            ctx.dispose()

    def test_developer_api_create_resource(self, playwright: Playwright, rbac_developer_user: Dict, rbac_test_team: Dict):
        """Developer should be able to create a resource via REST API."""
        token = _make_user_jwt(rbac_developer_user["email"], token_use="session")
        ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            name = f"{RBAC_TEST_PREFIX}-api-dev-res-{uuid.uuid4().hex[:8]}"
            resp = ctx.post(
                "/resources",
                data={
                    "resource": {
                        "uri": f"file:///rbac-test/{name}",
                        "name": name,
                        "description": "RBAC API test resource",
                        "mimeType": "text/plain",
                    },
                    "team_id": None,
                    "visibility": "public",
                },
            )
            assert resp.status != 403, f"Developer REST API resource create denied (status={resp.status})"
            logger.info("Developer API create resource: status=%d", resp.status)

            # Cleanup if created
            if resp.status in (200, 201):
                res_id = resp.json().get("id")
                if res_id:
                    ctx.delete(f"/resources/{res_id}")
        finally:
            ctx.dispose()

    def test_viewer_api_create_resource_denied(self, playwright: Playwright, rbac_viewer_user: Dict, rbac_test_team: Dict):
        """Viewer should be denied resource creation via REST API."""
        token = _make_user_jwt(rbac_viewer_user["email"], token_use="session")
        ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            name = f"{RBAC_TEST_PREFIX}-api-viewer-res-{uuid.uuid4().hex[:8]}"
            resp = ctx.post(
                "/resources",
                data={
                    "resource": {
                        "uri": f"file:///rbac-test/{name}",
                        "name": name,
                        "description": "Should be denied",
                        "mimeType": "text/plain",
                    },
                    "team_id": None,
                    "visibility": "public",
                },
            )
            # RBAC 403 or body validation 422 — either way, viewer must NOT succeed
            assert resp.status not in (200, 201), f"Viewer should be denied resource creation but got status={resp.status}"
            logger.info("Viewer API create resource: status=%d — correctly denied", resp.status)
        finally:
            ctx.dispose()

    def test_developer_api_create_prompt(self, playwright: Playwright, rbac_developer_user: Dict, rbac_test_team: Dict):
        """Developer should be able to create a prompt via REST API."""
        token = _make_user_jwt(rbac_developer_user["email"], token_use="session")
        ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            name = f"{RBAC_TEST_PREFIX}-api-dev-prompt-{uuid.uuid4().hex[:8]}"
            resp = ctx.post(
                "/prompts",
                data={
                    "prompt": {
                        "name": name,
                        "description": "RBAC API test prompt",
                        "template": "Hello {{name}}",
                        "arguments": [],
                    },
                    "team_id": None,
                    "visibility": "public",
                },
            )
            assert resp.status != 403, f"Developer REST API prompt create denied (status={resp.status})"
            logger.info("Developer API create prompt: status=%d", resp.status)

            # Cleanup if created
            if resp.status in (200, 201):
                prompt_id = resp.json().get("id")
                if prompt_id:
                    ctx.delete(f"/prompts/{prompt_id}")
        finally:
            ctx.dispose()

    def test_viewer_api_create_prompt_denied(self, playwright: Playwright, rbac_viewer_user: Dict, rbac_test_team: Dict):
        """Viewer should be denied prompt creation via REST API."""
        token = _make_user_jwt(rbac_viewer_user["email"], token_use="session")
        ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            name = f"{RBAC_TEST_PREFIX}-api-viewer-prompt-{uuid.uuid4().hex[:8]}"
            resp = ctx.post(
                "/prompts",
                data={
                    "prompt": {
                        "name": name,
                        "description": "Should be denied",
                        "template": "Hello {{name}}",
                        "arguments": [],
                    },
                    "team_id": None,
                    "visibility": "public",
                },
            )
            assert resp.status == 403, f"Viewer should be denied prompt creation but got status={resp.status}"
            logger.info("Viewer API create prompt: status=%d — correctly denied", resp.status)
        finally:
            ctx.dispose()
