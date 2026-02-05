# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_permission_service_comprehensive.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive unit tests for PermissionService to maximize coverage.
"""

# Standard
from datetime import timedelta
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import EmailTeamMember, PermissionAuditLog, Permissions, UserRole, utc_now
from mcpgateway.services.permission_service import PermissionService


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock(spec=Session)
    return session


@pytest.fixture
def permission_service(mock_db_session):
    """Create permission service instance with mock dependencies."""
    return PermissionService(mock_db_session, audit_enabled=True)


@pytest.fixture
def permission_service_no_audit(mock_db_session):
    """Create permission service instance without auditing."""
    return PermissionService(mock_db_session, audit_enabled=False)


class TestPermissionServiceCore:
    """Test core permission functionality."""

    @pytest.mark.asyncio
    async def test_check_permission_with_auditing(self, permission_service):
        """Test permission check with audit logging enabled."""
        user_email = "user@example.com"
        permission = "tools.create"

        # Mock dependencies
        with (
            patch.object(permission_service, "_is_user_admin", return_value=False),
            patch.object(permission_service, "get_user_permissions", return_value={permission}),
            patch.object(permission_service, "_log_permission_check") as mock_log,
            patch.object(permission_service, "_get_roles_for_audit", return_value={"roles": []}),
        ):
            result = await permission_service.check_permission(
                user_email=user_email, permission=permission, resource_type="tool", resource_id="tool-123", team_id="team-456", ip_address="192.168.1.1", user_agent="Mozilla/5.0"
            )

            assert result == True
            # Verify audit logging was called
            mock_log.assert_called_once()
            call_args = mock_log.call_args[1]
            assert call_args["user_email"] == user_email
            assert call_args["permission"] == permission
            assert call_args["granted"] == True
            assert call_args["ip_address"] == "192.168.1.1"
            assert call_args["user_agent"] == "Mozilla/5.0"

    @pytest.mark.asyncio
    async def test_check_permission_exception_handling(self, permission_service):
        """Test permission check handles exceptions gracefully."""
        # Make _is_user_admin raise an exception
        with patch.object(permission_service, "_is_user_admin", side_effect=Exception("Database error")):
            result = await permission_service.check_permission("user@example.com", "tools.read")
            # Should default to deny on error
            assert result == False

    @pytest.mark.asyncio
    async def test_check_permission_wildcard(self, permission_service):
        """Test permission check with wildcard permissions."""
        with patch.object(permission_service, "_is_user_admin", return_value=False), patch.object(permission_service, "get_user_permissions", return_value={Permissions.ALL_PERMISSIONS}):
            result = await permission_service.check_permission("user@example.com", "any.permission")
            assert result == True

    @pytest.mark.asyncio
    async def test_check_permission_team_fallback_not_called_for_non_team(self, permission_service):
        """Test fallback is not called for non-team permissions."""
        with (
            patch.object(permission_service, "_is_user_admin", return_value=False),
            patch.object(permission_service, "get_user_permissions", return_value=set()),
            patch.object(permission_service, "_check_team_fallback_permissions") as mock_fallback,
        ):
            result = await permission_service.check_permission("user@example.com", "tools.create")
            assert result == False
            # Fallback should not be called for non-team permissions
            mock_fallback.assert_not_called()


class TestPermissionCaching:
    """Test permission caching functionality."""

    @pytest.mark.asyncio
    async def test_get_user_permissions_uses_cache(self, permission_service):
        """Test that get_user_permissions uses cache when valid."""
        user_email = "cached@example.com"
        team_id = "team-123"
        cache_key = f"{user_email}:{team_id}"
        cached_permissions = {"tools.read", "resources.write"}

        # Set up cache
        permission_service._permission_cache[cache_key] = cached_permissions
        permission_service._cache_timestamps[cache_key] = utc_now()

        # Mock _is_cache_valid to return True
        with patch.object(permission_service, "_is_cache_valid", return_value=True):
            result = await permission_service.get_user_permissions(user_email, team_id)

            assert result == cached_permissions
            # Should not call database
            permission_service.db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_user_permissions_cache_miss(self, permission_service):
        """Test get_user_permissions when cache misses."""
        user_email = "nocache@example.com"
        team_id = "team-123"

        # Mock role with permissions
        mock_role = MagicMock()
        mock_role.get_effective_permissions.return_value = {"tools.read", "resources.read"}

        mock_user_role = MagicMock()
        mock_user_role.role = mock_role

        # Mock database query
        with patch.object(permission_service, "_is_cache_valid", return_value=False), patch.object(permission_service, "_get_user_roles", return_value=[mock_user_role]):
            result = await permission_service.get_user_permissions(user_email, team_id)

            assert "tools.read" in result
            assert "resources.read" in result

            # Check cache was populated
            cache_key = f"{user_email}:{team_id}"
            assert cache_key in permission_service._permission_cache
            assert cache_key in permission_service._cache_timestamps

    def test_is_cache_valid_no_cache(self, permission_service):
        """Test cache validity when cache doesn't exist."""
        assert permission_service._is_cache_valid("nonexistent") == False

    def test_is_cache_valid_missing_timestamp(self, permission_service):
        """Test cache validity when timestamp is missing."""
        permission_service._permission_cache["key"] = {"permission"}
        assert permission_service._is_cache_valid("key") == False

    def test_is_cache_valid_expired(self, permission_service):
        """Test cache validity when cache is expired."""
        cache_key = "expired"
        permission_service._permission_cache[cache_key] = {"permission"}
        # Set timestamp to be older than TTL
        permission_service._cache_timestamps[cache_key] = utc_now() - timedelta(seconds=permission_service.cache_ttl + 1)

        assert permission_service._is_cache_valid(cache_key) == False

    def test_is_cache_valid_fresh(self, permission_service):
        """Test cache validity when cache is fresh."""
        cache_key = "fresh"
        permission_service._permission_cache[cache_key] = {"permission"}
        permission_service._cache_timestamps[cache_key] = utc_now()

        assert permission_service._is_cache_valid(cache_key) == True

    def test_clear_user_cache(self, permission_service):
        """Test clearing cache for specific user."""
        # Set up cache for multiple users
        permission_service._permission_cache = {
            "alice@example.com:global": {"tools.read"},
            "alice@example.com:team1": {"resources.write"},
            "bob@example.com:global": {"admin"},
        }
        permission_service._cache_timestamps = {
            "alice@example.com:global": utc_now(),
            "alice@example.com:team1": utc_now(),
            "bob@example.com:global": utc_now(),
        }

        # Clear Alice's cache
        permission_service.clear_user_cache("alice@example.com")

        # Alice's entries should be removed
        assert "alice@example.com:global" not in permission_service._permission_cache
        assert "alice@example.com:team1" not in permission_service._permission_cache
        assert "alice@example.com:global" not in permission_service._cache_timestamps
        assert "alice@example.com:team1" not in permission_service._cache_timestamps

        # Bob's entries should remain
        assert "bob@example.com:global" in permission_service._permission_cache
        assert "bob@example.com:global" in permission_service._cache_timestamps

    def test_clear_cache(self, permission_service):
        """Test clearing all cache."""
        # Set up cache
        permission_service._permission_cache = {
            "user1:global": {"perm1"},
            "user2:team": {"perm2"},
        }
        permission_service._cache_timestamps = {
            "user1:global": utc_now(),
            "user2:team": utc_now(),
        }

        # Clear all cache
        permission_service.clear_cache()

        assert permission_service._permission_cache == {}
        assert permission_service._cache_timestamps == {}


class TestUserRoles:
    """Test user role retrieval functionality."""

    @pytest.mark.asyncio
    async def test_get_user_roles_with_filters(self, permission_service):
        """Test get_user_roles with various filters."""
        user_email = "user@example.com"

        # Mock database result
        mock_result = MagicMock()
        mock_roles = [MagicMock(spec=UserRole), MagicMock(spec=UserRole)]
        mock_result.scalars.return_value.all.return_value = mock_roles
        permission_service.db.execute.return_value = mock_result

        # Test with scope filter
        result = await permission_service.get_user_roles(user_email, scope="global")
        assert result == mock_roles

        # Test with team_id filter
        result = await permission_service.get_user_roles(user_email, team_id="team-123")
        assert result == mock_roles

        # Test with include_expired
        result = await permission_service.get_user_roles(user_email, include_expired=True)
        assert result == mock_roles

    @pytest.mark.asyncio
    async def test_get_user_roles_internal(self, permission_service):
        """Test internal _get_user_roles method."""
        user_email = "user@example.com"
        team_id = "team-123"

        # Mock database result (contains_eager requires .unique() before .scalars())
        mock_result = MagicMock()
        mock_roles = [MagicMock(spec=UserRole)]
        mock_result.unique.return_value.scalars.return_value.all.return_value = mock_roles
        permission_service.db.execute.return_value = mock_result

        result = await permission_service._get_user_roles(user_email, team_id)
        assert result == mock_roles

        # Verify query was built correctly (team_id should be included)
        permission_service.db.execute.assert_called_once()


class TestResourcePermissions:
    """Test resource-specific permission checking."""

    @pytest.mark.asyncio
    async def test_has_permission_on_resource_granted(self, permission_service):
        """Test has_permission_on_resource when permission is granted."""
        with patch.object(permission_service, "check_permission", return_value=True):
            result = await permission_service.has_permission_on_resource(user_email="user@example.com", permission="tools.read", resource_type="tool", resource_id="tool-123", team_id="team-456")
            assert result == True

    @pytest.mark.asyncio
    async def test_has_permission_on_resource_denied(self, permission_service):
        """Test has_permission_on_resource when permission is denied."""
        with patch.object(permission_service, "check_permission", return_value=False):
            result = await permission_service.has_permission_on_resource(user_email="user@example.com", permission="tools.read", resource_type="tool", resource_id="tool-123")
            assert result == False


class TestAdminPermissions:
    """Test admin permission checking."""

    @pytest.mark.asyncio
    async def test_check_admin_permission_platform_admin(self, permission_service):
        """Test check_admin_permission for platform admin."""
        with patch.object(permission_service, "_is_user_admin", return_value=True):
            result = await permission_service.check_admin_permission("admin@example.com")
            assert result == True

    @pytest.mark.asyncio
    async def test_check_admin_permission_with_admin_perms(self, permission_service):
        """Test check_admin_permission for user with admin permissions."""
        admin_perms = {Permissions.ADMIN_SYSTEM_CONFIG, "other.permission"}

        with patch.object(permission_service, "_is_user_admin", return_value=False), patch.object(permission_service, "get_user_permissions", return_value=admin_perms):
            result = await permission_service.check_admin_permission("user@example.com")
            assert result == True

    @pytest.mark.asyncio
    async def test_check_admin_permission_no_admin_perms(self, permission_service):
        """Test check_admin_permission for regular user."""
        regular_perms = {"tools.read", "resources.write"}

        with patch.object(permission_service, "_is_user_admin", return_value=False), patch.object(permission_service, "get_user_permissions", return_value=regular_perms):
            result = await permission_service.check_admin_permission("user@example.com")
            assert result == False


class TestAuditLogging:
    """Test permission audit logging."""

    @pytest.mark.asyncio
    async def test_log_permission_check(self, permission_service):
        """Test _log_permission_check creates audit log."""
        # Call the logging method
        await permission_service._log_permission_check(
            user_email="user@example.com",
            permission="tools.create",
            resource_type="tool",
            resource_id="tool-123",
            team_id="team-456",
            granted=True,
            roles_checked={"roles": []},
            ip_address="192.168.1.1",
            user_agent="TestAgent",
        )

        # Verify audit log was added to database
        permission_service.db.add.assert_called_once()
        permission_service.db.commit.assert_called_once()

        # Check the audit log object
        audit_log = permission_service.db.add.call_args[0][0]
        assert isinstance(audit_log, PermissionAuditLog)
        assert audit_log.user_email == "user@example.com"
        assert audit_log.permission == "tools.create"
        assert audit_log.granted == True

    @pytest.mark.asyncio
    async def test_get_roles_for_audit(self, permission_service):
        """Test _get_roles_for_audit returns role information from roles cache."""
        # Mock user roles
        mock_role = MagicMock()
        mock_role.id = "role-123"
        mock_role.name = "TestRole"
        mock_role.permissions = ["tools.read"]

        mock_user_role = MagicMock()
        mock_user_role.role_id = "role-123"
        mock_user_role.role = mock_role
        mock_user_role.scope = "global"

        # Populate the roles cache (normally done by get_user_permissions)
        permission_service._roles_cache["user@example.com:global"] = [mock_user_role]

        result = permission_service._get_roles_for_audit("user@example.com", None)

        assert "roles" in result
        assert len(result["roles"]) == 1
        assert result["roles"][0]["id"] == "role-123"
        assert result["roles"][0]["name"] == "TestRole"
        assert result["roles"][0]["scope"] == "global"


class TestTeamFallbackPermissions:
    """Test team fallback permission logic."""

    @pytest.mark.asyncio
    async def test_team_fallback_global_create(self, permission_service):
        """Test fallback allows global team creation."""
        result = await permission_service._check_team_fallback_permissions("user@example.com", "teams.create", None)
        assert result == True

    @pytest.mark.asyncio
    async def test_team_fallback_global_read(self, permission_service):
        """Test fallback allows global team read."""
        result = await permission_service._check_team_fallback_permissions("user@example.com", "teams.read", None)
        assert result == True

    @pytest.mark.asyncio
    async def test_team_fallback_global_denied(self, permission_service):
        """Test fallback denies other global team operations."""
        result = await permission_service._check_team_fallback_permissions("user@example.com", "teams.delete", None)
        assert result == False

    @pytest.mark.asyncio
    async def test_team_fallback_unknown_role(self, permission_service):
        """Test fallback with unknown team role."""
        with patch.object(permission_service, "_is_team_member", return_value=True), patch.object(permission_service, "_get_user_team_role", return_value="unknown"):
            result = await permission_service._check_team_fallback_permissions("user@example.com", "teams.read", "team-123")
            assert result == False


class TestTeamMembership:
    """Test team membership checking."""

    @pytest.mark.asyncio
    async def test_is_team_member_true(self, permission_service):
        """Test _is_team_member when user is a member."""
        mock_member = MagicMock(spec=EmailTeamMember)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_member
        permission_service.db.execute.return_value = mock_result

        result = await permission_service._is_team_member("user@example.com", "team-123")
        assert result == True

    @pytest.mark.asyncio
    async def test_is_team_member_false(self, permission_service):
        """Test _is_team_member when user is not a member."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        permission_service.db.execute.return_value = mock_result

        result = await permission_service._is_team_member("user@example.com", "team-123")
        assert result == False

    @pytest.mark.asyncio
    async def test_get_user_team_role_owner(self, permission_service):
        """Test _get_user_team_role returns owner role."""
        mock_member = MagicMock(spec=EmailTeamMember)
        mock_member.role = "owner"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_member
        permission_service.db.execute.return_value = mock_result

        result = await permission_service._get_user_team_role("user@example.com", "team-123")
        assert result == "owner"

    @pytest.mark.asyncio
    async def test_get_user_team_role_none(self, permission_service):
        """Test _get_user_team_role when user is not a member."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        permission_service.db.execute.return_value = mock_result

        result = await permission_service._get_user_team_role("user@example.com", "team-123")
        assert result is None


class TestNoAuditMode:
    """Test permission service without audit logging."""

    @pytest.mark.asyncio
    async def test_check_permission_no_audit(self, permission_service_no_audit):
        """Test permission check without audit logging."""
        with (
            patch.object(permission_service_no_audit, "_is_user_admin", return_value=False),
            patch.object(permission_service_no_audit, "get_user_permissions", return_value={"tools.read"}),
            patch.object(permission_service_no_audit, "_log_permission_check") as mock_log,
        ):
            result = await permission_service_no_audit.check_permission("user@example.com", "tools.read")

            assert result == True
            # Audit logging should not be called
            mock_log.assert_not_called()


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_empty_user_permissions(self, permission_service):
        """Test handling of empty user permissions."""
        with patch.object(permission_service, "_is_user_admin", return_value=False), patch.object(permission_service, "get_user_permissions", return_value=set()):
            result = await permission_service.check_permission("user@example.com", "tools.read")
            assert result == False

    @pytest.mark.asyncio
    async def test_multiple_roles_permissions_merge(self, permission_service):
        """Test that permissions from multiple roles are merged correctly."""
        # Mock multiple roles with different permissions
        mock_role1 = MagicMock()
        mock_role1.get_effective_permissions.return_value = {"tools.read", "tools.write"}

        mock_role2 = MagicMock()
        mock_role2.get_effective_permissions.return_value = {"resources.read", "tools.write"}

        mock_user_role1 = MagicMock()
        mock_user_role1.role = mock_role1

        mock_user_role2 = MagicMock()
        mock_user_role2.role = mock_role2

        with patch.object(permission_service, "_is_cache_valid", return_value=False), patch.object(permission_service, "_get_user_roles", return_value=[mock_user_role1, mock_user_role2]):
            result = await permission_service.get_user_permissions("user@example.com")

            # Should have all unique permissions from both roles
            assert "tools.read" in result
            assert "tools.write" in result
            assert "resources.read" in result
            assert len(result) == 3

    @pytest.mark.asyncio
    async def test_cache_key_format(self, permission_service):
        """Test cache key format for different scenarios."""
        # Global context
        cache_key = "user@example.com:global"
        assert ":" in cache_key
        assert cache_key.endswith("global")

        # Team context
        team_cache_key = "user@example.com:team-123"
        assert ":" in team_cache_key
        assert team_cache_key.endswith("team-123")

    def test_clear_cache_empty(self, permission_service):
        """Test clearing already empty cache."""
        permission_service.clear_cache()
        assert permission_service._permission_cache == {}
        assert permission_service._cache_timestamps == {}

    def test_clear_user_cache_nonexistent(self, permission_service):
        """Test clearing cache for nonexistent user."""
        permission_service._permission_cache = {"other@example.com:global": {"perm"}}
        permission_service.clear_user_cache("nonexistent@example.com")
        # Should not affect other users
        assert "other@example.com:global" in permission_service._permission_cache
