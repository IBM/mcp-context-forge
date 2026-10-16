# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/token_backends/db_backend.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Database token storage backend.

Phase 1: Minimal extraction (copy-paste from existing token_storage_service.py).
Accepts team_id parameter but COMPLETELY IGNORES it - no database schema changes.
This is purely code reorganization to enable the façade pattern.

Phase 2 (future): Add team_id column to oauth_tokens table and use it in queries.
"""

import asyncio
import hashlib
import logging
import os
import tempfile
import time
import weakref
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, cast, ClassVar, Optional

from filelock import FileLock, Timeout
from sqlalchemy import and_, delete, or_, select, Text, type_coerce, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import Settings
from mcpgateway.db import Gateway, OAuthToken
from mcpgateway.services.encryption_service import get_encryption_service
from mcpgateway.services.oauth_manager import OAuthError, OAuthInvalidGrantError, OAuthManager, parse_expires_in

from .base import AbstractTokenBackend, TokenRecord
from .refresh_helpers import apply_omit_resource_and_normalize, check_private_gateway_access, compute_prior_ttl

logger = logging.getLogger(__name__)

# Worker processes on one host serialize a token refresh through one of these lock
# files. The wait is longer than OAuthManager's default refresh: 3 attempts with a
# 30 s timeout each, plus backoff. After the wait the refresh goes ahead unlocked.
_REFRESH_LOCK_STRIPES = 64
_REFRESH_LOCK_WAIT_SECONDS = 120.0
_REFRESH_LOCK_POLL_SECONDS = 0.05


def _refresh_lock_path(gateway_id: str, app_user_email: str) -> str:
    """Return the lock file that serializes refreshes of one token on this host.

    Args:
        gateway_id: Gateway ID
        app_user_email: ContextForge user email

    Returns:
        Path of one of a fixed set of lock files in the system temp directory
    """
    digest = hashlib.sha256(f"{gateway_id}\0{app_user_email}".encode()).digest()
    stripe = int.from_bytes(digest[:4], "big") % _REFRESH_LOCK_STRIPES
    return os.path.join(tempfile.gettempdir(), f"mcpgateway_oauth_refresh_{stripe:02d}.lock")


@asynccontextmanager
async def _refresh_file_lock(gateway_id: str, app_user_email: str) -> AsyncIterator[None]:
    """Hold the host-wide refresh lock for one token without blocking the event loop.

    The lock is polled with non-blocking attempts. If it stays busy for
    _REFRESH_LOCK_WAIT_SECONDS, or the lock file is not usable, the caller
    continues without it, as before this lock existed.

    Args:
        gateway_id: Gateway ID
        app_user_email: ContextForge user email

    Yields:
        None, while the lock is held or after the wait gave up
    """
    lock = FileLock(_refresh_lock_path(gateway_id, app_user_email))
    deadline = time.monotonic() + _REFRESH_LOCK_WAIT_SECONDS
    acquired = False
    while not acquired:
        try:
            lock.acquire(blocking=False)
            acquired = True
        except Timeout:
            if time.monotonic() >= deadline:
                logger.warning("Token refresh lock for gateway %s is still busy; refreshing without it", SecurityValidator.sanitize_log_message(gateway_id))
                break
            await asyncio.sleep(_REFRESH_LOCK_POLL_SECONDS)
        except OSError as e:
            logger.warning("Token refresh lock file is not usable (%s); refreshing without it", e)
            break
    try:
        yield
    finally:
        if acquired:
            lock.release()


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Return a timestamp as timezone-aware UTC, so database and in-memory values compare equal.

    Args:
        value: Timestamp that may lack a timezone (SQLite returns naive values)

    Returns:
        The timestamp in UTC, or None
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


# Note: _preserve_prior_ttl() has been replaced by compute_prior_ttl() from refresh_helpers.py
# to avoid code duplication between DatabaseTokenBackend and VaultTokenBackend.


class DatabaseTokenBackend(AbstractTokenBackend):
    """
    Database token storage backend (Phase 1 - minimal extraction).

    IMPORTANT: Accepts team_id parameter but COMPLETELY IGNORES it.
    NO database schema changes. SQL queries use (gateway_id, app_user_email) as before.
    This is purely code reorganization to enable the façade pattern.

    Phase 2 will add team_id column and update queries.
    """

    # Per-(gateway_id, app_user_email) locks that let one request at a time in this
    # process refresh a token. Providers that rotate refresh tokens reject or
    # supersede a second use of the same refresh token. Weak values drop a lock as
    # soon as no request holds or waits on it, so the map needs no size limit.
    _refresh_locks: ClassVar["weakref.WeakValueDictionary[tuple[str, str], asyncio.Lock]"] = weakref.WeakValueDictionary()

    def __init__(self, db: Session, settings: Settings):
        """Initialize database backend.

        Args:
            db: SQLAlchemy database session
            settings: Application settings
        """
        self.db = db
        self.settings = settings
        try:
            self.encryption = get_encryption_service(settings.auth_encryption_secret)
        except (ImportError, AttributeError):
            logger.warning("OAuth encryption not available, using plain text storage")
            self.encryption = None

    async def store_tokens(
        self,
        gateway_id: str,
        team_id: str,  # ← Phase 1: Accepted but NOT used (no DB column yet)
        user_id: str,
        app_user_email: str,
        access_token: str,
        refresh_token: str | None,
        expires_in: int | None,
        scopes: list[str],
        learned_aud: str | None = None,
        learned_iss: str | None = None,
    ) -> TokenRecord:
        """Store OAuth tokens in database.

        Phase 1: team_id parameter is IGNORED. No database schema changes.
        Query uses (gateway_id, app_user_email) as unique key.

        Args:
            gateway_id: Gateway ID (FK to gateways.id)
            team_id: Team identifier (IGNORED in Phase 1)
            user_id: OAuth provider user ID
            app_user_email: ContextForge user email
            access_token: Access token (will be encrypted)
            refresh_token: Refresh token (will be encrypted)
            expires_in: Token expiration in seconds, or None
            scopes: OAuth scopes
            learned_aud: Learned JWT audience from token introspection (stored in DB)
            learned_iss: Learned JWT issuer from token introspection (stored in DB)

        Returns:
            TokenRecord with plain-text tokens

        Raises:
            OAuthError: If storage fails
        """
        try:
            # Encrypt sensitive tokens if encryption is available
            encrypted_access = access_token
            encrypted_refresh = refresh_token

            if self.encryption:
                encrypted_access = await self.encryption.encrypt_secret_async(access_token)
                if refresh_token:
                    encrypted_refresh = await self.encryption.encrypt_secret_async(refresh_token)

            # Calculate expiration (None if provider does not specify expires_in)
            if expires_in is not None:
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            else:
                logger.info(
                    "No expires_in from OAuth provider for gateway %s; token will not auto-expire",
                    SecurityValidator.sanitize_log_message(gateway_id),
                )
                expires_at = None

            # PHASE 1: Query by (gateway_id, app_user_email) - team_id IGNORED
            token_record = self.db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.app_user_email == app_user_email)).scalar_one_or_none()

            now = datetime.now(timezone.utc)

            if token_record:
                # Update existing record
                token_record.user_id = user_id
                token_record.access_token = encrypted_access
                token_record.refresh_token = encrypted_refresh
                token_record.expires_at = expires_at
                token_record.scopes = scopes
                # Only overwrite when caller supplies a value — never erase a
                # previously-learned audience/issuer with None on re-auth.
                if learned_aud is not None:
                    token_record.learned_aud = learned_aud
                if learned_iss is not None:
                    token_record.learned_iss = learned_iss
                token_record.updated_at = now
                logger.info(
                    "Updated OAuth tokens for gateway %s, app user %s, OAuth user %s",
                    SecurityValidator.sanitize_log_message(gateway_id),
                    SecurityValidator.sanitize_log_message(app_user_email),
                    SecurityValidator.sanitize_log_message(user_id),
                )
            else:
                # Create new record
                token_record = OAuthToken(
                    gateway_id=gateway_id,
                    user_id=user_id,
                    app_user_email=app_user_email,
                    access_token=encrypted_access,
                    refresh_token=encrypted_refresh,
                    expires_at=expires_at,
                    scopes=scopes,
                    learned_aud=learned_aud,
                    learned_iss=learned_iss,
                )
                self.db.add(token_record)
                logger.info(
                    "Stored new OAuth tokens for gateway %s, app user %s, OAuth user %s",
                    SecurityValidator.sanitize_log_message(gateway_id),
                    SecurityValidator.sanitize_log_message(app_user_email),
                    SecurityValidator.sanitize_log_message(user_id),
                )

            self.db.commit()

            # Return TokenRecord with plain-text tokens
            return TokenRecord(
                gateway_id=gateway_id,
                mcp_url=self._resolve_mcp_url(gateway_id),
                team_id="default",  # Phase 1: fallback (no DB source)
                user_id=user_id,
                app_user_email=app_user_email,
                access_token=access_token,  # Plain-text in return value
                refresh_token=refresh_token,
                token_type="Bearer",  # nosec B106 - OAuth token_type constant, not a password
                expires_at=expires_at,
                scopes=scopes,
                created_at=token_record.created_at,
                updated_at=now,
            )

        except Exception as e:
            self.db.rollback()
            # Log full detail server-side; surface only a generic message to
            # the caller to avoid leaking DB internals (CWE-209).
            logger.error(
                "Failed to store OAuth tokens for gateway %s: %s",
                SecurityValidator.sanitize_log_message(gateway_id),
                str(e),
                exc_info=True,
            )
            raise OAuthError("Token storage failed")

    async def get_user_token(
        self,
        gateway_id: str,
        team_id: str,  # ← Phase 1: Accepted but NOT used
        app_user_email: str,
        threshold_seconds: int = 300,
    ) -> str | None:
        """Get valid access token, refreshing if necessary.

        Phase 1: team_id parameter is IGNORED. Query uses (gateway_id, app_user_email).

        Args:
            gateway_id: Gateway ID
            team_id: Team identifier (IGNORED in Phase 1)
            app_user_email: ContextForge user email
            threshold_seconds: Seconds before expiry to consider token expired

        Returns:
            Plain-text access token or None
        """
        try:
            # PHASE 1: Query by (gateway_id, app_user_email) - team_id IGNORED
            token_record = self.db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.app_user_email == app_user_email)).scalar_one_or_none()

            if not token_record:
                logger.debug(
                    "No OAuth tokens found for gateway %s, app user %s",
                    SecurityValidator.sanitize_log_message(gateway_id),
                    SecurityValidator.sanitize_log_message(app_user_email),
                )
                return None

            # Verify token_type is Bearer
            if hasattr(token_record, "token_type") and token_record.token_type and token_record.token_type.lower() != "bearer":
                logger.warning(
                    "Unexpected token_type '%s' for gateway %s, app user %s; expected 'Bearer'",
                    token_record.token_type,
                    SecurityValidator.sanitize_log_message(gateway_id),
                    SecurityValidator.sanitize_log_message(app_user_email),
                )

            # Check if token is expired or near expiration
            if self._is_token_expired(token_record, threshold_seconds):
                logger.info(
                    "OAuth token expired for gateway %s, app user %s",
                    SecurityValidator.sanitize_log_message(gateway_id),
                    SecurityValidator.sanitize_log_message(app_user_email),
                )
                if token_record.refresh_token:
                    # Attempt to refresh token
                    new_token = await self._refresh_expired_token(token_record, threshold_seconds)
                    if new_token:
                        return new_token
                return None

            # Decrypt and return valid token
            return await self._decrypt_access_token(token_record.access_token)

        except Exception as e:
            logger.error("Failed to retrieve OAuth token: %s", str(e))
            return None

    async def get_token_info(
        self,
        gateway_id: str,
        team_id: str,  # ← Phase 1: Accepted but NOT used
        app_user_email: str,
    ) -> dict | None:
        """Get non-sensitive token metadata.

        Phase 1: team_id parameter is IGNORED.

        Returns ``None`` only when no token record exists for this
        (gateway_id, app_user_email) pair. An unexpected failure (e.g. a DB
        error) is logged and re-raised rather than swallowed to ``None``, so
        callers exposing this through a user-facing status field (see
        ``mcpgateway.routers.oauth_router._get_caller_token_status``) can
        distinguish "never authorized" from "lookup failed" - the two read
        identically to a caller if both collapse to ``None``.

        Args:
            gateway_id: Gateway ID
            team_id: Team identifier (IGNORED in Phase 1)
            app_user_email: ContextForge user email

        Returns:
            Token info dict, or None if no token is stored.

        Raises:
            Exception: Propagated from the underlying database query on failure.
        """
        try:
            # PHASE 1: Query by (gateway_id, app_user_email) - team_id IGNORED
            token_record = self.db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.app_user_email == app_user_email)).scalar_one_or_none()

            if not token_record:
                return None

            # Determine status
            is_expired = self._is_token_expired(token_record, 0)
            is_near_expiry = not is_expired and self._is_token_expired(token_record, 300)

            if is_expired:
                status = "expired"
            elif is_near_expiry:
                status = "near_expiry"
            else:
                status = "valid"

            return {
                "scopes": token_record.scopes,
                "expires_at": token_record.expires_at.isoformat() if token_record.expires_at else None,
                "status": status,
                "updated_at": token_record.updated_at.isoformat(),
            }

        except Exception as e:
            logger.error("Failed to get token info: %s", str(e))
            raise

    async def get_token_info_bulk(
        self,
        gateway_ids: list[str],
        team_id: str,  # ← Phase 1: Accepted but NOT used
        app_user_email: str,
    ) -> dict[str, dict | Exception | None]:
        """Bulk-lookup non-sensitive token metadata for multiple gateways.

        Overrides the loop-based default in :class:`AbstractTokenBackend` with a
        single ``WHERE gateway_id IN (...) AND app_user_email = :email`` query, so a
        batch status request issues one round trip regardless of how many gateway
        ids it covers.

        Phase 1: team_id parameter is IGNORED (matches get_token_info()).

        Args:
            gateway_ids: Gateway IDs to look up.
            team_id: Team identifier (IGNORED in Phase 1).
            app_user_email: ContextForge user email.

        Returns:
            Mapping of gateway_id to the same dict get_token_info() returns, or
            None for ids with no stored token. Ids with no matching row are simply
            absent from the underlying query result and mapped to None below.

        Raises:
            Exception: Propagated from the underlying database query on failure -
                a single query backs the whole batch, so a DB error is not
                isolated to one id the way the default per-item loop would.
        """
        if not gateway_ids:
            return {}

        try:
            token_records = self.db.execute(select(OAuthToken).where(OAuthToken.gateway_id.in_(gateway_ids), OAuthToken.app_user_email == app_user_email)).scalars().all()
        except Exception as e:
            logger.error("Failed to get bulk token info: %s", str(e))
            raise

        records_by_gateway = {record.gateway_id: record for record in token_records}

        results: dict[str, dict | Exception | None] = {}
        for gateway_id in gateway_ids:
            token_record = records_by_gateway.get(gateway_id)
            if not token_record:
                results[gateway_id] = None
                continue

            is_expired = self._is_token_expired(token_record, 0)
            is_near_expiry = not is_expired and self._is_token_expired(token_record, 300)

            if is_expired:
                status = "expired"
            elif is_near_expiry:
                status = "near_expiry"
            else:
                status = "valid"

            results[gateway_id] = {
                "scopes": token_record.scopes,
                "expires_at": token_record.expires_at.isoformat() if token_record.expires_at else None,
                "status": status,
                "updated_at": token_record.updated_at.isoformat(),
            }

        return results

    async def revoke_user_tokens(
        self,
        gateway_id: str,
        team_id: str,  # ← Phase 1: Accepted but NOT used
        app_user_email: str,
    ) -> bool:
        """Revoke/delete stored tokens.

        Phase 1: team_id parameter is IGNORED.

        Args:
            gateway_id: Gateway ID
            team_id: Team identifier (IGNORED in Phase 1)
            app_user_email: ContextForge user email

        Returns:
            True if deleted, False if not found
        """
        try:
            # PHASE 1: Query by (gateway_id, app_user_email) - team_id IGNORED
            token_record = self.db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.app_user_email == app_user_email)).scalar_one_or_none()

            if token_record:
                self.db.delete(token_record)
                self.db.commit()
                logger.info(
                    "Revoked OAuth tokens for gateway %s, user %s",
                    SecurityValidator.sanitize_log_message(gateway_id),
                    SecurityValidator.sanitize_log_message(app_user_email),
                )
                return True

            return False

        except Exception as e:
            self.db.rollback()
            logger.error("Failed to revoke OAuth tokens: %s", str(e))
            return False

    async def cleanup_expired_tokens(
        self,
        max_age_days: int = 30,
    ) -> int:
        """Clean up stale OAuth tokens.

        Two cohorts are deleted:
        1. Tokens whose expires_at is older than cutoff
        2. Tokens with expires_at IS NULL whose updated_at is older than cutoff

        Args:
            max_age_days: Maximum age of tokens to keep

        Returns:
            Number of tokens deleted
        """
        try:
            cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)

            stale_filter = or_(
                OAuthToken.expires_at < cutoff_date,
                and_(OAuthToken.expires_at.is_(None), OAuthToken.updated_at < cutoff_date),
            )
            result = self.db.execute(delete(OAuthToken).where(stale_filter))
            count = result.rowcount

            self.db.commit()

            if count > 0:
                logger.info("Cleaned up %d stale OAuth tokens", count)

            return count

        except Exception as e:
            self.db.rollback()
            logger.error("Failed to cleanup expired tokens: %s", e)
            return 0

    # ──────────────────────────────────────────────────────────────────────
    # Private helper methods (from original token_storage_service.py)
    # ──────────────────────────────────────────────────────────────────────

    async def _refresh_expired_token(self, token_record: OAuthToken, threshold_seconds: int) -> Optional[str]:
        """Refresh an expired token, unless another request or worker already did.

        Requests that find the same expired token wait on a per-key asyncio lock,
        then on a host-wide file lock shared by all worker processes. The lock
        holder reads the row again before it calls the token endpoint. If the row
        changed since the first read, or the token is no longer expired, another
        request or worker refreshed it. That token is returned, and the refresh
        token is not sent again.

        Args:
            token_record: Expired OAuth token record
            threshold_seconds: Seconds before expiry to consider token expired

        Returns:
            Valid access token, or None if no token is available
        """
        key = (token_record.gateway_id, token_record.app_user_email)
        async with self._refresh_locks.setdefault(key, asyncio.Lock()), _refresh_file_lock(*key):
            current = self._read_stored_token(*key)
            if current is None:
                return None
            if _as_utc(current.updated_at) == _as_utc(token_record.updated_at) and self._is_token_expired(current, threshold_seconds):
                return await self._refresh_access_token(token_record, current.refresh_token)
        # Decrypt after the locks are released, so that waiting requests do not queue behind the key derivation.
        logger.info(
            "OAuth token for gateway %s, app user %s was already refreshed; using the stored token",
            SecurityValidator.sanitize_log_message(token_record.gateway_id),
            SecurityValidator.sanitize_log_message(token_record.app_user_email),
        )
        return await self._decrypt_access_token(current.access_token)

    def _read_stored_token(self, gateway_id: str, app_user_email: str) -> Any:
        """Read the token row as stored, without decrypting the token columns.

        Each encryption uses a new random salt, so only the stored text identifies
        the refresh token that a refresh starts from. Skipping column decryption
        also keeps the key derivation off the event loop.

        Args:
            gateway_id: Gateway ID
            app_user_email: ContextForge user email

        Returns:
            Row with expires_at, updated_at and the stored access_token and
            refresh_token text, or None if the token no longer exists
        """
        statement = select(
            OAuthToken.expires_at,
            OAuthToken.updated_at,
            type_coerce(OAuthToken.access_token, Text).label("access_token"),
            type_coerce(OAuthToken.refresh_token, Text).label("refresh_token"),
        ).where(OAuthToken.gateway_id == gateway_id, OAuthToken.app_user_email == app_user_email)
        return self.db.execute(statement).one_or_none()

    async def _decrypt_access_token(self, access_token: str) -> Optional[str]:
        """Return the plain-text form of a stored access token.

        Args:
            access_token: Access token as stored or as loaded from the token record

        Returns:
            Plain-text access token, or None if decryption fails
        """
        if self.encryption:
            return await self.encryption.decrypt_secret_async(access_token)
        return access_token

    def _claim_unchanged_token(self, token_record: OAuthToken, stored_refresh_token: Optional[str], now: datetime) -> bool:
        """Lock the token row for this transaction if it still holds the given refresh token.

        One guarded UPDATE compares the stored refresh token and locks the row, on
        every supported database. If another request or worker stored new tokens
        after this refresh started, no row matches. The caller must still end the
        transaction, because SQLite takes its database write lock in both cases.

        Args:
            token_record: OAuth token record being refreshed
            stored_refresh_token: Refresh token as stored when the refresh started
            now: Update time to record on the row

        Returns:
            True if the row is unchanged and locked, False otherwise
        """
        statement = (
            update(OAuthToken)
            .where(
                OAuthToken.gateway_id == token_record.gateway_id,
                OAuthToken.app_user_email == token_record.app_user_email,
                type_coerce(OAuthToken.refresh_token, Text) == stored_refresh_token,
            )
            .values(updated_at=now)
            .execution_options(synchronize_session=False)
        )
        result = cast(CursorResult[Any], self.db.execute(statement))
        return result.rowcount != 0

    async def _use_token_stored_concurrently(self, token_record: OAuthToken) -> Optional[str]:
        """Return the token that another request or worker stored during this refresh.

        Args:
            token_record: OAuth token record that this refresh started from

        Returns:
            Stored access token, or None if the token was deleted
        """
        logger.info(
            "OAuth token for gateway %s, user %s changed during refresh; keeping the stored token",
            SecurityValidator.sanitize_log_message(token_record.gateway_id),
            SecurityValidator.sanitize_log_message(token_record.app_user_email),
        )
        current = self._read_stored_token(token_record.gateway_id, token_record.app_user_email)
        # The missed claim wrote nothing. End its transaction before the next await so that SQLite releases its write lock.
        self.db.commit()
        return await self._decrypt_access_token(current.access_token) if current else None

    async def _refresh_access_token(self, token_record: OAuthToken, stored_refresh_token: Optional[str] = None) -> Optional[str]:
        """Refresh an expired access token using refresh token.

        The new tokens are written only if the row still holds the refresh token that
        this refresh read. An invalid_grant response deletes the token under the same
        condition. Otherwise another request or worker stored new tokens, and those
        are kept and returned.

        Args:
            token_record: OAuth token record to refresh
            stored_refresh_token: Refresh token text as stored, if the caller already read it

        Returns:
            New access token or None if refresh failed
        """
        try:
            if stored_refresh_token is None and token_record.refresh_token:
                current = self._read_stored_token(token_record.gateway_id, token_record.app_user_email)
                stored_refresh_token = current.refresh_token if current else None
            if not stored_refresh_token:
                logger.warning("No refresh token available for gateway %s", SecurityValidator.sanitize_log_message(token_record.gateway_id))
                return None

            # Get the gateway configuration
            gateway = self.db.query(Gateway).filter(Gateway.id == token_record.gateway_id).first()

            if not gateway or not gateway.oauth_config:
                logger.error("No OAuth configuration found for gateway %s", SecurityValidator.sanitize_log_message(token_record.gateway_id))
                return None

            # PR #4341: Refuse refresh on private gateway whose owner != token owner
            if not check_private_gateway_access(
                gateway_visibility=getattr(gateway, "visibility", "public"),
                gateway_owner_email=getattr(gateway, "owner_email", None),
                token_owner_email=token_record.app_user_email,
                gateway_id=token_record.gateway_id,
            ):
                return None

            # Decrypt the refresh token
            refresh_token = stored_refresh_token
            if self.encryption:
                try:
                    refresh_token = await self.encryption.decrypt_secret_async(refresh_token)
                except Exception as e:
                    logger.error("Failed to decrypt refresh token: %s", str(e))
                    return None

            # Decrypt client_secret if encryption is available.
            # Always attempt decryption rather than using an is_encrypted() heuristic.
            # Fail closed on decryption failure: decrypt_secret_async() is the idempotent
            # wrapper — it returns None (never raises) when decryption fails due to a wrong
            # key or corrupted ciphertext. Sending None or the raw ciphertext envelope as a
            # literal client_secret to an Authorization Server causes repeated invalid_client
            # attempts that can trigger IdP rate-limiting/lockout. We raise OAuthError on
            # None so the outer OAuthError handler preserves the token for a later retry.
            oauth_config = gateway.oauth_config.copy()
            if "client_secret" in oauth_config and oauth_config["client_secret"]:
                if self.encryption:
                    client_secret_value = oauth_config["client_secret"]
                    decrypted_secret = await self.encryption.decrypt_secret_async(client_secret_value)
                    if decrypted_secret is None:
                        raise OAuthError(
                            f"client_secret decryption failed for gateway {token_record.gateway_id}: "
                            "decrypt_secret_async returned None (wrong AUTH_ENCRYPTION_SECRET or corrupted ciphertext). "
                            "Check that AUTH_ENCRYPTION_SECRET matches the value used when the gateway was stored."
                        )
                    oauth_config["client_secret"] = decrypted_secret

            # RFC 8707: Set resource parameter for JWT access tokens during refresh
            # PR #5244: Apply omit_resource flag and normalize resource parameter
            apply_omit_resource_and_normalize(oauth_config, gateway.url, token_record.gateway_id)

            # Use OAuthManager to refresh the token
            oauth_manager = OAuthManager()

            logger.info(
                "Attempting to refresh token for gateway %s, user %s",
                SecurityValidator.sanitize_log_message(token_record.gateway_id),
                SecurityValidator.sanitize_log_message(token_record.app_user_email),
            )
            token_response = await oauth_manager.refresh_token(
                refresh_token,
                oauth_config,
                ca_certificate=gateway.ca_certificate,
                client_cert=gateway.client_cert,
                client_key=gateway.client_key,
            )

            # Update stored tokens with new values
            new_access_token = token_response["access_token"]
            new_refresh_token = token_response.get("refresh_token", refresh_token)
            expires_in = parse_expires_in(token_response)

            # Encrypt new tokens
            encrypted_access = new_access_token
            encrypted_refresh = new_refresh_token
            if self.encryption:
                encrypted_access = await self.encryption.encrypt_secret_async(new_access_token)
                encrypted_refresh = await self.encryption.encrypt_secret_async(new_refresh_token)

            now = datetime.now(timezone.utc)
            if not self._claim_unchanged_token(token_record, stored_refresh_token, now):
                return await self._use_token_stored_concurrently(token_record)

            # Update the token record
            token_record.access_token = encrypted_access
            token_record.refresh_token = encrypted_refresh
            if expires_in is not None:
                token_record.expires_at = now + timedelta(seconds=expires_in)
            else:
                # PR #5244: Preserve prior TTL if available
                preserved_ttl = compute_prior_ttl(token_record.expires_at, token_record.updated_at, token_record.gateway_id)
                if preserved_ttl is not None:
                    token_record.expires_at = now + timedelta(seconds=preserved_ttl)
                else:
                    logger.info(
                        "No expires_in on refresh response for gateway %s; no prior TTL to preserve",
                        SecurityValidator.sanitize_log_message(token_record.gateway_id),
                    )
                    token_record.expires_at = None
            token_record.updated_at = now

            self.db.commit()
            logger.info(
                "Successfully refreshed token for gateway %s, user %s",
                SecurityValidator.sanitize_log_message(token_record.gateway_id),
                SecurityValidator.sanitize_log_message(token_record.app_user_email),
            )

            return new_access_token

        except OAuthInvalidGrantError as e:
            # RFC 6749 §5.2: invalid_grant is a permanent failure — the refresh
            # token has been revoked, expired, or does not match the grant.
            # OAuthInvalidGrantError is raised by OAuthManager only when the
            # token endpoint explicitly returns {"error": "invalid_grant"}, so
            # this match is based on structured type, not substring heuristics.
            # If the stored refresh token changed after this refresh read it, another
            # request or worker replaced it. The rejection applies only to the old one.
            if not self._claim_unchanged_token(token_record, stored_refresh_token, datetime.now(timezone.utc)):
                return await self._use_token_stored_concurrently(token_record)
            logger.warning(
                "Refresh token is permanently invalid for gateway %s (invalid_grant). Deleting token to force re-authorization. Error: %s",
                token_record.gateway_id,
                str(e),
            )
            self.db.delete(token_record)
            self.db.commit()
            return None
        except OAuthError as e:
            # All other OAuth errors (invalid_client, invalid_request, network
            # failures wrapped as OAuthError, decryption failure, etc.).
            # These are configuration or transient errors — NOT a permanent
            # token failure.  Preserve the token so a later retry can succeed.
            logger.error(
                "Token refresh failed for gateway %s but error does not indicate invalid refresh token. Preserving token for retry. Error: %s",
                token_record.gateway_id,
                str(e),
            )
            return None
        except Exception as e:
            # Non-OAuth errors (network, parsing, encryption, etc.)
            logger.error("Unexpected error refreshing token for gateway %s: %s", token_record.gateway_id, str(e))
            # Preserve token - this is likely a transient or configuration issue
            return None

    async def get_user_learned_audience(
        self,
        gateway_id: str,
        team_id: str,  # ← Phase 1: Accepted but NOT used (no DB column yet)
        app_user_email: str,
    ) -> tuple[str | None, str | None]:
        """Return the per-user learned JWT audience and issuer for a gateway-user pair.

        Used by token_validation_service.validate_oauth_token_claims to authoritatively
        validate a user's token audience against the value learned from their own prior
        OAuth callback, rather than a globally-shared gateway.oauth_config value.

        Phase 1: team_id parameter is IGNORED. Query uses (gateway_id, app_user_email).

        Args:
            gateway_id: ID of the gateway
            team_id: Team identifier (IGNORED in Phase 1 - no DB column yet)
            app_user_email: ContextForge user email

        Returns:
            Tuple of (learned_aud, learned_iss). Either element may be None if
            no token record exists or if the fields were never populated.
        """
        try:
            token_record = self.db.execute(
                select(OAuthToken.learned_aud, OAuthToken.learned_iss).where(
                    OAuthToken.gateway_id == gateway_id,
                    OAuthToken.app_user_email == app_user_email,
                )
            ).one_or_none()
            if token_record is None:
                return (None, None)
            return (token_record.learned_aud, token_record.learned_iss)
        except Exception as e:
            logger.debug(
                "Failed to retrieve learned audience for gateway %s: %s",
                SecurityValidator.sanitize_log_message(gateway_id),
                e,
            )
            return (None, None)

    def _is_token_expired(self, token_record: OAuthToken, threshold_seconds: int = 300) -> bool:
        """Check if token is expired or near expiration.

        Tokens with expires_at IS NULL are returned as non-expired.

        Args:
            token_record: OAuth token record to check
            threshold_seconds: Seconds before expiry to consider token expired

        Returns:
            True if token is expired or near expiration
        """
        if not token_record.expires_at:
            return False  # No provider-supplied lifetime
        expires_at = token_record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) + timedelta(seconds=threshold_seconds) >= expires_at
