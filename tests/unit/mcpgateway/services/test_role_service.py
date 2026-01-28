# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_role_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive unit tests for RoleService.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Role, UserRole, utc_now
from mcpgateway.services.role_service import RoleService


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = Mock(spec=Session)
    db.execute = Mock()
    db.add = Mock()
    db.commit = Mock()
    db.refresh = Mock()
    return db


@pytest.fixture
def role_service(mock_db):
    """Create a RoleService instance with mock database."""
    return RoleService(mock_db)


@pytest.fixture
def sample_role():
    """Create a sample role for testing."""
    role = Mock(spec=Role)
    role.id = "role-123"
    role.name = "test-role"
    role.description = "Test role description"
    role.scope = "team"
    role.permissions = ["tools.read", "tools.execute"]
    role.created_by = "admin@example.com"
    role.inherits_from = None
    role.is_system_role = False
    role.is_active = True
    role.created_at = utc_now()
    role.updated_at = utc_now()
    return role


@pytest.fixture
def sample_user_role():
    """Create a sample user role assignment for testing."""
    user_role = Mock(spec=UserRole)
    user_role.id = "ur-456"
    user_role.user_email = "user@example.com"
    user_role.role_id = "role-123"
    user_role.scope = "team"
    user_role.scope_id = "team-789"
    user_role.granted_by = "admin@example.com"
    user_role.expires_at = None
    user_role.is_active = True
    user_role.created_at = utc_now()
    user_role.is_expired = Mock(return_value=False)
    return user_role


class TestRoleServiceInit:
    """Test RoleService initialization."""

    def test_init_stores_db_session(self, mock_db):
        """Test that initialization stores the database session."""
        service = RoleService(mock_db)
        assert service.db is mock_db

    def test_init_with_none_db(self):
        """Test initialization with None database."""
        service = RoleService(None)
        assert service.db is None


class TestCreateRole:
    """Test create_role method."""

    @pytest.mark.asyncio
    async def test_create_role_success(self, role_service, mock_db, sample_role):
        """Test successful role creation."""
        # Mock get_role_by_name to return None (no existing role)
        with patch.object(role_service, "get_role_by_name", new=AsyncMock(return_value=None)):
            with patch("mcpgateway.services.role_service.Permissions.get_all_permissions", return_value=["tools.read", "tools.execute"]):
                with patch("mcpgateway.services.role_service.Role") as MockRole:
                    MockRole.return_value = sample_role

                    result = await role_service.create_role(
                        name="test-role", description="Test role description", scope="team", permissions=["tools.read", "tools.execute"], created_by="admin@example.com"
                    )

                    assert result == sample_role
                    mock_db.add.assert_called_once_with(sample_role)
                    mock_db.commit.assert_called_once()
                    mock_db.refresh.assert_called_once_with(sample_role)

    @pytest.mark.asyncio
    async def test_create_role_invalid_scope(self, role_service):
        """Test role creation with invalid scope."""
        with pytest.raises(ValueError, match="Invalid scope: invalid"):
            await role_service.create_role(name="test-role", description="Test role", scope="invalid", permissions=[], created_by="admin@example.com")

    @pytest.mark.asyncio
    async def test_create_role_duplicate_name(self, role_service, sample_role):
        """Test role creation with duplicate name."""
        with patch.object(role_service, "get_role_by_name", new=AsyncMock(return_value=sample_role)):
            with pytest.raises(ValueError, match="already exists"):
                await role_service.create_role(name="test-role", description="Test role", scope="team", permissions=[], created_by="admin@example.com")

    @pytest.mark.asyncio
    async def test_create_role_invalid_permissions(self, role_service):
        """Test role creation with invalid permissions."""
        with patch.object(role_service, "get_role_by_name", new=AsyncMock(return_value=None)):
            with patch("mcpgateway.services.role_service.Permissions.get_all_permissions", return_value=["valid.permission"]):
                with pytest.raises(ValueError, match="Invalid permissions"):
                    await role_service.create_role(name="test-role", description="Test role", scope="global", permissions=["invalid.permission"], created_by="admin@example.com")

    @pytest.mark.asyncio
    async def test_create_role_with_inheritance(self, role_service, mock_db, sample_role):
        """Test role creation with parent role inheritance."""
        parent_role = Mock(spec=Role)
        parent_role.id = "parent-role-id"

        with patch.object(role_service, "get_role_by_name", new=AsyncMock(return_value=None)):
            with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=parent_role)):
                with patch.object(role_service, "_would_create_cycle", new=AsyncMock(return_value=False)):
                    with patch("mcpgateway.services.role_service.Permissions.get_all_permissions", return_value=["tools.read"]):
                        with patch("mcpgateway.services.role_service.Role") as MockRole:
                            MockRole.return_value = sample_role

                            result = await role_service.create_role(
                                name="child-role", description="Child role", scope="team", permissions=["tools.read"], created_by="admin@example.com", inherits_from="parent-role-id"
                            )

                            assert result == sample_role
                            MockRole.assert_called_once_with(
                                name="child-role",
                                description="Child role",
                                scope="team",
                                permissions=["tools.read"],
                                created_by="admin@example.com",
                                inherits_from="parent-role-id",
                                is_system_role=False,
                            )

    @pytest.mark.asyncio
    async def test_create_role_parent_not_found(self, role_service):
        """Test role creation with non-existent parent role."""
        with patch.object(role_service, "get_role_by_name", new=AsyncMock(return_value=None)):
            with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=None)):
                with pytest.raises(ValueError, match="Parent role not found"):
                    await role_service.create_role(name="child-role", description="Child role", scope="team", permissions=[], created_by="admin@example.com", inherits_from="non-existent-parent")

    @pytest.mark.asyncio
    async def test_create_role_would_create_cycle(self, role_service):
        """Test role creation that would create inheritance cycle."""
        parent_role = Mock(spec=Role)
        parent_role.id = "parent-role-id"

        with patch.object(role_service, "get_role_by_name", new=AsyncMock(return_value=None)):
            with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=parent_role)):
                with patch.object(role_service, "_would_create_cycle", new=AsyncMock(return_value=True)):
                    with pytest.raises(ValueError, match="would create a cycle"):
                        await role_service.create_role(name="child-role", description="Child role", scope="team", permissions=[], created_by="admin@example.com", inherits_from="parent-role-id")

    @pytest.mark.asyncio
    async def test_create_system_role(self, role_service, mock_db):
        """Test creation of a system role."""
        with patch.object(role_service, "get_role_by_name", new=AsyncMock(return_value=None)):
            with patch("mcpgateway.services.role_service.Permissions.get_all_permissions", return_value=[]):
                with patch("mcpgateway.services.role_service.Role") as MockRole:
                    system_role = Mock(spec=Role)
                    system_role.id = "sys-role-id"
                    system_role.name = "system-admin"
                    system_role.is_system_role = True
                    MockRole.return_value = system_role

                    result = await role_service.create_role(name="system-admin", description="System admin role", scope="global", permissions=[], created_by="system", is_system_role=True)

                    assert result.is_system_role is True
                    MockRole.assert_called_once_with(name="system-admin", description="System admin role", scope="global", permissions=[], created_by="system", inherits_from=None, is_system_role=True)

    @pytest.mark.asyncio
    async def test_create_role_with_wildcard_permission(self, role_service, mock_db):
        """Test role creation with wildcard permission."""
        with patch.object(role_service, "get_role_by_name", new=AsyncMock(return_value=None)):
            with patch("mcpgateway.services.role_service.Permissions.get_all_permissions", return_value=["tools.read"]):
                with patch("mcpgateway.services.role_service.Permissions.ALL_PERMISSIONS", "*"):
                    with patch("mcpgateway.services.role_service.Role") as MockRole:
                        role = Mock(spec=Role)
                        MockRole.return_value = role

                        result = await role_service.create_role(name="admin", description="Admin role", scope="global", permissions=["*"], created_by="admin@example.com")

                        assert result == role
                        mock_db.add.assert_called_once()


class TestGetRoleById:
    """Test get_role_by_id method."""

    @pytest.mark.asyncio
    async def test_get_role_by_id_found(self, role_service, mock_db, sample_role):
        """Test getting role by ID when it exists."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = sample_role
        mock_db.execute.return_value = mock_result

        result = await role_service.get_role_by_id("role-123")

        assert result == sample_role
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_role_by_id_not_found(self, role_service, mock_db):
        """Test getting role by ID when it doesn't exist."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await role_service.get_role_by_id("non-existent")

        assert result is None
        mock_db.execute.assert_called_once()


class TestGetRoleByName:
    """Test get_role_by_name method."""

    @pytest.mark.asyncio
    async def test_get_role_by_name_found(self, role_service, mock_db, sample_role):
        """Test getting role by name when it exists."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = sample_role
        mock_db.execute.return_value = mock_result

        result = await role_service.get_role_by_name("test-role", "team")

        assert result == sample_role
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_role_by_name_not_found(self, role_service, mock_db):
        """Test getting role by name when it doesn't exist."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await role_service.get_role_by_name("non-existent", "global")

        assert result is None


class TestListRoles:
    """Test list_roles method."""

    @pytest.mark.asyncio
    async def test_list_roles_all(self, role_service, mock_db):
        """Test listing all roles without filters."""
        roles = [Mock(spec=Role), Mock(spec=Role)]
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = roles
        mock_db.execute.return_value = mock_result

        result = await role_service.list_roles()

        assert result == roles
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_roles_by_scope(self, role_service, mock_db):
        """Test listing roles filtered by scope."""
        team_roles = [Mock(spec=Role)]
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = team_roles
        mock_db.execute.return_value = mock_result

        result = await role_service.list_roles(scope="team")

        assert result == team_roles

    @pytest.mark.asyncio
    async def test_list_roles_exclude_system(self, role_service, mock_db):
        """Test listing roles excluding system roles."""
        user_roles = [Mock(spec=Role)]
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = user_roles
        mock_db.execute.return_value = mock_result

        result = await role_service.list_roles(include_system=False)

        assert result == user_roles

    @pytest.mark.asyncio
    async def test_list_roles_include_inactive(self, role_service, mock_db):
        """Test listing roles including inactive ones."""
        all_roles = [Mock(spec=Role), Mock(spec=Role)]
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = all_roles
        mock_db.execute.return_value = mock_result

        result = await role_service.list_roles(include_inactive=True)

        assert result == all_roles

    @pytest.mark.asyncio
    async def test_list_roles_combined_filters(self, role_service, mock_db):
        """Test listing roles with multiple filters."""
        filtered_roles = [Mock(spec=Role)]
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = filtered_roles
        mock_db.execute.return_value = mock_result

        result = await role_service.list_roles(scope="global", include_system=False, include_inactive=False)

        assert result == filtered_roles


class TestUpdateRole:
    """Test update_role method."""

    @pytest.mark.asyncio
    async def test_update_role_success(self, role_service, mock_db, sample_role):
        """Test successful role update."""
        sample_role.is_system_role = False

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with patch("mcpgateway.services.role_service.utc_now", return_value=datetime.now(timezone.utc)):
                result = await role_service.update_role(role_id="role-123", description="Updated description")

                assert result == sample_role
                assert sample_role.description == "Updated description"
                mock_db.commit.assert_called_once()
                mock_db.refresh.assert_called_once_with(sample_role)

    @pytest.mark.asyncio
    async def test_update_role_not_found(self, role_service):
        """Test updating non-existent role."""
        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=None)):
            result = await role_service.update_role(role_id="non-existent")
            assert result is None

    @pytest.mark.asyncio
    async def test_update_role_system_role(self, role_service, sample_role):
        """Test that system roles cannot be updated."""
        sample_role.is_system_role = True

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with pytest.raises(ValueError, match="Cannot modify system roles"):
                await role_service.update_role(role_id="role-123", name="new-name")

    @pytest.mark.asyncio
    async def test_update_role_name_duplicate(self, role_service, sample_role):
        """Test updating role name to duplicate name."""
        sample_role.is_system_role = False
        existing_role = Mock(spec=Role)
        existing_role.id = "other-role-id"

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with patch.object(role_service, "get_role_by_name", new=AsyncMock(return_value=existing_role)):
                with pytest.raises(ValueError, match="already exists"):
                    await role_service.update_role(role_id="role-123", name="existing-name")

    @pytest.mark.asyncio
    async def test_update_role_name_same_role(self, role_service, mock_db, sample_role):
        """Test updating role with same name for same role (allowed)."""
        sample_role.is_system_role = False
        sample_role.id = "role-123"
        sample_role.name = "test-role"

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with patch.object(role_service, "get_role_by_name", new=AsyncMock(return_value=sample_role)):
                with patch("mcpgateway.services.role_service.utc_now", return_value=datetime.now(timezone.utc)):
                    result = await role_service.update_role(role_id="role-123", name="test-role")

                    assert result == sample_role
                    mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_role_permissions(self, role_service, mock_db, sample_role):
        """Test updating role permissions."""
        sample_role.is_system_role = False
        new_permissions = ["users.read", "users.write"]

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with patch("mcpgateway.services.role_service.Permissions.get_all_permissions", return_value=new_permissions):
                with patch("mcpgateway.services.role_service.utc_now", return_value=datetime.now(timezone.utc)):
                    result = await role_service.update_role(role_id="role-123", permissions=new_permissions)

                    assert result.permissions == new_permissions
                    mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_role_invalid_permissions(self, role_service, sample_role):
        """Test updating role with invalid permissions."""
        sample_role.is_system_role = False

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with patch("mcpgateway.services.role_service.Permissions.get_all_permissions", return_value=["valid.perm"]):
                with pytest.raises(ValueError, match="Invalid permissions"):
                    await role_service.update_role(role_id="role-123", permissions=["invalid.perm"])

    @pytest.mark.asyncio
    async def test_update_role_inheritance(self, role_service, mock_db, sample_role):
        """Test updating role inheritance."""
        sample_role.is_system_role = False
        sample_role.inherits_from = None
        parent_role = Mock(spec=Role)
        parent_role.id = "parent-id"

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(side_effect=[sample_role, parent_role])):
            with patch.object(role_service, "_would_create_cycle", new=AsyncMock(return_value=False)):
                with patch("mcpgateway.services.role_service.utc_now", return_value=datetime.now(timezone.utc)):
                    result = await role_service.update_role(role_id="role-123", inherits_from="parent-id")

                    assert result.inherits_from == "parent-id"
                    mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_role_remove_inheritance(self, role_service, mock_db, sample_role):
        """Test removing role inheritance."""
        sample_role.is_system_role = False
        sample_role.inherits_from = "parent-id"

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with patch("mcpgateway.services.role_service.utc_now", return_value=datetime.now(timezone.utc)):
                result = await role_service.update_role(role_id="role-123", inherits_from="")

                assert result.inherits_from == ""
                mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_role_active_status(self, role_service, mock_db, sample_role):
        """Test updating role active status."""
        sample_role.is_system_role = False
        sample_role.is_active = True

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with patch("mcpgateway.services.role_service.utc_now", return_value=datetime.now(timezone.utc)):
                result = await role_service.update_role(role_id="role-123", is_active=False)

                assert result.is_active is False
                mock_db.commit.assert_called_once()


class TestDeleteRole:
    """Test delete_role method."""

    @pytest.mark.asyncio
    async def test_delete_role_success(self, role_service, mock_db, sample_role):
        """Test successful role deletion (soft delete)."""
        sample_role.is_system_role = False

        mock_update_result = Mock()
        mock_update_result.update.return_value = None
        mock_db.execute.return_value = mock_update_result

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with patch("mcpgateway.services.role_service.utc_now", return_value=datetime.now(timezone.utc)):
                result = await role_service.delete_role("role-123")

                assert result is True
                assert sample_role.is_active is False
                mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_role_not_found(self, role_service):
        """Test deleting non-existent role."""
        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=None)):
            result = await role_service.delete_role("non-existent")
            assert result is False

    @pytest.mark.asyncio
    async def test_delete_system_role(self, role_service, sample_role):
        """Test that system roles cannot be deleted."""
        sample_role.is_system_role = True

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with pytest.raises(ValueError, match="Cannot delete system roles"):
                await role_service.delete_role("role-123")


class TestAssignRoleToUser:
    """Test assign_role_to_user method."""

    @pytest.mark.asyncio
    async def test_assign_role_success(self, role_service, mock_db, sample_role, sample_user_role):
        """Test successful role assignment to user."""
        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with patch.object(role_service, "get_user_role_assignment", new=AsyncMock(return_value=None)):
                with patch("mcpgateway.services.role_service.UserRole") as MockUserRole:
                    MockUserRole.return_value = sample_user_role

                    result = await role_service.assign_role_to_user(user_email="user@example.com", role_id="role-123", scope="team", scope_id="team-789", granted_by="admin@example.com")

                    assert result == sample_user_role
                    mock_db.add.assert_called_once_with(sample_user_role)
                    mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_assign_role_not_found(self, role_service):
        """Test assigning non-existent role."""
        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=None)):
            with pytest.raises(ValueError, match="Role not found or inactive"):
                await role_service.assign_role_to_user(user_email="user@example.com", role_id="non-existent", scope="team", scope_id="team-789", granted_by="admin@example.com")

    @pytest.mark.asyncio
    async def test_assign_inactive_role(self, role_service, sample_role):
        """Test assigning inactive role."""
        sample_role.is_active = False

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with pytest.raises(ValueError, match="Role not found or inactive"):
                await role_service.assign_role_to_user(user_email="user@example.com", role_id="role-123", scope="team", scope_id="team-789", granted_by="admin@example.com")

    @pytest.mark.asyncio
    async def test_assign_role_scope_mismatch(self, role_service, sample_role):
        """Test assigning role with scope mismatch."""
        sample_role.scope = "global"

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with pytest.raises(ValueError, match="doesn't match"):
                await role_service.assign_role_to_user(user_email="user@example.com", role_id="role-123", scope="team", scope_id="team-789", granted_by="admin@example.com")

    @pytest.mark.asyncio
    async def test_assign_team_role_without_scope_id(self, role_service, sample_role):
        """Test assigning team-scoped role without scope_id."""
        sample_role.scope = "team"

        mock_get_role = AsyncMock(return_value=sample_role)
        with patch.object(role_service, "get_role_by_id", new=mock_get_role):
            with pytest.raises(ValueError, match="scope_id required"):
                await role_service.assign_role_to_user(user_email="user@example.com", role_id="role-123", scope="team", scope_id=None, granted_by="admin@example.com")

    @pytest.mark.asyncio
    async def test_assign_global_role_with_scope_id(self, role_service, sample_role):
        """Test assigning global role with scope_id."""
        sample_role.scope = "global"

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with pytest.raises(ValueError, match="scope_id not allowed"):
                await role_service.assign_role_to_user(user_email="user@example.com", role_id="role-123", scope="global", scope_id="should-not-have", granted_by="admin@example.com")

    @pytest.mark.asyncio
    async def test_assign_duplicate_active_role(self, role_service, sample_role, sample_user_role):
        """Test assigning role that user already has."""
        sample_user_role.is_active = True
        sample_user_role.is_expired.return_value = False

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with patch.object(role_service, "get_user_role_assignment", new=AsyncMock(return_value=sample_user_role)):
                with pytest.raises(ValueError, match="already has this role"):
                    await role_service.assign_role_to_user(user_email="user@example.com", role_id="role-123", scope="team", scope_id="team-789", granted_by="admin@example.com")

    @pytest.mark.asyncio
    async def test_assign_role_with_expiration(self, role_service, mock_db, sample_role):
        """Test assigning role with expiration date."""
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with patch.object(role_service, "get_user_role_assignment", new=AsyncMock(return_value=None)):
                with patch("mcpgateway.services.role_service.UserRole") as MockUserRole:
                    user_role = Mock()
                    MockUserRole.return_value = user_role

                    result = await role_service.assign_role_to_user(
                        user_email="user@example.com", role_id="role-123", scope="team", scope_id="team-789", granted_by="admin@example.com", expires_at=expires_at
                    )

                    MockUserRole.assert_called_once_with(user_email="user@example.com", role_id="role-123", scope="team", scope_id="team-789", granted_by="admin@example.com", expires_at=expires_at)

    @pytest.mark.asyncio
    async def test_assign_personal_role_with_scope_id(self, role_service, sample_role):
        """Test assigning personal role with scope_id."""
        sample_role.scope = "personal"

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with pytest.raises(ValueError, match="scope_id not allowed"):
                await role_service.assign_role_to_user(user_email="user@example.com", role_id="role-123", scope="personal", scope_id="should-not-have", granted_by="admin@example.com")


class TestRevokeRoleFromUser:
    """Test revoke_role_from_user method."""

    @pytest.mark.asyncio
    async def test_revoke_role_success(self, role_service, mock_db, sample_user_role):
        """Test successful role revocation."""
        sample_user_role.is_active = True

        with patch.object(role_service, "get_user_role_assignment", new=AsyncMock(return_value=sample_user_role)):
            result = await role_service.revoke_role_from_user(user_email="user@example.com", role_id="role-123", scope="team", scope_id="team-789")

            assert result is True
            assert sample_user_role.is_active is False
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_revoke_role_not_found(self, role_service):
        """Test revoking non-existent role assignment."""
        with patch.object(role_service, "get_user_role_assignment", new=AsyncMock(return_value=None)):
            result = await role_service.revoke_role_from_user(user_email="user@example.com", role_id="role-123", scope="team", scope_id="team-789")

            assert result is False

    @pytest.mark.asyncio
    async def test_revoke_inactive_role(self, role_service, sample_user_role):
        """Test revoking already inactive role assignment."""
        sample_user_role.is_active = False

        with patch.object(role_service, "get_user_role_assignment", new=AsyncMock(return_value=sample_user_role)):
            result = await role_service.revoke_role_from_user(user_email="user@example.com", role_id="role-123", scope="team", scope_id="team-789")

            assert result is False


class TestGetUserRoleAssignment:
    """Test get_user_role_assignment method."""

    @pytest.mark.asyncio
    async def test_get_user_role_assignment_found(self, role_service, mock_db, sample_user_role):
        """Test getting existing user role assignment."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = sample_user_role
        mock_db.execute.return_value = mock_result

        result = await role_service.get_user_role_assignment(user_email="user@example.com", role_id="role-123", scope="team", scope_id="team-789")

        assert result == sample_user_role

    @pytest.mark.asyncio
    async def test_get_user_role_assignment_not_found(self, role_service, mock_db):
        """Test getting non-existent user role assignment."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await role_service.get_user_role_assignment(user_email="user@example.com", role_id="role-123", scope="team", scope_id="team-789")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_role_assignment_no_scope_id(self, role_service, mock_db, sample_user_role):
        """Test getting user role assignment without scope_id."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = sample_user_role
        mock_db.execute.return_value = mock_result

        result = await role_service.get_user_role_assignment(user_email="user@example.com", role_id="role-123", scope="global", scope_id=None)

        assert result == sample_user_role


class TestListUserRoles:
    """Test list_user_roles method."""

    @pytest.mark.asyncio
    async def test_list_user_roles_all(self, role_service, mock_db):
        """Test listing all roles for a user."""
        user_roles = [Mock(spec=UserRole), Mock(spec=UserRole)]
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = user_roles
        mock_db.execute.return_value = mock_result

        result = await role_service.list_user_roles("user@example.com")

        assert result == user_roles

    @pytest.mark.asyncio
    async def test_list_user_roles_by_scope(self, role_service, mock_db):
        """Test listing user roles filtered by scope."""
        team_roles = [Mock(spec=UserRole)]
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = team_roles
        mock_db.execute.return_value = mock_result

        result = await role_service.list_user_roles("user@example.com", scope="team")

        assert result == team_roles

    @pytest.mark.asyncio
    async def test_list_user_roles_include_expired(self, role_service, mock_db):
        """Test listing user roles including expired ones."""
        all_roles = [Mock(spec=UserRole), Mock(spec=UserRole)]
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = all_roles
        mock_db.execute.return_value = mock_result

        result = await role_service.list_user_roles("user@example.com", include_expired=True)

        assert result == all_roles


class TestListRoleAssignments:
    """Test list_role_assignments method."""

    @pytest.mark.asyncio
    async def test_list_role_assignments_all(self, role_service, mock_db):
        """Test listing all assignments for a role."""
        assignments = [Mock(spec=UserRole), Mock(spec=UserRole)]
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = assignments
        mock_db.execute.return_value = mock_result

        result = await role_service.list_role_assignments("role-123")

        assert result == assignments

    @pytest.mark.asyncio
    async def test_list_role_assignments_by_scope(self, role_service, mock_db):
        """Test listing role assignments filtered by scope."""
        team_assignments = [Mock(spec=UserRole)]
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = team_assignments
        mock_db.execute.return_value = mock_result

        result = await role_service.list_role_assignments("role-123", scope="team")

        assert result == team_assignments

    @pytest.mark.asyncio
    async def test_list_role_assignments_include_expired(self, role_service, mock_db):
        """Test listing role assignments including expired ones."""
        all_assignments = [Mock(spec=UserRole), Mock(spec=UserRole)]
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = all_assignments
        mock_db.execute.return_value = mock_result

        result = await role_service.list_role_assignments("role-123", include_expired=True)

        assert result == all_assignments


class TestWouldCreateCycle:
    """Test _would_create_cycle method."""

    @pytest.mark.asyncio
    async def test_would_create_cycle_no_child(self, role_service):
        """Test cycle detection with no child_id."""
        result = await role_service._would_create_cycle("parent-id", None)
        assert result is False

    @pytest.mark.asyncio
    async def test_would_create_cycle_direct_cycle(self, role_service):
        """Test detection of direct cycle (A -> A)."""
        result = await role_service._would_create_cycle("role-123", "role-123")
        assert result is True

    @pytest.mark.asyncio
    async def test_would_create_cycle_indirect_cycle(self, role_service, mock_db):
        """Test detection of indirect cycle (A -> B -> C -> A)."""
        # Mock the chain: parent -> middle -> child
        # Trying to set child as parent of parent would create cycle
        mock_result1 = Mock()
        mock_result1.scalar_one_or_none.return_value = "middle-id"

        mock_result2 = Mock()
        mock_result2.scalar_one_or_none.return_value = "child-id"

        mock_result3 = Mock()
        mock_result3.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [mock_result1, mock_result2, mock_result3]

        result = await role_service._would_create_cycle("parent-id", "child-id")
        assert result is True

    @pytest.mark.asyncio
    async def test_would_create_cycle_no_cycle(self, role_service, mock_db):
        """Test when no cycle would be created."""
        # Mock a chain that doesn't create a cycle
        mock_result1 = Mock()
        mock_result1.scalar_one_or_none.return_value = "other-parent"

        mock_result2 = Mock()
        mock_result2.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [mock_result1, mock_result2]

        result = await role_service._would_create_cycle("parent-id", "child-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_would_create_cycle_with_visited_tracking(self, role_service, mock_db):
        """Test that visited nodes are tracked to prevent infinite loops."""
        # Create a scenario where we might visit the same node twice
        mock_result1 = Mock()
        mock_result1.scalar_one_or_none.return_value = "node-b"

        mock_result2 = Mock()
        mock_result2.scalar_one_or_none.return_value = "node-c"

        mock_result3 = Mock()
        mock_result3.scalar_one_or_none.return_value = "node-b"  # Already visited

        mock_db.execute.side_effect = [mock_result1, mock_result2, mock_result3]

        result = await role_service._would_create_cycle("node-a", "node-x")
        assert result is False  # Should stop when encountering visited node


class TestEdgeCasesAndErrorHandling:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_create_role_empty_permissions_list(self, role_service, mock_db):
        """Test creating role with empty permissions list."""
        with patch.object(role_service, "get_role_by_name", new=AsyncMock(return_value=None)):
            with patch("mcpgateway.services.role_service.Permissions.get_all_permissions", return_value=[]):
                with patch("mcpgateway.services.role_service.Role") as MockRole:
                    role = Mock(spec=Role)
                    MockRole.return_value = role

                    result = await role_service.create_role(name="empty-perms", description="Role with no permissions", scope="team", permissions=[], created_by="admin@example.com")

                    assert result == role
                    MockRole.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_role_with_none_values(self, role_service, mock_db, sample_role):
        """Test updating role with None values (should not update those fields)."""
        sample_role.is_system_role = False
        original_name = sample_role.name
        original_description = sample_role.description

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with patch("mcpgateway.services.role_service.utc_now", return_value=datetime.now(timezone.utc)):
                result = await role_service.update_role(role_id="role-123", name=None, description=None, permissions=None)

                assert result.name == original_name
                assert result.description == original_description
                mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_database_error_handling(self, role_service, mock_db):
        """Test handling of database errors."""
        mock_db.commit.side_effect = Exception("Database error")

        with patch.object(role_service, "get_role_by_name", new=AsyncMock(return_value=None)):
            with patch("mcpgateway.services.role_service.Permissions.get_all_permissions", return_value=[]):
                with patch("mcpgateway.services.role_service.Role") as MockRole:
                    MockRole.return_value = Mock(spec=Role)

                    with pytest.raises(Exception, match="Database error"):
                        await role_service.create_role(name="test", description="test", scope="global", permissions=[], created_by="admin@example.com")

    @pytest.mark.asyncio
    async def test_concurrent_role_assignment(self, role_service, mock_db, sample_role):
        """Test handling concurrent role assignments (race condition)."""
        # First check returns None, but by the time we try to create,
        # another process has created the assignment
        mock_db.commit.side_effect = Exception("Unique constraint violation")

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with patch.object(role_service, "get_user_role_assignment", new=AsyncMock(return_value=None)):
                with patch("mcpgateway.services.role_service.UserRole"):
                    with pytest.raises(Exception, match="Unique constraint violation"):
                        await role_service.assign_role_to_user(user_email="user@example.com", role_id="role-123", scope="team", scope_id="team-789", granted_by="admin@example.com")


class TestComplexScenarios:
    """Test complex real-world scenarios."""

    @pytest.mark.asyncio
    async def test_role_inheritance_chain(self, role_service, mock_db):
        """Test multiple levels of role inheritance."""
        # Create a chain: grandparent -> parent -> child
        grandparent = Mock(spec=Role)
        grandparent.id = "grandparent-id"
        grandparent.inherits_from = None

        parent = Mock(spec=Role)
        parent.id = "parent-id"
        parent.inherits_from = "grandparent-id"

        with patch.object(role_service, "get_role_by_name", new=AsyncMock(return_value=None)):
            with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=parent)):
                with patch.object(role_service, "_would_create_cycle", new=AsyncMock(return_value=False)):
                    with patch("mcpgateway.services.role_service.Permissions.get_all_permissions", return_value=[]):
                        with patch("mcpgateway.services.role_service.Role") as MockRole:
                            child = Mock(spec=Role)
                            MockRole.return_value = child

                            result = await role_service.create_role(
                                name="child-role", description="Child role", scope="team", permissions=[], created_by="admin@example.com", inherits_from="parent-id"
                            )

                            assert result == child

    @pytest.mark.asyncio
    async def test_bulk_role_operations(self, role_service, mock_db):
        """Test performing multiple role operations in sequence."""
        role1 = Mock(spec=Role)
        role1.id = "role1-id"
        role1.is_system_role = False
        role1.is_active = True

        role2 = Mock(spec=Role)
        role2.id = "role2-id"
        role2.is_system_role = False
        role2.is_active = True

        # Create first role
        with patch.object(role_service, "get_role_by_name", new=AsyncMock(return_value=None)):
            with patch("mcpgateway.services.role_service.Permissions.get_all_permissions", return_value=["perm1"]):
                with patch("mcpgateway.services.role_service.Role", return_value=role1):
                    r1 = await role_service.create_role(name="role1", description="First role", scope="global", permissions=["perm1"], created_by="admin@example.com")

        # Update first role
        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=role1)):
            with patch("mcpgateway.services.role_service.utc_now", return_value=datetime.now(timezone.utc)):
                r1_updated = await role_service.update_role(role_id="role1-id", description="Updated description")

        # Create second role inheriting from first
        with patch.object(role_service, "get_role_by_name", new=AsyncMock(return_value=None)):
            with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=role1)):
                with patch.object(role_service, "_would_create_cycle", new=AsyncMock(return_value=False)):
                    with patch("mcpgateway.services.role_service.Permissions.get_all_permissions", return_value=["perm1", "perm2"]):
                        with patch("mcpgateway.services.role_service.Role", return_value=role2):
                            r2 = await role_service.create_role(
                                name="role2", description="Second role", scope="global", permissions=["perm2"], created_by="admin@example.com", inherits_from="role1-id"
                            )

        assert r1 == role1
        assert r1_updated == role1
        assert r2 == role2

    @pytest.mark.asyncio
    async def test_expired_role_handling(self, role_service, mock_db, sample_user_role):
        """Test handling of expired role assignments."""
        # Set up an expired role
        sample_user_role.is_active = True
        sample_user_role.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        sample_user_role.is_expired.return_value = True

        # Test that expired role doesn't prevent new assignment
        sample_role = Mock(spec=Role)
        sample_role.id = "role-123"
        sample_role.scope = "team"
        sample_role.is_active = True

        with patch.object(role_service, "get_role_by_id", new=AsyncMock(return_value=sample_role)):
            with patch.object(role_service, "get_user_role_assignment", new=AsyncMock(return_value=sample_user_role)):
                with patch("mcpgateway.services.role_service.UserRole") as MockUserRole:
                    new_assignment = Mock()
                    MockUserRole.return_value = new_assignment

                    result = await role_service.assign_role_to_user(user_email="user@example.com", role_id="role-123", scope="team", scope_id="team-789", granted_by="admin@example.com")

                    assert result == new_assignment
                    mock_db.add.assert_called_once()
