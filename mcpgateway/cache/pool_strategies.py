# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/pool_strategies.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Session Pool Strategy Enumerations.

This module defines the strategy types and status enums used by the session
pooling system. These enums ensure type safety and provide clear documentation
of available pooling strategies.

Examples:
    >>> from mcpgateway.cache.pool_strategies import PoolStrategy, PoolStatus
    >>> strategy = PoolStrategy.LEAST_CONNECTIONS
    >>> strategy.value
    'least_connections'
    >>> status = PoolStatus.ACTIVE
    >>> status.value
    'active'
"""

# Standard
from enum import Enum


class PoolStrategy(str, Enum):
    """
    Session pool routing strategies.

    Defines how sessions are distributed across pool slots.

    Attributes:
        ROUND_ROBIN: Distributes sessions evenly in circular order
        LEAST_CONNECTIONS: Routes to slot with fewest active connections
        STICKY: Maintains user affinity to specific pool slots
        WEIGHTED: Routes based on server performance metrics
        NONE: No pooling, direct connection mode

    Examples:
        >>> PoolStrategy.ROUND_ROBIN.value
        'round_robin'
        >>> list(PoolStrategy)
        [<PoolStrategy.ROUND_ROBIN: 'round_robin'>, <PoolStrategy.LEAST_CONNECTIONS: 'least_connections'>, <PoolStrategy.STICKY: 'sticky'>, <PoolStrategy.WEIGHTED: 'weighted'>, <PoolStrategy.NONE: 'none'>]
    """

    ROUND_ROBIN = "round_robin"
    LEAST_CONNECTIONS = "least_connections"
    STICKY = "sticky"
    WEIGHTED = "weighted"
    NONE = "none"


class PoolStatus(str, Enum):
    """
    Session pool health status.

    Indicates the operational state of a session pool.

    Attributes:
        IDLE: Pool is created but not yet initialized
        WARMING: Pool is initializing and creating minimum sessions
        ACTIVE: Pool is healthy and accepting connections
        DEGRADED: Pool is operational but experiencing issues
        INACTIVE: Pool is not accepting new connections
        INITIALIZING: Pool is being created
        DRAINING: Pool is being shut down gracefully
        ERROR: Pool encountered an error and is shut down

    Examples:
        >>> PoolStatus.ACTIVE.value
        'active'
        >>> PoolStatus.DEGRADED.value
        'degraded'
    """

    IDLE = "idle"
    WARMING = "warming"
    ACTIVE = "active"
    DEGRADED = "degraded"
    INACTIVE = "inactive"
    INITIALIZING = "initializing"
    DRAINING = "draining"
    ERROR = "error"


# Strategy descriptions for UI and documentation
STRATEGY_DESCRIPTIONS = {
    PoolStrategy.ROUND_ROBIN: "Distributes sessions evenly across all pool slots in circular order. Best for balanced workloads.",
    PoolStrategy.LEAST_CONNECTIONS: "Routes to the slot with fewest active connections. Best for varying request durations.",
    PoolStrategy.STICKY: "Maintains user affinity to specific pool slots. Best for stateful sessions.",
    PoolStrategy.WEIGHTED: "Routes based on server performance metrics and health. Best for heterogeneous servers.",
    PoolStrategy.NONE: "No pooling, creates direct connections. Use when pooling overhead exceeds benefits.",
}


def get_strategy_description(strategy: PoolStrategy) -> str:
    """
    Get human-readable description of a pooling strategy.

    Args:
        strategy: The pool strategy enum value

    Returns:
        str: Description of the strategy

    Examples:
        >>> desc = get_strategy_description(PoolStrategy.ROUND_ROBIN)
        >>> "circular" in desc.lower()
        True
        >>> desc = get_strategy_description(PoolStrategy.LEAST_CONNECTIONS)
        >>> "fewest" in desc.lower()
        True
    """
    return STRATEGY_DESCRIPTIONS.get(strategy, "Unknown strategy")


def recommend_strategy(avg_response_time: float, failure_rate: float, has_state: bool = False) -> PoolStrategy:
    """
    Recommend optimal pooling strategy based on server metrics.

    Args:
        avg_response_time: Average response time in seconds
        failure_rate: Failure rate as decimal (0.0 to 1.0)
        has_state: Whether sessions maintain state

    Returns:
        PoolStrategy: Recommended strategy

    Examples:
        >>> recommend_strategy(0.5, 0.01, False)
        <PoolStrategy.ROUND_ROBIN: 'round_robin'>
        >>> recommend_strategy(2.0, 0.01, False)
        <PoolStrategy.LEAST_CONNECTIONS: 'least_connections'>
        >>> recommend_strategy(0.5, 0.15, False)
        <PoolStrategy.WEIGHTED: 'weighted'>
        >>> recommend_strategy(0.5, 0.01, True)
        <PoolStrategy.STICKY: 'sticky'>
    """
    # Stateful sessions require sticky strategy
    if has_state:
        return PoolStrategy.STICKY

    # High failure rate: use weighted to avoid bad servers
    if failure_rate > 0.1:
        return PoolStrategy.WEIGHTED

    # High latency: use least connections to avoid overload
    if avg_response_time > 1.0:
        return PoolStrategy.LEAST_CONNECTIONS

    # Default: round robin for balanced load
    return PoolStrategy.ROUND_ROBIN


# Made with Bob
