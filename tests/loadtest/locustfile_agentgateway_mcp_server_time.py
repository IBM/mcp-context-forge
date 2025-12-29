# -*- coding: utf-8 -*-
"""Load testing for external MCP server via Streamable HTTP.

This module tests an MCP server at http://localhost:3000 using the
Streamable HTTP transport protocol. It calls the `localhost-get-system-time`
tool to measure MCP server performance.

User Classes:
- MCPServerTimeUser: MCP protocol test via Streamable HTTP (weight: 10)
- MCPServerTimeStressUser: High-frequency stress test (weight: 1)

Default Parameters:
- Users: 50
- Spawn rate: 10/s
- Run time: 60s
- Host: http://localhost:3000

Usage:
    # Web UI with class picker
    make load-test-agentgateway-mcp-server-time

    # Or manually:
    locust -f locustfile_agentgateway_mcp_server_time.py --class-picker

    # Headless
    locust -f locustfile_agentgateway_mcp_server_time.py \
           --host=http://localhost:3000 \
           --users=50 --spawn-rate=10 --run-time=60s --headless

Environment Variables:
    MCP_SERVER_URL: MCP Server URL (default: http://localhost:3000/mcp)
    MCP_TOOL_NAME: Tool name to call (default: localhost-get-system-time)

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import logging
import os
import random
import time

from locust import User, between, events, tag, task
from locust.runners import MasterRunner, WorkerRunner

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# Default Test Parameters (for Web UI)
# =============================================================================


@events.init_command_line_parser.add_listener
def set_defaults(parser):
    """Set default values for the Locust web UI."""
    parser.set_defaults(users=50, spawn_rate=10, run_time="60s", host="http://localhost:3000")


# =============================================================================
# Configuration
# =============================================================================

# MCP Streamable HTTP endpoint - note: this server uses root path, not /mcp
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:3000/")
MCP_TOOL_NAME = os.environ.get("MCP_TOOL_NAME", "get_system_time")

# Test data
TIMEZONES = [
    "UTC",
    "America/New_York",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Paris",
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Australia/Sydney",
    "America/Chicago",
    "America/Denver",
    "Europe/Berlin",
    "Asia/Singapore",
    "Europe/Dublin",
]


# =============================================================================
# Event Handlers
# =============================================================================


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Log test configuration at start."""
    if isinstance(environment.runner, MasterRunner) or isinstance(environment.runner, WorkerRunner):
        return

    logger.info("=" * 60)
    logger.info("MCP SERVER TIME LOAD TEST")
    logger.info("=" * 60)
    logger.info(f"MCP Server URL: {MCP_SERVER_URL}")
    logger.info(f"Tool Name: {MCP_TOOL_NAME}")
    logger.info("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Print summary at test end."""
    if isinstance(environment.runner, MasterRunner):
        return

    stats = environment.stats
    total_requests = stats.total.num_requests
    total_failures = stats.total.num_failures
    failure_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0

    print("\n" + "=" * 80)
    print("MCP SERVER TIME TEST SUMMARY")
    print("=" * 80)
    print(f"\n{'OVERALL METRICS':^80}")
    print("-" * 80)
    print(f"  Total Requests:     {total_requests:,}")
    print(f"  Total Failures:     {total_failures:,} ({failure_rate:.2f}%)")
    print(f"  Requests/sec (RPS): {stats.total.total_rps:.2f}")
    print(f"\n  Response Times (ms):")
    print(f"    Average:          {stats.total.avg_response_time:.2f}")
    print(f"    Min:              {stats.total.min_response_time:.2f}")
    print(f"    Max:              {stats.total.max_response_time:.2f}")
    if stats.total.num_requests > 0:
        print(f"    Median (p50):     {stats.total.get_response_time_percentile(0.5):.2f}")
        print(f"    p90:              {stats.total.get_response_time_percentile(0.9):.2f}")
        print(f"    p95:              {stats.total.get_response_time_percentile(0.95):.2f}")
        print(f"    p99:              {stats.total.get_response_time_percentile(0.99):.2f}")
    print("=" * 80)


# =============================================================================
# MCP Server Time User (Streamable HTTP)
# =============================================================================


class MCPServerTimeUser(User):
    """Load test for MCP server via Streamable HTTP protocol.

    Tests the MCP protocol directly using synchronous HTTP requests to
    the Streamable HTTP endpoint at localhost:3000.

    Calls the `localhost-get-system-time` tool.

    Default host: http://localhost:3000
    """

    weight = 10
    wait_time = between(0.1, 0.5)

    def __init__(self, *args, **kwargs):
        """Initialize with requests session for MCP calls."""
        super().__init__(*args, **kwargs)
        import requests

        self._session = requests.Session()
        self._request_id = 0
        self._initialized = False
        self._mcp_session_id = None
        logger.info(f"MCP Streamable HTTP client configured for {MCP_SERVER_URL}")

    def on_stop(self):
        """Close the session."""
        if self._session:
            self._session.close()

    def _next_id(self):
        """Get next request ID."""
        self._request_id += 1
        return self._request_id

    def _fire_request(self, name: str, start_time: float, exception: Exception = None):
        """Fire a request event for Locust metrics."""
        elapsed = (time.perf_counter() - start_time) * 1000
        events.request.fire(
            request_type="MCP",
            name=name,
            response_time=elapsed,
            response_length=0,
            exception=exception,
        )

    def _mcp_request(self, method: str, params: dict = None):
        """Make an MCP JSON-RPC request."""
        import json

        payload = {"jsonrpc": "2.0", "method": method, "id": self._next_id()}
        if params:
            payload["params"] = params

        # Server requires both application/json and text/event-stream accept headers
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._mcp_session_id:
            headers["mcp-session-id"] = self._mcp_session_id

        response = self._session.post(MCP_SERVER_URL, json=payload, headers=headers, timeout=10)

        # Capture session ID from response header (case-insensitive)
        for header_name in ["mcp-session-id", "Mcp-Session-Id"]:
            if header_name in response.headers:
                self._mcp_session_id = response.headers[header_name]
                break

        response.raise_for_status()

        # Parse SSE response format (data: {...})
        text = response.text.strip()
        if text.startswith("data:"):
            text = text[5:].strip()

        result = json.loads(text)

        if "error" in result:
            raise Exception(f"MCP error: {result['error']}")

        return result.get("result")

    def _ensure_initialized(self):
        """Ensure MCP session is initialized."""
        if not self._initialized:
            self._mcp_request(
                "initialize",
                {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "locust-mcp-client", "version": "1.0"}},
            )
            self._initialized = True

    @task(10)
    @tag("mcp", "time")
    def mcp_get_system_time(self):
        """MCP: Call localhost-get-system-time tool."""
        tz = random.choice(TIMEZONES)
        start = time.perf_counter()
        try:
            self._ensure_initialized()
            result = self._mcp_request("tools/call", {"name": MCP_TOOL_NAME, "arguments": {"timezone": tz}})
            # Validate response contains time data
            content = result.get("content", [])
            if content and len(content) > 0:
                self._fire_request(MCP_TOOL_NAME, start)
            else:
                raise Exception("Invalid response: missing time content")
        except Exception as e:
            self._fire_request(MCP_TOOL_NAME, start, e)

    @task(5)
    @tag("mcp", "time")
    def mcp_get_system_time_utc(self):
        """MCP: Call localhost-get-system-time with UTC."""
        start = time.perf_counter()
        try:
            self._ensure_initialized()
            result = self._mcp_request("tools/call", {"name": MCP_TOOL_NAME, "arguments": {"timezone": "UTC"}})
            content = result.get("content", [])
            if content and len(content) > 0:
                self._fire_request(f"{MCP_TOOL_NAME} [UTC]", start)
            else:
                raise Exception("Invalid response: missing time content")
        except Exception as e:
            self._fire_request(f"{MCP_TOOL_NAME} [UTC]", start, e)

    @task(3)
    @tag("mcp", "list")
    def mcp_list_tools(self):
        """MCP: List available tools."""
        start = time.perf_counter()
        try:
            self._ensure_initialized()
            result = self._mcp_request("tools/list", {})
            tools = result.get("tools", [])
            if tools:
                self._fire_request("tools/list", start)
            else:
                # Empty tools list is acceptable
                self._fire_request("tools/list", start)
        except Exception as e:
            self._fire_request("tools/list", start, e)

    @task(2)
    @tag("mcp", "ping")
    def mcp_ping(self):
        """MCP: Ping the server."""
        start = time.perf_counter()
        try:
            self._ensure_initialized()
            self._mcp_request("ping", {})
            self._fire_request("ping", start)
        except Exception as e:
            self._fire_request("ping", start, e)


class MCPServerTimeStressUser(User):
    """High-frequency stress test for MCP server.

    Minimal wait times to find maximum throughput.
    Weight: Low (only for stress tests)
    """

    weight = 1
    wait_time = between(0.01, 0.05)

    def __init__(self, *args, **kwargs):
        """Initialize with requests session for MCP calls."""
        super().__init__(*args, **kwargs)
        import requests

        self._session = requests.Session()
        self._request_id = 0
        self._initialized = False
        self._mcp_session_id = None

    def on_stop(self):
        """Close the session."""
        if self._session:
            self._session.close()

    def _next_id(self):
        """Get next request ID."""
        self._request_id += 1
        return self._request_id

    def _fire_request(self, name: str, start_time: float, exception: Exception = None):
        """Fire a request event for Locust metrics."""
        elapsed = (time.perf_counter() - start_time) * 1000
        events.request.fire(
            request_type="MCP-STRESS",
            name=name,
            response_time=elapsed,
            response_length=0,
            exception=exception,
        )

    def _mcp_request(self, method: str, params: dict = None):
        """Make an MCP JSON-RPC request."""
        import json

        payload = {"jsonrpc": "2.0", "method": method, "id": self._next_id()}
        if params:
            payload["params"] = params

        # Server requires both application/json and text/event-stream accept headers
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._mcp_session_id:
            headers["mcp-session-id"] = self._mcp_session_id

        response = self._session.post(MCP_SERVER_URL, json=payload, headers=headers, timeout=10)

        # Capture session ID from response header (case-insensitive)
        for header_name in ["mcp-session-id", "Mcp-Session-Id"]:
            if header_name in response.headers:
                self._mcp_session_id = response.headers[header_name]
                break

        response.raise_for_status()

        # Parse SSE response format (data: {...})
        text = response.text.strip()
        if text.startswith("data:"):
            text = text[5:].strip()

        result = json.loads(text)

        if "error" in result:
            raise Exception(f"MCP error: {result['error']}")

        return result.get("result")

    def _ensure_initialized(self):
        """Ensure MCP session is initialized."""
        if not self._initialized:
            self._mcp_request(
                "initialize",
                {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "locust-stress-client", "version": "1.0"}},
            )
            self._initialized = True

    @task(10)
    @tag("mcp", "stress")
    def rapid_get_time(self):
        """Rapid time checks for stress testing."""
        start = time.perf_counter()
        try:
            self._ensure_initialized()
            self._mcp_request("tools/call", {"name": MCP_TOOL_NAME, "arguments": {"timezone": "UTC"}})
            self._fire_request(f"{MCP_TOOL_NAME} [stress]", start)
        except Exception as e:
            self._fire_request(f"{MCP_TOOL_NAME} [stress]", start, e)

    @task(5)
    @tag("mcp", "stress")
    def rapid_ping(self):
        """Rapid ping for stress testing."""
        start = time.perf_counter()
        try:
            self._ensure_initialized()
            self._mcp_request("ping", {})
            self._fire_request("ping [stress]", start)
        except Exception as e:
            self._fire_request("ping [stress]", start, e)
