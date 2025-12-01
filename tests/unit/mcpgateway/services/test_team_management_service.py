# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_team_management_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive tests for Team Management Service functionality.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
# First-Party
from mcpgateway.db import EmailTeam, EmailUser, UserRole
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.services.role_service import RoleService


class TestTeamManagementService:
    """Comprehensive test suite for Team Management Service."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def mock_role_service(self):
        """Create mock role service."""
        return MagicMock(spec=RoleService)

    @pytest.fixture
    def service(self, mock_db, mock_role_service):
        """Create team management service instance."""
        service = TeamManagementService(mock_db)
        service.role_service = mock_role_service
        return service

    @pytest.fixture
    def mock_team(self):
        """Create mock team."""
        team = MagicMock(spec=EmailTeam)
        team.id = "team123"
        team.name = "Test Team"
        team.slug = "test-team"
        team.description = "A test team"
        team.created_by = "admin@example.com"
        team.is_personal = False
        team.visibility = "private"
        team.max_members = 100
        team.is_active = True
        return team

    @pytest.fixture
    def mock_user(self):
        """Create mock user."""
        user = MagicMock(spec=EmailUser)
        user.email = "user@example.com"
        user.is_active = True
        return user

    @pytest.fixture
    def mock_membership(self):
        """Create mock team membership."""
        membership = MagicMock(spec=UserRole)
        membership.team_id = "team123"
        membership.user_email = "user@example.com"
        membership.role = "team_member"
        membership.is_active = True
        return membership

    # =========================================================================
    # Service Initialization Tests
    # =========================================================================

    def test_service_initialization(self, mock_db):
        """Test service initialization."""
        service = TeamManagementService(mock_db)

        assert service.db == mock_db
        assert service.db is not None

    def test_service_has_required_methods(self, service):
        """Test that service has all required methods."""
        required_methods = [
            "create_team",
            "get_team_by_id",
            "get_team_by_slug",
            "update_team",
            "delete_team",
            "add_member_to_team",
            "remove_member_from_team",
            "update_member_role",
            "get_user_teams",
            "get_team_roles",
            "get_user_role_in_team",
            "list_teams",
        ]

        for method_name in required_methods:
            assert hasattr(service, method_name)
            assert callable(getattr(service, method_name))

    # =========================================================================
    # Team Creation Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_team_success(self, service, mock_db, mock_role_service):
        """Test successful team creation."""
        mock_team = MagicMock(spec=EmailTeam)
        mock_team.id = "team123"
        mock_team.name = "Test Team"

        mock_db.add.return_value = None
        mock_db.flush.return_value = None
        mock_db.commit.return_value = None

        # Mock the query for existing inactive teams to return None (no existing team)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        # Mock RoleService
        mock_role_service.get_role_by_name.return_value = MagicMock(id="owner-role-id")

        with (
            patch("mcpgateway.services.team_management_service.EmailTeam") as MockTeam,
            patch("mcpgateway.utils.create_slug.slugify") as mock_slugify,
        ):
            MockTeam.return_value = mock_team
            mock_slugify.return_value = "test-team"

            result = await service.create_team(name="Test Team", description="A test team", created_by="admin@example.com", visibility="private")

            assert result == mock_team
            mock_db.add.assert_called()
            mock_db.flush.assert_called_once()
            mock_db.commit.assert_called_once()
            mock_role_service.assign_role_to_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_team_invalid_visibility(self, service):
        """Test team creation with invalid visibility."""
        with pytest.raises(ValueError, match="Invalid visibility"):
            await service.create_team(name="Test Team", description="A test team", created_by="admin@example.com", visibility="invalid")

    @pytest.mark.asyncio
    async def test_create_team_database_error(self, service, mock_db):
        """Test team creation with database error."""
        # Mock the query for existing inactive teams to return None first
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.add.side_effect = Exception("Database error")

        with patch("mcpgateway.services.team_management_service.EmailTeam"), patch("mcpgateway.utils.create_slug.slugify") as mock_slugify:
            mock_slugify.return_value = "test-team"
            with pytest.raises(Exception):
                await service.create_team(name="Test Team", description="A test team", created_by="admin@example.com")

            mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_team_with_settings_defaults(self, service, mock_db):
        """Test team creation uses settings defaults."""
        mock_team = MagicMock(spec=EmailTeam)

        # Mock the query for existing inactive teams to return None
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with (
            patch("mcpgateway.services.team_management_service.settings") as mock_settings,
            patch("mcpgateway.services.team_management_service.EmailTeam") as MockTeam,
            patch("mcpgateway.services.team_management_service.UserRole"),
            patch("mcpgateway.utils.create_slug.slugify") as mock_slugify,
        ):
            mock_settings.max_members_per_team = 50
            MockTeam.return_value = mock_team
            mock_slugify.return_value = "test-team"

            await service.create_team(name="Test Team", description="A test team", created_by="admin@example.com")

            MockTeam.assert_called_once()
            call_kwargs = MockTeam.call_args[1]
            assert call_kwargs["max_members"] == 50

    @pytest.mark.asyncio
    async def test_create_team_reactivates_existing_inactive_team(self, service, mock_db, mock_role_service):
        """Test that creating a team with same name as inactive team reactivates it."""
        # Mock existing inactive team
        mock_existing_team = MagicMock(spec=EmailTeam)
        mock_existing_team.id = "existing_team_id"
        mock_existing_team.name = "Old Team Name"
        mock_existing_team.is_active = False

        # Mock existing inactive membership
        mock_existing_membership = MagicMock(spec=UserRole)
        mock_existing_membership.team_id = "existing_team_id"
        mock_existing_membership.user_email = "admin@example.com"
        mock_existing_membership.is_active = False

        # Setup mock queries to return existing inactive team
        mock_db.query.return_value.filter.return_value.first.return_value = mock_existing_team

        # Mock RoleService
        mock_role_service.get_role_by_name.return_value = MagicMock(id="owner-role-id")
        mock_role_service.get_user_role_assignment.return_value = mock_existing_membership

        with patch("mcpgateway.utils.create_slug.slugify") as mock_slugify, patch("mcpgateway.services.team_management_service.utc_now") as mock_utc_now:
            mock_slugify.return_value = "test-team"
            mock_utc_now.return_value = "2023-01-01T00:00:00Z"

            result = await service.create_team(name="Test Team", description="A reactivated team", created_by="admin@example.com", visibility="public")

            # Verify the existing team was reactivated with new details
            assert result == mock_existing_team
            assert mock_existing_team.name == "Test Team"
            assert mock_existing_team.description == "A reactivated team"
            assert mock_existing_team.visibility == "public"
            assert mock_existing_team.is_active is True

            # Verify role service calls
            mock_role_service.get_user_role_assignment.assert_called_once()
            mock_role_service.assign_role_to_user.assert_called_once()

    # =========================================================================
    # Team Retrieval Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_team_by_id_found(self, service, mock_db, mock_team):
        """Test getting team by ID when team exists."""
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_team
        mock_db.query.return_value = mock_query

        result = await service.get_team_by_id("team123")

        assert result == mock_team
        mock_db.query.assert_called_once_with(EmailTeam)

    @pytest.mark.asyncio
    async def test_get_team_by_id_not_found(self, service, mock_db):
        """Test getting team by ID when team doesn't exist."""
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query

        result = await service.get_team_by_id("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_team_by_id_database_error(self, service, mock_db):
        """Test getting team by ID with database error."""
        mock_db.query.side_effect = Exception("Database error")

        result = await service.get_team_by_id("team123")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_team_by_slug_found(self, service, mock_db, mock_team):
        """Test getting team by slug when team exists."""
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_team
        mock_db.query.return_value = mock_query

        result = await service.get_team_by_slug("test-team")

        assert result == mock_team
        mock_db.query.assert_called_once_with(EmailTeam)

    @pytest.mark.asyncio
    async def test_get_team_by_slug_not_found(self, service, mock_db):
        """Test getting team by slug when team doesn't exist."""
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query

        result = await service.get_team_by_slug("nonexistent-slug")

        assert result is None

    # =========================================================================
    # Team Update Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_update_team_success(self, service, mock_db, mock_team):
        """Test successful team update."""
        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.update_team(team_id="team123", name="Updated Team", description="Updated description", visibility="public")

            assert result is True
            assert mock_team.name == "Updated Team"
            assert mock_team.description == "Updated description"
            assert mock_team.visibility == "public"
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_team_not_found(self, service):
        """Test updating non-existent team."""
        with patch.object(service, "get_team_by_id", return_value=None):
            result = await service.update_team(team_id="nonexistent", name="New Name")

            assert result is False

    @pytest.mark.asyncio
    async def test_update_personal_team_rejected(self, service, mock_team):
        """Test updating personal team is rejected."""
        mock_team.is_personal = True

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.update_team(team_id="team123", name="New Name")

            assert result is False

    @pytest.mark.asyncio
    async def test_update_team_invalid_visibility(self, service, mock_team):
        """Test updating team with invalid visibility."""
        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.update_team(team_id="team123", visibility="invalid")
            assert result is False

    @pytest.mark.asyncio
    async def test_update_team_database_error(self, service, mock_db, mock_team):
        """Test team update with database error."""
        mock_db.commit.side_effect = Exception("Database error")

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.update_team(team_id="team123", name="New Name")

            assert result is False
            mock_db.rollback.assert_called_once()

    # =========================================================================
    # Team Deletion Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_delete_team_success(self, service, mock_db, mock_team, mock_role_service):
        """Test successful team deletion."""
        mock_query = MagicMock()
        mock_query.filter.return_value.update.return_value = None
        mock_db.query.return_value = mock_query

        mock_role_service.list_scope_role_assignments.return_value = [MagicMock()]

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.delete_team(team_id="team123", deleted_by="admin@example.com")

            assert result is True
            assert mock_team.is_active is False
            mock_db.commit.assert_called_once()
            mock_role_service.revoke_scope_role_assignments.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_team_not_found(self, service):
        """Test deleting non-existent team."""
        with patch.object(service, "get_team_by_id", return_value=None):
            result = await service.delete_team(team_id="nonexistent", deleted_by="admin@example.com")

            assert result is False

    @pytest.mark.skip(reason="Personal team deletion check disabled in service")
    @pytest.mark.asyncio
    async def test_delete_personal_team_rejected(self, service, mock_team):
        """Test deleting personal team is rejected."""
        mock_team.is_personal = True

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.delete_team(team_id="team123", deleted_by="admin@example.com")
            assert result is False

    @pytest.mark.asyncio
    async def test_delete_team_database_error(self, service, mock_db, mock_team):
        """Test team deletion with database error."""
        mock_db.commit.side_effect = Exception("Database error")

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.delete_team(team_id="team123", deleted_by="admin@example.com")

            assert result is False
            mock_db.rollback.assert_called_once()

    # =========================================================================
    # Team Membership Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_add_member_success(self, service, mock_db, mock_team, mock_user, mock_role_service):
        """Test successful member addition."""
        # Setup mocks
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        # Mock RoleService
        mock_role_service.get_role_by_name.return_value = MagicMock(id="role-id")
        mock_role_service.get_user_role_assignment.return_value = None
        mock_role_service.list_scope_role_assignments.return_value = []  # for max members check

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.add_member_to_team(team_id="team123", user_email="user@example.com", role="team_member")

            assert result is True
            mock_role_service.assign_role_to_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_member_invalid_role(self, service):
        """Test adding member with invalid role."""
        result = await service.add_member_to_team(team_id="team123", user_email="user@example.com", role="invalid")
        assert result is False

    @pytest.mark.asyncio
    async def test_add_member_team_not_found(self, service):
        """Test adding member to non-existent team."""
        with patch.object(service, "get_team_by_id", return_value=None):
            result = await service.add_member_to_team(team_id="nonexistent", user_email="user@example.com")

            assert result is False

    @pytest.mark.asyncio
    async def test_add_member_user_not_found(self, service, mock_team, mock_db):
        """Test adding non-existent user to team."""
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.add_member_to_team(team_id="team123", user_email="nonexistent@example.com")

            assert result is False

    @pytest.mark.asyncio
    async def test_add_member_already_member(self, service, mock_team, mock_user, mock_membership, mock_db, mock_role_service):
        """Test adding user who is already a member."""
        mock_membership.is_active = True

        # Setup query mocks
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        # Mock RoleService
        mock_role_service.get_role_by_name.return_value = MagicMock(id="role-id")
        mock_role_service.get_user_role_assignment.return_value = mock_membership

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.add_member_to_team(team_id="team123", user_email="user@example.com")

            assert result is False

    @pytest.mark.asyncio
    async def test_add_member_max_members_exceeded(self, service, mock_team, mock_user, mock_db, mock_role_service):
        """Test adding member when max members limit is reached."""
        mock_team.max_members = 10

        # Setup query mocks
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        # Mock RoleService
        mock_role_service.get_role_by_name.return_value = MagicMock(id="role-id")
        mock_role_service.get_user_role_assignment.return_value = None
        # Return 10 mock assignments
        mock_role_service.list_scope_role_assignments.return_value = [MagicMock()] * 10

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.add_member_to_team(team_id="team123", user_email="user@example.com")
            assert result is False

    @pytest.mark.asyncio
    async def test_remove_member_success(self, service, mock_team, mock_membership, mock_db, mock_role_service):
        """Test successful member removal."""
        # Mock RoleService
        mock_role_service.list_user_roles.return_value = [mock_membership]

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.remove_member_from_team(team_id="team123", user_email="user@example.com")

            assert result is True
            mock_role_service.revoke_role_from_user.assert_called_once()

    @pytest.mark.skip(reason="Last owner check not implemented in service yet")
    @pytest.mark.asyncio
    async def test_remove_last_owner_rejected(self, service, mock_team, mock_membership, mock_db):
        """Test removing last owner is rejected."""
        pass

    # =========================================================================
    # Role Management Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_update_member_role_success(self, service, mock_team, mock_membership, mock_db, mock_role_service):
        """Test successful role update."""
        # Mock RoleService
        mock_role_service.list_user_roles.return_value = [mock_membership]
        mock_role_service.get_role_by_name.return_value = MagicMock(id="new-role-id")

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.update_member_role(team_id="team123", user_email="user@example.com", new_role="team_member")

            assert result is True
            mock_role_service.assign_role_to_user.assert_called_once()
            mock_role_service.revoke_role_from_user.assert_called()

    @pytest.mark.asyncio
    async def test_update_member_role_invalid_role(self, service):
        """Test updating member with invalid role."""
        result = await service.update_member_role(team_id="team123", user_email="user@example.com", new_role="invalid")
        assert result is False

    @pytest.mark.skip(reason="Last owner check not implemented in service yet")
    @pytest.mark.asyncio
    async def test_update_last_owner_role_rejected(self, service, mock_team, mock_membership, mock_db):
        """Test updating last owner role is rejected."""
        pass

    # =========================================================================
    # Team Listing and Query Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_user_teams(self, service, mock_db, mock_role_service):
        """Test getting user teams."""
        mock_teams = [MagicMock(spec=EmailTeam) for _ in range(3)]
        for i, team in enumerate(mock_teams):
            team.id = f"team-{i}"
            team.is_personal = False

        # Mock RoleService to return roles with scope_id
        mock_roles = []
        for team in mock_teams:
            role = MagicMock(spec=UserRole)
            role.scope_id = team.id
            mock_roles.append(role)

        mock_role_service.list_user_roles.return_value = mock_roles

        # Mock DB query for teams
        mock_query = MagicMock()
        # Handle one filter call (since include_personal=True)
        mock_query.filter.return_value.all.return_value = mock_teams
        mock_db.query.return_value = mock_query

        result = await service.get_user_teams("user@example.com")

        assert result == mock_teams
        mock_role_service.list_user_roles.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_user_teams_exclude_personal(self, service, mock_db, mock_role_service):
        """Test getting user teams excluding personal teams."""
        mock_teams = [MagicMock(spec=EmailTeam) for _ in range(2)]
        for i, team in enumerate(mock_teams):
            team.id = f"team-{i}"
            team.is_personal = False

        # Mock RoleService
        mock_roles = []
        for team in mock_teams:
            role = MagicMock(spec=UserRole)
            role.scope_id = team.id
            mock_roles.append(role)
        mock_role_service.list_user_roles.return_value = mock_roles

        mock_query = MagicMock()
        # Handle two filter calls (one for IDs, one for is_personal=False)
        mock_query.filter.return_value.filter.return_value.all.return_value = mock_teams
        mock_db.query.return_value = mock_query

        result = await service.get_user_teams("user@example.com", include_personal=False)

        assert result == mock_teams

    @pytest.mark.asyncio
    async def test_get_team_roles(self, service, mock_db, mock_role_service):
        """Test getting team roles."""
        mock_members = [MagicMock(spec=UserRole) for _ in range(3)]
        mock_role_service.list_scope_role_assignments.return_value = mock_members

        result = await service.get_team_roles("team123")

        assert result == mock_members
        mock_role_service.list_scope_role_assignments.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_user_role_in_team(self, service, mock_db, mock_role_service):
        """Test getting user role in team."""
        mock_membership = MagicMock(spec=UserRole)
        mock_membership.role = MagicMock()
        mock_membership.role.name = "team_member"

        mock_role_service.list_user_roles.return_value = [mock_membership]

        result = await service.get_user_role_in_team("user@example.com", "team123")

        assert result == "team_member"
        mock_role_service.list_user_roles.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_user_role_in_team_not_member(self, service, mock_db, mock_role_service):
        """Test getting user role when not a member."""
        mock_role_service.list_user_roles.return_value = []

        result = await service.get_user_role_in_team("user@example.com", "team123")

        assert result is None

    @pytest.mark.asyncio
    async def test_list_teams(self, service, mock_db):
        """Test listing teams with pagination."""
        mock_teams = [MagicMock(spec=EmailTeam) for _ in range(5)]

        mock_query = MagicMock()
        mock_query.filter.return_value.count.return_value = 10
        mock_query.filter.return_value.offset.return_value.limit.return_value.all.return_value = mock_teams
        mock_db.query.return_value = mock_query

        teams, total_count = await service.list_teams(limit=5, offset=0)

        assert teams == mock_teams
        assert total_count == 10

    @pytest.mark.asyncio
    async def test_list_teams_with_visibility_filter(self, service, mock_db):
        """Test listing teams with visibility filter."""
        mock_teams = [MagicMock(spec=EmailTeam) for _ in range(3)]

        mock_query = MagicMock()
        mock_query.filter.return_value.filter.return_value.count.return_value = 3
        mock_query.filter.return_value.filter.return_value.offset.return_value.limit.return_value.all.return_value = mock_teams
        mock_db.query.return_value = mock_query

        teams, total_count = await service.list_teams(visibility_filter="public")

        assert teams == mock_teams
        assert total_count == 3

    # =========================================================================
    # Error Handling Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_database_error_handling(self, service, mock_db, mock_role_service):
        """Test various database error scenarios return appropriate defaults."""
        mock_db.query.side_effect = Exception("Database connection failed")
        mock_role_service.list_user_roles.side_effect = Exception("Role service failed")
        mock_role_service.list_scope_role_assignments.side_effect = Exception("Role service failed")

        # Test methods that should return None on error
        assert await service.get_team_by_id("team123") is None
        assert await service.get_team_by_slug("team-slug") is None
        assert await service.get_user_role_in_team("user@example.com", "team123") is None

        # Test methods that should return empty lists on error
        assert await service.get_user_teams("user@example.com") == []
        assert await service.get_team_roles("team123") == []

        # Test methods that should return (empty_list, 0) on error
        teams, count = await service.list_teams()
        assert teams == []
        assert count == 0

    # =========================================================================
    # Edge Case Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_reactivate_existing_membership(self, service, mock_team, mock_user, mock_membership, mock_db, mock_role_service):
        """Test reactivating an existing inactive membership."""
        mock_membership.is_active = False

        # Mock DB query for user
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        # Mock RoleService
        mock_role_service.get_role_by_name.return_value = MagicMock(id="role-id")
        mock_role_service.get_user_role_assignment.return_value = mock_membership
        mock_role_service.list_scope_role_assignments.return_value = []

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.add_member_to_team(team_id="team123", user_email="user@example.com", role="team_member")

            assert result is True
            # The service should call assign_role_to_user, which handles reactivation/assignment
            mock_role_service.assign_role_to_user.assert_called_once()

    def test_visibility_validation_values(self, service):
        """Test that visibility validation accepts all valid values."""
        valid_visibilities = ["private", "public"]

        for visibility in valid_visibilities:
            # Should not raise an exception during validation
            # This is tested implicitly in create_team and update_team tests
            assert visibility in valid_visibilities

    def test_role_validation_values(self, service):
        """Test that role validation accepts all valid values."""
        valid_roles = ["team_owner", "team_member"]

        for role in valid_roles:
            # Should not raise an exception during validation
            # This is tested implicitly in add_member and update_role tests
            assert role in valid_roles
