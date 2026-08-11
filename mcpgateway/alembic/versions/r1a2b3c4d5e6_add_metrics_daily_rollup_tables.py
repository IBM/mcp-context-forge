# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/r1a2b3c4d5e6_add_metrics_daily_rollup_tables.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add metrics daily rollup tables.
This migration creates daily summary tables for all 5 metric types
(tools, resources, prompts, servers, a2a_agents) by aggregating the
existing hourly rollup tables, so long-term statistics queries read
one row per entity per day instead of scanning months of hourly rows.

Unlike the hourly tables, daily tables intentionally have NO percentile
columns (p50/p95/p99): percentiles cannot be composed across time buckets,
and no query path reads rollup percentiles.
Revision ID: r1a2b3c4d5e6
Revises: d5e6f7a8b9c1
Create Date: 2026-08-11 00:00:00.000000
"""

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "r1a2b3c4d5e6"
down_revision = "d5e6f7a8b9c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create metrics daily rollup tables."""
    # Tool metrics daily
    op.create_table(
        "tool_metrics_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tool_id", sa.String(36), sa.ForeignKey("tools.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("day_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_response_time", sa.Float(), nullable=True),
        sa.Column("max_response_time", sa.Float(), nullable=True),
        sa.Column("avg_response_time", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tool_id", "day_start", name="uq_tool_metrics_daily_tool_day"),
    )
    op.create_index("ix_tool_metrics_daily_day_start", "tool_metrics_daily", ["day_start"])

    # Resource metrics daily
    op.create_table(
        "resource_metrics_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resource_id", sa.String(36), sa.ForeignKey("resources.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("resource_name", sa.String(255), nullable=False),
        sa.Column("day_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_response_time", sa.Float(), nullable=True),
        sa.Column("max_response_time", sa.Float(), nullable=True),
        sa.Column("avg_response_time", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("resource_id", "day_start", name="uq_resource_metrics_daily_resource_day"),
    )
    op.create_index("ix_resource_metrics_daily_day_start", "resource_metrics_daily", ["day_start"])

    # Prompt metrics daily
    op.create_table(
        "prompt_metrics_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("prompt_id", sa.String(36), sa.ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("prompt_name", sa.String(255), nullable=False),
        sa.Column("day_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_response_time", sa.Float(), nullable=True),
        sa.Column("max_response_time", sa.Float(), nullable=True),
        sa.Column("avg_response_time", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("prompt_id", "day_start", name="uq_prompt_metrics_daily_prompt_day"),
    )
    op.create_index("ix_prompt_metrics_daily_day_start", "prompt_metrics_daily", ["day_start"])

    # Server metrics daily
    op.create_table(
        "server_metrics_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("server_id", sa.String(36), sa.ForeignKey("servers.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("server_name", sa.String(255), nullable=False),
        sa.Column("day_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_response_time", sa.Float(), nullable=True),
        sa.Column("max_response_time", sa.Float(), nullable=True),
        sa.Column("avg_response_time", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("server_id", "day_start", name="uq_server_metrics_daily_server_day"),
    )
    op.create_index("ix_server_metrics_daily_day_start", "server_metrics_daily", ["day_start"])

    # A2A agent metrics daily
    op.create_table(
        "a2a_agent_metrics_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("a2a_agent_id", sa.String(36), sa.ForeignKey("a2a_agents.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("agent_name", sa.String(255), nullable=False),
        sa.Column("day_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interaction_type", sa.String(50), nullable=False, server_default="invoke"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_response_time", sa.Float(), nullable=True),
        sa.Column("max_response_time", sa.Float(), nullable=True),
        sa.Column("avg_response_time", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("a2a_agent_id", "day_start", "interaction_type", name="uq_a2a_agent_metrics_daily_agent_day_type"),
    )
    op.create_index("ix_a2a_agent_metrics_daily_day_start", "a2a_agent_metrics_daily", ["day_start"])


def downgrade() -> None:
    """Drop metrics daily rollup tables."""
    op.drop_table("a2a_agent_metrics_daily")
    op.drop_table("server_metrics_daily")
    op.drop_table("prompt_metrics_daily")
    op.drop_table("resource_metrics_daily")
    op.drop_table("tool_metrics_daily")
