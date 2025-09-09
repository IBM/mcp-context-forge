# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/add_a2a_agents_and_metrics.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

add_a2a_agents_and_metrics

Revision ID: add_a2a_agents_and_metrics
Revises: add_oauth_tokens_table
Create Date: 2025-08-19 10:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "add_a2a_agents_and_metrics"
down_revision: Union[str, Sequence[str], None] = "add_oauth_tokens_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add A2A agents and metrics tables."""

    # Check if table already exists (for development scenarios)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "a2a_agents" not in existing_tables:
        # Create a2a_agents table with unique constraints included (SQLite compatible)
        op.create_table(
            "a2a_agents",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(255), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("endpoint_url", sa.String(767), nullable=False),
            sa.Column("agent_type", sa.String(50), nullable=False, server_default="generic"),
            sa.Column("protocol_version", sa.String(10), nullable=False, server_default="1.0"),
            sa.Column("capabilities", sa.JSON(), nullable=True),
            sa.Column("config", sa.JSON(), nullable=True),
            sa.Column("auth_type", sa.String(50)),
            sa.Column("auth_value", sa.Text()),
            sa.Column("enabled", sa.Boolean(), server_default="1"),
            sa.Column("reachable", sa.Boolean(), server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_interaction", sa.DateTime(timezone=True)),
            sa.Column("tags", sa.JSON(), nullable=True),
            sa.Column("created_by", sa.String(255)),
            sa.Column("created_from_ip", sa.String(45)),
            sa.Column("created_via", sa.String(100)),
            sa.Column("created_user_agent", sa.Text()),
            sa.Column("modified_by", sa.String(255)),
            sa.Column("modified_from_ip", sa.String(45)),
            sa.Column("modified_via", sa.String(100)),
            sa.Column("modified_user_agent", sa.Text()),
            sa.Column("import_batch_id", sa.String(36)),
            sa.Column("federation_source", sa.String(255)),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.UniqueConstraint("name", name="uq_a2a_agents_name"),
            sa.UniqueConstraint("slug", name="uq_a2a_agents_slug"),
        )

    if "a2a_agent_metrics" not in existing_tables:
        # Create a2a_agent_metrics table
        op.create_table(
            "a2a_agent_metrics",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("a2a_agent_id", sa.String(36), sa.ForeignKey("a2a_agents.id"), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("response_time", sa.Float(), nullable=False),
            sa.Column("is_success", sa.Boolean(), nullable=False),
            sa.Column("error_message", sa.Text()),
            sa.Column("interaction_type", sa.String(50), nullable=False, server_default="invoke"),
        )

    # Only create association table if both referenced tables exist
    if "server_a2a_association" not in existing_tables and "servers" in existing_tables and "a2a_agents" in existing_tables:
        # Create server_a2a_association table
        op.create_table(
            "server_a2a_association",
            sa.Column("server_id", sa.String(36), sa.ForeignKey("servers.id"), primary_key=True),
            sa.Column("a2a_agent_id", sa.String(36), sa.ForeignKey("a2a_agents.id"), primary_key=True),
        )

    # Create indexes for performance (check if they exist first)
    # Only create indexes if tables were actually created
    if "a2a_agents" in existing_tables:
        try:
            existing_indexes = [idx["name"] for idx in inspector.get_indexes("a2a_agents")]
        except Exception:
            existing_indexes = []

        if "idx_a2a_agents_enabled" not in existing_indexes:
            try:
                op.create_index("idx_a2a_agents_enabled", "a2a_agents", ["enabled"])
            except Exception as e:
                print(f"Warning: Could not create index idx_a2a_agents_enabled: {e}")

        if "idx_a2a_agents_agent_type" not in existing_indexes:
            try:
                op.create_index("idx_a2a_agents_agent_type", "a2a_agents", ["agent_type"])
            except Exception as e:
                print(f"Warning: Could not create index idx_a2a_agents_agent_type: {e}")

        # Create B-tree index for tags (safer than GIN, works on both PostgreSQL and SQLite)
        if "idx_a2a_agents_tags" not in existing_indexes:
            try:
                op.create_index("idx_a2a_agents_tags", "a2a_agents", ["tags"])
            except Exception as e:
                print(f"Warning: Could not create index idx_a2a_agents_tags: {e}")

    # Metrics table indexes
    if "a2a_agent_metrics" in existing_tables:
        try:
            existing_metrics_indexes = [idx["name"] for idx in inspector.get_indexes("a2a_agent_metrics")]
        except Exception:
            existing_metrics_indexes = []

        if "idx_a2a_agent_metrics_agent_id" not in existing_metrics_indexes:
            try:
                op.create_index("idx_a2a_agent_metrics_agent_id", "a2a_agent_metrics", ["a2a_agent_id"])
            except Exception as e:
                print(f"Warning: Could not create index idx_a2a_agent_metrics_agent_id: {e}")

        if "idx_a2a_agent_metrics_timestamp" not in existing_metrics_indexes:
            try:
                op.create_index("idx_a2a_agent_metrics_timestamp", "a2a_agent_metrics", ["timestamp"])
            except Exception as e:
                print(f"Warning: Could not create index idx_a2a_agent_metrics_timestamp: {e}")


def downgrade() -> None:
    """Reverse the A2A agents and metrics tables."""
    # Check if tables exist before trying to drop indexes/tables
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # Drop indexes first (if they exist)
    if "a2a_agents" in existing_tables:
        try:
            existing_indexes = [idx["name"] for idx in inspector.get_indexes("a2a_agents")]

            for index_name in ["idx_a2a_agents_tags", "idx_a2a_agents_agent_type", "idx_a2a_agents_enabled"]:
                if index_name in existing_indexes:
                    try:
                        op.drop_index(index_name, "a2a_agents")
                    except Exception as e:
                        print(f"Warning: Could not drop index {index_name}: {e}")
        except Exception as e:
            print(f"Warning: Could not get indexes for a2a_agents: {e}")

    if "a2a_agent_metrics" in existing_tables:
        try:
            existing_metrics_indexes = [idx["name"] for idx in inspector.get_indexes("a2a_agent_metrics")]

            for index_name in ["idx_a2a_agent_metrics_timestamp", "idx_a2a_agent_metrics_agent_id"]:
                if index_name in existing_metrics_indexes:
                    try:
                        op.drop_index(index_name, "a2a_agent_metrics")
                    except Exception as e:
                        print(f"Warning: Could not drop index {index_name}: {e}")
        except Exception as e:
            print(f"Warning: Could not get indexes for a2a_agent_metrics: {e}")

    # Drop tables (if they exist)
    for table_name in ["server_a2a_association", "a2a_agent_metrics", "a2a_agents"]:
        if table_name in existing_tables:
            try:
                op.drop_table(table_name)
            except Exception as e:
                print(f"Warning: Could not drop table {table_name}: {e}")
