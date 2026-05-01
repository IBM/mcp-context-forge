# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/20a0e0538ac5_add_composite_indexes_for_metrics_time_.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

add_composite_indexes_for_metrics_time_partitioning

Revision ID: 20a0e0538ac5
Revises: 64acf94cb7f2
Create Date: 2026-03-13 17:16:05.005732

Adds composite indexes on (entity_id, timestamp) columns to raw metrics tables
for optimized time-partitioned queries. These indexes improve performance for
queries like: WHERE tool_id = ? AND timestamp >= current_hour_start

Particularly beneficial for PostgreSQL deployments. SQLite can also use these
indexes but has good performance with single-column indexes via index intersection.

Indexes added:
- idx_tool_metrics_tool_id_timestamp: (tool_id, timestamp)
- idx_resource_metrics_resource_id_timestamp: (resource_id, timestamp)
- idx_prompt_metrics_prompt_id_timestamp: (prompt_id, timestamp)
- idx_server_metrics_server_id_timestamp: (server_id, timestamp)

Related to PR #3649 - Performance optimization for metrics aggregation.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20a0e0538ac5"
down_revision: Union[str, Sequence[str], None] = "abf8ac3b6008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(table_name: str, index_name: str) -> bool:
    """
    Check if an index exists on a table.

    Args:
        table_name (str): Name of the table to check.
        index_name (str): Name of the index to check.

    Returns:
        bool: True if the index exists, False otherwise.
    """
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        existing_indexes = inspector.get_indexes(table_name)
        return any(idx["name"] == index_name for idx in existing_indexes)
    except Exception:
        return False


def _table_exists(table_name: str) -> bool:
    """
    Check if a table exists.

    Args:
        table_name (str): Name of the table to check.

    Returns:
        bool: True if the table exists, False otherwise.
    """
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        return table_name in inspector.get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    """Upgrade schema."""
    # SQLite has limited ALTER TABLE support. The column type is already functionally
    # equivalent (JSON stored as TEXT in SQLite).

    # Add composite indexes for time-partitioned metrics queries
    # These improve performance for queries like: WHERE entity_id = ? AND timestamp >= ?

    # Tool metrics: (tool_id, timestamp)
    if _table_exists("tool_metrics") and not _index_exists("tool_metrics", "idx_tool_metrics_tool_id_timestamp"):
        op.create_index("idx_tool_metrics_tool_id_timestamp", "tool_metrics", ["tool_id", "timestamp"], unique=False)

    # Resource metrics: (resource_id, timestamp)
    if _table_exists("resource_metrics") and not _index_exists("resource_metrics", "idx_resource_metrics_resource_id_timestamp"):
        op.create_index("idx_resource_metrics_resource_id_timestamp", "resource_metrics", ["resource_id", "timestamp"], unique=False)

    # Prompt metrics: (prompt_id, timestamp)
    if _table_exists("prompt_metrics") and not _index_exists("prompt_metrics", "idx_prompt_metrics_prompt_id_timestamp"):
        op.create_index("idx_prompt_metrics_prompt_id_timestamp", "prompt_metrics", ["prompt_id", "timestamp"], unique=False)

    # Server metrics: (server_id, timestamp)
    if _table_exists("server_metrics") and not _index_exists("server_metrics", "idx_server_metrics_server_id_timestamp"):
        op.create_index("idx_server_metrics_server_id_timestamp", "server_metrics", ["server_id", "timestamp"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop composite indexes
    if _table_exists("server_metrics") and _index_exists("server_metrics", "idx_server_metrics_server_id_timestamp"):
        op.drop_index("idx_server_metrics_server_id_timestamp", table_name="server_metrics")

    if _table_exists("prompt_metrics") and _index_exists("prompt_metrics", "idx_prompt_metrics_prompt_id_timestamp"):
        op.drop_index("idx_prompt_metrics_prompt_id_timestamp", table_name="prompt_metrics")

    if _table_exists("resource_metrics") and _index_exists("resource_metrics", "idx_resource_metrics_resource_id_timestamp"):
        op.drop_index("idx_resource_metrics_resource_id_timestamp", table_name="resource_metrics")

    if _table_exists("tool_metrics") and _index_exists("tool_metrics", "idx_tool_metrics_tool_id_timestamp"):
        op.drop_index("idx_tool_metrics_tool_id_timestamp", table_name="tool_metrics")
