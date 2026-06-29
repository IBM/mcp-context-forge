# -*- coding: utf-8 -*-
"""Location: ./mcp_reverse_proxy/tests/test_mcp_reverse_proxy_base.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for reverse proxy transport base classes.
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import AsyncMock

# Third-Party
import pytest

# First-Party
from mcp_reverse_proxy.base import ConnectionState, GatewayTransport, McpServerTransport, MessageType


class DummyMcpTransport(McpServerTransport):
    """Concrete MCP transport for exercising base class behavior."""

    def __init__(self) -> None:
        self.handlers = []
        self.auth_calls = []

    async def start(self) -> None:
        """Start the transport."""

    async def stop(self) -> None:
        """Stop the transport."""

    async def send(self, message: str) -> None:
        """Send a message."""
        self.last_message = message

    def add_message_handler(self, handler) -> None:
        """Register a message handler."""
        self.handlers.append(handler)

    def set_authentication(self, auth_headers: dict[str, str], auth_type: str | None = None) -> None:
        """Delegate to the base implementation and record the call."""
        super().set_authentication(auth_headers, auth_type)
        self.auth_calls.append((auth_headers, auth_type))


class DummyGatewayTransport(GatewayTransport):
    """Concrete gateway transport for exercising abstract contract behavior."""

    def __init__(self) -> None:
        self.handlers = []
        self.sent_messages = []
        self.connected = False

    async def connect(self) -> None:
        """Open the connection."""
        self.connected = True

    async def disconnect(self) -> None:
        """Close the connection."""
        self.connected = False

    async def send(self, message: str | bytes) -> None:
        """Record a sent message."""
        self.sent_messages.append(message)

    def add_message_handler(self, handler) -> None:
        """Register a message handler."""
        self.handlers.append(handler)

    async def is_connected(self) -> bool:
        """Return current connection status."""
        return self.connected


def test_connection_state_enum_values_are_stable() -> None:
    """Connection state enum values should match protocol expectations."""
    assert ConnectionState.DISCONNECTED.value == "disconnected"
    assert ConnectionState.CONNECTING.value == "connecting"
    assert ConnectionState.CONNECTED.value == "connected"
    assert ConnectionState.RECONNECTING.value == "reconnecting"
    assert ConnectionState.SHUTTING_DOWN.value == "shutting_down"


def test_message_type_enum_values_are_stable() -> None:
    """Message type enum values should match the reverse proxy protocol."""
    assert MessageType.REGISTER.value == "register"
    assert MessageType.UNREGISTER.value == "unregister"
    assert MessageType.HEARTBEAT.value == "heartbeat"
    assert MessageType.ERROR.value == "error"
    assert MessageType.REQUEST.value == "request"
    assert MessageType.RESPONSE.value == "response"
    assert MessageType.NOTIFICATION.value == "notification"


def test_mcp_server_transport_cannot_be_instantiated_directly() -> None:
    """Abstract MCP transport should reject direct instantiation."""
    with pytest.raises(TypeError):
        McpServerTransport()


def test_gateway_transport_cannot_be_instantiated_directly() -> None:
    """Abstract gateway transport should reject direct instantiation."""
    with pytest.raises(TypeError):
        GatewayTransport()


@pytest.mark.asyncio
async def test_mcp_server_transport_default_set_authentication_is_noop() -> None:
    """Default MCP auth hook should accept headers without mutating behavior."""
    transport = DummyMcpTransport()

    transport.set_authentication({"Authorization": "Bearer token"}, "bearer")

    assert transport.auth_calls == [({"Authorization": "Bearer token"}, "bearer")]


@pytest.mark.asyncio
async def test_dummy_mcp_transport_implements_base_contract() -> None:
    """Concrete MCP transport should satisfy the abstract interface."""
    transport = DummyMcpTransport()
    handler = AsyncMock()

    await transport.start()
    transport.add_message_handler(handler)
    await transport.send('{"jsonrpc":"2.0"}')
    await transport.stop()

    assert transport.handlers == [handler]
    assert transport.last_message == '{"jsonrpc":"2.0"}'


@pytest.mark.asyncio
async def test_dummy_gateway_transport_implements_base_contract() -> None:
    """Concrete gateway transport should satisfy the abstract interface."""
    transport = DummyGatewayTransport()
    handler = AsyncMock()

    await transport.connect()
    transport.add_message_handler(handler)
    await transport.send("message")
    assert await transport.is_connected() is True

    await transport.disconnect()

    assert transport.handlers == [handler]
    assert transport.sent_messages == ["message"]
    assert await transport.is_connected() is False

