# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/teams.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Team Management API Routes.
Provides team management endpoints:
- Team creation and management
- Team membership management
- Team invitations
- Team-scoped resource access
"""

# Standard
from datetime import timedelta
import logging
from typing import List

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user, get_db
from mcpgateway.db import Team, TeamInvitation, TeamMember, User, utc_now
from mcpgateway.schemas import ErrorResponse, TeamCreate, TeamInviteRequest, TeamInviteResponse, TeamMemberResponse, TeamResponse, TeamRole, TeamUpdate, UpdateMemberRoleRequest
from mcpgateway.utils.create_slug import slugify

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/teams", tags=["Team Management"])


@router.post(
    "/",
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        409: {"model": ErrorResponse, "description": "Team name already exists"},
    },
)
@router.post("", include_in_schema=False)  # Support both /teams and /teams/
async def create_team(request: Request, team_data: TeamCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Create a new team.

    Creates a new team with the current user as the owner.
    """
    # Check if team name already exists
    slug = slugify(team_data.name)
    existing_team = db.query(Team).filter(Team.slug == slug).first()

    if existing_team:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Team name already exists")

    # Create team
    team = Team(name=team_data.name, slug=slug, description=team_data.description, created_by=current_user.id, is_active=True)

    db.add(team)
    db.flush()  # Get the team ID

    # Add creator as team owner
    membership = TeamMember(team_id=team.id, user_id=current_user.id, role=TeamRole.OWNER.value)

    db.add(membership)
    db.commit()
    db.refresh(team)

    logger.info(f"Team created by {current_user.username}: {team.name}")

    # Return team with member count
    member_count = db.query(TeamMember).filter(TeamMember.team_id == team.id).count()

    response = TeamResponse(
        id=team.id,
        name=team.name,
        slug=team.slug,
        description=team.description,
        created_by=team.created_by,
        created_at=team.created_at,
        updated_at=team.updated_at,
        is_active=team.is_active,
        member_count=member_count,
    )
    return response


@router.get("/", include_in_schema=True)
@router.get("", include_in_schema=False)  # Support both /teams and /teams/
async def list_teams(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    include_all: bool = Query(False, description="Include all teams (admin only)"),
):
    """
    List teams.

    Returns teams that the user is a member of, or all teams if admin and include_all=True.
    """
    if include_all and current_user.is_admin:
        # Admin can see all teams
        teams = db.query(Team).filter(Team.is_active.is_(True)).all()
    else:
        # Regular users see only their teams
        user_team_ids = db.query(TeamMember.team_id).filter(TeamMember.user_id == current_user.id).subquery()
        teams = db.query(Team).filter(Team.id.in_(user_team_ids), Team.is_active.is_(True)).all()

    # Add member counts to all teams
    result = []
    for team in teams:
        member_count = db.query(TeamMember).filter(TeamMember.team_id == team.id).count()

        team_dict = {
            "id": team.id,
            "name": team.name,
            "slug": team.slug,
            "description": team.description,
            "created_by": team.created_by,
            "created_at": team.created_at.isoformat(),
            "updated_at": team.updated_at.isoformat(),
            "is_active": team.is_active,
            "member_count": member_count,
        }
        result.append(team_dict)

    return result


@router.get(
    "/{team_id}/members",
    response_model=List[TeamMemberResponse],
    responses={404: {"model": ErrorResponse, "description": "Team not found"}, 403: {"model": ErrorResponse, "description": "Not a team member"}},
)
async def list_team_members(team_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    List team members.

    Returns all members of the team if user is a member or admin.
    """
    # Verify team exists
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # Check if user is team member or admin
    if not current_user.is_admin:
        membership = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.user_id == current_user.id).first()

        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this team")

    # Get all team members with user info
    members = db.query(TeamMember).join(User).filter(TeamMember.team_id == team_id).all()

    result = []
    for member in members:
        user = member.user
        result.append(
            TeamMemberResponse(
                id=member.id,
                user_id=user.id,
                username=user.username,
                email=user.email,
                full_name=user.full_name,
                role=TeamRole(member.role),
                joined_at=member.joined_at,
                invited_by=member.invited_by,
            )
        )

    return result


@router.post(
    "/{team_id}/invite",
    response_model=TeamInviteResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Team not found"},
        403: {"model": ErrorResponse, "description": "Not authorized to invite members"},
        409: {"model": ErrorResponse, "description": "User already invited or is member"},
    },
)
async def invite_team_member(team_id: str, request: Request, invite_data: TeamInviteRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Invite a new team member.

    Requires team owner or admin role to invite new members.
    """
    # Verify team exists
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # Check if user can invite (team owner/admin or system admin)
    if not current_user.is_admin:
        membership = (
            db.query(TeamMember)
            .filter(
                TeamMember.team_id == team_id,
                TeamMember.user_id == current_user.id,
                TeamMember.role.in_([TeamRole.OWNER.value, TeamRole.ADMIN.value]),
            )
            .first()
        )

        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team owners/admins can invite members")

    # Check if user is already a member
    existing_member = db.query(TeamMember).join(User).filter(TeamMember.team_id == team_id, User.email == invite_data.email).first()

    if existing_member:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already a team member")

    # Check if invitation already exists
    existing_invite = db.query(TeamInvitation).filter(TeamInvitation.team_id == team_id, TeamInvitation.email == invite_data.email, TeamInvitation.is_active.is_(True)).first()

    if existing_invite:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invitation already sent to this email")

    # Create invitation
    # Standard
    import secrets

    invitation = TeamInvitation(
        team_id=team_id,
        email=invite_data.email,
        role=invite_data.role.value,
        invited_by=current_user.id,
        expires_at=utc_now() + timedelta(days=7),  # 7-day expiration
        token=secrets.token_urlsafe(32),
        is_active=True,
    )

    db.add(invitation)
    db.commit()
    db.refresh(invitation)

    logger.info(f"Team invitation sent by {current_user.username} to {invite_data.email} for team {team.name}")

    return TeamInviteResponse.from_orm(invitation)


# Complete team management endpoints


@router.delete(
    "/{team_id}/members/{user_id}",
    responses={
        200: {"description": "Member removed successfully"},
        404: {"model": ErrorResponse, "description": "Team or member not found"},
        403: {"model": ErrorResponse, "description": "Not authorized to remove members"},
        400: {"model": ErrorResponse, "description": "Cannot remove last owner"},
    },
)
async def remove_team_member(team_id: str, user_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Remove a team member.

    Requires team owner/admin role. Cannot remove the last owner.
    """
    # Verify team exists
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # Check authorization
    if not current_user.is_admin:
        requester_membership = (
            db.query(TeamMember)
            .filter(
                TeamMember.team_id == team_id,
                TeamMember.user_id == current_user.id,
                TeamMember.role.in_([TeamRole.OWNER.value, TeamRole.ADMIN.value]),
            )
            .first()
        )

        if not requester_membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team owners/admins can remove members")

    # Find the member to remove
    member = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.user_id == user_id).first()

    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found in team")

    # Prevent removing the last owner
    if member.role == TeamRole.OWNER.value:
        owner_count = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.role == TeamRole.OWNER.value).count()

        if owner_count <= 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove the last team owner")

    # Remove the member
    db.delete(member)
    db.commit()

    # Get user info for logging
    user = db.query(User).filter(User.id == user_id).first()
    username = user.username if user else user_id

    logger.info(f"User {username} removed from team {team.name} by {current_user.username}")

    return {"message": f"Member {username} removed from team successfully"}


@router.put(
    "/{team_id}",
    response_model=TeamResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Team not found"},
        403: {"model": ErrorResponse, "description": "Not authorized to update team"},
        409: {"model": ErrorResponse, "description": "Team name already exists"},
    },
)
async def update_team(team_id: str, team_data: TeamUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Update team information.

    Requires team owner/admin role or system admin.
    """
    # Verify team exists
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # Check authorization
    if not current_user.is_admin:
        membership = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.user_id == current_user.id, TeamMember.role.in_([TeamRole.OWNER.value, TeamRole.ADMIN.value])).first()

        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team owners/admins can update team")

    # Check if new name conflicts with existing teams
    if team_data.name and team_data.name != team.name:
        new_slug = slugify(team_data.name)
        existing_team = db.query(Team).filter(Team.slug == new_slug, Team.id != team_id).first()

        if existing_team:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Team name already exists")

        team.name = team_data.name
        team.slug = new_slug

    # Update other fields
    if team_data.description is not None:
        team.description = team_data.description

    if team_data.is_active is not None:
        team.is_active = team_data.is_active

    team.updated_at = utc_now()
    db.commit()
    db.refresh(team)

    logger.info(f"Team {team.name} updated by {current_user.username}")

    # Return team with member count
    member_count = db.query(TeamMember).filter(TeamMember.team_id == team.id).count()

    response = TeamResponse(
        id=team.id,
        name=team.name,
        slug=team.slug,
        description=team.description,
        created_by=team.created_by,
        created_at=team.created_at,
        updated_at=team.updated_at,
        is_active=team.is_active,
        member_count=member_count,
    )
    return response


@router.delete(
    "/{team_id}",
    responses={
        200: {"description": "Team deleted successfully"},
        404: {"model": ErrorResponse, "description": "Team not found"},
        403: {"model": ErrorResponse, "description": "Not authorized to delete team"},
        400: {"model": ErrorResponse, "description": "Cannot delete team with members"},
    },
)
async def delete_team(team_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Delete a team.

    Requires team owner role or system admin.
    Team must have no members before deletion.
    """
    # Verify team exists
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # Check authorization (only team owners or system admins can delete)
    if not current_user.is_admin:
        membership = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.user_id == current_user.id, TeamMember.role == TeamRole.OWNER.value).first()

        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team owners can delete teams")

    # Check if team has members
    member_count = db.query(TeamMember).filter(TeamMember.team_id == team_id).count()
    if member_count > 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot delete team with {member_count} members. Remove all members first.")

    team_name = team.name
    db.delete(team)
    db.commit()

    logger.warning(f"Team {team_name} deleted by {current_user.username}")

    return {"message": f"Team '{team_name}' deleted successfully"}


@router.put(
    "/{team_id}/members/{user_id}/role",
    response_model=TeamMemberResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Team or member not found"},
        403: {"model": ErrorResponse, "description": "Not authorized to change roles"},
        400: {"model": ErrorResponse, "description": "Cannot change role of last owner"},
    },
)
async def update_member_role(team_id: str, user_id: str, role_data: UpdateMemberRoleRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Update team member role.

    Requires team owner/admin role. Cannot demote the last owner.
    """
    # Verify team exists
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # Check authorization
    if not current_user.is_admin:
        requester_membership = (
            db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.user_id == current_user.id, TeamMember.role.in_([TeamRole.OWNER.value, TeamRole.ADMIN.value])).first()
        )

        if not requester_membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team owners/admins can change roles")

    # Find the member to update
    member = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.user_id == user_id).first()

    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found in team")

    # Prevent demoting the last owner
    if member.role == TeamRole.OWNER.value and role_data.role != TeamRole.OWNER:
        owner_count = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.role == TeamRole.OWNER.value).count()

        if owner_count <= 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot demote the last team owner")

    # Update role
    old_role = member.role
    member.role = role_data.role.value
    db.commit()
    db.refresh(member)

    # Get user info for response
    user_obj = member.user

    logger.info(f"User {user_obj.username} role changed from {old_role} to {role_data.role.value} in team {team.name} by {current_user.username}")

    return TeamMemberResponse(
        id=member.id,
        user_id=user_obj.id,
        username=user_obj.username,
        email=user_obj.email,
        full_name=user_obj.full_name,
        role=TeamRole(member.role),
        joined_at=member.joined_at,
        invited_by=member.invited_by,
    )


@router.post(
    "/{team_id}/leave",
    responses={
        200: {"description": "Left team successfully"},
        404: {"model": ErrorResponse, "description": "Team not found"},
        400: {"model": ErrorResponse, "description": "Cannot leave team as last owner"},
    },
)
async def leave_team(team_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Leave a team.

    Cannot leave if you're the last owner.
    """
    # Verify team exists
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # Find user's membership
    membership = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.user_id == current_user.id).first()

    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="You are not a member of this team")

    # Prevent last owner from leaving
    if membership.role == TeamRole.OWNER.value:
        owner_count = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.role == TeamRole.OWNER.value).count()

        if owner_count <= 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot leave team as the last owner. Transfer ownership or delete the team.")

    # Remove membership
    db.delete(membership)
    db.commit()

    logger.info(f"User {current_user.username} left team {team.name}")

    return {"message": f"Successfully left team '{team.name}'"}


@router.get(
    "/{team_id}/invitations",
    response_model=List[TeamInviteResponse],
    responses={
        404: {"model": ErrorResponse, "description": "Team not found"},
        403: {"model": ErrorResponse, "description": "Not a team member"},
    },
)
async def list_team_invitations(team_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), include_expired: bool = False):
    """
    List pending team invitations.

    Returns pending invitations for the team if user is a member or admin.
    """
    # Verify team exists
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # Check if user is team member or admin
    if not current_user.is_admin:
        membership = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.user_id == current_user.id).first()

        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this team")

    # Get invitations
    query = db.query(TeamInvitation).filter(TeamInvitation.team_id == team_id)

    if not include_expired:
        query = query.filter(TeamInvitation.is_active.is_(True), TeamInvitation.expires_at > utc_now())

    invitations = query.order_by(TeamInvitation.invited_at.desc()).all()

    return [TeamInviteResponse.from_orm(invitation) for invitation in invitations]


@router.delete(
    "/{team_id}/invitations/{invitation_id}",
    responses={
        200: {"description": "Invitation cancelled successfully"},
        404: {"model": ErrorResponse, "description": "Team or invitation not found"},
        403: {"model": ErrorResponse, "description": "Not authorized to cancel invitation"},
    },
)
async def cancel_team_invitation(team_id: str, invitation_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Cancel a team invitation.

    Requires team owner/admin role or system admin.
    """
    # Verify team exists
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # Check authorization
    if not current_user.is_admin:
        membership = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.user_id == current_user.id, TeamMember.role.in_([TeamRole.OWNER.value, TeamRole.ADMIN.value])).first()

        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team owners/admins can cancel invitations")

    # Find the invitation
    invitation = db.query(TeamInvitation).filter(TeamInvitation.id == invitation_id, TeamInvitation.team_id == team_id).first()

    if not invitation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")

    # Cancel the invitation
    invitation.is_active = False
    db.commit()

    logger.info(f"Team invitation cancelled by {current_user.username} for {invitation.email} to team {team.name}")

    return {"message": f"Invitation to {invitation.email} cancelled successfully"}


@router.post(
    "/{team_id}/invitations/{invitation_id}/resend",
    response_model=TeamInviteResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Team or invitation not found"},
        403: {"model": ErrorResponse, "description": "Not authorized to resend invitation"},
        400: {"model": ErrorResponse, "description": "Cannot resend expired or accepted invitation"},
    },
)
async def resend_team_invitation(team_id: str, invitation_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Resend a team invitation with new expiration.

    Requires team owner/admin role or system admin.
    """
    # Verify team exists
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # Check authorization
    if not current_user.is_admin:
        membership = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.user_id == current_user.id, TeamMember.role.in_([TeamRole.OWNER.value, TeamRole.ADMIN.value])).first()

        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team owners/admins can resend invitations")

    # Find the invitation
    invitation = db.query(TeamInvitation).filter(TeamInvitation.id == invitation_id, TeamInvitation.team_id == team_id).first()

    if not invitation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")

    # Check if invitation can be resent
    if invitation.accepted_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot resend accepted invitation")

    # Update invitation with new expiration and token
    # Standard
    import secrets

    invitation.expires_at = utc_now() + timedelta(days=7)
    invitation.token = secrets.token_urlsafe(32)
    invitation.is_active = True
    invitation.invited_at = utc_now()  # Update invite timestamp
    db.commit()
    db.refresh(invitation)

    logger.info(f"Team invitation resent by {current_user.username} to {invitation.email} for team {team.name}")

    return TeamInviteResponse.from_orm(invitation)


@router.post(
    "/accept-invitation/{token}",
    responses={
        200: {"description": "Invitation accepted successfully"},
        404: {"model": ErrorResponse, "description": "Invitation not found or expired"},
        409: {"model": ErrorResponse, "description": "User already a team member"},
    },
)
async def accept_team_invitation(token: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Accept a team invitation using invitation token.

    User must be logged in and invitation must be valid and not expired.
    """
    # Find the invitation by token
    invitation = db.query(TeamInvitation).filter(TeamInvitation.token == token, TeamInvitation.is_active.is_(True)).first()

    if not invitation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found or expired")

    # Check if invitation is expired
    if invitation.expires_at < utc_now():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation has expired")

    # Check if user email matches invitation
    if current_user.email != invitation.email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invitation email does not match your account email")

    # Check if user is already a team member
    existing_membership = db.query(TeamMember).filter(TeamMember.team_id == invitation.team_id, TeamMember.user_id == current_user.id).first()

    if existing_membership:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You are already a member of this team")

    # Accept the invitation
    membership = TeamMember(team_id=invitation.team_id, user_id=current_user.id, role=invitation.role, invited_by=invitation.invited_by)

    db.add(membership)

    # Mark invitation as accepted
    invitation.accepted_at = utc_now()
    invitation.accepted_by = current_user.id
    invitation.is_active = False

    db.commit()
    db.refresh(membership)

    team = invitation.team
    logger.info(f"User {current_user.username} accepted invitation to team {team.name}")

    return {"message": f"Successfully joined team '{team.name}'", "team_id": team.id, "team_name": team.name, "role": membership.role}


@router.get(
    "/my-invitations",
    response_model=List[TeamInviteResponse],
    responses={
        200: {"description": "List of pending invitations for current user"},
    },
)
async def list_my_invitations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    List pending team invitations for the current user.

    Returns invitations sent to the user's email address.
    """
    if not current_user.email:
        return []

    # Get pending invitations for user's email
    invitations = (
        db.query(TeamInvitation)
        .filter(TeamInvitation.email == current_user.email, TeamInvitation.is_active.is_(True), TeamInvitation.expires_at > utc_now(), TeamInvitation.accepted_at.is_(None))
        .order_by(TeamInvitation.invited_at.desc())
        .all()
    )

    return [TeamInviteResponse.from_orm(invitation) for invitation in invitations]


@router.get(
    "/my-teams",
    response_model=List[TeamResponse],
    responses={
        200: {"description": "List of teams user belongs to"},
    },
)
async def list_my_teams(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    List teams that the current user belongs to.

    Returns all teams where the user is a member, along with their role.
    """
    # Get user's team memberships
    memberships = db.query(TeamMember).filter(TeamMember.user_id == current_user.id).all()

    result = []
    for membership in memberships:
        team = membership.team
        if team.is_active:
            member_count = db.query(TeamMember).filter(TeamMember.team_id == team.id).count()

            response = TeamResponse(
                id=team.id,
                name=team.name,
                slug=team.slug,
                description=team.description,
                created_by=team.created_by,
                created_at=team.created_at,
                updated_at=team.updated_at,
                is_active=team.is_active,
                member_count=member_count,
            )
            # Add user's role in this team (if TeamResponse supports it)
            if hasattr(response, "user_role"):
                response.user_role = membership.role
            if hasattr(response, "joined_at"):
                response.joined_at = membership.joined_at
            result.append(response)

    return result


@router.post(
    "/{team_id}/transfer-ownership",
    responses={
        200: {"description": "Ownership transferred successfully"},
        404: {"model": ErrorResponse, "description": "Team or user not found"},
        403: {"model": ErrorResponse, "description": "Only team owners can transfer ownership"},
        400: {"model": ErrorResponse, "description": "Target user must be a team member"},
    },
)
async def transfer_team_ownership(team_id: str, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Transfer team ownership to another team member.

    Requires current user to be team owner.
    Target user must already be a team member.
    """
    # Parse form data
    form_data = await request.form()
    new_owner_id = form_data.get("new_owner_id", "").strip()

    if not new_owner_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New owner user ID is required")

    # Verify team exists
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # Check if current user is team owner
    current_membership = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.user_id == current_user.id, TeamMember.role == TeamRole.OWNER.value).first()

    if not current_membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team owners can transfer ownership")

    # Check if target user is a team member
    target_membership = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.user_id == new_owner_id).first()

    if not target_membership:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Target user must be a team member")

    # Get target user info
    target_user = target_membership.user

    # Transfer ownership
    current_membership.role = TeamRole.ADMIN.value  # Demote current owner to admin
    target_membership.role = TeamRole.OWNER.value  # Promote target to owner

    db.commit()

    logger.info(f"Team {team.name} ownership transferred from {current_user.username} to {target_user.username}")

    return {"message": f"Team ownership transferred to {target_user.username}", "new_owner": target_user.username, "team_name": team.name}


@router.get(
    "/{team_id}/resources",
    responses={
        200: {"description": "List of team resources"},
        404: {"model": ErrorResponse, "description": "Team not found"},
        403: {"model": ErrorResponse, "description": "Not a team member"},
    },
)
async def list_team_resources(team_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    List resources scoped to this team.

    Returns tools, resources, prompts, servers, etc. that belong to this team.
    """
    # Verify team exists
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # Check if user is team member or admin
    if not current_user.is_admin:
        membership = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.user_id == current_user.id).first()

        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this team")

    # Get team resources
    # First-Party
    from mcpgateway.db import A2AAgent, Gateway, Prompt, Resource, Server, Tool

    team_tools = db.query(Tool).filter(Tool.scope_type == "team", Tool.scope_team_id == team_id).all()

    team_resources = db.query(Resource).filter(Resource.scope_type == "team", Resource.scope_team_id == team_id).all()

    team_prompts = db.query(Prompt).filter(Prompt.scope_type == "team", Prompt.scope_team_id == team_id).all()

    team_servers = db.query(Server).filter(Server.scope_type == "team", Server.scope_team_id == team_id).all()

    team_gateways = db.query(Gateway).filter(Gateway.scope_type == "team", Gateway.scope_team_id == team_id).all()

    team_agents = db.query(A2AAgent).filter(A2AAgent.scope_type == "team", A2AAgent.scope_team_id == team_id).all()

    return {
        "team_id": team_id,
        "team_name": team.name,
        "tools": len(team_tools),
        "resources": len(team_resources),
        "prompts": len(team_prompts),
        "servers": len(team_servers),
        "gateways": len(team_gateways),
        "a2a_agents": len(team_agents),
        "total_resources": len(team_tools) + len(team_resources) + len(team_prompts) + len(team_servers) + len(team_gateways) + len(team_agents),
    }
