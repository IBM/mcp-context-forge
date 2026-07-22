# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_mcp_method_registry.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the MCP method registry and method routing.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import patch

# Third-Party
import orjson
import pytest

# First-Party
from mcpgateway.services.mcp_apps import MCP_UI_EXTENSION
from mcpgateway.services.mcp_method_registry import mcp_method_registry, MCPMethodRegistry


class FakeRequest:
    """Small request double for RPC routing tests."""

    def __init__(self, body: dict) -> None:
        self._body = orjson.dumps(body)
        self.headers = {}
        self.query_params = {}
        self.state = SimpleNamespace()

    async def body(self) -> bytes:
        """Return encoded request body."""
        return self._body


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

    def test_app_bridge_methods_are_gated_on_the_feature_flag(self, monkeypatch):
        """AppBridge methods are only routable while MCP Apps are enabled."""
        registry = MCPMethodRegistry()

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", False)
        assert not registry.is_app_bridge_method("tools/call")

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        for method in ("tools/call", "resources/read", "notifications/message", "ping"):
            assert registry.is_app_bridge_method(method)

    def test_core_methods_are_not_implicitly_app_bridge_methods(self, monkeypatch):
        """Being a core MCP method must not grant an app access over the AppBridge."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        registry = MCPMethodRegistry()

        for method in ("initialize", "tools/list", "prompts/list", "resources/list", "resources/subscribe", "logging/setLevel"):
            assert registry.is_core_method(method)
            assert not registry.is_app_bridge_method(method)

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

    def test_global_registry_instance(self):
        """Global mcp_method_registry instance should be available."""
        assert mcp_method_registry is not None
        assert isinstance(mcp_method_registry, MCPMethodRegistry)


class TestMCPMethodRouting:
    """Tests for MCP method routing behavior."""

    @pytest.mark.asyncio
    async def test_unknown_mcp_apps_method_returns_method_not_found(self, monkeypatch):
        """Unknown MCP Apps methods should return method-not-found error."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        request = FakeRequest({"jsonrpc": "2.0", "id": "ext-1", "method": "extensions/unknown", "params": {}})

        response = await main_mod._handle_rpc_authenticated(request, db=SimpleNamespace(), user={"email": "user@example.com"})

        assert response["error"]["code"] == -32601
        assert response["id"] == "ext-1"

    @pytest.mark.asyncio
    async def test_known_mcp_prefix_but_unknown_method(self, monkeypatch):
        """Known MCP prefix but unknown method should return method-not-found."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        request = FakeRequest({"jsonrpc": "2.0", "id": "ext-2", "method": "io.modelcontextprotocol/unknown", "params": {}})

        response = await main_mod._handle_rpc_authenticated(request, db=SimpleNamespace(), user={"email": "user@example.com"})

        assert response["error"]["code"] == -32601
        assert response["id"] == "ext-2"

    @pytest.mark.asyncio
    async def test_known_extension_method_without_handler_returns_method_not_found(self, monkeypatch):
        """Known extension methods still need explicit handler support."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        request = FakeRequest({"jsonrpc": "2.0", "id": "ext-3", "method": "extensions/known", "params": {}})

        with patch("mcpgateway.services.mcp_method_registry.mcp_method_registry.is_known_method", return_value=True):
            response = await main_mod._handle_rpc_authenticated(request, db=SimpleNamespace(), user={"email": "user@example.com"})

        assert response["error"]["code"] == -32601
        assert response["id"] == "ext-3"

    def test_core_method_precedence(self, monkeypatch):
        """Core MCP methods should be handled first."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

        # First-Party
        from mcpgateway.services.mcp_method_registry import mcp_method_registry

        assert mcp_method_registry.is_core_method("tools/call")
        assert mcp_method_registry.is_known_method("tools/call")
