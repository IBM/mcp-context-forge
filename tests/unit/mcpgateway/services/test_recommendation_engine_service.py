# -*- coding: utf-8 -*-
"""Tests for the Multi-Strategy Recommendation Engine.

Covers:
- RecommendationEngine: ranking, dedup, boost factors, personalization,
  deterministic ordering, performance (50ms for 100+ candidates)
- Explanation generation and "why not" queries
- Strategy score aggregation and provenance
- Edge cases: empty input, single strategy, all hidden

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import time
from typing import Dict, List

# Third-Party
import pytest

# First-Party
from mcpgateway.services.recommendation_engine_service import (
    DEFAULT_BOOST_FACTORS,
    DEFAULT_STRATEGY_WEIGHTS,
    RecommendationEngine,
    RecommendationExplanation,
    RecommendationResponse,
    RecommendationStrategy,
    RecommendedTool,
    StrategyResult,
    StrategyScore,
    WhyNotResponse,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def engine():
    """Create a default RecommendationEngine."""
    return RecommendationEngine()


@pytest.fixture
def custom_engine():
    """Create an engine with custom weights."""
    return RecommendationEngine(
        strategy_weights={"semantic": 0.50, "collaborative": 0.30, "trending": 0.20},
        boost_factors={"favorite": 1.5, "recently_used": 1.2},
    )


@pytest.fixture
def sample_strategy_results():
    """Build strategy results with multiple tools across strategies."""
    return {
        "semantic": [
            StrategyResult(
                tool_id="tool-1",
                score=0.9,
                strategy="semantic",
                reason="High semantic match",
                metadata={"tool_name": "Tool One", "description": "First tool", "tags": ["api"]},
            ),
            StrategyResult(
                tool_id="tool-2",
                score=0.6,
                strategy="semantic",
                reason="Moderate semantic match",
                metadata={"tool_name": "Tool Two", "description": "Second tool", "tags": ["db"]},
            ),
        ],
        "collaborative": [
            StrategyResult(
                tool_id="tool-1",
                score=0.7,
                strategy="collaborative",
                reason="Popular with similar users",
                metadata={"tool_name": "Tool One", "description": "First tool", "tags": ["api"]},
            ),
            StrategyResult(
                tool_id="tool-3",
                score=0.8,
                strategy="collaborative",
                reason="Top team pick",
                metadata={"tool_name": "Tool Three", "description": "Third tool", "tags": ["ml"]},
            ),
        ],
        "trending": [
            StrategyResult(
                tool_id="tool-2",
                score=0.5,
                strategy="trending",
                reason="Trending this week",
                metadata={"tool_name": "Tool Two", "description": "Second tool", "tags": ["db"]},
            ),
        ],
    }


@pytest.fixture
def large_strategy_results():
    """Build strategy results with 150+ tools for performance testing."""
    results: Dict[str, List[StrategyResult]] = {
        "semantic": [],
        "collaborative": [],
        "workflow": [],
        "conversation": [],
        "trending": [],
        "new": [],
    }
    for i in range(150):
        tid = f"tool-{i:04d}"
        for strategy in results:
            results[strategy].append(
                StrategyResult(
                    tool_id=tid,
                    score=0.1 + (i % 10) * 0.09,
                    strategy=strategy,
                    reason=f"Score from {strategy}",
                    metadata={"tool_name": f"Tool {i}", "description": f"Desc {i}", "tags": ["test"]},
                )
            )
    return results


# ============================================================================
# Default weights and config tests
# ============================================================================


class TestDefaultConfig:
    """Tests for default configuration values."""

    def test_default_strategy_weights_sum_to_one(self):
        total = sum(DEFAULT_STRATEGY_WEIGHTS.values())
        assert abs(total - 1.0) < 0.01, f"Weights sum to {total}, expected 1.0"

    def test_default_strategy_weights_all_positive(self):
        for strategy, weight in DEFAULT_STRATEGY_WEIGHTS.items():
            assert weight > 0, f"Strategy {strategy} has non-positive weight {weight}"

    def test_default_boost_factors_all_above_one(self):
        for name, factor in DEFAULT_BOOST_FACTORS.items():
            assert factor >= 1.0, f"Boost {name} is {factor}, expected >= 1.0"

    def test_strategy_enum_values(self):
        assert RecommendationStrategy.SEMANTIC == "semantic"
        assert RecommendationStrategy.COLLABORATIVE == "collaborative"
        assert RecommendationStrategy.WORKFLOW == "workflow"
        assert RecommendationStrategy.CONVERSATION == "conversation"
        assert RecommendationStrategy.TRENDING == "trending"
        assert RecommendationStrategy.NEW == "new"


# ============================================================================
# Pydantic model tests
# ============================================================================


class TestPydanticModels:
    """Tests for Pydantic response models."""

    def test_strategy_score_model(self):
        score = StrategyScore(
            strategy="semantic",
            raw_score=0.9,
            weight=0.35,
            weighted_score=0.315,
            reason="Strong match",
        )
        assert score.strategy == "semantic"
        assert score.weighted_score == 0.315

    def test_recommended_tool_model(self):
        tool = RecommendedTool(
            tool_id="t1",
            tool_name="My Tool",
            score=0.85,
            rank=1,
            recommendation_id="abc123",
            contributing_strategies=["semantic", "collaborative"],
        )
        assert tool.tool_id == "t1"
        assert tool.rank == 1
        assert len(tool.contributing_strategies) == 2

    def test_explanation_model(self):
        exp = RecommendationExplanation(
            strategy_scores=[],
            boost_factors={"favorite": 1.2},
            total_boost=1.2,
            final_score=0.5,
            personalization_applied=True,
            personalization_multiplier=1.3,
        )
        assert exp.personalization_applied is True
        assert exp.total_boost == 1.2

    def test_recommendation_response_model(self):
        resp = RecommendationResponse(
            recommendations=[],
            total_candidates=50,
            ranking_time_ms=12.5,
            strategies_used=["semantic"],
        )
        assert resp.total_candidates == 50
        assert resp.generated_at is not None

    def test_why_not_response_model(self):
        resp = WhyNotResponse(
            tool_id="t1",
            tool_name="Missing Tool",
            reasons=["Too low score"],
            suppressed=False,
        )
        assert not resp.suppressed
        assert len(resp.reasons) == 1


# ============================================================================
# Core ranking tests
# ============================================================================


class TestRankingCore:
    """Tests for the core ranking functionality."""

    def test_rank_combines_strategies(self, engine, sample_strategy_results):
        ranked = engine.rank(sample_strategy_results, limit=10)
        assert len(ranked) > 0
        # tool-1 appears in both semantic and collaborative — should rank high
        tool_ids = [r.tool_id for r in ranked]
        assert "tool-1" in tool_ids

    def test_rank_assigns_sequential_ranks(self, engine, sample_strategy_results):
        ranked = engine.rank(sample_strategy_results, limit=10)
        for i, item in enumerate(ranked, start=1):
            assert item.rank == i

    def test_rank_scores_descending(self, engine, sample_strategy_results):
        ranked = engine.rank(sample_strategy_results, limit=10)
        scores = [r.score for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_rank_respects_limit(self, engine, sample_strategy_results):
        ranked = engine.rank(sample_strategy_results, limit=2)
        assert len(ranked) <= 2

    def test_rank_deterministic(self, engine, sample_strategy_results):
        """Identical input produces identical output."""
        r1 = engine.rank(sample_strategy_results, limit=10)
        r2 = engine.rank(sample_strategy_results, limit=10)
        assert [r.tool_id for r in r1] == [r.tool_id for r in r2]
        assert [r.score for r in r1] == [r.score for r in r2]

    def test_rank_deduplicates_by_tool_id(self, engine, sample_strategy_results):
        ranked = engine.rank(sample_strategy_results, limit=10)
        tool_ids = [r.tool_id for r in ranked]
        assert len(tool_ids) == len(set(tool_ids)), "Duplicate tool_ids in results"

    def test_rank_empty_input(self, engine):
        ranked = engine.rank({}, limit=10)
        assert ranked == []

    def test_rank_single_strategy(self, engine):
        results = {
            "semantic": [
                StrategyResult(tool_id="t1", score=0.5, strategy="semantic", metadata={"tool_name": "T1"}),
            ]
        }
        ranked = engine.rank(results, limit=10)
        assert len(ranked) == 1
        assert ranked[0].tool_id == "t1"

    def test_rank_merges_scores_across_strategies(self, engine):
        """tool-1 in semantic (0.9*0.35=0.315) + collaborative (0.7*0.25=0.175) = 0.49."""
        results = {
            "semantic": [StrategyResult(tool_id="t1", score=0.9, strategy="semantic", metadata={})],
            "collaborative": [StrategyResult(tool_id="t1", score=0.7, strategy="collaborative", metadata={})],
        }
        ranked = engine.rank(results, limit=10)
        assert len(ranked) == 1
        expected = 0.9 * 0.35 + 0.7 * 0.25
        assert abs(ranked[0].score - expected) < 0.001

    def test_contributing_strategies_tracked(self, engine, sample_strategy_results):
        ranked = engine.rank(sample_strategy_results, limit=10)
        t1 = next(r for r in ranked if r.tool_id == "tool-1")
        assert "semantic" in t1.contributing_strategies
        assert "collaborative" in t1.contributing_strategies

    def test_recommendation_id_generated(self, engine, sample_strategy_results):
        ranked = engine.rank(sample_strategy_results, limit=10)
        for r in ranked:
            assert r.recommendation_id, f"Missing recommendation_id for {r.tool_id}"
            assert len(r.recommendation_id) == 16


# ============================================================================
# Boost factor tests
# ============================================================================


class TestBoostFactors:
    """Tests for boost factor application."""

    def test_favorite_boost(self, engine):
        results = {
            "semantic": [
                StrategyResult(tool_id="t1", score=0.5, strategy="semantic", metadata={}),
                StrategyResult(tool_id="t2", score=0.5, strategy="semantic", metadata={}),
            ]
        }
        ranked = engine.rank(results, favorites={"t1"}, limit=10)
        t1 = next(r for r in ranked if r.tool_id == "t1")
        t2 = next(r for r in ranked if r.tool_id == "t2")
        assert t1.score > t2.score, "Favorite should score higher"

    def test_recently_used_boost(self, engine):
        results = {
            "semantic": [
                StrategyResult(tool_id="t1", score=0.5, strategy="semantic", metadata={}),
                StrategyResult(tool_id="t2", score=0.5, strategy="semantic", metadata={}),
            ]
        }
        ranked = engine.rank(results, recently_used={"t1"}, limit=10)
        t1 = next(r for r in ranked if r.tool_id == "t1")
        t2 = next(r for r in ranked if r.tool_id == "t2")
        assert t1.score > t2.score

    def test_team_favorite_boost(self, engine):
        results = {
            "semantic": [
                StrategyResult(tool_id="t1", score=0.5, strategy="semantic", metadata={}),
                StrategyResult(tool_id="t2", score=0.5, strategy="semantic", metadata={}),
            ]
        }
        ranked = engine.rank(results, team_favorites={"t1"}, limit=10)
        t1 = next(r for r in ranked if r.tool_id == "t1")
        t2 = next(r for r in ranked if r.tool_id == "t2")
        assert t1.score > t2.score

    def test_stacked_boosts(self, engine):
        """All three boosts applied to same tool."""
        results = {
            "semantic": [
                StrategyResult(tool_id="t1", score=0.5, strategy="semantic", metadata={}),
                StrategyResult(tool_id="t2", score=0.5, strategy="semantic", metadata={}),
            ]
        }
        ranked = engine.rank(
            results,
            favorites={"t1"},
            recently_used={"t1"},
            team_favorites={"t1"},
            limit=10,
        )
        t1 = next(r for r in ranked if r.tool_id == "t1")
        t2 = next(r for r in ranked if r.tool_id == "t2")
        # Stacked: 1.2 * 1.1 * 1.05 = 1.386
        expected_boost = 1.2 * 1.1 * 1.05
        assert abs(t1.score / t2.score - expected_boost) < 0.01

    def test_boost_factors_in_explanation(self, engine):
        results = {
            "semantic": [StrategyResult(tool_id="t1", score=0.5, strategy="semantic", metadata={})],
        }
        ranked = engine.rank(results, favorites={"t1"}, limit=10)
        assert "favorite" in ranked[0].explanation.boost_factors

    def test_custom_boost_factors(self, custom_engine):
        results = {
            "semantic": [
                StrategyResult(tool_id="t1", score=0.5, strategy="semantic", metadata={}),
                StrategyResult(tool_id="t2", score=0.5, strategy="semantic", metadata={}),
            ]
        }
        ranked = custom_engine.rank(results, favorites={"t1"}, limit=10)
        t1 = next(r for r in ranked if r.tool_id == "t1")
        t2 = next(r for r in ranked if r.tool_id == "t2")
        # Custom favorite boost is 1.5 (not default 1.2)
        expected_ratio = 1.5
        assert abs(t1.score / t2.score - expected_ratio) < 0.01


# ============================================================================
# Personalization tests
# ============================================================================


class TestPersonalization:
    """Tests for personalization support."""

    def test_positive_personalization_boosts(self, engine):
        results = {
            "semantic": [
                StrategyResult(tool_id="t1", score=0.5, strategy="semantic", metadata={}),
                StrategyResult(tool_id="t2", score=0.5, strategy="semantic", metadata={}),
            ]
        }
        personalization = {"t1": 0.3}  # +30% affinity
        ranked = engine.rank(results, personalization=personalization, limit=10)
        t1 = next(r for r in ranked if r.tool_id == "t1")
        t2 = next(r for r in ranked if r.tool_id == "t2")
        assert t1.score > t2.score
        assert t1.explanation.personalization_applied

    def test_negative_personalization_suppresses(self, engine):
        results = {
            "semantic": [
                StrategyResult(tool_id="t1", score=0.5, strategy="semantic", metadata={}),
                StrategyResult(tool_id="t2", score=0.5, strategy="semantic", metadata={}),
            ]
        }
        personalization = {"t1": -0.5}  # Suppress
        ranked = engine.rank(results, personalization=personalization, limit=10)
        t1 = next(r for r in ranked if r.tool_id == "t1")
        t2 = next(r for r in ranked if r.tool_id == "t2")
        assert t1.score < t2.score

    def test_hidden_tools_excluded(self, engine):
        results = {
            "semantic": [
                StrategyResult(tool_id="t1", score=0.9, strategy="semantic", metadata={}),
                StrategyResult(tool_id="t2", score=0.5, strategy="semantic", metadata={}),
            ]
        }
        ranked = engine.rank(results, hidden_tools={"t1"}, limit=10)
        tool_ids = [r.tool_id for r in ranked]
        assert "t1" not in tool_ids
        assert "t2" in tool_ids

    def test_all_tools_hidden(self, engine):
        results = {
            "semantic": [
                StrategyResult(tool_id="t1", score=0.9, strategy="semantic", metadata={}),
            ]
        }
        ranked = engine.rank(results, hidden_tools={"t1"}, limit=10)
        assert ranked == []

    def test_personalization_clamped(self, engine):
        """Extreme personalization values should be clamped."""
        results = {
            "semantic": [StrategyResult(tool_id="t1", score=0.5, strategy="semantic", metadata={})],
        }
        # Very high affinity — should be clamped to max 1.5x multiplier
        personalization = {"t1": 10.0}
        ranked = engine.rank(results, personalization=personalization, limit=10)
        # Max multiplier is min(1.5, 1.0 + 10.0) = 1.5
        expected = 0.5 * 0.35 * 1.5
        assert abs(ranked[0].score - expected) < 0.001


# ============================================================================
# Weight override tests
# ============================================================================


class TestWeightOverrides:
    """Tests for dynamic weight overrides (A/B testing support)."""

    def test_weight_override_changes_ranking(self, engine):
        results = {
            "semantic": [StrategyResult(tool_id="t1", score=0.9, strategy="semantic", metadata={})],
            "trending": [StrategyResult(tool_id="t2", score=0.9, strategy="trending", metadata={})],
        }
        # Default: semantic=0.35, trending=0.05 => t1 wins
        ranked_default = engine.rank(results, limit=10)
        assert ranked_default[0].tool_id == "t1"

        # Override: semantic=0.05, trending=0.95 => t2 wins
        ranked_override = engine.rank(results, weight_overrides={"semantic": 0.05, "trending": 0.95}, limit=10)
        assert ranked_override[0].tool_id == "t2"


# ============================================================================
# Performance tests
# ============================================================================


class TestPerformance:
    """Tests for ranking performance requirements."""

    def test_ranking_100_candidates_under_50ms(self, engine, large_strategy_results):
        """Ranking 150 candidates across 6 strategies must complete in <50ms."""
        start = time.monotonic()
        ranked = engine.rank(large_strategy_results, limit=20)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 50, f"Ranking took {elapsed_ms:.1f}ms, exceeds 50ms limit"
        assert len(ranked) == 20

    def test_ranking_large_set_deterministic(self, engine, large_strategy_results):
        r1 = engine.rank(large_strategy_results, limit=20)
        r2 = engine.rank(large_strategy_results, limit=20)
        assert [r.tool_id for r in r1] == [r.tool_id for r in r2]


# ============================================================================
# Explanation and "why not" tests
# ============================================================================


class TestExplanations:
    """Tests for recommendation explanations."""

    def test_explanation_includes_strategy_scores(self, engine, sample_strategy_results):
        ranked = engine.rank(sample_strategy_results, limit=10)
        for r in ranked:
            assert len(r.explanation.strategy_scores) > 0

    def test_explanation_shows_boost_factors(self, engine):
        results = {
            "semantic": [StrategyResult(tool_id="t1", score=0.5, strategy="semantic", metadata={})],
        }
        ranked = engine.rank(results, favorites={"t1"}, recently_used={"t1"}, limit=10)
        exp = ranked[0].explanation
        assert "favorite" in exp.boost_factors
        assert "recently_used" in exp.boost_factors
        assert exp.total_boost > 1.0

    def test_explanation_final_score_matches(self, engine, sample_strategy_results):
        ranked = engine.rank(sample_strategy_results, limit=10)
        for r in ranked:
            assert abs(r.score - r.explanation.final_score) < 0.0001

    def test_why_not_hidden_tool(self, engine):
        results = {
            "semantic": [StrategyResult(tool_id="t1", score=0.9, strategy="semantic", metadata={})],
        }
        resp = engine.explain_why_not("t1", "Tool One", results, hidden_tools={"t1"})
        assert resp.suppressed
        assert any("hidden" in r.lower() for r in resp.reasons)

    def test_why_not_missing_tool(self, engine):
        results = {
            "semantic": [StrategyResult(tool_id="t1", score=0.9, strategy="semantic", metadata={})],
        }
        resp = engine.explain_why_not("t-missing", "Missing Tool", results)
        assert any("did not appear" in r.lower() for r in resp.reasons)

    def test_why_not_low_score(self, engine):
        results = {
            "semantic": [StrategyResult(tool_id="t1", score=0.001, strategy="semantic", metadata={})],
        }
        resp = engine.explain_why_not("t1", "Low Tool", results)
        assert any("score" in r.lower() for r in resp.reasons)

    def test_why_not_negative_personalization(self, engine):
        results = {
            "semantic": [StrategyResult(tool_id="t1", score=0.5, strategy="semantic", metadata={})],
        }
        resp = engine.explain_why_not("t1", "Tool", results, personalization={"t1": -0.5})
        assert any("personalization" in r.lower() for r in resp.reasons)

    def test_why_not_returns_strategy_scores(self, engine):
        results = {
            "semantic": [
                StrategyResult(tool_id="t1", score=0.5, strategy="semantic", reason="Match", metadata={}),
            ],
        }
        resp = engine.explain_why_not("t1", "Tool", results)
        assert len(resp.strategy_scores) == 1
        assert resp.strategy_scores[0].strategy == "semantic"


# ============================================================================
# Edge case tests
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_zero_scores(self, engine):
        results = {
            "semantic": [StrategyResult(tool_id="t1", score=0.0, strategy="semantic", metadata={})],
        }
        ranked = engine.rank(results, limit=10)
        assert len(ranked) == 1
        assert ranked[0].score == 0.0

    def test_identical_scores_sorted_by_tool_id(self, engine):
        """Ties broken by tool_id alphabetically for determinism."""
        results = {
            "semantic": [
                StrategyResult(tool_id="b-tool", score=0.5, strategy="semantic", metadata={}),
                StrategyResult(tool_id="a-tool", score=0.5, strategy="semantic", metadata={}),
            ]
        }
        ranked = engine.rank(results, limit=10)
        assert ranked[0].tool_id == "a-tool"
        assert ranked[1].tool_id == "b-tool"

    def test_unknown_strategy_ignored_in_weights(self, engine):
        results = {
            "unknown_strategy": [
                StrategyResult(tool_id="t1", score=0.9, strategy="unknown_strategy", metadata={}),
            ]
        }
        ranked = engine.rank(results, limit=10)
        # Weight = 0.0 for unknown, so score should be 0
        assert len(ranked) == 1
        assert ranked[0].score == 0.0

    def test_recommendation_id_deterministic(self, engine):
        id1 = RecommendationEngine._generate_recommendation_id("t1", 0.5)
        id2 = RecommendationEngine._generate_recommendation_id("t1", 0.5)
        assert id1 == id2

    def test_recommendation_id_varies_with_score(self, engine):
        id1 = RecommendationEngine._generate_recommendation_id("t1", 0.5)
        id2 = RecommendationEngine._generate_recommendation_id("t1", 0.6)
        assert id1 != id2
