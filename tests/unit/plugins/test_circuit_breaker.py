# -*- coding: utf-8 -*-
"""Tests for Circuit Breaker Plugin.

Verifies all functionality:
1. Closed state - allows requests
2. Opens on consecutive failures
3. Opens on error rate threshold
4. Blocks requests when open
5. Half-open state - allows probe request
6. Closes on successful probe
7. Reopens on failed probe
8. Timeout failures trigger circuit breaker
9. retry_after_seconds calculation
10. Per-tool configuration overrides
"""

import asyncio
import pytest
import time
from unittest.mock import MagicMock, patch

# Import the circuit breaker components
from plugins.circuit_breaker.circuit_breaker import (
    CircuitBreakerPlugin,
    CircuitBreakerConfig,
    _ToolState,
    _STATE,
    _get_state,
    _cfg_for,
    _is_error,
)
from mcpgateway.plugins.framework import (
    PluginConfig,
    PluginContext,
    ToolPreInvokePayload,
    ToolPostInvokePayload,
    GlobalContext,
)


@pytest.fixture(autouse=True)
def clear_state():
    """Clear circuit breaker state before each test."""
    _STATE.clear()
    yield
    _STATE.clear()


@pytest.fixture
def plugin():
    """Create a circuit breaker plugin with test configuration."""
    config = PluginConfig(
        id="test-cb",
        kind="circuit_breaker",
        name="Test Circuit Breaker",
        enabled=True,
        order=0,
        config={
            "error_rate_threshold": 0.5,
            "window_seconds": 60,
            "min_calls": 3,
            "consecutive_failure_threshold": 3,
            "cooldown_seconds": 30,
        },
    )
    return CircuitBreakerPlugin(config)


@pytest.fixture
def context():
    """Create a plugin context for testing."""
    global_ctx = GlobalContext(request_id="test-request-123")
    return PluginContext(plugin_id="test-cb", global_context=global_ctx)


class TestCircuitBreakerClosedState:
    """Test circuit breaker in closed state."""

    @pytest.mark.asyncio
    async def test_allows_requests_when_closed(self, plugin, context):
        """Closed circuit should allow requests through."""
        payload = ToolPreInvokePayload(name="test_tool", args={})
        result = await plugin.tool_pre_invoke(payload, context)

        assert result.continue_processing is True
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_records_call_timestamp(self, plugin, context):
        """Pre-invoke should record call timestamp in context."""
        payload = ToolPreInvokePayload(name="test_tool", args={})
        await plugin.tool_pre_invoke(payload, context)

        call_time = context.get_state("cb_call_time")
        assert call_time is not None
        assert abs(call_time - time.time()) < 1  # Within 1 second


class TestCircuitBreakerOpening:
    """Test circuit breaker opening conditions."""

    @pytest.mark.asyncio
    async def test_opens_on_consecutive_failures(self, plugin, context):
        """Circuit should open after consecutive_failure_threshold failures."""
        tool = "test_tool"

        # Simulate 3 consecutive failures
        for _ in range(3):
            pre_payload = ToolPreInvokePayload(name=tool, args={})
            await plugin.tool_pre_invoke(pre_payload, context)

            post_payload = ToolPostInvokePayload(name=tool, result={"is_error": True})
            result = await plugin.tool_post_invoke(post_payload, context)

        # Check circuit is now open
        assert result.metadata["circuit_open_until"] > 0
        assert result.metadata["circuit_consecutive_failures"] == 3

    @pytest.mark.asyncio
    async def test_opens_on_error_rate_threshold(self, plugin, context):
        """Circuit should open when error rate exceeds threshold."""
        tool = "test_tool"

        # Simulate 3 calls (min_calls): 2 failures, 1 success = 66% error rate > 50% threshold
        for i in range(3):
            pre_payload = ToolPreInvokePayload(name=tool, args={})
            await plugin.tool_pre_invoke(pre_payload, context)

            is_error = i < 2  # First 2 are failures
            post_payload = ToolPostInvokePayload(name=tool, result={"is_error": is_error})
            result = await plugin.tool_post_invoke(post_payload, context)

        # Check circuit is now open
        assert result.metadata["circuit_open_until"] > 0
        assert result.metadata["circuit_failure_rate"] >= 0.5


class TestCircuitBreakerOpenState:
    """Test circuit breaker in open state."""

    @pytest.mark.asyncio
    async def test_blocks_requests_when_open(self, plugin, context):
        """Open circuit should block requests."""
        tool = "test_tool"
        st = _get_state(tool)
        st.open_until = time.time() + 30  # Open for 30 seconds

        payload = ToolPreInvokePayload(name=tool, args={})
        result = await plugin.tool_pre_invoke(payload, context)

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "CIRCUIT_OPEN"

    @pytest.mark.asyncio
    async def test_returns_retry_after_seconds(self, plugin, context):
        """Open circuit should return retry_after_seconds in violation details."""
        tool = "test_tool"
        st = _get_state(tool)
        st.open_until = time.time() + 30  # Open for 30 seconds

        payload = ToolPreInvokePayload(name=tool, args={})
        result = await plugin.tool_pre_invoke(payload, context)

        assert result.violation is not None
        assert "retry_after_seconds" in result.violation.details
        assert result.violation.details["retry_after_seconds"] > 0
        assert result.violation.details["retry_after_seconds"] <= 30


class TestCircuitBreakerHalfOpenState:
    """Test circuit breaker half-open state."""

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_cooldown(self, plugin, context):
        """Circuit should transition to half-open after cooldown."""
        tool = "test_tool"
        st = _get_state(tool)
        st.open_until = time.time() - 1  # Cooldown elapsed
        st.consecutive_failures = 5

        payload = ToolPreInvokePayload(name=tool, args={})
        result = await plugin.tool_pre_invoke(payload, context)

        # Should allow request through (half-open)
        assert result.continue_processing is True
        assert st.half_open is True
        assert context.get_state("cb_half_open_test") is True

    @pytest.mark.asyncio
    async def test_closes_on_successful_probe(self, plugin, context):
        """Half-open circuit should close on successful probe."""
        tool = "test_tool"
        st = _get_state(tool)
        st.half_open = True
        st.consecutive_failures = 5

        # Set context for half-open test
        context.set_state("cb_half_open_test", True)
        context.set_state("cb_call_time", time.time())

        # Successful probe
        post_payload = ToolPostInvokePayload(name=tool, result={"is_error": False})
        result = await plugin.tool_post_invoke(post_payload, context)

        # Circuit should be fully closed
        assert st.half_open is False
        assert st.consecutive_failures == 0
        assert result.metadata["circuit_open_until"] == 0.0

    @pytest.mark.asyncio
    async def test_reopens_on_failed_probe(self, plugin, context):
        """Half-open circuit should reopen immediately on failed probe."""
        tool = "test_tool"
        st = _get_state(tool)
        st.half_open = True
        st.consecutive_failures = 5

        # Set context for half-open test
        context.set_state("cb_half_open_test", True)
        context.set_state("cb_call_time", time.time())

        # Failed probe
        post_payload = ToolPostInvokePayload(name=tool, result={"is_error": True})
        with patch("mcpgateway.services.metrics.circuit_breaker_open_counter") as mock_counter:
            mock_counter.labels.return_value.inc = MagicMock()
            result = await plugin.tool_post_invoke(post_payload, context)

        # Circuit should be reopened
        assert st.half_open is False
        assert result.metadata["circuit_open_until"] > time.time()

    @pytest.mark.asyncio
    async def test_blocks_concurrent_probes_during_half_open(self, plugin, context):
        """Only one probe should be allowed during half-open state."""
        tool = "test_tool"
        st = _get_state(tool)
        st.half_open = True  # Must be in half-open state
        st.half_open_in_flight = True  # Simulate a probe already in progress
        st.half_open_started = time.time()  # Probe started recently
        st.consecutive_failures = 5

        payload = ToolPreInvokePayload(name=tool, args={})
        result = await plugin.tool_pre_invoke(payload, context)

        # Should block - another probe is in flight
        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "CIRCUIT_HALF_OPEN_PROBE_IN_FLIGHT"

    @pytest.mark.asyncio
    async def test_stale_probe_detection_resets_half_open(self, plugin, context):
        """Stale probe (longer than cooldown) should reset and allow new probe."""
        tool = "test_tool"
        st = _get_state(tool)
        st.half_open = True
        st.half_open_in_flight = True
        st.half_open_started = time.time() - 120  # Probe started 2 minutes ago (stale)
        st.consecutive_failures = 5

        payload = ToolPreInvokePayload(name=tool, args={})
        result = await plugin.tool_pre_invoke(payload, context)

        # Stale probe should be reset, circuit reopened
        assert st.half_open is False
        assert st.half_open_in_flight is False
        assert st.open_until > 0  # Circuit should be reopened

    @pytest.mark.asyncio
    async def test_clears_in_flight_flag_on_probe_success(self, plugin, context):
        """Successful probe should clear the in-flight flag."""
        tool = "test_tool"
        st = _get_state(tool)
        st.half_open = True
        st.half_open_in_flight = True
        st.consecutive_failures = 5

        context.set_state("cb_half_open_test", True)
        context.set_state("cb_call_time", time.time())

        post_payload = ToolPostInvokePayload(name=tool, result={"is_error": False})
        await plugin.tool_post_invoke(post_payload, context)

        # In-flight flag should be cleared
        assert st.half_open_in_flight is False

    @pytest.mark.asyncio
    async def test_clears_in_flight_flag_on_probe_failure(self, plugin, context):
        """Failed probe should clear the in-flight flag."""
        tool = "test_tool"
        st = _get_state(tool)
        st.half_open = True
        st.half_open_in_flight = True
        st.consecutive_failures = 5

        context.set_state("cb_half_open_test", True)
        context.set_state("cb_call_time", time.time())

        post_payload = ToolPostInvokePayload(name=tool, result={"is_error": True})
        with patch("mcpgateway.services.metrics.circuit_breaker_open_counter") as mock_counter:
            mock_counter.labels.return_value.inc = MagicMock()
            await plugin.tool_post_invoke(post_payload, context)

        # In-flight flag should be cleared
        assert st.half_open_in_flight is False


class TestTimeoutIntegration:
    """Test timeout integration with circuit breaker."""

    @pytest.mark.asyncio
    async def test_timeout_counted_as_failure(self, plugin, context):
        """Timeout flag should be counted as failure."""
        tool = "test_tool"

        # Set timeout flag (as tool_service would do)
        context.set_state("cb_timeout_failure", True)
        context.set_state("cb_call_time", time.time())

        # Post-invoke with a technically successful result but timeout flag set
        post_payload = ToolPostInvokePayload(name=tool, result={"is_error": False})
        result = await plugin.tool_post_invoke(post_payload, context)

        # Should count as failure
        assert result.metadata["circuit_failures_in_window"] == 1
        assert result.metadata["circuit_consecutive_failures"] == 1


class TestPerToolOverrides:
    """Test per-tool configuration overrides."""

    @pytest.mark.asyncio
    async def test_tool_override_applied(self, context):
        """Per-tool overrides should be applied correctly."""
        config = PluginConfig(
            id="test-cb",
            kind="circuit_breaker",
            name="Test Circuit Breaker",
            enabled=True,
            order=0,
            config={
                "consecutive_failure_threshold": 5,
                "tool_overrides": {
                    "critical_tool": {"consecutive_failure_threshold": 10}
                },
            },
        )
        plugin = CircuitBreakerPlugin(config)

        # Simulate 5 failures on critical_tool (should NOT open - needs 10)
        for _ in range(5):
            pre_payload = ToolPreInvokePayload(name="critical_tool", args={})
            await plugin.tool_pre_invoke(pre_payload, context)

            post_payload = ToolPostInvokePayload(name="critical_tool", result={"is_error": True})
            result = await plugin.tool_post_invoke(post_payload, context)

        # Circuit should still be closed (needs 10 failures)
        assert result.metadata["circuit_open_until"] == 0.0
        assert result.metadata["circuit_consecutive_failures"] == 5


class TestHelperFunctions:
    """Test helper functions."""

    def test_is_error_with_dict(self):
        """_is_error should detect error in dict result."""
        assert _is_error({"is_error": True}) is True
        assert _is_error({"is_error": False}) is False
        assert _is_error({"success": True}) is False

    def test_is_error_with_camel_case(self):
        """_is_error should detect error in camelCase (serialized via by_alias=True)."""
        # When ToolResult.model_dump(by_alias=True) is used, is_error becomes isError
        assert _is_error({"isError": True}) is True
        assert _is_error({"isError": False}) is False
        # snake_case takes precedence if both present
        assert _is_error({"is_error": True, "isError": False}) is True

    def test_is_error_with_object(self):
        """_is_error should detect error in object result."""
        class MockResult:
            is_error = True

        assert _is_error(MockResult()) is True
        MockResult.is_error = False
        assert _is_error(MockResult()) is False

    def test_cfg_for_with_override(self):
        """_cfg_for should merge tool overrides."""
        base_cfg = CircuitBreakerConfig(
            consecutive_failure_threshold=5,
            tool_overrides={"special_tool": {"consecutive_failure_threshold": 10}},
        )

        merged = _cfg_for(base_cfg, "special_tool")
        assert merged.consecutive_failure_threshold == 10

        default = _cfg_for(base_cfg, "regular_tool")
        assert default.consecutive_failure_threshold == 5


class TestWindowEviction:
    """Test time window eviction logic."""

    @pytest.mark.asyncio
    async def test_old_entries_evicted(self, plugin, context):
        """Old call/failure entries should be evicted after window expires."""
        tool = "test_tool"
        st = _get_state(tool)

        # Add old entries (outside window)
        old_time = time.time() - 120  # 2 minutes ago
        st.calls.append(old_time)
        st.failures.append(old_time)

        # Make a new call
        pre_payload = ToolPreInvokePayload(name=tool, args={})
        await plugin.tool_pre_invoke(pre_payload, context)

        post_payload = ToolPostInvokePayload(name=tool, result={"is_error": False})
        result = await plugin.tool_post_invoke(post_payload, context)

        # Old entries should be evicted
        assert result.metadata["circuit_calls_in_window"] == 1
        assert result.metadata["circuit_failures_in_window"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
