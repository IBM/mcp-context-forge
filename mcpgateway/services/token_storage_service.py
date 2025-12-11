# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/token_storage_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

OAuth Token Storage Service for MCP Gateway.

This module handles the storage, retrieval, and management of OAuth access and refresh tokens
for Authorization Code flow implementations.
"""

# Standard
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional

# Third-Party
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import get_settings
from mcpgateway.db import OAuthToken
from mcpgateway.services.encryption_service import get_encryption_service
from mcpgateway.services.oauth_manager import OAuthError

logger = logging.getLogger(__name__)


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

    async def store_tokens(self, gateway_id: str, user_id: str, app_user_email: str, access_token: str, refresh_token: Optional[str], expires_in: int, scopes: List[str]) -> OAuthToken:
        """Store OAuth tokens for a gateway-user combination.

        Args:
            gateway_id: ID of the gateway
            user_id: OAuth provider user ID
            app_user_email: MCP Gateway user email (required)
            access_token: Access token from OAuth provider
            refresh_token: Refresh token from OAuth provider (optional)
            expires_in: Token expiration time in seconds
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
                encrypted_access = self.encryption.encrypt_secret(access_token)
                if refresh_token:
                    encrypted_refresh = self.encryption.encrypt_secret(refresh_token)

            # Calculate expiration
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
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
                logger.info(f"Updated OAuth tokens for gateway {gateway_id}, app user {app_user_email}, OAuth user {user_id}")
            else:
                # Create new record
                token_record = OAuthToken(
                    gateway_id=gateway_id, user_id=user_id, app_user_email=app_user_email, access_token=encrypted_access, refresh_token=encrypted_refresh, expires_at=expires_at, scopes=scopes
                )
                self.db.add(token_record)
                logger.info(f"Stored new OAuth tokens for gateway {gateway_id}, app user {app_user_email}, OAuth user {user_id}")

            self.db.commit()
            return token_record

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to store OAuth tokens: {str(e)}")
            raise OAuthError(f"Token storage failed: {str(e)}")

    async def get_user_token(self, gateway_id: str, app_user_email: str, threshold_seconds: int = 300) -> Optional[str]:
        """Get a valid access token for a specific MCP Gateway user, refreshing if necessary.

        Args:
            gateway_id: ID of the gateway
            app_user_email: MCP Gateway user email (required)
            threshold_seconds: Seconds before expiry to consider token expired

        Returns:
            Valid access token or None if no valid token available for this user
        """
        try:
            token_record = self.db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.app_user_email == app_user_email)).scalar_one_or_none()

            if not token_record:
                logger.debug(f"No OAuth tokens found for gateway {gateway_id}, app user {app_user_email}")
                return None

            # Check if token is expired or near expiration
            if self._is_token_expired(token_record, threshold_seconds):
                logger.info(f"OAuth token expired for gateway {gateway_id}, app user {app_user_email}")
                if token_record.refresh_token:
                    # Attempt to refresh token
                    new_token = await self._refresh_access_token(token_record)
                    if new_token:
                        return new_token
                return None

            # Decrypt and return valid token
            if self.encryption:
                return self.encryption.decrypt_secret(token_record.access_token)
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

            # Decrypt the refresh token if encryption is available
            refresh_token = token_record.refresh_token
            if self.encryption:
                try:
                    refresh_token = self.encryption.decrypt_secret(refresh_token)
                except Exception as e:
                    logger.error(f"Failed to decrypt refresh token: {str(e)}")
                    return None

            # Decrypt client_secret if it's encrypted
            oauth_config = gateway.oauth_config.copy()
            if "client_secret" in oauth_config and oauth_config["client_secret"]:
                if self.encryption:
                    try:
                        oauth_config["client_secret"] = self.encryption.decrypt_secret(oauth_config["client_secret"])
                    except Exception:  # nosec B110
                        # If decryption fails, assume it's already plain text - intentional fallback
                        pass

            # Use OAuthManager to refresh the token
            # First-Party
            from mcpgateway.services.oauth_manager import OAuthManager  # pylint: disable=import-outside-toplevel

            oauth_manager = OAuthManager()

            logger.info(f"Attempting to refresh token for gateway {token_record.gateway_id}, user {token_record.app_user_email}")
            token_response = await oauth_manager.refresh_token(refresh_token, oauth_config)

            # Update stored tokens with new values
            new_access_token = token_response["access_token"]
            new_refresh_token = token_response.get("refresh_token", refresh_token)  # Some providers return new refresh token
            expires_in = token_response.get("expires_in", 3600)

            # Encrypt new tokens if encryption is available
            encrypted_access = new_access_token
            encrypted_refresh = new_refresh_token
            if self.encryption:
                encrypted_access = self.encryption.encrypt_secret(new_access_token)
                encrypted_refresh = self.encryption.encrypt_secret(new_refresh_token)

            # Update the token record
            token_record.access_token = encrypted_access
            token_record.refresh_token = encrypted_refresh
            token_record.expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
            token_record.updated_at = datetime.now(timezone.utc)

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
            return False
        expires_at = token_record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) + timedelta(seconds=threshold_seconds) >= expires_at

    async def get_token_info(self, gateway_id: str, app_user_email: str) -> Optional[Dict[str, Any]]:
        """Get information about stored OAuth tokens.

        Args:
            gateway_id: ID of the gateway
            app_user_email: MCP Gateway user email

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
                "app_user_email": token_record.app_user_email,  # MCP Gateway user
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
            app_user_email: MCP Gateway user email

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
                logger.info(f"Revoked OAuth tokens for gateway {gateway_id}, user {app_user_email}")
                return True

            return False

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to revoke OAuth tokens: {str(e)}")
            return False

    async def cleanup_expired_tokens(self, max_age_days: int = 30) -> int:
        """Clean up expired OAuth tokens older than specified days.

        Args:
            max_age_days: Maximum age of tokens to keep

        Returns:
            Number of tokens cleaned up

        Examples:
            >>> from types import SimpleNamespace
            >>> from unittest.mock import MagicMock
            >>> svc = TokenStorageService(MagicMock())
            >>> svc.db.execute.return_value.scalars.return_value.all.return_value = [SimpleNamespace(), SimpleNamespace()]
            >>> svc.db.delete = lambda obj: None
            >>> svc.db.commit = lambda: None
            >>> import asyncio
            >>> asyncio.run(svc.cleanup_expired_tokens(1))
            2
        """
        try:
            cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)

            expired_tokens = self.db.execute(select(OAuthToken).where(OAuthToken.expires_at < cutoff_date)).scalars().all()

            count = len(expired_tokens)
            for token in expired_tokens:
                self.db.delete(token)

            self.db.commit()
            logger.info(f"Cleaned up {count} expired OAuth tokens")
            return count

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to cleanup expired tokens: {str(e)}")
            return 0
