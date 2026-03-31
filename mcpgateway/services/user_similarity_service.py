# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/user_similarity_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Description:
    User similarity computation service for collaborative filtering.
    Calculates similarity between users based on tool usage patterns
    using various algorithms (cosine, Jaccard, Dice, overlap).

    Key features:
    - Multiple similarity algorithms (cosine, Jaccard, Dice, overlap coefficient)
    - Redis caching for precomputed similarities
    - Team-aware similarity (prioritize users in same team)
    - Configurable minimum interaction thresholds
    - Background precomputation for active users

Usage:
    ```python
    from mcpgateway.services.user_similarity_service import user_similarity_service
    
    # Compute similarity between two users
    similarity = await user_similarity_service.compute_similarity(
        user1_email="user1@example.com",
        user2_email="user2@example.com",
        algorithm="cosine"
    )
    
    # Get most similar users
    similar_users = await user_similarity_service.get_similar_users(
        user_email="user@example.com",
        limit=10,
        min_common_tools=2
    )
    ```
"""

# Standard
import asyncio
import math
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, List, Literal, Optional, Set, Tuple

# Third-Party
import orjson
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import ToolUsageEvent, fresh_db_session, utc_now
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.redis_client import get_redis_client

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

SimilarityAlgorithm = Literal["cosine", "jaccard", "dice", "overlap"]


class UserSimilarityService:
    """Service for computing user-to-user similarity based on tool usage.

    Supports multiple algorithms and Redis caching for performance.
    """

    def __init__(self) -> None:
        """Initialize the user similarity service."""
        self._initialized = False
        self._redis_client = None
        self._similarity_cache_prefix = "user_similarity:"
        self._tool_usage_cache_prefix = "user_tools:"
        self._precompute_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Initialize service and start background precomputation if enabled."""
        if self._initialized:
            logger.warning("UserSimilarityService already initialized")
            return

        logger.info("Initializing UserSimilarityService")

        # Initialize Redis client
        try:
            self._redis_client = get_redis_client()
            if self._redis_client:
                await self._redis_client.ping()
                logger.info("Redis connection established for similarity caching")
        except Exception as e:
            logger.warning(f"Redis unavailable for similarity caching: {e}")
            self._redis_client = None

        # Start background precomputation if enabled
        if settings.similarity_precompute_enabled:
            self._precompute_task = asyncio.create_task(self._precompute_loop())
            logger.info(f"Similarity precomputation task started (interval: {settings.similarity_precompute_interval_hours}h)")

        self._initialized = True
        logger.info("UserSimilarityService initialized successfully")

    async def shutdown(self) -> None:
        """Shutdown service and cancel background tasks."""
        if not self._initialized:
            return

        logger.info("Shutting down UserSimilarityService")

        # Cancel precomputation task
        if self._precompute_task and not self._precompute_task.done():
            self._precompute_task.cancel()
            try:
                await self._precompute_task
            except asyncio.CancelledError:
                pass

        self._initialized = False
        logger.info("UserSimilarityService shutdown complete")

    async def compute_similarity(
        self,
        user1_email: str,
        user2_email: str,
        algorithm: SimilarityAlgorithm = "cosine",
        use_cache: bool = True,
    ) -> float:
        """Compute similarity between two users based on tool usage.

        Args:
            user1_email: First user email
            user2_email: Second user email
            algorithm: Similarity algorithm to use
            use_cache: Whether to use Redis cache

        Returns:
            Similarity score (0.0 to 1.0)
        """
        if user1_email == user2_email:
            return 1.0

        # Try cache first
        if use_cache and settings.similarity_cache_enabled and self._redis_client:
            cached = await self._get_cached_similarity(user1_email, user2_email, algorithm)
            if cached is not None:
                return cached

        # Get tool usage for both users
        user1_tools = await self._get_user_tool_usage(user1_email)
        user2_tools = await self._get_user_tool_usage(user2_email)

        # Check minimum interaction threshold
        if len(user1_tools) < settings.cf_min_user_interactions or len(user2_tools) < settings.cf_min_user_interactions:
            return 0.0

        # Compute similarity using selected algorithm
        if algorithm == "cosine":
            similarity = self._cosine_similarity(user1_tools, user2_tools)
        elif algorithm == "jaccard":
            similarity = self._jaccard_similarity(user1_tools, user2_tools)
        elif algorithm == "dice":
            similarity = self._dice_similarity(user1_tools, user2_tools)
        elif algorithm == "overlap":
            similarity = self._overlap_coefficient(user1_tools, user2_tools)
        else:
            logger.warning(f"Unknown similarity algorithm: {algorithm}, defaulting to cosine")
            similarity = self._cosine_similarity(user1_tools, user2_tools)

        # Team-aware boost: users in the same team are likely to share relevant tools
        if settings.cf_team_similarity_boost > 0.0:
            team1 = await self._get_user_primary_team(user1_email)
            team2 = await self._get_user_primary_team(user2_email)
            if team1 and team2 and team1 == team2:
                similarity = min(1.0, similarity + settings.cf_team_similarity_boost)
                logger.debug(f"Applied team similarity boost for {user1_email} and {user2_email} (team={team1})")

        # Cache result
        if use_cache and settings.similarity_cache_enabled and self._redis_client:
            await self._cache_similarity(user1_email, user2_email, algorithm, similarity)

        return similarity

    async def get_similar_users(
        self,
        user_email: str,
        limit: int = 10,
        min_common_tools: Optional[int] = None,
        algorithm: SimilarityAlgorithm = "cosine",
    ) -> List[Tuple[str, float]]:
        """Get most similar users to the target user.

        Args:
            user_email: Target user email
            limit: Maximum number of similar users to return
            min_common_tools: Minimum common tools required (None = use config default)
            algorithm: Similarity algorithm to use

        Returns:
            List of (user_email, similarity_score) tuples, sorted by similarity descending
        """
        if min_common_tools is None:
            min_common_tools = settings.cf_min_common_tools

        # Get target user's tool usage
        target_tools = await self._get_user_tool_usage(user_email)
        if len(target_tools) < settings.cf_min_user_interactions:
            logger.debug(f"User {user_email} has insufficient interactions ({len(target_tools)} < {settings.cf_min_user_interactions})")
            return []

        # Get all candidate users with sufficient interactions
        candidate_users = await self._get_candidate_users(user_email, target_tools, min_common_tools)

        # Compute similarities
        similarities: List[Tuple[str, float]] = []
        for candidate_email in candidate_users:
            sim = await self.compute_similarity(user_email, candidate_email, algorithm)
            if sim > 0.0:
                similarities.append((candidate_email, sim))

        # Sort by similarity descending and limit
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:limit]

    async def _get_user_tool_usage(self, user_email: str) -> Counter:
        """Get weighted tool usage for a user (frequency-based).

        Args:
            user_email: User email

        Returns:
            Counter mapping tool_id to usage count
        """
        # Try cache first
        if settings.similarity_cache_enabled and self._redis_client:
            try:
                cache_key = f"{self._tool_usage_cache_prefix}{user_email}"
                cached = await self._redis_client.get(cache_key)
                if cached:
                    data = orjson.loads(cached)
                    return Counter(data)
            except Exception as e:
                logger.warning(f"Failed to read tool usage cache for {user_email}: {e}")

        # Query database
        try:
            with fresh_db_session() as session:
                # Get tool usage counts (successful executions only)
                stmt = (
                    select(ToolUsageEvent.tool_id, func.count(ToolUsageEvent.id).label("count"))
                    .where(ToolUsageEvent.user_email == user_email, ToolUsageEvent.success == True)
                    .group_by(ToolUsageEvent.tool_id)
                )
                result = session.execute(stmt)
                rows = result.all()

                tool_counts = Counter({row.tool_id: row.count for row in rows})

                # Cache result
                if settings.similarity_cache_enabled and self._redis_client:
                    try:
                        cache_key = f"{self._tool_usage_cache_prefix}{user_email}"
                        await self._redis_client.setex(cache_key, settings.similarity_cache_ttl, orjson.dumps(dict(tool_counts)))
                    except Exception as e:
                        logger.warning(f"Failed to cache tool usage for {user_email}: {e}")

                return tool_counts
        except Exception as e:
            logger.error(f"Failed to get tool usage for {user_email}: {e}", exc_info=True)
            return Counter()

    async def _get_candidate_users(self, target_email: str, target_tools: Counter, min_common_tools: int) -> List[str]:
        """Get candidate users who have used at least min_common_tools in common.

        Args:
            target_email: Target user email to exclude
            target_tools: Target user's tool usage
            min_common_tools: Minimum common tools required

        Returns:
            List of candidate user emails
        """
        try:
            with fresh_db_session() as session:
                # Get users who have used target tools
                tool_ids = list(target_tools.keys())
                stmt = (
                    select(ToolUsageEvent.user_email, func.count(func.distinct(ToolUsageEvent.tool_id)).label("common_count"))
                    .where(ToolUsageEvent.user_email != target_email, ToolUsageEvent.tool_id.in_(tool_ids), ToolUsageEvent.success == True)
                    .group_by(ToolUsageEvent.user_email)
                    .having(func.count(func.distinct(ToolUsageEvent.tool_id)) >= min_common_tools)
                )
                result = session.execute(stmt)
                rows = result.all()

                return [row.user_email for row in rows]
        except Exception as e:
            logger.error(f"Failed to get candidate users: {e}", exc_info=True)
            return []

    def _cosine_similarity(self, tools1: Counter, tools2: Counter) -> float:
        """Compute cosine similarity between two tool usage vectors.

        Args:
            tools1: First user's tool usage counts
            tools2: Second user's tool usage counts

        Returns:
            Cosine similarity (0.0 to 1.0)
        """
        # Get common tools
        common_tools = set(tools1.keys()) & set(tools2.keys())
        if not common_tools:
            return 0.0

        # Compute dot product
        dot_product = sum(tools1[tool] * tools2[tool] for tool in common_tools)

        # Compute magnitudes
        magnitude1 = math.sqrt(sum(count**2 for count in tools1.values()))
        magnitude2 = math.sqrt(sum(count**2 for count in tools2.values()))

        if magnitude1 == 0.0 or magnitude2 == 0.0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)

    def _jaccard_similarity(self, tools1: Counter, tools2: Counter) -> float:
        """Compute Jaccard similarity (intersection over union).

        Args:
            tools1: First user's tool usage counts
            tools2: Second user's tool usage counts

        Returns:
            Jaccard similarity (0.0 to 1.0)
        """
        set1 = set(tools1.keys())
        set2 = set(tools2.keys())

        if not set1 and not set2:
            return 0.0

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        return intersection / union if union > 0 else 0.0

    def _dice_similarity(self, tools1: Counter, tools2: Counter) -> float:
        """Compute Dice coefficient (2 * intersection / sum of sizes).

        Args:
            tools1: First user's tool usage counts
            tools2: Second user's tool usage counts

        Returns:
            Dice coefficient (0.0 to 1.0)
        """
        set1 = set(tools1.keys())
        set2 = set(tools2.keys())

        if not set1 and not set2:
            return 0.0

        intersection = len(set1 & set2)
        total_size = len(set1) + len(set2)

        return (2 * intersection) / total_size if total_size > 0 else 0.0

    def _overlap_coefficient(self, tools1: Counter, tools2: Counter) -> float:
        """Compute overlap coefficient (intersection / min size).

        Args:
            tools1: First user's tool usage counts
            tools2: Second user's tool usage counts

        Returns:
            Overlap coefficient (0.0 to 1.0)
        """
        set1 = set(tools1.keys())
        set2 = set(tools2.keys())

        if not set1 or not set2:
            return 0.0

        intersection = len(set1 & set2)
        min_size = min(len(set1), len(set2))

        return intersection / min_size if min_size > 0 else 0.0

    async def _get_user_primary_team(self, user_email: str) -> Optional[str]:
        """Return the team ID most frequently associated with a user's events.

        Args:
            user_email: User email to look up

        Returns:
            Team ID string, or None if the user has no team-tagged events
        """
        try:
            with fresh_db_session() as session:
                stmt = (
                    select(ToolUsageEvent.user_team_id, func.count(ToolUsageEvent.id).label("cnt"))
                    .where(ToolUsageEvent.user_email == user_email, ToolUsageEvent.user_team_id.isnot(None))
                    .group_by(ToolUsageEvent.user_team_id)
                    .order_by(func.count(ToolUsageEvent.id).desc())
                    .limit(1)
                )
                result = session.execute(stmt)
                row = result.first()
                return row.user_team_id if row else None
        except Exception as e:
            logger.warning(f"Failed to get primary team for {user_email}: {e}")
            return None

    async def _get_cached_similarity(self, user1_email: str, user2_email: str, algorithm: str) -> Optional[float]:
        """Get cached similarity from Redis.

        Args:
            user1_email: First user email
            user2_email: Second user email
            algorithm: Similarity algorithm

        Returns:
            Cached similarity score or None
        """
        try:
            # Normalize key order (so user1-user2 and user2-user1 share cache)
            key = self._make_similarity_key(user1_email, user2_email, algorithm)
            cached = await self._redis_client.get(key)
            if cached:
                return float(cached)
        except Exception as e:
            logger.warning(f"Failed to read cached similarity: {e}")
        return None

    async def _cache_similarity(self, user1_email: str, user2_email: str, algorithm: str, similarity: float) -> None:
        """Cache similarity to Redis.

        Args:
            user1_email: First user email
            user2_email: Second user email
            algorithm: Similarity algorithm
            similarity: Similarity score to cache
        """
        try:
            key = self._make_similarity_key(user1_email, user2_email, algorithm)
            await self._redis_client.setex(key, settings.similarity_cache_ttl, str(similarity))
        except Exception as e:
            logger.warning(f"Failed to cache similarity: {e}")

    def _make_similarity_key(self, user1_email: str, user2_email: str, algorithm: str) -> str:
        """Create normalized cache key for similarity.

        Args:
            user1_email: First user email
            user2_email: Second user email
            algorithm: Similarity algorithm

        Returns:
            Normalized cache key
        """
        # Sort emails to ensure consistency
        emails = sorted([user1_email, user2_email])
        return f"{self._similarity_cache_prefix}{algorithm}:{emails[0]}:{emails[1]}"

    async def _precompute_loop(self) -> None:
        """Background loop for precomputing similarities between active users."""
        while True:
            try:
                await asyncio.sleep(settings.similarity_precompute_interval_hours * 3600)
                await self._precompute_similarities()
            except asyncio.CancelledError:
                logger.info("Similarity precomputation task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in similarity precomputation loop: {e}", exc_info=True)

    async def _precompute_similarities(self) -> None:
        """Precompute similarities for active users (top N by recent activity)."""
        try:
            # Get active users (users with usage in last 30 days)
            cutoff_date = utc_now() - timedelta(days=30)

            with fresh_db_session() as session:
                stmt = (
                    select(ToolUsageEvent.user_email, func.count(ToolUsageEvent.id).label("count"))
                    .where(ToolUsageEvent.timestamp >= cutoff_date, ToolUsageEvent.success == True)
                    .group_by(ToolUsageEvent.user_email)
                    .order_by(func.count(ToolUsageEvent.id).desc())
                    .limit(100)  # Top 100 active users
                )
                result = session.execute(stmt)
                active_users = [row.user_email for row in result.all()]

            logger.info(f"Precomputing similarities for {len(active_users)} active users")

            # Compute pairwise similarities (O(n^2), limited to top 100 users)
            algorithm = settings.cf_similarity_algorithm
            computed = 0
            for i, user1 in enumerate(active_users):
                for user2 in active_users[i + 1 :]:
                    await self.compute_similarity(user1, user2, algorithm, use_cache=True)
                    computed += 1

            logger.info(f"Precomputed {computed} user similarities")
        except Exception as e:
            logger.error(f"Failed to precompute similarities: {e}", exc_info=True)


# Module-level singleton
user_similarity_service = UserSimilarityService()
