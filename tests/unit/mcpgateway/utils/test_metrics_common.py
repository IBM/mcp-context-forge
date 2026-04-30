# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_metrics_common.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for metrics_common utilities.
"""

# Standard
from types import SimpleNamespace

# First-Party
from mcpgateway.utils.metrics_common import build_top_performers


def test_build_top_performers_converts_types():
    result = SimpleNamespace(
        id=1,
        name="tool",
        execution_count=5,
        avg_response_time=1.23,
        success_rate=99.9,
        last_execution=None,
    )

    performers = build_top_performers([result])

    assert performers[0].id == 1
    assert performers[0].name == "tool"
    assert performers[0].execution_count == 5
    assert performers[0].avg_response_time == 1.23
    assert performers[0].success_rate == 99.9
    assert performers[0].last_execution is None


def test_build_top_performers_handles_missing_values():
    result = SimpleNamespace(
        id=2,
        name="tool2",
        execution_count=None,
        avg_response_time=None,
        success_rate=None,
        last_execution=None,
    )

    performers = build_top_performers([result])

    assert performers[0].execution_count == 0
    assert performers[0].avg_response_time is None
    assert performers[0].success_rate is None
    assert performers[0].last_execution is None


def test_build_top_performers_preserves_zero_values():
    """Zero avg_response_time and success_rate must not be coerced to None."""
    result = SimpleNamespace(
        id=3,
        name="zero-tool",
        execution_count=10,
        avg_response_time=0.0,
        success_rate=0.0,
        last_execution=None,
    )

    performers = build_top_performers([result])

    assert performers[0].avg_response_time == 0.0
    assert performers[0].success_rate == 0.0
