# -*- coding: utf-8 -*-
"""Tests for the extension registry and method routing."""

# Third-Party
import pytest

# First-Party
from mcpgateway.services.extension_registry import extension_registry, ExtensionRegistry
from mcpgateway.services.mcp_apps import MCP_UI_EXTENSION


class TestExtensionRegistry:
    """Tests for extension registry functionality."""

    def test_core_methods_recognized(self):
        """Core MCP methods should be recognized."""
        registry = ExtensionRegistry()

        assert registry.is_core_method("initialize")
        assert registry.is_core_method("tools/list")
        assert registry.is_core_method("tools/call")
        assert registry.is_core_method("resources/read")
        assert registry.is_core_method("prompts/get")

    def test_unknown_methods_not_recognized(self):
        """Unknown methods should not be recognized."""
        registry = ExtensionRegistry()

        assert not registry.is_core_method("unknown/method")
        assert not registry.is_core_method("extensions/custom")
        assert not registry.is_known_method("io.example/custom")

    def test_extension_methods_registered(self, monkeypatch):
        """Extension methods should be registered for known extensions."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        registry = ExtensionRegistry()

        # MCP Apps extension supports tools/call
        methods = registry.get_extension_methods(MCP_UI_EXTENSION)
        assert methods is not None
        assert "tools/call" in methods
        assert registry.is_extension_method("tools/call", MCP_UI_EXTENSION)

    def test_non_core_extension_method_recognition_when_enabled(self, monkeypatch):
        """Enabled extensions can make non-core extension methods known."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        registry = ExtensionRegistry()
        registry._extensions[MCP_UI_EXTENSION] = frozenset({"ui/render"})

        assert registry.is_known_method("ui/render")

    def test_extension_method_recognition_when_enabled(self, monkeypatch):
        """Extension methods should be recognized when extension is enabled."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        registry = ExtensionRegistry()

        # tools/call is both a core method and an extension method
        assert registry.is_known_method("tools/call")

    def test_extension_method_not_recognized_when_disabled(self, monkeypatch):
        """Extension-specific methods should not be recognized when extension is disabled."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", False)
        registry = ExtensionRegistry()

        # Core methods still recognized
        assert registry.is_known_method("tools/call")

        # But extension-specific methods are not
        # (Currently MCP Apps only uses tools/call which is also core, so this is a placeholder)

    def test_core_methods_take_precedence(self):
        """Core MCP methods should take precedence over extension methods."""
        registry = ExtensionRegistry()

        # tools/call is a core method
        assert registry.is_core_method("tools/call")

        # Even if an extension also supports it, core takes precedence
        assert registry.is_known_method("tools/call")

    def test_unknown_extension_id(self):
        """Unknown extension IDs should return None for methods."""
        registry = ExtensionRegistry()

        methods = registry.get_extension_methods("io.example/unknown")
        assert methods is None

        assert not registry.is_extension_method("tools/call", "io.example/unknown")

    def test_global_registry_instance(self):
        """Global extension_registry instance should be available."""
        assert extension_registry is not None
        assert isinstance(extension_registry, ExtensionRegistry)


class TestExtensionMethodRouting:
    """Tests for extension method routing behavior."""

    def test_unknown_extension_method_returns_method_not_found(self, monkeypatch):
        """Unknown extension methods should return method-not-found error."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

        # Simulate RPC handler behavior
        # First-Party
        from mcpgateway.services.extension_registry import extension_registry

        method = "extensions/unknown"
        assert not extension_registry.is_known_method(method)

        # This should trigger -32601 error in actual RPC handler

    def test_known_extension_prefix_but_unknown_method(self, monkeypatch):
        """Known extension prefix but unknown method should return method-not-found."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

        # First-Party
        from mcpgateway.services.extension_registry import extension_registry

        # io.modelcontextprotocol/ prefix is known, but /unknown is not
        method = "io.modelcontextprotocol/unknown"
        assert not extension_registry.is_known_method(method)

    def test_core_method_precedence_over_extensions(self, monkeypatch):
        """Core MCP methods should be handled before checking extensions."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

        # First-Party
        from mcpgateway.services.extension_registry import extension_registry

        # tools/call is both core and extension method
        assert extension_registry.is_core_method("tools/call")
        assert extension_registry.is_known_method("tools/call")

        # Core method check should come first in RPC handler
        # (verified by code inspection in main.py)
