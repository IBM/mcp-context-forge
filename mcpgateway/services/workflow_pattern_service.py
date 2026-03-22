"""Workflow pattern detection service for the context-aware recommender.

Builds a tool co-occurrence matrix from historical ToolMetric records and uses it
to recommend tools that are frequently used together with recently used tools.
The matrix is rebuilt once daily via a background asyncio task and cached in Redis.
"""

import asyncio
import json
import logging
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from mcpgateway.config import settings
from mcpgateway.db import Tool, ToolMetric, fresh_db_session
from mcpgateway.schemas import WorkflowRecommendation
from mcpgateway.utils.redis_client import get_redis_client

logger = logging.getLogger(__name__)

COOCCURRENCE_CACHE_KEY = "workflow:cooccurrence_matrix"


class WorkflowPatternService:
    """Detects tool co-occurrence patterns and recommends likely next tools.

    Analyses ToolMetric records to find tool pairs invoked within a configurable
    time window (default 5 minutes). The co-occurrence matrix is a single global
    structure rebuilt once per day across all users and cached in Redis. On first
    deploy the matrix is empty; the service degrades gracefully by returning no
    workflow recommendations until the first rebuild completes.

    Examples:
        >>> svc = WorkflowPatternService()
        >>> isinstance(svc, WorkflowPatternService)
        True
    """

    def __init__(self) -> None:
        """Initialise with an empty in-memory matrix and no background task."""
        self._memory_matrix: Dict[str, Dict[str, int]] = {}
        self._update_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    async def initialize(self) -> None:
        """Start the daily background pattern rebuild task.

        Follows the MetricsBufferService pattern: spawns an asyncio task that runs
        indefinitely until shutdown() is called.

        Examples:
            >>> import asyncio
            >>> svc = WorkflowPatternService()
            >>> # asyncio.run(svc.initialize())
            >>> # svc._update_task is not None
            True
        """
        if self._update_task is None or self._update_task.done():
            self._update_task = asyncio.create_task(self._update_patterns_loop())
            logger.info("WorkflowPatternService background task started")

    async def shutdown(self) -> None:
        """Cancel the background rebuild task.

        Examples:
            >>> import asyncio
            >>> svc = WorkflowPatternService()
            >>> # Safe to call even if initialize() was never called
            True
        """
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
            logger.info("WorkflowPatternService background task stopped")

    async def _update_patterns_loop(self) -> None:
        """Rebuild the co-occurrence matrix immediately, then repeat every 24 hours.

        The matrix is global (all users, all time) so one rebuild per day is sufficient
        to capture meaningful usage patterns without excessive database load.
        """
        while True:
            try:
                await self._rebuild_cooccurrence_matrix()
            except Exception as exc:
                logger.warning("WorkflowPatternService matrix rebuild failed: %s", exc)
            await asyncio.sleep(86400)

    async def _rebuild_cooccurrence_matrix(self) -> None:
        """Query all ToolMetric records and compute pairwise co-occurrence within the time window.

        Two tools co-occur if both were invoked within settings.recommendation_workflow_window_minutes
        of each other. Pairs below settings.recommendation_min_cooccurrence are discarded.
        The filtered matrix is persisted to Redis and the in-memory cache.
        """
        window = timedelta(minutes=settings.recommendation_workflow_window_minutes)
        min_count = settings.recommendation_min_cooccurrence

        matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        with fresh_db_session() as db:
            rows = list(db.execute(select(ToolMetric.tool_id, ToolMetric.timestamp).order_by(ToolMetric.timestamp)).all())

        for i, (tool_id_a, ts_a) in enumerate(rows):
            cutoff = ts_a + window
            for tool_id_b, ts_b in rows[i + 1 :]:
                if ts_b > cutoff:
                    break
                if tool_id_a != tool_id_b:
                    matrix[tool_id_a][tool_id_b] += 1
                    matrix[tool_id_b][tool_id_a] += 1

        filtered: Dict[str, Dict[str, int]] = {
            a: {b: cnt for b, cnt in pairs.items() if cnt >= min_count}
            for a, pairs in matrix.items()
            if any(cnt >= min_count for cnt in pairs.values())
        }

        client: Optional[Any] = await get_redis_client()
        if client:
            try:
                await client.set(COOCCURRENCE_CACHE_KEY, json.dumps(filtered), ex=settings.recommendation_pattern_cache_ttl)
            except Exception as exc:
                logger.debug("Failed to write cooccurrence matrix to Redis: %s", exc)

        self._memory_matrix = filtered
        logger.info("WorkflowPatternService matrix rebuilt: %d tool entries", len(filtered))

    async def _get_matrix(self) -> Dict[str, Dict[str, int]]:
        """Return the co-occurrence matrix, loading from Redis if the memory cache is empty.

        Returns:
            Dict mapping tool_id to a dict of {tool_id: co-occurrence count}.
        """
        if self._memory_matrix:
            return self._memory_matrix

        client: Optional[Any] = await get_redis_client()
        if client:
            try:
                raw = await client.get(COOCCURRENCE_CACHE_KEY)
                if raw:
                    self._memory_matrix = json.loads(raw)
                    return self._memory_matrix
            except Exception as exc:
                logger.debug("Could not load cooccurrence matrix from Redis: %s", exc)

        return {}

    async def get_workflow_recommendations(self, recent_tool_ids: List[str], db: Session, limit: int = 10) -> List[WorkflowRecommendation]:
        """Return tools likely to follow the recently used tools.

        Aggregates co-occurrence scores across all recently used tools, normalises
        to [0, 1], resolves names from the database, and returns the top results
        with a human-readable explanation.

        Args:
            recent_tool_ids: IDs of tools the user has recently invoked.
            db: Active SQLAlchemy session for resolving tool names and descriptions.
            limit: Maximum number of recommendations to return.

        Returns:
            List of WorkflowRecommendation sorted by score descending.
            Returns an empty list if no matrix is available or no candidates found.

        Examples:
            >>> svc = WorkflowPatternService()
            >>> import asyncio
            >>> # asyncio.run(svc.get_workflow_recommendations([], db=None)) == []
            True
        """
        if not recent_tool_ids:
            return []

        matrix = await self._get_matrix()
        if not matrix:
            return []

        # Sum co-occurrence counts for tools not already in the recent list
        candidate_scores: Dict[str, int] = defaultdict(int)
        for tool_id in recent_tool_ids:
            for next_tool_id, count in matrix.get(tool_id, {}).items():
                if next_tool_id not in recent_tool_ids:
                    candidate_scores[next_tool_id] += count

        if not candidate_scores:
            return []

        max_score = max(candidate_scores.values())

        # Resolve tool_ids -> (name, description) in one query
        tool_ids = list(candidate_scores.keys())
        tool_rows = db.execute(select(Tool.id, Tool.name, Tool.description).where(Tool.id.in_(tool_ids))).all()
        tool_map: Dict[str, Tuple[str, Optional[str]]] = {row.id: (row.name, row.description) for row in tool_rows}

        # Map each candidate to the recent tool that most strongly predicts it
        trigger_map: Dict[str, str] = {}
        for tool_id in recent_tool_ids:
            trigger_name = db.execute(select(Tool.name).where(Tool.id == tool_id)).scalar_one_or_none() or tool_id
            for next_tool_id in matrix.get(tool_id, {}):
                if next_tool_id not in trigger_map:
                    trigger_map[next_tool_id] = trigger_name

        results: List[WorkflowRecommendation] = []
        for tool_id, raw_score in sorted(candidate_scores.items(), key=lambda x: -x[1])[:limit]:
            if tool_id not in tool_map:
                continue
            name, description = tool_map[tool_id]
            results.append(
                WorkflowRecommendation(
                    tool_name=name,
                    description=description,
                    score=raw_score / max_score,
                    explanation=f"Often used with {trigger_map.get(tool_id, 'recent tools')}",
                )
            )

        return results


_service: Optional[WorkflowPatternService] = None


def get_workflow_pattern_service() -> WorkflowPatternService:
    """Return the singleton WorkflowPatternService instance.

    Returns:
        WorkflowPatternService: The shared service instance.

    Examples:
        >>> svc = get_workflow_pattern_service()
        >>> isinstance(svc, WorkflowPatternService)
        True
    """
    global _service
    if _service is None:
        _service = WorkflowPatternService()
    return _service
