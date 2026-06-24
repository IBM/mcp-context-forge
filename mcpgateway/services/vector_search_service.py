# -*- coding: utf-8 -*-
"""Vector search service stub.

Placeholder for the full vector search implementation (issue #2229).
Provides embedding retrieval and similarity search over tool embeddings.
"""

import logging
import math
from typing import Any, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _cosine_similarity_numpy(vec_a: List[float], vec_b: List[float]) -> float:
    """Compute cosine similarity between two vectors without numpy."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorSearchService:
    """Stub vector search service for tool embeddings."""

    def __init__(self, db: Optional[Session] = None):
        """Initialize the stub vector search service.

        Args:
            db: Optional database session used by embedding lookups.
        """
        self.db = db

    def get_tool_embedding(self, db: Session, tool_id: str) -> Any:
        """Retrieve the stored embedding for a tool.

        Returns None when no embedding is found (stub always returns None).
        """
        try:
            from mcpgateway.db import ToolEmbedding

            result = db.query(ToolEmbedding).filter(ToolEmbedding.tool_id == tool_id).first()
            return result
        except Exception as e:
            logger.debug("Failed to get tool embedding for %s: %s", tool_id, e)
            return None

    async def search_similar_tools(
        self,
        embedding: List[float],
        limit: int = 10,
        db: Optional[Session] = None,
    ) -> List[Any]:
        """Search for tools similar to the given embedding vector.

        Returns empty list when no embeddings are available.
        """
        session = db or self.db
        if session is None:
            return []

        try:
            from mcpgateway.db import ToolEmbedding

            all_embeddings = session.query(ToolEmbedding).all()
            if not all_embeddings:
                return []

            scored = []
            for te in all_embeddings:
                sim = _cosine_similarity_numpy(embedding, te.embedding)
                scored.append((te, sim))
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:limit]
        except Exception as e:
            logger.debug("Vector similarity search failed: %s", e)
            return []
