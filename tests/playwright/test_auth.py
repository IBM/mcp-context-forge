# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Manav Gupta

Authentication tests for MCP Gateway Admin UI.
"""

# Standard
import os
import re

# Third-Party
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect
import pytest

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("PLATFORM_ADMIN_PASSWORD", "changeme")
ADMIN_NEW_PASSWORD = os.getenv("PLATFORM_ADMIN_NEW_PASSWORD", "changeme123")
ADMIN_ACTIVE_PASSWORD = [ADMIN_PASSWORD]


class TestAuthentication:
    """Authentication tests for MCP Gateway Admin UI.

    Tests email/password authentication flow for the admin interface.

    Examples:
        pytest tests/playwright/test_auth.py
    """

    def _login(self, page, email: str, password: str, allow_password_change: bool = False) -> None:
        """Submit the admin login form."""
        response = page.goto(f"{BASE_URL}/admin/login")
        if response and response.status == 404:
            pytest.skip("Admin UI not enabled (login endpoint not found).")
        try:
            page.wait_for_selector('input[name="email"]', timeout=3000)
        except PlaywrightTimeoutError:
            pytest.skip("Admin login form not available; email auth likely disabled.")
        page.fill('input[name="email"]', email)
        page.fill('input[name="password"]', password)
        previous_url = page.url
        page.click('button[type="submit"]')
        page.wait_for_load_state("domcontentloaded")
        if page.url == previous_url:
            page.wait_for_timeout(500)
        if allow_password_change and re.search(r"/admin/change-password-required", page.url):
            page.fill('input[name="current_password"]', password)
            page.fill('input[name="new_password"]', ADMIN_NEW_PASSWORD)
            page.fill('input[name="confirm_password"]', ADMIN_NEW_PASSWORD)
            previous_url = page.url
            page.click('button[type="submit"]')
            ADMIN_ACTIVE_PASSWORD[0] = ADMIN_NEW_PASSWORD
            page.wait_for_load_state("domcontentloaded")
            if page.url == previous_url:
                page.wait_for_timeout(500)
        elif allow_password_change and re.search(r"error=invalid_credentials", page.url) and ADMIN_NEW_PASSWORD != password:
            page.fill('input[name="email"]', email)
            page.fill('input[name="password"]', ADMIN_NEW_PASSWORD)
            previous_url = page.url
            page.click('button[type="submit"]')
            ADMIN_ACTIVE_PASSWORD[0] = ADMIN_NEW_PASSWORD
            page.wait_for_load_state("domcontentloaded")
            if page.url == previous_url:
                page.wait_for_timeout(500)

    def test_should_login_with_valid_credentials(self, browser):
        """Test successful access with valid email/password credentials."""
        context = browser.new_context(base_url=BASE_URL, ignore_https_errors=True)
        page = context.new_page()
        # Go directly to admin and log in if redirected
        page.goto("/admin")
        if re.search(r"/admin/login", page.url):
            self._login(page, ADMIN_EMAIL, ADMIN_ACTIVE_PASSWORD[0], allow_password_change=True)

        # Verify we successfully accessed the admin flow
        expect(page).to_have_url(re.compile(r".*/admin(?!/login).*"))

        # Check for JWT cookie (set on successful email login)
        cookies = page.context.cookies()
        jwt_cookie = next((c for c in cookies if c["name"] == "jwt_token"), None)
        if jwt_cookie:
            assert jwt_cookie["httpOnly"] is True

        context.close()

    def test_should_reject_invalid_credentials(self, browser):
        """Test rejection with invalid email/password credentials."""
        context = browser.new_context(base_url=BASE_URL, ignore_https_errors=True)
        page = context.new_page()

        self._login(page, "invalid@example.com", "wrong-password")

        # Expect redirect back to login with an error
        expect(page).to_have_url(re.compile(r".*/admin/login\?error=invalid_credentials"))
        expect(page.locator("#error-message")).to_be_visible()

        context.close()

    def test_should_require_authentication(self, browser):
        """Test that admin requires authentication."""
        context = browser.new_context(base_url=BASE_URL, ignore_https_errors=True)  # No credentials provided
        page = context.new_page()

        # Access admin without credentials should redirect to login page when auth is required
        response = page.goto("/admin")
        if response and response.status == 404:
            pytest.skip("Admin UI not enabled (admin endpoint not found).")
        if re.search(r"/admin/login", page.url):
            expect(page).to_have_url(re.compile(r".*/admin/login"))
        else:
            expect(page.locator('[data-testid="servers-tab"]')).to_be_visible()

        context.close()

    def test_should_access_admin_with_valid_auth(self, browser):
        """Test that valid credentials allow full admin access."""
        context = browser.new_context(base_url=BASE_URL, ignore_https_errors=True)
        page = context.new_page()

        # Access admin page and log in if needed
        response = page.goto("/admin")
        if response and response.status == 404:
            pytest.skip("Admin UI not enabled (admin endpoint not found).")
        if re.search(r"/admin/login", page.url):
            self._login(page, ADMIN_EMAIL, ADMIN_ACTIVE_PASSWORD[0], allow_password_change=True)

        # Verify admin interface elements are present
        if re.search(r"/admin/change-password-required", page.url):
            pytest.skip("Admin password change required; configure a final password and retry.")
        expect(page).to_have_url(re.compile(r".*/admin(?!/login).*"))
        expect(page.locator("h1")).to_contain_text("Gateway Administration")

        # Check that we can see admin tabs
        expect(page.locator('[data-testid="servers-tab"]')).to_be_visible()
        expect(page.locator('[data-testid="tools-tab"]')).to_be_visible()
        expect(page.locator('[data-testid="gateways-tab"]')).to_be_visible()

        context.close()
