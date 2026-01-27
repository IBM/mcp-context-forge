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
from playwright.sync_api import APIRequestContext, Page, Playwright
import pytest

# First-Party
from mcpgateway.config import Settings

# Get configuration from environment
BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")
API_TOKEN = os.getenv("MCP_AUTH", "")

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
    if re.search(r"login", page.url):
        page.wait_for_selector('input[name="email"]')
        current_password = ADMIN_ACTIVE_PASSWORD[0] or settings.platform_admin_password.get_secret_value()
        page.fill('input[name="email"]', admin_email)
        page.fill('input[name="password"]', current_password)
        previous_url = page.url
        page.click('button[type="submit"]')
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
            ADMIN_ACTIVE_PASSWORD[0] = ADMIN_NEW_PASSWORD
            _wait_for_admin_transition(page, previous_url)
    # Verify we're on the admin page
    page.wait_for_url(re.compile(r".*/admin(?!/login).*"))
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
