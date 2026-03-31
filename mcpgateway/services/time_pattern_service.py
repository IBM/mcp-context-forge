"""Time-based usage pattern service for the context-aware recommender.

Analyses a user's historical tool invocations to detect hour-of-day and
day-of-week patterns, returning tools the user frequently uses at the current
time. Requires a minimum of 30 days of history before making predictions.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from mcpgateway.config import settings
from mcpgateway.db import Tool, ToolMetric
from mcpgateway.schemas import TimeRecommendation

logger = logging.getLogger(__name__)

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class TimePatternService:
    """Recommends tools based on a user's time-of-day and day-of-week usage patterns.

    Queries ToolMetric records for the given user over the last 90 days, filters
    to rows matching the current weekday within a ±2-hour window, and scores tools
    by normalised frequency. Returns an empty list if fewer than
    settings.recommendation_min_history_days of history exist.

    Examples:
        >>> svc = TimePatternService()
        >>> isinstance(svc, TimePatternService)
        True
    """

    async def get_time_recommendations(self, user_id: str, db: Session, limit: int = 10) -> List[TimeRecommendation]:
        """Return tools the user frequently uses at the current time of day and day of week.

        Args:
            user_id: The user whose ToolMetric history to query.
            db: Active SQLAlchemy session.
            limit: Maximum number of recommendations to return.

        Returns:
            List of TimeRecommendation sorted by score descending.
            Returns an empty list if insufficient history exists or no matching rows found.

        Examples:
            >>> svc = TimePatternService()
            >>> import asyncio
            >>> # asyncio.run(svc.get_time_recommendations("new_user", db=None)) == []
            True
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=90)

        rows = db.execute(
            select(ToolMetric.tool_id, ToolMetric.timestamp).where(
                and_(
                    ToolMetric.user_id == user_id,
                    ToolMetric.timestamp >= cutoff,
                )
            )
        ).all()

        if not rows:
            return []

        # Require minimum history span before making predictions
        timestamps = [r.timestamp.replace(tzinfo=timezone.utc) if r.timestamp.tzinfo is None else r.timestamp for r in rows]
        history_days = (now - min(timestamps)).days
        if history_days < settings.recommendation_min_history_days:
            return []

        current_weekday = now.weekday()
        current_hour = now.hour

        # Score tools used on the same weekday within ±2 hours of the current hour
        candidate_scores: Dict[str, int] = defaultdict(int)
        for row in rows:
            ts = row.timestamp.replace(tzinfo=timezone.utc) if row.timestamp.tzinfo is None else row.timestamp
            if ts.weekday() != current_weekday:
                continue
            if abs(ts.hour - current_hour) > 2:
                continue
            candidate_scores[row.tool_id] += 1

        if not candidate_scores:
            return []

        max_score = max(candidate_scores.values())

        # Resolve tool_ids -> (name, description) in one query
        tool_ids = list(candidate_scores.keys())
        tool_rows = db.execute(select(Tool.id, Tool.name, Tool.description).where(Tool.id.in_(tool_ids))).all()
        tool_map = {row.id: (row.name, row.description) for row in tool_rows}

        day_name = DAY_NAMES[current_weekday]
        if current_hour < 12:
            period = "mornings"
        elif current_hour < 18:
            period = "afternoons"
        else:
            period = "evenings"

        results: List[TimeRecommendation] = []
        for tool_id, count in sorted(candidate_scores.items(), key=lambda x: -x[1])[:limit]:
            if tool_id not in tool_map:
                continue
            name, description = tool_map[tool_id]
            results.append(
                TimeRecommendation(
                    tool_name=name,
                    description=description,
                    score=count / max_score,
                    explanation=f"Frequently used on {day_name} {period}",
                )
            )

        return results


_service: Optional[TimePatternService] = None


def get_time_pattern_service() -> TimePatternService:
    """Return the singleton TimePatternService instance.

    Returns:
        TimePatternService: The shared service instance.

    Examples:
        >>> svc = get_time_pattern_service()
        >>> isinstance(svc, TimePatternService)
        True
    """
    global _service
    if _service is None:
        _service = TimePatternService()
    return _service
