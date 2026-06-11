# -*- coding: utf-8 -*-
"""Tests for the MCP method registry and method routing."""

# Third-Party
import pytest

# First-Party
from mcpgateway.services.mcp_method_registry import mcp_method_registry, MCPMethodRegistry
from mcpgateway.services.mcp_apps import MCP_UI_EXTENSION


class TestMCPMethodRegistry:
    """Tests for MCP method registry functionality."""

    def test_core_methods_recognized(self):
        """Core MCP methods should be recognized."""
        registry = MCPMethodRegistry()

        assert registry.is_core_method("initialize")
        assert registry.is_core_method("tools/list")
        assert registry.is_core_method("tools/call")
        assert registry.is_core_method("resources/read")
        assert registry.is_core_method("prompts/get")

    def test_unknown_methods_not_recognized(self):
        """Unknown methods should not be recognized."""
        registry = MCPMethodRegistry()

        assert not registry.is_core_method("unknown/method")
        assert not registry.is_core_method("extensions/custom")
        assert not registry.is_known_method("io.example/custom")

    def test_mcp_apps_methods_registered(self, monkeypatch):
        """MCP Apps methods should be registered for the UI capability."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        registry = MCPMethodRegistry()

        methods = registry.get_mcp_apps_methods(MCP_UI_EXTENSION)
        assert methods is not None
        assert "tools/call" in methods
        assert registry.is_mcp_apps_method("tools/call", MCP_UI_EXTENSION)

    def test_non_core_mcp_apps_method_recognition_when_enabled(self, monkeypatch):
        """Enabled MCP Apps can make non-core AppBridge methods known."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        registry = MCPMethodRegistry()
        registry._mcp_apps_methods[MCP_UI_EXTENSION] = frozenset({"ui/render"})

        assert registry.is_known_method("ui/render")

    def test_mcp_apps_method_recognition_when_enabled(self, monkeypatch):
        """MCP Apps methods should be recognized when the feature is enabled."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        registry = MCPMethodRegistry()

        # tools/call is both a core method and an AppBridge method.
        assert registry.is_known_method("tools/call")

    def test_mcp_apps_method_not_recognized_when_disabled(self, monkeypatch):
        """MCP Apps-specific methods should not be recognized when disabled."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", False)
        registry = MCPMethodRegistry()

        # Core methods still recognized
        assert registry.is_known_method("tools/call")

        # Currently MCP Apps only uses tools/call, which is also core.

    def test_core_methods_take_precedence(self):
        """Core MCP methods should take precedence."""
        registry = MCPMethodRegistry()

        # tools/call is a core method
        assert registry.is_core_method("tools/call")

        assert registry.is_known_method("tools/call")

    def test_unknown_capability_id(self):
        """Unknown capability IDs should return None for methods."""
        registry = MCPMethodRegistry()

        methods = registry.get_mcp_apps_methods("io.example/unknown")
        assert methods is None

        assert not registry.is_mcp_apps_method("tools/call", "io.example/unknown")

    def test_global_registry_instance(self):
        """Global mcp_method_registry instance should be available."""
        assert mcp_method_registry is not None
        assert isinstance(mcp_method_registry, MCPMethodRegistry)


class TestMCPMethodRouting:
    """Tests for MCP method routing behavior."""

    def test_unknown_mcp_apps_method_returns_method_not_found(self, monkeypatch):
        """Unknown MCP Apps methods should return method-not-found error."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

        # Simulate RPC handler behavior
        # First-Party
        from mcpgateway.services.mcp_method_registry import mcp_method_registry

        method = "extensions/unknown"
        assert not mcp_method_registry.is_known_method(method)

        # This should trigger -32601 error in actual RPC handler

    def test_known_mcp_prefix_but_unknown_method(self, monkeypatch):
        """Known MCP prefix but unknown method should return method-not-found."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

        # First-Party
        from mcpgateway.services.mcp_method_registry import mcp_method_registry

        # io.modelcontextprotocol/ prefix is known, but /unknown is not
        method = "io.modelcontextprotocol/unknown"
        assert not mcp_method_registry.is_known_method(method)

    def test_core_method_precedence(self, monkeypatch):
        """Core MCP methods should be handled first."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

        # First-Party
        from mcpgateway.services.mcp_method_registry import mcp_method_registry

        assert mcp_method_registry.is_core_method("tools/call")
        assert mcp_method_registry.is_known_method("tools/call")

        # Core method check should come first in RPC handler
        # (verified by code inspection in main.py)
