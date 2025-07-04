# -*- coding: utf-8 -*-
"""Add enabled and reachable columns in tools and gateways tables and migrate data (is_active ➜ enabled,reachable).

Revision ID: e75490e949b1
Revises: e4fc04d1a442
Create Date: 2025‑07‑02 17:12:40.678256
"""

# Standard
from typing import Sequence, Union

# Third-Party
import sqlalchemy as sa

# First-Party
# Alembic / SQLAlchemy
from alembic import op

# Revision identifiers.
revision: str = "e75490e949b1"
down_revision: Union[str, Sequence[str], None] = "e4fc04d1a442"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    """
    Renames 'is_active' to 'enabled' and adds a new 'reachable' column (default True)
    in both 'tools' and 'gateways' tables.
    """
    op.alter_column('tools', 'is_active', new_column_name='enabled')
    op.add_column('tools', sa.Column('reachable', sa.Boolean(), nullable=False, server_default=sa.true()))

    op.alter_column('gateways', 'is_active', new_column_name='enabled')
    op.add_column('gateways', sa.Column('reachable', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    """
    Reverts the changes by renaming 'enabled' back to 'is_active'
    and dropping the 'reachable' column in both 'tools' and 'gateways' tables.
    """
    op.alter_column('tools', 'enabled', new_column_name='is_active')
    op.drop_column('tools', 'reachable')

    op.alter_column('gateways', 'enabled', new_column_name='is_active')
    op.drop_column('gateways', 'reachable')
