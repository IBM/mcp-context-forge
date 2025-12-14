# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_ssl_key_manager.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan

Unit tests for SSL key manager utility.
"""

# Standard
import os
from pathlib import Path
import tempfile

# Third-Party
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest

# First-Party
from mcpgateway.utils.ssl_key_manager import SSLKeyManager, prepare_ssl_key


@pytest.fixture
def temp_cert_dir(tmp_path):
    """Create a temporary directory for test certificates."""
    cert_dir = tmp_path / "certs"
    cert_dir.mkdir()
    return cert_dir


@pytest.fixture
def unencrypted_key(temp_cert_dir):
    """Generate an unencrypted RSA private key for testing."""
    # Generate a test RSA key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Save as unencrypted PEM
    key_path = temp_cert_dir / "key.pem"
    with open(key_path, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    return key_path


@pytest.fixture
def encrypted_key(temp_cert_dir):
    """Generate a passphrase-protected RSA private key for testing."""
    # Generate a test RSA key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Save as encrypted PEM with passphrase "test123"
    key_path = temp_cert_dir / "key-encrypted.pem"
    with open(key_path, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.BestAvailableEncryption(b"test123"),
            )
        )

    return key_path, "test123"


class TestSSLKeyManager:
    """Test suite for SSLKeyManager class."""

    def test_prepare_key_file_unencrypted(self, unencrypted_key):
        """Test that unencrypted keys are returned as-is."""
        manager = SSLKeyManager()

        result = manager.prepare_key_file(str(unencrypted_key))

        # Should return the original path
        assert result == str(unencrypted_key)

        # No temporary file should be created
        assert manager._temp_key_file is None

    def test_prepare_key_file_encrypted(self, encrypted_key):
        """Test that encrypted keys are decrypted to temporary files."""
        key_path, passphrase = encrypted_key
        manager = SSLKeyManager()

        result = manager.prepare_key_file(str(key_path), passphrase)

        # Should return a different path (temporary file)
        assert result != str(key_path)

        # Temporary file should exist
        temp_path = Path(result)
        assert temp_path.exists()

        # Temporary file should have restrictive permissions (0o600)
        stat_info = os.stat(result)
        permissions = stat_info.st_mode & 0o777
        assert permissions == 0o600

        # Temporary file should be tracked
        assert manager._temp_key_file == temp_path

        # Verify the decrypted key is valid
        with open(result, "rb") as f:
            key_data = f.read()
            # Should be able to load without password
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            private_key = load_pem_private_key(key_data, password=None)
            assert private_key is not None

        # Cleanup
        manager.cleanup()
        assert not temp_path.exists()

    def test_prepare_key_file_wrong_passphrase(self, encrypted_key):
        """Test that wrong passphrase raises ValueError."""
        key_path, _ = encrypted_key
        manager = SSLKeyManager()

        with pytest.raises(ValueError, match="Failed to decrypt private key"):
            manager.prepare_key_file(str(key_path), "wrong_password")

        # Ensure cleanup was called
        assert manager._temp_key_file is None

    def test_prepare_key_file_missing_file(self, temp_cert_dir):
        """Test that missing key file raises FileNotFoundError."""
        manager = SSLKeyManager()
        missing_path = temp_cert_dir / "nonexistent.pem"

        with pytest.raises(FileNotFoundError, match="Key file not found"):
            manager.prepare_key_file(str(missing_path))

    def test_cleanup_removes_temp_file(self, encrypted_key):
        """Test that cleanup removes temporary files."""
        key_path, passphrase = encrypted_key
        manager = SSLKeyManager()

        # Create temporary file
        temp_path = manager.prepare_key_file(str(key_path), passphrase)
        assert Path(temp_path).exists()

        # Cleanup should remove it
        manager.cleanup()
        assert not Path(temp_path).exists()
        assert manager._temp_key_file is None

    def test_cleanup_idempotent(self):
        """Test that cleanup can be called multiple times safely."""
        manager = SSLKeyManager()

        # Should not raise even if no temp file exists
        manager.cleanup()
        manager.cleanup()

    def test_prepare_ssl_key_convenience_function(self, unencrypted_key):
        """Test the convenience function prepare_ssl_key."""
        result = prepare_ssl_key(str(unencrypted_key))

        # Should work the same as the manager method
        assert result == str(unencrypted_key)

    def test_prepare_ssl_key_with_passphrase(self, encrypted_key):
        """Test convenience function with passphrase."""
        key_path, passphrase = encrypted_key

        result = prepare_ssl_key(str(key_path), passphrase)

        # Should return a temporary file path
        assert result != str(key_path)
        assert Path(result).exists()

        # Verify it's a valid unencrypted key
        with open(result, "rb") as f:
            key_data = f.read()
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            private_key = load_pem_private_key(key_data, password=None)
            assert private_key is not None


class TestSSLKeyManagerIntegration:
    """Integration tests for SSL key manager."""

    def test_atexit_cleanup(self, encrypted_key):
        """Test that atexit handler is registered for cleanup."""
        import atexit

        key_path, passphrase = encrypted_key
        manager = SSLKeyManager()

        # Get initial atexit handlers count
        initial_handlers = len(atexit._exithandlers) if hasattr(atexit, '_exithandlers') else 0

        # Prepare key (should register cleanup)
        temp_path = manager.prepare_key_file(str(key_path), passphrase)

        # Verify atexit handler was registered
        # Note: This is implementation-dependent and may vary by Python version
        if hasattr(atexit, '_exithandlers'):
            assert len(atexit._exithandlers) > initial_handlers

        # Manual cleanup for test
        manager.cleanup()

    def test_multiple_keys(self, temp_cert_dir):
        """Test handling multiple keys (should only track the last one)."""
        # Generate two encrypted keys
        key1 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        key1_path = temp_cert_dir / "key1.pem"
        key2_path = temp_cert_dir / "key2.pem"

        for key, path in [(key1, key1_path), (key2, key2_path)]:
            with open(path, "wb") as f:
                f.write(
                    key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.TraditionalOpenSSL,
                        encryption_algorithm=serialization.BestAvailableEncryption(b"test"),
                    )
                )

        manager = SSLKeyManager()

        # Prepare first key
        temp1 = manager.prepare_key_file(str(key1_path), "test")
        temp1_path = Path(temp1)
        assert temp1_path.exists()

        # Prepare second key (should replace the first)
        temp2 = manager.prepare_key_file(str(key2_path), "test")
        temp2_path = Path(temp2)
        assert temp2_path.exists()

        # Only the second temp file should be tracked
        assert manager._temp_key_file == temp2_path

        # Cleanup should only remove the second file
        manager.cleanup()
        assert not temp2_path.exists()
