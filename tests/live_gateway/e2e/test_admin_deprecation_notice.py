# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_admin_deprecation_notice.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify the Admin UI deprecation notice against a running gateway.

Set MCPGATEWAY_UI_DEPRECATION_NOTICE_ENABLED identically in the gateway and test process.
Run once with the default and once with false to exercise both configurations.
Install Playwright Chromium to run the dismissal and refresh browser test.
"""

# Standard
import os

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]


def test_authenticated_admin_deprecation_notice() -> None:
    """Render one notice when enabled and keep HTMX partials free of duplicate notices."""
    enabled = os.getenv("MCPGATEWAY_UI_DEPRECATION_NOTICE_ENABLED", "true").strip().lower() in {"true", "1", "yes", "on"}
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
    with httpx.Client(base_url=BASE_URL, headers=make_auth_headers(token), timeout=30) as client:
        response = client.get("/admin/")
        if response.status_code == 404:
            pytest.skip("Admin UI is disabled on this gateway")
        assert response.status_code == 200
        assert response.text.count('id="admin-ui-deprecation-notice"') == int(enabled)
        assert ('datetime="2027-01-27"' in response.text) is enabled
        assert ("27 January 2027" in response.text) is enabled

        partial = client.get("/admin/tools/partial", headers={"HX-Request": "true"})
        assert partial.status_code == 200
        assert 'id="admin-ui-deprecation-notice"' not in partial.text


def test_banner_dismissal_resets_on_refresh() -> None:
    """Hide the notice during navigation and restore it on refresh without changing the feature flag."""
    playwright = pytest.importorskip("playwright.sync_api")
    enabled = os.getenv("MCPGATEWAY_UI_DEPRECATION_NOTICE_ENABLED", "true").strip().lower() in {"true", "1", "yes", "on"}
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        try:
            context = browser.new_context()
            context.add_cookies([{"name": "jwt_token", "value": token, "url": BASE_URL}])
            page = context.new_page()
            response = page.goto(f"{BASE_URL}/admin/")
            assert response is not None
            if response.status == 404:
                pytest.skip("Admin UI is disabled on this gateway")
            assert response.status == 200
            banner = page.locator("#admin-ui-deprecation-notice")
            if not enabled:
                playwright.expect(banner).to_have_count(0)
                return

            playwright.expect(banner).to_be_visible()
            dismiss = page.get_by_role("button", name="Dismiss deprecation notice")
            dismiss.click()
            playwright.expect(banner).to_be_hidden()
            page.locator("#tab-tools").click()
            playwright.expect(banner).to_be_hidden()
            page.reload()
            playwright.expect(banner).to_be_visible()
            dismiss.focus()
            dismiss.press("Enter")
            playwright.expect(banner).to_be_hidden()
            page.reload()
            playwright.expect(banner).to_be_visible()
        finally:
            browser.close()


@pytest.mark.parametrize("path", ["/admin/login", "/admin/forgot-password"])
def test_authentication_screens_exclude_deprecation_notice(path: str) -> None:
    """Exclude the deprecation notice from authentication screens.

    Args:
        path: Authentication screen URL path.
    """
    response = httpx.get(f"{BASE_URL}{path}", timeout=30)
    if response.status_code == 404:
        pytest.skip("Admin UI or password recovery is disabled on this gateway")
    assert response.status_code == 200
    assert 'id="admin-ui-deprecation-notice"' not in response.text
