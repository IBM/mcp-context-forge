# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/collaborative_recommender.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Description:
    Collaborative filtering recommendation service that combines user
    similarity and tool popularity to suggest relevant tools based on
    usage patterns of similar users.

    Key features:
    - User-based collaborative filtering
    - Weighted scoring combining popularity and similarity
    - Team-aware recommendations (prioritize team members)
    - Role-based filtering
    - Integration with semantic search boosting

Usage:
    ```python
    from mcpgateway.services.collaborative_recommender import collaborative_recommender
    
    # Get recommendations for a user
    recommendations = await collaborative_recommender.recommend_tools(
        user_email="user@example.com",
        limit=10,
        include_reasoning=True,
        user_team_id="team-123",
        user_role="developer"
    )
    
    # Get boost scores for existing candidate tools (search integration)
    boost_scores = await collaborative_recommender.get_boost_scores(
        user_email="user@example.com",
        candidate_tools=["tool1", "tool2", "tool3"]
    )
    ```
"""

# Standard
import asyncio
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

# Third-Party
from sqlalchemy import func, select

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import ToolUsageEvent, fresh_db_session
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.user_similarity_service import user_similarity_service

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class CollaborativeRecommenderService:
    """Service for generating collaborative filtering recommendations.

    Uses user similarity and usage patterns to recommend tools.
    """

    def __init__(self) -> None:
        """Initialize the collaborative recommender service."""
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize service dependencies."""
        if self._initialized:
            logger.warning("CollaborativeRecommenderService already initialized")
            return

        logger.info("Initializing CollaborativeRecommenderService")

        # Ensure user similarity service is initialized
        if not user_similarity_service._initialized:
            await user_similarity_service.initialize()

        self._initialized = True
        logger.info("CollaborativeRecommenderService initialized successfully")

    async def shutdown(self) -> None:
        """Shutdown service."""
        if not self._initialized:
            return

        logger.info("Shutting down CollaborativeRecommenderService")
        self._initialized = False
        logger.info("CollaborativeRecommenderService shutdown complete")

    async def recommend_tools(
        self,
        user_email: str,
        limit: int = 10,
        include_reasoning: bool = False,
        user_team_id: Optional[str] = None,
        user_role: Optional[str] = None,
        exclude_tools: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Generate collaborative filtering recommendations for a user.

        Args:
            user_email: Target user email
            limit: Maximum number of recommendations
            include_reasoning: Include explanation of why tools were recommended
            user_team_id: User's team ID (for team-aware recommendations)
            user_role: User's role (for role-based filtering)
            exclude_tools: Tool IDs to exclude from recommendations

        Returns:
            List of recommendation dicts with tool_id, score (0-1), and optional reasoning
        """
        if not settings.collaborative_filtering_enabled:
            return []

        if exclude_tools is None:
            exclude_tools = set()

        # Get user's existing tool usage (to exclude)
        user_tools = await user_similarity_service._get_user_tool_usage(user_email)
        exclude_tools.update(user_tools.keys())

        # Get similar users
        similar_users = await user_similarity_service.get_similar_users(
            user_email=user_email,
            limit=50,  # Consider top 50 similar users
            algorithm=settings.cf_similarity_algorithm,
        )

        # Fallback: not enough similar users → use org-wide popular tools
        if len(similar_users) < settings.cf_min_similar_users:
            logger.debug(
                f"Only {len(similar_users)} similar users found for {user_email} "
                f"(threshold {settings.cf_min_similar_users}); falling back to popular tools"
            )
            return await self._popular_tool_fallback(user_email, exclude_tools, limit, user_role)

        # Aggregate tool usage from similar users (weighted by similarity)
        tool_scores: Dict[str, float] = {}
        tool_sources: Dict[str, List[Tuple[str, float]]] = {}  # For reasoning

        for similar_email, similarity_score in similar_users:
            similar_tools = await user_similarity_service._get_user_tool_usage(similar_email)

            for tool_id, usage_count in similar_tools.items():
                if tool_id in exclude_tools:
                    continue

                # Weighted score: usage_count * similarity_score
                weighted_score = usage_count * similarity_score
                tool_scores[tool_id] = tool_scores.get(tool_id, 0.0) + weighted_score

                # Track sources for reasoning
                if include_reasoning:
                    if tool_id not in tool_sources:
                        tool_sources[tool_id] = []
                    tool_sources[tool_id].append((similar_email, similarity_score))

        if not tool_scores:
            logger.debug(f"No new tools to recommend for {user_email}")
            return []

        # Normalise scores to [0, 1] using max-score normalisation
        max_score = max(tool_scores.values())
        if max_score > 0:
            tool_scores = {k: v / max_score for k, v in tool_scores.items()}

        # Apply minimum relevance threshold (spec: > 0.6)
        tool_scores = {k: v for k, v in tool_scores.items() if v >= settings.cf_min_relevance_score}

        if not tool_scores:
            logger.debug(f"No tools met the relevance threshold ({settings.cf_min_relevance_score}) for {user_email}")
            return []

        # Sort by score descending and limit
        sorted_tools = sorted(tool_scores.items(), key=lambda x: x[1], reverse=True)[:limit]

        # Build recommendations
        recommendations = []
        for tool_id, score in sorted_tools:
            rec: Dict[str, Any] = {
                "tool_id": tool_id,
                "score": round(score, 4),
            }

            if include_reasoning:
                # Get top 3 similar users who used this tool
                sources = tool_sources.get(tool_id, [])
                sources.sort(key=lambda x: x[1], reverse=True)
                user_count = len(sources)
                rec["reasoning"] = {
                    "similar_users_count": user_count,
                    "top_similar_users": [{"email": email, "similarity": sim} for email, sim in sources[:3]],
                    "explanation": f"Used by {user_count} similar user{'s' if user_count != 1 else ''}.",
                }

            recommendations.append(rec)

        logger.debug(f"Generated {len(recommendations)} collaborative recommendations for {user_email}")
        return recommendations

    async def _popular_tool_fallback(
        self,
        user_email: str,
        exclude_tools: Set[str],
        limit: int,
        user_role: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Return org-wide popular tools the user has not yet used.

        Used when the user has fewer than cf_min_similar_users peers to
        generate collaborative recommendations from.

        Args:
            user_email: Target user email (used only for logging)
            exclude_tools: Tool IDs the user has already used
            limit: Maximum recommendations to return
            user_role: User role for role-specific popularity (None = global)

        Returns:
            Normalised recommendation list with fallback reasoning
        """
        # Prefer role-specific popularity; fall back to global trending
        if user_role:
            candidates = await self.get_popular_tools_for_role(user_role, limit=limit * 3, time_window_days=30)
        else:
            candidates = await self.get_trending_tools(limit=limit * 3, time_window_days=30)

        results: List[Dict[str, Any]] = []
        raw_scores: List[float] = []

        for tool in candidates:
            if tool["tool_id"] in exclude_tools:
                continue
            results.append(
                {
                    "tool_id": tool["tool_id"],
                    "score": float(tool.get("usage_count", tool.get("trend_score", 1))),
                    "reasoning": {
                        "similar_users_count": 0,
                        "top_similar_users": [],
                        "explanation": f"Popular in your organisation ({tool.get('usage_count', 0)} recent uses).",
                        "fallback_reason": "insufficient_similar_users",
                    },
                }
            )
            raw_scores.append(results[-1]["score"])
            if len(results) >= limit:
                break

        # Normalise scores to [0, 1]
        if raw_scores:
            max_score = max(raw_scores)
            if max_score > 0:
                for rec in results:
                    rec["score"] = round(rec["score"] / max_score, 4)

        logger.debug(f"Fallback: returning {len(results)} popular tools for {user_email} (role={user_role})")
        return results

    async def get_boost_scores(
        self,
        user_email: str,
        candidate_tools: List[str],
    ) -> Dict[str, float]:
        """Get collaborative filtering boost scores for candidate tools.

        Used to augment semantic search results with collaborative signals.

        Args:
            user_email: Target user email
            candidate_tools: List of candidate tool IDs from semantic search

        Returns:
            Dict mapping tool_id to boost score (0.0 to 1.0)
        """
        if not settings.collaborative_filtering_enabled or settings.cf_boost_weight == 0.0:
            return {}

        # Get similar users
        similar_users = await user_similarity_service.get_similar_users(
            user_email=user_email,
            limit=20,  # Top 20 similar users for boosting
            algorithm=settings.cf_similarity_algorithm,
        )

        if not similar_users:
            return {}

        # Compute boost scores for candidates
        boost_scores: Dict[str, float] = {}

        for tool_id in candidate_tools:
            # Count how many similar users have used this tool (weighted by similarity)
            weighted_usage = 0.0

            for similar_email, similarity_score in similar_users:
                similar_tools = await user_similarity_service._get_user_tool_usage(similar_email)
                if tool_id in similar_tools:
                    # Weight by both similarity and usage frequency
                    weighted_usage += similarity_score * similar_tools[tool_id]

            # Normalize to 0-1 range (divide by max possible score)
            max_possible_score = sum(sim for _, sim in similar_users)
            if max_possible_score > 0:
                boost_scores[tool_id] = min(1.0, weighted_usage / max_possible_score)
            else:
                boost_scores[tool_id] = 0.0

        return boost_scores

    async def get_trending_tools(
        self,
        limit: int = 10,
        time_window_days: int = 7,
        user_team_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get trending tools based on recent usage spikes.

        Args:
            limit: Maximum number of tools to return
            time_window_days: Time window for trend analysis
            user_team_id: Filter by team (None = global)

        Returns:
            List of trending tool dicts with tool_id, usage_count, trend_score
        """
        try:
            from datetime import timedelta

            from mcpgateway.db import utc_now

            cutoff_date = utc_now() - timedelta(days=time_window_days)

            with fresh_db_session() as session:
                # Get tool usage counts in time window
                stmt = (
                    select(ToolUsageEvent.tool_id, func.count(ToolUsageEvent.id).label("usage_count"))
                    .where(ToolUsageEvent.timestamp >= cutoff_date, ToolUsageEvent.success == True)
                    .group_by(ToolUsageEvent.tool_id)
                    .order_by(func.count(ToolUsageEvent.id).desc())
                    .limit(limit)
                )

                # Filter by team if specified
                if user_team_id:
                    stmt = stmt.where(ToolUsageEvent.user_team_id == user_team_id)

                result = session.execute(stmt)
                rows = result.all()

                trending = [
                    {
                        "tool_id": row.tool_id,
                        "usage_count": row.usage_count,
                        "trend_score": float(row.usage_count),  # Simplified: just use raw count
                    }
                    for row in rows
                ]

                logger.debug(f"Found {len(trending)} trending tools in last {time_window_days} days")
                return trending
        except Exception as e:
            logger.error(f"Failed to get trending tools: {e}", exc_info=True)
            return []

    async def get_popular_tools_for_role(
        self,
        user_role: str,
        limit: int = 10,
        time_window_days: int = 30,
    ) -> List[Dict[str, Any]]:
        """Get popular tools for a specific role.

        Args:
            user_role: Role to filter by
            limit: Maximum number of tools to return
            time_window_days: Time window for popularity calculation

        Returns:
            List of popular tool dicts with tool_id, usage_count
        """
        try:
            from datetime import timedelta

            from mcpgateway.db import utc_now

            cutoff_date = utc_now() - timedelta(days=time_window_days)

            with fresh_db_session() as session:
                stmt = (
                    select(ToolUsageEvent.tool_id, func.count(ToolUsageEvent.id).label("usage_count"))
                    .where(
                        ToolUsageEvent.timestamp >= cutoff_date,
                        ToolUsageEvent.success == True,
                        ToolUsageEvent.user_role == user_role,
                    )
                    .group_by(ToolUsageEvent.tool_id)
                    .order_by(func.count(ToolUsageEvent.id).desc())
                    .limit(limit)
                )

                result = session.execute(stmt)
                rows = result.all()

                popular = [
                    {
                        "tool_id": row.tool_id,
                        "usage_count": row.usage_count,
                    }
                    for row in rows
                ]

                logger.debug(f"Found {len(popular)} popular tools for role {user_role}")
                return popular
        except Exception as e:
            logger.error(f"Failed to get popular tools for role {user_role}: {e}", exc_info=True)
            return []

    async def get_recommendation_stats(self, user_email: str) -> Dict[str, Any]:
        """Get recommendation system stats for a user.

        Args:
            user_email: User email

        Returns:
            Dict with stats about recommendations (similar users count, etc.)
        """
        try:
            # Get user's tool usage
            user_tools = await user_similarity_service._get_user_tool_usage(user_email)

            # Get similar users
            similar_users = await user_similarity_service.get_similar_users(
                user_email=user_email,
                limit=10,
                algorithm=settings.cf_similarity_algorithm,
            )

            # Get recent recommendations
            recommendations = await self.recommend_tools(
                user_email=user_email,
                limit=10,
                include_reasoning=False,
            )

            return {
                "user_email": user_email,
                "user_tool_count": len(user_tools),
                "similar_users_count": len(similar_users),
                "available_recommendations": len(recommendations),
                "cf_enabled": settings.collaborative_filtering_enabled,
                "cf_boost_weight": settings.cf_boost_weight,
                "similarity_algorithm": settings.cf_similarity_algorithm,
            }
        except Exception as e:
            logger.error(f"Failed to get recommendation stats for {user_email}: {e}", exc_info=True)
            return {
                "user_email": user_email,
                "error": str(e),
            }


# Module-level singleton
collaborative_recommender = CollaborativeRecommenderService()
