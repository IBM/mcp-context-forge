# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Top-30 browser-driven security scenarios for Playwright."""

# Future
from __future__ import annotations

# Standard
from contextlib import suppress
from datetime import datetime, timedelta, timezone
import os
import re
import time
from typing import Any
from urllib.parse import urlparse
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext, BrowserContext, Page, expect
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.create_jwt_token import _create_jwt_token

# Local
from ..pages.login_page import LoginPage
from .conftest import BASE_URL

pytestmark = [pytest.mark.ui, pytest.mark.e2e, pytest.mark.playwright_security_e2e]

_UNSET = object()
TEST_PASSWORD = "SecureTestPass123!"


def _extract_servers(response_json: Any) -> list[dict[str, Any]]:
    if isinstance(response_json, list):
        return response_json
    if isinstance(response_json, dict):
        servers = response_json.get("servers")
        if isinstance(servers, list):
            return servers
    return []


def _extract_token_id(response_json: dict[str, Any]) -> str | None:
    token_obj = response_json.get("token", response_json)
    return token_obj.get("id") or token_obj.get("token_id")


def _make_jwt(
    email: str,
    *,
    is_admin: bool,
    teams: object = _UNSET,
    exp: int | None = None,
    scopes: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {"sub": email}
    if teams is not _UNSET:
        payload["teams"] = teams
    if exp is not None:
        payload["exp"] = exp
    return _create_jwt_token(
        payload,
        user_data={"email": email, "is_admin": is_admin, "auth_provider": "local"},
        scopes=scopes,
    )


def _api_context(playwright, token: str, extra_headers: dict[str, str] | None = None) -> APIRequestContext:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    return playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers=headers,
    )


def _set_jwt_cookie(context: BrowserContext, token: str) -> None:
    context.add_cookies(
        [
            {
                "name": "jwt_token",
                "value": token,
                "url": f"{BASE_URL.rstrip('/')}/",
                "httpOnly": True,
                "sameSite": "Lax",
            }
        ]
    )


def _expected_samesite() -> str:
    value = (settings.cookie_samesite or "lax").strip().lower()
    return {"lax": "Lax", "strict": "Strict", "none": "None"}.get(value, "Lax")


def _server_ids_for_token(playwright, token: str, path: str = "/servers") -> set[str]:
    ctx = _api_context(playwright, token)
    try:
        response = ctx.get(path)
        assert response.status == 200, f"Expected 200 from {path}, got {response.status}: {response.text()}"
        return {item["id"] for item in _extract_servers(response.json())}
    finally:
        ctx.dispose()


def _ws_url(token: str | None = None) -> str:
    parsed = urlparse(BASE_URL)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    base = f"{scheme}://{parsed.netloc}/ws"
    return f"{base}?token={token}" if token else base


def _probe_websocket(page: Page, ws_url: str, timeout_ms: int = 6000) -> dict[str, Any]:
    return page.evaluate(
        """
        async ({ wsUrl, timeoutMs }) => {
          return await new Promise((resolve) => {
            let settled = false;
            let timer = null;
            const finish = (value) => {
              if (!settled) {
                settled = true;
                if (timer) clearTimeout(timer);
                resolve(value);
              }
            };

            timer = setTimeout(() => finish({ event: "timeout" }), timeoutMs);

            try {
              const ws = new WebSocket(wsUrl);

              ws.onopen = () => {
                try { ws.send("not-json"); } catch (_err) {}
              };

              ws.onmessage = (event) => {
                finish({ event: "message", data: String(event.data || "") });
                try { ws.close(); } catch (_err) {}
              };

              ws.onclose = (event) => {
                finish({ event: "close", code: event.code, reason: event.reason || "" });
              };

              ws.onerror = () => {
                finish({ event: "error" });
              };
            } catch (err) {
              finish({ event: "exception", message: String(err) });
            }
          });
        }
        """,
        {"wsUrl": ws_url, "timeoutMs": timeout_ms},
    )


@pytest.fixture
def email_logged_in_page(context: BrowserContext) -> Page:
    """Create a browser page logged in via email/password (no JWT fallback header)."""
    page = context.new_page()
    login_page = LoginPage(page, BASE_URL)
    response = login_page.navigate()
    if response and response.status == 404:
        pytest.skip("Admin login endpoint is unavailable in this environment.")
    if not login_page.is_login_form_available(timeout=3000):
        pytest.skip("Email login form is unavailable in this environment.")

    admin_email = os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com")
    candidate_passwords = [os.getenv("PLATFORM_ADMIN_NEW_PASSWORD", "Changeme123!"), os.getenv("PLATFORM_ADMIN_PASSWORD", "changeme")]

    login_succeeded = False
    for password in candidate_passwords:
        login_page.submit_login(admin_email, password)

        if login_page.is_on_change_password_page():
            desired_password = os.getenv("PLATFORM_ADMIN_NEW_PASSWORD", "Changeme123!")
            login_page.submit_password_change(password, desired_password)

        if "/admin/login" not in page.url and "/admin/change-password-required" not in page.url:
            login_succeeded = True
            break

    if not login_succeeded:
        pytest.skip("Unable to complete email/password login with configured credentials.")

    expect(page).to_have_url(re.compile(r".*/admin(?!/login).*"))
    return page


@pytest.fixture
def scoped_server_matrix(playwright):
    team_id: str | None = None
    public_server_id: str | None = None
    team_server_id: str | None = None
    member_email: str | None = None
    admin_ctx = _api_context(playwright, _make_jwt("admin@example.com", is_admin=True, teams=None))

    team_name = f"pw-sec-team-{uuid.uuid4().hex[:8]}"
    public_name = f"pw-sec-public-{uuid.uuid4().hex[:8]}"
    team_name_server = f"pw-sec-team-server-{uuid.uuid4().hex[:8]}"

    team_resp = admin_ctx.post("/teams/", data={"name": team_name, "description": "Playwright security team", "visibility": "private"})
    if team_resp.status == 404:
        admin_ctx.dispose()
        pytest.skip("/teams endpoint is unavailable in this environment.")
    assert team_resp.status in (200, 201), f"Failed to create team: {team_resp.status} {team_resp.text()}"
    team_id = team_resp.json()["id"]

    public_resp = admin_ctx.post(
        "/servers",
        data={"server": {"name": public_name, "description": "public scope probe"}, "team_id": None, "visibility": "public"},
    )
    assert public_resp.status in (200, 201), f"Failed to create public server: {public_resp.status} {public_resp.text()}"
    public_server_id = public_resp.json()["id"]

    team_resp_server = admin_ctx.post(
        "/servers",
        data={"server": {"name": team_name_server, "description": "team scope probe"}, "team_id": team_id, "visibility": "team"},
    )
    assert team_resp_server.status in (200, 201), f"Failed to create team server: {team_resp_server.status} {team_resp_server.text()}"
    team_server_id = team_resp_server.json()["id"]

    member_email = f"pw-sec-member-{uuid.uuid4().hex[:8]}@example.com"
    user_resp = admin_ctx.post(
        "/auth/email/admin/users",
        data={"email": member_email, "password": TEST_PASSWORD, "full_name": "Playwright Scope Member"},
    )
    assert user_resp.status in (200, 201, 409), f"Failed to create member user: {user_resp.status} {user_resp.text()}"

    invite_resp = admin_ctx.post(
        f"/teams/{team_id}/invitations",
        data={"email": member_email, "role": "member"},
    )
    assert invite_resp.status in (200, 201), f"Failed to invite member user: {invite_resp.status} {invite_resp.text()}"
    invitation_token = invite_resp.json()["token"]

    member_ctx = _api_context(playwright, _make_jwt(member_email, is_admin=False))
    try:
        accept_resp = member_ctx.post(f"/teams/invitations/{invitation_token}/accept")
    finally:
        member_ctx.dispose()
    assert accept_resp.status == 200, f"Failed to accept invitation: {accept_resp.status} {accept_resp.text()}"

    # Team membership checks can lag briefly in cache-backed environments.
    member_visible = False
    for _ in range(20):
        members_resp = admin_ctx.get(f"/teams/{team_id}/members")
        if members_resp.status == 200:
            payload = members_resp.json()
            members = payload if isinstance(payload, list) else payload.get("members", [])
            if any(member.get("user_email") == member_email for member in members):
                member_visible = True
                break
        time.sleep(0.2)
    assert member_visible, "Invited user did not appear as a team member in time."

    try:
        yield {
            "team_id": team_id,
            "public_server_id": public_server_id,
            "team_server_id": team_server_id,
            "public_server_name": public_name,
            "team_server_name": team_name_server,
            "member_email": member_email,
        }
    finally:
        if member_email and team_id:
            with suppress(Exception):
                admin_ctx.delete(f"/teams/{team_id}/members/{member_email}")
        if member_email:
            with suppress(Exception):
                admin_ctx.delete(f"/auth/email/admin/users/{member_email}")
        if team_server_id:
            with suppress(Exception):
                admin_ctx.delete(f"/servers/{team_server_id}")
        if public_server_id:
            with suppress(Exception):
                admin_ctx.delete(f"/servers/{public_server_id}")
        if team_id:
            with suppress(Exception):
                admin_ctx.delete(f"/teams/{team_id}")
        admin_ctx.dispose()


@pytest.fixture
def public_server_id(admin_api: APIRequestContext) -> str:
    response = admin_api.post(
        "/servers",
        data={
            "server": {"name": f"pw-sec-transport-{uuid.uuid4().hex[:8]}", "description": "transport auth checks"},
            "team_id": None,
            "visibility": "public",
        },
    )
    if response.status == 404:
        pytest.skip("/servers endpoint unavailable in this environment.")
    assert response.status in (200, 201), f"Failed to create server for transport checks: {response.status} {response.text()}"
    server_id = response.json()["id"]
    yield server_id
    with suppress(Exception):
        admin_api.delete(f"/servers/{server_id}")


@pytest.fixture
def read_only_scoped_token(admin_api: APIRequestContext):
    create_resp = admin_api.post(
        "/tokens",
        data={
            "name": f"pw-read-only-{uuid.uuid4().hex[:8]}",
            "expires_in_days": 1,
            "scope": {"permissions": ["servers.read"]},
        },
    )
    assert create_resp.status in (200, 201), f"Failed creating scoped token: {create_resp.status} {create_resp.text()}"
    payload = create_resp.json()
    token_id = _extract_token_id(payload)
    access_token = payload["access_token"]

    try:
        yield {"token_id": token_id, "access_token": access_token}
    finally:
        if token_id:
            with suppress(Exception):
                admin_api.delete(f"/tokens/{token_id}")


class TestPlaywrightSecurityE2EAuthAndSession:
    """Authentication and browser-session protections."""

    def test_01_admin_route_requires_authentication_when_enabled(self, context: BrowserContext):
        page = context.new_page()
        response = page.goto("/admin")
        if response and response.status == 404:
            pytest.skip("Admin UI endpoint is unavailable in this environment.")

        if settings.auth_required:
            expect(page).to_have_url(re.compile(r".*/admin/login.*"))
        else:
            expect(page).to_have_url(re.compile(r".*/admin(?!/login).*"))

    def test_02_admin_deep_link_requires_authentication_when_enabled(self, context: BrowserContext):
        page = context.new_page()
        response = page.goto("/admin/#tokens")
        if response and response.status == 404:
            pytest.skip("Admin UI endpoint is unavailable in this environment.")

        if settings.auth_required:
            expect(page).to_have_url(re.compile(r".*/admin/login.*"))
        else:
            expect(page).to_have_url(re.compile(r".*/admin(?!/login).*"))

    def test_03_invalid_credentials_show_generic_error_message(self, context: BrowserContext):
        page = context.new_page()
        login_page = LoginPage(page, BASE_URL)
        response = login_page.navigate()
        if response and response.status == 404:
            pytest.skip("Admin login endpoint is unavailable in this environment.")
        if not login_page.is_login_form_available(timeout=3000):
            pytest.skip("Email login form is not available in this environment.")

        login_page.submit_login("invalid@example.com", "definitely-wrong-password")

        expect(page).to_have_url(re.compile(r".*/admin/login\?error=invalid_credentials"))
        expect(login_page.error_message).to_be_visible()
        expect(login_page.error_message).to_contain_text("Invalid email or password")
        content = page.content()
        assert "Traceback" not in content
        assert "Exception" not in content

    def test_04_login_page_maps_admin_required_error(self, context: BrowserContext):
        page = context.new_page()
        response = page.goto("/admin/login?error=admin_required")
        if response and response.status == 404:
            pytest.skip("Admin login endpoint is unavailable in this environment.")

        error = page.locator("#error-message")
        expect(error).to_be_visible()
        expect(error).to_contain_text("Admin privileges required")
        assert "Traceback" not in page.content()

    def test_05_login_page_maps_session_expired_error(self, context: BrowserContext):
        page = context.new_page()
        response = page.goto("/admin/login?error=session_expired")
        if response and response.status == 404:
            pytest.skip("Admin login endpoint is unavailable in this environment.")

        error = page.locator("#error-message")
        expect(error).to_be_visible()
        expect(error).to_contain_text("Session Expired")
        assert "Traceback" not in page.content()

    def test_06_authenticated_admin_shell_loads_expected_tabs(self, admin_page):
        expect(admin_page.page).to_have_url(re.compile(r".*/admin(?!/login).*"))
        expect(admin_page.servers_tab).to_be_visible()
        expect(admin_page.tools_tab).to_be_visible()
        expect(admin_page.gateways_tab).to_be_visible()
        expect(admin_page.teams_tab).to_be_visible()

    def test_07_session_cookie_has_http_only_and_samesite(self, admin_page):
        if not settings.auth_required:
            pytest.skip("Auth is disabled, cookie hardening is not applicable.")

        jwt_cookie = next((cookie for cookie in admin_page.page.context.cookies() if cookie["name"] == "jwt_token"), None)
        assert jwt_cookie is not None, "Expected jwt_token cookie after authentication."
        assert jwt_cookie["httpOnly"] is True
        assert jwt_cookie["sameSite"] == _expected_samesite()

    def test_08_logout_post_clears_cookie_and_returns_to_login(self, email_logged_in_page: Page):
        if not settings.auth_required:
            pytest.skip("Auth is disabled, logout session invalidation is not applicable.")

        logout_button = email_logged_in_page.locator('form[action$="/admin/logout"] button[type="submit"]')
        expect(logout_button).to_be_visible()
        email_logged_in_page.once("dialog", lambda dialog: dialog.accept())
        logout_button.click()
        email_logged_in_page.wait_for_load_state("domcontentloaded")

        expect(email_logged_in_page).to_have_url(re.compile(r".*/admin/login.*"))

        jwt_cookie = next((cookie for cookie in email_logged_in_page.context.cookies() if cookie["name"] == "jwt_token"), None)
        assert jwt_cookie is None or not jwt_cookie.get("value"), "jwt_token cookie should be cleared after logout."

    def test_09_logout_get_front_channel_clears_cookie(self, email_logged_in_page: Page):
        if not settings.auth_required:
            pytest.skip("Auth is disabled, logout session invalidation is not applicable.")

        response = email_logged_in_page.goto("/admin/logout")
        if response:
            assert response.status in (200, 302, 303)

        email_logged_in_page.goto(f"/admin?logout_check={uuid.uuid4().hex[:8]}")
        expect(email_logged_in_page).to_have_url(re.compile(r".*/admin/login.*"))

        jwt_cookie = next((cookie for cookie in email_logged_in_page.context.cookies() if cookie["name"] == "jwt_token"), None)
        assert jwt_cookie is None or not jwt_cookie.get("value"), "jwt_token cookie should be cleared after logout."

    def test_10_logout_in_one_tab_invalidates_other_tab(self, email_logged_in_page: Page):
        if not settings.auth_required:
            pytest.skip("Auth is disabled, multi-tab session invalidation is not applicable.")

        page_one = email_logged_in_page
        page_two = page_one.context.new_page()
        page_two.goto("/admin")
        expect(page_two).to_have_url(re.compile(r".*/admin(?!/login).*"))

        logout_button = page_one.locator('form[action$="/admin/logout"] button[type="submit"]')
        expect(logout_button).to_be_visible()
        page_one.once("dialog", lambda dialog: dialog.accept())
        logout_button.click()
        page_one.wait_for_load_state("domcontentloaded")

        page_two.goto(f"/admin?logout_check={uuid.uuid4().hex[:8]}")
        expect(page_two).to_have_url(re.compile(r".*/admin/login.*"))
        page_two.close()

    def test_11_post_logout_admin_api_requests_are_denied(self, email_logged_in_page: Page):
        if not settings.auth_required:
            pytest.skip("Auth is disabled, post-logout denial checks are not applicable.")

        logout_button = email_logged_in_page.locator('form[action$="/admin/logout"] button[type="submit"]')
        expect(logout_button).to_be_visible()
        email_logged_in_page.once("dialog", lambda dialog: dialog.accept())
        logout_button.click()
        email_logged_in_page.wait_for_load_state("domcontentloaded")

        response = email_logged_in_page.request.get("/auth/email/admin/users")

        if response.status == 200:
            assert "/admin/login" in response.url or "Sign In" in response.text()
        else:
            assert response.status in (401, 403, 302, 303)

    def test_12_expired_session_cookie_redirects_to_login(self, context: BrowserContext):
        if not settings.auth_required:
            pytest.skip("Auth is disabled, expiration handling is not applicable.")

        expired_at = int((datetime.now(timezone.utc) - timedelta(minutes=10)).timestamp())
        expired_token = _make_jwt("admin@example.com", is_admin=True, teams=None, exp=expired_at)
        _set_jwt_cookie(context, expired_token)

        page = context.new_page()
        response = page.goto("/admin")
        if response and response.status == 404:
            pytest.skip("Admin UI endpoint is unavailable in this environment.")
        expect(page).to_have_url(re.compile(r".*/admin/login.*"))

    def test_13_non_admin_token_cannot_access_admin_ui(self, context: BrowserContext):
        if not settings.auth_required:
            pytest.skip("Auth is disabled, admin-role routing checks are not applicable.")

        non_admin_token = _make_jwt(f"nonadmin-{uuid.uuid4().hex[:8]}@example.com", is_admin=False, teams=[])
        context.set_extra_http_headers({"Authorization": f"Bearer {non_admin_token}"})
        _set_jwt_cookie(context, non_admin_token)

        page = context.new_page()
        response = page.goto("/admin")
        if response and response.status == 404:
            pytest.skip("Admin UI endpoint is unavailable in this environment.")

        if "/admin/login" in page.url:
            assert (
                "error=admin_required" in page.url
                or "error=invalid_credentials" in page.url
                or page.url.rstrip("/").endswith("/admin/login")
            )
            return

        # Some deployments keep URL at /admin and render denied content; ensure admin-only API is blocked.
        probe = page.request.get("/auth/email/admin/users")
        assert probe.status in (401, 403), f"Non-admin browser session should not access admin user API, got {probe.status}: {probe.text()}"

    def test_14_cookie_only_auth_is_rejected_for_api_calls(self, playwright):
        if not settings.auth_required:
            pytest.skip("Auth is disabled, cookie-only API auth rejection is not applicable.")

        admin_token = _make_jwt("admin@example.com", is_admin=True, teams=None)
        ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={
                "Accept": "application/json",
                "Cookie": f"jwt_token={admin_token}",
            },
        )
        try:
            response = ctx.get("/servers")
            assert response.status == 401, f"Cookie-only API authentication should be rejected, got {response.status}: {response.text()}"
        finally:
            ctx.dispose()


class TestPlaywrightSecurityE2EScopeAndRBAC:
    """Token scope and role enforcement in browser-driven flows."""

    def test_15_teams_missing_claim_is_public_only(self, playwright, scoped_server_matrix: dict[str, str]):
        token = _make_jwt("admin@example.com", is_admin=True)
        ids = _server_ids_for_token(playwright, token)
        assert scoped_server_matrix["public_server_id"] in ids
        assert scoped_server_matrix["team_server_id"] not in ids

    def test_16_teams_empty_claim_is_public_only(self, playwright, scoped_server_matrix: dict[str, str]):
        token = _make_jwt("admin@example.com", is_admin=True, teams=[])
        ids = _server_ids_for_token(playwright, token)
        assert scoped_server_matrix["public_server_id"] in ids
        assert scoped_server_matrix["team_server_id"] not in ids

    def test_17_teams_null_with_admin_true_is_unrestricted(self, playwright, scoped_server_matrix: dict[str, str]):
        token = _make_jwt("admin@example.com", is_admin=True, teams=None)
        ids = _server_ids_for_token(playwright, token)
        assert scoped_server_matrix["public_server_id"] in ids
        assert scoped_server_matrix["team_server_id"] in ids

    def test_18_teams_null_with_admin_false_is_public_only(self, playwright, scoped_server_matrix: dict[str, str]):
        token = _make_jwt(scoped_server_matrix["member_email"], is_admin=False, teams=None)
        ids = _server_ids_for_token(playwright, token)
        assert scoped_server_matrix["public_server_id"] in ids
        assert scoped_server_matrix["team_server_id"] not in ids

    def test_19_team_scoped_token_sees_public_and_team_servers(self, playwright, scoped_server_matrix: dict[str, str]):
        token = _make_jwt(scoped_server_matrix["member_email"], is_admin=False, teams=[scoped_server_matrix["team_id"]])
        ids = _server_ids_for_token(playwright, token)
        assert scoped_server_matrix["public_server_id"] in ids
        assert scoped_server_matrix["team_server_id"] in ids

    def test_20_duplicate_visibility_query_params_do_not_expand_scope(self, playwright, scoped_server_matrix: dict[str, str]):
        token = _make_jwt("admin@example.com", is_admin=True)
        ids = _server_ids_for_token(playwright, token, "/servers?visibility=public&visibility=team")
        assert scoped_server_matrix["team_server_id"] not in ids

    def test_21_non_admin_cannot_create_users(self, playwright):
        token = _make_jwt(f"rbac-user-{uuid.uuid4().hex[:8]}@example.com", is_admin=False, teams=[])
        ctx = _api_context(playwright, token)
        try:
            response = ctx.post(
                "/auth/email/admin/users",
                data={
                    "email": f"forbidden-{uuid.uuid4().hex[:8]}@example.com",
                    "password": "SecurePass123!",
                    "full_name": "Forbidden User",
                },
            )
            assert response.status in (401, 403), f"Non-admin user creation should be denied, got {response.status}: {response.text()}"
        finally:
            ctx.dispose()

    def test_22_non_admin_cannot_create_roles(self, playwright):
        token = _make_jwt(f"rbac-role-{uuid.uuid4().hex[:8]}@example.com", is_admin=False, teams=[])
        ctx = _api_context(playwright, token)
        try:
            response = ctx.post(
                "/rbac/roles",
                data={"name": f"forbidden-role-{uuid.uuid4().hex[:8]}", "description": "should fail", "scope": "global", "permissions": ["tools.read"]},
            )
            assert response.status in (401, 403), f"Non-admin role creation should be denied, got {response.status}: {response.text()}"
        finally:
            ctx.dispose()

    def test_23_non_admin_cannot_access_admin_token_list(self, playwright):
        token = _make_jwt(f"rbac-token-{uuid.uuid4().hex[:8]}@example.com", is_admin=False, teams=[])
        ctx = _api_context(playwright, token)
        try:
            response = ctx.get("/tokens/admin/all")
            assert response.status in (401, 403), f"Non-admin token-admin endpoint access should be denied, got {response.status}: {response.text()}"
        finally:
            ctx.dispose()

    def test_24_read_only_scoped_token_cannot_create_server(self, admin_api: APIRequestContext, playwright, read_only_scoped_token: dict[str, str]):
        ctx = _api_context(playwright, read_only_scoped_token["access_token"])
        created_server_id: str | None = None
        try:
            response = ctx.post(
                "/servers",
                data={
                    "server": {"name": f"forbidden-create-{uuid.uuid4().hex[:8]}", "description": "scope enforcement"},
                    "team_id": None,
                    "visibility": "public",
                },
            )
            if response.status in (200, 201):
                created_server_id = response.json().get("id")
            assert response.status == 403, f"Read-only scoped token should not create servers, got {response.status}: {response.text()}"
        finally:
            ctx.dispose()
            if created_server_id:
                with suppress(Exception):
                    admin_api.delete(f"/servers/{created_server_id}")

    def test_25_read_only_scoped_token_can_still_list_servers(self, playwright, read_only_scoped_token: dict[str, str]):
        ctx = _api_context(playwright, read_only_scoped_token["access_token"])
        try:
            response = ctx.get("/servers")
            assert response.status == 200, f"Read-only scoped token should list servers, got {response.status}: {response.text()}"
        finally:
            ctx.dispose()


class TestPlaywrightSecurityE2ETransportAndSanitization:
    """Browser-observable transport auth and UI sanitization protections."""

    def test_26_sse_message_endpoint_rejects_unauthenticated_requests(self, anon_api: APIRequestContext, public_server_id: str):
        if not settings.auth_required:
            pytest.skip("Auth is disabled; unauthenticated rejection checks are not applicable.")

        response = anon_api.post(
            f"/servers/{public_server_id}/message?session_id=security-e2e-{uuid.uuid4().hex[:8]}",
            data={"jsonrpc": "2.0", "id": "1", "method": "ping", "params": {}},
        )
        if response.status == 404:
            pytest.skip("SSE message endpoint is unavailable in this environment.")
        assert response.status in (401, 403), f"Unauthenticated message endpoint should be denied, got {response.status}: {response.text()}"

    def test_27_sse_message_endpoint_allows_authenticated_requests(self, playwright, public_server_id: str):
        ctx = _api_context(playwright, _make_jwt("admin@example.com", is_admin=True, teams=None))
        try:
            response = ctx.post(
                f"/servers/{public_server_id}/message?session_id=security-e2e-{uuid.uuid4().hex[:8]}",
                data={"jsonrpc": "2.0", "id": "2", "method": "ping", "params": {}},
            )
            if response.status == 404:
                pytest.skip("SSE message endpoint is unavailable in this environment.")
            assert response.status not in (401, 403), f"Authenticated message endpoint should not fail auth, got {response.status}: {response.text()}"
        finally:
            ctx.dispose()

    def test_28_websocket_unauthenticated_is_blocked_when_auth_is_enforced(self, context: BrowserContext):
        if not (settings.mcp_client_auth_enabled or settings.auth_required):
            pytest.skip("WebSocket auth enforcement is disabled in this environment.")

        page = context.new_page()
        result = _probe_websocket(page, _ws_url())

        # A successful unauthenticated JSON-RPC parse error message would indicate auth bypass.
        assert result.get("event") != "message", f"Unauthenticated WebSocket unexpectedly accepted payload: {result}"
        assert result.get("event") in ("close", "error", "timeout", "exception")

    def test_29_websocket_authenticated_handles_invalid_jsonrpc_payload(self, context: BrowserContext):
        page = context.new_page()
        token = _make_jwt("admin@example.com", is_admin=True, teams=None)
        result = _probe_websocket(page, _ws_url(token))

        if result.get("event") in ("timeout", "error", "exception"):
            pytest.skip(f"WebSocket endpoint unavailable or unreachable in this environment: {result}")

        if result.get("event") == "close" and result.get("code") in (1005, 1006):
            pytest.skip(f"WebSocket endpoint unavailable in this environment: {result}")

        if result.get("event") == "message":
            payload = str(result.get("data", ""))
            assert "Parse error" in payload or "jsonrpc" in payload
        else:
            assert result.get("event") == "close"
            assert result.get("code") in (1000, 1008, 1011), f"Unexpected authenticated WebSocket close behavior: {result}"

    def test_30_xss_payloads_do_not_execute_in_login_errors_or_server_catalog(self, admin_api: APIRequestContext, admin_page):
        nonce = uuid.uuid4().hex[:8]

        admin_page.page.goto(f"/admin/login?error=<img src=x onerror=window.__pw_xss_login_{nonce}=1>")
        expect(admin_page.page.locator("#error-message")).to_be_visible()
        login_xss_marker = admin_page.page.evaluate(f"Boolean(window.__pw_xss_login_{nonce})")
        assert login_xss_marker is False, "Error query parameter executed JavaScript in login page."

        server_name = f'<script>window.__pw_xss_catalog_{nonce}=1</script>xss-{nonce}'
        create_resp = admin_api.post(
            "/servers",
            data={
                "server": {"name": server_name, "description": "xss catalog probe"},
                "team_id": None,
                "visibility": "public",
            },
        )

        created_server_id: str | None = None
        if create_resp.status in (200, 201):
            created_server_id = create_resp.json()["id"]
        else:
            assert create_resp.status in (400, 422), f"Unexpected server create response for XSS probe: {create_resp.status} {create_resp.text()}"
            assert "traceback" not in create_resp.text().lower()
            return

        dialog_seen = {"value": False}

        def _on_dialog(dialog) -> None:
            dialog_seen["value"] = True
            dialog.dismiss()

        admin_page.page.on("dialog", _on_dialog)

        try:
            admin_page.page.evaluate(f"window.__pw_xss_catalog_{nonce}=0")
            admin_page.navigate()
            admin_page.click_servers_tab()
            admin_page.search_servers(f"xss-{nonce}")
            row = admin_page.page.locator(f'[data-testid="server-item"]:has-text("xss-{nonce}")').first
            expect(row).to_be_visible()

            catalog_xss_marker = admin_page.page.evaluate(f"window.__pw_xss_catalog_{nonce}")
            assert catalog_xss_marker == 0, "Server catalog rendered executable JavaScript from server name."
            assert dialog_seen["value"] is False, "Server catalog triggered a browser dialog from injected markup."
        finally:
            if created_server_id:
                with suppress(Exception):
                    admin_api.delete(f"/servers/{created_server_id}")
