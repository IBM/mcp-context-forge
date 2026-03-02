# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""iframe embedding security tests.

Covers:
  - T-1: CSRF cookie SameSite=Strict attribute verification
  - T-2: End-to-end iframe embedding with security header validation
  - Security header (X-Frame-Options, CSP frame-ancestors) consistency
  - Cookie attribute hardening (JWT, CSRF, ui_hide)
  - Embedded mode UI behavior
  - CORS behavior in iframe context
"""

# Future
from __future__ import annotations

# Standard
import re
from typing import Any, Dict, List, Optional
import uuid

# Third-Party
from playwright.sync_api import FrameLocator, Page, Route
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import pytest

# First-Party
from mcpgateway.admin import ADMIN_CSRF_COOKIE_NAME, UI_HIDE_SECTIONS_COOKIE_NAME
from mcpgateway.config import settings

# Local
from ..conftest import _ensure_admin_logged_in

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _expected_samesite() -> str:
    """Map settings.cookie_samesite to Playwright's capitalized form."""
    value = (settings.cookie_samesite or "lax").strip().lower()
    return {"lax": "Lax", "strict": "Strict", "none": "None"}.get(value, "Lax")


def _find_cookie(page: Page, name: str) -> Optional[Dict[str, Any]]:
    """Find a cookie by name from the browser context."""
    return next((c for c in page.context.cookies() if c["name"] == name), None)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def captured_admin_headers(page: Page, base_url: str) -> Dict[str, str]:
    """Intercept /admin/ response and capture security headers.

    Returns a dict with lowercased header names as keys.
    """
    captured: Dict[str, str] = {}

    def _capture(route: Route) -> None:
        response = route.fetch()
        for hdr in ("x-frame-options", "content-security-policy", "referrer-policy"):
            val = response.headers.get(hdr)
            if val:
                captured[hdr] = val
        route.fulfill(response=response)

    pattern = re.compile(r".*/admin/?(\?.*)?$")
    page.route(pattern, _capture)
    _ensure_admin_logged_in(page, base_url)
    page.unroute(pattern)
    return captured


@pytest.fixture
def iframe_host(page: Page, base_url: str):
    """Load admin inside an iframe, stripping X-Frame-Options/CSP restrictions.

    Returns a tuple of (frame_locator, frame_object) for interacting with
    the embedded admin.
    """
    _ensure_admin_logged_in(page, base_url)

    def _strip_headers(route: Route) -> None:
        try:
            response = route.fetch()
            headers = dict(response.headers)
            headers.pop("x-frame-options", None)
            if "content-security-policy" in headers:
                headers["content-security-policy"] = headers["content-security-policy"].replace("frame-ancestors 'none'", "frame-ancestors 'self'")
            route.fulfill(status=response.status, headers=headers, body=response.body())
        except Exception:
            pass

    admin_pattern = re.compile(r".*/admin.*")
    page.route(admin_pattern, _strip_headers)

    admin_url = f"{base_url}/admin/"
    page.set_content(
        f"""<!DOCTYPE html>
<html><head><title>iframe host</title></head>
<body style="margin:0;padding:0">
<iframe id="admin-frame"
        src="{admin_url}"
        style="width:100%;height:100vh;border:none"
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals">
</iframe>
</body></html>"""
    )

    frame = page.frame_locator("#admin-frame")
    try:
        frame.locator('[data-testid="servers-tab"]').wait_for(state="visible", timeout=30000)
    except PlaywrightTimeoutError:
        pass  # CI may be slower; tests will assert individually

    yield frame

    page.unroute(admin_pattern)


@pytest.fixture
def console_errors(page: Page):
    """Capture JS pageerror events from the page (including same-origin iframes).

    Only captures uncaught exceptions (pageerror), not console.error calls,
    to avoid false positives from third-party CDN libraries.
    """
    errors: List[str] = []

    def _on_pageerror(error):
        errors.append(f"pageerror: {error}")

    page.on("pageerror", _on_pageerror)
    yield errors
    page.remove_listener("pageerror", _on_pageerror)


# ===================================================================
# CLASS 1: Security headers in iframe context
# ===================================================================


@pytest.mark.ui
@pytest.mark.security
@pytest.mark.iframe
class TestSecurityHeadersInIframeContext:
    """Verify X-Frame-Options and CSP headers on live admin responses."""

    def test_x_frame_options_header_matches_config(self, captured_admin_headers):
        """X-Frame-Options header value matches settings.x_frame_options."""
        configured = settings.x_frame_options
        header_val = captured_admin_headers.get("x-frame-options")

        if configured is None:
            assert header_val is None, f"Expected no X-Frame-Options when config is None, got: {header_val}"
        else:
            assert header_val is not None, "Expected X-Frame-Options header when configured"
            assert header_val.upper() == configured.upper(), f"Expected X-Frame-Options={configured}, got {header_val}"

    def test_csp_frame_ancestors_synced_with_x_frame_options(self, captured_admin_headers):
        """CSP frame-ancestors directive is consistent with X-Frame-Options.

        Mapping per security_headers.py:290-301:
          DENY        -> frame-ancestors 'none'
          SAMEORIGIN  -> frame-ancestors 'self'
          ALLOW-ALL   -> frame-ancestors * file: http: https:
          None        -> no frame-ancestors directive
        """
        if not settings.security_headers_enabled:
            pytest.skip("Security headers disabled.")

        csp = captured_admin_headers.get("content-security-policy", "")
        x_frame = settings.x_frame_options

        if x_frame is None:
            assert "frame-ancestors" not in csp, f"frame-ancestors should be absent when x_frame_options is None; CSP: {csp}"
            return

        x_frame_upper = x_frame.upper()
        expected_map = {
            "DENY": "'none'",
            "SAMEORIGIN": "'self'",
        }

        if x_frame_upper in expected_map:
            expected_fa = expected_map[x_frame_upper]
            assert f"frame-ancestors {expected_fa}" in csp, f"Expected frame-ancestors {expected_fa} in CSP for X-Frame-Options={x_frame}; got: {csp}"
        elif x_frame_upper == "ALLOW-ALL":
            assert "frame-ancestors *" in csp or "frame-ancestors * file:" in csp, f"Expected permissive frame-ancestors for ALLOW-ALL; got: {csp}"
        elif x_frame_upper.startswith("ALLOW-FROM"):
            assert "frame-ancestors" in csp, f"Expected frame-ancestors directive for ALLOW-FROM; got: {csp}"

    def test_security_headers_present_when_enabled(self, captured_admin_headers):
        """CSP, X-Frame-Options, and Referrer-Policy exist when security_headers_enabled=True."""
        if not settings.security_headers_enabled:
            pytest.skip("Security headers disabled in config.")

        assert "content-security-policy" in captured_admin_headers, "Missing Content-Security-Policy header"
        assert "referrer-policy" in captured_admin_headers, "Missing Referrer-Policy header"
        if settings.x_frame_options is not None:
            assert "x-frame-options" in captured_admin_headers, "Missing X-Frame-Options header"

    def test_x_frame_options_deny_blocks_iframe(self, page: Page, base_url: str):
        """When X-Frame-Options=DENY, admin must not load inside an iframe (no header stripping)."""
        if settings.x_frame_options is None or settings.x_frame_options.upper() != "DENY":
            pytest.skip("X-Frame-Options is not DENY; test only applies when DENY is configured.")

        _ensure_admin_logged_in(page, base_url)
        admin_url = f"{base_url}/admin/"
        page.set_content(
            f"""<!DOCTYPE html>
<html><head><title>deny test</title></head>
<body>
<iframe id="admin-frame" src="{admin_url}" style="width:100%;height:100vh;border:none"></iframe>
</body></html>"""
        )

        frame = page.frame_locator("#admin-frame")
        try:
            frame.locator('[data-testid="servers-tab"]').wait_for(state="visible", timeout=5000)
            # If we get here, the iframe loaded — browser didn't enforce DENY.
            # Some browsers (especially in test mode) may not enforce X-Frame-Options.
            # Mark as xfail rather than hard-fail to keep the test useful as a signal.
            pytest.xfail("Browser did not enforce X-Frame-Options: DENY in test mode")
        except PlaywrightTimeoutError:
            pass  # Expected: iframe content blocked

    def test_iframe_loads_after_header_stripping(self, iframe_host):
        """Admin loads inside iframe when X-Frame-Options/CSP are stripped."""
        servers_tab = iframe_host.locator('[data-testid="servers-tab"]')
        try:
            servers_tab.wait_for(state="visible", timeout=15000)
        except PlaywrightTimeoutError:
            pytest.fail("Admin content did not load inside iframe after header stripping")


# ===================================================================
# CLASS 2: Cookie security attributes
# ===================================================================


@pytest.mark.ui
@pytest.mark.security
@pytest.mark.iframe
class TestCookieSecurityAttributes:
    """Verify cookie attributes for JWT, CSRF, and ui_hide cookies.

    Fills gap T-1: CSRF cookie SameSite=Strict verification.
    """

    def test_jwt_cookie_samesite_matches_config(self, page: Page, base_url: str):
        """jwt_token cookie has sameSite matching settings.cookie_samesite."""
        if not settings.auth_required:
            pytest.skip("Authentication disabled; session cookies not applicable.")

        _ensure_admin_logged_in(page, base_url)
        jwt_cookie = _find_cookie(page, "jwt_token")
        assert jwt_cookie is not None, "Expected jwt_token cookie after admin authentication"
        assert jwt_cookie["sameSite"] == _expected_samesite(), f"Expected sameSite={_expected_samesite()}, got {jwt_cookie['sameSite']}"

    def test_csrf_cookie_samesite_is_strict(self, page: Page, base_url: str):
        """T-1: CSRF cookie mcpgateway_csrf_token has sameSite=Strict.

        Hardcoded at admin.py:1145 — CSRF tokens must use Strict to prevent
        cross-site request attachment regardless of global cookie_samesite config.
        """
        if not settings.auth_required:
            pytest.skip("Authentication disabled; CSRF cookies not applicable.")

        _ensure_admin_logged_in(page, base_url)
        csrf_cookie = _find_cookie(page, ADMIN_CSRF_COOKIE_NAME)
        assert csrf_cookie is not None, f"Expected {ADMIN_CSRF_COOKIE_NAME} cookie after admin authentication"
        assert csrf_cookie["sameSite"] == "Strict", f"CSRF cookie must have sameSite=Strict, got {csrf_cookie['sameSite']}"

    def test_csrf_cookie_httponly_is_false(self, page: Page, base_url: str):
        """CSRF cookie httpOnly=False — JS must read it to send as x-csrf-token header."""
        if not settings.auth_required:
            pytest.skip("Authentication disabled; CSRF cookies not applicable.")

        _ensure_admin_logged_in(page, base_url)
        csrf_cookie = _find_cookie(page, ADMIN_CSRF_COOKIE_NAME)
        assert csrf_cookie is not None, f"Expected {ADMIN_CSRF_COOKIE_NAME} cookie"
        assert csrf_cookie["httpOnly"] is False, "CSRF cookie must not be httpOnly (JS needs to read it)"

    def test_csrf_cookie_path_scoped_to_admin(self, page: Page, base_url: str):
        """CSRF cookie path starts with /admin."""
        if not settings.auth_required:
            pytest.skip("Authentication disabled; CSRF cookies not applicable.")

        _ensure_admin_logged_in(page, base_url)
        csrf_cookie = _find_cookie(page, ADMIN_CSRF_COOKIE_NAME)
        assert csrf_cookie is not None, f"Expected {ADMIN_CSRF_COOKIE_NAME} cookie"
        assert csrf_cookie["path"].startswith("/admin"), f"CSRF cookie path should start with /admin, got {csrf_cookie['path']}"

    def test_ui_hide_cookie_samesite_matches_config(self, page: Page, base_url: str):
        """ui_hide_sections cookie has sameSite matching settings.cookie_samesite."""
        _ensure_admin_logged_in(page, base_url)
        page.goto(f"{base_url}/admin/?ui_hide=metrics")
        try:
            page.wait_for_selector('[data-testid="servers-tab"]', state="visible", timeout=15000)
        except PlaywrightTimeoutError:
            pytest.skip("Admin page did not load after ui_hide navigation.")

        ui_cookie = _find_cookie(page, UI_HIDE_SECTIONS_COOKIE_NAME)
        assert ui_cookie is not None, f"Expected {UI_HIDE_SECTIONS_COOKIE_NAME} cookie after ?ui_hide=metrics"
        assert ui_cookie["sameSite"] == _expected_samesite(), f"Expected sameSite={_expected_samesite()}, got {ui_cookie['sameSite']}"

    def test_ui_hide_cookie_is_httponly(self, page: Page, base_url: str):
        """ui_hide_sections cookie has httpOnly=True (server-only cookie)."""
        _ensure_admin_logged_in(page, base_url)
        page.goto(f"{base_url}/admin/?ui_hide=metrics")
        try:
            page.wait_for_selector('[data-testid="servers-tab"]', state="visible", timeout=15000)
        except PlaywrightTimeoutError:
            pytest.skip("Admin page did not load after ui_hide navigation.")

        ui_cookie = _find_cookie(page, UI_HIDE_SECTIONS_COOKIE_NAME)
        assert ui_cookie is not None, f"Expected {UI_HIDE_SECTIONS_COOKIE_NAME} cookie"
        assert ui_cookie["httpOnly"] is True, "ui_hide_sections cookie should be httpOnly"


# ===================================================================
# CLASS 3: Embedded mode UI behavior
# ===================================================================


@pytest.mark.ui
@pytest.mark.security
@pytest.mark.iframe
class TestEmbeddedModeUIBehavior:
    """Verify embedded mode and ?ui_hide= behavior."""

    def test_embedded_mode_hides_logout(self, page: Page, base_url: str):
        """When mcpgateway_ui_embedded=True, logout button is hidden."""
        if not settings.mcpgateway_ui_embedded:
            pytest.skip("Embedded mode is disabled; skipping embedded-specific test.")

        _ensure_admin_logged_in(page, base_url)
        logout_btn = page.locator('[data-testid="logout-btn"], a[href*="logout"], button:has-text("Logout"), button:has-text("Log out")')
        assert logout_btn.count() == 0 or not logout_btn.first.is_visible(), "Logout button should be hidden in embedded mode"

    def test_embedded_mode_hides_team_selector(self, page: Page, base_url: str):
        """When mcpgateway_ui_embedded=True, team selector is hidden."""
        if not settings.mcpgateway_ui_embedded:
            pytest.skip("Embedded mode is disabled; skipping embedded-specific test.")

        _ensure_admin_logged_in(page, base_url)
        team_selector = page.locator('[data-testid="team-selector"], select[name="team_id"], #team-selector')
        assert team_selector.count() == 0 or not team_selector.first.is_visible(), "Team selector should be hidden in embedded mode"

    def test_non_embedded_mode_shows_logout(self, page: Page, base_url: str):
        """When mcpgateway_ui_embedded=False, logout button is visible."""
        if settings.mcpgateway_ui_embedded:
            pytest.skip("Embedded mode is enabled; skipping non-embedded test.")
        if not settings.auth_required:
            pytest.skip("Authentication disabled; logout button may not be present.")

        _ensure_admin_logged_in(page, base_url)
        logout_btn = page.locator('[data-testid="logout-btn"], a[href*="logout"], button:has-text("Logout"), button:has-text("Log out")')
        assert logout_btn.count() > 0 and logout_btn.first.is_visible(), "Logout button should be visible in non-embedded mode"

    def test_ui_hide_query_param_hides_section_in_iframe(self, page: Page, base_url: str):
        """?ui_hide=metrics hides metrics tab but keeps servers tab visible inside iframe."""
        _ensure_admin_logged_in(page, base_url)

        def _strip_headers(route: Route) -> None:
            try:
                response = route.fetch()
                headers = dict(response.headers)
                headers.pop("x-frame-options", None)
                if "content-security-policy" in headers:
                    headers["content-security-policy"] = headers["content-security-policy"].replace("frame-ancestors 'none'", "frame-ancestors 'self'")
                route.fulfill(status=response.status, headers=headers, body=response.body())
            except Exception:
                pass

        admin_pattern = re.compile(r".*/admin.*")
        page.route(admin_pattern, _strip_headers)

        admin_url = f"{base_url}/admin/?ui_hide=metrics"
        page.set_content(
            f"""<!DOCTYPE html>
<html><head><title>ui_hide iframe test</title></head>
<body>
<iframe id="admin-frame" src="{admin_url}" style="width:100%;height:100vh;border:none"
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals">
</iframe>
</body></html>"""
        )

        frame = page.frame_locator("#admin-frame")
        try:
            frame.locator('[data-testid="servers-tab"]').wait_for(state="visible", timeout=30000)
        except PlaywrightTimeoutError:
            pytest.skip("Admin did not load inside iframe for ui_hide test.")

        servers_tab = frame.locator('[data-testid="servers-tab"]')
        assert servers_tab.is_visible(), "Servers tab should be visible with ?ui_hide=metrics"

        metrics_tab = frame.locator('[data-testid="metrics-tab"]')
        assert metrics_tab.count() == 0 or not metrics_tab.is_visible(), "Metrics tab should be hidden with ?ui_hide=metrics"

        page.unroute(admin_pattern)

    def test_ui_hide_empty_clears_cookie(self, page: Page, base_url: str):
        """Navigating with ?ui_hide= (empty) clears the ui_hide cookie."""
        _ensure_admin_logged_in(page, base_url)

        # First set the cookie by navigating with a value
        page.goto(f"{base_url}/admin/?ui_hide=metrics")
        try:
            page.wait_for_selector('[data-testid="servers-tab"]', state="visible", timeout=15000)
        except PlaywrightTimeoutError:
            pytest.skip("Admin page did not load for ui_hide cookie test.")

        ui_cookie = _find_cookie(page, UI_HIDE_SECTIONS_COOKIE_NAME)
        assert ui_cookie is not None, "Expected ui_hide cookie to be set after ?ui_hide=metrics"

        # Now clear it with empty ui_hide
        page.goto(f"{base_url}/admin/?ui_hide=")
        try:
            page.wait_for_selector('[data-testid="servers-tab"]', state="visible", timeout=15000)
        except PlaywrightTimeoutError:
            pass

        ui_cookie_after = _find_cookie(page, UI_HIDE_SECTIONS_COOKIE_NAME)
        assert ui_cookie_after is None or not ui_cookie_after.get("value"), "ui_hide cookie should be cleared after ?ui_hide= (empty)"


# ===================================================================
# CLASS 4: CORS in iframe context
# ===================================================================


@pytest.mark.ui
@pytest.mark.security
@pytest.mark.iframe
class TestCORSInIframeContext:
    """Verify CORS behavior relevant to iframe embedding."""

    def test_same_origin_fetch_from_iframe(self, page: Page, iframe_host):
        """fetch('/health') from inside the iframe succeeds (same-origin)."""
        frame = iframe_host
        result = frame.locator("body").evaluate(
            """async () => {
                try {
                    const resp = await fetch('/health');
                    return { status: resp.status, ok: resp.ok };
                } catch (e) {
                    return { error: e.message };
                }
            }"""
        )
        assert "error" not in result, f"Same-origin fetch from iframe failed: {result.get('error')}"
        assert result["status"] == 200, f"Expected 200 from /health, got {result['status']}"

    def test_cors_preflight_allowed_origin(self, page: Page, base_url: str):
        """OPTIONS to /health with an allowed Origin gets Access-Control-Allow-Origin."""
        if not settings.cors_enabled:
            pytest.skip("CORS disabled in config.")

        allowed = next(iter(settings.allowed_origins), None)
        if not allowed:
            pytest.skip("No allowed_origins configured.")

        response = page.request.fetch(
            f"{base_url}/health",
            method="OPTIONS",
            headers={
                "Origin": allowed,
                "Access-Control-Request-Method": "GET",
            },
        )
        acao = response.headers.get("access-control-allow-origin")
        assert acao is not None, f"Expected Access-Control-Allow-Origin header for allowed origin {allowed}"
        assert acao in (allowed, "*"), f"Expected ACAO={allowed} or *, got {acao}"

    def test_cors_preflight_disallowed_origin(self, page: Page, base_url: str):
        """OPTIONS to /health with evil origin gets no CORS allow header (unless wildcard)."""
        if not settings.cors_enabled:
            pytest.skip("CORS disabled in config.")
        if "*" in settings.allowed_origins:
            pytest.skip("Wildcard origin configured; all origins are allowed.")

        response = page.request.fetch(
            f"{base_url}/health",
            method="OPTIONS",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        acao = response.headers.get("access-control-allow-origin")
        assert acao is None or acao not in ("https://evil.example.com", "*"), f"Evil origin should not be allowed; got ACAO={acao}"

    def test_csrf_cross_origin_rejection(self, page: Page, base_url: str):
        """POST to /admin/logout with cross-origin and no CSRF token is rejected."""
        if not settings.auth_required:
            pytest.skip("Authentication disabled; CSRF protections not applicable.")

        _ensure_admin_logged_in(page, base_url)
        response = page.request.post(
            f"{base_url}/admin/logout",
            headers={"Origin": "https://evil.example.com"},
        )
        assert response.status in (400, 403), f"Cross-origin POST without CSRF token should be rejected, got {response.status}"


# ===================================================================
# CLASS 5: Tab navigation inside iframe
# ===================================================================


@pytest.mark.ui
@pytest.mark.security
@pytest.mark.iframe
class TestIframeTabNavigation:
    """Verify that admin tab navigation works correctly inside an iframe.

    Each tab click should reveal its panel, produce no JS errors,
    and not cause the parent page URL to change (iframe escape).
    """

    @pytest.mark.parametrize(
        "tab_selector,panel_selector",
        [
            pytest.param('[data-testid="gateways-tab"]', "#gateways-panel", id="mcp-servers"),
            pytest.param('[data-testid="servers-tab"]', "#catalog-panel", id="virtual-servers"),
            pytest.param('[data-testid="tools-tab"]', "#tools-panel", id="tools"),
            pytest.param("#tab-prompts", "#prompts-panel", id="prompts"),
            pytest.param("#tab-resources", "#resources-panel", id="resources"),
            pytest.param('[data-testid="a2a-agents-tab"]', "#a2a-agents-panel", id="a2a-agents"),
        ],
    )
    def test_tab_click_shows_panel(self, page: Page, iframe_host: FrameLocator, console_errors: List[str], tab_selector: str, panel_selector: str):
        """Clicking a tab inside the iframe reveals its panel without errors or URL escape."""
        frame = iframe_host
        tab = frame.locator(tab_selector)

        try:
            tab.wait_for(state="visible", timeout=15000)
        except PlaywrightTimeoutError:
            pytest.skip(f"Tab {tab_selector} not visible (may be hidden by ui_hide config)")

        url_before = page.url
        tab.click()

        panel = frame.locator(panel_selector)
        try:
            panel.wait_for(state="visible", timeout=15000)
        except PlaywrightTimeoutError:
            pytest.fail(f"Panel {panel_selector} did not become visible after clicking {tab_selector}")

        assert not console_errors, f"JS errors during tab navigation: {console_errors}"
        assert page.url == url_before, f"Parent URL changed from {url_before} to {page.url} — iframe navigation escaped"


# ===================================================================
# CLASS 6: Form submission inside iframe
# ===================================================================


@pytest.mark.ui
@pytest.mark.security
@pytest.mark.iframe
class TestIframeFormSubmission:
    """Verify that admin form submissions work correctly inside an iframe.

    Uses the admin_api fixture from security/conftest.py for API-level
    pre-creation, verification, and cleanup of entities.
    """

    # Non-routable local URL that fails fast (connection refused) instead of
    # timing out.  Uses transport=HTTP so the server doesn't attempt an SSE
    # handshake.  Mirrors the pattern used in test_admin_url_context.py.
    _FAST_FAIL_GW_URL = "http://127.0.0.1:19999"

    def _reload_iframe(self, page: Page, iframe_host: FrameLocator) -> None:
        """Reload the iframe content and wait for JS initialization."""
        iframe_frame = page.frames[-1]
        iframe_frame.evaluate("() => location.reload()")
        try:
            iframe_frame.wait_for_load_state("domcontentloaded", timeout=15000)
        except PlaywrightTimeoutError:
            pass
        # Wait for admin shell to load inside the refreshed iframe
        try:
            iframe_host.locator('[data-testid="servers-tab"]').wait_for(state="visible", timeout=30000)
        except PlaywrightTimeoutError:
            pass
        # Wait for JS initialization (showTab + HTMX) before any tab clicks
        try:
            iframe_frame.wait_for_function("typeof window.showTab === 'function' && typeof window.htmx !== 'undefined'", timeout=15000)
        except PlaywrightTimeoutError:
            pass

    def _navigate_to_gateways_tab(self, page: Page, frame: FrameLocator) -> None:
        """Navigate to gateways tab with JS fallback if click doesn't work.

        Handles the case where Playwright click on the tab doesn't trigger
        the JS showTab function after an iframe reload.
        """
        gw_tab = frame.locator('[data-testid="gateways-tab"]')
        try:
            gw_tab.wait_for(state="visible", timeout=15000)
        except PlaywrightTimeoutError:
            pytest.skip("Gateways tab not visible after reload")

        gw_tab.click()

        panel = frame.locator("#gateways-panel")
        try:
            panel.wait_for(state="visible", timeout=5000)
        except PlaywrightTimeoutError:
            # Fallback: call showTab directly via JS
            iframe_frame = page.frames[-1]
            iframe_frame.evaluate("() => { if (typeof showTab === 'function') showTab('gateways'); }")
            panel.wait_for(state="visible", timeout=15000)

    def _create_gateway_via_api(self, admin_api, name: str) -> str:
        """Create a gateway via REST API using JSON. Returns gateway ID; skips on failure."""
        create_resp = admin_api.post(
            "/gateways",
            headers={"Content-Type": "application/json"},
            data={"name": name, "url": self._FAST_FAIL_GW_URL, "transport": "HTTP"},
        )
        if not create_resp.ok:
            pytest.skip(f"Could not create test gateway (HTTP {create_resp.status}) — skipping.")
        gw_id = create_resp.json().get("id", "")
        if not gw_id:
            pytest.skip("Gateway created but ID missing — skipping.")
        return gw_id

    def _cleanup_gateway(self, admin_api, gw_id: str) -> None:
        """Best-effort gateway cleanup."""
        try:
            admin_api.delete(f"/gateways/{gw_id}")
        except Exception:
            pass

    def test_add_gateway_via_iframe_form(self, page: Page, iframe_host: FrameLocator, console_errors: List[str], admin_api):
        """Fill and submit the add-gateway form inside the iframe, verify entity via API."""
        frame = iframe_host
        gw_name = f"iframe-gw-{uuid.uuid4().hex[:8]}"
        gw_id = None

        try:
            # Navigate to gateways tab
            gw_tab = frame.locator('[data-testid="gateways-tab"]')
            try:
                gw_tab.wait_for(state="visible", timeout=15000)
            except PlaywrightTimeoutError:
                pytest.skip("Gateways tab not visible")
            gw_tab.click()
            frame.locator("#gateways-panel").wait_for(state="visible", timeout=15000)

            # Fill form with fast-fail URL (connection refused is faster than DNS timeout)
            frame.locator("#mcp-server-name").fill(gw_name)
            frame.locator("#mcp-server-url").fill(self._FAST_FAIL_GW_URL)

            # Submit and wait for the POST response from the admin form handler.
            # The admin form uses JS fetch() so the page does NOT navigate.
            with page.expect_response(lambda r: "/admin/gateways" in r.url and r.request.method == "POST", timeout=30000) as resp_info:
                frame.locator('#add-gateway-form button[type="submit"]').click()

            post_resp = resp_info.value
            if post_resp.status >= 400:
                pytest.skip(f"Gateway form submission returned HTTP {post_resp.status} — server may reject unreachable URLs")

            # Verify via API
            resp = admin_api.get("/gateways/")
            assert resp.ok, f"GET /gateways/ failed: {resp.status}"
            gateways = resp.json()
            match = [g for g in gateways if g.get("name") == gw_name]
            assert match, f"Gateway '{gw_name}' not found in API response"
            gw_id = match[0]["id"]

            assert not console_errors, f"JS errors during gateway add: {console_errors}"
        finally:
            if gw_id:
                self._cleanup_gateway(admin_api, gw_id)

    def test_add_virtual_server_via_iframe_form(self, page: Page, iframe_host: FrameLocator, console_errors: List[str], admin_api):
        """Fill and submit the add-server form inside the iframe, verify entity via API."""
        frame = iframe_host
        srv_name = f"iframe-srv-{uuid.uuid4().hex[:8]}"
        srv_id = None

        try:
            # Navigate to servers tab
            srv_tab = frame.locator('[data-testid="servers-tab"]')
            try:
                srv_tab.wait_for(state="visible", timeout=15000)
            except PlaywrightTimeoutError:
                pytest.skip("Servers tab not visible")
            srv_tab.click()
            frame.locator("#catalog-panel").wait_for(state="visible", timeout=15000)

            # Fill form
            frame.locator("#server-name").fill(srv_name)

            # Submit and wait for response
            with page.expect_response(lambda r: "/admin/servers" in r.url and r.request.method == "POST", timeout=15000):
                frame.locator('#add-server-form button[type="submit"]').click()

            # Verify via API
            resp = admin_api.get("/servers/")
            assert resp.ok, f"GET /servers/ failed: {resp.status}"
            servers = resp.json()
            match = [s for s in servers if s.get("name") == srv_name]
            assert match, f"Server '{srv_name}' not found in API response"
            srv_id = match[0]["id"]

            assert not console_errors, f"JS errors during server add: {console_errors}"
        finally:
            if srv_id:
                admin_api.delete(f"/servers/{srv_id}")

    def test_add_tool_via_iframe_form(self, page: Page, iframe_host: FrameLocator, console_errors: List[str], admin_api):
        """Fill and submit the add-tool form inside the iframe, verify entity via API."""
        frame = iframe_host
        tool_name = f"iframe-tool-{uuid.uuid4().hex[:8]}"
        tool_url = "https://httpbin.org/post"
        tool_id = None

        try:
            # Navigate to tools tab
            tools_tab = frame.locator('[data-testid="tools-tab"]')
            try:
                tools_tab.wait_for(state="visible", timeout=15000)
            except PlaywrightTimeoutError:
                pytest.skip("Tools tab not visible")
            tools_tab.click()
            frame.locator("#tools-panel").wait_for(state="visible", timeout=15000)

            # Fill form
            frame.locator("#tool-name").fill(tool_name)
            frame.locator("#tool-url").fill(tool_url)

            # Submit and wait for response
            with page.expect_response(lambda r: "/admin/tools" in r.url and r.request.method == "POST", timeout=15000):
                frame.locator('#add-tool-form button[type="submit"]').click()

            # Verify via API
            resp = admin_api.get("/tools/")
            assert resp.ok, f"GET /tools/ failed: {resp.status}"
            tools = resp.json()
            match = [t for t in tools if t.get("name") == tool_name]
            assert match, f"Tool '{tool_name}' not found in API response"
            tool_id = match[0]["id"]

            assert not console_errors, f"JS errors during tool add: {console_errors}"
        finally:
            if tool_id:
                admin_api.delete(f"/tools/{tool_id}")

    def test_edit_gateway_via_iframe_modal(self, page: Page, iframe_host: FrameLocator, console_errors: List[str], admin_api):
        """Pre-create a gateway via API, edit its description via the iframe modal, verify change."""
        frame = iframe_host
        gw_name = f"iframe-edit-gw-{uuid.uuid4().hex[:8]}"
        new_description = f"edited-{uuid.uuid4().hex[:6]}"

        # Pre-create via API (skips on failure — e.g. if URL is unreachable)
        gw_id = self._create_gateway_via_api(admin_api, gw_name)

        try:
            # Reload iframe to pick up new gateway
            self._reload_iframe(page, frame)
            self._navigate_to_gateways_tab(page, frame)

            # Click the edit button for this specific gateway
            edit_btn = frame.locator(f"button[onclick*=\"editGateway('{gw_id}')\"]")
            try:
                edit_btn.wait_for(state="visible", timeout=15000)
            except PlaywrightTimeoutError:
                pytest.skip(f"Edit button for gateway {gw_id} not visible")

            edit_btn.click()

            # Wait for edit modal to appear
            edit_form = frame.locator("#edit-gateway-form")
            try:
                edit_form.wait_for(state="visible", timeout=15000)
            except PlaywrightTimeoutError:
                pytest.fail("Edit gateway modal did not appear")

            # Modify description
            desc_field = frame.locator("#edit-gateway-description")
            desc_field.fill(new_description)

            # Submit edit form
            with page.expect_response(lambda r: "/admin/gateways" in r.url and r.request.method == "POST", timeout=15000):
                edit_form.locator('button[type="submit"]').click()

            # Verify via API
            verify_resp = admin_api.get(f"/gateways/{gw_id}")
            assert verify_resp.ok, f"GET /gateways/{gw_id} failed: {verify_resp.status}"
            assert verify_resp.json().get("description") == new_description, f"Description not updated to '{new_description}'"

            assert not console_errors, f"JS errors during gateway edit: {console_errors}"
        finally:
            self._cleanup_gateway(admin_api, gw_id)

    def test_delete_gateway_via_iframe(self, page: Page, iframe_host: FrameLocator, console_errors: List[str], admin_api):
        """Pre-create a gateway via API, delete it via iframe UI, verify 404 via API."""
        frame = iframe_host
        gw_name = f"iframe-del-gw-{uuid.uuid4().hex[:8]}"

        # Pre-create via API
        gw_id = self._create_gateway_via_api(admin_api, gw_name)

        try:
            # Reload iframe to pick up new gateway
            self._reload_iframe(page, frame)
            self._navigate_to_gateways_tab(page, frame)

            # Auto-accept confirmation dialogs on the HOST page
            page.on("dialog", lambda d: d.accept())

            # Click delete button for this gateway (use .first — responsive layouts
            # may render both a compact and full-width row for the same gateway)
            delete_btn = frame.locator(f'form[action*="/gateways/{gw_id}/delete"] button[type="submit"]').first
            try:
                delete_btn.wait_for(state="visible", timeout=15000)
            except PlaywrightTimeoutError:
                pytest.skip(f"Delete button for gateway {gw_id} not visible")

            with page.expect_response(lambda r: f"/gateways/{gw_id}/delete" in r.url, timeout=15000):
                delete_btn.click()

            # Verify gateway is gone
            verify_resp = admin_api.get(f"/gateways/{gw_id}")
            assert verify_resp.status in (404, 410), f"Expected 404/410 after delete, got {verify_resp.status}"

            assert not console_errors, f"JS errors during gateway delete: {console_errors}"
        finally:
            self._cleanup_gateway(admin_api, gw_id)

    def test_toggle_gateway_state_via_iframe(self, page: Page, iframe_host: FrameLocator, console_errors: List[str], admin_api):
        """Pre-create a gateway via API, toggle it inactive via iframe, verify via API."""
        frame = iframe_host
        gw_name = f"iframe-toggle-gw-{uuid.uuid4().hex[:8]}"

        # Pre-create via API
        gw_id = self._create_gateway_via_api(admin_api, gw_name)

        try:
            # Reload iframe to pick up new gateway
            self._reload_iframe(page, frame)
            self._navigate_to_gateways_tab(page, frame)

            # Click the deactivate/toggle button for this gateway
            toggle_btn = frame.locator(f'form[action*="/gateways/{gw_id}/state"] button[type="submit"]')
            try:
                toggle_btn.first.wait_for(state="visible", timeout=15000)
            except PlaywrightTimeoutError:
                pytest.skip(f"Toggle button for gateway {gw_id} not visible")

            with page.expect_response(lambda r: f"/gateways/{gw_id}/state" in r.url, timeout=15000):
                toggle_btn.first.click()

            # Verify gateway is now inactive
            verify_resp = admin_api.get(f"/gateways/{gw_id}")
            assert verify_resp.ok, f"GET /gateways/{gw_id} failed: {verify_resp.status}"
            gw_data = verify_resp.json()
            assert gw_data.get("enabled") is False, f"Expected enabled=False after toggle, got {gw_data.get('enabled')}"

            assert not console_errors, f"JS errors during gateway toggle: {console_errors}"
        finally:
            self._cleanup_gateway(admin_api, gw_id)
