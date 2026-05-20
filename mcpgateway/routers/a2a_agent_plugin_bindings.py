# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/a2a_agent_plugin_bindings.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Madhumohan Jaishankar

A2A Agent Plugin Bindings Router.
Provides endpoints for configuring per-agent per-tenant plugin policies for A2A agents.

Endpoints:
    POST   /v1/a2a-agents/plugin-bindings                              — Create or update a binding (upsert)
    GET    /v1/a2a-agents/plugin-bindings                              — List all bindings
    GET    /v1/a2a-agents/plugin-bindings/{team_id}                    — List bindings for a specific team
    DELETE /v1/a2a-agents/plugin-bindings?binding_reference_id={ref}   — Delete all bindings by external reference ID
    DELETE /v1/a2a-agents/plugin-bindings/{id}                         — Delete a binding by UUID
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
from mcpgateway.schemas import A2AAgentPluginBindingListResponse, A2AAgentPluginBindingRequest, A2AAgentPluginBindingResponse
from mcpgateway.services.a2a_agent_plugin_binding_service import A2AAgentPluginBindingForbiddenError, A2AAgentPluginBindingNotFoundError, A2AAgentPluginBindingService
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

router = APIRouter(prefix="/v1/a2a-agents/plugin-bindings", tags=["A2A Agent Plugin Bindings"])

_service = A2AAgentPluginBindingService()


def _allowed_teams_from_ctx(ctx: Dict[str, Any]) -> Optional[set[str]]:
    """Derive the set of teams a caller is allowed to mutate.

    Returns ``None`` for unrestricted admins (full bypass).
    Returns an empty set for public-only callers (nothing allowed).
    """
    is_admin: bool = ctx.get("is_admin", False)
    token_teams = ctx.get("token_teams")
    return None if (is_admin and token_teams is None) else set(token_teams or [])


async def _invalidate_and_broadcast(bindings: List[A2AAgentPluginBindingResponse]) -> None:
    """Evict local caches and broadcast pub/sub frames for a batch of bindings.

    Wildcard bindings (``agent_name == "*"``) affect every cached context for
    the team, so they go through the team-wide channel; specific bindings only
    evict the one context.
    """
    wildcard_teams = {b.team_id for b in bindings if b.agent_name == "*"}
    specific_ctx_ids = {make_context_id(b.team_id, b.agent_name) for b in bindings if b.agent_name != "*"}

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
# POST — upsert binding
# ---------------------------------------------------------------------------


@router.post("/", response_model=A2AAgentPluginBindingResponse, status_code=status.HTTP_200_OK)
@require_permission("tools.manage_plugins")
async def upsert_a2a_agent_plugin_binding(
    request: A2AAgentPluginBindingRequest,
    current_user_ctx: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
    team_id: str = Query(..., min_length=1, description="Team ID to create the binding for"),
) -> A2AAgentPluginBindingResponse:
    """Create or update an A2A agent plugin binding.

    Each (team_id, agent_name, plugin_id) triple is upserted:
    - Existing rows are updated in place (id and created_* fields preserved).
    - New rows are inserted.

    Args:
        request: Validated binding payload.
        current_user_ctx: Authenticated user context.
        db: Database session.
        team_id: Team ID to create the binding for (required query parameter).

    Returns:
        A2AAgentPluginBindingResponse: The created or updated binding.

    Raises:
        HTTPException: 400 if the request payload is invalid, 403 if the caller lacks permission.

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(upsert_a2a_agent_plugin_binding)
        True
    """
    try:
        caller_email: str = current_user_ctx["email"]
        allowed_teams = _allowed_teams_from_ctx(current_user_ctx)
        user_teams: set = set() if allowed_teams is None else allowed_teams

        if allowed_teams is not None and team_id not in user_teams:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Not authorized to configure bindings for team: {team_id}",
            )

        binding = _service.upsert_binding(
            db=db,
            team_id=team_id,
            agent_name=request.agent_name,
            plugin_id=request.plugin_id,
            mode=request.mode,
            priority=request.priority,
            config=request.config,
            on_error=request.on_error,
            caller_email=caller_email,
        )
        db.commit()
        await _invalidate_and_broadcast([binding])
        return binding
    except ValueError as exc:
        logger.error("Failed to upsert A2A agent plugin binding: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET — list all bindings
# ---------------------------------------------------------------------------


@router.get("/", response_model=A2AAgentPluginBindingListResponse)
@require_permission("tools.read")
async def list_a2a_agent_plugin_bindings(
    binding_reference_id: Optional[str] = None,
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Maximum number of results"),
    offset: Optional[int] = Query(None, ge=0, description="Number of results to skip"),
    current_user_ctx: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> A2AAgentPluginBindingListResponse:
    """List all A2A agent plugin bindings across all teams.

    Args:
        binding_reference_id: Optional filter — return only bindings with this reference ID.
        limit: Maximum number of results to return.
        offset: Number of results to skip.
        current_user_ctx: Authenticated user context.
        db: Database session.

    Returns:
        A2AAgentPluginBindingListResponse: Paginated bindings.

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(list_a2a_agent_plugin_bindings)
        True
    """
    limit_val = limit if isinstance(limit, int) else 100
    offset_val = offset if isinstance(offset, int) else 0
    bindings, total = _service.list_bindings(db, team_id=None, binding_reference_id=binding_reference_id, limit=limit_val, offset=offset_val)
    return A2AAgentPluginBindingListResponse(bindings=bindings, total=total)


# ---------------------------------------------------------------------------
# GET /{team_id} — list bindings for a team
# ---------------------------------------------------------------------------


@router.get("/{team_id}", response_model=A2AAgentPluginBindingListResponse)
@require_permission("tools.read")
async def list_a2a_agent_plugin_bindings_for_team(
    team_id: str,
    binding_reference_id: Optional[str] = None,
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Maximum number of results"),
    offset: Optional[int] = Query(None, ge=0, description="Number of results to skip"),
    current_user_ctx: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> A2AAgentPluginBindingListResponse:
    """List all A2A agent plugin bindings for a specific team.

    Args:
        team_id: Team identifier to filter by.
        binding_reference_id: Optional filter — return only bindings with this reference ID.
        limit: Maximum number of results to return.
        offset: Number of results to skip.
        current_user_ctx: Authenticated user context.
        db: Database session.

    Returns:
        A2AAgentPluginBindingListResponse: Bindings for the specified team.

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(list_a2a_agent_plugin_bindings_for_team)
        True
    """
    limit_val = limit if isinstance(limit, int) else 100
    offset_val = offset if isinstance(offset, int) else 0
    bindings, total = _service.list_bindings(db, team_id=team_id, binding_reference_id=binding_reference_id, limit=limit_val, offset=offset_val)
    return A2AAgentPluginBindingListResponse(bindings=bindings, total=total)


# ---------------------------------------------------------------------------
# DELETE / — remove all bindings by external reference ID
# ---------------------------------------------------------------------------


@router.delete("/", response_model=A2AAgentPluginBindingListResponse, status_code=status.HTTP_200_OK)
@require_permission("tools.manage_plugins")
async def delete_a2a_agent_plugin_bindings_by_reference(
    binding_reference_id: str = Query(..., min_length=1, description="External reference ID whose bindings to delete"),
    current_user_ctx: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> A2AAgentPluginBindingListResponse:
    """Delete all bindings associated with an external reference ID.

    Intended for use by external systems that need to remove all ContextForge
    bindings tied to one of their own reference objects without knowing the
    internal ContextForge UUIDs.

    Returns the deleted records (empty list if none matched — not an error).

    Non-admin callers may only delete bindings belonging to their own teams;
    bindings on other teams are silently skipped.

    Args:
        binding_reference_id: The external reference ID whose bindings to delete.
        current_user_ctx: Authenticated user context.
        db: Database session.

    Returns:
        A2AAgentPluginBindingListResponse: All deleted binding records.

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(delete_a2a_agent_plugin_bindings_by_reference)
        True
    """
    allowed_teams = _allowed_teams_from_ctx(current_user_ctx)
    deleted: List[A2AAgentPluginBindingResponse] = _service.delete_bindings_by_reference(db, binding_reference_id, allowed_teams=allowed_teams)
    db.commit()
    await _invalidate_and_broadcast(deleted)
    return A2AAgentPluginBindingListResponse(bindings=deleted, total=len(deleted))


# ---------------------------------------------------------------------------
# DELETE /{id} — remove a binding by its UUID
# ---------------------------------------------------------------------------


@router.delete("/{binding_id}", response_model=A2AAgentPluginBindingResponse, status_code=status.HTTP_200_OK)
@require_permission("tools.manage_plugins")
async def delete_a2a_agent_plugin_binding(
    binding_id: str,
    current_user_ctx: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> A2AAgentPluginBindingResponse:
    """Delete an A2A agent plugin binding by its unique ID.

    Returns the full details of the deleted binding so callers can
    confirm exactly what was removed without a prior GET.

    Args:
        binding_id: UUID of the binding to delete.
        current_user_ctx: Authenticated user context.
        db: Database session.

    Returns:
        A2AAgentPluginBindingResponse: The deleted binding record.

    Raises:
        HTTPException: 403 if the caller is not a member of the binding's team.
        HTTPException: 404 if no binding with the given ID exists.

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(delete_a2a_agent_plugin_binding)
        True
    """
    try:
        allowed_teams = _allowed_teams_from_ctx(current_user_ctx)
        deleted = _service.delete_binding(db, binding_id, allowed_teams=allowed_teams)
        db.commit()
        await _invalidate_and_broadcast([deleted])
        return deleted
    except A2AAgentPluginBindingNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except A2AAgentPluginBindingForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
