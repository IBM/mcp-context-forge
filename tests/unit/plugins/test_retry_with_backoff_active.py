# -*- coding: utf-8 -*-
"""Tests for Retry With Backoff (Active) Plugin.

Verifies:
1. _compute_delay_ms — no-jitter exact values, jitter range, exponential growth, cap
2. _is_failure — isError flag, status_code variants, non-retriable codes, non-dict
3. _cfg_for — base config passthrough, per-tool override merging
4. RetryWithBackoffPlugin.__init__ — max_retries clamping, tool_overrides clamping
5. tool_post_invoke — first failure signals retry, exhaustion gives up, success resets state
6. State isolation — _STATE cleared between tests
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch

from plugins.retry_with_backoff_active.retry_with_backoff_active import (
    RetryWithBackoffPlugin,
    RetryConfig,
    _ToolRetryState,
    _STATE,
    _get_state,
    _cfg_for,
    _compute_delay_ms,
    _is_failure,
)
from mcpgateway.plugins.framework import (
    PluginConfig,
    PluginContext,
    ToolPostInvokePayload,
    GlobalContext,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_state():
    """Wipe module-level _STATE before and after every test."""
    _STATE.clear()
    yield
    _STATE.clear()


def make_plugin(config_overrides: dict | None = None) -> RetryWithBackoffPlugin:
    """Build a plugin with default config, optionally overriding fields."""
    cfg = {
        "max_retries": 3,
        "backoff_base_ms": 200,
        "max_backoff_ms": 5000,
        "jitter": False,          # deterministic by default in tests
        "retry_on_status": [429, 500, 502, 503, 504],
        "tool_overrides": {},
    }
    if config_overrides:
        cfg.update(config_overrides)
    plugin_config = PluginConfig(
        id="test-retry",
        kind="retry_with_backoff_active",
        name="Test Retry Plugin",
        enabled=True,
        order=0,
        config=cfg,
    )
    return RetryWithBackoffPlugin(plugin_config)


def make_context() -> PluginContext:
    return PluginContext(plugin_id="test-retry", global_context=GlobalContext(request_id="req-1"))


def make_payload(tool: str, result: dict) -> ToolPostInvokePayload:
    return ToolPostInvokePayload(name=tool, result=result)


# ---------------------------------------------------------------------------
# 1. _compute_delay_ms
# ---------------------------------------------------------------------------

class TestComputeDelayMs:
    def test_no_jitter_returns_exact_ceiling(self):
        cfg = RetryConfig(backoff_base_ms=200, max_backoff_ms=5000, jitter=False)
        assert _compute_delay_ms(0, cfg) == 200   # base * 2^0
        assert _compute_delay_ms(1, cfg) == 400   # base * 2^1
        assert _compute_delay_ms(2, cfg) == 800   # base * 2^2

    def test_no_jitter_caps_at_max_backoff(self):
        cfg = RetryConfig(backoff_base_ms=200, max_backoff_ms=500, jitter=False)
        assert _compute_delay_ms(0, cfg) == 200
        assert _compute_delay_ms(1, cfg) == 400
        assert _compute_delay_ms(2, cfg) == 500   # capped — 800 > 500
        assert _compute_delay_ms(10, cfg) == 500  # still capped

    def test_jitter_returns_value_in_range(self):
        cfg = RetryConfig(backoff_base_ms=200, max_backoff_ms=5000, jitter=True)
        for _ in range(50):
            delay = _compute_delay_ms(0, cfg)
            assert 0 <= delay <= 200, f"jitter out of range: {delay}"

    def test_jitter_respects_cap(self):
        cfg = RetryConfig(backoff_base_ms=200, max_backoff_ms=300, jitter=True)
        for _ in range(50):
            delay = _compute_delay_ms(5, cfg)  # uncapped would be 200*32=6400
            assert 0 <= delay <= 300, f"jitter exceeded cap: {delay}"

    def test_exponential_growth_without_jitter(self):
        cfg = RetryConfig(backoff_base_ms=100, max_backoff_ms=100_000, jitter=False)
        delays = [_compute_delay_ms(i, cfg) for i in range(5)]
        assert delays == [100, 200, 400, 800, 1600]


# ---------------------------------------------------------------------------
# 2. _is_failure
# ---------------------------------------------------------------------------

class TestIsFailure:
    def setup_method(self):
        self.cfg = RetryConfig()

    def test_is_error_true_triggers_failure(self):
        assert _is_failure({"isError": True}, self.cfg) is True

    def test_is_error_false_is_not_failure(self):
        assert _is_failure({"isError": False}, self.cfg) is False

    def test_status_code_500_is_failure(self):
        assert _is_failure({"status_code": 500}, self.cfg) is True

    def test_statusCode_variant_is_failure(self):
        assert _is_failure({"statusCode": 503}, self.cfg) is True

    def test_status_variant_is_failure(self):
        assert _is_failure({"status": 429}, self.cfg) is True

    def test_status_400_is_not_retriable(self):
        assert _is_failure({"status_code": 400}, self.cfg) is False

    def test_status_404_is_not_retriable(self):
        assert _is_failure({"status_code": 404}, self.cfg) is False

    def test_status_200_is_not_failure(self):
        assert _is_failure({"status_code": 200}, self.cfg) is False

    def test_non_dict_result_is_not_failure(self):
        assert _is_failure("error string", self.cfg) is False
        assert _is_failure(None, self.cfg) is False
        assert _is_failure(42, self.cfg) is False

    def test_empty_dict_is_not_failure(self):
        assert _is_failure({}, self.cfg) is False

    def test_custom_retry_on_status(self):
        cfg = RetryConfig(retry_on_status=[408])
        assert _is_failure({"status_code": 408}, cfg) is True
        assert _is_failure({"status_code": 500}, cfg) is False  # not in custom list


# ---------------------------------------------------------------------------
# 3. _cfg_for
# ---------------------------------------------------------------------------

class TestCfgFor:
    def test_no_override_returns_same_object(self):
        cfg = RetryConfig()
        result = _cfg_for(cfg, "unknown_tool")
        assert result is cfg

    def test_override_merges_max_retries(self):
        cfg = RetryConfig(max_retries=3, tool_overrides={"my_tool": {"max_retries": 1}})
        merged = _cfg_for(cfg, "my_tool")
        assert merged.max_retries == 1
        assert merged.backoff_base_ms == cfg.backoff_base_ms  # base fields preserved

    def test_override_does_not_include_tool_overrides(self):
        cfg = RetryConfig(tool_overrides={"my_tool": {"max_retries": 1}})
        merged = _cfg_for(cfg, "my_tool")
        assert merged.tool_overrides == {}

    def test_other_tool_not_affected_by_override(self):
        cfg = RetryConfig(max_retries=3, tool_overrides={"tool_a": {"max_retries": 1}})
        result = _cfg_for(cfg, "tool_b")
        assert result is cfg
        assert result.max_retries == 3


# ---------------------------------------------------------------------------
# 4. Plugin __init__ — clamping
# ---------------------------------------------------------------------------

class TestPluginInit:
    def test_max_retries_not_clamped_when_within_ceiling(self):
        with patch("plugins.retry_with_backoff_active.retry_with_backoff_active.get_settings") as mock_settings:
            mock_settings.return_value.max_tool_retries = 5
            plugin = make_plugin({"max_retries": 3})
            assert plugin._cfg.max_retries == 3

    def test_max_retries_clamped_to_gateway_ceiling(self):
        with patch("plugins.retry_with_backoff_active.retry_with_backoff_active.get_settings") as mock_settings:
            mock_settings.return_value.max_tool_retries = 2
            plugin = make_plugin({"max_retries": 5})
            assert plugin._cfg.max_retries == 2

    def test_tool_override_max_retries_clamped(self):
        with patch("plugins.retry_with_backoff_active.retry_with_backoff_active.get_settings") as mock_settings:
            mock_settings.return_value.max_tool_retries = 2
            plugin = make_plugin({
                "max_retries": 2,
                "tool_overrides": {"slow_api": {"max_retries": 10}},
            })
            assert plugin._cfg.tool_overrides["slow_api"]["max_retries"] == 2

    def test_clamping_emits_warning(self, caplog):
        import logging
        with patch("plugins.retry_with_backoff_active.retry_with_backoff_active.get_settings") as mock_settings:
            mock_settings.return_value.max_tool_retries = 1
            with caplog.at_level(logging.WARNING):
                make_plugin({"max_retries": 5})
            assert "clamping" in caplog.text


# ---------------------------------------------------------------------------
# 5. tool_post_invoke — core behaviour
# ---------------------------------------------------------------------------

class TestToolPostInvoke:
    @pytest.mark.asyncio
    async def test_success_returns_no_retry(self):
        plugin = make_plugin()
        ctx = make_context()
        payload = make_payload("tool_a", {"result": "ok"})
        result = await plugin.tool_post_invoke(payload, ctx)
        assert result.retry_delay_ms == 0

    @pytest.mark.asyncio
    async def test_first_failure_requests_retry(self):
        plugin = make_plugin()
        ctx = make_context()
        payload = make_payload("tool_a", {"isError": True})
        result = await plugin.tool_post_invoke(payload, ctx)
        assert result.retry_delay_ms > 0

    @pytest.mark.asyncio
    async def test_delay_grows_on_consecutive_failures(self):
        plugin = make_plugin({"jitter": False, "backoff_base_ms": 100})
        ctx = make_context()
        # failure 1: attempt=0 → 100ms
        r1 = await plugin.tool_post_invoke(make_payload("t", {"isError": True}), ctx)
        # failure 2: attempt=1 → 200ms
        r2 = await plugin.tool_post_invoke(make_payload("t", {"isError": True}), ctx)
        assert r2.retry_delay_ms > r1.retry_delay_ms

    @pytest.mark.asyncio
    async def test_exhausted_retries_returns_zero_delay(self):
        """After max_retries failures, plugin gives up (retry_delay_ms=0)."""
        plugin = make_plugin({"max_retries": 2})
        ctx = make_context()
        payload = make_payload("tool_a", {"isError": True})
        # 2 failures → still within budget
        await plugin.tool_post_invoke(payload, ctx)
        await plugin.tool_post_invoke(payload, ctx)
        # 3rd failure → exhausted
        result = await plugin.tool_post_invoke(payload, ctx)
        assert result.retry_delay_ms == 0

    @pytest.mark.asyncio
    async def test_success_resets_failure_counter(self):
        plugin = make_plugin({"max_retries": 1})
        ctx = make_context()
        # Exhaust retries
        await plugin.tool_post_invoke(make_payload("t", {"isError": True}), ctx)
        await plugin.tool_post_invoke(make_payload("t", {"isError": True}), ctx)
        # Simulate success (gateway gave up, tool eventually succeeded)
        await plugin.tool_post_invoke(make_payload("t", {"result": "ok"}), ctx)
        # State should be reset — next failure should retry again
        state = _get_state("t")
        assert state.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_per_tool_override_is_applied(self):
        """A tool with max_retries=1 override should exhaust after 1 retry."""
        plugin = make_plugin({
            "max_retries": 3,
            "tool_overrides": {"fragile_tool": {"max_retries": 1}},
        })
        ctx = make_context()
        # 1st failure: within budget
        r1 = await plugin.tool_post_invoke(make_payload("fragile_tool", {"isError": True}), ctx)
        assert r1.retry_delay_ms > 0
        # 2nd failure: exhausted (override max_retries=1)
        r2 = await plugin.tool_post_invoke(make_payload("fragile_tool", {"isError": True}), ctx)
        assert r2.retry_delay_ms == 0

    @pytest.mark.asyncio
    async def test_different_tools_have_independent_state(self):
        plugin = make_plugin({"max_retries": 1})
        ctx = make_context()
        # tool_a exhausts retries
        await plugin.tool_post_invoke(make_payload("tool_a", {"isError": True}), ctx)
        await plugin.tool_post_invoke(make_payload("tool_a", {"isError": True}), ctx)
        # tool_b is unaffected
        r = await plugin.tool_post_invoke(make_payload("tool_b", {"isError": True}), ctx)
        assert r.retry_delay_ms > 0

    @pytest.mark.asyncio
    async def test_status_code_failure_triggers_retry(self):
        plugin = make_plugin()
        ctx = make_context()
        result = await plugin.tool_post_invoke(make_payload("t", {"status_code": 503}), ctx)
        assert result.retry_delay_ms > 0

    @pytest.mark.asyncio
    async def test_non_retriable_status_does_not_retry(self):
        plugin = make_plugin()
        ctx = make_context()
        result = await plugin.tool_post_invoke(make_payload("t", {"status_code": 400}), ctx)
        assert result.retry_delay_ms == 0


# ---------------------------------------------------------------------------
# 6. _get_state
# ---------------------------------------------------------------------------

class TestGetState:
    def test_creates_fresh_state_for_new_tool(self):
        st = _get_state("brand_new_tool")
        assert st.consecutive_failures == 0
        assert st.last_failure_at == 0.0

    def test_returns_same_object_on_second_call(self):
        s1 = _get_state("tool_x")
        s1.consecutive_failures = 7
        s2 = _get_state("tool_x")
        assert s2.consecutive_failures == 7
        assert s1 is s2
