# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/gateway_plugin_manager.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhumohan Jaishankar

Gateway-specific subclass of TenantPluginManagerFactory.

Bridges the ToolPluginBinding DB table with the plugin framework by
implementing get_config_from_db() to translate stored bindings into
PluginConfigOverride objects the framework merges with base YAML config.

Context ID convention: ``"<team_id>::<tool_name>"``
"""

# Standard
import logging
from typing import Callable, Optional

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from cpex.framework import PluginConfigOverride, PluginMode, TenantPluginManagerFactory
from mcpgateway.services.tool_plugin_binding_service import get_bindings_for_tool

logger = logging.getLogger(__name__)

CONTEXT_ID_SEPARATOR = "::"

_BINDING_MODE_TO_PLUGIN_MODE: dict[str, PluginMode] = {
    "enforce": PluginMode.SEQUENTIAL,
    "permissive": PluginMode.AUDIT,
    "disabled": PluginMode.DISABLED,
}


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

    def __init__(self, *args: object, db_factory: Callable[[], Session], **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._db_factory = db_factory

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
