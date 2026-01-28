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
    """Upgrade schema.

    Raises:
        RuntimeError: If tools table is missing (required for FK) or if orphaned
            tool_id values exist that would block FK creation.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if fresh database (tables created via create_all + stamp)
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    # Skip if a2a_agents table doesn't exist
    if not inspector.has_table("a2a_agents"):
        print("a2a_agents table not found. Skipping migration.")
        return

    # Fail if tools table doesn't exist - FK requires it
    if not inspector.has_table("tools"):
        raise RuntimeError(
            "Cannot proceed: a2a_agents table exists but tools table is missing. " "This migration adds a FK from a2a_agents.tool_id to tools.id. " "Please verify your database schema."
        )

    # Check current state
    columns = [col["name"] for col in inspector.get_columns("a2a_agents")]
    indexes = [idx["name"] for idx in inspector.get_indexes("a2a_agents")]
    fks = [fk["name"] for fk in inspector.get_foreign_keys("a2a_agents") if fk.get("name")]

    # Determine what needs to be added
    need_column = "tool_id" not in columns
    need_index = "idx_a2a_agents_tool_id" not in indexes
    need_fk = "fk_a2a_agents_tool_id" not in fks

    # If column exists but FK doesn't, check for orphaned references that would block FK creation
    if not need_column and need_fk:
        # Use COUNT for efficiency, then fetch limited sample for error message
        orphan_count = bind.execute(sa.text("SELECT COUNT(*) FROM a2a_agents WHERE tool_id IS NOT NULL " "AND tool_id NOT IN (SELECT id FROM tools)")).scalar() or 0
        if orphan_count > 0:
            # Fetch limited sample for error details
            sample = bind.execute(sa.text("SELECT id, tool_id FROM a2a_agents WHERE tool_id IS NOT NULL " "AND tool_id NOT IN (SELECT id FROM tools) LIMIT 10")).fetchall()
            orphan_details = "\n".join(f"  - agent {aid} -> tool {tid}" for aid, tid in sample)
            more_msg = f"\n  ... and {orphan_count - len(sample)} more" if orphan_count > len(sample) else ""
            raise RuntimeError(
                f"Cannot add FK constraint: {orphan_count} a2a_agents have tool_id "  # nosec B608
                f"referencing non-existent tools:\n{orphan_details}{more_msg}\n\n"
                "To fix, run: UPDATE a2a_agents SET tool_id = NULL WHERE tool_id NOT IN (SELECT id FROM tools);"
            )

    # Use batch mode for all schema changes (required for SQLite FK support)
    if need_column or need_index or need_fk:
        with op.batch_alter_table("a2a_agents", schema=None) as batch_op:
            if need_column:
                batch_op.add_column(sa.Column("tool_id", sa.String(length=36), nullable=True))
            if need_fk:
                batch_op.create_foreign_key("fk_a2a_agents_tool_id", "tools", ["tool_id"], ["id"], ondelete="SET NULL")
            if need_index:
                batch_op.create_index("idx_a2a_agents_tool_id", ["tool_id"], unique=False)

    # Always run backfill for rows with NULL tool_id (idempotent operation)
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
            WHERE tool_id IS NULL AND EXISTS (
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
            WHERE tool_id IS NULL AND EXISTS (
                SELECT 1 FROM tools
                WHERE integration_type = 'A2A'
                AND annotations->>'a2a_agent_id' = a2a_agents.id
            )
        """
            )
        )
    elif dialect_name == "mysql":
        # MySQL JSON extraction (MySQL 5.7+)
        bind.execute(
            sa.text(
                """
            UPDATE a2a_agents
            SET tool_id = (
                SELECT id FROM tools
                WHERE integration_type = 'A2A'
                AND JSON_UNQUOTE(JSON_EXTRACT(annotations, '$.a2a_agent_id')) = a2a_agents.id
                LIMIT 1
            )
            WHERE tool_id IS NULL AND EXISTS (
                SELECT 1 FROM tools
                WHERE integration_type = 'A2A'
                AND JSON_UNQUOTE(JSON_EXTRACT(annotations, '$.a2a_agent_id')) = a2a_agents.id
            )
        """
            )
        )
    else:
        print(f"WARNING: Backfill not implemented for dialect '{dialect_name}'. tool_id will remain NULL for existing agents.")


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if fresh database
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    # Skip if a2a_agents table doesn't exist
    if not inspector.has_table("a2a_agents"):
        print("a2a_agents table not found. Skipping migration.")
        return

    # Check if column exists before dropping
    columns = [col["name"] for col in inspector.get_columns("a2a_agents")]
    if "tool_id" not in columns:
        print("tool_id column does not exist. Skipping migration.")
        return

    # Use batch mode for SQLite compatibility
    with op.batch_alter_table("a2a_agents", schema=None) as batch_op:
        batch_op.drop_index("idx_a2a_agents_tool_id")
        batch_op.drop_constraint("fk_a2a_agents_tool_id", type_="foreignkey")
        batch_op.drop_column("tool_id")
