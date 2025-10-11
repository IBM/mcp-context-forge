# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_sso_user_normalization.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Test SSO user info normalization functionality across all providers.
Tests edge cases where provider claims might be missing or incomplete.
"""

# Standard
from unittest.mock import MagicMock, patch

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
    )


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


@pytest.fixture
def google_provider():
    """Create a Google SSO provider for testing."""
    return SSOProvider(
        id="google",
        name="google",
        display_name="Google",
        provider_type="oidc",
        client_id="test_client_id",
        client_secret_encrypted="encrypted_secret",
        is_enabled=True,
        trusted_domains=["example.com"],
        auto_create_users=True,
    )


class TestEntraIDNormalization:
    """Test Microsoft Entra ID user info normalization with various edge cases."""

    def test_entra_complete_userinfo(self, sso_service, entra_provider):
        """Test normalization with all Entra ID claims present."""
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "preferred_username": "user@company.com",
            "sub": "abc123",
            "oid": "def456",
            "picture": "https://graph.microsoft.com/photo.jpg",
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert normalized["email"] == "user@company.com"
        assert normalized["full_name"] == "Test User"
        assert normalized["avatar_url"] == "https://graph.microsoft.com/photo.jpg"
        assert normalized["provider_id"] == "abc123"  # sub takes priority
        assert normalized["username"] == "user@company.com"  # preferred_username
        assert normalized["provider"] == "entra"

    def test_entra_missing_email_fallback_to_preferred_username(self, sso_service, entra_provider):
        """Test email fallback to preferred_username when email claim is missing."""
        user_data = {
            # No email claim (common with Entra ID)
            "name": "Test User",
            "preferred_username": "user@company.com",  # This should become email
            "sub": "abc123",
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert normalized["email"] == "user@company.com"  # From preferred_username
        assert normalized["full_name"] == "Test User"
        assert normalized["username"] == "user@company.com"
        assert normalized["provider"] == "entra"

    def test_entra_missing_email_fallback_to_upn(self, sso_service, entra_provider):
        """Test email fallback to upn when email and preferred_username are missing."""
        user_data = {
            # No email or preferred_username
            "name": "Test User",
            "upn": "user@company.com",  # Fallback to UPN
            "sub": "abc123",
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert normalized["email"] == "user@company.com"  # From upn
        assert normalized["full_name"] == "Test User"
        assert normalized["username"] == "user"  # Extracted from email
        assert normalized["provider"] == "entra"

    def test_entra_missing_all_email_sources(self, sso_service, entra_provider):
        """Test graceful handling when all email sources are missing."""
        user_data = {
            # No email, preferred_username, or upn
            "name": "Test User",
            "sub": "abc123",
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert normalized["email"] is None  # Should be None, not crash
        assert normalized["full_name"] == "Test User"
        assert normalized["username"] is None  # No email to extract from
        assert normalized["provider"] == "entra"

    def test_entra_missing_name_fallback_to_email(self, sso_service, entra_provider):
        """Test full_name fallback to email when name claim is missing."""
        user_data = {
            "email": "user@company.com",
            # No name claim
            "preferred_username": "user@company.com",
            "sub": "abc123",
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert normalized["email"] == "user@company.com"
        assert normalized["full_name"] == "user@company.com"  # Fallback to email
        assert normalized["provider"] == "entra"

    def test_entra_missing_name_and_email(self, sso_service, entra_provider):
        """Test handling when both name and email are missing."""
        user_data = {
            # No name or email
            "preferred_username": "user@company.com",
            "sub": "abc123",
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert normalized["email"] == "user@company.com"  # From preferred_username
        assert normalized["full_name"] == "user@company.com"  # Fallback to email
        assert normalized["provider"] == "entra"

    def test_entra_oid_fallback_when_sub_missing(self, sso_service, entra_provider):
        """Test provider_id fallback to oid when sub is missing."""
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            # No sub claim
            "oid": "def456",  # Entra-specific object ID
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert normalized["provider_id"] == "def456"  # Falls back to oid
        assert normalized["email"] == "user@company.com"
        assert normalized["provider"] == "entra"

    def test_entra_username_extraction_from_email(self, sso_service, entra_provider):
        """Test username extraction from email when preferred_username is missing."""
        user_data = {
            "email": "testuser@company.com",
            "name": "Test User",
            # No preferred_username
            "sub": "abc123",
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert normalized["username"] == "testuser"  # Extracted from email
        assert normalized["email"] == "testuser@company.com"
        assert normalized["provider"] == "entra"

    def test_entra_minimal_valid_data(self, sso_service, entra_provider):
        """Test minimal valid Entra ID data that should work."""
        user_data = {
            "preferred_username": "user@company.com",  # Minimum needed
            "oid": "def456",  # Minimum provider_id
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert normalized["email"] == "user@company.com"
        assert normalized["full_name"] == "user@company.com"  # Fallback
        assert normalized["provider_id"] == "def456"
        assert normalized["username"] == "user@company.com"
        assert normalized["provider"] == "entra"


class TestGitHubNormalization:
    """Test GitHub user info normalization."""

    def test_github_complete_userinfo(self, sso_service, github_provider):
        """Test GitHub normalization with complete data."""
        user_data = {
            "email": "user@example.com",
            "name": "Test User",
            "login": "testuser",
            "id": 12345,
            "avatar_url": "https://avatars.githubusercontent.com/u/12345",
            "organizations": ["test-org", "another-org"],
        }

        normalized = sso_service._normalize_user_info(github_provider, user_data)

        assert normalized["email"] == "user@example.com"
        assert normalized["full_name"] == "Test User"
        assert normalized["avatar_url"] == "https://avatars.githubusercontent.com/u/12345"
        assert normalized["provider_id"] == 12345
        assert normalized["username"] == "testuser"
        assert normalized["provider"] == "github"
        assert normalized["organizations"] == ["test-org", "another-org"]

    def test_github_missing_name_fallback_to_login(self, sso_service, github_provider):
        """Test GitHub full_name fallback to login when name is missing."""
        user_data = {
            "email": "user@example.com",
            # No name
            "login": "testuser",
            "id": 12345,
        }

        normalized = sso_service._normalize_user_info(github_provider, user_data)

        assert normalized["full_name"] == "testuser"  # Falls back to login
        assert normalized["username"] == "testuser"

    def test_github_empty_organizations(self, sso_service, github_provider):
        """Test GitHub with no organizations."""
        user_data = {
            "email": "user@example.com",
            "name": "Test User",
            "login": "testuser",
            "id": 12345,
            # No organizations key
        }

        normalized = sso_service._normalize_user_info(github_provider, user_data)

        assert normalized["organizations"] == []  # Default empty list


class TestGoogleNormalization:
    """Test Google user info normalization."""

    def test_google_complete_userinfo(self, sso_service, google_provider):
        """Test Google normalization with complete data."""
        user_data = {
            "email": "user@example.com",
            "name": "Test User",
            "sub": "google-user-id-123",
            "picture": "https://lh3.googleusercontent.com/a/photo.jpg",
        }

        normalized = sso_service._normalize_user_info(google_provider, user_data)

        assert normalized["email"] == "user@example.com"
        assert normalized["full_name"] == "Test User"
        assert normalized["avatar_url"] == "https://lh3.googleusercontent.com/a/photo.jpg"
        assert normalized["provider_id"] == "google-user-id-123"
        assert normalized["username"] == "user"  # Extracted from email
        assert normalized["provider"] == "google"

    def test_google_username_extraction(self, sso_service, google_provider):
        """Test username extraction from Google email."""
        user_data = {
            "email": "testuser123@gmail.com",
            "name": "Test User",
            "sub": "google-id",
        }

        normalized = sso_service._normalize_user_info(google_provider, user_data)

        assert normalized["username"] == "testuser123"  # Extracted from email


class TestOktaNormalization:
    """Test Okta user info normalization."""

    def test_okta_complete_userinfo(self, sso_service):
        """Test Okta normalization with complete data."""
        okta_provider = SSOProvider(id="okta", name="okta", display_name="Okta", provider_type="oidc")

        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "okta-user-id",
            "preferred_username": "user@company.com",
            "picture": "https://okta.com/profile.jpg",
        }

        normalized = sso_service._normalize_user_info(okta_provider, user_data)

        assert normalized["email"] == "user@company.com"
        assert normalized["full_name"] == "Test User"
        assert normalized["avatar_url"] == "https://okta.com/profile.jpg"
        assert normalized["provider_id"] == "okta-user-id"
        assert normalized["username"] == "user@company.com"
        assert normalized["provider"] == "okta"

    def test_okta_missing_preferred_username(self, sso_service):
        """Test Okta username extraction when preferred_username is missing."""
        okta_provider = SSOProvider(id="okta", name="okta", display_name="Okta", provider_type="oidc")

        user_data = {
            "email": "testuser@company.com",
            "name": "Test User",
            "sub": "okta-user-id",
            # No preferred_username
        }

        normalized = sso_service._normalize_user_info(okta_provider, user_data)

        assert normalized["username"] == "testuser"  # Extracted from email


class TestIBMVerifyNormalization:
    """Test IBM Security Verify user info normalization."""

    def test_ibm_verify_complete_userinfo(self, sso_service):
        """Test IBM Verify normalization with complete data."""
        ibm_provider = SSOProvider(id="ibm_verify", name="ibm_verify", display_name="IBM Security Verify", provider_type="oidc")

        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "ibm-user-id",
            "preferred_username": "user@company.com",
            "picture": "https://verify.ibm.com/profile.jpg",
        }

        normalized = sso_service._normalize_user_info(ibm_provider, user_data)

        assert normalized["email"] == "user@company.com"
        assert normalized["full_name"] == "Test User"
        assert normalized["avatar_url"] == "https://verify.ibm.com/profile.jpg"
        assert normalized["provider_id"] == "ibm-user-id"
        assert normalized["username"] == "user@company.com"
        assert normalized["provider"] == "ibm_verify"


class TestGenericOIDCNormalization:
    """Test generic OIDC provider normalization."""

    def test_generic_oidc_provider(self, sso_service):
        """Test normalization for unknown/generic OIDC provider."""
        generic_provider = SSOProvider(id="custom_oidc", name="custom_oidc", display_name="Custom OIDC", provider_type="oidc")

        user_data = {
            "email": "user@provider.com",
            "name": "Test User",
            "sub": "custom-user-id",
            "preferred_username": "testuser",
            "picture": "https://provider.com/photo.jpg",
        }

        normalized = sso_service._normalize_user_info(generic_provider, user_data)

        # Should use generic OIDC normalization
        assert normalized["email"] == "user@provider.com"
        assert normalized["full_name"] == "Test User"
        assert normalized["avatar_url"] == "https://provider.com/photo.jpg"
        assert normalized["provider_id"] == "custom-user-id"
        assert normalized["username"] == "testuser"
        assert normalized["provider"] == "custom_oidc"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
