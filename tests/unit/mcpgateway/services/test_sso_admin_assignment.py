# -*- coding: utf-8 -*-
"""Test SSO admin privilege assignment functionality."""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import SSOProvider
from mcpgateway.services.sso_service import SSOService


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock(spec=Session)
    return session


@pytest.fixture
def sso_service(mock_db_session):
    """Create SSO service instance with mock dependencies."""
    with patch('mcpgateway.services.sso_service.EmailAuthService'):
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
        auto_create_users=True
    )


class TestSSOAdminAssignment:
    """Test SSO admin privilege assignment logic."""

    def test_should_user_be_admin_domain_based(self, sso_service, github_provider):
        """Test domain-based admin assignment."""
        with patch('mcpgateway.services.sso_service.settings') as mock_settings:
            mock_settings.sso_auto_admin_domains = ["admincompany.com", "executives.org"]

            user_info = {"full_name": "Test User", "provider": "github"}

            # Should be admin for admin domain
            assert sso_service._should_user_be_admin("admin@admincompany.com", user_info, github_provider) == True

            # Should not be admin for regular domain
            assert sso_service._should_user_be_admin("user@regular.com", user_info, github_provider) == False

            # Case insensitive check
            assert sso_service._should_user_be_admin("admin@ADMINCOMPANY.COM", user_info, github_provider) == True

    def test_should_user_be_admin_github_orgs(self, sso_service, github_provider):
        """Test GitHub organization-based admin assignment."""
        with patch('mcpgateway.services.sso_service.settings') as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = ["admin-org", "leadership"]

            # User with admin organization
            user_info = {
                "full_name": "Test User",
                "provider": "github",
                "organizations": ["admin-org", "public-org"]
            }
            assert sso_service._should_user_be_admin("user@example.com", user_info, github_provider) == True

            # User without admin organization
            user_info_no_admin_org = {
                "full_name": "Test User",
                "provider": "github",
                "organizations": ["public-org", "other-org"]
            }
            assert sso_service._should_user_be_admin("user@example.com", user_info_no_admin_org, github_provider) == False

            # User with no organizations
            user_info_no_orgs = {
                "full_name": "Test User",
                "provider": "github",
                "organizations": []
            }
            assert sso_service._should_user_be_admin("user@example.com", user_info_no_orgs, github_provider) == False

    def test_should_user_be_admin_google_domains(self, sso_service):
        """Test Google domain-based admin assignment."""
        google_provider = SSOProvider(id="google", name="google", display_name="Google")

        with patch('mcpgateway.services.sso_service.settings') as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = ["company.com", "enterprise.org"]

            user_info = {"full_name": "Test User", "provider": "google"}

            # Should be admin for Google admin domain
            assert sso_service._should_user_be_admin("user@company.com", user_info, google_provider) == True

            # Should not be admin for regular domain
            assert sso_service._should_user_be_admin("user@gmail.com", user_info, google_provider) == False

    def test_should_user_be_admin_no_rules(self, sso_service, github_provider):
        """Test that users are not admin when no admin rules are configured."""
        with patch('mcpgateway.services.sso_service.settings') as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []

            user_info = {"full_name": "Test User", "provider": "github"}
            assert sso_service._should_user_be_admin("user@example.com", user_info, github_provider) == False

    def test_should_user_be_admin_priority_domain_first(self, sso_service, github_provider):
        """Test that domain-based admin assignment has priority."""
        with patch('mcpgateway.services.sso_service.settings') as mock_settings:
            mock_settings.sso_auto_admin_domains = ["company.com"]
            mock_settings.sso_github_admin_orgs = ["non-admin-org"]

            user_info = {
                "full_name": "Test User",
                "provider": "github",
                "organizations": ["non-admin-org"]  # This org is NOT in admin list
            }

            # Should still be admin because of domain
            assert sso_service._should_user_be_admin("user@company.com", user_info, github_provider) == True
