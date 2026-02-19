# -*- coding: utf-8 -*-
"""merge policy engine and latest main

Revision ID: 76b63ffaf38b
Revises: 01225b0e4ad2, x7h8i9j0k1l2
Create Date: 2026-02-19 17:01:04.769050

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '76b63ffaf38b'
down_revision: Union[str, Sequence[str], None] = ('01225b0e4ad2', 'x7h8i9j0k1l2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
