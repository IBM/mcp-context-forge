#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI tool for managing simple authentication tokens.

This tool allows administrators to create, list, and revoke tokens
for the simple token authentication plugin.
"""

import argparse
import sys

from plugins.examples.simple_token_auth.token_storage import TokenStorage


def create_token(storage: TokenStorage, email: str, full_name: str, is_admin: bool, expires_days: int):
    """Create a new authentication token."""
    token = storage.create_token(
        email=email,
        full_name=full_name,
        is_admin=is_admin,
        expires_in_days=expires_days if expires_days > 0 else None,
    )

    print("\n✓ Token created successfully!")
    print(f"\nUser: {full_name} ({email})")
    print(f"Admin: {is_admin}")
    print(f"Expires: {'Never' if expires_days <= 0 else f'{expires_days} days'}")
    print(f"\nToken: {token}")
    print("\nUse this token in API requests:")
    print(f"  curl -H 'X-Auth-Token: {token}' http://localhost:4444/protocol/initialize")
    print()


def list_tokens(storage: TokenStorage):
    """List all active tokens."""
    tokens = storage.list_active_tokens()

    if not tokens:
        print("\nNo active tokens found.\n")
        return

    print(f"\nActive tokens: {len(tokens)}")
    print("-" * 80)

    for token_data in tokens:
        expires = token_data.expires_at.isoformat() if token_data.expires_at else "Never"
        admin_badge = " [ADMIN]" if token_data.is_admin else ""
        print(f"\nEmail: {token_data.email}{admin_badge}")
        print(f"Name: {token_data.full_name}")
        print(f"Token: {token_data.token[:20]}...")
        print(f"Created: {token_data.created_at.isoformat()}")
        print(f"Expires: {expires}")

    print()


def revoke_token(storage: TokenStorage, token: str):
    """Revoke a specific token."""
    success = storage.revoke_token(token)

    if success:
        print("\n✓ Token revoked successfully\n")
    else:
        print("\n✗ Token not found\n")
        sys.exit(1)


def revoke_user(storage: TokenStorage, email: str):
    """Revoke all tokens for a user."""
    count = storage.revoke_user_tokens(email)

    if count > 0:
        print(f"\n✓ Revoked {count} token(s) for {email}\n")
    else:
        print(f"\n✗ No tokens found for {email}\n")
        sys.exit(1)


def cleanup(storage: TokenStorage):
    """Remove expired tokens."""
    count = storage.cleanup_expired()
    print(f"\n✓ Removed {count} expired token(s)\n")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Manage simple authentication tokens",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create a token for a regular user
  python -m plugins.simple_token_auth.token_cli create user@example.com "User Name"

  # Create an admin token that never expires
  python -m plugins.simple_token_auth.token_cli create admin@example.com "Admin User" --admin --expires 0

  # List all active tokens
  python -m plugins.simple_token_auth.token_cli list

  # Revoke a specific token
  python -m plugins.simple_token_auth.token_cli revoke TOKEN_STRING

  # Revoke all tokens for a user
  python -m plugins.simple_token_auth.token_cli revoke-user user@example.com

  # Clean up expired tokens
  python -m plugins.simple_token_auth.token_cli cleanup
        """,
    )

    parser.add_argument(
        "--storage",
        default="data/auth_tokens.json",
        help="Path to token storage file (default: data/auth_tokens.json)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Create command
    create_parser = subparsers.add_parser("create", help="Create a new token")
    create_parser.add_argument("email", help="User email address")
    create_parser.add_argument("full_name", help="User full name")
    create_parser.add_argument("--admin", action="store_true", help="Grant admin privileges")
    create_parser.add_argument("--expires", type=int, default=30, help="Days until expiration (0 = never, default: 30)")

    # List command
    subparsers.add_parser("list", help="List all active tokens")

    # Revoke command
    revoke_parser = subparsers.add_parser("revoke", help="Revoke a specific token")
    revoke_parser.add_argument("token", help="Token to revoke")

    # Revoke user command
    revoke_user_parser = subparsers.add_parser("revoke-user", help="Revoke all tokens for a user")
    revoke_user_parser.add_argument("email", help="User email address")

    # Cleanup command
    subparsers.add_parser("cleanup", help="Remove expired tokens")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Initialize storage
    storage = TokenStorage(storage_file=args.storage)

    # Execute command
    if args.command == "create":
        create_token(storage, args.email, args.full_name, args.admin, args.expires)
    elif args.command == "list":
        list_tokens(storage)
    elif args.command == "revoke":
        revoke_token(storage, args.token)
    elif args.command == "revoke-user":
        revoke_user(storage, args.email)
    elif args.command == "cleanup":
        cleanup(storage)


if __name__ == "__main__":
    main()
