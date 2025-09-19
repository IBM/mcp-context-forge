# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_registry.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for plugin registry.
"""
# Standard
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework.models import HookType, PluginConfig
from mcpgateway.plugins.framework.registry import PluginInstanceRegistry


@pytest.mark.asyncio
async def test_registry_register():
    """Load a plugin with the plugin loader."""
    config = ConfigLoader.load_config(config="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    registry = PluginInstanceRegistry()
    registry.register(plugin)

    all_plugins = registry.get_all_plugins()
    assert len(all_plugins) == 1
    assert registry.get_plugin("ReplaceBadWordsPlugin")
    assert registry.get_plugin("SomeNonExistentPlugin") is None

    registry.unregister("ReplaceBadWordsPlugin")
    assert registry.plugin_count == 0

    registry.unregister("SomePluginThatDoesntExist")

    all_plugins = registry.get_all_plugins()
    assert len(all_plugins) == 0


@pytest.mark.asyncio
async def test_registry_duplicate_plugin_registration():
    """Test that registering a plugin twice raises ValueError."""
    config = ConfigLoader.load_config(config="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    registry = PluginInstanceRegistry()

    # First registration should work
    registry.register(plugin)
    assert registry.plugin_count == 1

    # Second registration should raise ValueError (line 77)
    with pytest.raises(ValueError, match="Plugin .* already registered"):
        registry.register(plugin)

    # Clean up
    registry.unregister(plugin.name)
    assert registry.plugin_count == 0


@pytest.mark.asyncio
async def test_registry_priority_sorting():
    """Test plugin priority sorting and caching."""
    registry = PluginInstanceRegistry()

    # Create plugins with different priorities
    low_priority_config = PluginConfig(
        name="LowPriority",
        description="Low priority plugin",
        author="Test",
        version="1.0",
        tags=["test"],
        kind="test.Plugin",
        hooks=[HookType.PROMPT_PRE_FETCH],
        priority=300,  # High number = low priority
        config={}
    )

    high_priority_config = PluginConfig(
        name="HighPriority",
        description="High priority plugin",
        author="Test",
        version="1.0",
        tags=["test"],
        kind="test.Plugin",
        hooks=[HookType.PROMPT_PRE_FETCH],
        priority=50,   # Low number = high priority
        config={}
    )

    # Create plugin instances
    low_priority_plugin = Plugin(low_priority_config)
    high_priority_plugin = Plugin(high_priority_config)

    # Register plugins in reverse priority order
    registry.register(low_priority_plugin)
    registry.register(high_priority_plugin)

    # Get plugins for hook - should be sorted by priority (lines 131-134)
    hook_plugins = registry.get_plugins_for_hook(HookType.PROMPT_PRE_FETCH)
    assert len(hook_plugins) == 2
    assert hook_plugins[0].name == "HighPriority"  # Lower number = higher priority
    assert hook_plugins[1].name == "LowPriority"

    # Test priority cache - calling again should use cached result
    cached_plugins = registry.get_plugins_for_hook(HookType.PROMPT_PRE_FETCH)
    assert cached_plugins == hook_plugins

    # Clean up
    registry.unregister("LowPriority")
    registry.unregister("HighPriority")
    assert registry.plugin_count == 0


@pytest.mark.asyncio
async def test_registry_hook_filtering():
    """Test getting plugins for different hooks."""
    registry = PluginInstanceRegistry()

    # Create plugin with specific hooks
    pre_fetch_config = PluginConfig(
        name="PreFetchPlugin",
        description="Pre-fetch plugin",
        author="Test",
        version="1.0",
        tags=["test"],
        kind="test.Plugin",
        hooks=[HookType.PROMPT_PRE_FETCH],
        config={}
    )

    post_fetch_config = PluginConfig(
        name="PostFetchPlugin",
        description="Post-fetch plugin",
        author="Test",
        version="1.0",
        tags=["test"],
        kind="test.Plugin",
        hooks=[HookType.PROMPT_POST_FETCH],
        config={}
    )

    pre_fetch_plugin = Plugin(pre_fetch_config)
    post_fetch_plugin = Plugin(post_fetch_config)

    registry.register(pre_fetch_plugin)
    registry.register(post_fetch_plugin)

    # Test hook filtering
    pre_plugins = registry.get_plugins_for_hook(HookType.PROMPT_PRE_FETCH)
    post_plugins = registry.get_plugins_for_hook(HookType.PROMPT_POST_FETCH)
    tool_plugins = registry.get_plugins_for_hook(HookType.TOOL_PRE_INVOKE)

    assert len(pre_plugins) == 1
    assert pre_plugins[0].name == "PreFetchPlugin"

    assert len(post_plugins) == 1
    assert post_plugins[0].name == "PostFetchPlugin"

    assert len(tool_plugins) == 0  # No plugins for this hook

    # Clean up
    registry.unregister("PreFetchPlugin")
    registry.unregister("PostFetchPlugin")


@pytest.mark.asyncio
async def test_registry_shutdown():
    """Test registry shutdown functionality (lines 155-162)."""
    registry = PluginInstanceRegistry()

    # Create mock plugins with shutdown methods
    mock_plugin1 = Plugin(PluginConfig(
        name="Plugin1",
        description="Test plugin 1",
        author="Test",
        version="1.0",
        tags=["test"],
        kind="test.Plugin",
        hooks=[HookType.PROMPT_PRE_FETCH],
        config={}
    ))

    mock_plugin2 = Plugin(PluginConfig(
        name="Plugin2",
        description="Test plugin 2",
        author="Test",
        version="1.0",
        tags=["test"],
        kind="test.Plugin",
        hooks=[HookType.PROMPT_POST_FETCH],
        config={}
    ))

    # Mock the shutdown methods
    mock_plugin1.shutdown = AsyncMock()
    mock_plugin2.shutdown = AsyncMock()

    registry.register(mock_plugin1)
    registry.register(mock_plugin2)

    assert registry.plugin_count == 2

    # Test shutdown
    await registry.shutdown()

    # Verify shutdown was called on both plugins
    mock_plugin1.shutdown.assert_called_once()
    mock_plugin2.shutdown.assert_called_once()

    # Verify registry is cleared
    assert registry.plugin_count == 0
    assert len(registry.get_all_plugins()) == 0
    assert len(registry._hooks) == 0
    assert len(registry._priority_cache) == 0


@pytest.mark.asyncio
async def test_registry_shutdown_with_error():
    """Test registry shutdown when plugin shutdown fails (lines 158-159)."""
    registry = PluginInstanceRegistry()

    # Create mock plugin that fails during shutdown
    failing_plugin = Plugin(PluginConfig(
        name="FailingPlugin",
        description="Plugin that fails shutdown",
        author="Test",
        version="1.0",
        tags=["test"],
        kind="test.Plugin",
        hooks=[HookType.PROMPT_PRE_FETCH],
        config={}
    ))

    # Mock shutdown to raise an exception
    failing_plugin.shutdown = AsyncMock(side_effect=RuntimeError("Shutdown failed"))

    registry.register(failing_plugin)
    assert registry.plugin_count == 1

    # Shutdown should handle the error gracefully
    with patch('mcpgateway.plugins.framework.registry.logger') as mock_logger:
        await registry.shutdown()

        # Verify error was logged
        mock_logger.error.assert_called_once()
        error_call = mock_logger.error.call_args[0][0]
        assert "Error shutting down plugin FailingPlugin" in error_call

    # Registry should still be cleared despite the error
    assert registry.plugin_count == 0


@pytest.mark.asyncio
async def test_registry_edge_cases():
    """Test various edge cases for full coverage."""
    registry = PluginInstanceRegistry()

    # Test getting plugin that doesn't exist
    assert registry.get_plugin("NonExistent") is None

    # Test unregistering plugin that doesn't exist (line 100-101)
    registry.unregister("NonExistent")  # Should do nothing
    assert registry.plugin_count == 0

    # Test getting hooks for empty registry
    empty_hooks = registry.get_plugins_for_hook(HookType.PROMPT_PRE_FETCH)
    assert len(empty_hooks) == 0

    # Test get_all_plugins when empty
    assert len(registry.get_all_plugins()) == 0


@pytest.mark.asyncio
async def test_registry_cache_invalidation():
    """Test that priority cache is invalidated correctly."""
    registry = PluginInstanceRegistry()

    plugin_config = PluginConfig(
        name="TestPlugin",
        description="Test plugin",
        author="Test",
        version="1.0",
        tags=["test"],
        kind="test.Plugin",
        hooks=[HookType.PROMPT_PRE_FETCH],
        config={}
    )

    plugin = Plugin(plugin_config)

    # Register plugin
    registry.register(plugin)

    # Get plugins for hook (populates cache)
    hooks1 = registry.get_plugins_for_hook(HookType.PROMPT_PRE_FETCH)
    assert len(hooks1) == 1

    # Cache should be populated
    assert HookType.PROMPT_PRE_FETCH in registry._priority_cache

    # Unregister plugin (should invalidate cache)
    registry.unregister("TestPlugin")

    # Cache should be cleared for this hook type
    hooks2 = registry.get_plugins_for_hook(HookType.PROMPT_PRE_FETCH)
    assert len(hooks2) == 0
