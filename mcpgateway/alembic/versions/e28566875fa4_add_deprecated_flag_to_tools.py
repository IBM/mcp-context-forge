"""add_deprecated_flag_to_tools

Revision ID: e28566875fa4
Revises: b29af8761e97
Create Date: 2026-05-20 12:39:20.637697

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e28566875fa4"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "b29af8761e97"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add deprecated column to tools table."""
    inspector = sa.inspect(op.get_bind())

    # Skip if table doesn't exist (fresh DB uses db.py models directly)
    if "tools" not in inspector.get_table_names():
        return

    # Skip if column already exists
    columns = [col["name"] for col in inspector.get_columns("tools")]
    if "deprecated" in columns:
        return

    # Add deprecated column with default False
    op.add_column("tools", sa.Column("deprecated", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Remove deprecated column from tools table."""
    inspector = sa.inspect(op.get_bind())

    # Skip if table doesn't exist
    if "tools" not in inspector.get_table_names():
        return

    # Skip if column doesn't exist
    columns = [col["name"] for col in inspector.get_columns("tools")]
    if "deprecated" not in columns:
        return

    op.drop_column("tools", "deprecated")
