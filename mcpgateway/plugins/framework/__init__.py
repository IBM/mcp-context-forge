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
import json
import logging
import random
import time
from typing import Any, Callable, Literal, Optional, Union

# Third-Party
from pydantic import BaseModel, TypeAdapter
from pydantic import ValidationError as _ValidationError

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
from mcpgateway.plugins.framework import _state
from mcpgateway.plugins.framework._redis import get_shared_redis_client as _redis
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

# Redis keys / channel for cross-worker/cross-pod runtime coordination.
_REDIS_PLUGINS_ENABLED_KEY = "plugin:global:enabled"
_REDIS_INVALIDATION_CHANNEL = "plugin:invalidation"
_PLUGIN_MODE_TTL_SECONDS = 86400  # 24 h — aligned with the Redis key ``ex=`` value.
_pubsub_task: Optional["asyncio.Task[None]"] = None
# Guards the check-then-create-task pattern in start_plugin_invalidation_listener
# so two concurrent callers can't both reach ``asyncio.create_task`` and leak
# a second Redis subscription.
_pubsub_start_lock = asyncio.Lock()

# Short-lived local cache for the shared "plugins enabled" flag. get_plugin_manager
# is called on every authenticated request; without this each call would cost a
# Redis round-trip. The pub/sub listener invalidates the cache on global_toggle
# messages, so the TTL only bounds the worst case when pub/sub is down.
_SHARED_ENABLED_CACHE_TTL = 2.0
_shared_enabled_cache: Optional[tuple[bool, float]] = None
_shared_enabled_cache_lock = asyncio.Lock()

# Per-plugin mode-override state and the degraded-boot flag live in ``_state``
# (a leaf submodule) so ``framework.manager`` can read them without importing
# ``framework/__init__.py`` — otherwise we'd have a static ``framework ->
# framework.manager -> framework`` import cycle that pylint R0401 flags.
# Writers in this module go through ``_state.set_local_mode_override`` /
# ``_state.clear_local_mode_overrides``; no alias is held so the single
# write seam is genuinely single.

_logger = logging.getLogger(__name__)


class _GlobalToggleMsg(BaseModel):
    """Pub/sub frame announcing a plugin subsystem enable/disable."""

    type: Literal["global_toggle"]
    enabled: bool


class _ModeChangeMsg(BaseModel):
    """Pub/sub frame announcing a per-plugin mode override change.

    ``ttl_seconds`` carries the Redis-key TTL from the publisher so every peer
    stamps the same absolute deadline on its local override copy. Defaults to
    the canonical 24 h constant for back-compat with older publishers.
    """

    type: Literal["mode_change"]
    plugin: str
    mode: Literal["enforce", "enforce_ignore_error", "permissive", "disabled"]
    ttl_seconds: int = _PLUGIN_MODE_TTL_SECONDS


class _BindingChangeMsg(BaseModel):
    """Pub/sub frame announcing a ToolPluginBinding change for a single context."""

    type: Literal["binding_change"]
    context_id: str


class _TeamBindingChangeMsg(BaseModel):
    """Pub/sub frame announcing a wildcard binding change — every cached context for the team must be evicted."""

    type: Literal["team_binding_change"]
    team_id: str


# Discriminated union shared by producer and consumer. A typo in the ``type``
# field on the producer fails Pydantic validation on the listener instead of
# silently no-oping.
_InvalidationMsg = Union[_GlobalToggleMsg, _ModeChangeMsg, _BindingChangeMsg, _TeamBindingChangeMsg]
_invalidation_adapter: TypeAdapter[_InvalidationMsg] = TypeAdapter(_InvalidationMsg)


def are_plugins_enabled() -> bool:
    """Return the in-memory plugin-subsystem flag."""
    return _PLUGINS_ENABLED


async def _read_shared_enabled() -> bool:
    """Fetch the shared toggle from Redis or fall back to the in-memory flag."""
    try:
        client = await _redis()
    except Exception as exc:
        _logger.warning("Plugin shared toggle read failed (%s), using in-memory flag", exc)
        return _PLUGINS_ENABLED

    if client is None:
        return _PLUGINS_ENABLED

    try:
        val = await client.get(_REDIS_PLUGINS_ENABLED_KEY)
    except Exception as exc:
        _logger.warning("Plugin shared toggle Redis GET failed (%s), using in-memory flag", exc)
        return _PLUGINS_ENABLED

    if val is None:
        return _PLUGINS_ENABLED
    return val.decode() == "true" if isinstance(val, bytes) else str(val) == "true"


async def are_plugins_enabled_shared() -> bool:
    """Return the shared plugin-subsystem toggle, cached briefly to stay off the hot path."""
    global _shared_enabled_cache
    async with _shared_enabled_cache_lock:
        cache = _shared_enabled_cache
        now = asyncio.get_event_loop().time()
        if cache is not None and (now - cache[1]) < _SHARED_ENABLED_CACHE_TTL:
            return cache[0]

        value = await _read_shared_enabled()
        _shared_enabled_cache = (value, now)
        return value


def _invalidate_shared_enabled_cache() -> None:
    """Drop the local memoization so the next read goes to Redis.

    Called by the pub/sub listener when a global_toggle broadcast arrives.
    """
    global _shared_enabled_cache
    _shared_enabled_cache = None


def enable_plugins(toggle: bool) -> None:
    """Toggle the in-memory flag. Use ``enable_plugins_shared`` for cross-worker reach."""
    global _PLUGINS_ENABLED
    _PLUGINS_ENABLED = toggle
    _invalidate_shared_enabled_cache()


async def enable_plugins_shared(toggle: bool) -> bool:
    """Persist the global toggle to Redis (no TTL — operator kill-switch persists) and broadcast the change.

    Returns True when Redis accepted the write. Falls back to the in-memory flag
    on Redis failure so the current worker still honors the operator intent.
    """
    global _PLUGINS_ENABLED
    _PLUGINS_ENABLED = toggle
    _invalidate_shared_enabled_cache()

    try:
        client = await _redis()
    except Exception as exc:
        _logger.warning("Failed to obtain Redis client for plugin toggle (%s) — change is local only", exc)
        return False
    if client is None:
        _logger.warning("Redis unavailable — plugin toggle change is local only")
        return False

    try:
        await client.set(_REDIS_PLUGINS_ENABLED_KEY, "true" if toggle else "false")
    except Exception as exc:
        _logger.warning("Failed to write plugin toggle to Redis (%s) — change is local only", exc)
        return False

    published = await _publish_invalidation({"type": "global_toggle", "enabled": toggle})
    if not published:
        # Partial write: SET persisted, broadcast didn't. Peers will converge
        # on the next cache-TTL read (a few seconds) rather than instantly —
        # surface this at ERROR so it reaches on-call, not just DEBUG logs.
        _logger.error("Plugin global toggle persisted to Redis but broadcast failed — peer workers will lag until next cache refresh")
    return True


async def _publish_invalidation(message: dict[str, Any]) -> bool:
    """Best-effort publish to the invalidation channel; logs but does not raise.

    Listeners also evict on their own TTL, so a publish miss only widens the
    propagation window — it does not corrupt state.
    """
    try:
        client = await _redis()
    except Exception as exc:
        _logger.warning("Plugin invalidation publish skipped — Redis client error (%s)", exc)
        return False
    if client is None:
        return False

    try:
        await client.publish(_REDIS_INVALIDATION_CHANNEL, json.dumps(message))
        return True
    except Exception as exc:
        _logger.warning("Plugin invalidation publish failed for %s (%s)", message.get("type"), exc)
        return False


def get_local_mode_overrides() -> dict[str, str]:
    """Return a snapshot of the in-process per-plugin mode override map.

    Prunes expired entries from the backing map before the snapshot so the
    dict doesn't leak an entry per plugin name ever overridden on workers
    that never otherwise trigger a prune.
    """
    now = time.monotonic()
    _state.prune_expired_local_overrides(now)
    return _state.active_local_mode_overrides(now)


async def publish_plugin_mode_change(plugin_name: str, mode: str) -> bool:
    """Persist a per-plugin mode override locally and attempt to broadcast it.

    Always updates the in-process override map so the change takes effect on
    this worker even when Redis is unavailable (single-node deployments).
    Returns True only when Redis accepted the write — the caller uses this
    signal to distinguish "cluster-wide" from "this worker only".

    When the Redis SET succeeds, the local entry carries an expiry aligned
    with the Redis 24 h TTL so both copies clear together. When the Redis
    SET fails, the local entry is durable (no expiry) because the operator
    never got confirmation that a timer had started.
    """
    try:
        client = await _redis()
    except Exception as exc:
        _logger.warning("Plugin mode Redis write skipped — client error (%s)", exc)
        _state.set_local_mode_override(plugin_name, mode, None)
        return False
    if client is None:
        _state.set_local_mode_override(plugin_name, mode, None)
        return False

    try:
        await client.set(f"plugin:{plugin_name}:mode", mode, ex=_PLUGIN_MODE_TTL_SECONDS)
    except Exception as exc:
        _logger.warning("Plugin mode Redis SET failed for %s (%s)", plugin_name, exc)
        _state.set_local_mode_override(plugin_name, mode, None)
        return False

    _state.set_local_mode_override(plugin_name, mode, time.monotonic() + _PLUGIN_MODE_TTL_SECONDS)
    # Peers use ttl_seconds to stamp their local copy with the same absolute
    # deadline — without it each worker would anchor expiry to its own
    # reception time and drift past the Redis key.
    published = await _publish_invalidation({"type": "mode_change", "plugin": plugin_name, "mode": mode, "ttl_seconds": _PLUGIN_MODE_TTL_SECONDS})
    if not published:
        _logger.error(
            "Plugin mode override persisted to Redis for %s but broadcast failed — peer workers will lag until next cache refresh",
            plugin_name,
        )
    return True


async def publish_binding_change(context_id: str) -> bool:
    """Broadcast a per-context binding change so remote workers evict the cached manager."""
    return await _publish_invalidation({"type": "binding_change", "context_id": context_id})


async def publish_team_binding_change(team_id: str) -> bool:
    """Broadcast a wildcard binding change — every worker evicts every cached context for the team."""
    return await _publish_invalidation({"type": "team_binding_change", "team_id": team_id})


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
        # First-Party
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
    """Return the context-scoped manager, reading the shared toggle so runtime enable/disable propagates."""
    if not await are_plugins_enabled_shared():
        return None
    if _plugin_manager_factory is None:
        _warn_factory_init_degraded_once()
        return None
    return await _plugin_manager_factory.get_manager(server_id)


def mark_factory_init_degraded() -> None:
    """Record that opportunistic factory init failed on this node.

    Called from ``main.py`` lifespan when ``plugins.enabled=false`` AND the
    factory-init probe raised. On its own this is not an error — the operator
    opted out of plugins locally. It becomes an error later if the shared
    toggle flips the subsystem on and this node cannot honour it; the first
    such ``get_plugin_manager`` call emits one ERROR.
    """
    _state.mark_factory_init_degraded()


def _reset_factory_init_degraded_for_tests() -> None:
    """Clear the degraded-boot flag so test isolation is clean."""
    _state._reset_factory_init_degraded_for_tests()  # pylint: disable=protected-access


def _warn_factory_init_degraded_once() -> None:
    """Emit one ERROR the first time a shared-toggle request hits a degraded node."""
    if not _state.is_factory_init_degraded() or _state.is_factory_init_degraded_logged():
        return
    _state.mark_factory_init_degraded_logged()
    _logger.error(
        "Plugin subsystem asked to serve plugins (shared toggle=true) but factory init failed during startup on this node; "
        "restart after fixing %s to participate. Until then, plugin hooks on this worker will no-op.",
        "settings.plugins.config_file",
    )


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
    """Tear the factory down whenever one exists.

    Must not gate on ``_PLUGINS_ENABLED``: an operator can runtime-disable plugins
    via ``PUT /admin/plugins {"enabled": false}`` and then stop the gateway. The
    factory and any in-flight build tasks still need cleanup even though the
    in-memory flag is ``False`` by the time lifespan teardown runs.
    """
    global _plugin_manager_factory  # pylint: disable=global-statement

    factory = _plugin_manager_factory
    _plugin_manager_factory = None
    if factory is not None:
        await factory.shutdown()


def reset_plugin_manager_factory() -> None:
    """Reset the global factory and all per-server managers (primarily for tests)."""
    global _plugin_manager_factory
    _plugin_manager_factory = None


def get_plugin_manager_factory() -> Optional[TenantPluginManagerFactory]:
    """Return the active factory without leaking the private module binding.

    Router code that needs to call ``invalidate_team`` / ``iter_context_ids``
    goes through this accessor instead of importing ``_plugin_manager_factory``
    so the factory can be swapped (tests, future per-request scoping) without
    hunting for every private import.
    """
    return _plugin_manager_factory


def list_configured_plugin_names() -> list[str]:
    """Return the plugin names from the loaded YAML config, regardless of runtime state.

    Admin validation (e.g. ``PUT /admin/plugins/{name}``) must not gate on the
    live manager: on a process that booted with plugins globally disabled the
    manager is never wired, so ``PluginService.get_all_plugins()`` returns
    ``[]`` and every valid plugin name 404s. The factory's ``_base_config``
    is populated at startup from ``PLUGINS_CONFIG_FILE`` even when the shared
    toggle is off, so it's the authoritative source for "names an operator
    may pre-stage an override for".
    """
    if _plugin_manager_factory is None:
        return []
    config = _plugin_manager_factory._base_config  # pylint: disable=protected-access
    if not config or not config.plugins:
        return []
    return [plugin.name for plugin in config.plugins]


async def get_plugin_mode_override(plugin_name: str) -> Optional[str]:
    """Return the per-plugin Redis mode override, or ``None`` when the key is unset.

    Raises on Redis transport errors so callers can distinguish "no override"
    from "Redis unreachable" instead of silently accepting the YAML default.

    Raises:
        RuntimeError: If the Redis client errors while fetching the override.
    """
    try:
        client = await _redis()
    except Exception as exc:
        raise RuntimeError(f"Redis client unavailable for plugin mode lookup: {exc}") from exc
    if client is None:
        return None
    try:
        val = await client.get(f"plugin:{plugin_name}:mode")
    except Exception as exc:
        raise RuntimeError(f"Redis GET failed for plugin {plugin_name}: {exc}") from exc
    if val is None:
        return None
    return val.decode() if isinstance(val, bytes) else str(val)


async def invalidate_all_plugin_managers() -> None:
    """Reload every cached plugin manager; delegates to the factory's public method."""
    factory = _plugin_manager_factory
    if factory is None:
        return
    await factory.invalidate_all()


async def reload_plugin_context(context_id: str) -> None:
    """Evict and rebuild the cached manager for ``context_id``.

    Eviction is safe when plugins are disabled — we only skip the work when
    the factory itself has not been initialised.
    """
    if _plugin_manager_factory is None:
        return
    await _plugin_manager_factory.reload_tenant(context_id)


async def _handle_invalidation_message(message: dict[str, Any]) -> None:
    """Dispatch one pub/sub frame to the matching invalidation handler.

    Args:
        message: Raw redis-py pub/sub frame with ``type`` and ``data`` keys.
    """
    if message.get("type") != "message":
        return  # subscribe/unsubscribe notifications — not an invalidation event

    try:
        data = json.loads(message["data"])
    except (ValueError, KeyError, TypeError) as exc:
        _logger.warning("Ignoring malformed plugin invalidation message (%s)", exc)
        return

    try:
        frame = _invalidation_adapter.validate_python(data)
    except _ValidationError as exc:
        _logger.warning("Ignoring unrecognised plugin invalidation frame %r (%s)", data, exc)
        return

    match frame:
        case _GlobalToggleMsg(enabled=enabled):
            global _PLUGINS_ENABLED
            _PLUGINS_ENABLED = enabled
            _invalidate_shared_enabled_cache()
            _logger.debug("Pub/sub: global toggle set to %s", _PLUGINS_ENABLED)

        case _ModeChangeMsg(plugin=plugin, mode=mode, ttl_seconds=ttl_seconds):
            # Mirror the broadcast into the local override map so this worker's
            # rebuild uses the new mode even if the Redis MGET on rebuild races
            # with the key's 24 h TTL. ``ttl_seconds`` arrives from the publisher
            # so every peer uses the same absolute deadline regardless of when
            # the broadcast lands locally.
            _state.set_local_mode_override(plugin, mode, time.monotonic() + ttl_seconds)
            await invalidate_all_plugin_managers()
            _logger.debug("Pub/sub: mode change for %s, all managers invalidated", plugin)

        case _TeamBindingChangeMsg(team_id=team_id) if _plugin_manager_factory is not None:
            try:
                await _plugin_manager_factory.invalidate_team(team_id)
                _logger.debug("Pub/sub: team_binding_change, invalidated team %s", team_id)
            except Exception as exc:
                _logger.warning("Pub/sub team_binding_change failed for %s (%s)", team_id, exc)

        case _BindingChangeMsg(context_id=context_id) if _plugin_manager_factory is not None:
            try:
                await _plugin_manager_factory.reload_tenant(context_id)
                _logger.debug("Pub/sub: binding change, reloaded context %s", context_id)
            except Exception as exc:
                _logger.warning("Pub/sub binding_change reload failed for %s (%s)", context_id, exc)


async def _plugin_invalidation_listener() -> None:
    """Subscribe to the invalidation channel and dispatch messages until cancelled.

    Reconnects on transport errors with exponential backoff plus jitter; the
    TTL-based cache refresh bounds staleness if this listener stays down.
    """
    backoff = 1.0
    max_backoff = 30.0
    consecutive_failures = 0

    while True:
        try:
            client = await _redis()
            if not client:
                _logger.debug("Plugin invalidation listener: Redis unavailable, retrying in 10s")
                await asyncio.sleep(10)
                continue

            pubsub = client.pubsub()
            await pubsub.subscribe(_REDIS_INVALIDATION_CHANNEL)
            _logger.info("Plugin invalidation listener subscribed to %s", _REDIS_INVALIDATION_CHANNEL)
            backoff = 1.0
            consecutive_failures = 0

            async for message in pubsub.listen():
                await _handle_invalidation_message(message)

        except asyncio.CancelledError:
            _logger.info("Plugin invalidation listener cancelled")
            break
        except Exception as exc:
            consecutive_failures += 1
            level = logging.ERROR if consecutive_failures >= 5 else logging.WARNING
            jitter = random.uniform(0, backoff / 2)  # nosec B311 - jitter for backoff, not cryptographic
            delay = min(max_backoff, backoff + jitter)
            _logger.log(
                level,
                "Plugin invalidation listener error (%s, failure #%d), reconnecting in %.1fs",
                exc,
                consecutive_failures,
                delay,
            )
            await asyncio.sleep(delay)
            backoff = min(max_backoff, backoff * 2)


async def start_plugin_invalidation_listener() -> None:
    """Start the pub/sub listener if a Redis provider is wired and the task is not already running.

    Single-node deployments without Redis would otherwise spin the listener's
    10-second retry loop indefinitely. Skip the task entirely in that case —
    operators can register a provider later and call this function again.
    Concurrent callers are serialized via ``_pubsub_start_lock`` so only one
    task is ever created.
    """
    global _pubsub_task
    async with _pubsub_start_lock:
        if _pubsub_task is not None and not _pubsub_task.done():
            return
        try:
            client = await _redis()
        except Exception as exc:  # noqa: BLE001 — probe failure; log and bail
            _logger.warning("Plugin invalidation listener probe failed (%s); listener not started", exc)
            return
        if client is None:
            _logger.info("Plugin invalidation listener not started — no Redis provider registered")
            return
        _pubsub_task = asyncio.create_task(_plugin_invalidation_listener())


async def stop_plugin_invalidation_listener() -> None:
    """Cancel the pub/sub listener and await its teardown."""
    global _pubsub_task
    task = _pubsub_task
    _pubsub_task = None
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


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
    "get_plugin_manager_factory",
    "get_plugin_mode_override",
    "list_configured_plugin_names",
    "invalidate_all_plugin_managers",
    "mark_factory_init_degraded",
    "get_local_mode_overrides",
    "publish_binding_change",
    "publish_plugin_mode_change",
    "publish_team_binding_change",
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
