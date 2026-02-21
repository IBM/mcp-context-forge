# -*- coding: utf-8 -*-
"""Unit tests for LDAP Auth router - LDAP bind login, status, and sync endpoints."""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException, status
import pytest

# First-Party
from mcpgateway.db import EmailUser
from mcpgateway.schemas import LdapLoginRequest, LdapStatusResponse, LdapSyncResponse
from mcpgateway.services.ldap_service import LdapConnectionError, LdapService, LdapUserEntry, SyncResult


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def mock_user():
    """Create a mock EmailUser for LDAP authentication."""
    user = MagicMock(spec=EmailUser)
    user.email = "alice@example.org"
    user.full_name = "Alice Liddell"
    user.is_admin = False
    user.is_active = True
    user.auth_provider = "ldap"
    user.password_change_required = False
    user.created_at = datetime.now(tz=timezone.utc)
    user.updated_at = datetime.now(tz=timezone.utc)
    user.last_login = None
    user.email_verified_at = None
    user.team_memberships = []
    user.get_teams = MagicMock(return_value=[])
    user.is_account_locked = MagicMock(return_value=False)
    user.reset_failed_attempts = MagicMock()
    user.increment_failed_attempts = MagicMock(return_value=False)
    return user


@pytest.fixture
def mock_admin_user():
    """Create a mock admin EmailUser for LDAP status/sync endpoints."""
    user = MagicMock(spec=EmailUser)
    user.email = "admin@example.org"
    user.full_name = "Admin User"
    user.is_admin = True
    user.is_active = True
    user.auth_provider = "ldap"
    return user


@pytest.fixture
def mock_request():
    """Create a mock FastAPI request."""
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {"User-Agent": "TestAgent/1.0"}
    return request


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = MagicMock()
    return db


@pytest.fixture
def mock_ldap_entry():
    """Create a mock LDAP user entry."""
    return LdapUserEntry(
        dn="uid=alice,ou=Users,dc=example,dc=org",
        uid="alice",
        email="alice@example.org",
        full_name="Alice Liddell",
        groups=["cn=data-science,ou=Groups,dc=example,dc=org"],
    )


# ── Login Endpoint ──────────────────────────────────────────────────


class TestLdapLogin:
    """Test LDAP login endpoint."""

    @pytest.mark.asyncio
    async def test_login_success(self, mock_user, mock_request, mock_db, mock_ldap_entry):
        """Test successful LDAP bind login returns JWT."""
        # First-Party
        from mcpgateway.routers.ldap_auth import ldap_login

        login_request = LdapLoginRequest(username="alice", password="password")

        with patch("mcpgateway.routers.ldap_auth.LdapService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.authenticate.return_value = mock_ldap_entry
            mock_svc.get_or_create_user = AsyncMock(return_value=mock_user)

            with patch("mcpgateway.routers.email_auth.create_access_token", new_callable=AsyncMock, return_value=("jwt-token-here", 604800)):
                with patch("mcpgateway.db.EmailAuthEvent"):
                    with patch("mcpgateway.routers.ldap_auth.EmailUserResponse") as mock_resp:
                        mock_resp.from_email_user.return_value = MagicMock(
                            email="alice@example.org",
                            full_name="Alice Liddell",
                            is_admin=False,
                            is_active=True,
                            auth_provider="ldap",
                        )
                        result = await ldap_login(login_request, mock_request, mock_db)

        assert result.access_token == "jwt-token-here"
        assert result.token_type == "bearer"
        assert result.expires_in == 604800

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, mock_request, mock_db):
        """Test login with invalid LDAP credentials returns 401."""
        # First-Party
        from mcpgateway.routers.ldap_auth import ldap_login

        login_request = LdapLoginRequest(username="alice", password="wrong")

        with patch("mcpgateway.routers.ldap_auth.LdapService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.authenticate.return_value = None  # Auth failed

            with pytest.raises(HTTPException) as exc_info:
                await ldap_login(login_request, mock_request, mock_db)

        assert exc_info.value.status_code == 401
        assert "Invalid LDAP credentials" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_login_server_unreachable(self, mock_request, mock_db):
        """Test login when LDAP server is unreachable returns 503."""
        # First-Party
        from mcpgateway.routers.ldap_auth import ldap_login

        login_request = LdapLoginRequest(username="alice", password="password")

        with patch("mcpgateway.routers.ldap_auth.LdapService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.authenticate.side_effect = LdapConnectionError("Connection refused")

            with pytest.raises(HTTPException) as exc_info:
                await ldap_login(login_request, mock_request, mock_db)

        assert exc_info.value.status_code == 503
        assert "LDAP server is unreachable" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_login_auto_provision_disabled(self, mock_request, mock_db, mock_ldap_entry):
        """Test login when user auto-provisioning is disabled returns 403."""
        # First-Party
        from mcpgateway.routers.ldap_auth import ldap_login

        login_request = LdapLoginRequest(username="alice", password="password")

        with patch("mcpgateway.routers.ldap_auth.LdapService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.authenticate.return_value = mock_ldap_entry
            mock_svc.get_or_create_user = AsyncMock(return_value=None)  # Auto-create disabled

            with pytest.raises(HTTPException) as exc_info:
                await ldap_login(login_request, mock_request, mock_db)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_login_locked_account(self, mock_user, mock_request, mock_db, mock_ldap_entry):
        """Test login returns 401 when account is locked."""
        # First-Party
        from mcpgateway.routers.ldap_auth import ldap_login

        mock_user.is_account_locked.return_value = True
        login_request = LdapLoginRequest(username="alice", password="password")

        with patch("mcpgateway.routers.ldap_auth.LdapService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.authenticate.return_value = mock_ldap_entry
            mock_svc.get_or_create_user = AsyncMock(return_value=mock_user)

            with pytest.raises(HTTPException) as exc_info:
                await ldap_login(login_request, mock_request, mock_db)

        assert exc_info.value.status_code == 401
        assert "locked" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_login_resets_failed_attempts(self, mock_user, mock_request, mock_db, mock_ldap_entry):
        """Test successful login resets failed login attempts."""
        # First-Party
        from mcpgateway.routers.ldap_auth import ldap_login

        login_request = LdapLoginRequest(username="alice", password="password")

        with patch("mcpgateway.routers.ldap_auth.LdapService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.authenticate.return_value = mock_ldap_entry
            mock_svc.get_or_create_user = AsyncMock(return_value=mock_user)

            with patch("mcpgateway.routers.email_auth.create_access_token", new_callable=AsyncMock, return_value=("jwt-token-here", 604800)):
                with patch("mcpgateway.db.EmailAuthEvent"):
                    with patch("mcpgateway.routers.ldap_auth.EmailUserResponse") as mock_resp:
                        mock_resp.from_email_user.return_value = MagicMock(
                            email="alice@example.org",
                            full_name="Alice Liddell",
                            is_admin=False,
                            is_active=True,
                            auth_provider="ldap",
                        )
                        await ldap_login(login_request, mock_request, mock_db)

        mock_user.reset_failed_attempts.assert_called_once()


# ── Status Endpoint ─────────────────────────────────────────────────


class TestLdapStatus:
    """Test LDAP status endpoint."""

    @pytest.mark.asyncio
    async def test_status_connected(self, mock_admin_user):
        """Test status when LDAP is connected (admin user)."""
        # First-Party
        from mcpgateway.routers.ldap_auth import ldap_status

        # Reset last_sync_at on the real class
        LdapService._last_sync_at = None

        with patch("mcpgateway.routers.ldap_auth.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db

            with patch("mcpgateway.routers.ldap_auth.LdapService") as mock_svc_cls:
                mock_svc = mock_svc_cls.return_value
                mock_svc.check_connection.return_value = (True, None)
                # Patch class attribute on the mock class
                mock_svc_cls._last_sync_at = None

                with patch("mcpgateway.routers.ldap_auth.settings") as mock_settings:
                    mock_settings.ldap_uri = "ldap://localhost:389"
                    mock_settings.ldap_base_dn = "dc=example,dc=org"
                    mock_settings.ldap_sync_enabled = True

                    result = await ldap_status(mock_admin_user)

        assert result.connected is True
        assert result.error is None
        assert result.server_uri == "ldap://localhost:389"

    @pytest.mark.asyncio
    async def test_status_disconnected(self, mock_admin_user):
        """Test status when LDAP is disconnected returns sanitized error."""
        # First-Party
        from mcpgateway.routers.ldap_auth import ldap_status

        LdapService._last_sync_at = None

        with patch("mcpgateway.routers.ldap_auth.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db

            with patch("mcpgateway.routers.ldap_auth.LdapService") as mock_svc_cls:
                mock_svc = mock_svc_cls.return_value
                mock_svc.check_connection.return_value = (False, "Connection refused to ldap://internal:389")
                mock_svc_cls._last_sync_at = None

                with patch("mcpgateway.routers.ldap_auth.settings") as mock_settings:
                    mock_settings.ldap_uri = "ldap://localhost:389"
                    mock_settings.ldap_base_dn = "dc=example,dc=org"
                    mock_settings.ldap_sync_enabled = False

                    result = await ldap_status(mock_admin_user)

        assert result.connected is False
        # Error should be sanitized - not leak internal connection details
        assert result.error == "Connection failed"

    @pytest.mark.asyncio
    async def test_status_with_last_sync(self, mock_admin_user):
        """Test status includes last sync timestamp."""
        # First-Party
        from mcpgateway.routers.ldap_auth import ldap_status

        sync_time = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        LdapService._last_sync_at = sync_time

        with patch("mcpgateway.routers.ldap_auth.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db

            with patch("mcpgateway.routers.ldap_auth.LdapService") as mock_svc_cls:
                mock_svc = mock_svc_cls.return_value
                mock_svc.check_connection.return_value = (True, None)
                mock_svc_cls._last_sync_at = sync_time

                with patch("mcpgateway.routers.ldap_auth.settings") as mock_settings:
                    mock_settings.ldap_uri = "ldap://localhost:389"
                    mock_settings.ldap_base_dn = "dc=example,dc=org"
                    mock_settings.ldap_sync_enabled = True

                    result = await ldap_status(mock_admin_user)

        assert result.last_sync_at is not None
        assert "2026-01-15" in result.last_sync_at

        # Cleanup
        LdapService._last_sync_at = None

    @pytest.mark.asyncio
    async def test_status_requires_admin(self, mock_user):
        """Test status endpoint rejects non-admin users."""
        # First-Party
        from mcpgateway.routers.ldap_auth import ldap_status

        with pytest.raises(HTTPException) as exc_info:
            await ldap_status(mock_user)

        assert exc_info.value.status_code == 403
        assert "Admin privileges required" in exc_info.value.detail


# ── Sync Endpoint ───────────────────────────────────────────────────


class TestLdapSync:
    """Test LDAP sync endpoint."""

    @pytest.mark.asyncio
    async def test_sync_success(self, mock_db):
        """Test successful directory sync trigger."""
        # First-Party
        from mcpgateway.routers.ldap_auth import ldap_sync

        admin_user = MagicMock(spec=EmailUser)
        admin_user.is_admin = True

        sync_result = SyncResult(users_synced=5, groups_synced=3)

        with patch("mcpgateway.routers.ldap_auth.LdapService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.sync_directory = AsyncMock(return_value=sync_result)

            result = await ldap_sync(admin_user, mock_db)

        assert result.users_synced == 5
        assert result.groups_synced == 3

    @pytest.mark.asyncio
    async def test_sync_requires_admin(self, mock_db):
        """Test sync endpoint rejects non-admin users."""
        # First-Party
        from mcpgateway.routers.ldap_auth import ldap_sync

        regular_user = MagicMock(spec=EmailUser)
        regular_user.is_admin = False

        with pytest.raises(HTTPException) as exc_info:
            await ldap_sync(regular_user, mock_db)

        assert exc_info.value.status_code == 403
        assert "Admin privileges required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_sync_server_unreachable(self, mock_db):
        """Test sync when LDAP server is unreachable."""
        # First-Party
        from mcpgateway.routers.ldap_auth import ldap_sync

        admin_user = MagicMock(spec=EmailUser)
        admin_user.is_admin = True

        with patch("mcpgateway.routers.ldap_auth.LdapService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.sync_directory = AsyncMock(side_effect=LdapConnectionError("down"))

            with pytest.raises(HTTPException) as exc_info:
                await ldap_sync(admin_user, mock_db)

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_sync_with_errors(self, mock_db):
        """Test sync returns partial results with errors."""
        # First-Party
        from mcpgateway.routers.ldap_auth import ldap_sync

        admin_user = MagicMock(spec=EmailUser)
        admin_user.is_admin = True

        sync_result = SyncResult(
            users_synced=3,
            groups_synced=1,
            errors=["Failed to sync user bob: timeout"],
        )

        with patch("mcpgateway.routers.ldap_auth.LdapService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.sync_directory = AsyncMock(return_value=sync_result)

            result = await ldap_sync(admin_user, mock_db)

        assert result.users_synced == 3
        assert len(result.errors) == 1


# ── Schema Validation ───────────────────────────────────────────────


class TestLdapSchemas:
    """Test LDAP request/response schemas."""

    def test_login_request_valid(self):
        """Test valid LDAP login request."""
        req = LdapLoginRequest(username="alice", password="password")
        assert req.username == "alice"

    def test_login_request_strips_whitespace(self):
        """Test that username is stripped of whitespace."""
        req = LdapLoginRequest(username="  alice  ", password="password")
        assert req.username == "alice"

    def test_login_request_empty_username_rejected(self):
        """Test that empty username is rejected."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            LdapLoginRequest(username="", password="password")

    def test_login_request_empty_password_rejected(self):
        """Test that empty password is rejected."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            LdapLoginRequest(username="alice", password="")

    def test_sync_response(self):
        """Test LdapSyncResponse schema."""
        resp = LdapSyncResponse(users_synced=5, groups_synced=3, users_removed=1, groups_removed=0)
        assert resp.users_synced == 5
        assert resp.groups_removed == 0

    def test_status_response(self):
        """Test LdapStatusResponse schema."""
        resp = LdapStatusResponse(
            connected=True,
            server_uri="ldap://localhost:389",
            base_dn="dc=example,dc=org",
            sync_enabled=True,
        )
        assert resp.connected is True
        assert resp.error is None


# ── Helper Functions ────────────────────────────────────────────────


class TestHelpers:
    """Test router helper functions."""

    def test_get_client_ip_forwarded(self):
        """Test IP extraction from X-Forwarded-For header."""
        # First-Party
        from mcpgateway.routers.ldap_auth import get_client_ip

        request = MagicMock()
        request.headers = {"X-Forwarded-For": "10.0.0.1, 192.168.1.1"}
        result = get_client_ip(request)
        assert result == "10.0.0.1"

    def test_get_client_ip_real_ip(self):
        """Test IP extraction from X-Real-IP header."""
        # First-Party
        from mcpgateway.routers.ldap_auth import get_client_ip

        request = MagicMock()
        request.headers = {"X-Real-IP": "10.0.0.1"}
        result = get_client_ip(request)
        assert result == "10.0.0.1"

    def test_get_client_ip_direct(self):
        """Test IP extraction from direct client connection."""
        # First-Party
        from mcpgateway.routers.ldap_auth import get_client_ip

        request = MagicMock()
        request.headers = {}
        request.client.host = "127.0.0.1"
        result = get_client_ip(request)
        assert result == "127.0.0.1"
