"""Tests for RBAC UI permission checking in admin.py.

Tests the get_user_action_permissions() function and UI_ACTION_PERMISSIONS constant.

Includes regression coverage for issue #3416, where users without
``teams.create`` must not see the team creation action in the admin UI.
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from mcpgateway.admin import get_user_action_permissions, UI_ACTION_PERMISSIONS


class TestUIActionPermissions:
    """Test UI_ACTION_PERMISSIONS constant."""

    def test_ui_action_permissions_structure(self):
        """UI_ACTION_PERMISSIONS should have correct structure."""
        assert isinstance(UI_ACTION_PERMISSIONS, dict)
        assert len(UI_ACTION_PERMISSIONS) == 9  # Only create actions

    def test_ui_action_permissions_keys(self):
        """UI_ACTION_PERMISSIONS should have expected keys."""
        expected_keys = {
            "can_create_team",
            "can_create_server",
            "can_create_tool",
            "can_create_resource",
            "can_create_prompt",
            "can_create_gateway",
            "can_create_user",
            "can_create_token",
            "can_create_agent",
        }
        assert set(UI_ACTION_PERMISSIONS.keys()) == expected_keys

    def test_ui_action_permissions_values(self):
        """UI_ACTION_PERMISSIONS should map to valid RBAC permissions."""
        expected_mappings = {
            "can_create_team": "teams.create",
            "can_create_server": "servers.create",
            "can_create_tool": "tools.create",
            "can_create_resource": "resources.create",
            "can_create_prompt": "prompts.create",
            "can_create_gateway": "gateways.create",
            "can_create_user": "admin.user_management",
            "can_create_token": "tokens.read",
            "can_create_agent": "a2a.create",
        }
        assert UI_ACTION_PERMISSIONS == expected_mappings


class TestGetUserActionPermissions:
    """Test get_user_action_permissions() function."""

    @pytest.mark.asyncio
    async def test_platform_admin_unrestricted_gets_all_permissions(self):
        """Platform admin with unrestricted token (teams=None) gets all permissions."""
        db = Mock()
        result = await get_user_action_permissions(
            db=db,
            user_email="admin@example.com",
            is_admin=True,
            token_teams=None,  # Unrestricted
        )

        # Should get all permissions
        assert len(result) == 9
        assert all(result.values()), "All permissions should be True"
        assert result["can_create_team"] is True
        assert result["can_create_server"] is True
        assert result["can_create_tool"] is True

    @pytest.mark.asyncio
    async def test_platform_admin_with_team_scope_checks_permissions(self):
        """Platform admin with team scope still checks permissions."""
        db = Mock()

        with patch("mcpgateway.admin.PermissionService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service
            mock_service.check_permission = AsyncMock(return_value=True)

            result = await get_user_action_permissions(
                db=db,
                user_email="admin@example.com",
                is_admin=True,
                token_teams=["team1"],  # Scoped
            )

            # Should check permissions (not bypass)
            assert mock_service.check_permission.call_count == 9
            assert all(result.values())

    @pytest.mark.asyncio
    async def test_regular_user_with_all_permissions(self):
        """Regular user with all create permissions gets all flags."""
        db = Mock()

        with patch("mcpgateway.admin.PermissionService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service
            mock_service.check_permission = AsyncMock(return_value=True)

            result = await get_user_action_permissions(
                db=db,
                user_email="user@example.com",
                is_admin=False,
                token_teams=["team1"],
            )

            assert len(result) == 9
            assert all(result.values())
            assert mock_service.check_permission.call_count == 9

    @pytest.mark.asyncio
    async def test_regular_user_with_no_permissions(self):
        """Regular user with no permissions gets all False flags."""
        db = Mock()

        with patch("mcpgateway.admin.PermissionService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service
            mock_service.check_permission = AsyncMock(return_value=False)

            result = await get_user_action_permissions(
                db=db,
                user_email="user@example.com",
                is_admin=False,
                token_teams=["team1"],
            )

            assert len(result) == 9
            assert not any(result.values()), "All permissions should be False"
            assert result["can_create_team"] is False
            assert result["can_create_server"] is False

    @pytest.mark.asyncio
    async def test_regular_user_with_partial_permissions(self):
        """Regular user with some permissions gets mixed flags."""
        db = Mock()

        # Mock permission service to grant only teams.create and tools.create
        def check_permission_side_effect(user_email, permission, token_teams, allow_admin_bypass, check_any_team):
            return permission in ["teams.create", "tools.create"]

        with patch("mcpgateway.admin.PermissionService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service
            mock_service.check_permission = AsyncMock(side_effect=check_permission_side_effect)

            result = await get_user_action_permissions(
                db=db,
                user_email="user@example.com",
                is_admin=False,
                token_teams=["team1"],
            )

            assert result["can_create_team"] is True
            assert result["can_create_tool"] is True
            assert result["can_create_server"] is False
            assert result["can_create_resource"] is False
            assert result["can_create_prompt"] is False

    @pytest.mark.asyncio
    async def test_public_only_token_scope(self):
        """User with public-only token scope (teams=[]) gets limited permissions."""
        db = Mock()

        with patch("mcpgateway.admin.PermissionService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service
            mock_service.check_permission = AsyncMock(return_value=False)

            result = await get_user_action_permissions(
                db=db,
                user_email="user@example.com",
                is_admin=False,
                token_teams=[],  # Public-only
            )

            assert len(result) == 9
            assert not any(result.values())

    @pytest.mark.asyncio
    async def test_permission_check_error_fails_closed(self):
        """Permission check errors should fail closed (deny permission)."""
        db = Mock()

        with patch("mcpgateway.admin.PermissionService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service
            mock_service.check_permission = AsyncMock(side_effect=Exception("DB error"))

            result = await get_user_action_permissions(
                db=db,
                user_email="user@example.com",
                is_admin=False,
                token_teams=["team1"],
            )

            # All permissions should be False due to errors
            assert len(result) == 9
            assert not any(result.values()), "Should fail closed on errors"

    @pytest.mark.asyncio
    async def test_permission_service_called_with_correct_params(self):
        """Permission service should be called with correct parameters."""
        db = Mock()

        with patch("mcpgateway.admin.PermissionService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service
            mock_service.check_permission = AsyncMock(return_value=True)

            await get_user_action_permissions(
                db=db,
                user_email="user@example.com",
                is_admin=False,
                token_teams=["team1", "team2"],
            )

            # Verify service initialization
            mock_service_class.assert_called_once_with(db, audit_enabled=False)

            # Verify check_permission calls
            assert mock_service.check_permission.call_count == 9

            # Check first call parameters
            first_call = mock_service.check_permission.call_args_list[0]
            assert first_call.kwargs["user_email"] == "user@example.com"
            assert first_call.kwargs["token_teams"] == ["team1", "team2"]
            assert first_call.kwargs["allow_admin_bypass"] is False
            assert first_call.kwargs["check_any_team"] is True

    @pytest.mark.asyncio
    async def test_all_permission_flags_checked(self):
        """All 9 permission flags should be checked."""
        db = Mock()

        with patch("mcpgateway.admin.PermissionService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service

            checked_permissions = []
            async def track_permission(user_email, permission, token_teams, allow_admin_bypass, check_any_team):
                checked_permissions.append(permission)
                return True

            mock_service.check_permission = AsyncMock(side_effect=track_permission)

            result = await get_user_action_permissions(
                db=db,
                user_email="user@example.com",
                is_admin=False,
                token_teams=["team1"],
            )

            # Verify all expected permissions were checked
            expected_permissions = {
                "teams.create",
                "servers.create",
                "tools.create",
                "resources.create",
                "prompts.create",
                "gateways.create",
                "admin.user_management",
                "tokens.read",
                "a2a.create",
            }
            assert set(checked_permissions) == expected_permissions
            assert len(result) == 9

    @pytest.mark.asyncio
    async def test_mixed_permission_errors(self):
        """Some permissions succeed, some fail - should handle gracefully."""
        db = Mock()

        call_count = 0
        async def mixed_results(user_email, permission, token_teams, allow_admin_bypass, check_any_team):
            nonlocal call_count
            call_count += 1
            if call_count % 3 == 0:
                raise Exception("Intermittent error")
            return call_count % 2 == 0

        with patch("mcpgateway.admin.PermissionService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service
            mock_service.check_permission = AsyncMock(side_effect=mixed_results)

            result = await get_user_action_permissions(
                db=db,
                user_email="user@example.com",
                is_admin=False,
                token_teams=["team1"],
            )

            # Should have results for all 9 permissions
            assert len(result) == 9
            # Some should be True, some False (from errors)
            assert any(result.values()), "Some permissions should succeed"
            assert not all(result.values()), "Some permissions should fail"
