# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/argon2_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Argon2id Password Hashing Service.
Enhanced security password hashing to replace bcrypt (#544).
"""

# Standard
import logging
import secrets

try:
    # Third-Party
    from argon2 import PasswordHasher
    from argon2.exceptions import HashingError, VerifyMismatchError

    ARGON2_AVAILABLE = True
except ImportError:
    ARGON2_AVAILABLE = False
    PasswordHasher = None

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


class Argon2PasswordService:
    """
    Argon2id password hashing service for enhanced security.

    Implements issue #544: Database-Backed User Authentication with Argon2id
    """

    def __init__(self):
        """Initialize Argon2id password hasher with configured parameters."""
        if not ARGON2_AVAILABLE:
            logger.warning("Argon2 not available, falling back to bcrypt")
            self.hasher = None
            return

        # Use settings or secure defaults
        time_cost = getattr(settings, "argon2id_time_cost", 3)
        memory_cost = getattr(settings, "argon2id_memory_cost", 65536)  # 64 MB
        parallelism = getattr(settings, "argon2id_parallelism", 1)

        self.hasher = PasswordHasher(time_cost=time_cost, memory_cost=memory_cost, parallelism=parallelism, hash_len=32, salt_len=16)

        logger.info(f"Argon2id initialized: time_cost={time_cost}, memory_cost={memory_cost}, parallelism={parallelism}")

    def hash_password(self, password: str) -> str:
        """
        Hash password using Argon2id.

        Args:
            password: Plain text password

        Returns:
            str: Argon2id hash of the password

        Raises:
            HashingError: If hashing fails
        """
        if not self.hasher:
            # Fallback to bcrypt if Argon2 not available
            logger.warning("Argon2 not available, using bcrypt fallback")
            # First-Party
            from mcpgateway.services.user_service import PasswordPolicy

            return PasswordPolicy.hash_password(password)

        try:
            return self.hasher.hash(password)
        except Exception as e:
            logger.error(f"Argon2id hashing failed: {e}")
            raise HashingError(f"Password hashing failed: {e}")

    def verify_password(self, password: str, password_hash: str) -> bool:
        """
        Verify password against Argon2id hash.

        Args:
            password: Plain text password
            password_hash: Argon2id hash or bcrypt hash (for backward compatibility)

        Returns:
            bool: True if password matches hash
        """
        if not password_hash:
            return False

        try:
            # Try Argon2id verification first
            if self.hasher and password_hash.startswith("$argon2"):
                try:
                    self.hasher.verify(password_hash, password)
                    return True
                except VerifyMismatchError:
                    return False

            # Fallback to bcrypt for legacy hashes
            if password_hash.startswith("$2b$"):
                logger.debug("Using bcrypt verification for legacy hash")
                # First-Party
                from mcpgateway.services.user_service import PasswordPolicy

                return PasswordPolicy.verify_password(password, password_hash)

            # Try Argon2 verification for any other format
            if self.hasher:
                try:
                    self.hasher.verify(password_hash, password)
                    return True
                except VerifyMismatchError:
                    return False

            return False

        except Exception as e:
            logger.warning(f"Password verification failed: {e}")
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        """
        Check if password hash needs to be updated.

        Args:
            password_hash: Current password hash

        Returns:
            bool: True if hash should be updated
        """
        if not self.hasher:
            return False

        # Rehash bcrypt hashes to Argon2id
        if password_hash.startswith("$2b$"):
            return True

        # Check if Argon2 parameters need updating
        if password_hash.startswith("$argon2"):
            try:
                return self.hasher.check_needs_rehash(password_hash)
            except:
                return False

        return False

    def generate_secure_token(self, length: int = 32) -> str:
        """
        Generate cryptographically secure random token.

        Args:
            length: Token length in bytes

        Returns:
            str: URL-safe base64 encoded token
        """
        return secrets.token_urlsafe(length)


# Global service instance
argon2_service = Argon2PasswordService()


def get_argon2_service() -> Argon2PasswordService:
    """Get the global Argon2 password service instance."""
    return argon2_service
