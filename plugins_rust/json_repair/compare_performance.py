#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Performance comparison for json_repair (Python vs Rust).

This benchmark compares:
- Python implementation from ``plugins/json_repair/json_repair.py``
- Rust implementation exposed via PyO3 module ``json_repair``

Usage:
    python compare_performance.py
    python compare_performance.py --iteration-tiers 10,100,500,1000
    python compare_performance.py --iterations 1000 --warmup 30
"""

from __future__ import annotations

# Standard
import argparse
import asyncio
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
    payloads: list[str]


def _make_object_json(target_kb: int, repairable: bool, seed: int = 0) -> str:
    """Create deterministic object-like JSON-ish text around target size."""
    parts = []
    idx = 0
    current_len = 0
    target_len = target_kb * 1024

    while current_len < target_len:
        key = f"k{seed}_{idx}"
        if repairable:
            part = f"'{key}': 'value_{seed}_{idx}'"
        else:
            part = f'"{key}": "value_{seed}_{idx}"'

        # Account for comma separator for all but first part.
        current_len += len(part) + (1 if parts else 0)
        parts.append(part)
        idx += 1

    body = ",".join(parts)
    if repairable:
        return "{" + body + ",}"
    return "{" + body + "}"


def _build_payload_variants(target_kb: int, repairable: bool, variants: int) -> list[str]:
    """Create multiple payload variants with distinct keys to reduce parser key-cache effects."""
    return [_make_object_json(target_kb, repairable=repairable, seed=i) for i in range(variants)]


def generate_scenarios(payload_variants: int) -> list[Scenario]:
    """Build benchmark scenarios with realistic payload sizes."""
    if payload_variants < 1:
        raise ValueError("payload_variants must be >= 1")

    def _missing_braces_variant(i: int) -> str:
        return f'"a_{i}": {i + 1}, "b_{i}": {i + 2}'

    return [
        Scenario("small_valid_1kb", _build_payload_variants(1, repairable=False, variants=payload_variants)),
        Scenario("small_repairable_1kb", _build_payload_variants(1, repairable=True, variants=payload_variants)),
        Scenario("medium_valid_5kb", _build_payload_variants(5, repairable=False, variants=payload_variants)),
        Scenario("medium_repairable_5kb", _build_payload_variants(5, repairable=True, variants=payload_variants)),
        Scenario("large_valid_50kb", _build_payload_variants(50, repairable=False, variants=payload_variants)),
        Scenario("large_repairable_50kb", _build_payload_variants(50, repairable=True, variants=payload_variants)),
        Scenario("xlarge_valid_500kb", _build_payload_variants(500, repairable=False, variants=payload_variants)),
        Scenario("xlarge_repairable_500kb", _build_payload_variants(500, repairable=True, variants=payload_variants)),
        Scenario("xxlarge_valid_1024kb", _build_payload_variants(1024, repairable=False, variants=payload_variants)),
        Scenario("xxlarge_repairable_1024kb", _build_payload_variants(1024, repairable=True, variants=payload_variants)),
        Scenario("unrepairable_text", [f"not-json-at-all {i} " * 200 for i in range(payload_variants)]),
        Scenario("missing_braces", [_missing_braces_variant(i) for i in range(payload_variants)]),
    ]


def benchmark_python(payloads: list[str], iterations: int, warmup: int) -> tuple[list[float], str | None]:
    """Benchmark Python core repair function."""
    for i in range(warmup):
        payload = payloads[i % len(payloads)]
        PY_IMPL._repair(payload)

    times: list[float] = []
    output: str | None = None
    for i in range(iterations):
        payload = payloads[i % len(payloads)]
        start = time.perf_counter()
        output = PY_IMPL._repair(payload)
        times.append(time.perf_counter() - start)
    return times, output


def benchmark_rust(payloads: list[str], iterations: int, warmup: int, rust_repair: Callable[[str], str | None]) -> tuple[list[float], str | None]:
    """Benchmark Rust core repair function."""
    for i in range(warmup):
        payload = payloads[i % len(payloads)]
        rust_repair(payload)

    times: list[float] = []
    output: str | None = None
    for i in range(iterations):
        payload = payloads[i % len(payloads)]
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


def _build_hook_runner(use_rust: bool):
    """Build async runner for full plugin hook path."""
    # First-Party
    from mcpgateway.plugins.framework import (
        GlobalContext,
        PluginConfig,
        PluginContext,
        ToolHookType,
        ToolPostInvokePayload,
    )

    original_rust_available = getattr(PY_IMPL, "_RUST_AVAILABLE", False)
    original_rust_cls = getattr(PY_IMPL, "JSONRepairPluginRust", None)

    if not use_rust:
        setattr(PY_IMPL, "_RUST_AVAILABLE", False)
        setattr(PY_IMPL, "JSONRepairPluginRust", None)

    try:
        plugin_config = PluginConfig(
            name="json_repair_bench",
            kind="plugins.json_repair.json_repair.JSONRepairPlugin",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
        )
        plugin = PY_IMPL.JSONRepairPlugin(plugin_config)
    finally:
        # Restore module globals after plugin construction.
        setattr(PY_IMPL, "_RUST_AVAILABLE", original_rust_available)
        setattr(PY_IMPL, "JSONRepairPluginRust", original_rust_cls)

    plugin_ctx = PluginContext(global_context=GlobalContext(request_id="json-repair-bench"))

    async def _run(text: str) -> str | None:
        payload = ToolPostInvokePayload(name="x", result=text)
        result = await plugin.tool_post_invoke(payload, plugin_ctx)
        if result.modified_payload is None:
            return None
        return result.modified_payload.result

    return _run


async def _benchmark_hook(payloads: list[str], iterations: int, warmup: int, hook_runner: Callable[[str], "asyncio.Future[str | None]"]) -> tuple[list[float], str | None]:
    """Benchmark full tool_post_invoke hook path."""
    for i in range(warmup):
        payload = payloads[i % len(payloads)]
        await hook_runner(payload)

    times: list[float] = []
    output: str | None = None
    for i in range(iterations):
        payload = payloads[i % len(payloads)]
        start = time.perf_counter()
        output = await hook_runner(payload)
        times.append(time.perf_counter() - start)
    return times, output


def _default_warmup_for_iterations(iterations: int) -> int:
    """Choose practical warmup counts per iteration tier."""
    tier_defaults = {10: 5, 100: 10, 500: 20, 1000: 30}
    if iterations in tier_defaults:
        return tier_defaults[iterations]
    return max(5, min(100, iterations // 20))


def _parse_iteration_tiers(raw: str) -> list[int]:
    """Parse a comma-separated iteration tier list."""
    tiers: list[int] = []
    for token in raw.split(","):
        value = token.strip()
        if not value:
            continue
        parsed = int(value)
        if parsed <= 0:
            raise ValueError("iteration tiers must be positive integers")
        if parsed not in tiers:
            tiers.append(parsed)
    if not tiers:
        raise ValueError("iteration tiers cannot be empty")
    return tiers


def run_scenario(scenario: Scenario, iterations: int, warmup: int, rust_repair: Callable[[str], str | None] | None) -> None:
    """Run benchmark scenario for both core and full-hook modes."""
    print("\n" + "=" * 72)
    print(f"Scenario: {scenario.name}")
    print("=" * 72)

    # Core mode: direct repair path.
    py_core_times, py_core_output = benchmark_python(scenario.payloads, iterations, warmup)
    py_core_mean, py_core_median, py_core_stdev = _summarize(py_core_times)

    rust_core_mean = rust_core_median = rust_core_stdev = 0.0
    rust_core_output: str | None = None
    if rust_repair is not None:
        rust_core_times, rust_core_output = benchmark_rust(scenario.payloads, iterations, warmup, rust_repair)
        rust_core_mean, rust_core_median, rust_core_stdev = _summarize(rust_core_times)

    # Hook mode: full tool_post_invoke path.
    py_hook_runner = _build_hook_runner(use_rust=False)
    py_hook_times, py_hook_output = asyncio.run(_benchmark_hook(scenario.payloads, iterations, warmup, py_hook_runner))
    py_hook_mean, py_hook_median, py_hook_stdev = _summarize(py_hook_times)

    rust_hook_mean = rust_hook_median = rust_hook_stdev = 0.0
    rust_hook_output: str | None = None
    if rust_repair is not None:
        rust_hook_runner = _build_hook_runner(use_rust=True)
        rust_hook_times, rust_hook_output = asyncio.run(_benchmark_hook(scenario.payloads, iterations, warmup, rust_hook_runner))
        rust_hook_mean, rust_hook_median, rust_hook_stdev = _summarize(rust_hook_times)

    print("Mode: core (direct repair)")
    print(f"  Python: {py_core_mean:.3f} ms ±{py_core_stdev:.3f} (median: {py_core_median:.3f})")
    if rust_repair is None:
        print("  Rust: not available")
    else:
        core_speedup = py_core_mean / rust_core_mean if rust_core_mean > 0 else 0.0
        print(f"  Rust:   {rust_core_mean:.3f} ms ±{rust_core_stdev:.3f} (median: {rust_core_median:.3f})")
        print(f"  Speedup (core): {core_speedup:.2f}x")

    print("Mode: hook (tool_post_invoke end-to-end)")
    print(f"  Python: {py_hook_mean:.3f} ms ±{py_hook_stdev:.3f} (median: {py_hook_median:.3f})")
    if rust_repair is None:
        print("  Rust: not available")
    else:
        hook_speedup = py_hook_mean / rust_hook_mean if rust_hook_mean > 0 else 0.0
        print(f"  Rust:   {rust_hook_mean:.3f} ms ±{rust_hook_stdev:.3f} (median: {rust_hook_median:.3f})")
        print(f"  Speedup (hook): {hook_speedup:.2f}x")

    # Performance difference between modes for each implementation.
    py_mode_ratio = py_hook_mean / py_core_mean if py_core_mean > 0 else 0.0
    print(f"Mode overhead: Python hook/core = {py_mode_ratio:.2f}x")
    if rust_repair is not None:
        rust_mode_ratio = rust_hook_mean / rust_core_mean if rust_core_mean > 0 else 0.0
        print(f"Mode overhead: Rust   hook/core = {rust_mode_ratio:.2f}x")

    # Output parity checks.
    py_core_norm = _canonical_json(py_core_output)
    py_hook_norm = _canonical_json(py_hook_output)
    if py_core_norm != py_hook_norm:
        print("WARNING: Python core vs hook output mismatch")

    if rust_repair is not None:
        rust_core_norm = _canonical_json(rust_core_output)
        rust_hook_norm = _canonical_json(rust_hook_output)
        if rust_core_norm != rust_hook_norm:
            print("WARNING: Rust core vs hook output mismatch")

        if py_core_norm != rust_core_norm:
            print("WARNING: Python vs Rust output mismatch (core mode)")
        if py_hook_norm != rust_hook_norm:
            print("WARNING: Python vs Rust output mismatch (hook mode)")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="json_repair Python vs Rust benchmark")
    parser.add_argument("--iteration-tiers", type=str, default="10,100,500,1000", help="Comma-separated iteration tiers (PII-style multi-run benchmark).")
    parser.add_argument("--iterations", type=int, default=None, help="Single-run override for iterations per scenario.")
    parser.add_argument("--warmup", type=int, default=None, help="Single-run override for warmup iterations per scenario.")
    parser.add_argument(
        "--payload-variants",
        type=int,
        default=32,
        help="Number of distinct payload variants to rotate per scenario (1 keeps the original same-input loop).",
    )
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

    if args.iterations is not None:
        if args.iterations <= 0:
            raise ValueError("--iterations must be a positive integer")
        warmup = args.warmup if args.warmup is not None else _default_warmup_for_iterations(args.iterations)
        if warmup < 0:
            raise ValueError("--warmup must be >= 0")
        run_profiles = [(args.iterations, warmup)]
        profile_label = "single-run override"
    else:
        tiers = _parse_iteration_tiers(args.iteration_tiers)
        run_profiles = [(iters, _default_warmup_for_iterations(iters)) for iters in tiers]
        profile_label = "tiered run"

    print("JSON Repair Performance Comparison")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Rust available: {'yes' if rust_repair is not None else 'no'}")
    print(f"Profile mode: {profile_label}")
    print(f"Payload variants per scenario: {args.payload_variants}")

    scenarios = generate_scenarios(args.payload_variants)
    for iterations, warmup in run_profiles:
        print("\n" + "#" * 72)
        print(f"Profile: iterations={iterations}, warmup={warmup}")
        print("#" * 72)
        for scenario in scenarios:
            run_scenario(scenario, iterations, warmup, rust_repair)

    print("\n" + "=" * 72)
    print("Benchmark complete")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
