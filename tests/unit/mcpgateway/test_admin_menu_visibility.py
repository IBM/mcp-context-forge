# -*- coding: utf-8 -*-
"""Unit tests for permission-based menu visibility in admin UI.

Tests the get_hidden_sections_for_user function that determines which
menu sections should be hidden based on user RBAC permissions.
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from mcpgateway.admin import get_hidden_sections_for_user, SECTION_PERMISSIONS


@pytest.mark.asyncio
async def test_platform_admin_unrestricted_sees_all_sections():
    """Platform admin with unrestricted token (token_teams=None) sees all sections."""
    db = Mock()
    static_hidden = set()

    result = await get_hidden_sections_for_user(
        db=db,
        user_email="admin@example.com",
        is_admin=True,
        token_teams=None,  # Unrestricted admin token
        static_hidden=static_hidden,
    )

    # Should only return static hidden sections (none in this case)
    assert result == set()


@pytest.mark.asyncio
async def test_static_hidden_sections_always_hidden():
    """Sections in static_hidden are always hidden regardless of permissions."""
    db = Mock()
    static_hidden = {"tools", "servers"}

    with patch("mcpgateway.admin.PermissionService") as mock_service_class:
        mock_service = Mock()
        mock_service.check_permission = AsyncMock(return_value=True)
        mock_service_class.return_value = mock_service

        result = await get_hidden_sections_for_user(
            db=db,
            user_email="user@example.com",
            is_admin=False,
            token_teams=["team1"],
            static_hidden=static_hidden,
        )

    # Static hidden sections should be in result
    assert "tools" in result
    assert "servers" in result


@pytest.mark.asyncio
async def test_developer_sees_core_sections_hides_admin_sections():
    """Developer role sees core sections but admin sections are hidden."""
    db = Mock()
    static_hidden = set()

    # Mock permission service to grant core permissions, deny admin permissions
    with patch("mcpgateway.admin.PermissionService") as mock_service_class:
        mock_service = Mock()

        async def check_permission_side_effect(user_email, permission, **kwargs):
            # Grant core permissions
            if permission in ["tools.read", "servers.read", "resources.read", "prompts.read", "gateways.read"]:
                return True
            # Deny admin permissions
            if permission.startswith("admin."):
                return False
            return False

        mock_service.check_permission = AsyncMock(side_effect=check_permission_side_effect)
        mock_service_class.return_value = mock_service

        result = await get_hidden_sections_for_user(
            db=db,
            user_email="developer@example.com",
            is_admin=False,
            token_teams=["team1"],
            static_hidden=static_hidden,
        )

    # Core sections should NOT be hidden
    assert "tools" not in result
    assert "servers" not in result
    assert "resources" not in result
    assert "prompts" not in result
    assert "gateways" not in result

    # Admin sections SHOULD be hidden
    assert "users" in result
    assert "maintenance" in result
    assert "logs" in result
    assert "export-import" in result
    assert "plugins" in result
    assert "metrics" in result


@pytest.mark.asyncio
async def test_viewer_sees_only_read_sections():
    """Viewer role sees only read-only sections."""
    db = Mock()
    static_hidden = set()

    with patch("mcpgateway.admin.PermissionService") as mock_service_class:
        mock_service = Mock()

        async def check_permission_side_effect(user_email, permission, **kwargs):
            # Grant only read permissions for core sections
            if permission in ["tools.read", "resources.read", "prompts.read"]:
                return True
            return False

        mock_service.check_permission = AsyncMock(side_effect=check_permission_side_effect)
        mock_service_class.return_value = mock_service

        result = await get_hidden_sections_for_user(
            db=db,
            user_email="viewer@example.com",
            is_admin=False,
            token_teams=["team1"],
            static_hidden=static_hidden,
        )

    # Sections with granted permissions should NOT be hidden
    assert "tools" not in result
    assert "resources" not in result
    assert "prompts" not in result

    # Sections without permissions SHOULD be hidden
    assert "servers" in result
    assert "gateways" in result
    assert "users" in result
    assert "maintenance" in result


@pytest.mark.asyncio
async def test_public_only_token_hides_admin_sections():
    """Public-only token (token_teams=[]) hides admin sections."""
    db = Mock()
    static_hidden = set()

    with patch("mcpgateway.admin.PermissionService") as mock_service_class:
        mock_service = Mock()

        async def check_permission_side_effect(user_email, permission, **kwargs):
            # Public-only tokens should not have admin permissions
            if permission.startswith("admin."):
                return False
            # Grant some core permissions
            if permission in ["tools.read", "servers.read"]:
                return True
            return False

        mock_service.check_permission = AsyncMock(side_effect=check_permission_side_effect)
        mock_service_class.return_value = mock_service

        result = await get_hidden_sections_for_user(
            db=db,
            user_email="user@example.com",
            is_admin=False,
            token_teams=[],  # Public-only token
            static_hidden=static_hidden,
        )

    # Admin sections should be hidden
    assert "users" in result
    assert "maintenance" in result
    assert "logs" in result


@pytest.mark.asyncio
async def test_permission_check_error_hides_section():
    """If permission check raises error, section is hidden (fail-closed)."""
    db = Mock()
    static_hidden = set()

    with patch("mcpgateway.admin.PermissionService") as mock_service_class:
        mock_service = Mock()
        mock_service.check_permission = AsyncMock(side_effect=Exception("Database error"))
        mock_service_class.return_value = mock_service

        result = await get_hidden_sections_for_user(
            db=db,
            user_email="user@example.com",
            is_admin=False,
            token_teams=["team1"],
            static_hidden=static_hidden,
        )

    # All sections with required permissions should be hidden due to errors
    for section, permission in SECTION_PERMISSIONS.items():
        if permission is not None:  # Sections with permission requirements
            assert section in result


@pytest.mark.asyncio
async def test_sections_without_permission_requirement_not_hidden():
    """Sections with no permission requirement (None) are never hidden by permission checks."""
    db = Mock()
    static_hidden = set()

    with patch("mcpgateway.admin.PermissionService") as mock_service_class:
        mock_service = Mock()
        mock_service.check_permission = AsyncMock(return_value=False)  # Deny all
        mock_service_class.return_value = mock_service

        result = await get_hidden_sections_for_user(
            db=db,
            user_email="user@example.com",
            is_admin=False,
            token_teams=["team1"],
            static_hidden=static_hidden,
        )

    # Sections with None permission should NOT be hidden
    for section, permission in SECTION_PERMISSIONS.items():
        if permission is None:
            assert section not in result


@pytest.mark.asyncio
async def test_team_admin_sees_team_sections():
    """Team admin sees team management sections."""
    db = Mock()
    static_hidden = set()

    with patch("mcpgateway.admin.PermissionService") as mock_service_class:
        mock_service = Mock()

        async def check_permission_side_effect(user_email, permission, **kwargs):
            # Grant team and core permissions
            if permission in ["teams.read", "tokens.read", "tools.read", "servers.read", "resources.read"]:
                return True
            # Deny admin permissions
            if permission.startswith("admin."):
                return False
            return False

        mock_service.check_permission = AsyncMock(side_effect=check_permission_side_effect)
        mock_service_class.return_value = mock_service

        result = await get_hidden_sections_for_user(
            db=db,
            user_email="teamadmin@example.com",
            is_admin=False,
            token_teams=["team1"],
            static_hidden=static_hidden,
        )

    # Team sections should NOT be hidden
    assert "teams" not in result
    assert "tokens" not in result

    # Core sections should NOT be hidden
    assert "tools" not in result
    assert "servers" not in result

    # Admin sections SHOULD be hidden
    assert "users" in result
    assert "maintenance" in result


@pytest.mark.asyncio
async def test_combined_static_and_permission_hiding():
    """Static hidden sections and permission-based hiding work together."""
    db = Mock()
    static_hidden = {"metrics", "plugins"}  # Statically hidden

    with patch("mcpgateway.admin.PermissionService") as mock_service_class:
        mock_service = Mock()

        async def check_permission_side_effect(user_email, permission, **kwargs):
            # Grant only tools.read
            if permission == "tools.read":
                return True
            return False

        mock_service.check_permission = AsyncMock(side_effect=check_permission_side_effect)
        mock_service_class.return_value = mock_service

        result = await get_hidden_sections_for_user(
            db=db,
            user_email="user@example.com",
            is_admin=False,
            token_teams=["team1"],
            static_hidden=static_hidden,
        )

    # Static hidden sections should be in result
    assert "metrics" in result
    assert "plugins" in result

    # Permission-denied sections should be in result
    assert "servers" in result
    assert "users" in result

    # Permission-granted section should NOT be in result
    assert "tools" not in result
