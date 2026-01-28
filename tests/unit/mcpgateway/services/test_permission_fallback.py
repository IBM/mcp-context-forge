# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_permission_fallback.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test permission fallback functionality for regular users.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.services.permission_service import PermissionService


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock(spec=Session)
    return session


@pytest.fixture
def permission_service(mock_db_session):
    """Create permission service instance with mock dependencies."""
    return PermissionService(mock_db_session, audit_enabled=False)


class TestPermissionFallback:
    """Test permission fallback functionality for team management."""

    @pytest.mark.asyncio
    async def test_admin_user_bypasses_all_checks(self, permission_service):
        """Test that admin users bypass all permission checks."""
        with patch.object(permission_service, "_is_user_admin", return_value=True):
            # Admin should have access to any permission
            assert await permission_service.check_permission("admin@example.com", "teams.create") == True
            assert await permission_service.check_permission("admin@example.com", "teams.delete", team_id="team-123") == True
            assert await permission_service.check_permission("admin@example.com", "any.permission") == True

    @pytest.mark.asyncio
    async def test_team_create_permission_for_regular_users(self, permission_service):
        """Test that regular users can create teams."""
        with patch.object(permission_service, "_is_user_admin", return_value=False), patch.object(permission_service, "get_user_permissions", return_value=set()):
            # Regular user should be able to create teams (global permission)
            assert await permission_service.check_permission("user@example.com", "teams.create") == True

    @pytest.mark.asyncio
    async def test_team_owner_permissions(self, permission_service):
        """Test that team owners have full permissions on their teams."""
        with (
            patch.object(permission_service, "_is_user_admin", return_value=False),
            patch.object(permission_service, "get_user_permissions", return_value=set()),
            patch.object(permission_service, "_is_team_member", return_value=True),
            patch.object(permission_service, "_get_user_team_role", return_value="owner"),
        ):
            # Team owner should have full permissions on their team
            assert await permission_service.check_permission("owner@example.com", "teams.read", team_id="team-123") == True
            assert await permission_service.check_permission("owner@example.com", "teams.update", team_id="team-123") == True
            assert await permission_service.check_permission("owner@example.com", "teams.delete", team_id="team-123") == True
            assert await permission_service.check_permission("owner@example.com", "teams.manage_members", team_id="team-123") == True

    @pytest.mark.asyncio
    async def test_team_member_permissions(self, permission_service):
        """Test that team members have read permissions on their teams."""
        with (
            patch.object(permission_service, "_is_user_admin", return_value=False),
            patch.object(permission_service, "get_user_permissions", return_value=set()),
            patch.object(permission_service, "_is_team_member", return_value=True),
            patch.object(permission_service, "_get_user_team_role", return_value="member"),
        ):
            # Team member should have read permissions
            assert await permission_service.check_permission("member@example.com", "teams.read", team_id="team-123") == True

            # But not management permissions
            assert await permission_service.check_permission("member@example.com", "teams.update", team_id="team-123") == False
            assert await permission_service.check_permission("member@example.com", "teams.delete", team_id="team-123") == False
            assert await permission_service.check_permission("member@example.com", "teams.manage_members", team_id="team-123") == False

    @pytest.mark.asyncio
    async def test_non_team_member_denied(self, permission_service):
        """Test that non-team members are denied team-specific permissions."""
        with (
            patch.object(permission_service, "_is_user_admin", return_value=False),
            patch.object(permission_service, "get_user_permissions", return_value=set()),
            patch.object(permission_service, "_is_team_member", return_value=False),
        ):
            # Non-member should be denied all team-specific permissions
            assert await permission_service.check_permission("outsider@example.com", "teams.read", team_id="team-123") == False
            assert await permission_service.check_permission("outsider@example.com", "teams.update", team_id="team-123") == False
            assert await permission_service.check_permission("outsider@example.com", "teams.manage_members", team_id="team-123") == False

    @pytest.mark.asyncio
    async def test_explicit_rbac_permissions_override_fallback(self, permission_service):
        """Test that explicit RBAC permissions override fallback logic."""
        # User has explicit RBAC permission
        with patch.object(permission_service, "_is_user_admin", return_value=False), patch.object(permission_service, "get_user_permissions", return_value={"teams.manage_members"}):
            # Should get permission from RBAC, not fallback
            assert await permission_service.check_permission("rbac_user@example.com", "teams.manage_members", team_id="team-123") == True

            # Fallback should not be checked when RBAC grants permission

    @pytest.mark.asyncio
    async def test_platform_admin_virtual_user_recognition(self, permission_service):
        """Test that platform admin virtual user is recognized by RBAC checks."""
        # First-Party
        from mcpgateway.config import settings

        platform_admin_email = getattr(settings, "platform_admin_email", "admin@example.com")

        # Mock database query to return None (user not in database)
        with patch.object(permission_service.db, "execute") as mock_execute:
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None  # User not found in DB
            mock_execute.return_value = mock_result

            # _is_user_admin should still return True for platform admin email
            result = await permission_service._is_user_admin(platform_admin_email)
            assert result == True, "Platform admin should be recognized even when not in database"

    @pytest.mark.asyncio
    async def test_platform_admin_check_admin_permission(self, permission_service):
        """Test that platform admin passes check_admin_permission even when virtual."""
        # First-Party
        from mcpgateway.config import settings

        platform_admin_email = getattr(settings, "platform_admin_email", "admin@example.com")

        # Mock _is_user_admin to return True (our fix working)
        with patch.object(permission_service, "_is_user_admin", return_value=True):
            result = await permission_service.check_admin_permission(platform_admin_email)
            assert result == True, "Platform admin should have admin permissions"

    @pytest.mark.asyncio
    async def test_non_platform_admin_virtual_user_not_recognized(self, permission_service):
        """Test that non-platform admin users don't get virtual admin privileges."""
        # Mock database query to return None (user not in database)
        with patch.object(permission_service.db, "execute") as mock_execute:
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None  # User not found in DB
            mock_execute.return_value = mock_result

            # Non-platform admin should return False
            result = await permission_service._is_user_admin("random@example.com")
            assert result == False, "Non-platform admin should not get virtual admin privileges"

    @pytest.mark.asyncio
    async def test_platform_admin_edge_case_empty_setting(self, permission_service):
        """Test behavior when platform_admin_email setting is empty."""
        # Mock database query to return None
        with patch.object(permission_service.db, "execute") as mock_execute:
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_execute.return_value = mock_result

            # Mock empty platform admin email setting
            with patch("mcpgateway.services.permission_service.getattr", return_value=""):
                result = await permission_service._is_user_admin("admin@example.com")
                assert result == False, "Should not grant admin privileges when platform_admin_email is empty"


class TestTokenPermissionFallback:
    """Test permission fallback functionality for token management."""

    @pytest.mark.asyncio
    async def test_regular_user_can_create_tokens(self, permission_service):
        """Test that regular users can create their own tokens."""
        with patch.object(permission_service, "_is_user_admin", return_value=False), patch.object(permission_service, "get_user_permissions", return_value=set()):
            # Regular user should be able to create tokens
            assert await permission_service.check_permission("user@example.com", "tokens.create") is True

    @pytest.mark.asyncio
    async def test_regular_user_can_read_tokens(self, permission_service):
        """Test that regular users can read their own tokens."""
        with patch.object(permission_service, "_is_user_admin", return_value=False), patch.object(permission_service, "get_user_permissions", return_value=set()):
            # Regular user should be able to read tokens
            assert await permission_service.check_permission("user@example.com", "tokens.read") is True

    @pytest.mark.asyncio
    async def test_regular_user_can_revoke_tokens(self, permission_service):
        """Test that regular users can revoke their own tokens."""
        with patch.object(permission_service, "_is_user_admin", return_value=False), patch.object(permission_service, "get_user_permissions", return_value=set()):
            # Regular user should be able to revoke tokens
            assert await permission_service.check_permission("user@example.com", "tokens.revoke") is True

    @pytest.mark.asyncio
    async def test_regular_user_can_update_tokens(self, permission_service):
        """Test that regular users can update their own tokens."""
        with patch.object(permission_service, "_is_user_admin", return_value=False), patch.object(permission_service, "get_user_permissions", return_value=set()):
            # Regular user should be able to update tokens
            assert await permission_service.check_permission("user@example.com", "tokens.update") is True

    @pytest.mark.asyncio
    async def test_admin_user_has_all_token_permissions(self, permission_service):
        """Test that admin users have all token permissions."""
        with patch.object(permission_service, "_is_user_admin", return_value=True):
            # Admin should have all permissions
            assert await permission_service.check_permission("admin@example.com", "tokens.create") is True
            assert await permission_service.check_permission("admin@example.com", "tokens.read") is True
            assert await permission_service.check_permission("admin@example.com", "tokens.update") is True
            assert await permission_service.check_permission("admin@example.com", "tokens.revoke") is True
