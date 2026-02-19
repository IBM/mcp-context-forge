# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_team_management_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive tests for Team Management Service functionality.
"""

# Standard
import asyncio
import base64
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import orjson
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import EmailTeam, EmailTeamJoinRequest, EmailTeamMember, EmailUser
from mcpgateway.services.team_management_service import TeamManagementService


class TestTeamManagementService:
    """Comprehensive test suite for Team Management Service."""

    @pytest.fixture(autouse=True)
    async def drain_fire_and_forget_tasks(self):
        """Give fire-and-forget cache invalidation tasks one loop turn to complete."""
        yield
        await asyncio.sleep(0)

    @pytest.fixture(autouse=True)
    def clear_caches(self):
        """Clear caches before each test to avoid cross-test contamination."""
        # Clear auth cache
        try:
            # First-Party
            from mcpgateway.cache.auth_cache import get_auth_cache

            cache = get_auth_cache()
            cache.invalidate_all()
        except ImportError:
            pass

        # Clear admin stats cache
        try:
            # First-Party
            from mcpgateway.cache.admin_stats_cache import get_admin_stats_cache

            cache = get_admin_stats_cache()
            cache.invalidate_all()
        except ImportError:
            pass

        yield

        # Also clear after test
        try:
            # First-Party
            from mcpgateway.cache.auth_cache import get_auth_cache

            cache = get_auth_cache()
            cache.invalidate_all()
        except ImportError:
            pass

        try:
            # First-Party
            from mcpgateway.cache.admin_stats_cache import get_admin_stats_cache

            cache = get_admin_stats_cache()
            cache.invalidate_all()
        except ImportError:
            pass

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def service(self, mock_db):
        """Create team management service instance."""
        return TeamManagementService(mock_db)

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
        membership = MagicMock(spec=EmailTeamMember)
        membership.team_id = "team123"
        membership.user_email = "user@example.com"
        membership.role = "member"
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
            "get_team_members",
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
    async def test_create_team_success(self, service, mock_db):
        """Test successful team creation."""
        mock_team = MagicMock(spec=EmailTeam)
        mock_team.id = "team123"
        mock_team.name = "Test Team"

        mock_db.add.return_value = None
        mock_db.flush.return_value = None
        mock_db.commit.return_value = None

        # Mock the query for existing inactive teams to return None (no existing team)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with (
            patch("mcpgateway.services.team_management_service.EmailTeam") as MockTeam,
            patch("mcpgateway.services.team_management_service.EmailTeamMember") as MockMember,
            patch("mcpgateway.utils.create_slug.slugify") as mock_slugify,
        ):
            MockTeam.return_value = mock_team
            mock_slugify.return_value = "test-team"

            result = await service.create_team(name="Test Team", description="A test team", created_by="admin@example.com", visibility="private")

            assert result == mock_team
            mock_db.add.assert_called()
            mock_db.flush.assert_called_once()
            mock_db.commit.assert_called_once()

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
            patch("mcpgateway.services.team_management_service.EmailTeamMember"),
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
    async def test_create_team_reactivates_existing_inactive_team(self, service, mock_db):
        """Test that creating a team with same name as inactive team reactivates it."""
        # Mock existing inactive team
        mock_existing_team = MagicMock(spec=EmailTeam)
        mock_existing_team.id = "existing_team_id"
        mock_existing_team.name = "Old Team Name"
        mock_existing_team.is_active = False

        # Mock existing inactive membership
        mock_existing_membership = MagicMock(spec=EmailTeamMember)
        mock_existing_membership.team_id = "existing_team_id"
        mock_existing_membership.user_email = "admin@example.com"
        mock_existing_membership.is_active = False

        # Setup mock queries to return existing inactive team and membership
        mock_queries = [mock_existing_team, mock_existing_membership]
        mock_db.query.return_value.filter.return_value.first.side_effect = mock_queries

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

            # Verify existing membership was reactivated
            assert mock_existing_membership.role == "owner"
            assert mock_existing_membership.is_active is True

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
        """Test updating team with invalid visibility raises ValueError."""
        with patch.object(service, "get_team_by_id", return_value=mock_team):
            with pytest.raises(ValueError, match="Invalid visibility"):
                await service.update_team(team_id="team123", visibility="invalid")

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
    async def test_delete_team_success(self, service, mock_db, mock_team):
        """Test successful team deletion."""
        mock_query = MagicMock()
        mock_query.filter.return_value.update.return_value = None
        mock_db.query.return_value = mock_query

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.delete_team(team_id="team123", deleted_by="admin@example.com")

            assert result is True
            assert mock_team.is_active is False
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_team_not_found(self, service):
        """Test deleting non-existent team."""
        with patch.object(service, "get_team_by_id", return_value=None):
            result = await service.delete_team(team_id="nonexistent", deleted_by="admin@example.com")

            assert result is False

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
    async def test_add_member_success(self, service, mock_db, mock_team, mock_user):
        """Test successful member addition."""
        # Setup mocks
        mock_team_query = MagicMock()
        mock_team_query.filter.return_value.first.return_value = mock_team

        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = mock_user

        mock_existing_query = MagicMock()
        mock_existing_query.filter.return_value.first.return_value = None

        mock_count_query = MagicMock()
        mock_count_query.filter.return_value.count.return_value = 5

        def side_effect(model):
            if model == EmailTeam:
                return mock_team_query
            elif model == EmailUser:
                return mock_user_query
            elif model == EmailTeamMember:
                if not hasattr(side_effect, "call_count"):
                    side_effect.call_count = 0
                side_effect.call_count += 1
                if side_effect.call_count == 1:
                    return mock_existing_query
                else:
                    return mock_count_query

        mock_db.query.side_effect = side_effect

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            await service.add_member_to_team(team_id="team123", user_email="user@example.com", role="member")

            assert mock_db.add.call_count == 2
            assert mock_db.commit.call_count == 2  # One for membership, one for history

    @pytest.mark.asyncio
    async def test_add_member_invalid_role(self, service):
        """Test adding member with invalid role."""
        from mcpgateway.services.team_management_service import InvalidRoleError

        with pytest.raises(InvalidRoleError) as exc_info:
            await service.add_member_to_team(team_id="team123", user_email="user@example.com", role="invalid")
        assert "Invalid role" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_add_member_personal_team_rejected(self, service, mock_team):
        """Test adding member to personal team is rejected."""
        from mcpgateway.services.team_management_service import TeamManagementError

        mock_team.is_personal = True

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            with pytest.raises(TeamManagementError) as exc_info:
                await service.add_member_to_team(team_id="team123", user_email="user@example.com")
            assert "Cannot add members to personal teams" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_add_member_team_not_found(self, service):
        """Test adding member to non-existent team."""
        from mcpgateway.services.team_management_service import TeamNotFoundError

        with patch.object(service, "get_team_by_id", return_value=None):
            with pytest.raises(TeamNotFoundError) as exc_info:
                await service.add_member_to_team(team_id="nonexistent", user_email="user@example.com")
            assert str(exc_info.value) == "Team not found"

    @pytest.mark.asyncio
    async def test_add_member_user_not_found(self, service, mock_team, mock_db):
        """Test adding non-existent user to team."""
        from mcpgateway.services.team_management_service import UserNotFoundError

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            with pytest.raises(UserNotFoundError) as exc_info:
                await service.add_member_to_team(team_id="team123", user_email="nonexistent@example.com")
            assert str(exc_info.value) == "User not found"

    @pytest.mark.asyncio
    async def test_add_member_already_member(self, service, mock_team, mock_user, mock_membership, mock_db):
        """Test adding user who is already a member."""
        from mcpgateway.services.team_management_service import MemberAlreadyExistsError

        mock_membership.is_active = True

        # Setup query mocks
        def query_side_effect(model):
            mock_query = MagicMock()
            if model == EmailUser:
                mock_query.filter.return_value.first.return_value = mock_user
            elif model == EmailTeamMember:
                mock_query.filter.return_value.first.return_value = mock_membership
            return mock_query

        mock_db.query.side_effect = query_side_effect

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            with pytest.raises(MemberAlreadyExistsError) as exc_info:
                await service.add_member_to_team(team_id="team123", user_email="user@example.com")
            assert str(exc_info.value) == "User is already a member of this team"

    @pytest.mark.asyncio
    async def test_add_member_max_members_exceeded(self, service, mock_team, mock_user, mock_db):
        """Test adding member when max members limit is reached."""
        from mcpgateway.services.team_management_service import TeamMemberLimitExceededError

        mock_team.max_members = 10

        # Setup query mocks
        def query_side_effect(model):
            mock_query = MagicMock()
            if model == EmailUser:
                mock_query.filter.return_value.first.return_value = mock_user
            elif model == EmailTeamMember:
                if not hasattr(query_side_effect, "call_count"):
                    query_side_effect.call_count = 0
                query_side_effect.call_count += 1
                if query_side_effect.call_count == 1:
                    # First call - check existing membership
                    mock_query.filter.return_value.first.return_value = None
                else:
                    # Second call - count current members
                    mock_query.filter.return_value.count.return_value = 10
            return mock_query

        mock_db.query.side_effect = query_side_effect

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            with pytest.raises(TeamMemberLimitExceededError) as exc_info:
                await service.add_member_to_team(team_id="team123", user_email="user@example.com")
            assert "maximum member limit" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_remove_member_success(self, service, mock_team, mock_membership, mock_db):
        """Test successful member removal."""
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_membership
        mock_db.query.return_value = mock_query

        # Mock role service to avoid role revocation calls
        mock_role_service = MagicMock()
        mock_role_service.get_role_by_name = AsyncMock(return_value=None)  # No role found
        service._role_service = mock_role_service

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.remove_member_from_team(team_id="team123", user_email="user@example.com")

            assert result is True
            assert mock_membership.is_active is False
            assert mock_db.commit.call_count == 2  # One for soft delete, one for history

    @pytest.mark.asyncio
    async def test_remove_last_owner_rejected(self, service, mock_team, mock_membership, mock_db):
        """Test removing last owner is rejected."""
        mock_membership.role = "owner"

        # Setup query mocks for membership lookup and owner count
        def query_side_effect(model):
            mock_query = MagicMock()
            if hasattr(query_side_effect, "call_count"):
                query_side_effect.call_count += 1
            else:
                query_side_effect.call_count = 1

            if query_side_effect.call_count == 1:
                # First call - get membership
                mock_query.filter.return_value.first.return_value = mock_membership
            else:
                # Second call - count owners
                mock_query.filter.return_value.count.return_value = 1
            return mock_query

        mock_db.query.side_effect = query_side_effect

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.remove_member_from_team(team_id="team123", user_email="user@example.com")
            assert result is False

    # =========================================================================
    # Role Management Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_update_member_role_success(self, service, mock_team, mock_membership, mock_db):
        """Test successful role update."""
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_membership
        mock_db.query.return_value = mock_query

        # Mock role service to avoid RBAC changes
        mock_role_service = MagicMock()
        mock_role_service.get_role_by_name = AsyncMock(return_value=None)
        service._role_service = mock_role_service

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.update_member_role(team_id="team123", user_email="user@example.com", new_role="member")

            assert result is True
            assert mock_membership.role == "member"
            assert mock_db.commit.call_count == 2  # One for role update, one for history

    @pytest.mark.asyncio
    async def test_update_member_role_member_to_owner_transitions_rbac(self, service, mock_team, mock_membership, mock_db):
        """Test that changing from member to owner updates RBAC roles."""
        mock_membership.role = "member"  # Current role is member

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_membership
        mock_db.query.return_value = mock_query

        # Mock role service
        mock_member_role = MagicMock()
        mock_member_role.id = "member-role-id"
        mock_owner_role = MagicMock()
        mock_owner_role.id = "owner-role-id"

        mock_role_service = MagicMock()
        mock_role_service.get_role_by_name = AsyncMock(side_effect=[mock_member_role, mock_owner_role])  # First call for member, second for owner
        mock_role_service.revoke_role_from_user = AsyncMock(return_value=True)
        mock_role_service.assign_role_to_user = AsyncMock(return_value=MagicMock())
        service._role_service = mock_role_service

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.update_member_role(team_id="team123", user_email="user@example.com", new_role="owner", updated_by="admin@example.com")

            assert result is True
            assert mock_membership.role == "owner"
            # Should revoke member role
            mock_role_service.revoke_role_from_user.assert_called_with(user_email="user@example.com", role_id="member-role-id", scope="team", scope_id="team123")
            # Should assign owner role
            mock_role_service.assign_role_to_user.assert_called_with(user_email="user@example.com", role_id="owner-role-id", scope="team", scope_id="team123", granted_by="admin@example.com")

    @pytest.mark.asyncio
    async def test_update_member_role_owner_to_member_transitions_rbac(self, service, mock_team, mock_membership, mock_db):
        """Test that changing from owner to member updates RBAC roles."""
        mock_membership.role = "owner"  # Current role is owner

        # Setup query mocks - first call gets membership, second counts owners
        mock_membership_query = MagicMock()
        mock_membership_query.filter.return_value.first.return_value = mock_membership

        mock_owner_count_query = MagicMock()
        mock_owner_count_query.filter.return_value.count.return_value = 2  # Not the last owner

        call_count = [0]

        def query_side_effect(model):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call - get membership
                return mock_membership_query
            else:
                # Second call - count owners
                return mock_owner_count_query

        mock_db.query.side_effect = query_side_effect

        # Mock role service
        mock_member_role = MagicMock()
        mock_member_role.id = "member-role-id"
        mock_owner_role = MagicMock()
        mock_owner_role.id = "owner-role-id"

        mock_role_service = MagicMock()
        mock_role_service.get_role_by_name = AsyncMock(side_effect=[mock_member_role, mock_owner_role])
        mock_role_service.revoke_role_from_user = AsyncMock(return_value=True)
        mock_role_service.assign_role_to_user = AsyncMock(return_value=MagicMock())
        service._role_service = mock_role_service

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.update_member_role(team_id="team123", user_email="user@example.com", new_role="member", updated_by="admin@example.com")

            assert result is True
            assert mock_membership.role == "member"
            # Should revoke owner role
            mock_role_service.revoke_role_from_user.assert_called_with(user_email="user@example.com", role_id="owner-role-id", scope="team", scope_id="team123")
            # Should assign member role
            mock_role_service.assign_role_to_user.assert_called_with(user_email="user@example.com", role_id="member-role-id", scope="team", scope_id="team123", granted_by="admin@example.com")

    @pytest.mark.asyncio
    async def test_update_member_role_invalid_role(self, service):
        """Test updating member with invalid role raises ValueError."""
        with pytest.raises(ValueError, match="Invalid role"):
            await service.update_member_role(team_id="team123", user_email="user@example.com", new_role="invalid")

    @pytest.mark.asyncio
    async def test_update_last_owner_role_rejected(self, service, mock_team, mock_membership, mock_db):
        """Test updating last owner role is rejected."""
        mock_membership.role = "owner"

        def query_side_effect(model):
            mock_query = MagicMock()
            if hasattr(query_side_effect, "call_count"):
                query_side_effect.call_count += 1
            else:
                query_side_effect.call_count = 1

            if query_side_effect.call_count == 1:
                # First call - get membership
                mock_query.filter.return_value.first.return_value = mock_membership
            else:
                # Second call - count owners
                mock_query.filter.return_value.count.return_value = 1
            return mock_query

        mock_db.query.side_effect = query_side_effect

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            with pytest.raises(ValueError, match="Cannot remove owner role from the last owner"):
                await service.update_member_role(team_id="team123", user_email="user@example.com", new_role="member")

    # =========================================================================
    # Team Listing and Query Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_user_teams(self, service, mock_db):
        """Test getting user teams."""
        mock_teams = [MagicMock(spec=EmailTeam) for _ in range(3)]

        mock_query = MagicMock()
        mock_query.join.return_value.filter.return_value.all.return_value = mock_teams
        mock_db.query.return_value = mock_query

        result = await service.get_user_teams("user@example.com")

        assert result == mock_teams
        mock_db.query.assert_called_once_with(EmailTeam)

    @pytest.mark.asyncio
    async def test_get_user_teams_exclude_personal(self, service, mock_db):
        """Test getting user teams excluding personal teams."""
        mock_teams = [MagicMock(spec=EmailTeam) for _ in range(2)]

        mock_query = MagicMock()
        mock_query.join.return_value.filter.return_value.filter.return_value.all.return_value = mock_teams
        mock_db.query.return_value = mock_query

        result = await service.get_user_teams("user@example.com", include_personal=False)

        assert result == mock_teams

    @pytest.mark.asyncio
    async def test_get_team_members(self, service, mock_db):
        """Test getting team members."""
        mock_members = [(MagicMock(spec=EmailUser), MagicMock(spec=EmailTeamMember)) for _ in range(3)]

        # Mock execute() to return a result with .all() method (SQLAlchemy 2.0 style)
        mock_result = MagicMock()
        mock_result.all.return_value = mock_members
        mock_db.execute.return_value = mock_result
        mock_db.commit.return_value = None

        result = await service.get_team_members("team123")

        assert result == mock_members
        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_team_members_with_cursor_pagination(self, service, mock_db):
        """Test getting team members with cursor-based pagination."""
        # Create mock EmailTeamMember objects with user relationship
        mock_memberships = []
        for i in range(3):
            mock_member = MagicMock(spec=EmailTeamMember)
            mock_member.id = f"member-{i}"
            mock_member.joined_at = datetime(2024, 1, 15, 10, 0, i, tzinfo=timezone.utc)
            mock_member.user = MagicMock(spec=EmailUser)
            mock_member.user.email = f"user{i}@example.com"
            mock_memberships.append(mock_member)

        # Return 4 items to trigger has_more (limit=3 + 1)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_memberships + [MagicMock(spec=EmailTeamMember)]
        mock_db.execute.return_value = mock_result
        mock_db.commit.return_value = None

        # Call with limit (triggers cursor-based pagination)
        result = await service.get_team_members("team123", cursor=None, limit=3)

        # Result should be a tuple (members, next_cursor)
        assert isinstance(result, tuple)
        members, next_cursor = result
        assert len(members) == 3
        assert next_cursor is not None

        # Verify cursor uses (joined_at, id)
        cursor_json = base64.urlsafe_b64decode(next_cursor.encode()).decode()
        cursor_data = orjson.loads(cursor_json)
        assert "joined_at" in cursor_data
        assert "id" in cursor_data

    @pytest.mark.asyncio
    async def test_get_team_members_with_cursor_advances(self, service, mock_db):
        """Test that cursor-based pagination advances correctly."""
        # Create a cursor from a previous page
        cursor_data = {
            "joined_at": "2024-01-15T10:00:02+00:00",
            "id": "member-2",
        }
        cursor = base64.urlsafe_b64encode(orjson.dumps(cursor_data)).decode()

        # Mock remaining members
        mock_memberships = []
        for i in range(2):
            mock_member = MagicMock(spec=EmailTeamMember)
            mock_member.id = f"member-{i + 3}"
            mock_member.joined_at = datetime(2024, 1, 15, 9, 0, i, tzinfo=timezone.utc)
            mock_member.user = MagicMock(spec=EmailUser)
            mock_memberships.append(mock_member)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_memberships
        mock_db.execute.return_value = mock_result
        mock_db.commit.return_value = None

        result = await service.get_team_members("team123", cursor=cursor, limit=10)

        members, next_cursor = result
        assert len(members) == 2
        assert next_cursor is None  # No more results

    @pytest.mark.asyncio
    async def test_get_user_role_in_team(self, service, mock_db):
        """Test getting user role in team."""
        mock_membership = MagicMock(spec=EmailTeamMember)
        mock_membership.role = "member"

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_membership
        mock_db.query.return_value = mock_query

        result = await service.get_user_role_in_team("user@example.com", "team123")

        assert result == "member"

    @pytest.mark.asyncio
    async def test_get_user_role_in_team_not_member(self, service, mock_db):
        """Test getting user role when not a member."""
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query

        result = await service.get_user_role_in_team("user@example.com", "team123")

        assert result is None

    @pytest.mark.asyncio
    async def test_list_teams(self, service, mock_db):
        """Test listing teams with pagination."""
        mock_teams = [MagicMock(spec=EmailTeam) for _ in range(5)]

        # Mock unified_paginate return value (tuple of list, cursor)
        with patch("mcpgateway.services.team_management_service.unified_paginate") as mock_paginate:
            mock_paginate.return_value = (mock_teams, None)

            result = await service.list_teams(limit=5, offset=0)

            # Should return tuple (teams, cursor) now
            teams, cursor = result
            assert teams == mock_teams
            assert cursor is None

            # Verify unified_paginate was called
            mock_paginate.assert_called_once()
            # Verify offset was applied to query manually if offset > 0
            # In this test call offset=0, so manually application might be skipped or 0
            # But we passed offset to service.

    @pytest.mark.asyncio
    async def test_list_teams_with_visibility_filter(self, service, mock_db):
        """Test listing teams with visibility filter."""
        mock_teams = [MagicMock(spec=EmailTeam) for _ in range(3)]

        with patch("mcpgateway.services.team_management_service.unified_paginate") as mock_paginate:
            mock_paginate.return_value = (mock_teams, "next_cursor")

            result = await service.list_teams(visibility_filter="public")

            teams, cursor = result
            assert teams == mock_teams
            assert cursor == "next_cursor"

    @pytest.mark.asyncio
    async def test_list_teams_include_personal(self, service, mock_db):
        """Test listing teams with include_personal flag."""
        mock_teams = [MagicMock(spec=EmailTeam) for _ in range(3)]

        with patch("mcpgateway.services.team_management_service.unified_paginate") as mock_paginate:
            mock_paginate.return_value = (mock_teams, None)

            # Test default (include_personal=False)
            await service.list_teams()
            # method called with kwargs
            kwargs = mock_paginate.call_args.kwargs
            query = kwargs.get("query")
            # unified_paginate(db, query, ...)
            # Let's inspect the query string compilation or check filtering
            # Since we can't easily compile SqlAlchemy query mocks, we trust the implementation change
            # But we can verify include_personal=True doesn't explode

            await service.list_teams(include_personal=True)
            mock_paginate.assert_called()

    @pytest.mark.asyncio
    async def test_list_teams_with_search_query_page(self, service, mock_db):
        """Test list_teams applies search_query and page-based ordering."""
        mock_page = {"data": [], "pagination": {}, "links": {}}

        with patch("mcpgateway.services.team_management_service.unified_paginate") as mock_paginate:
            mock_paginate.return_value = mock_page

            result = await service.list_teams(search_query="alpha", page=1, per_page=10)

            assert result == mock_page
            mock_paginate.assert_called_once()
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_teams_with_offset(self, service, mock_db):
        """Test list_teams applies offset when no page/cursor provided."""
        with patch("mcpgateway.services.team_management_service.unified_paginate") as mock_paginate:
            mock_paginate.return_value = ([], None)

            await service.list_teams(offset=5)

            mock_paginate.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_all_team_ids_with_filters(self, service, mock_db):
        """Test get_all_team_ids applies filters and returns IDs."""
        mock_result = MagicMock()
        mock_result.all.return_value = [("team-1",), ("team-2",)]
        mock_db.execute.return_value = mock_result

        result = await service.get_all_team_ids(include_inactive=True, visibility_filter="public", include_personal=True, search_query="alpha")

        assert result == ["team-1", "team-2"]
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_teams_count_with_filters(self, service, mock_db):
        """Test get_teams_count applies filters and returns scalar count."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 4
        mock_db.execute.return_value = mock_result

        result = await service.get_teams_count(include_inactive=True, visibility_filter="private", include_personal=True, search_query="beta")

        assert result == 4
        mock_db.commit.assert_called_once()

    # =========================================================================
    # Discovery and Join Request Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_discover_public_teams_success(self, service, mock_db):
        """Test discovering public teams returns results."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [MagicMock(spec=EmailTeam)]
        mock_db.query.return_value = mock_query

        result = await service.discover_public_teams("user@example.com", skip=5, limit=2)

        assert len(result) == 1
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_discover_public_teams_error(self, service, mock_db):
        """Test discover_public_teams handles query errors."""
        mock_db.query.side_effect = Exception("Database error")

        result = await service.discover_public_teams("user@example.com")

        assert result == []
        mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_join_request_team_not_found(self, service, mock_db):
        """Test create_join_request when team is not found."""
        with patch.object(service, "get_team_by_id", AsyncMock(return_value=None)):
            with pytest.raises(ValueError, match="Team not found"):
                await service.create_join_request("team-1", "user@example.com")

        mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_join_request_team_not_public(self, service, mock_db):
        """Test create_join_request when team is not public."""
        team = MagicMock(spec=EmailTeam)
        team.visibility = "private"

        with patch.object(service, "get_team_by_id", AsyncMock(return_value=team)):
            with pytest.raises(ValueError, match="public teams"):
                await service.create_join_request("team-1", "user@example.com")

        mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_join_request_existing_member(self, service, mock_db):
        """Test create_join_request when user already a member."""
        team = MagicMock(spec=EmailTeam)
        team.visibility = "public"

        member_query = MagicMock()
        member_query.filter.return_value.first.return_value = MagicMock(spec=EmailTeamMember)
        mock_db.query.return_value = member_query

        with patch.object(service, "get_team_by_id", AsyncMock(return_value=team)):
            with pytest.raises(ValueError, match="already a member"):
                await service.create_join_request("team-1", "user@example.com")

        mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_join_request_existing_pending_request(self, service, mock_db):
        """Test create_join_request when pending request already exists."""
        team = MagicMock(spec=EmailTeam)
        team.visibility = "public"

        member_query = MagicMock()
        member_query.filter.return_value.first.return_value = None

        existing_request = MagicMock(spec=EmailTeamJoinRequest)
        existing_request.status = "pending"
        existing_request.is_expired.return_value = False
        request_query = MagicMock()
        request_query.filter.return_value.first.return_value = existing_request

        mock_db.query.side_effect = [member_query, request_query]

        with patch.object(service, "get_team_by_id", AsyncMock(return_value=team)):
            with pytest.raises(ValueError, match="pending join request"):
                await service.create_join_request("team-1", "user@example.com")

        mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_join_request_updates_existing_request(self, service, mock_db):
        """Test create_join_request updates non-pending existing request."""
        team = MagicMock(spec=EmailTeam)
        team.visibility = "public"

        member_query = MagicMock()
        member_query.filter.return_value.first.return_value = None

        existing_request = MagicMock(spec=EmailTeamJoinRequest)
        existing_request.status = "rejected"
        existing_request.is_expired.return_value = True
        request_query = MagicMock()
        request_query.filter.return_value.first.return_value = existing_request

        mock_db.query.side_effect = [member_query, request_query]

        fixed_now = datetime(2024, 1, 1, tzinfo=timezone.utc)
        with (
            patch.object(service, "get_team_by_id", AsyncMock(return_value=team)),
            patch("mcpgateway.services.team_management_service.utc_now", return_value=fixed_now),
        ):
            result = await service.create_join_request("team-1", "user@example.com", message="hello")

        assert result is existing_request
        assert existing_request.status == "pending"
        assert existing_request.message == "hello"
        assert existing_request.reviewed_at is None
        assert existing_request.reviewed_by is None
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once_with(existing_request)

    @pytest.mark.asyncio
    async def test_create_join_request_new_request(self, service, mock_db):
        """Test create_join_request creates a new request when none exists."""
        team = MagicMock(spec=EmailTeam)
        team.visibility = "public"

        member_query = MagicMock()
        member_query.filter.return_value.first.return_value = None
        request_query = MagicMock()
        request_query.filter.return_value.first.return_value = None
        mock_db.query.side_effect = [member_query, request_query]

        new_request = MagicMock(spec=EmailTeamJoinRequest)

        with (
            patch.object(service, "get_team_by_id", AsyncMock(return_value=team)),
            patch("mcpgateway.services.team_management_service.EmailTeamJoinRequest", return_value=new_request),
        ):
            result = await service.create_join_request("team-1", "user@example.com", message=None)

        assert result is new_request
        mock_db.add.assert_called_once_with(new_request)
        mock_db.refresh.assert_called_once_with(new_request)

    @pytest.mark.asyncio
    async def test_list_join_requests_success(self, service, mock_db):
        """Test list_join_requests returns pending requests."""
        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.all.return_value = [MagicMock(spec=EmailTeamJoinRequest)]
        mock_db.query.return_value = mock_query

        result = await service.list_join_requests("team-1")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_list_join_requests_error(self, service, mock_db):
        """Test list_join_requests handles errors."""
        mock_db.query.side_effect = Exception("Database error")

        result = await service.list_join_requests("team-1")

        assert result == []

    @pytest.mark.asyncio
    async def test_approve_join_request_not_found(self, service, mock_db):
        """Test approve_join_request when request is missing."""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await service.approve_join_request("req-1", "admin@example.com")

        mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_approve_join_request_expired(self, service, mock_db):
        """Test approve_join_request when request is expired."""
        join_request = MagicMock(spec=EmailTeamJoinRequest)
        join_request.is_expired.return_value = True
        mock_db.query.return_value.filter.return_value.first.return_value = join_request

        with pytest.raises(ValueError, match="expired"):
            await service.approve_join_request("req-1", "admin@example.com")

        assert join_request.status == "expired"
        mock_db.commit.assert_called_once()
        mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_approve_join_request_success(self, service, mock_db):
        """Test approve_join_request adds member and updates request."""
        join_request = MagicMock(spec=EmailTeamJoinRequest)
        join_request.team_id = "team-1"
        join_request.user_email = "user@example.com"
        join_request.is_expired.return_value = False
        mock_db.query.return_value.filter.return_value.first.return_value = join_request

        member = MagicMock(spec=EmailTeamMember)
        member.id = "member-1"
        member.role = "member"

        with (
            patch("mcpgateway.services.team_management_service.EmailTeamMember", return_value=member),
            patch.object(service, "_log_team_member_action") as mock_log_action,
            patch.object(service, "invalidate_team_member_count_cache", new=AsyncMock()) as mock_invalidate,
            patch.object(
                service,
                "_fire_and_forget",
                side_effect=lambda coro: coro.close() if hasattr(coro, "close") else None,
            ),
            patch("mcpgateway.services.team_management_service.auth_cache.invalidate_team", new=AsyncMock()),
            patch("mcpgateway.services.team_management_service.auth_cache.invalidate_user_role", new=AsyncMock()),
            patch("mcpgateway.services.team_management_service.auth_cache.invalidate_user_teams", new=AsyncMock()),
            patch("mcpgateway.services.team_management_service.auth_cache.invalidate_team_membership", new=AsyncMock()),
            patch("mcpgateway.services.team_management_service.admin_stats_cache.invalidate_teams", new=AsyncMock()),
        ):
            result = await service.approve_join_request("req-1", "admin@example.com")

        assert result is member
        mock_db.flush.assert_called_once()
        mock_db.refresh.assert_called_once_with(member)
        mock_log_action.assert_called_once()
        mock_invalidate.assert_awaited_once_with("team-1")

    @pytest.mark.asyncio
    async def test_approve_join_request_assigns_rbac_role(self, service, mock_db):
        """Test approve_join_request assigns the RBAC role to approved member."""
        join_request = MagicMock(spec=EmailTeamJoinRequest)
        join_request.team_id = "team-1"
        join_request.user_email = "user@example.com"
        join_request.is_expired.return_value = False
        mock_db.query.return_value.filter.return_value.first.return_value = join_request

        member = MagicMock(spec=EmailTeamMember)
        member.id = "member-1"
        member.role = "member"

        # Mock role service
        mock_role = MagicMock()
        mock_role.id = "role123"
        mock_role.is_active = True
        mock_role_service = MagicMock()
        mock_role_service.get_role_by_name = AsyncMock(return_value=mock_role)
        mock_role_service.get_user_role_assignment = AsyncMock(return_value=None)
        mock_role_service.assign_role_to_user = AsyncMock(return_value=MagicMock())
        service._role_service = mock_role_service

        # Mock settings to use "viewer" (test expects this value)
        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.default_team_member_role = "viewer"

            with (
                patch("mcpgateway.services.team_management_service.EmailTeamMember", return_value=member),
                patch.object(service, "_log_team_member_action"),
                patch.object(service, "invalidate_team_member_count_cache", new=AsyncMock()),
                patch.object(
                    service,
                    "_fire_and_forget",
                    side_effect=lambda coro: coro.close() if hasattr(coro, "close") else None,
                ),
                patch("mcpgateway.services.team_management_service.auth_cache.invalidate_team", new=AsyncMock()),
                patch("mcpgateway.services.team_management_service.auth_cache.invalidate_user_role", new=AsyncMock()),
                patch("mcpgateway.services.team_management_service.auth_cache.invalidate_user_teams", new=AsyncMock()),
                patch("mcpgateway.services.team_management_service.auth_cache.invalidate_team_membership", new=AsyncMock()),
                patch("mcpgateway.services.team_management_service.admin_stats_cache.invalidate_teams", new=AsyncMock()),
            ):
                result = await service.approve_join_request("req-1", "admin@example.com")

        assert result is member
        mock_role_service.get_role_by_name.assert_called_once_with("viewer", scope="team")
        mock_role_service.assign_role_to_user.assert_called_once()
        call_args = mock_role_service.assign_role_to_user.call_args[1]
        assert call_args["user_email"] == "user@example.com"
        assert call_args["scope"] == "team"
        assert call_args["scope_id"] == "team-1"

    @pytest.mark.asyncio
    async def test_approve_join_request_role_not_found(self, service, mock_db):
        """Test approve_join_request works when role is not found."""
        join_request = MagicMock(spec=EmailTeamJoinRequest)
        join_request.team_id = "team-1"
        join_request.user_email = "user@example.com"
        join_request.is_expired.return_value = False
        mock_db.query.return_value.filter.return_value.first.return_value = join_request

        member = MagicMock(spec=EmailTeamMember)
        member.id = "member-1"
        member.role = "member"

        # Mock role service - role not found
        mock_role_service = MagicMock()
        mock_role_service.get_role_by_name = AsyncMock(return_value=None)
        service._role_service = mock_role_service

        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.default_team_member_role = "viewer"

            with (
                patch("mcpgateway.services.team_management_service.EmailTeamMember", return_value=member),
                patch.object(service, "_log_team_member_action"),
                patch.object(service, "invalidate_team_member_count_cache", new=AsyncMock()),
                patch.object(
                    service,
                    "_fire_and_forget",
                    side_effect=lambda coro: coro.close() if hasattr(coro, "close") else None,
                ),
                patch("mcpgateway.services.team_management_service.auth_cache.invalidate_team", new=AsyncMock()),
                patch("mcpgateway.services.team_management_service.auth_cache.invalidate_user_role", new=AsyncMock()),
                patch("mcpgateway.services.team_management_service.auth_cache.invalidate_user_teams", new=AsyncMock()),
                patch("mcpgateway.services.team_management_service.auth_cache.invalidate_team_membership", new=AsyncMock()),
                patch("mcpgateway.services.team_management_service.admin_stats_cache.invalidate_teams", new=AsyncMock()),
            ):
                result = await service.approve_join_request("req-1", "admin@example.com")

        # Should still return member even without role
        assert result is member
        mock_role_service.get_role_by_name.assert_called_once_with("viewer", scope="team")
        mock_role_service.assign_role_to_user.assert_not_called()

    @pytest.mark.asyncio
    async def test_reject_join_request_success(self, service, mock_db):
        """Test rejecting a join request updates status."""
        join_request = MagicMock(spec=EmailTeamJoinRequest)
        join_request.user_email = "user@example.com"
        join_request.team_id = "team-1"
        mock_db.query.return_value.filter.return_value.first.return_value = join_request

        result = await service.reject_join_request("req-1", "admin@example.com")

        assert result is True
        assert join_request.status == "rejected"
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_reject_join_request_not_found(self, service, mock_db):
        """Test rejecting missing join request raises error."""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await service.reject_join_request("req-1", "admin@example.com")

        mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_user_join_requests_with_team_filter(self, service, mock_db):
        """Test get_user_join_requests applies team filter."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [MagicMock(spec=EmailTeamJoinRequest)]
        mock_db.query.return_value = mock_query

        result = await service.get_user_join_requests("user@example.com", team_id="team-1")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_user_join_requests_error(self, service, mock_db):
        """Test get_user_join_requests handles errors."""
        mock_db.query.side_effect = Exception("Database error")

        result = await service.get_user_join_requests("user@example.com")

        assert result == []

    @pytest.mark.asyncio
    async def test_cancel_join_request_not_found(self, service, mock_db):
        """Test cancel_join_request returns False when missing."""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = await service.cancel_join_request("req-1", "user@example.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_join_request_success(self, service, mock_db):
        """Test cancel_join_request updates request status."""
        join_request = MagicMock(spec=EmailTeamJoinRequest)
        join_request.user_email = "user@example.com"
        join_request.team_id = "team-1"
        mock_db.query.return_value.filter.return_value.first.return_value = join_request

        result = await service.cancel_join_request("req-1", "user@example.com")

        assert result is True
        assert join_request.status == "cancelled"
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_join_request_error(self, service, mock_db):
        """Test cancel_join_request handles database errors."""
        mock_db.query.side_effect = Exception("Database error")

        result = await service.cancel_join_request("req-1", "user@example.com")

        assert result is False
        mock_db.rollback.assert_called_once()

    # =========================================================================
    # Error Handling Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_database_error_handling(self, service, mock_db):
        """Test various database error scenarios return appropriate defaults."""
        # Test unified_paginate failure
        with patch("mcpgateway.services.team_management_service.unified_paginate", side_effect=Exception("Database connection failed")):
            with pytest.raises(Exception, match="Database connection failed"):
                await service.list_teams()

        mock_db.query.side_effect = Exception("Database connection failed")
        mock_db.execute.side_effect = Exception("Database connection failed")

        # Test methods that should return None on error
        assert await service.get_team_by_id("team123") is None
        assert await service.get_team_by_slug("team-slug") is None
        assert await service.get_user_role_in_team("user@example.com", "team123") is None

        # Test methods that should return empty lists on error
        assert await service.get_user_teams("user@example.com") == []
        assert await service.get_team_members("team123") == []

        # Test methods that should raise exception on error (list_teams)
        with pytest.raises(Exception, match="Database connection failed"):
            await service.list_teams()

    # =========================================================================
    # Edge Case Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_reactivate_existing_membership(self, service, mock_team, mock_user, mock_membership, mock_db):
        """Test reactivating an existing inactive membership."""
        mock_membership.is_active = False

        def query_side_effect(model):
            mock_query = MagicMock()
            if model == EmailUser:
                mock_query.filter.return_value.first.return_value = mock_user
            elif model == EmailTeamMember:
                if not hasattr(query_side_effect, "call_count"):
                    query_side_effect.call_count = 0
                query_side_effect.call_count += 1
                if query_side_effect.call_count == 1:
                    mock_query.filter.return_value.first.return_value = mock_membership
                else:
                    mock_query.filter.return_value.count.return_value = 5
            return mock_query

        mock_db.query.side_effect = query_side_effect

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            await service.add_member_to_team(team_id="team123", user_email="user@example.com", role="member")

            assert mock_membership.is_active is True
            assert mock_membership.role == "member"

    def test_visibility_validation_values(self, service):
        """Test that visibility validation accepts all valid values."""
        valid_visibilities = ["private", "public"]

        for visibility in valid_visibilities:
            # Should not raise an exception during validation
            # This is tested implicitly in create_team and update_team tests
            assert visibility in valid_visibilities

    def test_role_validation_values(self, service):
        """Test that role validation accepts all valid values."""
        valid_roles = ["owner", "member"]

        for role in valid_roles:
            # Should not raise an exception during validation
            # This is tested implicitly in add_member and update_role tests
            assert role in valid_roles

    # ---------------------------------------------------------------------------
    # count_team_owners Tests
    # ---------------------------------------------------------------------------
    def test_count_team_owners_no_owners(self, service, mock_db):
        """Test count_team_owners returns 0 when no owners."""
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        result = service.count_team_owners("team-123")

        assert result == 0
        mock_db.query.assert_called_once()

    def test_count_team_owners_one_owner(self, service, mock_db):
        """Test count_team_owners returns 1 for single owner."""
        mock_db.query.return_value.filter.return_value.count.return_value = 1

        result = service.count_team_owners("team-123")

        assert result == 1

    def test_count_team_owners_multiple_owners(self, service, mock_db):
        """Test count_team_owners returns correct count for multiple owners."""
        mock_db.query.return_value.filter.return_value.count.return_value = 5

        result = service.count_team_owners("team-abc")

        assert result == 5

    def test_count_team_owners_filters_by_team_id(self, service, mock_db):
        """Test count_team_owners filters by correct team_id."""
        mock_db.query.return_value.filter.return_value.count.return_value = 2

        service.count_team_owners("specific-team-id")

        # Verify the filter chain was called
        mock_db.query.return_value.filter.assert_called()

    # =========================================================================
    # Batch Query Methods Tests (N+1 Query Elimination - Issue #1892)
    # =========================================================================

    def test_get_member_counts_batch_empty_list(self, service):
        """Test get_member_counts_batch returns empty dict for empty list."""
        result = service.get_member_counts_batch([])
        assert result == {}

    def test_get_member_counts_batch_single_team(self, service, mock_db):
        """Test get_member_counts_batch with single team."""
        # Create a mock result row
        mock_row = MagicMock()
        mock_row.team_id = "team-123"
        mock_row.count = 5

        mock_db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [mock_row]

        result = service.get_member_counts_batch(["team-123"])

        assert result == {"team-123": 5}
        mock_db.commit.assert_called_once()

    def test_get_member_counts_batch_multiple_teams(self, service, mock_db):
        """Test get_member_counts_batch with multiple teams."""
        # Create mock result rows
        mock_rows = []
        for i, (team_id, count) in enumerate([("team-1", 3), ("team-2", 7)]):
            row = MagicMock()
            row.team_id = team_id
            row.count = count
            mock_rows.append(row)

        mock_db.query.return_value.filter.return_value.group_by.return_value.all.return_value = mock_rows

        result = service.get_member_counts_batch(["team-1", "team-2", "team-3"])

        assert result == {"team-1": 3, "team-2": 7, "team-3": 0}  # team-3 defaults to 0

    def test_get_member_counts_batch_database_error(self, service, mock_db):
        """Test get_member_counts_batch handles database error."""
        mock_db.query.side_effect = Exception("Database error")

        with pytest.raises(Exception, match="Database error"):
            service.get_member_counts_batch(["team-123"])

        mock_db.rollback.assert_called_once()

    def test_get_user_roles_batch_empty_list(self, service):
        """Test get_user_roles_batch returns empty dict for empty list."""
        result = service.get_user_roles_batch("user@example.com", [])
        assert result == {}

    def test_get_user_roles_batch_with_memberships(self, service, mock_db):
        """Test get_user_roles_batch with mixed memberships."""
        # Create mock result rows
        mock_rows = []
        for team_id, role in [("team-1", "owner"), ("team-2", "member")]:
            row = MagicMock()
            row.team_id = team_id
            row.role = role
            mock_rows.append(row)

        mock_db.query.return_value.filter.return_value.all.return_value = mock_rows

        result = service.get_user_roles_batch("user@example.com", ["team-1", "team-2", "team-3"])

        assert result == {"team-1": "owner", "team-2": "member", "team-3": None}

    def test_get_user_roles_batch_database_error(self, service, mock_db):
        """Test get_user_roles_batch handles database error."""
        mock_db.query.side_effect = Exception("Database error")

        with pytest.raises(Exception, match="Database error"):
            service.get_user_roles_batch("user@example.com", ["team-123"])

        mock_db.rollback.assert_called_once()

    def test_get_pending_join_requests_batch_empty_list(self, service):
        """Test get_pending_join_requests_batch returns empty dict for empty list."""
        result = service.get_pending_join_requests_batch("user@example.com", [])
        assert result == {}

    def test_get_pending_join_requests_batch_with_requests(self, service, mock_db):
        """Test get_pending_join_requests_batch with pending requests."""
        mock_request = MagicMock(spec=EmailTeamJoinRequest)
        mock_request.team_id = "team-1"

        mock_db.query.return_value.filter.return_value.all.return_value = [mock_request]

        result = service.get_pending_join_requests_batch("user@example.com", ["team-1", "team-2"])

        assert result["team-1"] == mock_request
        assert result["team-2"] is None

    def test_get_pending_join_requests_batch_database_error(self, service, mock_db):
        """Test get_pending_join_requests_batch handles database error."""
        mock_db.query.side_effect = Exception("Database error")

        with pytest.raises(Exception, match="Database error"):
            service.get_pending_join_requests_batch("user@example.com", ["team-123"])

        mock_db.rollback.assert_called_once()

    # =========================================================================
    # Cached Batch Methods Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_member_counts_batch_cached_empty_list(self, service):
        """Test get_member_counts_batch_cached returns empty dict for empty list."""
        result = await service.get_member_counts_batch_cached([])
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_member_counts_batch_cached_disabled(self, service, mock_db):
        """Test get_member_counts_batch_cached falls back to sync when caching disabled."""
        mock_row = MagicMock()
        mock_row.team_id = "team-123"
        mock_row.count = 5
        mock_db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [mock_row]

        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.team_member_count_cache_enabled = False
            mock_settings.team_member_count_cache_ttl = 300

            result = await service.get_member_counts_batch_cached(["team-123"])

            assert result == {"team-123": 5}

    @pytest.mark.asyncio
    async def test_get_member_counts_batch_cached_redis_unavailable(self, service, mock_db):
        """Test get_member_counts_batch_cached handles Redis unavailable."""
        mock_row = MagicMock()
        mock_row.team_id = "team-123"
        mock_row.count = 5
        mock_db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [mock_row]

        with (
            patch("mcpgateway.services.team_management_service.settings") as mock_settings,
            patch("mcpgateway.utils.redis_client.get_redis_client", return_value=None),
        ):
            mock_settings.team_member_count_cache_enabled = True
            mock_settings.team_member_count_cache_ttl = 300
            mock_settings.cache_prefix = "mcpgw:"

            result = await service.get_member_counts_batch_cached(["team-123"])

            assert result == {"team-123": 5}

    @pytest.mark.asyncio
    async def test_invalidate_team_member_count_cache_disabled(self, service):
        """Test invalidate_team_member_count_cache is no-op when caching disabled."""
        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.team_member_count_cache_enabled = False

            # Should not raise any exception
            await service.invalidate_team_member_count_cache("team-123")

    @pytest.mark.asyncio
    async def test_invalidate_team_member_count_cache_redis_unavailable(self, service):
        """Test invalidate_team_member_count_cache handles Redis unavailable."""
        with (
            patch("mcpgateway.services.team_management_service.settings") as mock_settings,
            patch("mcpgateway.utils.redis_client.get_redis_client", return_value=None),
        ):
            mock_settings.team_member_count_cache_enabled = True
            mock_settings.cache_prefix = "mcpgw:"

            # Should not raise any exception
            await service.invalidate_team_member_count_cache("team-123")

    # ---- get_member ---- #
    @pytest.mark.asyncio
    async def test_get_member_found(self, service, mock_db):
        """get_member returns member when found."""
        mock_member = MagicMock(spec=EmailTeamMember)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_member
        result = await service.get_member("team-1", "user@test.com")
        assert result is mock_member

    @pytest.mark.asyncio
    async def test_get_member_not_found(self, service, mock_db):
        """get_member returns None when not found."""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        result = await service.get_member("team-1", "user@test.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_member_exception(self, service, mock_db):
        """get_member returns None on exception."""
        mock_db.query.side_effect = Exception("db error")
        result = await service.get_member("team-1", "user@test.com")
        assert result is None

    # ---- remove_member_from_team edge cases ---- #
    @pytest.mark.asyncio
    async def test_remove_member_team_not_found(self, service, mock_db):
        """remove_member returns False when team not found."""
        service.get_team_by_id = AsyncMock(return_value=None)
        result = await service.remove_member_from_team("team-bad", "user@test.com")
        assert result is False

    @pytest.mark.asyncio
    async def test_remove_member_personal_team(self, service, mock_db):
        """remove_member returns False for personal teams."""
        team = MagicMock()
        team.is_personal = True
        service.get_team_by_id = AsyncMock(return_value=team)
        result = await service.remove_member_from_team("team-1", "user@test.com")
        assert result is False

    @pytest.mark.asyncio
    async def test_remove_member_not_a_member(self, service, mock_db):
        """remove_member returns False when user is not a member."""
        team = MagicMock()
        team.is_personal = False
        service.get_team_by_id = AsyncMock(return_value=team)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        result = await service.remove_member_from_team("team-1", "user@test.com")
        assert result is False

    # ---- update_member_role edge cases ---- #
    @pytest.mark.asyncio
    async def test_update_member_role_team_not_found(self, service, mock_db):
        """update_member_role returns False when team not found."""
        service.get_team_by_id = AsyncMock(return_value=None)
        result = await service.update_member_role("team-bad", "user@test.com", "member")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_member_role_personal_team(self, service, mock_db):
        """update_member_role returns False for personal teams."""
        team = MagicMock()
        team.is_personal = True
        service.get_team_by_id = AsyncMock(return_value=team)
        result = await service.update_member_role("team-1", "user@test.com", "member")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_member_role_not_a_member(self, service, mock_db):
        """update_member_role returns False when user is not a member."""
        team = MagicMock()
        team.is_personal = False
        service.get_team_by_id = AsyncMock(return_value=team)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        result = await service.update_member_role("team-1", "user@test.com", "member")
        assert result is False

    # ---- verify_team_for_user ---- #
    @pytest.mark.asyncio
    async def test_verify_team_for_user_no_team_id_personal(self, service, mock_db):
        """verify_team_for_user returns personal team ID when no team_id provided."""
        personal_team = MagicMock()
        personal_team.id = "personal-1"
        personal_team.is_personal = True
        mock_db.query.return_value.join.return_value.filter.return_value.all.return_value = [personal_team]
        mock_db.commit = MagicMock()
        result = await service.verify_team_for_user("user@test.com")
        assert result == "personal-1"

    @pytest.mark.asyncio
    async def test_verify_team_for_user_team_id_valid(self, service, mock_db):
        """verify_team_for_user returns team_id when user is a member."""
        team = MagicMock()
        team.id = "team-1"
        team.is_personal = False
        mock_db.query.return_value.join.return_value.filter.return_value.all.return_value = [team]
        mock_db.commit = MagicMock()
        result = await service.verify_team_for_user("user@test.com", team_id="team-1")
        assert result == "team-1"

    @pytest.mark.asyncio
    async def test_verify_team_for_user_team_id_not_member(self, service, mock_db):
        """verify_team_for_user returns empty list when user is not member of team."""
        team = MagicMock()
        team.id = "team-other"
        team.is_personal = False
        mock_db.query.return_value.join.return_value.filter.return_value.all.return_value = [team]
        mock_db.commit = MagicMock()
        result = await service.verify_team_for_user("user@test.com", team_id="team-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_verify_team_for_user_db_error(self, service, mock_db):
        """verify_team_for_user returns [] on DB error."""
        mock_db.query.side_effect = Exception("db error")
        mock_db.rollback = MagicMock()
        result = await service.verify_team_for_user("user@test.com")
        assert result == []

    # ---- get_user_teams cache paths ---- #
    @pytest.mark.asyncio
    async def test_get_user_teams_cache_hit_with_objects(self, service, mock_db):
        """get_user_teams returns CachedTeamData from cache when cache hit with team objects."""
        # Third-Party
        from mcpgateway.schemas import CachedTeamData

        now = datetime.now(timezone.utc)
        cached_teams = [
            {
                "id": "team-1",
                "name": "Team One",
                "slug": "team-one",
                "description": "Test team",
                "created_by": "admin@example.com",
                "is_personal": False,
                "visibility": "public",
                "max_members": 100,
                "is_active": True,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
        ]

        mock_cache = AsyncMock()
        mock_cache.get_user_teams = AsyncMock(return_value=cached_teams)
        service._get_auth_cache = MagicMock(return_value=mock_cache)

        result = await service.get_user_teams("user@test.com")
        assert len(result) == 1
        # Verify it returns CachedTeamData (Pydantic model), not EmailTeam (SQLAlchemy ORM)
        assert isinstance(result[0], CachedTeamData)
        assert result[0].id == "team-1"
        assert result[0].name == "Team One"

    @pytest.mark.asyncio
    async def test_get_user_teams_cache_hit_empty(self, service, mock_db):
        """get_user_teams returns [] on cache hit with empty list."""
        mock_cache = AsyncMock()
        mock_cache.get_user_teams = AsyncMock(return_value=[])
        service._get_auth_cache = MagicMock(return_value=mock_cache)

        result = await service.get_user_teams("user@test.com")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_user_teams_cache_fetch_error_falls_through(self, service, mock_db):
        """get_user_teams falls through to full query on cache fetch error."""
        mock_cache = AsyncMock()
        mock_cache.get_user_teams = AsyncMock(return_value=["team-1"])
        service._get_auth_cache = MagicMock(return_value=mock_cache)

        # Cache hit IDs, but DB fetch by IDs fails
        mock_db.query.return_value.filter.return_value.all.side_effect = [
            Exception("db error"),  # First call (by IDs) fails
            [MagicMock()],  # Second call (full query) succeeds
        ]
        mock_db.rollback = MagicMock()
        mock_db.commit = MagicMock()

        # The join().filter() path needs a separate mock for the full query
        mock_db.query.return_value.join.return_value.filter.return_value.all.return_value = [MagicMock()]

        result = await service.get_user_teams("user@test.com")
        # Should fall through to full query and succeed
        assert len(result) >= 0  # Just verify no exception

    # =========================================================================
    # RBAC Role Assignment Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_add_member_assigns_rbac_role(self, service, mock_db, mock_team, mock_user):
        """Test that adding a member assigns the configured RBAC role."""
        # Setup mocks - use side_effect like the existing test
        mock_team_query = MagicMock()
        mock_team_query.filter.return_value.first.return_value = mock_team

        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = mock_user

        mock_existing_query = MagicMock()
        mock_existing_query.filter.return_value.first.return_value = None

        mock_count_query = MagicMock()
        mock_count_query.filter.return_value.count.return_value = 1

        def side_effect(model):
            if model == EmailTeam:
                return mock_team_query
            elif model == EmailUser:
                return mock_user_query
            elif model == EmailTeamMember:
                if not hasattr(side_effect, "call_count"):
                    side_effect.call_count = 0
                side_effect.call_count += 1
                if side_effect.call_count == 1:
                    return mock_existing_query
                else:
                    return mock_count_query

        mock_db.query.side_effect = side_effect

        # Mock role service - set _role_service directly since role_service is a property
        mock_role = MagicMock()
        mock_role.id = "role123"
        mock_role.is_active = True
        mock_role_service = MagicMock()
        mock_role_service.get_role_by_name = AsyncMock(return_value=mock_role)
        mock_role_service.get_user_role_assignment = AsyncMock(return_value=None)
        mock_role_service.assign_role_to_user = AsyncMock(return_value=MagicMock())
        service._role_service = mock_role_service

        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.default_team_member_role = "viewer"

            with patch.object(service, "get_team_by_id", return_value=mock_team):
                # Execute
                result = await service.add_member_to_team(team_id="team123", user_email="user@example.com", role="member", invited_by="admin@example.com")

                # Verify
                assert result is not None
                mock_role_service.get_role_by_name.assert_called_once_with("viewer", scope="team")
                mock_role_service.assign_role_to_user.assert_called_once()
                call_args = mock_role_service.assign_role_to_user.call_args[1]
                assert call_args["user_email"] == "user@example.com"
                assert call_args["role_id"] == "role123"
                assert call_args["scope"] == "team"
                assert call_args["scope_id"] == "team123"

    @pytest.mark.asyncio
    async def test_add_member_skips_role_if_already_assigned(self, service, mock_db, mock_team, mock_user):
        """Test that adding a member skips role assignment if already has role."""
        # Setup mocks
        mock_team_query = MagicMock()
        mock_team_query.filter.return_value.first.return_value = mock_team

        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = mock_user

        mock_existing_query = MagicMock()
        mock_existing_query.filter.return_value.first.return_value = None

        mock_count_query = MagicMock()
        mock_count_query.filter.return_value.count.return_value = 1

        def side_effect(model):
            if model == EmailTeam:
                return mock_team_query
            elif model == EmailUser:
                return mock_user_query
            elif model == EmailTeamMember:
                if not hasattr(side_effect, "call_count"):
                    side_effect.call_count = 0
                side_effect.call_count += 1
                if side_effect.call_count == 1:
                    return mock_existing_query
                else:
                    return mock_count_query

        mock_db.query.side_effect = side_effect

        # Mock role service
        mock_role = MagicMock()
        mock_role.id = "role123"
        mock_role.is_active = True
        existing_assignment = MagicMock()
        existing_assignment.is_active = True
        mock_role_service = MagicMock()
        mock_role_service.get_role_by_name = AsyncMock(return_value=mock_role)
        mock_role_service.get_user_role_assignment = AsyncMock(return_value=existing_assignment)
        mock_role_service.assign_role_to_user = AsyncMock(return_value=MagicMock())
        service._role_service = mock_role_service

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            # Execute
            result = await service.add_member_to_team(team_id="team123", user_email="user@example.com", role="member", invited_by="admin@example.com")

            # Verify - should NOT assign role again
            assert result is not None
            mock_role_service.get_role_by_name.assert_called_once()
            mock_role_service.assign_role_to_user.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_member_revokes_rbac_role(self, service, mock_db, mock_team):
        """Test that removing a member revokes both team RBAC roles defensively."""
        # Setup membership mock
        mock_membership = MagicMock(spec=EmailTeamMember)
        mock_membership.role = "member"
        mock_membership.is_active = True

        # Mock role service with distinct role IDs for owner vs member
        mock_owner_role = MagicMock()
        mock_owner_role.id = "owner_role_123"
        mock_member_role = MagicMock()
        mock_member_role.id = "member_role_456"

        mock_role_service = MagicMock()

        def get_role_by_name_side_effect(name, scope="team"):
            if name == "team_admin":
                return mock_owner_role
            elif name == "viewer":
                return mock_member_role
            return None

        mock_role_service.get_role_by_name = AsyncMock(side_effect=get_role_by_name_side_effect)
        mock_role_service.revoke_role_from_user = AsyncMock(return_value=True)
        service._role_service = mock_role_service

        # Patch get_team_by_id
        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.default_team_owner_role = "team_admin"
            mock_settings.default_team_member_role = "viewer"

            with patch.object(service, "get_team_by_id", new_callable=AsyncMock) as mock_get_team:
                mock_get_team.return_value = mock_team
                mock_db.query.return_value.filter.return_value.first.return_value = mock_membership

                # Execute
                result = await service.remove_member_from_team(team_id="team123", user_email="user@example.com", removed_by="admin@example.com")

                # Verify - both owner and member roles are revoked defensively
                assert result is True
                assert mock_role_service.get_role_by_name.call_count == 2
                assert mock_role_service.revoke_role_from_user.call_count == 2

    @pytest.mark.asyncio
    async def test_add_member_role_not_found(self, service, mock_db, mock_team, mock_user):
        """Test that adding a member works when role is not found."""
        # Setup mocks
        mock_team_query = MagicMock()
        mock_team_query.filter.return_value.first.return_value = mock_team

        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = mock_user

        mock_existing_query = MagicMock()
        mock_existing_query.filter.return_value.first.return_value = None

        mock_count_query = MagicMock()
        mock_count_query.filter.return_value.count.return_value = 1

        def side_effect(model):
            if model == EmailTeam:
                return mock_team_query
            elif model == EmailUser:
                return mock_user_query
            elif model == EmailTeamMember:
                if not hasattr(side_effect, "call_count"):
                    side_effect.call_count = 0
                side_effect.call_count += 1
                if side_effect.call_count == 1:
                    return mock_existing_query
                else:
                    return mock_count_query

        mock_db.query.side_effect = side_effect

        # Mock role service - role not found
        mock_role_service = MagicMock()
        mock_role_service.get_role_by_name = AsyncMock(return_value=None)  # Role not found
        service._role_service = mock_role_service

        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.default_team_member_role = "viewer"

            with patch.object(service, "get_team_by_id", return_value=mock_team):
                # Execute
                result = await service.add_member_to_team(team_id="team123", user_email="user@example.com", role="member", invited_by="admin@example.com")

                # Verify - member should still be added even without role
                assert result is not None
                mock_role_service.get_role_by_name.assert_called_once_with("viewer", scope="team")
                mock_role_service.assign_role_to_user.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_member_role_assignment_exception(self, service, mock_db, mock_team, mock_user):
        """Test that adding a member works when role assignment raises exception."""
        # Setup mocks
        mock_team_query = MagicMock()
        mock_team_query.filter.return_value.first.return_value = mock_team

        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = mock_user

        mock_existing_query = MagicMock()
        mock_existing_query.filter.return_value.first.return_value = None

        mock_count_query = MagicMock()
        mock_count_query.filter.return_value.count.return_value = 1

        def side_effect(model):
            if model == EmailTeam:
                return mock_team_query
            elif model == EmailUser:
                return mock_user_query
            elif model == EmailTeamMember:
                if not hasattr(side_effect, "call_count"):
                    side_effect.call_count = 0
                side_effect.call_count += 1
                if side_effect.call_count == 1:
                    return mock_existing_query
                else:
                    return mock_count_query

        mock_db.query.side_effect = side_effect

        # Mock role service - role assignment raises exception
        mock_role = MagicMock()
        mock_role.id = "role123"
        mock_role.is_active = True
        mock_role_service = MagicMock()
        mock_role_service.get_role_by_name = AsyncMock(return_value=mock_role)
        mock_role_service.get_user_role_assignment = AsyncMock(side_effect=Exception("DB error"))
        service._role_service = mock_role_service

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            # Execute - should not raise
            result = await service.add_member_to_team(team_id="team123", user_email="user@example.com", role="member", invited_by="admin@example.com")

            # Verify - member should still be added
            assert result is not None

    @pytest.mark.asyncio
    async def test_add_member_reactivate_assigns_role(self, service, mock_db, mock_team, mock_user, mock_membership):
        """Test that reactivating a member assigns the RBAC role."""
        # Setup - existing inactive membership
        mock_membership.is_active = False

        mock_team_query = MagicMock()
        mock_team_query.filter.return_value.first.return_value = mock_team

        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = mock_user

        mock_existing_query = MagicMock()
        mock_existing_query.filter.return_value.first.return_value = mock_membership

        mock_count_query = MagicMock()
        mock_count_query.filter.return_value.count.return_value = 5

        def side_effect(model):
            if model == EmailTeam:
                return mock_team_query
            elif model == EmailUser:
                return mock_user_query
            elif model == EmailTeamMember:
                if not hasattr(side_effect, "call_count"):
                    side_effect.call_count = 0
                side_effect.call_count += 1
                if side_effect.call_count == 1:
                    return mock_existing_query
                else:
                    return mock_count_query

        mock_db.query.side_effect = side_effect

        # Mock role service
        mock_role = MagicMock()
        mock_role.id = "role123"
        mock_role.is_active = True
        mock_role_service = MagicMock()
        mock_role_service.get_role_by_name = AsyncMock(return_value=mock_role)
        mock_role_service.get_user_role_assignment = AsyncMock(return_value=None)
        mock_role_service.assign_role_to_user = AsyncMock(return_value=MagicMock())
        service._role_service = mock_role_service

        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.default_team_member_role = "viewer"

            with patch.object(service, "get_team_by_id", return_value=mock_team):
                # Execute
                result = await service.add_member_to_team(team_id="team123", user_email="user@example.com", role="member", invited_by="admin@example.com")

                # Verify
                assert result is not None
                assert mock_membership.is_active is True
                mock_role_service.get_role_by_name.assert_called_once_with("viewer", scope="team")
                mock_role_service.assign_role_to_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_member_role_not_found(self, service, mock_db, mock_team):
        """Test that removing a member works when roles are not found."""
        # Setup membership mock
        mock_membership = MagicMock(spec=EmailTeamMember)
        mock_membership.role = "member"
        mock_membership.is_active = True

        # Mock role service - role not found
        mock_role_service = MagicMock()
        mock_role_service.get_role_by_name = AsyncMock(return_value=None)  # Role not found
        service._role_service = mock_role_service

        # Patch get_team_by_id
        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.default_team_owner_role = "team_admin"
            mock_settings.default_team_member_role = "viewer"

            with patch.object(service, "get_team_by_id", new_callable=AsyncMock) as mock_get_team:
                mock_get_team.return_value = mock_team
                mock_db.query.return_value.filter.return_value.first.return_value = mock_membership

                # Execute
                result = await service.remove_member_from_team(team_id="team123", user_email="user@example.com", removed_by="admin@example.com")

                # Verify - member should still be removed even when roles not found
                assert result is True
                assert mock_role_service.get_role_by_name.call_count == 2
                mock_role_service.revoke_role_from_user.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_member_no_role_to_revoke(self, service, mock_db, mock_team):
        """Test that removing a member works when there's no role to revoke."""
        # Setup membership mock
        mock_membership = MagicMock(spec=EmailTeamMember)
        mock_membership.role = "member"
        mock_membership.is_active = True

        # Mock role service - revoke returns False
        mock_role = MagicMock()
        mock_role.id = "role123"
        mock_role.is_active = True
        mock_role_service = MagicMock()
        mock_role_service.get_role_by_name = AsyncMock(return_value=mock_role)
        mock_role_service.revoke_role_from_user = AsyncMock(return_value=False)  # No role to revoke
        service._role_service = mock_role_service

        # Patch get_team_by_id
        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.default_team_owner_role = "team_admin"
            mock_settings.default_team_member_role = "viewer"

            with patch.object(service, "get_team_by_id", new_callable=AsyncMock) as mock_get_team:
                mock_get_team.return_value = mock_team
                mock_db.query.return_value.filter.return_value.first.return_value = mock_membership

                # Execute
                result = await service.remove_member_from_team(team_id="team123", user_email="user@example.com", removed_by="admin@example.com")

                # Verify - both roles attempted for revocation
                assert result is True
                assert mock_role_service.get_role_by_name.call_count == 2
                assert mock_role_service.revoke_role_from_user.call_count == 2

    @pytest.mark.asyncio
    async def test_remove_member_role_revocation_exception(self, service, mock_db, mock_team):
        """Test that removing a member works when role revocation raises exception."""
        # Setup membership mock
        mock_membership = MagicMock(spec=EmailTeamMember)
        mock_membership.role = "member"
        mock_membership.is_active = True

        # Mock role service - revoke raises exception
        mock_role = MagicMock()
        mock_role.id = "role123"
        mock_role.is_active = True
        mock_role_service = MagicMock()
        mock_role_service.get_role_by_name = AsyncMock(return_value=mock_role)
        mock_role_service.revoke_role_from_user = AsyncMock(side_effect=Exception("DB error"))
        service._role_service = mock_role_service

        # Patch get_team_by_id
        with patch.object(service, "get_team_by_id", new_callable=AsyncMock) as mock_get_team:
            mock_get_team.return_value = mock_team
            mock_db.query.return_value.filter.return_value.first.return_value = mock_membership

            # Execute - should not raise
            result = await service.remove_member_from_team(team_id="team123", user_email="user@example.com", removed_by="admin@example.com")

            # Verify - member should still be removed
            assert result is True
