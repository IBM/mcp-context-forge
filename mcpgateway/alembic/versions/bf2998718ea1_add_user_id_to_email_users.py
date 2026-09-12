# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/bf2998718ea1_add_user_id_to_email_users.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

add_user_id_to_email_users

Revision ID: bf2998718ea1
Revises: 5e211ec89cad
Create Date: 2026-09-09 21:15:35.188743
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "bf2998718ea1"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "5e211ec89cad"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable user_id column to email_users, backfill it with email, and index it."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if table doesn't exist (fresh DB uses db.py models directly)
    if "email_users" not in inspector.get_table_names():
        return

    # Add the column only when missing; backfill and index steps still run
    columns = [col["name"] for col in inspector.get_columns("email_users")]
    if "user_id" not in columns:
        with op.batch_alter_table("email_users") as batch_op:
            batch_op.add_column(sa.Column("user_id", sa.String(255), nullable=True))

    # Backfill existing rows; the WHERE clause makes re-runs safe
    bind.execute(text("UPDATE email_users SET user_id = email WHERE user_id IS NULL"))

    # Create a non-unique index for user_id lookups
    inspector = sa.inspect(bind)
    indexes = [index["name"] for index in inspector.get_indexes("email_users")]
    if "ix_email_users_user_id" not in indexes:
        op.create_index("ix_email_users_user_id", "email_users", ["user_id"], unique=False)


def downgrade() -> None:
    """Remove the user_id index and column from email_users."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if table doesn't exist
    if "email_users" not in inspector.get_table_names():
        return

    indexes = [index["name"] for index in inspector.get_indexes("email_users")]
    if "ix_email_users_user_id" in indexes:
        op.drop_index("ix_email_users_user_id", table_name="email_users")

    columns = [col["name"] for col in inspector.get_columns("email_users")]
    if "user_id" in columns:
        with op.batch_alter_table("email_users") as batch_op:
            batch_op.drop_column("user_id")
