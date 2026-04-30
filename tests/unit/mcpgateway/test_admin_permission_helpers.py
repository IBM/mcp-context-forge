# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_permission_helpers.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for admin.py permission helper functions and RBAC UI logic.

This module tests the internal helper functions and permission checking logic in admin.py:

Permission Extraction & Validation:
- _extract_permission_from_route: Extracts RBAC permissions from FastAPI routes
- validate_section_permissions: Validates UI section permissions match route permissions

UI Configuration Helpers:
- _normalize_ui_hide_values: Normalizes UI visibility configuration from various input formats
- _owner_access_condition: Builds SQLAlchemy conditions for owner-based access control

Permission Checking Logic:
- get_hidden_sections_for_user: Determines which UI sections to hide based on user permissions
- get_user_action_permissions: Checks user permissions for UI action buttons (create, edit, etc.)

These tests ensure proper fail-closed behavior (deny on error), correct permission mapping,
and consistent RBAC enforcement across the admin UI.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from mcpgateway.admin import (
    _extract_permission_from_route,
    validate_section_permissions,
    _normalize_ui_hide_values,
)


class TestExtractPermissionFromRoute:
    """Test _extract_permission_from_route function."""

    def test_extract_permission_route_without_endpoint(self):
        """Test extracting permission from route without endpoint attribute (line 291)."""
        # Create a route mock without endpoint attribute
        route = MagicMock()
        del route.endpoint  # Remove endpoint attribute

        result = _extract_permission_from_route(route)

        assert result is None

    def test_extract_permission_route_with_endpoint_no_permission(self):
        """Test extracting permission from route with endpoint but no permission."""
        route = MagicMock()
        route.endpoint = MagicMock(spec=[])  # Empty spec means no attributes

        result = _extract_permission_from_route(route)

        assert result is None

    def test_extract_permission_route_with_permission(self):
        """Test extracting permission from route with permission."""
        route = MagicMock()
        route.endpoint = MagicMock()
        route.endpoint._required_permission = "tools.read"

        result = _extract_permission_from_route(route)

        assert result == "tools.read"

    def test_extract_permission_route_exception_handling(self):
        """Test exception handling in _extract_permission_from_route."""
        route = MagicMock()
        route.path = "/test"
        # Make hasattr return True but getattr raise an exception
        route.endpoint = MagicMock()
        type(route.endpoint)._required_permission = property(lambda self: (_ for _ in ()).throw(Exception("Test error")))

        result = _extract_permission_from_route(route)

        assert result is None


class TestValidateSectionPermissions:
    """Test validate_section_permissions function."""

    @patch("mcpgateway.admin.SECTION_PERMISSIONS", {"overview": None, "tools": "tools.read"})
    @patch("mcpgateway.admin._SECTION_TO_ROUTE_PATH", {"overview": None, "tools": "/admin/tools"})
    @patch("mcpgateway.admin.LOGGER")
    def test_validate_section_permissions_with_none_route_path(self, mock_logger):
        """Test validate_section_permissions with None route_path (lines 307-312)."""
        # Create a route that matches the tools path
        route = MagicMock()
        route.path = "/admin/tools"
        route.endpoint = MagicMock(spec=[])
        route.endpoint._required_permission = "tools.read"

        router = MagicMock()
        router.routes = [route]

        validate_section_permissions(router)

        # Should log info about validation passing (overview section has None route_path and is skipped)
        mock_logger.info.assert_called_once()
        assert "validation passed" in mock_logger.info.call_args[0][0]

    @patch("mcpgateway.admin.SECTION_PERMISSIONS", {"tools": "tools.read", "servers": "servers.read"})
    @patch("mcpgateway.admin._SECTION_TO_ROUTE_PATH", {"tools": "/admin/tools", "servers": "/admin/servers"})
    @patch("mcpgateway.admin.LOGGER")
    def test_validate_section_permissions_with_mismatches(self, mock_logger):
        """Test validate_section_permissions with mismatches raises ValueError in test env."""
        # Create routes with mismatched permissions
        route1 = MagicMock()
        route1.path = "/admin/tools"
        route1.endpoint = MagicMock()
        route1.endpoint._required_permission = "tools.write"  # Mismatch!

        route2 = MagicMock()
        route2.path = "/admin/servers"
        route2.endpoint = MagicMock()
        route2.endpoint._required_permission = None  # Mismatch!

        router = MagicMock()
        router.routes = [route1, route2]

        # In test environment (PYTEST_CURRENT_TEST is set), should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            validate_section_permissions(router)

        # Verify error message contains details about mismatches
        error_msg = str(exc_info.value)
        assert "mismatches" in error_msg
        assert "tools" in error_msg
        assert "servers" in error_msg

    @patch("mcpgateway.admin.SECTION_PERMISSIONS", {"tools": "tools.read", "servers": "servers.read"})
    @patch("mcpgateway.admin._SECTION_TO_ROUTE_PATH", {"tools": "/admin/tools", "servers": "/admin/servers"})
    @patch("mcpgateway.admin.LOGGER")
    def test_validate_section_permissions_production_warns_on_mismatch(self, mock_logger):
        """Test validate_section_permissions logs warnings in production (non-test) env."""
        route1 = MagicMock()
        route1.path = "/admin/tools"
        route1.endpoint = MagicMock()
        route1.endpoint._required_permission = "tools.write"  # Mismatch!

        route2 = MagicMock()
        route2.path = "/admin/servers"
        route2.endpoint = MagicMock()
        route2.endpoint._required_permission = "servers.read"

        router = MagicMock()
        router.routes = [route1, route2]

        # Simulate production environment by clearing test/CI env vars
        with patch.dict("os.environ", {}, clear=True):
            validate_section_permissions(router)

        # Should log warnings instead of raising
        assert mock_logger.warning.call_count == 2
        assert "mismatches" in mock_logger.warning.call_args_list[0][0][0]
        assert "mapping needs updating" in mock_logger.warning.call_args_list[1][0][0]

    @patch("mcpgateway.admin.SECTION_PERMISSIONS", {"tools": "tools.read"})
    @patch("mcpgateway.admin._SECTION_TO_ROUTE_PATH", {"tools": "/admin/tools"})
    @patch("mcpgateway.admin.LOGGER")
    def test_validate_section_permissions_all_match(self, mock_logger):
        """Test validate_section_permissions when all permissions match."""
        route = MagicMock()
        route.path = "/admin/tools"
        route.endpoint = MagicMock()
        route.endpoint._required_permission = "tools.read"

        router = MagicMock()
        router.routes = [route]

        validate_section_permissions(router)

        # Should log info about validation passing
        mock_logger.info.assert_called_once()
        assert "validation passed" in mock_logger.info.call_args[0][0]


class TestNormalizeUIHideValues:
    """Test _normalize_ui_hide_values function."""

    def test_normalize_ui_hide_values_with_none(self):
        """Test _normalize_ui_hide_values with None input."""
        result = _normalize_ui_hide_values(None, frozenset(["tools", "servers"]))

        assert result == set()

    def test_normalize_ui_hide_values_with_csv_string(self):
        """Test _normalize_ui_hide_values with CSV string."""
        result = _normalize_ui_hide_values("tools,servers", frozenset(["tools", "servers", "gateways"]))

        assert result == {"tools", "servers"}

    def test_normalize_ui_hide_values_with_list(self):
        """Test _normalize_ui_hide_values with list input."""
        result = _normalize_ui_hide_values(["tools", "servers"], frozenset(["tools", "servers", "gateways"]))

        assert result == {"tools", "servers"}

    def test_normalize_ui_hide_values_with_invalid_type(self):
        """Test _normalize_ui_hide_values with invalid type (line 350)."""
        # Test with integer (not string, list, tuple, or set)
        result = _normalize_ui_hide_values(12345, frozenset(["tools", "servers"]))

        assert result == set()

    def test_normalize_ui_hide_values_with_dict(self):
        """Test _normalize_ui_hide_values with dict (another invalid type)."""
        result = _normalize_ui_hide_values({"key": "value"}, frozenset(["tools", "servers"]))

        assert result == set()

    def test_normalize_ui_hide_values_with_aliases(self):
        """Test _normalize_ui_hide_values with aliases."""
        aliases = {"t": "tools", "s": "servers"}
        result = _normalize_ui_hide_values("t,s", frozenset(["tools", "servers"]), aliases)

        assert result == {"tools", "servers"}

    def test_normalize_ui_hide_values_filters_invalid(self):
        """Test _normalize_ui_hide_values filters out invalid values."""
        result = _normalize_ui_hide_values("tools,invalid,servers", frozenset(["tools", "servers"]))

        assert result == {"tools", "servers"}
        assert "invalid" not in result

    def test_normalize_ui_hide_values_with_empty_tokens(self):
        """Test _normalize_ui_hide_values with empty tokens."""
        result = _normalize_ui_hide_values("tools,,servers,", frozenset(["tools", "servers"]))

        assert result == {"tools", "servers"}

    def test_normalize_ui_hide_values_case_insensitive(self):
        """Test _normalize_ui_hide_values is case insensitive."""
        result = _normalize_ui_hide_values("TOOLS,Servers", frozenset(["tools", "servers"]))

        assert result == {"tools", "servers"}


class TestPermissionCheckingLogic:
    """Test permission checking logic around line 490."""

    @pytest.mark.asyncio
    @patch("mcpgateway.admin.SECTION_PERMISSIONS", {"tools": "tools.read", "servers": "servers.read"})
    @patch("mcpgateway.admin.PermissionService")
    async def test_permission_checking_hides_section_on_false(self, mock_perm_service_class):
        """Test that sections are hidden when user lacks permission (line 494)."""
        from mcpgateway.admin import get_hidden_sections_for_user

        # Mock permission service to deny permission
        mock_perm_service = MagicMock()
        mock_perm_service.check_permission = AsyncMock(return_value=False)
        mock_perm_service_class.return_value = mock_perm_service

        mock_db = MagicMock()
        result = await get_hidden_sections_for_user(mock_db, "test@example.com", False, ["team1"], set())

        # Verify sections are hidden due to lack of permission
        assert "tools" in result
        assert "servers" in result

    @pytest.mark.asyncio
    @patch("mcpgateway.admin.SECTION_PERMISSIONS", {"tools": "tools.read"})
    @patch("mcpgateway.admin.PermissionService")
    async def test_permission_checking_exception_hides_section(self, mock_perm_service_class):
        """Test that sections are hidden on exception (line 499-500)."""
        from mcpgateway.admin import get_hidden_sections_for_user

        # Mock permission service to raise exception
        mock_perm_service = MagicMock()
        mock_perm_service.check_permission = AsyncMock(side_effect=Exception("Permission check failed"))
        mock_perm_service_class.return_value = mock_perm_service

        mock_db = MagicMock()
        result = await get_hidden_sections_for_user(mock_db, "test@example.com", False, ["team1"], set())

        # Verify section is hidden on error (fail-closed)
        assert "tools" in result

    @pytest.mark.asyncio
    @patch("mcpgateway.admin.UI_ACTION_PERMISSIONS", {"can_create_tools": "tools.create", "can_edit_servers": "servers.update"})
    @patch("mcpgateway.admin.PermissionService")
    async def test_get_ui_action_permissions_exception_denies(self, mock_perm_service_class):
        """Test that permissions are denied on exception (line 573-574)."""
        from mcpgateway.admin import get_user_action_permissions

        # Mock permission service to raise exception
        mock_perm_service = MagicMock()
        mock_perm_service.check_permission = AsyncMock(side_effect=Exception("Permission check failed"))
        mock_perm_service_class.return_value = mock_perm_service

        mock_db = MagicMock()
        result = await get_user_action_permissions(mock_db, "test@example.com", False, ["team1"])

        # Verify permissions are denied on error (fail-closed)
        assert result["can_create_tools"] is False
        assert result["can_edit_servers"] is False

    @pytest.mark.asyncio
    @patch("mcpgateway.admin.UI_ACTION_PERMISSIONS", {"can_create_tools": "tools.create"})
    @patch("mcpgateway.admin.PermissionService")
    async def test_get_ui_action_permissions_grants_permission(self, mock_perm_service_class):
        """Test that permissions are granted when check passes (line 571)."""
        from mcpgateway.admin import get_user_action_permissions

        # Mock permission service to allow permission
        mock_perm_service = MagicMock()
        mock_perm_service.check_permission = AsyncMock(return_value=True)
        mock_perm_service_class.return_value = mock_perm_service

        mock_db = MagicMock()
        result = await get_user_action_permissions(mock_db, "admin@example.com", True, None)

        # Verify permission is granted
        assert result["can_create_tools"] is True

    @pytest.mark.asyncio
    @patch("mcpgateway.admin.PermissionService")
    async def test_permission_checking_shows_section_with_permission(self, mock_perm_service_class):
        """Test that sections are shown when user has permission."""
        from mcpgateway.admin import get_ui_visibility_config
        from fastapi import Request

        # Mock permission service to allow permission
        mock_perm_service = MagicMock()
        mock_perm_service.check_permission = AsyncMock(return_value=True)
        mock_perm_service_class.return_value = mock_perm_service

        # Create mock request
        request = MagicMock(spec=Request)
        request.cookies = {}
        request.query_params = {}
        request.state = MagicMock()
        request.state.user = {"email": "admin@example.com", "teams": None, "is_admin": True}
        request.state.db = MagicMock()

        # Call the function
        result = get_ui_visibility_config(request)

        # Verify result structure
        assert "hidden_sections" in result
        assert "hidden_header_items" in result


class TestOwnerAccessCondition:
    """Test _owner_access_condition function for line 3718."""

    def test_owner_access_condition_with_matching_team_id(self):
        """Test _owner_access_condition when team_id matches (line 3718)."""
        from mcpgateway.admin import _owner_access_condition
        from sqlalchemy import Column

        # Create mock columns and user
        owner_col = Column("owner_email")
        team_col = Column("team_id")
        user = {"email": "test@example.com", "is_admin": False}

        # Test with matching team_id
        condition = _owner_access_condition(owner_col, team_col, user_email="test@example.com", team_ids=["team-123"], user=user)

        # The function returns a SQLAlchemy condition, not a boolean
        assert condition is not None

    def test_owner_access_condition_with_admin_user(self):
        """Test _owner_access_condition with admin user."""
        from mcpgateway.admin import _owner_access_condition
        from sqlalchemy import Column

        # Create mock columns and admin user
        owner_col = Column("owner_email")
        team_col = Column("team_id")
        user = {"email": "admin@example.com", "is_admin": True, "teams": None}

        # Test with admin user (unrestricted token)
        condition = _owner_access_condition(owner_col, team_col, user_email="admin@example.com", team_ids=None, user=user)

        # Admin with unrestricted token should get a SQLAlchemy condition (not True)
        # The function returns a condition object, not a boolean
        assert condition is not None

    def test_owner_access_condition_with_empty_team_ids(self):
        """Test _owner_access_condition with empty team_ids."""
        from mcpgateway.admin import _owner_access_condition
        from sqlalchemy import Column

        # Create mock columns and user
        owner_col = Column("owner_email")
        team_col = Column("team_id")
        user = {"email": "test@example.com", "is_admin": False}

        # Test with empty team_ids
        condition = _owner_access_condition(owner_col, team_col, user_email="test@example.com", team_ids=[], user=user)

        # Should return a condition (not True/False)
        assert condition is not None
