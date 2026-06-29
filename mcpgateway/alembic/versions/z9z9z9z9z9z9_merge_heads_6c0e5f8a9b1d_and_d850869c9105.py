"""merge heads 6c0e5f8a9b1d and d850869c9105

Revision ID: z9z9z9z9z9z9
Revises: 6c0e5f8a9b1d, d850869c9105
Create Date: 2026-06-22 17:39:00.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = 'z9z9z9z9z9z9'
down_revision: Union[str, Sequence[str], None] = ('6c0e5f8a9b1d', 'd850869c9105')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

# Made with Bob
