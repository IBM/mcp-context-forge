# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/analytics_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Analytics and Collaborative Filtering Router.
This module provides FastAPI routes for usage analytics, user preferences,
and collaborative filtering recommendations.

Examples:
    >>> from fastapi import FastAPI
    >>> from mcpgateway.routers.analytics_router import router
    >>> app = FastAPI()
    >>> app.include_router(router, prefix="/api/v1", tags=["Analytics"])
"""

# Standard
from datetime import datetime
from typing import Any, Dict, List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.services.collaborative_recommender import collaborative_recommender
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.usage_analytics_service import usage_analytics_service
from mcpgateway.services.user_similarity_service import user_similarity_service

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Create router
router = APIRouter(prefix="/api/v1", tags=["Analytics"])


# ===================================
# Pydantic Models
# ===================================


class ToolUsageEventRequest(BaseModel):
    """Request model for recording a tool usage event."""

    tool_id: str = Field(..., description="Tool identifier")
    execution_duration_ms: Optional[int] = Field(None, description="Execution time in milliseconds")
    success: bool = Field(True, description="Whether execution succeeded")
    error_message: Optional[str] = Field(None, description="Error message if execution failed")
    session_id: Optional[str] = Field(None, description="Session identifier")
    interaction_type: str = Field("invoke", description="Type of interaction: invoke, view, or dismiss")
    context_hash: Optional[str] = Field(None, description="Hashed context for privacy-preserving analytics")


class UserPreferenceRequest(BaseModel):
    """Request model for updating user analytics preferences."""

    analytics_opted_in: bool = Field(..., description="Whether user is opted into analytics")
    data_retention_days: Optional[int] = Field(None, ge=30, le=730, description="Custom retention period in days")


class UserPreferenceResponse(BaseModel):
    """Response model for user preferences."""

    user_email: str
    analytics_opted_in: bool
    data_retention_days: int
    last_updated: datetime


class ToolRecommendation(BaseModel):
    """Single tool recommendation."""

    tool_id: str
    score: float
    reasoning: Optional[Dict[str, Any]] = None


class RecommendationsResponse(BaseModel):
    """Response model for tool recommendations."""

    user_email: str
    recommendations: List[ToolRecommendation]
    algorithm: str
    total_count: int


class SimilarUser(BaseModel):
    """Similar user information."""

    user_email: str
    similarity_score: float


class SimilarUsersResponse(BaseModel):
    """Response model for similar users."""

    user_email: str
    similar_users: List[SimilarUser]
    algorithm: str
    total_count: int


class RecommendationStatsResponse(BaseModel):
    """Response model for recommendation system stats."""

    user_email: str
    user_tool_count: int
    similar_users_count: int
    available_recommendations: int
    cf_enabled: bool
    cf_boost_weight: float
    similarity_algorithm: str


class TrendingTool(BaseModel):
    """Trending tool information."""

    tool_id: str
    usage_count: int
    trend_score: float


class TrendingToolsResponse(BaseModel):
    """Response model for trending tools."""

    trending_tools: List[TrendingTool]
    time_window_days: int
    total_count: int


# ===================================
# Endpoints
# ===================================


@router.post("/analytics/tool-usage", status_code=status.HTTP_201_CREATED)
async def record_tool_usage(
    event: ToolUsageEventRequest,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> Dict[str, str]:
    """Record a tool usage event for analytics.

    Args:
        event: Tool usage event data
        current_user_ctx: Current user context with permissions

    Returns:
        Success message

    Raises:
        HTTPException: If analytics is disabled or recording fails
    """
    if not settings.analytics_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Analytics is disabled")

    user_email = current_user_ctx.get("email")
    user_role = current_user_ctx.get("role")
    user_teams = current_user_ctx.get("teams", [])
    user_team_id = user_teams[0] if user_teams else None

    try:
        await usage_analytics_service.record_usage_event(
            user_email=user_email,
            tool_id=event.tool_id,
            execution_duration_ms=event.execution_duration_ms,
            success=event.success,
            error_message=event.error_message,
            session_id=event.session_id,
            user_role=user_role,
            user_team_id=user_team_id,
            interaction_type=event.interaction_type,
            context_hash=event.context_hash,
        )
        return {"status": "success", "message": "Tool usage event recorded"}
    except Exception as e:
        logger.error(f"Failed to record tool usage: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to record usage event")


@router.get("/users/me/preferences", response_model=UserPreferenceResponse)
async def get_user_preferences(
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> UserPreferenceResponse:
    """Get current user's analytics preferences.

    Args:
        current_user_ctx: Current user context with permissions

    Returns:
        User preferences

    Raises:
        HTTPException: If retrieval fails
    """
    user_email = current_user_ctx.get("email")

    try:
        # Export data includes preferences
        data = await usage_analytics_service.export_user_data(user_email)
        prefs = data["preferences"]

        return UserPreferenceResponse(
            user_email=user_email,
            analytics_opted_in=prefs["analytics_opted_in"],
            data_retention_days=prefs["data_retention_days"],
            last_updated=prefs["last_updated"] if prefs["last_updated"] else datetime.utcnow(),
        )
    except Exception as e:
        logger.error(f"Failed to get user preferences for {user_email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve preferences")


@router.put("/users/me/preferences", response_model=UserPreferenceResponse)
async def update_user_preferences(
    preferences: UserPreferenceRequest,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> UserPreferenceResponse:
    """Update current user's analytics preferences.

    Args:
        preferences: New preference values
        current_user_ctx: Current user context with permissions

    Returns:
        Updated preferences

    Raises:
        HTTPException: If update fails
    """
    if not settings.analytics_allow_opt_out:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Opt-out is disabled by administrator")

    user_email = current_user_ctx.get("email")

    try:
        await usage_analytics_service.set_user_preference(
            user_email=user_email,
            analytics_opted_in=preferences.analytics_opted_in,
            data_retention_days=preferences.data_retention_days,
        )

        # Return updated preferences
        return await get_user_preferences(current_user_ctx)
    except Exception as e:
        logger.error(f"Failed to update user preferences for {user_email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update preferences")


@router.get("/users/me/usage-data")
async def export_user_data(
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Export all analytics data for the current user (GDPR/privacy compliance).

    Args:
        current_user_ctx: Current user context with permissions

    Returns:
        All user analytics data

    Raises:
        HTTPException: If export fails or is disabled
    """
    if not settings.analytics_export_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Data export is disabled by administrator")

    user_email = current_user_ctx.get("email")

    try:
        data = await usage_analytics_service.export_user_data(user_email)
        return data
    except Exception as e:
        logger.error(f"Failed to export user data for {user_email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to export data")


@router.delete("/users/me/usage-data", status_code=status.HTTP_200_OK)
async def delete_user_data(
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Delete all analytics data for the current user (GDPR right to erasure).

    Args:
        current_user_ctx: Current user context with permissions

    Returns:
        Deletion confirmation with count

    Raises:
        HTTPException: If deletion fails or is disabled
    """
    if not settings.analytics_delete_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Data deletion is disabled by administrator")

    user_email = current_user_ctx.get("email")

    try:
        deleted_count = await usage_analytics_service.delete_user_data(user_email)
        return {
            "status": "success",
            "message": f"Deleted {deleted_count} usage events and preferences for {user_email}",
            "deleted_count": deleted_count,
        }
    except Exception as e:
        logger.error(f"Failed to delete user data for {user_email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete data")


@router.get("/users/{target_email}/usage-data")
async def export_user_data_admin(
    target_email: str = Path(..., description="Email address of the user whose data to export"),
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Export analytics data for any user by email (admin only, GDPR compliance).

    Satisfies the GDPR right-of-access requirement for administrators acting on
    behalf of a data-subject. The calling account must have the ``platform_admin``
    role; all other roles receive HTTP 403.

    Args:
        target_email: Email of the user whose data to retrieve
        current_user_ctx: Current admin user context with permissions

    Returns:
        All analytics data for the target user

    Raises:
        HTTPException 403: If the caller is not a platform_admin
        HTTPException 403: If data export is disabled by configuration
        HTTPException 500: If the export fails
    """
    if not settings.analytics_export_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Data export is disabled by administrator")

    caller_role = current_user_ctx.get("role", "")
    if caller_role != "platform_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only platform_admin accounts may export another user's analytics data",
        )

    try:
        data = await usage_analytics_service.export_user_data(target_email)
        return data
    except Exception as e:
        logger.error(f"Admin failed to export data for {target_email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to export data")


@router.get("/recommendations/tools", response_model=RecommendationsResponse)
async def get_tool_recommendations(
    limit: int = Query(10, ge=1, le=50, description="Maximum recommendations to return"),
    include_reasoning: bool = Query(False, description="Include explanation of why tools were recommended"),
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> RecommendationsResponse:
    """Get collaborative filtering tool recommendations for the current user.

    Args:
        limit: Maximum number of recommendations
        include_reasoning: Include reasoning for each recommendation
        current_user_ctx: Current user context with permissions

    Returns:
        Tool recommendations

    Raises:
        HTTPException: If recommendations fail or are disabled
    """
    if not settings.collaborative_filtering_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Collaborative filtering is disabled")

    user_email = current_user_ctx.get("email")
    user_teams = current_user_ctx.get("teams", [])
    user_team_id = user_teams[0] if user_teams else None
    user_role = current_user_ctx.get("role")

    try:
        recommendations = await collaborative_recommender.recommend_tools(
            user_email=user_email,
            limit=limit,
            include_reasoning=include_reasoning,
            user_team_id=user_team_id,
            user_role=user_role,
        )

        return RecommendationsResponse(
            user_email=user_email,
            recommendations=[ToolRecommendation(**rec) for rec in recommendations],
            algorithm=settings.cf_similarity_algorithm,
            total_count=len(recommendations),
        )
    except Exception as e:
        logger.error(f"Failed to get recommendations for {user_email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate recommendations")


@router.get("/recommendations/stats", response_model=RecommendationStatsResponse)
async def get_recommendation_stats(
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> RecommendationStatsResponse:
    """Get recommendation system statistics for the current user.

    Args:
        current_user_ctx: Current user context with permissions

    Returns:
        Recommendation system stats

    Raises:
        HTTPException: If stats retrieval fails
    """
    user_email = current_user_ctx.get("email")

    try:
        stats = await collaborative_recommender.get_recommendation_stats(user_email)
        return RecommendationStatsResponse(**stats)
    except Exception as e:
        logger.error(f"Failed to get recommendation stats for {user_email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve stats")


@router.get("/users/similar", response_model=SimilarUsersResponse)
async def get_similar_users(
    limit: int = Query(10, ge=1, le=50, description="Maximum similar users to return"),
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> SimilarUsersResponse:
    """Get users most similar to the current user based on tool usage patterns.

    Args:
        limit: Maximum number of similar users
        current_user_ctx: Current user context with permissions

    Returns:
        List of similar users with similarity scores

    Raises:
        HTTPException: If similarity computation fails
    """
    if not settings.collaborative_filtering_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Collaborative filtering is disabled")

    user_email = current_user_ctx.get("email")

    try:
        similar_users = await user_similarity_service.get_similar_users(
            user_email=user_email,
            limit=limit,
            algorithm=settings.cf_similarity_algorithm,
        )

        return SimilarUsersResponse(
            user_email=user_email,
            similar_users=[SimilarUser(user_email=email, similarity_score=score) for email, score in similar_users],
            algorithm=settings.cf_similarity_algorithm,
            total_count=len(similar_users),
        )
    except Exception as e:
        logger.error(f"Failed to get similar users for {user_email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to compute similar users")


@router.get("/tools/trending", response_model=TrendingToolsResponse)
async def get_trending_tools(
    limit: int = Query(10, ge=1, le=50, description="Maximum trending tools to return"),
    time_window_days: int = Query(7, ge=1, le=90, description="Time window for trend analysis in days"),
    team_filter: bool = Query(False, description="Filter by user's team"),
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> TrendingToolsResponse:
    """Get trending tools based on recent usage spikes.

    Args:
        limit: Maximum number of trending tools
        time_window_days: Time window for trend analysis
        team_filter: Whether to filter by user's team
        current_user_ctx: Current user context with permissions

    Returns:
        List of trending tools

    Raises:
        HTTPException: If trending computation fails
    """
    user_teams = current_user_ctx.get("teams", [])
    user_team_id = user_teams[0] if team_filter and user_teams else None

    try:
        trending = await collaborative_recommender.get_trending_tools(
            limit=limit,
            time_window_days=time_window_days,
            user_team_id=user_team_id,
        )

        return TrendingToolsResponse(
            trending_tools=[TrendingTool(**tool) for tool in trending],
            time_window_days=time_window_days,
            total_count=len(trending),
        )
    except Exception as e:
        logger.error(f"Failed to get trending tools: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get trending tools")
