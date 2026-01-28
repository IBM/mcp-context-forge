# -*- coding: utf-8 -*-
"""Add metrics hourly rollup tables.

This migration creates hourly summary tables for all 5 metric types
(tools, resources, prompts, servers, a2a_agents) to enable efficient
historical queries without scanning millions of raw metrics.

Revision ID: q1b2c3d4e5f6
Revises: p0a1b2c3d4e5
Create Date: 2025-01-01 00:00:00.000000

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "q1b2c3d4e5f6"
down_revision = "p0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create metrics hourly rollup tables."""
    # Tool metrics hourly
    op.create_table(
        "tool_metrics_hourly",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tool_id", sa.String(36), sa.ForeignKey("tools.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("hour_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_response_time", sa.Float(), nullable=True),
        sa.Column("max_response_time", sa.Float(), nullable=True),
        sa.Column("avg_response_time", sa.Float(), nullable=True),
        sa.Column("p50_response_time", sa.Float(), nullable=True),
        sa.Column("p95_response_time", sa.Float(), nullable=True),
        sa.Column("p99_response_time", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tool_id", "hour_start", name="uq_tool_metrics_hourly_tool_hour"),
    )
    op.create_index("ix_tool_metrics_hourly_hour_start", "tool_metrics_hourly", ["hour_start"])

    # Resource metrics hourly
    op.create_table(
        "resource_metrics_hourly",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resource_id", sa.String(36), sa.ForeignKey("resources.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("resource_name", sa.String(255), nullable=False),
        sa.Column("hour_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_response_time", sa.Float(), nullable=True),
        sa.Column("max_response_time", sa.Float(), nullable=True),
        sa.Column("avg_response_time", sa.Float(), nullable=True),
        sa.Column("p50_response_time", sa.Float(), nullable=True),
        sa.Column("p95_response_time", sa.Float(), nullable=True),
        sa.Column("p99_response_time", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("resource_id", "hour_start", name="uq_resource_metrics_hourly_resource_hour"),
    )
    op.create_index("ix_resource_metrics_hourly_hour_start", "resource_metrics_hourly", ["hour_start"])

    # Prompt metrics hourly
    op.create_table(
        "prompt_metrics_hourly",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("prompt_id", sa.String(36), sa.ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("prompt_name", sa.String(255), nullable=False),
        sa.Column("hour_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_response_time", sa.Float(), nullable=True),
        sa.Column("max_response_time", sa.Float(), nullable=True),
        sa.Column("avg_response_time", sa.Float(), nullable=True),
        sa.Column("p50_response_time", sa.Float(), nullable=True),
        sa.Column("p95_response_time", sa.Float(), nullable=True),
        sa.Column("p99_response_time", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("prompt_id", "hour_start", name="uq_prompt_metrics_hourly_prompt_hour"),
    )
    op.create_index("ix_prompt_metrics_hourly_hour_start", "prompt_metrics_hourly", ["hour_start"])

    # Server metrics hourly
    op.create_table(
        "server_metrics_hourly",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("server_id", sa.String(36), sa.ForeignKey("servers.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("server_name", sa.String(255), nullable=False),
        sa.Column("hour_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_response_time", sa.Float(), nullable=True),
        sa.Column("max_response_time", sa.Float(), nullable=True),
        sa.Column("avg_response_time", sa.Float(), nullable=True),
        sa.Column("p50_response_time", sa.Float(), nullable=True),
        sa.Column("p95_response_time", sa.Float(), nullable=True),
        sa.Column("p99_response_time", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("server_id", "hour_start", name="uq_server_metrics_hourly_server_hour"),
    )
    op.create_index("ix_server_metrics_hourly_hour_start", "server_metrics_hourly", ["hour_start"])

    # A2A agent metrics hourly
    op.create_table(
        "a2a_agent_metrics_hourly",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("a2a_agent_id", sa.String(36), sa.ForeignKey("a2a_agents.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("agent_name", sa.String(255), nullable=False),
        sa.Column("hour_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interaction_type", sa.String(50), nullable=False, server_default="invoke"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_response_time", sa.Float(), nullable=True),
        sa.Column("max_response_time", sa.Float(), nullable=True),
        sa.Column("avg_response_time", sa.Float(), nullable=True),
        sa.Column("p50_response_time", sa.Float(), nullable=True),
        sa.Column("p95_response_time", sa.Float(), nullable=True),
        sa.Column("p99_response_time", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("a2a_agent_id", "hour_start", "interaction_type", name="uq_a2a_agent_metrics_hourly_agent_hour_type"),
    )
    op.create_index("ix_a2a_agent_metrics_hourly_hour_start", "a2a_agent_metrics_hourly", ["hour_start"])


def downgrade() -> None:
    """Drop metrics hourly rollup tables."""
    op.drop_table("a2a_agent_metrics_hourly")
    op.drop_table("server_metrics_hourly")
    op.drop_table("prompt_metrics_hourly")
    op.drop_table("resource_metrics_hourly")
    op.drop_table("tool_metrics_hourly")
