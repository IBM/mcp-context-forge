"""add_canonical_url_to_servers

Revision ID: 1d92a8045125
Revises: e28566875fa4
Create Date: 2026-05-22 16:51:08.269206

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "1d92a8045125"
down_revision: Union[str, Sequence[str], None] = "e28566875fa4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add canonical_url column to servers table.

    Idempotent: checks table and column existence before adding.
    No hermetic downgrade needed — purely additive column with no settings dependency.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "servers" not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns("servers")]
    if "canonical_url" not in columns:
        op.add_column(
            "servers",
            sa.Column("canonical_url", sa.String(767), nullable=True),
        )


def downgrade() -> None:
    """Remove canonical_url column from servers table.

    Idempotent: checks table and column existence before dropping.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "servers" not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns("servers")]
    if "canonical_url" in columns:
        op.drop_column("servers", "canonical_url")
