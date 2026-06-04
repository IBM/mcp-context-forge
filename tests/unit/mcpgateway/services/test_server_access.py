# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_server_access.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Tests for server access control (_check_server_access) with admin bypass and owner matching.
"""

# Standard
from unittest.mock import MagicMock, Mock

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Server as DbServer
from mcpgateway.services.server_service import ServerService


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
def server_service():
    """Create a ServerService instance."""
    return ServerService()


@pytest.fixture
def public_server():
    """Create a public server fixture."""
    server = MagicMock(spec=DbServer)
    server.visibility = "public"
    server.owner_email = "owner@example.com"
    server.team_id = None
    return server


@pytest.fixture
def team_server():
    """Create a team server fixture."""
    server = MagicMock(spec=DbServer)
    server.visibility = "team"
    server.owner_email = "owner@example.com"
    server.team_id = "team-123"
    return server


@pytest.fixture
def private_server():
    """Create a private server fixture."""
    server = MagicMock(spec=DbServer)
    server.visibility = "private"
    server.owner_email = "owner@example.com"
    server.team_id = None
    return server


class TestCanAccessServerAdminBypass:
    """Test _check_server_access with admin bypass (token_teams=None)."""

    @pytest.mark.asyncio
    async def test_admin_can_access_own_private_server(self, server_service, private_server):
        """Admin with token_teams=None can access their own private server (PR #4877)."""
        # Admin user accessing their own private server
        user_email = "owner@example.com"
        token_teams = None  # Signals admin bypass

        # Mock is_admin_bypass_granted to return True
        mock_db_admin = MagicMock()
        mock_admin_result = Mock()
        mock_admin_result.scalar_one_or_none.return_value = MagicMock(is_admin=True)
        mock_db_admin.execute.return_value = mock_admin_result

        result = await server_service._check_server_access(mock_db_admin, private_server, user_email, token_teams)

        assert result is True

    @pytest.mark.asyncio
    async def test_admin_cannot_access_others_private_server(self, server_service, private_server):
        """Admin with token_teams=None cannot access another user's private server (PR #4877)."""
        # Admin user accessing someone else's private server
        user_email = "admin@example.com"
        token_teams = None  # Signals admin bypass
        private_server.owner_email = "other@example.com"

        # Mock is_admin_bypass_granted to return True
        mock_db_admin = MagicMock()
        mock_admin_result = Mock()
        mock_admin_result.scalar_one_or_none.return_value = MagicMock(is_admin=True)
        mock_db_admin.execute.return_value = mock_admin_result

        result = await server_service._check_server_access(mock_db_admin, private_server, user_email, token_teams)

        assert result is False

    @pytest.mark.asyncio
    async def test_admin_can_access_public_server(self, server_service, public_server):
        """Admin with token_teams=None can access public servers (PR #4877)."""
        user_email = "admin@example.com"
        token_teams = None  # Signals admin bypass

        # Mock is_admin_bypass_granted to return True
        mock_db_admin = MagicMock()
        mock_admin_result = Mock()
        mock_admin_result.scalar_one_or_none.return_value = MagicMock(is_admin=True)
        mock_db_admin.execute.return_value = mock_admin_result

        result = await server_service._check_server_access(mock_db_admin, public_server, user_email, token_teams)

        assert result is True

    @pytest.mark.asyncio
    async def test_admin_can_access_team_server(self, server_service, team_server):
        """Admin with token_teams=None can access team servers (PR #4877)."""
        user_email = "admin@example.com"
        token_teams = None  # Signals admin bypass

        # Mock is_admin_bypass_granted to return True
        mock_db_admin = MagicMock()
        mock_admin_result = Mock()
        mock_admin_result.scalar_one_or_none.return_value = MagicMock(is_admin=True)
        mock_db_admin.execute.return_value = mock_admin_result

        result = await server_service._check_server_access(mock_db_admin, team_server, user_email, token_teams)

        assert result is True

    @pytest.mark.asyncio
    async def test_admin_private_server_without_owner_email(self, server_service, private_server):
        """Admin cannot access private server without owner_email set (PR #4877)."""
        user_email = "admin@example.com"
        token_teams = None  # Signals admin bypass
        private_server.owner_email = None

        # Mock is_admin_bypass_granted to return True
        mock_db_admin = MagicMock()
        mock_admin_result = Mock()
        mock_admin_result.scalar_one_or_none.return_value = MagicMock(is_admin=True)
        mock_db_admin.execute.return_value = mock_admin_result

        result = await server_service._check_server_access(mock_db_admin, private_server, user_email, token_teams)

        # Implementation returns None when owner_email is None (truthy check fails)
        assert not result


class TestCanAccessServerNonAdmin:
    """Test _check_server_access without admin bypass (regular users)."""

    @pytest.mark.asyncio
    async def test_regular_user_can_access_public_server(self, server_service, mock_db, public_server):
        """Regular user can access public servers."""
        user_email = "user@example.com"
        token_teams = []  # Regular user, not admin bypass

        result = await server_service._check_server_access(mock_db, public_server, user_email, token_teams)

        assert result is True

    @pytest.mark.asyncio
    async def test_regular_user_can_access_team_server_when_in_team(self, server_service, mock_db, team_server):
        """Regular user can access team server when their token includes the team."""
        user_email = "user@example.com"
        token_teams = ["team-123"]  # User is in the team

        result = await server_service._check_server_access(mock_db, team_server, user_email, token_teams)

        assert result is True

    @pytest.mark.asyncio
    async def test_regular_user_cannot_access_team_server_when_not_in_team(self, server_service, mock_db, team_server):
        """Regular user cannot access team server when not in the team."""
        user_email = "user@example.com"
        token_teams = ["other-team"]  # User is not in the server's team

        result = await server_service._check_server_access(mock_db, team_server, user_email, token_teams)

        assert result is False

    @pytest.mark.asyncio
    async def test_regular_user_can_access_own_private_server(self, server_service, mock_db, private_server):
        """Regular user can access their own private server when they have team membership."""
        user_email = "owner@example.com"
        token_teams = ["team-123"]  # Regular user with team membership (not public-only)

        result = await server_service._check_server_access(mock_db, private_server, user_email, token_teams)

        assert result is True

    @pytest.mark.asyncio
    async def test_regular_user_cannot_access_others_private_server(self, server_service, mock_db, private_server):
        """Regular user cannot access another user's private server."""
        user_email = "user@example.com"
        token_teams = []  # Regular user
        private_server.owner_email = "other@example.com"

        result = await server_service._check_server_access(mock_db, private_server, user_email, token_teams)

        assert result is False


class TestCanAccessServerEdgeCases:
    """Test edge cases for _check_server_access."""

    @pytest.mark.asyncio
    async def test_empty_user_email(self, server_service, mock_db, public_server):
        """Empty user_email can access public servers."""
        user_email = ""
        token_teams = []

        result = await server_service._check_server_access(mock_db, public_server, user_email, token_teams)

        assert result is True

    @pytest.mark.asyncio
    async def test_none_user_email_public(self, server_service, mock_db, public_server):
        """None user_email can access public servers."""
        user_email = None
        token_teams = []

        result = await server_service._check_server_access(mock_db, public_server, user_email, token_teams)

        assert result is True

    @pytest.mark.asyncio
    async def test_none_user_email_private(self, server_service, mock_db, private_server):
        """None user_email cannot access private servers."""
        user_email = None
        token_teams = []

        result = await server_service._check_server_access(mock_db, private_server, user_email, token_teams)

        assert result is False

    @pytest.mark.asyncio
    async def test_server_without_visibility(self, server_service, mock_db):
        """Server without visibility attribute defaults to False."""
        server = MagicMock(spec=DbServer)
        server.visibility = None
        server.owner_email = "owner@example.com"
        user_email = "user@example.com"
        token_teams = []

        result = await server_service._check_server_access(mock_db, server, user_email, token_teams)

        assert result is False
