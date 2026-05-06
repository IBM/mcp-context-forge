# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_proxy_auth.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for proxy authentication functionality.

Tests the new MCP_CLIENT_AUTH_ENABLED and proxy authentication features.
"""

# Standard
from unittest.mock import AsyncMock, Mock, patch

# Third-Party
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
import pytest

# First-Party
from mcpgateway.utils import verify_credentials as vc

TEST_JWT_SECRET = "test-jwt-secret-key-with-minimum-32-bytes"


class TestProxyAuthentication:
    """Test cases for proxy authentication functionality."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings for testing."""

        class MockSettings:
            jwt_secret_key = TEST_JWT_SECRET
            jwt_algorithm = "HS256"
            basic_auth_user = "admin"
            basic_auth_password = "password"
            auth_required = True
            allow_unauthenticated_admin = False
            mcp_client_auth_enabled = True
            trust_proxy_auth = False
            trust_proxy_auth_dangerously = False
            proxy_user_header = "X-Authenticated-User"
            require_token_expiration = False
            docs_allow_basic_auth = False
            require_user_in_db = True
            platform_admin_email = "admin@example.com"

        return MockSettings()

    @pytest.fixture
    def mock_request(self):
        """Create a mock request object."""
        request = Mock(spec=Request)
        request.headers = {}
        request.cookies = {}  # Empty cookies dict, not Mock
        return request

    @pytest.mark.asyncio
    async def test_standard_jwt_auth_enabled(self, mock_settings, mock_request):
        """Test standard JWT authentication when MCP client auth is enabled."""
        mock_settings.mcp_client_auth_enabled = True
        mock_settings.auth_required = True

        with patch.object(vc, "settings", mock_settings):
            # Test with no credentials should raise exception
            with pytest.raises(HTTPException) as exc_info:
                await vc.require_auth(mock_request, None, None)
            assert exc_info.value.status_code == 401
            assert exc_info.value.detail == "Not authenticated"

    @pytest.mark.asyncio
    async def test_proxy_auth_disabled_without_trust_raises_when_auth_required(self, mock_settings, mock_request):
        """Test that disabling MCP client auth without trust raises 401 when auth_required."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = False
        mock_settings.auth_required = True

        with patch.object(vc, "settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await vc.require_auth(mock_request, None, None)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_proxy_auth_disabled_without_trust_returns_anonymous(self, mock_settings, mock_request):
        """Test that disabling MCP client auth without trust returns anonymous when auth not required."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = False
        mock_settings.auth_required = False

        with patch.object(vc, "settings", mock_settings):
            result = await vc.require_auth(mock_request, None, None)
            assert result == "anonymous"

    @pytest.mark.asyncio
    async def test_proxy_auth_requires_explicit_dangerous_ack(self, mock_settings, mock_request):
        """Proxy trust mode must be explicitly acknowledged when MCP auth is disabled."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.trust_proxy_auth_dangerously = False
        mock_settings.auth_required = True
        mock_request.headers = {"X-Authenticated-User": "proxy-user"}

        with patch.object(vc, "settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await vc.require_auth(mock_request, None, None)
            assert exc_info.value.status_code == 401
            assert "no auth method configured" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_proxy_auth_with_header(self, mock_settings, mock_request):
        """Test proxy authentication with user header."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.trust_proxy_auth_dangerously = True
        mock_request.headers = {"X-Authenticated-User": "proxy-user"}
        mock_request.state = Mock()

        # Mock database user lookup
        mock_user = Mock()
        mock_user.is_admin = False
        mock_user.email = "proxy-user"

        with patch.object(vc, "settings", mock_settings):
            with patch("mcpgateway.db.get_db") as mock_get_db:
                with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service:
                    with patch("mcpgateway.auth._resolve_teams_from_db", new_callable=AsyncMock) as mock_resolve_teams:
                        # Setup mocks
                        mock_db = Mock()
                        mock_get_db.return_value = iter([mock_db])
                        mock_auth_service.return_value.get_user_by_email = AsyncMock(return_value=mock_user)
                        mock_resolve_teams.return_value = ["team1"]

                        result = await vc.require_auth(mock_request, None, None)

                        assert result["sub"] == "proxy-user"
                        assert result["source"] == "proxy"
                        assert result["token"] is None
                        assert result["is_admin"] is False
                        assert result["teams"] == ["team1"]
                        assert result["email"] == "proxy-user"

    @pytest.mark.asyncio
    async def test_proxy_auth_without_header_raises_when_auth_required(self, mock_settings, mock_request):
        """Test proxy authentication without user header raises 401 when auth_required."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.trust_proxy_auth_dangerously = True
        mock_settings.auth_required = True
        mock_request.headers = {}  # No proxy header

        with patch.object(vc, "settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await vc.require_auth(mock_request, None, None)
            assert exc_info.value.status_code == 401
            assert "Proxy authentication header required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_proxy_auth_without_header_returns_anonymous(self, mock_settings, mock_request):
        """Test proxy authentication without user header returns anonymous when auth not required."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.trust_proxy_auth_dangerously = True
        mock_settings.auth_required = False
        mock_request.headers = {}  # No proxy header

        with patch.object(vc, "settings", mock_settings):
            result = await vc.require_auth(mock_request, None, None)
            assert result == "anonymous"

    @pytest.mark.asyncio
    async def test_custom_proxy_header(self, mock_settings, mock_request):
        """Test proxy authentication with custom header name."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.trust_proxy_auth_dangerously = True
        mock_settings.proxy_user_header = "X-Remote-User"
        mock_request.headers = {"X-Remote-User": "custom-user"}
        mock_request.state = Mock()

        # Mock database user lookup
        mock_user = Mock()
        mock_user.is_admin = False
        mock_user.email = "custom-user"

        with patch.object(vc, "settings", mock_settings):
            with patch("mcpgateway.db.get_db") as mock_get_db:
                with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service:
                    with patch("mcpgateway.auth._resolve_teams_from_db", new_callable=AsyncMock) as mock_resolve_teams:
                        # Setup mocks
                        mock_db = Mock()
                        mock_get_db.return_value = iter([mock_db])
                        mock_auth_service.return_value.get_user_by_email = AsyncMock(return_value=mock_user)
                        mock_resolve_teams.return_value = ["team1"]

                        result = await vc.require_auth(mock_request, None, None)

                        assert result["sub"] == "custom-user"
                        assert result["source"] == "proxy"
                        assert result["token"] is None
                        assert result["is_admin"] is False
                        assert result["teams"] == ["team1"]
                        assert result["email"] == "custom-user"

    @pytest.mark.asyncio
    async def test_mcp_client_auth_mode_skips_proxy_path(self, mock_settings, mock_request):
        """With mcp_client_auth_enabled=True the proxy branch is skipped; anonymous returned when auth_required=False."""
        mock_settings.mcp_client_auth_enabled = True
        mock_settings.trust_proxy_auth = True
        mock_settings.auth_required = False  # Allow anonymous

        # mcp_client_auth_enabled=True routes through the standard JWT flow even
        # when proxy trust is configured; with no token and auth optional, we
        # expect "anonymous" (not a proxy payload).
        with patch.object(vc, "settings", mock_settings):
            result = await vc.require_auth(mock_request, None, None)
            assert result == "anonymous"

    @pytest.mark.asyncio
    async def test_backwards_compatibility(self, mock_settings, mock_request):
        """Test that existing AUTH_REQUIRED behavior is preserved."""
        mock_settings.mcp_client_auth_enabled = True  # Default
        mock_settings.auth_required = False

        with patch.object(vc, "settings", mock_settings):
            # Should return anonymous when auth not required
            result = await vc.require_auth(mock_request, None, None)
            assert result == "anonymous"

    @pytest.mark.asyncio
    async def test_mixed_auth_scenario(self, mock_settings, mock_request):
        """Test scenario with both proxy header and JWT token."""
        # Third-Party
        import jwt

        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.trust_proxy_auth_dangerously = True
        mock_request.headers = {"X-Authenticated-User": "proxy-user"}
        mock_request.state = Mock()

        # Create a valid JWT token
        token = jwt.encode({"sub": "jwt-user"}, mock_settings.jwt_secret_key, algorithm="HS256")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        # Mock database user lookup
        mock_user = Mock()
        mock_user.is_admin = False
        mock_user.email = "proxy-user"

        with patch.object(vc, "settings", mock_settings):
            with patch("mcpgateway.db.get_db") as mock_get_db:
                with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service:
                    with patch("mcpgateway.auth._resolve_teams_from_db", new_callable=AsyncMock) as mock_resolve_teams:
                        # Setup mocks
                        mock_db = Mock()
                        mock_get_db.return_value = iter([mock_db])
                        mock_auth_service.return_value.get_user_by_email = AsyncMock(return_value=mock_user)
                        mock_resolve_teams.return_value = ["team1"]

                        # When MCP client auth is disabled, proxy takes precedence
                        result = await vc.require_auth(mock_request, creds, None)

                        assert result["sub"] == "proxy-user"
                        assert result["source"] == "proxy"
                        assert result["token"] is None
                        assert result["is_admin"] is False
                        assert result["teams"] == ["team1"]
                        assert result["email"] == "proxy-user"

    @pytest.mark.asyncio
    async def test_proxy_auth_platform_admin_bootstrap(self, mock_settings, mock_request):
        """Test proxy authentication with platform admin bootstrap when user not in DB."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.trust_proxy_auth_dangerously = True
        mock_settings.require_user_in_db = False
        mock_settings.platform_admin_email = "admin@example.com"
        mock_request.headers = {"X-Authenticated-User": "admin@example.com"}
        mock_request.state = Mock()

        with patch.object(vc, "settings", mock_settings):
            with patch("mcpgateway.db.get_db") as mock_get_db:
                with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service:
                    # Setup mocks - user NOT found in DB
                    mock_db = Mock()
                    mock_get_db.return_value = iter([mock_db])
                    mock_auth_service.return_value.get_user_by_email = AsyncMock(return_value=None)

                    result = await vc.require_auth(mock_request, None, None)

                    # Should bootstrap platform admin
                    assert result["sub"] == "admin@example.com"
                    assert result["source"] == "proxy"
                    assert result["token"] is None
                    assert result["is_admin"] is True
                    assert result["teams"] is None  # Admin bypass
                    assert result["email"] == "admin@example.com"

    @pytest.mark.asyncio
    async def test_proxy_auth_user_not_found_raises_401(self, mock_settings, mock_request):
        """Test proxy authentication raises 401 when user not in DB and not platform admin."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.trust_proxy_auth_dangerously = True
        mock_settings.require_user_in_db = True
        mock_settings.platform_admin_email = "admin@example.com"
        mock_request.headers = {"X-Authenticated-User": "unknown-user@example.com"}
        mock_request.state = Mock()

        with patch.object(vc, "settings", mock_settings):
            with patch("mcpgateway.db.get_db") as mock_get_db:
                with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service:
                    # Setup mocks - user NOT found in DB
                    mock_db = Mock()
                    mock_get_db.return_value = iter([mock_db])
                    mock_auth_service.return_value.get_user_by_email = AsyncMock(return_value=None)

                    with pytest.raises(HTTPException) as exc_info:
                        await vc.require_auth(mock_request, None, None)

                    assert exc_info.value.status_code == 401
                    assert "User not found in database" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_proxy_auth_admin_user_in_db_yields_admin_bypass(self, mock_settings, mock_request):
        """Admin user found in DB gets is_admin=True and teams=None (admin bypass)."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.trust_proxy_auth_dangerously = True
        mock_request.headers = {"X-Authenticated-User": "admin-user@example.com"}
        mock_request.state = Mock()

        mock_user = Mock()
        mock_user.is_admin = True
        mock_user.email = "admin-user@example.com"

        with (
            patch.object(vc, "settings", mock_settings),
            patch("mcpgateway.db.get_db") as mock_get_db,
            patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service,
            patch("mcpgateway.auth._resolve_teams_from_db", new_callable=AsyncMock) as mock_resolve_teams,
        ):
            mock_get_db.return_value = iter([Mock()])
            mock_auth_service.return_value.get_user_by_email = AsyncMock(return_value=mock_user)
            # _resolve_teams_from_db returns None for admins (admin bypass)
            mock_resolve_teams.return_value = None

            result = await vc.require_auth(mock_request, None, None)

        assert result["sub"] == "admin-user@example.com"
        assert result["is_admin"] is True
        assert result["teams"] is None
        assert result["source"] == "proxy"

    @pytest.mark.asyncio
    async def test_proxy_auth_multiple_teams(self, mock_settings, mock_request):
        """Non-admin user with multiple team memberships returns the full list."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.trust_proxy_auth_dangerously = True
        mock_request.headers = {"X-Authenticated-User": "multi-team-user@example.com"}
        mock_request.state = Mock()

        mock_user = Mock()
        mock_user.is_admin = False
        mock_user.email = "multi-team-user@example.com"

        with (
            patch.object(vc, "settings", mock_settings),
            patch("mcpgateway.db.get_db") as mock_get_db,
            patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service,
            patch("mcpgateway.auth._resolve_teams_from_db", new_callable=AsyncMock) as mock_resolve_teams,
        ):
            mock_get_db.return_value = iter([Mock()])
            mock_auth_service.return_value.get_user_by_email = AsyncMock(return_value=mock_user)
            mock_resolve_teams.return_value = ["team-a", "team-b", "team-c"]

            result = await vc.require_auth(mock_request, None, None)

        assert result["is_admin"] is False
        assert result["teams"] == ["team-a", "team-b", "team-c"]

    @pytest.mark.asyncio
    async def test_require_auth_header_first_proxy_returns_enriched_payload(self, mock_settings, mock_request):
        """Parity test: require_auth_header_first returns the enriched payload (same helper)."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.trust_proxy_auth_dangerously = True
        mock_request.headers = {"X-Authenticated-User": "mcp-user@example.com"}
        mock_request.cookies = {}
        mock_request.state = Mock()

        mock_user = Mock()
        mock_user.is_admin = False
        mock_user.email = "mcp-user@example.com"

        with (
            patch.object(vc, "settings", mock_settings),
            patch("mcpgateway.db.get_db") as mock_get_db,
            patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service,
            patch("mcpgateway.auth._resolve_teams_from_db", new_callable=AsyncMock) as mock_resolve_teams,
        ):
            mock_get_db.return_value = iter([Mock()])
            mock_auth_service.return_value.get_user_by_email = AsyncMock(return_value=mock_user)
            mock_resolve_teams.return_value = ["team1"]

            result = await vc.require_auth_header_first(auth_header=None, jwt_token=None, request=mock_request)

        # Same enriched shape as require_auth (both go through _authenticate_proxy_user)
        assert result["sub"] == "mcp-user@example.com"
        assert result["source"] == "proxy"
        assert result["token"] is None
        assert result["is_admin"] is False
        assert result["teams"] == ["team1"]
        assert result["email"] == "mcp-user@example.com"

    @pytest.mark.asyncio
    async def test_require_auth_header_first_proxy_admin_bootstrap(self, mock_settings, mock_request):
        """Parity test: require_auth_header_first supports platform-admin bootstrap."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.trust_proxy_auth_dangerously = True
        mock_settings.require_user_in_db = False
        mock_settings.platform_admin_email = "admin@example.com"
        mock_request.headers = {"X-Authenticated-User": "admin@example.com"}
        mock_request.cookies = {}
        mock_request.state = Mock()

        with patch.object(vc, "settings", mock_settings), patch("mcpgateway.db.get_db") as mock_get_db, patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service:
            mock_get_db.return_value = iter([Mock()])
            mock_auth_service.return_value.get_user_by_email = AsyncMock(return_value=None)

            result = await vc.require_auth_header_first(auth_header=None, jwt_token=None, request=mock_request)

        assert result["is_admin"] is True
        assert result["teams"] is None

    @pytest.mark.asyncio
    async def test_proxy_auth_disabled_user_raises_401(self, mock_settings, mock_request):
        """Disabled users must NOT authenticate via proxy (matches JWT _enforce_revocation_and_active_user)."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.trust_proxy_auth_dangerously = True
        mock_request.headers = {"X-Authenticated-User": "disabled-user@example.com"}
        mock_request.state = Mock()

        disabled_user = Mock()
        disabled_user.is_admin = False
        disabled_user.is_active = False  # Account disabled
        disabled_user.email = "disabled-user@example.com"

        with patch.object(vc, "settings", mock_settings), patch("mcpgateway.db.get_db") as mock_get_db, patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service:
            mock_get_db.return_value = iter([Mock()])
            mock_auth_service.return_value.get_user_by_email = AsyncMock(return_value=disabled_user)

            with pytest.raises(HTTPException) as exc_info:
                await vc.require_auth(mock_request, None, None)

        assert exc_info.value.status_code == 401
        assert "Account disabled" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_proxy_auth_disabled_admin_raises_401(self, mock_settings, mock_request):
        """Disabled admins must NOT authenticate via proxy even though is_admin=True on the record."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.trust_proxy_auth_dangerously = True
        mock_request.headers = {"X-Authenticated-User": "disabled-admin@example.com"}
        mock_request.state = Mock()

        disabled_admin = Mock()
        disabled_admin.is_admin = True
        disabled_admin.is_active = False  # Even disabled admins must be rejected
        disabled_admin.email = "disabled-admin@example.com"

        with patch.object(vc, "settings", mock_settings), patch("mcpgateway.db.get_db") as mock_get_db, patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service:
            mock_get_db.return_value = iter([Mock()])
            mock_auth_service.return_value.get_user_by_email = AsyncMock(return_value=disabled_admin)

            with pytest.raises(HTTPException) as exc_info:
                await vc.require_auth(mock_request, None, None)

        assert exc_info.value.status_code == 401
        assert "Account disabled" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_proxy_auth_payload_has_token_use_session(self, mock_settings, mock_request):
        """Proxy payload sets token_use='session' so downstream dispatchers use DB-backed team resolution."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.trust_proxy_auth_dangerously = True
        mock_request.headers = {"X-Authenticated-User": "user@example.com"}
        mock_request.state = Mock()

        mock_user = Mock()
        mock_user.is_admin = False
        mock_user.is_active = True
        mock_user.email = "user@example.com"

        with (
            patch.object(vc, "settings", mock_settings),
            patch("mcpgateway.db.get_db") as mock_get_db,
            patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service,
            patch("mcpgateway.auth._resolve_teams_from_db", new_callable=AsyncMock) as mock_resolve_teams,
        ):
            mock_get_db.return_value = iter([Mock()])
            mock_auth_service.return_value.get_user_by_email = AsyncMock(return_value=mock_user)
            mock_resolve_teams.return_value = ["team1"]

            result = await vc.require_auth(mock_request, None, None)

        # token_use: "session" routes main.py:2870 and streamablehttp_transport.py:1998 dispatchers
        # to resolve_session_teams (DB-backed) rather than normalize_token_teams (embedded teams).
        assert result["token_use"] == "session"


class TestRBACProxyAuthentication:
    """Test cases for RBAC middleware proxy authentication functionality."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings for testing."""

        class MockSettings:
            jwt_secret_key = TEST_JWT_SECRET
            jwt_algorithm = "HS256"
            basic_auth_user = "admin"
            basic_auth_password = "password"
            auth_required = False
            allow_unauthenticated_admin = False
            mcp_client_auth_enabled = False
            trust_proxy_auth = True
            trust_proxy_auth_dangerously = True
            proxy_user_header = "X-Authenticated-User"
            require_token_expiration = False
            docs_allow_basic_auth = False
            platform_admin_email = "admin@example.com"
            app_root_path = ""

        return MockSettings()

    @pytest.fixture
    def mock_request(self):
        """Create a mock request object."""
        request = Mock(spec=Request)
        request.headers = {}
        request.cookies = {}
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.state = Mock()
        request.state.request_id = "test-request-id"
        request.state.team_id = None
        return request

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return Mock()

    @pytest.mark.asyncio
    async def test_rbac_proxy_auth_with_header(self, mock_settings, mock_request, mock_db):
        """Test RBAC middleware accepts proxy authentication with header."""
        # First-Party
        from mcpgateway.middleware import rbac

        mock_request.headers = {"X-Authenticated-User": "proxy-user"}

        # Mock the database query to return None (user not found in DB)
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch.object(rbac, "settings", mock_settings):
            with patch("mcpgateway.middleware.rbac.fresh_db_session") as mock_fresh_db:
                mock_fresh_db.return_value.__enter__.return_value = mock_db
                result = await rbac.get_current_user_with_permissions(mock_request, None, None)
                assert result["email"] == "proxy-user"
                assert result["auth_method"] == "proxy"
                assert result["is_admin"] is False
                # Verify plugin context fields are included for cross-hook sharing
                assert "plugin_context_table" in result
                assert "plugin_global_context" in result

    @pytest.mark.asyncio
    async def test_rbac_proxy_auth_without_header(self, mock_settings, mock_request, mock_db):
        """Test RBAC middleware returns anonymous when no proxy header."""
        # First-Party
        from mcpgateway.middleware import rbac

        mock_request.headers = {}

        with patch.object(rbac, "settings", mock_settings):
            result = await rbac.get_current_user_with_permissions(mock_request, None, None)
            assert result["email"] == "anonymous"
            assert result["auth_method"] == "anonymous"
            assert result["is_admin"] is False

    @pytest.mark.asyncio
    async def test_rbac_proxy_auth_disabled_without_trust(self, mock_settings, mock_request, mock_db):
        """Test RBAC middleware returns anonymous when proxy auth not trusted."""
        # First-Party
        from mcpgateway.middleware import rbac

        mock_settings.trust_proxy_auth = False
        mock_request.headers = {"X-Authenticated-User": "proxy-user"}

        with patch.object(rbac, "settings", mock_settings):
            result = await rbac.get_current_user_with_permissions(mock_request, None, None)
            assert result["email"] == "anonymous"
            assert result["auth_method"] == "anonymous"

    @pytest.mark.asyncio
    async def test_rbac_standard_jwt_when_mcp_auth_enabled(self, mock_settings, mock_request, mock_db):
        """Test RBAC middleware uses JWT when MCP client auth is enabled."""
        # First-Party
        from mcpgateway.middleware import rbac

        mock_settings.mcp_client_auth_enabled = True
        mock_settings.auth_required = False
        mock_request.headers = {"X-Authenticated-User": "proxy-user"}

        with patch.object(rbac, "settings", mock_settings):
            # Should ignore proxy header and use JWT flow (auth disabled -> anonymous by default)
            result = await rbac.get_current_user_with_permissions(mock_request, None, None)
            assert result["email"] == "anonymous"
            assert result["auth_method"] == "anonymous"

    @pytest.mark.asyncio
    async def test_rbac_proxy_auth_preserves_plugin_context(self, mock_settings, mock_request, mock_db):
        """Test RBAC middleware preserves plugin context for cross-hook sharing."""
        # First-Party
        from mcpgateway.middleware import rbac

        mock_request.headers = {"X-Authenticated-User": "proxy-user"}
        # Simulate plugin context set by HttpAuthMiddleware
        mock_request.state.plugin_context_table = {"test_plugin": {"key": "value"}}
        mock_request.state.plugin_global_context = Mock()

        with patch.object(rbac, "settings", mock_settings):
            with patch("mcpgateway.middleware.rbac.fresh_db_session") as mock_fresh_db:
                mock_fresh_db.return_value.__enter__.return_value = mock_db
                result = await rbac.get_current_user_with_permissions(mock_request, None, None)
                # Verify plugin contexts are passed through for HTTP_AUTH_CHECK_PERMISSION hooks
                assert result["plugin_context_table"] == {"test_plugin": {"key": "value"}}
                assert result["plugin_global_context"] is not None

    @pytest.mark.asyncio
    async def test_rbac_proxy_auth_missing_header_returns_401_when_auth_required(self, mock_settings, mock_request, mock_db):
        """Test RBAC middleware returns 401 when proxy header missing and auth_required=true."""
        # First-Party
        from mcpgateway.middleware import rbac

        mock_settings.auth_required = True
        mock_request.headers = {}  # No proxy header

        with patch.object(rbac, "settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await rbac.get_current_user_with_permissions(mock_request, None, None)
            assert exc_info.value.status_code == 401
            assert "Proxy authentication header required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_rbac_proxy_auth_missing_header_redirects_browser_when_auth_required(self, mock_settings, mock_request, mock_db):
        """Test RBAC middleware redirects browser when proxy header missing and auth_required=true."""
        # First-Party
        from mcpgateway.middleware import rbac

        mock_settings.auth_required = True
        mock_request.headers = {"accept": "text/html"}  # Browser request, no proxy header

        with patch.object(rbac, "settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await rbac.get_current_user_with_permissions(mock_request, None, None)
            assert exc_info.value.status_code == 302
            assert "/admin/login" in exc_info.value.headers.get("Location", "")

    @pytest.mark.asyncio
    async def test_rbac_proxy_auth_looks_up_admin_status(self, mock_settings, mock_request, mock_db):
        """Test RBAC middleware looks up is_admin from database for proxy users."""
        # First-Party
        from mcpgateway.middleware import rbac

        mock_request.headers = {"X-Authenticated-User": "admin@example.com"}

        # Mock the platform_admin_email check
        mock_settings.platform_admin_email = "admin@example.com"

        with patch.object(rbac, "settings", mock_settings):
            result = await rbac.get_current_user_with_permissions(mock_request, None, None)
            assert result["email"] == "admin@example.com"
            assert result["is_admin"] is True  # Matches platform_admin_email
            assert result["auth_method"] == "proxy"


class TestWebSocketAuthentication:
    """Test cases for WebSocket authentication."""

    @pytest.mark.asyncio
    async def test_websocket_auth_required(self):
        """Test that WebSocket requires authentication when enabled."""
        # Standard
        from unittest.mock import AsyncMock

        # Third-Party
        from fastapi import WebSocket

        # Create mock WebSocket
        websocket = AsyncMock(spec=WebSocket)
        websocket.query_params = {}
        websocket.headers = {}
        websocket.close = AsyncMock()

        # Mock settings with auth required
        with patch("mcpgateway.main.settings") as mock_settings:
            mock_settings.mcp_client_auth_enabled = True
            mock_settings.auth_required = True
            mock_settings.trust_proxy_auth = False
            mock_settings.trust_proxy_auth_dangerously = False

            # Import and call the websocket_endpoint function
            # First-Party
            from mcpgateway.main import websocket_endpoint

            # Should close connection due to missing auth
            await websocket_endpoint(websocket)
            websocket.close.assert_called_once_with(code=1008, reason="Authentication required")

    @pytest.mark.asyncio
    async def test_websocket_with_authorization_header(self):
        """Test WebSocket authentication with bearer token in Authorization header."""
        # Standard
        from unittest.mock import AsyncMock

        # Third-Party
        from fastapi import WebSocket
        import jwt

        # Create mock WebSocket
        websocket = AsyncMock(spec=WebSocket)
        token = jwt.encode({"sub": "test-user"}, TEST_JWT_SECRET, algorithm="HS256")
        websocket.query_params = {}
        websocket.headers = {"authorization": f"Bearer {token}"}
        websocket.accept = AsyncMock()
        websocket.receive_text = AsyncMock(side_effect=Exception("Test complete"))

        # Mock settings
        with patch("mcpgateway.main.settings") as mock_settings:
            mock_settings.mcp_client_auth_enabled = True
            mock_settings.auth_required = True
            mock_settings.mcpgateway_ws_relay_enabled = True
            mock_settings.port = 8000
            mock_settings.trust_proxy_auth_dangerously = False

            # Mock websocket auth helper to succeed
            with patch("mcpgateway.main._authenticate_websocket_user", new=AsyncMock(return_value=(token, None))):
                # First-Party
                from mcpgateway.main import websocket_endpoint

                try:
                    await websocket_endpoint(websocket)
                except Exception as e:
                    if str(e) != "Test complete":
                        raise

                # Should accept connection
                websocket.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_with_proxy_auth(self):
        """Test WebSocket authentication with proxy headers."""
        # Standard
        from unittest.mock import AsyncMock

        # Third-Party
        from fastapi import WebSocket

        # Create mock WebSocket
        websocket = AsyncMock(spec=WebSocket)
        websocket.query_params = {}
        websocket.headers = {"X-Authenticated-User": "proxy-user"}
        websocket.accept = AsyncMock()
        websocket.receive_text = AsyncMock(side_effect=Exception("Test complete"))

        # Mock settings for proxy auth
        with patch("mcpgateway.main.settings") as mock_settings:
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = True
            mock_settings.trust_proxy_auth_dangerously = True
            mock_settings.proxy_user_header = "X-Authenticated-User"
            mock_settings.auth_required = False
            mock_settings.port = 8000

            # First-Party
            from mcpgateway.main import websocket_endpoint

            try:
                await websocket_endpoint(websocket)
            except Exception as e:
                if str(e) != "Test complete":
                    raise

            # Should accept connection with proxy auth
            websocket.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_streamable_http_auth_with_proxy_header(self):
        """streamable_http_auth allows request when proxy header matches a valid active DB user."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import streamable_http_auth

        scope = {
            "type": "http",
            "path": "/servers/123/mcp",
            "headers": [(b"x-authenticated-user", b"proxy-user")],
        }

        mock_user = Mock()
        mock_user.is_admin = False
        mock_user.is_active = True
        mock_user.email = "proxy-user"

        with (
            patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings,
            patch("mcpgateway.db.get_db") as mock_get_db,
            patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service,
            patch("mcpgateway.auth._resolve_teams_from_db", new_callable=AsyncMock) as mock_resolve_teams,
        ):
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = True
            mock_settings.trust_proxy_auth_dangerously = True
            mock_settings.proxy_user_header = "X-Authenticated-User"
            mock_settings.jwt_secret_key = TEST_JWT_SECRET
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.auth_required = False
            mock_settings.require_user_in_db = True

            mock_get_db.return_value = iter([Mock()])
            mock_auth_service.return_value.get_user_by_email = AsyncMock(return_value=mock_user)
            mock_resolve_teams.return_value = []

            allowed = await streamable_http_auth(scope, AsyncMock(), AsyncMock())
            assert allowed is True

    @pytest.mark.asyncio
    async def test_streamable_http_auth_no_header_denied_when_required(self):
        """Should deny when proxy header missing and auth_required true."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import streamable_http_auth

        scope = {
            "type": "http",
            "path": "/servers/123/mcp",
            "headers": [],
        }
        with (
            patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings,
            patch("mcpgateway.transports.streamablehttp_transport._check_server_oauth_enforcement", new_callable=AsyncMock, return_value=None),
        ):
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = True
            mock_settings.trust_proxy_auth_dangerously = True
            mock_settings.proxy_user_header = "X-Authenticated-User"
            mock_settings.jwt_secret_key = TEST_JWT_SECRET
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.auth_required = True
            send = AsyncMock()
            ok = await streamable_http_auth(scope, AsyncMock(), send)
            # When denied, function returns False and send called with 401 response
            assert ok is False
            assert any(isinstance(call.args[0], dict) and call.args[0].get("status") == 401 for call in send.mock_calls)
