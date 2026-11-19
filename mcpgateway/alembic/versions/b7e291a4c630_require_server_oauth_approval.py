# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/b7e291a4c630_require_server_oauth_approval.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Require administrator approval for virtual-server OAuth settings.

Revision ID: b7e291a4c630
Revises: 7a3a6305ddb6
"""

# Third-Party
from alembic import op
import sqlalchemy as sa

revision = "b7e291a4c630"  # pragma: allowlist secret
down_revision = "7a3a6305ddb6"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add unapproved defaults while preserving existing OAuth settings."""
    inspector = sa.inspect(op.get_bind())
    if "servers" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("servers")}
    if "oauth_config_approved" not in columns:
        op.add_column("servers", sa.Column("oauth_config_approved", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "oauth_config_generation" not in columns:
        op.add_column("servers", sa.Column("oauth_config_generation", sa.String(32), nullable=True))


def downgrade() -> None:
    """Remove approval state without changing OAuth settings."""
    inspector = sa.inspect(op.get_bind())
    if "servers" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("servers")}
    with op.batch_alter_table("servers") as batch:
        if "oauth_config_generation" in columns:
            batch.drop_column("oauth_config_generation")
        if "oauth_config_approved" in columns:
            batch.drop_column("oauth_config_approved")
