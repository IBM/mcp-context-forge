# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/__init__.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Gateway plugin integration.

Provides the global plugin manager factory singleton that wires the
cpex ``TenantPluginManagerFactory`` to gateway-specific hook payload
policies defined in ``mcpgateway.plugins.policy``.

Also provides cross-worker/cross-pod runtime management via Redis
pub/sub for plugin enable/disable and per-plugin mode changes.
"""

# Standard
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import random
import time
from typing import TYPE_CHECKING, Any, Callable, Literal, Optional, Union

# Third-Party
from cpex.framework import ObservabilityProvider, TenantPluginManager
from pydantic import BaseModel, TypeAdapter
from pydantic import ValidationError as _ValidationError

# First-Party
from mcpgateway.plugins import _state
from mcpgateway.plugins._redis import get_shared_redis_client as _redis

if TYPE_CHECKING:
    from mcpgateway.plugins.gateway_plugin_manager import TenantPluginManagerFactory

# --- Global plugin manager factory singleton ---
_PLUGINS_ENABLED = False
_plugin_manager_factory: Optional[TenantPluginManagerFactory] = None
_observability_service: Optional[ObservabilityProvider] = None
DEFAULT_SERVER_ID = "__global__"

_REDIS_PLUGINS_ENABLED_KEY = "plugin:global:enabled"
_REDIS_INVALIDATION_CHANNEL = "plugin:invalidation"
_PLUGIN_MODE_TTL_SECONDS = 86400
_pubsub_task: Optional["asyncio.Task[None]"] = None
_pubsub_start_lock = asyncio.Lock()

_SHARED_ENABLED_CACHE_TTL = 2.0
_shared_enabled_cache: Optional[tuple[bool, float]] = None
_shared_enabled_cache_lock = asyncio.Lock()

_logger = logging.getLogger(__name__)


class _GlobalToggleMsg(BaseModel):
    """Redis pub/sub payload for a global plugin enable/disable toggle."""

    type: Literal["global_toggle"]
    enabled: bool


class _ModeChangeMsg(BaseModel):
    """Redis pub/sub payload for a per-plugin mode override."""

    type: Literal["mode_change"]
    plugin: str
    mode: Literal[
        "enforce",
        "enforce_ignore_error",
        "permissive",
        "disabled",
        "sequential",
        "concurrent",
        "transform",
        "audit",
        "fire_and_forget",
    ]
    ttl_seconds: int = _PLUGIN_MODE_TTL_SECONDS


class _BindingChangeMsg(BaseModel):
    """Redis pub/sub payload for a per-context binding change."""

    type: Literal["binding_change"]
    context_id: str


class _TeamBindingChangeMsg(BaseModel):
    """Redis pub/sub payload for a team-level binding change."""

    type: Literal["team_binding_change"]
    team_id: str


_InvalidationMsg = Union[_GlobalToggleMsg, _ModeChangeMsg, _BindingChangeMsg, _TeamBindingChangeMsg]
_invalidation_adapter: TypeAdapter[_InvalidationMsg] = TypeAdapter(_InvalidationMsg)


def _get_invalidation_hmac_key() -> Optional[bytes]:
    """Return the HMAC signing key for pub/sub messages, or None if unconfigured."""
    from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel
    from pydantic import SecretStr  # pylint: disable=import-outside-toplevel

    secret = settings.jwt_secret_key
    if not secret:
        return None
    raw = secret.get_secret_value() if isinstance(secret, SecretStr) else str(secret)
    if not raw:
        return None
    return raw.encode()


def _sign_message(payload: str) -> str:
    """Wrap a JSON payload with an HMAC signature envelope."""
    key = _get_invalidation_hmac_key()
    if key is None:
        return payload
    sig = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return json.dumps({"payload": payload, "sig": sig})


def _verify_and_extract(raw: str) -> Optional[str]:
    """Verify HMAC and return the inner payload, or None on failure.

    Accepts both signed (envelope with sig+payload) and unsigned (plain JSON)
    messages for rolling-deploy compatibility. Unsigned messages are accepted
    with a warning when HMAC is configured.
    """
    key = _get_invalidation_hmac_key()

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        _logger.warning("Plugin invalidation: message is not valid JSON, dropping")
        return None

    if isinstance(parsed, dict) and "sig" in parsed and "payload" in parsed:
        if key is None:
            return parsed["payload"]
        expected = hmac.new(key, parsed["payload"].encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, parsed["sig"]):
            _logger.error("Plugin invalidation: HMAC verification FAILED — possible spoofed message, dropping")
            return None
        return parsed["payload"]

    # Plain unsigned message (no envelope) — accept for backward compatibility
    if key is not None:
        _logger.warning("Plugin invalidation: received unsigned message while HMAC is configured — expected only during rolling deploy")
    return raw


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
        now = asyncio.get_running_loop().time()
        if cache is not None and (now - cache[1]) < _SHARED_ENABLED_CACHE_TTL:
            return cache[0]

        value = await _read_shared_enabled()
        _shared_enabled_cache = (value, now)
        return value


def _invalidate_shared_enabled_cache() -> None:
    """Clear the in-memory shared-enabled cache so the next read hits Redis."""
    global _shared_enabled_cache
    _shared_enabled_cache = None


def enable_plugins(toggle: bool) -> None:
    """Toggle the in-memory flag. Use ``enable_plugins_shared`` for cross-worker reach."""
    global _PLUGINS_ENABLED
    _PLUGINS_ENABLED = toggle
    _invalidate_shared_enabled_cache()


async def enable_plugins_shared(toggle: bool) -> bool:
    """Persist the global toggle to Redis and broadcast the change.

    Returns True when Redis accepted the write.
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
        _logger.error("Plugin global toggle persisted to Redis but broadcast failed — peer workers will lag until next cache refresh")
    return True


async def _publish_invalidation(message: dict[str, Any]) -> bool:
    """Broadcast a plugin invalidation message over Redis pub/sub."""
    try:
        client = await _redis()
    except Exception as exc:
        _logger.warning("Plugin invalidation publish skipped — Redis client error (%s)", exc)
        return False
    if client is None:
        return False

    try:
        payload = json.dumps(message)
        signed = _sign_message(payload)
        await client.publish(_REDIS_INVALIDATION_CHANNEL, signed)
        return True
    except Exception as exc:
        _logger.warning("Plugin invalidation publish failed for %s (%s)", message.get("type"), exc)
        return False


def get_local_mode_overrides() -> dict[str, str]:
    """Return a snapshot of the in-process per-plugin mode override map."""
    now = time.monotonic()
    _state.prune_expired_local_overrides(now)
    return _state.active_local_mode_overrides(now)


async def publish_plugin_mode_change(plugin_name: str, mode: str) -> bool:
    """Persist a per-plugin mode override locally and attempt to broadcast it."""
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
    published = await _publish_invalidation({"type": "mode_change", "plugin": plugin_name, "mode": mode, "ttl_seconds": _PLUGIN_MODE_TTL_SECONDS})
    if not published:
        _logger.error("Plugin mode override persisted to Redis for %s but broadcast failed — peer workers will lag until next cache refresh", plugin_name)
    return True


async def publish_binding_change(context_id: str) -> bool:
    """Broadcast a per-context binding change so remote workers evict the cached manager."""
    return await _publish_invalidation({"type": "binding_change", "context_id": context_id})


async def publish_team_binding_change(team_id: str) -> bool:
    """Broadcast a wildcard binding change — every worker evicts every cached context for the team."""
    return await _publish_invalidation({"type": "team_binding_change", "team_id": team_id})


def init_plugin_manager_factory(
    yaml_path: str,
    timeout: int,
    hook_policies: dict,
    observability: Optional[ObservabilityProvider] = None,
    db_factory: Optional[Callable] = None,
) -> None:
    """Explicitly initialise the global plugin manager factory."""
    global _plugin_manager_factory
    global _observability_service
    _observability_service = observability
    # First-Party
    from mcpgateway.plugins.gateway_plugin_manager import TenantPluginManagerFactory  # pylint: disable=import-outside-toplevel

    _plugin_manager_factory = TenantPluginManagerFactory(
        yaml_path=yaml_path,
        timeout=timeout,
        hook_policies=hook_policies,
        observability=observability,
        db_factory=db_factory,
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
    """Record that opportunistic factory init failed on this node."""
    _state.mark_factory_init_degraded()


def _reset_factory_init_degraded_for_tests() -> None:
    """Reset the degraded-init flag (test-only helper)."""
    _state._reset_factory_init_degraded_for_tests()  # pylint: disable=protected-access


def _warn_factory_init_degraded_once() -> None:
    """Log a one-shot error when plugins are requested but factory init failed."""
    if not _state.is_factory_init_degraded() or _state.is_factory_init_degraded_logged():
        return
    _state.mark_factory_init_degraded_logged()
    _logger.error(
        "Plugin subsystem asked to serve plugins (shared toggle=true) but factory init failed during startup on this node; "
        "restart after fixing %s to participate. Until then, plugin hooks on this worker will no-op.",
        "settings.plugins.config_file",
    )


def set_global_observability(observability: ObservabilityProvider) -> None:
    """Set the global observability provider and propagate it to the active factory."""
    global _observability_service
    _observability_service = observability
    if _plugin_manager_factory is not None:
        _plugin_manager_factory.observability = observability


async def shutdown_plugin_manager_factory() -> None:
    """Tear the factory down whenever one exists.

    Must not gate on ``_PLUGINS_ENABLED``: an operator can runtime-disable plugins
    and then stop the gateway — the factory still needs cleanup.
    """
    global _plugin_manager_factory

    factory = _plugin_manager_factory
    _plugin_manager_factory = None
    if factory is not None:
        await factory.shutdown()


def reset_plugin_manager_factory() -> None:
    """Reset the global factory and all per-server managers (primarily for tests)."""
    global _plugin_manager_factory
    _plugin_manager_factory = None


def get_plugin_manager_factory() -> Optional[TenantPluginManagerFactory]:
    """Return the active factory without leaking the private module binding."""
    return _plugin_manager_factory


def list_configured_plugin_names() -> list[str]:
    """Return the plugin names from the loaded YAML config, regardless of runtime state."""
    if _plugin_manager_factory is None:
        return []
    return _plugin_manager_factory.plugin_names


async def get_plugin_mode_override(plugin_name: str) -> Optional[str]:
    """Return the per-plugin Redis mode override, or ``None`` when the key is unset."""
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
    """Evict and rebuild the cached manager for ``context_id``."""
    if _plugin_manager_factory is None:
        return
    await _plugin_manager_factory.reload_tenant(context_id)


async def _handle_invalidation_message(message: dict[str, Any]) -> None:
    """Dispatch a single Redis pub/sub invalidation message to the appropriate handler."""
    if message.get("type") != "message":
        return

    raw_data = message.get("data")
    if raw_data is None:
        _logger.warning("Ignoring plugin invalidation message with missing data")
        return

    raw_str = raw_data.decode() if isinstance(raw_data, bytes) else str(raw_data)
    verified_payload = _verify_and_extract(raw_str)
    if verified_payload is None:
        return

    try:
        data = json.loads(verified_payload)
    except (ValueError, TypeError) as exc:
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
            _logger.warning("Pub/sub: global plugin toggle changed to %s", _PLUGINS_ENABLED)

        case _ModeChangeMsg(plugin=plugin, mode=mode, ttl_seconds=ttl_seconds):
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

        case _:
            _logger.debug("Pub/sub: invalidation message dropped (factory not initialized): %r", frame)


async def _plugin_invalidation_listener() -> None:
    """Long-running task that subscribes to the Redis invalidation channel."""
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
    """Start the pub/sub listener if a Redis provider is wired and the task is not already running."""
    global _pubsub_task
    async with _pubsub_start_lock:
        if _pubsub_task is not None and not _pubsub_task.done():
            return
        try:
            client = await _redis()
        except Exception as exc:  # noqa: BLE001
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
