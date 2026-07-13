# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/search.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unified Search API Router.

Exposes the unified cross-entity search capability at a stable, versioned,
non-admin path (``GET /v1/search``). Historically this capability was only
reachable through ``GET /admin/search``, which is gated on the ``admin.dashboard``
permission and lives under the admin dashboard router. Client-facing callers
(e.g. the React global search) should not depend on an admin-panel route that
may be deprecated, so this router re-exposes the same behavior and response
shape without the admin-panel gate.

Security model:
    This route requires only authentication at the top level. It does NOT add
    an ``admin.dashboard`` gate. Real authorization is enforced per-entity
    inside :func:`mcpgateway.admin.perform_unified_search`: each entity search
    carries its own RBAC permission (``tools.read``, ``gateways.read``,
    ``admin.user_management`` for users, etc.) and token scoping continues to
    filter visible entities. Entity-specific denials are suppressed so a single
    restricted entity type never fails the whole search or leaks existence.
"""

# Standard
import logging
from typing import Any, Optional

# Third-Party
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.admin import _validated_team_id_param, perform_unified_search  # noqa: PLC2701 — reuse admin team_id validation for parity
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
    team_id: Optional[str] = Depends(_validated_team_id_param),
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user_with_permissions),
) -> dict[str, Any]:
    """Unified search across primary entities (versioned, non-admin route).

    Preserves the behavior, query parameters, and grouped/flattened response
    shape of ``GET /admin/search`` but without the ``admin.dashboard`` gate.
    Delegates to :func:`mcpgateway.admin.perform_unified_search`; per-entity
    RBAC and token scoping are enforced inside that helper.

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
