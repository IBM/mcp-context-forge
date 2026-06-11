# -*- coding: utf-8 -*-
"""Semantic search service stub.

Placeholder for the full semantic search implementation (issue #2229).
Returns empty results, allowing fallback to keyword search.
"""

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


class SemanticSearchService:
    """Stub semantic search service that returns empty results."""

    async def search_tools(
        self,
        query: str,
        db: Any = None,
        limit: int = 10,
        threshold: float = 0.7,
    ) -> List[Any]:
        """Return empty results — semantic search not yet implemented."""
        logger.debug("Semantic search not available, returning empty results for query: %s", query[:100])
        return []


_instance: Optional[SemanticSearchService] = None


def get_semantic_search_service() -> SemanticSearchService:
    """Get or create the singleton semantic search service."""
    global _instance
    if _instance is None:
        _instance = SemanticSearchService()
    return _instance
