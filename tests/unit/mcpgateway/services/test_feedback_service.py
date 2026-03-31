# -*- coding: utf-8 -*-
"""Tests for the User Feedback Collection and Personalized Preference Model.

Covers:
- FeedbackStore: store, retrieve, stats, cache invalidation
- PreferenceModelBuilder: affinity calculation, decay, hidden tools,
  category preferences, strategy trust, min interactions threshold
- FeedbackService: end-to-end processing under 20ms
- Edge cases: empty history, single interaction, boundary values

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import math
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services.feedback_service import (
    AFFINITY_DELTAS,
    DECAY_HALF_LIFE_DAYS,
    DECAY_LAMBDA,
    MIN_INTERACTIONS_FOR_PERSONALIZATION,
    PREFERENCE_CACHE_TTL_SECONDS,
    FeedbackRecord,
    FeedbackResponse,
    FeedbackService,
    FeedbackStats,
    FeedbackStore,
    FeedbackSubmission,
    InteractionType,
    PreferenceModelBuilder,
    UserPreferences,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def store():
    """Create an in-memory FeedbackStore."""
    return FeedbackStore()


@pytest.fixture
def builder(store):
    """Create a PreferenceModelBuilder with in-memory store."""
    return PreferenceModelBuilder(store)


@pytest.fixture
def service():
    """Create a FeedbackService with no Redis."""
    return FeedbackService()


@pytest.fixture
def mock_redis():
    """Create a mock async Redis client."""
    redis = AsyncMock()
    redis.set = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    return redis


# ============================================================================
# InteractionType tests
# ============================================================================


class TestInteractionTypes:
    """Tests for interaction type enumeration."""

    def test_all_types_defined(self):
        assert InteractionType.CLICKED == "CLICKED"
        assert InteractionType.USED == "USED"
        assert InteractionType.DISMISSED == "DISMISSED"
        assert InteractionType.HIDDEN == "HIDDEN"

    def test_affinity_deltas_defined(self):
        assert AFFINITY_DELTAS[InteractionType.USED] == 0.3
        assert AFFINITY_DELTAS[InteractionType.CLICKED] == 0.1
        assert AFFINITY_DELTAS[InteractionType.DISMISSED] == -0.2
        assert AFFINITY_DELTAS[InteractionType.HIDDEN] == -1.0

    def test_decay_constants(self):
        assert DECAY_HALF_LIFE_DAYS == 90
        expected_lambda = math.log(2) / 90
        assert abs(DECAY_LAMBDA - expected_lambda) < 1e-10


# ============================================================================
# Pydantic model tests
# ============================================================================


class TestPydanticModels:
    """Tests for feedback Pydantic models."""

    def test_feedback_record_creation(self):
        record = FeedbackRecord(
            user_id="user1",
            tool_id="tool1",
            interaction_type=InteractionType.USED,
            strategies=["semantic"],
        )
        assert record.user_id == "user1"
        assert record.interaction_type == InteractionType.USED
        assert record.timestamp is not None

    def test_feedback_submission(self):
        sub = FeedbackSubmission(
            user_id="u1",
            tool_id="t1",
            interaction_type=InteractionType.CLICKED,
            recommendation_id="rec-123",
            strategies=["semantic", "collaborative"],
            context={"page": "search"},
        )
        assert sub.recommendation_id == "rec-123"
        assert len(sub.strategies) == 2

    def test_user_preferences_model(self):
        prefs = UserPreferences(
            user_id="u1",
            tool_affinities={"t1": 0.5},
            hidden_tools={"t2"},
            total_interactions=15,
            personalization_ready=True,
        )
        assert prefs.personalization_ready
        assert "t2" in prefs.hidden_tools

    def test_feedback_stats_model(self):
        stats = FeedbackStats(
            user_id="u1",
            total_interactions=10,
            interaction_counts={"USED": 5, "CLICKED": 5},
            unique_tools_interacted=3,
            personalization_ready=True,
        )
        assert stats.total_interactions == 10


# ============================================================================
# FeedbackStore tests
# ============================================================================


class TestFeedbackStore:
    """Tests for the FeedbackStore."""

    @pytest.mark.asyncio
    async def test_store_feedback(self, store):
        record = FeedbackRecord(
            user_id="u1",
            tool_id="t1",
            interaction_type=InteractionType.USED,
        )
        fid = await store.store_feedback(record)
        assert fid
        assert len(fid) == 16

    @pytest.mark.asyncio
    async def test_store_generates_unique_ids(self, store):
        ids = set()
        for i in range(5):
            record = FeedbackRecord(
                user_id="u1",
                tool_id=f"t{i}",
                interaction_type=InteractionType.CLICKED,
            )
            fid = await store.store_feedback(record)
            ids.add(fid)
        assert len(ids) == 5

    @pytest.mark.asyncio
    async def test_retrieve_user_feedback(self, store):
        for i in range(3):
            await store.store_feedback(
                FeedbackRecord(
                    user_id="u1",
                    tool_id=f"t{i}",
                    interaction_type=InteractionType.USED,
                )
            )
        records = store.get_user_feedback("u1")
        assert len(records) == 3

    @pytest.mark.asyncio
    async def test_retrieve_empty_user(self, store):
        records = store.get_user_feedback("nonexistent")
        assert records == []

    @pytest.mark.asyncio
    async def test_filter_by_since(self, store):
        old_record = FeedbackRecord(
            user_id="u1",
            tool_id="t1",
            interaction_type=InteractionType.USED,
            timestamp=datetime.now(timezone.utc) - timedelta(days=100),
        )
        new_record = FeedbackRecord(
            user_id="u1",
            tool_id="t2",
            interaction_type=InteractionType.USED,
        )
        await store.store_feedback(old_record)
        await store.store_feedback(new_record)

        since = datetime.now(timezone.utc) - timedelta(days=1)
        records = store.get_user_feedback("u1", since=since)
        assert len(records) == 1
        assert records[0].tool_id == "t2"

    @pytest.mark.asyncio
    async def test_filter_by_interaction_type(self, store):
        await store.store_feedback(
            FeedbackRecord(user_id="u1", tool_id="t1", interaction_type=InteractionType.USED)
        )
        await store.store_feedback(
            FeedbackRecord(user_id="u1", tool_id="t2", interaction_type=InteractionType.HIDDEN)
        )

        used = store.get_user_feedback("u1", interaction_type=InteractionType.USED)
        assert len(used) == 1
        assert used[0].tool_id == "t1"

    @pytest.mark.asyncio
    async def test_feedback_stats(self, store):
        for interaction in [InteractionType.USED, InteractionType.USED, InteractionType.CLICKED]:
            await store.store_feedback(
                FeedbackRecord(user_id="u1", tool_id="t1", interaction_type=interaction)
            )
        stats = store.get_feedback_stats("u1")
        assert stats.total_interactions == 3
        assert stats.interaction_counts["USED"] == 2
        assert stats.interaction_counts["CLICKED"] == 1
        assert stats.unique_tools_interacted == 1

    @pytest.mark.asyncio
    async def test_feedback_stats_empty(self, store):
        stats = store.get_feedback_stats("nobody")
        assert stats.total_interactions == 0
        assert not stats.personalization_ready

    @pytest.mark.asyncio
    async def test_store_invalidates_cache(self, store):
        # Manually set cache
        store._preferences_cache["u1"] = UserPreferences(user_id="u1")
        store._cache_expiry["u1"] = time.monotonic() + 3600

        await store.store_feedback(
            FeedbackRecord(user_id="u1", tool_id="t1", interaction_type=InteractionType.USED)
        )

        assert "u1" not in store._preferences_cache

    @pytest.mark.asyncio
    async def test_store_with_redis_fallback(self, mock_redis):
        store = FeedbackStore(redis_client=mock_redis)
        record = FeedbackRecord(
            user_id="u1",
            tool_id="t1",
            interaction_type=InteractionType.USED,
        )
        fid = await store.store_feedback(record)
        assert fid
        mock_redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_with_redis_failure(self, mock_redis):
        mock_redis.set = AsyncMock(side_effect=Exception("Redis down"))
        store = FeedbackStore(redis_client=mock_redis)
        record = FeedbackRecord(
            user_id="u1",
            tool_id="t1",
            interaction_type=InteractionType.USED,
        )
        fid = await store.store_feedback(record)
        # Should still work with in-memory fallback
        assert fid
        records = store.get_user_feedback("u1")
        assert len(records) == 1


# ============================================================================
# PreferenceModelBuilder tests
# ============================================================================


class TestPreferenceModelBuilder:
    """Tests for the preference model builder."""

    @pytest.mark.asyncio
    async def test_build_empty_preferences(self, builder):
        prefs = builder.build_preferences("u1")
        assert prefs.user_id == "u1"
        assert prefs.total_interactions == 0
        assert not prefs.personalization_ready

    @pytest.mark.asyncio
    async def test_build_with_insufficient_interactions(self, store, builder):
        for i in range(5):
            await store.store_feedback(
                FeedbackRecord(user_id="u1", tool_id=f"t{i}", interaction_type=InteractionType.CLICKED)
            )
        prefs = builder.build_preferences("u1")
        assert prefs.total_interactions == 5
        assert not prefs.personalization_ready

    @pytest.mark.asyncio
    async def test_build_with_sufficient_interactions(self, store, builder):
        for i in range(MIN_INTERACTIONS_FOR_PERSONALIZATION):
            await store.store_feedback(
                FeedbackRecord(user_id="u1", tool_id=f"t{i % 3}", interaction_type=InteractionType.USED)
            )
        prefs = builder.build_preferences("u1")
        assert prefs.personalization_ready
        assert prefs.total_interactions >= MIN_INTERACTIONS_FOR_PERSONALIZATION

    @pytest.mark.asyncio
    async def test_used_increases_affinity(self, store, builder):
        await store.store_feedback(
            FeedbackRecord(user_id="u1", tool_id="t1", interaction_type=InteractionType.USED)
        )
        prefs = builder.build_preferences("u1")
        assert prefs.tool_affinities.get("t1", 0) > 0

    @pytest.mark.asyncio
    async def test_clicked_increases_affinity_less(self, store, builder):
        await store.store_feedback(
            FeedbackRecord(user_id="u1", tool_id="t1", interaction_type=InteractionType.CLICKED)
        )
        await store.store_feedback(
            FeedbackRecord(user_id="u1", tool_id="t2", interaction_type=InteractionType.USED)
        )
        prefs = builder.build_preferences("u1")
        assert prefs.tool_affinities.get("t2", 0) > prefs.tool_affinities.get("t1", 0)

    @pytest.mark.asyncio
    async def test_hidden_decreases_affinity(self, store, builder):
        await store.store_feedback(
            FeedbackRecord(user_id="u1", tool_id="t1", interaction_type=InteractionType.HIDDEN)
        )
        prefs = builder.build_preferences("u1")
        assert prefs.tool_affinities.get("t1", 0) < 0

    @pytest.mark.asyncio
    async def test_hidden_tools_tracked(self, store, builder):
        await store.store_feedback(
            FeedbackRecord(user_id="u1", tool_id="t1", interaction_type=InteractionType.HIDDEN)
        )
        prefs = builder.build_preferences("u1")
        assert "t1" in prefs.hidden_tools

    @pytest.mark.asyncio
    async def test_exponential_decay(self, store, builder):
        """Recent interactions should have more weight than old ones."""
        now = datetime.now(timezone.utc)

        # Old interaction (60 days ago)
        await store.store_feedback(
            FeedbackRecord(
                user_id="u1",
                tool_id="old-tool",
                interaction_type=InteractionType.USED,
                timestamp=now - timedelta(days=60),
            )
        )
        # Recent interaction (1 day ago)
        await store.store_feedback(
            FeedbackRecord(
                user_id="u1",
                tool_id="new-tool",
                interaction_type=InteractionType.USED,
                timestamp=now - timedelta(days=1),
            )
        )

        prefs = builder.build_preferences("u1")
        # New tool should have higher affinity due to less decay
        assert prefs.tool_affinities.get("new-tool", 0) > prefs.tool_affinities.get("old-tool", 0)

    @pytest.mark.asyncio
    async def test_decay_formula(self, store, builder):
        """Verify the decay formula: delta * exp(-lambda * age_days)."""
        now = datetime.now(timezone.utc)
        age_days = 45  # Half of half-life

        await store.store_feedback(
            FeedbackRecord(
                user_id="u1",
                tool_id="t1",
                interaction_type=InteractionType.USED,
                timestamp=now - timedelta(days=age_days),
            )
        )

        prefs = builder.build_preferences("u1")
        expected = AFFINITY_DELTAS[InteractionType.USED] * math.exp(-DECAY_LAMBDA * age_days)
        actual = prefs.tool_affinities.get("t1", 0)
        assert abs(actual - expected) < 0.01

    @pytest.mark.asyncio
    async def test_category_preferences(self, store, builder):
        await store.store_feedback(
            FeedbackRecord(
                user_id="u1",
                tool_id="t1",
                interaction_type=InteractionType.USED,
                context={"categories": ["api", "data"]},
            )
        )
        prefs = builder.build_preferences("u1")
        assert "api" in prefs.category_preferences
        assert prefs.category_preferences["api"] > 0

    @pytest.mark.asyncio
    async def test_strategy_trust_scores(self, store, builder):
        await store.store_feedback(
            FeedbackRecord(
                user_id="u1",
                tool_id="t1",
                interaction_type=InteractionType.USED,
                strategies=["semantic"],
            )
        )
        prefs = builder.build_preferences("u1")
        assert "semantic" in prefs.strategy_trust
        assert prefs.strategy_trust["semantic"] > 0.5  # Positive trust

    @pytest.mark.asyncio
    async def test_strategy_trust_negative(self, store, builder):
        await store.store_feedback(
            FeedbackRecord(
                user_id="u1",
                tool_id="t1",
                interaction_type=InteractionType.HIDDEN,
                strategies=["trending"],
            )
        )
        prefs = builder.build_preferences("u1")
        assert "trending" in prefs.strategy_trust
        assert prefs.strategy_trust["trending"] < 0.5  # Negative trust

    @pytest.mark.asyncio
    async def test_preference_caching(self, store, builder):
        await store.store_feedback(
            FeedbackRecord(user_id="u1", tool_id="t1", interaction_type=InteractionType.USED)
        )
        p1 = builder.build_preferences("u1")
        p2 = builder.build_preferences("u1")  # Should hit cache
        assert p1.computed_at == p2.computed_at

    @pytest.mark.asyncio
    async def test_get_personalization_multipliers_ready(self, store, builder):
        for i in range(MIN_INTERACTIONS_FOR_PERSONALIZATION):
            await store.store_feedback(
                FeedbackRecord(user_id="u1", tool_id="t1", interaction_type=InteractionType.USED)
            )
        multipliers = builder.get_personalization_multipliers("u1")
        assert "t1" in multipliers
        assert multipliers["t1"] > 0  # Positive boost

    @pytest.mark.asyncio
    async def test_get_personalization_multipliers_not_ready(self, store, builder):
        await store.store_feedback(
            FeedbackRecord(user_id="u1", tool_id="t1", interaction_type=InteractionType.USED)
        )
        multipliers = builder.get_personalization_multipliers("u1")
        assert multipliers == {}  # Not enough interactions

    @pytest.mark.asyncio
    async def test_get_hidden_tools(self, store, builder):
        await store.store_feedback(
            FeedbackRecord(user_id="u1", tool_id="t1", interaction_type=InteractionType.HIDDEN)
        )
        hidden = builder.get_hidden_tools("u1")
        assert "t1" in hidden

    @pytest.mark.asyncio
    async def test_multiplier_clamped_for_hidden(self, store, builder):
        for i in range(MIN_INTERACTIONS_FOR_PERSONALIZATION):
            await store.store_feedback(
                FeedbackRecord(user_id="u1", tool_id="hidden-tool", interaction_type=InteractionType.HIDDEN)
            )
        multipliers = builder.get_personalization_multipliers("u1")
        assert multipliers.get("hidden-tool", 0) == -0.9  # Will result in 0.1x


# ============================================================================
# FeedbackService tests
# ============================================================================


class TestFeedbackService:
    """Tests for the high-level FeedbackService."""

    @pytest.mark.asyncio
    async def test_process_feedback(self, service):
        submission = FeedbackSubmission(
            user_id="u1",
            tool_id="t1",
            interaction_type=InteractionType.USED,
            recommendation_id="rec-1",
            strategies=["semantic"],
        )
        response = await service.process_feedback(submission)
        assert response.success
        assert response.feedback_id
        assert response.preferences_updated

    @pytest.mark.asyncio
    async def test_process_feedback_under_20ms(self, service):
        """Feedback processing must complete in under 20ms."""
        submission = FeedbackSubmission(
            user_id="u1",
            tool_id="t1",
            interaction_type=InteractionType.CLICKED,
        )
        start = time.monotonic()
        response = await service.process_feedback(submission)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 20, f"Feedback processing took {elapsed_ms:.1f}ms, exceeds 20ms"
        assert response.success

    @pytest.mark.asyncio
    async def test_get_preferences(self, service):
        await service.process_feedback(
            FeedbackSubmission(user_id="u1", tool_id="t1", interaction_type=InteractionType.USED)
        )
        prefs = service.get_preferences("u1")
        assert prefs.user_id == "u1"
        assert prefs.total_interactions == 1

    @pytest.mark.asyncio
    async def test_get_personalization(self, service):
        personalization = service.get_personalization("u1")
        assert isinstance(personalization, dict)

    @pytest.mark.asyncio
    async def test_get_hidden_tools(self, service):
        await service.process_feedback(
            FeedbackSubmission(user_id="u1", tool_id="t1", interaction_type=InteractionType.HIDDEN)
        )
        hidden = service.get_hidden_tools("u1")
        assert "t1" in hidden

    @pytest.mark.asyncio
    async def test_get_stats(self, service):
        await service.process_feedback(
            FeedbackSubmission(user_id="u1", tool_id="t1", interaction_type=InteractionType.USED)
        )
        stats = service.get_stats("u1")
        assert stats.total_interactions == 1

    @pytest.mark.asyncio
    async def test_real_time_preference_update(self, service):
        """Preferences should update in real-time after feedback."""
        await service.process_feedback(
            FeedbackSubmission(user_id="u1", tool_id="t1", interaction_type=InteractionType.USED)
        )
        p1 = service.get_preferences("u1")
        assert p1.tool_affinities.get("t1", 0) > 0

        await service.process_feedback(
            FeedbackSubmission(user_id="u1", tool_id="t1", interaction_type=InteractionType.HIDDEN)
        )
        p2 = service.get_preferences("u1")
        # Affinity should decrease after HIDDEN
        assert p2.tool_affinities.get("t1", 0) < p1.tool_affinities.get("t1", 0)

    @pytest.mark.asyncio
    async def test_multiple_users_isolated(self, service):
        await service.process_feedback(
            FeedbackSubmission(user_id="u1", tool_id="t1", interaction_type=InteractionType.USED)
        )
        await service.process_feedback(
            FeedbackSubmission(user_id="u2", tool_id="t2", interaction_type=InteractionType.HIDDEN)
        )

        p1 = service.get_preferences("u1")
        p2 = service.get_preferences("u2")

        assert "t1" in p1.tool_affinities
        assert "t1" not in p2.tool_affinities
        assert "t2" not in p1.tool_affinities
        assert "t2" in p2.tool_affinities
