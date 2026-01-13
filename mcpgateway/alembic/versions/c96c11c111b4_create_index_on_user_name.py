# -*- coding: utf-8 -*-
"""Add index on email_users.full_name for search performance

Revision ID: c96c11c111b4
Revises: 77243f5bfce5
Create Date: 2026-01-13 19:23:33.138318

This migration adds an index on email_users.full_name to speed up user search
queries that filter by name. The index improves performance for:
- User search in admin UI (/admin/users/search)
- Team member selection searches
- Any ILIKE queries on full_name field

Note: This is a standard B-tree index that works with both SQLite and PostgreSQL.
For PostgreSQL production deployments with large user bases (>10k users), consider
upgrading to a trigram index (pg_trgm) or functional index on lower(full_name)
for better case-insensitive search performance.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "c96c11c111b4"
down_revision: Union[str, Sequence[str], None] = "77243f5bfce5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(table_name: str, index_name: str) -> bool:
    """Check if an index exists on a table.

    Args:
        table_name: Name of the table
        index_name: Name of the index to check

    Returns:
        True if index exists, False otherwise
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
        index_name: Name for the new index
        table_name: Table to create index on
        columns: List of column names to index
        unique: Whether the index should be unique

    Returns:
        True if index was created, False if it already existed
    """
    if _index_exists(table_name, index_name):
        return False

    op.create_index(index_name, table_name, columns, unique=unique)
    return True


def _drop_index_safe(index_name: str, table_name: str) -> bool:
    """Drop an index only if it exists.

    Args:
        index_name: Name of the index to drop
        table_name: Table the index is on

    Returns:
        True if index was dropped, False if it didn't exist
    """
    if not _index_exists(table_name, index_name):
        return False

    op.drop_index(index_name, table_name=table_name)
    return True


def upgrade() -> None:
    """Add index on email_users.full_name for search performance."""
    _create_index_safe("ix_email_users_full_name", "email_users", ["full_name"], unique=False)


def downgrade() -> None:
    """Remove index on email_users.full_name."""
    _drop_index_safe("ix_email_users_full_name", "email_users")
