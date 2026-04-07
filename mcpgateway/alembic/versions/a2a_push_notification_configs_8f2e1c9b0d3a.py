"""Add a2a_push_notification_configs table

Revision ID: 8f2e1c9b0d3a
Revises: 3f7e9d1a2b4c
Create Date: 2026-03-31

Creates the a2a_push_notification_configs table for persisting webhook
push notification configurations for A2A task state changes.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "8f2e1c9b0d3a"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "3f7e9d1a2b4c"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create a2a_push_notification_configs table."""
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()

    if "a2a_push_notification_configs" not in existing_tables:
        op.create_table(
            "a2a_push_notification_configs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "a2a_agent_id",
                sa.String(36),
                sa.ForeignKey("a2a_agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("task_id", sa.String(255), nullable=False),
            sa.Column("webhook_url", sa.String(2048), nullable=False),
            sa.Column("auth_token", sa.Text(), nullable=True),
            sa.Column("events", sa.JSON(), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("a2a_agent_id", "task_id", "webhook_url", name="uq_push_config_agent_task_url"),
        )
        op.create_index("ix_a2a_push_notification_configs_a2a_agent_id", "a2a_push_notification_configs", ["a2a_agent_id"])
        op.create_index("ix_a2a_push_notification_configs_task_id", "a2a_push_notification_configs", ["task_id"])


def downgrade() -> None:
    """Drop a2a_push_notification_configs table."""
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()

    if "a2a_push_notification_configs" in existing_tables:
        op.drop_index("ix_a2a_push_notification_configs_task_id", table_name="a2a_push_notification_configs")
        op.drop_index("ix_a2a_push_notification_configs_a2a_agent_id", table_name="a2a_push_notification_configs")
        op.drop_table("a2a_push_notification_configs")
