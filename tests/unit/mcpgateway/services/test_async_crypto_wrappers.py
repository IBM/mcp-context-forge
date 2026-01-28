# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_async_crypto_wrappers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test async wrappers for crypto operations (Argon2 and Fernet).

These tests verify that the async wrappers correctly delegate to their
sync counterparts via asyncio.to_thread, ensuring non-blocking crypto
operations in async contexts.
"""

# Third-Party
import pytest
from pydantic import SecretStr


class TestArgon2AsyncWrappers:
    """Test async wrappers for Argon2 password hashing."""

    @pytest.mark.asyncio
    async def test_hash_password_async_returns_valid_hash(self):
        """Test that hash_password_async returns a valid Argon2id hash."""
        # First-Party
        from mcpgateway.services.argon2_service import Argon2PasswordService

        # Use light params for testing
        service = Argon2PasswordService(time_cost=1, memory_cost=1024)
        password = "test_password_123"

        hash_value = await service.hash_password_async(password)

        assert hash_value.startswith("$argon2id$")
        assert len(hash_value) > 50

    @pytest.mark.asyncio
    async def test_hash_password_async_matches_sync(self):
        """Test that hash_password_async produces verifiable hashes like sync version."""
        # First-Party
        from mcpgateway.services.argon2_service import Argon2PasswordService

        service = Argon2PasswordService(time_cost=1, memory_cost=1024)
        password = "test_password_123"

        # Hash with async
        async_hash = await service.hash_password_async(password)

        # Verify with sync (proves the hash is valid)
        assert service.verify_password(password, async_hash) is True
        assert service.verify_password("wrong_password", async_hash) is False

    @pytest.mark.asyncio
    async def test_verify_password_async_correct_password(self):
        """Test that verify_password_async returns True for correct password."""
        # First-Party
        from mcpgateway.services.argon2_service import Argon2PasswordService

        service = Argon2PasswordService(time_cost=1, memory_cost=1024)
        password = "correct_password"
        hash_value = service.hash_password(password)

        result = await service.verify_password_async(password, hash_value)

        assert result is True

    @pytest.mark.asyncio
    async def test_verify_password_async_wrong_password(self):
        """Test that verify_password_async returns False for wrong password."""
        # First-Party
        from mcpgateway.services.argon2_service import Argon2PasswordService

        service = Argon2PasswordService(time_cost=1, memory_cost=1024)
        password = "correct_password"
        hash_value = service.hash_password(password)

        result = await service.verify_password_async("wrong_password", hash_value)

        assert result is False

    @pytest.mark.asyncio
    async def test_verify_password_async_empty_inputs(self):
        """Test that verify_password_async handles empty inputs safely."""
        # First-Party
        from mcpgateway.services.argon2_service import Argon2PasswordService

        service = Argon2PasswordService(time_cost=1, memory_cost=1024)

        assert await service.verify_password_async("", "some_hash") is False
        assert await service.verify_password_async("password", "") is False

    @pytest.mark.asyncio
    async def test_module_level_hash_password_async(self):
        """Test the module-level hash_password_async convenience function."""
        # First-Party
        from mcpgateway.services.argon2_service import hash_password_async, verify_password_async

        password = "module_level_test"

        hash_value = await hash_password_async(password)

        assert hash_value.startswith("$argon2id$")
        assert await verify_password_async(password, hash_value) is True

    @pytest.mark.asyncio
    async def test_async_hash_produces_unique_hashes(self):
        """Test that async hashing produces unique hashes (due to random salt)."""
        # First-Party
        from mcpgateway.services.argon2_service import Argon2PasswordService

        service = Argon2PasswordService(time_cost=1, memory_cost=1024)
        password = "same_password"

        hash1 = await service.hash_password_async(password)
        hash2 = await service.hash_password_async(password)

        # Same password should produce different hashes
        assert hash1 != hash2
        # But both should verify correctly
        assert await service.verify_password_async(password, hash1) is True
        assert await service.verify_password_async(password, hash2) is True


class TestEncryptionServiceAsyncWrappers:
    """Test async wrappers for Fernet encryption."""

    @pytest.mark.asyncio
    async def test_encrypt_secret_async_returns_encrypted(self):
        """Test that encrypt_secret_async returns an encrypted bundle."""
        # First-Party
        from mcpgateway.services.encryption_service import EncryptionService

        service = EncryptionService(SecretStr("test-encryption-key"), time_cost=1, memory_cost=1024)
        plaintext = "my_secret_value"

        encrypted = await service.encrypt_secret_async(plaintext)

        assert encrypted != plaintext
        assert service.is_encrypted(encrypted) is True

    @pytest.mark.asyncio
    async def test_decrypt_secret_async_returns_plaintext(self):
        """Test that decrypt_secret_async returns the original plaintext."""
        # First-Party
        from mcpgateway.services.encryption_service import EncryptionService

        service = EncryptionService(SecretStr("test-encryption-key"), time_cost=1, memory_cost=1024)
        plaintext = "my_secret_value"

        encrypted = service.encrypt_secret(plaintext)
        decrypted = await service.decrypt_secret_async(encrypted)

        assert decrypted == plaintext

    @pytest.mark.asyncio
    async def test_async_encrypt_decrypt_roundtrip(self):
        """Test full async encrypt/decrypt roundtrip."""
        # First-Party
        from mcpgateway.services.encryption_service import EncryptionService

        service = EncryptionService(SecretStr("roundtrip-key"), time_cost=1, memory_cost=1024)
        plaintext = "sensitive_data_123"

        encrypted = await service.encrypt_secret_async(plaintext)
        decrypted = await service.decrypt_secret_async(encrypted)

        assert decrypted == plaintext

    @pytest.mark.asyncio
    async def test_async_decrypt_handles_invalid_input(self):
        """Test that decrypt_secret_async handles invalid input gracefully."""
        # First-Party
        from mcpgateway.services.encryption_service import EncryptionService

        service = EncryptionService(SecretStr("test-key"), time_cost=1, memory_cost=1024)

        result = await service.decrypt_secret_async("not_valid_encrypted_data")

        assert result is None

    @pytest.mark.asyncio
    async def test_async_methods_match_sync_behavior(self):
        """Test that async methods produce results compatible with sync methods."""
        # First-Party
        from mcpgateway.services.encryption_service import EncryptionService

        service = EncryptionService(SecretStr("compatibility-key"), time_cost=1, memory_cost=1024)
        plaintext = "test_compatibility"

        # Encrypt with async, decrypt with sync
        async_encrypted = await service.encrypt_secret_async(plaintext)
        sync_decrypted = service.decrypt_secret(async_encrypted)
        assert sync_decrypted == plaintext

        # Encrypt with sync, decrypt with async
        sync_encrypted = service.encrypt_secret(plaintext)
        async_decrypted = await service.decrypt_secret_async(sync_encrypted)
        assert async_decrypted == plaintext

    @pytest.mark.asyncio
    async def test_async_encrypt_produces_unique_ciphertext(self):
        """Test that async encryption produces unique ciphertext (due to random salt)."""
        # First-Party
        from mcpgateway.services.encryption_service import EncryptionService

        service = EncryptionService(SecretStr("unique-key"), time_cost=1, memory_cost=1024)
        plaintext = "same_value"

        encrypted1 = await service.encrypt_secret_async(plaintext)
        encrypted2 = await service.encrypt_secret_async(plaintext)

        # Same plaintext should produce different ciphertext
        assert encrypted1 != encrypted2
        # But both should decrypt to original
        assert await service.decrypt_secret_async(encrypted1) == plaintext
        assert await service.decrypt_secret_async(encrypted2) == plaintext
