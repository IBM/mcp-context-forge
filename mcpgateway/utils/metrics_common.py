# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/metrics_common.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Common utilities for metrics handling across service modules.
"""

# Standard
from typing import List, Optional, Union

# First-Party
from mcpgateway.schemas import TopPerformer


def calculate_success_rate(successful: Union[int, float], total: Union[int, float]) -> Optional[float]:
    """
    Calculate success rate as a percentage.

    This function handles division by zero and ensures the result is always a valid
    percentage or None if the calculation is not possible.

    Args:
        successful: Number of successful operations
        total: Total number of operations

    Returns:
        Optional[float]: Success rate as a percentage (0-100) or None if total is zero

    Examples:
        >>> calculate_success_rate(75, 100)
        75.0
        >>> calculate_success_rate(0, 0)
        None
        >>> calculate_success_rate(0, 10)
        0.0
        >>> calculate_success_rate(5, 0)
        None
    """
    if total is None or successful is None:
        return None

    try:
        total_float = float(total)
        if total_float <= 0:
            return None
        return (float(successful) / total_float) * 100.0
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def format_response_time(response_time: Optional[float]) -> Optional[str]:
    """
    Format response time to display with 3 decimal places.

    Args:
        response_time: Response time in seconds

    Returns:
        Optional[str]: Formatted response time with 3 decimal places or None

    Examples:
        >>> format_response_time(1.2345)
        '1.235'
        >>> format_response_time(None)
        None
        >>> format_response_time(0)
        '0.000'
    """
    if response_time is None:
        return None

    try:
        return f"{float(response_time):.3f}"
    except (ValueError, TypeError):
        return None


def build_top_performers(results: List) -> List[TopPerformer]:
    """
    Convert database query results to TopPerformer objects.

    This utility function eliminates code duplication across service modules
    that need to convert database query results with metrics into TopPerformer objects.

    Args:
        results: List of database query results, each containing:
            - id: Entity ID
            - name: Entity name
            - execution_count: Total executions
            - avg_response_time: Average response time
            - success_rate: Success rate percentage
            - last_execution: Last execution timestamp

    Returns:
        List[TopPerformer]: List of TopPerformer objects with proper type conversions

    Examples:
        >>> from unittest.mock import MagicMock
        >>> result = MagicMock()
        >>> result.id = 1
        >>> result.name = "test"
        >>> result.execution_count = 10
        >>> result.avg_response_time = 1.5
        >>> result.success_rate = 85.0
        >>> result.last_execution = None
        >>> performers = build_top_performers([result])
        >>> len(performers)
        1
        >>> performers[0].id
        1
        >>> performers[0].execution_count
        10
        >>> performers[0].avg_response_time
        1.5
    """
    return [
        TopPerformer(
            id=result.id,
            name=result.name,
            execution_count=result.execution_count or 0,
            avg_response_time=float(result.avg_response_time) if result.avg_response_time else None,
            success_rate=float(result.success_rate) if result.success_rate else None,
            last_execution=result.last_execution,
        )
        for result in results
    ]
