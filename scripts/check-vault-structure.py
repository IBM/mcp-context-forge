#!/usr/bin/env python3
"""
Debug script to check Vault token structure and identify team_id extraction issues.
"""

import asyncio
import os
import sys

import httpx


VAULT_ADDR = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN", "test-root-token")


async def list_vault_path(path: str, depth: int = 0) -> None:
    """Recursively list Vault paths and show structure."""
    headers = {"X-Vault-Token": VAULT_TOKEN}
    list_url = f"{VAULT_ADDR}/v1/{path}?list=true"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(list_url, headers=headers)
            if resp.status_code == 404:
                print(f"{'  ' * depth}(no data)")
                return
            resp.raise_for_status()
            data = resp.json()

            keys = data.get("data", {}).get("keys", [])
            for key in keys:
                print(f"{'  ' * depth}📁 {key}")

                # If it ends with /, recurse
                if key.endswith("/"):
                    await list_vault_path(f"{path}/{key.rstrip('/')}", depth + 1)
                else:
                    # Try to get the actual secret
                    secret_url = f"{VAULT_ADDR}/v1/{path}/{key}"
                    secret_resp = await client.get(secret_url, headers=headers)
                    if secret_resp.status_code == 200:
                        secret_data = secret_resp.json().get("data", {}).get("data", {})
                        print(f"{'  ' * depth}  Keys: {list(secret_data.keys())}")
                        # Show important fields
                        if "email" in secret_data:
                            print(f"{'  ' * depth}    email: {secret_data['email']}")
                        if "team_id" in secret_data:
                            print(f"{'  ' * depth}    team_id: {secret_data['team_id']}")
                        if "mcp_url" in secret_data:
                            print(f"{'  ' * depth}    mcp_url: {secret_data['mcp_url']}")
                        if "user_id" in secret_data:
                            print(f"{'  ' * depth}    user_id: {secret_data['user_id']}")

    except httpx.HTTPError as e:
        print(f"{'  ' * depth}❌ Error: {e}")


async def main():
    """Main entry point."""
    print("🔍 Vault OAuth Token Structure")
    print("=" * 60)
    print(f"VAULT_ADDR: {VAULT_ADDR}")
    print(f"VAULT_TOKEN: {VAULT_TOKEN[:10]}...")
    print("")

    print("📂 secret/data/contextforge/oauth/")
    await list_vault_path("secret/data/contextforge/oauth")

    print("")
    print("=" * 60)
    print("")
    print("Expected structure:")
    print("  secret/data/contextforge/oauth/")
    print("    team1/                    # ← team_id")
    print("      ca602dd4/               # ← server_id (hash of gateway.url)")
    print("        user2%40example.com   # ← URL-encoded email")
    print("")
    print("If you see a different structure, there's a bug in team_id extraction.")


if __name__ == "__main__":
    asyncio.run(main())
