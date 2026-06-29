"""add_sunset_date_to_tools

Revision ID: 15a7b5f1e41a
Revises: e198602c3c1e
Create Date: 2026-05-26 11:50:39.306163

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "15a7b5f1e41a"
down_revision: Union[str, Sequence[str], None] = "e198602c3c1e"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add sunset_date column to tools table with index for efficient queries."""
    inspector = sa.inspect(op.get_bind())

    # Skip if table doesn't exist yet (fresh DB uses db.py models directly)
    if "tools" not in inspector.get_table_names():
        return

    # Skip if column already exists
    columns = [col["name"] for col in inspector.get_columns("tools")]
    if "sunset_date" in columns:
        return

    # Add sunset_date column (nullable, timezone-aware datetime)
    op.add_column("tools", sa.Column("sunset_date", sa.DateTime(timezone=True), nullable=True))

    # Create index for efficient sunset transition queries
    # Index name follows convention: ix_<table>_<column>
    op.create_index("ix_tools_sunset_date", "tools", ["sunset_date"], unique=False)


def downgrade() -> None:
    """Remove sunset_date column and index from tools table."""
    inspector = sa.inspect(op.get_bind())

    # Skip if table doesn't exist
    if "tools" not in inspector.get_table_names():
        return

    # Drop index if it exists
    existing_indexes = [idx["name"] for idx in inspector.get_indexes("tools")]
    if "ix_tools_sunset_date" in existing_indexes:
        op.drop_index("ix_tools_sunset_date", table_name="tools")

    # Drop column if it exists
    columns = [col["name"] for col in inspector.get_columns("tools")]
    if "sunset_date" in columns:
        op.drop_column("tools", "sunset_date")
