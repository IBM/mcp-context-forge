# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/rate_limiter/test_rate_limiter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for RateLimiterPlugin.
"""

import pytest

from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    PromptHookType,
    PromptPrehookPayload,
    ToolHookType
)
from plugins.rate_limiter.rate_limiter import RateLimiterPlugin, _make_headers, _parse_rate, _select_most_restrictive, _store


@pytest.fixture(autouse=True)
def clear_rate_limit_store():
    """Clear the rate limiter store before each test to ensure test isolation."""
    _store.clear()
    yield
    _store.clear()


def _mk(rate: str) -> RateLimiterPlugin:
    return RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[PromptHookType.PROMPT_PRE_FETCH, ToolHookType.TOOL_PRE_INVOKE],
            config={"by_user": rate},
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
        with pytest.raises(ValueError, match="Unsupported rate unit"):
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
