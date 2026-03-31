# -*- coding: utf-8 -*-
"""User Feedback Collection and Personalized Preference Model.

Captures user interactions (CLICKED, USED, DISMISSED, HIDDEN) with
recommended tools, learns from 90-day interaction history, and builds
a personalized preference model with exponential decay.

Feedback processing completes in under 20ms.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

# Third-Party
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Interaction types
# ---------------------------------------------------------------------------


class InteractionType(str, Enum):
    """Types of user interactions with recommended tools."""

    CLICKED = "CLICKED"
    USED = "USED"
    DISMISSED = "DISMISSED"
    HIDDEN = "HIDDEN"


# Affinity deltas per interaction type
AFFINITY_DELTAS: Dict[str, float] = {
    InteractionType.USED: 0.3,
    InteractionType.CLICKED: 0.1,
    InteractionType.DISMISSED: -0.2,
    InteractionType.HIDDEN: -1.0,
}

# Exponential decay parameters
DECAY_HALF_LIFE_DAYS = 90
DECAY_LAMBDA = math.log(2) / DECAY_HALF_LIFE_DAYS

# Preference model parameters
MIN_INTERACTIONS_FOR_PERSONALIZATION = 10
PREFERENCE_CACHE_TTL_SECONDS = 3600  # 1 hour

# Personalization boost/suppress ranges
MAX_AFFINITY_BOOST = 0.5  # +50% max boost (1.0 -> 1.5)
HIDDEN_SUPPRESS_FACTOR = 0.1  # Suppress hidden tools to 10%


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class FeedbackRecord(BaseModel):
    """A single user feedback interaction."""

    id: str = Field("", description="Unique feedback record ID")
    user_id: str = Field(..., description="User identifier")
    tool_id: str = Field(..., description="Tool that was interacted with")
    recommendation_id: Optional[str] = Field(None, description="Original recommendation ID")
    interaction_type: InteractionType = Field(..., description="Type of interaction")
    strategies: List[str] = Field(default_factory=list, description="Strategies that surfaced this tool")
    context: Dict[str, Any] = Field(default_factory=dict, description="Context at time of interaction")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"from_attributes": True}


class FeedbackSubmission(BaseModel):
    """Request to submit feedback."""

    user_id: str = Field(..., description="User identifier")
    tool_id: str = Field(..., description="Tool identifier")
    recommendation_id: Optional[str] = Field(None, description="Recommendation that surfaced this")
    interaction_type: InteractionType = Field(..., description="Interaction type")
    strategies: List[str] = Field(default_factory=list, description="Contributing strategies")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context")


class FeedbackResponse(BaseModel):
    """Response after processing feedback."""

    success: bool = Field(True)
    feedback_id: str = Field("")
    processing_time_ms: float = Field(0.0)
    preferences_updated: bool = Field(False)


class UserPreferences(BaseModel):
    """Learned user preference model."""

    user_id: str = Field(..., description="User identifier")
    tool_affinities: Dict[str, float] = Field(default_factory=dict, description="tool_id -> affinity score")
    category_preferences: Dict[str, float] = Field(default_factory=dict, description="category -> preference")
    strategy_trust: Dict[str, float] = Field(default_factory=dict, description="strategy -> trust score")
    hidden_tools: Set[str] = Field(default_factory=set, description="Explicitly hidden tool IDs")
    total_interactions: int = Field(0, description="Total interaction count")
    personalization_ready: bool = Field(False, description=">=10 interactions for personalization")
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    decay_half_life_days: int = Field(DECAY_HALF_LIFE_DAYS)


class FeedbackStats(BaseModel):
    """Statistics about user feedback."""

    user_id: str
    total_interactions: int = 0
    interaction_counts: Dict[str, int] = Field(default_factory=dict)
    unique_tools_interacted: int = 0
    personalization_ready: bool = False
    oldest_interaction: Optional[datetime] = None
    newest_interaction: Optional[datetime] = None


# ---------------------------------------------------------------------------
# In-memory feedback store (Redis-like interface)
# ---------------------------------------------------------------------------


class FeedbackStore:
    """In-memory store for feedback records with Redis-compatible interface.

    In production, this would delegate to Redis. For simplicity and testability,
    this uses in-memory storage with the same API contract.
    """

    def __init__(self, redis_client: Optional[Any] = None):
        self._redis = redis_client
        self._feedback: Dict[str, List[FeedbackRecord]] = {}  # user_id -> records
        self._preferences_cache: Dict[str, UserPreferences] = {}
        self._cache_expiry: Dict[str, float] = {}

    async def store_feedback(self, record: FeedbackRecord) -> str:
        """Store a feedback record.

        Args:
            record: Feedback record to store.

        Returns:
            Feedback ID.
        """
        import hashlib

        feedback_id = hashlib.sha256(
            f"{record.user_id}:{record.tool_id}:{record.interaction_type}:{record.timestamp.isoformat()}".encode()
        ).hexdigest()[:16]
        record.id = feedback_id

        if record.user_id not in self._feedback:
            self._feedback[record.user_id] = []
        self._feedback[record.user_id].append(record)

        # Invalidate cached preferences
        self._preferences_cache.pop(record.user_id, None)
        self._cache_expiry.pop(record.user_id, None)

        if self._redis:
            try:
                import orjson

                key = f"feedback:{record.user_id}:{feedback_id}"
                await self._redis.set(key, orjson.dumps(record.model_dump(mode="json")), ex=DECAY_HALF_LIFE_DAYS * 86400)
            except Exception:
                logger.debug("Redis store_feedback failed, using in-memory only")

        return feedback_id

    def get_user_feedback(
        self,
        user_id: str,
        since: Optional[datetime] = None,
        interaction_type: Optional[InteractionType] = None,
    ) -> List[FeedbackRecord]:
        """Get feedback records for a user.

        Args:
            user_id: User to query.
            since: Only return feedback after this time.
            interaction_type: Filter by interaction type.

        Returns:
            List of matching feedback records.
        """
        records = self._feedback.get(user_id, [])

        if since:
            records = [r for r in records if r.timestamp >= since]

        if interaction_type:
            records = [r for r in records if r.interaction_type == interaction_type]

        return records

    def get_feedback_stats(self, user_id: str) -> FeedbackStats:
        """Get feedback statistics for a user.

        Args:
            user_id: User identifier.

        Returns:
            FeedbackStats for the user.
        """
        records = self._feedback.get(user_id, [])
        if not records:
            return FeedbackStats(user_id=user_id)

        counts: Dict[str, int] = {}
        tools: set[str] = set()
        for r in records:
            counts[r.interaction_type] = counts.get(r.interaction_type, 0) + 1
            tools.add(r.tool_id)

        timestamps = [r.timestamp for r in records]

        return FeedbackStats(
            user_id=user_id,
            total_interactions=len(records),
            interaction_counts=counts,
            unique_tools_interacted=len(tools),
            personalization_ready=len(records) >= MIN_INTERACTIONS_FOR_PERSONALIZATION,
            oldest_interaction=min(timestamps) if timestamps else None,
            newest_interaction=max(timestamps) if timestamps else None,
        )

    def get_cached_preferences(self, user_id: str) -> Optional[UserPreferences]:
        """Return cached preferences if still valid, else None."""
        cached = self._preferences_cache.get(user_id)
        if cached:
            expiry = self._cache_expiry.get(user_id, 0)
            if time.monotonic() < expiry:
                return cached
        return None

    def set_cached_preferences(self, user_id: str, prefs: UserPreferences) -> None:
        """Cache computed preferences with TTL."""
        self._preferences_cache[user_id] = prefs
        self._cache_expiry[user_id] = time.monotonic() + PREFERENCE_CACHE_TTL_SECONDS


# ---------------------------------------------------------------------------
# Preference model builder
# ---------------------------------------------------------------------------


class PreferenceModelBuilder:
    """Builds personalized preference models from feedback history.

    Learns tool affinities, category preferences, and strategy trust
    scores from 90-day interaction history with exponential decay.
    """

    def __init__(self, feedback_store: FeedbackStore):
        self._store = feedback_store

    def build_preferences(self, user_id: str) -> UserPreferences:
        """Build a preference model from user's feedback history.

        Uses 90-day interaction window with exponential time decay.
        Requires minimum 10 interactions before activating personalization.

        Args:
            user_id: User to build preferences for.

        Returns:
            UserPreferences model.
        """
        # Check cache
        cached = self._store.get_cached_preferences(user_id)
        if cached:
            return cached

        now = datetime.now(timezone.utc)
        since = now - timedelta(days=DECAY_HALF_LIFE_DAYS * 2)  # Look back 2x half-life
        records = self._store.get_user_feedback(user_id, since=since)

        tool_affinities: Dict[str, float] = {}
        category_counts: Dict[str, float] = {}
        strategy_scores: Dict[str, List[float]] = {}
        hidden_tools: Set[str] = set()

        for record in records:
            age_days = (now - record.timestamp).total_seconds() / 86400
            decay = math.exp(-DECAY_LAMBDA * age_days)
            delta = AFFINITY_DELTAS.get(record.interaction_type, 0.0)
            weighted_delta = delta * decay

            # Tool affinity
            current = tool_affinities.get(record.tool_id, 0.0)
            tool_affinities[record.tool_id] = current + weighted_delta

            # Track hidden tools
            if record.interaction_type == InteractionType.HIDDEN:
                hidden_tools.add(record.tool_id)

            # Category preferences from context
            categories = record.context.get("categories", [])
            for cat in categories:
                category_counts[cat] = category_counts.get(cat, 0.0) + weighted_delta

            # Strategy trust
            for strategy in record.strategies:
                if strategy not in strategy_scores:
                    strategy_scores[strategy] = []
                # Positive interactions increase trust
                trust_delta = 1.0 if delta > 0 else -0.5 if delta < 0 else 0.0
                strategy_scores[strategy].append(trust_delta * decay)

        # Normalize strategy trust to [0, 1]
        strategy_trust: Dict[str, float] = {}
        for strat, scores in strategy_scores.items():
            if scores:
                avg = sum(scores) / len(scores)
                strategy_trust[strat] = max(0.0, min(1.0, 0.5 + avg * 0.5))

        total_interactions = len(records)
        personalization_ready = total_interactions >= MIN_INTERACTIONS_FOR_PERSONALIZATION

        prefs = UserPreferences(
            user_id=user_id,
            tool_affinities=tool_affinities,
            category_preferences=category_counts,
            strategy_trust=strategy_trust,
            hidden_tools=hidden_tools,
            total_interactions=total_interactions,
            personalization_ready=personalization_ready,
            decay_half_life_days=DECAY_HALF_LIFE_DAYS,
        )

        # Cache with TTL
        self._store.set_cached_preferences(user_id, prefs)

        return prefs

    def get_personalization_multipliers(self, user_id: str) -> Dict[str, float]:
        """Get per-tool personalization multipliers for ranking.

        Returns multipliers in the range [0.1, 1.5]:
        - High affinity tools: 1.1 - 1.5x boost
        - Neutral tools: 1.0x (no change)
        - Hidden tools: 0.1x (strong suppression)

        Args:
            user_id: User identifier.

        Returns:
            Dict mapping tool_id to multiplier offset from 1.0.
            Positive values boost, negative suppress.
        """
        prefs = self.build_preferences(user_id)
        if not prefs.personalization_ready:
            return {}

        multipliers: Dict[str, float] = {}
        for tool_id, affinity in prefs.tool_affinities.items():
            if tool_id in prefs.hidden_tools:
                multipliers[tool_id] = -0.9  # Will result in 0.1x
            else:
                # Clamp affinity to boost range
                multipliers[tool_id] = max(-0.9, min(MAX_AFFINITY_BOOST, affinity))

        return multipliers

    def get_hidden_tools(self, user_id: str) -> Set[str]:
        """Get set of tools the user has explicitly hidden.

        Args:
            user_id: User identifier.

        Returns:
            Set of hidden tool_ids.
        """
        prefs = self.build_preferences(user_id)
        return prefs.hidden_tools


# ---------------------------------------------------------------------------
# Feedback service (high-level API)
# ---------------------------------------------------------------------------


class FeedbackService:
    """High-level service for processing feedback and querying preferences.

    Processes feedback in under 20ms and updates preferences in real-time.
    """

    def __init__(self, redis_client: Optional[Any] = None):
        self.store = FeedbackStore(redis_client=redis_client)
        self.preference_builder = PreferenceModelBuilder(self.store)

    async def process_feedback(self, submission: FeedbackSubmission) -> FeedbackResponse:
        """Process a feedback submission.

        Args:
            submission: Feedback to process.

        Returns:
            FeedbackResponse with processing metadata.
        """
        start = time.monotonic()

        record = FeedbackRecord(
            id="",
            user_id=submission.user_id,
            tool_id=submission.tool_id,
            recommendation_id=submission.recommendation_id,
            interaction_type=submission.interaction_type,
            strategies=submission.strategies,
            context=submission.context,
        )

        feedback_id = await self.store.store_feedback(record)

        # Rebuild preferences (invalidates cache)
        self.preference_builder.build_preferences(submission.user_id)

        elapsed_ms = (time.monotonic() - start) * 1000
        return FeedbackResponse(
            success=True,
            feedback_id=feedback_id,
            processing_time_ms=round(elapsed_ms, 2),
            preferences_updated=True,
        )

    def get_preferences(self, user_id: str) -> UserPreferences:
        """Get current user preferences.

        Args:
            user_id: User identifier.

        Returns:
            UserPreferences model.
        """
        return self.preference_builder.build_preferences(user_id)

    def get_personalization(self, user_id: str) -> Dict[str, float]:
        """Get personalization multipliers for ranking.

        Args:
            user_id: User identifier.

        Returns:
            Dict mapping tool_id to affinity offset.
        """
        return self.preference_builder.get_personalization_multipliers(user_id)

    def get_hidden_tools(self, user_id: str) -> Set[str]:
        """Get hidden tool set.

        Args:
            user_id: User identifier.

        Returns:
            Set of hidden tool_ids.
        """
        return self.preference_builder.get_hidden_tools(user_id)

    def get_stats(self, user_id: str) -> FeedbackStats:
        """Get feedback statistics.

        Args:
            user_id: User identifier.

        Returns:
            FeedbackStats.
        """
        return self.store.get_feedback_stats(user_id)
