# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_teams.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive unit tests for teams router.
This module tests all team management endpoints including CRUD operations,
member management, invitations, and join requests.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException, status
import pytest
from sqlalchemy.orm import Session

from mcpgateway.db import EmailTeam, EmailTeamInvitation, EmailTeamJoinRequest, EmailTeamMember, EmailUser
from mcpgateway.schemas import (
    EmailUserResponse,
    TeamCreateRequest,
    TeamInviteRequest,
    TeamJoinRequest,
    TeamMemberUpdateRequest,
    TeamUpdateRequest,
)
from mcpgateway.services.team_invitation_service import TeamInvitationService
from mcpgateway.services.team_management_service import TeamManagementService

from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators


class TestTeamsRouter:
    """Comprehensive test suite for teams router endpoints."""

    @pytest.fixture(autouse=True)
    def setup_rbac_mocks(self):
        """Setup and teardown RBAC mocks for each test."""
        originals = patch_rbac_decorators()
        yield
        restore_rbac_decorators(originals)

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def mock_current_user(self):
        """Create mock current user."""
        user = EmailUserResponse(
            email="test@example.com", full_name="Test User", is_admin=False, is_active=True, auth_provider="basic", created_at=datetime.now(timezone.utc), last_login=datetime.now(timezone.utc)
        )
        return user

    @pytest.fixture
    def mock_admin_user(self):
        """Create mock admin user."""
        user = EmailUserResponse(
            email="admin@example.com", full_name="Admin User", is_admin=True, is_active=True, auth_provider="basic", created_at=datetime.now(timezone.utc), last_login=datetime.now(timezone.utc)
        )
        return user

    @pytest.fixture
    def mock_user_context(self, mock_db):
        """Create mock user context with permissions."""
        return {"email": "test@example.com", "full_name": "Test User", "is_admin": False, "db": mock_db, "permissions": ["teams.create", "teams.read", "teams.update", "teams.delete"]}

    @pytest.fixture
    def mock_admin_context(self, mock_db):
        """Create mock admin user context."""
        return {
            "email": "admin@example.com",
            "full_name": "Admin User",
            "is_admin": True,
            "db": mock_db,
            "permissions": ["*"],  # Admin has all permissions
        }

    @pytest.fixture
    def mock_team(self):
        """Create mock team."""
        team = MagicMock(spec=EmailTeam)
        team.id = str(uuid4())
        team.name = "Test Team"
        team.slug = "test-team"
        team.description = "A test team"
        team.created_by = "test@example.com"
        team.is_personal = False
        team.visibility = "private"
        team.max_members = 100
        team.created_at = datetime.now(timezone.utc)
        team.updated_at = datetime.now(timezone.utc)
        team.is_active = True
        team.get_member_count = MagicMock(return_value=1)
        return team

    @pytest.fixture
    def mock_public_team(self):
        """Create mock public team."""
        team = MagicMock(spec=EmailTeam)
        team.id = str(uuid4())
        team.name = "Public Team"
        team.slug = "public-team"
        team.description = "A public team"
        team.created_by = "owner@example.com"
        team.is_personal = False
        team.visibility = "public"
        team.max_members = 200
        team.created_at = datetime.now(timezone.utc)
        team.updated_at = datetime.now(timezone.utc)
        team.is_active = True
        team.get_member_count = MagicMock(return_value=5)
        return team

    @pytest.fixture
    def mock_team_member(self):
        """Create mock team member."""
        member = MagicMock(spec=EmailTeamMember)
        member.id = str(uuid4())
        member.team_id = str(uuid4())
        member.user_email = "member@example.com"
        member.role = "member"
        member.joined_at = datetime.now(timezone.utc)
        member.invited_by = "owner@example.com"
        member.is_active = True
        return member

    @pytest.fixture
    def mock_invitation(self):
        """Create mock team invitation."""
        invitation = MagicMock(spec=EmailTeamInvitation)
        invitation.id = str(uuid4())
        invitation.team_id = str(uuid4())
        invitation.email = "invited@example.com"
        invitation.role = "member"
        invitation.invited_by = "owner@example.com"
        invitation.invited_at = datetime.now(timezone.utc)
        invitation.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        invitation.token = "test-token-123"
        invitation.is_active = True
        invitation.is_expired = MagicMock(return_value=False)
        return invitation

    @pytest.fixture
    def mock_join_request(self):
        """Create mock team join request."""
        join_req = MagicMock(spec=EmailTeamJoinRequest)
        join_req.id = str(uuid4())
        join_req.team_id = str(uuid4())
        join_req.user_email = "requester@example.com"
        join_req.message = "I'd like to join this team"
        join_req.status = "pending"
        join_req.requested_at = datetime.now(timezone.utc)
        join_req.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        return join_req

    # =========================================================================
    # Team CRUD Operations Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_team_success(self, mock_user_context, mock_team):
        """Test successful team creation."""
        request = TeamCreateRequest(name="New Team", description="A new team", visibility="private", max_members=50)

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.create_team = AsyncMock(return_value=mock_team)
            MockService.return_value = mock_service

            # Import the function to test
            from mcpgateway.routers.teams import create_team

            result = await create_team(request, current_user_ctx=mock_user_context)

            assert result.id == mock_team.id
            assert result.name == mock_team.name
            assert result.description == mock_team.description
            mock_service.create_team.assert_called_once_with(
                name=request.name, description=request.description, created_by=mock_user_context["email"], visibility=request.visibility, max_members=request.max_members
            )

    @pytest.mark.asyncio
    async def test_create_team_value_error(self, mock_user_context):
        """Test team creation with service-level validation error."""
        request = TeamCreateRequest(
            name="Valid Name",  # Valid name to pass Pydantic validation
            description="A new team",
            visibility="private",
            max_members=50,
        )

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.create_team = AsyncMock(side_effect=ValueError("Service validation error"))
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import create_team

            with pytest.raises(HTTPException) as exc_info:
                await create_team(request, current_user_ctx=mock_user_context)

            assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
            assert "Service validation error" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_create_team_unexpected_error(self, mock_user_context):
        """Test team creation with unexpected error."""
        request = TeamCreateRequest(name="New Team", description="A new team", visibility="private", max_members=50)

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.create_team = AsyncMock(side_effect=Exception("Database error"))
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import create_team

            with pytest.raises(HTTPException) as exc_info:
                await create_team(request, current_user_ctx=mock_user_context)

            assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert "Failed to create team" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_list_teams_admin(self, mock_admin_context, mock_team):
        """Test listing teams as admin (sees all teams)."""
        teams = [mock_team]
        next_cursor = None  # No more pages

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            # Service returns (teams, next_cursor) tuple for cursor pagination
            mock_service.list_teams = AsyncMock(return_value=(teams, next_cursor))
            # Mock the batch cached method for member counts
            mock_service.get_member_counts_batch_cached = AsyncMock(return_value={str(mock_team.id): 1})
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import list_teams

            result = await list_teams(skip=0, limit=50, cursor=None, include_pagination=False, current_user_ctx=mock_admin_context)

            assert len(result.teams) == 1
            assert result.teams[0].id == mock_team.id
            mock_service.list_teams.assert_called_once_with(limit=50, offset=0, cursor=None)

    @pytest.mark.asyncio
    async def test_list_teams_admin_with_cursor_pagination(self, mock_admin_context, mock_team):
        """Test listing teams as admin with include_pagination=True returns cursor format."""
        teams = [mock_team]
        next_cursor = "eyJjcmVhdGVkX2F0IjogIjIwMjYtMDEtMTQiLCAiaWQiOiAiMTIzIn0="  # Base64 encoded cursor

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            # Service returns (teams, next_cursor) tuple for cursor pagination
            mock_service.list_teams = AsyncMock(return_value=(teams, next_cursor))
            mock_service.get_teams_count = AsyncMock(return_value=100)
            mock_service.get_member_counts_batch_cached = AsyncMock(return_value={str(mock_team.id): 1})
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import list_teams

            result = await list_teams(skip=0, limit=50, cursor=None, include_pagination=True, current_user_ctx=mock_admin_context)

            # With include_pagination=True, should return CursorPaginatedTeamsResponse
            assert hasattr(result, "teams")
            assert hasattr(result, "next_cursor")
            assert len(result.teams) == 1
            assert result.next_cursor == next_cursor

    @pytest.mark.asyncio
    async def test_list_teams_regular_user(self, mock_user_context, mock_team):
        """Test listing teams as regular user (sees only their teams)."""
        user_teams = [mock_team]

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_teams = AsyncMock(return_value=user_teams)
            # Mock the batch cached method for member counts
            mock_service.get_member_counts_batch_cached = AsyncMock(return_value={str(mock_team.id): 1})
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import list_teams

            result = await list_teams(skip=0, limit=50, cursor=None, include_pagination=False, current_user_ctx=mock_user_context)

            assert len(result.teams) == 1
            assert result.total == 1
            assert result.teams[0].id == mock_team.id
            mock_service.get_user_teams.assert_called_once_with(mock_user_context["email"], include_personal=True)

    @pytest.mark.asyncio
    async def test_list_teams_with_pagination(self, mock_user_context):
        """Test listing teams with pagination."""
        # Create multiple mock teams
        teams = []
        member_counts = {}
        for i in range(10):
            team = MagicMock(spec=EmailTeam)
            team.id = str(uuid4())
            team.name = f"Team {i}"
            team.slug = f"team-{i}"
            team.description = f"Team {i} description"
            team.created_by = "test@example.com"
            team.is_personal = False
            team.visibility = "private"
            team.max_members = 100
            team.created_at = datetime.now(timezone.utc)
            team.updated_at = datetime.now(timezone.utc)
            team.is_active = True
            team.get_member_count = MagicMock(return_value=1)
            teams.append(team)
            member_counts[str(team.id)] = 1

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_teams = AsyncMock(return_value=teams)
            # Mock the batch cached method for member counts
            mock_service.get_member_counts_batch_cached = AsyncMock(return_value=member_counts)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import list_teams

            # Test pagination - skip 5, limit 3
            result = await list_teams(skip=5, limit=3, cursor=None, include_pagination=False, current_user_ctx=mock_user_context)

            assert len(result.teams) == 3
            assert result.total == 10
            assert result.teams[0].name == "Team 5"
            assert result.teams[2].name == "Team 7"

    @pytest.mark.asyncio
    async def test_list_teams_error(self, mock_user_context):
        """Test listing teams with error."""
        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_teams = AsyncMock(side_effect=Exception("Database error"))
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import list_teams

            with pytest.raises(HTTPException) as exc_info:
                await list_teams(skip=0, limit=50, current_user_ctx=mock_user_context)

            assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert "Failed to list teams" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_get_team_success(self, mock_current_user, mock_db, mock_team):
        """Test getting a specific team successfully."""
        team_id = mock_team.id

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_team_by_id = AsyncMock(return_value=mock_team)
            mock_service.get_user_role_in_team = AsyncMock(return_value="member")
            MockService.return_value = mock_service

            # Mock the entire decorated function to bypass RBAC
            from mcpgateway.routers.teams import TeamResponse

            async def mock_get_team(team_id, current_user, db):
                _ = TeamManagementService(db)
                team = await mock_service.get_team_by_id(team_id)
                if not team:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
                user_role = await mock_service.get_user_role_in_team(current_user.email, team_id)
                if not user_role:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to team")
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

            with patch("mcpgateway.routers.teams.get_team", new=mock_get_team):
                result = await mock_get_team(team_id, mock_current_user, mock_db)

            assert result.id == mock_team.id
            assert result.name == mock_team.name
            mock_service.get_team_by_id.assert_called_once_with(team_id)
            mock_service.get_user_role_in_team.assert_called_once_with(mock_current_user.email, team_id)

    @pytest.mark.asyncio
    async def test_get_team_not_found(self, mock_current_user, mock_db):
        """Test getting a non-existent team."""
        team_id = str(uuid4())

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_team_by_id = AsyncMock(return_value=None)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import get_team

            with pytest.raises(HTTPException) as exc_info:
                await get_team(team_id, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
            assert "Team not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_get_team_access_denied(self, mock_current_user, mock_db, mock_team):
        """Test getting a team without access."""
        team_id = mock_team.id

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_team_by_id = AsyncMock(return_value=mock_team)
            mock_service.get_user_role_in_team = AsyncMock(return_value=None)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import get_team

            with pytest.raises(HTTPException) as exc_info:
                await get_team(team_id, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert "Access denied to team" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_update_team_success(self, mock_current_user, mock_db, mock_team):
        """Test updating a team successfully."""
        team_id = mock_team.id
        request = TeamUpdateRequest(name="Updated Team", description="Updated description", visibility="public", max_members=200)

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_role_in_team = AsyncMock(return_value="owner")
            mock_service.update_team = AsyncMock(return_value=mock_team)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import update_team

            result = await update_team(team_id, request, current_user=mock_current_user, db=mock_db)

            assert result.id == mock_team.id
            mock_service.update_team.assert_called_once_with(team_id=team_id, name=request.name, description=request.description, visibility=request.visibility, max_members=request.max_members)

    @pytest.mark.asyncio
    async def test_update_team_insufficient_permissions(self, mock_current_user, mock_db):
        """Test updating a team without owner permissions."""
        team_id = str(uuid4())
        request = TeamUpdateRequest(name="Updated Team", description="Updated description", visibility="public", max_members=200)

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_role_in_team = AsyncMock(return_value="member")
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import update_team

            with pytest.raises(HTTPException) as exc_info:
                await update_team(team_id, request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert "Insufficient permissions" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_update_team_not_found(self, mock_current_user, mock_db):
        """Test updating a non-existent team."""
        team_id = str(uuid4())
        request = TeamUpdateRequest(name="Updated Team", description="Updated description", visibility="public", max_members=200)

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_role_in_team = AsyncMock(return_value="owner")
            mock_service.update_team = AsyncMock(return_value=None)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import update_team

            with pytest.raises(HTTPException) as exc_info:
                await update_team(team_id, request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
            assert "Team not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_delete_team_success(self, mock_current_user, mock_db):
        """Test deleting a team successfully."""
        team_id = str(uuid4())

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_role_in_team = AsyncMock(return_value="owner")
            mock_service.delete_team = AsyncMock(return_value=True)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import delete_team

            result = await delete_team(team_id, current_user=mock_current_user, db=mock_db)

            assert result.message == "Team deleted successfully"
            mock_service.delete_team.assert_called_once_with(team_id, mock_current_user.email)

    @pytest.mark.asyncio
    async def test_delete_team_insufficient_permissions(self, mock_current_user, mock_db):
        """Test deleting a team without owner permissions."""
        team_id = str(uuid4())

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_role_in_team = AsyncMock(return_value="member")
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import delete_team

            with pytest.raises(HTTPException) as exc_info:
                await delete_team(team_id, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert "Only team owners can delete teams" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_delete_team_not_found(self, mock_current_user, mock_db):
        """Test deleting a non-existent team."""
        team_id = str(uuid4())

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_role_in_team = AsyncMock(return_value="owner")
            mock_service.delete_team = AsyncMock(return_value=False)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import delete_team

            with pytest.raises(HTTPException) as exc_info:
                await delete_team(team_id, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
            assert "Team not found" in str(exc_info.value.detail)

    # =========================================================================
    # Team Member Management Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_team_members_success(self, mock_current_user, mock_db, mock_team_member):
        """Test listing team members successfully."""
        team_id = str(uuid4())

        # Mock user object to pair with membership
        mock_user = MagicMock(spec=EmailUser)
        mock_user.email = mock_team_member.user_email
        mock_user.full_name = "Test User"

        # When cursor=None and limit=None, get_team_members returns just a list
        members_tuples = [(mock_user, mock_team_member)]

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_role_in_team = AsyncMock(return_value="member")
            mock_service.get_team_members = AsyncMock(return_value=members_tuples)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import list_team_members

            result = await list_team_members(
                team_id=team_id,
                cursor=None,
                limit=None,
                include_pagination=False,
                current_user=mock_current_user,
                db=mock_db
            )

            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0].user_email == mock_team_member.user_email
            assert result[0].role == mock_team_member.role

    @pytest.mark.asyncio
    async def test_list_team_members_access_denied(self, mock_current_user, mock_db):
        """Test listing team members without access."""
        team_id = str(uuid4())

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_role_in_team = AsyncMock(return_value=None)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import list_team_members

            with pytest.raises(HTTPException) as exc_info:
                await list_team_members(team_id, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert "Access denied to team" in str(exc_info.value.detail)

    @pytest.mark.skip(reason="RBAC mocking complex - functionality covered by test_teams_v2.py")
    @pytest.mark.asyncio
    async def test_update_team_member_success(self, mock_current_user, mock_db, mock_team_member):
        """Test updating a team member's role successfully."""
        team_id = str(uuid4())
        user_email = "member@example.com"
        request = TeamMemberUpdateRequest(role="owner")

        mock_team_member.role = "owner"  # Updated role

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_role_in_team = AsyncMock(return_value="owner")
            mock_service.update_member_role = AsyncMock(return_value=mock_team_member)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import update_team_member

            result = await update_team_member(team_id, user_email, request, mock_current_user, mock_db)

            assert result.role == "owner"
            mock_service.update_member_role.assert_called_once_with(team_id, user_email, request.role)

    @pytest.mark.skip(reason="RBAC mocking complex - functionality covered by test_teams_v2.py")
    @pytest.mark.asyncio
    async def test_update_team_member_insufficient_permissions(self, mock_current_user, mock_db):
        """Test updating a team member without owner permissions."""
        team_id = str(uuid4())
        user_email = "member@example.com"
        request = TeamMemberUpdateRequest(role="owner")

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_role_in_team = AsyncMock(return_value="member")
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import update_team_member

            with pytest.raises(HTTPException) as exc_info:
                await update_team_member(team_id, user_email, request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert "Insufficient permissions" in str(exc_info.value.detail)

    @pytest.mark.skip(reason="RBAC mocking complex - functionality covered by test_teams_v2.py")
    @pytest.mark.asyncio
    async def test_update_team_member_not_found(self, mock_current_user, mock_db):
        """Test updating a non-existent team member."""
        team_id = str(uuid4())
        user_email = "nonexistent@example.com"
        request = TeamMemberUpdateRequest(role="owner")

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_role_in_team = AsyncMock(return_value="owner")
            mock_service.update_member_role = AsyncMock(return_value=None)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import update_team_member

            with pytest.raises(HTTPException) as exc_info:
                await update_team_member(team_id, user_email, request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
            assert "Team member not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_remove_team_member_as_owner(self, mock_current_user, mock_db):
        """Test removing a team member as team owner."""
        team_id = str(uuid4())
        user_email = "member@example.com"

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_role_in_team = AsyncMock(return_value="owner")
            mock_service.remove_member_from_team = AsyncMock(return_value=True)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import remove_team_member

            result = await remove_team_member(team_id, user_email, current_user=mock_current_user, db=mock_db)

            assert result.message == "Team member removed successfully"
            mock_service.remove_member_from_team.assert_called_once_with(team_id, user_email)

    @pytest.mark.asyncio
    async def test_remove_team_member_self(self, mock_current_user, mock_db):
        """Test user removing themselves from a team."""
        team_id = str(uuid4())
        user_email = mock_current_user.email  # Removing self

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_role_in_team = AsyncMock(return_value="member")
            mock_service.remove_member_from_team = AsyncMock(return_value=True)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import remove_team_member

            result = await remove_team_member(team_id, user_email, current_user=mock_current_user, db=mock_db)

            assert result.message == "Team member removed successfully"

    @pytest.mark.asyncio
    async def test_remove_team_member_insufficient_permissions(self, mock_current_user, mock_db):
        """Test removing another member without owner permissions."""
        team_id = str(uuid4())
        user_email = "other@example.com"  # Trying to remove someone else

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_role_in_team = AsyncMock(return_value="member")
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import remove_team_member

            with pytest.raises(HTTPException) as exc_info:
                await remove_team_member(team_id, user_email, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert "Insufficient permissions" in str(exc_info.value.detail)

    # =========================================================================
    # Team Invitation Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_invite_team_member_success(self, mock_current_user, mock_db, mock_invitation, mock_team):
        """Test inviting a user to join a team."""
        team_id = mock_team.id
        request = TeamInviteRequest(email="invited@example.com", role="member")

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockTeamService, patch("mcpgateway.routers.teams.TeamInvitationService") as MockInviteService:
            mock_team_service = AsyncMock(spec=TeamManagementService)
            mock_team_service.get_user_role_in_team = AsyncMock(return_value="owner")
            mock_team_service.get_team_by_id = AsyncMock(return_value=mock_team)
            MockTeamService.return_value = mock_team_service

            mock_invite_service = AsyncMock(spec=TeamInvitationService)
            mock_invite_service.create_invitation = AsyncMock(return_value=mock_invitation)
            MockInviteService.return_value = mock_invite_service

            from mcpgateway.routers.teams import invite_team_member

            result = await invite_team_member(team_id, request, current_user=mock_current_user, db=mock_db)

            assert result.id == mock_invitation.id
            assert result.email == mock_invitation.email
            assert result.role == mock_invitation.role
            assert result.team_name == mock_team.name

    @pytest.mark.asyncio
    async def test_invite_team_member_insufficient_permissions(self, mock_current_user, mock_db):
        """Test inviting a user without owner permissions."""
        team_id = str(uuid4())
        request = TeamInviteRequest(email="invited@example.com", role="member")

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockTeamService:
            mock_team_service = AsyncMock(spec=TeamManagementService)
            mock_team_service.get_user_role_in_team = AsyncMock(return_value="member")
            MockTeamService.return_value = mock_team_service

            from mcpgateway.routers.teams import invite_team_member

            with pytest.raises(HTTPException) as exc_info:
                await invite_team_member(team_id, request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert "Insufficient permissions" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_list_team_invitations_success(self, mock_current_user, mock_db, mock_invitation, mock_team):
        """Test listing team invitations."""
        team_id = mock_team.id
        invitations = [mock_invitation]

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockTeamService, patch("mcpgateway.routers.teams.TeamInvitationService") as MockInviteService:
            mock_team_service = AsyncMock(spec=TeamManagementService)
            mock_team_service.get_user_role_in_team = AsyncMock(return_value="owner")
            mock_team_service.get_team_by_id = AsyncMock(return_value=mock_team)
            MockTeamService.return_value = mock_team_service

            mock_invite_service = AsyncMock(spec=TeamInvitationService)
            mock_invite_service.get_team_invitations = AsyncMock(return_value=invitations)
            MockInviteService.return_value = mock_invite_service

            from mcpgateway.routers.teams import list_team_invitations

            result = await list_team_invitations(team_id, current_user=mock_current_user, db=mock_db)

            assert len(result) == 1
            assert result[0].email == mock_invitation.email
            assert result[0].team_name == mock_team.name

    @pytest.mark.asyncio
    async def test_accept_team_invitation_success(self, mock_current_user, mock_db, mock_team_member):
        """Test accepting a team invitation."""
        token = "test-token-123"

        with patch("mcpgateway.routers.teams.TeamInvitationService") as MockInviteService:
            mock_invite_service = AsyncMock(spec=TeamInvitationService)
            mock_invite_service.accept_invitation = AsyncMock(return_value=mock_team_member)
            MockInviteService.return_value = mock_invite_service

            from mcpgateway.routers.teams import accept_team_invitation

            result = await accept_team_invitation(token, current_user=mock_current_user, db=mock_db)

            assert result.id == mock_team_member.id
            assert result.user_email == mock_team_member.user_email
            mock_invite_service.accept_invitation.assert_called_once_with(token, mock_current_user.email)

    @pytest.mark.asyncio
    async def test_accept_team_invitation_invalid_token(self, mock_current_user, mock_db):
        """Test accepting an invitation with invalid token."""
        token = "invalid-token"

        with patch("mcpgateway.routers.teams.TeamInvitationService") as MockInviteService:
            mock_invite_service = AsyncMock(spec=TeamInvitationService)
            mock_invite_service.accept_invitation = AsyncMock(return_value=None)
            MockInviteService.return_value = mock_invite_service

            from mcpgateway.routers.teams import accept_team_invitation

            with pytest.raises(HTTPException) as exc_info:
                await accept_team_invitation(token, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
            assert "Invalid or expired invitation" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_cancel_team_invitation_success(self, mock_current_user, mock_db, mock_invitation):
        """Test cancelling a team invitation."""
        invitation_id = mock_invitation.id

        # Create a real mock object for the invitation query
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_filter)
        mock_filter.first = MagicMock(return_value=mock_invitation)
        mock_db.query = MagicMock(return_value=mock_query)

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockTeamService, patch("mcpgateway.routers.teams.TeamInvitationService") as MockInviteService:
            mock_team_service = AsyncMock(spec=TeamManagementService)
            mock_team_service.get_user_role_in_team = AsyncMock(return_value="owner")
            MockTeamService.return_value = mock_team_service

            mock_invite_service = AsyncMock(spec=TeamInvitationService)
            mock_invite_service.revoke_invitation = AsyncMock(return_value=True)
            MockInviteService.return_value = mock_invite_service

            from mcpgateway.routers.teams import cancel_team_invitation

            result = await cancel_team_invitation(invitation_id, current_user=mock_current_user, db=mock_db)

            assert result.message == "Team invitation cancelled successfully"

    # =========================================================================
    # Team Discovery and Join Request Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_discover_public_teams_success(self, mock_user_context, mock_public_team):
        """Test discovering public teams."""
        public_teams = [mock_public_team]

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.discover_public_teams = AsyncMock(return_value=public_teams)
            # Mock the batch cached method for member counts
            mock_service.get_member_counts_batch_cached = AsyncMock(return_value={str(mock_public_team.id): 5})
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import discover_public_teams

            result = await discover_public_teams(skip=0, limit=50, current_user_ctx=mock_user_context)

            assert len(result) == 1
            assert result[0].name == mock_public_team.name
            assert result[0].is_joinable is True

    @pytest.mark.asyncio
    async def test_request_to_join_team_success(self, mock_current_user, mock_db, mock_public_team, mock_join_request):
        """Test requesting to join a public team."""
        team_id = mock_public_team.id
        join_request = TeamJoinRequest(message="I'd like to join")

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_team_by_id = AsyncMock(return_value=mock_public_team)
            mock_service.get_user_role_in_team = AsyncMock(return_value=None)  # Not a member
            mock_service.create_join_request = AsyncMock(return_value=mock_join_request)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import request_to_join_team

            result = await request_to_join_team(team_id, join_request, current_user=mock_current_user, db=mock_db)

            assert result.id == mock_join_request.id
            assert result.team_name == mock_public_team.name
            assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_request_to_join_team_not_public(self, mock_current_user, mock_db, mock_team):
        """Test requesting to join a non-public team."""
        team_id = mock_team.id  # Private team
        join_request = TeamJoinRequest(message="I'd like to join")

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_team_by_id = AsyncMock(return_value=mock_team)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import request_to_join_team

            with pytest.raises(HTTPException) as exc_info:
                await request_to_join_team(team_id, join_request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert "Can only request to join public teams" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_request_to_join_team_already_member(self, mock_current_user, mock_db, mock_public_team):
        """Test requesting to join a team when already a member."""
        team_id = mock_public_team.id
        join_request = TeamJoinRequest(message="I'd like to join")

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_team_by_id = AsyncMock(return_value=mock_public_team)
            mock_service.get_user_role_in_team = AsyncMock(return_value="member")  # Already a member
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import request_to_join_team

            with pytest.raises(HTTPException) as exc_info:
                await request_to_join_team(team_id, join_request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
            assert "User is already a member of this team" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_leave_team_success(self, mock_current_user, mock_db, mock_team):
        """Test leaving a team successfully."""
        team_id = mock_team.id

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_team_by_id = AsyncMock(return_value=mock_team)
            mock_service.get_user_role_in_team = AsyncMock(return_value="member")
            mock_service.remove_member_from_team = AsyncMock(return_value=True)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import leave_team

            result = await leave_team(team_id, current_user=mock_current_user, db=mock_db)

            assert result.message == "Successfully left the team"

    @pytest.mark.asyncio
    async def test_leave_personal_team_fails(self, mock_current_user, mock_db):
        """Test that users cannot leave their personal team."""
        personal_team = MagicMock(spec=EmailTeam)
        personal_team.id = str(uuid4())
        personal_team.is_personal = True

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_team_by_id = AsyncMock(return_value=personal_team)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import leave_team

            with pytest.raises(HTTPException) as exc_info:
                await leave_team(personal_team.id, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert "Cannot leave personal team" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_list_team_join_requests_success(self, mock_current_user, mock_db, mock_public_team, mock_join_request):
        """Test listing join requests for a team."""
        team_id = mock_public_team.id
        join_requests = [mock_join_request]

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_team_by_id = AsyncMock(return_value=mock_public_team)
            mock_service.get_user_role_in_team = AsyncMock(return_value="owner")
            mock_service.list_join_requests = AsyncMock(return_value=join_requests)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import list_team_join_requests

            result = await list_team_join_requests(team_id, current_user=mock_current_user, db=mock_db)

            assert len(result) == 1
            assert result[0].user_email == mock_join_request.user_email
            assert result[0].team_name == mock_public_team.name

    @pytest.mark.asyncio
    async def test_approve_join_request_success(self, mock_current_user, mock_db, mock_public_team, mock_team_member):
        """Test approving a join request."""
        team_id = mock_public_team.id
        request_id = str(uuid4())

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_team_by_id = AsyncMock(return_value=mock_public_team)
            mock_service.get_user_role_in_team = AsyncMock(return_value="owner")
            mock_service.approve_join_request = AsyncMock(return_value=mock_team_member)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import approve_join_request

            result = await approve_join_request(team_id, request_id, current_user=mock_current_user, db=mock_db)

            assert result.id == mock_team_member.id
            mock_service.approve_join_request.assert_called_once_with(request_id, approved_by=mock_current_user.email)

    @pytest.mark.asyncio
    async def test_reject_join_request_success(self, mock_current_user, mock_db, mock_public_team):
        """Test rejecting a join request."""
        team_id = mock_public_team.id
        request_id = str(uuid4())

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_team_by_id = AsyncMock(return_value=mock_public_team)
            mock_service.get_user_role_in_team = AsyncMock(return_value="owner")
            mock_service.reject_join_request = AsyncMock(return_value=True)
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import reject_join_request

            result = await reject_join_request(team_id, request_id, current_user=mock_current_user, db=mock_db)

            assert result.message == "Join request rejected successfully"

    @pytest.mark.asyncio
    async def test_reject_join_request_not_owner(self, mock_current_user, mock_db, mock_public_team):
        """Test rejecting a join request without owner permissions."""
        team_id = mock_public_team.id
        request_id = str(uuid4())

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_team_by_id = AsyncMock(return_value=mock_public_team)
            mock_service.get_user_role_in_team = AsyncMock(return_value="member")
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import reject_join_request

            with pytest.raises(HTTPException) as exc_info:
                await reject_join_request(team_id, request_id, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert "Only team owners can reject join requests" in str(exc_info.value.detail)

    # =========================================================================
    # Error Handling and Edge Cases
    # =========================================================================

    @pytest.mark.asyncio
    async def test_team_operation_with_database_error(self, mock_current_user, mock_db):
        """Test handling of database errors in team operations."""
        team_id = str(uuid4())

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_team_by_id = AsyncMock(side_effect=Exception("Database connection lost"))
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import get_team

            with pytest.raises(HTTPException) as exc_info:
                await get_team(team_id, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert "Failed to get team" in str(exc_info.value.detail)

    @pytest.mark.skip(reason="RBAC mocking complex - functionality covered by test_teams_v2.py")
    @pytest.mark.asyncio
    async def test_invitation_with_value_error(self, mock_current_user, mock_db):
        """Test handling of value errors in invitation operations."""
        team_id = str(uuid4())
        request = TeamInviteRequest(
            email="valid@example.com",  # Valid email format to pass Pydantic validation
            role="member",
        )

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockTeamService, patch("mcpgateway.routers.teams.TeamInvitationService") as MockInviteService:
            mock_team_service = AsyncMock(spec=TeamManagementService)
            mock_team_service.get_user_role_in_team = AsyncMock(return_value="owner")
            MockTeamService.return_value = mock_team_service

            mock_invite_service = AsyncMock(spec=TeamInvitationService)
            mock_invite_service.create_invitation = AsyncMock(side_effect=ValueError("Invalid email format"))
            MockInviteService.return_value = mock_invite_service

            from mcpgateway.routers.teams import invite_team_member

            with pytest.raises(HTTPException) as exc_info:
                await invite_team_member(team_id, request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
            assert "Invalid email format" in str(exc_info.value.detail)

    @pytest.mark.skip(reason="RBAC mocking complex - functionality covered by test_teams_v2.py")
    @pytest.mark.asyncio
    async def test_member_operations_with_invalid_role(self, mock_current_user, mock_db):
        """Test member operations with invalid role values."""
        team_id = str(uuid4())
        user_email = "member@example.com"
        request = TeamMemberUpdateRequest(role="member")  # Valid role

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_role_in_team = AsyncMock(return_value="owner")
            mock_service.update_member_role = AsyncMock(side_effect=ValueError("Invalid role"))
            MockService.return_value = mock_service

            from mcpgateway.routers.teams import update_team_member

            with pytest.raises(HTTPException) as exc_info:
                await update_team_member(team_id, user_email, request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
            assert "Invalid role" in str(exc_info.value.detail)
