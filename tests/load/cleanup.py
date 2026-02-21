# -*- coding: utf-8 -*-
"""CLI for cleaning up load test data.

Usage:
    python -m tests.load.cleanup --profile production --confirm
    python -m tests.load.cleanup --all --confirm
"""

import argparse
import logging
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from mcpgateway.config import settings

from .utils.progress import ProgressTracker


# Logger setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Deletion order (respects foreign keys)
DELETION_ORDER = [
    "tool_metrics",
    "resource_metrics",
    "prompt_metrics",
    "server_metrics",
    "a2a_agent_metrics",
    "permission_audit_logs",
    "email_auth_events",
    "token_usage_logs",
    "email_api_tokens",
    "email_team_member_history",
    "email_team_invitations",
    "email_team_join_requests",
    "email_team_members",
    "tools",
    "resources",
    "prompts",
    "servers",
    "a2a_agents",
    "gateways",
    "email_teams",
    "user_roles",
    "roles",
    "sso_auth_sessions",
    "sso_providers",
    "email_users",
]


def create_database_session():
    """Create database session.

    Returns:
        SQLAlchemy session
    """
    engine = create_engine(settings.database_url, echo=False)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def get_test_data_count(db, table: str, email_domain: str = "loadtest.example.com") -> int:
    """Get count of test data records in a table.

    Args:
        db: Database session
        table: Table name
        email_domain: Email domain for test data

    Returns:
        Count of test records
    """
    try:
        # Tables with email field
        if table in ["email_users", "email_api_tokens", "tools", "resources", "prompts", "servers"]:
            if table in ["email_users"]:
                result = db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE email LIKE :domain"), {"domain": f"%{email_domain}"})
            elif table in ["email_api_tokens"]:
                result = db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE user_email LIKE :domain"), {"domain": f"%{email_domain}"})
            else:
                result = db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE created_by LIKE :domain"), {"domain": f"%{email_domain}"})
        # Teams created by test users
        elif table == "email_teams":
            result = db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE created_by LIKE :domain"), {"domain": f"%{email_domain}"})
        else:
            # For other tables, count all (assumes test environment)
            result = db.execute(text(f"SELECT COUNT(*) FROM {table}"))

        return result.scalar()
    except Exception as e:
        logger.warning(f"Could not count records in {table}: {e}")
        return 0


def delete_test_data(
    db,
    table: str,
    email_domain: str = "loadtest.example.com",
    batch_size: int = 1000,
    dry_run: bool = False
) -> int:
    """Delete test data from a table.

    Args:
        db: Database session
        table: Table name
        email_domain: Email domain for test data
        batch_size: Batch delete size
        dry_run: If True, don't actually delete

    Returns:
        Number of records deleted
    """
    count = get_test_data_count(db, table, email_domain)

    if count == 0:
        return 0

    if dry_run:
        logger.info(f"[DRY RUN] Would delete {count} records from {table}")
        return count

    logger.info(f"Deleting {count} records from {table}...")

    try:
        # Delete all matching records (SQLite LIMIT in DELETE requires compile-time option)
        deleted = 0
        with ProgressTracker(count, f"Deleting {table}", "records") as progress:
            # Delete all matching records at once
            if table in ["email_users"]:
                result = db.execute(
                    text(f"DELETE FROM {table} WHERE email LIKE :domain"),
                    {"domain": f"%{email_domain}"}
                )
            elif table in ["email_api_tokens"]:
                result = db.execute(
                    text(f"DELETE FROM {table} WHERE user_email LIKE :domain"),
                    {"domain": f"%{email_domain}"}
                )
            elif table in ["email_teams"]:
                result = db.execute(
                    text(f"DELETE FROM {table} WHERE created_by LIKE :domain"),
                    {"domain": f"%{email_domain}"}
                )
            elif table in ["tools", "resources", "prompts", "servers"]:
                result = db.execute(
                    text(f"DELETE FROM {table} WHERE created_by LIKE :domain"),
                    {"domain": f"%{email_domain}"}
                )
            else:
                # Delete all from table (assumes test environment)
                result = db.execute(text(f"DELETE FROM {table}"))

            rows_deleted = result.rowcount
            db.commit()

            deleted = rows_deleted
            progress.update(rows_deleted)

        logger.info(f"Deleted {deleted} records from {table}")
        return deleted

    except Exception as e:
        logger.error(f"Failed to delete from {table}: {e}")
        db.rollback()
        raise


def truncate_all_tables(db, dry_run: bool = False) -> int:
    """Truncate all tables (DANGEROUS!).

    Args:
        db: Database session
        dry_run: If True, don't actually truncate

    Returns:
        Number of tables truncated
    """
    logger.warning("TRUNCATING ALL TABLES - THIS CANNOT BE UNDONE!")

    if dry_run:
        logger.info(f"[DRY RUN] Would truncate {len(DELETION_ORDER)} tables")
        return len(DELETION_ORDER)

    truncated = 0
    for table in DELETION_ORDER:
        try:
            db.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
            db.commit()
            logger.info(f"Truncated {table}")
            truncated += 1
        except Exception as e:
            logger.warning(f"Could not truncate {table}: {e}")
            db.rollback()

    return truncated


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Clean up load test data from ContextForge database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--profile",
        type=str,
        choices=["small", "medium", "large", "production", "massive"],
        help="Profile that was used for generation"
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Delete all test data (matches email domain)"
    )

    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate all tables (DANGEROUS - deletes everything!)"
    )

    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm deletion (required for safety)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting"
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch delete size (default: 1000)"
    )

    parser.add_argument(
        "--email-domain",
        type=str,
        default="loadtest.example.com",
        help="Email domain for test data (default: loadtest.example.com)"
    )

    args = parser.parse_args()

    # Safety checks
    if not args.confirm and not args.dry_run:
        logger.error("Must specify --confirm to delete data (or use --dry-run)")
        sys.exit(1)

    if args.truncate and not args.confirm:
        logger.error("--truncate requires --confirm for safety")
        sys.exit(1)

    if args.truncate:
        response = input("TRUNCATE WILL DELETE ALL DATA! Type 'YES' to continue: ")
        if response != "YES":
            logger.info("Cancelled")
            sys.exit(0)

    # Create database session
    db = create_database_session()

    start_time = time.time()
    total_deleted = 0

    try:
        if args.truncate:
            # Truncate all tables
            total_deleted = truncate_all_tables(db, dry_run=args.dry_run)
        else:
            # Delete test data in correct order
            for table in DELETION_ORDER:
                deleted = delete_test_data(db, table, args.email_domain, args.batch_size, args.dry_run)
                total_deleted += deleted

        elapsed_time = time.time() - start_time

        print("\n" + "="*80)
        print("Cleanup Summary")
        print("="*80)
        print(f"Duration: {elapsed_time:.2f} seconds")
        print(f"Records Deleted: {total_deleted:,}")
        print(f"Dry Run: {args.dry_run}")
        print("="*80)

        logger.info("Cleanup complete!")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Cleanup failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
