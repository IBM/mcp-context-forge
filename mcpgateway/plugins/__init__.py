# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Gateway plugin integration.

Provides the ``get_plugin_manager()`` singleton factory that wires the
cpex ``PluginManager`` to gateway-specific hook payload policies defined
in ``mcpgateway.plugins.policy``.
"""

# Standard
from typing import Optional

# Third-Party
from cpex.framework import ObservabilityProvider, PluginManager
from cpex.framework.settings import settings

# Plugin manager singleton (lazy initialization)
_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager(observability: Optional[ObservabilityProvider] = None) -> Optional[PluginManager]:
    """Get or initialize the plugin manager singleton.

    This is the public API for accessing the plugin manager from anywhere in the application.
    The plugin manager is lazily initialized on first access if plugins are enabled.

    Args:
        observability: Optional observability provider implementing ObservabilityProvider protocol.

    Returns:
        PluginManager instance if plugins are enabled, None otherwise.

    Examples:
        >>> from mcpgateway.plugins import get_plugin_manager
        >>> pm = get_plugin_manager()
        >>> # Returns PluginManager if plugins are enabled, None otherwise
        >>> pm is None or isinstance(pm, PluginManager)
        True
    """
    global _plugin_manager  # pylint: disable=global-statement
    if _plugin_manager is None:
        if settings.enabled:
            # Import concrete policies from the gateway side
            from mcpgateway.plugins.policy import HOOK_PAYLOAD_POLICIES  # pylint: disable=import-outside-toplevel

            _plugin_manager = PluginManager(
                settings.config_file,
                timeout=settings.plugin_timeout,
                observability=observability,
                hook_policies=HOOK_PAYLOAD_POLICIES,
            )
    return _plugin_manager
