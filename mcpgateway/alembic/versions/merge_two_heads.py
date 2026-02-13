"""merge all outstanding heads

Revision ID: merge_two_heads
Revises: 5126ced48fd0, c3d4e5f6a7b8
Create Date: 2026-02-13

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "merge_two_heads"
down_revision: Union[str, Sequence[str], None] = ("5126ced48fd0", "c3d4e5f6a7b8")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
