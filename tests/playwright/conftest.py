# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/conftest.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Playwright test configuration - Simple version without python-dotenv.
This assumes environment variables are loaded by the Makefile.
"""

# Standard
import os
import re
from typing import Generator, Optional

# Third-Party
from playwright.sync_api import APIRequestContext, Page, Playwright, expect
import pytest

# First-Party
from mcpgateway.config import Settings
from mcpgateway.utils.create_jwt_token import _create_jwt_token

# Get configuration from environment
BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")
API_TOKEN = os.getenv("MCP_AUTH", "")
DISABLE_JWT_FALLBACK = os.getenv("PLAYWRIGHT_DISABLE_JWT_FALLBACK", "").lower() in ("1", "true", "yes")

# Email login credentials (admin user)
ADMIN_EMAIL = os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("PLATFORM_ADMIN_PASSWORD", "changeme")
ADMIN_NEW_PASSWORD = os.getenv("PLATFORM_ADMIN_NEW_PASSWORD", "changeme123")
ADMIN_ACTIVE_PASSWORD = [ADMIN_PASSWORD]

# Ensure UI/Admin are enabled for tests
os.environ["MCPGATEWAY_UI_ENABLED"] = "true"
os.environ["MCPGATEWAY_ADMIN_API_ENABLED"] = "true"


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for the application."""
    return BASE_URL


def _format_auth_header(token: str) -> Optional[str]:
    """Normalize auth header value for API requests."""
    if not token:
        return None
    if token.lower().startswith(("bearer ", "basic ")):
        return token
    return f"Bearer {token}"


def _wait_for_admin_transition(page: Page, previous_url: Optional[str] = None) -> None:
    """Wait for admin-related navigation after login actions."""
    page.wait_for_load_state("domcontentloaded")
    if previous_url and page.url == previous_url:
        page.wait_for_timeout(500)


def _wait_for_login_response(page: Page) -> Optional[int]:
    """Wait for the login POST response and return its status code."""
    try:
        response = page.wait_for_response(lambda resp: "/admin/login" in resp.url and resp.request.method == "POST", timeout=10000)
    except Exception:
        return None
    return response.status


def _set_admin_jwt_cookie(page: Page, email: str) -> None:
    """Seed an admin JWT cookie to bypass UI login when credentials are unknown."""
    try:
        token = _create_jwt_token({"sub": email})
    except Exception as exc:  # pragma: no cover - should only fail on misconfig
        raise AssertionError(f"Failed to create admin JWT token: {exc}") from exc

    cookie_url = f"{BASE_URL.rstrip('/')}/"
    page.context.set_extra_http_headers({"Authorization": f"Bearer {token}"})
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


@pytest.fixture(scope="session")
def api_request_context(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Create API request context with optional bearer token."""
    headers = {"Accept": "application/json"}
    auth_header = _format_auth_header(API_TOKEN)
    if auth_header:
        headers["Authorization"] = auth_header

    request_context = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers=headers,
    )
    yield request_context
    request_context.dispose()


@pytest.fixture
def page(browser) -> Generator[Page, None, None]:
    """Create page for UI tests."""
    context = browser.new_context(base_url=BASE_URL, ignore_https_errors=True)
    page = context.new_page()
    yield page
    context.close()


# Fixture if you need the default page fixture name
@pytest.fixture
def authenticated_page(page: Page) -> Page:
    """Alias for page fixture."""
    return page


@pytest.fixture
def admin_page(page: Page):
    """Provide a logged-in admin page for UI tests."""
    settings = Settings()
    admin_email = settings.platform_admin_email or ADMIN_EMAIL
    # Go directly to admin - session login handled here if needed
    page.goto("/admin")
    login_form_visible = page.locator('input[name="email"]').count() > 0
    if re.search(r"/admin/change-password-required", page.url):
        current_password = ADMIN_ACTIVE_PASSWORD[0] or settings.platform_admin_password.get_secret_value()
        page.fill('input[name="current_password"]', current_password)
        page.fill('input[name="new_password"]', ADMIN_NEW_PASSWORD)
        page.fill('input[name="confirm_password"]', ADMIN_NEW_PASSWORD)
        previous_url = page.url
        page.click('button[type="submit"]')
        ADMIN_ACTIVE_PASSWORD[0] = ADMIN_NEW_PASSWORD
        _wait_for_admin_transition(page, previous_url)
    # Handle login page redirect if auth is required
    if re.search(r"login", page.url) or login_form_visible:
        page.wait_for_selector('input[name="email"]')
        current_password = ADMIN_ACTIVE_PASSWORD[0] or settings.platform_admin_password.get_secret_value()
        page.fill('input[name="email"]', admin_email)
        page.fill('input[name="password"]', current_password)
        previous_url = page.url
        page.click('button[type="submit"]')
        status = _wait_for_login_response(page)
        if status is not None and status >= 400:
            raise AssertionError(f"Login failed with status {status}")
        _wait_for_admin_transition(page, previous_url)
        if re.search(r"/admin/change-password-required", page.url):
            page.fill('input[name="current_password"]', current_password)
            page.fill('input[name="new_password"]', ADMIN_NEW_PASSWORD)
            page.fill('input[name="confirm_password"]', ADMIN_NEW_PASSWORD)
            previous_url = page.url
            page.click('button[type="submit"]')
            ADMIN_ACTIVE_PASSWORD[0] = ADMIN_NEW_PASSWORD
            _wait_for_admin_transition(page, previous_url)
        if re.search(r"error=invalid_credentials", page.url) and ADMIN_NEW_PASSWORD != current_password:
            page.fill('input[name="email"]', admin_email)
            page.fill('input[name="password"]', ADMIN_NEW_PASSWORD)
            previous_url = page.url
            page.click('button[type="submit"]')
            status = _wait_for_login_response(page)
            if status is not None and status >= 400:
                raise AssertionError(f"Login failed with status {status}")
            ADMIN_ACTIVE_PASSWORD[0] = ADMIN_NEW_PASSWORD
            _wait_for_admin_transition(page, previous_url)
    # If login still failed, fallback to JWT cookie unless disabled
        if re.search(r"/admin/login", page.url):
            if DISABLE_JWT_FALLBACK:
                raise AssertionError("Admin login failed; set PLATFORM_ADMIN_PASSWORD or allow JWT fallback.")
            _set_admin_jwt_cookie(page, admin_email)
            page.goto("/admin/")
            _wait_for_admin_transition(page)
    # Verify we're on the admin page
    expect(page).to_have_url(re.compile(r".*/admin(?!/login).*"))
    return page


@pytest.fixture
def test_tool_data():
    """Provide test data for tool creation."""
    # Standard
    import uuid

    unique_id = uuid.uuid4()
    return {
        "name": f"test-api-tool-{unique_id}",
        "description": "Test API tool for automation",
        "url": "https://api.example.com/test",
        "integrationType": "REST",
        "requestType": "GET",
        "headers": '{"Authorization": "Bearer test-token"}',
        "input_schema": '{"type": "object", "properties": {"query": {"type": "string"}}}',
    }


@pytest.fixture(autouse=True)
def setup_test_environment(page: Page):
    """Set viewport and default timeout for consistent UI tests."""
    page.set_viewport_size({"width": 1280, "height": 720})
    page.set_default_timeout(30000)
    # Optionally, add request logging or interception here
