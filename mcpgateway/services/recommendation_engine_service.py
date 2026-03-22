# -*- coding: utf-8 -*-
"""Personalized Recommendation Engine with Multi-Strategy Ranking.

Combines six recommendation strategies (semantic, collaborative, workflow,
conversation, trending, new) with configurable weights, applies boost factors,
deduplicates results, and maintains a full provenance trail.

Ranking completes within 50ms for 100+ candidates.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import hashlib
import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

# Third-Party
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strategy enumeration
# ---------------------------------------------------------------------------


class RecommendationStrategy(str, Enum):
    """Available recommendation strategies."""

    SEMANTIC = "semantic"
    COLLABORATIVE = "collaborative"
    WORKFLOW = "workflow"
    CONVERSATION = "conversation"
    TRENDING = "trending"
    NEW = "new"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_STRATEGY_WEIGHTS: Dict[str, float] = {
    RecommendationStrategy.SEMANTIC: 0.35,
    RecommendationStrategy.COLLABORATIVE: 0.25,
    RecommendationStrategy.WORKFLOW: 0.20,
    RecommendationStrategy.CONVERSATION: 0.10,
    RecommendationStrategy.TRENDING: 0.05,
    RecommendationStrategy.NEW: 0.05,
}

DEFAULT_BOOST_FACTORS: Dict[str, float] = {
    "favorite": 1.2,
    "recently_used": 1.1,
    "team_favorite": 1.05,
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class StrategyScore(BaseModel):
    """Score contribution from a single strategy."""

    strategy: str = Field(..., description="Strategy name")
    raw_score: float = Field(..., description="Raw score from strategy")
    weight: float = Field(..., description="Strategy weight used")
    weighted_score: float = Field(..., description="raw_score * weight")
    reason: str = Field("", description="Human-readable explanation")


class RecommendationExplanation(BaseModel):
    """Full explanation of why a tool was recommended."""

    strategy_scores: list[StrategyScore] = Field(default_factory=lambda: list[StrategyScore]())
    boost_factors: Dict[str, float] = Field(default_factory=dict, description="Applied boost factors")
    total_boost: float = Field(1.0, description="Combined boost multiplier")
    final_score: float = Field(0.0, description="Score after boosts")
    personalization_applied: bool = Field(False, description="Whether personalization was active")
    personalization_multiplier: float = Field(1.0, description="Personalization boost/suppress factor")
    context_factors: Dict[str, Any] = Field(default_factory=dict, description="Context that influenced ranking")


class RecommendedTool(BaseModel):
    """A single recommended tool with full provenance."""

    tool_id: str = Field(..., description="Tool identifier")
    tool_name: str = Field("", description="Display name")
    description: Optional[str] = Field(None, description="Tool description")
    tags: List[str] = Field(default_factory=list, description="Tool tags")
    score: float = Field(0.0, description="Final combined score")
    rank: int = Field(0, description="Position in recommendation list")
    recommendation_id: str = Field("", description="Unique ID for this recommendation")
    contributing_strategies: List[str] = Field(default_factory=list, description="Strategies that contributed")
    explanation: RecommendationExplanation = Field(default_factory=lambda: RecommendationExplanation(total_boost=1.0, final_score=0.0, personalization_applied=False, personalization_multiplier=1.0))

    model_config = {"from_attributes": True}


class RecommendationRequest(BaseModel):
    """Request for recommendations."""

    user_id: str = Field(..., description="User identifier")
    query: Optional[str] = Field(None, description="Search query for semantic matching")
    context: Dict[str, Any] = Field(default_factory=dict, description="Contextual information")
    team_id: Optional[str] = Field(None, description="Team filter")
    limit: int = Field(10, ge=1, le=100, description="Max results")
    strategy_weights: Optional[Dict[str, float]] = Field(None, description="Override strategy weights")
    include_explanation: bool = Field(True, description="Include detailed explanations")


class RecommendationResponse(BaseModel):
    """Response containing ranked recommendations."""

    recommendations: list[RecommendedTool] = Field(default_factory=lambda: list[RecommendedTool]())  # pyright: ignore[reportUnknownMemberType]
    total_candidates: int = Field(0, description="Total candidates before filtering")
    ranking_time_ms: float = Field(0.0, description="Time taken to rank in milliseconds")
    strategies_used: List[str] = Field(default_factory=list)
    experiment_variant: Optional[str] = Field(None, description="A/B test variant if active")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WhyNotResponse(BaseModel):
    """Response explaining why a tool was not recommended."""

    tool_id: str
    tool_name: str
    reasons: List[str] = Field(default_factory=list)
    strategy_scores: list[StrategyScore] = Field(default_factory=lambda: list[StrategyScore]())  # pyright: ignore[reportUnknownMemberType]
    would_rank: Optional[int] = Field(None, description="Position if it were included")
    suppressed: bool = Field(False, description="Whether actively suppressed")


# ---------------------------------------------------------------------------
# Strategy result container
# ---------------------------------------------------------------------------


class StrategyResult(BaseModel):
    """Result from a single strategy evaluation."""

    tool_id: str
    score: float
    strategy: str
    reason: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Recommendation Engine
# ---------------------------------------------------------------------------


class RecommendationEngine:
    """Multi-strategy recommendation ranker with personalization support.

    Aggregates scores from six strategies, applies boost factors and
    personalization, deduplicates by tool_id, and produces deterministic
    rankings for identical input.

    Attributes:
        strategy_weights: Configurable weights for each strategy.
        boost_factors: Configurable boost multipliers.
    """

    def __init__(
        self,
        strategy_weights: Optional[Dict[str, float]] = None,
        boost_factors: Optional[Dict[str, float]] = None,
    ):
        self.strategy_weights = dict(strategy_weights or DEFAULT_STRATEGY_WEIGHTS)
        self.boost_factors = dict(boost_factors or DEFAULT_BOOST_FACTORS)

    def rank(
        self,
        strategy_results: Dict[str, List[StrategyResult]],
        user_context: Optional[Dict[str, Any]] = None,
        personalization: Optional[Dict[str, float]] = None,
        hidden_tools: Optional[set[str]] = None,
        favorites: Optional[set[str]] = None,
        recently_used: Optional[set[str]] = None,
        team_favorites: Optional[set[str]] = None,
        weight_overrides: Optional[Dict[str, float]] = None,
        limit: int = 10,
    ) -> List[RecommendedTool]:
        """Rank tools across all strategies and return top results.

        Args:
            strategy_results: {strategy_name: [StrategyResult, ...]}.
            user_context: Optional context factors.
            personalization: {tool_id: affinity_score} from preference model.
            hidden_tools: Set of tool_ids the user has hidden.
            favorites: Set of tool_ids marked as favorites.
            recently_used: Set of tool_ids recently used.
            team_favorites: Set of tool_ids popular in user's team.
            weight_overrides: Override strategy weights (e.g. from A/B test).
            limit: Maximum results to return.

        Returns:
            List of RecommendedTool sorted by score descending.
        """
        start = time.monotonic()
        weights = dict(self.strategy_weights)
        if weight_overrides:
            weights.update(weight_overrides)

        user_context = user_context or {}
        personalization = personalization or {}
        hidden_tools = hidden_tools or set()
        favorites = favorites or set()
        recently_used = recently_used or set()
        team_favorites = team_favorites or set()

        # Step 1: Aggregate scores by tool_id
        aggregated: Dict[str, Dict[str, Any]] = {}

        for strategy_name, results in strategy_results.items():
            weight = weights.get(strategy_name, 0.0)
            for result in results:
                tid = result.tool_id
                if tid not in aggregated:
                    aggregated[tid] = {
                        "strategy_scores": [],
                        "total_weighted": 0.0,
                        "strategies": set(),
                        "metadata": {},
                    }

                weighted = result.score * weight
                aggregated[tid]["strategy_scores"].append(
                    StrategyScore(
                        strategy=strategy_name,
                        raw_score=result.score,
                        weight=weight,
                        weighted_score=round(weighted, 6),
                        reason=result.reason,
                    )
                )
                aggregated[tid]["total_weighted"] += weighted
                aggregated[tid]["strategies"].add(strategy_name)
                aggregated[tid]["metadata"].update(result.metadata)

        # Step 2: Apply boost factors and personalization
        ranked: List[RecommendedTool] = []

        for tid, data in aggregated.items():
            # Skip hidden tools (suppress to very low score)
            if tid in hidden_tools:
                continue

            base_score = data["total_weighted"]
            boost_applied: Dict[str, float] = {}
            total_boost = 1.0

            if tid in favorites:
                boost_applied["favorite"] = self.boost_factors.get("favorite", 1.2)
                total_boost *= boost_applied["favorite"]

            if tid in recently_used:
                boost_applied["recently_used"] = self.boost_factors.get("recently_used", 1.1)
                total_boost *= boost_applied["recently_used"]

            if tid in team_favorites:
                boost_applied["team_favorite"] = self.boost_factors.get("team_favorite", 1.05)
                total_boost *= boost_applied["team_favorite"]

            # Personalization multiplier
            personalization_applied = False
            personalization_mult = 1.0
            if tid in personalization:
                affinity = personalization[tid]
                personalization_mult = max(0.1, min(1.5, 1.0 + affinity))
                personalization_applied = True

            final_score = base_score * total_boost * personalization_mult

            meta = data["metadata"]
            rec_id = self._generate_recommendation_id(tid, final_score)

            explanation = RecommendationExplanation(
                strategy_scores=data["strategy_scores"],
                boost_factors=boost_applied,
                total_boost=round(total_boost, 4),
                final_score=round(final_score, 6),
                personalization_applied=personalization_applied,
                personalization_multiplier=round(personalization_mult, 4),
                context_factors=user_context,
            )

            ranked.append(
                RecommendedTool(
                    tool_id=tid,
                    tool_name=meta.get("tool_name", ""),
                    description=meta.get("description"),
                    tags=meta.get("tags", []),
                    score=round(final_score, 6),
                    rank=0,
                    recommendation_id=rec_id,
                    contributing_strategies=sorted(data["strategies"]),
                    explanation=explanation,
                )
            )

        # Step 3: Sort deterministically (score desc, tool_id asc for ties)
        ranked.sort(key=lambda r: (-r.score, r.tool_id))

        # Step 4: Assign ranks
        for idx, item in enumerate(ranked[:limit], start=1):
            item.rank = idx

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.debug("Ranked %d candidates in %.2fms", len(ranked), elapsed_ms)

        return ranked[:limit]

    def explain_why_not(
        self,
        tool_id: str,
        tool_name: str,
        strategy_results: Dict[str, List[StrategyResult]],
        hidden_tools: Optional[set[str]] = None,
        personalization: Optional[Dict[str, float]] = None,
    ) -> WhyNotResponse:
        """Explain why a tool was not recommended.

        Args:
            tool_id: Tool to explain.
            tool_name: Display name.
            strategy_results: All strategy results.
            hidden_tools: Set of hidden tool_ids.
            personalization: Personalization affinities.

        Returns:
            WhyNotResponse with reasons.
        """
        hidden_tools = hidden_tools or set()
        personalization = personalization or {}
        reasons: List[str] = []
        scores: List[StrategyScore] = []

        suppressed = tool_id in hidden_tools
        if suppressed:
            reasons.append("Tool was hidden/dismissed by user")

        found_in_any = False
        for strategy_name, results in strategy_results.items():
            for result in results:
                if result.tool_id == tool_id:
                    found_in_any = True
                    weight = self.strategy_weights.get(strategy_name, 0.0)
                    scores.append(
                        StrategyScore(
                            strategy=strategy_name,
                            raw_score=result.score,
                            weight=weight,
                            weighted_score=round(result.score * weight, 6),
                            reason=result.reason,
                        )
                    )

        if not found_in_any:
            reasons.append("Tool did not appear in any strategy results")

        if scores:
            total = sum(s.weighted_score for s in scores)
            if total < 0.01:
                reasons.append(f"Combined score too low ({total:.4f})")

        if tool_id in personalization and personalization[tool_id] < 0:
            reasons.append(f"Negative personalization affinity ({personalization[tool_id]:.2f})")

        return WhyNotResponse(
            tool_id=tool_id,
            tool_name=tool_name,
            reasons=reasons,
            strategy_scores=scores,
            would_rank=None,
            suppressed=suppressed,
        )

    @staticmethod
    def _generate_recommendation_id(tool_id: str, score: float) -> str:
        """Generate a deterministic recommendation ID."""
        data = f"{tool_id}:{score}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
