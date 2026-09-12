# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/a824749abd27_add_user_id_to_roles_and_team_members.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

add_user_id_to_roles_and_team_members

Revision ID: a824749abd27
Revises: bf2998718ea1
Create Date: 2026-09-12 17:50:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a824749abd27"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "bf2998718ea1"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, index) pairs gaining a nullable canonical user_id column (#5893).
# The FK-bearing user_email columns keep the e-mail; user_id stores the
# canonical ID for users whose IdP subject diverges from their e-mail.
_TARGETS = (
    ("user_roles", "ix_user_roles_user_id"),
    ("email_team_members", "ix_email_team_members_user_id"),
)


def upgrade() -> None:
    """Add nullable indexed user_id columns to user_roles and email_team_members."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    for table, index_name in _TARGETS:
        # Skip if table doesn't exist (fresh DB uses db.py models directly)
        if table not in tables:
            continue

        columns = [col["name"] for col in inspector.get_columns(table)]
        if "user_id" not in columns:
            with op.batch_alter_table(table) as batch_op:
                batch_op.add_column(sa.Column("user_id", sa.String(255), nullable=True))

        # Re-inspect: the column add above invalidates the earlier snapshot
        inspector = sa.inspect(bind)
        indexes = [index["name"] for index in inspector.get_indexes(table)]
        if index_name not in indexes:
            op.create_index(index_name, table, ["user_id"], unique=False)


def downgrade() -> None:
    """Remove the user_id indexes and columns from user_roles and email_team_members."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    for table, index_name in _TARGETS:
        if table not in tables:
            continue

        indexes = [index["name"] for index in inspector.get_indexes(table)]
        if index_name in indexes:
            op.drop_index(index_name, table_name=table)

        columns = [col["name"] for col in inspector.get_columns(table)]
        if "user_id" in columns:
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_column("user_id")
