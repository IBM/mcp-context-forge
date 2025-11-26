# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/rbac.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

RBAC API Router.

This module provides REST API endpoints for Role-Based Access Control (RBAC)
management including roles, user role assignments, and permission checking.

Examples:
    >>> from mcpgateway.routers.rbac import router
    >>> from fastapi import APIRouter
    >>> isinstance(router, APIRouter)
    True
"""

# Standard
from datetime import datetime, timezone
import logging
from typing import Generator, List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Permissions, SessionLocal
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_admin_permission, require_permission
from mcpgateway.schemas import PermissionCheckRequest, PermissionCheckResponse, PermissionListResponse, RoleCreateRequest, RoleResponse, RoleUpdateRequest, UserRoleAssignRequest, UserRoleResponse
from mcpgateway.services.permission_service import PermissionService
from mcpgateway.services.role_service import RoleService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rbac", tags=["RBAC"])


def get_db() -> Generator[Session, None, None]:
    """Get database session for dependency injection.

    Yields:
        Session: SQLAlchemy database session

    Examples:
        >>> gen = get_db()
        >>> db = next(gen)
        >>> hasattr(db, 'close')
        True
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ===== Role Management Endpoints =====


@router.post("/roles", response_model=RoleResponse)
@require_admin_permission()
async def create_role(role_data: RoleCreateRequest, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Create a new role.

    Requires admin permissions to create roles.

    Args:
        role_data: Role creation data
        user: Current authenticated user
        db: Database session

    Returns:
        RoleResponse: Created role details

    Raises:
        HTTPException: If role creation fails

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(create_role)
        True
    """
    try:
        role_service = RoleService(db)
        role = await role_service.create_role(
            name=role_data.name,
            description=role_data.description,
            scope=role_data.scope,
            permissions=role_data.permissions,
            inherits_from=role_data.inherits_from,
            created_by=user["email"],
            is_system_role=role_data.is_system_role or False,
        )

        logger.info(f"Role created: {role.id} by {user['email']}")
        return RoleResponse.from_orm(role)

    except ValueError as e:
        logger.error(f"Role creation validation error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Role creation failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create role")


@router.get("/roles", response_model=List[RoleResponse])
@require_permission("admin.user_management")
async def list_roles(
    scope: Optional[str] = Query(None, description="Filter by scope"),
    active_only: bool = Query(True, description="Show only active roles"),
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
):
    """List all roles.

    Args:
        scope: Optional scope filter
        active_only: Whether to show only active roles
        user: Current authenticated user
        db: Database session

    Returns:
        List[RoleResponse]: List of roles

    Raises:
        HTTPException: If user lacks required permissions

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(list_roles)
        True
    """
    try:
        role_service = RoleService(db)
        roles = await role_service.list_roles(scope=scope)

        return [RoleResponse.from_orm(role) for role in roles]

    except Exception as e:
        logger.error(f"Failed to list roles: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve roles")


@router.get("/roles/{role_id}", response_model=RoleResponse)
@require_permission("admin.user_management")
async def get_role(role_id: str, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Get role details by ID.

    Args:
        role_id: Role identifier
        user: Current authenticated user
        db: Database session

    Returns:
        RoleResponse: Role details

    Raises:
        HTTPException: If role not found

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(get_role)
        True
    """
    try:
        role_service = RoleService(db)
        role = await role_service.get_role_by_id(role_id)

        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

        return RoleResponse.from_orm(role)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get role {role_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve role")


@router.put("/roles/{role_id}", response_model=RoleResponse)
@require_admin_permission()
async def update_role(role_id: str, role_data: RoleUpdateRequest, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Update an existing role.

    Args:
        role_id: Role identifier
        role_data: Role update data
        user: Current authenticated user
        db: Database session

    Returns:
        RoleResponse: Updated role details

    Raises:
        HTTPException: If role not found or update fails

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(update_role)
        True
    """
    try:
        role_service = RoleService(db)
        role = await role_service.update_role(role_id, **role_data.dict(exclude_unset=True))

        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

        logger.info(f"Role updated: {role_id} by {user['email']}")
        return RoleResponse.from_orm(role)

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Role update validation error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Role update failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update role")


@router.delete("/roles/{role_id}")
@require_admin_permission()
async def delete_role(role_id: str, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Delete a role.

    Args:
        role_id: Role identifier
        user: Current authenticated user
        db: Database session

    Returns:
        dict: Success message

    Raises:
        HTTPException: If role not found or deletion fails

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(delete_role)
        True
    """
    try:
        role_service = RoleService(db)
        success = await role_service.delete_role(role_id)

        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

        logger.info(f"Role deleted: {role_id} by {user['email']}")
        return {"message": "Role deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Role deletion failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete role")


# ===== User Role Assignment Endpoints =====


@router.post("/users/{user_email}/roles", response_model=UserRoleResponse)
@require_permission("admin.user_management")
async def assign_role_to_user(user_email: str, assignment_data: UserRoleAssignRequest, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Assign a role to a user.

    Args:
        user_email: User email address
        assignment_data: Role assignment data
        user: Current authenticated user
        db: Database session

    Returns:
        UserRoleResponse: Created role assignment

    Raises:
        HTTPException: If assignment fails

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(assign_role_to_user)
        True
    """
    try:
        role_service = RoleService(db)
        user_role = await role_service.assign_role_to_user(
            user_email=user_email, role_id=assignment_data.role_id, scope=assignment_data.scope, scope_id=assignment_data.scope_id, granted_by=user["email"], expires_at=assignment_data.expires_at
        )

        logger.info(f"Role assigned: {assignment_data.role_id} to {user_email} by {user['email']}")
        return UserRoleResponse.from_orm(user_role)

    except ValueError as e:
        logger.error(f"Role assignment validation error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Role assignment failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to assign role")


@router.get("/users/{user_email}/roles", response_model=List[UserRoleResponse])
@require_permission("admin.user_management")
async def get_user_roles(
    user_email: str,
    scope: Optional[str] = Query(None, description="Filter by scope"),
    active_only: bool = Query(True, description="Show only active assignments"),
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
):
    """Get roles assigned to a user.

    Args:
        user_email: User email address
        scope: Optional scope filter
        active_only: Whether to show only active assignments
        user: Current authenticated user
        db: Database session

    Returns:
        List[UserRoleResponse]: User's role assignments

    Raises:
        HTTPException: If role retrieval fails

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(get_user_roles)
        True
    """
    try:
        permission_service = PermissionService(db)
        user_roles = await permission_service.get_user_roles(user_email=user_email, scope=scope, include_expired=not active_only)

        return [UserRoleResponse.from_orm(user_role) for user_role in user_roles]

    except Exception as e:
        logger.error(f"Failed to get user roles for {user_email}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve user roles")


@router.delete("/users/{user_email}/roles/{role_id}")
@require_permission("admin.user_management")
async def revoke_user_role(
    user_email: str,
    role_id: str,
    scope: Optional[str] = Query(None, description="Scope filter"),
    scope_id: Optional[str] = Query(None, description="Scope ID filter"),
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
):
    """Revoke a role from a user.

    Args:
        user_email: User email address
        role_id: Role identifier
        scope: Optional scope filter
        scope_id: Optional scope ID filter
        user: Current authenticated user
        db: Database session

    Returns:
        dict: Success message

    Raises:
        HTTPException: If revocation fails

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(revoke_user_role)
        True
    """
    try:
        role_service = RoleService(db)
        success = await role_service.revoke_role_from_user(user_email=user_email, role_id=role_id, scope=scope, scope_id=scope_id)

        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role assignment not found")

        logger.info(f"Role revoked: {role_id} from {user_email} by {user['email']}")
        return {"message": "Role revoked successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Role revocation failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to revoke role")


# ===== Permission Checking Endpoints =====


@router.post("/permissions/check", response_model=PermissionCheckResponse)
@require_permission("admin.security_audit")
async def check_permission(check_data: PermissionCheckRequest, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Check if a user has specific permission.

    Args:
        check_data: Permission check request
        user: Current authenticated user
        db: Database session

    Returns:
        PermissionCheckResponse: Permission check result

    Raises:
        HTTPException: If permission check fails

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(check_permission)
        True
    """
    try:
        permission_service = PermissionService(db)
        granted = await permission_service.check_permission(
            user_email=check_data.user_email,
            permission=check_data.permission,
            resource_type=check_data.resource_type,
            resource_id=check_data.resource_id,
            team_id=check_data.team_id,
            ip_address=user.get("ip_address"),
            user_agent=user.get("user_agent"),
        )

        return PermissionCheckResponse(user_email=check_data.user_email, permission=check_data.permission, granted=granted, checked_at=datetime.now(tz=timezone.utc), checked_by=user["email"])

    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to check permission")


@router.get("/permissions/user/{user_email}", response_model=List[str])
@require_permission("admin.security_audit")
async def get_user_permissions(user_email: str, team_id: Optional[str] = Query(None, description="Team context"), user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Get all effective permissions for a user.

    Args:
        user_email: User email address
        team_id: Optional team context
        user: Current authenticated user
        db: Database session

    Returns:
        List[str]: User's effective permissions

    Raises:
        HTTPException: If retrieving user permissions fails

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(get_user_permissions)
        True
    """
    try:
        permission_service = PermissionService(db)
        permissions = await permission_service.get_user_permissions(user_email=user_email, team_id=team_id)

        return sorted(list(permissions))

    except Exception as e:
        logger.error(f"Failed to get user permissions for {user_email}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve user permissions")


@router.get("/permissions/available", response_model=PermissionListResponse)
async def get_available_permissions(user=Depends(get_current_user_with_permissions)):
    """Get all available permissions in the system.

    Args:
        user: Current authenticated user

    Returns:
        PermissionListResponse: Available permissions organized by resource type

    Raises:
        HTTPException: If retrieving available permissions fails
    """
    try:
        all_permissions = Permissions.get_all_permissions()
        permissions_by_resource = Permissions.get_permissions_by_resource()

        return PermissionListResponse(all_permissions=all_permissions, permissions_by_resource=permissions_by_resource, total_count=len(all_permissions))

    except Exception as e:
        logger.error(f"Failed to get available permissions: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve available permissions")


# ===== Self-Service Endpoints =====


@router.get("/my/roles", response_model=List[UserRoleResponse])
async def get_my_roles(user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Get current user's role assignments.

    Args:
        user: Current authenticated user
        db: Database session

    Returns:
        List[UserRoleResponse]: Current user's role assignments

    Raises:
        HTTPException: If retrieving user roles fails

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(get_my_roles)
        True
    """
    try:
        permission_service = PermissionService(db)
        user_roles = await permission_service.get_user_roles(user_email=user["email"], include_expired=False)

        return [UserRoleResponse.from_orm(user_role) for user_role in user_roles]

    except Exception as e:
        logger.error(f"Failed to get my roles for {user['email']}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve your roles")


@router.get("/my/permissions", response_model=List[str])
async def get_my_permissions(team_id: Optional[str] = Query(None, description="Team context"), user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Get current user's effective permissions.

    Args:
        team_id: Optional team context
        user: Current authenticated user
        db: Database session

    Returns:
        List[str]: Current user's effective permissions

    Raises:
        HTTPException: If retrieving user permissions fails

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(get_my_permissions)
        True
    """
    try:
        permission_service = PermissionService(db)
        permissions = await permission_service.get_user_permissions(user_email=user["email"], team_id=team_id)

        return sorted(list(permissions))

    except Exception as e:
        logger.error(f"Failed to get my permissions for {user['email']}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve your permissions")
