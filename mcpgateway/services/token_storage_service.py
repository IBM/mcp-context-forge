# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/token_storage_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

OAuth Token Storage Service for ContextForge.

This module handles the storage, retrieval, and management of OAuth access and refresh tokens
for Authorization Code flow implementations.
"""

# Standard
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional

# Third-Party
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import get_settings
from mcpgateway.db import OAuthToken
from mcpgateway.services.encryption_service import get_encryption_service
from mcpgateway.services.oauth_manager import OAuthError

logger = logging.getLogger(__name__)


def _preserve_prior_ttl(token_record: OAuthToken) -> Optional[int]:
    """Compute the token's prior TTL in seconds, or ``None`` if not derivable.

    Used when an OAuth refresh response omits ``expires_in`` but the token
    previously had a finite lifetime - the gateway preserves the original
    issuance TTL by computing ``expires_at - updated_at`` from the existing
    record. Returns ``None`` when either timestamp is missing or the difference
    is non-positive (clock skew or already-expired records).

    Args:
        token_record: Existing OAuth token row, before the refresh applies.

    Returns:
        Positive integer seconds of prior TTL, or ``None``.

    Examples:
        >>> from types import SimpleNamespace
        >>> from datetime import datetime, timedelta, timezone
        >>> issued = datetime(2026, 1, 1, tzinfo=timezone.utc)
        >>> rec = SimpleNamespace(expires_at=issued + timedelta(hours=1), updated_at=issued)
        >>> _preserve_prior_ttl(rec)
        3600
        >>> _preserve_prior_ttl(SimpleNamespace(expires_at=None, updated_at=issued)) is None
        True
        >>> _preserve_prior_ttl(SimpleNamespace(expires_at=issued, updated_at=issued + timedelta(hours=1))) is None
        True
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


class TokenStorageService:
    """Manages OAuth token storage and retrieval.

    Examples:
        >>> service = TokenStorageService(None)  # Mock DB for doctest
        >>> service.db is None
        True
        >>> service.encryption is not None or service.encryption is None  # Encryption may or may not be available
        True
        >>> # Test token expiration calculation
        >>> from datetime import datetime, timedelta
        >>> expires_in = 3600  # 1 hour
        >>> now = datetime.now(tz=timezone.utc)
        >>> expires_at = now + timedelta(seconds=expires_in)
        >>> expires_at > now
        True
        >>> # Test scope list handling
        >>> scopes = ["read", "write", "admin"]
        >>> isinstance(scopes, list)
        True
        >>> "read" in scopes
        True
        >>> # Test token encryption detection
        >>> short_token = "abc123"
        >>> len(short_token) < 100
        True
        >>> encrypted_token = "gAAAAABh" + "x" * 100
        >>> len(encrypted_token) > 100
        True
    """

    def __init__(self, db: Session):
        """Initialize Token Storage Service.

        Args:
            db: Database session
        """
        self.db = db
        try:
            settings = get_settings()
            self.encryption = get_encryption_service(settings.auth_encryption_secret)
        except (ImportError, AttributeError):
            logger.warning("OAuth encryption not available, using plain text storage")
            self.encryption = None

    async def store_tokens(self, gateway_id: str, user_id: str, app_user_email: str, access_token: str, refresh_token: Optional[str], expires_in: Optional[int], scopes: List[str]) -> OAuthToken:
        """Store OAuth tokens for a gateway-user combination.

        Args:
            gateway_id: ID of the gateway
            user_id: OAuth provider user ID
            app_user_email: ContextForge user email (required)
            access_token: Access token from OAuth provider
            refresh_token: Refresh token from OAuth provider (optional)
            expires_in: Token expiration time in seconds, or None if the provider does not specify expiration
            scopes: List of OAuth scopes granted

        Returns:
            OAuthToken record

        Raises:
            OAuthError: If token storage fails
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
            # Create or update token record - now scoped by app_user_email
            token_record = self.db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.app_user_email == app_user_email)).scalar_one_or_none()

            if token_record:
                # Update existing record
                token_record.user_id = user_id  # Update OAuth provider ID in case it changed
                token_record.access_token = encrypted_access
                token_record.refresh_token = encrypted_refresh
                token_record.expires_at = expires_at
                token_record.scopes = scopes
                token_record.updated_at = datetime.now(timezone.utc)
                logger.info(
                    f"Updated OAuth tokens for gateway {SecurityValidator.sanitize_log_message(gateway_id)}, app user {SecurityValidator.sanitize_log_message(app_user_email)}, OAuth user {SecurityValidator.sanitize_log_message(user_id)}"
                )
            else:
                # Create new record
                token_record = OAuthToken(
                    gateway_id=gateway_id, user_id=user_id, app_user_email=app_user_email, access_token=encrypted_access, refresh_token=encrypted_refresh, expires_at=expires_at, scopes=scopes
                )
                self.db.add(token_record)
                logger.info(
                    f"Stored new OAuth tokens for gateway {SecurityValidator.sanitize_log_message(gateway_id)}, app user {SecurityValidator.sanitize_log_message(app_user_email)}, OAuth user {SecurityValidator.sanitize_log_message(user_id)}"
                )

            self.db.commit()
            return token_record

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to store OAuth tokens: {str(e)}")
            raise OAuthError(f"Token storage failed: {str(e)}")

    async def get_user_token(self, gateway_id: str, app_user_email: str, threshold_seconds: int = 300) -> Optional[str]:
        """Get a valid access token for a specific ContextForge user, refreshing if necessary.

        Args:
            gateway_id: ID of the gateway
            app_user_email: ContextForge user email (required)
            threshold_seconds: Seconds before expiry to consider token expired

        Returns:
            Valid access token or None if no valid token available for this user
        """
        try:
            token_record = self.db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.app_user_email == app_user_email)).scalar_one_or_none()

            if not token_record:
                logger.debug(f"No OAuth tokens found for gateway {SecurityValidator.sanitize_log_message(gateway_id)}, app user {SecurityValidator.sanitize_log_message(app_user_email)}")
                return None

            # Verify token_type is Bearer
            if hasattr(token_record, "token_type") and token_record.token_type and token_record.token_type.lower() != "bearer":
                logger.warning(
                    f"Unexpected token_type '{token_record.token_type}' for gateway "
                    f"{SecurityValidator.sanitize_log_message(gateway_id)}, app user "
                    f"{SecurityValidator.sanitize_log_message(app_user_email)}; expected 'Bearer'"
                )

            # Check if token is expired or near expiration
            if self._is_token_expired(token_record, threshold_seconds):
                logger.info(f"OAuth token expired for gateway {SecurityValidator.sanitize_log_message(gateway_id)}, app user {SecurityValidator.sanitize_log_message(app_user_email)}")
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
            logger.error(f"Failed to retrieve OAuth token: {str(e)}")
            return None

    # REMOVED: get_any_valid_token() - This was a security vulnerability
    # All OAuth tokens MUST be user-specific to prevent cross-user token access

    async def _refresh_access_token(self, token_record: OAuthToken) -> Optional[str]:
        """Refresh an expired access token using refresh token.

        Args:
            token_record: OAuth token record to refresh

        Returns:
            New access token or None if refresh failed
        """
        try:
            if not token_record.refresh_token:
                logger.warning(f"No refresh token available for gateway {token_record.gateway_id}")
                return None

            # Get the gateway configuration to retrieve OAuth settings
            # First-Party
            from mcpgateway.db import Gateway  # pylint: disable=import-outside-toplevel

            gateway = self.db.query(Gateway).filter(Gateway.id == token_record.gateway_id).first()

            if not gateway or not gateway.oauth_config:
                logger.error(f"No OAuth configuration found for gateway {token_record.gateway_id}")
                return None

            # Refuse refresh on a private gateway whose owner is not the token
            # owner (PR #4341 invariant): prevents OAuth secret leakage when a
            # gateway's ownership / visibility changes after token issuance.
            # The token owner is ``app_user_email`` (ContextForge user), not
            # the OAuth provider's ``user_id``. Public and team gateways are
            # not gated here — their RBAC enforcement happens at the call
            # sites that issue refreshes.
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

            # Decrypt the refresh token if encryption is available
            refresh_token = token_record.refresh_token
            if self.encryption:
                try:
                    refresh_token = await self.encryption.decrypt_secret_async(refresh_token)
                except Exception as e:
                    logger.error(f"Failed to decrypt refresh token: {str(e)}")
                    return None

            # Decrypt client_secret if it's encrypted
            oauth_config = gateway.oauth_config.copy()
            if "client_secret" in oauth_config and oauth_config["client_secret"]:
                if self.encryption:
                    try:
                        oauth_config["client_secret"] = await self.encryption.decrypt_secret_async(oauth_config["client_secret"])
                    except Exception:  # nosec B110
                        # If decryption fails, assume it's already plain text - intentional fallback
                        pass

            # RFC 8707: Set resource parameter for JWT access tokens during refresh
            # Standard
            from urllib.parse import urlparse, urlunparse  # pylint: disable=import-outside-toplevel

            def normalize_resource(url: str, *, preserve_query: bool = False) -> str | None:
                """Normalize a resource value per RFC 8707, or pass through opaque identifiers.

                URL-shaped inputs are canonicalized (fragment stripped; query stripped
                or preserved per ``preserve_query``).  Non-URL inputs are returned
                verbatim so that opaque audience identifiers learned from IdPs that do
                not honor RFC 8707 (e.g. ServiceNow / Authentik returning ``aud=client_id``)
                round-trip correctly through token refresh.  RFC 8707 §2 explicitly
                permits the AS to map ``resource`` to an abstract identifier; the
                resource server therefore must accept either form.

                Args:
                    url: Resource URL or opaque audience identifier to normalize.
                    preserve_query: If True, preserve query (for explicit config). If False, strip query.

                Returns:
                    Normalized URL string, the original opaque value, or None if input is empty.
                """
                if not url:
                    return None
                parsed = urlparse(url)
                # If the value lacks a scheme it is not a URL; treat as an opaque
                # audience identifier and pass through verbatim so a learned
                # client_id-style audience survives refresh.
                if not parsed.scheme:
                    return url
                # Remove fragment (MUST NOT); query: preserve for explicit, strip for auto-derived
                query = parsed.query if preserve_query else ""
                return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, ""))

            existing_resource = oauth_config.get("resource")
            if existing_resource:
                # Normalize existing resource - preserve query for explicit config
                if isinstance(existing_resource, list):
                    original_count = len(existing_resource)
                    normalized = [normalize_resource(r, preserve_query=True) for r in existing_resource]
                    oauth_config["resource"] = [r for r in normalized if r]
                    if not oauth_config["resource"] and original_count > 0:
                        logger.warning(f"All {original_count} configured resource values were empty and removed during refresh")
                else:
                    normalized = normalize_resource(existing_resource, preserve_query=True)
                    if not normalized and existing_resource:
                        logger.warning(f"Configured resource was empty and removed during refresh: {existing_resource}")
                    oauth_config["resource"] = normalized
            elif gateway.url:
                # Derive from gateway.url if not explicitly configured (strip query)
                oauth_config["resource"] = normalize_resource(gateway.url)
                if not oauth_config.get("resource"):
                    logger.warning(f"Gateway URL is empty, skipping resource parameter: {gateway.url}")

            # Use OAuthManager to refresh the token
            # First-Party
            from mcpgateway.services.oauth_manager import OAuthManager, parse_expires_in  # pylint: disable=import-outside-toplevel

            oauth_manager = OAuthManager()

            logger.info(f"Attempting to refresh token for gateway {token_record.gateway_id}, user {token_record.app_user_email}")
            token_response = await oauth_manager.refresh_token(
                refresh_token,
                oauth_config,
                ca_certificate=gateway.ca_certificate,
                client_cert=gateway.client_cert,
                client_key=gateway.client_key,
            )

            # Update stored tokens with new values
            new_access_token = token_response["access_token"]
            new_refresh_token = token_response.get("refresh_token", refresh_token)  # Some providers return new refresh token
            # Reuse the same parsing as the initial-auth path so refresh and
            # callback flows agree on what "missing expires_in" means.
            expires_in = parse_expires_in(token_response)

            # Encrypt new tokens if encryption is available
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
                # Refresh response omitted expires_in. If the token previously had a finite
                # expiry, preserve the prior TTL (expires_at - updated_at) so proactive
                # refresh keeps working - clearing it outright would cause _is_token_expired
                # to return False forever and stop the refresh loop. If there was no prior
                # expiry, leave it as None (provider-level "no known lifetime").
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
            logger.info(f"Successfully refreshed token for gateway {token_record.gateway_id}, user {token_record.app_user_email}")

            return new_access_token

        except Exception as e:
            logger.error(f"Failed to refresh OAuth token for gateway {token_record.gateway_id}: {str(e)}")
            # If refresh fails, we should clear the token to force re-authentication
            if "invalid" in str(e).lower() or "expired" in str(e).lower():
                logger.warning(f"Refresh token appears invalid/expired, clearing tokens for gateway {token_record.gateway_id}")
                self.db.delete(token_record)
                self.db.commit()
            return None

    def _is_token_expired(self, token_record: OAuthToken, threshold_seconds: int = 300) -> bool:
        """Check if token is expired or near expiration.

        Tokens with ``expires_at IS NULL`` are returned as non-expired by
        design: when the OAuth provider omits ``expires_in`` (RFC 6749 §5.1
        marks it RECOMMENDED, not REQUIRED — see e.g. GitHub OAuth Apps),
        the gateway has no local lifetime to check against. Stale-token
        accumulation is bounded by
        :meth:`cleanup_expired_tokens`, which ages out NULL-expiry rows
        once ``created_at`` exceeds ``max_age_days``.

        Args:
            token_record: OAuth token record to check
            threshold_seconds: Seconds before expiry to consider token expired

        Returns:
            True if token is expired or near expiration

        Examples:
            >>> from types import SimpleNamespace
            >>> from datetime import datetime, timedelta
            >>> svc = TokenStorageService(None)
            >>> future = datetime.now(tz=timezone.utc) + timedelta(seconds=600)
            >>> past = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
            >>> rec_future = SimpleNamespace(expires_at=future)
            >>> rec_past = SimpleNamespace(expires_at=past)
            >>> svc._is_token_expired(rec_future, threshold_seconds=300)  # 10 min ahead, 5 min threshold
            False
            >>> svc._is_token_expired(rec_future, threshold_seconds=900)  # 10 min ahead, 15 min threshold
            True
            >>> svc._is_token_expired(rec_past, threshold_seconds=0)
            True
            >>> svc._is_token_expired(SimpleNamespace(expires_at=None))
            False
        """
        if not token_record.expires_at:
            # No provider-supplied lifetime; treat as non-expired (see contract above).
            return False
        expires_at = token_record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) + timedelta(seconds=threshold_seconds) >= expires_at

    async def get_token_info(self, gateway_id: str, app_user_email: str) -> Optional[Dict[str, Any]]:
        """Get information about stored OAuth tokens.

        Args:
            gateway_id: ID of the gateway
            app_user_email: ContextForge user email

        Returns:
            Token information dictionary or None if not found

        Examples:
            >>> from types import SimpleNamespace
            >>> from datetime import datetime, timedelta
            >>> svc = TokenStorageService(None)
            >>> now = datetime.now(tz=timezone.utc)
            >>> future = now + timedelta(seconds=60)
            >>> rec = SimpleNamespace(user_id='u1', app_user_email='u1', token_type='bearer', expires_at=future, scopes=['s1'], created_at=now, updated_at=now)
            >>> class _Res:
            ...     def scalar_one_or_none(self):
            ...         return rec
            >>> class _DB:
            ...     def execute(self, *_args, **_kw):
            ...         return _Res()
            >>> svc.db = _DB()
            >>> import asyncio
            >>> info = asyncio.run(svc.get_token_info('g1', 'u1'))
            >>> info['user_id']
            'u1'
            >>> isinstance(info['is_expired'], bool)
            True
        """
        try:
            token_record = self.db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.app_user_email == app_user_email)).scalar_one_or_none()

            if not token_record:
                return None

            return {
                "user_id": token_record.user_id,  # OAuth provider user ID
                "app_user_email": token_record.app_user_email,  # ContextForge user
                "token_type": token_record.token_type,
                "expires_at": token_record.expires_at.isoformat() if token_record.expires_at else None,
                "scopes": token_record.scopes,
                "created_at": token_record.created_at.isoformat(),
                "updated_at": token_record.updated_at.isoformat(),
                "is_expired": self._is_token_expired(token_record, 0),
            }

        except Exception as e:
            logger.error(f"Failed to get token info: {str(e)}")
            return None

    async def revoke_user_tokens(self, gateway_id: str, app_user_email: str) -> bool:
        """Revoke OAuth tokens for a specific user.

        Args:
            gateway_id: ID of the gateway
            app_user_email: ContextForge user email

        Returns:
            True if tokens were revoked successfully

        Examples:
            >>> from types import SimpleNamespace
            >>> from unittest.mock import MagicMock
            >>> svc = TokenStorageService(MagicMock())
            >>> rec = SimpleNamespace()
            >>> svc.db.execute.return_value.scalar_one_or_none.return_value = rec
            >>> svc.db.delete = lambda obj: None
            >>> svc.db.commit = lambda: None
            >>> import asyncio
            >>> asyncio.run(svc.revoke_user_tokens('g1', 'u1'))
            True
            >>> # Not found
            >>> svc.db.execute.return_value.scalar_one_or_none.return_value = None
            >>> asyncio.run(svc.revoke_user_tokens('g1', 'u1'))
            False
        """
        try:
            token_record = self.db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.app_user_email == app_user_email)).scalar_one_or_none()

            if token_record:
                self.db.delete(token_record)
                self.db.commit()
                logger.info(f"Revoked OAuth tokens for gateway {SecurityValidator.sanitize_log_message(gateway_id)}, user {SecurityValidator.sanitize_log_message(app_user_email)}")
                return True

            return False

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to revoke OAuth tokens: {str(e)}")
            return False

    async def cleanup_expired_tokens(self, max_age_days: int = 30) -> int:
        """Clean up stale OAuth tokens older than ``max_age_days``.

        Two cohorts are deleted in a single SQL ``DELETE`` so the table doesn't
        accumulate dead rows:

        1. Tokens whose ``expires_at`` is older than the cutoff (the original
           "expired more than N days ago" behaviour).
        2. Tokens with ``expires_at IS NULL`` (provider omitted ``expires_in``)
           whose ``updated_at`` is older than the cutoff. ``NULL < <cutoff>``
           evaluates to ``NULL`` in SQL three-valued logic, so without this
           branch those rows would never age out. ``updated_at`` (rather than
           ``created_at``) is the right freshness signal because
           ``store_tokens`` advances it on re-authorization, so a recently
           re-authorized token isn't deleted just because its original row was
           old.

        Args:
            max_age_days: Maximum age of tokens to keep, measured from
                ``expires_at`` for tokens with a known expiry and from
                ``updated_at`` for tokens with no provider-supplied expiry.

        Returns:
            Number of tokens cleaned up

        Examples:
            >>> from unittest.mock import MagicMock
            >>> svc = TokenStorageService(MagicMock())
            >>> svc.db.execute.return_value.rowcount = 2
            >>> svc.db.commit = lambda: None
            >>> import asyncio
            >>> asyncio.run(svc.cleanup_expired_tokens(1))
            2
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
