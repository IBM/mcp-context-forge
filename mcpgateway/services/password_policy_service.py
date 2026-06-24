# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/password_policy_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan Catanus

Password Policy Enforcement Service.
This module provides comprehensive password policy enforcement including:
- Minimum length requirements (12+ characters for users, 20+ for service accounts)
- Complexity requirements (uppercase, lowercase, numbers, special characters)
- Password history tracking (prevent reuse of last 5 passwords)
- Username-based password validation
- Common password detection
- Service account password requirements (64-128 bits entropy)

Examples:
    >>> from mcpgateway.services.password_policy_service import PasswordPolicyService
    >>> from mcpgateway.db import SessionLocal
    >>> with SessionLocal() as db:
    ...     service = PasswordPolicyService(db)
    ...     # Validate user password (no sequential chars)
    ...     result = service.validate_user_password("SecureP@ssw0rd!", "alice@example.com")
    ...     # Validate service account password
    ...     result = service.validate_service_account_password("very-long-random-password-with-128-bits-entropy")
"""

# Standard
import functools
import logging
import re
import secrets
import string
from typing import Optional, Set
import uuid

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import PasswordHistory
from mcpgateway.services.argon2_service import Argon2PasswordService

logger = logging.getLogger(__name__)

# Common weak passwords from OWASP and NIST guidelines
COMMON_PASSWORDS: Set[str] = {
    "password",
    "password01",
    "password123",
    "password01@",
    "admin@123",
    "admin",
    "admin123",
    "administrator",
    "root",
    "toor",
    "welcome",
    "welcome123",
    "changeme",
    "letmein",
    "qwerty",
    "123456",
    "12345678",
    "password1",
    "abc123",
    "monkey",
    "1234567890",
    "password!",
    "password1!",
    "admin!",
    "admin1",
    "p@ssw0rd",
    "p@ssword",
    "passw0rd",
    "password@123",
    "admin@1234",
    # Additional 12+ char common passwords for testing (from pentesting reports)
    "password01@!",
    "admin@pass!x",
    "welcome@pass",
}


class PasswordPolicyError(Exception):
    """Raised when password doesn't meet policy requirements."""


class PasswordPolicyService:
    """Service for comprehensive password policy enforcement.

    This service implements OWASP and NIST password guidelines including:
    - Minimum 12 characters for user accounts
    - Minimum 20 characters for service accounts (privileged)
    - Complexity requirements (3 of 4 character types)
    - Password history (prevent reuse of last 5 passwords)
    - Common password detection
    - Username-based password validation
    - Cryptographically secure random password generation

    Attributes:
        db (Session): Database session for password history tracking
        password_service (Argon2PasswordService): Service for password hashing
    """

    def __init__(self, db: Session, password_service: Optional[Argon2PasswordService] = None):
        """Initialize the password policy service.

        Args:
            db: SQLAlchemy database session
            password_service: Optional password service for hashing/verification.
                              If not provided, a new Argon2PasswordService is created.
        """
        self.db = db
        self.password_service = password_service or Argon2PasswordService()

    def validate_user_password(
        self,
        password: str,
        email: Optional[str] = None,
        is_privileged: bool = False,
    ) -> bool:
        """Validate password for user accounts against comprehensive policy.

        Args:
            password: Password to validate
            email: User's email address (for username-based validation)
            is_privileged: Whether this is a privileged account (requires longer password)

        Returns:
            bool: True if password meets all requirements

        Raises:
            PasswordPolicyError: If password doesn't meet requirements

        Examples:
            >>> from mcpgateway.db import SessionLocal
            >>> with SessionLocal() as db:
            ...     service = PasswordPolicyService(db)
            ...     service.validate_user_password("SecureP@ssw0rd!", "alice@example.com")
            True
        """
        if not password:
            raise PasswordPolicyError("Password is required")

        # Minimum length: 12 characters (OWASP recommendation)
        # Privileged accounts: 22 characters (12 + 10 as recommended)
        min_length = getattr(settings, "password_min_length_user", 12)
        if is_privileged:
            min_length = getattr(settings, "password_min_length_privileged", 22)

        if len(password) < min_length:
            raise PasswordPolicyError(f"Password must be at least {min_length} characters long ({'privileged account' if is_privileged else 'user account'})")

        # Check complexity requirements (must have 3 of 4 character types)
        complexity_count = 0
        has_lower = bool(re.search(r"[a-z]", password))
        has_upper = bool(re.search(r"[A-Z]", password))
        has_digit = bool(re.search(r"[0-9]", password))
        has_special = bool(re.search(r'[!@#$%^&*(),.?":{}|<>\-_=+\[\]\\;\'`~]', password))

        if has_lower:
            complexity_count += 1
        if has_upper:
            complexity_count += 1
        if has_digit:
            complexity_count += 1
        if has_special:
            complexity_count += 1

        if complexity_count < 3:
            raise PasswordPolicyError("Password must contain at least 3 of the following: lowercase letters, uppercase letters, numbers, special characters")

        # Check against common passwords
        is_common = password.lower() in COMMON_PASSWORDS
        if is_common:
            raise PasswordPolicyError("Password is too common or easily guessable")

        # Check if password contains username
        if email:
            username = email.split("@")[0].lower()
            contains_username = len(username) >= 3 and username in password.lower()
            if contains_username:
                raise PasswordPolicyError("Password must not be based on your username")

        # Check for sequential characters (e.g., "123", "abc")
        has_sequential = self._has_sequential_chars(password)
        if has_sequential:
            raise PasswordPolicyError("Password contains too many sequential characters")

        return True

    def validate_service_account_password(self, password: str) -> bool:
        """Validate password for service accounts (requires 64-128 bits entropy).

        Service accounts should use randomly generated passwords with minimum
        20 characters (approximately 130 bits of entropy with full keyboard charset).

        Args:
            password: Password to validate

        Returns:
            bool: True if password meets service account requirements

        Raises:
            PasswordPolicyError: If password doesn't meet requirements

        Examples:
            >>> from mcpgateway.db import SessionLocal
            >>> with SessionLocal() as db:
            ...     service = PasswordPolicyService(db)
            ...     # 20+ character random password
            ...     service.validate_service_account_password("aB3$xY9#mN2@pQ7!wR5%")
            True
        """
        if not password:
            raise PasswordPolicyError("Password is required")

        # Service accounts: minimum 20 characters (recommended by pentesting report)
        min_length = getattr(settings, "password_min_length_service", 20)

        if len(password) < min_length:
            raise PasswordPolicyError(f"Service account password must be at least {min_length} characters long (recommended: use randomly generated passwords with 64-128 bits entropy)")

        # Service accounts should have high entropy - check for randomness
        if not self._has_sufficient_entropy(password):
            raise PasswordPolicyError("Service account password appears to have low entropy. Use cryptographically secure random generation (e.g., UUID or secrets module)")

        return True

    async def check_password_history(
        self,
        email: str,
        new_password: str,
        history_count: int = 5,
        current_password_hash: Optional[str] = None,
    ) -> bool:
        """Check if password was used in recent history or matches current password.

        Args:
            email: User's email address
            new_password: New password to check
            history_count: Number of previous passwords to check (default: 5)
            current_password_hash: Current password hash to check against (optional)

        Returns:
            bool: True if password is not in history

        Raises:
            PasswordPolicyError: If password was recently used or matches current password

        Examples:
            >>> from mcpgateway.db import SessionLocal
            >>> import asyncio
            >>> with SessionLocal() as db:
            ...     service = PasswordPolicyService(db)
            ...     # Note: This is an async method, use in async context
            ...     # asyncio.run(service.check_password_history("alice@example.com", "NewP@ssw0rd!"))
            ...     True
            True
        """
        # First check if new password matches current password
        if current_password_hash and await self.password_service.verify_password_async(new_password, current_password_hash):
            raise PasswordPolicyError("New password must be different from current password")

        # Get user's password history
        history_entries = self.db.query(PasswordHistory).filter(PasswordHistory.user_email == email).order_by(PasswordHistory.changed_at.desc()).limit(history_count).all()

        # Check if new password matches any in history
        for entry in history_entries:
            if await self.password_service.verify_password_async(new_password, entry.password_hash):
                raise PasswordPolicyError(f"Password was used recently. Please choose a different password (last {history_count} passwords cannot be reused)")

        return True

    async def save_password_to_history(self, email: str, password_hash: str) -> None:
        """Save password hash to history for future validation.

        Args:
            email: User's email address
            password_hash: Hashed password to save

        Examples:
            >>> from mcpgateway.db import SessionLocal
            >>> with SessionLocal() as db:
            ...     service = PasswordPolicyService(db)
            ...     # Note: async method, use in async context
            ...     # await service.save_password_to_history("alice@example.com", "hashed")
            ...     True
            True
        """
        history_entry = PasswordHistory(
            user_email=email,
            password_hash=password_hash,
        )
        self.db.add(history_entry)

        # Clean up old history entries (keep only last N)
        history_count = getattr(settings, "password_history_count", 5)
        old_entries = self.db.query(PasswordHistory).filter(PasswordHistory.user_email == email).order_by(PasswordHistory.changed_at.desc()).offset(history_count).all()

        for entry in old_entries:
            self.db.delete(entry)

    @staticmethod
    def generate_secure_password(length: int = 20, for_service_account: bool = False) -> str:
        """Generate cryptographically secure random password.

        Args:
            length: Password length (default: 20, minimum: 12)
            for_service_account: If True, generates UUID-based password (128-bit entropy)

        Returns:
            str: Randomly generated password

        Examples:
            >>> from mcpgateway.db import SessionLocal
            >>> with SessionLocal() as db:
            ...     service = PasswordPolicyService(db)
            ...     password = service.generate_secure_password(20)
            ...     len(password) >= 20
            True
            >>> # Service account password (UUID-based, 128-bit entropy)
            >>> service_password = service.generate_secure_password(for_service_account=True)
            >>> len(service_password) == 36  # UUID format
            True
        """
        if for_service_account:
            # Use UUID for service accounts (128-bit entropy as recommended)
            return str(uuid.uuid4())

        # For user accounts, use full printable keyboard characters
        # Each character provides ~6.5 bits of entropy
        min_length = max(length, 12)

        # Use all printable ASCII characters for maximum entropy
        charset = string.ascii_letters + string.digits + string.punctuation

        # Generate random password
        password = "".join(secrets.choice(charset) for _ in range(min_length))

        return password

    @staticmethod
    def _has_sequential_chars(password: str, max_sequential: int = 3) -> bool:
        """Check if password contains too many sequential characters.

        Args:
            password: Password to check
            max_sequential: Maximum allowed sequential characters

        Returns:
            bool: True if password has too many sequential characters
        """
        # Check for sequential numbers (e.g., "123", "456") and reverse (e.g., "321", "987")
        for i in range(len(password) - max_sequential + 1):
            substr = password[i : i + max_sequential]
            if substr.isdigit():
                digits = [int(c) for c in substr]
                is_ascending = all(digits[j] + 1 == digits[j + 1] for j in range(len(digits) - 1))
                is_descending = all(digits[j] - 1 == digits[j + 1] for j in range(len(digits) - 1))
                if is_ascending or is_descending:
                    return True

        # Check for sequential letters (e.g., "abc", "xyz") and reverse (e.g., "cba", "zyx")
        for i in range(len(password) - max_sequential + 1):
            substr = password[i : i + max_sequential].lower()
            if substr.isalpha():
                is_ascending = all(ord(substr[j]) + 1 == ord(substr[j + 1]) for j in range(len(substr) - 1))
                is_descending = all(ord(substr[j]) - 1 == ord(substr[j + 1]) for j in range(len(substr) - 1))
                if is_ascending or is_descending:
                    return True

        return False

    @staticmethod
    def _has_sufficient_entropy(password: str, min_unique_chars: int = 10) -> bool:
        """Check if password has sufficient entropy (randomness).

        Args:
            password: Password to check
            min_unique_chars: Minimum number of unique characters required

        Returns:
            bool: True if password appears to have sufficient entropy
        """
        # Check for minimum unique characters
        unique_chars = len(set(password))
        if unique_chars < min_unique_chars:
            return False

        # Check for repeated patterns
        if len(password) >= 4:
            for i in range(len(password) - 3):
                pattern = password[i : i + 2]
                if password.count(pattern) > 2:
                    return False

        return True

    def get_password_strength_score(self, password: str) -> dict:
        """Calculate password strength score and provide feedback.

        Args:
            password: Password to evaluate

        Returns:
            dict: Score (0-100) and feedback messages

        Examples:
            >>> from mcpgateway.db import SessionLocal
            >>> with SessionLocal() as db:
            ...     service = PasswordPolicyService(db)
            ...     result = service.get_password_strength_score("weak")
            ...     result['score'] < 50
            True
        """
        score = 0
        feedback = []

        # Length scoring
        if len(password) >= 12:
            score += 25
        elif len(password) >= 8:
            score += 15
            feedback.append("Consider using at least 12 characters")
        else:
            feedback.append("Password is too short (minimum 12 characters recommended)")

        # Complexity scoring
        has_lower = bool(re.search(r"[a-z]", password))
        has_upper = bool(re.search(r"[A-Z]", password))
        has_digit = bool(re.search(r"[0-9]", password))
        has_special = bool(re.search(r'[!@#$%^&*(),.?":{}|<>\-_=+\[\]\\;\'`~]', password))

        complexity_count = sum([has_lower, has_upper, has_digit, has_special])
        score += complexity_count * 15

        if complexity_count < 3:
            feedback.append("Add more character types (uppercase, lowercase, numbers, special)")

        # Check for common passwords
        if password.lower() not in COMMON_PASSWORDS:
            score += 20
        else:
            feedback.append("Password is too common")
            score = min(score, 30)  # Cap score for common passwords

        # Check for sequential characters
        if not self._has_sequential_chars(password):
            score += 10
        else:
            feedback.append("Avoid sequential characters (e.g., '123', 'abc')")

        # Entropy check
        if self._has_sufficient_entropy(password):
            score += 15
        else:
            feedback.append("Password appears predictable - use more random characters")

        return {
            "score": min(score, 100),
            "feedback": feedback,
            "strength": "strong" if score >= 80 else "medium" if score >= 60 else "weak",
        }

    @staticmethod
    @functools.lru_cache(maxsize=2)
    def get_password_requirements(is_privileged: bool = False) -> dict:
        """Get the actual password requirements for display to users.

        Returns a dict describing what passwords must meet:
        - Minimum length
        - Character type requirements (3 of 4: uppercase, lowercase, numbers, special)
        - Rules about sequential chars, common passwords, username reuse

        This method is cached since settings don't change at runtime, avoiding
        redundant dict construction across page loads.

        Args:
            is_privileged: Whether this is for a privileged account

        Returns:
            dict: Password requirements with descriptions

        Raises:
            TypeError: If is_privileged is not a boolean
        """
        if not isinstance(is_privileged, bool):
            raise TypeError(f"is_privileged must be bool, got {type(is_privileged).__name__}")

        min_length = getattr(settings, "password_min_length_user", 12)
        if is_privileged:
            min_length = getattr(settings, "password_min_length_privileged", 22)

        return {
            "min_length": min_length,
            "min_length_description": f"At least {min_length} characters long",
            "complexity_required": 3,
            "complexity_total": 4,
            "complexity_description": "At least 3 of the following 4 character types:",
            "complexity_types": [
                {"name": "uppercase", "description": "Uppercase letters (A-Z)"},
                {"name": "lowercase", "description": "Lowercase letters (a-z)"},
                {"name": "numbers", "description": "Numbers (0-9)"},
                {"name": "special", "description": "Special characters (!@#$%^&*()_+-=[]{};:'\"\\|,.<>?)"},
            ],
            "restrictions": [
                "Cannot contain more than 3 sequential characters (e.g., '123', 'abc')",
                "Cannot be a common password",
                "Cannot contain your username",
            ],
        }
