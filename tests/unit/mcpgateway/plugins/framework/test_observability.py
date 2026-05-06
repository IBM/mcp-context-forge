# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_observability.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Tests for observability dependency injection in the plugin framework.
Verifies that a mock ObservabilityProvider can be injected into PluginManager
and that start_span/end_span are called during plugin execution.
"""

# Standard
from contextlib import contextmanager
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
    PluginMode,
    PluginResult,
    PromptHookType,
    PromptPrehookPayload,
)
from mcpgateway.plugins.framework.base import HookRef
from mcpgateway.plugins.framework.manager import PluginExecutor
from mcpgateway.plugins.framework.observability import current_trace_id, NullObservability
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


class BlockingPlugin(Plugin):
    """A minimal plugin that stops the hook chain."""

    async def prompt_pre_fetch(self, payload, context):  # noqa: ARG002
        return PluginResult(continue_processing=False, modified_payload=payload)


class PassthroughToolPlugin(Plugin):
    """A minimal tool plugin that allows the hook chain to complete."""

    async def tool_pre_invoke(self, payload, context):  # noqa: ARG002
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


@pytest.mark.asyncio
async def test_plugin_manager_emits_otel_hook_and_plugin_spans():
    """Plugin manager should emit OTEL spans for the hook chain and plugin execution."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml", observability=None)
    await manager.initialize()

    config = PluginConfig(
        name="TracedPlugin",
        description="Plugin for OTEL test",
        author="Test",
        version="1.0",
        tags=["test"],
        kind="TracedPlugin",
        hooks=["prompt_pre_fetch"],
        config={},
    )
    plugin = SimplePlugin(config)

    spans: List[Tuple[str, Dict[str, Any] | None]] = []

    @contextmanager
    def record_span(name: str, attributes: Optional[Dict[str, Any]] = None):
        spans.append((name, attributes))
        yield None

    with patch.object(manager._registry, "get_hook_refs_for_hook") as mock_get:
        hook_ref = HookRef(PromptHookType.PROMPT_PRE_FETCH, PluginRef(plugin))
        mock_get.return_value = [hook_ref]

        payload = PromptPrehookPayload(prompt_id="test", args={})
        global_context = GlobalContext(request_id="req-otel-1")

        with patch("mcpgateway.plugins.framework.manager.create_span", side_effect=record_span):
            result, _ = await manager.invoke_hook(
                PromptHookType.PROMPT_PRE_FETCH,
                payload,
                global_context=global_context,
            )

    assert result.continue_processing is True
    assert [name for name, _ in spans] == ["plugin.hook.invoke", "plugin.execute"]
    assert spans[0][1]["plugin.hook.type"] == PromptHookType.PROMPT_PRE_FETCH
    assert spans[1][1]["plugin.name"] == "TracedPlugin"
    assert spans[1][1]["plugin.hook.type"] == PromptHookType.PROMPT_PRE_FETCH

    await manager.shutdown()


@pytest.mark.asyncio
async def test_plugin_manager_records_when_plugin_stops_chain():
    """Hook-chain span should record which plugin stopped processing."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml", observability=None)
    await manager.initialize()

    config = PluginConfig(
        name="BlockingPlugin",
        description="Plugin for OTEL stop test",
        author="Test",
        version="1.0",
        tags=["test"],
        kind="BlockingPlugin",
        hooks=["prompt_pre_fetch"],
        config={},
        mode=PluginMode.ENFORCE,
    )
    plugin = BlockingPlugin(config)

    class RecordingSpan:
        def __init__(self, name: str, attributes: Optional[Dict[str, Any]] = None):
            self.name = name
            self.attributes = dict(attributes or {})

        def set_attribute(self, key: str, value: Any) -> None:
            self.attributes[key] = value

    recorded: List[RecordingSpan] = []

    @contextmanager
    def record_span(name: str, attributes: Optional[Dict[str, Any]] = None):
        span = RecordingSpan(name, attributes)
        recorded.append(span)
        yield span

    with patch.object(manager._registry, "get_hook_refs_for_hook") as mock_get:
        hook_ref = HookRef(PromptHookType.PROMPT_PRE_FETCH, PluginRef(plugin))
        mock_get.return_value = [hook_ref]

        payload = PromptPrehookPayload(prompt_id="test", args={})
        global_context = GlobalContext(request_id="req-otel-stop")

        with patch("mcpgateway.plugins.framework.manager.create_span", side_effect=record_span):
            result, _ = await manager.invoke_hook(
                PromptHookType.PROMPT_PRE_FETCH,
                payload,
                global_context=global_context,
            )

    assert result.continue_processing is False
    hook_chain_span = recorded[0]
    plugin_span = recorded[1]
    assert hook_chain_span.name == "plugin.hook.invoke"
    assert hook_chain_span.attributes["plugin.chain.stopped"] is True
    assert hook_chain_span.attributes["plugin.chain.stopped_by"] == "BlockingPlugin"
    assert plugin_span.name == "plugin.execute"
    assert plugin_span.attributes["plugin.name"] == "BlockingPlugin"

    await manager.shutdown()


@pytest.mark.asyncio
async def test_plugin_manager_records_skipped_and_executed_counts_when_chain_completes():
    """Completed hook chains should record executed and skipped plugin counts."""
    # First-Party
    from mcpgateway.plugins.framework import ToolHookType, ToolPreInvokePayload

    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml", observability=None)
    await manager.initialize()

    disabled_config = PluginConfig(
        name="DisabledPlugin",
        description="Disabled plugin for OTEL accounting test",
        author="Test",
        version="1.0",
        tags=["test"],
        kind="DisabledPlugin",
        hooks=["tool_pre_invoke"],
        config={},
        mode=PluginMode.DISABLED,
    )
    enabled_config = PluginConfig(
        name="EnabledPlugin",
        description="Enabled plugin for OTEL accounting test",
        author="Test",
        version="1.0",
        tags=["test"],
        kind="EnabledPlugin",
        hooks=["tool_pre_invoke"],
        config={},
        mode=PluginMode.ENFORCE,
    )

    disabled_plugin = PassthroughToolPlugin(disabled_config)
    enabled_plugin = PassthroughToolPlugin(enabled_config)

    class RecordingSpan:
        def __init__(self, name: str, attributes: Optional[Dict[str, Any]] = None):
            self.name = name
            self.attributes = dict(attributes or {})

        def set_attribute(self, key: str, value: Any) -> None:
            self.attributes[key] = value

    recorded: List[RecordingSpan] = []

    @contextmanager
    def record_span(name: str, attributes: Optional[Dict[str, Any]] = None):
        span = RecordingSpan(name, attributes)
        recorded.append(span)
        yield span

    with patch.object(manager._registry, "get_hook_refs_for_hook") as mock_get:
        mock_get.return_value = [
            HookRef("tool_pre_invoke", PluginRef(disabled_plugin)),
            HookRef("tool_pre_invoke", PluginRef(enabled_plugin)),
        ]

        payload = ToolPreInvokePayload(name="tool-a", args={})
        global_context = GlobalContext(request_id="req-otel-counts")

        with patch("mcpgateway.plugins.framework.manager.create_span", side_effect=record_span):
            result, _ = await manager.invoke_hook(
                ToolHookType.TOOL_PRE_INVOKE,
                payload,
                global_context=global_context,
            )

    assert result.continue_processing is True
    hook_chain_span = recorded[0]
    assert hook_chain_span.name == "plugin.hook.invoke"
    assert hook_chain_span.attributes["plugin.executed_count"] == 1
    assert hook_chain_span.attributes["plugin.skipped_count"] == 1
    assert hook_chain_span.attributes["plugin.chain.stopped"] is False

    await manager.shutdown()


def test_protocol_method_bodies():
    """Verify that calling Protocol method stubs directly returns None."""
    # First-Party
    from mcpgateway.plugins.framework.observability import ObservabilityProvider

    # Call the unbound protocol methods directly to exercise the `...` bodies
    result1 = ObservabilityProvider.start_span(None, trace_id="t", name="n")
    assert result1 is None

    result2 = ObservabilityProvider.end_span(None, span_id=None)
    assert result2 is None


@pytest.mark.asyncio
async def test_get_plugin_manager_creates_manager_when_enabled():
    """Test that get_plugin_manager creates a TenantPluginManager when plugins_enabled is True."""
    # First-Party
    import mcpgateway.plugins.framework as fw
    from mcpgateway.plugins.framework.manager import TenantPluginManager

    recorder = RecordingObservability()

    fw.enable_plugins(True)
    fw.init_plugin_manager_factory(
        yaml_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml",
        timeout=30,
        hook_policies={},
        observability=recorder,
    )
    pm = await fw.get_plugin_manager()

    assert pm is not None
    assert isinstance(pm, TenantPluginManager)


@pytest.mark.asyncio
async def test_get_plugin_manager_returns_none_when_disabled():
    """get_plugin_manager returns None immediately when _PLUGINS_ENABLED is False (line 119)."""
    # First-Party
    import mcpgateway.plugins.framework as fw

    fw.enable_plugins(False)
    result = await fw.get_plugin_manager("any-server")
    assert result is None


@pytest.mark.asyncio
async def test_get_plugin_manager_returns_none_when_factory_missing():
    """get_plugin_manager returns None when enabled but factory not yet initialised (line 122)."""
    # First-Party
    import mcpgateway.plugins.framework as fw

    fw.enable_plugins(True)
    fw.reset_plugin_manager_factory()  # ensures factory is None
    result = await fw.get_plugin_manager("any-server")
    assert result is None
    fw.enable_plugins(False)  # restore default


def test_set_global_observability_updates_factory():
    """set_global_observability propagates to the factory when one exists (lines 129-131)."""
    # Standard
    from unittest.mock import MagicMock

    # First-Party
    import mcpgateway.plugins.framework as fw

    mock_factory = MagicMock()
    fw._plugin_manager_factory = mock_factory
    mock_obs = MagicMock()

    fw.set_global_observability(mock_obs)

    assert fw._observability_service is mock_obs
    assert mock_factory.observability == mock_obs
    fw.reset_plugin_manager_factory()


def test_reset_plugin_manager_factory_clears_reference():
    """reset_plugin_manager_factory sets the factory to None (line 155)."""
    # Standard
    from unittest.mock import MagicMock

    # First-Party
    import mcpgateway.plugins.framework as fw

    fw._plugin_manager_factory = MagicMock()
    fw.reset_plugin_manager_factory()
    assert fw._plugin_manager_factory is None


@pytest.mark.asyncio
async def test_shutdown_plugin_manager_factory_when_disabled():
    """Shutdown must tear the factory down even when the in-memory flag is False.

    Runtime-disabling plugins flips ``_PLUGINS_ENABLED`` to False, but gateway
    shutdown must still call ``factory.shutdown()`` — otherwise in-flight build
    tasks leak. Pins the fix that removed the ``if not _PLUGINS_ENABLED``
    early-return.
    """
    # Standard
    from unittest.mock import AsyncMock, MagicMock

    # First-Party
    import mcpgateway.plugins.framework as fw

    mock_factory = MagicMock()
    mock_factory.shutdown = AsyncMock()
    fw._plugin_manager_factory = mock_factory
    fw.enable_plugins(False)

    try:
        await fw.shutdown_plugin_manager_factory()
        mock_factory.shutdown.assert_awaited_once()
        assert fw._plugin_manager_factory is None
    finally:
        fw._plugin_manager_factory = None


@pytest.mark.asyncio
async def test_shutdown_plugin_manager_factory_when_enabled():
    """shutdown_plugin_manager_factory calls factory.shutdown() when plugins enabled (lines 144-149)."""
    # Standard
    from unittest.mock import AsyncMock, MagicMock

    # First-Party
    import mcpgateway.plugins.framework as fw

    mock_factory = MagicMock()
    mock_factory.shutdown = AsyncMock()
    fw._plugin_manager_factory = mock_factory
    fw.enable_plugins(True)

    await fw.shutdown_plugin_manager_factory()

    mock_factory.shutdown.assert_awaited_once()
    assert fw._plugin_manager_factory is None
    fw.enable_plugins(False)  # restore default
