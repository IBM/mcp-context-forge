# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_observability.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Tests for observability dependency injection in the plugin framework.
Verifies that a mock ObservabilityProvider can be injected into PluginManager
and that start_span/end_span are called during plugin execution.
"""

# Standard
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import (
    GlobalContext,
    Plugin,
    PluginConfig,
    PluginManager,
    PluginResult,
    PromptHookType,
    PromptPrehookPayload,
)
from mcpgateway.plugins.framework.base import HookRef
from mcpgateway.plugins.framework.manager import PluginExecutor
from mcpgateway.plugins.framework.observability import NullObservability, current_trace_id
from mcpgateway.plugins.framework.registry import PluginRef


class RecordingObservability:
    """Mock observability provider that records all calls for assertions."""

    def __init__(self):
        self.spans: List[Tuple[str, dict]] = []
        self.ended_spans: List[Tuple[Optional[str], str, Optional[Dict[str, Any]]]] = []

    def start_span(
        self,
        trace_id: str,
        name: str,
        kind: str = "internal",
        resource_type: Optional[str] = None,
        resource_name: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        span_id = f"span-{len(self.spans)}"
        self.spans.append(
            (
                span_id,
                {
                    "trace_id": trace_id,
                    "name": name,
                    "kind": kind,
                    "resource_type": resource_type,
                    "resource_name": resource_name,
                    "attributes": attributes,
                },
            )
        )
        return span_id

    def end_span(
        self,
        span_id: Optional[str],
        status: str = "ok",
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.ended_spans.append((span_id, status, attributes))


class SimplePlugin(Plugin):
    """A minimal plugin that modifies the payload."""

    async def prompt_pre_fetch(self, payload, context):
        payload.args["traced"] = "yes"
        return PluginResult(continue_processing=True, modified_payload=payload)


@pytest.mark.asyncio
async def test_observability_injection_via_plugin_manager():
    """Test that an ObservabilityProvider injected into PluginManager is invoked during hook execution."""
    recorder = RecordingObservability()
    trace_id = "test-trace-001"

    manager = PluginManager(
        "./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml",
        observability=recorder,
    )
    await manager.initialize()

    config = PluginConfig(
        name="TracedPlugin",
        description="Plugin for observability test",
        author="Test",
        version="1.0",
        tags=["test"],
        kind="TracedPlugin",
        hooks=["prompt_pre_fetch"],
        config={},
    )
    plugin = SimplePlugin(config)

    token = current_trace_id.set(trace_id)
    try:
        with patch.object(manager._registry, "get_hook_refs_for_hook") as mock_get:
            hook_ref = HookRef(PromptHookType.PROMPT_PRE_FETCH, PluginRef(plugin))
            mock_get.return_value = [hook_ref]

            payload = PromptPrehookPayload(prompt_id="test", args={})
            global_context = GlobalContext(request_id="req-1")

            result, _ = await manager.invoke_hook(
                PromptHookType.PROMPT_PRE_FETCH,
                payload,
                global_context=global_context,
            )

        assert result.continue_processing
        assert result.modified_payload is not None
        assert result.modified_payload.args["traced"] == "yes"

        # Verify start_span was called
        assert len(recorder.spans) == 1
        span_id, span_info = recorder.spans[0]
        assert span_info["trace_id"] == trace_id
        assert "TracedPlugin" in span_info["name"]
        assert span_info["kind"] == "internal"
        assert span_info["resource_type"] == "plugin"
        assert span_info["resource_name"] == "TracedPlugin"
        assert span_info["attributes"]["plugin.name"] == "TracedPlugin"

        # Verify end_span was called with matching span_id
        assert len(recorder.ended_spans) == 1
        ended_span_id, status, end_attrs = recorder.ended_spans[0]
        assert ended_span_id == span_id
        assert status == "ok"
        assert end_attrs["plugin.had_violation"] is False
        assert end_attrs["plugin.modified_payload"] is True
    finally:
        current_trace_id.reset(token)
        await manager.shutdown()


@pytest.mark.asyncio
async def test_no_tracing_without_trace_id():
    """Test that observability is not invoked when no trace_id is set."""
    recorder = RecordingObservability()

    manager = PluginManager(
        "./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml",
        observability=recorder,
    )
    await manager.initialize()

    config = PluginConfig(
        name="UntracedPlugin",
        description="Plugin without trace",
        author="Test",
        version="1.0",
        tags=["test"],
        kind="UntracedPlugin",
        hooks=["prompt_pre_fetch"],
        config={},
    )
    plugin = SimplePlugin(config)

    # Do NOT set current_trace_id — it should default to None
    with patch.object(manager._registry, "get_hook_refs_for_hook") as mock_get:
        hook_ref = HookRef(PromptHookType.PROMPT_PRE_FETCH, PluginRef(plugin))
        mock_get.return_value = [hook_ref]

        payload = PromptPrehookPayload(prompt_id="test", args={})
        global_context = GlobalContext(request_id="req-2")

        result, _ = await manager.invoke_hook(
            PromptHookType.PROMPT_PRE_FETCH,
            payload,
            global_context=global_context,
        )

    assert result.continue_processing
    # No spans should have been created
    assert len(recorder.spans) == 0
    assert len(recorder.ended_spans) == 0

    await manager.shutdown()


@pytest.mark.asyncio
async def test_no_tracing_without_provider():
    """Test that plugin execution works when no observability provider is injected."""
    manager = PluginManager(
        "./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml",
        observability=None,
    )
    await manager.initialize()

    config = PluginConfig(
        name="NoProviderPlugin",
        description="Plugin without observability",
        author="Test",
        version="1.0",
        tags=["test"],
        kind="NoProviderPlugin",
        hooks=["prompt_pre_fetch"],
        config={},
    )
    plugin = SimplePlugin(config)

    token = current_trace_id.set("trace-no-provider")
    try:
        with patch.object(manager._registry, "get_hook_refs_for_hook") as mock_get:
            hook_ref = HookRef(PromptHookType.PROMPT_PRE_FETCH, PluginRef(plugin))
            mock_get.return_value = [hook_ref]

            payload = PromptPrehookPayload(prompt_id="test", args={})
            global_context = GlobalContext(request_id="req-3")

            result, _ = await manager.invoke_hook(
                PromptHookType.PROMPT_PRE_FETCH,
                payload,
                global_context=global_context,
            )

        # Plugin should still execute normally
        assert result.continue_processing
        assert result.modified_payload is not None
        assert result.modified_payload.args["traced"] == "yes"
    finally:
        current_trace_id.reset(token)
        await manager.shutdown()


@pytest.mark.asyncio
async def test_null_observability_default():
    """Test NullObservability no-op implementation."""
    null_obs = NullObservability()

    # start_span returns None
    span_id = null_obs.start_span(trace_id="t1", name="test_span")
    assert span_id is None

    # end_span does nothing (no error)
    null_obs.end_span(span_id=None, status="ok")
    null_obs.end_span(span_id="some-span", status="error", attributes={"key": "val"})


@pytest.mark.asyncio
async def test_executor_observability_injection():
    """Test that PluginExecutor correctly receives and uses an observability provider."""
    recorder = RecordingObservability()
    executor = PluginExecutor(observability=recorder)

    assert executor.observability is recorder

    # Also verify default is None
    default_executor = PluginExecutor()
    assert default_executor.observability is None
