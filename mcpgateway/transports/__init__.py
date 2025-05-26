# -*- coding: utf-8 -*-
"""MCP Transport Package.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This package provides transport implementations for the MCP protocol:
- stdio: Communication over standard input/output
- SSE: Server-Sent Events for server-to-client streaming
- WebSocket: Full-duplex communication
"""

from mcpgateway.transports.base import Transport
from mcpgateway.transports.sse_transport import SSETransport
from mcpgateway.transports.stdio_transport import StdioTransport
from mcpgateway.transports.websocket_transport import WebSocketTransport

__all__ = ["Transport", "StdioTransport", "SSETransport", "WebSocketTransport"]
