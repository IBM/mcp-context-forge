"""merge heads

Revision ID: 631ae0b46de5
Revises: b1b2b3b4b5b6, c3d4e5f6a7b8
Create Date: 2026-02-13 15:01:59.364990

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '631ae0b46de5'
down_revision: Union[str, Sequence[str], None] = ('b1b2b3b4b5b6', 'c3d4e5f6a7b8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
