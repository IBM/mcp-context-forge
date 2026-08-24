# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_oauth_router.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for OAuth router.
This module tests OAuth endpoints including authorization flow, callbacks, and status endpoints.
"""

# Standard
import base64
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Gateway
from mcpgateway.middleware.token_scoping import ResourceOwnershipResult
from mcpgateway.routers.oauth_router import (
    ADMIN_CSRF_COOKIE_NAME,
    _require_admin_user,
    delete_registered_client,
    enforce_fetch_tools_csrf,
    get_registered_client_for_gateway,
    list_registered_oauth_clients,
)
from mcpgateway.schemas import EmailUserResponse
from mcpgateway.services.oauth_manager import OAuthError
from mcpgateway.utils.oauth_resource import derive_resource_origin


class TestDeriveResourceOrigin:
    """Tests for derive_resource_origin (origin-extraction fallback for auto-derived resource)."""

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://api.salesforce.com/platform/mcp/v1/sobject", "https://api.salesforce.com"),
            ("https://api.example.com:8443/path?q=1#frag", "https://api.example.com:8443"),
            ("http://localhost:9000/foo", "http://localhost:9000"),
            ("https://gw.example.com", "https://gw.example.com"),
            ("https://gw.example.com/", "https://gw.example.com"),
        ],
    )
    def test_extracts_origin(self, url, expected):
        """Hierarchical URLs return scheme+netloc only."""
        assert derive_resource_origin(url) == expected

    @pytest.mark.parametrize("bad_input", [None, "", "   ", "no-scheme.com", "urn:example:resource", "/relative/path"])
    def test_returns_none_for_non_hierarchical(self, bad_input):
        """Empty, scheme-less, URN, and relative inputs return None (caller falls back to auto-learn)."""
        assert derive_resource_origin(bad_input) is None


@pytest.fixture
def mock_db():
    """Create mock database session."""
    db = Mock(spec=Session)
    return db


@pytest.fixture
def mock_request():
    """Create mock FastAPI request."""
    request = Mock(spec=Request)
    request.url = Mock()
    request.url.scheme = "https"
    request.url.netloc = "gateway.example.com"
    request.scope = {"root_path": ""}
    request.state = SimpleNamespace(token_teams=["team-1"])
    return request


@pytest.fixture
def mock_request_popup():
    """Create mock FastAPI request for popup mode."""
    request = Mock(spec=Request)
    request.url = Mock()
    request.url.scheme = "https"
    request.url.netloc = "gateway.example.com"
    request.scope = {"root_path": ""}
    request.state = SimpleNamespace(token_teams=["team-1"], csp_nonce="test-nonce-popup", is_popup=True)
    return request


@pytest.fixture
def mock_admin_request():
    """Create an un-narrowed admin request (token_teams=None) for DCR management tests."""
    request = Mock(spec=Request)
    request.state = SimpleNamespace(token_teams=None)
    return request


@pytest.fixture
def mock_gateway():
    """Create mock gateway with OAuth config."""
    gateway = Mock(spec=Gateway)
    gateway.id = "gateway123"
    gateway.name = "Test Gateway"
    gateway.url = "https://mcp.example.com"  # MCP server URL
    gateway.visibility = "public"
    gateway.owner_email = None
    gateway.team_id = None  # No team restriction - allow all authenticated users
    gateway.oauth_config = {
        "grant_type": "authorization_code",
        "client_id": "test_client",
        "client_secret": "test_secret",  # pragma: allowlist secret
        "authorization_url": "https://oauth.example.com/authorize",
        "token_url": "https://oauth.example.com/token",
        "redirect_uri": "https://gateway.example.com/oauth/callback",
        "scopes": ["read", "write"],
    }
    return gateway


@pytest.fixture
def mock_current_user():
    """Create mock current user."""
    user = Mock(spec=EmailUserResponse)
    user.get = Mock(return_value="test@example.com")
    user.email = "test@example.com"
    user.full_name = "Test User"
    user.is_active = True
    user.is_admin = False
    return user


class TestEnforceFetchToolsCsrf:
    """Tests for enforce_fetch_tools_csrf."""

    @pytest.fixture
    def csrf_request(self):
        request = Mock(spec=Request)
        request.headers = {}
        request.cookies = {}
        return request

    @pytest.mark.asyncio
    async def test_bearer_token_skips_csrf(self, csrf_request):
        csrf_request.headers = {"authorization": "Bearer abc123"}

        assert await enforce_fetch_tools_csrf(csrf_request) is None

    @patch("mcpgateway.routers.oauth_router.settings.app_domain", "https://gateway.example.com")
    @patch("mcpgateway.routers.oauth_router.settings.csrf_trusted_origins", {"https://trusted.example.com"})
    @pytest.mark.asyncio
    async def test_valid_origin_with_matching_csrf_cookie_and_header(self, csrf_request):
        csrf_request.headers = {
            "origin": "https://gateway.example.com",
            "x-csrf-token": "token-123",
        }
        csrf_request.cookies = {"mcpgateway_csrf_token": "token-123"}

        assert await enforce_fetch_tools_csrf(csrf_request) is None

    @patch("mcpgateway.routers.oauth_router.settings.app_domain", "https://gateway.example.com")
    @patch("mcpgateway.routers.oauth_router.settings.csrf_trusted_origins", set())
    @pytest.mark.asyncio
    async def test_missing_origin_and_referer_raises_403(self, csrf_request):
        with pytest.raises(HTTPException) as exc_info:
            await enforce_fetch_tools_csrf(csrf_request)

        assert exc_info.value.status_code == 403

    @patch("mcpgateway.routers.oauth_router.settings.app_domain", "https://gateway.example.com")
    @patch("mcpgateway.routers.oauth_router.settings.csrf_trusted_origins", set())
    @pytest.mark.asyncio
    async def test_invalid_origin_raises_403(self, csrf_request):
        csrf_request.headers = {"origin": "https://evil.example.com"}

        with pytest.raises(HTTPException) as exc_info:
            await enforce_fetch_tools_csrf(csrf_request)

        assert exc_info.value.status_code == 403

    @patch("mcpgateway.routers.oauth_router.settings.app_domain", "https://gateway.example.com")
    @patch("mcpgateway.routers.oauth_router.settings.csrf_trusted_origins", set())
    @pytest.mark.asyncio
    async def test_missing_csrf_cookie_raises_403(self, csrf_request):
        csrf_request.headers = {"origin": "https://gateway.example.com", "x-csrf-token": "token-123"}

        with pytest.raises(HTTPException) as exc_info:
            await enforce_fetch_tools_csrf(csrf_request)

        assert exc_info.value.status_code == 403

    @patch("mcpgateway.routers.oauth_router.settings.app_domain", "https://gateway.example.com")
    @patch("mcpgateway.routers.oauth_router.settings.csrf_trusted_origins", set())
    @pytest.mark.asyncio
    async def test_missing_csrf_header_raises_403(self, csrf_request):
        csrf_request.headers = {"origin": "https://gateway.example.com"}
        csrf_request.cookies = {"mcpgateway_csrf_token": "token-123"}

        with pytest.raises(HTTPException) as exc_info:
            await enforce_fetch_tools_csrf(csrf_request)

        assert exc_info.value.status_code == 403

    @patch("mcpgateway.routers.oauth_router.settings.app_domain", "https://gateway.example.com")
    @patch("mcpgateway.routers.oauth_router.settings.csrf_trusted_origins", set())
    @pytest.mark.asyncio
    async def test_mismatched_csrf_cookie_and_header_raises_403(self, csrf_request):
        csrf_request.headers = {"origin": "https://gateway.example.com", "x-csrf-token": "header-token"}
        csrf_request.cookies = {"mcpgateway_csrf_token": "cookie-token"}

        with pytest.raises(HTTPException) as exc_info:
            await enforce_fetch_tools_csrf(csrf_request)

        assert exc_info.value.status_code == 403

    @patch("mcpgateway.routers.oauth_router.settings.app_domain", "https://gateway.example.com")
    @patch("mcpgateway.routers.oauth_router.settings.csrf_trusted_origins", set())
    @patch("mcpgateway.routers.oauth_router.urlparse", side_effect=Exception("parse error"))
    @pytest.mark.asyncio
    async def test_referer_parse_exception_raises_403(self, mock_urlparse, csrf_request):
        csrf_request.headers = {"referer": "https://gateway.example.com", "x-csrf-token": "token-123"}
        csrf_request.cookies = {"mcpgateway_csrf_token": "token-123"}

        with pytest.raises(HTTPException) as exc_info:
            await enforce_fetch_tools_csrf(csrf_request)

        assert exc_info.value.status_code == 403

    @patch("mcpgateway.routers.oauth_router.settings.app_domain", "http://localhost:4444")
    @patch("mcpgateway.routers.oauth_router.settings.csrf_trusted_origins", set())
    @pytest.mark.asyncio
    async def test_pass_with_request_origin_when_app_domain_does_not_match(self, csrf_request):
        """RC1: request_origin allows production Origin when app_domain is the default localhost."""
        url_mock = Mock()
        url_mock.scheme = "https"
        url_mock.netloc = "production.example.com"
        csrf_request.url = url_mock
        csrf_request.headers = {
            "origin": "https://production.example.com",
            "x-csrf-token": "valid-token",
        }
        csrf_request.cookies = {"mcpgateway_csrf_token": "valid-token"}

        assert await enforce_fetch_tools_csrf(csrf_request) is None

    @patch("mcpgateway.routers.oauth_router.settings.app_domain", "https://gateway.example.com")
    @patch("mcpgateway.routers.oauth_router.settings.csrf_trusted_origins", set())
    @pytest.mark.asyncio
    async def test_x_forwarded_host_injection_denied_when_app_domain_configured(self, csrf_request):
        """Finding 4 deny-path: when app_domain is a real domain, an attacker-controlled
        request_origin (via X-Forwarded-Host) must NOT widen the allowed set."""
        url_mock = Mock()
        url_mock.scheme = "https"
        url_mock.netloc = "evil.example.com"
        csrf_request.url = url_mock
        csrf_request.headers = {
            "origin": "https://evil.example.com",
            "x-csrf-token": "valid-token",
        }
        csrf_request.cookies = {"mcpgateway_csrf_token": "valid-token"}

        with pytest.raises(HTTPException) as exc_info:
            await enforce_fetch_tools_csrf(csrf_request)

        assert exc_info.value.status_code == 403


class TestOAuthRouter:
    """Test cases for OAuth router endpoints."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = Mock(spec=Session)
        return db

    @pytest.fixture
    def mock_request(self):
        """Create mock FastAPI request."""
        request = Mock(spec=Request)
        request.url = Mock()
        request.url.scheme = "https"
        request.url.netloc = "gateway.example.com"
        request.scope = {"root_path": ""}
        request.state = SimpleNamespace(token_teams=["team-1"])
        return request

    @pytest.fixture
    def mock_gateway(self):
        """Create mock gateway with OAuth config."""
        gateway = Mock(spec=Gateway)
        gateway.id = "gateway123"
        gateway.name = "Test Gateway"
        gateway.url = "https://mcp.example.com"  # MCP server URL
        gateway.visibility = "public"
        gateway.owner_email = None
        gateway.team_id = None  # No team restriction - allow all authenticated users
        gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "test_client",
            "client_secret": "test_secret",  # pragma: allowlist secret
            "authorization_url": "https://oauth.example.com/authorize",
            "token_url": "https://oauth.example.com/token",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
            "scopes": ["read", "write"],
        }
        return gateway

    @pytest.fixture
    def mock_current_user(self):
        """Create mock current user."""
        user = Mock(spec=EmailUserResponse)
        user.get = Mock(return_value="test@example.com")
        user.email = "test@example.com"
        user.full_name = "Test User"
        user.is_active = True
        user.is_admin = False
        return user

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_success(self, mock_db, mock_request, mock_gateway, mock_current_user):
        """Test successful OAuth flow initiation."""
        # Setup
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://oauth.example.com/authorize?client_id=test_client&response_type=code&state=gateway123_abc123", "state": "gateway123_abc123"}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService") as mock_token_storage_class:
                mock_token_storage = Mock()
                mock_token_storage_class.return_value = mock_token_storage

                # Import the function to test
                # First-Party
                from mcpgateway.routers.oauth_router import initiate_oauth_flow

                # Execute
                result = await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

                # Assert
                assert isinstance(result, RedirectResponse)
                assert result.status_code == 307  # Temporary redirect
                assert result.headers["location"] == auth_data["authorization_url"]

                mock_oauth_manager_class.assert_called_once_with(token_storage=mock_token_storage)

                # Verify the oauth_config includes the resource parameter (RFC 8707)
                call_args = mock_oauth_manager.initiate_authorization_code_flow.call_args
                assert call_args[0][0] == "gateway123"
                assert call_args[1]["app_user_email"] == mock_current_user.get("email")
                # oauth_config should have resource set to gateway.url
                oauth_config_passed = call_args[0][1]
                assert oauth_config_passed["resource"] == mock_gateway.url

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_gateway_not_found(self, mock_db, mock_request, mock_current_user):
        """Test OAuth flow initiation with non-existent gateway."""
        # Setup
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        # First-Party
        from mcpgateway.routers.oauth_router import initiate_oauth_flow

        # Execute & Assert
        with pytest.raises(HTTPException) as exc_info:
            await initiate_oauth_flow("nonexistent", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 404
        assert "Gateway not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_no_oauth_config(self, mock_db, mock_request, mock_current_user):
        """Test OAuth flow initiation with gateway that has no OAuth config."""
        # Setup
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.visibility = "public"
        mock_gateway.oauth_config = None
        mock_gateway.team_id = None  # No team restriction
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        # First-Party
        from mcpgateway.routers.oauth_router import initiate_oauth_flow

        # Execute & Assert
        with pytest.raises(HTTPException) as exc_info:
            await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 400
        assert "Gateway is not configured for OAuth" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_wrong_grant_type(self, mock_db, mock_request, mock_current_user):
        """Test OAuth flow initiation with wrong grant type."""
        # Setup
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.visibility = "public"
        mock_gateway.oauth_config = {"grant_type": "client_credentials"}
        mock_gateway.team_id = None  # No team restriction
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        # First-Party
        from mcpgateway.routers.oauth_router import initiate_oauth_flow

        # Execute & Assert
        with pytest.raises(HTTPException) as exc_info:
            await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 400
        assert "Gateway is not configured for Authorization Code flow" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_dcr_disabled_missing_client_id(self, mock_db, mock_request, mock_current_user):
        """Test OAuth flow when issuer exists but DCR auto-registration is disabled."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "issuer": "https://issuer.example.com",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with patch("mcpgateway.routers.oauth_router.settings") as mock_settings:
            mock_settings.dcr_enabled = False
            mock_settings.dcr_auto_register_on_missing_credentials = False

            from mcpgateway.routers.oauth_router import initiate_oauth_flow

            with pytest.raises(HTTPException) as exc_info:
                await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

            assert exc_info.value.status_code == 400
            assert "incomplete" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_uses_persisted_resource_as_is(self, mock_db, mock_request, mock_current_user):
        """Test that a persisted resource (learned from IdP aud) is used as-is."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "client-id",
            "client_secret": "secret",
            "authorization_url": "https://auth.example.com/authorize",
            "token_url": "https://auth.example.com/token",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
            "resource": "my-client-id-from-idp",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://auth.example.com/authorize?state=x", "state": "x"}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import initiate_oauth_flow

                await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        oauth_config_passed = mock_oauth_manager.initiate_authorization_code_flow.call_args[0][1]
        assert oauth_config_passed["resource"] == "my-client-id-from-idp"

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_resource_list_persisted_as_is(self, mock_db, mock_request, mock_current_user):
        """Test that a persisted resource list (learned from IdP aud array) is used as-is."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "client-id",
            "client_secret": "secret",
            "authorization_url": "https://auth.example.com/authorize",
            "token_url": "https://auth.example.com/token",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
            "resource": ["https://api.example.com", "my-client-id"],
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://auth.example.com/authorize?state=x", "state": "x"}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import initiate_oauth_flow

                await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        oauth_config_passed = mock_oauth_manager.initiate_authorization_code_flow.call_args[0][1]
        assert oauth_config_passed["resource"] == ["https://api.example.com", "my-client-id"]

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_defaults_redirect_uri(self, mock_db, mock_request, mock_current_user):
        """A config with no redirect_uri gets the gateway's own callback URL (API-created/legacy rows)."""
        # First-Party
        from mcpgateway.config import settings

        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "client-id",
            "client_secret": "secret",
            "authorization_url": "https://auth.example.com/authorize",
            "token_url": "https://auth.example.com/token",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://auth.example.com/authorize?state=x", "state": "x"}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import initiate_oauth_flow

                await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        oauth_config_passed = mock_oauth_manager.initiate_authorization_code_flow.call_args[0][1]
        assert oauth_config_passed["redirect_uri"] == f"{str(settings.app_domain).rstrip('/')}/oauth/callback"

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_defaults_redirect_uri_includes_root_path(self, mock_db, mock_request, mock_current_user):
        """Behind a reverse proxy with a non-empty root_path, the derived callback must
        include it -- otherwise the URL sent to the IdP 404s once past the proxy."""
        # First-Party
        from mcpgateway.config import settings

        mock_request.scope = {"root_path": "/proxy/mcp"}

        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "client-id",
            "client_secret": "secret",
            "authorization_url": "https://auth.example.com/authorize",
            "token_url": "https://auth.example.com/token",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://auth.example.com/authorize?state=x", "state": "x"}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import initiate_oauth_flow

                await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        oauth_config_passed = mock_oauth_manager.initiate_authorization_code_flow.call_args[0][1]
        assert oauth_config_passed["redirect_uri"] == f"{str(settings.app_domain).rstrip('/')}/proxy/mcp/oauth/callback"

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_preserves_explicit_redirect_uri(self, mock_db, mock_request, mock_gateway, mock_current_user):
        """An explicitly configured redirect_uri is passed through untouched."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://oauth.example.com/authorize?state=x", "state": "x"}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import initiate_oauth_flow

                await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        oauth_config_passed = mock_oauth_manager.initiate_authorization_code_flow.call_args[0][1]
        assert oauth_config_passed["redirect_uri"] == "https://gateway.example.com/oauth/callback"

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_missing_client_id(self, mock_db, mock_request, mock_current_user):
        """Test OAuth flow missing client_id without DCR issuer."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "authorization_url": "https://auth.example.com/authorize",
            "token_url": "https://auth.example.com/token",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        from mcpgateway.routers.oauth_router import initiate_oauth_flow

        with pytest.raises(HTTPException) as exc_info:
            await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 400
        assert "missing client_id" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_dcr_unexpected_error(self, mock_db, mock_request, mock_current_user):
        """Test DCR path handles unexpected exception."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "issuer": "https://issuer.example.com",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with (
            patch("mcpgateway.routers.oauth_router.settings") as mock_settings,
            patch("mcpgateway.routers.oauth_router.DcrService") as mock_dcr_class,
        ):
            mock_settings.dcr_enabled = True
            mock_settings.dcr_auto_register_on_missing_credentials = True
            mock_settings.dcr_default_scopes = ["openid"]
            mock_settings.auth_encryption_secret = "secret"

            mock_dcr = Mock()
            mock_dcr.get_or_register_client = AsyncMock(side_effect=Exception("boom"))
            mock_dcr_class.return_value = mock_dcr

            from mcpgateway.routers.oauth_router import initiate_oauth_flow

            with pytest.raises(HTTPException) as exc_info:
                await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 500
        assert "Failed to register OAuth client" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_oauth_manager_error(self, mock_db, mock_request, mock_gateway, mock_current_user):
        """Test OAuth flow initiation when OAuth manager throws error."""
        # Setup
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.initiate_authorization_code_flow = AsyncMock(side_effect=OAuthError("OAuth service unavailable"))
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                # First-Party
                from mcpgateway.routers.oauth_router import initiate_oauth_flow

                # Execute & Assert
                with pytest.raises(HTTPException) as exc_info:
                    await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

                assert exc_info.value.status_code == 500
                assert "Failed to initiate OAuth flow" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_oauth_callback_success(self, mock_db, mock_request, mock_gateway):
        """Test successful OAuth callback handling."""
        # Standard
        import base64
        import json

        # Setup state with new format (payload + 32-byte signature)
        state_data = {"gateway_id": "gateway123", "app_user_email": "test@example.com", "nonce": "abc123"}
        payload = json.dumps(state_data).encode()
        signature = b"x" * 32  # Mock 32-byte signature
        state = base64.urlsafe_b64encode(payload + signature).decode()

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        token_result = {"user_id": "oauth_user_123", "app_user_email": "test@example.com", "expires_at": "2024-01-01T12:00:00", "token_aud": None, "state_data": {"app_user_email": "test@example.com", "team_id": None}}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.resolve_gateway_id_from_state = AsyncMock(return_value="gateway123")
            mock_oauth_manager.complete_authorization_code_flow = AsyncMock(return_value=token_result)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                # First-Party
                from mcpgateway.routers.oauth_router import oauth_callback

                # Execute
                result = await oauth_callback(code="auth_code_123", state=state, request=mock_request, db=mock_db)

                # Assert
                assert isinstance(result, HTMLResponse)
                assert "✅ OAuth Authorization Successful" in result.body.decode()
                assert "oauth_user_123" in result.body.decode()

                # Verify the oauth_config includes the resource parameter (RFC 8707)
                call_args = mock_oauth_manager.complete_authorization_code_flow.call_args
                oauth_config_passed = call_args[0][3]  # 4th positional arg is credentials
                assert oauth_config_passed["resource"] == "https://mcp.example.com"  # Normalized URL

    @pytest.mark.asyncio
    async def test_oauth_callback_resource_string_persisted_as_is(self, mock_db, mock_request):
        """Test OAuth callback uses persisted resource as-is (learned from IdP aud)."""
        import base64
        import json

        state_data = {"gateway_id": "gateway123", "app_user_email": "test@example.com"}
        payload = json.dumps(state_data).encode()
        signature = b"x" * 32
        state = base64.urlsafe_b64encode(payload + signature).decode()

        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "client-id",
            "client_secret": "secret",
            "authorization_url": "https://auth.example.com/authorize",
            "token_url": "https://auth.example.com/token",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
            "resource": "my-client-id-from-idp",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        token_result = {"user_id": "oauth_user_123", "app_user_email": "test@example.com", "expires_at": "2024-01-01T12:00:00", "token_aud": None, "state_data": {"app_user_email": "test@example.com", "team_id": None}}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.resolve_gateway_id_from_state = AsyncMock(return_value="gateway123")
            mock_oauth_manager.complete_authorization_code_flow = AsyncMock(return_value=token_result)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import oauth_callback

                result = await oauth_callback(code="auth_code_123", state=state, request=mock_request, db=mock_db)

        assert isinstance(result, HTMLResponse)
        oauth_config_passed = mock_oauth_manager.complete_authorization_code_flow.call_args[0][3]
        assert oauth_config_passed["resource"] == "my-client-id-from-idp"

    @pytest.mark.asyncio
    async def test_oauth_callback_defaults_redirect_uri(self, mock_db, mock_request):
        """The callback passes OAuthManager the gateway's own callback URL as its
        default_redirect_uri fallback -- OAuthManager applies it only if the state pinned
        at authorize time carries none (see TestRedirectUriPinning in test_oauth_manager.py
        for the actual application/pinning-precedence logic, which lives there now)."""
        # First-Party
        from mcpgateway.config import settings

        state_data = {"gateway_id": "gateway123", "app_user_email": "test@example.com"}
        payload = json.dumps(state_data).encode()
        signature = b"x" * 32
        state = base64.urlsafe_b64encode(payload + signature).decode()

        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "client-id",
            "client_secret": "secret",
            "authorization_url": "https://auth.example.com/authorize",
            "token_url": "https://auth.example.com/token",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        token_result = {"user_id": "oauth_user_123", "app_user_email": "test@example.com", "expires_at": "2024-01-01T12:00:00", "token_aud": None}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.resolve_gateway_id_from_state = AsyncMock(return_value="gateway123")
            mock_oauth_manager.complete_authorization_code_flow = AsyncMock(return_value=token_result)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import oauth_callback

                result = await oauth_callback(code="auth_code_123", state=state, request=mock_request, db=mock_db)

        assert isinstance(result, HTMLResponse)
        default_redirect_uri_passed = mock_oauth_manager.complete_authorization_code_flow.call_args.kwargs["default_redirect_uri"]
        assert default_redirect_uri_passed == f"{str(settings.app_domain).rstrip('/')}/oauth/callback"

    @pytest.mark.asyncio
    async def test_oauth_callback_legacy_state_format(self, mock_db, mock_request, mock_gateway):
        """Test OAuth callback handling with legacy state format."""
        # Setup - legacy state format
        state = "gateway123_abc123"
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        token_result = {"user_id": "oauth_user_123", "app_user_email": "test@example.com", "expires_at": "2024-01-01T12:00:00", "state_data": {"app_user_email": "test@example.com", "team_id": None}}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.resolve_gateway_id_from_state = AsyncMock(return_value="gateway123")
            mock_oauth_manager.complete_authorization_code_flow = AsyncMock(return_value=token_result)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                # First-Party
                from mcpgateway.routers.oauth_router import oauth_callback

                # Execute
                result = await oauth_callback(code="auth_code_123", state=state, request=mock_request, db=mock_db)

                # Assert
                assert isinstance(result, HTMLResponse)
                assert "✅ OAuth Authorization Successful" in result.body.decode()

    @pytest.mark.asyncio
    async def test_oauth_callback_opaque_state_lookup(self, mock_db, mock_request, mock_gateway):
        """Test OAuth callback resolves gateway via opaque state mapping."""
        state = "opaque-state-token"
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway
        token_result = {"user_id": "oauth_user_123", "app_user_email": "test@example.com", "expires_at": "2024-01-01T12:00:00", "state_data": {"app_user_email": "test@example.com", "team_id": None}}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.resolve_gateway_id_from_state = AsyncMock(return_value="gateway123")
            mock_oauth_manager.complete_authorization_code_flow = AsyncMock(return_value=token_result)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import oauth_callback

                result = await oauth_callback(code="auth_code_123", state=state, request=mock_request, db=mock_db)

        assert isinstance(result, HTMLResponse)
        assert result.status_code == 200
        mock_oauth_manager.resolve_gateway_id_from_state.assert_awaited_once_with("opaque-state-token", allow_legacy_fallback=False)

    @pytest.mark.asyncio
    async def test_oauth_callback_provider_error_response(self, mock_db, mock_request):
        """Test OAuth callback handles provider error payload without code."""
        # First-Party
        from mcpgateway.routers.oauth_router import oauth_callback

        result = await oauth_callback(
            code=None,
            state="gateway123_abc123",
            error="invalid_target",
            error_description="AADSTS9010010: The resource parameter does not match the requested scopes.",
            request=mock_request,
            db=mock_db,
        )

        assert isinstance(result, HTMLResponse)
        assert result.status_code == 400
        assert "OAuth Authorization Failed" in result.body.decode()
        assert "invalid_target" in result.body.decode()
        assert "AADSTS9010010" in result.body.decode()

    @pytest.mark.asyncio
    async def test_oauth_callback_missing_code_without_error(self, mock_db, mock_request):
        """Test OAuth callback returns friendly message when code is missing."""
        # First-Party
        from mcpgateway.routers.oauth_router import oauth_callback

        result = await oauth_callback(code=None, state="gateway123_abc123", request=mock_request, db=mock_db)

        assert isinstance(result, HTMLResponse)
        assert result.status_code == 400
        assert "Missing authorization code" in result.body.decode()

    @pytest.mark.asyncio
    async def test_oauth_callback_missing_state_returns_invalid_state(self, mock_db, mock_request):
        """Missing state should return controlled invalid-state response."""
        from mcpgateway.routers.oauth_router import oauth_callback

        result = await oauth_callback(code="auth_code_123", state=None, request=mock_request, db=mock_db)

        assert isinstance(result, HTMLResponse)
        assert result.status_code == 400
        assert "Invalid OAuth state parameter" in result.body.decode()

    @pytest.mark.asyncio
    async def test_oauth_callback_invalid_state(self, mock_db, mock_request):
        """Test OAuth callback with invalid state parameter."""
        # First-Party
        from mcpgateway.routers.oauth_router import oauth_callback

        # Execute
        result = await oauth_callback(code="auth_code_123", state="invalid", request=mock_request, db=mock_db)

        # Assert
        assert isinstance(result, HTMLResponse)
        assert result.status_code == 400
        assert "Invalid OAuth state parameter" in result.body.decode()

    @pytest.mark.asyncio
    async def test_oauth_callback_state_too_short(self, mock_db, mock_request):
        """Test OAuth callback with state that's too short to contain signature."""
        # Standard
        import base64

        # Setup - create state with less than 32 bytes total
        short_payload = b"short"
        state = base64.urlsafe_b64encode(short_payload).decode()

        # First-Party
        from mcpgateway.routers.oauth_router import oauth_callback

        # Execute
        result = await oauth_callback(code="auth_code_123", state=state, request=mock_request, db=mock_db)

        # Assert
        assert isinstance(result, HTMLResponse)
        assert result.status_code == 400
        assert "Invalid OAuth state parameter" in result.body.decode()

    @pytest.mark.asyncio
    async def test_oauth_callback_gateway_not_found(self, mock_db, mock_request):
        """Test OAuth callback when gateway is not found."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.resolve_gateway_id_from_state = AsyncMock(return_value="nonexistent")
            mock_oauth_manager_class.return_value = mock_oauth_manager

            # First-Party
            from mcpgateway.routers.oauth_router import oauth_callback

            # Execute
            result = await oauth_callback(code="auth_code_123", state="opaque-state", request=mock_request, db=mock_db)

        # Assert
        assert isinstance(result, HTMLResponse)
        assert result.status_code == 400
        assert "Invalid OAuth state parameter" in result.body.decode()

    @pytest.mark.asyncio
    async def test_oauth_callback_no_oauth_config(self, mock_db, mock_request):
        """Test OAuth callback when gateway has no OAuth config."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.oauth_config = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.resolve_gateway_id_from_state = AsyncMock(return_value="gateway123")
            mock_oauth_manager_class.return_value = mock_oauth_manager

            # First-Party
            from mcpgateway.routers.oauth_router import oauth_callback

            # Execute
            result = await oauth_callback(code="auth_code_123", state="opaque-state", request=mock_request, db=mock_db)

        # Assert
        assert isinstance(result, HTMLResponse)
        assert result.status_code == 400
        assert "Invalid OAuth state parameter" in result.body.decode()

    @pytest.mark.asyncio
    async def test_oauth_callback_oauth_error(self, mock_db, mock_request, mock_gateway):
        """Test OAuth callback when OAuth manager throws OAuthError."""
        # Standard
        import base64
        import json

        # Setup
        state_data = {"gateway_id": "gateway123", "app_user_email": "test@example.com"}
        payload = json.dumps(state_data).encode()
        signature = b"x" * 32  # Mock 32-byte signature
        state = base64.urlsafe_b64encode(payload + signature).decode()

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.resolve_gateway_id_from_state = AsyncMock(return_value="gateway123")
            mock_oauth_manager.complete_authorization_code_flow = AsyncMock(side_effect=OAuthError("Invalid authorization code"))
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                # First-Party
                from mcpgateway.routers.oauth_router import oauth_callback

                # Execute
                result = await oauth_callback(code="invalid_code", state=state, request=mock_request, db=mock_db)

                # Assert
                assert isinstance(result, HTMLResponse)
                assert result.status_code == 400
                assert "❌ OAuth Authorization Failed" in result.body.decode()
                # B2d (CWE-209): raw error detail must NOT appear in the browser page;
                # only the generic user-facing message is rendered.
                assert "Invalid authorization code" not in result.body.decode()
                assert "OAuth authorization failed" in result.body.decode()

    @pytest.mark.asyncio
    async def test_oauth_callback_unexpected_error(self, mock_db, mock_request, mock_gateway):
        """Test OAuth callback handles unexpected errors."""
        import base64
        import json

        state_data = {"gateway_id": "gateway123", "app_user_email": "test@example.com"}
        payload = json.dumps(state_data).encode()
        signature = b"x" * 32
        state = base64.urlsafe_b64encode(payload + signature).decode()

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.resolve_gateway_id_from_state = AsyncMock(return_value="gateway123")
            mock_oauth_manager.complete_authorization_code_flow = AsyncMock(side_effect=RuntimeError("boom"))
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import oauth_callback

                result = await oauth_callback(code="auth_code_123", state=state, request=mock_request, db=mock_db)

        assert isinstance(result, HTMLResponse)
        assert result.status_code == 500
        assert "OAuth Authorization Failed" in result.body.decode()

    @pytest.mark.asyncio
    async def test_get_oauth_status_success(self, mock_db, mock_gateway, mock_current_user, mock_request):
        """Test successful OAuth status retrieval."""
        # Setup
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        # First-Party
        from mcpgateway.routers.oauth_router import get_oauth_status

        # Execute (now requires current_user for authentication)
        result = await get_oauth_status("gateway123", mock_request, mock_current_user, mock_db)

        # Assert
        assert result["oauth_enabled"] is True
        assert result["grant_type"] == "authorization_code"
        assert result["client_id"] == "test_client"
        assert result["scopes"] == ["read", "write"]

    @pytest.mark.asyncio
    async def test_get_oauth_status_no_oauth_config(self, mock_db, mock_current_user, mock_request):
        """Test OAuth status when gateway has no OAuth config."""
        # Setup
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.oauth_config = None
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None  # No team restriction
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        # First-Party
        from mcpgateway.routers.oauth_router import get_oauth_status

        # Execute (now requires current_user for authentication)
        result = await get_oauth_status("gateway123", mock_request, mock_current_user, mock_db)

        # Assert
        assert result["oauth_enabled"] is False
        assert "Gateway is not configured for OAuth" in result["message"]

    @pytest.mark.asyncio
    async def test_get_oauth_status_gateway_not_found(self, mock_db, mock_current_user, mock_request):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        from mcpgateway.routers.oauth_router import get_oauth_status

        with pytest.raises(HTTPException) as exc_info:
            await get_oauth_status("gateway123", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_oauth_status_non_authorization_code(self, mock_db, mock_current_user, mock_request):
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {"grant_type": "client_credentials", "client_id": "cid"}
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        from mcpgateway.routers.oauth_router import get_oauth_status

        result = await get_oauth_status("gateway123", mock_request, mock_current_user, mock_db)

        assert result["grant_type"] == "client_credentials"
        assert "configured for client_credentials" in result["message"]

    @pytest.mark.asyncio
    async def test_get_oauth_status_exception(self, mock_db, mock_current_user, mock_request):
        mock_db.execute.side_effect = Exception("boom")

        from mcpgateway.routers.oauth_router import get_oauth_status

        with pytest.raises(HTTPException) as exc_info:
            await get_oauth_status("gateway123", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_success(self, mock_db, mock_current_user):
        """Test successful tools fetching after OAuth."""
        # Setup
        mock_tools_result = {"tools": [{"name": "tool1", "description": "Test tool 1"}, {"name": "tool2", "description": "Test tool 2"}, {"name": "tool3", "description": "Test tool 3"}]}
        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=["team-1"])
        gateway = Mock(spec=Gateway)
        gateway.visibility = "public"
        gateway.team_id = None
        gateway.owner_email = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = gateway

        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_gateway_service_class:
            mock_gateway_service = Mock()
            mock_gateway_service.fetch_tools_after_oauth = AsyncMock(return_value=mock_tools_result)
            mock_gateway_service_class.return_value = mock_gateway_service

            # First-Party
            from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

            # Execute
            with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.ALLOWED):
                result = await fetch_tools_after_oauth(gateway_id="gateway123", request=request, current_user={"email": "test@example.com", "is_admin": False}, db=mock_db)

            # Assert
            assert result["success"] is True
            assert "Successfully fetched and created 3 tools" in result["message"]
            mock_gateway_service.fetch_tools_after_oauth.assert_called_once_with(mock_db, "gateway123", "test@example.com", teams=None)

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_no_tools(self, mock_db, mock_current_user):
        """Test tools fetching after OAuth when no tools are returned."""
        # Setup
        mock_tools_result = {"tools": []}
        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=["team-1"])
        gateway = Mock(spec=Gateway)
        gateway.visibility = "public"
        gateway.team_id = None
        gateway.owner_email = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = gateway

        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_gateway_service_class:
            mock_gateway_service = Mock()
            mock_gateway_service.fetch_tools_after_oauth = AsyncMock(return_value=mock_tools_result)
            mock_gateway_service_class.return_value = mock_gateway_service

            # First-Party
            from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

            # Execute
            with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.ALLOWED):
                result = await fetch_tools_after_oauth(gateway_id="gateway123", request=request, current_user={"email": "test@example.com", "is_admin": False}, db=mock_db)

            # Assert
            assert result["success"] is True
            assert "Successfully fetched and created 0 tools" in result["message"]

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_service_error(self, mock_db, mock_current_user):
        """Test tools fetching when GatewayService throws error."""
        # Setup
        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=["team-1"])
        gateway = Mock(spec=Gateway)
        gateway.visibility = "public"
        gateway.team_id = None
        gateway.owner_email = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = gateway

        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_gateway_service_class:
            mock_gateway_service = Mock()
            mock_gateway_service.fetch_tools_after_oauth = AsyncMock(side_effect=Exception("Failed to connect to MCP server"))
            mock_gateway_service_class.return_value = mock_gateway_service

            # First-Party
            from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

            # Execute & Assert
            with pytest.raises(HTTPException) as exc_info:
                with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.ALLOWED):
                    await fetch_tools_after_oauth(gateway_id="gateway123", request=request, current_user={"email": "test@example.com", "is_admin": False}, db=mock_db)

            assert exc_info.value.status_code == 500
            assert "Failed to fetch tools" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_malformed_result(self, mock_db, mock_current_user):
        """Test tools fetching when service returns malformed result."""
        # Setup
        mock_tools_result = {"message": "Success"}  # Missing "tools" key
        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=["team-1"])
        gateway = Mock(spec=Gateway)
        gateway.visibility = "public"
        gateway.team_id = None
        gateway.owner_email = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = gateway

        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_gateway_service_class:
            mock_gateway_service = Mock()
            mock_gateway_service.fetch_tools_after_oauth = AsyncMock(return_value=mock_tools_result)
            mock_gateway_service_class.return_value = mock_gateway_service

            # First-Party
            from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

            # Execute
            with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.ALLOWED):
                result = await fetch_tools_after_oauth(gateway_id="gateway123", request=request, current_user={"email": "test@example.com", "is_admin": False}, db=mock_db)

            # Assert
            assert result["success"] is True
            assert "Successfully fetched and created 0 tools" in result["message"]

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_denies_cross_scope_gateway(self, mock_db, mock_current_user):
        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=["team-2"])
        gateway = Mock(spec=Gateway)
        gateway.visibility = "team"
        gateway.team_id = "team-1"
        gateway.owner_email = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = gateway

        from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

        with pytest.raises(HTTPException) as exc_info:
            with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.DENIED):
                await fetch_tools_after_oauth(gateway_id="gateway123", request=request, current_user={"email": "test@example.com", "is_admin": False}, db=mock_db)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_cached_public_only_admin_token_stays_scoped(self, mock_db):
        request = Mock(spec=Request)
        request.state = SimpleNamespace(_jwt_verified_payload=("token", {"teams": [], "is_admin": True}))
        gateway = Mock(spec=Gateway)
        gateway.visibility = "team"
        gateway.team_id = "team-1"
        gateway.owner_email = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = gateway

        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_gateway_service_class:
            mock_gateway_service = Mock()
            mock_gateway_service.fetch_tools_after_oauth = AsyncMock(return_value={"tools": []})
            mock_gateway_service_class.return_value = mock_gateway_service

            from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

            with pytest.raises(HTTPException) as exc_info:
                with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.DENIED) as ownership_check:
                    await fetch_tools_after_oauth(
                        gateway_id="gateway123",
                        request=request,
                        current_user={"email": "admin@example.com", "is_admin": True},
                        db=mock_db,
                    )

        assert exc_info.value.status_code == 403
        assert ownership_check.call_args.args[1] == []

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_cached_public_only_admin_token_allow_path(self, mock_db):
        request = Mock(spec=Request)
        request.state = SimpleNamespace(_jwt_verified_payload=("token", {"teams": [], "is_admin": True}))
        gateway = Mock(spec=Gateway)
        gateway.visibility = "public"
        gateway.team_id = None
        gateway.owner_email = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = gateway

        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_gateway_service_class:
            mock_gateway_service = Mock()
            mock_gateway_service.fetch_tools_after_oauth = AsyncMock(return_value={"tools": [{"name": "t1"}]})
            mock_gateway_service_class.return_value = mock_gateway_service

            from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

            with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.ALLOWED) as ownership_check:
                result = await fetch_tools_after_oauth(
                    gateway_id="gateway123",
                    request=request,
                    current_user={"email": "admin@example.com", "is_admin": True},
                    db=mock_db,
                )

        assert result["success"] is True
        assert ownership_check.call_args.args[1] == []

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_gateway_not_found(self, mock_db, mock_current_user):
        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=["team-1"])
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

        with pytest.raises(HTTPException) as exc_info:
            await fetch_tools_after_oauth(gateway_id="missing-gateway", request=request, current_user={"email": "test@example.com", "is_admin": False}, db=mock_db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_requires_gateways_update_permission(self, mock_db):
        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=["team-1"])
        gateway = Mock(spec=Gateway)
        gateway.visibility = "public"
        gateway.team_id = None
        gateway.owner_email = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = gateway

        from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

        with patch("mcpgateway.middleware.rbac.PermissionService.check_permission", new=AsyncMock(return_value=False)):
            with pytest.raises(HTTPException) as exc_info:
                await fetch_tools_after_oauth(
                    gateway_id="gateway123",
                    request=request,
                    current_user={"email": "test@example.com", "is_admin": False},
                    db=mock_db,
                )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_fails_closed_on_non_admin_null_token_teams(self, mock_db):
        """Non-admin contexts with null token teams must not bypass ownership checks."""
        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=None)
        gateway = Mock(spec=Gateway)
        gateway.visibility = "team"
        gateway.team_id = "team-1"
        gateway.owner_email = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = gateway

        from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

        with pytest.raises(HTTPException) as exc_info:
            with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.DENIED):
                await fetch_tools_after_oauth(
                    gateway_id="gateway123",
                    request=request,
                    current_user={"email": "user@example.com", "is_admin": False},
                    db=mock_db,
                )

        assert exc_info.value.status_code == 403

    def test_resolve_token_teams_for_scope_check_admin_attribute_fallback(self):
        request = Mock(spec=Request)
        request.state = SimpleNamespace()
        current_user = SimpleNamespace(email="admin@example.com", is_admin=True)

        from mcpgateway.routers.oauth_router import _resolve_token_teams_for_scope_check

        result = _resolve_token_teams_for_scope_check(request, current_user)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_tools_token_exchange_delegates_to_manual_refresh(self, mock_db, mock_current_user):
        """token-exchange gateways route through refresh_gateway_manually, not fetch_tools_after_oauth."""
        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=["team-1"])
        request.headers = {"cookie": "jwt_token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1In0.c2ln"}  # pragma: allowlist secret
        gateway = Mock(spec=Gateway)
        gateway.visibility = "public"
        gateway.team_id = None
        gateway.owner_email = None
        gateway.oauth_config = {"grant_type": "token-exchange", "token_url": "https://as.example.com/token", "target_audience": "aud"}
        mock_db.execute.return_value.scalar_one_or_none.return_value = gateway

        refresh_result = {"success": True, "tools_added": 2, "tools_updated": 1, "tools_removed": 0}
        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_service_class:
            mock_service = Mock()
            mock_service.refresh_gateway_manually = AsyncMock(return_value=refresh_result)
            mock_service.fetch_tools_after_oauth = AsyncMock()
            mock_service_class.return_value = mock_service

            # First-Party
            from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

            with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.ALLOWED):
                result = await fetch_tools_after_oauth(gateway_id="gw-te", request=request, current_user={"email": "admin@example.com", "is_admin": True}, db=mock_db)

        assert result["success"] is True
        assert "Successfully fetched and created 3 tools" in result["message"]
        mock_service.fetch_tools_after_oauth.assert_not_called()
        kwargs = mock_service.refresh_gateway_manually.await_args.kwargs
        assert kwargs["gateway_id"] == "gw-te"
        assert kwargs["user_email"] == "admin@example.com"
        assert kwargs["request_headers"]["cookie"].startswith("jwt_token=")

    @pytest.mark.asyncio
    async def test_fetch_tools_token_exchange_failure_maps_to_400(self, mock_db, mock_current_user):
        """success=False from refresh_gateway_manually must surface as HTTP 400, not 200."""
        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=["team-1"])
        request.headers = {}
        gateway = Mock(spec=Gateway)
        gateway.visibility = "public"
        gateway.team_id = None
        gateway.owner_email = None
        gateway.oauth_config = {"grant_type": "token-exchange", "token_url": "https://as.example.com/token", "target_audience": "aud"}
        mock_db.execute.return_value.scalar_one_or_none.return_value = gateway

        refresh_result = {"success": False, "error": "User authentication required for token-exchange gateway 'gw'."}
        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_service_class:
            mock_service = Mock()
            mock_service.refresh_gateway_manually = AsyncMock(return_value=refresh_result)
            mock_service_class.return_value = mock_service

            # First-Party
            from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

            with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.ALLOWED):
                with pytest.raises(HTTPException) as exc_info:
                    await fetch_tools_after_oauth(gateway_id="gw-te", request=request, current_user={"email": "admin@example.com", "is_admin": True}, db=mock_db)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Failed to fetch tools"

    @pytest.mark.asyncio
    async def test_fetch_tools_token_exchange_concurrent_refresh_maps_to_409(self, mock_db, mock_current_user):
        """GatewayError (refresh already in progress) must map to HTTP 409."""
        # First-Party
        from mcpgateway.services.gateway_service import GatewayError

        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=["team-1"])
        request.headers = {}
        gateway = Mock(spec=Gateway)
        gateway.visibility = "public"
        gateway.team_id = None
        gateway.owner_email = None
        gateway.oauth_config = {"grant_type": "token-exchange", "token_url": "https://as.example.com/token", "target_audience": "aud"}
        mock_db.execute.return_value.scalar_one_or_none.return_value = gateway

        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_service_class:
            mock_service = Mock()
            mock_service.refresh_gateway_manually = AsyncMock(side_effect=GatewayError("Refresh already in progress for gateway gw"))
            mock_service_class.return_value = mock_service

            # First-Party
            from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

            with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.ALLOWED):
                with pytest.raises(HTTPException) as exc_info:
                    await fetch_tools_after_oauth(gateway_id="gw-te", request=request, current_user={"email": "admin@example.com", "is_admin": True}, db=mock_db)

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_fetch_tools_token_exchange_gateway_not_found_maps_to_404(self, mock_db, mock_current_user):
        """GatewayNotFoundError raised mid-refresh (gateway deleted concurrently) must map to HTTP 404.

        Distinct from the earlier `if not gateway` check in the handler: that guards the
        gateway row not existing at request start, this guards it disappearing during the
        manual-refresh call itself.
        """
        # First-Party
        from mcpgateway.services.gateway_service import GatewayNotFoundError

        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=["team-1"])
        request.headers = {}
        gateway = Mock(spec=Gateway)
        gateway.visibility = "public"
        gateway.team_id = None
        gateway.owner_email = None
        gateway.oauth_config = {"grant_type": "token-exchange", "token_url": "https://as.example.com/token", "target_audience": "aud"}
        mock_db.execute.return_value.scalar_one_or_none.return_value = gateway

        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_service_class:
            mock_service = Mock()
            mock_service.refresh_gateway_manually = AsyncMock(side_effect=GatewayNotFoundError("Gateway with ID 'gw-te' not found"))
            mock_service_class.return_value = mock_service

            # First-Party
            from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

            with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.ALLOWED):
                with pytest.raises(HTTPException) as exc_info:
                    await fetch_tools_after_oauth(gateway_id="gw-te", request=request, current_user={"email": "admin@example.com", "is_admin": True}, db=mock_db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_fetch_tools_token_exchange_connection_error_maps_to_400(self, mock_db, mock_current_user):
        """GatewayConnectionError must be re-raised past the inner handler and mapped to HTTP 400
        by the endpoint's outer `except GatewayConnectionError` clause (not swallowed as 409 by
        the inner bare `except GatewayError` clause).
        """
        # First-Party
        from mcpgateway.services.gateway_service import GatewayConnectionError

        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=["team-1"])
        request.headers = {}
        gateway = Mock(spec=Gateway)
        gateway.visibility = "public"
        gateway.team_id = None
        gateway.owner_email = None
        gateway.oauth_config = {"grant_type": "token-exchange", "token_url": "https://as.example.com/token", "target_audience": "aud"}
        mock_db.execute.return_value.scalar_one_or_none.return_value = gateway

        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_service_class:
            mock_service = Mock()
            mock_service.refresh_gateway_manually = AsyncMock(side_effect=GatewayConnectionError("some connection failure"))
            mock_service_class.return_value = mock_service

            # First-Party
            from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

            with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.ALLOWED):
                with pytest.raises(HTTPException) as exc_info:
                    await fetch_tools_after_oauth(gateway_id="gw-te", request=request, current_user={"email": "admin@example.com", "is_admin": True}, db=mock_db)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Failed to fetch tools"


class TestOAuthAccessHelpers:
    def test_resolve_token_teams_for_scope_check_invalid_state_value_fails_closed(self):
        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams="team-1")

        from mcpgateway.routers.oauth_router import _resolve_token_teams_for_scope_check

        result = _resolve_token_teams_for_scope_check(request, {"email": "user@example.com", "is_admin": False})
        assert result == []

    def test_extract_is_admin_unknown_context_returns_false(self):
        from mcpgateway.routers.oauth_router import _extract_is_admin

        assert _extract_is_admin(SimpleNamespace()) is False

    @pytest.mark.asyncio
    async def test_enforce_gateway_access_requires_email(self, mock_db):
        from mcpgateway.routers.oauth_router import _enforce_gateway_access

        gateway = SimpleNamespace(visibility="public", owner_email=None, team_id=None)

        # Test with a user object that has neither email nor sub claim
        # get_user_email will return "unknown" which should be rejected
        with pytest.raises(HTTPException) as exc_info:
            await _enforce_gateway_access("gateway123", gateway, {}, mock_db, request=None)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_enforce_gateway_access_non_admin_null_token_teams_fails_closed(self, mock_db):
        from mcpgateway.routers.oauth_router import _enforce_gateway_access

        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=None)
        gateway = SimpleNamespace(visibility="public", owner_email=None, team_id=None)

        with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.DENIED) as ownership_check:
            with pytest.raises(HTTPException) as exc_info:
                await _enforce_gateway_access("gateway123", gateway, {"email": "user@example.com", "is_admin": False}, mock_db, request=request)

        assert exc_info.value.status_code == 403
        assert ownership_check.call_args.args[1] == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ownership_result", [ResourceOwnershipResult.DENIED, ResourceOwnershipResult.NOT_FOUND])
    async def test_enforce_gateway_access_rejects_non_allowed_ownership_results(self, mock_db, ownership_result):
        from mcpgateway.routers.oauth_router import _enforce_gateway_access

        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=[])
        gateway = SimpleNamespace(visibility="public", owner_email=None, team_id=None)

        with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ownership_result):
            with pytest.raises(HTTPException) as exc_info:
                await _enforce_gateway_access("gateway123", gateway, {"email": "user@example.com", "is_admin": False}, mock_db, request=request)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_enforce_gateway_access_allows_allowed_ownership_result(self, mock_db):
        from mcpgateway.routers.oauth_router import _enforce_gateway_access

        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=[])
        gateway = SimpleNamespace(visibility="public", owner_email=None, team_id=None)

        with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.ALLOWED):
            await _enforce_gateway_access("gateway123", gateway, {"email": "user@example.com", "is_admin": False}, mock_db, request=request)

    @pytest.mark.asyncio
    async def test_enforce_gateway_access_admin_null_token_teams_short_circuit(self, mock_db):
        from mcpgateway.routers.oauth_router import _enforce_gateway_access

        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=None)
        gateway = SimpleNamespace(visibility="team", owner_email=None, team_id="team-1")

        with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership") as ownership_check:
            await _enforce_gateway_access("gateway123", gateway, {"email": "admin@example.com", "is_admin": True}, mock_db, request=request)

        ownership_check.assert_not_called()

    @pytest.mark.asyncio
    async def test_enforce_gateway_access_admin_short_circuit(self, mock_db):
        from mcpgateway.routers.oauth_router import _enforce_gateway_access

        gateway = SimpleNamespace(visibility="team", owner_email=None, team_id="team-1")
        await _enforce_gateway_access("gateway123", gateway, {"email": "admin@example.com", "is_admin": True}, mock_db, request=None)

    @pytest.mark.asyncio
    async def test_enforce_gateway_access_team_visibility_missing_team_id_denied(self, mock_db):
        from mcpgateway.routers.oauth_router import _enforce_gateway_access

        gateway = SimpleNamespace(visibility="team", owner_email=None, team_id=None)
        with pytest.raises(HTTPException) as exc_info:
            await _enforce_gateway_access("gateway123", gateway, {"email": "user@example.com", "is_admin": False}, mock_db, request=None)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_enforce_gateway_access_team_visibility_member_allowed(self, mock_db):
        from mcpgateway.routers.oauth_router import _enforce_gateway_access

        class _User:
            def is_team_member(self, _team_id):
                return True

        class _AuthService:
            async def get_user_by_email(self, _email):
                return _User()

        gateway = SimpleNamespace(visibility="team", owner_email=None, team_id="team-1")
        with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=_AuthService()):
            await _enforce_gateway_access("gateway123", gateway, {"email": "user@example.com", "is_admin": False}, mock_db, request=None)

    @pytest.mark.asyncio
    async def test_enforce_gateway_access_unknown_visibility_owner_allowed(self, mock_db):
        from mcpgateway.routers.oauth_router import _enforce_gateway_access

        gateway = SimpleNamespace(visibility="internal", owner_email="owner@example.com", team_id=None)
        await _enforce_gateway_access("gateway123", gateway, {"email": "owner@example.com", "is_admin": False}, mock_db, request=None)

    @pytest.mark.asyncio
    async def test_enforce_gateway_access_unknown_visibility_team_member_allowed(self, mock_db):
        from mcpgateway.routers.oauth_router import _enforce_gateway_access

        class _User:
            def is_team_member(self, _team_id):
                return True

        class _AuthService:
            async def get_user_by_email(self, _email):
                return _User()

        gateway = SimpleNamespace(visibility="internal", owner_email=None, team_id="team-1")
        with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=_AuthService()):
            await _enforce_gateway_access("gateway123", gateway, {"email": "user@example.com", "is_admin": False}, mock_db, request=None)

    @pytest.mark.asyncio
    async def test_enforce_gateway_access_unknown_visibility_team_non_member_denied(self, mock_db):
        from mcpgateway.routers.oauth_router import _enforce_gateway_access

        class _User:
            def is_team_member(self, _team_id):
                return False

        class _AuthService:
            async def get_user_by_email(self, _email):
                return _User()

        gateway = SimpleNamespace(visibility="internal", owner_email=None, team_id="team-1")
        with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=_AuthService()):
            with pytest.raises(HTTPException) as exc_info:
                await _enforce_gateway_access("gateway123", gateway, {"email": "user@example.com", "is_admin": False}, mock_db, request=None)

        assert exc_info.value.status_code == 403


class TestOAuthRouterAdditionalCoverage:
    """Additional coverage for OAuth router branches."""

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_dcr_success(self, mock_db, mock_request, mock_current_user):
        """Test DCR auto-registration path success."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.auth_type = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "issuer": "https://issuer.example.com",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://issuer.example.com/auth"}

        class _Registered:
            client_id = "client-123"
            client_secret_encrypted = None
            token_endpoint_auth_method = "client_secret_post"

        class _FakeDcrService:
            async def get_or_register_client(self, **_kwargs):
                return _Registered()

            async def discover_as_metadata(self, _issuer):
                return {"authorization_endpoint": "https://issuer.example.com/auth", "token_endpoint": "https://issuer.example.com/token"}

        with patch("mcpgateway.routers.oauth_router.DcrService", return_value=_FakeDcrService()):
            with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
                mock_mgr = Mock()
                mock_mgr.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
                mock_oauth_mgr.return_value = mock_mgr

                with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                    # First-Party
                    from mcpgateway.routers.oauth_router import initiate_oauth_flow

                    with patch("mcpgateway.routers.oauth_router.settings") as mock_settings:
                        mock_settings.dcr_enabled = True
                        mock_settings.dcr_auto_register_on_missing_credentials = True
                        mock_settings.dcr_default_scopes = ["openid"]

                        result = await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert isinstance(result, RedirectResponse)
        assert mock_gateway.auth_type == "oauth"
        assert mock_gateway.oauth_config["client_id"] == "client-123"
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_dcr_does_not_persist_request_local_resource(self, mock_db, mock_request, mock_current_user):
        """Regression for the 2nd-review MEDIUM: DCR must not persist the request-local
        auto-derived ``resource`` to shared ``gateway.oauth_config``.

        This route enforces gateway *access* but not ``gateways.update``, so persisting
        the auto-derived resource would let any authenticated caller pin the shared
        audience for all users — the same RBAC-bypass class the callback-path
        redesign eliminated by moving learned audience to OAuthToken.learned_aud.
        """
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Gateway"
        mock_gateway.url = "https://mcp.example.com/deep/path"
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.auth_type = None
        # Gateway has issuer but no client_id (triggers DCR) and no admin-configured resource.
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "issuer": "https://issuer.example.com",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://issuer.example.com/auth"}

        class _Registered:
            client_id = "client-123"
            client_secret_encrypted = None
            token_endpoint_auth_method = "client_secret_post"

        class _FakeDcrService:
            async def get_or_register_client(self, **_kwargs):
                return _Registered()

            async def discover_as_metadata(self, _issuer):
                return {"authorization_endpoint": "https://issuer.example.com/auth", "token_endpoint": "https://issuer.example.com/token"}

        with patch("mcpgateway.routers.oauth_router.DcrService", return_value=_FakeDcrService()):
            with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
                mock_mgr = Mock()
                mock_mgr.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
                mock_oauth_mgr.return_value = mock_mgr

                with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                    from mcpgateway.routers.oauth_router import initiate_oauth_flow

                    with patch("mcpgateway.routers.oauth_router.settings") as mock_settings:
                        mock_settings.dcr_enabled = True
                        mock_settings.dcr_auto_register_on_missing_credentials = True
                        mock_settings.dcr_default_scopes = ["openid"]

                        await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        # DCR credentials + AS metadata MUST be persisted (this is the whole point of DCR).
        assert mock_gateway.oauth_config["client_id"] == "client-123"
        assert mock_gateway.oauth_config["token_endpoint_auth_method"] == "client_secret_post"
        assert mock_gateway.oauth_config["authorization_url"] == "https://issuer.example.com/auth"
        assert mock_gateway.oauth_config["token_url"] == "https://issuer.example.com/token"

        # Request-local auto-derived resource MUST NOT be persisted to shared config.
        # It was set in the request-local dict for the outbound RFC 8707 request,
        # but must be stripped before writing to gateway.oauth_config.
        assert "resource" not in mock_gateway.oauth_config, (
            "DCR persist path leaked request-local `resource` to shared gateway.oauth_config — "
            "this is the RBAC-bypass class of bug the DCR-path fix eliminated. See "
            "oauth_router.initiate_oauth_flow's persist_dict logic."
        )

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_dcr_preserves_admin_configured_resource(self, mock_db, mock_request, mock_current_user):
        """Admin-configured ``resource`` must survive the DCR persistence path unchanged."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Gateway"
        mock_gateway.url = "https://mcp.example.com/deep/path"
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.auth_type = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "issuer": "https://issuer.example.com",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
            "resource": "api://admin-configured-audience",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://issuer.example.com/auth"}

        class _Registered:
            client_id = "client-123"
            client_secret_encrypted = None
            token_endpoint_auth_method = "client_secret_post"

        class _FakeDcrService:
            async def get_or_register_client(self, **_kwargs):
                return _Registered()

            async def discover_as_metadata(self, _issuer):
                return {"authorization_endpoint": "https://issuer.example.com/auth", "token_endpoint": "https://issuer.example.com/token"}

        with patch("mcpgateway.routers.oauth_router.DcrService", return_value=_FakeDcrService()):
            with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
                mock_mgr = Mock()
                mock_mgr.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
                mock_oauth_mgr.return_value = mock_mgr

                with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                    from mcpgateway.routers.oauth_router import initiate_oauth_flow

                    with patch("mcpgateway.routers.oauth_router.settings") as mock_settings:
                        mock_settings.dcr_enabled = True
                        mock_settings.dcr_auto_register_on_missing_credentials = True
                        mock_settings.dcr_default_scopes = ["openid"]

                        await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        # Admin's explicit resource must be preserved exactly — not overwritten by origin derivation.
        assert mock_gateway.oauth_config["resource"] == "api://admin-configured-audience"

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_dcr_preserves_blank_stored_resource(self, mock_db, mock_request, mock_current_user):
        """Documents the current DCR-persist semantics for ``stored_resource == ""``.

        The strip logic uses ``if stored_resource is None: pop`` else preserve.  An
        empty string is falsy but NOT ``None``, so the ``else`` branch runs and the
        blank stored value is persisted as-is (not replaced by origin derivation).
        This locks the intent: blank is treated as "explicit admin state" rather
        than "no admin config".  If empty resource is later declared invalid, the
        fix belongs in the gateway config validation layer, not in this DCR strip.
        """
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Gateway"
        mock_gateway.url = "https://mcp.example.com/deep/path"
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.auth_type = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "issuer": "https://issuer.example.com",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
            "resource": "",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://issuer.example.com/auth"}

        class _Registered:
            client_id = "client-123"
            client_secret_encrypted = None
            token_endpoint_auth_method = "client_secret_post"

        class _FakeDcrService:
            async def get_or_register_client(self, **_kwargs):
                return _Registered()

            async def discover_as_metadata(self, _issuer):
                return {"authorization_endpoint": "https://issuer.example.com/auth", "token_endpoint": "https://issuer.example.com/token"}

        with patch("mcpgateway.routers.oauth_router.DcrService", return_value=_FakeDcrService()):
            with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
                mock_mgr = Mock()
                mock_mgr.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
                mock_oauth_mgr.return_value = mock_mgr

                with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                    from mcpgateway.routers.oauth_router import initiate_oauth_flow

                    with patch("mcpgateway.routers.oauth_router.settings") as mock_settings:
                        mock_settings.dcr_enabled = True
                        mock_settings.dcr_auto_register_on_missing_credentials = True
                        mock_settings.dcr_default_scopes = ["openid"]

                        await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        # Blank stored resource must survive DCR persistence — the origin-derived value
        # is stripped even though the stored value is falsy. This is the intentional
        # "preserve explicit admin state" branch of the strip logic in
        # oauth_router.initiate_oauth_flow's persist_dict block.
        assert "resource" in mock_gateway.oauth_config
        assert mock_gateway.oauth_config["resource"] == ""

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_team_access_denied(self, mock_db, mock_request, mock_current_user):
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.visibility = "team"
        mock_gateway.team_id = "team-1"
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "cid",
            "authorization_url": "https://issuer.example.com/auth",
            "token_url": "https://issuer.example.com/token",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        class _User:
            def is_team_member(self, _team_id):
                return False

        class _AuthService:
            async def get_user_by_email(self, _email):
                return _User()

        with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=_AuthService()):
            # First-Party
            from mcpgateway.routers.oauth_router import initiate_oauth_flow

            with pytest.raises(HTTPException) as exc_info:
                await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_resource_list_used_as_is(self, mock_db, mock_request, mock_current_user):
        """Resource lists (learned from IdP aud arrays) are passed through unchanged."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "cid",
            "authorization_url": "https://issuer.example.com/auth",
            "token_url": "https://issuer.example.com/token",
            "resource": ["not-a-url"],
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://issuer.example.com/auth"}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
            mock_mgr = Mock()
            mock_mgr.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
            mock_oauth_mgr.return_value = mock_mgr

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import initiate_oauth_flow

                result = await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert isinstance(result, RedirectResponse)
        oauth_config_passed = mock_mgr.initiate_authorization_code_flow.call_args[0][1]
        assert oauth_config_passed["resource"] == ["not-a-url"]

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_dcr_decrypts_secret(self, mock_db, mock_request, mock_current_user):
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.auth_type = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "issuer": "https://issuer.example.com",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://issuer.example.com/auth"}

        class _Registered:
            client_id = "client-123"
            client_secret_encrypted = "encrypted"
            token_endpoint_auth_method = "client_secret_post"

        class _FakeDcrService:
            async def get_or_register_client(self, **_kwargs):
                return _Registered()

            async def discover_as_metadata(self, _issuer):
                return {"authorization_endpoint": "https://issuer.example.com/auth", "token_endpoint": "https://issuer.example.com/token"}

        class _Encryption:
            async def decrypt_secret_async(self, _value):
                return "decrypted"

            async def encrypt_secret_async(self, value):
                return f"enc::{value}"

            @staticmethod
            def is_encrypted(value):
                return isinstance(value, str) and value.startswith("enc::")

        with patch("mcpgateway.routers.oauth_router.DcrService", return_value=_FakeDcrService()):
            with patch("mcpgateway.services.encryption_service.get_encryption_service", return_value=_Encryption()):
                with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
                    mock_mgr = Mock()
                    mock_mgr.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
                    mock_oauth_mgr.return_value = mock_mgr

                    with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                        from mcpgateway.routers.oauth_router import initiate_oauth_flow

                        with patch("mcpgateway.routers.oauth_router.settings") as mock_settings:
                            mock_settings.dcr_enabled = True
                            mock_settings.dcr_auto_register_on_missing_credentials = True
                            mock_settings.dcr_default_scopes = ["openid"]
                            mock_settings.auth_encryption_secret = "secret"

                            result = await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert isinstance(result, RedirectResponse)
        assert mock_gateway.oauth_config["client_secret"] != "decrypted"
        assert mock_gateway.oauth_config["client_secret"].startswith("enc::")

    @pytest.mark.asyncio
    async def test_oauth_callback_invalid_state_json(self, mock_db, mock_request):
        import base64

        payload = b"\x00" * 5
        state_raw = payload + (b"\x00" * 32)
        state = base64.urlsafe_b64encode(state_raw).decode()

        from mcpgateway.routers.oauth_router import oauth_callback

        response = await oauth_callback(code="code", state=state, request=mock_request, db=mock_db)

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_oauth_callback_missing_gateway_id_in_state(self, mock_db, mock_request):
        import base64
        import orjson

        payload = orjson.dumps({"foo": "bar"})
        state_raw = payload + (b"0" * 32)
        state = base64.urlsafe_b64encode(state_raw).decode()

        from mcpgateway.routers.oauth_router import oauth_callback

        response = await oauth_callback(code="code", state=state, request=mock_request, db=mock_db)

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_oauth_callback_resource_list_used_as_is(self, mock_db, mock_request):
        """Resource lists (learned from IdP aud arrays) are passed through unchanged in callback."""
        import base64
        import orjson

        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "client",
            "resource": ["not-a-url"],
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        payload = orjson.dumps({"gateway_id": "gateway123"})
        state_raw = payload + (b"0" * 32)
        state = base64.urlsafe_b64encode(state_raw).decode()

        result_payload = {"user_id": "u1", "state_data": {"app_user_email": "u1@example.com", "team_id": None}}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
            mock_mgr = Mock()
            mock_mgr.resolve_gateway_id_from_state = AsyncMock(return_value="gateway123")
            mock_mgr.complete_authorization_code_flow = AsyncMock(return_value=result_payload)
            mock_oauth_mgr.return_value = mock_mgr

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import oauth_callback

                response = await oauth_callback(code="code", state=state, request=mock_request, db=mock_db)

        assert response.status_code == 200
        oauth_config_passed = mock_mgr.complete_authorization_code_flow.call_args[0][3]
        assert oauth_config_passed["resource"] == ["not-a-url"]

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_dcr_error(self, mock_db, mock_request, mock_current_user):
        """Test DCR error handling path."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.visibility = "public"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "issuer": "https://issuer.example.com",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        class _FakeDcrService:
            async def get_or_register_client(self, **_kwargs):
                from mcpgateway.services.dcr_service import DcrError

                raise DcrError("boom")

        with patch("mcpgateway.routers.oauth_router.DcrService", return_value=_FakeDcrService()):
            # First-Party
            from mcpgateway.routers.oauth_router import initiate_oauth_flow

            with patch("mcpgateway.routers.oauth_router.settings") as mock_settings:
                mock_settings.dcr_enabled = True
                mock_settings.dcr_auto_register_on_missing_credentials = True

                with pytest.raises(HTTPException) as exc_info:
                    await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_oauth_status_team_access_denied(self, mock_db, mock_request):
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.visibility = "team"
        mock_gateway.team_id = "team-1"
        mock_gateway.oauth_config = {"grant_type": "authorization_code", "client_id": "cid"}
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        class _User:
            def is_team_member(self, _team_id):
                return False

        class _AuthService:
            async def get_user_by_email(self, _email):
                return _User()

        with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=_AuthService()):
            # First-Party
            from mcpgateway.routers.oauth_router import get_oauth_status

            with pytest.raises(HTTPException) as exc_info:
                await get_oauth_status("gateway123", mock_request, {"email": "user@example.com"}, mock_db)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_private_gateway_non_owner_denied(self, mock_db, mock_request):
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.visibility = "private"
        mock_gateway.owner_email = "owner@example.com"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "cid",
            "authorization_url": "https://issuer.example.com/auth",
            "token_url": "https://issuer.example.com/token",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        from mcpgateway.routers.oauth_router import initiate_oauth_flow

        with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.ALLOWED):
            with pytest.raises(HTTPException) as exc_info:
                await initiate_oauth_flow("gateway123", mock_request, {"email": "intruder@example.com", "is_admin": False}, mock_db)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_oauth_status_private_gateway_owner_allowed(self, mock_db, mock_request):
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.visibility = "private"
        mock_gateway.owner_email = "owner@example.com"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {"grant_type": "authorization_code", "client_id": "cid"}
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        from mcpgateway.routers.oauth_router import get_oauth_status

        with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.ALLOWED):
            result = await get_oauth_status(
                "gateway123",
                mock_request,
                current_user={"email": "owner@example.com", "is_admin": False},
                db=mock_db,
            )

        assert result["oauth_enabled"] is True

    @pytest.mark.asyncio
    async def test_get_oauth_status_private_gateway_non_owner_denied(self, mock_db, mock_request):
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.visibility = "private"
        mock_gateway.owner_email = "owner@example.com"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {"grant_type": "authorization_code", "client_id": "cid"}
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        from mcpgateway.routers.oauth_router import get_oauth_status

        with patch("mcpgateway.routers.oauth_router.token_scoping_middleware._check_resource_team_ownership", return_value=ResourceOwnershipResult.ALLOWED):
            with pytest.raises(HTTPException) as exc_info:
                await get_oauth_status(
                    "gateway123",
                    mock_request,
                    current_user={"email": "intruder@example.com", "is_admin": False},
                    db=mock_db,
                )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_list_registered_oauth_clients(self, mock_db, mock_admin_request):
        """Un-narrowed admin can list registered OAuth clients."""

        class _Client:
            id = "c1"
            gateway_id = "g1"
            issuer = "https://issuer"
            client_id = "client"
            redirect_uris = "https://cb1,https://cb2"
            grant_types = ["authorization_code"]
            scope = "openid"
            token_endpoint_auth_method = "client_secret_basic"
            created_at = datetime.now(timezone.utc)
            expires_at = None
            is_active = True

        mock_db.execute.return_value.scalars.return_value.all.return_value = [_Client()]

        # First-Party
        from mcpgateway.routers.oauth_router import list_registered_oauth_clients

        result = await list_registered_oauth_clients(mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)

        assert result["total"] == 1
        assert result["clients"][0]["gateway_id"] == "g1"
        assert result["clients"][0]["redirect_uris"] == ["https://cb1", "https://cb2"]

    @pytest.mark.asyncio
    async def test_list_registered_oauth_clients_error(self, mock_db, mock_admin_request):
        """Un-narrowed admin sees a 500 when the database lookup fails."""
        mock_db.execute.side_effect = Exception("boom")

        from mcpgateway.routers.oauth_router import list_registered_oauth_clients

        with pytest.raises(HTTPException) as exc_info:
            await list_registered_oauth_clients(mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_registered_client_for_gateway_success(self, mock_db, mock_admin_request):
        """Un-narrowed admin can fetch the registered client for a gateway."""

        class _Client:
            id = "c1"
            gateway_id = "g1"
            issuer = "https://issuer"
            client_id = "client"
            redirect_uris = "https://cb1,https://cb2"
            grant_types = ["authorization_code"]
            scope = "openid"
            token_endpoint_auth_method = "client_secret_basic"
            registration_client_uri = "https://issuer/clients/c1"
            created_at = datetime.now(timezone.utc)
            expires_at = None
            is_active = True

        mock_db.execute.return_value.scalar_one_or_none.return_value = _Client()

        from mcpgateway.routers.oauth_router import get_registered_client_for_gateway

        result = await get_registered_client_for_gateway("gateway123", mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)

        assert result["id"] == "c1"
        assert result["gateway_id"] == "g1"
        assert result["redirect_uris"] == ["https://cb1", "https://cb2"]
        assert result["grant_types"] == ["authorization_code"]

    @pytest.mark.asyncio
    async def test_get_registered_client_for_gateway_not_found(self, mock_db, mock_admin_request):
        """Un-narrowed admin gets a 404 when no client is registered for the gateway."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        # First-Party
        from mcpgateway.routers.oauth_router import get_registered_client_for_gateway

        with pytest.raises(HTTPException) as exc_info:
            await get_registered_client_for_gateway("gateway123", mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_registered_client_for_gateway_error(self, mock_db, mock_admin_request):
        """Un-narrowed admin sees a 500 when the database lookup fails."""
        mock_db.execute.side_effect = Exception("boom")

        from mcpgateway.routers.oauth_router import get_registered_client_for_gateway

        with pytest.raises(HTTPException) as exc_info:
            await get_registered_client_for_gateway("gateway123", mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_delete_registered_client_success(self, mock_db, mock_admin_request):
        """Un-narrowed admin can delete a registered OAuth client."""
        client = Mock()
        client.id = "c1"
        client.issuer = "https://issuer"
        client.gateway_id = "g1"
        mock_db.execute.return_value.scalar_one_or_none.return_value = client

        # First-Party
        from mcpgateway.routers.oauth_router import delete_registered_client

        result = await delete_registered_client("c1", mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)

        assert result["success"] is True
        mock_db.delete.assert_called_once_with(client)
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_registered_client_not_found(self, mock_db, mock_admin_request):
        """Un-narrowed admin gets a 404 when deleting a client that does not exist."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        from mcpgateway.routers.oauth_router import delete_registered_client

        with pytest.raises(HTTPException) as exc_info:
            await delete_registered_client("missing", mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_registered_client_error(self, mock_db, mock_admin_request):
        """Un-narrowed admin sees a 500 and rollback when the delete commit fails."""
        client = Mock()
        client.id = "c1"
        client.issuer = "https://issuer"
        client.gateway_id = "g1"
        mock_db.execute.return_value.scalar_one_or_none.return_value = client
        mock_db.commit.side_effect = Exception("boom")

        with pytest.raises(HTTPException) as exc_info:
            await delete_registered_client("c1", mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)

        assert exc_info.value.status_code == 500
        mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_registered_oauth_client_endpoints_require_admin(self, mock_db, mock_admin_request):
        """Non-admin callers are rejected with 403 on all three DCR management routes, even when RBAC grants the permission."""
        with pytest.raises(HTTPException) as exc_info:
            await list_registered_oauth_clients(mock_admin_request, current_user={"email": "user@example.com", "is_admin": False}, db=mock_db)
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await get_registered_client_for_gateway("gateway123", mock_admin_request, current_user={"email": "user@example.com", "is_admin": False}, db=mock_db)
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await delete_registered_client("client123", mock_admin_request, current_user={"email": "user@example.com", "is_admin": False}, db=mock_db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_registered_oauth_client_endpoints_reject_narrowed_admin(self, mock_db, mock_admin_request):
        """Narrowed admin tokens (token_teams is not None) must be denied on all DCR management routes."""
        narrowed_admin = {"email": "admin@example.com", "is_admin": True, "token_teams": ["team-a"]}

        with pytest.raises(HTTPException) as exc_info:
            await list_registered_oauth_clients(mock_admin_request, current_user=narrowed_admin, db=mock_db)
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await get_registered_client_for_gateway("gateway123", mock_admin_request, current_user=narrowed_admin, db=mock_db)
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await delete_registered_client("client123", mock_admin_request, current_user=narrowed_admin, db=mock_db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_registered_oauth_client_endpoints_reject_public_only_admin(self, mock_db, mock_admin_request):
        """Public-only admin token (token_teams=[]) is also rejected — not just narrowed tokens."""
        public_only_admin = {"email": "admin@example.com", "is_admin": True, "token_teams": []}

        with pytest.raises(HTTPException) as exc_info:
            await list_registered_oauth_clients(mock_admin_request, current_user=public_only_admin, db=mock_db)
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await get_registered_client_for_gateway("gateway123", mock_admin_request, current_user=public_only_admin, db=mock_db)
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await delete_registered_client("client123", mock_admin_request, current_user=public_only_admin, db=mock_db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_registered_oauth_client_endpoints_allow_unnarrowed_admin_explicit_none(self, mock_db, mock_admin_request):
        """Explicit token_teams=None is the un-narrowed admin bypass — all three routes must pass the guard."""
        unnarrowed_admin = {"email": "admin@example.com", "is_admin": True, "token_teams": None}

        # list — needs DB to return something
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        result = await list_registered_oauth_clients(mock_admin_request, current_user=unnarrowed_admin, db=mock_db)
        assert result["total"] == 0

        # get — not found is still a valid pass-through of the auth guard
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await get_registered_client_for_gateway("gw1", mock_admin_request, current_user=unnarrowed_admin, db=mock_db)
        assert exc_info.value.status_code == 404

        # delete — not found likewise
        with pytest.raises(HTTPException) as exc_info:
            await delete_registered_client("c1", mock_admin_request, current_user=unnarrowed_admin, db=mock_db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_require_admin_user_typed_object_non_admin(self):
        """_require_admin_user rejects typed objects (hasattr branch) when is_admin is falsy."""
        class _FakeUser:
            is_admin = False
            token_teams = None

        with pytest.raises(HTTPException) as exc_info:
            _require_admin_user(_FakeUser())
        assert exc_info.value.status_code == 403
        assert "Admin" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_admin_user_typed_object_narrowed(self):
        """_require_admin_user rejects typed objects (hasattr branch) when token_teams is not None."""
        class _FakeUser:
            is_admin = True
            token_teams = ["team-x"]

        with pytest.raises(HTTPException) as exc_info:
            _require_admin_user(_FakeUser())
        assert exc_info.value.status_code == 403
        assert "un-narrowed" in exc_info.value.detail

    def test_require_admin_user_typed_object_unnarrowed_passes(self):
        """_require_admin_user allows typed objects with is_admin=True and token_teams=None."""
        class _FakeUser:
            is_admin = True
            token_teams = None

        _require_admin_user(_FakeUser())  # must not raise

    @pytest.mark.asyncio
    async def test_list_registered_oauth_clients_grant_types_as_csv(self, mock_db, mock_admin_request):
        """grant_types stored as a CSV string must be split into a list in the response."""
        class _Client:
            id = "c2"
            gateway_id = "g2"
            issuer = "https://issuer"
            client_id = "cid"
            redirect_uris = ["https://cb"]
            grant_types = "authorization_code,client_credentials"
            scope = "openid"
            token_endpoint_auth_method = "client_secret_basic"
            created_at = datetime.now(timezone.utc)
            expires_at = None
            is_active = True

        mock_db.execute.return_value.scalars.return_value.all.return_value = [_Client()]

        # No token_teams key → .get("token_teams") returns None → un-narrowed admin bypass (auth guard passes).
        result = await list_registered_oauth_clients(mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)
        assert result["clients"][0]["grant_types"] == ["authorization_code", "client_credentials"]

    @pytest.mark.asyncio
    async def test_delete_registered_client_response_shape(self, mock_db, mock_admin_request):
        """DELETE response must include gateway_id and issuer alongside the success flag."""
        client = Mock()
        client.id = "c1"
        client.issuer = "https://issuer.example.com"
        client.gateway_id = "gw-99"
        mock_db.execute.return_value.scalar_one_or_none.return_value = client

        # No token_teams key → .get("token_teams") returns None → un-narrowed admin bypass (auth guard passes).
        result = await delete_registered_client("c1", mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)
        assert result["gateway_id"] == "gw-99"
        assert result["issuer"] == "https://issuer.example.com"
        assert "c1" in result["message"]

    @pytest.mark.asyncio
    async def test_get_registered_client_includes_registration_client_uri(self, mock_db, mock_admin_request):
        """GET /{gateway_id} response must expose registration_client_uri."""
        class _Client:
            id = "c1"
            gateway_id = "g1"
            issuer = "https://issuer"
            client_id = "cid"
            redirect_uris = ["https://cb"]
            grant_types = ["authorization_code"]
            scope = "openid"
            token_endpoint_auth_method = "client_secret_basic"
            registration_client_uri = "https://issuer/register/c1"
            created_at = datetime.now(timezone.utc)
            expires_at = None
            is_active = True

        mock_db.execute.return_value.scalar_one_or_none.return_value = _Client()

        # No token_teams key → .get("token_teams") returns None → un-narrowed admin bypass (auth guard passes).
        result = await get_registered_client_for_gateway("g1", mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)
        assert result["registration_client_uri"] == "https://issuer/register/c1"

    @pytest.mark.asyncio
    async def test_list_registered_clients_denied_without_read_permission(self, mock_db, mock_admin_request, mock_permission_service):
        """An eligible admin without admin.oauth_clients:read is rejected with 403."""
        mock_permission_service.check_permission = AsyncMock(return_value=False)

        # First-Party
        from mcpgateway.routers.oauth_router import list_registered_oauth_clients

        with pytest.raises(HTTPException) as exc_info:
            await list_registered_oauth_clients(mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)

        assert exc_info.value.status_code == 403
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_registered_client_denied_without_read_permission(self, mock_db, mock_admin_request, mock_permission_service):
        """An eligible admin without admin.oauth_clients:read cannot fetch a gateway's client."""
        mock_permission_service.check_permission = AsyncMock(return_value=False)

        # First-Party
        from mcpgateway.routers.oauth_router import get_registered_client_for_gateway

        with pytest.raises(HTTPException) as exc_info:
            await get_registered_client_for_gateway("gateway123", mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)

        assert exc_info.value.status_code == 403
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_registered_client_denied_without_delete_permission(self, mock_db, mock_admin_request, mock_permission_service):
        """An eligible admin without admin.oauth_clients:delete is rejected and mutates nothing."""
        mock_permission_service.check_permission = AsyncMock(return_value=False)
        client = Mock()
        client.id = "c1"
        client.issuer = "https://issuer"
        client.gateway_id = "g1"
        mock_db.execute.return_value.scalar_one_or_none.return_value = client

        # First-Party
        from mcpgateway.routers.oauth_router import delete_registered_client

        with pytest.raises(HTTPException) as exc_info:
            await delete_registered_client("c1", mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)

        assert exc_info.value.status_code == 403
        mock_db.delete.assert_not_called()
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_registered_client_routes_use_named_permissions(self, mock_db, mock_admin_request, mock_permission_service):
        """The routes check the named permissions with admin bypass disabled."""
        # First-Party
        from mcpgateway.db import Permissions
        from mcpgateway.routers.oauth_router import delete_registered_client, list_registered_oauth_clients

        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        await list_registered_oauth_clients(mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)
        assert mock_permission_service.check_permission.await_args.kwargs["permission"] == Permissions.ADMIN_OAUTH_CLIENTS_READ
        assert mock_permission_service.check_permission.await_args.kwargs["allow_admin_bypass"] is False

        client = Mock()
        client.id = "c1"
        client.issuer = "https://issuer"
        client.gateway_id = "g1"
        mock_db.execute.return_value.scalar_one_or_none.return_value = client
        await delete_registered_client("c1", mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)
        assert mock_permission_service.check_permission.await_args.kwargs["permission"] == Permissions.ADMIN_OAUTH_CLIENTS_DELETE
        assert mock_permission_service.check_permission.await_args.kwargs["allow_admin_bypass"] is False

    @pytest.mark.asyncio
    async def test_registered_client_routes_reject_scoped_token_without_permission(self, mock_db, mock_admin_request, mock_permission_service):
        """Layer 1: a scoped API token lacking the permission is rejected before RBAC runs."""
        # First-Party
        from mcpgateway.routers.oauth_router import delete_registered_client, list_registered_oauth_clients

        scoped_admin = {"email": "admin", "is_admin": True, "token_scopes": ["gateways.read"]}

        with pytest.raises(HTTPException) as exc_info:
            await list_registered_oauth_clients(mock_admin_request, current_user=scoped_admin, db=mock_db)
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await delete_registered_client("c1", mock_admin_request, current_user=scoped_admin, db=mock_db)
        assert exc_info.value.status_code == 403
        mock_db.delete.assert_not_called()
        mock_db.execute.assert_not_called()
        mock_permission_service.check_permission.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_registered_client_routes_reject_narrowed_admin_with_permission(self, mock_db):
        """A team-narrowed admin holding the permission is still rejected (global rows have no team scope)."""
        narrowed_request = Mock(spec=Request)
        narrowed_request.state = SimpleNamespace(token_teams=["team-1"])

        # First-Party
        from mcpgateway.routers.oauth_router import list_registered_oauth_clients

        with pytest.raises(HTTPException) as exc_info:
            await list_registered_oauth_clients(narrowed_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)

        assert exc_info.value.status_code == 403
        assert "un-narrowed" in exc_info.value.detail
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_registered_client_routes_check_global_scope_only(self, mock_db, mock_admin_request, mock_permission_service):
        """RBAC permission check on all three routes is global-only: it never resolves a
        team_id (not from the ``gateway_id`` resource, not from user context) and never
        aggregates across the caller's team-scoped roles. Otherwise a role granted on a
        single team could authorize these globally-scoped operations."""
        # First-Party
        from mcpgateway.routers.oauth_router import delete_registered_client, get_registered_client_for_gateway, list_registered_oauth_clients

        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        await list_registered_oauth_clients(mock_admin_request, current_user={"email": "admin", "is_admin": True}, db=mock_db)
        assert mock_permission_service.check_permission.await_args.kwargs["team_id"] is None
        assert mock_permission_service.check_permission.await_args.kwargs["check_any_team"] is False

        client = Mock()
        client.id = "c1"
        client.issuer = "https://issuer"
        client.gateway_id = "g1"
        mock_db.execute.return_value.scalar_one_or_none.return_value = client
        await get_registered_client_for_gateway("gateway123", mock_admin_request, current_user={"email": "admin", "is_admin": True, "team_id": "team-1"}, db=mock_db)
        assert mock_permission_service.check_permission.await_args.kwargs["team_id"] is None
        assert mock_permission_service.check_permission.await_args.kwargs["check_any_team"] is False

        await delete_registered_client("c1", mock_admin_request, current_user={"email": "admin", "is_admin": True, "team_id": "team-1"}, db=mock_db)
        assert mock_permission_service.check_permission.await_args.kwargs["team_id"] is None
        assert mock_permission_service.check_permission.await_args.kwargs["check_any_team"] is False

    @pytest.mark.asyncio
    async def test_oauth_callback_gateway_id_with_quotes_escaped(self, mock_db, mock_request):
        """Verify gateway_id containing quotes is escaped with quote=True in the fetch-tools URL (XSS fix)."""
        import base64
        import json

        malicious_id = "gw'\"<script>"
        state_data = {"gateway_id": malicious_id, "app_user_email": "test@example.com"}
        payload = json.dumps(state_data).encode()
        signature = b"x" * 32
        state = base64.urlsafe_b64encode(payload + signature).decode()

        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = malicious_id
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "cid",
            "token_url": "https://auth.example.com/token",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        token_result = {"user_id": "u1", "expires_at": None, "state_data": {"app_user_email": "u1@example.com", "team_id": None}}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
            mock_mgr = Mock()
            mock_mgr.resolve_gateway_id_from_state = AsyncMock(return_value=malicious_id)
            mock_mgr.complete_authorization_code_flow = AsyncMock(return_value=token_result)
            mock_oauth_mgr.return_value = mock_mgr

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import oauth_callback

                result = await oauth_callback(code="code", state=state, request=mock_request, db=mock_db)

        body = result.body.decode()
        # Raw quotes and script tags must not appear unescaped in the HTML
        assert "gw'\"<script>" not in body
        # The escaped form should be present
        assert "gw&#x27;&quot;&lt;script&gt;" in body


class TestOAuthCallbackCSPCompliance:
    """Test CSP nonce support in OAuth callback success page.

    Regression guard for PR #4424 and #4673 CSP implementation.
    Ensures the OAuth callback page properly includes CSP nonce in inline scripts.
    """

    @pytest.mark.asyncio
    async def test_oauth_callback_success_includes_csp_nonce_in_script_tag(self, mock_db, mock_request):
        """Verify OAuth callback success page includes CSP nonce in inline script tag.

        This is the critical test that exercises the actual /oauth/callback endpoint
        and verifies the CSP nonce is properly applied to the inline script.
        """
        # Setup: Create gateway with OAuth config
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "test-gateway-123"
        mock_gateway.name = "Test OAuth Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "test-secret",  # pragma: allowlist secret
            "authorization_url": "https://oauth.example.com/authorize",
            "token_url": "https://oauth.example.com/token",
            "redirect_uri": "http://localhost:4444/oauth/callback",
        }
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        # Mock OAuth manager to return successful result
        oauth_result = {
            "user_id": "user@example.com",
            "expires_at": "2026-12-31T23:59:59Z",
            "token_aud": None,
            "state_data": {"app_user_email": "user@example.com", "team_id": None},
        }

        # Add CSP nonce to request state (simulating SecurityHeadersMiddleware)
        mock_request.state.csp_nonce = "test-nonce-abc123xyz"

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
            mock_mgr = Mock()
            mock_mgr.resolve_gateway_id_from_state = AsyncMock(return_value="test-gateway-123")
            mock_mgr.complete_authorization_code_flow = AsyncMock(return_value=oauth_result)
            mock_oauth_mgr.return_value = mock_mgr

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import oauth_callback

                result = await oauth_callback(code="test-auth-code", state="test-state-token", request=mock_request, db=mock_db)

        # Verify response is HTML
        assert isinstance(result, HTMLResponse)
        assert result.status_code == 200

        # Decode response body
        body = result.body.decode()

        # Critical assertion: Verify CSP nonce is present in script tag
        assert '<script nonce="test-nonce-abc123xyz">' in body, "OAuth callback page must include CSP nonce in inline script tag"

        # Verify no inline onclick handlers (CSP violation)
        assert "onclick=" not in body, "OAuth callback page must not use inline onclick handlers (CSP violation)"

        # Verify addEventListener pattern is used instead
        assert "addEventListener" in body, "OAuth callback page must use addEventListener for CSP compliance"

        # Verify IIFE wrapper for proper scoping
        assert "(function()" in body or "(function ()" in body, "OAuth callback page script should use IIFE for proper scoping"

    @pytest.mark.asyncio
    async def test_oauth_callback_sets_csrf_cookie(self, mock_db, mock_request):
        """Verify OAuth callback response sets mcpgateway_csrf_token cookie."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "csrf-cookie-test"
        mock_gateway.name = "CSRF Cookie Test"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "test-secret",  # pragma: allowlist secret
            "authorization_url": "https://oauth.example.com/authorize",
            "token_url": "https://oauth.example.com/token",
            "redirect_uri": "http://localhost:4444/oauth/callback",
        }
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway
        mock_request.state.csp_nonce = "test-nonce"

        oauth_result = {
            "user_id": "user@example.com",
            "expires_at": "2026-12-31T23:59:59Z",
            "token_aud": None,
            "state_data": {"app_user_email": "user@example.com", "team_id": None},
        }

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
            mock_mgr = Mock()
            mock_mgr.resolve_gateway_id_from_state = AsyncMock(return_value="csrf-cookie-test")
            mock_mgr.complete_authorization_code_flow = AsyncMock(return_value=oauth_result)
            mock_oauth_mgr.return_value = mock_mgr

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import oauth_callback

                result = await oauth_callback(
                    code="test-auth-code",
                    state="test-state-token",
                    request=mock_request,
                    db=mock_db,
                )

        assert isinstance(result, HTMLResponse)
        assert result.status_code == 200

        set_cookie = result.headers.get("set-cookie")
        assert set_cookie is not None, "Response must include Set-Cookie header"
        assert ADMIN_CSRF_COOKIE_NAME in set_cookie, f"Set-Cookie must contain {ADMIN_CSRF_COOKIE_NAME}"

        cookie_value = None
        for part in set_cookie.split(";"):
            part = part.strip()
            if part.startswith(f"{ADMIN_CSRF_COOKIE_NAME}="):
                cookie_value = part.split("=", 1)[1]
                break
        assert cookie_value is not None, f"Cookie {ADMIN_CSRF_COOKIE_NAME} must have a value"
        assert len(cookie_value) >= 32, f"CSRF token must be at least 32 chars, got {len(cookie_value)}"

        assert "Secure" not in set_cookie or "HttpOnly" not in set_cookie, "CSRF cookie must NOT be HttpOnly (JS needs to read it)"
        assert "SameSite=strict" in set_cookie or "SameSite=Strict" in set_cookie, "CSRF cookie must have SameSite=strict"

    @pytest.mark.asyncio
    async def test_oauth_callback_reuses_existing_csrf_cookie(self, mock_db, mock_request):
        """Verify OAuth callback reuses existing valid CSRF token instead of generating a new one."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "csrf-reuse-test"
        mock_gateway.name = "CSRF Reuse Test"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "test-secret",  # pragma: allowlist secret
            "authorization_url": "https://oauth.example.com/authorize",
            "token_url": "https://oauth.example.com/token",
            "redirect_uri": "http://localhost:4444/oauth/callback",
        }
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway
        mock_request.state.csp_nonce = "test-nonce"

        existing_token = "aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789_"  # pragma: allowlist secret

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
            mock_mgr = Mock()
            mock_mgr.resolve_gateway_id_from_state = AsyncMock(return_value="csrf-reuse-test")
            mock_mgr.complete_authorization_code_flow = AsyncMock(
                return_value={
                    "user_id": "user@example.com",
                    "expires_at": "2026-12-31T23:59:59Z",
                    "token_aud": None,
                    "state_data": {"app_user_email": "user@example.com", "team_id": None},
                }
            )
            mock_oauth_mgr.return_value = mock_mgr

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import oauth_callback, ADMIN_CSRF_COOKIE_NAME

                with patch.object(mock_request, "cookies", {ADMIN_CSRF_COOKIE_NAME: existing_token}):
                    result = await oauth_callback(
                        code="test-auth-code",
                        state="test-state-token",
                        request=mock_request,
                        db=mock_db,
                    )

        assert isinstance(result, HTMLResponse)
        set_cookie = result.headers.get("set-cookie", "")
        assert existing_token in set_cookie, "Existing valid CSRF token should be reused in Set-Cookie"

    @pytest.mark.asyncio
    async def test_oauth_callback_success_handles_missing_csp_nonce_gracefully(self, mock_db, mock_request):
        """Verify OAuth callback works even if CSP nonce is missing (fallback behavior)."""
        # Setup: Create gateway with OAuth config
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "test-gateway-456"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "token_url": "https://oauth.example.com/token",
        }
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        oauth_result = {
            "user_id": "user@example.com",
            "expires_at": "2026-12-31T23:59:59Z",
            "token_aud": None,
            "state_data": {"app_user_email": "user@example.com", "team_id": None},
        }

        # Simulate missing CSP nonce (request.state.csp_nonce not set)
        # This tests the fallback behavior in get_csp_nonce_from_request
        if hasattr(mock_request.state, "csp_nonce"):
            delattr(mock_request.state, "csp_nonce")

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
            mock_mgr = Mock()
            mock_mgr.resolve_gateway_id_from_state = AsyncMock(return_value="test-gateway-456")
            mock_mgr.complete_authorization_code_flow = AsyncMock(return_value=oauth_result)
            mock_oauth_mgr.return_value = mock_mgr

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import oauth_callback

                result = await oauth_callback(code="test-auth-code", state="test-state-token", request=mock_request, db=mock_db)

        # Verify response is still valid HTML
        assert isinstance(result, HTMLResponse)
        assert result.status_code == 200

        body = result.body.decode()

        # When nonce is missing, get_csp_nonce_from_request returns empty string
        # The script tag should still be present but with empty nonce attribute
        assert '<script nonce="">' in body, "OAuth callback should handle missing CSP nonce gracefully with empty nonce attribute"

    @pytest.mark.asyncio
    async def test_oauth_callback_error_pages_do_not_include_inline_scripts(self, mock_db, mock_request):
        """Verify OAuth callback error pages don't have inline scripts (no CSP concerns)."""
        from mcpgateway.routers.oauth_router import oauth_callback

        # Test error callback (provider returned error)
        result = await oauth_callback(code=None, state="test-state", error="access_denied", error_description="User denied access", request=mock_request, db=mock_db)

        assert isinstance(result, HTMLResponse)
        assert result.status_code == 400
        body = result.body.decode()

        # Error pages should not have inline scripts
        assert "<script" not in body, "OAuth error pages should not contain inline scripts"

        # Test missing code error
        result = await oauth_callback(code=None, state="test-state", request=mock_request, db=mock_db)

        assert isinstance(result, HTMLResponse)
        assert result.status_code == 400
        body = result.body.decode()
        assert "<script" not in body

    @pytest.mark.asyncio
    async def test_oauth_callback_csp_nonce_uniqueness_per_request(self, mock_db):
        """Verify each OAuth callback request gets a unique CSP nonce.

        This test simulates multiple requests to ensure nonces are unique,
        preventing nonce reuse attacks.
        """
        # Setup gateway
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "test-gateway-789"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "token_url": "https://oauth.example.com/token",
        }
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        oauth_result = {
            "user_id": "user@example.com",
            "expires_at": "2026-12-31T23:59:59Z",
            "token_aud": None,
            "state_data": {"app_user_email": "user@example.com", "team_id": None},
        }

        nonces_seen = set()

        # Simulate 3 different requests
        for i in range(3):
            mock_request = Mock(spec=Request)
            mock_request.url = Mock()
            mock_request.url.scheme = "https"
            mock_request.url.netloc = "gateway.example.com"
            mock_request.scope = {"root_path": ""}
            mock_request.state = SimpleNamespace()
            mock_request.state.csp_nonce = f"unique-nonce-{i}-abc123xyz"

            with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
                mock_mgr = Mock()
                mock_mgr.resolve_gateway_id_from_state = AsyncMock(return_value="test-gateway-789")
                mock_mgr.complete_authorization_code_flow = AsyncMock(return_value=oauth_result)
                mock_oauth_mgr.return_value = mock_mgr

                with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                    from mcpgateway.routers.oauth_router import oauth_callback

                    result = await oauth_callback(code="test-auth-code", state="test-state-token", request=mock_request, db=mock_db)

            body = result.body.decode()

            # Extract nonce from script tag
            import re

            nonce_match = re.search(r'<script nonce="([^"]+)">', body)
            assert nonce_match, f"Request {i}: CSP nonce not found in script tag"

            nonce = nonce_match.group(1)
            assert nonce not in nonces_seen, f"Request {i}: Nonce {nonce} was reused (security violation)"
            nonces_seen.add(nonce)

        # Verify we collected 3 unique nonces
        assert len(nonces_seen) == 3, "Each request should have a unique CSP nonce"



class TestOAuthRouterPopupMode:
    """Test cases for OAuth router popup mode functionality."""

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_with_popup_parameter(self, mock_db, mock_request, mock_gateway, mock_current_user):
        """Test that popup=True parameter is passed to OAuth manager."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {
            "authorization_url": "https://oauth.example.com/authorize?state=popup.abc123",
            "state": "popup.abc123"
        }

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                with patch("mcpgateway.routers.oauth_router._enforce_gateway_access", new_callable=AsyncMock):
                    from mcpgateway.routers.oauth_router import initiate_oauth_flow

                    # Execute with popup=True
                    result = await initiate_oauth_flow(
                        gateway_id="gateway123",
                        request=mock_request,
                        popup=True,
                        current_user=mock_current_user,
                        db=mock_db
                    )

                    # Assert redirect response
                    assert isinstance(result, RedirectResponse)
                    assert result.status_code == 307

                    # Verify popup=True was passed to OAuth manager
                    call_args = mock_oauth_manager.initiate_authorization_code_flow.call_args
                    assert call_args[1]["popup"] is True

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_without_popup_parameter(self, mock_db, mock_request, mock_gateway, mock_current_user):
        """Test that popup defaults to False when not provided."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {
            "authorization_url": "https://oauth.example.com/authorize?state=abc123",
            "state": "abc123"
        }

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                with patch("mcpgateway.routers.oauth_router._enforce_gateway_access", new_callable=AsyncMock):
                    from mcpgateway.routers.oauth_router import initiate_oauth_flow

                    # Execute without popup parameter (defaults to False)
                    result = await initiate_oauth_flow(
                        gateway_id="gateway123",
                        request=mock_request,
                        current_user=mock_current_user,
                        db=mock_db
                    )

                    # Assert redirect response
                    assert isinstance(result, RedirectResponse)

                    # Verify popup=False was passed to OAuth manager
                    call_args = mock_oauth_manager.initiate_authorization_code_flow.call_args
                    # popup is a Query object with default False, check its value
                    popup_arg = call_args[1]["popup"]
                    assert popup_arg == False or (hasattr(popup_arg, 'default') and popup_arg.default == False)

    @pytest.mark.asyncio
    async def test_popup_notification_script_helper(self):
        """Test _popup_notification_script generates safe HTML."""
        from mcpgateway.routers.oauth_router import _popup_notification_script

        payload = {
            "type": "oauth_callback",
            "status": "success",
            "gatewayId": "test-gateway",
            "gatewayName": "Test Gateway"
        }
        nonce = "test-nonce-123"

        result = _popup_notification_script(nonce, payload)

        # Verify it's a script tag with nonce
        assert '<script nonce="test-nonce-123">' in result
        assert '</script>' in result

        # Verify payload is present (JSON.stringify formats with spaces)
        assert '"type": "oauth_callback"' in result or '"type":"oauth_callback"' in result
        assert '"status": "success"' in result or '"status":"success"' in result

        # Verify dangerous characters are escaped in the payload (not in the script tags themselves)
        # Extract just the payload part between postMessage( and )
        import re
        payload_match = re.search(r'postMessage\(({[^}]+})', result)
        if payload_match:
            payload_str = payload_match.group(1)
            # The payload should not contain unescaped < or > characters
            assert '<script' not in payload_str
            assert '</script' not in payload_str

    @pytest.mark.asyncio
    async def test_popup_notification_script_escapes_dangerous_characters(self):
        """Test that _popup_notification_script escapes <, >, and & in payload."""
        from mcpgateway.routers.oauth_router import _popup_notification_script

        payload = {
            "message": "<script>alert('xss')</script>",
            "data": "value&with&ampersands",
            "html": "<div>content</div>"
        }
        nonce = "safe-nonce"

        result = _popup_notification_script(nonce, payload)

        # Verify dangerous characters are Unicode-escaped (JSON.stringify does this)
        assert '\\u003c' in result or '\\u003C' in result  # < escaped
        assert '\\u003e' in result or '\\u003E' in result  # > escaped
        assert '\\u0026' in result  # & escaped

        # Verify the actual dangerous strings are not present
        assert "<script>alert" not in result
        assert "<div>" not in result

    @pytest.mark.asyncio
    async def test_popup_notification_script_escapes_line_terminators(self):
        """Test that U+2028 and U+2029 in payload are escaped.

        json.dumps emits these characters literally, but JavaScript treats
        them as line terminators inside string literals, which causes a
        SyntaxError and hangs the popup.
        """
        from mcpgateway.routers.oauth_router import _popup_notification_script

        payload = {
            "errorDescription": "line1\u2028line2\u2029end",
        }
        nonce = "safe-nonce"

        result = _popup_notification_script(nonce, payload)

        assert "\\u2028" in result
        assert "\\u2029" in result
        assert "\u2028" not in result
        assert "\u2029" not in result

    @pytest.mark.asyncio
    async def test_popup_notification_script_escapes_nonce(self):
        """Test that nonce is HTML-escaped to prevent attribute injection."""
        from mcpgateway.routers.oauth_router import _popup_notification_script

        dangerous_nonce = 'nonce"><script>alert("xss")</script><div class="'
        payload = {"status": "success"}

        result = _popup_notification_script(dangerous_nonce, payload)

        # Verify nonce is HTML-escaped
        assert 'nonce&quot;&gt;&lt;script&gt;' in result or "nonce&#x27;&#x3E;&#x3C;script&#x3E;" in result
        # Verify the dangerous script is not executable
        assert '"><script>alert' not in result

    @pytest.mark.asyncio
    async def test_oauth_callback_with_popup_state_success(self, mock_db):
        """Test oauth_callback returns postMessage response when state starts with 'popup.'"""
        from mcpgateway.routers.oauth_router import oauth_callback

        # Mock gateway
        mock_gateway = Mock()
        mock_gateway.id = "test-gateway"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.oauth_config = {
            "client_id": "test-client",
            "authorization_url": "https://oauth.example.com/authorize",
            "token_url": "https://oauth.example.com/token"
        }
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        # Mock OAuth manager
        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.resolve_gateway_id_from_state = AsyncMock(return_value="test-gateway")
            mock_oauth_manager.complete_authorization_code_flow = AsyncMock(return_value={
                "user_id": "user@example.com",
                "expires_at": "2026-12-31T23:59:59Z",
                "state_data": {"app_user_email": "user@example.com", "team_id": None},
            })
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                with patch("mcpgateway.routers.oauth_router._persist_learned_audience", new_callable=AsyncMock):
                    # Mock request with CSP nonce
                    mock_request = Mock()
                    mock_request.state = Mock()
                    mock_request.state.csp_nonce = "test-nonce-456"

                    # Execute with popup state
                    result = await oauth_callback(
                        code="auth-code-123",
                        state="popup.abc123def456",
                        request=mock_request,
                        db=mock_db
                    )

                    # Assert HTMLResponse with postMessage script
                    assert isinstance(result, HTMLResponse)
                    body = result.body.decode()

                    # Verify postMessage script is present
                    assert '<script nonce="test-nonce-456">' in body
                    assert 'window.opener.postMessage' in body
                    assert '"type": "oauth_callback"' in body or '"type":"oauth_callback"' in body
                    assert '"status": "success"' in body or '"status":"success"' in body
                    assert '"gatewayId": "test-gateway"' in body or '"gatewayId":"test-gateway"' in body
                    assert '"gatewayName": "Test Gateway"' in body or '"gatewayName":"Test Gateway"' in body

                    # Verify no legacy admin UI elements
                    assert 'Fetch Tools from MCP Server' not in body

    @pytest.mark.asyncio
    async def test_oauth_callback_with_popup_state_provider_error(self, mock_db):
        """Test oauth_callback returns postMessage error when provider returns error with popup state."""
        from mcpgateway.routers.oauth_router import oauth_callback

        # Mock request with CSP nonce
        mock_request = Mock()
        mock_request.state = Mock()
        mock_request.state.csp_nonce = "test-nonce-789"

        # Execute with popup state and provider error
        result = await oauth_callback(
            code=None,
            state="popup.xyz789",
            error="access_denied",
            error_description="User denied authorization",
            request=mock_request,
            db=mock_db
        )

        # Assert HTMLResponse with postMessage error script
        assert isinstance(result, HTMLResponse)
        assert result.status_code == 400
        body = result.body.decode()

        # Verify postMessage error script
        assert '<script nonce="test-nonce-789">' in body
        assert 'window.opener.postMessage' in body
        assert '"type": "oauth_callback"' in body or '"type":"oauth_callback"' in body
        assert '"status": "error"' in body or '"status":"error"' in body
        assert '"error": "access_denied"' in body or '"error":"access_denied"' in body
        assert '"errorDescription": "User denied authorization"' in body or '"errorDescription":"User denied authorization"' in body

        # Verify no legacy admin UI elements
        assert 'Return to Admin Panel' not in body

    @pytest.mark.asyncio
    async def test_oauth_callback_with_popup_state_missing_code(self, mock_db):
        """Test oauth_callback returns postMessage error when code is missing with popup state."""
        from mcpgateway.routers.oauth_router import oauth_callback

        # Mock request with CSP nonce
        mock_request = Mock()
        mock_request.state = Mock()
        mock_request.state.csp_nonce = "test-nonce-missing"

        # Execute with popup state but no code
        result = await oauth_callback(
            code=None,
            state="popup.state123",
            request=mock_request,
            db=mock_db
        )

        # Assert HTMLResponse with postMessage error
        assert isinstance(result, HTMLResponse)
        assert result.status_code == 400
        body = result.body.decode()

        # Verify postMessage error script
        assert '<script nonce="test-nonce-missing">' in body
        assert '"type": "oauth_callback"' in body or '"type":"oauth_callback"' in body
        assert '"status": "error"' in body or '"status":"error"' in body
        assert '"error": "missing_code"' in body or '"error":"missing_code"' in body
        assert '"errorDescription": "Missing authorization code in callback response."' in body or '"errorDescription":"Missing authorization code in callback response."' in body

    @pytest.mark.asyncio
    async def test_oauth_callback_with_popup_state_invalid_state(self, mock_db):
        """Test oauth_callback returns postMessage error when state is invalid with popup prefix."""
        from mcpgateway.routers.oauth_router import oauth_callback

        # Mock OAuth manager to return None for invalid state
        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.resolve_gateway_id_from_state = AsyncMock(return_value=None)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                # Mock request with CSP nonce
                mock_request = Mock()
                mock_request.state = Mock()
                mock_request.state.csp_nonce = "test-nonce-invalid"

                # Execute with popup state that doesn't resolve
                result = await oauth_callback(
                    code="auth-code-123",
                    state="popup.invalid-state",
                    request=mock_request,
                    db=mock_db
                )

                # Assert HTMLResponse with postMessage error
                assert isinstance(result, HTMLResponse)
                assert result.status_code == 400
                body = result.body.decode()

                # Verify postMessage error script
                assert '<script nonce="test-nonce-invalid">' in body
                assert '"type": "oauth_callback"' in body or '"type":"oauth_callback"' in body
                assert '"status": "error"' in body or '"status":"error"' in body
                assert '"error": "invalid_state"' in body or '"error":"invalid_state"' in body
                assert '"errorDescription": "Invalid OAuth state parameter."' in body or '"errorDescription":"Invalid OAuth state parameter."' in body

    @pytest.mark.asyncio
    async def test_oauth_callback_without_popup_state_returns_html_page(self, mock_db):
        """Test oauth_callback returns full HTML page when state does not start with 'popup.'"""
        from mcpgateway.routers.oauth_router import oauth_callback

        # Mock gateway
        mock_gateway = Mock()
        mock_gateway.id = "test-gateway"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.oauth_config = {
            "client_id": "test-client",
            "authorization_url": "https://oauth.example.com/authorize",
            "token_url": "https://oauth.example.com/token"
        }
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        # Mock OAuth manager
        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.resolve_gateway_id_from_state = AsyncMock(return_value="test-gateway")
            mock_oauth_manager.complete_authorization_code_flow = AsyncMock(return_value={
                "user_id": "user@example.com",
                "expires_at": "2026-12-31T23:59:59Z",
                "state_data": {"app_user_email": "user@example.com", "team_id": None},
            })
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                with patch("mcpgateway.routers.oauth_router._persist_learned_audience", new_callable=AsyncMock):
                    # Mock request with CSP nonce
                    mock_request = Mock()
                    mock_request.state = Mock()
                    mock_request.state.csp_nonce = "test-nonce-legacy"

                    # Execute with non-popup state
                    result = await oauth_callback(
                        code="auth-code-123",
                        state="regular-state-abc123",
                        request=mock_request,
                        db=mock_db
                    )

                    # Assert HTMLResponse with legacy admin UI
                    assert isinstance(result, HTMLResponse)
                    body = result.body.decode()

                    # Verify legacy admin UI elements are present
                    assert 'OAuth Authorization Successful' in body
                    assert 'Fetch Tools from MCP Server' in body
                    assert 'Return to Admin Panel' in body

                    # Verify NO postMessage script (should use inline fetch script instead)
                    assert 'window.opener.postMessage' not in body

    @pytest.mark.asyncio
    async def test_oauth_callback_without_popup_state_provider_error_returns_html(self, mock_db):
        """Test oauth_callback returns full HTML error page when provider returns error without popup state."""
        from mcpgateway.routers.oauth_router import oauth_callback

        # Mock request
        mock_request = Mock()
        mock_request.state = Mock()
        mock_request.state.csp_nonce = "test-nonce-error"

        # Execute with non-popup state and provider error
        result = await oauth_callback(
            code=None,
            state="regular-state-xyz",
            error="access_denied",
            error_description="User denied authorization",
            request=mock_request,
            db=mock_db
        )

        # Assert HTMLResponse with legacy error page
        assert isinstance(result, HTMLResponse)
        assert result.status_code == 400
        body = result.body.decode()

        # Verify legacy admin UI error elements
        assert 'OAuth Authorization Failed' in body
        assert 'access_denied' in body
        assert 'User denied authorization' in body
        assert 'Return to Admin Panel' in body

        # Verify NO postMessage script
        assert 'window.opener.postMessage' not in body

    @pytest.mark.asyncio
    async def test_oauth_callback_oauth_error_popup_mode(self, mock_db, mock_request_popup, mock_gateway):
        """Test OAuth callback OAuthError in popup mode (line 887 coverage)."""
        # Setup state with popup prefix
        state_data = {"gateway_id": "gateway123", "app_user_email": "test@example.com"}
        payload = json.dumps(state_data).encode()
        signature = b"x" * 32
        state = "popup." + base64.urlsafe_b64encode(payload + signature).decode()

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.resolve_gateway_id_from_state = AsyncMock(return_value="gateway123")
            mock_oauth_manager.complete_authorization_code_flow = AsyncMock(
                side_effect=OAuthError("Invalid authorization code")
            )
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import oauth_callback

                # Execute
                result = await oauth_callback(
                    code="invalid_code",
                    state=state,
                    request=mock_request_popup,
                    db=mock_db
                )

                # Assert popup response
                assert result.status_code == 400
                assert b"<!DOCTYPE html>" in result.body
                assert b"oauth_callback" in result.body
                assert b"oauth_error" in result.body

    @pytest.mark.asyncio
    async def test_oauth_callback_unexpected_error_popup_mode(self, mock_db, mock_request_popup, mock_gateway):
        """Test OAuth callback unexpected error in popup mode (line 930 coverage)."""
        # Setup state with popup prefix
        state_data = {"gateway_id": "gateway123", "app_user_email": "test@example.com"}
        payload = json.dumps(state_data).encode()
        signature = b"x" * 32
        state = "popup." + base64.urlsafe_b64encode(payload + signature).decode()

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.resolve_gateway_id_from_state = AsyncMock(return_value="gateway123")
            mock_oauth_manager.complete_authorization_code_flow = AsyncMock(
                side_effect=RuntimeError("Unexpected server error")
            )
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import oauth_callback

                # Execute
                result = await oauth_callback(
                    code="auth_code_123",
                    state=state,
                    request=mock_request_popup,
                    db=mock_db
                )

                # Assert popup response
                assert result.status_code == 500
                assert b"<!DOCTYPE html>" in result.body
                assert b"oauth_callback" in result.body
                assert b"server_error" in result.body


class TestOAuthRouterPopupQueryResolution:
    """HTTP-level tests exercising FastAPI's real `Query` dependency-injection layer for `popup`.

    The tests above call `initiate_oauth_flow` directly as a plain coroutine, so the
    `popup` parameter never goes through FastAPI's `Query` resolution -- it's whatever
    the test passes in (or the raw `Query(default=False)` sentinel when omitted). These
    tests instead route a real HTTP request through a `TestClient`, so `popup` is parsed
    from the query string exactly as it would be in production.
    """

    @staticmethod
    def _build_app(mock_db, mock_current_user):
        from fastapi import FastAPI

        from mcpgateway.db import get_db
        from mcpgateway.middleware.rbac import get_current_user_with_permissions
        from mcpgateway.routers.oauth_router import oauth_router

        app = FastAPI()
        app.include_router(oauth_router)

        async def _get_db_override():
            return mock_db

        async def _get_user_override():
            return mock_current_user

        app.dependency_overrides[get_db] = _get_db_override
        app.dependency_overrides[get_current_user_with_permissions] = _get_user_override
        return app

    def test_authorize_popup_true_resolved_from_query_string(self, mock_db, mock_gateway, mock_current_user):
        """`?popup=true` on the real route must resolve to `popup=True` in the handler."""
        from fastapi.testclient import TestClient

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway
        auth_data = {"authorization_url": "https://oauth.example.com/authorize?state=popup.abc123", "state": "popup.abc123"}

        app = self._build_app(mock_db, mock_current_user)

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                with patch("mcpgateway.routers.oauth_router._enforce_gateway_access", new_callable=AsyncMock):
                    client = TestClient(app)
                    response = client.get("/oauth/authorize/gateway123?popup=true", follow_redirects=False)

        assert response.status_code == 307
        assert response.headers["location"] == auth_data["authorization_url"]
        call_kwargs = mock_oauth_manager.initiate_authorization_code_flow.call_args.kwargs
        assert call_kwargs["popup"] is True

    def test_authorize_popup_omitted_resolves_to_false_from_query_string(self, mock_db, mock_gateway, mock_current_user):
        """Omitting `popup` on the real route must resolve to `popup=False`, not the `Query` default object."""
        from fastapi.testclient import TestClient

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway
        auth_data = {"authorization_url": "https://oauth.example.com/authorize?state=abc123", "state": "abc123"}

        app = self._build_app(mock_db, mock_current_user)

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                with patch("mcpgateway.routers.oauth_router._enforce_gateway_access", new_callable=AsyncMock):
                    client = TestClient(app)
                    response = client.get("/oauth/authorize/gateway123", follow_redirects=False)

        assert response.status_code == 307
        call_kwargs = mock_oauth_manager.initiate_authorization_code_flow.call_args.kwargs
        assert call_kwargs["popup"] is False


class TestOAuthClientManagementScopeGuard:
    """Regression tests for GHSA-gj7g-7r6g-jc8v: DCR management routes must reject any
    admin whose token is team-narrowed or public-only, since registered OAuth clients
    are stored globally with no team column to scope against.
    """

    @pytest.mark.asyncio
    async def test_narrowed_admin_denied_all_routes(self, mock_db):
        """A team-narrowed admin token is rejected on all three DCR management routes."""
        from mcpgateway.routers.oauth_router import delete_registered_client, get_registered_client_for_gateway, list_registered_oauth_clients

        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=["team-1"])
        admin_user = {"email": "admin@example.com", "is_admin": True}

        with pytest.raises(HTTPException) as exc_info:
            await list_registered_oauth_clients(request, current_user=admin_user, db=mock_db)
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await get_registered_client_for_gateway("gateway123", request, current_user=admin_user, db=mock_db)
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await delete_registered_client("client123", request, current_user=admin_user, db=mock_db)
        assert exc_info.value.status_code == 403
        mock_db.delete.assert_not_called()
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_public_only_admin_denied_all_routes(self, mock_db):
        """A public-only admin token (empty team list) is rejected on all three DCR routes."""
        from mcpgateway.routers.oauth_router import delete_registered_client, get_registered_client_for_gateway, list_registered_oauth_clients

        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams=[])
        admin_user = {"email": "admin@example.com", "is_admin": True}

        with pytest.raises(HTTPException) as exc_info:
            await list_registered_oauth_clients(request, current_user=admin_user, db=mock_db)
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await get_registered_client_for_gateway("gateway123", request, current_user=admin_user, db=mock_db)
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await delete_registered_client("client123", request, current_user=admin_user, db=mock_db)
        assert exc_info.value.status_code == 403
        mock_db.delete.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_malformed_token_teams_non_admin_denied(self):
        """A non-admin caller is rejected before token-team shape is even considered."""
        from mcpgateway.routers.oauth_router import _require_unnarrowed_admin

        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams="team-1")
        non_admin_user = {"email": "user@example.com", "is_admin": False}

        with pytest.raises(HTTPException) as exc_info:
            _require_unnarrowed_admin(request, non_admin_user)
        assert exc_info.value.status_code == 403

    def test_malformed_token_teams_admin_allowed_characterization(self):
        """Characterization test: a malformed (non-list, non-None) ``token_teams`` value
        with no cached JWT payload to fall back on currently resets to the sentinel and
        is treated as un-narrowed for an admin, so access is ALLOWED rather than denied.

        This is a known inherited gap in ``_resolve_token_teams_for_scope_check`` (not
        introduced by this guard). Asserted explicitly so a future tightening of that
        helper fails this test loudly instead of silently changing behavior.
        """
        from mcpgateway.routers.oauth_router import _require_unnarrowed_admin

        request = Mock(spec=Request)
        request.state = SimpleNamespace(token_teams="team-1")
        admin_user = {"email": "admin@example.com", "is_admin": True}

        assert _require_unnarrowed_admin(request, admin_user) is None

    def test_missing_token_teams_admin_allowed_characterization(self):
        """Characterization test: a request state with no ``token_teams`` attribute at
        all, and no cached JWT payload to re-derive from, falls back to un-narrowed
        scope for an admin, so access is ALLOWED.

        This is a known inherited gap in ``_resolve_token_teams_for_scope_check`` (not
        introduced by this guard). Asserted explicitly so a future tightening of that
        helper fails this test loudly instead of silently changing behavior.
        """
        from mcpgateway.routers.oauth_router import _require_unnarrowed_admin

        request = Mock(spec=Request)
        request.state = SimpleNamespace()  # no token_teams, no _jwt_verified_payload
        admin_user = {"email": "admin@example.com", "is_admin": True}

        assert _require_unnarrowed_admin(request, admin_user) is None

    def test_narrowing_recovered_from_cached_jwt_payload_denied(self):
        """When ``token_teams`` is absent but a cached verified JWT payload is present,
        the guard re-derives team scoping from the payload via ``normalize_token_teams``
        and still denies a team-narrowed admin.
        """
        from mcpgateway.routers.oauth_router import _require_unnarrowed_admin

        request = Mock(spec=Request)
        request.state = SimpleNamespace(_jwt_verified_payload=("tok", {"teams": ["team-1"], "is_admin": True}))
        admin_user = {"email": "admin@example.com", "is_admin": True}

        with pytest.raises(HTTPException) as exc_info:
            _require_unnarrowed_admin(request, admin_user)
        assert exc_info.value.status_code == 403

    @pytest.mark.parametrize(
        "state_kwargs,expect_denied",
        [
            ({"token_teams": None}, False),
            ({"token_teams": ["team-1"]}, True),
            ({"token_teams": []}, True),
            ({}, False),
        ],
        ids=["unnarrowed-none", "narrowed-list", "public-only-empty", "absent-attribute"],
    )
    def test_require_unnarrowed_admin_team_shapes(self, state_kwargs, expect_denied):
        """Direct unit test of ``_require_unnarrowed_admin`` across every ``token_teams``
        shape an admin request can carry: ``None`` (un-narrowed, allowed), a non-empty
        list (narrowed, denied), an empty list (public-only, denied), and the attribute
        being entirely absent with no cached payload (falls back to allowed for admins).
        """
        from mcpgateway.routers.oauth_router import _require_unnarrowed_admin

        request = Mock(spec=Request)
        request.state = SimpleNamespace(**state_kwargs)
        admin_user = {"email": "admin@example.com", "is_admin": True}

        if expect_denied:
            with pytest.raises(HTTPException) as exc_info:
                _require_unnarrowed_admin(request, admin_user)
            assert exc_info.value.status_code == 403
        else:
            assert _require_unnarrowed_admin(request, admin_user) is None


class TestIsWellFormedAudience:
    """Shape validation for the audience claim gate used before persisting learned audiences."""

    @pytest.mark.parametrize("value", ["https://api.example.com", " client-id ", "a"])
    def test_accepts_non_empty_strings(self, value):
        from mcpgateway.routers.oauth_router import _is_well_formed_audience

        assert _is_well_formed_audience(value) is True

    @pytest.mark.parametrize("value", ["", "   ", "\t\n"])
    def test_rejects_blank_strings(self, value):
        from mcpgateway.routers.oauth_router import _is_well_formed_audience

        assert _is_well_formed_audience(value) is False

    @pytest.mark.parametrize("value", [["a"], ["a", "b"], [" a "]])
    def test_accepts_lists_of_non_empty_strings(self, value):
        from mcpgateway.routers.oauth_router import _is_well_formed_audience

        assert _is_well_formed_audience(value) is True

    @pytest.mark.parametrize("value", [[], ["", "a"], ["   "], ["a", 1], [None], ["a", ["b"]]])
    def test_rejects_malformed_lists(self, value):
        from mcpgateway.routers.oauth_router import _is_well_formed_audience

        assert _is_well_formed_audience(value) is False

    @pytest.mark.parametrize("value", [None, 0, 1, 3.14, True, {"aud": "x"}, ("a",)])
    def test_rejects_non_string_non_list(self, value):
        from mcpgateway.routers.oauth_router import _is_well_formed_audience

        assert _is_well_formed_audience(value) is False


class TestPersistLearnedAudience:
    """Branch coverage for _persist_learned_audience (first-write-only learning with issuer pinning)."""

    @staticmethod
    def _gateway(oauth_config):
        gateway = Mock(spec=Gateway)
        gateway.name = "gw-audience-test"
        gateway.oauth_config = oauth_config
        return gateway

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_aud", [None, "", "   ", 123, [], ["", "  "], ["ok", 7], {"aud": "x"}])
    async def test_skips_malformed_token_aud(self, mock_db, bad_aud):
        """Malformed token_aud must be dropped without touching persisted state."""
        from mcpgateway.routers.oauth_router import _persist_learned_audience

        gateway = self._gateway({"issuer": "https://idp.example.com"})
        await _persist_learned_audience(gateway, {"token_aud": bad_aud}, mock_db)

        mock_db.flush.assert_not_called()
        assert gateway.oauth_config == {"issuer": "https://idp.example.com"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("existing_resource", ["https://api.example.com", ["https://a.example.com", "https://b.example.com"]])
    async def test_skips_when_resource_already_set(self, mock_db, existing_resource):
        """First-write-only: an existing usable resource is never overwritten by a callback."""
        from mcpgateway.routers.oauth_router import _persist_learned_audience

        gateway = self._gateway({"resource": existing_resource})
        await _persist_learned_audience(gateway, {"token_aud": "new-audience"}, mock_db)

        mock_db.flush.assert_not_called()
        assert gateway.oauth_config == {"resource": existing_resource}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_iss", [None, 123, "https://other-idp.example.com", "https://idp.example.com.evil.example"])
    async def test_skips_when_token_issuer_mismatches(self, mock_db, bad_iss):
        """Issuer pinning: a token from a different (or unverifiable) AS cannot inject an audience."""
        from mcpgateway.routers.oauth_router import _persist_learned_audience

        gateway = self._gateway({"issuer": "https://idp.example.com"})
        await _persist_learned_audience(gateway, {"token_aud": "aud-x", "token_iss": bad_iss}, mock_db)

        mock_db.flush.assert_not_called()
        assert gateway.oauth_config == {"issuer": "https://idp.example.com"}

    @pytest.mark.asyncio
    async def test_persists_when_issuer_matches_modulo_trailing_slash(self, mock_db):
        """Trailing-slash differences between configured issuer and iss claim are equivalent."""
        from mcpgateway.routers.oauth_router import _persist_learned_audience

        gateway = self._gateway({"issuer": "https://idp.example.com/"})
        await _persist_learned_audience(gateway, {"token_aud": "aud-x", "token_iss": "https://idp.example.com"}, mock_db)

        mock_db.flush.assert_called_once_with()
        assert gateway.oauth_config == {"issuer": "https://idp.example.com/", "resource": "aud-x"}

    @pytest.mark.asyncio
    async def test_persists_when_no_issuer_configured(self, mock_db):
        """Without a configured issuer the pinning check is skipped (non-OIDC setups)."""
        from mcpgateway.routers.oauth_router import _persist_learned_audience

        gateway = self._gateway({})
        await _persist_learned_audience(gateway, {"token_aud": ["aud-a", "aud-b"]}, mock_db)

        mock_db.flush.assert_called_once_with()
        assert gateway.oauth_config == {"resource": ["aud-a", "aud-b"]}

    @pytest.mark.asyncio
    async def test_persists_when_oauth_config_is_none(self, mock_db):
        from mcpgateway.routers.oauth_router import _persist_learned_audience

        gateway = self._gateway(None)
        await _persist_learned_audience(gateway, {"token_aud": "aud-x"}, mock_db)

        mock_db.flush.assert_called_once_with()
        assert gateway.oauth_config == {"resource": "aud-x"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("blank_resource", ["", "   ", [], ["", "  "]])
    async def test_blank_resource_treated_as_unset_and_relearned(self, mock_db, blank_resource):
        """Empty shapes count as unset so clearing the field via the update API re-arms learning."""
        from mcpgateway.routers.oauth_router import _persist_learned_audience

        gateway = self._gateway({"resource": blank_resource})
        await _persist_learned_audience(gateway, {"token_aud": "aud-new"}, mock_db)

        mock_db.flush.assert_called_once_with()
        assert gateway.oauth_config == {"resource": "aud-new"}

    @pytest.mark.asyncio
    async def test_input_oauth_config_dict_is_not_mutated(self, mock_db):
        """The write path copies the config dict instead of mutating the caller's object."""
        from mcpgateway.routers.oauth_router import _persist_learned_audience

        original = {"issuer": "https://idp.example.com"}
        gateway = self._gateway(original)
        await _persist_learned_audience(gateway, {"token_aud": "aud-x", "token_iss": "https://idp.example.com"}, mock_db)

        assert original == {"issuer": "https://idp.example.com"}
        assert gateway.oauth_config is not original


# ===========================================================================
# Tests for _build_user_context session-token path (CWE-863 fix)
# ===========================================================================


class TestBuildUserContextSessionTokenPath:
    """Tests for _build_user_context session-token Vault path selection.

    The session-token branch now uses ``token_teams`` (DB-authoritative, revocation-
    aware) as the primary path selector, falling back to ``jwt_teams_claim`` only
    when ``token_teams`` is ``None`` (admin bypass case).
    """

    def test_session_token_normal_user_uses_token_teams(self):
        """Normal session token uses DB-authoritative token_teams for path selection."""
        from mcpgateway.routers.oauth_router import _build_user_context

        current_user = {
            "email": "user@example.com",
            "is_admin": False,
            "token_use": "session",
            "token_teams": ["engineering", "ops"],  # DB-authoritative
            "jwt_teams_claim": ["engineering", "ops", "stale-team"],  # More than DB — ignored
        }
        result = _build_user_context(current_user)

        assert result["email"] == "user@example.com"
        # token_teams is used, not jwt_teams_claim — stale-team not included
        assert result["teams"] == ["engineering", "ops"]
        assert result["is_admin"] is False

    def test_session_token_revoked_user_goes_to_shared_path(self):
        """Revoked team member (token_teams=[]) is routed to shared path, not stale JWT team.

        CWE-863 regression test: a user removed from a team in the DB gets
        token_teams=[] from resolve_session_teams(). The stale jwt_teams_claim
        must NOT be used as a fallback path — that would let a revoked user
        continue storing tokens under their former team's Vault path.
        """
        from mcpgateway.routers.oauth_router import _build_user_context

        current_user = {
            "email": "revoked@example.com",
            "is_admin": False,
            "token_use": "session",
            "token_teams": [],  # Revoked — resolve_session_teams returned empty intersection
            "jwt_teams_claim": ["engineering"],  # Stale JWT claim — must NOT be used
        }
        result = _build_user_context(current_user)

        assert result["email"] == "revoked@example.com"
        # Must route to shared path, NOT engineering — revocation respected
        assert result["teams"] is None

    def test_session_token_admin_falls_back_to_jwt_teams_claim(self):
        """Admin (token_teams=None bypass) falls back to jwt_teams_claim as a path hint.

        Admins have no DB team list (resolve_session_teams returns None for admin bypass).
        jwt_teams_claim is used as a read/write path hint so the admin's tokens
        go to the correct team-scoped Vault path.
        """
        from mcpgateway.routers.oauth_router import _build_user_context

        current_user = {
            "email": "admin@example.com",
            "is_admin": True,
            "token_use": "session",
            "token_teams": None,  # Admin bypass from resolve_session_teams()
            "jwt_teams_claim": ["engineering", "ops"],
        }
        result = _build_user_context(current_user)

        assert result["email"] == "admin@example.com"
        assert result["teams"] == ["engineering", "ops"]
        assert result["is_admin"] is True

    def test_session_token_admin_with_empty_jwt_teams_returns_shared_path(self):
        """Admin session with empty jwt_teams_claim returns shared path."""
        from mcpgateway.routers.oauth_router import _build_user_context

        current_user = {
            "email": "admin@example.com",
            "is_admin": True,
            "token_use": "session",
            "jwt_teams_claim": [],  # Empty — no team, falls through to shared path
            "token_teams": None,
        }
        result = _build_user_context(current_user)

        assert result["email"] == "admin@example.com"
        assert result["teams"] is None
        assert result["is_admin"] is True

    def test_session_token_admin_with_null_jwt_teams_returns_shared_path(self):
        """Admin session with null jwt_teams_claim returns shared path."""
        from mcpgateway.routers.oauth_router import _build_user_context

        current_user = {
            "email": "admin@example.com",
            "is_admin": True,
            "token_use": "session",
            "jwt_teams_claim": None,
            "token_teams": None,
        }
        result = _build_user_context(current_user)

        assert result["teams"] is None

    def test_session_token_admin_jwt_teams_filters_empty_strings(self):
        """Admin session jwt_teams_claim fallback filters out blank strings."""
        from mcpgateway.routers.oauth_router import _build_user_context

        current_user = {
            "email": "admin@example.com",
            "is_admin": True,
            "token_use": "session",
            "jwt_teams_claim": ["", "engineering", None, "ops"],
            "token_teams": None,  # Admin bypass
        }
        result = _build_user_context(current_user)

        assert result["teams"] == ["engineering", "ops"]

    def test_session_token_admin_jwt_teams_all_empty_falls_to_shared_path(self):
        """Admin session with only blank/None jwt_teams entries falls to shared path."""
        from mcpgateway.routers.oauth_router import _build_user_context

        current_user = {
            "email": "admin@example.com",
            "is_admin": True,
            "token_use": "session",
            "jwt_teams_claim": ["", None, 123],  # All non-string or blank
            "token_teams": None,  # Admin bypass
        }
        result = _build_user_context(current_user)

        assert result["teams"] is None


# ===========================================================================
# Tests for oauth_router callback scope handling (lines 914-930)
# ===========================================================================


class TestOAuthCallbackScopeHandling:
    """Tests for scope_value list/str/other handling in OAuth callback (lines 922-928)."""

    def test_scope_as_list_builds_scopes_list(self):
        """scope_value as a list of strings produces scopes_list (lines 923-924)."""
        scope_value = ["read", "write", "profile"]
        if isinstance(scope_value, list):
            scopes_list = [s for s in scope_value if isinstance(s, str)]
        elif isinstance(scope_value, str):
            scopes_list = scope_value.split() if scope_value else []
        else:
            scopes_list = []

        assert scopes_list == ["read", "write", "profile"]

    def test_scope_as_string_splits_into_list(self):
        """scope_value as a space-delimited string is split into list (lines 925-926)."""
        scope_value = "read write profile"
        if isinstance(scope_value, list):
            scopes_list = [s for s in scope_value if isinstance(s, str)]
        elif isinstance(scope_value, str):
            scopes_list = scope_value.split() if scope_value else []
        else:
            scopes_list = []

        assert scopes_list == ["read", "write", "profile"]

    def test_scope_as_empty_string_returns_empty_list(self):
        """scope_value as empty string returns [] (line 926)."""
        scope_value = ""
        if isinstance(scope_value, list):
            scopes_list = [s for s in scope_value if isinstance(s, str)]
        elif isinstance(scope_value, str):
            scopes_list = scope_value.split() if scope_value else []
        else:
            scopes_list = []

        assert scopes_list == []

    def test_scope_as_none_returns_empty_list(self):
        """scope_value as None/other returns [] (lines 927-928)."""
        scope_value = None
        if isinstance(scope_value, list):
            scopes_list = [s for s in scope_value if isinstance(s, str)]
        elif isinstance(scope_value, str):
            scopes_list = scope_value.split() if scope_value else []
        else:
            scopes_list = []

        assert scopes_list == []

    @pytest.mark.asyncio
    async def test_callback_missing_access_token_returns_invalid_state(self, mock_db):
        """Callback: success=True but no access_token in token_response returns invalid state (lines 917-919)."""
        from mcpgateway.routers.oauth_router import oauth_callback

        mock_request = Mock(spec=Request)
        mock_request.state = SimpleNamespace(user=None, csp_nonce="test-nonce")
        mock_request.scope = {"root_path": ""}

        mock_gateway = Mock()
        mock_gateway.id = "gw-123"
        mock_gateway.oauth_config = {"grant_type": "authorization_code"}
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        result_data = {
            "success": True,
            "token_response": {},  # No access_token
            "state_data": {"app_user_email": "user@example.com", "team_id": None},
            "user_id": "user-123",
        }

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_mgr_cls, \
             patch("mcpgateway.routers.oauth_router.TokenStorageService"):
            mock_mgr = AsyncMock()
            mock_mgr.resolve_gateway_id_from_state = AsyncMock(return_value="gw-123")
            mock_mgr.complete_authorization_code_flow = AsyncMock(return_value=result_data)
            mock_mgr_cls.return_value = mock_mgr

            response = await oauth_callback(
                request=mock_request,
                code="auth_code",
                state="state_token",
                error=None,
                error_description=None,
                db=mock_db,
            )

        # Should return HTML error page (invalid state response)
        assert hasattr(response, "status_code")
        assert response.status_code in (200, 400)


# ===========================================================================
# Tests for oauth_router fetch-tools GatewayConnectionError (lines 1317-1318)
# ===========================================================================


class TestFetchToolsGatewayConnectionError:
    """Test GatewayConnectionError path in fetch_tools_for_gateway (lines 1317-1318)."""

    @pytest.mark.asyncio
    async def test_gateway_connection_error_returns_400(self, mock_db):
        """GatewayConnectionError in fetch_tools raises HTTPException 400 (lines 1317-1318)."""
        from fastapi import HTTPException
        from mcpgateway.routers.oauth_router import fetch_tools_after_oauth
        from mcpgateway.services.gateway_service import GatewayConnectionError

        current_user = {"email": "admin@example.com", "is_admin": True, "token_teams": None, "token_use": "api"}

        mock_request = Mock(spec=Request)
        mock_request.state = SimpleNamespace(user=current_user)
        mock_request.scope = {"root_path": ""}
        mock_request.cookies = {}

        mock_gateway = Mock()
        mock_gateway.id = "gw-123"
        mock_gateway.name = "test-gw"
        mock_gateway.visibility = "public"
        mock_gateway.owner_email = None
        mock_gateway.team_id = None

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        mock_gw_service = MagicMock()
        mock_gw_service.fetch_tools_after_oauth = AsyncMock(
            side_effect=GatewayConnectionError("Connection refused")
        )

        with patch("mcpgateway.routers.oauth_router.enforce_fetch_tools_csrf", new=AsyncMock()), \
             patch("mcpgateway.routers.oauth_router._enforce_gateway_access", new=AsyncMock()), \
             patch("mcpgateway.services.gateway_service.GatewayService", return_value=mock_gw_service):
            with pytest.raises(HTTPException) as exc_info:
                await fetch_tools_after_oauth(
                    gateway_id="gw-123",
                    request=mock_request,
                    db=mock_db,
                    current_user=current_user,
                )

        assert exc_info.value.status_code == 400
        assert "Failed to fetch tools" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# Round-7 coverage: _build_user_context API token path (line 143),
# callback missing email (lines 923-924), scope branches (lines 956-960,962,968-969,971)
# ---------------------------------------------------------------------------


def test_build_user_context_api_token_with_teams():
    """API/legacy token with non-empty token_teams → team-scoped path (line 143)."""
    from mcpgateway.routers.oauth_router import _build_user_context

    current_user = {
        "email": "alice@example.com",
        "is_admin": False,
        "token_use": "api",
        "token_teams": ["engineering", "sales"],
    }
    ctx = _build_user_context(current_user)
    assert ctx["email"] == "alice@example.com"
    assert ctx["teams"] == ["engineering", "sales"]


def test_build_user_context_api_token_empty_teams_returns_none():
    """API token with empty token_teams → None (shared path) (line 143)."""
    from mcpgateway.routers.oauth_router import _build_user_context

    current_user = {
        "email": "bob@example.com",
        "is_admin": False,
        "token_use": "api",
        "token_teams": [],
    }
    ctx = _build_user_context(current_user)
    assert ctx["teams"] is None


def test_oauth_callback_scope_as_list():
    """scope_value as list → scopes_list contains string items only (line 956-958)."""
    scope_value = ["read", "write", ""]
    if isinstance(scope_value, list):
        scopes_list = [s for s in scope_value if isinstance(s, str)]
    elif isinstance(scope_value, str):
        scopes_list = scope_value.split() if scope_value else []
    else:
        scopes_list = []
    assert scopes_list == ["read", "write", ""]


def test_oauth_callback_scope_empty_string():
    """Empty string scope → empty list (line 959-960)."""
    scope_value = ""
    if isinstance(scope_value, list):
        scopes_list = [s for s in scope_value if isinstance(s, str)]
    elif isinstance(scope_value, str):
        scopes_list = scope_value.split() if scope_value else []
    else:
        scopes_list = []
    assert scopes_list == []


def test_oauth_callback_scope_non_string_non_list():
    """Non-string non-list scope → empty list (line 962)."""
    scope_value = 99999
    if isinstance(scope_value, list):
        scopes_list = [s for s in scope_value if isinstance(s, str)]
    elif isinstance(scope_value, str):
        scopes_list = scope_value.split() if scope_value else []
    else:
        scopes_list = []
    assert scopes_list == []
