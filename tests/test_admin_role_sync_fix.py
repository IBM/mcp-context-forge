# -*- coding: utf-8 -*-
"""Tests for Admin UI Administrator Checkbox ↔ RBAC Role Desync Fix.

This test module verifies that the bug fix properly ensures atomicity between
the is_admin flag and RBAC role assignments.

Bug Summary:
When creating or editing a user via the Admin UI and toggling the "administrator"
checkbox, the user's is_admin flag must be synchronized with the platform_admin
RBAC role assignment. Previously, these could get out of sync, resulting in users
who appear to be admins but receive permission errors.

Fix Summary:
1. create_user(): Verifies admin role exists before creating admin user, fails atomically if role assignment fails
2. update_user(): Verifies admin role exists before promotion, only sets is_admin=True after successful role assignment
3. Startup verification: Checks required roles exist and repairs any existing inconsistencies
4. Admin UI: Already has proper error handling to display role assignment failures
"""

# Standard
from unittest.mock import AsyncMock, Mock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailUser, Role, UserRole
from mcpgateway.services.email_auth_service import EmailAuthService


class TestAdminRoleSyncFix:
    """Test suite for admin/role synchronization bug fix."""

    @pytest.mark.asyncio
    async def test_create_admin_user_fails_when_role_missing(self, db_session: Session):
        """Test that creating an admin user fails if the platform_admin role doesn't exist.

        This ensures atomicity - we don't create a user with is_admin=True if role assignment will fail.
        """
        auth_service = EmailAuthService(db_session)

        # Mock role service to return None (role doesn't exist)
        with patch.object(auth_service, "role_service") as mock_role_service:
            mock_role_service.get_role_by_name = AsyncMock(return_value=None)

            # Attempt to create admin user should fail with clear error
            with pytest.raises(ValueError) as exc_info:
                await auth_service.create_user(
                    email="admin@example.com",
                    password="SecurePass123!",
                    full_name="Test Admin",
                    is_admin=True,
                )

            # Verify error message mentions the missing role
            assert "platform_admin" in str(exc_info.value).lower()
            assert "does not exist" in str(exc_info.value).lower()

            # Verify user was NOT created in database
            user = await auth_service.get_user_by_email("admin@example.com")
            assert user is None

    @pytest.mark.asyncio
    async def test_create_admin_user_succeeds_when_role_exists(self, db_session: Session):
        """Test that creating an admin user succeeds when the platform_admin role exists."""
        auth_service = EmailAuthService(db_session)

        # Create the required admin role
        admin_role = Role(
            name=settings.default_admin_role,
            description="Platform Administrator",
            scope="global",
            permissions=["*"],
            created_by="system",
            is_system_role=True,
        )
        db_session.add(admin_role)
        db_session.commit()

        # Mock role assignment to succeed
        with patch.object(auth_service, "role_service") as mock_role_service:
            mock_role_service.get_role_by_name = AsyncMock(return_value=admin_role)
            mock_role_service.assign_role_to_user = AsyncMock(return_value=Mock())

            # Create admin user should succeed
            user = await auth_service.create_user(
                email="admin@example.com",
                password="SecurePass123!",
                full_name="Test Admin",
                is_admin=True,
            )

            # Verify user was created with is_admin=True
            assert user is not None
            assert user.email == "admin@example.com"
            assert user.is_admin is True

            # Verify role assignment was attempted
            mock_role_service.assign_role_to_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_admin_user_rolls_back_on_role_assignment_failure(self, db_session: Session):
        """Test that user creation is rolled back if role assignment fails after user is created."""
        auth_service = EmailAuthService(db_session)

        # Create the required admin role
        admin_role = Role(
            name=settings.default_admin_role,
            description="Platform Administrator",
            scope="global",
            permissions=["*"],
            created_by="system",
            is_system_role=True,
        )
        db_session.add(admin_role)
        db_session.commit()

        # Mock role service to fail during assignment
        with patch.object(auth_service, "role_service") as mock_role_service:
            mock_role_service.get_role_by_name = AsyncMock(return_value=admin_role)
            mock_role_service.assign_role_to_user = AsyncMock(side_effect=ValueError("Role assignment failed"))

            # Attempt to create admin user should fail
            with pytest.raises(ValueError) as exc_info:
                await auth_service.create_user(
                    email="admin@example.com",
                    password="SecurePass123!",
                    full_name="Test Admin",
                    is_admin=True,
                )

            assert "role assignment failed" in str(exc_info.value).lower()

            # Verify user was NOT created (rolled back)
            user = await auth_service.get_user_by_email("admin@example.com")
            assert user is None

    @pytest.mark.asyncio
    async def test_update_user_to_admin_fails_when_role_missing(self, db_session: Session):
        """Test that promoting a user to admin fails if the platform_admin role doesn't exist."""
        auth_service = EmailAuthService(db_session)

        # Create a regular user first
        user = EmailUser(
            email="user@example.com",
            password_hash="hashed",
            full_name="Test User",
            is_admin=False,
        )
        db_session.add(user)
        db_session.commit()

        # Mock role service to return None (role doesn't exist)
        with patch.object(auth_service, "role_service") as mock_role_service:
            mock_role_service.get_role_by_name = AsyncMock(return_value=None)

            # Attempt to promote user to admin should fail
            with pytest.raises(ValueError) as exc_info:
                await auth_service.update_user(
                    email="user@example.com",
                    is_admin=True,
                )

            # Verify error message mentions the missing role
            assert "platform_admin" in str(exc_info.value).lower()
            assert "does not exist" in str(exc_info.value).lower()

            # Verify user is still NOT an admin
            db_session.refresh(user)
            assert user.is_admin is False

    @pytest.mark.asyncio
    async def test_update_user_to_admin_only_sets_flag_after_role_assignment(self, db_session: Session):
        """Test that is_admin flag is only set to True AFTER successful role assignment."""
        auth_service = EmailAuthService(db_session)

        # Create a regular user first
        user = EmailUser(
            email="user@example.com",
            password_hash="hashed",
            full_name="Test User",
            is_admin=False,
        )
        db_session.add(user)
        db_session.commit()

        # Create the required admin role
        admin_role = Role(
            name=settings.default_admin_role,
            description="Platform Administrator",
            scope="global",
            permissions=["*"],
            created_by="system",
            is_system_role=True,
        )
        db_session.add(admin_role)
        db_session.commit()

        # Mock role service
        with patch.object(auth_service, "role_service") as mock_role_service:
            mock_role_service.get_role_by_name = AsyncMock(return_value=admin_role)
            mock_role_service.get_user_role_assignment = AsyncMock(return_value=None)
            mock_role_service.assign_role_to_user = AsyncMock(return_value=Mock())
            mock_role_service.revoke_role_from_user = AsyncMock(return_value=True)

            # Promote user to admin
            updated_user = await auth_service.update_user(
                email="user@example.com",
                is_admin=True,
            )

            # Verify user is now an admin
            assert updated_user.is_admin is True

            # Verify role assignment was called
            mock_role_service.assign_role_to_user.assert_called()

    @pytest.mark.asyncio
    async def test_update_user_to_admin_fails_atomically_on_role_assignment_error(self, db_session: Session):
        """Test that promotion fails atomically if role assignment fails."""
        auth_service = EmailAuthService(db_session)

        # Create a regular user first
        user = EmailUser(
            email="user@example.com",
            password_hash="hashed",
            full_name="Test User",
            is_admin=False,
        )
        db_session.add(user)
        db_session.commit()

        # Create the required admin role
        admin_role = Role(
            name=settings.default_admin_role,
            description="Platform Administrator",
            scope="global",
            permissions=["*"],
            created_by="system",
            is_system_role=True,
        )
        db_session.add(admin_role)
        db_session.commit()

        # Mock role service to fail during assignment
        with patch.object(auth_service, "role_service") as mock_role_service:
            mock_role_service.get_role_by_name = AsyncMock(return_value=admin_role)
            mock_role_service.get_user_role_assignment = AsyncMock(return_value=None)
            mock_role_service.assign_role_to_user = AsyncMock(side_effect=ValueError("Assignment failed"))

            # Attempt to promote user should fail
            with pytest.raises(ValueError) as exc_info:
                await auth_service.update_user(
                    email="user@example.com",
                    is_admin=True,
                )

            assert "assignment failed" in str(exc_info.value).lower()

            # Verify user is still NOT an admin (atomic failure)
            db_session.refresh(user)
            assert user.is_admin is False

    @pytest.mark.asyncio
    async def test_verify_required_roles_exist_logs_warning_when_missing(self, db_session: Session):
        """Test that verify_required_roles_exist logs warnings for missing roles."""
        auth_service = EmailAuthService(db_session)

        # Mock role service to return None for all roles
        with patch.object(auth_service, "role_service") as mock_role_service:
            mock_role_service.get_role_by_name = AsyncMock(return_value=None)

            # Should not raise, but should log warnings
            with patch("mcpgateway.services.email_auth_service.logger") as mock_logger:
                await auth_service.verify_required_roles_exist()

                # Verify warning was logged
                mock_logger.warning.assert_called_once()
                warning_msg = mock_logger.warning.call_args[0][0]
                assert "missing" in warning_msg.lower()
                assert "platform_admin" in warning_msg.lower()

    @pytest.mark.asyncio
    async def test_verify_required_roles_exist_logs_success_when_all_present(self, db_session: Session):
        """Test that verify_required_roles_exist logs success when all roles exist."""
        auth_service = EmailAuthService(db_session)

        # Mock role service to return roles
        mock_role = Mock()
        with patch.object(auth_service, "role_service") as mock_role_service:
            mock_role_service.get_role_by_name = AsyncMock(return_value=mock_role)

            # Should log success
            with patch("mcpgateway.services.email_auth_service.logger") as mock_logger:
                await auth_service.verify_required_roles_exist()

                # Verify info was logged
                mock_logger.info.assert_called_once()
                info_msg = mock_logger.info.call_args[0][0]
                assert "verified" in info_msg.lower()

    @pytest.mark.asyncio
    async def test_consistency_check_detects_admin_without_role(self, db_session: Session):
        """Test that consistency check detects users with is_admin=True but no role."""
        auth_service = EmailAuthService(db_session)

        # Create an admin user without role assignment (simulating the bug)
        user = EmailUser(
            email="admin@example.com",
            password_hash="hashed",
            full_name="Admin User",
            is_admin=True,
        )
        db_session.add(user)
        db_session.commit()

        # Create the admin role
        admin_role = Role(
            name=settings.default_admin_role,
            description="Platform Administrator",
            scope="global",
            permissions=["*"],
            created_by="system",
            is_system_role=True,
        )
        db_session.add(admin_role)
        db_session.commit()

        # Mock role service
        with patch.object(auth_service, "role_service") as mock_role_service:
            mock_role_service.get_role_by_name = AsyncMock(return_value=admin_role)
            mock_role_service.get_user_role_assignment = AsyncMock(return_value=None)  # No role assigned

            # Run consistency check in dry-run mode
            result = await auth_service.check_and_repair_admin_role_consistency(dry_run=True)

            # Verify inconsistency was detected
            assert result["checked"] == 1
            assert len(result["inconsistent"]) == 1
            assert "admin@example.com" in result["inconsistent"]
            assert len(result["repaired"]) == 0  # Dry run doesn't repair

    @pytest.mark.asyncio
    async def test_consistency_check_repairs_admin_without_role(self, db_session: Session):
        """Test that consistency check repairs users with is_admin=True but no role."""
        auth_service = EmailAuthService(db_session)

        # Create an admin user without role assignment (simulating the bug)
        user = EmailUser(
            email="admin@example.com",
            password_hash="hashed",
            full_name="Admin User",
            is_admin=True,
        )
        db_session.add(user)
        db_session.commit()

        # Create the admin role
        admin_role = Role(
            name=settings.default_admin_role,
            description="Platform Administrator",
            scope="global",
            permissions=["*"],
            created_by="system",
            is_system_role=True,
        )
        db_session.add(admin_role)
        db_session.commit()

        # Mock role service
        with patch.object(auth_service, "role_service") as mock_role_service:
            mock_role_service.get_role_by_name = AsyncMock(return_value=admin_role)
            mock_role_service.get_user_role_assignment = AsyncMock(return_value=None)  # No role assigned
            mock_role_service.assign_role_to_user = AsyncMock(return_value=Mock())

            # Run consistency check with repair
            result = await auth_service.check_and_repair_admin_role_consistency(dry_run=False)

            # Verify repair was performed
            assert result["checked"] == 1
            assert len(result["inconsistent"]) == 1
            assert len(result["repaired"]) == 1
            assert "admin@example.com" in result["repaired"]
            assert len(result["failed"]) == 0

            # Verify role assignment was called
            mock_role_service.assign_role_to_user.assert_called_once()


# Pytest fixtures
@pytest.fixture
def db_session():
    """Provide a mock database session for testing."""
    session = Mock(spec=Session)
    session.add = Mock()
    session.commit = Mock()
    session.refresh = Mock()
    session.rollback = Mock()
    session.execute = Mock()
    return session

# Made with Bob
