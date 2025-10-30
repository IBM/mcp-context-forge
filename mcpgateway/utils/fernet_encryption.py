# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/oauth_encryption.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Fernet Encryption Utilities.

This module provides encryption and decryption functions for client secrets
using the AUTH_ENCRYPTION_SECRET from configuration.
"""

# Standard
import base64
import json
import logging
import os
from typing import Optional

# Third-Party
from argon2.low_level import hash_secret_raw, Type
from cryptography.fernet import Fernet
from pydantic import SecretStr

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


class FernetEncryption:
    """Handles Fernet encryption and decryption of client secrets.

    Examples:
        Basic roundtrip:
        >>> enc = FernetEncryption(SecretStr('very-secret-key'))
        >>> cipher = enc.encrypt_secret('hello')
        >>> isinstance(cipher, str) and enc.is_encrypted(cipher)
        True
        >>> enc.decrypt_secret(cipher)
        'hello'

        Non-encrypted text detection:
        >>> enc.is_encrypted('plain-text')
        False
    """

    def __init__(self, encryption_secret: SecretStr, time_cost: Optional[int] = None, memory_cost: Optional[int] = None, parallelism: Optional[int] = None, hash_len: int = 32, salt_len: int = 16):
        """Initialize the encryption handler.

        Args:
            encryption_secret: Secret key for encryption/decryption
            time_cost: Argon2id time cost parameter
            memory_cost: Argon2id memory cost parameter (in KiB)
            parallelism: Argon2id parallelism parameter
            hash_len: Length of the derived key
            salt_len: Length of the salt
        """
        self.encryption_secret = encryption_secret.get_secret_value().encode()
        self.time_cost = time_cost or getattr(settings, "argon2id_time_cost", 3)
        self.memory_cost = memory_cost or getattr(settings, "argon2id_memory_cost", 65536)
        self.parallelism = parallelism or getattr(settings, "argon2id_parallelism", 1)
        self.hash_len = hash_len
        self.salt_len = salt_len

    def derive_key_argon2id(self, passphrase: bytes, salt: bytes, time_cost: int, memory_cost: int, parallelism: int) -> bytes:
        raw = hash_secret_raw(
            secret=passphrase,
            salt=salt,
            time_cost=time_cost,
            memory_cost=memory_cost,  # KiB
            parallelism=parallelism,
            hash_len=self.hash_len,
            type=Type.ID,
        )
        return base64.urlsafe_b64encode(raw)

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
            salt = os.urandom(16)
            key = self.derive_key_argon2id(self.encryption_secret, salt, self.time_cost, self.memory_cost, self.parallelism)
            fernet = Fernet(key)
            encrypted = fernet.encrypt(plaintext.encode())
            return json.dumps(
                {
                    "kdf": "argon2id",
                    "t": self.time_cost,
                    "m": self.memory_cost,
                    "p": self.parallelism,
                    "salt": base64.b64encode(salt).decode(),
                    "token": encrypted.decode(),
                }
            )
        except Exception as e:
            logger.error(f"Failed to encrypt secret: {e}")
            raise

    def decrypt_secret(self, bundle_json: str) -> Optional[str]:
        """Decrypt an encrypted secret.

        Args:
            bundle_json: str: JSON string containing encryption metadata and token

        Returns:
            Decrypted secret string, or None if decryption fails
        """
        try:
            b = json.loads(bundle_json)
            salt = base64.b64decode(b["salt"])
            key = self.derive_key_argon2id(self.encryption_secret, salt, time_cost=b["t"], memory_cost=b["m"], parallelism=b["p"])
            fernet = Fernet(key)
            decrypted = fernet.decrypt(b["token"].encode())
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Failed to decrypt secret: {e}")
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


def get_fernet_encryption(encryption_secret: SecretStr) -> FernetEncryption:
    """Get an Fernet encryption instance.

    Args:
        encryption_secret: Secret key for encryption/decryption

    Returns:
        FernetEncryption instance

    Examples:
        >>> enc = get_fernet_encryption(SecretStr('k'))
        >>> isinstance(enc, FernetEncryption)
        True
    """
    return FernetEncryption(encryption_secret)
