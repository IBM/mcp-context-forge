#!/usr/bin/env python3
"""
Pytest-based benchmark comparison between Python and Rust deny list implementations.
This test always displays detailed output regardless of pytest flags.

This is a thin wrapper around benchmarks/compare.py module.
"""

import pytest

from benchmarks.compare import (
    ALL_IMPLS,
    CONFIG_FILES,
    WARMUP_RUNS,
    BENCHMARK_RUNS,
    run_benchmark,
    validate_results,
)


@pytest.mark.asyncio
async def test_benchmark_comparison():
    """Benchmark comparison between implementations."""
    results = await run_benchmark(
        config_files=CONFIG_FILES,
        impls=ALL_IMPLS,
        warmup_runs=WARMUP_RUNS,
        benchmark_runs=BENCHMARK_RUNS,
    )
    validate_results(results)
