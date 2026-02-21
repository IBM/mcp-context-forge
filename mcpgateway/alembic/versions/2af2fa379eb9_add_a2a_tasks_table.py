# -*- coding: utf-8 -*-
"""Add a2a_tasks table for persisted A2A task snapshots.

Revision ID: 2af2fa379eb9
Revises: x7h8i9j0k1l2
Create Date: 2026-02-16 00:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "2af2fa379eb9"
down_revision: Union[str, Sequence[str], None] = "x7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create a2a_tasks table and indexes."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "a2a_agents" not in tables:
        return

    if "a2a_tasks" not in tables:
        op.create_table(
            "a2a_tasks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("a2a_agent_id", sa.String(length=36), nullable=False),
            sa.Column("task_id", sa.String(length=255), nullable=False),
            sa.Column("context_id", sa.String(length=255), nullable=True),
            sa.Column("state", sa.String(length=64), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("latest_message", sa.JSON(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["a2a_agent_id"], ["a2a_agents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("a2a_agent_id", "task_id", name="uq_a2a_tasks_agent_task"),
        )
        inspector = sa.inspect(bind)

    indexes = {idx["name"] for idx in inspector.get_indexes("a2a_tasks")}

    if "ix_a2a_tasks_a2a_agent_id" not in indexes:
        op.create_index("ix_a2a_tasks_a2a_agent_id", "a2a_tasks", ["a2a_agent_id"], unique=False)
    if "ix_a2a_tasks_task_id" not in indexes:
        op.create_index("ix_a2a_tasks_task_id", "a2a_tasks", ["task_id"], unique=False)
    if "ix_a2a_tasks_state" not in indexes:
        op.create_index("ix_a2a_tasks_state", "a2a_tasks", ["state"], unique=False)
    if "ix_a2a_tasks_state_updated" not in indexes:
        op.create_index("ix_a2a_tasks_state_updated", "a2a_tasks", ["state", "updated_at"], unique=False)


def downgrade() -> None:
    """Drop a2a_tasks table and indexes."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "a2a_tasks" not in tables:
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("a2a_tasks")}

    if "ix_a2a_tasks_state_updated" in indexes:
        op.drop_index("ix_a2a_tasks_state_updated", table_name="a2a_tasks")
    if "ix_a2a_tasks_state" in indexes:
        op.drop_index("ix_a2a_tasks_state", table_name="a2a_tasks")
    if "ix_a2a_tasks_task_id" in indexes:
        op.drop_index("ix_a2a_tasks_task_id", table_name="a2a_tasks")
    if "ix_a2a_tasks_a2a_agent_id" in indexes:
        op.drop_index("ix_a2a_tasks_a2a_agent_id", table_name="a2a_tasks")

    op.drop_table("a2a_tasks")
