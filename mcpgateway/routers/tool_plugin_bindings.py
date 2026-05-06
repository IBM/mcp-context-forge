# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/tool_plugin_bindings.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Madhumohan Jaishankar

Tool Plugin Bindings Router.
Provides endpoints for configuring per-tool per-tenant plugin policies.

Endpoints:
    POST   /v1/tools/plugin_bindings                              — Create or update bindings (upsert)
    GET    /v1/tools/plugin_bindings                              — List all bindings
    GET    /v1/tools/plugin_bindings/{team_id}                    — List bindings for a specific team
    DELETE /v1/tools/plugin_bindings?binding_reference_id={ref}   — Delete all bindings by external reference ID
    DELETE /v1/tools/plugin_bindings/{id}                         — Delete a binding by UUID
"""

# Standard
from typing import Any, Dict, List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.plugins import get_plugin_manager_factory, publish_binding_change, publish_team_binding_change, reload_plugin_context
from mcpgateway.plugins.gateway_plugin_manager import CONTEXT_ID_SEPARATOR, make_context_id
from mcpgateway.schemas import ToolPluginBindingListResponse, ToolPluginBindingRequest, ToolPluginBindingResponse
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.tool_plugin_binding_service import ToolPluginBindingNotFoundError, ToolPluginBindingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

router = APIRouter(prefix="/v1/tools/plugin_bindings", tags=["Tool Plugin Bindings"])

_service = ToolPluginBindingService()


async def _invalidate_and_broadcast(bindings: List[ToolPluginBindingResponse]) -> None:
    """Evict local caches and broadcast pub/sub frames for a batch of bindings.

    Wildcard bindings (``tool_name == "*"``) affect every cached context for
    the team, so they go through the team-wide channel; specific bindings only
    evict the one context. Factory may be ``None`` on nodes where opportunistic
    init failed — we still publish so healthy peers converge.
    """
    wildcard_teams = {b.team_id for b in bindings if b.tool_name == "*"}
    specific_ctx_ids = {make_context_id(b.team_id, b.tool_name) for b in bindings if b.tool_name != "*"}

    for ctx_id in specific_ctx_ids:
        await reload_plugin_context(ctx_id)
        await publish_binding_change(ctx_id)

    if wildcard_teams:
        factory = get_plugin_manager_factory()
        if factory is not None:
            for team_id in wildcard_teams:
                await factory.invalidate_team(team_id, CONTEXT_ID_SEPARATOR)
        for team_id in wildcard_teams:
            await publish_team_binding_change(team_id)


# ---------------------------------------------------------------------------
# POST — upsert bindings
# ---------------------------------------------------------------------------


@router.post("/", response_model=ToolPluginBindingListResponse, status_code=status.HTTP_200_OK)
@require_permission("tools.manage_plugins")
async def upsert_tool_plugin_bindings(
    request: ToolPluginBindingRequest,
    current_user_ctx: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> ToolPluginBindingListResponse:
    """Create or update tool plugin bindings.

    Each (team_id, tool_name, plugin_id) triple is upserted:
    - Existing rows are updated in place (id and created_* fields preserved).
    - New rows are inserted.

    Multiple teams and multiple tools per policy can be configured in a single request.

    Args:
        request: Validated binding payload keyed by team_id.
        current_user_ctx: Authenticated user context.
        db: Database session.

    Returns:
        ToolPluginBindingListResponse: All created/updated bindings.

    Raises:
        HTTPException: 400 if the request payload is invalid, 403 if the caller lacks permission.

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(upsert_tool_plugin_bindings)
        True
    """
    try:
        caller_email: str = current_user_ctx["email"]
        is_admin: bool = current_user_ctx.get("is_admin", False)
        user_teams: list = current_user_ctx.get("teams", []) or []

        if not is_admin:
            unauthorized = [tid for tid in request.teams if tid not in user_teams]
            if unauthorized:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Not authorized to configure bindings for team(s): {', '.join(unauthorized)}",
                )

        bindings = _service.upsert_bindings(db, request, caller_email=caller_email)
        # Commit before invalidating cache so the new session opened by reload
        # reads committed data. The get_db() cleanup commit is then a safe no-op.
        db.commit()

        await _invalidate_and_broadcast(bindings)
        return ToolPluginBindingListResponse(bindings=bindings, total=len(bindings))
    except ValueError as exc:
        logger.error("Failed to upsert tool plugin bindings: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET — list all bindings
# ---------------------------------------------------------------------------


@router.get("/", response_model=ToolPluginBindingListResponse)
@require_permission("tools.read")
async def list_tool_plugin_bindings(
    binding_reference_id: Optional[str] = None,
    current_user_ctx: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> ToolPluginBindingListResponse:
    """List all tool plugin bindings across all teams.

    Args:
        binding_reference_id: Optional filter — return only bindings with this reference ID.
        current_user_ctx: Authenticated user context.
        db: Database session.

    Returns:
        ToolPluginBindingListResponse: All bindings.

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(list_tool_plugin_bindings)
        True
    """
    bindings = _service.list_bindings(db, team_id=None, binding_reference_id=binding_reference_id)
    return ToolPluginBindingListResponse(bindings=bindings, total=len(bindings))


# ---------------------------------------------------------------------------
# GET /{team_id} — list bindings for a team
# ---------------------------------------------------------------------------


@router.get("/{team_id}", response_model=ToolPluginBindingListResponse)
@require_permission("tools.read")
async def list_tool_plugin_bindings_for_team(
    team_id: str,
    binding_reference_id: Optional[str] = None,
    current_user_ctx: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> ToolPluginBindingListResponse:
    """List all tool plugin bindings for a specific team.

    Args:
        team_id: Team identifier to filter by.
        binding_reference_id: Optional filter — return only bindings with this reference ID.
        current_user_ctx: Authenticated user context.
        db: Database session.

    Returns:
        ToolPluginBindingListResponse: Bindings for the specified team.

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(list_tool_plugin_bindings_for_team)
        True
    """
    bindings = _service.list_bindings(db, team_id=team_id, binding_reference_id=binding_reference_id)
    return ToolPluginBindingListResponse(bindings=bindings, total=len(bindings))


# ---------------------------------------------------------------------------
# DELETE / — remove all bindings by external reference ID
# ---------------------------------------------------------------------------


@router.delete("/", response_model=ToolPluginBindingListResponse, status_code=status.HTTP_200_OK)
@require_permission("tools.manage_plugins")
async def delete_tool_plugin_bindings_by_reference(
    binding_reference_id: str = Query(..., min_length=1, description="External reference ID whose bindings to delete"),
    current_user_ctx: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> ToolPluginBindingListResponse:
    """Delete all bindings associated with an external reference ID.

    Intended for use by external systems that need to remove all ContextForge
    bindings tied to one of their own reference objects without knowing the
    internal ContextForge UUIDs.

    Returns the deleted records (empty list if none matched — not an error).

    Args:
        binding_reference_id: The external reference ID whose bindings to delete.
        current_user_ctx: Authenticated user context.
        db: Database session.

    Returns:
        ToolPluginBindingListResponse: All deleted binding records.

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(delete_tool_plugin_bindings_by_reference)
        True
    """
    deleted: List[ToolPluginBindingResponse] = _service.delete_bindings_by_reference(db, binding_reference_id)
    db.commit()
    await _invalidate_and_broadcast(deleted)
    return ToolPluginBindingListResponse(bindings=deleted, total=len(deleted))


# ---------------------------------------------------------------------------
# DELETE /{id} — remove a binding by its UUID
# ---------------------------------------------------------------------------


@router.delete("/{binding_id}", response_model=ToolPluginBindingResponse, status_code=status.HTTP_200_OK)
@require_permission("tools.manage_plugins")
async def delete_tool_plugin_binding(
    binding_id: str,
    current_user_ctx: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> ToolPluginBindingResponse:
    """Delete a tool plugin binding by its unique ID.

    Returns the full details of the deleted binding so callers can
    confirm exactly what was removed without a prior GET.

    Args:
        binding_id: UUID of the binding to delete.
        current_user_ctx: Authenticated user context.
        db: Database session.

    Returns:
        ToolPluginBindingResponse: The deleted binding record.

    Raises:
        HTTPException: 404 if no binding with the given ID exists.

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(delete_tool_plugin_binding)
        True
    """
    try:
        deleted = _service.delete_binding(db, binding_id)
        db.commit()
        await _invalidate_and_broadcast([deleted])
        return deleted
    except ToolPluginBindingNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
