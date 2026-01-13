# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/argon2_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Argon2id Password Hashing Service.
This module provides secure password hashing and verification using Argon2id,
the winner of the Password Hashing Competition and recommended by OWASP.

Examples:
    >>> from mcpgateway.services.argon2_service import Argon2PasswordService
    >>> service = Argon2PasswordService(time_cost=1, memory_cost=1024)  # Light params for testing
    >>> hash = service.hash_password("test123")
    >>> service.verify_password("test123", hash)
    True
    >>> service.verify_password("wrong", hash)
    False
"""

# Standard
from typing import Optional

# Third-Party
from argon2 import PasswordHasher
from argon2.exceptions import HashingError, InvalidHash, VerifyMismatchError

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class Argon2PasswordService:
    """Service for Argon2id password hashing and verification.

    This service provides secure password hashing using Argon2id with
    configurable parameters for time cost, memory cost, and parallelism.
    It follows OWASP recommendations for password storage.

    Attributes:
        hasher (PasswordHasher): Configured Argon2 password hasher

    Examples:
        >>> service = Argon2PasswordService(time_cost=1, memory_cost=1024)  # Light params for testing
        >>> password = "secure_password_123"
        >>> hash_value = service.hash_password(password)
        >>> service.verify_password(password, hash_value)
        True
        >>> service.verify_password("wrong_password", hash_value)
        False
    """

    def __init__(self, time_cost: Optional[int] = None, memory_cost: Optional[int] = None, parallelism: Optional[int] = None, hash_len: int = 32, salt_len: int = 16):
        """Initialize the Argon2 password service.

        Args:
            time_cost: Number of iterations (default from settings)
            memory_cost: Memory usage in KiB (default from settings)
            parallelism: Number of threads (default from settings)
            hash_len: Length of the hash in bytes
            salt_len: Length of the salt in bytes

        Examples:
            >>> service = Argon2PasswordService(time_cost=1, memory_cost=1024)  # Light params for testing
            >>> isinstance(service.hasher, PasswordHasher)
            True
            >>> custom_service = Argon2PasswordService(time_cost=1, memory_cost=2048)
            >>> isinstance(custom_service.hasher, PasswordHasher)
            True
        """
        # Use settings values or provided defaults
        self.time_cost = time_cost or getattr(settings, "argon2id_time_cost", 3)
        self.memory_cost = memory_cost or getattr(settings, "argon2id_memory_cost", 65536)
        self.parallelism = parallelism or getattr(settings, "argon2id_parallelism", 1)

        # Initialize Argon2 password hasher with configured parameters
        self.hasher = PasswordHasher(time_cost=self.time_cost, memory_cost=self.memory_cost, parallelism=self.parallelism, hash_len=hash_len, salt_len=salt_len)

        logger.info(f"Initialized Argon2PasswordService with time_cost={self.time_cost}, memory_cost={self.memory_cost}, parallelism={self.parallelism}")

    def hash_password(self, password: str) -> str:
        """Hash a password using Argon2id.

        Args:
            password: The plain text password to hash

        Returns:
            str: The Argon2id hash string

        Raises:
            ValueError: If password is empty or None
            HashingError: If hashing fails

        Examples:
            >>> service = Argon2PasswordService(time_cost=1, memory_cost=1024)  # Light params for testing
            >>> hash_value = service.hash_password("test123")
            >>> hash_value.startswith("$argon2id$")
            True
            >>> len(hash_value) > 50
            True
            >>> service.hash_password("test123") != service.hash_password("test123")
            True
        """
        if not password:
            raise ValueError("Password cannot be empty or None")

        try:
            hash_value = self.hasher.hash(password)
            logger.debug("Successfully hashed password for user authentication")
            return hash_value
        except HashingError as e:
            logger.error(f"Failed to hash password: {e}")
            raise HashingError(f"Password hashing failed: {e}") from e

    def verify_password(self, password: str, hash_value: str) -> bool:
        """Verify a password against its Argon2id hash.

        Args:
            password: The plain text password to verify
            hash_value: The stored Argon2id hash

        Returns:
            bool: True if password matches hash, False otherwise

        Examples:
            >>> service = Argon2PasswordService(time_cost=1, memory_cost=1024)  # Light params for testing
            >>> hash_val = service.hash_password("correct_password")
            >>> service.verify_password("correct_password", hash_val)
            True
            >>> service.verify_password("wrong_password", hash_val)
            False
            >>> service.verify_password("", hash_val)
            False
        """
        if not password or not hash_value:
            return False

        try:
            # verify() raises VerifyMismatchError if password doesn't match
            self.hasher.verify(hash_value, password)
            logger.debug("Password verification successful")
            return True
        except VerifyMismatchError:
            logger.debug("Password verification failed - password mismatch")
            return False
        except (InvalidHash, ValueError) as e:
            logger.warning(f"Invalid hash format during verification: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during password verification: {e}")
            return False

    def needs_rehash(self, hash_value: str) -> bool:
        """Check if a hash needs to be rehashed due to parameter changes.

        This is useful for gradually updating password hashes when you
        change Argon2 parameters (e.g., increasing time_cost for security).

        Args:
            hash_value: The stored Argon2id hash to check

        Returns:
            bool: True if hash should be updated, False otherwise

        Examples:
            >>> service = Argon2PasswordService(time_cost=1, memory_cost=1024)  # Light params for testing
            >>> hash_val = service.hash_password("test")
            >>> service.needs_rehash(hash_val)
            False
            >>> service_new = Argon2PasswordService(time_cost=2, memory_cost=1024)
            >>> service_new.needs_rehash(hash_val)
            True
        """
        if not hash_value:
            return True

        try:
            return self.hasher.check_needs_rehash(hash_value)
        except (InvalidHash, ValueError) as e:
            logger.warning(f"Invalid hash format when checking rehash need: {e}")
            return True
        except Exception as e:
            logger.error(f"Unexpected error checking rehash need: {e}")
            return True

    def get_hash_info(self, hash_value: str) -> Optional[dict]:
        """Extract information from an Argon2 hash.

        Args:
            hash_value: The Argon2id hash to analyze

        Returns:
            dict: Hash parameters or None if invalid

        Examples:
            >>> service = Argon2PasswordService(time_cost=1, memory_cost=1024)  # Light params for testing
            >>> hash_val = service.hash_password("test")
            >>> info = service.get_hash_info(hash_val)
            >>> info is not None
            True
            >>> 'time_cost' in info
            True
            >>> 'memory_cost' in info
            True
        """
        if not hash_value:
            return None

        try:
            # Parse the hash to extract parameters
            # Argon2 hash format: $argon2id$v=19$m=65536,t=3,p=1$salt$hash
            parts = hash_value.split("$")
            if len(parts) < 4 or parts[1] != "argon2id":
                return None

            params_part = parts[3]  # m=65536,t=3,p=1
            params = {}

            for param in params_part.split(","):
                key, value = param.split("=")
                if key == "m":
                    params["memory_cost"] = int(value)
                elif key == "t":
                    params["time_cost"] = int(value)
                elif key == "p":
                    params["parallelism"] = int(value)

            params["variant"] = "argon2id"
            if len(parts) > 2:
                params["version"] = parts[2]

            return params
        except (ValueError, IndexError) as e:
            logger.warning(f"Failed to parse Argon2 hash info: {e}")
            return None

    def __repr__(self) -> str:
        """String representation of the service.

        Returns:
            str: String representation of Argon2PasswordService instance
        """
        return f"Argon2PasswordService(time_cost={self.time_cost}, memory_cost={self.memory_cost}, parallelism={self.parallelism})"


# Global instance for use throughout the application
password_service = Argon2PasswordService()


def hash_password(password: str) -> str:
    """Hash a password using the global Argon2 service.

    Convenience function for password hashing.

    Args:
        password: The password to hash

    Returns:
        str: The hashed password

    Examples:
        >>> service = Argon2PasswordService(time_cost=1, memory_cost=1024)  # Light params for testing
        >>> hash_val = service.hash_password("test123")
        >>> hash_val.startswith("$argon2id$")
        True
    """
    return password_service.hash_password(password)


def verify_password(password: str, hash_value: str) -> bool:
    """Verify a password using the global Argon2 service.

    Convenience function for password verification.

    Args:
        password: The password to verify
        hash_value: The stored hash

    Returns:
        bool: True if password matches

    Examples:
        >>> service = Argon2PasswordService(time_cost=1, memory_cost=1024)  # Light params for testing
        >>> hash_val = service.hash_password("test123")
        >>> service.verify_password("test123", hash_val)
        True
        >>> service.verify_password("wrong", hash_val)
        False
    """
    return password_service.verify_password(password, hash_value)


def needs_rehash(hash_value: str) -> bool:
    """Check if a hash needs rehashing using the global service.

    Args:
        hash_value: The hash to check

    Returns:
        bool: True if rehash is needed
    """
    return password_service.needs_rehash(hash_value)
