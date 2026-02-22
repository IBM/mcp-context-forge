#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Performance comparison for json_repair (Python vs Rust).

This benchmark compares:
- Python implementation from ``plugins/json_repair/json_repair.py``
- Rust implementation exposed via PyO3 module ``json_repair``

Usage:
    python compare_performance.py
    python compare_performance.py --iterations 10000 --warmup 200
"""

from __future__ import annotations

# Standard
import argparse
import importlib.util
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Third-Party
import orjson


def _load_python_impl():
    """Load the Python json_repair implementation by file path.

    Loaded by path to avoid a name conflict with the Rust extension module,
    which is also imported as ``json_repair``.
    """
    py_file = Path(__file__).parent.parent.parent / "plugins" / "json_repair" / "json_repair.py"
    spec = importlib.util.spec_from_file_location("python_json_repair_impl", py_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load Python implementation from {py_file}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PY_IMPL = _load_python_impl()

# Try to import Rust implementation.
try:
    from json_repair import JSONRepairPluginRust

    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    JSONRepairPluginRust = None  # type: ignore
    print("WARNING: Rust implementation not available. Build it with:")
    print("  cd plugins_rust/json_repair && maturin develop --release")
    print()


@dataclass(frozen=True)
class Scenario:
    """Single benchmark scenario."""

    name: str
    payload: str


def _make_object_json(target_kb: int, repairable: bool) -> str:
    """Create deterministic object-like JSON-ish text around target size."""
    parts = []
    idx = 0
    while len(",".join(parts)) < target_kb * 1024:
        if repairable:
            parts.append(f"'k{idx}': 'value_{idx}'")
        else:
            parts.append(f'"k{idx}": "value_{idx}"')
        idx += 1

    body = ",".join(parts)
    if repairable:
        return "{" + body + ",}"
    return "{" + body + "}"


def generate_scenarios() -> list[Scenario]:
    """Build benchmark scenarios with realistic payload sizes."""
    return [
        Scenario("small_valid_1kb", _make_object_json(1, repairable=False)),
        Scenario("small_repairable_1kb", _make_object_json(1, repairable=True)),
        Scenario("medium_valid_5kb", _make_object_json(5, repairable=False)),
        Scenario("medium_repairable_5kb", _make_object_json(5, repairable=True)),
        Scenario("large_valid_50kb", _make_object_json(50, repairable=False)),
        Scenario("large_repairable_50kb", _make_object_json(50, repairable=True)),
        Scenario("xlarge_valid_500kb", _make_object_json(500, repairable=False)),
        Scenario("xlarge_repairable_500kb", _make_object_json(500, repairable=True)),
        Scenario("xxlarge_valid_1024kb", _make_object_json(1024, repairable=False)),
        Scenario("xxlarge_repairable_1024kb", _make_object_json(1024, repairable=True)),
        Scenario("unrepairable_text", "not-json-at-all " * 200),
        Scenario("missing_braces", '"a": 1, "b": 2'),
    ]


def benchmark_python(payload: str, iterations: int, warmup: int) -> tuple[list[float], str | None]:
    """Benchmark Python repair function."""
    for _ in range(warmup):
        PY_IMPL._repair(payload)

    times: list[float] = []
    output: str | None = None
    for _ in range(iterations):
        start = time.perf_counter()
        output = PY_IMPL._repair(payload)
        times.append(time.perf_counter() - start)
    return times, output


def benchmark_rust(payload: str, iterations: int, warmup: int, rust_repair: Callable[[str], str | None]) -> tuple[list[float], str | None]:
    """Benchmark Rust repair function."""
    for _ in range(warmup):
        rust_repair(payload)

    times: list[float] = []
    output: str | None = None
    for _ in range(iterations):
        start = time.perf_counter()
        output = rust_repair(payload)
        times.append(time.perf_counter() - start)
    return times, output


def _summarize(times: list[float]) -> tuple[float, float, float]:
    """Calculate mean, median, and standard deviation in milliseconds."""
    mean_ms = statistics.mean(times) * 1000
    median_ms = statistics.median(times) * 1000
    stdev_ms = statistics.stdev(times) * 1000 if len(times) > 1 else 0.0
    return mean_ms, median_ms, stdev_ms


def _canonical_json(s: str | None):
    """Parse JSON for semantic comparison, ignoring string formatting differences."""
    if s is None:
        return None
    return orjson.loads(s)


def run_scenario(scenario: Scenario, iterations: int, warmup: int, rust_repair: Callable[[str], str | None] | None) -> None:
    """Run benchmark for one scenario and print results."""
    print("\n" + "=" * 72)
    print(f"Scenario: {scenario.name}")
    print("=" * 72)

    py_times, py_output = benchmark_python(scenario.payload, iterations, warmup)
    py_mean, py_median, py_stdev = _summarize(py_times)
    print(f"Python: {py_mean:.3f} ms ±{py_stdev:.3f} (median: {py_median:.3f})")

    if rust_repair is None:
        print("Rust: not available")
        return

    rust_times, rust_output = benchmark_rust(scenario.payload, iterations, warmup, rust_repair)
    rust_mean, rust_median, rust_stdev = _summarize(rust_times)
    speedup = py_mean / rust_mean if rust_mean > 0 else 0.0
    print(f"Rust:   {rust_mean:.3f} ms ±{rust_stdev:.3f} (median: {rust_median:.3f})")
    print(f"Speedup: {speedup:.2f}x")

    py_norm = _canonical_json(py_output)
    rust_norm = _canonical_json(rust_output)
    if py_norm != rust_norm:
        print("WARNING: output mismatch between Python and Rust implementations")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="json_repair Python vs Rust benchmark")
    parser.add_argument("--iterations", type=int, default=10000, help="Iterations per scenario")
    parser.add_argument("--warmup", type=int, default=100, help="Warmup iterations per scenario")
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint."""
    args = parse_args()

    rust_repair = None
    if RUST_AVAILABLE and JSONRepairPluginRust is not None:
        try:
            rust_repair = JSONRepairPluginRust().repair
        except Exception as exc:
            print(f"WARNING: Failed to initialize Rust helper: {exc}")

    print("JSON Repair Performance Comparison")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Rust available: {'yes' if rust_repair is not None else 'no'}")
    print(f"Iterations: {args.iterations} (+{args.warmup} warmup)")

    for scenario in generate_scenarios():
        run_scenario(scenario, args.iterations, args.warmup, rust_repair)

    print("\n" + "=" * 72)
    print("Benchmark complete")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
