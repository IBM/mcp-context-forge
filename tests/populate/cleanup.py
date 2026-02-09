# -*- coding: utf-8 -*-
"""Clean up populated test data via REST API DELETE endpoints.

Usage:
    python -m tests.populate.cleanup --confirm
    python -m tests.populate.cleanup --dry-run

Note: Teams and users cleanup is best-effort. Teams require owner tokens
(not admin), and user deletion may fail due to foreign key constraints.
For a complete wipe, delete the database file: rm mcp.db
"""

# Standard
import argparse
import asyncio
import logging
import os
import re
import sys
import time
from typing import Any, Dict, List

# Third-Party
from rich.console import Console

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Deletion order (respects dependencies - delete leaf entities first)
# (entity_name, list_endpoint, id_field, items_key_or_none)
# items_key: key in response dict containing items, or None for plain-list endpoints
DELETION_ORDER = [
    ("a2a_agents", "/a2a", "id", "agents"),
    ("servers", "/servers", "id", "servers"),
    ("prompts", "/prompts", "id", "prompts"),
    ("resources", "/resources", "id", "resources"),
    ("tools", "/tools", "id", "tools"),
    ("gateways", "/gateways", "id", "gateways"),
]

# Teams and users require special handling (ownership, cascading deps)
LOADTEST_PASSWORD = "LoadTest1234!"


async def cleanup_entities(
    base_url: str,
    email_domain: str = "loadtest.example.com",
    dry_run: bool = False,
    batch_size: int = 50,
) -> Dict[str, Any]:
    """Delete all entities with @loadtest.example.com via API."""
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

    async with httpx.AsyncClient(base_url=base_url, timeout=60.0, follow_redirects=True) as client:
        for entity_name, list_endpoint, id_field, items_key in DELETION_ORDER:
            deleted = 0
            errors = 0

            # Fetch all entities
            entity_ids: List[str] = []
            cursor = None
            page_size = 100
            loadtest_name_re = re.compile(r"^.+-(server|prompt|resource|agent|tool)-\d+-\d+$")

            while True:
                try:
                    params: Dict[str, Any] = {"limit": page_size}
                    if items_key:
                        params["include_pagination"] = "true"
                        if cursor:
                            params["cursor"] = cursor

                    resp = await client.get(list_endpoint, headers=headers, params=params)
                    if resp.status_code != 200:
                        break

                    data = resp.json()

                    # Extract items from response
                    if isinstance(data, dict):
                        items = data.get(items_key, []) if items_key else []
                        # Cursor-based uses nextCursor, offset-based has no cursor
                        cursor = data.get("nextCursor")
                    elif isinstance(data, list):
                        items = data
                        cursor = None
                    else:
                        break

                    if not items:
                        break

                    for item in items:
                        # Filter to loadtest entities by checking multiple identifying fields
                        searchable = " ".join(str(item.get(f, "")) for f in ("email", "created_by", "user_email", "name", "url", "uri", "endpointUrl", "description", "slug"))
                        item_name = str(item.get("name", ""))
                        is_loadtest = email_domain in searchable or loadtest_name_re.match(item_name)
                        if is_loadtest:
                            entity_ids.append(str(item.get(id_field, item.get("id", ""))))

                    # Stop if no more pages
                    if not items_key or not cursor or len(items) < page_size:
                        break

                except Exception as exc:
                    logger.warning(f"Failed to list {entity_name}: {exc}")
                    break

            if not entity_ids:
                results[entity_name] = {"found": 0, "deleted": 0, "errors": 0}
                continue

            if dry_run:
                logger.info(f"[DRY RUN] Would delete {len(entity_ids)} {entity_name}")
                results[entity_name] = {"found": len(entity_ids), "deleted": 0, "dry_run": True}
                continue

            # Delete in batches
            sem = asyncio.Semaphore(batch_size)

            async def _delete_one(eid: str, ep: str = list_endpoint, hdrs: Dict[str, str] = headers):
                nonlocal deleted, errors
                async with sem:
                    try:
                        delete_endpoint = f"{ep.rstrip('/')}/{eid}"
                        resp = await client.delete(delete_endpoint, headers=hdrs)
                        if resp.status_code in (200, 204, 404):
                            deleted += 1
                        else:
                            errors += 1
                    except Exception:
                        errors += 1

            # Process deletion in chunks
            for i in range(0, len(entity_ids), batch_size * 2):
                chunk = entity_ids[i : i + batch_size * 2]
                await asyncio.gather(*[_delete_one(eid) for eid in chunk])

            results[entity_name] = {"found": len(entity_ids), "deleted": deleted, "errors": errors}
            logger.info(f"Deleted {deleted}/{len(entity_ids)} {entity_name} (errors: {errors})")

        # --- Teams: delete via user tokens (owners only) ---
        teams_deleted = 0
        teams_errors = 0
        teams_found = 0

        # List all teams
        team_map: Dict[str, str] = {}  # team_id -> created_by email
        cursor = None
        while True:
            params_t: Dict[str, Any] = {"limit": 100, "include_pagination": "true"}
            if cursor:
                params_t["cursor"] = cursor
            try:
                resp = await client.get("/teams/", headers=headers, params=params_t)
                if resp.status_code != 200:
                    break
                data = resp.json()
                teams_list = data.get("teams", []) if isinstance(data, dict) else data
                for t in teams_list:
                    created_by = t.get("created_by", "")
                    if email_domain in str(created_by) or email_domain in str(t.get("slug", "")):
                        team_map[t["id"]] = created_by
                cursor = data.get("nextCursor") if isinstance(data, dict) else None
                if not cursor or len(teams_list) < 100:
                    break
            except Exception:
                break

        teams_found = len(team_map)
        if teams_found > 0 and not dry_run:
            # Group teams by owner
            owner_teams: Dict[str, List[str]] = {}
            for tid, owner in team_map.items():
                owner_teams.setdefault(owner, []).append(tid)

            # Login as each owner and delete their teams
            for owner_email, team_ids_to_delete in owner_teams.items():
                try:
                    login_resp = await client.post(
                        "/auth/email/login",
                        json={"email": owner_email, "password": LOADTEST_PASSWORD},
                        headers={"Content-Type": "application/json"},
                    )
                    if login_resp.status_code != 200:
                        teams_errors += len(team_ids_to_delete)
                        continue
                    user_jwt = login_resp.json().get("access_token") or login_resp.json().get("token")
                    if not user_jwt:
                        teams_errors += len(team_ids_to_delete)
                        continue
                    user_hdrs = {"Authorization": f"Bearer {user_jwt}", "Content-Type": "application/json"}
                    for tid in team_ids_to_delete:
                        try:
                            resp = await client.delete(f"/teams/{tid}", headers=user_hdrs)
                            if resp.status_code in (200, 204, 404):
                                teams_deleted += 1
                            else:
                                teams_errors += 1
                        except Exception:
                            teams_errors += 1
                except Exception:
                    teams_errors += len(team_ids_to_delete)
        elif teams_found > 0 and dry_run:
            logger.info(f"[DRY RUN] Would delete {teams_found} teams")

        results["teams"] = {"found": teams_found, "deleted": teams_deleted, "errors": teams_errors}
        if teams_found > 0 and not dry_run:
            logger.info(f"Deleted {teams_deleted}/{teams_found} teams (errors: {teams_errors})")

        # --- Users: delete via admin endpoint ---
        users_deleted = 0
        users_errors = 0
        try:
            resp = await client.get("/auth/email/admin/users", headers=headers, params={"limit": 500})
            user_list = resp.json() if resp.status_code == 200 else []
            user_emails = [u["email"] for u in user_list if isinstance(u, dict) and email_domain in str(u.get("email", ""))]
        except Exception:
            user_emails = []

        if user_emails and not dry_run:
            for ue in user_emails:
                try:
                    resp = await client.delete(f"/auth/email/admin/users/{ue}", headers=headers)
                    if resp.status_code in (200, 204, 404):
                        users_deleted += 1
                    else:
                        users_errors += 1
                except Exception:
                    users_errors += 1
        elif user_emails and dry_run:
            logger.info(f"[DRY RUN] Would delete {len(user_emails)} users")

        results["users"] = {"found": len(user_emails), "deleted": users_deleted, "errors": users_errors}
        if user_emails and not dry_run:
            logger.info(f"Deleted {users_deleted}/{len(user_emails)} users (errors: {users_errors})")

    return results


def main():
    parser = argparse.ArgumentParser(description="Clean up loadtest data via REST API")
    parser.add_argument("--base-url", type=str, default=os.environ.get("MCPGATEWAY_BASE_URL", "http://localhost:8080"))
    parser.add_argument("--email-domain", type=str, default="loadtest.example.com")
    parser.add_argument("--confirm", action="store_true", help="Confirm deletion (required)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")
    parser.add_argument("--batch-size", type=int, default=50, help="Concurrent delete batch size")
    args = parser.parse_args()

    console = Console()

    if not args.confirm and not args.dry_run:
        console.print("[red]Must specify --confirm to delete data (or use --dry-run)[/red]")
        sys.exit(1)

    console.print(f"\n[bold cyan]Cleaning up loadtest data at {args.base_url}[/bold cyan]")
    console.print(f"[dim]Email domain filter: @{args.email_domain}[/dim]\n")

    if args.dry_run:
        console.print("[yellow]DRY RUN - No entities will be deleted[/yellow]\n")

    start_time = time.time()
    results = asyncio.run(cleanup_entities(args.base_url, args.email_domain, args.dry_run, args.batch_size))
    duration = time.time() - start_time

    # Print summary
    total_deleted = sum(r.get("deleted", 0) for r in results.values())
    total_errors = sum(r.get("errors", 0) for r in results.values())
    total_found = sum(r.get("found", 0) for r in results.values())

    console.print(f"\n{'=' * 60}")
    console.print("[bold]Cleanup Summary[/bold]")
    console.print(f"{'=' * 60}")

    for entity, info in results.items():
        found = info.get("found", 0)
        deleted = info.get("deleted", 0)
        errs = info.get("errors", 0)
        if found > 0:
            console.print(f"  {entity:20s}  found: {found:>8,}  deleted: {deleted:>8,}  errors: {errs:>4,}")

    console.print(f"\n  {'Total':20s}  found: {total_found:>8,}  deleted: {total_deleted:>8,}  errors: {total_errors:>4,}")
    console.print(f"  Duration: {duration:.2f}s")
    console.print(f"  Dry Run: {args.dry_run}")
    console.print(f"{'=' * 60}\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
