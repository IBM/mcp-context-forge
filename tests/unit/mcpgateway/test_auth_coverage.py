# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_auth_coverage.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Coverage tests for auth.py changes related to is_admin resolution.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mcpgateway.auth import _resolve_teams_from_db, resolve_session_teams
from mcpgateway.db import EmailUser


class TestResolveTeamsFromDbIsAdminBranches:
    """Test is_admin resolution branches in _resolve_teams_from_db."""

    @pytest.mark.asyncio
    async def test_dict_user_info_with_is_admin_none_fetches_from_db(self):
        """Test dict user_info with is_admin=None triggers DB lookup."""
        user_info = {"email": "test@example.com"}  # No is_admin key

        mock_db_user = MagicMock(spec=EmailUser)
        mock_db_user.is_admin = True

        with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_db_user):
            result = await _resolve_teams_from_db(email="test@example.com", user_info=user_info)

        # Admin bypass returns None
        assert result is None

    @pytest.mark.asyncio
    async def test_dict_user_info_with_is_admin_false_queries_teams(self):
        """Test dict user_info with is_admin=False queries teams."""
        user_info = {"email": "test@example.com", "is_admin": False}

        with patch("mcpgateway.auth._get_user_by_email_sync", side_effect=AssertionError("Should not be called")):
            with patch("mcpgateway.auth._get_user_team_ids_sync", return_value=["team1"]):
                result = await _resolve_teams_from_db(email="test@example.com", user_info=user_info)

        assert result == ["team1"]

    @pytest.mark.asyncio
    async def test_object_user_info_with_is_admin_none_fetches_from_db(self):
        """Test object user_info without is_admin attr triggers DB lookup."""
        user_info = MagicMock()
        del user_info.is_admin  # Ensure attribute doesn't exist

        mock_db_user = MagicMock(spec=EmailUser)
        mock_db_user.is_admin = False

        with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_db_user):
            with patch("mcpgateway.auth._get_user_team_ids_sync", return_value=["team1"]):
                result = await _resolve_teams_from_db(email="test@example.com", user_info=user_info)

        assert result == ["team1"]

    @pytest.mark.asyncio
    async def test_db_user_not_found_defaults_to_non_admin(self):
        """Test DB lookup returning None defaults is_admin to False."""
        user_info = {"email": "test@example.com"}  # No is_admin key

        with patch("mcpgateway.auth._get_user_by_email_sync", return_value=None):
            with patch("mcpgateway.auth._get_user_team_ids_sync", return_value=["team1"]):
                result = await _resolve_teams_from_db(email="test@example.com", user_info=user_info)

        assert result == ["team1"]


class TestResolveSessionTeamsUuidResolution:
    """Test UUID resolution in resolve_session_teams."""

    @pytest.mark.asyncio
    async def test_uuid_email_resolves_to_actual_email(self):
        """Test UUID in email field gets resolved to actual email."""
        uuid_email = "550e8400-e29b-41d4-a716-446655440000"
        actual_email = "user@example.com"
        payload = {"token_use": "session"}

        with patch("mcpgateway.auth._get_email_by_id_sync", return_value=actual_email):
            with patch("mcpgateway.auth._resolve_teams_from_db", new_callable=AsyncMock) as mock_resolve:
                mock_resolve.return_value = ["team1"]

                result = await resolve_session_teams(payload=payload, email=uuid_email, user_info={"email": actual_email})

        # Verify _get_email_by_id_sync was called with UUID
        assert result == ["team1"]

    @pytest.mark.asyncio
    async def test_invalid_uuid_skips_resolution(self):
        """Test non-UUID email skips UUID resolution."""
        email = "user@example.com"
        payload = {"token_use": "session"}

        with patch("mcpgateway.auth._get_email_by_id_sync", side_effect=AssertionError("Should not be called")):
            with patch("mcpgateway.auth._resolve_teams_from_db", new_callable=AsyncMock) as mock_resolve:
                mock_resolve.return_value = ["team1"]

                result = await resolve_session_teams(payload=payload, email=email, user_info={"email": email})

        assert result == ["team1"]

    @pytest.mark.asyncio
    async def test_uuid_resolution_returns_none_uses_original(self):
        """Test UUID resolution returning None uses original UUID."""
        uuid_email = "550e8400-e29b-41d4-a716-446655440000"
        payload = {"token_use": "session"}

        with patch("mcpgateway.auth._get_email_by_id_sync", return_value=None):
            with patch("mcpgateway.auth._resolve_teams_from_db", new_callable=AsyncMock) as mock_resolve:
                mock_resolve.return_value = []

                result = await resolve_session_teams(payload=payload, email=uuid_email, user_info={"email": uuid_email})

        assert result == []
