# -*- coding: utf-8 -*-
"""add a2a agents performance indexes

Revision ID: o9i0j1k2l3m4
Revises: n8h9i0j1k2l3
Create Date: 2025-12-23 14:00:00.000000

This migration adds additional indexes to the a2a_agents table to improve
query performance. These indexes address the 100% sequential scan rate
observed during load testing.

New indexes added (not in previous migration n8h9i0j1k2l3):
- idx_a2a_agents_name: For lookup by agent name (WHERE name = ?)
- idx_a2a_agents_enabled: For filtering active agents (WHERE enabled = true)
- idx_a2a_agents_visibility: Single-column for visibility queries
- idx_a2a_agents_slug: For slug lookups (WHERE slug = ?)
- idx_a2a_agents_slug_visibility: Composite for slug+visibility queries

Note: Migration n8h9i0j1k2l3 already defines these indexes:
- idx_a2a_agents_team_id
- idx_a2a_agents_team_visibility_active_created
- idx_a2a_agents_visibility_active_created
This migration only adds the NEW indexes listed above.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "o9i0j1k2l3m4"
down_revision: Union[str, Sequence[str], None] = "n8h9i0j1k2l3"
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
        print(f"⚠️  Skipping {index_name}: Index already exists on {table_name}")
        return False

    op.create_index(index_name, table_name, columns, unique=unique)
    print(f"✓ Created index {index_name} on {table_name}({', '.join(columns)})")
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
        print(f"⚠️  Skipping drop of {index_name}: Index does not exist on {table_name}")
        return False

    op.drop_index(index_name, table_name=table_name)
    print(f"✓ Dropped index {index_name} from {table_name}")
    return True


def upgrade() -> None:
    """Add performance indexes to a2a_agents table."""
    print("\n" + "=" * 80)
    print("Adding A2A Agents Performance Indexes")
    print("=" * 80)

    # Single-column indexes for common filter operations
    print("\n--- Single-column indexes ---")
    _create_index_safe("idx_a2a_agents_name", "a2a_agents", ["name"])
    _create_index_safe("idx_a2a_agents_enabled", "a2a_agents", ["enabled"])
    _create_index_safe("idx_a2a_agents_visibility", "a2a_agents", ["visibility"])
    _create_index_safe("idx_a2a_agents_slug", "a2a_agents", ["slug"])

    # Composite index for slug + visibility queries
    print("\n--- Composite indexes ---")
    _create_index_safe("idx_a2a_agents_slug_visibility", "a2a_agents", ["slug", "visibility"])

    print("\n✓ A2A Agents indexes migration complete")


def downgrade() -> None:
    """Remove a2a_agents performance indexes added by this migration."""
    print("\n" + "=" * 80)
    print("Removing A2A Agents Performance Indexes")
    print("=" * 80)

    # Remove composite index
    _drop_index_safe("idx_a2a_agents_slug_visibility", "a2a_agents")

    # Remove single-column indexes
    _drop_index_safe("idx_a2a_agents_slug", "a2a_agents")
    _drop_index_safe("idx_a2a_agents_visibility", "a2a_agents")
    _drop_index_safe("idx_a2a_agents_enabled", "a2a_agents")
    _drop_index_safe("idx_a2a_agents_name", "a2a_agents")

    print("\n✓ A2A Agents indexes downgrade complete")
