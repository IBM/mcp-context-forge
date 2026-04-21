"""merge token_revocation and uaid heads

Revision ID: cae28b15a507
Revises: aa1b2c3d4e5f, d2b501bf4262
Create Date: 2026-04-21 16:10:45.722681

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "cae28b15a507"
down_revision: Union[str, Sequence[str], None] = ("aa1b2c3d4e5f", "d2b501bf4262")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
