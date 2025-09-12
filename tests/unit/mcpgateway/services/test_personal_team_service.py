# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_personal_team_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Comprehensive tests for Personal Team Service functionality.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import EmailTeam, EmailTeamMember, EmailUser, utc_now
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

    def test_service_has_required_methods(self, service):
        """Test that service has all required methods."""
        required_methods = [
            'create_personal_team',
            'get_personal_team',
            'ensure_personal_team',
            'is_personal_team',
            'delete_personal_team',
            'get_personal_team_owner',
        ]
        
        for method_name in required_methods:
            assert hasattr(service, method_name)
            assert callable(getattr(service, method_name))

    # =========================================================================
    # Personal Team Creation Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_personal_team_success(self, service, mock_db, mock_user):
        """Test successful personal team creation."""
        # Setup: No existing team
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        with patch('mcpgateway.services.personal_team_service.EmailTeam') as MockTeam, \
             patch('mcpgateway.services.personal_team_service.EmailTeamMember') as MockMember, \
             patch('mcpgateway.services.personal_team_service.utc_now') as mock_utc_now:
            
            mock_team = MagicMock()
            mock_team.id = "new-team-id"
            mock_team.name = "Test User's Team"
            MockTeam.return_value = mock_team
            mock_utc_now.return_value = "2025-01-01T00:00:00Z"
            
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
            mock_db.flush.assert_called_once()
            
            # Verify membership creation
            MockMember.assert_called_once_with(
                team_id="new-team-id",
                user_email="testuser@example.com",
                role="owner",
                joined_at=mock_utc_now.return_value,
                is_active=True
            )
            
            # Verify commit
            mock_db.commit.assert_called_once()

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
        
        with patch('mcpgateway.services.personal_team_service.EmailTeam') as MockTeam, \
             patch('mcpgateway.services.personal_team_service.EmailTeamMember'):
            
            mock_team = MagicMock()
            mock_team.id = "special-team-id"
            MockTeam.return_value = mock_team
            
            result = await service.create_personal_team(user)
            
            # Verify slug generation handles special characters
            MockTeam.assert_called_once()
            call_args = MockTeam.call_args[1]
            # The '+' character is preserved in the slug
            assert call_args['slug'] == "personal-test+special-user-sub-example-com"
            assert call_args['name'] == "Special User's Team"

    @pytest.mark.asyncio
    async def test_create_personal_team_database_error(self, service, mock_db, mock_user):
        """Test personal team creation with database error."""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.commit.side_effect = Exception("Database error")
        
        with patch('mcpgateway.services.personal_team_service.EmailTeam'), \
             patch('mcpgateway.services.personal_team_service.EmailTeamMember'):
            
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
    # Ensure Personal Team Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_ensure_personal_team_existing(self, service, mock_user, mock_personal_team):
        """Test ensure personal team when team already exists."""
        with patch.object(service, 'get_personal_team', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_personal_team
            
            result = await service.ensure_personal_team(mock_user)
            
            assert result == mock_personal_team
            mock_get.assert_called_once_with("testuser@example.com")

    @pytest.mark.asyncio
    async def test_ensure_personal_team_create_new(self, service, mock_user, mock_personal_team):
        """Test ensure personal team creates new team when none exists."""
        with patch.object(service, 'get_personal_team', new_callable=AsyncMock) as mock_get, \
             patch.object(service, 'create_personal_team', new_callable=AsyncMock) as mock_create:
            
            mock_get.return_value = None  # No existing team
            mock_create.return_value = mock_personal_team
            
            result = await service.ensure_personal_team(mock_user)
            
            assert result == mock_personal_team
            mock_get.assert_called_once_with("testuser@example.com")
            mock_create.assert_called_once_with(mock_user)

    @pytest.mark.asyncio
    async def test_ensure_personal_team_creation_fails_then_succeeds(self, service, mock_user, mock_personal_team):
        """Test ensure personal team when creation fails with ValueError but team exists."""
        with patch.object(service, 'get_personal_team', new_callable=AsyncMock) as mock_get, \
             patch.object(service, 'create_personal_team', new_callable=AsyncMock) as mock_create:
            
            # First call returns None, second call returns the team
            mock_get.side_effect = [None, mock_personal_team]
            mock_create.side_effect = ValueError("Team already exists")
            
            result = await service.ensure_personal_team(mock_user)
            
            assert result == mock_personal_team
            assert mock_get.call_count == 2
            mock_create.assert_called_once_with(mock_user)

    @pytest.mark.asyncio
    async def test_ensure_personal_team_complete_failure(self, service, mock_user):
        """Test ensure personal team when both creation and retrieval fail."""
        with patch.object(service, 'get_personal_team', new_callable=AsyncMock) as mock_get, \
             patch.object(service, 'create_personal_team', new_callable=AsyncMock) as mock_create:
            
            mock_get.side_effect = [None, None]  # Team not found both times
            mock_create.side_effect = ValueError("Team already exists")
            
            with pytest.raises(Exception, match="Failed to get or create personal team"):
                await service.ensure_personal_team(mock_user)

    # =========================================================================
    # Is Personal Team Tests
    # =========================================================================

    def test_is_personal_team_true(self, service, mock_db, mock_personal_team):
        """Test checking if a team is personal (true case)."""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_personal_team
        
        result = service.is_personal_team("personal-team-123")
        
        assert result is True
        mock_db.query.assert_called_once_with(EmailTeam)

    def test_is_personal_team_false(self, service, mock_db, mock_regular_team):
        """Test checking if a team is personal (false case)."""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_regular_team
        
        result = service.is_personal_team("regular-team-456")
        
        assert result is False

    def test_is_personal_team_not_found(self, service, mock_db):
        """Test checking if a non-existent team is personal."""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        result = service.is_personal_team("nonexistent-team")
        
        assert result is False

    def test_is_personal_team_inactive(self, service, mock_db):
        """Test checking if an inactive team is personal."""
        team = MagicMock(spec=EmailTeam)
        team.is_personal = True
        team.is_active = False
        mock_db.query.return_value.filter.return_value.first.return_value = None  # Filtered out as inactive
        
        result = service.is_personal_team("inactive-team")
        
        assert result is False

    def test_is_personal_team_database_error(self, service, mock_db):
        """Test checking if team is personal with database error."""
        mock_db.query.side_effect = Exception("Database error")
        
        result = service.is_personal_team("team-id")
        
        assert result is False  # Should return False on error

    # =========================================================================
    # Delete Personal Team Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_delete_personal_team_not_allowed(self, service):
        """Test that personal teams cannot be deleted."""
        with patch.object(service, 'is_personal_team') as mock_check:
            mock_check.return_value = True
            
            with pytest.raises(ValueError, match="Personal teams cannot be deleted"):
                await service.delete_personal_team("personal-team-123")

    @pytest.mark.asyncio
    async def test_delete_non_personal_team(self, service):
        """Test delete operation on non-personal team."""
        with patch.object(service, 'is_personal_team') as mock_check:
            mock_check.return_value = False
            
            result = await service.delete_personal_team("regular-team-456")
            
            assert result is False  # Still returns False as this service doesn't delete any teams

    # =========================================================================
    # Get Personal Team Owner Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_personal_team_owner_found(self, service, mock_db, mock_personal_team):
        """Test getting owner of a personal team."""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_personal_team
        
        result = await service.get_personal_team_owner("personal-team-123")
        
        assert result == "testuser@example.com"
        mock_db.query.assert_called_once_with(EmailTeam)

    @pytest.mark.asyncio
    async def test_get_personal_team_owner_not_found(self, service, mock_db):
        """Test getting owner of non-existent personal team."""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        result = await service.get_personal_team_owner("nonexistent-team")
        
        assert result is None

    @pytest.mark.asyncio
    async def test_get_personal_team_owner_not_personal(self, service, mock_db, mock_regular_team):
        """Test getting owner of a non-personal team."""
        # Query should filter for is_personal=True, so regular team won't be found
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        result = await service.get_personal_team_owner("regular-team-456")
        
        assert result is None

    @pytest.mark.asyncio
    async def test_get_personal_team_owner_database_error(self, service, mock_db):
        """Test getting owner with database error."""
        mock_db.query.side_effect = Exception("Database error")
        
        result = await service.get_personal_team_owner("team-id")
        
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
        
        with patch('mcpgateway.services.personal_team_service.EmailTeam') as MockTeam, \
             patch('mcpgateway.services.personal_team_service.EmailTeamMember'):
            
            mock_team = MagicMock()
            mock_team.id = "long-email-team"
            MockTeam.return_value = mock_team
            
            result = await service.create_personal_team(user)
            
            assert result == mock_team
            call_args = MockTeam.call_args[1]
            expected_slug = "personal-very-long-email-address-with-many-dots-subdomain-example-com"
            assert call_args['slug'] == expected_slug

    @pytest.mark.asyncio
    async def test_create_personal_team_rollback_on_flush_error(self, service, mock_db, mock_user):
        """Test that rollback is called if flush fails."""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.flush.side_effect = Exception("Flush failed")
        
        with patch('mcpgateway.services.personal_team_service.EmailTeam'), \
             patch('mcpgateway.services.personal_team_service.EmailTeamMember'):
            
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
            MagicMock(id="existing-team")  # After failed creation attempt
        ]
        
        with patch('mcpgateway.services.personal_team_service.EmailTeam'), \
             patch('mcpgateway.services.personal_team_service.EmailTeamMember'):
            
            mock_db.commit.side_effect = Exception("UNIQUE constraint failed")
            
            with pytest.raises(Exception, match="UNIQUE constraint failed"):
                await service.create_personal_team(mock_user)
            
            mock_db.rollback.assert_called_once()

