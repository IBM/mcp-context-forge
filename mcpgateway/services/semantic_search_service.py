# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/semantic_search_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Team C

Semantic Search Service for Tool Discovery.

This module provides semantic search capabilities for tool discovery using
embeddings and vector similarity search. It serves as an abstraction layer
over the embedding generation and vector search implementations.

The service coordinates between:
- Embedding generation (Team A implementation)
- Vector similarity search (Team B implementation with pgvector)
"""

# Standard
from typing import List, Optional

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.schemas import ToolSearchResult


class EmbeddingService:
    """Service for generating text embeddings.

    This is a stub interface for Team A's embedding implementation.
    The actual implementation will be provided by Team A.
    """

    async def embed_query(self, query: str) -> List[float]:
        """Generate embedding vector for a query string.

        Args:
            query: The text query to embed

        Returns:
            List of floats representing the embedding vector

        Raises:
            RuntimeError: If embedding generation fails
        """
        # TODO: Team A will implement actual embedding generation
        # For now, return a stub embedding (768-dimensional vector of zeros)
        # This allows Team C to develop and test the API endpoint structure
        return [0.0] * 768


class VectorSearchService:
    """Service for vector similarity search over tool embeddings.

    This is a stub interface for Team B's vector search implementation.
    The actual implementation will use PostgreSQL with pgvector extension.
    """

    async def search_similar_tools(
        self,
        embedding: List[float],
        limit: int = 10,
        threshold: Optional[float] = None,
    ) -> List[ToolSearchResult]:
        """Search for tools similar to the given embedding vector.

        Args:
            embedding: Query embedding vector
            limit: Maximum number of results to return
            threshold: Optional similarity threshold (0-1). Only return results
                      with similarity >= threshold

        Returns:
            List of ToolSearchResult objects ranked by similarity (highest first)

        Raises:
            RuntimeError: If vector search fails
        """
        # TODO: Team B will implement actual vector search with pgvector
        # For now, return empty results to allow API development
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

        return results


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
