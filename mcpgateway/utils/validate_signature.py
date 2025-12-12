#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/validate_signature.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhav Kandukuri

Utility to validate Ed25519 signatures.
Given data, signature, and public key PEM, verifies authenticity.
"""

# Future
from __future__ import annotations

# Standard
# Logging setup
import logging

# Third-Party
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

# First-Party
from mcpgateway.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper: sign data using Ed25519 private key
# ---------------------------------------------------------------------------


def sign_data(data: bytes, private_key_pem: str) -> str:
    """Sign data using an Ed25519 private key.

    Args:
        data: Message bytes to sign.
        private_key_pem: PEM-formatted private key string.

    Returns:
        str: Hex-encoded signature.

    Raises:
        TypeError: If the provided key is not an Ed25519 private key.

    Examples:
        >>> from cryptography.hazmat.primitives.asymmetric import ed25519
        >>> from cryptography.hazmat.primitives import serialization
        >>>
        >>> # Generate a test key pair
        >>> private_key = ed25519.Ed25519PrivateKey.generate()
        >>> private_pem = private_key.private_bytes(
        ...     encoding=serialization.Encoding.PEM,
        ...     format=serialization.PrivateFormat.PKCS8,
        ...     encryption_algorithm=serialization.NoEncryption()
        ... ).decode()
        >>>
        >>> # Sign some data
        >>> data = b"test message"
        >>> signature = sign_data(data, private_pem)
        >>> isinstance(signature, str)
        True
        >>> len(signature) == 128  # 64 bytes = 128 hex chars
        True
    """
    try:
        private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
        if not isinstance(private_key, ed25519.Ed25519PrivateKey):
            raise TypeError("Expected an Ed25519 private key")
        return private_key.sign(data).hex()
    except Exception as e:
        logger.error(f"Error signing data: {e}")
        raise


# ---------------------------------------------------------------------------
# Validate Ed25519 signature
# ---------------------------------------------------------------------------


def validate_signature(data: bytes, signature: bytes | str, public_key_pem: str) -> bool:
    """Validate an Ed25519 signature.

    Args:
        data: Original message bytes.
        signature: Signature bytes or hex string to verify.
        public_key_pem: PEM-formatted public key string.

    Returns:
        bool: True if signature is valid, False otherwise.

    Examples:
        >>> from cryptography.hazmat.primitives.asymmetric import ed25519
        >>> from cryptography.hazmat.primitives import serialization
        >>>
        >>> # Generate a test key pair
        >>> private_key = ed25519.Ed25519PrivateKey.generate()
        >>> public_key = private_key.public_key()
        >>> public_pem = public_key.public_bytes(
        ...     encoding=serialization.Encoding.PEM,
        ...     format=serialization.PublicFormat.SubjectPublicKeyInfo
        ... ).decode()
        >>>
        >>> # Sign and verify
        >>> data = b"test message"
        >>> signature = private_key.sign(data)
        >>> validate_signature(data, signature, public_pem)
        True
        >>>
        >>> # Test with hex signature
        >>> hex_sig = signature.hex()
        >>> validate_signature(data, hex_sig, public_pem)
        True
        >>>
        >>> # Test invalid signature
        >>> validate_signature(b"wrong data", signature, public_pem)
        False
        >>>
        >>> # Test with string data (gets encoded)
        >>> validate_signature("test message", signature, public_pem)
        True
        >>>
        >>> # Test invalid hex signature format
        >>> validate_signature(data, "not-valid-hex", public_pem)
        False
    """
    if isinstance(data, str):
        data = data.encode()

    # Accept hex-encoded signatures
    if isinstance(signature, str):
        try:
            signature = bytes.fromhex(signature)
        except ValueError:
            logger.error("Invalid hex signature format.")
            return False

    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode())
        public_key.verify(signature, data)
        return True
    except Exception as e:
        logger.error(f"Signature validation failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Helper: re-sign data after verifying old signature
# ---------------------------------------------------------------------------


def resign_data(
    data: bytes,
    old_public_key_pem: str,
    old_signature: bytes | str,
    new_private_key_pem: str,
) -> bytes | None:
    """Re-sign data after verifying old signature.

    Args:
        data: Message bytes to verify and re-sign.
        old_public_key_pem: PEM-formatted old public key.
        old_signature: Existing signature bytes or empty string.
        new_private_key_pem: PEM-formatted new private key.

    Returns:
        bytes | None: New signature if re-signed, None if verification fails.

    Examples:
        >>> from cryptography.hazmat.primitives.asymmetric import ed25519
        >>> from cryptography.hazmat.primitives import serialization
        >>>
        >>> # Generate old and new key pairs
        >>> old_private = ed25519.Ed25519PrivateKey.generate()
        >>> old_public = old_private.public_key()
        >>> new_private = ed25519.Ed25519PrivateKey.generate()
        >>>
        >>> old_public_pem = old_public.public_bytes(
        ...     encoding=serialization.Encoding.PEM,
        ...     format=serialization.PublicFormat.SubjectPublicKeyInfo
        ... ).decode()
        >>> new_private_pem = new_private.private_bytes(
        ...     encoding=serialization.Encoding.PEM,
        ...     format=serialization.PrivateFormat.PKCS8,
        ...     encryption_algorithm=serialization.NoEncryption()
        ... ).decode()
        >>>
        >>> # Test first-time signing (no old signature)
        >>> data = b"test message"
        >>> new_sig = resign_data(data, old_public_pem, "", new_private_pem)
        >>> isinstance(new_sig, str)
        True
        >>>
        >>> # Test re-signing with valid old signature
        >>> old_sig = old_private.sign(data)
        >>> new_sig2 = resign_data(data, old_public_pem, old_sig, new_private_pem)
        >>> isinstance(new_sig2, str)
        True
        >>> new_sig2 != old_sig.hex()  # New signature should be different
        True
        >>>
        >>> # Test with invalid old signature (should return None)
        >>> bad_sig = b"invalid signature bytes"
        >>> result = resign_data(data, old_public_pem, bad_sig, new_private_pem)
        >>> result is None
        True
    """
    # Handle first-time signing (no old signature)
    if not old_signature:
        logger.info("No existing signature found — signing for the first time.")
        return sign_data(data, new_private_key_pem)

    if isinstance(old_signature, str):
        old_signature = old_signature.encode()

    # Verify old signature before re-signing
    if not validate_signature(data, old_signature, old_public_key_pem):
        logger.warning("Old signature invalid — not re-signing.")
        return None

    logger.info("Old signature valid — re-signing with new key.")
    return sign_data(data, new_private_key_pem)


if __name__ == "__main__":
    # Example usage
    settings = get_settings()

    private_key_pem = settings.ed25519_private_key
    private_key_obj = serialization.load_pem_private_key(
        private_key_pem.encode(),
        password=None,
    )
    public_key = private_key_obj.public_key()

    message = b"test message"
    sig = private_key_obj.sign(message)

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    logger.info("Signature valid:", validate_signature(message, sig, public_pem))
