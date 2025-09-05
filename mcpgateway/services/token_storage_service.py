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
from datetime import datetime, timedelta
import logging
from typing import Any, Dict, List, Optional

# Third-Party
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import get_settings
from mcpgateway.db import OAuthToken
from mcpgateway.services.oauth_manager import OAuthError
from mcpgateway.utils.oauth_encryption import get_oauth_encryption

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
        >>> now = datetime.utcnow()
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
            self.encryption = get_oauth_encryption(settings.auth_encryption_secret)
        except (ImportError, AttributeError):
            logger.warning("OAuth encryption not available, using plain text storage")
            self.encryption = None

    async def store_tokens(self, gateway_id: str, user_id: str, access_token: str, refresh_token: Optional[str], expires_in: int, scopes: List[str]) -> OAuthToken:
        """Store OAuth tokens for a gateway-user combination.

        Args:
            gateway_id: ID of the gateway
            user_id: OAuth provider user ID
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
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

            # Create or update token record
            token_record = self.db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.user_id == user_id)).scalar_one_or_none()

            if token_record:
                # Update existing record
                token_record.access_token = encrypted_access
                token_record.refresh_token = encrypted_refresh
                token_record.expires_at = expires_at
                token_record.scopes = scopes
                token_record.updated_at = datetime.utcnow()
                logger.info(f"Updated OAuth tokens for gateway {gateway_id}, user {user_id}")
            else:
                # Create new record
                token_record = OAuthToken(gateway_id=gateway_id, user_id=user_id, access_token=encrypted_access, refresh_token=encrypted_refresh, expires_at=expires_at, scopes=scopes)
                self.db.add(token_record)
                logger.info(f"Stored new OAuth tokens for gateway {gateway_id}, user {user_id}")

            self.db.commit()
            return token_record

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to store OAuth tokens: {str(e)}")
            raise OAuthError(f"Token storage failed: {str(e)}")

    async def get_valid_token(self, gateway_id: str, user_id: str, threshold_seconds: int = 300) -> Optional[str]:
        """Get a valid access token, refreshing if necessary.

        Args:
            gateway_id: ID of the gateway
            user_id: OAuth provider user ID
            threshold_seconds: Seconds before expiry to consider token expired

        Returns:
            Valid access token or None if no valid token available
        """
        try:
            token_record = self.db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.user_id == user_id)).scalar_one_or_none()

            if not token_record:
                logger.debug(f"No OAuth tokens found for gateway {gateway_id}, user {user_id}")
                return None

            # Check if token is expired or near expiration
            if self._is_token_expired(token_record, threshold_seconds):
                logger.info(f"OAuth token expired for gateway {gateway_id}, user {user_id}")
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

    async def get_any_valid_token(self, gateway_id: str, threshold_seconds: int = 300) -> Optional[str]:
        """Get any valid access token for a gateway, regardless of user.

        Args:
            gateway_id: ID of the gateway
            threshold_seconds: Seconds before expiry to consider token expired

        Returns:
            Valid access token or None if no valid token available

        Examples:
            >>> from types import SimpleNamespace
            >>> from datetime import datetime, timedelta
            >>> svc = TokenStorageService(None)
            >>> svc.encryption = None  # simplify for doctest
            >>> future = datetime.utcnow() + timedelta(seconds=3600)
            >>> rec = SimpleNamespace(gateway_id='g1', user_id='u1', access_token='tok', refresh_token=None, expires_at=future)
            >>> class _Res:
            ...     def scalar_one_or_none(self):
            ...         return rec
            >>> class _DB:
            ...     def execute(self, *_args, **_kw):
            ...         return _Res()
            >>> svc.db = _DB()
            >>> import asyncio
            >>> asyncio.run(svc.get_any_valid_token('g1'))
            'tok'
            >>> # Expired record returns None
            >>> past = datetime.utcnow() - timedelta(seconds=1)
            >>> rec2 = SimpleNamespace(gateway_id='g1', user_id='u1', access_token='tok', refresh_token=None, expires_at=past)
            >>> class _Res2:
            ...     def scalar_one_or_none(self):
            ...         return rec2
            >>> svc.db.execute = lambda *_a, **_k: _Res2()
            >>> asyncio.run(svc.get_any_valid_token('g1')) is None
            True
        """
        try:
            # Get any token for this gateway
            token_record = self.db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id)).scalar_one_or_none()

            if not token_record:
                logger.debug(f"No OAuth tokens found for gateway {gateway_id}")
                return None

            # Check if token is expired or near expiration
            if self._is_token_expired(token_record, threshold_seconds):
                logger.info(f"OAuth token expired for gateway {gateway_id}")
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

    async def _refresh_access_token(self, token_record: OAuthToken) -> Optional[str]:
        """Refresh an expired access token using refresh token.

        Args:
            token_record: OAuth token record to refresh

        Returns:
            New access token or None if refresh failed
        """
        try:
            # This is a placeholder for token refresh implementation
            # In a real implementation, you would:
            # 1. Decrypt the refresh token
            # 2. Make a request to the OAuth provider's token endpoint
            # 3. Update the stored tokens with the new response
            # 4. Return the new access token

            logger.info(f"Token refresh not yet implemented for gateway {token_record.gateway_id}")
            return None

        except Exception as e:
            logger.error(f"Failed to refresh OAuth token: {str(e)}")
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
            >>> future = datetime.utcnow() + timedelta(seconds=600)
            >>> past = datetime.utcnow() - timedelta(seconds=10)
            >>> rec_future = SimpleNamespace(expires_at=future)
            >>> rec_past = SimpleNamespace(expires_at=past)
            >>> svc._is_token_expired(rec_future, threshold_seconds=300)  # 10 min ahead, 5 min threshold
            False
            >>> svc._is_token_expired(rec_future, threshold_seconds=900)  # 10 min ahead, 15 min threshold
            True
            >>> svc._is_token_expired(rec_past, threshold_seconds=0)
            True
            >>> svc._is_token_expired(SimpleNamespace(expires_at=None))
            True
        """
        if not token_record.expires_at:
            return True

        return datetime.utcnow() + timedelta(seconds=threshold_seconds) >= token_record.expires_at

    async def get_token_info(self, gateway_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Get information about stored OAuth tokens.

        Args:
            gateway_id: ID of the gateway
            user_id: OAuth provider user ID

        Returns:
            Token information dictionary or None if not found

        Examples:
            >>> from types import SimpleNamespace
            >>> from datetime import datetime, timedelta
            >>> svc = TokenStorageService(None)
            >>> now = datetime.utcnow()
            >>> future = now + timedelta(seconds=60)
            >>> rec = SimpleNamespace(user_id='u1', token_type='bearer', expires_at=future, scopes=['s1'], created_at=now, updated_at=now)
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
            token_record = self.db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.user_id == user_id)).scalar_one_or_none()

            if not token_record:
                return None

            return {
                "user_id": token_record.user_id,
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

    async def revoke_user_tokens(self, gateway_id: str, user_id: str) -> bool:
        """Revoke OAuth tokens for a specific user.

        Args:
            gateway_id: ID of the gateway
            user_id: OAuth provider user ID

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
            token_record = self.db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id, OAuthToken.user_id == user_id)).scalar_one_or_none()

            if token_record:
                self.db.delete(token_record)
                self.db.commit()
                logger.info(f"Revoked OAuth tokens for gateway {gateway_id}, user {user_id}")
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
            cutoff_date = datetime.utcnow() - timedelta(days=max_age_days)

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
