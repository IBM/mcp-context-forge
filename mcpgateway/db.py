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
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import logging
import os
from typing import Any, cast, Dict, Generator, List, Optional, TYPE_CHECKING
import uuid

# Third-Party
import jsonschema
from sqlalchemy import Boolean, Column, create_engine, DateTime, event, Float, ForeignKey, func, Index
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import Integer, JSON, make_url, MetaData, select, String, Table, Text, UniqueConstraint, VARCHAR
from sqlalchemy.engine import Engine
from sqlalchemy.event import listen
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import DeclarativeBase, joinedload, Mapped, mapped_column, relationship, Session, sessionmaker
from sqlalchemy.orm.attributes import get_history
from sqlalchemy.pool import NullPool, QueuePool

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
#    and the specific driver ("psycopg", "asyncpg", empty string = default).
# ---------------------------------------------------------------------------
url = make_url(settings.database_url)
backend = url.get_backend_name()  # e.g. 'postgresql', 'sqlite'
driver = url.get_driver_name() or "default"

# Start with an empty dict and add options only when the driver can accept
# them; this prevents unexpected TypeError at connect time.
connect_args: dict[str, object] = {}

# ---------------------------------------------------------------------------
# 2. PostgreSQL (synchronous psycopg3)
#    The keep-alive parameters below are recognised by libpq and let the
#    kernel detect broken network links quickly.
#
#    Additionally, support PostgreSQL-specific options like search_path
#    via the 'options' query parameter in DATABASE_URL.
#    Example: postgresql+psycopg://user:pass@host/db?options=-c%20search_path=mcp_gateway
#
#    IMPORTANT: Use postgresql+psycopg:// (not postgresql://) for psycopg3.
# ---------------------------------------------------------------------------
if backend == "postgresql" and driver in ("psycopg", "default", ""):
    connect_args.update(
        keepalives=1,  # enable TCP keep-alive probes
        keepalives_idle=30,  # seconds of idleness before first probe
        keepalives_interval=5,  # seconds between probes
        keepalives_count=5,  # drop the link after N failed probes
        # psycopg3: prepare_threshold controls automatic server-side prepared statements
        # After N executions of the same query, psycopg3 prepares it server-side
        # This significantly improves performance for frequently-executed queries
        prepare_threshold=settings.db_prepare_threshold,
    )

    # Extract and apply PostgreSQL options from URL query parameters
    # This allows users to specify search_path for custom schema support (Issue #1535)
    url_options = url.query.get("options")
    if url_options:
        connect_args["options"] = url_options
        logger.info(f"PostgreSQL connection options applied: {url_options}")

    logger.info(f"psycopg3 prepare_threshold set to {settings.db_prepare_threshold}")

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

# Check for SQLALCHEMY_ECHO environment variable for query debugging
# This is useful for N+1 detection and performance analysis
_sqlalchemy_echo = os.getenv("SQLALCHEMY_ECHO", "").lower() in ("true", "1", "yes")


def build_engine() -> Engine:
    """Build the SQLAlchemy engine with appropriate settings.

    This function constructs the SQLAlchemy engine using the database URL
    and connection arguments determined by the backend type. It also configures
    the connection pool size and timeout based on application settings.

    Environment variables:
        SQLALCHEMY_ECHO: Set to 'true' to log all SQL queries (useful for N+1 detection)

    Returns:
        SQLAlchemy Engine instance configured for the specified database.
    """
    if _sqlalchemy_echo:
        logger.info("SQLALCHEMY_ECHO enabled - all SQL queries will be logged")

    if backend == "sqlite":
        # SQLite supports connection pooling with proper configuration
        # For SQLite, we use a smaller pool size since it's file-based
        sqlite_pool_size = min(settings.db_pool_size, 50)  # Cap at 50 for SQLite
        sqlite_max_overflow = min(settings.db_max_overflow, 20)  # Cap at 20 for SQLite

        logger.info("Configuring SQLite with pool_size=%s, max_overflow=%s", sqlite_pool_size, sqlite_max_overflow)

        return create_engine(
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
            # Log all SQL queries when SQLALCHEMY_ECHO=true (useful for N+1 detection)
            echo=_sqlalchemy_echo,
        )

    if backend in ("mysql", "mariadb"):
        # MariaDB/MySQL specific configuration
        logger.info("Configuring MariaDB/MySQL with pool_size=%s, max_overflow=%s", settings.db_pool_size, settings.db_max_overflow)

        return create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
            connect_args=connect_args,
            isolation_level="READ_COMMITTED",  # Fix PyMySQL sync issues
            # Log all SQL queries when SQLALCHEMY_ECHO=true (useful for N+1 detection)
            echo=_sqlalchemy_echo,
        )

    # Determine if PgBouncer is in use (detected via URL or explicit config)
    is_pgbouncer = "pgbouncer" in settings.database_url.lower()

    # Determine pool class based on configuration
    # - "auto": NullPool with PgBouncer (recommended), QueuePool otherwise
    # - "null": Always NullPool (delegate pooling to PgBouncer/external pooler)
    # - "queue": Always QueuePool (application-side pooling)
    use_null_pool = False
    if settings.db_pool_class == "null":
        use_null_pool = True
        logger.info("Using NullPool (explicit configuration)")
    elif settings.db_pool_class == "auto" and is_pgbouncer:
        use_null_pool = True
        logger.info("PgBouncer detected - using NullPool (recommended: let PgBouncer handle pooling)")
    elif settings.db_pool_class == "queue":
        logger.info("Using QueuePool (explicit configuration)")
    else:
        logger.info("Using QueuePool with pool_size=%s, max_overflow=%s", settings.db_pool_size, settings.db_max_overflow)

    # Determine pre_ping setting
    # - "auto": Enabled for non-PgBouncer with QueuePool, disabled otherwise
    # - "true": Always enable (validates connections, catches stale connections)
    # - "false": Always disable
    if settings.db_pool_pre_ping == "true":
        use_pre_ping = True
        logger.info("pool_pre_ping enabled (explicit configuration)")
    elif settings.db_pool_pre_ping == "false":
        use_pre_ping = False
        logger.info("pool_pre_ping disabled (explicit configuration)")
    else:  # "auto"
        # With NullPool, pre_ping is not needed (no pooled connections to validate)
        # With QueuePool + PgBouncer, pre_ping helps detect stale connections
        use_pre_ping = not use_null_pool and not is_pgbouncer
        if is_pgbouncer and not use_null_pool:
            logger.info("PgBouncer with QueuePool - consider enabling DB_POOL_PRE_PING=true to detect stale connections")

    # Build engine with appropriate pool configuration
    if use_null_pool:
        return create_engine(
            settings.database_url,
            poolclass=NullPool,
            connect_args=connect_args,
            echo=_sqlalchemy_echo,
        )

    return create_engine(
        settings.database_url,
        pool_pre_ping=use_pre_ping,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        connect_args=connect_args,
        echo=_sqlalchemy_echo,
    )


engine = build_engine()

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
        # Enable foreign key constraints for ON DELETE CASCADE support
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# ---------------------------------------------------------------------------
# Resilient Session class for graceful error recovery
# ---------------------------------------------------------------------------
class ResilientSession(Session):
    """A Session subclass that auto-rollbacks on connection errors.

    When a database operation fails due to a connection error (e.g., PgBouncer
    query_wait_timeout), this session automatically rolls back to clear the
    invalid transaction state. This prevents cascading PendingRollbackError
    failures when multiple queries run within the same request.

    Without this, the first failed query leaves the session in a "needs rollback"
    state, and all subsequent queries fail with PendingRollbackError before
    even attempting to use the database.
    """

    # Error types that indicate connection issues requiring rollback
    _connection_error_patterns = (
        "query_wait_timeout",
        "server closed the connection unexpectedly",
        "connection reset by peer",
        "connection timed out",
        "could not receive data from server",
        "could not send data to server",
        "terminating connection",
        "no connection to the server",
    )

    def _is_connection_error(self, exception: Exception) -> bool:
        """Check if an exception indicates a broken database connection.

        Args:
            exception: The exception to check.

        Returns:
            True if the exception indicates a connection error, False otherwise.
        """
        exc_name = type(exception).__name__
        exc_msg = str(exception).lower()

        # Check for known connection error types
        if exc_name in ("ProtocolViolation", "OperationalError", "InterfaceError"):
            return True

        # Check for connection error patterns in message
        for pattern in self._connection_error_patterns:
            if pattern in exc_msg:
                return True

        return False

    def _safe_rollback(self) -> None:
        """Attempt to rollback, invalidating the session if rollback fails."""
        try:
            self.rollback()
        except Exception:
            try:
                self.invalidate()
            except Exception:
                pass  # nosec B110 - Best effort cleanup on connection failure

    def execute(self, statement, params=None, **kw):
        """Execute a statement with automatic rollback on connection errors.

        Wraps the parent execute method to catch connection errors and
        automatically rollback the session to prevent PendingRollbackError cascade.

        Args:
            statement: The SQL statement to execute.
            params: Optional parameters for the statement.
            **kw: Additional keyword arguments passed to Session.execute().

        Returns:
            The result of the execute operation.

        Raises:
            Exception: Re-raises any exception after rolling back on connection errors.
        """
        try:
            return super().execute(statement, params, **kw)
        except Exception as e:
            if self._is_connection_error(e):
                logger.warning(
                    "Connection error during execute, auto-rolling back session: %s",
                    type(e).__name__,
                )
                self._safe_rollback()
            raise

    def scalar(self, statement, params=None, **kw):
        """Execute and return a scalar with automatic rollback on connection errors.

        Wraps the parent scalar method to catch connection errors and
        automatically rollback the session to prevent PendingRollbackError cascade.

        Args:
            statement: The SQL statement to execute.
            params: Optional parameters for the statement.
            **kw: Additional keyword arguments passed to Session.scalar().

        Returns:
            The scalar result of the query.

        Raises:
            Exception: Re-raises any exception after rolling back on connection errors.
        """
        try:
            return super().scalar(statement, params, **kw)
        except Exception as e:
            if self._is_connection_error(e):
                logger.warning(
                    "Connection error during scalar, auto-rolling back session: %s",
                    type(e).__name__,
                )
                self._safe_rollback()
            raise

    def scalars(self, statement, params=None, **kw):
        """Execute and return scalars with automatic rollback on connection errors.

        Wraps the parent scalars method to catch connection errors and
        automatically rollback the session to prevent PendingRollbackError cascade.

        Args:
            statement: The SQL statement to execute.
            params: Optional parameters for the statement.
            **kw: Additional keyword arguments passed to Session.scalars().

        Returns:
            The scalars result of the query.

        Raises:
            Exception: Re-raises any exception after rolling back on connection errors.
        """
        try:
            return super().scalars(statement, params, **kw)
        except Exception as e:
            if self._is_connection_error(e):
                logger.warning(
                    "Connection error during scalars, auto-rolling back session: %s",
                    type(e).__name__,
                )
                self._safe_rollback()
            raise


# Session factory using ResilientSession
# expire_on_commit=False prevents SQLAlchemy from expiring ORM objects after commit,
# allowing continued access to attributes without re-querying the database.
# This is essential when commits happen during read operations (e.g., to release transactions).
SessionLocal = sessionmaker(class_=ResilientSession, autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


@event.listens_for(ResilientSession, "after_transaction_end")
def end_transaction_cleanup(_session, _transaction):
    """Ensure connection is properly released after transaction ends.

    This event fires after COMMIT or ROLLBACK, ensuring the connection
    is returned to PgBouncer cleanly with no open transaction.

    Args:
        _session: The SQLAlchemy session that ended the transaction.
        _transaction: The transaction that was ended.
    """
    # The transaction has already ended - nothing to do here
    # This is just for monitoring/logging if needed


@event.listens_for(ResilientSession, "before_commit")
def before_commit_handler(session):
    """Handler before commit to ensure transaction is in good state.

    This is called before COMMIT, ensuring any pending work is flushed.

    Args:
        session: The SQLAlchemy session about to commit.
    """
    try:
        session.flush()
    except Exception:  # nosec B110
        # If flush fails, the commit will also fail and trigger rollback
        pass


# ---------------------------------------------------------------------------
# Pool event listeners for connection resilience
# These handlers ensure broken connections are properly invalidated and
# discarded from the pool, preventing "poisoned" connections from causing
# cascading failures (e.g., PendingRollbackError after PgBouncer timeout).
#
# Key issue: PgBouncer returns ProtocolViolation (SQL error 08P01) for
# query_wait_timeout, but SQLAlchemy doesn't recognize this as a disconnect
# by default. We must explicitly mark these errors as disconnects so the
# connection pool properly invalidates these connections.
#
# References:
# - https://github.com/zodb/relstorage/issues/412
# - https://docs.sqlalchemy.org/en/20/core/pooling.html#custom-legacy-pessimistic-ping
# ---------------------------------------------------------------------------
@event.listens_for(engine, "handle_error")
def handle_pool_error(exception_context):
    """Mark PgBouncer and connection errors as disconnects for proper pool invalidation.

    This event fires when an error occurs during query execution. By marking
    certain errors as disconnects (is_disconnect=True), SQLAlchemy will:
    1. Invalidate the current connection (discard from pool)
    2. Invalidate all other pooled connections older than current time

    Without this, PgBouncer errors like query_wait_timeout result in
    ProtocolViolation which is classified as DatabaseError, not a disconnect.
    The connection stays in the pool and causes PendingRollbackError on reuse.

    Args:
        exception_context: SQLAlchemy ExceptionContext with error details.
    """
    original = exception_context.original_exception
    if original is None:
        return

    # Get the exception class name and message for pattern matching
    exc_class = type(original).__name__
    exc_msg = str(original).lower()

    # List of error patterns that indicate the connection is broken
    # and should be treated as a disconnect for pool invalidation
    disconnect_patterns = [
        # PgBouncer errors
        "query_wait_timeout",
        "server_login_retry",
        "client_login_timeout",
        "client_idle_timeout",
        "idle_transaction_timeout",
        "server closed the connection unexpectedly",
        "connection reset by peer",
        "connection timed out",
        "no connection to the server",
        "terminating connection",
        "connection has been closed unexpectedly",
        # PostgreSQL errors indicating dead connection
        "could not receive data from server",
        "could not send data to server",
        "ssl connection has been closed unexpectedly",
        "canceling statement due to conflict with recovery",
    ]

    # Check for ProtocolViolation or OperationalError with disconnect patterns
    is_connection_error = exc_class in ("ProtocolViolation", "OperationalError", "InterfaceError", "DatabaseError")

    if is_connection_error:
        for pattern in disconnect_patterns:
            if pattern in exc_msg:
                exception_context.is_disconnect = True
                logger.warning(
                    "Connection error detected, marking as disconnect for pool invalidation: %s: %s",
                    exc_class,
                    pattern,
                )
                return

    # Also treat ProtocolViolation from PgBouncer as disconnect even without message match
    # PgBouncer sends 08P01 PROTOCOL_VIOLATION for various connection issues
    if exc_class == "ProtocolViolation":
        exception_context.is_disconnect = True
        logger.warning(
            "ProtocolViolation detected (likely PgBouncer), marking as disconnect: %s",
            exc_msg[:200],
        )


@event.listens_for(engine, "checkin")
def reset_connection_on_checkin(dbapi_connection, _connection_record):
    """Reset connection state when returned to pool.

    This ensures transactions are properly closed before the connection
    is returned to PgBouncer, preventing 'idle in transaction' buildup.
    With PgBouncer in transaction mode, connections stays reserved until
    the transaction ends - this rollback releases them immediately.

    Args:
        dbapi_connection: The raw DBAPI connection being checked in.
        _connection_record: The connection record tracking this connection.
    """
    try:
        # Issue a rollback to close any open transaction
        # This is safe for both read and write operations:
        # - For reads: rollback has no effect but closes the transaction
        # - For writes: they should already be committed by the application
        dbapi_connection.rollback()
    except Exception as e:
        # Connection may be invalid - log and try to force close
        logger.debug("Connection checkin rollback failed: %s", e)
        try:
            # Try to close the raw connection to release it from PgBouncer
            dbapi_connection.close()
        except Exception:  # nosec B110
            pass  # Nothing more we can do


@event.listens_for(engine, "reset")
def reset_connection_on_reset(dbapi_connection, _connection_record):
    """Reset connection state when the pool resets a connection.

    This handles the case where a connection is being reset before reuse.

    Args:
        dbapi_connection: The raw DBAPI connection being reset.
        _connection_record: The connection record tracking this connection.
    """
    try:
        dbapi_connection.rollback()
    except Exception:  # nosec B110
        pass  # Connection may be invalid


def _refresh_gateway_slugs_batched(session: Session, batch_size: int) -> None:
    """Refresh gateway slugs in small batches to reduce memory usage.

    Args:
        session: Active SQLAlchemy session.
        batch_size: Maximum number of rows to process per batch.
    """

    last_id: Optional[str] = None

    while True:
        query = session.query(Gateway).order_by(Gateway.id)
        if last_id is not None:
            query = query.filter(Gateway.id > last_id)

        gateways = query.limit(batch_size).all()
        if not gateways:
            break

        updated = False
        for gateway in gateways:
            new_slug = slugify(gateway.name)
            if gateway.slug != new_slug:
                gateway.slug = new_slug
                updated = True

        if updated:
            session.commit()

        # Free ORM state from memory between batches
        session.expire_all()
        last_id = gateways[-1].id


def _refresh_tool_names_batched(session: Session, batch_size: int) -> None:
    """Refresh tool names in batches with eager-loaded gateways.

    Uses joinedload(Tool.gateway) to avoid N+1 queries when accessing the
    gateway relationship while regenerating tool names.

    Args:
        session: Active SQLAlchemy session.
        batch_size: Maximum number of rows to process per batch.
    """

    last_id: Optional[str] = None
    separator = settings.gateway_tool_name_separator

    while True:
        stmt = select(Tool).options(joinedload(Tool.gateway)).order_by(Tool.id).limit(batch_size)
        if last_id is not None:
            stmt = stmt.where(Tool.id > last_id)

        tools = session.execute(stmt).scalars().all()
        if not tools:
            break

        updated = False
        for tool in tools:
            # Prefer custom_name_slug when available; fall back to original_name
            name_slug_source = getattr(tool, "custom_name_slug", None) or tool.original_name
            name_slug = slugify(name_slug_source)

            if tool.gateway:
                gateway_slug = slugify(tool.gateway.name)
                new_name = f"{gateway_slug}{separator}{name_slug}"
            else:
                new_name = name_slug

            if tool.name != new_name:
                tool.name = new_name
                updated = True

        if updated:
            session.commit()

        # Free ORM state from memory between batches
        session.expire_all()
        last_id = tools[-1].id


def _refresh_prompt_names_batched(session: Session, batch_size: int) -> None:
    """Refresh prompt names in batches with eager-loaded gateways.

    Uses joinedload(Prompt.gateway) to avoid N+1 queries when accessing the
    gateway relationship while regenerating prompt names.

    Args:
        session: Active SQLAlchemy session.
        batch_size: Maximum number of rows to process per batch.
    """
    last_id: Optional[str] = None
    separator = settings.gateway_tool_name_separator

    while True:
        stmt = select(Prompt).options(joinedload(Prompt.gateway)).order_by(Prompt.id).limit(batch_size)
        if last_id is not None:
            stmt = stmt.where(Prompt.id > last_id)

        prompts = session.execute(stmt).scalars().all()
        if not prompts:
            break

        updated = False
        for prompt in prompts:
            name_slug_source = getattr(prompt, "custom_name_slug", None) or prompt.original_name
            name_slug = slugify(name_slug_source)

            if prompt.gateway:
                gateway_slug = slugify(prompt.gateway.name)
                new_name = f"{gateway_slug}{separator}{name_slug}"
            else:
                new_name = name_slug

            if prompt.name != new_name:
                prompt.name = new_name
                updated = True

        if updated:
            session.commit()

        session.expire_all()
        last_id = prompts[-1].id


def refresh_slugs_on_startup(batch_size: Optional[int] = None) -> None:
    """Refresh slugs for all gateways and tool names on startup.

    This implementation avoids loading all rows into memory at once by
    streaming through the tables in batches and eager-loading tool.gateway
    relationships to prevent N+1 query patterns.

    Args:
        batch_size: Optional maximum number of rows to process per batch. If
            not provided, the value is taken from
            ``settings.slug_refresh_batch_size`` with a default of ``1000``.
    """

    effective_batch_size = batch_size or getattr(settings, "slug_refresh_batch_size", 1000)

    try:
        with cast(Any, SessionLocal)() as session:
            # Skip if tables don't exist yet (fresh database)
            try:
                _refresh_gateway_slugs_batched(session, effective_batch_size)
            except (OperationalError, ProgrammingError) as e:
                # Table doesn't exist yet - expected on fresh database
                logger.info("Gateway table not found, skipping slug refresh: %s", e)
                return

            try:
                _refresh_tool_names_batched(session, effective_batch_size)
            except (OperationalError, ProgrammingError) as e:
                # Table doesn't exist yet - expected on fresh database
                logger.info("Tool table not found, skipping tool name refresh: %s", e)

            try:
                _refresh_prompt_names_batched(session, effective_batch_size)
            except (OperationalError, ProgrammingError) as e:
                # Table doesn't exist yet - expected on fresh database
                logger.info("Prompt table not found, skipping prompt name refresh: %s", e)

    except SQLAlchemyError as e:
        logger.warning("Failed to refresh slugs on startup (database error): %s", e)
    except Exception as e:
        logger.warning("Failed to refresh slugs on startup (unexpected error): %s", e)


class Base(DeclarativeBase):
    """Base class for all models."""

    # MariaDB-compatible naming convention for foreign keys
    metadata = MetaData(
        naming_convention={
            "fk": "fk_%(table_name)s_%(column_0_name)s",
            "pk": "pk_%(table_name)s",
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
        }
    )


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
    password_change_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

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

        Uses direct SQL COUNT to avoid loading all members into memory.

        Returns:
            int: Number of active team members

        Examples:
            >>> team = EmailTeam(name="Test Team", slug="test-team", created_by="admin@example.com")
            >>> team.get_member_count()
            0
        """
        # Third-Party
        from sqlalchemy.orm import object_session  # pylint: disable=import-outside-toplevel

        session = object_session(self)
        if session is None:
            # Fallback for detached objects (e.g., in doctests)
            return len([m for m in self.members if m.is_active])

        count = session.query(func.count(EmailTeamMember.id)).filter(EmailTeamMember.team_id == self.id, EmailTeamMember.is_active.is_(True)).scalar()  # pylint: disable=not-callable
        return count or 0

    def is_member(self, user_email: str) -> bool:
        """Check if a user is a member of this team.

        Uses direct SQL EXISTS to avoid loading all members into memory.

        Args:
            user_email: Email address to check

        Returns:
            bool: True if user is an active member, False otherwise

        Examples:
            >>> team = EmailTeam(name="Test Team", slug="test-team", created_by="admin@example.com")
            >>> team.is_member("admin@example.com")
            False
        """
        # Third-Party
        from sqlalchemy.orm import object_session  # pylint: disable=import-outside-toplevel

        session = object_session(self)
        if session is None:
            # Fallback for detached objects (e.g., in doctests)
            return any(m.user_email == user_email and m.is_active for m in self.members)

        exists = session.query(EmailTeamMember.id).filter(EmailTeamMember.team_id == self.id, EmailTeamMember.user_email == user_email, EmailTeamMember.is_active.is_(True)).first()
        return exists is not None

    def get_member_role(self, user_email: str) -> Optional[str]:
        """Get the role of a user in this team.

        Uses direct SQL query to avoid loading all members into memory.

        Args:
            user_email: Email address to check

        Returns:
            str: User's role or None if not a member

        Examples:
            >>> team = EmailTeam(name="Test Team", slug="test-team", created_by="admin@example.com")
            >>> team.get_member_role("admin@example.com")
        """
        # Third-Party
        from sqlalchemy.orm import object_session  # pylint: disable=import-outside-toplevel

        session = object_session(self)
        if session is None:
            # Fallback for detached objects (e.g., in doctests)
            for member in self.members:
                if member.user_email == user_email and member.is_active:
                    return member.role
            return None

        member = session.query(EmailTeamMember.role).filter(EmailTeamMember.team_id == self.id, EmailTeamMember.user_email == user_email, EmailTeamMember.is_active.is_(True)).first()
        return member[0] if member else None


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
    team_member_id: Mapped[str] = mapped_column(String(36), ForeignKey("email_team_members.id", ondelete="CASCADE"), nullable=False)
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
    Column("resource_id", String(36), ForeignKey("resources.id"), primary_key=True),
)

# Association table for servers and prompts
server_prompt_association = Table(
    "server_prompt_association",
    Base.metadata,
    Column("server_id", String(36), ForeignKey("servers.id"), primary_key=True),
    Column("prompt_id", String(36), ForeignKey("prompts.id"), primary_key=True),
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
    tool_id: Mapped[str] = mapped_column(String(36), ForeignKey("tools.id"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
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
        resource_id (str): Foreign key linking to the resource.
        timestamp (datetime): The time when the invocation occurred.
        response_time (float): The response time in seconds.
        is_success (bool): True if the invocation succeeded, False otherwise.
        error_message (Optional[str]): Error message if the invocation failed.
    """

    __tablename__ = "resource_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(36), ForeignKey("resources.id"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
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
    server_id: Mapped[str] = mapped_column(String(36), ForeignKey("servers.id"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
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
        prompt_id (str): Foreign key linking to the prompt.
        timestamp (datetime): The time when the invocation occurred.
        response_time (float): The response time in seconds.
        is_success (bool): True if the invocation succeeded, False otherwise.
        error_message (Optional[str]): Error message if the invocation failed.
    """

    __tablename__ = "prompt_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    prompt_id: Mapped[str] = mapped_column(String(36), ForeignKey("prompts.id"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
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
    a2a_agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("a2a_agents.id"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    response_time: Mapped[float] = mapped_column(Float, nullable=False)
    is_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    interaction_type: Mapped[str] = mapped_column(String(50), nullable=False, default="invoke")

    # Relationship back to the A2AAgent model.
    a2a_agent: Mapped["A2AAgent"] = relationship("A2AAgent", back_populates="metrics")


# ===================================
# Metrics Hourly Rollup Tables
# These tables store pre-aggregated hourly summaries for efficient historical queries.
# Raw metrics can be cleaned up after rollup, reducing storage while preserving trends.
# ===================================


class ToolMetricsHourly(Base):
    """
    Hourly rollup of tool metrics for efficient historical trend analysis.

    This table stores pre-aggregated metrics per tool per hour, enabling fast
    queries for dashboards and reports without scanning millions of raw metrics.

    Attributes:
        id: Primary key.
        tool_id: Foreign key to the tool (nullable for deleted tools).
        tool_name: Tool name snapshot (preserved even if tool is deleted).
        hour_start: Start of the aggregation hour (UTC).
        total_count: Total invocations during this hour.
        success_count: Successful invocations.
        failure_count: Failed invocations.
        min_response_time: Minimum response time in seconds.
        max_response_time: Maximum response time in seconds.
        avg_response_time: Average response time in seconds.
        p50_response_time: 50th percentile (median) response time.
        p95_response_time: 95th percentile response time.
        p99_response_time: 99th percentile response time.
        created_at: When this rollup was created.
    """

    __tablename__ = "tool_metrics_hourly"
    __table_args__ = (
        UniqueConstraint("tool_id", "hour_start", name="uq_tool_metrics_hourly_tool_hour"),
        Index("ix_tool_metrics_hourly_hour_start", "hour_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tool_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("tools.id", ondelete="SET NULL"), nullable=True, index=True)
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hour_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p50_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p95_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p99_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ResourceMetricsHourly(Base):
    """Hourly rollup of resource metrics for efficient historical trend analysis."""

    __tablename__ = "resource_metrics_hourly"
    __table_args__ = (
        UniqueConstraint("resource_id", "hour_start", name="uq_resource_metrics_hourly_resource_hour"),
        Index("ix_resource_metrics_hourly_hour_start", "hour_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("resources.id", ondelete="SET NULL"), nullable=True, index=True)
    resource_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hour_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p50_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p95_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p99_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PromptMetricsHourly(Base):
    """Hourly rollup of prompt metrics for efficient historical trend analysis."""

    __tablename__ = "prompt_metrics_hourly"
    __table_args__ = (
        UniqueConstraint("prompt_id", "hour_start", name="uq_prompt_metrics_hourly_prompt_hour"),
        Index("ix_prompt_metrics_hourly_hour_start", "hour_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    prompt_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True, index=True)
    prompt_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hour_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p50_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p95_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p99_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ServerMetricsHourly(Base):
    """Hourly rollup of server metrics for efficient historical trend analysis."""

    __tablename__ = "server_metrics_hourly"
    __table_args__ = (
        UniqueConstraint("server_id", "hour_start", name="uq_server_metrics_hourly_server_hour"),
        Index("ix_server_metrics_hourly_hour_start", "hour_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("servers.id", ondelete="SET NULL"), nullable=True, index=True)
    server_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hour_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p50_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p95_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p99_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class A2AAgentMetricsHourly(Base):
    """Hourly rollup of A2A agent metrics for efficient historical trend analysis."""

    __tablename__ = "a2a_agent_metrics_hourly"
    __table_args__ = (
        UniqueConstraint("a2a_agent_id", "hour_start", "interaction_type", name="uq_a2a_agent_metrics_hourly_agent_hour_type"),
        Index("ix_a2a_agent_metrics_hourly_hour_start", "hour_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    a2a_agent_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("a2a_agents.id", ondelete="SET NULL"), nullable=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hour_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interaction_type: Mapped[str] = mapped_column(String(50), nullable=False, default="invoke")
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p50_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p95_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p99_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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


# ---------------------------------------------------------------------------
# Performance Monitoring Models
# ---------------------------------------------------------------------------


class PerformanceSnapshot(Base):
    """
    ORM model for point-in-time performance snapshots.

    Stores comprehensive system, request, and worker metrics at regular intervals
    for historical analysis and trend detection.

    Attributes:
        id (int): Auto-incrementing primary key.
        timestamp (datetime): When the snapshot was taken.
        host (str): Hostname of the machine.
        worker_id (str): Worker identifier (PID or UUID).
        metrics_json (dict): JSON blob containing all metrics data.
        created_at (datetime): Record creation timestamp.
    """

    __tablename__ = "performance_snapshots"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Snapshot metadata
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    worker_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # Metrics data (JSON blob)
    metrics_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Indexes for efficient querying
    __table_args__ = (
        Index("idx_performance_snapshots_timestamp", "timestamp"),
        Index("idx_performance_snapshots_host_timestamp", "host", "timestamp"),
        Index("idx_performance_snapshots_created_at", "created_at"),
    )


class PerformanceAggregate(Base):
    """
    ORM model for aggregated performance metrics.

    Stores hourly and daily aggregations of performance data for efficient
    historical reporting and trend analysis.

    Attributes:
        id (int): Auto-incrementing primary key.
        period_start (datetime): Start of the aggregation period.
        period_end (datetime): End of the aggregation period.
        period_type (str): Type of aggregation (hourly, daily).
        host (str): Hostname (None for cluster-wide aggregates).
        Various aggregate metrics for requests and resources.
        created_at (datetime): Record creation timestamp.
    """

    __tablename__ = "performance_aggregates"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Period metadata
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # hourly, daily
    host: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    # Request aggregates
    requests_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    requests_2xx: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    requests_4xx: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    requests_5xx: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_response_time_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    p95_response_time_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    peak_requests_per_second: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Resource aggregates
    avg_cpu_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_memory_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    peak_cpu_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    peak_memory_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Indexes and constraints
    __table_args__ = (
        Index("idx_performance_aggregates_period", "period_type", "period_start"),
        Index("idx_performance_aggregates_host_period", "host", "period_type", "period_start"),
        UniqueConstraint("period_type", "period_start", "host", name="uq_performance_aggregate_period_host"),
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
    gateway_id: Mapped[Optional[str]] = mapped_column(ForeignKey("gateways.id", ondelete="CASCADE"))
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

    __table_args__ = (
        UniqueConstraint("gateway_id", "original_name", name="uq_gateway_id__original_name"),
        UniqueConstraint("team_id", "owner_email", "name", name="uq_team_owner_email_name_tool"),
        Index("idx_tools_created_at_id", "created_at", "id"),
    )

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

    def _metrics_loaded(self) -> bool:
        """Check if metrics relationship is loaded without triggering lazy load.

        Returns:
            bool: True if metrics are loaded, False otherwise.
        """
        return "metrics" in sa_inspect(self).dict

    def _get_metric_counts(self) -> tuple[int, int, int]:
        """Get total, successful, and failed metric counts in a single operation.

        When metrics are already loaded, computes from memory in O(n).
        When not loaded, uses a single SQL query with conditional aggregation.

        Note: For bulk operations, use metrics_summary which computes all fields
        in a single pass, or ensure metrics are preloaded via selectinload.

        Returns:
            tuple[int, int, int]: (total, successful, failed) counts.
        """
        # If metrics are loaded, compute from memory in a single pass
        if self._metrics_loaded():
            total = 0
            successful = 0
            for m in self.metrics:
                total += 1
                if m.is_success:
                    successful += 1
            return (total, successful, total - successful)

        # Use single SQL query with conditional aggregation
        # Third-Party
        from sqlalchemy import case  # pylint: disable=import-outside-toplevel
        from sqlalchemy.orm import object_session  # pylint: disable=import-outside-toplevel

        session = object_session(self)
        if session is None:
            return (0, 0, 0)

        result = (
            session.query(
                func.count(ToolMetric.id),  # pylint: disable=not-callable
                func.sum(case((ToolMetric.is_success.is_(True), 1), else_=0)),
            )
            .filter(ToolMetric.tool_id == self.id)
            .one()
        )

        total = result[0] or 0
        successful = result[1] or 0
        return (total, successful, total - successful)

    @hybrid_property
    def execution_count(self) -> int:
        """Number of ToolMetric records associated with this tool instance.

        Note: Each property access may trigger a SQL query if metrics aren't loaded.
        For reading multiple metric fields, use metrics_summary or preload metrics.

        Returns:
            int: Count of ToolMetric records for this tool.
        """
        return self._get_metric_counts()[0]

    @execution_count.expression
    @classmethod
    def execution_count(cls) -> Any:
        """SQL expression that counts ToolMetric rows for this tool.

        Returns:
            Any: SQLAlchemy labeled count expression for tool metrics.
        """
        return select(func.count(ToolMetric.id)).where(ToolMetric.tool_id == cls.id).correlate(cls).scalar_subquery().label("execution_count")  # pylint: disable=not-callable

    @property
    def successful_executions(self) -> int:
        """Count of successful tool executions.

        Returns:
            int: The count of successful tool executions.
        """
        return self._get_metric_counts()[1]

    @property
    def failed_executions(self) -> int:
        """Count of failed tool executions.

        Returns:
            int: The count of failed tool executions.
        """
        return self._get_metric_counts()[2]

    @property
    def failure_rate(self) -> float:
        """Failure rate as a float between 0 and 1.

        Returns:
            float: The failure rate as a value between 0 and 1.
        """
        total, _, failed = self._get_metric_counts()
        return failed / total if total > 0 else 0.0

    @property
    def min_response_time(self) -> Optional[float]:
        """Minimum response time among all tool executions.

        Returns None if metrics are not loaded (use metrics_summary for SQL fallback).

        Returns:
            Optional[float]: The minimum response time, or None.
        """
        if not self._metrics_loaded():
            return None
        times: List[float] = [m.response_time for m in self.metrics]
        return min(times) if times else None

    @property
    def max_response_time(self) -> Optional[float]:
        """Maximum response time among all tool executions.

        Returns None if metrics are not loaded (use metrics_summary for SQL fallback).

        Returns:
            Optional[float]: The maximum response time, or None.
        """
        if not self._metrics_loaded():
            return None
        times: List[float] = [m.response_time for m in self.metrics]
        return max(times) if times else None

    @property
    def avg_response_time(self) -> Optional[float]:
        """Average response time among all tool executions.

        Returns None if metrics are not loaded (use metrics_summary for SQL fallback).

        Returns:
            Optional[float]: The average response time, or None.
        """
        if not self._metrics_loaded():
            return None
        times: List[float] = [m.response_time for m in self.metrics]
        return sum(times) / len(times) if times else None

    @property
    def last_execution_time(self) -> Optional[datetime]:
        """Timestamp of the most recent tool execution.

        Returns None if metrics are not loaded (use metrics_summary for SQL fallback).

        Returns:
            Optional[datetime]: The timestamp of the most recent execution, or None.
        """
        if not self._metrics_loaded():
            return None
        if not self.metrics:
            return None
        return max(m.timestamp for m in self.metrics)

    @property
    def metrics_summary(self) -> Dict[str, Any]:
        """Aggregated metrics for the tool.

        When metrics are loaded: computes all values from memory in a single pass.
        When not loaded: uses a single SQL query with aggregation for all fields.

        Returns:
            Dict[str, Any]: Dictionary containing aggregated metrics:
                - total_executions, successful_executions, failed_executions
                - failure_rate, min/max/avg_response_time, last_execution_time
        """
        # If metrics are loaded, compute everything in a single pass
        if self._metrics_loaded():
            total = 0
            successful = 0
            min_rt: Optional[float] = None
            max_rt: Optional[float] = None
            sum_rt = 0.0
            last_time: Optional[datetime] = None

            for m in self.metrics:
                total += 1
                if m.is_success:
                    successful += 1
                rt = m.response_time
                if min_rt is None or rt < min_rt:
                    min_rt = rt
                if max_rt is None or rt > max_rt:
                    max_rt = rt
                sum_rt += rt
                if last_time is None or m.timestamp > last_time:
                    last_time = m.timestamp

            failed = total - successful
            return {
                "total_executions": total,
                "successful_executions": successful,
                "failed_executions": failed,
                "failure_rate": failed / total if total > 0 else 0.0,
                "min_response_time": min_rt,
                "max_response_time": max_rt,
                "avg_response_time": sum_rt / total if total > 0 else None,
                "last_execution_time": last_time,
            }

        # Use single SQL query with full aggregation
        # Third-Party
        from sqlalchemy import case  # pylint: disable=import-outside-toplevel
        from sqlalchemy.orm import object_session  # pylint: disable=import-outside-toplevel

        session = object_session(self)
        if session is None:
            return {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "failure_rate": 0.0,
                "min_response_time": None,
                "max_response_time": None,
                "avg_response_time": None,
                "last_execution_time": None,
            }

        result = (
            session.query(
                func.count(ToolMetric.id),  # pylint: disable=not-callable
                func.sum(case((ToolMetric.is_success.is_(True), 1), else_=0)),
                func.min(ToolMetric.response_time),  # pylint: disable=not-callable
                func.max(ToolMetric.response_time),  # pylint: disable=not-callable
                func.avg(ToolMetric.response_time),  # pylint: disable=not-callable
                func.max(ToolMetric.timestamp),  # pylint: disable=not-callable
            )
            .filter(ToolMetric.tool_id == self.id)
            .one()
        )

        total = result[0] or 0
        successful = result[1] or 0
        failed = total - successful

        return {
            "total_executions": total,
            "successful_executions": successful,
            "failed_executions": failed,
            "failure_rate": failed / total if total > 0 else 0.0,
            "min_response_time": result[2],
            "max_response_time": result[3],
            "avg_response_time": float(result[4]) if result[4] is not None else None,
            "last_execution_time": result[5],
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

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)
    uri: Mapped[str] = mapped_column(String(767), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uri_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # URI template for parameterized resources
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    # is_active: Mapped[bool] = mapped_column(default=True)
    enabled: Mapped[bool] = mapped_column(default=True)
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

    gateway_id: Mapped[Optional[str]] = mapped_column(ForeignKey("gateways.id", ondelete="CASCADE"))
    gateway: Mapped["Gateway"] = relationship("Gateway", back_populates="resources")
    # federated_with = relationship("Gateway", secondary=resource_gateway_table, back_populates="federated_resources")

    # Many-to-many relationship with Servers
    servers: Mapped[List["Server"]] = relationship("Server", secondary=server_resource_association, back_populates="resources")
    __table_args__ = (
        UniqueConstraint("team_id", "owner_email", "uri", name="uq_team_owner_uri_resource"),
        Index("idx_resources_created_at_id", "created_at", "id"),
    )

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

    def _metrics_loaded(self) -> bool:
        """Check if metrics relationship is loaded without triggering lazy load.

        Returns:
            bool: True if metrics are loaded, False otherwise.
        """
        return "metrics" in sa_inspect(self).dict

    def _get_metric_counts(self) -> tuple[int, int, int]:
        """Get total, successful, and failed metric counts in a single operation.

        When metrics are already loaded, computes from memory in O(n).
        When not loaded, uses a single SQL query with conditional aggregation.

        Returns:
            tuple[int, int, int]: (total, successful, failed) counts.
        """
        if self._metrics_loaded():
            total = 0
            successful = 0
            for m in self.metrics:
                total += 1
                if m.is_success:
                    successful += 1
            return (total, successful, total - successful)

        # Third-Party
        from sqlalchemy import case  # pylint: disable=import-outside-toplevel
        from sqlalchemy.orm import object_session  # pylint: disable=import-outside-toplevel

        session = object_session(self)
        if session is None:
            return (0, 0, 0)

        result = (
            session.query(
                func.count(ResourceMetric.id),  # pylint: disable=not-callable
                func.sum(case((ResourceMetric.is_success.is_(True), 1), else_=0)),
            )
            .filter(ResourceMetric.resource_id == self.id)
            .one()
        )

        total = result[0] or 0
        successful = result[1] or 0
        return (total, successful, total - successful)

    @hybrid_property
    def execution_count(self) -> int:
        """Number of ResourceMetric records associated with this resource instance.

        Returns:
            int: Count of ResourceMetric records for this resource.
        """
        return self._get_metric_counts()[0]

    @execution_count.expression
    @classmethod
    def execution_count(cls) -> Any:
        """SQL expression that counts ResourceMetric rows for this resource.

        Returns:
            Any: SQLAlchemy labeled count expression for resource metrics.
        """
        return select(func.count(ResourceMetric.id)).where(ResourceMetric.resource_id == cls.id).correlate(cls).scalar_subquery().label("execution_count")  # pylint: disable=not-callable

    @property
    def successful_executions(self) -> int:
        """Count of successful resource invocations.

        Returns:
            int: The count of successful resource invocations.
        """
        return self._get_metric_counts()[1]

    @property
    def failed_executions(self) -> int:
        """Count of failed resource invocations.

        Returns:
            int: The count of failed resource invocations.
        """
        return self._get_metric_counts()[2]

    @property
    def failure_rate(self) -> float:
        """Failure rate as a float between 0 and 1.

        Returns:
            float: The failure rate as a value between 0 and 1.
        """
        total, _, failed = self._get_metric_counts()
        return failed / total if total > 0 else 0.0

    @property
    def min_response_time(self) -> Optional[float]:
        """Minimum response time among all resource invocations.

        Returns None if metrics are not loaded. Note: counts may be non-zero
        (via SQL) while timing is None. Use service layer converters for
        consistent metrics, or preload metrics via selectinload.

        Returns:
            Optional[float]: The minimum response time, or None.
        """
        if not self._metrics_loaded():
            return None
        times: List[float] = [m.response_time for m in self.metrics]
        return min(times) if times else None

    @property
    def max_response_time(self) -> Optional[float]:
        """Maximum response time among all resource invocations.

        Returns None if metrics are not loaded. Note: counts may be non-zero
        (via SQL) while timing is None. Use service layer converters for
        consistent metrics, or preload metrics via selectinload.

        Returns:
            Optional[float]: The maximum response time, or None.
        """
        if not self._metrics_loaded():
            return None
        times: List[float] = [m.response_time for m in self.metrics]
        return max(times) if times else None

    @property
    def avg_response_time(self) -> Optional[float]:
        """Average response time among all resource invocations.

        Returns None if metrics are not loaded. Note: counts may be non-zero
        (via SQL) while timing is None. Use service layer converters for
        consistent metrics, or preload metrics via selectinload.

        Returns:
            Optional[float]: The average response time, or None.
        """
        if not self._metrics_loaded():
            return None
        times: List[float] = [m.response_time for m in self.metrics]
        return sum(times) / len(times) if times else None

    @property
    def last_execution_time(self) -> Optional[datetime]:
        """Timestamp of the most recent resource invocation.

        Returns None if metrics are not loaded. Note: counts may be non-zero
        (via SQL) while timing is None. Use service layer converters for
        consistent metrics, or preload metrics via selectinload.

        Returns:
            Optional[datetime]: The timestamp of the most recent invocation, or None.
        """
        if not self._metrics_loaded():
            return None
        if not self.metrics:
            return None
        return max(m.timestamp for m in self.metrics)

    @property
    def metrics_summary(self) -> Dict[str, Any]:
        """Aggregated metrics for the resource.

        When metrics are loaded: computes all values from memory in a single pass.
        When not loaded: uses a single SQL query with aggregation for all fields.

        Returns:
            Dict[str, Any]: Dictionary containing aggregated metrics:
                - total_executions, successful_executions, failed_executions
                - failure_rate, min/max/avg_response_time, last_execution_time
        """
        if self._metrics_loaded():
            total = 0
            successful = 0
            min_rt: Optional[float] = None
            max_rt: Optional[float] = None
            sum_rt = 0.0
            last_time: Optional[datetime] = None

            for m in self.metrics:
                total += 1
                if m.is_success:
                    successful += 1
                rt = m.response_time
                if min_rt is None or rt < min_rt:
                    min_rt = rt
                if max_rt is None or rt > max_rt:
                    max_rt = rt
                sum_rt += rt
                if last_time is None or m.timestamp > last_time:
                    last_time = m.timestamp

            failed = total - successful
            return {
                "total_executions": total,
                "successful_executions": successful,
                "failed_executions": failed,
                "failure_rate": failed / total if total > 0 else 0.0,
                "min_response_time": min_rt,
                "max_response_time": max_rt,
                "avg_response_time": sum_rt / total if total > 0 else None,
                "last_execution_time": last_time,
            }

        # Third-Party
        from sqlalchemy import case  # pylint: disable=import-outside-toplevel
        from sqlalchemy.orm import object_session  # pylint: disable=import-outside-toplevel

        session = object_session(self)
        if session is None:
            return {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "failure_rate": 0.0,
                "min_response_time": None,
                "max_response_time": None,
                "avg_response_time": None,
                "last_execution_time": None,
            }

        result = (
            session.query(
                func.count(ResourceMetric.id),  # pylint: disable=not-callable
                func.sum(case((ResourceMetric.is_success.is_(True), 1), else_=0)),
                func.min(ResourceMetric.response_time),  # pylint: disable=not-callable
                func.max(ResourceMetric.response_time),  # pylint: disable=not-callable
                func.avg(ResourceMetric.response_time),  # pylint: disable=not-callable
                func.max(ResourceMetric.timestamp),  # pylint: disable=not-callable
            )
            .filter(ResourceMetric.resource_id == self.id)
            .one()
        )

        total = result[0] or 0
        successful = result[1] or 0
        failed = total - successful

        return {
            "total_executions": total,
            "successful_executions": successful,
            "failed_executions": failed,
            "failure_rate": failed / total if total > 0 else 0.0,
            "min_response_time": result[2],
            "max_response_time": result[3],
            "avg_response_time": float(result[4]) if result[4] is not None else None,
            "last_execution_time": result[5],
        }

    # Team scoping fields for resource organization
    team_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("email_teams.id", ondelete="SET NULL"), nullable=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="public")


class ResourceSubscription(Base):
    """Tracks subscriptions to resource updates."""

    __tablename__ = "resource_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"))
    subscriber_id: Mapped[str] = mapped_column(String(255), nullable=False)  # Client identifier
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_notification: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    resource: Mapped["Resource"] = relationship(back_populates="subscriptions")


class ToolOpsTestCases(Base):
    """
    ORM model for a registered Tool test cases.

    Represents a tool and the generated test cases.
    Includes:
        - tool_id: unique tool identifier
        - test_cases: generated test cases.
        - run_status: status of test case generation
    """

    __tablename__ = "toolops_test_cases"

    tool_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    test_cases: Mapped[Dict[str, Any]] = mapped_column(JSON)
    run_status: Mapped[str] = mapped_column(String(255), nullable=False)


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

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    custom_name: Mapped[str] = mapped_column(String(255), nullable=False)
    custom_name_slug: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    template: Mapped[str] = mapped_column(Text)
    argument_schema: Mapped[Dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    # is_active: Mapped[bool] = mapped_column(default=True)
    enabled: Mapped[bool] = mapped_column(default=True)
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

    gateway_id: Mapped[Optional[str]] = mapped_column(ForeignKey("gateways.id", ondelete="CASCADE"))
    gateway: Mapped["Gateway"] = relationship("Gateway", back_populates="prompts")
    # federated_with = relationship("Gateway", secondary=prompt_gateway_table, back_populates="federated_prompts")

    # Many-to-many relationship with Servers
    servers: Mapped[List["Server"]] = relationship("Server", secondary=server_prompt_association, back_populates="prompts")

    # Team scoping fields for resource organization
    team_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("email_teams.id", ondelete="SET NULL"), nullable=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="public")

    __table_args__ = (
        UniqueConstraint("team_id", "owner_email", "name", name="uq_team_owner_name_prompt"),
        UniqueConstraint("gateway_id", "original_name", name="uq_gateway_id__original_name_prompt"),
        Index("idx_prompts_created_at_id", "created_at", "id"),
    )

    @hybrid_property
    def gateway_slug(self) -> Optional[str]:
        """Return the related gateway's slug if available.

        Returns:
            Optional[str]: Gateway slug or None when no gateway is attached.
        """
        return self.gateway.slug if self.gateway else None

    @gateway_slug.expression
    @classmethod
    def gateway_slug(cls) -> Any:
        """SQL expression to select current gateway slug for this prompt.

        Returns:
            Any: SQLAlchemy scalar subquery selecting the gateway slug.
        """
        return select(Gateway.slug).where(Gateway.id == cls.gateway_id).scalar_subquery()

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

    def _metrics_loaded(self) -> bool:
        """Check if metrics relationship is loaded without triggering lazy load.

        Returns:
            bool: True if metrics are loaded, False otherwise.
        """
        return "metrics" in sa_inspect(self).dict

    def _get_metric_counts(self) -> tuple[int, int, int]:
        """Get total, successful, and failed metric counts in a single operation.

        When metrics are already loaded, computes from memory in O(n).
        When not loaded, uses a single SQL query with conditional aggregation.

        Returns:
            tuple[int, int, int]: (total, successful, failed) counts.
        """
        if self._metrics_loaded():
            total = 0
            successful = 0
            for m in self.metrics:
                total += 1
                if m.is_success:
                    successful += 1
            return (total, successful, total - successful)

        # Third-Party
        from sqlalchemy import case  # pylint: disable=import-outside-toplevel
        from sqlalchemy.orm import object_session  # pylint: disable=import-outside-toplevel

        session = object_session(self)
        if session is None:
            return (0, 0, 0)

        result = (
            session.query(
                func.count(PromptMetric.id),  # pylint: disable=not-callable
                func.sum(case((PromptMetric.is_success.is_(True), 1), else_=0)),
            )
            .filter(PromptMetric.prompt_id == self.id)
            .one()
        )

        total = result[0] or 0
        successful = result[1] or 0
        return (total, successful, total - successful)

    @hybrid_property
    def execution_count(self) -> int:
        """Number of PromptMetric records associated with this prompt instance.

        Returns:
            int: Count of PromptMetric records for this prompt.
        """
        return self._get_metric_counts()[0]

    @execution_count.expression
    @classmethod
    def execution_count(cls) -> Any:
        """SQL expression that counts PromptMetric rows for this prompt.

        Returns:
            Any: SQLAlchemy labeled count expression for prompt metrics.
        """
        return select(func.count(PromptMetric.id)).where(PromptMetric.prompt_id == cls.id).correlate(cls).scalar_subquery().label("execution_count")  # pylint: disable=not-callable

    @property
    def successful_executions(self) -> int:
        """Count of successful prompt invocations.

        Returns:
            int: The count of successful prompt invocations.
        """
        return self._get_metric_counts()[1]

    @property
    def failed_executions(self) -> int:
        """Count of failed prompt invocations.

        Returns:
            int: The count of failed prompt invocations.
        """
        return self._get_metric_counts()[2]

    @property
    def failure_rate(self) -> float:
        """Failure rate as a float between 0 and 1.

        Returns:
            float: The failure rate as a value between 0 and 1.
        """
        total, _, failed = self._get_metric_counts()
        return failed / total if total > 0 else 0.0

    @property
    def min_response_time(self) -> Optional[float]:
        """Minimum response time among all prompt invocations.

        Returns None if metrics are not loaded. Note: counts may be non-zero
        (via SQL) while timing is None. Use service layer converters for
        consistent metrics, or preload metrics via selectinload.

        Returns:
            Optional[float]: The minimum response time, or None.
        """
        if not self._metrics_loaded():
            return None
        times: List[float] = [m.response_time for m in self.metrics]
        return min(times) if times else None

    @property
    def max_response_time(self) -> Optional[float]:
        """Maximum response time among all prompt invocations.

        Returns None if metrics are not loaded. Note: counts may be non-zero
        (via SQL) while timing is None. Use service layer converters for
        consistent metrics, or preload metrics via selectinload.

        Returns:
            Optional[float]: The maximum response time, or None.
        """
        if not self._metrics_loaded():
            return None
        times: List[float] = [m.response_time for m in self.metrics]
        return max(times) if times else None

    @property
    def avg_response_time(self) -> Optional[float]:
        """Average response time among all prompt invocations.

        Returns None if metrics are not loaded. Note: counts may be non-zero
        (via SQL) while timing is None. Use service layer converters for
        consistent metrics, or preload metrics via selectinload.

        Returns:
            Optional[float]: The average response time, or None.
        """
        if not self._metrics_loaded():
            return None
        times: List[float] = [m.response_time for m in self.metrics]
        return sum(times) / len(times) if times else None

    @property
    def last_execution_time(self) -> Optional[datetime]:
        """Timestamp of the most recent prompt invocation.

        Returns None if metrics are not loaded. Note: counts may be non-zero
        (via SQL) while timing is None. Use service layer converters for
        consistent metrics, or preload metrics via selectinload.

        Returns:
            Optional[datetime]: The timestamp of the most recent invocation, or None if no invocations exist.
        """
        if not self._metrics_loaded():
            return None
        if not self.metrics:
            return None
        return max(m.timestamp for m in self.metrics)

    @property
    def metrics_summary(self) -> Dict[str, Any]:
        """Aggregated metrics for the prompt.

        When metrics are loaded: computes all values from memory in a single pass.
        When not loaded: uses a single SQL query with aggregation for all fields.

        Returns:
            Dict[str, Any]: Dictionary containing aggregated metrics:
                - total_executions, successful_executions, failed_executions
                - failure_rate, min/max/avg_response_time, last_execution_time
        """
        if self._metrics_loaded():
            total = 0
            successful = 0
            min_rt: Optional[float] = None
            max_rt: Optional[float] = None
            sum_rt = 0.0
            last_time: Optional[datetime] = None

            for m in self.metrics:
                total += 1
                if m.is_success:
                    successful += 1
                rt = m.response_time
                if min_rt is None or rt < min_rt:
                    min_rt = rt
                if max_rt is None or rt > max_rt:
                    max_rt = rt
                sum_rt += rt
                if last_time is None or m.timestamp > last_time:
                    last_time = m.timestamp

            failed = total - successful
            return {
                "total_executions": total,
                "successful_executions": successful,
                "failed_executions": failed,
                "failure_rate": failed / total if total > 0 else 0.0,
                "min_response_time": min_rt,
                "max_response_time": max_rt,
                "avg_response_time": sum_rt / total if total > 0 else None,
                "last_execution_time": last_time,
            }

        # Third-Party
        from sqlalchemy import case  # pylint: disable=import-outside-toplevel
        from sqlalchemy.orm import object_session  # pylint: disable=import-outside-toplevel

        session = object_session(self)
        if session is None:
            return {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "failure_rate": 0.0,
                "min_response_time": None,
                "max_response_time": None,
                "avg_response_time": None,
                "last_execution_time": None,
            }

        result = (
            session.query(
                func.count(PromptMetric.id),  # pylint: disable=not-callable
                func.sum(case((PromptMetric.is_success.is_(True), 1), else_=0)),
                func.min(PromptMetric.response_time),  # pylint: disable=not-callable
                func.max(PromptMetric.response_time),  # pylint: disable=not-callable
                func.avg(PromptMetric.response_time),  # pylint: disable=not-callable
                func.max(PromptMetric.timestamp),  # pylint: disable=not-callable
            )
            .filter(PromptMetric.prompt_id == self.id)
            .one()
        )

        total = result[0] or 0
        successful = result[1] or 0
        failed = total - successful

        return {
            "total_executions": total,
            "successful_executions": successful,
            "failed_executions": failed,
            "failure_rate": failed / total if total > 0 else 0.0,
            "min_response_time": result[2],
            "max_response_time": result[3],
            "avg_response_time": float(result[4]) if result[4] is not None else None,
            "last_execution_time": result[5],
        }


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
    # is_active: Mapped[bool] = mapped_column(default=True)
    enabled: Mapped[bool] = mapped_column(default=True)
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

    def _metrics_loaded(self) -> bool:
        """Check if metrics relationship is loaded without triggering lazy load.

        Returns:
            bool: True if metrics are loaded, False otherwise.
        """
        return "metrics" in sa_inspect(self).dict

    def _get_metric_counts(self) -> tuple[int, int, int]:
        """Get total, successful, and failed metric counts in a single operation.

        When metrics are already loaded, computes from memory in O(n).
        When not loaded, uses a single SQL query with conditional aggregation.

        Returns:
            tuple[int, int, int]: (total, successful, failed) counts.
        """
        if self._metrics_loaded():
            total = 0
            successful = 0
            for m in self.metrics:
                total += 1
                if m.is_success:
                    successful += 1
            return (total, successful, total - successful)

        # Third-Party
        from sqlalchemy import case  # pylint: disable=import-outside-toplevel
        from sqlalchemy.orm import object_session  # pylint: disable=import-outside-toplevel

        session = object_session(self)
        if session is None:
            return (0, 0, 0)

        result = (
            session.query(
                func.count(ServerMetric.id),  # pylint: disable=not-callable
                func.sum(case((ServerMetric.is_success.is_(True), 1), else_=0)),
            )
            .filter(ServerMetric.server_id == self.id)
            .one()
        )

        total = result[0] or 0
        successful = result[1] or 0
        return (total, successful, total - successful)

    @hybrid_property
    def execution_count(self) -> int:
        """Number of ServerMetric records associated with this server instance.

        Returns:
            int: Count of ServerMetric records for this server.
        """
        return self._get_metric_counts()[0]

    @execution_count.expression
    @classmethod
    def execution_count(cls) -> Any:
        """SQL expression that counts ServerMetric rows for this server.

        Returns:
            Any: SQLAlchemy labeled count expression for server metrics.
        """
        return select(func.count(ServerMetric.id)).where(ServerMetric.server_id == cls.id).correlate(cls).scalar_subquery().label("execution_count")  # pylint: disable=not-callable

    @property
    def successful_executions(self) -> int:
        """Count of successful server invocations.

        Returns:
            int: The count of successful server invocations.
        """
        return self._get_metric_counts()[1]

    @property
    def failed_executions(self) -> int:
        """Count of failed server invocations.

        Returns:
            int: The count of failed server invocations.
        """
        return self._get_metric_counts()[2]

    @property
    def failure_rate(self) -> float:
        """Failure rate as a float between 0 and 1.

        Returns:
            float: The failure rate as a value between 0 and 1.
        """
        total, _, failed = self._get_metric_counts()
        return failed / total if total > 0 else 0.0

    @property
    def min_response_time(self) -> Optional[float]:
        """Minimum response time among all server invocations.

        Returns None if metrics are not loaded. Note: counts may be non-zero
        (via SQL) while timing is None. Use service layer converters for
        consistent metrics, or preload metrics via selectinload.

        Returns:
            Optional[float]: The minimum response time, or None.
        """
        if not self._metrics_loaded():
            return None
        times: List[float] = [m.response_time for m in self.metrics]
        return min(times) if times else None

    @property
    def max_response_time(self) -> Optional[float]:
        """Maximum response time among all server invocations.

        Returns None if metrics are not loaded. Note: counts may be non-zero
        (via SQL) while timing is None. Use service layer converters for
        consistent metrics, or preload metrics via selectinload.

        Returns:
            Optional[float]: The maximum response time, or None.
        """
        if not self._metrics_loaded():
            return None
        times: List[float] = [m.response_time for m in self.metrics]
        return max(times) if times else None

    @property
    def avg_response_time(self) -> Optional[float]:
        """Average response time among all server invocations.

        Returns None if metrics are not loaded. Note: counts may be non-zero
        (via SQL) while timing is None. Use service layer converters for
        consistent metrics, or preload metrics via selectinload.

        Returns:
            Optional[float]: The average response time, or None.
        """
        if not self._metrics_loaded():
            return None
        times: List[float] = [m.response_time for m in self.metrics]
        return sum(times) / len(times) if times else None

    @property
    def last_execution_time(self) -> Optional[datetime]:
        """Timestamp of the most recent server invocation.

        Returns None if metrics are not loaded. Note: counts may be non-zero
        (via SQL) while timing is None. Use service layer converters for
        consistent metrics, or preload metrics via selectinload.

        Returns:
            Optional[datetime]: The timestamp of the most recent invocation, or None.
        """
        if not self._metrics_loaded():
            return None
        if not self.metrics:
            return None
        return max(m.timestamp for m in self.metrics)

    @property
    def metrics_summary(self) -> Dict[str, Any]:
        """Aggregated metrics for the server.

        When metrics are loaded: computes all values from memory in a single pass.
        When not loaded: uses a single SQL query with aggregation for all fields.

        Returns:
            Dict[str, Any]: Dictionary containing aggregated metrics:
                - total_executions, successful_executions, failed_executions
                - failure_rate, min/max/avg_response_time, last_execution_time
        """
        if self._metrics_loaded():
            total = 0
            successful = 0
            min_rt: Optional[float] = None
            max_rt: Optional[float] = None
            sum_rt = 0.0
            last_time: Optional[datetime] = None

            for m in self.metrics:
                total += 1
                if m.is_success:
                    successful += 1
                rt = m.response_time
                if min_rt is None or rt < min_rt:
                    min_rt = rt
                if max_rt is None or rt > max_rt:
                    max_rt = rt
                sum_rt += rt
                if last_time is None or m.timestamp > last_time:
                    last_time = m.timestamp

            failed = total - successful
            return {
                "total_executions": total,
                "successful_executions": successful,
                "failed_executions": failed,
                "failure_rate": failed / total if total > 0 else 0.0,
                "min_response_time": min_rt,
                "max_response_time": max_rt,
                "avg_response_time": sum_rt / total if total > 0 else None,
                "last_execution_time": last_time,
            }

        # Third-Party
        from sqlalchemy import case  # pylint: disable=import-outside-toplevel
        from sqlalchemy.orm import object_session  # pylint: disable=import-outside-toplevel

        session = object_session(self)
        if session is None:
            return {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "failure_rate": 0.0,
                "min_response_time": None,
                "max_response_time": None,
                "avg_response_time": None,
                "last_execution_time": None,
            }

        result = (
            session.query(
                func.count(ServerMetric.id),  # pylint: disable=not-callable
                func.sum(case((ServerMetric.is_success.is_(True), 1), else_=0)),
                func.min(ServerMetric.response_time),  # pylint: disable=not-callable
                func.max(ServerMetric.response_time),  # pylint: disable=not-callable
                func.avg(ServerMetric.response_time),  # pylint: disable=not-callable
                func.max(ServerMetric.timestamp),  # pylint: disable=not-callable
            )
            .filter(ServerMetric.server_id == self.id)
            .one()
        )

        total = result[0] or 0
        successful = result[1] or 0
        failed = total - successful

        return {
            "total_executions": total,
            "successful_executions": successful,
            "failed_executions": failed,
            "failure_rate": failed / total if total > 0 else 0.0,
            "min_response_time": result[2],
            "max_response_time": result[3],
            "avg_response_time": float(result[4]) if result[4] is not None else None,
            "last_execution_time": result[5],
        }

    # Team scoping fields for resource organization
    team_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("email_teams.id", ondelete="SET NULL"), nullable=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="public")
    __table_args__ = (
        UniqueConstraint("team_id", "owner_email", "name", name="uq_team_owner_name_server"),
        Index("idx_servers_created_at_id", "created_at", "id"),
    )


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
    tools: Mapped[List["Tool"]] = relationship(back_populates="gateway", foreign_keys="Tool.gateway_id", cascade="all, delete-orphan", passive_deletes=True)

    # Relationship with local prompts this gateway provides
    prompts: Mapped[List["Prompt"]] = relationship(back_populates="gateway", cascade="all, delete-orphan", passive_deletes=True)

    # Relationship with local resources this gateway provides
    resources: Mapped[List["Resource"]] = relationship(back_populates="gateway", cascade="all, delete-orphan", passive_deletes=True)

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

    __table_args__ = (
        UniqueConstraint("team_id", "owner_email", "slug", name="uq_team_owner_slug_gateway"),
        Index("idx_gateways_created_at_id", "created_at", "id"),
    )


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

    logger.info("Gateway name changed for ID %s. Issuing bulk update for tools.", target.id)

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


@event.listens_for(Gateway, "after_update")
def update_prompt_names_on_gateway_update(_mapper, connection, target):
    """Update prompt names when a gateway name changes.

    Args:
        _mapper: SQLAlchemy mapper for the Gateway model.
        connection: Database connection for the update transaction.
        target: Gateway instance being updated.
    """
    if not get_history(target, "name").has_changes():
        return

    logger.info("Gateway name changed for ID %s. Issuing bulk update for prompts.", target.id)

    prompts_table = Prompt.__table__
    new_gateway_slug = slugify(target.name)
    separator = settings.gateway_tool_name_separator

    stmt = (
        cast(Any, prompts_table)
        .update()
        .where(prompts_table.c.gateway_id == target.id)
        .values(name=new_gateway_slug + separator + prompts_table.c.custom_name_slug)
        .execution_options(synchronize_session=False)
    )

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
    __table_args__ = (
        UniqueConstraint("team_id", "owner_email", "slug", name="uq_team_owner_slug_a2a_agent"),
        Index("idx_a2a_agents_created_at_id", "created_at", "id"),
    )

    # Relationship with OAuth tokens
    # oauth_tokens: Mapped[List["OAuthToken"]] = relationship("OAuthToken", back_populates="gateway", cascade="all, delete-orphan")

    # Relationship with registered OAuth clients (DCR)
    # registered_oauth_clients: Mapped[List["RegisteredOAuthClient"]] = relationship("RegisteredOAuthClient", back_populates="gateway", cascade="all, delete-orphan")

    def _metrics_loaded(self) -> bool:
        """Check if metrics relationship is loaded without triggering lazy load.

        Returns:
            bool: True if metrics are loaded, False otherwise.
        """
        return "metrics" in sa_inspect(self).dict

    @property
    def execution_count(self) -> int:
        """Total number of interactions with this agent.
        Returns 0 if metrics are not loaded (avoids lazy loading).

        Returns:
            int: The total count of interactions.
        """
        if not self._metrics_loaded():
            return 0
        return len(self.metrics)

    @property
    def successful_executions(self) -> int:
        """Number of successful interactions.
        Returns 0 if metrics are not loaded (avoids lazy loading).

        Returns:
            int: The count of successful interactions.
        """
        if not self._metrics_loaded():
            return 0
        return sum(1 for m in self.metrics if m.is_success)

    @property
    def failed_executions(self) -> int:
        """Number of failed interactions.
        Returns 0 if metrics are not loaded (avoids lazy loading).

        Returns:
            int: The count of failed interactions.
        """
        if not self._metrics_loaded():
            return 0
        return sum(1 for m in self.metrics if not m.is_success)

    @property
    def failure_rate(self) -> float:
        """Failure rate as a percentage.
        Returns 0.0 if metrics are not loaded (avoids lazy loading).

        Returns:
            float: The failure rate percentage.
        """
        if not self._metrics_loaded():
            return 0.0
        if not self.metrics:
            return 0.0
        return (self.failed_executions / len(self.metrics)) * 100

    @property
    def avg_response_time(self) -> Optional[float]:
        """Average response time in seconds.
        Returns None if metrics are not loaded (avoids lazy loading).

        Returns:
            Optional[float]: The average response time, or None if no metrics.
        """
        if not self._metrics_loaded():
            return None
        if not self.metrics:
            return None
        return sum(m.response_time for m in self.metrics) / len(self.metrics)

    @property
    def last_execution_time(self) -> Optional[datetime]:
        """Timestamp of the most recent interaction.
        Returns None if metrics are not loaded (avoids lazy loading).

        Returns:
            Optional[datetime]: The timestamp of the last interaction, or None if no metrics.
        """
        if not self._metrics_loaded():
            return None
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

    Commits the transaction on successful completion to avoid implicit rollbacks
    for read-only operations. Rolls back explicitly on exception.

    Yields:
        SessionLocal: A SQLAlchemy database session.

    Raises:
        Exception: Re-raises any exception after rolling back the transaction.

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
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            try:
                db.invalidate()
            except Exception:
                pass  # nosec B110 - Best effort cleanup on connection failure
        raise
    finally:
        db.close()


@contextmanager
def fresh_db_session() -> Generator[Session, Any, None]:
    """Get a fresh database session for isolated operations.

    Use this when you need a new session independent of the request lifecycle,
    such as for metrics recording after releasing the main session.

    This is a synchronous context manager that creates a new database session
    from the SessionLocal factory. The session is automatically committed on
    successful exit or rolled back on exception, then closed.

    Note: Prior to this fix, sessions were closed without commit, causing
    PostgreSQL to implicitly rollback all transactions (even read-only SELECTs).
    This was causing ~40% rollback rate under load.

    Yields:
        Session: A fresh SQLAlchemy database session.

    Raises:
        Exception: Any exception raised during database operations is re-raised
            after rolling back the transaction.

    Examples:
        >>> from mcpgateway.db import fresh_db_session
        >>> with fresh_db_session() as db:
        ...     hasattr(db, 'query')
        True
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()  # Commit on successful exit (even for read-only operations)
    except Exception:
        try:
            db.rollback()  # Explicit rollback on exception
        except Exception:
            try:
                db.invalidate()  # Connection broken, discard from pool
            except Exception:
                pass  # nosec B110 - Best effort cleanup on connection failure
        raise
    finally:
        db.close()


def patch_string_columns_for_mariadb(base, engine_) -> None:
    """
    MariaDB requires VARCHAR to have an explicit length.
    Auto-assign VARCHAR(255) to any String() columns without a length.

    Args:
        base (DeclarativeBase): SQLAlchemy Declarative Base containing metadata.
        engine_ (Engine): SQLAlchemy engine, used to detect MariaDB dialect.
    """
    if engine_.dialect.name != "mariadb":
        return

    for table in base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, String) and column.type.length is None:
                # Replace with VARCHAR(255)
                column.type = VARCHAR(255)


def extract_json_field(column, json_path: str):
    """Extract a JSON field in a database-agnostic way.

    This function provides cross-database compatibility for JSON field extraction,
    supporting both SQLite and PostgreSQL backends.

    Args:
        column: SQLAlchemy column containing JSON data
        json_path: JSON path in SQLite format (e.g., '$.\"tool.name\"')

    Returns:
        SQLAlchemy expression for extracting the JSON field as text

    Note:
        - For SQLite: Uses json_extract(column, '$.\"key\"')
        - For PostgreSQL: Uses column ->> 'key' operator
        - Backend-specific behavior is tested via unit tests in test_db.py
    """

    if backend == "postgresql":
        # PostgreSQL uses ->> operator for text extraction
        # Convert $.\"key\" or $.\"nested.key\" format to just the key
        # Handle both simple keys and nested keys with dots
        path_key = json_path.replace('$."', "").replace('"', "")
        return column.op("->>")(path_key)

    # SQLite and other databases use json_extract function
    # Keep the original $.\"key\" format
    return func.json_extract(column, json_path)


# Create all tables
def init_db():
    """
    Initialize database tables.

    Raises:
        Exception: If database initialization fails.
    """
    try:
        # Apply MariaDB compatibility fix
        patch_string_columns_for_mariadb(Base, engine)

        # Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
    except SQLAlchemyError as e:
        raise Exception(f"Failed to initialize database: {str(e)}")


# ============================================================================
# Structured Logging Models
# ============================================================================


class StructuredLogEntry(Base):
    """Structured log entry for comprehensive logging and analysis.

    Stores all log entries with correlation IDs, performance metrics,
    and security context for advanced search and analytics.
    """

    __tablename__ = "structured_log_entries"

    # Primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)

    # Timestamps
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utc_now)

    # Correlation and request tracking
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)

    # Log metadata
    level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    component: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    logger: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # User and request context
    user_id: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    client_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)  # IPv6 max length
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    request_method: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Performance data
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    operation_type: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)

    # Security context
    is_security_event: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    security_severity: Mapped[Optional[str]] = mapped_column(String(20), index=True, nullable=True)  # LOW, MEDIUM, HIGH, CRITICAL
    threat_indicators: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Structured context data
    context: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error_details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    performance_metrics: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # System information
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    process_id: Mapped[int] = mapped_column(Integer, nullable=False)
    thread_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    environment: Mapped[str] = mapped_column(String(50), nullable=False, default="production")

    # OpenTelemetry trace context
    trace_id: Mapped[Optional[str]] = mapped_column(String(32), index=True, nullable=True)
    span_id: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # Indexes for performance
    __table_args__ = (
        Index("idx_log_correlation_time", "correlation_id", "timestamp"),
        Index("idx_log_user_time", "user_id", "timestamp"),
        Index("idx_log_level_time", "level", "timestamp"),
        Index("idx_log_component_time", "component", "timestamp"),
        Index("idx_log_security", "is_security_event", "security_severity", "timestamp"),
        Index("idx_log_operation", "operation_type", "timestamp"),
        Index("idx_log_trace", "trace_id", "timestamp"),
    )


class PerformanceMetric(Base):
    """Aggregated performance metrics from log analysis.

    Stores time-windowed aggregations of operation performance
    for analytics and trend analysis.
    """

    __tablename__ = "performance_metrics"

    # Primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)

    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utc_now)

    # Metric identification
    operation_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    component: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Aggregated metrics
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Duration metrics (in milliseconds)
    avg_duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    min_duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    max_duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    p50_duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    p95_duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    p99_duration_ms: Mapped[float] = mapped_column(Float, nullable=False)

    # Time window
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)

    # Additional context
    metric_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("idx_perf_operation_time", "operation_type", "window_start"),
        Index("idx_perf_component_time", "component", "window_start"),
        Index("idx_perf_window", "window_start", "window_end"),
    )


class SecurityEvent(Base):
    """Security event logging for threat detection and audit trails.

    Specialized table for security events with enhanced context
    and threat analysis capabilities.
    """

    __tablename__ = "security_events"

    # Primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)

    # Timestamps
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utc_now)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Correlation tracking
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    log_entry_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("structured_log_entries.id"), index=True, nullable=True)

    # Event classification
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)  # auth_failure, suspicious_activity, rate_limit, etc.
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # LOW, MEDIUM, HIGH, CRITICAL
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # authentication, authorization, data_access, etc.

    # User and request context
    user_id: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    client_ip: Mapped[str] = mapped_column(String(45), nullable=False, index=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Event details
    description: Mapped[str] = mapped_column(Text, nullable=False)
    action_taken: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # blocked, allowed, flagged, etc.

    # Threat analysis
    threat_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # 0.0-1.0
    threat_indicators: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    failed_attempts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Resolution tracking
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Alert tracking
    alert_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    alert_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    alert_recipients: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    # Additional context
    context: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("idx_security_type_time", "event_type", "timestamp"),
        Index("idx_security_severity_time", "severity", "timestamp"),
        Index("idx_security_user_time", "user_id", "timestamp"),
        Index("idx_security_ip_time", "client_ip", "timestamp"),
        Index("idx_security_unresolved", "resolved", "severity", "timestamp"),
    )


# ---------------------------------------------------------------------------
# LLM Provider Configuration Models
# ---------------------------------------------------------------------------


class LLMProviderType:
    """Constants for LLM provider types."""

    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    ANTHROPIC = "anthropic"
    BEDROCK = "bedrock"
    GOOGLE_VERTEX = "google_vertex"
    WATSONX = "watsonx"
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"
    COHERE = "cohere"
    MISTRAL = "mistral"
    GROQ = "groq"
    TOGETHER = "together"

    @classmethod
    def get_all_types(cls) -> List[str]:
        """Get list of all supported provider types.

        Returns:
            List of provider type strings.
        """
        return [
            cls.OPENAI,
            cls.AZURE_OPENAI,
            cls.ANTHROPIC,
            cls.BEDROCK,
            cls.GOOGLE_VERTEX,
            cls.WATSONX,
            cls.OLLAMA,
            cls.OPENAI_COMPATIBLE,
            cls.COHERE,
            cls.MISTRAL,
            cls.GROQ,
            cls.TOGETHER,
        ]

    @classmethod
    def get_provider_defaults(cls) -> Dict[str, Dict[str, Any]]:
        """Get default configuration for each provider type.

        Returns:
            Dictionary mapping provider type to default config.
        """
        return {
            cls.OPENAI: {
                "api_base": "https://api.openai.com/v1",
                "default_model": "gpt-4o",
                "supports_model_list": True,
                "models_endpoint": "/models",
                "requires_api_key": True,
                "description": "OpenAI GPT models (GPT-4, GPT-4o, etc.)",
            },
            cls.AZURE_OPENAI: {
                "api_base": "https://{resource}.openai.azure.com/openai/deployments/{deployment}",
                "default_model": "",
                "supports_model_list": False,
                "requires_api_key": True,
                "description": "Azure OpenAI Service",
            },
            cls.ANTHROPIC: {
                "api_base": "https://api.anthropic.com",
                "default_model": "claude-sonnet-4-20250514",
                "supports_model_list": False,
                "requires_api_key": True,
                "description": "Anthropic Claude models",
            },
            cls.OLLAMA: {
                "api_base": "http://localhost:11434/v1",
                "default_model": "llama3.2",
                "supports_model_list": True,
                "models_endpoint": "/models",
                "requires_api_key": False,
                "description": "Local Ollama server (OpenAI-compatible)",
            },
            cls.OPENAI_COMPATIBLE: {
                "api_base": "http://localhost:8080/v1",
                "default_model": "",
                "supports_model_list": True,
                "models_endpoint": "/models",
                "requires_api_key": False,
                "description": "Any OpenAI-compatible API server",
            },
            cls.COHERE: {
                "api_base": "https://api.cohere.ai/v1",
                "default_model": "command-r-plus",
                "supports_model_list": True,
                "models_endpoint": "/models",
                "requires_api_key": True,
                "description": "Cohere Command models",
            },
            cls.MISTRAL: {
                "api_base": "https://api.mistral.ai/v1",
                "default_model": "mistral-large-latest",
                "supports_model_list": True,
                "models_endpoint": "/models",
                "requires_api_key": True,
                "description": "Mistral AI models",
            },
            cls.GROQ: {
                "api_base": "https://api.groq.com/openai/v1",
                "default_model": "llama-3.3-70b-versatile",
                "supports_model_list": True,
                "models_endpoint": "/models",
                "requires_api_key": True,
                "description": "Groq high-speed inference",
            },
            cls.TOGETHER: {
                "api_base": "https://api.together.xyz/v1",
                "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
                "supports_model_list": True,
                "models_endpoint": "/models",
                "requires_api_key": True,
                "description": "Together AI inference",
            },
            cls.BEDROCK: {
                "api_base": "",
                "default_model": "anthropic.claude-3-sonnet-20240229-v1:0",
                "supports_model_list": False,
                "requires_api_key": False,
                "description": "AWS Bedrock (uses IAM credentials)",
            },
            cls.GOOGLE_VERTEX: {
                "api_base": "",
                "default_model": "gemini-1.5-pro",
                "supports_model_list": False,
                "requires_api_key": False,
                "description": "Google Vertex AI (uses service account)",
            },
            cls.WATSONX: {
                "api_base": "https://us-south.ml.cloud.ibm.com",
                "default_model": "ibm/granite-13b-chat-v2",
                "supports_model_list": False,
                "requires_api_key": True,
                "description": "IBM watsonx.ai",
            },
        }


class LLMProvider(Base):
    """ORM model for LLM provider configurations.

    Stores credentials and settings for external LLM providers
    used by the internal LLM Chat feature.

    Attributes:
        id: Unique identifier (UUID)
        name: Display name (unique)
        slug: URL-safe identifier (unique)
        provider_type: Provider type (openai, anthropic, etc.)
        api_key: Encrypted API key
        api_base: Base URL for API requests
        api_version: API version (for Azure OpenAI)
        config: Provider-specific settings (JSON)
        default_model: Default model ID
        default_temperature: Default temperature (0.0-2.0)
        default_max_tokens: Default max tokens
        enabled: Whether provider is enabled
        health_status: Current health status (healthy/unhealthy/unknown)
        last_health_check: Last health check timestamp
        plugin_ids: Attached plugin IDs (JSON)
    """

    __tablename__ = "llm_providers"

    # Primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)

    # Basic info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Provider type
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Credentials (encrypted)
    api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    api_base: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    api_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Provider-specific configuration
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Default settings
    default_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    default_temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    default_max_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Status
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    health_status: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    last_health_check: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Plugin integration
    plugin_ids: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Audit fields
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    modified_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    models: Mapped[List["LLMModel"]] = relationship("LLMModel", back_populates="provider", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("name", name="uq_llm_providers_name"),
        UniqueConstraint("slug", name="uq_llm_providers_slug"),
        Index("idx_llm_providers_enabled", "enabled"),
        Index("idx_llm_providers_type", "provider_type"),
        Index("idx_llm_providers_health", "health_status"),
    )

    def __repr__(self) -> str:
        """Return string representation.

        Returns:
            String representation of the provider.
        """
        return f"<LLMProvider(id='{self.id}', name='{self.name}', type='{self.provider_type}')>"


class LLMModel(Base):
    """ORM model for LLM model definitions.

    Stores model metadata and capabilities for each provider.

    Attributes:
        id: Unique identifier (UUID)
        provider_id: Foreign key to llm_providers
        model_id: Provider's model ID (e.g., gpt-4o)
        model_name: Display name
        model_alias: Optional routing alias
        supports_chat: Whether model supports chat completions
        supports_streaming: Whether model supports streaming
        supports_function_calling: Whether model supports function/tool calling
        supports_vision: Whether model supports vision/images
        context_window: Maximum context tokens
        max_output_tokens: Maximum output tokens
        enabled: Whether model is enabled
        deprecated: Whether model is deprecated
    """

    __tablename__ = "llm_models"

    # Primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)

    # Provider relationship
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("llm_providers.id", ondelete="CASCADE"), nullable=False)

    # Model identification
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_alias: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Capabilities
    supports_chat: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supports_streaming: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supports_function_calling: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Limits
    context_window: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Status
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Relationship
    provider: Mapped["LLMProvider"] = relationship("LLMProvider", back_populates="models")

    __table_args__ = (
        UniqueConstraint("provider_id", "model_id", name="uq_llm_models_provider_model"),
        Index("idx_llm_models_provider", "provider_id"),
        Index("idx_llm_models_enabled", "enabled"),
        Index("idx_llm_models_deprecated", "deprecated"),
    )

    def __repr__(self) -> str:
        """Return string representation.

        Returns:
            String representation of the model.
        """
        return f"<LLMModel(id='{self.id}', model_id='{self.model_id}', provider_id='{self.provider_id}')>"


class AuditTrail(Base):
    """Comprehensive audit trail for data access and changes.

    Tracks all significant system changes and data access for
    compliance and security auditing.
    """

    __tablename__ = "audit_trails"

    # Primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)

    # Timestamps
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utc_now)

    # Correlation tracking
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)

    # Action details
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)  # create, read, update, delete, execute, etc.
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)  # tool, resource, prompt, user, etc.
    resource_id: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    resource_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # User context
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    team_id: Mapped[Optional[str]] = mapped_column(String(36), index=True, nullable=True)

    # Request context
    client_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    request_method: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Change tracking
    old_values: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    new_values: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    changes: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Data classification
    data_classification: Mapped[Optional[str]] = mapped_column(String(50), index=True, nullable=True)  # public, internal, confidential, restricted
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)

    # Result
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Additional context
    context: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("idx_audit_action_time", "action", "timestamp"),
        Index("idx_audit_resource_time", "resource_type", "resource_id", "timestamp"),
        Index("idx_audit_user_time", "user_id", "timestamp"),
        Index("idx_audit_classification", "data_classification", "timestamp"),
        Index("idx_audit_review", "requires_review", "timestamp"),
    )


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


@event.listens_for(LLMProvider, "before_insert")
def set_llm_provider_slug(_mapper, _conn, target):
    """Set the slug for an LLMProvider before insert.

    Args:
        _mapper: Mapper
        _conn: Connection
        target: Target LLMProvider instance
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


@event.listens_for(Prompt, "before_insert")
@event.listens_for(Prompt, "before_update")
def set_prompt_name_and_slug(mapper, connection, target):  # pylint: disable=unused-argument
    """Set name fields for Prompt before insert/update.

    - Sets original_name from name if missing (legacy compatibility).
    - Sets custom_name to original_name if not provided.
    - Sets display_name to custom_name if not provided.
    - Calculates custom_name_slug from custom_name.
    - Updates name to gateway_slug + separator + custom_name_slug.

    Args:
        mapper: SQLAlchemy mapper for the Prompt model.
        connection: Database connection for the insert/update.
        target: Prompt instance being inserted or updated.
    """
    if not target.original_name:
        target.original_name = target.name
    if not target.custom_name:
        target.custom_name = target.original_name
    if not target.display_name:
        target.display_name = target.custom_name
    target.custom_name_slug = slugify(target.custom_name)
    gateway_slug = slugify(target.gateway.name) if target.gateway else ""
    if gateway_slug:
        sep = settings.gateway_tool_name_separator
        target.name = f"{gateway_slug}{sep}{target.custom_name_slug}"
    else:
        target.name = target.custom_name_slug
