# -*- coding: utf-8 -*-
"""Streamable HTTP echo-with-delay load test for ContextForge.

Measures gateway throughput when the backend MCP tool has an artificial delay,
exercising the full Streamable HTTP path: /servers/{server_id}/mcp.

Each Locust user establishes one MCP session (initialize + Mcp-Session-Id) and
then repeatedly calls fast-test-echo with a configurable delay (default 500ms).

Usage (containerized — recommended):
    make load-test-echo-delay          # headless, 200 users, 3min
    make load-test-echo-delay-ui       # web UI at http://localhost:8089

Usage (local):
    cd tests/loadtest
    locust -f locustfile_echo_delay.py --host=http://localhost:4444 \\
           --users=200 --spawn-rate=20 --run-time=180s --headless

Environment Variables:
    MCPGATEWAY_BEARER_TOKEN:   JWT token (auto-loaded from /tokens/gateway.jwt in container)
    ECHO_DELAY_MS:             Delay in milliseconds for each echo call (default: 500)
    ECHO_DELAY_SERVER_ID:      Virtual server ID (default: matches register_fast_test in docker-compose)
    JWT_SECRET_KEY:            Secret for auto-generating JWT if token not provided (default: my-test-key)
    NUM_TENANTS:               Number of discrete tenants to simulate (default: 10)

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import itertools
import logging
import os
import random
import time
import uuid
from pathlib import Path

from locust import User, between, events, tag, task
from locust.runners import MasterRunner, WorkerRunner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================


def _load_env_file() -> dict[str, str]:
    """Load environment variables from .env file."""
    env_vars: dict[str, str] = {}
    search_paths = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path.cwd().parent.parent / ".env",
        Path(__file__).parent.parent.parent / ".env",
    ]
    for path in search_paths:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, _, value = line.partition("=")
                            key = key.strip()
                            value = value.strip()
                            if value and value[0] in ('"', "'") and value[-1] == value[0]:
                                value = value[1:-1]
                            env_vars[key] = value
            except Exception as e:
                logger.warning(f"Error reading .env file: {e}")
            break
    return env_vars


_ENV_FILE_VARS = _load_env_file()


def _cfg(key: str, default: str = "") -> str:
    return os.environ.get(key) or _ENV_FILE_VARS.get(key, default)


# Auth
BEARER_TOKEN = _cfg("MCPGATEWAY_BEARER_TOKEN", "")
JWT_SECRET = _cfg("JWT_SECRET_KEY", "my-test-key")
WXO_AUTH_ENABLED = _cfg("LOCUST_WXO_AUTH_ENABLED", "true").lower() in ("true", "1", "yes")

# Echo delay settings
ECHO_DELAY_MS = int(_cfg("ECHO_DELAY_MS", "500"))

# Multi-tenant settings
NUM_TENANTS = int(_cfg("NUM_TENANTS", "10"))
if NUM_TENANTS < 1:
    raise ValueError(f"NUM_TENANTS must be >= 1, got {NUM_TENANTS}")
TENANT_IDS = [f"tenant-{i:03d}" for i in range(NUM_TENANTS)]

# Virtual server ID — matches the fixed ID created by register_fast_test in docker-compose
# Override via ECHO_DELAY_SERVER_ID to target a different virtual server
FAST_TEST_SERVER_ID = _cfg("ECHO_DELAY_SERVER_ID", "b8e3f1a2c4d5e6f7a1b2c3d4e5f6a7b8")

# Direct URL to the fast_test_server REST API (bypasses gateway entirely).
# Used as a baseline to isolate whether errors originate in the gateway or the backend.
# In docker-compose this is the container hostname; override for local testing.
FAST_TEST_DIRECT_URL = _cfg("FAST_TEST_DIRECT_URL", "http://fast_test_server:8880")

# MCP protocol version (must match gateway config)
MCP_PROTOCOL_VERSION = "2025-11-25"

logger.info(f"Echo delay: {ECHO_DELAY_MS}ms")
logger.info(f"Virtual server ID: {FAST_TEST_SERVER_ID}")
logger.info(f"Tenants: {NUM_TENANTS} ({TENANT_IDS[0]} .. {TENANT_IDS[-1]})")


# =============================================================================
# JWT generation
# =============================================================================


# Monotonic counter for unique user IDs (thread-safe via GIL)
_user_counter = itertools.count(1)


def _generate_jwt_token(user_email: str, tenant_id: str) -> str | None:
    """Generate a JWT token with per-user identity and tenant claims.

    The woTenantId claim is read by the WXO auth plugin to map the user
    to the correct team.
    """
    now = int(time.time())
    payload = {
        "username": user_email,
        "iat": now,
        "iss": "mcpgateway",
        "aud": "mcpgateway-api",
        "sub": user_email,
        "exp": now + 86400,
        "woTenantId": tenant_id,
    }
    try:
        import jwt  # noqa: E402  # pylint: disable=import-outside-toplevel

        return jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    except ImportError:
        pass

    # Manual fallback
    import base64  # pylint: disable=import-outside-toplevel
    import hashlib  # pylint: disable=import-outside-toplevel
    import hmac  # pylint: disable=import-outside-toplevel
    import json as json_mod  # pylint: disable=import-outside-toplevel

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64url(json_mod.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url(json_mod.dumps(payload, separators=(",", ":")).encode())
    sig = b64url(hmac.new(JWT_SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def _create_user_identity() -> tuple[str, str, str]:
    """Create a unique user identity with a randomly assigned tenant.

    Returns:
        Tuple of (user_id, user_email, tenant_id).
    """
    user_num = next(_user_counter)
    tenant_id = random.choice(TENANT_IDS)
    user_id = f"user-{user_num:04d}-{uuid.uuid4().hex[:8]}"
    user_email = f"{user_id}@loadtest.example.com"
    return user_id, user_email, tenant_id


# =============================================================================
# Default parameters for Web UI
# =============================================================================


@events.init_command_line_parser.add_listener
def set_defaults(parser):
    parser.set_defaults(
        users=200,
        spawn_rate=20,
        run_time="180s",
    )


# =============================================================================
# Event handlers
# =============================================================================


@events.test_start.add_listener
def on_test_start(environment, **_kwargs):
    """Log test configuration at start."""
    if isinstance(environment.runner, WorkerRunner):
        return

    host = environment.host or "http://localhost:4444"

    logger.info("=" * 60)
    logger.info("ECHO DELAY STREAMABLE HTTP LOAD TEST")
    logger.info("=" * 60)
    logger.info(f"  Gateway:    {host}")
    logger.info(f"  Echo delay: {ECHO_DELAY_MS}ms")
    logger.info(f"  Tenants:    {NUM_TENANTS}")
    logger.info(f"  MCP path:   /servers/{FAST_TEST_SERVER_ID}/mcp")
    logger.info("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment, **_kwargs):
    """Print throughput summary."""
    if isinstance(environment.runner, MasterRunner):
        return

    stats = environment.stats
    total = stats.total.num_requests
    failures = stats.total.num_failures
    fail_rate = (failures / total * 100) if total > 0 else 0

    print("\n" + "=" * 80)
    print("ECHO DELAY LOAD TEST SUMMARY")
    print("=" * 80)
    print(f"\n  Tenants:            {NUM_TENANTS}")
    print(f"  Echo delay:         {ECHO_DELAY_MS}ms")
    print(f"  Total Requests:     {total:,}")
    print(f"  Total Failures:     {failures:,} ({fail_rate:.2f}%)")
    print(f"  Requests/sec (RPS): {stats.total.total_rps:.2f}")
    print("\n  Response Times (ms):")
    print(f"    Average:          {stats.total.avg_response_time:.2f}")
    print(f"    Min:              {stats.total.min_response_time:.2f}")
    print(f"    Max:              {stats.total.max_response_time:.2f}")
    if total > 0:
        print(f"    Median (p50):     {stats.total.get_response_time_percentile(0.5):.2f}")
        print(f"    p90:              {stats.total.get_response_time_percentile(0.9):.2f}")
        print(f"    p95:              {stats.total.get_response_time_percentile(0.95):.2f}")
        print(f"    p99:              {stats.total.get_response_time_percentile(0.99):.2f}")

    # Theoretical max: users / (delay_s + overhead)
    print(f"\n  Theoretical max RPS at {ECHO_DELAY_MS}ms delay:")
    print(f"    (users / {ECHO_DELAY_MS/1000:.1f}s) = ~{environment.runner.user_count / (ECHO_DELAY_MS / 1000):.0f} RPS")
    print("=" * 80)


# =============================================================================
# User class
# =============================================================================


class EchoDelayUser(User):
    """Streamable HTTP MCP user that calls fast-test-echo with a delay.

    Each user:
    1. Establishes an MCP session via initialize
    2. Repeatedly calls fast-test-echo with the configured delay
    3. Reports metrics via Locust event system
    """

    weight = 1
    wait_time = between(0.0, 0.1)  # Minimal wait — the delay is server-side

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        import requests  # pylint: disable=import-outside-toplevel

        self._session = requests.Session()
        self._request_id = 0
        self._mcp_session_id = None
        self._initialized = False
        self._mcp_url = None
        self._sample_logged = False

        # Assign unique identity and tenant
        self._user_id, self._user_email, self._tenant_id = _create_user_identity()
        if WXO_AUTH_ENABLED:
            self._token = _generate_jwt_token(self._user_email, self._tenant_id)
            if not self._token:
                raise RuntimeError(f"Failed to generate JWT for {self._user_email}")
            logger.info(f"User {self._user_id} assigned to {self._tenant_id}")
        else:
            # Use the admin token generated by locust_token service
            if not BEARER_TOKEN:
                raise RuntimeError("WXO auth disabled but MCPGATEWAY_BEARER_TOKEN is not set. Provide a bearer token or enable WXO auth.")
            self._token = BEARER_TOKEN
            logger.info(f"User {self._user_id} (WXO auth disabled, using admin token)")

        # Echo messages to rotate through
        self._messages = [
            "load-test-echo",
            "performance-benchmark",
            "throughput-measurement",
            "delay-test-payload",
            "streamable-http-test",
        ]

    def on_start(self):
        """Build the MCP URL targeting the fast_test virtual server."""
        host = self.host or "http://localhost:4444"
        self._mcp_url = f"{host}/servers/{FAST_TEST_SERVER_ID}/mcp"

    def on_stop(self):
        if self._session:
            self._session.close()

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        if self._mcp_session_id:
            h["Mcp-Session-Id"] = self._mcp_session_id
        return h

    def _mcp_post(self, method: str, params: dict | None, name: str) -> dict | None:
        """POST a JSON-RPC request to the MCP endpoint and report to Locust."""
        if not self._mcp_url:
            events.request.fire(
                request_type="MCP",
                name=name,
                response_time=0,
                response_length=0,
                exception=Exception("No MCP URL — server ID discovery failed"),
            )
            return None

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        start = time.perf_counter()
        try:
            resp = self._session.post(self._mcp_url, json=payload, headers=self._headers(), timeout=30)
            elapsed_ms = (time.perf_counter() - start) * 1000

            # Capture session ID
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self._mcp_session_id = sid

            if resp.status_code != 200:
                # Include body snippet for diagnosis (auth errors, backpressure, etc.)
                body_preview = resp.text[:200] if resp.text else ""
                events.request.fire(
                    request_type="MCP",
                    name=name,
                    response_time=elapsed_ms,
                    response_length=len(resp.content),
                    exception=Exception(f"HTTP {resp.status_code}: {body_preview}"),
                )
                return None

            body = resp.json()
            if "error" in body:
                events.request.fire(
                    request_type="MCP",
                    name=name,
                    response_time=elapsed_ms,
                    response_length=len(resp.content),
                    exception=Exception(f"JSON-RPC error {body['error'].get('code', '?')}: {body['error'].get('message', '?')}"),
                )
                return None

            result = body.get("result")

            # Check for MCP tool-level errors (isError=true in the result)
            if isinstance(result, dict) and result.get("isError"):
                content = result.get("content", [])
                err_text = ""
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        err_text = item.get("text", "")
                        break
                events.request.fire(
                    request_type="MCP",
                    name=name,
                    response_time=elapsed_ms,
                    response_length=len(resp.content),
                    exception=Exception(f"MCP tool error: {err_text[:200]}"),
                )
                return None

            events.request.fire(
                request_type="MCP",
                name=name,
                response_time=elapsed_ms,
                response_length=len(resp.content),
            )
            return result

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            events.request.fire(
                request_type="MCP",
                name=name,
                response_time=elapsed_ms,
                response_length=0,
                exception=e,
            )
            return None

    def _ensure_initialized(self):
        """Initialize the MCP session if not already done."""
        if self._initialized:
            return
        result = self._mcp_post(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "locust-echo-delay", "version": "1.0"},
            },
            "initialize",
        )
        if result is not None:
            self._initialized = True

    @task(10)
    @tag("mcp", "echo", "delay")
    def call_echo_with_delay(self):
        """Call fast-test-echo with the configured delay."""
        self._ensure_initialized()
        message = random.choice(self._messages)
        result = self._mcp_post(
            "tools/call",
            {
                "name": "fast-test-echo",
                "arguments": {"message": message, "delay": ECHO_DELAY_MS},
            },
            f"echo (delay={ECHO_DELAY_MS}ms)",
        )
        # Log one sample response for debugging
        if result is not None and not self._sample_logged:
            logger.info(f"Sample echo response: {result}")
            self._sample_logged = True

    @task(1)
    @tag("mcp", "list")
    def list_tools(self):
        """List tools as a lightweight heartbeat."""
        self._ensure_initialized()
        self._mcp_post("tools/list", {}, "tools/list")

    # Uncomment to enable direct baseline (bypasses gateway, useful for isolating bottlenecks)
    # @task(2)
    # @tag("direct", "baseline")
    def direct_echo_baseline(self):
        """Call the fast_test_server REST API directly, bypassing the gateway.

        Reported as request_type="DIRECT" so it appears separately in Locust stats.
        If this succeeds while MCP tasks fail, the problem is in the gateway layer.
        If this also fails, the fast_test_server itself is overloaded.
        """
        message = random.choice(self._messages)
        payload = {"message": message, "delay": ECHO_DELAY_MS}
        start = time.perf_counter()
        try:
            resp = self._session.post(
                f"{FAST_TEST_DIRECT_URL}/api/echo",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            if resp.status_code == 200:
                events.request.fire(
                    request_type="DIRECT",
                    name=f"direct echo (delay={ECHO_DELAY_MS}ms)",
                    response_time=elapsed_ms,
                    response_length=len(resp.content),
                )
            else:
                events.request.fire(
                    request_type="DIRECT",
                    name=f"direct echo (delay={ECHO_DELAY_MS}ms)",
                    response_time=elapsed_ms,
                    response_length=len(resp.content),
                    exception=Exception(f"HTTP {resp.status_code}"),
                )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            events.request.fire(
                request_type="DIRECT",
                name=f"direct echo (delay={ECHO_DELAY_MS}ms)",
                response_time=elapsed_ms,
                response_length=0,
                exception=e,
            )
