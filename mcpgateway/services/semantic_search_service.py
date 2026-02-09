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
import time
import json
from typing import List, Optional, Dict, Tuple

# First-Party
from mcpgateway.schemas import ToolSearchResult
from mcpgateway.utils.redis_client import get_redis_client

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

    CACHE_TTL_SECONDS = 60

    def __init__(self):
        """Initialize semantic search service with embedding and vector search services."""
        self.embedding_service = EmbeddingService()
        self.vector_search_service = VectorSearchService()

        # Fallback memory cache
        self._memory_cache: Dict[str, Tuple[float, List[ToolSearchResult]]] = {}

    # Helpers

    def _nornalize_query(self, query: str) -> str:
        return query.strip().lower()
    
    def _make_cache_key(self, query: str, limit: int, threshold: Optional[float]) -> str:
        return f"semantic:{query}:{limit}:{threshold}"
    
    # Memory cache

    def _get_memory_cache(self, key: str) -> Optional[List[ToolSearchResult]]:
        entry = self._memory_cache.get(key)
        if not entry:
            return None
        
        expires_at, results = entry
        
        if time.time() > expires_at:
            del self._memory_cache[key]
            return None
        
        return results
    
    def _set_memory_cache(self, key: str, results: List[ToolSearchResult]) -> None:
        self._memory_cache[key] = (
            time.time() + self.CACHE_TTL_SECONDS,
            results,
        )

    # Redis cache

    async def _get_redis_cache(self, key: str) -> Optional[List[ToolSearchResult]]:
        client = await get_redis_client()
        if not client:
            return None
        
        raw = await client.get(key)
        if not raw:
            return None
        
        # deserialize
        data = json.loads(raw)
        return [ToolSearchResult(**item) for item in data]
    
    async def _set_redis_cache(self, key: str, results: List[ToolSearchResult]) -> None:
        client = await get_redis_client()
        if not client:
            return
        
        payload = json.dumps([r.model_dump() for r in results])

        await client.set(
            key,
            payload,
            ex=self.CACHE_TTL_SECONDS,
        )

    # Public API

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

        normalized_query = self._normalize_query(query)
        cache_key = self._make_cache_key(normalized_query, limit, threshold)

        # 1. Try Redis first

        cached = await self._get_redis_cache(cache_key)
        if cached is not None:
            return cached
        
        # 2. Try memory fallback

        cached = self._get_memory_cache(cache_key)
        if cached is not None:
            return cached
        
        # 3. Compute normally

        # Generate embedding for query
        embedding = await self.embedding_service.embed_query(normalized_query)

        # Perform vector search
        results = await self.vector_search_service.search_similar_tools(
            embedding=embedding,
            limit=limit,
            threshold=threshold,
        )

        # 4. Store cache
        await self._set_redis_cache(cache_key, results)
        self._set_memory_cache(cache_key, results)
        
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
