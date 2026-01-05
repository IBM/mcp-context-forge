# -*- coding: utf-8 -*-
"""Load testing for Rust fast-test-server via MCP Streamable HTTP and REST API.

This module tests the Rust fast-test-server using both:
- MCP Streamable HTTP protocol (with proper session management)
- REST API (for baseline comparison)

Uses FastHttpUser (geventhttpclient) for maximum throughput.

User Classes:
- RustMCPUser: MCP protocol test via Streamable HTTP (weight: 10)
- RustMCPStressUser: High-frequency MCP stress test (weight: 1)
- RustRESTUser: REST API test for comparison (weight: 5)

Usage:
    # Start the server first:
    make run-release PORT=9080

    # Web UI with class picker (distributed across all CPUs)
    make locust-ui

    # Headless tests with auto CPU detection
    make locust-mcp    # MCP protocol test
    make locust-rest   # REST API test
    make locust-both   # Both tests sequentially

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import json
import logging
import os
import random

from locust import FastHttpUser, constant, events, tag, task
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
    parser.set_defaults(users=100, spawn_rate=20, run_time="60s", host="http://localhost:9080")


# =============================================================================
# Configuration
# =============================================================================

MCP_PATH = os.environ.get("RUST_MCP_PATH", "/mcp")

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
]

ECHO_MESSAGES = [
    "Hello, World!",
    "Testing MCP protocol",
    "Rust is blazingly fast",
    "Load testing in progress",
    "Performance benchmark",
    "Echo echo echo",
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
    logger.info("RUST FAST-TEST-SERVER LOAD TEST (FastHttpUser)")
    logger.info("=" * 60)
    logger.info(f"Host: {environment.host}")
    logger.info(f"MCP Endpoint: {environment.host}{MCP_PATH}")
    logger.info(f"REST Endpoints: {environment.host}/api/echo, {environment.host}/api/time")
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
    print("RUST FAST-TEST-SERVER TEST SUMMARY (FastHttpUser)")
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
# MCP Streamable HTTP User (FastHttpUser-based)
# =============================================================================


class RustMCPUser(FastHttpUser):
    """Load test for Rust fast-test-server via MCP Streamable HTTP protocol.

    Uses FastHttpUser (geventhttpclient) for maximum throughput.
    Tests the MCP protocol directly at /mcp endpoint.

    Calls: echo, get_system_time, get_stats tools
    """

    weight = 10
    wait_time = constant(0)  # No wait time for maximum throughput
    abstract = False

    # Connection pool settings for high concurrency
    connection_timeout = 10.0
    network_timeout = 10.0

    def __init__(self, *args, **kwargs):
        """Initialize MCP state."""
        super().__init__(*args, **kwargs)
        self._request_id = 0
        self._initialized = False
        self._mcp_session_id = None

    def _next_id(self):
        """Get next request ID."""
        self._request_id += 1
        return self._request_id

    def _mcp_request(self, method: str, params: dict = None, name: str = None):
        """Make an MCP JSON-RPC request using FastHttpUser client."""
        payload = {"jsonrpc": "2.0", "method": method, "id": self._next_id()}
        if params:
            payload["params"] = params

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id

        with self.client.post(
            MCP_PATH,
            data=json.dumps(payload),
            headers=headers,
            name=name or f"MCP:{method}",
            catch_response=True,
        ) as response:
            # Capture session ID from response header
            session_id = response.headers.get("mcp-session-id") or response.headers.get("Mcp-Session-Id")
            if session_id:
                self._mcp_session_id = session_id

            if response.status_code != 200:
                response.failure(f"Status {response.status_code}")
                return None

            # Parse SSE response format (data: {...})
            text = response.text.strip()
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("data:"):
                    text = line[5:].strip()
                    break

            try:
                result = json.loads(text)
                if "error" in result:
                    response.failure(f"MCP error: {result['error']}")
                    return None
                response.success()
                return result.get("result")
            except json.JSONDecodeError as e:
                response.failure(f"JSON decode error: {e}")
                return None

    def _ensure_initialized(self):
        """Ensure MCP session is initialized."""
        if not self._initialized:
            result = self._mcp_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "locust-fast-mcp-client", "version": "1.0"},
                },
                name="MCP:initialize",
            )
            if result:
                # Send initialized notification (fire and forget)
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                }
                if self._mcp_session_id:
                    headers["Mcp-Session-Id"] = self._mcp_session_id
                try:
                    self.client.post(
                        MCP_PATH,
                        data=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                        headers=headers,
                        name="MCP:initialized",
                    )
                except Exception:
                    pass
                self._initialized = True

    @task(10)
    @tag("mcp", "echo")
    def mcp_echo(self):
        """MCP: Call echo tool."""
        self._ensure_initialized()
        message = random.choice(ECHO_MESSAGES)
        self._mcp_request("tools/call", {"name": "echo", "arguments": {"message": message}}, name="MCP:echo")

    @task(8)
    @tag("mcp", "time")
    def mcp_get_system_time(self):
        """MCP: Call get_system_time tool."""
        self._ensure_initialized()
        tz = random.choice(TIMEZONES)
        self._mcp_request("tools/call", {"name": "get_system_time", "arguments": {"timezone": tz}}, name="MCP:get_system_time")

    @task(5)
    @tag("mcp", "time")
    def mcp_get_system_time_utc(self):
        """MCP: Call get_system_time with UTC."""
        self._ensure_initialized()
        self._mcp_request("tools/call", {"name": "get_system_time", "arguments": {"timezone": "UTC"}}, name="MCP:get_system_time[UTC]")

    @task(3)
    @tag("mcp", "stats")
    def mcp_get_stats(self):
        """MCP: Call get_stats tool."""
        self._ensure_initialized()
        self._mcp_request("tools/call", {"name": "get_stats", "arguments": {}}, name="MCP:get_stats")

    @task(3)
    @tag("mcp", "list")
    def mcp_list_tools(self):
        """MCP: List available tools."""
        self._ensure_initialized()
        self._mcp_request("tools/list", {}, name="MCP:tools/list")


# =============================================================================
# MCP Stress Test User (FastHttpUser-based)
# =============================================================================


class RustMCPStressUser(FastHttpUser):
    """High-frequency stress test for Rust MCP server.

    Uses FastHttpUser (geventhttpclient) with no wait time for maximum throughput.
    Weight: Low (only for stress tests)
    """

    weight = 1
    wait_time = constant(0)  # No wait for maximum stress
    abstract = False

    connection_timeout = 10.0
    network_timeout = 10.0

    def __init__(self, *args, **kwargs):
        """Initialize MCP state."""
        super().__init__(*args, **kwargs)
        self._request_id = 0
        self._initialized = False
        self._mcp_session_id = None

    def _next_id(self):
        """Get next request ID."""
        self._request_id += 1
        return self._request_id

    def _mcp_request(self, method: str, params: dict = None, name: str = None):
        """Make an MCP JSON-RPC request."""
        payload = {"jsonrpc": "2.0", "method": method, "id": self._next_id()}
        if params:
            payload["params"] = params

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id

        with self.client.post(
            MCP_PATH,
            data=json.dumps(payload),
            headers=headers,
            name=name or f"MCP-STRESS:{method}",
            catch_response=True,
        ) as response:
            session_id = response.headers.get("mcp-session-id") or response.headers.get("Mcp-Session-Id")
            if session_id:
                self._mcp_session_id = session_id

            if response.status_code != 200:
                response.failure(f"Status {response.status_code}")
                return None

            text = response.text.strip()
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("data:"):
                    text = line[5:].strip()
                    break

            try:
                result = json.loads(text)
                if "error" in result:
                    response.failure(f"MCP error: {result['error']}")
                    return None
                response.success()
                return result.get("result")
            except json.JSONDecodeError as e:
                response.failure(f"JSON decode error: {e}")
                return None

    def _ensure_initialized(self):
        """Ensure MCP session is initialized."""
        if not self._initialized:
            result = self._mcp_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "locust-stress-client", "version": "1.0"},
                },
                name="MCP-STRESS:initialize",
            )
            if result:
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                }
                if self._mcp_session_id:
                    headers["Mcp-Session-Id"] = self._mcp_session_id
                try:
                    self.client.post(
                        MCP_PATH,
                        data=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                        headers=headers,
                        name="MCP-STRESS:initialized",
                    )
                except Exception:
                    pass
                self._initialized = True

    @task(10)
    @tag("mcp", "stress", "echo")
    def rapid_echo(self):
        """Rapid echo for stress testing."""
        self._ensure_initialized()
        self._mcp_request("tools/call", {"name": "echo", "arguments": {"message": "stress"}}, name="MCP-STRESS:echo")

    @task(5)
    @tag("mcp", "stress", "time")
    def rapid_get_time(self):
        """Rapid time checks for stress testing."""
        self._ensure_initialized()
        self._mcp_request("tools/call", {"name": "get_system_time", "arguments": {"timezone": "UTC"}}, name="MCP-STRESS:time")


# =============================================================================
# REST API User (FastHttpUser for maximum throughput)
# =============================================================================


class RustRESTUser(FastHttpUser):
    """Load test for Rust fast-test-server REST API.

    Uses FastHttpUser (geventhttpclient) for maximum throughput.
    Tests REST API endpoints directly (no MCP protocol overhead).
    """

    weight = 5
    wait_time = constant(0)  # No wait for maximum throughput
    abstract = False

    connection_timeout = 10.0
    network_timeout = 10.0

    @task(10)
    @tag("rest", "echo")
    def rest_echo(self):
        """POST /api/echo - Echo message."""
        message = random.choice(ECHO_MESSAGES)
        with self.client.post(
            "/api/echo",
            data=json.dumps({"message": message}),
            headers={"Content-Type": "application/json"},
            name="/api/echo",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(8)
    @tag("rest", "time")
    def rest_time(self):
        """GET /api/time - Get current time."""
        tz = random.choice(TIMEZONES)
        with self.client.get(
            f"/api/time?tz={tz}",
            name="/api/time",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(5)
    @tag("rest", "time")
    def rest_time_utc(self):
        """GET /api/time - Get current UTC time."""
        with self.client.get(
            "/api/time",
            name="/api/time[UTC]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(2)
    @tag("rest", "health")
    def health_check(self):
        """GET /health - Health check endpoint."""
        with self.client.get(
            "/health",
            name="/health",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(1)
    @tag("rest", "version")
    def version_check(self):
        """GET /version - Version info endpoint."""
        with self.client.get(
            "/version",
            name="/version",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")
