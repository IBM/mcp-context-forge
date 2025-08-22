# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/transports/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Transport Package.
This package provides transport implementations for the MCP protocol:
- stdio: Communication over standard input/output
- SSE: Server-Sent Events for server-to-client streaming
- WebSocket: Full-duplex communication

Examples:
    >>> # Import all available transport classes
    >>> from mcpgateway.transports import Transport, StdioTransport, SSETransport, WebSocketTransport
    >>>
    >>> # Verify all classes are imported correctly
    >>> Transport.__name__
    'Transport'
    >>> StdioTransport.__name__
    'StdioTransport'
    >>> SSETransport.__name__
    'SSETransport'
    >>> WebSocketTransport.__name__
    'WebSocketTransport'

    >>> # Check that all transports inherit from base Transport
    >>> from mcpgateway.transports.base import Transport
    >>> issubclass(StdioTransport, Transport)
    True
    >>> issubclass(SSETransport, Transport)
    True
    >>> issubclass(WebSocketTransport, Transport)
    True

    >>> # Verify __all__ exports all expected classes
    >>> from mcpgateway.transports import __all__
    >>> sorted(__all__)
    ['SSETransport', 'StdioTransport', 'Transport', 'WebSocketTransport']

    >>> # Test that we can instantiate transport classes
    >>> stdio = StdioTransport()
    >>> isinstance(stdio, Transport)
    True
    >>> sse = SSETransport("http://localhost:8000")
    >>> isinstance(sse, Transport)
    True
    >>> ws = WebSocketTransport("ws://localhost:8000")
    >>> isinstance(ws, Transport)
    True
"""

from mcpgateway.transports.base import Transport
from mcpgateway.transports.sse_transport import SSETransport
from mcpgateway.transports.stdio_transport import StdioTransport
from mcpgateway.transports.websocket_transport import WebSocketTransport

__all__ = ["Transport", "StdioTransport", "SSETransport", "WebSocketTransport"]
