# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/86a6a377e442_add_rbac_rules_catalog.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

add rbac_rules catalog

Revision ID: 86a6a377e442
Revises: f7a8b9c0d1e2
Create Date: 2026-10-03
"""

# Standard
from typing import Sequence, Union

# Third-Party
import sqlalchemy as sa
from alembic import op

revision: str = "86a6a377e442"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the rbac_rules table.

    The built-in matrix seed is inserted by bootstrap_db at startup
    (RuleCatalogService.reseed_defaults); importing application code
    here would break alembic runs without the full settings
    environment.
    """
    inspector = sa.inspect(op.get_bind())
    if "rbac_rules" in inspector.get_table_names():
        return
    op.create_table(
        "rbac_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("capability_type", sa.String(30), nullable=False),
        sa.Column("capability_id", sa.String(255), nullable=True),
        sa.Column("permission", sa.String(100), nullable=True),
        sa.Column("phase", sa.String(20), nullable=False, server_default="pre_invocation"),
        sa.Column("predicate", sa.Text(), nullable=False),
        sa.Column("effect", sa.String(10), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Drop the rbac_rules table."""
    inspector = sa.inspect(op.get_bind())
    if "rbac_rules" not in inspector.get_table_names():
        return
    op.drop_table("rbac_rules")
