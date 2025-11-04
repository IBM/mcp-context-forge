#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/generate_keys.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhav Kandukuri

Utility to generate Ed25519 key pairs for JWT or signing use.
Safely writes PEM-formatted private and public keys to disk.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

# Logging setup
import logging

logger = logging.getLogger(__name__)

def generate_ed25519_keypair(private_path: Path, public_path: Path) -> None:
    """Generate an Ed25519 key pair and save to PEM files."""
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
    """Generate an Ed25519 private key and return PEM string."""
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
    """Derive the public key PEM from a given Ed25519 private key PEM string."""
    private_key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return public_pem.decode()


def main() -> None:
    private_pem = generate_ed25519_private_key()
    print("Ed25519 private key generated successfully.\n")
    print(private_pem)


if __name__ == "__main__":
    main()
