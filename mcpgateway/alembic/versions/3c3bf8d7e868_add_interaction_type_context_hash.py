# -*- coding: utf-8 -*-
"""add interaction_type and context_hash to tool_usage_events

Revision ID: 3c3bf8d7e868
Revises: d4e5f6a7b8c9
Create Date: 2026-03-19

Adds the interaction_type (invoke/view/dismiss) and context_hash fields
introduced alongside the collaborative-filtering analytics pipeline.

down_revision points to d4e5f6a7b8c9 (add_dynamic_servers_and_rules),
the only fully-connected head on this branch.  The companion head
e1f2a3b4c5d6 (add_grant_source_to_user_roles) references parent
d9e0f1a2b3c4 which does not exist in this branch's versions directory
and cannot safely be incorporated into a merge revision here.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c3bf8d7e868"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if "tool_usage_events" not in inspector.get_table_names():
        # Fresh database: the table is created directly from db.py models which
        # already include these columns, so no migration step is needed.
        return

    existing_columns = [col["name"] for col in inspector.get_columns("tool_usage_events")]

    if "interaction_type" not in existing_columns:
        op.add_column(
            "tool_usage_events",
            sa.Column("interaction_type", sa.String(20), nullable=False, server_default="invoke"),
        )

    if "context_hash" not in existing_columns:
        op.add_column(
            "tool_usage_events",
            sa.Column("context_hash", sa.String(64), nullable=True),
        )

    # Add index on interaction_type for analytics queries (idempotent)
    existing_indexes = [idx["name"] for idx in inspector.get_indexes("tool_usage_events")]
    if "idx_usage_events_interaction_type" not in existing_indexes:
        op.create_index("idx_usage_events_interaction_type", "tool_usage_events", ["interaction_type"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if "tool_usage_events" not in inspector.get_table_names():
        return

    existing_indexes = [idx["name"] for idx in inspector.get_indexes("tool_usage_events")]
    if "idx_usage_events_interaction_type" in existing_indexes:
        op.drop_index("idx_usage_events_interaction_type", table_name="tool_usage_events")

    existing_columns = [col["name"] for col in inspector.get_columns("tool_usage_events")]
    if "context_hash" in existing_columns:
        op.drop_column("tool_usage_events", "context_hash")
    if "interaction_type" in existing_columns:
        op.drop_column("tool_usage_events", "interaction_type")
