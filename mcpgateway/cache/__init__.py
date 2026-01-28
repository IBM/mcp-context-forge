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
- Auth caching for user, team, and token revocation data
- Registry caching for tools, prompts, resources, agents, servers, gateways
- Admin stats caching for dashboard statistics

Note: Imports are lazy to avoid circular dependencies with services.
"""

from typing import TYPE_CHECKING

__all__ = [
    "A2AStatsCache",
    "a2a_stats_cache",
    "AdminStatsCache",
    "admin_stats_cache",
    "AuthCache",
    "auth_cache",
    "CachedAuthContext",
    "GlobalConfigCache",
    "global_config_cache",
    "MetricsCache",
    "metrics_cache",
    "RegistryCache",
    "registry_cache",
    "ToolLookupCache",
    "tool_lookup_cache",
    "ResourceCache",
    "SessionRegistry",
]

# Lazy imports to avoid circular dependencies
# When services import cache.global_config_cache, we don't want to
# trigger imports of ResourceCache/SessionRegistry which depend on services

if TYPE_CHECKING:
    from mcpgateway.cache.a2a_stats_cache import A2AStatsCache, a2a_stats_cache
    from mcpgateway.cache.admin_stats_cache import AdminStatsCache, admin_stats_cache
    from mcpgateway.cache.auth_cache import AuthCache, auth_cache, CachedAuthContext
    from mcpgateway.cache.global_config_cache import GlobalConfigCache, global_config_cache
    from mcpgateway.cache.metrics_cache import MetricsCache, metrics_cache
    from mcpgateway.cache.registry_cache import RegistryCache, registry_cache
    from mcpgateway.cache.tool_lookup_cache import ToolLookupCache, tool_lookup_cache
    from mcpgateway.cache.resource_cache import ResourceCache
    from mcpgateway.cache.session_registry import SessionRegistry


def __getattr__(name: str):
    """Lazy import handler for cache submodules.

    Args:
        name: The attribute name being accessed.

    Returns:
        The requested cache class or instance.

    Raises:
        AttributeError: If the requested attribute is not found.
    """
    # pylint: disable=import-outside-toplevel
    if name in ("A2AStatsCache", "a2a_stats_cache"):
        from mcpgateway.cache.a2a_stats_cache import A2AStatsCache, a2a_stats_cache

        return a2a_stats_cache if name == "a2a_stats_cache" else A2AStatsCache
    if name in ("AdminStatsCache", "admin_stats_cache"):
        from mcpgateway.cache.admin_stats_cache import AdminStatsCache, admin_stats_cache

        return admin_stats_cache if name == "admin_stats_cache" else AdminStatsCache
    if name in ("AuthCache", "auth_cache", "CachedAuthContext"):
        from mcpgateway.cache.auth_cache import AuthCache, auth_cache, CachedAuthContext

        if name == "auth_cache":
            return auth_cache
        if name == "CachedAuthContext":
            return CachedAuthContext
        return AuthCache
    if name in ("GlobalConfigCache", "global_config_cache"):
        from mcpgateway.cache.global_config_cache import GlobalConfigCache, global_config_cache

        return global_config_cache if name == "global_config_cache" else GlobalConfigCache
    if name in ("MetricsCache", "metrics_cache"):
        from mcpgateway.cache.metrics_cache import MetricsCache, metrics_cache

        return metrics_cache if name == "metrics_cache" else MetricsCache
    if name in ("RegistryCache", "registry_cache"):
        from mcpgateway.cache.registry_cache import RegistryCache, registry_cache

        return registry_cache if name == "registry_cache" else RegistryCache
    if name in ("ToolLookupCache", "tool_lookup_cache"):
        from mcpgateway.cache.tool_lookup_cache import ToolLookupCache, tool_lookup_cache

        return tool_lookup_cache if name == "tool_lookup_cache" else ToolLookupCache
    if name == "ResourceCache":
        from mcpgateway.cache.resource_cache import ResourceCache

        return ResourceCache
    if name == "SessionRegistry":
        from mcpgateway.cache.session_registry import SessionRegistry

        return SessionRegistry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
