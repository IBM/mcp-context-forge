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
from typing import Dict, Generator, Optional

# Third-Party
from playwright.sync_api import APIRequestContext, BrowserContext, expect, Page, Playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import pytest

# First-Party
from mcpgateway.config import Settings
from mcpgateway.utils.create_jwt_token import _create_jwt_token

# Get configuration from environment
BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")
API_TOKEN = os.getenv("MCP_AUTH", "")
DISABLE_JWT_FALLBACK = os.getenv("PLAYWRIGHT_DISABLE_JWT_FALLBACK", "").lower() in ("1", "true", "yes")
PLAYWRIGHT_VIDEO_SIZE = os.getenv("PLAYWRIGHT_VIDEO_SIZE", "1920x1080")
PLAYWRIGHT_VIEWPORT_SIZE = os.getenv("PLAYWRIGHT_VIEWPORT_SIZE", PLAYWRIGHT_VIDEO_SIZE)

# Email login credentials (admin user)
ADMIN_EMAIL = os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("PLATFORM_ADMIN_PASSWORD", "changeme")
ADMIN_NEW_PASSWORD = os.getenv("PLATFORM_ADMIN_NEW_PASSWORD", "Changeme123!")
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


def _parse_video_size(size: str) -> Optional[Dict[str, int]]:
    """Parse WIDTHxHEIGHT size from env string."""
    if not size:
        return None
    match = re.match(r"^\s*(\d+)x(\d+)\s*$", size)
    if not match:
        raise ValueError("PLAYWRIGHT_VIDEO_SIZE must be in the format WIDTHxHEIGHT (e.g., 1280x720).")
    return {"width": int(match.group(1)), "height": int(match.group(2))}


VIDEO_SIZE = _parse_video_size(PLAYWRIGHT_VIDEO_SIZE)
VIEWPORT_SIZE = _parse_video_size(PLAYWRIGHT_VIEWPORT_SIZE)


def _wait_for_admin_transition(page: Page, previous_url: Optional[str] = None) -> None:
    """Wait for admin-related navigation after login actions."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except PlaywrightTimeoutError:
        page.wait_for_timeout(500)
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

    token = API_TOKEN
    if not token and not DISABLE_JWT_FALLBACK:
        # Generate a fallback token for testing if none provided
        try:
            token = _create_jwt_token({"sub": ADMIN_EMAIL})
        except Exception:
            pass  # Use empty if generation fails

    auth_header = _format_auth_header(token)
    if auth_header:
        headers["Authorization"] = auth_header

    request_context = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers=headers,
    )
    yield request_context
    request_context.dispose()


@pytest.fixture(scope="session")
def browser_context_args(
    pytestconfig,
    playwright: Playwright,
    device: Optional[str],
    base_url: Optional[str],
    _pw_artifacts_folder,
) -> Dict:
    """Customize Playwright browser context for artifacts + video quality."""
    context_args: Dict = {}
    if device:
        context_args.update(playwright.devices[device])
    if base_url:
        context_args["base_url"] = base_url

    video_option = pytestconfig.getoption("--video")
    capture_video = video_option in ["on", "retain-on-failure"]
    if capture_video:
        context_args["record_video_dir"] = _pw_artifacts_folder.name
        if VIDEO_SIZE:
            context_args["record_video_size"] = VIDEO_SIZE

    if VIEWPORT_SIZE and not device:
        context_args["viewport"] = VIEWPORT_SIZE

    return context_args


@pytest.fixture
def context(new_context) -> BrowserContext:
    """Create a browser context using pytest-playwright hooks for artifacts."""
    return new_context(ignore_https_errors=True)


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
    # Ensure the Authorization header is set for programmatic page.request calls.
    # Cookie-only auth is rejected for non-browser requests (CSRF protection),
    # so extract the JWT from the cookie and set it as a Bearer header.
    jwt_cookie = next((c for c in page.context.cookies() if c["name"] == "jwt_token"), None)
    if jwt_cookie:
        page.context.set_extra_http_headers({"Authorization": f"Bearer {jwt_cookie['value']}"})
    # Wait for the application shell to load to ensure we aren't looking at a 500 error page
    try:
        page.wait_for_selector('[data-testid="servers-tab"]', state="visible", timeout=60000)
    except Exception:
        # If tab is missing, check if we have an error message on page to report
        content = page.content()
        if "Internal Server Error" in content:
            raise AssertionError("Admin page failed to load: Internal Server Error (500)")
        raise
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


@pytest.fixture
def test_server_data():
    """Provide test data for server creation."""
    # Standard
    import uuid

    unique_id = uuid.uuid4()
    return {
        "name": f"test-server-{unique_id}",
        "icon": "http://localhost:9000/icon.png",
    }


@pytest.fixture
def test_resource_data():
    """Provide test data for resource creation."""
    # Standard
    import uuid

    unique_id = uuid.uuid4()
    return {
        "uri": f"file:///tmp/test-resource-{unique_id}.txt",
        "name": f"Test Resource {unique_id}",
        "mimeType": "text/plain",
        "description": "A test resource created by automation",
    }


@pytest.fixture
def test_prompt_data():
    """Provide test data for prompt creation."""
    # Standard
    import uuid

    unique_id = uuid.uuid4()
    return {
        "name": f"test-prompt-{unique_id}",
        "description": "A test prompt created by automation",
        "arguments": '[{"name": "topic", "description": "Topic to discuss", "required": true}]',
    }


@pytest.fixture(autouse=True)
def setup_test_environment(page: Page):
    """Set viewport and default timeout for consistent UI tests."""
    if VIEWPORT_SIZE:
        page.set_viewport_size(VIEWPORT_SIZE)
    page.set_default_timeout(60000)
    # Optionally, add request logging or interception here
