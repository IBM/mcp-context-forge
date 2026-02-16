# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_encryption_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for Encryption Service.
"""

# Standard
from unittest.mock import patch

# Third-Party
from pydantic import SecretStr
import pytest

# First-Party
from mcpgateway.services.encryption_service import EncryptionService

class TestEncryptionService:
    """Test cases for EncryptionService class."""

    def test_init(self):
        """Test EncryptionService initialization."""
        encryption = EncryptionService(SecretStr("test_secret_key"))
        assert encryption.encryption_secret == b"test_secret_key"

    def test_encrypt_secret_success(self):
        """Test successful secret encryption."""
        encryption = EncryptionService(SecretStr("test_secret_key"))
        plaintext = "my_secret_token_123"

        encrypted = encryption.encrypt_secret(plaintext)

        # Should be a v2: prefixed JSON string
        assert isinstance(encrypted, str)
        assert encrypted.startswith("v2:{")
        assert len(encrypted) > len(plaintext)  # Encrypted data should be longer

        # Should be able to decrypt back to original
        decrypted = encryption.decrypt_secret(encrypted)
        assert decrypted == plaintext

    def test_encrypt_secret_already_encrypted_raises(self):
        """Test that encrypt_secret raises when given already-encrypted data."""
        encryption = EncryptionService(SecretStr("test_key"))
        plaintext = "secret"

        # Encrypt once
        encrypted = encryption.encrypt_secret(plaintext)

        # Trying to encrypt again should raise AlreadyEncryptedError
        from mcpgateway.services.encryption_service import AlreadyEncryptedError

        with pytest.raises(AlreadyEncryptedError):
            encryption.encrypt_secret(encrypted)

    def test_encrypt_secret_different_keys_different_output(self):
        """Test that different keys produce different encrypted output."""
        encryption1 = EncryptionService(SecretStr("key1"))
        encryption2 = EncryptionService(SecretStr("key2"))
        plaintext = "same_secret"

        encrypted1 = encryption1.encrypt_secret(plaintext)
        encrypted2 = encryption2.encrypt_secret(plaintext)

        # Different keys should produce different encrypted output
        assert encrypted1 != encrypted2

    def test_encrypt_secret_same_key_different_output(self):
        """Test that same key produces different encrypted output due to nonce."""
        encryption = EncryptionService(SecretStr("test_key"))
        plaintext = "same_secret"

        encrypted1 = encryption.encrypt_secret(plaintext)
        encrypted2 = encryption.encrypt_secret(plaintext)

        # Same plaintext with same key should produce different output (due to nonce)
        assert encrypted1 != encrypted2

        # But both should decrypt to the same plaintext
        assert encryption.decrypt_secret(encrypted1) == plaintext
        assert encryption.decrypt_secret(encrypted2) == plaintext

    def test_encrypt_secret_empty_string(self):
        """Test encrypting empty string."""
        encryption = EncryptionService(SecretStr("test_key"))

        encrypted = encryption.encrypt_secret("")
        decrypted = encryption.decrypt_secret(encrypted)

        assert decrypted == ""

    def test_encrypt_secret_unicode_characters(self):
        """Test encrypting string with unicode characters."""
        encryption = EncryptionService(SecretStr("test_key"))
        plaintext = "🔐 secret with émojis and spéciàl chars ñ"

        encrypted = encryption.encrypt_secret(plaintext)
        decrypted = encryption.decrypt_secret(encrypted)

        assert decrypted == plaintext

    def test_encrypt_secret_exception_handling(self):
        """Test exception handling in encrypt_secret."""
        encryption = EncryptionService(SecretStr("test_key"))

        with patch.object(encryption, "derive_key_argon2id", side_effect=Exception("Encryption failed")):
            with pytest.raises(Exception, match="Encryption failed"):
                encryption.encrypt_secret("test")

    def test_decrypt_secret_success(self):
        """Test successful secret decryption."""
        encryption = EncryptionService(SecretStr("test_secret_key"))
        plaintext = "original_secret"

        # First encrypt
        encrypted = encryption.encrypt_secret(plaintext)

        # Then decrypt
        decrypted = encryption.decrypt_secret(encrypted)

        assert decrypted == plaintext

    def test_decrypt_secret_invalid_data(self):
        """Test decryption with invalid encrypted data raises NotEncryptedError."""
        encryption = EncryptionService(SecretStr("test_key"))
        from mcpgateway.services.encryption_service import NotEncryptedError

        # Invalid data is plaintext, so should raise NotEncryptedError
        with pytest.raises(NotEncryptedError):
            encryption.decrypt_secret("invalid_encrypted_data")

    def test_decrypt_secret_wrong_key(self):
        """Test decryption with wrong key raises ValueError."""
        encryption1 = EncryptionService(SecretStr("key1"))
        encryption2 = EncryptionService(SecretStr("key2"))

        # Encrypt with one key
        encrypted = encryption1.encrypt_secret("secret")

        # Try to decrypt with different key - should raise ValueError
        with pytest.raises(ValueError):
            encryption2.decrypt_secret(encrypted)

    def test_decrypt_secret_corrupted_data(self):
        """Test decryption with corrupted data raises error in strict mode."""
        encryption = EncryptionService(SecretStr("test_key"))

        # Create valid encrypted data then corrupt it
        encrypted = encryption.encrypt_secret("test")
        corrupted = encrypted[:-5] + "XXXXX"  # Corrupt the end

        # Should raise an error on corrupted data
        from mcpgateway.services.encryption_service import NotEncryptedError

        with pytest.raises((ValueError, NotEncryptedError)):
            encryption.decrypt_secret(corrupted)

    def test_decrypt_secret_malformed_base64(self):
        """Test decryption with malformed base64 raises NotEncryptedError."""
        encryption = EncryptionService(SecretStr("test_key"))
        from mcpgateway.services.encryption_service import NotEncryptedError

        # Malformed base64 is not detected as encrypted
        with pytest.raises(NotEncryptedError):
            encryption.decrypt_secret("not_valid_base64!@#")

    def test_decrypt_secret_empty_string(self):
        """Test decryption with empty string raises NotEncryptedError."""
        encryption = EncryptionService(SecretStr("test_key"))
        from mcpgateway.services.encryption_service import NotEncryptedError

        # Empty string is not encrypted
        with pytest.raises(NotEncryptedError):
            encryption.decrypt_secret("")

    def test_is_encrypted_valid_encrypted_data(self):
        """Test is_encrypted with valid encrypted data."""
        encryption = EncryptionService(SecretStr("test_key"))

        encrypted = encryption.encrypt_secret("test_data")

        assert encryption.is_encrypted(encrypted) is True

    def test_is_encrypted_plain_text(self):
        """Test is_encrypted with plain text."""
        encryption = EncryptionService(SecretStr("test_key"))

        assert encryption.is_encrypted("plain_text_secret") is False
        assert encryption.is_encrypted("another_plain_string") is False

    def test_is_encrypted_short_data(self):
        """Test is_encrypted with short data."""
        encryption = EncryptionService(SecretStr("test_key"))

        # Fernet encrypted data should be at least 32 bytes
        short_data = "dGVzdA=="  # "test" in base64 (only 4 bytes when decoded)

        assert encryption.is_encrypted(short_data) is False

    def test_is_encrypted_valid_base64_but_not_encrypted(self):
        """Test is_encrypted correctly rejects valid base64 without encryption markers."""
        encryption = EncryptionService(SecretStr("test_key"))

        # Create base64 data that's long enough but doesn't match encrypted format
        import base64

        fake_data = b"a" * 40  # 40 bytes of 'a'
        base64_fake = base64.urlsafe_b64encode(fake_data).decode()

        # Should correctly identify this as NOT encrypted (no v2: prefix, not JSON, no version byte 0x80)
        assert encryption.is_encrypted(base64_fake) is False

        # Calling decrypt_secret should raise NotEncryptedError
        from mcpgateway.services.encryption_service import NotEncryptedError

        with pytest.raises(NotEncryptedError):
            encryption.decrypt_secret(base64_fake)

    def test_is_encrypted_invalid_base64(self):
        """Test is_encrypted with invalid base64."""
        encryption = EncryptionService(SecretStr("test_key"))

        assert encryption.is_encrypted("not_base64!@#$%") is False

    def test_is_encrypted_exception_handling(self):
        """Test exception handling in is_encrypted."""
        encryption = EncryptionService(SecretStr("test_key"))

        # Test with None (should handle gracefully)
        with patch("base64.urlsafe_b64decode", side_effect=Exception("Base64 error")):
            result = encryption.is_encrypted("any_string")
            assert result is False

    def test_get_encryption_service_function(self):
        """Test the get_encryption_service utility function."""
        # First-Party
        from mcpgateway.services.encryption_service import get_encryption_service

        encryption = get_encryption_service(SecretStr("test_secret"))

        assert isinstance(encryption, EncryptionService)
        assert encryption.encryption_secret == b"test_secret"

    def test_encryption_roundtrip_multiple_values(self):
        """Test encryption/decryption roundtrip with multiple values."""
        encryption = EncryptionService(SecretStr("test_key"))

        test_values = [
            "simple_token",
            "complex_token_with_special_chars_123!@#",
            "very_long_token_" * 100,  # Very long token
            "token_with_newlines\n\r\t",
            "token with spaces and symbols: !@#$%^&*()",
            "🔐🗝️🔑 tokens with emojis",
        ]

        for original in test_values:
            encrypted = encryption.encrypt_secret(original)
            decrypted = encryption.decrypt_secret(encrypted)

            assert decrypted == original, f"Failed for: {original}"
            assert encryption.is_encrypted(encrypted) is True

    def test_encryption_key_derivation_consistency(self):
        """Test that key derivation is consistent across instances."""
        # Create two instances with same key
        encryption1 = EncryptionService(SecretStr("same_key"))
        encryption2 = EncryptionService(SecretStr("same_key"))

        # Encrypt with first instance
        plaintext = "test_consistency"
        encrypted = encryption1.encrypt_secret(plaintext)

        # Decrypt with second instance
        decrypted = encryption2.decrypt_secret(encrypted)

        assert decrypted == plaintext

    def test_encryption_with_long_key(self):
        """Test encryption with very long key."""
        long_key = SecretStr("a" * 1000)  # Very long key
        encryption = EncryptionService(long_key)

        encrypted = encryption.encrypt_secret("test_data")
        decrypted = encryption.decrypt_secret(encrypted)

        assert decrypted == "test_data"

    def test_encryption_with_special_char_key(self):
        """Test encryption with key containing special characters."""
        special_key = SecretStr("key_with_special_chars!@#$%^&*()_+-={}[]|\\:;\"'<>?,./")
        encryption = EncryptionService(special_key)

        encrypted = encryption.encrypt_secret("test_data")
        decrypted = encryption.decrypt_secret(encrypted)

        assert decrypted == "test_data"
    # ============ Tests for new strict/idempotent API ============

    def test_decrypt_secret_or_plaintext_with_plaintext(self):
        """Test decrypt_secret_or_plaintext returns plaintext unchanged."""
        encryption = EncryptionService(SecretStr("test_key"))
        plaintext = "plain_secret_text"

        result = encryption.decrypt_secret_or_plaintext(plaintext)

        assert result == plaintext

    def test_decrypt_secret_or_plaintext_with_encrypted(self):
        """Test decrypt_secret_or_plaintext decrypts encrypted data."""
        encryption = EncryptionService(SecretStr("test_key"))
        plaintext = "secret_to_encrypt"

        encrypted = encryption.encrypt_secret(plaintext)
        result = encryption.decrypt_secret_or_plaintext(encrypted)

        assert result == plaintext

    def test_decrypt_secret_or_plaintext_with_corrupted_returns_none(self):
        """Test decrypt_secret_or_plaintext returns None for corrupted encrypted bundles.

        When a v2: bundle is corrupted (failed JSON parsing), it returns None
        since it's clearly meant to be encrypted data that failed.
        """
        encryption = EncryptionService(SecretStr("test_key"))

        encrypted = encryption.encrypt_secret("test")
        # Corrupt it so the JSON parsing fails
        corrupted = encrypted[:-10] + "XXXXXXXXXX"  # Corrupt the token field

        # Corrupted v2: bundle returns None (it was encrypted but failed)
        result = encryption.decrypt_secret_or_plaintext(corrupted)

        assert result is None

    def test_decrypt_secret_or_plaintext_with_wrong_key_returns_none(self):
        """Test decrypt_secret_or_plaintext returns None with wrong decryption key."""
        encryption1 = EncryptionService(SecretStr("key1"))
        encryption2 = EncryptionService(SecretStr("key2"))

        encrypted = encryption1.encrypt_secret("secret")
        result = encryption2.decrypt_secret_or_plaintext(encrypted)

        assert result is None

    def test_encrypt_secret_idempotent_requires_strict_mode(self):
        """Test that encrypt_secret is not idempotent (strict mode)."""
        encryption = EncryptionService(SecretStr("test_key"))
        plaintext = "secret"

        encrypted = encryption.encrypt_secret(plaintext)

        # Trying to encrypt again raises AlreadyEncryptedError
        from mcpgateway.services.encryption_service import AlreadyEncryptedError

        with pytest.raises(AlreadyEncryptedError):
            encryption.encrypt_secret(encrypted)

    # ============ Tests for real-world token formats ============

    def test_jwt_token_not_misidentified_as_encrypted(self):
        """Test that JWT tokens are not misidentified as encrypted."""
        encryption = EncryptionService(SecretStr("test_key"))

        # Sample JWT tokens in 100-500 char range
        jwt_tokens = [
            # Short JWT
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
            # Medium JWT with more claims
            "eyJhbGciOiJSUzI1NiIsImtpZCI6InRlc3Qta2V5In0.eyJpc3MiOiJodHRwczovL2V4YW1wbGUuY29tIiwic3ViIjoiMTIzNDU2Nzg5MCIsImF1ZCI6WyJodHRwczovL2FwaS5leGFtcGxlLmNvbSJdLCJpYXQiOjE1MTYyMzkwMjIsImV4cCI6MTUxNjI0MjYyMn0.signature",
        ]

        for jwt in jwt_tokens:
            # JWTs should NOT be detected as encrypted
            assert encryption.is_encrypted(jwt) is False, f"JWT incorrectly detected as encrypted: {jwt[:50]}..."

            # Trying to decrypt strict should raise NotEncryptedError
            from mcpgateway.services.encryption_service import NotEncryptedError

            with pytest.raises(NotEncryptedError):
                encryption.decrypt_secret(jwt)

            # Idempotent decrypt should return JWT unchanged
            result = encryption.decrypt_secret_or_plaintext(jwt)
            assert result == jwt

    def test_oauth2_bearer_token_not_misidentified(self):
        """Test that OAuth2 bearer tokens are not misidentified as encrypted."""
        encryption = EncryptionService(SecretStr("test_key"))

        # Sample OAuth2 tokens
        oauth_tokens = [
            "ya29.a0AfH6SMBx...",  # Google OAuth format
            "EAABsbCS1iHgBAOZCjJ7bW6vBZBjqN...",  # Facebook format
            "slApdkwl2pDFl9plpwD3lkGpwDfk=",  # Generic bearer token
        ]

        for token in oauth_tokens:
            assert encryption.is_encrypted(token) is False, f"OAuth token incorrectly detected as encrypted: {token[:50]}..."

    def test_api_key_formats_not_misidentified(self):
        """Test that API keys are not misidentified as encrypted."""
        import base64

        encryption = EncryptionService(SecretStr("test_key"))

        api_keys = [
            "sk-1234567890abcdefghijklmnopqrst",  # OpenAI format
            "ghp_1234567890abcdefghijklmnopqrst",  # GitHub format
            "AKIA1234567890ABCDEF",  # AWS format
            base64.urlsafe_b64encode(b"some_api_key_data" * 5).decode(),  # Base64 encoded key
        ]

        for key in api_keys:
            assert encryption.is_encrypted(key) is False, f"API key incorrectly detected as encrypted: {key[:50]}..."

    def test_plaintext_json_not_misidentified_as_encrypted(self):
        """Test that plaintext JSON with similar structure is not misidentified."""
        encryption = EncryptionService(SecretStr("test_key"))

        # Create JSON that looks like it could be encrypted but isn't
        import json

        fake_encrypted_json = json.dumps({
            "kdf": "argon2id",
            "other_field": "value",
            # Missing required fields: salt, token, t, m, p
        })

        # Should NOT be detected as encrypted (missing required fields)
        assert encryption.is_encrypted(fake_encrypted_json) is False

    def test_corrupted_encrypted_token_raises_on_strict_decrypt(self):
        """Test that corrupted encrypted tokens raise an error in strict mode."""
        from mcpgateway.services.encryption_service import NotEncryptedError

        encryption = EncryptionService(SecretStr("test_key"))

        encrypted = encryption.encrypt_secret("secret_data")

        # Various corruption scenarios
        corrupted_variants = [
            encrypted[:-5] + "XXXXX",  # Corrupt end (but still looks like v2: JSON)
            encrypted[:10] + "XXXXX" + encrypted[15:],  # Corrupt middle (breaks JSON)
            "v2:{invalid json here}",  # Malformed v2: bundle
        ]

        for corrupted in corrupted_variants:
            # Corrupted data should either:
            # 1. Raise ValueError if detected as encrypted but fails to decrypt
            # 2. Raise NotEncryptedError if not detected as encrypted (which is also an error)
            with pytest.raises((ValueError, NotEncryptedError)):
                encryption.decrypt_secret(corrupted)

    def test_truncated_encrypted_token_raises_on_strict_decrypt(self):
        """Test that truncated encrypted tokens raise ValueError in strict mode."""
        encryption = EncryptionService(SecretStr("test_key"))

        encrypted = encryption.encrypt_secret("secret_data")

        # Truncate at various points
        truncated_variants = [
            encrypted[:len(encrypted) // 2],  # Truncate half
            encrypted[:-10],  # Truncate end
            "v2:{",  # Barely start of JSON
        ]

        for truncated in truncated_variants:
            with pytest.raises((ValueError, Exception)):
                encryption.decrypt_secret(truncated)

    def test_v2_format_marker_consistency(self):
        """Test that all encrypted data includes v2: format marker."""
        encryption = EncryptionService(SecretStr("test_key"))

        test_data = [
            "simple_secret",
            "very_long_secret_" * 100,
            "secret_with_special_chars_!@#$%^&*()",
        ]

        for plaintext in test_data:
            encrypted = encryption.encrypt_secret(plaintext)
            assert encrypted.startswith("v2:{"), f"Encrypted data missing v2: prefix: {encrypted[:50]}..."

            # Should be detectable and decryptable
            assert encryption.is_encrypted(encrypted) is True
            decrypted = encryption.decrypt_secret(encrypted)
            assert decrypted == plaintext

    # ============ Tests for concurrent/async behavior ============

    @pytest.mark.asyncio
    async def test_concurrent_encrypt_same_data(self):
        """Test concurrent encryption of same plaintext produces different outputs."""
        encryption = EncryptionService(SecretStr("test_key"))
        plaintext = "concurrent_secret"

        # Fire concurrent encrypts
        import asyncio

        tasks = [encryption.encrypt_secret_async(plaintext) for _ in range(10)]
        results = await asyncio.gather(*tasks)

        # All should decrypt to same plaintext
        for encrypted in results:
            decrypted = encryption.decrypt_secret(encrypted)
            assert decrypted == plaintext

        # But results should be different (random nonce/salt)
        assert len(set(results)) == 10, "Concurrent encryptions should produce unique outputs due to random salt"

    @pytest.mark.asyncio
    async def test_concurrent_decrypt_mixed_async(self):
        """Test concurrent decryption of mixed plaintext and encrypted data."""
        encryption = EncryptionService(SecretStr("test_key"))

        plaintext1 = "plaintext_secret_1"
        encrypted1 = encryption.encrypt_secret("encrypted_secret_1")
        plaintext2 = "plaintext_secret_2"
        encrypted2 = encryption.encrypt_secret("encrypted_secret_2")

        # Mix plaintext and encrypted in concurrent calls
        import asyncio

        tasks = [
            encryption.decrypt_secret_or_plaintext_async(plaintext1),
            encryption.decrypt_secret_or_plaintext_async(encrypted1),
            encryption.decrypt_secret_or_plaintext_async(plaintext2),
            encryption.decrypt_secret_or_plaintext_async(encrypted2),
        ]
        results = await asyncio.gather(*tasks)

        # Should return correct values in order
        assert results[0] == plaintext1
        assert results[1] == "encrypted_secret_1"
        assert results[2] == plaintext2
        assert results[3] == "encrypted_secret_2"

    def test_encrypt_multiple_times_concurrent_same_key(self):
        """Test that encrypting same plaintext multiple times with same key produces different results."""
        encryption = EncryptionService(SecretStr("same_key"))
        plaintext = "same_plaintext"

        # Encrypt 5 times with same instance
        encrypted_results = [encryption.encrypt_secret(plaintext) for _ in range(5)]

        # All should be unique (due to random salt in each encryption)
        assert len(set(encrypted_results)) == 5, "Same plaintext should produce different ciphertexts (random salt)"

        # All should decrypt to same plaintext
        for encrypted in encrypted_results:
            assert encryption.decrypt_secret(encrypted) == plaintext

    # ============ Tests for missing coverage lines ============

    @pytest.mark.asyncio
    async def test_decrypt_secret_strict_async(self):
        """Test decrypt_secret_strict_async (covers line 279)."""
        encryption = EncryptionService(SecretStr("test_key"))
        plaintext = "test_secret"

        encrypted = encryption.encrypt_secret(plaintext)
        decrypted = await encryption.decrypt_secret_strict_async(encrypted)

        assert decrypted == plaintext

    @pytest.mark.asyncio
    async def test_decrypt_secret_strict_async_raises_on_plaintext(self):
        """Test decrypt_secret_strict_async raises NotEncryptedError on plaintext."""
        from mcpgateway.services.encryption_service import NotEncryptedError

        encryption = EncryptionService(SecretStr("test_key"))

        with pytest.raises(NotEncryptedError):
            await encryption.decrypt_secret_strict_async("plaintext_data")

    def test_decrypt_bundle_missing_required_keys(self):
        """Test _decrypt_bundle with missing required keys (covers line 371)."""
        encryption = EncryptionService(SecretStr("test_key"))

        # Create a v2 bundle missing required keys
        import json
        incomplete_bundle = json.dumps({
            "version": "v2",
            "kdf": "argon2id",
            "salt": "dGVzdA==",
            # Missing: token, t, m, p
        })

        with pytest.raises(ValueError, match="missing required keys"):
            encryption._decrypt_bundle(f"v2:{incomplete_bundle}")

    def test_decrypt_bundle_corrupted_token(self):
        """Test _decrypt_bundle with corrupted token (covers lines 381-384)."""
        encryption = EncryptionService(SecretStr("test_key"))

        # Create a valid-looking bundle with corrupted token
        import json
        import base64
        corrupted_bundle = json.dumps({
            "version": "v2",
            "kdf": "argon2id",
            "salt": base64.b64encode(b"testsalt12345678").decode(),
            "token": "corrupted_invalid_fernet_token",
            "t": 1,
            "m": 1024,
            "p": 1,
        })

        with pytest.raises(ValueError, match="Decryption failed"):
            encryption._decrypt_bundle(f"v2:{corrupted_bundle}")

    def test_is_valid_v2_bundle_non_dict(self):
        """Test _is_valid_v2_bundle with non-dict JSON (covers line 453)."""
        encryption = EncryptionService(SecretStr("test_key"))

        # JSON array instead of object
        result = encryption._is_valid_v2_bundle('["not", "a", "dict"]')
        assert result is False

    def test_is_valid_v2_bundle_wrong_version(self):
        """Test _is_valid_v2_bundle with wrong version (covers line 457)."""
        encryption = EncryptionService(SecretStr("test_key"))

        import json
        wrong_version = json.dumps({
            "version": "v1",  # Wrong version
            "kdf": "argon2id",
            "salt": "dGVzdA==",
            "token": "token",
            "t": 1,
            "m": 1024,
            "p": 1,
        })

        result = encryption._is_valid_v2_bundle(wrong_version)
        assert result is False

    def test_is_valid_json_bundle_non_dict(self):
        """Test _is_valid_json_bundle with non-dict JSON (covers line 477)."""
        encryption = EncryptionService(SecretStr("test_key"))

        # JSON string instead of object
        result = encryption._is_valid_json_bundle('"just a string"')
        assert result is False

    def test_is_valid_json_bundle_no_version_or_kdf(self):
        """Test _is_valid_json_bundle without version or kdf (covers line 486)."""
        encryption = EncryptionService(SecretStr("test_key"))

        import json
        no_markers = json.dumps({
            "salt": "dGVzdA==",
            "token": "token",
            "t": 1,
            "m": 1024,
            "p": 1,
            # Missing both version and kdf
        })

        result = encryption._is_valid_json_bundle(no_markers)
        assert result is False

    def test_is_valid_json_bundle_invalid_json(self):
        """Test _is_valid_json_bundle with invalid JSON (covers lines 490-491)."""
        encryption = EncryptionService(SecretStr("test_key"))

        result = encryption._is_valid_json_bundle("{invalid json here")
        assert result is False

    def test_decrypt_secret_or_plaintext_with_v2_corrupted_returns_none(self):
        """Test decrypt_secret_or_plaintext returns None for corrupted v2: bundle."""
        encryption = EncryptionService(SecretStr("test_key"))

        # Data with v2: prefix but invalid JSON
        corrupted_v2 = "v2:{this is not valid json}"
        result = encryption.decrypt_secret_or_plaintext(corrupted_v2)

        # Should return None since it has v2: prefix but failed validation
        assert result is None

    def test_legacy_json_bundle_without_v2_prefix(self):
        """Test that legacy JSON bundles (without v2: prefix) are still supported."""
        encryption = EncryptionService(SecretStr("test_key"))
        plaintext = "legacy_secret"

        # Encrypt to get a v2 bundle
        encrypted = encryption.encrypt_secret(plaintext)

        # Remove the v2: prefix to simulate legacy format
        legacy_bundle = encrypted[3:]  # Remove "v2:"

        # Should still be detected as encrypted
        assert encryption.is_encrypted(legacy_bundle) is True

        # Should still decrypt correctly
        decrypted = encryption.decrypt_secret(legacy_bundle)
        assert decrypted == plaintext
