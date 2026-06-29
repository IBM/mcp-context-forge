"""merge_multiple_heads

Revision ID: d80ddfa65ddb
Revises: 296db37fd26c, a7f3c9e1b2d4
Create Date: 2026-04-07 14:07:09.561726

"""

# Standard
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "d80ddfa65ddb"
down_revision: Union[str, Sequence[str], None] = ("296db37fd26c", "a7f3c9e1b2d4")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
