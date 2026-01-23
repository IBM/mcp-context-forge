#!/usr/bin/env python3
"""
Cleanup script for orphaned resources, prompts, and tools.

This script identifies and removes database records that were left orphaned
due to incomplete gateway deletions (e.g., issue #2341 crash scenarios).

Orphaned records are those where:
- gateway_id is NULL, OR
- gateway_id points to a non-existent gateway

Usage:
    # Dry run (default) - shows what would be deleted
    python scripts/cleanup_orphaned_resources.py

    # Actually delete orphaned records
    python scripts/cleanup_orphaned_resources.py --execute

    # Filter by team
    python scripts/cleanup_orphaned_resources.py --team-id <team_id>

    # Filter by owner
    python scripts/cleanup_orphaned_resources.py --owner-email <email>
"""

import argparse
import sys
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, ".")

from sqlalchemy import delete, select, and_, or_
from sqlalchemy.orm import Session

from mcpgateway.db import (
    SessionLocal,
    Resource as DbResource,
    Prompt as DbPrompt,
    Tool as DbTool,
    Gateway as DbGateway,
    ResourceMetric,
    PromptMetric,
    ToolMetric,
    ResourceSubscription,
    server_resource_association,
    server_prompt_association,
    server_tool_association,
)


def get_orphaned_resources(db: Session, team_id: str = None, owner_email: str = None):
    """Find resources with no valid gateway."""
    # Get all valid gateway IDs
    valid_gateway_ids = set(
        r[0] for r in db.execute(select(DbGateway.id)).all()
    )

    # Build query for resources
    query = select(DbResource)

    if team_id:
        query = query.where(DbResource.team_id == team_id)
    if owner_email:
        query = query.where(DbResource.owner_email == owner_email)

    resources = db.execute(query).scalars().all()

    # Filter to orphaned (gateway_id is NULL or invalid)
    orphaned = [
        r for r in resources
        if r.gateway_id is None or r.gateway_id not in valid_gateway_ids
    ]

    return orphaned


def get_orphaned_prompts(db: Session, team_id: str = None, owner_email: str = None):
    """Find prompts with no valid gateway."""
    valid_gateway_ids = set(
        r[0] for r in db.execute(select(DbGateway.id)).all()
    )

    query = select(DbPrompt)

    if team_id:
        query = query.where(DbPrompt.team_id == team_id)
    if owner_email:
        query = query.where(DbPrompt.owner_email == owner_email)

    prompts = db.execute(query).scalars().all()

    orphaned = [
        p for p in prompts
        if p.gateway_id is None or p.gateway_id not in valid_gateway_ids
    ]

    return orphaned


def get_orphaned_tools(db: Session, team_id: str = None, owner_email: str = None):
    """Find tools with no valid gateway."""
    valid_gateway_ids = set(
        r[0] for r in db.execute(select(DbGateway.id)).all()
    )

    query = select(DbTool)

    if team_id:
        query = query.where(DbTool.team_id == team_id)
    if owner_email:
        query = query.where(DbTool.owner_email == owner_email)

    tools = db.execute(query).scalars().all()

    orphaned = [
        t for t in tools
        if t.gateway_id is None or t.gateway_id not in valid_gateway_ids
    ]

    return orphaned


def delete_orphaned_resources(db: Session, resource_ids: list, dry_run: bool = True):
    """Delete orphaned resources and their related records."""
    if not resource_ids:
        return 0

    if dry_run:
        return len(resource_ids)

    # Delete in chunks to avoid SQLite parameter limits
    for i in range(0, len(resource_ids), 500):
        chunk = resource_ids[i:i + 500]
        # Delete related records first
        db.execute(delete(ResourceMetric).where(ResourceMetric.resource_id.in_(chunk)))
        db.execute(delete(ResourceSubscription).where(ResourceSubscription.resource_id.in_(chunk)))
        db.execute(delete(server_resource_association).where(
            server_resource_association.c.resource_id.in_(chunk)
        ))
        # Delete resources
        db.execute(delete(DbResource).where(DbResource.id.in_(chunk)))

    return len(resource_ids)


def delete_orphaned_prompts(db: Session, prompt_ids: list, dry_run: bool = True):
    """Delete orphaned prompts and their related records."""
    if not prompt_ids:
        return 0

    if dry_run:
        return len(prompt_ids)

    for i in range(0, len(prompt_ids), 500):
        chunk = prompt_ids[i:i + 500]
        db.execute(delete(PromptMetric).where(PromptMetric.prompt_id.in_(chunk)))
        db.execute(delete(server_prompt_association).where(
            server_prompt_association.c.prompt_id.in_(chunk)
        ))
        db.execute(delete(DbPrompt).where(DbPrompt.id.in_(chunk)))

    return len(prompt_ids)


def delete_orphaned_tools(db: Session, tool_ids: list, dry_run: bool = True):
    """Delete orphaned tools and their related records."""
    if not tool_ids:
        return 0

    if dry_run:
        return len(tool_ids)

    for i in range(0, len(tool_ids), 500):
        chunk = tool_ids[i:i + 500]
        db.execute(delete(ToolMetric).where(ToolMetric.tool_id.in_(chunk)))
        db.execute(delete(server_tool_association).where(
            server_tool_association.c.tool_id.in_(chunk)
        ))
        db.execute(delete(DbTool).where(DbTool.id.in_(chunk)))

    return len(tool_ids)


def main():
    parser = argparse.ArgumentParser(
        description="Cleanup orphaned resources, prompts, and tools from the database."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete records (default is dry-run)"
    )
    parser.add_argument(
        "--team-id",
        type=str,
        help="Filter by team ID"
    )
    parser.add_argument(
        "--owner-email",
        type=str,
        help="Filter by owner email"
    )
    args = parser.parse_args()

    dry_run = not args.execute

    print(f"{'=' * 60}")
    print(f"Orphaned Records Cleanup Script")
    print(f"{'=' * 60}")
    print(f"Mode: {'DRY RUN (no changes will be made)' if dry_run else 'EXECUTE (records will be deleted)'}")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    if args.team_id:
        print(f"Team filter: {args.team_id}")
    if args.owner_email:
        print(f"Owner filter: {args.owner_email}")
    print(f"{'=' * 60}\n")

    db = SessionLocal()
    try:
        # Find orphaned records
        print("Scanning for orphaned records...\n")

        orphaned_resources = get_orphaned_resources(db, args.team_id, args.owner_email)
        orphaned_prompts = get_orphaned_prompts(db, args.team_id, args.owner_email)
        orphaned_tools = get_orphaned_tools(db, args.team_id, args.owner_email)

        # Report findings
        print(f"Orphaned Resources: {len(orphaned_resources)}")
        for r in orphaned_resources[:10]:  # Show first 10
            print(f"  - {r.uri} (team={r.team_id}, owner={r.owner_email}, gateway_id={r.gateway_id})")
        if len(orphaned_resources) > 10:
            print(f"  ... and {len(orphaned_resources) - 10} more")
        print()

        print(f"Orphaned Prompts: {len(orphaned_prompts)}")
        for p in orphaned_prompts[:10]:
            print(f"  - {p.name} (team={p.team_id}, owner={p.owner_email}, gateway_id={p.gateway_id})")
        if len(orphaned_prompts) > 10:
            print(f"  ... and {len(orphaned_prompts) - 10} more")
        print()

        print(f"Orphaned Tools: {len(orphaned_tools)}")
        for t in orphaned_tools[:10]:
            print(f"  - {t.original_name} (team={t.team_id}, owner={t.owner_email}, gateway_id={t.gateway_id})")
        if len(orphaned_tools) > 10:
            print(f"  ... and {len(orphaned_tools) - 10} more")
        print()

        total_orphaned = len(orphaned_resources) + len(orphaned_prompts) + len(orphaned_tools)

        if total_orphaned == 0:
            print("No orphaned records found. Database is clean.")
            return 0

        # Delete if not dry run
        if not dry_run:
            print(f"{'=' * 60}")
            print("Deleting orphaned records...")
            print(f"{'=' * 60}\n")

            resource_ids = [r.id for r in orphaned_resources]
            prompt_ids = [p.id for p in orphaned_prompts]
            tool_ids = [t.id for t in orphaned_tools]

            deleted_resources = delete_orphaned_resources(db, resource_ids, dry_run=False)
            deleted_prompts = delete_orphaned_prompts(db, prompt_ids, dry_run=False)
            deleted_tools = delete_orphaned_tools(db, tool_ids, dry_run=False)

            db.commit()

            print(f"Deleted {deleted_resources} orphaned resources")
            print(f"Deleted {deleted_prompts} orphaned prompts")
            print(f"Deleted {deleted_tools} orphaned tools")
            print(f"\nTotal: {deleted_resources + deleted_prompts + deleted_tools} records deleted")
        else:
            print(f"{'=' * 60}")
            print(f"DRY RUN COMPLETE")
            print(f"{'=' * 60}")
            print(f"\nWould delete {total_orphaned} orphaned records.")
            print(f"Run with --execute to actually delete these records.")

        return 0

    except Exception as e:
        print(f"ERROR: {e}")
        db.rollback()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
