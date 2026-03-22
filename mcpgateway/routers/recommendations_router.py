# -*- coding: utf-8 -*-
"""Personalized Recommendations API Router.

Exposes endpoints for:
- Getting personalized tool recommendations
- Submitting user feedback
- Managing A/B experiments
- Querying recommendation explanations
- "Why not recommended?" queries

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import logging
from typing import Any, Dict, List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_db
from mcpgateway.services.ab_testing_service import (
    ABTestingService,
    ExperimentConfig,
    ExperimentCreateRequest,
    ExperimentReport,
    ExperimentStatus,
)
from mcpgateway.services.feedback_service import (
    FeedbackResponse,
    FeedbackService,
    FeedbackStats,
    FeedbackSubmission,
    UserPreferences,
)
from mcpgateway.services.recommendation_engine_service import (
    RecommendationEngine,
    RecommendationRequest,
    RecommendationResponse,
    StrategyResult,
    WhyNotResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/recommendations",
    tags=["Personalized Recommendations"],
)

# ---------------------------------------------------------------------------
# Module-level service singletons (initialized at startup)
# ---------------------------------------------------------------------------

_engine = RecommendationEngine()
_feedback_service = FeedbackService()
_ab_service = ABTestingService()


def init_recommendations_redis(redis_client: Any) -> None:
    """Inject async Redis client at startup.

    Args:
        redis_client: An async Redis client instance (or None).
    """
    global _feedback_service  # noqa: PLW0603
    _feedback_service = FeedbackService(redis_client=redis_client)


def _get_engine() -> RecommendationEngine:
    """Dependency for recommendation engine."""
    return _engine


def _get_feedback() -> FeedbackService:
    """Dependency for feedback service."""
    return _feedback_service


def _get_ab_service() -> ABTestingService:
    """Dependency for A/B testing service."""
    return _ab_service


# ---------------------------------------------------------------------------
# Recommendation endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=RecommendationResponse,
    summary="Get personalized recommendations",
    description="Combine multiple strategies to produce ranked tool recommendations "
    "with personalization, boost factors, and full provenance.",
)
async def get_recommendations(
    request: RecommendationRequest,
    engine: RecommendationEngine = Depends(_get_engine),
    feedback: FeedbackService = Depends(_get_feedback),
    ab_service: ABTestingService = Depends(_get_ab_service),
    db: Session = Depends(get_db),
) -> RecommendationResponse:
    """Get personalized tool recommendations.

    Aggregates strategies, applies boosts and personalization,
    and returns ranked results with explanations.

    Args:
        request: Recommendation request with user context.
        engine: Injected recommendation engine.
        feedback: Injected feedback service.
        ab_service: Injected A/B testing service.
        db: SQLAlchemy session.

    Returns:
        RecommendationResponse with ranked tools.
    """
    import time

    start = time.monotonic()

    # Build strategy results from context
    strategy_results = _build_strategy_results(request, db)

    # Get personalization
    personalization = feedback.get_personalization(request.user_id)
    hidden_tools = feedback.get_hidden_tools(request.user_id)

    # Check A/B experiments
    weight_overrides = None
    experiment_variant = None
    for exp in ab_service.list_experiments(status=ExperimentStatus.RUNNING):
        variant_weights = ab_service.get_variant_weights(exp.experiment_id, request.user_id)
        if variant_weights:
            weight_overrides = variant_weights
            experiment_variant = ab_service.assign_variant(exp.experiment_id, request.user_id)
            ab_service.record_impression(exp.experiment_id, request.user_id)
            break

    # Use request-level weight overrides if provided
    if request.strategy_weights:
        weight_overrides = request.strategy_weights

    # Rank
    ranked = engine.rank(
        strategy_results=strategy_results,
        user_context=request.context,
        personalization=personalization,
        hidden_tools=hidden_tools,
        favorites=request.context.get("favorites", set()),
        recently_used=request.context.get("recently_used", set()),
        team_favorites=request.context.get("team_favorites", set()),
        weight_overrides=weight_overrides,
        limit=request.limit,
    )

    elapsed_ms = (time.monotonic() - start) * 1000

    total_candidates = sum(len(r) for r in strategy_results.values())

    return RecommendationResponse(
        recommendations=ranked,
        total_candidates=total_candidates,
        ranking_time_ms=round(elapsed_ms, 2),
        strategies_used=list(strategy_results.keys()),
        experiment_variant=experiment_variant,
    )


@router.get(
    "/explain/{tool_id}",
    response_model=WhyNotResponse,
    summary="Why not recommended?",
    description="Explain why a specific tool was not recommended or ranked lower.",
)
async def explain_why_not(
    tool_id: str,
    user_id: str = Query(..., description="User identifier"),
    query: Optional[str] = Query(None, description="Original search query"),
    engine: RecommendationEngine = Depends(_get_engine),
    feedback: FeedbackService = Depends(_get_feedback),
    db: Session = Depends(get_db),
) -> WhyNotResponse:
    """Explain why a tool was not in recommendations.

    Args:
        tool_id: Tool to investigate.
        user_id: User who requested.
        query: Original query for context.
        engine: Injected engine.
        feedback: Injected feedback service.
        db: SQLAlchemy session.

    Returns:
        WhyNotResponse with explanation.
    """
    # First-Party
    from mcpgateway.db import Tool

    tool = db.query(Tool).filter(Tool.id == tool_id).first()
    tool_name = tool.name if tool else tool_id

    request = RecommendationRequest(user_id=user_id, query=query, team_id=None, limit=10, strategy_weights=None, include_explanation=True)
    strategy_results = _build_strategy_results(request, db)
    hidden = feedback.get_hidden_tools(user_id)
    personalization = feedback.get_personalization(user_id)

    return engine.explain_why_not(
        tool_id=tool_id,
        tool_name=tool_name,
        strategy_results=strategy_results,
        hidden_tools=hidden,
        personalization=personalization,
    )


# ---------------------------------------------------------------------------
# Feedback endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    summary="Submit recommendation feedback",
    description="Record user interaction with a recommendation (CLICKED, USED, DISMISSED, HIDDEN). "
    "Processes in under 20ms.",
)
async def submit_feedback(
    submission: FeedbackSubmission,
    feedback: FeedbackService = Depends(_get_feedback),
) -> FeedbackResponse:
    """Submit feedback for a recommendation.

    Args:
        submission: Feedback submission.
        feedback: Injected feedback service.

    Returns:
        FeedbackResponse with processing metadata.
    """
    return await feedback.process_feedback(submission)


@router.get(
    "/feedback/stats/{user_id}",
    response_model=FeedbackStats,
    summary="Get user feedback statistics",
)
async def get_feedback_stats(
    user_id: str,
    feedback: FeedbackService = Depends(_get_feedback),
) -> FeedbackStats:
    """Get feedback statistics for a user.

    Args:
        user_id: User identifier.
        feedback: Injected feedback service.

    Returns:
        FeedbackStats.
    """
    return feedback.get_stats(user_id)


@router.get(
    "/preferences/{user_id}",
    response_model=UserPreferences,
    summary="Get user preference model",
)
async def get_user_preferences(
    user_id: str,
    feedback: FeedbackService = Depends(_get_feedback),
) -> UserPreferences:
    """Get the learned preference model for a user.

    Args:
        user_id: User identifier.
        feedback: Injected feedback service.

    Returns:
        UserPreferences model.
    """
    return feedback.get_preferences(user_id)


# ---------------------------------------------------------------------------
# A/B Testing endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/experiments",
    response_model=ExperimentConfig,
    summary="Create A/B experiment",
)
async def create_experiment(
    request: ExperimentCreateRequest,
    ab_service: ABTestingService = Depends(_get_ab_service),
) -> ExperimentConfig:
    """Create a new A/B testing experiment.

    Args:
        request: Experiment configuration.
        ab_service: Injected A/B service.

    Returns:
        Created ExperimentConfig.
    """
    try:
        return ab_service.create_experiment(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/experiments/{experiment_id}/start",
    response_model=ExperimentConfig,
    summary="Start experiment",
)
async def start_experiment(
    experiment_id: str,
    ab_service: ABTestingService = Depends(_get_ab_service),
) -> ExperimentConfig:
    """Start a draft or paused experiment.

    Args:
        experiment_id: Experiment to start.
        ab_service: Injected A/B service.

    Returns:
        Updated ExperimentConfig.
    """
    try:
        return ab_service.start_experiment(experiment_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Experiment not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/experiments/{experiment_id}/pause",
    response_model=ExperimentConfig,
    summary="Pause experiment",
)
async def pause_experiment(
    experiment_id: str,
    ab_service: ABTestingService = Depends(_get_ab_service),
) -> ExperimentConfig:
    """Pause a running experiment.

    Args:
        experiment_id: Experiment to pause.
        ab_service: Injected A/B service.

    Returns:
        Updated ExperimentConfig.
    """
    try:
        return ab_service.pause_experiment(experiment_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Experiment not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/experiments/{experiment_id}/complete",
    response_model=ExperimentConfig,
    summary="Complete experiment",
)
async def complete_experiment(
    experiment_id: str,
    ab_service: ABTestingService = Depends(_get_ab_service),
) -> ExperimentConfig:
    """Mark an experiment as completed.

    Args:
        experiment_id: Experiment to complete.
        ab_service: Injected A/B service.

    Returns:
        Updated ExperimentConfig.
    """
    try:
        return ab_service.complete_experiment(experiment_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Experiment not found")


@router.delete(
    "/experiments/{experiment_id}",
    summary="Delete experiment",
)
async def delete_experiment(
    experiment_id: str,
    ab_service: ABTestingService = Depends(_get_ab_service),
) -> Dict[str, str]:
    """Delete an experiment.

    Args:
        experiment_id: Experiment to delete.
        ab_service: Injected A/B service.

    Returns:
        Confirmation message.
    """
    try:
        ab_service.delete_experiment(experiment_id)
        return {"status": "deleted", "experiment_id": experiment_id}
    except KeyError:
        raise HTTPException(status_code=404, detail="Experiment not found")


@router.get(
    "/experiments",
    response_model=List[ExperimentConfig],
    summary="List experiments",
)
async def list_experiments(
    status: Optional[ExperimentStatus] = Query(None, description="Filter by status"),
    ab_service: ABTestingService = Depends(_get_ab_service),
) -> List[ExperimentConfig]:
    """List all experiments.

    Args:
        status: Optional status filter.
        ab_service: Injected A/B service.

    Returns:
        List of experiments.
    """
    return ab_service.list_experiments(status=status)


@router.get(
    "/experiments/{experiment_id}/report",
    response_model=ExperimentReport,
    summary="Get experiment report",
)
async def get_experiment_report(
    experiment_id: str,
    ab_service: ABTestingService = Depends(_get_ab_service),
) -> ExperimentReport:
    """Get a full experiment report with metrics and significance.

    Args:
        experiment_id: Experiment ID.
        ab_service: Injected A/B service.

    Returns:
        ExperimentReport.
    """
    try:
        return ab_service.get_report(experiment_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Experiment not found")


# ---------------------------------------------------------------------------
# Strategy builder (internal)
# ---------------------------------------------------------------------------


def _build_strategy_results(
    request: RecommendationRequest,
    db: Session,
) -> Dict[str, List[StrategyResult]]:
    """Build strategy results from available data sources.

    Queries the database and builds mock/real strategy scores
    for each registered strategy. This is the integration point
    where real strategy implementations would plug in.

    Args:
        request: The recommendation request.
        db: Database session.

    Returns:
        Dict mapping strategy name to list of StrategyResult.
    """
    # First-Party
    from mcpgateway.db import Tool, ToolMetric

    from sqlalchemy import func, select
    from datetime import datetime, timedelta, timezone
    import math

    results: Dict[str, List[StrategyResult]] = {}
    now = datetime.now(timezone.utc)

    # Load enabled tools
    stmt = select(Tool).where(Tool.enabled.is_(True))
    if request.team_id:
        stmt = stmt.where(Tool.team_id == request.team_id)

    tools = db.execute(stmt).scalars().all()
    if not tools:
        return results

    # --- Trending strategy: score based on recent usage growth ---
    trending_results: List[StrategyResult] = []
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)

    for tool in tools:
        # Simple trending score based on execution count
        current_stmt = select(func.count()).where(
            ToolMetric.tool_id == tool.id,
            ToolMetric.timestamp >= week_ago,
        )
        current = db.execute(current_stmt).scalar() or 0

        prev_stmt = select(func.count()).where(
            ToolMetric.tool_id == tool.id,
            ToolMetric.timestamp >= two_weeks_ago,
            ToolMetric.timestamp < week_ago,
        )
        prev = db.execute(prev_stmt).scalar() or 0

        if current > 0:
            growth = ((current - prev) / max(prev, 1)) * 100
            score = min(1.0, math.log1p(current) / 10 + min(growth, 500) / 1000)
            trending_results.append(
                StrategyResult(
                    tool_id=tool.id,
                    score=score,
                    strategy="trending",
                    reason=f"Trending with {current} recent uses (+{growth:.0f}%)",
                    metadata={"tool_name": tool.name, "description": tool.description, "tags": tool.tags or []},
                )
            )

    if trending_results:
        results["trending"] = trending_results

    # --- New tools strategy: boost recently added tools ---
    new_results: List[StrategyResult] = []
    new_cutoff = now - timedelta(days=7)
    for tool in tools:
        if tool.created_at and tool.created_at >= new_cutoff:
            age_days = max((now - tool.created_at).total_seconds() / 86400, 0.1)
            score = max(0.1, 1.0 - (age_days / 7.0))
            new_results.append(
                StrategyResult(
                    tool_id=tool.id,
                    score=score,
                    strategy="new",
                    reason=f"New tool added {age_days:.1f} days ago",
                    metadata={"tool_name": tool.name, "description": tool.description, "tags": tool.tags or []},
                )
            )

    if new_results:
        results["new"] = new_results

    # --- Semantic strategy: keyword matching on query ---
    if request.query:
        semantic_results: List[StrategyResult] = []
        query_lower = request.query.lower()
        for tool in tools:
            name_match = query_lower in (tool.name or "").lower()
            desc_match = query_lower in (tool.description or "").lower()
            tag_match = any(query_lower in (t or "").lower() for t in (tool.tags or []))

            if name_match or desc_match or tag_match:
                score = 0.0
                if name_match:
                    score += 0.6
                if desc_match:
                    score += 0.3
                if tag_match:
                    score += 0.1
                semantic_results.append(
                    StrategyResult(
                        tool_id=tool.id,
                        score=min(score, 1.0),
                        strategy="semantic",
                        reason=f"Matches query '{request.query}'",
                        metadata={"tool_name": tool.name, "description": tool.description, "tags": tool.tags or []},
                    )
                )

        if semantic_results:
            results["semantic"] = semantic_results

    # --- Collaborative strategy: tools used by similar users (based on popularity) ---
    collab_results: List[StrategyResult] = []
    month_ago = now - timedelta(days=30)
    for tool in tools:
        pop_stmt = select(func.count()).where(
            ToolMetric.tool_id == tool.id,
            ToolMetric.timestamp >= month_ago,
        )
        pop = db.execute(pop_stmt).scalar() or 0
        if pop > 0:
            score = min(1.0, math.log1p(pop) / 8)
            collab_results.append(
                StrategyResult(
                    tool_id=tool.id,
                    score=score,
                    strategy="collaborative",
                    reason=f"Popular with {pop} uses in 30 days",
                    metadata={"tool_name": tool.name, "description": tool.description, "tags": tool.tags or []},
                )
            )

    if collab_results:
        results["collaborative"] = collab_results

    # --- Workflow strategy: tools with high success rate ---
    workflow_results: List[StrategyResult] = []
    for tool in tools:
        success_stmt = select(func.count()).where(
            ToolMetric.tool_id == tool.id,
            ToolMetric.is_success.is_(True),
            ToolMetric.timestamp >= month_ago,
        )
        total_stmt = select(func.count()).where(
            ToolMetric.tool_id == tool.id,
            ToolMetric.timestamp >= month_ago,
        )
        successes = db.execute(success_stmt).scalar() or 0
        total = db.execute(total_stmt).scalar() or 0

        if total >= 5:
            success_rate = successes / total
            score = success_rate * 0.8 + min(1.0, math.log1p(total) / 10) * 0.2
            workflow_results.append(
                StrategyResult(
                    tool_id=tool.id,
                    score=score,
                    strategy="workflow",
                    reason=f"High reliability: {success_rate:.0%} success rate ({total} uses)",
                    metadata={"tool_name": tool.name, "description": tool.description, "tags": tool.tags or []},
                )
            )

    if workflow_results:
        results["workflow"] = workflow_results

    # --- Conversation strategy: based on context tags ---
    context_tags = request.context.get("tags", [])
    if context_tags:
        conv_results: List[StrategyResult] = []
        for tool in tools:
            tool_tags = set(t.lower() for t in (tool.tags or []))
            context_set = set(t.lower() for t in context_tags)
            overlap = tool_tags & context_set
            if overlap:
                score = len(overlap) / max(len(context_set), 1)
                conv_results.append(
                    StrategyResult(
                        tool_id=tool.id,
                        score=min(score, 1.0),
                        strategy="conversation",
                        reason=f"Matches conversation context: {', '.join(overlap)}",
                        metadata={"tool_name": tool.name, "description": tool.description, "tags": tool.tags or []},
                    )
                )

        if conv_results:
            results["conversation"] = conv_results

    return results
