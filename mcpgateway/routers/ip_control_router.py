# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/ip_control_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

IP Access Control Router.

This module provides REST API endpoints for managing IP-based access control
rules, temporary blocks, testing, and status.

Examples:
    >>> from mcpgateway.routers.ip_control_router import router
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
    IPBlockCreate,
    IPBlockResponse,
    IPControlStatusResponse,
    IPRuleCreate,
    IPRuleListResponse,
    IPRuleResponse,
    IPRuleUpdate,
    IPTestRequest,
    IPTestResponse,
)
from mcpgateway.services.ip_control_service import get_ip_control_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ip-control", tags=["IP Access Control"])


def get_db() -> Generator[Session, None, None]:
    """Get database session for dependency injection.

    Yields:
        Session: SQLAlchemy database session

    Raises:
        Exception: Re-raises any exception after rollback.

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
        try:
            db.rollback()
        except Exception:
            try:
                db.invalidate()
            except Exception:
                pass  # nosec B110 - Best effort cleanup on connection failure
        raise
    finally:
        db.close()


# ===== Rule Management Endpoints =====


@router.post("/rules", response_model=IPRuleResponse, status_code=status.HTTP_201_CREATED)
@require_admin_permission()
async def create_rule(rule_data: IPRuleCreate, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Create a new IP access control rule.

    Args:
        rule_data: Rule creation data.
        user: Authenticated admin user context.
        db: Database session.

    Returns:
        IPRuleResponse: Created rule.
    """
    service = get_ip_control_service()
    rule = service.create_rule(
        data=rule_data.model_dump(exclude_none=True),
        user_email=user.get("email", "system") if isinstance(user, dict) else getattr(user, "email", "system"),
        db=db,
    )
    return rule


@router.get("/rules", response_model=IPRuleListResponse)
@require_admin_permission()
async def list_rules(
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=1000, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    is_active: Optional[bool] = Query(default=None, description="Filter by active status"),
    rule_type: Optional[str] = Query(default=None, description="Filter by rule type (allow/deny)"),
):
    """List IP access control rules with pagination.

    Args:
        user: Authenticated admin user context.
        db: Database session.
        limit: Page size.
        offset: Page offset.
        is_active: Optional active filter.
        rule_type: Optional rule type filter.

    Returns:
        IPRuleListResponse: Paginated rules list.
    """
    service = get_ip_control_service()
    rules, total = service.list_rules(db=db, limit=limit, offset=offset, is_active=is_active, rule_type=rule_type)
    return IPRuleListResponse(rules=rules, total=total, limit=limit, offset=offset)


@router.get("/rules/{rule_id}", response_model=IPRuleResponse)
@require_admin_permission()
async def get_rule(rule_id: str, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Get a single IP access control rule.

    Args:
        rule_id: Rule ID.
        user: Authenticated admin user context.
        db: Database session.

    Returns:
        IPRuleResponse: The requested rule.

    Raises:
        HTTPException: 404 if rule not found.
    """
    service = get_ip_control_service()
    rule = service.get_rule(rule_id, db=db)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"IP rule {rule_id} not found")
    return rule


@router.patch("/rules/{rule_id}", response_model=IPRuleResponse)
@require_admin_permission()
async def update_rule(rule_id: str, rule_data: IPRuleUpdate, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Update an existing IP access control rule.

    Args:
        rule_id: Rule ID.
        rule_data: Fields to update.
        user: Authenticated admin user context.
        db: Database session.

    Returns:
        IPRuleResponse: Updated rule.

    Raises:
        HTTPException: 404 if rule not found.
    """
    service = get_ip_control_service()
    rule = service.update_rule(
        rule_id=rule_id,
        data=rule_data.model_dump(exclude_none=True),
        user_email=user.get("email", "system") if isinstance(user, dict) else getattr(user, "email", "system"),
        db=db,
    )
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"IP rule {rule_id} not found")
    return rule


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_admin_permission()
async def delete_rule(rule_id: str, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Delete an IP access control rule.

    Args:
        rule_id: Rule ID.
        user: Authenticated admin user context.
        db: Database session.

    Raises:
        HTTPException: 404 if rule not found.
    """
    service = get_ip_control_service()
    deleted = service.delete_rule(
        rule_id=rule_id,
        user_email=user.get("email", "system") if isinstance(user, dict) else getattr(user, "email", "system"),
        db=db,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"IP rule {rule_id} not found")


# ===== Block Management Endpoints =====


@router.post("/blocks", response_model=IPBlockResponse, status_code=status.HTTP_201_CREATED)
@require_admin_permission()
async def create_block(block_data: IPBlockCreate, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Create a temporary IP block.

    Args:
        block_data: Block creation data.
        user: Authenticated admin user context.
        db: Database session.

    Returns:
        IPBlockResponse: Created block.
    """
    service = get_ip_control_service()
    block = service.create_block(
        data=block_data.model_dump(),
        user_email=user.get("email", "system") if isinstance(user, dict) else getattr(user, "email", "system"),
        db=db,
    )
    return block


@router.get("/blocks", response_model=list[IPBlockResponse])
@require_admin_permission()
async def list_blocks(
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
    active_only: bool = Query(default=True, description="Only show active non-expired blocks"),
):
    """List temporary IP blocks.

    Args:
        user: Authenticated admin user context.
        db: Database session.
        active_only: Whether to filter for active blocks only.

    Returns:
        List of IPBlockResponse.
    """
    service = get_ip_control_service()
    return service.list_blocks(db=db, active_only=active_only)


@router.delete("/blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_admin_permission()
async def remove_block(block_id: str, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Remove (deactivate) a temporary IP block.

    Args:
        block_id: Block ID.
        user: Authenticated admin user context.
        db: Database session.

    Raises:
        HTTPException: 404 if block not found.
    """
    service = get_ip_control_service()
    removed = service.remove_block(
        block_id=block_id,
        user_email=user.get("email", "system") if isinstance(user, dict) else getattr(user, "email", "system"),
        db=db,
    )
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"IP block {block_id} not found")


# ===== Diagnostic Endpoints =====


@router.post("/test", response_model=IPTestResponse)
@require_admin_permission()
async def test_ip(test_data: IPTestRequest, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Test an IP address against current rules (bypasses cache).

    Args:
        test_data: IP and path to test.
        user: Authenticated admin user context.
        db: Database session.

    Returns:
        IPTestResponse: Test result.
    """
    service = get_ip_control_service()
    result = service.test_ip(ip=test_data.ip_address, path=test_data.path, db=db)
    return IPTestResponse(**result)


@router.get("/status", response_model=IPControlStatusResponse)
@require_admin_permission()
async def get_status(user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Get IP access control system status.

    Args:
        user: Authenticated admin user context.
        db: Database session.

    Returns:
        IPControlStatusResponse: System status.
    """
    service = get_ip_control_service()
    return IPControlStatusResponse(**service.get_status(db=db))


@router.post("/cache/clear", status_code=status.HTTP_204_NO_CONTENT)
@require_admin_permission()
async def clear_cache(user=Depends(get_current_user_with_permissions)):
    """Clear the IP control evaluation cache.

    Args:
        user: Authenticated admin user context.
    """
    service = get_ip_control_service()
    service.invalidate_cache()
    logger.info("IP control cache cleared by admin")
