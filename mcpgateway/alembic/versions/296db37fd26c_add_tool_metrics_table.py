"""add_tool_metrics_table

Revision ID: 296db37fd26c
Revises: aa1bb2cc3dd4
Create Date: 2026-04-04 14:50:14.335361

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "296db37fd26c"
down_revision: Union[str, Sequence[str], None] = "aa1bb2cc3dd4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing base metrics tables (tool_metrics, resource_metrics, server_metrics, prompt_metrics)."""
    # Check if tables already exist (idempotent migration)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # Create tool_metrics table if missing
    if "tool_metrics" not in existing_tables:
        op.create_table(
            "tool_metrics",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tool_id", sa.String(36), sa.ForeignKey("tools.id", ondelete="CASCADE"), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("response_time", sa.Float(), nullable=False),
            sa.Column("is_success", sa.Boolean(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
        )
        op.create_index("ix_tool_metrics_tool_id", "tool_metrics", ["tool_id"])
        op.create_index("ix_tool_metrics_timestamp", "tool_metrics", ["timestamp"])

    # Create resource_metrics table if missing
    if "resource_metrics" not in existing_tables:
        op.create_table(
            "resource_metrics",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("resource_id", sa.String(36), sa.ForeignKey("resources.id"), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("response_time", sa.Float(), nullable=False),
            sa.Column("is_success", sa.Boolean(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
        )
        op.create_index("ix_resource_metrics_resource_id", "resource_metrics", ["resource_id"])
        op.create_index("ix_resource_metrics_timestamp", "resource_metrics", ["timestamp"])

    # Create server_metrics table if missing
    if "server_metrics" not in existing_tables:
        op.create_table(
            "server_metrics",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("server_id", sa.String(36), sa.ForeignKey("servers.id"), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("response_time", sa.Float(), nullable=False),
            sa.Column("is_success", sa.Boolean(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
        )
        op.create_index("ix_server_metrics_server_id", "server_metrics", ["server_id"])
        op.create_index("ix_server_metrics_timestamp", "server_metrics", ["timestamp"])

    # Create prompt_metrics table if missing
    if "prompt_metrics" not in existing_tables:
        op.create_table(
            "prompt_metrics",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("prompt_id", sa.String(36), sa.ForeignKey("prompts.id"), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("response_time", sa.Float(), nullable=False),
            sa.Column("is_success", sa.Boolean(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
        )
        op.create_index("ix_prompt_metrics_prompt_id", "prompt_metrics", ["prompt_id"])
        op.create_index("ix_prompt_metrics_timestamp", "prompt_metrics", ["timestamp"])


def downgrade() -> None:
    """Remove base metrics tables."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # Drop tables in reverse order (if they exist)
    for table_name in ["prompt_metrics", "server_metrics", "resource_metrics", "tool_metrics"]:
        if table_name in existing_tables:
            try:
                # Drop indexes first
                existing_indexes = [idx["name"] for idx in inspector.get_indexes(table_name)]
                for idx_name in existing_indexes:
                    if idx_name.startswith("ix_"):
                        try:
                            op.drop_index(idx_name, table_name=table_name)
                        except Exception as e:
                            print(f"Warning: Could not drop index {idx_name}: {e}")
            except Exception as e:
                print(f"Warning: Could not get indexes for {table_name}: {e}")

            # Drop table
            try:
                op.drop_table(table_name)
            except Exception as e:
                print(f"Warning: Could not drop table {table_name}: {e}")


# Made with Bob
