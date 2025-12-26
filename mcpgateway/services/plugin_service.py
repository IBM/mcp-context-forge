# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/plugin_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Plugin service for managing and querying MCP Gateway plugins.
This module provides a service layer for accessing plugin information,
statistics, and configuration from the PluginManager.
"""

# Standard
from collections import defaultdict
import logging
from typing import Any, Dict, List, Optional

# First-Party
from mcpgateway.plugins.framework import PluginManager
from mcpgateway.plugins.framework.models import PluginMode

logger = logging.getLogger(__name__)

# Cache import (lazy to avoid circular dependencies)
_ADMIN_STATS_CACHE = None


def _get_admin_stats_cache():
    """Get admin stats cache singleton lazily.

    Returns:
        AdminStatsCache instance.
    """
    global _ADMIN_STATS_CACHE  # pylint: disable=global-statement
    if _ADMIN_STATS_CACHE is None:
        # First-Party
        from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

        _ADMIN_STATS_CACHE = admin_stats_cache
    return _ADMIN_STATS_CACHE


class PluginService:
    """Service for managing plugin information and statistics."""

    def __init__(self, plugin_manager: Optional[PluginManager] = None):
        """Initialize the plugin service.

        Args:
            plugin_manager: Optional PluginManager instance. If not provided,
                           attempts to get from app state will be made at runtime.
        """
        self._plugin_manager = plugin_manager

    def get_plugin_manager(self) -> Optional[PluginManager]:
        """Get the plugin manager instance.

        Returns:
            PluginManager instance or None if plugins are disabled.
        """
        return self._plugin_manager

    def set_plugin_manager(self, manager: PluginManager) -> None:
        """Set the plugin manager instance.

        Args:
            manager: The PluginManager instance to use.
        """
        self._plugin_manager = manager

    def get_all_plugins(self) -> List[Dict[str, Any]]:
        """Get all registered plugins with their configuration, including disabled plugins.

        Returns:
            List of plugin dictionaries containing configuration and status.
        """
        if not self._plugin_manager:
            return []

        plugins = []
        registry = self._plugin_manager._registry  # pylint: disable=protected-access
        config = self._plugin_manager._config  # pylint: disable=protected-access

        # First, add all registered (enabled) plugins from the registry
        registered_names = set()
        for plugin_ref in registry.get_all_plugins():
            # Get the plugin config from the plugin reference
            plugin_config = plugin_ref.plugin.config if hasattr(plugin_ref, "plugin") else plugin_ref._plugin.config if hasattr(plugin_ref, "_plugin") else None  # pylint: disable=protected-access

            plugin_dict = {
                "name": plugin_ref.name,
                "description": plugin_config.description if plugin_config and plugin_config.description else "",
                "author": plugin_config.author if plugin_config and plugin_config.author else "Unknown",
                "version": plugin_config.version if plugin_config and plugin_config.version else "0.0.0",
                "mode": plugin_ref.mode if isinstance(plugin_ref.mode, str) else plugin_ref.mode.value if plugin_ref.mode else "disabled",
                "priority": plugin_ref.priority,
                "hooks": [hook if isinstance(hook, str) else hook.value for hook in plugin_ref.hooks] if plugin_ref.hooks else [],
                "tags": plugin_ref.tags or [],
                "kind": plugin_config.kind if plugin_config and plugin_config.kind else "",
                "namespace": plugin_config.namespace if plugin_config and plugin_config.namespace else "",
                "status": "enabled" if plugin_ref.mode != PluginMode.DISABLED else "disabled",
            }

            # Add implementation type if available (e.g., Rust vs Python for PII filter)
            plugin_instance = plugin_ref.plugin if hasattr(plugin_ref, "plugin") else plugin_ref._plugin if hasattr(plugin_ref, "_plugin") else None  # pylint: disable=protected-access
            if plugin_instance and hasattr(plugin_instance, "implementation"):
                plugin_dict["implementation"] = plugin_instance.implementation

            # Add config summary (first few keys only for list view)
            if plugin_config and hasattr(plugin_config, "config") and plugin_config.config:
                config_keys = list(plugin_config.config.keys())[:5]
                plugin_dict["config_summary"] = {k: plugin_config.config[k] for k in config_keys}
            else:
                plugin_dict["config_summary"] = {}

            plugins.append(plugin_dict)
            registered_names.add(plugin_ref.name)

        # Then, add disabled plugins from the configuration (not in registry)
        if config and config.plugins:
            for plugin_config in config.plugins:
                if plugin_config.mode == PluginMode.DISABLED and plugin_config.name not in registered_names:
                    plugin_dict = {
                        "name": plugin_config.name,
                        "description": plugin_config.description or "",
                        "author": plugin_config.author or "Unknown",
                        "version": plugin_config.version or "0.0.0",
                        "mode": plugin_config.mode if isinstance(plugin_config.mode, str) else plugin_config.mode.value,
                        "priority": plugin_config.priority or 100,
                        "hooks": [hook if isinstance(hook, str) else hook.value for hook in plugin_config.hooks] if plugin_config.hooks else [],
                        "tags": plugin_config.tags or [],
                        "kind": plugin_config.kind or "",
                        "namespace": plugin_config.namespace or "",
                        "status": "disabled",
                        "config_summary": {},
                    }

                    # Add config summary (first few keys only for list view)
                    if hasattr(plugin_config, "config") and plugin_config.config:
                        config_keys = list(plugin_config.config.keys())[:5]
                        plugin_dict["config_summary"] = {k: plugin_config.config[k] for k in config_keys}

                    plugins.append(plugin_dict)

        return sorted(plugins, key=lambda x: x["priority"])

    def get_plugin_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific plugin.

        Args:
            name: The name of the plugin to retrieve.

        Returns:
            Plugin dictionary with full configuration or None if not found.
        """
        if not self._plugin_manager:
            return None

        registry = self._plugin_manager._registry  # pylint: disable=protected-access
        plugin_ref = registry.get_plugin(name)

        if not plugin_ref:
            return None

        # Get the plugin config from the plugin reference
        plugin_config = plugin_ref.plugin.config if hasattr(plugin_ref, "plugin") else plugin_ref._plugin.config if hasattr(plugin_ref, "_plugin") else None  # pylint: disable=protected-access

        plugin_dict = {
            "name": plugin_ref.name,
            "description": plugin_config.description if plugin_config and plugin_config.description else "",
            "author": plugin_config.author if plugin_config and plugin_config.author else "Unknown",
            "version": plugin_config.version if plugin_config and plugin_config.version else "0.0.0",
            "mode": plugin_ref.mode if isinstance(plugin_ref.mode, str) else plugin_ref.mode.value if plugin_ref.mode else "disabled",
            "priority": plugin_ref.priority,
            "hooks": [hook if isinstance(hook, str) else hook.value for hook in plugin_ref.hooks] if plugin_ref.hooks else [],
            "tags": plugin_ref.tags or [],
            "kind": plugin_config.kind if plugin_config and plugin_config.kind else "",
            "namespace": plugin_config.namespace if plugin_config and plugin_config.namespace else "",
            "status": "enabled" if plugin_ref.mode != PluginMode.DISABLED else "disabled",
            "conditions": plugin_ref.conditions or [],
            "config": plugin_config.config if plugin_config and hasattr(plugin_config, "config") else {},
        }

        # Add manifest info if available
        if hasattr(plugin_ref, "manifest"):
            plugin_dict["manifest"] = {"available_hooks": plugin_ref.manifest.available_hooks, "default_config": plugin_ref.manifest.default_config}

        return plugin_dict

    async def get_plugin_statistics(self) -> Dict[str, Any]:
        """Get statistics about all plugins.

        Returns:
            Dictionary containing plugin statistics by various dimensions.
        """
        if not self._plugin_manager:
            return {
                "total_plugins": 0,
                "enabled_plugins": 0,
                "disabled_plugins": 0,
                "plugins_by_hook": {},
                "plugins_by_mode": {},
                "plugins_by_tag": {},
                "plugins_by_author": {},
            }

        # Check cache first
        cache = _get_admin_stats_cache()
        cached = await cache.get_plugin_stats()
        if cached is not None:
            return cached

        all_plugins = self.get_all_plugins()

        # Count by status
        enabled_count = sum(1 for p in all_plugins if p["status"] == "enabled")
        disabled_count = sum(1 for p in all_plugins if p["status"] == "disabled")

        # Count by hook
        hooks_count = defaultdict(int)
        for plugin in all_plugins:
            for hook in plugin["hooks"]:
                hooks_count[hook] += 1

        # Count by mode
        mode_count = defaultdict(int)
        for plugin in all_plugins:
            mode_count[plugin["mode"]] += 1

        # Count by tag
        tag_count = defaultdict(int)
        for plugin in all_plugins:
            for tag in plugin["tags"]:
                tag_count[tag] += 1

        # Count by author
        author_count = defaultdict(int)
        for plugin in all_plugins:
            author = plugin.get("author", "Unknown")
            author_count[author] += 1

        stats = {
            "total_plugins": len(all_plugins),
            "enabled_plugins": enabled_count,
            "disabled_plugins": disabled_count,
            "plugins_by_hook": dict(hooks_count),
            "plugins_by_mode": dict(mode_count),
            "plugins_by_tag": dict(sorted(tag_count.items(), key=lambda x: x[1], reverse=True)[:10]),  # Top 10 tags
            "plugins_by_author": dict(sorted(author_count.items(), key=lambda x: x[1], reverse=True)),  # All authors sorted by count
        }

        # Store in cache
        await cache.set_plugin_stats(stats)

        return stats

    def search_plugins(self, query: Optional[str] = None, mode: Optional[str] = None, hook: Optional[str] = None, tag: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search and filter plugins based on criteria.

        Args:
            query: Text search in name, description, author.
            mode: Filter by mode (enforce, permissive, disabled).
            hook: Filter by hook type.
            tag: Filter by tag.

        Returns:
            Filtered list of plugins.
        """
        plugins = self.get_all_plugins()

        # Text search
        if query:
            query_lower = query.lower()
            plugins = [p for p in plugins if query_lower in p["name"].lower() or query_lower in p["description"].lower() or query_lower in p["author"].lower()]

        # Mode filter
        if mode:
            plugins = [p for p in plugins if p["mode"] == mode]

        # Hook filter
        if hook:
            plugins = [p for p in plugins if hook in p["hooks"]]

        # Tag filter
        if tag:
            plugins = [p for p in plugins if tag in p["tags"]]

        return plugins


# Singleton instance
_plugin_service = PluginService()


def get_plugin_service() -> PluginService:
    """Get the singleton plugin service instance.

    Returns:
        The global PluginService instance.
    """
    return _plugin_service
