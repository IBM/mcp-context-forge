# -*- coding: utf-8 -*-
"""Unit tests for session pool strategies.

Tests the pool strategy selection logic, including:
- Strategy recommendation based on metrics
- Strategy enum validation
- Strategy descriptions
- Edge cases and error handling
"""

import pytest

from mcpgateway.cache.pool_strategies import (
    PoolStrategy,
    PoolStatus,
    recommend_strategy,
    get_strategy_description,
    STRATEGY_DESCRIPTIONS,
)


class TestPoolStrategy:
    """Test PoolStrategy enum."""

    def test_pool_strategy_values(self):
        """Test that all expected strategies are defined."""
        assert PoolStrategy.ROUND_ROBIN == "round_robin"
        assert PoolStrategy.LEAST_CONNECTIONS == "least_connections"
        assert PoolStrategy.STICKY == "sticky"
        assert PoolStrategy.WEIGHTED == "weighted"
        assert PoolStrategy.NONE == "none"

    def test_pool_strategy_iteration(self):
        """Test that we can iterate over all strategies."""
        strategies = list(PoolStrategy)
        assert len(strategies) == 5
        assert PoolStrategy.ROUND_ROBIN in strategies
        assert PoolStrategy.LEAST_CONNECTIONS in strategies
        assert PoolStrategy.STICKY in strategies
        assert PoolStrategy.WEIGHTED in strategies
        assert PoolStrategy.NONE in strategies

    def test_pool_strategy_string_conversion(self):
        """Test string conversion of strategies."""
        # String conversion returns the enum representation, not the value
        assert str(PoolStrategy.ROUND_ROBIN) == "PoolStrategy.ROUND_ROBIN"
        assert str(PoolStrategy.LEAST_CONNECTIONS) == "PoolStrategy.LEAST_CONNECTIONS"

    def test_pool_strategy_value_access(self):
        """Test accessing strategy values."""
        assert PoolStrategy.ROUND_ROBIN.value == "round_robin"
        assert PoolStrategy.STICKY.value == "sticky"


class TestPoolStatus:
    """Test PoolStatus enum."""

    def test_pool_status_values(self):
        """Test that all expected statuses are defined."""
        assert PoolStatus.IDLE == "idle"
        assert PoolStatus.WARMING == "warming"
        assert PoolStatus.ACTIVE == "active"
        assert PoolStatus.DEGRADED == "degraded"
        assert PoolStatus.INACTIVE == "inactive"
        assert PoolStatus.INITIALIZING == "initializing"
        assert PoolStatus.DRAINING == "draining"
        assert PoolStatus.ERROR == "error"

    def test_pool_status_iteration(self):
        """Test that we can iterate over all statuses."""
        statuses = list(PoolStatus)
        assert len(statuses) == 8
        assert PoolStatus.IDLE in statuses
        assert PoolStatus.WARMING in statuses
        assert PoolStatus.ACTIVE in statuses
        assert PoolStatus.DEGRADED in statuses
        assert PoolStatus.INACTIVE in statuses
        assert PoolStatus.INITIALIZING in statuses
        assert PoolStatus.DRAINING in statuses
        assert PoolStatus.ERROR in statuses

    def test_pool_status_string_conversion(self):
        """Test string conversion of statuses."""
        # String conversion returns the enum representation, not the value
        assert str(PoolStatus.ACTIVE) == "PoolStatus.ACTIVE"
        assert str(PoolStatus.DEGRADED) == "PoolStatus.DEGRADED"


class TestRecommendStrategy:
    """Test strategy recommendation logic."""

    def test_recommend_round_robin_for_low_latency(self):
        """Test that round robin is recommended for low latency and low failure rate."""
        strategy = recommend_strategy(
            avg_response_time=0.5,  # Low latency
            failure_rate=0.01,  # Low failure rate
            has_state=False
        )
        assert strategy == PoolStrategy.ROUND_ROBIN

    def test_recommend_least_connections_for_high_latency(self):
        """Test that least connections is recommended for high latency."""
        strategy = recommend_strategy(
            avg_response_time=2.0,  # High latency (> 1.0)
            failure_rate=0.01,
            has_state=False
        )
        assert strategy == PoolStrategy.LEAST_CONNECTIONS

    def test_recommend_weighted_for_high_failure_rate(self):
        """Test that weighted is recommended for high failure rate."""
        strategy = recommend_strategy(
            avg_response_time=0.5,
            failure_rate=0.15,  # High failure rate (> 0.1)
            has_state=False
        )
        assert strategy == PoolStrategy.WEIGHTED

    def test_recommend_sticky_for_stateful_sessions(self):
        """Test that sticky is recommended for stateful sessions."""
        strategy = recommend_strategy(
            avg_response_time=0.5,
            failure_rate=0.01,
            has_state=True  # Stateful
        )
        assert strategy == PoolStrategy.STICKY

    def test_sticky_overrides_other_factors(self):
        """Test that stateful sessions always get sticky strategy."""
        # Even with high latency and high failure rate
        strategy = recommend_strategy(
            avg_response_time=5.0,
            failure_rate=0.20,
            has_state=True
        )
        assert strategy == PoolStrategy.STICKY

    def test_weighted_takes_precedence_over_latency(self):
        """Test that high failure rate takes precedence over high latency."""
        strategy = recommend_strategy(
            avg_response_time=2.0,  # High latency
            failure_rate=0.15,  # High failure rate
            has_state=False
        )
        # Weighted should be chosen over least_connections
        assert strategy == PoolStrategy.WEIGHTED

    def test_boundary_conditions(self):
        """Test boundary conditions for thresholds."""
        # Exactly at latency threshold
        strategy1 = recommend_strategy(1.0, 0.01, False)
        assert strategy1 == PoolStrategy.ROUND_ROBIN
        
        # Just over latency threshold
        strategy2 = recommend_strategy(1.01, 0.01, False)
        assert strategy2 == PoolStrategy.LEAST_CONNECTIONS
        
        # Exactly at failure threshold
        strategy3 = recommend_strategy(0.5, 0.1, False)
        assert strategy3 == PoolStrategy.ROUND_ROBIN
        
        # Just over failure threshold
        strategy4 = recommend_strategy(0.5, 0.11, False)
        assert strategy4 == PoolStrategy.WEIGHTED


class TestGetStrategyDescription:
    """Test strategy description retrieval."""

    def test_get_round_robin_description(self):
        """Test getting round robin description."""
        desc = get_strategy_description(PoolStrategy.ROUND_ROBIN)
        assert isinstance(desc, str)
        assert len(desc) > 0
        assert "circular" in desc.lower() or "evenly" in desc.lower()

    def test_get_least_connections_description(self):
        """Test getting least connections description."""
        desc = get_strategy_description(PoolStrategy.LEAST_CONNECTIONS)
        assert isinstance(desc, str)
        assert "fewest" in desc.lower() or "least" in desc.lower()

    def test_get_sticky_description(self):
        """Test getting sticky description."""
        desc = get_strategy_description(PoolStrategy.STICKY)
        assert isinstance(desc, str)
        assert "affinity" in desc.lower() or "stateful" in desc.lower()

    def test_get_weighted_description(self):
        """Test getting weighted description."""
        desc = get_strategy_description(PoolStrategy.WEIGHTED)
        assert isinstance(desc, str)
        assert "performance" in desc.lower() or "metrics" in desc.lower()

    def test_get_none_description(self):
        """Test getting none strategy description."""
        desc = get_strategy_description(PoolStrategy.NONE)
        assert isinstance(desc, str)
        assert "direct" in desc.lower() or "no pooling" in desc.lower()

    def test_all_strategies_have_descriptions(self):
        """Test that all strategies have descriptions."""
        for strategy in PoolStrategy:
            desc = get_strategy_description(strategy)
            assert isinstance(desc, str)
            assert len(desc) > 0
            assert desc != "Unknown strategy"


class TestStrategyDescriptions:
    """Test STRATEGY_DESCRIPTIONS constant."""

    def test_descriptions_dict_exists(self):
        """Test that descriptions dictionary exists."""
        assert isinstance(STRATEGY_DESCRIPTIONS, dict)
        assert len(STRATEGY_DESCRIPTIONS) == 5

    def test_all_strategies_in_descriptions(self):
        """Test that all strategies have entries in descriptions."""
        for strategy in PoolStrategy:
            assert strategy in STRATEGY_DESCRIPTIONS

    def test_descriptions_are_strings(self):
        """Test that all descriptions are non-empty strings."""
        for strategy, desc in STRATEGY_DESCRIPTIONS.items():
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_descriptions_are_informative(self):
        """Test that descriptions contain useful information."""
        for strategy, desc in STRATEGY_DESCRIPTIONS.items():
            # Each description should be at least 20 characters
            assert len(desc) >= 20
            # Should contain the word "Best" or "Use" (as per implementation)
            assert "Best" in desc or "best" in desc or "Use" in desc


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_zero_latency(self):
        """Test handling of zero latency."""
        strategy = recommend_strategy(0.0, 0.01, False)
        assert strategy == PoolStrategy.ROUND_ROBIN

    def test_zero_failure_rate(self):
        """Test handling of zero failure rate."""
        strategy = recommend_strategy(0.5, 0.0, False)
        assert strategy == PoolStrategy.ROUND_ROBIN

    def test_very_high_latency(self):
        """Test handling of very high latency."""
        strategy = recommend_strategy(100.0, 0.01, False)
        assert strategy == PoolStrategy.LEAST_CONNECTIONS

    def test_very_high_failure_rate(self):
        """Test handling of very high failure rate."""
        strategy = recommend_strategy(0.5, 0.99, False)
        assert strategy == PoolStrategy.WEIGHTED

    def test_negative_latency(self):
        """Test handling of negative latency (invalid input)."""
        # Should still return a valid strategy
        strategy = recommend_strategy(-1.0, 0.01, False)
        assert strategy in list(PoolStrategy)

    def test_negative_failure_rate(self):
        """Test handling of negative failure rate (invalid input)."""
        # Should still return a valid strategy
        strategy = recommend_strategy(0.5, -0.1, False)
        assert strategy in list(PoolStrategy)

    def test_failure_rate_over_one(self):
        """Test handling of failure rate > 1.0 (invalid input)."""
        # Should still return a valid strategy
        strategy = recommend_strategy(0.5, 1.5, False)
        assert strategy in list(PoolStrategy)


@pytest.mark.parametrize("strategy", list(PoolStrategy))
def test_all_strategies_valid(strategy):
    """Test that all strategy enum values are valid strings."""
    assert isinstance(strategy.value, str)
    assert len(strategy.value) > 0
    # Values can have underscores or be single words like "none", "sticky", "weighted"
    assert "_" in strategy.value or strategy.value in ["none", "sticky", "weighted"]


@pytest.mark.parametrize("status", list(PoolStatus))
def test_all_statuses_valid(status):
    """Test that all status enum values are valid strings."""
    assert isinstance(status.value, str)
    assert len(status.value) > 0


def test_strategy_recommendation_consistency():
    """Test that strategy recommendations are consistent for same input."""
    # Should return same strategy for same metrics
    strategy1 = recommend_strategy(0.5, 0.01, False)
    strategy2 = recommend_strategy(0.5, 0.01, False)
    strategy3 = recommend_strategy(0.5, 0.01, False)
    
    assert strategy1 == strategy2 == strategy3


def test_strategy_recommendation_deterministic():
    """Test that recommendations are deterministic."""
    test_cases = [
        (0.5, 0.01, False, PoolStrategy.ROUND_ROBIN),
        (2.0, 0.01, False, PoolStrategy.LEAST_CONNECTIONS),
        (0.5, 0.15, False, PoolStrategy.WEIGHTED),
        (0.5, 0.01, True, PoolStrategy.STICKY),
    ]
    
    for avg_time, fail_rate, has_state, expected in test_cases:
        result = recommend_strategy(avg_time, fail_rate, has_state)
        assert result == expected, f"Expected {expected} for ({avg_time}, {fail_rate}, {has_state}), got {result}"


class TestStrategyPriority:
    """Test strategy selection priority."""

    def test_stateful_highest_priority(self):
        """Test that stateful sessions have highest priority."""
        # Stateful should override everything
        assert recommend_strategy(10.0, 0.5, True) == PoolStrategy.STICKY

    def test_failure_rate_over_latency(self):
        """Test that failure rate takes precedence over latency."""
        # High failure rate should choose weighted over least_connections
        assert recommend_strategy(5.0, 0.2, False) == PoolStrategy.WEIGHTED

    def test_default_to_round_robin(self):
        """Test that round robin is the default for good metrics."""
        assert recommend_strategy(0.1, 0.001, False) == PoolStrategy.ROUND_ROBIN
        assert recommend_strategy(0.5, 0.05, False) == PoolStrategy.ROUND_ROBIN
        assert recommend_strategy(0.9, 0.09, False) == PoolStrategy.ROUND_ROBIN

# Made with Bob
