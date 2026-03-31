#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Performance comparison: Rust vs Python for retry_with_backoff plugin.

This benchmark provides a fair apples-to-apples comparison by using native
Python objects for both implementations, eliminating JSON serialization overhead.

Measurements:
- Python (native): Baseline Python implementation
- Rust (native): High-performance Rust implementation via PyO3

Usage:
    python compare_performance.py
    python compare_performance.py --iterations 10000 --warmup 100
"""

import argparse
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Import Rust implementation
# ---------------------------------------------------------------------------
try:
    from retry_with_backoff_rust.retry_with_backoff_rust import (
        RetryStateManager as RustRetryStateManager,
    )

    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    RustRetryStateManager = None
    print("⚠️  Rust implementation not available. Build it with:")
    print("   cd plugins_rust/retry_with_backoff && make install")
    print()

# ---------------------------------------------------------------------------
# Import Python implementation
# ---------------------------------------------------------------------------
plugins_path = Path(__file__).parent.parent.parent / "plugins" / "retry_with_backoff"
if plugins_path.exists():
    sys.path.insert(0, str(plugins_path))
    mcpgateway_path = Path(__file__).parent.parent.parent / "mcpgateway"
    if mcpgateway_path.exists():
        sys.path.insert(0, str(mcpgateway_path))
else:
    print(f"⚠️  Warning: Python implementation path not found: {plugins_path}")
    print()

try:
    from retry_with_backoff import (
        RetryConfig,
        _ToolRetryState,
        _compute_delay_ms,
        _del_state,
        _get_state,
        _is_failure,
    )

    PYTHON_AVAILABLE = True
except ImportError as e:
    PYTHON_AVAILABLE = False
    print(f"⚠️  Python implementation not available: {e}")
    print("   Make sure pydantic is installed: uv pip install pydantic")
    print()


# ---------------------------------------------------------------------------
# Python fallback implementation (mirrors Rust logic)
# ---------------------------------------------------------------------------


class PythonRetryStateManager:
    """Python implementation mirroring Rust RetryStateManager API."""

    def __init__(
        self,
        max_retries: int,
        base_ms: int,
        max_ms: int,
        jitter: bool,
        retry_on_status: List[int],
    ):
        self.max_retries = max_retries
        self.base_ms = base_ms
        self.max_ms = max_ms
        self.jitter = jitter
        self.retry_on_status = set(retry_on_status)
        self._state: Dict[str, _ToolRetryState] = {}

    def _make_key(self, tool: str, request_id: str) -> str:
        return f"{tool}:{request_id}"

    def check_and_update(
        self,
        tool: str,
        request_id: str,
        is_error: bool,
        status_code: Optional[int],
    ) -> Tuple[bool, int]:
        """Check failure and update state, returning (should_retry, delay_ms)."""
        failed = is_error or (status_code is not None and status_code in self.retry_on_status)

        key = self._make_key(tool, request_id)

        if failed:
            state = self._state.get(key)
            if state is None:
                state = _ToolRetryState()
                self._state[key] = state

            state.consecutive_failures += 1
            state.last_failure_at = time.monotonic()

            if state.consecutive_failures <= self.max_retries:
                attempt = state.consecutive_failures - 1
                delay = _compute_delay_ms(
                    attempt,
                    RetryConfig(
                        max_retries=self.max_retries,
                        backoff_base_ms=self.base_ms,
                        max_backoff_ms=self.max_ms,
                        jitter=self.jitter,
                        retry_on_status=list(self.retry_on_status),
                    ),
                )
                return (True, delay)
            else:
                self._del_state(tool, request_id)
                return (False, 0)
        else:
            self._del_state(tool, request_id)
            return (False, 0)

    def _del_state(self, tool: str, request_id: str) -> None:
        key = self._make_key(tool, request_id)
        self._state.pop(key, None)


# ---------------------------------------------------------------------------
# Benchmark functions
# ---------------------------------------------------------------------------


def benchmark_implementation(
    impl: Any,
    tool_names: List[str],
    request_ids: List[str],
    failure_rate: float,
    iterations: int,
    warmup: int = 5,
) -> Tuple[List[float], int]:
    """Benchmark an implementation (Python or Rust).

    Args:
        impl: RetryStateManager instance (Python or Rust)
        tool_names: List of tool names to simulate
        request_ids: List of request IDs to simulate
        failure_rate: Fraction of calls that should fail (0.0-1.0)
        iterations: Number of benchmark iterations
        warmup: Number of warmup iterations

    Returns:
        Tuple of (list of times in seconds, retry count)
    """
    # Warmup phase
    for _ in range(warmup):
        for tool in tool_names[:3]:
            for req_id in request_ids[:3]:
                is_error = random.random() < failure_rate
                status_code = 503 if is_error and random.random() < 0.7 else None
                impl.check_and_update(tool, req_id, is_error, status_code)

    # Benchmark phase
    times = []
    retry_count = 0

    random.seed(42)  # Reproducible results

    for _ in range(iterations):
        start = time.perf_counter()

        for tool in tool_names:
            for req_id in request_ids:
                is_error = random.random() < failure_rate
                if is_error:
                    status_code = 503 if random.random() < 0.7 else None
                else:
                    status_code = None

                should_retry, _ = impl.check_and_update(tool, req_id, is_error, status_code)
                if should_retry:
                    retry_count += 1

        times.append(time.perf_counter() - start)

    return times, retry_count


def run_load_scenario(
    name: str,
    tool_count: int,
    request_count: int,
    failure_rate: float,
    iterations: int,
    warmup: int,
) -> Optional[Dict[str, Any]]:
    """Run load-based benchmark scenario.

    Returns:
        Dictionary with scenario results, or None if benchmark failed.
    """
    print(f"\n{'=' * 70}")
    print(f"Scenario: {name}")
    print(f"  Tools: {tool_count}, Requests: {request_count}, Failure rate: {failure_rate:.0%}")
    print(f"{'=' * 70}")

    tool_names = [f"tool_{i}" for i in range(tool_count)]
    request_ids = [f"req_{i}" for i in range(request_count)]

    config = {
        "max_retries": 3,
        "base_ms": 100,
        "max_ms": 5000,
        "jitter": False,  # Disabled for consistent measurements
        "retry_on_status": [429, 500, 502, 503, 504],
    }

    results = {}

    # Benchmark Python
    if PYTHON_AVAILABLE:
        print("Running Python...", end=" ", flush=True)
        py_impl = PythonRetryStateManager(**config)
        py_times, py_retries = benchmark_implementation(py_impl, tool_names, request_ids, failure_rate, iterations, warmup)
        py_mean = statistics.mean(py_times) * 1_000_000  # Convert to microseconds
        py_median = statistics.median(py_times) * 1_000_000
        py_stdev = statistics.stdev(py_times) * 1_000_000 if len(py_times) > 1 else 0
        results["python"] = {
            "mean": py_mean,
            "median": py_median,
            "stdev": py_stdev,
            "retries": py_retries,
        }
        print(f"✓ ({py_mean:.3f} µs/iter, {py_retries} retries)")
    else:
        print("Running Python... ✗ (not available)")

    # Benchmark Rust
    if RUST_AVAILABLE:
        print("Running Rust...", end=" ", flush=True)
        rust_impl = RustRetryStateManager(**config)
        rust_times, rust_retries = benchmark_implementation(rust_impl, tool_names, request_ids, failure_rate, iterations, warmup)
        rust_mean = statistics.mean(rust_times) * 1_000_000  # Convert to microseconds
        rust_median = statistics.median(rust_times) * 1_000_000
        rust_stdev = statistics.stdev(rust_times) * 1_000_000 if len(rust_times) > 1 else 0
        results["rust"] = {
            "mean": rust_mean,
            "median": rust_median,
            "stdev": rust_stdev,
            "retries": rust_retries,
        }
        print(f"✓ ({rust_mean:.3f} µs/iter, {rust_retries} retries)")
    else:
        print("Running Rust... ✗ (not available)")

    # Calculate and display results
    print("\n📊 Results:")

    if "python" in results:
        py = results["python"]
        print(f"  Python: {py['mean']:>10.3f} µs ±{py['stdev']:>8.3f} (median: {py['median']:>10.3f})")

    if "rust" in results:
        rust = results["rust"]
        print(f"  Rust:   {rust['mean']:>10.3f} µs ±{rust['stdev']:>8.3f} (median: {rust['median']:>10.3f})")

    speedup = None
    if "python" in results and "rust" in results:
        speedup = py_mean / rust_mean if rust_mean > 0 else 0
        print(f"\n  🚀 Speedup: {speedup:.2f}x faster with Rust")

        if abs(py_retries - rust_retries) > py_retries * 0.01:
            print(f"\n  ⚠️  WARNING: Different retry counts! Python={py_retries}, Rust={rust_retries}")
        else:
            print(f"  ✓ Retry counts match (Python={py_retries}, Rust={rust_retries})")

    return {
        "name": name,
        "type": "load",
        "config": {"tools": tool_count, "requests": request_count, "failure_rate": failure_rate},
        "python": results.get("python"),
        "rust": results.get("rust"),
        "speedup": speedup,
    }


def reset_state():
    """Reset Python state between benchmarks."""
    if PYTHON_AVAILABLE:
        from retry_with_backoff import _STATE

        _STATE.clear()


def benchmark_sequential(
    impl_name: str,
    calls: List[Dict[str, Any]],
    config: RetryConfig,
    rust_mgr: Optional[Any] = None,
    warmup: int = 5,
) -> Tuple[List[float], int]:
    """Benchmark sequential call pattern (original compare_performance.py style)."""
    reset_state()

    times = []
    retry_count = 0
    tool = "test_tool"

    # Warmup
    for i in range(warmup):
        if impl_name == "python":
            _get_state(tool, f"warmup_{i}")
            _del_state(tool, f"warmup_{i}")
        else:
            pass  # Rust handles state internally

    for i, call in enumerate(calls):
        req_id = f"seq_{i}"
        start = time.perf_counter()

        if impl_name == "python":
            result = {"isError": call["is_error"], "content": [], "structuredContent": None}
            if call["status_code"] is not None:
                result["structuredContent"] = {"status_code": call["status_code"]}

            st = _get_state(tool, req_id)
            if _is_failure(result, config):
                st.consecutive_failures += 1
                if st.consecutive_failures <= config.max_retries:
                    _compute_delay_ms(st.consecutive_failures - 1, config)
                    retry_count += 1
                    _del_state(tool, req_id)
                else:
                    _del_state(tool, req_id)
            else:
                _del_state(tool, req_id)
        else:
            # Rust
            should_retry, _ = rust_mgr.check_and_update(tool, req_id, call["is_error"], call["status_code"])
            if should_retry:
                retry_count += 1

        times.append(time.perf_counter() - start)

    return times, retry_count


def run_sequential_scenario(
    name: str,
    calls: List[Dict[str, Any]],
    config: RetryConfig,
    warmup: int,
) -> Optional[Dict[str, Any]]:
    """Run sequential call pattern scenario.

    Returns:
        Dictionary with scenario results, or None if benchmark failed.
    """
    print(f"\n{'=' * 70}")
    print(f"Scenario: {name}")
    print(f"{'=' * 70}")

    results = {}

    # Python
    if PYTHON_AVAILABLE:
        print("Running Python...", end=" ", flush=True)
        py_times, py_count = benchmark_sequential("python", calls, config, warmup)
        py_mean = statistics.mean(py_times) * 1_000_000
        py_median = statistics.median(py_times) * 1_000_000
        py_stdev = statistics.stdev(py_times) * 1_000_000 if len(py_times) > 1 else 0
        results["python"] = {
            "mean": py_mean,
            "median": py_median,
            "stdev": py_stdev,
            "retries": py_count,
        }
        print(f"✓ ({py_mean:.3f} µs/call, {py_count} retries)")
    else:
        print("Running Python... ✗ (not available)")

    # Rust
    if RUST_AVAILABLE:
        rust_mgr = RustRetryStateManager(
            config.max_retries,
            config.backoff_base_ms,
            config.max_backoff_ms,
            config.jitter,
            config.retry_on_status,
        )
        print("Running Rust...", end=" ", flush=True)
        rust_times, rust_count = benchmark_sequential("rust", calls, config, rust_mgr=rust_mgr, warmup=warmup)
        rust_mean = statistics.mean(rust_times) * 1_000_000
        rust_median = statistics.median(rust_times) * 1_000_000
        rust_stdev = statistics.stdev(rust_times) * 1_000_000 if len(rust_times) > 1 else 0
        results["rust"] = {
            "mean": rust_mean,
            "median": rust_median,
            "stdev": rust_stdev,
            "retries": rust_count,
        }
        print(f"✓ ({rust_mean:.3f} µs/call, {rust_count} retries)")
    else:
        print("Running Rust... ✗ (not available)")

    print("\n📊 Results:")
    if "python" in results:
        py = results["python"]
        print(f"  Python: {py['mean']:>10.3f} µs ±{py['stdev']:>8.3f} (median: {py['median']:>10.3f})")
    if "rust" in results:
        rust = results["rust"]
        print(f"  Rust:   {rust['mean']:>10.3f} µs ±{rust['stdev']:>8.3f} (median: {rust['median']:>10.3f})")

    speedup = None
    if "python" in results and "rust" in results:
        speedup = py_mean / rust_mean if rust_mean > 0 else 0
        print(f"\n  🚀 Speedup: {speedup:.2f}x faster with Rust")
        if py_count != rust_count:
            print(f"\n  ⚠️  WARNING: Different retry counts! Python={py_count}, Rust={rust_count}")

    return {
        "name": name,
        "type": "sequential",
        "python": results.get("python"),
        "rust": results.get("rust"),
        "speedup": speedup,
    }


def generate_sequential_scenarios(iterations: int) -> List[Dict[str, Any]]:
    """Generate sequential test scenarios with different failure patterns."""
    scenarios = []

    scenarios.append(
        {
            "name": "All successes",
            "calls": [{"is_error": False, "status_code": None} for _ in range(iterations)],
        }
    )

    scenarios.append(
        {
            "name": "All failures (exhaust)",
            "calls": [{"is_error": True, "status_code": None} for _ in range(iterations)],
        }
    )

    scenarios.append(
        {
            "name": "Mixed (50/50)",
            "calls": [{"is_error": (i % 2 == 0), "status_code": None} for i in range(iterations)],
        }
    )

    scenarios.append(
        {
            "name": "Rate limiting (429)",
            "calls": [{"is_error": False, "status_code": 429 if i % 3 == 0 else 200} for i in range(iterations)],
        }
    )

    scenarios.append(
        {
            "name": "Server errors",
            "calls": [
                {
                    "is_error": False,
                    "status_code": [500, 502, 503][i % 3] if i % 4 != 0 else 200,
                }
                for i in range(iterations)
            ],
        }
    )

    return scenarios


def main():
    """Run performance comparison benchmarks."""
    parser = argparse.ArgumentParser(description="Rust vs Python performance comparison for retry_with_backoff")
    parser.add_argument(
        "--iterations",
        type=int,
        default=10000,
        help="Benchmark iterations per scenario",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=100,
        help="Warmup iterations",
    )
    args = parser.parse_args()

    print("🔄 Retry With Backoff Performance Comparison")
    print(f"{'=' * 70}")
    print(f"Iterations: {args.iterations} (+ {args.warmup} warmup)")
    print(f"Rust available: {'✓' if RUST_AVAILABLE else '✗'}")
    print(f"Python available: {'✓' if PYTHON_AVAILABLE else '✗'}")

    if not RUST_AVAILABLE and not PYTHON_AVAILABLE:
        print("\n❌ Error: Neither implementation is available!")
        print("   Install at least one implementation to run benchmarks.")
        sys.exit(1)

    config = RetryConfig(
        max_retries=3,
        backoff_base_ms=200,
        max_backoff_ms=5000,
        jitter=False,
        retry_on_status=[429, 500, 502, 503, 504],
    )

    all_results: List[Dict[str, Any]] = []

    print("\n" + "=" * 70)
    print("PART 1: Sequential Call Patterns (per-call overhead)")
    print("=" * 70)

    sequential_scenarios = generate_sequential_scenarios(min(args.iterations, 1000))
    for scenario in sequential_scenarios:
        result = run_sequential_scenario(
            scenario["name"],
            scenario["calls"],
            config,
            args.warmup,
        )
        if result:
            all_results.append(result)

    print("\n" + "=" * 70)
    print("PART 2: Concurrent Load Patterns (batch throughput)")
    print("=" * 70)

    load_scenarios = [
        ("Low load (1 tool, 10 reqs, 10% fail)", 1, 10, 0.1),
        ("Medium load (5 tools, 50 reqs, 30% fail)", 5, 50, 0.3),
        ("High load (10 tools, 100 reqs, 50% fail)", 10, 100, 0.5),
        ("Stress test (20 tools, 200 reqs, 70% fail)", 20, 200, 0.7),
    ]

    for name, tool_count, request_count, failure_rate in load_scenarios:
        result = run_load_scenario(
            name,
            tool_count,
            request_count,
            failure_rate,
            args.iterations,
            args.warmup,
        )
        if result:
            all_results.append(result)

    # Display summary
    print(f"\n{'=' * 70}")
    print("📊 PERFORMANCE SUMMARY")
    print(f"{'=' * 70}")

    if all_results:
        # Calculate overall statistics
        speedups = [r["speedup"] for r in all_results if r["speedup"] is not None]

        if speedups:
            avg_speedup = statistics.mean(speedups)
            min_speedup = min(speedups)
            max_speedup = max(speedups)

            print("\n🚀 Rust Speedup Overview:")
            print(f"  Average: {avg_speedup:.2f}x faster")
            print(f"  Min:     {min_speedup:.2f}x faster")
            print(f"  Max:     {max_speedup:.2f}x faster")

        # Per-scenario breakdown
        print("\n📈 Scenario Breakdown:")
        print(f"{'Scenario':<45} {'Python (µs)':>14} {'Rust (µs)':>12} {'Speedup':>10}")
        print(f"{'-' * 45} {'-' * 14} {'-' * 12} {'-' * 10}")

        for result in all_results:
            name = result["name"][:44]
            py_time = result["python"]["mean"] if result["python"] else float("inf")
            rust_time = result["rust"]["mean"] if result["rust"] else float("inf")
            speedup = result["speedup"] if result["speedup"] else float("inf")

            py_str = f"{py_time:>14.3f}" if py_time != float("inf") else "N/A"
            rust_str = f"{rust_time:>12.3f}" if rust_time != float("inf") else "N/A"
            speedup_str = f"{speedup:>10.2f}x" if speedup != float("inf") else "N/A"

            print(f"{name:<45} {py_str:>14} {rust_str:>12} {speedup_str:>10}")

        # Overall recommendation
        print("\n💡 Recommendation:")
        if speedups:
            if avg_speedup >= 2.0:
                print("   Rust implementation provides significant performance benefits")
                print(f"   ({avg_speedup:.1f}x average speedup). Recommended for production.")
            elif avg_speedup >= 1.5:
                print(f"   Rust implementation offers moderate speedup ({avg_speedup:.1f}x).")
                print("   Consider using for high-throughput scenarios.")
            else:
                print(f"   Rust implementation shows marginal improvement ({avg_speedup:.1f}x).")
                print("   Python may be sufficient for low-load use cases.")

    print(f"\n{'=' * 70}")
    print("✅ Benchmark complete!")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
