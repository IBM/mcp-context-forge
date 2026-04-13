# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_rate_limiter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for rate limiter plugin.

Tests verify:
1. Rate limit enforcement via plugin hooks
2. HTTP 429 status code on limit exceeded
3. Retry-After and X-RateLimit-* headers
4. Multi-dimensional rate limiting (user, tenant, tool)
5. Window reset behavior
6. Header propagation through exception handler
7. Plugin configuration from config file

Note: This tests the PLUGIN-based rate limiting, not middleware.
The rate limiter is implemented as a plugin that hooks into
prompt_pre_fetch and tool_pre_invoke.
"""

# Standard
import asyncio
import socket
import subprocess
import time

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.main import app
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    PromptPrehookPayload,
    ToolPreInvokePayload,
)
from mcpgateway.plugins.framework.base import HookRef, PluginRef
from mcpgateway.plugins.framework.errors import PluginViolationError
from mcpgateway.plugins.framework.manager import PluginExecutor
from mcpgateway.plugins.framework.models import PluginMode
from cpex_rate_limiter.rate_limiter import RateLimiterPlugin

# API Endpoints
PROMPT_ENDPOINT = "/api/v1/prompts/"
TOOL_INVOKE_ENDPOINT = "/api/v1/tools/invoke"


@pytest.fixture
def rate_limit_plugin_2_per_second():
    """Rate limiter plugin configured for 2 requests per second."""
    config = PluginConfig(
        name="RateLimiter",
        kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
        hooks=["prompt_pre_fetch", "tool_pre_invoke"],
        priority=100,
        config={"by_user": "2/s", "by_tenant": None, "by_tool": {}},
    )
    return RateLimiterPlugin(config)


@pytest.fixture
def rate_limit_plugin_multi_dimensional():
    """Rate limiter plugin with multi-dimensional limits."""
    config = PluginConfig(
        name="RateLimiter",
        kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
        hooks=["prompt_pre_fetch", "tool_pre_invoke"],
        priority=100,
        config={"by_user": "10/s", "by_tenant": "5/s", "by_tool": {"restricted_tool": "1/s"}},
    )
    return RateLimiterPlugin(config)


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


class TestRateLimitBasics:
    """Basic rate limit enforcement tests via plugin."""

    @pytest.mark.asyncio
    async def test_under_limit_allows_requests(self, rate_limit_plugin_2_per_second):
        """Verify requests under limit are allowed."""
        plugin = rate_limit_plugin_2_per_second
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = PromptPrehookPayload(prompt_id="test", args={})

        # First request - should succeed
        result1 = await plugin.prompt_pre_fetch(payload, ctx)
        assert result1.violation is None
        assert result1.http_headers is not None
        assert result1.http_headers["X-RateLimit-Remaining"] == "1"

        # Second request - should succeed
        result2 = await plugin.prompt_pre_fetch(payload, ctx)
        assert result2.violation is None
        assert result2.http_headers["X-RateLimit-Remaining"] == "0"

    @pytest.mark.asyncio
    async def test_exceeding_limit_returns_violation(self, rate_limit_plugin_2_per_second):
        """Verify exceeding limit returns violation with HTTP 429."""
        plugin = rate_limit_plugin_2_per_second
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = PromptPrehookPayload(prompt_id="test", args={})

        # Exhaust rate limit
        await plugin.prompt_pre_fetch(payload, ctx)
        await plugin.prompt_pre_fetch(payload, ctx)

        # Third request should be rate limited
        result = await plugin.prompt_pre_fetch(payload, ctx)
        assert result.violation is not None
        assert result.violation.http_status_code == 429
        assert result.violation.code == "RATE_LIMIT"
        assert "rate limit exceeded" in result.violation.description.lower()

    @pytest.mark.asyncio
    async def test_rate_limit_headers_present(self, rate_limit_plugin_2_per_second):
        """Verify all rate limit headers are present."""
        plugin = rate_limit_plugin_2_per_second
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = PromptPrehookPayload(prompt_id="test", args={})

        result = await plugin.prompt_pre_fetch(payload, ctx)

        assert result.http_headers is not None
        assert "X-RateLimit-Limit" in result.http_headers
        assert "X-RateLimit-Remaining" in result.http_headers
        assert "X-RateLimit-Reset" in result.http_headers

        limit = int(result.http_headers["X-RateLimit-Limit"])
        remaining = int(result.http_headers["X-RateLimit-Remaining"])
        reset = int(result.http_headers["X-RateLimit-Reset"])

        assert limit == 2
        assert remaining == 1
        assert reset > int(time.time())

    @pytest.mark.asyncio
    async def test_retry_after_header_on_violation(self, rate_limit_plugin_2_per_second):
        """Verify Retry-After header is present on violations."""
        plugin = rate_limit_plugin_2_per_second
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = PromptPrehookPayload(prompt_id="test", args={})

        # Exhaust rate limit
        await plugin.prompt_pre_fetch(payload, ctx)
        await plugin.prompt_pre_fetch(payload, ctx)

        # Get violation
        result = await plugin.prompt_pre_fetch(payload, ctx)
        assert result.violation is not None
        assert result.violation.http_headers is not None
        assert "Retry-After" in result.violation.http_headers

        retry_after = int(result.violation.http_headers["Retry-After"])
        assert 0 < retry_after <= 1  # 1 second window

    @pytest.mark.asyncio
    async def test_success_response_no_retry_after(self, rate_limit_plugin_2_per_second):
        """Verify successful responses don't include Retry-After header."""
        plugin = rate_limit_plugin_2_per_second
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = PromptPrehookPayload(prompt_id="test", args={})

        result = await plugin.prompt_pre_fetch(payload, ctx)

        assert result.violation is None
        assert result.http_headers is not None
        assert "Retry-After" not in result.http_headers


class TestRateLimitAlgorithm:
    """Window-based rate limiting algorithm tests."""

    @pytest.mark.asyncio
    async def test_remaining_count_decrements(self, rate_limit_plugin_2_per_second):
        """Verify remaining count decrements correctly."""
        plugin = rate_limit_plugin_2_per_second
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = PromptPrehookPayload(prompt_id="test", args={})

        # First request
        result1 = await plugin.prompt_pre_fetch(payload, ctx)
        assert result1.http_headers["X-RateLimit-Remaining"] == "1"

        # Second request
        result2 = await plugin.prompt_pre_fetch(payload, ctx)
        assert result2.http_headers["X-RateLimit-Remaining"] == "0"

    @pytest.mark.asyncio
    async def test_rate_limit_resets_after_window(self, rate_limit_plugin_2_per_second):
        """Verify rate limit resets after the window expires."""
        plugin = rate_limit_plugin_2_per_second
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = PromptPrehookPayload(prompt_id="test", args={})

        # Exhaust rate limit
        await plugin.prompt_pre_fetch(payload, ctx)
        await plugin.prompt_pre_fetch(payload, ctx)

        # Verify rate limited
        result = await plugin.prompt_pre_fetch(payload, ctx)
        assert result.violation is not None

        # Wait for window to reset (1 second + buffer)
        await asyncio.sleep(1.1)

        # Verify rate limit reset
        result = await plugin.prompt_pre_fetch(payload, ctx)
        assert result.violation is None
        assert result.http_headers["X-RateLimit-Remaining"] == "1"

    @pytest.mark.asyncio
    async def test_reset_timestamp_accuracy(self, rate_limit_plugin_2_per_second):
        """Verify X-RateLimit-Reset timestamp is accurate."""
        plugin = rate_limit_plugin_2_per_second
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = PromptPrehookPayload(prompt_id="test", args={})

        result = await plugin.prompt_pre_fetch(payload, ctx)
        reset_time = int(result.http_headers["X-RateLimit-Reset"])
        current_time = int(time.time())

        # Reset should be current time + 1 second (with small tolerance)
        expected_reset = current_time + 1
        assert abs(reset_time - expected_reset) <= 2


class TestMultiDimensionalRateLimiting:
    """Multi-dimensional rate limiting tests (user, tenant, tool)."""

    @pytest.mark.asyncio
    async def test_user_rate_limit_enforced(self):
        """Verify user rate limits are enforced independently per user."""
        # Configure with ONLY user limits (no tenant limit)
        config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["prompt_pre_fetch"],
            priority=100,
            config={"by_user": "10/s", "by_tenant": None, "by_tool": {}},  # No tenant limit
        )
        plugin = RateLimiterPlugin(config)

        ctx_alice = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id="team1"))
        ctx_bob = PluginContext(global_context=GlobalContext(request_id="r2", user="bob", tenant_id="team1"))
        payload = PromptPrehookPayload(prompt_id="test", args={})

        # Alice makes 10 requests (her limit)
        for _ in range(10):
            result = await plugin.prompt_pre_fetch(payload, ctx_alice)
            assert result.violation is None

        # Alice's 11th request should be rate limited
        result = await plugin.prompt_pre_fetch(payload, ctx_alice)
        assert result.violation is not None

        # Bob should still have his own limit (not affected by Alice)
        result = await plugin.prompt_pre_fetch(payload, ctx_bob)
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_tenant_rate_limit_enforced(self, rate_limit_plugin_multi_dimensional):
        """Verify tenant rate limits are enforced across users."""
        plugin = rate_limit_plugin_multi_dimensional
        ctx_alice = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id="team1"))
        ctx_bob = PluginContext(global_context=GlobalContext(request_id="r2", user="bob", tenant_id="team1"))
        payload = PromptPrehookPayload(prompt_id="test", args={})

        # Alice makes 3 requests
        for _ in range(3):
            result = await plugin.prompt_pre_fetch(payload, ctx_alice)
            assert result.violation is None

        # Bob makes 2 requests (total 5 for team1)
        for _ in range(2):
            result = await plugin.prompt_pre_fetch(payload, ctx_bob)
            assert result.violation is None

        # Next request from either user should be rate limited (tenant limit reached)
        result = await plugin.prompt_pre_fetch(payload, ctx_alice)
        assert result.violation is not None
        assert result.violation.http_status_code == 429

    @pytest.mark.asyncio
    async def test_per_tool_rate_limiting(self, rate_limit_plugin_multi_dimensional):
        """Verify per-tool rate limits are enforced."""
        plugin = rate_limit_plugin_multi_dimensional
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))

        restricted_payload = ToolPreInvokePayload(name="restricted_tool", arguments={})
        unrestricted_payload = ToolPreInvokePayload(name="other_tool", arguments={})

        # First call to restricted tool succeeds
        result = await plugin.tool_pre_invoke(restricted_payload, ctx)
        assert result.violation is None

        # Second call to restricted tool should be rate limited
        result = await plugin.tool_pre_invoke(restricted_payload, ctx)
        assert result.violation is not None
        assert result.violation.http_status_code == 429

        # Other tool should still work
        result = await plugin.tool_pre_invoke(unrestricted_payload, ctx)
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_most_restrictive_dimension_selected(self):
        """Verify most restrictive dimension is selected."""
        # Configure with different limits
        config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["prompt_pre_fetch"],
            priority=100,
            config={
                "by_user": "10/s",  # More permissive
                "by_tenant": "2/s",  # More restrictive
            },
        )
        plugin = RateLimiterPlugin(config)

        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id="team1"))
        payload = PromptPrehookPayload(prompt_id="test", args={})

        # Make 2 requests (tenant limit)
        await plugin.prompt_pre_fetch(payload, ctx)
        await plugin.prompt_pre_fetch(payload, ctx)

        # Third request should be rate limited by tenant limit
        result = await plugin.prompt_pre_fetch(payload, ctx)
        assert result.violation is not None
        # Headers should show tenant limit (2), not user limit (10)
        assert result.violation.http_headers["X-RateLimit-Limit"] == "2"


class TestToolPreInvoke:
    """Tests for tool_pre_invoke hook."""

    @pytest.mark.asyncio
    async def test_tool_invoke_rate_limiting(self, rate_limit_plugin_2_per_second):
        """Verify tool invocations are rate limited."""
        plugin = rate_limit_plugin_2_per_second
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        # First two requests succeed
        result1 = await plugin.tool_pre_invoke(payload, ctx)
        assert result1.violation is None

        result2 = await plugin.tool_pre_invoke(payload, ctx)
        assert result2.violation is None

        # Third request should be rate limited
        result3 = await plugin.tool_pre_invoke(payload, ctx)
        assert result3.violation is not None
        assert result3.violation.http_status_code == 429

    @pytest.mark.asyncio
    async def test_tool_invoke_headers_present(self, rate_limit_plugin_2_per_second):
        """Verify headers are present on tool invocations."""
        plugin = rate_limit_plugin_2_per_second
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        result = await plugin.tool_pre_invoke(payload, ctx)

        assert result.http_headers is not None
        assert "X-RateLimit-Limit" in result.http_headers
        assert "X-RateLimit-Remaining" in result.http_headers
        assert "X-RateLimit-Reset" in result.http_headers
        assert "Retry-After" not in result.http_headers  # Not on success


class TestStoreCleanup:
    """Tests for rate limit store cleanup."""

    @pytest.mark.asyncio
    async def test_store_cleanup_between_tests(self, rate_limit_plugin_2_per_second):
        """Verify each plugin instance starts with an empty store."""
        plugin = rate_limit_plugin_2_per_second
        backend = plugin._rate_backend

        # Fresh instance — store must be empty before any requests
        assert len(backend._algorithm._store) == 0

        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = PromptPrehookPayload(prompt_id="test", args={})

        await plugin.prompt_pre_fetch(payload, ctx)

        # After one request a window entry must exist
        assert len(backend._algorithm._store) > 0

    @pytest.mark.asyncio
    async def test_multiple_users_create_separate_windows(self, rate_limit_plugin_2_per_second):
        """Verify multiple users create separate window entries in the backend store."""
        plugin = rate_limit_plugin_2_per_second
        backend = plugin._rate_backend

        ctx_alice = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        ctx_bob = PluginContext(global_context=GlobalContext(request_id="r2", user="bob"))
        payload = PromptPrehookPayload(prompt_id="test", args={})

        await plugin.prompt_pre_fetch(payload, ctx_alice)
        await plugin.prompt_pre_fetch(payload, ctx_bob)

        # Each user must have their own key in the store
        assert len(backend._algorithm._store) >= 2


class TestSlidingWindowIntegration:
    """End-to-end integration tests for the sliding_window algorithm."""

    @pytest.fixture
    def plugin(self):
        config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["prompt_pre_fetch", "tool_pre_invoke"],
            priority=100,
            config={"by_user": "3/s", "algorithm": "sliding_window"},
        )
        return RateLimiterPlugin(config)

    @pytest.mark.asyncio
    async def test_sliding_window_enforces_limit(self, plugin):
        """Sliding window allows exactly N requests then blocks."""
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(3):
            result = await plugin.tool_pre_invoke(payload, ctx)
            assert result.violation is None

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is not None
        assert result.violation.http_status_code == 429

    @pytest.mark.asyncio
    async def test_sliding_window_returns_ratelimit_headers(self, plugin):
        """Sliding window includes X-RateLimit-* headers on allowed requests."""
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is None
        assert result.http_headers is not None
        assert "X-RateLimit-Limit" in result.http_headers
        assert "X-RateLimit-Remaining" in result.http_headers
        assert "X-RateLimit-Reset" in result.http_headers
        assert "Retry-After" not in result.http_headers

    @pytest.mark.asyncio
    async def test_sliding_window_retry_after_on_violation(self, plugin):
        """Sliding window includes Retry-After on violations."""
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(3):
            await plugin.tool_pre_invoke(payload, ctx)

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is not None
        assert "Retry-After" in result.violation.http_headers

    @pytest.mark.asyncio
    async def test_sliding_window_resets_after_window(self, plugin):
        """Sliding window allows requests again after the window elapses."""
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(3):
            await plugin.tool_pre_invoke(payload, ctx)

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is not None

        await asyncio.sleep(1.1)

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_sliding_window_independent_users(self, plugin):
        """Sliding window tracks separate counters per user."""
        ctx_alice = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        ctx_bob = PluginContext(global_context=GlobalContext(request_id="r2", user="bob"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(3):
            await plugin.tool_pre_invoke(payload, ctx_alice)

        alice_blocked = await plugin.tool_pre_invoke(payload, ctx_alice)
        assert alice_blocked.violation is not None

        bob_allowed = await plugin.tool_pre_invoke(payload, ctx_bob)
        assert bob_allowed.violation is None


class TestTokenBucketIntegration:
    """End-to-end integration tests for the token_bucket algorithm."""

    @pytest.fixture
    def plugin(self):
        config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["prompt_pre_fetch", "tool_pre_invoke"],
            priority=100,
            config={"by_user": "3/s", "algorithm": "token_bucket"},
        )
        return RateLimiterPlugin(config)

    @pytest.mark.asyncio
    async def test_token_bucket_enforces_limit(self, plugin):
        """Token bucket allows up to capacity requests then blocks."""
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(3):
            result = await plugin.tool_pre_invoke(payload, ctx)
            assert result.violation is None

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is not None
        assert result.violation.http_status_code == 429

    @pytest.mark.asyncio
    async def test_token_bucket_returns_ratelimit_headers(self, plugin):
        """Token bucket includes X-RateLimit-* headers on allowed requests."""
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is None
        assert result.http_headers is not None
        assert "X-RateLimit-Limit" in result.http_headers
        assert "X-RateLimit-Remaining" in result.http_headers
        assert "X-RateLimit-Reset" in result.http_headers

    @pytest.mark.asyncio
    async def test_token_bucket_remaining_decrements(self, plugin):
        """Token bucket X-RateLimit-Remaining decrements with each request."""
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        r1 = await plugin.tool_pre_invoke(payload, ctx)
        r2 = await plugin.tool_pre_invoke(payload, ctx)

        remaining1 = int(r1.http_headers["X-RateLimit-Remaining"])
        remaining2 = int(r2.http_headers["X-RateLimit-Remaining"])
        assert remaining2 < remaining1

    @pytest.mark.asyncio
    async def test_token_bucket_refills_over_time(self, plugin):
        """Token bucket allows requests again after tokens refill."""
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(3):
            await plugin.tool_pre_invoke(payload, ctx)

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is not None

        await asyncio.sleep(1.1)

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_token_bucket_independent_users(self, plugin):
        """Token bucket tracks separate buckets per user."""
        ctx_alice = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        ctx_bob = PluginContext(global_context=GlobalContext(request_id="r2", user="bob"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(3):
            await plugin.tool_pre_invoke(payload, ctx_alice)

        alice_blocked = await plugin.tool_pre_invoke(payload, ctx_alice)
        assert alice_blocked.violation is not None

        bob_allowed = await plugin.tool_pre_invoke(payload, ctx_bob)
        assert bob_allowed.violation is None


class TestCrossHookSharing:
    """Verify that prompt_pre_fetch and tool_pre_invoke share the same rate limit counters.

    Both hooks key by_user as 'user:{username}' and by_tenant as 'tenant:{tenant_id}'.
    A user consuming quota via one hook must be counted against the same bucket
    when using the other hook — the limit is per-identity, not per-hook.
    """

    @pytest.fixture
    def plugin(self):
        config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["prompt_pre_fetch", "tool_pre_invoke"],
            priority=100,
            config={"by_user": "5/s"},
        )
        return RateLimiterPlugin(config)

    @pytest.mark.asyncio
    async def test_prompt_and_tool_share_user_counter(self, plugin):
        """Requests via prompt_pre_fetch and tool_pre_invoke decrement the same user bucket."""
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        prompt_payload = PromptPrehookPayload(prompt_id="p", args={})
        tool_payload = ToolPreInvokePayload(name="tool", arguments={})

        # 3 prompt requests
        for _ in range(3):
            result = await plugin.prompt_pre_fetch(prompt_payload, ctx)
            assert result.violation is None

        # 2 tool requests — total 5, still within limit
        for _ in range(2):
            result = await plugin.tool_pre_invoke(tool_payload, ctx)
            assert result.violation is None

        # 6th request (either hook) must be blocked
        result = await plugin.tool_pre_invoke(tool_payload, ctx)
        assert result.violation is not None, "6th request should be blocked — prompt and tool hooks must share the same user counter"

    @pytest.mark.asyncio
    async def test_remaining_count_decrements_across_hooks(self, plugin):
        """X-RateLimit-Remaining reflects consumption from both hooks."""
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        prompt_payload = PromptPrehookPayload(prompt_id="p", args={})
        tool_payload = ToolPreInvokePayload(name="tool", arguments={})

        r1 = await plugin.prompt_pre_fetch(prompt_payload, ctx)
        remaining_after_prompt = int(r1.http_headers["X-RateLimit-Remaining"])

        r2 = await plugin.tool_pre_invoke(tool_payload, ctx)
        remaining_after_tool = int(r2.http_headers["X-RateLimit-Remaining"])

        assert remaining_after_tool < remaining_after_prompt, "Remaining count must decrease after a tool request following a prompt request — same shared counter"

    @pytest.mark.asyncio
    async def test_tenant_counter_shared_across_hooks_and_users(self, plugin):
        """Tenant bucket is shared across all users in the same tenant, regardless of hook."""
        config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["prompt_pre_fetch", "tool_pre_invoke"],
            priority=100,
            config={"by_user": "10/s", "by_tenant": "4/s"},
        )
        plugin = RateLimiterPlugin(config)

        ctx_alice = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id="team1"))
        ctx_bob = PluginContext(global_context=GlobalContext(request_id="r2", user="bob", tenant_id="team1"))

        # Alice: 2 prompt requests
        for _ in range(2):
            await plugin.prompt_pre_fetch(PromptPrehookPayload(prompt_id="p", args={}), ctx_alice)

        # Bob: 2 tool requests — total 4 for team1, tenant limit reached
        for _ in range(2):
            await plugin.tool_pre_invoke(ToolPreInvokePayload(name="tool", arguments={}), ctx_bob)

        # 5th request from either user must be blocked by tenant limit
        result = await plugin.prompt_pre_fetch(PromptPrehookPayload(prompt_id="p", args={}), ctx_alice)
        assert result.violation is not None, "Tenant limit must be enforced across both users and both hooks"


class TestPermissiveMode:
    """Permissive mode logs violations but never blocks requests.

    Mode enforcement is handled by PluginExecutor.execute_plugin(), not the
    plugin itself. These tests go through PluginExecutor to exercise that path.
    """

    def _make_plugin_and_hook(self, limit: str) -> tuple:
        config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["tool_pre_invoke"],
            priority=100,
            mode=PluginMode.PERMISSIVE,
            config={"by_user": limit},
        )
        plugin = RateLimiterPlugin(config)
        hook_ref = HookRef("tool_pre_invoke", PluginRef(plugin))
        executor = PluginExecutor(timeout=5)
        return plugin, hook_ref, executor

    @pytest.mark.asyncio
    async def test_permissive_mode_does_not_raise_on_violation(self):
        """PluginExecutor must not raise PluginViolationError in permissive mode."""
        plugin, hook_ref, executor = self._make_plugin_and_hook("1/s")
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        await executor.execute_plugin(hook_ref, payload, ctx, violations_as_exceptions=True)

        try:
            result = await executor.execute_plugin(hook_ref, payload, ctx, violations_as_exceptions=True)
        except PluginViolationError:
            pytest.fail("PluginViolationError raised in permissive mode — should be suppressed by executor")

        # Violation info is surfaced for observability but request is not blocked
        assert result.violation is not None
        assert result.violation.http_status_code == 429

    @pytest.mark.asyncio
    async def test_permissive_mode_still_tracks_counters(self):
        """Permissive mode still decrements the counter — backend store must grow."""
        plugin, hook_ref, executor = self._make_plugin_and_hook("10/s")
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        await executor.execute_plugin(hook_ref, payload, ctx, violations_as_exceptions=True)
        await executor.execute_plugin(hook_ref, payload, ctx, violations_as_exceptions=True)

        # Counter must have been incremented — key exists in backend store
        store = plugin._rate_backend._algorithm._store
        assert len(store) > 0, "Permissive mode must still track counters in the backend store"
        key = next(iter(store))
        assert store[key].count == 2, f"Expected count=2 after 2 requests, got {store[key].count}"

    @pytest.mark.asyncio
    async def test_permissive_mode_contrast_with_enforce(self):
        """Enforce mode raises PluginViolationError; permissive mode does not."""
        enforce_config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["tool_pre_invoke"],
            config={"by_user": "1/s"},
            mode=PluginMode.ENFORCE,
        )
        enforce_plugin = RateLimiterPlugin(enforce_config)
        enforce_ref = HookRef("tool_pre_invoke", PluginRef(enforce_plugin))
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})
        executor = PluginExecutor(timeout=5)

        await executor.execute_plugin(enforce_ref, payload, ctx, violations_as_exceptions=True)

        with pytest.raises(PluginViolationError):
            await executor.execute_plugin(enforce_ref, payload, ctx, violations_as_exceptions=True)


class TestDisabledMode:
    """Disabled mode — PluginExecutor.execute() skips the plugin entirely.

    The disabled check lives in execute() (batch), not execute_plugin() (single),
    so tests must go through execute() with a list of hook_refs.
    """

    def _make_plugin_and_refs(self) -> tuple:
        config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["tool_pre_invoke"],
            priority=100,
            mode=PluginMode.DISABLED,
            config={"by_user": "1/s"},
        )
        plugin = RateLimiterPlugin(config)
        hook_ref = HookRef("tool_pre_invoke", PluginRef(plugin))
        executor = PluginExecutor(timeout=5)
        return plugin, [hook_ref], executor

    @pytest.mark.asyncio
    async def test_disabled_mode_never_blocks(self):
        """execute() skips a disabled plugin — no violation ever returned."""
        plugin, hook_refs, executor = self._make_plugin_and_refs()
        global_ctx = GlobalContext(request_id="r1", user="alice")
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(10):
            result, _ = await executor.execute(hook_refs, payload, global_ctx, "tool_pre_invoke", violations_as_exceptions=True)
            assert result.violation is None, "Disabled plugin must never produce a violation"

    @pytest.mark.asyncio
    async def test_disabled_mode_does_not_track_counters(self):
        """execute() skips the plugin — backend store must remain empty."""
        plugin, hook_refs, executor = self._make_plugin_and_refs()
        global_ctx = GlobalContext(request_id="r1", user="alice")
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(5):
            await executor.execute(hook_refs, payload, global_ctx, "tool_pre_invoke", violations_as_exceptions=True)

        assert len(plugin._rate_backend._algorithm._store) == 0, "Disabled plugin must not write to the backend store — executor skips it entirely"

    def test_disabled_plugin_mode_property(self):
        """Plugin mode property reflects the configured disabled mode."""
        plugin, _, _ = self._make_plugin_and_refs()
        assert plugin.mode == PluginMode.DISABLED


class TestTenantIsolation:
    """Tenant isolation tests reflecting the real production GlobalContext path.

    In production (mcpgateway/auth.py):
      - global_context.tenant_id is always None (not derived from JWT teams)
      - global_context.user is set as a dict {"email": ..., "is_admin": ..., "full_name": ...}

    These tests document the actual behaviour of the rate limiter under those
    conditions so that regressions are caught if the production path changes.
    """

    @pytest.fixture
    def plugin(self):
        config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["tool_pre_invoke"],
            priority=100,
            config={"by_user": "3/s", "by_tenant": "5/s"},
        )
        return RateLimiterPlugin(config)

    @pytest.mark.asyncio
    async def test_user_dict_identity_is_rate_limited_independently(self, plugin):
        """When user is a dict (production path), each distinct dict is a separate bucket.

        In production global_context.user = {"email": "alice@...", "is_admin": False, ...}.
        The rate limiter uses this dict as the key via str(dict), so two users with
        different email addresses must have independent per-user counters.
        """
        alice_dict = {"email": "alice@example.com", "is_admin": False, "full_name": "Alice"}
        bob_dict = {"email": "bob@example.com", "is_admin": False, "full_name": "Bob"}

        ctx_alice = PluginContext(global_context=GlobalContext(request_id="r1", user=alice_dict))
        ctx_bob = PluginContext(global_context=GlobalContext(request_id="r2", user=bob_dict))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(3):
            await plugin.tool_pre_invoke(payload, ctx_alice)

        alice_blocked = await plugin.tool_pre_invoke(payload, ctx_alice)
        assert alice_blocked.violation is not None, "Alice must be blocked after exhausting her limit"

        bob_allowed = await plugin.tool_pre_invoke(payload, ctx_bob)
        assert bob_allowed.violation is None, "Bob must have an independent counter — Alice's limit must not affect him"

    @pytest.mark.asyncio
    async def test_explicit_tenant_id_isolates_teams(self, plugin):
        """When tenant_id is explicitly set, different teams have independent tenant buckets.

        This is the behaviour a custom auth plugin would produce if it populates
        global_context.tenant_id from the JWT teams claim.
        """
        ctx_team1 = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id="team1"))
        ctx_team2 = PluginContext(global_context=GlobalContext(request_id="r2", user="bob", tenant_id="team2"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        # Exhaust team1's tenant limit (5/s)
        for _ in range(5):
            await plugin.tool_pre_invoke(payload, ctx_team1)

        team1_blocked = await plugin.tool_pre_invoke(payload, ctx_team1)
        assert team1_blocked.violation is not None, "team1 must be blocked after 5 requests"

        # team2 must be unaffected — its own counter starts at 0
        team2_allowed = await plugin.tool_pre_invoke(payload, ctx_team2)
        assert team2_allowed.violation is None, "team2 must have its own independent tenant bucket"

    @pytest.mark.asyncio
    async def test_anonymous_user_has_separate_bucket_from_authenticated(self, plugin):
        """Unauthenticated requests (user=None → 'anonymous') must not consume authenticated user quota."""
        ctx_anon = PluginContext(global_context=GlobalContext(request_id="r1", user=None))
        ctx_alice = PluginContext(global_context=GlobalContext(request_id="r2", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        # Exhaust anonymous bucket
        for _ in range(3):
            await plugin.tool_pre_invoke(payload, ctx_anon)

        anon_blocked = await plugin.tool_pre_invoke(payload, ctx_anon)
        assert anon_blocked.violation is not None, "Anonymous bucket must be exhausted"

        # Alice must be unaffected
        alice_allowed = await plugin.tool_pre_invoke(payload, ctx_alice)
        assert alice_allowed.violation is None, "Authenticated user must have a separate bucket from anonymous"

    # ------------------------------------------------------------------
    # P0: desired behavior after the tenant_id propagation fix
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_none_tenant_id_skips_by_tenant_entirely(self):
        """When tenant_id is None, by_tenant must be skipped — not enforced against a shared 'default' bucket.

        Production path (mcpgateway/auth.py) always sets tenant_id=None.  Bucketing
        every request into 'tenant:default' creates a global shared limit that
        cross-throttles unrelated users — worse than no tenant limiting at all.

        Expected behavior after fix: by_tenant is a no-op when tenant_id is absent.
        Uses a high by_user limit so only by_tenant could trigger a block.
        """
        config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["tool_pre_invoke"],
            priority=100,
            config={"by_user": "100/s", "by_tenant": "5/s"},
        )
        plugin = RateLimiterPlugin(config)
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id=None))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        # by_tenant limit is 5/s; without a real tenant, no request should be
        # blocked by the tenant dimension regardless of how many we send.
        for i in range(7):
            result = await plugin.tool_pre_invoke(payload, ctx)
            assert result.violation is None, f"Request {i + 1}: by_tenant must be skipped when tenant_id is None — " "no request should be blocked by a phantom 'default' tenant bucket"

    @pytest.mark.asyncio
    async def test_multi_team_users_do_not_share_tenant_bucket(self, plugin):
        """Two users with tenant_id=None must not throttle each other via a shared 'default' bucket.

        This is the multi-tenant deployment correctness test: if alice and bob are
        from different organisations but both have tenant_id=None (e.g. multi-team
        API tokens), a fake 'default' bucket would cross-throttle them.  The plugin
        must skip by_tenant for both instead.
        """
        ctx_alice = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id=None))
        ctx_bob = PluginContext(global_context=GlobalContext(request_id="r2", user="bob", tenant_id=None))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        # Alice sends 5 requests — tenant limit is 5/s
        for _ in range(5):
            await plugin.tool_pre_invoke(payload, ctx_alice)

        # Bob's first request must not be blocked — he should not share Alice's bucket
        bob_result = await plugin.tool_pre_invoke(payload, ctx_bob)
        assert bob_result.violation is None, "Bob must not be blocked by Alice's activity — " "users with tenant_id=None must not share a 'default' tenant bucket"

    @pytest.mark.asyncio
    async def test_explicit_tenant_scopes_correctly_after_fix(self):
        """P1: when tenant_id IS provided, by_tenant still enforces correctly.

        This is a regression guard: the fix must not break the case where tenant_id
        is explicitly set (e.g. by a custom auth plugin or future auth-layer fix).
        Uses a high by_user limit so only by_tenant can trigger a block.
        """
        config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["tool_pre_invoke"],
            priority=100,
            config={"by_user": "100/s", "by_tenant": "5/s"},
        )
        plugin = RateLimiterPlugin(config)
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id="org-acme"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(5):
            result = await plugin.tool_pre_invoke(payload, ctx)
            assert result.violation is None

        blocked = await plugin.tool_pre_invoke(payload, ctx)
        assert blocked.violation is not None, "by_tenant must still enforce when tenant_id is explicitly set"


class TestNoLimitsAndMissingContext:
    """Behaviour when no limits are configured or GlobalContext fields are absent.

    These tests document the plugin's safe defaults so regressions are caught
    if the fallback logic in prompt_pre_fetch / tool_pre_invoke changes.
    """

    @pytest.mark.asyncio
    async def test_no_limits_configured_allows_all_requests(self):
        """Plugin with all dimensions None must allow every request without tracking."""
        config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["tool_pre_invoke"],
            config={},  # no by_user, no by_tenant, no by_tool
        )
        plugin = RateLimiterPlugin(config)
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(20):
            result = await plugin.tool_pre_invoke(payload, ctx)
            assert result.violation is None, "Unconfigured plugin must never block"

    @pytest.mark.asyncio
    async def test_no_limits_configured_returns_no_headers(self):
        """Plugin with no configured limits must not set X-RateLimit-* headers."""
        config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["tool_pre_invoke"],
            config={},
        )
        plugin = RateLimiterPlugin(config)
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert not result.http_headers, "No limits configured — X-RateLimit-* headers must not be present"

    @pytest.mark.asyncio
    async def test_none_user_defaults_to_anonymous_bucket(self):
        """user=None in GlobalContext must fall back to 'anonymous' as the rate limit key."""
        config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["tool_pre_invoke"],
            config={"by_user": "2/s"},
        )
        plugin = RateLimiterPlugin(config)
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user=None))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        await plugin.tool_pre_invoke(payload, ctx)
        await plugin.tool_pre_invoke(payload, ctx)

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is not None, "user=None must be treated as 'anonymous' and enforced"

        # Confirm the key in the store is 'user:anonymous'
        store = plugin._rate_backend._algorithm._store
        assert any("anonymous" in k for k in store), "Expected 'anonymous' bucket key in store when user=None"

    @pytest.mark.asyncio
    async def test_none_tenant_id_skips_by_tenant_check(self):
        """tenant_id=None in GlobalContext must skip the by_tenant check entirely — no 'default' bucket."""
        config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["tool_pre_invoke"],
            config={"by_tenant": "2/s"},
        )
        plugin = RateLimiterPlugin(config)
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice", tenant_id=None))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        # With no by_user limit, by_tenant is the only dimension — but it must be skipped
        for _ in range(3):
            result = await plugin.tool_pre_invoke(payload, ctx)
            assert result.violation is None, "by_tenant must be skipped when tenant_id is None"

        store = plugin._rate_backend._algorithm._store
        assert not any("tenant" in k for k in store), "No tenant bucket must be created in the store when tenant_id is None"

    @pytest.mark.asyncio
    async def test_both_user_and_tenant_none_still_enforces(self):
        """With both user=None and tenant_id=None the plugin must still enforce limits."""
        config = PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["tool_pre_invoke"],
            config={"by_user": "2/s", "by_tenant": "10/s"},
        )
        plugin = RateLimiterPlugin(config)
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user=None, tenant_id=None))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        await plugin.tool_pre_invoke(payload, ctx)
        await plugin.tool_pre_invoke(payload, ctx)

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is not None, "With user=None and tenant_id=None the plugin must still enforce via anonymous/default buckets"

    @pytest.mark.asyncio
    async def test_separate_plugin_instances_have_independent_stores(self):
        """Two RateLimiterPlugin instances must never share backend state."""

        def make_plugin():
            return RateLimiterPlugin(
                PluginConfig(
                    name="RateLimiter",
                    kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
                    hooks=["tool_pre_invoke"],
                    config={"by_user": "2/s"},
                )
            )

        plugin_a = make_plugin()
        plugin_b = make_plugin()

        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        # Exhaust plugin_a
        await plugin_a.tool_pre_invoke(payload, ctx)
        await plugin_a.tool_pre_invoke(payload, ctx)
        a_blocked = await plugin_a.tool_pre_invoke(payload, ctx)
        assert a_blocked.violation is not None

        # plugin_b must be completely unaffected
        b_allowed = await plugin_b.tool_pre_invoke(payload, ctx)
        assert b_allowed.violation is None, "Two plugin instances must have independent stores — exhausting one must not affect the other"


# =============================================================================
# Redis Backend Integration Tests
# =============================================================================
#
# These tests require a real Redis instance.  They are skipped automatically
# when Redis is not reachable and Docker cannot start one.  Each test flushes
# DB 15 before use to avoid cross-test contamination.
#
# Run with: uv run pytest tests/integration/test_rate_limiter.py -k Redis -v
# =============================================================================


def _redis_port_open(host: str = "127.0.0.1", port: int = 6379, timeout: float = 0.2) -> bool:
    """Return True if a TCP connection to host:port succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def redis_url_for_integration():
    """Yield a Redis URL pointing at a real Redis instance.

    Tries localhost:6379 first.  If not reachable, attempts to start a
    temporary Docker container.  Skips the test module if neither works.
    Container is stopped automatically after all tests in the module finish.
    """
    try:
        # Third-Party
        import redis.asyncio  # noqa: F401
    except Exception:
        pytest.skip("redis.asyncio package not installed")

    host, port = "127.0.0.1", 6379
    container_id = None

    if not _redis_port_open(host, port):
        try:
            res = subprocess.run(
                ["docker", "run", "-d", "--rm", "-p", f"{port}:6379", "--name", "pytest-rl-redis-integ", "redis:7"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            container_id = res.stdout.strip()
        except Exception as exc:
            pytest.skip(f"Redis unavailable and docker start failed: {exc}")

        for _ in range(50):
            if _redis_port_open(host, port):
                break
            time.sleep(0.1)
        else:
            if container_id:
                subprocess.run(["docker", "stop", container_id], check=False)
            pytest.skip("Redis did not start in time")

    yield f"redis://{host}:{port}/15"  # DB 15 — isolated from other data

    if container_id:
        subprocess.run(["docker", "stop", container_id], check=False)


def _make_redis_plugin(redis_url: str, algorithm: str = "fixed_window", limit: str = "3/s") -> RateLimiterPlugin:
    """Create a RateLimiterPlugin backed by real Redis."""
    return RateLimiterPlugin(
        PluginConfig(
            name="RateLimiter",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["tool_pre_invoke"],
            priority=100,
            config={
                "by_user": limit,
                "backend": "redis",
                "redis_url": redis_url,
                "algorithm": algorithm,
            },
        )
    )


async def _flush_redis(redis_url: str) -> None:
    """Flush DB 15 before each test to ensure a clean slate."""
    # Third-Party
    import redis.asyncio as aioredis  # noqa: PLC0415

    client = aioredis.from_url(redis_url)
    await client.flushdb()
    await client.aclose()


class TestRedisBackendIntegration:
    """End-to-end integration tests for the Redis backend.

    Validates plugin wiring, shared-counter semantics, TTL/window reset
    behavior, and fallback behavior against a real Redis-backed gateway flow.
    """

    @pytest.mark.asyncio
    async def test_redis_plugin_enforces_limit(self, redis_url_for_integration):
        """Plugin wired to real Redis blocks on N+1 requests within the window."""
        await _flush_redis(redis_url_for_integration)

        plugin = _make_redis_plugin(redis_url_for_integration, algorithm="fixed_window", limit="3/s")
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(3):
            result = await plugin.tool_pre_invoke(payload, ctx)
            assert result.violation is None

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is not None
        assert result.violation.http_status_code == 429

    @pytest.mark.asyncio
    async def test_redis_shared_counter_across_plugin_instances(self, redis_url_for_integration):
        """Two plugin instances pointing at the same Redis share rate limit counters.

        This is the core multi-instance correctness test: after instance A exhausts
        the limit, instance B must be blocked because they share the same Redis key.
        """
        await _flush_redis(redis_url_for_integration)

        plugin_a = _make_redis_plugin(redis_url_for_integration, limit="3/s")
        plugin_b = _make_redis_plugin(redis_url_for_integration, limit="3/s")
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(3):
            result = await plugin_a.tool_pre_invoke(payload, ctx)
            assert result.violation is None

        result = await plugin_b.tool_pre_invoke(payload, ctx)
        assert result.violation is not None, "Redis backend must share counters across plugin instances — " "instance B must be blocked after instance A exhausts the limit"

    @pytest.mark.asyncio
    async def test_redis_window_resets_after_ttl(self, redis_url_for_integration):
        """After the rate window expires, Redis TTL resets counters and requests are allowed again."""
        await _flush_redis(redis_url_for_integration)

        plugin = _make_redis_plugin(redis_url_for_integration, algorithm="fixed_window", limit="2/s")
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        await plugin.tool_pre_invoke(payload, ctx)
        await plugin.tool_pre_invoke(payload, ctx)
        blocked = await plugin.tool_pre_invoke(payload, ctx)
        assert blocked.violation is not None

        # Wait for the 1-second window to expire via real Redis TTL
        await asyncio.sleep(1.1)

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is None, "After the rate window expires, Redis TTL must reset counters and allow fresh requests"

    @pytest.mark.asyncio
    async def test_redis_fallback_to_memory_on_unavailable_redis(self):
        """Plugin with an unreachable Redis URL falls back to memory backend without crashing."""
        plugin = _make_redis_plugin("redis://127.0.0.1:19999/0", limit="3/s")
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        # Must not raise — fallback to memory backend should handle the request
        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is None, "Plugin must fall back to memory backend when Redis is unavailable — must not crash"

    # ------------------------------------------------------------------
    # sliding_window on real Redis
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_redis_sliding_window_enforces_limit(self, redis_url_for_integration):
        """sliding_window on real Redis blocks on N+1 requests within the window."""
        await _flush_redis(redis_url_for_integration)

        plugin = _make_redis_plugin(redis_url_for_integration, algorithm="sliding_window", limit="3/s")
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(3):
            result = await plugin.tool_pre_invoke(payload, ctx)
            assert result.violation is None

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is not None
        assert result.violation.http_status_code == 429

    @pytest.mark.asyncio
    async def test_redis_sliding_window_shared_counter_across_instances(self, redis_url_for_integration):
        """Two sliding_window plugin instances share counters via Redis.

        After instance A exhausts the limit, instance B must be blocked because
        they share the same Redis sorted-set key.
        """
        await _flush_redis(redis_url_for_integration)

        plugin_a = _make_redis_plugin(redis_url_for_integration, algorithm="sliding_window", limit="3/s")
        plugin_b = _make_redis_plugin(redis_url_for_integration, algorithm="sliding_window", limit="3/s")
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(3):
            result = await plugin_a.tool_pre_invoke(payload, ctx)
            assert result.violation is None

        result = await plugin_b.tool_pre_invoke(payload, ctx)
        assert result.violation is not None, "sliding_window Redis backend must share counters across instances — " "instance B must be blocked after instance A exhausts the limit"

    @pytest.mark.asyncio
    async def test_redis_sliding_window_resets_after_window(self, redis_url_for_integration):
        """After the sliding window elapses, Redis TTL resets the sorted set and requests are allowed again."""
        await _flush_redis(redis_url_for_integration)

        plugin = _make_redis_plugin(redis_url_for_integration, algorithm="sliding_window", limit="2/s")
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        await plugin.tool_pre_invoke(payload, ctx)
        await plugin.tool_pre_invoke(payload, ctx)
        blocked = await plugin.tool_pre_invoke(payload, ctx)
        assert blocked.violation is not None

        await asyncio.sleep(1.1)

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is None, "After the sliding window elapses, Redis TTL must reset the sorted set and allow fresh requests"

    # ------------------------------------------------------------------
    # token_bucket on real Redis
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_redis_token_bucket_enforces_limit(self, redis_url_for_integration):
        """token_bucket on real Redis blocks when bucket is empty."""
        await _flush_redis(redis_url_for_integration)

        plugin = _make_redis_plugin(redis_url_for_integration, algorithm="token_bucket", limit="3/s")
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(3):
            result = await plugin.tool_pre_invoke(payload, ctx)
            assert result.violation is None

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is not None
        assert result.violation.http_status_code == 429

    @pytest.mark.asyncio
    async def test_redis_token_bucket_shared_counter_across_instances(self, redis_url_for_integration):
        """Two token_bucket plugin instances share bucket state via Redis.

        After instance A drains the bucket, instance B must be blocked because
        they share the same Redis hash key.
        """
        await _flush_redis(redis_url_for_integration)

        plugin_a = _make_redis_plugin(redis_url_for_integration, algorithm="token_bucket", limit="3/s")
        plugin_b = _make_redis_plugin(redis_url_for_integration, algorithm="token_bucket", limit="3/s")
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        for _ in range(3):
            result = await plugin_a.tool_pre_invoke(payload, ctx)
            assert result.violation is None

        result = await plugin_b.tool_pre_invoke(payload, ctx)
        assert result.violation is not None, "token_bucket Redis backend must share bucket state across instances — " "instance B must be blocked after instance A drains the bucket"

    @pytest.mark.asyncio
    async def test_redis_token_bucket_refills_over_time(self, redis_url_for_integration):
        """After the bucket drains, tokens refill over time and requests are allowed again."""
        await _flush_redis(redis_url_for_integration)

        plugin = _make_redis_plugin(redis_url_for_integration, algorithm="token_bucket", limit="2/s")
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = ToolPreInvokePayload(name="tool", arguments={})

        await plugin.tool_pre_invoke(payload, ctx)
        await plugin.tool_pre_invoke(payload, ctx)
        blocked = await plugin.tool_pre_invoke(payload, ctx)
        assert blocked.violation is not None

        await asyncio.sleep(1.1)

        result = await plugin.tool_pre_invoke(payload, ctx)
        assert result.violation is None, "After tokens refill over time, token_bucket Redis backend must allow requests again"


# =============================================================================
# Auth boundary deny-path tests (HTTP level)
# =============================================================================


class TestRateLimiterAuthBoundary:
    """Deny-path tests: unauthenticated requests must get 401 before
    reaching the rate limiter.  These use the FastAPI TestClient fixture.
    """

    def test_unauthenticated_prompt_request_returns_401(self, client):
        """Unauthenticated request to /api/v1/prompts/ must receive 401."""
        response = client.get(PROMPT_ENDPOINT)
        assert response.status_code == 401, "Unauthenticated request must be rejected with 401 before hitting rate limiter"

    def test_unauthenticated_tool_invoke_returns_401(self, client):
        """Unauthenticated request to /api/v1/tools/invoke must receive 401."""
        response = client.post(TOOL_INVOKE_ENDPOINT, json={"name": "test", "arguments": {}})
        assert response.status_code == 401, "Unauthenticated tool invoke must be rejected with 401 before hitting rate limiter"
