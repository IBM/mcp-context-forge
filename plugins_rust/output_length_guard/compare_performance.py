#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Performance comparison: Python vs Rust output length guard.

Measures the hot-path processing time for both implementations using
native Python objects (no JSON serialization overhead).

Scenarios cover the realistic input shapes the plugin sees:
  - Plain strings (small, medium, large)
  - Lists of strings
  - Nested dicts/lists (structured content)
  - Token-mode truncation with binary search
  - Block-mode violation detection

Usage:
    python compare_performance.py
    python compare_performance.py --iterations 5000 --warmup 50
"""

import argparse
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import Mock

# Add plugins directory to path for Python implementation imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Suppress debug logging from the plugin during benchmarks
import logging  # noqa: E402
logging.disable(logging.CRITICAL)

from plugins.output_length_guard.output_length_guard import (  # noqa: E402
    OutputLengthGuardConfig,
    _estimate_tokens,
    _find_token_cut_point,
    _find_word_boundary,
    _process_structured_data,
    _truncate,
)

# Try to import Rust implementation
try:
    from output_length_guard_rust.output_length_guard_rust import OutputLengthGuardEngine

    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    OutputLengthGuardEngine = None  # type: ignore
    print("Rust implementation not available. Build it with:")
    print("   cd plugins_rust/output_length_guard && make install")
    print()


# ── Test data generators ─────────────────────────────────────────────────────


def make_string(size: int) -> str:
    """Generate a realistic English-like string of approximately `size` chars."""
    words = "The quick brown fox jumps over the lazy dog and then runs across the wide green meadow ".split()
    parts: List[str] = []
    total = 0
    i = 0
    while total < size:
        w = words[i % len(words)]
        parts.append(w)
        total += len(w) + 1
        i += 1
    return " ".join(parts)[:size]


def make_list_of_strings(count: int, item_size: int) -> List[str]:
    """Generate a list of `count` strings, each ~`item_size` chars."""
    return [make_string(item_size) for _ in range(count)]


def make_nested_dict(depth: int, breadth: int, leaf_size: int) -> Dict[str, Any]:
    """Generate a nested dict structure."""
    if depth <= 0:
        return {"value": make_string(leaf_size)}
    return {f"key_{i}": make_nested_dict(depth - 1, breadth, leaf_size) for i in range(breadth)}


def make_config(**overrides) -> OutputLengthGuardConfig:
    """Create a config with sensible defaults for benchmarking."""
    defaults = {
        "min_chars": 0,
        "max_chars": 500,
        "strategy": "truncate",
        "ellipsis": "...",
        "word_boundary": False,
        "limit_mode": "character",
    }
    defaults.update(overrides)
    return OutputLengthGuardConfig(**defaults)


# ── Benchmark runners ─────────────────────────────────────────────────────────


def bench_python_truncate(data: str, cfg: OutputLengthGuardConfig, iterations: int, warmup: int) -> List[float]:
    """Benchmark Python _truncate on a single string."""
    for _ in range(warmup):
        _truncate(data, cfg.max_chars, cfg.ellipsis, cfg.word_boundary, limit_mode=cfg.limit_mode)

    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        _truncate(data, cfg.max_chars, cfg.ellipsis, cfg.word_boundary, limit_mode=cfg.limit_mode)
        times.append(time.perf_counter() - start)
    return times


def bench_rust_truncate(engine: Any, data: str, iterations: int, warmup: int) -> List[float]:
    """Benchmark Rust engine.truncate_string on a single string."""
    for _ in range(warmup):
        engine.truncate_string(data)

    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        engine.truncate_string(data)
        times.append(time.perf_counter() - start)
    return times


def bench_python_process(data: Any, cfg: OutputLengthGuardConfig, iterations: int, warmup: int) -> List[float]:
    """Benchmark Python _process_structured_data on a container."""
    ctx = Mock()
    for _ in range(warmup):
        _process_structured_data(
            data, cfg.min_chars, cfg.max_chars, cfg.ellipsis, cfg.strategy,
            cfg.word_boundary, ctx, "", cfg.min_tokens, cfg.max_tokens,
            cfg.chars_per_token, cfg.max_text_length, cfg.max_structure_size,
            cfg.max_recursion_depth, cfg.max_binary_search_iterations, cfg.limit_mode,
        )

    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        _process_structured_data(
            data, cfg.min_chars, cfg.max_chars, cfg.ellipsis, cfg.strategy,
            cfg.word_boundary, ctx, "", cfg.min_tokens, cfg.max_tokens,
            cfg.chars_per_token, cfg.max_text_length, cfg.max_structure_size,
            cfg.max_recursion_depth, cfg.max_binary_search_iterations, cfg.limit_mode,
        )
        times.append(time.perf_counter() - start)
    return times


def bench_rust_process(engine: Any, data: Any, iterations: int, warmup: int) -> List[float]:
    """Benchmark Rust engine.process on a container."""
    for _ in range(warmup):
        engine.process(data)

    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        engine.process(data)
        times.append(time.perf_counter() - start)
    return times


# ── Reporting ─────────────────────────────────────────────────────────────────


def report(name: str, py_times: List[float], rust_times: Optional[List[float]]):
    """Print benchmark results for a scenario."""
    py_mean = statistics.mean(py_times) * 1_000_000  # microseconds
    py_median = statistics.median(py_times) * 1_000_000
    py_stdev = statistics.stdev(py_times) * 1_000_000 if len(py_times) > 1 else 0

    print(f"\n{'─' * 70}")
    print(f"  {name}")
    print(f"{'─' * 70}")
    print(f"  Python:  {py_mean:>10.2f} us  (median {py_median:.2f}, stdev {py_stdev:.2f})")

    if rust_times:
        rust_mean = statistics.mean(rust_times) * 1_000_000
        rust_median = statistics.median(rust_times) * 1_000_000
        rust_stdev = statistics.stdev(rust_times) * 1_000_000 if len(rust_times) > 1 else 0
        speedup = py_mean / rust_mean if rust_mean > 0 else float("inf")

        print(f"  Rust:    {rust_mean:>10.2f} us  (median {rust_median:.2f}, stdev {rust_stdev:.2f})")
        if speedup >= 1:
            print(f"  Speedup: {speedup:>10.2f}x faster")
        else:
            print(f"  Speedup: {1/speedup:>10.2f}x slower")
    else:
        print("  Rust:    N/A")


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Output Length Guard: Python vs Rust performance comparison")
    parser.add_argument("--iterations", type=int, default=10000, help="Iterations per scenario (default: 10000)")
    parser.add_argument("--warmup", type=int, default=100, help="Warmup iterations (default: 100)")
    args = parser.parse_args()

    iters = args.iterations
    warmup = args.warmup

    print("Output Length Guard - Performance Comparison")
    print(f"Iterations: {iters} (+{warmup} warmup)")
    print(f"Rust available: {'yes' if RUST_AVAILABLE else 'no'}")

    # Create Rust engine instances for different configs
    rust_char_engine = None
    rust_token_engine = None
    rust_block_engine = None
    rust_wb_engine = None

    cfg_char = make_config(max_chars=500, limit_mode="character")
    cfg_token = make_config(max_tokens=50, chars_per_token=4, limit_mode="token")
    cfg_block = make_config(max_chars=500, strategy="block", limit_mode="character")
    cfg_wb = make_config(max_chars=500, word_boundary=True, limit_mode="character")

    if RUST_AVAILABLE:
        rust_char_engine = OutputLengthGuardEngine(cfg_char)
        rust_token_engine = OutputLengthGuardEngine(cfg_token)
        rust_block_engine = OutputLengthGuardEngine(cfg_block)
        rust_wb_engine = OutputLengthGuardEngine(cfg_wb)

    # ── Scenario 1: Single string truncation ──────────────────────────────

    print(f"\n{'=' * 70}")
    print("  SCENARIO GROUP 1: Single String Truncation (character mode)")
    print(f"{'=' * 70}")

    for label, size in [("1 KB", 1_000), ("10 KB", 10_000), ("100 KB", 100_000), ("1 MB", 1_000_000)]:
        text = make_string(size)
        py = bench_python_truncate(text, cfg_char, iters, warmup)
        rs = bench_rust_truncate(rust_char_engine, text, iters, warmup) if rust_char_engine else None
        report(f"String truncation ({label} -> 500 chars)", py, rs)

    # ── Scenario 2: Token-mode truncation with binary search ──────────────

    print(f"\n{'=' * 70}")
    print("  SCENARIO GROUP 2: Token-Mode Truncation (binary search)")
    print(f"{'=' * 70}")

    for label, size in [("1 KB", 1_000), ("10 KB", 10_000), ("100 KB", 100_000)]:
        text = make_string(size)
        py = bench_python_truncate(text, cfg_token, iters, warmup)
        rs = bench_rust_truncate(rust_token_engine, text, iters, warmup) if rust_token_engine else None
        report(f"Token truncation ({label} -> 50 tokens)", py, rs)

    # ── Scenario 3: Word-boundary truncation ──────────────────────────────

    print(f"\n{'=' * 70}")
    print("  SCENARIO GROUP 3: Word-Boundary Truncation")
    print(f"{'=' * 70}")

    for label, size in [("1 KB", 1_000), ("100 KB", 100_000)]:
        text = make_string(size)
        py = bench_python_truncate(text, cfg_wb, iters, warmup)
        rs = bench_rust_truncate(rust_wb_engine, text, iters, warmup) if rust_wb_engine else None
        report(f"Word-boundary truncation ({label})", py, rs)

    # ── Scenario 4: Container processing (list of strings) ───────────────

    print(f"\n{'=' * 70}")
    print("  SCENARIO GROUP 4: List of Strings")
    print(f"{'=' * 70}")

    for label, count, item_size in [("10 x 1KB", 10, 1_000), ("100 x 1KB", 100, 1_000), ("10 x 10KB", 10, 10_000)]:
        data = make_list_of_strings(count, item_size)
        py = bench_python_process(data, cfg_char, iters, warmup)
        rs = bench_rust_process(rust_char_engine, data, iters, warmup) if rust_char_engine else None
        report(f"List processing ({label})", py, rs)

    # ── Scenario 5: Nested dict processing ────────────────────────────────

    print(f"\n{'=' * 70}")
    print("  SCENARIO GROUP 5: Nested Dict Structures")
    print(f"{'=' * 70}")

    for label, depth, breadth, leaf in [("shallow (d=2, b=5)", 2, 5, 1_000), ("deep (d=5, b=3)", 5, 3, 500), ("wide (d=2, b=20)", 2, 20, 500)]:
        data = make_nested_dict(depth, breadth, leaf)
        py = bench_python_process(data, cfg_char, iters, warmup)
        rs = bench_rust_process(rust_char_engine, data, iters, warmup) if rust_char_engine else None
        report(f"Nested dict ({label})", py, rs)

    # ── Scenario 6: Block mode (violation detection) ──────────────────────

    print(f"\n{'=' * 70}")
    print("  SCENARIO GROUP 6: Block Mode (violation detection)")
    print(f"{'=' * 70}")

    for label, size in [("1 KB", 1_000), ("10 KB", 10_000)]:
        text = make_string(size)
        py = bench_python_process(text, cfg_block, iters, warmup)
        rs = bench_rust_process(rust_block_engine, text, iters, warmup) if rust_block_engine else None
        report(f"Block mode ({label})", py, rs)

    # ── Scenario 7: Under-limit passthrough (no modification) ─────────────

    print(f"\n{'=' * 70}")
    print("  SCENARIO GROUP 7: Under-Limit Passthrough (no-op)")
    print(f"{'=' * 70}")

    short_text = "Hello world"
    py = bench_python_process(short_text, cfg_char, iters, warmup)
    rs = bench_rust_process(rust_char_engine, short_text, iters, warmup) if rust_char_engine else None
    report("Short string passthrough (11 chars, max 500)", py, rs)

    short_list = ["Hello", "world", "foo", "bar"]
    py = bench_python_process(short_list, cfg_char, iters, warmup)
    rs = bench_rust_process(rust_char_engine, short_list, iters, warmup) if rust_char_engine else None
    report("Short list passthrough (4 items, all under limit)", py, rs)

    # ── Summary ───────────────────────────────────────────────────────────

    print(f"\n{'=' * 70}")
    print("  Benchmark complete")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
