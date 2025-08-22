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
        # Create a2a_agents table
        op.create_table(
            "a2a_agents",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("slug", sa.String(), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("endpoint_url", sa.String(), nullable=False),
            sa.Column("agent_type", sa.String(), nullable=False, server_default="generic"),
            sa.Column("protocol_version", sa.String(), nullable=False, server_default="1.0"),
            sa.Column("capabilities", sa.JSON(), server_default="{}"),
            sa.Column("config", sa.JSON(), server_default="{}"),
            sa.Column("auth_type", sa.String()),
            sa.Column("auth_value", sa.Text()),
            sa.Column("enabled", sa.Boolean(), server_default="1"),
            sa.Column("reachable", sa.Boolean(), server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_interaction", sa.DateTime(timezone=True)),
            sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("created_by", sa.String()),
            sa.Column("created_from_ip", sa.String()),
            sa.Column("created_via", sa.String()),
            sa.Column("created_user_agent", sa.Text()),
            sa.Column("modified_by", sa.String()),
            sa.Column("modified_from_ip", sa.String()),
            sa.Column("modified_via", sa.String()),
            sa.Column("modified_user_agent", sa.Text()),
            sa.Column("import_batch_id", sa.String()),
            sa.Column("federation_source", sa.String()),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        )

        # Create unique constraints
        op.create_unique_constraint("uq_a2a_agents_name", "a2a_agents", ["name"])
        op.create_unique_constraint("uq_a2a_agents_slug", "a2a_agents", ["slug"])

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
            sa.Column("interaction_type", sa.String(), nullable=False, server_default="invoke"),
        )

    if "server_a2a_association" not in existing_tables:
        # Create server_a2a_association table
        op.create_table(
            "server_a2a_association",
            sa.Column("server_id", sa.String(), sa.ForeignKey("servers.id"), primary_key=True),
            sa.Column("a2a_agent_id", sa.String(), sa.ForeignKey("a2a_agents.id"), primary_key=True),
        )

    # Create indexes for performance (check if they exist first)
    existing_indexes = []
    try:
        existing_indexes = [idx["name"] for idx in inspector.get_indexes("a2a_agents")]
    except Exception:
        pass

    if "idx_a2a_agents_enabled" not in existing_indexes:
        try:
            op.create_index("idx_a2a_agents_enabled", "a2a_agents", ["enabled"])
        except Exception:
            pass

    if "idx_a2a_agents_agent_type" not in existing_indexes:
        try:
            op.create_index("idx_a2a_agents_agent_type", "a2a_agents", ["agent_type"])
        except Exception:
            pass

    # Metrics table indexes
    try:
        existing_indexes = [idx["name"] for idx in inspector.get_indexes("a2a_agent_metrics")]
        if "idx_a2a_agent_metrics_agent_id" not in existing_indexes:
            op.create_index("idx_a2a_agent_metrics_agent_id", "a2a_agent_metrics", ["a2a_agent_id"])
        if "idx_a2a_agent_metrics_timestamp" not in existing_indexes:
            op.create_index("idx_a2a_agent_metrics_timestamp", "a2a_agent_metrics", ["timestamp"])
    except Exception:
        pass

    # Create GIN indexes for tags on PostgreSQL (ignored on SQLite)
    try:
        if "idx_a2a_agents_tags" not in existing_indexes:
            op.create_index("idx_a2a_agents_tags", "a2a_agents", ["tags"], postgresql_using="gin")
    except Exception:  # nosec B110 - database compatibility
        pass  # SQLite doesn't support GIN indexes


def downgrade() -> None:
    """Reverse the A2A agents and metrics tables."""

    # Drop indexes first
    try:
        op.drop_index("idx_a2a_agents_tags", "a2a_agents")
    except Exception:  # nosec B110 - database compatibility
        pass

    op.drop_index("idx_a2a_agent_metrics_timestamp", "a2a_agent_metrics")
    op.drop_index("idx_a2a_agent_metrics_agent_id", "a2a_agent_metrics")
    op.drop_index("idx_a2a_agents_agent_type", "a2a_agents")
    op.drop_index("idx_a2a_agents_enabled", "a2a_agents")

    # Drop tables
    op.drop_table("server_a2a_association")
    op.drop_table("a2a_agent_metrics")
    op.drop_table("a2a_agents")
