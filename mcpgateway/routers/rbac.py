# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/rbac.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

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
from typing import Dict, Generator, List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.common.query_params import QueryIdentifierDotted, QueryScopeId, QueryTeamContext
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.db import Permissions, SessionLocal
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_admin_permission, require_permission
from mcpgateway.schemas import (
    EntityRulesSummaryResponse,
    PermissionCheckRequest,
    PermissionCheckResponse,
    PermissionListResponse,
    RbacRuleCreateRequest,
    RbacRuleResponse,
    RbacRuleUpdateRequest,
    RoleCreateRequest,
    RoleResponse,
    RoleUpdateRequest,
    UserRoleAssignRequest,
    UserRoleResponse,
)
from mcpgateway.services.rule_catalog_service import RuleCatalogError, RuleCatalogProtectedError, RuleCatalogService
from mcpgateway.services.rule_provider import get_rule_provider as PermissionService
from mcpgateway.services.role_service import RoleService
from mcpgateway.utils.error_formatter import PublicValidationError, safe_error_detail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rbac", tags=["RBAC"])


def get_db() -> Generator[Session, None, None]:
    """Get database session for dependency injection.

    Commits the transaction on successful completion to avoid implicit rollbacks
    for read-only operations. Rolls back explicitly on exception.

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

        logger.info(f"Role created: {role.id} by {SecurityValidator.sanitize_log_message(user['email'])}")
        db.commit()
        db.close()
        return RoleResponse.model_validate(role)

    except PublicValidationError as e:
        logger.error("Role creation validation error: %s", SecurityValidator.sanitize_log_message(str(e)))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        logger.error("Role creation validation error: %s", SecurityValidator.sanitize_log_message(str(e)))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=safe_error_detail(e))
    except Exception as e:
        logger.error(f"Role creation failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create role")


@router.get("/roles", response_model=List[RoleResponse])
@require_permission("admin.user_management")
async def list_roles(
    scope: QueryIdentifierDotted = None,
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
        # Release transaction before response serialization
        db.commit()
        db.close()

        return [RoleResponse.model_validate(role) for role in roles]

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

        db.commit()
        db.close()
        return RoleResponse.model_validate(role)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get role %s: %s", SecurityValidator.sanitize_log_message(role_id), e)
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
        role = await role_service.update_role(role_id, **role_data.model_dump(exclude_unset=True))

        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

        logger.info("Role updated: %s by %s", SecurityValidator.sanitize_log_message(role_id), SecurityValidator.sanitize_log_message(user["email"]))
        db.commit()
        db.close()
        return RoleResponse.model_validate(role)

    except HTTPException:
        raise
    except PublicValidationError as e:
        logger.error("Role update validation error: %s", SecurityValidator.sanitize_log_message(str(e)))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        logger.error("Role update validation error: %s", SecurityValidator.sanitize_log_message(str(e)))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=safe_error_detail(e))
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

        logger.info("Role deleted: %s by %s", SecurityValidator.sanitize_log_message(role_id), SecurityValidator.sanitize_log_message(user["email"]))
        db.commit()
        db.close()
        return {"message": "Role deleted successfully"}

    except HTTPException:
        raise
    except PublicValidationError as e:
        logger.error("Role deletion validation error: %s", SecurityValidator.sanitize_log_message(str(e)))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        logger.error("Role deletion validation error: %s", SecurityValidator.sanitize_log_message(str(e)))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=safe_error_detail(e))
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

        logger.info(
            "Role assigned: %s to %s by %s",
            SecurityValidator.sanitize_log_message(assignment_data.role_id),
            SecurityValidator.sanitize_log_message(user_email),
            SecurityValidator.sanitize_log_message(user["email"]),
        )
        db.commit()
        db.close()
        return UserRoleResponse.model_validate(user_role)

    except PublicValidationError as e:
        logger.error("Role assignment validation error: %s", SecurityValidator.sanitize_log_message(str(e)))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        logger.error("Role assignment validation error: %s", SecurityValidator.sanitize_log_message(str(e)))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=safe_error_detail(e))
    except Exception as e:
        logger.error(f"Role assignment failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to assign role")


@router.get("/users/{user_email}/roles", response_model=List[UserRoleResponse])
@require_permission("admin.user_management")
async def get_user_roles(
    user_email: str,
    scope: QueryIdentifierDotted = None,
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

        result = [UserRoleResponse.model_validate(user_role) for user_role in user_roles]
        db.commit()
        db.close()
        return result

    except Exception as e:
        logger.error(f"Failed to get user roles for {SecurityValidator.sanitize_log_message(user_email)}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve user roles")


@router.delete("/users/{user_email}/roles/{role_id}")
@require_permission("admin.user_management")
async def revoke_user_role(
    user_email: str,
    role_id: str,
    scope: QueryIdentifierDotted = None,
    scope_id: QueryScopeId = None,
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

        logger.info(
            "Role revoked: %s from %s by %s",
            SecurityValidator.sanitize_log_message(role_id),
            SecurityValidator.sanitize_log_message(user_email),
            SecurityValidator.sanitize_log_message(user["email"]),
        )
        db.commit()
        db.close()
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

        db.commit()
        db.close()
        return PermissionCheckResponse(user_email=check_data.user_email, permission=check_data.permission, granted=granted, checked_at=datetime.now(tz=timezone.utc), checked_by=user["email"])

    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to check permission")


@router.get("/permissions/user/{user_email}", response_model=List[str])
@require_permission("admin.security_audit")
async def get_user_permissions(
    user_email: str,
    team_id: QueryTeamContext = None,
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
):
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

        result = sorted(list(permissions))
        db.commit()
        db.close()
        return result

    except Exception as e:
        logger.error(f"Failed to get user permissions for {SecurityValidator.sanitize_log_message(user_email)}: {e}")
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

        result = [UserRoleResponse.model_validate(user_role) for user_role in user_roles]
        db.commit()
        db.close()
        return result

    except Exception as e:
        logger.error(f"Failed to get my roles for {SecurityValidator.sanitize_log_message(user['email'])}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve your roles")


@router.get("/my/permissions", response_model=List[str])
async def get_my_permissions(
    team_id: QueryTeamContext = None,
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
):
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
        permissions = await permission_service.get_user_permissions(user_email=user["email"], team_id=team_id, token_teams=user.get("token_teams"))

        result = sorted(list(permissions))
        db.commit()
        db.close()
        return result

    except Exception as e:
        logger.error(f"Failed to get my permissions for {SecurityValidator.sanitize_log_message(user['email'])}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve your permissions")


@router.get("/rules", response_model=List[RbacRuleResponse])
async def list_rules(capability_type: Optional[str] = Query(None), capability_id: Optional[str] = Query(None), user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """List rule catalog rules.

    Args:
        capability_type: Filter by capability type when given.
        capability_id: Filter by entity id when given.
        user: Current authenticated user.
        db: Database session.

    Returns:
        List[RbacRuleResponse]: Rules ordered by priority then name.

    Raises:
        HTTPException: When the query fails.
    """
    try:
        catalog = RuleCatalogService(db)
        rules = catalog.list_rules(capability_type=capability_type, capability_id=capability_id)
        db.commit()
        db.close()
        return [RbacRuleResponse.model_validate(rule) for rule in rules]
    except Exception as e:
        logger.error(f"Failed to list rbac rules: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list rules")


@router.get("/rules/entity-summary", response_model=EntityRulesSummaryResponse)
async def get_entity_rules_summary(capability_type: str = Query(...), capability_id: str = Query(...), user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Return the rules that govern one entity.

    Args:
        capability_type: Capability type of the entity.
        capability_id: Entity identifier.
        user: Current authenticated user.
        db: Database session.

    Returns:
        EntityRulesSummaryResponse: Entity rules, type-inherited rules, and
        the built-in defaults for the capability type.

    Raises:
        HTTPException: When the capability type is unknown or the query fails.
    """
    try:
        catalog = RuleCatalogService(db)
        inherited = [r for r in catalog.list_rules(capability_type=capability_type) if r.capability_id is None]
        scoped = [r for r in catalog.list_rules(capability_type=capability_type, capability_id=capability_id) if r.capability_id is not None]
        defaults: Dict[str, List[str]] = {}
        from mcpgateway.services.rule_catalog_service import DEFAULT_ROLE_DEFINITIONS  # pylint: disable=import-outside-toplevel

        for role in DEFAULT_ROLE_DEFINITIONS:
            permissions = [
                p
                for p in role.get("permissions", [])
                if p == "*"
                or p.replace(":", ".").split(".")[0]
                == {"tool": "tools", "resource": "resources", "prompt": "prompts", "server": "servers", "gateway": "gateways", "a2a_agent": "a2a", "route": ""}.get(capability_type, "")
            ]
            if permissions:
                defaults[role["name"]] = permissions
        db.commit()
        db.close()
        return EntityRulesSummaryResponse(rules=[RbacRuleResponse.model_validate(r) for r in scoped], inherited=[RbacRuleResponse.model_validate(r) for r in inherited], defaults=defaults)
    except Exception as e:
        logger.error(f"Failed to build entity rules summary: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to build entity rules summary")


@router.post("/rules", response_model=RbacRuleResponse, status_code=status.HTTP_201_CREATED)
@require_permission(Permissions.RBAC_RULES_MANAGE)
async def create_rule(rule_data: RbacRuleCreateRequest, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Create a rule catalog rule.

    Args:
        rule_data: Rule creation payload.
        user: Current authenticated user.
        db: Database session.

    Returns:
        RbacRuleResponse: The created rule.

    Raises:
        HTTPException: When the payload is invalid or the name duplicates.
    """
    try:
        catalog = RuleCatalogService(db)
        rule = catalog.create_rule(
            name=rule_data.name,
            description=rule_data.description,
            capability_type=rule_data.capability_type,
            capability_id=rule_data.capability_id,
            permission=rule_data.permission,
            phase=rule_data.phase,
            predicate=rule_data.predicate,
            effect=rule_data.effect,
            priority=rule_data.priority,
            created_by=user["email"],
        )
        logger.info(f"RBAC rule created: {rule.id} by {SecurityValidator.sanitize_log_message(user['email'])}")
        db.commit()
        db.close()
        return RbacRuleResponse.model_validate(rule)
    except RuleCatalogError as e:
        logger.error("RBAC rule creation validation error: %s", SecurityValidator.sanitize_log_message(str(e)))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.error(f"RBAC rule creation failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create rule")


@router.patch("/rules/{rule_id}", response_model=RbacRuleResponse)
@require_permission(Permissions.RBAC_RULES_MANAGE)
async def update_rule(rule_id: str, rule_data: RbacRuleUpdateRequest, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Update a rule catalog rule.

    Args:
        rule_id: Rule identifier.
        rule_data: Rule update payload.
        user: Current authenticated user.
        db: Database session.

    Returns:
        RbacRuleResponse: The updated rule.

    Raises:
        HTTPException: When the rule is absent or the payload is invalid.
    """
    fields = rule_data.model_dump(exclude_unset=True)
    try:
        catalog = RuleCatalogService(db)
        rule = catalog.update_rule(rule_id, **fields)
        logger.info(f"RBAC rule updated: {rule_id} by {SecurityValidator.sanitize_log_message(user['email'])}")
        db.commit()
        db.close()
        return RbacRuleResponse.model_validate(rule)
    except RuleCatalogError as e:
        message = str(e)
        code = status.HTTP_404_NOT_FOUND if "not found" in message else status.HTTP_422_UNPROCESSABLE_ENTITY
        logger.error("RBAC rule update error: %s", SecurityValidator.sanitize_log_message(message))
        raise HTTPException(status_code=code, detail=message)
    except Exception as e:
        logger.error(f"RBAC rule update failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update rule")


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission(Permissions.RBAC_RULES_MANAGE)
async def delete_rule(rule_id: str, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Delete a rule catalog rule.

    Args:
        rule_id: Rule identifier.
        user: Current authenticated user.
        db: Database session.

    Raises:
        HTTPException: When the rule is absent or protected.
    """
    try:
        catalog = RuleCatalogService(db)
        catalog.delete_rule(rule_id)
        logger.info(f"RBAC rule deleted: {rule_id} by {SecurityValidator.sanitize_log_message(user['email'])}")
        db.commit()
        db.close()
    except RuleCatalogProtectedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except RuleCatalogError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"RBAC rule deletion failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete rule")
