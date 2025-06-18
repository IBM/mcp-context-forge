# -*- coding: utf-8 -*-
"""MCP Gateway Transport-Translation Bridge Package.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Manav Gupta

This package provides transport-translation bridge functionality for the MCP protocol:
- Bridge between stdio, SSE, WebSocket, and Streamable-HTTP transports
- Bidirectional message routing with JSON-RPC integrity
- Security features including token redaction and CORS support
- Health monitoring and observability features
"""

from mcpgateway.translate.bridge import (
    TranslateBridge,
    TransportEndpoint,
    StdIOEndpoint,
    SSEEndpoint,
    WSEndpoint,
    StreamableHTTPEndpoint,
)
from mcpgateway.translate.cli import main

__all__ = [
    "TranslateBridge",
    "TransportEndpoint", 
    "StdIOEndpoint",
    "SSEEndpoint",
    "WSEndpoint",
    "StreamableHTTPEndpoint",
    "main",
]
