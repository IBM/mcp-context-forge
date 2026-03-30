"""add health_check_enabled to gateways

Revision ID: b46886f8f835
Revises: 225bde88217e
Create Date: 2026-03-30 08:45:59.978289

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b46886f8f835"
down_revision: Union[str, Sequence[str], None] = "225bde88217e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add health_check_enabled column to gateways table."""
    op.add_column(
        "gateways",
        sa.Column("health_check_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    """Remove health_check_enabled column from gateways table."""
    op.drop_column("gateways", "health_check_enabled")
