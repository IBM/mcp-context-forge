# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/catalog.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

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
from mcpgateway.schemas import CatalogListRequest, CatalogListResponse, CatalogServerRegisterBody, CatalogServerRegisterRequest, CatalogServerRegisterResponse
from mcpgateway.services.catalog_service import CATALOG_REGISTER_ALREADY_REGISTERED_MSG, CATALOG_REGISTER_NOT_FOUND_MSG, CatalogRegistrationPermissionError, catalog_service

router = APIRouter(prefix="/catalog", tags=["Catalog"])


@router.get("", response_model=CatalogListResponse)
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


# Registration bottoms out in gateway_service.register_gateway (a federated peer), so it requires
# the same gateways.create as POST /v1/gateways in addition to the admin twin's servers.create.
@router.post("/{catalog_id}/register", response_model=CatalogServerRegisterResponse)
@require_permission("servers.create", allow_admin_bypass=False)
@require_permission("gateways.create", allow_admin_bypass=False)
async def register_catalog_server(
    catalog_id: str,
    request: Request,
    body: Optional[CatalogServerRegisterBody] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> CatalogServerRegisterResponse:
    """Register a catalog server as a gateway for the authenticated API caller.

    Unknown catalog ids map to HTTP 404 and already-registered servers to HTTP 409.
    Remaining business failures (unreachable server, auth failure) are returned as an
    HTTP 200 envelope with ``success=False`` and a mapped message; the ``error`` field
    is blanked because the service captures raw exception text there. The admin
    registration endpoint keeps its 200-envelope contract unchanged.

    Args:
        catalog_id: Catalog server ID to register.
        request: FastAPI request object.
        body: Optional overrides (custom name, API key).
        db: Database session.
        user: Authenticated user.

    Returns:
        Registration result envelope.

    Raises:
        HTTPException: If the catalog feature is disabled (404), the catalog id is
            unknown (404), or the server is already registered (409).
    """
    if not settings.mcpgateway_catalog_enabled:
        raise HTTPException(status_code=404, detail="Catalog feature is disabled")

    # Map body fields (including visibility/team_id) into the service request
    service_request = (
        CatalogServerRegisterRequest(
            server_id=catalog_id,
            name=body.name if body else None,
            api_key=body.api_key if body else None,
            visibility=body.visibility if body else None,
            team_id=body.team_id if body else None,
        )
        if body
        else None
    )

    user_email, token_teams = get_scoped_resource_access_context(request, user)

    try:
        result = await catalog_service.register_catalog_server(
            catalog_id=catalog_id,
            request=service_request,
            db=db,
            created_by=user_email,
            owner_email=user_email,
            token_teams=token_teams,
        )
    except CatalogRegistrationPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if not result.success:
        if result.message == CATALOG_REGISTER_NOT_FOUND_MSG:
            raise HTTPException(status_code=404, detail="Catalog server not found")
        if result.message == CATALOG_REGISTER_ALREADY_REGISTERED_MSG:
            raise HTTPException(status_code=409, detail="Server already registered")
        result.error = None

    return result
