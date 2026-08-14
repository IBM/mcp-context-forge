"""merge candidate schema protection and upstream plugin permission

Revision ID: d5e6f7a8b9c1
Revises: 9a8b7c6d5e4f, e4f5a6b7c8d9
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5e6f7a8b9c1'
down_revision: Union[str, Sequence[str], None] = ('9a8b7c6d5e4f', 'e4f5a6b7c8d9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
