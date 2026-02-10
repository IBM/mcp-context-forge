# -*- coding: utf-8 -*-
"""Tests for experimental Rust streamable HTTP bridge behavior."""

from __future__ import annotations

# Standard
import sys
import types

# Third-Party
import pytest

# First-Party
from mcpgateway.transports.rust_streamable_bridge import RustStreamableHTTPTransportBridge


@pytest.mark.asyncio
async def test_bridge_disabled_when_flag_unset(monkeypatch):
    monkeypatch.delenv("MCP_USE_RUST_TRANSPORT", raising=False)
    bridge = RustStreamableHTTPTransportBridge.from_env()
    assert bridge.enabled is False
    assert await bridge.handle_request({}, None, None) is False


@pytest.mark.asyncio
async def test_bridge_enabled_when_module_present(monkeypatch):
    monkeypatch.setenv("MCP_USE_RUST_TRANSPORT", "1")
    fake_module = types.SimpleNamespace(start_streamable_http_transport=lambda _scope: False)
    monkeypatch.setitem(sys.modules, "mcpgateway_transport_rs", fake_module)

    bridge = RustStreamableHTTPTransportBridge.from_env()

    assert bridge.enabled is True
    assert await bridge.handle_request({"path": "/mcp"}, None, None) is False


@pytest.mark.asyncio
async def test_bridge_falls_back_when_module_missing(monkeypatch):
    monkeypatch.setenv("MCP_USE_RUST_TRANSPORT", "1")
    monkeypatch.delitem(sys.modules, "mcpgateway_transport_rs", raising=False)

    bridge = RustStreamableHTTPTransportBridge.from_env()

    assert bridge.enabled is False
    assert await bridge.handle_request({}, None, None) is False