# -*- coding: utf-8 -*-
"""remove original_name_slug and added custom_name

Revision ID: c9dd86c0aac9
Revises: add_oauth_tokens_table
Create Date: 2025-08-19 15:15:26.509036

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c9dd86c0aac9"
down_revision: Union[str, Sequence[str], None] = "add_oauth_tokens_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Remove original_name_slug column
    op.alter_column("tools", "original_name_slug", new_column_name="custom_name_slug")

    # Add custom_name column
    op.add_column("tools", sa.Column("custom_name", sa.String(), nullable=True))
    op.execute("UPDATE tools SET custom_name = original_name")
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # Remove custom_name column
    op.drop_column("tools", "custom_name")

    # Add original_name_slug column back
    op.alter_column("tools", "custom_name_slug", new_column_name="original_name_slug")
    # ### end Alembic commands ###
