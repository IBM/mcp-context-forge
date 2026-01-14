# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_teams_v2.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive unit tests for teams router - V2 with improved RBAC mocking.
This module tests all team management endpoints including CRUD operations,
member management, invitations, and join requests.
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

# Third-Party
import pytest
from fastapi import HTTPException, status
from sqlalchemy.orm import Session


# First, patch RBAC decorators before any mcpgateway imports
def mock_require_permission_decorator(permission: str, resource_type=None):
    """Mock decorator that bypasses permission checks."""

    def decorator(func):
        return func

    return decorator


def mock_require_admin_permission():
    """Mock decorator that bypasses admin permission checks."""

    def decorator(func):
        return func

    return decorator


# Apply the patches before importing mcpgateway modules
with patch("mcpgateway.middleware.rbac.require_permission", mock_require_permission_decorator):
    with patch("mcpgateway.middleware.rbac.require_admin_permission", mock_require_admin_permission):
        # Now import mcpgateway modules with mocked decorators
        from mcpgateway.db import EmailTeam, EmailTeamMember, EmailUser
        from mcpgateway.routers import teams
        from mcpgateway.schemas import (
            EmailUserResponse,
            TeamCreateRequest,
            TeamMemberUpdateRequest,
            TeamUpdateRequest,
        )
        from mcpgateway.services.team_management_service import TeamManagementService

        # Force reload teams module to apply mocked decorators
        import importlib

        importlib.reload(teams)


class TestTeamsRouterV2:
    """Comprehensive test suite for teams router endpoints - V2."""

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
    def mock_user_context(self, mock_db):
        """Create mock user context with permissions."""
        return {"email": "test@example.com", "full_name": "Test User", "is_admin": False, "db": mock_db, "permissions": ["teams.create", "teams.read", "teams.update", "teams.delete"]}

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

            result = await teams.create_team(request, current_user_ctx=mock_user_context)

            assert result.id == mock_team.id
            assert result.name == mock_team.name
            assert result.description == mock_team.description
            mock_service.create_team.assert_called_once_with(
                name=request.name, description=request.description, created_by=mock_user_context["email"], visibility=request.visibility, max_members=request.max_members
            )

    @pytest.mark.asyncio
    async def test_create_team_value_error(self, mock_user_context):
        """Test team creation with invalid data."""
        request = TeamCreateRequest(
            name="Valid Name",  # Valid name to pass Pydantic validation
            description="A new team",
            visibility="private",
            max_members=50,
        )

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.create_team = AsyncMock(side_effect=ValueError("Team name cannot be empty"))
            MockService.return_value = mock_service

            with pytest.raises(HTTPException) as exc_info:
                await teams.create_team(request, current_user_ctx=mock_user_context)

            assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
            assert "Team name cannot be empty" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_get_team_success(self, mock_current_user, mock_db, mock_team):
        """Test getting a specific team successfully."""
        team_id = mock_team.id

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_team_by_id = AsyncMock(return_value=mock_team)
            mock_service.get_user_role_in_team = AsyncMock(return_value="member")
            MockService.return_value = mock_service

            result = await teams.get_team(team_id, current_user=mock_current_user, db=mock_db)

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

            with pytest.raises(HTTPException) as exc_info:
                await teams.get_team(team_id, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
            assert "Team not found" in str(exc_info.value.detail)

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

            result = await teams.update_team(team_id, request, current_user=mock_current_user, db=mock_db)

            assert result.id == mock_team.id
            mock_service.update_team.assert_called_once_with(team_id=team_id, name=request.name, description=request.description, visibility=request.visibility, max_members=request.max_members)

    @pytest.mark.asyncio
    async def test_delete_team_success(self, mock_current_user, mock_db):
        """Test deleting a team successfully."""
        team_id = str(uuid4())

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_user_role_in_team = AsyncMock(return_value="owner")
            mock_service.delete_team = AsyncMock(return_value=True)
            MockService.return_value = mock_service

            result = await teams.delete_team(team_id, current_user=mock_current_user, db=mock_db)

            assert result.message == "Team deleted successfully"
            mock_service.delete_team.assert_called_once_with(team_id, mock_current_user.email)

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

            result = await teams.list_team_members(
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

            result = await teams.update_team_member(team_id, user_email, request, current_user=mock_current_user, db=mock_db)

            assert result.role == "owner"
            mock_service.update_member_role.assert_called_once_with(team_id, user_email, request.role)

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

            result = await teams.remove_team_member(team_id, user_email, current_user=mock_current_user, db=mock_db)

            assert result.message == "Team member removed successfully"
            mock_service.remove_member_from_team.assert_called_once_with(team_id, user_email)

    # =========================================================================
    # Error Handling Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_team_operation_with_database_error(self, mock_current_user, mock_db):
        """Test handling of database errors in team operations."""
        team_id = str(uuid4())

        with patch("mcpgateway.routers.teams.TeamManagementService") as MockService:
            mock_service = AsyncMock(spec=TeamManagementService)
            mock_service.get_team_by_id = AsyncMock(side_effect=Exception("Database connection lost"))
            MockService.return_value = mock_service

            with pytest.raises(HTTPException) as exc_info:
                await teams.get_team(team_id, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert "Failed to get team" in str(exc_info.value.detail)
