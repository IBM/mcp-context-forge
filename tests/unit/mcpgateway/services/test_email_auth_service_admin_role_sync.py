# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_email_auth_service_admin_role_sync.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Marek Dano

Tests the automatic assignment and revocation of platform_admin role
when is_admin flag changes.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import EmailUser
from mcpgateway.services.email_auth_service import EmailAuthService


@pytest.fixture
def mock_db():
    """Create mock database session."""
    return MagicMock(spec=Session)


@pytest.mark.asyncio
async def test_create_user_admin_role_not_found(mock_db):
    """Test create_user when platform_admin role doesn't exist in DB."""
    service = EmailAuthService(mock_db)

    with patch.object(service, "get_user_by_email", new=AsyncMock(return_value=None)):
        with patch.object(service.password_service, "hash_password_async", new=AsyncMock(return_value="hashed")):
            with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
                mock_settings.auto_create_personal_teams = False
                mock_settings.password_min_length = 8
                mock_settings.password_require_uppercase = False
                mock_settings.password_require_lowercase = False
                mock_settings.password_require_numbers = False
                mock_settings.password_require_special = False

                # Mock RoleService with get_role_by_name returning None (role not found)
                mock_role_service = MagicMock()
                mock_role_service.get_role_by_name = AsyncMock(return_value=None)
                mock_role_service.assign_role_to_user = AsyncMock()

                with patch("mcpgateway.services.role_service.RoleService", return_value=mock_role_service):
                    user = await service.create_user(email="test@example.com", password="TestPass123!", is_admin=True)

                    # User created despite role not found
                    assert user.is_admin is True
                    assert user.email == "test@example.com"

                    # assign_role_to_user should NOT be called since role was not found
                    mock_role_service.assign_role_to_user.assert_not_called()


@pytest.mark.asyncio
async def test_update_user_admin_role_not_found(mock_db):
    """Test update_user when platform_admin role doesn't exist."""
    service = EmailAuthService(mock_db)

    # Create existing user
    existing_user = EmailUser(email="test@example.com", password_hash="hashed", is_admin=False, is_active=True)

    # Mock database query to return existing user
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_user
    mock_db.execute.return_value = mock_result

    # Mock RoleService.get_role_by_name to return None for both roles
    with patch("mcpgateway.services.role_service.RoleService") as mock_role_service_cls:
        mock_role_service = AsyncMock()
        mock_role_service.get_role_by_name = AsyncMock(return_value=None)
        mock_role_service_cls.return_value = mock_role_service

        # Update user to admin
        updated_user = await service.update_user(email="test@example.com", is_admin=True)

        # Verify user was updated despite roles not found
        assert updated_user.is_admin is True

        # Verify both roles were looked up
        assert mock_role_service.get_role_by_name.call_count == 2
        mock_role_service.get_role_by_name.assert_any_call("platform_admin", "global")
        mock_role_service.get_role_by_name.assert_any_call("platform_viewer", "global")


@pytest.mark.asyncio
async def test_update_user_revoke_admin_role(mock_db):
    """Test update_user revokes platform_admin and assigns platform_viewer when demoting admin."""
    service = EmailAuthService(mock_db)

    # Create existing admin user
    existing_user = EmailUser(email="test@example.com", password_hash="hashed", is_admin=True, is_active=True)

    # Mock database query to return existing user
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_user
    mock_db.execute.return_value = mock_result

    # Mock is_last_active_admin to return False (not last admin)
    with patch.object(service, "is_last_active_admin", new=AsyncMock(return_value=False)):
        # Mock settings.protect_all_admins to False
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.protect_all_admins = False

            # Mock RoleService
            with patch("mcpgateway.services.role_service.RoleService") as mock_role_service_cls:
                mock_role_service = AsyncMock()
                mock_admin_role = MagicMock(id="admin-role-123")
                mock_viewer_role = MagicMock(id="viewer-role-456")

                async def get_role_by_name_side_effect(name, scope):
                    if name == "platform_admin":
                        return mock_admin_role
                    if name == "platform_viewer":
                        return mock_viewer_role
                    return None

                mock_role_service.get_role_by_name = AsyncMock(side_effect=get_role_by_name_side_effect)
                mock_role_service.revoke_role_from_user = AsyncMock(return_value=True)
                mock_role_service.get_user_role_assignment = AsyncMock(return_value=None)
                mock_role_service.assign_role_to_user = AsyncMock()
                mock_role_service_cls.return_value = mock_role_service

                # Update user to non-admin
                updated_user = await service.update_user(email="test@example.com", is_admin=False)

                # Verify user was demoted
                assert updated_user.is_admin is False

                # Verify platform_admin was revoked
                mock_role_service.revoke_role_from_user.assert_called_once_with(user_email="test@example.com", role_id="admin-role-123", scope="global", scope_id=None)

                # Verify platform_viewer was assigned
                mock_role_service.assign_role_to_user.assert_called_once_with(user_email="test@example.com", role_id="viewer-role-456", scope="global", scope_id=None, granted_by="test@example.com")


@pytest.mark.asyncio
async def test_update_user_admin_role_sync_exception(mock_db):
    """Test update_user when role sync raises exception."""
    service = EmailAuthService(mock_db)

    # Create existing user
    existing_user = EmailUser(email="test@example.com", password_hash="hashed", is_admin=False, is_active=True)

    # Mock database query to return existing user
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_user
    mock_db.execute.return_value = mock_result

    # Mock RoleService to raise exception on role lookup
    with patch("mcpgateway.services.role_service.RoleService") as mock_role_service_cls:
        mock_role_service = AsyncMock()
        mock_role_service.get_role_by_name = AsyncMock(side_effect=Exception("DB error"))
        mock_role_service_cls.return_value = mock_role_service

        # Update user to admin - should succeed despite role sync failure
        updated_user = await service.update_user(email="test@example.com", is_admin=True)

        # Verify user was updated despite role sync failure
        assert updated_user.is_admin is True


@pytest.mark.asyncio
async def test_update_user_assign_admin_role_inactive_assignment(mock_db):
    """Test update_user assigns platform_admin and revokes platform_viewer on promotion."""
    service = EmailAuthService(mock_db)

    # Create existing user
    existing_user = EmailUser(email="test@example.com", password_hash="hashed", is_admin=False, is_active=True)

    # Mock database query to return existing user
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_user
    mock_db.execute.return_value = mock_result

    # Mock RoleService with inactive platform_admin assignment
    with patch("mcpgateway.services.role_service.RoleService") as mock_role_service_cls:
        mock_role_service = AsyncMock()
        mock_admin_role = MagicMock(id="admin-role-123")
        mock_viewer_role = MagicMock(id="viewer-role-456")

        async def get_role_by_name_side_effect(name, scope):
            if name == "platform_admin":
                return mock_admin_role
            if name == "platform_viewer":
                return mock_viewer_role
            return None

        mock_role_service.get_role_by_name = AsyncMock(side_effect=get_role_by_name_side_effect)

        # Mock existing but inactive platform_admin assignment
        mock_assignment = MagicMock(is_active=False)
        mock_role_service.get_user_role_assignment = AsyncMock(return_value=mock_assignment)
        mock_role_service.assign_role_to_user = AsyncMock()
        mock_role_service.revoke_role_from_user = AsyncMock(return_value=True)
        mock_role_service_cls.return_value = mock_role_service

        # Update user to admin
        updated_user = await service.update_user(email="test@example.com", is_admin=True)

        # Verify user was promoted
        assert updated_user.is_admin is True

        # Verify platform_admin was assigned (because existing assignment was inactive)
        mock_role_service.assign_role_to_user.assert_called_once_with(user_email="test@example.com", role_id="admin-role-123", scope="global", scope_id=None, granted_by="test@example.com")

        # Verify platform_viewer was revoked
        mock_role_service.revoke_role_from_user.assert_called_once_with(user_email="test@example.com", role_id="viewer-role-456", scope="global", scope_id=None)
