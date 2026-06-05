# -*- coding: utf-8 -*-
"""Minimal extension registry for MCP Apps and future extensions.

This module provides a small registry to track known extensions and their
supported methods, enabling default-deny behavior for unknown extension methods
while keeping core MCP methods as the authority.
"""

# Standard
from typing import Dict, FrozenSet, Optional

# First-Party
from mcpgateway.services.mcp_apps import mcp_apps_enabled, MCP_UI_EXTENSION

# Core MCP methods that always take precedence over extensions
_CORE_MCP_METHODS: FrozenSet[str] = frozenset(
    {
        "initialize",
        "ping",
        "tools/list",
        "tools/call",
        "resources/list",
        "resources/read",
        "resources/templates/list",
        "resources/subscribe",
        "resources/unsubscribe",
        "prompts/list",
        "prompts/get",
        "logging/setLevel",
        "completion/complete",
        "notifications/initialized",
        "notifications/cancelled",
        "notifications/progress",
        "notifications/message",
        "notifications/resources/list_changed",
        "notifications/resources/updated",
        "notifications/prompts/list_changed",
        "notifications/tools/list_changed",
    }
)


class ExtensionRegistry:
    """Registry for known MCP extensions and their supported methods."""

    def __init__(self) -> None:
        """Initialize the extension registry with built-in extensions."""
        self._extensions: Dict[str, FrozenSet[str]] = {}
        self._register_builtin_extensions()

    def _register_builtin_extensions(self) -> None:
        """Register built-in extensions like MCP Apps."""
        # MCP Apps extension supports AppBridge tool calls
        self._extensions[MCP_UI_EXTENSION] = frozenset({"tools/call"})

    def is_core_method(self, method: str) -> bool:
        """Return whether a method is a core MCP method."""
        return method in _CORE_MCP_METHODS

    def is_extension_method(self, method: str, extension_id: str) -> bool:
        """Return whether a method is supported by a known extension."""
        if extension_id not in self._extensions:
            return False
        return method in self._extensions[extension_id]

    def is_known_method(self, method: str) -> bool:
        """Return whether a method is known (core or any extension)."""
        if self.is_core_method(method):
            return True
        # Check if any enabled extension supports this method
        if mcp_apps_enabled() and method in self._extensions.get(MCP_UI_EXTENSION, frozenset()):
            return True
        return False

    def get_extension_methods(self, extension_id: str) -> Optional[FrozenSet[str]]:
        """Return the set of methods supported by an extension."""
        return self._extensions.get(extension_id)


# Global extension registry instance
extension_registry = ExtensionRegistry()
