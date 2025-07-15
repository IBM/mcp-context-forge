# -*- coding: utf-8 -*-
"""
Playwright test configuration - Simple version without python-dotenv.
This assumes environment variables are loaded by the Makefile.
"""
# Standard
import base64
import os
from typing import Generator

# Third-Party
from playwright.sync_api import APIRequestContext, Page, Playwright
import pytest

# Get configuration from environment
BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:4444")
API_TOKEN = os.getenv("MCP_AUTH_TOKEN", "test-token")

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
