# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_access.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for gateway access control (_check_gateway_access) with admin bypass and owner matching.
"""

# Standard
from unittest.mock import MagicMock, Mock

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.services.gateway_service import GatewayService


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = MagicMock()
    # Mock is_admin_bypass_granted check (db.execute for user lookup)
    mock_result = Mock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_result
    return db


@pytest.fixture
def gateway_service():
    """Create a GatewayService instance."""
    return GatewayService()


@pytest.fixture
def public_gateway():
    """Create a public gateway fixture."""
    gateway = MagicMock(spec=DbGateway)
    gateway.visibility = "public"
    gateway.owner_email = "owner@example.com"
    gateway.team_id = None
    return gateway


@pytest.fixture
def team_gateway():
    """Create a team gateway fixture."""
    gateway = MagicMock(spec=DbGateway)
    gateway.visibility = "team"
    gateway.owner_email = "owner@example.com"
    gateway.team_id = "team-123"
    return gateway


@pytest.fixture
def private_gateway():
    """Create a private gateway fixture."""
    gateway = MagicMock(spec=DbGateway)
    gateway.visibility = "private"
    gateway.owner_email = "owner@example.com"
    gateway.team_id = None
    return gateway


class TestCanAccessGatewayAdminBypass:
    """Test _check_gateway_access with admin bypass (token_teams=None)."""

    @pytest.mark.asyncio
    async def test_admin_can_access_own_private_gateway(self, gateway_service, private_gateway):
        """Admin with token_teams=None can access their own private gateway (PR #4877)."""
        # Admin user accessing their own private gateway
        user_email = "owner@example.com"
        token_teams = None  # Signals admin bypass

        # Mock is_admin_bypass_granted to return True
        mock_db_admin = MagicMock()
        mock_admin_result = Mock()
        mock_admin_result.scalar_one_or_none.return_value = MagicMock(is_admin=True)
        mock_db_admin.execute.return_value = mock_admin_result

        result = await gateway_service._check_gateway_access(mock_db_admin, private_gateway, user_email, token_teams)

        assert result is True

    @pytest.mark.asyncio
    async def test_admin_cannot_access_others_private_gateway(self, gateway_service, private_gateway):
        """Admin with token_teams=None cannot access another user's private gateway (PR #4877)."""
        # Admin user accessing someone else's private gateway
        user_email = "admin@example.com"
        token_teams = None  # Signals admin bypass
        private_gateway.owner_email = "other@example.com"

        # Mock is_admin_bypass_granted to return True
        mock_db_admin = MagicMock()
        mock_admin_result = Mock()
        mock_admin_result.scalar_one_or_none.return_value = MagicMock(is_admin=True)
        mock_db_admin.execute.return_value = mock_admin_result

        result = await gateway_service._check_gateway_access(mock_db_admin, private_gateway, user_email, token_teams)

        assert result is False

    @pytest.mark.asyncio
    async def test_admin_can_access_public_gateway(self, gateway_service, public_gateway):
        """Admin with token_teams=None can access public gateways (PR #4877)."""
        user_email = "admin@example.com"
        token_teams = None  # Signals admin bypass

        # Mock is_admin_bypass_granted to return True
        mock_db_admin = MagicMock()
        mock_admin_result = Mock()
        mock_admin_result.scalar_one_or_none.return_value = MagicMock(is_admin=True)
        mock_db_admin.execute.return_value = mock_admin_result

        result = await gateway_service._check_gateway_access(mock_db_admin, public_gateway, user_email, token_teams)

        assert result is True

    @pytest.mark.asyncio
    async def test_admin_can_access_team_gateway(self, gateway_service, team_gateway):
        """Admin with token_teams=None can access team gateways (PR #4877)."""
        user_email = "admin@example.com"
        token_teams = None  # Signals admin bypass

        # Mock is_admin_bypass_granted to return True
        mock_db_admin = MagicMock()
        mock_admin_result = Mock()
        mock_admin_result.scalar_one_or_none.return_value = MagicMock(is_admin=True)
        mock_db_admin.execute.return_value = mock_admin_result

        result = await gateway_service._check_gateway_access(mock_db_admin, team_gateway, user_email, token_teams)

        assert result is True

    @pytest.mark.asyncio
    async def test_admin_private_gateway_without_owner_email(self, gateway_service, private_gateway):
        """Admin cannot access private gateway without owner_email set (PR #4877)."""
        user_email = "admin@example.com"
        token_teams = None  # Signals admin bypass
        private_gateway.owner_email = None

        # Mock is_admin_bypass_granted to return True
        mock_db_admin = MagicMock()
        mock_admin_result = Mock()
        mock_admin_result.scalar_one_or_none.return_value = MagicMock(is_admin=True)
        mock_db_admin.execute.return_value = mock_admin_result

        result = await gateway_service._check_gateway_access(mock_db_admin, private_gateway, user_email, token_teams)

        # Implementation returns None when owner_email is None (truthy check fails)
        assert not result


class TestCanAccessGatewayNonAdmin:
    """Test _check_gateway_access without admin bypass (regular users)."""

    @pytest.mark.asyncio
    async def test_regular_user_can_access_public_gateway(self, gateway_service, mock_db, public_gateway):
        """Regular user can access public gateways."""
        user_email = "user@example.com"
        token_teams = []  # Regular user, not admin bypass

        result = await gateway_service._check_gateway_access(mock_db, public_gateway, user_email, token_teams)

        assert result is True

    @pytest.mark.asyncio
    async def test_regular_user_can_access_team_gateway_when_in_team(self, gateway_service, mock_db, team_gateway):
        """Regular user can access team gateway when their token includes the team."""
        user_email = "user@example.com"
        token_teams = ["team-123"]  # User is in the team

        result = await gateway_service._check_gateway_access(mock_db, team_gateway, user_email, token_teams)

        assert result is True

    @pytest.mark.asyncio
    async def test_regular_user_cannot_access_team_gateway_when_not_in_team(self, gateway_service, mock_db, team_gateway):
        """Regular user cannot access team gateway when not in the team."""
        user_email = "user@example.com"
        token_teams = ["other-team"]  # User is not in the gateway's team

        result = await gateway_service._check_gateway_access(mock_db, team_gateway, user_email, token_teams)

        assert result is False

    @pytest.mark.asyncio
    async def test_regular_user_can_access_own_private_gateway(self, gateway_service, mock_db, private_gateway):
        """Regular user can access their own private gateway when they have team membership."""
        user_email = "owner@example.com"
        token_teams = ["team-123"]  # Regular user with team membership (not public-only)

        result = await gateway_service._check_gateway_access(mock_db, private_gateway, user_email, token_teams)

        assert result is True

    @pytest.mark.asyncio
    async def test_regular_user_cannot_access_others_private_gateway(self, gateway_service, mock_db, private_gateway):
        """Regular user cannot access another user's private gateway."""
        user_email = "user@example.com"
        token_teams = []  # Regular user
        private_gateway.owner_email = "other@example.com"

        result = await gateway_service._check_gateway_access(mock_db, private_gateway, user_email, token_teams)

        assert result is False


class TestCanAccessGatewayEdgeCases:
    """Test edge cases for _check_gateway_access."""

    @pytest.mark.asyncio
    async def test_empty_user_email(self, gateway_service, mock_db, public_gateway):
        """Empty user_email can access public gateways."""
        user_email = ""
        token_teams = []

        result = await gateway_service._check_gateway_access(mock_db, public_gateway, user_email, token_teams)

        assert result is True

    @pytest.mark.asyncio
    async def test_none_user_email_public(self, gateway_service, mock_db, public_gateway):
        """None user_email can access public gateways."""
        user_email = None
        token_teams = []

        result = await gateway_service._check_gateway_access(mock_db, public_gateway, user_email, token_teams)

        assert result is True

    @pytest.mark.asyncio
    async def test_none_user_email_private(self, gateway_service, mock_db, private_gateway):
        """None user_email cannot access private gateways."""
        user_email = None
        token_teams = []

        result = await gateway_service._check_gateway_access(mock_db, private_gateway, user_email, token_teams)

        assert result is False

    @pytest.mark.asyncio
    async def test_gateway_without_visibility(self, gateway_service, mock_db):
        """Gateway without visibility attribute defaults to False."""
        gateway = MagicMock(spec=DbGateway)
        gateway.visibility = None
        gateway.owner_email = "owner@example.com"
        user_email = "user@example.com"
        token_teams = []

        result = await gateway_service._check_gateway_access(mock_db, gateway, user_email, token_teams)

        assert result is False
