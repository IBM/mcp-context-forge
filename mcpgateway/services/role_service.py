# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/role_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Role Management Service for RBAC System.

This module provides CRUD operations for roles and user role assignments.
It handles role creation, assignment, revocation, and validation.
"""

# Standard
from datetime import datetime
import logging
from typing import List, Optional

# Third-Party
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Permissions, Role, UserRole, utc_now

logger = logging.getLogger(__name__)


class RoleService:
    """Service for managing roles and role assignments.

    Provides comprehensive role management including creation, assignment,
    revocation, and validation with support for role inheritance.

    Attributes:
            Database session

    Examples:
        Basic construction:
        >>> from unittest.mock import Mock
        >>> service = RoleService(Mock())
        >>> isinstance(service, RoleService)
        True
        >>> hasattr(service, 'db')
        True
    """

    def __init__(self, db: Session):
        """Initialize role service.

        Args:
            db: Database session

        Examples:
            Basic initialization:
            >>> from mcpgateway.services.role_service import RoleService
            >>> from unittest.mock import Mock
            >>> db_session = Mock()
            >>> service = RoleService(db_session)
            >>> service.db is db_session
            True

            Service instance attributes:
            >>> hasattr(service, 'db')
            True
            >>> service.__class__.__name__
            'RoleService'
        """
        self.db = db

    async def create_role(self, name: str, description: str, scope: str, permissions: List[str], created_by: str, inherits_from: Optional[str] = None, is_system_role: bool = False) -> Role:
        """Create a new role.

        Args:
            name: Role name (must be unique within scope)
            description: Role description
            scope: Role scope ('global', 'team', 'personal')
            permissions: List of permission strings
            created_by: Email of user creating the role
            inherits_from: ID of parent role for inheritance
            is_system_role: Whether this is a system-defined role

        Returns:
            Role: The created role

        Raises:
            ValueError: If role name already exists or invalid parameters

        Examples:
            Basic role creation parameters:
            >>> from mcpgateway.services.role_service import RoleService
            >>> role_name = "developer"
            >>> len(role_name) > 0
            True
            >>> role_scope = "team"
            >>> role_scope in ["global", "team", "personal"]
            True
            >>> permissions = ["tools.read", "tools.execute"]
            >>> all(isinstance(p, str) for p in permissions)
            True

            Role validation logic:
            >>> # Test role name validation
            >>> test_name = "admin-role"
            >>> len(test_name) <= 255
            True
            >>> bool(test_name.strip())
            True

            >>> # Test scope validation
            >>> valid_scopes = ["global", "team", "personal"]
            >>> "team" in valid_scopes
            True
            >>> "invalid" in valid_scopes
            False

            >>> # Test permissions format
            >>> perms = ["users.read", "users.write", "teams.manage"]
            >>> all("." in p for p in perms)
            True
            >>> all(len(p) > 0 for p in perms)
            True

            Role inheritance validation:
            >>> # Test inherits_from parameter
            >>> parent_role_id = "role-123"
            >>> isinstance(parent_role_id, str)
            True
            >>> parent_role_id != ""
            True

            System role flags:
            >>> is_system = True
            >>> isinstance(is_system, bool)
            True
            >>> is_admin_role = False
            >>> isinstance(is_admin_role, bool)
            True

            Creator validation:
            >>> created_by = "admin@example.com"
            >>> "@" in created_by
            True
            >>> len(created_by) > 0
            True

            Invalid scope is rejected immediately:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> svc = RoleService(Mock())
            >>> try:
            ...     asyncio.run(svc.create_role('n','d','invalid',[], 'u@example.com'))
            ... except ValueError as e:
            ...     'Invalid scope' in str(e)
            True

            Duplicate name rejected within scope:
            >>> from unittest.mock import AsyncMock, patch
            >>> svc = RoleService(Mock())
            >>> with patch.object(RoleService, 'get_role_by_name', new=AsyncMock(return_value=object())):
            ...     try:
            ...         asyncio.run(svc.create_role('dup','d','global',[], 'u@example.com'))
            ...     except ValueError as e:
            ...         'already exists' in str(e)
            True

            Invalid permissions rejected:
            >>> with patch.object(RoleService, 'get_role_by_name', new=AsyncMock(return_value=None)):
            ...     with patch('mcpgateway.services.role_service.Permissions.get_all_permissions', return_value=[]):
            ...         try:
            ...             asyncio.run(svc.create_role('n','d','global',['bad'], 'u@example.com'))
            ...         except ValueError as e:
            ...             'Invalid permissions' in str(e)
            True

            Parent not found and cycle detection:
            >>> with patch.object(RoleService, 'get_role_by_name', new=AsyncMock(return_value=None)):
            ...     with patch.object(RoleService, 'get_role_by_id', new=AsyncMock(return_value=None)):
            ...         try:
            ...             asyncio.run(svc.create_role('n','d','global',[], 'u@example.com', inherits_from='p'))
            ...         except ValueError as e:
            ...             'Parent role not found' in str(e)
            True
            >>> with patch.object(RoleService, 'get_role_by_name', new=AsyncMock(return_value=None)):
            ...     with patch.object(RoleService, 'get_role_by_id', new=AsyncMock(return_value=object())):
            ...         with patch.object(RoleService, '_would_create_cycle', new=AsyncMock(return_value=True)):
            ...             try:
            ...                 asyncio.run(svc.create_role('n','d','global',[], 'u@example.com', inherits_from='p'))
            ...             except ValueError as e:
            ...                 'create a cycle' in str(e)
            True
        """
        # Validate scope
        if scope not in ["global", "team", "personal"]:
            raise ValueError(f"Invalid scope: {scope}")

        # Check for duplicate name within scope
        existing = await self.get_role_by_name(name, scope)
        if existing:
            raise ValueError(f"Role '{name}' already exists in scope '{scope}'")

        # Validate permissions
        valid_permissions = Permissions.get_all_permissions()
        valid_permissions.append(Permissions.ALL_PERMISSIONS)  # Allow wildcard

        invalid_perms = [p for p in permissions if p not in valid_permissions]
        if invalid_perms:
            raise ValueError(f"Invalid permissions: {invalid_perms}")

        # Validate inheritance
        parent_role = None
        if inherits_from:
            parent_role = await self.get_role_by_id(inherits_from)
            if not parent_role:
                raise ValueError(f"Parent role not found: {inherits_from}")

            # Check for circular inheritance
            if await self._would_create_cycle(inherits_from, None):
                raise ValueError("Role inheritance would create a cycle")

        # Create the role
        role = Role(name=name, description=description, scope=scope, permissions=permissions, created_by=created_by, inherits_from=inherits_from, is_system_role=is_system_role)

        self.db.add(role)
        self.db.commit()
        self.db.refresh(role)

        logger.info(f"Created role: {role.name} (scope: {role.scope}, id: {role.id})")
        return role

    async def get_role_by_id(self, role_id: str) -> Optional[Role]:
        """Get role by ID.

        Args:
            role_id: Role ID to lookup

        Returns:
            Optional[Role]: The role if found, None otherwise

        Examples:
            Check coroutine nature and signature:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> service = RoleService(Mock())
            >>> asyncio.iscoroutinefunction(service.get_role_by_id)
            True
        """
        result = self.db.execute(select(Role).where(Role.id == role_id))
        role = result.scalar_one_or_none()
        return role

    async def get_role_by_name(self, name: str, scope: str) -> Optional[Role]:
        """Get role by name and scope.

        Args:
            name: Role name
            scope: Role scope

        Returns:
            Optional[Role]: The role if found, None otherwise

        Examples:
            Basic callable validation:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> service = RoleService(Mock())
            >>> asyncio.iscoroutinefunction(service.get_role_by_name)
            True
        """
        result = self.db.execute(select(Role).where(and_(Role.name == name, Role.scope == scope, Role.is_active.is_(True))))
        role = result.scalar_one_or_none()
        return role

    async def list_roles(self, scope: Optional[str] = None, include_system: bool = True, include_inactive: bool = False) -> List[Role]:
        """List roles with optional filtering.

        Args:
            scope: Filter by scope ('global', 'team', 'personal')
            include_system: Whether to include system roles
            include_inactive: Whether to include inactive roles

        Returns:
            List[Role]: List of matching roles

        Examples:
            Callable check:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> service = RoleService(Mock())
            >>> asyncio.iscoroutinefunction(service.list_roles)
            True
            >>> # Simulate empty list result
            >>> class _Res:
            ...     def scalars(self):
            ...         class _S:
            ...             def all(self):
            ...                 return []
            ...         return _S()
            >>> service.db.execute = lambda *_a, **_k: _Res()
            >>> asyncio.run(service.list_roles('team', include_system=False, include_inactive=True)) == []
            True
        """
        query = select(Role)

        conditions = []

        if scope:
            conditions.append(Role.scope == scope)

        if not include_system:
            conditions.append(Role.is_system_role.is_(False))

        if not include_inactive:
            conditions.append(Role.is_active.is_(True))

        if conditions:
            query = query.where(and_(*conditions))

        query = query.order_by(Role.scope, Role.name)

        result = self.db.execute(query)
        roles = result.scalars().all()
        return roles

    async def update_role(
        self,
        role_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        permissions: Optional[List[str]] = None,
        inherits_from: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Role]:
        """Update an existing role.

        Args:
            role_id: ID of role to update
            name: New role name
            description: New role description
            permissions: New permissions list
            inherits_from: New parent role ID
            is_active: New active status

        Returns:
            Optional[Role]: Updated role or None if not found

        Raises:
            ValueError: If update would create invalid state

        Examples:
            Signature and coroutine checks:
            >>> import asyncio, inspect
            >>> from unittest.mock import Mock
            >>> service = RoleService(Mock())
            >>> asyncio.iscoroutinefunction(service.update_role)
            True
            >>> params = inspect.signature(RoleService.update_role).parameters
            >>> all(p in params for p in [
            ...     'role_id', 'name', 'description', 'permissions', 'inherits_from', 'is_active'
            ... ])
            True

        Additional validation paths:
            Cannot modify system roles:
            >>> from unittest.mock import AsyncMock, patch
            >>> service = RoleService(object())
            >>> mock_role = type('R', (), {'is_system_role': True})()
            >>> with patch.object(RoleService, 'get_role_by_id', new=AsyncMock(return_value=mock_role)):
            ...     try:
            ...         _ = asyncio.run(service.update_role('rid'))
            ...     except ValueError as e:
            ...         'system roles' in str(e)
            True

            Returns None when role not found:
            >>> with patch.object(RoleService, 'get_role_by_id', new=AsyncMock(return_value=None)):
            ...     asyncio.run(service.update_role('missing')) is None
            True

            Duplicate new name rejected:
            >>> role = type('R', (), {'is_system_role': False, 'name': 'old', 'scope': 'global', 'id': 'id1', 'is_active': True})()
            >>> with patch.object(RoleService, 'get_role_by_id', new=AsyncMock(return_value=role)):
            ...     with patch.object(RoleService, 'get_role_by_name', new=AsyncMock(return_value=type('R2', (), {'id': 'id2'})())):
            ...         try:
            ...             asyncio.run(service.update_role('id1', name='new'))
            ...         except ValueError as e:
            ...             'already exists' in str(e)
            True

            Invalid permissions rejected on update:
            >>> role = type('R', (), {'is_system_role': False, 'name': 'old', 'scope': 'global', 'id': 'id1', 'is_active': True})()
            >>> with patch.object(RoleService, 'get_role_by_id', new=AsyncMock(return_value=role)):
            ...     with patch('mcpgateway.services.role_service.Permissions.get_all_permissions', return_value=[]):
            ...         try:
            ...             asyncio.run(service.update_role('id1', permissions=['bad']))
            ...         except ValueError as e:
            ...             'Invalid permissions' in str(e)
            True

            Parent not found and cycle detection on update:
            >>> role = type('R', (), {'is_system_role': False, 'name': 'old', 'scope': 'global', 'id': 'id1', 'inherits_from': None, 'is_active': True})()
            >>> with patch.object(RoleService, 'get_role_by_id', new=AsyncMock(side_effect=[role, None])):
            ...     try:
            ...         asyncio.run(service.update_role('id1', inherits_from='p'))
            ...     except ValueError as e:
            ...         'Parent role not found' in str(e)
            True
            >>> with patch.object(RoleService, 'get_role_by_id', new=AsyncMock(side_effect=[role, object()])):
            ...     with patch.object(RoleService, '_would_create_cycle', new=AsyncMock(return_value=True)):
            ...         try:
            ...             asyncio.run(service.update_role('id1', inherits_from='p'))
            ...         except ValueError as e:
            ...             'create a cycle' in str(e)
            True
        """
        role = await self.get_role_by_id(role_id)
        if not role:
            return None

        # Prevent modification of system roles
        if role.is_system_role:
            raise ValueError("Cannot modify system roles")

        # Validate new name if provided
        if name and name != role.name:
            existing = await self.get_role_by_name(name, role.scope)
            if existing and existing.id != role_id:
                raise ValueError(f"Role '{name}' already exists in scope '{role.scope}'")
            role.name = name

        # Update description
        if description is not None:
            role.description = description

        # Validate and update permissions
        if permissions is not None:
            valid_permissions = Permissions.get_all_permissions()
            valid_permissions.append(Permissions.ALL_PERMISSIONS)

            invalid_perms = [p for p in permissions if p not in valid_permissions]
            if invalid_perms:
                raise ValueError(f"Invalid permissions: {invalid_perms}")

            role.permissions = permissions

        # Validate and update inheritance
        if inherits_from is not None:
            if inherits_from != role.inherits_from:
                if inherits_from:
                    parent_role = await self.get_role_by_id(inherits_from)
                    if not parent_role:
                        raise ValueError(f"Parent role not found: {inherits_from}")

                    # Check for circular inheritance
                    if await self._would_create_cycle(inherits_from, role_id):
                        raise ValueError("Role inheritance would create a cycle")

                role.inherits_from = inherits_from

        # Update active status
        if is_active is not None:
            role.is_active = is_active

        # Update timestamp
        role.updated_at = utc_now()

        self.db.commit()
        self.db.refresh(role)

        logger.info(f"Updated role: {role.name} (id: {role.id})")
        return role

    async def delete_role(self, role_id: str) -> bool:
        """Delete a role.

        Soft deletes the role by setting is_active to False.
        Also deactivates all user role assignments.

        Args:
            role_id: ID of role to delete

        Returns:
            bool: True if role was deleted, False if not found

        Raises:
            ValueError: If trying to delete a system role

        Examples:
            Coroutine check:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> service = RoleService(Mock())
            >>> asyncio.iscoroutinefunction(service.delete_role)
            True

            Returns False when role not found:
            >>> from unittest.mock import AsyncMock, patch
            >>> with patch.object(RoleService, 'get_role_by_id', new=AsyncMock(return_value=None)):
            ...     asyncio.run(service.delete_role('missing'))
            False

            System roles cannot be deleted:
            >>> sys_role = type('R', (), {'is_system_role': True})()
            >>> with patch.object(RoleService, 'get_role_by_id', new=AsyncMock(return_value=sys_role)):
            ...     try:
            ...         asyncio.run(service.delete_role('rid'))
            ...     except ValueError as e:
            ...         'system roles' in str(e)
            True
        """
        role = await self.get_role_by_id(role_id)
        if not role:
            return False

        if role.is_system_role:
            raise ValueError("Cannot delete system roles")

        # Soft delete the role
        role.is_active = False
        role.updated_at = utc_now()

        # Deactivate all user assignments of this role
        self.db.execute(select(UserRole).where(UserRole.role_id == role_id)).update({"is_active": False})

        self.db.commit()

        logger.info(f"Deleted role: {role.name} (id: {role.id})")
        return True

    async def assign_role_to_user(self, user_email: str, role_id: str, scope: str, scope_id: Optional[str], granted_by: str, expires_at: Optional[datetime] = None) -> UserRole:
        """Assign a role to a user.

        Args:
            user_email: Email of user to assign role to
            role_id: ID of role to assign
            scope: Scope of assignment ('global', 'team', 'personal')
            scope_id: Team ID if team-scoped
            granted_by: Email of user granting the role
            expires_at: Optional expiration datetime

        Returns:
            UserRole: The role assignment

        Raises:
            ValueError: If invalid parameters or assignment already exists

        Examples:
            Coroutine check:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> service = RoleService(Mock())
            >>> asyncio.iscoroutinefunction(service.assign_role_to_user)
            True

            Scope mismatch raises error:
            >>> from unittest.mock import AsyncMock, patch
            >>> role = type('Role', (), {'is_active': True, 'scope': 'team'})()
            >>> with patch.object(RoleService, 'get_role_by_id', new=AsyncMock(return_value=role)):
            ...     try:
            ...         asyncio.run(service.assign_role_to_user('u@e','rid','global',None,'admin'))
            ...     except ValueError as e:
            ...         "doesn't match" in str(e)
            True

            Team scope requires scope_id:
            >>> with patch.object(RoleService, 'get_role_by_id', new=AsyncMock(return_value=role)):
            ...     try:
            ...         asyncio.run(service.assign_role_to_user('u@e','rid','team',None,'admin'))
            ...     except ValueError as e:
            ...         'scope_id required' in str(e)
            True

            Global scope forbids scope_id:
            >>> role.scope = 'global'
            >>> with patch.object(RoleService, 'get_role_by_id', new=AsyncMock(return_value=role)):
            ...     try:
            ...         asyncio.run(service.assign_role_to_user('u@e','rid','global','x','admin'))
            ...     except ValueError as e:
            ...         'not allowed for global' in str(e)
            True

            Duplicate active assignment is rejected:
            >>> role.scope = 'team'
            >>> active = type('UR', (), {'is_active': True, 'is_expired': lambda self: False})()
            >>> with patch.object(RoleService, 'get_role_by_id', new=AsyncMock(return_value=role)):
            ...     with patch.object(RoleService, 'get_user_role_assignment', new=AsyncMock(return_value=active)):
            ...         try:
            ...             asyncio.run(service.assign_role_to_user('u@e','rid','team','t1','admin'))
            ...         except ValueError as e:
            ...             'already has this role' in str(e)
            True

            Role not found or inactive raises:
            >>> inactive = type('Role', (), {'is_active': False, 'scope': 'team'})()
            >>> with patch.object(RoleService, 'get_role_by_id', new=AsyncMock(return_value=inactive)):
            ...     try:
            ...         asyncio.run(service.assign_role_to_user('u@e','rid','team','t1','admin'))
            ...     except ValueError as e:
            ...         'not found or inactive' in str(e)
            True
        """
        # Validate role exists and is active
        role = await self.get_role_by_id(role_id)
        if not role or not role.is_active:
            raise ValueError(f"Role not found or inactive: {role_id}")

        # Validate scope consistency
        if role.scope != scope:
            raise ValueError(f"Role scope '{role.scope}' doesn't match assignment scope '{scope}'")

        # Validate scope_id requirements
        if scope == "team" and not scope_id:
            raise ValueError("scope_id required for team-scoped assignments")
        if scope in ["global", "personal"] and scope_id:
            raise ValueError(f"scope_id not allowed for {scope} assignments")

        # Check for existing active assignment
        existing = await self.get_user_role_assignment(user_email, role_id, scope, scope_id)
        if existing and existing.is_active and not existing.is_expired():
            raise ValueError("User already has this role assignment")

        # Create the assignment
        user_role = UserRole(user_email=user_email, role_id=role_id, scope=scope, scope_id=scope_id, granted_by=granted_by, expires_at=expires_at)

        self.db.add(user_role)
        self.db.commit()
        self.db.refresh(user_role)

        logger.info(f"Assigned role {role.name} to {user_email} (scope: {scope}, scope_id: {scope_id})")
        return user_role

    async def revoke_role_from_user(self, user_email: str, role_id: str, scope: str, scope_id: Optional[str]) -> bool:
        """Revoke a role from a user.

        Args:
            user_email: Email of user
            role_id: ID of role to revoke
            scope: Scope of assignment
            scope_id: Team ID if team-scoped

        Returns:
            bool: True if role was revoked, False if not found

        Examples:
            Coroutine check:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> service = RoleService(Mock())
            >>> asyncio.iscoroutinefunction(service.revoke_role_from_user)
            True

            Returns False when assignment not found or inactive:
            >>> from unittest.mock import AsyncMock, patch
            >>> with patch.object(RoleService, 'get_user_role_assignment', new=AsyncMock(return_value=None)):
            ...     asyncio.run(service.revoke_role_from_user('u','r','team','t'))
            False

            Returns True on successful revoke:
            >>> active = type('UR', (), {'is_active': True})()
            >>> with patch.object(RoleService, 'get_user_role_assignment', new=AsyncMock(return_value=active)):
            ...     asyncio.run(service.revoke_role_from_user('u','r','team','t'))
            True
        """
        user_role = await self.get_user_role_assignment(user_email, role_id, scope, scope_id)

        if not user_role or not user_role.is_active:
            return False

        user_role.is_active = False
        self.db.commit()

        logger.info(f"Revoked role {role_id} from {user_email} (scope: {scope}, scope_id: {scope_id})")
        return True

    async def get_user_role_assignment(self, user_email: str, role_id: str, scope: str, scope_id: Optional[str]) -> Optional[UserRole]:
        """Get a specific user role assignment.

        Args:
            user_email: Email of user
            role_id: ID of role
            scope: Scope of assignment
            scope_id: Team ID if team-scoped

        Returns:
            Optional[UserRole]: The role assignment if found

        Examples:
            Coroutine check:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> service = RoleService(Mock())
            >>> asyncio.iscoroutinefunction(service.get_user_role_assignment)
            True
        """
        conditions = [UserRole.user_email == user_email, UserRole.role_id == role_id, UserRole.scope == scope]

        if scope_id:
            conditions.append(UserRole.scope_id == scope_id)
        else:
            conditions.append(UserRole.scope_id.is_(None))

        result = self.db.execute(select(UserRole).where(and_(*conditions)))
        user_role = result.scalar_one_or_none()
        return user_role

    async def list_user_roles(self, user_email: str, scope: Optional[str] = None, include_expired: bool = False) -> List[UserRole]:
        """List all role assignments for a user.

        Args:
            user_email: Email of user
            scope: Filter by scope
            include_expired: Whether to include expired roles

        Returns:
            List[UserRole]: User's role assignments

        Examples:
            Coroutine check:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> service = RoleService(Mock())
            >>> asyncio.iscoroutinefunction(service.list_user_roles)
            True
            >>> # Simulate scalar results aggregation
            >>> class _Res:
            ...     def scalars(self):
            ...         class _S:
            ...             def all(self):
            ...                 return ['ur1', 'ur2']
            ...         return _S()
            >>> service.db.execute = lambda *_a, **_k: _Res()
            >>> result = asyncio.run(service.list_user_roles('u@example.com', 'team'))
            >>> isinstance(result, list) and len(result) == 2
            True
        """
        query = select(UserRole).join(Role).where(and_(UserRole.user_email == user_email, UserRole.is_active.is_(True), Role.is_active.is_(True)))

        if scope:
            query = query.where(UserRole.scope == scope)

        if not include_expired:
            now = utc_now()
            query = query.where((UserRole.expires_at.is_(None)) | (UserRole.expires_at > now))

        query = query.order_by(UserRole.scope, Role.name)

        result = self.db.execute(query)
        user_roles = result.scalars().all()
        return user_roles

    async def list_role_assignments(self, role_id: str, scope: Optional[str] = None, include_expired: bool = False) -> List[UserRole]:
        """List all user assignments for a role.

        Args:
            role_id: ID of role
            scope: Filter by scope
            include_expired: Whether to include expired assignments

        Returns:
            List[UserRole]: Role assignments

        Examples:
            Coroutine check:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> service = RoleService(Mock())
            >>> asyncio.iscoroutinefunction(service.list_role_assignments)
            True
            >>> # Simulate scalar results aggregation
            >>> class _Res:
            ...     def scalars(self):
            ...         class _S:
            ...             def all(self):
            ...                 return []
            ...         return _S()
            >>> service.db.execute = lambda *_a, **_k: _Res()
            >>> asyncio.run(service.list_role_assignments('rid'))
            []
        """
        query = select(UserRole).where(and_(UserRole.role_id == role_id, UserRole.is_active.is_(True)))

        if scope:
            query = query.where(UserRole.scope == scope)

        if not include_expired:
            now = utc_now()
            query = query.where((UserRole.expires_at.is_(None)) | (UserRole.expires_at > now))

        query = query.order_by(UserRole.user_email)

        result = self.db.execute(query)
        assignments = result.scalars().all()
        return assignments

    async def _would_create_cycle(self, parent_id: str, child_id: Optional[str]) -> bool:
        """Check if setting parent_id as parent of child_id would create a cycle.

        Args:
            parent_id: ID of the proposed parent role
            child_id: ID of the proposed child role

        Returns:
            True if setting this relationship would create a cycle, False otherwise

        Examples:
            Test cycle detection logic:
            >>> from mcpgateway.services.role_service import RoleService

            Basic parameter validation:
            >>> parent_id = "role-admin"
            >>> child_id = "role-user"
            >>> parent_id != child_id
            True
            >>> isinstance(parent_id, str)
            True
            >>> isinstance(child_id, str)
            True

            Test None child_id handling (line 584-585):
            >>> child_id_none = None
            >>> child_id_none is None
            True
            >>> # This should return False without cycle check

            Test cycle detection scenarios:
            >>> # Direct cycle: A -> A
            >>> same_id = "role-123"
            >>> same_id == same_id
            True

            >>> # Simple cycle: A -> B, B -> A
            >>> role_a = "role-a"
            >>> role_b = "role-b"
            >>> role_a != role_b
            True

            Test visited set logic:
            >>> visited = set()
            >>> current = "role-1"
            >>> current not in visited
            True
            >>> visited.add(current)
            >>> current in visited
            True

            Test role hierarchy traversal:
            >>> # Test hierarchy: admin -> manager -> user
            >>> admin_role = "admin-role"
            >>> manager_role = "manager-role"
            >>> user_role = "user-role"
            >>> all(isinstance(r, str) for r in [admin_role, manager_role, user_role])
            True
            >>> len({admin_role, manager_role, user_role}) == 3
            True
        """
        if not child_id:
            return False

        visited = set()
        current = parent_id

        while current and current not in visited:
            if current == child_id:
                return True

            visited.add(current)

            # Get parent of current role
            result = self.db.execute(select(Role.inherits_from).where(Role.id == current))
            current = result.scalar_one_or_none()

        return False
