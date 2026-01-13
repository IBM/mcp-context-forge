# -*- coding: utf-8 -*-
"""Add tool_id to a2a_agents

Revision ID: 77243f5bfce5
Revises: s3c4d5e6f7g8
Create Date: 2026-01-08 00:13:26.384875

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "77243f5bfce5"
down_revision: Union[str, Sequence[str], None] = "s3c4d5e6f7g8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table("a2a_agents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tool_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key("fk_a2a_agents_tool_id", "tools", ["tool_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("idx_a2a_agents_tool_id", ["tool_id"], unique=False)

    # Populate tool_id for existing agents by matching tools with a2a_agent_id in annotations
    # This uses a raw SQL update with a subquery to find the matching tool
    bind = op.get_bind()

    # For SQLite, we need to use JSON extraction
    # For PostgreSQL, we'd use JSONB operators
    dialect_name = bind.dialect.name

    if dialect_name == "sqlite":
        # SQLite JSON extraction
        # Find tools where annotations contains the agent's ID as a2a_agent_id
        bind.execute(
            sa.text(
                """
            UPDATE a2a_agents
            SET tool_id = (
                SELECT id FROM tools
                WHERE integration_type = 'A2A'
                AND json_extract(annotations, '$.a2a_agent_id') = a2a_agents.id
                LIMIT 1
            )
            WHERE EXISTS (
                SELECT 1 FROM tools
                WHERE integration_type = 'A2A'
                AND json_extract(annotations, '$.a2a_agent_id') = a2a_agents.id
            )
        """
            )
        )
    elif dialect_name == "postgresql":
        # PostgreSQL JSONB operators
        bind.execute(
            sa.text(
                """
            UPDATE a2a_agents
            SET tool_id = (
                SELECT id FROM tools
                WHERE integration_type = 'A2A'
                AND annotations->>'a2a_agent_id' = a2a_agents.id
                LIMIT 1
            )
            WHERE EXISTS (
                SELECT 1 FROM tools
                WHERE integration_type = 'A2A'
                AND annotations->>'a2a_agent_id' = a2a_agents.id
            )
        """
            )
        )
    else:
        # For other databases, try generic approach (may not work)
        pass


def downgrade() -> None:
    """Downgrade schema."""
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table("a2a_agents", schema=None) as batch_op:
        batch_op.drop_index("idx_a2a_agents_tool_id")
        batch_op.drop_constraint("fk_a2a_agents_tool_id", type_="foreignkey")
        batch_op.drop_column("tool_id")
