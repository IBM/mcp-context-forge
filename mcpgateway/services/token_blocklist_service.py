# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/token_blocklist_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan Catanus

Token Blocklist Service for JWT Token Revocation.

This service implements server-side token blocklist functionality to provide
immediate token invalidation capabilities, addressing security requirements
for logout, idle timeout, and token refresh scenarios.

Key Features:
- Server-side token revocation with blocklist
- Idle timeout tracking and enforcement
- Automatic cleanup of expired tokens
- Redis caching for performance
- Comprehensive audit logging

Security Compliance:
- Implements X-Force Red recommendations for token management
- Supports 5-20 minute token lifetimes
- Tracks token activity for idle timeout enforcement
- Maintains revocation audit trail
"""

# Standard
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

# Third-Party
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import fresh_db_session, TokenRevocation, utc_now
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class TokenBlocklistService:
    """Service for managing JWT token revocation blocklist.

    This service provides comprehensive token lifecycle management including
    revocation, idle timeout tracking, and automatic cleanup of expired entries.
    """

    def __init__(self, db: Optional[Session] = None):
        """Initialize the token blocklist service.

        Args:
            db: Optional database session. If not provided, creates new sessions as needed.
        """
        self.db = db
        self._redis_client = None

    def _get_redis_client(self):
        """Get Redis client for caching (lazy initialization).

        Returns:
            Redis client if available, None otherwise.
        """
        if self._redis_client is None:
            try:
                # Third-Party
                import redis  # pylint: disable=import-outside-toplevel

                if settings.redis_url:
                    self._redis_client = redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
                    # Test connection
                    self._redis_client.ping()
                    logger.debug("Redis connection established for token blocklist")
            except Exception as e:
                logger.warning(f"Redis not available for token blocklist caching: {e}")
                self._redis_client = False  # Mark as unavailable

        return self._redis_client if self._redis_client is not False else None

    def revoke_token(self, jti: str, revoked_by: str, reason: str = "logout", token_expiry: Optional[datetime] = None, last_activity: Optional[datetime] = None) -> bool:
        """Revoke a token by adding it to the blocklist.

        Args:
            jti: JWT ID to revoke
            revoked_by: Email of user revoking the token
            reason: Reason for revocation (logout, idle_timeout, security, token_refresh, etc.)
            token_expiry: Original token expiry for cleanup scheduling
            last_activity: Last activity timestamp for audit trail

        Returns:
            True if token was revoked successfully, False otherwise.

        Examples:
            >>> service = TokenBlocklistService()
            >>> # Requires database connection - see unit tests for examples
            >>> # service.revoke_token(jti="abc-123", revoked_by="user@example.com", reason="logout")
        """
        try:
            if self.db is not None:
                # Use provided session
                db = self.db
                # Check if already revoked
                existing = db.execute(select(TokenRevocation).where(TokenRevocation.jti == jti)).scalar_one_or_none()

                if existing:
                    logger.debug(f"Token {jti} already revoked")
                    return True

                # Create revocation record
                revocation = TokenRevocation(jti=jti, revoked_by=revoked_by, reason=reason, token_expiry=token_expiry, last_activity=last_activity or utc_now())

                db.add(revocation)
                db.commit()
            else:
                # Create own session
                with fresh_db_session() as db:
                    # Check if already revoked
                    existing = db.execute(select(TokenRevocation).where(TokenRevocation.jti == jti)).scalar_one_or_none()

                    if existing:
                        logger.debug(f"Token {jti} already revoked")
                        return True

                    # Create revocation record
                    revocation = TokenRevocation(jti=jti, revoked_by=revoked_by, reason=reason, token_expiry=token_expiry, last_activity=last_activity or utc_now())

                    db.add(revocation)
                    db.commit()

            # Cache in Redis for fast lookup
            redis_client = self._get_redis_client()
            if redis_client:
                try:
                    # Cache with TTL matching token expiry
                    ttl_seconds = 86400  # Default 24 hours
                    if token_expiry:
                        ttl_seconds = int((token_expiry - utc_now()).total_seconds())
                        ttl_seconds = max(ttl_seconds, 60)  # Minimum 1 minute

                    redis_client.setex(f"token:revoked:{jti}", ttl_seconds, "1")
                except Exception as e:
                    logger.warning(f"Failed to cache revocation in Redis: {e}")

            logger.info(
                f"Token revoked: jti={jti}, reason={reason}, revoked_by={revoked_by}",
                extra={"security_event": "token_revocation", "security_severity": "medium", "jti": jti, "reason": reason, "revoked_by": revoked_by},
            )

            return True

        except Exception as e:
            logger.error(f"Failed to revoke token {jti}: {e}")
            return False

    def is_token_revoked(self, jti: str) -> bool:
        """Check if a token is revoked.

        Args:
            jti: JWT ID to check

        Returns:
            True if token is revoked, False otherwise.

        Examples:
            >>> service = TokenBlocklistService()
            >>> # Returns True (fail-closed) when database unavailable
            >>> # See unit tests for proper usage examples
        """
        try:
            # Check Redis cache first
            redis_client = self._get_redis_client()
            if redis_client:
                try:
                    if redis_client.exists(f"token:revoked:{jti}"):
                        return True
                except Exception as e:
                    logger.debug(f"Redis cache check failed: {e}")

            # Fall back to database
            if self.db is not None:
                result = self.db.execute(select(TokenRevocation).where(TokenRevocation.jti == jti)).scalar_one_or_none()
                return result is not None

            with fresh_db_session() as db:
                result = db.execute(select(TokenRevocation).where(TokenRevocation.jti == jti)).scalar_one_or_none()
                return result is not None

        except Exception as e:
            logger.error(f"Failed to check token revocation status: {e}")
            # Fail closed - treat as revoked on error
            return True

    def check_idle_timeout(self, jti: str, last_activity: datetime, current_time: Optional[datetime] = None) -> bool:
        """Check if a token has exceeded idle timeout.

        Args:
            jti: JWT ID to check
            last_activity: Last activity timestamp
            current_time: Current time (defaults to now)

        Returns:
            True if token has exceeded idle timeout, False otherwise.
        """
        current_time = current_time or utc_now()
        idle_timeout_minutes = settings.token_idle_timeout

        # Ensure last_activity is timezone-aware
        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=timezone.utc)

        idle_duration = current_time - last_activity
        max_idle = timedelta(minutes=idle_timeout_minutes)

        if idle_duration > max_idle:
            logger.info(
                f"Token {jti} exceeded idle timeout: {idle_duration.total_seconds()/60:.1f} minutes",
                extra={"security_event": "idle_timeout", "security_severity": "low", "jti": jti, "idle_minutes": idle_duration.total_seconds() / 60},
            )
            return True

        return False

    def update_activity(self, jti: str) -> bool:
        """Update last activity timestamp for a token.

        Args:
            jti: JWT ID to update

        Returns:
            True if updated successfully, False otherwise.
        """
        try:
            # Update Redis cache
            redis_client = self._get_redis_client()
            if redis_client:
                try:
                    redis_client.setex(f"token:activity:{jti}", settings.token_idle_timeout * 60, utc_now().isoformat())  # TTL in seconds
                except Exception as e:
                    logger.debug(f"Failed to update activity in Redis: {e}")

            return True

        except Exception as e:
            logger.error(f"Failed to update token activity: {e}")
            return False

    def get_last_activity(self, jti: str) -> Optional[datetime]:
        """Get last activity timestamp for a token.

        Args:
            jti: JWT ID to check

        Returns:
            Last activity timestamp if available, None otherwise.
        """
        try:
            # Check Redis cache first
            redis_client = self._get_redis_client()
            if redis_client:
                try:
                    activity_str = redis_client.get(f"token:activity:{jti}")
                    if activity_str:
                        return datetime.fromisoformat(activity_str)
                except Exception as e:
                    logger.debug(f"Failed to get activity from Redis: {e}")

            return None

        except Exception as e:
            logger.error(f"Failed to get token activity: {e}")
            return None

    def cleanup_expired_tokens(self, hours_retention: Optional[int] = None) -> int:
        """Clean up expired tokens from the blocklist.

        Removes tokens that have been expired for longer than the retention period.

        Args:
            hours_retention: Hours to retain expired tokens (defaults to config setting)

        Returns:
            Number of tokens cleaned up.
        """
        hours_retention = hours_retention or settings.token_blocklist_cleanup_hours
        cutoff_time = utc_now() - timedelta(hours=hours_retention)

        try:
            if self.db is not None:
                # Use provided session
                result = self.db.execute(delete(TokenRevocation).where(TokenRevocation.token_expiry < cutoff_time))
                deleted_count = result.rowcount
                self.db.commit()

                if deleted_count > 0:
                    logger.info(
                        f"Cleaned up {deleted_count} expired tokens from blocklist",
                        extra={"security_event": "blocklist_cleanup", "deleted_count": deleted_count, "cutoff_time": cutoff_time.isoformat()},
                    )

                return deleted_count

            # Create own session
            with fresh_db_session() as db:
                result = db.execute(delete(TokenRevocation).where(TokenRevocation.token_expiry < cutoff_time))
                deleted_count = result.rowcount
                db.commit()

                if deleted_count > 0:
                    logger.info(
                        f"Cleaned up {deleted_count} expired tokens from blocklist",
                        extra={"security_event": "blocklist_cleanup", "deleted_count": deleted_count, "cutoff_time": cutoff_time.isoformat()},
                    )

                return deleted_count

        except Exception as e:
            logger.error(f"Failed to cleanup expired tokens: {e}")
            return 0

    def revoke_user_tokens(self, user_email: str, revoked_by: str, reason: str = "security") -> int:
        """Revoke all active tokens for a user.

        This is useful for security incidents or when a user's credentials are compromised.

        Args:
            user_email: Email of user whose tokens should be revoked
            revoked_by: Email of user performing the revocation
            reason: Reason for revocation

        Returns:
            Number of tokens revoked.
        """
        # Note: This requires tracking active tokens per user, which would need
        # additional implementation. For now, this is a placeholder for future enhancement.
        logger.warning(
            f"Bulk token revocation requested for user {user_email} but not yet implemented",
            extra={"security_event": "bulk_revocation_requested", "target_user": user_email, "revoked_by": revoked_by, "reason": reason},
        )
        return 0

    def get_revocation_stats(self) -> Dict[str, int]:
        """Get statistics about token revocations.

        Returns:
            Dictionary with revocation statistics.
        """
        try:
            # Import func at the top of the method
            # Third-Party
            from sqlalchemy import func  # pylint: disable=import-outside-toplevel,redefined-outer-name

            if self.db is not None:
                # Use provided session
                # Count total revocations
                total = self.db.execute(select(func.count()).select_from(TokenRevocation)).scalar()  # pylint: disable=not-callable

                # Count by reason
                reason_counts = self.db.execute(select(TokenRevocation.reason, func.count(TokenRevocation.jti)).group_by(TokenRevocation.reason)).all()  # pylint: disable=not-callable

                stats = {"total_revoked": total or 0, "by_reason": dict(reason_counts)}

                return stats

            # Create own session
            with fresh_db_session() as db:
                # Count total revocations
                total = db.execute(select(func.count()).select_from(TokenRevocation)).scalar()  # pylint: disable=not-callable

                # Count by reason
                reason_counts = db.execute(select(TokenRevocation.reason, func.count(TokenRevocation.jti)).group_by(TokenRevocation.reason)).all()  # pylint: disable=not-callable

                stats = {"total_revoked": total or 0, "by_reason": dict(reason_counts)}

                return stats

        except Exception as e:
            logger.error(f"Failed to get revocation stats: {e}")
            return {"total_revoked": 0, "by_reason": {}}


# Singleton instance for convenience
_blocklist_service: Optional[TokenBlocklistService] = None


def get_token_blocklist_service(db: Optional[Session] = None) -> TokenBlocklistService:
    """Get or create the token blocklist service instance.

    Args:
        db: Optional database session

    Returns:
        TokenBlocklistService instance.
    """
    global _blocklist_service

    if db is not None:
        # Always create new instance when db is provided
        return TokenBlocklistService(db=db)

    if _blocklist_service is None:
        _blocklist_service = TokenBlocklistService()

    return _blocklist_service
