# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/dynamic_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Dynamic Server Catalog Router.

Exposes the DynamicServerService via REST endpoints for creating, reading,
updating, and deleting dynamic servers and their filtering rules.

Catalog endpoints (tools, resources, prompts, preview) are stubbed with
HTTP 501 until the rule evaluation engine (Issue 4) is merged.

Examples:
    >>> from fastapi import FastAPI
    >>> from mcpgateway.routers.dynamic_router import dynamic_router
    >>> app = FastAPI()
    >>> app.include_router(dynamic_router, prefix="/dynamic-servers", tags=["Dynamic Servers"])
    >>> isinstance(dynamic_router, APIRouter)
    True
"""

# Standard
from typing import List

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import DynamicRule as DbDynamicRule, get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.schemas import (
    DynamicCatalogResponse,
    DynamicRuleCreate,
    DynamicRuleRead,
    DynamicServerCreate,
    DynamicServerRead,
    DynamicServerUpdate,
)
from mcpgateway.services.dynamic_server_service import DynamicServerService
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Create router
dynamic_router = APIRouter()


# ---------------------------------------------------------------------------
# CRUD Operations
# ---------------------------------------------------------------------------


@dynamic_router.post("/", response_model=DynamicServerRead, status_code=status.HTTP_201_CREATED)
@require_permission("dynamic_servers.create")
async def create_dynamic_server(
    request: DynamicServerCreate,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> DynamicServerRead:
    """Create a new dynamic server with optional filtering rules.

    Args:
        request: Dynamic server creation data including name, rules, and visibility.
        current_user_ctx: Currently authenticated user context.
        db: Database session.

    Returns:
        DynamicServerRead: The created dynamic server.

    Raises:
        HTTPException: 400 if validation fails, 500 on unexpected errors.
    """
    try:
        logger.info(f"Creating dynamic server: {request.name}")
        service = DynamicServerService()
        result = service.create_dynamic_server(db, request, current_user_ctx)
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error creating dynamic server: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error creating dynamic server: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create dynamic server")


@dynamic_router.get("/", response_model=List[DynamicServerRead])
@require_permission("dynamic_servers.read")
async def list_dynamic_servers(
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> List[DynamicServerRead]:
    """List dynamic servers with pagination and team scoping.

    Args:
        limit: Maximum number of results to return.
        offset: Number of results to skip.
        current_user_ctx: Currently authenticated user context.
        db: Database session.

    Returns:
        List[DynamicServerRead]: Paginated list of dynamic servers.

    Raises:
        HTTPException: 500 on unexpected errors.
    """
    try:
        logger.info(f"Listing dynamic servers (limit={limit}, offset={offset})")
        service = DynamicServerService()
        token_teams = current_user_ctx.get("teams")
        results = service.list_dynamic_servers(db, token_teams=token_teams, limit=limit, offset=offset)
        return results
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error listing dynamic servers: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list dynamic servers")


@dynamic_router.get("/{server_id}", response_model=DynamicServerRead)
@require_permission("dynamic_servers.read")
async def get_dynamic_server(
    server_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> DynamicServerRead:
    """Get a single dynamic server by ID.

    Args:
        server_id: Unique identifier of the dynamic server.
        current_user_ctx: Currently authenticated user context.
        db: Database session.

    Returns:
        DynamicServerRead: The requested dynamic server.

    Raises:
        HTTPException: 404 if server not found, 500 on unexpected errors.
    """
    try:
        logger.info(f"Fetching dynamic server: {server_id}")
        service = DynamicServerService()
        result = service.get_dynamic_server(db, server_id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching dynamic server {server_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get dynamic server")


@dynamic_router.put("/{server_id}", response_model=DynamicServerRead)
@require_permission("dynamic_servers.update")
async def update_dynamic_server(
    server_id: str,
    request: DynamicServerUpdate,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> DynamicServerRead:
    """Update an existing dynamic server.

    Args:
        server_id: Unique identifier of the dynamic server.
        request: Fields to update on the dynamic server.
        current_user_ctx: Currently authenticated user context.
        db: Database session.

    Returns:
        DynamicServerRead: The updated dynamic server.

    Raises:
        HTTPException: 400 if validation fails, 404 if server not found, 500 on unexpected errors.
    """
    try:
        logger.info(f"Updating dynamic server: {server_id}")
        service = DynamicServerService()
        result = service.update_dynamic_server(db, server_id, request)
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error updating dynamic server {server_id}: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error updating dynamic server {server_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update dynamic server")


@dynamic_router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission("dynamic_servers.delete")
async def delete_dynamic_server(
    server_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> None:
    """Delete a dynamic server and its associated rules.

    Args:
        server_id: Unique identifier of the dynamic server to delete.
        current_user_ctx: Currently authenticated user context.
        db: Database session.

    Returns:
        None: No content on success (HTTP 204).

    Raises:
        HTTPException: 404 if server not found, 500 on unexpected errors.
    """
    try:
        logger.info(f"Deleting dynamic server: {server_id}")
        service = DynamicServerService()
        service.delete_dynamic_server(db, server_id)
        return None
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error deleting dynamic server {server_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete dynamic server")


# ---------------------------------------------------------------------------
# Rule Operations
# ---------------------------------------------------------------------------


@dynamic_router.post("/{server_id}/rules", response_model=DynamicRuleRead, status_code=status.HTTP_201_CREATED)
@require_permission("dynamic_servers.update")
async def add_rule(
    server_id: str,
    request: DynamicRuleCreate,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> DynamicRuleRead:
    """Add a filtering rule to a dynamic server.

    Args:
        server_id: Unique identifier of the dynamic server.
        request: Rule creation data with rule_type, entity_type, and value.
        current_user_ctx: Currently authenticated user context.
        db: Database session.

    Returns:
        DynamicRuleRead: The created rule.

    Raises:
        HTTPException: 400 if validation fails, 404 if server not found, 500 on unexpected errors.
    """
    try:
        logger.info(f"Adding rule to dynamic server: {server_id}")
        # Verify the server exists (raises 404 if not)
        service = DynamicServerService()
        service.get_dynamic_server(db, server_id)

        rule = DbDynamicRule(
            dynamic_server_id=server_id,
            rule_type=request.rule_type,
            entity_type=request.entity_type,
            value=request.value,
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        logger.info(f"Added rule {rule.id} to dynamic server {server_id}")
        return DynamicRuleRead(
            id=rule.id,
            rule_type=rule.rule_type,
            entity_type=rule.entity_type,
            value=rule.value,
            created_at=rule.created_at,
        )
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error adding rule to server {server_id}: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error adding rule to server {server_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to add rule")


@dynamic_router.delete("/{server_id}/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission("dynamic_servers.update")
async def delete_rule(
    server_id: str,
    rule_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> None:
    """Remove a filtering rule from a dynamic server.

    Args:
        server_id: Unique identifier of the dynamic server.
        rule_id: Unique identifier of the rule to remove.
        current_user_ctx: Currently authenticated user context.
        db: Database session.

    Returns:
        None: No content on success (HTTP 204).

    Raises:
        HTTPException: 404 if server or rule not found, 500 on unexpected errors.
    """
    try:
        logger.info(f"Deleting rule {rule_id} from dynamic server {server_id}")
        # Verify the server exists (raises 404 if not)
        service = DynamicServerService()
        service.get_dynamic_server(db, server_id)

        rule = db.get(DbDynamicRule, rule_id)
        if not rule or rule.dynamic_server_id != server_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Rule {rule_id} not found on server {server_id}",
            )
        db.delete(rule)
        db.commit()
        logger.info(f"Deleted rule {rule_id} from dynamic server {server_id}")
        return None
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error deleting rule {rule_id} from server {server_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete rule")


# ---------------------------------------------------------------------------
# Catalog Endpoints
# ---------------------------------------------------------------------------


@dynamic_router.get("/{server_id}/tools", response_model=List[str])
@require_permission("dynamic_servers.read")
async def get_catalog_tools(
    server_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> List[str]:
    """Get tool names matched by this dynamic server's rules.

    Evaluates the server's rules against the live tool catalog and returns
    the names of all matching tools.

    Args:
        server_id: Unique identifier of the dynamic server.
        current_user_ctx: Currently authenticated user context.
        db: Database session.

    Returns:
        List[str]: Sorted list of matching tool names.

    Raises:
        HTTPException: 501 while catalog evaluation is not implemented.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Catalog tools preview is not implemented")

    try:
        logger.info(f"Evaluating catalog tools for server {server_id}")
        service = DynamicServerService()
        result = await service.evaluate_catalog(db, server_id)
        return result.tools
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error evaluating catalog tools for server {server_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to evaluate catalog tools")


@dynamic_router.get("/{server_id}/resources", response_model=List[str])
@require_permission("dynamic_servers.read")
async def get_catalog_resources(
    server_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> List[str]:
    """Get resource names matched by this dynamic server's rules.

    Evaluates the server's rules against the live resource catalog and returns
    the names of all matching resources.

    Args:
        server_id: Unique identifier of the dynamic server.
        current_user_ctx: Currently authenticated user context.
        db: Database session.

    Returns:
        List[str]: Sorted list of matching resource names.

    Raises:
        HTTPException: 501 while catalog evaluation is not implemented.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Catalog resources preview is not implemented")

    try:
        logger.info(f"Evaluating catalog resources for server {server_id}")
        service = DynamicServerService()
        result = await service.evaluate_catalog(db, server_id)
        return result.resources
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error evaluating catalog resources for server {server_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to evaluate catalog resources")


@dynamic_router.get("/{server_id}/prompts", response_model=List[str])
@require_permission("dynamic_servers.read")
async def get_catalog_prompts(
    server_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> List[str]:
    """Get prompt names matched by this dynamic server's rules.

    Evaluates the server's rules against the live prompt catalog and returns
    the names of all matching prompts.

    Args:
        server_id: Unique identifier of the dynamic server.
        current_user_ctx: Currently authenticated user context.
        db: Database session.

    Returns:
        List[str]: Sorted list of matching prompt names.

    Raises:
        HTTPException: 501 while catalog evaluation is not implemented.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Catalog prompts preview is not implemented")

    try:
        logger.info(f"Evaluating catalog prompts for server {server_id}")
        service = DynamicServerService()
        result = await service.evaluate_catalog(db, server_id)
        return result.prompts
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error evaluating catalog prompts for server {server_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to evaluate catalog prompts")


@dynamic_router.post("/preview", response_model=DynamicCatalogResponse)
@require_permission("dynamic_servers.read")
async def preview_catalog(
    request: DynamicServerCreate,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> DynamicCatalogResponse:
    """Preview what a set of rules would match without persisting a server.

    Evaluates the provided rules against the live catalog as a dry run.
    Nothing is written to the database.

    Args:
        request: Dynamic server definition containing the rules to preview.
                 The name and description fields are ignored.
        current_user_ctx: Currently authenticated user context.
        db: Database session.

    Returns:
        DynamicCatalogResponse: Matching tools, resources, and prompts.

    Raises:
        HTTPException: 501 while catalog evaluation is not implemented.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Catalog preview is not implemented")

    try:
        logger.info("Evaluating catalog preview")
        service = DynamicServerService()
        result = await service.preview_catalog(db, request.rules or [])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during catalog preview: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to preview catalog")
