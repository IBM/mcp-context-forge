# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/gateway_plugin_manager.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Gateway-owned TenantPluginManagerFactory and PluginConfigOverride.

cpex's TenantPluginManagerFactory is no longer imported or subclassed.
This module provides a standalone factory that uses cpex's
TenantPluginManager for actual plugin execution while adding
gateway-specific features:
- TTL-based cache with ``_CachedManager`` wrappers
- Per-plugin Redis mode overrides via ``_apply_redis_mode_overrides``
- ``invalidate_all`` / ``invalidate_team`` for cross-worker propagation
- CF-owned ``PluginConfigOverride`` with ``on_error`` field
- Optional DB wiring for per-tool plugin bindings

Context ID convention: ``"<team_id>::<tool_name>"``

Tools of one team that have no tool-specific ``ToolPluginBinding`` rows resolve
to the same configuration. They share one manager cached under
``"<team_id>::*"``. ``*`` cannot be a tool name, so the shared key never
collides with a real tool. ``_aliases`` maps each such ``context_id`` to the
shared key. Tools with tool-specific rows keep their own slot.
"""

# Standard
import asyncio
import logging
import time
from typing import Any, Callable, Optional

# Third-Party
from cpex.framework import ConfigLoader, HookPayloadPolicy, ObservabilityProvider, OnError, PluginMode, TenantPluginManager
from cpex.framework.models import Config
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.plugins._redis import get_shared_redis_client as _redis
from mcpgateway.plugins._state import active_local_mode_overrides, prune_expired_local_overrides
from mcpgateway.plugins.metadata import enrich_config_plugin_metadata
from mcpgateway.services.tool_plugin_binding_service import get_bindings_for_tool

logger = logging.getLogger(__name__)

CONTEXT_ID_SEPARATOR = "::"
SHARED_TOOL_KEY = "*"

_LEGACY_MODE_TO_PLUGIN_MODE: dict[str, tuple[PluginMode, Optional[OnError]]] = {
    "enforce": (PluginMode.SEQUENTIAL, None),
    "enforce_ignore_error": (PluginMode.SEQUENTIAL, OnError.IGNORE),
    "permissive": (PluginMode.TRANSFORM, None),
    "disabled": (PluginMode.DISABLED, None),
}


class PluginConfigOverride(BaseModel):
    """CF-owned plugin configuration override with on_error support."""

    name: str
    config: Optional[dict[str, Any]] = None
    mode: Optional[PluginMode] = None
    on_error: Optional[OnError] = None
    priority: Optional[int] = None


class _CachedManager:
    """A cached tenant manager paired with the monotonic timestamp of its build."""

    __slots__ = ("manager", "created_at")

    def __init__(self, manager: TenantPluginManager, created_at: float) -> None:
        self.manager = manager
        self.created_at = created_at

    @staticmethod
    def expired(created_at: float, ttl: float) -> bool:
        """Return True when ``ttl > 0`` and *created_at* is older than ``ttl`` seconds."""
        return ttl > 0 and (time.monotonic() - created_at) > ttl

    def is_expired(self, ttl: float) -> bool:
        """Return True when ``ttl > 0`` and the entry is older than ``ttl`` seconds."""
        return self.expired(self.created_at, ttl)


class TenantPluginManagerFactory:
    """Standalone factory for context-scoped TenantPluginManager instances.

    TTL caching, Redis mode overrides, invalidate_all/invalidate_team,
    on_error support, and optional DB wiring for per-tool plugin bindings.

    When *db_factory* is provided, ``get_config_from_db`` reads
    ``ToolPluginBinding`` rows for the context.  Without it the method
    returns ``None`` and the base YAML config is used as-is.

    Context IDs must follow the ``"<team_id>::<tool_name>"`` convention.
    Call sites should use :func:`make_context_id` to construct them.
    """

    DEFAULT_CACHE_TTL = 300  # seconds; bounds staleness when an invalidation message is missed
    CONTEXT_ID_SEPARATOR = CONTEXT_ID_SEPARATOR

    def __init__(
        self,
        yaml_path: str,
        timeout: int = 30,
        observability: Optional[ObservabilityProvider] = None,
        hook_policies: Optional[dict[str, HookPayloadPolicy]] = None,
        cache_ttl: Optional[int] = None,
        db_factory: Optional[Callable[[], Session]] = None,
    ):
        """Initialise the factory, loading base config from *yaml_path*."""
        self._base_config: Config = enrich_config_plugin_metadata(ConfigLoader.load_config(yaml_path))
        self._timeout = timeout
        self._observability = observability
        self._hook_policies = hook_policies
        self._managers: dict[str, _CachedManager] = {}
        self._inflight: dict[str, asyncio.Task[TenantPluginManager]] = {}
        self._aliases: dict[str, tuple[str, float]] = {}  # context_id -> (shared cache key, alias created_at)
        self._lock = asyncio.Lock()
        self._cache_ttl = cache_ttl if cache_ttl is not None else self.DEFAULT_CACHE_TTL
        self._db_factory = db_factory

    @property
    def observability(self) -> Optional[ObservabilityProvider]:
        """Get the current observability provider."""
        return self._observability

    @observability.setter
    def observability(self, value: Optional[ObservabilityProvider]) -> None:
        """Set or replace the observability provider."""
        self._observability = value

    @property
    def plugin_names(self) -> list[str]:
        """Return the plugin names from the loaded base YAML config."""
        if not self._base_config or not self._base_config.plugins:
            return []
        return [plugin.name for plugin in self._base_config.plugins]

    def _cached_manager(self, context_id: str) -> Optional[TenantPluginManager]:
        """Return the live cached manager for *context_id*, directly or through its alias."""
        entry = self._managers.get(context_id)
        if entry is not None and not entry.is_expired(self._cache_ttl):
            return entry.manager
        alias = self._aliases.get(context_id)
        if alias is not None:
            shared_key, aliased_at = alias
            shared = self._managers.get(shared_key)
            if shared is not None and not shared.is_expired(self._cache_ttl) and not _CachedManager.expired(aliased_at, self._cache_ttl):
                return shared.manager
        return None

    async def get_manager(self, context_id: Optional[str] = None) -> TenantPluginManager:
        """Get or create a TenantPluginManager for the given context."""
        context_id = context_id or "__global__"

        cached = self._cached_manager(context_id)
        if cached is not None:
            return cached

        async with self._lock:
            cached = self._cached_manager(context_id)
            if cached is not None:
                return cached

            entry = self._managers.get(context_id)
            if entry is not None and entry.is_expired(self._cache_ttl):
                expired = self._managers.pop(context_id)
                logger.debug("Cache TTL expired for context_id=%s, rebuilding", context_id)
                try:
                    await expired.manager.shutdown()
                except Exception:
                    logger.warning("Failed to shutdown expired manager for context_id=%s", context_id, exc_info=True)

            inflight = self._inflight.get(context_id)
            if inflight is None:
                inflight = asyncio.create_task(self._build_manager(context_id))
                self._inflight[context_id] = inflight

        try:
            manager = await inflight
            async with self._lock:
                entry = self._managers.get(context_id)
                if entry is not None:
                    return entry.manager
                return manager
        finally:
            async with self._lock:
                if self._inflight.get(context_id) is inflight:
                    self._inflight.pop(context_id, None)

    @staticmethod
    def _resolve_cache_key(context_id: str, bindings: list[Any]) -> str:
        """Return the cache key for *context_id* given its resolved bindings.

        A tool without tool-specific rows (wildcard rows only, or none) uses
        the team's shared key. Any other context keeps its own key.
        """
        if CONTEXT_ID_SEPARATOR not in context_id:
            return context_id
        team_id, tool_name = context_id.split(CONTEXT_ID_SEPARATOR, 1)
        if any(b.tool_name == tool_name for b in bindings):
            return context_id
        return f"{team_id}{CONTEXT_ID_SEPARATOR}{SHARED_TOOL_KEY}"

    async def _build_manager(self, context_id: str) -> TenantPluginManager:
        """Create, initialise, and cache a new manager for *context_id*.

        When *context_id* resolves to the team's shared key and a live manager
        already holds that key, the existing manager is reused. After the slow
        ``initialize()``, the key is checked again so that a concurrent build
        never replaces a manager that another request already received.
        """
        manager = None
        try:
            bindings = await self._fetch_bindings(context_id)
            cache_key = self._resolve_cache_key(context_id, bindings)
            shares_slot = cache_key != context_id

            if shares_slot:
                async with self._lock:
                    existing = self._managers.get(cache_key)
                    if existing is not None and not existing.is_expired(self._cache_ttl):
                        self._aliases[context_id] = (cache_key, time.monotonic())
                        return existing.manager

            config = self._merge_tenant_config(self._bindings_to_overrides(bindings))
            config = await self._apply_redis_mode_overrides(config)

            manager = TenantPluginManager(
                config=config,
                timeout=self._timeout,
                observability=self._observability,
                hook_policies=self._hook_policies,
            )
            await manager.initialize()

            async with self._lock:
                existing = self._managers.get(cache_key)
                if shares_slot:
                    self._aliases[context_id] = (cache_key, time.monotonic())
                if shares_slot and existing is not None and not existing.is_expired(self._cache_ttl):
                    winner, discarded = existing.manager, manager
                else:
                    self._managers[cache_key] = _CachedManager(manager=manager, created_at=time.monotonic())
                    winner, discarded = manager, existing.manager if existing is not None else None
            manager = None

            if discarded is not None and discarded is not winner:
                try:
                    await discarded.shutdown()
                except Exception:
                    logger.warning("Failed to shutdown superseded manager for context_id=%s", cache_key, exc_info=True)

            return winner

        except asyncio.CancelledError:
            if manager is not None:
                try:
                    await manager.shutdown()
                except Exception:
                    logger.warning("Failed to shutdown cancelled manager for context_id=%s", context_id, exc_info=True)
            raise
        except Exception:
            logger.error("Manager build failed for context_id=%s", context_id, exc_info=True)
            if manager is not None:
                try:
                    await manager.shutdown()
                except Exception:
                    logger.warning("Failed to shutdown manager after error for context_id=%s", context_id, exc_info=True)
            raise

    def _merge_tenant_config(self, tenant_cfg_override: Optional[list[PluginConfigOverride]]) -> Config:
        """Overlay per-tenant plugin overrides onto the base YAML config."""
        if tenant_cfg_override is None:
            return self._base_config

        override_map = {p.name: p for p in tenant_cfg_override}
        if not any(p.name in override_map for p in self._base_config.plugins or []):
            return self._base_config

        merged_plugins = []

        for plugin in self._base_config.plugins or []:
            override = override_map.get(plugin.name)
            if not override:
                merged_plugins.append(plugin)
                continue
            merged_config = {**(plugin.config or {}), **(override.config or {})}
            update: dict[str, Any] = {
                "config": merged_config,
                "mode": override.mode if override.mode is not None else plugin.mode,
                "priority": override.priority if override.priority is not None else plugin.priority,
            }
            if override.on_error is not None:
                update["on_error"] = override.on_error
            merged_plugins.append(plugin.model_copy(update=update))

        return self._base_config.model_copy(update={"plugins": merged_plugins}, deep=True)

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
                mapping = _LEGACY_MODE_TO_PLUGIN_MODE.get(mode_str)
                if mapping is not None:
                    mode, on_error = mapping
                else:
                    try:
                        mode = PluginMode(mode_str)
                        on_error = None
                    except ValueError:
                        logger.warning("Ignoring invalid %s mode override %r for plugin %s — value not in PluginMode", source, mode_str, plugin.name)
                        continue
                try:
                    update: dict[str, Any] = {"mode": mode}
                    if on_error is not None:
                        update["on_error"] = on_error
                    updated_plugins.append(plugin.model_copy(update=update))
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

    async def reload_tenant(self, context_id: str) -> TenantPluginManager:
        """Evict and rebuild the cached manager for *context_id*."""
        async with self._lock:
            old_entry = self._managers.pop(context_id, None)
            self._aliases.pop(context_id, None)

            inflight = self._inflight.get(context_id)
            if inflight is not None:
                inflight.cancel()
                self._inflight.pop(context_id, None)

            inflight = asyncio.create_task(self._build_manager(context_id))
            self._inflight[context_id] = inflight

        old = old_entry.manager if old_entry is not None else None
        if old is not None:
            try:
                await old.shutdown()
            except Exception:
                logger.exception("Failed to shutdown old manager for context_id=%s", context_id)

        try:
            return await inflight
        finally:
            async with self._lock:
                if self._inflight.get(context_id) is inflight:
                    self._inflight.pop(context_id, None)

    async def shutdown(self) -> None:
        """Shut down all cached managers and cancel in-flight build tasks."""
        async with self._lock:
            entries = list(self._managers.values())
            inflight = list(self._inflight.values())
            self._managers.clear()
            self._aliases.clear()
            self._inflight.clear()

        for task in inflight:
            task.cancel()

        if inflight:
            await asyncio.gather(*inflight, return_exceptions=True)

        for entry in entries:
            try:
                await entry.manager.shutdown()
            except Exception:
                logger.exception("Failed to shutdown plugin manager")

    async def _fetch_bindings(self, context_id: str) -> list[Any]:
        """Return the ``ToolPluginBinding`` rows that apply to *context_id*.

        Returns an empty list when no *db_factory* is configured or the
        context ID has no ``"<team_id>::<tool_name>"`` shape.
        """
        if self._db_factory is None:
            return []

        if CONTEXT_ID_SEPARATOR not in context_id:
            logger.debug("get_config_from_db: unrecognised context_id format %r, skipping", context_id)
            return []

        team_id, tool_name = context_id.split(CONTEXT_ID_SEPARATOR, 1)

        try:
            db: Session = self._db_factory()
            try:
                return list(get_bindings_for_tool(db, team_id, tool_name))
            finally:
                db.close()
        except Exception:
            logger.error(
                "get_config_from_db: DB error for context_id=%s — failing rebuild to avoid dropping bindings",
                context_id,
                exc_info=True,
            )
            raise

    async def get_config_from_db(self, context_id: str) -> Optional[list[PluginConfigOverride]]:
        """Fetch per-tool plugin overrides from the DB for *context_id*.

        Returns ``None`` when no *db_factory* is configured or no bindings exist.
        """
        return self._bindings_to_overrides(await self._fetch_bindings(context_id))

    @staticmethod
    def _bindings_to_overrides(bindings: list[Any]) -> Optional[list[PluginConfigOverride]]:
        """Translate binding rows into ``PluginConfigOverride`` objects."""
        if not bindings:
            logger.debug("get_config_from_db: no bindings found")
            return None

        overrides: list[PluginConfigOverride] = []
        for binding in bindings:
            plugin_name = binding.plugin_id
            mapping = _LEGACY_MODE_TO_PLUGIN_MODE.get(binding.mode) if binding.mode else None
            mode: Optional[PluginMode] = mapping[0] if mapping is not None else None
            on_error: Optional[OnError] = mapping[1] if mapping is not None else None

            binding_on_error = getattr(binding, "on_error", None)
            if binding_on_error is not None:
                try:
                    on_error = OnError(binding_on_error)
                except ValueError:
                    logger.warning("get_config_from_db: invalid on_error=%r for binding %s, ignoring", binding_on_error, binding.plugin_id)

            overrides.append(
                PluginConfigOverride(
                    name=plugin_name,
                    config=binding.config or {},
                    mode=mode,
                    on_error=on_error,
                    priority=binding.priority,
                )
            )

        return overrides if overrides else None

    async def invalidate_all(self) -> None:
        """Reload every cached manager concurrently, logging failures."""
        async with self._lock:
            context_ids = list(self._managers.keys())
        results = await asyncio.gather(
            *(self.reload_tenant(ctx_id) for ctx_id in context_ids),
            return_exceptions=True,
        )
        for ctx_id, result in zip(context_ids, results):
            if isinstance(result, BaseException):
                logger.warning("invalidate_all: reload failed for context_id=%s (%s)", ctx_id, result)
        logger.debug("invalidate_all: rebuilt %d managers (%d failures)", len(context_ids), sum(1 for r in results if isinstance(r, BaseException)))

    async def invalidate_team(self, team_id: str, separator: Optional[str] = None) -> None:
        """Reload every cached manager whose context_id starts with team_id plus separator."""
        sep = separator if separator is not None else CONTEXT_ID_SEPARATOR
        prefix = f"{team_id}{sep}"
        async with self._lock:
            context_ids = [cid for cid in self._managers if cid.startswith(prefix)]
        results = await asyncio.gather(
            *(self.reload_tenant(ctx_id) for ctx_id in context_ids),
            return_exceptions=True,
        )
        for ctx_id, result in zip(context_ids, results):
            if isinstance(result, BaseException):
                logger.warning("invalidate_team: reload failed for context_id=%s (%s)", ctx_id, result)
        logger.debug("invalidate_team: team=%s rebuilt %d managers (%d failures)", team_id, len(context_ids), sum(1 for r in results if isinstance(r, BaseException)))

    def iter_context_ids(self) -> list[str]:
        """Return a snapshot of the cached context IDs."""
        return list(self._managers.keys())


# Deprecated: use TenantPluginManagerFactory directly. Remove after v1.1.0.
GatewayTenantPluginManagerFactory = TenantPluginManagerFactory


def make_context_id(team_id: str, tool_name: str) -> str:
    """Build the context_id string expected by TenantPluginManagerFactory."""
    return f"{team_id}{CONTEXT_ID_SEPARATOR}{tool_name}"
