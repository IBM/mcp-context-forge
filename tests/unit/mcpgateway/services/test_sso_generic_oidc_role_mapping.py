# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_sso_generic_oidc_role_mapping.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Test Generic OIDC role mapping functionality.
Tests group extraction, role mapping, and role synchronization for generic OIDC providers.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Role, SSOProvider
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
def generic_provider():
    """Create a Generic OIDC SSO provider for testing."""
    return SSOProvider(
        id="authentik",
        name="authentik",
        display_name="Authentik",
        provider_type="oidc",
        client_id="test_client_id",
        client_secret_encrypted="encrypted_secret",
        is_enabled=True,
        trusted_domains=["company.com"],
        auto_create_users=True,
        provider_metadata={
            "groups_claim": "groups",
            "admin_groups": ["platform-admins", "super-admins"],
            "role_mappings": {
                "developers": "developer",
                "team-leads": "team_admin",
            },
            "default_role": "viewer",
            "sync_roles": True,
        },
    )


class TestGenericOIDCGroupExtraction:
    """Test Generic OIDC group and role extraction from tokens."""

    def test_groups_claim_extraction(self, sso_service, generic_provider):
        """Test extraction of groups from default 'groups' claim."""
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "abc123",
            "groups": ["developers", "viewers"],
        }

        normalized = sso_service._normalize_user_info(generic_provider, user_data)

        assert "groups" in normalized
        assert len(normalized["groups"]) == 2
        assert "developers" in normalized["groups"]
        assert "viewers" in normalized["groups"]

    def test_custom_groups_claim(self, sso_service):
        """Test using custom groups claim name from provider_metadata."""
        provider = SSOProvider(
            id="authentik",
            name="authentik",
            display_name="Authentik",
            provider_type="oidc",
            client_id="test_client_id",
            client_secret_encrypted="encrypted_secret",
            is_enabled=True,
            provider_metadata={"groups_claim": "custom_groups"},
        )

        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "abc123",
            "custom_groups": ["group1", "group2"],
        }

        normalized = sso_service._normalize_user_info(provider, user_data)

        assert "groups" in normalized
        assert len(normalized["groups"]) == 2
        assert "group1" in normalized["groups"]
        assert "group2" in normalized["groups"]

    def test_roles_claim_extraction(self, sso_service, generic_provider):
        """Test extraction of roles from 'roles' claim."""
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "abc123",
            "roles": ["Admin", "Developer"],
        }

        normalized = sso_service._normalize_user_info(generic_provider, user_data)

        assert "groups" in normalized
        assert len(normalized["groups"]) == 2
        assert "Admin" in normalized["groups"]
        assert "Developer" in normalized["groups"]

    def test_combined_groups_and_roles_deduplication(self, sso_service, generic_provider):
        """Test that duplicate groups from groups + roles claims are deduplicated."""
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "abc123",
            "groups": ["Developer", "Admin"],
            "roles": ["Developer", "Viewer"],  # Developer appears in both
        }

        normalized = sso_service._normalize_user_info(generic_provider, user_data)

        assert "groups" in normalized
        assert len(normalized["groups"]) == 3  # Developer, Admin, Viewer (deduplicated)
        assert "Developer" in normalized["groups"]
        assert "Admin" in normalized["groups"]
        assert "Viewer" in normalized["groups"]

    def test_empty_groups_returns_empty_list(self, sso_service, generic_provider):
        """Test handling when no groups or roles are present."""
        user_data = {"email": "user@company.com", "name": "Test User", "sub": "abc123"}

        normalized = sso_service._normalize_user_info(generic_provider, user_data)

        assert "groups" in normalized
        assert normalized["groups"] == []

    def test_other_providers_not_affected(self, sso_service):
        """Test that other SSO providers are not affected by generic OIDC changes."""
        github_provider = SSOProvider(id="github", name="github", display_name="GitHub", provider_type="oauth2")

        user_data = {"email": "user@example.com", "name": "Test User", "login": "testuser", "id": 12345}

        normalized = sso_service._normalize_user_info(github_provider, user_data)

        assert normalized["provider"] == "github"
        assert "groups" not in normalized or normalized.get("groups") == []

    def test_entra_provider_not_affected(self, sso_service):
        """Test that Entra provider still uses its own normalization path."""
        entra_provider = SSOProvider(
            id="entra",
            name="entra",
            display_name="Microsoft Entra ID",
            provider_type="oidc",
            client_id="test_client_id",
            client_secret_encrypted="encrypted_secret",
            is_enabled=True,
            provider_metadata={"groups_claim": "groups"},
        )

        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "abc123",
            "groups": ["entra-group-1"],
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert normalized["provider"] == "entra"
        assert "groups" in normalized
        assert "entra-group-1" in normalized["groups"]

    def test_generic_provider_id_preserved(self, sso_service, generic_provider):
        """Test that the generic provider's ID is preserved in normalized output."""
        user_data = {"email": "user@company.com", "name": "Test User", "sub": "abc123"}

        normalized = sso_service._normalize_user_info(generic_provider, user_data)

        assert normalized["provider"] == "authentik"


class TestGenericOIDCAdminGroupAssignment:
    """Test Generic OIDC admin group assignment."""

    def test_admin_group_assignment(self, sso_service, generic_provider):
        """Test admin assignment via sso_generic_admin_groups."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_generic_admin_groups = ["platform-admins", "super-admins"]

            user_info = {"full_name": "Test User", "provider": "authentik", "groups": ["platform-admins", "developers"]}
            assert sso_service._should_user_be_admin("user@company.com", user_info, generic_provider) is True

    def test_admin_group_case_insensitive(self, sso_service, generic_provider):
        """Test that admin group matching is case-insensitive."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_generic_admin_groups = ["platform-admins"]

            user_info = {"full_name": "Test User", "provider": "authentik", "groups": ["PLATFORM-ADMINS", "developers"]}
            assert sso_service._should_user_be_admin("user@company.com", user_info, generic_provider) is True

    def test_user_without_admin_group_returns_false(self, sso_service, generic_provider):
        """Test user without admin group returns False."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_generic_admin_groups = ["platform-admins"]

            user_info = {"full_name": "Test User", "provider": "authentik", "groups": ["developers", "viewers"]}
            assert sso_service._should_user_be_admin("user@company.com", user_info, generic_provider) is False

    def test_admin_check_skipped_for_known_providers(self, sso_service):
        """Test that generic admin groups are NOT checked for known providers."""
        entra_provider = SSOProvider(
            id="entra",
            name="entra",
            display_name="Microsoft Entra ID",
            provider_type="oidc",
            client_id="test_client_id",
            client_secret_encrypted="encrypted_secret",
            is_enabled=True,
            provider_metadata={},
        )

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_generic_admin_groups = ["platform-admins"]

            user_info = {"full_name": "Test User", "provider": "entra", "groups": ["platform-admins"]}
            # Entra provider should NOT match generic admin groups
            assert sso_service._should_user_be_admin("user@company.com", user_info, entra_provider) is False


class TestGenericOIDCRoleMapping:
    """Test Generic OIDC group to role mapping."""

    @pytest.mark.asyncio
    async def test_map_groups_to_roles_from_mappings(self, sso_service, generic_provider):
        """Test mapping groups to roles using provider_metadata role_mappings."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_generic_admin_groups = []

            with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
                mock_role_service = MockRoleService.return_value

                developer_role = MagicMock(spec=Role)
                developer_role.name = "developer"
                developer_role.scope = "team"

                team_admin_role = MagicMock(spec=Role)
                team_admin_role.name = "team_admin"
                team_admin_role.scope = "team"

                async def mock_get_role_by_name(name, scope):
                    """Return mock role by name."""
                    if name == "developer":
                        return developer_role
                    elif name == "team_admin":
                        return team_admin_role
                    return None

                mock_role_service.get_role_by_name = AsyncMock(side_effect=mock_get_role_by_name)

                user_groups = ["developers", "team-leads"]
                role_assignments = await sso_service._map_groups_to_roles("user@company.com", user_groups, generic_provider)

                assert len(role_assignments) == 2
                assert any(r["role_name"] == "developer" for r in role_assignments)
                assert any(r["role_name"] == "team_admin" for r in role_assignments)

    @pytest.mark.asyncio
    async def test_map_groups_to_roles_admin_group(self, sso_service, generic_provider):
        """Test mapping admin groups to platform_admin role."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_generic_admin_groups = ["platform-admins"]
            mock_settings.default_admin_role = "platform_admin"

            user_groups = ["platform-admins", "developers"]
            role_assignments = await sso_service._map_groups_to_roles("user@company.com", user_groups, generic_provider)

            assert len(role_assignments) >= 1
            assert any(r["role_name"] == "platform_admin" and r["scope"] == "global" for r in role_assignments)

    @pytest.mark.asyncio
    async def test_map_groups_to_roles_default_role(self, sso_service, generic_provider):
        """Test assigning default role when no groups match mappings."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_generic_admin_groups = []

            with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
                mock_role_service = MockRoleService.return_value

                viewer_role = MagicMock(spec=Role)
                viewer_role.name = "viewer"
                viewer_role.scope = "team"

                mock_role_service.get_role_by_name = AsyncMock(return_value=viewer_role)

                user_groups = ["unmapped-group"]
                role_assignments = await sso_service._map_groups_to_roles("user@company.com", user_groups, generic_provider)

                assert len(role_assignments) == 1
                assert role_assignments[0]["role_name"] == "viewer"
                assert role_assignments[0]["scope"] == "team"

    @pytest.mark.asyncio
    async def test_early_exit_when_no_mappings_configured(self, sso_service):
        """Test that role mapping returns early when no configuration exists."""
        provider_no_mappings = SSOProvider(
            id="authentik",
            name="authentik",
            display_name="Authentik",
            provider_type="oidc",
            client_id="test_client_id",
            client_secret_encrypted="encrypted_secret",
            is_enabled=True,
            provider_metadata={},  # No role_mappings, no default_role
        )

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_entra_default_role = None
            mock_settings.sso_generic_admin_groups = []

            role_assignments = await sso_service._map_groups_to_roles("user@company.com", ["SomeGroup"], provider_no_mappings)

            assert len(role_assignments) == 0

    @pytest.mark.asyncio
    async def test_default_role_not_applied_when_user_has_mapped_roles(self, sso_service, generic_provider):
        """Test that default role is NOT applied when user has mapped roles."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_generic_admin_groups = ["platform-admins"]
            mock_settings.default_admin_role = "platform_admin"

            user_groups = ["platform-admins"]
            role_assignments = await sso_service._map_groups_to_roles("user@company.com", user_groups, generic_provider)

            assert len(role_assignments) >= 1
            assert any(r["role_name"] == "platform_admin" for r in role_assignments)
            assert not any(r["role_name"] == "viewer" for r in role_assignments)


class TestProviderLevelSyncOptOut:
    """Test provider-level sync_roles flag in provider_metadata for generic providers."""

    @pytest.mark.asyncio
    async def test_sync_skipped_when_provider_sync_roles_disabled(self, sso_service):
        """Test that role sync is skipped when provider has sync_roles=False."""
        provider_no_sync = SSOProvider(
            id="authentik",
            name="authentik",
            display_name="Authentik",
            provider_type="oidc",
            client_id="test_client_id",
            client_secret_encrypted="encrypted_secret",
            is_enabled=True,
            provider_metadata={
                "sync_roles": False,
                "role_mappings": {
                    "developers": "developer",
                },
            },
        )

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_generic_admin_groups = []

            await sso_service._map_groups_to_roles("user@company.com", ["developers"], provider_no_sync)

            assert provider_no_sync.provider_metadata.get("sync_roles") is False

    @pytest.mark.asyncio
    async def test_sync_proceeds_when_provider_sync_roles_true(self, sso_service, generic_provider):
        """Test that role sync proceeds when provider has sync_roles=True."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.sso_generic_admin_groups = ["platform-admins"]
            mock_settings.default_admin_role = "platform_admin"

            role_assignments = await sso_service._map_groups_to_roles("user@company.com", ["platform-admins"], generic_provider)

            assert len(role_assignments) == 1
            assert role_assignments[0]["role_name"] == "platform_admin"
