# -*- coding: utf-8 -*-
"""Token storage for simple authentication.

Provides both in-memory and file-based token storage for simple authentication tokens.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import orjson

logger = logging.getLogger(__name__)


class TokenData:
    """Data associated with an authentication token."""

    def __init__(
        self,
        token: str,
        email: str,
        full_name: str,
        is_admin: bool = False,
        created_at: Optional[datetime] = None,
        expires_at: Optional[datetime] = None,
    ):
        """Initialize token data.

        Args:
            token: The authentication token string
            email: User's email address
            full_name: User's full name
            is_admin: Whether user has admin privileges
            created_at: When token was created
            expires_at: When token expires (None = never expires)
        """
        self.token = token
        self.email = email
        self.full_name = full_name
        self.is_admin = is_admin
        self.created_at = created_at or datetime.now(timezone.utc)
        self.expires_at = expires_at

    def is_expired(self) -> bool:
        """Check if token is expired."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "token": self.token,
            "email": self.email,
            "full_name": self.full_name,
            "is_admin": self.is_admin,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TokenData":
        """Create TokenData from dictionary."""
        return cls(
            token=data["token"],
            email=data["email"],
            full_name=data["full_name"],
            is_admin=data.get("is_admin", False),
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
        )


class TokenStorage:
    """Simple token storage with file-based persistence."""

    def __init__(self, storage_file: Optional[str] = None):
        """Initialize token storage.

        Args:
            storage_file: Path to file for persisting tokens. If None, uses memory only.
        """
        self.storage_file = Path(storage_file) if storage_file else None
        self.tokens: dict[str, TokenData] = {}
        self._load_tokens()

    def _load_tokens(self):
        """Load tokens from file if it exists."""
        if self.storage_file and self.storage_file.exists():
            try:
                with open(self.storage_file, "rb") as f:
                    data = orjson.loads(f.read())
                    for token_dict in data.get("tokens", []):
                        token_data = TokenData.from_dict(token_dict)
                        if not token_data.is_expired():
                            self.tokens[token_data.token] = token_data
                logger.info(f"Loaded {len(self.tokens)} tokens from {self.storage_file}")
            except Exception as e:
                logger.warning(f"Failed to load tokens from {self.storage_file}: {e}")

    def _save_tokens(self):
        """Save tokens to file."""
        if not self.storage_file:
            return

        try:
            # Ensure parent directory exists
            self.storage_file.parent.mkdir(parents=True, exist_ok=True)

            # Save active tokens only
            data = {"tokens": [td.to_dict() for td in self.tokens.values() if not td.is_expired()]}

            with open(self.storage_file, "wb") as f:
                f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))
            logger.debug(f"Saved {len(data['tokens'])} tokens to {self.storage_file}")
        except Exception as e:
            logger.error(f"Failed to save tokens to {self.storage_file}: {e}")

    def generate_token(self) -> str:
        """Generate a secure random token."""
        return secrets.token_urlsafe(32)

    def create_token(
        self,
        email: str,
        full_name: str,
        is_admin: bool = False,
        expires_in_days: Optional[int] = None,
    ) -> str:
        """Create a new authentication token for a user.

        Args:
            email: User's email address
            full_name: User's full name
            is_admin: Whether user has admin privileges
            expires_in_days: Number of days until token expires (None = never)

        Returns:
            The generated token string
        """
        token = self.generate_token()
        expires_at = None
        if expires_in_days is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

        token_data = TokenData(
            token=token,
            email=email,
            full_name=full_name,
            is_admin=is_admin,
            expires_at=expires_at,
        )

        self.tokens[token] = token_data
        self._save_tokens()

        logger.info(f"Created token for {email}, expires: {expires_at or 'never'}")
        return token

    def validate_token(self, token: str) -> Optional[TokenData]:
        """Validate a token and return associated user data.

        Args:
            token: The token to validate

        Returns:
            TokenData if valid, None if invalid or expired
        """
        token_data = self.tokens.get(token)
        if token_data is None:
            return None

        if token_data.is_expired():
            logger.info(f"Token expired for {token_data.email}")
            self.revoke_token(token)
            return None

        return token_data

    def revoke_token(self, token: str) -> bool:
        """Revoke a token.

        Args:
            token: The token to revoke

        Returns:
            True if token was revoked, False if token didn't exist
        """
        if token in self.tokens:
            email = self.tokens[token].email
            del self.tokens[token]
            self._save_tokens()
            logger.info(f"Revoked token for {email}")
            return True
        return False

    def revoke_user_tokens(self, email: str) -> int:
        """Revoke all tokens for a specific user.

        Args:
            email: User's email address

        Returns:
            Number of tokens revoked
        """
        tokens_to_revoke = [token for token, data in self.tokens.items() if data.email == email]
        for token in tokens_to_revoke:
            del self.tokens[token]

        if tokens_to_revoke:
            self._save_tokens()
            logger.info(f"Revoked {len(tokens_to_revoke)} tokens for {email}")

        return len(tokens_to_revoke)

    def cleanup_expired(self) -> int:
        """Remove expired tokens.

        Returns:
            Number of tokens removed
        """
        expired = [token for token, data in self.tokens.items() if data.is_expired()]
        for token in expired:
            del self.tokens[token]

        if expired:
            self._save_tokens()
            logger.info(f"Cleaned up {len(expired)} expired tokens")

        return len(expired)

    def list_active_tokens(self) -> list[TokenData]:
        """List all active (non-expired) tokens.

        Returns:
            List of TokenData objects
        """
        return [data for data in self.tokens.values() if not data.is_expired()]
