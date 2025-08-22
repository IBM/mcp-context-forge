# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/metrics_common.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Common utilities for metrics handling across service modules.
"""

# Standard
from typing import List

# First-Party
from mcpgateway.schemas import TopPerformer


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
