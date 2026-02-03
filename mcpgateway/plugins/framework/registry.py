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
from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
from mcpgateway.plugins.framework.external.mcp.client import ExternalHookRef

# Use standard logging to avoid circular imports (plugins -> services -> plugins)
logger = logging.getLogger(__name__)


class PluginInstanceRegistry:
    """Registry for managing loaded plugins.

    Examples:
        >>> from mcpgateway.plugins.framework import Plugin, PluginConfig
        >>> from mcpgateway.plugins.framework.hooks.prompts import PromptHookType
        >>> registry = PluginInstanceRegistry()
        >>> config = PluginConfig(
        ...     name="test",
        ...     description="Test",
        ...     author="test",
        ...     kind="test.Plugin",
        ...     version="1.0",
        ...     hooks=[PromptHookType.PROMPT_PRE_FETCH],
        ...     tags=[]
        ... )
        >>> async def prompt_pre_fetch(payload, context): ...
        >>> plugin = Plugin(config)
        >>> plugin.prompt_pre_fetch = prompt_pre_fetch
        >>> registry.register(plugin)
        >>> registry.get_plugin("test").name
        'test'
        >>> len(registry.get_hook_refs_for_hook(PromptHookType.PROMPT_PRE_FETCH))
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
        self._hooks: dict[str, list[HookRef]] = defaultdict(list)
        self._hooks_by_name: dict[str, dict[str, HookRef]] = {}
        self._priority_cache: dict[str, list[HookRef]] = {}

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

        plugin_hooks = {}

        # Check if this is an external plugin by looking for the invoke_hook method
        # External plugins (MCP, gRPC, Unix socket) use invoke_hook instead of direct hook methods
        external = hasattr(plugin, "invoke_hook") and callable(getattr(plugin, "invoke_hook"))

        # Register hooks
        for hook_type in plugin.hooks:
            hook_ref: HookRef
            if external:
                hook_ref = ExternalHookRef(hook_type, plugin_ref)
            else:
                hook_ref = HookRef(hook_type, plugin_ref)
            self._hooks[hook_type].append(hook_ref)
            plugin_hooks[hook_type] = hook_ref
            # Invalidate priority cache for this hook
            self._priority_cache.pop(hook_type, None)
        self._hooks_by_name[plugin.name] = plugin_hooks

        logger.info(f"Registered plugin: {plugin.name} with hooks: {list(plugin.hooks)}")

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
            self._hooks[hook_type] = [p for p in self._hooks[hook_type] if p.plugin_ref.name != plugin_name]
            self._priority_cache.pop(hook_type, None)

        # Remove from hooks by name
        self._hooks_by_name.pop(plugin_name, None)

        logger.info(f"Unregistered plugin: {plugin_name}")

    def get_plugin(self, name: str) -> Optional[PluginRef]:
        """Get a plugin by name.

        Args:
            name: the name of the plugin to return.

        Returns:
            A plugin.
        """
        return self._plugins.get(name)

    def get_plugin_hook_by_name(self, name: str, hook_type: str) -> Optional[HookRef]:
        """Gets a hook reference for a particular plugin and hook type.

        Args:
            name: plugin name.
            hook_type: the hook type.

        Returns:
            A hook reference for the plugin or None if not found.
        """
        if name in self._hooks_by_name:
            hooks = self._hooks_by_name[name]
            if hook_type in hooks:
                return hooks[hook_type]
        return None

    def get_hook_refs_for_hook(self, hook_type: str) -> list[HookRef]:
        """Get all plugins for a specific hook, sorted by priority.

        Args:
            hook_type: the hook type.

        Returns:
            A list of plugin instances.
        """
        if hook_type not in self._priority_cache:
            hook_refs = sorted(self._hooks[hook_type], key=lambda p: p.plugin_ref.priority)
            self._priority_cache[hook_type] = hook_refs
        return self._priority_cache[hook_type]

    def get_all_plugins(self) -> list[PluginRef]:
        """Get all registered plugin instances.

        Returns:
            A list of registered plugin instances.
        """
        return list(self._plugins.values())

    def has_hooks_for(self, hook_type: str) -> bool:
        """Check if there are any hooks registered for a specific hook type.

        Args:
            hook_type: The type of hook to check for.

        Returns:
            bool: True if there are hooks registered for the specified type, False otherwise.
        """
        return bool(self._hooks.get(hook_type))

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
