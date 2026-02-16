# -*- coding: utf-8 -*-
"""merge heads after policy engine rebase

Revision ID: 01225b0e4ad2
Revises: 94ab1dd2f2b1, w6g7h8i9j0k1
Create Date: 2026-02-16 14:06:55.914060

"""

# Standard
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "01225b0e4ad2"
down_revision: Union[str, Sequence[str], None] = ("94ab1dd2f2b1", "w6g7h8i9j0k1")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
