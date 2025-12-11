# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/ssl_key_manager.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan

SSL key management utilities for handling passphrase-protected keys.

This module provides utilities for managing SSL private keys, including support
for passphrase-protected keys. It handles decryption and secure temporary file
management for use with Gunicorn and other servers that don't natively support
passphrase-protected keys.
"""

# Standard
import atexit
import logging
import os
from pathlib import Path
import tempfile
from typing import Optional

# Third-Party
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_private_key

logger = logging.getLogger(__name__)


class SSLKeyManager:
    """Manages SSL private keys, including passphrase-protected keys.

    This class handles the decryption of passphrase-protected private keys
    and creates temporary unencrypted key files for use with servers that
    don't support passphrase-protected keys directly (like Gunicorn).

    The temporary files are created with secure permissions (0o600) and are
    automatically cleaned up on process exit.

    Examples:
        >>> manager = SSLKeyManager()
        >>> key_path = manager.prepare_key_file("certs/key.pem")  # doctest: +SKIP
        >>> # Use key_path with Gunicorn
        >>> manager.cleanup()  # doctest: +SKIP
    """

    def __init__(self):
        """Initialize the SSL key manager."""
        self._temp_key_file: Optional[Path] = None

    def prepare_key_file(
        self,
        key_file: str | Path,
        password: Optional[str] = None,
    ) -> str:
        """Prepare a key file for use with Gunicorn.

        If the key is passphrase-protected, decrypt it and write to a
        temporary file with secure permissions. Otherwise, return the
        original path.

        Args:
            key_file: Path to the private key file
            password: Optional passphrase for encrypted key

        Returns:
            Path to the usable key file (original or temporary)

        Raises:
            FileNotFoundError: If the key file doesn't exist
            ValueError: If decryption fails (wrong passphrase, invalid key, etc.)

        Examples:
            >>> manager = SSLKeyManager()
            >>> # Unencrypted key - returns original path
            >>> path = manager.prepare_key_file("certs/key.pem")  # doctest: +SKIP
            >>> # Encrypted key - returns temporary decrypted path
            >>> path = manager.prepare_key_file("certs/key-enc.pem", "secret")  # doctest: +SKIP
        """
        key_path = Path(key_file)

        if not key_path.exists():
            raise FileNotFoundError(f"Key file not found: {key_file}")

        # If no password, use the key as-is
        if not password:
            logger.info(f"Using unencrypted key file: {key_file}")
            return str(key_path)

        # Decrypt the key and write to temporary file
        logger.info("Decrypting passphrase-protected key...")

        try:
            # Read and decrypt the key
            with open(key_path, "rb") as f:
                key_data = f.read()

            private_key = load_pem_private_key(
                key_data,
                password=password.encode() if password else None,
            )

            # Serialize to unencrypted PEM
            unencrypted_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )

            # Write to temporary file with secure permissions
            fd, temp_path = tempfile.mkstemp(suffix=".pem", prefix="ssl_key_")
            self._temp_key_file = Path(temp_path)

            # Set restrictive permissions (owner read/write only)
            os.chmod(temp_path, 0o600)

            # Write the decrypted key
            with os.fdopen(fd, "wb") as f:
                f.write(unencrypted_pem)

            logger.info(f"Decrypted key written to temporary file: {temp_path}")

            # Register cleanup on exit
            atexit.register(self.cleanup)

            return temp_path

        except Exception as e:
            logger.error(f"Failed to decrypt key: {e}")
            self.cleanup()
            raise ValueError("Failed to decrypt private key. Check that the passphrase is correct.") from e

    def cleanup(self):
        """Remove temporary key file if it exists.

        This method is automatically called on process exit via atexit,
        but can also be called manually for explicit cleanup.
        """
        if self._temp_key_file and self._temp_key_file.exists():
            try:
                self._temp_key_file.unlink()
                logger.info(f"Cleaned up temporary key file: {self._temp_key_file}")
            except Exception as e:
                logger.warning(f"Failed to clean up temporary key file: {e}")
            finally:
                self._temp_key_file = None


# Global instance for convenience
_key_manager = SSLKeyManager()


def prepare_ssl_key(key_file: str, password: Optional[str] = None) -> str:
    """Prepare an SSL key file for use with Gunicorn.

    This is a convenience function that uses the global key manager instance.

    Args:
        key_file: Path to the private key file
        password: Optional passphrase for encrypted key

    Returns:
        Path to the usable key file (original or temporary)

    Raises:
        FileNotFoundError: If the key file doesn't exist
        ValueError: If decryption fails

    Examples:
        >>> from mcpgateway.utils.ssl_key_manager import prepare_ssl_key
        >>> key_path = prepare_ssl_key("certs/key.pem")  # doctest: +SKIP
        >>> key_path = prepare_ssl_key("certs/key-enc.pem", "secret")  # doctest: +SKIP
    """
    return _key_manager.prepare_key_file(key_file, password)
