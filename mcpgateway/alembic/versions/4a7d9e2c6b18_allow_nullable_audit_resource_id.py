# -*- coding: utf-8 -*-
# Alembic exposes operation proxies dynamically and prefixes filenames with revision IDs.
# pylint: disable=invalid-name,no-member
"""Location: ./mcpgateway/alembic/versions/4a7d9e2c6b18_allow_nullable_audit_resource_id.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Allow aggregate audit rows without individual resource IDs.

Revision ID: 4a7d9e2c6b18
Revises: c7e91a2b4d60
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "4a7d9e2c6b18"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "c7e91a2b4d60"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Permit NULL resource IDs while preserving audit rows and indexes."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("audit_trails"):
        return
    resource_id = next((column for column in inspector.get_columns("audit_trails") if column["name"] == "resource_id"), None)
    if resource_id is None or resource_id["nullable"]:
        return

    with op.batch_alter_table("audit_trails") as batch_op:
        batch_op.alter_column("resource_id", existing_type=resource_id["type"], nullable=True)


def downgrade() -> None:
    """Restore required resource IDs when every audit row has a resource ID."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("audit_trails"):
        return
    resource_id = next((column for column in inspector.get_columns("audit_trails") if column["name"] == "resource_id"), None)
    if resource_id is None or not resource_id["nullable"]:
        return

    if bind.execute(sa.text("SELECT 1 FROM audit_trails WHERE resource_id IS NULL LIMIT 1")).first() is not None:
        raise RuntimeError("Cannot restore NOT NULL on audit_trails.resource_id while NULL resource IDs exist. Preserve these audit rows and keep the current revision.")

    with op.batch_alter_table("audit_trails") as batch_op:
        batch_op.alter_column("resource_id", existing_type=resource_id["type"], nullable=False)
