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
from playwright.sync_api import expect, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import pytest

# Local
from .pages.admin_page import AdminPage
from .pages.login_page import LoginPage

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")
ADMIN_EMAIL = os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("PLATFORM_ADMIN_PASSWORD", "changeme")
ADMIN_NEW_PASSWORD = os.getenv("PLATFORM_ADMIN_NEW_PASSWORD", "Changeme123!")
ADMIN_ACTIVE_PASSWORD = [ADMIN_PASSWORD]


class TestAuthentication:
    """Authentication tests for MCP Gateway Admin UI.

    Tests email/password authentication flow for the admin interface.

    Examples:
        pytest tests/playwright/test_auth.py
    """

    def _login(self, page, email: str, password: str, allow_password_change: bool = False) -> bool:
        """Submit the admin login form using LoginPage object."""
        login_page = LoginPage(page, BASE_URL)
        
        response = login_page.navigate()
        if response and response.status == 404:
            pytest.skip("Admin UI not enabled (login endpoint not found).")
        
        if not login_page.is_login_form_available(timeout=3000):
            pytest.skip("Admin login form not available; email auth likely disabled.")
        
        # Perform login with optional password change
        if allow_password_change:
            success = login_page.login(email, password, ADMIN_NEW_PASSWORD)
            if success and login_page.is_on_change_password_page():
                # Password was changed
                ADMIN_ACTIVE_PASSWORD[0] = ADMIN_NEW_PASSWORD
            elif not success and ADMIN_NEW_PASSWORD != password:
                # Try with new password
                success = login_page.login(email, ADMIN_NEW_PASSWORD)
                if success:
                    ADMIN_ACTIVE_PASSWORD[0] = ADMIN_NEW_PASSWORD
            return success
        else:
            login_page.submit_login(email, password)
            return not login_page.has_invalid_credentials_error()

    def test_should_login_with_valid_credentials(self, context):
        """Test successful access with valid email/password credentials."""
        page = context.new_page()
        # Go directly to admin and log in if redirected
        page.goto("/admin")
        if re.search(r"/admin/login", page.url):
            if not self._login(page, ADMIN_EMAIL, ADMIN_ACTIVE_PASSWORD[0], allow_password_change=True):
                pytest.skip("Admin credentials invalid. Set PLATFORM_ADMIN_PASSWORD/PLATFORM_ADMIN_NEW_PASSWORD to match the running gateway.")

        # Verify we successfully accessed the admin flow
        expect(page).to_have_url(re.compile(r".*/admin(?!/login).*"))

        # Check for JWT cookie (set on successful email login)
        cookies = page.context.cookies()
        jwt_cookie = next((c for c in cookies if c["name"] == "jwt_token"), None)
        if jwt_cookie:
            assert jwt_cookie["httpOnly"] is True

    def test_should_reject_invalid_credentials(self, context):
        """Test rejection with invalid email/password credentials."""
        page = context.new_page()

        self._login(page, "invalid@example.com", "wrong-password")

        # Expect redirect back to login with an error
        login_page = LoginPage(page, BASE_URL)
        expect(page).to_have_url(re.compile(r".*/admin/login\?error=invalid_credentials"))
        expect(login_page.error_message).to_be_visible()

    def test_should_require_authentication(self, context):
        """Test that admin requires authentication."""
        page = context.new_page()

        # Access admin without credentials should redirect to login page when auth is required
        response = page.goto("/admin")
        if response and response.status == 404:
            pytest.skip("Admin UI not enabled (admin endpoint not found).")
        if re.search(r"/admin/login", page.url):
            expect(page).to_have_url(re.compile(r".*/admin/login"))
        else:
            admin_ui = AdminPage(page, BASE_URL)
            expect(admin_ui.servers_tab).to_be_visible()

    def test_should_access_admin_with_valid_auth(self, context):
        """Test that valid credentials allow full admin access."""
        page = context.new_page()

        # Access admin page and log in if needed
        response = page.goto("/admin")
        if response and response.status == 404:
            pytest.skip("Admin UI not enabled (admin endpoint not found).")
        if re.search(r"/admin/login", page.url):
            if not self._login(page, ADMIN_EMAIL, ADMIN_ACTIVE_PASSWORD[0], allow_password_change=True):
                pytest.skip("Admin credentials invalid. Set PLATFORM_ADMIN_PASSWORD/PLATFORM_ADMIN_NEW_PASSWORD to match the running gateway.")

        # Verify admin interface elements are present
        if re.search(r"/admin/change-password-required", page.url):
            pytest.skip("Admin password change required; configure a final password and retry.")
        expect(page).to_have_url(re.compile(r".*/admin(?!/login).*"))
        expect(page.locator("h1")).to_contain_text("Gateway Administration")

        # Check that we can see admin tabs
        admin_ui = AdminPage(page, BASE_URL)
        expect(admin_ui.servers_tab).to_be_visible()
        expect(admin_ui.gateways_tab).to_be_visible()
        expect(admin_ui.tools_tab).to_be_visible()

    def test_login_with_correct_credentials_must_succeed(self, context):
        """Test that login with correct credentials MUST succeed - this test will FAIL if it doesn't work.
        
        This is a critical test that ensures the authentication system is working properly.
        Unlike other tests that may skip on failure, this one will fail hard to alert of auth issues.
        """
        page = context.new_page()
        
        env_password = os.getenv("PLATFORM_ADMIN_PASSWORD")

        # Navigate to login page
        login_page = LoginPage(page, BASE_URL)
        response = login_page.navigate()
        
        # Check if admin UI is enabled
        if response and response.status == 404:
            pytest.fail("Admin UI not enabled (login endpoint not found). Cannot verify authentication.")
        
        # Check if login form is available
        if not login_page.is_login_form_available(timeout=3000):
            pytest.fail("Admin login form not available. Email auth may be disabled.")
        
        # Attempt login with correct credentials
        login_page.submit_login(ADMIN_EMAIL, ADMIN_ACTIVE_PASSWORD[0])
        
        # Check for invalid credentials error
        if login_page.has_invalid_credentials_error():
            error_msg = (
                f"Login FAILED with correct credentials!\n"
                f"Email: {ADMIN_EMAIL}\n"
                f"Password source: {'ENV VAR' if env_password else 'DEFAULT'}\n"
                f"\nPossible causes:\n"
                f"1. The password in the environment variable doesn't match the server's expected password\n"
                f"2. The server may be using a different password than what's configured\n"
                f"3. The password may have been changed on the server but not updated in the env var\n"
                f"\nTo fix: Verify the correct password on the server and update PLATFORM_ADMIN_PASSWORD"
            )
            pytest.fail(error_msg)
        
        # Verify successful login by checking URL
        try:
            expect(page).to_have_url(re.compile(r".*/admin(?!/login).*"), timeout=5000)
        except PlaywrightTimeoutError:
            current_url = page.url
            pytest.fail(
                f"Login appeared to succeed but did not redirect to admin page.\n"
                f"Current URL: {current_url}\n"
                f"Expected URL pattern: .*/admin(?!/login).*"
            )
        
        # Verify JWT cookie is set
        cookies = page.context.cookies()
        jwt_cookie = next((c for c in cookies if c["name"] == "jwt_token"), None)
        if not jwt_cookie:
            pytest.fail("Login succeeded but JWT token cookie was not set. Authentication may be incomplete.")
        
        assert jwt_cookie["httpOnly"] is True, "JWT cookie should be httpOnly for security"
