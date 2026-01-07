# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/team_invitation_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Team Invitation Service.
This module provides team invitation creation, management, and acceptance
for the multi-team collaboration system.

Examples:
    >>> from mcpgateway.services.team_invitation_service import TeamInvitationService
    >>> from mcpgateway.db import SessionLocal
    >>> db = SessionLocal()
    >>> service = TeamInvitationService(db)
    >>> # Service handles team invitation lifecycle
"""

# Standard
from datetime import timedelta
import secrets
from typing import List, Optional

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailTeam, EmailTeamInvitation, EmailTeamMember, EmailUser, utc_now
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class TeamInvitationService:
    """Service for team invitation management.

    This service handles invitation creation, validation, acceptance,
    and cleanup for team membership management.

    Attributes:
        db (Session): SQLAlchemy database session

    Examples:
        >>> from mcpgateway.services.team_invitation_service import TeamInvitationService
        >>> from mcpgateway.db import SessionLocal
        >>> db = SessionLocal()
        >>> service = TeamInvitationService(db)
        >>> service.db is not None
        True
    """

    def __init__(self, db: Session):
        """Initialize the team invitation service.

        Args:
            db: SQLAlchemy database session

        Examples:
            Basic initialization:
            >>> from mcpgateway.services.team_invitation_service import TeamInvitationService
            >>> from unittest.mock import Mock
            >>> db_session = Mock()
            >>> service = TeamInvitationService(db_session)
            >>> service.db is db_session
            True

            Service attributes:
            >>> hasattr(service, 'db')
            True
            >>> service.__class__.__name__
            'TeamInvitationService'
        """
        self.db = db

    def _generate_invitation_token(self) -> str:
        """Generate a secure invitation token.

        Returns:
            str: A cryptographically secure random token

        Examples:
            Test token generation:
            >>> from mcpgateway.services.team_invitation_service import TeamInvitationService
            >>> from unittest.mock import Mock
            >>> db_session = Mock()
            >>> service = TeamInvitationService(db_session)
            >>> token = service._generate_invitation_token()
            >>> isinstance(token, str)
            True
            >>> len(token) > 0
            True

            Token characteristics:
            >>> # Test that token is URL-safe
            >>> import string
            >>> valid_chars = string.ascii_letters + string.digits + '-_'
            >>> all(c in valid_chars for c in token)
            True

            >>> # Test token length (base64-encoded 32 bytes)
            >>> len(token) >= 32  # URL-safe base64 of 32 bytes is ~43 chars
            True

            Token uniqueness:
            >>> token1 = service._generate_invitation_token()
            >>> token2 = service._generate_invitation_token()
            >>> token1 != token2
            True
        """
        return secrets.token_urlsafe(32)

    async def create_invitation(self, team_id: str, email: str, role: str, invited_by: str, expiry_days: Optional[int] = None) -> Optional[EmailTeamInvitation]:
        """Create a team invitation.

        Args:
            team_id: ID of the team
            email: Email address to invite
            role: Role to assign (owner, member)
            invited_by: Email of user sending the invitation
            expiry_days: Days until invitation expires (default from settings)

        Returns:
            EmailTeamInvitation: The created invitation or None if failed

        Raises:
            ValueError: If invitation parameters are invalid
            Exception: If invitation creation fails

        Examples:
            Team owners can send invitations to new members.
        """
        try:
            # Validate role
            valid_roles = ["owner", "member"]
            if role not in valid_roles:
                raise ValueError(f"Invalid role. Must be one of: {', '.join(valid_roles)}")

            # Check if team exists
            team = self.db.query(EmailTeam).filter(EmailTeam.id == team_id, EmailTeam.is_active.is_(True)).first()

            if not team:
                logger.warning(f"Team {team_id} not found")
                return None

            # Prevent invitations to personal teams
            if team.is_personal:
                logger.warning(f"Cannot send invitations to personal team {team_id}")
                raise ValueError("Cannot send invitations to personal teams")

            # Check if inviter exists and is a team member
            inviter = self.db.query(EmailUser).filter(EmailUser.email == invited_by).first()
            if not inviter:
                logger.warning(f"Inviter {invited_by} not found")
                return None

            # Check if inviter is a member of the team with appropriate permissions
            inviter_membership = self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == team_id, EmailTeamMember.user_email == invited_by, EmailTeamMember.is_active.is_(True)).first()

            if not inviter_membership:
                logger.warning(f"Inviter {invited_by} is not a member of team {team_id}")
                raise ValueError("Only team members can send invitations")

            # Only owners can send invitations
            if inviter_membership.role != "owner":
                logger.warning(f"User {invited_by} does not have permission to invite to team {team_id}")
                raise ValueError("Only team owners can send invitations")

            # Check if user is already a team member
            existing_member = self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == team_id, EmailTeamMember.user_email == email, EmailTeamMember.is_active.is_(True)).first()

            if existing_member:
                logger.warning(f"User {email} is already a member of team {team_id}")
                raise ValueError(f"User {email} is already a member of this team")

            # Check for existing active invitations
            existing_invitation = self.db.query(EmailTeamInvitation).filter(EmailTeamInvitation.team_id == team_id, EmailTeamInvitation.email == email, EmailTeamInvitation.is_active.is_(True)).first()

            if existing_invitation and not existing_invitation.is_expired():
                logger.warning(f"Active invitation already exists for {email} to team {team_id}")
                raise ValueError(f"An active invitation already exists for {email}")

            # Check team member limit
            if team.max_members:
                current_member_count = self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == team_id, EmailTeamMember.is_active.is_(True)).count()

                pending_invitation_count = self.db.query(EmailTeamInvitation).filter(EmailTeamInvitation.team_id == team_id, EmailTeamInvitation.is_active.is_(True)).count()

                if (current_member_count + pending_invitation_count) >= team.max_members:
                    logger.warning(f"Team {team_id} has reached maximum member limit")
                    raise ValueError(f"Team has reached maximum member limit of {team.max_members}")

            # Deactivate any existing invitations for this email/team combination
            if existing_invitation:
                existing_invitation.is_active = False

            # Set expiry
            if expiry_days is None:
                expiry_days = getattr(settings, "invitation_expiry_days", 7)
            expires_at = utc_now() + timedelta(days=expiry_days)

            # Create the invitation
            invitation = EmailTeamInvitation(
                team_id=team_id, email=email, role=role, invited_by=invited_by, invited_at=utc_now(), expires_at=expires_at, token=self._generate_invitation_token(), is_active=True
            )

            self.db.add(invitation)
            self.db.commit()

            logger.info(f"Created invitation for {email} to team {team_id} by {invited_by}")
            return invitation

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to create invitation for {email} to team {team_id}: {e}")
            raise

    async def get_invitation_by_token(self, token: str) -> Optional[EmailTeamInvitation]:
        """Get an invitation by its token.

        Args:
            token: The invitation token

        Returns:
            EmailTeamInvitation: The invitation or None if not found

        Examples:
            Used for invitation acceptance and validation.
        """
        try:
            invitation = self.db.query(EmailTeamInvitation).filter(EmailTeamInvitation.token == token).first()

            return invitation

        except Exception as e:
            logger.error(f"Failed to get invitation by token: {e}")
            return None

    async def accept_invitation(self, token: str, accepting_user_email: Optional[str] = None) -> bool:
        """Accept a team invitation.

        Args:
            token: The invitation token
            accepting_user_email: Email of user accepting (for validation)

        Returns:
            bool: True if invitation was accepted successfully, False otherwise

        Raises:
            ValueError: If invitation is invalid or expired
            Exception: If acceptance fails

        Examples:
            Users can accept invitations to join teams.
        """
        try:
            # Get the invitation
            invitation = await self.get_invitation_by_token(token)
            if not invitation:
                logger.warning("Invitation not found for token")
                raise ValueError("Invitation not found")

            # Check if invitation is valid
            if not invitation.is_valid():
                logger.warning(f"Invalid or expired invitation for {invitation.email}")
                raise ValueError("Invitation is invalid or expired")

            # Validate accepting user email if provided
            if accepting_user_email and accepting_user_email != invitation.email:
                logger.warning(f"Email mismatch: invitation for {invitation.email}, accepting as {accepting_user_email}")
                raise ValueError("Email address does not match invitation")

            # Check if user exists (if email provided, they must exist)
            if accepting_user_email:
                user = self.db.query(EmailUser).filter(EmailUser.email == accepting_user_email).first()
                if not user:
                    logger.warning(f"User {accepting_user_email} not found")
                    raise ValueError("User account not found")

            # Check if team still exists
            team = self.db.query(EmailTeam).filter(EmailTeam.id == invitation.team_id, EmailTeam.is_active.is_(True)).first()

            if not team:
                logger.warning(f"Team {invitation.team_id} not found or inactive")
                raise ValueError("Team not found or inactive")

            # Check if user is already a member
            existing_member = (
                self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == invitation.team_id, EmailTeamMember.user_email == invitation.email, EmailTeamMember.is_active.is_(True)).first()
            )

            if existing_member:
                logger.warning(f"User {invitation.email} is already a member of team {invitation.team_id}")
                # Deactivate the invitation since they're already a member
                invitation.is_active = False
                self.db.commit()
                raise ValueError("User is already a member of this team")

            # Check team member limit
            if team.max_members:
                current_member_count = self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == invitation.team_id, EmailTeamMember.is_active.is_(True)).count()
                if current_member_count >= team.max_members:
                    logger.warning(f"Team {invitation.team_id} has reached maximum member limit")
                    raise ValueError(f"Team has reached maximum member limit of {team.max_members}")

            # Create team membership
            membership = EmailTeamMember(team_id=invitation.team_id, user_email=invitation.email, role=invitation.role, joined_at=utc_now(), invited_by=invitation.invited_by, is_active=True)

            self.db.add(membership)

            # Deactivate the invitation
            invitation.is_active = False

            self.db.commit()

            # Invalidate auth cache for user's team membership
            try:
                # Standard
                import asyncio  # pylint: disable=import-outside-toplevel

                # First-Party
                from mcpgateway.cache.auth_cache import auth_cache  # pylint: disable=import-outside-toplevel

                asyncio.create_task(auth_cache.invalidate_team(invitation.email))
                asyncio.create_task(auth_cache.invalidate_user_role(invitation.email, invitation.team_id))
                asyncio.create_task(auth_cache.invalidate_user_teams(invitation.email))
                asyncio.create_task(auth_cache.invalidate_team_membership(invitation.email))
            except Exception as cache_error:
                logger.debug(f"Failed to invalidate cache on invitation acceptance: {cache_error}")

            logger.info(f"User {invitation.email} accepted invitation to team {invitation.team_id}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to accept invitation: {e}")
            raise

    async def decline_invitation(self, token: str, declining_user_email: Optional[str] = None) -> bool:
        """Decline a team invitation.

        Args:
            token: The invitation token
            declining_user_email: Email of user declining (for validation)

        Returns:
            bool: True if invitation was declined successfully, False otherwise

        Examples:
            Users can decline invitations they don't want to accept.
        """
        try:
            # Get the invitation
            invitation = await self.get_invitation_by_token(token)
            if not invitation:
                logger.warning("Invitation not found for token")
                return False

            # Validate declining user email if provided
            if declining_user_email and declining_user_email != invitation.email:
                logger.warning(f"Email mismatch: invitation for {invitation.email}, declining as {declining_user_email}")
                return False

            # Deactivate the invitation
            invitation.is_active = False
            self.db.commit()

            logger.info(f"User {invitation.email} declined invitation to team {invitation.team_id}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to decline invitation: {e}")
            return False

    async def revoke_invitation(self, invitation_id: str, revoked_by: str) -> bool:
        """Revoke a team invitation.

        Args:
            invitation_id: ID of the invitation to revoke
            revoked_by: Email of user revoking the invitation

        Returns:
            bool: True if invitation was revoked successfully, False otherwise

        Examples:
            Team owners can revoke pending invitations.
        """
        try:
            # Get the invitation
            invitation = self.db.query(EmailTeamInvitation).filter(EmailTeamInvitation.id == invitation_id, EmailTeamInvitation.is_active.is_(True)).first()

            if not invitation:
                logger.warning(f"Active invitation {invitation_id} not found")
                return False

            # Check if revoker has permission
            revoker_membership = (
                self.db.query(EmailTeamMember).filter(EmailTeamMember.team_id == invitation.team_id, EmailTeamMember.user_email == revoked_by, EmailTeamMember.is_active.is_(True)).first()
            )

            if not revoker_membership or revoker_membership.role != "owner":
                logger.warning(f"User {revoked_by} does not have permission to revoke invitation {invitation_id}")
                return False

            # Revoke the invitation
            invitation.is_active = False
            self.db.commit()

            logger.info(f"Invitation {invitation_id} revoked by {revoked_by}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to revoke invitation {invitation_id}: {e}")
            return False

    async def get_team_invitations(self, team_id: str, active_only: bool = True) -> List[EmailTeamInvitation]:
        """Get all invitations for a team.

        Args:
            team_id: ID of the team
            active_only: Whether to return only active invitations

        Returns:
            List[EmailTeamInvitation]: List of team invitations

        Examples:
            Team management interface showing pending invitations.
        """
        try:
            query = self.db.query(EmailTeamInvitation).filter(EmailTeamInvitation.team_id == team_id)

            if active_only:
                query = query.filter(EmailTeamInvitation.is_active.is_(True))

            invitations = query.order_by(EmailTeamInvitation.invited_at.desc()).all()
            return invitations

        except Exception as e:
            logger.error(f"Failed to get invitations for team {team_id}: {e}")
            return []

    async def get_user_invitations(self, email: str, active_only: bool = True) -> List[EmailTeamInvitation]:
        """Get all invitations for a user.

        Args:
            email: Email address of the user
            active_only: Whether to return only active invitations

        Returns:
            List[EmailTeamInvitation]: List of invitations for the user

        Examples:
            User dashboard showing pending team invitations.
        """
        try:
            query = self.db.query(EmailTeamInvitation).filter(EmailTeamInvitation.email == email)

            if active_only:
                query = query.filter(EmailTeamInvitation.is_active.is_(True))

            invitations = query.order_by(EmailTeamInvitation.invited_at.desc()).all()
            return invitations

        except Exception as e:
            logger.error(f"Failed to get invitations for user {email}: {e}")
            return []

    async def cleanup_expired_invitations(self) -> int:
        """Clean up expired invitations.

        Returns:
            int: Number of invitations cleaned up

        Examples:
            Periodic cleanup task to remove expired invitations.
        """
        try:
            now = utc_now()
            expired_count = self.db.query(EmailTeamInvitation).filter(EmailTeamInvitation.expires_at < now, EmailTeamInvitation.is_active.is_(True)).update({"is_active": False})

            self.db.commit()

            if expired_count > 0:
                logger.info(f"Cleaned up {expired_count} expired invitations")

            return expired_count

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to cleanup expired invitations: {e}")
            return 0
