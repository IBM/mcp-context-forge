"""Merge Protection metrics

Revision ID: ccb256f6ea21
Revises: 6beda57a5998, 14ac971cee42
Create Date: 2025-09-20 15:13:37.220379

"""

# Standard
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "ccb256f6ea21"
down_revision: Union[str, Sequence[str], None] = ("6beda57a5998", "14ac971cee42")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
