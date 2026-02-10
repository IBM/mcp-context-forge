# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/permission_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Permission Service for RBAC System.

This module provides the core permission checking logic for the RBAC system.
It handles role-based permission validation, permission auditing, and caching.
"""

# Standard
from datetime import datetime
import logging
from typing import Dict, List, Optional, Set

# Third-Party
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import contains_eager, Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import PermissionAuditLog, Permissions, Role, UserRole, utc_now

logger = logging.getLogger(__name__)


class PermissionService:
    """Service for checking and managing user permissions.

    Provides role-based permission checking with caching, auditing,
    and support for global, team, and personal scopes.

    Attributes:
        db: Database session
        audit_enabled: Whether to log permission checks
        cache_ttl: Permission cache TTL in seconds

    Examples:
        Basic construction and coroutine checks:
        >>> from unittest.mock import Mock
        >>> service = PermissionService(Mock())
        >>> isinstance(service, PermissionService)
        True
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(service.check_permission)
        True
        >>> asyncio.iscoroutinefunction(service.get_user_permissions)
        True
    """

    def __init__(self, db: Session, audit_enabled: Optional[bool] = None):
        """Initialize permission service.

        Args:
            db: Database session
            audit_enabled: Whether to enable permission auditing (defaults to settings.permission_audit_enabled / PERMISSION_AUDIT_ENABLED)
        """
        self.db = db
        if audit_enabled is None:
            audit_enabled = settings.permission_audit_enabled
        self.audit_enabled = audit_enabled
        self._permission_cache: Dict[str, Set[str]] = {}
        self._roles_cache: Dict[str, List[UserRole]] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
        self.cache_ttl = 300  # 5 minutes

    async def check_permission(
        self,
        user_email: str,
        permission: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        team_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        allow_admin_bypass: bool = True,
        check_any_team: bool = False,
    ) -> bool:
        """Check if user has specific permission.

        Checks user's roles across all applicable scopes (global, team, personal)
        and returns True if any role grants the required permission.

        Args:
            user_email: Email of the user to check
            permission: Permission to check (e.g., 'tools.create')
            resource_type: Type of resource being accessed
            resource_id: Specific resource ID if applicable
            team_id: Team context for the permission check
            ip_address: IP address for audit logging
            user_agent: User agent for audit logging
            allow_admin_bypass: If True, admin users bypass all permission checks.
                               If False, admins must have explicit permissions.
                               Default is True for backward compatibility.
            check_any_team: If True, check permission across ALL team-scoped roles
                           (used for list/read endpoints with multi-team session tokens)

        Returns:
            bool: True if permission is granted, False otherwise

        Examples:
            Parameter validation helpers:
            >>> permission = "users.read"
            >>> permission.count('.') == 1
            True
            >>> team_id = "team-123"
            >>> isinstance(team_id, str)
            True
            >>> from unittest.mock import Mock
            >>> service = PermissionService(Mock())
            >>> import asyncio
            >>> asyncio.iscoroutinefunction(service.check_permission)
            True
        """
        try:
            # Check if user is admin (bypass all permission checks if allowed)
            if allow_admin_bypass and await self._is_user_admin(user_email):
                return True

            # Get user's effective permissions (uses cache when valid)
            user_permissions = await self.get_user_permissions(user_email, team_id, include_all_teams=check_any_team)

            # Check if user has the specific permission or wildcard
            granted = permission in user_permissions or Permissions.ALL_PERMISSIONS in user_permissions

            # If no explicit permissions found, check fallback permissions for team operations
            if not granted and permission.startswith("teams."):
                granted = await self._check_team_fallback_permissions(user_email, permission, team_id)

            # If no explicit permissions found, check fallback permissions for token operations
            if not granted and permission.startswith("tokens."):
                granted = await self._check_token_fallback_permissions(user_email, permission)

            # Log the permission check if auditing is enabled
            if self.audit_enabled:
                # Reuse roles cached by get_user_permissions (no second query)
                roles_checked = self._get_roles_for_audit(user_email, team_id)
                await self._log_permission_check(
                    user_email=user_email,
                    permission=permission,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    team_id=team_id,
                    granted=granted,
                    roles_checked=roles_checked,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )

            logger.debug(f"Permission check: user={user_email}, permission={permission}, team={team_id}, granted={granted}")

            return granted

        except Exception as e:
            logger.error(f"Error checking permission for {user_email}: {e}")
            # Default to deny on error
            return False

    async def has_admin_permission(self, user_email: str) -> bool:
        """Check if user has any admin-level permission.

        This is used by AdminAuthMiddleware to allow access to /admin/* routes
        for users who have admin permissions via RBAC, even if they're not
        marked as is_admin in the database.

        Args:
            user_email: Email of the user to check

        Returns:
            bool: True if user is an admin OR has any admin.* permission
        """
        try:
            # First check if user is a database admin
            if await self._is_user_admin(user_email):
                return True

            # Get user's permissions and check for any admin.* permission
            user_permissions = await self.get_user_permissions(user_email)

            # Check for wildcard or any admin permission
            if Permissions.ALL_PERMISSIONS in user_permissions:
                return True

            # Check for any admin.* permission
            for perm in user_permissions:
                if perm.startswith("admin."):
                    return True

            return False

        except Exception as e:
            logger.error(f"Error checking admin permission for {user_email}: {e}")
            return False

    async def get_user_permissions(self, user_email: str, team_id: Optional[str] = None, include_all_teams: bool = False) -> Set[str]:
        """Get all effective permissions for a user.

        Collects permissions from all user's roles across applicable scopes.
        Includes role inheritance and handles permission caching.

        Args:
            user_email: Email of the user
            team_id: Optional team context
            include_all_teams: If True, include ALL team-scoped roles (for list/read endpoints)

        Returns:
            Set[str]: All effective permissions for the user

        Examples:
            Key shapes and coroutine check:
            >>> cache_key = f"user@example.com:{'global'}"
            >>> ':' in cache_key
            True
            >>> from unittest.mock import Mock
            >>> service = PermissionService(Mock())
            >>> import asyncio
            >>> asyncio.iscoroutinefunction(service.get_user_permissions)
            True
        """
        # Use distinct cache key for any-team lookups to avoid poisoning global cache
        if include_all_teams:
            cache_key = f"{user_email}:__anyteam__"
        else:
            cache_key = f"{user_email}:{team_id or 'global'}"
        if self._is_cache_valid(cache_key):
            cached_perms = self._permission_cache[cache_key]
            logger.debug(f"[RBAC] Cache hit for {user_email} (team_id={team_id}): {cached_perms}")
            return cached_perms

        permissions = set()

        # Get all active roles for the user (with eager-loaded role relationship)
        user_roles = await self._get_user_roles(user_email, team_id, include_all_teams=include_all_teams)
        logger.debug(f"[RBAC] Found {len(user_roles)} roles for {user_email} (team_id={team_id})")

        # Collect permissions from all roles
        for user_role in user_roles:
            role_permissions = user_role.role.get_effective_permissions()
            logger.debug(f"[RBAC] Role '{user_role.role.name}' (scope={user_role.scope}, scope_id={user_role.scope_id}) has permissions: {role_permissions}")
            permissions.update(role_permissions)

        # Cache both permissions and roles
        self._permission_cache[cache_key] = permissions
        self._roles_cache[cache_key] = user_roles
        self._cache_timestamps[cache_key] = utc_now()

        return permissions

    async def get_user_roles(self, user_email: str, scope: Optional[str] = None, team_id: Optional[str] = None, include_expired: bool = False) -> List[UserRole]:
        """Get user's role assignments.

        Args:
            user_email: Email of the user
            scope: Filter by scope ('global', 'team', 'personal')
            team_id: Filter by team ID
            include_expired: Whether to include expired roles

        Returns:
            List[UserRole]: User's role assignments

        Examples:
            Coroutine check:
            >>> from unittest.mock import Mock
            >>> service = PermissionService(Mock())
            >>> import asyncio
            >>> asyncio.iscoroutinefunction(service.get_user_roles)
            True
        """
        query = select(UserRole).join(Role).where(and_(UserRole.user_email == user_email, UserRole.is_active.is_(True), Role.is_active.is_(True)))

        if scope:
            query = query.where(UserRole.scope == scope)

        if team_id:
            query = query.where(UserRole.scope_id == team_id)

        if not include_expired:
            now = utc_now()
            query = query.where((UserRole.expires_at.is_(None)) | (UserRole.expires_at > now))

        result = self.db.execute(query)
        user_roles = result.scalars().all()
        return user_roles

    async def has_permission_on_resource(self, user_email: str, permission: str, resource_type: str, resource_id: str, team_id: Optional[str] = None) -> bool:
        """Check if user has permission on a specific resource.

        This method can be extended to include resource-specific
        permission logic (e.g., resource ownership, sharing rules).

        Args:
            user_email: Email of the user
            permission: Permission to check
            resource_type: Type of resource
            resource_id: Specific resource ID
            team_id: Team context

        Returns:
            bool: True if user has permission on the resource

        Examples:
            Coroutine check and parameter sanity:
            >>> from unittest.mock import Mock
            >>> service = PermissionService(Mock())
            >>> import asyncio
            >>> asyncio.iscoroutinefunction(service.has_permission_on_resource)
            True
            >>> res_type, res_id = "tools", "tool-123"
            >>> all(isinstance(x, str) for x in (res_type, res_id))
            True
        """
        # Basic permission check
        if not await self.check_permission(user_email=user_email, permission=permission, resource_type=resource_type, resource_id=resource_id, team_id=team_id):
            return False

        # NOTE: Add resource-specific logic here in future enhancement
        # For example:
        # - Check resource ownership
        # - Check resource sharing permissions
        # - Check resource team membership

        return True

    async def check_resource_ownership(self, user_email: str, resource: any, allow_team_admin: bool = True) -> bool:
        """Check if user owns a resource or is a team admin for team resources.

        This method checks resource ownership based on the owner_email field
        and optionally allows team admins to modify team-scoped resources.

        Args:
            user_email: Email of the user to check
            resource: Resource object with owner_email, team_id, and visibility attributes
            allow_team_admin: Whether to allow team admins for team-scoped resources

        Returns:
            bool: True if user owns the resource or is authorized team admin

        Examples:
            >>> from unittest.mock import Mock
            >>> service = PermissionService(Mock())
            >>> import asyncio
            >>> asyncio.iscoroutinefunction(service.check_resource_ownership)
            True
        """
        # Check if user is platform admin (bypass ownership checks)
        if await self._is_user_admin(user_email):
            return True

        # Check direct ownership
        if hasattr(resource, "owner_email") and resource.owner_email == user_email:
            return True

        # Check team admin permission for team resources
        if allow_team_admin and hasattr(resource, "visibility") and resource.visibility == "team":
            if hasattr(resource, "team_id") and resource.team_id:
                user_role = await self._get_user_team_role(user_email, resource.team_id)
                if user_role == "owner":
                    return True

        return False

    async def check_admin_permission(self, user_email: str) -> bool:
        """Check if user has any admin permissions.

        Args:
            user_email: Email of the user

        Returns:
            bool: True if user has admin permissions

        Examples:
            Coroutine check:
            >>> from unittest.mock import Mock
            >>> service = PermissionService(Mock())
            >>> import asyncio
            >>> asyncio.iscoroutinefunction(service.check_admin_permission)
            True
        """
        # First check if user is admin (handles platform admin virtual user)
        if await self._is_user_admin(user_email):
            return True

        admin_permissions = [Permissions.ADMIN_SYSTEM_CONFIG, Permissions.ADMIN_USER_MANAGEMENT, Permissions.ADMIN_SECURITY_AUDIT, Permissions.ALL_PERMISSIONS]

        user_permissions = await self.get_user_permissions(user_email)
        return any(perm in user_permissions for perm in admin_permissions)

    def clear_user_cache(self, user_email: str) -> None:
        """Clear cached permissions for a user.

        Should be called when user's roles change.

        Args:
            user_email: Email of the user

        Examples:
            Cache invalidation behavior:
            >>> from unittest.mock import Mock
            >>> service = PermissionService(Mock())
            >>> service._permission_cache = {"alice:global": {"tools.read"}, "bob:team1": {"*"}}
            >>> service._cache_timestamps = {"alice:global": utc_now(), "bob:team1": utc_now()}
            >>> service.clear_user_cache("alice")
            >>> "alice:global" in service._permission_cache
            False
            >>> "bob:team1" in service._permission_cache
            True
        """
        keys_to_remove = [key for key in self._permission_cache if key.startswith(f"{user_email}:")]

        for key in keys_to_remove:
            self._permission_cache.pop(key, None)
            self._roles_cache.pop(key, None)
            self._cache_timestamps.pop(key, None)

        logger.debug(f"Cleared permission cache for user: {user_email}")

    def clear_cache(self) -> None:
        """Clear all cached permissions.

        Examples:
            Clear all cache:
            >>> from unittest.mock import Mock
            >>> service = PermissionService(Mock())
            >>> service._permission_cache = {"x": {"p"}}
            >>> service._cache_timestamps = {"x": utc_now()}
            >>> service.clear_cache()
            >>> service._permission_cache == {}
            True
            >>> service._cache_timestamps == {}
            True
        """
        self._permission_cache.clear()
        self._roles_cache.clear()
        self._cache_timestamps.clear()
        logger.debug("Cleared all permission cache")

    async def _get_user_roles(self, user_email: str, team_id: Optional[str] = None, include_all_teams: bool = False) -> List[UserRole]:
        """Get user roles for permission checking.

        Always includes global and personal roles. Team-scoped role inclusion
        depends on the parameters:

        - team_id provided: includes team roles for that specific team
          (plus team roles with scope_id=NULL which apply to all teams)
        - team_id=None, include_all_teams=True: includes ALL team-scoped roles
        - team_id=None, include_all_teams=False: includes only team-scoped roles
          with scope_id=NULL (roles that apply to all teams, e.g. during login)

        Args:
            user_email: Email address of the user
            team_id: Optional team ID to filter to a specific team's roles
            include_all_teams: If True, include ALL team-scoped roles (for list/read with session tokens)

        Returns:
            List[UserRole]: List of active roles for the user
        """
        query = select(UserRole).join(Role).options(contains_eager(UserRole.role)).where(and_(UserRole.user_email == user_email, UserRole.is_active.is_(True), Role.is_active.is_(True)))

        # Include global roles and personal roles
        scope_conditions = [UserRole.scope == "global", UserRole.scope == "personal"]

        if team_id:
            # Filter to specific team's roles only
            scope_conditions.append(and_(UserRole.scope == "team", or_(UserRole.scope_id == team_id, UserRole.scope_id.is_(None))))
        elif include_all_teams:
            # Include ALL team-scoped roles (for list/read endpoints with session tokens)
            scope_conditions.append(UserRole.scope == "team")
        else:
            # When team_id is None and include_all_teams is False (e.g., during login),
            # include team-scoped roles with scope_id=None (roles that apply to all teams)
            scope_conditions.append(and_(UserRole.scope == "team", UserRole.scope_id.is_(None)))

        query = query.where(or_(*scope_conditions))

        # Filter out expired roles
        now = utc_now()
        query = query.where((UserRole.expires_at.is_(None)) | (UserRole.expires_at > now))

        result = self.db.execute(query)
        user_roles = result.unique().scalars().all()
        return user_roles

    async def _log_permission_check(
        self,
        user_email: str,
        permission: str,
        resource_type: Optional[str],
        resource_id: Optional[str],
        team_id: Optional[str],
        granted: bool,
        roles_checked: Dict,
        ip_address: Optional[str],
        user_agent: Optional[str],
    ) -> None:
        """Log permission check for auditing.

        Args:
            user_email: Email address of the user
            permission: Permission being checked
            resource_type: Type of resource being accessed
            resource_id: ID of specific resource
            team_id: ID of team context
            granted: Whether permission was granted
            roles_checked: Dictionary of roles that were checked
            ip_address: IP address of request
            user_agent: User agent of request
        """
        audit_log = PermissionAuditLog(
            user_email=user_email,
            permission=permission,
            resource_type=resource_type,
            resource_id=resource_id,
            team_id=team_id,
            granted=granted,
            roles_checked=roles_checked,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        self.db.add(audit_log)
        self.db.commit()

    def _get_roles_for_audit(self, user_email: str, team_id: Optional[str]) -> Dict:
        """Get role information for audit logging from cached roles.

        Uses roles cached by get_user_permissions() to avoid a duplicate DB query.

        Args:
            user_email: Email address of the user.
            team_id: Optional team ID for context.

        Returns:
            Dict: Role information for audit logging
        """
        cache_key = f"{user_email}:{team_id or 'global'}"
        user_roles = self._roles_cache.get(cache_key, [])
        return {"roles": [{"id": ur.role_id, "name": ur.role.name, "scope": ur.scope, "permissions": ur.role.permissions} for ur in user_roles]}

    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached permissions are still valid.

        Args:
            cache_key: Cache key to check validity for

        Returns:
            bool: True if cache is valid, False otherwise
        """
        if cache_key not in self._permission_cache:
            return False

        if cache_key not in self._cache_timestamps:
            return False

        age = utc_now() - self._cache_timestamps[cache_key]
        return age.total_seconds() < self.cache_ttl

    async def _is_user_admin(self, user_email: str) -> bool:
        """Check if user is admin by looking up user record directly.

        Args:
            user_email: Email address of the user

        Returns:
            bool: True if user is admin
        """
        # First-Party
        from mcpgateway.db import EmailUser  # pylint: disable=import-outside-toplevel

        # Special case for platform admin (virtual user)
        if user_email == getattr(settings, "platform_admin_email", ""):
            return True

        user = self.db.execute(select(EmailUser).where(EmailUser.email == user_email)).scalar_one_or_none()
        return bool(user and user.is_admin)

    async def _check_team_fallback_permissions(self, user_email: str, permission: str, team_id: Optional[str]) -> bool:
        """Check fallback team permissions for users without explicit RBAC roles.

        This provides basic team management permissions for authenticated users on teams they belong to.

        Args:
            user_email: Email address of the user
            permission: Permission being checked
            team_id: Team ID context

        Returns:
            bool: True if user has fallback permission
        """
        if not team_id:
            # For global team operations, allow authenticated users to read their teams and create new teams
            if permission in ["teams.create", "teams.read"]:
                return True
            return False

        # Get user's role in the team (single query instead of two separate queries)
        user_role = await self._get_user_team_role(user_email, team_id)

        # If user is not a member (role is None), deny access
        if user_role is None:
            return False

        # Define fallback permissions based on team role
        if user_role == "owner":
            # Team owners get full permissions on their teams
            return permission in ["teams.read", "teams.update", "teams.delete", "teams.manage_members", "teams.create"]
        if user_role in ["member"]:
            # Team members get basic read permissions
            return permission in ["teams.read"]

        return False

    async def _is_team_member(self, user_email: str, team_id: str) -> bool:
        """Check if user is a member of the specified team.

        Note: This method delegates to _get_user_team_role to avoid duplicate DB queries.

        Args:
            user_email: Email address of the user
            team_id: Team ID

        Returns:
            bool: True if user is a team member
        """
        # Delegate to _get_user_team_role to avoid duplicate query
        return await self._get_user_team_role(user_email, team_id) is not None

    async def _get_user_team_role(self, user_email: str, team_id: str) -> Optional[str]:
        """Get user's role in the specified team.

        Args:
            user_email: Email address of the user
            team_id: Team ID

        Returns:
            Optional[str]: User's role in the team or None if not a member
        """
        # First-Party
        from mcpgateway.db import EmailTeamMember  # pylint: disable=import-outside-toplevel

        member = self.db.execute(select(EmailTeamMember).where(and_(EmailTeamMember.user_email == user_email, EmailTeamMember.team_id == team_id, EmailTeamMember.is_active))).scalar_one_or_none()
        self.db.commit()  # Release transaction to avoid idle-in-transaction

        return member.role if member else None

    async def _check_token_fallback_permissions(self, _user_email: str, permission: str) -> bool:
        """Check fallback token permissions for authenticated users.

        All authenticated users can manage their own tokens. The token endpoints
        already filter by user_email, so this just grants access to the endpoints.

        Args:
            _user_email: Email address of the user (unused)
            permission: Permission being checked

        Returns:
            bool: True if user has fallback permission for token operations
        """
        # Any authenticated user can create, read, update, and revoke their own tokens
        # The actual filtering by user_email happens in the token service layer
        if permission in ["tokens.create", "tokens.read", "tokens.update", "tokens.revoke"]:
            return True

        return False
