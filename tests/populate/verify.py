# -*- coding: utf-8 -*-
"""Verify populated data via REST API GET endpoints.

Usage:
    python -m tests.populate.verify
    python -m tests.populate.verify --base-url http://gateway:4444
"""

# Standard
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict

# Third-Party
from rich.console import Console
from rich.table import Table

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Endpoints to verify: (endpoint, entity_name, items_key)
# items_key: key in the response dict containing items, or None for plain-list endpoints
VERIFY_ENDPOINTS = [
    ("/auth/email/admin/users", "users", None),
    ("/teams/", "teams", "teams"),
    ("/tools", "tools", "tools"),
    ("/resources", "resources", "resources"),
    ("/prompts", "prompts", "prompts"),
    ("/servers", "servers", "servers"),
    ("/gateways", "gateways", "gateways"),
    ("/a2a", "a2a_agents", "agents"),
    ("/tokens", "tokens", "tokens"),
    ("/rbac/roles", "roles", None),
]


async def verify_entities(base_url: str, email_domain: str = "loadtest.example.com") -> Dict[str, Any]:
    """Verify entity counts via GET endpoints."""
    # Third-Party
    import httpx

    # Generate admin token
    try:
        # First-Party
        from mcpgateway.utils.create_jwt_token import _create_jwt_token

        admin_token = os.environ.get("MCPGATEWAY_BEARER_TOKEN") or _create_jwt_token(
            data={"sub": "admin@example.com", "username": "admin@example.com"},
            expires_in_minutes=60,
            user_data={"email": "admin@example.com", "full_name": "Admin", "is_admin": True},
            teams=None,
        )
    except ImportError:
        admin_token = os.environ.get("MCPGATEWAY_BEARER_TOKEN", "")
        if not admin_token:
            raise RuntimeError("Set MCPGATEWAY_BEARER_TOKEN or install mcpgateway")

    headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}

    results: Dict[str, Any] = {}

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0, follow_redirects=True) as client:
        for endpoint, entity_name, items_key in VERIFY_ENDPOINTS:
            try:
                if items_key:
                    # Paginated endpoint: iterate pages and count all items
                    total = 0
                    cursor = None
                    page_limit = 100  # Some endpoints cap at 100
                    while True:
                        params: Dict[str, Any] = {"limit": page_limit, "include_pagination": "true"}
                        if cursor:
                            params["cursor"] = cursor
                        resp = await client.get(endpoint, headers=headers, params=params)
                        if resp.status_code != 200:
                            results[entity_name] = {"count": 0, "status": f"http_{resp.status_code}"}
                            break
                        data = resp.json()
                        if isinstance(data, dict):
                            # Check for offset-based total first
                            if "total" in data:
                                results[entity_name] = {"count": data["total"], "status": "ok"}
                                break
                            items = data.get(items_key, [])
                            total += len(items)
                            cursor = data.get("nextCursor")
                            if not cursor or len(items) < page_limit:
                                results[entity_name] = {"count": total, "status": "ok"}
                                break
                        else:
                            results[entity_name] = {"count": len(data) if isinstance(data, list) else 0, "status": "ok"}
                            break
                else:
                    # Plain list endpoint (users, roles)
                    resp = await client.get(endpoint, headers=headers, params={"limit": 500})
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, list):
                            results[entity_name] = {"count": len(data), "status": "ok"}
                        elif isinstance(data, dict) and "total" in data:
                            results[entity_name] = {"count": data["total"], "status": "ok"}
                        else:
                            results[entity_name] = {"count": "unknown", "status": "no_count"}
                    else:
                        results[entity_name] = {"count": 0, "status": f"http_{resp.status_code}"}

            except Exception as exc:
                results[entity_name] = {"count": 0, "status": f"error: {exc}"}

        # Verify login works for a sample user
        try:
            login_resp = await client.post(
                "/auth/email/login",
                headers={"Content-Type": "application/json"},
                json={"email": f"user1@{email_domain}", "password": "LoadTest1234!"},
            )
            results["user_login_test"] = {
                "status": "ok" if login_resp.status_code == 200 else f"http_{login_resp.status_code}",
                "can_login": login_resp.status_code == 200,
            }
        except Exception as exc:
            results["user_login_test"] = {"status": f"error: {exc}", "can_login": False}

    return results


def main():
    parser = argparse.ArgumentParser(description="Verify populated data via REST API")
    parser.add_argument("--base-url", type=str, default=os.environ.get("MCPGATEWAY_BASE_URL", "http://localhost:8080"))
    parser.add_argument("--email-domain", type=str, default="loadtest.example.com")
    parser.add_argument("--output", type=str, help="Save report to JSON file")
    args = parser.parse_args()

    console = Console()
    console.print(f"\n[bold cyan]Verifying populated data at {args.base_url}[/bold cyan]\n")

    results = asyncio.run(verify_entities(args.base_url, args.email_domain))

    # Display results
    table = Table(title="Entity Verification", show_header=True, header_style="bold")
    table.add_column("Entity", style="cyan", no_wrap=True)
    table.add_column("Count", justify="right")
    table.add_column("Status", style="bold")

    all_ok = True
    for entity, info in sorted(results.items()):
        status = info.get("status", "unknown")
        count = info.get("count", "?")
        is_ok = status == "ok" or info.get("can_login", False)
        style = "green" if is_ok else "yellow" if status == "partial" else "red"

        if not is_ok and entity != "user_login_test":
            all_ok = False

        table.add_row(entity, str(count), f"[{style}]{status}[/{style}]")

    console.print(table)

    # Login test result
    login_info = results.get("user_login_test", {})
    if login_info.get("can_login"):
        console.print("\n[green]v[/green] User login verification: PASSED")
    else:
        console.print(f"\n[red]x[/red] User login verification: FAILED ({login_info.get('status', 'unknown')})")

    console.print(f"\n[bold]Overall: {'[green]ALL CHECKS PASSED[/green]' if all_ok else '[yellow]SOME CHECKS INCOMPLETE[/yellow]'}[/bold]\n")

    # Save report
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        console.print(f"[dim]Report saved to: {output_path}[/dim]")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
