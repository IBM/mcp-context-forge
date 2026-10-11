# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/security/test_admin_flash_message_xss.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for the admin dashboard ``?error=`` / ``?message=`` flash banner.

A crafted link must not execute script in a logged-in admin session or choose
the banner wording. The banner maps a fixed set of codes to text; anything else
shows a generic error.
"""

# Future
from __future__ import annotations

# Standard
from urllib.parse import quote

# Third-Party
from playwright.sync_api import Page
import pytest

# Local
from ..conftest import _ensure_admin_logged_in

MXSS_PAYLOAD = "<form><math><mtext></form><mglyph><style></math><img src=/np.png onerror=\"window.__flashXss=1;document.title='FLASH_XSS'\">"


PAYLOADS = [
    MXSS_PAYLOAD,
    "<img src=/np.png onerror=\"window.__flashXss=1;document.title='FLASH_XSS'\">",
    "<svg onload=\"window.__flashXss=1;document.title='FLASH_XSS'\"></svg>",
    '<math><annotation-xml encoding="text/html"><img src=/np.png onerror="window.__flashXss=1"></math>',
    "<b>bold</b>",
]


GENERIC_ERROR = "❌ Something went wrong. Please try again."


@pytest.mark.parametrize("payload", PAYLOADS)
def test_error_payload_shows_generic_message(page: Page, base_url: str, payload: str) -> None:
    """An unknown ?error= value never runs and never reaches the banner text."""
    _ensure_admin_logged_in(page, base_url)

    page.goto(f"{base_url}/admin/?error={quote(payload, safe='')}", wait_until="load")
    banner = page.locator("#global-notification")
    banner.wait_for(state="visible")

    # Give a 404 on /np.png time to fire onerror if the payload were live.
    page.wait_for_timeout(500)

    assert page.evaluate("window.__flashXss") is None
    assert page.title() != "FLASH_XSS"
    assert banner.locator("img, svg, math, form, b").count() == 0
    assert banner.locator("span").text_content() == GENERIC_ERROR


@pytest.mark.parametrize("param", ["message", "success"])
def test_info_payload_shows_no_banner(page: Page, base_url: str, param: str) -> None:
    """Unknown info codes and the removed ?success= parameter render nothing."""
    _ensure_admin_logged_in(page, base_url)

    page.goto(f"{base_url}/admin/?{param}={quote(MXSS_PAYLOAD, safe='')}", wait_until="load")
    page.wait_for_timeout(500)

    assert page.evaluate("window.__flashXss") is None
    assert page.locator("#global-notification").is_hidden()


def test_error_banner_is_dismissable_and_focused(page: Page, base_url: str) -> None:
    """A known error code shows its text, takes keyboard focus, and stays until dismissed."""
    _ensure_admin_logged_in(page, base_url)

    page.goto(f"{base_url}/admin/?error=permission_denied#tools", wait_until="load")
    banner = page.locator("#global-notification")
    banner.wait_for(state="visible")

    assert banner.locator("span").text_content() == "❌ You do not have permission to perform this action."
    assert "error=" not in page.url
    close_button = banner.get_by_role("button", name="Dismiss notification")
    assert close_button.evaluate("el => el === document.activeElement")

    page.wait_for_timeout(5500)
    assert banner.is_visible()

    page.keyboard.press("Enter")
    assert banner.is_hidden()


def test_admin_csp_blocks_inline_event_handlers(page: Page, base_url: str) -> None:
    """The admin page CSP forbids inline on* handler attributes."""
    _ensure_admin_logged_in(page, base_url)
    response = page.goto(f"{base_url}/admin/", wait_until="load")

    assert response is not None
    csp = response.headers.get("content-security-policy", "")
    assert "script-src-attr 'none'" in csp


def test_htmx_code_evaluation_is_disabled(page: Page, base_url: str) -> None:
    """Injected htmx markup cannot evaluate code through trigger filters or hx-vals js: values."""
    _ensure_admin_logged_in(page, base_url)
    page.goto(f"{base_url}/admin/", wait_until="load")
    page.wait_for_function("window.htmx !== undefined")

    assert page.evaluate("window.htmx.config.allowEval") is False
    page.evaluate(
        """() => {
            const btn = document.createElement('button');
            btn.setAttribute('hx-get', '/health');
            btn.setAttribute('hx-trigger', 'click[window.__htmxEval=1]');
            btn.setAttribute('hx-vals', 'js:{a: (window.__htmxEval=2)}');
            document.body.appendChild(btn);
            window.htmx.process(btn);
            btn.click();
        }"""
    )
    page.wait_for_timeout(500)
    assert page.evaluate("window.__htmxEval") is None
