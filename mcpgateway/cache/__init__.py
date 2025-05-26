# -*- coding: utf-8 -*-
"""Cache Package.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Provides caching components for the MCP Gateway including:
- Resource content caching
"""

from mcpgateway.cache.resource_cache import ResourceCache
from mcpgateway.cache.session_registry import SessionRegistry

__all__ = ["ResourceCache", "SessionRegistry"]
