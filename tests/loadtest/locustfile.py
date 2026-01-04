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
    cd tests/loadtest && locust --host=http://localhost:8080

Environment Variables (also reads from .env file):
    LOADTEST_HOST: Target host URL (default: http://localhost:8080)
    LOADTEST_USERS: Number of concurrent users (default: 1000)
    LOADTEST_SPAWN_RATE: Users spawned per second (default: 100)
    LOADTEST_RUN_TIME: Test duration, e.g., "60s", "5m" (default: 5m)
    LOADTEST_JWT_EXPIRY_HOURS: JWT token expiry in hours (default: 8760 = 1 year)
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

# Standard
import logging
import os
from pathlib import Path
import random
import time
from typing import Any
import uuid

# Third-Party
from locust import between, events, tag, task
from locust.contrib.fasthttp import FastHttpUser
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
# Token expiry in hours - default 8760 (1 year) to avoid expiration during long load tests
# JTI (JWT ID) is automatically generated for each token for proper cache keying
JWT_TOKEN_EXPIRY_HOURS = int(_get_config("LOADTEST_JWT_EXPIRY_HOURS", "8760"))

# Log loaded configuration (masking sensitive values)
logger.info("Configuration loaded:")
logger.info(f"  BASIC_AUTH_USER: {BASIC_AUTH_USER}")
logger.info(f"  JWT_ALGORITHM: {JWT_ALGORITHM}")
logger.info(f"  JWT_AUDIENCE: {JWT_AUDIENCE}")
logger.info(f"  JWT_ISSUER: {JWT_ISSUER}")
logger.info(f"  JWT_SECRET_KEY: {'*' * len(JWT_SECRET_KEY) if JWT_SECRET_KEY else '(not set)'}")
logger.info(f"  JWT_TOKEN_EXPIRY_HOURS: {JWT_TOKEN_EXPIRY_HOURS}")

# Test data pools (populated during test setup)
# IDs for REST API calls (GET /tools/{id}, etc.)
TOOL_IDS: list[str] = []
SERVER_IDS: list[str] = []
GATEWAY_IDS: list[str] = []
RESOURCE_IDS: list[str] = []
PROMPT_IDS: list[str] = []

# Names/URIs for RPC calls (tools/call uses name, resources/read uses uri, etc.)
TOOL_NAMES: list[str] = []
RESOURCE_URIS: list[str] = []
PROMPT_NAMES: list[str] = []

# Tools that require arguments and are tested with proper arguments in specific user classes
# These should be excluded from generic rpc_call_tool to avoid false failures
TOOLS_WITH_REQUIRED_ARGS: set[str] = {
    "fast-time-convert-time",  # Requires: time, source_timezone, target_timezone
    "fast-time-get-system-time",  # Requires: timezone
}


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


def _fetch_json(url: str, headers: dict[str, str], timeout: float = 30.0) -> tuple[int, Any]:
    """Fetch JSON from URL using urllib (gevent-safe, no threading issues with Python 3.13).

    Args:
        url: Full URL to fetch
        headers: HTTP headers to include
        timeout: Request timeout in seconds

    Returns:
        Tuple of (status_code, json_data or None)
    """
    # Standard
    import json  # pylint: disable=import-outside-toplevel
    import urllib.error  # pylint: disable=import-outside-toplevel
    import urllib.request  # pylint: disable=import-outside-toplevel

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return (resp.status, data)
    except urllib.error.HTTPError as e:
        return (e.code, None)
    except Exception:
        return (0, None)


@events.test_start.add_listener
def on_test_start(environment, **_kwargs):  # pylint: disable=unused-argument
    """Fetch existing entity IDs for use in tests.

    Uses urllib.request instead of httpx to avoid Python 3.13/gevent threading conflicts.
    httpx creates threads that trigger '_DummyThread' object has no attribute '_handle' errors.
    """
    logger.info("Test starting - fetching entity IDs...")

    host = environment.host or "http://localhost:8080"
    headers = _get_auth_headers()

    try:
        # Fetch tools
        # API returns {"tools": [...], "nextCursor": ...} or list for legacy
        status, data = _fetch_json(f"{host}/tools", headers)
        if status == 200 and data:
            items = data if isinstance(data, list) else data.get("tools", data.get("items", []))
            TOOL_IDS.extend([str(t.get("id")) for t in items[:50] if t.get("id")])
            TOOL_NAMES.extend([str(t.get("name")) for t in items[:50] if t.get("name")])
            logger.info(f"Loaded {len(TOOL_IDS)} tool IDs, {len(TOOL_NAMES)} tool names")

        # Fetch servers
        # API returns {"servers": [...], "nextCursor": ...} or list for legacy
        status, data = _fetch_json(f"{host}/servers", headers)
        if status == 200 and data:
            items = data if isinstance(data, list) else data.get("servers", data.get("items", []))
            SERVER_IDS.extend([str(s.get("id")) for s in items[:50] if s.get("id")])
            logger.info(f"Loaded {len(SERVER_IDS)} server IDs")

        # Fetch gateways
        # API returns {"gateways": [...], "nextCursor": ...} or list for legacy
        status, data = _fetch_json(f"{host}/gateways", headers)
        if status == 200 and data:
            items = data if isinstance(data, list) else data.get("gateways", data.get("items", []))
            GATEWAY_IDS.extend([str(g.get("id")) for g in items[:50] if g.get("id")])
            logger.info(f"Loaded {len(GATEWAY_IDS)} gateway IDs")

        # Fetch resources
        # API returns {"resources": [...], "nextCursor": ...} or list for legacy
        status, data = _fetch_json(f"{host}/resources", headers)
        if status == 200 and data:
            items = data if isinstance(data, list) else data.get("resources", data.get("items", []))
            RESOURCE_IDS.extend([str(r.get("id")) for r in items[:50] if r.get("id")])
            RESOURCE_URIS.extend([str(r.get("uri")) for r in items[:50] if r.get("uri")])
            logger.info(f"Loaded {len(RESOURCE_IDS)} resource IDs, {len(RESOURCE_URIS)} resource URIs")

        # Fetch prompts
        # API returns {"prompts": [...], "nextCursor": ...} or list for legacy
        status, data = _fetch_json(f"{host}/prompts", headers)
        if status == 200 and data:
            items = data if isinstance(data, list) else data.get("prompts", data.get("items", []))
            PROMPT_IDS.extend([str(p.get("id")) for p in items[:50] if p.get("id")])
            PROMPT_NAMES.extend([str(p.get("name")) for p in items[:50] if p.get("name")])
            logger.info(f"Loaded {len(PROMPT_IDS)} prompt IDs, {len(PROMPT_NAMES)} prompt names")

    except Exception as e:
        logger.warning(f"Failed to fetch entity IDs: {e}")
        logger.info("Tests will continue without pre-fetched IDs")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):  # pylint: disable=unused-argument
    """Clean up after test and print summary statistics."""
    logger.info("Test stopped")
    TOOL_IDS.clear()
    SERVER_IDS.clear()
    GATEWAY_IDS.clear()
    RESOURCE_IDS.clear()
    PROMPT_IDS.clear()
    TOOL_NAMES.clear()
    RESOURCE_URIS.clear()
    PROMPT_NAMES.clear()

    # Print detailed summary statistics
    _print_summary_stats(environment)


def _print_summary_stats(environment) -> None:
    """Print detailed summary statistics after test completion."""
    stats = environment.stats

    if not stats.entries:
        logger.info("No statistics recorded")
        return

    print("\n" + "=" * 100)
    print("LOAD TEST SUMMARY")
    print("=" * 100)

    # Overall totals
    total_requests = stats.total.num_requests
    total_failures = stats.total.num_failures
    total_rps = stats.total.total_rps
    failure_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0

    print(f"\n{'OVERALL METRICS':^100}")
    print("-" * 100)
    print(f"  Total Requests:     {total_requests:,}")
    print(f"  Total Failures:     {total_failures:,} ({failure_rate:.2f}%)")
    print(f"  Requests/sec (RPS): {total_rps:.2f}")

    if stats.total.num_requests > 0:
        print("\n  Response Times (ms):")
        print(f"    Average:          {stats.total.avg_response_time:.2f}")
        print(f"    Min:              {stats.total.min_response_time:.2f}")
        print(f"    Max:              {stats.total.max_response_time:.2f}")
        print(f"    Median (p50):     {stats.total.get_response_time_percentile(0.50):.2f}")
        print(f"    p90:              {stats.total.get_response_time_percentile(0.90):.2f}")
        print(f"    p95:              {stats.total.get_response_time_percentile(0.95):.2f}")
        print(f"    p99:              {stats.total.get_response_time_percentile(0.99):.2f}")

    # Per-endpoint breakdown (top 15 by request count)
    print(f"\n{'ENDPOINT BREAKDOWN (Top 15 by request count)':^100}")
    print("-" * 100)
    print(f"{'Endpoint':<40} {'Reqs':>8} {'Fails':>7} {'Avg':>8} {'Min':>8} {'Max':>8} {'p95':>8} {'RPS':>8}")
    print("-" * 100)

    # Sort by request count, get top 15
    sorted_entries = sorted(stats.entries.values(), key=lambda x: x.num_requests, reverse=True)[:15]

    for entry in sorted_entries:
        name = entry.name[:38] + ".." if len(entry.name) > 40 else entry.name
        reqs = entry.num_requests
        fails = entry.num_failures
        avg = entry.avg_response_time if reqs > 0 else 0
        min_rt = entry.min_response_time if reqs > 0 else 0
        max_rt = entry.max_response_time if reqs > 0 else 0
        p95 = entry.get_response_time_percentile(0.95) if reqs > 0 else 0
        rps = entry.total_rps

        print(f"{name:<40} {reqs:>8,} {fails:>7,} {avg:>8.1f} {min_rt:>8.1f} {max_rt:>8.1f} {p95:>8.1f} {rps:>8.2f}")

    # Slowest endpoints (by average response time)
    slow_entries = sorted(
        [e for e in stats.entries.values() if e.num_requests >= 10],
        key=lambda x: x.avg_response_time,
        reverse=True,
    )[:5]

    if slow_entries:
        print(f"\n{'SLOWEST ENDPOINTS (min 10 requests)':^100}")
        print("-" * 100)
        print(f"{'Endpoint':<50} {'Avg (ms)':>12} {'p95 (ms)':>12} {'Requests':>12}")
        print("-" * 100)
        for entry in slow_entries:
            name = entry.name[:48] + ".." if len(entry.name) > 50 else entry.name
            print(f"{name:<50} {entry.avg_response_time:>12.2f} {entry.get_response_time_percentile(0.95):>12.2f} {entry.num_requests:>12,}")

    # Error summary
    if stats.errors:
        print(f"\n{'ERRORS':^100}")
        print("-" * 100)
        for _error_key, error in list(stats.errors.items())[:10]:
            print(f"  [{error.occurrences}x] {error.method} {error.name}: {str(error.error)[:80]}")

    print("\n" + "=" * 100)
    print("END OF SUMMARY")
    print("=" * 100 + "\n")


# =============================================================================
# Helper Functions
# =============================================================================


def _generate_jwt_token() -> str:
    """Generate a JWT token for API authentication.

    Uses PyJWT to create a token with the configured secret and algorithm.
    Reads JWT settings from .env file or environment variables.

    The token includes:
    - sub: User email (JWT_USERNAME)
    - exp: Expiration time (configurable via LOADTEST_JWT_EXPIRY_HOURS, default 1 year)
    - iat: Issued at time
    - aud: Audience (JWT_AUDIENCE)
    - iss: Issuer (JWT_ISSUER)
    - jti: JWT ID - unique identifier for cache keying and token revocation
    """
    try:
        # Standard
        from datetime import datetime, timedelta, timezone  # pylint: disable=import-outside-toplevel

        # Third-Party
        import jwt  # pylint: disable=import-outside-toplevel

        jti = str(uuid.uuid4())
        payload = {
            "sub": JWT_USERNAME,
            "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_TOKEN_EXPIRY_HOURS),
            "iat": datetime.now(timezone.utc),
            "aud": JWT_AUDIENCE,
            "iss": JWT_ISSUER,
            "jti": jti,  # JWT ID for auth cache keying and token revocation support
        }
        token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        logger.info(f"Generated JWT token for user: {JWT_USERNAME} (aud={JWT_AUDIENCE}, iss={JWT_ISSUER}, jti={jti[:8]}..., expires_in={JWT_TOKEN_EXPIRY_HOURS}h)")
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
            # Standard
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


class BaseUser(FastHttpUser):
    """Base user class with common configuration.

    Uses FastHttpUser (gevent-based) for maximum throughput.
    """

    abstract = True
    wait_time = between(0.1, 0.5)

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

    def _validate_json_response(self, response, allowed_codes: list[int] | None = None):
        """Validate response is successful and contains valid JSON.

        Args:
            response: The response object from catch_response=True context
            allowed_codes: List of acceptable status codes (default: [200])
        """
        allowed = allowed_codes or [200]
        if response.status_code not in allowed:
            response.failure(f"Expected {allowed}, got {response.status_code}")
            return False
        try:
            data = response.json()
            if data is None:
                response.failure("Response JSON is null")
                return False
        except Exception as e:
            response.failure(f"Invalid JSON: {e}")
            return False
        response.success()
        return True

    def _validate_html_response(self, response, allowed_codes: list[int] | None = None):
        """Validate response is successful HTML.

        Args:
            response: The response object from catch_response=True context
            allowed_codes: List of acceptable status codes (default: [200])
        """
        allowed = allowed_codes or [200]
        if response.status_code not in allowed:
            response.failure(f"Expected {allowed}, got {response.status_code}")
            return False
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            response.failure(f"Expected HTML, got {content_type}")
            return False
        response.success()
        return True

    def _validate_status(self, response, allowed_codes: list[int] | None = None):
        """Validate response status code only.

        Args:
            response: The response object from catch_response=True context
            allowed_codes: List of acceptable status codes (default: [200])
        """
        allowed = allowed_codes or [200]
        if response.status_code not in allowed:
            response.failure(f"Expected {allowed}, got {response.status_code}")
            return False
        response.success()
        return True

    def _validate_jsonrpc_response(self, response, allowed_codes: list[int] | None = None):
        """Validate response is successful JSON-RPC (no error field).

        JSON-RPC 2.0 errors are returned with HTTP 200 but contain an "error" field.
        This method detects such errors and marks them as failures in Locust.

        Args:
            response: The response object from catch_response=True context
            allowed_codes: List of acceptable status codes (default: [200])

        Returns:
            bool: True if response is valid JSON-RPC success, False otherwise
        """
        allowed = allowed_codes or [200]
        if response.status_code not in allowed:
            response.failure(f"Expected {allowed}, got {response.status_code}")
            return False
        try:
            data = response.json()
            if data is None:
                response.failure("Response JSON is null")
                return False
            # Check for JSON-RPC error field
            if "error" in data:
                error_obj = data["error"]
                error_code = error_obj.get("code", "unknown")
                error_msg = error_obj.get("message", "Unknown error")
                error_data = str(error_obj.get("data", ""))[:100]
                response.failure(f"JSON-RPC error [{error_code}]: {error_msg} - {error_data}")
                return False
        except Exception as e:
            response.failure(f"Invalid JSON: {e}")
            return False
        response.success()
        return True


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
        with self.client.get("/health", name="/health", catch_response=True) as response:
            self._validate_status(response)

    @task(5)
    @tag("health")
    def readiness_check(self):
        """Check readiness endpoint (no auth required)."""
        with self.client.get("/ready", name="/ready", catch_response=True) as response:
            self._validate_status(response)

    @task(2)
    @tag("health")
    def metrics_endpoint(self):
        """Check Prometheus metrics endpoint."""
        with self.client.get("/metrics", headers=self.auth_headers, name="/metrics", catch_response=True) as response:
            self._validate_status(response)

    @task(1)
    @tag("health")
    def openapi_schema(self):
        """Fetch OpenAPI schema."""
        with self.client.get("/openapi.json", headers=self.auth_headers, name="/openapi.json", catch_response=True) as response:
            self._validate_json_response(response)


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
        with self.client.get("/tools", headers=self.auth_headers, name="/tools", catch_response=True) as response:
            self._validate_json_response(response)

    @task(8)
    @tag("api", "servers")
    def list_servers(self):
        """List all servers."""
        with self.client.get("/servers", headers=self.auth_headers, name="/servers", catch_response=True) as response:
            self._validate_json_response(response)

    @task(6)
    @tag("api", "gateways")
    def list_gateways(self):
        """List all gateways."""
        with self.client.get("/gateways", headers=self.auth_headers, name="/gateways", catch_response=True) as response:
            self._validate_json_response(response)

    @task(5)
    @tag("api", "resources")
    def list_resources(self):
        """List all resources."""
        with self.client.get("/resources", headers=self.auth_headers, name="/resources", catch_response=True) as response:
            self._validate_json_response(response)

    @task(5)
    @tag("api", "prompts")
    def list_prompts(self):
        """List all prompts."""
        with self.client.get("/prompts", headers=self.auth_headers, name="/prompts", catch_response=True) as response:
            self._validate_json_response(response)

    @task(4)
    @tag("api", "a2a")
    def list_a2a_agents(self):
        """List A2A agents."""
        with self.client.get("/a2a", headers=self.auth_headers, name="/a2a", catch_response=True) as response:
            self._validate_json_response(response)

    @task(3)
    @tag("api", "tags")
    def list_tags(self):
        """List all tags."""
        with self.client.get("/tags", headers=self.auth_headers, name="/tags", catch_response=True) as response:
            self._validate_json_response(response)

    @task(2)
    @tag("api", "metrics")
    def get_metrics(self):
        """Get application metrics."""
        with self.client.get("/metrics", headers=self.auth_headers, name="/metrics [api]", catch_response=True) as response:
            self._validate_status(response)

    @task(3)
    @tag("api", "tools")
    def get_single_tool(self):
        """Get a specific tool by ID."""
        if TOOL_IDS:
            tool_id = random.choice(TOOL_IDS)
            with self.client.get(
                f"/tools/{tool_id}",
                headers=self.auth_headers,
                name="/tools/[id]",
                catch_response=True,
            ) as response:
                # 200=Success, 404=Not found (acceptable)
                self._validate_json_response(response, allowed_codes=[200, 404])

    @task(3)
    @tag("api", "servers")
    def get_single_server(self):
        """Get a specific server by ID."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            with self.client.get(
                f"/servers/{server_id}",
                headers=self.auth_headers,
                name="/servers/[id]",
                catch_response=True,
            ) as response:
                # 200=Success, 404=Not found (acceptable)
                self._validate_json_response(response, allowed_codes=[200, 404])

    @task(2)
    @tag("api", "gateways")
    def get_single_gateway(self):
        """Get a specific gateway by ID."""
        if GATEWAY_IDS:
            gateway_id = random.choice(GATEWAY_IDS)
            with self.client.get(
                f"/gateways/{gateway_id}",
                headers=self.auth_headers,
                name="/gateways/[id]",
                catch_response=True,
            ) as response:
                self._validate_json_response(response, allowed_codes=[200, 404])

    @task(2)
    @tag("api", "roots")
    def list_roots(self):
        """List roots."""
        with self.client.get(
            "/roots",
            headers=self.auth_headers,
            name="/roots",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(2)
    @tag("api", "resources")
    def get_single_resource(self):
        """Get a specific resource by ID."""
        if RESOURCE_IDS:
            resource_id = random.choice(RESOURCE_IDS)
            with self.client.get(
                f"/resources/{resource_id}",
                headers=self.auth_headers,
                name="/resources/[id]",
                catch_response=True,
            ) as response:
                # 200=Success, 403=Forbidden (read-only), 404=Not found
                self._validate_json_response(response, allowed_codes=[200, 403, 404])

    @task(2)
    @tag("api", "prompts")
    def get_single_prompt(self):
        """Get a specific prompt by ID."""
        if PROMPT_IDS:
            prompt_id = random.choice(PROMPT_IDS)
            with self.client.get(
                f"/prompts/{prompt_id}",
                headers=self.auth_headers,
                name="/prompts/[id]",
                catch_response=True,
            ) as response:
                # 200=Success, 403=Forbidden (read-only), 404=Not found
                self._validate_json_response(response, allowed_codes=[200, 403, 404])

    @task(2)
    @tag("api", "servers")
    def get_server_tools(self):
        """Get tools for a specific server."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            with self.client.get(f"/servers/{server_id}/tools", headers=self.auth_headers, name="/servers/[id]/tools", catch_response=True) as response:
                self._validate_json_response(response, allowed_codes=[200, 404])

    @task(2)
    @tag("api", "servers")
    def get_server_resources(self):
        """Get resources for a specific server."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            with self.client.get(f"/servers/{server_id}/resources", headers=self.auth_headers, name="/servers/[id]/resources", catch_response=True) as response:
                self._validate_json_response(response, allowed_codes=[200, 404])

    @task(1)
    @tag("api", "discovery")
    def well_known_robots(self):
        """Check robots.txt (always available)."""
        with self.client.get(
            "/.well-known/robots.txt",
            headers=self.auth_headers,
            name="/.well-known/robots.txt",
            catch_response=True,
        ) as response:
            # 200=Success, 404=Not configured
            self._validate_status(response, allowed_codes=[200, 404])

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
            # 200=Success, 404=Not configured
            self._validate_status(response, allowed_codes=[200, 404])


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
        with self.client.get("/admin/", headers=self.admin_headers, name="/admin/", catch_response=True) as response:
            self._validate_html_response(response)

    @task(8)
    @tag("admin", "tools")
    def admin_tools_page(self):
        """Load tools list (JSON API)."""
        with self.client.get("/admin/tools", headers=self.admin_headers, name="/admin/tools", catch_response=True) as response:
            self._validate_json_response(response)

    @task(7)
    @tag("admin", "servers")
    def admin_servers_page(self):
        """Load servers list (JSON API)."""
        with self.client.get("/admin/servers", headers=self.admin_headers, name="/admin/servers", catch_response=True) as response:
            self._validate_json_response(response)

    @task(6)
    @tag("admin", "gateways")
    def admin_gateways_page(self):
        """Load gateways list (JSON API)."""
        with self.client.get("/admin/gateways", headers=self.admin_headers, name="/admin/gateways", catch_response=True) as response:
            self._validate_json_response(response)

    @task(5)
    @tag("admin", "resources")
    def admin_resources_page(self):
        """Load resources list (JSON API)."""
        with self.client.get("/admin/resources", headers=self.admin_headers, name="/admin/resources", catch_response=True) as response:
            self._validate_json_response(response)

    @task(5)
    @tag("admin", "prompts")
    def admin_prompts_page(self):
        """Load prompts list (JSON API)."""
        with self.client.get("/admin/prompts", headers=self.admin_headers, name="/admin/prompts", catch_response=True) as response:
            self._validate_json_response(response)

    @task(4)
    @tag("admin", "a2a")
    def admin_a2a_list(self):
        """Load A2A agents list (JSON API)."""
        with self.client.get("/admin/a2a", headers=self.auth_headers, name="/admin/a2a", catch_response=True) as response:
            self._validate_json_response(response)

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
            self._validate_status(response, allowed_codes=[200, 404])

    @task(2)
    @tag("admin", "logs")
    def admin_logs(self):
        """Load logs (JSON API)."""
        with self.client.get("/admin/logs", headers=self.auth_headers, name="/admin/logs", catch_response=True) as response:
            self._validate_json_response(response)

    @task(2)
    @tag("admin", "config")
    def admin_config_settings(self):
        """Load config settings (JSON API)."""
        with self.client.get("/admin/config/settings", headers=self.auth_headers, name="/admin/config/settings", catch_response=True) as response:
            self._validate_json_response(response)

    @task(2)
    @tag("admin", "metrics")
    def admin_metrics(self):
        """Load metrics (JSON API)."""
        with self.client.get("/admin/metrics", headers=self.admin_headers, name="/admin/metrics", catch_response=True) as response:
            self._validate_json_response(response)

    @task(2)
    @tag("admin", "teams")
    def admin_teams(self):
        """Load teams management page."""
        with self.client.get("/admin/teams", headers=self.admin_headers, name="/admin/teams", catch_response=True) as response:
            self._validate_html_response(response)

    @task(2)
    @tag("admin", "users")
    def admin_users(self):
        """Load users management page."""
        with self.client.get("/admin/users", headers=self.admin_headers, name="/admin/users", catch_response=True) as response:
            self._validate_html_response(response)

    @task(1)
    @tag("admin", "export")
    def admin_export_config(self):
        """Load export configuration (JSON API)."""
        with self.client.get("/admin/export/configuration", headers=self.admin_headers, name="/admin/export/configuration", catch_response=True) as response:
            self._validate_json_response(response)

    @task(1)
    @tag("admin", "htmx", "tools")
    def admin_tools_partial(self):
        """Fetch tools partial via HTMX."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get("/admin/tools/partial", headers=headers, name="/admin/tools/partial", catch_response=True) as response:
            self._validate_html_response(response)

    @task(1)
    @tag("admin", "htmx", "resources")
    def admin_resources_partial(self):
        """Fetch resources partial via HTMX."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get("/admin/resources/partial", headers=headers, name="/admin/resources/partial", catch_response=True) as response:
            self._validate_html_response(response)

    @task(1)
    @tag("admin", "htmx", "prompts")
    def admin_prompts_partial(self):
        """Fetch prompts partial via HTMX."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get("/admin/prompts/partial", headers=headers, name="/admin/prompts/partial", catch_response=True) as response:
            self._validate_html_response(response)

    @task(1)
    @tag("admin", "htmx", "metrics")
    def admin_metrics_partial(self):
        """Fetch metrics partial via HTMX."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get("/admin/metrics/partial", headers=headers, name="/admin/metrics/partial", catch_response=True) as response:
            self._validate_html_response(response)

    @task(1)
    @tag("admin", "htmx")
    def admin_htmx_refresh(self):
        """Simulate HTMX partial refresh."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        endpoint = random.choice(["/admin/tools/partial", "/admin/resources/partial", "/admin/prompts/partial"])
        with self.client.get(endpoint, headers=headers, name=f"{endpoint} [htmx]", catch_response=True) as response:
            self._validate_html_response(response)


class MCPJsonRpcUser(BaseUser):
    """User that makes MCP JSON-RPC requests.

    Simulates MCP clients (Claude Desktop, etc.) making protocol requests.
    Weight: High (core MCP traffic)
    """

    weight = 4
    wait_time = between(0.2, 1.0)

    def _rpc_request(self, payload: dict, name: str):
        """Make an RPC request with proper error handling.

        Uses JSON-RPC validation to detect errors returned with HTTP 200.
        """
        with self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name=name,
            catch_response=True,
        ) as response:
            self._validate_jsonrpc_response(response)

    @task(10)
    @tag("mcp", "rpc", "tools")
    def rpc_list_tools(self):
        """JSON-RPC: List tools."""
        payload = _json_rpc_request("tools/list")
        self._rpc_request(payload, "/rpc tools/list")

    @task(8)
    @tag("mcp", "rpc", "resources")
    def rpc_list_resources(self):
        """JSON-RPC: List resources."""
        payload = _json_rpc_request("resources/list")
        self._rpc_request(payload, "/rpc resources/list")

    @task(8)
    @tag("mcp", "rpc", "prompts")
    def rpc_list_prompts(self):
        """JSON-RPC: List prompts."""
        payload = _json_rpc_request("prompts/list")
        self._rpc_request(payload, "/rpc prompts/list")

    @task(5)
    @tag("mcp", "rpc", "tools")
    def rpc_call_tool(self):
        """JSON-RPC: Call a tool with empty arguments.

        Note: Tools that require arguments are excluded here and tested
        separately in dedicated user classes (e.g., FastTimeUser) with proper arguments.
        """
        # Filter out tools that require arguments - they're tested with proper args elsewhere
        callable_tools = [t for t in TOOL_NAMES if t not in TOOLS_WITH_REQUIRED_ARGS]
        if callable_tools:
            tool_name = random.choice(callable_tools)
            payload = _json_rpc_request("tools/call", {"name": tool_name, "arguments": {}})
            self._rpc_request(payload, "/rpc tools/call")

    @task(4)
    @tag("mcp", "rpc", "resources")
    def rpc_read_resource(self):
        """JSON-RPC: Read a resource."""
        if RESOURCE_URIS:
            resource_uri = random.choice(RESOURCE_URIS)
            payload = _json_rpc_request("resources/read", {"uri": resource_uri})
            self._rpc_request(payload, "/rpc resources/read")

    @task(4)
    @tag("mcp", "rpc", "prompts")
    def rpc_get_prompt(self):
        """JSON-RPC: Get a prompt."""
        if PROMPT_NAMES:
            prompt_name = random.choice(PROMPT_NAMES)
            payload = _json_rpc_request("prompts/get", {"name": prompt_name})
            self._rpc_request(payload, "/rpc prompts/get")

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
        self._rpc_request(payload, "/rpc initialize")

    @task(2)
    @tag("mcp", "rpc", "ping")
    def rpc_ping(self):
        """JSON-RPC: Ping."""
        payload = _json_rpc_request("ping")
        self._rpc_request(payload, "/rpc ping")

    @task(3)
    @tag("mcp", "rpc", "resources")
    def rpc_list_resource_templates(self):
        """JSON-RPC: List resource templates."""
        payload = _json_rpc_request("resources/templates/list")
        self._rpc_request(payload, "/rpc resources/templates/list")

    @task(2)
    @tag("mcp", "protocol")
    def protocol_initialize(self):
        """Protocol endpoint: Initialize."""
        payload = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
            "clientInfo": {"name": "locust-load-test", "version": "1.0.0"},
        }
        with self.client.post(
            "/protocol/initialize",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/protocol/initialize",
            catch_response=True,
        ) as response:
            self._validate_status(response)

    @task(2)
    @tag("mcp", "protocol")
    def protocol_ping(self):
        """Protocol endpoint: Ping (JSON-RPC format)."""
        payload = _json_rpc_request("ping")
        with self.client.post(
            "/protocol/ping",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/protocol/ping",
            catch_response=True,
        ) as response:
            self._validate_status(response)


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
        tool_name = f"loadtest-tool-{uuid.uuid4().hex[:8]}"
        tool_data = {
            "name": tool_name,
            "description": "Load test tool - will be deleted",
            "integration_type": "MCP",
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
            elif response.status_code in (409, 422):
                response.success()  # Conflict or validation error is acceptable for load test

    @task(3)
    @tag("api", "write", "servers")
    def create_and_delete_server(self):
        """Create a virtual server and then delete it."""
        server_name = f"loadtest-server-{uuid.uuid4().hex[:8]}"
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
                    self.client.delete(f"/servers/{server_id}", headers=self.auth_headers, name="/servers/[id] [delete]")
                except Exception:
                    pass
            elif response.status_code in (409, 422):
                response.success()  # Conflict or validation error is acceptable for load test

    @task(2)
    @tag("api", "write", "toggle")
    def toggle_server_status(self):
        """Toggle a server's enabled status."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            with self.client.post(
                f"/servers/{server_id}/toggle",
                headers=self.auth_headers,
                name="/servers/[id]/toggle",
                catch_response=True,
            ) as response:
                # 403/404 are acceptable - entity may not exist or may be read-only
                self._validate_json_response(response, allowed_codes=[200, 403, 404])

    @task(2)
    @tag("api", "write", "toggle")
    def toggle_tool_status(self):
        """Toggle a tool's enabled status."""
        if TOOL_IDS:
            tool_id = random.choice(TOOL_IDS)
            with self.client.post(
                f"/tools/{tool_id}/toggle",
                headers=self.auth_headers,
                name="/tools/[id]/toggle",
                catch_response=True,
            ) as response:
                # 403/404 are acceptable - entity may not exist or may be read-only
                self._validate_json_response(response, allowed_codes=[200, 403, 404])

    @task(2)
    @tag("api", "write", "toggle")
    def toggle_resource_status(self):
        """Toggle a resource's enabled status."""
        if RESOURCE_IDS:
            resource_id = random.choice(RESOURCE_IDS)
            with self.client.post(
                f"/resources/{resource_id}/toggle",
                headers=self.auth_headers,
                name="/resources/[id]/toggle",
                catch_response=True,
            ) as response:
                # 403/404 are acceptable - entity may not exist or may be read-only
                self._validate_json_response(response, allowed_codes=[200, 403, 404])

    @task(2)
    @tag("api", "write", "toggle")
    def toggle_prompt_status(self):
        """Toggle a prompt's enabled status."""
        if PROMPT_IDS:
            prompt_id = random.choice(PROMPT_IDS)
            with self.client.post(
                f"/prompts/{prompt_id}/toggle",
                headers=self.auth_headers,
                name="/prompts/[id]/toggle",
                catch_response=True,
            ) as response:
                # 403/404 are acceptable - entity may not exist or may be read-only
                self._validate_json_response(response, allowed_codes=[200, 403, 404])

    @task(2)
    @tag("api", "write", "toggle")
    def toggle_gateway_status(self):
        """Toggle a gateway's enabled status."""
        if GATEWAY_IDS:
            gateway_id = random.choice(GATEWAY_IDS)
            with self.client.post(
                f"/gateways/{gateway_id}/toggle",
                headers=self.auth_headers,
                name="/gateways/[id]/toggle",
                catch_response=True,
            ) as response:
                # 403/404/502 are acceptable - gateway may not exist or may be unreachable
                self._validate_json_response(response, allowed_codes=[200, 403, 404])

    @task(2)
    @tag("api", "write", "resources")
    def create_and_delete_resource(self):
        """Create a resource and then delete it."""
        resource_hex = uuid.uuid4().hex[:8]
        resource_uri = f"file:///tmp/loadtest-{resource_hex}.txt"
        resource_data = {
            "uri": resource_uri,
            "name": f"loadtest-resource-{resource_hex}",
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
                    res_id = data.get("id") or data.get("uri") or resource_uri
                    time.sleep(0.1)
                    self.client.delete(f"/resources/{res_id}", headers=self.auth_headers, name="/resources/[id] [delete]")
                except Exception:
                    pass
            elif response.status_code in (409, 422):
                response.success()  # Conflict or validation error is acceptable for load test

    @task(2)
    @tag("api", "write", "prompts")
    def create_and_delete_prompt(self):
        """Create a prompt and then delete it."""
        prompt_name = f"loadtest-prompt-{uuid.uuid4().hex[:8]}"
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
                    self.client.delete(f"/prompts/{prompt_id}", headers=self.auth_headers, name="/prompts/[id] [delete]")
                except Exception:
                    pass
            elif response.status_code in (409, 422):
                response.success()  # Conflict or validation error is acceptable for load test

    @task(1)
    @tag("api", "write", "gateways")
    def read_and_refresh_gateway(self):
        """Read existing gateway and trigger a refresh."""
        # First, get list of gateways
        # API returns {"gateways": [...], "nextCursor": ...} or list for legacy
        with self.client.get(
            "/gateways",
            headers=self.auth_headers,
            name="/gateways [list for refresh]",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Failed to list gateways: {response.status_code}")
                return
            try:
                data = response.json()
                # Extract gateways list from paginated response
                gateways = data if isinstance(data, list) else data.get("gateways", data.get("items", []))
                if not gateways:
                    response.success()
                    return
                response.success()
            except Exception as e:
                response.failure(f"Invalid JSON: {e}")
                return

        # Pick a gateway and read its details
        gateway = random.choice(gateways)
        gateway_id = gateway.get("id")
        if gateway_id:
            with self.client.get(
                f"/gateways/{gateway_id}",
                headers=self.auth_headers,
                name="/gateways/[id] [read]",
                catch_response=True,
            ) as response:
                self._validate_json_response(response, allowed_codes=[200, 404])


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
        with self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/rpc ping [stress]",
            catch_response=True,
        ) as response:
            self._validate_jsonrpc_response(response)


class FastTimeUser(BaseUser):
    """User that calls the fast_time MCP server tools.

    Tests the fast-time-get-system-time tool via JSON-RPC.
    Weight: High (main MCP tool testing)

    NOTE: These tests require the fast_time MCP server to be running.
    502 errors are expected if no MCP server is connected.
    """

    weight = 5
    wait_time = between(0.1, 0.5)

    def _rpc_request(self, payload: dict, name: str):
        """Make an RPC request with proper error handling.

        Uses JSON-RPC validation to detect errors returned with HTTP 200.
        """
        with self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name=name,
            catch_response=True,
        ) as response:
            self._validate_jsonrpc_response(response)

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
        self._rpc_request(payload, "/rpc fast-time-get-system-time")

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
        self._rpc_request(payload, "/rpc fast-time-get-system-time [UTC]")

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
        self._rpc_request(payload, "/rpc fast-time-convert-time")

    @task(2)
    @tag("mcp", "fasttime", "list")
    def list_tools(self):
        """List tools via JSON-RPC."""
        payload = _json_rpc_request("tools/list")
        self._rpc_request(payload, "/rpc tools/list [fasttime]")


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
        with self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/rpc tools/list",
            catch_response=True,
        ) as response:
            self._validate_jsonrpc_response(response)

    @task(8)
    @tag("realistic", "admin")
    def admin_dashboard(self):
        """Load admin dashboard."""
        with self.client.get(
            "/admin/",
            headers=self.admin_headers,
            name="/admin/",
            catch_response=True,
        ) as response:
            # 200=Success, 502=Bad Gateway (server under high load)
            self._validate_status(response)

    @task(5)
    @tag("realistic", "api")
    def get_single_tool(self):
        """Get specific tool."""
        if TOOL_IDS:
            tool_id = random.choice(TOOL_IDS)
            with self.client.get(
                f"/tools/{tool_id}",
                headers=self.auth_headers,
                name="/tools/[id]",
                catch_response=True,
            ) as response:
                # 200=Success, 404=Not found, 502=Bad Gateway
                self._validate_json_response(response, allowed_codes=[200, 404])

    @task(5)
    @tag("realistic", "api")
    def get_single_server(self):
        """Get specific server."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            with self.client.get(
                f"/servers/{server_id}",
                headers=self.auth_headers,
                name="/servers/[id]",
                catch_response=True,
            ) as response:
                # 200=Success, 404=Not found, 502=Bad Gateway
                self._validate_json_response(response, allowed_codes=[200, 404])

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
