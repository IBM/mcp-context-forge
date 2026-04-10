# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Gateway plugin integration.

Provides the global plugin manager factory singleton that wires the
cpex ``TenantPluginManagerFactory`` to gateway-specific hook payload
policies defined in ``mcpgateway.plugins.policy``.
"""

# Standard
from typing import Callable, Optional

# Third-Party
from cpex.framework import ObservabilityProvider, TenantPluginManager, TenantPluginManagerFactory

# --- Global plugin manager factory singleton ---
_PLUGINS_ENABLED = False
_plugin_manager_factory: Optional[TenantPluginManagerFactory] = None
_observability_service: Optional[ObservabilityProvider] = None
DEFAULT_SERVER_ID = "__global__"


def enable_plugins(toggle: bool) -> None:
    """Enable or disable the plugin subsystem globally."""
    global _PLUGINS_ENABLED  # pylint: disable=global-statement
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
    (observability, settings) are ready.

    Args:
        yaml_path: Path to the plugins YAML config file.
        timeout: Per-plugin call timeout in seconds.
        hook_policies: Hook payload policy map from ``mcpgateway.plugins.policy``.
        observability: Optional observability provider to attach to the factory.
        db_factory: Zero-argument callable returning a SQLAlchemy Session
            (e.g. ``SessionLocal``).  When provided the factory uses
            ``GatewayTenantPluginManagerFactory`` so per-tool plugin bindings
            stored in the DB are applied.
    """
    global _plugin_manager_factory  # pylint: disable=global-statement
    global _observability_service  # pylint: disable=global-statement
    _observability_service = observability
    if db_factory is not None:
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
        Context-specific manager when plugins are enabled and the factory is initialized,
        otherwise ``None``.
    """
    if not _PLUGINS_ENABLED:
        return None
    if _plugin_manager_factory is None:
        return None
    return await _plugin_manager_factory.get_manager(server_id)


def set_global_observability(observability: ObservabilityProvider) -> None:
    """Set the global observability provider and propagate it to the active factory."""
    global _observability_service  # pylint: disable=global-statement
    _observability_service = observability
    if _plugin_manager_factory is not None:
        _plugin_manager_factory.observability = observability


async def shutdown_plugin_manager_factory() -> None:
    """Shutdown and reset the global plugin manager factory."""
    global _plugin_manager_factory  # pylint: disable=global-statement
    if not _PLUGINS_ENABLED:
        return
    factory = _plugin_manager_factory
    _plugin_manager_factory = None
    if factory is not None:
        await factory.shutdown()


def reset_plugin_manager_factory() -> None:
    """Reset the global plugin manager factory (for testing)."""
    global _plugin_manager_factory  # pylint: disable=global-statement
    _plugin_manager_factory = None


async def reload_plugin_context(context_id: str) -> None:
    """Invalidate and rebuild the cached plugin manager for *context_id*.

    No-op when plugins are disabled or the factory is not initialised.

    Args:
        context_id: Context key to evict and rebuild.
    """
    if not _PLUGINS_ENABLED or _plugin_manager_factory is None:
        return
    await _plugin_manager_factory.reload_tenant(context_id)
