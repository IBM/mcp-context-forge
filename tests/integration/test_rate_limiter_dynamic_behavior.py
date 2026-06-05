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
from tests.helpers.mcp_session import initialize_mcp_session

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080")
GATEWAY_EMAIL = os.environ.get("GATEWAY_EMAIL", "admin@example.com")
GATEWAY_PASSWORD = os.environ.get("GATEWAY_PASSWORD", "changeme")

PLUGIN_NAME = "RateLimiterPlugin"

# Wait after admin changes for propagation (NGINX cache TTL + pub/sub)
PROPAGATION_WAIT = int(os.environ.get("PROPAGATION_WAIT", str(PLUGIN_MODE_PROPAGATION_WAIT_SECONDS)))

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
    for server in resp.json():
        tools = server.get("associatedTools", [])
        # Prefer echo tool (echoes back, cheap), fall back to any time tool
        for tool in tools:
            if "echo" in tool.lower():
                return server["id"], tool
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


def _send_tool_burst(server_id: str, tool_name: str, count: int) -> dict:
    """Send a burst of tool calls and return counts of allowed vs rate-limited.

    Performs an MCP initialize + initialized handshake first to obtain a
    session id, then issues all ``count`` tools/call requests with that
    id in the ``Mcp-Session-Id`` header.

    Returns:
        {"allowed": int, "rate_limited": int, "errors": int, "total": int}
    """
    allowed = 0
    rate_limited = 0
    errors = 0

    # Single token reused for the handshake and every burst call below; the
    # gateway doesn't bind sessions to the originating token, but two independent
    # `_fresh_headers()` calls cost two POST /auth/login round-trips and obscure
    # which token is actually paired with `Mcp-Session-Id`.
    base_headers = _fresh_headers()

    sid = initialize_mcp_session(
        GATEWAY_URL, server_id, base_headers,
        client_name="rate-limiter-dynamic-test",
    )
    if sid is None:
        # Returning an all-errors counter would let
        # `test_burst_all_allowed_when_disabled` evaluate `0 == 0` and
        # `0 == BURST_SIZE - BURST_SIZE` — both pass, so a total handshake
        # failure looks like a green test. Mirror the multi-tenant file's
        # pattern (PR #4635 R4) and surface a descriptive failure instead.
        pytest.fail(
            f"MCP session handshake failed for server {server_id!r} — "
            f"see logger output for the failing step"
        )

    headers = {
        **base_headers,
        "Accept": "application/json, text/event-stream",
        "Mcp-Session-Id": sid,
    }

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
                f"{GATEWAY_URL}/servers/{server_id}/mcp",
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
        """After changing mode, GET /admin/plugins reflects an active (non-disabled) mode.

        The admin-mode API accepts ``"enforce"`` / ``"permissive"`` / ``"disabled"``
        from the operator. Since the cpex framework refactor, ``GET /admin/plugins``
        reports the framework's internal mode label, which differs from the
        operator-facing label (``"enforce"`` becomes ``"sequential"``,
        ``"permissive"`` becomes ``"transform"``). The test only needs to confirm
        the toggle takes effect — i.e. the reported mode is no longer ``"disabled"``.
        """
        _set_plugin_mode("enforce")
        time.sleep(PROPAGATION_WAIT)

        state = _get_plugin_state()
        plugins = {p["name"]: p for p in state.get("plugins", [])}
        assert PLUGIN_NAME in plugins, "RateLimiterPlugin not in plugin list"
        reported_mode = plugins[PLUGIN_NAME]["mode"]
        # TEMP (issue #4709): /admin/plugins reports the framework's internal
        # mode label ("sequential"), not the operator label ("enforce") that
        # we PUT. Once the asymmetry between /admin/plugins and
        # /v1/tools/plugin_bindings/ is resolved (issue #4709), revert this
        # back to:  assert reported_mode == "enforce"
        expected_framework_mode = "sequential"
        assert reported_mode == expected_framework_mode, (
            f"After PUT mode=enforce, /admin/plugins should report "
            f"{expected_framework_mode!r} (framework label, see issue #4709); "
            f"got {reported_mode!r}"
        )

    def test_mode_reverts_in_admin_api_after_disable(self, server_and_tool):
        """After disabling, GET /admin/plugins reflects disabled mode."""
        _set_plugin_mode("enforce")
        time.sleep(PROPAGATION_WAIT)
        _set_plugin_mode("disabled")
        time.sleep(PROPAGATION_WAIT)

        state = _get_plugin_state()
        plugins = {p["name"]: p for p in state.get("plugins", [])}
        assert plugins[PLUGIN_NAME]["mode"] == "disabled"
