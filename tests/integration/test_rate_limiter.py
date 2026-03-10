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

import asyncio
import time
from typing import AsyncIterator, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from mcpgateway.main import app
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    PromptPrehookPayload,
    ToolPreInvokePayload,
)
from mcpgateway.utils.create_jwt_token import _create_jwt_token
from plugins.rate_limiter.rate_limiter import RateLimiterPlugin, _store


# API Endpoints
PROMPT_ENDPOINT = "/api/v1/prompts/"
TOOL_INVOKE_ENDPOINT = "/api/v1/tools/invoke"


@pytest.fixture(autouse=True)
def clear_rate_limit_store():
    """Clear rate limit store before and after each test."""
    _store.clear()
    yield
    _store.clear()


@pytest.fixture
def jwt_token_alice():
    """JWT token for user alice in team1."""
    return _create_jwt_token(
        {"sub": "alice", "username": "alice"},
        expires_in_minutes=60,
        user_data={"email": "alice@example.com", "full_name": "Alice", "is_admin": False, "auth_provider": "test"},
        teams=["team1"],
    )


@pytest.fixture
def jwt_token_bob():
    """JWT token for user bob in team2."""
    return _create_jwt_token(
        {"sub": "bob", "username": "bob"},
        expires_in_minutes=60,
        user_data={"email": "bob@example.com", "full_name": "Bob", "is_admin": False, "auth_provider": "test"},
        teams=["team2"],
    )


@pytest.fixture
def rate_limit_plugin_2_per_second():
    """Rate limiter plugin configured for 2 requests per second."""
    config = PluginConfig(
        name="RateLimiter",
        kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
        hooks=["prompt_pre_fetch", "tool_pre_invoke"],
        priority=100,
        config={
            "by_user": "2/s",
            "by_tenant": None,
            "by_tool": {}
        }
    )
    return RateLimiterPlugin(config)


@pytest.fixture
def rate_limit_plugin_multi_dimensional():
    """Rate limiter plugin with multi-dimensional limits."""
    config = PluginConfig(
        name="RateLimiter",
        kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
        hooks=["prompt_pre_fetch", "tool_pre_invoke"],
        priority=100,
        config={
            "by_user": "10/s",
            "by_tenant": "5/s",
            "by_tool": {
                "restricted_tool": "1/s"
            }
        }
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
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["prompt_pre_fetch"],
            priority=100,
            config={
                "by_user": "10/s",
                "by_tenant": None,  # No tenant limit
                "by_tool": {}
            }
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
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["prompt_pre_fetch"],
            priority=100,
            config={
                "by_user": "10/s",  # More permissive
                "by_tenant": "2/s",  # More restrictive
            }
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
        """Verify store is cleaned up between tests."""
        # Store should be empty at start (autouse fixture)
        assert len(_store) == 0

        plugin = rate_limit_plugin_2_per_second
        ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        payload = PromptPrehookPayload(prompt_id="test", args={})

        # Make a request
        await plugin.prompt_pre_fetch(payload, ctx)

        # Store should have entries
        assert len(_store) > 0

    @pytest.mark.asyncio
    async def test_multiple_users_create_separate_windows(self, rate_limit_plugin_2_per_second):
        """Verify multiple users create separate windows in store."""
        plugin = rate_limit_plugin_2_per_second

        ctx_alice = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
        ctx_bob = PluginContext(global_context=GlobalContext(request_id="r2", user="bob"))
        payload = PromptPrehookPayload(prompt_id="test", args={})

        # Make requests from both users
        await plugin.prompt_pre_fetch(payload, ctx_alice)
        await plugin.prompt_pre_fetch(payload, ctx_bob)

        # Store should have entries for both users
        assert len(_store) >= 2
