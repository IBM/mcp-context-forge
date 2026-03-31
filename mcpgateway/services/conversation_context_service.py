"""Conversation context extraction service for the context-aware recommender.

Analyses a user's recent chat history by passing the concatenated messages directly
into the semantic search service, returning tools already ranked by similarity to the
conversation. Results are cached in Redis with a short TTL.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from mcpgateway.config import settings
from mcpgateway.schemas import ToolSearchResult
from mcpgateway.services.mcp_client_chat_service import ChatHistoryManager
from mcpgateway.utils.redis_client import get_redis_client

logger = logging.getLogger(__name__)


class ConversationContextService:
    """Extracts relevant tools from a user's recent conversation history via semantic search.

    Reads the last N chat messages, concatenates their content, and passes the text
    directly to SemanticSearchService so that embedding similarity does the matching.
    Results are cached in Redis for 5 minutes.

    Examples:
        >>> svc = ConversationContextService()
        >>> isinstance(svc, ConversationContextService)
        True
    """

    def __init__(self) -> None:
        """Initialise with an empty in-memory cache."""
        self._memory_cache: Dict[str, Tuple[float, List[ToolSearchResult]]] = {}

    async def extract_context(self, user_id: str, db: Session, n: int = 10, limit: int = 10) -> List[ToolSearchResult]:
        """Return tools semantically relevant to a user's recent conversation.

        Checks Redis cache first (5-min TTL), then in-memory fallback. On a cache miss,
        fetches the last N messages from the user's Redis-backed chat history, concatenates
        them, and runs a semantic search against the tool embeddings table. The user_id is
        only used as a Redis key to retrieve existing chat history — nothing is written to
        the database by this service.

        Args:
            user_id: Key used to look up the user's chat history in Redis (chat_history:{user_id}).
            db: Active SQLAlchemy session passed through to the semantic search service.
            n: Number of most recent messages to include (default 10).
            limit: Maximum number of tool results to return (default 10).

        Returns:
            List of ToolSearchResult ranked by semantic similarity to the conversation.
            Returns an empty list if the user has no history or if the search fails.

        Examples:
            >>> import asyncio
            >>> svc = ConversationContextService()
            >>> # With no history the service returns an empty list
            >>> # results = asyncio.run(svc.extract_context("unknown_user", db=None))
            >>> # results == []
            True
        """
        cache_key = f"conv_context:{user_id}:{n}:{limit}"

        # 1. Try Redis cache
        client: Optional[Any] = await get_redis_client()
        if client:
            try:
                raw = await client.get(cache_key)
                if raw:
                    data = json.loads(raw)
                    return [ToolSearchResult(**item) for item in data]
            except Exception as exc:
                logger.debug("Redis cache miss for conv_context %s: %s", cache_key, exc)

        # 2. Try in-memory fallback
        entry = self._memory_cache.get(cache_key)
        if entry:
            expires_at, results = entry
            if time.monotonic() < expires_at:
                return results

        # 3. Fetch chat history from Redis — return empty list if unavailable
        history: List[Dict[str, str]] = []
        try:
            manager = ChatHistoryManager(redis_client=client)
            history = await manager.get_history(user_id)
        except Exception as exc:
            logger.warning("Could not fetch chat history for %s: %s", user_id, exc)

        if not history:
            return []

        # 4. Concatenate last n messages and run semantic search against tool embeddings
        messages = history[-n:]
        combined_text = " ".join(m.get("content", "") for m in messages).strip()
        if not combined_text:
            return []

        results: List[ToolSearchResult] = []
        try:
            from mcpgateway.services.semantic_search_service import get_semantic_search_service  # pylint: disable=import-outside-toplevel

            search_svc = get_semantic_search_service()
            results = await search_svc.search_tools(combined_text[:8192], db, limit)
        except Exception as exc:
            logger.warning("Semantic search failed for conversation context %s: %s", cache_key, exc)

        # 5. Populate caches
        ttl = settings.recommendation_context_cache_ttl
        if client:
            try:
                await client.set(cache_key, json.dumps([r.model_dump() for r in results]), ex=ttl)
            except Exception as exc:
                logger.debug("Failed to write conv_context to Redis: %s", exc)
        self._memory_cache[cache_key] = (time.monotonic() + ttl, results)

        return results


_service: Optional[ConversationContextService] = None


def get_conversation_context_service() -> ConversationContextService:
    """Return the singleton ConversationContextService instance.

    Returns:
        ConversationContextService: The shared service instance.

    Examples:
        >>> svc = get_conversation_context_service()
        >>> isinstance(svc, ConversationContextService)
        True
    """
    global _service
    if _service is None:
        _service = ConversationContextService()
    return _service
