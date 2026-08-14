"""merge grpc/sql/debug platform and upstream oauth fixes

Revision ID: f000baa38a15
Revises: 7ab59991e017, c8d9e0f1a2b3
Create Date: 2026-08-06 16:10:34.021701

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f000baa38a15'
down_revision: Union[str, Sequence[str], None] = ('7ab59991e017', 'c8d9e0f1a2b3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
