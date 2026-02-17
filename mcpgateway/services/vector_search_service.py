# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/vector_search_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Vector Search Service for semantic similarity search over tool embeddings.

Primary backend (PostgreSQL):
    Uses pgvector's native cosine distance operator (<=>) for similarity search.
    This leverages the HNSW index on the tool_embeddings table for fast
    approximate nearest-neighbor lookup.

Fallback backend (SQLite):
    For development and testing where pgvector is not available, loads embeddings
    into memory and computes cosine similarity using numpy.
"""

# Standard
import logging
from typing import List, Optional

# Third-Party
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Tool, ToolEmbedding
from mcpgateway.schemas import ToolSearchResult

logger = logging.getLogger(__name__)


def _cosine_similarity_numpy(vec_a: List[float], vec_b: List[float]) -> float:
    """Compute cosine similarity between two vectors using numpy.

    SQLite fallback only — on PostgreSQL, pgvector handles this in SQL.

    Args:
        vec_a: First embedding vector.
        vec_b: Second embedding vector.

    Returns:
        Cosine similarity score clamped to [0.0, 1.0].
    """
    import numpy as np  # noqa: E402  # Lazy import — transitive dep of pgvector, not declared in pyproject.toml

    a = np.asarray(vec_a, dtype=np.float64)
    b = np.asarray(vec_b, dtype=np.float64)

    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    similarity = float(np.dot(a, b) / (norm_a * norm_b))
    return max(0.0, min(1.0, similarity))


class VectorSearchService:
    """Service for vector similarity search over tool embeddings.

    Uses pgvector for PostgreSQL (production) with HNSW-indexed cosine distance.
    Falls back to numpy-based cosine similarity on SQLite (dev/test).
    """

    def __init__(self, db: Optional[Session] = None):
        """Initialize the vector search service.

        Args:
            db: Optional database session for queries.
        """
        self.db = db

    async def search_similar_tools(
        self,
        embedding: List[float],
        limit: int = 10,
        threshold: Optional[float] = None,
        db: Optional[Session] = None,
    ) -> List[ToolSearchResult]:
        """Search for tools similar to the given embedding vector.

        On PostgreSQL, uses pgvector's cosine_distance() which leverages the
        HNSW index for fast approximate nearest-neighbor search.
        On SQLite, falls back to in-memory numpy computation.

        Args:
            embedding: Query embedding vector (1536-dimensional).
            limit: Maximum number of results to return (1-50).
            threshold: Optional similarity threshold (0-1).
                Only return results with similarity >= threshold.
            db: Optional database session. Falls back to self.db.

        Returns:
            List of ToolSearchResult objects ranked by similarity (highest first).

        Raises:
            RuntimeError: If no database session is available or vector search fails.
        """
        session = db or self.db
        if session is None:
            raise RuntimeError("No database session available for vector search")

        if not embedding:
            logger.warning("Empty embedding provided for similarity search")
            return []

        try:
            dialect_name = session.get_bind().dialect.name
            if dialect_name == "postgresql":
                return self._search_postgresql(session, embedding, limit, threshold)
            else:
                return self._search_sqlite(session, embedding, limit, threshold)
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            raise RuntimeError(f"Vector search failed: {e}") from e

    def _search_postgresql(
        self,
        db: Session,
        embedding: List[float],
        limit: int,
        threshold: Optional[float],
    ) -> List[ToolSearchResult]:
        """Similarity search using pgvector's native cosine distance operator.

        Uses the <=> operator which leverages the HNSW index for fast ANN search.
        All computation happens in PostgreSQL — no Python-side vector math.
        """
        distance_expr = ToolEmbedding.embedding.cosine_distance(embedding)

        query = (
            select(
                ToolEmbedding,
                Tool,
                (1 - distance_expr).label("similarity"),
            )
            .join(Tool, ToolEmbedding.tool_id == Tool.id)
            .filter(Tool.enabled.is_(True))
        )

        if threshold is not None:
            query = query.filter(distance_expr <= (1 - threshold))

        query = query.order_by(distance_expr.asc()).limit(limit)
        rows = db.execute(query).all()

        return [
            ToolSearchResult(
                tool_name=tool.name,
                description=tool.description,
                server_id=tool.gateway_id,
                server_name=tool.gateway.name if tool.gateway else None,
                similarity_score=max(0.0, min(1.0, float(similarity))),
            )
            for _tool_embedding, tool, similarity in rows
        ]

    def _search_sqlite(
        self,
        db: Session,
        embedding: List[float],
        limit: int,
        threshold: Optional[float],
    ) -> List[ToolSearchResult]:
        """Fallback similarity search for SQLite (dev/test only).

        Loads all embeddings into memory and computes cosine similarity with numpy.
        """
        query = select(ToolEmbedding, Tool).join(Tool, ToolEmbedding.tool_id == Tool.id).filter(Tool.enabled.is_(True))
        rows = db.execute(query).all()

        if not rows:
            return []

        scored: List[tuple[float, ToolEmbedding, Tool]] = []
        for tool_embedding, tool in rows:
            similarity = _cosine_similarity_numpy(embedding, tool_embedding.embedding)
            if threshold is not None and similarity < threshold:
                continue
            scored.append((similarity, tool_embedding, tool))

        scored.sort(key=lambda x: x[0], reverse=True)
        scored = scored[:limit]

        return [
            ToolSearchResult(
                tool_name=tool.name,
                description=tool.description,
                server_id=tool.gateway_id,
                server_name=tool.gateway.name if tool.gateway else None,
                similarity_score=similarity,
            )
            for similarity, _tool_embedding, tool in scored
        ]

    def get_tool_embedding(
        self,
        db: Session,
        tool_id: str,
    ) -> Optional[ToolEmbedding]:
        """Retrieve stored embedding for a tool.

        Args:
            db: Database session.
            tool_id: ID of the tool.

        Returns:
            ToolEmbedding if found, None otherwise.
        """
        return db.query(ToolEmbedding).filter(ToolEmbedding.tool_id == tool_id).first()

    def delete_tool_embedding(
        self,
        db: Session,
        tool_id: str,
    ) -> bool:
        """Delete stored embedding for a tool.

        Args:
            db: Database session.
            tool_id: ID of the tool.

        Returns:
            True if deleted, False if not found.
        """
        embedding = self.get_tool_embedding(db, tool_id)
        if embedding:
            db.delete(embedding)
            db.commit()
            logger.info(f"Deleted embedding for tool {tool_id}")
            return True
        logger.warning(f"No embedding found for tool {tool_id}")
        return False
