# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_personal_team_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive tests for Personal Team Service functionality.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import EmailTeam, EmailUser
from mcpgateway.services.personal_team_service import PersonalTeamService


class TestPersonalTeamService:
    """Comprehensive test suite for Personal Team Service."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = MagicMock(spec=Session)
        # Setup query chain mocking
        db.query.return_value.filter.return_value.first.return_value = None
        return db

    @pytest.fixture
    def service(self, mock_db):
        """Create personal team service instance."""
        return PersonalTeamService(mock_db)

    @pytest.fixture
    def mock_user(self):
        """Create mock user."""
        user = MagicMock(spec=EmailUser)
        user.email = "testuser@example.com"
        user.is_active = True
        user.get_display_name.return_value = "Test User"
        return user

    @pytest.fixture
    def mock_personal_team(self):
        """Create mock personal team."""
        team = MagicMock(spec=EmailTeam)
        team.id = "personal-team-123"
        team.name = "Test User's Team"
        team.slug = "personal-testuser-example-com"
        team.description = "Personal workspace for testuser@example.com"
        team.created_by = "testuser@example.com"
        team.is_personal = True
        team.visibility = "private"
        team.is_active = True
        return team

    @pytest.fixture
    def mock_regular_team(self):
        """Create mock regular (non-personal) team."""
        team = MagicMock(spec=EmailTeam)
        team.id = "regular-team-456"
        team.name = "Regular Team"
        team.slug = "regular-team"
        team.is_personal = False
        team.is_active = True
        return team

    # =========================================================================
    # Service Initialization Tests
    # =========================================================================

    def test_service_initialization(self, mock_db):
        """Test service initialization with database session."""
        service = PersonalTeamService(mock_db)
        assert service.db == mock_db
        assert service.db is not None



    # =========================================================================
    # Personal Team Creation Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_personal_team_success(self, service, mock_db, mock_user):
        """Test successful personal team creation."""
        # Setup: No existing team
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with (
            patch("mcpgateway.services.personal_team_service.EmailTeam") as MockTeam,
            patch("mcpgateway.services.personal_team_service.RoleService") as MockRoleService,
        ):
            mock_team = MagicMock()
            mock_team.id = "new-team-id"
            mock_team.name = "Test User's Team"
            MockTeam.return_value = mock_team

            # Setup RoleService mock
            mock_role_service_instance = MockRoleService.return_value
            mock_role = MagicMock()
            mock_role.id = "role-id"
            mock_role_service_instance.get_role_by_name = AsyncMock(return_value=mock_role)
            mock_role_service_instance.assign_role_to_user = AsyncMock()

            result = await service.create_personal_team(mock_user)

            # Verify team creation
            assert result == mock_team
            MockTeam.assert_called_once_with(
                name="Test User's Team",
                slug="personal-testuser-example-com",
                description="Personal workspace for testuser@example.com",
                created_by="testuser@example.com",
                is_personal=True,
                visibility="private",
                is_active=True,
            )

            # Verify team was added to database
            mock_db.add.assert_any_call(mock_team)
            assert mock_db.flush.call_count == 1

            # Verify role assignment
            mock_role_service_instance.get_role_by_name.assert_called_once()
            mock_role_service_instance.assign_role_to_user.assert_called_once_with(
                user_email="testuser@example.com",
                role_id="role-id",
                scope="team",
                scope_id="new-team-id",
                granted_by="testuser@example.com",
                expires_at=None
            )

    @pytest.mark.asyncio
    async def test_create_personal_team_already_exists(self, service, mock_db, mock_user, mock_personal_team):
        """Test personal team creation when team already exists."""
        # Setup: Existing team found
        mock_db.query.return_value.filter.return_value.first.return_value = mock_personal_team

        with pytest.raises(ValueError, match="already has a personal team"):
            await service.create_personal_team(mock_user)

        # Verify no database operations
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_personal_team_with_special_characters_in_email(self, service, mock_db):
        """Test personal team creation with special characters in email."""
        user = MagicMock(spec=EmailUser)
        user.email = "test+special.user@sub.example.com"
        user.get_display_name.return_value = "Special User"

        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("mcpgateway.services.personal_team_service.EmailTeam") as MockTeam, patch("mcpgateway.services.personal_team_service.RoleService") as MockRoleService:
            mock_team = MagicMock()
            mock_team.id = "special-team-id"
            MockTeam.return_value = mock_team

            # Setup RoleService mock
            mock_role_service_instance = MockRoleService.return_value
            mock_role = MagicMock()
            mock_role.id = "role-id"
            mock_role_service_instance.get_role_by_name = AsyncMock(return_value=mock_role)
            mock_role_service_instance.assign_role_to_user = AsyncMock()

            result = await service.create_personal_team(user)

            # Verify slug generation handles special characters
            MockTeam.assert_called_once()
            call_args = MockTeam.call_args[1]
            # The '+' character is preserved in the slug
            assert call_args["slug"] == "personal-test+special-user-sub-example-com"
            assert call_args["name"] == "Special User's Team"

    @pytest.mark.asyncio
    async def test_create_personal_team_database_error(self, service, mock_db, mock_user):
        """Test personal team creation with database error."""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.add.side_effect = Exception("Database error")

        with patch("mcpgateway.services.personal_team_service.EmailTeam"), patch("mcpgateway.services.personal_team_service.RoleService"):
            with pytest.raises(Exception, match="Database error"):
                await service.create_personal_team(mock_user)

            # Verify rollback was called
            mock_db.rollback.assert_called_once()

    # =========================================================================
    # Personal Team Retrieval Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_personal_team_found(self, service, mock_db, mock_personal_team):
        """Test successful personal team retrieval."""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_personal_team

        result = await service.get_personal_team("testuser@example.com")

        assert result == mock_personal_team
        mock_db.query.assert_called_once_with(EmailTeam)

    @pytest.mark.asyncio
    async def test_get_personal_team_not_found(self, service, mock_db):
        """Test personal team retrieval when not found."""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = await service.get_personal_team("nonexistent@example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_personal_team_database_error(self, service, mock_db):
        """Test personal team retrieval with database error."""
        mock_db.query.side_effect = Exception("Database connection failed")

        result = await service.get_personal_team("testuser@example.com")

        assert result is None  # Should return None on error



    # =========================================================================
    # Integration and Edge Case Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_personal_team_with_long_email(self, service, mock_db):
        """Test personal team creation with very long email address."""
        user = MagicMock(spec=EmailUser)
        user.email = "very.long.email.address.with.many.dots@subdomain.example.com"
        user.get_display_name.return_value = "Long Email User"

        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("mcpgateway.services.personal_team_service.EmailTeam") as MockTeam, patch("mcpgateway.services.personal_team_service.RoleService") as MockRoleService:
            mock_team = MagicMock()
            mock_team.id = "long-email-team"
            MockTeam.return_value = mock_team

            # Setup RoleService mock
            mock_role_service_instance = MockRoleService.return_value
            mock_role = MagicMock()
            mock_role.id = "role-id"
            mock_role_service_instance.get_role_by_name = AsyncMock(return_value=mock_role)
            mock_role_service_instance.assign_role_to_user = AsyncMock()

            result = await service.create_personal_team(user)

            assert result == mock_team
            call_args = MockTeam.call_args[1]
            expected_slug = "personal-very-long-email-address-with-many-dots-subdomain-example-com"
            assert call_args["slug"] == expected_slug

    @pytest.mark.asyncio
    async def test_create_personal_team_rollback_on_flush_error(self, service, mock_db, mock_user):
        """Test that rollback is called if flush fails."""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.flush.side_effect = Exception("Flush failed")

        with patch("mcpgateway.services.personal_team_service.EmailTeam"), patch("mcpgateway.services.personal_team_service.RoleService"):
            with pytest.raises(Exception, match="Flush failed"):
                await service.create_personal_team(mock_user)

            mock_db.rollback.assert_called_once()
            mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_concurrent_team_creation_handling(self, service, mock_db, mock_user):
        """Test handling of concurrent team creation attempts."""
        # Simulate race condition: first check shows no team, but creation fails due to concurrent creation
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            None,  # Initial check in create_personal_team
            MagicMock(id="existing-team"),  # After failed creation attempt
        ]

        with patch("mcpgateway.services.personal_team_service.EmailTeam"), patch("mcpgateway.services.personal_team_service.RoleService"):
            mock_db.flush.side_effect = Exception("UNIQUE constraint failed")

            with pytest.raises(Exception, match="UNIQUE constraint failed"):
                await service.create_personal_team(mock_user)

            mock_db.rollback.assert_called_once()
