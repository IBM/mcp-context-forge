# -*- coding: utf-8 -*-
"""Unit tests for EncryptionService."""

# Standard
import asyncio
from unittest.mock import patch

# Third-Party
import pytest
from pydantic import SecretStr

# First-Party
from mcpgateway.services.encryption_service import EncryptionService, get_encryption_service


# ---------- Construction ----------


def test_init_with_secret_str():
    """SecretStr is unwrapped correctly."""
    svc = EncryptionService(SecretStr("my-secret"))
    assert svc.encryption_secret == b"my-secret"


def test_init_with_plain_string():
    """Plain string is accepted for backwards compatibility."""
    svc = EncryptionService("my-secret")
    assert svc.encryption_secret == b"my-secret"


def test_init_custom_params():
    """Custom argon2 params are stored."""
    svc = EncryptionService("k", time_cost=2, memory_cost=1024, parallelism=2, hash_len=16, salt_len=8)
    assert svc.time_cost == 2
    assert svc.memory_cost == 1024
    assert svc.parallelism == 2
    assert svc.hash_len == 16
    assert svc.salt_len == 8


# ---------- Encrypt / Decrypt roundtrip ----------


def test_encrypt_decrypt_roundtrip():
    """Encrypt then decrypt returns original plaintext."""
    svc = EncryptionService("test-key", time_cost=1, memory_cost=1024, parallelism=1)
    encrypted = svc.encrypt_secret("hello world")
    assert isinstance(encrypted, str)
    decrypted = svc.decrypt_secret(encrypted)
    assert decrypted == "hello world"


def test_encrypt_produces_json():
    """Encrypted output is a JSON bundle with expected keys."""
    import orjson
    svc = EncryptionService("test-key", time_cost=1, memory_cost=1024, parallelism=1)
    encrypted = svc.encrypt_secret("secret")
    bundle = orjson.loads(encrypted)
    assert bundle["kdf"] == "argon2id"
    assert "salt" in bundle
    assert "token" in bundle
    assert bundle["t"] == 1
    assert bundle["m"] == 1024
    assert bundle["p"] == 1


def test_decrypt_invalid_json_returns_none():
    """Invalid JSON returns None."""
    svc = EncryptionService("test-key")
    result = svc.decrypt_secret("not-json")
    assert result is None


def test_decrypt_wrong_key_returns_none():
    """Decrypting with wrong key returns None."""
    svc1 = EncryptionService("key-one", time_cost=1, memory_cost=1024, parallelism=1)
    svc2 = EncryptionService("key-two", time_cost=1, memory_cost=1024, parallelism=1)
    encrypted = svc1.encrypt_secret("secret")
    result = svc2.decrypt_secret(encrypted)
    assert result is None


# ---------- Async methods ----------


@pytest.mark.asyncio
async def test_encrypt_secret_async():
    """Async encrypt works."""
    svc = EncryptionService("test-key", time_cost=1, memory_cost=1024, parallelism=1)
    encrypted = await svc.encrypt_secret_async("async-secret")
    assert isinstance(encrypted, str)


@pytest.mark.asyncio
async def test_decrypt_secret_async():
    """Async decrypt works."""
    svc = EncryptionService("test-key", time_cost=1, memory_cost=1024, parallelism=1)
    encrypted = svc.encrypt_secret("async-secret")
    decrypted = await svc.decrypt_secret_async(encrypted)
    assert decrypted == "async-secret"


@pytest.mark.asyncio
async def test_decrypt_secret_async_invalid():
    """Async decrypt returns None for bad input."""
    svc = EncryptionService("test-key")
    result = await svc.decrypt_secret_async("garbage")
    assert result is None


# ---------- is_encrypted ----------


def test_is_encrypted_argon2id_format():
    """Argon2id JSON format is detected."""
    svc = EncryptionService("test-key", time_cost=1, memory_cost=1024, parallelism=1)
    encrypted = svc.encrypt_secret("test")
    assert svc.is_encrypted(encrypted) is True


def test_is_encrypted_empty():
    """Empty string is not encrypted."""
    svc = EncryptionService("k")
    assert svc.is_encrypted("") is False


def test_is_encrypted_plain_text():
    """Plain text is not detected as encrypted."""
    svc = EncryptionService("k")
    assert svc.is_encrypted("hello world") is False


def test_is_encrypted_invalid_json():
    """Invalid JSON starting with { is not detected as encrypted."""
    svc = EncryptionService("k")
    assert svc.is_encrypted("{not valid json") is False


def test_is_encrypted_json_without_kdf():
    """JSON without kdf field is not detected as encrypted."""
    svc = EncryptionService("k")
    assert svc.is_encrypted('{"key": "value"}') is False


def test_is_encrypted_legacy_base64():
    """Legacy base64-encoded Fernet format is detected as encrypted."""
    import base64
    import os
    svc = EncryptionService("k")
    # Create a base64 string of >= 32 bytes
    raw = os.urandom(48)
    legacy = base64.urlsafe_b64encode(raw).decode()
    assert svc.is_encrypted(legacy) is True


def test_is_encrypted_short_base64():
    """Short base64 string is not detected as encrypted (< 32 bytes decoded)."""
    import base64
    svc = EncryptionService("k")
    raw = b"short"
    short = base64.urlsafe_b64encode(raw).decode()
    assert svc.is_encrypted(short) is False


def test_is_encrypted_invalid_base64():
    """Non-base64 text returns False."""
    svc = EncryptionService("k")
    assert svc.is_encrypted("hello!@#$%^&*() world") is False


# ---------- derive_key_argon2id ----------


def test_derive_key_produces_url_safe_base64():
    """Derived key is valid URL-safe base64."""
    import base64
    svc = EncryptionService("test-key", time_cost=1, memory_cost=1024, parallelism=1)
    key = svc.derive_key_argon2id(b"passphrase", b"0123456789abcdef", 1, 1024, 1)
    # Should be valid URL-safe base64
    decoded = base64.urlsafe_b64decode(key)
    assert len(decoded) == 32  # hash_len=32


# ---------- get_encryption_service ----------


def test_get_encryption_service_with_secret_str():
    """Factory function with SecretStr."""
    svc = get_encryption_service(SecretStr("my-key"))
    assert isinstance(svc, EncryptionService)


def test_get_encryption_service_with_string():
    """Factory function with plain string."""
    svc = get_encryption_service("my-key")
    assert isinstance(svc, EncryptionService)


# ---------- Error handling ----------


def test_encrypt_secret_error_propagates():
    """Encryption error is propagated."""
    svc = EncryptionService("k")
    with patch.object(svc, "derive_key_argon2id", side_effect=RuntimeError("derive fail")):
        with pytest.raises(RuntimeError, match="derive fail"):
            svc.encrypt_secret("test")
