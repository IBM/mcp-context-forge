# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_menu_visibility.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for permission-based menu visibility in admin UI.

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


@pytest.mark.asyncio
async def test_batch_permission_path_used_when_available():
    """When get_user_permissions() returns a set, batch in-memory checks are used."""
    db = Mock()
    static_hidden = set()

    with patch("mcpgateway.admin.PermissionService") as mock_service_class:
        mock_service = Mock()
        # Return an awaitable set of permissions from get_user_permissions
        mock_service.get_user_permissions = AsyncMock(return_value={"tools.read", "servers.read", "resources.read"})
        # check_permission should NOT be called when batch path succeeds
        mock_service.check_permission = AsyncMock(return_value=False)
        mock_service_class.return_value = mock_service

        result = await get_hidden_sections_for_user(
            db=db,
            user_email="user@example.com",
            is_admin=False,
            token_teams=["team1"],
            static_hidden=static_hidden,
        )

    # Batch path should have been used - check_permission should not be called
    mock_service.check_permission.assert_not_called()

    # Sections with granted permissions should NOT be hidden
    assert "tools" not in result
    assert "servers" not in result
    assert "resources" not in result

    # Sections without granted permissions SHOULD be hidden
    assert "users" in result
    assert "maintenance" in result
    assert "plugins" in result


@pytest.mark.asyncio
async def test_batch_permission_path_wildcard_grants_all():
    """When get_user_permissions() returns '*', all sections are visible."""
    db = Mock()
    static_hidden = set()

    with patch("mcpgateway.admin.PermissionService") as mock_service_class:
        mock_service = Mock()
        mock_service.get_user_permissions = AsyncMock(return_value={"*"})
        mock_service.check_permission = AsyncMock(return_value=False)
        mock_service_class.return_value = mock_service

        result = await get_hidden_sections_for_user(
            db=db,
            user_email="admin@example.com",
            is_admin=False,
            token_teams=["team1"],
            static_hidden=static_hidden,
        )

    # Wildcard should grant all permissions - no sections hidden
    assert result == set()


@pytest.mark.asyncio
async def test_batch_permission_fallback_on_exception():
    """When get_user_permissions() raises, falls back to per-section check_permission."""
    db = Mock()
    static_hidden = set()

    with patch("mcpgateway.admin.PermissionService") as mock_service_class:
        mock_service = Mock()
        # get_user_permissions raises, triggering fallback
        mock_service.get_user_permissions = AsyncMock(side_effect=Exception("Not implemented"))
        mock_service.check_permission = AsyncMock(return_value=True)
        mock_service_class.return_value = mock_service

        result = await get_hidden_sections_for_user(
            db=db,
            user_email="user@example.com",
            is_admin=False,
            token_teams=["team1"],
            static_hidden=static_hidden,
        )

    # Fallback to check_permission should have been used
    assert mock_service.check_permission.call_count > 0
    # All permissions granted via fallback
    assert result == set()


@pytest.mark.asyncio
async def test_batch_path_denies_admin_perms_for_public_only_token():
    """Public-only token (token_teams=[]) must not satisfy admin.* perms via batch path."""
    db = Mock()
    static_hidden = set()

    with patch("mcpgateway.admin.PermissionService") as mock_service_class:
        mock_service = Mock()
        # Batch path returns admin permissions, but token is public-only
        mock_service.get_user_permissions = AsyncMock(return_value={"admin.system_config", "tools.read", "*"})
        mock_service.check_permission = AsyncMock(return_value=False)
        mock_service_class.return_value = mock_service

        result = await get_hidden_sections_for_user(
            db=db,
            user_email="user@example.com",
            is_admin=False,
            token_teams=[],  # Public-only
            static_hidden=static_hidden,
        )

    # Admin sections should be hidden despite having admin.* and * in permissions
    assert "users" in result
    assert "maintenance" in result
    assert "logs" in result
    assert "plugins" in result

    # Non-admin sections should still be visible (wildcard grants them)
    assert "tools" not in result
    assert "servers" not in result


@pytest.mark.asyncio
async def test_none_permission_sections_never_hidden():
    """Sections mapped to None permission are never hidden by permission checks."""
    db = Mock()
    static_hidden = set()

    with patch("mcpgateway.admin.SECTION_PERMISSIONS", {"visible_section": None, "tools": "tools.read"}):
        with patch("mcpgateway.admin.PermissionService") as mock_service_class:
            mock_service = Mock()
            mock_service.get_user_permissions = AsyncMock(return_value=set())  # No permissions
            mock_service.check_permission = AsyncMock(return_value=False)
            mock_service_class.return_value = mock_service

            result = await get_hidden_sections_for_user(
                db=db,
                user_email="user@example.com",
                is_admin=False,
                token_teams=["team1"],
                static_hidden=static_hidden,
            )

    # None-permission section should NOT be hidden
    assert "visible_section" not in result
    # Section with denied permission should be hidden
    assert "tools" in result


def test_section_permissions_uses_valid_permissions():
    """All permissions in SECTION_PERMISSIONS must exist in the Permissions class."""
    from mcpgateway.db import Permissions

    # Collect all permission strings defined in the Permissions class
    defined_permissions = set()
    for attr_name in dir(Permissions):
        val = getattr(Permissions, attr_name)
        if isinstance(val, str) and not attr_name.startswith("_"):
            defined_permissions.add(val)

    for section, permission in SECTION_PERMISSIONS.items():
        if permission is None:
            continue
        assert permission in defined_permissions, (
            f"SECTION_PERMISSIONS['{section}'] = '{permission}' is not defined in Permissions class. "
            f"Available admin permissions: {sorted(p for p in defined_permissions if p.startswith('admin.'))}"
        )


def test_grpc_services_has_separate_section_permission():
    """gRPC services must have its own section, not bundled with A2A agents."""
    assert "grpc-services" in SECTION_PERMISSIONS, "grpc-services must be a separate section"
    assert "agents" in SECTION_PERMISSIONS, "agents (A2A) must be a separate section"
    assert SECTION_PERMISSIONS["grpc-services"] == "admin.grpc", "gRPC must require admin.grpc"
    assert SECTION_PERMISSIONS["agents"] == "a2a.read", "agents must require a2a.read"


def test_roots_permission_matches_routes():
    """Roots section must use admin.system_config, matching its route decorators."""
    assert SECTION_PERMISSIONS["roots"] == "admin.system_config"


def test_grpc_services_is_hidable_section():
    """grpc-services must be a first-class hidable section, not an alias."""
    from mcpgateway.config import UI_HIDABLE_SECTIONS, UI_HIDE_SECTION_ALIASES

    assert "grpc-services" in UI_HIDABLE_SECTIONS, "grpc-services must be in UI_HIDABLE_SECTIONS"
    assert "grpc-services" not in UI_HIDE_SECTION_ALIASES, "grpc-services must not be an alias"
