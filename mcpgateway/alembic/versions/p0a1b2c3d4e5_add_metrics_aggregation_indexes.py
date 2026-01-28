# -*- coding: utf-8 -*-
"""add metrics aggregation indexes

Revision ID: p0a1b2c3d4e5
Revises: o9i0j1k2l3m4
Create Date: 2025-12-24 16:00:00.000000

This migration adds composite indexes on (entity_id, is_success) columns
to metrics tables to improve aggregation query performance.

The aggregate_metrics() functions perform COUNT and SUM operations grouped
by is_success status. Without these indexes, these queries require full
table scans which causes performance degradation under load.

New indexes added:
- idx_tool_metrics_tool_is_success: (tool_id, is_success)
- idx_resource_metrics_resource_is_success: (resource_id, is_success)
- idx_prompt_metrics_prompt_is_success: (prompt_id, is_success)
- idx_server_metrics_server_is_success: (server_id, is_success)
- idx_a2a_agent_metrics_agent_is_success: (a2a_agent_id, is_success)

See GitHub Issue #1734 for details.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "p0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "o9i0j1k2l3m4"
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
    """Create an index if it doesn't already exist.

    Args:
        index_name: Name for the new index
        table_name: Table to create index on
        columns: List of column names for the index
        unique: Whether to create a unique index

    Returns:
        True if index was created, False if it already existed
    """
    if _index_exists(table_name, index_name):
        print(f"  ⏭️  Index {index_name} already exists on {table_name}")
        return False

    try:
        op.create_index(index_name, table_name, columns, unique=unique)
        print(f"  ✓ Created index {index_name} on {table_name} ({', '.join(columns)})")
        return True
    except Exception as e:
        print(f"  ⚠️  Failed to create index {index_name} on {table_name}: {e}")
        return False


def _drop_index_safe(index_name: str, table_name: str) -> bool:
    """Drop an index if it exists.

    Args:
        index_name: Name of the index to drop
        table_name: Table the index is on

    Returns:
        True if index was dropped, False if it didn't exist
    """
    if not _index_exists(table_name, index_name):
        print(f"  ⏭️  Index {index_name} does not exist on {table_name}")
        return False

    try:
        op.drop_index(index_name, table_name=table_name)
        print(f"  ✓ Dropped index {index_name} from {table_name}")
        return True
    except Exception as e:
        print(f"  ⚠️  Failed to drop index {index_name} from {table_name}: {e}")
        return False


def upgrade() -> None:
    """Add composite indexes for metrics aggregation queries."""
    print("\n=== Adding Metrics Aggregation Indexes ===\n")

    # Tool metrics: (tool_id, is_success) for aggregation queries
    _create_index_safe(
        "idx_tool_metrics_tool_is_success",
        "tool_metrics",
        ["tool_id", "is_success"],
    )

    # Resource metrics: (resource_id, is_success) for aggregation queries
    _create_index_safe(
        "idx_resource_metrics_resource_is_success",
        "resource_metrics",
        ["resource_id", "is_success"],
    )

    # Prompt metrics: (prompt_id, is_success) for aggregation queries
    _create_index_safe(
        "idx_prompt_metrics_prompt_is_success",
        "prompt_metrics",
        ["prompt_id", "is_success"],
    )

    # Server metrics: (server_id, is_success) for aggregation queries
    _create_index_safe(
        "idx_server_metrics_server_is_success",
        "server_metrics",
        ["server_id", "is_success"],
    )

    # A2A Agent metrics: (a2a_agent_id, is_success) for aggregation queries
    _create_index_safe(
        "idx_a2a_agent_metrics_agent_is_success",
        "a2a_agent_metrics",
        ["a2a_agent_id", "is_success"],
    )

    print("\n=== Metrics Aggregation Indexes Complete ===\n")


def downgrade() -> None:
    """Remove composite indexes for metrics aggregation queries."""
    print("\n=== Removing Metrics Aggregation Indexes ===\n")

    _drop_index_safe("idx_a2a_agent_metrics_agent_is_success", "a2a_agent_metrics")
    _drop_index_safe("idx_server_metrics_server_is_success", "server_metrics")
    _drop_index_safe("idx_prompt_metrics_prompt_is_success", "prompt_metrics")
    _drop_index_safe("idx_resource_metrics_resource_is_success", "resource_metrics")
    _drop_index_safe("idx_tool_metrics_tool_is_success", "tool_metrics")

    print("\n=== Metrics Aggregation Indexes Removal Complete ===\n")
