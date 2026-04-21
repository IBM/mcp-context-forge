# -*- coding: utf-8 -*-
"""Tests for Retry With Backoff Plugin.

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
from mcpgateway.plugins.framework import (
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
# 2. _is_failure
# ---------------------------------------------------------------------------


class TestIsFailure:
    def setup_method(self):
        self.cfg = RetryConfig()



    def test_check_text_content_disabled_by_default(self):
        # check_text_content=false (default): text content with status_code NOT checked
        result = {
            "isError": False,
            "structuredContent": None,
            "content": [{"type": "text", "text": '{"status_code": 503, "message": "downstream down"}'}],
        }
        assert _is_failure(result, self.cfg) is False


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



    def test_custom_retry_on_status(self):
        cfg = RetryConfig(retry_on_status=[408])
        assert _is_failure({"structuredContent": {"status_code": 408}}, cfg) is True
        assert _is_failure({"structuredContent": {"status_code": 500}}, cfg) is False  # not in custom list



    # -- Signal 1 status-code-aware tests --

    def test_is_error_with_retryable_status_triggers_failure(self):
        # isError=True + structuredContent.status_code in retry_on_status → retry.
        result = {"isError": True, "structuredContent": {"status_code": 503}}
        assert _is_failure(result, self.cfg) is True


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





# ---------------------------------------------------------------------------
# 4. Plugin __init__ — clamping
# ---------------------------------------------------------------------------


class TestPluginInit:
    def test_max_retries_not_clamped_when_within_ceiling(self):
        with patch("cpex_retry_with_backoff.retry_with_backoff.get_settings") as mock_settings:
            mock_settings.return_value.max_tool_retries = 5
            plugin = make_plugin({"max_retries": 3})
            assert plugin._cfg.max_retries == 3


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
    async def test_delay_grows_on_consecutive_failures(self):
        plugin = make_plugin({"jitter": False, "backoff_base_ms": 100})
        ctx = make_context()
        # failure 1: attempt=0 → 100ms
        r1 = await plugin.tool_post_invoke(make_payload("t", {"isError": True}), ctx)
        # failure 2: attempt=1 → 200ms
        r2 = await plugin.tool_post_invoke(make_payload("t", {"isError": True}), ctx)
        assert r2.retry_delay_ms > r1.retry_delay_ms





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



# ---------------------------------------------------------------------------
# 6. _get_state
# ---------------------------------------------------------------------------


class TestGetState:

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


