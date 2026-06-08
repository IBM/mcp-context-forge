# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/b29af8761e97_add_a2a_agent_plugin_binding_table.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Madhumohan Jaishankar

add_a2a_agent_plugin_binding_table

Revision ID: b29af8761e97
Revises: 351b43e1d273
Create Date: 2026-05-15 11:59:42.434761
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b29af8761e97"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "351b43e1d273"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create a2a_agent_plugin_bindings table for per-agent plugin policies."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    # Skip if table already exists (idempotent)
    if "a2a_agent_plugin_bindings" in tables:
        return

    op.create_table(
        "a2a_agent_plugin_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("team_id", sa.String(length=36), nullable=False),
        sa.Column("agent_name", sa.String(length=255), nullable=False),
        sa.Column("plugin_id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default=sa.text("'enforce'")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("50")),
        sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("binding_reference_id", sa.String(length=255), nullable=True),
        sa.Column("on_error", sa.String(length=10), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.CheckConstraint(
            "on_error IN ('fail', 'ignore', 'disable') OR on_error IS NULL",
            name="ck_a2a_agent_plugin_bindings_on_error_valid",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["email_teams.id"],
            name="fk_a2a_agent_plugin_bindings_team_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_a2a_agent_plugin_bindings"),
        sa.UniqueConstraint(
            "team_id",
            "agent_name",
            "plugin_id",
            name="uq_a2a_agent_plugin_binding",
        ),
    )
    op.create_index(
        "ix_a2a_agent_plugin_bindings_team_id",
        "a2a_agent_plugin_bindings",
        ["team_id"],
        unique=False,
    )
    op.create_index(
        "ix_a2a_agent_plugin_bindings_agent_name",
        "a2a_agent_plugin_bindings",
        ["agent_name"],
        unique=False,
    )
    op.create_index(
        "ix_a2a_agent_plugin_bindings_binding_reference_id",
        "a2a_agent_plugin_bindings",
        ["binding_reference_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop a2a_agent_plugin_bindings table if it exists."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "a2a_agent_plugin_bindings" not in tables:
        return

    op.drop_table("a2a_agent_plugin_bindings")
