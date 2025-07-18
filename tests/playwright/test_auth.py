# -*- coding: utf-8 -*-
import os
import re
import pytest
from playwright.sync_api import expect

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")
BASIC_AUTH_USER = os.getenv("BASIC_AUTH_USER", "admin")
BASIC_AUTH_PASSWORD = os.getenv("BASIC_AUTH_PASSWORD", "changeme")

class TestAuthentication:
    """Authentication tests for MCP Gateway Admin UI.

    Tests HTTP Basic Auth authentication flow for the admin interface.

    Examples:
        pytest tests/playwright/test_auth.py
    """
    def test_should_login_with_valid_credentials(self, browser):
        """Test successful access with valid HTTP Basic Auth credentials."""
        context = browser.new_context(
            http_credentials={
                "username": BASIC_AUTH_USER,
                "password": BASIC_AUTH_PASSWORD,
            }
        )
        page = context.new_page()
        # Go directly to admin - HTTP Basic Auth handles authentication
        page.goto(f"{BASE_URL}/admin")
        page.screenshot(path="debug_login_page.png")

        # Verify we successfully accessed the admin page
        expect(page).to_have_url(re.compile(r".*admin"))
        expect(page.locator("h1")).to_contain_text("MCP Context Forge")

        # Check for JWT cookie (optional with HTTP Basic Auth)
        cookies = page.context.cookies()
        jwt_cookie = next((c for c in cookies if c["name"] == "jwt_token"), None)
        if jwt_cookie:
            assert jwt_cookie["httpOnly"] is True

        context.close()

    def test_should_reject_invalid_credentials(self, browser):
        """Test rejection with invalid HTTP Basic Auth credentials."""
        context = browser.new_context(
            http_credentials={
                "username": "invalid",
                "password": "wrong",
            }
        )
        page = context.new_page()

        # Try to access admin with invalid credentials
        response = page.goto(f"{BASE_URL}/admin")

        # Should get 401 Unauthorized
        assert response.status == 401
        context.close()

    def test_should_require_authentication(self, browser):
        """Test that admin requires authentication."""
        context = browser.new_context()  # No credentials provided
        page = context.new_page()

        # Try to access admin without credentials
        response = page.goto(f"{BASE_URL}/admin")

        # Should get 401 Unauthorized
        assert response.status == 401
        context.close()

    def test_should_access_admin_with_valid_auth(self, browser):
        """Test that valid credentials allow full admin access."""
        context = browser.new_context(
            http_credentials={
                "username": BASIC_AUTH_USER,
                "password": BASIC_AUTH_PASSWORD,
            }
        )
        page = context.new_page()

        # Access admin page
        page.goto(f"{BASE_URL}/admin")

        # Verify admin interface elements are present
        expect(page).to_have_url(re.compile(r".*admin"))
        expect(page.locator("h1")).to_contain_text("MCP Context Forge")

        # Check that we can see admin tabs
        expect(page.locator('[data-testid="servers-tab"]')).to_be_visible()
        expect(page.locator('[data-testid="tools-tab"]')).to_be_visible()
        expect(page.locator('[data-testid="gateways-tab"]')).to_be_visible()

        context.close()
