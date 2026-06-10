# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_oauth_audience.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for OAuth audience parameter support (Issue #3499).

Tests cover:
- Authorization URL includes audience parameter
- Token exchange includes audience parameter
- Client credentials flow includes audience parameter
- Token refresh includes audience parameter
- Audience-only configs omit resource parameter
- Both audience and resource can coexist
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.oauth_manager import OAuthManager


@pytest.fixture
def oauth_manager():
    """Create OAuthManager instance for testing."""
    return OAuthManager()


class TestOAuthAudienceParameter:
    """Test suite for OAuth audience parameter support."""

    def test_create_authorization_url_with_audience(self, oauth_manager):
        """Test that authorization URL includes audience parameter when configured."""
        url = oauth_manager._create_authorization_url_with_pkce(
            credentials={
                "client_id": "test-client",
                "authorization_url": "https://auth.atlassian.com/authorize",
                "redirect_uri": "https://gateway.example.com/callback",
                "scopes": ["read:jira-work", "write:jira-work"],
                "audience": "api.atlassian.com",
            },
            state="test-state",
            code_challenge="test-challenge",
            code_challenge_method="S256",
        )

        assert "audience=api.atlassian.com" in url
        assert "client_id=test-client" in url
        assert "state=test-state" in url

    def test_create_authorization_url_without_audience(self, oauth_manager):
        """Test that authorization URL works without audience parameter."""
        url = oauth_manager._create_authorization_url_with_pkce(
            credentials={
                "client_id": "test-client",
                "authorization_url": "https://auth.example.com/authorize",
                "redirect_uri": "https://gateway.example.com/callback",
                "scopes": ["read", "write"],
            },
            state="test-state",
            code_challenge="test-challenge",
            code_challenge_method="S256",
        )

        assert "audience=" not in url
        assert "client_id=test-client" in url

    def test_create_authorization_url_with_audience_and_resource(self, oauth_manager):
        """Test that both audience and resource can be included together."""
        url = oauth_manager._create_authorization_url_with_pkce(
            credentials={
                "client_id": "test-client",
                "authorization_url": "https://auth.example.com/authorize",
                "redirect_uri": "https://gateway.example.com/callback",
                "scopes": ["read"],
                "audience": "https://my-api.example.com",
                "resource": "https://mcp-server.example.com",
            },
            state="test-state",
            code_challenge="test-challenge",
            code_challenge_method="S256",
        )

        assert "audience=https%3A%2F%2Fmy-api.example.com" in url
        assert "resource=https%3A%2F%2Fmcp-server.example.com" in url

    @pytest.mark.asyncio
    async def test_exchange_code_includes_audience(self, oauth_manager):
        """Test that token exchange includes audience parameter."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"access_token": "test-token", "token_type": "Bearer", "expires_in": 3600}

        with patch.object(oauth_manager, "_post_token_request", new_callable=AsyncMock, return_value=mock_response):
            credentials = {
                "client_id": "test-client",
                "client_secret": "test-secret",
                "token_url": "https://auth.atlassian.com/oauth/token",
                "redirect_uri": "https://gateway.example.com/callback",
                "audience": "api.atlassian.com",
            }

            result = await oauth_manager._exchange_code_for_tokens(credentials=credentials, code="auth-code-123", code_verifier="test-verifier")

            # Verify the token request was called
            oauth_manager._post_token_request.assert_called_once()
            call_args = oauth_manager._post_token_request.call_args
            token_data = call_args[0][1]  # Second positional argument

            # Check that audience is in the token data
            assert token_data["audience"] == "api.atlassian.com"
            assert result["access_token"] == "test-token"

    @pytest.mark.asyncio
    async def test_client_credentials_includes_audience(self, oauth_manager):
        """Test that client credentials flow includes audience parameter."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"access_token": "test-token", "token_type": "Bearer", "expires_in": 3600}

        with patch.object(oauth_manager, "_post_token_request", new_callable=AsyncMock, return_value=mock_response):
            credentials = {
                "grant_type": "client_credentials",
                "client_id": "test-client",
                "client_secret": "test-secret",
                "token_url": "https://my-tenant.auth0.com/oauth/token",
                "audience": "https://my-api.example.com",
                "scopes": ["read:data", "write:data"],
            }

            result = await oauth_manager._client_credentials_flow(credentials=credentials)

            # Verify the token request was called
            oauth_manager._post_token_request.assert_called_once()
            call_args = oauth_manager._post_token_request.call_args
            token_data = call_args[0][1]  # Second positional argument

            # Check that audience is in the token data
            assert token_data["audience"] == "https://my-api.example.com"
            assert result == "test-token"

    @pytest.mark.asyncio
    async def test_refresh_token_includes_audience(self, oauth_manager):
        """Test that token refresh includes audience parameter."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"access_token": "new-token", "token_type": "Bearer", "expires_in": 3600}

        with patch.object(oauth_manager, "_post_token_request", new_callable=AsyncMock, return_value=mock_response):
            credentials = {
                "client_id": "test-client",
                "client_secret": "test-secret",
                "token_url": "https://auth.example.com/token",
                "audience": "https://my-api.example.com",
            }

            result = await oauth_manager.refresh_token(refresh_token="old-refresh-token", credentials=credentials)

            # Verify the token request was called
            oauth_manager._post_token_request.assert_called_once()
            call_args = oauth_manager._post_token_request.call_args
            token_data = call_args[0][1]  # Second positional argument

            # Check that audience is in the token data
            assert token_data["audience"] == "https://my-api.example.com"
            assert result["access_token"] == "new-token"

    def test_should_include_resource_with_audience_only(self, oauth_manager):
        """Test that resource is omitted when only audience is configured."""
        credentials = {"audience": "api.atlassian.com"}

        result = oauth_manager._should_include_resource_parameter(credentials, scopes=["read"])

        assert result is False

    def test_should_include_resource_with_both_audience_and_resource(self, oauth_manager):
        """Test that resource is included when both audience and resource are configured."""
        credentials = {"audience": "https://my-api.example.com", "resource": "https://mcp-server.example.com"}

        result = oauth_manager._should_include_resource_parameter(credentials, scopes=["read"])

        assert result is True

    def test_should_include_resource_with_resource_only(self, oauth_manager):
        """Test that resource is included when only resource is configured."""
        credentials = {"resource": "https://mcp-server.example.com"}

        result = oauth_manager._should_include_resource_parameter(credentials, scopes=["read"])

        assert result is True

    @pytest.mark.asyncio
    async def test_atlassian_oauth_flow_example(self, oauth_manager):
        """Integration test: Atlassian OAuth flow with audience parameter."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"access_token": "atlassian-token", "token_type": "Bearer", "expires_in": 3600, "refresh_token": "refresh-token"}

        with patch.object(oauth_manager, "_post_token_request", new_callable=AsyncMock, return_value=mock_response):
            # Atlassian-specific configuration
            credentials = {
                "grant_type": "authorization_code",
                "client_id": "atlassian-client-id",
                "client_secret": "atlassian-client-secret",
                "authorization_url": "https://auth.atlassian.com/authorize",
                "token_url": "https://auth.atlassian.com/oauth/token",
                "redirect_uri": "https://gateway.example.com/oauth/callback",
                "audience": "api.atlassian.com",
                "scopes": ["read:jira-work", "write:jira-work", "read:confluence-content.all"],
            }

            # Test authorization URL generation
            auth_url = oauth_manager._create_authorization_url_with_pkce(credentials=credentials, state="atlassian-state", code_challenge="challenge", code_challenge_method="S256")

            assert "audience=api.atlassian.com" in auth_url
            assert "scope=read%3Ajira-work+write%3Ajira-work+read%3Aconfluence-content.all" in auth_url

            # Test token exchange
            result = await oauth_manager._exchange_code_for_tokens(credentials=credentials, code="atlassian-code", code_verifier="verifier")

            assert result["access_token"] == "atlassian-token"
            assert result["refresh_token"] == "refresh-token"

    @pytest.mark.asyncio
    async def test_auth0_oauth_flow_example(self, oauth_manager):
        """Integration test: Auth0 OAuth flow with audience parameter."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"access_token": "auth0-token", "token_type": "Bearer", "expires_in": 86400}

        with patch.object(oauth_manager, "_post_token_request", new_callable=AsyncMock, return_value=mock_response):
            # Auth0-specific configuration
            credentials = {
                "grant_type": "client_credentials",
                "client_id": "auth0-client-id",
                "client_secret": "auth0-client-secret",
                "token_url": "https://my-tenant.auth0.com/oauth/token",
                "audience": "https://my-api.example.com",
                "scopes": ["read:users", "write:users"],
            }

            result = await oauth_manager._client_credentials_flow(credentials=credentials)

            assert result == "auth0-token"

    def test_validate_audience_with_valid_uri(self, oauth_manager):
        """Test audience validation with valid URI format."""
        credentials = {"audience": "https://api.example.com"}
        result = oauth_manager._validate_and_extract_audience(credentials)
        assert result == "https://api.example.com"

    def test_validate_audience_with_valid_hostname(self, oauth_manager):
        """Test audience validation with valid hostname format."""
        credentials = {"audience": "api.atlassian.com"}
        result = oauth_manager._validate_and_extract_audience(credentials)
        assert result == "api.atlassian.com"

    def test_validate_audience_strips_whitespace(self, oauth_manager):
        """Test that audience validation strips leading/trailing whitespace."""
        credentials = {"audience": "  api.example.com  "}
        result = oauth_manager._validate_and_extract_audience(credentials)
        assert result == "api.example.com"

    def test_validate_audience_rejects_empty_string(self, oauth_manager):
        """Test that empty string audience returns None."""
        credentials = {"audience": ""}
        result = oauth_manager._validate_and_extract_audience(credentials)
        assert result is None

    def test_validate_audience_rejects_whitespace_only(self, oauth_manager):
        """Test that whitespace-only audience returns None."""
        credentials = {"audience": "   "}
        result = oauth_manager._validate_and_extract_audience(credentials)
        assert result is None

    def test_validate_audience_rejects_invalid_characters(self, oauth_manager):
        """Test that audience with control characters is rejected."""
        import pytest

        credentials = {"audience": "api.example.com\nmalicious"}
        with pytest.raises(ValueError, match="Invalid audience format"):
            oauth_manager._validate_and_extract_audience(credentials)

    def test_validate_audience_rejects_too_long(self, oauth_manager):
        """Test that audience exceeding max length is rejected."""
        import pytest

        credentials = {"audience": "a" * 513}  # Max is 512
        with pytest.raises(ValueError, match="Audience parameter too long"):
            oauth_manager._validate_and_extract_audience(credentials)

    def test_validate_audience_missing_returns_none(self, oauth_manager):
        """Test that missing audience returns None."""
        credentials = {}
        result = oauth_manager._validate_and_extract_audience(credentials)
        assert result is None

    @pytest.mark.asyncio
    async def test_token_exchange_with_audience_and_resource(self, oauth_manager):
        """Test that token exchange can include both audience and resource parameters."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"access_token": "test-token", "token_type": "Bearer", "expires_in": 3600}

        with patch.object(oauth_manager, "_post_token_request", new_callable=AsyncMock, return_value=mock_response):
            credentials = {
                "client_id": "test-client",
                "client_secret": "test-secret",
                "token_url": "https://auth.example.com/token",
                "redirect_uri": "https://gateway.example.com/callback",
                "audience": "https://my-api.example.com",
                "resource": "https://mcp-server.example.com",
                "scopes": ["read"],
            }

            result = await oauth_manager._exchange_code_for_tokens(credentials=credentials, code="auth-code", code_verifier="verifier")

            # Verify both parameters are in the request
            oauth_manager._post_token_request.assert_called_once()
            call_args = oauth_manager._post_token_request.call_args
            token_data = call_args[0][1]

            assert token_data["audience"] == "https://my-api.example.com"
            assert token_data["resource"] == "https://mcp-server.example.com"
            assert result["access_token"] == "test-token"
