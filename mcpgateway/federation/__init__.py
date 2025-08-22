# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/federation/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Federation Package.
Exposes components for MCP Gateway federation including:
- Gateway discovery
- Request forwarding
- Federation management
"""

from mcpgateway.federation.discovery import DiscoveryService
from mcpgateway.federation.forward import ForwardingService

__all__ = [
    "DiscoveryService",
    "ForwardingService",
]
