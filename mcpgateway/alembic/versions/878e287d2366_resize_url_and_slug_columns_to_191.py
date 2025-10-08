""""resize url and slug columns to 191"

Revision ID: 878e287d2366
Revises: 2f67b12600b4
Create Date: 2025-10-08 09:08:35.363100

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '878e287d2366'
down_revision: Union[str, Sequence[str], None] = '2f67b12600b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Truncate existing values longer than 191 chars
    op.execute("""
        UPDATE gateways
        SET slug = LEFT(slug, 191),
            url = LEFT(url, 191)
        WHERE LENGTH(slug) > 191 OR LENGTH(url) > 191;
    """)

    # Resize columns to String(191)
    op.alter_column(
        'gateways',
        'slug',
        existing_type=sa.String(length=255),
        type_=sa.String(length=191),
        existing_nullable=False
    )
    op.alter_column(
        'gateways',
        'url',
        existing_type=sa.String(length=767),
        type_=sa.String(length=191),
        existing_nullable=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        'gateways',
        'slug',
        existing_type=sa.String(length=191),
        type_=sa.String(length=255),
        existing_nullable=False
    )
    op.alter_column(
        'gateways',
        'url',
        existing_type=sa.String(length=191),
        type_=sa.String(length=767),
        existing_nullable=False
    )