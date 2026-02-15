# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/team_management_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Team Management Service.
This module provides team creation, management, and membership operations
for the multi-team collaboration system.

Examples:
    >>> from unittest.mock import Mock
    >>> service = TeamManagementService(Mock())
    >>> isinstance(service, TeamManagementService)
    True
    >>> hasattr(service, 'db')
    True
"""

# Standard
import asyncio
import base64
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

# Third-Party
import orjson
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import selectinload, Session

# First-Party
from mcpgateway.cache.admin_stats_cache import admin_stats_cache
from mcpgateway.cache.auth_cache import auth_cache, get_auth_cache
from mcpgateway.config import settings
from mcpgateway.db import EmailTeam, EmailTeamJoinRequest, EmailTeamMember, EmailTeamMemberHistory, EmailUser, utc_now
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.pagination import unified_paginate
from mcpgateway.utils.redis_client import get_redis_client

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class TeamManagementError(Exception):
    """Base class for team management-related errors.

    Examples:
        >>> error = TeamManagementError("Test error")
        >>> str(error)
        'Test error'
        >>> isinstance(error, Exception)
        True
    """


class InvalidRoleError(TeamManagementError):
    """Raised when an invalid role is specified.

    Examples:
        >>> error = InvalidRoleError("Invalid role: guest")
        >>> str(error)
        'Invalid role: guest'
        >>> isinstance(error, TeamManagementError)
        True
    """


class TeamNotFoundError(TeamManagementError):
    """Raised when a team does not exist.

    Examples:
        >>> error = TeamNotFoundError("Team not found: team-123")
        >>> str(error)
        'Team not found: team-123'
        >>> isinstance(error, TeamManagementError)
        True
    """


class UserNotFoundError(TeamManagementError):
    """Raised when a user does not exist.

    Examples:
        >>> error = UserNotFoundError("User not found: user@example.com")
        >>> str(error)
        'User not found: user@example.com'
        >>> isinstance(error, TeamManagementError)
        True
    """


class MemberAlreadyExistsError(TeamManagementError):
    """Raised when a user is already a member of the team.

    Examples:
        >>> error = MemberAlreadyExistsError("User user@example.com is already a member of team team-123")
        >>> str(error)
        'User user@example.com is already a member of team team-123'
        >>> isinstance(error, TeamManagementError)
        True
    """


class TeamMemberLimitExceededError(TeamManagementError):
    """Raised when a team has reached its maximum member limit.

    Examples:
        >>> error = TeamMemberLimitExceededError("Team has reached maximum member limit of 10")
        >>> str(error)
        'Team has reached maximum member limit of 10'
        >>> isinstance(error, TeamManagementError)
        True
    """


class TeamMemberAddError(TeamManagementError):
    """Raised when adding a member to a team fails due to database or system errors.

    Examples:
        >>> error = TeamMemberAddError("Failed to add member due to database error")
        >>> str(error)
        'Failed to add member due to database error'
        >>> isinstance(error, TeamManagementError)
        True
    """


class TeamManagementService:
    """Service for team management operations.

    This service handles team creation, membership management,
    role assignments, and team access control.

    Attributes:
        db (Session): SQLAlchemy database session

    Examples:
        >>> from unittest.mock import Mock
        >>> service = TeamManagementService(Mock())
        >>> service.__class__.__name__
        'TeamManagementService'
        >>> hasattr(service, 'db')
        True
    """

    def __init__(self, db: Session):
        """Initialize the team management service.

        Args:
            db: SQLAlchemy database session

        Examples:
            Basic initialization:
            >>> from mcpgateway.services.team_management_service import TeamManagementService
            >>> from unittest.mock import Mock
            >>> db_session = Mock()
            >>> service = TeamManagementService(db_session)
            >>> service.db is db_session
            True

            Service attributes:
            >>> hasattr(service, 'db')
            True
            >>> service.__class__.__name__
            'TeamManagementService'
        """
        self.db = db
        self._role_service = None  # Lazy initialization to avoid circular imports

    @property
    def role_service(self):
        """Lazy-initialized RoleService to avoid circular imports.

        Returns:
            RoleService: Instance of RoleService
        """
        if self._role_service is None:
            # First-Party
            from mcpgateway.services.role_service import RoleService  # pylint: disable=import-outside-toplevel

            self._role_service = RoleService(self.db)
        return self._role_service

    @staticmethod
    def _get_rbac_role_name(membership_role: str) -> str:
        """Map a team membership role to the corresponding configurable RBAC role name.

        Args:
            membership_role: Team membership role ('owner' or 'member').

        Returns:
            str: The configured RBAC role name from settings.
        """
        return settings.default_team_owner_role if membership_role == "owner" else settings.default_team_member_role

    @staticmethod
    def _fire_and_forget(coro: Any) -> None:
        """Schedule a background coroutine and close it if scheduling fails.

        Args:
            coro: The coroutine to schedule as a background task.

        Raises:
            Exception: If asyncio.create_task fails (e.g. no running loop).
        """
        try:
            task = asyncio.create_task(coro)
            # Some tests patch create_task with a plain Mock return value. In that
            # case the coroutine is never actually scheduled and must be closed.
            if asyncio.iscoroutine(coro) and not isinstance(task, asyncio.Task):
                close = getattr(coro, "close", None)
                if callable(close):
                    close()
        except Exception:
            # If create_task() fails (e.g. no running loop), the coroutine has
            # already been created and must be closed to avoid runtime warnings.
            close = getattr(coro, "close", None)
            if callable(close):
                close()
            raise

    def _log_team_member_action(self, team_member_id: str, team_id: str, user_email: str, role: str, action: str, action_by: Optional[str]):
        """
        Log a team member action to EmailTeamMemberHistory.

        Args:
            team_member_id: ID of the EmailTeamMember
            team_id: Team ID
            user_email: Email of the affected user
            role: Role at the time of action
            action: Action type ("added", "removed", "reactivated", "role_changed")
            action_by: Email of the user who performed the action

        Examples:
            >>> from mcpgateway.services.team_management_service import TeamManagementService
            >>> from unittest.mock import Mock
            >>> service = TeamManagementService(Mock())
            >>> service._log_team_member_action("tm-123", "team-123", "user@example.com", "member", "added", "admin@example.com")
        """
        history = EmailTeamMemberHistory(team_member_id=team_member_id, team_id=team_id, user_email=user_email, role=role, action=action, action_by=action_by, action_timestamp=utc_now())
        self.db.add(history)
        self.db.commit()

    async def create_team(self, name: str, description: Optional[str], created_by: str, visibility: Optional[str] = "public", max_members: Optional[int] = None) -> EmailTeam:
        """Create a new team.

        Args:
            name: Team name
            description: Team description
            created_by: Email of the user creating the team
            visibility: Team visibility (private, team, public)
            max_members: Maximum number of team members allowed

        Returns:
            EmailTeam: The created team

        Raises:
            ValueError: If team name is taken or invalid
            Exception: If team creation fails

        Examples:
            Team creation parameter validation:
            >>> from mcpgateway.services.team_management_service import TeamManagementService

            Test team name validation:
            >>> team_name = "My Development Team"
            >>> len(team_name) > 0
            True
            >>> len(team_name) <= 255
            True
            >>> bool(team_name.strip())
            True

            Test visibility validation:
            >>> visibility = "private"
            >>> valid_visibilities = ["private", "public"]
            >>> visibility in valid_visibilities
            True
            >>> "invalid" in valid_visibilities
            False

            Test max_members validation:
            >>> max_members = 50
            >>> isinstance(max_members, int)
            True
            >>> max_members > 0
            True

            Test creator validation:
            >>> created_by = "admin@example.com"
            >>> "@" in created_by
            True
            >>> len(created_by) > 0
            True

            Test description handling:
            >>> description = "A team for software development"
            >>> description is not None
            True
            >>> isinstance(description, str)
            True

            >>> # Test None description
            >>> description_none = None
            >>> description_none is None
            True
        """
        try:
            # Validate visibility
            valid_visibilities = ["private", "public"]
            if visibility not in valid_visibilities:
                raise ValueError(f"Invalid visibility. Must be one of: {', '.join(valid_visibilities)}")

            # Apply default max members from settings
            if max_members is None:
                max_members = getattr(settings, "max_members_per_team", 100)

            # Check for existing inactive team with same name

            potential_slug = slugify(name)
            existing_inactive_team = self.db.query(EmailTeam).filter(EmailTeam.slug == potential_slug, EmailTeam.is_active.is_(False)).first()

            if existing_inactive_team:
                # Reactivate the existing team with new details
                existing_inactive_team.name = name
                existing_inactive_team.description = description
                existing_inactive_team.created_by = created_by
                existing_inactive_team.visibility = visibility
                existing_inactive_team.max_members = max_members
                existing_inactive_team.is_active = True
                existing_inactive_team.updated_at = utc_now()
                team = existing_inactive_team

                # Check if the creator already has an inactive membership
                existing_membership = self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == team.id, EmailTeamMember.user_email == created_by).first()

                if existing_membership:
                    # Reactivate existing membership as owner
                    existing_membership.role = "owner"
                    existing_membership.joined_at = utc_now()
                    existing_membership.is_active = True
                    membership = existing_membership
                else:
                    # Create new membership
                    membership = EmailTeamMember(team_id=team.id, user_email=created_by, role="owner", joined_at=utc_now(), is_active=True)
                    self.db.add(membership)

                logger.info(f"Reactivated existing team with slug {potential_slug}")
            else:
                # Create the team (slug will be auto-generated by event listener)
                team = EmailTeam(name=name, description=description, created_by=created_by, is_personal=False, visibility=visibility, max_members=max_members, is_active=True)
                self.db.add(team)

                self.db.flush()  # Get the team ID

                # Add the creator as owner
                membership = EmailTeamMember(team_id=team.id, user_email=created_by, role="owner", joined_at=utc_now(), is_active=True)
                self.db.add(membership)

            self.db.commit()

            # Invalidate member count cache for the new team
            await self.invalidate_team_member_count_cache(str(team.id))

            # Invalidate auth cache for creator's team membership
            # Without this, the cache won't know the user belongs to this new team
            try:
                await auth_cache.invalidate_user_teams(created_by)
                await auth_cache.invalidate_team_membership(created_by)
                await auth_cache.invalidate_user_role(created_by, str(team.id))
                await admin_stats_cache.invalidate_teams()
            except Exception as cache_error:
                logger.debug(f"Failed to invalidate cache on team create: {cache_error}")

            logger.info(f"Created team '{team.name}' by {created_by}")
            return team

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to create team '{name}': {e}")
            raise

    async def get_team_by_id(self, team_id: str) -> Optional[EmailTeam]:
        """Get a team by ID.

        Args:
            team_id: Team ID to lookup

        Returns:
            EmailTeam: The team or None if not found

        Examples:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> service = TeamManagementService(Mock())
            >>> asyncio.iscoroutinefunction(service.get_team_by_id)
            True
        """
        try:
            team = self.db.query(EmailTeam).filter(EmailTeam.id == team_id, EmailTeam.is_active.is_(True)).first()
            self.db.commit()  # Release transaction to avoid idle-in-transaction
            return team

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to get team by ID {team_id}: {e}")
            return None

    async def get_team_by_slug(self, slug: str) -> Optional[EmailTeam]:
        """Get a team by slug.

        Args:
            slug: Team slug to lookup

        Returns:
            EmailTeam: The team or None if not found

        Examples:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> service = TeamManagementService(Mock())
            >>> asyncio.iscoroutinefunction(service.get_team_by_slug)
            True
        """
        try:
            team = self.db.query(EmailTeam).filter(EmailTeam.slug == slug, EmailTeam.is_active.is_(True)).first()
            self.db.commit()  # Release transaction to avoid idle-in-transaction
            return team

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to get team by slug {slug}: {e}")
            return None

    async def update_team(
        self, team_id: str, name: Optional[str] = None, description: Optional[str] = None, visibility: Optional[str] = None, max_members: Optional[int] = None, updated_by: Optional[str] = None
    ) -> bool:
        """Update team information.

        Args:
            team_id: ID of the team to update
            name: New team name
            description: New team description
            visibility: New visibility setting
            max_members: New maximum member limit
            updated_by: Email of user making the update

        Returns:
            bool: True if update succeeded, False otherwise

        Raises:
            ValueError: If visibility setting is invalid

        Examples:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> service = TeamManagementService(Mock())
            >>> asyncio.iscoroutinefunction(service.update_team)
            True
        """
        try:
            team = await self.get_team_by_id(team_id)
            if not team:
                logger.warning(f"Team {team_id} not found for update")
                return False

            # Prevent updating personal teams
            if team.is_personal:
                logger.warning(f"Cannot update personal team {team_id}")
                return False

            # Update fields if provided
            if name is not None:
                team.name = name
                # Slug will be updated by event listener if name changes

            if description is not None:
                team.description = description

            if visibility is not None:
                valid_visibilities = ["private", "public"]
                if visibility not in valid_visibilities:
                    raise ValueError(f"Invalid visibility. Must be one of: {', '.join(valid_visibilities)}")
                team.visibility = visibility

            if max_members is not None:
                team.max_members = max_members

            team.updated_at = utc_now()
            self.db.commit()

            logger.info(f"Updated team {team_id} by {updated_by}")
            return True

        except ValueError:
            raise  # Let ValueError propagate to caller for proper error handling
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to update team {team_id}: {e}")
            return False

    async def delete_team(self, team_id: str, deleted_by: str) -> bool:
        """Delete a team (soft delete).

        Args:
            team_id: ID of the team to delete
            deleted_by: Email of user performing deletion

        Returns:
            bool: True if deletion succeeded, False otherwise

        Raises:
            ValueError: If attempting to delete a personal team

        Examples:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> service = TeamManagementService(Mock())
            >>> asyncio.iscoroutinefunction(service.delete_team)
            True
        """
        try:
            team = await self.get_team_by_id(team_id)
            if not team:
                logger.warning(f"Team {team_id} not found for deletion")
                return False

            # Prevent deleting personal teams
            if team.is_personal:
                logger.warning(f"Cannot delete personal team {team_id}")
                raise ValueError("Personal teams cannot be deleted")

            # Soft delete the team
            team.is_active = False
            team.updated_at = utc_now()

            # Get all active memberships before deactivating (for history logging)
            memberships = self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == team_id, EmailTeamMember.is_active.is_(True)).all()

            # Log history for each membership (before bulk update)
            for membership in memberships:
                self._log_team_member_action(membership.id, team_id, membership.user_email, membership.role, "team-deleted", deleted_by)

            # Bulk update: deactivate all memberships in single query instead of looping
            self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == team_id, EmailTeamMember.is_active.is_(True)).update({EmailTeamMember.is_active: False}, synchronize_session=False)

            self.db.commit()

            # Invalidate all role caches for this team
            try:
                self._fire_and_forget(auth_cache.invalidate_team_roles(team_id))
                self._fire_and_forget(admin_stats_cache.invalidate_teams())
                # Also invalidate team cache, teams list cache, and team membership cache for each member
                for membership in memberships:
                    self._fire_and_forget(auth_cache.invalidate_team(membership.user_email))
                    self._fire_and_forget(auth_cache.invalidate_user_teams(membership.user_email))
                    self._fire_and_forget(auth_cache.invalidate_team_membership(membership.user_email))
            except Exception as cache_error:
                logger.debug(f"Failed to invalidate caches on team delete: {cache_error}")

            logger.info(f"Deleted team {team_id} by {deleted_by}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to delete team {team_id}: {e}")
            return False

    async def add_member_to_team(self, team_id: str, user_email: str, role: str = "member", invited_by: Optional[str] = None) -> EmailTeamMember:
        """Add a member to a team.

        Args:
            team_id: ID of the team
            user_email: Email of the user to add
            role: Role to assign (owner, member)
            invited_by: Email of user who added this member

        Returns:
            EmailTeamMember: The created or reactivated team member object

        Raises:
            InvalidRoleError: If role is invalid
            TeamNotFoundError: If team does not exist
            TeamManagementError: If team is a personal team
            UserNotFoundError: If user does not exist
            MemberAlreadyExistsError: If user is already a member
            TeamMemberLimitExceededError: If team has reached maximum member limit
            TeamMemberAddError: If adding member fails due to database or system errors

        Examples:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> service = TeamManagementService(Mock())
            >>> asyncio.iscoroutinefunction(service.add_member_to_team)
            True
            >>> # After adding, EmailTeamMemberHistory is updated
            >>> # service._log_team_member_action("tm-123", "team-123", "user@example.com", "member", "added", "admin@example.com")
        """
        # Validate role
        valid_roles = ["owner", "member"]
        if role not in valid_roles:
            raise InvalidRoleError(f"Invalid role '{role}'. Must be one of: {', '.join(valid_roles)}")

        # Check if team exists
        team = await self.get_team_by_id(team_id)
        if not team:
            logger.warning(f"Team {team_id} not found")
            raise TeamNotFoundError("Team not found")

        # Prevent adding members to personal teams
        if team.is_personal:
            logger.warning(f"Cannot add members to personal team {team_id}")
            raise TeamManagementError("Cannot add members to personal teams")

        # Check if user exists
        user = self.db.query(EmailUser).filter(EmailUser.email == user_email).first()
        if not user:
            logger.warning(f"User {user_email} not found")
            raise UserNotFoundError("User not found")

        # Check if user is already a member
        existing_membership = self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == team_id, EmailTeamMember.user_email == user_email).first()

        if existing_membership and existing_membership.is_active:
            logger.warning(f"User {user_email} is already a member of team {team_id}")
            raise MemberAlreadyExistsError("User is already a member of this team")

        # Check team member limit
        if team.max_members:
            current_member_count = self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == team_id, EmailTeamMember.is_active.is_(True)).count()

            if current_member_count >= team.max_members:
                logger.warning(f"Team {team_id} has reached maximum member limit of {team.max_members}")
                raise TeamMemberLimitExceededError(f"Team has reached maximum member limit of {team.max_members}")

        # Add or reactivate membership
        try:
            if existing_membership:
                existing_membership.is_active = True
                existing_membership.role = role
                existing_membership.joined_at = utc_now()
                existing_membership.invited_by = invited_by
                self.db.commit()
                self._log_team_member_action(existing_membership.id, team_id, user_email, role, "reactivated", invited_by)
                member = existing_membership
            else:
                membership = EmailTeamMember(team_id=team_id, user_email=user_email, role=role, joined_at=utc_now(), invited_by=invited_by, is_active=True)
                self.db.add(membership)
                self.db.commit()
                self._log_team_member_action(membership.id, team_id, user_email, role, "added", invited_by)
                member = membership

            # Assign team-scoped RBAC role matching the membership role (owner or member)
            try:
                rbac_role_name = self._get_rbac_role_name(role)
                team_rbac_role = await self.role_service.get_role_by_name(rbac_role_name, scope="team")
                if team_rbac_role:
                    existing = await self.role_service.get_user_role_assignment(user_email=user_email, role_id=team_rbac_role.id, scope="team", scope_id=team_id)
                    if not existing or not existing.is_active:
                        await self.role_service.assign_role_to_user(user_email=user_email, role_id=team_rbac_role.id, scope="team", scope_id=team_id, granted_by=invited_by or user_email)
                        logger.info(f"Assigned {rbac_role_name} role to {user_email} for team {team_id}")
                    else:
                        logger.debug(f"User {user_email} already has active {rbac_role_name} role for team {team_id}")
                else:
                    logger.warning(f"Role '{rbac_role_name}' not found. User {user_email} added without RBAC role.")
            except Exception as role_error:
                logger.warning(f"Failed to assign role to {user_email}: {role_error}")

            # Invalidate auth cache for user's team membership and role
            try:
                self._fire_and_forget(auth_cache.invalidate_team(user_email))
                self._fire_and_forget(auth_cache.invalidate_user_role(user_email, team_id))
                self._fire_and_forget(auth_cache.invalidate_user_teams(user_email))
                self._fire_and_forget(auth_cache.invalidate_team_membership(user_email))
                self._fire_and_forget(admin_stats_cache.invalidate_teams())
            except Exception as cache_error:
                logger.debug(f"Failed to invalidate cache on team add: {cache_error}")

            # Invalidate member count cache for this team
            await self.invalidate_team_member_count_cache(str(team_id))

            logger.info(f"Added {user_email} to team {team_id} with role {role}")
            return member

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to add {user_email} to team {team_id}: {e}")
            raise TeamMemberAddError("Failed to add member to team") from e

    async def remove_member_from_team(self, team_id: str, user_email: str, removed_by: Optional[str] = None) -> bool:
        """Remove a member from a team.

        Args:
            team_id: ID of the team
            user_email: Email of the user to remove
            removed_by: Email of user performing the removal

        Returns:
            bool: True if member was removed successfully, False otherwise

        Raises:
            ValueError: If attempting to remove the last owner

        Examples:
            Team membership management with role-based access control.
            After removal, EmailTeamMemberHistory is updated via _log_team_member_action.
        """
        try:
            team = await self.get_team_by_id(team_id)
            if not team:
                logger.warning(f"Team {team_id} not found")
                return False

            # Prevent removing members from personal teams
            if team.is_personal:
                logger.warning(f"Cannot remove members from personal team {team_id}")
                return False

            # Find the membership
            membership = self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == team_id, EmailTeamMember.user_email == user_email, EmailTeamMember.is_active.is_(True)).first()

            if not membership:
                logger.warning(f"User {user_email} is not a member of team {team_id}")
                return False

            # Prevent removing the last owner
            if membership.role == "owner":
                owner_count = self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == team_id, EmailTeamMember.role == "owner", EmailTeamMember.is_active.is_(True)).count()

                if owner_count <= 1:
                    logger.warning(f"Cannot remove the last owner from team {team_id}")
                    raise ValueError("Cannot remove the last owner from a team")

            # Remove membership (soft delete)
            membership.is_active = False
            self.db.commit()
            self._log_team_member_action(membership.id, team_id, user_email, membership.role, "removed", removed_by)

            # Revoke all team-scoped RBAC roles from removed member defensively
            # (revoke both owner and member roles to handle edge cases)
            try:
                for role_name in (settings.default_team_owner_role, settings.default_team_member_role):
                    rbac_role = await self.role_service.get_role_by_name(role_name, scope="team")
                    if rbac_role:
                        revoked = await self.role_service.revoke_role_from_user(user_email=user_email, role_id=rbac_role.id, scope="team", scope_id=team_id)
                        if revoked:
                            logger.info(f"Revoked {role_name} role from {user_email} for team {team_id}")
            except Exception as role_error:
                logger.warning(f"Failed to revoke roles from {user_email}: {role_error}")

            # Invalidate auth cache for user's team membership and role
            try:
                self._fire_and_forget(auth_cache.invalidate_team(user_email))
                self._fire_and_forget(auth_cache.invalidate_user_role(user_email, team_id))
                self._fire_and_forget(auth_cache.invalidate_user_teams(user_email))
                self._fire_and_forget(auth_cache.invalidate_team_membership(user_email))
            except Exception as cache_error:
                logger.debug(f"Failed to invalidate cache on team remove: {cache_error}")

            # Invalidate member count cache for this team
            await self.invalidate_team_member_count_cache(str(team_id))

            logger.info(f"Removed {user_email} from team {team_id} by {removed_by}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to remove {user_email} from team {team_id}: {e}")
            return False

    async def update_member_role(self, team_id: str, user_email: str, new_role: str, updated_by: Optional[str] = None) -> bool:
        """Update a team member's role.

        Args:
            team_id: ID of the team
            user_email: Email of the user whose role to update
            new_role: New role to assign
            updated_by: Email of user making the change

        Returns:
            bool: True if role was updated successfully, False otherwise

        Raises:
            ValueError: If role is invalid or removing last owner role

        Examples:
            Role management within teams for access control.
            After role update, EmailTeamMemberHistory is updated via _log_team_member_action.
        """
        try:
            # Validate role
            valid_roles = ["owner", "member"]
            if new_role not in valid_roles:
                raise ValueError(f"Invalid role. Must be one of: {', '.join(valid_roles)}")

            team = await self.get_team_by_id(team_id)
            if not team:
                logger.warning(f"Team {team_id} not found")
                return False

            # Prevent updating roles in personal teams
            if team.is_personal:
                logger.warning(f"Cannot update roles in personal team {team_id}")
                return False

            # Find the membership
            membership = self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == team_id, EmailTeamMember.user_email == user_email, EmailTeamMember.is_active.is_(True)).first()

            if not membership:
                logger.warning(f"User {user_email} is not a member of team {team_id}")
                return False

            # Prevent changing the role of the last owner to non-owner
            if membership.role == "owner" and new_role != "owner":
                owner_count = self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == team_id, EmailTeamMember.role == "owner", EmailTeamMember.is_active.is_(True)).count()

                if owner_count <= 1:
                    logger.warning(f"Cannot remove owner role from the last owner of team {team_id}")
                    raise ValueError("Cannot remove owner role from the last owner of a team")

            # Update the role
            old_role = membership.role
            membership.role = new_role
            self.db.commit()
            self._log_team_member_action(membership.id, team_id, user_email, new_role, "role_changed", updated_by)

            # Handle RBAC role changes when team membership role changes
            if old_role != new_role:
                try:
                    # Get both role types
                    team_member_role = await self.role_service.get_role_by_name(settings.default_team_member_role, scope="team")
                    team_owner_role = await self.role_service.get_role_by_name(settings.default_team_owner_role, scope="team")

                    # Handle role transitions
                    if old_role == "member" and new_role == "owner":
                        # member -> owner: revoke member role, assign owner role
                        if team_member_role:
                            await self.role_service.revoke_role_from_user(user_email=user_email, role_id=team_member_role.id, scope="team", scope_id=team_id)
                        if team_owner_role:
                            await self.role_service.assign_role_to_user(user_email=user_email, role_id=team_owner_role.id, scope="team", scope_id=team_id, granted_by=updated_by or user_email)
                        logger.info(f"Transitioned RBAC role from {settings.default_team_member_role} to {settings.default_team_owner_role} for {user_email} in team {team_id}")

                    elif old_role == "owner" and new_role == "member":
                        # owner -> member: revoke owner role, assign member role
                        if team_owner_role:
                            await self.role_service.revoke_role_from_user(user_email=user_email, role_id=team_owner_role.id, scope="team", scope_id=team_id)
                        if team_member_role:
                            await self.role_service.assign_role_to_user(user_email=user_email, role_id=team_member_role.id, scope="team", scope_id=team_id, granted_by=updated_by or user_email)
                        logger.info(f"Transitioned RBAC role from {settings.default_team_owner_role} to {settings.default_team_member_role} for {user_email} in team {team_id}")

                except Exception as role_error:
                    logger.warning(f"Failed to update RBAC roles for {user_email} in team {team_id}: {role_error}")
                    # Don't fail the membership role update if RBAC role update fails

            # Invalidate role cache
            try:
                self._fire_and_forget(auth_cache.invalidate_user_role(user_email, team_id))
            except Exception as cache_error:
                logger.debug(f"Failed to invalidate cache on role update: {cache_error}")

            logger.info(f"Updated role of {user_email} in team {team_id} to {new_role} by {updated_by}")
            return True

        except ValueError:
            raise  # Let ValueError propagate to caller for proper error handling
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to update role of {user_email} in team {team_id}: {e}")
            return False

    async def get_member(self, team_id: str, user_email: str) -> Optional[EmailTeamMember]:
        """Get a single team member by team ID and user email.

        Args:
            team_id: ID of the team
            user_email: Email of the user

        Returns:
            EmailTeamMember if found and active, None otherwise
        """
        try:
            return self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == team_id, EmailTeamMember.user_email == user_email, EmailTeamMember.is_active.is_(True)).first()
        except Exception as e:
            logger.error(f"Failed to get member {user_email} in team {team_id}: {e}")
            return None

    async def get_user_teams(self, user_email: str, include_personal: bool = True) -> List[EmailTeam]:
        """Get all teams a user belongs to.

        Uses caching to reduce database queries (called 20+ times per request).
        Cache can be disabled via AUTH_CACHE_TEAMS_ENABLED=false.

        Args:
            user_email: Email of the user
            include_personal: Whether to include personal teams

        Returns:
            List[EmailTeam]: List of teams the user belongs to

        Examples:
            User dashboard showing team memberships.
        """
        # Check cache first
        cache = self._get_auth_cache()
        cache_key = f"{user_email}:{include_personal}"

        if cache:
            cached_team_ids = await cache.get_user_teams(cache_key)
            if cached_team_ids is not None:
                if not cached_team_ids:  # Empty list = user has no teams
                    return []
                # Fetch full team objects by IDs (fast indexed lookup)
                try:
                    teams = self.db.query(EmailTeam).filter(EmailTeam.id.in_(cached_team_ids), EmailTeam.is_active.is_(True)).all()
                    self.db.commit()  # Release transaction to avoid idle-in-transaction
                    return teams
                except Exception as e:
                    self.db.rollback()
                    logger.warning(f"Failed to fetch teams by IDs from cache: {e}")
                    # Fall through to full query

        # Cache miss or caching disabled - do full query
        try:
            query = self.db.query(EmailTeam).join(EmailTeamMember).filter(EmailTeamMember.user_email == user_email, EmailTeamMember.is_active.is_(True), EmailTeam.is_active.is_(True))

            if not include_personal:
                query = query.filter(EmailTeam.is_personal.is_(False))

            teams = query.all()
            self.db.commit()  # Release transaction to avoid idle-in-transaction

            # Update cache with team IDs
            if cache:
                team_ids = [t.id for t in teams]
                await cache.set_user_teams(cache_key, team_ids)

            return teams

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to get teams for user {user_email}: {e}")
            return []

    async def verify_team_for_user(self, user_email, team_id=None):
        """
        Retrieve a team ID for a user based on their membership and optionally a specific team ID.

        This function attempts to fetch all teams associated with the given user email.
        If no `team_id` is provided, it returns the ID of the user's personal team (if any).
        If a `team_id` is provided, it checks whether the user is a member of that team.
        If the user is not a member of the specified team, it returns a JSONResponse with an error message.

        Args:
            user_email (str): The email of the user whose teams are being queried.
            team_id (str or None, optional): Specific team ID to check for membership. Defaults to None.

        Returns:
            str or JSONResponse or None:
                - If `team_id` is None, returns the ID of the user's personal team or None if not found.
                - If `team_id` is provided and the user is a member of that team, returns `team_id`.
                - If `team_id` is provided but the user is not a member of that team, returns a JSONResponse with error.
                - Returns None if an error occurs and no `team_id` was initially provided.

        Raises:
            None explicitly, but any exceptions during the process are caught and logged.

        Examples:
            Verifies user team if team_id provided otherwise finds its personal id.
        """
        try:
            # Get all teams the user belongs to in a single query
            try:
                query = self.db.query(EmailTeam).join(EmailTeamMember).filter(EmailTeamMember.user_email == user_email, EmailTeamMember.is_active.is_(True), EmailTeam.is_active.is_(True))
                user_teams = query.all()
                self.db.commit()  # Release transaction to avoid idle-in-transaction
            except Exception as e:
                self.db.rollback()
                logger.error(f"Failed to get teams for user {user_email}: {e}")
                return []

            if not team_id:
                # If no team_id is provided, try to get the personal team
                personal_team = next((t for t in user_teams if getattr(t, "is_personal", False)), None)
                team_id = personal_team.id if personal_team else None
            else:
                # Check if the provided team_id exists among the user's teams
                is_team_present = any(team.id == team_id for team in user_teams)
                if not is_team_present:
                    return []
        except Exception as e:
            self.db.rollback()
            print(f"An error occurred: {e}")
            if not team_id:
                team_id = None

        return team_id

    async def get_team_members(
        self,
        team_id: str,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
    ) -> Union[List[Tuple[EmailUser, EmailTeamMember]], Tuple[List[Tuple[EmailUser, EmailTeamMember]], Optional[str]], Dict[str, Any]]:
        """Get all members of a team with optional cursor or page-based pagination.

        Note: This method returns ORM objects and cannot be cached since callers
        depend on ORM attributes and methods.

        Args:
            team_id: ID of the team
            cursor: Opaque cursor token for cursor-based pagination
            limit: Maximum number of members to return (for cursor-based, default: 50)
            page: Page number for page-based pagination (1-indexed). Mutually exclusive with cursor.
            per_page: Items per page for page-based pagination (default: 30)

        Returns:
            - If cursor is provided: Tuple (members, next_cursor)
            - If page is provided: Dict with keys 'data', 'pagination', 'links'
            - If neither: List of all members (backward compatibility)

        Examples:
            Team member management and role display.
        """
        try:
            # Build base query - for pagination, select EmailTeamMember and eager-load user
            # For backward compat (no pagination), select both entities as tuple
            if cursor is None and page is None and limit is None:
                # Backward compatibility: return tuples (no pagination requested)
                query = (
                    select(EmailUser, EmailTeamMember)
                    .join(EmailTeamMember, EmailUser.email == EmailTeamMember.user_email)
                    .where(EmailTeamMember.team_id == team_id, EmailTeamMember.is_active.is_(True))
                    .order_by(EmailUser.full_name, EmailUser.email)
                )
                result = self.db.execute(query)
                members = list(result.all())
                self.db.commit()
                return members

            # For pagination: select EmailTeamMember and eager-load user to avoid N+1
            query = (
                select(EmailTeamMember)
                .options(selectinload(EmailTeamMember.user))
                .where(EmailTeamMember.team_id == team_id, EmailTeamMember.is_active.is_(True))
                .join(EmailUser, EmailUser.email == EmailTeamMember.user_email)
            )

            # PAGE-BASED PAGINATION (Admin UI) - use unified_paginate
            if page is not None:
                # Alphabetical ordering for user-friendly display
                query = query.order_by(EmailUser.full_name, EmailUser.email)
                pag_result = await unified_paginate(
                    db=self.db,
                    query=query,
                    page=page,
                    per_page=per_page or 30,
                    cursor=None,
                    limit=None,
                    base_url=f"/admin/teams/{team_id}/members",
                    query_params={},
                )
                self.db.commit()
                memberships = pag_result["data"]
                tuples = [(m.user, m) for m in memberships]
                return {
                    "data": tuples,
                    "pagination": pag_result["pagination"],
                    "links": pag_result["links"],
                }

            # CURSOR-BASED PAGINATION (API) - custom implementation using (joined_at, id)
            # unified_paginate uses created_at which doesn't exist on EmailTeamMember

            # Order by joined_at DESC, id DESC for keyset pagination
            query = query.order_by(desc(EmailTeamMember.joined_at), desc(EmailTeamMember.id))

            # Decode cursor and apply keyset filter
            if cursor:
                try:
                    cursor_json = base64.urlsafe_b64decode(cursor.encode()).decode()
                    cursor_data = orjson.loads(cursor_json)
                    last_id = cursor_data.get("id")
                    joined_str = cursor_data.get("joined_at")
                    if last_id and joined_str:
                        last_joined = datetime.fromisoformat(joined_str)
                        # Keyset filter: (joined_at < last) OR (joined_at = last AND id < last_id)
                        query = query.where(
                            or_(
                                EmailTeamMember.joined_at < last_joined,
                                and_(EmailTeamMember.joined_at == last_joined, EmailTeamMember.id < last_id),
                            )
                        )
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid cursor for team members, ignoring: {e}")

            # Fetch limit + 1 to check for more results (cap at max_page_size)
            page_size = min(limit or 50, settings.pagination_max_page_size)
            query = query.limit(page_size + 1)
            memberships = list(self.db.execute(query).scalars().all())

            # Check if there are more results
            has_more = len(memberships) > page_size
            if has_more:
                memberships = memberships[:page_size]

            # Generate next cursor using (joined_at, id)
            next_cursor = None
            if has_more and memberships:
                last_member = memberships[-1]
                cursor_data = {
                    "joined_at": last_member.joined_at.isoformat() if last_member.joined_at else None,
                    "id": last_member.id,
                }
                next_cursor = base64.urlsafe_b64encode(orjson.dumps(cursor_data)).decode()

            self.db.commit()
            tuples = [(m.user, m) for m in memberships]
            return (tuples, next_cursor)

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to get members for team {team_id}: {e}")

            # Return appropriate empty response based on mode
            if page is not None:
                return {"data": [], "pagination": {"page": page, "per_page": per_page or 30, "total": 0, "has_next": False, "has_prev": False}, "links": None}

            if cursor is not None:
                return ([], None)

            return []

    def count_team_owners(self, team_id: str) -> int:
        """Count the number of owners in a team using SQL COUNT.

        This is more efficient than loading all members and counting in Python.

        Args:
            team_id: ID of the team

        Returns:
            int: Number of active owners in the team
        """
        count = self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == team_id, EmailTeamMember.role == "owner", EmailTeamMember.is_active.is_(True)).count()
        self.db.commit()  # Release transaction to avoid idle-in-transaction
        return count

    def _get_auth_cache(self):
        """Get auth cache instance lazily.

        Returns:
            AuthCache instance or None if unavailable.
        """
        try:
            return get_auth_cache()
        except ImportError:
            return None

    def _get_admin_stats_cache(self):
        """Get admin stats cache instance lazily.

        Returns:
            AdminStatsCache instance or None if unavailable.
        """
        try:
            # First-Party
            from mcpgateway.cache.admin_stats_cache import get_admin_stats_cache  # pylint: disable=import-outside-toplevel

            return get_admin_stats_cache()
        except ImportError:
            return None

    async def get_user_role_in_team(self, user_email: str, team_id: str) -> Optional[str]:
        """Get a user's role in a specific team.

        Uses caching to reduce database queries (called 11+ times per team operation).

        Args:
            user_email: Email of the user
            team_id: ID of the team

        Returns:
            str: User's role or None if not a member

        Examples:
            Access control and permission checking.
        """
        # Check cache first
        cache = self._get_auth_cache()
        if cache:
            cached_role = await cache.get_user_role(user_email, team_id)
            if cached_role is not None:
                # Empty string means "not a member" (cached None)
                return cached_role if cached_role else None

        try:
            membership = self.db.query(EmailTeamMember).filter(EmailTeamMember.user_email == user_email, EmailTeamMember.team_id == team_id, EmailTeamMember.is_active.is_(True)).first()
            self.db.commit()  # Release transaction to avoid idle-in-transaction

            role = membership.role if membership else None

            # Store in cache
            if cache:
                await cache.set_user_role(user_email, team_id, role)

            return role

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to get role for {user_email} in team {team_id}: {e}")
            return None

    async def list_teams(
        self,
        # Unified pagination params
        limit: int = 100,
        offset: int = 0,
        cursor: Optional[str] = None,
        page: Optional[int] = None,
        per_page: int = 50,
        include_inactive: bool = False,
        visibility_filter: Optional[str] = None,
        base_url: Optional[str] = None,
        include_personal: bool = False,
        search_query: Optional[str] = None,
    ) -> Union[Tuple[List[EmailTeam], Optional[str]], Dict[str, Any]]:
        """List teams with pagination support (cursor or page based).

        Args:
            limit: Max items for cursor pagination
            offset: Offset for legacy/cursor pagination
            cursor: Cursor token
            page: Page number (1-indexed)
            per_page: Items per page
            include_inactive: Whether to include inactive teams
            visibility_filter: Filter by visibility (private, team, public)
            base_url: Base URL for pagination links
            include_personal: Whether to include personal teams
            search_query: Search term for name/slug/description

        Returns:
            Union[Tuple[List[EmailTeam], Optional[str]], Dict[str, Any]]:
                - Tuple (teams, next_cursor) if cursor/offset based
                - Dict {data, pagination, links} if page based
        """
        query = select(EmailTeam)

        if not include_personal:
            query = query.where(EmailTeam.is_personal.is_(False))

        if not include_inactive:
            query = query.where(EmailTeam.is_active.is_(True))

        if visibility_filter:
            query = query.where(EmailTeam.visibility == visibility_filter)

        if search_query:
            search_term = f"%{search_query}%"
            query = query.where(
                or_(
                    EmailTeam.name.ilike(search_term),
                    EmailTeam.slug.ilike(search_term),
                    EmailTeam.description.ilike(search_term),
                )
            )

        # Choose ordering based on pagination mode:
        # - Page-based (UI): alphabetical by name for user-friendly display
        # - Cursor-based (API): created_at DESC, id DESC to match unified_paginate expectations
        if page is not None:
            query = query.order_by(EmailTeam.name, EmailTeam.id)
        else:
            query = query.order_by(desc(EmailTeam.created_at), desc(EmailTeam.id))

        # Base URL for pagination links (default to admin partial if not provided)
        if not base_url:
            base_url = f"{settings.app_root_path}/admin/teams/partial"

        # Apply offset manually for legacy offset-based pagination if not using page or cursor
        if not page and not cursor and offset > 0:
            query = query.offset(offset)

        result = await unified_paginate(
            db=self.db,
            query=query,
            cursor=cursor,
            limit=limit,
            page=page,
            per_page=per_page,
            base_url=base_url,
        )
        self.db.commit()  # Release transaction to avoid idle-in-transaction
        return result

    async def get_all_team_ids(
        self,
        include_inactive: bool = False,
        visibility_filter: Optional[str] = None,
        include_personal: bool = False,
        search_query: Optional[str] = None,
    ) -> List[int]:
        """Get all team IDs matching criteria (unpaginated).

        Args:
            include_inactive: Whether to include inactive teams
            visibility_filter: Filter by visibility (private, team, public)
            include_personal: Whether to include personal teams
            search_query: Search term for name/slug

        Returns:
            List[int]: List of team IDs
        """
        query = select(EmailTeam.id)

        if not include_personal:
            query = query.where(EmailTeam.is_personal.is_(False))

        if not include_inactive:
            query = query.where(EmailTeam.is_active.is_(True))

        if visibility_filter:
            query = query.where(EmailTeam.visibility == visibility_filter)

        if search_query:
            search_term = f"%{search_query}%"
            query = query.where(
                or_(
                    EmailTeam.name.ilike(search_term),
                    EmailTeam.slug.ilike(search_term),
                )
            )

        result = self.db.execute(query)
        team_ids = [row[0] for row in result.all()]
        self.db.commit()  # Release transaction to avoid idle-in-transaction
        return team_ids

    async def get_teams_count(
        self,
        include_inactive: bool = False,
        visibility_filter: Optional[str] = None,
        include_personal: bool = False,
        search_query: Optional[str] = None,
    ) -> int:
        """Get total count of teams matching criteria.

        Args:
            include_inactive: Whether to include inactive teams
            visibility_filter: Filter by visibility (private, team, public)
            include_personal: Whether to include personal teams
            search_query: Search term for name/slug

        Returns:
            int: Total count of matching teams
        """
        query = select(func.count(EmailTeam.id))  # pylint: disable=not-callable

        if not include_personal:
            query = query.where(EmailTeam.is_personal.is_(False))

        if not include_inactive:
            query = query.where(EmailTeam.is_active.is_(True))

        if visibility_filter:
            query = query.where(EmailTeam.visibility == visibility_filter)

        if search_query:
            search_term = f"%{search_query}%"
            query = query.where(
                or_(
                    EmailTeam.name.ilike(search_term),
                    EmailTeam.slug.ilike(search_term),
                )
            )

        result = self.db.execute(query)
        count = result.scalar() or 0
        self.db.commit()  # Release transaction to avoid idle-in-transaction
        return count

    async def discover_public_teams(self, user_email: str, skip: int = 0, limit: Optional[int] = None) -> List[EmailTeam]:
        """Discover public teams that user can join.

        Args:
            user_email: Email of the user discovering teams
            skip: Number of teams to skip for pagination
            limit: Maximum number of teams to return (None for unlimited)

        Returns:
            List[EmailTeam]: List of public teams user can join

        Raises:
            Exception: If discovery fails
        """
        try:
            # Optimized: Use subquery instead of loading all IDs into memory (2 queries → 1)
            user_team_subquery = select(EmailTeamMember.team_id).where(EmailTeamMember.user_email == user_email, EmailTeamMember.is_active.is_(True)).scalar_subquery()

            query = self.db.query(EmailTeam).filter(EmailTeam.visibility == "public", EmailTeam.is_active.is_(True), EmailTeam.is_personal.is_(False), ~EmailTeam.id.in_(user_team_subquery))

            query = query.offset(skip)
            if limit is not None:
                query = query.limit(limit)
            teams = query.all()
            self.db.commit()  # Release transaction to avoid idle-in-transaction
            return teams

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to discover public teams for {user_email}: {e}")
            return []

    async def create_join_request(self, team_id: str, user_email: str, message: Optional[str] = None) -> "EmailTeamJoinRequest":
        """Create a request to join a public team.

        Args:
            team_id: ID of the team to join
            user_email: Email of the user requesting to join
            message: Optional message to team owners

        Returns:
            EmailTeamJoinRequest: Created join request

        Raises:
            ValueError: If team not found, not public, or user already member/has pending request
        """
        try:
            # Validate team
            team = await self.get_team_by_id(team_id)
            if not team:
                raise ValueError("Team not found")

            if team.visibility != "public":
                raise ValueError("Can only request to join public teams")

            # Check if user is already a member
            existing_member = self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == team_id, EmailTeamMember.user_email == user_email, EmailTeamMember.is_active.is_(True)).first()

            if existing_member:
                raise ValueError("User is already a member of this team")

            # Check for existing requests (any status)
            existing_request = self.db.query(EmailTeamJoinRequest).filter(EmailTeamJoinRequest.team_id == team_id, EmailTeamJoinRequest.user_email == user_email).first()

            if existing_request:
                if existing_request.status == "pending" and not existing_request.is_expired():
                    raise ValueError("User already has a pending join request for this team")

                # Update existing request (cancelled, rejected, expired) to pending
                existing_request.message = message or ""
                existing_request.status = "pending"
                existing_request.requested_at = utc_now()
                existing_request.expires_at = utc_now() + timedelta(days=7)
                existing_request.reviewed_at = None
                existing_request.reviewed_by = None
                existing_request.notes = None
                join_request = existing_request
            else:
                # Create new join request
                join_request = EmailTeamJoinRequest(team_id=team_id, user_email=user_email, message=message, expires_at=utc_now() + timedelta(days=7))
                self.db.add(join_request)

            self.db.commit()
            self.db.refresh(join_request)

            logger.info(f"Created join request for user {user_email} to team {team_id}")
            return join_request

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to create join request: {e}")
            raise

    async def list_join_requests(self, team_id: str) -> List["EmailTeamJoinRequest"]:
        """List pending join requests for a team.

        Args:
            team_id: ID of the team

        Returns:
            List[EmailTeamJoinRequest]: List of pending join requests
        """
        try:
            requests = (
                self.db.query(EmailTeamJoinRequest).filter(EmailTeamJoinRequest.team_id == team_id, EmailTeamJoinRequest.status == "pending").order_by(EmailTeamJoinRequest.requested_at.desc()).all()
            )
            return requests

        except Exception as e:
            logger.error(f"Failed to list join requests for team {team_id}: {e}")
            return []

    async def approve_join_request(self, request_id: str, approved_by: str) -> Optional[EmailTeamMember]:
        """Approve a team join request.

        Args:
            request_id: ID of the join request
            approved_by: Email of the user approving the request

        Returns:
            EmailTeamMember: New team member or None if request not found

        Raises:
            ValueError: If request not found, expired, or already processed
        """
        try:
            # Get join request
            join_request = self.db.query(EmailTeamJoinRequest).filter(EmailTeamJoinRequest.id == request_id, EmailTeamJoinRequest.status == "pending").first()

            if not join_request:
                raise ValueError("Join request not found or already processed")

            if join_request.is_expired():
                join_request.status = "expired"
                self.db.commit()
                raise ValueError("Join request has expired")

            # Add user to team
            member = EmailTeamMember(team_id=join_request.team_id, user_email=join_request.user_email, role="member", invited_by=approved_by, joined_at=utc_now())  # New joiners are always members

            self.db.add(member)
            # Update join request status
            join_request.status = "approved"
            join_request.reviewed_at = utc_now()
            join_request.reviewed_by = approved_by

            self.db.flush()
            self._log_team_member_action(member.id, join_request.team_id, join_request.user_email, member.role, "added", approved_by)

            self.db.refresh(member)

            # Assign team-scoped RBAC role matching the membership role
            try:
                rbac_role_name = self._get_rbac_role_name(member.role)
                team_rbac_role = await self.role_service.get_role_by_name(rbac_role_name, scope="team")
                if team_rbac_role:
                    existing = await self.role_service.get_user_role_assignment(user_email=join_request.user_email, role_id=team_rbac_role.id, scope="team", scope_id=join_request.team_id)
                    if not existing or not existing.is_active:
                        await self.role_service.assign_role_to_user(user_email=join_request.user_email, role_id=team_rbac_role.id, scope="team", scope_id=join_request.team_id, granted_by=approved_by)
                        logger.info(f"Assigned {rbac_role_name} role to {join_request.user_email} for team {join_request.team_id}")
                    else:
                        logger.debug(f"User {join_request.user_email} already has active {rbac_role_name} role for team {join_request.team_id}")
                else:
                    logger.warning(f"Role '{rbac_role_name}' not found. User {join_request.user_email} added without RBAC role.")
            except Exception as role_error:
                logger.warning(f"Failed to assign role to {join_request.user_email}: {role_error}")

            # Invalidate auth cache for user's team membership and role
            try:
                self._fire_and_forget(auth_cache.invalidate_team(join_request.user_email))
                self._fire_and_forget(auth_cache.invalidate_user_role(join_request.user_email, join_request.team_id))
                self._fire_and_forget(auth_cache.invalidate_user_teams(join_request.user_email))
                self._fire_and_forget(auth_cache.invalidate_team_membership(join_request.user_email))
                self._fire_and_forget(admin_stats_cache.invalidate_teams())
            except Exception as cache_error:
                logger.debug(f"Failed to invalidate caches on join approval: {cache_error}")

            # Invalidate member count cache for this team
            await self.invalidate_team_member_count_cache(str(join_request.team_id))

            logger.info(f"Approved join request {request_id}: user {join_request.user_email} joined team {join_request.team_id}")
            return member

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to approve join request {request_id}: {e}")
            raise

    async def reject_join_request(self, request_id: str, rejected_by: str) -> bool:
        """Reject a team join request.

        Args:
            request_id: ID of the join request
            rejected_by: Email of the user rejecting the request

        Returns:
            bool: True if request was rejected successfully

        Raises:
            ValueError: If request not found or already processed
        """
        try:
            # Get join request
            join_request = self.db.query(EmailTeamJoinRequest).filter(EmailTeamJoinRequest.id == request_id, EmailTeamJoinRequest.status == "pending").first()

            if not join_request:
                raise ValueError("Join request not found or already processed")

            # Update join request status
            join_request.status = "rejected"
            join_request.reviewed_at = utc_now()
            join_request.reviewed_by = rejected_by

            self.db.commit()

            logger.info(f"Rejected join request {request_id}: user {join_request.user_email} for team {join_request.team_id}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to reject join request {request_id}: {e}")
            raise

    async def get_user_join_requests(self, user_email: str, team_id: Optional[str] = None) -> List["EmailTeamJoinRequest"]:
        """Get join requests made by a user.

        Args:
            user_email: Email of the user
            team_id: Optional team ID to filter requests

        Returns:
            List[EmailTeamJoinRequest]: List of join requests made by the user

        Examples:
            Get all requests made by a user or for a specific team.
        """
        try:
            query = self.db.query(EmailTeamJoinRequest).filter(EmailTeamJoinRequest.user_email == user_email)

            if team_id:
                query = query.filter(EmailTeamJoinRequest.team_id == team_id)

            requests = query.all()
            return requests

        except Exception as e:
            logger.error(f"Failed to get join requests for user {user_email}: {e}")
            return []

    async def cancel_join_request(self, request_id: str, user_email: str) -> bool:
        """Cancel a join request.

        Args:
            request_id: ID of the join request to cancel
            user_email: Email of the user canceling the request

        Returns:
            bool: True if canceled successfully, False otherwise

        Examples:
            Allow users to cancel their pending join requests.
        """
        try:
            # Get the join request
            join_request = (
                self.db.query(EmailTeamJoinRequest).filter(EmailTeamJoinRequest.id == request_id, EmailTeamJoinRequest.user_email == user_email, EmailTeamJoinRequest.status == "pending").first()
            )

            if not join_request:
                logger.warning(f"Join request {request_id} not found for user {user_email} or not pending")
                return False

            # Update join request status
            join_request.status = "cancelled"
            join_request.reviewed_at = utc_now()
            join_request.reviewed_by = user_email

            self.db.commit()

            logger.info(f"Cancelled join request {request_id} by user {user_email}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to cancel join request {request_id}: {e}")
            return False

    # ==================================================================================
    # Batch Query Methods (N+1 Query Elimination - Issue #1892)
    # ==================================================================================

    def get_member_counts_batch(self, team_ids: List[str]) -> Dict[str, int]:
        """Get member counts for multiple teams in a single query.

        This is a synchronous method following the existing service pattern.
        Note: Like other sync SQLAlchemy calls, this will block the event
        loop in async contexts. For typical team counts this is acceptable.

        Args:
            team_ids: List of team UUIDs

        Returns:
            Dict mapping team_id to member count

        Raises:
            Exception: Re-raises any database errors after rollback

        Examples:
            >>> from unittest.mock import Mock
            >>> service = TeamManagementService(Mock())
            >>> service.get_member_counts_batch([])
            {}
        """
        if not team_ids:
            return {}

        try:
            # Single query for all teams
            results = (
                self.db.query(EmailTeamMember.team_id, func.count(EmailTeamMember.id).label("count"))  # pylint: disable=not-callable
                .filter(EmailTeamMember.team_id.in_(team_ids), EmailTeamMember.is_active.is_(True))
                .group_by(EmailTeamMember.team_id)
                .all()
            )

            self.db.commit()  # Release transaction to avoid idle-in-transaction

            # Build result dict, defaulting to 0 for teams with no members
            counts = {str(row.team_id): row.count for row in results}
            return {tid: counts.get(tid, 0) for tid in team_ids}
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to get member counts for teams: {e}")
            raise

    def get_user_roles_batch(self, user_email: str, team_ids: List[str]) -> Dict[str, Optional[str]]:
        """Get a user's role in multiple teams in a single query.

        Args:
            user_email: Email of the user
            team_ids: List of team UUIDs

        Returns:
            Dict mapping team_id to role (or None if not a member)

        Raises:
            Exception: Re-raises any database errors after rollback
        """
        if not team_ids:
            return {}

        try:
            # Single query for all teams
            results = (
                self.db.query(EmailTeamMember.team_id, EmailTeamMember.role)
                .filter(EmailTeamMember.user_email == user_email, EmailTeamMember.team_id.in_(team_ids), EmailTeamMember.is_active.is_(True))
                .all()
            )

            self.db.commit()  # Release transaction to avoid idle-in-transaction

            # Build result dict - teams with no membership return None
            roles = {str(row.team_id): row.role for row in results}
            return {tid: roles.get(tid) for tid in team_ids}
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to get user roles for {user_email}: {e}")
            raise

    def get_pending_join_requests_batch(self, user_email: str, team_ids: List[str]) -> Dict[str, Optional[Any]]:
        """Get pending join requests for a user across multiple teams in a single query.

        Args:
            user_email: Email of the user
            team_ids: List of team UUIDs to check

        Returns:
            Dict mapping team_id to pending EmailTeamJoinRequest (or None if no pending request)

        Raises:
            Exception: Re-raises any database errors after rollback
        """
        if not team_ids:
            return {}

        try:
            # Single query for all pending requests across teams
            results = (
                self.db.query(EmailTeamJoinRequest).filter(EmailTeamJoinRequest.user_email == user_email, EmailTeamJoinRequest.team_id.in_(team_ids), EmailTeamJoinRequest.status == "pending").all()
            )

            self.db.commit()  # Release transaction to avoid idle-in-transaction

            # Build result dict - only one pending request per team expected
            pending_reqs = {str(req.team_id): req for req in results}
            return {tid: pending_reqs.get(tid) for tid in team_ids}
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to get pending join requests for {user_email}: {e}")
            raise

    # ==================================================================================
    # Cached Batch Methods (Redis caching for member counts)
    # ==================================================================================

    def _get_member_count_cache_key(self, team_id: str) -> str:
        """Build cache key using settings.cache_prefix for consistency.

        Args:
            team_id: Team UUID to build cache key for

        Returns:
            Cache key string in format "{prefix}team:member_count:{team_id}"
        """
        cache_prefix = getattr(settings, "cache_prefix", "mcpgw:")
        return f"{cache_prefix}team:member_count:{team_id}"

    async def get_member_counts_batch_cached(self, team_ids: List[str]) -> Dict[str, int]:
        """Get member counts for multiple teams, using Redis cache with DB fallback.

        Caching behavior is controlled by settings:
        - team_member_count_cache_enabled: Enable/disable caching (default: True)
        - team_member_count_cache_ttl: Cache TTL in seconds (default: 300)

        Args:
            team_ids: List of team UUIDs

        Returns:
            Dict mapping team_id to member count

        Raises:
            Exception: Re-raises any database errors after rollback
        """
        if not team_ids:
            return {}

        cache_enabled = getattr(settings, "team_member_count_cache_enabled", True)
        cache_ttl = getattr(settings, "team_member_count_cache_ttl", 300)

        # If caching disabled, go straight to batch DB query
        if not cache_enabled:
            return self.get_member_counts_batch(team_ids)

        try:
            redis_client = await get_redis_client()
        except Exception:
            redis_client = None

        result: Dict[str, int] = {}
        cache_misses: List[str] = []

        # Step 1: Check Redis cache for all team IDs
        if redis_client:
            try:
                cache_keys = [self._get_member_count_cache_key(tid) for tid in team_ids]
                cached_values = await redis_client.mget(cache_keys)

                for tid, cached in zip(team_ids, cached_values):
                    if cached is not None:
                        result[tid] = int(cached)
                    else:
                        cache_misses.append(tid)
            except Exception as e:
                logger.warning(f"Redis cache read failed, falling back to DB: {e}")
                cache_misses = list(team_ids)
        else:
            # No Redis available, fall back to DB
            cache_misses = list(team_ids)

        # Step 2: Query database for cache misses
        if cache_misses:
            try:
                db_results = (
                    self.db.query(EmailTeamMember.team_id, func.count(EmailTeamMember.id).label("count"))  # pylint: disable=not-callable
                    .filter(EmailTeamMember.team_id.in_(cache_misses), EmailTeamMember.is_active.is_(True))
                    .group_by(EmailTeamMember.team_id)
                    .all()
                )

                self.db.commit()

                db_counts = {str(row.team_id): row.count for row in db_results}

                # Fill in results and cache them
                for tid in cache_misses:
                    count = db_counts.get(tid, 0)
                    result[tid] = count

                    # Step 3: Cache the result with configured TTL
                    if redis_client:
                        try:
                            await redis_client.setex(self._get_member_count_cache_key(tid), cache_ttl, str(count))
                        except Exception as e:
                            logger.warning(f"Redis cache write failed for team {tid}: {e}")

            except Exception as e:
                self.db.rollback()
                logger.error(f"Failed to get member counts for teams: {e}")
                raise

        return result

    async def invalidate_team_member_count_cache(self, team_id: str) -> None:
        """Invalidate the cached member count for a team.

        Call this after any membership changes (add/remove/update).
        No-op if caching is disabled or Redis unavailable.

        Args:
            team_id: Team UUID to invalidate
        """
        cache_enabled = getattr(settings, "team_member_count_cache_enabled", True)
        if not cache_enabled:
            return

        try:
            redis_client = await get_redis_client()
            if redis_client:
                await redis_client.delete(self._get_member_count_cache_key(team_id))
        except Exception as e:
            logger.warning(f"Failed to invalidate member count cache for team {team_id}: {e}")
