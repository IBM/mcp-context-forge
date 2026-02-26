# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/jit.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ioannis Ioannou

Just-in-Time (JIT) Access API Router.

Provides REST endpoints for JIT access grant management including
requesting, approving, rejecting, and revoking temporary elevated access.

Examples:
    >>> from mcpgateway.routers.jit import router
    >>> from fastapi import APIRouter
    >>> isinstance(router, APIRouter)
    True
"""

# Standard
import logging
from typing import Generator, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import SessionLocal
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_admin_permission
from mcpgateway.schemas import (
    JITGrantApproveRequest,
    JITGrantListResponse,
    JITGrantRejectRequest,
    JITGrantRequest,
    JITGrantResponse,
    JITGrantRevokeRequest,
)
from mcpgateway.services.jit_service import JITGrantInvalidStatusError, JITGrantNotFoundError, JITService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jit", tags=["JIT Access"])


def get_db() -> Generator[Session, None, None]:
    """Get database session for dependency injection.

    Yields:
        Session: SQLAlchemy database session

    Raises:
        Exception: Re-raises any exception after rolling back the transaction.

    Examples:
        >>> gen = get_db()
        >>> db = next(gen)
        >>> hasattr(db, 'close')
        True
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("", response_model=JITGrantResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=JITGrantResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def request_jit_access(
    request: JITGrantRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_permissions),
) -> JITGrantResponse:
    """Request temporary elevated access (JIT grant).

    Args:
        request: JIT grant request details
        db: Database session
        current_user: Authenticated user

    Returns:
        Created JIT grant

    Raises:
        HTTPException: 400 if request is invalid
    """
    service = JITService(db)
    try:
        grant = await service.create_grant(
            requester_email=current_user.email,
            requested_role=request.requested_role,
            justification=request.justification,
            duration_hours=request.duration_hours,
            ticket_url=request.ticket_url,
        )
        return JITGrantResponse.model_validate(grant)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("", response_model=JITGrantListResponse)
@router.get("/", response_model=JITGrantListResponse, include_in_schema=False)
async def list_jit_grants(
    requester_email: Optional[str] = Query(None, description="Filter by requester email"),
    grant_status: Optional[str] = Query(None, alias="status", description="Filter by status"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
    current_user=Depends(require_admin_permission),
) -> JITGrantListResponse:
    """List JIT grants (admin only).

    Args:
        requester_email: Optional filter by requester
        grant_status: Optional filter by status
        limit: Maximum results to return
        offset: Pagination offset
        db: Database session
        current_user: Admin user

    Returns:
        List of JIT grants
    """
    service = JITService(db)
    grants = await service.list_grants(
        requester_email=requester_email,
        status=grant_status,
        limit=limit,
        offset=offset,
    )
    return JITGrantListResponse(
        grants=[JITGrantResponse.model_validate(g) for g in grants],
        total=len(grants),
    )


@router.get("/mine", response_model=JITGrantListResponse)
async def list_my_jit_grants(
    grant_status: Optional[str] = Query(None, alias="status", description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_permissions),
) -> JITGrantListResponse:
    """List the current user's own JIT grants.

    Args:
        grant_status: Optional filter by status
        limit: Maximum results
        offset: Pagination offset
        db: Database session
        current_user: Authenticated user

    Returns:
        List of user's JIT grants
    """
    service = JITService(db)
    grants = await service.list_grants(
        requester_email=current_user.email,
        status=grant_status,
        limit=limit,
        offset=offset,
    )
    return JITGrantListResponse(
        grants=[JITGrantResponse.model_validate(g) for g in grants],
        total=len(grants),
    )


@router.get("/{grant_id}", response_model=JITGrantResponse)
async def get_jit_grant(
    grant_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_permissions),
) -> JITGrantResponse:
    """Get a specific JIT grant by ID.

    Args:
        grant_id: Grant ID
        db: Database session
        current_user: Authenticated user

    Returns:
        JIT grant details

    Raises:
        HTTPException: 404 if grant not found, 403 if not authorized
    """
    service = JITService(db)
    try:
        grant = await service.get_grant(grant_id)
    except JITGrantNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    # Users can only view their own grants unless admin
    if grant.requester_email != current_user.email and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return JITGrantResponse.model_validate(grant)


@router.post("/{grant_id}/approve", response_model=JITGrantResponse)
async def approve_jit_grant(
    grant_id: str,
    request: JITGrantApproveRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin_permission),
) -> JITGrantResponse:
    """Approve a pending JIT grant (admin only).

    Args:
        grant_id: Grant ID to approve
        request: Approval request with optional note
        db: Database session
        current_user: Admin user

    Returns:
        Updated JIT grant

    Raises:
        HTTPException: 404 if not found, 400 if invalid status
    """
    service = JITService(db)
    try:
        grant = await service.approve_grant(
            grant_id=grant_id,
            approver_email=current_user.email,
            note=request.note,
        )
        return JITGrantResponse.model_validate(grant)
    except JITGrantNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except JITGrantInvalidStatusError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{grant_id}/reject", response_model=JITGrantResponse)
async def reject_jit_grant(
    grant_id: str,
    request: JITGrantRejectRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin_permission),
) -> JITGrantResponse:
    """Reject a pending JIT grant (admin only).

    Args:
        grant_id: Grant ID to reject
        request: Rejection request with reason
        db: Database session
        current_user: Admin user

    Returns:
        Updated JIT grant

    Raises:
        HTTPException: 404 if not found, 400 if invalid status
    """
    service = JITService(db)
    try:
        grant = await service.reject_grant(
            grant_id=grant_id,
            approver_email=current_user.email,
            reason=request.reason,
        )
        return JITGrantResponse.model_validate(grant)
    except JITGrantNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except JITGrantInvalidStatusError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{grant_id}/revoke", response_model=JITGrantResponse)
async def revoke_jit_grant(
    grant_id: str,
    request: JITGrantRevokeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_permissions),
) -> JITGrantResponse:
    """Revoke an active JIT grant.

    Users can revoke their own grants; admins can revoke any grant.

    Args:
        grant_id: Grant ID to revoke
        request: Revocation request with reason
        db: Database session
        current_user: Authenticated user

    Returns:
        Updated JIT grant

    Raises:
        HTTPException: 404 if not found, 400 if invalid status, 403 if not authorized
    """
    service = JITService(db)
    try:
        grant = await service.get_grant(grant_id)
    except JITGrantNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    if grant.requester_email != current_user.email and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    try:
        grant = await service.revoke_grant(
            grant_id=grant_id,
            revoker_email=current_user.email,
            reason=request.reason,
        )
        return JITGrantResponse.model_validate(grant)
    except JITGrantInvalidStatusError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
