# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/plugins.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Versioned plugin discovery API.
"""

# Standard
import logging
from typing import Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.plugins import are_plugins_enabled_shared
from mcpgateway.schemas import PluginListResponse
from mcpgateway.services.plugin_service import get_plugin_service, sync_plugin_service_from_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plugins", tags=["Plugins"])


@router.get("", response_model=PluginListResponse)
@require_permission("plugins.read")
async def list_plugins(
    request: Request,
    search: Optional[str] = None,
    mode: Optional[str] = None,
    hook: Optional[str] = None,
    tag: Optional[str] = None,
    db: Session = Depends(get_db),  # pylint: disable=unused-argument
    user=Depends(get_current_user_with_permissions),  # pylint: disable=unused-argument
) -> PluginListResponse:
    """List installed plugins for authenticated API clients.

    Configuration values are omitted because plugin configuration can contain
    credentials and other administrator-only data.

    Args:
        request: Current FastAPI request.
        search: Optional text search in name, description, and author.
        mode: Optional plugin mode filter.
        hook: Optional hook filter.
        tag: Optional tag filter.
        db: Request-scoped database session used by RBAC.
        user: Authenticated user context.

    Returns:
        Filtered plugin summaries and status counts.

    Raises:
        HTTPException: If plugin metadata cannot be retrieved.
    """
    try:
        plugin_service = get_plugin_service()
        await sync_plugin_service_from_runtime(request, plugin_service)

        if any((search, mode, hook, tag)):
            plugins = plugin_service.search_plugins(query=search, mode=mode, hook=hook, tag=tag)
        else:
            plugins = plugin_service.get_all_plugins()

        safe_plugins = [{**plugin, "config_summary": {}} for plugin in plugins]
        enabled_count = sum(1 for plugin in safe_plugins if plugin["status"] == "enabled")
        disabled_count = sum(1 for plugin in safe_plugins if plugin["status"] == "disabled")

        return PluginListResponse(
            plugins_globally_enabled=await are_plugins_enabled_shared(),
            plugins=safe_plugins,
            total=len(safe_plugins),
            enabled_count=enabled_count,
            disabled_count=disabled_count,
        )
    except Exception as exc:
        logger.exception("Failed to list plugins")
        raise HTTPException(status_code=500, detail="Failed to list plugins") from exc
