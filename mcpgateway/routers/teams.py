# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/teams.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Team Management Router.
This module provides FastAPI routes for team management including
team creation, member management, and invitation handling.

Examples:
    >>> from fastapi import FastAPI
    >>> from mcpgateway.routers.teams import teams_router
    >>> app = FastAPI()
    >>> app.include_router(teams_router, prefix="/teams", tags=["Teams"])
    >>> isinstance(teams_router, APIRouter)
    True
    >>> len(teams_router.routes) > 10  # Multiple team management endpoints
    True
"""

# Standard
from typing import Any, cast, List, Optional, Union

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.schemas import (
    CursorPaginatedTeamsResponse,
    EmailUserResponse,
    PaginatedTeamMembersResponse,
    SuccessResponse,
    TeamCreateRequest,
    TeamDiscoveryResponse,
    TeamInvitationResponse,
    TeamInviteRequest,
    TeamJoinRequest,
    TeamJoinRequestResponse,
    TeamListResponse,
    TeamMemberResponse,
    TeamMemberUpdateRequest,
    TeamResponse,
    TeamUpdateRequest,
)
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.team_invitation_service import TeamInvitationService
from mcpgateway.services.team_management_service import TeamManagementService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Create router
teams_router = APIRouter()


# ---------------------------------------------------------------------------
# Team CRUD Operations
# ---------------------------------------------------------------------------


@teams_router.post("/", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
@require_permission("teams.create")
async def create_team(request: TeamCreateRequest, current_user_ctx: dict = Depends(get_current_user_with_permissions)) -> TeamResponse:
    """Create a new team.

    Args:
        request: Team creation request data
        current_user_ctx: Currently authenticated user context

    Returns:
        TeamResponse: Created team data

    Raises:
        HTTPException: If team creation fails

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(create_team)
        True
    """
    try:
        db = current_user_ctx["db"]
        service = TeamManagementService(db)
        team = await service.create_team(name=request.name, description=request.description, created_by=current_user_ctx["email"], visibility=request.visibility, max_members=request.max_members)

        return TeamResponse(
            id=team.id,
            name=team.name,
            slug=team.slug,
            description=team.description,
            created_by=team.created_by,
            is_personal=team.is_personal,
            visibility=team.visibility,
            max_members=team.max_members,
            member_count=team.get_member_count(),
            created_at=team.created_at,
            updated_at=team.updated_at,
            is_active=team.is_active,
        )
    except ValueError as e:
        logger.error(f"Team creation failed: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error creating team: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create team")


@teams_router.get("/", response_model=Union[TeamListResponse, CursorPaginatedTeamsResponse])
@require_permission("teams.read")
async def list_teams(
    skip: int = Query(0, ge=0, description="Number of teams to skip"),
    limit: int = Query(50, ge=1, le=100, description="Number of teams to return"),
    cursor: Optional[str] = Query(None, description="Pagination cursor"),
    include_pagination: bool = Query(False, description="Include pagination metadata (cursor)"),
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> Union[TeamListResponse, CursorPaginatedTeamsResponse]:
    """List teams visible to the caller.

    - Administrators see all non-personal teams (paginated)
    - Regular users see only teams they are a member of (paginated client-side)

    Args:
        skip: Number of teams to skip for pagination
        limit: Maximum number of teams to return
        cursor: Pagination cursor
        include_pagination: Include pagination metadata
        current_user_ctx: Current user context with permissions and database session

    Returns:
        Union[TeamListResponse, CursorPaginatedTeamsResponse]: List of teams

    Raises:
        HTTPException: If there's an error listing teams
    """
    try:
        db = current_user_ctx["db"]
        service = TeamManagementService(db)

        teams_data = []
        next_cursor = None
        total = 0

        if current_user_ctx.get("is_admin"):
            # Use updated list_teams logic
            # If current request uses offset (skip), mapped to offset.
            # If cursor, mapped to cursor.
            # page is None, so returns Tuple
            result = await service.list_teams(
                limit=limit,
                offset=skip,
                cursor=cursor,
            )
            # Result is tuple (list, next_cursor)
            teams_data, next_cursor = result

            # Get accurate total count for API consumers
            total = await service.get_teams_count()
        else:
            # Fallback to user teams and apply pagination locally
            user_teams = await service.get_user_teams(current_user_ctx["email"], include_personal=True)
            total = len(user_teams)
            teams_data = user_teams[skip : skip + limit]

        # Batch fetch member counts with caching (N+1 elimination)
        team_ids = [str(team.id) for team in teams_data]
        member_counts = await service.get_member_counts_batch_cached(team_ids)

        team_responses = [
            TeamResponse(
                id=team.id,
                name=team.name,
                slug=team.slug,
                description=team.description,
                created_by=team.created_by,
                is_personal=team.is_personal,
                visibility=team.visibility,
                max_members=team.max_members,
                member_count=member_counts.get(str(team.id), 0),
                created_at=team.created_at,
                updated_at=team.updated_at,
                is_active=team.is_active,
            )
            for team in teams_data
        ]

        if include_pagination:
            return CursorPaginatedTeamsResponse(teams=team_responses, nextCursor=next_cursor)

        return TeamListResponse(teams=team_responses, total=total)
    except Exception as e:
        logger.error(f"Error listing teams: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list teams")


@teams_router.get("/{team_id}", response_model=TeamResponse)
@require_permission("teams.read")
async def get_team(team_id: str, current_user: EmailUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> TeamResponse:
    """Get a specific team by ID.

    Args:
        team_id: Team UUID
        current_user: Currently authenticated user
        db: Database session

    Returns:
        TeamResponse: Team data

    Raises:
        HTTPException: If team not found or access denied
    """
    try:
        service = TeamManagementService(db)
        team = await service.get_team_by_id(team_id)

        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        # Check if user has access to the team
        user_role = await service.get_user_role_in_team(current_user.email, team_id)
        if not user_role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to team")

        team_obj = cast(Any, team)
        return TeamResponse(
            id=team_obj.id,
            name=team_obj.name,
            slug=team_obj.slug,
            description=team_obj.description,
            created_by=team_obj.created_by,
            is_personal=team_obj.is_personal,
            visibility=team_obj.visibility,
            max_members=team_obj.max_members,
            member_count=team_obj.get_member_count(),
            created_at=team_obj.created_at,
            updated_at=team_obj.updated_at,
            is_active=team_obj.is_active,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting team {team_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get team")


@teams_router.put("/{team_id}", response_model=TeamResponse)
@require_permission("teams.update")
async def update_team(team_id: str, request: TeamUpdateRequest, current_user: EmailUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> TeamResponse:
    """Update a team.

    Args:
        team_id: Team UUID
        request: Team update request data
        current_user: Currently authenticated user
        db: Database session

    Returns:
        TeamResponse: Updated team data

    Raises:
        HTTPException: If team not found, access denied, or update fails
    """
    try:
        service = TeamManagementService(db)

        # Check if user is team owner
        role = await service.get_user_role_in_team(current_user.email, team_id)
        if role != "owner":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

        team = await service.update_team(team_id=team_id, name=request.name, description=request.description, visibility=request.visibility, max_members=request.max_members)

        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        team_obj = cast(Any, team)
        return TeamResponse(
            id=team_obj.id,
            name=team_obj.name,
            slug=team_obj.slug,
            description=team_obj.description,
            created_by=team_obj.created_by,
            is_personal=team_obj.is_personal,
            visibility=team_obj.visibility,
            max_members=team_obj.max_members,
            member_count=team_obj.get_member_count(),
            created_at=team_obj.created_at,
            updated_at=team_obj.updated_at,
            is_active=team_obj.is_active,
        )
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Team update failed: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating team {team_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update team")


@teams_router.delete("/{team_id}", response_model=SuccessResponse)
@require_permission("teams.delete")
async def delete_team(team_id: str, current_user: EmailUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> SuccessResponse:
    """Delete a team.

    Args:
        team_id: Team UUID
        current_user: Currently authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success confirmation

    Raises:
        HTTPException: If team not found, access denied, or deletion fails
    """
    try:
        service = TeamManagementService(db)

        # Check if user is team owner
        role = await service.get_user_role_in_team(current_user.email, team_id)
        if role != "owner":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team owners can delete teams")

        success = await service.delete_team(team_id, current_user.email)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        return SuccessResponse(message="Team deleted successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting team {team_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete team")


# ---------------------------------------------------------------------------
# Team Member Management
# ---------------------------------------------------------------------------


@teams_router.get("/{team_id}/members", response_model=Union[PaginatedTeamMembersResponse, List[TeamMemberResponse]])
@require_permission("teams.read")
async def list_team_members(
    team_id: str,
    cursor: Optional[str] = Query(None, description="Cursor for pagination"),
    limit: Optional[int] = Query(None, ge=1, le=settings.pagination_max_page_size, description="Maximum number of members to return (default: 50)"),
    include_pagination: bool = Query(False, description="Include cursor pagination metadata in response"),
    current_user: EmailUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Union[PaginatedTeamMembersResponse, List[TeamMemberResponse]]:
    """List team members with cursor-based pagination.

    Args:
        team_id: Team UUID
        cursor: Pagination cursor for fetching the next set of results
        limit: Maximum number of members to return (default: 50)
        include_pagination: Whether to include cursor pagination metadata in the response (default: false)
        current_user: Currently authenticated user
        db: Database session

    Returns:
        PaginatedTeamMembersResponse with members and nextCursor if include_pagination=true, or
        List of team members if include_pagination=false

    Raises:
        HTTPException: If team not found or access denied
    """
    try:
        service = TeamManagementService(db)

        # Check if user has access to the team
        user_role = await service.get_user_role_in_team(current_user.email, team_id)
        if not user_role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to team")

        # Get members - service returns different types based on parameters:
        # - cursor=None, limit=None: List[Tuple] (backward compat)
        # - cursor or limit provided: Tuple[List[Tuple], next_cursor]
        result = await service.get_team_members(team_id, cursor=cursor, limit=limit)

        # Handle different return types from service
        if cursor is not None or limit is not None:
            # Cursor pagination was used - result is a tuple
            members, next_cursor = result
        else:
            # No pagination - result is a plain list
            members = result
            next_cursor = None

        # Convert to response objects
        member_responses = []
        for user, membership in members:
            member_responses.append(
                TeamMemberResponse(
                    id=membership.id,
                    team_id=membership.team_id,
                    user_email=membership.user_email,
                    role=membership.role,
                    joined_at=membership.joined_at,
                    invited_by=membership.invited_by,
                    is_active=membership.is_active,
                )
            )

        # Return with pagination metadata if requested
        if include_pagination:
            return PaginatedTeamMembersResponse(members=member_responses, nextCursor=next_cursor)

        return member_responses
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing team members for team {team_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list team members")


@teams_router.put("/{team_id}/members/{user_email}", response_model=TeamMemberResponse)
@require_permission("teams.manage_members")
async def update_team_member(
    team_id: str, user_email: str, request: TeamMemberUpdateRequest, current_user: EmailUserResponse = Depends(get_current_user), db: Session = Depends(get_db)
) -> TeamMemberResponse:
    """Update a team member's role.

    Args:
        team_id: Team UUID
        user_email: Email of the member to update
        request: Member update request data
        current_user: Currently authenticated user
        db: Database session

    Returns:
        TeamMemberResponse: Updated member data

    Raises:
        HTTPException: If member not found, access denied, or update fails
    """
    try:
        service = TeamManagementService(db)

        # Check if user is team owner
        role = await service.get_user_role_in_team(current_user.email, team_id)
        if role != "owner":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

        member = await service.update_member_role(team_id, user_email, request.role)
        if not member:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")

        mm = cast(Any, member)
        return TeamMemberResponse(id=mm.id, team_id=mm.team_id, user_email=mm.user_email, role=mm.role, joined_at=mm.joined_at, invited_by=mm.invited_by, is_active=mm.is_active)
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Member update failed: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating team member {user_email} in team {team_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update team member")


@teams_router.delete("/{team_id}/members/{user_email}", response_model=SuccessResponse)
@require_permission("teams.manage_members")
async def remove_team_member(team_id: str, user_email: str, current_user: EmailUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> SuccessResponse:
    """Remove a team member.

    Args:
        team_id: Team UUID
        user_email: Email of the member to remove
        current_user: Currently authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success confirmation

    Raises:
        HTTPException: If member not found, access denied, or removal fails
    """
    try:
        service = TeamManagementService(db)

        # Users can remove themselves, or owners can remove others
        current_user_role = await service.get_user_role_in_team(current_user.email, team_id)
        if current_user.email != user_email and current_user_role != "owner":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

        success = await service.remove_member_from_team(team_id, user_email)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")

        return SuccessResponse(message="Team member removed successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing team member {user_email} from team {team_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to remove team member")


# ---------------------------------------------------------------------------
# Team Invitations
# ---------------------------------------------------------------------------


@teams_router.post("/{team_id}/invitations", response_model=TeamInvitationResponse, status_code=status.HTTP_201_CREATED)
@require_permission("teams.manage_members")
async def invite_team_member(team_id: str, request: TeamInviteRequest, current_user: EmailUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> TeamInvitationResponse:
    """Invite a user to join a team.

    Args:
        team_id: Team UUID
        request: Invitation request data
        current_user: Currently authenticated user
        db: Database session

    Returns:
        TeamInvitationResponse: Created invitation data

    Raises:
        HTTPException: If team not found, access denied, or invitation fails
    """
    try:
        team_service = TeamManagementService(db)
        invitation_service = TeamInvitationService(db)

        # Check if user is team owner
        role = await team_service.get_user_role_in_team(current_user.email, team_id)
        if role != "owner":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

        invitation = await invitation_service.create_invitation(team_id=team_id, email=str(request.email), role=request.role, invited_by=current_user.email)
        if not invitation:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create invitation")

        # Get team name for response
        team = await team_service.get_team_by_id(team_id)
        team_name = team.name if team else "Unknown Team"

        return TeamInvitationResponse(
            id=invitation.id,
            team_id=invitation.team_id,
            team_name=team_name,
            email=invitation.email,
            role=invitation.role,
            invited_by=invitation.invited_by,
            invited_at=invitation.invited_at,
            expires_at=invitation.expires_at,
            token=invitation.token,
            is_active=invitation.is_active,
            is_expired=invitation.is_expired(),
        )
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Team invitation failed: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating team invitation for team {team_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create invitation")


@teams_router.get("/{team_id}/invitations", response_model=List[TeamInvitationResponse])
@require_permission("teams.read")
async def list_team_invitations(team_id: str, current_user: EmailUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> List[TeamInvitationResponse]:
    """List team invitations.

    Args:
        team_id: Team UUID
        current_user: Currently authenticated user
        db: Database session

    Returns:
        List[TeamInvitationResponse]: List of team invitations

    Raises:
        HTTPException: If team not found or access denied
    """
    try:
        team_service = TeamManagementService(db)
        invitation_service = TeamInvitationService(db)

        # Check if user is team owner
        role = await team_service.get_user_role_in_team(current_user.email, team_id)
        if role != "owner":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

        invitations = await invitation_service.get_team_invitations(team_id)

        # Get team name for responses
        team = await team_service.get_team_by_id(team_id)
        team_name = team.name if team else "Unknown Team"

        invitation_responses = []
        for invitation in invitations:
            invitation_responses.append(
                TeamInvitationResponse(
                    id=invitation.id,
                    team_id=invitation.team_id,
                    team_name=team_name,
                    email=invitation.email,
                    role=invitation.role,
                    invited_by=invitation.invited_by,
                    invited_at=invitation.invited_at,
                    expires_at=invitation.expires_at,
                    token=invitation.token,
                    is_active=invitation.is_active,
                    is_expired=invitation.is_expired(),
                )
            )

        return invitation_responses
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing team invitations for team {team_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list invitations")


@teams_router.post("/invitations/{token}/accept", response_model=TeamMemberResponse)
@require_permission("teams.read")
async def accept_team_invitation(token: str, current_user: EmailUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> TeamMemberResponse:
    """Accept a team invitation.

    Args:
        token: Invitation token
        current_user: Currently authenticated user
        db: Database session

    Returns:
        TeamMemberResponse: New team member data

    Raises:
        HTTPException: If invitation not found, expired, or acceptance fails
    """
    try:
        invitation_service = TeamInvitationService(db)

        member = await invitation_service.accept_invitation(token, current_user.email)
        if not member or not hasattr(member, "id"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired invitation")

        mm = cast(Any, member)
        return TeamMemberResponse(id=mm.id, team_id=mm.team_id, user_email=mm.user_email, role=mm.role, joined_at=mm.joined_at, invited_by=mm.invited_by, is_active=mm.is_active)
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Invitation acceptance failed: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error accepting invitation {token}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to accept invitation")


@teams_router.delete("/invitations/{invitation_id}", response_model=SuccessResponse)
@require_permission("teams.manage_members")
async def cancel_team_invitation(invitation_id: str, current_user: EmailUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> SuccessResponse:
    """Cancel a team invitation.

    Args:
        invitation_id: Invitation UUID
        current_user: Currently authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success confirmation

    Raises:
        HTTPException: If invitation not found, access denied, or cancellation fails
    """
    try:
        team_service = TeamManagementService(db)
        invitation_service = TeamInvitationService(db)

        # Get invitation to check team permissions
        # First-Party
        from mcpgateway.db import EmailTeamInvitation

        invitation = db.query(EmailTeamInvitation).filter(EmailTeamInvitation.id == invitation_id).first()
        if not invitation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")

        # Check if user is team owner or the inviter
        role = await team_service.get_user_role_in_team(current_user.email, invitation.team_id)
        if role != "owner" and current_user.email != invitation.invited_by:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

        success = await invitation_service.revoke_invitation(invitation_id, current_user.email)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")

        return SuccessResponse(message="Team invitation cancelled successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling invitation {invitation_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to cancel invitation")


@teams_router.get("/discover", response_model=List[TeamDiscoveryResponse])
@require_permission("teams.read")
async def discover_public_teams(
    skip: int = Query(0, ge=0, description="Number of teams to skip"),
    limit: int = Query(50, ge=1, le=100, description="Number of teams to return"),
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> List[TeamDiscoveryResponse]:
    """Discover public teams that can be joined.

    Returns public teams that are discoverable to all authenticated users.
    Only shows teams where the current user is not already a member.

    Args:
        skip: Number of teams to skip for pagination
        limit: Maximum number of teams to return
        current_user_ctx: Current user context with permissions and database session

    Returns:
        List[TeamDiscoveryResponse]: List of discoverable public teams

    Raises:
        HTTPException: If there's an error discovering teams
    """
    try:
        db = current_user_ctx["db"]
        team_service = TeamManagementService(db)

        # Get public teams where user is not already a member
        public_teams = await team_service.discover_public_teams(current_user_ctx["email"], skip=skip, limit=limit)

        # Batch fetch member counts with caching (N+1 elimination)
        team_ids = [str(team.id) for team in public_teams]
        member_counts = await team_service.get_member_counts_batch_cached(team_ids)

        discovery_responses = []
        for team in public_teams:
            discovery_responses.append(
                TeamDiscoveryResponse(
                    id=team.id,
                    name=team.name,
                    description=team.description,
                    member_count=member_counts.get(str(team.id), 0),
                    created_at=team.created_at,
                    is_joinable=True,  # All returned teams are joinable
                )
            )

        return discovery_responses
    except Exception as e:
        logger.error(f"Error discovering public teams: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to discover teams")


@teams_router.post("/{team_id}/join", response_model=TeamJoinRequestResponse)
async def request_to_join_team(
    team_id: str,
    join_request: TeamJoinRequest,
    current_user: EmailUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TeamJoinRequestResponse:
    """Request to join a public team.

    Allows users to request membership in public teams. The request will be
    pending until approved by a team owner.

    Args:
        team_id: ID of the team to join
        join_request: Join request details including optional message
        current_user: Currently authenticated user
        db: Database session

    Returns:
        TeamJoinRequestResponse: Created join request details

    Raises:
        HTTPException: If team not found, not public, user already member, or request fails
    """
    try:
        team_service = TeamManagementService(db)

        # Validate team exists and is public
        team = await team_service.get_team_by_id(team_id)
        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        if team.visibility != "public":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Can only request to join public teams")

        # Check if user is already a member
        user_role = await team_service.get_user_role_in_team(current_user.email, team_id)
        if user_role:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is already a member of this team")

        # Create join request
        join_req = await team_service.create_join_request(team_id=team_id, user_email=current_user.email, message=join_request.message)

        return TeamJoinRequestResponse(
            id=join_req.id,
            team_id=join_req.team_id,
            team_name=team.name,
            user_email=join_req.user_email,
            message=join_req.message,
            status=join_req.status,
            requested_at=join_req.requested_at,
            expires_at=join_req.expires_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating join request for team {team_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create join request")


@teams_router.delete("/{team_id}/leave", response_model=SuccessResponse)
async def leave_team(
    team_id: str,
    current_user: EmailUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SuccessResponse:
    """Leave a team.

    Allows users to remove themselves from a team. Cannot leave personal teams
    or if they are the last owner of a team.

    Args:
        team_id: ID of the team to leave
        current_user: Currently authenticated user
        db: Database session

    Returns:
        SuccessResponse: Confirmation of leaving the team

    Raises:
        HTTPException: If team not found, user not member, cannot leave personal team, or last owner
    """
    try:
        team_service = TeamManagementService(db)

        # Validate team exists
        team = await team_service.get_team_by_id(team_id)
        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        # Cannot leave personal team
        if team.is_personal:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot leave personal team")

        # Check if user is member
        user_role = await team_service.get_user_role_in_team(current_user.email, team_id)
        if not user_role:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is not a member of this team")

        # Remove user from team
        success = await team_service.remove_member_from_team(team_id, current_user.email, removed_by=current_user.email)
        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot leave team - you may be the last owner")

        return SuccessResponse(message="Successfully left the team")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error leaving team {team_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to leave team")


@teams_router.get("/{team_id}/join-requests", response_model=List[TeamJoinRequestResponse])
@require_permission("teams.manage_members")
async def list_team_join_requests(
    team_id: str,
    current_user: EmailUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[TeamJoinRequestResponse]:
    """List pending join requests for a team.

    Only team owners can view join requests for their teams.

    Args:
        team_id: ID of the team
        current_user: Currently authenticated user
        db: Database session

    Returns:
        List[TeamJoinRequestResponse]: List of pending join requests

    Raises:
        HTTPException: If team not found or user not authorized
    """
    try:
        team_service = TeamManagementService(db)

        # Validate team exists and user is owner
        team = await team_service.get_team_by_id(team_id)
        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        user_role = await team_service.get_user_role_in_team(current_user.email, team_id)
        if user_role != "owner":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team owners can view join requests")

        # Get join requests
        join_requests = await team_service.list_join_requests(team_id)

        return [
            TeamJoinRequestResponse(
                id=req.id,
                team_id=req.team_id,
                team_name=team.name,
                user_email=req.user_email,
                message=req.message,
                status=req.status,
                requested_at=req.requested_at,
                expires_at=req.expires_at,
            )
            for req in join_requests
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing join requests for team {team_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list join requests")


@teams_router.post("/{team_id}/join-requests/{request_id}/approve", response_model=TeamMemberResponse)
@require_permission("teams.manage_members")
async def approve_join_request(
    team_id: str,
    request_id: str,
    current_user: EmailUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TeamMemberResponse:
    """Approve a team join request.

    Only team owners can approve join requests for their teams.

    Args:
        team_id: ID of the team
        request_id: ID of the join request
        current_user: Currently authenticated user
        db: Database session

    Returns:
        TeamMemberResponse: New team member data

    Raises:
        HTTPException: If request not found or user not authorized
    """
    try:
        team_service = TeamManagementService(db)

        # Validate team exists and user is owner
        team = await team_service.get_team_by_id(team_id)
        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        user_role = await team_service.get_user_role_in_team(current_user.email, team_id)
        if user_role != "owner":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team owners can approve join requests")

        # Approve join request
        member = await team_service.approve_join_request(request_id, approved_by=current_user.email)
        if not member:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Join request not found")

        return TeamMemberResponse(
            id=member.id,
            team_id=member.team_id,
            user_email=member.user_email,
            role=member.role,
            joined_at=member.joined_at,
            invited_by=member.invited_by,
            is_active=member.is_active,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving join request {request_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to approve join request")


@teams_router.delete("/{team_id}/join-requests/{request_id}", response_model=SuccessResponse)
@require_permission("teams.manage_members")
async def reject_join_request(
    team_id: str,
    request_id: str,
    current_user: EmailUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SuccessResponse:
    """Reject a team join request.

    Only team owners can reject join requests for their teams.

    Args:
        team_id: ID of the team
        request_id: ID of the join request
        current_user: Currently authenticated user
        db: Database session

    Returns:
        SuccessResponse: Confirmation of rejection

    Raises:
        HTTPException: If request not found or user not authorized
    """
    try:
        team_service = TeamManagementService(db)

        # Validate team exists and user is owner
        team = await team_service.get_team_by_id(team_id)
        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        user_role = await team_service.get_user_role_in_team(current_user.email, team_id)
        if user_role != "owner":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team owners can reject join requests")

        # Reject join request
        success = await team_service.reject_join_request(request_id, rejected_by=current_user.email)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Join request not found")

        return SuccessResponse(message="Join request rejected successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rejecting join request {request_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to reject join request")
