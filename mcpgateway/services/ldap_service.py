# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/ldap_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

LDAP / Active Directory Authentication Service.
This module provides LDAP bind authentication, user/group lookup,
and directory sync for importing users and groups into the gateway.

Examples:
    >>> from mcpgateway.services.ldap_service import LdapService
    >>> isinstance(LdapService, type)
    True
"""

# Standard
import secrets
import string
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailUser, utc_now
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class LdapConnectionError(Exception):
    """Raised when LDAP connection fails.

    Examples:
        >>> try:
        ...     raise LdapConnectionError("Cannot connect")
        ... except LdapConnectionError as e:
        ...     str(e)
        'Cannot connect'
    """


class LdapBindError(Exception):
    """Raised when LDAP bind (authentication) fails.

    Examples:
        >>> try:
        ...     raise LdapBindError("Bad credentials")
        ... except LdapBindError as e:
        ...     str(e)
        'Bad credentials'
    """


class LdapSearchError(Exception):
    """Raised when LDAP search fails.

    Examples:
        >>> try:
        ...     raise LdapSearchError("Search failed")
        ... except LdapSearchError as e:
        ...     str(e)
        'Search failed'
    """


@dataclass(frozen=True)
class LdapUserEntry:
    """Represents a user entry found in LDAP.

    Examples:
        >>> entry = LdapUserEntry(dn="uid=alice,ou=Users,dc=example,dc=org", uid="alice", email="alice@example.org", full_name="Alice Liddell")
        >>> entry.uid
        'alice'
    """

    dn: str
    uid: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    groups: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class LdapGroupEntry:
    """Represents a group entry found in LDAP.

    Examples:
        >>> entry = LdapGroupEntry(dn="cn=admins,ou=Groups,dc=example,dc=org", name="admins", members=["uid=alice,ou=Users,dc=example,dc=org"])
        >>> entry.name
        'admins'
    """

    dn: str
    name: str
    members: List[str] = field(default_factory=list)


@dataclass
class SyncResult:
    """Result of an LDAP directory sync operation.

    Examples:
        >>> result = SyncResult()
        >>> result.users_synced
        0
    """

    users_synced: int = 0
    groups_synced: int = 0
    users_removed: int = 0
    groups_removed: int = 0
    errors: List[str] = field(default_factory=list)


def _get_ldap3():
    """Lazy import ldap3 to avoid hard dependency.

    Returns:
        The ldap3 module.

    Raises:
        ImportError: If ldap3 is not installed.
    """
    try:
        import ldap3  # noqa: F811

        return ldap3
    except ImportError:
        raise ImportError("ldap3 is required for LDAP support. Install with: pip install 'mcp-contextforge-gateway[ldap]'")


class LdapService:
    """Service for LDAP/Active Directory authentication and directory sync.

    Provides LDAP bind authentication, user and group lookup,
    and periodic directory synchronization.

    Attributes:
        db: SQLAlchemy database session

    Examples:
        >>> from unittest.mock import MagicMock
        >>> service = LdapService(db=MagicMock())
        >>> isinstance(service, LdapService)
        True
    """

    _last_sync_at: Optional[datetime] = None

    def __init__(self, db: Session):
        """Initialize the LDAP service.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        logger.debug("LdapService initialized")

    def _build_server(self) -> Any:
        """Build an ldap3 Server object from configuration.

        Returns:
            ldap3.Server instance configured from settings.
        """
        ldap3 = _get_ldap3()

        tls = None
        if settings.ldap_use_ssl or settings.ldap_start_tls:
            tls = ldap3.Tls(
                validate=2 if settings.ldap_tls_validate else 0,  # ssl.CERT_REQUIRED=2, ssl.CERT_NONE=0
            )

        return ldap3.Server(
            settings.ldap_uri,
            use_ssl=settings.ldap_use_ssl,
            tls=tls,
            connect_timeout=settings.ldap_connect_timeout,
            get_info=ldap3.ALL,
        )

    def _get_user_search_dn(self) -> str:
        """Construct the full DN for user searches.

        Returns:
            Full search DN combining user search base and base DN.

        Examples:
            >>> from unittest.mock import MagicMock
            >>> service = LdapService(db=MagicMock())
            >>> isinstance(service._get_user_search_dn(), str)
            True
        """
        if settings.ldap_user_search_base:
            return f"{settings.ldap_user_search_base},{settings.ldap_base_dn}"
        return settings.ldap_base_dn

    def _get_group_search_dn(self) -> str:
        """Construct the full DN for group searches.

        Returns:
            Full search DN combining group search base and base DN.
        """
        if settings.ldap_group_search_base:
            return f"{settings.ldap_group_search_base},{settings.ldap_base_dn}"
        return settings.ldap_base_dn

    def _get_auto_bind(self) -> Any:
        """Return the appropriate auto_bind constant based on TLS config.

        When StartTLS is enabled, uses AUTO_BIND_TLS_BEFORE_BIND to ensure
        the TLS handshake completes before any credentials are sent.

        Returns:
            ldap3 auto_bind constant.
        """
        ldap3 = _get_ldap3()
        if settings.ldap_start_tls:
            return ldap3.AUTO_BIND_TLS_BEFORE_BIND
        return True

    def check_connection(self) -> tuple[bool, Optional[str]]:
        """Check if the LDAP server is reachable using service account bind.

        Returns:
            Tuple of (connected: bool, error_message: Optional[str])
        """
        ldap3 = _get_ldap3()
        try:
            server = self._build_server()
            conn = ldap3.Connection(
                server,
                user=settings.ldap_bind_dn,
                password=settings.ldap_bind_password.get_secret_value(),
                auto_bind=self._get_auto_bind(),
                read_only=True,
                receive_timeout=settings.ldap_connect_timeout,
            )
            conn.unbind()
            return True, None
        except Exception as exc:
            logger.warning("LDAP connection check failed: %s", exc)
            return False, str(exc)

    def authenticate(self, username: str, password: str) -> Optional[LdapUserEntry]:
        """Authenticate a user via LDAP simple bind.

        Performs a two-step process:
        1. Search for the user DN using the service account
        2. Attempt a simple bind with the found DN and provided password

        Args:
            username: The LDAP username (uid/sAMAccountName)
            password: The user's password

        Returns:
            LdapUserEntry if authentication succeeds, None otherwise.

        Raises:
            LdapConnectionError: If the LDAP server is unreachable.
        """
        if not password:
            logger.warning("LDAP bind rejected: empty password for user %s", username)
            return None

        ldap3 = _get_ldap3()
        try:
            # Step 1: Find user DN via service account
            server = self._build_server()
            service_conn = ldap3.Connection(
                server,
                user=settings.ldap_bind_dn,
                password=settings.ldap_bind_password.get_secret_value(),
                auto_bind=self._get_auto_bind(),
                read_only=True,
                receive_timeout=settings.ldap_search_timeout,
            )

            search_filter = settings.ldap_user_search_filter.replace("{username}", ldap3.utils.conv.escape_filter_chars(username))
            search_dn = self._get_user_search_dn()

            service_conn.search(
                search_base=search_dn,
                search_filter=search_filter,
                search_scope=ldap3.SUBTREE,
                attributes=[
                    settings.ldap_user_uid_attribute,
                    settings.ldap_user_email_attribute,
                    settings.ldap_user_name_attribute,
                    "memberOf",
                ],
                time_limit=settings.ldap_search_timeout,
            )

            entries = [e for e in service_conn.entries if e.entry_dn and "CN=Configuration" not in str(e.entry_dn)]
            service_conn.unbind()

            if not entries:
                logger.info("LDAP user not found: %s", username)
                return None

            entry = entries[0]
            user_dn = entry.entry_dn
            uid = str(getattr(entry, settings.ldap_user_uid_attribute, username))
            email = str(getattr(entry, settings.ldap_user_email_attribute, "")) or None
            full_name = str(getattr(entry, settings.ldap_user_name_attribute, "")) or None
            groups = [str(g) for g in getattr(entry, "memberOf", [])] if hasattr(entry, "memberOf") else []

            # Step 2: Bind as the user to verify credentials
            user_conn = ldap3.Connection(
                server,
                user=user_dn,
                password=password,
                auto_bind=self._get_auto_bind(),
                read_only=True,
                receive_timeout=settings.ldap_connect_timeout,
            )
            user_conn.unbind()

            logger.info("LDAP bind successful for user: %s (DN: %s)", username, user_dn)
            return LdapUserEntry(dn=user_dn, uid=uid, email=email, full_name=full_name, groups=groups)

        except ldap3.core.exceptions.LDAPBindError:
            logger.info("LDAP bind failed for user: %s (invalid credentials)", username)
            return None
        except ldap3.core.exceptions.LDAPSocketOpenError as exc:
            logger.error("LDAP connection failed: %s", exc)
            raise LdapConnectionError(f"Cannot connect to LDAP server: {exc}") from exc
        except Exception as exc:
            logger.error("LDAP authentication error for user %s: %s", username, exc)
            return None

    def search_users(self) -> List[LdapUserEntry]:
        """Search for all users in the LDAP directory.

        Returns:
            List of LdapUserEntry objects.

        Raises:
            LdapConnectionError: If the LDAP server is unreachable.
            LdapSearchError: If the search fails.
        """
        ldap3 = _get_ldap3()
        try:
            server = self._build_server()
            conn = ldap3.Connection(
                server,
                user=settings.ldap_bind_dn,
                password=settings.ldap_bind_password.get_secret_value(),
                auto_bind=self._get_auto_bind(),
                read_only=True,
                receive_timeout=settings.ldap_search_timeout,
            )

            search_dn = self._get_user_search_dn()
            user_filter = settings.ldap_user_search_filter.replace("{username}", "*")

            conn.search(
                search_base=search_dn,
                search_filter=user_filter,
                search_scope=ldap3.SUBTREE,
                attributes=[
                    settings.ldap_user_uid_attribute,
                    settings.ldap_user_email_attribute,
                    settings.ldap_user_name_attribute,
                    "memberOf",
                ],
                paged_size=settings.ldap_page_size,
                time_limit=settings.ldap_search_timeout,
            )

            users: List[LdapUserEntry] = []
            for entry in conn.entries:
                if not entry.entry_dn or "CN=Configuration" in str(entry.entry_dn):
                    continue
                uid = str(getattr(entry, settings.ldap_user_uid_attribute, ""))
                if not uid:
                    continue
                email = str(getattr(entry, settings.ldap_user_email_attribute, "")) or None
                full_name = str(getattr(entry, settings.ldap_user_name_attribute, "")) or None
                groups = [str(g) for g in getattr(entry, "memberOf", [])] if hasattr(entry, "memberOf") else []
                users.append(LdapUserEntry(dn=entry.entry_dn, uid=uid, email=email, full_name=full_name, groups=groups))

            conn.unbind()
            logger.info("LDAP user search returned %d users", len(users))
            return users

        except ldap3.core.exceptions.LDAPSocketOpenError as exc:
            raise LdapConnectionError(f"Cannot connect to LDAP server: {exc}") from exc
        except Exception as exc:
            raise LdapSearchError(f"LDAP user search failed: {exc}") from exc

    def search_groups(self) -> List[LdapGroupEntry]:
        """Search for all groups in the LDAP directory.

        Returns:
            List of LdapGroupEntry objects.

        Raises:
            LdapConnectionError: If the LDAP server is unreachable.
            LdapSearchError: If the search fails.
        """
        ldap3 = _get_ldap3()
        try:
            server = self._build_server()
            conn = ldap3.Connection(
                server,
                user=settings.ldap_bind_dn,
                password=settings.ldap_bind_password.get_secret_value(),
                auto_bind=self._get_auto_bind(),
                read_only=True,
                receive_timeout=settings.ldap_search_timeout,
            )

            search_dn = self._get_group_search_dn()

            conn.search(
                search_base=search_dn,
                search_filter=settings.ldap_group_search_filter,
                search_scope=ldap3.SUBTREE,
                attributes=[
                    settings.ldap_group_name_attribute,
                    settings.ldap_group_member_attribute,
                ],
                paged_size=settings.ldap_page_size,
                time_limit=settings.ldap_search_timeout,
            )

            groups: List[LdapGroupEntry] = []
            for entry in conn.entries:
                if not entry.entry_dn:
                    continue
                name = str(getattr(entry, settings.ldap_group_name_attribute, ""))
                if not name:
                    continue
                members = [str(m) for m in getattr(entry, settings.ldap_group_member_attribute, [])]
                groups.append(LdapGroupEntry(dn=entry.entry_dn, name=name, members=members))

            conn.unbind()
            logger.info("LDAP group search returned %d groups", len(groups))
            return groups

        except ldap3.core.exceptions.LDAPSocketOpenError as exc:
            raise LdapConnectionError(f"Cannot connect to LDAP server: {exc}") from exc
        except Exception as exc:
            raise LdapSearchError(f"LDAP group search failed: {exc}") from exc

    def _resolve_role(self, ldap_groups: List[str]) -> Optional[str]:
        """Map LDAP group memberships to a gateway role.

        Checks the configured role_mappings dict. Returns the first matching
        role or the default_role if no mapping matches.

        Args:
            ldap_groups: List of LDAP group DNs or names the user belongs to.

        Returns:
            Gateway role name, or None if no mapping and no default.

        Examples:
            >>> from unittest.mock import MagicMock
            >>> service = LdapService(db=MagicMock())
            >>> service._resolve_role([])  # Returns default role
            'viewer'
        """
        role_mappings = settings.ldap_role_mappings
        if role_mappings:
            group_names = set()
            for g in ldap_groups:
                group_names.add(g)
                # Extract CN from DN if present (e.g., "cn=admins,ou=Groups,dc=...")
                if "," in g:
                    parts = g.split(",")
                    for part in parts:
                        if part.strip().lower().startswith("cn="):
                            group_names.add(part.strip().split("=", 1)[1])

            for ldap_group, role in role_mappings.items():
                if ldap_group in group_names:
                    return role

        return settings.ldap_default_role

    def _generate_placeholder_password(self) -> str:
        """Generate a secure random password for LDAP users.

        LDAP users authenticate via LDAP bind, so this password is never used
        directly. It prevents local login for LDAP-provisioned accounts.

        Returns:
            Random 64-character password.
        """
        chars = string.ascii_letters + string.digits + string.punctuation
        return "".join(secrets.choice(chars) for _ in range(64))

    async def get_or_create_user(self, ldap_entry: LdapUserEntry) -> Optional[EmailUser]:
        """Get or create a gateway user from an LDAP entry.

        If the user exists and was created from LDAP, returns it.
        If the user doesn't exist and auto_create_users is enabled, creates it.

        Args:
            ldap_entry: The LDAP user entry.

        Returns:
            EmailUser instance or None if creation is disabled.
        """
        # First-Party
        from mcpgateway.services.email_auth_service import EmailAuthService

        auth_service = EmailAuthService(self.db)

        # Derive email: prefer the mail attribute, fall back to uid@base_dn
        email = ldap_entry.email
        if not email or email in ("[]", ""):
            # Construct email from uid + base_dn domain
            domain_parts = [p.split("=")[1] for p in settings.ldap_base_dn.split(",") if "=" in p]
            domain = ".".join(domain_parts) if domain_parts else "ldap.local"
            email = f"{ldap_entry.uid}@{domain}"
        email = email.lower().strip()

        # Check if user already exists
        existing = await auth_service.get_user_by_email(email)
        if existing:
            # Reject login if the account was created via a different auth provider
            if existing.auth_provider and existing.auth_provider != "ldap":
                logger.warning(
                    "LDAP login rejected for %s: account uses auth_provider=%s",
                    email,
                    existing.auth_provider,
                )
                return None

            # Re-evaluate is_admin from current LDAP group memberships (matches SSO pattern)
            role = self._resolve_role(ldap_entry.groups)
            should_be_admin = role == "platform_admin" if role else False
            admin_origin = getattr(existing, "admin_origin", None)
            if should_be_admin and not existing.is_admin:
                logger.info("Upgrading is_admin to True for %s based on LDAP groups", email)
                existing.is_admin = True
                existing.admin_origin = "ldap"
            elif not should_be_admin and existing.is_admin and admin_origin == "ldap":
                logger.info("Revoking is_admin for %s - removed from LDAP admin groups", email)
                existing.is_admin = False
                existing.admin_origin = None

            return existing

        if not settings.ldap_auto_create_users:
            logger.info("LDAP user %s not found and auto-create disabled", email)
            return None

        # Resolve role from LDAP groups
        role = self._resolve_role(ldap_entry.groups)
        is_admin = role == "platform_admin" if role else False

        try:
            user = await auth_service.create_user(
                email=email,
                password=self._generate_placeholder_password(),
                full_name=ldap_entry.full_name or ldap_entry.uid,
                is_admin=is_admin,
                auth_provider="ldap",
                skip_password_validation=True,
            )
            logger.info("Created LDAP user: %s (role: %s)", email, role)
            return user
        except Exception as exc:
            logger.error("Failed to create LDAP user %s: %s", email, exc)
            return None

    async def sync_directory(self) -> SyncResult:
        """Perform a full directory sync from LDAP.

        Imports all users and groups from LDAP, creates/updates gateway
        records, and optionally removes orphaned records.

        Returns:
            SyncResult with counts and errors.
        """
        # First-Party
        from mcpgateway.services.email_auth_service import EmailAuthService

        result = SyncResult()
        auth_service = EmailAuthService(self.db)

        # Sync users
        try:
            ldap_users = self.search_users()
        except (LdapConnectionError, LdapSearchError) as exc:
            result.errors.append(f"User search failed: {exc}")
            return result

        synced_emails: set[str] = set()
        for ldap_user in ldap_users:
            try:
                user = await self.get_or_create_user(ldap_user)
                if user:
                    email = getattr(user, "email", None)
                    if email:
                        synced_emails.add(email)
                    result.users_synced += 1
            except Exception as exc:
                result.errors.append(f"Failed to sync user {ldap_user.uid}: {exc}")

        # Sync groups -> teams
        try:
            ldap_groups = self.search_groups()
        except (LdapConnectionError, LdapSearchError) as exc:
            result.errors.append(f"Group search failed: {exc}")
            ldap_groups = []

        if settings.ldap_auto_create_teams:
            synced_group_names: set[str] = set()
            for ldap_group in ldap_groups:
                try:
                    await self._sync_group_to_team(ldap_group, auth_service)
                    synced_group_names.add(ldap_group.name)
                    result.groups_synced += 1
                except Exception as exc:
                    result.errors.append(f"Failed to sync group {ldap_group.name}: {exc}")

        # Handle orphan removal
        if settings.ldap_sync_delete_orphans and synced_emails:
            try:
                removed = self._remove_orphan_users(synced_emails)
                result.users_removed = removed
            except Exception as exc:
                result.errors.append(f"Orphan removal failed: {exc}")

        LdapService._last_sync_at = datetime.now(tz=timezone.utc)
        logger.info(
            "LDAP sync completed: %d users, %d groups synced; %d users removed; %d errors",
            result.users_synced,
            result.groups_synced,
            result.users_removed,
            len(result.errors),
        )
        return result

    async def _sync_group_to_team(self, ldap_group: LdapGroupEntry, auth_service: Any) -> None:
        """Sync an LDAP group to a gateway team.

        Args:
            ldap_group: LDAP group entry.
            auth_service: EmailAuthService instance.
        """
        # First-Party
        from mcpgateway.db import EmailTeam, EmailTeamMember

        team_name = f"ldap-{ldap_group.name}"

        existing_team = self.db.query(EmailTeam).filter(EmailTeam.name == team_name).first()
        if not existing_team:
            existing_team = EmailTeam(
                name=team_name,
                description=f"LDAP group: {ldap_group.name}",
            )
            self.db.add(existing_team)
            self.db.flush()
            logger.info("Created team from LDAP group: %s", team_name)

        # Resolve member emails from DNs
        for member_dn in ldap_group.members:
            # Extract uid from DN (e.g., "uid=alice,ou=Users,dc=example,dc=org" -> "alice")
            uid = None
            for part in member_dn.split(","):
                key_val = part.strip().split("=", 1)
                if len(key_val) == 2 and key_val[0].strip().lower() == settings.ldap_user_uid_attribute.lower():
                    uid = key_val[1].strip()
                    break

            if not uid:
                continue

            # Look up the user's email
            domain_parts = [p.split("=")[1] for p in settings.ldap_base_dn.split(",") if "=" in p]
            domain = ".".join(domain_parts) if domain_parts else "ldap.local"
            email = f"{uid}@{domain}"

            user = await auth_service.get_user_by_email(email)
            if not user:
                continue

            # Add membership if not exists
            existing_member = (
                self.db.query(EmailTeamMember)
                .filter(
                    EmailTeamMember.team_id == existing_team.id,
                    EmailTeamMember.user_email == email,
                )
                .first()
            )
            if not existing_member:
                member = EmailTeamMember(
                    team_id=existing_team.id,
                    user_email=email,
                    role="member",
                )
                self.db.add(member)

        self.db.commit()

    def _remove_orphan_users(self, active_emails: set[str]) -> int:
        """Remove LDAP-provisioned users not found in the latest sync.

        Only removes users with auth_provider='ldap'.

        Args:
            active_emails: Set of emails found in the latest LDAP sync.

        Returns:
            Number of users removed.
        """
        ldap_users = self.db.query(EmailUser).filter(EmailUser.auth_provider == "ldap").all()
        removed = 0
        for user in ldap_users:
            if user.email not in active_emails:
                logger.info("Removing orphan LDAP user: %s", user.email)
                self.db.delete(user)
                removed += 1
        if removed:
            self.db.commit()
        return removed
