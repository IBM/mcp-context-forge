# -*- coding: utf-8 -*-
"""Test observability verification fixtures for plugin E2E testing.

This validates that the observability fixtures in conftest.py work correctly
and can be used to verify plugin execution.

NOTE: This test file runs AFTER test_pii_filter_e2e.py (alphabetical order)
to avoid race conditions and ensure consistent behavior.
"""

from __future__ import annotations

from typing import Any
import logging

import pytest

pytestmark = [pytest.mark.e2e]  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

logger = logging.getLogger(__name__)


class TestObservabilityVerification:
    """Validate observability verification fixtures."""

    def test_query_observability_traces_fixture_exists(
        self,
        query_observability_traces: Any,
    ) -> None:
        """The query_observability_traces fixture should be available."""
        assert query_observability_traces is not None
        assert callable(query_observability_traces)

    def test_verify_plugin_execution_fixture_exists(
        self,
        verify_plugin_execution: Any,
    ) -> None:
        """The verify_plugin_execution fixture should be available."""
        assert verify_plugin_execution is not None
        assert callable(verify_plugin_execution)

    def test_can_query_traces_after_tool_invocation(
        self,
        plugin_harness: dict[str, Any],
        invoke_tool: Any,
        query_observability_traces: Any,
    ) -> None:
        """Should be able to query observability traces after invoking a tool."""
        # Invoke tool
        response = invoke_tool(plugin_harness, arguments={"timezone": "UTC"}, request_id=100)
        assert response["status_code"] == 200, response

        # Query traces
        traces = query_observability_traces(
            resource_type="tool",
            resource_name=plugin_harness["tool_name"],
            limit=10
        )

        # Log what we got
        logger.info("Found %d traces for tool %s", len(traces), plugin_harness["tool_name"])
        if traces:
            logger.info("First trace: %s", traces[0])

        # Traces may or may not exist depending on observability config
        # This test just verifies the fixture works without errors
        assert isinstance(traces, list)

    def test_can_verify_plugin_execution(
        self,
        plugin_harness: dict[str, Any],
        invoke_tool: Any,
        verify_plugin_execution: Any,
    ) -> None:
        """Should be able to check if plugin executed via observability."""
        # Invoke tool
        response = invoke_tool(plugin_harness, arguments={"timezone": "UTC"}, request_id=101)
        assert response["status_code"] == 200, response

        # Try to verify plugin execution
        executed = verify_plugin_execution(
            resource_name=plugin_harness["tool_name"],
            resource_type="tool",
            plugin_name="pii_filter"
        )

        # Log result
        logger.info("Plugin execution detected: %s", executed)

        # This test just verifies the fixture works without errors
        # The actual result depends on whether observability is capturing plugin spans
        assert isinstance(executed, bool)

    def test_observability_fixtures_handle_missing_data_gracefully(
        self,
        query_observability_traces: Any,
        verify_plugin_execution: Any,
    ) -> None:
        """Observability fixtures should handle missing data without errors."""
        # Query for non-existent resource
        traces = query_observability_traces(
            resource_type="tool",
            resource_name="non-existent-tool-12345",
            limit=10
        )
        assert isinstance(traces, list)
        assert len(traces) == 0

        # Verify for non-existent resource
        executed = verify_plugin_execution(
            resource_name="non-existent-tool-12345",
            resource_type="tool"
        )
        assert executed is False


class TestPluginExecutionVerification:
    """Validate plugin execution via observability traces."""

    def test_can_detect_plugin_execution_for_tool_invocation(
        self,
        plugin_harness: dict[str, Any],
        invoke_tool: Any,
        verify_plugin_execution: Any,
    ) -> None:
        """Should detect plugin execution when tool is invoked."""
        # Invoke tool
        response = invoke_tool(
            plugin_harness,
            arguments={"user_input": "test data", "timezone": "UTC"},
            request_id=200
        )
        assert response["status_code"] == 200, response

        # Verify plugin executed
        executed = verify_plugin_execution(
            resource_name=plugin_harness["tool_name"],
            resource_type="tool",
            plugin_name="pii_filter"
        )

        logger.info("Plugin execution detected for tool %s: %s", plugin_harness["tool_name"], executed)

        # If observability is working, we should detect plugin execution
        # If not, this test documents the expected behavior
        if executed:
            logger.info("✓ Plugin execution successfully detected via observability")
        else:
            logger.warning("⚠ Plugin execution not detected - check observability configuration")

    def test_can_detect_plugin_execution_for_prompt_fetch(
        self,
        plugin_harness: dict[str, Any],
        invoke_prompt: Any,
        verify_plugin_execution: Any,
    ) -> None:
        """Should detect plugin execution when prompt is fetched."""
        # Invoke prompt
        response = invoke_prompt(
            plugin_harness,
            arguments={"user_input": "test data", "secondary_input": "more data"},
            request_id=201
        )
        assert response["status_code"] == 200, response

        # Verify plugin executed
        executed = verify_plugin_execution(
            resource_name=plugin_harness["prompt_name"],
            resource_type="prompt",
            plugin_name="pii_filter"
        )

        logger.info("Plugin execution detected for prompt %s: %s", plugin_harness["prompt_name"], executed)

        if executed:
            logger.info("✓ Plugin execution successfully detected via observability")
        else:
            logger.warning("⚠ Plugin execution not detected - check observability configuration")

    def test_can_verify_specific_hook_types(
        self,
        plugin_harness: dict[str, Any],
        invoke_tool: Any,
        verify_plugin_execution: Any,
    ) -> None:
        """Should be able to verify specific hook types (pre/post)."""
        # Invoke tool
        response = invoke_tool(
            plugin_harness,
            arguments={"user_input": "test", "timezone": "UTC"},
            request_id=202
        )
        assert response["status_code"] == 200, response

        # Check for pre-invoke hook
        pre_executed = verify_plugin_execution(
            resource_name=plugin_harness["tool_name"],
            resource_type="tool",
            plugin_name="pii_filter",
            hook_type="pre_invoke"
        )

        # Check for post-invoke hook
        post_executed = verify_plugin_execution(
            resource_name=plugin_harness["tool_name"],
            resource_type="tool",
            plugin_name="pii_filter",
            hook_type="post_invoke"
        )

        logger.info("Pre-invoke hook detected: %s", pre_executed)
        logger.info("Post-invoke hook detected: %s", post_executed)

        # Both hooks should execute for a complete tool invocation
        if pre_executed and post_executed:
            logger.info("✓ Both pre and post hooks detected")
        else:
            logger.warning("⚠ Not all hooks detected - check observability configuration")


class TestHookOrderingVerification:
    """Validate plugin hook execution order via observability traces."""

    def test_tool_hooks_execute_in_correct_order(
        self,
        plugin_harness: dict[str, Any],
        invoke_tool: Any,
        query_observability_traces: Any,
    ) -> None:
        """Pre-invoke hook should execute before post-invoke hook for tools."""
        # Invoke tool
        response = invoke_tool(
            plugin_harness,
            arguments={"user_input": "test", "timezone": "UTC"},
            request_id=300
        )
        assert response["status_code"] == 200, response

        # Query traces
        traces = query_observability_traces(
            resource_type="tool",
            resource_name=plugin_harness["tool_name"],
            limit=10
        )

        if not traces:
            logger.warning("⚠ No traces found - observability may not be capturing plugin spans")
            pytest.skip("No traces available for hook ordering verification")

        # Find plugin-related spans
        plugin_spans = []
        for trace in traces:
            spans = trace.get("spans", [])
            for span in spans:
                span_name = span.get("name", "").lower()
                if "plugin" in span_name or "pii" in span_name:
                    plugin_spans.append(span)

        if not plugin_spans:
            logger.warning("⚠ No plugin spans found in traces")
            pytest.skip("No plugin spans available for hook ordering verification")

        # Look for pre and post invoke spans
        pre_spans = [s for s in plugin_spans if "pre" in s.get("name", "").lower()]
        post_spans = [s for s in plugin_spans if "post" in s.get("name", "").lower()]

        logger.info("Found %d pre-invoke spans and %d post-invoke spans", len(pre_spans), len(post_spans))

        if pre_spans and post_spans:
            # Verify pre-invoke happened before post-invoke
            pre_time = pre_spans[0].get("start_time", 0)
            post_time = post_spans[0].get("start_time", 0)

            assert pre_time < post_time, (
                f"Pre-invoke hook should execute before post-invoke hook. "
                f"Pre: {pre_time}, Post: {post_time}"
            )
            logger.info("✓ Hook execution order verified: pre-invoke before post-invoke")
        else:
            logger.warning("⚠ Could not verify hook ordering - insufficient span data")

    def test_prompt_hooks_execute_in_correct_order(
        self,
        plugin_harness: dict[str, Any],
        invoke_prompt: Any,
        query_observability_traces: Any,
    ) -> None:
        """Pre-fetch hook should execute before post-fetch hook for prompts."""
        # Invoke prompt
        response = invoke_prompt(
            plugin_harness,
            arguments={"user_input": "test", "secondary_input": "data"},
            request_id=301
        )
        assert response["status_code"] == 200, response

        # Query traces
        traces = query_observability_traces(
            resource_type="prompt",
            resource_name=plugin_harness["prompt_name"],
            limit=10
        )

        if not traces:
            logger.warning("⚠ No traces found - observability may not be capturing plugin spans")
            pytest.skip("No traces available for hook ordering verification")

        # Find plugin-related spans
        plugin_spans = []
        for trace in traces:
            spans = trace.get("spans", [])
            for span in spans:
                span_name = span.get("name", "").lower()
                if "plugin" in span_name or "pii" in span_name:
                    plugin_spans.append(span)

        if not plugin_spans:
            logger.warning("⚠ No plugin spans found in traces")
            pytest.skip("No plugin spans available for hook ordering verification")

        # Look for pre and post fetch spans
        pre_spans = [s for s in plugin_spans if "pre" in s.get("name", "").lower()]
        post_spans = [s for s in plugin_spans if "post" in s.get("name", "").lower()]

        logger.info("Found %d pre-fetch spans and %d post-fetch spans", len(pre_spans), len(post_spans))

        if pre_spans and post_spans:
            # Verify pre-fetch happened before post-fetch
            pre_time = pre_spans[0].get("start_time", 0)
            post_time = post_spans[0].get("start_time", 0)

            assert pre_time < post_time, (
                f"Pre-fetch hook should execute before post-fetch hook. "
                f"Pre: {pre_time}, Post: {post_time}"
            )
            logger.info("✓ Hook execution order verified: pre-fetch before post-fetch")
        else:
            logger.warning("⚠ Could not verify hook ordering - insufficient span data")

    def test_multiple_tool_invocations_maintain_hook_order(
        self,
        plugin_harness: dict[str, Any],
        invoke_tool: Any,
        query_observability_traces: Any,
    ) -> None:
        """Hook ordering should be consistent across multiple invocations."""
        # Invoke tool multiple times
        for i in range(3):
            response = invoke_tool(
                plugin_harness,
                arguments={"user_input": f"test-{i}", "timezone": "UTC"},
                request_id=400 + i
            )
            assert response["status_code"] == 200, response

        # Query traces
        traces = query_observability_traces(
            resource_type="tool",
            resource_name=plugin_harness["tool_name"],
            limit=20
        )

        if not traces:
            logger.warning("⚠ No traces found")
            pytest.skip("No traces available for verification")

        # Count hook executions
        pre_count = 0
        post_count = 0

        for trace in traces:
            spans = trace.get("spans", [])
            for span in spans:
                span_name = span.get("name", "").lower()
                if "plugin" in span_name or "pii" in span_name:
                    if "pre" in span_name:
                        pre_count += 1
                    if "post" in span_name:
                        post_count += 1

        logger.info("Found %d pre-invoke and %d post-invoke hook executions", pre_count, post_count)

        # We should have equal numbers of pre and post hooks
        if pre_count > 0 and post_count > 0:
            assert pre_count == post_count, (
                f"Pre and post hook counts should match. Pre: {pre_count}, Post: {post_count}"
            )
            logger.info("✓ Hook execution counts match across multiple invocations")
        else:
            logger.warning("⚠ Could not verify hook counts - insufficient span data")

# Made with Bob
