# -*- coding: utf-8 -*-
"""add_grpc_service_id_to_tools

Revision ID: w7x8y9z0a1b2
Revises: w6g7h8i9j0k1
Create Date: 2026-02-16 13:45:00.000000

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "w7x8y9z0a1b2"
down_revision: Union[str, None] = "w6g7h8i9j0k1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add grpc_service_id foreign key to tools table."""
    # Check if tools table exists
    inspector = sa.inspect(op.get_bind())
    if "tools" not in inspector.get_table_names():
        return

    # Check if column already exists
    columns = [col["name"] for col in inspector.get_columns("tools")]
    if "grpc_service_id" in columns:
        return

    # Add grpc_service_id column with foreign key to grpc_services
    op.add_column(
        "tools",
        sa.Column("grpc_service_id", sa.String(36), nullable=True),
    )

    # Add foreign key constraint
    # Note: SQLite doesn't support adding FK constraints to existing tables,
    # so we only add it for other databases
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_tools_grpc_service_id",
            "tools",
            "grpc_services",
            ["grpc_service_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    """Remove grpc_service_id from tools table."""
    inspector = sa.inspect(op.get_bind())
    if "tools" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("tools")]
    if "grpc_service_id" not in columns:
        return

    # Drop foreign key constraint (non-SQLite only)
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_tools_grpc_service_id", "tools", type_="foreignkey")

    # Drop column
    op.drop_column("tools", "grpc_service_id")
