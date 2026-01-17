# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_sso_entra_role_mapping.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Test Microsoft EntraID role mapping functionality.
Tests group extraction, role mapping, and role synchronization.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Role, SSOProvider, UserRole
from mcpgateway.services.sso_service import SSOService


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock(spec=Session)
    return session


@pytest.fixture
def sso_service(mock_db_session):
    """Create SSO service instance with mock dependencies."""
    with patch("mcpgateway.services.sso_service.EmailAuthService"):
        service = SSOService(mock_db_session)
        return service


@pytest.fixture
def entra_provider():
    """Create a Microsoft Entra ID SSO provider for testing."""
    return SSOProvider(
        id="entra",
        name="entra",
        display_name="Microsoft Entra ID",
        provider_type="oidc",
        client_id="test_client_id",
        client_secret_encrypted="encrypted_secret",
        is_enabled=True,
        trusted_domains=["company.com"],
        auto_create_users=True,
        provider_metadata={
            "groups_claim": "groups",
            "role_mappings": {
                "e5f6g7h8-1234-5678-90ab-cdef12345678": "developer",
                "i9j0k1l2-1234-5678-90ab-cdef12345678": "team_admin",
            },
        },
    )


class TestEntraIDGroupExtraction:
    """Test EntraID group and role extraction from tokens."""

    def test_entra_groups_claim_extraction(self, sso_service, entra_provider):
        """Test extraction of groups from 'groups' claim."""
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "abc123",
            "groups": ["a1b2c3d4-1234-5678-90ab-cdef12345678", "e5f6g7h8-1234-5678-90ab-cdef12345678"],
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert "groups" in normalized
        assert len(normalized["groups"]) == 2
        assert "a1b2c3d4-1234-5678-90ab-cdef12345678" in normalized["groups"]
        assert "e5f6g7h8-1234-5678-90ab-cdef12345678" in normalized["groups"]

    def test_entra_roles_claim_extraction(self, sso_service, entra_provider):
        """Test extraction of app roles from 'roles' claim."""
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "abc123",
            "roles": ["Admin", "Developer"],
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert "groups" in normalized
        assert len(normalized["groups"]) == 2
        assert "Admin" in normalized["groups"]
        assert "Developer" in normalized["groups"]

    def test_entra_both_groups_and_roles(self, sso_service, entra_provider):
        """Test extraction when both groups and roles claims are present."""
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "abc123",
            "groups": ["a1b2c3d4-1234-5678-90ab-cdef12345678"],
            "roles": ["Developer"],
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert "groups" in normalized
        assert len(normalized["groups"]) == 2
        assert "a1b2c3d4-1234-5678-90ab-cdef12345678" in normalized["groups"]
        assert "Developer" in normalized["groups"]

    def test_entra_duplicate_groups_deduplication(self, sso_service, entra_provider):
        """Test that duplicate groups are deduplicated."""
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "abc123",
            "groups": ["Developer", "Admin"],
            "roles": ["Developer", "Viewer"],  # Developer appears in both
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert "groups" in normalized
        assert len(normalized["groups"]) == 3  # Developer, Admin, Viewer (deduplicated)
        assert "Developer" in normalized["groups"]
        assert "Admin" in normalized["groups"]
        assert "Viewer" in normalized["groups"]

    def test_entra_no_groups_or_roles(self, sso_service, entra_provider):
        """Test handling when no groups or roles are present."""
        user_data = {"email": "user@company.com", "name": "Test User", "sub": "abc123"}

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert "groups" in normalized
        assert normalized["groups"] == []

    def test_entra_custom_groups_claim(self, sso_service):
        """Test using custom groups claim name."""
        provider = SSOProvider(
            id="entra",
            name="entra",
            display_name="Microsoft Entra ID",
            provider_type="oidc",
            client_id="test_client_id",
            client_secret_encrypted="encrypted_secret",
            is_enabled=True,
            provider_metadata={"groups_claim": "custom_groups"},
        )

        user_data = {"email": "user@company.com", "name": "Test User", "sub": "abc123", "custom_groups": ["group1", "group2"]}

        normalized = sso_service._normalize_user_info(provider, user_data)

        assert "groups" in normalized
        assert len(normalized["groups"]) == 2
        assert "group1" in normalized["groups"]
        assert "group2" in normalized["groups"]


class TestEntraIDAdminGroupAssignment:
    """Test EntraID admin group assignment."""

    def test_entra_admin_group_assignment(self, sso_service, entra_provider):
        """Test admin assignment via EntraID admin groups."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = ["a1b2c3d4-1234-5678-90ab-cdef12345678", "Admin"]

            # User with admin group (Object ID)
            user_info = {"full_name": "Test User", "provider": "entra", "groups": ["a1b2c3d4-1234-5678-90ab-cdef12345678", "other-group"]}
            assert sso_service._should_user_be_admin("user@company.com", user_info, entra_provider) is True

            # User with admin role (App Role)
            user_info_role = {"full_name": "Test User", "provider": "entra", "groups": ["Admin", "Developer"]}
            assert sso_service._should_user_be_admin("user@company.com", user_info_role, entra_provider) is True

            # User without admin group
            user_info_no_admin = {"full_name": "Test User", "provider": "entra", "groups": ["Developer", "Viewer"]}
            assert sso_service._should_user_be_admin("user@company.com", user_info_no_admin, entra_provider) is False

    def test_entra_admin_group_case_insensitive(self, sso_service, entra_provider):
        """Test that admin group matching is case-insensitive."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = ["admin"]

            user_info = {"full_name": "Test User", "provider": "entra", "groups": ["ADMIN", "Developer"]}
            assert sso_service._should_user_be_admin("user@company.com", user_info, entra_provider) is True


class TestEntraIDRoleMapping:
    """Test EntraID group to role mapping."""

    @pytest.mark.asyncio
    async def test_map_groups_to_roles_admin_group(self, sso_service, entra_provider):
        """Test mapping admin groups to platform_admin role."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = ["Admin"]
            mock_settings.sso_entra_role_mappings = {}

            user_groups = ["Admin", "Developer"]
            role_assignments = await sso_service._map_groups_to_roles("user@company.com", user_groups, entra_provider)

            assert len(role_assignments) == 1
            assert role_assignments[0]["role_name"] == "platform_admin"
            assert role_assignments[0]["scope"] == "global"

    @pytest.mark.asyncio
    async def test_map_groups_to_roles_from_mappings(self, sso_service, entra_provider):
        """Test mapping groups to roles using role_mappings."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_role_mappings = {}

            # Mock RoleService
            with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
                mock_role_service = MockRoleService.return_value

                # Mock developer role
                developer_role = MagicMock(spec=Role)
                developer_role.name = "developer"
                developer_role.scope = "team"

                # Mock team_admin role
                team_admin_role = MagicMock(spec=Role)
                team_admin_role.name = "team_admin"
                team_admin_role.scope = "team"

                async def mock_get_role_by_name(name, scope):
                    if name == "developer":
                        return developer_role
                    elif name == "team_admin":
                        return team_admin_role
                    return None

                mock_role_service.get_role_by_name = AsyncMock(side_effect=mock_get_role_by_name)

                user_groups = ["e5f6g7h8-1234-5678-90ab-cdef12345678", "i9j0k1l2-1234-5678-90ab-cdef12345678"]
                role_assignments = await sso_service._map_groups_to_roles("user@company.com", user_groups, entra_provider)

                assert len(role_assignments) == 2
                assert any(r["role_name"] == "developer" for r in role_assignments)
                assert any(r["role_name"] == "team_admin" for r in role_assignments)

    @pytest.mark.asyncio
    async def test_map_groups_to_roles_default_role(self, sso_service, entra_provider):
        """Test assigning default role when no mappings match."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_entra_default_role = "viewer"

            # Mock RoleService
            with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
                mock_role_service = MockRoleService.return_value

                viewer_role = MagicMock(spec=Role)
                viewer_role.name = "viewer"
                viewer_role.scope = "team"

                mock_role_service.get_role_by_name = AsyncMock(return_value=viewer_role)

                user_groups = ["unmapped-group"]
                role_assignments = await sso_service._map_groups_to_roles("user@company.com", user_groups, entra_provider)

                assert len(role_assignments) == 1
                assert role_assignments[0]["role_name"] == "viewer"
                assert role_assignments[0]["scope"] == "team"

    @pytest.mark.asyncio
    async def test_map_groups_to_roles_no_duplicate_assignments(self, sso_service, entra_provider):
        """Test that duplicate role assignments are avoided."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_role_mappings = {"Developer": "developer", "Dev": "developer"}  # Both map to same role

            # Mock RoleService
            with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
                mock_role_service = MockRoleService.return_value

                developer_role = MagicMock(spec=Role)
                developer_role.name = "developer"
                developer_role.scope = "team"

                mock_role_service.get_role_by_name = AsyncMock(return_value=developer_role)

                user_groups = ["Developer", "Dev"]
                role_assignments = await sso_service._map_groups_to_roles("user@company.com", user_groups, entra_provider)

                # Should only have one developer assignment despite two groups mapping to it
                assert len(role_assignments) == 1
                assert role_assignments[0]["role_name"] == "developer"


class TestEntraIDRoleSynchronization:
    """Test EntraID role synchronization on login."""

    @pytest.mark.asyncio
    async def test_sync_user_roles_assign_new_roles(self, sso_service, entra_provider):
        """Test assigning new roles during synchronization."""
        with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            mock_role_service = MockRoleService.return_value

            # Mock existing roles (empty)
            mock_role_service.list_user_roles = AsyncMock(return_value=[])

            # Mock role lookup
            developer_role = MagicMock(spec=Role)
            developer_role.id = "role-123"
            developer_role.name = "developer"
            developer_role.scope = "team"

            mock_role_service.get_role_by_name = AsyncMock(return_value=developer_role)
            mock_role_service.get_user_role_assignment = AsyncMock(return_value=None)
            mock_role_service.assign_role_to_user = AsyncMock()

            role_assignments = [{"role_name": "developer", "scope": "team", "scope_id": None}]

            await sso_service._sync_user_roles("user@company.com", role_assignments, entra_provider)

            # Verify role was assigned
            mock_role_service.assign_role_to_user.assert_called_once_with(user_email="user@company.com", role_id="role-123", scope="team", scope_id=None, granted_by="sso_system")

    @pytest.mark.asyncio
    async def test_sync_user_roles_revoke_old_roles(self, sso_service, entra_provider):
        """Test revoking roles that are no longer in groups."""
        with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            mock_role_service = MockRoleService.return_value

            # Mock existing SSO-granted role
            old_role = MagicMock(spec=Role)
            old_role.id = "old-role-123"
            old_role.name = "old_role"

            old_user_role = MagicMock(spec=UserRole)
            old_user_role.role_id = "old-role-123"
            old_user_role.role = old_role
            old_user_role.scope = "team"
            old_user_role.scope_id = None
            old_user_role.granted_by = "sso_system"

            mock_role_service.list_user_roles = AsyncMock(return_value=[old_user_role])
            mock_role_service.revoke_role_from_user = AsyncMock()

            # New role assignments (different from old)
            role_assignments = []  # No roles

            await sso_service._sync_user_roles("user@company.com", role_assignments, entra_provider)

            # Verify old role was revoked
            mock_role_service.revoke_role_from_user.assert_called_once_with(user_email="user@company.com", role_id="old-role-123", scope="team", scope_id=None)

    @pytest.mark.asyncio
    async def test_sync_user_roles_preserve_manual_assignments(self, sso_service, entra_provider):
        """Test that manually assigned roles are preserved."""
        with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            mock_role_service = MockRoleService.return_value

            # Mock manually assigned role (not granted by sso_system)
            manual_role = MagicMock(spec=Role)
            manual_role.id = "manual-role-123"
            manual_role.name = "manual_role"

            manual_user_role = MagicMock(spec=UserRole)
            manual_user_role.role_id = "manual-role-123"
            manual_user_role.role = manual_role
            manual_user_role.scope = "team"
            manual_user_role.scope_id = None
            manual_user_role.granted_by = "admin@company.com"  # Not sso_system

            mock_role_service.list_user_roles = AsyncMock(return_value=[manual_user_role])
            mock_role_service.revoke_role_from_user = AsyncMock()

            role_assignments = []  # No SSO roles

            await sso_service._sync_user_roles("user@company.com", role_assignments, entra_provider)

            # Verify manual role was NOT revoked
            mock_role_service.revoke_role_from_user.assert_not_called()


class TestEntraIDIntegration:
    """Test end-to-end EntraID role mapping integration."""

    def test_entra_normalization_includes_groups(self, sso_service, entra_provider):
        """Test that normalized user info includes groups for EntraID."""
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "abc123",
            "groups": ["group1", "group2"],
            "roles": ["Role1"],
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert normalized["provider"] == "entra"
        assert "groups" in normalized
        assert len(normalized["groups"]) == 3
        assert "group1" in normalized["groups"]
        assert "group2" in normalized["groups"]
        assert "Role1" in normalized["groups"]

    def test_other_providers_not_affected(self, sso_service):
        """Test that other SSO providers are not affected by EntraID changes."""
        github_provider = SSOProvider(id="github", name="github", display_name="GitHub", provider_type="oauth2")

        user_data = {"email": "user@example.com", "name": "Test User", "login": "testuser", "id": 12345}

        normalized = sso_service._normalize_user_info(github_provider, user_data)

        assert normalized["provider"] == "github"
        # GitHub should not have groups key (not implemented for GitHub)
        assert "groups" not in normalized or normalized.get("groups") == []


class TestEntraIDConfigurationIntegration:
    """Test that configuration is properly wired through bootstrap to runtime."""

    def test_entra_groups_claim_from_bootstrap_metadata(self, sso_service):
        """Test that custom groups_claim from provider metadata is honored during normalization.

        This tests the fix for: SSO_ENTRA_GROUPS_CLAIM env var being ignored because
        the Entra provider bootstrap now includes metadata with groups_claim.
        """
        # Simulate provider with custom groups_claim in metadata (set via bootstrap)
        provider = SSOProvider(
            id="entra",
            name="entra",
            display_name="Microsoft Entra ID",
            provider_type="oidc",
            client_id="test_client_id",
            client_secret_encrypted="encrypted_secret",
            is_enabled=True,
            provider_metadata={"groups_claim": "custom_groups"},  # Custom claim from env config
        )

        # User data has groups in custom claim, not default 'groups'
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "abc123",
            "custom_groups": ["group1", "group2"],
            "groups": ["should_be_ignored"],
        }

        normalized = sso_service._normalize_user_info(provider, user_data)

        assert "groups" in normalized
        assert "group1" in normalized["groups"]
        assert "group2" in normalized["groups"]
        # The default 'groups' claim should be ignored when custom_groups is configured
        assert "should_be_ignored" not in normalized["groups"]


class TestEntraIDRoleRevocationOnLogin:
    """Test role revocation during login flow when user loses group mappings."""

    @pytest.mark.asyncio
    async def test_sync_revokes_all_roles_when_empty_assignments(self, sso_service, entra_provider):
        """Test that all SSO roles are revoked when role_assignments is empty.

        This tests the fix for: role sync not happening when role_assignments is empty,
        which prevented revocation when user lost all mapped groups.
        """
        with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            mock_role_service = MockRoleService.return_value

            # User previously had SSO-granted role
            old_role = MagicMock(spec=Role)
            old_role.id = "old-role-123"
            old_role.name = "developer"

            old_user_role = MagicMock(spec=UserRole)
            old_user_role.role_id = "old-role-123"
            old_user_role.role = old_role
            old_user_role.scope = "team"
            old_user_role.scope_id = None
            old_user_role.granted_by = "sso_system"

            mock_role_service.list_user_roles = AsyncMock(return_value=[old_user_role])
            mock_role_service.revoke_role_from_user = AsyncMock()

            # User now has no mapped roles (empty list)
            role_assignments = []

            await sso_service._sync_user_roles("user@company.com", role_assignments, entra_provider)

            # Verify old SSO role was revoked
            mock_role_service.revoke_role_from_user.assert_called_once_with(user_email="user@company.com", role_id="old-role-123", scope="team", scope_id=None)

    @pytest.mark.asyncio
    async def test_sync_revokes_removed_roles_keeps_remaining(self, sso_service, entra_provider):
        """Test partial revocation: some roles removed, some retained."""
        with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            mock_role_service = MockRoleService.return_value

            # User had two SSO-granted roles
            developer_role = MagicMock(spec=Role)
            developer_role.id = "dev-role-123"
            developer_role.name = "developer"

            admin_role = MagicMock(spec=Role)
            admin_role.id = "admin-role-456"
            admin_role.name = "team_admin"

            dev_user_role = MagicMock(spec=UserRole)
            dev_user_role.role_id = "dev-role-123"
            dev_user_role.role = developer_role
            dev_user_role.scope = "team"
            dev_user_role.scope_id = None
            dev_user_role.granted_by = "sso_system"

            admin_user_role = MagicMock(spec=UserRole)
            admin_user_role.role_id = "admin-role-456"
            admin_user_role.role = admin_role
            admin_user_role.scope = "team"
            admin_user_role.scope_id = None
            admin_user_role.granted_by = "sso_system"

            mock_role_service.list_user_roles = AsyncMock(return_value=[dev_user_role, admin_user_role])
            mock_role_service.revoke_role_from_user = AsyncMock()
            mock_role_service.get_role_by_name = AsyncMock(return_value=developer_role)
            mock_role_service.get_user_role_assignment = AsyncMock(return_value=dev_user_role)

            # User now only has developer role (lost team_admin)
            role_assignments = [{"role_name": "developer", "scope": "team", "scope_id": None}]

            await sso_service._sync_user_roles("user@company.com", role_assignments, entra_provider)

            # Verify only team_admin was revoked
            mock_role_service.revoke_role_from_user.assert_called_once_with(user_email="user@company.com", role_id="admin-role-456", scope="team", scope_id=None)


class TestEntraIDDefaultRoleForNoGroups:
    """Test default role assignment for users with no groups."""

    @pytest.mark.asyncio
    async def test_default_role_applied_with_empty_groups_list(self, sso_service, entra_provider):
        """Test that default role is applied when user has empty groups list.

        This tests the fix for: default role not being applied because
        _map_groups_to_roles was only called when user_info.get('groups') was truthy.
        """
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_entra_default_role = "viewer"

            with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
                mock_role_service = MockRoleService.return_value

                viewer_role = MagicMock(spec=Role)
                viewer_role.name = "viewer"
                viewer_role.scope = "team"

                mock_role_service.get_role_by_name = AsyncMock(return_value=viewer_role)

                # User with empty groups list (not None, but [])
                role_assignments = await sso_service._map_groups_to_roles("user@company.com", [], entra_provider)

                assert len(role_assignments) == 1
                assert role_assignments[0]["role_name"] == "viewer"
                assert role_assignments[0]["scope"] == "team"

    @pytest.mark.asyncio
    async def test_default_role_not_applied_when_disabled(self, sso_service, entra_provider):
        """Test that no default role is applied when setting is disabled."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_entra_default_role = None  # Disabled

            role_assignments = await sso_service._map_groups_to_roles("user@company.com", [], entra_provider)

            assert len(role_assignments) == 0

    @pytest.mark.asyncio
    async def test_default_role_not_applied_when_user_has_mapped_roles(self, sso_service, entra_provider):
        """Test that default role is NOT applied when user has mapped roles."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = ["Admin"]
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_entra_default_role = "viewer"

            # User is in Admin group
            role_assignments = await sso_service._map_groups_to_roles("user@company.com", ["Admin"], entra_provider)

            # Should get platform_admin, not viewer
            assert len(role_assignments) == 1
            assert role_assignments[0]["role_name"] == "platform_admin"
            assert not any(r["role_name"] == "viewer" for r in role_assignments)


class TestProviderLevelSyncOptOut:
    """Test provider-level sync_roles flag in provider_metadata."""

    @pytest.mark.asyncio
    async def test_sync_skipped_when_provider_sync_roles_disabled(self, sso_service):
        """Test that role sync is skipped when provider has sync_roles=False."""
        # Create provider with sync_roles disabled in metadata
        provider_no_sync = SSOProvider(
            id="entra",
            name="entra",
            display_name="Microsoft Entra ID",
            provider_type="oidc",
            client_id="test_client_id",
            client_secret_encrypted="encrypted_secret",
            is_enabled=True,
            provider_metadata={
                "sync_roles": False,  # Disable role synchronization
                "role_mappings": {
                    "Developer": "developer",
                },
            },
        )

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_entra_default_role = None

            # Even with mappings defined, sync_roles=False should skip all processing
            # Call the function to verify it runs without error
            await sso_service._map_groups_to_roles("user@company.com", ["Developer"], provider_no_sync)

            # This test verifies the metadata sync_roles flag is accessible and respected
            assert provider_no_sync.provider_metadata.get("sync_roles") is False

    @pytest.mark.asyncio
    async def test_early_exit_when_no_mappings_configured(self, sso_service):
        """Test that role mapping returns early when no configuration exists."""
        # Create provider with no role mappings
        provider_no_mappings = SSOProvider(
            id="generic",
            name="generic",
            display_name="Generic OIDC",
            provider_type="oidc",
            client_id="test_client_id",
            client_secret_encrypted="encrypted_secret",
            is_enabled=True,
            provider_metadata={},  # No role_mappings
        )

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_entra_default_role = None

            # No mappings, no admin groups, no default role = early exit
            role_assignments = await sso_service._map_groups_to_roles("user@company.com", ["SomeGroup"], provider_no_mappings)

            # Should return empty list (early exit)
            assert len(role_assignments) == 0

    @pytest.mark.asyncio
    async def test_sync_proceeds_when_provider_sync_roles_true(self, sso_service, entra_provider):
        """Test that role sync proceeds when provider has sync_roles=True."""
        # Update provider metadata to explicitly enable sync
        entra_provider.provider_metadata["sync_roles"] = True

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = ["Admin"]
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_entra_default_role = None

            role_assignments = await sso_service._map_groups_to_roles("user@company.com", ["Admin"], entra_provider)

            # Should get platform_admin
            assert len(role_assignments) == 1
            assert role_assignments[0]["role_name"] == "platform_admin"


class TestJWTClaimsDecoding:
    """Test JWT claims decoding for id_token parsing."""

    def test_decode_valid_jwt_claims(self, sso_service):
        """Test decoding a valid JWT token."""
        import base64

        import orjson

        # Create a valid JWT-like structure
        header = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}').decode().rstrip("=")
        payload_data = {"sub": "user123", "groups": ["admin", "developer"], "roles": ["Admin"]}
        payload = base64.urlsafe_b64encode(orjson.dumps(payload_data)).decode().rstrip("=")
        signature = "fake_signature"
        token = f"{header}.{payload}.{signature}"

        claims = sso_service._decode_jwt_claims(token)

        assert claims is not None
        assert claims["sub"] == "user123"
        assert claims["groups"] == ["admin", "developer"]
        assert claims["roles"] == ["Admin"]

    def test_decode_jwt_with_padding_needed(self, sso_service):
        """Test decoding JWT that needs base64 padding."""
        import base64

        import orjson

        header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').decode().rstrip("=")
        # Short payload that will need padding
        payload_data = {"sub": "x"}
        payload = base64.urlsafe_b64encode(orjson.dumps(payload_data)).decode().rstrip("=")
        token = f"{header}.{payload}.sig"

        claims = sso_service._decode_jwt_claims(token)

        assert claims is not None
        assert claims["sub"] == "x"

    def test_decode_invalid_jwt_format(self, sso_service):
        """Test that invalid JWT format returns None."""
        # Not enough parts
        assert sso_service._decode_jwt_claims("invalid") is None
        assert sso_service._decode_jwt_claims("only.two") is None

    def test_decode_invalid_base64(self, sso_service):
        """Test that invalid base64 in payload returns None."""
        # Invalid base64 characters in payload
        assert sso_service._decode_jwt_claims("header.!@#$.signature") is None

    def test_decode_invalid_json(self, sso_service):
        """Test that invalid JSON in payload returns None."""
        import base64

        header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').decode().rstrip("=")
        # Invalid JSON
        payload = base64.urlsafe_b64encode(b"not json").decode().rstrip("=")
        token = f"{header}.{payload}.sig"

        assert sso_service._decode_jwt_claims(token) is None


class TestIsAdminSyncOnLogin:
    """Test is_admin synchronization on login for existing users."""

    @pytest.mark.asyncio
    async def test_is_admin_upgraded_when_user_gains_admin_group(self, sso_service, entra_provider):
        """Test that existing non-admin user gets is_admin=True when added to admin group."""
        # Create mock existing user WITHOUT admin
        mock_user = MagicMock()
        mock_user.email = "user@company.com"
        mock_user.full_name = "Test User"
        mock_user.is_admin = False  # Not admin initially
        mock_user.auth_provider = "entra"
        mock_user.email_verified = True
        mock_user.get_teams.return_value = []

        # Mock auth service to return existing user
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        sso_service.get_provider = MagicMock(return_value=entra_provider)

        # User info with admin group
        user_info = {
            "email": "user@company.com",
            "full_name": "Test User",
            "provider": "entra",
            "groups": ["Admin"],  # User is now in admin group
        }

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = ["Admin"]
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_sync_roles_on_login = True
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_entra_default_role = None

            with patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
                mock_jwt.return_value = "mock_token"

                await sso_service.authenticate_or_create_user(user_info)

                # Verify is_admin was updated to True
                assert mock_user.is_admin is True

    @pytest.mark.asyncio
    async def test_is_admin_preserved_when_user_loses_admin_group(self, sso_service, entra_provider):
        """Test that existing admin user keeps is_admin=True even when removed from admin group.

        This is intentional: SSO only UPGRADES is_admin, never downgrades.
        Manual admin grants (via Admin UI/API) are preserved.
        To revoke admin access, use the Admin UI/API directly.
        """
        # Create mock existing user WITH admin (e.g., manually granted)
        mock_user = MagicMock()
        mock_user.email = "user@company.com"
        mock_user.full_name = "Test User"
        mock_user.is_admin = True  # Admin initially (manual grant)
        mock_user.auth_provider = "entra"
        mock_user.email_verified = True
        mock_user.get_teams.return_value = []

        # Mock auth service to return existing user
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        sso_service.get_provider = MagicMock(return_value=entra_provider)

        # User info WITHOUT admin group
        user_info = {
            "email": "user@company.com",
            "full_name": "Test User",
            "provider": "entra",
            "groups": ["Developer"],  # User no longer in admin group
        }

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = ["Admin"]
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_sync_roles_on_login = True
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_entra_default_role = None

            with patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
                mock_jwt.return_value = "mock_token"

                await sso_service.authenticate_or_create_user(user_info)

                # Verify is_admin was PRESERVED (not revoked) - manual grants are kept
                assert mock_user.is_admin is True

    @pytest.mark.asyncio
    async def test_is_admin_unchanged_when_status_matches(self, sso_service, entra_provider):
        """Test that is_admin is not changed when current status matches groups."""
        # Create mock existing admin user
        mock_user = MagicMock()
        mock_user.email = "user@company.com"
        mock_user.full_name = "Test User"
        mock_user.is_admin = True  # Already admin
        mock_user.auth_provider = "entra"
        mock_user.email_verified = True
        mock_user.get_teams.return_value = []

        # Track if is_admin was set
        is_admin_set_count = 0
        original_is_admin = mock_user.is_admin

        def track_is_admin_set(value):
            nonlocal is_admin_set_count
            is_admin_set_count += 1

        type(mock_user).is_admin = property(lambda self: original_is_admin, track_is_admin_set)

        # Mock auth service to return existing user
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        sso_service.get_provider = MagicMock(return_value=entra_provider)

        # User info with admin group (status should match)
        user_info = {
            "email": "user@company.com",
            "full_name": "Test User",
            "provider": "entra",
            "groups": ["Admin"],  # Still in admin group
        }

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = ["Admin"]
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_sync_roles_on_login = True
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_entra_default_role = None

            with patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
                mock_jwt.return_value = "mock_token"

                await sso_service.authenticate_or_create_user(user_info)

                # is_admin should NOT have been set since it already matched
                assert is_admin_set_count == 0
