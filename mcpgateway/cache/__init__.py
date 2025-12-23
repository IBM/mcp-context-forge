# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Cache Package.
Provides caching components for the MCP Gateway including:
- Resource content caching
- Session registry for MCP connections
- GlobalConfig caching for passthrough headers

Note: Imports are lazy to avoid circular dependencies with services.
"""

from typing import TYPE_CHECKING

__all__ = ["GlobalConfigCache", "global_config_cache", "ResourceCache", "SessionRegistry"]

# Lazy imports to avoid circular dependencies
# When services import cache.global_config_cache, we don't want to
# trigger imports of ResourceCache/SessionRegistry which depend on services

if TYPE_CHECKING:
    from mcpgateway.cache.global_config_cache import GlobalConfigCache, global_config_cache
    from mcpgateway.cache.resource_cache import ResourceCache
    from mcpgateway.cache.session_registry import SessionRegistry


def __getattr__(name: str):
    """Lazy import handler for cache submodules."""
    if name in ("GlobalConfigCache", "global_config_cache"):
        from mcpgateway.cache.global_config_cache import GlobalConfigCache, global_config_cache

        return global_config_cache if name == "global_config_cache" else GlobalConfigCache
    elif name == "ResourceCache":
        from mcpgateway.cache.resource_cache import ResourceCache

        return ResourceCache
    elif name == "SessionRegistry":
        from mcpgateway.cache.session_registry import SessionRegistry

        return SessionRegistry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
