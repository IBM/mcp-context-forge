"""
Database token storage backend.

Phase 1: Minimal extraction (copy-paste from existing token_storage_service.py).
Accepts team_id parameter but COMPLETELY IGNORES it - no database schema changes.
This is purely code reorganization to enable the façade pattern.

Phase 2 (future): Add team_id column to oauth_tokens table and use it in queries.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import Settings
from mcpgateway.db import Gateway, OAuthToken
from mcpgateway.services.encryption_service import get_encryption_service
from mcpgateway.services.oauth_manager import OAuthError, OAuthManager, parse_expires_in

from .base import AbstractTokenBackend, TokenRecord, normalize_resource_url

logger = logging.getLogger(__name__)


def _preserve_prior_ttl(token_record: OAuthToken) -> Optional[int]:
    """Compute the token's prior TTL in seconds, or None if not derivable.

    Used when an OAuth refresh response omits expires_in but the token
    previously had a finite lifetime - the gateway preserves the original
    issuance TTL by computing expires_at - updated_at from the existing
    record. Returns None when either timestamp is missing or the difference
    is non-positive (clock skew or already-expired records).

    Args:
        token_record: Existing OAuth token row, before the refresh applies.

    Returns:
        Positive integer seconds of prior TTL, or None.
    """
    prev_expires_at = token_record.expires_at
    prev_updated_at = token_record.updated_at
    if prev_expires_at is None or prev_updated_at is None:
        return None
    # Normalize naive timestamps to UTC for the subtraction.
    if prev_expires_at.tzinfo is None:
        prev_expires_at = prev_expires_at.replace(tzinfo=timezone.utc)
    if prev_updated_at.tzinfo is None:
        prev_updated_at = prev_updated_at.replace(tzinfo=timezone.utc)
    prev_ttl = int((prev_expires_at - prev_updated_at).total_seconds())
    if prev_ttl <= 0:
        return None
    return prev_ttl


class DatabaseTokenBackend(AbstractTokenBackend):
    """
    Database token storage backend (Phase 1 - minimal extraction).

    IMPORTANT: Accepts team_id parameter but COMPLETELY IGNORES it.
    NO database schema changes. SQL queries use (gateway_id, app_user_email) as before.
    This is purely code reorganization to enable the façade pattern.

    Phase 2 will add team_id column and update queries.
    """

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
            token_record = self.db.execute(
                select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.app_user_email == app_user_email)
            ).scalar_one_or_none()

            now = datetime.now(timezone.utc)

            if token_record:
                # Update existing record
                token_record.user_id = user_id
                token_record.access_token = encrypted_access
                token_record.refresh_token = encrypted_refresh
                token_record.expires_at = expires_at
                token_record.scopes = scopes
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
                token_type="Bearer",
                expires_at=expires_at,
                scopes=scopes,
                created_at=token_record.created_at,
                updated_at=now,
            )

        except Exception as e:
            self.db.rollback()
            logger.error("Failed to store OAuth tokens: %s", str(e))
            raise OAuthError(f"Token storage failed: {str(e)}")

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
            token_record = self.db.execute(
                select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.app_user_email == app_user_email)
            ).scalar_one_or_none()

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
                    new_token = await self._refresh_access_token(token_record)
                    if new_token:
                        return new_token
                return None

            # Decrypt and return valid token
            if self.encryption:
                return await self.encryption.decrypt_secret_async(token_record.access_token)
            return token_record.access_token

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

        Args:
            gateway_id: Gateway ID
            team_id: Team identifier (IGNORED in Phase 1)
            app_user_email: ContextForge user email

        Returns:
            Token info dict or None
        """
        try:
            # PHASE 1: Query by (gateway_id, app_user_email) - team_id IGNORED
            token_record = self.db.execute(
                select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.app_user_email == app_user_email)
            ).scalar_one_or_none()

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
            return None

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
            token_record = self.db.execute(
                select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.app_user_email == app_user_email)
            ).scalar_one_or_none()

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

    async def _refresh_access_token(self, token_record: OAuthToken) -> Optional[str]:
        """Refresh an expired access token using refresh token.

        Args:
            token_record: OAuth token record to refresh

        Returns:
            New access token or None if refresh failed
        """
        try:
            if not token_record.refresh_token:
                logger.warning("No refresh token available for gateway %s", token_record.gateway_id)
                return None

            # Get the gateway configuration
            gateway = self.db.query(Gateway).filter(Gateway.id == token_record.gateway_id).first()

            if not gateway or not gateway.oauth_config:
                logger.error("No OAuth configuration found for gateway %s", token_record.gateway_id)
                return None

            # PR #4341: Refuse refresh on private gateway whose owner != token owner
            gateway_visibility = getattr(gateway, "visibility", "public")
            gateway_owner_email = getattr(gateway, "owner_email", None)
            if gateway_visibility == "private" and gateway_owner_email and gateway_owner_email != token_record.app_user_email:
                logger.warning(
                    "OAuth refresh denied: gateway %s is private and owned by %s, not token owner %s",
                    token_record.gateway_id,
                    gateway_owner_email,
                    token_record.app_user_email,
                )
                return None

            # Decrypt the refresh token
            refresh_token = token_record.refresh_token
            if self.encryption:
                try:
                    refresh_token = await self.encryption.decrypt_secret_async(refresh_token)
                except Exception as e:
                    logger.error("Failed to decrypt refresh token: %s", str(e))
                    return None

            # Decrypt client_secret if encrypted
            oauth_config = gateway.oauth_config.copy()
            if "client_secret" in oauth_config and oauth_config["client_secret"]:
                if self.encryption:
                    try:
                        oauth_config["client_secret"] = await self.encryption.decrypt_secret_async(oauth_config["client_secret"])
                    except Exception:  # nosec B110
                        pass  # If decryption fails, assume plain text

            # RFC 8707: Set resource parameter for JWT access tokens during refresh
            existing_resource = oauth_config.get("resource")
            if existing_resource:
                if isinstance(existing_resource, list):
                    normalized = [normalize_resource_url(r, preserve_query=True) for r in existing_resource]
                    oauth_config["resource"] = [r for r in normalized if r]
                else:
                    oauth_config["resource"] = normalize_resource_url(existing_resource, preserve_query=True)
            elif gateway.url:
                oauth_config["resource"] = normalize_resource_url(gateway.url)

            # Use OAuthManager to refresh the token
            oauth_manager = OAuthManager()

            logger.info("Attempting to refresh token for gateway %s, user %s", token_record.gateway_id, token_record.app_user_email)
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

            # Update the token record
            token_record.access_token = encrypted_access
            token_record.refresh_token = encrypted_refresh
            now = datetime.now(timezone.utc)
            if expires_in is not None:
                token_record.expires_at = now + timedelta(seconds=expires_in)
            else:
                # Preserve prior TTL if available
                preserved_ttl = _preserve_prior_ttl(token_record)
                if preserved_ttl is not None:
                    logger.info(
                        "No expires_in on refresh response for gateway %s; preserving prior TTL of %d seconds",
                        SecurityValidator.sanitize_log_message(token_record.gateway_id),
                        preserved_ttl,
                    )
                    token_record.expires_at = now + timedelta(seconds=preserved_ttl)
                else:
                    logger.info(
                        "No expires_in on refresh response for gateway %s; no prior TTL to preserve",
                        SecurityValidator.sanitize_log_message(token_record.gateway_id),
                    )
                    token_record.expires_at = None
            token_record.updated_at = now

            self.db.commit()
            logger.info("Successfully refreshed token for gateway %s, user %s", token_record.gateway_id, token_record.app_user_email)

            return new_access_token

        except Exception as e:
            logger.error("Failed to refresh OAuth token for gateway %s: %s", token_record.gateway_id, str(e))
            # If refresh fails with invalid/expired error, clear tokens
            if "invalid" in str(e).lower() or "expired" in str(e).lower():
                logger.warning("Refresh token appears invalid/expired, clearing tokens for gateway %s", token_record.gateway_id)
                self.db.delete(token_record)
                self.db.commit()
            return None

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
