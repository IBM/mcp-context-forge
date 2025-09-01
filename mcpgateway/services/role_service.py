# -*- coding: utf-8 -*-
"""Role Management Service for RBAC System.

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
        Create a role::

            service = RoleService(db_session)
            role = await service.create_role(
                name="team_admin",
                description="Team administrator",
                scope="team",
                permissions=["teams.manage_members"],
                created_by="admin@example.com"
            )
            # role.name -> 'team_admin'
    """

    def __init__(self, db: Session):
        """Initialize role service.

        Args:
            db: Database session
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
                service = RoleService(db)
                role = await service.create_role(
            ...     name="developer",
            ...     description="Software developer role",
            ...     scope="team",
            ...     permissions=["tools.read", "tools.execute"],
            ...     created_by="admin@example.com"
            ... )
                role.scope
            'team'
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
                service = RoleService(db)
                role = await service.get_role_by_id("role-123")
                role.name if role else None
            'admin'
        """
        result = self.db.execute(select(Role).where(Role.id == role_id))
        return result.scalar_one_or_none()

    async def get_role_by_name(self, name: str, scope: str) -> Optional[Role]:
        """Get role by name and scope.

        Args:
            name: Role name
            scope: Role scope

        Returns:
            Optional[Role]: The role if found, None otherwise

        Examples:
                service = RoleService(db)
                role = await service.get_role_by_name("admin", "global")
                role.scope if role else None
            'global'
        """
        result = self.db.execute(select(Role).where(and_(Role.name == name, Role.scope == scope, Role.is_active.is_(True))))
        return result.scalar_one_or_none()

    async def list_roles(self, scope: Optional[str] = None, include_system: bool = True, include_inactive: bool = False) -> List[Role]:
        """List roles with optional filtering.

        Args:
            scope: Filter by scope ('global', 'team', 'personal')
            include_system: Whether to include system roles
            include_inactive: Whether to include inactive roles

        Returns:
            List[Role]: List of matching roles

        Examples:
                service = RoleService(db)
                team_roles = await service.list_roles(scope="team")
                len(team_roles) >= 0
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
        return result.scalars().all()

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
                service = RoleService(db)
                role = await service.update_role(
            ...     role_id="role-123",
            ...     permissions=["tools.read", "tools.write"]
            ... )
                "tools.write" in role.permissions if role else False
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
                service = RoleService(db)
                success = await service.delete_role("role-123")
                success
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
                service = RoleService(db)
                user_role = await service.assign_role_to_user(
            ...     user_email="user@example.com",
            ...     role_id="role-123",
            ...     scope="team",
            ...     scope_id="team-456",
            ...     granted_by="admin@example.com"
            ... )
                user_role.user_email
            'user@example.com'
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

        logger.info(f"Assigned role {role.name} to {user_email} " f"(scope: {scope}, scope_id: {scope_id})")
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
                service = RoleService(db)
                success = await service.revoke_role_from_user(
            ...     user_email="user@example.com",
            ...     role_id="role-123",
            ...     scope="team",
            ...     scope_id="team-456"
            ... )
                success
            True
        """
        user_role = await self.get_user_role_assignment(user_email, role_id, scope, scope_id)

        if not user_role or not user_role.is_active:
            return False

        user_role.is_active = False
        self.db.commit()

        logger.info(f"Revoked role {role_id} from {user_email} " f"(scope: {scope}, scope_id: {scope_id})")
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
                service = RoleService(db)
                user_role = await service.get_user_role_assignment(
            ...     "user@example.com", "role-123", "global", None
            ... )
                user_role.scope if user_role else None
            'global'
        """
        conditions = [UserRole.user_email == user_email, UserRole.role_id == role_id, UserRole.scope == scope]

        if scope_id:
            conditions.append(UserRole.scope_id == scope_id)
        else:
            conditions.append(UserRole.scope_id.is_(None))

        result = self.db.execute(select(UserRole).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def list_user_roles(self, user_email: str, scope: Optional[str] = None, include_expired: bool = False) -> List[UserRole]:
        """List all role assignments for a user.

        Args:
            user_email: Email of user
            scope: Filter by scope
            include_expired: Whether to include expired roles

        Returns:
            List[UserRole]: User's role assignments

        Examples:
                service = RoleService(db)
                roles = await service.list_user_roles("user@example.com")
                len(roles) >= 0
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
        return result.scalars().all()

    async def list_role_assignments(self, role_id: str, scope: Optional[str] = None, include_expired: bool = False) -> List[UserRole]:
        """List all user assignments for a role.

        Args:
            role_id: ID of role
            scope: Filter by scope
            include_expired: Whether to include expired assignments

        Returns:
            List[UserRole]: Role assignments

        Examples:
                service = RoleService(db)
                assignments = await service.list_role_assignments("role-123")
                len(assignments) >= 0
            True
        """
        query = select(UserRole).where(and_(UserRole.role_id == role_id, UserRole.is_active.is_(True)))

        if scope:
            query = query.where(UserRole.scope == scope)

        if not include_expired:
            now = utc_now()
            query = query.where((UserRole.expires_at.is_(None)) | (UserRole.expires_at > now))

        query = query.order_by(UserRole.user_email)

        result = self.db.execute(query)
        return result.scalars().all()

    async def _would_create_cycle(self, parent_id: str, child_id: Optional[str]) -> bool:
        """Check if setting parent_id as parent of child_id would create a cycle.

        Args:
            parent_id: ID of the proposed parent role
            child_id: ID of the proposed child role

        Returns:
            True if setting this relationship would create a cycle, False otherwise
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
