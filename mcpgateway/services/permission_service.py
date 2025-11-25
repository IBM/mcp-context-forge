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
import re
from typing import Dict, List, Optional, Set

# Third-Party
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

# First-Party
# First-Party
from mcpgateway.db import PermissionAuditLog, Permissions, Prompt, Resource, Role, Server, Tool, UserRole, utc_now
from mcpgateway.services.role_service import RoleService

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

    def __init__(self, db: Session, audit_enabled: bool = True):
        """Initialize permission service.

        Args:
            db: Database session
            audit_enabled: Whether to enable permission auditing
        """
        self.db = db
        self.role_service = RoleService(db)
        self.audit_enabled = audit_enabled
        self._permission_cache: Dict[str, Set[str]] = {}
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
            # # First check if user is admin (bypass all permission checks)
            # if await self._is_user_admin(user_email):
            #     return True

            if not team_id:
                permissions = await self.get_user_permissions(user_email)
                if permission in permissions or Permissions.ALL_PERMISSIONS in permissions:
                    return True
                return permission in await self.get_user_permissions(user_email)

            # Get user's effective permissions from roles
            user_permissions = await self.get_user_permissions(user_email, team_id)

            # Check if user has the specific permission or wildcard
            granted = permission in user_permissions or Permissions.ALL_PERMISSIONS in user_permissions

            # If no explicit permissions found, check fallback permissions for team operations
            if not granted and permission.startswith("teams."):
                granted = await self._check_team_fallback_permissions(user_email, permission, team_id)

            # Log the permission check if auditing is enabled
            if self.audit_enabled:
                await self._log_permission_check(
                    user_email=user_email,
                    permission=permission,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    team_id=team_id,
                    granted=granted,
                    roles_checked=await self._get_roles_for_audit(user_email, team_id),
                    ip_address=ip_address,
                    user_agent=user_agent,
                )

            logger.debug(f"Permission check: user={user_email}, permission={permission}, team={team_id}, granted={granted}")

            return granted

        except Exception as e:
            logger.error(f"Error checking permission for {user_email}: {e}")
            # Default to deny on error
            return False

    async def get_user_permissions(self, user_email: str, team_id: Optional[str] = None) -> Set[str]:
        """Get all effective permissions for a user.

        Collects permissions from all user's roles across applicable scopes.
        Includes role inheritance and handles permission caching.

        Args:
            user_email: Email of the user
            team_id: Optional team context

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
        # Check cache first
        cache_key = f"{user_email}:{team_id or 'global'}"
        if self._is_cache_valid(cache_key):
            return self._permission_cache[cache_key]

        permissions = set()

        # Get all active roles for the user
        user_roles = await self._get_user_roles(user_email, team_id)

        # Collect permissions from all roles
        for user_role in user_roles:
            role_permissions = user_role.role.get_effective_permissions()
            permissions.update(role_permissions)

        # Cache the result
        self._permission_cache[cache_key] = permissions
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
        return result.scalars().all()

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
                if user_role == "team_owner":
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
        self._cache_timestamps.clear()
        logger.debug("Cleared all permission cache")

    async def _get_user_roles(self, user_email: str, team_id: Optional[str] = None) -> List[UserRole]:
        """Get user roles for permission checking.

        Includes global roles and team-specific roles if team_id is provided.

        Args:
            user_email: Email address of the user
            team_id: Optional team ID to include team-specific roles

        Returns:
            List[UserRole]: List of active roles for the user
        """
        return await self.role_service.get_effective_user_roles(user_email, team_id)

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

    async def _get_roles_for_audit(self, user_email: str, team_id: Optional[str]) -> Dict:
        """Get role information for audit logging.

        Args:
            user_email: Email address of the user
            team_id: Optional team ID for context

        Returns:
            Dict: Role information for audit logging
        """
        user_roles = await self._get_user_roles(user_email, team_id)
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
        from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel
        from mcpgateway.db import EmailUser  # pylint: disable=import-outside-toplevel

        # Special case for platform admin (virtual user)
        if user_email == getattr(settings, "platform_owner_email", ""):
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

        # Check if user is a member of this team
        if not await self._is_team_member(user_email, team_id):
            return False

        # Get user's role in the team
        user_role = await self._get_user_team_role(user_email, team_id)

        # Define fallback permissions based on team role
        if user_role == "team_owner":
            # Team owners get full permissions on their teams
            return permission in ["teams.read", "teams.update", "teams.delete", "teams.manage_members", "teams.create"]
        if user_role in ["team_member"]:
            # Team members get basic read permissions
            return permission in ["teams.read"]

        return False

    async def _is_team_member(self, user_email: str, team_id: str) -> bool:
        """Check if user is a member of the specified team.

        Args:
            user_email: Email address of the user
            team_id: Team ID

        Returns:
            bool: True if user is a team member
        """
        member = await self.role_service.get_team_member_role(user_email, team_id)
        return member is not None

    async def _get_user_team_role(self, user_email: str, team_id: str) -> Optional[str]:
        """Get user's role in the specified team.

        Args:
            user_email: Email address of the user
            team_id: Team ID

        Returns:
            Optional[str]: User's role in the team or None if not a member
        """
        member = await self.role_service.get_team_member_role(user_email, team_id)
        return member.role.name if member else None

    def get_required_permission(self, request_method: str, request_path: str) -> Optional[str]:
        """Determine required permission for a request path and method.

        Args:
            request_method: HTTP method (GET, POST, etc.)
            request_path: The request path/URL

        Returns:
            Optional[str]: The required permission string, or None if no specific permission is required.
        """
        # First-Party
        from mcpgateway.permissions_manager import PERMISSION_MAPPINGS  # pylint: disable=import-outside-toplevel

        # Check each permission mapping
        for (method, path_pattern), required_permission in PERMISSION_MAPPINGS.items():
            if request_method == method and re.match(path_pattern, request_path):
                return required_permission

        return None

    async def validate_token_team_membership(self, user_email: str, token_teams: List[str]) -> bool:
        """Validate that the user is still a member of the teams in their token.

        Args:
            user_email: Email of the user
            token_teams: List of team IDs from the token

        Returns:
            bool: True if membership is valid (or not required), False otherwise
        """
        # PUBLIC-ONLY TOKEN: No team validation needed
        if not token_teams:
            return True

        if not user_email:
            return False

        # Check if user has any active team roles
        roles = await self.role_service.get_effective_user_roles(user_email)
        has_team_roles = any(r.scope == "team" for r in roles)

        return has_team_roles

    async def check_resource_access(self, request_path: str, token_teams: List[str]) -> bool:
        """Check if token has access to the requested resource.

        Implements Three-Tier Resource Visibility (Public/Team/Private):
        - PUBLIC: Accessible by all tokens (public-only and team-scoped)
        - TEAM: Accessible only by tokens scoped to that specific team
        - PRIVATE: Accessible only by tokens scoped to that specific team

        Args:
            request_path: The request path/URL
            token_teams: List of team IDs from the token (empty list = public-only token)

        Returns:
            bool: True if resource access is allowed, False otherwise
        """
        # Normalize token_teams: extract team IDs from dict objects (backward compatibility)
        token_team_ids = []
        for team in token_teams:
            if isinstance(team, dict) and "id" in team:
                token_team_ids.append(team["id"])
            else:
                token_team_ids.append(team)

        # Determine token type
        is_public_token = not token_team_ids or len(token_team_ids) == 0

        if is_public_token:
            logger.debug("Processing request with PUBLIC-ONLY token")
        else:
            logger.debug(f"Processing request with TEAM-SCOPED token (teams: {token_teams})")

        # Extract resource type and ID from path using regex patterns
        resource_patterns = [
            (r"/servers/?([a-f0-9\-]*)", "server"),
            (r"/tools/?([a-f0-9\-]*)", "tool"),
            (r"/resources/?(\d*)", "resource"),
            (r"/prompts/?(\d*)", "prompt"),
        ]

        resource_id = None
        resource_type = None

        for pattern, rtype in resource_patterns:
            match = re.search(pattern, request_path)
            if match:
                resource_id = match.group(1)
                resource_type = rtype
                logger.debug(f"Extracted {rtype} ID: {resource_id} from path: {request_path}")
                break

        # If no resource ID in path, allow (general endpoints like /health, /tokens, /metrics)
        if not resource_id or not resource_type:
            logger.debug(f"No resource ID found in path {request_path}, allowing access")
            return True

        try:
            # Check Virtual Servers
            if resource_type == "server":
                server = self.db.execute(select(Server).where(Server.id == resource_id)).scalar_one_or_none()

                if not server:
                    logger.warning(f"Server {resource_id} not found in database")
                    return True

                # Get server visibility (default to 'team' if field doesn't exist)
                server_visibility = getattr(server, "visibility", "team")

                # PUBLIC SERVERS: Accessible by everyone (including public-only tokens)
                if server_visibility == "public":
                    logger.debug(f"Access granted: Server {resource_id} is PUBLIC")
                    return True

                # PUBLIC-ONLY TOKEN: Can ONLY access public servers
                if is_public_token:
                    logger.warning(f"Access denied: Public-only token cannot access {server_visibility} server {resource_id}")
                    return False

                # TEAM-SCOPED SERVERS: Check if server belongs to token's teams
                if server_visibility == "team":
                    if server.team_id in token_team_ids:
                        logger.debug(f"Access granted: Team server {resource_id} belongs to token's team {server.team_id}")
                        return True

                    logger.warning(f"Access denied: Server {resource_id} is team-scoped to '{server.team_id}', token is scoped to teams {token_team_ids}")
                    return False

                # PRIVATE SERVERS: Check if server belongs to token's teams
                if server_visibility == "private":
                    if server.team_id in token_team_ids:
                        logger.debug(f"Access granted: Private server {resource_id} in token's team {server.team_id}")
                        return True

                    logger.warning(f"Access denied: Server {resource_id} is private to team '{server.team_id}'")
                    return False

                # Unknown visibility - deny by default
                logger.warning(f"Access denied: Server {resource_id} has unknown visibility: {server_visibility}")
                return False

            # CHECK TOOLS
            if resource_type == "tool":
                tool = self.db.execute(select(Tool).where(Tool.id == resource_id)).scalar_one_or_none()

                if not tool:
                    logger.warning(f"Tool {resource_id} not found in database")
                    return True

                # Get tool visibility (default to 'team' if field doesn't exist)
                tool_visibility = getattr(tool, "visibility", "team")

                # PUBLIC TOOLS: Accessible by everyone (including public-only tokens)
                if tool_visibility == "public":
                    logger.debug(f"Access granted: Tool {resource_id} is PUBLIC")
                    return True

                # PUBLIC-ONLY TOKEN: Can ONLY access public tools
                if is_public_token:
                    logger.warning(f"Access denied: Public-only token cannot access {tool_visibility} tool {resource_id}")
                    return False

                # TEAM TOOLS: Check if tool's team matches token's teams
                if tool_visibility == "team":
                    tool_team_id = getattr(tool, "team_id", None)
                    if tool_team_id and tool_team_id in token_team_ids:
                        logger.debug(f"Access granted: Team tool {resource_id} belongs to token's team {tool_team_id}")
                        return True

                    logger.warning(f"Access denied: Tool {resource_id} is team-scoped to '{tool_team_id}', token is scoped to teams {token_team_ids}")
                    return False

                # PRIVATE TOOLS: Check if tool is in token's team context
                if tool_visibility in ["private", "user"]:
                    tool_team_id = getattr(tool, "team_id", None)
                    if tool_team_id and tool_team_id in token_team_ids:
                        logger.debug(f"Access granted: Private tool {resource_id} in token's team {tool_team_id}")
                        return True

                    logger.warning(f"Access denied: Tool {resource_id} is {tool_visibility} and not in token's teams")
                    return False

                # Unknown visibility - deny by default
                logger.warning(f"Access denied: Tool {resource_id} has unknown visibility: {tool_visibility}")
                return False

            # CHECK RESOURCES
            if resource_type == "resource":
                resource = self.db.execute(select(Resource).where(Resource.id == int(resource_id))).scalar_one_or_none()

                if not resource:
                    logger.warning(f"Resource {resource_id} not found in database")
                    return True

                # Get resource visibility (default to 'team' if field doesn't exist)
                resource_visibility = getattr(resource, "visibility", "team")

                # PUBLIC RESOURCES: Accessible by everyone (including public-only tokens)
                if resource_visibility == "public":
                    logger.debug(f"Access granted: Resource {resource_id} is PUBLIC")
                    return True

                # PUBLIC-ONLY TOKEN: Can ONLY access public resources
                if is_public_token:
                    logger.warning(f"Access denied: Public-only token cannot access {resource_visibility} resource {resource_id}")
                    return False

                # TEAM RESOURCES: Check if resource's team matches token's teams
                if resource_visibility == "team":
                    resource_team_id = getattr(resource, "team_id", None)
                    if resource_team_id and resource_team_id in token_team_ids:
                        logger.debug(f"Access granted: Team resource {resource_id} belongs to token's team {resource_team_id}")
                        return True

                    logger.warning(f"Access denied: Resource {resource_id} is team-scoped to '{resource_team_id}', token is scoped to teams {token_team_ids}")
                    return False

                # PRIVATE RESOURCES: Check if resource is in token's team context
                if resource_visibility in ["private", "user"]:
                    resource_team_id = getattr(resource, "team_id", None)
                    if resource_team_id and resource_team_id in token_team_ids:
                        logger.debug(f"Access granted: Private resource {resource_id} in token's team {resource_team_id}")
                        return True

                    logger.warning(f"Access denied: Resource {resource_id} is {resource_visibility} and not in token's teams")
                    return False

                # Unknown visibility - deny by default
                logger.warning(f"Access denied: Resource {resource_id} has unknown visibility: {resource_visibility}")
                return False

            # CHECK PROMPTS
            if resource_type == "prompt":
                prompt = self.db.execute(select(Prompt).where(Prompt.id == int(resource_id))).scalar_one_or_none()

                if not prompt:
                    logger.warning(f"Prompt {resource_id} not found in database")
                    return True

                # Get prompt visibility (default to 'team' if field doesn't exist)
                prompt_visibility = getattr(prompt, "visibility", "team")

                # PUBLIC PROMPTS: Accessible by everyone (including public-only tokens)
                if prompt_visibility == "public":
                    logger.debug(f"Access granted: Prompt {resource_id} is PUBLIC")
                    return True

                # PUBLIC-ONLY TOKEN: Can ONLY access public prompts
                if is_public_token:
                    logger.warning(f"Access denied: Public-only token cannot access {prompt_visibility} prompt {resource_id}")
                    return False

                # TEAM PROMPTS: Check if prompt's team matches token's teams
                if prompt_visibility == "team":
                    prompt_team_id = getattr(prompt, "team_id", None)
                    if prompt_team_id and prompt_team_id in token_team_ids:
                        logger.debug(f"Access granted: Team prompt {resource_id} belongs to token's team {prompt_team_id}")
                        return True

                    logger.warning(f"Access denied: Prompt {resource_id} is team-scoped to '{prompt_team_id}', token is scoped to teams {token_team_ids}")
                    return False

                # PRIVATE PROMPTS: Check if prompt is in token's team context
                if prompt_visibility in ["private", "user"]:
                    prompt_team_id = getattr(prompt, "team_id", None)
                    if prompt_team_id and prompt_team_id in token_team_ids:
                        logger.debug(f"Access granted: Private prompt {resource_id} in token's team {prompt_team_id}")
                        return True

                    logger.warning(f"Access denied: Prompt {resource_id} is {prompt_visibility} and not in token's teams")
                    return False

                # Unknown visibility - deny by default
                logger.warning(f"Access denied: Prompt {resource_id} has unknown visibility: {prompt_visibility}")
                return False

            # UNKNOWN RESOURCE TYPE
            logger.warning(f"Unknown resource type '{resource_type}' for path: {request_path}")
            return False

        except Exception as e:
            logger.error(f"Error checking resource team ownership for {request_path}: {e}", exc_info=True)
            # Fail securely - deny access on error
            return False
