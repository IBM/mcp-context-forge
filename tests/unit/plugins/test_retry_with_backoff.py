# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_retry_with_backoff.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Retry With Backoff Plugin.

Verifies:
1. _compute_delay_ms — no-jitter exact values, jitter range, exponential growth, cap
2. _is_failure — isError flag, status_code variants, non-retriable codes, non-dict
3. _cfg_for — base config passthrough, per-tool override merging
4. RetryWithBackoffPlugin.__init__ — max_retries clamping, tool_overrides clamping
5. tool_post_invoke — first failure signals retry, exhaustion gives up, success resets state
6. State isolation — unique request_id per make_context() call ensures natural key isolation
7. Execution-path selection — native state manager handles structured failures, local state path handles text-content inspection
8. retry_policy metadata — all return paths include advisory policy dict; resource_post_fetch hook
"""

import logging
import uuid
import pytest
from unittest.mock import MagicMock, patch

from cpex_retry_with_backoff.retry_with_backoff import (
    RetryWithBackoffPlugin,
    RetryConfig,
    _STATE,
    _STATE_TTL_SECONDS,
    _get_state,
    _del_state,
    _cfg_for,
    _compute_delay_ms,
    _is_failure,
)
from cpex.framework import (
    PluginConfig,
    PluginContext,
    ResourcePostFetchPayload,
    ToolPostInvokePayload,
    GlobalContext,
)
from mcpgateway.common.models import ResourceContent

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def make_plugin(config_overrides: dict | None = None) -> RetryWithBackoffPlugin:
    """Build a plugin with default config, optionally overriding fields.

    Args:
        config_overrides: Optional dict of config fields to override.

    Returns:
        Configured RetryWithBackoffPlugin instance.
    """
    cfg = {
        "max_retries": 3,
        "backoff_base_ms": 200,
        "max_backoff_ms": 5000,
        "jitter": False,  # deterministic by default in tests
        "retry_on_status": [429, 500, 502, 503, 504],
        "tool_overrides": {},
    }
    if config_overrides:
        cfg.update(config_overrides)
    plugin_config = PluginConfig(
        id="test-retry",
        kind="retry_with_backoff",
        name="Test Retry Plugin",
        enabled=True,
        order=0,
        config=cfg,
    )
    return RetryWithBackoffPlugin(plugin_config)


def make_context() -> PluginContext:
    # Unique request_id per call ensures each test's state entries never
    # collide with another test's, giving natural isolation without clearing.
    return PluginContext(plugin_id="test-retry", global_context=GlobalContext(request_id=str(uuid.uuid4())))


def make_payload(tool: str, result: dict) -> ToolPostInvokePayload:
    return ToolPostInvokePayload(name=tool, result=result)


# ---------------------------------------------------------------------------
# 1. _compute_delay_ms
# ---------------------------------------------------------------------------


class TestComputeDelayMs:
    def test_no_jitter_returns_exact_ceiling(self):
        cfg = RetryConfig(backoff_base_ms=200, max_backoff_ms=5000, jitter=False)
        assert _compute_delay_ms(0, cfg) == 200  # base * 2^0
        assert _compute_delay_ms(1, cfg) == 400  # base * 2^1
        assert _compute_delay_ms(2, cfg) == 800  # base * 2^2

    def test_no_jitter_caps_at_max_backoff(self):
        cfg = RetryConfig(backoff_base_ms=200, max_backoff_ms=500, jitter=False)
        assert _compute_delay_ms(0, cfg) == 200
        assert _compute_delay_ms(1, cfg) == 400
        assert _compute_delay_ms(2, cfg) == 500  # capped — 800 > 500
        assert _compute_delay_ms(10, cfg) == 500  # still capped

    def test_jitter_returns_value_within_cap(self):
        cfg = RetryConfig(backoff_base_ms=200, max_backoff_ms=300, jitter=True)
        delay = _compute_delay_ms(5, cfg)
        assert 0 <= delay <= 300

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

    def test_status_code_500_in_structured_content_is_failure(self):
        assert _is_failure({"isError": False, "structuredContent": {"status_code": 500}}, self.cfg) is True

    def test_status_400_in_structured_content_is_not_retriable(self):
        assert _is_failure({"isError": False, "structuredContent": {"status_code": 400}}, self.cfg) is False

    def test_status_200_in_structured_content_is_not_failure(self):
        assert _is_failure({"isError": False, "structuredContent": {"status_code": 200}}, self.cfg) is False

    def test_check_text_content_disabled_by_default(self):
        # check_text_content=false (default): text content with status_code NOT checked
        result = {
            "isError": False,
            "structuredContent": None,
            "content": [{"type": "text", "text": '{"status_code": 503, "message": "downstream down"}'}],
        }
        assert _is_failure(result, self.cfg) is False

    def test_check_text_content_enabled_retryable_status(self):
        cfg = RetryConfig(check_text_content=True)
        result = {
            "isError": False,
            "structuredContent": None,
            "content": [{"type": "text", "text": '{"status_code": 503, "message": "downstream down"}'}],
        }
        assert _is_failure(result, cfg) is True

    def test_check_text_content_enabled_non_retryable_status(self):
        cfg = RetryConfig(check_text_content=True)
        result = {
            "isError": False,
            "structuredContent": None,
            "content": [{"type": "text", "text": '{"status_code": 400, "message": "bad request"}'}],
        }
        assert _is_failure(result, cfg) is False

    def test_check_text_content_skipped_when_structured_content_present(self):
        # Text content parsing only runs when structuredContent is absent (None)
        # If structuredContent is present but has no failure, text content is NOT parsed
        cfg = RetryConfig(check_text_content=True)
        result = {
            "isError": False,
            "structuredContent": {"status_code": 200},  # present, not a failure
            "content": [{"type": "text", "text": '{"status_code": 503}'}],  # would be a failure if parsed
        }
        assert _is_failure(result, cfg) is False

    def test_check_text_content_invalid_json_ignored(self):
        cfg = RetryConfig(check_text_content=True)
        result = {
            "isError": False,
            "structuredContent": None,
            "content": [{"type": "text", "text": "not json at all"}],
        }
        assert _is_failure(result, cfg) is False

    def test_check_text_content_is_error_in_text(self):
        cfg = RetryConfig(check_text_content=True)
        result = {
            "isError": False,
            "structuredContent": None,
            "content": [{"type": "text", "text": '{"isError": true, "message": "failed"}'}],
        }
        assert _is_failure(result, cfg) is True

    def test_non_dict_result_is_not_failure(self):
        assert _is_failure("error string", self.cfg) is False
        assert _is_failure(None, self.cfg) is False
        assert _is_failure(42, self.cfg) is False

    def test_empty_dict_is_not_failure(self):
        assert _is_failure({}, self.cfg) is False

    def test_custom_retry_on_status(self):
        cfg = RetryConfig(retry_on_status=[408])
        assert _is_failure({"structuredContent": {"status_code": 408}}, cfg) is True
        assert _is_failure({"structuredContent": {"status_code": 500}}, cfg) is False  # not in custom list

    def test_structured_content_is_error_true_triggers_failure(self):
        # Signal 2: structuredContent.isError=True counts as a failure even
        # when the outer isError is False (nested error from a structured response).
        assert _is_failure({"isError": False, "structuredContent": {"isError": True}}, self.cfg) is True

    def test_structured_content_without_status_code_is_not_failure(self):
        # structuredContent present but contains neither isError nor status_code → not a failure.
        assert _is_failure({"isError": False, "structuredContent": {"result": "ok"}}, self.cfg) is False

    # -- Signal 1 status-code-aware tests --

    def test_is_error_with_retryable_status_triggers_failure(self):
        # isError=True + structuredContent.status_code in retry_on_status → retry.
        result = {"isError": True, "structuredContent": {"status_code": 503}}
        assert _is_failure(result, self.cfg) is True

    def test_is_error_with_non_retryable_status_skips_retry(self):
        # isError=True + status_code NOT in retry_on_status → not retryable.
        result = {"isError": True, "structuredContent": {"status_code": 400}}
        assert _is_failure(result, self.cfg) is False

    def test_is_error_with_404_skips_retry(self):
        result = {"isError": True, "structuredContent": {"status_code": 404}}
        assert _is_failure(result, self.cfg) is False

    def test_is_error_with_401_skips_retry(self):
        result = {"isError": True, "structuredContent": {"status_code": 401}}
        assert _is_failure(result, self.cfg) is False

    def test_is_error_without_status_code_always_retries(self):
        # isError=True with no structuredContent → generic exception → always retry.
        assert _is_failure({"isError": True}, self.cfg) is True
        assert _is_failure({"isError": True, "structuredContent": None}, self.cfg) is True

    def test_is_error_with_empty_structured_content_always_retries(self):
        # isError=True + structuredContent without status_code → still a generic error.
        result = {"isError": True, "structuredContent": {}}
        assert _is_failure(result, self.cfg) is True


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
        with patch("cpex_retry_with_backoff.retry_with_backoff.get_settings") as mock_settings:
            mock_settings.return_value.max_tool_retries = 5
            plugin = make_plugin({"max_retries": 3})
            assert plugin._cfg.max_retries == 3

    def test_max_retries_clamped_to_gateway_ceiling(self):
        with patch("cpex_retry_with_backoff.retry_with_backoff.get_settings") as mock_settings:
            mock_settings.return_value.max_tool_retries = 2
            plugin = make_plugin({"max_retries": 5})
            assert plugin._cfg.max_retries == 2

    def test_tool_override_max_retries_clamped(self):
        with patch("cpex_retry_with_backoff.retry_with_backoff.get_settings") as mock_settings:
            mock_settings.return_value.max_tool_retries = 2
            plugin = make_plugin(
                {
                    "max_retries": 2,
                    "tool_overrides": {"slow_api": {"max_retries": 10}},
                }
            )
            assert plugin._cfg.tool_overrides["slow_api"]["max_retries"] == 2

    def test_clamping_emits_warning(self, caplog):
        with patch("cpex_retry_with_backoff.retry_with_backoff.get_settings") as mock_settings:
            mock_settings.return_value.max_tool_retries = 1
            with caplog.at_level(logging.WARNING):
                make_plugin({"max_retries": 5})
            assert any(r.getMessage() == "retry_with_backoff: max_retries=5 exceeds gateway ceiling=1, clamping" for r in caplog.records)

    def test_max_retries_equal_ceiling_not_clamped(self):
        """max_retries exactly equal to the gateway ceiling must not be clamped."""
        with patch("cpex_retry_with_backoff.retry_with_backoff.get_settings") as mock_settings:
            mock_settings.return_value.max_tool_retries = 3
            plugin = make_plugin({"max_retries": 3})
            assert plugin._cfg.max_retries == 3


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
    async def test_exhaustion_resets_counter_for_next_call(self):
        """After exhaustion the counter resets so the next independent call gets a fresh retry budget."""
        plugin = make_plugin({"max_retries": 2, "jitter": False})
        ctx = make_context()
        payload = make_payload("tool_x", {"isError": True})
        # Exhaust: 3 failures (original + 2 retries)
        await plugin.tool_post_invoke(payload, ctx)
        await plugin.tool_post_invoke(payload, ctx)
        await plugin.tool_post_invoke(payload, ctx)  # exhausted, returns 0
        # Counter must be reset — next independent call should retry again
        r = await plugin.tool_post_invoke(payload, ctx)
        assert r.retry_delay_ms > 0, "next independent call must get a fresh retry, not be blocked by previous exhaustion"

    @pytest.mark.asyncio
    async def test_success_resets_failure_counter(self):
        """After a partial failure run followed by a success the state is cleared,
        so a subsequent failure on the same invocation must retry again."""
        plugin = make_plugin({"max_retries": 1, "jitter": False})
        ctx = make_context()
        # First failure — within budget
        r1 = await plugin.tool_post_invoke(make_payload("t", {"isError": True}), ctx)
        assert r1.retry_delay_ms > 0
        # Success — state is deleted (reset)
        await plugin.tool_post_invoke(make_payload("t", {"result": "ok"}), ctx)
        # Next failure on the same invocation must get a fresh retry budget
        r3 = await plugin.tool_post_invoke(make_payload("t", {"isError": True}), ctx)
        assert r3.retry_delay_ms > 0, "success must reset state so the next failure retries"

    @pytest.mark.asyncio
    async def test_per_tool_override_is_applied(self):
        """A tool with max_retries=1 override should exhaust after 1 retry."""
        plugin = make_plugin(
            {
                "max_retries": 3,
                "tool_overrides": {"fragile_tool": {"max_retries": 1}},
            }
        )
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
        result = await plugin.tool_post_invoke(make_payload("t", {"structuredContent": {"status_code": 503}}), ctx)
        assert result.retry_delay_ms > 0

    @pytest.mark.asyncio
    async def test_non_retriable_status_does_not_retry(self):
        plugin = make_plugin()
        ctx = make_context()
        result = await plugin.tool_post_invoke(make_payload("t", {"structuredContent": {"status_code": 400}}), ctx)
        assert result.retry_delay_ms == 0

    @pytest.mark.asyncio
    async def test_max_retries_zero_gives_up_immediately(self):
        """max_retries=0 means no retries at all — every failure must return delay=0."""
        plugin = make_plugin({"max_retries": 0})
        ctx = make_context()
        result = await plugin.tool_post_invoke(make_payload("t", {"isError": True}), ctx)
        assert result.retry_delay_ms == 0


# ---------------------------------------------------------------------------
# 6. _get_state
# ---------------------------------------------------------------------------


class TestGetState:
    def test_creates_fresh_state_for_new_tool(self):
        st = _get_state("brand_new_tool", "req-fresh")
        assert st.consecutive_failures == 0
        assert st.last_failure_at == 0.0

    def test_returns_same_object_on_second_call(self):
        s1 = _get_state("tool_x", "req-same")
        s1.consecutive_failures = 7
        s2 = _get_state("tool_x", "req-same")
        assert s2.consecutive_failures == 7
        assert s1 is s2

    def test_ttl_eviction_removes_stale_entries(self):
        """Entries whose last_failure_at is older than _STATE_TTL_SECONDS are evicted."""
        import time

        key = "evict_tool:evict_req"
        # Inject a stale entry directly into _STATE
        from cpex_retry_with_backoff.retry_with_backoff import _ToolRetryState

        _STATE[key] = _ToolRetryState(consecutive_failures=3, last_failure_at=time.monotonic() - _STATE_TTL_SECONDS - 1)
        assert key in _STATE
        # _get_state triggers eviction
        _get_state("other_tool", "other_req")
        assert key not in _STATE, "stale entry should have been evicted"
        # Clean up
        _del_state("other_tool", "other_req")

    def test_ttl_eviction_preserves_fresh_entries(self):
        """Entries within the TTL window are not evicted."""
        import time

        key = "fresh_tool:fresh_req"
        from cpex_retry_with_backoff.retry_with_backoff import _ToolRetryState

        _STATE[key] = _ToolRetryState(consecutive_failures=1, last_failure_at=time.monotonic())
        _get_state("other_tool2", "other_req2")
        assert key in _STATE, "fresh entry should not be evicted"
        # Clean up
        _STATE.pop(key, None)
        _del_state("other_tool2", "other_req2")


# ---------------------------------------------------------------------------
# 7. Execution-path selection
# ---------------------------------------------------------------------------


class TestExecutionPathSelection:
    """Verify the plugin uses the correct state-management path for each signal type."""

    @pytest.mark.asyncio
    async def test_local_state_path_handles_absent_native_manager(self):
        """The local state path (check_text_content=True) must retry correctly without a native manager."""
        plugin = make_plugin({"check_text_content": True})
        ctx = make_context()

        with patch.object(plugin, "_rust", None):
            r1 = await plugin.tool_post_invoke(make_payload("t", {"isError": True}), ctx)
            assert r1.retry_delay_ms > 0, "local state path should request a retry on first failure"

            r2 = await plugin.tool_post_invoke(make_payload("t", {"result": "ok"}), ctx)
            assert r2.retry_delay_ms == 0, "local state path should return 0 on success"

    @pytest.mark.asyncio
    async def test_native_state_manager_handles_structured_failures(self):
        """Without text-content parsing the plugin should delegate retry tracking to the native state manager."""
        plugin = make_plugin()
        ctx = make_context()

        # Mock the instance-level _rust so we can assert it was called,
        # regardless of whether the .so is present.
        mock_rust = MagicMock()
        mock_rust.check_and_update.return_value = (True, 300)

        with patch.object(plugin, "_rust", mock_rust):
            r = await plugin.tool_post_invoke(make_payload("t", {"isError": True}), ctx)

        mock_rust.check_and_update.assert_called_once()
        assert r.retry_delay_ms == 300

    @pytest.mark.asyncio
    async def test_text_content_checks_bypass_native_state_manager(self):
        """When check_text_content=True the plugin must use the local state path even when the native manager exists."""
        plugin = make_plugin({"check_text_content": True})
        ctx = make_context()

        mock_rust = MagicMock()
        mock_rust.check_and_update.return_value = (True, 300)

        with patch.object(plugin, "_rust", mock_rust):
            await plugin.tool_post_invoke(make_payload("t", {"isError": True}), ctx)

        mock_rust.check_and_update.assert_not_called()


# ---------------------------------------------------------------------------
# 8. retry_policy metadata
# ---------------------------------------------------------------------------


class TestRetryPolicyMetadata:
    """Verify that retry_policy metadata is attached on every tool_post_invoke
    return path and on resource_post_fetch."""

    @pytest.mark.asyncio
    async def test_success_path_includes_policy_metadata(self):
        plugin = make_plugin({"max_retries": 2, "backoff_base_ms": 100, "max_backoff_ms": 1000, "retry_on_status": [429, 503]})
        ctx = make_context()
        result = await plugin.tool_post_invoke(make_payload("t", {"result": "ok"}), ctx)
        assert result.metadata["retry_policy"] == {
            "max_retries": 2,
            "backoff_base_ms": 100,
            "max_backoff_ms": 1000,
            "retry_on_status": [429, 503],
        }

    @pytest.mark.asyncio
    async def test_failure_retry_path_includes_policy_metadata(self):
        plugin = make_plugin({"max_retries": 3, "backoff_base_ms": 200, "max_backoff_ms": 5000, "retry_on_status": [500]})
        ctx = make_context()
        result = await plugin.tool_post_invoke(make_payload("t", {"isError": True}), ctx)
        assert result.retry_delay_ms > 0
        assert result.metadata["retry_policy"] == {
            "max_retries": 3,
            "backoff_base_ms": 200,
            "max_backoff_ms": 5000,
            "retry_on_status": [500],
        }

    @pytest.mark.asyncio
    async def test_exhaustion_path_includes_policy_metadata(self):
        plugin = make_plugin({"max_retries": 1, "backoff_base_ms": 200, "max_backoff_ms": 5000, "retry_on_status": [503]})
        ctx = make_context()
        payload = make_payload("t", {"isError": True})
        await plugin.tool_post_invoke(payload, ctx)  # failure 1 — within budget
        result = await plugin.tool_post_invoke(payload, ctx)  # failure 2 — exhausted
        assert result.retry_delay_ms == 0
        assert result.metadata["retry_policy"] == {
            "max_retries": 1,
            "backoff_base_ms": 200,
            "max_backoff_ms": 5000,
            "retry_on_status": [503],
        }

    @pytest.mark.asyncio
    async def test_resource_post_fetch_returns_policy_metadata(self):
        plugin = make_plugin({"max_retries": 2, "backoff_base_ms": 150, "max_backoff_ms": 3000, "retry_on_status": [503]})
        ctx = make_context()
        content = ResourceContent(type="resource", id="r1", uri="file:///data.txt", text="hello")
        payload = ResourcePostFetchPayload(uri="file:///data.txt", content=content)
        result = await plugin.resource_post_fetch(payload, ctx)
        assert result.metadata["retry_policy"] == {
            "max_retries": 2,
            "backoff_base_ms": 150,
            "max_backoff_ms": 3000,
            "retry_on_status": [503],
        }
