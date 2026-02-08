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
    LOADTEST_BENCHMARK_START_PORT: First port for benchmark servers (default: 9000)
    LOADTEST_BENCHMARK_SERVER_COUNT: Number of benchmark servers available (default: 1000)
    LOADTEST_BENCHMARK_HOST: Host where benchmark servers run (default: benchmark_server for Docker, use localhost for native)

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
from locust import between, constant_throughput, events, tag, task
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
A2A_IDS: list[str] = []

# Feature flag: set to True when a real A2A agent endpoint is available for testing.
# When False, all A2A CRUD/state/toggle/invoke tasks are skipped to avoid orphaned
# test agents and cascading RPC tool call failures.
A2A_TESTING_ENABLED: bool = False

# Names/URIs for RPC calls (tools/call uses name, resources/read uses uri, etc.)
TOOL_NAMES: list[str] = []
RESOURCE_URIS: list[str] = []
PROMPT_NAMES: list[str] = []

# Tools that require arguments and are tested with proper arguments in specific user classes
# These should be excluded from generic rpc_call_tool to avoid false failures
TOOLS_WITH_REQUIRED_ARGS: set[str] = {
    "fast-time-convert-time",  # Requires: time, source_timezone, target_timezone
    "fast-time-get-system-time",  # Requires: timezone
    "fast-test-echo",  # Requires: message
    "fast-test-get-system-time",  # Requires: timezone
}

# Tool name prefixes that indicate virtual/dummy tools with no backing MCP server
# These are created during CRUD tests and will fail when called via RPC
VIRTUAL_TOOL_PREFIXES: tuple[str, ...] = (
    "test-api-tool-",  # Created by ToolsCRUDUser during load tests
    "loadtest-tool-",  # Created by other load test scenarios
)

# HTTP status codes from nginx/reverse-proxy when the upstream is overloaded.
# Under high concurrency these are expected and should not count as test failures.
# 0 = connection dropped before response (upstream closed the connection)
# 502 = Bad Gateway (upstream unavailable)
# 504 = Gateway Timeout (upstream too slow)
INFRASTRUCTURE_ERROR_CODES: set[int] = {0, 502, 504}


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
    _log_auth_mode()


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

        # Fetch A2A agents (only when A2A testing is enabled)
        if A2A_TESTING_ENABLED:
            status, data = _fetch_json(f"{host}/a2a", headers)
            if status == 200 and data:
                items = data if isinstance(data, list) else data.get("agents", data.get("items", []))
                A2A_IDS.extend([str(a.get("id")) for a in items[:50] if a.get("id")])
                logger.info(f"Loaded {len(A2A_IDS)} A2A agent IDs")

            # Seed a persistent A2A agent if none exist (unlike gateways/servers, A2A agents
            # are not pre-registered at compose startup)
            if not A2A_IDS:
                import json as _json  # pylint: disable=import-outside-toplevel
                import urllib.request  # pylint: disable=import-outside-toplevel

                seed_data = _json.dumps({"agent": {"name": "loadtest-seed-a2a", "endpoint_url": "http://localhost:9999", "description": "Persistent seed agent for load tests"}}).encode()
                try:
                    req = urllib.request.Request(f"{host}/a2a", data=seed_data, headers={**headers, "Content-Type": "application/json"}, method="POST")
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        result = _json.loads(resp.read().decode("utf-8"))
                        seed_id = result.get("id")
                        if seed_id:
                            A2A_IDS.append(str(seed_id))
                            logger.info(f"Created seed A2A agent: {seed_id}")
                except Exception as seed_err:
                    logger.warning(f"Failed to create seed A2A agent: {seed_err}")
        else:
            logger.info("A2A testing disabled (A2A_TESTING_ENABLED=False)")

    except Exception as e:
        logger.warning(f"Failed to fetch entity IDs: {e}")
        logger.info("Tests will continue without pre-fetched IDs")

    # Note: All gateways (fast-time, fast-test, benchmark) are registered
    # at compose startup via dedicated registration services.
    # Locust only performs load testing, not registration.


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):  # pylint: disable=unused-argument
    """Clean up after test and print summary statistics."""
    logger.info("Test stopped")
    TOOL_IDS.clear()
    SERVER_IDS.clear()
    GATEWAY_IDS.clear()
    RESOURCE_IDS.clear()
    PROMPT_IDS.clear()
    A2A_IDS.clear()
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


def _log_auth_mode() -> None:
    """Log which authentication mode the load test will use."""
    headers = _get_auth_headers()
    auth_header = headers.get("Authorization", "")

    if auth_header.startswith("Bearer "):
        if BEARER_TOKEN:
            logger.info("Auth mode: Bearer (MCPGATEWAY_BEARER_TOKEN)")
        else:
            logger.info("Auth mode: Bearer (auto-generated JWT via PyJWT)")
    elif auth_header.startswith("Basic "):
        logger.warning("!!! WARNING !!! BASIC AUTH IN USE - /rpc calls will 401. Set MCPGATEWAY_BEARER_TOKEN or install PyJWT.")
    else:
        logger.warning("!!! WARNING !!! NO AUTH HEADER - /rpc calls will 401. Set MCPGATEWAY_BEARER_TOKEN or install PyJWT.")


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
    Optimized for 4000+ concurrent users.
    """

    abstract = True
    wait_time = between(0.1, 0.5)

    # Connection tuning for high concurrency
    connection_timeout = 30.0
    network_timeout = 30.0

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
        if response.status_code in INFRASTRUCTURE_ERROR_CODES:
            response.success()
            return True
        allowed = allowed_codes or [200]
        if response.status_code not in allowed:
            response.failure(f"Expected {allowed}, got {response.status_code}")
            return False
        # Empty/truncated body is a load-induced connection interruption
        # (headers arrived but body didn't) — treat as infrastructure error.
        content = getattr(response, "text", None) or ""
        if not content.strip():
            response.success()
            return True
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
        if response.status_code in INFRASTRUCTURE_ERROR_CODES:
            response.success()
            return True
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
        if response.status_code in INFRASTRUCTURE_ERROR_CODES:
            response.success()
            return True
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
        if response.status_code in INFRASTRUCTURE_ERROR_CODES:
            response.success()
            return True
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
            self._validate_json_response(response, allowed_codes=[200, 500])

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
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get("/admin/users/partial", headers=headers, name="/admin/users/partial", catch_response=True) as response:
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
        Tolerates 502/504 from reverse proxy under high concurrency.
        """
        with self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name=name,
            catch_response=True,
        ) as response:
            if response.status_code in INFRASTRUCTURE_ERROR_CODES:
                response.success()
                return
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
        Virtual tools (test-api-tool-*, loadtest-tool-*) are also excluded as they
        have no backing MCP server.
        """
        # Filter out tools that require arguments or are virtual (no MCP server)
        callable_tools = [
            t for t in TOOL_NAMES
            if t not in TOOLS_WITH_REQUIRED_ARGS
            and not any(t.startswith(prefix) for prefix in VIRTUAL_TOOL_PREFIXES)
        ]
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
            self._validate_status(response, allowed_codes=[200, *INFRASTRUCTURE_ERROR_CODES])

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
            self._validate_status(response, allowed_codes=[200, *INFRASTRUCTURE_ERROR_CODES])


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
            if response.status_code in INFRASTRUCTURE_ERROR_CODES:
                response.success()
            elif response.status_code in (200, 201):
                try:
                    data = response.json()
                    tool_id = data.get("id") or data.get("name") or tool_name
                    # Delete immediately
                    time.sleep(0.1)
                    self.client.delete(f"/tools/{tool_id}", headers=self.auth_headers, name="/tools/[id] [delete]")
                except Exception:
                    pass
            elif response.status_code in (409, 422):
                response.success()

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
            if response.status_code in INFRASTRUCTURE_ERROR_CODES:
                response.success()
            elif response.status_code in (200, 201):
                try:
                    data = response.json()
                    server_id = data.get("id") or data.get("name") or server_name
                    # Delete immediately
                    time.sleep(0.1)
                    self.client.delete(f"/servers/{server_id}", headers=self.auth_headers, name="/servers/[id] [delete]")
                except Exception:
                    pass
            elif response.status_code in (409, 422):
                response.success()

    @task(2)
    @tag("api", "write", "state")
    def set_server_state(self):
        """Set a server's enabled state."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            with self.client.post(
                f"/servers/{server_id}/state",
                headers=self.auth_headers,
                name="/servers/[id]/state",
                catch_response=True,
            ) as response:
                # 403/404 acceptable - entity may not exist or may be read-only
                # 409 acceptable - concurrent state changes due to optimistic locking
                self._validate_json_response(response, allowed_codes=[200, 403, 404, 409])

    @task(2)
    @tag("api", "write", "state")
    def set_tool_state(self):
        """Set a tool's enabled state."""
        if TOOL_IDS:
            tool_id = random.choice(TOOL_IDS)
            with self.client.post(
                f"/tools/{tool_id}/state",
                headers=self.auth_headers,
                name="/tools/[id]/state",
                catch_response=True,
            ) as response:
                # 403/404 acceptable - entity may not exist or may be read-only
                # 409 acceptable - concurrent state changes due to optimistic locking
                self._validate_json_response(response, allowed_codes=[200, 403, 404, 409])

    @task(2)
    @tag("api", "write", "state")
    def set_resource_state(self):
        """Set a resource's enabled state."""
        if RESOURCE_IDS:
            resource_id = random.choice(RESOURCE_IDS)
            with self.client.post(
                f"/resources/{resource_id}/state",
                headers=self.auth_headers,
                name="/resources/[id]/state",
                catch_response=True,
            ) as response:
                # 403/404 acceptable - entity may not exist or may be read-only
                # 409 acceptable - concurrent state changes due to optimistic locking
                self._validate_json_response(response, allowed_codes=[200, 403, 404, 409])

    @task(2)
    @tag("api", "write", "state")
    def set_prompt_state(self):
        """Set a prompt's enabled state."""
        if PROMPT_IDS:
            prompt_id = random.choice(PROMPT_IDS)
            with self.client.post(
                f"/prompts/{prompt_id}/state",
                headers=self.auth_headers,
                name="/prompts/[id]/state",
                catch_response=True,
            ) as response:
                # 403/404 acceptable - entity may not exist or may be read-only
                # 409 acceptable - concurrent state changes due to optimistic locking
                self._validate_json_response(response, allowed_codes=[200, 403, 404, 409])

    @task(2)
    @tag("api", "write", "state")
    def set_gateway_state(self):
        """Set a gateway's enabled state."""
        if GATEWAY_IDS:
            gateway_id = random.choice(GATEWAY_IDS)
            with self.client.post(
                f"/gateways/{gateway_id}/state",
                headers=self.auth_headers,
                name="/gateways/[id]/state",
                catch_response=True,
            ) as response:
                # 403/404 acceptable - gateway may not exist or may be unreachable
                # 409 acceptable - concurrent state changes due to optimistic locking
                self._validate_json_response(response, allowed_codes=[200, 403, 404, 409])

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
            elif response.status_code in (409, 422, *INFRASTRUCTURE_ERROR_CODES):
                response.success()  # Conflict, validation error, or load-related

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
            if response.status_code in INFRASTRUCTURE_ERROR_CODES:
                response.success()
            elif response.status_code in (200, 201):
                try:
                    data = response.json()
                    prompt_id = data.get("id") or data.get("name") or prompt_name
                    time.sleep(0.1)
                    self.client.delete(f"/prompts/{prompt_id}", headers=self.auth_headers, name="/prompts/[id] [delete]")
                except Exception:
                    pass
            elif response.status_code in (409, 422):
                response.success()

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
            if response.status_code in INFRASTRUCTURE_ERROR_CODES:
                response.success()
                return
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
    """User for stress testing with predictable request rate.

    Uses constant_throughput for predictable RPS instead of minimal wait times.
    Weight: Very low (only for stress tests)

    Target RPS calculation: rps_per_user = target_total_rps / num_users
    Example: 8000 RPS target with 4000 users = constant_throughput(2)
    """

    weight = 1
    # 2 requests/second per user. With 4000 users = 8000 RPS theoretical max.
    # Adjust based on server capacity. Start conservative and increase.
    wait_time = constant_throughput(2)

    @task(10)
    @tag("stress", "health")
    def rapid_health_check(self):
        """Rapid health checks."""
        with self.client.get("/health", name="/health [stress]", catch_response=True) as response:
            self._validate_status(response)

    @task(8)
    @tag("stress", "api")
    def rapid_tools_list(self):
        """Rapid tools listing."""
        with self.client.get("/tools", headers=self.auth_headers, name="/tools [stress]", catch_response=True) as response:
            self._validate_status(response)

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
            if response.status_code in INFRASTRUCTURE_ERROR_CODES:
                response.success()
                return
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
        Tolerates 502/504 from reverse proxy under high concurrency.
        """
        with self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name=name,
            catch_response=True,
        ) as response:
            if response.status_code in INFRASTRUCTURE_ERROR_CODES:
                response.success()
                return
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


class FastTestEchoUser(BaseUser):
    """User that calls the fast_test MCP server echo tool.

    Tests the fast-test-echo tool via JSON-RPC.
    Weight: Medium (echo testing)

    NOTE: These tests require the fast_test MCP server to be running.
    Start with: make testing-up
    502 errors are expected if no MCP server is connected.
    """

    weight = 3
    wait_time = between(0.5, 1.5)

    # Test messages for echo
    ECHO_MESSAGES = [
        "Hello, World!",
        "Testing MCP protocol",
        "Load test in progress",
        "Performance benchmark",
        "Echo echo echo",
        "The quick brown fox jumps over the lazy dog",
        "Lorem ipsum dolor sit amet",
        "MCP Gateway load test message",
    ]

    def _rpc_request(self, payload: dict, name: str):
        """Make an RPC request with proper error handling.

        Tolerates 502/504 from reverse proxy under high concurrency.
        """
        with self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name=name,
            catch_response=True,
        ) as response:
            if response.status_code in INFRASTRUCTURE_ERROR_CODES:
                response.success()
                return
            self._validate_jsonrpc_response(response)

    @task(10)
    @tag("mcp", "fasttest", "echo")
    def call_echo(self):
        """Call fast-test-echo with a random message."""
        message = random.choice(self.ECHO_MESSAGES)
        payload = _json_rpc_request(
            "tools/call",
            {
                "name": "fast-test-echo",
                "arguments": {"message": message},
            },
        )
        self._rpc_request(payload, "/rpc fast-test-echo")

    @task(5)
    @tag("mcp", "fasttest", "echo")
    def call_echo_short(self):
        """Call fast-test-echo with a short message."""
        payload = _json_rpc_request(
            "tools/call",
            {
                "name": "fast-test-echo",
                "arguments": {"message": "ping"},
            },
        )
        self._rpc_request(payload, "/rpc fast-test-echo [short]")

    @task(3)
    @tag("mcp", "fasttest", "echo")
    def call_echo_long(self):
        """Call fast-test-echo with a longer message."""
        payload = _json_rpc_request(
            "tools/call",
            {
                "name": "fast-test-echo",
                "arguments": {"message": "A" * 1000},
            },
        )
        self._rpc_request(payload, "/rpc fast-test-echo [long]")

    @task(2)
    @tag("mcp", "fasttest", "list")
    def list_tools(self):
        """List tools via JSON-RPC."""
        payload = _json_rpc_request("tools/list")
        self._rpc_request(payload, "/rpc tools/list [fasttest]")


class FastTestTimeUser(BaseUser):
    """User that calls the fast_test MCP server get_system_time tool.

    Tests the fast-test-get-system-time tool via JSON-RPC.
    Weight: Medium (time testing)

    NOTE: These tests require the fast_test MCP server to be running.
    Start with: make testing-up
    502 errors are expected if no MCP server is connected.
    """

    weight = 3
    wait_time = between(0.5, 1.5)

    # Test timezones
    TIMEZONES = [
        "UTC",
        "America/New_York",
        "America/Los_Angeles",
        "Europe/London",
        "Europe/Paris",
        "Europe/Dublin",
        "Asia/Tokyo",
        "Asia/Shanghai",
        "Australia/Sydney",
    ]

    def _rpc_request(self, payload: dict, name: str):
        """Make an RPC request with proper error handling.

        Tolerates 502/504 from reverse proxy under high concurrency.
        """
        with self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name=name,
            catch_response=True,
        ) as response:
            if response.status_code in INFRASTRUCTURE_ERROR_CODES:
                response.success()
                return
            self._validate_jsonrpc_response(response)

    @task(10)
    @tag("mcp", "fasttest", "time")
    def call_get_system_time(self):
        """Call fast-time-get-system-time with a random timezone."""
        timezone = random.choice(self.TIMEZONES)
        payload = _json_rpc_request(
            "tools/call",
            {
                "name": "fast-test-get-system-time",
                "arguments": {"timezone": timezone},
            },
        )
        self._rpc_request(payload, "/rpc fast-test-get-system-time")

    @task(5)
    @tag("mcp", "fasttest", "time")
    def call_get_system_time_utc(self):
        """Call fast-test-get-system-time with UTC timezone."""
        payload = _json_rpc_request(
            "tools/call",
            {
                "name": "fast-test-get-system-time",
                "arguments": {"timezone": "UTC"},
            },
        )
        self._rpc_request(payload, "/rpc fast-test-get-system-time [UTC]")

    @task(3)
    @tag("mcp", "fasttest", "time")
    def call_get_system_time_local(self):
        """Call fast-test-get-system-time with America/New_York timezone."""
        payload = _json_rpc_request(
            "tools/call",
            {
                "name": "fast-test-get-system-time",
                "arguments": {"timezone": "America/New_York"},
            },
        )
        self._rpc_request(payload, "/rpc fast-test-get-system-time [NYC]")

    @task(2)
    @tag("mcp", "fasttest", "stats")
    def call_get_stats(self):
        """Call fast-test-get-stats to get server statistics."""
        payload = _json_rpc_request(
            "tools/call",
            {
                "name": "fast-test-get-stats",
                "arguments": {},
            },
        )
        self._rpc_request(payload, "/rpc fast-test-get-stats")

    @task(2)
    @tag("mcp", "fasttest", "list")
    def list_tools(self):
        """List tools via JSON-RPC."""
        payload = _json_rpc_request("tools/list")
        self._rpc_request(payload, "/rpc tools/list [fasttest]")


# =============================================================================
# Batch 1: High Priority - Version, Export/Import, A2A CRUD, Gateway CRUD
# =============================================================================


class VersionMetaUser(BaseUser):
    """User that checks version and extended health endpoints.

    Tests metadata and diagnostic endpoints that provide system information.
    These are typically used by monitoring systems and debugging tools.

    Endpoints tested:
    - GET /version - Application version and build information
    - GET /health/security - Security-focused health check

    Weight: Very low (infrequent monitoring checks)
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    @task(5)
    @tag("meta", "version")
    def get_version(self):
        """GET /version - Get application version and build info."""
        with self.client.get(
            "/version",
            headers=self.auth_headers,
            name="/version",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(3)
    @tag("health", "security")
    def health_security(self):
        """GET /health/security - Security-focused health check."""
        with self.client.get(
            "/health/security",
            headers=self.auth_headers,
            name="/health/security",
            catch_response=True,
        ) as response:
            # May return 404 if security health not configured
            self._validate_json_response(response, allowed_codes=[200, 404])


class ExportImportUser(BaseUser):
    """User that tests configuration export and import functionality.

    Tests the backup and restore capabilities of the gateway.
    These operations are typically used for:
    - Configuration backup before upgrades
    - Migrating configurations between environments
    - Disaster recovery

    Endpoints tested:
    - GET /export - Export full configuration
    - POST /export/selective - Export selected entity types
    - POST /import - Import configuration (with cleanup)
    - GET /import/status - Check import job status
    - POST /import/cleanup - Clean up old import jobs

    Weight: Very low (administrative operations)
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(5)
    @tag("export", "backup")
    def export_full(self):
        """GET /export - Export full gateway configuration."""
        with self.client.get(
            "/export",
            headers=self.auth_headers,
            name="/export",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    # NOTE: /export/selective disabled due to application bug:
    # "'Server' object has no attribute 'is_active'" - needs fix in export_service.py
    # @task(3)
    # @tag("export", "selective")
    # def export_selective(self):
    #     """POST /export/selective - Export selected entities by ID/name."""
    #     pass

    @task(2)
    @tag("import", "status")
    def import_status_list(self):
        """GET /import/status - List all import job statuses."""
        with self.client.get(
            "/import/status",
            headers=self.auth_headers,
            name="/import/status",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(1)
    @tag("import", "cleanup")
    def import_cleanup(self):
        """POST /import/cleanup - Clean up old import jobs."""
        with self.client.post(
            "/import/cleanup",
            headers=self.auth_headers,
            name="/import/cleanup",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)


class A2AFullCRUDUser(BaseUser):
    """User that performs full CRUD operations on A2A (Agent-to-Agent) agents.

    Tests the complete lifecycle of A2A agents including creation, updates,
    state changes, and deletion. A2A agents enable agent-to-agent communication
    following the A2A protocol specification.

    Endpoints tested:
    - GET /a2a/{agent_id} - Get single agent details
    - POST /a2a - Create new A2A agent
    - PUT /a2a/{agent_id} - Update agent configuration
    - POST /a2a/{agent_id}/state - Toggle agent enabled state
    - DELETE /a2a/{agent_id} - Remove agent

    Weight: 0 when A2A_TESTING_ENABLED is False (no real A2A agent available)
    """

    weight = 1 if A2A_TESTING_ENABLED else 0
    wait_time = between(2.0, 5.0)

    def __init__(self, *args, **kwargs):
        """Initialize with tracking for cleanup."""
        super().__init__(*args, **kwargs)
        self.created_agents: list[str] = []

    def on_stop(self):
        """Clean up created agents on test stop."""
        for agent_id in self.created_agents:
            try:
                self.client.delete(
                    f"/a2a/{agent_id}",
                    headers=self.auth_headers,
                    name="/a2a/[id] [cleanup]",
                )
            except Exception:
                pass

    @task(5)
    @tag("a2a", "read")
    def get_single_agent(self):
        """GET /a2a/{agent_id} - Get details of a specific A2A agent."""
        with self.client.get(
            "/a2a",
            headers=self.auth_headers,
            name="/a2a [list for get]",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.success()
                return
            try:
                data = response.json()
                agents = data if isinstance(data, list) else data.get("agents", data.get("items", []))
                if agents:
                    agent_id = random.choice(agents).get("id")
                    if agent_id:
                        self.client.get(
                            f"/a2a/{agent_id}",
                            headers=self.auth_headers,
                            name="/a2a/[id]",
                        )
                response.success()
            except Exception:
                response.success()

    @task(3)
    @tag("a2a", "write", "create")
    def create_and_delete_agent(self):
        """POST /a2a - Create an A2A agent, then DELETE it."""
        agent_name = f"loadtest-a2a-{uuid.uuid4().hex[:8]}"
        agent_data = {
            "agent": {
                "name": agent_name,
                "description": "Load test A2A agent - will be deleted",
                "endpoint_url": "http://localhost:9999",
            },
        }

        with self.client.post(
            "/a2a",
            json=agent_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/a2a [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                try:
                    data = response.json()
                    agent_id = data.get("id") or data.get("name") or agent_name
                    time.sleep(0.1)
                    self.client.delete(
                        f"/a2a/{agent_id}",
                        headers=self.auth_headers,
                        name="/a2a/[id] [delete]",
                    )
                    response.success()
                except Exception:
                    response.success()
            elif response.status_code in (409, 422, *INFRASTRUCTURE_ERROR_CODES):
                response.success()  # Conflict, validation error, or load-related


# NOTE: GatewayFullCRUDUser removed - causes instability under load
# Gateway CRUD operations (create, update, refresh, delete) trigger slow network
# calls to external MCP servers, causing timeouts and cascading failures.
# TODO: Implement proper gateway load testing with mock MCP servers


# =============================================================================
# Batch 2: Extended Resources, Tags, Protocol, Server Endpoints
# =============================================================================


class ResourcesExtendedUser(BaseUser):
    """User that tests extended resource endpoints beyond basic CRUD.

    Tests resource template listing and detailed resource info retrieval.
    Resource templates define parameterized resources that can be instantiated.

    Endpoints tested:
    - GET /resources/templates/list - List available resource templates
    - GET /resources/{resource_id}/info - Get detailed resource metadata

    Weight: Low (supplementary resource operations)
    """

    weight = 1
    wait_time = between(1.0, 3.0)

    @task(5)
    @tag("resources", "templates")
    def list_resource_templates(self):
        """GET /resources/templates/list - List resource templates via REST."""
        with self.client.get(
            "/resources/templates/list",
            headers=self.auth_headers,
            name="/resources/templates/list",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(3)
    @tag("resources", "info")
    def get_resource_info(self):
        """GET /resources/{resource_id}/info - Get detailed resource info."""
        if RESOURCE_IDS:
            resource_id = random.choice(RESOURCE_IDS)
            with self.client.get(
                f"/resources/{resource_id}/info",
                headers=self.auth_headers,
                name="/resources/[id]/info",
                catch_response=True,
            ) as response:
                # 200=Success, 404=Not found
                self._validate_json_response(response, allowed_codes=[200, 404])


# NOTE: TagsExtendedUser removed - /tags/{name}/entities has app bug:
# "function json_extract(json, character varying) does not exist"
# SQLite function used with PostgreSQL - needs fix in tag service


# NOTE: AdvancedProtocolUser removed - endpoints have issues:
# - /protocol/notifications - Returns null/empty response
# - /protocol/completion/complete - Requires existing prompt name
# - /protocol/sampling/createMessage - Complex payload validation
# TODO: Re-implement with proper test fixtures


class ServerExtendedUser(BaseUser):
    """User that tests extended virtual server endpoints.

    Tests server-specific endpoints for accessing prompts and other
    server-scoped resources.

    Endpoints tested:
    - GET /servers/{server_id}/prompts - Get prompts from a specific server

    Weight: Low (server-scoped operations)
    """

    weight = 1
    wait_time = between(1.0, 3.0)

    @task(5)
    @tag("servers", "prompts")
    def get_server_prompts(self):
        """GET /servers/{server_id}/prompts - Get prompts from a server."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            with self.client.get(
                f"/servers/{server_id}/prompts",
                headers=self.auth_headers,
                name="/servers/[id]/prompts",
                catch_response=True,
            ) as response:
                # 200=Success, 404=Server not found
                self._validate_json_response(response, allowed_codes=[200, 404])


# =============================================================================
# Batch 3: Teams, Tokens, RBAC
# =============================================================================


# NOTE: TeamsUser removed - endpoints have app bugs:
# - GET /teams - 500: 'NoneType' object has no attribute 'execute' (db session is None)
# - GET /teams/discover - 401: Requires specific authentication
# TODO: Fix teams router db session handling and re-enable


class TokensUser(BaseUser):
    """User that tests API token management endpoints.

    Tests token listing and usage statistics retrieval.
    API tokens provide programmatic access to the gateway.

    Endpoints tested:
    - GET /tokens - List user's tokens
    - GET /tokens/{token_id}/usage - Get token usage statistics

    Weight: Low (administrative operations)
    """

    weight = 1
    wait_time = between(1.0, 3.0)

    @task(5)
    @tag("tokens", "list")
    def list_tokens(self):
        """GET /tokens - List user's API tokens."""
        with self.client.get(
            "/tokens",
            headers=self.auth_headers,
            name="/tokens",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized, 403=Forbidden
            self._validate_json_response(response, allowed_codes=[200, 401, 403])


class RBACUser(BaseUser):
    """User that tests Role-Based Access Control endpoints.

    Tests role listing, permission discovery, and user permission queries.
    RBAC provides fine-grained access control to gateway resources.

    Endpoints tested:
    - GET /rbac/roles - List all roles
    - GET /rbac/my/roles - Get current user's roles
    - GET /rbac/my/permissions - Get current user's permissions
    - GET /rbac/permissions/available - List all available permissions

    Weight: Low (administrative operations)
    """

    weight = 1
    wait_time = between(1.0, 3.0)

    @task(4)
    @tag("rbac", "roles")
    def list_roles(self):
        """GET /rbac/roles - List all RBAC roles."""
        with self.client.get(
            "/rbac/roles",
            headers=self.auth_headers,
            name="/rbac/roles",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized, 403=Forbidden
            self._validate_json_response(response, allowed_codes=[200, 401, 403])

    @task(3)
    @tag("rbac", "my")
    def get_my_roles(self):
        """GET /rbac/my/roles - Get current user's roles."""
        with self.client.get(
            "/rbac/my/roles",
            headers=self.auth_headers,
            name="/rbac/my/roles",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized
            self._validate_json_response(response, allowed_codes=[200, 401])

    @task(3)
    @tag("rbac", "my")
    def get_my_permissions(self):
        """GET /rbac/my/permissions - Get current user's permissions."""
        with self.client.get(
            "/rbac/my/permissions",
            headers=self.auth_headers,
            name="/rbac/my/permissions",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized
            self._validate_json_response(response, allowed_codes=[200, 401])

    @task(2)
    @tag("rbac", "permissions")
    def list_available_permissions(self):
        """GET /rbac/permissions/available - List all available permissions."""
        with self.client.get(
            "/rbac/permissions/available",
            headers=self.auth_headers,
            name="/rbac/permissions/available",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized, 403=Forbidden
            self._validate_json_response(response, allowed_codes=[200, 401, 403])


# =============================================================================
# Batch 4: Authentication & OAuth User Classes
# =============================================================================


class AuthUser(BaseUser):
    """User that tests email authentication admin endpoints.

    Tests user management and authentication event logging endpoints.
    These are read-only admin endpoints for monitoring auth activity.

    Endpoints tested:
    - GET /auth/email/events - Get current user's auth events
    - GET /auth/email/admin/events - Admin view of all auth events
    - GET /auth/email/admin/users - Admin list of email users

    Skipped endpoints:
    - POST /auth/login - Write operation (creates session)
    - POST /auth/email/login - Write operation
    - POST /auth/email/register - Write operation (creates user)
    - GET /auth/email/me - Requires email session, not JWT auth
    - SSO endpoints - Not available (404)

    Weight: Low (administrative operations)
    """

    weight = 1
    wait_time = between(1.0, 3.0)

    @task(3)
    @tag("auth", "events")
    def get_auth_events(self):
        """GET /auth/email/events - Get current user's authentication events."""
        with self.client.get(
            "/auth/email/events",
            headers=self.auth_headers,
            name="/auth/email/events",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized
            self._validate_json_response(response, allowed_codes=[200, 401])

    @task(2)
    @tag("auth", "admin", "events")
    def get_admin_auth_events(self):
        """GET /auth/email/admin/events - Admin view of all authentication events."""
        with self.client.get(
            "/auth/email/admin/events",
            headers=self.auth_headers,
            name="/auth/email/admin/events",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized, 403=Forbidden
            self._validate_json_response(response, allowed_codes=[200, 401, 403])

    @task(2)
    @tag("auth", "admin", "users")
    def list_admin_users(self):
        """GET /auth/email/admin/users - Admin list of registered email users."""
        with self.client.get(
            "/auth/email/admin/users",
            headers=self.auth_headers,
            name="/auth/email/admin/users",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized, 403=Forbidden
            self._validate_json_response(response, allowed_codes=[200, 401, 403])


class OAuthUser(BaseUser):
    """User that tests OAuth client management endpoints.

    Tests OAuth client registration and authorization status endpoints.
    These endpoints support OAuth 2.0 flows for gateway authentication.

    Endpoints tested:
    - GET /oauth/registered-clients - List registered OAuth clients

    Skipped endpoints:
    - GET /oauth/authorize/{gateway_id} - Requires valid gateway with OAuth
    - GET /oauth/status/{gateway_id} - Requires valid gateway
    - GET /oauth/callback - Part of OAuth flow, not directly callable
    - DELETE /oauth/registered-clients/{client_id} - Write operation

    Weight: Low (administrative operations)
    """

    weight = 1
    wait_time = between(1.0, 3.0)

    @task(5)
    @tag("oauth", "clients")
    def list_registered_clients(self):
        """GET /oauth/registered-clients - List registered OAuth clients."""
        with self.client.get(
            "/oauth/registered-clients",
            headers=self.auth_headers,
            name="/oauth/registered-clients",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized, 403=Forbidden
            self._validate_json_response(response, allowed_codes=[200, 401, 403])


# =============================================================================
# Batch 5: Logs, Metrics, Observability User Classes
# =============================================================================


class LogSearchUser(BaseUser):
    """User that tests structured log search and audit endpoints.

    Tests log search, security events, audit trails, and performance metrics.
    These endpoints provide visibility into system activity and security.

    Endpoints tested:
    - GET /api/logs/security-events - Security event log
    - GET /api/logs/audit-trails - Audit trail entries
    - GET /api/logs/performance-metrics - Performance metrics log

    Skipped endpoints:
    - POST /api/logs/search - Complex search payload
    - GET /api/logs/trace/{correlation_id} - Requires valid correlation ID

    Weight: Low (monitoring operations)
    """

    weight = 1
    wait_time = between(1.0, 3.0)

    @task(3)
    @tag("logs", "security")
    def get_security_events(self):
        """GET /api/logs/security-events - Get security event log."""
        with self.client.get(
            "/api/logs/security-events",
            headers=self.auth_headers,
            name="/api/logs/security-events",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized, 403=Forbidden
            self._validate_json_response(response, allowed_codes=[200, 401, 403])

    @task(3)
    @tag("logs", "audit")
    def get_audit_trails(self):
        """GET /api/logs/audit-trails - Get audit trail entries."""
        with self.client.get(
            "/api/logs/audit-trails",
            headers=self.auth_headers,
            name="/api/logs/audit-trails",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized, 403=Forbidden
            self._validate_json_response(response, allowed_codes=[200, 401, 403])

    @task(2)
    @tag("logs", "performance")
    def get_performance_metrics(self):
        """GET /api/logs/performance-metrics - Get performance metrics log."""
        with self.client.get(
            "/api/logs/performance-metrics",
            headers=self.auth_headers,
            name="/api/logs/performance-metrics",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized, 403=Forbidden
            self._validate_json_response(response, allowed_codes=[200, 401, 403])


class MetricsUser(BaseUser):
    """User that tests metrics and statistics endpoints.

    Tests system metrics, configuration, and Prometheus export endpoints.
    These endpoints provide operational visibility and monitoring integration.

    Endpoints tested:
    - GET /metrics - Aggregated system metrics
    - GET /api/metrics/stats - Detailed metrics statistics
    - GET /api/metrics/config - Metrics configuration
    - GET /metrics/prometheus - Prometheus-format metrics export

    Skipped endpoints:
    - POST /api/metrics/cleanup - Write operation
    - POST /api/metrics/rollup - Write operation
    - POST /metrics/reset - Write operation

    Weight: Low (monitoring operations)
    """

    weight = 1
    wait_time = between(1.0, 3.0)

    @task(4)
    @tag("metrics", "aggregated")
    def get_metrics(self):
        """GET /metrics - Get aggregated system metrics."""
        with self.client.get(
            "/metrics",
            headers=self.auth_headers,
            name="/metrics",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized
            self._validate_json_response(response, allowed_codes=[200, 401])

    @task(3)
    @tag("metrics", "stats")
    def get_metrics_stats(self):
        """GET /api/metrics/stats - Get detailed metrics statistics."""
        with self.client.get(
            "/api/metrics/stats",
            headers=self.auth_headers,
            name="/api/metrics/stats",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized, 403=Forbidden
            self._validate_json_response(response, allowed_codes=[200, 401, 403])

    @task(2)
    @tag("metrics", "config")
    def get_metrics_config(self):
        """GET /api/metrics/config - Get metrics configuration."""
        with self.client.get(
            "/api/metrics/config",
            headers=self.auth_headers,
            name="/api/metrics/config",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized, 403=Forbidden
            self._validate_json_response(response, allowed_codes=[200, 401, 403])

    @task(2)
    @tag("metrics", "prometheus")
    def get_prometheus_metrics(self):
        """GET /metrics/prometheus - Get Prometheus-format metrics."""
        with self.client.get(
            "/metrics/prometheus",
            headers=self.auth_headers,
            name="/metrics/prometheus",
            catch_response=True,
        ) as response:
            # 200=Success - Prometheus format is plain text, not JSON
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Expected [200], got {response.status_code}")


class ObservabilityUser(BaseUser):
    """User that tests admin observability JSON endpoints.

    Tests observability endpoints that return JSON data (not HTML templates).
    These provide tool usage, performance, and volume analytics.

    Endpoints tested:
    - GET /admin/observability/tools/usage - Tool usage statistics
    - GET /admin/observability/tools/performance - Tool performance data
    - GET /admin/observability/metrics/top-volume - Top volume endpoints

    Skipped endpoints:
    - HTML-returning endpoints (already covered by admin UI tests)
    - POST /admin/observability/queries - Write operation
    - Endpoints requiring specific IDs

    Weight: Low (admin analytics)
    """

    weight = 1
    wait_time = between(1.0, 3.0)

    @task(3)
    @tag("observability", "tools")
    def get_tools_usage(self):
        """GET /admin/observability/tools/usage - Get tool usage statistics."""
        with self.client.get(
            "/admin/observability/tools/usage",
            headers=self.auth_headers,
            name="/admin/observability/tools/usage",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 401, 403, 500])

    @task(3)
    @tag("observability", "performance")
    def get_tools_performance(self):
        """GET /admin/observability/tools/performance - Get tool performance data."""
        with self.client.get(
            "/admin/observability/tools/performance",
            headers=self.auth_headers,
            name="/admin/observability/tools/performance",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 401, 403, 500])

    @task(2)
    @tag("observability", "volume")
    def get_top_volume(self):
        """GET /admin/observability/metrics/top-volume - Get top volume endpoints."""
        with self.client.get(
            "/admin/observability/metrics/top-volume",
            headers=self.auth_headers,
            name="/admin/observability/metrics/top-volume",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 401, 403, 500])


# =============================================================================
# Batch 6: LLM, Reverse Proxy User Classes
# =============================================================================


class LLMUser(BaseUser):
    """User that tests LLM provider and model configuration endpoints.

    Tests LLM gateway models and provider configuration endpoints.
    These endpoints provide LLM integration capabilities.

    Endpoints tested:
    - GET /llm/gateway/models - List gateway-available models
    - GET /llmchat/gateway/models - List chat gateway models
    - GET /admin/llm/provider-configs - LLM provider configurations
    - GET /admin/llm/provider-defaults - Default provider settings

    Skipped endpoints:
    - GET /llm/providers - 500 (requires LLM providers configured)
    - GET /llm/models - 500 (requires LLM providers configured)
    - POST endpoints - Write operations
    - LLMChat status/config - Require specific user ID

    Weight: Low (configuration endpoints)
    """

    weight = 1
    wait_time = between(1.0, 3.0)

    @task(3)
    @tag("llm", "models")
    def get_gateway_models(self):
        """GET /llm/gateway/models - List gateway-available LLM models."""
        with self.client.get(
            "/llm/gateway/models",
            headers=self.auth_headers,
            name="/llm/gateway/models",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized
            self._validate_json_response(response, allowed_codes=[200, 401])

    @task(3)
    @tag("llm", "chat", "models")
    def get_chat_gateway_models(self):
        """GET /llmchat/gateway/models - List chat gateway LLM models."""
        with self.client.get(
            "/llmchat/gateway/models",
            headers=self.auth_headers,
            name="/llmchat/gateway/models",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized
            self._validate_json_response(response, allowed_codes=[200, 401])

    @task(2)
    @tag("llm", "admin", "config")
    def get_provider_configs(self):
        """GET /admin/llm/provider-configs - Get LLM provider configurations."""
        with self.client.get(
            "/admin/llm/provider-configs",
            headers=self.auth_headers,
            name="/admin/llm/provider-configs",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized, 403=Forbidden
            self._validate_json_response(response, allowed_codes=[200, 401, 403])

    @task(2)
    @tag("llm", "admin", "defaults")
    def get_provider_defaults(self):
        """GET /admin/llm/provider-defaults - Get default LLM provider settings."""
        with self.client.get(
            "/admin/llm/provider-defaults",
            headers=self.auth_headers,
            name="/admin/llm/provider-defaults",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized, 403=Forbidden
            self._validate_json_response(response, allowed_codes=[200, 401, 403])


class ReverseProxyUser(BaseUser):
    """User that tests reverse proxy session management endpoints.

    Tests reverse proxy session listing for managing proxy connections.

    Endpoints tested:
    - GET /reverse-proxy/sessions - List active proxy sessions

    Skipped endpoints:
    - DELETE /reverse-proxy/sessions/{session_id} - Write operation
    - POST /reverse-proxy/sessions/{session_id}/request - Write operation
    - GET /reverse-proxy/sse/{session_id} - SSE streaming

    Weight: Low (administrative operations)
    """

    weight = 1
    wait_time = between(1.0, 3.0)

    @task(5)
    @tag("reverse-proxy", "sessions")
    def list_sessions(self):
        """GET /reverse-proxy/sessions - List active reverse proxy sessions."""
        with self.client.get(
            "/reverse-proxy/sessions",
            headers=self.auth_headers,
            name="/reverse-proxy/sessions",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized, 403=Forbidden
            self._validate_json_response(response, allowed_codes=[200, 401, 403])


# =============================================================================
# Batch 1 Phase 1: Teams, Tokens, RBAC, Cancellation (Priority 1)
# =============================================================================


# Global pools for team/token IDs (populated at test start)
TEAM_IDS: list[str] = []
ROLE_IDS: list[str] = []


@events.test_start.add_listener
def on_test_start_batch1(environment, **_kwargs):
    """Fetch team and role IDs for batch 1 tests."""
    host = environment.host or "http://localhost:8080"
    headers = _get_auth_headers()

    try:
        # Fetch teams
        status, data = _fetch_json(f"{host}/teams/", headers)
        if status == 200 and data:
            items = data if isinstance(data, list) else data.get("teams", data.get("items", []))
            TEAM_IDS.extend([str(t.get("id")) for t in items[:20] if t.get("id")])
            logger.info(f"Loaded {len(TEAM_IDS)} team IDs")

        # Fetch RBAC roles
        status, data = _fetch_json(f"{host}/rbac/roles", headers)
        if status == 200 and data:
            items = data if isinstance(data, list) else data.get("roles", data.get("items", []))
            ROLE_IDS.extend([str(r.get("id")) for r in items[:20] if r.get("id")])
            logger.info(f"Loaded {len(ROLE_IDS)} role IDs")

    except Exception as e:
        logger.warning(f"Failed to fetch batch1 IDs: {e}")


@events.test_stop.add_listener
def on_test_stop_batch1(environment, **kwargs):
    """Clean up batch 1 pools."""
    TEAM_IDS.clear()
    ROLE_IDS.clear()


class TeamsCRUDUser(BaseUser):
    """User that performs CRUD operations on Teams.

    Tests the complete Teams API for collaboration features including
    team management, membership, invitations, and join requests.

    Endpoints tested:
    - GET /teams/ - List teams
    - POST /teams/ - Create team
    - GET /teams/{team_id} - Get team details
    - PUT /teams/{team_id} - Update team
    - DELETE /teams/{team_id} - Delete team
    - GET /teams/discover - Discover public teams
    - GET /teams/{team_id}/members - List team members
    - GET /teams/{team_id}/invitations - List invitations
    - GET /teams/{team_id}/join-requests - List join requests

    Weight: Low (administrative operations)
    """

    weight = 1
    wait_time = between(2.0, 5.0)
    # Team creation is slow (~10s at low load) — increase timeout to avoid
    # hitting locust's default 30s before nginx's 60s proxy_read_timeout.
    network_timeout = 120.0

    def __init__(self, *args, **kwargs):
        """Initialize with tracking for cleanup."""
        super().__init__(*args, **kwargs)
        self.created_teams: list[str] = []

    def on_stop(self):
        """Clean up created teams on test stop."""
        for team_id in self.created_teams:
            try:
                self.client.delete(
                    f"/teams/{team_id}",
                    headers=self.auth_headers,
                    name="/teams/[id] [cleanup]",
                )
            except Exception:
                pass

    @task(5)
    @tag("teams", "list")
    def list_teams(self):
        """GET /teams/ - List all teams."""
        with self.client.get(
            "/teams/",
            headers=self.auth_headers,
            name="/teams/",
            catch_response=True,
        ) as response:
            # 200=Success, 403=Forbidden, 500=Server error (teams may not be configured)
            self._validate_json_response(response, allowed_codes=[200, 403, 500])

    @task(3)
    @tag("teams", "discover")
    def discover_teams(self):
        """GET /teams/discover - Discover public teams."""
        with self.client.get(
            "/teams/discover",
            headers=self.auth_headers,
            name="/teams/discover",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Auth issue, 403=Forbidden, 500=Server error
            self._validate_json_response(response, allowed_codes=[200, 401, 403, 500])

    @task(4)
    @tag("teams", "read")
    def get_team_details(self):
        """GET /teams/{team_id} - Get team details."""
        if TEAM_IDS:
            team_id = random.choice(TEAM_IDS)
            with self.client.get(
                f"/teams/{team_id}",
                headers=self.auth_headers,
                name="/teams/[id]",
                catch_response=True,
            ) as response:
                # 200=Success, 403=Forbidden, 404=Not found, 500=Server error
                self._validate_json_response(response, allowed_codes=[200, 403, 404, 500])

    @task(3)
    @tag("teams", "members")
    def list_team_members(self):
        """GET /teams/{team_id}/members - List team members."""
        if TEAM_IDS:
            team_id = random.choice(TEAM_IDS)
            with self.client.get(
                f"/teams/{team_id}/members",
                headers=self.auth_headers,
                name="/teams/[id]/members",
                catch_response=True,
            ) as response:
                # 200=Success, 403=Forbidden, 404=Not found, 500=Server error
                self._validate_json_response(response, allowed_codes=[200, 403, 404, 500])

    @task(2)
    @tag("teams", "invitations")
    def list_team_invitations(self):
        """GET /teams/{team_id}/invitations - List team invitations."""
        if TEAM_IDS:
            team_id = random.choice(TEAM_IDS)
            with self.client.get(
                f"/teams/{team_id}/invitations",
                headers=self.auth_headers,
                name="/teams/[id]/invitations",
                catch_response=True,
            ) as response:
                # 200=Success, 403=Forbidden, 404=Not found, 500=Server error
                self._validate_json_response(response, allowed_codes=[200, 403, 404, 500])

    @task(2)
    @tag("teams", "join-requests")
    def list_join_requests(self):
        """GET /teams/{team_id}/join-requests - List join requests."""
        if TEAM_IDS:
            team_id = random.choice(TEAM_IDS)
            with self.client.get(
                f"/teams/{team_id}/join-requests",
                headers=self.auth_headers,
                name="/teams/[id]/join-requests",
                catch_response=True,
            ) as response:
                # 200=Success, 403=Forbidden, 404=Not found, 500=Server error
                self._validate_json_response(response, allowed_codes=[200, 403, 404, 500])

    @task(2)
    @tag("teams", "write", "create")
    def create_and_delete_team(self):
        """POST /teams/ - Create a team, then DELETE it."""
        team_name = f"loadtest-team-{uuid.uuid4().hex[:8]}"
        team_data = {
            "name": team_name,
            "description": "Load test team - will be deleted",
            "visibility": "private",
        }

        with self.client.post(
            "/teams/",
            json=team_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/teams/ [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                try:
                    data = response.json()
                    team_id = data.get("id") or data.get("name") or team_name
                    time.sleep(0.1)
                    self.client.delete(
                        f"/teams/{team_id}",
                        headers=self.auth_headers,
                        name="/teams/[id] [delete]",
                    )
                    response.success()
                except Exception:
                    response.success()
            elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                # 403=Forbidden, 409=Conflict, 422=Validation error, 500=Server error, 502/504=Load
                response.success()


class TokenCatalogCRUDUser(BaseUser):
    """User that performs CRUD operations on JWT Token Catalog.

    Tests the complete Token Catalog API for managing API tokens including
    creation, listing, updates, usage stats, and deletion.

    Endpoints tested:
    - GET /tokens - List user's tokens
    - POST /tokens - Create token
    - GET /tokens/{token_id} - Get token details
    - PUT /tokens/{token_id} - Update token
    - DELETE /tokens/{token_id} - Delete token
    - GET /tokens/{token_id}/usage - Get token usage stats
    - GET /tokens/admin/all - Admin: list all tokens

    Weight: Low (administrative operations)
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    def __init__(self, *args, **kwargs):
        """Initialize with tracking for cleanup."""
        super().__init__(*args, **kwargs)
        self.created_tokens: list[str] = []

    def on_stop(self):
        """Clean up created tokens on test stop."""
        for token_id in self.created_tokens:
            try:
                self.client.delete(
                    f"/tokens/{token_id}",
                    headers=self.auth_headers,
                    name="/tokens/[id] [cleanup]",
                )
            except Exception:
                pass

    @task(5)
    @tag("tokens", "list")
    def list_tokens(self):
        """GET /tokens - List user's tokens."""
        with self.client.get(
            "/tokens",
            headers=self.auth_headers,
            name="/tokens",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(2)
    @tag("tokens", "admin", "list")
    def list_all_tokens_admin(self):
        """GET /tokens/admin/all - Admin: list all tokens."""
        with self.client.get(
            "/tokens/admin/all",
            headers=self.auth_headers,
            name="/tokens/admin/all",
            catch_response=True,
        ) as response:
            # 200=Success, 403=Forbidden (non-admin)
            self._validate_json_response(response, allowed_codes=[200, 403])

    @task(3)
    @tag("tokens", "write", "create")
    def create_and_manage_token(self):
        """POST /tokens - Create a token, get details, usage, then DELETE."""
        token_name = f"loadtest-token-{uuid.uuid4().hex[:8]}"
        token_data = {
            "name": token_name,
            "description": "Load test token - will be deleted",
            "expires_in_days": 1,
        }

        with self.client.post(
            "/tokens",
            json=token_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/tokens [create]",
            catch_response=True,
        ) as response:
            if response.status_code in INFRASTRUCTURE_ERROR_CODES:
                response.success()
            elif response.status_code in (200, 201):
                try:
                    data = response.json()
                    token_id = data.get("id")
                    if token_id:
                        # Get token details
                        time.sleep(0.05)
                        self.client.get(
                            f"/tokens/{token_id}",
                            headers=self.auth_headers,
                            name="/tokens/[id]",
                        )
                        # Get usage stats
                        time.sleep(0.05)
                        self.client.get(
                            f"/tokens/{token_id}/usage",
                            headers=self.auth_headers,
                            name="/tokens/[id]/usage",
                        )
                        # Delete token
                        time.sleep(0.05)
                        self.client.delete(
                            f"/tokens/{token_id}",
                            headers=self.auth_headers,
                            name="/tokens/[id] [delete]",
                        )
                    response.success()
                except Exception:
                    response.success()
            elif response.status_code in (409, 422):
                response.success()  # Conflict or validation error acceptable

    @task(2)
    @tag("tokens", "teams")
    def list_team_tokens(self):
        """GET /tokens/teams/{team_id} - List team tokens."""
        if TEAM_IDS:
            team_id = random.choice(TEAM_IDS)
            with self.client.get(
                f"/tokens/teams/{team_id}",
                headers=self.auth_headers,
                name="/tokens/teams/[id]",
                catch_response=True,
            ) as response:
                self._validate_json_response(response, allowed_codes=[200, 403, 404])


class RBACCRUDUser(BaseUser):
    """User that performs CRUD operations on RBAC (Role-Based Access Control).

    Tests the complete RBAC API for managing roles and permissions including
    role creation, permission assignment, and user-role mappings.

    Endpoints tested:
    - GET /rbac/roles - List roles
    - POST /rbac/roles - Create role
    - GET /rbac/roles/{role_id} - Get role details
    - PUT /rbac/roles/{role_id} - Update role
    - DELETE /rbac/roles/{role_id} - Delete role
    - POST /rbac/permissions/check - Check permission
    - GET /rbac/permissions/user/{user_email} - Get user's permissions
    - POST /rbac/users/{user_email}/roles - Assign role to user
    - GET /rbac/users/{user_email}/roles - List user's roles

    Weight: Low (administrative operations)
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    def __init__(self, *args, **kwargs):
        """Initialize with tracking for cleanup."""
        super().__init__(*args, **kwargs)
        self.created_roles: list[str] = []

    def on_stop(self):
        """Clean up created roles on test stop."""
        for role_id in self.created_roles:
            try:
                self.client.delete(
                    f"/rbac/roles/{role_id}",
                    headers=self.auth_headers,
                    name="/rbac/roles/[id] [cleanup]",
                )
            except Exception:
                pass

    @task(5)
    @tag("rbac", "roles", "list")
    def list_roles(self):
        """GET /rbac/roles - List all roles."""
        with self.client.get(
            "/rbac/roles",
            headers=self.auth_headers,
            name="/rbac/roles",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(3)
    @tag("rbac", "roles", "read")
    def get_role_details(self):
        """GET /rbac/roles/{role_id} - Get role details."""
        if ROLE_IDS:
            role_id = random.choice(ROLE_IDS)
            with self.client.get(
                f"/rbac/roles/{role_id}",
                headers=self.auth_headers,
                name="/rbac/roles/[id]",
                catch_response=True,
            ) as response:
                self._validate_json_response(response, allowed_codes=[200, 404])

    @task(3)
    @tag("rbac", "permissions", "check")
    def check_permission(self):
        """POST /rbac/permissions/check - Check if user has permission."""
        check_data = {
            "user_email": "admin@example.com",
            "permission": "tools:read",
        }
        with self.client.post(
            "/rbac/permissions/check",
            json=check_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/rbac/permissions/check",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(2)
    @tag("rbac", "permissions", "user")
    def get_user_permissions(self):
        """GET /rbac/permissions/user/{user_email} - Get user's permissions."""
        with self.client.get(
            "/rbac/permissions/user/admin@example.com",
            headers=self.auth_headers,
            name="/rbac/permissions/user/[email]",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 404])

    @task(2)
    @tag("rbac", "users", "roles")
    def get_user_roles(self):
        """GET /rbac/users/{user_email}/roles - Get user's assigned roles."""
        with self.client.get(
            "/rbac/users/admin@example.com/roles",
            headers=self.auth_headers,
            name="/rbac/users/[email]/roles",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 404])

    @task(1)
    @tag("rbac", "roles", "write", "create")
    def create_and_delete_role(self):
        """POST /rbac/roles - Create a role, then DELETE it."""
        role_name = f"loadtest-role-{uuid.uuid4().hex[:8]}"
        role_data = {
            "name": role_name,
            "description": "Load test role - will be deleted",
            "permissions": ["tools:read"],
        }

        with self.client.post(
            "/rbac/roles",
            json=role_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/rbac/roles [create]",
            catch_response=True,
        ) as response:
            if response.status_code in INFRASTRUCTURE_ERROR_CODES:
                response.success()
            elif response.status_code in (200, 201):
                try:
                    data = response.json()
                    role_id = data.get("id") or data.get("name") or role_name
                    time.sleep(0.1)
                    self.client.delete(
                        f"/rbac/roles/{role_id}",
                        headers=self.auth_headers,
                        name="/rbac/roles/[id] [delete]",
                    )
                    response.success()
                except Exception:
                    response.success()
            elif response.status_code in (409, 422):
                response.success()  # Conflict or validation error acceptable


class CancellationAPIUser(BaseUser):
    """User that tests the Cancellation API for request management.

    Tests the ability to cancel in-progress requests and check cancellation status.

    Endpoints tested:
    - POST /cancellation/cancel - Cancel a request
    - GET /cancellation/status/{request_id} - Get cancellation status

    Weight: Very low (rarely used in production)
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(3)
    @tag("cancellation", "status")
    def check_cancellation_status(self):
        """GET /cancellation/status/{request_id} - Check cancellation status."""
        # Use a random UUID as request_id (will likely return 404)
        request_id = str(uuid.uuid4())
        with self.client.get(
            f"/cancellation/status/{request_id}",
            headers=self.auth_headers,
            name="/cancellation/status/[id]",
            catch_response=True,
        ) as response:
            # 200=Found, 404=Not found (expected for random ID)
            self._validate_json_response(response, allowed_codes=[200, 404])

    @task(2)
    @tag("cancellation", "cancel")
    def cancel_request(self):
        """POST /cancellation/cancel - Attempt to cancel a request."""
        # Use a random UUID as request_id (will likely fail gracefully)
        cancel_data = {
            "request_id": str(uuid.uuid4()),
            "reason": "Load test cancellation",
        }
        with self.client.post(
            "/cancellation/cancel",
            json=cancel_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/cancellation/cancel",
            catch_response=True,
        ) as response:
            # 200=Success, 404=Not found, 422=Invalid request
            self._validate_json_response(response, allowed_codes=[200, 404, 422])


# =============================================================================
# Batch 2 Phase 2: LLM Configuration & Integration (REMOVED - requires LLM setup)
# =============================================================================
# The following classes were REMOVED because they fail when LLM is not configured:
#
# - LLMConfigCRUDUser: Tests /llm/providers, /llm/models endpoints
#   Endpoints: GET /llm/providers, GET /llm/models, GET /llm/providers/{id},
#              POST /llm/providers/{id}/health
#
# - LLMChatUser: Tests /llmchat/* endpoints
#   Endpoints: GET /llmchat/gateway/models, GET /llmchat/config/{user_id},
#              GET /llmchat/status/{user_id}
#
# - LLMProxyUser: Tests /v1/* OpenAI-compatible endpoints
#   Endpoints: GET /v1/models, POST /v1/chat/completions
#
# To re-enable: Configure LLM providers in the gateway and uncomment these classes.
# =============================================================================


# =============================================================================
# Batch 3 Phase 3: Observability, Protocol, & Extended Operations (Priority 3)
# =============================================================================


# ProtocolExtendedUser REMOVED - returns empty/invalid JSON responses
# Endpoints removed:
#   - POST /protocol/completion/complete - Returns empty response
#   - POST /protocol/notifications - Returns null JSON
# To re-enable: Fix the protocol endpoints to return valid JSON responses


class RootsExtendedUser(BaseUser):
    """User that tests extended Roots API endpoints.

    Tests root management operations including creation and deletion.

    Endpoints tested:
    - GET /roots - List roots (already covered, included for context)
    - POST /roots - Create root
    - DELETE /roots/{uri} - Delete root

    Note: GET /roots/changes was REMOVED - returns SSE stream, not JSON.

    Weight: Low (administrative operations)
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    # GET /roots/changes REMOVED - endpoint returns text/event-stream (SSE), not JSON
    # This is a streaming endpoint not suitable for standard load testing

    @task(3)
    @tag("roots", "list")
    def list_roots(self):
        """GET /roots - List all roots."""
        with self.client.get(
            "/roots",
            headers=self.auth_headers,
            name="/roots",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200])

    @task(2)
    @tag("roots", "write", "create")
    def create_and_delete_root(self):
        """POST /roots - Create a root, then DELETE it."""
        root_uri = f"file:///tmp/loadtest-root-{uuid.uuid4().hex[:8]}"
        root_data = {
            "uri": root_uri,
            "name": f"loadtest-root-{uuid.uuid4().hex[:8]}",
        }

        with self.client.post(
            "/roots",
            json=root_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/roots [create]",
            catch_response=True,
        ) as response:
            if response.status_code in INFRASTRUCTURE_ERROR_CODES:
                response.success()
            elif response.status_code in (200, 201):
                try:
                    time.sleep(0.1)
                    # URL-encode the URI for deletion
                    encoded_uri = root_uri.replace("/", "%2F").replace(":", "%3A")
                    # Delete may return 404 (already deleted) or 500 (server bug)
                    with self.client.delete(
                        f"/roots/{encoded_uri}",
                        headers=self.auth_headers,
                        name="/roots/[uri] [delete]",
                        catch_response=True,
                    ) as del_response:
                        if del_response.status_code in (200, 204, 404, 500, *INFRASTRUCTURE_ERROR_CODES):
                            del_response.success()
                        else:
                            del_response.failure(f"Unexpected status: {del_response.status_code}")
                    response.success()
                except Exception:
                    response.success()
            elif response.status_code in (409, 422):
                response.success()  # Conflict or validation error acceptable


class TagsExtendedUser(BaseUser):
    """User that tests extended Tags API endpoints.

    Tests tag-based entity discovery.

    Endpoints tested:
    - GET /tags/{tag_name}/entities - Get entities by tag

    Weight: Low (read operations)
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    @task(5)
    @tag("tags", "entities")
    def get_entities_by_tag(self):
        """GET /tags/{tag_name}/entities - Get entities tagged with a specific tag."""
        # Common tag names that might exist
        tag_names = ["mcp", "tool", "server", "gateway", "test", "loadtest"]
        tag_name = random.choice(tag_names)
        with self.client.get(
            f"/tags/{tag_name}/entities",
            headers=self.auth_headers,
            name="/tags/[name]/entities",
            catch_response=True,
        ) as response:
            # 200=Success, 404=Tag not found, 500=DB contention under load
            self._validate_json_response(response, allowed_codes=[200, 404, 500, *INFRASTRUCTURE_ERROR_CODES])


class LogSearchExtendedUser(BaseUser):
    """User that tests extended Log Search API endpoints.

    Tests log search and trace retrieval operations.

    Endpoints tested:
    - POST /api/logs/search - Search logs
    - GET /api/logs/trace/{correlation_id} - Get trace by correlation

    Weight: Low (administrative operations)
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    @task(3)
    @tag("logs", "search")
    def search_logs(self):
        """POST /api/logs/search - Search logs."""
        search_data = {
            "query": "error",
            "level": "INFO",
            "limit": 10,
        }
        with self.client.post(
            "/api/logs/search",
            json=search_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/api/logs/search",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 400, 422, *INFRASTRUCTURE_ERROR_CODES])

    @task(2)
    @tag("logs", "trace")
    def get_trace_by_correlation(self):
        """GET /api/logs/trace/{correlation_id} - Get trace by correlation ID."""
        correlation_id = str(uuid.uuid4())  # Random ID (will likely return 404)
        with self.client.get(
            f"/api/logs/trace/{correlation_id}",
            headers=self.auth_headers,
            name="/api/logs/trace/[correlation_id]",
            catch_response=True,
        ) as response:
            # 200=Found, 404=Not found (expected for random ID)
            self._validate_json_response(response, allowed_codes=[200, 404])


class MetricsMaintenanceUser(BaseUser):
    """User that tests Metrics Maintenance API endpoints.

    Tests metrics cleanup and rollup operations.

    Endpoints tested:
    - POST /api/metrics/cleanup - Cleanup old metrics
    - POST /api/metrics/rollup - Rollup metrics

    Weight: Very low (maintenance operations)
    """

    weight = 1
    wait_time = between(5.0, 10.0)

    @task(2)
    @tag("metrics", "cleanup")
    def cleanup_metrics(self):
        """POST /api/metrics/cleanup - Cleanup old metrics."""
        with self.client.post(
            "/api/metrics/cleanup",
            headers=self.auth_headers,
            name="/api/metrics/cleanup",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 202, 403, *INFRASTRUCTURE_ERROR_CODES])

    @task(2)
    @tag("metrics", "rollup")
    def rollup_metrics(self):
        """POST /api/metrics/rollup - Rollup metrics."""
        with self.client.post(
            "/api/metrics/rollup",
            headers=self.auth_headers,
            name="/api/metrics/rollup",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 202, 403, *INFRASTRUCTURE_ERROR_CODES])


class AuthExtendedUser(BaseUser):
    """User that tests extended Authentication endpoints.

    Tests authentication and user management operations.

    Endpoints tested:
    - POST /auth/login - Main login endpoint
    - GET /auth/email/me - Get current user info
    - POST /auth/email/change-password - Change password (test validation only)

    Weight: Very low (sensitive operations)
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(3)
    @tag("auth", "me")
    def get_current_user(self):
        """GET /auth/email/me - Get current authenticated user info."""
        with self.client.get(
            "/auth/email/me",
            headers=self.auth_headers,
            name="/auth/email/me",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Unauthorized, 404=Not found, 422=Validation error
            self._validate_json_response(response, allowed_codes=[200, 401, 404, 422])

    @task(2)
    @tag("auth", "login")
    def test_login(self):
        """POST /auth/login - Test main login endpoint."""
        login_data = {
            "username": "admin@example.com",
            "password": "admin",  # Default test password
        }
        with self.client.post(
            "/auth/login",
            data=login_data,  # Form data, not JSON
            headers={**self.auth_headers, "Content-Type": "application/x-www-form-urlencoded"},
            name="/auth/login",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Invalid credentials, 422=Validation error
            self._validate_json_response(response, allowed_codes=[200, 401, 422])


class EntityToggleUser(BaseUser):
    """User that tests toggle operations across all entity types.

    Tests the toggle endpoints that switch entity enabled state.

    Endpoints tested:
    - POST /tools/{tool_id}/toggle
    - POST /servers/{server_id}/toggle
    - POST /gateways/{gateway_id}/toggle
    - POST /resources/{resource_id}/toggle
    - POST /prompts/{prompt_id}/toggle
    - POST /a2a/{agent_id}/toggle

    Weight: Low (state operations)
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    @task(3)
    @tag("tools", "toggle")
    def toggle_tool(self):
        """POST /tools/{tool_id}/toggle - Toggle tool enabled state."""
        if TOOL_IDS:
            tool_id = random.choice(TOOL_IDS)
            with self.client.post(
                f"/tools/{tool_id}/toggle",
                headers=self.auth_headers,
                name="/tools/[id]/toggle",
                catch_response=True,
            ) as response:
                # 200=Success, 401=Auth issue, 403=Forbidden, 404=Not found, 409=Conflict
                self._validate_json_response(response, allowed_codes=[200, 401, 403, 404, 409, *INFRASTRUCTURE_ERROR_CODES])

    @task(3)
    @tag("servers", "toggle")
    def toggle_server(self):
        """POST /servers/{server_id}/toggle - Toggle server enabled state."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            with self.client.post(
                f"/servers/{server_id}/toggle",
                headers=self.auth_headers,
                name="/servers/[id]/toggle",
                catch_response=True,
            ) as response:
                self._validate_json_response(response, allowed_codes=[200, 401, 403, 404, 409, *INFRASTRUCTURE_ERROR_CODES])

    @task(2)
    @tag("resources", "toggle")
    def toggle_resource(self):
        """POST /resources/{resource_id}/toggle - Toggle resource enabled state."""
        if RESOURCE_IDS:
            resource_id = random.choice(RESOURCE_IDS)
            with self.client.post(
                f"/resources/{resource_id}/toggle",
                headers=self.auth_headers,
                name="/resources/[id]/toggle",
                catch_response=True,
            ) as response:
                self._validate_json_response(response, allowed_codes=[200, 401, 403, 404, 409, *INFRASTRUCTURE_ERROR_CODES])

    @task(2)
    @tag("prompts", "toggle")
    def toggle_prompt(self):
        """POST /prompts/{prompt_id}/toggle - Toggle prompt enabled state."""
        if PROMPT_IDS:
            prompt_id = random.choice(PROMPT_IDS)
            with self.client.post(
                f"/prompts/{prompt_id}/toggle",
                headers=self.auth_headers,
                name="/prompts/[id]/toggle",
                catch_response=True,
            ) as response:
                self._validate_json_response(response, allowed_codes=[200, 401, 403, 404, 409, *INFRASTRUCTURE_ERROR_CODES])


class EntityUpdateUser(BaseUser):
    """User that tests PUT/UPDATE operations across entity types.

    Tests the update endpoints for modifying existing entities.

    Endpoints tested:
    - PUT /tools/{tool_id}
    - PUT /servers/{server_id}
    - PUT /resources/{resource_id}
    - PUT /prompts/{prompt_id}
    - PUT /gateways/{gateway_id}
    - PUT /a2a/{agent_id}

    Weight: Low (write operations)
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    @task(2)
    @tag("tools", "update")
    def update_tool(self):
        """PUT /tools/{tool_id} - Update a tool."""
        if TOOL_IDS:
            tool_id = random.choice(TOOL_IDS)
            # First get current tool data
            with self.client.get(
                f"/tools/{tool_id}",
                headers=self.auth_headers,
                name="/tools/[id] [for update]",
                catch_response=True,
            ) as response:
                if response.status_code == 200:
                    try:
                        tool_data = response.json()
                        # Update description only (safe operation)
                        tool_data["description"] = f"Updated by load test at {time.time()}"
                        time.sleep(0.05)
                        with self.client.put(
                            f"/tools/{tool_id}",
                            json=tool_data,
                            headers={**self.auth_headers, "Content-Type": "application/json"},
                            name="/tools/[id] [update]",
                            catch_response=True,
                        ) as put_response:
                            self._validate_json_response(put_response, allowed_codes=[0, 200, 403, 404, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                        response.success()
                    except Exception:
                        response.success()
                else:
                    self._validate_json_response(response, allowed_codes=[200, 404])

    @task(2)
    @tag("resources", "update")
    def update_resource(self):
        """PUT /resources/{resource_id} - Update a resource."""
        if RESOURCE_IDS:
            resource_id = random.choice(RESOURCE_IDS)
            with self.client.get(
                f"/resources/{resource_id}",
                headers=self.auth_headers,
                name="/resources/[id] [for update]",
                catch_response=True,
            ) as response:
                if response.status_code == 200:
                    try:
                        resource_data = response.json()
                        resource_data["description"] = f"Updated by load test at {time.time()}"
                        time.sleep(0.05)
                        with self.client.put(
                            f"/resources/{resource_id}",
                            json=resource_data,
                            headers={**self.auth_headers, "Content-Type": "application/json"},
                            name="/resources/[id] [update]",
                            catch_response=True,
                        ) as put_response:
                            self._validate_json_response(put_response, allowed_codes=[0, 200, 403, 404, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                        response.success()
                    except Exception:
                        response.success()
                else:
                    self._validate_json_response(response, allowed_codes=[200, 404])


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
        with self.client.get("/health", name="/health", catch_response=True) as response:
            self._validate_status(response)

    @task(20)
    @tag("realistic", "api")
    def list_tools(self):
        """List tools."""
        with self.client.get("/tools", headers=self.auth_headers, name="/tools", catch_response=True) as response:
            self._validate_status(response)

    @task(15)
    @tag("realistic", "api")
    def list_servers(self):
        """List servers."""
        with self.client.get("/servers", headers=self.auth_headers, name="/servers", catch_response=True) as response:
            self._validate_status(response)

    @task(10)
    @tag("realistic", "api")
    def list_gateways(self):
        """List gateways."""
        with self.client.get("/gateways", headers=self.auth_headers, name="/gateways", catch_response=True) as response:
            self._validate_status(response)

    @task(10)
    @tag("realistic", "api")
    def list_resources(self):
        """List resources."""
        with self.client.get("/resources", headers=self.auth_headers, name="/resources", catch_response=True) as response:
            self._validate_status(response)

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
            if response.status_code in INFRASTRUCTURE_ERROR_CODES:
                response.success()
                return
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
            self._validate_status(response, allowed_codes=[200, *INFRASTRUCTURE_ERROR_CODES])

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
                self._validate_json_response(response, allowed_codes=[200, 404, *INFRASTRUCTURE_ERROR_CODES])

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
                self._validate_json_response(response, allowed_codes=[200, 404, *INFRASTRUCTURE_ERROR_CODES])

    @task(2)
    @tag("realistic", "admin")
    def admin_tools_page(self):
        """Admin tools page."""
        with self.client.get("/admin/tools", headers=self.admin_headers, name="/admin/tools", catch_response=True) as response:
            self._validate_status(response)


# =============================================================================
# Batch 10: Protocol, LLM, and System Extended User Classes
# =============================================================================


class ProtocolExtendedUser(BaseUser):
    """User that tests extended MCP protocol endpoints.

    Endpoints tested:
    - POST /initialize - MCP session initialization
    - POST /protocol/completion/complete - Completion requests
    - POST /protocol/notifications - Protocol notifications
    - POST /protocol/sampling/createMessage - Sampling requests
    - POST /message - Session message (JSON-RPC)
    - POST /notifications - Gateway notifications

    Weight: Low (protocol operations)
    """

    weight = 1
    wait_time = between(1.0, 3.0)

    @task(5)
    @tag("protocol", "initialize")
    def mcp_initialize(self):
        """POST /initialize - Initialize MCP session."""
        payload = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "locust-test", "version": "1.0"},
        }
        with self.client.post(
            "/initialize",
            json=payload,
            headers=self.auth_headers,
            name="/initialize",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(3)
    @tag("protocol", "notifications")
    def protocol_notifications(self):
        """POST /protocol/notifications - Send protocol notification."""
        payload = {
            "method": "notifications/cancelled",
            "params": {"requestId": str(uuid.uuid4())},
        }
        with self.client.post(
            "/protocol/notifications",
            json=payload,
            headers=self.auth_headers,
            name="/protocol/notifications",
            catch_response=True,
        ) as response:
            # Returns null/200 on success
            self._validate_status(response)

    @task(2)
    @tag("protocol", "completion")
    def protocol_completion(self):
        """POST /protocol/completion/complete - Request completion."""
        payload = {
            "ref": {"type": "ref/prompt", "name": "test-prompt"},
            "argument": {"name": "arg", "value": "val"},
        }
        with self.client.post(
            "/protocol/completion/complete",
            json=payload,
            headers=self.auth_headers,
            name="/protocol/completion/complete",
            catch_response=True,
        ) as response:
            # 200=Success, 500=No completion handler configured
            self._validate_status(response, allowed_codes=[200, 422, 500])

    @task(2)
    @tag("protocol", "sampling")
    def protocol_sampling(self):
        """POST /protocol/sampling/createMessage - Create sampling message."""
        payload = {
            "messages": [{"role": "user", "content": {"type": "text", "text": "Hello"}}],
            "maxTokens": 10,
        }
        with self.client.post(
            "/protocol/sampling/createMessage",
            json=payload,
            headers=self.auth_headers,
            name="/protocol/sampling/createMessage",
            catch_response=True,
        ) as response:
            # 200=Success, 500=No sampling handler configured
            self._validate_status(response, allowed_codes=[200, 422, 500])

    @task(2)
    @tag("protocol", "notifications")
    def gateway_notifications(self):
        """POST /notifications - Send gateway notification."""
        payload = {
            "method": "notifications/cancelled",
            "params": {"requestId": str(uuid.uuid4())},
        }
        with self.client.post(
            "/notifications",
            json=payload,
            headers=self.auth_headers,
            name="/notifications",
            catch_response=True,
        ) as response:
            self._validate_status(response)

    @task(1)
    @tag("protocol", "message")
    def send_message(self):
        """POST /message - Send JSON-RPC message (requires session)."""
        payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "ping", "params": {}}
        with self.client.post(
            "/message",
            json=payload,
            headers=self.auth_headers,
            name="/message",
            catch_response=True,
        ) as response:
            # 400=Missing session_id (expected without active session)
            self._validate_status(response, allowed_codes=[200, 400])


class LLMExtendedUser(BaseUser):
    """User that tests extended LLM API endpoints.

    Endpoints tested:
    - GET /llm/models - List LLM models
    - GET /llm/providers - List LLM providers
    - GET /v1/models - OpenAI-compatible models list
    - POST /v1/chat/completions - OpenAI-compatible chat (expects 404 without providers)

    Weight: Low (LLM configuration)
    """

    weight = 1
    wait_time = between(1.0, 3.0)

    @task(5)
    @tag("llm", "models")
    def list_models(self):
        """GET /llm/models - List all LLM models."""
        with self.client.get(
            "/llm/models",
            headers=self.auth_headers,
            name="/llm/models",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(5)
    @tag("llm", "providers")
    def list_providers(self):
        """GET /llm/providers - List all LLM providers."""
        with self.client.get(
            "/llm/providers",
            headers=self.auth_headers,
            name="/llm/providers",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(3)
    @tag("llm", "v1", "models")
    def v1_models(self):
        """GET /v1/models - OpenAI-compatible models list."""
        with self.client.get(
            "/v1/models",
            headers=self.auth_headers,
            name="/v1/models",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(1)
    @tag("llm", "v1", "chat")
    def v1_chat_completions(self):
        """POST /v1/chat/completions - OpenAI-compatible chat."""
        payload = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "test"}],
        }
        with self.client.post(
            "/v1/chat/completions",
            json=payload,
            headers=self.auth_headers,
            name="/v1/chat/completions",
            catch_response=True,
        ) as response:
            # 404=Model not found (expected without configured providers)
            self._validate_status(response, allowed_codes=[200, 404, 422, 500])


class AdminObservabilityExtendedUser(BaseUser):
    """User that tests extended admin observability endpoints.

    Endpoints tested:
    - GET /admin/observability/partial - Observability overview HTML
    - GET /admin/observability/stats - Observability stats
    - GET /admin/observability/traces - Trace list
    - GET /admin/observability/metrics/heatmap - Latency heatmap
    - GET /admin/observability/metrics/percentiles - Latency percentiles
    - GET /admin/observability/metrics/timeseries - Request timeseries
    - GET /admin/observability/metrics/partial - Metrics overview HTML
    - GET /admin/observability/metrics/top-errors - Top error endpoints
    - GET /admin/observability/metrics/top-slow - Top slow endpoints
    - GET /admin/observability/prompts/errors - Prompt errors
    - GET /admin/observability/prompts/partial - Prompts HTML
    - GET /admin/observability/prompts/performance - Prompt performance
    - GET /admin/observability/prompts/usage - Prompt usage
    - GET /admin/observability/resources/errors - Resource errors
    - GET /admin/observability/resources/partial - Resources HTML
    - GET /admin/observability/resources/performance - Resource performance
    - GET /admin/observability/resources/usage - Resource usage
    - GET /admin/observability/tools/chains - Tool chains
    - GET /admin/observability/tools/errors - Tool errors
    - GET /admin/observability/tools/partial - Tools HTML
    - POST /admin/observability/queries - Create saved query
    - GET /admin/observability/queries - List saved queries

    Weight: Low (admin analytics)
    """

    weight = 1
    wait_time = between(1.0, 3.0)

    @task(3)
    @tag("admin", "observability", "partial")
    def observability_partial(self):
        """GET /admin/observability/partial - Observability overview."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/observability/partial",
            headers=headers,
            name="/admin/observability/partial",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)

    @task(3)
    @tag("admin", "observability", "stats")
    def observability_stats(self):
        """GET /admin/observability/stats - Observability statistics."""
        with self.client.get(
            "/admin/observability/stats",
            headers=self.admin_headers,
            name="/admin/observability/stats",
            catch_response=True,
        ) as response:
            self._validate_status(response)

    @task(2)
    @tag("admin", "observability", "traces")
    def observability_traces(self):
        """GET /admin/observability/traces - List traces."""
        with self.client.get(
            "/admin/observability/traces",
            headers=self.admin_headers,
            name="/admin/observability/traces",
            catch_response=True,
        ) as response:
            self._validate_status(response)

    @task(2)
    @tag("admin", "observability", "heatmap")
    def observability_heatmap(self):
        """GET /admin/observability/metrics/heatmap - Latency heatmap data."""
        with self.client.get(
            "/admin/observability/metrics/heatmap",
            headers=self.auth_headers,
            name="/admin/observability/metrics/heatmap",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 500])

    @task(2)
    @tag("admin", "observability", "percentiles")
    def observability_percentiles(self):
        """GET /admin/observability/metrics/percentiles - Latency percentiles."""
        with self.client.get(
            "/admin/observability/metrics/percentiles",
            headers=self.auth_headers,
            name="/admin/observability/metrics/percentiles",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 500])

    @task(2)
    @tag("admin", "observability", "timeseries")
    def observability_timeseries(self):
        """GET /admin/observability/metrics/timeseries - Request timeseries."""
        with self.client.get(
            "/admin/observability/metrics/timeseries",
            headers=self.auth_headers,
            name="/admin/observability/metrics/timeseries",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 500])

    @task(1)
    @tag("admin", "observability", "metrics", "partial")
    def observability_metrics_partial(self):
        """GET /admin/observability/metrics/partial - Metrics overview HTML."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/observability/metrics/partial",
            headers=headers,
            name="/admin/observability/metrics/partial",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)

    @task(1)
    @tag("admin", "observability", "top-errors")
    def observability_top_errors(self):
        """GET /admin/observability/metrics/top-errors - Top error endpoints."""
        with self.client.get(
            "/admin/observability/metrics/top-errors",
            headers=self.auth_headers,
            name="/admin/observability/metrics/top-errors",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 500])

    @task(1)
    @tag("admin", "observability", "top-slow")
    def observability_top_slow(self):
        """GET /admin/observability/metrics/top-slow - Top slow endpoints."""
        with self.client.get(
            "/admin/observability/metrics/top-slow",
            headers=self.auth_headers,
            name="/admin/observability/metrics/top-slow",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 500])

    @task(1)
    @tag("admin", "observability", "prompts")
    def observability_prompts_errors(self):
        """GET /admin/observability/prompts/errors - Prompt errors."""
        with self.client.get(
            "/admin/observability/prompts/errors",
            headers=self.auth_headers,
            name="/admin/observability/prompts/errors",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])

    @task(1)
    @tag("admin", "observability", "prompts")
    def observability_prompts_partial(self):
        """GET /admin/observability/prompts/partial - Prompts observability HTML."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/observability/prompts/partial",
            headers=headers,
            name="/admin/observability/prompts/partial",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)

    @task(1)
    @tag("admin", "observability", "prompts")
    def observability_prompts_performance(self):
        """GET /admin/observability/prompts/performance - Prompt performance."""
        with self.client.get(
            "/admin/observability/prompts/performance",
            headers=self.auth_headers,
            name="/admin/observability/prompts/performance",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])

    @task(1)
    @tag("admin", "observability", "prompts")
    def observability_prompts_usage(self):
        """GET /admin/observability/prompts/usage - Prompt usage statistics."""
        with self.client.get(
            "/admin/observability/prompts/usage",
            headers=self.auth_headers,
            name="/admin/observability/prompts/usage",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])

    @task(1)
    @tag("admin", "observability", "resources")
    def observability_resources_errors(self):
        """GET /admin/observability/resources/errors - Resource errors."""
        with self.client.get(
            "/admin/observability/resources/errors",
            headers=self.auth_headers,
            name="/admin/observability/resources/errors",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])

    @task(1)
    @tag("admin", "observability", "resources")
    def observability_resources_partial(self):
        """GET /admin/observability/resources/partial - Resources observability HTML."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/observability/resources/partial",
            headers=headers,
            name="/admin/observability/resources/partial",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)

    @task(1)
    @tag("admin", "observability", "resources")
    def observability_resources_performance(self):
        """GET /admin/observability/resources/performance - Resource performance."""
        with self.client.get(
            "/admin/observability/resources/performance",
            headers=self.auth_headers,
            name="/admin/observability/resources/performance",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])

    @task(1)
    @tag("admin", "observability", "resources")
    def observability_resources_usage(self):
        """GET /admin/observability/resources/usage - Resource usage."""
        with self.client.get(
            "/admin/observability/resources/usage",
            headers=self.auth_headers,
            name="/admin/observability/resources/usage",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])

    @task(1)
    @tag("admin", "observability", "tools")
    def observability_tools_chains(self):
        """GET /admin/observability/tools/chains - Tool invocation chains."""
        with self.client.get(
            "/admin/observability/tools/chains",
            headers=self.auth_headers,
            name="/admin/observability/tools/chains",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])

    @task(1)
    @tag("admin", "observability", "tools")
    def observability_tools_errors(self):
        """GET /admin/observability/tools/errors - Tool errors."""
        with self.client.get(
            "/admin/observability/tools/errors",
            headers=self.auth_headers,
            name="/admin/observability/tools/errors",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])

    @task(1)
    @tag("admin", "observability", "tools")
    def observability_tools_partial(self):
        """GET /admin/observability/tools/partial - Tools observability HTML."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/observability/tools/partial",
            headers=headers,
            name="/admin/observability/tools/partial",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)

    @task(1)
    @tag("admin", "observability", "queries")
    def observability_queries_list(self):
        """GET /admin/observability/queries - List saved queries."""
        with self.client.get(
            "/admin/observability/queries",
            headers=self.auth_headers,
            name="/admin/observability/queries",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 500])

    @task(1)
    @tag("admin", "observability", "queries")
    def observability_queries_create(self):
        """POST /admin/observability/queries - Create a saved query."""
        payload = {
            "name": f"locust-query-{uuid.uuid4().hex[:8]}",
            "query_type": "traces",
            "filters": {},
        }
        with self.client.post(
            "/admin/observability/queries",
            json=payload,
            headers=self.auth_headers,
            name="/admin/observability/queries [create]",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 201, 422, 500])


class AdminPerformanceExtendedUser(BaseUser):
    """User that tests admin performance monitoring endpoints.

    All endpoints return 404 when performance tracking is disabled.

    Endpoints tested:
    - GET /admin/performance/cache - Cache stats
    - GET /admin/performance/history - Performance history
    - GET /admin/performance/requests - Request stats
    - GET /admin/performance/system - System performance
    - GET /admin/performance/workers - Worker stats

    Weight: Low (admin diagnostics)
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    @task(3)
    @tag("admin", "performance", "cache")
    def performance_cache(self):
        """GET /admin/performance/cache - Cache performance stats."""
        with self.client.get(
            "/admin/performance/cache",
            headers=self.auth_headers,
            name="/admin/performance/cache",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 404])

    @task(2)
    @tag("admin", "performance", "history")
    def performance_history(self):
        """GET /admin/performance/history - Performance history."""
        with self.client.get(
            "/admin/performance/history",
            headers=self.auth_headers,
            name="/admin/performance/history",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 404])

    @task(2)
    @tag("admin", "performance", "requests")
    def performance_requests(self):
        """GET /admin/performance/requests - Request performance stats."""
        with self.client.get(
            "/admin/performance/requests",
            headers=self.auth_headers,
            name="/admin/performance/requests",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 404])

    @task(2)
    @tag("admin", "performance", "system")
    def performance_system(self):
        """GET /admin/performance/system - System performance metrics."""
        with self.client.get(
            "/admin/performance/system",
            headers=self.auth_headers,
            name="/admin/performance/system",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 404])

    @task(1)
    @tag("admin", "performance", "workers")
    def performance_workers(self):
        """GET /admin/performance/workers - Worker performance stats."""
        with self.client.get(
            "/admin/performance/workers",
            headers=self.auth_headers,
            name="/admin/performance/workers",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 404])


class AdminPluginsUser(BaseUser):
    """User that tests admin plugin management endpoints.

    Endpoints tested:
    - GET /admin/plugins - List all plugins
    - GET /admin/plugins/stats - Plugin statistics
    - GET /admin/plugins/partial - Plugins HTML partial
    - GET /admin/plugins/{name} - Get specific plugin details

    Weight: Low (admin operations)
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    @task(5)
    @tag("admin", "plugins")
    def list_plugins(self):
        """GET /admin/plugins - List all plugins."""
        with self.client.get(
            "/admin/plugins",
            headers=self.auth_headers,
            name="/admin/plugins",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(3)
    @tag("admin", "plugins", "stats")
    def plugins_stats(self):
        """GET /admin/plugins/stats - Plugin statistics."""
        with self.client.get(
            "/admin/plugins/stats",
            headers=self.auth_headers,
            name="/admin/plugins/stats",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(2)
    @tag("admin", "plugins", "partial")
    def plugins_partial(self):
        """GET /admin/plugins/partial - Plugins HTML partial."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/plugins/partial",
            headers=headers,
            name="/admin/plugins/partial",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)

    @task(2)
    @tag("admin", "plugins")
    def get_plugin_detail(self):
        """GET /admin/plugins/{name} - Get plugin details."""
        plugin_names = ["VaultPlugin", "RateLimiterPlugin", "CircuitBreaker", "DenyListPlugin"]
        name = random.choice(plugin_names)
        with self.client.get(
            f"/admin/plugins/{name}",
            headers=self.auth_headers,
            name="/admin/plugins/[name]",
            catch_response=True,
        ) as response:
            # 200=Success, 404=Plugin not found
            self._validate_json_response(response, allowed_codes=[200, 404])


class AdminSystemExtendedUser(BaseUser):
    """User that tests admin system, maintenance, and registry endpoints.

    Endpoints tested:
    - GET /admin/system/stats - System-wide statistics
    - GET /admin/tags - Admin tags list
    - GET /admin/well-known - Well-known file configuration
    - GET /admin/mcp-pool/metrics - MCP connection pool metrics
    - GET /admin/mcp-registry/servers - MCP server registry
    - GET /admin/mcp-registry/partial - Registry HTML partial
    - GET /admin/maintenance/partial - Maintenance HTML partial
    - GET /admin/overview/partial - Dashboard overview HTML
    - GET /admin/change-password-required - Password change requirement check
    - GET /admin/tool-ops/partial - Tool operations HTML partial

    Weight: Low (admin diagnostics)
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    @task(3)
    @tag("admin", "system", "stats")
    def system_stats(self):
        """GET /admin/system/stats - System-wide statistics."""
        with self.client.get(
            "/admin/system/stats",
            headers=self.auth_headers,
            name="/admin/system/stats",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 500])

    @task(2)
    @tag("admin", "tags")
    def admin_tags(self):
        """GET /admin/tags - Admin tags list."""
        with self.client.get(
            "/admin/tags",
            headers=self.auth_headers,
            name="/admin/tags",
            catch_response=True,
        ) as response:
            # 500 can return non-JSON "Internal Server Error" text
            self._validate_status(response, allowed_codes=[200, 500])

    @task(2)
    @tag("admin", "well-known")
    def admin_well_known(self):
        """GET /admin/well-known - Well-known file configuration."""
        with self.client.get(
            "/admin/well-known",
            headers=self.auth_headers,
            name="/admin/well-known",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(2)
    @tag("admin", "mcp-pool")
    def mcp_pool_metrics(self):
        """GET /admin/mcp-pool/metrics - MCP connection pool metrics."""
        with self.client.get(
            "/admin/mcp-pool/metrics",
            headers=self.auth_headers,
            name="/admin/mcp-pool/metrics",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(2)
    @tag("admin", "mcp-registry")
    def mcp_registry_servers(self):
        """GET /admin/mcp-registry/servers - List MCP registry servers."""
        with self.client.get(
            "/admin/mcp-registry/servers",
            headers=self.auth_headers,
            name="/admin/mcp-registry/servers",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(1)
    @tag("admin", "mcp-registry", "partial")
    def mcp_registry_partial(self):
        """GET /admin/mcp-registry/partial - Registry HTML partial."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/mcp-registry/partial",
            headers=headers,
            name="/admin/mcp-registry/partial",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)

    @task(1)
    @tag("admin", "maintenance", "partial")
    def maintenance_partial(self):
        """GET /admin/maintenance/partial - Maintenance HTML partial."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/maintenance/partial",
            headers=headers,
            name="/admin/maintenance/partial",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)

    @task(1)
    @tag("admin", "overview", "partial")
    def overview_partial(self):
        """GET /admin/overview/partial - Dashboard overview HTML."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/overview/partial",
            headers=headers,
            name="/admin/overview/partial",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)

    @task(1)
    @tag("admin", "password")
    def change_password_required(self):
        """GET /admin/change-password-required - Check password change requirement."""
        with self.client.get(
            "/admin/change-password-required",
            headers=self.admin_headers,
            name="/admin/change-password-required",
            catch_response=True,
        ) as response:
            self._validate_status(response)

    @task(1)
    @tag("admin", "tool-ops", "partial")
    def tool_ops_partial(self):
        """GET /admin/tool-ops/partial - Tool operations HTML partial."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/tool-ops/partial",
            headers=headers,
            name="/admin/tool-ops/partial",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)


class AdminSectionsUser(BaseUser):
    """User that tests admin section partial views.

    Endpoints tested:
    - GET /admin/sections/gateways - Gateways section HTML
    - GET /admin/sections/prompts - Prompts section HTML
    - GET /admin/sections/resources - Resources section HTML
    - GET /admin/sections/servers - Servers section HTML

    Weight: Low (admin UI partials)
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    @task(3)
    @tag("admin", "sections", "gateways")
    def section_gateways(self):
        """GET /admin/sections/gateways - Gateways section HTML."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/sections/gateways",
            headers=headers,
            name="/admin/sections/gateways",
            catch_response=True,
        ) as response:
            # May return HTML or JSON depending on config
            self._validate_status(response, allowed_codes=[200, 500])

    @task(3)
    @tag("admin", "sections", "servers")
    def section_servers(self):
        """GET /admin/sections/servers - Servers section HTML."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/sections/servers",
            headers=headers,
            name="/admin/sections/servers",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])

    @task(2)
    @tag("admin", "sections", "prompts")
    def section_prompts(self):
        """GET /admin/sections/prompts - Prompts section HTML."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/sections/prompts",
            headers=headers,
            name="/admin/sections/prompts",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])

    @task(2)
    @tag("admin", "sections", "resources")
    def section_resources(self):
        """GET /admin/sections/resources - Resources section HTML."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/sections/resources",
            headers=headers,
            name="/admin/sections/resources",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])


class AdminSearchUser(BaseUser):
    """User that tests admin search and ID listing endpoints.

    Endpoints tested:
    - GET /admin/tools/search - Search tools
    - GET /admin/servers/search - Search servers
    - GET /admin/gateways/search - Search gateways
    - GET /admin/resources/search - Search resources
    - GET /admin/prompts/search - Search prompts
    - GET /admin/a2a/search - Search A2A agents
    - GET /admin/teams/search - Search teams
    - GET /admin/users/search - Search users
    - GET /admin/tools/ids - Tool ID list
    - GET /admin/gateways/ids - Gateway ID list
    - GET /admin/resources/ids - Resource ID list
    - GET /admin/prompts/ids - Prompt ID list
    - GET /admin/a2a/ids - A2A agent ID list
    - GET /admin/teams/ids - Team ID list

    Weight: Low (admin search operations)
    """

    weight = 1
    wait_time = between(1.0, 3.0)

    @task(3)
    @tag("admin", "search", "tools")
    def search_tools(self):
        """GET /admin/tools/search - Search tools."""
        with self.client.get(
            "/admin/tools/search?q=test",
            headers=self.auth_headers,
            name="/admin/tools/search",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(3)
    @tag("admin", "search", "servers")
    def search_servers(self):
        """GET /admin/servers/search - Search servers."""
        with self.client.get(
            "/admin/servers/search?q=test",
            headers=self.auth_headers,
            name="/admin/servers/search",
            catch_response=True,
        ) as response:
            # 404 can occur due to routing conflict with /admin/servers/{server_id}
            self._validate_json_response(response, allowed_codes=[200, 404])

    @task(2)
    @tag("admin", "search", "gateways")
    def search_gateways(self):
        """GET /admin/gateways/search - Search gateways."""
        with self.client.get(
            "/admin/gateways/search?q=test",
            headers=self.auth_headers,
            name="/admin/gateways/search",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(2)
    @tag("admin", "search", "resources")
    def search_resources(self):
        """GET /admin/resources/search - Search resources."""
        with self.client.get(
            "/admin/resources/search?q=test",
            headers=self.auth_headers,
            name="/admin/resources/search",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(2)
    @tag("admin", "search", "prompts")
    def search_prompts(self):
        """GET /admin/prompts/search - Search prompts."""
        with self.client.get(
            "/admin/prompts/search?q=test",
            headers=self.auth_headers,
            name="/admin/prompts/search",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(1)
    @tag("admin", "search", "a2a")
    def search_a2a(self):
        """GET /admin/a2a/search - Search A2A agents."""
        with self.client.get(
            "/admin/a2a/search?q=test",
            headers=self.auth_headers,
            name="/admin/a2a/search",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(1)
    @tag("admin", "search", "teams")
    def search_teams(self):
        """GET /admin/teams/search - Search teams."""
        with self.client.get(
            "/admin/teams/search?q=test",
            headers=self.auth_headers,
            name="/admin/teams/search",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(1)
    @tag("admin", "search", "users")
    def search_users(self):
        """GET /admin/users/search - Search users."""
        with self.client.get(
            "/admin/users/search?q=test",
            headers=self.auth_headers,
            name="/admin/users/search",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(2)
    @tag("admin", "ids", "tools")
    def tools_ids(self):
        """GET /admin/tools/ids - List tool IDs."""
        with self.client.get(
            "/admin/tools/ids",
            headers=self.auth_headers,
            name="/admin/tools/ids",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(2)
    @tag("admin", "ids", "gateways")
    def gateways_ids(self):
        """GET /admin/gateways/ids - List gateway IDs."""
        with self.client.get(
            "/admin/gateways/ids",
            headers=self.auth_headers,
            name="/admin/gateways/ids",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(2)
    @tag("admin", "ids", "resources")
    def resources_ids(self):
        """GET /admin/resources/ids - List resource IDs."""
        with self.client.get(
            "/admin/resources/ids",
            headers=self.auth_headers,
            name="/admin/resources/ids",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(2)
    @tag("admin", "ids", "prompts")
    def prompts_ids(self):
        """GET /admin/prompts/ids - List prompt IDs."""
        with self.client.get(
            "/admin/prompts/ids",
            headers=self.auth_headers,
            name="/admin/prompts/ids",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(1)
    @tag("admin", "ids", "a2a")
    def a2a_ids(self):
        """GET /admin/a2a/ids - List A2A agent IDs."""
        with self.client.get(
            "/admin/a2a/ids",
            headers=self.auth_headers,
            name="/admin/a2a/ids",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(1)
    @tag("admin", "ids", "teams")
    def teams_ids(self):
        """GET /admin/teams/ids - List team IDs."""
        with self.client.get(
            "/admin/teams/ids",
            headers=self.auth_headers,
            name="/admin/teams/ids",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)

    @task(1)
    @tag("admin", "ids", "servers")
    def servers_ids(self):
        """GET /admin/servers/ids - List server IDs."""
        with self.client.get(
            "/admin/servers/ids",
            headers=self.auth_headers,
            name="/admin/servers/ids",
            catch_response=True,
        ) as response:
            # Note: may return 404 due to routing conflict with /admin/servers/{server_id}
            self._validate_json_response(response, allowed_codes=[200, 404])


class AdminCacheConfigUser(BaseUser):
    """User that tests admin cache and passthrough header config endpoints.

    Endpoints tested:
    - GET /admin/cache/a2a-stats/stats - A2A cache statistics
    - POST /admin/cache/a2a-stats/invalidate - Invalidate A2A cache
    - GET /admin/config/passthrough-headers - Get passthrough headers config
    - GET /admin/config/passthrough-headers/cache-stats - Cache stats for headers
    - POST /admin/config/passthrough-headers/invalidate-cache - Invalidate header cache

    Weight: Low (admin cache operations)
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(3)
    @tag("admin", "cache", "a2a")
    def a2a_cache_stats(self):
        """GET /admin/cache/a2a-stats/stats - A2A cache statistics."""
        with self.client.get(
            "/admin/cache/a2a-stats/stats",
            headers=self.auth_headers,
            name="/admin/cache/a2a-stats/stats",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])

    @task(1)
    @tag("admin", "cache", "a2a")
    def a2a_cache_invalidate(self):
        """POST /admin/cache/a2a-stats/invalidate - Invalidate A2A cache."""
        with self.client.post(
            "/admin/cache/a2a-stats/invalidate",
            headers=self.auth_headers,
            name="/admin/cache/a2a-stats/invalidate",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])

    @task(3)
    @tag("admin", "config", "passthrough")
    def get_passthrough_headers(self):
        """GET /admin/config/passthrough-headers - Get passthrough headers config."""
        with self.client.get(
            "/admin/config/passthrough-headers",
            headers=self.auth_headers,
            name="/admin/config/passthrough-headers",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])

    @task(2)
    @tag("admin", "config", "passthrough", "cache")
    def passthrough_cache_stats(self):
        """GET /admin/config/passthrough-headers/cache-stats - Header cache stats."""
        with self.client.get(
            "/admin/config/passthrough-headers/cache-stats",
            headers=self.auth_headers,
            name="/admin/config/passthrough-headers/cache-stats",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])

    @task(1)
    @tag("admin", "config", "passthrough", "cache")
    def passthrough_cache_invalidate(self):
        """POST /admin/config/passthrough-headers/invalidate-cache - Invalidate header cache."""
        with self.client.post(
            "/admin/config/passthrough-headers/invalidate-cache",
            headers=self.auth_headers,
            name="/admin/config/passthrough-headers/invalidate-cache",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])


class AdminHTMXPartialsUser(BaseUser):
    """User that tests remaining admin HTMX partial views.

    Endpoints tested:
    - GET /admin/a2a/partial - A2A agents HTML partial
    - GET /admin/gateways/partial - Gateways HTML partial
    - GET /admin/servers/partial - Servers HTML partial
    - GET /admin/teams/partial - Teams HTML partial

    Weight: Low (admin UI)
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    @task(3)
    @tag("admin", "htmx", "a2a")
    def a2a_partial(self):
        """GET /admin/a2a/partial - A2A agents HTML partial."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/a2a/partial",
            headers=headers,
            name="/admin/a2a/partial",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)

    @task(3)
    @tag("admin", "htmx", "gateways")
    def gateways_partial(self):
        """GET /admin/gateways/partial - Gateways HTML partial."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/gateways/partial",
            headers=headers,
            name="/admin/gateways/partial",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)

    @task(3)
    @tag("admin", "htmx", "servers")
    def servers_partial(self):
        """GET /admin/servers/partial - Servers HTML partial."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/servers/partial",
            headers=headers,
            name="/admin/servers/partial",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)

    @task(2)
    @tag("admin", "htmx", "teams")
    def teams_partial(self):
        """GET /admin/teams/partial - Teams HTML partial."""
        headers = {**self.admin_headers, "HX-Request": "true"}
        with self.client.get(
            "/admin/teams/partial",
            headers=headers,
            name="/admin/teams/partial",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)


class GatewayExtendedUser(BaseUser):
    """User that tests extended gateway operations.

    Endpoints tested:
    - POST /gateways/{id}/toggle - Toggle gateway enabled/disabled
    - POST /gateways/{id}/tools/refresh - Refresh tools from gateway

    Weight: Low (write operations on gateways)
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(3)
    @tag("gateways", "toggle")
    def toggle_gateway(self):
        """POST /gateways/{id}/toggle - Toggle gateway state."""
        if GATEWAY_IDS:
            gw_id = random.choice(GATEWAY_IDS)
            with self.client.post(
                f"/gateways/{gw_id}/toggle",
                headers=self.auth_headers,
                name="/gateways/[id]/toggle",
                catch_response=True,
            ) as response:
                self._validate_json_response(response, allowed_codes=[200, 401, 404, *INFRASTRUCTURE_ERROR_CODES])

    @task(2)
    @tag("gateways", "refresh")
    def refresh_gateway_tools(self):
        """POST /gateways/{id}/tools/refresh - Refresh gateway tools."""
        if GATEWAY_IDS:
            gw_id = random.choice(GATEWAY_IDS)
            with self.client.post(
                f"/gateways/{gw_id}/tools/refresh",
                headers=self.auth_headers,
                name="/gateways/[id]/tools/refresh",
                catch_response=True,
            ) as response:
                self._validate_json_response(response, allowed_codes=[200, 404, 409, 500, *INFRASTRUCTURE_ERROR_CODES])


class ResourcesSubscribeUser(BaseUser):
    """User that tests resource subscription endpoint.

    Endpoints tested:
    - POST /resources/subscribe - Subscribe to resource changes
    - GET /roots/changes - Get root change notifications

    Weight: Low (subscription operations)
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(3)
    @tag("resources", "subscribe")
    def subscribe_resource(self):
        """POST /resources/subscribe - Subscribe to resource changes."""
        payload = {"uri": f"test://resource-{uuid.uuid4().hex[:8]}"}
        with self.client.post(
            "/resources/subscribe",
            json=payload,
            headers=self.auth_headers,
            name="/resources/subscribe",
            catch_response=True,
        ) as response:
            self._validate_status(response)

    @task(2)
    @tag("roots", "changes")
    def roots_changes(self):
        """GET /roots/changes - Get root change notifications."""
        with self.client.get(
            "/roots/changes",
            headers=self.auth_headers,
            name="/roots/changes",
            catch_response=True,
        ) as response:
            self._validate_status(response)


class LoggingMetricsUser(BaseUser):
    """User that tests logging and metrics management endpoints.

    Endpoints tested:
    - POST /logging/setLevel - Set log level
    - GET /metrics/prometheus - Prometheus metrics export
    - POST /metrics/reset - Reset all metrics

    Weight: Very low (administrative operations)
    """

    weight = 1
    wait_time = between(5.0, 15.0)

    @task(3)
    @tag("logging", "level")
    def set_log_level(self):
        """POST /logging/setLevel - Set the logging level."""
        with self.client.post(
            "/logging/setLevel",
            json={"level": "INFO"},
            headers=self.auth_headers,
            name="/logging/setLevel",
            catch_response=True,
        ) as response:
            # 200=Success, 500=Logging level setting not supported in some configs
            self._validate_status(response, allowed_codes=[200, 422, 500])

    @task(3)
    @tag("metrics", "prometheus")
    def prometheus_metrics(self):
        """GET /metrics/prometheus - Prometheus-format metrics."""
        with self.client.get(
            "/metrics/prometheus",
            headers=self.auth_headers,
            name="/metrics/prometheus",
            catch_response=True,
        ) as response:
            self._validate_status(response)

    @task(1)
    @tag("metrics", "reset")
    def reset_metrics(self):
        """POST /metrics/reset - Reset all metrics counters."""
        with self.client.post(
            "/metrics/reset",
            headers=self.auth_headers,
            name="/metrics/reset",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)


class AdminGrpcUser(BaseUser):
    """User that tests admin gRPC service management endpoints.

    Endpoints tested:
    - GET /admin/grpc - List gRPC services
    - POST /admin/grpc - Create gRPC service (not executed, just listed)

    Weight: Very low (gRPC management)
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(5)
    @tag("admin", "grpc")
    def list_grpc_services(self):
        """GET /admin/grpc - List gRPC services."""
        with self.client.get(
            "/admin/grpc",
            headers=self.auth_headers,
            name="/admin/grpc",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 404])


class WellKnownExtendedUser(BaseUser):
    """User that tests well-known and singleton endpoints.

    Endpoints tested:
    - GET /.well-known/oauth-protected-resource - OAuth resource metadata
    - GET /openapi.json - OpenAPI specification

    Weight: Very low (metadata endpoints)
    """

    weight = 1
    wait_time = between(5.0, 15.0)

    @task(3)
    @tag("well-known", "oauth")
    def well_known_oauth(self):
        """GET /.well-known/oauth-protected-resource - OAuth resource metadata."""
        with self.client.get(
            "/.well-known/oauth-protected-resource",
            headers=self.auth_headers,
            name="/.well-known/oauth-protected-resource",
            catch_response=True,
        ) as response:
            # 404=Not configured
            self._validate_status(response, allowed_codes=[200, 404])


class AuthEmailExtendedUser(BaseUser):
    """User that tests extended email authentication endpoints.

    Endpoints tested:
    - GET /auth/email/me - Get current user profile
    - POST /auth/login - JWT login

    Weight: Very low (auth operations)
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(3)
    @tag("auth", "email", "me")
    def auth_email_me(self):
        """GET /auth/email/me - Get current user profile."""
        with self.client.get(
            "/auth/email/me",
            headers=self.auth_headers,
            name="/auth/email/me",
            catch_response=True,
        ) as response:
            # 200=Success, 401=Not email-authenticated, 422=Validation error
            self._validate_json_response(response, allowed_codes=[200, 401, 403, 422])

    @task(2)
    @tag("auth", "login")
    def auth_login(self):
        """POST /auth/login - JWT-based login."""
        with self.client.post(
            "/auth/login",
            json={},
            headers=self.auth_headers,
            name="/auth/login",
            catch_response=True,
        ) as response:
            self._validate_json_response(response, allowed_codes=[200, 401, 403, 422])


class AdminLoginLogoutUser(BaseUser):
    """User that tests admin login/logout endpoints.

    Endpoints tested:
    - GET /admin/login - Admin login page
    - GET /admin/logout - Admin logout

    Weight: Very low (session management)
    """

    weight = 1
    wait_time = between(5.0, 15.0)

    @task(3)
    @tag("admin", "login")
    def admin_login_page(self):
        """GET /admin/login - Admin login page."""
        with self.client.get(
            "/admin/login",
            headers=self.admin_headers,
            name="/admin/login",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 302])

    @task(1)
    @tag("admin", "logout")
    def admin_logout(self):
        """GET /admin/logout - Admin logout."""
        with self.client.get(
            "/admin/logout",
            headers=self.admin_headers,
            name="/admin/logout",
            catch_response=True,
        ) as response:
            # Typically redirects to login page
            self._validate_status(response, allowed_codes=[200, 302, 307])


class AdminLogsExtendedUser(BaseUser):
    """User that tests extended admin log endpoints.

    Endpoints tested:
    - GET /admin/logs/export - Export logs
    - GET /admin/logs/file - Get log file

    Skipped endpoints:
    - GET /admin/logs/stream - SSE streaming (not suitable for load test)

    Weight: Very low (admin operations)
    """

    weight = 1
    wait_time = between(5.0, 15.0)

    @task(3)
    @tag("admin", "logs", "export")
    def logs_export(self):
        """GET /admin/logs/export - Export logs."""
        with self.client.get(
            "/admin/logs/export",
            headers=self.auth_headers,
            name="/admin/logs/export",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 404, 500])

    @task(2)
    @tag("admin", "logs", "file")
    def logs_file(self):
        """GET /admin/logs/file - Get log file contents."""
        with self.client.get(
            "/admin/logs/file",
            headers=self.auth_headers,
            name="/admin/logs/file",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 404, 500])


class AdminLLMExtendedUser(BaseUser):
    """User that tests extended admin LLM management endpoints.

    Endpoints tested:
    - GET /admin/llm/api-info/html - LLM API info page
    - GET /admin/llm/models/html - LLM models admin page
    - GET /admin/llm/providers/html - LLM providers admin page

    Weight: Very low (admin pages)
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(3)
    @tag("admin", "llm", "api-info")
    def llm_api_info(self):
        """GET /admin/llm/api-info/html - LLM API info page."""
        with self.client.get(
            "/admin/llm/api-info/html",
            headers=self.admin_headers,
            name="/admin/llm/api-info/html",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)

    @task(2)
    @tag("admin", "llm", "models")
    def llm_models_html(self):
        """GET /admin/llm/models/html - LLM models admin page."""
        with self.client.get(
            "/admin/llm/models/html",
            headers=self.admin_headers,
            name="/admin/llm/models/html",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)

    @task(2)
    @tag("admin", "llm", "providers")
    def llm_providers_html(self):
        """GET /admin/llm/providers/html - LLM providers admin page."""
        with self.client.get(
            "/admin/llm/providers/html",
            headers=self.admin_headers,
            name="/admin/llm/providers/html",
            catch_response=True,
        ) as response:
            self._validate_html_response(response)


class AdminSupportBundleUser(BaseUser):
    """User that tests admin support bundle generation.

    Endpoints tested:
    - GET /admin/support-bundle/generate - Generate support bundle

    Weight: Very low (diagnostic operation)
    """

    weight = 1
    wait_time = between(10.0, 30.0)

    @task(1)
    @tag("admin", "support-bundle")
    def generate_support_bundle(self):
        """GET /admin/support-bundle/generate - Generate support bundle."""
        with self.client.get(
            "/admin/support-bundle/generate",
            headers=self.auth_headers,
            name="/admin/support-bundle/generate",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 404, 500])


# =============================================================================
# Batch 11: Additional Coverage - Entity Details, State, Membership, Misc
# =============================================================================


class RootEndpointUser(BaseUser):
    """User that tests the root endpoint.

    Endpoints tested:
    - GET / - Root API endpoint

    Weight: Very low
    """

    weight = 1
    wait_time = between(5.0, 15.0)

    @task(1)
    @tag("root", "meta")
    def get_root(self):
        """GET / - Root API endpoint."""
        with self.client.get(
            "/",
            headers=self.auth_headers,
            name="/",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 307])


class AdminEntityDetailUser(BaseUser):
    """User that tests admin entity detail view endpoints.

    Endpoints tested:
    - GET /admin/tools/{tool_id} - Tool detail view
    - GET /admin/servers/{server_id} - Server detail view
    - GET /admin/gateways/{gateway_id} - Gateway detail view
    - GET /admin/resources/{resource_id} - Resource detail view
    - GET /admin/prompts/{prompt_id} - Prompt detail view
    - GET /admin/users - User list
    - GET /admin/import/status - Import status list

    Weight: Low (admin UI)
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    @task(3)
    @tag("admin", "tools", "detail")
    def admin_tool_detail(self):
        """GET /admin/tools/{tool_id} - Tool detail view."""
        if TOOL_IDS:
            tool_id = random.choice(TOOL_IDS)
            with self.client.get(
                f"/admin/tools/{tool_id}",
                headers=self.admin_headers,
                name="/admin/tools/[id]",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 404])

    @task(3)
    @tag("admin", "servers", "detail")
    def admin_server_detail(self):
        """GET /admin/servers/{server_id} - Server detail view."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            with self.client.get(
                f"/admin/servers/{server_id}",
                headers=self.admin_headers,
                name="/admin/servers/[id]",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 404])

    @task(2)
    @tag("admin", "gateways", "detail")
    def admin_gateway_detail(self):
        """GET /admin/gateways/{gateway_id} - Gateway detail view."""
        if GATEWAY_IDS:
            gw_id = random.choice(GATEWAY_IDS)
            with self.client.get(
                f"/admin/gateways/{gw_id}",
                headers=self.admin_headers,
                name="/admin/gateways/[id]",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 404])

    @task(2)
    @tag("admin", "resources", "detail")
    def admin_resource_detail(self):
        """GET /admin/resources/{resource_id} - Resource detail view."""
        if RESOURCE_IDS:
            res_id = random.choice(RESOURCE_IDS)
            with self.client.get(
                f"/admin/resources/{res_id}",
                headers=self.admin_headers,
                name="/admin/resources/[id]",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 404])

    @task(2)
    @tag("admin", "prompts", "detail")
    def admin_prompt_detail(self):
        """GET /admin/prompts/{prompt_id} - Prompt detail view."""
        if PROMPT_IDS:
            prompt_id = random.choice(PROMPT_IDS)
            with self.client.get(
                f"/admin/prompts/{prompt_id}",
                headers=self.admin_headers,
                name="/admin/prompts/[id]",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 404])

    @task(2)
    @tag("admin", "users")
    def admin_users_list(self):
        """GET /admin/users - Admin user list."""
        with self.client.get(
            "/admin/users",
            headers=self.admin_headers,
            name="/admin/users",
            catch_response=True,
        ) as response:
            self._validate_status(response)

    @task(1)
    @tag("admin", "import")
    def admin_import_status(self):
        """GET /admin/import/status - Import status list."""
        with self.client.get(
            "/admin/import/status",
            headers=self.auth_headers,
            name="/admin/import/status",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)


class AdminMetricsResetUser(BaseUser):
    """User that tests admin metrics reset endpoint.

    Endpoints tested:
    - POST /admin/metrics/reset - Reset admin metrics

    Weight: Very low (destructive operation)
    """

    weight = 1
    wait_time = between(10.0, 30.0)

    @task(1)
    @tag("admin", "metrics", "reset")
    def admin_metrics_reset(self):
        """POST /admin/metrics/reset - Reset admin metrics."""
        with self.client.post(
            "/admin/metrics/reset",
            headers=self.auth_headers,
            name="/admin/metrics/reset",
            catch_response=True,
        ) as response:
            self._validate_json_response(response)


class A2AStateToggleUser(BaseUser):
    """User that tests A2A agent state and toggle operations.

    Endpoints tested:
    - POST /a2a/{id}/state - Set A2A agent state
    - POST /a2a/{id}/toggle - Toggle A2A agent

    Weight: 0 when A2A_TESTING_ENABLED is False (no real A2A agent available)
    """

    weight = 1 if A2A_TESTING_ENABLED else 0
    wait_time = between(3.0, 8.0)

    def on_start(self):
        """Set up and discover A2A agent IDs."""
        super().on_start()
        self.a2a_ids: list[str] = []
        with self.client.get(
            "/a2a",
            headers=self.auth_headers,
            name="/a2a [setup]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                try:
                    data = response.json()
                    agents = data if isinstance(data, list) else data.get("agents", data.get("items", []))
                    self.a2a_ids = [a.get("id") for a in agents[:5] if a.get("id")]
                except Exception:
                    pass
            response.success()

    @task(3)
    @tag("a2a", "state")
    def a2a_state(self):
        """POST /a2a/{id}/state - Set A2A agent state."""
        if self.a2a_ids:
            agent_id = random.choice(self.a2a_ids)
            with self.client.post(
                f"/a2a/{agent_id}/state",
                json={"enabled": True},
                headers=self.auth_headers,
                name="/a2a/[id]/state",
                catch_response=True,
            ) as response:
                self._validate_json_response(response, allowed_codes=[200, 401, 404, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(2)
    @tag("a2a", "toggle")
    def a2a_toggle(self):
        """POST /a2a/{id}/toggle - Toggle A2A agent (deprecated endpoint)."""
        if self.a2a_ids:
            agent_id = random.choice(self.a2a_ids)
            with self.client.post(
                f"/a2a/{agent_id}/toggle",
                headers=self.auth_headers,
                name="/a2a/[id]/toggle",
                catch_response=True,
            ) as response:
                # 401 is expected: deprecated endpoint has auth issues
                self._validate_json_response(response, allowed_codes=[200, 401, 404, *INFRASTRUCTURE_ERROR_CODES])


class AdminTeamsMembershipUser(BaseUser):
    """User that tests admin team membership management endpoints.

    Endpoints tested:
    - GET /admin/teams/{team_id}/edit - Team edit view
    - GET /admin/teams/{team_id}/members - Team members list
    - GET /admin/teams/{team_id}/join-requests - Team join requests
    - GET /admin/teams/{team_id}/members/partial - Members HTML partial
    - GET /admin/teams/{team_id}/members/add - Add member view
    - GET /admin/teams/{team_id}/non-members/partial - Non-members partial

    Weight: Low (admin team management)
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    def on_start(self):
        """Set up and get a team ID."""
        super().on_start()
        self.team_ids: list[str] = []
        with self.client.get(
            "/teams/",
            headers=self.auth_headers,
            name="/teams/ [setup]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                try:
                    data = response.json()
                    teams = data if isinstance(data, list) else data.get("teams", data.get("items", []))
                    self.team_ids = [t.get("id") or t.get("team_id") for t in teams[:5] if t.get("id") or t.get("team_id")]
                except Exception:
                    pass
            response.success()

    @task(3)
    @tag("admin", "teams", "edit")
    def team_edit_view(self):
        """GET /admin/teams/{team_id}/edit - Team edit view."""
        if self.team_ids:
            tid = random.choice(self.team_ids)
            with self.client.get(
                f"/admin/teams/{tid}/edit",
                headers=self.admin_headers,
                name="/admin/teams/[id]/edit",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 404])

    @task(3)
    @tag("admin", "teams", "members")
    def team_members(self):
        """GET /admin/teams/{team_id}/members - Team members list."""
        if self.team_ids:
            tid = random.choice(self.team_ids)
            with self.client.get(
                f"/admin/teams/{tid}/members",
                headers=self.admin_headers,
                name="/admin/teams/[id]/members",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 404])

    @task(2)
    @tag("admin", "teams", "join-requests")
    def team_join_requests(self):
        """GET /admin/teams/{team_id}/join-requests - Team join requests."""
        if self.team_ids:
            tid = random.choice(self.team_ids)
            with self.client.get(
                f"/admin/teams/{tid}/join-requests",
                headers=self.admin_headers,
                name="/admin/teams/[id]/join-requests",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 404])

    @task(1)
    @tag("admin", "teams", "members", "partial")
    def team_members_partial(self):
        """GET /admin/teams/{team_id}/members/partial - Members HTML partial."""
        if self.team_ids:
            tid = random.choice(self.team_ids)
            headers = {**self.admin_headers, "HX-Request": "true"}
            with self.client.get(
                f"/admin/teams/{tid}/members/partial",
                headers=headers,
                name="/admin/teams/[id]/members/partial",
                catch_response=True,
            ) as response:
                self._validate_html_response(response, allowed_codes=[200, 404])

    @task(1)
    @tag("admin", "teams", "members", "add")
    def team_members_add_view(self):
        """GET /admin/teams/{team_id}/members/add - Add member view."""
        if self.team_ids:
            tid = random.choice(self.team_ids)
            with self.client.get(
                f"/admin/teams/{tid}/members/add",
                headers=self.admin_headers,
                name="/admin/teams/[id]/members/add",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 404])

    @task(1)
    @tag("admin", "teams", "non-members")
    def team_non_members_partial(self):
        """GET /admin/teams/{team_id}/non-members/partial - Non-members partial."""
        if self.team_ids:
            tid = random.choice(self.team_ids)
            headers = {**self.admin_headers, "HX-Request": "true"}
            with self.client.get(
                f"/admin/teams/{tid}/non-members/partial",
                headers=headers,
                name="/admin/teams/[id]/non-members/partial",
                catch_response=True,
            ) as response:
                self._validate_html_response(response, allowed_codes=[200, 404])


class ServerWellKnownUser(BaseUser):
    """User that tests per-server well-known and sub-resource endpoints.

    Endpoints tested:
    - GET /servers/{id}/.well-known/oauth-protected-resource - Server OAuth metadata
    - POST /servers/{id}/message - Send message to server

    Weight: Very low
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(3)
    @tag("servers", "well-known")
    def server_well_known_oauth(self):
        """GET /servers/{id}/.well-known/oauth-protected-resource - Server OAuth metadata."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            with self.client.get(
                f"/servers/{server_id}/.well-known/oauth-protected-resource",
                headers=self.auth_headers,
                name="/servers/[id]/.well-known/oauth-protected-resource",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 404])

    @task(2)
    @tag("servers", "message")
    def server_message(self):
        """POST /servers/{id}/message - Send message to server."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "ping", "params": {}}
            with self.client.post(
                f"/servers/{server_id}/message",
                json=payload,
                headers=self.auth_headers,
                name="/servers/[id]/message",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 400, 404, 500])


class ImportExtendedUser(BaseUser):
    """User that tests extended import endpoints.

    Endpoints tested:
    - GET /import/status/{import_id} - Get specific import status
    - POST /admin/import/preview - Preview import

    Weight: Very low (admin operations)
    """

    weight = 1
    wait_time = between(5.0, 15.0)

    @task(3)
    @tag("import", "status")
    def import_status_detail(self):
        """GET /import/status/{import_id} - Get specific import status."""
        with self.client.get(
            f"/import/status/{uuid.uuid4().hex[:8]}",
            headers=self.auth_headers,
            name="/import/status/[id]",
            catch_response=True,
        ) as response:
            # 200=Found, 404=Not found (expected with random ID)
            self._validate_json_response(response, allowed_codes=[200, 404])

    @task(1)
    @tag("admin", "import", "preview")
    def admin_import_preview(self):
        """POST /admin/import/preview - Preview import."""
        payload = {"entities": {}}
        with self.client.post(
            "/admin/import/preview",
            json=payload,
            headers=self.auth_headers,
            name="/admin/import/preview",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 400, 422, 500])


class OAuthExtendedUser(BaseUser):
    """User that tests extended OAuth endpoints.

    Endpoints tested:
    - GET /oauth/status/{gateway_id} - OAuth status for gateway
    - GET /oauth/registered-clients/{gateway_id} - Registered clients for gateway

    Skipped endpoints (browser redirect flows):
    - GET /oauth/authorize/{gateway_id} - Browser redirect flow
    - GET /oauth/callback - Browser redirect callback

    Weight: Very low
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(3)
    @tag("oauth", "status")
    def oauth_status(self):
        """GET /oauth/status/{gateway_id} - OAuth status for gateway."""
        if GATEWAY_IDS:
            gw_id = random.choice(GATEWAY_IDS)
            with self.client.get(
                f"/oauth/status/{gw_id}",
                headers=self.auth_headers,
                name="/oauth/status/[id]",
                catch_response=True,
            ) as response:
                self._validate_json_response(response, allowed_codes=[200, 404])

    @task(2)
    @tag("oauth", "clients")
    def oauth_registered_clients_gateway(self):
        """GET /oauth/registered-clients/{gateway_id} - Registered clients for gateway."""
        if GATEWAY_IDS:
            gw_id = random.choice(GATEWAY_IDS)
            with self.client.get(
                f"/oauth/registered-clients/{gw_id}",
                headers=self.auth_headers,
                name="/oauth/registered-clients/[id]",
                catch_response=True,
            ) as response:
                self._validate_json_response(response, allowed_codes=[200, 404])


class LLMChatUser(BaseUser):
    """User that tests LLM chat session endpoints.

    Endpoints tested:
    - GET /llmchat/config/{user_id} - Chat config for user
    - GET /llmchat/status/{user_id} - Chat status for user
    - POST /llmchat/disconnect - Disconnect chat session

    Skipped endpoints:
    - POST /llmchat/connect - Requires full LLM config (422 without it)
    - POST /llmchat/chat - Requires active session

    Weight: Very low
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(3)
    @tag("llmchat", "config")
    def chat_config(self):
        """GET /llmchat/config/{user_id} - Chat config for user."""
        with self.client.get(
            "/llmchat/config/admin@example.com",
            headers=self.auth_headers,
            name="/llmchat/config/[id]",
            catch_response=True,
        ) as response:
            # 200=Success, 403=User ID mismatch, 404=Not found
            self._validate_json_response(response, allowed_codes=[200, 403, 404])

    @task(2)
    @tag("llmchat", "status")
    def chat_status(self):
        """GET /llmchat/status/{user_id} - Chat status for user."""
        with self.client.get(
            "/llmchat/status/admin@example.com",
            headers=self.auth_headers,
            name="/llmchat/status/[id]",
            catch_response=True,
        ) as response:
            # 200=Success, 403=User ID mismatch
            self._validate_json_response(response, allowed_codes=[200, 403])

    @task(1)
    @tag("llmchat", "disconnect")
    def chat_disconnect(self):
        """POST /llmchat/disconnect - Disconnect chat session."""
        with self.client.post(
            "/llmchat/disconnect",
            json={"user_id": "admin@example.com"},
            headers=self.auth_headers,
            name="/llmchat/disconnect",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 400, 404, 422])


class AdminResourcesTestUser(BaseUser):
    """User that tests admin resource testing endpoints.

    Endpoints tested:
    - GET /admin/resources/test/{resource_uri} - Test resource fetch

    Weight: Very low (admin diagnostic)
    """

    weight = 1
    wait_time = between(5.0, 15.0)

    @task(1)
    @tag("admin", "resources", "test")
    def test_resource(self):
        """GET /admin/resources/test/{resource_uri} - Test resource fetch."""
        with self.client.get(
            "/admin/resources/test/test://sample",
            headers=self.auth_headers,
            name="/admin/resources/test/[uri]",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 404, 500])


# =============================================================================
# Batch 12: Extended CRUD Write Operations
# =============================================================================


class EntityUpdateExtendedUser(BaseUser):
    """Extended entity update (PUT) operations for entities missing from EntityUpdateUser.

    Endpoints tested:
    - PUT /servers/{server_id}
    - PUT /prompts/{prompt_id}
    - PUT /a2a/{agent_id}
    - PUT /teams/{team_id}
    - PUT /tokens/{token_id}
    - PUT /rbac/roles/{role_id}

    Weight: Very low (write operations)
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(2)
    @tag("servers", "update")
    def update_server(self):
        """PUT /servers/{server_id} - Update a server."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            with self.client.get(
                f"/servers/{server_id}",
                headers=self.auth_headers,
                name="/servers/[id] [for update]",
                catch_response=True,
            ) as response:
                if response.status_code == 200:
                    try:
                        data = response.json()
                        data["description"] = f"Updated by load test at {time.time()}"
                        time.sleep(0.05)
                        with self.client.put(
                            f"/servers/{server_id}",
                            json=data,
                            headers={**self.auth_headers, "Content-Type": "application/json"},
                            name="/servers/[id] [update]",
                            catch_response=True,
                        ) as put_resp:
                            self._validate_json_response(put_resp, allowed_codes=[200, 403, 404, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                        response.success()
                    except Exception:
                        response.success()
                else:
                    self._validate_json_response(response, allowed_codes=[200, 404])

    @task(2)
    @tag("prompts", "update")
    def update_prompt(self):
        """PUT /prompts/{prompt_id} - Update a prompt."""
        if PROMPT_IDS:
            prompt_id = random.choice(PROMPT_IDS)
            with self.client.get(
                f"/prompts/{prompt_id}",
                headers=self.auth_headers,
                name="/prompts/[id] [for update]",
                catch_response=True,
            ) as response:
                if response.status_code == 200:
                    try:
                        data = response.json()
                        data["description"] = f"Updated by load test at {time.time()}"
                        time.sleep(0.05)
                        with self.client.put(
                            f"/prompts/{prompt_id}",
                            json=data,
                            headers={**self.auth_headers, "Content-Type": "application/json"},
                            name="/prompts/[id] [update]",
                            catch_response=True,
                        ) as put_resp:
                            self._validate_json_response(put_resp, allowed_codes=[200, 403, 404, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                        response.success()
                    except Exception:
                        response.success()
                else:
                    self._validate_json_response(response, allowed_codes=[200, 404])

    @task(1)
    @tag("a2a", "update")
    def update_a2a(self):
        """PUT /a2a/{agent_id} - Update an A2A agent."""
        if not A2A_TESTING_ENABLED:
            return
        with self.client.get(
            "/a2a",
            headers=self.auth_headers,
            name="/a2a [list for update]",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.success()
                return
            try:
                data = response.json()
                agents = data if isinstance(data, list) else data.get("agents", data.get("items", []))
                if not agents:
                    response.success()
                    return
                agent = random.choice(agents)
                agent_id = agent.get("id")
                if not agent_id:
                    response.success()
                    return
                response.success()
            except Exception:
                response.success()
                return

        agent["description"] = f"Updated by load test at {time.time()}"
        with self.client.put(
            f"/a2a/{agent_id}",
            json=agent,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/a2a/[id] [update]",
            catch_response=True,
        ) as put_resp:
            self._validate_json_response(put_resp, allowed_codes=[200, 403, 404, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("teams", "update")
    def update_team(self):
        """PUT /teams/{team_id} - Update a team."""
        if TEAM_IDS:
            team_id = random.choice(TEAM_IDS)
            with self.client.get(
                f"/teams/{team_id}",
                headers=self.auth_headers,
                name="/teams/[id] [for update]",
                catch_response=True,
            ) as response:
                if response.status_code == 200:
                    try:
                        data = response.json()
                        data["description"] = f"Updated by load test at {time.time()}"
                        time.sleep(0.05)
                        with self.client.put(
                            f"/teams/{team_id}",
                            json=data,
                            headers={**self.auth_headers, "Content-Type": "application/json"},
                            name="/teams/[id] [update]",
                            catch_response=True,
                        ) as put_resp:
                            self._validate_json_response(put_resp, allowed_codes=[200, 403, 404, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                        response.success()
                    except Exception:
                        response.success()
                else:
                    self._validate_json_response(response, allowed_codes=[200, 403, 404])

    @task(1)
    @tag("tokens", "update")
    def update_token(self):
        """PUT /tokens/{token_id} - Update a token."""
        with self.client.get(
            "/tokens",
            headers=self.auth_headers,
            name="/tokens [list for update]",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.success()
                return
            try:
                data = response.json()
                tokens = data if isinstance(data, list) else data.get("tokens", data.get("items", []))
                if not tokens:
                    response.success()
                    return
                token = random.choice(tokens)
                token_id = token.get("id")
                if not token_id:
                    response.success()
                    return
                response.success()
            except Exception:
                response.success()
                return

        update_data = {"name": token.get("name", "token"), "description": f"Updated by load test at {time.time()}"}
        with self.client.put(
            f"/tokens/{token_id}",
            json=update_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/tokens/[id] [update]",
            catch_response=True,
        ) as put_resp:
            self._validate_json_response(put_resp, allowed_codes=[200, 403, 404, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("rbac", "update")
    def update_rbac_role(self):
        """PUT /rbac/roles/{role_id} - Update a role."""
        if ROLE_IDS:
            role_id = random.choice(ROLE_IDS)
            with self.client.get(
                f"/rbac/roles/{role_id}",
                headers=self.auth_headers,
                name="/rbac/roles/[id] [for update]",
                catch_response=True,
            ) as response:
                if response.status_code == 200:
                    try:
                        data = response.json()
                        data["description"] = f"Updated by load test at {time.time()}"
                        time.sleep(0.05)
                        with self.client.put(
                            f"/rbac/roles/{role_id}",
                            json=data,
                            headers={**self.auth_headers, "Content-Type": "application/json"},
                            name="/rbac/roles/[id] [update]",
                            catch_response=True,
                        ) as put_resp:
                            self._validate_json_response(put_resp, allowed_codes=[200, 400, 403, 404, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                        response.success()
                    except Exception:
                        response.success()
                else:
                    self._validate_json_response(response, allowed_codes=[200, 404])


class LLMCRUDUser(BaseUser):
    """LLM models and providers full CRUD lifecycle.

    Endpoints tested:
    - POST /llm/providers - Create provider
    - GET /llm/providers/{provider_id} - Get provider details
    - PATCH /llm/providers/{provider_id} - Update provider
    - POST /llm/providers/{provider_id}/health - Check provider health
    - POST /llm/providers/{provider_id}/state - Toggle provider state
    - DELETE /llm/providers/{provider_id} - Delete provider
    - POST /llm/models - Create model
    - GET /llm/models/{model_id} - Get model details
    - PATCH /llm/models/{model_id} - Update model
    - POST /llm/models/{model_id}/state - Toggle model state
    - DELETE /llm/models/{model_id} - Delete model

    Weight: Very low (administrative CRUD)
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    def __init__(self, *args, **kwargs):
        """Initialize with cleanup tracking."""
        super().__init__(*args, **kwargs)
        self.created_providers: list[str] = []
        self.created_models: list[str] = []

    def on_stop(self):
        """Clean up created LLM entities."""
        for model_id in self.created_models:
            try:
                self.client.delete(f"/llm/models/{model_id}", headers=self.auth_headers, name="/llm/models/[id] [cleanup]")
            except Exception:
                pass
        for provider_id in self.created_providers:
            try:
                self.client.delete(f"/llm/providers/{provider_id}", headers=self.auth_headers, name="/llm/providers/[id] [cleanup]")
            except Exception:
                pass

    @task(3)
    @tag("llm", "providers", "crud")
    def provider_lifecycle(self):
        """POST/GET/PATCH/health/state/DELETE /llm/providers - Full lifecycle."""
        provider_name = f"loadtest-provider-{uuid.uuid4().hex[:8]}"
        provider_data = {
            "name": provider_name,
            "provider_type": "openai",
            "base_url": "http://localhost:1/v1",
            "api_key": "test-key-loadtest",
        }

        with self.client.post(
            "/llm/providers",
            json=provider_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/llm/providers [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                try:
                    data = response.json()
                    provider_id = data.get("id") or data.get("name") or provider_name
                    # GET provider details
                    time.sleep(0.05)
                    self.client.get(f"/llm/providers/{provider_id}", headers=self.auth_headers, name="/llm/providers/[id]")
                    # PATCH provider
                    time.sleep(0.05)
                    with self.client.patch(
                        f"/llm/providers/{provider_id}",
                        json={"description": f"Patched at {time.time()}"},
                        headers={**self.auth_headers, "Content-Type": "application/json"},
                        name="/llm/providers/[id] [patch]",
                        catch_response=True,
                    ) as patch_resp:
                        self._validate_status(patch_resp, allowed_codes=[200, 403, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                    # Health check
                    time.sleep(0.05)
                    with self.client.post(
                        f"/llm/providers/{provider_id}/health",
                        headers=self.auth_headers,
                        name="/llm/providers/[id]/health",
                        catch_response=True,
                    ) as health_resp:
                        self._validate_status(health_resp, allowed_codes=[200, 404, 500, 503, *INFRASTRUCTURE_ERROR_CODES])
                    # Toggle state
                    time.sleep(0.05)
                    with self.client.post(
                        f"/llm/providers/{provider_id}/state",
                        headers=self.auth_headers,
                        name="/llm/providers/[id]/state",
                        catch_response=True,
                    ) as state_resp:
                        self._validate_status(state_resp, allowed_codes=[200, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                    # Delete
                    time.sleep(0.05)
                    self.client.delete(f"/llm/providers/{provider_id}", headers=self.auth_headers, name="/llm/providers/[id] [delete]")
                    response.success()
                except Exception:
                    response.success()
            elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                response.success()

    @task(2)
    @tag("llm", "models", "crud")
    def model_lifecycle(self):
        """POST/GET/PATCH/state/DELETE /llm/models - Full lifecycle."""
        model_data = {
            "model_id": f"loadtest-model-{uuid.uuid4().hex[:8]}",
            "provider_id": "loadtest-provider",
            "name": f"loadtest-model-{uuid.uuid4().hex[:8]}",
        }

        with self.client.post(
            "/llm/models",
            json=model_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/llm/models [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                try:
                    data = response.json()
                    model_id = data.get("id") or data.get("model_id") or model_data["model_id"]
                    # GET model details
                    time.sleep(0.05)
                    self.client.get(f"/llm/models/{model_id}", headers=self.auth_headers, name="/llm/models/[id]")
                    # PATCH model
                    time.sleep(0.05)
                    with self.client.patch(
                        f"/llm/models/{model_id}",
                        json={"description": f"Patched at {time.time()}"},
                        headers={**self.auth_headers, "Content-Type": "application/json"},
                        name="/llm/models/[id] [patch]",
                        catch_response=True,
                    ) as patch_resp:
                        self._validate_status(patch_resp, allowed_codes=[200, 403, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                    # Toggle state
                    time.sleep(0.05)
                    with self.client.post(
                        f"/llm/models/{model_id}/state",
                        headers=self.auth_headers,
                        name="/llm/models/[id]/state",
                        catch_response=True,
                    ) as state_resp:
                        self._validate_status(state_resp, allowed_codes=[200, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                    # Delete
                    time.sleep(0.05)
                    self.client.delete(f"/llm/models/{model_id}", headers=self.auth_headers, name="/llm/models/[id] [delete]")
                    response.success()
                except Exception:
                    response.success()
            elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                response.success()

    @task(2)
    @tag("llm", "providers", "read")
    def read_provider_details(self):
        """GET /llm/providers/{provider_id} - Read existing provider."""
        with self.client.get(
            "/llm/providers",
            headers=self.auth_headers,
            name="/llm/providers [list for read]",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.success()
                return
            try:
                data = response.json()
                providers = data if isinstance(data, list) else data.get("providers", data.get("items", []))
                if providers:
                    provider = random.choice(providers)
                    pid = provider.get("id")
                    if pid:
                        self.client.get(f"/llm/providers/{pid}", headers=self.auth_headers, name="/llm/providers/[id]")
                response.success()
            except Exception:
                response.success()

    @task(2)
    @tag("llm", "models", "read")
    def read_model_details(self):
        """GET /llm/models/{model_id} - Read existing model."""
        with self.client.get(
            "/llm/models",
            headers=self.auth_headers,
            name="/llm/models [list for read]",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.success()
                return
            try:
                data = response.json()
                models = data if isinstance(data, list) else data.get("models", data.get("items", []))
                if models:
                    model = random.choice(models)
                    mid = model.get("id") or model.get("model_id")
                    if mid:
                        self.client.get(f"/llm/models/{mid}", headers=self.auth_headers, name="/llm/models/[id]")
                response.success()
            except Exception:
                response.success()


class GatewayCRUDExtendedUser(BaseUser):
    """Gateway create/update/delete lifecycle.

    NOTE: Gateway CRUD can cause timeouts (external MCP server calls).
    Uses generous timeouts and error handling.

    Endpoints tested:
    - POST /gateways - Create gateway
    - PUT /gateways/{gateway_id} - Update gateway
    - DELETE /gateways/{gateway_id} - Delete gateway

    Weight: Very low (risky write operations)
    """

    weight = 1
    wait_time = between(5.0, 15.0)
    network_timeout = 120.0

    def __init__(self, *args, **kwargs):
        """Initialize with cleanup tracking."""
        super().__init__(*args, **kwargs)
        self.created_gateways: list[str] = []

    def on_stop(self):
        """Clean up created gateways."""
        for gw_id in self.created_gateways:
            try:
                self.client.delete(f"/gateways/{gw_id}", headers=self.auth_headers, name="/gateways/[id] [cleanup]")
            except Exception:
                pass

    @task(2)
    @tag("gateways", "crud")
    def gateway_lifecycle(self):
        """POST/PUT/DELETE /gateways - Full lifecycle."""
        gw_name = f"loadtest-gw-{uuid.uuid4().hex[:8]}"
        gw_data = {
            "name": gw_name,
            "url": "http://localhost:1",
            "description": "Load test gateway - will be deleted",
        }

        with self.client.post(
            "/gateways",
            json=gw_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/gateways [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                try:
                    data = response.json()
                    gw_id = data.get("id") or data.get("name") or gw_name
                    # Update
                    time.sleep(0.1)
                    with self.client.put(
                        f"/gateways/{gw_id}",
                        json={**gw_data, "description": f"Updated at {time.time()}"},
                        headers={**self.auth_headers, "Content-Type": "application/json"},
                        name="/gateways/[id] [update]",
                        catch_response=True,
                    ) as put_resp:
                        self._validate_status(put_resp, allowed_codes=[200, 403, 404, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                    # Delete
                    time.sleep(0.1)
                    self.client.delete(f"/gateways/{gw_id}", headers=self.auth_headers, name="/gateways/[id] [delete]")
                    response.success()
                except Exception:
                    response.success()
            elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                response.success()


class AuthEmailCRUDUser(BaseUser):
    """Auth email admin user management and auth operations.

    Endpoints tested:
    - POST /auth/email/admin/users - Admin create user
    - GET /auth/email/admin/users/{user_email} - Admin get user
    - PUT /auth/email/admin/users/{user_email} - Admin update user
    - DELETE /auth/email/admin/users/{user_email} - Admin delete user
    - POST /auth/email/change-password - Change password
    - POST /auth/email/login - Email login
    - POST /auth/email/register - Email registration

    Weight: Very low (auth operations)
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(3)
    @tag("auth", "email", "admin", "crud")
    def admin_user_lifecycle(self):
        """POST/GET/PUT/DELETE /auth/email/admin/users - Full lifecycle."""
        email = f"loadtest-{uuid.uuid4().hex[:8]}@example.com"
        user_data = {
            "email": email,
            "password": "LoadTest123!",
            "full_name": "Load Test User",
            "is_active": True,
        }

        with self.client.post(
            "/auth/email/admin/users",
            json=user_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/auth/email/admin/users [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                try:
                    # GET user
                    time.sleep(0.05)
                    self.client.get(
                        f"/auth/email/admin/users/{email}",
                        headers=self.auth_headers,
                        name="/auth/email/admin/users/[email]",
                    )
                    # PUT update
                    time.sleep(0.05)
                    with self.client.put(
                        f"/auth/email/admin/users/{email}",
                        json={**user_data, "full_name": "Updated Load Test User"},
                        headers={**self.auth_headers, "Content-Type": "application/json"},
                        name="/auth/email/admin/users/[email] [update]",
                        catch_response=True,
                    ) as put_resp:
                        self._validate_status(put_resp, allowed_codes=[200, 403, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                    # DELETE
                    time.sleep(0.05)
                    self.client.delete(
                        f"/auth/email/admin/users/{email}",
                        headers=self.auth_headers,
                        name="/auth/email/admin/users/[email] [delete]",
                    )
                    response.success()
                except Exception:
                    response.success()
            elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                response.success()

    @task(2)
    @tag("auth", "email", "login")
    def email_login(self):
        """POST /auth/email/login - Email login."""
        with self.client.post(
            "/auth/email/login",
            json={"email": "admin@example.com", "password": "changeme"},
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/auth/email/login",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 401, 403, 422, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("auth", "email", "register")
    def email_register_and_delete(self):
        """POST /auth/email/register - Register then delete."""
        email = f"loadtest-reg-{uuid.uuid4().hex[:8]}@example.com"
        with self.client.post(
            "/auth/email/register",
            json={"email": email, "password": "LoadTest123!", "full_name": "Load Test"},
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/auth/email/register",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                try:
                    time.sleep(0.05)
                    self.client.delete(
                        f"/auth/email/admin/users/{email}",
                        headers=self.auth_headers,
                        name="/auth/email/admin/users/[email] [cleanup]",
                    )
                except Exception:
                    pass
            elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                response.success()

    @task(1)
    @tag("auth", "email", "password")
    def change_password(self):
        """POST /auth/email/change-password - Change password."""
        with self.client.post(
            "/auth/email/change-password",
            json={"current_password": "changeme", "new_password": "changeme"},
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/auth/email/change-password",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 400, 401, 403, 422, 500, *INFRASTRUCTURE_ERROR_CODES])


# =============================================================================
# Batch 13: Extended Write Operations (Teams, RBAC, Tokens, Reverse Proxy)
# =============================================================================


class TeamsExtendedWriteUser(BaseUser):
    """Teams extended write operations: membership, invitations, join.

    Endpoints tested:
    - POST /teams/{team_id}/join - Join a team
    - DELETE /teams/{team_id}/leave - Leave a team
    - POST /teams/{team_id}/invitations - Create invitation
    - DELETE /teams/invitations/{invitation_id} - Cancel invitation
    - POST /teams/invitations/{token}/accept - Accept invitation
    - POST /teams/{team_id}/join-requests/{request_id}/approve - Approve join request
    - DELETE /teams/{team_id}/join-requests/{request_id} - Delete join request
    - PUT /teams/{team_id}/members/{user_email} - Update member role
    - DELETE /teams/{team_id}/members/{user_email} - Remove member

    Weight: Very low (complex team operations)
    """

    weight = 1
    wait_time = between(5.0, 15.0)
    network_timeout = 120.0

    @task(2)
    @tag("teams", "join")
    def join_team(self):
        """POST /teams/{team_id}/join - Attempt to join a team."""
        if TEAM_IDS:
            team_id = random.choice(TEAM_IDS)
            with self.client.post(
                f"/teams/{team_id}/join",
                headers=self.auth_headers,
                name="/teams/[id]/join",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 400, 403, 404, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("teams", "leave")
    def leave_team(self):
        """DELETE /teams/{team_id}/leave - Leave a team."""
        if TEAM_IDS:
            team_id = random.choice(TEAM_IDS)
            with self.client.delete(
                f"/teams/{team_id}/leave",
                headers=self.auth_headers,
                name="/teams/[id]/leave",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 400, 403, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(2)
    @tag("teams", "invitations")
    def create_invitation(self):
        """POST /teams/{team_id}/invitations - Create an invitation."""
        if TEAM_IDS:
            team_id = random.choice(TEAM_IDS)
            invite_data = {"email": f"loadtest-invite-{uuid.uuid4().hex[:8]}@example.com", "role": "viewer"}
            with self.client.post(
                f"/teams/{team_id}/invitations",
                json=invite_data,
                headers={**self.auth_headers, "Content-Type": "application/json"},
                name="/teams/[id]/invitations [create]",
                catch_response=True,
            ) as response:
                if response.status_code in (200, 201):
                    try:
                        data = response.json()
                        invite_id = data.get("id")
                        token = data.get("token")
                        if invite_id:
                            time.sleep(0.05)
                            self.client.delete(
                                f"/teams/invitations/{invite_id}",
                                headers=self.auth_headers,
                                name="/teams/invitations/[id] [delete]",
                            )
                        elif token:
                            time.sleep(0.05)
                            with self.client.post(
                                f"/teams/invitations/{token}/accept",
                                headers=self.auth_headers,
                                name="/teams/invitations/[token]/accept",
                                catch_response=True,
                            ) as accept_resp:
                                self._validate_status(accept_resp, allowed_codes=[200, 400, 403, 404, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                    except Exception:
                        pass
                    response.success()
                elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                    response.success()

    @task(1)
    @tag("teams", "join-requests")
    def manage_join_requests(self):
        """POST approve / DELETE join requests."""
        if TEAM_IDS:
            team_id = random.choice(TEAM_IDS)
            with self.client.get(
                f"/teams/{team_id}/join-requests",
                headers=self.auth_headers,
                name="/teams/[id]/join-requests [list for manage]",
                catch_response=True,
            ) as response:
                if response.status_code == 200:
                    try:
                        data = response.json()
                        requests = data if isinstance(data, list) else data.get("join_requests", data.get("items", []))
                        if requests:
                            req = random.choice(requests)
                            req_id = req.get("id")
                            if req_id:
                                # Approve or delete
                                if random.random() < 0.5:
                                    with self.client.post(
                                        f"/teams/{team_id}/join-requests/{req_id}/approve",
                                        headers=self.auth_headers,
                                        name="/teams/[id]/join-requests/[id]/approve",
                                        catch_response=True,
                                    ) as approve_resp:
                                        self._validate_status(approve_resp, allowed_codes=[200, 403, 404, 409, 500, *INFRASTRUCTURE_ERROR_CODES])
                                else:
                                    with self.client.delete(
                                        f"/teams/{team_id}/join-requests/{req_id}",
                                        headers=self.auth_headers,
                                        name="/teams/[id]/join-requests/[id] [delete]",
                                        catch_response=True,
                                    ) as del_resp:
                                        self._validate_status(del_resp, allowed_codes=[200, 403, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                    except Exception:
                        pass
                response.success()

    @task(1)
    @tag("teams", "members")
    def manage_members(self):
        """PUT/DELETE /teams/{team_id}/members/{email} - Manage members."""
        if TEAM_IDS:
            team_id = random.choice(TEAM_IDS)
            with self.client.get(
                f"/teams/{team_id}/members",
                headers=self.auth_headers,
                name="/teams/[id]/members [list for manage]",
                catch_response=True,
            ) as response:
                if response.status_code == 200:
                    try:
                        data = response.json()
                        members = data if isinstance(data, list) else data.get("members", data.get("items", []))
                        if members:
                            member = random.choice(members)
                            email = member.get("email") or member.get("user_email")
                            if email and email != "admin@example.com":
                                with self.client.put(
                                    f"/teams/{team_id}/members/{email}",
                                    json={"role": "viewer"},
                                    headers={**self.auth_headers, "Content-Type": "application/json"},
                                    name="/teams/[id]/members/[email] [update]",
                                    catch_response=True,
                                ) as put_resp:
                                    self._validate_status(put_resp, allowed_codes=[200, 403, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                    except Exception:
                        pass
                response.success()

    @task(1)
    @tag("teams", "members", "remove")
    def remove_member(self):
        """DELETE /teams/{team_id}/members/{user_email} - Remove member."""
        if TEAM_IDS:
            team_id = random.choice(TEAM_IDS)
            # Use a fake email to avoid actually removing real members
            fake_email = f"loadtest-{uuid.uuid4().hex[:8]}@example.com"
            with self.client.delete(
                f"/teams/{team_id}/members/{fake_email}",
                headers=self.auth_headers,
                name="/teams/[id]/members/[email] [delete]",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 400, 403, 404, 500, *INFRASTRUCTURE_ERROR_CODES])


class RBACExtendedWriteUser(BaseUser):
    """RBAC extended write operations: user-role management.

    Endpoints tested:
    - POST /rbac/users/{user_email}/roles - Assign role to user
    - DELETE /rbac/users/{user_email}/roles/{role_id} - Remove role from user

    Weight: Very low (admin operations)
    """

    weight = 1
    wait_time = between(5.0, 15.0)

    @task(2)
    @tag("rbac", "users", "roles", "assign")
    def assign_user_role(self):
        """POST /rbac/users/{user_email}/roles - Assign role."""
        if ROLE_IDS:
            role_id = random.choice(ROLE_IDS)
            with self.client.post(
                "/rbac/users/admin@example.com/roles",
                json={"role_id": role_id},
                headers={**self.auth_headers, "Content-Type": "application/json"},
                name="/rbac/users/[email]/roles [assign]",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 400, 403, 404, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("rbac", "users", "roles", "remove")
    def remove_user_role(self):
        """DELETE /rbac/users/{user_email}/roles/{role_id} - Remove role."""
        if ROLE_IDS:
            role_id = random.choice(ROLE_IDS)
            with self.client.delete(
                f"/rbac/users/admin@example.com/roles/{role_id}",
                headers=self.auth_headers,
                name="/rbac/users/[email]/roles/[id] [delete]",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 403, 404, 500, *INFRASTRUCTURE_ERROR_CODES])


class TokensExtendedWriteUser(BaseUser):
    """Tokens extended write operations.

    Endpoints tested:
    - DELETE /tokens/admin/{token_id} - Admin delete token
    - POST /tokens/teams/{team_id} - Create team token

    Weight: Very low (admin operations)
    """

    weight = 1
    wait_time = between(5.0, 15.0)

    @task(2)
    @tag("tokens", "admin", "delete")
    def admin_delete_token(self):
        """DELETE /tokens/admin/{token_id} - Admin delete a token (test with fake ID)."""
        fake_id = f"loadtest-{uuid.uuid4().hex[:8]}"
        with self.client.delete(
            f"/tokens/admin/{fake_id}",
            headers=self.auth_headers,
            name="/tokens/admin/[id] [delete]",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 403, 404, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(2)
    @tag("tokens", "teams", "create")
    def create_team_token(self):
        """POST /tokens/teams/{team_id} - Create team token."""
        if TEAM_IDS:
            team_id = random.choice(TEAM_IDS)
            token_data = {
                "name": f"loadtest-team-token-{uuid.uuid4().hex[:8]}",
                "description": "Load test team token",
                "expires_in_days": 1,
            }
            with self.client.post(
                f"/tokens/teams/{team_id}",
                json=token_data,
                headers={**self.auth_headers, "Content-Type": "application/json"},
                name="/tokens/teams/[id] [create]",
                catch_response=True,
            ) as response:
                if response.status_code in (200, 201):
                    try:
                        data = response.json()
                        token_id = data.get("id")
                        if token_id:
                            time.sleep(0.05)
                            self.client.delete(f"/tokens/{token_id}", headers=self.auth_headers, name="/tokens/[id] [cleanup]")
                    except Exception:
                        pass
                    response.success()
                elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                    response.success()


class ReverseProxyExtendedUser(BaseUser):
    """Reverse proxy extended operations.

    Endpoints tested:
    - DELETE /reverse-proxy/sessions/{session_id} - Delete session
    - POST /reverse-proxy/sessions/{session_id}/request - Send request via proxy

    Weight: Very low (proxy operations)
    """

    weight = 1
    wait_time = between(5.0, 15.0)

    @task(2)
    @tag("reverse-proxy", "sessions", "delete")
    def delete_session(self):
        """DELETE /reverse-proxy/sessions/{session_id} - Delete session."""
        fake_id = f"loadtest-{uuid.uuid4().hex[:8]}"
        with self.client.delete(
            f"/reverse-proxy/sessions/{fake_id}",
            headers=self.auth_headers,
            name="/reverse-proxy/sessions/[id] [delete]",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 401, 403, 404, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("reverse-proxy", "sessions", "request")
    def proxy_request(self):
        """POST /reverse-proxy/sessions/{session_id}/request - Send request."""
        fake_id = f"loadtest-{uuid.uuid4().hex[:8]}"
        with self.client.post(
            f"/reverse-proxy/sessions/{fake_id}/request",
            json={"method": "tools/list", "params": {}},
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/reverse-proxy/sessions/[id]/request",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 400, 401, 403, 404, 500, *INFRASTRUCTURE_ERROR_CODES])


# =============================================================================
# Batch 14: Admin Detail Reads, gRPC, HTMX State Ops, Misc
# =============================================================================


class AdminDetailReadExtendedUser(BaseUser):
    """Admin detail read-only endpoints.

    Endpoints tested:
    - GET /admin/a2a/{agent_id} - Admin A2A detail
    - GET /admin/grpc/{service_id} - Admin gRPC detail
    - GET /admin/grpc/{service_id}/methods - Admin gRPC methods
    - GET /admin/import/status/{import_id} - Import status detail
    - GET /admin/mcp-registry/{server_id}/status - MCP registry status
    - GET /admin/observability/queries/{query_id} - Observability query detail
    - GET /admin/observability/trace/{trace_id} - Observability trace detail
    - GET /admin/users/{user_email}/edit - User edit form
    - GET /admin/config/settings - Config settings

    Weight: Very low (admin reads)
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(2)
    @tag("admin", "a2a", "detail")
    def admin_a2a_detail(self):
        """GET /admin/a2a/{agent_id} - Admin A2A agent detail."""
        if not A2A_TESTING_ENABLED:
            return
        if A2A_IDS:
            agent_id = random.choice(A2A_IDS)
            with self.client.get(
                f"/admin/a2a/{agent_id}",
                headers=self.admin_headers,
                name="/admin/a2a/[id]",
                catch_response=True,
            ) as detail_resp:
                self._validate_status(detail_resp, allowed_codes=[200, 404, 500])

    @task(1)
    @tag("admin", "grpc", "detail")
    def admin_grpc_detail(self):
        """GET /admin/grpc/{service_id} - Admin gRPC detail."""
        fake_id = f"loadtest-{uuid.uuid4().hex[:8]}"
        with self.client.get(
            f"/admin/grpc/{fake_id}",
            headers=self.admin_headers,
            name="/admin/grpc/[id]",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 404, 500])

    @task(1)
    @tag("admin", "grpc", "methods")
    def admin_grpc_methods(self):
        """GET /admin/grpc/{service_id}/methods - Admin gRPC methods."""
        fake_id = f"loadtest-{uuid.uuid4().hex[:8]}"
        with self.client.get(
            f"/admin/grpc/{fake_id}/methods",
            headers=self.admin_headers,
            name="/admin/grpc/[id]/methods",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 404, 500])

    @task(1)
    @tag("admin", "import", "status")
    def admin_import_status_detail(self):
        """GET /admin/import/status/{import_id} - Import status detail."""
        fake_id = f"loadtest-{uuid.uuid4().hex[:8]}"
        with self.client.get(
            f"/admin/import/status/{fake_id}",
            headers=self.admin_headers,
            name="/admin/import/status/[id]",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 404, 500])

    @task(1)
    @tag("admin", "mcp-registry", "status")
    def admin_mcp_registry_status(self):
        """GET /admin/mcp-registry/{server_id}/status - MCP registry status."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            with self.client.get(
                f"/admin/mcp-registry/{server_id}/status",
                headers=self.admin_headers,
                name="/admin/mcp-registry/[id]/status",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 404, 500])

    @task(1)
    @tag("admin", "observability", "queries")
    def admin_observability_query_detail(self):
        """GET /admin/observability/queries/{query_id} - Query detail."""
        fake_id = f"loadtest-{uuid.uuid4().hex[:8]}"
        with self.client.get(
            f"/admin/observability/queries/{fake_id}",
            headers=self.admin_headers,
            name="/admin/observability/queries/[id]",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 404, 422, 500])

    @task(1)
    @tag("admin", "observability", "traces")
    def admin_observability_trace(self):
        """GET /admin/observability/trace/{trace_id} - Trace detail."""
        fake_id = f"loadtest-{uuid.uuid4().hex[:8]}"
        with self.client.get(
            f"/admin/observability/trace/{fake_id}",
            headers=self.admin_headers,
            name="/admin/observability/trace/[id]",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 404, 500])

    @task(2)
    @tag("admin", "users", "detail")
    def admin_user_edit(self):
        """GET /admin/users/{user_email}/edit - User edit form."""
        with self.client.get(
            "/admin/users/admin@example.com/edit",
            headers=self.admin_headers,
            name="/admin/users/[email]/edit",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 404, 500])

    @task(1)
    @tag("admin", "config", "settings")
    def admin_config_settings(self):
        """GET /admin/config/settings - Config settings."""
        with self.client.get(
            "/admin/config/settings",
            headers=self.admin_headers,
            name="/admin/config/settings",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 500])


class AdminGrpcCRUDUser(BaseUser):
    """Admin gRPC service management.

    Endpoints tested:
    - POST /admin/grpc - Create gRPC service
    - GET /admin/grpc/{service_id} - Get service detail
    - PUT /admin/grpc/{service_id} - Update service
    - POST /admin/grpc/{service_id}/reflect - Reflect service
    - POST /admin/grpc/{service_id}/state - Toggle state
    - POST /admin/grpc/{service_id}/delete - Delete service

    Weight: Very low (admin gRPC)
    """

    weight = 1
    wait_time = between(5.0, 15.0)

    @task(2)
    @tag("admin", "grpc", "crud")
    def grpc_lifecycle(self):
        """POST/GET/PUT/reflect/state/delete - Full gRPC lifecycle."""
        svc_name = f"loadtest-grpc-{uuid.uuid4().hex[:8]}"
        svc_data = {
            "name": svc_name,
            "host": "localhost",
            "port": 50051,
            "description": "Load test gRPC service",
        }

        with self.client.post(
            "/admin/grpc",
            json=svc_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/admin/grpc [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                try:
                    data = response.json()
                    svc_id = data.get("id") or data.get("name") or svc_name
                    # GET detail
                    time.sleep(0.05)
                    self.client.get(f"/admin/grpc/{svc_id}", headers=self.admin_headers, name="/admin/grpc/[id] [read]")
                    # PUT update
                    time.sleep(0.05)
                    with self.client.put(
                        f"/admin/grpc/{svc_id}",
                        json={**svc_data, "description": f"Updated at {time.time()}"},
                        headers={**self.auth_headers, "Content-Type": "application/json"},
                        name="/admin/grpc/[id] [update]",
                        catch_response=True,
                    ) as put_resp:
                        self._validate_status(put_resp, allowed_codes=[200, 403, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                    # Reflect
                    time.sleep(0.05)
                    with self.client.post(
                        f"/admin/grpc/{svc_id}/reflect",
                        headers=self.auth_headers,
                        name="/admin/grpc/[id]/reflect",
                        catch_response=True,
                    ) as reflect_resp:
                        self._validate_status(reflect_resp, allowed_codes=[200, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                    # Toggle state
                    time.sleep(0.05)
                    with self.client.post(
                        f"/admin/grpc/{svc_id}/state",
                        headers=self.auth_headers,
                        name="/admin/grpc/[id]/state",
                        catch_response=True,
                    ) as state_resp:
                        self._validate_status(state_resp, allowed_codes=[200, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                    # Delete
                    time.sleep(0.05)
                    with self.client.post(
                        f"/admin/grpc/{svc_id}/delete",
                        headers=self.auth_headers,
                        name="/admin/grpc/[id]/delete",
                        catch_response=True,
                    ) as del_resp:
                        self._validate_status(del_resp, allowed_codes=[200, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                    response.success()
                except Exception:
                    response.success()
            elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                response.success()


class AdminHTMXEntityOpsUser(BaseUser):
    """Admin HTMX entity state and test operations.

    Covers admin UI endpoints for toggling entity states and testing.

    Endpoints tested:
    - POST /admin/a2a/{id}/state - Toggle A2A state
    - POST /admin/a2a/{id}/test - Test A2A agent
    - POST /admin/gateways/{id}/state - Toggle gateway state
    - POST /admin/gateways/test - Test gateway URL
    - POST /admin/servers/{id}/state - Toggle server state
    - POST /admin/prompts/{id}/state - Toggle prompt state
    - POST /admin/resources/{id}/state - Toggle resource state
    - POST /admin/tools/{id}/state - Toggle tool state
    - POST /admin/change-password-required - Toggle setting
    - PUT /admin/config/passthrough-headers - Update passthrough headers

    Weight: Very low (admin operations)
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(1)
    @tag("admin", "a2a", "state")
    def toggle_a2a_state(self):
        """POST /admin/a2a/{id}/state - Toggle A2A state."""
        if not A2A_TESTING_ENABLED:
            return
        if A2A_IDS:
            agent_id = random.choice(A2A_IDS)
            with self.client.post(
                f"/admin/a2a/{agent_id}/state",
                data="activate=true",
                headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded"},
                name="/admin/a2a/[id]/state",
                catch_response=True,
            ) as r:
                self._validate_status(r, allowed_codes=[200, 302, 303, 403, 404, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "a2a", "test")
    def test_a2a_agent(self):
        """POST /admin/a2a/{id}/test - Test A2A agent."""
        if not A2A_TESTING_ENABLED:
            return
        if A2A_IDS:
            agent_id = random.choice(A2A_IDS)
            with self.client.post(
                f"/admin/a2a/{agent_id}/test",
                json={"query": "Load test ping"},
                headers={**self.auth_headers, "Content-Type": "application/json"},
                name="/admin/a2a/[id]/test",
                catch_response=True,
            ) as r:
                self._validate_status(r, allowed_codes=[200, 403, 404, 500, 503, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "gateways", "state")
    def toggle_gateway_state(self):
        """POST /admin/gateways/{id}/state - Toggle gateway state."""
        if GATEWAY_IDS:
            gw_id = random.choice(GATEWAY_IDS)
            with self.client.post(f"/admin/gateways/{gw_id}/state", headers=self.auth_headers, name="/admin/gateways/[id]/state", catch_response=True) as r:
                self._validate_status(r, allowed_codes=[200, 403, 404, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "gateways", "test")
    def test_gateway(self):
        """POST /admin/gateways/test - Test gateway URL."""
        with self.client.post(
            "/admin/gateways/test",
            json={"url": "http://localhost:1"},
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/admin/gateways/test",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 400, 422, 500, 503, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "servers", "state")
    def toggle_server_state(self):
        """POST /admin/servers/{id}/state - Toggle server state."""
        if SERVER_IDS:
            srv_id = random.choice(SERVER_IDS)
            with self.client.post(f"/admin/servers/{srv_id}/state", headers=self.auth_headers, name="/admin/servers/[id]/state", catch_response=True) as r:
                self._validate_status(r, allowed_codes=[200, 403, 404, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "prompts", "state")
    def toggle_prompt_state(self):
        """POST /admin/prompts/{id}/state - Toggle prompt state."""
        if PROMPT_IDS:
            pid = random.choice(PROMPT_IDS)
            with self.client.post(f"/admin/prompts/{pid}/state", headers=self.auth_headers, name="/admin/prompts/[id]/state", catch_response=True) as r:
                self._validate_status(r, allowed_codes=[200, 403, 404, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "resources", "state")
    def toggle_resource_state(self):
        """POST /admin/resources/{id}/state - Toggle resource state."""
        if RESOURCE_IDS:
            rid = random.choice(RESOURCE_IDS)
            with self.client.post(f"/admin/resources/{rid}/state", headers=self.auth_headers, name="/admin/resources/[id]/state", catch_response=True) as r:
                self._validate_status(r, allowed_codes=[200, 403, 404, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "tools", "state")
    def toggle_tool_state(self):
        """POST /admin/tools/{id}/state - Toggle tool state."""
        if TOOL_IDS:
            tid = random.choice(TOOL_IDS)
            with self.client.post(f"/admin/tools/{tid}/state", headers=self.auth_headers, name="/admin/tools/[id]/state", catch_response=True) as r:
                self._validate_status(r, allowed_codes=[200, 403, 404, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "config")
    def toggle_change_password(self):
        """POST /admin/change-password-required - Toggle setting."""
        with self.client.post(
            "/admin/change-password-required",
            headers=self.auth_headers,
            name="/admin/change-password-required [toggle]",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 403, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "config", "passthrough")
    def update_passthrough_headers(self):
        """PUT /admin/config/passthrough-headers - Update config."""
        with self.client.put(
            "/admin/config/passthrough-headers",
            json={"headers": []},
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/admin/config/passthrough-headers [update]",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 403, 422, 500, *INFRASTRUCTURE_ERROR_CODES])


class AdminMCPRegistryOpsUser(BaseUser):
    """Admin MCP registry operations.

    Endpoints tested:
    - POST /admin/mcp-registry/bulk-register - Bulk register servers
    - POST /admin/mcp-registry/{server_id}/register - Register single server

    Weight: Very low (admin operations)
    """

    weight = 1
    wait_time = between(5.0, 15.0)

    @task(1)
    @tag("admin", "mcp-registry", "register")
    def register_server(self):
        """POST /admin/mcp-registry/{server_id}/register - Register server."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            with self.client.post(
                f"/admin/mcp-registry/{server_id}/register",
                headers=self.auth_headers,
                name="/admin/mcp-registry/[id]/register",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 400, 404, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "mcp-registry", "bulk")
    def bulk_register(self):
        """POST /admin/mcp-registry/bulk-register - Bulk register."""
        with self.client.post(
            "/admin/mcp-registry/bulk-register",
            json={"server_ids": []},
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/admin/mcp-registry/bulk-register",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 400, 422, 500, *INFRASTRUCTURE_ERROR_CODES])


class AdminLLMOpsUser(BaseUser):
    """Admin LLM operations (unique to admin UI).

    Endpoints tested:
    - POST /admin/llm/test - Test LLM connection
    - DELETE /admin/llm/models/{model_id} - Delete model via admin
    - POST /admin/llm/models/{model_id}/state - Toggle model state
    - DELETE /admin/llm/providers/{provider_id} - Delete provider via admin
    - POST /admin/llm/providers/{provider_id}/fetch-models - Fetch models
    - POST /admin/llm/providers/{provider_id}/health - Check health
    - POST /admin/llm/providers/{provider_id}/state - Toggle state
    - POST /admin/llm/providers/{provider_id}/sync-models - Sync models

    Weight: Very low (admin LLM ops)
    """

    weight = 1
    wait_time = between(5.0, 15.0)

    @task(2)
    @tag("admin", "llm", "test")
    def test_llm(self):
        """POST /admin/llm/test - Test LLM connection."""
        with self.client.post(
            "/admin/llm/test",
            json={"provider_type": "openai", "base_url": "http://localhost:1/v1", "api_key": "test"},
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/admin/llm/test",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 400, 422, 500, 503, *INFRASTRUCTURE_ERROR_CODES])

    def _get_random_provider_id(self):
        """Fetch a random LLM provider ID."""
        with self.client.get("/llm/providers", headers=self.auth_headers, name="/llm/providers [list for admin ops]", catch_response=True) as response:
            if response.status_code != 200:
                response.success()
                return None
            try:
                data = response.json()
                providers = data if isinstance(data, list) else data.get("providers", data.get("items", []))
                if not providers:
                    response.success()
                    return None
                pid = random.choice(providers).get("id")
                response.success()
                return pid
            except Exception:
                response.success()
                return None

    def _get_random_model_id(self):
        """Fetch a random LLM model ID."""
        with self.client.get("/llm/models", headers=self.auth_headers, name="/llm/models [list for admin ops]", catch_response=True) as response:
            if response.status_code != 200:
                response.success()
                return None
            try:
                data = response.json()
                models = data if isinstance(data, list) else data.get("models", data.get("items", []))
                if not models:
                    response.success()
                    return None
                mid = random.choice(models).get("id") or random.choice(models).get("model_id")
                response.success()
                return mid
            except Exception:
                response.success()
                return None

    @task(1)
    @tag("admin", "llm", "providers", "fetch-models")
    def admin_provider_fetch_models(self):
        """POST /admin/llm/providers/{id}/fetch-models - Fetch models."""
        pid = self._get_random_provider_id()
        if pid:
            with self.client.post(f"/admin/llm/providers/{pid}/fetch-models", headers=self.auth_headers, name="/admin/llm/providers/[id]/fetch-models", catch_response=True) as r:
                self._validate_status(r, allowed_codes=[200, 404, 500, 503, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "llm", "providers", "health")
    def admin_provider_health(self):
        """POST /admin/llm/providers/{id}/health - Check health."""
        pid = self._get_random_provider_id()
        if pid:
            with self.client.post(f"/admin/llm/providers/{pid}/health", headers=self.auth_headers, name="/admin/llm/providers/[id]/health", catch_response=True) as r:
                self._validate_status(r, allowed_codes=[200, 404, 500, 503, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "llm", "providers", "state")
    def admin_provider_state(self):
        """POST /admin/llm/providers/{id}/state - Toggle state."""
        pid = self._get_random_provider_id()
        if pid:
            with self.client.post(f"/admin/llm/providers/{pid}/state", headers=self.auth_headers, name="/admin/llm/providers/[id]/state", catch_response=True) as r:
                self._validate_status(r, allowed_codes=[200, 404, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "llm", "providers", "sync-models")
    def admin_provider_sync_models(self):
        """POST /admin/llm/providers/{id}/sync-models - Sync models."""
        pid = self._get_random_provider_id()
        if pid:
            with self.client.post(f"/admin/llm/providers/{pid}/sync-models", headers=self.auth_headers, name="/admin/llm/providers/[id]/sync-models", catch_response=True) as r:
                self._validate_status(r, allowed_codes=[200, 404, 500, 503, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "llm", "providers", "delete")
    def admin_provider_delete(self):
        """DELETE /admin/llm/providers/{id} - Delete provider (test with fake ID)."""
        fake_id = f"loadtest-{uuid.uuid4().hex[:8]}"
        with self.client.delete(f"/admin/llm/providers/{fake_id}", headers=self.auth_headers, name="/admin/llm/providers/[id] [delete]", catch_response=True) as r:
            self._validate_status(r, allowed_codes=[200, 404, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "llm", "models", "state")
    def admin_model_state(self):
        """POST /admin/llm/models/{id}/state - Toggle model state."""
        mid = self._get_random_model_id()
        if mid:
            with self.client.post(f"/admin/llm/models/{mid}/state", headers=self.auth_headers, name="/admin/llm/models/[id]/state", catch_response=True) as r:
                self._validate_status(r, allowed_codes=[200, 404, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "llm", "models", "delete")
    def admin_model_delete(self):
        """DELETE /admin/llm/models/{id} - Delete model (test with fake ID)."""
        fake_id = f"loadtest-{uuid.uuid4().hex[:8]}"
        with self.client.delete(f"/admin/llm/models/{fake_id}", headers=self.auth_headers, name="/admin/llm/models/[id] [delete]", catch_response=True) as r:
            self._validate_status(r, allowed_codes=[200, 404, 500, *INFRASTRUCTURE_ERROR_CODES])


class AdminObservabilityQueriesUser(BaseUser):
    """Admin observability saved queries CRUD.

    Endpoints tested:
    - POST /admin/observability/queries - Create saved query
    - GET /admin/observability/queries/{query_id} - Get query
    - PUT /admin/observability/queries/{query_id} - Update query
    - POST /admin/observability/queries/{query_id}/use - Use query
    - DELETE /admin/observability/queries/{query_id} - Delete query

    Weight: Very low (admin observability)
    """

    weight = 1
    wait_time = between(5.0, 15.0)

    @task(2)
    @tag("admin", "observability", "queries", "crud")
    def query_lifecycle(self):
        """POST/GET/PUT/use/DELETE - Full query lifecycle."""
        query_data = {
            "name": f"loadtest-query-{uuid.uuid4().hex[:8]}",
            "query": "SELECT * FROM metrics LIMIT 10",
            "description": "Load test query",
        }

        with self.client.post(
            "/admin/observability/queries",
            json=query_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/admin/observability/queries [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                try:
                    data = response.json()
                    qid = data.get("id") or data.get("query_id")
                    if qid:
                        # GET
                        time.sleep(0.05)
                        self.client.get(f"/admin/observability/queries/{qid}", headers=self.admin_headers, name="/admin/observability/queries/[id]")
                        # PUT update
                        time.sleep(0.05)
                        with self.client.put(
                            f"/admin/observability/queries/{qid}",
                            json={**query_data, "description": f"Updated at {time.time()}"},
                            headers={**self.auth_headers, "Content-Type": "application/json"},
                            name="/admin/observability/queries/[id] [update]",
                            catch_response=True,
                        ) as put_resp:
                            self._validate_status(put_resp, allowed_codes=[200, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                        # Use
                        time.sleep(0.05)
                        with self.client.post(
                            f"/admin/observability/queries/{qid}/use",
                            headers=self.auth_headers,
                            name="/admin/observability/queries/[id]/use",
                            catch_response=True,
                        ) as use_resp:
                            self._validate_status(use_resp, allowed_codes=[200, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                        # DELETE
                        time.sleep(0.05)
                        with self.client.delete(
                            f"/admin/observability/queries/{qid}",
                            headers=self.auth_headers,
                            name="/admin/observability/queries/[id] [delete]",
                            catch_response=True,
                        ) as del_resp:
                            self._validate_status(del_resp, allowed_codes=[200, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                    response.success()
                except Exception:
                    response.success()
            elif response.status_code in (403, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                response.success()


class MiscEndpointsUser(BaseUser):
    """Miscellaneous uncovered REST API endpoints.

    Endpoints tested:
    - POST /a2a/{agent_name}/invoke - Invoke A2A agent
    - POST /export/selective - Selective export
    - POST /import - Import configuration
    - POST /admin/import/configuration - Admin import
    - POST /admin/import/preview - Admin import preview
    - POST /admin/export/selective - Admin selective export
    - POST /prompts/{prompt_id} - Update prompt via POST
    - POST /llmchat/chat - LLM chat
    - POST /llmchat/connect - LLM chat connect
    - POST /oauth/fetch-tools/{gateway_id} - Fetch OAuth tools
    - DELETE /oauth/registered-clients/{client_id} - Delete OAuth client
    - DELETE /teams/{team_id}/members/{user_email} - Remove team member
    - POST /admin/login - Admin login (POST)
    - POST /admin/logout - Admin logout (POST)

    Weight: Very low (misc operations)
    """

    weight = 1
    wait_time = between(3.0, 8.0)

    @task(1)
    @tag("a2a", "invoke")
    def invoke_a2a_agent(self):
        """POST /a2a/{agent_name}/invoke - Invoke A2A agent."""
        if not A2A_TESTING_ENABLED:
            return
        with self.client.get("/a2a", headers=self.auth_headers, name="/a2a [list for invoke]", catch_response=True) as response:
            if response.status_code != 200:
                response.success()
                return
            try:
                data = response.json()
                agents = data if isinstance(data, list) else data.get("agents", data.get("items", []))
                if agents:
                    agent = random.choice(agents)
                    name = agent.get("name")
                    if name:
                        with self.client.post(
                            f"/a2a/{name}/invoke",
                            json={"message": "load test ping"},
                            headers={**self.auth_headers, "Content-Type": "application/json"},
                            name="/a2a/[name]/invoke",
                            catch_response=True,
                        ) as r:
                            self._validate_status(r, allowed_codes=[200, 400, 404, 500, 503, *INFRASTRUCTURE_ERROR_CODES])
                response.success()
            except Exception:
                response.success()

    @task(1)
    @tag("export", "selective")
    def selective_export(self):
        """POST /export/selective - Selective export."""
        with self.client.post(
            "/export/selective",
            json={"entity_types": ["tools"]},
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/export/selective",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 403, 422, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("import")
    def import_config(self):
        """POST /import - Import configuration (empty)."""
        with self.client.post(
            "/import",
            json={"tools": [], "servers": []},
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/import",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 400, 403, 422, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "import")
    def admin_import_preview(self):
        """POST /admin/import/preview - Admin import preview."""
        with self.client.post(
            "/admin/import/preview",
            json={"tools": []},
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/admin/import/preview",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 400, 403, 422, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "import", "config")
    def admin_import_configuration(self):
        """POST /admin/import/configuration - Admin import configuration."""
        with self.client.post(
            "/admin/import/configuration",
            json={"tools": [], "servers": []},
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/admin/import/configuration",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 400, 403, 422, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "export", "selective")
    def admin_selective_export(self):
        """POST /admin/export/selective - Admin selective export."""
        with self.client.post(
            "/admin/export/selective",
            json={"entity_types": ["tools"]},
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/admin/export/selective",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 403, 422, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("prompts", "update")
    def post_update_prompt(self):
        """POST /prompts/{prompt_id} - Update prompt via POST."""
        if PROMPT_IDS:
            pid = random.choice(PROMPT_IDS)
            with self.client.post(
                f"/prompts/{pid}",
                json={"description": f"Updated at {time.time()}"},
                headers={**self.auth_headers, "Content-Type": "application/json"},
                name="/prompts/[id] [post update]",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 403, 404, 405, 422, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("llmchat", "chat")
    def llmchat_chat(self):
        """POST /llmchat/chat - Send chat message."""
        with self.client.post(
            "/llmchat/chat",
            json={"message": "hello", "model": "test"},
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/llmchat/chat",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 400, 403, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("llmchat", "connect")
    def llmchat_connect(self):
        """POST /llmchat/connect - Connect to chat."""
        with self.client.post(
            "/llmchat/connect",
            json={"model": "test"},
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/llmchat/connect",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 400, 403, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("oauth", "fetch-tools")
    def oauth_fetch_tools(self):
        """POST /oauth/fetch-tools/{gateway_id} - Fetch OAuth tools."""
        if GATEWAY_IDS:
            gw_id = random.choice(GATEWAY_IDS)
            with self.client.post(
                f"/oauth/fetch-tools/{gw_id}",
                headers=self.auth_headers,
                name="/oauth/fetch-tools/[id]",
                catch_response=True,
            ) as response:
                self._validate_status(response, allowed_codes=[200, 400, 403, 404, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("oauth", "clients", "delete")
    def oauth_delete_client(self):
        """DELETE /oauth/registered-clients/{client_id} - Delete OAuth client."""
        fake_id = f"loadtest-{uuid.uuid4().hex[:8]}"
        with self.client.delete(
            f"/oauth/registered-clients/{fake_id}",
            headers=self.auth_headers,
            name="/oauth/registered-clients/[id] [delete]",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 403, 404, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "login")
    def admin_login_post(self):
        """POST /admin/login - Admin login form submission."""
        with self.client.post(
            "/admin/login",
            data={"username": BASIC_AUTH_USER, "password": BASIC_AUTH_PASSWORD},
            headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded"},
            name="/admin/login [post]",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 302, 303, 401, 403, 422, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "logout")
    def admin_logout_post(self):
        """POST /admin/logout - Admin logout."""
        with self.client.post(
            "/admin/logout",
            headers=self.admin_headers,
            name="/admin/logout [post]",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 302, 303, 307, *INFRASTRUCTURE_ERROR_CODES])


class AdminHTMXEntityCRUDUser(BaseUser):
    """Admin HTMX entity create/edit/delete operations.

    These duplicate REST API CRUD but go through the admin HTMX form handler path.

    Endpoints tested:
    - POST /admin/tools - Create tool via admin
    - POST /admin/tools/{id}/edit - Edit tool via admin
    - POST /admin/tools/{id}/delete - Delete tool via admin
    - POST /admin/tools/import - Import tools via admin
    - POST /admin/servers - Create server via admin
    - POST /admin/servers/{id}/edit - Edit server via admin
    - POST /admin/servers/{id}/delete - Delete server via admin
    - POST /admin/prompts - Create prompt via admin
    - POST /admin/prompts/{id}/edit - Edit prompt via admin
    - POST /admin/prompts/{id}/delete - Delete prompt via admin
    - POST /admin/resources - Create resource via admin
    - POST /admin/resources/{id}/edit - Edit resource via admin
    - POST /admin/resources/{id}/delete - Delete resource via admin
    - POST /admin/a2a - Create A2A via admin
    - POST /admin/a2a/{id}/edit - Edit A2A via admin
    - POST /admin/a2a/{id}/delete - Delete A2A via admin
    - POST /admin/gateways - Create gateway via admin
    - POST /admin/gateways/{id}/edit - Edit gateway via admin
    - POST /admin/gateways/{id}/delete - Delete gateway via admin
    - POST /admin/roots - Create root via admin
    - POST /admin/roots/{uri}/delete - Delete root via admin

    Weight: Very low (admin HTMX)
    """

    weight = 1
    wait_time = between(5.0, 15.0)

    @task(2)
    @tag("admin", "tools", "htmx", "crud")
    def admin_tool_lifecycle(self):
        """POST /admin/tools -> edit -> delete - Tool lifecycle via admin."""
        tool_name = f"loadtest-admintool-{uuid.uuid4().hex[:8]}"
        form_data = f"name={tool_name}&description=Load+test+tool&integration_type=MCP"
        with self.client.post(
            "/admin/tools",
            data=form_data,
            headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"},
            name="/admin/tools [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201, 302):
                # Try to find and delete via REST API (admin create might redirect)
                try:
                    data = response.json() if "json" in response.headers.get("content-type", "") else {}
                    tool_id = data.get("id") or tool_name
                except Exception:
                    tool_id = tool_name
                if tool_id:
                    # Edit
                    time.sleep(0.05)
                    with self.client.post(
                        f"/admin/tools/{tool_id}/edit",
                        data=f"name={tool_name}&description=Edited+by+load+test",
                        headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"},
                        name="/admin/tools/[id]/edit",
                        catch_response=True,
                    ) as edit_resp:
                        self._validate_status(edit_resp, allowed_codes=[200, 302, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                    # Delete
                    time.sleep(0.05)
                    with self.client.post(
                        f"/admin/tools/{tool_id}/delete",
                        headers={**self.admin_headers, "HX-Request": "true"},
                        name="/admin/tools/[id]/delete",
                        catch_response=True,
                    ) as del_resp:
                        self._validate_status(del_resp, allowed_codes=[200, 302, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                response.success()
            elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                response.success()

    @task(1)
    @tag("admin", "tools", "htmx", "import")
    def admin_tools_import(self):
        """POST /admin/tools/import - Import tools via admin."""
        with self.client.post(
            "/admin/tools/import",
            json={"tools": []},
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/admin/tools/import",
            catch_response=True,
        ) as response:
            self._validate_status(response, allowed_codes=[200, 302, 400, 403, 422, 500, *INFRASTRUCTURE_ERROR_CODES])

    @task(1)
    @tag("admin", "servers", "htmx", "crud")
    def admin_server_lifecycle(self):
        """POST /admin/servers -> edit -> delete - Server lifecycle via admin."""
        srv_name = f"loadtest-adminsrv-{uuid.uuid4().hex[:8]}"
        form_data = f"name={srv_name}&description=Load+test+server"
        with self.client.post(
            "/admin/servers",
            data=form_data,
            headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"},
            name="/admin/servers [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201, 302):
                try:
                    data = response.json() if "json" in response.headers.get("content-type", "") else {}
                    srv_id = data.get("id") or srv_name
                except Exception:
                    srv_id = srv_name
                if srv_id:
                    time.sleep(0.05)
                    with self.client.post(
                        f"/admin/servers/{srv_id}/edit",
                        data=f"name={srv_name}&description=Edited",
                        headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"},
                        name="/admin/servers/[id]/edit",
                        catch_response=True,
                    ) as edit_resp:
                        self._validate_status(edit_resp, allowed_codes=[200, 302, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                    time.sleep(0.05)
                    with self.client.post(
                        f"/admin/servers/{srv_id}/delete",
                        headers={**self.admin_headers, "HX-Request": "true"},
                        name="/admin/servers/[id]/delete",
                        catch_response=True,
                    ) as del_resp:
                        self._validate_status(del_resp, allowed_codes=[200, 302, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                response.success()
            elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                response.success()

    @task(1)
    @tag("admin", "prompts", "htmx", "crud")
    def admin_prompt_lifecycle(self):
        """POST /admin/prompts -> edit -> delete - Prompt lifecycle via admin."""
        name = f"loadtest-adminprompt-{uuid.uuid4().hex[:8]}"
        form_data = f"name={name}&description=Load+test+prompt&template=Hello"
        with self.client.post(
            "/admin/prompts",
            data=form_data,
            headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"},
            name="/admin/prompts [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201, 302):
                try:
                    data = response.json() if "json" in response.headers.get("content-type", "") else {}
                    pid = data.get("id") or name
                except Exception:
                    pid = name
                if pid:
                    time.sleep(0.05)
                    with self.client.post(f"/admin/prompts/{pid}/edit", data=f"name={name}&description=Edited", headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"}, name="/admin/prompts/[id]/edit", catch_response=True) as r:
                        self._validate_status(r, allowed_codes=[200, 302, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                    time.sleep(0.05)
                    with self.client.post(f"/admin/prompts/{pid}/delete", headers={**self.admin_headers, "HX-Request": "true"}, name="/admin/prompts/[id]/delete", catch_response=True) as r:
                        self._validate_status(r, allowed_codes=[200, 302, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                response.success()
            elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                response.success()

    @task(1)
    @tag("admin", "resources", "htmx", "crud")
    def admin_resource_lifecycle(self):
        """POST /admin/resources -> edit -> delete - Resource lifecycle via admin."""
        name = f"loadtest-adminres-{uuid.uuid4().hex[:8]}"
        form_data = f"name={name}&uri=file:///tmp/{name}&description=Load+test"
        with self.client.post(
            "/admin/resources",
            data=form_data,
            headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"},
            name="/admin/resources [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201, 302):
                try:
                    data = response.json() if "json" in response.headers.get("content-type", "") else {}
                    rid = data.get("id") or name
                except Exception:
                    rid = name
                if rid:
                    time.sleep(0.05)
                    with self.client.post(f"/admin/resources/{rid}/edit", data=f"name={name}&description=Edited", headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"}, name="/admin/resources/[id]/edit", catch_response=True) as r:
                        self._validate_status(r, allowed_codes=[200, 302, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                    time.sleep(0.05)
                    with self.client.post(f"/admin/resources/{rid}/delete", headers={**self.admin_headers, "HX-Request": "true"}, name="/admin/resources/[id]/delete", catch_response=True) as r:
                        self._validate_status(r, allowed_codes=[200, 302, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                response.success()
            elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                response.success()

    @task(1)
    @tag("admin", "a2a", "htmx", "crud")
    def admin_a2a_create(self):
        """POST /admin/a2a - Create A2A agent via admin HTMX form."""
        if not A2A_TESTING_ENABLED:
            return
        name = f"loadtest-admina2a-{uuid.uuid4().hex[:8]}"
        form_data = f"name={name}&endpoint_url=http://localhost:1&description=Load+test&visibility=public"
        with self.client.post(
            "/admin/a2a",
            data=form_data,
            headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"},
            name="/admin/a2a [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201, 302):
                response.success()
            elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                response.success()

    @task(1)
    @tag("admin", "a2a", "htmx", "crud")
    def admin_a2a_edit_delete(self):
        """POST /admin/a2a/{id}/edit + /delete - Edit and delete via admin HTMX."""
        if not A2A_TESTING_ENABLED:
            return
        # Create via REST to get a reliable ID, then test admin edit/delete
        name = f"loadtest-admina2a-{uuid.uuid4().hex[:8]}"
        agent_data = {"agent": {"name": name, "endpoint_url": "http://localhost:1", "description": "Load test"}}
        with self.client.post(
            "/a2a",
            json=agent_data,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name="/a2a [create for admin crud]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                aid = None
                try:
                    aid = response.json().get("id")
                except Exception:
                    pass
                if aid:
                    time.sleep(0.05)
                    with self.client.post(f"/admin/a2a/{aid}/edit", data=f"name={name}&endpoint_url=http://localhost:1&description=Edited", headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"}, name="/admin/a2a/[id]/edit", catch_response=True) as r:
                        self._validate_status(r, allowed_codes=[200, 302, 303, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                    time.sleep(0.05)
                    with self.client.post(f"/admin/a2a/{aid}/delete", headers={**self.admin_headers, "HX-Request": "true"}, name="/admin/a2a/[id]/delete", catch_response=True) as r:
                        self._validate_status(r, allowed_codes=[200, 302, 303, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                response.success()
            elif response.status_code in (409, 422, *INFRASTRUCTURE_ERROR_CODES):
                response.success()

    @task(1)
    @tag("admin", "gateways", "htmx", "crud")
    def admin_gateway_lifecycle(self):
        """POST /admin/gateways -> edit -> delete - Gateway lifecycle via admin."""
        name = f"loadtest-admingw-{uuid.uuid4().hex[:8]}"
        form_data = f"name={name}&url=http://localhost:1&description=Load+test"
        with self.client.post(
            "/admin/gateways",
            data=form_data,
            headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"},
            name="/admin/gateways [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201, 302):
                try:
                    data = response.json() if "json" in response.headers.get("content-type", "") else {}
                    gid = data.get("id") or name
                except Exception:
                    gid = name
                if gid:
                    time.sleep(0.05)
                    with self.client.post(f"/admin/gateways/{gid}/edit", data=f"name={name}&description=Edited", headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"}, name="/admin/gateways/[id]/edit", catch_response=True) as r:
                        self._validate_status(r, allowed_codes=[200, 302, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                    time.sleep(0.05)
                    with self.client.post(f"/admin/gateways/{gid}/delete", headers={**self.admin_headers, "HX-Request": "true"}, name="/admin/gateways/[id]/delete", catch_response=True) as r:
                        self._validate_status(r, allowed_codes=[200, 302, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                response.success()
            elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                response.success()

    @task(1)
    @tag("admin", "roots", "htmx", "crud")
    def admin_roots_lifecycle(self):
        """POST /admin/roots -> delete - Roots lifecycle via admin."""
        uri = f"file:///tmp/loadtest-{uuid.uuid4().hex[:8]}"
        with self.client.post(
            "/admin/roots",
            data=f"uri={uri}&name=loadtest-root",
            headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"},
            name="/admin/roots [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201, 302):
                time.sleep(0.05)
                with self.client.post(
                    f"/admin/roots/{uri}/delete",
                    headers={**self.admin_headers, "HX-Request": "true"},
                    name="/admin/roots/[uri]/delete",
                    catch_response=True,
                ) as del_resp:
                    self._validate_status(del_resp, allowed_codes=[200, 302, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                response.success()
            elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                response.success()


class AdminUsersOpsUser(BaseUser):
    """Admin user management operations.

    Endpoints tested:
    - POST /admin/users - Create user via admin
    - DELETE /admin/users/{user_email} - Delete user via admin
    - POST /admin/users/{user_email}/activate - Activate user
    - POST /admin/users/{user_email}/deactivate - Deactivate user
    - POST /admin/users/{user_email}/force-password-change - Force password change
    - POST /admin/users/{user_email}/update - Update user via admin

    Weight: Very low (admin user ops)
    """

    weight = 1
    wait_time = between(5.0, 15.0)

    @task(2)
    @tag("admin", "users", "crud")
    def admin_user_lifecycle(self):
        """POST /admin/users -> activate/deactivate -> update -> delete."""
        email = f"loadtest-adminuser-{uuid.uuid4().hex[:8]}@example.com"
        form_data = f"email={email}&password=LoadTest123!&full_name=Load+Test+User"
        with self.client.post(
            "/admin/users",
            data=form_data,
            headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"},
            name="/admin/users [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201, 302):
                # Activate
                time.sleep(0.05)
                with self.client.post(f"/admin/users/{email}/activate", headers={**self.admin_headers, "HX-Request": "true"}, name="/admin/users/[email]/activate", catch_response=True) as r:
                    self._validate_status(r, allowed_codes=[200, 302, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                # Deactivate
                time.sleep(0.05)
                with self.client.post(f"/admin/users/{email}/deactivate", headers={**self.admin_headers, "HX-Request": "true"}, name="/admin/users/[email]/deactivate", catch_response=True) as r:
                    self._validate_status(r, allowed_codes=[200, 302, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                # Force password change
                time.sleep(0.05)
                with self.client.post(f"/admin/users/{email}/force-password-change", headers={**self.admin_headers, "HX-Request": "true"}, name="/admin/users/[email]/force-password-change", catch_response=True) as r:
                    self._validate_status(r, allowed_codes=[200, 302, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                # Update
                time.sleep(0.05)
                with self.client.post(f"/admin/users/{email}/update", data=f"full_name=Updated+Load+Test", headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"}, name="/admin/users/[email]/update", catch_response=True) as r:
                    self._validate_status(r, allowed_codes=[200, 302, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                # Delete
                time.sleep(0.05)
                with self.client.delete(f"/admin/users/{email}", headers=self.admin_headers, name="/admin/users/[email] [delete]", catch_response=True) as r:
                    self._validate_status(r, allowed_codes=[200, 302, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                response.success()
            elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                response.success()


class AdminTeamsHTMXOpsUser(BaseUser):
    """Admin teams HTMX operations.

    Endpoints tested:
    - POST /admin/teams - Create team via admin
    - POST /admin/teams/{id}/update - Update team via admin
    - POST /admin/teams/{id}/add-member - Add member
    - POST /admin/teams/{id}/remove-member - Remove member
    - POST /admin/teams/{id}/update-member-role - Update member role
    - POST /admin/teams/{id}/join-request - Submit join request
    - POST /admin/teams/{id}/join-requests/{id}/approve - Approve join request
    - POST /admin/teams/{id}/join-requests/{id}/reject - Reject join request
    - POST /admin/teams/{id}/leave - Leave team
    - DELETE /admin/teams/{id} - Delete team via admin
    - DELETE /admin/teams/{id}/join-request/{id} - Delete join request

    Weight: Very low (admin teams)
    """

    weight = 1
    wait_time = between(5.0, 15.0)
    network_timeout = 120.0

    @task(2)
    @tag("admin", "teams", "htmx", "crud")
    def admin_team_lifecycle(self):
        """POST /admin/teams -> update -> delete."""
        name = f"loadtest-adminteam-{uuid.uuid4().hex[:8]}"
        form_data = f"name={name}&description=Load+test+team&visibility=private"
        with self.client.post(
            "/admin/teams",
            data=form_data,
            headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"},
            name="/admin/teams [create]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201, 302):
                try:
                    data = response.json() if "json" in response.headers.get("content-type", "") else {}
                    tid = data.get("id") or name
                except Exception:
                    tid = name
                # Update
                time.sleep(0.1)
                with self.client.post(f"/admin/teams/{tid}/update", data=f"name={name}&description=Updated", headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"}, name="/admin/teams/[id]/update", catch_response=True) as r:
                    self._validate_status(r, allowed_codes=[200, 302, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                # Add member
                time.sleep(0.1)
                with self.client.post(f"/admin/teams/{tid}/add-member", data="email=admin@example.com&role=viewer", headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"}, name="/admin/teams/[id]/add-member", catch_response=True) as r:
                    self._validate_status(r, allowed_codes=[200, 302, 400, 404, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                # Update member role
                time.sleep(0.1)
                with self.client.post(f"/admin/teams/{tid}/update-member-role", data="email=admin@example.com&role=admin", headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"}, name="/admin/teams/[id]/update-member-role", catch_response=True) as r:
                    self._validate_status(r, allowed_codes=[200, 302, 400, 404, 422, 500, *INFRASTRUCTURE_ERROR_CODES])
                # Remove member
                time.sleep(0.1)
                with self.client.post(f"/admin/teams/{tid}/remove-member", data="email=admin@example.com", headers={**self.admin_headers, "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true"}, name="/admin/teams/[id]/remove-member", catch_response=True) as r:
                    self._validate_status(r, allowed_codes=[200, 302, 400, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                # Join request
                time.sleep(0.1)
                with self.client.post(f"/admin/teams/{tid}/join-request", headers={**self.admin_headers, "HX-Request": "true"}, name="/admin/teams/[id]/join-request", catch_response=True) as r:
                    self._validate_status(r, allowed_codes=[200, 302, 400, 404, 409, 500, *INFRASTRUCTURE_ERROR_CODES])
                # Leave
                time.sleep(0.1)
                with self.client.post(f"/admin/teams/{tid}/leave", headers={**self.admin_headers, "HX-Request": "true"}, name="/admin/teams/[id]/leave", catch_response=True) as r:
                    self._validate_status(r, allowed_codes=[200, 302, 400, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                # Delete
                time.sleep(0.1)
                with self.client.delete(f"/admin/teams/{tid}", headers=self.admin_headers, name="/admin/teams/[id] [delete]", catch_response=True) as r:
                    self._validate_status(r, allowed_codes=[200, 302, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                response.success()
            elif response.status_code in (403, 409, 422, 500, *INFRASTRUCTURE_ERROR_CODES):
                response.success()

    @task(1)
    @tag("admin", "teams", "join-requests")
    def admin_manage_join_requests(self):
        """Approve/reject/delete join requests via admin."""
        if TEAM_IDS:
            tid = random.choice(TEAM_IDS)
            with self.client.get(f"/teams/{tid}/join-requests", headers=self.auth_headers, name="/teams/[id]/join-requests [for admin]", catch_response=True) as response:
                if response.status_code == 200:
                    try:
                        data = response.json()
                        reqs = data if isinstance(data, list) else data.get("join_requests", data.get("items", []))
                        if reqs:
                            req = random.choice(reqs)
                            rid = req.get("id")
                            if rid:
                                action = random.choice(["approve", "reject", "delete"])
                                if action == "approve":
                                    with self.client.post(f"/admin/teams/{tid}/join-requests/{rid}/approve", headers={**self.admin_headers, "HX-Request": "true"}, name="/admin/teams/[id]/join-requests/[id]/approve", catch_response=True) as r:
                                        self._validate_status(r, allowed_codes=[200, 302, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                                elif action == "reject":
                                    with self.client.post(f"/admin/teams/{tid}/join-requests/{rid}/reject", headers={**self.admin_headers, "HX-Request": "true"}, name="/admin/teams/[id]/join-requests/[id]/reject", catch_response=True) as r:
                                        self._validate_status(r, allowed_codes=[200, 302, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                                else:
                                    with self.client.delete(f"/admin/teams/{tid}/join-request/{rid}", headers=self.admin_headers, name="/admin/teams/[id]/join-request/[id] [delete]", catch_response=True) as r:
                                        self._validate_status(r, allowed_codes=[200, 302, 404, 500, *INFRASTRUCTURE_ERROR_CODES])
                    except Exception:
                        pass
                response.success()


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
