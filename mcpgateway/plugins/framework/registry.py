# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/registry.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Plugin instance registry.
Module that stores plugin instances and manages hook points.
"""

# Standard
from collections import defaultdict
import logging
from typing import Optional

# First-Party
from mcpgateway.plugins.framework.base import Plugin, PluginRef
from mcpgateway.plugins.framework.models import HookType

# Use standard logging to avoid circular imports (plugins -> services -> plugins)
logger = logging.getLogger(__name__)


class PluginInstanceRegistry:
    """Registry for managing loaded plugins.

    Examples:
        >>> from mcpgateway.plugins.framework import Plugin, PluginConfig, HookType
        >>> registry = PluginInstanceRegistry()
        >>> config = PluginConfig(
        ...     name="test",
        ...     description="Test",
        ...     author="test",
        ...     kind="test.Plugin",
        ...     version="1.0",
        ...     hooks=[HookType.PROMPT_PRE_FETCH],
        ...     tags=[]
        ... )
        >>> plugin = Plugin(config)
        >>> registry.register(plugin)
        >>> registry.get_plugin("test").name
        'test'
        >>> len(registry.get_plugins_for_hook(HookType.PROMPT_PRE_FETCH))
        1
        >>> registry.unregister("test")
        >>> registry.get_plugin("test") is None
        True
    """

    def __init__(self) -> None:
        """Initialize a plugin instance registry.

        Examples:
            >>> registry = PluginInstanceRegistry()
            >>> isinstance(registry._plugins, dict)
            True
            >>> isinstance(registry._hooks, dict)
            True
            >>> len(registry._plugins)
            0
        """
        self._plugins: dict[str, PluginRef] = {}
        self._hooks: dict[HookType, list[PluginRef]] = defaultdict(list)
        self._priority_cache: dict[HookType, list[PluginRef]] = {}

    def register(self, plugin: Plugin) -> None:
        """Register a plugin instance.

        Args:
            plugin: plugin to be registered.

        Raises:
            ValueError: if plugin is already registered.
        """
        if plugin.name in self._plugins:
            raise ValueError(f"Plugin {plugin.name} already registered")

        plugin_ref = PluginRef(plugin)

        self._plugins[plugin.name] = plugin_ref

        # Register hooks
        for hook_type in plugin.hooks:
            self._hooks[hook_type].append(plugin_ref)
            # Invalidate priority cache for this hook
            self._priority_cache.pop(hook_type, None)

        logger.info(f"Registered plugin: {plugin.name} with hooks: {[h.name for h in plugin.hooks]}")

    def unregister(self, plugin_name: str) -> None:
        """Unregister a plugin given its name.

        Args:
            plugin_name: The name of the plugin to unregister.

        Returns:
            None
        """
        if plugin_name not in self._plugins:
            return

        plugin = self._plugins.pop(plugin_name)
        # Remove from hooks
        for hook_type in plugin.hooks:
            self._hooks[hook_type] = [p for p in self._hooks[hook_type] if p.name != plugin_name]
            self._priority_cache.pop(hook_type, None)

        logger.info(f"Unregistered plugin: {plugin_name}")

    def get_plugin(self, name: str) -> Optional[PluginRef]:
        """Get a plugin by name.

        Args:
            name: the name of the plugin to return.

        Returns:
            A plugin.
        """
        return self._plugins.get(name)

    def get_plugins_for_hook(self, hook_type: HookType) -> list[PluginRef]:
        """Get all plugins for a specific hook, sorted by priority.

        Args:
            hook_type: the hook type.

        Returns:
            A list of plugin instances.
        """
        if hook_type not in self._priority_cache:
            plugins = sorted(self._hooks[hook_type], key=lambda p: p.priority)
            self._priority_cache[hook_type] = plugins
        return self._priority_cache[hook_type]

    def get_all_plugins(self) -> list[PluginRef]:
        """Get all registered plugin instances.

        Returns:
            A list of registered plugin instances.
        """
        return list(self._plugins.values())

    @property
    def plugin_count(self) -> int:
        """Return the number of plugins registered.

        Returns:
            The number of plugins registered.
        """
        return len(self._plugins)

    async def shutdown(self) -> None:
        """Shutdown all plugins."""
        # Must cleanup the plugins in reverse of creating them to handle asyncio cleanup issues.
        # https://github.com/microsoft/semantic-kernel/issues/12627
        for plugin_ref in reversed(self._plugins.values()):
            try:
                await plugin_ref.plugin.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down plugin {plugin_ref.plugin.name}: {e}")
        self._plugins.clear()
        self._hooks.clear()
        self._priority_cache.clear()
