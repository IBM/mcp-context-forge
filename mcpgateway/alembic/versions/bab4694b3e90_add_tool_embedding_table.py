"""add_tool_embedding_table

Revision ID: bab4694b3e90
<<<<<<< Updated upstream
Revises: 5126ced48fd0
=======
Revises: 8a16a77260f0
>>>>>>> Stashed changes
Create Date: 2026-02-10 14:11:14.392859

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
try:
    from pgvector.sqlalchemy import Vector # type: ignore
<<<<<<< Updated upstream
except ImportError:
    Vector = None
=======
    HAS_PGVECTOR = True
except ImportError:
    Vector = None
    HAS_PGVECTOR = False
>>>>>>> Stashed changes


# revision identifiers, used by Alembic.
revision: str = 'bab4694b3e90'
down_revision: Union[str, Sequence[str], None] = '8a16a77260f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add tool_embeddings table with database-specific column types."""
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == 'postgresql':
        op.execute('CREATE EXTENSION IF NOT EXISTS vector')

        # Check for pgvector presence
        if not HAS_PGVECTOR:
            raise ImportError(
                "pgvector is required for PostgreSQL. "
                "Install with: pip install pgvector"
            )

        # Import Vector only here
        from pgvector.sqlalchemy import Vector as PgVector
        embedding_col = sa.Column('embedding', PgVector(1536), nullable=False)
    else:
        embedding_col = sa.Column('embedding', sa.JSON, nullable=False)

    op.create_table(
        'tool_embeddings',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('tool_id', sa.String(36), nullable=False),
        embedding_col,
        sa.Column('model_name', sa.String(255), nullable=False,
                 server_default='text-embedding-3-small'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                 server_default=sa.text('now()' if dialect_name == 'postgresql'
                                       else "(datetime('now'))"),
                 nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                 server_default=sa.text('now()' if dialect_name == 'postgresql'
                                       else "(datetime('now'))"),
                 nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_tool_embeddings'),
        sa.ForeignKeyConstraint(['tool_id'], ['tools.id'],
                               name='fk_tool_embeddings_tool_id',
                               ondelete='CASCADE'),
    )

    # Add indexes
    if dialect_name == 'postgresql':
        op.create_index(
            'idx_tool_embeddings_hnsw',
            'tool_embeddings',
            ['embedding'],
            postgresql_using='ivfflat',
            postgresql_with={'lists': 100},
        )

    op.create_index('idx_tool_embeddings_tool_id', 'tool_embeddings', ['tool_id'])


def downgrade() -> None:
    """Drop tool_embeddings table."""
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    inspector = sa.inspect(bind)
    
    # Check if table exists before trying to drop it
    if 'tool_embeddings' not in inspector.get_table_names():
        return
    
    # Get existing indexes
    existing_indexes = {idx['name'] for idx in inspector.get_indexes('tool_embeddings')}
    
    # Drop indexes only if they exist
    if 'idx_tool_embeddings_tool_id' in existing_indexes:
        op.drop_index('idx_tool_embeddings_tool_id', table_name='tool_embeddings')
    
    if dialect_name == 'postgresql' and 'idx_tool_embeddings_vector' in existing_indexes:
        op.drop_index('idx_tool_embeddings_vector', table_name='tool_embeddings')
    
    # Drop table
    op.drop_table('tool_embeddings')