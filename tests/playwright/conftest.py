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
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext, BrowserContext, expect, Page, Playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import pytest

# First-Party
from mcpgateway.config import Settings
from mcpgateway.utils.create_jwt_token import _create_jwt_token

# Local
from .pages.admin_page import AdminPage
from .pages.agents_page import AgentsPage
from .pages.gateways_page import GatewaysPage
from .pages.login_page import LoginPage
from .pages.mcp_registry_page import MCPRegistryPage
from .pages.metrics_page import MetricsPage
from .pages.prompts_page import PromptsPage
from .pages.resources_page import ResourcesPage
from .pages.servers_page import ServersPage
from .pages.team_page import TeamPage
from .pages.tokens_page import TokensPage
from .pages.tools_page import ToolsPage
from .pages.version_page import VersionPage

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
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except PlaywrightTimeoutError:
        pass  # Page may already be loaded
    if previous_url and page.url == previous_url:
        # URL hasn't changed yet; wait for navigation to complete
        try:
            page.wait_for_url(lambda url: url != previous_url, timeout=5000)
        except PlaywrightTimeoutError:
            pass  # May not navigate (e.g., auth not required)


def _submit_login_and_wait(page: Page, login_page, email: str, password: str) -> Optional[int]:
    """Submit login form and return the POST response status code."""
    try:
        with page.expect_response(lambda resp: "/admin/login" in resp.url and resp.request.method == "POST", timeout=10000) as response_info:
            login_page.submit_login(email, password)
        return response_info.value.status
    except PlaywrightTimeoutError:
        return None


def _set_admin_jwt_cookie(page: Page, email: str) -> None:
    """Seed an admin JWT cookie to bypass UI login when credentials are unknown."""
    try:
        token = _create_jwt_token({"sub": email}, user_data={"email": email, "is_admin": True, "auth_provider": "local"}, teams=None)
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


def _ensure_admin_logged_in(page: Page, base_url: str) -> None:
    """Ensure the page is logged into the admin interface using LoginPage.

    This helper function handles all login scenarios including:
    - Password change requirements
    - Initial login
    - Retry with new password
    - JWT fallback if credentials fail
    """
    settings = Settings()
    admin_email = settings.platform_admin_email or ADMIN_EMAIL

    # Create LoginPage instance
    login_page = LoginPage(page, base_url)

    # Go directly to admin
    page.goto("/admin")

    # Handle password change requirement
    if login_page.is_on_change_password_page():
        current_password = ADMIN_ACTIVE_PASSWORD[0] or settings.platform_admin_password.get_secret_value()
        login_page.submit_password_change(current_password, ADMIN_NEW_PASSWORD)
        ADMIN_ACTIVE_PASSWORD[0] = ADMIN_NEW_PASSWORD
        _wait_for_admin_transition(page)

    # Handle login page redirect if auth is required
    if login_page.is_on_login_page() or login_page.is_login_form_available():
        current_password = ADMIN_ACTIVE_PASSWORD[0] or settings.platform_admin_password.get_secret_value()

        status = _submit_login_and_wait(page, login_page, admin_email, current_password)
        if status is not None and status >= 400:
            raise AssertionError(f"Login failed with status {status}")
        _wait_for_admin_transition(page)

        # Handle password change after login
        if login_page.is_on_change_password_page():
            login_page.submit_password_change(current_password, ADMIN_NEW_PASSWORD)
            ADMIN_ACTIVE_PASSWORD[0] = ADMIN_NEW_PASSWORD
            _wait_for_admin_transition(page)

        # Retry with new password if credentials were invalid
        if login_page.has_invalid_credentials_error() and ADMIN_NEW_PASSWORD != current_password:
            status = _submit_login_and_wait(page, login_page, admin_email, ADMIN_NEW_PASSWORD)
            if status is not None and status >= 400:
                raise AssertionError(f"Login failed with status {status}")
            ADMIN_ACTIVE_PASSWORD[0] = ADMIN_NEW_PASSWORD
            _wait_for_admin_transition(page)

        # If login still failed, fallback to JWT cookie unless disabled
        if login_page.is_on_login_page():
            if DISABLE_JWT_FALLBACK:
                raise AssertionError("Admin login failed; set PLATFORM_ADMIN_PASSWORD or allow JWT fallback.")
            _set_admin_jwt_cookie(page, admin_email)
            page.goto("/admin/")
            _wait_for_admin_transition(page)

    # Verify we're on the admin page
    expect(page).to_have_url(re.compile(r".*/admin(?!/login).*"))

    # Wait for the application shell to load
    try:
        page.wait_for_selector('[data-testid="servers-tab"]', state="visible", timeout=60000)
    except PlaywrightTimeoutError:
        content = page.content()
        if "Internal Server Error" in content:
            raise AssertionError("Admin page failed to load: Internal Server Error (500)")
        raise


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
def admin_page(page: Page, base_url: str) -> AdminPage:
    """Provide a logged-in AdminPage instance for UI tests."""
    _ensure_admin_logged_in(page, base_url)
    return AdminPage(page, base_url)


@pytest.fixture
def team_page(page: Page, base_url: str) -> TeamPage:
    """Provide a logged-in TeamPage instance for team tests."""
    _ensure_admin_logged_in(page, base_url)
    return TeamPage(page)


@pytest.fixture
def tokens_page(page: Page, base_url: str) -> TokensPage:
    """Provide a logged-in TokensPage instance for token tests."""
    _ensure_admin_logged_in(page, base_url)
    return TokensPage(page)


@pytest.fixture
def metrics_page(page: Page, base_url: str) -> MetricsPage:
    """Provide a logged-in MetricsPage instance for metrics tests."""
    _ensure_admin_logged_in(page, base_url)
    return MetricsPage(page)


@pytest.fixture
def tools_page(page: Page, base_url: str) -> ToolsPage:
    """Provide a logged-in ToolsPage instance for tool tests."""
    _ensure_admin_logged_in(page, base_url)
    return ToolsPage(page)


@pytest.fixture
def resources_page(page: Page, base_url: str) -> ResourcesPage:
    """Provide a logged-in ResourcesPage instance for resource tests."""
    _ensure_admin_logged_in(page, base_url)
    return ResourcesPage(page)


@pytest.fixture
def prompts_page(page: Page, base_url: str) -> PromptsPage:
    """Provide a logged-in PromptsPage instance for prompt tests."""
    _ensure_admin_logged_in(page, base_url)
    return PromptsPage(page)


@pytest.fixture
def agents_page(page: Page, base_url: str) -> AgentsPage:
    """Provide a logged-in AgentsPage instance for A2A agent tests."""
    _ensure_admin_logged_in(page, base_url)
    return AgentsPage(page)


@pytest.fixture
def gateways_page(page: Page, base_url: str) -> GatewaysPage:
    """Provide a logged-in GatewaysPage instance for gateway tests."""
    _ensure_admin_logged_in(page, base_url)
    return GatewaysPage(page)


@pytest.fixture
def servers_page(page: Page, base_url: str) -> ServersPage:
    """Provide a logged-in ServersPage instance for virtual server tests."""
    _ensure_admin_logged_in(page, base_url)
    return ServersPage(page)


@pytest.fixture
def version_page(page: Page, base_url: str) -> VersionPage:
    """Provide a logged-in VersionPage instance for version info tests."""
    _ensure_admin_logged_in(page, base_url)
    return VersionPage(page)


@pytest.fixture
def mcp_registry_page(page: Page, base_url: str) -> MCPRegistryPage:
    """Provide a logged-in MCPRegistryPage instance for MCP Registry tests."""
    _ensure_admin_logged_in(page, base_url)
    return MCPRegistryPage(page)


@pytest.fixture
def test_tool_data():
    """Provide test data for tool creation."""
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
    unique_id = uuid.uuid4()
    return {
        "name": f"test-server-{unique_id}",
        "icon": "http://localhost:9000/icon.png",
    }


@pytest.fixture
def test_resource_data():
    """Provide test data for resource creation."""
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
    unique_id = uuid.uuid4()
    return {
        "name": f"test-prompt-{unique_id}",
        "description": "A test prompt created by automation",
        "arguments": '[{"name": "topic", "description": "Topic to discuss", "required": true}]',
    }


@pytest.fixture
def test_agent_data():
    """Provide test data for A2A agent creation."""
    unique_id = uuid.uuid4()
    return {
        "name": f"test-agent-{unique_id}",
        "endpoint_url": "https://api.example.com/agent",
        "agent_type": "generic",
        "description": "A test A2A agent created by automation",
        "tags": "test,automation,ai",
        "visibility": "public",
    }


# Pool of valid MCP server URLs for testing
# These are real, publicly available MCP servers that can be used for testing
VALID_MCP_SERVER_URLS = [
    "https://docs.mcp.cloudflare.com/sse",
    "https://www.javadocs.dev/mcp",
    "https://mcp.openzeppelin.com/contracts/cairo/mcp",
    "https://mcp.openzeppelin.com/contracts/stylus/mcp",
    "https://mcp.openzeppelin.com/contracts/stellar/mcp",
    "https://mcp.openzeppelin.com/contracts/solidity/mcp",
]


@pytest.fixture
def test_gateway_data():
    """Provide test data for gateway creation."""
    unique_id = uuid.uuid4()
    # Use specific URL for simple gateway test
    url = VALID_MCP_SERVER_URLS[0]

    return {
        "name": f"test-gateway-{unique_id}",
        "url": url,
        "description": "A test MCP Server gateway created by automation",
        "tags": "test,automation,mcp",
        "transport": "SSE",
        "visibility": "public",
    }


@pytest.fixture
def test_gateway_with_basic_auth_data():
    """Provide test data for gateway with basic authentication."""
    unique_id = uuid.uuid4()
    # Use specific URL for basic auth test (index 1 after removing Astro)
    url = VALID_MCP_SERVER_URLS[1]

    return {
        "name": f"test-gateway-basic-{unique_id}",
        "url": url,
        "description": "Test gateway with basic auth",
        "tags": "test,auth,basic",
        "transport": "SSE",
        "visibility": "public",
        "auth_type": "basic",
        "auth_username": "testuser",
        "auth_password": "testpass123",
    }


@pytest.fixture
def test_gateway_with_bearer_auth_data():
    """Provide test data for gateway with bearer token authentication."""
    unique_id = uuid.uuid4()
    # Use specific URL for bearer auth test
    url = VALID_MCP_SERVER_URLS[2]

    return {
        "name": f"test-gateway-bearer-{unique_id}",
        "url": url,
        "description": "Test gateway with bearer token auth",
        "tags": "test,auth,bearer",
        "transport": "SSE",
        "visibility": "private",
        "auth_type": "bearer",
        "auth_token": "test-bearer-token-12345",
    }


@pytest.fixture
def test_gateway_with_oauth_data():
    """Provide test data for gateway with OAuth 2.0 authentication."""
    unique_id = uuid.uuid4()
    # Use specific URL for OAuth test
    url = VALID_MCP_SERVER_URLS[3]

    return {
        "name": f"test-gateway-oauth-{unique_id}",
        "url": url,
        "description": "Test gateway with OAuth 2.0",
        "tags": "test,auth,oauth",
        "transport": "SSE",
        "visibility": "team",
        "auth_type": "oauth",
        "oauth_grant_type": "client_credentials",
        "oauth_issuer": "http://localhost:3003",
        "oauth_client_id": "test-client-id",
        "oauth_client_secret": "test-client-secret",
        "oauth_scopes": "openid profile email",
    }


@pytest.fixture(autouse=True)
def setup_test_environment(page: Page):
    """Set viewport and default timeout for consistent UI tests."""
    if VIEWPORT_SIZE:
        page.set_viewport_size(VIEWPORT_SIZE)
    page.set_default_timeout(60000)
    # Optionally, add request logging or interception here
