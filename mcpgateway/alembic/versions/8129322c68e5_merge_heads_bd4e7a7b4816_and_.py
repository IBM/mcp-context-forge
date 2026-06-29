"""merge_heads_bd4e7a7b4816_and_e28566875fa4

Revision ID: 8129322c68e5
Revises: bd4e7a7b4816, e28566875fa4
Create Date: 2026-06-04 22:00:37.668823

"""

# Standard
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "8129322c68e5"
down_revision: Union[str, Sequence[str], None] = ("bd4e7a7b4816", "e28566875fa4")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
