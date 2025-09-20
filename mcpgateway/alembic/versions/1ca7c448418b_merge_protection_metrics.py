"""Merge protection metrics

Revision ID: 1ca7c448418b
Revises: 6beda57a5998, e182847d89e6
Create Date: 2025-09-20 13:52:51.722245

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1ca7c448418b'
down_revision: Union[str, Sequence[str], None] = ('6beda57a5998', 'e182847d89e6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
