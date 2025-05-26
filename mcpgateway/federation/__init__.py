# -*- coding: utf-8 -*-
"""Federation Package.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Exposes components for MCP Gateway federation including:
- Gateway discovery
- Request forwarding
- Federation management
"""

from mcpgateway.federation.discovery import DiscoveryService
from mcpgateway.federation.forward import ForwardingService
from mcpgateway.federation.manager import (
    FederationError,
    FederationManager,
)

__all__ = [
    "DiscoveryService",
    "ForwardingService",
    "FederationManager",
    "FederationError",
]
