# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/gateway_plugin_manager.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Gateway-owned TenantPluginManagerFactory.

cpex's TenantPluginManagerFactory is no longer imported or subclassed.
This module provides a standalone factory that uses cpex's
TenantPluginManager for actual plugin execution while adding
gateway-specific features:
- TTL-based cache with ``_CachedManager`` wrappers
- Per-plugin Redis mode overrides via ``_apply_redis_mode_overrides``
- ``invalidate_all`` / ``invalidate_team`` for cross-worker propagation
- Deterministic DB-binding compilation against operator plugin definitions
- Optional DB wiring for per-tool plugin bindings

Context ID convention: ``"<team_id>::<tool_name>"``
"""

# Standard
import asyncio
import logging
import time
from typing import Callable, Optional

# Third-Party
from cpex.framework import ConfigLoader, HookPayloadPolicy, ObservabilityProvider, TenantPluginManager
from cpex.framework.models import Config
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.plugins._redis import get_shared_redis_client as _redis
from mcpgateway.plugins._state import active_local_mode_overrides, prune_expired_local_overrides
from mcpgateway.plugins.binding_compiler import BindingCompilationError, BindingCompilationErrorCode, BindingCompilationInput, BindingSource, RuntimeModeOverride, ToolBinding, compile_tool_bindings
from mcpgateway.plugins.metadata import enrich_config_plugin_metadata
from mcpgateway.services.tool_plugin_binding_service import get_bindings_for_tool

logger = logging.getLogger(__name__)

CONTEXT_ID_SEPARATOR = "::"


class _CachedManager:
    """A cached tenant manager paired with the monotonic timestamp of its build."""

    __slots__ = ("manager", "created_at")

    def __init__(self, manager: TenantPluginManager, created_at: float) -> None:
        self.manager = manager
        self.created_at = created_at

    def is_expired(self, ttl: float) -> bool:
        """Return True when ``ttl > 0`` and the entry is older than ``ttl`` seconds."""
        return ttl > 0 and (time.monotonic() - self.created_at) > ttl


class TenantPluginManagerFactory:
    """Standalone factory for context-scoped TenantPluginManager instances.

    TTL caching, Redis mode overrides, invalidate_all/invalidate_team,
    on_error support, and optional DB wiring for per-tool plugin bindings.

    When *db_factory* is provided, ``get_config_from_db`` reads
    ``ToolPluginBinding`` rows for the context.  Without it the method
    returns ``None`` and the base YAML config is compiled without bindings.

    Context IDs must follow the ``"<team_id>::<tool_name>"`` convention.
    Call sites should use :func:`make_context_id` to construct them.
    """

    DEFAULT_CACHE_TTL = 30
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

    async def get_manager(self, context_id: Optional[str] = None) -> TenantPluginManager:
        """Get or create a TenantPluginManager for the given context."""
        context_id = context_id or "__global__"
        expired = None

        async with self._lock:
            entry = self._managers.get(context_id)
            if entry is not None:
                if entry.is_expired(self._cache_ttl):
                    expired = self._managers.pop(context_id, None)
                    logger.debug("Cache TTL expired for context_id=%s, rebuilding", context_id)
                else:
                    return entry.manager

            if expired is not None:
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

    async def _build_manager(self, context_id: str) -> TenantPluginManager:
        """Create, initialise, and cache a new manager for *context_id*."""
        manager = None
        try:
            compiled_config = await self.get_config_from_db(context_id)
            config = self._merge_tenant_config(compiled_config)
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

            old = old_entry.manager if old_entry is not None else None
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
            logger.error("Manager build failed for context_id=%s", context_id, exc_info=True)
            if manager is not None:
                try:
                    await manager.shutdown()
                except Exception:
                    logger.warning("Failed to shutdown manager after error for context_id=%s", context_id)
            raise

    def _merge_tenant_config(self, tenant_config: Config | None) -> Config:
        """Select a compiled tenant config or compile the operator config empty."""
        if tenant_config is not None:
            return tenant_config
        return compile_tool_bindings(BindingCompilationInput(operator_config=self._base_config, tool_name="*", bindings=()))

    async def _apply_redis_mode_overrides(self, config: Config) -> Config:
        """Compile the effective Redis and process-local mode observations."""
        plugins = config.plugins or []
        now = time.monotonic()
        prune_expired_local_overrides(now)
        local_overrides = active_local_mode_overrides(now)

        redis_values: list[bytes | str | None] = [None] * len(plugins)
        if plugins:
            try:
                client = await _redis()
            except Exception as exc:
                logger.warning("Redis mode overrides skipped — client error (%s)", exc, exc_info=True)
                client = None

            if client is not None:
                keys = [f"plugin:{plugin.name}:mode" for plugin in plugins]
                try:
                    redis_values = list(await client.mget(keys))
                except Exception as exc:
                    logger.warning("Redis MGET for plugin modes failed (%s)", exc, exc_info=True)
                    redis_values = [None] * len(plugins)
                if len(redis_values) != len(plugins):
                    raise BindingCompilationError(BindingCompilationErrorCode.RUNTIME_OVERRIDE_MISMATCH)

        runtime_overrides: list[RuntimeModeOverride] = []
        plugin_names = {plugin.name for plugin in plugins}
        for plugin, redis_raw in zip(plugins, redis_values):
            match redis_raw:
                case None:
                    redis_mode = None
                case bytes():
                    try:
                        redis_mode = redis_raw.decode()
                    except UnicodeDecodeError:
                        raise BindingCompilationError(BindingCompilationErrorCode.UNSUPPORTED_MODE, plugin.name) from None
                case str():
                    redis_mode = redis_raw
            local_mode = local_overrides.get(plugin.name)
            if redis_mode is not None or local_mode is not None:
                runtime_overrides.append(RuntimeModeOverride(plugin_id=plugin.name, redis_mode=redis_mode, local_mode=local_mode))

        for plugin_name in sorted(local_overrides.keys() - plugin_names):
            runtime_overrides.append(RuntimeModeOverride(plugin_id=plugin_name, local_mode=local_overrides[plugin_name]))

        if not runtime_overrides:
            return config
        return compile_tool_bindings(BindingCompilationInput(operator_config=config, tool_name="*", bindings=(), runtime_overrides=tuple(runtime_overrides)))

    async def reload_tenant(self, context_id: str) -> TenantPluginManager:
        """Evict and rebuild the cached manager for *context_id*."""
        async with self._lock:
            old_entry = self._managers.pop(context_id, None)

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

    async def get_config_from_db(self, context_id: str) -> Config | None:
        """Fetch and compile per-tool plugin bindings for *context_id*.

        Returns ``None`` only when DB lookup is unavailable for this context.
        """
        if self._db_factory is None:
            return None

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

        detached_bindings = tuple(
            ToolBinding(
                plugin_id=binding.plugin_id,
                tool_name=binding.tool_name,
                mode=binding.mode,
                priority=binding.priority,
                config=binding.config,
                on_error=binding.on_error,
                source=BindingSource.TOOL,
            )
            for binding in bindings
        )
        return compile_tool_bindings(
            BindingCompilationInput(
                operator_config=self._base_config,
                tool_name=tool_name,
                bindings=detached_bindings,
            )
        )

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
