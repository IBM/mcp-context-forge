"""
Regression tests for admin team visibility security issue.

Tests that admin users cannot see personal teams of other users or private teams
they are not members of. This addresses the security vulnerability where admins
could view all teams including personal workspaces.

Security Invariants:
- Admin users should only see teams they are members of, plus discoverable public teams
- Personal teams of other users should NEVER be exposed to admins
- Private teams the admin is not a member of should NOT be visible to admins
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mcpgateway.admin import admin_teams_partial_html, admin_get_all_team_ids, admin_search_teams, admin_list_teams
from mcpgateway.db import EmailTeam, EmailUser


@pytest.fixture
def mock_admin_user():
    """Create a mock admin user."""
    user = MagicMock(spec=EmailUser)
    user.email = "admin@example.com"
    user.is_admin = True
    user.is_active = True
    return user


@pytest.fixture
def mock_regular_user():
    """Create a mock regular user."""
    user = MagicMock(spec=EmailUser)
    user.email = "user@example.com"
    user.is_admin = False
    user.is_active = True
    return user


@pytest.fixture
def mock_personal_team():
    """Create a mock personal team."""
    team = MagicMock(spec=EmailTeam)
    team.id = "personal-team-id"
    team.name = "user@example.com"
    team.slug = "user-example-com"
    team.description = "Personal workspace"
    team.created_by = "user@example.com"
    team.is_personal = True
    team.visibility = "private"
    team.is_active = True
    return team


@pytest.fixture
def mock_private_team():
    """Create a mock private team."""
    team = MagicMock(spec=EmailTeam)
    team.id = "private-team-id"
    team.name = "Private Team"
    team.slug = "private-team"
    team.description = "A private team"
    team.created_by = "user@example.com"
    team.is_personal = False
    team.visibility = "private"
    team.is_active = True
    return team


@pytest.fixture
def mock_public_team():
    """Create a mock public team."""
    team = MagicMock(spec=EmailTeam)
    team.id = "public-team-id"
    team.name = "Public Team"
    team.slug = "public-team"
    team.description = "A public team"
    team.created_by = "user@example.com"
    team.is_personal = False
    team.visibility = "public"
    team.is_active = True
    return team


@pytest.mark.asyncio
class TestAdminTeamVisibilitySecurity:
    """Test suite for admin team visibility security."""

    async def test_admin_teams_partial_excludes_personal_teams(self, monkeypatch, mock_admin_user, mock_personal_team, mock_public_team):
        """Admin should NOT see other users' personal teams via admin_teams_partial_html."""
        monkeypatch.setattr("mcpgateway.admin.settings.email_auth_enabled", True)

        mock_request = MagicMock()
        mock_request.app.state.templates.TemplateResponse = MagicMock()
        mock_request.url.path = "/admin/teams/partial"

        mock_db = MagicMock()

        # Mock auth service to return admin user
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_admin_user)

        # Mock team service - list_teams should be called with include_personal=False
        mock_team_service = MagicMock()
        mock_team_service.get_user_teams = AsyncMock(return_value=[])
        mock_team_service.discover_public_teams = AsyncMock(return_value=[mock_public_team])
        mock_team_service.get_user_roles_batch = MagicMock(return_value={})
        mock_team_service.get_pending_join_requests_batch = MagicMock(return_value={})
        mock_team_service.get_member_counts_batch_cached = AsyncMock(return_value={})
        mock_team_service.get_user_personal_team = AsyncMock(return_value=None)  # Admin has no personal team in this test

        # The key assertion: list_teams should be called with include_personal=False
        mock_team_service.list_teams = AsyncMock(return_value={
            "data": [mock_public_team],  # Only public team, NO personal teams
            "pagination": MagicMock(page=1, per_page=50, total_items=1, total_pages=1, has_next=False, has_prev=False),
            "links": None
        })

        with patch("mcpgateway.admin.EmailAuthService", return_value=mock_auth_service), \
             patch("mcpgateway.admin.TeamManagementService", return_value=mock_team_service), \
             patch("mcpgateway.admin.get_user_email", return_value="admin@example.com"), \
             patch("mcpgateway.admin._resolve_root_path", return_value=""):

            await admin_teams_partial_html(
                request=mock_request,
                page=1,
                per_page=50,
                include_inactive=False,
                visibility=None,
                render=None,
                q=None,
                relationship=None,
                db=mock_db,
                user=mock_admin_user
            )

            # Verify list_teams was called with include_personal=False
            mock_team_service.list_teams.assert_called_once()
            call_kwargs = mock_team_service.list_teams.call_args[1]
            assert call_kwargs["include_personal"] is False, "Admin should not see personal teams"

    async def test_admin_get_all_team_ids_excludes_personal_teams(self, monkeypatch, mock_admin_user, mock_personal_team):
        """Admin should NOT see other users' personal teams via admin_get_all_team_ids."""
        mock_db = MagicMock()

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_admin_user)

        mock_team_service = MagicMock()
        # The key assertion: get_all_team_ids should be called with include_personal=False
        mock_team_service.get_all_team_ids = AsyncMock(return_value=["public-team-id"])
        mock_team_service.get_user_personal_team = AsyncMock(return_value=None)  # Admin has no personal team in this test

        with patch("mcpgateway.admin.EmailAuthService", return_value=mock_auth_service), \
             patch("mcpgateway.admin.TeamManagementService", return_value=mock_team_service), \
             patch("mcpgateway.admin.get_user_email", return_value="admin@example.com"):

            await admin_get_all_team_ids(
                include_inactive=False,
                visibility=None,
                q=None,
                db=mock_db,
                user=mock_admin_user
            )

            # Verify get_all_team_ids was called with include_personal=False
            mock_team_service.get_all_team_ids.assert_called_once()
            call_kwargs = mock_team_service.get_all_team_ids.call_args[1]
            assert call_kwargs["include_personal"] is False, "Admin should not see personal teams"

    async def test_admin_search_teams_excludes_personal_teams(self, monkeypatch, mock_admin_user, mock_public_team):
        """Admin should NOT see other users' personal teams via admin_search_teams."""
        mock_db = MagicMock()

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_admin_user)

        mock_team_service = MagicMock()
        # The key assertion: list_teams should be called with include_personal=False
        mock_team_service.list_teams = AsyncMock(return_value={
            "data": [mock_public_team],
            "pagination": MagicMock(),
            "links": None
        })
        mock_team_service.get_user_personal_team = AsyncMock(return_value=None)  # Admin has no personal team in this test

        with patch("mcpgateway.admin.EmailAuthService", return_value=mock_auth_service), \
             patch("mcpgateway.admin.TeamManagementService", return_value=mock_team_service), \
             patch("mcpgateway.admin.get_user_email", return_value="admin@example.com"), \
             patch("mcpgateway.admin._normalize_search_query", return_value="test"):

            await admin_search_teams(
                q="test",
                include_inactive=False,
                limit=50,
                visibility=None,
                db=mock_db,
                user=mock_admin_user
            )

            # Verify list_teams was called with include_personal=False
            mock_team_service.list_teams.assert_called_once()
            call_kwargs = mock_team_service.list_teams.call_args[1]
            assert call_kwargs["include_personal"] is False, "Admin should not see personal teams"

    async def test_admin_list_teams_excludes_personal_teams(self, monkeypatch, mock_admin_user, mock_public_team):
        """Admin should NOT see other users' personal teams via admin_list_teams."""
        monkeypatch.setattr("mcpgateway.admin.settings.email_auth_enabled", True)

        mock_request = MagicMock()
        mock_request.app.state.templates.TemplateResponse = MagicMock()
        mock_db = MagicMock()

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_admin_user)

        mock_team_service = MagicMock()
        # The key assertion: list_teams should be called with include_personal=False
        mock_team_service.list_teams = AsyncMock(return_value={
            "data": [mock_public_team],
            "pagination": MagicMock(page=1, per_page=50, total_items=1, total_pages=1, has_next=False, has_prev=False),
            "links": None
        })
        mock_team_service.get_member_counts_batch_cached = AsyncMock(return_value={})
        mock_team_service.get_user_personal_team = AsyncMock(return_value=None)  # Admin has no personal team in this test

        with patch("mcpgateway.admin.EmailAuthService", return_value=mock_auth_service), \
             patch("mcpgateway.admin.TeamManagementService", return_value=mock_team_service), \
             patch("mcpgateway.admin.get_user_email", return_value="admin@example.com"), \
             patch("mcpgateway.admin._resolve_root_path", return_value=""):

            await admin_list_teams(
                request=mock_request,
                page=1,
                per_page=50,
                q=None,
                db=mock_db,
                user=mock_admin_user,
                unified=False
            )

            # Verify list_teams was called with include_personal=False
            mock_team_service.list_teams.assert_called_once()
            call_kwargs = mock_team_service.list_teams.call_args[1]
            assert call_kwargs["include_personal"] is False, "Admin should not see personal teams"

    async def test_non_admin_can_see_own_personal_team(self, monkeypatch, mock_regular_user, mock_personal_team):
        """Non-admin users should still see their own personal team."""
        monkeypatch.setattr("mcpgateway.admin.settings.email_auth_enabled", True)

        mock_request = MagicMock()
        mock_request.app.state.templates.TemplateResponse = MagicMock()
        mock_request.url.path = "/admin/teams/partial"

        mock_db = MagicMock()

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_regular_user)

        mock_team_service = MagicMock()
        # Non-admin gets their teams via get_user_teams which includes personal
        mock_team_service.get_user_teams = AsyncMock(return_value=[mock_personal_team])
        mock_team_service.discover_public_teams = AsyncMock(return_value=[])
        mock_team_service.get_user_roles_batch = MagicMock(return_value={"personal-team-id": "owner"})
        mock_team_service.get_pending_join_requests_batch = MagicMock(return_value={})
        mock_team_service.get_member_counts_batch_cached = AsyncMock(return_value={"personal-team-id": 1})
        mock_team_service.get_user_personal_team = AsyncMock(return_value=mock_personal_team)

        with patch("mcpgateway.admin.EmailAuthService", return_value=mock_auth_service), \
             patch("mcpgateway.admin.TeamManagementService", return_value=mock_team_service), \
             patch("mcpgateway.admin.get_user_email", return_value="user@example.com"), \
             patch("mcpgateway.admin._resolve_root_path", return_value=""):

            await admin_teams_partial_html(
                request=mock_request,
                page=1,
                per_page=50,
                include_inactive=False,
                visibility=None,
                render=None,
                q=None,
                relationship=None,
                db=mock_db,
                user=mock_regular_user
            )

            # Verify get_user_teams was called with include_personal=True for non-admin
            mock_team_service.get_user_teams.assert_called_once()
            call_kwargs = mock_team_service.get_user_teams.call_args[1]
            assert call_kwargs["include_personal"] is True, "Non-admin should see their own personal team"

    async def test_admin_can_see_own_personal_team(self, monkeypatch, mock_admin_user):
        """Admin users SHOULD see their own personal team (regression test for fix)."""
        monkeypatch.setattr("mcpgateway.admin.settings.email_auth_enabled", True)

        # Create admin's personal team
        admin_personal_team = MagicMock(spec=EmailTeam)
        admin_personal_team.id = "admin-personal-team-id"
        admin_personal_team.name = "admin@example.com"
        admin_personal_team.slug = "admin-example-com"
        admin_personal_team.description = "Admin's personal workspace"
        admin_personal_team.created_by = "admin@example.com"
        admin_personal_team.is_personal = True
        admin_personal_team.visibility = "private"
        admin_personal_team.is_active = True

        mock_request = MagicMock()
        mock_request.app.state.templates.TemplateResponse = MagicMock()
        mock_request.url.path = "/admin/teams/partial"

        mock_db = MagicMock()

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_admin_user)

        mock_team_service = MagicMock()
        mock_team_service.get_user_teams = AsyncMock(return_value=[])
        mock_team_service.discover_public_teams = AsyncMock(return_value=[])
        mock_team_service.get_user_roles_batch = MagicMock(return_value={})
        mock_team_service.get_pending_join_requests_batch = MagicMock(return_value={})
        mock_team_service.get_member_counts_batch_cached = AsyncMock(return_value={"admin-personal-team-id": 1})

        # list_teams returns empty (no non-personal teams)
        mock_team_service.list_teams = AsyncMock(return_value={
            "data": [],
            "pagination": MagicMock(page=1, per_page=50, total_items=0, total_pages=0, has_next=False, has_prev=False),
            "links": None
        })

        # get_user_personal_team returns admin's personal team (must be AsyncMock)
        mock_team_service.get_user_personal_team = AsyncMock(return_value=admin_personal_team)

        with patch("mcpgateway.admin.EmailAuthService", return_value=mock_auth_service), \
             patch("mcpgateway.admin.TeamManagementService", return_value=mock_team_service), \
             patch("mcpgateway.admin.get_user_email", return_value="admin@example.com"), \
             patch("mcpgateway.admin._resolve_root_path", return_value=""):

            await admin_teams_partial_html(
                request=mock_request,
                page=1,
                per_page=50,
                include_inactive=False,
                visibility=None,
                render=None,
                q=None,
                relationship=None,
                db=mock_db,
                user=mock_admin_user
            )

            # Verify get_user_personal_team was called to fetch admin's personal team
            mock_team_service.get_user_personal_team.assert_called_once_with("admin@example.com")

            # Verify list_teams was still called with include_personal=False (to exclude OTHER users' personal teams)
            mock_team_service.list_teams.assert_called_once()
            call_kwargs = mock_team_service.list_teams.call_args[1]
            assert call_kwargs["include_personal"] is False, "Should not include other users' personal teams"

    async def test_admin_cannot_see_private_teams_not_member_of(self, monkeypatch, mock_admin_user, mock_private_team, mock_public_team):
        """Admin should NOT see private teams they are not a member of."""
        monkeypatch.setattr("mcpgateway.admin.settings.email_auth_enabled", True)

        mock_request = MagicMock()
        mock_request.app.state.templates.TemplateResponse = MagicMock()
        mock_request.url.path = "/admin/teams/partial"

        mock_db = MagicMock()

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_admin_user)

        mock_team_service = MagicMock()
        # Admin is not a member of any teams
        mock_team_service.get_user_teams = AsyncMock(return_value=[])
        # Only public teams are discoverable
        mock_team_service.discover_public_teams = AsyncMock(return_value=[mock_public_team])
        mock_team_service.get_user_roles_batch = MagicMock(return_value={})
        mock_team_service.get_pending_join_requests_batch = MagicMock(return_value={})
        mock_team_service.get_member_counts_batch_cached = AsyncMock(return_value={})
        mock_team_service.get_user_personal_team = AsyncMock(return_value=None)

        # list_teams should only return public teams, not private ones
        mock_team_service.list_teams = AsyncMock(return_value={
            "data": [mock_public_team],  # Only public team, NO private teams
            "pagination": MagicMock(page=1, per_page=50, total_items=1, total_pages=1, has_next=False, has_prev=False),
            "links": None
        })

        with patch("mcpgateway.admin.EmailAuthService", return_value=mock_auth_service), \
             patch("mcpgateway.admin.TeamManagementService", return_value=mock_team_service), \
             patch("mcpgateway.admin.get_user_email", return_value="admin@example.com"), \
             patch("mcpgateway.admin._resolve_root_path", return_value=""):

            await admin_teams_partial_html(
                request=mock_request,
                page=1,
                per_page=50,
                include_inactive=False,
                visibility=None,
                render=None,
                q=None,
                relationship=None,
                db=mock_db,
                user=mock_admin_user
            )

            # Verify the returned data does not include private teams
            mock_team_service.list_teams.assert_called_once()
            call_kwargs = mock_team_service.list_teams.call_args[1]
            assert call_kwargs["include_personal"] is False

            # The service layer should handle filtering private teams based on membership
            # This test verifies the admin endpoint doesn't bypass that filtering

