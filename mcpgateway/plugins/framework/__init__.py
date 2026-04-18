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
import asyncio
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

# Redis key for cross-worker/cross-pod global plugin toggle
_REDIS_PLUGINS_ENABLED_KEY = "plugin:global:enabled"
_REDIS_INVALIDATION_CHANNEL = "plugin:invalidation"
_pubsub_task: Optional["asyncio.Task[None]"] = None


def are_plugins_enabled() -> bool:
    """Return whether the plugin subsystem is currently enabled.

    Returns the in-memory flag. For cross-worker consistency,
    use ``are_plugins_enabled_shared()`` which reads from Redis.
    """
    return _PLUGINS_ENABLED


async def are_plugins_enabled_shared() -> bool:
    """Check the global plugin toggle from Redis (shared across all workers/pods).

    Falls back to the in-memory ``_PLUGINS_ENABLED`` flag if Redis is unavailable.
    """
    import logging as _logging  # pylint: disable=import-outside-toplevel

    _log = _logging.getLogger(__name__)
    try:
        from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

        client = await get_redis_client()
        if client:
            val = await client.get(_REDIS_PLUGINS_ENABLED_KEY)
            if val is not None:
                result = val.decode() == "true" if isinstance(val, bytes) else str(val) == "true"
                return result
            # Key not set in Redis — fall through to in-memory
        else:
            _log.debug("are_plugins_enabled_shared: Redis client is None, using in-memory flag")
    except Exception as exc:
        _log.debug("are_plugins_enabled_shared: Redis read failed (%s), using in-memory flag", exc)
    return _PLUGINS_ENABLED


def enable_plugins(toggle: bool) -> None:
    """Enable or disable the plugin subsystem globally (in-memory only).

    For cross-worker/cross-pod propagation, use ``enable_plugins_shared()``.

    Args:
        toggle: Pass ``True`` to activate plugins, ``False`` to deactivate.
    """
    global _PLUGINS_ENABLED
    _PLUGINS_ENABLED = toggle


async def enable_plugins_shared(toggle: bool) -> None:
    """Enable or disable the plugin subsystem globally via Redis.

    Writes to Redis so all workers and pods pick up the change.
    Also updates the local in-memory flag.

    Args:
        toggle: Pass ``True`` to activate plugins, ``False`` to deactivate.
    """
    global _PLUGINS_ENABLED
    _PLUGINS_ENABLED = toggle
    try:
        from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel
        import json as _json  # pylint: disable=import-outside-toplevel

        client = await get_redis_client()
        if client:
            await client.set(_REDIS_PLUGINS_ENABLED_KEY, "true" if toggle else "false")
            try:
                await client.publish(
                    _REDIS_INVALIDATION_CHANNEL,
                    _json.dumps({"type": "global_toggle", "enabled": toggle}),
                )
            except Exception:
                pass  # Publish failure is non-critical — TTL fallback covers it
    except Exception:
        import logging  # pylint: disable=import-outside-toplevel

        logging.getLogger(__name__).warning("Failed to write plugin toggle to Redis — change is local only")


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

    Checks the shared (Redis) plugin toggle on every call so that runtime
    enable/disable propagates across all workers and pods without restart.
    Falls back to the in-memory flag if Redis is unavailable.

    Args:
        server_id: Context identifier used to resolve a specific manager instance.

    Returns:
        Optional[TenantPluginManager]: Context-specific manager when plugins are
            enabled and the factory is initialized, otherwise ``None``.
    """
    if not await are_plugins_enabled_shared():
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


async def get_plugin_mode_override(plugin_name: str) -> Optional[str]:
    """Get a plugin's runtime mode override from Redis.

    Returns None if no override exists (use YAML default).
    """
    try:
        from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

        client = await get_redis_client()
        if client:
            val = await client.get(f"plugin:{plugin_name}:mode")
            if val is not None:
                return val.decode() if isinstance(val, bytes) else str(val)
    except Exception:
        pass
    return None


async def invalidate_all_plugin_managers() -> None:
    """Evict all cached plugin managers so they rebuild with fresh config.

    Call this after a global plugin mode change so all contexts
    pick up the new mode on their next request.
    """
    if _plugin_manager_factory is None:
        return
    async with _plugin_manager_factory._lock:
        contexts = list(_plugin_manager_factory._managers.keys())
    for ctx_id in contexts:
        await _plugin_manager_factory.reload_tenant(ctx_id)


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


async def _handle_invalidation_message(message: dict) -> None:
    """Handle a single pub/sub invalidation message.

    Called by the background subscriber task when a message arrives
    on the ``plugin:invalidation`` channel.

    Args:
        message: Redis pub/sub message dict with 'type' and 'data' keys.
    """
    import json as _json  # pylint: disable=import-outside-toplevel
    import logging as _logging  # pylint: disable=import-outside-toplevel

    _log = _logging.getLogger(__name__)

    if message.get("type") != "message":
        return  # Ignore subscribe/unsubscribe notifications

    try:
        data = _json.loads(message["data"])
    except (ValueError, KeyError, TypeError):
        _log.debug("Ignoring malformed invalidation message")
        return

    msg_type = data.get("type")

    if msg_type == "global_toggle":
        global _PLUGINS_ENABLED
        _PLUGINS_ENABLED = data.get("enabled", True)
        _log.debug("Pub/sub: global toggle set to %s", _PLUGINS_ENABLED)

    elif msg_type == "mode_change":
        await invalidate_all_plugin_managers()
        _log.debug("Pub/sub: mode change for %s, all managers invalidated", data.get("plugin"))

    elif msg_type == "binding_change":
        context_id = data.get("context_id")
        if context_id and _plugin_manager_factory is not None:
            try:
                await _plugin_manager_factory.reload_tenant(context_id)
                _log.debug("Pub/sub: binding change, reloaded context %s", context_id)
            except Exception:
                _log.debug("Pub/sub: failed to reload context %s", context_id)


async def _plugin_invalidation_listener() -> None:
    """Background task that subscribes to Redis pub/sub for instant cache invalidation.

    Listens on the ``plugin:invalidation`` channel and processes messages
    to evict stale plugin managers. Automatically reconnects on Redis disconnect.
    The TTL-based cache refresh serves as fallback if this listener is down.
    """
    import logging as _logging  # pylint: disable=import-outside-toplevel

    _log = _logging.getLogger(__name__)

    while True:
        try:
            from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

            client = await get_redis_client()
            if not client:
                _log.debug("Plugin invalidation listener: Redis not available, retrying in 10s")
                await asyncio.sleep(10)
                continue

            pubsub = client.pubsub()
            await pubsub.subscribe(_REDIS_INVALIDATION_CHANNEL)
            _log.info("Plugin invalidation listener started on channel: %s", _REDIS_INVALIDATION_CHANNEL)

            async for message in pubsub.listen():
                await _handle_invalidation_message(message)

        except asyncio.CancelledError:
            _log.info("Plugin invalidation listener cancelled")
            break
        except Exception as exc:
            _log.warning("Plugin invalidation listener error (%s), reconnecting in 5s", exc)
            await asyncio.sleep(5)


async def start_plugin_invalidation_listener() -> None:
    """Start the background pub/sub listener task.

    Safe to call multiple times — only starts one listener.
    Called during gateway lifespan startup.
    """
    global _pubsub_task
    if _pubsub_task is not None and not _pubsub_task.done():
        return  # Already running
    _pubsub_task = asyncio.create_task(_plugin_invalidation_listener())


async def stop_plugin_invalidation_listener() -> None:
    """Stop the background pub/sub listener task.

    Called during gateway lifespan shutdown.
    """
    global _pubsub_task
    if _pubsub_task is not None and not _pubsub_task.done():
        _pubsub_task.cancel()
        try:
            await _pubsub_task
        except asyncio.CancelledError:
            pass
    _pubsub_task = None


__all__ = [
    "AgentHookType",
    "AgentPostInvokePayload",
    "AgentPostInvokeResult",
    "AgentPreInvokePayload",
    "AgentPreInvokeResult",
    "are_plugins_enabled",
    "are_plugins_enabled_shared",
    "enable_plugins",
    "enable_plugins_shared",
    "get_plugin_mode_override",
    "invalidate_all_plugin_managers",
    "start_plugin_invalidation_listener",
    "stop_plugin_invalidation_listener",
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
