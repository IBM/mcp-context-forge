"""" resize url and slug columns to 191"

Revision ID: 878e287d2366
Revises: 3c89a45f32e5
Create Date: 2025-10-08 09:08:35.363100

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '878e287d2366'
down_revision: Union[str, Sequence[str], None] = '3c89a45f32e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Get database dialect for dialect-specific operations
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    # Truncate existing values longer than 191 chars using dialect-appropriate functions
    if dialect_name == 'sqlite':
        # SQLite uses SUBSTR and LENGTH
        op.execute("""
            UPDATE gateways
            SET slug = SUBSTR(slug, 1, 191),
                url = SUBSTR(url, 1, 191)
            WHERE LENGTH(slug) > 191 OR LENGTH(url) > 191;
        """)
    elif dialect_name == 'postgresql':
        # PostgreSQL supports LEFT and CHAR_LENGTH
        op.execute("""
            UPDATE gateways
            SET slug = LEFT(slug, 191),
                url = LEFT(url, 191)
            WHERE CHAR_LENGTH(slug) > 191 OR CHAR_LENGTH(url) > 191;
        """)
    elif dialect_name == 'mysql':
        # MySQL supports LEFT and CHAR_LENGTH (character-based, not byte-based)
        op.execute("""
            UPDATE gateways
            SET slug = LEFT(slug, 191),
                url = LEFT(url, 191)
            WHERE CHAR_LENGTH(slug) > 191 OR CHAR_LENGTH(url) > 191;
        """)
    else:
        # Fallback for other databases
        op.execute("""
            UPDATE gateways
            SET slug = SUBSTR(slug, 1, 191),
                url = SUBSTR(url, 1, 191)
            WHERE LENGTH(slug) > 191 OR LENGTH(url) > 191;
        """)

    # Resize columns to String(191)
    # SQLite requires batch operations for ALTER COLUMN
    if dialect_name == 'sqlite':
        with op.batch_alter_table('gateways', schema=None) as batch_op:
            batch_op.alter_column(
                'slug',
                existing_type=sa.String(length=255),
                type_=sa.String(length=191),
                existing_nullable=False
            )
            batch_op.alter_column(
                'url',
                existing_type=sa.String(length=767),
                type_=sa.String(length=191),
                existing_nullable=False
            )
    else:
        # PostgreSQL and MySQL support direct ALTER COLUMN
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
    # Get database dialect for dialect-specific operations
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    # SQLite requires batch operations for ALTER COLUMN
    if dialect_name == 'sqlite':
        with op.batch_alter_table('gateways', schema=None) as batch_op:
            batch_op.alter_column(
                'slug',
                existing_type=sa.String(length=191),
                type_=sa.String(length=255),
                existing_nullable=False
            )
            batch_op.alter_column(
                'url',
                existing_type=sa.String(length=191),
                type_=sa.String(length=767),
                existing_nullable=False
            )
    else:
        # PostgreSQL and MySQL support direct ALTER COLUMN
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
