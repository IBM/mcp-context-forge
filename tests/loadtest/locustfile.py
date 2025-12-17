# -*- coding: utf-8 -*-
"""Locust load testing scenarios for MCP Gateway.

This module provides comprehensive load testing for MCP Gateway using Locust.
It includes multiple user types simulating different usage patterns.

Usage:
    # Web UI mode (interactive)
    make load-test-ui

    # Headless mode (CI/scripts)
    make load-test

    # Direct invocation
    cd tests/loadtest && locust --host=http://localhost:8000

Environment Variables (also reads from .env file):
    LOADTEST_HOST: Target host URL (default: http://localhost:8000)
    LOADTEST_USERS: Number of concurrent users (default: 50)
    LOADTEST_SPAWN_RATE: Users spawned per second (default: 10)
    LOADTEST_RUN_TIME: Test duration, e.g., "60s", "5m" (default: 60s)
    MCPGATEWAY_BEARER_TOKEN: JWT token for authenticated requests
    BASIC_AUTH_USER: Basic auth username (default: admin)
    BASIC_AUTH_PASSWORD: Basic auth password (default: changeme)
    JWT_SECRET_KEY: Secret key for JWT signing
    JWT_ALGORITHM: JWT algorithm (default: HS256)
    JWT_AUDIENCE: JWT audience claim
    JWT_ISSUER: JWT issuer claim

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import logging
import os
from pathlib import Path
import random
import time
import uuid
from typing import Any

from locust import HttpUser, between, events, tag, task
from locust.runners import MasterRunner, WorkerRunner

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# Configuration - Load from .env file and environment variables
# =============================================================================


def _load_env_file() -> dict[str, str]:
    """Load environment variables from .env file.

    Searches for .env file in current directory and parent directories.
    Returns a dict of key-value pairs from the .env file.
    """
    env_vars: dict[str, str] = {}

    # Search for .env file
    search_paths = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path.cwd().parent.parent / ".env",
        Path(__file__).parent.parent.parent / ".env",  # Project root
    ]

    env_file = None
    for path in search_paths:
        if path.exists():
            env_file = path
            break

    if env_file is None:
        logger.info("No .env file found, using environment variables only")
        return env_vars

    logger.info(f"Loading configuration from {env_file}")

    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue
                # Handle key=value pairs
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    # Remove quotes if present
                    if value and value[0] in ('"', "'") and value[-1] == value[0]:
                        value = value[1:-1]
                    env_vars[key] = value
    except Exception as e:
        logger.warning(f"Error reading .env file: {e}")

    return env_vars


def _get_config(key: str, default: str = "") -> str:
    """Get configuration value from environment or .env file.

    Priority: Environment variable > .env file > default
    """
    # First check environment variable
    env_value = os.environ.get(key)
    if env_value is not None:
        return env_value

    # Then check .env file
    if key in _ENV_FILE_VARS:
        return _ENV_FILE_VARS[key]

    return default


# Load .env file once at module import
_ENV_FILE_VARS = _load_env_file()

# Authentication settings (from env or .env file)
BEARER_TOKEN = _get_config("MCPGATEWAY_BEARER_TOKEN", "")
BASIC_AUTH_USER = _get_config("BASIC_AUTH_USER", "admin")
BASIC_AUTH_PASSWORD = _get_config("BASIC_AUTH_PASSWORD", "changeme")

# JWT settings for auto-generation (if MCPGATEWAY_BEARER_TOKEN not set)
JWT_SECRET_KEY = _get_config("JWT_SECRET_KEY", "my-test-key")
JWT_ALGORITHM = _get_config("JWT_ALGORITHM", "HS256")
JWT_AUDIENCE = _get_config("JWT_AUDIENCE", "mcpgateway-api")
JWT_ISSUER = _get_config("JWT_ISSUER", "mcpgateway")
# Default to platform admin email for guaranteed authentication
# This matches the PLATFORM_ADMIN_EMAIL default in .env.example
JWT_USERNAME = _get_config("JWT_USERNAME", _get_config("PLATFORM_ADMIN_EMAIL", "admin@example.com"))

# Log loaded configuration (masking sensitive values)
logger.info("Configuration loaded:")
logger.info(f"  BASIC_AUTH_USER: {BASIC_AUTH_USER}")
logger.info(f"  JWT_ALGORITHM: {JWT_ALGORITHM}")
logger.info(f"  JWT_AUDIENCE: {JWT_AUDIENCE}")
logger.info(f"  JWT_ISSUER: {JWT_ISSUER}")
logger.info(f"  JWT_SECRET_KEY: {'*' * len(JWT_SECRET_KEY) if JWT_SECRET_KEY else '(not set)'}")

# Test data pools (populated during test setup)
TOOL_IDS: list[str] = []
SERVER_IDS: list[str] = []
GATEWAY_IDS: list[str] = []
RESOURCE_IDS: list[str] = []
PROMPT_IDS: list[str] = []


# =============================================================================
# Event Handlers
# =============================================================================


@events.init.add_listener
def on_locust_init(environment, **_kwargs):  # pylint: disable=unused-argument
    """Initialize test environment."""
    if isinstance(environment.runner, MasterRunner):
        logger.info("Running as master node")
    elif isinstance(environment.runner, WorkerRunner):
        logger.info("Running as worker node")
    else:
        logger.info("Running in standalone mode")


@events.test_start.add_listener
def on_test_start(environment, **_kwargs):  # pylint: disable=unused-argument
    """Fetch existing entity IDs for use in tests."""
    logger.info("Test starting - fetching entity IDs...")

    host = environment.host or "http://localhost:8000"
    headers = _get_auth_headers()

    try:
        import httpx  # pylint: disable=import-outside-toplevel

        with httpx.Client(base_url=host, timeout=30.0) as client:
            # Fetch tools
            resp = client.get("/tools", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else data.get("items", [])
                TOOL_IDS.extend([t.get("id") or t.get("name") for t in items[:50]])
                logger.info(f"Loaded {len(TOOL_IDS)} tool IDs")

            # Fetch servers
            resp = client.get("/servers", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else data.get("items", [])
                SERVER_IDS.extend([s.get("id") or s.get("name") for s in items[:50]])
                logger.info(f"Loaded {len(SERVER_IDS)} server IDs")

            # Fetch gateways
            resp = client.get("/gateways", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else data.get("items", [])
                GATEWAY_IDS.extend([g.get("id") or g.get("name") for g in items[:50]])
                logger.info(f"Loaded {len(GATEWAY_IDS)} gateway IDs")

            # Fetch resources
            resp = client.get("/resources", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else data.get("items", [])
                RESOURCE_IDS.extend([r.get("id") or r.get("uri") for r in items[:50]])
                logger.info(f"Loaded {len(RESOURCE_IDS)} resource IDs")

            # Fetch prompts
            resp = client.get("/prompts", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else data.get("items", [])
                PROMPT_IDS.extend([p.get("id") or p.get("name") for p in items[:50]])
                logger.info(f"Loaded {len(PROMPT_IDS)} prompt IDs")

    except Exception as e:
        logger.warning(f"Failed to fetch entity IDs: {e}")
        logger.info("Tests will continue without pre-fetched IDs")


@events.test_stop.add_listener
def on_test_stop(_environment, **_kwargs):  # pylint: disable=unused-argument
    """Clean up after test."""
    logger.info("Test stopped")
    TOOL_IDS.clear()
    SERVER_IDS.clear()
    GATEWAY_IDS.clear()
    RESOURCE_IDS.clear()
    PROMPT_IDS.clear()


# =============================================================================
# Helper Functions
# =============================================================================


def _generate_jwt_token() -> str:
    """Generate a JWT token for API authentication.

    Uses PyJWT to create a token with the configured secret and algorithm.
    Reads JWT settings from .env file or environment variables.
    """
    try:
        import jwt  # pylint: disable=import-outside-toplevel
        from datetime import datetime, timezone, timedelta  # pylint: disable=import-outside-toplevel

        payload = {
            "sub": JWT_USERNAME,
            "exp": datetime.now(timezone.utc) + timedelta(hours=24),
            "iat": datetime.now(timezone.utc),
            "aud": JWT_AUDIENCE,
            "iss": JWT_ISSUER,
        }
        token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        logger.info(f"Generated JWT token for user: {JWT_USERNAME} (aud={JWT_AUDIENCE}, iss={JWT_ISSUER})")
        return token
    except ImportError:
        logger.warning("PyJWT not installed, falling back to basic auth. Install with: pip install pyjwt")
        return ""
    except Exception as e:
        logger.warning(f"Failed to generate JWT token: {e}, falling back to basic auth")
        return ""


# Cache the generated token
_CACHED_TOKEN: str | None = None


def _get_auth_headers() -> dict[str, str]:
    """Get authentication headers.

    Priority:
    1. MCPGATEWAY_BEARER_TOKEN env var (if set)
    2. Auto-generated JWT token (if PyJWT available)
    3. Basic auth fallback (for admin UI only)
    """
    global _CACHED_TOKEN  # pylint: disable=global-statement
    headers = {"Accept": "application/json"}

    if BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {BEARER_TOKEN}"
    else:
        # Try to generate/use JWT token
        if _CACHED_TOKEN is None:
            _CACHED_TOKEN = _generate_jwt_token()

        if _CACHED_TOKEN:
            headers["Authorization"] = f"Bearer {_CACHED_TOKEN}"
        else:
            # Fallback to basic auth (works for admin UI but not REST API)
            import base64  # pylint: disable=import-outside-toplevel

            credentials = base64.b64encode(f"{BASIC_AUTH_USER}:{BASIC_AUTH_PASSWORD}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"
            logger.warning("Using basic auth - REST API endpoints may fail. Set MCPGATEWAY_BEARER_TOKEN or install PyJWT.")

    return headers


def _json_rpc_request(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a JSON-RPC 2.0 request."""
    return {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params or {},
    }


# =============================================================================
# User Classes
# =============================================================================


class BaseUser(HttpUser):
    """Base user class with common configuration."""

    abstract = True
    wait_time = between(0.5, 2.0)

    def __init__(self, *args, **kwargs):
        """Initialize base user with auth headers."""
        super().__init__(*args, **kwargs)
        self.auth_headers: dict[str, str] = {}
        self.admin_headers: dict[str, str] = {}

    def on_start(self):
        """Set up authentication for the user."""
        self.auth_headers = _get_auth_headers()
        self.admin_headers = {
            **self.auth_headers,
            "Accept": "text/html",
        }


class HealthCheckUser(BaseUser):
    """User that only performs health checks.

    Simulates monitoring systems and health probes.
    Weight: Low (monitoring traffic)
    """

    weight = 1
    wait_time = between(1.0, 3.0)

    @task(10)
    @tag("health", "critical")
    def health_check(self):
        """Check the health endpoint (no auth required)."""
        self.client.get("/health", name="/health")

    @task(5)
    @tag("health")
    def readiness_check(self):
        """Check readiness endpoint (no auth required)."""
        self.client.get("/ready", name="/ready")

    @task(2)
    @tag("health")
    def metrics_endpoint(self):
        """Check Prometheus metrics endpoint."""
        self.client.get("/metrics", headers=self.auth_headers, name="/metrics")

    @task(1)
    @tag("health")
    def openapi_schema(self):
        """Fetch OpenAPI schema."""
        self.client.get("/openapi.json", headers=self.auth_headers, name="/openapi.json")


class ReadOnlyAPIUser(BaseUser):
    """User that performs read-only API operations.

    Simulates API consumers reading data without modifications.
    Weight: High (most common usage pattern)
    """

    weight = 5
    wait_time = between(0.3, 1.5)

    @task(10)
    @tag("api", "tools")
    def list_tools(self):
        """List all tools."""
        self.client.get("/tools", headers=self.auth_headers, name="/tools")

    @task(8)
    @tag("api", "servers")
    def list_servers(self):
        """List all servers."""
        self.client.get("/servers", headers=self.auth_headers, name="/servers")

    @task(6)
    @tag("api", "gateways")
    def list_gateways(self):
        """List all gateways."""
        self.client.get("/gateways", headers=self.auth_headers, name="/gateways")

    @task(5)
    @tag("api", "resources")
    def list_resources(self):
        """List all resources."""
        self.client.get("/resources", headers=self.auth_headers, name="/resources")

    @task(5)
    @tag("api", "prompts")
    def list_prompts(self):
        """List all prompts."""
        self.client.get("/prompts", headers=self.auth_headers, name="/prompts")

    @task(4)
    @tag("api", "a2a")
    def list_a2a_agents(self):
        """List A2A agents."""
        self.client.get("/a2a", headers=self.auth_headers, name="/a2a")

    @task(3)
    @tag("api", "tags")
    def list_tags(self):
        """List all tags."""
        self.client.get("/tags", headers=self.auth_headers, name="/tags")

    @task(2)
    @tag("api", "metrics")
    def get_metrics(self):
        """Get application metrics."""
        self.client.get("/metrics", headers=self.auth_headers, name="/metrics [api]")

    @task(3)
    @tag("api", "tools")
    def get_single_tool(self):
        """Get a specific tool by ID."""
        if TOOL_IDS:
            tool_id = random.choice(TOOL_IDS)
            self.client.get(f"/tools/{tool_id}", headers=self.auth_headers, name="/tools/[id]")

    @task(3)
    @tag("api", "servers")
    def get_single_server(self):
        """Get a specific server by ID."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            self.client.get(f"/servers/{server_id}", headers=self.auth_headers, name="/servers/[id]")

    @task(2)
    @tag("api", "gateways")
    def get_single_gateway(self):
        """Get a specific gateway by ID."""
        if GATEWAY_IDS:
            gateway_id = random.choice(GATEWAY_IDS)
            self.client.get(f"/gateways/{gateway_id}", headers=self.auth_headers, name="/gateways/[id]")

    @task(2)
    @tag("api", "roots")
    def list_roots(self):
        """List roots."""
        self.client.get("/roots", headers=self.auth_headers, name="/roots")

    @task(2)
    @tag("api", "resources")
    def get_single_resource(self):
        """Get a specific resource by ID."""
        if RESOURCE_IDS:
            resource_id = random.choice(RESOURCE_IDS)
            self.client.get(f"/resources/{resource_id}", headers=self.auth_headers, name="/resources/[id]")

    @task(2)
    @tag("api", "prompts")
    def get_single_prompt(self):
        """Get a specific prompt by ID."""
        if PROMPT_IDS:
            prompt_id = random.choice(PROMPT_IDS)
            self.client.get(f"/prompts/{prompt_id}", headers=self.auth_headers, name="/prompts/[id]")

    @task(2)
    @tag("api", "servers")
    def get_server_tools(self):
        """Get tools for a specific server."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            self.client.get(f"/servers/{server_id}/tools", headers=self.auth_headers, name="/servers/[id]/tools")

    @task(2)
    @tag("api", "servers")
    def get_server_resources(self):
        """Get resources for a specific server."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            self.client.get(
                f"/servers/{server_id}/resources", headers=self.auth_headers, name="/servers/[id]/resources"
            )

    @task(1)
    @tag("api", "discovery")
    def well_known_robots(self):
        """Check robots.txt (always available)."""
        self.client.get("/.well-known/robots.txt", headers=self.auth_headers, name="/.well-known/robots.txt")

    @task(1)
    @tag("api", "discovery")
    def well_known_security(self):
        """Check security.txt."""
        with self.client.get(
            "/.well-known/security.txt",
            headers=self.auth_headers,
            name="/.well-known/security.txt",
            catch_response=True,
        ) as response:
            # 404 is acceptable if not configured
            if response.status_code in (200, 404):
                response.success()


class AdminUIUser(BaseUser):
    """User that browses the Admin UI.

    Simulates administrators using the web interface.
    Weight: Medium (admin traffic)
    """

    weight = 3
    wait_time = between(1.0, 3.0)

    @task(10)
    @tag("admin", "dashboard")
    def admin_dashboard(self):
        """Load admin dashboard."""
        self.client.get("/admin/", headers=self.admin_headers, name="/admin/")

    @task(8)
    @tag("admin", "tools")
    def admin_tools_page(self):
        """Load tools management page."""
        self.client.get("/admin/tools", headers=self.admin_headers, name="/admin/tools")

    @task(7)
    @tag("admin", "servers")
    def admin_servers_page(self):
        """Load servers management page."""
        self.client.get("/admin/servers", headers=self.admin_headers, name="/admin/servers")

    @task(6)
    @tag("admin", "gateways")
    def admin_gateways_page(self):
        """Load gateways management page."""
        self.client.get("/admin/gateways", headers=self.admin_headers, name="/admin/gateways")

    @task(5)
    @tag("admin", "resources")
    def admin_resources_page(self):
        """Load resources management page."""
        self.client.get("/admin/resources", headers=self.admin_headers, name="/admin/resources")

    @task(5)
    @tag("admin", "prompts")
    def admin_prompts_page(self):
        """Load prompts management page."""
        self.client.get("/admin/prompts", headers=self.admin_headers, name="/admin/prompts")

    @task(4)
    @tag("admin", "a2a")
    def admin_a2a_list(self):
        """Load A2A agents list."""
        self.client.get("/admin/a2a", headers=self.auth_headers, name="/admin/a2a")

    @task(3)
    @tag("admin", "performance")
    def admin_performance(self):
        """Load performance stats (if enabled)."""
        with self.client.get(
            "/admin/performance/stats",
            headers={**self.admin_headers, "HX-Request": "true"},
            name="/admin/performance/stats",
            catch_response=True,
        ) as response:
            # 404 is acceptable if performance tracking is disabled
            if response.status_code in (200, 404):
                response.success()

    @task(2)
    @tag("admin", "logs")
    def admin_logs(self):
        """Load logs page."""
        self.client.get("/admin/logs", headers=self.auth_headers, name="/admin/logs")

    @task(2)
    @tag("admin", "config")
    def admin_config_settings(self):
        """Load config settings."""
        self.client.get("/admin/config/settings", headers=self.auth_headers, name="/admin/config/settings")

    @task(2)
    @tag("admin", "metrics")
    def admin_metrics(self):
        """Load metrics page."""
        self.client.get("/admin/metrics", headers=self.admin_headers, name="/admin/metrics")

    @task(2)
    @tag("admin", "teams")
    def admin_teams(self):
        """Load teams management page."""
        self.client.get("/admin/teams", headers=self.admin_headers, name="/admin/teams")

    @task(2)
    @tag("admin", "users")
    def admin_users(self):
        """Load users management page."""
        self.client.get("/admin/users", headers=self.admin_headers, name="/admin/users")

    @task(1)
    @tag("admin", "export")
    def admin_export_config(self):
        """Load export configuration page."""
        self.client.get("/admin/export/configuration", headers=self.admin_headers, name="/admin/export/configuration")

    @task(1)
    @tag("admin", "htmx", "tools")
    def admin_tools_partial(self):
        """Fetch tools partial via HTMX."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        self.client.get("/admin/tools/partial", headers=headers, name="/admin/tools/partial")

    @task(1)
    @tag("admin", "htmx", "resources")
    def admin_resources_partial(self):
        """Fetch resources partial via HTMX."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        self.client.get("/admin/resources/partial", headers=headers, name="/admin/resources/partial")

    @task(1)
    @tag("admin", "htmx", "prompts")
    def admin_prompts_partial(self):
        """Fetch prompts partial via HTMX."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        self.client.get("/admin/prompts/partial", headers=headers, name="/admin/prompts/partial")

    @task(1)
    @tag("admin", "htmx", "metrics")
    def admin_metrics_partial(self):
        """Fetch metrics partial via HTMX."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        self.client.get("/admin/metrics/partial", headers=headers, name="/admin/metrics/partial")

    @task(1)
    @tag("admin", "htmx")
    def admin_htmx_refresh(self):
        """Simulate HTMX partial refresh."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        endpoint = random.choice(["/admin/tools", "/admin/servers", "/admin/gateways"])
        self.client.get(endpoint, headers=headers, name=f"{endpoint} [htmx]")


class MCPJsonRpcUser(BaseUser):
    """User that makes MCP JSON-RPC requests.

    Simulates MCP clients (Claude Desktop, etc.) making protocol requests.
    Weight: High (core MCP traffic)
    """

    weight = 4
    wait_time = between(0.2, 1.0)

    @task(10)
    @tag("mcp", "rpc", "tools")
    def rpc_list_tools(self):
        """JSON-RPC: List tools."""
        payload = _json_rpc_request("tools/list")
        self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/rpc tools/list",
        )

    @task(8)
    @tag("mcp", "rpc", "resources")
    def rpc_list_resources(self):
        """JSON-RPC: List resources."""
        payload = _json_rpc_request("resources/list")
        self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/rpc resources/list",
        )

    @task(8)
    @tag("mcp", "rpc", "prompts")
    def rpc_list_prompts(self):
        """JSON-RPC: List prompts."""
        payload = _json_rpc_request("prompts/list")
        self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/rpc prompts/list",
        )

    @task(5)
    @tag("mcp", "rpc", "tools")
    def rpc_call_tool(self):
        """JSON-RPC: Call a tool."""
        if TOOL_IDS:
            tool_name = random.choice(TOOL_IDS)
            payload = _json_rpc_request("tools/call", {"name": tool_name, "arguments": {}})
            self.client.post(
                "/rpc",
                json=payload,
                headers={**self.auth_headers, "Content-Type": "application/json"},
                name="/rpc tools/call",
            )

    @task(4)
    @tag("mcp", "rpc", "resources")
    def rpc_read_resource(self):
        """JSON-RPC: Read a resource."""
        if RESOURCE_IDS:
            resource_uri = random.choice(RESOURCE_IDS)
            payload = _json_rpc_request("resources/read", {"uri": resource_uri})
            self.client.post(
                "/rpc",
                json=payload,
                headers={**self.auth_headers, "Content-Type": "application/json"},
                name="/rpc resources/read",
            )

    @task(4)
    @tag("mcp", "rpc", "prompts")
    def rpc_get_prompt(self):
        """JSON-RPC: Get a prompt."""
        if PROMPT_IDS:
            prompt_name = random.choice(PROMPT_IDS)
            payload = _json_rpc_request("prompts/get", {"name": prompt_name})
            self.client.post(
                "/rpc",
                json=payload,
                headers={**self.auth_headers, "Content-Type": "application/json"},
                name="/rpc prompts/get",
            )

    @task(3)
    @tag("mcp", "rpc", "initialize")
    def rpc_initialize(self):
        """JSON-RPC: Initialize session."""
        payload = _json_rpc_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "clientInfo": {"name": "locust-load-test", "version": "1.0.0"},
            },
        )
        self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/rpc initialize",
        )

    @task(2)
    @tag("mcp", "rpc", "ping")
    def rpc_ping(self):
        """JSON-RPC: Ping."""
        payload = _json_rpc_request("ping")
        self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/rpc ping",
        )

    @task(3)
    @tag("mcp", "rpc", "resources")
    def rpc_list_resource_templates(self):
        """JSON-RPC: List resource templates."""
        payload = _json_rpc_request("resources/templates/list")
        self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/rpc resources/templates/list",
        )

    @task(2)
    @tag("mcp", "protocol")
    def protocol_initialize(self):
        """Protocol endpoint: Initialize."""
        payload = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
            "clientInfo": {"name": "locust-load-test", "version": "1.0.0"},
        }
        self.client.post(
            "/protocol/initialize",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/protocol/initialize",
        )

    @task(2)
    @tag("mcp", "protocol")
    def protocol_ping(self):
        """Protocol endpoint: Ping (JSON-RPC format)."""
        payload = _json_rpc_request("ping")
        self.client.post(
            "/protocol/ping",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/protocol/ping",
        )


class WriteAPIUser(BaseUser):
    """User that performs write operations.

    Simulates administrators or automated systems creating/updating entities.
    Weight: Low (writes are less common than reads)
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    def __init__(self, *args, **kwargs):
        """Initialize with tracking for cleanup."""
        super().__init__(*args, **kwargs)
        self.created_tools: list[str] = []
        self.created_servers: list[str] = []

    def on_stop(self):
        """Clean up created entities."""
        # Clean up tools
        for tool_id in self.created_tools:
            try:
                self.client.delete(f"/tools/{tool_id}", headers=self.auth_headers, name="/tools/[id] [cleanup]")
            except Exception:
                pass

        # Clean up servers
        for server_id in self.created_servers:
            try:
                self.client.delete(f"/servers/{server_id}", headers=self.auth_headers, name="/servers/[id] [cleanup]")
            except Exception:
                pass

    @task(5)
    @tag("api", "write", "tools")
    def create_and_delete_tool(self):
        """Create a tool and then delete it."""
        tool_name = f"loadtest_tool_{uuid.uuid4().hex[:8]}"
        tool_data = {
            "name": tool_name,
            "url": "http://localhost:9999/loadtest",
            "description": "Load test tool - will be deleted",
            "integration_type": "REST",
            "request_type": "POST",
            "input_schema": {"type": "object", "properties": {"input": {"type": "string"}}},
        }

        # Create
        with self.client.post(
            "/tools",
            json=tool_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/tools [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                try:
                    data = response.json()
                    tool_id = data.get("id") or data.get("name") or tool_name
                    # Delete immediately
                    time.sleep(0.1)
                    self.client.delete(f"/tools/{tool_id}", headers=self.auth_headers, name="/tools/[id] [delete]")
                except Exception:
                    pass
            elif response.status_code == 409:
                response.success()  # Conflict is acceptable

    @task(3)
    @tag("api", "write", "servers")
    def create_and_delete_server(self):
        """Create a virtual server and then delete it."""
        server_name = f"loadtest_server_{uuid.uuid4().hex[:8]}"
        server_data = {
            "name": server_name,
            "description": "Load test virtual server - will be deleted",
        }

        # Create
        with self.client.post(
            "/servers",
            json=server_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/servers [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                try:
                    data = response.json()
                    server_id = data.get("id") or data.get("name") or server_name
                    # Delete immediately
                    time.sleep(0.1)
                    self.client.delete(
                        f"/servers/{server_id}", headers=self.auth_headers, name="/servers/[id] [delete]"
                    )
                except Exception:
                    pass
            elif response.status_code == 409:
                response.success()  # Conflict is acceptable

    @task(2)
    @tag("api", "write", "toggle")
    def toggle_server_status(self):
        """Toggle a server's enabled status."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            # Just attempt the toggle - may fail if server doesn't support it
            self.client.post(
                f"/servers/{server_id}/toggle",
                headers=self.auth_headers,
                name="/servers/[id]/toggle",
            )

    @task(2)
    @tag("api", "write", "toggle")
    def toggle_tool_status(self):
        """Toggle a tool's enabled status."""
        if TOOL_IDS:
            tool_id = random.choice(TOOL_IDS)
            self.client.post(
                f"/tools/{tool_id}/toggle",
                headers=self.auth_headers,
                name="/tools/[id]/toggle",
            )

    @task(2)
    @tag("api", "write", "toggle")
    def toggle_resource_status(self):
        """Toggle a resource's enabled status."""
        if RESOURCE_IDS:
            resource_id = random.choice(RESOURCE_IDS)
            self.client.post(
                f"/resources/{resource_id}/toggle",
                headers=self.auth_headers,
                name="/resources/[id]/toggle",
            )

    @task(2)
    @tag("api", "write", "toggle")
    def toggle_prompt_status(self):
        """Toggle a prompt's enabled status."""
        if PROMPT_IDS:
            prompt_id = random.choice(PROMPT_IDS)
            self.client.post(
                f"/prompts/{prompt_id}/toggle",
                headers=self.auth_headers,
                name="/prompts/[id]/toggle",
            )

    @task(2)
    @tag("api", "write", "toggle")
    def toggle_gateway_status(self):
        """Toggle a gateway's enabled status."""
        if GATEWAY_IDS:
            gateway_id = random.choice(GATEWAY_IDS)
            self.client.post(
                f"/gateways/{gateway_id}/toggle",
                headers=self.auth_headers,
                name="/gateways/[id]/toggle",
            )

    @task(2)
    @tag("api", "write", "resources")
    def create_and_delete_resource(self):
        """Create a resource and then delete it."""
        resource_id = uuid.uuid4().hex[:8]
        resource_uri = f"file:///tmp/loadtest_{resource_id}.txt"
        resource_data = {
            "uri": resource_uri,
            "name": f"loadtest_resource_{resource_id}",
            "description": "Load test resource - will be deleted",
            "mime_type": "text/plain",
            "content": "Load test resource content",
        }

        with self.client.post(
            "/resources",
            json=resource_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/resources [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                try:
                    data = response.json()
                    resource_id = data.get("id") or data.get("uri") or resource_uri
                    time.sleep(0.1)
                    self.client.delete(
                        f"/resources/{resource_id}", headers=self.auth_headers, name="/resources/[id] [delete]"
                    )
                except Exception:
                    pass
            elif response.status_code == 409:
                response.success()

    @task(2)
    @tag("api", "write", "prompts")
    def create_and_delete_prompt(self):
        """Create a prompt and then delete it."""
        prompt_name = f"loadtest_prompt_{uuid.uuid4().hex[:8]}"
        prompt_data = {
            "name": prompt_name,
            "description": "Load test prompt - will be deleted",
            "template": "This is a load test prompt template with input: {{input}}",
            "arguments": [{"name": "input", "description": "Input text", "required": False}],
        }

        with self.client.post(
            "/prompts",
            json=prompt_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/prompts [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                try:
                    data = response.json()
                    prompt_id = data.get("id") or data.get("name") or prompt_name
                    time.sleep(0.1)
                    self.client.delete(
                        f"/prompts/{prompt_id}", headers=self.auth_headers, name="/prompts/[id] [delete]"
                    )
                except Exception:
                    pass
            elif response.status_code == 409:
                response.success()

    @task(1)
    @tag("api", "write", "gateways")
    def create_and_delete_gateway(self):
        """Create a gateway and then delete it."""
        gateway_name = f"loadtest_gateway_{uuid.uuid4().hex[:8]}"
        gateway_data = {
            "name": gateway_name,
            "description": "Load test gateway - will be deleted",
            "url": "http://localhost:9999/loadtest",
            "transport": "SSE",
        }

        with self.client.post(
            "/gateways",
            json=gateway_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/gateways [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                try:
                    data = response.json()
                    gateway_id = data.get("id") or data.get("name") or gateway_name
                    time.sleep(0.1)
                    self.client.delete(
                        f"/gateways/{gateway_id}", headers=self.auth_headers, name="/gateways/[id] [delete]"
                    )
                except Exception:
                    pass
            elif response.status_code == 409:
                response.success()


class StressTestUser(BaseUser):
    """User for stress testing with rapid requests.

    Simulates high-load scenarios with minimal wait times.
    Weight: Very low (only for stress tests)
    """

    weight = 1
    wait_time = between(0.05, 0.2)

    @task(10)
    @tag("stress", "health")
    def rapid_health_check(self):
        """Rapid health checks."""
        self.client.get("/health", name="/health [stress]")

    @task(8)
    @tag("stress", "api")
    def rapid_tools_list(self):
        """Rapid tools listing."""
        self.client.get("/tools", headers=self.auth_headers, name="/tools [stress]")

    @task(5)
    @tag("stress", "rpc")
    def rapid_rpc_ping(self):
        """Rapid RPC pings."""
        payload = _json_rpc_request("ping")
        self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/rpc ping [stress]",
        )


class FastTimeUser(BaseUser):
    """User that calls the fast_time MCP server tools.

    Tests the fast-time-get-system-time tool via JSON-RPC.
    Weight: High (main MCP tool testing)
    """

    weight = 5
    wait_time = between(0.1, 0.5)

    @task(10)
    @tag("mcp", "fasttime", "tools")
    def call_get_system_time(self):
        """Call fast-time-get-system-time with Europe/Dublin timezone."""
        payload = _json_rpc_request(
            "tools/call",
            {
                "name": "fast-time-get-system-time",
                "arguments": {"timezone": "Europe/Dublin"},
            },
        )
        self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/rpc fast-time-get-system-time",
        )

    @task(5)
    @tag("mcp", "fasttime", "tools")
    def call_get_system_time_utc(self):
        """Call fast-time-get-system-time with UTC timezone."""
        payload = _json_rpc_request(
            "tools/call",
            {
                "name": "fast-time-get-system-time",
                "arguments": {"timezone": "UTC"},
            },
        )
        self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/rpc fast-time-get-system-time [UTC]",
        )

    @task(3)
    @tag("mcp", "fasttime", "tools")
    def call_convert_time(self):
        """Call fast-time-convert-time to convert between timezones."""
        payload = _json_rpc_request(
            "tools/call",
            {
                "name": "fast-time-convert-time",
                "arguments": {
                    "time": "2025-01-01T12:00:00",
                    "source_timezone": "UTC",
                    "target_timezone": "Europe/Dublin",
                },
            },
        )
        self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/rpc fast-time-convert-time",
        )

    @task(2)
    @tag("mcp", "fasttime", "list")
    def list_tools(self):
        """List tools via JSON-RPC."""
        payload = _json_rpc_request("tools/list")
        self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/rpc tools/list [fasttime]",
        )


# =============================================================================
# Combined User (Realistic Traffic Pattern)
# =============================================================================


class RealisticUser(BaseUser):
    """User that simulates realistic mixed traffic.

    Combines behaviors from all user types with realistic weights.
    This is the default user for most load tests.
    """

    weight = 10
    wait_time = between(0.5, 2.0)

    @task(15)
    @tag("realistic", "health")
    def health_check(self):
        """Health check."""
        self.client.get("/health", name="/health")

    @task(20)
    @tag("realistic", "api")
    def list_tools(self):
        """List tools."""
        self.client.get("/tools", headers=self.auth_headers, name="/tools")

    @task(15)
    @tag("realistic", "api")
    def list_servers(self):
        """List servers."""
        self.client.get("/servers", headers=self.auth_headers, name="/servers")

    @task(10)
    @tag("realistic", "api")
    def list_gateways(self):
        """List gateways."""
        self.client.get("/gateways", headers=self.auth_headers, name="/gateways")

    @task(10)
    @tag("realistic", "api")
    def list_resources(self):
        """List resources."""
        self.client.get("/resources", headers=self.auth_headers, name="/resources")

    @task(10)
    @tag("realistic", "rpc")
    def rpc_list_tools(self):
        """JSON-RPC list tools."""
        payload = _json_rpc_request("tools/list")
        self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/rpc tools/list",
        )

    @task(8)
    @tag("realistic", "admin")
    def admin_dashboard(self):
        """Load admin dashboard."""
        self.client.get("/admin/", headers=self.admin_headers, name="/admin/")

    @task(5)
    @tag("realistic", "api")
    def get_single_tool(self):
        """Get specific tool."""
        if TOOL_IDS:
            tool_id = random.choice(TOOL_IDS)
            self.client.get(f"/tools/{tool_id}", headers=self.auth_headers, name="/tools/[id]")

    @task(5)
    @tag("realistic", "api")
    def get_single_server(self):
        """Get specific server."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            self.client.get(f"/servers/{server_id}", headers=self.auth_headers, name="/servers/[id]")

    @task(2)
    @tag("realistic", "admin")
    def admin_tools_page(self):
        """Admin tools page."""
        self.client.get("/admin/tools", headers=self.admin_headers, name="/admin/tools")


# =============================================================================
# Custom Shape (Optional - for advanced load patterns)
# =============================================================================

# Uncomment to use custom load shape instead of fixed user count
#
# from locust import LoadTestShape
#
# class StagesShape(LoadTestShape):
#     """Custom load shape with stages: ramp up, sustain, spike, cooldown."""
#
#     stages = [
#         {"duration": 60, "users": 10, "spawn_rate": 2},    # Warm up
#         {"duration": 120, "users": 50, "spawn_rate": 10},  # Ramp up
#         {"duration": 180, "users": 50, "spawn_rate": 10},  # Sustain
#         {"duration": 200, "users": 100, "spawn_rate": 20}, # Spike
#         {"duration": 240, "users": 50, "spawn_rate": 10},  # Recovery
#         {"duration": 300, "users": 10, "spawn_rate": 5},   # Cool down
#     ]
#
#     def tick(self):
#         run_time = self.get_run_time()
#
#         for stage in self.stages:
#             if run_time < stage["duration"]:
#                 return (stage["users"], stage["spawn_rate"])
#
#         return None  # Stop test
