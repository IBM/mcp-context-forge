# -*- coding: utf-8 -*-
"""add_cascade_to_association_tables

Revision ID: aa1bb2cc3dd4
Revises: 43c07ed25a24
Create Date: 2026-04-01 13:17:00.000000

Add ON DELETE CASCADE to foreign key constraints in server association tables
and metrics tables to allow proper deletion of tools, resources, prompts, and
A2A agents when they are removed from the system.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aa1bb2cc3dd4"
down_revision: Union[str, Sequence[str], None] = "615af4ab94b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ON DELETE CASCADE to association table foreign keys."""
    # Third-Party
    import sqlalchemy as sa

    # Get database connection to check if we're using PostgreSQL
    conn = op.get_bind()
    dialect_name = conn.dialect.name

    if dialect_name == "postgresql":
        # PostgreSQL: Drop and recreate constraints with CASCADE
        inspector = sa.inspect(conn)

        # Helper function to check if constraint exists
        def constraint_exists(table_name: str, constraint_name: str) -> bool:
            try:
                fks = inspector.get_foreign_keys(table_name)
                return any(fk.get("name") == constraint_name for fk in fks)
            except Exception:
                return False

        # server_tool_association
        if constraint_exists("server_tool_association", "fk_server_tool_association_server_id"):
            op.drop_constraint("fk_server_tool_association_server_id", "server_tool_association", type_="foreignkey")
        if constraint_exists("server_tool_association", "fk_server_tool_association_tool_id"):
            op.drop_constraint("fk_server_tool_association_tool_id", "server_tool_association", type_="foreignkey")
        op.create_foreign_key(
            "fk_server_tool_association_server_id",
            "server_tool_association",
            "servers",
            ["server_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_server_tool_association_tool_id",
            "server_tool_association",
            "tools",
            ["tool_id"],
            ["id"],
            ondelete="CASCADE",
        )

        # server_resource_association
        if constraint_exists("server_resource_association", "fk_server_resource_association_server_id"):
            op.drop_constraint("fk_server_resource_association_server_id", "server_resource_association", type_="foreignkey")
        if constraint_exists("server_resource_association", "fk_server_resource_association_resource_id"):
            op.drop_constraint("fk_server_resource_association_resource_id", "server_resource_association", type_="foreignkey")
        op.create_foreign_key(
            "fk_server_resource_association_server_id",
            "server_resource_association",
            "servers",
            ["server_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_server_resource_association_resource_id",
            "server_resource_association",
            "resources",
            ["resource_id"],
            ["id"],
            ondelete="CASCADE",
        )

        # server_prompt_association
        if constraint_exists("server_prompt_association", "fk_server_prompt_association_server_id"):
            op.drop_constraint("fk_server_prompt_association_server_id", "server_prompt_association", type_="foreignkey")
        if constraint_exists("server_prompt_association", "fk_server_prompt_association_prompt_id"):
            op.drop_constraint("fk_server_prompt_association_prompt_id", "server_prompt_association", type_="foreignkey")
        op.create_foreign_key(
            "fk_server_prompt_association_server_id",
            "server_prompt_association",
            "servers",
            ["server_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_server_prompt_association_prompt_id",
            "server_prompt_association",
            "prompts",
            ["prompt_id"],
            ["id"],
            ondelete="CASCADE",
        )

        # server_a2a_association
        if constraint_exists("server_a2a_association", "fk_server_a2a_association_server_id"):
            op.drop_constraint("fk_server_a2a_association_server_id", "server_a2a_association", type_="foreignkey")
        if constraint_exists("server_a2a_association", "fk_server_a2a_association_a2a_agent_id"):
            op.drop_constraint("fk_server_a2a_association_a2a_agent_id", "server_a2a_association", type_="foreignkey")
        op.create_foreign_key(
            "fk_server_a2a_association_server_id",
            "server_a2a_association",
            "servers",
            ["server_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_server_a2a_association_a2a_agent_id",
            "server_a2a_association",
            "a2a_agents",
            ["a2a_agent_id"],
            ["id"],
            ondelete="CASCADE",
        )

        # tool_metrics - Add CASCADE to allow deleting tools with metrics
        if constraint_exists("tool_metrics", "tool_metrics_tool_id_fkey"):
            op.drop_constraint("tool_metrics_tool_id_fkey", "tool_metrics", type_="foreignkey")
        op.create_foreign_key(
            "tool_metrics_tool_id_fkey",
            "tool_metrics",
            "tools",
            ["tool_id"],
            ["id"],
            ondelete="CASCADE",
        )

    elif dialect_name == "sqlite":
        # SQLite: Foreign keys are enabled via PRAGMA, CASCADE is handled by recreating tables
        # SQLite doesn't support ALTER TABLE for foreign keys, but since we enable
        # PRAGMA foreign_keys=ON in db.py, the new schema definition with CASCADE
        # will be used for new databases. For existing SQLite databases, the
        # association table entries will be manually deleted by the application code.
        pass


def downgrade() -> None:
    """Remove ON DELETE CASCADE from association table foreign keys."""
    conn = op.get_bind()
    dialect_name = conn.dialect.name

    if dialect_name == "postgresql":
        # PostgreSQL: Drop and recreate constraints without CASCADE

        # server_tool_association
        op.drop_constraint("fk_server_tool_association_server_id", "server_tool_association", type_="foreignkey")
        op.drop_constraint("fk_server_tool_association_tool_id", "server_tool_association", type_="foreignkey")
        op.create_foreign_key(
            "fk_server_tool_association_server_id",
            "server_tool_association",
            "servers",
            ["server_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_server_tool_association_tool_id",
            "server_tool_association",
            "tools",
            ["tool_id"],
            ["id"],
        )

        # server_resource_association
        op.drop_constraint("fk_server_resource_association_server_id", "server_resource_association", type_="foreignkey")
        op.drop_constraint("fk_server_resource_association_resource_id", "server_resource_association", type_="foreignkey")
        op.create_foreign_key(
            "fk_server_resource_association_server_id",
            "server_resource_association",
            "servers",
            ["server_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_server_resource_association_resource_id",
            "server_resource_association",
            "resources",
            ["resource_id"],
            ["id"],
        )

        # server_prompt_association
        op.drop_constraint("fk_server_prompt_association_server_id", "server_prompt_association", type_="foreignkey")
        op.drop_constraint("fk_server_prompt_association_prompt_id", "server_prompt_association", type_="foreignkey")
        op.create_foreign_key(
            "fk_server_prompt_association_server_id",
            "server_prompt_association",
            "servers",
            ["server_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_server_prompt_association_prompt_id",
            "server_prompt_association",
            "prompts",
            ["prompt_id"],
            ["id"],
        )

        # server_a2a_association
        op.drop_constraint("fk_server_a2a_association_server_id", "server_a2a_association", type_="foreignkey")
        op.drop_constraint("fk_server_a2a_association_a2a_agent_id", "server_a2a_association", type_="foreignkey")
        op.create_foreign_key(
            "fk_server_a2a_association_server_id",
            "server_a2a_association",
            "servers",
            ["server_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_server_a2a_association_a2a_agent_id",
            "server_a2a_association",
            "a2a_agents",
            ["a2a_agent_id"],
            ["id"],
        )

        # tool_metrics - Remove CASCADE
        op.drop_constraint("tool_metrics_tool_id_fkey", "tool_metrics", type_="foreignkey")
        op.create_foreign_key(
            "tool_metrics_tool_id_fkey",
            "tool_metrics",
            "tools",
            ["tool_id"],
            ["id"],
        )

    elif dialect_name == "sqlite":
        # SQLite: No action needed for downgrade
        pass
