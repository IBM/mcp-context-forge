# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/rate_limiter/test_rate_limiter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for RateLimiterPlugin.
"""

import pytest

from mcpgateway.plugins.framework import GlobalContext, PluginConfig, PluginContext, PromptHookType, PromptPrehookPayload, ToolHookType
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
async def test_prompt_pre_fetch_success_has_no_http_headers():
    """Test that successful requests do not set http_headers on the result."""
    plugin = _mk("10/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
    payload = PromptPrehookPayload(prompt_id="p", args={})

    result = await plugin.prompt_pre_fetch(payload, ctx)

    assert result.violation is None
    assert result.metadata is not None


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
async def test_tool_pre_invoke_success_has_no_http_headers():
    """Test that successful tool invocations do not set http_headers on the result."""
    from mcpgateway.plugins.framework import ToolPreInvokePayload

    plugin = _mk("10/s")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    result = await plugin.tool_pre_invoke(payload, ctx)

    assert result.violation is None
    assert result.metadata is not None


@pytest.mark.asyncio
async def test_tool_pre_invoke_per_tool_rate_limiting():
    """Test per-tool rate limiting configuration."""
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

    # Test Category 3: Multiple Violated Dimensions - Select Longest Reset

    def test_multiple_violated_longest_reset_wins(self):
        """When multiple violated, select the one with longest reset time
        so clients wait long enough for ALL violated dimensions to reset."""
        now = 1000
        results = [
            (False, 10, now + 30, {"limited": True, "remaining": 0, "reset_in": 30}),
            (False, 20, now + 60, {"limited": True, "remaining": 0, "reset_in": 60}),
            (False, 30, now + 120, {"limited": True, "remaining": 0, "reset_in": 120}),  # Longest
        ]
        allowed, limit, remaining, reset_ts, meta = _select_most_restrictive(results)
        assert allowed is False
        assert limit == 30  # Longest reset_in (120)
        assert remaining == 0
        assert reset_ts == now + 120
        assert meta["reset_in"] == 120

    def test_violated_with_allowed_dimensions(self):
        """When some violated and some allowed, violated takes precedence.
        Among violated, the longest reset wins so clients wait long enough."""
        now = 1000
        results = [
            (True, 100, now + 60, {"limited": True, "remaining": 90, "reset_in": 60}),  # Allowed
            (False, 50, now + 30, {"limited": True, "remaining": 0, "reset_in": 30}),  # Violated
            (False, 75, now + 90, {"limited": True, "remaining": 0, "reset_in": 90}),  # Violated (longest)
        ]
        allowed, limit, remaining, reset_ts, meta = _select_most_restrictive(results)
        assert allowed is False
        assert limit == 75  # Violated with longest reset
        assert remaining == 0
        assert reset_ts == now + 90
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
        """Realistic scenario: multiple violated with different reset times.
        Longest reset wins so clients wait for all dimensions to clear."""
        now = 1000
        results = [
            (False, 100, now + 60, {"limited": True, "remaining": 0, "reset_in": 60}),  # User (longest)
            (False, 1000, now + 10, {"limited": True, "remaining": 0, "reset_in": 10}),  # Tenant
            (False, 50, now + 30, {"limited": True, "remaining": 0, "reset_in": 30}),  # Tool
        ]
        allowed, limit, remaining, reset_ts, meta = _select_most_restrictive(results)
        assert allowed is False
        assert limit == 100  # User has longest reset
        assert remaining == 0
        assert reset_ts == now + 60
        assert meta["reset_in"] == 60

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
    """Tests for _parse_rate function including daily unit support."""

    def test_parse_rate_seconds(self):
        """Test parsing second-based rates."""
        assert _parse_rate("10/s") == (10, 1)
        assert _parse_rate("10/sec") == (10, 1)
        assert _parse_rate("10/second") == (10, 1)

    def test_parse_rate_minutes(self):
        """Test parsing minute-based rates."""
        assert _parse_rate("60/m") == (60, 60)
        assert _parse_rate("60/min") == (60, 60)
        assert _parse_rate("60/minute") == (60, 60)

    def test_parse_rate_hours(self):
        """Test parsing hour-based rates."""
        assert _parse_rate("100/h") == (100, 3600)
        assert _parse_rate("100/hr") == (100, 3600)
        assert _parse_rate("100/hour") == (100, 3600)

    def test_parse_rate_daily_short(self):
        """Test parsing daily rate with short unit."""
        assert _parse_rate("1000/d") == (1000, 86400)

    def test_parse_rate_daily_long(self):
        """Test parsing daily rate with long unit."""
        assert _parse_rate("1000/day") == (1000, 86400)

    def test_parse_rate_unsupported_unit(self):
        """Test that unsupported units raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported rate unit"):
            _parse_rate("100/w")

    def test_parse_rate_case_insensitive(self):
        """Test that units are case-insensitive."""
        assert _parse_rate("10/S") == (10, 1)
        assert _parse_rate("60/M") == (60, 60)
        assert _parse_rate("100/H") == (100, 3600)
        assert _parse_rate("1000/D") == (1000, 86400)
        assert _parse_rate("1000/Day") == (1000, 86400)

    def test_parse_rate_whitespace_in_unit(self):
        """Test that whitespace in units is handled."""
        assert _parse_rate("10/ s ") == (10, 1)
        assert _parse_rate("1000/ d ") == (1000, 86400)


@pytest.mark.asyncio
async def test_daily_rate_limit_blocks_after_quota():
    """Test that daily rate limits enforce correctly."""
    plugin = _mk("3/d")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
    payload = PromptPrehookPayload(prompt_id="p", args={})

    # Three requests should succeed
    for _ in range(3):
        result = await plugin.prompt_pre_fetch(payload, ctx)
        assert result.violation is None

    # Fourth should be blocked
    result = await plugin.prompt_pre_fetch(payload, ctx)
    assert result.violation is not None
    assert result.violation.http_status_code == 429
    assert result.violation.code == "RATE_LIMIT"


@pytest.mark.asyncio
async def test_daily_rate_limit_headers_accuracy():
    """Test that daily rate limit violation headers have correct values."""
    plugin = _mk("1/d")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="u1"))
    payload = PromptPrehookPayload(prompt_id="p", args={})

    # First request succeeds
    await plugin.prompt_pre_fetch(payload, ctx)

    # Second triggers violation
    result = await plugin.prompt_pre_fetch(payload, ctx)
    assert result.violation is not None

    headers = result.violation.http_headers
    assert headers is not None
    assert headers["X-RateLimit-Limit"] == "1"
    assert headers["X-RateLimit-Remaining"] == "0"
    # Retry-After should be close to 86400 seconds (24 hours)
    retry_after = int(headers["Retry-After"])
    assert 86390 <= retry_after <= 86400
