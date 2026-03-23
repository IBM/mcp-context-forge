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
            "groups": ["a1b2c3d4-1234-5678-90ab-cdef12345678"],
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

    def test_entra_missing_email_verified_claim_is_omitted(self, sso_service, entra_provider):
        """Entra ID work/school userinfo omits email_verified; key must not appear in normalized output.

        Regression test for https://github.com/IBM/mcp-context-forge/issues/3253:
        first-time Entra logins were rejected because a missing email_verified claim
        was treated as unverified.  The fix mirrors the GitHub provider pattern —
        only propagate the claim when the IdP explicitly includes it.
        """
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "preferred_username": "user@company.com",
            "sub": "abc123",
            # No email_verified claim — typical Entra ID response
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert "email_verified" not in normalized, "email_verified must not be injected when Entra ID omits it; " "_is_email_verified_claim treats absence as pass-through"
        assert normalized["email"] == "user@company.com"
        assert normalized["provider"] == "entra"

    def test_entra_explicit_false_email_verified_is_preserved(self, sso_service, entra_provider):
        """When Entra explicitly marks email_verified=False the claim must be kept so the user is blocked."""
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "preferred_username": "user@company.com",
            "sub": "abc123",
            "email_verified": False,  # Explicit rejection by IdP
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert normalized["email_verified"] is False

    def test_entra_explicit_true_email_verified_is_preserved(self, sso_service, entra_provider):
        """When Entra explicitly marks email_verified=True the claim is propagated normally."""
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "preferred_username": "user@company.com",
            "sub": "abc123",
            "email_verified": True,
        }

        normalized = sso_service._normalize_user_info(entra_provider, user_data)

        assert normalized["email_verified"] is True


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

    def test_github_missing_email_verified_claim_is_omitted(self, sso_service, github_provider):
        """GitHub /user payloads should not force unverified-email rejection."""
        user_data = {
            "email": "user@example.com",
            "name": "Test User",
            "login": "testuser",
            "id": 12345,
        }

        normalized = sso_service._normalize_user_info(github_provider, user_data)

        assert "email_verified" not in normalized

    def test_github_explicit_email_verified_claim_is_preserved(self, sso_service, github_provider):
        user_data = {
            "email": "user@example.com",
            "name": "Test User",
            "login": "testuser",
            "id": 12345,
            "email_verified": False,
        }

        normalized = sso_service._normalize_user_info(github_provider, user_data)

        assert normalized["email_verified"] is False


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

    def test_google_missing_email_verified_claim_is_omitted(self, sso_service, google_provider):
        """Google userinfo without email_verified must not inject None into the normalized dict."""
        user_data = {
            "email": "user@gmail.com",
            "name": "Test User",
            "sub": "google-id",
            # No email_verified key
        }

        normalized = sso_service._normalize_user_info(google_provider, user_data)

        assert "email_verified" not in normalized

    def test_google_explicit_false_email_verified_is_preserved(self, sso_service, google_provider):
        """When Google explicitly marks email_verified=False the user must be blocked."""
        user_data = {
            "email": "user@gmail.com",
            "name": "Test User",
            "sub": "google-id",
            "email_verified": False,
        }

        normalized = sso_service._normalize_user_info(google_provider, user_data)

        assert normalized["email_verified"] is False


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

    def test_okta_missing_email_verified_claim_is_omitted(self, sso_service):
        """Okta deployments that omit email_verified must not be blocked."""
        okta_provider = SSOProvider(id="okta", name="okta", display_name="Okta", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "okta-user-id",
            # No email_verified key
        }

        normalized = sso_service._normalize_user_info(okta_provider, user_data)

        assert "email_verified" not in normalized

    def test_okta_explicit_false_email_verified_is_preserved(self, sso_service):
        """When Okta explicitly marks email_verified=False the user must be blocked."""
        okta_provider = SSOProvider(id="okta", name="okta", display_name="Okta", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "okta-user-id",
            "email_verified": False,
        }

        normalized = sso_service._normalize_user_info(okta_provider, user_data)

        assert normalized["email_verified"] is False

    def test_okta_groups_default_claim(self, sso_service):
        """Okta groups are extracted from the default 'groups' claim."""
        okta_provider = SSOProvider(id="okta", name="okta", display_name="Okta", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "okta-user-id",
            "groups": ["Engineering", "Platform"],
        }

        normalized = sso_service._normalize_user_info(okta_provider, user_data)

        assert sorted(normalized["groups"]) == ["Engineering", "Platform"]

    def test_okta_groups_custom_claim(self, sso_service):
        """Okta groups are extracted from a custom claim via provider_metadata."""
        okta_provider = SSOProvider(id="okta", name="okta", display_name="Okta", provider_type="oidc", provider_metadata={"groups_claim": "okta_groups"})
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "okta-user-id",
            "okta_groups": ["Admins", "DevOps"],
        }

        normalized = sso_service._normalize_user_info(okta_provider, user_data)

        assert sorted(normalized["groups"]) == ["Admins", "DevOps"]

    def test_okta_groups_with_roles_merge(self, sso_service):
        """Okta roles claim is merged into groups list."""
        okta_provider = SSOProvider(id="okta", name="okta", display_name="Okta", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "okta-user-id",
            "groups": ["Engineering"],
            "roles": ["admin", "editor"],
        }

        normalized = sso_service._normalize_user_info(okta_provider, user_data)

        assert sorted(normalized["groups"]) == ["Engineering", "admin", "editor"]

    def test_okta_groups_absent_defaults_empty(self, sso_service):
        """When no groups claim is present, Okta groups defaults to empty list."""
        okta_provider = SSOProvider(id="okta", name="okta", display_name="Okta", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "okta-user-id",
        }

        normalized = sso_service._normalize_user_info(okta_provider, user_data)

        assert normalized["groups"] == []

    def test_okta_groups_string_value(self, sso_service):
        """A single string group value is wrapped in a list for Okta."""
        okta_provider = SSOProvider(id="okta", name="okta", display_name="Okta", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "okta-user-id",
            "groups": "SingleGroup",
        }

        normalized = sso_service._normalize_user_info(okta_provider, user_data)

        assert normalized["groups"] == ["SingleGroup"]

    def test_okta_groups_non_string_filtered(self, sso_service):
        """Non-string elements in Okta groups list are filtered out."""
        okta_provider = SSOProvider(id="okta", name="okta", display_name="Okta", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "okta-user-id",
            "groups": ["Engineering", 42, {"nested": "value"}, None, "Platform"],
        }

        normalized = sso_service._normalize_user_info(okta_provider, user_data)

        assert sorted(normalized["groups"]) == ["Engineering", "Platform"]

    def test_okta_roles_non_string_filtered(self, sso_service):
        """Non-string elements in Okta roles list are filtered out."""
        okta_provider = SSOProvider(id="okta", name="okta", display_name="Okta", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "okta-user-id",
            "roles": ["admin", 123, None],
        }

        normalized = sso_service._normalize_user_info(okta_provider, user_data)

        assert normalized["groups"] == ["admin"]

    def test_okta_roles_single_string(self, sso_service):
        """A single string roles value is included in groups for Okta."""
        okta_provider = SSOProvider(id="okta", name="okta", display_name="Okta", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "okta-user-id",
            "roles": "admin",
        }

        normalized = sso_service._normalize_user_info(okta_provider, user_data)

        assert normalized["groups"] == ["admin"]

    def test_okta_groups_deduplicated(self, sso_service):
        """Duplicate entries between groups and roles are deduplicated."""
        okta_provider = SSOProvider(id="okta", name="okta", display_name="Okta", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "okta-user-id",
            "groups": ["admin", "Engineering"],
            "roles": ["admin"],
        }

        normalized = sso_service._normalize_user_info(okta_provider, user_data)

        assert sorted(normalized["groups"]) == ["Engineering", "admin"]


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

    def test_ibm_verify_missing_email_verified_claim_is_omitted(self, sso_service):
        """IBM Verify responses that omit email_verified must not inject None."""
        ibm_provider = SSOProvider(id="ibm_verify", name="ibm_verify", display_name="IBM Security Verify", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "ibm-user-id",
            # No email_verified key
        }

        normalized = sso_service._normalize_user_info(ibm_provider, user_data)

        assert "email_verified" not in normalized

    def test_ibm_verify_explicit_false_email_verified_is_preserved(self, sso_service):
        """When IBM Verify explicitly marks email_verified=False the user must be blocked."""
        ibm_provider = SSOProvider(id="ibm_verify", name="ibm_verify", display_name="IBM Security Verify", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "ibm-user-id",
            "email_verified": False,
        }

        normalized = sso_service._normalize_user_info(ibm_provider, user_data)

        assert normalized["email_verified"] is False

    def test_ibm_verify_groups_default_claim(self, sso_service):
        """IBM Verify groups are extracted from the default 'groups' claim."""
        ibm_provider = SSOProvider(id="ibm_verify", name="ibm_verify", display_name="IBM Security Verify", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "ibm-user-id",
            "groups": ["Developers", "CloudOps"],
        }

        normalized = sso_service._normalize_user_info(ibm_provider, user_data)

        assert sorted(normalized["groups"]) == ["CloudOps", "Developers"]

    def test_ibm_verify_groups_with_roles_merge(self, sso_service):
        """IBM Verify roles claim is merged into groups list."""
        ibm_provider = SSOProvider(id="ibm_verify", name="ibm_verify", display_name="IBM Security Verify", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "ibm-user-id",
            "groups": ["Developers"],
            "roles": ["admin"],
        }

        normalized = sso_service._normalize_user_info(ibm_provider, user_data)

        assert sorted(normalized["groups"]) == ["Developers", "admin"]

    def test_ibm_verify_groups_absent_defaults_empty(self, sso_service):
        """When no groups claim is present, IBM Verify groups defaults to empty list."""
        ibm_provider = SSOProvider(id="ibm_verify", name="ibm_verify", display_name="IBM Security Verify", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "ibm-user-id",
        }

        normalized = sso_service._normalize_user_info(ibm_provider, user_data)

        assert normalized["groups"] == []

    def test_ibm_verify_groups_non_string_filtered(self, sso_service):
        """Non-string elements in IBM Verify groups list are filtered out."""
        ibm_provider = SSOProvider(id="ibm_verify", name="ibm_verify", display_name="IBM Security Verify", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "ibm-user-id",
            "groups": ["Engineering", 42, None, "Platform"],
        }

        normalized = sso_service._normalize_user_info(ibm_provider, user_data)

        assert sorted(normalized["groups"]) == ["Engineering", "Platform"]

    def test_ibm_verify_roles_single_string(self, sso_service):
        """A single string roles value is included in groups for IBM Verify."""
        ibm_provider = SSOProvider(id="ibm_verify", name="ibm_verify", display_name="IBM Security Verify", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "ibm-user-id",
            "roles": "operator",
        }

        normalized = sso_service._normalize_user_info(ibm_provider, user_data)

        assert normalized["groups"] == ["operator"]


class TestKeycloakNormalization:
    """Test Keycloak user info normalization with role mapping."""

    def test_keycloak_complete_userinfo_with_realm_roles(self, sso_service):
        """Test Keycloak normalization with complete data including realm roles."""
        keycloak_provider = SSOProvider(
            id="keycloak",
            name="keycloak",
            display_name="Keycloak",
            provider_type="oidc",
            provider_metadata={
                "realm": "master",
                "map_realm_roles": True,
                "map_client_roles": False,
                "username_claim": "preferred_username",
                "email_claim": "email",
                "groups_claim": "groups",
            },
        )

        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "keycloak-user-id",
            "preferred_username": "testuser",
            "picture": "https://keycloak.company.com/avatar.jpg",
            "realm_access": {"roles": ["admin", "developer", "user"]},
            "groups": ["engineering", "platform-team"],
        }

        normalized = sso_service._normalize_user_info(keycloak_provider, user_data)

        assert normalized["email"] == "user@company.com"
        assert normalized["full_name"] == "Test User"
        assert normalized["avatar_url"] == "https://keycloak.company.com/avatar.jpg"
        assert normalized["provider_id"] == "keycloak-user-id"
        assert normalized["username"] == "testuser"
        assert normalized["provider"] == "keycloak"
        # Check groups as set since order may vary
        assert set(normalized["groups"]) == {"admin", "developer", "user", "engineering", "platform-team"}

    def test_keycloak_with_client_roles(self, sso_service):
        """Test Keycloak normalization with client roles enabled."""
        keycloak_provider = SSOProvider(
            id="keycloak",
            name="keycloak",
            display_name="Keycloak",
            provider_type="oidc",
            provider_metadata={
                "realm": "master",
                "map_realm_roles": False,
                "map_client_roles": True,
                "username_claim": "preferred_username",
                "email_claim": "email",
                "groups_claim": "groups",
            },
        )

        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "keycloak-user-id",
            "preferred_username": "testuser",
            "resource_access": {"mcp-gateway": {"roles": ["gateway-admin", "gateway-user"]}, "another-client": {"roles": ["viewer"]}},
        }

        normalized = sso_service._normalize_user_info(keycloak_provider, user_data)

        assert normalized["email"] == "user@company.com"
        assert normalized["provider"] == "keycloak"
        assert "mcp-gateway:gateway-admin" in normalized["groups"]
        assert "mcp-gateway:gateway-user" in normalized["groups"]
        assert "another-client:viewer" in normalized["groups"]

    def test_keycloak_with_both_realm_and_client_roles(self, sso_service):
        """Test Keycloak with both realm and client roles enabled."""
        keycloak_provider = SSOProvider(
            id="keycloak",
            name="keycloak",
            display_name="Keycloak",
            provider_type="oidc",
            provider_metadata={
                "realm": "master",
                "map_realm_roles": True,
                "map_client_roles": True,
                "username_claim": "preferred_username",
                "email_claim": "email",
                "groups_claim": "groups",
            },
        )

        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "keycloak-user-id",
            "preferred_username": "testuser",
            "realm_access": {"roles": ["admin"]},
            "resource_access": {"mcp-gateway": {"roles": ["gateway-admin"]}},
            "groups": ["engineering"],
        }

        normalized = sso_service._normalize_user_info(keycloak_provider, user_data)

        assert normalized["provider"] == "keycloak"
        # Should have realm roles, client roles, and custom groups all combined
        assert "admin" in normalized["groups"]  # Realm role
        assert "mcp-gateway:gateway-admin" in normalized["groups"]  # Client role
        assert "engineering" in normalized["groups"]  # Custom group
        assert len(normalized["groups"]) == 3

    def test_keycloak_missing_realm_roles(self, sso_service):
        """Test Keycloak when realm_access is missing."""
        keycloak_provider = SSOProvider(
            id="keycloak",
            name="keycloak",
            display_name="Keycloak",
            provider_type="oidc",
            provider_metadata={"realm": "master", "map_realm_roles": True, "map_client_roles": False, "username_claim": "preferred_username", "email_claim": "email", "groups_claim": "groups"},
        )

        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "keycloak-user-id",
            # No realm_access key
        }

        normalized = sso_service._normalize_user_info(keycloak_provider, user_data)

        assert normalized["email"] == "user@company.com"
        assert normalized["provider"] == "keycloak"
        assert normalized["groups"] == []  # Empty groups when no roles

    def test_keycloak_custom_claims(self, sso_service):
        """Test Keycloak with custom JWT claim mappings."""
        keycloak_provider = SSOProvider(
            id="keycloak",
            name="keycloak",
            display_name="Keycloak",
            provider_type="oidc",
            provider_metadata={
                "realm": "custom-realm",
                "map_realm_roles": True,
                "map_client_roles": False,
                "username_claim": "username",  # Custom claim
                "email_claim": "email_address",  # Custom claim
                "groups_claim": "user_groups",  # Custom claim
            },
        )

        user_data = {
            "email_address": "user@company.com",  # Custom email claim
            "name": "Test User",
            "sub": "keycloak-user-id",
            "username": "custom_username",  # Custom username claim
            "realm_access": {"roles": ["admin"]},
            "user_groups": ["team-a", "team-b"],  # Custom groups claim
        }

        normalized = sso_service._normalize_user_info(keycloak_provider, user_data)

        assert normalized["email"] == "user@company.com"
        assert normalized["username"] == "custom_username"
        assert normalized["provider"] == "keycloak"
        assert "admin" in normalized["groups"]
        assert "team-a" in normalized["groups"]
        assert "team-b" in normalized["groups"]

    def test_keycloak_minimal_valid_data(self, sso_service):
        """Test Keycloak with minimal required data."""
        keycloak_provider = SSOProvider(
            id="keycloak",
            name="keycloak",
            display_name="Keycloak",
            provider_type="oidc",
            provider_metadata={"realm": "master", "map_realm_roles": True, "map_client_roles": False, "username_claim": "preferred_username", "email_claim": "email", "groups_claim": "groups"},
        )

        user_data = {
            "email": "user@company.com",
            "sub": "keycloak-user-id",
        }

        normalized = sso_service._normalize_user_info(keycloak_provider, user_data)

        assert normalized["email"] == "user@company.com"
        assert normalized["provider_id"] == "keycloak-user-id"
        assert normalized["username"] == "user"  # Extracted from email
        assert normalized["provider"] == "keycloak"
        assert normalized["groups"] == []

    def test_keycloak_groups_deduplication(self, sso_service):
        """Test that Keycloak deduplicates groups from multiple sources."""
        keycloak_provider = SSOProvider(
            id="keycloak",
            name="keycloak",
            display_name="Keycloak",
            provider_type="oidc",
            provider_metadata={
                "realm": "master",
                "map_realm_roles": True,
                "map_client_roles": True,
                "username_claim": "preferred_username",
                "email_claim": "email",
                "groups_claim": "groups",
            },
        )

        user_data = {
            "email": "user@company.com",
            "sub": "keycloak-user-id",
            "realm_access": {"roles": ["admin", "user"]},
            "resource_access": {"mcp-gateway": {"roles": ["admin"]}},  # "admin" duplicates realm role
            "groups": ["user", "developer"],  # "user" duplicates realm role
        }

        normalized = sso_service._normalize_user_info(keycloak_provider, user_data)

        # Check deduplication - should only have unique values
        groups = normalized["groups"]
        assert len(groups) == len(set(groups))  # No duplicates
        assert "admin" in groups
        assert "user" in groups
        assert "mcp-gateway:admin" in groups  # Client role is namespaced, so not a duplicate
        assert "developer" in groups

    def test_keycloak_missing_email_verified_claim_is_omitted(self, sso_service):
        """Keycloak realms that omit email_verified must not inject None into the normalized dict."""
        keycloak_provider = SSOProvider(
            id="keycloak",
            name="keycloak",
            display_name="Keycloak",
            provider_type="oidc",
            provider_metadata={"realm": "master", "map_realm_roles": False, "map_client_roles": False, "username_claim": "preferred_username", "email_claim": "email", "groups_claim": "groups"},
        )
        user_data = {
            "email": "user@company.com",
            "sub": "keycloak-user-id",
            # No email_verified key
        }

        normalized = sso_service._normalize_user_info(keycloak_provider, user_data)

        assert "email_verified" not in normalized

    def test_keycloak_explicit_false_email_verified_is_preserved(self, sso_service):
        """When Keycloak explicitly marks email_verified=False the user must be blocked."""
        keycloak_provider = SSOProvider(
            id="keycloak",
            name="keycloak",
            display_name="Keycloak",
            provider_type="oidc",
            provider_metadata={"realm": "master", "map_realm_roles": False, "map_client_roles": False, "username_claim": "preferred_username", "email_claim": "email", "groups_claim": "groups"},
        )
        user_data = {
            "email": "user@company.com",
            "sub": "keycloak-user-id",
            "email_verified": False,
        }

        normalized = sso_service._normalize_user_info(keycloak_provider, user_data)

        assert normalized["email_verified"] is False


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

    def test_generic_oidc_missing_email_verified_claim_is_omitted(self, sso_service):
        """Generic OIDC providers that omit email_verified must not be blocked.

        Regression guard: the old code used user_data.get("email_verified") which
        injects None into the normalized dict.  _is_email_verified_claim then sees
        the key present with a None value and returns False, rejecting the user.
        The key must be absent when the IdP does not send it.
        """
        generic_provider = SSOProvider(id="custom_oidc", name="custom_oidc", display_name="Custom OIDC", provider_type="oidc")
        user_data = {
            "email": "user@provider.com",
            "name": "Test User",
            "sub": "custom-user-id",
            # No email_verified key
        }

        normalized = sso_service._normalize_user_info(generic_provider, user_data)

        assert "email_verified" not in normalized, "email_verified must not be injected when the OIDC provider omits it; " "_is_email_verified_claim treats absence as pass-through"

    def test_generic_oidc_explicit_false_email_verified_is_preserved(self, sso_service):
        """When a generic OIDC provider explicitly marks email_verified=False the user must be blocked."""
        generic_provider = SSOProvider(id="custom_oidc", name="custom_oidc", display_name="Custom OIDC", provider_type="oidc")
        user_data = {
            "email": "user@provider.com",
            "name": "Test User",
            "sub": "custom-user-id",
            "email_verified": False,
        }

        normalized = sso_service._normalize_user_info(generic_provider, user_data)

        assert normalized["email_verified"] is False

    def test_generic_oidc_groups_default_claim(self, sso_service):
        """Groups are extracted from the default 'groups' claim."""
        provider = SSOProvider(id="jumpcloud", name="jumpcloud", display_name="JumpCloud", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "user-123",
            "groups": ["Engineering", "Platform"],
        }

        normalized = sso_service._normalize_user_info(provider, user_data)

        assert sorted(normalized["groups"]) == ["Engineering", "Platform"]

    def test_generic_oidc_groups_custom_claim(self, sso_service):
        """Groups are extracted from a custom claim specified in provider_metadata."""
        provider = SSOProvider(id="custom_oidc", name="custom_oidc", display_name="Custom OIDC", provider_type="oidc", provider_metadata={"groups_claim": "roles"})
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "user-123",
            "roles": ["admin", "editor"],
        }

        normalized = sso_service._normalize_user_info(provider, user_data)

        assert sorted(normalized["groups"]) == ["admin", "editor"]

    def test_generic_oidc_groups_string_value(self, sso_service):
        """A single string group value is wrapped in a list."""
        provider = SSOProvider(id="custom_oidc", name="custom_oidc", display_name="Custom OIDC", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "user-123",
            "groups": "Engineering",
        }

        normalized = sso_service._normalize_user_info(provider, user_data)

        assert normalized["groups"] == ["Engineering"]

    def test_generic_oidc_groups_absent_claim(self, sso_service):
        """When no groups claim is present, groups defaults to empty list."""
        provider = SSOProvider(id="custom_oidc", name="custom_oidc", display_name="Custom OIDC", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "user-123",
        }

        normalized = sso_service._normalize_user_info(provider, user_data)

        assert normalized["groups"] == []

    def test_generic_oidc_groups_empty_metadata(self, sso_service):
        """When provider_metadata is None, groups_claim defaults to 'groups'."""
        provider = SSOProvider(id="custom_oidc", name="custom_oidc", display_name="Custom OIDC", provider_type="oidc", provider_metadata=None)
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "user-123",
            "groups": ["DevOps"],
        }

        normalized = sso_service._normalize_user_info(provider, user_data)

        assert normalized["groups"] == ["DevOps"]

    def test_generic_oidc_groups_non_list_non_string_ignored(self, sso_service):
        """Non-list, non-string group values (e.g. int, dict) result in empty groups."""
        provider = SSOProvider(id="custom_oidc", name="custom_oidc", display_name="Custom OIDC", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "user-123",
            "groups": 42,
        }

        normalized = sso_service._normalize_user_info(provider, user_data)

        assert normalized["groups"] == []

    def test_generic_oidc_groups_nested_structures_filtered(self, sso_service):
        """Nested structures (dicts, lists) in the groups list are filtered to strings only."""
        provider = SSOProvider(id="custom_oidc", name="custom_oidc", display_name="Custom OIDC", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "user-123",
            "groups": ["Engineering", {"nested": "value"}, 42, "Platform", None],
        }

        normalized = sso_service._normalize_user_info(provider, user_data)

        assert sorted(normalized["groups"]) == ["Engineering", "Platform"]

    def test_generic_oidc_groups_with_email_verified(self, sso_service):
        """Groups extraction works alongside email_verified handling."""
        provider = SSOProvider(id="custom_oidc", name="custom_oidc", display_name="Custom OIDC", provider_type="oidc", provider_metadata={"groups_claim": "team_memberships"})
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "user-123",
            "email_verified": True,
            "team_memberships": ["backend", "sre"],
        }

        normalized = sso_service._normalize_user_info(provider, user_data)

        assert sorted(normalized["groups"]) == ["backend", "sre"]
        assert normalized["email_verified"] is True

    def test_generic_oidc_roles_merged_into_groups(self, sso_service):
        """Roles claim is merged into groups for generic OIDC providers."""
        provider = SSOProvider(id="custom_oidc", name="custom_oidc", display_name="Custom OIDC", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "user-123",
            "groups": ["Engineering"],
            "roles": ["admin", "editor"],
        }

        normalized = sso_service._normalize_user_info(provider, user_data)

        assert sorted(normalized["groups"]) == ["Engineering", "admin", "editor"]

    def test_generic_oidc_roles_only_without_groups(self, sso_service):
        """Roles are included even when no groups claim is present."""
        provider = SSOProvider(id="custom_oidc", name="custom_oidc", display_name="Custom OIDC", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "user-123",
            "roles": ["viewer", "editor"],
        }

        normalized = sso_service._normalize_user_info(provider, user_data)

        assert sorted(normalized["groups"]) == ["editor", "viewer"]

    def test_generic_oidc_roles_single_string(self, sso_service):
        """A single string roles value is included in groups."""
        provider = SSOProvider(id="custom_oidc", name="custom_oidc", display_name="Custom OIDC", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "user-123",
            "roles": "viewer",
        }

        normalized = sso_service._normalize_user_info(provider, user_data)

        assert normalized["groups"] == ["viewer"]

    def test_generic_oidc_roles_non_string_filtered(self, sso_service):
        """Non-string elements in roles list are filtered out."""
        provider = SSOProvider(id="custom_oidc", name="custom_oidc", display_name="Custom OIDC", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "user-123",
            "roles": ["admin", 123, None, {"role": "editor"}],
        }

        normalized = sso_service._normalize_user_info(provider, user_data)

        assert normalized["groups"] == ["admin"]

    def test_generic_oidc_groups_and_roles_deduplicated(self, sso_service):
        """Duplicates between groups and roles are removed."""
        provider = SSOProvider(id="custom_oidc", name="custom_oidc", display_name="Custom OIDC", provider_type="oidc")
        user_data = {
            "email": "user@company.com",
            "name": "Test User",
            "sub": "user-123",
            "groups": ["admin", "Engineering"],
            "roles": ["admin", "viewer"],
        }

        normalized = sso_service._normalize_user_info(provider, user_data)

        assert sorted(normalized["groups"]) == ["Engineering", "admin", "viewer"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
