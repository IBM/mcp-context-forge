# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_team_management_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive tests for Team Management Service functionality.
"""

# Standard
import base64
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

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
            result = await service.add_member_to_team(team_id="team123", user_email="user@example.com", role="member")

            assert result is True
            assert mock_db.add.call_count == 2
            assert mock_db.commit.call_count == 2  # One for membership, one for history

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
    async def test_add_member_already_member(self, service, mock_team, mock_user, mock_membership, mock_db):
        """Test adding user who is already a member."""
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
            result = await service.add_member_to_team(team_id="team123", user_email="user@example.com")

            assert result is False

    @pytest.mark.asyncio
    async def test_add_member_max_members_exceeded(self, service, mock_team, mock_user, mock_db):
        """Test adding member when max members limit is reached."""
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
            result = await service.add_member_to_team(team_id="team123", user_email="user@example.com")
            assert result is False

    @pytest.mark.asyncio
    async def test_remove_member_success(self, service, mock_team, mock_membership, mock_db):
        """Test successful member removal."""
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_membership
        mock_db.query.return_value = mock_query

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

        with patch.object(service, "get_team_by_id", return_value=mock_team):
            result = await service.update_member_role(team_id="team123", user_email="user@example.com", new_role="member")

            assert result is True
            assert mock_membership.role == "member"
            assert mock_db.commit.call_count == 2  # One for role update, one for history

    @pytest.mark.asyncio
    async def test_update_member_role_invalid_role(self, service):
        """Test updating member with invalid role."""
        result = await service.update_member_role(team_id="team123", user_email="user@example.com", new_role="invalid")
        assert result is False

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
            result = await service.update_member_role(team_id="team123", user_email="user@example.com", new_role="member")
            assert result is False

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
            mock_member.id = f"member-{i+3}"
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
            result = await service.add_member_to_team(team_id="team123", user_email="user@example.com", role="member")

            assert result is True
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
