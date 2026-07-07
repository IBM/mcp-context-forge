# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/catalog.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: IBM

MCP Registry catalog API router.
"""

# Standard
from typing import List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth_context import get_scoped_resource_access_context
from mcpgateway.config import settings
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.schemas import CatalogListRequest, CatalogListResponse
from mcpgateway.services.catalog_service import catalog_service

router = APIRouter(prefix="/catalog", tags=["Catalog"])


@router.get("", response_model=CatalogListResponse)
@router.get("/", response_model=CatalogListResponse)
@require_permission("servers.read")
async def list_catalog_servers(
    request: Request,
    category: Optional[str] = None,
    auth_type: Optional[str] = None,
    provider: Optional[str] = None,
    search: Optional[str] = None,
    tags: Optional[List[str]] = Query(None),
    show_registered_only: bool = False,
    show_available_only: bool = True,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> CatalogListResponse:
    """Get MCP registry catalog servers for the authenticated API caller.

    Args:
        request: FastAPI request object.
        category: Filter by category.
        auth_type: Filter by authentication type.
        provider: Filter by provider.
        search: Search in name/description.
        tags: Filter by one or more tags.
        show_registered_only: Show only already registered servers visible to the caller.
        show_available_only: Show only available servers.
        limit: Maximum results.
        offset: Pagination offset.
        db: Database session.
        user: Authenticated user.

    Returns:
        Catalog servers matching the provided filters.

    Raises:
        HTTPException: If the catalog feature is disabled.
    """
    if not settings.mcpgateway_catalog_enabled:
        raise HTTPException(status_code=404, detail="Catalog feature is disabled")

    user_email, token_teams = get_scoped_resource_access_context(request, user)
    catalog_request = CatalogListRequest(
        category=category,
        auth_type=auth_type,
        provider=provider,
        search=search,
        tags=tags or [],
        show_registered_only=show_registered_only,
        show_available_only=show_available_only,
        limit=limit,
        offset=offset,
    )

    return await catalog_service.get_catalog_servers(catalog_request, db, user_email=user_email, token_teams=token_teams)
