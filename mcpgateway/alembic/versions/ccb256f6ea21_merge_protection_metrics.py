"""Merge Protection metrics

Revision ID: ccb256f6ea21
Revises: 6beda57a5998, e182847d89e6
Create Date: 2025-09-20 15:13:37.220379

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ccb256f6ea21'
down_revision: Union[str, Sequence[str], None] = ('6beda57a5998', 'e182847d89e6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
