# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/592625561893_add_tool_plugin_bindings_table.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Add tool_plugin_bindings table for per-tool per-tenant plugin policies

Revision ID: 592625561893
Revises: cbedf4e580e0
Create Date: 2026-04-03 00:00:00.000000
"""

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "592625561893"  # pragma: allowlist secret
down_revision = "cbedf4e580e0"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create tool_plugin_bindings table if it does not already exist."""
    inspector = sa.inspect(op.get_bind())

    if "tool_plugin_bindings" in inspector.get_table_names():
        return

    op.create_table(
        "tool_plugin_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("team_id", sa.String(36), sa.ForeignKey("email_teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("plugin_id", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False, server_default="enforce"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.UniqueConstraint("team_id", "tool_name", "plugin_id", name="uq_tool_plugin_binding"),
    )

    op.create_index("ix_tool_plugin_bindings_team_id", "tool_plugin_bindings", ["team_id"])
    op.create_index("ix_tool_plugin_bindings_tool_name", "tool_plugin_bindings", ["tool_name"])


def downgrade() -> None:
    """Drop tool_plugin_bindings table."""
    inspector = sa.inspect(op.get_bind())

    if "tool_plugin_bindings" not in inspector.get_table_names():
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("tool_plugin_bindings")}
    for name in ("ix_tool_plugin_bindings_tool_name", "idx_tool_plugin_bindings_tool_name"):
        if name in indexes:
            op.drop_index(name, table_name="tool_plugin_bindings")
            break
    for name in ("ix_tool_plugin_bindings_team_id", "idx_tool_plugin_bindings_team_id"):
        if name in indexes:
            op.drop_index(name, table_name="tool_plugin_bindings")
            break
    op.drop_table("tool_plugin_bindings")
