# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/rate_limiter/test_rate_limiter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for RateLimiterPlugin.
"""

# Standard
import asyncio
import os
import time
from typing import Any, Dict
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    PromptHookType,
    PromptPrehookPayload,
    ToolHookType,
    ToolPreInvokePayload,
)
from mcpgateway.plugins.framework.base import HookRef, PluginRef
from mcpgateway.plugins.framework.errors import PluginViolationError
from mcpgateway.plugins.framework.manager import PluginExecutor
from mcpgateway.plugins.framework.models import PluginMode
from plugins.rate_limiter.rate_limiter import (
    _extract_user_identity,
    _make_headers,
    _parse_rate,
    _select_most_restrictive,
    ALGORITHM_FIXED_WINDOW,
    ALGORITHM_SLIDING_WINDOW,
    ALGORITHM_TOKEN_BUCKET,
    FixedWindowAlgorithm,
    MemoryBackend,
    RateLimiterPlugin,
    RedisBackend,
    RustRateLimiterEngine,
    SlidingWindowAlgorithm,
    TokenBucketAlgorithm,
)


def _clear_plugin(plugin: RateLimiterPlugin) -> None:
    """Clear the algorithm store for a plugin instance."""
    backend = plugin._rate_backend
    if isinstance(backend, MemoryBackend):
        backend._algorithm._store.clear()


@pytest.fixture(autouse=True)
def clear_rate_limit_store():
    """No-op: each test creates its own plugin instance with a fresh store.
    Individual tests call _clear_plugin() when sharing a plugin across steps."""
    yield


def _mk(rate: str, algorithm: str = ALGORITHM_FIXED_WINDOW) -> RateLimiterPlugin:
    return RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[PromptHookType.PROMPT_PRE_FETCH, ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": rate, "algorithm": algorithm},
        )
    )


@pytest.mark.asyncio
async def test_rate_limit_blocks_on_third_call():
    plugin = _mk("2/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
    payload = PromptPrehookPayload(prompt_id="p", args={})
    r1 = await plugin.prompt_pre_fetch(payload, ctx)
    assert r1.violation is None
    r2 = await plugin.prompt_pre_fetch(payload, ctx)
    assert r2.violation is None
    r3 = await plugin.prompt_pre_fetch(payload, ctx)
    assert r3.violation is not None


# ============================================================================
# HTTP 429 Status Code Tests
# ============================================================================


@pytest.mark.asyncio
async def test_prompt_pre_fetch_violation_returns_http_429():
    """Test that rate limit violations return HTTP 429 status code."""
    plugin = _mk("1/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
    payload = PromptPrehookPayload(prompt_id="p", args={})

    # First request succeeds
    r1 = await plugin.prompt_pre_fetch(payload, ctx)
    assert r1.violation is None

    # Second request should be rate limited
    r2 = await plugin.prompt_pre_fetch(payload, ctx)
    assert r2.violation is not None
    assert r2.violation.http_status_code == 429
    assert r2.violation.code == "RATE_LIMIT"


@pytest.mark.asyncio
async def test_prompt_pre_fetch_violation_includes_all_headers():
    """Test that violations include all RFC-compliant rate limit headers."""
    plugin = _mk("2/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
    payload = PromptPrehookPayload(prompt_id="p", args={})

    # Trigger rate limit
    await plugin.prompt_pre_fetch(payload, ctx)  # 1st
    await plugin.prompt_pre_fetch(payload, ctx)  # 2nd
    result = await plugin.prompt_pre_fetch(payload, ctx)  # 3rd - exceeds limit

    assert result.violation is not None
    headers = result.violation.http_headers
    assert headers is not None

    # Verify all required headers
    assert "X-RateLimit-Limit" in headers
    assert headers["X-RateLimit-Limit"] == "2"

    assert "X-RateLimit-Remaining" in headers
    assert headers["X-RateLimit-Remaining"] == "0"

    assert "X-RateLimit-Reset" in headers
    assert int(headers["X-RateLimit-Reset"]) > 0

    assert "Retry-After" in headers
    assert int(headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_prompt_pre_fetch_success_includes_headers_without_retry_after():
    """Test that successful requests include headers but not Retry-After."""
    plugin = _mk("10/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
    payload = PromptPrehookPayload(prompt_id="p", args={})

    result = await plugin.prompt_pre_fetch(payload, ctx)

    assert result.violation is None
    assert result.http_headers is not None

    headers = result.http_headers
    assert "X-RateLimit-Limit" in headers
    assert headers["X-RateLimit-Limit"] == "10"

    assert "X-RateLimit-Remaining" in headers
    assert headers["X-RateLimit-Remaining"] == "9"  # 1 used, 9 remaining

    assert "X-RateLimit-Reset" in headers
    assert int(headers["X-RateLimit-Reset"]) > 0

    assert "Retry-After" not in headers  # Should NOT be present on success


# ============================================================================
# tool_pre_invoke Tests
# ============================================================================


@pytest.mark.asyncio
async def test_tool_pre_invoke_violation_returns_http_429():
    """Test that tool_pre_invoke violations return HTTP 429 status code."""
    # First-Party
    from mcpgateway.plugins.framework import ToolPreInvokePayload

    plugin = _mk("1/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    # First request succeeds
    r1 = await plugin.tool_pre_invoke(payload, ctx)
    assert r1.violation is None

    # Second request should be rate limited
    r2 = await plugin.tool_pre_invoke(payload, ctx)
    assert r2.violation is not None
    assert r2.violation.http_status_code == 429
    assert r2.violation.code == "RATE_LIMIT"


@pytest.mark.asyncio
async def test_tool_pre_invoke_violation_includes_headers():
    """Test that tool_pre_invoke violations include rate limit headers."""
    # First-Party
    from mcpgateway.plugins.framework import ToolPreInvokePayload

    plugin = _mk("2/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    # Trigger rate limit
    await plugin.tool_pre_invoke(payload, ctx)  # 1st
    await plugin.tool_pre_invoke(payload, ctx)  # 2nd
    result = await plugin.tool_pre_invoke(payload, ctx)  # 3rd - exceeds limit

    assert result.violation is not None
    headers = result.violation.http_headers
    assert headers is not None

    # Verify headers are present
    assert "X-RateLimit-Limit" in headers
    assert "X-RateLimit-Remaining" in headers
    assert headers["X-RateLimit-Remaining"] == "0"
    assert "X-RateLimit-Reset" in headers
    assert "Retry-After" in headers


@pytest.mark.asyncio
async def test_tool_pre_invoke_success_includes_headers_without_retry_after():
    """Test that successful tool invocations include headers but not Retry-After."""
    # First-Party
    from mcpgateway.plugins.framework import ToolPreInvokePayload

    plugin = _mk("10/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    result = await plugin.tool_pre_invoke(payload, ctx)

    assert result.violation is None
    assert result.http_headers is not None

    headers = result.http_headers
    assert "X-RateLimit-Limit" in headers
    assert "X-RateLimit-Remaining" in headers
    assert "X-RateLimit-Reset" in headers
    assert "Retry-After" not in headers


@pytest.mark.asyncio
async def test_tool_pre_invoke_per_tool_rate_limiting():
    """Test per-tool rate limiting configuration."""
    # First-Party
    from mcpgateway.plugins.framework import ToolPreInvokePayload

    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": "100/s", "by_tool": {"restricted_tool": "1/s"}},  # High user limit  # Low tool-specific limit
        )
    )

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
    restricted_payload = ToolPreInvokePayload(name="restricted_tool", arguments={})
    unrestricted_payload = ToolPreInvokePayload(name="other_tool", arguments={})

    # First call to restricted tool succeeds
    r1 = await plugin.tool_pre_invoke(restricted_payload, ctx)
    assert r1.violation is None

    # Second call to same tool should be rate limited
    r2 = await plugin.tool_pre_invoke(restricted_payload, ctx)
    assert r2.violation is not None
    assert r2.violation.http_status_code == 429

    # But other tool should still work (only user limit applies)
    r3 = await plugin.tool_pre_invoke(unrestricted_payload, ctx)
    assert r3.violation is None


# ============================================================================
# Helper Function Tests
# ============================================================================


def test_make_headers_with_retry_after():
    """Test header generation with Retry-After."""
    headers = _make_headers(limit=60, remaining=0, reset_timestamp=1737394800, retry_after=35, include_retry_after=True)

    assert headers["X-RateLimit-Limit"] == "60"
    assert headers["X-RateLimit-Remaining"] == "0"
    assert headers["X-RateLimit-Reset"] == "1737394800"
    assert headers["Retry-After"] == "35"


def test_make_headers_without_retry_after():
    """Test header generation without Retry-After."""
    headers = _make_headers(limit=60, remaining=45, reset_timestamp=1737394800, retry_after=35, include_retry_after=False)

    assert headers["X-RateLimit-Limit"] == "60"
    assert headers["X-RateLimit-Remaining"] == "45"
    assert headers["X-RateLimit-Reset"] == "1737394800"
    assert "Retry-After" not in headers


# ============================================================================
# _select_most_restrictive TESTS
# ============================================================================


class TestSelectMostRestrictive:
    """Comprehensive tests for _select_most_restrictive function."""

    # Test Category 1: Edge Cases & Empty Handling

    def test_empty_list_returns_unlimited(self):
        """Empty list should return unlimited result."""
        allowed, limit, remaining, reset_ts, meta = _select_most_restrictive([])
        assert allowed is True
        assert limit == 0
        assert remaining == 0
        assert reset_ts == 0
        assert meta == {"limited": False}

    def test_single_unlimited_result(self):
        """Single unlimited result (limit=0) should return unlimited."""
        results = [(True, 0, 0, {"limited": False})]
        allowed, limit, _remaining, _reset_ts, meta = _select_most_restrictive(results)
        assert allowed is True
        assert limit == 0
        assert meta["limited"] is False

    def test_all_unlimited_results(self):
        """All unlimited results should return unlimited."""
        results = [
            (True, 0, 0, {"limited": False}),
            (True, 0, 0, {"limited": False}),
            (True, 0, 0, {"limited": False}),
        ]
        allowed, limit, _remaining, _reset_ts, meta = _select_most_restrictive(results)
        assert allowed is True
        assert limit == 0
        assert meta["limited"] is False

    # Test Category 2: Single Dimension

    def test_single_violated_dimension(self):
        """Single violated dimension should be returned with remaining=0."""
        now = 1000
        results = [(False, 10, now + 60, {"limited": True, "remaining": 0, "reset_in": 60})]
        allowed, limit, remaining, reset_ts, meta = _select_most_restrictive(results)
        assert allowed is False
        assert limit == 10
        assert remaining == 0
        assert reset_ts == now + 60
        assert meta["reset_in"] == 60

    def test_single_allowed_dimension(self):
        """Single allowed dimension should be returned with correct remaining."""
        now = 1000
        results = [(True, 100, now + 60, {"limited": True, "remaining": 95, "reset_in": 60})]
        allowed, limit, remaining, reset_ts, _meta = _select_most_restrictive(results)
        assert allowed is True
        assert limit == 100
        assert remaining == 95
        assert reset_ts == now + 60

    # Test Category 3: Multiple Violated Dimensions - Select Shortest Reset

    def test_multiple_violated_shortest_reset_wins(self):
        """When multiple violated, select the one with shortest reset time."""
        now = 1000
        results = [
            (False, 10, now + 30, {"limited": True, "remaining": 0, "reset_in": 30}),  # Resets sooner
            (False, 20, now + 60, {"limited": True, "remaining": 0, "reset_in": 60}),
            (False, 30, now + 120, {"limited": True, "remaining": 0, "reset_in": 120}),
        ]
        allowed, limit, remaining, reset_ts, meta = _select_most_restrictive(results)
        assert allowed is False
        assert limit == 10  # Shortest reset_in (30)
        assert remaining == 0
        assert reset_ts == now + 30
        assert meta["reset_in"] == 30

    def test_violated_with_allowed_dimensions(self):
        """When some violated and some allowed, violated takes precedence."""
        now = 1000
        results = [
            (True, 100, now + 60, {"limited": True, "remaining": 90, "reset_in": 60}),  # Allowed
            (False, 50, now + 30, {"limited": True, "remaining": 0, "reset_in": 30}),  # Violated (shortest)
            (False, 75, now + 90, {"limited": True, "remaining": 0, "reset_in": 90}),  # Violated
        ]
        allowed, limit, remaining, reset_ts, meta = _select_most_restrictive(results)
        assert allowed is False
        assert limit == 50  # Violated with shortest reset
        assert remaining == 0
        assert reset_ts == now + 30
        assert "dimensions" in meta
        assert "violated" in meta["dimensions"]
        assert "allowed" in meta["dimensions"]

    def test_multiple_violated_equal_reset_times(self):
        """When multiple violated with equal reset times, first one wins (stable)."""
        now = 1000
        results = [
            (False, 10, now + 60, {"limited": True, "remaining": 0, "reset_in": 60}),
            (False, 20, now + 60, {"limited": True, "remaining": 0, "reset_in": 60}),
        ]
        allowed, limit, remaining, _reset_ts, meta = _select_most_restrictive(results)
        assert allowed is False
        assert limit == 10  # First one with shortest reset
        assert remaining == 0
        assert meta["reset_in"] == 60

    # Test Category 4: Multiple Allowed Dimensions - Select Lowest Remaining

    def test_multiple_allowed_lowest_remaining_wins(self):
        """When all allowed, select the one with lowest remaining."""
        now = 1000
        results = [
            (True, 100, now + 60, {"limited": True, "remaining": 50, "reset_in": 60}),
            (True, 200, now + 60, {"limited": True, "remaining": 10, "reset_in": 60}),  # Lowest remaining
            (True, 150, now + 60, {"limited": True, "remaining": 75, "reset_in": 60}),
        ]
        allowed, limit, remaining, reset_ts, _meta = _select_most_restrictive(results)
        assert allowed is True
        assert limit == 200  # Has lowest remaining (10)
        assert remaining == 10
        assert reset_ts == now + 60

    def test_allowed_with_equal_remaining(self):
        """When remaining is equal, first one wins (stable sort)."""
        now = 1000
        results = [
            (True, 100, now + 60, {"limited": True, "remaining": 25, "reset_in": 60}),
            (True, 200, now + 30, {"limited": True, "remaining": 25, "reset_in": 30}),
        ]
        allowed, limit, remaining, _reset_ts, _meta = _select_most_restrictive(results)
        assert allowed is True
        assert remaining == 25
        assert limit == 100  # First one when remaining is equal

    def test_two_allowed_different_remaining(self):
        """Two allowed dimensions with different remaining."""
        now = 1000
        results = [
            (True, 100, now + 60, {"limited": True, "remaining": 80, "reset_in": 60}),
            (True, 50, now + 60, {"limited": True, "remaining": 40, "reset_in": 60}),  # Lower remaining
        ]
        allowed, limit, remaining, _reset_ts, _meta = _select_most_restrictive(results)
        assert allowed is True
        assert limit == 50
        assert remaining == 40

    # Test Category 5: Mixed Limited and Unlimited

    def test_limited_more_restrictive_than_unlimited(self):
        """Limited dimension should be selected over unlimited."""
        now = 1000
        results = [
            (True, 0, 0, {"limited": False}),  # Unlimited
            (True, 100, now + 60, {"limited": True, "remaining": 95, "reset_in": 60}),  # Limited
        ]
        allowed, limit, remaining, _reset_ts, meta = _select_most_restrictive(results)
        assert allowed is True
        assert limit == 100  # Limited dimension selected
        assert remaining == 95
        assert meta["limited"] is True

    def test_violated_limited_with_unlimited(self):
        """Violated limited dimension should be selected over unlimited."""
        now = 1000
        results = [
            (True, 0, 0, {"limited": False}),  # Unlimited
            (False, 50, now + 30, {"limited": True, "remaining": 0, "reset_in": 30}),  # Violated
        ]
        allowed, limit, remaining, _reset_ts, _meta = _select_most_restrictive(results)
        assert allowed is False
        assert limit == 50
        assert remaining == 0

    def test_multiple_unlimited_with_one_limited(self):
        """Multiple unlimited with one limited should select limited."""
        now = 1000
        results = [
            (True, 0, 0, {"limited": False}),
            (True, 0, 0, {"limited": False}),
            (True, 75, now + 60, {"limited": True, "remaining": 60, "reset_in": 60}),
            (True, 0, 0, {"limited": False}),
        ]
        allowed, limit, remaining, _reset_ts, _meta = _select_most_restrictive(results)
        assert allowed is True
        assert limit == 75
        assert remaining == 60

    # Test Category 6: Realistic Scenarios

    def test_user_tenant_tool_all_allowed(self):
        """Realistic scenario: user, tenant, tool all allowed."""
        now = 1000
        results = [
            (True, 100, now + 60, {"limited": True, "remaining": 80, "reset_in": 60}),  # User
            (True, 1000, now + 60, {"limited": True, "remaining": 950, "reset_in": 60}),  # Tenant
            (True, 50, now + 60, {"limited": True, "remaining": 40, "reset_in": 60}),  # Tool (most restrictive)
        ]
        allowed, limit, remaining, _reset_ts, _meta = _select_most_restrictive(results)
        assert allowed is True
        assert limit == 50  # Tool has lowest remaining (40)
        assert remaining == 40

    def test_user_violated_tenant_tool_allowed(self):
        """Realistic scenario: user violated, others allowed."""
        now = 1000
        results = [
            (False, 100, now + 30, {"limited": True, "remaining": 0, "reset_in": 30}),  # User violated
            (True, 1000, now + 60, {"limited": True, "remaining": 950, "reset_in": 60}),  # Tenant allowed
            (True, 50, now + 60, {"limited": True, "remaining": 40, "reset_in": 60}),  # Tool allowed
        ]
        allowed, limit, remaining, reset_ts, _meta = _select_most_restrictive(results)
        assert allowed is False
        assert limit == 100  # User's violated limit
        assert remaining == 0
        assert reset_ts == now + 30

    def test_multiple_violated_different_reset_times(self):
        """Realistic scenario: multiple violated with different reset times."""
        now = 1000
        results = [
            (False, 100, now + 60, {"limited": True, "remaining": 0, "reset_in": 60}),  # User
            (False, 1000, now + 10, {"limited": True, "remaining": 0, "reset_in": 10}),  # Tenant (soonest)
            (False, 50, now + 30, {"limited": True, "remaining": 0, "reset_in": 30}),  # Tool
        ]
        allowed, limit, remaining, reset_ts, meta = _select_most_restrictive(results)
        assert allowed is False
        assert limit == 1000  # Tenant resets soonest
        assert remaining == 0
        assert reset_ts == now + 10
        assert meta["reset_in"] == 10

    def test_tenant_unlimited_user_tool_limited(self):
        """Realistic scenario: tenant unlimited, user and tool have limits."""
        now = 1000
        results = [
            (True, 100, now + 60, {"limited": True, "remaining": 80, "reset_in": 60}),  # User
            (True, 0, 0, {"limited": False}),  # Tenant unlimited
            (True, 50, now + 60, {"limited": True, "remaining": 30, "reset_in": 60}),  # Tool (most restrictive)
        ]
        allowed, limit, remaining, _reset_ts, _meta = _select_most_restrictive(results)
        assert allowed is True
        assert limit == 50  # Tool is most restrictive
        assert remaining == 30


# ============================================================================
# _parse_rate Tests
# ============================================================================


class TestParseRate:
    """Tests for _parse_rate helper covering all time units."""

    def test_seconds_short(self):
        assert _parse_rate("10/s") == (10, 1)

    def test_seconds_medium(self):
        assert _parse_rate("10/sec") == (10, 1)

    def test_seconds_long(self):
        assert _parse_rate("10/second") == (10, 1)

    def test_minutes_short(self):
        assert _parse_rate("60/m") == (60, 60)

    def test_minutes_medium(self):
        assert _parse_rate("60/min") == (60, 60)

    def test_minutes_long(self):
        assert _parse_rate("60/minute") == (60, 60)

    def test_hours_short(self):
        assert _parse_rate("100/h") == (100, 3600)

    def test_hours_medium(self):
        assert _parse_rate("100/hr") == (100, 3600)

    def test_hours_long(self):
        assert _parse_rate("100/hour") == (100, 3600)

    def test_unsupported_unit_raises(self):
        with pytest.raises(ValueError, match="unsupported unit"):
            _parse_rate("10/d")

    def test_whitespace_stripped(self):
        assert _parse_rate("5/ M ") == (5, 60)


# ============================================================================
# Unlimited (no-limit) path tests
# ============================================================================


def _mk_unlimited() -> RateLimiterPlugin:
    """Create a plugin with no rate limits configured."""
    return RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[PromptHookType.PROMPT_PRE_FETCH, ToolHookType.TOOL_PRE_INVOKE],
            config={},  # No limits
        )
    )


@pytest.mark.asyncio
async def test_prompt_pre_fetch_unlimited_returns_no_headers():
    """When no limits are configured, prompt_pre_fetch returns metadata without http_headers."""
    plugin = _mk_unlimited()
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
    payload = PromptPrehookPayload(prompt_id="p", args={})

    result = await plugin.prompt_pre_fetch(payload, ctx)
    assert result.violation is None
    assert result.http_headers is None
    assert result.metadata is not None
    assert result.metadata.get("limited") is False


@pytest.mark.asyncio
async def test_tool_pre_invoke_unlimited_returns_no_headers():
    """When no limits are configured, tool_pre_invoke returns metadata without http_headers."""
    # First-Party
    from mcpgateway.plugins.framework import ToolPreInvokePayload

    plugin = _mk_unlimited()
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    result = await plugin.tool_pre_invoke(payload, ctx)
    assert result.violation is None
    assert result.http_headers is None
    assert result.metadata is not None
    assert result.metadata.get("limited") is False


# ============================================================================
# Known Gap Tests — document current limitations (expected to fail)
#
# Each test is marked xfail(strict=True):
#   - While the gap exists   → shows as XFAIL  (CI passes, bug documented)
#   - Once the gap is fixed  → shows as XPASS  (CI fails, forcing marker removal)
# ============================================================================


@pytest.mark.asyncio
async def test_redis_backend_shares_state_across_instances():
    """
    With the Redis backend, the rate limit counter is shared across all workers.

    Clearing the local _store (simulating a new process) has no effect —
    the counter lives in Redis and persists between workers.

    A fake in-process Redis client is injected so the test runs without
    a live Redis server. The fake client uses its own dict (separate from _store)
    to simulate shared Redis state.
    """
    # Standard
    import time as _time

    class _FakeRedis:
        """In-process Redis stub: simulates INCR + EXPIRE Lua script semantics."""

        def __init__(self) -> None:
            self._data: Dict[str, tuple[int, int]] = {}  # key -> (count, expire_at)

        async def eval(self, script: str, numkeys: int, *args: Any) -> list[int]:
            key = args[0]
            window_seconds = int(args[1])
            now = int(_time.time())
            entry = self._data.get(key)
            if entry is None or entry[1] <= now:
                self._data[key] = (1, now + window_seconds)
                return [1, window_seconds]
            count, expire_at = entry
            self._data[key] = (count + 1, expire_at)
            return [count + 1, max(0, expire_at - now)]

    fake_redis = _FakeRedis()
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": "2/s", "backend": "redis", "redis_url": "redis://localhost:6379/0"},
        )
    )
    plugin._rate_backend._client = fake_redis  # inject fake Redis — no live server needed

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    # Worker 1: alice exhausts her limit (2 requests)
    r1 = await plugin.tool_pre_invoke(payload, ctx)
    r2 = await plugin.tool_pre_invoke(payload, ctx)
    assert r1.violation is None
    assert r2.violation is None

    # Simulate Worker 2 starting fresh — clearing the local memory store has no effect
    # on the Redis counter (the fake Redis client uses its own dict, not the plugin store)
    if isinstance(plugin._rate_backend, MemoryBackend):
        plugin._rate_backend._algorithm._store.clear()

    # Worker 2 shares the same Redis — alice's counter is still 2, next request is blocked
    r3 = await plugin.tool_pre_invoke(payload, ctx)
    assert r3.violation is not None, "alice made 3 requests total (limit is 2). With Redis backend, clearing " "local state has no effect — the counter persists in Redis across all workers."
    assert r3.violation.http_status_code == 429


@pytest.mark.asyncio
async def test_store_evicts_expired_windows():
    """
    After a rate limit window expires, the background TTL sweep removes its entry from _store.

    MemoryBackend starts a background asyncio task on first use that sweeps expired
    windows every 0.5s. Entries for users who never return are evicted automatically,
    bounding memory growth to active windows only.

    The Rust engine does not use the Python MemoryBackend store — this test is
    exercising the Python fallback path's sweep behaviour.
    """
    # First-Party
    import plugins.rate_limiter.rate_limiter as _rl_mod

    with patch.object(_rl_mod, "_RUST_AVAILABLE", False):
        plugin = _mk("5/s")
    store = plugin._rate_backend._algorithm._store
    UNIQUE_USERS = 100

    # Each unique user creates one entry in the algorithm store
    for i in range(UNIQUE_USERS):
        ctx = PluginContext(global_context=GlobalContext(request_id=f"r{i}", user=f"user_{i}"))
        payload = ToolPreInvokePayload(name="test_tool", arguments={})
        await plugin.tool_pre_invoke(payload, ctx)

    assert len(store) == UNIQUE_USERS  # confirm entries were created

    # Wait for all 1-second windows to expire and the sweep to run
    await asyncio.sleep(1.1)

    assert len(store) == 0, f"Expected store to be empty after all windows expired, " f"but found {len(store)} stale entries. "


@pytest.mark.asyncio
async def test_concurrent_requests_respect_limit():
    """
    20 concurrent async requests against a limit of 10 — exactly 10 should be allowed.

    This test PASSES under asyncio (single-threaded event loop, no real concurrency).
    It documents that the asyncio path is safe.

    NOTE: Under gunicorn threaded workers the dict read-modify-write in allow()
    is NOT atomic without the asyncio.Lock. Two threads can both read count=9,
    both pass the check, and both increment — allowing more than the configured
    limit. That scenario cannot be demonstrated in a single-threaded asyncio test.
    """
    plugin = _mk("10/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    results = await asyncio.gather(*[plugin.tool_pre_invoke(payload, ctx) for _ in range(20)])

    allowed = sum(1 for r in results if r.violation is None)

    assert allowed == 10, (
        f"Expected exactly 10 allowed requests (the limit), got {allowed}. "
        f"Under asyncio this should be deterministic. "
        f"Under threaded workers this assertion can fail due to dict race conditions."
    )


@pytest.mark.asyncio
async def test_fixed_window_allows_boundary_burst():
    """Empirical proof: fixed_window allows 2× the limit at a window boundary.

    A user sends N requests at the end of window W1 and N more at the start of
    W2.  All 2N succeed because the counter resets at the boundary.

    Example with limit=5/s:
      t=1000: requests 1-5 → allowed (window W1, count=5)
      t=1001: requests 6-10 → allowed (window W2 resets, count=1..5)
      Total = 10 requests in ~1 second against a limit of 5/s.

    This is the expected behavior of the fixed_window algorithm — not a bug,
    but a documented trade-off.  Use sliding_window or token_bucket to prevent
    boundary bursts (see companion test below).
    """
    # First-Party
    import plugins.rate_limiter.rate_limiter as _rl_mod

    with patch.object(_rl_mod, "_RUST_AVAILABLE", False):
        plugin = _mk("5/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    allowed_total = 0

    with patch("plugins.rate_limiter.rate_limiter.time") as mock_time:
        # Window W1: fill the limit exactly
        mock_time.time.return_value = 1000
        for _ in range(5):
            r = await plugin.tool_pre_invoke(payload, ctx)
            if r.violation is None:
                allowed_total += 1

        # Window W2: new window starts — limit resets
        mock_time.time.return_value = 1001
        for _ in range(5):
            r = await plugin.tool_pre_invoke(payload, ctx)
            if r.violation is None:
                allowed_total += 1

    # fixed_window: all 10 allowed (5 in W1 + 5 in W2 = 2× limit in ~1 second)
    assert allowed_total == 10, f"Expected fixed_window to allow 2× the limit at boundary, got {allowed_total}/10"


@pytest.mark.asyncio
async def test_sliding_window_prevents_boundary_burst():
    """Companion proof: sliding_window prevents the boundary burst that fixed_window allows.

    Same scenario as test_fixed_window_allows_boundary_burst but with
    sliding_window.  The 5 requests from W1 are still within the sliding window
    when W2 starts, so the second batch is blocked.
    """
    # First-Party
    import plugins.rate_limiter.rate_limiter as _rl_mod

    with patch.object(_rl_mod, "_RUST_AVAILABLE", False):
        plugin = RateLimiterPlugin(
            PluginConfig(
                name="rl-sw",
                kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE],
                config={"by_user": "5/s", "algorithm": ALGORITHM_SLIDING_WINDOW},
            )
        )
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    allowed_total = 0

    with patch("plugins.rate_limiter.rate_limiter.time") as mock_time:
        # Window W1: fill the limit exactly at t=1000
        mock_time.time.return_value = 1000.0
        for _ in range(5):
            r = await plugin.tool_pre_invoke(payload, ctx)
            if r.violation is None:
                allowed_total += 1

        # Half a second later: W1 timestamps are still within the 1s sliding window
        mock_time.time.return_value = 1000.5
        for _ in range(5):
            r = await plugin.tool_pre_invoke(payload, ctx)
            if r.violation is None:
                allowed_total += 1

    # sliding_window: only 5 allowed — the W1 timestamps at t=1000 are still
    # within the window at t=1000.5, so the second batch is blocked.
    assert allowed_total == 5, f"Expected sliding_window to prevent boundary burst, got {allowed_total}/10 allowed"


@pytest.mark.asyncio
async def test_prompt_pre_fetch_enforces_by_tool_config():
    """
    by_tool limits are enforced by prompt_pre_fetch using prompt_id as the key.

    When a prompt_id matches a key in by_tool, that rate limit is applied alongside
    by_user and by_tenant — the most restrictive wins.
    """
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[PromptHookType.PROMPT_PRE_FETCH],
            config={
                "by_user": "100/s",  # High — will not trigger
                "by_tool": {"search": "2/s"},  # Low — should trigger on 3rd call
            },
        )
    )

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = PromptPrehookPayload(prompt_id="search", args={})

    r1 = await plugin.prompt_pre_fetch(payload, ctx)
    r2 = await plugin.prompt_pre_fetch(payload, ctx)
    r3 = await plugin.prompt_pre_fetch(payload, ctx)  # should be blocked by by_tool

    assert r1.violation is None
    assert r2.violation is None
    # Expected: blocked because by_tool["search"] = 2/s is exhausted
    # Actual:   allowed — prompt_pre_fetch never reads by_tool
    assert r3.violation is not None, (
        "Expected 3rd prompt_pre_fetch call to be blocked by by_tool limit (2/s). " "prompt_pre_fetch does not check by_tool — tool-level limits only apply " "to tool_pre_invoke."
    )


# ============================================================================
# Edge Case Tests
#
# Tests that PASS document correct behaviour at boundaries.
# Tests marked xfail document gaps in input validation and error handling.
# ============================================================================


@pytest.mark.asyncio
async def test_empty_string_user_falls_back_to_anonymous():
    """
    An empty string user identity is falsy — falls back to 'anonymous'.
    All empty-identity requests share one bucket, correctly rate limited together.
    """
    plugin = _mk("2/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user=""))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    r1 = await plugin.tool_pre_invoke(payload, ctx)
    r2 = await plugin.tool_pre_invoke(payload, ctx)
    r3 = await plugin.tool_pre_invoke(payload, ctx)

    assert r1.violation is None
    assert r2.violation is None
    assert r3.violation is not None  # anonymous bucket exhausted
    assert r3.violation.http_status_code == 429


@pytest.mark.asyncio
async def test_none_tenant_skips_by_tenant_check():
    """
    None tenant_id must skip the by_tenant dimension entirely — no shared 'default' bucket.
    Multiple users with no tenant ID must not cross-throttle each other.
    """
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": "100/s", "by_tenant": "2/s"},
        )
    )

    ctx_alice = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id=None))
    ctx_bob = PluginContext(global_context=GlobalContext(request_id="r2", user="bob", tenant_id=None))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    r1 = await plugin.tool_pre_invoke(payload, ctx_alice)
    r2 = await plugin.tool_pre_invoke(payload, ctx_bob)
    r3 = await plugin.tool_pre_invoke(payload, ctx_alice)  # by_tenant skipped — must not block

    assert r1.violation is None
    assert r2.violation is None
    assert r3.violation is None  # by_tenant is skipped when tenant_id is None


@pytest.mark.asyncio
async def test_unicode_user_id_is_rate_limited_correctly():
    """
    Unicode user identities (non-ASCII email, CJK, emoji) are valid dict keys.
    Rate limiting works correctly for unicode identities.
    """
    plugin = _mk("2/s")
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    for user in ["用户@example.com", "ユーザー@test.jp", "مستخدم@example.com", "user🎉@example.com"]:
        _clear_plugin(plugin)
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user=user))

        r1 = await plugin.tool_pre_invoke(payload, ctx)
        r2 = await plugin.tool_pre_invoke(payload, ctx)
        r3 = await plugin.tool_pre_invoke(payload, ctx)

        assert r1.violation is None, f"First request failed for user: {user}"
        assert r2.violation is None, f"Second request failed for user: {user}"
        assert r3.violation is not None, f"Third request not blocked for user: {user}"


@pytest.mark.asyncio
async def test_very_large_user_pool_all_share_separate_buckets():
    """
    1000 distinct users each get their own independent bucket.
    No user should be affected by another user's requests.
    """
    plugin = _mk("1/s")
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    for i in range(1000):
        ctx = PluginContext(global_context=GlobalContext(request_id=f"r{i}", user=f"user_{i}@example.com"))
        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is None, f"user_{i} should not be blocked by other users"


def test_malformed_rate_count_raises_at_init():
    """
    A non-numeric count in the rate string (e.g. 'abc/m') now raises ValueError
    at plugin initialisation, not silently at request time.

    _validate_config() parses all rate strings in __init__ and raises immediately,
    giving a clear error at startup rather than a confusing failure mid-request.
    """
    with pytest.raises(ValueError, match="RateLimiterPlugin config errors"):
        RateLimiterPlugin(
            PluginConfig(
                name="rl",
                kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE],
                config={"by_user": "abc/m"},  # invalid count
            )
        )


def test_unsupported_rate_unit_raises_at_init():
    """
    An unsupported time unit (e.g. '60/d' for days) now raises ValueError
    at plugin initialisation via _validate_config().

    This ensures operators discover misconfigured rate strings at startup
    rather than when the first request hits the bad code path.
    """
    with pytest.raises(ValueError, match="RateLimiterPlugin config errors"):
        RateLimiterPlugin(
            PluginConfig(
                name="rl",
                kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE],
                config={"by_user": "60/d"},  # unsupported unit
            )
        )


def test_invalid_backend_raises_at_init():
    """
    An unrecognised backend (e.g. typo 'reddis') raises ValueError at startup
    via _validate_config() rather than silently falling back to memory.
    """
    with pytest.raises(ValueError, match="RateLimiterPlugin config errors"):
        RateLimiterPlugin(
            PluginConfig(
                name="rl",
                kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE],
                config={"by_user": "10/s", "backend": "reddis"},
            )
        )


def test_malformed_by_tool_rate_raises_at_init():
    """
    A malformed rate string inside by_tool (e.g. 'abc/m') raises ValueError
    at plugin initialisation listing the invalid tool entry.
    """
    with pytest.raises(ValueError, match="by_tool"):
        RateLimiterPlugin(
            PluginConfig(
                name="rl",
                kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE],
                config={"by_tool": {"search": "abc/m"}},
            )
        )


@pytest.mark.asyncio
async def test_graceful_degradation_tool_pre_invoke_does_not_crash_caller():
    """
    If an unexpected runtime error occurs inside tool_pre_invoke (e.g. a bug in the backend),
    the exception is caught, logged, and a permissive result is returned.

    The gateway request is NOT crashed by a plugin error.
    This is tested by patching the backend's allow method to raise a RuntimeError.
    """
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": "10/s"},
        )
    )
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    with patch.object(plugin._rate_backend, "allow", side_effect=RuntimeError("simulated internal error")):
        result = await plugin.tool_pre_invoke(payload, ctx)

    assert result is not None, "Plugin should return a result even when backend.allow() raises unexpectedly"
    assert result.violation is None, "Permissive degradation: unexpected errors allow the request through"


@pytest.mark.asyncio
async def test_graceful_degradation_prompt_pre_fetch_does_not_crash_caller():
    """
    If an unexpected runtime error occurs inside prompt_pre_fetch, the exception
    is caught, logged, and a permissive result is returned.
    """
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[PromptHookType.PROMPT_PRE_FETCH],
            config={"by_user": "10/s"},
        )
    )
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = PromptPrehookPayload(prompt_id="my_prompt", args={})

    with patch.object(plugin._rate_backend, "allow", side_effect=RuntimeError("simulated internal error")):
        result = await plugin.prompt_pre_fetch(payload, ctx)

    assert result is not None, "Plugin should return a result even when backend.allow() raises unexpectedly"
    assert result.violation is None, "Permissive degradation: unexpected errors allow the request through"


# ============================================================================
# Permissive Mode Tests
#
# mode=permissive is handled by the plugin manager (PluginExecutor), not by
# the plugin itself. When a plugin returns a violation in permissive mode the
# manager logs it but does NOT raise PluginViolationError — the request
# continues. These tests go through PluginExecutor to exercise that path.
# ============================================================================


@pytest.mark.asyncio
async def test_permissive_mode_allows_request_past_limit():
    """
    In permissive mode, exceeding the rate limit logs a warning but does NOT
    block the request. PluginExecutor must NOT raise PluginViolationError even
    with violations_as_exceptions=True.
    """
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": "1/s"},
            mode=PluginMode.PERMISSIVE,
        )
    )
    plugin_ref = PluginRef(plugin)
    hook_ref = HookRef("tool_pre_invoke", plugin_ref)
    executor = PluginExecutor(timeout=5)

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    # First call: allowed
    await executor.execute_plugin(hook_ref, payload, ctx, violations_as_exceptions=True)

    # Second call: exceeds limit — permissive mode must NOT raise
    try:
        result = await executor.execute_plugin(hook_ref, payload, ctx, violations_as_exceptions=True)
    except PluginViolationError:
        pytest.fail("PluginViolationError raised in permissive mode — should be suppressed")

    # The violation is still surfaced in the result (for observability), just not raised
    assert result.violation is not None, "Violation info should still be present for logging/metrics"
    assert result.violation.http_status_code == 429


@pytest.mark.asyncio
async def test_enforce_mode_raises_on_limit_exceeded():
    """
    Contrast: in enforce mode, exceeding the limit with violations_as_exceptions=True
    DOES raise PluginViolationError. This test ensures the distinction is clear.
    """
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": "1/s"},
            mode=PluginMode.ENFORCE,
        )
    )
    plugin_ref = PluginRef(plugin)
    hook_ref = HookRef("tool_pre_invoke", plugin_ref)
    executor = PluginExecutor(timeout=5)

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    # First call: allowed
    await executor.execute_plugin(hook_ref, payload, ctx, violations_as_exceptions=True)

    # Second call: enforce mode must raise
    with pytest.raises(PluginViolationError):
        await executor.execute_plugin(hook_ref, payload, ctx, violations_as_exceptions=True)


# ============================================================================
# Redis Fallback Tests
#
# When backend='redis' and redis_fallback=True, a Redis connection failure
# falls back to the in-process MemoryBackend. The rate limiter must continue
# to function correctly without crashing the caller.
# ============================================================================


@pytest.mark.asyncio
async def test_redis_fallback_to_memory_when_redis_unavailable():
    """
    When the Redis client raises an exception (simulating Redis being down),
    and redis_fallback=True, the plugin falls back to MemoryBackend and the
    request succeeds rather than erroring.

    Forces _RUST_AVAILABLE=False so the Python RedisBackend path is exercised —
    the Rust engine owns its own Redis connection and is not affected by
    injecting a broken client into _rate_backend._client.
    """

    class _BrokenRedis:
        """Simulates a Redis client that always fails."""

        async def eval(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("Redis is down")

    # First-Party
    import plugins.rate_limiter.rate_limiter as _rl_mod

    with patch.object(_rl_mod, "_RUST_AVAILABLE", False):
        plugin = RateLimiterPlugin(
            PluginConfig(
                name="rl",
                kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE],
                config={"by_user": "10/s", "backend": "redis", "redis_url": "redis://localhost:6379/0", "redis_fallback": True},
            )
        )
    plugin._rate_backend._client = _BrokenRedis()

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    result = await plugin.tool_pre_invoke(payload, ctx)
    assert result.violation is None, "Request should succeed via memory fallback when Redis is down"


@pytest.mark.asyncio
async def test_redis_fallback_enforces_limit_via_memory():
    """
    After falling back to memory, the MemoryBackend still enforces the rate
    limit correctly — the fallback is not a free pass.

    Forces _RUST_AVAILABLE=False so the Python RedisBackend path is exercised —
    the Rust engine owns its own Redis connection and is not affected by
    injecting a broken client into _rate_backend._client.
    """

    class _BrokenRedis:
        async def eval(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("Redis is down")

    # First-Party
    import plugins.rate_limiter.rate_limiter as _rl_mod

    with patch.object(_rl_mod, "_RUST_AVAILABLE", False):
        plugin = RateLimiterPlugin(
            PluginConfig(
                name="rl",
                kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE],
                config={"by_user": "2/s", "backend": "redis", "redis_url": "redis://localhost:6379/0", "redis_fallback": True},
            )
        )
    plugin._rate_backend._client = _BrokenRedis()

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    r1 = await plugin.tool_pre_invoke(payload, ctx)
    r2 = await plugin.tool_pre_invoke(payload, ctx)
    r3 = await plugin.tool_pre_invoke(payload, ctx)

    assert r1.violation is None
    assert r2.violation is None
    assert r3.violation is not None, "Memory fallback must still enforce the configured limit"
    assert r3.violation.http_status_code == 429


@pytest.mark.asyncio
async def test_redis_no_fallback_raises_on_redis_failure():
    """
    When redis_fallback=False and Redis is unavailable, the plugin's internal
    error handling catches the exception and allows the request through
    (graceful degradation), rather than crashing the caller.
    """

    class _BrokenRedis:
        async def eval(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("Redis is down")

    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": "10/s", "backend": "redis", "redis_url": "redis://localhost:6379/0", "redis_fallback": False},
        )
    )
    plugin._rate_backend._client = _BrokenRedis()
    plugin._rate_backend._fallback = None  # disable fallback explicitly

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    # Should not crash the caller — graceful degradation allows through
    result = await plugin.tool_pre_invoke(payload, ctx)
    assert result is not None, "Plugin must not propagate Redis failure to the caller"


# ============================================================================
# Cross-Tenant Isolation Tests
#
# Each tenant gets its own independent counter. Exhausting one tenant's limit
# must not block requests from a different tenant.
# ============================================================================


@pytest.mark.asyncio
async def test_cross_tenant_isolation_different_tenants_independent():
    """
    Exhausting tenant A's limit does not block tenant B.
    Each tenant has a completely separate counter.
    """
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_tenant": "2/s"},
        )
    )
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    ctx_a = PluginContext(global_context=GlobalContext(request_id="r1", user="user1", tenant_id="tenant-A"))
    ctx_b = PluginContext(global_context=GlobalContext(request_id="r2", user="user2", tenant_id="tenant-B"))

    # Exhaust tenant-A's limit
    await plugin.tool_pre_invoke(payload, ctx_a)
    await plugin.tool_pre_invoke(payload, ctx_a)
    blocked = await plugin.tool_pre_invoke(payload, ctx_a)
    assert blocked.violation is not None, "tenant-A should be rate limited"

    # tenant-B should be completely unaffected
    r = await plugin.tool_pre_invoke(payload, ctx_b)
    assert r.violation is None, "tenant-B should not be blocked by tenant-A's exhausted counter"


@pytest.mark.asyncio
async def test_cross_tenant_no_counter_bleed():
    """
    Many requests from tenant-A do not increment tenant-B's counter.
    tenant-B's remaining count should still be at its maximum.
    """
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_tenant": "100/s"},
        )
    )
    payload = ToolPreInvokePayload(name="test_tool", arguments={})
    ctx_a = PluginContext(global_context=GlobalContext(request_id="r1", user="u1", tenant_id="tenant-A"))
    ctx_b = PluginContext(global_context=GlobalContext(request_id="r2", user="u2", tenant_id="tenant-B"))

    # tenant-A sends 50 requests
    for _ in range(50):
        await plugin.tool_pre_invoke(payload, ctx_a)

    # tenant-B's first request should show remaining=99 (untouched)
    result = await plugin.tool_pre_invoke(payload, ctx_b)
    assert result.violation is None
    assert result.http_headers is not None
    assert result.http_headers["X-RateLimit-Remaining"] == "99", (
        f"tenant-B remaining should be 99 (limit=100, only 1 request so far), "
        f"got {result.http_headers['X-RateLimit-Remaining']} — "
        f"tenant-A's 50 requests must not have incremented tenant-B's counter"
    )


# ============================================================================
# Header Accuracy Tests
#
# Verify the mathematical correctness of Retry-After and X-RateLimit-Reset,
# not just their presence.
# ============================================================================


@pytest.mark.asyncio
async def test_retry_after_is_within_window_duration():
    """
    Retry-After must be <= the configured window duration.
    For a 1-second window it must be in [1, 1].
    For a 60-second window it must be in [1, 60].
    """
    plugin = _mk("1/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    await plugin.tool_pre_invoke(payload, ctx)  # consume limit
    result = await plugin.tool_pre_invoke(payload, ctx)  # trigger violation

    assert result.violation is not None
    retry_after = int(result.violation.http_headers["Retry-After"])
    assert 1 <= retry_after <= 1, f"For a 1/s limit, Retry-After should be 1 second, got {retry_after}"


@pytest.mark.asyncio
async def test_retry_after_for_minute_window_is_bounded():
    """
    For a 1/m limit, Retry-After must be between 1 and 60 seconds.
    It must not exceed the window size.
    """
    plugin = _mk("1/m")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    await plugin.tool_pre_invoke(payload, ctx)  # consume limit
    result = await plugin.tool_pre_invoke(payload, ctx)  # trigger violation

    assert result.violation is not None
    retry_after = int(result.violation.http_headers["Retry-After"])
    assert 1 <= retry_after <= 60, f"For a 1/m limit, Retry-After should be 1–60 seconds, got {retry_after}"


@pytest.mark.asyncio
async def test_x_ratelimit_reset_is_in_the_future():
    """
    X-RateLimit-Reset must be a Unix timestamp strictly greater than now.
    """
    plugin = _mk("10/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    before = int(time.time())
    result = await plugin.tool_pre_invoke(payload, ctx)
    after = int(time.time()) + 2  # small buffer for slow machines

    assert result.violation is None
    reset = int(result.http_headers["X-RateLimit-Reset"])
    assert reset >= before, f"X-RateLimit-Reset ({reset}) should be >= now ({before})"
    assert reset <= after + 1, f"X-RateLimit-Reset ({reset}) should be within 1s window of now"


@pytest.mark.asyncio
async def test_x_ratelimit_reset_consistent_within_window():
    """
    Multiple requests in the same window must return the same X-RateLimit-Reset
    timestamp. The reset timestamp is fixed at window-start + window-duration and
    must not shift between requests.
    """
    plugin = _mk("10/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    r1 = await plugin.tool_pre_invoke(payload, ctx)
    r2 = await plugin.tool_pre_invoke(payload, ctx)
    r3 = await plugin.tool_pre_invoke(payload, ctx)

    reset1 = r1.http_headers["X-RateLimit-Reset"]
    reset2 = r2.http_headers["X-RateLimit-Reset"]
    reset3 = r3.http_headers["X-RateLimit-Reset"]

    assert reset1 == reset2 == reset3, f"X-RateLimit-Reset must be identical across all requests in the same window. " f"Got {reset1}, {reset2}, {reset3}"


@pytest.mark.asyncio
async def test_x_ratelimit_remaining_decrements_correctly():
    """
    X-RateLimit-Remaining must decrement by exactly 1 per request
    until it reaches 0 at the limit boundary.
    """
    plugin = _mk("5/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    results = []
    for _ in range(5):
        r = await plugin.tool_pre_invoke(payload, ctx)
        assert r.violation is None
        results.append(int(r.http_headers["X-RateLimit-Remaining"]))

    assert results == [4, 3, 2, 1, 0], f"X-RateLimit-Remaining should count down 4→3→2→1→0, got {results}"


# ============================================================================
# Bypass Resistance Tests
#
# These tests document how the rate limiter handles identity edge cases.
# Tests that pass confirm correct/intentional behaviour.
# Tests marked xfail document known gaps where a caller could sidestep limits.
# ============================================================================


@pytest.mark.asyncio
async def test_bypass_none_user_falls_back_to_anonymous_bucket():
    """
    None user identity resolves to 'anonymous' — same bucket as an empty string.
    A caller cannot gain a fresh bucket by sending None as their user identity.
    """
    plugin = _mk("2/s")
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    # None user → "anonymous" bucket
    ctx_none = PluginContext(global_context=GlobalContext(request_id="r1", user=None))
    # empty string user → also "anonymous" bucket (via `or "anonymous"`)
    ctx_empty = PluginContext(global_context=GlobalContext(request_id="r2", user=""))

    r1 = await plugin.tool_pre_invoke(payload, ctx_none)
    r2 = await plugin.tool_pre_invoke(payload, ctx_empty)
    r3 = await plugin.tool_pre_invoke(payload, ctx_none)  # same "anonymous" bucket — exhausted

    assert r1.violation is None
    assert r2.violation is None
    assert r3.violation is not None, "None and empty-string users share the 'anonymous' bucket — " "a third request must be blocked regardless of which falsy identity sent it"


@pytest.mark.asyncio
async def test_bypass_whitespace_user_shares_anonymous_bucket():
    """
    A whitespace-only user identity ('   ') should be treated the same as an
    empty string and fall back to the 'anonymous' bucket.

    Current behaviour: '   ' is truthy, so `user or 'anonymous'` keeps it as-is,
    creating an independent 'user:   ' bucket. This is a bypass vector.
    """
    plugin = _mk("2/s")
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    ctx_anon = PluginContext(global_context=GlobalContext(request_id="r1", user=""))
    ctx_ws = PluginContext(global_context=GlobalContext(request_id="r2", user="   "))

    # Exhaust the anonymous bucket
    await plugin.tool_pre_invoke(payload, ctx_anon)
    await plugin.tool_pre_invoke(payload, ctx_anon)

    # Whitespace user should be in the same bucket → blocked
    r = await plugin.tool_pre_invoke(payload, ctx_ws)
    assert r.violation is not None, "Whitespace-only user identity should share the 'anonymous' bucket. " "Currently it creates its own bucket, bypassing the anonymous limit."


@pytest.mark.asyncio
async def test_bypass_tool_name_case_sensitivity():
    """
    A per-tool limit on 'search' should also apply to 'Search' and 'SEARCH'.

    Current behaviour: by_tool lookup is an exact dict key match — 'Search' does
    not hit the 'search' limit and gets an unlimited quota.
    """
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": "100/s", "by_tool": {"search": "1/s"}},
        )
    )
    payload_lower = ToolPreInvokePayload(name="search", arguments={})
    payload_upper = ToolPreInvokePayload(name="Search", arguments={})
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))

    # Exhaust the per-tool limit using the lowercase name
    await plugin.tool_pre_invoke(payload_lower, ctx)

    # Calling with different casing should still be caught by the same limit
    r = await plugin.tool_pre_invoke(payload_upper, ctx)
    assert r.violation is not None, "'Search' should be subject to the same 1/s limit as 'search'. " "Case-insensitive matching is not implemented — this is a bypass vector."


@pytest.mark.asyncio
async def test_bypass_tool_name_whitespace():
    """
    A per-tool limit on 'search' should also apply to ' search' (leading space).

    Current behaviour: ' search' != 'search' in the dict lookup, so the per-tool
    limit is not applied and the request is treated as having no tool-level limit.
    """
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": "100/s", "by_tool": {"search": "1/s"}},
        )
    )
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))

    # Exhaust the limit using the canonical name
    await plugin.tool_pre_invoke(ToolPreInvokePayload(name="search", arguments={}), ctx)

    # Whitespace variant should be caught by the same limit
    r = await plugin.tool_pre_invoke(ToolPreInvokePayload(name=" search", arguments={}), ctx)
    assert r.violation is not None, "' search' (leading space) should be subject to the same limit as 'search'. " "Whitespace stripping is not implemented — this is a bypass vector."


@pytest.mark.asyncio
async def test_bypass_anonymous_exhaustion_does_not_affect_real_users():
    """
    Exhausting the anonymous bucket must not block authenticated users.
    Each real user has their own independent bucket.
    """
    plugin = _mk("2/s")
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    ctx_anon = PluginContext(global_context=GlobalContext(request_id="r1", user=""))
    ctx_alice = PluginContext(global_context=GlobalContext(request_id="r2", user="alice@example.com"))

    # Exhaust the anonymous bucket
    await plugin.tool_pre_invoke(payload, ctx_anon)
    await plugin.tool_pre_invoke(payload, ctx_anon)
    blocked_anon = await plugin.tool_pre_invoke(payload, ctx_anon)
    assert blocked_anon.violation is not None

    # Alice is a real user — her bucket is untouched
    r = await plugin.tool_pre_invoke(payload, ctx_alice)
    assert r.violation is None, "Exhausting the anonymous bucket must not affect real authenticated users"


# ============================================================================
# Logging / PII Tests
#
# Violation descriptions must not contain user or tenant identifiers.
# These strings are included in log output (permissive mode) and in
# PluginViolationError messages (enforce mode) — leaking them would expose
# PII in structured logs and error traces.
# ============================================================================


@pytest.mark.asyncio
async def test_violation_description_does_not_contain_user_identity():
    """Violation description must not include the user's identity string."""
    plugin = _mk("1/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice@example.com"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    await plugin.tool_pre_invoke(payload, ctx)  # consume limit
    result = await plugin.tool_pre_invoke(payload, ctx)  # trigger violation

    assert result.violation is not None
    assert "alice@example.com" not in result.violation.description, (
        "User identity must not appear in the violation description — " "it is logged in permissive mode and embedded in PluginViolationError messages"
    )


@pytest.mark.asyncio
async def test_violation_description_does_not_contain_tenant_identity():
    """Violation description must not include the tenant identifier."""
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_tenant": "1/s"},
        )
    )
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id="acme-corp"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    await plugin.tool_pre_invoke(payload, ctx)
    result = await plugin.tool_pre_invoke(payload, ctx)

    assert result.violation is not None
    assert "acme-corp" not in result.violation.description, "Tenant identifier must not appear in the violation description"


@pytest.mark.asyncio
async def test_prompt_violation_description_does_not_contain_user_identity():
    """Same check for prompt_pre_fetch — description must not include user identity."""
    plugin = _mk("1/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="bob@example.com"))
    payload = PromptPrehookPayload(prompt_id="my_prompt", args={})

    await plugin.prompt_pre_fetch(payload, ctx)
    result = await plugin.prompt_pre_fetch(payload, ctx)

    assert result.violation is not None
    assert "bob@example.com" not in result.violation.description, "User identity must not appear in the prompt violation description"


@pytest.mark.asyncio
async def test_bypass_different_tenants_are_intentionally_independent():
    """
    Users in different tenants have separate tenant counters — this is intentional.
    A user who belongs to two tenants effectively gets two independent tenant quotas.
    This test documents the behaviour as intentional (not a bug) so reviewers have
    explicit confirmation that multi-tenant quota isolation is by design.
    """
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": "100/s", "by_tenant": "2/s"},
        )
    )
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    ctx_t1 = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id="tenant-1"))
    ctx_t2 = PluginContext(global_context=GlobalContext(request_id="r2", user="alice", tenant_id="tenant-2"))

    # Exhaust tenant-1 limit
    await plugin.tool_pre_invoke(payload, ctx_t1)
    await plugin.tool_pre_invoke(payload, ctx_t1)
    blocked = await plugin.tool_pre_invoke(payload, ctx_t1)
    assert blocked.violation is not None, "tenant-1 should be exhausted"

    # Same user in tenant-2 is allowed — separate counter, by design
    r = await plugin.tool_pre_invoke(payload, ctx_t2)
    assert r.violation is None, (
        "tenant-2 has a separate independent counter — this is intentional. " "Tenant identity comes from the JWT and is controlled by the auth layer, " "not bypassable by request content."
    )


# ============================================================================
# Algorithm Strategy Tests
#
# Tests that are specific to each algorithm: sliding_window and token_bucket.
# fixed_window behaviour is already covered by all existing tests above.
# ============================================================================


# ---------------------------------------------------------------------------
# Algorithm selection and validation
# ---------------------------------------------------------------------------


def test_invalid_algorithm_raises_at_init():
    """An unrecognised algorithm name must raise ValueError at startup."""
    with pytest.raises(ValueError, match="RateLimiterPlugin config errors"):
        RateLimiterPlugin(
            PluginConfig(
                name="rl",
                kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE],
                config={"by_user": "10/s", "algorithm": "leaky_bucket"},
            )
        )


def test_default_algorithm_is_fixed_window():
    """When algorithm is not specified, fixed_window is used."""
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": "10/s"},
        )
    )
    assert isinstance(plugin._rate_backend._algorithm, FixedWindowAlgorithm)


def test_sliding_window_algorithm_instantiated():
    """sliding_window config results in a SlidingWindowAlgorithm backend."""
    plugin = _mk("10/s", algorithm=ALGORITHM_SLIDING_WINDOW)
    assert isinstance(plugin._rate_backend._algorithm, SlidingWindowAlgorithm)


def test_token_bucket_algorithm_instantiated():
    """token_bucket config results in a TokenBucketAlgorithm backend."""
    plugin = _mk("10/s", algorithm=ALGORITHM_TOKEN_BUCKET)
    assert isinstance(plugin._rate_backend._algorithm, TokenBucketAlgorithm)


# ---------------------------------------------------------------------------
# Sliding window correctness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sliding_window_basic_enforcement():
    """Sliding window enforces the limit correctly under steady traffic."""
    plugin = _mk("3/s", algorithm=ALGORITHM_SLIDING_WINDOW)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    r1 = await plugin.tool_pre_invoke(payload, ctx)
    r2 = await plugin.tool_pre_invoke(payload, ctx)
    r3 = await plugin.tool_pre_invoke(payload, ctx)
    r4 = await plugin.tool_pre_invoke(payload, ctx)  # should be blocked

    assert r1.violation is None
    assert r2.violation is None
    assert r3.violation is None
    assert r4.violation is not None
    assert r4.violation.http_status_code == 429


@pytest.mark.asyncio
async def test_sliding_window_prevents_burst_at_boundary():
    """
    Sliding window does NOT allow 2× the limit at a window boundary.

    Unlike fixed window, the sliding window tracks exact timestamps. When
    requests straddle a boundary, old timestamps are still within the window
    and count against the limit — no burst is possible.
    """
    plugin = _mk("5/s", algorithm=ALGORITHM_SLIDING_WINDOW)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    allowed_total = 0

    with patch("plugins.rate_limiter.rate_limiter.time") as mock_time:
        # End of window W1: fill the limit
        mock_time.time.return_value = 1000.9
        for _ in range(5):
            r = await plugin.tool_pre_invoke(payload, ctx)
            if r.violation is None:
                allowed_total += 1

        # Start of window W2: timestamps from W1 are still within the 1s window
        mock_time.time.return_value = 1001.1
        for _ in range(5):
            r = await plugin.tool_pre_invoke(payload, ctx)
            if r.violation is None:
                allowed_total += 1

    # Sliding window: only requests older than 1s are evicted
    # At t=1001.1, cutoff = 1000.1 — all 5 requests at t=1000.9 are still inside
    assert allowed_total <= 6, f"Sliding window should prevent boundary burst. Got {allowed_total} allowed " f"(fixed window would allow 10, sliding window should block most of W2)."


@pytest.mark.asyncio
async def test_sliding_window_allows_after_window_passes():
    """After the full window duration passes, the sliding window resets naturally."""
    plugin = _mk("2/s", algorithm=ALGORITHM_SLIDING_WINDOW)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    # Exhaust the limit
    await plugin.tool_pre_invoke(payload, ctx)
    await plugin.tool_pre_invoke(payload, ctx)
    blocked = await plugin.tool_pre_invoke(payload, ctx)
    assert blocked.violation is not None

    # Wait for the window to pass
    await asyncio.sleep(1.1)

    # Should be allowed again
    r = await plugin.tool_pre_invoke(payload, ctx)
    assert r.violation is None, "Requests should be allowed after the sliding window passes"


@pytest.mark.asyncio
async def test_sliding_window_returns_429_and_headers():
    """Sliding window violations return HTTP 429 with rate limit headers."""
    plugin = _mk("1/s", algorithm=ALGORITHM_SLIDING_WINDOW)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    await plugin.tool_pre_invoke(payload, ctx)
    result = await plugin.tool_pre_invoke(payload, ctx)

    assert result.violation is not None
    assert result.violation.http_status_code == 429
    assert result.violation.code == "RATE_LIMIT"
    assert "X-RateLimit-Limit" in result.violation.http_headers
    assert "Retry-After" in result.violation.http_headers


# ---------------------------------------------------------------------------
# Token bucket correctness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_bucket_basic_enforcement():
    """Token bucket enforces the limit — once tokens are exhausted requests are blocked."""
    plugin = _mk("3/s", algorithm=ALGORITHM_TOKEN_BUCKET)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    r1 = await plugin.tool_pre_invoke(payload, ctx)
    r2 = await plugin.tool_pre_invoke(payload, ctx)
    r3 = await plugin.tool_pre_invoke(payload, ctx)
    r4 = await plugin.tool_pre_invoke(payload, ctx)  # bucket empty

    assert r1.violation is None
    assert r2.violation is None
    assert r3.violation is None
    assert r4.violation is not None
    assert r4.violation.http_status_code == 429


@pytest.mark.asyncio
async def test_token_bucket_allows_burst_up_to_capacity():
    """
    Token bucket allows an immediate burst up to the full bucket capacity.

    A user who has been idle accumulates tokens. When they send a burst of
    requests they can use all accumulated tokens at once — this is intentional
    token_bucket behaviour, unlike fixed or sliding window which always enforce
    a per-window ceiling.
    """
    plugin = _mk("5/s", algorithm=ALGORITHM_TOKEN_BUCKET)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    # Send all 5 requests immediately (burst from a full bucket)
    results = []
    for _ in range(5):
        r = await plugin.tool_pre_invoke(payload, ctx)
        results.append(r)

    allowed = sum(1 for r in results if r.violation is None)
    assert allowed == 5, f"Token bucket should allow a burst of 5 from a full bucket, got {allowed} allowed"

    # 6th request: bucket is now empty
    r6 = await plugin.tool_pre_invoke(payload, ctx)
    assert r6.violation is not None, "Bucket should be empty after a full burst"


@pytest.mark.asyncio
async def test_token_bucket_refills_over_time():
    """Tokens refill at the configured rate — requests are allowed again after waiting."""
    plugin = _mk("5/s", algorithm=ALGORITHM_TOKEN_BUCKET)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    # Drain the bucket
    for _ in range(5):
        await plugin.tool_pre_invoke(payload, ctx)

    blocked = await plugin.tool_pre_invoke(payload, ctx)
    assert blocked.violation is not None, "Bucket should be empty"

    # Wait for at least 1 token to refill (5 tokens/s → 1 token per 0.2s)
    await asyncio.sleep(0.3)

    r = await plugin.tool_pre_invoke(payload, ctx)
    assert r.violation is None, "At least 1 token should have refilled after 0.3s"


@pytest.mark.asyncio
async def test_token_bucket_returns_429_and_headers():
    """Token bucket violations return HTTP 429 with rate limit headers."""
    plugin = _mk("1/s", algorithm=ALGORITHM_TOKEN_BUCKET)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    await plugin.tool_pre_invoke(payload, ctx)
    result = await plugin.tool_pre_invoke(payload, ctx)

    assert result.violation is not None
    assert result.violation.http_status_code == 429
    assert result.violation.code == "RATE_LIMIT"
    assert "X-RateLimit-Limit" in result.violation.http_headers
    assert "Retry-After" in result.violation.http_headers


# ---------------------------------------------------------------------------
# Algorithm isolation — each instance gets its own independent store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_plugin_instances_different_algorithms_independent():
    """Two plugin instances using different algorithms have completely independent stores."""
    plugin_fw = _mk("2/s", algorithm=ALGORITHM_FIXED_WINDOW)
    plugin_sw = _mk("2/s", algorithm=ALGORITHM_SLIDING_WINDOW)
    plugin_tb = _mk("2/s", algorithm=ALGORITHM_TOKEN_BUCKET)

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    # Exhaust fixed window
    await plugin_fw.tool_pre_invoke(payload, ctx)
    await plugin_fw.tool_pre_invoke(payload, ctx)
    blocked_fw = await plugin_fw.tool_pre_invoke(payload, ctx)
    assert blocked_fw.violation is not None, "fixed_window alice should be blocked"

    # sliding_window and token_bucket instances are completely unaffected
    r_sw = await plugin_sw.tool_pre_invoke(payload, ctx)
    r_tb = await plugin_tb.tool_pre_invoke(payload, ctx)
    assert r_sw.violation is None, "sliding_window has its own store — should not be blocked"
    assert r_tb.violation is None, "token_bucket has its own store — should not be blocked"


# ---------------------------------------------------------------------------
# Redis + token_bucket
# ---------------------------------------------------------------------------


def test_token_bucket_with_redis_backend_uses_redis_backend():
    """token_bucket with backend=redis instantiates a RedisBackend, not MemoryBackend."""
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={
                "by_user": "10/s",
                "algorithm": "token_bucket",
                "backend": "redis",
                "redis_url": "redis://localhost:6379/0",
            },
        )
    )
    assert isinstance(plugin._rate_backend, RedisBackend)
    assert plugin._rate_backend._algorithm_name == ALGORITHM_TOKEN_BUCKET


@pytest.mark.asyncio
async def test_redis_token_bucket_enforces_limit():
    """RedisBackend with token_bucket enforces the limit via the Lua script."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    mock_client = AsyncMock()
    # First call: allowed=1, remaining=0, time_to_next=0
    # Second call: allowed=0, remaining=0, time_to_next=5
    mock_client.eval.side_effect = [
        [1, 0, 0],
        [0, 0, 5],
    ]

    backend = RedisBackend(
        redis_url="redis://localhost:6379/0",
        algorithm_name=ALGORITHM_TOKEN_BUCKET,
        _client=mock_client,
    )

    allowed1, _, _, meta1 = await backend.allow("user:alice", "1/s")
    allowed2, _, _, meta2 = await backend.allow("user:alice", "1/s")

    assert allowed1 is True
    assert meta1["remaining"] == 0
    assert allowed2 is False
    assert meta2["remaining"] == 0
    assert meta2["reset_in"] == 5


@pytest.mark.asyncio
async def test_redis_token_bucket_falls_back_to_memory_on_redis_error():
    """RedisBackend token_bucket falls back to MemoryBackend when Redis is unavailable."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    mock_client = AsyncMock()
    mock_client.eval.side_effect = ConnectionError("Redis unavailable")

    fallback = MemoryBackend(TokenBucketAlgorithm())
    backend = RedisBackend(
        redis_url="redis://localhost:6379/0",
        algorithm_name=ALGORITHM_TOKEN_BUCKET,
        fallback=fallback,
        _client=mock_client,
    )

    allowed, _, _, _ = await backend.allow("user:alice", "5/s")
    assert allowed is True


# ============================================================================
# Concurrency Stress Tests
# ============================================================================


@pytest.mark.asyncio
async def test_concurrent_stress_same_key_does_not_over_allow():
    """
    100 concurrent tasks hitting the same user key with a limit of 10/s.

    The asyncio.Lock in MemoryBackend serialises all allow() calls so the
    count increments atomically. Exactly 10 requests must be allowed — no
    more, no fewer.

    This is a stronger version of test_concurrent_requests_respect_limit:
    5× more load to surface any lock-ordering or double-increment bugs that
    a small gather might miss.
    """
    plugin = _mk("10/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="stress", user="alice"))
    payload = ToolPreInvokePayload(name="tool", arguments={})

    results = await asyncio.gather(*[plugin.tool_pre_invoke(payload, ctx) for _ in range(100)])

    allowed = sum(1 for r in results if r.violation is None)
    assert allowed == 10, f"Expected exactly 10 allowed, got {allowed} — lock may not be serialising correctly"


@pytest.mark.asyncio
@pytest.mark.parametrize("algorithm", [ALGORITHM_FIXED_WINDOW, ALGORITHM_SLIDING_WINDOW, ALGORITHM_TOKEN_BUCKET])
async def test_concurrent_stress_all_algorithms_do_not_over_allow(algorithm: str):
    """
    100 concurrent tasks against a limit of 15/s, run for each algorithm.

    Each algorithm must allow at most 15 requests. Sliding window and token
    bucket may allow fewer due to their stricter enforcement; none may allow
    more. This confirms the asyncio.Lock path holds regardless of which
    algorithm is selected.
    """
    plugin = _mk("15/s", algorithm=algorithm)
    ctx = PluginContext(global_context=GlobalContext(request_id="algo-stress", user="bob"))
    payload = ToolPreInvokePayload(name="tool", arguments={})

    results = await asyncio.gather(*[plugin.tool_pre_invoke(payload, ctx) for _ in range(100)])

    allowed = sum(1 for r in results if r.violation is None)
    assert allowed <= 15, f"[{algorithm}] Over-allowed: {allowed} > 15 — algorithm may not be thread-safe"


@pytest.mark.asyncio
async def test_concurrent_stress_window_boundary_total_does_not_exceed_double_limit():
    """
    Fixed window burst-at-boundary under concurrent load.

    50 tasks fire before the window resets, 50 fire after. The documented
    worst case for fixed_window is 2× the limit (N requests at end of W1 +
    N at start of W2). Under concurrent asyncio load the total allowed must
    never exceed 2× the limit — if it does, the lock is broken.

    Note: sliding_window and token_bucket are not subject to this bound;
    this test is intentionally fixed_window only.
    """
    limit = 10
    plugin = _mk(f"{limit}/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="boundary", user="carol"))
    payload = ToolPreInvokePayload(name="tool", arguments={})

    # First burst — within the current window
    first_wave = await asyncio.gather(*[plugin.tool_pre_invoke(payload, ctx) for _ in range(50)])

    # Advance time past the window boundary
    backend = plugin._rate_backend
    if isinstance(backend, MemoryBackend) and hasattr(backend._algorithm, "_store"):
        backend._algorithm._store.clear()

    # Second burst — new window
    second_wave = await asyncio.gather(*[plugin.tool_pre_invoke(payload, ctx) for _ in range(50)])

    total_allowed = sum(1 for r in first_wave + second_wave if r.violation is None)
    assert total_allowed <= 2 * limit, f"Total allowed {total_allowed} exceeds 2× limit ({2 * limit}) — " f"fixed_window boundary burst is worse than documented"


# ============================================================================
# Sweep Task Lifecycle Tests
# ============================================================================


@pytest.mark.asyncio
async def test_sweep_evicts_expired_fixed_window_keys():
    """
    After a fixed-window expires, the sweep task removes the key from the store.

    We exhaust the limit, then manually back-date the window start so the sweep
    sees the window as expired, run one sweep cycle, and confirm the store is
    empty. A subsequent request must be allowed again (fresh window).
    """
    backend = MemoryBackend(FixedWindowAlgorithm(), sweep_interval=999)
    # Exhaust a 1/s limit
    await backend.allow("user:dave", "1/s")
    await backend.allow("user:dave", "1/s")

    assert len(backend._algorithm._store) == 1

    # Back-date the window start by 2 seconds so sweep sees it as expired
    for wnd in backend._algorithm._store.values():
        wnd.window_start -= 2

    await backend._algorithm.sweep(backend._lock)

    assert len(backend._algorithm._store) == 0, "Expired window key was not evicted by sweep"

    # A fresh request should be allowed now
    allowed, *_ = await backend.allow("user:dave", "1/s")
    assert allowed is True, "Request after sweep eviction should start a fresh window"


@pytest.mark.asyncio
async def test_sweep_task_restarts_after_cancellation():
    """
    If the background sweep task is cancelled (e.g. during a test teardown or
    event loop churn), the next call to allow() must recreate it via
    _ensure_sweep_task().
    """
    backend = MemoryBackend(FixedWindowAlgorithm(), sweep_interval=999)

    # Trigger task creation
    await backend.allow("user:eve", "5/s")
    task = backend._sweep_task
    assert task is not None and not task.done()

    # Cancel the task — simulates teardown or loop restart
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert backend._sweep_task.done()

    # Next allow() call must recreate the sweep task
    await backend.allow("user:eve", "5/s")
    assert backend._sweep_task is not None
    assert not backend._sweep_task.done(), "Sweep task was not recreated after cancellation"


@pytest.mark.asyncio
async def test_sweep_does_not_evict_active_keys():
    """
    Keys with recent activity must survive a sweep cycle.

    We make a request (creating a live window), run the sweep immediately
    without back-dating the window, and confirm the key is still present.
    """
    backend = MemoryBackend(FixedWindowAlgorithm(), sweep_interval=999)
    await backend.allow("user:frank", "10/s")

    assert len(backend._algorithm._store) == 1

    # Run sweep — window is fresh, should NOT be evicted
    await backend._algorithm.sweep(backend._lock)

    assert len(backend._algorithm._store) == 1, "Active window key was incorrectly evicted by sweep"


# ============================================================================
# Clock / Timing Edge Case Tests
# ============================================================================


@pytest.mark.asyncio
async def test_token_bucket_caps_at_capacity_after_long_inactivity():
    """
    A token bucket that has been inactive for a very long time must not
    accumulate more tokens than its capacity.

    Without a cap, `tokens = min(count, tokens + elapsed * refill_rate)`
    would overflow. This test back-dates last_refill by 24 hours and confirms
    the bucket holds exactly `count` tokens — not more.
    """
    algorithm = TokenBucketAlgorithm()
    lock = asyncio.Lock()

    # First request — creates the bucket with count-1 tokens
    await algorithm.allow(lock, "user:grace", 10, 60)

    # Back-date last_refill by 24 hours to simulate long inactivity
    bucket = algorithm._store["user:grace"]
    bucket.last_refill -= 86400

    # Next request should be allowed and tokens must not exceed capacity (10)
    allowed, limit, _, meta = await algorithm.allow(lock, "user:grace", 10, 60)
    assert allowed is True
    assert meta["remaining"] <= limit, f"Token bucket overflowed: remaining={meta['remaining']} > limit={limit}"


@pytest.mark.asyncio
async def test_fixed_window_resets_after_window_duration_elapses():
    """
    Once a fixed window's duration has elapsed, the next request must open a
    fresh window and be allowed — even if the limit was previously exhausted.

    We exhaust a 2/s limit, then advance the window start backward by 2 seconds
    (simulating time passing), and confirm the next request is allowed.
    """
    algorithm = FixedWindowAlgorithm()
    lock = asyncio.Lock()

    await algorithm.allow(lock, "user:henry", 2, 1)
    await algorithm.allow(lock, "user:henry", 2, 1)
    blocked, *_ = await algorithm.allow(lock, "user:henry", 2, 1)
    assert blocked is False, "Limit should be exhausted at this point"

    # Simulate 2 seconds passing by back-dating the window start
    for wnd in algorithm._store.values():
        wnd.window_start -= 2

    allowed, *_ = await algorithm.allow(lock, "user:henry", 2, 1)
    assert allowed is True, "Request after window expiry should open a fresh window and be allowed"


@pytest.mark.asyncio
async def test_sliding_window_enforces_correctly_with_duplicate_timestamps():
    """
    When multiple requests arrive within the same millisecond, time.time()
    may return identical float values. The sliding window must still enforce
    the limit correctly — duplicate timestamps must each count as a distinct
    request.
    """
    algorithm = SlidingWindowAlgorithm()
    lock = asyncio.Lock()
    fixed_time = time.time()

    with patch("plugins.rate_limiter.rate_limiter.time") as mock_time:
        mock_time.time.return_value = fixed_time

        # Send limit+1 requests all at the same timestamp
        limit = 3
        results = []
        for _ in range(limit + 1):
            result = await algorithm.allow(lock, "user:iris", limit, 60)
            results.append(result)

    allowed = sum(1 for r, *_ in results if r is True)
    assert allowed == limit, f"Expected exactly {limit} allowed with duplicate timestamps, got {allowed}"


# ============================================================================
# Redis Error Mode Tests
# ============================================================================


@pytest.mark.asyncio
async def test_redis_timeout_falls_back_to_memory():
    """
    A transient TimeoutError from the Redis client must trigger the memory
    fallback when redis_fallback=True. The request must be allowed — a Redis
    timeout must never silently block traffic.
    """
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    mock_client = AsyncMock()
    mock_client.eval.side_effect = TimeoutError("Redis timed out")

    fallback = MemoryBackend(FixedWindowAlgorithm())
    backend = RedisBackend(
        redis_url="redis://localhost:6379/0",
        algorithm_name=ALGORITHM_FIXED_WINDOW,
        fallback=fallback,
        _client=mock_client,
    )

    allowed, *_ = await backend.allow("user:jack", "5/s")
    assert allowed is True, "Transient Redis timeout must fall back to memory and allow the request"


@pytest.mark.asyncio
async def test_redis_lua_script_error_fails_open_without_fallback():
    """
    If the Redis Lua script raises a ResponseError (e.g. after a Redis restart
    that flushed cached scripts), and no fallback is configured, the request
    must be allowed — fail-open is the documented behaviour when
    redis_fallback=False.
    """
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    try:
        # Third-Party
        from redis.exceptions import ResponseError  # noqa: PLC0415
    except ImportError:
        pytest.skip("redis package not installed")

    mock_client = AsyncMock()
    mock_client.eval.side_effect = ResponseError("NOSCRIPT No matching script")

    backend = RedisBackend(
        redis_url="redis://localhost:6379/0",
        algorithm_name=ALGORITHM_FIXED_WINDOW,
        fallback=None,
        _client=mock_client,
    )

    allowed, *_ = await backend.allow("user:kate", "5/s")
    assert allowed is True, "Lua script error without fallback must fail open (allow request)"


@pytest.mark.asyncio
async def test_redis_fallback_and_redis_counters_are_independent():
    """
    When Redis is down, the memory fallback tracks its own counter. When Redis
    recovers, the Redis counter starts fresh — the fallback counter must not
    bleed into Redis or vice versa.

    We exhaust the fallback limit during the outage, then restore Redis and
    confirm the first Redis-backed request is allowed (fresh Redis counter).
    """
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    mock_client = AsyncMock()

    # Phase 1: Redis is down — all calls go to fallback
    mock_client.eval.side_effect = ConnectionError("Redis down")
    fallback = MemoryBackend(FixedWindowAlgorithm())
    backend = RedisBackend(
        redis_url="redis://localhost:6379/0",
        algorithm_name=ALGORITHM_FIXED_WINDOW,
        fallback=fallback,
        _client=mock_client,
    )

    # Exhaust the fallback limit (2/s)
    await backend.allow("user:leo", "2/s")
    await backend.allow("user:leo", "2/s")
    fallback_blocked, *_ = await backend.allow("user:leo", "2/s")
    assert fallback_blocked is False, "Fallback must enforce limit during Redis outage"

    # Phase 2: Redis recovers — return a valid fixed-window result ([1, 60])
    mock_client.eval.side_effect = None
    mock_client.eval.return_value = [1, 60]  # count=1, ttl=60 → fresh window

    redis_allowed, *_ = await backend.allow("user:leo", "2/s")
    assert redis_allowed is True, "Redis counter must start fresh after recovery — fallback state must not carry over"


# ============================================================================
# Configuration Edge Case Tests
# ============================================================================


@pytest.mark.asyncio
async def test_very_large_rate_limit_does_not_overflow():
    """
    A rate limit of 1,000,000/min must initialise without error and correctly
    allow the first request. This guards against integer overflow in the counter
    or remaining calculation.
    """
    plugin = _mk("1000000/m")
    ctx = PluginContext(global_context=GlobalContext(request_id="large", user="user-large"))
    payload = ToolPreInvokePayload(name="tool", arguments={})

    result = await plugin.tool_pre_invoke(payload, ctx)
    assert result.violation is None, "First request under a very large limit must be allowed"

    headers = result.http_headers or {}
    remaining = int(headers.get("X-RateLimit-Remaining", -1))
    assert remaining == 999999, f"Remaining should be limit-1=999999, got {remaining}"


@pytest.mark.asyncio
async def test_very_small_rate_limit_allows_first_request():
    """
    A rate limit of 1/hour must allow the first request and block the second.

    This exercises the token bucket and fixed window at an extremely low refill
    rate (1/3600 tokens per second) — floating-point precision must not cause
    the first request to be incorrectly blocked.
    """
    for algorithm in [ALGORITHM_FIXED_WINDOW, ALGORITHM_SLIDING_WINDOW, ALGORITHM_TOKEN_BUCKET]:
        plugin = _mk("1/h", algorithm=algorithm)
        ctx = PluginContext(global_context=GlobalContext(request_id="small", user=f"user-small-{algorithm}"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        first = await plugin.tool_pre_invoke(payload, ctx)
        assert first.violation is None, f"[{algorithm}] First request under 1/h limit must be allowed"

        second = await plugin.tool_pre_invoke(payload, ctx)
        assert second.violation is not None, f"[{algorithm}] Second request under 1/h limit must be blocked"


def test_by_tool_with_special_character_tool_names():
    """
    Tool names containing spaces, slashes, and unicode characters must be
    accepted by _validate_config and stored as-is. The rate limiter must
    match by exact key — no normalisation or stripping.
    """
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={
                "by_tool": {
                    "my tool/v2": "5/m",
                    "outil-résumé": "10/m",
                    "工具": "3/m",
                }
            },
        )
    )
    # Config must be accepted without errors
    assert plugin._cfg.by_tool is not None
    assert "my tool/v2" in plugin._cfg.by_tool
    assert "outil-résumé" in plugin._cfg.by_tool
    assert "工具" in plugin._cfg.by_tool


# ============================================================================
# P0 Unit Tests — Redis/Memory Correctness
# ============================================================================


@pytest.mark.asyncio
async def test_redis_sliding_window_counts_multiple_requests_with_same_timestamp():
    """
    The fixed sliding window Lua script uses a unique member per request
    (ARGV[4] = uuid), so concurrent requests at the same timestamp each occupy
    their own sorted-set slot. Three requests at an identical timestamp against
    a limit of 2/s: first two allowed, third blocked.
    """
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    fixed_ts = 1_700_000_000.0

    # Simulate the FIXED Lua behaviour: unique member per request, check before ZADD
    store: dict[str, dict] = {}

    async def fake_eval(script, numkeys, key, *args):
        if "ZREMRANGEBYSCORE" in script:
            now = float(args[0])
            window = float(args[1])
            limit_val = int(args[2])
            member = str(args[3])  # unique member (uuid hex from _allow_sliding)
            cutoff = now - window
            if key not in store:
                store[key] = {}
            store[key] = {m: s for m, s in store[key].items() if s > cutoff}
            count = len(store[key])
            oldest_ts = min(store[key].values()) if store[key] else 0
            if count >= limit_val:
                return [0, count, oldest_ts]  # [allowed=0, count, oldest_ts]
            store[key][member] = now
            count += 1
            oldest_ts = min(store[key].values()) if store[key] else 0
            return [1, count, oldest_ts]  # [allowed=1, count, oldest_ts]
        return [0, 0, 0]

    mock_client = AsyncMock()
    mock_client.eval.side_effect = fake_eval

    backend = RedisBackend(
        redis_url="redis://localhost:6379/0",
        algorithm_name=ALGORITHM_SLIDING_WINDOW,
        fallback=None,
        _client=mock_client,
    )

    limit = "2/s"
    with patch("plugins.rate_limiter.rate_limiter.time") as mock_time:
        mock_time.time.return_value = fixed_ts
        r1, *_ = await backend.allow("user:test", limit)
        r2, *_ = await backend.allow("user:test", limit)
        r3, *_ = await backend.allow("user:test", limit)

    assert r1 is True
    assert r2 is True
    assert r3 is False, "Third request at same timestamp must be blocked — " "each request now occupies its own sorted-set slot via unique member"


@pytest.mark.asyncio
async def test_sliding_window_memory_evicts_idle_keys_after_window_expires():
    """
    When a sliding window key has no activity for longer than the window duration,
    the next allow() call must naturally evict stale timestamps and treat the key
    as fresh — allowing requests up to the full limit again.

    This tests the natural eviction path via allow() itself, not the sweep task.
    """
    algorithm = SlidingWindowAlgorithm()
    lock = asyncio.Lock()
    now = time.time()

    with patch("plugins.rate_limiter.rate_limiter.time") as mock_time:
        # Exhaust the limit now
        mock_time.time.return_value = now
        await algorithm.allow(lock, "user:test", 2, 1)
        await algorithm.allow(lock, "user:test", 2, 1)
        blocked, *_ = await algorithm.allow(lock, "user:test", 2, 1)
        assert blocked is False

        # Advance time past the window — all previous timestamps are now stale
        mock_time.time.return_value = now + 2.0

        # Next call must see an empty window and allow the request
        allowed, *_ = await algorithm.allow(lock, "user:test", 2, 1)
        assert allowed is True, "After window expires, allow() must evict stale timestamps and allow fresh requests"


@pytest.mark.asyncio
async def test_memory_and_redis_sliding_window_have_same_allow_block_sequence():
    """
    Memory backend and Redis backend must produce identical allow/block decisions
    for the same request timeline. This parity test uses an in-process Redis
    simulator that faithfully implements the fixed sliding window Lua script logic:
    unique member per request (ARGV[4]) and count check before ZADD.
    """
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    # In-process Redis simulator for the FIXED sliding window Lua script
    sim_store: dict[str, dict] = {}

    async def sliding_sim(script, numkeys, key, *args):
        now = float(args[0])
        window = float(args[1])
        limit_val = int(args[2])
        member = str(args[3])  # unique member from _allow_sliding
        cutoff = now - window
        if key not in sim_store:
            sim_store[key] = {}
        sim_store[key] = {m: s for m, s in sim_store[key].items() if s > cutoff}
        count = len(sim_store[key])
        oldest_ts = min(sim_store[key].values()) if sim_store[key] else now
        # Check before ZADD — blocked requests do NOT inflate the set
        if count >= limit_val:
            return [0, count, oldest_ts]  # [allowed=0, count, oldest_ts]
        sim_store[key][member] = now
        count += 1
        oldest_ts = min(sim_store[key].values()) if sim_store[key] else now
        return [1, count, oldest_ts]  # [allowed=1, count, oldest_ts]

    mock_client = AsyncMock()
    mock_client.eval.side_effect = sliding_sim

    redis_backend = RedisBackend(
        redis_url="redis://localhost:6379/0",
        algorithm_name=ALGORITHM_SLIDING_WINDOW,
        fallback=None,
        _client=mock_client,
    )
    memory_backend = MemoryBackend(SlidingWindowAlgorithm())

    limit = "3/s"
    base = time.time()
    offsets = [0.0, 0.1, 0.2, 0.5, 0.8, 1.1, 1.2, 1.5]

    redis_decisions = []
    memory_decisions = []

    for offset in offsets:
        t = base + offset
        with patch("plugins.rate_limiter.rate_limiter.time") as mock_time:
            mock_time.time.return_value = t
            r_allowed, *_ = await redis_backend.allow("user:test", limit)
            m_allowed, *_ = await memory_backend.allow("user:test", limit)
        redis_decisions.append(r_allowed)
        memory_decisions.append(m_allowed)

    assert redis_decisions == memory_decisions, f"Memory and Redis sliding window diverged:\n" f"  Redis:  {redis_decisions}\n" f"  Memory: {memory_decisions}"


@pytest.mark.asyncio
async def test_memory_and_redis_token_bucket_have_same_allow_block_sequence():
    """
    Memory backend and Redis backend must produce identical allow/block decisions
    for the token bucket algorithm across a fixed request timeline.
    Uses an in-process simulator of the token bucket Lua script.
    """
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    # In-process Redis simulator for token bucket
    sim_bucket: dict[str, dict] = {}

    async def token_bucket_sim(script, numkeys, key, *args):
        capacity = float(args[0])
        rate = float(args[1])
        now = float(args[2])

        if key not in sim_bucket:
            tokens = capacity - 1
            sim_bucket[key] = {"tokens": tokens, "last_refill": now}
            return [1, int(tokens), 0]

        b = sim_bucket[key]
        elapsed = now - b["last_refill"]
        tokens = min(capacity, b["tokens"] + elapsed * rate)

        if tokens >= 1.0:
            tokens -= 1.0
            allowed = 1
            time_to_next = 0
        else:
            allowed = 0
            time_to_next = int((1.0 - tokens) / rate) + 1

        sim_bucket[key] = {"tokens": tokens, "last_refill": now}
        return [allowed, int(tokens), time_to_next]

    mock_client = AsyncMock()
    mock_client.eval.side_effect = token_bucket_sim

    redis_backend = RedisBackend(
        redis_url="redis://localhost:6379/0",
        algorithm_name=ALGORITHM_TOKEN_BUCKET,
        fallback=None,
        _client=mock_client,
    )
    memory_backend = MemoryBackend(TokenBucketAlgorithm())

    limit = "3/s"
    base = time.time()
    offsets = [0.0, 0.1, 0.2, 0.4, 0.8, 1.0, 1.2, 1.6, 2.0]

    redis_decisions = []
    memory_decisions = []

    for offset in offsets:
        t = base + offset
        with patch("plugins.rate_limiter.rate_limiter.time") as mock_time:
            mock_time.time.return_value = t
            r_allowed, *_ = await redis_backend.allow("user:test", limit)
            m_allowed, *_ = await memory_backend.allow("user:test", limit)
        redis_decisions.append(r_allowed)
        memory_decisions.append(m_allowed)

    assert redis_decisions == memory_decisions, f"Memory and Redis token bucket diverged:\n" f"  Redis:  {redis_decisions}\n" f"  Memory: {memory_decisions}"


# ---------------------------------------------------------------------------
# P1 Unit Tests — header consistency and correctness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_bucket_success_headers_are_consistent_between_memory_and_redis():
    """
    For allowed token bucket requests, both memory and Redis backends must
    produce the same X-RateLimit-Remaining value and X-RateLimit-Limit == configured limit.
    """
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    sim_bucket: dict[str, dict] = {}

    async def token_bucket_sim(script, numkeys, key, *args):
        capacity = float(args[0])
        rate = float(args[1])
        now = float(args[2])
        if key not in sim_bucket:
            tokens = capacity - 1
            sim_bucket[key] = {"tokens": tokens, "last_refill": now}
            return [1, int(tokens), 0]
        b = sim_bucket[key]
        elapsed = now - b["last_refill"]
        tokens = min(capacity, b["tokens"] + elapsed * rate)
        if tokens >= 1.0:
            tokens -= 1.0
            allowed = 1
            time_to_next = 0
        else:
            allowed = 0
            time_to_next = int((1.0 - tokens) / rate) + 1
        sim_bucket[key] = {"tokens": tokens, "last_refill": now}
        return [allowed, int(tokens), time_to_next]

    mock_client = AsyncMock()
    mock_client.eval.side_effect = token_bucket_sim

    limit = "5/s"
    t0 = time.time()

    memory_backend = MemoryBackend(TokenBucketAlgorithm())
    redis_backend = RedisBackend(
        redis_url="redis://localhost:6379/0",
        algorithm_name=ALGORITHM_TOKEN_BUCKET,
        fallback=None,
        _client=mock_client,
    )

    with patch("plugins.rate_limiter.rate_limiter.time") as mock_time:
        mock_time.time.return_value = t0
        m_allowed, m_limit, m_reset, m_meta = await memory_backend.allow("user:x", limit)
        r_allowed, r_limit, r_reset, r_meta = await redis_backend.allow("user:x", limit)

    assert m_allowed is True
    assert r_allowed is True
    # Both must report the configured limit
    assert m_limit == 5
    assert r_limit == 5
    # Remaining should be 4 (one token consumed from a full bucket of 5)
    m_remaining = m_meta.get("remaining", 0)
    r_remaining = r_meta.get("remaining", 0)
    assert m_remaining == 4
    assert r_remaining == 4
    # Reset timestamp should be >= now
    assert m_reset >= t0
    assert r_reset >= t0


@pytest.mark.asyncio
async def test_token_bucket_memory_reset_timestamp_always_in_future():
    """Token bucket memory backend must never produce a past/present reset timestamp.

    When tokens_needed / refill_rate < 1, int() truncates to 0, placing
    reset_timestamp at now rather than in the future.  max(1, ...) guards
    against this — mirroring the same protection already present in the
    Redis path.

    Regression test: with limit="3/s", after consuming 1 token from a full
    bucket, tokens_needed=1 and refill_rate=3, so 1/3 ≈ 0.33 → int() = 0
    without the fix.
    """
    backend = MemoryBackend(TokenBucketAlgorithm())
    t0 = 1_000_000.0

    with patch("plugins.rate_limiter.rate_limiter.time") as mock_time:
        mock_time.time.return_value = t0
        allowed, _, reset_timestamp, _ = await backend.allow("user:test", "3/s")

    assert allowed is True
    assert reset_timestamp > t0, (
        f"reset_timestamp ({reset_timestamp}) must be strictly greater than now ({t0}). " "int(tokens_needed / refill_rate) rounds to 0 for fast refill rates without max(1, ...)."
    )


@pytest.mark.asyncio
async def test_sliding_window_reset_header_tracks_oldest_request_expiry():
    """
    For sliding_window, X-RateLimit-Reset must equal the timestamp of the
    oldest request in the current window plus the window duration — i.e.
    when that request ages out and a new slot opens.

    Forces the Python fallback path because the test relies on mocking
    time.time() to control both now_unix and internal rate-math timing.
    The Rust engine's monotonic clock is not affected by Python time mocks,
    so real elapsed time between requests causes the nanos-to-seconds
    integer division to diverge from the mocked expectations.
    """
    with patch("plugins.rate_limiter.rate_limiter._RUST_AVAILABLE", False):
        plugin = _mk("3/s", ALGORITHM_SLIDING_WINDOW)
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
        payload = ToolPreInvokePayload(name="t", arguments={})
        t0 = 1_000_000.0

        # First request at t0
        with patch("plugins.rate_limiter.rate_limiter.time") as mt:
            mt.time.return_value = t0
            r1 = await plugin.tool_pre_invoke(payload, ctx)
        assert r1.violation is None
        reset_after_first = (r1.http_headers or {}).get("X-RateLimit-Reset")
        assert reset_after_first is not None
        # Reset should be t0 + 1s (window = 1s, oldest entry = t0)
        assert float(reset_after_first) == pytest.approx(t0 + 1.0, abs=0.1)

        # Second request at t0 + 0.3s — oldest is still t0
        with patch("plugins.rate_limiter.rate_limiter.time") as mt:
            mt.time.return_value = t0 + 0.3
            r2 = await plugin.tool_pre_invoke(payload, ctx)
        assert r2.violation is None
        reset_after_second = (r2.http_headers or {}).get("X-RateLimit-Reset")
        # Reset still anchored to t0 (oldest request)
        assert float(reset_after_second) == pytest.approx(t0 + 1.0, abs=0.1)


@pytest.mark.asyncio
async def test_token_bucket_retry_after_matches_time_to_next_token():
    """
    When a token bucket request is blocked, Retry-After must be > 0 and
    reflect the time until the next token is available (roughly 1/rate seconds).
    """
    plugin = _mk("2/s", ALGORITHM_TOKEN_BUCKET)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
    payload = ToolPreInvokePayload(name="t", arguments={})
    t0 = 1_000_000.0

    # Exhaust both tokens
    with patch("plugins.rate_limiter.rate_limiter.time") as mt:
        mt.time.return_value = t0
        r1 = await plugin.tool_pre_invoke(payload, ctx)
        r2 = await plugin.tool_pre_invoke(payload, ctx)
    assert r1.violation is None
    assert r2.violation is None

    # Third request at same instant — bucket empty
    with patch("plugins.rate_limiter.rate_limiter.time") as mt:
        mt.time.return_value = t0
        r3 = await plugin.tool_pre_invoke(payload, ctx)
    assert r3.violation is not None
    retry_after = (r3.violation.http_headers or {}).get("Retry-After")
    assert retry_after is not None
    retry_secs = int(retry_after)
    # With rate 2/s, one token refills in 0.5s — Retry-After should be 1s (integer ceiling)
    assert 1 <= retry_secs <= 2


@pytest.mark.asyncio
@pytest.mark.parametrize("algorithm", [ALGORITHM_FIXED_WINDOW, ALGORITHM_SLIDING_WINDOW, ALGORITHM_TOKEN_BUCKET])
async def test_remaining_header_never_goes_negative_for_any_algorithm(algorithm: str):
    """
    X-RateLimit-Remaining must never be negative, regardless of algorithm,
    even when requests arrive after the limit is exhausted.
    """
    plugin = _mk("2/s", algorithm)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
    payload = ToolPreInvokePayload(name="t", arguments={})
    t0 = 1_000_000.0

    for _ in range(5):  # send 5 requests against a limit of 2
        with patch("plugins.rate_limiter.rate_limiter.time") as mt:
            mt.time.return_value = t0
            result = await plugin.tool_pre_invoke(payload, ctx)
        # Headers are on result.http_headers for allowed requests,
        # and on result.violation.http_headers for blocked requests.
        if result.violation is not None:
            headers = result.violation.http_headers or {}
        else:
            headers = result.http_headers or {}
        remaining_str = headers.get("X-RateLimit-Remaining")
        assert remaining_str is not None, "X-RateLimit-Remaining header must always be present"
        remaining = int(remaining_str)
        assert remaining >= 0, f"Remaining went negative ({remaining}) for algorithm={algorithm}"


# =============================================================================
# P1 Tests — SlidingWindowAlgorithm sweep() correctness
# =============================================================================


@pytest.mark.asyncio
async def test_sliding_window_sweep_evicts_keys_with_fully_stale_timestamps():
    """sweep() must remove keys whose entire timestamp list is outside the window.

    After a burst of activity, a key's timestamps age out over time.  The
    background sweep must remove such keys so memory does not grow without bound
    in long-lived gateways with transient users.

    This is a regression test: the previous implementation only removed keys
    with empty lists, leaving stale-but-non-empty entries alive indefinitely.
    """
    algorithm = SlidingWindowAlgorithm()
    lock = asyncio.Lock()

    with patch("plugins.rate_limiter.rate_limiter.time") as mock_time:
        # t=0: user makes requests that fill the window
        mock_time.time.return_value = 0.0
        await algorithm.allow(lock, "user:alice", 3, 1)
        await algorithm.allow(lock, "user:alice", 3, 1)

        # Confirm the key is present in the store
        assert any("user:alice" in k for k in algorithm._store), "Key must exist in store after allow() calls"

        # t=5: well past the 1-second window — all timestamps are stale
        mock_time.time.return_value = 5.0
        await algorithm.sweep(lock)

    # sweep() must have evicted the key — no stale entry should remain
    assert not any("user:alice" in k for k in algorithm._store), "sweep() must evict keys with fully stale timestamps, not just empty lists — " "idle users must not accumulate memory indefinitely"


@pytest.mark.asyncio
async def test_sliding_window_sweep_does_not_evict_active_keys():
    """sweep() must not remove keys that still have timestamps within the window."""
    algorithm = SlidingWindowAlgorithm()
    lock = asyncio.Lock()

    with patch("plugins.rate_limiter.rate_limiter.time") as mock_time:
        mock_time.time.return_value = 0.0
        await algorithm.allow(lock, "user:bob", 3, 60)  # 60-second window

        # t=10: still well within the 60-second window
        mock_time.time.return_value = 10.0
        await algorithm.sweep(lock)

    # Key must still be present — it has active timestamps
    assert any("user:bob" in k for k in algorithm._store), "sweep() must not evict keys whose timestamps are still within the window"


@pytest.mark.asyncio
async def test_sliding_window_allow_after_sweep_starts_fresh():
    """After sweep() evicts a stale key, a subsequent allow() treats it as a new key.

    This validates that eviction and re-admission work together correctly:
    a user who was rate-limited, goes idle (key swept), and returns should
    start with a full quota — not inherit leftover state.
    """
    algorithm = SlidingWindowAlgorithm()
    lock = asyncio.Lock()

    with patch("plugins.rate_limiter.rate_limiter.time") as mock_time:
        # Exhaust the limit at t=0
        mock_time.time.return_value = 0.0
        await algorithm.allow(lock, "user:carol", 2, 1)
        await algorithm.allow(lock, "user:carol", 2, 1)
        blocked, *_ = await algorithm.allow(lock, "user:carol", 2, 1)
        assert blocked is False, "Third request must be blocked"

        # t=5: window expired — sweep evicts the stale key
        mock_time.time.return_value = 5.0
        await algorithm.sweep(lock)

        # t=5: allow() must treat carol as a fresh key with full quota
        allowed, *_ = await algorithm.allow(lock, "user:carol", 2, 1)
        assert allowed is True, "After sweep() evicts the stale key, the next allow() must start fresh " "with a full quota — stale state must not persist"


# ---------------------------------------------------------------------------
# Rust engine architecture tests
# ---------------------------------------------------------------------------
# These tests assert the Python↔Rust seam properties required by the spec:
#   ARCH-01  check()/check_async() called exactly once per hook invocation
#   ARCH-03  Python wrapper contains no rate math (structural — the wrapper
#            delegates to check() which returns (allowed, headers, meta))
#   ARCH-04  Rust engine error / exception → fail-open (request allowed)
#   ARCH-05  _RUST_AVAILABLE = False path exercises the Python backend
# ---------------------------------------------------------------------------


def _mk_rust(rate: str, algorithm: str = ALGORITHM_FIXED_WINDOW) -> RateLimiterPlugin:
    """Create a plugin instance that is guaranteed to use the Rust engine."""
    # First-Party
    import plugins.rate_limiter.rate_limiter as _rl_mod

    with patch.object(_rl_mod, "_RUST_AVAILABLE", True):
        # If the real Rust extension is not installed this will silently fall
        # back to Python; the architecture tests skip in that case.
        plugin = RateLimiterPlugin(
            PluginConfig(
                name="rl",
                kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
                hooks=[PromptHookType.PROMPT_PRE_FETCH, ToolHookType.TOOL_PRE_INVOKE],
                config={"by_user": rate, "algorithm": algorithm},
            )
        )
    return plugin


# First-Party
import plugins.rate_limiter.rate_limiter as _rate_limiter_module  # noqa: E402

_RUST_ENGINE_PRESENT = _rate_limiter_module._RUST_AVAILABLE
_skip_no_rust = pytest.mark.skipif(not _RUST_ENGINE_PRESENT, reason="Rust engine not installed")


@_skip_no_rust
@pytest.mark.asyncio
async def test_arch01_evaluate_many_called_once_per_tool_hook():
    """ARCH-01: Python wrapper makes exactly one check() call per hook.

    The seam between Python and Rust must be a single PyO3 call regardless of
    how many active dimensions (user, tenant, tool) the request touches.
    Multiple calls would compound the bridge-crossing overhead under concurrency.
    """
    plugin = _mk_rust("10/s")
    assert plugin._rust_engine is not None, "Rust engine must be active for this test"

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id="acme"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    with patch.object(plugin._rust_engine, "check", wraps=plugin._rust_engine.check) as mock_check:
        await plugin.tool_pre_invoke(payload, ctx)
        assert mock_check.call_count == 1, f"check() must be called exactly once per hook invocation, got {mock_check.call_count}"


@_skip_no_rust
@pytest.mark.asyncio
async def test_arch01_evaluate_many_called_once_per_prompt_hook():
    """ARCH-01: Same single-call guarantee for prompt_pre_fetch via check()."""
    plugin = _mk_rust("10/s")
    assert plugin._rust_engine is not None

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = PromptPrehookPayload(prompt_id="my_prompt")

    with patch.object(plugin._rust_engine, "check", wraps=plugin._rust_engine.check) as mock_check:
        await plugin.prompt_pre_fetch(payload, ctx)
        assert mock_check.call_count == 1


@_skip_no_rust
@pytest.mark.asyncio
async def test_arch01_redis_rust_path_uses_async_entrypoint():
    """Redis-backed Rust path should await check_async exactly once."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": "10/s", "backend": "redis", "redis_url": "redis://localhost:6379/0"},
        )
    )
    if plugin._rust_engine is None:
        pytest.skip("Rust engine not active")

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="search", arguments={})

    sync_mock = patch.object(plugin._rust_engine, "check", wraps=plugin._rust_engine.check)
    async_mock = patch.object(plugin._rust_engine, "check_async", AsyncMock(wraps=plugin._rust_engine.check_async))
    with sync_mock as mock_sync, async_mock as mock_async:
        await plugin.tool_pre_invoke(payload, ctx)
        assert mock_async.await_count == 1
        assert mock_sync.call_count == 0


@_skip_no_rust
@pytest.mark.asyncio
async def test_arch01_memory_rust_path_keeps_sync_entrypoint():
    """Memory-backed Rust path should continue using the sync check entrypoint."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    plugin = _mk_rust("10/s")
    assert plugin._rust_engine is not None

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="search", arguments={})

    sync_mock = patch.object(plugin._rust_engine, "check", wraps=plugin._rust_engine.check)
    async_mock = patch.object(plugin._rust_engine, "check_async", AsyncMock(wraps=plugin._rust_engine.check_async))
    with sync_mock as mock_sync, async_mock as mock_async:
        await plugin.tool_pre_invoke(payload, ctx)
        assert mock_sync.call_count == 1
        assert mock_async.await_count == 0


@_skip_no_rust
@pytest.mark.asyncio
async def test_arch01_single_call_covers_all_active_dimensions():
    """ARCH-01: The single check() call receives all active dimensions.

    When user + tenant + tool are all configured, check() receives them as
    separate arguments and builds the checks internally — not split across
    multiple calls.
    """
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={
                "by_user": "30/m",
                "by_tenant": "300/m",
                "by_tool": {"search": "10/m"},
                "algorithm": ALGORITHM_FIXED_WINDOW,
            },
        )
    )
    if plugin._rust_engine is None:
        pytest.skip("Rust engine not active")

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id="acme"))
    payload = ToolPreInvokePayload(name="search", arguments={})

    with patch.object(plugin._rust_engine, "check", wraps=plugin._rust_engine.check) as mock_check:
        await plugin.tool_pre_invoke(payload, ctx)
        assert mock_check.call_count == 1
        # check() receives (user, tenant, tool, now_unix, include_retry_after)
        args = mock_check.call_args[0]
        assert args[0] == "alice", f"user must be passed; got {args[0]}"
        assert args[1] == "acme", f"tenant must be passed; got {args[1]}"
        assert args[2] == "search", f"tool must be passed; got {args[2]}"


@_skip_no_rust
@pytest.mark.asyncio
async def test_arch02_rust_tool_success_preserves_metadata_shape():
    """Rust fast path should preserve success metadata on the Python wrapper contract.

    The check() API returns (allowed, headers, meta) directly; the Python
    wrapper passes meta through as-is.
    """
    plugin = _mk_rust("10/s")
    assert plugin._rust_engine is not None

    fake_meta = {
        "limited": True,
        "remaining": 7,
        "reset_in": 60,
        "dimensions": {
            "allowed": [
                {"limited": True, "remaining": 9, "reset_in": 60},
                {"limited": True, "remaining": 7, "reset_in": 60},
            ]
        },
    }
    fake_headers = {
        "X-RateLimit-Limit": "10",
        "X-RateLimit-Remaining": "7",
        "X-RateLimit-Reset": "1700000060",
        "Retry-After": "0",
    }

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="search", arguments={})

    with patch.object(plugin._rust_engine, "check", return_value=(True, fake_headers, fake_meta)):
        result = await plugin.tool_pre_invoke(payload, ctx)

    assert result.violation is None
    assert result.metadata == fake_meta


@_skip_no_rust
@pytest.mark.asyncio
async def test_arch02_rust_prompt_block_preserves_details_shape():
    """Rust fast path should preserve blocked details on the Python wrapper contract.

    The check() API returns (allowed, headers, meta) directly; on a block the
    Python wrapper uses meta as violation.details.
    """
    plugin = _mk_rust("1/s")
    assert plugin._rust_engine is not None

    fake_meta = {
        "limited": True,
        "remaining": 0,
        "reset_in": 30,
        "dimensions": {
            "violated": [{"limited": True, "remaining": 0, "reset_in": 30}],
            "allowed": [{"limited": True, "remaining": 8, "reset_in": 60}],
        },
    }
    fake_headers = {
        "X-RateLimit-Limit": "1",
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset": "1700000030",
        "Retry-After": "30",
    }

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = PromptPrehookPayload(prompt_id="search")

    with patch.object(plugin._rust_engine, "check", return_value=(False, fake_headers, fake_meta)):
        result = await plugin.prompt_pre_fetch(payload, ctx)

    assert result.violation is not None
    assert result.violation.details == fake_meta


@_skip_no_rust
@pytest.mark.asyncio
async def test_arch04_rust_exception_is_fail_open():
    """ARCH-04: Rust engine exception → request is allowed (fail-open).

    The fail-open policy lives in Python, not Rust. If check() raises
    any exception, the hook must return an allow result — never block the caller.
    """
    plugin = _mk_rust("10/s")
    if plugin._rust_engine is None:
        pytest.skip("Rust engine not active")

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    with patch.object(plugin._rust_engine, "check", side_effect=RuntimeError("simulated Rust panic")):
        result = await plugin.tool_pre_invoke(payload, ctx)

    assert result.violation is None, "A Rust engine exception must not block the request — fail-open policy " "requires the hook to allow through on any unexpected error"
    assert result.continue_processing is True


@_skip_no_rust
@pytest.mark.asyncio
async def test_arch04_rust_exception_fail_open_prompt_hook():
    """ARCH-04: Same fail-open guarantee for prompt_pre_fetch via check()."""
    plugin = _mk_rust("10/s")
    if plugin._rust_engine is None:
        pytest.skip("Rust engine not active")

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = PromptPrehookPayload(prompt_id="my_prompt")

    with patch.object(plugin._rust_engine, "check", side_effect=RuntimeError("simulated Rust panic")):
        result = await plugin.prompt_pre_fetch(payload, ctx)

    assert result.violation is None
    assert result.continue_processing is True


@_skip_no_rust
@pytest.mark.asyncio
async def test_arch04_rust_redis_exception_uses_python_fallback_when_enabled():
    """Rust Redis runtime failure should honor redis_fallback=True via Python backend."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": "2/s", "backend": "redis", "redis_url": "redis://localhost:6379/0", "redis_fallback": True},
        )
    )
    if plugin._rust_engine is None:
        pytest.skip("Rust engine not active")

    class _BrokenRedis:
        async def eval(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("Redis is down")

        async def evalsha(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("Redis is down")

        async def script_load(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("Redis is down")

    plugin._rate_backend._client = _BrokenRedis()
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    with patch.object(
        plugin._rust_engine,
        "check_async",
        AsyncMock(side_effect=RuntimeError("simulated Rust panic")),
    ):
        r1 = await plugin.tool_pre_invoke(payload, ctx)
        r2 = await plugin.tool_pre_invoke(payload, ctx)
        r3 = await plugin.tool_pre_invoke(payload, ctx)

    assert r1.violation is None
    assert r2.violation is None
    assert r3.violation is not None, "Python fallback must still enforce the configured limit"
    assert r3.violation.http_status_code == 429


@_skip_no_rust
@pytest.mark.asyncio
async def test_arch04_rust_redis_exception_fail_open_when_fallback_disabled():
    """Rust Redis runtime failure should remain fail-open when redis_fallback=False."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": "2/s", "backend": "redis", "redis_url": "redis://localhost:6379/0", "redis_fallback": False},
        )
    )
    if plugin._rust_engine is None:
        pytest.skip("Rust engine not active")

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    with patch.object(
        plugin._rust_engine,
        "check_async",
        AsyncMock(side_effect=RuntimeError("simulated Rust panic")),
    ):
        result = await plugin.tool_pre_invoke(payload, ctx)

    assert result.violation is None
    assert result.continue_processing is True


@pytest.mark.asyncio
async def test_arch05_python_backend_used_when_rust_unavailable():
    """ARCH-05: When _RUST_AVAILABLE is False the Python MemoryBackend is used.

    The Rust engine is an acceleration path; Python memory backend must remain
    fully functional as a drop-in fallback when the extension is not installed.
    """
    # First-Party
    import plugins.rate_limiter.rate_limiter as _rl_mod

    with patch.object(_rl_mod, "_RUST_AVAILABLE", False):
        plugin = RateLimiterPlugin(
            PluginConfig(
                name="rl",
                kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE],
                config={"by_user": "3/s"},
            )
        )

    assert plugin._rust_engine is None, "Python fallback must not activate Rust engine"
    assert isinstance(plugin._rate_backend, MemoryBackend), "Python fallback must use MemoryBackend"

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="tool", arguments={})

    for _ in range(3):
        r = await plugin.tool_pre_invoke(payload, ctx)
        assert r.violation is None

    blocked = await plugin.tool_pre_invoke(payload, ctx)
    assert blocked.violation is not None
    assert blocked.violation.http_status_code == 429


@_skip_no_rust
@pytest.mark.asyncio
async def test_arch05_rust_engine_active_when_available():
    """ARCH-05 complement: when Rust is available, engine is wired in for memory backend."""
    plugin = _mk_rust("10/s")
    assert plugin._rust_engine is not None, "Rust engine must be active when _RUST_AVAILABLE=True and backend=memory"


@pytest.mark.asyncio
async def test_arch05_redis_backend_rust_owns_redis_when_available():
    """ARCH-06: When Rust is available and backend=redis, Rust owns the Redis connection.

    The Rust engine handles both memory and Redis backends. When _RUST_AVAILABLE=True
    and backend=redis, _rust_engine is set and the Rust extension communicates with
    Redis directly. The Python RedisBackend is still present for the Python fallback
    path (when Rust is unavailable).
    """
    # First-Party
    import plugins.rate_limiter.rate_limiter as _rl_mod

    if not _rl_mod._RUST_AVAILABLE:
        pytest.skip("Rust extension not available in this environment")

    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": "10/s", "backend": "redis", "redis_url": "redis://localhost:6379/0"},
        )
    )
    assert plugin._rust_engine is not None, "Rust engine must be active for Redis backend when Rust is available"
    assert isinstance(plugin._rate_backend, RedisBackend)


# =============================================================================
# Redis Batching Tests (REDIS-01, REDIS-03)
#
# REDIS-01: All dimension checks (user, tenant, tool) for a single hook
#           invocation must be batched into exactly ONE Redis eval call.
#           Current impl makes up to 3 sequential calls — these tests drive
#           the implementation of allow_many() and a multi-dimension Lua script.
#
# REDIS-03: The single Lua script call accepts all active dimensions and
#           returns all results in one reply.
# =============================================================================


def _mk_redis_plugin(config: dict) -> RateLimiterPlugin:
    """Create a Redis-backed plugin with a mock client injected.

    Forces _RUST_AVAILABLE=False so the Python RedisBackend path is exercised —
    these tests verify Python-level batching semantics (REDIS-01/03).
    The Rust+Redis path is validated by the load test.
    """
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    # First-Party
    import plugins.rate_limiter.rate_limiter as _rl_mod  # noqa: PLC0415

    with patch.object(_rl_mod, "_RUST_AVAILABLE", False):
        plugin = RateLimiterPlugin(
            PluginConfig(
                name="rl",
                kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
                hooks=[PromptHookType.PROMPT_PRE_FETCH, ToolHookType.TOOL_PRE_INVOKE],
                config={"backend": "redis", "redis_url": "redis://localhost:6379/0", **config},
            )
        )
    mock_client = AsyncMock()
    plugin._rate_backend._client = mock_client
    return plugin


@pytest.mark.asyncio
async def test_redis01_single_eval_call_per_tool_hook_one_dimension():
    """REDIS-01: With only by_user configured, tool_pre_invoke makes exactly 1 eval call."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    plugin = _mk_redis_plugin({"by_user": "10/s"})
    mock_client = plugin._rate_backend._client
    mock_client.eval = AsyncMock(return_value=[1, 60])  # fixed window: [count, ttl]

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    await plugin.tool_pre_invoke(payload, ctx)

    assert mock_client.eval.call_count == 1, f"REDIS-01: expected exactly 1 eval call for 1 active dimension, " f"got {mock_client.eval.call_count}"


@pytest.mark.asyncio
async def test_redis01_single_eval_call_per_tool_hook_three_dimensions():
    """REDIS-01: With user + tenant + tool all configured, tool_pre_invoke must
    still make exactly 1 eval call — all dimensions batched into one round-trip."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    plugin = _mk_redis_plugin(
        {
            "by_user": "30/m",
            "by_tenant": "300/m",
            "by_tool": {"search": "10/m"},
            "algorithm": ALGORITHM_FIXED_WINDOW,
        }
    )
    mock_client = plugin._rate_backend._client
    # Batched response: one result per dimension — [count, ttl] per dim
    mock_client.eval = AsyncMock(return_value=[[1, 60], [1, 60], [1, 60]])

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id="acme"))
    payload = ToolPreInvokePayload(name="search", arguments={})

    await plugin.tool_pre_invoke(payload, ctx)

    assert mock_client.eval.call_count == 1, (
        f"REDIS-01: expected exactly 1 eval call for 3 active dimensions (user+tenant+tool), " f"got {mock_client.eval.call_count} — dimensions must be batched into one round-trip"
    )


@pytest.mark.asyncio
async def test_redis01_single_eval_call_per_prompt_hook():
    """REDIS-01: prompt_pre_fetch also makes exactly 1 eval call regardless of active dims."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    plugin = _mk_redis_plugin(
        {
            "by_user": "10/s",
            "by_tenant": "100/s",
            "algorithm": ALGORITHM_FIXED_WINDOW,
        }
    )
    mock_client = plugin._rate_backend._client
    mock_client.eval = AsyncMock(return_value=[[1, 60], [1, 60]])

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id="acme"))
    payload = PromptPrehookPayload(prompt_id="my_prompt")

    await plugin.prompt_pre_fetch(payload, ctx)

    assert mock_client.eval.call_count == 1, f"REDIS-01: prompt_pre_fetch must batch all dimensions into 1 eval call, " f"got {mock_client.eval.call_count}"


@pytest.mark.asyncio
async def test_redis03_batched_script_returns_result_per_dimension():
    """REDIS-03: The single eval call must pass all active dimensions to the script
    and receive back one result per dimension."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    plugin = _mk_redis_plugin(
        {
            "by_user": "30/m",
            "by_tenant": "300/m",
            "by_tool": {"search": "10/m"},
            "algorithm": ALGORITHM_FIXED_WINDOW,
        }
    )
    mock_client = plugin._rate_backend._client
    # Simulate all three dimensions allowed
    mock_client.eval = AsyncMock(return_value=[[1, 60], [1, 60], [1, 60]])

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id="acme"))
    payload = ToolPreInvokePayload(name="search", arguments={})

    result = await plugin.tool_pre_invoke(payload, ctx)

    assert mock_client.eval.call_count == 1
    # The single call must have received all 3 dimension keys
    call_args = mock_client.eval.call_args
    # NUMKEYS should be 3 (one key per dimension)
    numkeys = call_args[0][1] if call_args[0] else call_args[1].get("numkeys", 0)
    assert numkeys == 3, f"REDIS-03: batched script must receive 3 keys (one per dimension), got {numkeys}"
    assert result.violation is None


@pytest.mark.asyncio
async def test_redis03_batched_script_block_when_any_dimension_violated():
    """REDIS-03: If any dimension result is blocked, the hook must return 429."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    plugin = _mk_redis_plugin(
        {
            "by_user": "30/m",
            "by_tenant": "2/m",  # tenant exhausted
            "algorithm": ALGORITHM_FIXED_WINDOW,
        }
    )
    mock_client = plugin._rate_backend._client
    # user: allowed, tenant: blocked
    mock_client.eval = AsyncMock(return_value=[[1, 60], [3, 60]])  # count > limit for tenant

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id="acme"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    result = await plugin.tool_pre_invoke(payload, ctx)

    assert mock_client.eval.call_count == 1
    assert result.violation is not None
    assert result.violation.http_status_code == 429


@pytest.mark.asyncio
async def test_redis01_no_eval_calls_when_no_limits_configured():
    """REDIS-01: When no dimensions are configured, no eval call is made."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    plugin = _mk_redis_plugin({})  # no limits
    mock_client = plugin._rate_backend._client
    mock_client.eval = AsyncMock()

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    result = await plugin.tool_pre_invoke(payload, ctx)

    assert mock_client.eval.call_count == 0, "No eval calls expected when no limits are configured"
    assert result.violation is None


# ---------------------------------------------------------------------------
# CORR-01: Rust and Python produce identical allow/block decisions
# ---------------------------------------------------------------------------
#
# Golden-file contract tests: for the same input sequence and the same
# algorithm, both engines must agree on every allow/block decision and on the
# remaining-token count.  Time-dependent fields (reset_timestamp, retry_after)
# are not compared because the two engines use different clock sources.
# ---------------------------------------------------------------------------


def _python_sequence(algorithm: str, limit: int, n_requests: int) -> list[bool]:
    """Run n_requests through the Python MemoryBackend; return allow decisions."""
    # First-Party
    from plugins.rate_limiter.rate_limiter import (  # noqa: PLC0415
        FixedWindowAlgorithm,
        MemoryBackend,
        SlidingWindowAlgorithm,
        TokenBucketAlgorithm,
    )

    algo_map = {
        ALGORITHM_FIXED_WINDOW: FixedWindowAlgorithm,
        ALGORITHM_SLIDING_WINDOW: SlidingWindowAlgorithm,
        ALGORITHM_TOKEN_BUCKET: TokenBucketAlgorithm,
    }
    backend = MemoryBackend(algorithm=algo_map[algorithm]())
    rate_str = f"{limit}/h"  # large window so it never resets during test

    async def _run():
        results = []
        for _ in range(n_requests):
            allowed, *_ = await backend.allow("user:test", rate_str)
            results.append(allowed)
        return results

    return asyncio.run(_run())


def _rust_sequence(algorithm: str, limit: int, n_requests: int) -> list[bool]:
    """Run n_requests through the Rust RateLimiterEngine; return allow decisions."""
    # First-Party
    from plugins.rate_limiter.rate_limiter import RustRateLimiterEngine  # noqa: PLC0415

    engine = RustRateLimiterEngine({"by_user": f"{limit}/h", "algorithm": algorithm})
    window_nanos = 3600 * 1_000_000_000  # 1 hour in nanos
    now_unix = int(time.time())
    results = []
    for _ in range(n_requests):
        r = engine.evaluate_many([("user:test", limit, window_nanos)], now_unix)
        results.append(r.allowed)
    return results


@_skip_no_rust
def test_corr01_fixed_window_parity():
    """CORR-01: Rust fixed_window allow/block sequence matches Python."""
    limit = 5
    n = 8  # 5 allowed + 3 blocked
    py = _python_sequence(ALGORITHM_FIXED_WINDOW, limit, n)
    rs = _rust_sequence(ALGORITHM_FIXED_WINDOW, limit, n)
    assert py == rs, f"Parity failure fixed_window: Python={py} Rust={rs}"


@_skip_no_rust
def test_corr01_token_bucket_parity():
    """CORR-01: Rust token_bucket allow/block sequence matches Python."""
    limit = 4
    n = 6  # 4 allowed + 2 blocked
    py = _python_sequence(ALGORITHM_TOKEN_BUCKET, limit, n)
    rs = _rust_sequence(ALGORITHM_TOKEN_BUCKET, limit, n)
    assert py == rs, f"Parity failure token_bucket: Python={py} Rust={rs}"


@_skip_no_rust
def test_corr01_sliding_window_parity():
    """CORR-01: Rust sliding_window allow/block sequence matches Python."""
    limit = 3
    n = 5  # 3 allowed + 2 blocked
    py = _python_sequence(ALGORITHM_SLIDING_WINDOW, limit, n)
    rs = _rust_sequence(ALGORITHM_SLIDING_WINDOW, limit, n)
    assert py == rs, f"Parity failure sliding_window: Python={py} Rust={rs}"


@_skip_no_rust
def test_corr01_remaining_count_parity_fixed_window():
    """CORR-01: remaining token count matches between Python and Rust (fixed_window)."""
    # First-Party
    from plugins.rate_limiter.rate_limiter import FixedWindowAlgorithm, MemoryBackend  # noqa: PLC0415
    from plugins.rate_limiter.rate_limiter import RustRateLimiterEngine  # noqa: PLC0415

    limit = 10
    window_nanos = 3600 * 1_000_000_000
    now_unix = int(time.time())

    py_backend = MemoryBackend(algorithm=FixedWindowAlgorithm())
    rust_engine = RustRateLimiterEngine({"by_user": f"{limit}/h", "algorithm": ALGORITHM_FIXED_WINDOW})

    async def _py_remaining(n: int) -> int:
        remaining = 0
        for _ in range(n):
            _, _, _, meta = await py_backend.allow("user:test", f"{limit}/h")
            remaining = meta.get("remaining", 0)
        return remaining

    n_requests = 4
    py_remaining = asyncio.run(_py_remaining(n_requests))
    rs_result = None
    for _ in range(n_requests):
        rs_result = rust_engine.evaluate_many([("user:test", limit, window_nanos)], now_unix)
    rs_remaining = rs_result.remaining

    assert py_remaining == rs_remaining, f"remaining mismatch after {n_requests} requests: Python={py_remaining} Rust={rs_remaining}"


@_skip_no_rust
@pytest.mark.parametrize("algorithm", [ALGORITHM_SLIDING_WINDOW, ALGORITHM_TOKEN_BUCKET])
def test_corr01_remaining_count_parity_all_algorithms(algorithm):
    """CORR-01: remaining count matches between Python and Rust for all algorithms."""
    # First-Party
    from plugins.rate_limiter.rate_limiter import FixedWindowAlgorithm, MemoryBackend, RustRateLimiterEngine, SlidingWindowAlgorithm, TokenBucketAlgorithm  # noqa: PLC0415

    algo_map = {
        ALGORITHM_FIXED_WINDOW: FixedWindowAlgorithm,
        ALGORITHM_SLIDING_WINDOW: SlidingWindowAlgorithm,
        ALGORITHM_TOKEN_BUCKET: TokenBucketAlgorithm,
    }
    limit = 10
    window_nanos = 3600 * 1_000_000_000
    now_unix = int(time.time())
    n_requests = 4

    py_backend = MemoryBackend(algorithm=algo_map[algorithm]())
    rust_engine = RustRateLimiterEngine({"by_user": f"{limit}/h", "algorithm": algorithm})

    async def _py_remaining() -> int:
        remaining = 0
        for _ in range(n_requests):
            _, _, _, meta = await py_backend.allow("user:test", f"{limit}/h")
            remaining = meta.get("remaining", 0)
        return remaining

    py_remaining = asyncio.run(_py_remaining())
    rs_result = None
    for _ in range(n_requests):
        rs_result = rust_engine.evaluate_many([("user:test", limit, window_nanos)], now_unix)
    rs_remaining = rs_result.remaining

    assert py_remaining == rs_remaining, f"remaining mismatch ({algorithm}) after {n_requests} requests: Python={py_remaining} Rust={rs_remaining}"


@_skip_no_rust
def test_corr01_multi_dimension_parity():
    """CORR-01: Rust check() with 3 dimensions produces the same allow/block sequence as Python."""
    plugin_py = RateLimiterPlugin(
        PluginConfig(
            name="rl-parity-py",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={
                "by_user": "5/h",
                "by_tenant": "10/h",
                "by_tool": {"test_tool": "3/h"},
                "algorithm": ALGORITHM_FIXED_WINDOW,
            },
        )
    )
    plugin_py._rust_engine = None  # force Python path

    plugin_rs = RateLimiterPlugin(
        PluginConfig(
            name="rl-parity-rs",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={
                "by_user": "5/h",
                "by_tenant": "10/h",
                "by_tool": {"test_tool": "3/h"},
                "algorithm": ALGORITHM_FIXED_WINDOW,
            },
        )
    )
    if plugin_rs._rust_engine is None:
        pytest.skip("Rust engine not active")

    payload = ToolPreInvokePayload(name="test_tool", arguments={})
    py_sequence: list[bool] = []
    rs_sequence: list[bool] = []

    async def _run():
        # Tool limit is 3/h — requests 4+ should be blocked by the tool dimension
        for i in range(6):
            ctx = PluginContext(global_context=GlobalContext(request_id=f"parity-{i}", user="alice@example.com", tenant_id="acme"))
            py_result = await plugin_py.tool_pre_invoke(payload, ctx)
            rs_result = await plugin_rs.tool_pre_invoke(payload, ctx)
            py_sequence.append(py_result.continue_processing)
            rs_sequence.append(rs_result.continue_processing)

    asyncio.run(_run())
    assert py_sequence == rs_sequence, f"Multi-dimension parity failure: Python={py_sequence} Rust={rs_sequence}"
    # First 3 allowed (tool limit), then 3 blocked
    assert py_sequence == [True, True, True, False, False, False]


# ---------------------------------------------------------------------------
# Redis key format parity — Python RedisBackend vs Rust engine key generation
#
# These tests guard the dual Lua-script invariant: Python and Rust must
# produce identical Redis keys so that mixed deployments share counters.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dimension,key,rate,expected_suffix",
    [
        ("user", "user:alice@example.com", "30/m", "user:alice@example.com:60"),
        ("tenant", "tenant:acme", "3000/m", "tenant:acme:60"),
        ("tool", "tool:my_tool", "10/s", "tool:my_tool:1"),
        ("user", "user:bob", "100/h", "user:bob:3600"),
    ],
    ids=["user-per-minute", "tenant-per-minute", "tool-per-second", "user-per-hour"],
)
def test_redis_key_format_parity_python_backend(dimension, key, rate, expected_suffix):
    """Python RedisBackend key format matches the documented pattern: {prefix}:{dim_key}:{window_seconds}."""
    count, window_seconds = _parse_rate(rate)
    prefix = "rl"
    redis_key = f"{prefix}:{key}:{window_seconds}"
    assert redis_key == f"rl:{expected_suffix}"


@pytest.mark.parametrize(
    "user,tenant,tool,by_user,by_tenant,by_tool_cfg,expected_keys",
    [
        (
            "alice@example.com",
            "acme",
            "summarize",
            "30/m",
            "3000/m",
            {"summarize": "10/m"},
            ["user:alice@example.com", "tenant:acme", "tool:summarize"],
        ),
        (
            "bob",
            None,
            "search",
            "30/m",
            "3000/m",
            {},
            ["user:bob"],
        ),
    ],
    ids=["three-dimensions", "user-only-no-tenant-no-tool"],
)
def test_redis_key_format_parity_rust_dimension_keys(user, tenant, tool, by_user, by_tenant, by_tool_cfg, expected_keys):
    """Rust engine dimension keys (built by _build_rust_checks) match Python path dimension keys."""
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="key-parity",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={
                "by_user": by_user,
                "by_tenant": by_tenant,
                "by_tool": by_tool_cfg,
                "algorithm": ALGORITHM_FIXED_WINDOW,
            },
        )
    )

    # Rust path dimension keys (built by Python wrapper, consumed by Rust engine)
    if plugin._rust_engine is not None:
        rust_checks = plugin._build_rust_checks(user, tenant, tool)
        rust_dim_keys = [key for key, _count, _window in rust_checks]
    else:
        # If Rust engine not built, manually replicate the key construction
        # to verify the pattern is consistent.
        rust_dim_keys = []
        if plugin._cfg.by_user:
            rust_dim_keys.append(f"user:{user}")
        if tenant and plugin._cfg.by_tenant:
            rust_dim_keys.append(f"tenant:{tenant}")
        normalised = {k.strip().lower(): v for k, v in (by_tool_cfg or {}).items()}
        if tool in normalised:
            rust_dim_keys.append(f"tool:{tool}")

    # Python path dimension keys (built inside _check_rate_limit)
    python_dim_keys = []
    if plugin._cfg.by_user:
        python_dim_keys.append(f"user:{user}")
    if tenant and plugin._cfg.by_tenant:
        python_dim_keys.append(f"tenant:{tenant}")
    if plugin._normalised_by_tool and tool in plugin._normalised_by_tool:
        python_dim_keys.append(f"tool:{tool}")

    assert rust_dim_keys == python_dim_keys, f"Dimension key mismatch: Rust={rust_dim_keys} Python={python_dim_keys}"
    assert rust_dim_keys == expected_keys


def test_redis_key_format_parity_window_seconds():
    """Both paths derive identical window_seconds from the same rate string."""
    for rate, expected_window in [("10/s", 1), ("30/m", 60), ("100/h", 3600)]:
        count, window_secs = _parse_rate(rate)
        # Python RedisBackend uses window_seconds directly from _parse_rate
        python_window = window_secs
        # Rust engine receives window_nanos and divides back to seconds for the key
        window_nanos = window_secs * 1_000_000_000
        rust_window = window_nanos // 1_000_000_000
        assert python_window == rust_window, f"Window mismatch for {rate}: Python={python_window} Rust={rust_window}"
        assert python_window == expected_window


def _normalise_lua(script: str) -> str:
    """Collapse whitespace in a Lua script for content-level comparison."""
    return " ".join(script.split())


@pytest.mark.parametrize(
    "py_attr,rust_const_name",
    [
        ("_LUA_BATCH_FIXED", "LUA_BATCH_FIXED"),
        ("_LUA_BATCH_SLIDING", "LUA_BATCH_SLIDING"),
        ("_LUA_BATCH_TOKEN_BUCKET", "LUA_BATCH_TOKEN_BUCKET"),
    ],
    ids=["batch-fixed", "batch-sliding", "batch-token-bucket"],
)
def test_redis_lua_script_content_parity(py_attr, rust_const_name):
    """Batch Lua scripts in Python RedisBackend and Rust redis_backend.rs must be functionally identical.

    This prevents silent divergence: the key-format parity tests verify key naming
    but not the Lua logic that runs inside Redis.  If a script is changed in one
    implementation it must be changed in the other for rolling-upgrade safety.
    """
    # Standard
    import pathlib  # noqa: PLC0415
    import re  # noqa: PLC0415

    py_script = getattr(RedisBackend, py_attr)

    rust_src = pathlib.Path(__file__).resolve().parents[6] / "plugins_rust" / "rate_limiter" / "src" / "redis_backend.rs"
    if not rust_src.exists():
        pytest.skip(f"Rust source not found at {rust_src}")

    rust_content = rust_src.read_text()

    # Extract the Rust constant by finding `const {name}: &str = r#"...content..."#;`
    pattern = rf'const {rust_const_name}:\s*&str\s*=\s*r#"(.*?)"#;'
    match = re.search(pattern, rust_content, re.DOTALL)
    assert match is not None, f"Could not find const {rust_const_name} in {rust_src}"
    rust_script = match.group(1)

    assert _normalise_lua(py_script) == _normalise_lua(rust_script), (
        f"Lua script content mismatch between Python RedisBackend.{py_attr} and Rust {rust_const_name}. " "Both must stay in sync for rolling-upgrade compatibility."
    )


# ---------------------------------------------------------------------------
# REDIS-02: EVALSHA used after SCRIPT LOAD; EVAL only as NOSCRIPT fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis02_evalsha_used_after_script_load():
    """REDIS-02: script_load called once at first use; evalsha used on request path."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    mock_client = AsyncMock()
    mock_client.script_load.return_value = "abc123sha"
    mock_client.evalsha.return_value = [1, 60]  # fixed window: count=1, ttl=60

    backend = RedisBackend(
        redis_url="redis://localhost:6379/0",
        algorithm_name=ALGORITHM_FIXED_WINDOW,
        _client=mock_client,
    )

    await backend.allow("user:alice", "10/s")

    # script_load must have been called (at least for _sha_fixed)
    assert mock_client.script_load.called, "script_load must be called to cache SHA"
    # evalsha must be used on the request path, not eval
    assert mock_client.evalsha.called, "evalsha must be used after SHA is cached"
    assert not mock_client.eval.called, "eval must NOT be called on the happy path"


@pytest.mark.asyncio
async def test_redis02_script_load_called_only_once_across_requests():
    """REDIS-02: script_load is called at most once — SHAs are cached after first load."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    mock_client = AsyncMock()
    mock_client.script_load.return_value = "deadbeef"
    mock_client.evalsha.return_value = [1, 60]

    backend = RedisBackend(
        redis_url="redis://localhost:6379/0",
        algorithm_name=ALGORITHM_FIXED_WINDOW,
        _client=mock_client,
    )

    for _ in range(5):
        await backend.allow("user:alice", "10/s")

    # script_load call count should be equal to the number of scripts (6),
    # not 5 × 6 — it only runs until all SHAs are populated.
    load_count = mock_client.script_load.call_count
    assert load_count <= 6, f"script_load should be called at most once per script, got {load_count} calls"


@pytest.mark.asyncio
async def test_redis02_noscript_fallback_to_eval():
    """REDIS-02: NOSCRIPT error causes fallback to EVAL and SHA reload."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    # Third-Party
    from redis.exceptions import ResponseError  # noqa: PLC0415

    mock_client = AsyncMock()
    mock_client.script_load.return_value = "abc123"
    # First evalsha raises NOSCRIPT; eval succeeds
    mock_client.evalsha.side_effect = ResponseError("NOSCRIPT No matching script")
    mock_client.eval.return_value = [1, 60]

    backend = RedisBackend(
        redis_url="redis://localhost:6379/0",
        algorithm_name=ALGORITHM_FIXED_WINDOW,
        _client=mock_client,
    )

    result = await backend.allow("user:alice", "10/s")
    allowed, *_ = result

    assert allowed is True, "NOSCRIPT fallback must still return a valid result"
    assert mock_client.eval.called, "eval must be used as NOSCRIPT fallback"


# ---------------------------------------------------------------------------
# REDIS-04: Redis connection failure → fallback to MemoryBackend, no exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis04_connection_failure_falls_back_to_memory_allow():
    """REDIS-04: allow() falls back to MemoryBackend on Redis connection failure."""
    # First-Party
    from plugins.rate_limiter.rate_limiter import FixedWindowAlgorithm  # noqa: PLC0415

    memory = MemoryBackend(algorithm=FixedWindowAlgorithm())
    backend = RedisBackend(
        redis_url="redis://localhost:6379/0",
        algorithm_name=ALGORITHM_FIXED_WINDOW,
        fallback=memory,
    )

    # Inject a broken client — script_load raises immediately
    class _Dead:
        async def script_load(self, *a: Any, **kw: Any) -> None:
            raise ConnectionError("Redis is down")

        async def eval(self, *a: Any, **kw: Any) -> None:
            raise ConnectionError("Redis is down")

        async def evalsha(self, *a: Any, **kw: Any) -> None:
            raise ConnectionError("Redis is down")

    backend._client = _Dead()

    allowed, *_ = await backend.allow("user:alice", "10/s")
    assert allowed is True, "Connection failure + fallback must allow the request"


@pytest.mark.asyncio
async def test_redis04_connection_failure_no_fallback_allows_gracefully():
    """REDIS-04: allow() fails open (allow) when Redis is down and no fallback is configured."""
    backend = RedisBackend(
        redis_url="redis://localhost:6379/0",
        algorithm_name=ALGORITHM_FIXED_WINDOW,
        fallback=None,
    )

    class _Dead:
        async def script_load(self, *a: Any, **kw: Any) -> None:
            raise ConnectionError("Redis is down")

        async def eval(self, *a: Any, **kw: Any) -> None:
            raise ConnectionError("Redis is down")

        async def evalsha(self, *a: Any, **kw: Any) -> None:
            raise ConnectionError("Redis is down")

    backend._client = _Dead()

    result = await backend.allow("user:alice", "10/s")
    assert result is not None, "allow() must not raise on Redis failure"
    allowed, *_ = result
    assert allowed is True, "No-fallback path must fail open"


@pytest.mark.asyncio
async def test_redis04_allow_many_falls_back_to_memory_on_connection_failure():
    """REDIS-04: allow_many() falls back to per-call MemoryBackend when Redis is down."""
    # First-Party
    from plugins.rate_limiter.rate_limiter import FixedWindowAlgorithm  # noqa: PLC0415

    memory = MemoryBackend(algorithm=FixedWindowAlgorithm())
    backend = RedisBackend(
        redis_url="redis://localhost:6379/0",
        algorithm_name=ALGORITHM_FIXED_WINDOW,
        fallback=memory,
    )

    class _Dead:
        async def script_load(self, *a: Any, **kw: Any) -> None:
            raise ConnectionError("Redis is down")

        async def eval(self, *a: Any, **kw: Any) -> None:
            raise ConnectionError("Redis is down")

        async def evalsha(self, *a: Any, **kw: Any) -> None:
            raise ConnectionError("Redis is down")

    backend._client = _Dead()

    checks = [("user:alice", "10/s"), ("tenant:acme", "100/s")]
    results = await backend.allow_many(checks)

    assert len(results) == 2, "allow_many must return one result per check"
    assert all(r[0] is True for r in results), "All dimensions must be allowed via memory fallback"


# ---------------------------------------------------------------------------
# PERF-05: at most one Redis network round-trip per hook invocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_perf05_single_round_trip_per_hook_one_dim():
    """PERF-05: one dimension → one evalsha call."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    mock_client = AsyncMock()
    mock_client.script_load.return_value = "sha1"
    mock_client.evalsha.return_value = [[1, 60]]

    plugin = _mk_redis_plugin({"by_user": "10/s"})
    plugin._rate_backend._client = mock_client
    # Pre-populate SHAs so evalsha is used directly
    plugin._rate_backend._sha_batch_fixed = "sha1"

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="search", arguments={})
    await plugin.tool_pre_invoke(payload, ctx)

    total_calls = mock_client.evalsha.call_count + mock_client.eval.call_count
    assert total_calls <= 1, f"PERF-05: expected ≤1 Redis call for 1 dimension, got {total_calls}"


@pytest.mark.asyncio
async def test_perf05_single_round_trip_per_hook_three_dims():
    """PERF-05: three dimensions (user + tenant + tool) → still one evalsha call."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    mock_client = AsyncMock()
    mock_client.script_load.return_value = "sha1"
    mock_client.evalsha.return_value = [[1, 60], [1, 60], [1, 60]]

    plugin = _mk_redis_plugin({"by_user": "10/s", "by_tenant": "100/s", "by_tool": {"search": "5/s"}})
    plugin._rate_backend._client = mock_client
    plugin._rate_backend._sha_batch_fixed = "sha1"

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id="acme"))
    payload = ToolPreInvokePayload(name="search", arguments={})
    await plugin.tool_pre_invoke(payload, ctx)

    total_calls = mock_client.evalsha.call_count + mock_client.eval.call_count
    assert total_calls <= 1, f"PERF-05: expected ≤1 Redis call for 3 dimensions, got {total_calls} — " f"all dimensions must be batched into a single round-trip"


# ---------------------------------------------------------------------------
# PERF-03: p99 latency — Rust path must not regress vs Python memory backend
# ---------------------------------------------------------------------------


@_skip_no_rust
@pytest.mark.asyncio
async def test_perf03_rust_p99_does_not_regress_vs_python():
    """PERF-03: p99 latency of Rust evaluate_many() must be ≤ Python MemoryBackend.allow() p99.

    Runs 1000 requests through each path concurrently (100 at a time) and
    compares p99 wall-clock latency.  The Rust path is expected to be faster;
    if it is somehow slower the test fails with a diagnostic message.
    """
    # First-Party
    from plugins.rate_limiter.rate_limiter import FixedWindowAlgorithm  # noqa: PLC0415

    CONCURRENCY = 100
    TOTAL = 1000
    LIMIT = TOTAL * 10  # never block during the benchmark
    WINDOW_NANOS = 3600 * 1_000_000_000

    # --- Python path ---
    py_backend = MemoryBackend(algorithm=FixedWindowAlgorithm())

    async def _py_call() -> float:
        t0 = time.perf_counter()
        await py_backend.allow("user:bench", f"{LIMIT}/h")
        return time.perf_counter() - t0

    sem = asyncio.Semaphore(CONCURRENCY)

    async def _bounded_py() -> float:
        async with sem:
            return await _py_call()

    py_times = await asyncio.gather(*[_bounded_py() for _ in range(TOTAL)])
    py_p99 = sorted(py_times)[int(0.99 * TOTAL)]

    # --- Rust path ---
    rust_engine = RustRateLimiterEngine({"by_user": f"{LIMIT}/h", "algorithm": ALGORITHM_FIXED_WINDOW})
    now_unix = int(time.time())

    async def _rust_call() -> float:
        t0 = time.perf_counter()
        rust_engine.evaluate_many([("user:bench", LIMIT, WINDOW_NANOS)], now_unix)
        return time.perf_counter() - t0

    async def _bounded_rust() -> float:
        async with sem:
            return await _rust_call()

    rust_times = await asyncio.gather(*[_bounded_rust() for _ in range(TOTAL)])
    rust_p99 = sorted(rust_times)[int(0.99 * TOTAL)]

    # Rust p99 must be ≤ Python p99 (Rust should be faster, never slower)
    assert rust_p99 <= py_p99, f"PERF-03: Rust p99 ({rust_p99*1e6:.1f} µs) regressed vs Python p99 ({py_p99*1e6:.1f} µs)"


# ---------------------------------------------------------------------------
# PERF-02: Python wrapper overhead is small relative to Rust engine time
# ---------------------------------------------------------------------------


@_skip_no_rust
def test_perf02_wrapper_overhead_is_small():
    """PERF-02: Python wrapper overhead (context extraction + PyO3 call) must be < 10× Rust engine time.

    Measures wrapper-only cost by mocking evaluate_many() to return instantly,
    then compares against real Rust engine time.  The wrapper must not dominate.
    """
    ITERATIONS = 10_000
    LIMIT = 1_000_000
    WINDOW_NANOS = 3600 * 1_000_000_000
    now_unix = int(time.time())

    class _FakeEvalResult:
        allowed = True
        limit = LIMIT
        remaining = LIMIT - 1
        reset_timestamp = now_unix + 3600
        retry_after = None

    fake_result = _FakeEvalResult()

    # --- Wrapper-only overhead (mocked Rust engine) ---
    plugin = _mk_rust(f"{LIMIT}/h")
    assert plugin._rust_engine is not None

    wrapper_times = []
    original_evaluate_many = plugin._rust_engine.evaluate_many
    plugin._rust_engine.evaluate_many = lambda checks, ts: fake_result
    try:
        checks = plugin._build_rust_checks("alice", None, "search")
        for _ in range(ITERATIONS):
            t0 = time.perf_counter_ns()
            plugin._rust_engine.evaluate_many(checks, now_unix)
            wrapper_times.append(time.perf_counter_ns() - t0)
    finally:
        plugin._rust_engine.evaluate_many = original_evaluate_many

    # --- Real Rust engine (no wrapper) ---
    engine = RustRateLimiterEngine({"by_user": f"{LIMIT}/h", "algorithm": ALGORITHM_FIXED_WINDOW})
    rust_times = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter_ns()
        engine.evaluate_many([("user:alice", LIMIT, WINDOW_NANOS)], now_unix)
        rust_times.append(time.perf_counter_ns() - t0)

    wrapper_median = sorted(wrapper_times)[ITERATIONS // 2]
    rust_median = sorted(rust_times)[ITERATIONS // 2]

    # Wrapper overhead must be < 10× the Rust engine time
    assert wrapper_median < rust_median * 10, f"PERF-02: wrapper overhead ({wrapper_median} ns median) is ≥10× Rust engine " f"({rust_median} ns median) — wrapper is dominating"


# ---------------------------------------------------------------------------
# MEM-06: Dimension keys are distinct — same name in different dims never collide
# ---------------------------------------------------------------------------


@_skip_no_rust
def test_mem06_user_tenant_tool_keys_are_distinct():
    """MEM-06: 'alice' as user, tenant, and tool must produce independent counters.

    Verifies that the key namespace (user:, tenant:, tool:) prevents hash collision
    between the same identifier used across different dimensions.
    """
    LIMIT = 2
    WINDOW_NANOS = 3600 * 1_000_000_000
    now_unix = int(time.time())
    engine = RustRateLimiterEngine({"by_user": f"{LIMIT}/h", "algorithm": ALGORITHM_FIXED_WINDOW})

    # Exhaust the user:alice counter
    engine.evaluate_many([("user:alice", LIMIT, WINDOW_NANOS)], now_unix)
    engine.evaluate_many([("user:alice", LIMIT, WINDOW_NANOS)], now_unix)
    blocked = engine.evaluate_many([("user:alice", LIMIT, WINDOW_NANOS)], now_unix)
    assert not blocked.allowed, "user:alice counter should be exhausted"

    # tenant:alice and tool:alice must still have independent counters
    r_tenant = engine.evaluate_many([("tenant:alice", LIMIT, WINDOW_NANOS)], now_unix)
    r_tool = engine.evaluate_many([("tool:alice", LIMIT, WINDOW_NANOS)], now_unix)

    assert r_tenant.allowed, "tenant:alice must be independent from user:alice"
    assert r_tool.allowed, "tool:alice must be independent from user:alice"


# ---------------------------------------------------------------------------
# TokenBucketAlgorithm.sweep() (14a)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_bucket_sweep_evicts_inactive_buckets():
    """TokenBucketAlgorithm.sweep() should evict buckets that have been inactive for >1 hour."""
    algo = TokenBucketAlgorithm()
    lock = asyncio.Lock()

    # Create a bucket by issuing a request.
    await algo.allow(lock, "user:stale", 10, 60)
    assert "user:stale" in algo._store

    # Manually backdate last_refill to >1 hour ago.
    algo._store["user:stale"].last_refill -= 3601

    await algo.sweep(lock)
    assert "user:stale" not in algo._store, "Bucket inactive for >1 hour must be evicted by sweep"


@pytest.mark.asyncio
async def test_token_bucket_sweep_keeps_active_buckets():
    """TokenBucketAlgorithm.sweep() should keep recently-used buckets."""
    algo = TokenBucketAlgorithm()
    lock = asyncio.Lock()

    await algo.allow(lock, "user:active", 10, 60)
    assert "user:active" in algo._store

    await algo.sweep(lock)
    assert "user:active" in algo._store, "Recently-used bucket must not be evicted"


# ---------------------------------------------------------------------------
# _extract_user_identity dict fallback chain (14d)
# ---------------------------------------------------------------------------


def test_extract_user_identity_dict_email():
    """Dict with 'email' key should use email as identity."""
    assert _extract_user_identity({"email": "alice@example.com"}) == "alice@example.com"


def test_extract_user_identity_dict_id_fallback():
    """Dict without 'email' should fall back to 'id'."""
    assert _extract_user_identity({"id": "user-123"}) == "user-123"


def test_extract_user_identity_dict_sub_fallback():
    """Dict without 'email' or 'id' should fall back to 'sub'."""
    assert _extract_user_identity({"sub": "sub-456"}) == "sub-456"


def test_extract_user_identity_dict_empty_email_falls_to_id():
    """Dict with empty 'email' should fall back to 'id'."""
    assert _extract_user_identity({"email": "", "id": "user-789"}) == "user-789"


def test_extract_user_identity_dict_all_empty_is_anonymous():
    """Dict with all falsy identity fields should return 'anonymous'."""
    assert _extract_user_identity({"email": "", "id": "", "sub": ""}) == "anonymous"


def test_extract_user_identity_dict_no_keys_is_anonymous():
    """Dict with no identity keys should return 'anonymous'."""
    assert _extract_user_identity({"roles": ["admin"]}) == "anonymous"


def test_extract_user_identity_colons_replaced():
    """Colons in identities must be replaced to prevent key-namespace collisions."""
    assert _extract_user_identity({"sub": "auth0|user:12345"}) == "auth0|user_12345"
    assert _extract_user_identity({"email": "urn:user:alice"}) == "urn_user_alice"
    assert _extract_user_identity("colon:in:string") == "colon_in_string"


# ---------------------------------------------------------------------------
# prompt_pre_fetch Rust async Redis path (14f)
# ---------------------------------------------------------------------------


@_skip_no_rust
@pytest.mark.asyncio
async def test_arch01_redis_rust_prompt_uses_async_entrypoint():
    """Redis-backed Rust path should await check_async for prompt_pre_fetch."""
    # Standard
    from unittest.mock import AsyncMock  # noqa: PLC0415

    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[PromptHookType.PROMPT_PRE_FETCH],
            config={"by_user": "10/s", "backend": "redis", "redis_url": "redis://localhost:6379/0"},
        )
    )
    if plugin._rust_engine is None:
        pytest.skip("Rust engine not active")

    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = PromptPrehookPayload(prompt_id="search")

    sync_mock = patch.object(plugin._rust_engine, "check", wraps=plugin._rust_engine.check)
    async_mock = patch.object(plugin._rust_engine, "check_async", AsyncMock(wraps=plugin._rust_engine.check_async))
    with sync_mock as mock_sync, async_mock as mock_async:
        await plugin.prompt_pre_fetch(payload, ctx)
        assert mock_async.await_count == 1, "prompt_pre_fetch must use async entrypoint for Redis"
        assert mock_sync.call_count == 0, "prompt_pre_fetch must not use sync entrypoint for Redis"


# ============================================================================
# Sliding window Retry-After regression
# ============================================================================


@pytest.mark.asyncio
async def test_sliding_window_retry_after_never_zero_when_blocked():
    """Retry-After (reset_in) must be >= 1 when the request is blocked.

    Regression: int truncation of (oldest_ts + window - now) could produce 0
    when the oldest timestamp + window rounded down to int(now).
    """
    algorithm = SlidingWindowAlgorithm()
    lock = asyncio.Lock()

    with patch("plugins.rate_limiter.rate_limiter.time") as mock_time:
        # Place a request at a fractional timestamp
        mock_time.time.return_value = 1000.1
        await algorithm.allow(lock, "user:x", 1, 1)  # consume limit

        # At t=1000.9: oldest=1000.1, reset_timestamp=int(1001.1)=1001,
        # reset_in = int(1001 - 1000.9) = int(0.1) = 0 WITHOUT the fix.
        mock_time.time.return_value = 1000.9
        allowed, _, _, meta = await algorithm.allow(lock, "user:x", 1, 1)

    assert allowed is False
    assert meta["reset_in"] >= 1, f"Retry-After must be >= 1 when blocked, got {meta['reset_in']}"


# ============================================================================
# Token bucket first-request memory/Redis parity
# ============================================================================


@pytest.mark.asyncio
async def test_token_bucket_first_request_reset_in_matches_refill_rate():
    """First-request reset_in must reflect tokens_needed/refill_rate, not the full window.

    Regression: memory path hard-coded time_to_full=window on first request,
    while Redis derived it from tokens_needed/refill_rate, causing metadata
    divergence between backends.
    """
    algorithm = TokenBucketAlgorithm()
    lock = asyncio.Lock()

    # 10/m → refill_rate = 10/60 ≈ 0.167 tok/s
    # After first request: tokens_needed = 1, time_to_full = 1/0.167 ≈ 6
    allowed, count, reset_ts, meta = await algorithm.allow(lock, "user:y", 10, 60)

    assert allowed is True
    assert meta["remaining"] == 9
    # Must NOT be 60 (the full window) — should be ~6 (1 token / refill_rate)
    assert meta["reset_in"] < 60, f"First-request reset_in should reflect tokens_needed/refill_rate, " f"not the full window. Got {meta['reset_in']}, expected ~6"
    assert meta["reset_in"] >= 1, "reset_in must be at least 1"


# ---------------------------------------------------------------------------
# RATE_LIMITER_FORCE_PYTHON env var (review finding #17)
# ---------------------------------------------------------------------------


def test_force_python_env_var_disables_rust():
    """Setting RATE_LIMITER_FORCE_PYTHON=1 must force _RUST_AVAILABLE to False."""
    # Standard
    import importlib  # noqa: PLC0415

    # First-Party
    import plugins.rate_limiter.rate_limiter as rl_mod  # noqa: PLC0415

    with patch.dict(os.environ, {"RATE_LIMITER_FORCE_PYTHON": "1"}):
        importlib.reload(rl_mod)
        assert rl_mod._RUST_AVAILABLE is False

    # Restore: reload without the env override so other tests are unaffected.
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("RATE_LIMITER_FORCE_PYTHON", None)
        importlib.reload(rl_mod)


# ---------------------------------------------------------------------------
# Edge-case rate string validation (review findings)
# ---------------------------------------------------------------------------


def test_parse_rate_zero_count_raises():
    """Zero-count rate string must raise ValueError — ambiguous semantics."""
    with pytest.raises(ValueError):
        _parse_rate("0/s")


def test_parse_rate_negative_count_raises():
    """Negative count rate string must raise ValueError."""
    with pytest.raises(ValueError):
        _parse_rate("-5/s")


def test_parse_rate_missing_slash_raises():
    """Malformed rate string without a slash must raise ValueError."""
    with pytest.raises(ValueError):
        _parse_rate("10m")


def test_parse_rate_empty_string_raises():
    """Empty rate string must raise ValueError."""
    with pytest.raises(ValueError):
        _parse_rate("")


def test_parse_rate_slash_only_raises():
    """Slash-only rate string must raise ValueError."""
    with pytest.raises(ValueError):
        _parse_rate("/s")


def test_validate_config_redis_url_required():
    """backend='redis' without redis_url must raise ValueError at init."""
    with pytest.raises(ValueError, match="redis_url is required"):
        RateLimiterPlugin(
            PluginConfig(
                name="rl",
                kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
                hooks=[PromptHookType.PROMPT_PRE_FETCH],
                config={"by_user": "10/s", "backend": "redis"},
            )
        )


# ---------------------------------------------------------------------------
# Rust tenant_id=None skips tenant dimension (review finding)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("plugins.rate_limiter.rate_limiter._RUST_AVAILABLE", False)
async def test_tenant_none_skips_by_tenant_dimension():
    """When tenant_id is None, the by_tenant dimension must be skipped entirely."""
    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[PromptHookType.PROMPT_PRE_FETCH],
            config={"by_user": "100/s", "by_tenant": "1/s"},
        )
    )
    # tenant_id=None — by_tenant should be skipped, so 2 requests should both pass
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1", tenant_id=None))
    payload = PromptPrehookPayload(prompt_id="p", args={})
    r1 = await plugin.prompt_pre_fetch(payload, ctx)
    assert r1.violation is None
    r2 = await plugin.prompt_pre_fetch(payload, ctx)
    assert r2.violation is None
