# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/6b65e7b0c0ad_drop_stale_oauth_token_unique_constraint.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Darren Halden

Drop stale oauth_tokens provider-user uniqueness constraint.

Revision ID: 6b65e7b0c0ad
Revises: 0a089912b5f0
Create Date: 2026-06-06 19:12:10.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "6b65e7b0c0ad"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "0a089912b5f0"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "oauth_tokens"
STALE_CONSTRAINT_NAME = "unique_gateway_user"


def _unique_constraint_exists(inspector: sa.Inspector, table_name: str, constraint_name: str) -> bool:
    """Return True when ``constraint_name`` exists on ``table_name``."""
    return any(constraint.get("name") == constraint_name for constraint in inspector.get_unique_constraints(table_name))


def upgrade() -> None:
    """Drop stale uniqueness on (gateway_id, user_id).

    OAuth provider ``user_id`` is not ContextForge's user identity; uniqueness is
    now enforced per ContextForge user by the existing (gateway_id,
    app_user_email) unique index/constraint.
    """
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if TABLE_NAME not in inspector.get_table_names():
        print(f"Table '{TABLE_NAME}' does not exist, skipping stale OAuth token constraint drop.")
        return

    if not _unique_constraint_exists(inspector, TABLE_NAME, STALE_CONSTRAINT_NAME):
        print(f"Constraint '{STALE_CONSTRAINT_NAME}' does not exist, skipping drop.")
        return

    if conn.dialect.name == "sqlite":
        with op.batch_alter_table(TABLE_NAME, schema=None) as batch_op:
            batch_op.drop_constraint(STALE_CONSTRAINT_NAME, type_="unique")
    else:
        op.drop_constraint(STALE_CONSTRAINT_NAME, TABLE_NAME, type_="unique")

    print(f"Successfully removed stale constraint '{STALE_CONSTRAINT_NAME}' from {TABLE_NAME}.")


def downgrade() -> None:
    """Restore the legacy provider-user uniqueness constraint."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if TABLE_NAME not in inspector.get_table_names():
        print(f"Table '{TABLE_NAME}' does not exist, skipping stale OAuth token constraint restore.")
        return

    if _unique_constraint_exists(inspector, TABLE_NAME, STALE_CONSTRAINT_NAME):
        print(f"Constraint '{STALE_CONSTRAINT_NAME}' already exists, skipping restore.")
        return

    if conn.dialect.name == "sqlite":
        with op.batch_alter_table(TABLE_NAME, schema=None) as batch_op:
            batch_op.create_unique_constraint(STALE_CONSTRAINT_NAME, ["gateway_id", "user_id"])
    else:
        op.create_unique_constraint(STALE_CONSTRAINT_NAME, TABLE_NAME, ["gateway_id", "user_id"])

    print(f"Successfully restored legacy constraint '{STALE_CONSTRAINT_NAME}' on {TABLE_NAME}.")
