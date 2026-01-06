# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/conftest.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Playwright test configuration - Simple version without python-dotenv.
This assumes environment variables are loaded by the Makefile.
"""

# Standard
import base64
import os
import re
from typing import Generator

# Third-Party
from playwright.sync_api import APIRequestContext, Page, Playwright
import pytest

# First-Party
from mcpgateway.config import Settings

# Get configuration from environment
BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")
API_TOKEN = os.getenv("MCP_AUTH", "test-token")

# Basic Auth credentials - these MUST be set in environment
BASIC_AUTH_USER = os.getenv("BASIC_AUTH_USER", "admin")
BASIC_AUTH_PASSWORD = os.getenv("BASIC_AUTH_PASSWORD", "changeme")

# Ensure UI/Admin are enabled for tests
os.environ["MCPGATEWAY_UI_ENABLED"] = "true"
os.environ["MCPGATEWAY_ADMIN_API_ENABLED"] = "true"


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for the application."""
    return BASE_URL


@pytest.fixture(scope="session")
def api_request_context(
    playwright: Playwright,
) -> Generator[APIRequestContext, None, None]:
    """Create API request context with Basic Auth."""
    # Create basic auth header
    credentials = f"{BASIC_AUTH_USER}:{BASIC_AUTH_PASSWORD}"
    basic_auth = base64.b64encode(credentials.encode()).decode()

    headers = {
        "Accept": "application/json",
        "Authorization": f"Basic {basic_auth}",
    }

    request_context = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers=headers,
    )
    yield request_context
    request_context.dispose()


@pytest.fixture
def page(browser) -> Generator[Page, None, None]:
    """Create page with Basic Auth credentials."""
    context = browser.new_context(
        base_url=BASE_URL,
        http_credentials={
            "username": BASIC_AUTH_USER,
            "password": BASIC_AUTH_PASSWORD,
        },
        ignore_https_errors=True,
    )
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
    # Go directly to admin - HTTP Basic Auth is handled by the page fixture
    page.goto("/admin")
    # Handle login page redirect if auth is required
    if re.search(r"login", page.url):
        page.fill('[name="email"]', settings.basic_auth_user)
        page.fill('[name="password"]', settings.basic_auth_password.get_secret_value())
        page.click('button[type="submit"]')
    # Verify we're on the admin page
    page.wait_for_url(re.compile(r".*admin"))
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
