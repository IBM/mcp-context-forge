# -*- coding: utf-8 -*-
"""Trending Tools Calculation Engine and Recommender.

Surfaces breakout tools and newly added tools based on usage growth patterns.
Supports configurable time windows (24h, 7d, 30d), percentage growth calculation,
breakout detection (100%+ growth spikes), and adoption velocity tracking.

Results are cached in Redis (with in-memory fallback) with a configurable TTL
and refreshed by a background task every 5 minutes.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# Third-Party
import orjson
from pydantic import BaseModel, Field
from sqlalchemy import case, distinct, func, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import SessionLocal, Tool, ToolMetric, ToolMetricsHourly

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------

TRENDING_WEIGHT = 0.05  # 5% weight in overall ranking


class TrendingToolResult(BaseModel):
    """A single trending tool with growth analytics."""

    tool_id: str = Field(..., description="Unique tool identifier")
    tool_name: str = Field(..., description="Display name of the tool")
    description: Optional[str] = Field(None, description="Tool description")
    tags: List[str] = Field(default_factory=list, description="Tool tags/categories")
    team_id: Optional[str] = Field(None, description="Owning team id")
    visibility: str = Field(default="public", description="Tool visibility")

    current_period_count: int = Field(0, description="Executions in current window")
    previous_period_count: int = Field(0, description="Executions in previous window")
    growth_percentage: float = Field(0.0, description="Percentage growth vs previous period")
    is_breakout: bool = Field(False, description="True when growth >= 100%")
    adoption_velocity: float = Field(0.0, description="Distinct new users per day (current window)")
    trending_score: float = Field(0.0, description="Composite trending score")
    rank: int = Field(0, description="Position in trending list")
    explanation: str = Field("", description="Human-readable trending explanation")
    is_new: bool = Field(False, description="True if tool was added within detection window")
    created_at: Optional[datetime] = Field(None, description="Tool creation timestamp")

    model_config = {"from_attributes": True}


class TrendingResponse(BaseModel):
    """Response envelope for the trending endpoint."""

    window: str = Field(..., description="Time window used (24h, 7d, 30d)")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cached: bool = Field(False, description="True if served from cache")
    tools: List[TrendingToolResult] = Field(default_factory=list)
    new_tools: List[TrendingToolResult] = Field(default_factory=list, description="Recently added tools")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WINDOW_HOURS: Dict[str, int] = {
    "24h": 24,
    "7d": 168,
    "30d": 720,
}

DEFAULT_WINDOW = "7d"
DEFAULT_LIMIT = 5
NEW_TOOLS_DAYS = 7  # Surface tools added within this many days
BACKGROUND_INTERVAL_SECONDS = 300  # 5 minutes
CACHE_TTL_SECONDS = 300  # 5 minutes


def _cache_key(window: str, team_id: Optional[str], category: Optional[str]) -> str:
    """Build a deterministic Redis/memory cache key.

    Args:
        window: Time window string (24h, 7d, 30d).
        team_id: Optional team filter.
        category: Optional tag/category filter.

    Returns:
        str: Cache key.
    """
    parts = ["trending", window]
    parts.append(f"team:{team_id}" if team_id else "team:__all__")
    parts.append(f"cat:{category}" if category else "cat:__all__")
    return ":".join(parts)


# ---------------------------------------------------------------------------
# Trending Calculation Engine
# ---------------------------------------------------------------------------


class TrendingCalculationEngine:
    """Compute trending scores from hourly rollup and raw metric tables.

    The engine compares executions in the *current* window against the
    *previous* window of the same length and derives:
    - percentage growth
    - breakout flag (>=100% growth)
    - adoption velocity  (distinct users / day proxy via distinct tool_id counts
      when user-level data is unavailable — falls back to execution density)
    - composite trending score

    All heavy queries target the ``tool_metrics_hourly`` table first; if no
    rollup data exists it falls back to raw ``tool_metrics``.
    """

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_trending(
        self,
        window: str = DEFAULT_WINDOW,
        team_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = DEFAULT_LIMIT,
    ) -> TrendingResponse:
        """Run full trending calculation and return ranked results.

        Args:
            window: One of ``24h``, ``7d``, ``30d``.
            team_id: Optional team id to filter tools.
            category: Optional tag/category to filter tools.
            limit: Maximum number of trending tools to return.

        Returns:
            TrendingResponse: Ranked trending tools plus new tools list.
        """
        hours = WINDOW_HOURS.get(window, WINDOW_HOURS[DEFAULT_WINDOW])
        now = datetime.now(timezone.utc)
        current_start = now - timedelta(hours=hours)
        previous_start = current_start - timedelta(hours=hours)

        # 1. Get execution counts per tool for both periods
        current_counts = self._period_counts(current_start, now, team_id, category)
        previous_counts = self._period_counts(previous_start, current_start, team_id, category)

        # 2. Load tool metadata for all tool_ids seen
        all_tool_ids = set(current_counts.keys()) | set(previous_counts.keys())
        if not all_tool_ids:
            return TrendingResponse(
                window=window,
                tools=[],
                new_tools=self._detect_new_tools(team_id, category),
            )

        tool_meta = self._load_tool_metadata(all_tool_ids, team_id, category)

        # 3. Score each tool
        scored: List[TrendingToolResult] = []
        for tool_id, meta in tool_meta.items():
            cur = current_counts.get(tool_id, 0)
            prev = previous_counts.get(tool_id, 0)
            growth = self._growth_pct(cur, prev)
            velocity = self._adoption_velocity(tool_id, current_start, now, hours)
            score = self._composite_score(cur, growth, velocity)
            is_new = meta.get("created_at") is not None and meta["created_at"] >= (now - timedelta(days=NEW_TOOLS_DAYS))

            explanation = self._build_explanation(growth, cur, is_new, meta.get("team_name"))

            scored.append(
                TrendingToolResult(
                    tool_id=tool_id,
                    tool_name=meta.get("name", ""),
                    description=meta.get("description"),
                    tags=meta.get("tags", []),
                    team_id=meta.get("team_id"),
                    visibility=meta.get("visibility", "public"),
                    current_period_count=cur,
                    previous_period_count=prev,
                    growth_percentage=round(growth, 2),
                    is_breakout=growth >= 100.0,
                    adoption_velocity=round(velocity, 2),
                    trending_score=round(score, 4),
                    explanation=explanation,
                    is_new=is_new,
                    created_at=meta.get("created_at"),
                )
            )

        # 4. Rank by trending_score descending
        scored.sort(key=lambda t: t.trending_score, reverse=True)
        for idx, item in enumerate(scored[:limit], start=1):
            item.rank = idx

        new_tools = self._detect_new_tools(team_id, category)

        return TrendingResponse(
            window=window,
            tools=scored[:limit],
            new_tools=new_tools,
        )

    # ------------------------------------------------------------------
    # Period counts (prefers hourly rollup, falls back to raw)
    # ------------------------------------------------------------------

    def _period_counts(
        self,
        start: datetime,
        end: datetime,
        team_id: Optional[str],
        category: Optional[str],
    ) -> Dict[str, int]:
        """Return {tool_id: execution_count} for tools in the given period.

        Tries ``tool_metrics_hourly`` first; falls back to raw ``tool_metrics``.

        Args:
            start: Period start (UTC).
            end: Period end (UTC).
            team_id: Optional team filter.
            category: Optional tag/category filter.

        Returns:
            Dict mapping tool_id to total execution count.
        """
        counts = self._period_counts_hourly(start, end, team_id, category)
        if counts:
            return counts
        return self._period_counts_raw(start, end, team_id, category)

    def _period_counts_hourly(
        self,
        start: datetime,
        end: datetime,
        team_id: Optional[str],
        category: Optional[str],
    ) -> Dict[str, int]:
        stmt = (
            select(
                ToolMetricsHourly.tool_id,
                func.sum(ToolMetricsHourly.total_count).label("total"),
            )
            .where(
                ToolMetricsHourly.hour_start >= start,
                ToolMetricsHourly.hour_start < end,
                ToolMetricsHourly.tool_id.isnot(None),
            )
            .group_by(ToolMetricsHourly.tool_id)
        )

        if team_id or category:
            stmt = stmt.join(Tool, Tool.id == ToolMetricsHourly.tool_id)
            if team_id:
                stmt = stmt.where(Tool.team_id == team_id)
            if category:
                stmt = stmt.where(Tool.tags.contains([category]))

        rows = self.db.execute(stmt).all()
        return {str(row[0]): int(row[1]) for row in rows}

    def _period_counts_raw(
        self,
        start: datetime,
        end: datetime,
        team_id: Optional[str],
        category: Optional[str],
    ) -> Dict[str, int]:
        stmt = (
            select(
                ToolMetric.tool_id,
                func.count(ToolMetric.id).label("total"),
            )
            .where(
                ToolMetric.timestamp >= start,
                ToolMetric.timestamp < end,
            )
            .group_by(ToolMetric.tool_id)
        )

        if team_id or category:
            stmt = stmt.join(Tool, Tool.id == ToolMetric.tool_id)
            if team_id:
                stmt = stmt.where(Tool.team_id == team_id)
            if category:
                stmt = stmt.where(Tool.tags.contains([category]))

        rows = self.db.execute(stmt).all()
        return {str(row[0]): int(row[1]) for row in rows}

    # ------------------------------------------------------------------
    # Adoption velocity
    # ------------------------------------------------------------------

    def _adoption_velocity(
        self,
        tool_id: str,
        start: datetime,
        end: datetime,
        window_hours: int,
    ) -> float:
        """Approximate adoption velocity as executions-per-day in the window.

        The raw ToolMetric table does not track distinct callers, so we use
        execution density as a proxy.  If hourly rollup data is available we
        use totals from there instead.

        Args:
            tool_id: Tool identifier.
            start: Window start.
            end: Window end.
            window_hours: Window size in hours.

        Returns:
            float: Executions per day in the window.
        """
        days = max(window_hours / 24.0, 1.0)

        # Try hourly first
        stmt = (
            select(func.sum(ToolMetricsHourly.total_count))
            .where(
                ToolMetricsHourly.tool_id == tool_id,
                ToolMetricsHourly.hour_start >= start,
                ToolMetricsHourly.hour_start < end,
            )
        )
        result = self.db.execute(stmt).scalar()
        if result is not None:
            return float(result) / days

        # Fallback to raw
        stmt_raw = (
            select(func.count(ToolMetric.id))
            .where(
                ToolMetric.tool_id == tool_id,
                ToolMetric.timestamp >= start,
                ToolMetric.timestamp < end,
            )
        )
        result_raw = self.db.execute(stmt_raw).scalar()
        return float(result_raw or 0) / days

    # ------------------------------------------------------------------
    # Tool metadata
    # ------------------------------------------------------------------

    def _load_tool_metadata(
        self,
        tool_ids: set,
        team_id: Optional[str],
        category: Optional[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Load metadata for a set of tool ids, respecting team/category filters.

        Args:
            tool_ids: Set of tool ids to look up.
            team_id: Optional team filter.
            category: Optional tag/category filter.

        Returns:
            Dict mapping tool_id to metadata dict.
        """
        stmt = select(Tool).where(Tool.id.in_(tool_ids), Tool.enabled.is_(True))

        if team_id:
            stmt = stmt.where(Tool.team_id == team_id)
        if category:
            stmt = stmt.where(Tool.tags.contains([category]))

        tools = self.db.execute(stmt).scalars().all()
        result: Dict[str, Dict[str, Any]] = {}
        for t in tools:
            result[t.id] = {
                "name": t.name,
                "description": t.description,
                "tags": t.tags or [],
                "team_id": t.team_id,
                "team_name": t.team if hasattr(t, "team") else None,
                "visibility": t.visibility,
                "created_at": t.created_at,
            }
        return result

    # ------------------------------------------------------------------
    # New tools detection
    # ------------------------------------------------------------------

    def _detect_new_tools(
        self,
        team_id: Optional[str],
        category: Optional[str],
    ) -> List[TrendingToolResult]:
        """Return tools added within the last ``NEW_TOOLS_DAYS`` days.

        Args:
            team_id: Optional team filter.
            category: Optional tag/category filter.

        Returns:
            List of TrendingToolResult flagged as new.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=NEW_TOOLS_DAYS)

        stmt = select(Tool).where(Tool.created_at >= cutoff, Tool.enabled.is_(True))

        if team_id:
            stmt = stmt.where(Tool.team_id == team_id)
        if category:
            stmt = stmt.where(Tool.tags.contains([category]))

        stmt = stmt.order_by(Tool.created_at.desc())

        tools = self.db.execute(stmt).scalars().all()

        results: List[TrendingToolResult] = []
        for t in tools:
            results.append(
                TrendingToolResult(
                    tool_id=t.id,
                    tool_name=t.name,
                    description=t.description,
                    tags=t.tags or [],
                    team_id=t.team_id,
                    visibility=t.visibility,
                    is_new=True,
                    created_at=t.created_at,
                    explanation="New tool added recently",
                )
            )
        return results

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _growth_pct(current: int, previous: int) -> float:
        """Calculate percentage growth between two period counts.

        Args:
            current: Current period execution count.
            previous: Previous period execution count.

        Returns:
            float: Percentage growth. Returns 100.0 when previous is 0
                   but current > 0. Returns 0.0 when both are 0.
        """
        if previous == 0:
            return 100.0 if current > 0 else 0.0
        return ((current - previous) / previous) * 100.0

    @staticmethod
    def _composite_score(current_count: int, growth_pct: float, velocity: float) -> float:
        """Compute a weighted composite trending score.

        Components:
        - 40% normalised current usage (log scale to dampen outliers)
        - 40% growth percentage (capped at 500%)
        - 20% adoption velocity (log scale)

        Args:
            current_count: Executions in current window.
            growth_pct: Percentage growth vs previous window.
            velocity: Adoption velocity (executions/day).

        Returns:
            float: Composite score >= 0.
        """
        import math

        usage_score = math.log1p(current_count)  # log(1 + n) avoids log(0)
        growth_score = min(growth_pct, 500.0) / 100.0  # cap at 5x
        velocity_score = math.log1p(velocity)

        return 0.4 * usage_score + 0.4 * growth_score + 0.2 * velocity_score

    @staticmethod
    def _build_explanation(
        growth: float,
        current_count: int,
        is_new: bool,
        team_name: Optional[str],
    ) -> str:
        """Build a human-readable trending explanation string.

        Args:
            growth: Percentage growth.
            current_count: Current period count.
            is_new: Whether the tool is newly added.
            team_name: Optional team name for scoped explanation.

        Returns:
            str: Explanation such as ``Trending in your org (+45%)``.
        """
        parts: List[str] = []
        if is_new:
            parts.append("Newly added")
        if growth >= 100:
            parts.append("Breakout tool")
        elif growth > 0:
            parts.append("Trending")
        else:
            parts.append("Steady usage")

        scope = f"in {team_name}" if team_name else "in your org"
        sign = "+" if growth >= 0 else ""
        parts.append(f"{scope} ({sign}{growth:.0f}%)")

        if current_count > 0:
            parts.append(f"{current_count} uses this period")

        return " · ".join(parts)


# ---------------------------------------------------------------------------
# Cache layer (Redis with in-memory fallback)
# ---------------------------------------------------------------------------


class TrendingCacheManager:
    """Manage trending result caching via Redis or an in-memory dict.

    All public methods are async-safe.  The class gracefully degrades to
    an in-memory dictionary when Redis is unavailable.
    """

    def __init__(self, redis_client: Optional[Any] = None, ttl: int = CACHE_TTL_SECONDS):
        self._redis = redis_client
        self._ttl = ttl
        self._memory: Dict[str, bytes] = {}
        self._memory_expiry: Dict[str, float] = {}

    async def get(self, key: str) -> Optional[TrendingResponse]:
        """Fetch cached trending response.

        Args:
            key: Cache key.

        Returns:
            TrendingResponse or None.
        """
        raw = await self._raw_get(key)
        if raw is None:
            return None
        try:
            data = orjson.loads(raw)
            resp = TrendingResponse(**data)
            resp.cached = True
            return resp
        except Exception:
            logger.warning("Failed to deserialise cached trending data for key=%s", key)
            return None

    async def set(self, key: str, response: TrendingResponse) -> None:
        """Store trending response in cache.

        Args:
            key: Cache key.
            response: TrendingResponse to cache.
        """
        raw = orjson.dumps(response.model_dump(mode="json"))
        await self._raw_set(key, raw)

    async def invalidate(self, key: str) -> None:
        """Remove a specific cache entry.

        Args:
            key: Cache key to remove.
        """
        if self._redis:
            try:
                await self._redis.delete(key)
            except Exception:
                logger.debug("Redis delete failed for key=%s", key)
        self._memory.pop(key, None)
        self._memory_expiry.pop(key, None)

    # -- internal helpers ------------------------------------------------

    async def _raw_get(self, key: str) -> Optional[bytes]:
        if self._redis:
            try:
                return await self._redis.get(key)
            except Exception:
                logger.debug("Redis GET failed, falling back to memory")

        raw = self._memory.get(key)
        if raw is not None:
            exp = self._memory_expiry.get(key, 0)
            if time.monotonic() > exp:
                self._memory.pop(key, None)
                self._memory_expiry.pop(key, None)
                return None
        return raw

    async def _raw_set(self, key: str, value: bytes) -> None:
        if self._redis:
            try:
                await self._redis.set(key, value, ex=self._ttl)
                return
            except Exception:
                logger.debug("Redis SET failed, falling back to memory")

        self._memory[key] = value
        self._memory_expiry[key] = time.monotonic() + self._ttl


# ---------------------------------------------------------------------------
# Background refresh task
# ---------------------------------------------------------------------------

_background_task: Optional[asyncio.Task] = None


async def start_trending_background_task(
    redis_client: Optional[Any] = None,
    interval: int = BACKGROUND_INTERVAL_SECONDS,
) -> asyncio.Task:
    """Launch the periodic trending recalculation loop.

    The task recalculates trending data for the three standard windows and
    stores results in the cache.  On startup it performs an immediate warm-up
    pass before entering the periodic loop.

    Args:
        redis_client: Optional async Redis client.
        interval: Seconds between recalculations.

    Returns:
        asyncio.Task: The running background task handle.
    """
    global _background_task  # noqa: PLW0603

    cache = TrendingCacheManager(redis_client=redis_client, ttl=CACHE_TTL_SECONDS)

    async def _loop() -> None:
        logger.info("Trending background task started (interval=%ds)", interval)

        while True:
            try:
                _refresh_all_windows(cache)
                logger.debug("Trending cache refreshed")
            except Exception:
                logger.exception("Trending background refresh failed — will retry next cycle")
            await asyncio.sleep(interval)

    _background_task = asyncio.create_task(_loop())
    return _background_task


def _refresh_all_windows(cache: TrendingCacheManager) -> None:
    """Synchronously refresh cache for all standard windows.

    Opens a new DB session, computes trending for each window, and
    stores results in the cache synchronously (the asyncio event-loop
    integration is handled by the caller).

    Args:
        cache: TrendingCacheManager instance.
    """
    with SessionLocal() as db:
        engine = TrendingCalculationEngine(db)

        for window in WINDOW_HOURS:
            key = _cache_key(window, None, None)
            response = engine.calculate_trending(window=window, limit=DEFAULT_LIMIT)

            # Synchronous cache write (safe because _raw_set falls back to memory dict)
            loop = asyncio.get_event_loop()
            loop.create_task(cache.set(key, response))


async def stop_trending_background_task() -> None:
    """Cancel the running background task if active."""
    global _background_task  # noqa: PLW0603
    if _background_task is not None:
        _background_task.cancel()
        try:
            await _background_task
        except asyncio.CancelledError:
            pass
        _background_task = None
        logger.info("Trending background task stopped")


# ---------------------------------------------------------------------------
# High-level service consumed by the router
# ---------------------------------------------------------------------------


class TrendingService:
    """Facade consumed by the trending router.

    Reads from cache when available; falls back to on-demand calculation.

    Args:
        db: SQLAlchemy session.
        redis_client: Optional async Redis client (for cache).
    """

    def __init__(self, db: Session, redis_client: Optional[Any] = None):
        self.db = db
        self.cache = TrendingCacheManager(redis_client=redis_client, ttl=CACHE_TTL_SECONDS)
        self.engine = TrendingCalculationEngine(db)

    async def get_trending(
        self,
        window: str = DEFAULT_WINDOW,
        team_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = DEFAULT_LIMIT,
    ) -> TrendingResponse:
        """Return trending tools, preferring cached data.

        Args:
            window: Time window (24h, 7d, 30d).
            team_id: Optional team filter.
            category: Optional tag/category filter.
            limit: Max tools to return.

        Returns:
            TrendingResponse with ranked trending tools.
        """
        key = _cache_key(window, team_id, category)

        # Try cache first
        cached = await self.cache.get(key)
        if cached is not None:
            return cached

        # On-demand calculation
        response = self.engine.calculate_trending(
            window=window,
            team_id=team_id,
            category=category,
            limit=limit,
        )

        # Store in cache asynchronously
        await self.cache.set(key, response)

        return response

    async def get_new_tools(
        self,
        team_id: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[TrendingToolResult]:
        """Return tools added in the last ``NEW_TOOLS_DAYS`` days.

        Args:
            team_id: Optional team filter.
            category: Optional tag/category filter.

        Returns:
            List of TrendingToolResult flagged as new.
        """
        return self.engine._detect_new_tools(team_id, category)
