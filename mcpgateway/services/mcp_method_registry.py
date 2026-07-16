# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/mcp_method_registry.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Contributors to the MCP-CONTEXT-FORGE project

MCP method registry for core MCP and MCP Apps routing.

This module provides a small registry to keep core MCP methods authoritative
while allowing feature-gated MCP Apps AppBridge methods to pass validation.
"""

# Standard
from typing import Dict, FrozenSet

# First-Party
from mcpgateway.services.mcp_apps import mcp_apps_enabled, MCP_UI_EXTENSION

# Core MCP methods that always take precedence.
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


class MCPMethodRegistry:
    """Registry for core MCP methods and feature-gated MCP Apps methods."""

    def __init__(self) -> None:
        """Initialize the MCP method registry."""
        self._mcp_apps_methods: Dict[str, FrozenSet[str]] = {}
        self._register_mcp_apps_methods()

    def _register_mcp_apps_methods(self) -> None:
        """Register MCP Apps AppBridge methods."""
        self._mcp_apps_methods[MCP_UI_EXTENSION] = frozenset({"tools/call"})

    def is_core_method(self, method: str) -> bool:
        """Return whether a method is a core MCP method."""
        return method in _CORE_MCP_METHODS

    def is_known_method(self, method: str) -> bool:
        """Return whether a method is known for core MCP or enabled MCP Apps."""
        if self.is_core_method(method):
            return True
        if mcp_apps_enabled() and method in self._mcp_apps_methods.get(MCP_UI_EXTENSION, frozenset()):
            return True
        return False


# Global MCP method registry instance.
mcp_method_registry = MCPMethodRegistry()
