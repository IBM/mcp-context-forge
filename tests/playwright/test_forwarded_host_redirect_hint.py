# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_forwarded_host_redirect_hint.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Playwright tests verifying that the OAuth redirect_uri hint in the admin UI
reflects the ``X-Forwarded-Host`` header when the gateway is behind a proxy.

Covers issue #4354: the admin UI's "Use: ..." hint for the OAuth redirect_uri
should show the proxy's public host, not the gateway's internal address.
"""

# Standard
import re

# Third-Party
from playwright.sync_api import expect, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import pytest

# Local
from .conftest import _ensure_admin_logged_in

_FORWARDED_HOST = "frontend-proxy.example.com"
_FORWARDED_PROTO = "https"

# CSS selector for the OAuth redirect_uri hint <code> element in the
# add-gateway form.  The hint lives inside #oauth-auth-code-fields-gw.
_HINT_CODE_SELECTOR_GW = "#oauth-auth-code-fields-gw p.text-blue-600 code.bg-blue-100"


def _wait_for_admin_content(page: Page) -> None:
    """Wait for admin app to settle after navigation."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1500)


@pytest.mark.ui
class TestForwardedHostRedirectHint:
    """Verify the OAuth redirect_uri hint reflects X-Forwarded-Host.

    Uses ``page.route()`` to intercept requests to the admin panel and
    re-fetch them with ``X-Forwarded-Host`` / ``X-Forwarded-Proto`` headers
    injected, simulating a reverse-proxy deployment.
    """

    @pytest.fixture(autouse=True)
    def _inject_forwarded_headers(self, page: Page, base_url: str):
        """Intercept admin requests and inject X-Forwarded-Host/Proto headers."""
        page.set_default_timeout(10000)

        def _handle_route(route):
            # Skip SSE event-stream requests -- they are long-lived and will
            # cause TargetClosedError on teardown.
            if "/events" in route.request.url:
                route.continue_()
                return
            response = route.fetch(
                headers={
                    **route.request.headers,
                    "x-forwarded-host": _FORWARDED_HOST,
                    "x-forwarded-proto": _FORWARDED_PROTO,
                },
            )
            route.fulfill(response=response)

        pattern = re.compile(re.escape(base_url.rstrip("/")) + r"/.*")
        page.route(pattern, _handle_route)
        yield
        page.unroute_all(behavior="ignoreErrors")

    def test_gateway_add_form_redirect_hint_uses_forwarded_host(self, page: Page, base_url: str):
        """The redirect_uri hint in the Add Gateway form shows the proxy host."""
        _ensure_admin_logged_in(page, base_url)

        page.goto(f"{base_url.rstrip('/')}/admin/#gateways")
        _wait_for_admin_content(page)

        # Reveal OAuth fields: select auth type "oauth".
        auth_type_select = page.locator("#auth-type-gw")
        auth_type_select.select_option("oauth")
        page.wait_for_selector("#auth-oauth-fields-gw", state="visible", timeout=5000)

        # authorization_code is the default grant type, so
        # #oauth-auth-code-fields-gw should already be visible.
        page.wait_for_selector("#oauth-auth-code-fields-gw", state="visible", timeout=5000)

        # Assert the hint <code> element contains the forwarded host.
        hint_code = page.locator(_HINT_CODE_SELECTOR_GW)
        expect(hint_code).to_be_visible()

        hint_text = hint_code.text_content()
        assert hint_text is not None, "Hint <code> element has no text content"

        expected_prefix = f"{_FORWARDED_PROTO}://{_FORWARDED_HOST}"
        assert hint_text.startswith(expected_prefix), f"Expected redirect_uri hint to start with '{expected_prefix}', but got: '{hint_text}'"
        assert hint_text.endswith("oauth/callback"), f"Expected redirect_uri hint to end with 'oauth/callback', but got: '{hint_text}'"

    def test_gateway_add_form_redirect_hint_without_forwarded_host(self, page: Page, base_url: str):
        """Without X-Forwarded-Host, the hint shows the direct server address."""
        # Remove the autouse routes so no forwarded headers are injected.
        page.unroute_all(behavior="ignoreErrors")

        _ensure_admin_logged_in(page, base_url)
        page.goto(f"{base_url.rstrip('/')}/admin/#gateways")
        _wait_for_admin_content(page)

        auth_type_select = page.locator("#auth-type-gw")
        auth_type_select.select_option("oauth")
        page.wait_for_selector("#auth-oauth-fields-gw", state="visible", timeout=5000)
        page.wait_for_selector("#oauth-auth-code-fields-gw", state="visible", timeout=5000)

        hint_code = page.locator(_HINT_CODE_SELECTOR_GW)
        expect(hint_code).to_be_visible()

        hint_text = hint_code.text_content()
        assert hint_text is not None, "Hint <code> element has no text content"

        # Without forwarded headers, should NOT show the proxy host.
        assert _FORWARDED_HOST not in hint_text, f"Hint should not contain forwarded host '{_FORWARDED_HOST}' without forwarding headers, but got: '{hint_text}'"
        assert hint_text.endswith("oauth/callback"), f"Expected redirect_uri hint to end with 'oauth/callback', but got: '{hint_text}'"
