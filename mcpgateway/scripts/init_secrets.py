# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/scripts/init_secrets.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Eleni Kechrioti

Secrets Initialization Script.
This script generates cryptographically secure secrets for JWT signing,
encryption, and administrative passwords. It supports writing to a file,
overwriting existing configurations, or piping to stdout.

Usage:
    python -m mcpgateway.scripts.init_secrets --output .env.secrets
    python -m mcpgateway.scripts.init_secrets --stdout --force
"""

# Standard
import argparse
import os
import secrets
import sys


def generate_token(nbytes: int) -> str:
    """
    Generate a cryptographically secure token.

    Args:
        nbytes (int): Number of bytes for the token generation.

    Returns:
        str: A URL-safe base64 encoded string.
    """
    return secrets.token_urlsafe(nbytes)


def main() -> None:
    """
    Main entry point for the secrets generation CLI.

    Parses arguments, generates required secrets for the Gateway,
    and handles file I/O operations or stdout printing.
    """
    parser = argparse.ArgumentParser(description="Generate secure secrets for MCP Gateway deployment.")
    parser.add_argument("--output", type=str, default=".env.secrets", help="Output file path")
    parser.add_argument("--force", action="store_true", help="Overwrite existing file if it exists")
    parser.add_argument("--stdout", action="store_true", help="Print secrets to stdout instead of a file")

    args = parser.parse_args()

    # Define the required secrets and their byte lengths
    # 32 bytes -> 43 chars (Keys), 18 bytes -> 24 chars (Passwords)
    secrets_map = {
        "JWT_SECRET_KEY": generate_token(32),
        "AUTH_ENCRYPTION_SECRET": generate_token(32),
        "BASIC_AUTH_PASSWORD": generate_token(18),
        "PLATFORM_ADMIN_PASSWORD": generate_token(18),
    }

    output_lines = [f"{key}={val}" for key, val in secrets_map.items()]
    output_content = "\n".join(output_lines) + "\n"

    # Handle Standard Output
    if args.stdout:
        print(output_content, end="")
        return

    # Acceptance Criteria: Prevent accidental overwrite
    if os.path.exists(args.output) and not args.force:
        print("Error: File already exists")
        print("Suggest using --force to overwrite")
        sys.exit(1)

    # File Writing
    try:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write("# Generated via: python -m mcpgateway.scripts.init_secrets\n")
            f.write(output_content)

        # Set restrictive permissions (read/write only for the owner)
        os.chmod(args.output, 0o600)

        print(f"Secrets written to {args.output}")
        print("\nHow to use this file:")
        print(f"1. Review the generated secrets in {args.output}")
        print("2. Merge these into your production environment or .env file.")
        print("3. IMPORTANT: Keep this file secure and never commit it to Git.")

    except OSError as e:
        print(f"Error: Could not write to file {args.output}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
