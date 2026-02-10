# -*- coding: utf-8 -*-
"""Add index for team name

Revision ID: 5f3c681b05e1
Revises: t4d5e6f7g8h9
Create Date: 2026-01-14 19:27:40.346276

This migration adds a composite index on (name, id) for the email_teams table
to optimize search and deterministic cursor-based pagination.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "5f3c681b05e1"
down_revision: Union[str, Sequence[str], None] = "t4d5e6f7g8h9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(table_name: str, index_name: str) -> bool:
    """Check if an index exists on a table.

    Args:
        table_name: Name of the table to check.
        index_name: Name of the index to look for.

    Returns:
        True if the index exists, False otherwise.
    """
    conn = op.get_bind()
    inspector = inspect(conn)

    try:
        existing_indexes = inspector.get_indexes(table_name)
        return any(idx["name"] == index_name for idx in existing_indexes)
    except Exception:
        return False


def _create_index_safe(index_name: str, table_name: str, columns: list[str], unique: bool = False) -> bool:
    """Create an index only if it doesn't already exist.

    Args:
        index_name: Name of the index to create.
        table_name: Name of the table to create the index on.
        columns: List of column names to include in the index.
        unique: Whether the index should enforce uniqueness.

    Returns:
        True if the index was created, False if it already existed.
    """
    if _index_exists(table_name, index_name):
        print(f"⚠️  Skipping {index_name}: Index already exists on {table_name}")
        return False

    op.create_index(index_name, table_name, columns, unique=unique)
    print(f"✓ Created index {index_name} on {table_name}({', '.join(columns)})")
    return True


def _drop_index_safe(index_name: str, table_name: str) -> bool:
    """Drop an index only if it exists.

    Args:
        index_name: Name of the index to drop.
        table_name: Name of the table containing the index.

    Returns:
        True if the index was dropped, False if it did not exist.
    """
    if not _index_exists(table_name, index_name):
        print(f"⚠️  Skipping drop of {index_name}: Index does not exist on {table_name}")
        return False

    op.drop_index(index_name, table_name=table_name)
    print(f"✓ Dropped index {index_name} from {table_name}")
    return True


def upgrade() -> None:
    """Add composite index on (name, id) for team search and pagination."""
    _create_index_safe("ix_email_teams_name_id", "email_teams", ["name", "id"])


def downgrade() -> None:
    """Remove composite index on (name, id)."""
    _drop_index_safe("ix_email_teams_name_id", "email_teams")
