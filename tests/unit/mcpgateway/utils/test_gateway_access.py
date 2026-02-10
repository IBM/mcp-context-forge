# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_gateway_access.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for gateway access control utilities.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.utils.gateway_access import check_gateway_access


class TestCheckGatewayAccess:
    """Test suite for check_gateway_access function."""

    @pytest.mark.asyncio
    async def test_public_gateway_accessible_by_all(self):
        """Public gateways should be accessible by everyone."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "public"
        gateway.team_id = None
        gateway.owner_email = None

        # Authenticated user
        result = await check_gateway_access(db, gateway, "user@example.com", [])
        assert result is True

        # Unauthenticated user
        result = await check_gateway_access(db, gateway, None, [])
        assert result is True

        # Public-only token
        result = await check_gateway_access(db, gateway, "user@example.com", [])
        assert result is True

    @pytest.mark.asyncio
    async def test_admin_bypass_with_none_token_teams(self):
        """Admin with token_teams=None should have unrestricted access."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "private"
        gateway.team_id = "team1"
        gateway.owner_email = "owner@example.com"

        # Admin bypass: token_teams=None AND user_email=None
        result = await check_gateway_access(db, gateway, None, None)
        assert result is True

    @pytest.mark.asyncio
    async def test_private_gateway_owner_access(self):
        """Private gateway owner should have access."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "private"
        gateway.team_id = None
        gateway.owner_email = "owner@example.com"

        # Owner has access
        result = await check_gateway_access(db, gateway, "owner@example.com", ["team1"])
        assert result is True

        # Non-owner denied
        result = await check_gateway_access(db, gateway, "other@example.com", ["team1"])
        assert result is False

    @pytest.mark.asyncio
    async def test_private_gateway_unauthenticated_denied(self):
        """Unauthenticated users should not access private gateways."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "private"
        gateway.team_id = None
        gateway.owner_email = "owner@example.com"

        result = await check_gateway_access(db, gateway, None, [])
        assert result is False

    @pytest.mark.asyncio
    async def test_public_only_token_denied_non_public(self):
        """Public-only tokens (empty teams array) should only access public gateways."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = "team1"
        gateway.owner_email = "owner@example.com"

        # Public-only token (empty teams array)
        result = await check_gateway_access(db, gateway, "user@example.com", [])
        assert result is False

        # Even if user is the owner
        result = await check_gateway_access(db, gateway, "owner@example.com", [])
        assert result is False

    @pytest.mark.asyncio
    async def test_team_gateway_team_member_access(self):
        """Team gateway should be accessible by team members."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = "team1"
        gateway.owner_email = "owner@example.com"

        # Team member has access
        result = await check_gateway_access(db, gateway, "member@example.com", ["team1", "team2"])
        assert result is True

        # Non-team member denied
        result = await check_gateway_access(db, gateway, "other@example.com", ["team2", "team3"])
        assert result is False

    @pytest.mark.asyncio
    async def test_team_gateway_owner_access(self):
        """Team gateway owner should have access even if not in token teams."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = "team1"
        gateway.owner_email = "owner@example.com"

        # Owner has access even without team in token
        result = await check_gateway_access(db, gateway, "owner@example.com", ["team2"])
        assert result is True

    @pytest.mark.asyncio
    async def test_team_gateway_db_lookup_when_token_teams_none(self):
        """Should look up teams from DB when token_teams is None (non-admin)."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = "team1"
        gateway.owner_email = "other@example.com"

        # Mock team service
        mock_team = MagicMock()
        mock_team.id = "team1"

        with patch("mcpgateway.services.team_management_service.TeamManagementService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_user_teams = AsyncMock(return_value=[mock_team])
            mock_service_class.return_value = mock_service

            # token_teams=None but user_email provided (non-admin case)
            result = await check_gateway_access(db, gateway, "user@example.com", None)
            assert result is True

            # Verify team service was called
            mock_service_class.assert_called_once_with(db)
            mock_service.get_user_teams.assert_called_once_with("user@example.com")

    @pytest.mark.asyncio
    async def test_team_gateway_db_lookup_no_access(self):
        """Should deny access when DB lookup shows user not in team."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = "team1"
        gateway.owner_email = "other@example.com"

        # Mock team service - user in different team
        mock_team = MagicMock()
        mock_team.id = "team2"

        with patch("mcpgateway.services.team_management_service.TeamManagementService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_user_teams = AsyncMock(return_value=[mock_team])
            mock_service_class.return_value = mock_service

            result = await check_gateway_access(db, gateway, "user@example.com", None)
            assert result is False

    @pytest.mark.asyncio
    async def test_gateway_without_visibility_defaults_to_public(self):
        """Gateway without visibility attribute should default to public."""
        db = MagicMock()
        gateway = MagicMock(spec=[])  # No attributes

        result = await check_gateway_access(db, gateway, "user@example.com", [])
        assert result is True

    @pytest.mark.asyncio
    async def test_team_gateway_with_public_visibility(self):
        """Team gateway with public visibility should allow team members."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "public"
        gateway.team_id = "team1"
        gateway.owner_email = "owner@example.com"

        # Team member has access
        result = await check_gateway_access(db, gateway, "member@example.com", ["team1"])
        assert result is True

        # Non-team member also has access (public visibility)
        result = await check_gateway_access(db, gateway, "other@example.com", ["team2"])
        assert result is True

    @pytest.mark.asyncio
    async def test_multiple_teams_in_token(self):
        """Should grant access if any team in token matches gateway team."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = "team2"
        gateway.owner_email = "owner@example.com"

        # User has multiple teams, one matches
        result = await check_gateway_access(db, gateway, "user@example.com", ["team1", "team2", "team3"])
        assert result is True

    @pytest.mark.asyncio
    async def test_no_user_email_non_public_denied(self):
        """No user email (non-admin) should be denied for non-public gateways."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = "team1"
        gateway.owner_email = "owner@example.com"

        # No user email, not admin (token_teams is not None)
        result = await check_gateway_access(db, gateway, None, ["team1"])
        assert result is False

    @pytest.mark.asyncio
    async def test_gateway_without_team_id(self):
        """Gateway without team_id should not grant team-based access."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = None
        gateway.owner_email = "owner@example.com"

        # Non-owner with teams should be denied
        result = await check_gateway_access(db, gateway, "user@example.com", ["team1"])
        assert result is False

        # Owner should still have access
        result = await check_gateway_access(db, gateway, "owner@example.com", ["team1"])
        assert result is True

    @pytest.mark.asyncio
    async def test_gateway_without_owner_email(self):
        """Gateway without owner_email should not grant owner-based access."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "private"
        gateway.team_id = None
        gateway.owner_email = None

        # No owner, so no one can access private gateway
        result = await check_gateway_access(db, gateway, "user@example.com", ["team1"])
        assert result is False

# Made with Bob
# Co-authored by Venkat (010gvr@gmail.com)
