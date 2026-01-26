# -*- coding: utf-8 -*-
"""Locust load test for detecting CPU spin loop bug (Issue #2360).

This test uses a spike/drop pattern to stress-test session cleanup:
1. Ramp up to high user count (creates many connections/tasks)
2. Drop to 0 users (triggers cleanup of all sessions)
3. Pause to observe CPU behavior (should return to idle)
4. Repeat multiple cycles

The CPU spin loop bug causes workers to consume 100% CPU each when idle
after clients disconnect, due to orphaned asyncio tasks in anyio's
_deliver_cancellation loop.

This is a FULL-FEATURED load test (not simplified) that uses:
- JWT authentication (auto-generated or from MCPGATEWAY_BEARER_TOKEN)
- All user classes from the main locustfile (API, RPC, Admin, FastTime, etc.)
- Entity ID fetching on test start
- Same patterns and weights as load-test-ui

See: https://github.com/IBM/mcp-context-forge/issues/2360

Usage:
    make load-test-spin-detector

    # Or directly:
    cd tests/loadtest && locust -f locustfile_spin_detector.py \
        --host=http://localhost:4444 --headless

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import logging
import os
import random
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Third-Party
from locust import LoadTestShape, between, constant_throughput, events, tag, task
from locust.contrib.fasthttp import FastHttpUser
from locust.runners import MasterRunner, WorkerRunner

# Configure logging - WARNING level to reduce noise in multi-worker mode
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)  # Suppress INFO messages from this module


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
        return env_vars

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
JWT_USERNAME = _get_config("JWT_USERNAME", _get_config("PLATFORM_ADMIN_EMAIL", "admin@example.com"))
# Token expiry in hours - default 8760 (1 year) to avoid expiration during long load tests
JWT_TOKEN_EXPIRY_HOURS = int(_get_config("LOADTEST_JWT_EXPIRY_HOURS", "8760"))

# Test data pools (populated during test setup)
TOOL_IDS: list[str] = []
SERVER_IDS: list[str] = []
GATEWAY_IDS: list[str] = []
RESOURCE_IDS: list[str] = []
PROMPT_IDS: list[str] = []

# Names/URIs for RPC calls
TOOL_NAMES: list[str] = []
RESOURCE_URIS: list[str] = []
PROMPT_NAMES: list[str] = []

# Tools that require arguments - excluded from generic rpc_call_tool
TOOLS_WITH_REQUIRED_ARGS: set[str] = {
    "fast-time-convert-time",
    "fast-time-get-system-time",
    "fast-test-echo",
    "fast-test-get-system-time",
}


# =============================================================================
# ANSI Color Codes
# =============================================================================
class Colors:
    """ANSI color codes for terminal output."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground colors
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

    # Background colors
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"

    @classmethod
    def disable(cls) -> None:
        """Disable colors (for non-TTY output)."""
        for attr in dir(cls):
            if not attr.startswith("_") and isinstance(getattr(cls, attr), str):
                setattr(cls, attr, "")


# Disable colors if not a TTY
if not sys.stdout.isatty():
    Colors.disable()


# =============================================================================
# Logging Setup
# =============================================================================
# Fixed log file path for easy monitoring: tail -f /tmp/spin_detector.log
LOG_FILE = "/tmp/spin_detector.log"
_log_file_handle = None


def _init_log_file() -> None:
    """Initialize the log file."""
    global _log_file_handle
    try:
        _log_file_handle = open(LOG_FILE, "w", encoding="utf-8")
        _log_file_handle.write("# CPU Spin Loop Detector Log\n")
        _log_file_handle.write(f"# Started: {datetime.now().isoformat()}\n")
        _log_file_handle.write("# Issue: https://github.com/IBM/mcp-context-forge/issues/2360\n")
        _log_file_handle.write("#" + "=" * 79 + "\n\n")
        _log_file_handle.flush()
    except Exception as e:
        print(f"{Colors.YELLOW}Warning: Could not create log file: {e}{Colors.RESET}")


def _close_log_file() -> None:
    """Close the log file."""
    global _log_file_handle
    if _log_file_handle:
        _log_file_handle.write(f"\n# Finished: {datetime.now().isoformat()}\n")
        _log_file_handle.close()
        _log_file_handle = None


def log(message: str, to_console: bool = True) -> None:
    """Log a message to both console and file.

    Args:
        message: Message to log (may contain ANSI codes for console).
        to_console: Whether to print to console.
    """
    timestamp = datetime.now().strftime("%H:%M:%S")

    if to_console:
        print(message)
        sys.stdout.flush()

    if _log_file_handle:
        # Strip ANSI codes for file
        clean_msg = message
        for attr in dir(Colors):
            if not attr.startswith("_") and isinstance(getattr(Colors, attr), str):
                clean_msg = clean_msg.replace(getattr(Colors, attr), "")
        _log_file_handle.write(f"[{timestamp}] {clean_msg}\n")
        _log_file_handle.flush()


# =============================================================================
# Docker Stats
# =============================================================================
def get_docker_stats() -> tuple[str, list[tuple[str, float]]]:
    """Get docker stats for gateway containers.

    Returns:
        Tuple of (formatted output string, list of (container_name, cpu_percent)).
    """
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            gateway_lines = []
            cpu_values = []

            for line in lines:
                if "gateway" in line.lower():
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        name = parts[0]
                        cpu_str = parts[1].replace("%", "")
                        try:
                            cpu = float(cpu_str)
                            cpu_values.append((name, cpu))
                        except ValueError:
                            cpu = 0.0
                        gateway_lines.append(line)

            if gateway_lines:
                header = f"{'CONTAINER':<40} {'CPU %':>10} {'MEMORY':>20}"
                formatted = header + "\n" + "-" * 72 + "\n"
                for line in gateway_lines:
                    parts = line.split("\t")
                    if len(parts) >= 3:
                        formatted += f"{parts[0]:<40} {parts[1]:>10} {parts[2]:>20}\n"
                return formatted, cpu_values
            return "(no gateway containers found)", []
        return f"(docker stats failed: {result.stderr})", []
    except subprocess.TimeoutExpired:
        return "(docker stats timed out)", []
    except FileNotFoundError:
        return "(docker not found)", []
    except Exception as e:
        return f"(error: {e})", []


def format_cpu_status(cpu_values: list[tuple[str, float]]) -> str:
    """Format CPU status with color-coded health indicator.

    Args:
        cpu_values: List of (container_name, cpu_percent) tuples.

    Returns:
        Formatted status string with colors.
    """
    if not cpu_values:
        return f"{Colors.YELLOW}[?] No CPU data{Colors.RESET}"

    max_cpu = max(cpu for _, cpu in cpu_values)
    total_cpu = sum(cpu for _, cpu in cpu_values)

    if max_cpu < 10:
        icon = f"{Colors.GREEN}{Colors.BOLD}[PASS]{Colors.RESET}"
        status = f"{Colors.GREEN}CPU idle - cleanup working correctly{Colors.RESET}"
    elif max_cpu < 50:
        icon = f"{Colors.YELLOW}{Colors.BOLD}[WARN]{Colors.RESET}"
        status = f"{Colors.YELLOW}CPU moderate - may be processing{Colors.RESET}"
    else:
        icon = f"{Colors.RED}{Colors.BOLD}[FAIL]{Colors.RESET}"
        status = f"{Colors.RED}CPU HIGH - possible spin loop!{Colors.RESET}"

    return f"{icon} Total: {total_cpu:.1f}% | Max: {max_cpu:.1f}% - {status}"


# =============================================================================
# Pretty Printing
# =============================================================================
def print_box(title: str, content: str, color: str = Colors.CYAN, width: int = 80) -> None:
    """Print a colored box with title and content.

    Args:
        title: Box title.
        content: Box content.
        color: Color for the border.
        width: Box width.
    """
    top = f"{color}{'=' * width}{Colors.RESET}"
    log(top)
    log(f"{color}{Colors.BOLD}{title.center(width)}{Colors.RESET}")
    log(f"{color}{'=' * width}{Colors.RESET}")
    if content:
        for line in content.split("\n"):
            log(line)


def print_section(title: str, color: str = Colors.BLUE) -> None:
    """Print a section header.

    Args:
        title: Section title.
        color: Color for the header.
    """
    log(f"\n{color}{Colors.BOLD}{title}{Colors.RESET}")
    log(f"{color}{'-' * len(title)}{Colors.RESET}")


# =============================================================================
# Authentication Helpers
# =============================================================================


def _generate_jwt_token() -> str:
    """Generate a JWT token for API authentication.

    Uses PyJWT to create a token with the configured secret and algorithm.
    """
    try:
        from datetime import timedelta, timezone  # pylint: disable=import-outside-toplevel

        import jwt  # pylint: disable=import-outside-toplevel

        jti = str(uuid.uuid4())
        payload = {
            "sub": JWT_USERNAME,
            "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_TOKEN_EXPIRY_HOURS),
            "iat": datetime.now(timezone.utc),
            "aud": JWT_AUDIENCE,
            "iss": JWT_ISSUER,
            "jti": jti,
        }
        token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        return token
    except ImportError:
        logger.warning("PyJWT not installed, falling back to basic auth")
        return ""
    except Exception as e:
        logger.warning(f"Failed to generate JWT token: {e}")
        return ""


# Cache the generated token
_CACHED_TOKEN: str | None = None


def _get_auth_headers() -> dict[str, str]:
    """Get authentication headers.

    Priority:
    1. MCPGATEWAY_BEARER_TOKEN env var (if set)
    2. Auto-generated JWT token (if PyJWT available)
    3. Basic auth fallback
    """
    global _CACHED_TOKEN  # pylint: disable=global-statement
    headers = {"Accept": "application/json"}

    if BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {BEARER_TOKEN}"
    else:
        if _CACHED_TOKEN is None:
            _CACHED_TOKEN = _generate_jwt_token()

        if _CACHED_TOKEN:
            headers["Authorization"] = f"Bearer {_CACHED_TOKEN}"
        else:
            import base64  # pylint: disable=import-outside-toplevel

            credentials = base64.b64encode(f"{BASIC_AUTH_USER}:{BASIC_AUTH_PASSWORD}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"
            logger.warning("Using basic auth - REST API endpoints may fail")

    return headers


def _log_auth_mode() -> None:
    """Log which authentication mode the load test will use."""
    headers = _get_auth_headers()
    auth_header = headers.get("Authorization", "")

    if auth_header.startswith("Bearer "):
        if BEARER_TOKEN:
            log(f"  {Colors.GREEN}Auth: Bearer (MCPGATEWAY_BEARER_TOKEN){Colors.RESET}")
        else:
            log(f"  {Colors.GREEN}Auth: Bearer (auto-generated JWT){Colors.RESET}")
    elif auth_header.startswith("Basic "):
        log(f"  {Colors.YELLOW}Auth: Basic (WARNING: /rpc calls may fail){Colors.RESET}")
    else:
        log(f"  {Colors.RED}Auth: None (WARNING: /rpc calls will fail){Colors.RESET}")


def _json_rpc_request(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a JSON-RPC 2.0 request."""
    return {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params or {},
    }


def _fetch_json(url: str, headers: dict[str, str], timeout: float = 30.0) -> tuple[int, Any]:
    """Fetch JSON from URL using urllib (gevent-safe).

    Args:
        url: Full URL to fetch
        headers: HTTP headers to include
        timeout: Request timeout in seconds

    Returns:
        Tuple of (status_code, json_data or None)
    """
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


# =============================================================================
# User Classes - Full-featured (matching load-test-ui)
# =============================================================================


class BaseUser(FastHttpUser):
    """Base user class with common configuration.

    Uses FastHttpUser (gevent-based) for maximum throughput.
    Optimized for 10000+ concurrent users with aggressive timing.
    """

    abstract = True
    wait_time = between(0.01, 0.1)  # Very fast - minimal wait between requests

    # Aggressive connection settings - fail fast
    connection_timeout = 5.0
    network_timeout = 5.0

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
        """Validate response is successful and contains valid JSON."""
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
        """Validate response is successful HTML."""
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
        """Validate response status code only."""
        allowed = allowed_codes or [200]
        if response.status_code not in allowed:
            response.failure(f"Expected {allowed}, got {response.status_code}")
            return False
        response.success()
        return True

    def _validate_jsonrpc_response(self, response, allowed_codes: list[int] | None = None):
        """Validate response is successful JSON-RPC (no error field)."""
        allowed = allowed_codes or [200]
        if response.status_code not in allowed:
            response.failure(f"Expected {allowed}, got {response.status_code}")
            return False
        try:
            data = response.json()
            if data is None:
                response.failure("Response JSON is null")
                return False
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
    """User that only performs health checks."""

    weight = 1
    wait_time = between(0.1, 0.3)  # Fast health checks

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


class ReadOnlyAPIUser(BaseUser):
    """User that performs read-only API operations."""

    weight = 5
    wait_time = between(0.01, 0.1)  # Aggressive

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

    @task(3)
    @tag("api", "tools")
    def get_single_tool(self):
        """Get a specific tool by ID."""
        if TOOL_IDS:
            tool_id = random.choice(TOOL_IDS)
            with self.client.get(f"/tools/{tool_id}", headers=self.auth_headers, name="/tools/[id]", catch_response=True) as response:
                self._validate_json_response(response, allowed_codes=[200, 404])

    @task(3)
    @tag("api", "servers")
    def get_single_server(self):
        """Get a specific server by ID."""
        if SERVER_IDS:
            server_id = random.choice(SERVER_IDS)
            with self.client.get(f"/servers/{server_id}", headers=self.auth_headers, name="/servers/[id]", catch_response=True) as response:
                self._validate_json_response(response, allowed_codes=[200, 404])


class MCPJsonRpcUser(BaseUser):
    """User that makes MCP JSON-RPC requests."""

    weight = 4
    wait_time = between(0.01, 0.1)  # Aggressive

    def _rpc_request(self, payload: dict, name: str):
        """Make an RPC request with proper error handling."""
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
        """JSON-RPC: Call a tool with empty arguments."""
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

    @task(3)
    @tag("mcp", "rpc", "initialize")
    def rpc_initialize(self):
        """JSON-RPC: Initialize session."""
        payload = _json_rpc_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "clientInfo": {"name": "spin-detector", "version": "1.0.0"},
            },
        )
        self._rpc_request(payload, "/rpc initialize")

    @task(2)
    @tag("mcp", "rpc", "ping")
    def rpc_ping(self):
        """JSON-RPC: Ping."""
        payload = _json_rpc_request("ping")
        self._rpc_request(payload, "/rpc ping")


class FastTimeUser(BaseUser):
    """User that calls the fast_time MCP server tools."""

    weight = 5
    wait_time = between(0.01, 0.1)  # Aggressive

    def _rpc_request(self, payload: dict, name: str):
        """Make an RPC request with proper error handling."""
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


class FastTestEchoUser(BaseUser):
    """User that calls the fast_test MCP server echo tool."""

    weight = 3
    wait_time = between(0.01, 0.1)  # Aggressive

    ECHO_MESSAGES = [
        "Hello, World!",
        "Testing MCP protocol",
        "Load test in progress",
        "Performance benchmark",
        "Echo echo echo",
        "The quick brown fox jumps over the lazy dog",
    ]

    def _rpc_request(self, payload: dict, name: str):
        """Make an RPC request with proper error handling."""
        with self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name=name,
            catch_response=True,
        ) as response:
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


class FastTestTimeUser(BaseUser):
    """User that calls the fast_test MCP server get_system_time tool."""

    weight = 3
    wait_time = between(0.01, 0.1)  # Aggressive

    TIMEZONES = [
        "UTC",
        "America/New_York",
        "America/Los_Angeles",
        "Europe/London",
        "Europe/Paris",
        "Europe/Dublin",
        "Asia/Tokyo",
    ]

    def _rpc_request(self, payload: dict, name: str):
        """Make an RPC request with proper error handling."""
        with self.client.post(
            "/rpc",
            json=payload,
            headers={**self.auth_headers, "Content-Type": "application/json"},
            name=name,
            catch_response=True,
        ) as response:
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


class WriteAPIUser(BaseUser):
    """User that performs write operations."""

    weight = 1
    wait_time = between(0.1, 0.3)  # Faster writes for stress

    def __init__(self, *args, **kwargs):
        """Initialize with tracking for cleanup."""
        super().__init__(*args, **kwargs)
        self.created_tools: list[str] = []

    def on_stop(self):
        """Clean up created entities."""
        for tool_id in self.created_tools:
            try:
                self.client.delete(f"/tools/{tool_id}", headers=self.auth_headers, name="/tools/[id] [cleanup]")
            except Exception:
                pass

    @task(5)
    @tag("api", "write", "tools")
    def create_and_delete_tool(self):
        """Create a tool and then delete it."""
        tool_name = f"spintest-tool-{uuid.uuid4().hex[:8]}"
        tool_data = {
            "name": tool_name,
            "description": "Spin detector test tool - will be deleted",
            "integration_type": "MCP",
            "input_schema": {"type": "object", "properties": {"input": {"type": "string"}}},
        }

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
                    time.sleep(0.1)
                    self.client.delete(f"/tools/{tool_id}", headers=self.auth_headers, name="/tools/[id] [delete]")
                except Exception:
                    pass
            elif response.status_code in (409, 422):
                response.success()


class StressTestUser(BaseUser):
    """User for stress testing with predictable request rate."""

    weight = 1
    wait_time = constant_throughput(2)

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


class RealisticUser(BaseUser):
    """User that simulates realistic mixed traffic."""

    weight = 10
    wait_time = between(0.01, 0.1)  # Aggressive for stress testing

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

    @task(5)
    @tag("realistic", "api")
    def get_single_tool(self):
        """Get specific tool."""
        if TOOL_IDS:
            tool_id = random.choice(TOOL_IDS)
            with self.client.get(f"/tools/{tool_id}", headers=self.auth_headers, name="/tools/[id]", catch_response=True) as response:
                self._validate_json_response(response, allowed_codes=[200, 404])


# =============================================================================
# Event Handlers
# =============================================================================


@events.init.add_listener
def on_locust_init(environment, **_kwargs):
    """Initialize test environment."""
    # Suppress noisy logging - only log on master for debugging
    if isinstance(environment.runner, MasterRunner):
        logger.debug("Running as master node")
    elif isinstance(environment.runner, WorkerRunner):
        logger.debug("Running as worker node")
    else:
        logger.debug("Running in standalone mode")


@events.test_start.add_listener
def on_test_start(environment, **_kwargs):
    """Fetch existing entity IDs for use in tests (master/standalone only)."""
    # Only fetch on master or standalone - workers don't need this
    if isinstance(environment.runner, WorkerRunner):
        return

    host = environment.host or "http://localhost:4444"
    headers = _get_auth_headers()

    try:
        # Fetch tools
        status, data = _fetch_json(f"{host}/tools", headers)
        if status == 200 and data:
            items = data if isinstance(data, list) else data.get("tools", data.get("items", []))
            TOOL_IDS.extend([str(t.get("id")) for t in items[:50] if t.get("id")])
            TOOL_NAMES.extend([str(t.get("name")) for t in items[:50] if t.get("name")])

        # Fetch servers
        status, data = _fetch_json(f"{host}/servers", headers)
        if status == 200 and data:
            items = data if isinstance(data, list) else data.get("servers", data.get("items", []))
            SERVER_IDS.extend([str(s.get("id")) for s in items[:50] if s.get("id")])

        # Fetch gateways
        status, data = _fetch_json(f"{host}/gateways", headers)
        if status == 200 and data:
            items = data if isinstance(data, list) else data.get("gateways", data.get("items", []))
            GATEWAY_IDS.extend([str(g.get("id")) for g in items[:50] if g.get("id")])

        # Fetch resources
        status, data = _fetch_json(f"{host}/resources", headers)
        if status == 200 and data:
            items = data if isinstance(data, list) else data.get("resources", data.get("items", []))
            RESOURCE_IDS.extend([str(r.get("id")) for r in items[:50] if r.get("id")])
            RESOURCE_URIS.extend([str(r.get("uri")) for r in items[:50] if r.get("uri")])

        # Fetch prompts
        status, data = _fetch_json(f"{host}/prompts", headers)
        if status == 200 and data:
            items = data if isinstance(data, list) else data.get("prompts", data.get("items", []))
            PROMPT_IDS.extend([str(p.get("id")) for p in items[:50] if p.get("id")])
            PROMPT_NAMES.extend([str(p.get("name")) for p in items[:50] if p.get("name")])

    except Exception:
        pass  # Tests will continue without pre-fetched IDs


@events.test_stop.add_listener
def on_test_stop(environment, **_kwargs):
    """Clean up on test stop (master/standalone only)."""
    # Only run cleanup on master or standalone
    if isinstance(environment.runner, WorkerRunner):
        return

    TOOL_IDS.clear()
    SERVER_IDS.clear()
    GATEWAY_IDS.clear()
    RESOURCE_IDS.clear()
    PROMPT_IDS.clear()
    TOOL_NAMES.clear()
    RESOURCE_URIS.clear()
    PROMPT_NAMES.clear()

    _close_log_file()
    log(f"\n{Colors.DIM}Log saved to: {LOG_FILE}{Colors.RESET}\n")


# =============================================================================
# Load Shape - Spike/Drop Pattern for CPU Spin Detection
# =============================================================================
class SpinDetectorShape(LoadTestShape):
    """Load shape with spike/drop pattern for detecting CPU spin loops.

    Pattern:
    - Ramp up to target users over ramp_time
    - Sustain load for sustain_time
    - Drop to 0 users
    - Pause for pause_time (monitor CPU - should return to idle)
    - Repeat for multiple cycles

    If CPU stays high during pause phases, the spin loop bug is present.
    """

    # Configuration for each cycle: (target_users, ramp_time, sustain_time, pause_time)
    # AGGRESSIVE pattern: 4000 → cancel → 4000 → cancel → 10000 → cancel
    # Designed to quickly trigger and detect CPU spin loop
    cycles = [
        (4000, 4, 5, 10),    # Cycle A: 4000 users, fast ramp, short sustain, 10s pause
        (4000, 4, 5, 10),    # Cycle B: 4000 users again
        (10000, 10, 5, 10),  # Cycle C: 10000 users (stress test)
        (4000, 4, 5, 10),    # Cycle D: Back to 4000
        (10000, 10, 5, 10),  # Cycle E: 10000 again
    ]

    spawn_rate = 1000  # FAST spawn rate for aggressive testing

    def __init__(self):
        """Initialize the load shape."""
        super().__init__()
        self._current_cycle = 0
        self._cycle_start_time = 0
        self._last_phase = None
        self._pause_stats: list[tuple[int, float]] = []  # (cycle, max_cpu) during pauses
        self._banner_printed = False
        self._total_cycles = 0  # Track total cycles across all iterations

    def tick(self) -> Optional[tuple[int, float]]:
        """Calculate the current target user count and spawn rate."""
        # Print banner on first tick (before any phase output)
        if not self._banner_printed:
            self._banner_printed = True
            self._print_banner()

        run_time = self.get_run_time()

        # Loop indefinitely - reset to cycle 0 when we reach the end
        if self._current_cycle >= len(self.cycles):
            self._current_cycle = 0
            self._last_phase = None  # Reset phase to trigger new cycle logging

        target_users, ramp_time, sustain_time, pause_time = self.cycles[self._current_cycle]
        cycle_duration = ramp_time + sustain_time + pause_time

        if self._cycle_start_time == 0:
            self._cycle_start_time = run_time

        cycle_time = run_time - self._cycle_start_time

        if cycle_time < ramp_time:
            phase = "ramp"
            progress = cycle_time / ramp_time
            users = max(1, int(target_users * progress))  # At least 1 user during ramp
        elif cycle_time < ramp_time + sustain_time:
            phase = "sustain"
            users = target_users
        elif cycle_time < cycle_duration:
            phase = "pause"
            users = 0
        else:
            self._current_cycle += 1
            self._total_cycles += 1
            self._cycle_start_time = run_time
            self._last_phase = None
            return self.tick()

        if phase != self._last_phase:
            self._log_phase_change(phase, users, target_users)
            self._last_phase = phase

        return (users, self.spawn_rate)

    def _print_banner(self) -> None:
        """Print initial banner and instructions."""
        _init_log_file()

        log("")
        print_box(
            "CPU SPIN LOOP DETECTOR",
            f"Issue #2360 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            Colors.CYAN,
        )

        log(
            f"""
{Colors.BOLD}PURPOSE:{Colors.RESET}
  Detect CPU spin loop bug caused by orphaned asyncio tasks.

{Colors.BOLD}AGGRESSIVE TEST PATTERN:{Colors.RESET}
  1. {Colors.GREEN}4000 users{Colors.RESET} (1000/s spawn) → {Colors.MAGENTA}cancel 10s{Colors.RESET}
  2. {Colors.GREEN}4000 users{Colors.RESET} (1000/s spawn) → {Colors.MAGENTA}cancel 10s{Colors.RESET}
  3. {Colors.RED}10000 users{Colors.RESET} (1000/s spawn) → {Colors.MAGENTA}cancel 10s{Colors.RESET}
  4. {Colors.BOLD}Repeat indefinitely{Colors.RESET}

{Colors.BOLD}EXPECTED:{Colors.RESET}
  {Colors.GREEN}PASS:{Colors.RESET} CPU <10% during pause | {Colors.RED}FAIL:{Colors.RESET} CPU >100% during pause

{Colors.BOLD}MONITORING:{Colors.RESET}
  Log file: {Colors.CYAN}{LOG_FILE}{Colors.RESET}
  Monitor:  {Colors.DIM}tail -f {LOG_FILE}{Colors.RESET}
"""
        )

        _log_auth_mode()

        print_section("Initial Docker Stats")
        stats_output, cpu_values = get_docker_stats()
        log(stats_output)
        log(f"\n{format_cpu_status(cpu_values)}\n")

    def _log_phase_change(self, phase: str, current_users: int, target_users: int) -> None:
        """Log phase transitions with docker stats."""
        # Use total cycles for display (1-indexed)
        cycle_num = self._total_cycles + 1
        cycle_letter = chr(ord('A') + (self._current_cycle % len(self.cycles)))

        stats_output, cpu_values = get_docker_stats()
        cpu_status = format_cpu_status(cpu_values)

        if phase == "ramp":
            print_box(
                f"CYCLE {cycle_num} ({cycle_letter}): RAMPING UP",
                f"Target: {target_users} users | Spawn rate: {self.spawn_rate}/s",
                Colors.BLUE,
            )
        elif phase == "sustain":
            print_box(
                f"CYCLE {cycle_num} ({cycle_letter}): SUSTAINING LOAD",
                f"Holding at {target_users} users",
                Colors.CYAN,
            )
        elif phase == "pause":
            print_box(
                f"CYCLE {cycle_num} ({cycle_letter}): PAUSE - MONITORING CPU",
                "",
                Colors.MAGENTA,
            )
            log("")
            log(f"  {Colors.YELLOW}{Colors.BOLD}>>> ALL USERS DISCONNECTED <<<{Colors.RESET}")
            log(f"  {Colors.YELLOW}>>> CPU should drop to <10% if cleanup is working <<<{Colors.RESET}")
            log("")

            # Record max CPU for this pause
            if cpu_values:
                max_cpu = max(cpu for _, cpu in cpu_values)
                self._pause_stats.append((cycle_num, max_cpu))

                # Log summary every 5 cycles
                if cycle_num % 5 == 0:
                    self._log_periodic_summary()

        # Print docker stats
        print_section("Docker Stats")
        log(stats_output)
        log(f"\n{cpu_status}\n")

    def _log_periodic_summary(self) -> None:
        """Log a periodic summary of pause phase CPU stats."""
        if not self._pause_stats:
            return

        # Get last 5 cycles
        recent = self._pause_stats[-5:]
        passes = sum(1 for _, cpu in recent if cpu < 10)
        warns = sum(1 for _, cpu in recent if 10 <= cpu < 50)
        fails = sum(1 for _, cpu in recent if cpu >= 50)

        log("")
        log(f"{Colors.CYAN}{Colors.BOLD}=== PERIODIC SUMMARY (last 5 cycles) ==={Colors.RESET}")
        log(f"  {Colors.GREEN}PASS: {passes}{Colors.RESET} | {Colors.YELLOW}WARN: {warns}{Colors.RESET} | {Colors.RED}FAIL: {fails}{Colors.RESET}")
        log(f"  Total cycles completed: {len(self._pause_stats)}")
        log("")

    def _print_final_report(self) -> None:
        """Print final summary report."""
        stats_output, cpu_values = get_docker_stats()

        log("")
        print_box(
            "TEST COMPLETE",
            "",
            Colors.GREEN if all(cpu < 10 for _, cpu in cpu_values) else Colors.RED,
        )

        # Summary table
        print_section("Pause Phase CPU Summary", Colors.MAGENTA)
        log(f"{'Cycle':<10} {'Max CPU %':<15} {'Status':<20}")
        log("-" * 45)

        all_passed = True
        for cycle_num, max_cpu in self._pause_stats:
            if max_cpu < 10:
                status = f"{Colors.GREEN}PASS{Colors.RESET}"
            elif max_cpu < 50:
                status = f"{Colors.YELLOW}WARN{Colors.RESET}"
                all_passed = False
            else:
                status = f"{Colors.RED}FAIL{Colors.RESET}"
                all_passed = False
            log(f"{cycle_num:<10} {max_cpu:<15.1f} {status}")

        # Final stats
        print_section("Final Docker Stats")
        log(stats_output)
        log(f"\n{format_cpu_status(cpu_values)}")

        # Verdict
        log("")
        if all_passed and cpu_values and all(cpu < 10 for _, cpu in cpu_values):
            log(f"{Colors.GREEN}{Colors.BOLD}")
            log("  +------------------------------------------+")
            log("  |              TEST PASSED                 |")
            log("  |   CPU returned to idle after cleanup     |")
            log("  +------------------------------------------+")
            log(f"{Colors.RESET}")
        else:
            log(f"{Colors.RED}{Colors.BOLD}")
            log("  +------------------------------------------+")
            log("  |              TEST FAILED                 |")
            log("  |   CPU spin loop may still be present     |")
            log("  +------------------------------------------+")
            log(f"{Colors.RESET}")
            log(f"\n{Colors.YELLOW}See: todo/how-to-analyze.md for debugging steps{Colors.RESET}")

        log(f"\n{Colors.DIM}Issue: https://github.com/IBM/mcp-context-forge/issues/2360{Colors.RESET}")
        log(f"{Colors.DIM}Log file: {LOG_FILE}{Colors.RESET}\n")
