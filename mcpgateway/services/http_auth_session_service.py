# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/http_auth_session_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Prakhar Singh



This service manages HTTP authentication sessions with enhanced security features
including timeouts, client binding, concurrent session limits, and audit trails.
Implements the SessionRegistry pattern from the issue architecture diagram.

Hybrid Redis + Database Architecture:
- Redis: Hot path for fast session validation and activity updates
- Database: Cold path for UI queries, audit trail, and durability
- Write path: Both Redis and DB updated
- Read path: Redis first, DB fallback
"""

# Standard
from datetime import datetime, timedelta, timezone
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

# Third-Party
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import HttpAuthSession, SessionLocal, utc_now
from mcpgateway.services.audit_trail_service import AuditTrailService
from mcpgateway.utils.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# Redis key prefixes for HTTP auth sessions
REDIS_SESSION_PREFIX = "http_auth:session:"
REDIS_USER_SESSIONS_PREFIX = "http_auth:user:"

# Security: Maximum length for user-agent strings in logs to prevent PII exposure
USER_AGENT_LOG_MAX_LENGTH = 100

# Security: Maximum length for user-agent strings in database to prevent abuse
USER_AGENT_DB_MAX_LENGTH = 500


def sanitize_user_agent(user_agent: str, max_length: int = USER_AGENT_DB_MAX_LENGTH) -> str:
    """Sanitize and truncate user-agent string before database storage.

    Removes control characters and limits length to prevent:
    - Extremely long strings that could cause performance issues
    - Control characters that could cause display/logging issues
    - Potential injection attacks via malformed user-agent strings

    Args:
        user_agent: Raw user-agent string from HTTP headers
        max_length: Maximum allowed length (default: 500 characters)

    Returns:
        Sanitized user-agent string, safe for database storage

    Example:
        >>> sanitize_user_agent("Mozilla/5.0\\x00\\x01 Test")
        'Mozilla/5.0 Test'
        >>> sanitize_user_agent("A" * 1000)[:10]
        'AAAAAAAAAA'
    """
    if not user_agent:
        return "unknown"

    # Remove control characters (ASCII 0-31 and 127) but keep printable chars
    sanitized = "".join(c for c in user_agent if c.isprintable())

    # Truncate to maximum length
    return sanitized[:max_length]


def sanitize_user_agent_for_logging(user_agent: Optional[str]) -> Optional[str]:
    """Sanitize and truncate user-agent string for logging.

    Consistently truncates user-agent strings to prevent PII exposure
    and log injection in all logging statements.

    Args:
        user_agent: User-agent string to sanitize

    Returns:
        Truncated user-agent string safe for logging, or None if input is None

    Example:
        >>> sanitize_user_agent_for_logging("Mozilla/5.0 " + "A" * 200)[:20]
        'Mozilla/5.0 AAAAAAAA'
    """
    if user_agent is None:
        return None
    return user_agent[:USER_AGENT_LOG_MAX_LENGTH]


def validate_ip_address(ip: str) -> str:
    """Validate and sanitize IP address.

    Args:
        ip: IP address string to validate

    Returns:
        Validated IP address or "unknown" if invalid

    Example:
        >>> validate_ip_address("192.168.1.1")
        '192.168.1.1'
        >>> validate_ip_address("invalid")
        'unknown'
    """
    if not ip:
        return "unknown"

    try:
        # Standard
        import ipaddress

        ipaddress.ip_address(ip)
        return ip
    except (ValueError, AttributeError):
        return "unknown"


async def create_http_auth_session(db: Session, user_email: str, request, context: str = "authentication") -> Optional[str]:
    """Create HTTP auth session with consistent error handling.

    This helper function eliminates code duplication across authentication flows
    (login, registration, admin login) by centralizing session creation logic.

    Args:
        db: Database session
        user_email: User's email address
        request: FastAPI Request object for extracting client info
        context: Context string for logging (e.g., "authentication", "registration")

    Returns:
        Session ID (jti) if session tracking is enabled and creation succeeds,
        None if session tracking is disabled

    Raises:
        HTTPException: If session tracking is enabled but session creation fails

    Example:
        >>> session_id = await create_http_auth_session(db, user.email, request, "login")
        >>> token, _ = await create_access_token(user, jti=session_id)
    """
    if not settings.session_tracking_enabled:
        return None

    try:
        # Extract and sanitize client info from request
        raw_ip = request.client.host if request.client else "unknown"
        ip_address = validate_ip_address(raw_ip)

        raw_user_agent = request.headers.get("user-agent", "unknown")
        user_agent = sanitize_user_agent(raw_user_agent)

        session_service = HttpAuthSessionService(db)
        session = await session_service.add_session(
            user_email=user_email,
            ip_address=ip_address,
            user_agent=user_agent,
            device_info={},  # Device info parsing not implemented yet
        )
        session_id = session.session_id
        logger.debug(f"Created session {session_id} for {context}: {user_email}")
        return session_id

    except Exception as exc:
        logger.error(f"Failed to create session for {context} ({user_email}): {exc}")
        # Rollback transaction to prevent partial state
        try:
            db.rollback()
        except Exception as rollback_error:
            logger.debug(f"Rollback failed during cleanup: {rollback_error}")
        # Import here to avoid circular dependency
        # Third-Party
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Session creation failed. Please try again.",
        ) from exc


class HttpAuthSessionService:
    """Service for managing HTTP authentication sessions (SessionRegistry).

    Implements the SessionRegistry pattern from Issue #541 for HTTP auth sessions:
    - Session lifecycle management (add, get, remove, list)
    - Timeout enforcement (idle and absolute)
    - Concurrent session limits with LRU eviction
    - Session binding validation (IP, user-agent)
    - Audit trail support

    Attributes:
        sessions: Dict - Stored in database (HttpAuthSession table)
        max_per_user: int - From settings.max_sessions_per_user
        idle_timeout: int - From settings.session_idle_timeout_minutes
        absolute_timeout: int - From settings.session_absolute_timeout_minutes
    """

    def __init__(self, db: Optional[Session] = None):
        """Initialize the session service.

        Args:
            db: Optional database session. If not provided, creates a new one.
        """
        self.db = db
        self._owns_db = db is None
        if self._owns_db:
            self.db = SessionLocal()

        # Cache Redis availability check to avoid repeated setting lookups
        self._redis_enabled = settings.cache_type == "redis" and bool(settings.redis_url)

        # Initialize audit trail service for enterprise logging
        self._audit_service = AuditTrailService()

    def __enter__(self):
        """Context manager entry.

        Returns:
            HttpAuthSessionService: Self for context manager protocol
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup database session if we own it.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred
        """
        if self._owns_db and self.db:
            self.db.close()

    async def _get_redis_client(self) -> Any:
        """Get Redis client if available and enabled.

        Returns:
            Redis client or None if Redis is disabled or unavailable
        """
        # Fast path: Skip Redis entirely if not configured
        if not self._redis_enabled:
            return None

        try:
            return await get_redis_client()
        except Exception as e:
            logger.warning(f"Failed to get Redis client for HTTP auth sessions: {e}")
            return None

    async def _cache_session_to_redis(self, session: HttpAuthSession) -> bool:
        """Cache session data to Redis with TTL.

        Args:
            session: HttpAuthSession instance to cache

        Returns:
            True if cached successfully, False otherwise
        """
        redis = await self._get_redis_client()
        if not redis:
            return False

        try:
            # Ensure timestamps are timezone-aware before converting to Unix timestamp
            # SQLite may return naive datetimes, which .timestamp() interprets as local time
            created_at = session.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            last_activity = session.last_activity
            if last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)

            # Serialize session data
            session_data = {
                "session_id": session.session_id,
                "user_email": session.user_email,
                "user_id": session.user_id,
                "created_at": created_at.timestamp(),
                "last_activity": last_activity.timestamp(),
                "ip_address": session.ip_address,
                "user_agent": session.user_agent,
                "device_info": json.dumps(session.device_info) if session.device_info else "{}",
            }

            # Store in Redis hash
            redis_key = f"{REDIS_SESSION_PREFIX}{session.session_id}"
            await redis.hset(redis_key, mapping=session_data)

            # Set TTL based on absolute timeout
            if settings.session_absolute_timeout_minutes > 0:
                ttl_seconds = settings.session_absolute_timeout_minutes * 60
                await redis.expire(redis_key, ttl_seconds)

            # Add to user's session set
            user_sessions_key = f"{REDIS_USER_SESSIONS_PREFIX}{session.user_email}:sessions"
            await redis.sadd(user_sessions_key, session.session_id)

            logger.debug(f"Cached session {session.session_id} to Redis")
            return True

        except Exception as e:
            logger.warning(f"Failed to cache session {session.session_id} to Redis: {e}")
            return False

    async def _get_session_from_redis(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve session data from Redis.

        Args:
            session_id: Session identifier

        Returns:
            Session data dict or None if not found
        """
        redis = await self._get_redis_client()
        if not redis:
            return None

        try:
            redis_key = f"{REDIS_SESSION_PREFIX}{session_id}"
            session_data = await redis.hgetall(redis_key)

            if not session_data:
                return None

            # Deserialize timestamps
            return {
                "session_id": session_data.get("session_id"),
                "user_email": session_data.get("user_email"),
                "user_id": session_data.get("user_id"),
                "created_at": float(session_data.get("created_at", 0)),
                "last_activity": float(session_data.get("last_activity", 0)),
                "ip_address": session_data.get("ip_address"),
                "user_agent": session_data.get("user_agent"),
                "device_info": json.loads(session_data.get("device_info", "{}")),
            }

        except Exception as e:
            logger.warning(f"Failed to get session {session_id} from Redis: {e}")
            return None

    async def _update_session_activity_in_redis(self, session_id: str) -> bool:
        """Update last_activity timestamp in Redis.

        Args:
            session_id: Session identifier

        Returns:
            True if updated successfully, False otherwise
        """
        redis = await self._get_redis_client()
        if not redis:
            return False

        try:
            redis_key = f"{REDIS_SESSION_PREFIX}{session_id}"
            now_timestamp = time.time()
            await redis.hset(redis_key, "last_activity", now_timestamp)

            logger.debug(f"Updated last_activity for session {session_id} in Redis")
            return True

        except Exception as e:
            logger.warning(f"Failed to update session {session_id} activity in Redis: {e}")
            return False

    async def _delete_session_from_redis(self, session_id: str, user_email: Optional[str] = None) -> bool:
        """Delete session from Redis.

        Args:
            session_id: Session identifier
            user_email: Optional user email to remove from user sessions set

        Returns:
            True if deleted successfully, False otherwise
        """
        redis = await self._get_redis_client()
        if not redis:
            return False

        try:
            # Delete session hash
            redis_key = f"{REDIS_SESSION_PREFIX}{session_id}"
            await redis.delete(redis_key)

            # Remove from user's session set if email provided
            if user_email:
                user_sessions_key = f"{REDIS_USER_SESSIONS_PREFIX}{user_email}:sessions"
                await redis.srem(user_sessions_key, session_id)

            logger.debug(f"Deleted session {session_id} from Redis")
            return True

        except Exception as e:
            logger.warning(f"Failed to delete session {session_id} from Redis: {e}")
            return False

    async def add_session(
        self,
        user_email: str,
        ip_address: str,
        user_agent: str,
        device_info: Optional[Dict[str, Any]] = None,
    ) -> HttpAuthSession:
        """Create a new HTTP auth session.

        Enforces max_sessions_per_user limit using LRU eviction.

        Args:
            user_email: User's email address
            ip_address: Client IP address
            user_agent: Client user-agent string
            device_info: Optional parsed device metadata

        Returns:
            Created HttpAuthSession instance
        """
        # Generate unique session ID
        session_id = str(uuid.uuid4())

        # Enforce concurrent session limits
        logger.debug(
            f"[SESSION_LIMIT] Creating new session for {user_email}. Max sessions per user: {settings.max_sessions_per_user}",
            extra={"user_email": user_email, "max_sessions": settings.max_sessions_per_user},
        )
        if settings.max_sessions_per_user > 0:
            await self.enforce_limits(user_email)
        else:
            logger.debug("[SESSION_LIMIT] Session limits disabled (max_sessions_per_user=0)")

        # Create new session
        now = utc_now()

        session = HttpAuthSession(
            session_id=session_id,
            user_id=user_email,
            user_email=user_email,
            created_at=now,
            last_activity=now,
            ip_address=ip_address,
            user_agent=user_agent,
            device_info=device_info or {},
        )

        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        # Cache to Redis
        try:
            await self._cache_session_to_redis(session)
        except Exception as e:
            logger.warning(f"Failed to cache session {session_id} to Redis: {e}")

        logger.debug(
            f"Created HTTP auth session {session_id} for user {user_email} from {ip_address}",
            extra={
                "session_id": session_id,
                "user_email": user_email,
                "ip_address": ip_address,
                "user_agent": sanitize_user_agent_for_logging(user_agent),
            },
        )

        # Enterprise audit logging: Session creation
        self._audit_service.log_action(
            action="CREATE",
            resource_type="http_auth_session",
            resource_id=session_id,
            user_id=user_email,
            user_email=user_email,
            client_ip=ip_address,
            user_agent=sanitize_user_agent_for_logging(user_agent),
            data_classification="confidential",
            success=True,
            context={
                "event_type": "session_created",
                "session_id": session_id,
                "ip_address": ip_address,
                "user_agent": sanitize_user_agent_for_logging(user_agent),
                "device_info": device_info or {},
            },
            details={
                "created_at": now.isoformat(),
                "max_sessions_per_user": settings.max_sessions_per_user,
                "idle_timeout_minutes": settings.session_idle_timeout_minutes,
                "absolute_timeout_minutes": settings.session_absolute_timeout_minutes,
            },
            db=self.db,
        )

        return session

    async def get_session(self, session_id: str, client_ip: Optional[str] = None, user_agent: Optional[str] = None) -> Optional[HttpAuthSession]:
        """Retrieve a session by ID and validate binding.

        Hybrid approach: Check Redis first for fast path, fallback to DB.

        Args:
            session_id: Session identifier
            client_ip: Client IP address for binding validation (optional)
            user_agent: User-Agent string for binding validation (optional)

        Returns:
            HttpAuthSession if found and valid, None otherwise
        """
        # Try Redis first (hot path)
        session = None
        try:
            redis_data = await self._get_session_from_redis(session_id)

            if redis_data:
                # Reconstruct session object from Redis data for validation
                session = HttpAuthSession(
                    session_id=redis_data["session_id"],
                    user_id=redis_data["user_id"],
                    user_email=redis_data["user_email"],
                    created_at=datetime.fromtimestamp(redis_data["created_at"], tz=timezone.utc),
                    last_activity=datetime.fromtimestamp(redis_data["last_activity"], tz=timezone.utc),
                    ip_address=redis_data["ip_address"],
                    user_agent=redis_data["user_agent"],
                    device_info=redis_data["device_info"],
                )
                logger.debug(f"Session {session_id} retrieved from Redis")
        except Exception as e:
            logger.debug(f"Redis lookup failed for session {session_id}, falling back to DB: {e}")

        # Fallback to database if not in Redis
        if not session:
            session = self.db.query(HttpAuthSession).filter(HttpAuthSession.session_id == session_id).first()
            if session:
                logger.debug(f"Session {session_id} retrieved from DB, caching to Redis")
                # Cache to Redis for next time
                try:
                    await self._cache_session_to_redis(session)
                except Exception as e:
                    logger.warning(f"Failed to cache session {session_id} to Redis: {e}")

        if not session:
            return None

        # Check if session is expired
        is_expired, reason = self._is_session_expired(session)
        if is_expired:
            logger.debug(
                f"Session {session_id} expired: {reason}",
                extra={"session_id": session_id, "reason": reason},
            )
            await self.terminate_session(session_id, reason=reason or "expired")
            return None

        # Phase 3: Validate session binding (IP and/or User-Agent)
        if not self._validate_session_binding(session, client_ip, user_agent):
            logger.warning(
                f"Session {session_id} binding validation failed",
                extra={
                    "session_id": session_id,
                    "user_email": session.user_email,
                    "stored_ip": session.ip_address,
                    "request_ip": client_ip,
                    "stored_ua": session.user_agent,
                    "request_ua": user_agent,
                },
            )

            # Enterprise audit logging: Binding violation
            self._audit_service.log_action(
                action="ACCESS",
                resource_type="http_auth_session",
                resource_id=session_id,
                user_id=session.user_email,
                user_email=session.user_email,
                client_ip=client_ip,
                user_agent=user_agent,
                data_classification="confidential",
                success=False,
                error_message="Session binding validation failed",
                context={
                    "event_type": "binding_violation",
                    "session_id": session_id,
                    "violation_type": "ip_or_user_agent_mismatch",
                    "stored_ip": session.ip_address,
                    "request_ip": client_ip,
                    "stored_user_agent": sanitize_user_agent_for_logging(session.user_agent),
                    "request_user_agent": sanitize_user_agent_for_logging(user_agent),
                },
                details={
                    "ip_binding_enabled": settings.session_bind_to_ip,
                    "ua_binding_enabled": settings.session_bind_to_user_agent,
                },
                db=self.db,
            )

            await self.terminate_session(session_id, reason="binding_violation")
            return None

        return session

    async def validate_session(self, session_id: str, client_ip: Optional[str] = None, user_agent: Optional[str] = None) -> bool:
        """Validate a session and update its activity timestamp.

        This is the primary method for session validation during authentication.
        It performs comprehensive validation including:
        - Session existence check
        - Idle timeout validation
        - Absolute timeout validation
        - Client binding validation (IP and/or User-Agent)
        - Activity timestamp update (if valid)

        Args:
            session_id: Session identifier (JWT jti claim)
            client_ip: Client IP address for binding validation (optional)
            user_agent: User-Agent string for binding validation (optional)

        Returns:
            True if session is valid and active, False otherwise

        Note:
            This method automatically terminates expired or invalid sessions.
            Activity timestamp is updated only if validation succeeds.
        """
        logger.debug(f"[VALIDATE_SESSION] Starting validation for session {session_id}")

        # Use get_session which performs all validation checks
        session = await self.get_session(session_id=session_id, client_ip=client_ip, user_agent=user_agent)

        if session is None:
            logger.debug(f"[VALIDATE_SESSION] Session {session_id} validation failed - session not found or invalid")
            return False

        # Session is valid - update activity timestamp
        logger.debug(f"[VALIDATE_SESSION] Session {session_id} is valid, updating activity timestamp")
        await self.touch_session(session_id)

        logger.debug(f"[VALIDATE_SESSION] Session {session_id} validation successful")
        return True

    async def touch_session(self, session_id: str) -> bool:
        """Update the last_activity timestamp for a session.

        Hybrid approach with throttling: Both Redis and DB updates are throttled to reduce
        unnecessary writes. This method is called on every authenticated request to track
        session activity and reset the idle timeout. To reduce write load, timestamps are
        only updated if the minimum update interval has passed since the last update.

        Args:
            session_id: Session identifier

        Returns:
            True if session was updated, False if not found
        """
        # Get session from DB to check throttling
        session = self.db.query(HttpAuthSession).filter(HttpAuthSession.session_id == session_id).first()

        if not session:
            return False

        # Check if we should update based on throttling interval
        now = utc_now()
        update_interval = timedelta(seconds=settings.session_activity_update_interval_seconds)

        # Ensure last_activity is timezone-aware for comparison
        last_activity = session.last_activity
        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=timezone.utc)

        time_since_last_update = now - last_activity

        # Skip update if within throttling interval (applies to both Redis and DB)
        if time_since_last_update < update_interval:
            logger.debug(
                f"Skipping last_activity update for session {session_id} "
                f"(last updated {time_since_last_update.total_seconds():.1f}s ago, "
                f"minimum interval: {update_interval.total_seconds()}s)",
                extra={"session_id": session_id, "user_email": session.user_email},
            )
            return True  # Session exists and is valid, just not updating

        # Update both Redis and DB (throttling passed)
        try:
            await self._update_session_activity_in_redis(session_id)
        except Exception as e:
            logger.debug(f"Failed to update session {session_id} activity in Redis: {e}")

        session.last_activity = now
        self.db.commit()

        logger.debug(
            f"Updated last_activity for session {session_id} in both Redis and DB " f"(was {time_since_last_update.total_seconds():.1f}s old)",
            extra={"session_id": session_id, "user_email": session.user_email},
        )

        return True

    async def list_user_sessions(self, user_email: str) -> List[HttpAuthSession]:
        """List all active sessions for a user.

        Args:
            user_email: User's email address

        Returns:
            List of active HttpAuthSession instances
        """
        sessions = self.db.query(HttpAuthSession).filter(HttpAuthSession.user_email == user_email).order_by(desc(HttpAuthSession.last_activity)).all()

        # Filter out expired sessions
        active_sessions = []
        for session in sessions:
            is_expired, reason = self._is_session_expired(session)
            if is_expired:
                await self.terminate_session(session.session_id, reason=reason)
            else:
                active_sessions.append(session)

        return active_sessions

    async def terminate_session(self, session_id: str, reason: str = "user_revoke") -> bool:
        """Terminate a session.

        Hybrid approach: Delete from both Redis and DB.

        Args:
            session_id: Session identifier
            reason: Termination reason

        Returns:
            True if session was terminated, False if not found
        """
        session = self.db.query(HttpAuthSession).filter(HttpAuthSession.session_id == session_id).first()

        if not session:
            return False

        user_email = session.user_email

        # Delete from database
        self.db.delete(session)
        self.db.commit()

        # Delete from Redis
        try:
            await self._delete_session_from_redis(session_id, user_email)
        except Exception as e:
            logger.warning(f"Failed to delete session {session_id} from Redis: {e}")

        logger.debug(
            f"Terminated session {session_id}: {reason}",
            extra={"session_id": session_id, "reason": reason, "user_email": user_email},
        )

        # Enterprise audit logging: Session termination
        self._audit_service.log_action(
            action="DELETE",
            resource_type="http_auth_session",
            resource_id=session_id,
            user_id=user_email,
            user_email=user_email,
            data_classification="confidential",
            success=True,
            context={
                "event_type": "session_terminated",
                "session_id": session_id,
                "termination_reason": reason,
            },
            details={
                "reason_category": self._categorize_termination_reason(reason),
            },
            db=self.db,
        )

        return True

    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions from both Redis and database.

        Optimized approach: Uses database-level filtering to identify expired sessions
        without loading all sessions into memory. Calculates cutoff times and queries
        only sessions that have exceeded idle or absolute timeouts.

        Handles both timezone-aware (PostgreSQL) and naive (SQLite) datetimes by
        ensuring cutoff times match the database's datetime format.

        Hybrid approach: Clean from both Redis and DB.
        This method is called by the background cleanup task to remove sessions
        that have exceeded their absolute or idle timeout.

        Returns:
            Number of sessions deleted
        """
        # Calculate cutoff times for expired sessions
        now = utc_now()
        expired_session_ids = []

        # Build query conditions for expired sessions
        conditions = []

        # Check idle timeout
        if settings.session_idle_timeout_minutes > 0:
            idle_cutoff = now - timedelta(minutes=settings.session_idle_timeout_minutes)
            # For SQLite compatibility: remove timezone info if database stores naive datetimes
            # The comparison will work correctly as long as both sides use the same timezone convention
            conditions.append(HttpAuthSession.last_activity < idle_cutoff)
            logger.debug(f"Idle timeout check: sessions with last_activity < {idle_cutoff} " f"({settings.session_idle_timeout_minutes} min ago)")

        # Check absolute timeout
        if settings.session_absolute_timeout_minutes > 0:
            absolute_cutoff = now - timedelta(minutes=settings.session_absolute_timeout_minutes)
            conditions.append(HttpAuthSession.created_at < absolute_cutoff)
            logger.debug(f"Absolute timeout check: sessions with created_at < {absolute_cutoff} " f"({settings.session_absolute_timeout_minutes} min ago)")

        # If no timeout settings enabled, nothing to clean up
        if not conditions:
            logger.debug("No timeout settings enabled, skipping session cleanup")
            return 0

        # Query only expired sessions using database-level filtering
        # Note: SQLAlchemy handles timezone comparison correctly for both
        # timezone-aware (PostgreSQL) and naive (SQLite) datetimes
        expired_sessions = self.db.query(HttpAuthSession).filter(or_(*conditions)).all()

        logger.debug(f"Found {len(expired_sessions)} potentially expired sessions via database query")

        deleted_count = 0
        for session in expired_sessions:
            # Double-check expiration using _is_session_expired which handles timezone edge cases
            # This ensures correct behavior regardless of database timezone handling
            is_expired, reason = self._is_session_expired(session)
            if is_expired:
                # Delete from database
                self.db.delete(session)
                expired_session_ids.append(session.session_id)
                deleted_count += 1
                logger.debug(f"Marked session {session.session_id} for deletion: {reason}")

        # Commit all deletions at once (more efficient than individual commits)
        if deleted_count > 0:
            self.db.commit()

            # Clean up from Redis in batch
            for session_id in expired_session_ids:
                try:
                    await self._delete_session_from_redis(session_id, None)
                except Exception as e:
                    logger.debug(f"Failed to delete session {session_id} from Redis during cleanup: {e}")

            logger.info(f"Cleaned up {deleted_count} expired HTTP auth sessions from DB and Redis")

            # Enterprise audit logging: Timeout events (batch log for efficiency)
            # Log a summary event for the cleanup operation
            self._audit_service.log_action(
                action="DELETE",
                resource_type="http_auth_session",
                resource_id="batch_cleanup",
                user_id="system",
                user_email="system",
                data_classification="confidential",
                success=True,
                context={
                    "event_type": "session_timeout_cleanup",
                    "cleanup_type": "scheduled",
                    "sessions_cleaned": deleted_count,
                },
                details={
                    "idle_timeout_minutes": settings.session_idle_timeout_minutes,
                    "absolute_timeout_minutes": settings.session_absolute_timeout_minutes,
                    "cleanup_timestamp": now.isoformat(),
                    "expired_session_ids": expired_session_ids[:100],  # Limit to first 100 for log size
                },
                db=self.db,
            )

            # Log individual timeout events for high-value sessions (optional, can be enabled via config)
            if settings.audit_trail_enabled and deleted_count <= 10:  # Only log individual events for small batches
                for session in expired_sessions:
                    if session.session_id in expired_session_ids:  # Only log actually deleted sessions
                        is_expired, reason = self._is_session_expired(session)
                        timeout_type = "idle_timeout" if "idle" in reason.lower() else "absolute_timeout"

                        # Ensure timestamps are timezone-aware for datetime arithmetic
                        # SQLite may return naive datetimes
                        created_at = session.created_at
                        if created_at.tzinfo is None:
                            created_at = created_at.replace(tzinfo=timezone.utc)

                        last_activity = session.last_activity
                        if last_activity.tzinfo is None:
                            last_activity = last_activity.replace(tzinfo=timezone.utc)

                        self._audit_service.log_action(
                            action="DELETE",
                            resource_type="http_auth_session",
                            resource_id=session.session_id,
                            user_id=session.user_email,
                            user_email=session.user_email,
                            data_classification="confidential",
                            success=True,
                            context={
                                "event_type": "session_timeout",
                                "session_id": session.session_id,
                                "timeout_type": timeout_type,
                                "timeout_reason": reason,
                            },
                            details={
                                "created_at": created_at.isoformat(),
                                "last_activity": last_activity.isoformat(),
                                "session_age_minutes": int((now - created_at).total_seconds() / 60),
                                "idle_duration_minutes": int((now - last_activity).total_seconds() / 60),
                            },
                            db=self.db,
                        )
        else:
            logger.debug("No expired sessions found after validation")

        return deleted_count

    async def enforce_limits(self, user_email: str) -> None:
        """Enforce max_sessions_per_user limit using LRU eviction.

        When a new session is about to be created and the user already has
        max_sessions_per_user active sessions, this method removes the oldest
        session(s) to make room for the new one.

        Args:
            user_email: User's email address
        """
        max_sessions = settings.max_sessions_per_user
        logger.debug(f"[SESSION_LIMIT] enforce_limits called for {user_email}. Max sessions: {max_sessions}", extra={"user_email": user_email, "max_sessions": max_sessions})

        if max_sessions <= 0:
            logger.debug(f"[SESSION_LIMIT] Session limits disabled (max_sessions={max_sessions}), skipping enforcement")
            return

        # Get current active sessions
        current_sessions = await self.list_user_sessions(user_email)
        current_count = len(current_sessions)

        logger.debug(
            f"[SESSION_LIMIT] User {user_email} has {current_count} active sessions (max: {max_sessions})",
            extra={"user_email": user_email, "current_count": current_count, "max_sessions": max_sessions, "session_ids": [s.session_id for s in current_sessions]},
        )

        # Only enforce if at or over limit
        # We need to remove enough sessions to make room for 1 new session
        if current_count >= max_sessions:
            # Calculate how many sessions to remove
            # If we have 5 sessions and max is 5, remove 1 to make room for the new one
            num_to_remove = current_count - max_sessions + 1

            logger.warning(
                f"[SESSION_LIMIT] User {user_email} at/over limit ({current_count}/{max_sessions}). Will remove {num_to_remove} oldest session(s)",
                extra={
                    "user_email": user_email,
                    "current_count": current_count,
                    "max_sessions": max_sessions,
                    "num_to_remove": num_to_remove,
                },
            )

            # Sort by last_activity (oldest first) and take the oldest N sessions
            sessions_to_remove = sorted(current_sessions, key=lambda s: s.last_activity)[:num_to_remove]

            for session in sessions_to_remove:
                logger.warning(
                    f"[SESSION_LIMIT] Evicting session {session.session_id} (last_activity: {session.last_activity})",
                    extra={
                        "session_id": session.session_id,
                        "user_email": user_email,
                        "last_activity": session.last_activity.isoformat(),
                    },
                )
                await self.terminate_session(session.session_id, reason="max_sessions_exceeded")
                logger.debug(
                    f"[SESSION_LIMIT] Successfully evicted session {session.session_id} for user {user_email}",
                    extra={
                        "session_id": session.session_id,
                        "user_email": user_email,
                        "max_sessions": max_sessions,
                        "current_sessions": current_count,
                        "num_removed": num_to_remove,
                    },
                )
        else:
            logger.debug(
                f"[SESSION_LIMIT] User {user_email} under limit ({current_count}/{max_sessions}). No eviction needed.",
                extra={
                    "user_email": user_email,
                    "current_count": current_count,
                    "max_sessions": max_sessions,
                },
            )

    def _validate_session_binding(self, session: HttpAuthSession, client_ip: Optional[str], user_agent: Optional[str]) -> bool:
        """Validate session binding to IP address and/or User-Agent.

        Phase 3: Session Binding - Anti-hijacking protection by validating that
        the request comes from the same client that created the session.

        Args:
            session: The session to validate
            client_ip: Current request's client IP address
            user_agent: Current request's User-Agent string

        Returns:
            True if binding validation passes or is disabled, False if validation fails
        """
        # IP address binding validation
        if settings.session_bind_to_ip:
            logger.debug(f"Validating session binding: IP check enabled (session={session.session_id})")
            if not client_ip:
                logger.warning(
                    f"Session binding validation failed: no client IP provided for session {session.session_id}",
                    extra={"session_id": session.session_id, "user_email": session.user_email},
                )
                return False

            if session.ip_address and session.ip_address != client_ip:
                logger.warning(
                    f"Session binding validation failed: IP mismatch for session {session.session_id}",
                    extra={
                        "session_id": session.session_id,
                        "user_email": session.user_email,
                        "stored_ip": session.ip_address,
                        "request_ip": client_ip,
                    },
                )
                return False

        # User-Agent binding validation
        if settings.session_bind_to_user_agent:
            if not user_agent:
                logger.warning(
                    f"Session binding validation failed: no User-Agent provided for session {session.session_id}",
                    extra={"session_id": session.session_id, "user_email": session.user_email},
                )
                return False

            if session.user_agent and session.user_agent != user_agent:
                logger.warning(
                    f"Session binding validation failed: User-Agent mismatch for session {session.session_id}",
                    extra={
                        "session_id": session.session_id,
                        "user_email": session.user_email,
                        "stored_ua": sanitize_user_agent_for_logging(session.user_agent),
                        "request_ua": sanitize_user_agent_for_logging(user_agent),
                    },
                )
                return False
        # Validation passed or binding is disabled
        logger.debug(f"Session binding validation passed for session {session.session_id}")
        return True

    def _categorize_termination_reason(self, reason: str) -> str:
        """Categorize termination reason for audit logging.

        Args:
            reason: Raw termination reason string

        Returns:
            Categorized reason (system, user, security, admin)
        """
        # System-initiated terminations
        if reason in ("expired", "absolute_timeout", "idle_timeout", "max_sessions_exceeded"):
            return "system"

        # Security-related terminations
        if reason in ("binding_violation", "security_audit", "suspicious_activity"):
            return "security"

        # User-initiated terminations
        if reason in ("user_revoke", "user_logout"):
            return "user"

        # Admin-initiated terminations (catch-all for custom reasons)
        return "admin"

    def _is_session_expired(self, session: HttpAuthSession) -> Tuple[bool, Optional[str]]:
        """Check if a session is expired.

        Args:
            session: Session to check

        Returns:
            Tuple of (is_expired, reason)
        """
        now = utc_now()

        # Ensure session timestamps are timezone-aware (SQLite may return naive datetimes)
        created_at = session.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        last_activity = session.last_activity
        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=timezone.utc)

        logger.debug(f"Checking session expiry for {session.session_id}: " f"created_at={created_at}, last_activity={last_activity}, now={now}")

        # Check absolute timeout
        if settings.session_absolute_timeout_minutes > 0:
            absolute_limit = created_at + timedelta(minutes=settings.session_absolute_timeout_minutes)
            time_since_creation = (now - created_at).total_seconds() / 60
            logger.debug(
                f"Absolute timeout check: limit={settings.session_absolute_timeout_minutes} min, " f"time_since_creation={time_since_creation:.2f} min, " f"absolute_limit={absolute_limit}, now={now}"
            )
            if now > absolute_limit:
                logger.debug(f"Session {session.session_id} expired due to absolute timeout: " f"{time_since_creation:.2f} min > {settings.session_absolute_timeout_minutes} min")
                return (True, "absolute_timeout")

        # Check idle timeout
        if settings.session_idle_timeout_minutes > 0:
            idle_limit = last_activity + timedelta(minutes=settings.session_idle_timeout_minutes)
            time_since_activity = (now - last_activity).total_seconds() / 60
            logger.debug(f"Idle timeout check: limit={settings.session_idle_timeout_minutes} min, " f"time_since_activity={time_since_activity:.2f} min, " f"idle_limit={idle_limit}, now={now}")
            if now > idle_limit:
                logger.debug(f"Session {session.session_id} expired due to idle timeout: " f"{time_since_activity:.2f} min > {settings.session_idle_timeout_minutes} min")
                return (True, "idle_timeout")

        logger.debug(f"Session {session.session_id} is still valid")
        return (False, None)
