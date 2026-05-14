# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_auth_coverage.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Additional tests for auth.py coverage gaps.

This module contains targeted tests for specific uncovered lines in mcpgateway/auth.py
to achieve 100% coverage.
"""

# Third-Party
import pytest


class TestGetTeamNameByIdSync:
    """Tests for _get_team_name_by_id_sync function."""

    def test_get_team_name_none_team_id_line_206(self):
        """Test _get_team_name_by_id_sync with None team_id (line 206)."""
        # First-Party
        from mcpgateway.auth import _get_team_name_by_id_sync

        # Should return None immediately for None team_id
        result = _get_team_name_by_id_sync(None)
        assert result is None

    def test_get_team_name_empty_team_id_line_206(self):
        """Test _get_team_name_by_id_sync with empty string team_id (line 206)."""
        # First-Party
        from mcpgateway.auth import _get_team_name_by_id_sync

        # Should return None immediately for empty team_id
        result = _get_team_name_by_id_sync("")
        assert result is None


class TestExtractClaimTeamName:
    """Tests for _extract_claim_team_name function."""

    def test_extract_claim_none_team_id_line_221(self):
        """Test _extract_claim_team_name with None team_id (line 221)."""
        # First-Party
        from mcpgateway.auth import _extract_claim_team_name

        payload = {"teams": [{"id": "team-1", "name": "Team One"}]}

        # Should return None immediately for None team_id
        result = _extract_claim_team_name(payload, None)
        assert result is None

    def test_extract_claim_teams_not_list_line_235(self):
        """Test _extract_claim_team_name when teams is not a list (line 235)."""
        # First-Party
        from mcpgateway.auth import _extract_claim_team_name

        # teams is a string instead of list
        payload = {"teams": "not-a-list"}

        result = _extract_claim_team_name(payload, "team-1")
        assert result is None

    def test_extract_claim_teams_is_dict_line_235(self):
        """Test _extract_claim_team_name when teams is a dict (line 235)."""
        # First-Party
        from mcpgateway.auth import _extract_claim_team_name

        # teams is a dict instead of list
        payload = {"teams": {"id": "team-1"}}

        result = _extract_claim_team_name(payload, "team-1")
        assert result is None

    def test_extract_claim_team_string_format_line_239(self):
        """Test _extract_claim_team_name with string team format (line 239)."""
        # First-Party
        from mcpgateway.auth import _extract_claim_team_name

        # Team as string (not dict)
        payload = {"teams": ["team-1", "team-2"]}

        # Should handle string format but return None (no name available)
        result = _extract_claim_team_name(payload, "team-1")
        assert result is None

    def test_extract_claim_team_name_none_line_251(self):
        """Test _extract_claim_team_name when team name is None (line 251)."""
        # First-Party
        from mcpgateway.auth import _extract_claim_team_name

        # Team dict with id but name is None
        payload = {"teams": [{"id": "team-1", "name": None}]}

        result = _extract_claim_team_name(payload, "team-1")
        assert result is None

    def test_extract_claim_team_name_empty_string_line_259(self):
        """Test _extract_claim_team_name when normalized name is empty (line 259)."""
        # First-Party
        from mcpgateway.auth import _extract_claim_team_name

        # Team dict with id and name that becomes empty after strip
        payload = {"teams": [{"id": "team-1", "name": "   "}]}

        result = _extract_claim_team_name(payload, "team-1")
        assert result is None


class TestJWTScopesValidation:
    """Tests for JWT scopes field validation in auth.py lines 1789-1798."""

    @pytest.mark.asyncio
    async def test_scopes_dict_with_permissions_line_1789_1790(self):
        """Test JWT with scopes as dict containing permissions list (lines 1789-1790)."""
        # Standard
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch

        # Third-Party
        from fastapi.security import HTTPAuthorizationCredentials

        # First-Party
        from mcpgateway.auth import get_current_user
        from mcpgateway.db import EmailUser

        # Mock request
        request = SimpleNamespace()
        request.state = SimpleNamespace()
        request.headers = {}
        request.cookies = {}

        # Mock credentials
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")

        # Mock JWT payload with scopes dict containing permissions
        jwt_payload = {
            "sub": "user@example.com",
            "scopes": {"permissions": ["tools.read", "a2a.execute"]},
            "exp": 9999999999,
        }

        # Mock user
        mock_user = EmailUser(email="user@example.com", is_admin=False, is_active=True)

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._check_token_revoked_sync", return_value=False),
        ):
            user = await get_current_user(credentials=credentials, request=request)

            # Verify token_scopes is set correctly on request.state
            assert hasattr(request.state, "token_scopes")
            assert request.state.token_scopes == ["tools.read", "a2a.execute"]
            assert user.email == "user@example.com"

    @pytest.mark.asyncio
    async def test_scopes_dict_without_permissions_key_line_1790_1793(self):
        """Test JWT with scopes dict but no permissions key (lines 1790, 1793)."""
        # Standard
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch

        # Third-Party
        from fastapi.security import HTTPAuthorizationCredentials

        # First-Party
        from mcpgateway.auth import get_current_user
        from mcpgateway.db import EmailUser

        # Mock request
        request = SimpleNamespace()
        request.state = SimpleNamespace()
        request.headers = {}
        request.cookies = {}

        # Mock credentials
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")

        # Mock JWT payload with scopes dict but no permissions key
        jwt_payload = {
            "sub": "user@example.com",
            "scopes": {"server_id": "srv-123"},  # Has scopes dict but no permissions
            "exp": 9999999999,
        }

        # Mock user
        mock_user = EmailUser(email="user@example.com", is_admin=False, is_active=True)

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._check_token_revoked_sync", return_value=False),
        ):
            user = await get_current_user(credentials=credentials, request=request)

            # Verify token_scopes is set to empty list (enforces scope checks, denies all)
            assert hasattr(request.state, "token_scopes")
            assert request.state.token_scopes == []
            assert user.email == "user@example.com"

    @pytest.mark.asyncio
    async def test_malformed_scopes_string_line_1797_1798(self):
        """Test JWT with malformed scopes (string instead of dict) raises 401 (lines 1797-1798)."""
        # Standard
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch

        # Third-Party
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials
        import pytest

        # First-Party
        from mcpgateway.auth import get_current_user

        # Mock request
        request = SimpleNamespace()
        request.state = SimpleNamespace()
        request.headers = {}
        request.cookies = {}

        # Mock credentials
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")

        # Mock JWT payload with malformed scopes (string instead of dict)
        jwt_payload = {
            "sub": "user@example.com",
            "scopes": "tools.read,a2a.execute",  # MALFORMED: should be dict
            "exp": 9999999999,
        }

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=credentials, request=request)

            # Verify 401 error is raised
            assert exc_info.value.status_code == 401
            assert "malformed scopes field" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_malformed_scopes_list_line_1797_1798(self):
        """Test JWT with malformed scopes (list instead of dict) raises 401 (lines 1797-1798)."""
        # Standard
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch

        # Third-Party
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials
        import pytest

        # First-Party
        from mcpgateway.auth import get_current_user

        # Mock request
        request = SimpleNamespace()
        request.state = SimpleNamespace()
        request.headers = {}
        request.cookies = {}

        # Mock credentials
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")

        # Mock JWT payload with malformed scopes (list instead of dict)
        jwt_payload = {
            "sub": "user@example.com",
            "scopes": ["tools.read", "a2a.execute"],  # MALFORMED: should be dict
            "exp": 9999999999,
        }

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=credentials, request=request)

            # Verify 401 error is raised
            assert exc_info.value.status_code == 401
            assert "malformed scopes field" in str(exc_info.value.detail)


# Note: Lines 993-994, 1006, and 1011 are inside get_current_user function
# which is complex to test in isolation. These lines are covered by existing
# integration tests in test_auth.py. The helper functions above provide
# sufficient coverage for the simpler utility functions.
