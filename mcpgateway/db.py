# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/db.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Gateway Database Models.
This module defines SQLAlchemy models for storing MCP entities including:
- Tools with input schema validation
- Resources with subscription tracking
- Prompts with argument templates
- Federated gateways with capability tracking
- Updated to record server associations independently using many-to-many relationships,
- and to record tool execution metrics.

Examples:
    >>> from mcpgateway.db import connect_args
    >>> isinstance(connect_args, dict)
    True
    >>> 'keepalives' in connect_args or 'check_same_thread' in connect_args or len(connect_args) == 0
    True
"""

# Standard
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, cast, Dict, Generator, List, Optional, TYPE_CHECKING
import uuid

# Third-Party
import jsonschema
from sqlalchemy import Boolean, Column, create_engine, DateTime, event, Float, ForeignKey, func, Index, Integer, JSON, make_url, select, String, Table, Text, UniqueConstraint
from sqlalchemy.event import listen
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session, sessionmaker
from sqlalchemy.orm.attributes import get_history
from sqlalchemy.pool import QueuePool

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.db_isready import wait_for_db_ready

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # First-Party
    from mcpgateway.common.models import ResourceContent

# ResourceContent will be imported locally where needed to avoid circular imports
# EmailUser models moved to this file to avoid circular imports

# ---------------------------------------------------------------------------
# 1. Parse the URL so we can inspect backend ("postgresql", "sqlite", ...)
#    and the specific driver ("psycopg2", "asyncpg", empty string = default).
# ---------------------------------------------------------------------------
url = make_url(settings.database_url)
backend = url.get_backend_name()  # e.g. 'postgresql', 'sqlite'
driver = url.get_driver_name() or "default"

# Start with an empty dict and add options only when the driver can accept
# them; this prevents unexpected TypeError at connect time.
connect_args: dict[str, object] = {}

# ---------------------------------------------------------------------------
# 2. PostgreSQL (synchronous psycopg2 only)
#    The keep-alive parameters below are recognised exclusively by libpq /
#    psycopg2 and let the kernel detect broken network links quickly.
# ---------------------------------------------------------------------------
if backend == "postgresql" and driver in ("psycopg2", "default", ""):
    connect_args.update(
        keepalives=1,  # enable TCP keep-alive probes
        keepalives_idle=30,  # seconds of idleness before first probe
        keepalives_interval=5,  # seconds between probes
        keepalives_count=5,  # drop the link after N failed probes
    )

# ---------------------------------------------------------------------------
# 3. SQLite (optional) - only one extra flag and it is *SQLite-specific*.
# ---------------------------------------------------------------------------
elif backend == "sqlite":
    # Allow pooled connections to hop across threads.
    connect_args["check_same_thread"] = False

# 4. Other backends (MySQL, MSSQL, etc.) leave `connect_args` empty.

# ---------------------------------------------------------------------------
# 5. Build the Engine with a single, clean connect_args mapping.
# ---------------------------------------------------------------------------
if backend == "sqlite":
    # SQLite supports connection pooling with proper configuration
    # For SQLite, we use a smaller pool size since it's file-based
    sqlite_pool_size = min(settings.db_pool_size, 50)  # Cap at 50 for SQLite
    sqlite_max_overflow = min(settings.db_max_overflow, 20)  # Cap at 20 for SQLite

    logger.info("Configuring SQLite with pool_size=%s, max_overflow=%s", sqlite_pool_size, sqlite_max_overflow)

    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,  # quick liveness check per checkout
        pool_size=sqlite_pool_size,
        max_overflow=sqlite_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        # SQLite specific optimizations
        poolclass=QueuePool,  # Explicit pool class
        connect_args=connect_args,
        # Log pool events in debug mode
        echo_pool=settings.log_level == "DEBUG",
    )
else:
    # Other databases support full pooling configuration
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,  # quick liveness check per checkout
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        connect_args=connect_args,
    )

# Initialize SQLAlchemy instrumentation for observability
if settings.observability_enabled:
    try:
        # First-Party
        from mcpgateway.instrumentation import instrument_sqlalchemy

        instrument_sqlalchemy(engine)
        logger.info("SQLAlchemy instrumentation enabled for observability")
    except ImportError:
        logger.warning("Failed to import SQLAlchemy instrumentation")


# ---------------------------------------------------------------------------
# 6. Function to return UTC timestamp
# ---------------------------------------------------------------------------
def utc_now() -> datetime:
    """Return the current Coordinated Universal Time (UTC).

    Returns:
        datetime: A timezone-aware `datetime` whose `tzinfo` is
        `datetime.timezone.utc`.

    Examples:
        >>> from mcpgateway.db import utc_now
        >>> now = utc_now()
        >>> now.tzinfo is not None
        True
        >>> str(now.tzinfo)
        'UTC'
        >>> isinstance(now, datetime)
        True
    """
    return datetime.now(timezone.utc)


# Configure SQLite for better concurrency if using SQLite
if backend == "sqlite":

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, _connection_record):
        """Set SQLite pragmas for better concurrency.

        This is critical for running with multiple gunicorn workers.
        WAL mode allows multiple readers and a single writer concurrently.

        Args:
            dbapi_conn: The raw DBAPI connection.
            _connection_record: A SQLAlchemy-specific object that maintains
                information about the connection's context.
        """
        cursor = dbapi_conn.cursor()
        # Enable WAL mode for better concurrency
        cursor.execute("PRAGMA journal_mode=WAL")
        # Set busy timeout to 30 seconds (30000 ms) to handle lock contention from observability
        cursor.execute("PRAGMA busy_timeout=30000")
        # Synchronous=NORMAL is safe with WAL mode and improves performance
        cursor.execute("PRAGMA synchronous=NORMAL")
        # Increase cache size for better performance (negative value = KB)
        cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
        cursor.close()


# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def refresh_slugs_on_startup():
    """Refresh slugs for all gateways and names of tools on startup."""

    with cast(Any, SessionLocal)() as session:
        gateways = session.query(Gateway).all()
        updated = False
        for gateway in gateways:
            new_slug = slugify(gateway.name)
            if gateway.slug != new_slug:
                gateway.slug = new_slug
                updated = True
        if updated:
            session.commit()

        tools = session.query(Tool).all()
        for tool in tools:
            session.expire(tool, ["gateway"])

        updated = False
        for tool in tools:
            if tool.gateway:
                new_name = f"{tool.gateway.slug}{settings.gateway_tool_name_separator}{slugify(tool.original_name)}"
            else:
                new_name = slugify(tool.original_name)
            if tool.name != new_name:
                tool.name = new_name
                updated = True
        if updated:
            session.commit()


class Base(DeclarativeBase):
    """Base class for all models."""


# ---------------------------------------------------------------------------
# RBAC Models - SQLAlchemy Database Models
# ---------------------------------------------------------------------------


class Role(Base):
    """Role model for RBAC system."""

    __tablename__ = "roles"

    # Primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Role metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)  # 'global', 'team', 'personal'

    # Permissions and inheritance
    permissions: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    inherits_from: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("roles.id"), nullable=True)

    # Metadata
    created_by: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=False)
    is_system_role: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    # Relationships
    parent_role: Mapped[Optional["Role"]] = relationship("Role", remote_side=[id], backref="child_roles")
    user_assignments: Mapped[List["UserRole"]] = relationship("UserRole", back_populates="role", cascade="all, delete-orphan")

    def get_effective_permissions(self) -> List[str]:
        """Get all permissions including inherited ones.

        Returns:
            List of permission strings including inherited permissions
        """
        effective_permissions = set(self.permissions)
        if self.parent_role:
            effective_permissions.update(self.parent_role.get_effective_permissions())
        return sorted(list(effective_permissions))


class UserRole(Base):
    """User role assignment model."""

    __tablename__ = "user_roles"

    # Primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Assignment details
    user_email: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=False)
    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("roles.id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)  # 'global', 'team', 'personal'
    scope_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)  # Team ID if team-scoped

    # Grant metadata
    granted_by: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    role: Mapped["Role"] = relationship("Role", back_populates="user_assignments")

    def is_expired(self) -> bool:
        """Check if the role assignment has expired.

        Returns:
            True if assignment has expired, False otherwise
        """
        if not self.expires_at:
            return False
        return utc_now() > self.expires_at


class PermissionAuditLog(Base):
    """Permission audit log model."""

    __tablename__ = "permission_audit_log"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Audit metadata
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Permission details
    permission: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    team_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    # Result
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    roles_checked: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)

    # Request metadata
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)  # IPv6 max length
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# Permission constants for the system
class Permissions:
    """System permission constants."""

    # User permissions
    USERS_CREATE = "users.create"
    USERS_READ = "users.read"
    USERS_UPDATE = "users.update"
    USERS_DELETE = "users.delete"
    USERS_INVITE = "users.invite"

    # Team permissions
    TEAMS_CREATE = "teams.create"
    TEAMS_READ = "teams.read"
    TEAMS_UPDATE = "teams.update"
    TEAMS_DELETE = "teams.delete"
    TEAMS_JOIN = "teams.join"
    TEAMS_MANAGE_MEMBERS = "teams.manage_members"

    # Tool permissions
    TOOLS_CREATE = "tools.create"
    TOOLS_READ = "tools.read"
    TOOLS_UPDATE = "tools.update"
    TOOLS_DELETE = "tools.delete"
    TOOLS_EXECUTE = "tools.execute"

    # Resource permissions
    RESOURCES_CREATE = "resources.create"
    RESOURCES_READ = "resources.read"
    RESOURCES_UPDATE = "resources.update"
    RESOURCES_DELETE = "resources.delete"
    RESOURCES_SHARE = "resources.share"

    # Prompt permissions
    PROMPTS_CREATE = "prompts.create"
    PROMPTS_READ = "prompts.read"
    PROMPTS_UPDATE = "prompts.update"
    PROMPTS_DELETE = "prompts.delete"
    PROMPTS_EXECUTE = "prompts.execute"

    # Server permissions
    SERVERS_CREATE = "servers.create"
    SERVERS_READ = "servers.read"
    SERVERS_UPDATE = "servers.update"
    SERVERS_DELETE = "servers.delete"
    SERVERS_MANAGE = "servers.manage"

    # Token permissions
    TOKENS_CREATE = "tokens.create"
    TOKENS_READ = "tokens.read"
    TOKENS_REVOKE = "tokens.revoke"
    TOKENS_SCOPE = "tokens.scope"

    # Admin permissions
    ADMIN_SYSTEM_CONFIG = "admin.system_config"
    ADMIN_USER_MANAGEMENT = "admin.user_management"
    ADMIN_SECURITY_AUDIT = "admin.security_audit"

    # Special permissions
    ALL_PERMISSIONS = "*"  # Wildcard for all permissions

    @classmethod
    def get_all_permissions(cls) -> List[str]:
        """Get list of all defined permissions.

        Returns:
            List of all permission strings defined in the class
        """
        permissions = []
        for attr_name in dir(cls):
            if not attr_name.startswith("_") and attr_name.isupper() and attr_name != "ALL_PERMISSIONS":
                attr_value = getattr(cls, attr_name)
                if isinstance(attr_value, str) and "." in attr_value:
                    permissions.append(attr_value)
        return sorted(permissions)

    @classmethod
    def get_permissions_by_resource(cls) -> Dict[str, List[str]]:
        """Get permissions organized by resource type.

        Returns:
            Dictionary mapping resource types to their permissions
        """
        resource_permissions = {}
        for permission in cls.get_all_permissions():
            resource_type = permission.split(".")[0]
            if resource_type not in resource_permissions:
                resource_permissions[resource_type] = []
            resource_permissions[resource_type].append(permission)
        return resource_permissions


# ---------------------------------------------------------------------------
# Email-based User Authentication Models
# ---------------------------------------------------------------------------


class EmailUser(Base):
    """Email-based user model for authentication.

    This model provides email-based authentication as the foundation
    for all multi-user features. Users are identified by email addresses
    instead of usernames.

    Attributes:
        email (str): Primary key, unique email identifier
        password_hash (str): Argon2id hashed password
        full_name (str): Optional display name for professional appearance
        is_admin (bool): Admin privileges flag
        is_active (bool): Account status flag
        auth_provider (str): Authentication provider ('local', 'github', etc.)
        password_hash_type (str): Type of password hash used
        failed_login_attempts (int): Count of failed login attempts
        locked_until (datetime): Account lockout expiration
        created_at (datetime): Account creation timestamp
        updated_at (datetime): Last account update timestamp
        last_login (datetime): Last successful login timestamp
        email_verified_at (datetime): Email verification timestamp

    Examples:
        >>> user = EmailUser(
        ...     email="alice@example.com",
        ...     password_hash="$argon2id$v=19$m=65536,t=3,p=1$...",
        ...     full_name="Alice Smith",
        ...     is_admin=False
        ... )
        >>> user.email
        'alice@example.com'
        >>> user.is_email_verified()
        False
        >>> user.is_account_locked()
        False
    """

    __tablename__ = "email_users"

    # Core identity fields
    email: Mapped[str] = mapped_column(String(255), primary_key=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Status fields
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Security fields
    auth_provider: Mapped[str] = mapped_column(String(50), default="local", nullable=False)
    password_hash_type: Mapped[str] = mapped_column(String(20), default="argon2id", nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        """String representation of the user.

        Returns:
            str: String representation of EmailUser instance
        """
        return f"<EmailUser(email='{self.email}', full_name='{self.full_name}', is_admin={self.is_admin})>"

    def is_email_verified(self) -> bool:
        """Check if the user's email is verified.

        Returns:
            bool: True if email is verified, False otherwise

        Examples:
            >>> user = EmailUser(email="test@example.com")
            >>> user.is_email_verified()
            False
            >>> user.email_verified_at = utc_now()
            >>> user.is_email_verified()
            True
        """
        return self.email_verified_at is not None

    def is_account_locked(self) -> bool:
        """Check if the account is currently locked.

        Returns:
            bool: True if account is locked, False otherwise

        Examples:
            >>> from datetime import timedelta
            >>> user = EmailUser(email="test@example.com")
            >>> user.is_account_locked()
            False
            >>> user.locked_until = utc_now() + timedelta(hours=1)
            >>> user.is_account_locked()
            True
        """
        if self.locked_until is None:
            return False
        return utc_now() < self.locked_until

    def get_display_name(self) -> str:
        """Get the user's display name.

        Returns the full_name if available, otherwise extracts
        the local part from the email address.

        Returns:
            str: Display name for the user

        Examples:
            >>> user = EmailUser(email="john@example.com", full_name="John Doe")
            >>> user.get_display_name()
            'John Doe'
            >>> user_no_name = EmailUser(email="jane@example.com")
            >>> user_no_name.get_display_name()
            'jane'
        """
        if self.full_name:
            return self.full_name
        return self.email.split("@")[0]

    def reset_failed_attempts(self) -> None:
        """Reset failed login attempts counter.

        Called after successful authentication to reset the
        failed attempts counter and clear any account lockout.

        Examples:
            >>> user = EmailUser(email="test@example.com", failed_login_attempts=3)
            >>> user.reset_failed_attempts()
            >>> user.failed_login_attempts
            0
            >>> user.locked_until is None
            True
        """
        self.failed_login_attempts = 0
        self.locked_until = None
        self.last_login = utc_now()

    def increment_failed_attempts(self, max_attempts: int = 5, lockout_duration_minutes: int = 30) -> bool:
        """Increment failed login attempts and potentially lock account.

        Args:
            max_attempts: Maximum allowed failed attempts before lockout
            lockout_duration_minutes: Duration of lockout in minutes

        Returns:
            bool: True if account is now locked, False otherwise

        Examples:
            >>> user = EmailUser(email="test@example.com", password_hash="test", failed_login_attempts=0)
            >>> user.increment_failed_attempts(max_attempts=3)
            False
            >>> user.failed_login_attempts
            1
            >>> for _ in range(2):
            ...     user.increment_failed_attempts(max_attempts=3)
            False
            True
            >>> user.is_account_locked()
            True
        """
        self.failed_login_attempts += 1

        if self.failed_login_attempts >= max_attempts:
            self.locked_until = utc_now() + timedelta(minutes=lockout_duration_minutes)
            return True

        return False

    # Team relationships
    team_memberships: Mapped[List["EmailTeamMember"]] = relationship("EmailTeamMember", foreign_keys="EmailTeamMember.user_email", back_populates="user")
    created_teams: Mapped[List["EmailTeam"]] = relationship("EmailTeam", foreign_keys="EmailTeam.created_by", back_populates="creator")
    sent_invitations: Mapped[List["EmailTeamInvitation"]] = relationship("EmailTeamInvitation", foreign_keys="EmailTeamInvitation.invited_by", back_populates="inviter")

    # API token relationships
    api_tokens: Mapped[List["EmailApiToken"]] = relationship("EmailApiToken", back_populates="user", cascade="all, delete-orphan")

    def get_teams(self) -> List["EmailTeam"]:
        """Get all teams this user is a member of.

        Returns:
            List[EmailTeam]: List of teams the user belongs to

        Examples:
            >>> user = EmailUser(email="user@example.com")
            >>> teams = user.get_teams()
            >>> isinstance(teams, list)
            True
        """
        return [membership.team for membership in self.team_memberships if membership.is_active]

    def get_personal_team(self) -> Optional["EmailTeam"]:
        """Get the user's personal team.

        Returns:
            EmailTeam: The user's personal team or None if not found

        Examples:
            >>> user = EmailUser(email="user@example.com")
            >>> personal_team = user.get_personal_team()
        """
        for team in self.created_teams:
            if team.is_personal and team.is_active:
                return team
        return None

    def is_team_member(self, team_id: str) -> bool:
        """Check if user is a member of the specified team.

        Args:
            team_id: ID of the team to check

        Returns:
            bool: True if user is a member, False otherwise

        Examples:
            >>> user = EmailUser(email="user@example.com")
            >>> user.is_team_member("team-123")
            False
        """
        return any(membership.team_id == team_id and membership.is_active for membership in self.team_memberships)

    def get_team_role(self, team_id: str) -> Optional[str]:
        """Get user's role in a specific team.

        Args:
            team_id: ID of the team to check

        Returns:
            str: User's role or None if not a member

        Examples:
            >>> user = EmailUser(email="user@example.com")
            >>> role = user.get_team_role("team-123")
        """
        for membership in self.team_memberships:
            if membership.team_id == team_id and membership.is_active:
                return membership.role
        return None


class EmailAuthEvent(Base):
    """Authentication event logging for email users.

    This model tracks all authentication attempts for auditing,
    security monitoring, and compliance purposes.

    Attributes:
        id (int): Primary key
        timestamp (datetime): Event timestamp
        user_email (str): Email of the user
        event_type (str): Type of authentication event
        success (bool): Whether the authentication was successful
        ip_address (str): Client IP address
        user_agent (str): Client user agent string
        failure_reason (str): Reason for authentication failure
        details (dict): Additional event details as JSON

    Examples:
        >>> event = EmailAuthEvent(
        ...     user_email="alice@example.com",
        ...     event_type="login",
        ...     success=True,
        ...     ip_address="192.168.1.100"
        ... )
        >>> event.event_type
        'login'
        >>> event.success
        True
    """

    __tablename__ = "email_auth_events"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Event details
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Client information
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)  # IPv6 compatible
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Failure information
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string

    def __repr__(self) -> str:
        """String representation of the auth event.

        Returns:
            str: String representation of EmailAuthEvent instance
        """
        return f"<EmailAuthEvent(user_email='{self.user_email}', event_type='{self.event_type}', success={self.success})>"

    @classmethod
    def create_login_attempt(
        cls,
        user_email: str,
        success: bool,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        failure_reason: Optional[str] = None,
    ) -> "EmailAuthEvent":
        """Create a login attempt event.

        Args:
            user_email: Email address of the user
            success: Whether the login was successful
            ip_address: Client IP address
            user_agent: Client user agent
            failure_reason: Reason for failure (if applicable)

        Returns:
            EmailAuthEvent: New authentication event

        Examples:
            >>> event = EmailAuthEvent.create_login_attempt(
            ...     user_email="user@example.com",
            ...     success=True,
            ...     ip_address="192.168.1.1"
            ... )
            >>> event.event_type
            'login'
            >>> event.success
            True
        """
        return cls(user_email=user_email, event_type="login", success=success, ip_address=ip_address, user_agent=user_agent, failure_reason=failure_reason)

    @classmethod
    def create_registration_event(
        cls,
        user_email: str,
        success: bool,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        failure_reason: Optional[str] = None,
    ) -> "EmailAuthEvent":
        """Create a registration event.

        Args:
            user_email: Email address of the user
            success: Whether the registration was successful
            ip_address: Client IP address
            user_agent: Client user agent
            failure_reason: Reason for failure (if applicable)

        Returns:
            EmailAuthEvent: New authentication event
        """
        return cls(user_email=user_email, event_type="registration", success=success, ip_address=ip_address, user_agent=user_agent, failure_reason=failure_reason)

    @classmethod
    def create_password_change_event(
        cls,
        user_email: str,
        success: bool,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> "EmailAuthEvent":
        """Create a password change event.

        Args:
            user_email: Email address of the user
            success: Whether the password change was successful
            ip_address: Client IP address
            user_agent: Client user agent

        Returns:
            EmailAuthEvent: New authentication event
        """
        return cls(user_email=user_email, event_type="password_change", success=success, ip_address=ip_address, user_agent=user_agent)


class EmailTeam(Base):
    """Email-based team model for multi-team collaboration.

    This model represents teams that users can belong to, with automatic
    personal team creation and role-based access control.

    Attributes:
        id (str): Primary key UUID
        name (str): Team display name
        slug (str): URL-friendly team identifier
        description (str): Team description
        created_by (str): Email of the user who created the team
        is_personal (bool): Whether this is a personal team
        visibility (str): Team visibility (private, public)
        max_members (int): Maximum number of team members allowed
        created_at (datetime): Team creation timestamp
        updated_at (datetime): Last update timestamp
        is_active (bool): Whether the team is active

    Examples:
        >>> team = EmailTeam(
        ...     name="Engineering Team",
        ...     slug="engineering-team",
        ...     created_by="admin@example.com",
        ...     is_personal=False
        ... )
        >>> team.name
        'Engineering Team'
        >>> team.is_personal
        False
    """

    __tablename__ = "email_teams"

    # Primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)

    # Basic team information
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=False)

    # Team settings
    is_personal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), default="public", nullable=False)
    max_members: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    members: Mapped[List["EmailTeamMember"]] = relationship("EmailTeamMember", back_populates="team", cascade="all, delete-orphan")
    invitations: Mapped[List["EmailTeamInvitation"]] = relationship("EmailTeamInvitation", back_populates="team", cascade="all, delete-orphan")
    api_tokens: Mapped[List["EmailApiToken"]] = relationship("EmailApiToken", back_populates="team", cascade="all, delete-orphan")
    creator: Mapped["EmailUser"] = relationship("EmailUser", foreign_keys=[created_by])

    def __repr__(self) -> str:
        """String representation of the team.

        Returns:
            str: String representation of EmailTeam instance
        """
        return f"<EmailTeam(id='{self.id}', name='{self.name}', is_personal={self.is_personal})>"

    def get_member_count(self) -> int:
        """Get the current number of team members.

        Returns:
            int: Number of active team members

        Examples:
            >>> team = EmailTeam(name="Test Team", slug="test-team", created_by="admin@example.com")
            >>> team.get_member_count()
            0
        """
        return len([m for m in self.members if m.is_active])

    def is_member(self, user_email: str) -> bool:
        """Check if a user is a member of this team.

        Args:
            user_email: Email address to check

        Returns:
            bool: True if user is an active member, False otherwise

        Examples:
            >>> team = EmailTeam(name="Test Team", slug="test-team", created_by="admin@example.com")
            >>> team.is_member("admin@example.com")
            False
        """
        return any(m.user_email == user_email and m.is_active for m in self.members)

    def get_member_role(self, user_email: str) -> Optional[str]:
        """Get the role of a user in this team.

        Args:
            user_email: Email address to check

        Returns:
            str: User's role or None if not a member

        Examples:
            >>> team = EmailTeam(name="Test Team", slug="test-team", created_by="admin@example.com")
            >>> team.get_member_role("admin@example.com")
        """
        for member in self.members:
            if member.user_email == user_email and member.is_active:
                return member.role
        return None


class EmailTeamMember(Base):
    """Team membership model linking users to teams with roles.

    This model represents the many-to-many relationship between users and teams
    with additional role information and audit trails.

    Attributes:
        id (str): Primary key UUID
        team_id (str): Foreign key to email_teams
        user_email (str): Foreign key to email_users
        role (str): Member role (owner, member)
        joined_at (datetime): When the user joined the team
        invited_by (str): Email of the user who invited this member
        is_active (bool): Whether the membership is active

    Examples:
        >>> member = EmailTeamMember(
        ...     team_id="team-123",
        ...     user_email="user@example.com",
        ...     role="member",
        ...     invited_by="admin@example.com"
        ... )
        >>> member.role
        'member'
    """

    __tablename__ = "email_team_members"

    # Primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)

    # Foreign keys
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("email_teams.id", ondelete="CASCADE"), nullable=False)
    user_email: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=False)

    # Membership details
    role: Mapped[str] = mapped_column(String(50), default="member", nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    invited_by: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    team: Mapped["EmailTeam"] = relationship("EmailTeam", back_populates="members")
    user: Mapped["EmailUser"] = relationship("EmailUser", foreign_keys=[user_email])
    inviter: Mapped[Optional["EmailUser"]] = relationship("EmailUser", foreign_keys=[invited_by])

    # Unique constraint to prevent duplicate memberships
    __table_args__ = (UniqueConstraint("team_id", "user_email", name="uq_team_member"),)

    def __repr__(self) -> str:
        """String representation of the team member.

        Returns:
            str: String representation of EmailTeamMember instance
        """
        return f"<EmailTeamMember(team_id='{self.team_id}', user_email='{self.user_email}', role='{self.role}')>"


# Team member history model
class EmailTeamMemberHistory(Base):
    """
    History of team member actions (add, remove, reactivate, role change).

    This model records every membership-related event for audit and compliance.
    Each record tracks the team, user, role, action type, actor, and timestamp.

    Attributes:
        id (str): Primary key UUID
        team_id (str): Foreign key to email_teams
        user_email (str): Foreign key to email_users
        role (str): Role at the time of action
        action (str): Action type ("added", "removed", "reactivated", "role_changed")
        action_by (str): Email of the user who performed the action
        action_timestamp (datetime): When the action occurred

    Examples:
        >>> from mcpgateway.db import EmailTeamMemberHistory, utc_now
        >>> history = EmailTeamMemberHistory(
        ...     team_id="team-123",
        ...     user_email="user@example.com",
        ...     role="member",
        ...     action="added",
        ...     action_by="admin@example.com",
        ...     action_timestamp=utc_now()
        ... )
        >>> history.action
        'added'
        >>> history.role
        'member'
        >>> isinstance(history.action_timestamp, type(utc_now()))
        True
    """

    __tablename__ = "email_team_member_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)
    team_member_id: Mapped[str] = mapped_column(String(36), ForeignKey("email_team_members.id"), nullable=False)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("email_teams.id"), nullable=False)
    user_email: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="member", nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "added", "removed", "reactivated", "role_changed"
    action_by: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=True)
    action_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    team_member: Mapped["EmailTeamMember"] = relationship("EmailTeamMember")
    team: Mapped["EmailTeam"] = relationship("EmailTeam")
    user: Mapped["EmailUser"] = relationship("EmailUser", foreign_keys=[user_email])
    actor: Mapped[Optional["EmailUser"]] = relationship("EmailUser", foreign_keys=[action_by])

    def __repr__(self) -> str:
        """
        Return a string representation of the EmailTeamMemberHistory instance.

        Returns:
            str: A string summarizing the team member history record.

        Examples:
            >>> from mcpgateway.db import EmailTeamMemberHistory, utc_now
            >>> history = EmailTeamMemberHistory(
            ...     team_member_id="tm-123",
            ...     team_id="team-123",
            ...     user_email="user@example.com",
            ...     role="member",
            ...     action="added",
            ...     action_by="admin@example.com",
            ...     action_timestamp=utc_now()
            ... )
            >>> isinstance(repr(history), str)
            True
        """
        return f"<EmailTeamMemberHistory(team_member_id='{self.team_member_id}', team_id='{self.team_id}', user_email='{self.user_email}', role='{self.role}', action='{self.action}', action_by='{self.action_by}', action_timestamp='{self.action_timestamp}')>"


class EmailTeamInvitation(Base):
    """Team invitation model for managing team member invitations.

    This model tracks invitations sent to users to join teams, including
    expiration dates and invitation tokens.

    Attributes:
        id (str): Primary key UUID
        team_id (str): Foreign key to email_teams
        email (str): Email address of the invited user
        role (str): Role the user will have when they accept
        invited_by (str): Email of the user who sent the invitation
        invited_at (datetime): When the invitation was sent
        expires_at (datetime): When the invitation expires
        token (str): Unique invitation token
        is_active (bool): Whether the invitation is still active

    Examples:
        >>> invitation = EmailTeamInvitation(
        ...     team_id="team-123",
        ...     email="newuser@example.com",
        ...     role="member",
        ...     invited_by="admin@example.com"
        ... )
        >>> invitation.role
        'member'
    """

    __tablename__ = "email_team_invitations"

    # Primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)

    # Foreign keys
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("email_teams.id", ondelete="CASCADE"), nullable=False)

    # Invitation details
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="member", nullable=False)
    invited_by: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=False)

    # Timing
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Security
    token: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    team: Mapped["EmailTeam"] = relationship("EmailTeam", back_populates="invitations")
    inviter: Mapped["EmailUser"] = relationship("EmailUser", foreign_keys=[invited_by])

    def __repr__(self) -> str:
        """String representation of the team invitation.

        Returns:
            str: String representation of EmailTeamInvitation instance
        """
        return f"<EmailTeamInvitation(team_id='{self.team_id}', email='{self.email}', role='{self.role}')>"

    def is_expired(self) -> bool:
        """Check if the invitation has expired.

        Returns:
            bool: True if the invitation has expired, False otherwise

        Examples:
            >>> from datetime import timedelta
            >>> invitation = EmailTeamInvitation(
            ...     team_id="team-123",
            ...     email="user@example.com",
            ...     role="member",
            ...     invited_by="admin@example.com",
            ...     expires_at=utc_now() + timedelta(days=7)
            ... )
            >>> invitation.is_expired()
            False
        """
        now = utc_now()
        expires_at = self.expires_at

        # Handle timezone awareness mismatch
        if now.tzinfo is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        elif now.tzinfo is None and expires_at.tzinfo is not None:
            now = now.replace(tzinfo=timezone.utc)

        return now > expires_at

    def is_valid(self) -> bool:
        """Check if the invitation is valid (active and not expired).

        Returns:
            bool: True if the invitation is valid, False otherwise

        Examples:
            >>> from datetime import timedelta
            >>> invitation = EmailTeamInvitation(
            ...     team_id="team-123",
            ...     email="user@example.com",
            ...     role="member",
            ...     invited_by="admin@example.com",
            ...     expires_at=utc_now() + timedelta(days=7),
            ...     is_active=True
            ... )
            >>> invitation.is_valid()
            True
        """
        return self.is_active and not self.is_expired()


class EmailTeamJoinRequest(Base):
    """Team join request model for managing public team join requests.

    This model tracks user requests to join public teams, including
    approval workflow and expiration dates.

    Attributes:
        id (str): Primary key UUID
        team_id (str): Foreign key to email_teams
        user_email (str): Email of the user requesting to join
        message (str): Optional message from the user
        status (str): Request status (pending, approved, rejected, expired)
        requested_at (datetime): When the request was made
        expires_at (datetime): When the request expires
        reviewed_at (datetime): When the request was reviewed
        reviewed_by (str): Email of user who reviewed the request
        notes (str): Optional admin notes
    """

    __tablename__ = "email_team_join_requests"

    # Primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)

    # Foreign keys
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("email_teams.id", ondelete="CASCADE"), nullable=False)
    user_email: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=False)

    # Request details
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)

    # Timing
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    team: Mapped["EmailTeam"] = relationship("EmailTeam")
    user: Mapped["EmailUser"] = relationship("EmailUser", foreign_keys=[user_email])
    reviewer: Mapped[Optional["EmailUser"]] = relationship("EmailUser", foreign_keys=[reviewed_by])

    # Unique constraint to prevent duplicate requests
    __table_args__ = (UniqueConstraint("team_id", "user_email", name="uq_team_join_request"),)

    def __repr__(self) -> str:
        """String representation of the team join request.

        Returns:
            str: String representation of the team join request.
        """
        return f"<EmailTeamJoinRequest(team_id='{self.team_id}', user_email='{self.user_email}', status='{self.status}')>"

    def is_expired(self) -> bool:
        """Check if the join request has expired.

        Returns:
            bool: True if the request has expired, False otherwise.
        """
        now = utc_now()
        expires_at = self.expires_at

        # Handle timezone awareness mismatch
        if now.tzinfo is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        elif now.tzinfo is None and expires_at.tzinfo is not None:
            now = now.replace(tzinfo=timezone.utc)

        return now > expires_at

    def is_pending(self) -> bool:
        """Check if the join request is still pending.

        Returns:
            bool: True if the request is pending and not expired, False otherwise.
        """
        return self.status == "pending" and not self.is_expired()


class PendingUserApproval(Base):
    """Model for pending SSO user registrations awaiting admin approval.

    This model stores information about users who have authenticated via SSO
    but require admin approval before their account is fully activated.

    Attributes:
        id (str): Primary key
        email (str): Email address of the pending user
        full_name (str): Full name from SSO provider
        auth_provider (str): SSO provider (github, google, etc.)
        sso_metadata (dict): Additional metadata from SSO provider
        requested_at (datetime): When the approval was requested
        expires_at (datetime): When the approval request expires
        approved_by (str): Email of admin who approved (if approved)
        approved_at (datetime): When the approval was granted
        status (str): Current status (pending, approved, rejected, expired)
        rejection_reason (str): Reason for rejection (if applicable)
        admin_notes (str): Notes from admin review

    Examples:
        >>> from datetime import timedelta
        >>> approval = PendingUserApproval(
        ...     email="newuser@example.com",
        ...     full_name="New User",
        ...     auth_provider="github",
        ...     expires_at=utc_now() + timedelta(days=30),
        ...     status="pending"
        ... )
        >>> approval.status
        'pending'
    """

    __tablename__ = "pending_user_approvals"

    # Primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # User details
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    sso_metadata: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)

    # Request details
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Approval details
    approved_by: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending, approved, rejected, expired
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    admin_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    approver: Mapped[Optional["EmailUser"]] = relationship("EmailUser", foreign_keys=[approved_by])

    def __repr__(self) -> str:
        """String representation of the pending approval.

        Returns:
            str: String representation of PendingUserApproval instance
        """
        return f"<PendingUserApproval(email='{self.email}', status='{self.status}', provider='{self.auth_provider}')>"

    def is_expired(self) -> bool:
        """Check if the approval request has expired.

        Returns:
            bool: True if the approval request has expired
        """
        now = utc_now()
        expires_at = self.expires_at

        # Handle timezone awareness mismatch
        if now.tzinfo is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        elif now.tzinfo is None and expires_at.tzinfo is not None:
            now = now.replace(tzinfo=timezone.utc)

        return now > expires_at

    def approve(self, admin_email: str, notes: Optional[str] = None) -> None:
        """Approve the user registration.

        Args:
            admin_email: Email of the admin approving the request
            notes: Optional admin notes
        """
        self.status = "approved"
        self.approved_by = admin_email
        self.approved_at = utc_now()
        self.admin_notes = notes

    def reject(self, admin_email: str, reason: str, notes: Optional[str] = None) -> None:
        """Reject the user registration.

        Args:
            admin_email: Email of the admin rejecting the request
            reason: Reason for rejection
            notes: Optional admin notes
        """
        self.status = "rejected"
        self.approved_by = admin_email
        self.approved_at = utc_now()
        self.rejection_reason = reason
        self.admin_notes = notes


# Association table for servers and tools
server_tool_association = Table(
    "server_tool_association",
    Base.metadata,
    Column("server_id", String(36), ForeignKey("servers.id"), primary_key=True),
    Column("tool_id", String(36), ForeignKey("tools.id"), primary_key=True),
)

# Association table for servers and resources
server_resource_association = Table(
    "server_resource_association",
    Base.metadata,
    Column("server_id", String(36), ForeignKey("servers.id"), primary_key=True),
    Column("resource_id", Integer, ForeignKey("resources.id"), primary_key=True),
)

# Association table for servers and prompts
server_prompt_association = Table(
    "server_prompt_association",
    Base.metadata,
    Column("server_id", String(36), ForeignKey("servers.id"), primary_key=True),
    Column("prompt_id", Integer, ForeignKey("prompts.id"), primary_key=True),
)

# Association table for servers and A2A agents
server_a2a_association = Table(
    "server_a2a_association",
    Base.metadata,
    Column("server_id", String(36), ForeignKey("servers.id"), primary_key=True),
    Column("a2a_agent_id", String(36), ForeignKey("a2a_agents.id"), primary_key=True),
)


class GlobalConfig(Base):
    """Global configuration settings.

    Attributes:
        id (int): Primary key
        passthrough_headers (List[str]): List of headers allowed to be passed through globally
    """

    __tablename__ = "global_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    passthrough_headers: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)  # Store list of strings as JSON array


class ToolMetric(Base):
    """
    ORM model for recording individual metrics for tool executions.

    Each record in this table corresponds to a single tool invocation and records:
        - timestamp (datetime): When the invocation occurred.
        - response_time (float): The execution time in seconds.
        - is_success (bool): True if the execution succeeded, False otherwise.
        - error_message (Optional[str]): Error message if the execution failed.

    Aggregated metrics (such as total executions, successful/failed counts, failure rate,
    minimum, maximum, and average response times, and last execution time) should be computed
    on the fly using SQL aggregate functions over the rows in this table.
    """

    __tablename__ = "tool_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    tool_id: Mapped[str] = mapped_column(String(36), ForeignKey("tools.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    response_time: Mapped[float] = mapped_column(Float, nullable=False)
    is_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship back to the Tool model.
    tool: Mapped["Tool"] = relationship("Tool", back_populates="metrics")


class ResourceMetric(Base):
    """
    ORM model for recording metrics for resource invocations.

    Attributes:
        id (int): Primary key.
        resource_id (int): Foreign key linking to the resource.
        timestamp (datetime): The time when the invocation occurred.
        response_time (float): The response time in seconds.
        is_success (bool): True if the invocation succeeded, False otherwise.
        error_message (Optional[str]): Error message if the invocation failed.
    """

    __tablename__ = "resource_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(Integer, ForeignKey("resources.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    response_time: Mapped[float] = mapped_column(Float, nullable=False)
    is_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship back to the Resource model.
    resource: Mapped["Resource"] = relationship("Resource", back_populates="metrics")


class ServerMetric(Base):
    """
    ORM model for recording metrics for server invocations.

    Attributes:
        id (int): Primary key.
        server_id (str): Foreign key linking to the server.
        timestamp (datetime): The time when the invocation occurred.
        response_time (float): The response time in seconds.
        is_success (bool): True if the invocation succeeded, False otherwise.
        error_message (Optional[str]): Error message if the invocation failed.
    """

    __tablename__ = "server_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[str] = mapped_column(String(36), ForeignKey("servers.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    response_time: Mapped[float] = mapped_column(Float, nullable=False)
    is_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship back to the Server model.
    server: Mapped["Server"] = relationship("Server", back_populates="metrics")


class PromptMetric(Base):
    """
    ORM model for recording metrics for prompt invocations.

    Attributes:
        id (int): Primary key.
        prompt_id (int): Foreign key linking to the prompt.
        timestamp (datetime): The time when the invocation occurred.
        response_time (float): The response time in seconds.
        is_success (bool): True if the invocation succeeded, False otherwise.
        error_message (Optional[str]): Error message if the invocation failed.
    """

    __tablename__ = "prompt_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    prompt_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompts.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    response_time: Mapped[float] = mapped_column(Float, nullable=False)
    is_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship back to the Prompt model.
    prompt: Mapped["Prompt"] = relationship("Prompt", back_populates="metrics")


class A2AAgentMetric(Base):
    """
    ORM model for recording metrics for A2A agent interactions.

    Attributes:
        id (int): Primary key.
        a2a_agent_id (str): Foreign key linking to the A2A agent.
        timestamp (datetime): The time when the interaction occurred.
        response_time (float): The response time in seconds.
        is_success (bool): True if the interaction succeeded, False otherwise.
        error_message (Optional[str]): Error message if the interaction failed.
        interaction_type (str): Type of interaction (invoke, query, etc.).
    """

    __tablename__ = "a2a_agent_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    a2a_agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("a2a_agents.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    response_time: Mapped[float] = mapped_column(Float, nullable=False)
    is_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    interaction_type: Mapped[str] = mapped_column(String(50), nullable=False, default="invoke")

    # Relationship back to the A2AAgent model.
    a2a_agent: Mapped["A2AAgent"] = relationship("A2AAgent", back_populates="metrics")


# ===================================
# Observability Models (OpenTelemetry-style traces, spans, events)
# ===================================


class ObservabilityTrace(Base):
    """
    ORM model for observability traces (similar to OpenTelemetry traces).

    A trace represents a complete request flow through the system. It contains
    one or more spans representing individual operations.

    Attributes:
        trace_id (str): Unique trace identifier (UUID or OpenTelemetry trace ID format).
        name (str): Human-readable name for the trace (e.g., "POST /tools/invoke").
        start_time (datetime): When the trace started.
        end_time (datetime): When the trace ended (optional, set when completed).
        duration_ms (float): Total duration in milliseconds.
        status (str): Trace status (success, error, timeout).
        status_message (str): Optional status message or error description.
        http_method (str): HTTP method for the request (GET, POST, etc.).
        http_url (str): Full URL of the request.
        http_status_code (int): HTTP response status code.
        user_email (str): User who initiated the request (if authenticated).
        user_agent (str): Client user agent string.
        ip_address (str): Client IP address.
        attributes (dict): Additional trace attributes (JSON).
        resource_attributes (dict): Resource attributes (service name, version, etc.).
        created_at (datetime): Trace creation timestamp.
    """

    __tablename__ = "observability_traces"

    # Primary key
    trace_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Trace metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unset")  # unset, ok, error
    status_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # HTTP request context
    http_method: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    http_url: Mapped[Optional[str]] = mapped_column(String(767), nullable=True)
    http_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # User context
    user_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    # Attributes (flexible key-value storage)
    attributes: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, default=dict)
    resource_attributes: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, default=dict)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    spans: Mapped[List["ObservabilitySpan"]] = relationship("ObservabilitySpan", back_populates="trace", cascade="all, delete-orphan")

    # Indexes for performance
    __table_args__ = (
        Index("idx_observability_traces_start_time", "start_time"),
        Index("idx_observability_traces_user_email", "user_email"),
        Index("idx_observability_traces_status", "status"),
        Index("idx_observability_traces_http_status_code", "http_status_code"),
    )


class ObservabilitySpan(Base):
    """
    ORM model for observability spans (similar to OpenTelemetry spans).

    A span represents a single operation within a trace. Spans can be nested
    to represent hierarchical operations.

    Attributes:
        span_id (str): Unique span identifier.
        trace_id (str): Parent trace ID.
        parent_span_id (str): Parent span ID (for nested spans).
        name (str): Span name (e.g., "database_query", "tool_invocation").
        kind (str): Span kind (internal, server, client, producer, consumer).
        start_time (datetime): When the span started.
        end_time (datetime): When the span ended.
        duration_ms (float): Span duration in milliseconds.
        status (str): Span status (success, error).
        status_message (str): Optional status message.
        attributes (dict): Span attributes (JSON).
        resource_name (str): Name of the resource being operated on.
        resource_type (str): Type of resource (tool, resource, prompt, gateway, etc.).
        resource_id (str): ID of the specific resource.
        created_at (datetime): Span creation timestamp.
    """

    __tablename__ = "observability_spans"

    # Primary key
    span_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Trace relationship
    trace_id: Mapped[str] = mapped_column(String(36), ForeignKey("observability_traces.trace_id", ondelete="CASCADE"), nullable=False, index=True)
    parent_span_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("observability_spans.span_id", ondelete="CASCADE"), nullable=True, index=True)

    # Span metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="internal")  # internal, server, client, producer, consumer
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unset")
    status_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Attributes
    attributes: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, default=dict)

    # Resource context
    resource_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)  # tool, resource, prompt, gateway, a2a_agent
    resource_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    trace: Mapped["ObservabilityTrace"] = relationship("ObservabilityTrace", back_populates="spans")
    parent_span: Mapped[Optional["ObservabilitySpan"]] = relationship("ObservabilitySpan", remote_side=[span_id], backref="child_spans")
    events: Mapped[List["ObservabilityEvent"]] = relationship("ObservabilityEvent", back_populates="span", cascade="all, delete-orphan")

    # Indexes for performance
    __table_args__ = (
        Index("idx_observability_spans_trace_id", "trace_id"),
        Index("idx_observability_spans_parent_span_id", "parent_span_id"),
        Index("idx_observability_spans_start_time", "start_time"),
        Index("idx_observability_spans_resource_type", "resource_type"),
        Index("idx_observability_spans_resource_name", "resource_name"),
    )


class ObservabilityEvent(Base):
    """
    ORM model for observability events (logs within spans).

    Events represent discrete occurrences within a span, such as log messages,
    exceptions, or state changes.

    Attributes:
        id (int): Auto-incrementing primary key.
        span_id (str): Parent span ID.
        name (str): Event name (e.g., "exception", "log", "checkpoint").
        timestamp (datetime): When the event occurred.
        attributes (dict): Event attributes (JSON).
        severity (str): Log severity level (debug, info, warning, error, critical).
        message (str): Event message.
        exception_type (str): Exception class name (if event is an exception).
        exception_message (str): Exception message.
        exception_stacktrace (str): Exception stacktrace.
        created_at (datetime): Event creation timestamp.
    """

    __tablename__ = "observability_events"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Span relationship
    span_id: Mapped[str] = mapped_column(String(36), ForeignKey("observability_spans.span_id", ondelete="CASCADE"), nullable=False, index=True)

    # Event metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    attributes: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, default=dict)

    # Log fields
    severity: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)  # debug, info, warning, error, critical
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Exception fields
    exception_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    exception_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exception_stacktrace: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    span: Mapped["ObservabilitySpan"] = relationship("ObservabilitySpan", back_populates="events")

    # Indexes for performance
    __table_args__ = (
        Index("idx_observability_events_span_id", "span_id"),
        Index("idx_observability_events_timestamp", "timestamp"),
        Index("idx_observability_events_severity", "severity"),
    )


class ObservabilityMetric(Base):
    """
    ORM model for observability metrics (time-series numerical data).

    Metrics represent numerical measurements over time, such as request rates,
    error rates, latencies, and custom business metrics.

    Attributes:
        id (int): Auto-incrementing primary key.
        name (str): Metric name (e.g., "http.request.duration", "tool.invocation.count").
        metric_type (str): Metric type (counter, gauge, histogram).
        value (float): Metric value.
        timestamp (datetime): When the metric was recorded.
        unit (str): Metric unit (ms, count, bytes, etc.).
        attributes (dict): Metric attributes/labels (JSON).
        resource_type (str): Type of resource (tool, resource, prompt, etc.).
        resource_id (str): ID of the specific resource.
        trace_id (str): Associated trace ID (optional).
        created_at (datetime): Metric creation timestamp.
    """

    __tablename__ = "observability_metrics"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Metric metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    metric_type: Mapped[str] = mapped_column(String(20), nullable=False)  # counter, gauge, histogram
    value: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    unit: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Attributes/labels
    attributes: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, default=dict)

    # Resource context
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

    # Trace association (optional)
    trace_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("observability_traces.trace_id", ondelete="SET NULL"), nullable=True, index=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Indexes for performance
    __table_args__ = (
        Index("idx_observability_metrics_name_timestamp", "name", "timestamp"),
        Index("idx_observability_metrics_resource_type", "resource_type"),
        Index("idx_observability_metrics_trace_id", "trace_id"),
    )


class ObservabilitySavedQuery(Base):
    """
    ORM model for saved observability queries (filter presets).

    Allows users to save their filter configurations for quick access and
    historical query tracking. Queries can be personal or shared with the team.

    Attributes:
        id (int): Auto-incrementing primary key.
        name (str): User-given name for the saved query.
        description (str): Optional description of what this query finds.
        user_email (str): Email of the user who created this query.
        filter_config (dict): JSON containing all filter values (time_range, status_filter, etc.).
        is_shared (bool): Whether this query is visible to other users.
        created_at (datetime): When the query was created.
        updated_at (datetime): When the query was last modified.
        last_used_at (datetime): When the query was last executed.
        use_count (int): How many times this query has been used.
    """

    __tablename__ = "observability_saved_queries"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Query metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Filter configuration (stored as JSON)
    filter_config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Sharing settings
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Timestamps and usage tracking
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Indexes for performance
    __table_args__ = (
        Index("idx_observability_saved_queries_user_email", "user_email"),
        Index("idx_observability_saved_queries_is_shared", "is_shared"),
        Index("idx_observability_saved_queries_created_at", "created_at"),
    )


class Tool(Base):
    """
    ORM model for a registered Tool.

    Supports both local tools and federated tools from other gateways.
    The integration_type field indicates the tool format:
    - "MCP" for MCP-compliant tools (default)
    - "REST" for REST tools

    Additionally, this model provides computed properties for aggregated metrics based
    on the associated ToolMetric records. These include:
        - execution_count: Total number of invocations.
        - successful_executions: Count of successful invocations.
        - failed_executions: Count of failed invocations.
        - failure_rate: Ratio of failed invocations to total invocations.
        - min_response_time: Fastest recorded response time.
        - max_response_time: Slowest recorded response time.
        - avg_response_time: Mean response time.
        - last_execution_time: Timestamp of the most recent invocation.

    The property `metrics_summary` returns a dictionary with these aggregated values.

    The following fields have been added to support tool invocation configuration:
        - request_type: HTTP method to use when invoking the tool.
        - auth_type: Type of authentication ("basic", "bearer", or None).
        - auth_username: Username for basic authentication.
        - auth_password: Password for basic authentication.
        - auth_token: Token for bearer token authentication.
        - auth_header_key: header key for authentication.
        - auth_header_value: header value for authentication.
    """

    __tablename__ = "tools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(767), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    integration_type: Mapped[str] = mapped_column(String(20), default="MCP")
    request_type: Mapped[str] = mapped_column(String(20), default="SSE")
    headers: Mapped[Optional[Dict[str, str]]] = mapped_column(JSON)
    input_schema: Mapped[Dict[str, Any]] = mapped_column(JSON)
    output_schema: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    annotations: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=lambda: {})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    enabled: Mapped[bool] = mapped_column(default=True)
    reachable: Mapped[bool] = mapped_column(default=True)
    jsonpath_filter: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)

    # Comprehensive metadata for audit tracking
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_from_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_via: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    modified_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    modified_from_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    modified_via: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    modified_user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    import_batch_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    federation_source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Request type and authentication fields
    auth_type: Mapped[Optional[str]] = mapped_column(String(20), default=None)  # "basic", "bearer", or None
    auth_value: Mapped[Optional[str]] = mapped_column(Text, default=None)

    # custom_name,custom_name_slug, display_name
    custom_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=False)
    custom_name_slug: Mapped[Optional[str]] = mapped_column(String(255), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Passthrough REST fields
    base_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    path_template: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    query_mapping: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    header_mapping: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    timeout_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    expose_passthrough: Mapped[bool] = mapped_column(Boolean, default=True)
    allowlist: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    plugin_chain_pre: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    plugin_chain_post: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    # Federation relationship with a local gateway
    gateway_id: Mapped[Optional[str]] = mapped_column(ForeignKey("gateways.id"))
    # gateway_slug: Mapped[Optional[str]] = mapped_column(ForeignKey("gateways.slug"))
    gateway: Mapped["Gateway"] = relationship("Gateway", primaryjoin="Tool.gateway_id == Gateway.id", foreign_keys=[gateway_id], back_populates="tools")
    # federated_with = relationship("Gateway", secondary=tool_gateway_table, back_populates="federated_tools")

    # Many-to-many relationship with Servers
    servers: Mapped[List["Server"]] = relationship("Server", secondary=server_tool_association, back_populates="tools")

    # Relationship with ToolMetric records
    metrics: Mapped[List["ToolMetric"]] = relationship("ToolMetric", back_populates="tool", cascade="all, delete-orphan")

    # Team scoping fields for resource organization
    team_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("email_teams.id", ondelete="SET NULL"), nullable=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="public")

    # @property
    # def gateway_slug(self) -> str:
    #     return self.gateway.slug

    _computed_name: Mapped[str] = mapped_column("name", String(255), nullable=False)  # Stored column

    @hybrid_property
    def name(self) -> str:
        """Return the display/lookup name computed from gateway and custom slug.

        Returns:
            str: Display/lookup name to use for this tool.
        """
        # Instance access resolves Column to Python value; cast ensures static acceptance
        if getattr(self, "_computed_name", None):
            return cast(str, getattr(self, "_computed_name"))
        custom_name_slug = slugify(getattr(self, "custom_name_slug"))
        if getattr(self, "gateway_id", None):
            gateway_slug = slugify(self.gateway.name)  # type: ignore[attr-defined]
            return f"{gateway_slug}{settings.gateway_tool_name_separator}{custom_name_slug}"
        return custom_name_slug

    @name.setter
    def name(self, value: str) -> None:
        """Setter for the stored name column.

        Args:
            value: Explicit name to persist to the underlying column.
        """
        setattr(self, "_computed_name", value)

    @name.expression
    @classmethod
    def name(cls) -> Any:
        """SQL expression for name used in queries (backs onto stored column).

        Returns:
            Any: SQLAlchemy expression referencing the stored name column.
        """
        return cls._computed_name

    __table_args__ = (UniqueConstraint("gateway_id", "original_name", name="uq_gateway_id__original_name"), UniqueConstraint("team_id", "owner_email", "name", name="uq_team_owner_email_name_tool"))

    @hybrid_property
    def gateway_slug(self) -> Optional[str]:
        """Python accessor returning the related gateway's slug if available.

        Returns:
            Optional[str]: The gateway slug, or None if no gateway relation.
        """
        return self.gateway.slug if self.gateway else None

    @gateway_slug.expression
    @classmethod
    def gateway_slug(cls) -> Any:
        """SQL expression to select current gateway slug for this tool.

        Returns:
            Any: SQLAlchemy scalar subquery selecting the gateway slug.
        """
        return select(Gateway.slug).where(Gateway.id == cls.gateway_id).scalar_subquery()

    @hybrid_property
    def execution_count(self) -> int:
        """Number of ToolMetric records associated with this tool instance.

        Returns:
            int: Count of ToolMetric records for this tool.
        """
        return len(getattr(self, "metrics", []))

    @execution_count.expression
    @classmethod
    def execution_count(cls) -> Any:
        """SQL expression that counts ToolMetric rows for this tool.

        Returns:
            Any: SQLAlchemy labeled count expression for tool metrics.
        """
        return select(func.count(ToolMetric.id)).where(ToolMetric.tool_id == cls.id).label("execution_count")  # pylint: disable=not-callable

    @property
    def successful_executions(self) -> int:
        """
        Returns the count of successful tool executions,
        computed from the associated ToolMetric records.

        Returns:
            int: The count of successful tool executions.
        """
        return sum(1 for m in self.metrics if m.is_success)

    @property
    def failed_executions(self) -> int:
        """
        Returns the count of failed tool executions,
        computed from the associated ToolMetric records.

        Returns:
            int: The count of failed tool executions.
        """
        return sum(1 for m in self.metrics if not m.is_success)

    @property
    def failure_rate(self) -> float:
        """
        Returns the failure rate (as a float between 0 and 1) computed as:
            (failed executions) / (total executions).
        Returns 0.0 if there are no executions.

        Returns:
            float: The failure rate as a value between 0 and 1.
        """
        total: int = self.execution_count
        # execution_count is a @hybrid_property, not a callable here
        if total == 0:  # pylint: disable=comparison-with-callable
            return 0.0
        return self.failed_executions / total

    @property
    def min_response_time(self) -> Optional[float]:
        """
        Returns the minimum response time among all tool executions.
        Returns None if no executions exist.

        Returns:
            Optional[float]: The minimum response time, or None if no executions exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return min(times) if times else None

    @property
    def max_response_time(self) -> Optional[float]:
        """
        Returns the maximum response time among all tool executions.
        Returns None if no executions exist.

        Returns:
            Optional[float]: The maximum response time, or None if no executions exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return max(times) if times else None

    @property
    def avg_response_time(self) -> Optional[float]:
        """
        Returns the average response time among all tool executions.
        Returns None if no executions exist.

        Returns:
            Optional[float]: The average response time, or None if no executions exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return sum(times) / len(times) if times else None

    @property
    def last_execution_time(self) -> Optional[datetime]:
        """
        Returns the timestamp of the most recent tool execution.
        Returns None if no executions exist.

        Returns:
            Optional[datetime]: The timestamp of the most recent execution, or None if no executions exist.
        """
        if not self.metrics:
            return None
        return max(m.timestamp for m in self.metrics)

    @property
    def metrics_summary(self) -> Dict[str, Any]:
        """
        Returns aggregated metrics for the tool as a dictionary with the following keys:
            - total_executions: Total number of invocations.
            - successful_executions: Number of successful invocations.
            - failed_executions: Number of failed invocations.
            - failure_rate: Failure rate (failed/total) or 0.0 if no invocations.
            - min_response_time: Minimum response time (or None if no invocations).
            - max_response_time: Maximum response time (or None if no invocations).
            - avg_response_time: Average response time (or None if no invocations).
            - last_execution_time: Timestamp of the most recent invocation (or None).

        Returns:
            Dict[str, Any]: Dictionary containing the aggregated metrics.
        """
        return {
            "total_executions": self.execution_count,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "failure_rate": self.failure_rate,
            "min_response_time": self.min_response_time,
            "max_response_time": self.max_response_time,
            "avg_response_time": self.avg_response_time,
            "last_execution_time": self.last_execution_time,
        }


class Resource(Base):
    """
    ORM model for a registered Resource.

    Resources represent content that can be read by clients.
    Supports subscriptions for real-time updates.
    Additionally, this model provides a relationship with ResourceMetric records
    to capture invocation metrics (such as execution counts, response times, and failures).
    """

    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    uri: Mapped[str] = mapped_column(String(767), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # URI template for parameterized resources
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    is_active: Mapped[bool] = mapped_column(default=True)
    tags: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)

    # Comprehensive metadata for audit tracking
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_from_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_via: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    modified_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    modified_from_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    modified_via: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    modified_user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    import_batch_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    federation_source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    metrics: Mapped[List["ResourceMetric"]] = relationship("ResourceMetric", back_populates="resource", cascade="all, delete-orphan")

    # Content storage - can be text or binary
    text_content: Mapped[Optional[str]] = mapped_column(Text)
    binary_content: Mapped[Optional[bytes]]

    # Subscription tracking
    subscriptions: Mapped[List["ResourceSubscription"]] = relationship("ResourceSubscription", back_populates="resource", cascade="all, delete-orphan")

    gateway_id: Mapped[Optional[str]] = mapped_column(ForeignKey("gateways.id"))
    gateway: Mapped["Gateway"] = relationship("Gateway", back_populates="resources")
    # federated_with = relationship("Gateway", secondary=resource_gateway_table, back_populates="federated_resources")

    # Many-to-many relationship with Servers
    servers: Mapped[List["Server"]] = relationship("Server", secondary=server_resource_association, back_populates="resources")
    __table_args__ = (UniqueConstraint("team_id", "owner_email", "uri", name="uq_team_owner_uri_resource"),)

    @property
    def content(self) -> "ResourceContent":
        """
        Returns the resource content in the appropriate format.

        If text content exists, returns a ResourceContent with text.
        Otherwise, if binary content exists, returns a ResourceContent with blob data.
        Raises a ValueError if no content is available.

        Returns:
            ResourceContent: The resource content with appropriate format (text or blob).

        Raises:
            ValueError: If the resource has no content available.

        Examples:
            >>> resource = Resource(uri="test://example", name="test")
            >>> resource.text_content = "Hello, World!"
            >>> content = resource.content
            >>> content.text
            'Hello, World!'
            >>> content.type
            'resource'

            >>> binary_resource = Resource(uri="test://binary", name="binary")
            >>> binary_resource.binary_content = b"\\x00\\x01\\x02"
            >>> binary_content = binary_resource.content
            >>> binary_content.blob
            b'\\x00\\x01\\x02'

            >>> empty_resource = Resource(uri="test://empty", name="empty")
            >>> try:
            ...     empty_resource.content
            ... except ValueError as e:
            ...     str(e)
            'Resource has no content'
        """

        # Local import to avoid circular import
        # First-Party
        from mcpgateway.common.models import ResourceContent  # pylint: disable=import-outside-toplevel

        if self.text_content is not None:
            return ResourceContent(
                type="resource",
                id=str(self.id),
                uri=self.uri,
                mime_type=self.mime_type,
                text=self.text_content,
            )
        if self.binary_content is not None:
            return ResourceContent(
                type="resource",
                id=str(self.id),
                uri=self.uri,
                mime_type=self.mime_type or "application/octet-stream",
                blob=self.binary_content,
            )
        raise ValueError("Resource has no content")

    @property
    def execution_count(self) -> int:
        """
        Returns the number of times the resource has been invoked,
        calculated from the associated ResourceMetric records.

        Returns:
            int: The total count of resource invocations.
        """
        return len(self.metrics)

    @property
    def successful_executions(self) -> int:
        """
        Returns the count of successful resource invocations,
        computed from the associated ResourceMetric records.

        Returns:
            int: The count of successful resource invocations.
        """
        return sum(1 for m in self.metrics if m.is_success)

    @property
    def failed_executions(self) -> int:
        """
        Returns the count of failed resource invocations,
        computed from the associated ResourceMetric records.

        Returns:
            int: The count of failed resource invocations.
        """
        return sum(1 for m in self.metrics if not m.is_success)

    @property
    def failure_rate(self) -> float:
        """
        Returns the failure rate (as a float between 0 and 1) computed as:
            (failed invocations) / (total invocations).
        Returns 0.0 if there are no invocations.

        Returns:
            float: The failure rate as a value between 0 and 1.
        """
        total: int = self.execution_count
        if total == 0:
            return 0.0
        return self.failed_executions / total

    @property
    def min_response_time(self) -> Optional[float]:
        """
        Returns the minimum response time among all resource invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The minimum response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return min(times) if times else None

    @property
    def max_response_time(self) -> Optional[float]:
        """
        Returns the maximum response time among all resource invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The maximum response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return max(times) if times else None

    @property
    def avg_response_time(self) -> Optional[float]:
        """
        Returns the average response time among all resource invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The average response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return sum(times) / len(times) if times else None

    @property
    def last_execution_time(self) -> Optional[datetime]:
        """
        Returns the timestamp of the most recent resource invocation.
        Returns None if no invocations exist.

        Returns:
            Optional[datetime]: The timestamp of the most recent invocation, or None if no invocations exist.
        """
        if not self.metrics:
            return None
        return max(m.timestamp for m in self.metrics)

    # Team scoping fields for resource organization
    team_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("email_teams.id", ondelete="SET NULL"), nullable=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="public")


class ResourceSubscription(Base):
    """Tracks subscriptions to resource updates."""

    __tablename__ = "resource_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"))
    subscriber_id: Mapped[str] = mapped_column(String(255), nullable=False)  # Client identifier
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_notification: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    resource: Mapped["Resource"] = relationship(back_populates="subscriptions")


class Prompt(Base):
    """
    ORM model for a registered Prompt template.

    Represents a prompt template along with its argument schema.
    Supports rendering and invocation of prompts.
    Additionally, this model provides computed properties for aggregated metrics based
    on the associated PromptMetric records. These include:
        - execution_count: Total number of prompt invocations.
        - successful_executions: Count of successful invocations.
        - failed_executions: Count of failed invocations.
        - failure_rate: Ratio of failed invocations to total invocations.
        - min_response_time: Fastest recorded response time.
        - max_response_time: Slowest recorded response time.
        - avg_response_time: Mean response time.
        - last_execution_time: Timestamp of the most recent invocation.
    """

    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    template: Mapped[str] = mapped_column(Text)
    argument_schema: Mapped[Dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    is_active: Mapped[bool] = mapped_column(default=True)
    tags: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)

    # Comprehensive metadata for audit tracking
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_from_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_via: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    modified_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    modified_from_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    modified_via: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    modified_user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    import_batch_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    federation_source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    metrics: Mapped[List["PromptMetric"]] = relationship("PromptMetric", back_populates="prompt", cascade="all, delete-orphan")

    gateway_id: Mapped[Optional[str]] = mapped_column(ForeignKey("gateways.id"))
    gateway: Mapped["Gateway"] = relationship("Gateway", back_populates="prompts")
    # federated_with = relationship("Gateway", secondary=prompt_gateway_table, back_populates="federated_prompts")

    # Many-to-many relationship with Servers
    servers: Mapped[List["Server"]] = relationship("Server", secondary=server_prompt_association, back_populates="prompts")

    # Team scoping fields for resource organization
    team_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("email_teams.id", ondelete="SET NULL"), nullable=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="public")

    __table_args__ = (UniqueConstraint("team_id", "owner_email", "name", name="uq_team_owner_name_prompt"),)

    def validate_arguments(self, args: Dict[str, str]) -> None:
        """
        Validate prompt arguments against the argument schema.

        Args:
            args (Dict[str, str]): Dictionary of arguments to validate.

        Raises:
            ValueError: If the arguments do not conform to the schema.

        Examples:
            >>> prompt = Prompt(
            ...     name="test_prompt",
            ...     template="Hello {name}",
            ...     argument_schema={
            ...         "type": "object",
            ...         "properties": {
            ...             "name": {"type": "string"}
            ...         },
            ...         "required": ["name"]
            ...     }
            ... )
            >>> prompt.validate_arguments({"name": "Alice"})  # No exception
            >>> try:
            ...     prompt.validate_arguments({"age": 25})  # Missing required field
            ... except ValueError as e:
            ...     "name" in str(e)
            True
        """
        try:
            jsonschema.validate(args, self.argument_schema)
        except jsonschema.exceptions.ValidationError as e:
            raise ValueError(f"Invalid prompt arguments: {str(e)}") from e

    @property
    def execution_count(self) -> int:
        """
        Returns the number of times the prompt has been invoked,
        calculated from the associated PromptMetric records.

        Returns:
            int: The total count of prompt invocations.
        """
        return len(self.metrics)

    @property
    def successful_executions(self) -> int:
        """
        Returns the count of successful prompt invocations,
        computed from the associated PromptMetric records.

        Returns:
            int: The count of successful prompt invocations.
        """
        return sum(1 for m in self.metrics if m.is_success)

    @property
    def failed_executions(self) -> int:
        """
        Returns the count of failed prompt invocations,
        computed from the associated PromptMetric records.

        Returns:
            int: The count of failed prompt invocations.
        """
        return sum(1 for m in self.metrics if not m.is_success)

    @property
    def failure_rate(self) -> float:
        """
        Returns the failure rate (as a float between 0 and 1) computed as:
            (failed invocations) / (total invocations).
        Returns 0.0 if there are no invocations.

        Returns:
            float: The failure rate as a value between 0 and 1.
        """
        total: int = self.execution_count
        if total == 0:
            return 0.0
        return self.failed_executions / total

    @property
    def min_response_time(self) -> Optional[float]:
        """
        Returns the minimum response time among all prompt invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The minimum response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return min(times) if times else None

    @property
    def max_response_time(self) -> Optional[float]:
        """
        Returns the maximum response time among all prompt invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The maximum response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return max(times) if times else None

    @property
    def avg_response_time(self) -> Optional[float]:
        """
        Returns the average response time among all prompt invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The average response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return sum(times) / len(times) if times else None

    @property
    def last_execution_time(self) -> Optional[datetime]:
        """
        Returns the timestamp of the most recent prompt invocation.
        Returns None if no invocations exist.

        Returns:
            Optional[datetime]: The timestamp of the most recent invocation, or None if no invocations exist.
        """
        if not self.metrics:
            return None
        return max(m.timestamp for m in self.metrics)


class Server(Base):
    """
    ORM model for MCP Servers Catalog.

    Represents a server that composes catalog items (tools, resources, prompts).
    Additionally, this model provides computed properties for aggregated metrics based
    on the associated ServerMetric records. These include:
        - execution_count: Total number of invocations.
        - successful_executions: Count of successful invocations.
        - failed_executions: Count of failed invocations.
        - failure_rate: Ratio of failed invocations to total invocations.
        - min_response_time: Fastest recorded response time.
        - max_response_time: Slowest recorded response time.
        - avg_response_time: Mean response time.
        - last_execution_time: Timestamp of the most recent invocation.
    """

    __tablename__ = "servers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(767), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    is_active: Mapped[bool] = mapped_column(default=True)
    tags: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)

    # Comprehensive metadata for audit tracking
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_from_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_via: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    modified_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    modified_from_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    modified_via: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    modified_user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    import_batch_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    federation_source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    metrics: Mapped[List["ServerMetric"]] = relationship("ServerMetric", back_populates="server", cascade="all, delete-orphan")

    # Many-to-many relationships for associated items
    tools: Mapped[List["Tool"]] = relationship("Tool", secondary=server_tool_association, back_populates="servers")
    resources: Mapped[List["Resource"]] = relationship("Resource", secondary=server_resource_association, back_populates="servers")
    prompts: Mapped[List["Prompt"]] = relationship("Prompt", secondary=server_prompt_association, back_populates="servers")
    a2a_agents: Mapped[List["A2AAgent"]] = relationship("A2AAgent", secondary=server_a2a_association, back_populates="servers")

    # API token relationships
    scoped_tokens: Mapped[List["EmailApiToken"]] = relationship("EmailApiToken", back_populates="server")

    @property
    def execution_count(self) -> int:
        """
        Returns the number of times the server has been invoked,
        calculated from the associated ServerMetric records.

        Returns:
            int: The total count of server invocations.
        """
        return len(self.metrics)

    @property
    def successful_executions(self) -> int:
        """
        Returns the count of successful server invocations,
        computed from the associated ServerMetric records.

        Returns:
            int: The count of successful server invocations.
        """
        return sum(1 for m in self.metrics if m.is_success)

    @property
    def failed_executions(self) -> int:
        """
        Returns the count of failed server invocations,
        computed from the associated ServerMetric records.

        Returns:
            int: The count of failed server invocations.
        """
        return sum(1 for m in self.metrics if not m.is_success)

    @property
    def failure_rate(self) -> float:
        """
        Returns the failure rate (as a float between 0 and 1) computed as:
            (failed invocations) / (total invocations).
        Returns 0.0 if there are no invocations.

        Returns:
            float: The failure rate as a value between 0 and 1.

        Examples:
            >>> tool = Tool(custom_name="test_tool", custom_name_slug="test-tool", input_schema={})
            >>> tool.failure_rate  # No metrics yet
            0.0
            >>> tool.metrics = [
            ...     ToolMetric(tool_id=tool.id, response_time=1.0, is_success=True),
            ...     ToolMetric(tool_id=tool.id, response_time=2.0, is_success=False),
            ...     ToolMetric(tool_id=tool.id, response_time=1.5, is_success=True),
            ... ]
            >>> tool.failure_rate
            0.3333333333333333
        """
        total: int = self.execution_count
        if total == 0:
            return 0.0
        return self.failed_executions / total

    @property
    def min_response_time(self) -> Optional[float]:
        """
        Returns the minimum response time among all server invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The minimum response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return min(times) if times else None

    @property
    def max_response_time(self) -> Optional[float]:
        """
        Returns the maximum response time among all server invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The maximum response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return max(times) if times else None

    @property
    def avg_response_time(self) -> Optional[float]:
        """
        Returns the average response time among all server invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The average response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return sum(times) / len(times) if times else None

    @property
    def last_execution_time(self) -> Optional[datetime]:
        """
        Returns the timestamp of the most recent server invocation.
        Returns None if no invocations exist.

        Returns:
            Optional[datetime]: The timestamp of the most recent invocation, or None if no invocations exist.
        """
        if not self.metrics:
            return None
        return max(m.timestamp for m in self.metrics)

    # Team scoping fields for resource organization
    team_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("email_teams.id", ondelete="SET NULL"), nullable=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="public")
    __table_args__ = (UniqueConstraint("team_id", "owner_email", "name", name="uq_team_owner_name_server"),)


class Gateway(Base):
    """ORM model for a federated peer Gateway."""

    __tablename__ = "gateways"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(767), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transport: Mapped[str] = mapped_column(String(20), default="SSE")
    capabilities: Mapped[Dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    enabled: Mapped[bool] = mapped_column(default=True)
    reachable: Mapped[bool] = mapped_column(default=True)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    tags: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)

    # Comprehensive metadata for audit tracking
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_from_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_via: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    modified_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    modified_from_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    modified_via: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    modified_user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    import_batch_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    federation_source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Header passthrough configuration
    passthrough_headers: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)  # Store list of strings as JSON array

    # CA certificate
    ca_certificate: Mapped[Optional[bytes]] = mapped_column(Text, nullable=True)
    ca_certificate_sig: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    signing_algorithm: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default="ed25519")  # e.g., "sha256"

    # Relationship with local tools this gateway provides
    tools: Mapped[List["Tool"]] = relationship(back_populates="gateway", foreign_keys="Tool.gateway_id", cascade="all, delete-orphan")

    # Relationship with local prompts this gateway provides
    prompts: Mapped[List["Prompt"]] = relationship(back_populates="gateway", cascade="all, delete-orphan")

    # Relationship with local resources this gateway provides
    resources: Mapped[List["Resource"]] = relationship(back_populates="gateway", cascade="all, delete-orphan")

    # # Tools federated from this gateway
    # federated_tools: Mapped[List["Tool"]] = relationship(secondary=tool_gateway_table, back_populates="federated_with")

    # # Prompts federated from this resource
    # federated_resources: Mapped[List["Resource"]] = relationship(secondary=resource_gateway_table, back_populates="federated_with")

    # # Prompts federated from this gateway
    # federated_prompts: Mapped[List["Prompt"]] = relationship(secondary=prompt_gateway_table, back_populates="federated_with")

    # Authorizations
    auth_type: Mapped[Optional[str]] = mapped_column(String(20), default=None)  # "basic", "bearer", "headers", "oauth" or None
    auth_value: Mapped[Optional[Dict[str, str]]] = mapped_column(JSON)

    # OAuth configuration
    oauth_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, comment="OAuth 2.0 configuration including grant_type, client_id, encrypted client_secret, URLs, and scopes")

    # Team scoping fields for resource organization
    team_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("email_teams.id", ondelete="SET NULL"), nullable=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="public")

    # Relationship with OAuth tokens
    oauth_tokens: Mapped[List["OAuthToken"]] = relationship("OAuthToken", back_populates="gateway", cascade="all, delete-orphan")

    # Relationship with registered OAuth clients (DCR)

    registered_oauth_clients: Mapped[List["RegisteredOAuthClient"]] = relationship("RegisteredOAuthClient", back_populates="gateway", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("team_id", "owner_email", "slug", name="uq_team_owner_slug_gateway"),)


@event.listens_for(Gateway, "after_update")
def update_tool_names_on_gateway_update(_mapper, connection, target):
    """
    If a Gateway's name is updated, efficiently update all of its
    child Tools' names with a single SQL statement.

    Args:
        _mapper: Mapper
        connection: Connection
        target: Target
    """
    # 1. Check if the 'name' field was actually part of the update.
    #    This is a concise way to see if the value has changed.
    if not get_history(target, "name").has_changes():
        return

    print(f"Gateway name changed for ID {target.id}. Issuing bulk update for tools.")

    # 2. Get a reference to the underlying database table for Tools
    tools_table = Tool.__table__

    # 3. Prepare the new values
    new_gateway_slug = slugify(target.name)
    separator = settings.gateway_tool_name_separator

    # 4. Construct a single, powerful UPDATE statement using SQLAlchemy Core.
    #    This is highly efficient as it all happens in the database.
    stmt = (
        cast(Any, tools_table)
        .update()
        .where(tools_table.c.gateway_id == target.id)
        .values(name=new_gateway_slug + separator + tools_table.c.custom_name_slug)
        .execution_options(synchronize_session=False)
    )

    # 5. Execute the statement using the connection from the ongoing transaction.
    connection.execute(stmt)


class A2AAgent(Base):
    """
    ORM model for A2A (Agent-to-Agent) compatible agents.

    A2A agents represent external AI agents that can be integrated into the gateway
    and exposed as tools within virtual servers. They support standardized
    Agent-to-Agent communication protocols for interoperability.
    """

    __tablename__ = "a2a_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    endpoint_url: Mapped[str] = mapped_column(String(767), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False, default="generic")  # e.g., "openai", "anthropic", "custom"
    protocol_version: Mapped[str] = mapped_column(String(10), nullable=False, default="1.0")
    capabilities: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # Configuration
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    # Authorizations
    auth_type: Mapped[Optional[str]] = mapped_column(String(20), default=None)  # "basic", "bearer", "headers", "oauth" or None
    auth_value: Mapped[Optional[Dict[str, str]]] = mapped_column(JSON)

    # OAuth configuration
    oauth_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, comment="OAuth 2.0 configuration including grant_type, client_id, encrypted client_secret, URLs, and scopes")

    # Header passthrough configuration
    passthrough_headers: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)  # Store list of strings as JSON array

    # Status and metadata
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reachable: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    last_interaction: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Tags for categorization
    tags: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)

    # Comprehensive metadata for audit tracking
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_from_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_via: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    modified_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    modified_from_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    modified_via: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    modified_user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    import_batch_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    federation_source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Team scoping fields for resource organization
    team_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("email_teams.id", ondelete="SET NULL"), nullable=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="public")

    # Relationships
    servers: Mapped[List["Server"]] = relationship("Server", secondary=server_a2a_association, back_populates="a2a_agents")
    metrics: Mapped[List["A2AAgentMetric"]] = relationship("A2AAgentMetric", back_populates="a2a_agent", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("team_id", "owner_email", "slug", name="uq_team_owner_slug_a2a_agent"),)

    # Relationship with OAuth tokens
    # oauth_tokens: Mapped[List["OAuthToken"]] = relationship("OAuthToken", back_populates="gateway", cascade="all, delete-orphan")

    # Relationship with registered OAuth clients (DCR)
    # registered_oauth_clients: Mapped[List["RegisteredOAuthClient"]] = relationship("RegisteredOAuthClient", back_populates="gateway", cascade="all, delete-orphan")

    @property
    def execution_count(self) -> int:
        """Total number of interactions with this agent.

        Returns:
            int: The total count of interactions.
        """
        return len(self.metrics)

    @property
    def successful_executions(self) -> int:
        """Number of successful interactions.

        Returns:
            int: The count of successful interactions.
        """
        return sum(1 for m in self.metrics if m.is_success)

    @property
    def failed_executions(self) -> int:
        """Number of failed interactions.

        Returns:
            int: The count of failed interactions.
        """
        return sum(1 for m in self.metrics if not m.is_success)

    @property
    def failure_rate(self) -> float:
        """Failure rate as a percentage.

        Returns:
            float: The failure rate percentage.
        """
        if not self.metrics:
            return 0.0
        return (self.failed_executions / len(self.metrics)) * 100

    @property
    def avg_response_time(self) -> Optional[float]:
        """Average response time in seconds.

        Returns:
            Optional[float]: The average response time, or None if no metrics.
        """
        if not self.metrics:
            return None
        return sum(m.response_time for m in self.metrics) / len(self.metrics)

    @property
    def last_execution_time(self) -> Optional[datetime]:
        """Timestamp of the most recent interaction.

        Returns:
            Optional[datetime]: The timestamp of the last interaction, or None if no metrics.
        """
        if not self.metrics:
            return None
        return max(m.timestamp for m in self.metrics)

    def __repr__(self) -> str:
        """Return a string representation of the A2AAgent instance.

        Returns:
            str: A formatted string containing the agent's ID, name, and type.

        Examples:
            >>> agent = A2AAgent(id='123', name='test-agent', agent_type='custom')
            >>> repr(agent)
            "<A2AAgent(id='123', name='test-agent', agent_type='custom')>"
        """
        return f"<A2AAgent(id='{self.id}', name='{self.name}', agent_type='{self.agent_type}')>"


class GrpcService(Base):
    """
    ORM model for gRPC services with reflection-based discovery.

    gRPC services represent external gRPC servers that can be automatically discovered
    via server reflection and exposed as MCP tools. The gateway translates between
    gRPC/Protobuf and MCP/JSON protocols.
    """

    __tablename__ = "grpc_services"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    target: Mapped[str] = mapped_column(String(767), nullable=False)  # host:port format

    # Configuration
    reflection_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tls_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tls_cert_path: Mapped[Optional[str]] = mapped_column(String(767))
    tls_key_path: Mapped[Optional[str]] = mapped_column(String(767))
    grpc_metadata: Mapped[Dict[str, str]] = mapped_column(JSON, default=dict)  # gRPC metadata headers

    # Status
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reachable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Discovery results from reflection
    service_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    method_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discovered_services: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)  # Service descriptors
    last_reflection: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Tags for categorization
    tags: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Comprehensive metadata for audit tracking
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_from_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_via: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    modified_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    modified_from_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    modified_via: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    modified_user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    import_batch_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    federation_source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Team scoping fields for resource organization
    team_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("email_teams.id", ondelete="SET NULL"), nullable=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="public")

    def __repr__(self) -> str:
        """Return a string representation of the GrpcService instance.

        Returns:
            str: A formatted string containing the service's ID, name, and target.
        """
        return f"<GrpcService(id='{self.id}', name='{self.name}', target='{self.target}')>"


class SessionRecord(Base):
    """ORM model for sessions from SSE client."""

    __tablename__ = "mcp_sessions"

    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)  # pylint: disable=not-callable
    last_accessed: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)  # pylint: disable=not-callable
    data: Mapped[str] = mapped_column(Text, nullable=True)

    messages: Mapped[List["SessionMessageRecord"]] = relationship("SessionMessageRecord", back_populates="session", cascade="all, delete-orphan")


class SessionMessageRecord(Base):
    """ORM model for messages from SSE client."""

    __tablename__ = "mcp_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(255), ForeignKey("mcp_sessions.session_id"))
    message: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)  # pylint: disable=not-callable
    last_accessed: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)  # pylint: disable=not-callable

    session: Mapped["SessionRecord"] = relationship("SessionRecord", back_populates="messages")


class OAuthToken(Base):
    """ORM model for OAuth access and refresh tokens with user association."""

    __tablename__ = "oauth_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)
    gateway_id: Mapped[str] = mapped_column(String(36), ForeignKey("gateways.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)  # OAuth provider's user ID
    app_user_email: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email", ondelete="CASCADE"), nullable=False)  # MCP Gateway user
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_type: Mapped[str] = mapped_column(String(50), default="Bearer")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    gateway: Mapped["Gateway"] = relationship("Gateway", back_populates="oauth_tokens")
    app_user: Mapped["EmailUser"] = relationship("EmailUser", foreign_keys=[app_user_email])

    # Unique constraint: one token per user per gateway
    __table_args__ = (UniqueConstraint("gateway_id", "app_user_email", name="uq_oauth_gateway_user"),)


class OAuthState(Base):
    """ORM model for OAuth authorization states with TTL for CSRF protection."""

    __tablename__ = "oauth_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)
    gateway_id: Mapped[str] = mapped_column(String(36), ForeignKey("gateways.id", ondelete="CASCADE"), nullable=False)
    state: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)  # The state parameter
    code_verifier: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # PKCE code verifier (RFC 7636)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # Relationships
    gateway: Mapped["Gateway"] = relationship("Gateway")

    # Index for efficient lookups
    __table_args__ = (Index("idx_oauth_state_lookup", "gateway_id", "state"),)


class RegisteredOAuthClient(Base):
    """Stores dynamically registered OAuth clients (RFC 7591 client mode).

    This model maintains client credentials obtained through Dynamic Client
    Registration with upstream Authorization Servers.
    """

    __tablename__ = "registered_oauth_clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    gateway_id: Mapped[str] = mapped_column(String(36), ForeignKey("gateways.id", ondelete="CASCADE"), nullable=False, index=True)

    # Registration details
    issuer: Mapped[str] = mapped_column(String(500), nullable=False)  # AS issuer URL
    client_id: Mapped[str] = mapped_column(String(500), nullable=False)
    client_secret_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Encrypted

    # RFC 7591 fields
    redirect_uris: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    grant_types: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    response_types: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    scope: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    token_endpoint_auth_method: Mapped[str] = mapped_column(String(50), default="client_secret_basic")

    # Registration management (RFC 7591 section 4)
    registration_client_uri: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    registration_access_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    gateway: Mapped["Gateway"] = relationship("Gateway", back_populates="registered_oauth_clients")

    # Unique constraint: one registration per gateway+issuer
    __table_args__ = (Index("idx_gateway_issuer", "gateway_id", "issuer", unique=True),)


class EmailApiToken(Base):
    """Email user API token model for token catalog management.

    This model provides comprehensive API token management with scoping,
    revocation, and usage tracking for email-based users.

    Attributes:
        id (str): Unique token identifier
        user_email (str): Owner's email address
        team_id (str): Team the token is associated with (required for team-based access)
        name (str): Human-readable token name
        jti (str): JWT ID for revocation checking
        token_hash (str): Hashed token value for security
        server_id (str): Optional server scope limitation
        resource_scopes (List[str]): Permission scopes like ['tools.read']
        ip_restrictions (List[str]): IP address/CIDR restrictions
        time_restrictions (dict): Time-based access restrictions
        usage_limits (dict): Rate limiting and usage quotas
        created_at (datetime): Token creation timestamp
        expires_at (datetime): Optional expiry timestamp
        last_used (datetime): Last usage timestamp
        is_active (bool): Active status flag
        description (str): Token description
        tags (List[str]): Organizational tags

    Examples:
        >>> token = EmailApiToken(
        ...     user_email="alice@example.com",
        ...     name="Production API Access",
        ...     server_id="prod-server-123",
        ...     resource_scopes=["tools.read", "resources.read"],
        ...     description="Read-only access to production tools"
        ... )
        >>> token.is_scoped_to_server("prod-server-123")
        True
        >>> token.has_permission("tools.read")
        True
    """

    __tablename__ = "email_api_tokens"

    # Core identity fields
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_email: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email", ondelete="CASCADE"), nullable=False, index=True)
    team_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("email_teams.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    jti: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Scoping fields
    server_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("servers.id", ondelete="CASCADE"), nullable=True)
    resource_scopes: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True, default=list)
    ip_restrictions: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True, default=list)
    time_restrictions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=dict)
    usage_limits: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=dict)

    # Lifecycle fields
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Metadata fields
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True, default=list)

    # Unique constraint for user+name combination
    __table_args__ = (
        UniqueConstraint("user_email", "name", name="uq_email_api_tokens_user_name"),
        Index("idx_email_api_tokens_user_email", "user_email"),
        Index("idx_email_api_tokens_jti", "jti"),
        Index("idx_email_api_tokens_expires_at", "expires_at"),
        Index("idx_email_api_tokens_is_active", "is_active"),
    )

    # Relationships
    user: Mapped["EmailUser"] = relationship("EmailUser", back_populates="api_tokens")
    team: Mapped[Optional["EmailTeam"]] = relationship("EmailTeam", back_populates="api_tokens")
    server: Mapped[Optional["Server"]] = relationship("Server", back_populates="scoped_tokens")

    def is_scoped_to_server(self, server_id: str) -> bool:
        """Check if token is scoped to a specific server.

        Args:
            server_id: Server ID to check against.

        Returns:
            bool: True if token is scoped to the server, False otherwise.
        """
        return self.server_id == server_id if self.server_id else False

    def has_permission(self, permission: str) -> bool:
        """Check if token has a specific permission.

        Args:
            permission: Permission string to check for.

        Returns:
            bool: True if token has the permission, False otherwise.
        """
        return permission in (self.resource_scopes or [])

    def is_team_token(self) -> bool:
        """Check if this is a team-based token.

        Returns:
            bool: True if token is associated with a team, False otherwise.
        """
        return self.team_id is not None

    def get_effective_permissions(self) -> List[str]:
        """Get effective permissions for this token.

        For team tokens, this should inherit team permissions.
        For personal tokens, this uses the resource_scopes.

        Returns:
            List[str]: List of effective permissions for this token.
        """
        if self.is_team_token() and self.team:
            # For team tokens, we would inherit team permissions
            # This would need to be implemented based on your RBAC system
            return self.resource_scopes or []
        return self.resource_scopes or []

    def is_expired(self) -> bool:
        """Check if token is expired.

        Returns:
            bool: True if token is expired, False otherwise.
        """
        if not self.expires_at:
            return False
        return utc_now() > self.expires_at

    def is_valid(self) -> bool:
        """Check if token is valid (active and not expired).

        Returns:
            bool: True if token is valid, False otherwise.
        """
        return self.is_active and not self.is_expired()


class TokenUsageLog(Base):
    """Token usage logging for analytics and security monitoring.

    This model tracks every API request made with email API tokens
    for security auditing and usage analytics.

    Attributes:
        id (int): Auto-incrementing log ID
        token_jti (str): Token JWT ID reference
        user_email (str): Token owner's email
        timestamp (datetime): Request timestamp
        endpoint (str): API endpoint accessed
        method (str): HTTP method used
        ip_address (str): Client IP address
        user_agent (str): Client user agent
        status_code (int): HTTP response status
        response_time_ms (int): Response time in milliseconds
        blocked (bool): Whether request was blocked
        block_reason (str): Reason for blocking if applicable

    Examples:
        >>> log = TokenUsageLog(
        ...     token_jti="token-uuid-123",
        ...     user_email="alice@example.com",
        ...     endpoint="/tools",
        ...     method="GET",
        ...     ip_address="192.168.1.100",
        ...     status_code=200,
        ...     response_time_ms=45
        ... )
    """

    __tablename__ = "token_usage_logs"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Token reference
    token_jti: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    # Request details
    endpoint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    method: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)  # IPv6 max length
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Response details
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Security fields
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    block_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Indexes for performance
    __table_args__ = (
        Index("idx_token_usage_logs_token_jti_timestamp", "token_jti", "timestamp"),
        Index("idx_token_usage_logs_user_email_timestamp", "user_email", "timestamp"),
    )


class TokenRevocation(Base):
    """Token revocation blacklist for immediate token invalidation.

    This model maintains a blacklist of revoked JWT tokens to provide
    immediate token invalidation capabilities.

    Attributes:
        jti (str): JWT ID (primary key)
        revoked_at (datetime): Revocation timestamp
        revoked_by (str): Email of user who revoked the token
        reason (str): Optional reason for revocation

    Examples:
        >>> revocation = TokenRevocation(
        ...     jti="token-uuid-123",
        ...     revoked_by="admin@example.com",
        ...     reason="Security compromise"
        ... )
    """

    __tablename__ = "token_revocations"

    # JWT ID as primary key
    jti: Mapped[str] = mapped_column(String(36), primary_key=True)

    # Revocation details
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revoked_by: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationship
    revoker: Mapped["EmailUser"] = relationship("EmailUser")


class SSOProvider(Base):
    """SSO identity provider configuration for OAuth2/OIDC authentication.

    Stores configuration and credentials for external identity providers
    like GitHub, Google, IBM Security Verify, Okta, Microsoft Entra ID,
    and any generic OIDC-compliant provider (Keycloak, Auth0, Authentik, etc.).

    Attributes:
        id (str): Unique provider ID (e.g., 'github', 'google', 'ibm_verify')
        name (str): Human-readable provider name
        display_name (str): Display name for UI
        provider_type (str): Protocol type ('oauth2', 'oidc')
        is_enabled (bool): Whether provider is active
        client_id (str): OAuth client ID
        client_secret_encrypted (str): Encrypted client secret
        authorization_url (str): OAuth authorization endpoint
        token_url (str): OAuth token endpoint
        userinfo_url (str): User info endpoint
        issuer (str): OIDC issuer (optional)
        trusted_domains (List[str]): Auto-approved email domains
        scope (str): OAuth scope string
        auto_create_users (bool): Auto-create users on first login
        team_mapping (dict): Organization/domain to team mapping rules
        created_at (datetime): Provider creation timestamp
        updated_at (datetime): Last configuration update

    Examples:
        >>> provider = SSOProvider(
        ...     id="github",
        ...     name="github",
        ...     display_name="GitHub",
        ...     provider_type="oauth2",
        ...     client_id="gh_client_123",
        ...     authorization_url="https://github.com/login/oauth/authorize",
        ...     token_url="https://github.com/login/oauth/access_token",
        ...     userinfo_url="https://api.github.com/user",
        ...     scope="user:email"
        ... )
    """

    __tablename__ = "sso_providers"

    # Provider identification
    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # github, google, ibm_verify, okta, keycloak, entra, or any custom ID
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(20), nullable=False)  # oauth2, oidc
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # OAuth2/OIDC Configuration
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)  # Encrypted storage
    authorization_url: Mapped[str] = mapped_column(String(500), nullable=False)
    token_url: Mapped[str] = mapped_column(String(500), nullable=False)
    userinfo_url: Mapped[str] = mapped_column(String(500), nullable=False)
    issuer: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # For OIDC

    # Provider Settings
    trusted_domains: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    scope: Mapped[str] = mapped_column(String(200), default="openid profile email", nullable=False)
    auto_create_users: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    team_mapping: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    def __repr__(self):
        """String representation of SSO provider.

        Returns:
            String representation of the SSO provider instance
        """
        return f"<SSOProvider(id='{self.id}', name='{self.name}', enabled={self.is_enabled})>"


class SSOAuthSession(Base):
    """Tracks SSO authentication sessions and state.

    Maintains OAuth state parameters and callback information during
    the SSO authentication flow for security and session management.

    Attributes:
        id (str): Unique session ID (UUID)
        provider_id (str): Reference to SSO provider
        state (str): OAuth state parameter for CSRF protection
        code_verifier (str): PKCE code verifier (for OAuth 2.1)
        nonce (str): OIDC nonce parameter
        redirect_uri (str): OAuth callback URI
        expires_at (datetime): Session expiration time
        user_email (str): User email after successful auth (optional)
        created_at (datetime): Session creation timestamp

    Examples:
        >>> session = SSOAuthSession(
        ...     provider_id="github",
        ...     state="csrf-state-token",
        ...     redirect_uri="https://gateway.example.com/auth/sso-callback/github"
        ... )
    """

    __tablename__ = "sso_auth_sessions"

    # Session identification
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider_id: Mapped[str] = mapped_column(String(50), ForeignKey("sso_providers.id"), nullable=False)

    # OAuth/OIDC parameters
    state: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)  # CSRF protection
    code_verifier: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # PKCE
    nonce: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # OIDC
    redirect_uri: Mapped[str] = mapped_column(String(500), nullable=False)

    # Session lifecycle
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: utc_now() + timedelta(minutes=10), nullable=False)  # 10-minute expiration
    user_email: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    provider: Mapped["SSOProvider"] = relationship("SSOProvider")
    user: Mapped[Optional["EmailUser"]] = relationship("EmailUser")

    @property
    def is_expired(self) -> bool:
        """Check if SSO auth session has expired.

        Returns:
            True if the session has expired, False otherwise
        """
        now = utc_now()
        expires = self.expires_at

        # Handle timezone mismatch by converting naive datetime to UTC if needed
        if expires.tzinfo is None:
            # expires_at is timezone-naive, assume it's UTC
            expires = expires.replace(tzinfo=timezone.utc)
        elif now.tzinfo is None:
            # now is timezone-naive (shouldn't happen with utc_now, but just in case)
            now = now.replace(tzinfo=timezone.utc)

        return now > expires

    def __repr__(self):
        """String representation of SSO auth session.

        Returns:
            str: String representation of the session object
        """
        return f"<SSOAuthSession(id='{self.id}', provider='{self.provider_id}', expired={self.is_expired})>"


# Event listeners for validation
def validate_tool_schema(mapper, connection, target):
    """
    Validate tool schema before insert/update.

    Args:
        mapper: The mapper being used for the operation.
        connection: The database connection.
        target: The target object being validated.

    Raises:
        ValueError: If the tool input schema is invalid.
    """
    # You can use mapper and connection later, if required.
    _ = mapper
    _ = connection
    if hasattr(target, "input_schema"):
        try:
            jsonschema.Draft7Validator.check_schema(target.input_schema)
        except jsonschema.exceptions.SchemaError as e:
            raise ValueError(f"Invalid tool input schema: {str(e)}") from e


def validate_tool_name(mapper, connection, target):
    """
    Validate tool name before insert/update. Check if the name matches the required pattern.

    Args:
        mapper: The mapper being used for the operation.
        connection: The database connection.
        target: The target object being validated.

    Raises:
        ValueError: If the tool name contains invalid characters.
    """
    # You can use mapper and connection later, if required.
    _ = mapper
    _ = connection
    if hasattr(target, "name"):
        try:
            SecurityValidator.validate_tool_name(target.name)
        except ValueError as e:
            raise ValueError(f"Invalid tool name: {str(e)}") from e


def validate_prompt_schema(mapper, connection, target):
    """
    Validate prompt argument schema before insert/update.

    Args:
        mapper: The mapper being used for the operation.
        connection: The database connection.
        target: The target object being validated.

    Raises:
        ValueError: If the prompt argument schema is invalid.
    """
    # You can use mapper and connection later, if required.
    _ = mapper
    _ = connection
    if hasattr(target, "argument_schema"):
        try:
            jsonschema.Draft7Validator.check_schema(target.argument_schema)
        except jsonschema.exceptions.SchemaError as e:
            raise ValueError(f"Invalid prompt argument schema: {str(e)}") from e


# Register validation listeners

listen(Tool, "before_insert", validate_tool_schema)
listen(Tool, "before_update", validate_tool_schema)
listen(Tool, "before_insert", validate_tool_name)
listen(Tool, "before_update", validate_tool_name)
listen(Prompt, "before_insert", validate_prompt_schema)
listen(Prompt, "before_update", validate_prompt_schema)


def get_db() -> Generator[Session, Any, None]:
    """
    Dependency to get database session.

    Yields:
        SessionLocal: A SQLAlchemy database session.

    Examples:
        >>> from mcpgateway.db import get_db
        >>> gen = get_db()
        >>> db = next(gen)
        >>> hasattr(db, 'query')
        True
        >>> hasattr(db, 'commit')
        True
        >>> gen.close()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Create all tables
def init_db():
    """
    Initialize database tables.

    Raises:
        Exception: If database initialization fails.
    """
    try:
        # Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
    except SQLAlchemyError as e:
        raise Exception(f"Failed to initialize database: {str(e)}")


if __name__ == "__main__":
    # Wait for database to be ready before initializing
    wait_for_db_ready(max_tries=int(settings.db_max_retries), interval=int(settings.db_retry_interval_ms) / 1000, sync=True)  # Converting ms to s

    init_db()


@event.listens_for(Gateway, "before_insert")
def set_gateway_slug(_mapper, _conn, target):
    """Set the slug for a Gateway before insert.

    Args:
        _mapper: Mapper
        _conn: Connection
        target: Target Gateway instance
    """

    target.slug = slugify(target.name)


@event.listens_for(A2AAgent, "before_insert")
def set_a2a_agent_slug(_mapper, _conn, target):
    """Set the slug for an A2AAgent before insert.

    Args:
        _mapper: Mapper
        _conn: Connection
        target: Target A2AAgent instance
    """
    target.slug = slugify(target.name)


@event.listens_for(GrpcService, "before_insert")
def set_grpc_service_slug(_mapper, _conn, target):
    """Set the slug for a GrpcService before insert.

    Args:
        _mapper: Mapper
        _conn: Connection
        target: Target GrpcService instance
    """
    target.slug = slugify(target.name)


@event.listens_for(EmailTeam, "before_insert")
def set_email_team_slug(_mapper, _conn, target):
    """Set the slug for an EmailTeam before insert.

    Args:
        _mapper: Mapper
        _conn: Connection
        target: Target EmailTeam instance
    """
    target.slug = slugify(target.name)


@event.listens_for(Tool, "before_insert")
@event.listens_for(Tool, "before_update")
def set_custom_name_and_slug(mapper, connection, target):  # pylint: disable=unused-argument
    """
    Event listener to set custom_name, custom_name_slug, and name for Tool before insert/update.

    - Sets custom_name to original_name if not provided.
    - Calculates custom_name_slug from custom_name using slugify.
    - Updates name to gateway_slug + separator + custom_name_slug.
    - Sets display_name to custom_name if not provided.

    Args:
        mapper: SQLAlchemy mapper for the Tool model.
        connection: Database connection.
        target: The Tool instance being inserted or updated.
    """
    # Set custom_name to original_name if not provided
    if not target.custom_name:
        target.custom_name = target.original_name
    # Set display_name to custom_name if not provided
    if not target.display_name:
        target.display_name = target.custom_name
    # Always update custom_name_slug from custom_name
    target.custom_name_slug = slugify(target.custom_name)
    # Update name field
    gateway_slug = slugify(target.gateway.name) if target.gateway else ""
    if gateway_slug:
        sep = settings.gateway_tool_name_separator
        target.name = f"{gateway_slug}{sep}{target.custom_name_slug}"
    else:
        target.name = target.custom_name_slug
