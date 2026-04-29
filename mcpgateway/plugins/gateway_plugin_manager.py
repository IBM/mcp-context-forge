# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/gateway_plugin_manager.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhumohan Jaishankar

Gateway-specific subclass of TenantPluginManagerFactory.

Bridges the ToolPluginBinding DB table with the plugin framework by
implementing get_config_from_db() to translate stored bindings into
PluginConfigOverride objects the framework merges with base YAML config.

Also provides gateway-layer cache management:
- TTL-based cache with ``_CachedManager`` wrappers
- Per-plugin Redis mode overrides via ``_apply_redis_mode_overrides``
- ``invalidate_all`` / ``invalidate_team`` for cross-worker propagation

Context ID convention: ``"<team_id>::<tool_name>"``
"""

# Standard
import asyncio
import logging
import time
from typing import Any, Callable, Optional

# Third-Party
from pydantic import ValidationError
from sqlalchemy.orm import Session

# First-Party
from cpex.framework import PluginConfigOverride, PluginMode, TenantPluginManager, TenantPluginManagerFactory
from mcpgateway.plugins._redis import get_shared_redis_client as _redis
from mcpgateway.plugins._state import active_local_mode_overrides, prune_expired_local_overrides
from mcpgateway.services.tool_plugin_binding_service import get_bindings_for_tool

logger = logging.getLogger(__name__)

CONTEXT_ID_SEPARATOR = "::"

_BINDING_MODE_TO_PLUGIN_MODE: dict[str, PluginMode] = {
    "enforce": PluginMode.SEQUENTIAL,
    "permissive": PluginMode.AUDIT,
    "disabled": PluginMode.DISABLED,
}

_GATEWAY_MODE_TO_PLUGIN_MODE: dict[str, PluginMode] = {
    "enforce": PluginMode.SEQUENTIAL,
    "enforce_ignore_error": PluginMode.AUDIT,
    "permissive": PluginMode.AUDIT,
    "disabled": PluginMode.DISABLED,
}


class _CachedManager:
    """A cached tenant manager paired with the monotonic timestamp of its build."""

    __slots__ = ("manager", "created_at")

    def __init__(self, manager: TenantPluginManager, created_at: float) -> None:
        self.manager = manager
        self.created_at = created_at

    def is_expired(self, ttl: float) -> bool:
        return ttl > 0 and (time.monotonic() - self.created_at) > ttl


class GatewayTenantPluginManagerFactory(TenantPluginManagerFactory):
    """TenantPluginManagerFactory wired to the gateway's ToolPluginBinding table.

    Context IDs must follow the ``"<team_id>::<tool_name>"`` convention.
    Call sites should use :func:`make_context_id` to construct them.

    When ``get_config_from_db`` is invoked for a context:

    * Wildcard bindings (``tool_name == "*"``) provide team-wide defaults.
    * Exact ``tool_name`` bindings override wildcards for the same plugin_id
      (last-write-wins by ``updated_at``).
    * The ``plugin_id`` column stores the plugin class name directly
      (e.g. ``"OutputLengthGuardPlugin"``); unknown names are passed through
      to the framework, which is responsible for ignoring unrecognised plugins.
    * Returns ``None`` (not an empty list) when no bindings are found so the
      framework falls back to the unmodified base YAML config.
    """

    DEFAULT_CACHE_TTL = 30
    CONTEXT_ID_SEPARATOR = CONTEXT_ID_SEPARATOR

    def __init__(self, *args: object, db_factory: Callable[[], Session], cache_ttl: Optional[int] = None, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._db_factory = db_factory
        self._cache_ttl = cache_ttl if cache_ttl is not None else self.DEFAULT_CACHE_TTL

    async def get_manager(self, context_id: Optional[str] = None) -> TenantPluginManager:
        context_id = context_id or "__global__"

        async with self._lock:
            entry = self._managers.get(context_id)
            if entry is not None:
                if isinstance(entry, _CachedManager) and entry.is_expired(self._cache_ttl):
                    self._managers.pop(context_id, None)
                    logger.debug("Cache TTL expired for context_id=%s, rebuilding", context_id)
                else:
                    return entry.manager if isinstance(entry, _CachedManager) else entry

            inflight = self._inflight.get(context_id)
            if inflight is None:
                inflight = asyncio.create_task(self._build_manager(context_id))
                self._inflight[context_id] = inflight

        try:
            manager = await inflight
            async with self._lock:
                entry = self._managers.get(context_id)
                if entry is not None:
                    return entry.manager if isinstance(entry, _CachedManager) else entry
                return manager
        finally:
            async with self._lock:
                if self._inflight.get(context_id) is inflight:
                    self._inflight.pop(context_id, None)

    async def _build_manager(self, context_id: str) -> TenantPluginManager:
        manager = None
        try:
            new_config = await self.get_config_from_db(context_id)
            config = self._merge_tenant_config(new_config)
            config = await self._apply_redis_mode_overrides(config)

            manager = TenantPluginManager(
                config=config,
                timeout=self._timeout,
                observability=self._observability,
                hook_policies=self._hook_policies,
            )
            await manager.initialize()

            async with self._lock:
                old_entry = self._managers.get(context_id)
                self._managers[context_id] = _CachedManager(manager=manager, created_at=time.monotonic())

            old = old_entry.manager if isinstance(old_entry, _CachedManager) else old_entry
            if old is not None and old is not manager:
                try:
                    await old.shutdown()
                except Exception:
                    logger.warning("Failed to shutdown old manager for context_id=%s", context_id)

            return manager

        except asyncio.CancelledError:
            if manager is not None:
                try:
                    await manager.shutdown()
                except Exception:
                    logger.warning("Failed to shutdown cancelled manager for context_id=%s", context_id)
            raise
        except Exception:
            if manager is not None:
                try:
                    await manager.shutdown()
                except Exception:
                    logger.warning("Failed to shutdown manager after error for context_id=%s", context_id)
            raise

    async def _apply_redis_mode_overrides(self, config: Any) -> Any:
        """Apply per-plugin mode overrides. Redis is authoritative; the in-process map is the fallback."""
        if not config.plugins:
            return config

        now = time.monotonic()
        prune_expired_local_overrides(now)
        local_overrides = active_local_mode_overrides(now)

        redis_values: list[Optional[Any]] = [None] * len(config.plugins)
        try:
            client = await _redis()
        except Exception as exc:
            logger.warning("Redis mode overrides skipped — client error (%s)", exc, exc_info=True)
            client = None

        if client is not None:
            keys = [f"plugin:{p.name}:mode" for p in config.plugins]
            try:
                redis_values = list(await client.mget(keys))
            except Exception as exc:
                logger.warning("Redis MGET for plugin modes failed (%s)", exc, exc_info=True)
                redis_values = [None] * len(config.plugins)

        modified = False
        updated_plugins = []
        for plugin, redis_raw in zip(config.plugins, redis_values):
            candidates: list[tuple[str, str]] = []
            if redis_raw is not None:
                redis_str = redis_raw.decode() if isinstance(redis_raw, bytes) else str(redis_raw)
                candidates.append(("redis", redis_str))
            if plugin.name in local_overrides:
                candidates.append(("local", local_overrides[plugin.name]))

            applied = False
            for source, mode_str in candidates:
                mode = _GATEWAY_MODE_TO_PLUGIN_MODE.get(mode_str)
                if mode is None:
                    try:
                        mode = PluginMode(mode_str)
                    except ValueError:
                        logger.warning("Ignoring invalid %s mode override %r for plugin %s — value not in PluginMode", source, mode_str, plugin.name)
                        continue
                try:
                    updated_plugins.append(plugin.model_copy(update={"mode": mode}))
                    modified = True
                    applied = True
                    break
                except ValidationError as exc:
                    logger.warning("Ignoring %s mode override for plugin %s — validation failed (%s)", source, plugin.name, exc)

            if not applied:
                updated_plugins.append(plugin)

        if modified:
            return config.model_copy(update={"plugins": updated_plugins}, deep=True)
        return config

    async def invalidate_all(self) -> None:
        """Reload every cached manager, logging failures instead of aborting the sweep."""
        async with self._lock:
            context_ids = list(self._managers.keys())
        for ctx_id in context_ids:
            try:
                await self.reload_tenant(ctx_id)
            except Exception as exc:
                logger.warning("invalidate_all: reload failed for context_id=%s (%s)", ctx_id, exc)

    async def invalidate_team(self, team_id: str, separator: Optional[str] = None) -> None:
        """Reload every cached manager whose context_id starts with team_id plus separator."""
        sep = separator if separator is not None else self.CONTEXT_ID_SEPARATOR
        prefix = f"{team_id}{sep}"
        async with self._lock:
            context_ids = [cid for cid in self._managers if cid.startswith(prefix)]
        for ctx_id in context_ids:
            try:
                await self.reload_tenant(ctx_id)
            except Exception as exc:
                logger.warning("invalidate_team: reload failed for context_id=%s (%s)", ctx_id, exc)

    def iter_context_ids(self) -> list[str]:
        """Return a snapshot of the cached context IDs."""
        return list(self._managers.keys())

    async def get_config_from_db(self, context_id: str) -> Optional[list[PluginConfigOverride]]:
        """Fetch per-tool plugin overrides from the DB for *context_id*.

        Args:
            context_id: Must be ``"<team_id>::<tool_name>"``.  Any other
                format is treated as having no overrides (returns ``None``).

        Returns:
            List of :class:`~cpex.framework.PluginConfigOverride`
            for this tool, or ``None`` if no bindings exist.
        """
        if CONTEXT_ID_SEPARATOR not in context_id:
            logger.debug("get_config_from_db: unrecognised context_id format %r, skipping", context_id)
            return None

        team_id, tool_name = context_id.split(CONTEXT_ID_SEPARATOR, 1)

        try:
            db: Session = self._db_factory()
            try:
                bindings = get_bindings_for_tool(db, team_id, tool_name)
            finally:
                db.close()
        except Exception:
            logger.error(
                "get_config_from_db: DB error for context_id=%s — failing rebuild to avoid dropping bindings",
                context_id,
                exc_info=True,
            )
            raise

        if not bindings:
            logger.debug("get_config_from_db: no bindings found for context_id=%s", context_id)
            return None

        overrides: list[PluginConfigOverride] = []
        for binding in bindings:
            plugin_name = binding.plugin_id
            mode: Optional[PluginMode] = _BINDING_MODE_TO_PLUGIN_MODE.get(binding.mode) if binding.mode else None
            overrides.append(
                PluginConfigOverride(
                    name=plugin_name,
                    config=binding.config or {},
                    mode=mode,
                    priority=binding.priority,
                )
            )

        return overrides if overrides else None


def make_context_id(team_id: str, tool_name: str) -> str:
    """Build the context_id string expected by GatewayTenantPluginManagerFactory.

    Args:
        team_id: Team identifier.
        tool_name: Tool name (use ``"*"`` for team-wide wildcard lookups).

    Returns:
        str: ``"<team_id>CONTEXT_ID_SEPARATOR<tool_name>"``
    """
    return f"{team_id}{CONTEXT_ID_SEPARATOR}{tool_name}"
