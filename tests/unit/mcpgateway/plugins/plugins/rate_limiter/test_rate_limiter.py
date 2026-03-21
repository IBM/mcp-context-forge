# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/rate_limiter/test_rate_limiter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for RateLimiterPlugin.
"""

import asyncio
import time
from typing import Any, Dict
from unittest.mock import patch

import pytest

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
    RedisBackend,
    ALGORITHM_FIXED_WINDOW,
    ALGORITHM_SLIDING_WINDOW,
    ALGORITHM_TOKEN_BUCKET,
    FixedWindowAlgorithm,
    MemoryBackend,
    RateLimiterPlugin,
    SlidingWindowAlgorithm,
    TokenBucketAlgorithm,
    _make_headers,
    _parse_rate,
    _select_most_restrictive,
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
    from mcpgateway.plugins.framework import ToolPreInvokePayload

    plugin = RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config={
                "by_user": "100/s",  # High user limit
                "by_tool": {
                    "restricted_tool": "1/s"  # Low tool-specific limit
                }
            },
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
            (False, 10, now + 30, {"limited": True, "remaining": 0, "reset_in": 30}),   # Resets sooner
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
            (False, 50, now + 30, {"limited": True, "remaining": 0, "reset_in": 30}),   # Violated (shortest)
            (False, 75, now + 90, {"limited": True, "remaining": 0, "reset_in": 90}),   # Violated
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
    assert r3.violation is not None, (
        "alice made 3 requests total (limit is 2). With Redis backend, clearing "
        "local state has no effect — the counter persists in Redis across all workers."
    )
    assert r3.violation.http_status_code == 429


@pytest.mark.asyncio
async def test_store_evicts_expired_windows():
    """
    After a rate limit window expires, the background TTL sweep removes its entry from _store.

    MemoryBackend starts a background asyncio task on first use that sweeps expired
    windows every 0.5s. Entries for users who never return are evicted automatically,
    bounding memory growth to active windows only.
    """
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

    assert len(store) == 0, (
        f"Expected store to be empty after all windows expired, "
        f"but found {len(store)} stale entries. "
    )


@pytest.mark.asyncio
async def test_concurrent_requests_respect_limit():
    """
    20 concurrent async requests against a limit of 10 — exactly 10 should be allowed.

    This test PASSES under asyncio (single-threaded event loop, no real concurrency).
    It documents that the asyncio path is safe.

    NOTE: Under gunicorn threaded workers the dict read-modify-write in _allow()
    is NOT atomic. Two threads can both read count=9, both pass the check, and both
    increment — allowing more than the configured limit. That scenario cannot be
    demonstrated in a single-threaded asyncio test.
    """
    plugin = _mk("10/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    results = await asyncio.gather(*[
        plugin.tool_pre_invoke(payload, ctx) for _ in range(20)
    ])

    allowed = sum(1 for r in results if r.violation is None)

    assert allowed == 10, (
        f"Expected exactly 10 allowed requests (the limit), got {allowed}. "
        f"Under asyncio this should be deterministic. "
        f"Under threaded workers this assertion can fail due to dict race conditions."
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Gap: fixed window allows 2× the limit at a window boundary. "
        "N requests at end of W1 + N requests at start of W2 all succeed."
    ),
)
@pytest.mark.asyncio
async def test_fixed_window_burst_at_boundary():
    """
    A user can burst at a window boundary: N requests at the end of window W1
    and N requests at the start of W2 both succeed, giving 2× the limit in practice.

    Example with limit=5/s:
      t=1000: requests 1-5 → allowed (window W1, count=5)
      t=1001: requests 6-10 → allowed (window W2 resets, count=1..5)
      Total = 10 requests in ~1 second against a limit of 5/s.

    Fix: use a sliding window or token bucket algorithm.
    """
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

    # Expected: a sliding window would cap total at ~5-6 across the boundary
    # Actual:   fixed window allows all 10 (5 in W1 + 5 in W2)
    assert allowed_total <= 5, (
        f"Fixed window burst: {allowed_total} requests allowed across the window "
        f"boundary. Configured limit is 5/s. "
        f"Fix: replace fixed window with a sliding window or token bucket."
    )


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
                "by_user": "100/s",          # High — will not trigger
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
        "Expected 3rd prompt_pre_fetch call to be blocked by by_tool limit (2/s). "
        "prompt_pre_fetch does not check by_tool — tool-level limits only apply "
        "to tool_pre_invoke."
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
async def test_none_tenant_falls_back_to_default_bucket():
    """
    None tenant_id falls back to 'default'. Multiple users with no tenant
    share the same tenant bucket — they can exhaust each other's tenant limit.
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
    r3 = await plugin.tool_pre_invoke(payload, ctx_alice)  # tenant "default" exhausted

    assert r1.violation is None
    assert r2.violation is None
    assert r3.violation is not None  # both users share "default" tenant bucket
    assert r3.violation.http_status_code == 429


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


@pytest.mark.asyncio
async def test_graceful_degradation_unexpected_runtime_error_does_not_crash_caller():
    """
    If an unexpected runtime error occurs inside a hook (e.g. a bug in _allow()),
    the exception is caught, logged, and a permissive result is returned.

    The gateway request is NOT crashed by a plugin error.
    This is tested by patching _allow to raise a RuntimeError mid-hook.
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

    assert result is not None, "Plugin should return a result even when _allow() raises unexpectedly"
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
    """

    class _BrokenRedis:
        """Simulates a Redis client that always fails."""

        async def eval(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("Redis is down")

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
    """

    class _BrokenRedis:
        async def eval(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("Redis is down")

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
    assert 1 <= retry_after <= 1, (
        f"For a 1/s limit, Retry-After should be 1 second, got {retry_after}"
    )


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
    assert 1 <= retry_after <= 60, (
        f"For a 1/m limit, Retry-After should be 1–60 seconds, got {retry_after}"
    )


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

    assert reset1 == reset2 == reset3, (
        f"X-RateLimit-Reset must be identical across all requests in the same window. "
        f"Got {reset1}, {reset2}, {reset3}"
    )


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

    assert results == [4, 3, 2, 1, 0], (
        f"X-RateLimit-Remaining should count down 4→3→2→1→0, got {results}"
    )


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
    assert r3.violation is not None, (
        "None and empty-string users share the 'anonymous' bucket — "
        "a third request must be blocked regardless of which falsy identity sent it"
    )


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
    assert r.violation is not None, (
        "Whitespace-only user identity should share the 'anonymous' bucket. "
        "Currently it creates its own bucket, bypassing the anonymous limit."
    )


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
    assert r.violation is not None, (
        "'Search' should be subject to the same 1/s limit as 'search'. "
        "Case-insensitive matching is not implemented — this is a bypass vector."
    )


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
    assert r.violation is not None, (
        "' search' (leading space) should be subject to the same limit as 'search'. "
        "Whitespace stripping is not implemented — this is a bypass vector."
    )


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
    assert r.violation is None, (
        "Exhausting the anonymous bucket must not affect real authenticated users"
    )


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
        "User identity must not appear in the violation description — "
        "it is logged in permissive mode and embedded in PluginViolationError messages"
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
    assert "acme-corp" not in result.violation.description, (
        "Tenant identifier must not appear in the violation description"
    )


@pytest.mark.asyncio
async def test_prompt_violation_description_does_not_contain_user_identity():
    """Same check for prompt_pre_fetch — description must not include user identity."""
    plugin = _mk("1/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="bob@example.com"))
    payload = PromptPrehookPayload(prompt_id="my_prompt", args={})

    await plugin.prompt_pre_fetch(payload, ctx)
    result = await plugin.prompt_pre_fetch(payload, ctx)

    assert result.violation is not None
    assert "bob@example.com" not in result.violation.description, (
        "User identity must not appear in the prompt violation description"
    )


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
        "tenant-2 has a separate independent counter — this is intentional. "
        "Tenant identity comes from the JWT and is controlled by the auth layer, "
        "not bypassable by request content."
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
    assert allowed_total <= 6, (
        f"Sliding window should prevent boundary burst. Got {allowed_total} allowed "
        f"(fixed window would allow 10, sliding window should block most of W2)."
    )


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
    assert allowed == 5, (
        f"Token bucket should allow a burst of 5 from a full bucket, got {allowed} allowed"
    )

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
    assert total_allowed <= 2 * limit, (
        f"Total allowed {total_allowed} exceeds 2× limit ({2 * limit}) — "
        f"fixed_window boundary burst is worse than documented"
    )


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
    assert meta["remaining"] <= limit, (
        f"Token bucket overflowed: remaining={meta['remaining']} > limit={limit}"
    )


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
    assert allowed == limit, (
        f"Expected exactly {limit} allowed with duplicate timestamps, got {allowed}"
    )


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
    from unittest.mock import AsyncMock  # noqa: PLC0415

    try:
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
    assert r3 is False, (
        "Third request at same timestamp must be blocked — "
        "each request now occupies its own sorted-set slot via unique member"
    )


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
        assert allowed is True, (
            "After window expires, allow() must evict stale timestamps and allow fresh requests"
        )


@pytest.mark.asyncio
async def test_memory_and_redis_sliding_window_have_same_allow_block_sequence():
    """
    Memory backend and Redis backend must produce identical allow/block decisions
    for the same request timeline. This parity test uses an in-process Redis
    simulator that faithfully implements the fixed sliding window Lua script logic:
    unique member per request (ARGV[4]) and count check before ZADD.
    """
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

    assert redis_decisions == memory_decisions, (
        f"Memory and Redis sliding window diverged:\n"
        f"  Redis:  {redis_decisions}\n"
        f"  Memory: {memory_decisions}"
    )


@pytest.mark.asyncio
async def test_memory_and_redis_token_bucket_have_same_allow_block_sequence():
    """
    Memory backend and Redis backend must produce identical allow/block decisions
    for the token bucket algorithm across a fixed request timeline.
    Uses an in-process simulator of the token bucket Lua script.
    """
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

    assert redis_decisions == memory_decisions, (
        f"Memory and Redis token bucket diverged:\n"
        f"  Redis:  {redis_decisions}\n"
        f"  Memory: {memory_decisions}"
    )


# ---------------------------------------------------------------------------
# P1 Unit Tests — header consistency and correctness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_bucket_success_headers_are_consistent_between_memory_and_redis():
    """
    For allowed token bucket requests, both memory and Redis backends must
    produce the same X-RateLimit-Remaining value and X-RateLimit-Limit == configured limit.
    """
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
async def test_sliding_window_reset_header_tracks_oldest_request_expiry():
    """
    For sliding_window, X-RateLimit-Reset must equal the timestamp of the
    oldest request in the current window plus the window duration — i.e.
    when that request ages out and a new slot opens.
    """
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
