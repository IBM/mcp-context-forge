# -*- coding: utf-8 -*-
"""Add indexes for cursor pagination

Revision ID: 4f07c116f917
Revises: q1b2c3d4e5f6
Create Date: 2025-12-29 15:00:00.000000

This migration adds composite indexes on (created_at, id) for cursor-based
pagination. These indexes enable efficient keyset pagination for large datasets
by supporting WHERE (created_at < ? OR (created_at = ? AND id < ?)) queries.

Indexes added:
- idx_resources_created_at_id: For resources table pagination
- idx_prompts_created_at_id: For prompts table pagination
- idx_servers_created_at_id: For servers table pagination
- idx_gateways_created_at_id: For gateways table pagination
- idx_a2a_agents_created_at_id: For a2a_agents table pagination

Note: The tools table already has idx_tools_created_at_id from a previous migration.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "4f07c116f917"
down_revision: Union[str, Sequence[str], None] = "q1b2c3d4e5f6"
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
    """Add composite indexes on (created_at, id) for cursor pagination."""
    print("\n" + "=" * 80)
    print("Adding Cursor Pagination Indexes")
    print("=" * 80)

    print("\n--- Composite indexes for keyset pagination ---")
    _create_index_safe("idx_resources_created_at_id", "resources", ["created_at", "id"])
    _create_index_safe("idx_prompts_created_at_id", "prompts", ["created_at", "id"])
    _create_index_safe("idx_servers_created_at_id", "servers", ["created_at", "id"])
    _create_index_safe("idx_gateways_created_at_id", "gateways", ["created_at", "id"])
    _create_index_safe("idx_a2a_agents_created_at_id", "a2a_agents", ["created_at", "id"])

    print("\n✓ Cursor pagination indexes migration complete")


def downgrade() -> None:
    """Remove composite indexes on (created_at, id)."""
    print("\n" + "=" * 80)
    print("Removing Cursor Pagination Indexes")
    print("=" * 80)

    _drop_index_safe("idx_a2a_agents_created_at_id", "a2a_agents")
    _drop_index_safe("idx_gateways_created_at_id", "gateways")
    _drop_index_safe("idx_servers_created_at_id", "servers")
    _drop_index_safe("idx_prompts_created_at_id", "prompts")
    _drop_index_safe("idx_resources_created_at_id", "resources")

    print("\n✓ Cursor pagination indexes downgrade complete")
