# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/rate_limiter/test_rate_limiter.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the packaged rate limiter plugin.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from cpex_rate_limiter.rate_limiter import RateLimiterConfig, RateLimiterPlugin, _parse_rate
from mcpgateway.plugins.framework import GlobalContext, PluginConfig, PluginContext, PromptHookType, PromptPrehookPayload, ToolHookType, ToolPreInvokePayload


def make_plugin(config: dict | None = None) -> RateLimiterPlugin:
    return RateLimiterPlugin(
        PluginConfig(
            name="rl",
            kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=[PromptHookType.PROMPT_PRE_FETCH, ToolHookType.TOOL_PRE_INVOKE],
            config=config or {},
        )
    )


def make_context(*, request_id: str = "r1", user: str = "u1", tenant_id: str | None = None) -> PluginContext:
    return PluginContext(global_context=GlobalContext(request_id=request_id, user=user, tenant_id=tenant_id))


class TestParseRate:
    def test_seconds_short(self):
        assert _parse_rate("10/s") == (10, 1)

    def test_minutes_medium(self):
        assert _parse_rate("60/min") == (60, 60)

    def test_hours_long(self):
        assert _parse_rate("100/hour") == (100, 3600)

    def test_invalid_unit_raises(self):
        with pytest.raises(ValueError, match='expected "<count>/<unit>"'):
            _parse_rate("10/d")

    def test_invalid_count_raises(self):
        with pytest.raises(ValueError):
            _parse_rate("0/s")


class TestRateLimiterConfig:
    def test_defaults_match_packaged_config(self):
        cfg = RateLimiterConfig()
        assert cfg.by_user is None
        assert cfg.by_tenant is None
        assert cfg.by_tool is None
        assert cfg.algorithm == "fixed_window"
        assert cfg.backend == "memory"
        assert cfg.redis_url is None
        assert cfg.redis_key_prefix == "rl"

    def test_overrides_are_applied(self):
        cfg = RateLimiterConfig(by_user="10/s", backend="redis", redis_url="redis://localhost:6379/0")
        assert cfg.by_user == "10/s"
        assert cfg.backend == "redis"
        assert cfg.redis_url == "redis://localhost:6379/0"


class TestRateLimiterPlugin:
    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_blocks_on_third_call(self):
        plugin = make_plugin({"by_user": "2/s"})
        ctx = make_context()
        payload = PromptPrehookPayload(prompt_id="p", args={})

        first = await plugin.prompt_pre_fetch(payload, ctx)
        second = await plugin.prompt_pre_fetch(payload, ctx)
        third = await plugin.prompt_pre_fetch(payload, ctx)

        assert first.violation is None
        assert second.violation is None
        assert third.continue_processing is False
        assert third.violation is not None
        assert third.violation.code == "RATE_LIMIT"
        assert third.violation.http_status_code == 429
        assert third.violation.http_headers["Retry-After"] == "1"

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_success_includes_rate_limit_headers(self):
        plugin = make_plugin({"by_user": "10/s"})
        ctx = make_context()
        payload = PromptPrehookPayload(prompt_id="p", args={})

        result = await plugin.prompt_pre_fetch(payload, ctx)

        assert result.violation is None
        assert result.http_headers["X-RateLimit-Limit"] == "10"
        assert result.http_headers["X-RateLimit-Remaining"] == "9"
        assert "Retry-After" not in result.http_headers
        assert int(result.http_headers["X-RateLimit-Reset"]) > 0

    @pytest.mark.asyncio
    async def test_tool_pre_invoke_applies_per_tool_limit(self):
        plugin = make_plugin({"by_user": "100/s", "by_tool": {"restricted_tool": "1/s"}})
        ctx = make_context(request_id="r2")
        restricted_payload = ToolPreInvokePayload(name="restricted_tool", arguments={})
        unrestricted_payload = ToolPreInvokePayload(name="other_tool", arguments={})

        first = await plugin.tool_pre_invoke(restricted_payload, ctx)
        second = await plugin.tool_pre_invoke(restricted_payload, ctx)
        third = await plugin.tool_pre_invoke(unrestricted_payload, ctx)

        assert first.violation is None
        assert second.violation is not None
        assert second.violation.http_status_code == 429
        assert third.violation is None

    @pytest.mark.asyncio
    async def test_tool_pre_invoke_applies_tenant_limit_when_present(self):
        plugin = make_plugin({"by_user": "100/s", "by_tenant": "1/s"})
        payload = ToolPreInvokePayload(name="search", arguments={})

        tenant_a = make_context(request_id="r3", user="u1", tenant_id="tenant-a")
        tenant_b = make_context(request_id="r4", user="u1", tenant_id="tenant-b")

        first = await plugin.tool_pre_invoke(payload, tenant_a)
        second = await plugin.tool_pre_invoke(payload, tenant_a)
        third = await plugin.tool_pre_invoke(payload, tenant_b)

        assert first.violation is None
        assert second.violation is not None
        assert third.violation is None

    @pytest.mark.asyncio
    async def test_tool_pre_invoke_skips_tenant_dimension_when_missing(self):
        plugin = make_plugin({"by_user": "100/s", "by_tenant": "1/s"})
        payload = ToolPreInvokePayload(name="search", arguments={})
        ctx = make_context(request_id="r5", tenant_id=None)

        first = await plugin.tool_pre_invoke(payload, ctx)
        second = await plugin.tool_pre_invoke(payload, ctx)

        assert first.violation is None
        assert second.violation is None

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_uses_packaged_core(self):
        plugin = make_plugin({"by_user": "5/s"})
        payload = PromptPrehookPayload(prompt_id="p", args={})
        ctx = make_context(request_id="r6")
        plugin._core = SimpleNamespace(prompt_pre_fetch=AsyncMock(return_value="sentinel"))

        result = await plugin.prompt_pre_fetch(payload, ctx)

        plugin._core.prompt_pre_fetch.assert_awaited_once_with(payload, ctx)
        assert result == "sentinel"

    @pytest.mark.asyncio
    async def test_tool_pre_invoke_uses_packaged_core(self):
        plugin = make_plugin({"by_user": "5/s"})
        payload = ToolPreInvokePayload(name="search", arguments={})
        ctx = make_context(request_id="r7")
        plugin._core = SimpleNamespace(tool_pre_invoke=AsyncMock(return_value="sentinel"))

        result = await plugin.tool_pre_invoke(payload, ctx)

        plugin._core.tool_pre_invoke.assert_awaited_once_with(payload, ctx)
        assert result == "sentinel"

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_fails_open_when_core_raises(self):
        plugin = make_plugin({"by_user": "5/s"})
        payload = PromptPrehookPayload(prompt_id="p", args={})
        ctx = make_context(request_id="r8")
        plugin._core = SimpleNamespace(prompt_pre_fetch=AsyncMock(side_effect=RuntimeError("boom")))

        result = await plugin.prompt_pre_fetch(payload, ctx)

        assert result.continue_processing is True
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_tool_pre_invoke_fails_open_when_core_raises(self):
        plugin = make_plugin({"by_user": "5/s"})
        payload = ToolPreInvokePayload(name="search", arguments={})
        ctx = make_context(request_id="r9")
        plugin._core = SimpleNamespace(tool_pre_invoke=AsyncMock(side_effect=RuntimeError("boom")))

        result = await plugin.tool_pre_invoke(payload, ctx)

        assert result.continue_processing is True
        assert result.violation is None
