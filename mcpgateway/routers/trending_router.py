# -*- coding: utf-8 -*-
"""Trending Tools API Router.

Exposes endpoints for querying trending tools, new tools, and analytics.
Supports org/team, window, limit, and category query parameters.
Responds in under 50 ms when cached.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import logging
from typing import List, Optional

# Third-Party
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_db
from mcpgateway.services.trending_service import (
    DEFAULT_LIMIT,
    DEFAULT_WINDOW,
    WINDOW_HOURS,
    TrendingResponse,
    TrendingService,
    TrendingToolResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/trending",
    tags=["Trending Analytics"],
)

# Module-level Redis client placeholder — set by ``init_trending_redis``
_redis_client = None


def init_trending_redis(redis_client) -> None:  # type: ignore[type-arg]
    """Inject async Redis client at startup.

    Called from ``main.py`` after Redis is initialised so that the router
    can pass it to the :class:`TrendingService`.

    Args:
        redis_client: An async Redis client instance (or None).
    """
    global _redis_client  # noqa: PLW0603
    _redis_client = redis_client


def _get_service(db: Session = Depends(get_db)) -> TrendingService:
    """FastAPI dependency that provides a ``TrendingService`` instance.

    Args:
        db: SQLAlchemy session (injected).

    Returns:
        TrendingService: Configured trending service.
    """
    return TrendingService(db=db, redis_client=_redis_client)


@router.get(
    "",
    response_model=TrendingResponse,
    summary="Get trending tools",
    description="Return the top trending tools ranked by usage growth. "
    "Supports filtering by team, category, and configurable time windows.",
)
async def get_trending_tools(
    window: str = Query(DEFAULT_WINDOW, description="Time window: 24h, 7d, or 30d"),
    team_id: Optional[str] = Query(None, description="Filter by team id"),
    category: Optional[str] = Query(None, description="Filter by tag/category"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=50, description="Max results"),
    service: TrendingService = Depends(_get_service),
) -> TrendingResponse:
    """Return the top trending tools ranked by usage growth.

    Args:
        window: Time window (24h, 7d, 30d).
        team_id: Optional team id filter.
        category: Optional tag/category filter.
        limit: Maximum number of results (1-50).
        service: Injected TrendingService.

    Returns:
        TrendingResponse: Ranked trending tools with analytics metadata.
    """
    if window not in WINDOW_HOURS:
        window = DEFAULT_WINDOW

    return await service.get_trending(
        window=window,
        team_id=team_id,
        category=category,
        limit=limit,
    )


@router.get(
    "/new",
    response_model=List[TrendingToolResult],
    summary="Get newly added tools",
    description="Return tools added within the last 7 days.",
)
async def get_new_tools(
    team_id: Optional[str] = Query(None, description="Filter by team id"),
    category: Optional[str] = Query(None, description="Filter by tag/category"),
    service: TrendingService = Depends(_get_service),
) -> List[TrendingToolResult]:
    """Return tools added within the last 7 days.

    Args:
        team_id: Optional team id filter.
        category: Optional tag/category filter.
        service: Injected TrendingService.

    Returns:
        List of recently added tools.
    """
    return await service.get_new_tools(team_id=team_id, category=category)
