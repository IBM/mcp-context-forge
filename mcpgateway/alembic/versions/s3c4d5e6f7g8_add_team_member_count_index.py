# -*- coding: utf-8 -*-
"""Add partial index for team member count queries

Revision ID: s3c4d5e6f7g8
Revises: r2b3c4d5e6f7
Create Date: 2026-01-04

This migration adds a partial index on email_team_members to optimize the
batch member count queries used by get_member_counts_batch(). The index
covers the WHERE is_active = true condition used in those queries.

For PostgreSQL, this uses a partial index which is most efficient.
For SQLite/MySQL, a composite index is used as partial indexes are not supported.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "s3c4d5e6f7g8"
down_revision: Union[str, Sequence[str], None] = "r2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(table_name: str, index_name: str) -> bool:
    """Check if an index already exists.

    Args:
        table_name: Name of the table to check
        index_name: Name of the index to look for

    Returns:
        True if the index exists, False otherwise
    """
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        existing = inspector.get_indexes(table_name)
        return any(idx["name"] == index_name for idx in existing)
    except Exception:
        return False


def upgrade() -> None:
    """Add partial index for team member count queries."""
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        # PostgreSQL: Use partial index (most efficient for WHERE is_active = true)
        # Note: NOT using CONCURRENTLY since that requires running outside transaction
        # For production with large tables, consider running CONCURRENTLY manually:
        #   CREATE INDEX CONCURRENTLY idx_email_team_members_team_active_partial
        #   ON email_team_members(team_id) WHERE is_active = true;
        if not _index_exists("email_team_members", "idx_email_team_members_team_active_partial"):
            op.execute(
                """
                CREATE INDEX idx_email_team_members_team_active_partial
                ON email_team_members(team_id)
                WHERE is_active = true
            """
            )
            print("Created partial index idx_email_team_members_team_active_partial")
    else:
        # SQLite/MySQL: Regular composite index (no partial index support)
        if not _index_exists("email_team_members", "idx_email_team_members_team_active_count"):
            op.create_index(
                "idx_email_team_members_team_active_count",
                "email_team_members",
                ["team_id", "is_active"],
            )
            print("Created composite index idx_email_team_members_team_active_count")


def downgrade() -> None:
    """Remove the partial index."""
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_email_team_members_team_active_partial")
    else:
        try:
            op.drop_index("idx_email_team_members_team_active_count", "email_team_members")
        except Exception:  # nosec B110 - Index may not exist during downgrade
            pass
