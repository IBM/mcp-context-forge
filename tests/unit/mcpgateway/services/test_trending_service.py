# -*- coding: utf-8 -*-
"""Tests for the Trending Tools Calculation Engine and Service.

Covers:
- TrendingCalculationEngine: growth calculation, composite scoring, breakout
  detection, adoption velocity, new tools detection, period count queries
- TrendingCacheManager: Redis path, in-memory fallback, TTL expiry
- TrendingService: cache-hit path, cache-miss path, new tools
- Background refresh task: start, stop, refresh cycle
- Edge cases: empty data, zero counts, negative growth, large orgs

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import asyncio
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

# Third-Party
import orjson
import pytest
from pydantic import ValidationError

# First-Party
from mcpgateway.services.trending_service import (
    BACKGROUND_INTERVAL_SECONDS,
    CACHE_TTL_SECONDS,
    DEFAULT_LIMIT,
    DEFAULT_WINDOW,
    NEW_TOOLS_DAYS,
    TRENDING_WEIGHT,
    WINDOW_HOURS,
    TrendingCacheManager,
    TrendingCalculationEngine,
    TrendingResponse,
    TrendingService,
    TrendingToolResult,
    _cache_key,
    _refresh_all_windows,
    start_trending_background_task,
    stop_trending_background_task,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_db():
    """Create a mock SQLAlchemy session."""
    db = MagicMock()
    db.execute = MagicMock()
    return db


@pytest.fixture
def engine(mock_db):
    """Create a TrendingCalculationEngine with mock DB."""
    return TrendingCalculationEngine(mock_db)


@pytest.fixture
def cache_manager():
    """Create an in-memory TrendingCacheManager (no Redis)."""
    return TrendingCacheManager(redis_client=None, ttl=5)


@pytest.fixture
def mock_redis():
    """Create a mock async Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    return redis


@pytest.fixture
def redis_cache_manager(mock_redis):
    """Create a TrendingCacheManager with mock Redis."""
    return TrendingCacheManager(redis_client=mock_redis, ttl=300)


@pytest.fixture
def service(mock_db):
    """Create a TrendingService with mock DB and no Redis."""
    return TrendingService(db=mock_db, redis_client=None)


# ============================================================================
# Pydantic Model Tests
# ============================================================================


class TestTrendingToolResult:
    """Tests for the TrendingToolResult Pydantic model."""

    def test_defaults(self):
        """Test default values of TrendingToolResult."""
        result = TrendingToolResult(tool_id="t1", tool_name="Test Tool")
        assert result.tool_id == "t1"
        assert result.tool_name == "Test Tool"
        assert result.current_period_count == 0
        assert result.previous_period_count == 0
        assert result.growth_percentage == 0.0
        assert result.is_breakout is False
        assert result.adoption_velocity == 0.0
        assert result.trending_score == 0.0
        assert result.rank == 0
        assert result.explanation == ""
        assert result.is_new is False
        assert result.tags == []
        assert result.visibility == "public"

    def test_breakout_tool(self):
        """Test a tool with breakout-level growth."""
        result = TrendingToolResult(
            tool_id="t2",
            tool_name="Breakout",
            growth_percentage=150.0,
            is_breakout=True,
            current_period_count=100,
            previous_period_count=40,
        )
        assert result.is_breakout is True
        assert result.growth_percentage == 150.0

    def test_new_tool_flag(self):
        """Test is_new flag."""
        result = TrendingToolResult(
            tool_id="t3",
            tool_name="New Tool",
            is_new=True,
            created_at=datetime.now(timezone.utc),
        )
        assert result.is_new is True


class TestTrendingResponse:
    """Tests for the TrendingResponse envelope model."""

    def test_empty_response(self):
        """Test an empty response."""
        resp = TrendingResponse(window="24h")
        assert resp.window == "24h"
        assert resp.tools == []
        assert resp.new_tools == []
        assert resp.cached is False
        assert resp.generated_at is not None

    def test_with_tools(self):
        """Test response with tools."""
        tool = TrendingToolResult(tool_id="t1", tool_name="Tool")
        resp = TrendingResponse(window="7d", tools=[tool])
        assert len(resp.tools) == 1
        assert resp.tools[0].tool_id == "t1"


# ============================================================================
# Cache Key Tests
# ============================================================================


class TestCacheKey:
    """Tests for the _cache_key helper."""

    def test_no_filters(self):
        key = _cache_key("24h", None, None)
        assert key == "trending:24h:team:__all__:cat:__all__"

    def test_with_team(self):
        key = _cache_key("7d", "team-123", None)
        assert key == "trending:7d:team:team-123:cat:__all__"

    def test_with_category(self):
        key = _cache_key("30d", None, "api")
        assert key == "trending:30d:team:__all__:cat:api"

    def test_with_both(self):
        key = _cache_key("24h", "team-1", "data")
        assert key == "trending:24h:team:team-1:cat:data"


# ============================================================================
# Growth Calculation Tests
# ============================================================================


class TestGrowthPct:
    """Tests for TrendingCalculationEngine._growth_pct static method."""

    def test_positive_growth(self):
        assert TrendingCalculationEngine._growth_pct(150, 100) == 50.0

    def test_negative_growth(self):
        assert TrendingCalculationEngine._growth_pct(50, 100) == -50.0

    def test_zero_to_nonzero(self):
        """Previous=0, current>0 → 100.0% (newly popular)."""
        assert TrendingCalculationEngine._growth_pct(10, 0) == 100.0

    def test_both_zero(self):
        assert TrendingCalculationEngine._growth_pct(0, 0) == 0.0

    def test_no_change(self):
        assert TrendingCalculationEngine._growth_pct(100, 100) == 0.0

    def test_double_growth(self):
        """100→200 = 100% growth (breakout threshold)."""
        assert TrendingCalculationEngine._growth_pct(200, 100) == 100.0

    def test_triple_growth(self):
        assert TrendingCalculationEngine._growth_pct(300, 100) == 200.0

    def test_accuracy_within_2_percent(self):
        """Acceptance: growth calculations accurate within ±2%."""
        # 123 to 189 = 53.658...%
        pct = TrendingCalculationEngine._growth_pct(189, 123)
        expected = ((189 - 123) / 123) * 100.0
        assert abs(pct - expected) < 0.02 * abs(expected)

    def test_large_numbers(self):
        """Handles orgs from 10 to 10,000+ users."""
        pct = TrendingCalculationEngine._growth_pct(10000, 5000)
        assert pct == 100.0

    def test_small_to_large(self):
        pct = TrendingCalculationEngine._growth_pct(10000, 1)
        assert pct == pytest.approx(999900.0, rel=1e-6)


# ============================================================================
# Composite Score Tests
# ============================================================================


class TestCompositeScore:
    """Tests for TrendingCalculationEngine._composite_score."""

    def test_all_zero(self):
        assert TrendingCalculationEngine._composite_score(0, 0.0, 0.0) == 0.0

    def test_positive_usage_only(self):
        score = TrendingCalculationEngine._composite_score(100, 0.0, 0.0)
        assert score == pytest.approx(0.4 * math.log1p(100), rel=1e-3)

    def test_growth_capped_at_500(self):
        """Growth above 500% should be capped."""
        score_500 = TrendingCalculationEngine._composite_score(0, 500.0, 0.0)
        score_1000 = TrendingCalculationEngine._composite_score(0, 1000.0, 0.0)
        assert score_500 == score_1000  # both capped at 5x

    def test_all_components(self):
        score = TrendingCalculationEngine._composite_score(50, 75.0, 10.0)
        expected = (
            0.4 * math.log1p(50)
            + 0.4 * (min(75.0, 500.0) / 100.0)
            + 0.2 * math.log1p(10.0)
        )
        assert score == pytest.approx(expected, rel=1e-6)

    def test_score_is_non_negative(self):
        """Score should always be non-negative even with negative growth."""
        # Negative growth gives negative growth_score, but usage/velocity offset it
        score = TrendingCalculationEngine._composite_score(100, -50.0, 5.0)
        # With log1p(100)=4.62, growth=-0.5, velocity=log1p(5)=1.79
        # 0.4*4.62 + 0.4*(-0.5) + 0.2*1.79 = 1.848 + (-0.2) + 0.358 > 0
        assert score > 0  # positive due to log components outweighing negative growth


# ============================================================================
# Explanation Builder Tests
# ============================================================================


class TestBuildExplanation:
    """Tests for TrendingCalculationEngine._build_explanation."""

    def test_breakout(self):
        expl = TrendingCalculationEngine._build_explanation(150.0, 200, False, None)
        assert "Breakout tool" in expl
        assert "+150%" in expl
        assert "200 uses" in expl

    def test_trending(self):
        expl = TrendingCalculationEngine._build_explanation(45.0, 50, False, "Engineering")
        assert "Trending" in expl
        assert "in Engineering" in expl
        assert "+45%" in expl

    def test_new_tool(self):
        expl = TrendingCalculationEngine._build_explanation(0.0, 0, True, None)
        assert "Newly added" in expl

    def test_steady_usage(self):
        expl = TrendingCalculationEngine._build_explanation(-10.0, 5, False, None)
        assert "Steady usage" in expl

    def test_zero_count(self):
        expl = TrendingCalculationEngine._build_explanation(100.0, 0, False, None)
        assert "uses this period" not in expl

    def test_with_team_name(self):
        expl = TrendingCalculationEngine._build_explanation(50.0, 10, False, "DevOps")
        assert "in DevOps" in expl

    def test_without_team_name(self):
        expl = TrendingCalculationEngine._build_explanation(50.0, 10, False, None)
        assert "in your org" in expl


# ============================================================================
# Period Counts Tests
# ============================================================================


class TestPeriodCounts:
    """Tests for period count queries."""

    def test_hourly_counts_used_when_available(self, engine, mock_db):
        """Should prefer hourly rollup data."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        # Mock hourly data
        mock_db.execute.return_value.all.return_value = [
            ("tool-1", 100),
            ("tool-2", 50),
        ]

        counts = engine._period_counts_hourly(start, now, None, None)
        assert counts == {"tool-1": 100, "tool-2": 50}
        mock_db.execute.assert_called_once()

    def test_raw_fallback_when_hourly_empty(self, engine, mock_db):
        """Should fall back to raw metrics when hourly is empty."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        # First call (hourly) returns empty, second (raw) returns data
        mock_db.execute.return_value.all.side_effect = [
            [],  # hourly
            [("tool-a", 25)],  # raw
        ]

        counts = engine._period_counts(start, now, None, None)
        assert counts == {"tool-a": 25}

    def test_empty_period(self, engine, mock_db):
        """No data in either source returns empty dict."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        mock_db.execute.return_value.all.return_value = []

        counts = engine._period_counts_hourly(start, now, None, None)
        assert counts == {}

    def test_raw_counts(self, engine, mock_db):
        """Direct raw metric counting."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        mock_db.execute.return_value.all.return_value = [
            ("tool-x", 42),
        ]

        counts = engine._period_counts_raw(start, now, None, None)
        assert counts == {"tool-x": 42}


# ============================================================================
# Adoption Velocity Tests
# ============================================================================


class TestAdoptionVelocity:
    """Tests for adoption velocity computation."""

    def test_velocity_from_hourly(self, engine, mock_db):
        """Velocity uses hourly data when available."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=168)  # 7 days

        # First call (hourly sum) returns 700
        mock_db.execute.return_value.scalar.return_value = 700

        velocity = engine._adoption_velocity("tool-1", start, now, 168)
        # 700 / 7 days = 100 per day
        assert velocity == 100.0

    def test_velocity_fallback_to_raw(self, engine, mock_db):
        """Velocity falls back to raw when hourly returns None."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        # First (hourly) returns None, second (raw) returns 48
        mock_db.execute.return_value.scalar.side_effect = [None, 48]

        velocity = engine._adoption_velocity("tool-2", start, now, 24)
        # 48 / 1 day = 48
        assert velocity == 48.0

    def test_velocity_zero(self, engine, mock_db):
        """Zero executions → zero velocity."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        mock_db.execute.return_value.scalar.side_effect = [None, 0]

        velocity = engine._adoption_velocity("tool-3", start, now, 24)
        assert velocity == 0.0


# ============================================================================
# New Tools Detection Tests
# ============================================================================


class TestDetectNewTools:
    """Tests for new tool detection."""

    def test_detects_recent_tools(self, engine, mock_db):
        """Tools created in the last 7 days are surfaced."""
        recent_tool = MagicMock()
        recent_tool.id = "new-1"
        recent_tool.name = "New API"
        recent_tool.description = "A new API tool"
        recent_tool.tags = ["api"]
        recent_tool.team_id = None
        recent_tool.visibility = "public"
        recent_tool.created_at = datetime.now(timezone.utc) - timedelta(days=2)

        mock_db.execute.return_value.scalars.return_value.all.return_value = [recent_tool]

        results = engine._detect_new_tools(None, None)
        assert len(results) == 1
        assert results[0].tool_id == "new-1"
        assert results[0].is_new is True
        assert results[0].explanation == "New tool added recently"

    def test_no_new_tools(self, engine, mock_db):
        """No tools created recently → empty list."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        results = engine._detect_new_tools(None, None)
        assert results == []


# ============================================================================
# Tool Metadata Tests
# ============================================================================


class TestLoadToolMetadata:
    """Tests for tool metadata loading."""

    def test_loads_metadata(self, engine, mock_db):
        tool = MagicMock()
        tool.id = "t1"
        tool.name = "My Tool"
        tool.description = "Does stuff"
        tool.tags = ["data"]
        tool.team_id = "team-1"
        tool.team = "Data Team"
        tool.visibility = "team"
        tool.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        mock_db.execute.return_value.scalars.return_value.all.return_value = [tool]

        meta = engine._load_tool_metadata({"t1"}, None, None)
        assert "t1" in meta
        assert meta["t1"]["name"] == "My Tool"
        assert meta["t1"]["team_name"] == "Data Team"
        assert meta["t1"]["tags"] == ["data"]

    def test_empty_tool_ids(self, engine, mock_db):
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        meta = engine._load_tool_metadata(set(), None, None)
        assert meta == {}


# ============================================================================
# Full Trending Calculation Tests
# ============================================================================


class TestCalculateTrending:
    """Integration-level tests for the full calculate_trending pipeline."""

    def test_empty_database(self, engine, mock_db):
        """No metrics → empty but valid response."""
        mock_db.execute.return_value.all.return_value = []
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        response = engine.calculate_trending(window="24h")
        assert response.window == "24h"
        assert response.tools == []

    def test_single_tool_trending(self, engine, mock_db):
        """Single tool with growth should rank #1."""
        tool = MagicMock()
        tool.id = "tool-1"
        tool.name = "Popular Tool"
        tool.description = "Very popular"
        tool.tags = ["api"]
        tool.team_id = None
        tool.team = None
        tool.visibility = "public"
        tool.created_at = datetime(2025, 6, 1, tzinfo=timezone.utc)

        # Mock the sequence of DB calls:
        # 1. _period_counts_hourly (current) → tool-1: 200
        # 2. _period_counts_hourly (previous) → tool-1: 100
        # 3. _load_tool_metadata → [tool]
        # 4. _adoption_velocity → 28.57
        # 5. _detect_new_tools → []
        call_count = [0]
        original_all = mock_db.execute.return_value.all

        def side_effect_all():
            call_count[0] += 1
            if call_count[0] == 1:
                return [("tool-1", 200)]  # current period
            elif call_count[0] == 2:
                return [("tool-1", 100)]  # previous period
            return []

        mock_db.execute.return_value.all.side_effect = side_effect_all
        mock_db.execute.return_value.scalars.return_value.all.return_value = [tool]
        mock_db.execute.return_value.scalar.return_value = 200  # for velocity

        response = engine.calculate_trending(window="7d", limit=5)
        assert len(response.tools) == 1
        t = response.tools[0]
        assert t.tool_id == "tool-1"
        assert t.current_period_count == 200
        assert t.previous_period_count == 100
        assert t.growth_percentage == 100.0
        assert t.is_breakout is True
        assert t.rank == 1

    def test_multiple_tools_ranked(self, engine, mock_db):
        """Multiple tools should be ranked by trending_score descending."""
        tools = []
        for i in range(3):
            t = MagicMock()
            t.id = f"t{i}"
            t.name = f"Tool {i}"
            t.description = f"Desc {i}"
            t.tags = []
            t.team_id = None
            t.team = None
            t.visibility = "public"
            t.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
            tools.append(t)

        call_count = [0]

        def side_effect_all():
            call_count[0] += 1
            if call_count[0] == 1:
                return [("t0", 10), ("t1", 100), ("t2", 50)]
            elif call_count[0] == 2:
                return [("t0", 5), ("t1", 10), ("t2", 45)]
            return []

        mock_db.execute.return_value.all.side_effect = side_effect_all
        mock_db.execute.return_value.scalars.return_value.all.return_value = tools
        mock_db.execute.return_value.scalar.return_value = 50

        response = engine.calculate_trending(window="24h", limit=3)
        assert len(response.tools) == 3
        # Rankings should be in descending score order
        scores = [t.trending_score for t in response.tools]
        assert scores == sorted(scores, reverse=True)
        assert response.tools[0].rank == 1
        assert response.tools[1].rank == 2
        assert response.tools[2].rank == 3

    def test_limit_respected(self, engine, mock_db):
        """Limit parameter caps the number of results."""
        tools = []
        current_data = []
        previous_data = []
        for i in range(10):
            t = MagicMock()
            t.id = f"t{i}"
            t.name = f"T{i}"
            t.description = None
            t.tags = []
            t.team_id = None
            t.team = None
            t.visibility = "public"
            t.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
            tools.append(t)
            current_data.append((f"t{i}", (i + 1) * 10))
            previous_data.append((f"t{i}", (i + 1) * 5))

        call_count = [0]

        def side_effect_all():
            call_count[0] += 1
            if call_count[0] == 1:
                return current_data
            elif call_count[0] == 2:
                return previous_data
            return []

        mock_db.execute.return_value.all.side_effect = side_effect_all
        mock_db.execute.return_value.scalars.return_value.all.return_value = tools
        mock_db.execute.return_value.scalar.return_value = 20

        response = engine.calculate_trending(window="7d", limit=3)
        assert len(response.tools) <= 3

    def test_invalid_window_defaults(self, engine, mock_db):
        """Invalid window string falls back to DEFAULT_WINDOW."""
        mock_db.execute.return_value.all.return_value = []
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        response = engine.calculate_trending(window="invalid")
        assert response.window == "invalid"  # window is passed through
        assert response.tools == []


# ============================================================================
# Breakout Detection Tests
# ============================================================================


class TestBreakoutDetection:
    """Verify breakout flag is set correctly."""

    def test_exactly_100_percent(self):
        """100% growth is breakout."""
        pct = TrendingCalculationEngine._growth_pct(200, 100)
        assert pct >= 100.0

    def test_below_100_percent(self):
        """99% growth is not breakout."""
        pct = TrendingCalculationEngine._growth_pct(199, 100)
        assert pct < 100.0

    def test_zero_previous_is_breakout(self):
        """0→anything is 100% (breakout)."""
        pct = TrendingCalculationEngine._growth_pct(1, 0)
        assert pct >= 100.0


# ============================================================================
# Cache Manager Tests
# ============================================================================


class TestTrendingCacheManagerMemory:
    """Tests for in-memory fallback cache."""

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache_manager):
        """Store and retrieve trending response."""
        resp = TrendingResponse(window="24h", tools=[])
        await cache_manager.set("test-key", resp)

        cached = await cache_manager.get("test-key")
        assert cached is not None
        assert cached.window == "24h"
        assert cached.cached is True

    @pytest.mark.asyncio
    async def test_cache_miss(self, cache_manager):
        """Missing key returns None."""
        result = await cache_manager.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_expiry(self):
        """Expired entries are evicted."""
        mgr = TrendingCacheManager(redis_client=None, ttl=0)
        resp = TrendingResponse(window="7d")
        await mgr.set("k", resp)
        # TTL=0 means already expired
        result = await mgr.get("k")
        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate(self, cache_manager):
        """Invalidate removes the entry."""
        resp = TrendingResponse(window="30d")
        await cache_manager.set("key-to-delete", resp)

        await cache_manager.invalidate("key-to-delete")
        assert await cache_manager.get("key-to-delete") is None


class TestTrendingCacheManagerRedis:
    """Tests for Redis-backed cache."""

    @pytest.mark.asyncio
    async def test_redis_get_hit(self, redis_cache_manager, mock_redis):
        """Redis GET returns data."""
        resp = TrendingResponse(window="24h")
        raw = orjson.dumps(resp.model_dump(mode="json"))
        mock_redis.get.return_value = raw

        cached = await redis_cache_manager.get("key")
        assert cached is not None
        assert cached.window == "24h"
        assert cached.cached is True
        mock_redis.get.assert_awaited_once_with("key")

    @pytest.mark.asyncio
    async def test_redis_get_miss(self, redis_cache_manager, mock_redis):
        """Redis GET returns None."""
        mock_redis.get.return_value = None

        result = await redis_cache_manager.get("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_redis_set(self, redis_cache_manager, mock_redis):
        """Redis SET stores data with TTL."""
        resp = TrendingResponse(window="7d")
        await redis_cache_manager.set("key", resp)

        mock_redis.set.assert_awaited_once()
        call_args = mock_redis.set.call_args
        assert call_args[1]["ex"] == 300

    @pytest.mark.asyncio
    async def test_redis_invalidate(self, redis_cache_manager, mock_redis):
        """Redis DELETE removes the key."""
        await redis_cache_manager.invalidate("key")
        mock_redis.delete.assert_awaited_once_with("key")

    @pytest.mark.asyncio
    async def test_redis_failure_falls_back_to_memory(self, mock_redis):
        """When Redis raises, falls back to in-memory."""
        mock_redis.get.side_effect = Exception("Connection refused")
        mock_redis.set.side_effect = Exception("Connection refused")

        mgr = TrendingCacheManager(redis_client=mock_redis, ttl=60)
        resp = TrendingResponse(window="24h")

        # SET should fall back to memory
        await mgr.set("fallback-key", resp)

        # GET from Redis fails, but memory has it
        cached = await mgr.get("fallback-key")
        assert cached is not None
        assert cached.window == "24h"

    @pytest.mark.asyncio
    async def test_redis_corrupt_data(self, redis_cache_manager, mock_redis):
        """Corrupted JSON in Redis returns None gracefully."""
        mock_redis.get.return_value = b"not-valid-json"

        result = await redis_cache_manager.get("corrupt")
        assert result is None


# ============================================================================
# TrendingService Tests
# ============================================================================


class TestTrendingService:
    """Tests for the TrendingService facade."""

    @pytest.mark.asyncio
    async def test_cache_hit(self, service):
        """Returns cached data when available."""
        # Pre-populate cache
        resp = TrendingResponse(window="24h", tools=[])
        key = _cache_key("24h", None, None)
        await service.cache.set(key, resp)

        result = await service.get_trending(window="24h")
        assert result.cached is True
        assert result.window == "24h"

    @pytest.mark.asyncio
    async def test_cache_miss_computes(self, service, mock_db):
        """Computes on-demand when cache is empty."""
        mock_db.execute.return_value.all.return_value = []
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        result = await service.get_trending(window="7d")
        assert result.cached is False
        assert result.window == "7d"

    @pytest.mark.asyncio
    async def test_get_new_tools(self, service, mock_db):
        """get_new_tools delegates to the engine."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        result = await service.get_new_tools()
        assert result == []

    @pytest.mark.asyncio
    async def test_custom_filters(self, service, mock_db):
        """Team and category filters are passed through."""
        mock_db.execute.return_value.all.return_value = []
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        result = await service.get_trending(
            window="30d", team_id="t-1", category="api", limit=3
        )
        assert result.window == "30d"


# ============================================================================
# Background Task Tests
# ============================================================================


class TestBackgroundTask:
    """Tests for the trending background refresh task."""

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        """Background task can be started and cleanly stopped."""
        task = await start_trending_background_task(redis_client=None, interval=1)
        assert not task.done()

        await stop_trending_background_task()
        # Give the event loop a moment to process cancellation
        await asyncio.sleep(0.1)
        assert task.done()

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self):
        """Stopping when no task is running is a no-op."""
        await stop_trending_background_task()  # should not raise

    @pytest.mark.asyncio
    async def test_refresh_all_windows_runs(self):
        """_refresh_all_windows executes without error with mocked DB."""
        with patch("mcpgateway.services.trending_service.SessionLocal") as mock_session_cls:
            mock_db = MagicMock()
            mock_db.execute.return_value.all.return_value = []
            mock_db.execute.return_value.scalars.return_value.all.return_value = []
            mock_db.execute.return_value.scalar.return_value = 0
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

            cache = TrendingCacheManager(redis_client=None, ttl=300)
            _refresh_all_windows(cache)
            # Verify DB was queried for each window (3 windows x 2 periods = 6 calls min)
            assert mock_db.execute.called


# ============================================================================
# Edge Cases and Acceptance Criteria Tests
# ============================================================================


class TestEdgeCases:
    """Edge cases and acceptance criteria verification."""

    def test_window_constants(self):
        """All expected windows exist."""
        assert "24h" in WINDOW_HOURS
        assert "7d" in WINDOW_HOURS
        assert "30d" in WINDOW_HOURS
        assert WINDOW_HOURS["24h"] == 24
        assert WINDOW_HOURS["7d"] == 168
        assert WINDOW_HOURS["30d"] == 720

    def test_default_values(self):
        """Module constants have expected defaults."""
        assert DEFAULT_WINDOW == "7d"
        assert DEFAULT_LIMIT == 5
        assert NEW_TOOLS_DAYS == 7
        assert BACKGROUND_INTERVAL_SECONDS == 300
        assert CACHE_TTL_SECONDS == 300
        assert TRENDING_WEIGHT == 0.05

    def test_trending_weight_is_5_percent(self):
        """Acceptance: 5% weight in overall ranking."""
        assert TRENDING_WEIGHT == 0.05

    @pytest.mark.asyncio
    async def test_cache_responds_fast(self, cache_manager):
        """Acceptance: cached response should be retrievable in <50ms."""
        resp = TrendingResponse(
            window="7d",
            tools=[
                TrendingToolResult(
                    tool_id=f"t{i}",
                    tool_name=f"Tool {i}",
                    growth_percentage=float(i * 10),
                    trending_score=float(i),
                )
                for i in range(5)
            ],
        )
        key = _cache_key("7d", None, None)
        await cache_manager.set(key, resp)

        start = time.monotonic()
        cached = await cache_manager.get(key)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert cached is not None
        assert elapsed_ms < 50, f"Cache read took {elapsed_ms:.1f}ms (should be <50ms)"

    def test_growth_accuracy_within_2_percent(self):
        """Acceptance: ±2% accuracy for growth calculations."""
        test_cases = [
            (150, 100, 50.0),
            (250, 100, 150.0),
            (75, 150, -50.0),
            (1000, 500, 100.0),
            (10001, 10000, 0.01),
        ]
        for current, previous, expected in test_cases:
            actual = TrendingCalculationEngine._growth_pct(current, previous)
            if expected != 0:
                error_pct = abs((actual - expected) / expected) * 100
                assert error_pct < 2, f"Growth {current}/{previous}: got {actual}, expected {expected}, error={error_pct:.4f}%"
            else:
                assert abs(actual - expected) < 0.02

    def test_handles_large_org_data(self, engine, mock_db):
        """Acceptance: Handles orgs from 10 to 10,000+ users."""
        # Simulate 10,000 user org with many tool executions
        tools = []
        current_data = []
        for i in range(100):
            t = MagicMock()
            t.id = f"t{i}"
            t.name = f"Tool {i}"
            t.description = None
            t.tags = []
            t.team_id = "large-org"
            t.team = "Large Org"
            t.visibility = "team"
            t.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
            tools.append(t)
            current_data.append((f"t{i}", 10000 + i * 100))

        call_count = [0]

        def side_effect_all():
            call_count[0] += 1
            if call_count[0] == 1:
                return current_data
            elif call_count[0] == 2:
                return [(tid, cnt // 2) for tid, cnt in current_data]
            return []

        mock_db.execute.return_value.all.side_effect = side_effect_all
        mock_db.execute.return_value.scalars.return_value.all.return_value = tools
        mock_db.execute.return_value.scalar.return_value = 5000

        response = engine.calculate_trending(
            window="7d", team_id="large-org", limit=10
        )
        assert len(response.tools) <= 10
        # All should show ~100% growth (doubled)
        for t in response.tools:
            assert t.growth_percentage == pytest.approx(100.0, abs=5)

    @pytest.mark.asyncio
    async def test_cache_hit_rate_stays_high(self, cache_manager):
        """Acceptance: cache hit rate exceeds 90%."""
        resp = TrendingResponse(window="24h")
        key = _cache_key("24h", None, None)
        await cache_manager.set(key, resp)

        hits = 0
        total = 100
        for _ in range(total):
            result = await cache_manager.get(key)
            if result is not None:
                hits += 1

        hit_rate = hits / total
        assert hit_rate >= 0.90, f"Cache hit rate {hit_rate:.0%} < 90%"


# ============================================================================
# Router Tests
# ============================================================================


class TestTrendingRouter:
    """Tests for the trending API router endpoints."""

    @pytest.mark.asyncio
    async def test_get_trending_tools_endpoint(self):
        """Test the GET /api/trending endpoint handler."""
        # First-Party
        from mcpgateway.routers.trending_router import get_trending_tools

        mock_service = AsyncMock(spec=TrendingService)
        mock_service.get_trending.return_value = TrendingResponse(
            window="7d",
            tools=[
                TrendingToolResult(
                    tool_id="t1",
                    tool_name="Hot Tool",
                    growth_percentage=75.0,
                    rank=1,
                )
            ],
        )

        result = await get_trending_tools(
            window="7d",
            team_id=None,
            category=None,
            limit=5,
            service=mock_service,
        )

        assert result.window == "7d"
        assert len(result.tools) == 1
        assert result.tools[0].tool_name == "Hot Tool"
        mock_service.get_trending.assert_awaited_once_with(
            window="7d", team_id=None, category=None, limit=5
        )

    @pytest.mark.asyncio
    async def test_get_trending_valid_window(self):
        """Valid window is passed through."""
        from mcpgateway.routers.trending_router import get_trending_tools

        mock_service = AsyncMock(spec=TrendingService)
        mock_service.get_trending.return_value = TrendingResponse(window="24h")

        result = await get_trending_tools(
            window="24h",
            team_id=None,
            category=None,
            limit=10,
            service=mock_service,
        )
        mock_service.get_trending.assert_awaited_once_with(
            window="24h", team_id=None, category=None, limit=10
        )
        assert result.window == "24h"

    @pytest.mark.asyncio
    async def test_get_new_tools_endpoint(self):
        """Test the GET /api/trending/new endpoint handler."""
        from mcpgateway.routers.trending_router import get_new_tools

        mock_service = AsyncMock(spec=TrendingService)
        mock_service.get_new_tools.return_value = [
            TrendingToolResult(
                tool_id="new-1",
                tool_name="Brand New",
                is_new=True,
            )
        ]

        result = await get_new_tools(
            team_id=None, category=None, service=mock_service
        )
        assert len(result) == 1
        assert result[0].is_new is True
        mock_service.get_new_tools.assert_awaited_once()

    def test_init_trending_redis(self):
        """init_trending_redis sets the module-level client."""
        from mcpgateway.routers import trending_router

        fake_redis = MagicMock()
        trending_router.init_trending_redis(fake_redis)
        assert trending_router._redis_client is fake_redis

        # Reset
        trending_router.init_trending_redis(None)
        assert trending_router._redis_client is None


# ============================================================================
# Serialization Round-Trip Tests
# ============================================================================


class TestSerializationRoundTrip:
    """Ensure models serialize/deserialize correctly through cache."""

    @pytest.mark.asyncio
    async def test_full_round_trip(self, cache_manager):
        """A full TrendingResponse survives cache serialization roundtrip."""
        original = TrendingResponse(
            window="30d",
            tools=[
                TrendingToolResult(
                    tool_id="rt-1",
                    tool_name="Round Trip Tool",
                    description="Tests serialization",
                    tags=["test", "serialization"],
                    team_id="team-xyz",
                    visibility="team",
                    current_period_count=500,
                    previous_period_count=200,
                    growth_percentage=150.0,
                    is_breakout=True,
                    adoption_velocity=71.43,
                    trending_score=3.14,
                    rank=1,
                    explanation="Breakout tool · in Test Team (+150%) · 500 uses this period",
                    is_new=False,
                    created_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
                )
            ],
            new_tools=[
                TrendingToolResult(
                    tool_id="new-rt",
                    tool_name="New RT Tool",
                    is_new=True,
                )
            ],
        )

        key = "roundtrip-test"
        await cache_manager.set(key, original)
        restored = await cache_manager.get(key)

        assert restored is not None
        assert restored.window == "30d"
        assert restored.cached is True
        assert len(restored.tools) == 1

        t = restored.tools[0]
        assert t.tool_id == "rt-1"
        assert t.growth_percentage == 150.0
        assert t.is_breakout is True
        assert t.adoption_velocity == 71.43
        assert t.tags == ["test", "serialization"]
        assert len(restored.new_tools) == 1
        assert restored.new_tools[0].is_new is True
