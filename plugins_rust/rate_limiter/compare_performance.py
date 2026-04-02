#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare Python and Rust rate limiter hook performance.

This benchmark measures the real plugin hook path, not just the raw Rust engine.
It mirrors the comparison style used by other Rust plugins in this repository by
reporting Python-vs-Rust timings in ms/iteration for the same hook inputs.

Design choices for fairness:
- use fresh identities per iteration (latency mode) so counters do not
  accumulate differently between implementations
- compare the same hook (`prompt_pre_fetch` / `tool_pre_invoke`) with the same
  plugin config, only toggling whether the Rust engine is active
- use a dedicated Redis DB (default: /15) so the benchmark does not disturb the
  running local stack

Modes:
- latency (default): per-call latency comparison, sequential
- throughput: max ops/sec comparison at various concurrency levels using
  ThreadPoolExecutor — demonstrates Rust's GIL-release advantage

Options:
- --dimensions 1|3: number of rate limit dimensions (1=user only, 3=user+tenant+tool)
- --workload allow|mixed: allow-only or mixed allow/block
- --concurrency N: thread count for throughput mode
"""

# Future
from __future__ import annotations

# Standard
import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Sequence
from uuid import uuid4

# Third-Party
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# First-Party
from mcpgateway.plugins.framework import GlobalContext, PluginConfig, PluginContext, PromptPrehookPayload, ToolPreInvokePayload
from plugins.rate_limiter.rate_limiter import RateLimiterPlugin

try:
    # Third-Party
    import redis.asyncio as aioredis
except ImportError:  # pragma: no cover - dependency exists in repo venv
    aioredis = None


class BenchmarkResult(BaseModel):
    """One measured implementation result for a scenario."""

    implementation: str
    mean_ms: float
    median_ms: float
    p95_ms: float


class ThroughputResult(BaseModel):
    """Throughput benchmark result for one concurrency level."""

    implementation: str
    threads: int
    ops_per_sec: float
    total_ops: int
    duration_sec: float


@dataclass(frozen=True)
class Scenario:
    """A benchmark scenario."""

    algorithm: str
    backend: str
    hook: str
    dimensions: int = 1
    workload: str = "allow"


def _percentile(values: Sequence[float], percentile: float) -> float:
    """Return a simple percentile from a sorted float sequence."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def _make_plugin_config(
    algorithm: str,
    backend: str,
    redis_url: str,
    redis_key_prefix: str,
    dimensions: int = 1,
    workload: str = "allow",
) -> PluginConfig:
    """Create a plugin config for the benchmark.

    dimensions=1: by_user only
    dimensions=3: by_user + by_tenant + by_tool (3-dimension batch)

    workload="allow": high limit so all requests are allowed
    workload="mixed": low limit so some requests are blocked
    """
    user_rate = "3/m" if workload == "mixed" else "600000/m"
    config: dict[str, Any] = {
        "algorithm": algorithm,
        "backend": backend,
        "redis_url": redis_url,
        "redis_key_prefix": redis_key_prefix,
        "redis_fallback": False,
    }
    if dimensions == 0:
        # Baseline: no rate limits configured — plugin short-circuits immediately.
        pass
    else:
        config["by_user"] = user_rate
        if dimensions >= 3:
            config["by_tenant"] = "6000000/m" if workload != "mixed" else "6/m"
            config["by_tool"] = {"benchmark_tool": "3000000/m" if workload != "mixed" else "5/m"}
    return PluginConfig(
        name=f"rate-limiter-bench-{algorithm}-{backend}-d{dimensions}-{workload}",
        kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
        hooks=["prompt_pre_fetch", "tool_pre_invoke"],
        config=config,
    )


def _build_plugin(
    algorithm: str,
    backend: str,
    use_rust: bool,
    redis_url: str,
    redis_key_prefix: str,
    dimensions: int = 1,
    workload: str = "allow",
) -> RateLimiterPlugin:
    """Instantiate a plugin and force the requested implementation path."""
    plugin = RateLimiterPlugin(_make_plugin_config(algorithm, backend, redis_url, redis_key_prefix, dimensions, workload))
    if not use_rust:
        plugin._rust_engine = None
    elif plugin._rust_engine is None:
        raise RuntimeError("Rust rate limiter engine is not available. Run: make -C plugins_rust/rate_limiter install")
    return plugin


def _build_prompt_contexts(count: int, dimensions: int = 1) -> list[PluginContext]:
    """Build prompt benchmark contexts with fresh user identities."""
    if dimensions >= 3:
        return [PluginContext(global_context=GlobalContext(request_id=f"prompt-{i}", user=f"prompt-user-{i}@example.com", tenant_id="bench-tenant")) for i in range(count)]
    return [PluginContext(global_context=GlobalContext(request_id=f"prompt-{i}", user=f"prompt-user-{i}@example.com")) for i in range(count)]


def _build_tool_contexts(count: int, dimensions: int = 1) -> list[PluginContext]:
    """Build tool benchmark contexts with fresh user identities."""
    if dimensions >= 3:
        return [PluginContext(global_context=GlobalContext(request_id=f"tool-{i}", user=f"tool-user-{i}@example.com", tenant_id="bench-tenant")) for i in range(count)]
    return [PluginContext(global_context=GlobalContext(request_id=f"tool-{i}", user=f"tool-user-{i}@example.com")) for i in range(count)]


async def _invoke_hook(plugin: RateLimiterPlugin, hook: str, payload: Any, context: PluginContext) -> Any:
    """Invoke the selected plugin hook."""
    if hook == "prompt_pre_fetch":
        return await plugin.prompt_pre_fetch(payload, context)
    return await plugin.tool_pre_invoke(payload, context)


async def _cleanup_plugin(plugin: RateLimiterPlugin) -> None:
    """Cancel any sweep task left behind by the memory backend."""
    rate_backend = getattr(plugin, "_rate_backend", None)
    sweep_task = getattr(rate_backend, "_sweep_task", None)
    if sweep_task is not None:
        try:
            sweep_task.cancel()
            await sweep_task
        except (asyncio.CancelledError, RuntimeError):
            # RuntimeError: event loop is closed — happens when the task was
            # created on a worker thread's event loop (throughput mode).
            pass
        except Exception:
            pass


async def _flush_redis(redis_url: str) -> None:
    """Flush the benchmark Redis DB for a clean run."""
    if aioredis is None:
        return
    client = aioredis.from_url(redis_url, decode_responses=False)
    try:
        await client.flushdb()
    finally:
        await client.aclose()


async def _redis_available(redis_url: str) -> bool:
    """Check whether the benchmark Redis target is reachable."""
    if aioredis is None:
        return False
    client = aioredis.from_url(redis_url, decode_responses=False)
    try:
        return bool(await client.ping())
    except Exception:
        return False
    finally:
        await client.aclose()


async def _parity_smoke_test(algorithm: str, backend: str, redis_url: str) -> None:
    """Quick sanity-check that Python and Rust agree on an allow/block sequence."""
    redis_key_prefix = f"rlbench-parity-{algorithm}-{backend}-{uuid4().hex}"
    if backend == "redis":
        await _flush_redis(redis_url)

    plugin_python = RateLimiterPlugin(
        PluginConfig(
            name="rate-limiter-parity-python",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["tool_pre_invoke"],
            config={
                "algorithm": algorithm,
                "backend": backend,
                "by_user": "3/m",
                "redis_url": redis_url,
                "redis_key_prefix": redis_key_prefix,
                "redis_fallback": False,
            },
        )
    )
    plugin_python._rust_engine = None

    plugin_rust = RateLimiterPlugin(
        PluginConfig(
            name="rate-limiter-parity-rust",
            kind="plugins.rate_limiter.rate_limiter.RateLimiterPlugin",
            hooks=["tool_pre_invoke"],
            config={
                "algorithm": algorithm,
                "backend": backend,
                "by_user": "3/m",
                "redis_url": redis_url,
                "redis_key_prefix": redis_key_prefix,
                "redis_fallback": False,
            },
        )
    )

    if plugin_rust._rust_engine is None:
        raise RuntimeError("Rust engine unavailable during parity check")

    payload = ToolPreInvokePayload(name="bench_tool", args={})
    python_sequence: list[bool] = []
    rust_sequence: list[bool] = []

    for idx in range(4):
        ctx_python = PluginContext(global_context=GlobalContext(request_id=f"parity-py-{idx}", user="same-user@example.com"))
        ctx_rust = PluginContext(global_context=GlobalContext(request_id=f"parity-rs-{idx}", user="same-user@example.com"))
        python_result = await plugin_python.tool_pre_invoke(payload, ctx_python)
        rust_result = await plugin_rust.tool_pre_invoke(payload, ctx_rust)
        python_sequence.append(python_result.continue_processing)
        rust_sequence.append(rust_result.continue_processing)

    await _cleanup_plugin(plugin_python)
    await _cleanup_plugin(plugin_rust)

    if python_sequence != rust_sequence:
        raise AssertionError(f"Parity failed for {algorithm}/{backend}: python={python_sequence}, rust={rust_sequence}")


# ---------------------------------------------------------------------------
# Latency mode (original sequential benchmark)
# ---------------------------------------------------------------------------


async def _benchmark_scenario(
    scenario: Scenario,
    implementation: str,
    iterations: int,
    warmup: int,
    redis_url: str,
) -> BenchmarkResult:
    """Benchmark one scenario for either the Python or Rust path."""
    use_rust = implementation == "Rust"
    redis_key_prefix = f"rlbench-{scenario.algorithm}-{scenario.backend}-{scenario.hook}-{implementation.lower()}-{uuid4().hex}"

    if scenario.backend == "redis":
        await _flush_redis(redis_url)

    plugin = _build_plugin(
        algorithm=scenario.algorithm,
        backend=scenario.backend,
        use_rust=use_rust,
        redis_url=redis_url,
        redis_key_prefix=redis_key_prefix,
        dimensions=scenario.dimensions,
        workload=scenario.workload,
    )

    total_calls = iterations + warmup
    if scenario.hook == "prompt_pre_fetch":
        payload = PromptPrehookPayload(prompt_id="benchmark_tool", args={})
        contexts = _build_prompt_contexts(total_calls, scenario.dimensions)
    else:
        payload = ToolPreInvokePayload(name="benchmark_tool", args={})
        contexts = _build_tool_contexts(total_calls, scenario.dimensions)

    # Warmup
    for idx in range(warmup):
        result = await _invoke_hook(plugin, scenario.hook, payload, contexts[idx])
        if scenario.workload == "allow" and not result.continue_processing:
            raise AssertionError(f"Unexpected rate-limit during warmup for {scenario.algorithm}/{scenario.backend}/{scenario.hook}")

    times_ms: list[float] = []
    for idx in range(warmup, total_calls):
        start = time.perf_counter()
        await _invoke_hook(plugin, scenario.hook, payload, contexts[idx])
        elapsed_ms = (time.perf_counter() - start) * 1000
        times_ms.append(elapsed_ms)

    await _cleanup_plugin(plugin)

    return BenchmarkResult(
        implementation=implementation,
        mean_ms=statistics.mean(times_ms),
        median_ms=statistics.median(times_ms),
        p95_ms=_percentile(times_ms, 0.95),
    )


# ---------------------------------------------------------------------------
# Throughput mode (concurrent threads — demonstrates GIL-release advantage)
# ---------------------------------------------------------------------------


async def _run_concurrent_batch(
    plugin: RateLimiterPlugin,
    scenario: Scenario,
    concurrency: int,
    iterations_per_task: int,
) -> list[float]:
    """Fire ``concurrency`` async tasks each running ``iterations_per_task`` calls.

    Returns a flat list of per-call times (ms).
    """
    hook = scenario.hook
    if hook == "prompt_pre_fetch":
        payload = PromptPrehookPayload(prompt_id="benchmark_tool", args={})
    else:
        payload = ToolPreInvokePayload(name="benchmark_tool", args={})

    sem = asyncio.Semaphore(concurrency)
    all_times: list[list[float]] = [[] for _ in range(concurrency)]

    async def _worker(worker_id: int) -> None:
        for i in range(iterations_per_task):
            async with sem:
                ctx = PluginContext(
                    global_context=GlobalContext(
                        request_id=f"c-{worker_id}-{i}",
                        user=f"c-{worker_id}-{i}@bench.test",
                        tenant_id="bench-tenant" if scenario.dimensions >= 3 else None,
                    )
                )
                start = time.perf_counter()
                await _invoke_hook(plugin, hook, payload, ctx)
                all_times[worker_id].append((time.perf_counter() - start) * 1000)

    await asyncio.gather(*[_worker(w) for w in range(concurrency)])
    return [t for task_times in all_times for t in task_times]


async def _benchmark_throughput(
    scenario: Scenario,
    implementation: str,
    concurrency: int,
    iterations_per_task: int,
    redis_url: str,
) -> ThroughputResult:
    """Measure concurrent async throughput at a given concurrency level.

    Runs ``concurrency`` async tasks, each firing ``iterations_per_task``
    hook calls through the same plugin.  This mirrors production uvicorn
    usage where multiple request handlers share a plugin concurrently.
    """
    use_rust = implementation == "Rust"
    redis_key_prefix = f"rlbench-tp-{scenario.algorithm}-{implementation.lower()}-{uuid4().hex}"

    if scenario.backend == "redis":
        await _flush_redis(redis_url)

    plugin = _build_plugin(
        algorithm=scenario.algorithm,
        backend=scenario.backend,
        use_rust=use_rust,
        redis_url=redis_url,
        redis_key_prefix=redis_key_prefix,
        dimensions=scenario.dimensions,
        workload=scenario.workload,
    )

    start = time.monotonic()
    times_ms = await _run_concurrent_batch(plugin, scenario, concurrency, iterations_per_task)
    elapsed = time.monotonic() - start
    total_ops = len(times_ms)

    await _cleanup_plugin(plugin)

    return ThroughputResult(
        implementation=implementation,
        threads=concurrency,
        ops_per_sec=total_ops / elapsed if elapsed > 0 else 0,
        total_ops=total_ops,
        duration_sec=elapsed,
    )


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------


async def _run_latency(args: argparse.Namespace, redis_enabled: bool) -> None:
    """Run latency-mode benchmarks."""
    # --- Baseline: no rate limits configured ---
    if args.baseline:
        hook = args.hooks[0]
        baseline_scenario = Scenario(algorithm="fixed_window", backend="memory", hook=hook, dimensions=0, workload="allow")
        print("=" * 88)
        print(f"BASELINE (no rate limits) / {hook}")
        print("=" * 88)
        baseline_result = await _benchmark_scenario(baseline_scenario, "Python", args.iterations, args.warmup, args.redis_url)
        print(f"  Baseline: mean {baseline_result.mean_ms:.4f} ms | median {baseline_result.median_ms:.4f} ms | p95 {baseline_result.p95_ms:.4f} ms")
        print()
    else:
        baseline_result = None

    # --- Per-scenario benchmarks ---
    scenarios = [
        Scenario(algorithm=algorithm, backend=backend, hook=hook, dimensions=args.dimensions, workload=args.workload)
        for algorithm in ("fixed_window", "sliding_window", "token_bucket")
        for backend in args.backends
        for hook in args.hooks
    ]

    for scenario in scenarios:
        if scenario.backend == "redis" and not redis_enabled:
            continue
        print("=" * 88)
        label = f"{scenario.algorithm} / {scenario.backend} / {scenario.hook}"
        if scenario.dimensions > 1:
            label += f" / {scenario.dimensions}d"
        if scenario.workload != "allow":
            label += f" / {scenario.workload}"
        print(f"Scenario: {label}")
        print("=" * 88)
        python_result = await _benchmark_scenario(scenario, "Python", args.iterations, args.warmup, args.redis_url)
        rust_result = await _benchmark_scenario(scenario, "Rust", args.iterations, args.warmup, args.redis_url)
        speedup = python_result.mean_ms / rust_result.mean_ms if rust_result.mean_ms else 0.0
        print(f"  Python:  mean {python_result.mean_ms:.3f} ms | median {python_result.median_ms:.3f} ms | p95 {python_result.p95_ms:.3f} ms")
        print(f"  Rust:    mean {rust_result.mean_ms:.3f} ms | median {rust_result.median_ms:.3f} ms | p95 {rust_result.p95_ms:.3f} ms")
        print(f"  Speedup: {speedup:.2f}x faster")
        if baseline_result and baseline_result.mean_ms > 0:
            py_overhead = python_result.mean_ms - baseline_result.mean_ms
            rs_overhead = rust_result.mean_ms - baseline_result.mean_ms
            print(f"  Rate-limiter overhead: Python +{py_overhead:.3f} ms | Rust +{rs_overhead:.3f} ms")
        print()


async def _run_throughput(args: argparse.Namespace, redis_enabled: bool) -> None:
    """Run throughput-mode benchmarks at various concurrency levels.

    Uses asyncio.gather with a shared plugin to mirror production uvicorn
    concurrency where multiple request handlers share the same plugin.
    """
    concurrency_levels = [1, 4, 16, 64]
    if args.concurrency:
        concurrency_levels = [args.concurrency]

    iterations_per_task = max(100, args.iterations // 4)

    for algorithm in ("fixed_window",):  # throughput mode uses one algorithm to keep output manageable
        for backend in args.backends:
            if backend == "redis" and not redis_enabled:
                continue
            hook = args.hooks[0]
            scenario = Scenario(algorithm=algorithm, backend=backend, hook=hook, dimensions=args.dimensions, workload=args.workload)

            print("=" * 88)
            label = f"THROUGHPUT: {algorithm} / {backend} / {hook}"
            if scenario.dimensions > 1:
                label += f" / {scenario.dimensions}d"
            if scenario.workload != "allow":
                label += f" / {scenario.workload}"
            print(label)
            print(f"  ({iterations_per_task} iterations per task)")
            print("=" * 88)
            print(f"  {'Tasks':>7}  {'Python ops/s':>14}  {'Rust ops/s':>14}  {'Speedup':>8}")
            print(f"  {'-----':>7}  {'-' * 14:>14}  {'-' * 14:>14}  {'--------':>8}")

            for concurrency in concurrency_levels:
                py_result = await _benchmark_throughput(scenario, "Python", concurrency, iterations_per_task, args.redis_url)
                rs_result = await _benchmark_throughput(scenario, "Rust", concurrency, iterations_per_task, args.redis_url)
                speedup = rs_result.ops_per_sec / py_result.ops_per_sec if py_result.ops_per_sec else 0.0
                print(f"  {concurrency:>7}  {py_result.ops_per_sec:>14,.0f}  {rs_result.ops_per_sec:>14,.0f}  {speedup:>7.2f}x")

            print()


async def _run(args: argparse.Namespace) -> int:
    """Run the benchmark suite."""
    redis_enabled = False
    if "redis" in args.backends:
        redis_enabled = await _redis_available(args.redis_url)
        if not redis_enabled:
            print(f"  Redis unavailable at {args.redis_url}; skipping Redis scenarios")

    print("Rate Limiter Performance Comparison (Plugin Hook Path)")
    print(f"Mode:       {args.mode}")
    print(f"Iterations: {args.iterations} (+ {args.warmup} warmup)")
    print(f"Hooks:      {', '.join(args.hooks)}")
    print(f"Backends:   {', '.join(args.backends)}")
    print(f"Dimensions: {args.dimensions}")
    print(f"Workload:   {args.workload}")
    if args.mode == "throughput":
        print(f"Concurrency: {args.concurrency or '1,2,4,8'}")
    print(f"Redis URL:  {args.redis_url}")
    print()

    # Parity checks
    for algorithm in ("fixed_window", "sliding_window", "token_bucket"):
        for backend in args.backends:
            if backend == "redis" and not redis_enabled:
                continue
            await _parity_smoke_test(algorithm, backend, args.redis_url)

    print("Parity smoke checks: pass")
    print()

    if args.mode == "latency":
        await _run_latency(args, redis_enabled)
    elif args.mode == "throughput":
        await _run_throughput(args, redis_enabled)

    print("Comparison complete")
    return 0


def _parse_args() -> argparse.Namespace:
    """Parse command-line flags."""
    parser = argparse.ArgumentParser(description="Rate limiter Python vs Rust hook-path benchmark")
    parser.add_argument("--iterations", type=int, default=1000, help="Measured iterations per scenario (latency mode)")
    parser.add_argument("--warmup", type=int, default=100, help="Warmup iterations per scenario (latency mode)")
    parser.add_argument(
        "--redis-url",
        default="redis://localhost:6379/15",
        help="Dedicated Redis URL for benchmark scenarios (defaults to DB 15)",
    )
    parser.add_argument(
        "--hooks",
        nargs="+",
        default=["prompt_pre_fetch", "tool_pre_invoke"],
        choices=["prompt_pre_fetch", "tool_pre_invoke"],
        help="Hooks to benchmark",
    )
    parser.add_argument(
        "--backends",
        nargs="+",
        default=["memory", "redis"],
        choices=["memory", "redis"],
        help="Backends to benchmark",
    )
    parser.add_argument(
        "--mode",
        default="latency",
        choices=["latency", "throughput"],
        help="Benchmark mode: latency (sequential per-call) or throughput (concurrent ops/sec)",
    )
    parser.add_argument(
        "--dimensions",
        type=int,
        default=1,
        choices=[1, 3],
        help="Number of rate limit dimensions: 1 (user only) or 3 (user+tenant+tool)",
    )
    parser.add_argument(
        "--workload",
        default="allow",
        choices=["allow", "mixed"],
        help="Workload type: allow (all requests pass) or mixed (some blocked)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Thread count for throughput mode (default: sweep 1,2,4,8)",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        default=False,
        help="Include a baseline run (no rate limits) to measure plugin overhead",
    )
    return parser.parse_args()


def main() -> int:
    """Run the async benchmark entrypoint."""
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
