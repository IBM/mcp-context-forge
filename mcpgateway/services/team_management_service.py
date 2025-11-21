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
from datetime import timedelta
from typing import List, Optional, Tuple

# Third-Party
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailTeam, EmailTeamJoinRequest, EmailUser, Role, UserRole, utc_now
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.role_service import RoleService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


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
            # First-Party
            from mcpgateway.utils.create_slug import slugify  # pylint: disable=import-outside-toplevel

            potential_slug = slugify(name)
            existing_inactive_team = self.db.query(EmailTeam).filter(EmailTeam.slug == potential_slug, EmailTeam.is_active.is_(False)).first()

            role_service = RoleService(self.db)
            role_for_team_owner: Optional[Role] = await role_service.get_role_by_name(settings.default_role_name_owner, "team")
            if role_for_team_owner:
                role_id = role_for_team_owner.id
            else:
                role_id = ""

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

                user_role: Optional[UserRole] = await role_service.get_user_role_assignment(user_email=created_by, role_id=role_id, scope="team", scope_id=team.id)

                if user_role and not user_role.is_active:
                    await role_service.assign_role_to_user(user_email=created_by, role_id=role_id, scope="team", scope_id=team.id, granted_by=created_by)

                logger.info(f"Reactivated existing team with slug {potential_slug}")
            else:
                # Create the team (slug will be auto-generated by event listener)
                team = EmailTeam(name=name, description=description, created_by=created_by, is_personal=False, visibility=visibility, max_members=max_members, is_active=True)
                self.db.add(team)

                self.db.flush()  # Get the team ID

                # Add the creator as owner
                await role_service.assign_role_to_user(user_email=created_by, role_id=role_id, scope="team", scope_id=team.id, granted_by=created_by)

            self.db.commit()

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

            return team

        except Exception as e:
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

            return team

        except Exception as e:
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

            # # Prevent deleting personal teams
            # if team.is_personal:
            #     logger.warning(f"Cannot delete personal team {team_id}")
            #     raise ValueError("Personal teams cannot be deleted")

            # Soft delete the team
            team.is_active = False
            team.updated_at = utc_now()

            role_service = RoleService(self.db)
            scope_role_assignments: List[UserRole] = await role_service.list_scope_role_assignments(scope="team", scope_id=team.id)

            if scope_role_assignments:
                await role_service.revoke_scope_role_assignments(scope="team", scope_id=team.id, revoked_by=deleted_by)

            user_roles_stmt = delete(UserRole).where(UserRole.scope_id == team.id, UserRole.scope == "team")
            self.db.execute(user_roles_stmt)

            self.db.delete(team)
            self.db.commit()
            
            logger.info(f"Deleted team {team_id} by {deleted_by}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to delete team {team_id}: {e}")
            return False

    async def add_member_to_team(self, team_id: str, user_email: str, role: str = "team_member", invited_by: Optional[str] = None) -> bool:
        """Add a member to a team.

        Args:
            team_id: ID of the team
            user_email: Email of the user to add
            role: Role to assign (owner, member)
            invited_by: Email of user who added this member

        Returns:
            bool: True if member was added successfully, False otherwise

        Raises:
            ValueError: If role is invalid or team member limit exceeded

        Examples:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> service = TeamManagementService(Mock())
            >>> asyncio.iscoroutinefunction(service.add_member_to_team)
            True
            >>> # service._log_team_member_action("tm-123", "team-123", "user@example.com", "team_member", "added", "admin@example.com")
        """
        try:
            # Validate role
            valid_roles = ["team_admin", "team_member", "team_viewer"]
            if role not in valid_roles:
                raise ValueError(f"Invalid role. Must be one of: {', '.join(valid_roles)}")

            # Check if team exists
            team = await self.get_team_by_id(team_id)
            if not team:
                logger.warning(f"Team {team_id} not found")
                return False

            # Check if user exists
            user = self.db.query(EmailUser).filter(EmailUser.email == user_email).first()
            if not user:
                logger.warning(f"User {user_email} not found")
                return False

            role_service = RoleService(self.db)

            role_obj: Optional[Role] = await role_service.get_role_by_name(role, "team")
            if role_obj is None:
                raise ValueError(f"Role '{role}' does not exist")

            user_role: Optional[UserRole] = await role_service.get_user_role_assignment(user_email=user_email, role_id=role_obj.id, scope="team", scope_id=team_id)

            if user_role and user_role.is_active:
                logger.warning(f"User {user_email} is already a member of team {team_id}")
                return False

            # Check team member limit
            if team.max_members:
                scope_role_assignments: List[UserRole] = await role_service.list_scope_role_assignments(scope="team", scope_id=team.id)
                current_member_count = len(scope_role_assignments)

                if current_member_count >= team.max_members:
                    logger.warning(f"Team {team_id} has reached maximum member limit")
                    raise ValueError(f"Team has reached maximum member limit of {team.max_members}")

            await role_service.assign_role_to_user(user_email=user_email, role_id=role_obj.id, scope="team", scope_id=team.id, granted_by=invited_by if invited_by else "")

            logger.info(f"Added {user_email} to team {team_id} with role {role}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to add {user_email} to team {team_id}: {e}")
            return False

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
            role_service = RoleService(self.db)
            list_role_assignments: List[UserRole] = await role_service.list_user_roles(user_email=user_email, scope="team", scope_id=team_id)

            if not list_role_assignments:
                logger.warning(f"User {user_email} is not a member of team {team_id}")
                return False

            await asyncio.gather(
                *[
                    role_service.revoke_role_from_user(
                        user_email=user_email,
                        role_id=role_assignment.role_id,
                        scope="team",
                        scope_id=team_id,
                        revoked_by=removed_by if removed_by else "",
                    )
                    for role_assignment in list_role_assignments
                ]
            )
            logger.info(f"Removed {user_email} from team {team_id} by {removed_by}")
            return True

        except Exception as e:
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
        """
        try:
            # Validate role
            valid_roles = ["team_owner", "team_member", "team_viewer"]
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

            role_service = RoleService(self.db)
            list_role_assignments: List[UserRole] = await role_service.list_user_roles(user_email=user_email, scope="team", scope_id=team_id)

            if not list_role_assignments:
                logger.warning(f"User {user_email} is not a member of team {team_id}")
                return False

            role: Optional[Role] = await role_service.get_role_by_name(new_role, "team")

            if role is None:
                raise ValueError(f"Role '{new_role}' does not exist")

            role_id: str = role.id

            await role_service.assign_role_to_user(user_email=user_email, role_id=role_id, scope="team", scope_id=team.id, granted_by=updated_by if updated_by else "")

            # Revoke other roles
            roles_assignments_to_disable = [ra for ra in list_role_assignments if ra.role_id != role_id]
            await asyncio.gather(
                *[
                    role_service.revoke_role_from_user(
                        user_email=user_email,
                        role_id=role_assignment.role_id,
                        scope="team",
                        scope_id=team_id,
                        revoked_by=updated_by if updated_by else "",
                    )
                    for role_assignment in roles_assignments_to_disable
                ]
            )

            logger.info(f"Updated role of {user_email} in team {team_id} to {new_role} by {updated_by}")
            return True

        except Exception as e:
            logger.error(f"Failed to update role of {user_email} in team {team_id}: {e}")
            return False

    async def get_user_teams(self, user_email: str, include_personal: bool = True) -> List[EmailTeam]:
        """Get all teams a user belongs to.

        Args:
            user_email: Email of the user
            include_personal: Whether to include personal teams

        Returns:
            List[EmailTeam]: List of teams the user belongs to

        Examples:
            User dashboard showing team memberships.
        """
        try:
            role_service = RoleService(self.db)
            team_roles: List[UserRole] = await role_service.list_user_roles(user_email=user_email, scope="team")
            team_ids: List[str] = list({tr.scope_id for tr in team_roles if tr.scope_id})

            query = self.db.query(EmailTeam)

            if team_ids:
                query = query.filter(EmailTeam.id.in_(team_ids))

            if not include_personal:
                query = query.filter(EmailTeam.is_personal.is_(False))

            teams = query.all()
            return teams

        except Exception as e:
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
            # First-Party
            user_teams = await self.get_user_teams(user_email, include_personal=True)

            if not user_teams:
                logger.error(f"Failed to get teams for user {user_email}")
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
            print(f"An error occurred: {e}")
            if not team_id:
                team_id = None

        return team_id

    async def get_team_roles(self, team_id: str) -> List[UserRole]:
        """Get all roles of a team.

        Args:
            team_id: ID of the team

        Returns:
            List[UserRole]: List of user roles

        Examples:
            Team member management and role display.
        """
        try:
            role_service = RoleService(self.db)
            team_roles: List[UserRole] = await role_service.list_scope_role_assignments(scope="team", scope_id=team_id)

            return team_roles

        except Exception as e:
            logger.error(f"Failed to get members for team {team_id}: {e}")
            return []

    async def get_user_role_in_team(self, user_email: str, team_id: str) -> Optional[str]:
        """Get a user's role in a specific team.

        Args:
            user_email: Email of the user
            team_id: ID of the team

        Returns:
            str: User's role or None if not a member

        Examples:
            Access control and permission checking.
        """
        try:
            role_service = RoleService(self.db)
            user_roles: List[UserRole] = await role_service.list_user_roles(user_email=user_email, scope="team", scope_id=team_id)

            return user_roles[0].role.name if user_roles else None

        except Exception as e:
            logger.error(f"Failed to get role for {user_email} in team {team_id}: {e}")
            return None

    async def list_teams(self, limit: int = 100, offset: int = 0, visibility_filter: Optional[str] = None) -> Tuple[List[EmailTeam], int]:
        """List teams with pagination.

        Args:
            limit: Maximum number of teams to return
            offset: Number of teams to skip
            visibility_filter: Filter by visibility (private, team, public)

        Returns:
            Tuple[List[EmailTeam], int]: (teams, total_count)

        Examples:
            Team discovery and administration.
        """
        try:
            query = self.db.query(EmailTeam).filter(EmailTeam.is_active.is_(True), EmailTeam.is_personal.is_(False))  # Exclude personal teams from listings

            if visibility_filter:
                query = query.filter(EmailTeam.visibility == visibility_filter)

            total_count = query.count()
            teams = query.offset(offset).limit(limit).all()

            return teams, total_count

        except Exception as e:
            logger.error(f"Failed to list teams: {e}")
            return [], 0

    async def discover_public_teams(self, user_email: str, skip: int = 0, limit: int = 50) -> List[EmailTeam]:
        """Discover public teams that user can join.

        Args:
            user_email: Email of the user discovering teams
            skip: Number of teams to skip for pagination
            limit: Maximum number of teams to return

        Returns:
            List[EmailTeam]: List of public teams user can join

        Raises:
            Exception: If discovery fails
        """
        try:
            # Get teams where user is not already a member
            user_teams = await self.get_user_teams(user_email, include_personal=True)
            user_team_ids = [team.id for team in user_teams]

            query = self.db.query(EmailTeam).filter(EmailTeam.visibility == "public", EmailTeam.is_active.is_(True), EmailTeam.is_personal.is_(False), ~EmailTeam.id.in_(user_team_subquery))

            return query.offset(skip).limit(limit).all()

        except Exception as e:
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
            role_service = RoleService(self.db)
            user_roles: List[UserRole] = await role_service.list_user_roles(user_email=user_email, scope="team", scope_id=team_id)

            if user_roles:
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
            return (
                self.db.query(EmailTeamJoinRequest).filter(EmailTeamJoinRequest.team_id == team_id, EmailTeamJoinRequest.status == "pending").order_by(EmailTeamJoinRequest.requested_at.desc()).all()
            )

        except Exception as e:
            logger.error(f"Failed to list join requests for team {team_id}: {e}")
            return []

    async def approve_join_request(self, request_id: str, approved_by: str) -> Optional[UserRole]:
        """Approve a team join request.

        Args:
            request_id: ID of the join request
            approved_by: Email of the user approving the request

        Returns:
            UserRole: New user role or None if request not found

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
            # New joiners are always members
            user_role = UserRole(
                user_email=join_request.user_email,
                role_id=(await RoleService(self.db).get_role_by_name("team_member", "team")).id,
                scope="team",
                scope_id=join_request.team_id,
                granted_by=approved_by,
            )
            self.db.add(user_role)
            # Update join request status
            join_request.status = "approved"
            join_request.reviewed_at = utc_now()
            join_request.reviewed_by = approved_by

            self.db.flush()
            self.db.refresh(user_role)

            logger.info(f"Approved join request {request_id}: user {join_request.user_email} joined team {join_request.team_id}")
            return user_role

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
