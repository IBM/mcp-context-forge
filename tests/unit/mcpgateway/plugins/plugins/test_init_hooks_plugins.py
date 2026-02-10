# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/test_init_hooks_plugins.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Unit tests for plugin instantiation and hook invocation.
These tests verify that each plugin can be loaded and its hooks invoked.

This module uses parametrized tests to generically test all plugins
and their hooks without repetitive code.
"""

# Standard
from typing import Any

# Third-Party
import pytest
import yaml

# First-Party
from mcpgateway.common.models import Message, PromptResult, ResourceContent, Role, TextContent
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginManager,
    PromptHookType,
    PromptPosthookPayload,
    PromptPrehookPayload,
    ResourceHookType,
    ResourcePostFetchPayload,
    ResourcePreFetchPayload,
    ToolHookType,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)

CONFIG_PATH = "./tests/unit/mcpgateway/plugins/fixtures/configs/init_hooks_plugins_test.yaml"


# Hook type mapping from string to enum
HOOK_TYPE_MAP: dict[str, Any] = {
    "prompt_pre_fetch": PromptHookType.PROMPT_PRE_FETCH,
    "prompt_post_fetch": PromptHookType.PROMPT_POST_FETCH,
    "tool_pre_invoke": ToolHookType.TOOL_PRE_INVOKE,
    "tool_post_invoke": ToolHookType.TOOL_POST_INVOKE,
    "resource_pre_fetch": ResourceHookType.RESOURCE_PRE_FETCH,
    "resource_post_fetch": ResourceHookType.RESOURCE_POST_FETCH,
}


def create_payload_for_hook(hook_name: str) -> Any:
    """Create an appropriate payload for the given hook type.

    Args:
        hook_name: The hook name string (e.g., 'prompt_pre_fetch').

    Returns:
        A payload object appropriate for the hook type.
    """
    if hook_name == "prompt_pre_fetch":
        return PromptPrehookPayload(prompt_id="test_prompt", args={"user": "Test input"})
    elif hook_name == "prompt_post_fetch":
        message = Message(content=TextContent(type="text", text="Test message"), role=Role.USER)
        prompt_result = PromptResult(messages=[message])
        return PromptPosthookPayload(prompt_id="test_prompt", result=prompt_result)
    elif hook_name == "tool_pre_invoke":
        return ToolPreInvokePayload(name="test_tool", args={"input": "Test data"})
    elif hook_name == "tool_post_invoke":
        return ToolPostInvokePayload(name="test_tool", result={"content": [{"type": "text", "text": "Test result"}]})
    elif hook_name == "resource_pre_fetch":
        return ResourcePreFetchPayload(uri="test://resource")
    elif hook_name == "resource_post_fetch":
        resource_content = ResourceContent(type="resource", id="res-1", uri="test://resource", text="Test content")
        return ResourcePostFetchPayload(uri="test://resource", content=resource_content)
    else:
        raise ValueError(f"Unknown hook type: {hook_name}")


def create_global_context() -> GlobalContext:
    """Create a standard global context for testing."""
    return GlobalContext(
        request_id="test-request-1",
        server_id="test-server-1",
        user="test_user",
        tenant_id="test_tenant",
    )


def load_plugin_configs(include_disabled: bool = False) -> list[dict[str, Any]]:
    """Load plugin configurations from the test config file.

    Args:
        include_disabled: If True, include disabled plugins. Default is False.

    Returns:
        List of plugin configuration dictionaries.
    """
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
    plugins = config.get("plugins", [])

    if not include_disabled:
        # Filter out disabled plugins
        plugins = [p for p in plugins if p.get("mode", "permissive") != "disabled"]

    return plugins


def get_plugin_test_params() -> list[tuple[str, str]]:
    """Generate test parameters for all enabled plugin/hook combinations.

    Returns:
        List of (plugin_name, hook_name) tuples for parametrization.
    """
    params = []
    plugins = load_plugin_configs(include_disabled=False)
    for plugin in plugins:
        plugin_name = plugin["name"]
        for hook in plugin.get("hooks", []):
            params.append((plugin_name, hook))
    return params


def get_plugin_names() -> list[str]:
    """Get list of enabled plugin names from config.

    Returns:
        List of plugin names (excludes disabled plugins).
    """
    plugins = load_plugin_configs(include_disabled=False)
    return [p["name"] for p in plugins]


# Generate test parameters
PLUGIN_HOOK_PARAMS = get_plugin_test_params()
PLUGIN_NAMES = get_plugin_names()


class TestPluginInstantiation:
    """Test that each enabled plugin can be instantiated."""

    @pytest.fixture(autouse=True)
    def reset_plugin_manager(self):
        """Reset PluginManager singleton before and after each test."""
        PluginManager.reset()
        yield
        PluginManager.reset()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("plugin_name", PLUGIN_NAMES, ids=lambda x: f"instantiate-{x}")
    async def test_plugin_instantiation(self, plugin_name: str):
        """Test that a plugin can be instantiated via PluginManager.

        Args:
            plugin_name: Name of the plugin to test.
        """
        manager = PluginManager(CONFIG_PATH)
        await manager.initialize()

        assert manager.initialized, f"Plugin manager failed to initialize for {plugin_name}"
        assert manager.plugin_count > 0, f"No plugins loaded for {plugin_name}"

        # Find the plugin by name
        plugin_found = False
        if manager.config and manager.config.plugins:
            for plugin_config in manager.config.plugins:
                if plugin_config.name == plugin_name:
                    plugin_found = True
                    break

        assert plugin_found, f"Plugin {plugin_name} not found in loaded plugins"
        await manager.shutdown()


class TestPluginHookInvocation:
    """Test hook invocation for each enabled plugin."""

    @pytest.fixture(autouse=True)
    def reset_plugin_manager(self):
        """Reset PluginManager singleton before and after each test."""
        PluginManager.reset()
        yield
        PluginManager.reset()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "plugin_name,hook_name",
        PLUGIN_HOOK_PARAMS,
        ids=lambda x: f"{x}" if isinstance(x, str) else None,
    )
    async def test_hook_invocation(self, plugin_name: str, hook_name: str):
        """Test that a plugin's hook can be invoked without fatal errors.

        This test verifies that:
        1. The plugin manager initializes successfully
        2. The hook can be invoked with an appropriate payload
        3. The result indicates processing should continue (in permissive mode)

        Note: Some plugins may log errors during hook invocation (e.g., missing
        metadata, external services unavailable) but should still allow processing
        to continue in permissive mode.

        Args:
            plugin_name: Name of the plugin to test.
            hook_name: Name of the hook to invoke.
        """
        manager = PluginManager(CONFIG_PATH)
        await manager.initialize()

        assert manager.initialized, "Plugin manager failed to initialize"

        # Get the hook type enum
        hook_type = HOOK_TYPE_MAP.get(hook_name)
        assert hook_type is not None, f"Unknown hook type: {hook_name}"

        # Create appropriate payload for the hook
        payload = create_payload_for_hook(hook_name)
        global_context = create_global_context()

        # Invoke the hook - in permissive mode, errors are logged but processing continues
        result, _ = await manager.invoke_hook(hook_type, payload, global_context=global_context)

        # In permissive mode, processing should always continue
        assert result.continue_processing, f"Hook {hook_name} for plugin {plugin_name} blocked processing unexpectedly"

        await manager.shutdown()


class TestAllPluginsTogether:
    """Test loading all enabled plugins together."""

    @pytest.fixture(autouse=True)
    def reset_plugin_manager(self):
        """Reset PluginManager singleton before and after each test."""
        PluginManager.reset()
        yield
        PluginManager.reset()

    @pytest.mark.asyncio
    async def test_all_plugins_load_together(self):
        """Test that all enabled plugins can be loaded simultaneously."""
        manager = PluginManager(CONFIG_PATH)
        await manager.initialize()

        assert manager.initialized, "Plugin manager failed to initialize"
        assert manager.plugin_count == len(PLUGIN_NAMES), f"Expected {len(PLUGIN_NAMES)} plugins, got {manager.plugin_count}"

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_all_hooks_invocable(self):
        """Test that all hooks across all plugins can be invoked in sequence."""
        manager = PluginManager(CONFIG_PATH)
        await manager.initialize()

        global_context = create_global_context()
        hooks_tested: set[str] = set()

        # Test each unique hook type
        for _, hook_name in PLUGIN_HOOK_PARAMS:
            if hook_name in hooks_tested:
                continue

            hook_type = HOOK_TYPE_MAP.get(hook_name)
            if hook_type is None:
                continue

            payload = create_payload_for_hook(hook_name)
            result, _ = await manager.invoke_hook(hook_type, payload, global_context=global_context)

            assert result.continue_processing, f"Hook {hook_name} blocked processing"
            hooks_tested.add(hook_name)

        await manager.shutdown()
