#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/hash_password.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Generate Argon2id password hashes for emergency admin recovery operations.
"""

# Standard
import argparse
import asyncio
import getpass
import sys

# First-Party
from mcpgateway.services.argon2_service import Argon2PasswordService


async def _generate_hash(password: str) -> str:
    """Generate an Argon2id hash for a plaintext password.

    Args:
        password: Plaintext password.

    Returns:
        str: Argon2id encoded hash.
    """
    service = Argon2PasswordService()
    return await service.hash_password_async(password)


def main() -> int:
    """Run CLI entrypoint for generating password hashes.

    Returns:
        int: Process exit code (`0` success, non-zero on validation failure).
    """
    parser = argparse.ArgumentParser(description="Generate an Argon2id password hash for ContextForge users.")
    parser.add_argument("--password", help="Password value. If omitted, a secure prompt is used.")
    args = parser.parse_args()

    password = args.password
    if not password:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match.", file=sys.stderr)
            return 1

    if not password:
        print("Password cannot be empty.", file=sys.stderr)
        return 1

    password_hash = asyncio.run(_generate_hash(password))
    print(password_hash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
