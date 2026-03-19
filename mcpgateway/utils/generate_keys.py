#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/generate_keys.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhav Kandukuri

Utility to generate Ed25519 key pairs for JWT or signing use.
Safely writes PEM-formatted private and public keys to disk.
"""

# Future
from __future__ import annotations

# Standard
# Logging setup
import logging
from pathlib import Path

# Third-Party
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

logger = logging.getLogger(__name__)


def generate_ed25519_keypair(private_path: Path, public_path: Path) -> None:
    """Generate an Ed25519 key pair and save to PEM files.

    Args:
        private_path: Path to save the private key PEM file.
        public_path: Path to save the public key PEM file.

    Examples:
        >>> import io
        >>> import tempfile
        >>> from contextlib import redirect_stdout
        >>> from pathlib import Path
        >>> from mcpgateway.utils.generate_keys import generate_ed25519_keypair
        >>> with tempfile.TemporaryDirectory() as d:
        ...     priv = Path(d) / "private.pem"
        ...     pub = Path(d) / "public.pem"
        ...     buf = io.StringIO()
        ...     with redirect_stdout(buf):
        ...         generate_ed25519_keypair(priv, pub)
        ...     (
        ...         priv.exists(),
        ...         pub.exists(),
        ...         "Ed25519 key pair generated" in buf.getvalue(),
        ...         priv.read_text(encoding="utf-8").startswith("-----BEGIN PRIVATE KEY-----"),
        ...         pub.read_text(encoding="utf-8").startswith("-----BEGIN PUBLIC KEY-----"),
        ...     )
        (True, True, True, True, True)
    """
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_path.write_bytes(private_bytes)
    public_path.write_bytes(public_bytes)

    print(f"✅ Ed25519 key pair generated:\n  Private: {private_path}\n  Public:  {public_path}")


# ---------------------------------------------------------------------------
# Simplified generator: return private key PEM only
# ---------------------------------------------------------------------------


def generate_ed25519_private_key() -> str:
    """Generate an Ed25519 private key and return PEM string.

    Returns:
        str: PEM-formatted Ed25519 private key.

    Examples:
        >>> from mcpgateway.utils.generate_keys import generate_ed25519_private_key
        >>> pem = generate_ed25519_private_key()
        >>> pem.startswith("-----BEGIN PRIVATE KEY-----")
        True
        >>> pem.strip().endswith("-----END PRIVATE KEY-----")
        True
    """
    private_key = ed25519.Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return private_pem


# ---------------------------------------------------------------------------
# Helper: derive public key from private PEM
# ---------------------------------------------------------------------------


def derive_public_key_from_private(private_pem: str) -> str:
    """Derive the public key PEM from a given Ed25519 private key PEM string.

    Args:
        private_pem: PEM-formatted Ed25519 private key string.

    Returns:
        str: PEM-formatted Ed25519 public key.

    Raises:
        RuntimeError: If the public key cannot be derived.

    Examples:
        >>> from mcpgateway.utils.generate_keys import derive_public_key_from_private, generate_ed25519_private_key
        >>> pub = derive_public_key_from_private(generate_ed25519_private_key())
        >>> pub.startswith("-----BEGIN PUBLIC KEY-----")
        True

        >>> derive_public_key_from_private("not a pem")
        Traceback (most recent call last):
        ...
        RuntimeError: Failed to derive public key from private PEM
    """
    try:
        private_key = serialization.load_pem_private_key(private_pem.encode(), password=None)
        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return public_pem.decode()
    except Exception as e:
        logger.error(f"Error deriving public key from private PEM: {e}")
        raise RuntimeError("Failed to derive public key from private PEM") from e


def main() -> None:
    """Command-line interface to generate Ed25519 private key PEM."""
    private_pem = generate_ed25519_private_key()
    print("Ed25519 private key generated successfully.\n")
    print(private_pem)


if __name__ == "__main__":
    main()
