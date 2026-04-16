"""add_a2a_task_events_table

Revision ID: ffe4494639d3
Revises: 8f2e1c9b0d3a
Create Date: 2026-04-02 11:15:42.565904

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "ffe4494639d3"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "8f2e1c9b0d3a"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create a2a_task_events table if it does not already exist."""
    inspector = sa.inspect(op.get_bind())
    if "a2a_task_events" in inspector.get_table_names():
        return

    op.create_table(
        "a2a_task_events",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("a2a_agent_id", sa.String(36), sa.ForeignKey("a2a_agents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("task_id", sa.String(255), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_a2a_task_events_task_id", "a2a_task_events", ["task_id"])
    op.create_index("ix_a2a_task_events_task_seq", "a2a_task_events", ["task_id", "sequence"])
    op.create_index("ix_a2a_task_events_agent_id", "a2a_task_events", ["a2a_agent_id"])


def downgrade() -> None:
    """Drop a2a_task_events table if it exists."""
    inspector = sa.inspect(op.get_bind())
    if "a2a_task_events" not in inspector.get_table_names():
        return

    op.drop_index("ix_a2a_task_events_task_seq", table_name="a2a_task_events")
    op.drop_index("ix_a2a_task_events_task_id", table_name="a2a_task_events")
    op.drop_table("a2a_task_events")
