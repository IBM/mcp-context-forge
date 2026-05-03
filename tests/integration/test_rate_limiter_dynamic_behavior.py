# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_rate_limiter_dynamic_behavior.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for rate limiter dynamic behavior.

Verifies that runtime mode changes to the RateLimiterPlugin via the admin API
actually affect rate limiting behavior on tool calls.

The rate limiter is configured in plugins/config.yaml with:
    mode: "disabled"
    by_user: "30/m"
    backend: "redis" (with redis_fallback: true)

Tests toggle the mode at runtime and verify tool calls are rate-limited
(or not) accordingly.

Requirements:
    - Running gateway (docker-compose with 3 replicas)
    - NGINX load balancer on port 8080
    - Redis available
    - fast-test-server or fast-time-server registered

Usage:
    uv run pytest tests/integration/test_rate_limiter_dynamic_behavior.py -v --with-integration
"""

# Standard
import os
import time
import uuid

# Third-Party
import pytest
import requests

from tests.helpers.integration_constants import PLUGIN_MODE_PROPAGATION_WAIT_SECONDS

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080")
GATEWAY_EMAIL = os.environ.get("GATEWAY_EMAIL", "admin@example.com")
GATEWAY_PASSWORD = os.environ.get("GATEWAY_PASSWORD", "changeme")

PLUGIN_NAME = "RateLimiterPlugin"
MCP_PROTOCOL_VERSION = "2025-11-25"

# Wait after admin changes for propagation (NGINX cache TTL + pub/sub)
PROPAGATION_WAIT = int(os.environ.get("PROPAGATION_WAIT", str(PLUGIN_MODE_PROPAGATION_WAIT_SECONDS)))

# Wait long enough for Redis rate-limit counters to expire between phases.
TTL_EXPIRY_WAIT = int(os.environ.get("RATE_LIMITER_TTL_EXPIRY_WAIT", "75"))

# Number of requests to send per burst — must exceed the configured
# by_user limit (30/m) to observe rate limiting
BURST_SIZE = 40

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_session_token() -> str:
    """Login and return a session token."""
    resp = requests.post(
        f"{GATEWAY_URL}/auth/login",
        json={"email": GATEWAY_EMAIL, "password": GATEWAY_PASSWORD},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _fresh_headers() -> dict:
    """Get fresh auth headers."""
    return {
        "Authorization": f"Bearer {_get_session_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _fresh_mcp_headers(
    token: str | None = None,
    session_id: str | None = None,
) -> dict:
    """Get MCP JSON-RPC headers for the server-scoped transport."""
    bearer = token or _get_session_token()
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }
    if session_id:
        headers["mcp-session-id"] = session_id
    return headers


def _is_gateway_running() -> bool:
    """Check if the gateway is reachable."""
    try:
        resp = requests.get(f"{GATEWAY_URL}/health", timeout=5)
        return resp.status_code == 200
    except requests.ConnectionError:
        return False


def _auto_detect_server_and_tool() -> tuple[str, str]:
    """Find a server ID and tool name for testing."""
    headers = _fresh_headers()
    resp = requests.get(f"{GATEWAY_URL}/servers", headers=headers, timeout=10)
    resp.raise_for_status()

    # Prefer an echo-capable server globally because it exercises the tool path
    # without requiring transport-specific session setup.
    for server in resp.json():
        tools = server.get("associatedTools", [])
        for tool in tools:
            if "echo" in tool.lower():
                return server["id"], tool

    for server in resp.json():
        tools = server.get("associatedTools", [])
        for tool in tools:
            if "time" in tool.lower() and "convert" not in tool.lower():
                return server["id"], tool
    pytest.skip("No suitable server/tool found for rate limiter test")


def _set_plugin_mode(mode: str) -> dict:
    """Set the rate limiter mode via admin API. Returns the response body."""
    headers = _fresh_headers()
    resp = requests.put(
        f"{GATEWAY_URL}/admin/plugins/{PLUGIN_NAME}",
        json={"mode": mode},
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _get_plugin_state() -> dict:
    """Get the current plugin state from admin API."""
    headers = _fresh_headers()
    resp = requests.get(
        f"{GATEWAY_URL}/admin/plugins",
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _initialize_mcp_session(
    server_id: str,
    token: str | None = None,
) -> str | None:
    """Initialize an MCP session for server-scoped tool calls."""
    resp = requests.post(
        f"{GATEWAY_URL}/servers/{server_id}/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "rate-limiter-dynamic-test", "version": "1.0.0"},
            },
        },
        headers=_fresh_mcp_headers(token=token),
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    assert "result" in data, f"Initialize failed: {data}"
    return resp.headers.get("mcp-session-id")


def _send_tool_burst(
    server_id: str,
    tool_name: str,
    count: int,
    token: str | None = None,
) -> dict:
    """Send a burst of tool calls and return counts of allowed vs rate-limited.

    Returns:
        {"allowed": int, "rate_limited": int, "errors": int, "total": int}
    """
    allowed = 0
    rate_limited = 0
    errors = 0
    session_id = _initialize_mcp_session(server_id, token=token)
    headers = _fresh_mcp_headers(token=token, session_id=session_id)

    for i in range(count):
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": {"message": f"rate-limit-test-{i}"} if "echo" in tool_name else {},
            },
        }
        try:
            resp = requests.post(
                f"{GATEWAY_URL}/servers/{server_id}/mcp/",
                json=payload,
                headers=headers,
                timeout=15,
            )

            if resp.status_code == 429:
                rate_limited += 1
                continue

            if resp.status_code != 200:
                errors += 1
                continue

            data = resp.json()
            result = data.get("result", {})

            # Check for MCP-level rate limit error (isError with rate/limit in content)
            if result.get("isError"):
                content = result.get("content", [])
                text = content[0].get("text", "") if content else ""
                if "rate" in text.lower() or "limit" in text.lower():
                    rate_limited += 1
                else:
                    errors += 1
            else:
                allowed += 1

        except requests.RequestException:
            errors += 1

    return {
        "allowed": allowed,
        "rate_limited": rate_limited,
        "errors": errors,
        "total": count,
    }


# ---------------------------------------------------------------------------
# Skip if gateway not running
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    not _is_gateway_running(),
    reason=f"Gateway not running at {GATEWAY_URL}",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def server_and_tool():
    """Auto-detect server ID and tool name once for the module."""
    return _auto_detect_server_and_tool()


@pytest.fixture(autouse=True)
def ensure_rate_limiter_disabled():
    """Disable the rate limiter before and after each test."""
    _set_plugin_mode("disabled")
    time.sleep(PROPAGATION_WAIT)
    yield
    _set_plugin_mode("disabled")
    time.sleep(PROPAGATION_WAIT)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRateLimiterDisabledAllowsAll:
    """When rate limiter is disabled, all requests should pass through."""

    def test_burst_all_allowed_when_disabled(self, server_and_tool):
        """With rate limiter disabled, a burst of requests should all succeed."""
        server_id, tool_name = server_and_tool
        result = _send_tool_burst(server_id, tool_name, BURST_SIZE)

        assert result["rate_limited"] == 0, f"Rate limiter should be disabled but {result['rate_limited']}/{result['total']} " f"requests were rate-limited"
        assert result["allowed"] == result["total"] - result["errors"], f"All non-error requests should be allowed: {result}"


class TestRateLimiterEnforceBlocks:
    """When rate limiter is enabled, requests exceeding the limit should be blocked."""

    def test_burst_some_blocked_when_enforcing(self, server_and_tool):
        """With rate limiter enforcing (30/m), a burst of 40 requests should see some blocked."""
        server_id, tool_name = server_and_tool

        # Enable rate limiter
        resp = _set_plugin_mode("enforce")
        assert resp["mode"] == "enforce"
        time.sleep(PROPAGATION_WAIT)

        # Send burst — should exceed 30/m limit
        result = _send_tool_burst(server_id, tool_name, BURST_SIZE)

        assert result["rate_limited"] > 0, f"Rate limiter should be enforcing (by_user: 30/m) but no requests were " f"rate-limited out of {result['total']}: {result}"


class TestRateLimiterRedisState:
    """Verify that rate limiter mode changes are persisted in Redis."""

    def test_mode_stored_in_redis(self, server_and_tool):
        """PUT mode=enforce stores the mode in Redis with redis_persisted=true."""
        resp = _set_plugin_mode("enforce")
        assert resp["redis_persisted"] is True, f"Mode change should be Redis-persisted: {resp}"
        assert resp["mode"] == "enforce"

    def test_mode_visible_in_admin_api_after_change(self, server_and_tool):
        """After changing mode, GET /admin/plugins reflects the new mode."""
        _set_plugin_mode("enforce")
        time.sleep(PROPAGATION_WAIT)

        state = _get_plugin_state()
        plugins = {p["name"]: p for p in state.get("plugins", [])}
        assert PLUGIN_NAME in plugins, "RateLimiterPlugin not in plugin list"
        assert plugins[PLUGIN_NAME]["mode"] == "enforce", f"Expected mode=enforce, got {plugins[PLUGIN_NAME]['mode']}"

    def test_mode_reverts_in_admin_api_after_disable(self, server_and_tool):
        """After disabling, GET /admin/plugins reflects disabled mode."""
        _set_plugin_mode("enforce")
        time.sleep(PROPAGATION_WAIT)
        _set_plugin_mode("disabled")
        time.sleep(PROPAGATION_WAIT)

        state = _get_plugin_state()
        plugins = {p["name"]: p for p in state.get("plugins", [])}
        assert plugins[PLUGIN_NAME]["mode"] == "disabled"


@pytest.mark.slow
class TestRateLimiterToggleAfterTTLExpiry:
    """Validate re-enforcement after counters expire naturally.

    This is intentionally a time-based experiment, not rapid toggle-cycle
    coverage. It verifies that enforce mode still blocks after a quiet period
    long enough for Redis counters to expire.
    """

    def test_enforce_disable_enforce_cycle_after_ttl_expiry(self, server_and_tool):
        """Enforce should work again after disabled mode and a full TTL wait."""
        server_id, tool_name = server_and_tool

        _set_plugin_mode("enforce")
        time.sleep(PROPAGATION_WAIT)
        phase_1 = _send_tool_burst(server_id, tool_name, BURST_SIZE)
        assert phase_1["errors"] == 0, f"Phase 1 should complete without transport errors: {phase_1}"
        assert phase_1["rate_limited"] > 0, f"Phase 1 should rate-limit some requests: {phase_1}"

        time.sleep(TTL_EXPIRY_WAIT)

        _set_plugin_mode("disabled")
        time.sleep(PROPAGATION_WAIT)
        phase_2 = _send_tool_burst(server_id, tool_name, BURST_SIZE)
        assert phase_2["errors"] == 0, f"Phase 2 should complete without transport errors: {phase_2}"
        assert phase_2["rate_limited"] == 0, f"Phase 2 should allow all requests while disabled: {phase_2}"
        assert phase_2["allowed"] == phase_2["total"] - phase_2["errors"], f"Phase 2 expected all non-error requests to be allowed: {phase_2}"

        time.sleep(TTL_EXPIRY_WAIT)

        _set_plugin_mode("enforce")
        time.sleep(PROPAGATION_WAIT)
        phase_3 = _send_tool_burst(server_id, tool_name, BURST_SIZE)
        assert phase_3["errors"] == 0, f"Phase 3 should complete without transport errors: {phase_3}"
        assert phase_3["rate_limited"] > 0, f"Phase 3 should rate-limit again after TTL expiry: {phase_3}"
