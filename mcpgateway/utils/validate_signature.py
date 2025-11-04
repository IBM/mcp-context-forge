#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/validate_signature.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhav Kandukuri

Utility to validate Ed25519 signatures.
Given data, signature, and public key PEM, verifies authenticity.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from mcpgateway.config import get_settings

# Logging setup
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper: sign data using Ed25519 private key
# ---------------------------------------------------------------------------


def sign_data(data: bytes, private_key_pem: str) -> bytes:
    """Sign data using an Ed25519 private key.

    Args:
        data: Message bytes to sign.
        private_key_pem: PEM-formatted private key string.

    Returns:
        bytes: Signature bytes.
    """
    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    if not isinstance(private_key, ed25519.Ed25519PrivateKey):
        raise TypeError("Expected an Ed25519 private key")
    return private_key.sign(data)


# ---------------------------------------------------------------------------
# Validate Ed25519 signature
# ---------------------------------------------------------------------------

def validate_signature(data: bytes, signature: bytes, public_key_pem: str) -> bool:
    """Validate an Ed25519 signature.

    Args:
        data: Original message bytes.
        signature: Signature bytes to verify.
        public_key_pem: PEM-formatted public key string.

    Returns:
        bool: True if signature is valid, False otherwise.
    """
    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode())
        public_key.verify(signature, data)
        return True
    except Exception:
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
    print(settings)

    # private_key_pem = settings.ed25519_private_key
    # print(private_key_pem)
    # private_key_obj = serialization.load_pem_private_key(
    #     private_key_pem.encode(),
    #     password=None,
    # )
    # public_key = private_key_obj.public_key()

    # message = b"test message"
    # sig = private_key_obj.sign(message)

    # public_pem = public_key.public_bytes(
    #     encoding=serialization.Encoding.PEM,
    #     format=serialization.PublicFormat.SubjectPublicKeyInfo,
    # ).decode()

    # logger.info("Signature valid:", validate_signature(message, sig, public_pem))