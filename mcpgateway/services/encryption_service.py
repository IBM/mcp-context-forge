# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/encryption_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Madhav Kandukuri

Encryption Service.

This service provides encryption and decryption functions for client secrets
using the AUTH_ENCRYPTION_SECRET from configuration.
"""

# Standard
import base64
import logging
import os
from typing import Optional, Union

# Third-Party
from argon2.low_level import hash_secret_raw, Type
from cryptography.fernet import Fernet
import orjson
from pydantic import SecretStr

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


class EncryptionService:
    """Handles encryption and decryption of client secrets.

    Examples:
        Basic roundtrip:
        >>> enc = EncryptionService(SecretStr('very-secret-key'))
        >>> cipher = enc.encrypt_secret('hello')
        >>> isinstance(cipher, str) and enc.is_encrypted(cipher)
        True
        >>> enc.decrypt_secret(cipher)
        'hello'

        Non-encrypted text detection:
        >>> enc.is_encrypted('plain-text')
        False
    """

    def __init__(
        self, encryption_secret: Union[SecretStr, str], time_cost: Optional[int] = None, memory_cost: Optional[int] = None, parallelism: Optional[int] = None, hash_len: int = 32, salt_len: int = 16
    ):
        """Initialize the encryption handler.

        Args:
            encryption_secret: Secret key for encryption/decryption
            time_cost: Argon2id time cost parameter
            memory_cost: Argon2id memory cost parameter (in KiB)
            parallelism: Argon2id parallelism parameter
            hash_len: Length of the derived key
            salt_len: Length of the salt
        """
        # Handle both SecretStr and plain string for backwards compatibility
        if isinstance(encryption_secret, SecretStr):
            self.encryption_secret = encryption_secret.get_secret_value().encode()
        else:
            # If a plain string is passed, use it directly (for testing/legacy code)
            self.encryption_secret = str(encryption_secret).encode()
        self.time_cost = time_cost or getattr(settings, "argon2id_time_cost", 3)
        self.memory_cost = memory_cost or getattr(settings, "argon2id_memory_cost", 65536)
        self.parallelism = parallelism or getattr(settings, "argon2id_parallelism", 1)
        self.hash_len = hash_len
        self.salt_len = salt_len

    def derive_key_argon2id(self, passphrase: bytes, salt: bytes, time_cost: int, memory_cost: int, parallelism: int) -> bytes:
        """Derive a key from a passphrase using Argon2id.

        Args:
            passphrase: The passphrase to derive the key from
            salt: The salt to use in key derivation
            time_cost: Argon2id time cost parameter
            memory_cost: Argon2id memory cost parameter (in KiB)
            parallelism: Argon2id parallelism parameter

        Returns:
            The derived key
        """
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
            return orjson.dumps(
                {
                    "kdf": "argon2id",
                    "t": self.time_cost,
                    "m": self.memory_cost,
                    "p": self.parallelism,
                    "salt": base64.b64encode(salt).decode(),
                    "token": encrypted.decode(),
                }
            ).decode()
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
            b = orjson.loads(bundle_json)
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

        Note:
            Supports both legacy PBKDF2 (base64-wrapped Fernet) and new Argon2id
            (JSON bundle) formats. Checks JSON format first, then falls back to
            base64 check for legacy format.
        """
        if not text:
            return False

        # Check for new Argon2id JSON bundle format
        if text.startswith("{"):
            try:
                obj = orjson.loads(text)
                if isinstance(obj, dict) and obj.get("kdf") == "argon2id":
                    return True
            except (orjson.JSONDecodeError, ValueError, KeyError):
                # Not valid JSON or missing expected structure - continue to legacy check
                pass

        # Check for legacy PBKDF2 base64-wrapped Fernet format
        try:
            decoded = base64.urlsafe_b64decode(text.encode())
            # Encrypted data should be at least 32 bytes (Fernet minimum)
            return len(decoded) >= 32
        except Exception:
            return False


def get_encryption_service(encryption_secret: Union[SecretStr, str]) -> EncryptionService:
    """Get an EncryptionService instance.

    Args:
        encryption_secret: Secret key for encryption/decryption (SecretStr or plain string)

    Returns:
        EncryptionService instance

    Examples:
        >>> enc = get_encryption_service(SecretStr('k'))
        >>> isinstance(enc, EncryptionService)
        True
        >>> enc2 = get_encryption_service('plain-key')
        >>> isinstance(enc2, EncryptionService)
        True
    """
    return EncryptionService(encryption_secret)
