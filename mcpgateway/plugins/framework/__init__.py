# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Services Package.
Exposes core ContextForge plugin components:
- Context
- Manager
- Payloads
- Models
- ExternalPluginServer
"""

# Standard
from typing import Callable, Optional

# First-Party
from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.errors import PluginError, PluginViolationError
from mcpgateway.plugins.framework.external.mcp.server import ExternalPluginServer
from mcpgateway.plugins.framework.hooks.agents import AgentHookType, AgentPostInvokePayload, AgentPostInvokeResult, AgentPreInvokePayload, AgentPreInvokeResult
from mcpgateway.plugins.framework.hooks.http import (
    HttpAuthCheckPermissionPayload,
    HttpAuthCheckPermissionResult,
    HttpAuthCheckPermissionResultPayload,
    HttpAuthResolveUserPayload,
    HttpAuthResolveUserResult,
    HttpHeaderPayload,
    HttpHookType,
    HttpPostRequestPayload,
    HttpPostRequestResult,
    HttpPreRequestPayload,
    HttpPreRequestResult,
)
from mcpgateway.plugins.framework.hooks.prompts import (
    PromptHookType,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
)
from mcpgateway.plugins.framework.hooks.registry import get_hook_registry, HookRegistry
from mcpgateway.plugins.framework.hooks.resources import ResourceHookType, ResourcePostFetchPayload, ResourcePostFetchResult, ResourcePreFetchPayload, ResourcePreFetchResult
from mcpgateway.plugins.framework.hooks.tools import ToolHookType, ToolPostInvokePayload, ToolPostInvokeResult, ToolPreInvokePayload, ToolPreInvokeResult
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework.manager import PluginManager, TenantPluginManager, TenantPluginManagerFactory
from mcpgateway.plugins.framework.models import (
    GlobalContext,
    MCPServerConfig,
    PluginCondition,
    PluginConfig,
    PluginContext,
    PluginContextTable,
    PluginErrorModel,
    PluginMode,
    PluginPayload,
    PluginResult,
    PluginViolation,
)
from mcpgateway.plugins.framework.observability import ObservabilityProvider
from mcpgateway.plugins.framework.utils import get_attr

# --- Global plugin manager factory singleton ---
_PLUGINS_ENABLED = False
_plugin_manager_factory: Optional[TenantPluginManagerFactory] = None
_observability_service: Optional[ObservabilityProvider] = None
DEFAULT_SERVER_ID = "__global__"


def enable_plugins(toggle: bool) -> None:
    """Enable or disable the plugin subsystem globally.

    Args:
        toggle: Pass ``True`` to activate plugins, ``False`` to deactivate.
    """
    global _PLUGINS_ENABLED
    _PLUGINS_ENABLED = toggle


def init_plugin_manager_factory(
    yaml_path: str,
    timeout: float,
    hook_policies: dict,
    observability: Optional[ObservabilityProvider] = None,
    db_factory: Optional[Callable] = None,
) -> None:
    """Explicitly initialise the global plugin manager factory.

    Called from ``main.py`` lifespan startup after all dependencies
    (observability, settings) are ready.  Prefer this over the lazy
    initialisation path inside :func:`get_plugin_manager` so that the
    factory is always created with a fully-wired dependency set.

    Args:
        yaml_path: Path to the plugins YAML config file.
        timeout: Per-plugin call timeout in seconds.
        hook_policies: Hook payload policy map from ``mcpgateway.plugins.policy``.
        observability: Optional observability provider to attach to the factory.
        db_factory: Zero-argument callable returning a SQLAlchemy Session
            (e.g. ``SessionLocal``).  When provided the factory uses
            :class:`~mcpgateway.plugins.gateway_plugin_manager.GatewayTenantPluginManagerFactory`
            so per-tool plugin bindings stored in the DB are applied.
            When ``None`` the base :class:`TenantPluginManagerFactory` is used
            (no DB overrides).
    """
    global _plugin_manager_factory
    global _observability_service
    _observability_service = observability
    if db_factory is not None:
        # Lazy import to avoid circular dependency:
        # framework/__init__ → gateway_plugin_manager → services → base_service → framework/__init__
        from mcpgateway.plugins.gateway_plugin_manager import GatewayTenantPluginManagerFactory  # pylint: disable=import-outside-toplevel

        _plugin_manager_factory = GatewayTenantPluginManagerFactory(
            yaml_path=yaml_path,
            timeout=timeout,
            hook_policies=hook_policies,
            observability=observability,
            db_factory=db_factory,
        )
    else:
        _plugin_manager_factory = TenantPluginManagerFactory(
            yaml_path=yaml_path,
            timeout=timeout,
            hook_policies=hook_policies,
            observability=observability,
        )


async def get_plugin_manager(server_id: str = DEFAULT_SERVER_ID) -> Optional[TenantPluginManager]:
    """Return a context-scoped plugin manager from the global async factory.

    Args:
        server_id: Context identifier used to resolve a specific manager instance.

    Returns:
        Optional[TenantPluginManager]: Context-specific manager when plugins are
            enabled and the factory is initialized, otherwise ``None``.
    """
    if not _PLUGINS_ENABLED:
        return None

    if _plugin_manager_factory is None:
        return None

    return await _plugin_manager_factory.get_manager(server_id)


def set_global_observability(observability: ObservabilityProvider) -> None:
    """Set the global observability provider and propagate it to the active factory.

    Args:
        observability: The observability provider to attach.
    """
    global _observability_service
    _observability_service = observability
    if _plugin_manager_factory is not None:
        _plugin_manager_factory.observability = observability


async def shutdown_plugin_manager_factory() -> None:
    """Shutdown and reset the global plugin manager factory.

    Calls :meth:`TenantPluginManagerFactory.shutdown` on the singleton factory (if one has
    been initialised) and then clears the reference so the next call to
    :func:`get_plugin_manager` will create a fresh factory.  Primarily used during
    application lifespan teardown.
    """
    global _plugin_manager_factory  # pylint: disable=global-statement

    if not _PLUGINS_ENABLED:
        return
    factory = _plugin_manager_factory
    _plugin_manager_factory = None
    if factory is not None:
        await factory.shutdown()


def reset_plugin_manager_factory() -> None:
    """Reset the global factory and all per-server managers (primarily for tests)."""
    global _plugin_manager_factory
    _plugin_manager_factory = None


async def reload_plugin_context(context_id: str) -> None:
    """Invalidate and rebuild the cached plugin manager for *context_id*.

    No-op when plugins are disabled or the factory is not initialised.
    Call this after persisting a ToolPluginBinding change so the next tool
    invocation picks up the updated DB overrides.

    Args:
        context_id: Context key to evict and rebuild (e.g. ``"<team_id>::<tool_name>"``).
    """
    if not _PLUGINS_ENABLED or _plugin_manager_factory is None:
        return
    await _plugin_manager_factory.reload_tenant(context_id)


__all__ = [
    "AgentHookType",
    "AgentPostInvokePayload",
    "AgentPostInvokeResult",
    "AgentPreInvokePayload",
    "AgentPreInvokeResult",
    "enable_plugins",
    "init_plugin_manager_factory",
    "set_global_observability",
    "ConfigLoader",
    "ExternalPluginServer",
    "get_attr",
    "get_hook_registry",
    "get_plugin_manager",
    "shutdown_plugin_manager_factory",
    "reset_plugin_manager_factory",
    "reload_plugin_context",
    "GlobalContext",
    "HookRegistry",
    "HttpAuthCheckPermissionPayload",
    "HttpAuthCheckPermissionResult",
    "HttpAuthCheckPermissionResultPayload",
    "HttpAuthResolveUserPayload",
    "HttpAuthResolveUserResult",
    "HttpHeaderPayload",
    "HttpHookType",
    "HttpPostRequestPayload",
    "HttpPostRequestResult",
    "HttpPreRequestPayload",
    "HttpPreRequestResult",
    "MCPServerConfig",
    "ObservabilityProvider",
    "Plugin",
    "PluginCondition",
    "PluginConfig",
    "PluginContext",
    "PluginContextTable",
    "PluginError",
    "PluginErrorModel",
    "PluginLoader",
    "PluginManager",
    "TenantPluginManager",
    "TenantPluginManagerFactory",
    "PluginMode",
    "PluginPayload",
    "PluginResult",
    "PluginViolation",
    "PluginViolationError",
    "PromptHookType",
    "PromptPosthookPayload",
    "PromptPosthookResult",
    "PromptPrehookPayload",
    "PromptPrehookResult",
    "ResourceHookType",
    "ResourcePostFetchPayload",
    "ResourcePostFetchResult",
    "ResourcePreFetchPayload",
    "ResourcePreFetchResult",
    "ToolHookType",
    "ToolPostInvokePayload",
    "ToolPostInvokeResult",
    "ToolPreInvokeResult",
    "ToolPreInvokePayload",
]
