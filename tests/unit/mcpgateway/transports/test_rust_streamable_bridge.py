# -*- coding: utf-8 -*-
"""Tests for experimental Rust streamable HTTP bridge behavior."""

from __future__ import annotations

# Standard
import sys
import types

# Third-Party
import pytest

# First-Party
from mcpgateway.transports import rust_streamable_bridge as bridge_mod
from mcpgateway.transports.rust_streamable_bridge import RustStreamableHTTPTransportBridge


def test_import_transport_module_handles_namespace_shadow(monkeypatch):
    class MissingAttrsModule:  # pragma: no cover - tiny local helper
        __file__ = None

    class PresentModule:
        @staticmethod
        def prepare_streamable_http_context(_scope):
            return {}

        @staticmethod
        def start_streamable_http_transport(_scope, _receive, _send):
            return True

    monkeypatch.setattr(bridge_mod.importlib, "import_module", lambda _name: MissingAttrsModule())

    class DummyLoader:
        def create_module(self, spec):
            return None

        def exec_module(self, module):
            module.prepare_streamable_http_context = PresentModule.prepare_streamable_http_context
            module.start_streamable_http_transport = PresentModule.start_streamable_http_transport

    spec = bridge_mod.machinery.ModuleSpec("mcpgateway_transport_rs", DummyLoader(), origin="/tmp/mcpgateway_transport_rs.so")
    monkeypatch.setattr(bridge_mod.machinery.PathFinder, "find_spec", lambda _name, _paths: spec)

    module = bridge_mod._import_transport_module()

    assert hasattr(module, "prepare_streamable_http_context")
    assert hasattr(module, "start_streamable_http_transport")


def test_import_transport_module_raises_when_rust_missing(monkeypatch):
    monkeypatch.setattr(bridge_mod.importlib, "import_module", lambda _name: types.SimpleNamespace())
    monkeypatch.setattr(bridge_mod.machinery.PathFinder, "find_spec", lambda _name, _paths: None)

    with pytest.raises(ImportError):
        bridge_mod._import_transport_module()


@pytest.mark.asyncio
async def test_bridge_disabled_when_flag_unset(monkeypatch):
    monkeypatch.delenv("MCP_USE_RUST_TRANSPORT", raising=False)
    bridge = RustStreamableHTTPTransportBridge.from_env()
    context = await bridge.prepare_request_context({"modified_path": "/servers/abc/mcp", "headers_dict": {"x-a": "1"}})

    assert bridge.enabled is False
    assert context.path == "/servers/abc/mcp"
    assert context.headers == {"x-a": "1"}
    assert context.server_id == "abc"
    assert context.is_mcp_path is True


@pytest.mark.asyncio
async def test_bridge_enabled_when_module_present(monkeypatch):
    monkeypatch.setenv("MCP_USE_RUST_TRANSPORT", "1")

    def fake_prepare(_scope):
        return {
            "path": "/servers/uuid/mcp",
            "headers": {"authorization": "Bearer abc"},
            "server_id": "uuid",
            "is_mcp_path": True,
        }

    async def fake_start(_scope, _receive, _send):
        return True
    fake_module = types.SimpleNamespace(prepare_streamable_http_context=fake_prepare)
    fake_module.start_streamable_http_transport = fake_start
    monkeypatch.setitem(sys.modules, "mcpgateway_transport_rs", fake_module)

    bridge = RustStreamableHTTPTransportBridge.from_env()
    context = await bridge.prepare_request_context({"path": "/x"})

    assert bridge.enabled is True
    assert context.server_id == "uuid"
    assert context.is_mcp_path is True
    assert context.headers["authorization"] == "Bearer abc"


@pytest.mark.asyncio
async def test_bridge_falls_back_when_rust_context_fails(monkeypatch):
    monkeypatch.setenv("MCP_USE_RUST_TRANSPORT", "1")

    def fake_prepare(_scope):
        raise RuntimeError("boom")

    async def fake_start(_scope, _receive, _send):
        return False

    fake_module = types.SimpleNamespace(prepare_streamable_http_context=fake_prepare)
    fake_module.start_streamable_http_transport = fake_start
    monkeypatch.setitem(sys.modules, "mcpgateway_transport_rs", fake_module)

    bridge = RustStreamableHTTPTransportBridge.from_env()
    context = await bridge.prepare_request_context({"modified_path": "/mcp", "headers_dict": {"X-Test": "ok"}})

    assert context.path == "/mcp"
    assert context.is_mcp_path is True
    assert context.headers == {"x-test": "ok"}


@pytest.mark.asyncio
async def test_bridge_handle_request_uses_rust_handler(monkeypatch):
    monkeypatch.setenv("MCP_USE_RUST_TRANSPORT", "1")

    def fake_prepare(_scope):
        return {"path": "/mcp", "headers": {}, "is_mcp_path": True}

    async def fake_start(_scope, _receive, _send):
        return True

    fake_module = types.SimpleNamespace(prepare_streamable_http_context=fake_prepare)
    fake_module.start_streamable_http_transport = fake_start
    monkeypatch.setitem(sys.modules, "mcpgateway_transport_rs", fake_module)

    bridge = RustStreamableHTTPTransportBridge.from_env()
    handled = await bridge.handle_request({}, None, None)

    assert handled is True


@pytest.mark.asyncio
async def test_bridge_handle_request_fallback_on_handler_error(monkeypatch):
    monkeypatch.setenv("MCP_USE_RUST_TRANSPORT", "1")

    def fake_prepare(_scope):
        return {"path": "/mcp", "headers": {}, "is_mcp_path": True}

    async def fake_start(_scope, _receive, _send):
        raise RuntimeError("boom")

    fake_module = types.SimpleNamespace(prepare_streamable_http_context=fake_prepare)
    fake_module.start_streamable_http_transport = fake_start
    monkeypatch.setitem(sys.modules, "mcpgateway_transport_rs", fake_module)

    bridge = RustStreamableHTTPTransportBridge.from_env()
    handled = await bridge.handle_request({}, None, None)

    assert handled is False


@pytest.mark.asyncio
async def test_bridge_handle_request_supports_sync_handlers(monkeypatch):
    monkeypatch.setenv("MCP_USE_RUST_TRANSPORT", "1")

    def fake_prepare(_scope):
        return {"path": "/mcp", "headers": {}, "is_mcp_path": True}

    def fake_start(_scope, _receive, _send):
        return True

    fake_module = types.SimpleNamespace(prepare_streamable_http_context=fake_prepare)
    fake_module.start_streamable_http_transport = fake_start
    monkeypatch.setitem(sys.modules, "mcpgateway_transport_rs", fake_module)

    bridge = RustStreamableHTTPTransportBridge.from_env()
    handled = await bridge.handle_request({}, None, None)

    assert handled is True
