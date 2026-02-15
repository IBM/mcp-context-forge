# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/encryption_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Madhav Kandukuri, Mohan Lakshmaiah

Encryption Service for Client Secrets.

Handles encryption and decryption of client secrets using Argon2id-derived
Fernet keys with explicit format markers for secure detection.

## Format & Detection

**New Format (v2):**
- Encrypted bundles are JSON objects prefixed with "v2:" marker
- Format: "v2:{...json...}"
- Contains explicit version, KDF type, parameters, salt, and encrypted token
- Always detectable by strict validation

**Legacy Support:**
- Fernet binary format (version byte 0x80 marker)
- JSON bundles with argon2id KDF (without v2: prefix)
- Accepted for reading, but all new encryptions use v2 format

## Detection & Security

**Strict Detection:**
- Checks v2: prefix first (most reliable)
- Falls back to legacy Fernet version byte (0x80)
- Validates all required JSON keys before considering data encrypted
- Returns False for ambiguous data (safe default)

**WARNING: Do NOT use is_encrypted() for security decisions:**
- Edge cases exist where plaintext JSON could theoretically match encrypted structure
- Always validate encryption state at storage boundaries
- Use explicit markers when possible (e.g., in database schema)

## API Usage

**Strict Mode** (for validation/auditing):
- `encrypt_secret(plaintext: str) -> str` – Raises if already encrypted
- `decrypt_secret(bundle: str) -> str` – Raises if not encrypted or fails
- Forces calling code to be explicit about intent

**Idempotent Mode** (for resilience):
- `decrypt_secret_or_plaintext(bundle: str) -> Optional[str]` – Returns plaintext if not encrypted
- `decrypt_secret_async(bundle: str) -> Optional[str]` – Backward compatible async wrapper

**Async Variants:**
- `encrypt_secret_async()` – Async encryption
- `decrypt_secret_async()` – Idempotent async (backward compatible)
- `decrypt_secret_strict_async()` – Strict async
- `decrypt_secret_or_plaintext_async()` – Idempotent async

## Error Handling

| Scenario | Strict Mode | Idempotent Mode |
|----------|-------------|-----------------|
| Encrypt plaintext | Returns encrypted bundle | Returns encrypted bundle |
| Encrypt already-encrypted | Raises `AlreadyEncryptedError` | Raises `AlreadyEncryptedError` |
| Decrypt valid bundle | Returns plaintext | Returns plaintext |
| Decrypt plaintext | Raises `NotEncryptedError` | Returns plaintext unchanged |
| Decrypt corrupted data | Raises `ValueError` | Returns None |
| Wrong decryption key | Raises `ValueError` | Returns None |

## Migration Strategy

1. **Phase 1 (Current)**: New encryptions use v2 format, decryptions accept both
2. **Phase 2 (Next sprint)**: Background job migrates legacy data to v2
3. **Phase 3 (When 95%+ migrated)**: Deprecate legacy format support
4. **Phase 4 (Next release)**: Remove legacy code

## Performance Notes

- Argon2id KDF: tuned for 3ms on modern hardware (see config)
- Random salt per encryption: unique ciphertexts for same plaintext
- Thread-safe: Each call derives unique salt/nonce
- Async via `asyncio.to_thread()`: scales to thread pool
"""

# Standard
import asyncio
import base64
import binascii
import logging
import os
from typing import Optional, Union

# Third-Party
from argon2.low_level import hash_secret_raw, Type
from cryptography.fernet import Fernet, InvalidToken
import orjson
from pydantic import SecretStr

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


class AlreadyEncryptedError(ValueError):
    """Raised when encrypt_secret() is called on already-encrypted data."""


class NotEncryptedError(ValueError):
    """Raised when decrypt_secret() is called on plaintext data."""


class EncryptionService:
    """Service for encrypting/decrypting client secrets using Argon2id-derived Fernet.

    Provides strict and idempotent modes for different use cases:
    - Strict mode: `encrypt_secret()` and `decrypt_secret()` for explicit validation
    - Idempotent mode: `decrypt_secret_or_plaintext()` for resilient decryption

    All new encryptions produce v2 format (v2:{json}). Legacy formats are still
    accepted for backward compatibility.

    Example (Strict Mode):
        ```python
        svc = EncryptionService(SecretStr("key"))
        encrypted = svc.encrypt_secret("my_secret")  # Returns "v2:{...}"
        plaintext = svc.decrypt_secret(encrypted)    # Returns "my_secret"
        # Raises AlreadyEncryptedError if called on already-encrypted data
        ```

    Example (Idempotent Mode):
        ```python
        # Returns plaintext unchanged, or None on error
        result = svc.decrypt_secret_or_plaintext(data)
        ```

    Thread-safe: All methods generate unique random salt/nonce per call.
    """

    # Format marker for new encrypted bundles
    FORMAT_MARKER = "v2:"
    FORMAT_VERSION = "v2"

    def __init__(
        self,
        encryption_secret: Union[SecretStr, str],
        time_cost: Optional[int] = None,
        memory_cost: Optional[int] = None,
        parallelism: Optional[int] = None,
        hash_len: int = 32,
        salt_len: int = 16,
    ):
        """Initialize the encryption service.

        Args:
            encryption_secret: Secret key for encryption/decryption (SecretStr or string)
            time_cost: Argon2id time cost parameter (default: from settings or 3)
            memory_cost: Argon2id memory cost parameter in KiB (default: from settings or 65536)
            parallelism: Argon2id parallelism parameter (default: from settings or 1)
            hash_len: Length of derived key in bytes (default: 32)
            salt_len: Length of salt in bytes (default: 16)
        """
        if isinstance(encryption_secret, SecretStr):
            self.encryption_secret = encryption_secret.get_secret_value().encode()
        else:
            self.encryption_secret = str(encryption_secret).encode()

        self.time_cost = time_cost or getattr(settings, "argon2id_time_cost", 3)
        self.memory_cost = memory_cost or getattr(settings, "argon2id_memory_cost", 65536)
        self.parallelism = parallelism or getattr(settings, "argon2id_parallelism", 1)
        self.hash_len = hash_len
        self.salt_len = salt_len

    def derive_key_argon2id(self, passphrase: bytes, salt: bytes, time_cost: int, memory_cost: int, parallelism: int) -> bytes:
        """Derive encryption key using Argon2id KDF.

        Args:
            passphrase: Secret passphrase to derive key from
            salt: Random salt for key derivation
            time_cost: Argon2id time cost parameter
            memory_cost: Argon2id memory cost parameter (in KiB)
            parallelism: Argon2id parallelism parameter

        Returns:
            Base64-encoded derived key ready for Fernet
        """
        raw = hash_secret_raw(
            secret=passphrase,
            salt=salt,
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=self.hash_len,
            type=Type.ID,
        )
        return base64.urlsafe_b64encode(raw)

    def encrypt_secret(self, plaintext: str) -> str:
        """Encrypt plaintext to v2 format with explicit marker.

        STRICT: Raises AlreadyEncryptedError if input is already encrypted.
        Caller must check is_encrypted() first if input origin is uncertain.

        Args:
            plaintext: Unencrypted secret to encrypt

        Returns:
            str: Encrypted bundle as "v2:{json}" string

        Raises:
            AlreadyEncryptedError: If input is already encrypted
            ValueError: If encryption fails
        """
        if self.is_encrypted(plaintext):
            raise AlreadyEncryptedError("Input is already encrypted. Use decrypt_secret() first, or use decrypt_secret_or_plaintext() if you need idempotent behavior.")

        try:
            salt = os.urandom(16)
            key = self.derive_key_argon2id(self.encryption_secret, salt, self.time_cost, self.memory_cost, self.parallelism)
            fernet = Fernet(key)
            token = fernet.encrypt(plaintext.encode()).decode()

            bundle_obj = {
                "version": self.FORMAT_VERSION,
                "kdf": "argon2id",
                "t": self.time_cost,
                "m": self.memory_cost,
                "p": self.parallelism,
                "salt": base64.b64encode(salt).decode(),
                "token": token,
            }

            json_str = orjson.dumps(bundle_obj).decode()
            return f"{self.FORMAT_MARKER}{json_str}"
        except Exception as e:
            logger.error("Failed to encrypt secret: %s", e)
            raise ValueError(f"Encryption failed: {e}") from e

    async def encrypt_secret_async(self, plaintext: str) -> str:
        """Async wrapper for encrypt_secret().

        Args:
            plaintext: Unencrypted secret to encrypt

        Returns:
            str: Encrypted bundle as "v2:{json}" string
        """
        return await asyncio.to_thread(self.encrypt_secret, plaintext)

    def decrypt_secret(self, bundle_json: str) -> str:
        """Decrypt an encrypted bundle (strict mode).

        STRICT: Raises NotEncryptedError if input is not encrypted.
        Raises DecryptionError if bundle is corrupted/invalid.

        Use decrypt_secret_or_plaintext() if you need idempotent behavior.

        Args:
            bundle_json: Encrypted bundle (with or without v2: prefix)

        Returns:
            str: Decrypted plaintext

        Raises:
            NotEncryptedError: If input is not encrypted
            ValueError: If decryption fails (corrupted/invalid data)
        """
        if not self.is_encrypted(bundle_json):
            raise NotEncryptedError("Input is not encrypted. Use decrypt_secret_or_plaintext() for idempotent behavior.")

        return self._decrypt_bundle(bundle_json)

    async def decrypt_secret_strict_async(self, bundle_json: str) -> str:
        """Async wrapper for decrypt_secret() (STRICT mode).

        Raises exceptions if input is not encrypted or decryption fails.
        Use this when you need explicit error handling.

        Args:
            bundle_json: Encrypted bundle (with or without v2: prefix)

        Returns:
            str: Decrypted plaintext
        """
        return await asyncio.to_thread(self.decrypt_secret, bundle_json)

    # NOTE: This async wrapper remains IDEMPOTENT for backward compatibility.
    # - Returns plaintext unchanged if input is not encrypted.
    # - Returns decrypted plaintext if input is encrypted.
    # - Returns None if decryption fails.
    # Prefer `decrypt_secret_strict_async()` or `decrypt_secret()` when strict validation is required.
    async def decrypt_secret_async(self, bundle_json: str) -> Optional[str]:
        """Async wrapper for decrypt_secret_or_plaintext() (IDEMPOTENT for backward compatibility).

        BACKWARD COMPATIBLE: This is idempotent for existing code.
        - Returns plaintext if not encrypted
        - Returns decrypted plaintext if encrypted
        - Returns None if decryption fails

        For strict error handling, use decrypt_secret_strict_async() or decrypt_secret().

        Args:
            bundle_json: Encrypted bundle or plaintext

        Returns:
            Optional[str]: Decrypted plaintext if encrypted, original input if plaintext, or None on failure
        """
        return await asyncio.to_thread(self.decrypt_secret_or_plaintext, bundle_json)

    # Idempotent helper: safe to call repeatedly. Returns original input for plaintext.
    def decrypt_secret_or_plaintext(self, bundle_json: str) -> Optional[str]:
        """Decrypt if encrypted, return plaintext unchanged if not (idempotent).

        Args:
            bundle_json: Encrypted bundle or plaintext

        Returns:
            Optional[str]: Decrypted plaintext if encrypted, original input if plaintext.
                None if bundle is encrypted but decryption fails.

        This method is idempotent: calling it multiple times is safe.
        Use decrypt_secret() if you need strict error handling.
        """
        is_encrypted = self.is_encrypted(bundle_json)
        if not is_encrypted:
            # For data that starts with encryption markers but failed validation,
            # return None (it was supposed to be encrypted but is corrupted)
            if bundle_json.startswith(self.FORMAT_MARKER):
                # Has v2: prefix but failed validation - corrupted encrypted data
                # Return None since this is almost certainly corrupted encryption
                logger.error("Input has v2: prefix but failed validation: %s", bundle_json[:50])
                return None

            # No encryption markers - treat as plaintext
            return bundle_json

        try:
            return self._decrypt_bundle(bundle_json)
        except Exception as e:
            logger.error("Failed to decrypt secret: %s", e)
            return None

    async def decrypt_secret_or_plaintext_async(self, bundle_json: str) -> Optional[str]:
        """Async wrapper for decrypt_secret_or_plaintext().

        Args:
            bundle_json: Encrypted bundle or plaintext

        Returns:
            Optional[str]: Decrypted plaintext if encrypted, original input if plaintext, or None on failure
        """
        return await asyncio.to_thread(self.decrypt_secret_or_plaintext, bundle_json)

    def _decrypt_bundle(self, bundle_json: str) -> str:
        """Internal method to decrypt an already-validated encrypted bundle.

        Args:
            bundle_json: Validated encrypted bundle (with or without v2: prefix)

        Returns:
            str: Decrypted plaintext

        Raises:
            ValueError: If bundle is corrupted or decryption fails
        """
        # Strip v2: prefix if present
        json_str = bundle_json
        if json_str.startswith(self.FORMAT_MARKER):
            json_str = json_str[len(self.FORMAT_MARKER) :]

        try:
            obj = orjson.loads(json_str)

            # Validate required keys
            required = {"salt", "token", "t", "m", "p"}
            if not required.issubset(set(obj.keys())):
                raise ValueError(f"Encrypted bundle missing required keys. Found: {set(obj.keys())}, Need: {required}")

            # Derive key and decrypt
            salt = base64.b64decode(obj["salt"])
            key = self.derive_key_argon2id(self.encryption_secret, salt, time_cost=obj["t"], memory_cost=obj["m"], parallelism=obj["p"])
            fernet = Fernet(key)
            decrypted = fernet.decrypt(obj["token"].encode())
            return decrypted.decode()
        except (InvalidToken, binascii.Error) as e:
            raise ValueError(f"Decryption failed (corrupted or wrong key): {e}") from e
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Decryption failed: {e}") from e

    def is_encrypted(self, text: str) -> bool:
        """Detect whether text is encrypted (best-effort heuristic).

        Checks for:
        1. v2: prefix with valid JSON bundle (most reliable)
        2. Legacy Fernet format (base64 with version byte 0x80)
        3. Legacy argon2id JSON format (for backward compatibility)

        ⚠️ SECURITY WARNING - READ BEFORE USING:

        This uses heuristics and has limitations:
        - NOT suitable for security-critical code paths
        - May fail to detect edge-case encrypted formats
        - May falsely identify structured plaintext as encrypted
        - ONLY use for non-security purposes (caching, logging, display)

        ALWAYS validate encryption state at storage/trust boundaries using:
        - Database schema constraints (e.g., separate plaintext/encrypted columns)
        - Explicit markers in data structure
        - Cryptographic signatures/MACs
        - Hardware security modules

        Args:
            text: Text to check for encryption markers

        Returns:
            bool: True if text appears to be encrypted, False otherwise (safe default)

        Examples:
            >>> enc = EncryptionService(SecretStr("key"))
            >>> encrypted = enc.encrypt_secret("secret")
            >>> enc.is_encrypted(encrypted)
            True
            >>> enc.is_encrypted("plaintext")
            False
        """
        if not text:
            return False

        # Check for v2: prefix (most reliable)
        if text.startswith(self.FORMAT_MARKER):
            return self._is_valid_v2_bundle(text[len(self.FORMAT_MARKER) :])

        # Check for JSON bundle (legacy or without prefix)
        if text.startswith("{"):
            return self._is_valid_json_bundle(text)

        # Check for legacy Fernet binary format
        return self._is_valid_fernet_format(text)

    def _is_valid_v2_bundle(self, json_str: str) -> bool:
        """Validate v2: prefixed bundle.

        Strictly validates that:
        1. JSON parses successfully
        2. Has version: "v2"
        3. Contains all required keys

        Args:
            json_str: JSON string to validate (without v2: prefix)

        Returns:
            bool: True if valid v2 bundle, False otherwise
        """
        try:
            obj = orjson.loads(json_str)
            if not isinstance(obj, dict):
                return False

            # Must have version and all required keys
            if obj.get("version") != self.FORMAT_VERSION:
                return False

            required = {"salt", "token", "t", "m", "p"}
            return required.issubset(set(obj.keys()))
        except (orjson.JSONDecodeError, ValueError):
            # Invalid JSON means it's not a valid v2 bundle
            return False

    def _is_valid_json_bundle(self, json_str: str) -> bool:
        """Validate legacy JSON bundle (without v2: prefix).

        Args:
            json_str: JSON string to validate

        Returns:
            bool: True if valid legacy JSON bundle, False otherwise
        """
        try:
            obj = orjson.loads(json_str)
            if not isinstance(obj, dict):
                return False

            required = {"salt", "token", "t", "m", "p"}

            # Require either explicit v2 version or argon2id kdf
            has_version = obj.get("version") == self.FORMAT_VERSION
            has_kdf = obj.get("kdf") == "argon2id"

            if not (has_version or has_kdf):
                return False

            # Validate all required keys present
            return required.issubset(set(obj.keys()))
        except (orjson.JSONDecodeError, ValueError):
            return False

    def _is_valid_fernet_format(self, text: str) -> bool:
        """Validate legacy Fernet binary format (base64 with version byte 0x80).

        Args:
            text: Text to validate

        Returns:
            bool: True if valid Fernet binary format, False otherwise
        """
        try:
            decoded = base64.urlsafe_b64decode(text.encode())
            # Fernet tokens are >= 57 bytes and start with version byte 0x80
            return len(decoded) >= 57 and decoded[0:1] == b"\x80"
        except Exception:
            return False


def get_encryption_service(encryption_secret: Union[SecretStr, str]) -> EncryptionService:
    """Factory function to create EncryptionService instance.

    Args:
        encryption_secret: Secret key for encryption (as SecretStr or string)

    Returns:
        EncryptionService: Configured encryption service instance
    """
    return EncryptionService(encryption_secret)
