# -*- coding: utf-8 -*-
"""Unit tests for LdapService - LDAP authentication and directory sync."""

# Standard
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services.ldap_service import (
    LdapService,
    LdapConnectionError,
    LdapBindError,
    LdapSearchError,
    LdapUserEntry,
    LdapGroupEntry,
    SyncResult,
    _get_ldap3,
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    db.execute.return_value.scalars.return_value.all.return_value = []

    def mock_refresh(obj):
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = "test-id"

    db.refresh.side_effect = mock_refresh
    return db


@pytest.fixture
def ldap_service(mock_db):
    """Create LdapService with mocked database."""
    return LdapService(mock_db)


@pytest.fixture
def mock_ldap3():
    """Create a comprehensive mock of the ldap3 module."""
    mock = MagicMock()
    mock.SUBTREE = "SUBTREE"
    mock.ALL = "ALL"
    mock.Tls.return_value = MagicMock()
    mock.utils.conv.escape_filter_chars = lambda x: x
    mock.core.exceptions.LDAPBindError = type("LDAPBindError", (Exception,), {})
    mock.core.exceptions.LDAPSocketOpenError = type("LDAPSocketOpenError", (Exception,), {})
    return mock


@pytest.fixture
def mock_settings():
    """Provide default LDAP settings for tests."""
    with patch("mcpgateway.services.ldap_service.settings") as mock_s:
        mock_s.ldap_uri = "ldap://localhost:389"
        mock_s.ldap_base_dn = "dc=example,dc=org"
        mock_s.ldap_bind_dn = "cn=admin,dc=example,dc=org"
        mock_s.ldap_bind_password = MagicMock()
        mock_s.ldap_bind_password.get_secret_value.return_value = "admin"
        mock_s.ldap_user_search_base = "ou=Users"
        mock_s.ldap_user_search_filter = "(uid={username})"
        mock_s.ldap_user_email_attribute = "mail"
        mock_s.ldap_user_name_attribute = "cn"
        mock_s.ldap_user_uid_attribute = "uid"
        mock_s.ldap_group_search_base = "ou=Groups"
        mock_s.ldap_group_search_filter = "(objectClass=groupOfNames)"
        mock_s.ldap_group_member_attribute = "member"
        mock_s.ldap_group_name_attribute = "cn"
        mock_s.ldap_use_ssl = False
        mock_s.ldap_start_tls = False
        mock_s.ldap_tls_validate = True
        mock_s.ldap_connect_timeout = 5
        mock_s.ldap_search_timeout = 10
        mock_s.ldap_page_size = 500
        mock_s.ldap_auto_create_users = True
        mock_s.ldap_auto_create_teams = True
        mock_s.ldap_sync_delete_orphans = False
        mock_s.ldap_role_mappings = {"admins": "platform_admin", "data-science": "developer"}
        mock_s.ldap_default_role = "viewer"
        mock_s.ldap_sync_enabled = False
        yield mock_s


# ── Exception Classes ───────────────────────────────────────────────


class TestExceptions:
    """Test custom exception classes."""

    def test_ldap_connection_error(self):
        with pytest.raises(LdapConnectionError, match="Cannot connect"):
            raise LdapConnectionError("Cannot connect")

    def test_ldap_bind_error(self):
        with pytest.raises(LdapBindError, match="Bad credentials"):
            raise LdapBindError("Bad credentials")

    def test_ldap_search_error(self):
        with pytest.raises(LdapSearchError, match="Search failed"):
            raise LdapSearchError("Search failed")


# ── Data Classes ────────────────────────────────────────────────────


class TestDataClasses:
    """Test LDAP data structures."""

    def test_ldap_user_entry(self):
        entry = LdapUserEntry(
            dn="uid=alice,ou=Users,dc=example,dc=org",
            uid="alice",
            email="alice@example.org",
            full_name="Alice Liddell",
            groups=["cn=admins,ou=Groups,dc=example,dc=org"],
        )
        assert entry.uid == "alice"
        assert entry.email == "alice@example.org"
        assert entry.full_name == "Alice Liddell"
        assert len(entry.groups) == 1

    def test_ldap_user_entry_defaults(self):
        entry = LdapUserEntry(dn="uid=bob,ou=Users,dc=example,dc=org", uid="bob")
        assert entry.email is None
        assert entry.full_name is None
        assert entry.groups == []

    def test_ldap_group_entry(self):
        entry = LdapGroupEntry(
            dn="cn=admins,ou=Groups,dc=example,dc=org",
            name="admins",
            members=["uid=alice,ou=Users,dc=example,dc=org"],
        )
        assert entry.name == "admins"
        assert len(entry.members) == 1

    def test_sync_result_defaults(self):
        result = SyncResult()
        assert result.users_synced == 0
        assert result.groups_synced == 0
        assert result.users_removed == 0
        assert result.groups_removed == 0
        assert result.errors == []


# ── ldap3 Lazy Import ───────────────────────────────────────────────


class TestGetLdap3:
    """Test ldap3 lazy import."""

    def test_import_failure_raises(self):
        with patch.dict("sys.modules", {"ldap3": None}):
            with patch("builtins.__import__", side_effect=ImportError("no ldap3")):
                with pytest.raises(ImportError, match="ldap3 is required"):
                    _get_ldap3()


# ── Connection Check ────────────────────────────────────────────────


class TestCheckConnection:
    """Test LDAP connection checking."""

    def test_check_connection_success(self, ldap_service, mock_ldap3, mock_settings):
        """Test successful connection check."""
        mock_conn = MagicMock()
        mock_ldap3.Connection.return_value = mock_conn

        with patch("mcpgateway.services.ldap_service._get_ldap3", return_value=mock_ldap3):
            connected, error = ldap_service.check_connection()

        assert connected is True
        assert error is None
        mock_conn.unbind.assert_called_once()

    def test_check_connection_failure(self, ldap_service, mock_ldap3, mock_settings):
        """Test connection check when server is unreachable."""
        mock_ldap3.Connection.side_effect = Exception("Connection refused")

        with patch("mcpgateway.services.ldap_service._get_ldap3", return_value=mock_ldap3):
            connected, error = ldap_service.check_connection()

        assert connected is False
        assert "Connection refused" in error

    def test_check_connection_with_start_tls(self, ldap_service, mock_ldap3, mock_settings):
        """Test connection check uses AUTO_BIND_TLS_BEFORE_BIND when StartTLS is enabled."""
        mock_settings.ldap_start_tls = True
        mock_ldap3.AUTO_BIND_TLS_BEFORE_BIND = "AUTO_BIND_TLS_BEFORE_BIND"
        mock_conn = MagicMock()
        mock_ldap3.Connection.return_value = mock_conn

        with patch("mcpgateway.services.ldap_service._get_ldap3", return_value=mock_ldap3):
            connected, error = ldap_service.check_connection()

        assert connected is True
        # Verify auto_bind=AUTO_BIND_TLS_BEFORE_BIND was used (credentials sent after TLS)
        call_kwargs = mock_ldap3.Connection.call_args
        assert call_kwargs[1]["auto_bind"] == "AUTO_BIND_TLS_BEFORE_BIND"


# ── Authentication ──────────────────────────────────────────────────


class TestAuthenticate:
    """Test LDAP bind authentication."""

    def _make_entry(self, mock_ldap3, uid="alice", email="alice@example.org", full_name="Alice Liddell", dn="uid=alice,ou=Users,dc=example,dc=org"):
        """Create a mock LDAP search entry."""
        entry = MagicMock()
        entry.entry_dn = dn
        entry.uid = MagicMock()
        entry.uid.__str__ = lambda self: uid
        entry.mail = MagicMock()
        entry.mail.__str__ = lambda self: email
        entry.cn = MagicMock()
        entry.cn.__str__ = lambda self: full_name
        # Use setattr for dynamic attribute access
        setattr(entry, "uid", uid)
        setattr(entry, "mail", email)
        setattr(entry, "cn", full_name)
        entry.memberOf = []
        return entry

    def test_authenticate_success(self, ldap_service, mock_ldap3, mock_settings):
        """Test successful LDAP bind authentication."""
        entry = self._make_entry(mock_ldap3)
        service_conn = MagicMock()
        service_conn.entries = [entry]
        user_conn = MagicMock()

        # First Connection call = service account, second = user bind
        mock_ldap3.Connection.side_effect = [service_conn, user_conn]

        with patch("mcpgateway.services.ldap_service._get_ldap3", return_value=mock_ldap3):
            result = ldap_service.authenticate("alice", "password")

        assert result is not None
        assert result.uid == "alice"
        assert result.email == "alice@example.org"
        assert result.full_name == "Alice Liddell"
        service_conn.unbind.assert_called_once()
        user_conn.unbind.assert_called_once()

    def test_authenticate_empty_password_rejected(self, ldap_service, mock_settings):
        """Test that empty passwords are rejected without contacting LDAP."""
        result = ldap_service.authenticate("alice", "")
        assert result is None

    def test_authenticate_user_not_found(self, ldap_service, mock_ldap3, mock_settings):
        """Test authentication when user doesn't exist in LDAP."""
        service_conn = MagicMock()
        service_conn.entries = []
        mock_ldap3.Connection.return_value = service_conn

        with patch("mcpgateway.services.ldap_service._get_ldap3", return_value=mock_ldap3):
            result = ldap_service.authenticate("nonexistent", "password")

        assert result is None

    def test_authenticate_bad_credentials(self, ldap_service, mock_ldap3, mock_settings):
        """Test authentication with invalid password."""
        entry = self._make_entry(mock_ldap3)
        service_conn = MagicMock()
        service_conn.entries = [entry]

        bind_error = mock_ldap3.core.exceptions.LDAPBindError("invalidCredentials")
        mock_ldap3.Connection.side_effect = [service_conn, bind_error]

        with patch("mcpgateway.services.ldap_service._get_ldap3", return_value=mock_ldap3):
            result = ldap_service.authenticate("alice", "wrong_password")

        assert result is None

    def test_authenticate_server_unreachable(self, ldap_service, mock_ldap3, mock_settings):
        """Test authentication when LDAP server is unreachable."""
        socket_error = mock_ldap3.core.exceptions.LDAPSocketOpenError("Connection refused")
        mock_ldap3.Connection.side_effect = socket_error

        with patch("mcpgateway.services.ldap_service._get_ldap3", return_value=mock_ldap3):
            with pytest.raises(LdapConnectionError, match="Cannot connect"):
                ldap_service.authenticate("alice", "password")

    def test_authenticate_with_memberof(self, ldap_service, mock_ldap3, mock_settings):
        """Test authentication captures group memberships."""
        entry = self._make_entry(mock_ldap3)
        entry.memberOf = ["cn=admins,ou=Groups,dc=example,dc=org", "cn=data-science,ou=Groups,dc=example,dc=org"]

        service_conn = MagicMock()
        service_conn.entries = [entry]
        user_conn = MagicMock()
        mock_ldap3.Connection.side_effect = [service_conn, user_conn]

        with patch("mcpgateway.services.ldap_service._get_ldap3", return_value=mock_ldap3):
            result = ldap_service.authenticate("alice", "password")

        assert result is not None
        assert len(result.groups) == 2


# ── User Search ─────────────────────────────────────────────────────


class TestSearchUsers:
    """Test LDAP user search."""

    def test_search_users_returns_entries(self, ldap_service, mock_ldap3, mock_settings):
        """Test searching for all LDAP users."""
        entry1 = MagicMock()
        entry1.entry_dn = "uid=alice,ou=Users,dc=example,dc=org"
        setattr(entry1, "uid", "alice")
        setattr(entry1, "mail", "alice@example.org")
        setattr(entry1, "cn", "Alice Liddell")
        entry1.memberOf = []

        entry2 = MagicMock()
        entry2.entry_dn = "uid=bob,ou=Users,dc=example,dc=org"
        setattr(entry2, "uid", "bob")
        setattr(entry2, "mail", "bob@example.org")
        setattr(entry2, "cn", "Bob Builder")
        entry2.memberOf = []

        conn = MagicMock()
        conn.entries = [entry1, entry2]
        mock_ldap3.Connection.return_value = conn

        with patch("mcpgateway.services.ldap_service._get_ldap3", return_value=mock_ldap3):
            users = ldap_service.search_users()

        assert len(users) == 2
        assert users[0].uid == "alice"
        assert users[1].uid == "bob"

    def test_search_users_server_unreachable(self, ldap_service, mock_ldap3, mock_settings):
        """Test user search when server is unreachable."""
        socket_error = mock_ldap3.core.exceptions.LDAPSocketOpenError("Connection refused")
        mock_ldap3.Connection.side_effect = socket_error

        with patch("mcpgateway.services.ldap_service._get_ldap3", return_value=mock_ldap3):
            with pytest.raises(LdapConnectionError):
                ldap_service.search_users()

    def test_search_users_filters_empty_uid(self, ldap_service, mock_ldap3, mock_settings):
        """Test that entries with empty uid are filtered out."""
        entry = MagicMock()
        entry.entry_dn = "uid=,ou=Users,dc=example,dc=org"
        setattr(entry, "uid", "")
        setattr(entry, "mail", "")
        setattr(entry, "cn", "")

        conn = MagicMock()
        conn.entries = [entry]
        mock_ldap3.Connection.return_value = conn

        with patch("mcpgateway.services.ldap_service._get_ldap3", return_value=mock_ldap3):
            users = ldap_service.search_users()

        assert len(users) == 0


# ── Group Search ────────────────────────────────────────────────────


class TestSearchGroups:
    """Test LDAP group search."""

    def test_search_groups_returns_entries(self, ldap_service, mock_ldap3, mock_settings):
        """Test searching for all LDAP groups."""
        entry = MagicMock()
        entry.entry_dn = "cn=admins,ou=Groups,dc=example,dc=org"
        setattr(entry, "cn", "admins")
        setattr(entry, "member", ["uid=alice,ou=Users,dc=example,dc=org"])

        conn = MagicMock()
        conn.entries = [entry]
        mock_ldap3.Connection.return_value = conn

        with patch("mcpgateway.services.ldap_service._get_ldap3", return_value=mock_ldap3):
            groups = ldap_service.search_groups()

        assert len(groups) == 1
        assert groups[0].name == "admins"
        assert len(groups[0].members) == 1

    def test_search_groups_server_unreachable(self, ldap_service, mock_ldap3, mock_settings):
        """Test group search when server is unreachable."""
        socket_error = mock_ldap3.core.exceptions.LDAPSocketOpenError("Connection refused")
        mock_ldap3.Connection.side_effect = socket_error

        with patch("mcpgateway.services.ldap_service._get_ldap3", return_value=mock_ldap3):
            with pytest.raises(LdapConnectionError):
                ldap_service.search_groups()


# ── Role Resolution ─────────────────────────────────────────────────


class TestResolveRole:
    """Test LDAP group to role mapping."""

    def test_resolve_role_exact_match(self, ldap_service, mock_settings):
        """Test role resolution with exact group name match."""
        role = ldap_service._resolve_role(["admins"])
        assert role == "platform_admin"

    def test_resolve_role_dn_match(self, ldap_service, mock_settings):
        """Test role resolution extracting CN from full DN."""
        role = ldap_service._resolve_role(["cn=data-science,ou=Groups,dc=example,dc=org"])
        assert role == "developer"

    def test_resolve_role_no_match_returns_default(self, ldap_service, mock_settings):
        """Test role resolution returns default role when no mapping matches."""
        role = ldap_service._resolve_role(["cn=unknown-group,ou=Groups,dc=example,dc=org"])
        assert role == "viewer"

    def test_resolve_role_empty_groups(self, ldap_service, mock_settings):
        """Test role resolution with empty group list."""
        role = ldap_service._resolve_role([])
        assert role == "viewer"

    def test_resolve_role_no_mappings(self, ldap_service, mock_settings):
        """Test role resolution when no mappings configured."""
        mock_settings.ldap_role_mappings = {}
        role = ldap_service._resolve_role(["admins"])
        assert role == "viewer"


# ── User Provisioning ──────────────────────────────────────────────


class TestGetOrCreateUser:
    """Test LDAP user provisioning."""

    @pytest.mark.asyncio
    async def test_get_existing_user(self, ldap_service, mock_settings):
        """Test returning existing user."""
        existing_user = MagicMock()
        existing_user.email = "alice@example.org"
        existing_user.auth_provider = "ldap"

        ldap_entry = LdapUserEntry(
            dn="uid=alice,ou=Users,dc=example,dc=org",
            uid="alice",
            email="alice@example.org",
            full_name="Alice Liddell",
        )

        with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_cls:
            mock_auth = mock_auth_cls.return_value
            mock_auth.get_user_by_email = AsyncMock(return_value=existing_user)

            result = await ldap_service.get_or_create_user(ldap_entry)

        assert result == existing_user

    @pytest.mark.asyncio
    async def test_create_new_user(self, ldap_service, mock_settings):
        """Test creating new user from LDAP entry."""
        new_user = MagicMock()
        new_user.email = "alice@example.org"

        ldap_entry = LdapUserEntry(
            dn="uid=alice,ou=Users,dc=example,dc=org",
            uid="alice",
            email="alice@example.org",
            full_name="Alice Liddell",
            groups=["cn=data-science,ou=Groups,dc=example,dc=org"],
        )

        with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_cls:
            mock_auth = mock_auth_cls.return_value
            mock_auth.get_user_by_email = AsyncMock(return_value=None)
            mock_auth.create_user = AsyncMock(return_value=new_user)

            result = await ldap_service.get_or_create_user(ldap_entry)

        assert result == new_user
        mock_auth.create_user.assert_called_once()
        call_kwargs = mock_auth.create_user.call_args
        assert call_kwargs[1]["auth_provider"] == "ldap"
        assert call_kwargs[1]["skip_password_validation"] is True

    @pytest.mark.asyncio
    async def test_auto_create_disabled(self, ldap_service, mock_settings):
        """Test that user creation is skipped when auto_create is disabled."""
        mock_settings.ldap_auto_create_users = False

        ldap_entry = LdapUserEntry(
            dn="uid=alice,ou=Users,dc=example,dc=org",
            uid="alice",
            email="alice@example.org",
        )

        with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_cls:
            mock_auth = mock_auth_cls.return_value
            mock_auth.get_user_by_email = AsyncMock(return_value=None)

            result = await ldap_service.get_or_create_user(ldap_entry)

        assert result is None

    @pytest.mark.asyncio
    async def test_email_fallback_from_uid(self, ldap_service, mock_settings):
        """Test that email is derived from uid+base_dn when mail attribute is missing."""
        new_user = MagicMock()
        new_user.email = "alice@example.org"

        ldap_entry = LdapUserEntry(
            dn="uid=alice,ou=Users,dc=example,dc=org",
            uid="alice",
            email=None,  # No mail attribute
        )

        with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_cls:
            mock_auth = mock_auth_cls.return_value
            mock_auth.get_user_by_email = AsyncMock(return_value=None)
            mock_auth.create_user = AsyncMock(return_value=new_user)

            result = await ldap_service.get_or_create_user(ldap_entry)

        assert result == new_user
        call_kwargs = mock_auth.create_user.call_args
        assert call_kwargs[1]["email"] == "alice@example.org"

    @pytest.mark.asyncio
    async def test_admin_role_from_group(self, ldap_service, mock_settings):
        """Test that users in admin groups get is_admin=True."""
        new_user = MagicMock()
        ldap_entry = LdapUserEntry(
            dn="uid=alice,ou=Users,dc=example,dc=org",
            uid="alice",
            email="alice@example.org",
            groups=["admins"],  # Maps to platform_admin
        )

        with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_cls:
            mock_auth = mock_auth_cls.return_value
            mock_auth.get_user_by_email = AsyncMock(return_value=None)
            mock_auth.create_user = AsyncMock(return_value=new_user)

            await ldap_service.get_or_create_user(ldap_entry)

        call_kwargs = mock_auth.create_user.call_args
        assert call_kwargs[1]["is_admin"] is True

    @pytest.mark.asyncio
    async def test_rejects_non_ldap_provider(self, ldap_service, mock_settings):
        """Test that login is rejected for users with a different auth provider."""
        existing_user = MagicMock()
        existing_user.email = "alice@example.org"
        existing_user.auth_provider = "local"  # Not LDAP

        ldap_entry = LdapUserEntry(
            dn="uid=alice,ou=Users,dc=example,dc=org",
            uid="alice",
            email="alice@example.org",
        )

        with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_cls:
            mock_auth = mock_auth_cls.return_value
            mock_auth.get_user_by_email = AsyncMock(return_value=existing_user)

            result = await ldap_service.get_or_create_user(ldap_entry)

        assert result is None

    @pytest.mark.asyncio
    async def test_role_upgrade_on_login(self, ldap_service, mock_settings):
        """Test that existing LDAP user gets admin upgraded based on current groups."""
        existing_user = MagicMock()
        existing_user.email = "alice@example.org"
        existing_user.auth_provider = "ldap"
        existing_user.is_admin = False
        existing_user.admin_origin = None

        ldap_entry = LdapUserEntry(
            dn="uid=alice,ou=Users,dc=example,dc=org",
            uid="alice",
            email="alice@example.org",
            groups=["admins"],  # Maps to platform_admin
        )

        with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_cls:
            mock_auth = mock_auth_cls.return_value
            mock_auth.get_user_by_email = AsyncMock(return_value=existing_user)

            result = await ldap_service.get_or_create_user(ldap_entry)

        assert result.is_admin is True
        assert result.admin_origin == "ldap"

    @pytest.mark.asyncio
    async def test_role_revoke_on_login(self, ldap_service, mock_settings):
        """Test that admin is revoked when user removed from admin LDAP group."""
        existing_user = MagicMock()
        existing_user.email = "alice@example.org"
        existing_user.auth_provider = "ldap"
        existing_user.is_admin = True
        existing_user.admin_origin = "ldap"  # Was granted via LDAP

        ldap_entry = LdapUserEntry(
            dn="uid=alice,ou=Users,dc=example,dc=org",
            uid="alice",
            email="alice@example.org",
            groups=["data-science"],  # No longer in admins group
        )

        with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_cls:
            mock_auth = mock_auth_cls.return_value
            mock_auth.get_user_by_email = AsyncMock(return_value=existing_user)

            result = await ldap_service.get_or_create_user(ldap_entry)

        assert result.is_admin is False
        assert result.admin_origin is None

    @pytest.mark.asyncio
    async def test_manual_admin_not_revoked(self, ldap_service, mock_settings):
        """Test that manually-granted admin is not revoked by LDAP group changes."""
        existing_user = MagicMock()
        existing_user.email = "alice@example.org"
        existing_user.auth_provider = "ldap"
        existing_user.is_admin = True
        existing_user.admin_origin = "manual"  # Granted manually, not via LDAP

        ldap_entry = LdapUserEntry(
            dn="uid=alice,ou=Users,dc=example,dc=org",
            uid="alice",
            email="alice@example.org",
            groups=["data-science"],  # Not in admins group
        )

        with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_cls:
            mock_auth = mock_auth_cls.return_value
            mock_auth.get_user_by_email = AsyncMock(return_value=existing_user)

            result = await ldap_service.get_or_create_user(ldap_entry)

        # Admin was granted manually, should NOT be revoked by LDAP
        assert result.is_admin is True


# ── Directory Sync ──────────────────────────────────────────────────


class TestSyncDirectory:
    """Test LDAP directory sync."""

    @pytest.mark.asyncio
    async def test_sync_directory_success(self, ldap_service, mock_settings):
        """Test successful directory sync."""
        mock_settings.ldap_auto_create_teams = False  # Simplify test

        user_entries = [
            LdapUserEntry(dn="uid=alice,ou=Users", uid="alice", email="alice@example.org"),
            LdapUserEntry(dn="uid=bob,ou=Users", uid="bob", email="bob@example.org"),
        ]

        mock_user = MagicMock()
        mock_user.email = "test@example.org"

        with patch.object(ldap_service, "search_users", return_value=user_entries):
            with patch.object(ldap_service, "search_groups", return_value=[]):
                with patch.object(ldap_service, "get_or_create_user", new_callable=AsyncMock, return_value=mock_user):
                    result = await ldap_service.sync_directory()

        assert result.users_synced == 2
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_sync_directory_user_search_fails(self, ldap_service, mock_settings):
        """Test sync when user search fails."""
        with patch.object(ldap_service, "search_users", side_effect=LdapConnectionError("down")):
            result = await ldap_service.sync_directory()

        assert result.users_synced == 0
        assert len(result.errors) == 1
        assert "User search failed" in result.errors[0]

    @pytest.mark.asyncio
    async def test_sync_directory_group_search_fails(self, ldap_service, mock_settings):
        """Test sync continues when group search fails."""
        mock_settings.ldap_auto_create_teams = True
        mock_user = MagicMock()
        mock_user.email = "alice@example.org"

        with patch.object(ldap_service, "search_users", return_value=[
            LdapUserEntry(dn="uid=alice", uid="alice", email="alice@example.org"),
        ]):
            with patch.object(ldap_service, "search_groups", side_effect=LdapSearchError("failed")):
                with patch.object(ldap_service, "get_or_create_user", new_callable=AsyncMock, return_value=mock_user):
                    result = await ldap_service.sync_directory()

        assert result.users_synced == 1
        assert len(result.errors) == 1
        assert "Group search failed" in result.errors[0]

    @pytest.mark.asyncio
    async def test_sync_directory_with_orphan_removal(self, ldap_service, mock_db, mock_settings):
        """Test sync with orphan user removal."""
        mock_settings.ldap_sync_delete_orphans = True
        mock_settings.ldap_auto_create_teams = False

        mock_user = MagicMock()
        mock_user.email = "alice@example.org"

        # One active LDAP user
        with patch.object(ldap_service, "search_users", return_value=[
            LdapUserEntry(dn="uid=alice", uid="alice", email="alice@example.org"),
        ]):
            with patch.object(ldap_service, "search_groups", return_value=[]):
                with patch.object(ldap_service, "get_or_create_user", new_callable=AsyncMock, return_value=mock_user):
                    with patch.object(ldap_service, "_remove_orphan_users", return_value=1):
                        result = await ldap_service.sync_directory()

        assert result.users_synced == 1
        assert result.users_removed == 1


# ── Orphan Removal ──────────────────────────────────────────────────


class TestRemoveOrphanUsers:
    """Test orphan LDAP user removal."""

    def test_remove_orphans(self, ldap_service, mock_db, mock_settings):
        """Test that LDAP users not in sync are removed."""
        orphan = MagicMock()
        orphan.email = "orphan@example.org"
        orphan.auth_provider = "ldap"

        active = MagicMock()
        active.email = "alice@example.org"
        active.auth_provider = "ldap"

        mock_db.query.return_value.filter.return_value.all.return_value = [active, orphan]

        removed = ldap_service._remove_orphan_users({"alice@example.org"})

        assert removed == 1
        mock_db.delete.assert_called_once_with(orphan)

    def test_no_orphans(self, ldap_service, mock_db, mock_settings):
        """Test no removal when all users are active."""
        user = MagicMock()
        user.email = "alice@example.org"
        mock_db.query.return_value.filter.return_value.all.return_value = [user]

        removed = ldap_service._remove_orphan_users({"alice@example.org"})

        assert removed == 0
        mock_db.delete.assert_not_called()


# ── Search DN Construction ──────────────────────────────────────────


class TestSearchDNConstruction:
    """Test DN construction helpers."""

    def test_user_search_dn(self, ldap_service, mock_settings):
        """Test user search DN construction."""
        result = ldap_service._get_user_search_dn()
        assert result == "ou=Users,dc=example,dc=org"

    def test_user_search_dn_empty_base(self, ldap_service, mock_settings):
        """Test user search DN when search base is empty."""
        mock_settings.ldap_user_search_base = ""
        result = ldap_service._get_user_search_dn()
        assert result == "dc=example,dc=org"

    def test_group_search_dn(self, ldap_service, mock_settings):
        """Test group search DN construction."""
        result = ldap_service._get_group_search_dn()
        assert result == "ou=Groups,dc=example,dc=org"


# ── Password Generation ────────────────────────────────────────────


class TestPasswordGeneration:
    """Test placeholder password generation."""

    def test_password_length(self, ldap_service):
        """Test that generated passwords are 64 characters."""
        pwd = ldap_service._generate_placeholder_password()
        assert len(pwd) == 64

    def test_password_uniqueness(self, ldap_service):
        """Test that generated passwords are unique."""
        pwd1 = ldap_service._generate_placeholder_password()
        pwd2 = ldap_service._generate_placeholder_password()
        assert pwd1 != pwd2
