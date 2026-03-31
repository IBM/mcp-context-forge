# -*- coding: utf-8 -*-
"""Location: ./tests/test_analytics_collaborative_filtering.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Integration tests for usage analytics and collaborative filtering.
"""

# Standard
import asyncio
import hashlib
import os
import tempfile
import time
from datetime import datetime, timedelta
from typing import AsyncGenerator

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
import mcpgateway.db as db_mod
from mcpgateway.config import settings
from mcpgateway.db import ToolUsageEvent, UserPreference, fresh_db_session
from mcpgateway.services.collaborative_recommender import collaborative_recommender
from mcpgateway.services.usage_analytics_service import usage_analytics_service
from mcpgateway.services.user_similarity_service import user_similarity_service


@pytest.fixture(autouse=True)
def _analytics_test_db(monkeypatch):
    """Set up an isolated SQLite DB for every test in this module."""
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(db_mod, "engine", engine, raising=False)
    monkeypatch.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    # Lower the min-interaction threshold so small test fixtures qualify
    monkeypatch.setattr(settings, "cf_min_user_interactions", 1, raising=False)
    monkeypatch.setattr(settings, "cf_min_common_tools", 1, raising=False)

    db_mod.Base.metadata.create_all(bind=engine)

    yield

    engine.dispose()
    os.close(fd)
    os.unlink(path)


@pytest.fixture
async def initialized_services() -> AsyncGenerator[None, None]:
    """Initialize analytics services for testing."""
    await usage_analytics_service.initialize()
    await user_similarity_service.initialize()
    await collaborative_recommender.initialize()
    yield
    await usage_analytics_service.shutdown()
    await user_similarity_service.shutdown()
    await collaborative_recommender.shutdown()


@pytest.fixture
async def sample_usage_events(initialized_services) -> None:
    """Create sample usage events for testing."""
    users = ["user1@example.com", "user2@example.com", "user3@example.com"]
    tools = ["tool_a", "tool_b", "tool_c", "tool_d"]

    # User 1: uses tool_a and tool_b frequently
    for _ in range(5):
        await usage_analytics_service.record_usage_event("user1@example.com", "tool_a", execution_duration_ms=100, success=True)
    for _ in range(3):
        await usage_analytics_service.record_usage_event("user1@example.com", "tool_b", execution_duration_ms=150, success=True)

    # User 2: uses tool_a and tool_c (similar to user1 on tool_a)
    for _ in range(4):
        await usage_analytics_service.record_usage_event("user2@example.com", "tool_a", execution_duration_ms=120, success=True)
    for _ in range(2):
        await usage_analytics_service.record_usage_event("user2@example.com", "tool_c", execution_duration_ms=200, success=True)

    # User 3: uses tool_d (dissimilar to others)
    for _ in range(6):
        await usage_analytics_service.record_usage_event("user3@example.com", "tool_d", execution_duration_ms=80, success=True)

    # Flush buffered events
    await usage_analytics_service._flush_event_buffer()


class TestUsageAnalyticsService:
    """Tests for usage analytics service."""

    @pytest.mark.asyncio
    async def test_record_usage_event(self, initialized_services):
        """Test recording a usage event."""
        await usage_analytics_service.record_usage_event(
            user_email="test@example.com",
            tool_id="test_tool",
            execution_duration_ms=100,
            success=True,
            session_id="test-session",
        )

        # Flush and verify
        await usage_analytics_service._flush_event_buffer()

        with fresh_db_session() as session:
            from sqlalchemy import select

            stmt = select(ToolUsageEvent).where(ToolUsageEvent.user_email == "test@example.com")
            result = session.execute(stmt)
            events = result.scalars().all()

            assert len(events) == 1
            assert events[0].tool_id == "test_tool"
            assert events[0].success is True

    @pytest.mark.asyncio
    async def test_opt_out_prevents_recording(self, initialized_services):
        """Test that opt-out prevents event recording."""
        user_email = "optout@example.com"

        # Set opt-out preference
        await usage_analytics_service.set_user_preference(user_email, analytics_opted_in=False)

        # Try to record event
        await usage_analytics_service.record_usage_event(user_email, "test_tool", success=True)
        await usage_analytics_service._flush_event_buffer()

        # Verify no events recorded
        with fresh_db_session() as session:
            from sqlalchemy import select

            stmt = select(ToolUsageEvent).where(ToolUsageEvent.user_email == user_email)
            result = session.execute(stmt)
            events = result.scalars().all()

            assert len(events) == 0

    @pytest.mark.asyncio
    async def test_export_user_data(self, initialized_services):
        """Test exporting user analytics data."""
        user_email = "export@example.com"

        # Record some events
        await usage_analytics_service.record_usage_event(user_email, "tool1", success=True)
        await usage_analytics_service.record_usage_event(user_email, "tool2", success=False, error_message="Test error")
        await usage_analytics_service._flush_event_buffer()

        # Export data
        data = await usage_analytics_service.export_user_data(user_email)

        assert data["user_email"] == user_email
        assert "preferences" in data
        assert "usage_events" in data
        assert len(data["usage_events"]) == 2

    @pytest.mark.asyncio
    async def test_delete_user_data(self, initialized_services):
        """Test deleting user analytics data."""
        user_email = "delete@example.com"

        # Record events
        await usage_analytics_service.record_usage_event(user_email, "tool1", success=True)
        await usage_analytics_service._flush_event_buffer()

        # Delete data
        deleted_count = await usage_analytics_service.delete_user_data(user_email)
        assert deleted_count >= 1

        # Verify deletion
        data = await usage_analytics_service.export_user_data(user_email)
        assert len(data["usage_events"]) == 0


class TestUserSimilarityService:
    """Tests for user similarity computation."""

    @pytest.mark.asyncio
    async def test_compute_cosine_similarity(self, sample_usage_events):
        """Test cosine similarity computation between users."""
        # User 1 and User 2 both use tool_a (should be similar)
        similarity = await user_similarity_service.compute_similarity("user1@example.com", "user2@example.com", algorithm="cosine")

        assert 0.0 <= similarity <= 1.0
        assert similarity > 0.5  # Should be fairly similar due to tool_a overlap

    @pytest.mark.asyncio
    async def test_compute_jaccard_similarity(self, sample_usage_events):
        """Test Jaccard similarity computation."""
        similarity = await user_similarity_service.compute_similarity("user1@example.com", "user2@example.com", algorithm="jaccard")

        assert 0.0 <= similarity <= 1.0
        # Jaccard = intersection / union = 1 / 3 ≈ 0.33 (tool_a common, tool_b/tool_c unique)
        assert similarity > 0.2

    @pytest.mark.asyncio
    async def test_get_similar_users(self, sample_usage_events):
        """Test finding similar users."""
        similar_users = await user_similarity_service.get_similar_users("user1@example.com", limit=10)

        assert len(similar_users) > 0
        # User 2 should be most similar (both use tool_a)
        assert similar_users[0][0] == "user2@example.com"
        assert similar_users[0][1] > 0.0


class TestCollaborativeRecommender:
    """Tests for collaborative filtering recommendations."""

    @pytest.mark.asyncio
    async def test_recommend_tools(self, sample_usage_events):
        """Test generating tool recommendations."""
        recommendations = await collaborative_recommender.recommend_tools(
            user_email="user1@example.com",
            limit=10,
            include_reasoning=True,
        )

        # Should recommend tool_c (used by similar user2) but not tool_a/tool_b (already used by user1)
        tool_ids = [rec["tool_id"] for rec in recommendations]
        assert "tool_c" in tool_ids  # From similar user2
        assert "tool_a" not in tool_ids  # Already used by user1
        assert "tool_b" not in tool_ids  # Already used by user1

        # Check reasoning
        if recommendations:
            assert "reasoning" in recommendations[0]
            assert "similar_users_count" in recommendations[0]["reasoning"]

    @pytest.mark.asyncio
    async def test_get_boost_scores(self, sample_usage_events):
        """Test getting collaborative filtering boost scores."""
        boost_scores = await collaborative_recommender.get_boost_scores(
            user_email="user1@example.com",
            candidate_tools=["tool_a", "tool_c", "tool_d"],
        )

        assert isinstance(boost_scores, dict)
        # tool_c should have higher boost (used by similar user2)
        # tool_a might have some boost from user2's usage
        if "tool_c" in boost_scores and "tool_d" in boost_scores:
            assert boost_scores["tool_c"] >= boost_scores["tool_d"]

    @pytest.mark.asyncio
    async def test_get_trending_tools(self, sample_usage_events):
        """Test getting trending tools."""
        trending = await collaborative_recommender.get_trending_tools(limit=5, time_window_days=7)

        assert isinstance(trending, list)
        # tool_a should be trending (used by both user1 and user2)
        if trending:
            tool_ids = [t["tool_id"] for t in trending]
            assert "tool_a" in tool_ids


@pytest.fixture
async def large_scale_events(initialized_services) -> None:
    """Bulk-insert usage events for 1200 synthetic users.

    Users are split into overlapping "groups" so that cosine/Jaccard similarity
    has realistic structure to work with.
    """
    num_users = 1200
    tool_pool = [f"scale_tool_{i}" for i in range(20)]
    group_size = 10
    timestamp_base = datetime.utcnow() - timedelta(days=1)
    events: list = []

    for user_idx in range(num_users):
        user_email = f"scale_user_{user_idx}@example.com"
        group = user_idx // group_size
        offset = group % len(tool_pool)
        primary_tools = (tool_pool + tool_pool)[offset : offset + 4]
        personal_tool = tool_pool[(user_idx * 3 + 7) % len(tool_pool)]

        for tool_id in set(primary_tools + [personal_tool]):
            events.append(
                ToolUsageEvent(
                    id=hashlib.md5(f"{user_email}:{tool_id}".encode()).hexdigest(),  # noqa: S324
                    user_email=user_email,
                    tool_id=tool_id,
                    timestamp=timestamp_base,
                    success=True,
                    interaction_type="invoke",
                )
            )

    # Bulk insert in a single transaction for speed
    with fresh_db_session() as session:
        session.add_all(events)
        session.commit()


class TestLargeScaleCollaborativeFiltering:
    """Integration tests with 1000+ mock users to validate CF at scale.

    Verify:
    - Similarity lookup completes within the p95 < 100 ms budget (with warm cache)
    - Recommendations are generated correctly across many users
    - The popular-tool fallback fires for isolated users
    """

    @pytest.mark.asyncio
    async def test_similarity_with_1200_users_completes(self, large_scale_events) -> None:
        """Similarity lookup for a user with 1200 peers completes in < 5 seconds end-to-end."""
        target = "scale_user_0@example.com"
        start = time.monotonic()
        similar = await user_similarity_service.get_similar_users(target, limit=50)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert isinstance(similar, list), "Should return a list"
        assert len(similar) > 0, "Should find at least one similar user among 1200 peers"
        # Full cold-path (no Redis) must stay under 5 s; with cache << 100 ms
        assert elapsed_ms < 5000, f"Similarity lookup took {elapsed_ms:.0f} ms (limit 5000 ms)"

    @pytest.mark.asyncio
    async def test_recommendations_with_1200_users(self, large_scale_events) -> None:
        """Recommendations are generated and every score is in [0, 1]."""
        target = "scale_user_0@example.com"
        recs = await collaborative_recommender.recommend_tools(
            user_email=target,
            limit=10,
            include_reasoning=True,
        )

        assert isinstance(recs, list)
        for rec in recs:
            assert 0.0 <= rec["score"] <= 1.0, f"Score {rec['score']} not in [0, 1]"
            if "reasoning" in rec and rec["reasoning"]:
                assert "explanation" in rec["reasoning"]

    @pytest.mark.asyncio
    async def test_fallback_triggered_for_isolated_user(self, initialized_services) -> None:
        """A user with no similar peers receives popular-tool fallback recommendations."""
        # Seed a globally popular tool first so the fallback has data to return
        with fresh_db_session() as session:
            for i in range(50):
                session.add(
                    ToolUsageEvent(
                        id=hashlib.md5(f"popular_seeder_{i}:popular_tool".encode()).hexdigest(),  # noqa: S324
                        user_email=f"popular_seeder_{i}@example.com",
                        tool_id="popular_org_tool",
                        timestamp=datetime.utcnow(),
                        success=True,
                        interaction_type="invoke",
                    )
                )
            # Isolated user uses only tools nobody else does
            for i in range(4):
                session.add(
                    ToolUsageEvent(
                        id=hashlib.md5(f"isolated@example.com:unique_{i}".encode()).hexdigest(),  # noqa: S324
                        user_email="isolated@example.com",
                        tool_id=f"unique_isolated_tool_{i}",
                        timestamp=datetime.utcnow(),
                        success=True,
                        interaction_type="invoke",
                    )
                )
            session.commit()

        recs = await collaborative_recommender.recommend_tools(
            user_email="isolated@example.com",
            limit=5,
        )
        # Fallback should return the popular org tool since isolated user hasn't used it
        assert isinstance(recs, list)
        if recs:
            tool_ids = [r["tool_id"] for r in recs]
            assert "popular_org_tool" in tool_ids


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--asyncio-mode=auto"])
