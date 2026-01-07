# -*- coding: utf-8 -*-
"""Baseline load testing for individual components and gateway.

This module provides load testing for individual components to establish
performance baselines, and also tests MCP through the gateway.

Components tested:
- Fast Time Server (REST API) - MCP server performance baseline
- Fast Time Server (MCP Client) - MCP protocol baseline direct to server
- Gateway MCP (SSE/HTTP) - MCP protocol through gateway virtual server
- PostgreSQL - Database performance baseline (optional, requires psycopg)
- Redis - Cache performance baseline (optional, requires redis)

User Classes (selectable via --class-picker in Web UI):
- FastTimeRESTUser: Standard REST API load test (weight: 10)
- FastTimeMCPUser: MCP protocol test direct to server (weight: 1)
- GatewayMCPUser: MCP protocol test through gateway (weight: 1)
- FastTimeStressUser: High-frequency stress test (weight: 1)
- PostgresUser: Direct PostgreSQL testing (weight: 1, requires psycopg)
- RedisUser: Direct Redis testing (weight: 1, requires redis)

Default Parameters:
- Users: 1000
- Spawn rate: 100/s
- Run time: 3 minutes (180s)
- Host: http://localhost:8888

Usage:
    # Web UI with class picker (recommended)
    make load-test-baseline-ui

    # Or manually:
    locust -f locustfile_baseline.py --class-picker

    # Headless baseline (1000 users, 3 min)
    make load-test-baseline

    # Headless stress (2000 users, 3 min)
    make load-test-baseline-stress

    # Custom headless run
    locust -f locustfile_baseline.py --host=http://localhost:8888 \
           --users 1000 --spawn-rate 100 --run-time 180s --headless

Environment Variables:
    BASELINE_FAST_TIME_HOST: Fast Time Server URL (default: http://localhost:8888)
    BASELINE_MCP_URL: MCP Server URL direct (default: http://localhost:8888/http)
    BASELINE_GATEWAY_URL: Gateway URL (default: http://localhost:8080)
    BASELINE_GATEWAY_SERVER_ID: Virtual server ID (default: 9779b6698cbd4b4995ee04a4fab38737)
    BASELINE_JWT_SECRET: JWT secret for gateway auth (default: my-test-key)
    BASELINE_POSTGRES_HOST: PostgreSQL host (default: localhost)
    BASELINE_POSTGRES_PORT: PostgreSQL port (default: 5432)
    BASELINE_POSTGRES_USER: PostgreSQL user (default: postgres)
    BASELINE_POSTGRES_PASSWORD: PostgreSQL password (default: mysecretpassword)
    BASELINE_POSTGRES_DB: PostgreSQL database (default: mcp)
    BASELINE_REDIS_URL: Redis URL (default: redis://localhost:6379/0)

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import logging
import os
import random
import time
from typing import Any

from locust import HttpUser, User, between, events, tag, task
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
    parser.set_defaults(
        users=1000,
        spawn_rate=100,
        run_time="180s",
        host="http://localhost:8888"
    )

# =============================================================================
# Configuration
# =============================================================================

FAST_TIME_HOST = os.environ.get("BASELINE_FAST_TIME_HOST", "http://localhost:8888")
MCP_URL = os.environ.get("BASELINE_MCP_URL", "http://localhost:8888/http")
GATEWAY_URL = os.environ.get("BASELINE_GATEWAY_URL", "http://localhost:8080")
GATEWAY_SERVER_ID = os.environ.get("BASELINE_GATEWAY_SERVER_ID", "9779b6698cbd4b4995ee04a4fab38737")
JWT_SECRET = os.environ.get("BASELINE_JWT_SECRET", "my-test-key")
POSTGRES_HOST = os.environ.get("BASELINE_POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.environ.get("BASELINE_POSTGRES_PORT", "5433"))
POSTGRES_USER = os.environ.get("BASELINE_POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.environ.get("BASELINE_POSTGRES_PASSWORD", "mysecretpassword")
POSTGRES_DB = os.environ.get("BASELINE_POSTGRES_DB", "mcp")
REDIS_URL = os.environ.get("BASELINE_REDIS_URL", "redis://localhost:6379/0")

# Test data
TIMEZONES = [
    "UTC", "America/New_York", "America/Los_Angeles", "Europe/London",
    "Europe/Paris", "Asia/Tokyo", "Asia/Shanghai", "Australia/Sydney",
    "America/Chicago", "America/Denver", "Europe/Berlin", "Asia/Singapore"
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
    logger.info("BASELINE PERFORMANCE TEST")
    logger.info("=" * 60)
    logger.info(f"Fast Time Server (REST): {FAST_TIME_HOST}")
    logger.info(f"Fast Time Server (MCP):  {MCP_URL}")
    logger.info(f"Gateway (MCP):           {GATEWAY_URL}/servers/{GATEWAY_SERVER_ID}/mcp")
    logger.info(f"PostgreSQL: {POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")
    logger.info(f"Redis: {REDIS_URL}")
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
    print("BASELINE TEST SUMMARY")
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
# Fast Time Server REST API Tests
# =============================================================================

class FastTimeRESTUser(HttpUser):
    """Load test for Fast Time Server REST API directly (no gateway).

    Tests the REST API endpoints exposed by the fast_time_server
    to establish a performance baseline.

    Default host: http://localhost:8888
    """

    weight = 10
    wait_time = between(0.1, 0.5)

    @task(10)
    @tag("fast-time", "rest", "time")
    def get_current_time(self):
        """GET /api/v1/time - Get current time in random timezone."""
        tz = random.choice(TIMEZONES)
        with self.client.get(
            f"/api/v1/time?timezone={tz}",
            name="/api/v1/time",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(8)
    @tag("fast-time", "rest", "time")
    def get_time_by_timezone(self):
        """GET /api/v1/time/{timezone} - Get time for specific timezone."""
        tz = random.choice(TIMEZONES)
        with self.client.get(
            f"/api/v1/time/{tz}",
            name="/api/v1/time/{timezone}",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(5)
    @tag("fast-time", "rest", "convert")
    def convert_time(self):
        """POST /api/v1/convert - Convert time between timezones."""
        from_tz = random.choice(TIMEZONES)
        to_tz = random.choice([t for t in TIMEZONES if t != from_tz])
        payload = {
            "time": "2025-01-15T10:30:00Z",
            "from_timezone": from_tz,
            "to_timezone": to_tz
        }
        with self.client.post(
            "/api/v1/convert",
            json=payload,
            name="/api/v1/convert",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(3)
    @tag("fast-time", "rest", "timezones")
    def list_timezones(self):
        """GET /api/v1/timezones - List all available timezones."""
        with self.client.get(
            "/api/v1/timezones",
            name="/api/v1/timezones",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(2)
    @tag("fast-time", "rest", "timezones")
    def get_timezone_info(self):
        """GET /api/v1/timezones/{timezone}/info - Get timezone details."""
        tz = random.choice(TIMEZONES)
        with self.client.get(
            f"/api/v1/timezones/{tz}/info",
            name="/api/v1/timezones/{timezone}/info",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(2)
    @tag("fast-time", "rest", "health")
    def health_check(self):
        """GET /health - Health check endpoint."""
        with self.client.get(
            "/health",
            name="/health",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(1)
    @tag("fast-time", "rest", "resources")
    def list_resources(self):
        """GET /api/v1/resources - List available resources."""
        with self.client.get(
            "/api/v1/resources",
            name="/api/v1/resources",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(1)
    @tag("fast-time", "rest", "prompts")
    def list_prompts(self):
        """GET /api/v1/prompts - List available prompts."""
        with self.client.get(
            "/api/v1/prompts",
            name="/api/v1/prompts",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")


class FastTimeStressUser(HttpUser):
    """High-frequency stress test for Fast Time Server.

    Minimal wait times to find maximum throughput.
    Weight: Low (only for stress tests)
    """

    weight = 1
    wait_time = between(0.01, 0.05)

    @task(10)
    @tag("fast-time", "stress")
    def rapid_time_check(self):
        """Rapid time checks for stress testing."""
        self.client.get("/api/v1/time?timezone=UTC", name="/api/v1/time [stress]")

    @task(5)
    @tag("fast-time", "stress")
    def rapid_health_check(self):
        """Rapid health checks for stress testing."""
        self.client.get("/health", name="/health [stress]")


# =============================================================================
# Fast Time Server MCP Client Tests (Streamable HTTP)
# =============================================================================

class FastTimeMCPUser(User):
    """Load test for Fast Time Server via MCP Streamable HTTP protocol.

    Tests the MCP protocol directly using synchronous HTTP requests to
    establish a performance baseline for the MCP server without the gateway.

    NOTE: Uses direct HTTP JSON-RPC calls to MCP Streamable HTTP endpoint.
    No HTTP host required - connects directly via MCP protocol.

    To enable: Select in class picker (Web UI) or set weight > 0
    """

    weight = 1  # Enabled by default
    wait_time = between(0.1, 0.5)

    def __init__(self, *args, **kwargs):
        """Initialize with requests session for MCP calls."""
        super().__init__(*args, **kwargs)
        import requests
        self._session = requests.Session()
        self._request_id = 0
        self._initialized = False
        self._mcp_session_id = None
        logger.info(f"MCP Streamable HTTP client configured for {MCP_URL}")

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
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self._next_id()
        }
        if params:
            payload["params"] = params

        headers = {"Content-Type": "application/json"}
        if self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id

        response = self._session.post(
            MCP_URL,
            json=payload,
            headers=headers,
            timeout=10
        )

        # Capture session ID from response header
        if "Mcp-Session-Id" in response.headers:
            self._mcp_session_id = response.headers["Mcp-Session-Id"]

        response.raise_for_status()
        result = response.json()

        if "error" in result:
            raise Exception(f"MCP error: {result['error']}")

        return result.get("result")

    def _ensure_initialized(self):
        """Ensure MCP session is initialized."""
        if not self._initialized:
            self._mcp_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "locust-mcp-client", "version": "1.0"}
            })
            self._initialized = True

    @task(10)
    @tag("fast-time", "mcp", "time")
    def mcp_get_system_time(self):
        """MCP: Call get_system_time tool."""
        tz = random.choice(TIMEZONES)
        start = time.perf_counter()
        try:
            self._ensure_initialized()
            self._mcp_request("tools/call", {
                "name": "get_system_time",
                "arguments": {"timezone": tz}
            })
            self._fire_request("get_system_time", start)
        except Exception as e:
            self._fire_request("get_system_time", start, e)

    @task(5)
    @tag("fast-time", "mcp", "convert")
    def mcp_convert_time(self):
        """MCP: Call convert_time tool."""
        source_tz = random.choice(TIMEZONES)
        target_tz = random.choice([t for t in TIMEZONES if t != source_tz])
        start = time.perf_counter()
        try:
            self._ensure_initialized()
            self._mcp_request("tools/call", {
                "name": "convert_time",
                "arguments": {
                    "time": "2025-01-15T10:30:00Z",
                    "source_timezone": source_tz,
                    "target_timezone": target_tz
                }
            })
            self._fire_request("convert_time", start)
        except Exception as e:
            self._fire_request("convert_time", start, e)

    @task(3)
    @tag("fast-time", "mcp", "list")
    def mcp_list_tools(self):
        """MCP: List available tools."""
        start = time.perf_counter()
        try:
            self._ensure_initialized()
            self._mcp_request("tools/list", {})
            self._fire_request("list_tools", start)
        except Exception as e:
            self._fire_request("list_tools", start, e)


# =============================================================================
# Gateway MCP Tests (via virtual server)
# =============================================================================

def _generate_jwt_token():
    """Generate a JWT token for gateway authentication.

    First tries to use the PyJWT library for proper token generation.
    Falls back to manual generation with compact JSON if PyJWT is not available.
    """
    import time as time_module

    now = int(time_module.time())
    payload = {
        "username": "admin@example.com",
        "iat": now,
        "iss": "mcpgateway",
        "aud": "mcpgateway-api",
        "sub": "admin@example.com",
        "exp": now + 86400  # 24 hours
    }

    # Try PyJWT first (proper implementation)
    try:
        import jwt
        return jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    except ImportError:
        pass

    # Fallback: manual JWT generation with compact JSON (no spaces)
    import base64
    import hashlib
    import hmac
    import json as json_module

    header = {"alg": "HS256", "typ": "JWT"}

    def b64url(data):
        # Use separators to get compact JSON without spaces
        json_str = json_module.dumps(data, separators=(",", ":"))
        return base64.urlsafe_b64encode(json_str.encode()).rstrip(b"=").decode()

    header_b64 = b64url(header)
    payload_b64 = b64url(payload)
    message = f"{header_b64}.{payload_b64}"
    signature = hmac.new(JWT_SECRET.encode(), message.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

    return f"{message}.{sig_b64}"


class GatewayMCPUser(User):
    """Load test for MCP protocol through the gateway virtual server.

    Tests the MCP protocol through the gateway to measure the overhead
    of routing through the gateway vs direct connection.

    Uses the virtual server endpoint: /servers/{server_id}/mcp

    To enable: Select in class picker (Web UI) or set weight > 0
    """

    weight = 1  # Enabled by default
    wait_time = between(0.1, 0.5)

    def __init__(self, *args, **kwargs):
        """Initialize with requests session for gateway MCP calls."""
        super().__init__(*args, **kwargs)
        import requests
        self._session = requests.Session()
        self._request_id = 0
        self._initialized = False
        self._mcp_session_id = None
        self._token = _generate_jwt_token()
        self._mcp_url = f"{GATEWAY_URL}/servers/{GATEWAY_SERVER_ID}/mcp"
        logger.info(f"Gateway MCP client configured for {self._mcp_url}")

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
            request_type="GW-MCP",
            name=name,
            response_time=elapsed,
            response_length=0,
            exception=exception,
        )

    def _mcp_request(self, method: str, params: dict = None):
        """Make an MCP JSON-RPC request through the gateway."""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self._next_id()
        }
        if params:
            payload["params"] = params

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}"
        }
        if self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id

        response = self._session.post(
            self._mcp_url,
            json=payload,
            headers=headers,
            timeout=10
        )

        # Capture session ID from response header
        if "Mcp-Session-Id" in response.headers:
            self._mcp_session_id = response.headers["Mcp-Session-Id"]

        response.raise_for_status()
        result = response.json()

        if "error" in result:
            raise Exception(f"MCP error: {result['error']}")

        return result.get("result")

    def _ensure_initialized(self):
        """Ensure MCP session is initialized."""
        if not self._initialized:
            self._mcp_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "locust-gateway-client", "version": "1.0"}
            })
            self._initialized = True

    @task(10)
    @tag("gateway", "mcp", "time")
    def gw_get_system_time(self):
        """Gateway MCP: Call get_system_time tool."""
        tz = random.choice(TIMEZONES)
        start = time.perf_counter()
        try:
            self._ensure_initialized()
            result = self._mcp_request("tools/call", {
                "name": "fast-time-get-system-time",
                "arguments": {"timezone": tz}
            })
            # Validate response contains time data
            content = result.get("content", [])
            if not content or "text" not in content[0]:
                raise Exception("Invalid response: missing time content")
            self._fire_request("get_system_time", start)
        except Exception as e:
            self._fire_request("get_system_time", start, e)

    @task(5)
    @tag("gateway", "mcp", "convert")
    def gw_convert_time(self):
        """Gateway MCP: Call convert_time tool."""
        source_tz = random.choice(TIMEZONES)
        target_tz = random.choice([t for t in TIMEZONES if t != source_tz])
        start = time.perf_counter()
        try:
            self._ensure_initialized()
            result = self._mcp_request("tools/call", {
                "name": "fast-time-convert-time",
                "arguments": {
                    "time": "2025-01-15T10:30:00Z",
                    "source_timezone": source_tz,
                    "target_timezone": target_tz
                }
            })
            # Validate response contains converted time
            content = result.get("content", [])
            if not content or "text" not in content[0]:
                raise Exception("Invalid response: missing converted time")
            self._fire_request("convert_time", start)
        except Exception as e:
            self._fire_request("convert_time", start, e)

    @task(3)
    @tag("gateway", "mcp", "list")
    def gw_list_tools(self):
        """Gateway MCP: List available tools."""
        start = time.perf_counter()
        try:
            self._ensure_initialized()
            result = self._mcp_request("tools/list", {})
            # Validate response contains tools
            tools = result.get("tools", [])
            if not tools:
                raise Exception("Invalid response: no tools returned")
            self._fire_request("list_tools", start)
        except Exception as e:
            self._fire_request("list_tools", start, e)


# =============================================================================
# PostgreSQL Direct Tests (requires psycopg)
# =============================================================================

class PostgresUser(User):
    """Direct PostgreSQL performance testing.

    NOTE: This user class tests PostgreSQL directly, not through HTTP.
    It uses the Locust event system to report metrics.
    No HTTP host required - connects directly to PostgreSQL.

    Requires: psycopg[binary] (psycopg3)

    To enable: Select in class picker (Web UI) or set weight > 0
    """

    weight = 1  # Enabled by default
    wait_time = between(0.1, 0.3)

    def __init__(self, *args, **kwargs):
        """Initialize with PostgreSQL connection."""
        super().__init__(*args, **kwargs)
        self.conn = None
        try:
            import psycopg
            self.conn = psycopg.connect(
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                dbname=POSTGRES_DB
            )
            logger.info("PostgreSQL connection established")
        except ImportError:
            logger.warning("psycopg not installed - PostgreSQL tests disabled")
        except Exception as e:
            logger.warning(f"PostgreSQL connection failed: {e}")

    def on_stop(self):
        """Close PostgreSQL connection."""
        if self.conn:
            self.conn.close()

    def _fire_request(self, name: str, start_time: float, exception: Exception = None):
        """Fire a request event for Locust metrics."""
        elapsed = (time.perf_counter() - start_time) * 1000
        events.request.fire(
            request_type="PSQL",
            name=name,
            response_time=elapsed,
            response_length=0,
            exception=exception,
        )

    @task(10)
    @tag("postgres", "read")
    def simple_select(self):
        """Simple SELECT query."""
        if not self.conn:
            return
        start = time.perf_counter()
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            self._fire_request("SELECT 1", start)
        except Exception as e:
            self._fire_request("SELECT 1", start, e)

    @task(5)
    @tag("postgres", "read")
    def count_tools(self):
        """Count tools in database."""
        if not self.conn:
            return
        start = time.perf_counter()
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM tools")
                cur.fetchone()
            self._fire_request("COUNT tools", start)
        except Exception as e:
            self._fire_request("COUNT tools", start, e)


# =============================================================================
# Redis Direct Tests (requires redis)
# =============================================================================

class RedisUser(User):
    """Direct Redis performance testing.

    NOTE: This user class tests Redis directly, not through HTTP.
    It uses the Locust event system to report metrics.
    No HTTP host required - connects directly to Redis.

    Requires: redis

    To enable: Select in class picker (Web UI) or set weight > 0
    """

    weight = 1  # Enabled by default
    wait_time = between(0.05, 0.2)

    def __init__(self, *args, **kwargs):
        """Initialize with Redis connection."""
        super().__init__(*args, **kwargs)
        self.redis_client = None
        try:
            import redis
            self.redis_client = redis.from_url(REDIS_URL)
            self.redis_client.ping()
            logger.info("Redis connection established")
        except ImportError:
            logger.warning("redis not installed - Redis tests disabled")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")

    def _fire_request(self, name: str, start_time: float, exception: Exception = None):
        """Fire a request event for Locust metrics."""
        elapsed = (time.perf_counter() - start_time) * 1000
        events.request.fire(
            request_type="REDIS",
            name=name,
            response_time=elapsed,
            response_length=0,
            exception=exception,
        )

    @task(10)
    @tag("redis", "read")
    def ping(self):
        """Redis PING command."""
        if not self.redis_client:
            return
        start = time.perf_counter()
        try:
            self.redis_client.ping()
            self._fire_request("PING", start)
        except Exception as e:
            self._fire_request("PING", start, e)

    @task(8)
    @tag("redis", "write")
    def set_get(self):
        """Redis SET/GET cycle."""
        if not self.redis_client:
            return
        key = f"loadtest:{random.randint(1, 1000)}"
        value = f"value_{time.perf_counter()}"

        # SET
        start = time.perf_counter()
        try:
            self.redis_client.set(key, value, ex=60)
            self._fire_request("SET", start)
        except Exception as e:
            self._fire_request("SET", start, e)
            return

        # GET
        start = time.perf_counter()
        try:
            self.redis_client.get(key)
            self._fire_request("GET", start)
        except Exception as e:
            self._fire_request("GET", start, e)

    @task(3)
    @tag("redis", "read")
    def info(self):
        """Redis INFO command."""
        if not self.redis_client:
            return
        start = time.perf_counter()
        try:
            self.redis_client.info("stats")
            self._fire_request("INFO stats", start)
        except Exception as e:
            self._fire_request("INFO stats", start, e)
