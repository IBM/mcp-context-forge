# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/semantic_search_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Team C

Semantic Search Service for Tool Discovery.

This module orchestrates semantic search by coordinating between:
- Team A's embedding service (mcpgateway/services/embedding_service.py)
- Team B's vector search service (mcpgateway/services/vector_search_service.py)

Team C is responsible for:
- Validating search parameters
- Orchestrating the embedding + search workflow
- Exposing the GET /tools/semantic endpoint (in main.py)
"""

# Standard
from typing import List, Optional

# First-Party
from mcpgateway.schemas import ToolSearchResult

# Import Team A's embedding service
# Team A will implement embed_query() in this file
try:
    from mcpgateway.services.embedding_service import EmbeddingService
except ImportError:
    # Fallback stub if Team A hasn't created the file yet
    class EmbeddingService:
        """Temporary stub until Team A implements embedding_service.py"""
        async def embed_query(self, query: str) -> List[float]:
            return [0.0] * 768

# Import Team B's vector search service
# Team B will implement search_similar_tools() in this file
try:
    from mcpgateway.services.vector_search_service import VectorSearchService
except ImportError:
    # Fallback stub if Team B hasn't created the file yet
    class VectorSearchService:
        """Temporary stub until Team B implements vector_search_service.py"""
        async def search_similar_tools(
            self,
            embedding: List[float],
            limit: int = 10,
            threshold: Optional[float] = None,
        ) -> List[ToolSearchResult]:
            return []


class SemanticSearchService:
    """Orchestrates semantic search operations.

    Coordinates embedding generation and vector search to provide
    semantic tool discovery capabilities.
    """

    def __init__(self):
        """Initialize semantic search service with embedding and vector search services."""
        self.embedding_service = EmbeddingService()
        self.vector_search_service = VectorSearchService()

    async def search_tools(
        self,
        query: str,
        limit: int = 10,
        threshold: Optional[float] = None,
    ) -> List[ToolSearchResult]:
        """Perform semantic search for tools matching the query.

        Args:
            query: Natural language search query
            limit: Maximum number of results (1-50)
            threshold: Optional similarity threshold (0-1)

        Returns:
            List of matching tools ranked by relevance

        Raises:
            ValueError: If parameters are invalid
            RuntimeError: If search operation fails
        """
        # Validate parameters
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        if limit < 1 or limit > 50:
            raise ValueError("Limit must be between 1 and 50")

        if threshold is not None and (threshold < 0.0 or threshold > 1.0):
            raise ValueError("Threshold must be between 0.0 and 1.0")

        # Generate embedding for query
        embedding = await self.embedding_service.embed_query(query.strip())

        # Perform vector search
        results = await self.vector_search_service.search_similar_tools(
            embedding=embedding,
            limit=limit,
            threshold=threshold,
        )

        # Return empty list if no matches
        if not results:
            return []
        
        # Ensure all results have a similarity score
        safe_results: List[ToolSearchResult] = []
        for r in results:
            if getattr(r, "score", None) is not None:
                safe_results.append(r)

        # Enforce threshold even if vector service didn't
        if threshold is not None:
            safe_results = [r for r in safe_results if r.score >= threshold]

        # Higher score = higher relevance (guarantee ranking)
        safe_results.sort(key=lambda r: r.score, reverse=True)

        # Respect limit strictly
        return safe_results[:limit]


# Singleton instance
_semantic_search_service: Optional[SemanticSearchService] = None


def get_semantic_search_service() -> SemanticSearchService:
    """Get or create the singleton SemanticSearchService instance.

    Returns:
        SemanticSearchService instance
    """
    global _semantic_search_service
    if _semantic_search_service is None:
        _semantic_search_service = SemanticSearchService()
    return _semantic_search_service
