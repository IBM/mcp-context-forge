"""add_hnsw_index_to_tool_embeddings

Revision ID: c3d4e5f6a7b8
Revises: bab4694b3e90
Create Date: 2026-02-12 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "bab4694b3e90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace IVFFlat index with HNSW index on tool_embeddings.embedding."""
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name != "postgresql":
        return  # SQLite: no vector indexes

    inspector = sa.inspect(bind)
    if "tool_embeddings" not in inspector.get_table_names():
        return

    existing = {idx["name"] for idx in inspector.get_indexes("tool_embeddings")}

    # Drop old IVFFlat index if present
    if "idx_tool_embeddings_vector" in existing:
        op.drop_index("idx_tool_embeddings_vector", table_name="tool_embeddings")

    # Create HNSW index (skip if already exists)
    if "idx_tool_embeddings_hnsw" not in existing:
        op.create_index(
            "idx_tool_embeddings_hnsw",
            "tool_embeddings",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )


def downgrade() -> None:
    """Revert to IVFFlat index on tool_embeddings.embedding."""
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name != "postgresql":
        return

    inspector = sa.inspect(bind)
    if "tool_embeddings" not in inspector.get_table_names():
        return

    existing = {idx["name"] for idx in inspector.get_indexes("tool_embeddings")}

    if "idx_tool_embeddings_hnsw" in existing:
        op.drop_index("idx_tool_embeddings_hnsw", table_name="tool_embeddings")

    if "idx_tool_embeddings_vector" not in existing:
        op.create_index(
            "idx_tool_embeddings_vector",
            "tool_embeddings",
            ["embedding"],
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
        )
