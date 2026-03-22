"""Context-aware tool recommender service.

Aggregates three signals — conversation context (10%), workflow co-occurrence (20%),
and time-based usage patterns (5%) — into a unified ranked list of tool recommendations.
Each signal is fetched concurrently and individual failures degrade gracefully without
affecting the remaining signals.
"""

import asyncio
import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from mcpgateway.config import settings
from mcpgateway.db import Tool
from mcpgateway.schemas import RecommendationResponse, ToolRecommendation

logger = logging.getLogger(__name__)


class ContextAwareRecommenderService:
    """Unified tool recommender combining conversation, workflow, and time signals.

    All three sub-services are called concurrently via asyncio.gather. If any signal
    fails, the remaining signals are still used. Tools already in recent_tool_names
    are filtered from the results. Scores are aggregated as the maximum weighted
    contribution across all signals to avoid double-counting.

    Examples:
        >>> svc = ContextAwareRecommenderService()
        >>> isinstance(svc, ContextAwareRecommenderService)
        True
    """

    async def recommend(self, user_id: str, recent_tool_names: List[str], db: Session, limit: int = 10) -> RecommendationResponse:
        """Generate ranked tool recommendations for a user.

        Fetches all three signals concurrently, aggregates scores, filters out
        recently used tools, and returns a ranked RecommendationResponse.

        Args:
            user_id: The user to generate recommendations for.
            recent_tool_names: Tool names the user has recently used (excluded from results).
            db: Active SQLAlchemy session.
            limit: Maximum number of recommendations to return.

        Returns:
            RecommendationResponse with ranked ToolRecommendation list.

        Examples:
            >>> import asyncio
            >>> svc = ContextAwareRecommenderService()
            >>> # asyncio.run(svc.recommend("user", [], db=None, limit=10))
            True
        """
        from mcpgateway.services.conversation_context_service import get_conversation_context_service  # pylint: disable=import-outside-toplevel
        from mcpgateway.services.time_pattern_service import get_time_pattern_service  # pylint: disable=import-outside-toplevel
        from mcpgateway.services.workflow_pattern_service import get_workflow_pattern_service  # pylint: disable=import-outside-toplevel

        # Resolve recent tool names -> IDs for workflow service
        recent_tool_ids: List[str] = []
        try:
            id_rows = db.execute(select(Tool.id, Tool.name).where(Tool.name.in_(recent_tool_names))).all()
            recent_tool_ids = [row.id for row in id_rows]
        except Exception as exc:
            logger.warning("Could not resolve recent tool IDs: %s", exc)

        # --- Fetch all signals concurrently ---
        conv_results = []
        workflow_results = []
        time_results = []

        async def _get_conv() -> None:
            nonlocal conv_results
            try:
                conv_results = await get_conversation_context_service().extract_context(user_id, db, limit=limit)
            except Exception as exc:
                logger.warning("Conversation signal failed: %s", exc)

        async def _get_workflow() -> None:
            nonlocal workflow_results
            try:
                workflow_results = await get_workflow_pattern_service().get_workflow_recommendations(recent_tool_ids, db, limit)
            except Exception as exc:
                logger.warning("Workflow signal failed: %s", exc)

        async def _get_time() -> None:
            nonlocal time_results
            try:
                time_results = await get_time_pattern_service().get_time_recommendations(user_id, db, limit)
            except Exception as exc:
                logger.warning("Time signal failed: %s", exc)

        await asyncio.gather(_get_conv(), _get_workflow(), _get_time())

        # --- Score aggregation ---
        w_conv = settings.recommendation_conversation_weight
        w_work = settings.recommendation_workflow_weight
        w_time = settings.recommendation_time_weight

        # Per tool: track max weighted contribution per signal and collect reasons
        tool_scores: Dict[str, Dict] = defaultdict(lambda: {
            "score": 0.0,
            "reasons": [],
            "signals": {"conversation": 0.0, "workflow": 0.0, "time": 0.0},
            "description": None,
        })

        for rec in conv_results:
            entry = tool_scores[rec.tool_name]
            contrib = rec.similarity_score * w_conv
            if contrib > entry["signals"]["conversation"]:
                entry["signals"]["conversation"] = contrib
                entry["score"] = max(entry["score"], contrib)
                entry["description"] = entry["description"] or rec.description

        for rec in workflow_results:
            entry = tool_scores[rec.tool_name]
            contrib = rec.score * w_work
            if contrib > entry["signals"]["workflow"]:
                entry["signals"]["workflow"] = contrib
                entry["score"] = max(entry["score"], contrib)
                entry["description"] = entry["description"] or rec.description
                if rec.explanation not in entry["reasons"]:
                    entry["reasons"].append(rec.explanation)

        for rec in time_results:
            entry = tool_scores[rec.tool_name]
            contrib = rec.score * w_time
            if contrib > entry["signals"]["time"]:
                entry["signals"]["time"] = contrib
                entry["score"] = max(entry["score"], contrib)
                entry["description"] = entry["description"] or rec.description
                if rec.explanation not in entry["reasons"]:
                    entry["reasons"].append(rec.explanation)

        # Filter out tools the user has already used recently
        recent_set = set(recent_tool_names)
        filtered: List[Tuple[str, Dict]] = [(name, data) for name, data in tool_scores.items() if name not in recent_set]

        ranked = sorted(filtered, key=lambda x: -x[1]["score"])[:limit]

        recommendations = [
            ToolRecommendation(
                tool_name=name,
                description=data["description"],
                score=round(data["score"], 4),
                reasons=data["reasons"],
                signals=data["signals"],
            )
            for name, data in ranked
        ]

        return RecommendationResponse(
            recommendations=recommendations,
            user_id=user_id,
            total_results=len(recommendations),
        )


_service: Optional[ContextAwareRecommenderService] = None


def get_context_aware_recommender_service() -> ContextAwareRecommenderService:
    """Return the singleton ContextAwareRecommenderService instance.

    Returns:
        ContextAwareRecommenderService: The shared service instance.

    Examples:
        >>> svc = get_context_aware_recommender_service()
        >>> isinstance(svc, ContextAwareRecommenderService)
        True
    """
    global _service
    if _service is None:
        _service = ContextAwareRecommenderService()
    return _service
