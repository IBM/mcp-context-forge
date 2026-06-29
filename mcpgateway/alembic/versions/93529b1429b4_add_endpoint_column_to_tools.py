"""add_endpoint_column_to_tools

Revision ID: 93529b1429b4
Revises: d80ddfa65ddb
Create Date: 2026-04-20 17:38:19.787236

Add endpoint column to tools table to support URL construction from gateway URL + endpoint.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "93529b1429b4"
down_revision: Union[str, Sequence[str], None] = "d80ddfa65ddb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add endpoint column to tools table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if fresh database (tables created via create_all + stamp)
    if not inspector.has_table("tools"):
        return

    # Add endpoint column if it doesn't exist
    columns = [col["name"] for col in inspector.get_columns("tools")]
    if "endpoint" not in columns:
        op.add_column("tools", sa.Column("endpoint", sa.String(767), nullable=True))


def downgrade() -> None:
    """Remove endpoint column from tools table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if fresh database
    if not inspector.has_table("tools"):
        return

    # Remove endpoint column if it exists
    columns = [col["name"] for col in inspector.get_columns("tools")]
    if "endpoint" in columns:
        op.drop_column("tools", "endpoint")


# Made with Bob
