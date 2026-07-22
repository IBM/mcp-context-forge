# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/search.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unified Search API Router.

Exposes unified cross-entity search at a stable, versioned, non-admin path
(``GET /v1/search``) so client-facing callers do not depend on
``GET /admin/search``, which is gated on ``admin.dashboard`` and slated for
deprecation.

Security model:
    Authentication only at the top level (no ``admin.dashboard`` gate). Real
    authorization is enforced per-entity inside
    :func:`mcpgateway.admin.perform_unified_search`, and token scoping still
    filters visible entities.
"""

# Standard
import logging
from typing import Any, Optional

# Third-Party
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.common.query_params import QueryEntityTypes, QueryGatewayIdList, QueryTagsFilter
from mcpgateway.config import settings
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Search"])


@router.get("/search", response_class=JSONResponse)
async def unified_search(
    q: str = Query("", max_length=500, description="Search query"),
    tags: QueryTagsFilter = None,
    entity_types: QueryEntityTypes = None,
    include_inactive: bool = False,
    limit: int = Query(8, ge=1, le=settings.pagination_max_page_size, description="Per-entity result limit"),
    limit_per_type: Optional[int] = Query(
        None,
        ge=1,
        le=settings.pagination_max_page_size,
        description="Optional alias for per-entity result limit",
    ),
    gateway_id: QueryGatewayIdList = None,
    team_id: Optional[str] = Query(None, description="Filter by team ID"),
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user_with_permissions),
) -> dict[str, Any]:
    """Unified search across primary entities (versioned, non-admin route).

    Same behavior and response shape as ``GET /admin/search`` without the
    ``admin.dashboard`` gate; delegates to
    :func:`mcpgateway.admin.perform_unified_search`.

    Args:
        q (str): Free-text search query.
        tags (Optional[str]): Tag filter expression (comma=OR, plus=AND).
        entity_types (Optional[str]): Optional comma-separated entity type list.
            Supported values: servers, gateways, tools, resources, prompts,
            agents, teams, users, roots.
        include_inactive (bool): Whether to include inactive entities.
        limit (int): Default per-entity limit for returned items.
        limit_per_type (Optional[int]): Optional alias overriding ``limit``.
        gateway_id (Optional[str]): Gateway filter for tools/resources/prompts.
        team_id (Optional[str]): Team scope filter.
        db (Session): Database session.
        user: Authenticated user context.

    Returns:
        dict[str, Any]: Grouped and flattened search results with metadata.
    """
    # Import lazily so admin-disabled deployments do not load mcpgateway.admin
    # (and its module-level service instances) at startup. The search router is
    # always mounted, but the admin core is only needed once a search runs.
    # First-Party
    from mcpgateway.admin import _validated_team_id_param, perform_unified_search  # noqa: PLC2701 — reuse admin core, deferred to keep admin off the startup import path  # pylint: disable=import-outside-toplevel

    team_id = _validated_team_id_param(team_id)
    return await perform_unified_search(
        q=q,
        tags=tags,
        entity_types=entity_types,
        include_inactive=include_inactive,
        limit=limit,
        limit_per_type=limit_per_type,
        gateway_id=gateway_id,
        team_id=team_id,
        db=db,
        user=user,
    )
