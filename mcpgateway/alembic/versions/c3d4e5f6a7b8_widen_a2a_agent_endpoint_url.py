# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/c3d4e5f6a7b8_widen_a2a_agent_endpoint_url.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Widen a2a_agents.endpoint_url to the length the URL validator accepts.

Revision ID: c3d4e5f6a7b8
Revises: b7e291a4c630
"""

# Third-Party
from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"  # pragma: allowlist secret
down_revision = "b7e291a4c630"  # pragma: allowlist secret
branch_labels = None
depends_on = None

OLD_LENGTH = 767
NEW_LENGTH = 2048


def _endpoint_url_length(inspector: sa.Inspector):
    """Return the current endpoint_url length, or None when it is not a sized string."""
    for column in inspector.get_columns("a2a_agents"):
        if column["name"] == "endpoint_url":
            return getattr(column["type"], "length", None)
    return None


def upgrade() -> None:
    """Widen endpoint_url so a URL that passes validation also fits the column."""
    inspector = sa.inspect(op.get_bind())
    if "a2a_agents" not in inspector.get_table_names():
        return
    length = _endpoint_url_length(inspector)
    if length is None or length >= NEW_LENGTH:
        return
    with op.batch_alter_table("a2a_agents") as batch:
        batch.alter_column("endpoint_url", type_=sa.String(NEW_LENGTH), existing_type=sa.String(length), existing_nullable=False)


def downgrade() -> None:
    """Restore the old length. Shortcut: narrowing fails when a row holds more than 767 characters, and that is the intended signal to keep the widening."""
    inspector = sa.inspect(op.get_bind())
    if "a2a_agents" not in inspector.get_table_names():
        return
    length = _endpoint_url_length(inspector)
    if length is None or length <= OLD_LENGTH:
        return
    with op.batch_alter_table("a2a_agents") as batch:
        batch.alter_column("endpoint_url", type_=sa.String(OLD_LENGTH), existing_type=sa.String(length), existing_nullable=False)
