# -*- coding: utf-8 -*-
"""Location: ./mcp_reverse_proxy/base.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Base classes and interfaces for reverse proxy transports.
This module defines abstract base classes for local and remote transports,
enabling extensible support for multiple MCP transport protocols.
"""

# Future
from __future__ import annotations

# Standard
from abc import ABC, abstractmethod
from enum import Enum
from typing import Awaitable, Callable


class ConnectionState(Enum):
    """Connection state enumeration."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    SHUTTING_DOWN = "shutting_down"


class MessageType(Enum):
    """Control message types for the reverse proxy protocol."""

    # Control messages
    REGISTER = "register"
    UNREGISTER = "unregister"
    HEARTBEAT = "heartbeat"
    ERROR = "error"

    # MCP messages
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"


class McpServerTransport(ABC):
    """Abstract base class for MCP server transports.

    Handles communication with MCP servers via various protocols
    (stdio, HTTP, SSE, etc.). The server can be local or remote.
    """

    @abstractmethod
    async def start(self) -> None:
        """Start the MCP server transport.

        Raises:
            RuntimeError: If transport fails to start.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Stop the MCP server transport gracefully."""

    @abstractmethod
    async def send(self, message: str) -> None:
        """Send a message to the MCP server.

        Args:
            message: JSON-RPC message to send.

        Raises:
            RuntimeError: If transport is not running.
        """

    @abstractmethod
    def add_message_handler(self, handler: Callable[[str], Awaitable[None]]) -> None:
        """Add a handler for messages from the MCP server.

        Args:
            handler: Async function to handle messages.
        """

    def set_authentication(self, auth_headers: dict[str, str], auth_type: str | None = None) -> None:
        """Set authentication headers for subsequent requests to the MCP server.

        Args:
            auth_headers: Dictionary of HTTP headers to use for authentication.
            auth_type: Type of authentication (basic, bearer, authheaders, etc.)

        Note:
            This is optional and only used by HTTP-based transports.
            Stdio-based transports can ignore this as they don't use HTTP headers.
        """
        pass  # Default implementation does nothing (for stdio)


class GatewayTransport(ABC):
    """Abstract base class for gateway transports.

    Handles communication with the remote gateway (currently WebSocket only).
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to gateway.

        Raises:
            Exception: If connection fails.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to gateway."""

    @abstractmethod
    async def send(self, message: str | bytes) -> None:
        """Send a message to the gateway.

        Args:
            message: Message to send (str or bytes).

        Raises:
            RuntimeError: If not connected.
        """

    @abstractmethod
    def add_message_handler(self, handler: Callable[[str], Awaitable[None]]) -> None:
        """Add a handler for messages from the gateway.

        Args:
            handler: Async function to handle messages.
        """

    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if transport is connected.

        Returns:
            True if connected to gateway.
        """
