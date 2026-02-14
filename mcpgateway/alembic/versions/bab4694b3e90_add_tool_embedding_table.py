"""add_tool_embedding_table

Revision ID: bab4694b3e90
Revises: b1b2b3b4b5b6
Create Date: 2026-02-10 14:11:14.392859

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
try:
    from pgvector.sqlalchemy import Vector
    HAS_PGVECTOR = True
except ImportError:
    HAS_PGVECTOR = False
    Vector = None  # type: ignore[assignment]


# revision identifiers, used by Alembic.
revision: str = 'bab4694b3e90'
down_revision: Union[str, Sequence[str], None] = '5126ced48fd0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add tool_embeddings table with database-specific column types."""
    # Get the database dialect
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    
    # Enable pgvector extension for PostgreSQL
    if dialect_name == 'postgresql':
        op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    
    # Create table with appropriate column type based on database
    if dialect_name == 'postgresql':
        # PostgreSQL: Use Vector type
        op.create_table(
            'tool_embeddings',
            sa.Column('id', sa.String(36), nullable=False),
            sa.Column('tool_id', sa.String(36), nullable=False),
            sa.Column('embedding', Vector(1536), nullable=False),
            sa.Column('model_name', sa.String(255), nullable=False, 
                     server_default='text-embedding-3-small'),
            sa.Column('created_at', sa.DateTime(timezone=True), 
                     server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), 
                     server_default=sa.text('now()'), nullable=False),
            sa.PrimaryKeyConstraint('id', name='pk_tool_embeddings'),
            sa.ForeignKeyConstraint(['tool_id'], ['tools.id'], 
                                   name='fk_tool_embeddings_tool_id',
                                   ondelete='CASCADE'),
        )
        
        # Add vector similarity index for PostgreSQL (optional but recommended)
        op.create_index(
            'idx_tool_embeddings_vector',
            'tool_embeddings',
            ['embedding'],
            postgresql_using='ivfflat',
            postgresql_with={'lists': 100},
        )
    else:
        # SQLite: Use JSON
        op.create_table(
            'tool_embeddings',
            sa.Column('id', sa.String(36), nullable=False),
            sa.Column('tool_id', sa.String(36), nullable=False),
            sa.Column('embedding', sa.JSON, nullable=False),
            sa.Column('model_name', sa.String(255), nullable=False, 
                     server_default='text-embedding-3-small'),
            sa.Column('created_at', sa.DateTime(timezone=True), 
                     server_default=sa.text("(datetime('now'))"), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), 
                     server_default=sa.text("(datetime('now'))"), nullable=False),
            sa.PrimaryKeyConstraint('id', name='pk_tool_embeddings'),
            sa.ForeignKeyConstraint(['tool_id'], ['tools.id'], 
                                   name='fk_tool_embeddings_tool_id',
                                   ondelete='CASCADE'),
        )
    
    # Create index for tool_id (works for both databases)
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