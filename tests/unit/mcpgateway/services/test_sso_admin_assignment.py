# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_sso_admin_assignment.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test SSO admin privilege assignment functionality.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import SSOProvider
from mcpgateway.services.sso_service import SSOProviderContext, SSOService


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
def github_provider():
    """Create a GitHub SSO provider for testing."""
    return SSOProvider(
        id="github",
        name="github",
        display_name="GitHub",
        provider_type="oauth2",
        client_id="test_client_id",
        client_secret_encrypted="encrypted_secret",
        is_enabled=True,
        trusted_domains=["example.com"],
        auto_create_users=True,
    )


class TestSSOAdminAssignment:
    """Test SSO admin privilege assignment logic."""

    def test_should_user_be_admin_domain_based(self, sso_service, github_provider):
        """Test domain-based admin assignment."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = ["admincompany.com", "executives.org"]

            user_info = {"full_name": "Test User", "provider": "github"}

            # Should be admin for admin domain
            assert sso_service._should_user_be_admin("admin@admincompany.com", user_info, github_provider) is True

            # Should not be admin for regular domain
            assert sso_service._should_user_be_admin("user@regular.com", user_info, github_provider) is False

            # Case insensitive check
            assert sso_service._should_user_be_admin("admin@ADMINCOMPANY.COM", user_info, github_provider) is True

    def test_should_user_be_admin_github_orgs(self, sso_service, github_provider):
        """Test GitHub organization-based admin assignment."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = ["admin-org", "leadership"]

            # User with admin organization
            user_info = {"full_name": "Test User", "provider": "github", "organizations": ["admin-org", "public-org"]}
            assert sso_service._should_user_be_admin("user@example.com", user_info, github_provider) is True

            # User without admin organization
            user_info_no_admin_org = {"full_name": "Test User", "provider": "github", "organizations": ["public-org", "other-org"]}
            assert sso_service._should_user_be_admin("user@example.com", user_info_no_admin_org, github_provider) is False

            # User with no organizations
            user_info_no_orgs = {"full_name": "Test User", "provider": "github", "organizations": []}
            assert sso_service._should_user_be_admin("user@example.com", user_info_no_orgs, github_provider) is False

    def test_should_user_be_admin_google_domains(self, sso_service):
        """Test Google domain-based admin assignment."""
        google_provider = SSOProvider(id="google", name="google", display_name="Google")

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = ["company.com", "enterprise.org"]

            user_info = {"full_name": "Test User", "provider": "google"}

            # Should be admin for Google admin domain
            assert sso_service._should_user_be_admin("user@company.com", user_info, google_provider) is True

            # Should not be admin for regular domain
            assert sso_service._should_user_be_admin("user@gmail.com", user_info, google_provider) is False

    def test_should_user_be_admin_no_rules(self, sso_service, github_provider):
        """Test that users are not admin when no admin rules are configured."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []

            user_info = {"full_name": "Test User", "provider": "github"}
            assert sso_service._should_user_be_admin("user@example.com", user_info, github_provider) is False

    def test_should_user_be_admin_priority_domain_first(self, sso_service, github_provider):
        """Test that domain-based admin assignment has priority."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = ["company.com"]
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []

            user_info = {"full_name": "Test User", "provider": "github"}
            # Domain-based should grant admin even without org membership
            assert sso_service._should_user_be_admin("user@company.com", user_info, github_provider) is True

    def test_should_user_be_admin_entra_groups(self, sso_service):
        """Test EntraID group-based admin assignment."""
        entra_provider = SSOProvider(id="entra", name="entra", display_name="Microsoft Entra ID")

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = ["a1b2c3d4-1234-5678-90ab-cdef12345678", "Admin"]

            # User with admin group (Object ID)
            user_info = {"full_name": "Test User", "provider": "entra", "groups": ["a1b2c3d4-1234-5678-90ab-cdef12345678", "Developer"]}
            assert sso_service._should_user_be_admin("user@company.com", user_info, entra_provider) is True

            # User with admin role (App Role)
            user_info_role = {"full_name": "Test User", "provider": "entra", "groups": ["Admin"]}
            assert sso_service._should_user_be_admin("user@company.com", user_info_role, entra_provider) is True

            # User without admin group
            user_info_no_admin = {"full_name": "Test User", "provider": "entra", "groups": ["Developer", "Viewer"]}
            assert sso_service._should_user_be_admin("user@company.com", user_info_no_admin, entra_provider) is False

            # User with no groups
            user_info_no_groups = {"full_name": "Test User", "provider": "entra", "groups": []}
            assert sso_service._should_user_be_admin("user@company.com", user_info_no_groups, entra_provider) is False


class TestGenericOIDCAdminAssignment:
    """Test admin promotion for generic OIDC providers (gap 2 fix — issue #4232).

    Covers:
    - sso_generic_admin_groups explicit group list
    - role_mappings → platform_admin promotion (provider-agnostic)
    - Scope isolation: sso_generic_admin_groups must not bleed into other providers
    """

    def _make_generic_provider(self, provider_id: str = "authentik", role_mappings: dict | None = None, groups_claim: str = "groups", default_role: str | None = None) -> SSOProviderContext:
        return SSOProviderContext(
            id=provider_id,
            provider_metadata={
                "groups_claim": groups_claim,
                "role_mappings": role_mappings or {},
                "default_role": default_role,
            },
        )

    def test_generic_admin_groups_grants_admin(self, sso_service):
        """User in sso_generic_admin_groups receives is_admin=True."""
        provider = self._make_generic_provider()
        user_info = {"groups": ["cf-platform-admin", "cf-dev"]}

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_generic_admin_groups = ["cf-platform-admin"]
            mock_settings.sso_generic_provider_id = "authentik"

            assert sso_service._should_user_be_admin("user@example.com", user_info, provider) is True

    def test_generic_admin_groups_case_insensitive(self, sso_service):
        """sso_generic_admin_groups comparison is case-insensitive."""
        provider = self._make_generic_provider()
        user_info = {"groups": ["CF-Platform-Admin"]}

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_generic_admin_groups = ["cf-platform-admin"]
            mock_settings.sso_generic_provider_id = "authentik"

            assert sso_service._should_user_be_admin("user@example.com", user_info, provider) is True

    def test_generic_admin_groups_no_match_returns_false(self, sso_service):
        """User not in sso_generic_admin_groups does not receive is_admin=True."""
        provider = self._make_generic_provider()
        user_info = {"groups": ["cf-dev", "cf-viewer"]}

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_generic_admin_groups = ["cf-platform-admin"]
            mock_settings.sso_generic_provider_id = "authentik"

            assert sso_service._should_user_be_admin("user@example.com", user_info, provider) is False

    def test_generic_admin_groups_scoped_to_generic_provider_id(self, sso_service):
        """sso_generic_admin_groups must not apply to a Keycloak provider (scope isolation)."""
        keycloak_provider = SSOProviderContext(
            id="keycloak",
            provider_metadata={
                "groups_claim": "groups",
                "role_mappings": {},
                "default_role": None,
            },
        )
        user_info = {"groups": ["cf-platform-admin"]}

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_generic_admin_groups = ["cf-platform-admin"]
            mock_settings.sso_generic_provider_id = "authentik"  # different from "keycloak"

            # Keycloak login must not be granted admin via sso_generic_admin_groups
            assert sso_service._should_user_be_admin("user@example.com", user_info, keycloak_provider) is False

    def test_role_mappings_platform_admin_grants_admin(self, sso_service):
        """A group mapped to platform_admin in provider_metadata.role_mappings grants is_admin=True."""
        provider = self._make_generic_provider(role_mappings={"cf-platform-admin": "platform_admin", "cf-dev": "developer"})
        user_info = {"groups": ["cf-platform-admin"]}

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_generic_admin_groups = []
            mock_settings.sso_generic_provider_id = "authentik"

            assert sso_service._should_user_be_admin("user@example.com", user_info, provider) is True

    def test_role_mappings_platform_admin_case_insensitive(self, sso_service):
        """role_mappings lookup is case-insensitive: IdP casing differences must not block promotion."""
        # Operator configured lowercase key; IdP sends mixed-case value
        provider = self._make_generic_provider(role_mappings={"cf-platform-admin": "platform_admin"})
        user_info = {"groups": ["CF-Platform-Admin"]}

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_generic_admin_groups = []
            mock_settings.sso_generic_provider_id = "authentik"

            assert sso_service._should_user_be_admin("user@example.com", user_info, provider) is True

    def test_role_mappings_non_admin_role_does_not_grant_admin(self, sso_service):
        """A group mapped to a non-admin role does not grant is_admin=True."""
        provider = self._make_generic_provider(role_mappings={"cf-dev": "developer"})
        user_info = {"groups": ["cf-dev"]}

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_generic_admin_groups = []
            mock_settings.sso_generic_provider_id = "authentik"

            assert sso_service._should_user_be_admin("user@example.com", user_info, provider) is False

    def test_role_mappings_check_is_provider_agnostic(self, sso_service):
        """role_mappings → platform_admin promotion works for any provider with role_mappings (e.g. Keycloak)."""
        keycloak_provider = SSOProviderContext(
            id="keycloak",
            provider_metadata={"role_mappings": {"gateway-admins": "platform_admin"}},
        )
        user_info = {"groups": ["gateway-admins"]}

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_generic_admin_groups = []
            mock_settings.sso_generic_provider_id = "authentik"

            assert sso_service._should_user_be_admin("user@example.com", user_info, keycloak_provider) is True

    def test_no_groups_in_user_info_returns_false(self, sso_service):
        """User with no groups claim in token is not promoted to admin."""
        provider = self._make_generic_provider(role_mappings={"cf-platform-admin": "platform_admin"})
        user_info = {}  # no "groups" key

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_generic_admin_groups = ["cf-platform-admin"]
            mock_settings.sso_generic_provider_id = "authentik"

            assert sso_service._should_user_be_admin("user@example.com", user_info, provider) is False

    def test_empty_role_mappings_returns_false(self, sso_service):
        """Provider with empty role_mappings does not promote any user via that path."""
        provider = self._make_generic_provider(role_mappings={})
        user_info = {"groups": ["cf-platform-admin"]}

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_generic_admin_groups = []
            mock_settings.sso_generic_provider_id = "authentik"

            assert sso_service._should_user_be_admin("user@example.com", user_info, provider) is False
