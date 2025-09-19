# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/oauth_encryption.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

OAuth Encryption Utilities.

This module provides encryption and decryption functions for OAuth client secrets
using the AUTH_ENCRYPTION_SECRET from configuration.
"""

# Standard
import base64
import logging
from typing import Optional

# Third-Party
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


class OAuthEncryption:
    """Handles encryption and decryption of OAuth client secrets.

    Examples:
        Basic roundtrip:
        >>> enc = OAuthEncryption('very-secret-key')
        >>> cipher = enc.encrypt_secret('hello')
        >>> isinstance(cipher, str) and enc.is_encrypted(cipher)
        True
        >>> enc.decrypt_secret(cipher)
        'hello'

        Non-encrypted text detection:
        >>> enc.is_encrypted('plain-text')
        False
    """

    def __init__(self, encryption_secret: str):
        """Initialize the encryption handler.

        Args:
            encryption_secret: Secret key for encryption/decryption
        """
        self.encryption_secret = encryption_secret.encode()
        self._fernet = None

    def _get_fernet(self) -> Fernet:
        """Get or create Fernet instance for encryption.

        Returns:
            Fernet instance for encryption/decryption
        """
        if self._fernet is None:
            # Derive a key from the encryption secret using PBKDF2
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"mcp_gateway_oauth",  # Fixed salt for consistency
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(self.encryption_secret))
            self._fernet = Fernet(key)
        return self._fernet

    def encrypt_secret(self, plaintext: str) -> str:
        """Encrypt a plaintext secret.

        Args:
            plaintext: The secret to encrypt

        Returns:
            Base64-encoded encrypted string

        Raises:
            Exception: If encryption fails
        """
        try:
            fernet = self._get_fernet()
            encrypted = fernet.encrypt(plaintext.encode())
            return base64.urlsafe_b64encode(encrypted).decode()
        except Exception as e:
            logger.error(f"Failed to encrypt OAuth secret: {e}")
            raise

    def decrypt_secret(self, encrypted_text: str) -> Optional[str]:
        """Decrypt an encrypted secret.

        Args:
            encrypted_text: Base64-encoded encrypted string

        Returns:
            Decrypted secret string, or None if decryption fails
        """
        try:
            fernet = self._get_fernet()
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_text.encode())
            decrypted = fernet.decrypt(encrypted_bytes)
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Failed to decrypt OAuth secret: {e}")
            return None

    def is_encrypted(self, text: str) -> bool:
        """Check if a string appears to be encrypted.

        Args:
            text: String to check

        Returns:
            True if the string appears to be encrypted
        """
        try:
            # Try to decode as base64 and check if it looks like encrypted data
            decoded = base64.urlsafe_b64decode(text.encode())
            # Encrypted data should be at least 32 bytes (Fernet minimum)
            return len(decoded) >= 32
        except Exception:
            return False


def get_oauth_encryption(encryption_secret: str) -> OAuthEncryption:
    """Get an OAuth encryption instance.

    Args:
        encryption_secret: Secret key for encryption/decryption

    Returns:
        OAuthEncryption instance

    Examples:
        >>> enc = get_oauth_encryption('k')
        >>> isinstance(enc, OAuthEncryption)
        True
    """
    return OAuthEncryption(encryption_secret)
