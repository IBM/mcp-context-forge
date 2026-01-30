# -*- coding: utf-8 -*-
"""add metrics composite indexes

Revision ID: p0j1k2l3m4n5
Revises: o9i0j1k2l3m4
Create Date: 2026-01-30 12:00:00.000000

This migration adds composite indexes on metrics tables for efficient
aggregation queries. Without these indexes, aggregation queries perform
full table scans when filtering by entity_id and is_success.

New composite indexes:
- idx_tool_metrics_tool_is_success: (tool_id, is_success) on tool_metrics
- idx_resource_metrics_resource_is_success: (resource_id, is_success) on resource_metrics
- idx_prompt_metrics_prompt_is_success: (prompt_id, is_success) on prompt_metrics
- idx_server_metrics_server_is_success: (server_id, is_success) on server_metrics
- idx_a2a_agent_metrics_agent_is_success: (a2a_agent_id, is_success) on a2a_agent_metrics

New timestamp indexes for metrics cleanup:
- idx_tool_metrics_timestamp: (timestamp) on tool_metrics
- idx_resource_metrics_timestamp: (timestamp) on resource_metrics
- idx_prompt_metrics_timestamp: (timestamp) on prompt_metrics
- idx_server_metrics_timestamp: (timestamp) on server_metrics
- idx_a2a_agent_metrics_timestamp: (timestamp) on a2a_agent_metrics
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "p0j1k2l3m4n5"
down_revision: Union[str, Sequence[str], None] = "o9i0j1k2l3m4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(table_name: str, index_name: str) -> bool:
    """Check if an index exists on a table."""
    conn = op.get_bind()
    inspector = inspect(conn)

    try:
        existing_indexes = inspector.get_indexes(table_name)
        return any(idx["name"] == index_name for idx in existing_indexes)
    except Exception:
        return False


def _create_index_safe(index_name: str, table_name: str, columns: list[str]) -> bool:
    """Create an index only if it doesn't already exist."""
    if _index_exists(table_name, index_name):
        print(f"  Skipping {index_name}: Index already exists on {table_name}")
        return False

    op.create_index(index_name, table_name, columns)
    print(f"  Created index {index_name} on {table_name}({', '.join(columns)})")
    return True


def _drop_index_safe(index_name: str, table_name: str) -> bool:
    """Drop an index only if it exists."""
    if not _index_exists(table_name, index_name):
        print(f"  Skipping drop of {index_name}: Index does not exist on {table_name}")
        return False

    op.drop_index(index_name, table_name=table_name)
    print(f"  Dropped index {index_name} from {table_name}")
    return True


def upgrade() -> None:
    """Add composite and timestamp indexes to metrics tables."""
    print("\n" + "=" * 80)
    print("Adding Metrics Composite Indexes for Aggregation Performance")
    print("=" * 80)

    # Composite indexes for aggregation queries (entity_id, is_success)
    print("\n--- Composite indexes for aggregation ---")
    _create_index_safe("idx_tool_metrics_tool_is_success", "tool_metrics", ["tool_id", "is_success"])
    _create_index_safe("idx_resource_metrics_resource_is_success", "resource_metrics", ["resource_id", "is_success"])
    _create_index_safe("idx_prompt_metrics_prompt_is_success", "prompt_metrics", ["prompt_id", "is_success"])
    _create_index_safe("idx_server_metrics_server_is_success", "server_metrics", ["server_id", "is_success"])
    _create_index_safe("idx_a2a_agent_metrics_agent_is_success", "a2a_agent_metrics", ["a2a_agent_id", "is_success"])

    # Timestamp indexes for cleanup queries and time-range filtering
    print("\n--- Timestamp indexes for cleanup ---")
    _create_index_safe("idx_tool_metrics_timestamp", "tool_metrics", ["timestamp"])
    _create_index_safe("idx_resource_metrics_timestamp", "resource_metrics", ["timestamp"])
    _create_index_safe("idx_prompt_metrics_timestamp", "prompt_metrics", ["timestamp"])
    _create_index_safe("idx_server_metrics_timestamp", "server_metrics", ["timestamp"])
    _create_index_safe("idx_a2a_agent_metrics_timestamp", "a2a_agent_metrics", ["timestamp"])

    print("\n  Metrics indexes migration complete")


def downgrade() -> None:
    """Remove metrics composite and timestamp indexes."""
    print("\n" + "=" * 80)
    print("Removing Metrics Composite Indexes")
    print("=" * 80)

    # Remove timestamp indexes
    _drop_index_safe("idx_a2a_agent_metrics_timestamp", "a2a_agent_metrics")
    _drop_index_safe("idx_server_metrics_timestamp", "server_metrics")
    _drop_index_safe("idx_prompt_metrics_timestamp", "prompt_metrics")
    _drop_index_safe("idx_resource_metrics_timestamp", "resource_metrics")
    _drop_index_safe("idx_tool_metrics_timestamp", "tool_metrics")

    # Remove composite indexes
    _drop_index_safe("idx_a2a_agent_metrics_agent_is_success", "a2a_agent_metrics")
    _drop_index_safe("idx_server_metrics_server_is_success", "server_metrics")
    _drop_index_safe("idx_prompt_metrics_prompt_is_success", "prompt_metrics")
    _drop_index_safe("idx_resource_metrics_resource_is_success", "resource_metrics")
    _drop_index_safe("idx_tool_metrics_tool_is_success", "tool_metrics")

    print("\n  Metrics indexes downgrade complete")
