#!/usr/bin/env python3
"""
Retrieve team-scoped OAuth credentials from Vault.

Usage:
    python3 scripts/get-oauth-credentials-vault.py <team_id> <mcp_url>

Example:
    python3 scripts/get-oauth-credentials-vault.py \
        "f8927490a44d4ede95889136d004c202" \
        "https://mcp.github.acme.com"
"""
import hashlib
import json
import os
import sys

import httpx


def hash_mcp_url(mcp_url: str) -> str:
    """Calculate server_id from mcp_url (SHA-256, first 8 chars)."""
    return hashlib.sha256(mcp_url.encode()).hexdigest()[:8]


async def get_oauth_credentials(team_id: str, mcp_url: str) -> dict | None:
    """Retrieve OAuth credentials from Vault."""
    # Load configuration
    vault_addr = os.getenv("VAULT_ADDR", "http://localhost:8200")
    vault_token = os.getenv("VAULT_TOKEN")
    vault_kv_mount = os.getenv("VAULT_KV_MOUNT", "secret")
    vault_kv_path_prefix = os.getenv("VAULT_KV_PATH_PREFIX", "contextforge/oauth")

    if not vault_token:
        print("Error: VAULT_TOKEN environment variable is not set", file=sys.stderr)
        return None

    # Calculate server_id
    server_id = hash_mcp_url(mcp_url)

    # Construct Vault path
    path = f"{vault_kv_mount}/data/{vault_kv_path_prefix}/credentials/{team_id}/{server_id}"
    url = f"{vault_addr}/v1/{path}"

    print(f"Retrieving OAuth credentials from Vault")
    print(f"  Team ID: {team_id}")
    print(f"  MCP URL: {mcp_url}")
    print(f"  Server ID: {server_id}")
    print(f"  Vault Path: {path}")
    print()

    # Fetch from Vault
    headers = {"X-Vault-Token": vault_token}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)

            if response.status_code == 404:
                print("❌ No OAuth credentials found at this path")
                return None

            response.raise_for_status()
            result = response.json()

            if "data" not in result or "data" not in result["data"]:
                print("❌ Invalid response structure from Vault")
                return None

            credentials = result["data"]["data"]
            print("✓ OAuth credentials found:")
            print()

            # Pretty-print credentials (redact secret)
            safe_creds = credentials.copy()
            if "client_secret" in safe_creds:
                safe_creds["client_secret"] = "[REDACTED]"

            print(json.dumps(safe_creds, indent=2))
            return credentials

        except httpx.HTTPStatusError as e:
            print(f"❌ HTTP error: {e.response.status_code}", file=sys.stderr)
            if e.response.content:
                error_data = e.response.json()
                if "errors" in error_data:
                    for error in error_data["errors"]:
                        print(f"  {error}", file=sys.stderr)
            return None

        except Exception as e:
            print(f"❌ Error: {e}", file=sys.stderr)
            return None


async def main():
    """Main entry point."""
    if len(sys.argv) != 3:
        print("Usage: python3 scripts/get-oauth-credentials-vault.py <team_id> <mcp_url>", file=sys.stderr)
        print()
        print("Example:")
        print('  python3 scripts/get-oauth-credentials-vault.py \\', file=sys.stderr)
        print('      "f8927490a44d4ede95889136d004c202" \\', file=sys.stderr)
        print('      "https://mcp.github.acme.com"', file=sys.stderr)
        sys.exit(1)

    team_id = sys.argv[1]
    mcp_url = sys.argv[2]

    credentials = await get_oauth_credentials(team_id, mcp_url)
    if not credentials:
        sys.exit(1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
