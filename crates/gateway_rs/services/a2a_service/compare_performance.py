#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Realistic Rust vs Python benchmarks for the A2A invoke service.

This comparison focuses on the Phase 2 invoke path, where language/runtime
choices matter most:

- `rust_batch`: the production Rust queue + invoker path
- `python_serial`: the current Python fallback path

Scenarios use a real threaded HTTP server, realistic JSON payload sizes,
encrypted auth, and duplicate request IDs so the benchmark reflects actual A2A
service behavior instead of an in-memory microbenchmark.

Latency assumptions used for the benchmark suite:

| Scenario type | Typical latency |
| --- | --- |
| Fast synchronous tool-like agent | ~50-200 ms |
| Typical production A2A request | ~100-800 ms |
| Agent calling an LLM or complex pipeline | 1-5+ seconds |
| Long-running task (async with streaming/polling) | seconds to minutes |

The `single` scenario intentionally stays near-zero-latency to measure
fixed invoke overhead. All multi-request scenarios are latency-bearing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Callable

from pydantic import SecretStr

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

for noisy_logger in (
    "httpx",
    "httpcore",
    "mcpgateway",
    "mcpgateway.config",
    "mcpgateway.services.http_client_service",
    "mcpgateway.services.metrics_buffer_service",
    "a2a_service.queue",
):
    logging.getLogger(noisy_logger).setLevel(logging.CRITICAL)

try:
    from gateway_rs import a2a_service as rust_a2a
except ImportError as exc:  # pragma: no cover - exercised in real environments
    print("Rust A2A extension is not available.")
    print(
        "Build it with `make gateway-rs-install` or `make rust-install`, then rerun this benchmark."
    )
    raise SystemExit(1) from exc

import mcpgateway.config as config_mod
import mcpgateway.services.a2a_service as a2a_service_mod
import mcpgateway.services.metrics_buffer_service as metrics_buffer_mod
from mcpgateway.config import settings
from mcpgateway.services.a2a_service import A2AAgentService
from mcpgateway.services.http_client_service import SharedHttpClient
from mcpgateway.utils.services_auth import encode_auth

AUTH_SECRET = "a2a-benchmark-secret-32-bytes-minimum"


def _benchmark_max_concurrency() -> int:
    return settings.httpx_max_connections


@dataclass(frozen=True)
class Scenario:
    name: str
    batch_size: int
    request_bytes: int
    response_bytes: int
    submission_mode: str = "batch"
    slow: bool = False
    delay_ms: int | None = None
    delay_range_ms: tuple[int, int] | None = None
    duplicate_factor: int = 1
    batch_repetitions: int = 1
    auth_modes: tuple[bool, ...] = (False, True)
    metrics_modes: tuple[bool, ...] = (False, True)
    iterations: int = 10
    warmup: int = 2


@dataclass
class LaneResult:
    scenario: str
    lane: str
    auth_enabled: bool
    metrics_enabled: bool
    iterations: int
    mean_ms: float
    median_ms: float
    min_ms: float
    max_ms: float
    p95_ms: float
    upstream_calls_per_iter: float


@dataclass
class ScenarioSpeedup:
    scenario: str
    auth_enabled: bool
    metrics_enabled: bool
    rust_median_ms: float
    python_median_ms: float
    rust_p95_ms: float
    python_p95_ms: float
    speedup_x: float
    tier: str


SCENARIOS = [
    Scenario(
        "single",
        batch_size=1,
        request_bytes=1024,
        response_bytes=512,
        delay_ms=0,
        iterations=80,
        warmup=10,
    ),
    Scenario(
        "batch_16_fast_sync",
        batch_size=16,
        request_bytes=1024,
        response_bytes=512,
        delay_range_ms=(50, 200),
        auth_modes=(True,),
        metrics_modes=(True,),
        iterations=6,
        warmup=1,
    ),
    Scenario(
        "batch_32_typical",
        batch_size=32,
        request_bytes=2048,
        response_bytes=1024,
        delay_range_ms=(100, 800),
        iterations=3,
        warmup=1,
    ),
    Scenario(
        "batch_32_typical_dup4",
        batch_size=32,
        request_bytes=2048,
        response_bytes=1024,
        delay_range_ms=(100, 800),
        duplicate_factor=4,
        auth_modes=(True,),
        metrics_modes=(True,),
        iterations=3,
        warmup=1,
    ),
    Scenario(
        "batch_128_typical",
        batch_size=128,
        request_bytes=4096,
        response_bytes=2048,
        delay_range_ms=(100, 800),
        auth_modes=(True,),
        metrics_modes=(True,),
        iterations=1,
        warmup=0,
    ),
    Scenario(
        "single_x128_typical_slow",
        batch_size=1,
        request_bytes=4096,
        response_bytes=2048,
        delay_range_ms=(100, 800),
        batch_repetitions=128,
        slow=True,
        auth_modes=(True,),
        metrics_modes=(True,),
        iterations=1,
        warmup=0,
    ),
    Scenario(
        "singles_128_typical",
        batch_size=128,
        request_bytes=4096,
        response_bytes=2048,
        submission_mode="single_fanout",
        delay_range_ms=(100, 800),
        auth_modes=(True,),
        metrics_modes=(True,),
        iterations=1,
        warmup=0,
    ),
    Scenario(
        "single_request_burst_1000",
        batch_size=1000,
        request_bytes=4096,
        response_bytes=2048,
        submission_mode="single_fanout",
        delay_range_ms=(100, 800),
        auth_modes=(True,),
        metrics_modes=(True,),
        iterations=1,
        warmup=0,
    ),
    Scenario(
        "batch_10x128_typical_slow",
        batch_size=128,
        request_bytes=4096,
        response_bytes=2048,
        delay_range_ms=(100, 800),
        batch_repetitions=10,
        slow=True,
        auth_modes=(True,),
        metrics_modes=(True,),
        iterations=1,
        warmup=0,
    ),
    Scenario(
        "batch_128_io_100_1000ms",
        batch_size=128,
        request_bytes=4096,
        response_bytes=2048,
        delay_range_ms=(100, 1000),
        auth_modes=(True,),
        metrics_modes=(True,),
        iterations=1,
        warmup=0,
    ),
]


def _p95(latencies_ms: list[float]) -> float:
    if len(latencies_ms) == 1:
        return latencies_ms[0]
    return statistics.quantiles(latencies_ms, n=20, method="inclusive")[18]


def _make_text(size: int, prefix: str) -> str:
    seed = (prefix + " lorem ipsum A2A invoke benchmark ").encode()
    repeated = (seed * ((size // len(seed)) + 2))[:size]
    return repeated.decode("ascii", errors="ignore")


def _make_parameters(index: int, request_bytes: int) -> dict[str, Any]:
    body = _make_text(max(256, request_bytes - 512), f"request-{index}")
    return {
        "query": f"Summarize the downstream task for request {index}",
        "conversation": [
            {"role": "system", "content": "You are an A2A benchmark assistant."},
            {"role": "user", "content": body[: len(body) // 2]},
            {"role": "assistant", "content": body[len(body) // 2 :]},
        ],
        "metadata": {
            "request_index": index,
            "tenant": "benchmark-team",
            "trace": f"bench-{index:04d}",
        },
    }


def _make_response_body(size: int) -> bytes:
    payload = {
        "status": "success",
        "response": _make_text(max(128, size - 128), "response"),
        "tokens_used": 256,
    }
    return json.dumps(payload).encode("utf-8")


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class _StubAgentState:
    def __init__(self, response_body: bytes, delays_s: list[float]) -> None:
        self.response_body = response_body
        self.delays_s = delays_s
        self.request_count = 0
        self.lock = threading.Lock()

    def next_delay(self) -> float:
        with self.lock:
            self.request_count += 1
            index = self.request_count - 1
            if index < len(self.delays_s):
                return self.delays_s[index]
            return self.delays_s[-1] if self.delays_s else 0.0

    def read_count(self) -> int:
        with self.lock:
            return self.request_count


def _build_delay_series(scenario: Scenario) -> list[float]:
    expected_calls = (
        scenario.batch_size // scenario.duplicate_factor
    ) * scenario.batch_repetitions
    if scenario.delay_range_ms is not None:
        low_ms, high_ms = scenario.delay_range_ms
        if expected_calls <= 1:
            return [low_ms / 1000.0]
        step = (high_ms - low_ms) / (expected_calls - 1)
        return [((low_ms + (step * index)) / 1000.0) for index in range(expected_calls)]
    if scenario.delay_ms is not None:
        return [scenario.delay_ms / 1000.0] * expected_calls
    return [0.0] * expected_calls


def _start_stub_agent_server(
    scenario: Scenario,
) -> tuple[str, _StubAgentState, Callable[[], None]]:
    state = _StubAgentState(
        _make_response_body(scenario.response_bytes), _build_delay_series(scenario)
    )

    class StubHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length:
                self.rfile.read(content_length)
            delay_s = state.next_delay()
            if delay_s:
                time.sleep(delay_s)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(state.response_body)))
            self.end_headers()
            self.wfile.write(state.response_body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    server = _ThreadedHTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}/invoke"

    def stop() -> None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    return base_url, state, stop


def _build_payloads(
    scenario: Scenario, base_url: str, auth_enabled: bool
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    unique_requests = scenario.batch_size // scenario.duplicate_factor

    for index in range(scenario.batch_size):
        request_id = None
        if scenario.duplicate_factor > 1:
            request_id = f"dup-{index % unique_requests}"

        payload: dict[str, Any] = {
            "base_url": base_url,
            "parameters": _make_parameters(index, scenario.request_bytes),
            "agent_type": "generic",
            "agent_protocol_version": "1.0",
            "interaction_type": "query",
            "agent_name": f"bench-agent-{scenario.name}",
            "agent_id": f"{scenario.name}-{index}",
            "auth_headers": {},
            "auth_query_params_plain": None,
            "auth_query_params_encrypted": None,
            "auth_value_encrypted": None,
            "request_id": request_id,
        }

        if auth_enabled:
            payload["auth_query_params_encrypted"] = {
                "access_token": encode_auth(
                    {"access_token": "bench-query-token"}, secret=AUTH_SECRET
                )
            }
            payload["auth_value_encrypted"] = encode_auth(
                {"Authorization": "Bearer bench-header-token"}, secret=AUTH_SECRET
            )

        payloads.append(payload)

    return payloads


def _expected_upstream_calls(payloads: list[dict[str, Any]]) -> int:
    request_ids = [
        payload.get("request_id") for payload in payloads if "code" not in payload
    ]
    unique_ids = {request_id for request_id in request_ids if request_id}
    without_request_id = sum(1 for request_id in request_ids if not request_id)
    return len(unique_ids) + without_request_id


def _disable_a2a_logging() -> None:
    a2a_service_mod.logger.disabled = True
    setattr(a2a_service_mod.structured_logger, "log", lambda *args, **kwargs: None)


def _speedup_tier(speedup_x: float) -> str:
    if speedup_x >= 10.0:
        return ">=10x"
    if speedup_x >= 5.0:
        return ">=5x"
    if speedup_x >= 2.0:
        return ">=2x"
    if speedup_x >= 1.0:
        return "<2x"
    return "rust slower"


def _build_speedups(results: list[LaneResult]) -> list[ScenarioSpeedup]:
    by_scenario: dict[tuple[str, bool, bool], dict[str, LaneResult]] = {}
    for result in results:
        key = (result.scenario, result.auth_enabled, result.metrics_enabled)
        by_scenario.setdefault(key, {})[result.lane] = result

    speedups: list[ScenarioSpeedup] = []
    for (scenario_name, auth_enabled, metrics_enabled), lanes in by_scenario.items():
        rust = lanes.get("rust_batch")
        python = lanes.get("python_serial")
        if rust is None or python is None:
            continue
        speedup_x = python.median_ms / rust.median_ms
        speedups.append(
            ScenarioSpeedup(
                scenario=scenario_name,
                auth_enabled=auth_enabled,
                metrics_enabled=metrics_enabled,
                rust_median_ms=rust.median_ms,
                python_median_ms=python.median_ms,
                rust_p95_ms=rust.p95_ms,
                python_p95_ms=python.p95_ms,
                speedup_x=speedup_x,
                tier=_speedup_tier(speedup_x),
            )
        )
    return speedups


async def _noop_record_metrics(*args: Any, **kwargs: Any) -> None:
    return


class _DummyDbSession:
    def commit(self) -> None:
        return


@contextmanager
def _dummy_fresh_db_session():
    yield _DummyDbSession()


class _DummyAgent:
    enabled = True
    last_interaction = None


def _setup_metrics_environment() -> None:
    metrics_buffer_mod._metrics_buffer_service = (
        metrics_buffer_mod.MetricsBufferService(enabled=True)
    )
    a2a_service_mod.fresh_db_session = _dummy_fresh_db_session  # type: ignore[assignment]
    a2a_service_mod.get_for_update = lambda db, model, agent_id: _DummyAgent()  # type: ignore[assignment]
    metrics_buffer_mod.fresh_db_session = _dummy_fresh_db_session  # type: ignore[assignment]
    metrics_buffer_mod.get_for_update = lambda db, model, agent_id: _DummyAgent()  # type: ignore[assignment]


async def run_rust_lane(
    service: A2AAgentService, payloads: list[dict[str, Any]], metrics_enabled: bool
) -> None:
    results, result_by_id = await service._invoke_phase2_rust(payloads)
    if len(results) != len(payloads):
        raise AssertionError(
            f"Rust returned {len(results)} results for {len(payloads)} payloads"
        )
    if any(result.get("status_code") != 200 for result in results):
        raise AssertionError("Rust lane produced non-200 responses")
    if metrics_enabled:
        metrics_buffer_mod.record_a2a_invoke_results_batch(
            payloads, result_by_id, datetime.now(timezone.utc)
        )


async def run_python_serial_lane(
    service: A2AAgentService, payloads: list[dict[str, Any]], metrics_enabled: bool
) -> None:
    if not metrics_enabled:
        service._record_python_invoke_metrics = _noop_record_metrics  # type: ignore[method-assign]
    results, _ = await service._invoke_phase2_python(payloads)
    if len(results) != len(payloads):
        raise AssertionError(
            f"Python serial returned {len(results)} results for {len(payloads)} payloads"
        )
    if any(result.get("status_code") != 200 for result in results):
        raise AssertionError("Python serial lane produced non-200 responses")


async def _run_submission(
    scenario: Scenario,
    service: A2AAgentService,
    payloads: list[dict[str, Any]],
    metrics_enabled: bool,
    runner: Callable[
        [A2AAgentService, list[dict[str, Any]], bool], asyncio.Future | Any
    ],
) -> None:
    if scenario.submission_mode == "batch":
        await runner(service, payloads, metrics_enabled)
        return
    if scenario.submission_mode == "single_fanout":
        async def run_one(payload: dict[str, Any]) -> None:
            await runner(service, [payload], metrics_enabled)

        await asyncio.gather(*(run_one(payload) for payload in payloads))
        return
    raise AssertionError(f"Unsupported submission mode: {scenario.submission_mode}")


async def measure_lane(
    scenario: Scenario,
    lane_name: str,
    auth_enabled: bool,
    metrics_enabled: bool,
    runner: Callable[
        [A2AAgentService, list[dict[str, Any]], bool], asyncio.Future | Any
    ],
) -> LaneResult:
    base_url, state, stop_server = _start_stub_agent_server(scenario)
    payloads = _build_payloads(scenario, base_url, auth_enabled)
    expected_calls = _expected_upstream_calls(payloads) * scenario.batch_repetitions
    latencies_ms: list[float] = []
    upstream_calls: list[int] = []

    try:
        total_runs = scenario.warmup + scenario.iterations
        for run_index in range(total_runs):
            service = A2AAgentService()
            before = state.read_count()
            started = time.perf_counter()
            for _ in range(scenario.batch_repetitions):
                await _run_submission(
                    scenario, service, payloads, metrics_enabled, runner
                )
            elapsed_ms = (time.perf_counter() - started) * 1000
            after = state.read_count()
            delta = after - before

            if delta != expected_calls:
                raise AssertionError(
                    f"{lane_name} scenario {scenario.name} sent {delta} upstream calls; expected {expected_calls}"
                )

            if run_index >= scenario.warmup:
                latencies_ms.append(elapsed_ms)
                upstream_calls.append(delta)
    finally:
        stop_server()

    return LaneResult(
        scenario=scenario.name,
        lane=lane_name,
        auth_enabled=auth_enabled,
        metrics_enabled=metrics_enabled,
        iterations=scenario.iterations,
        mean_ms=statistics.mean(latencies_ms),
        median_ms=statistics.median(latencies_ms),
        min_ms=min(latencies_ms),
        max_ms=max(latencies_ms),
        p95_ms=_p95(latencies_ms),
        upstream_calls_per_iter=statistics.mean(upstream_calls),
    )


async def benchmark_scenario(scenario: Scenario) -> list[LaneResult]:
    delay_desc = (
        f"{scenario.delay_range_ms[0]}-{scenario.delay_range_ms[1]}ms"
        if scenario.delay_range_ms is not None
        else f"{scenario.delay_ms}ms"
    )
    request_shape = (
        f"batch=1 fanout={scenario.batch_size}"
        if scenario.submission_mode == "single_fanout"
        else f"batch={scenario.batch_size}"
    )
    print(f"\nScenario: {scenario.name}")
    print(
        f"  {request_shape} request={scenario.request_bytes}B response={scenario.response_bytes}B "
        f"delay={delay_desc} dup_factor={scenario.duplicate_factor} repeats={scenario.batch_repetitions} "
        f"submission={scenario.submission_mode} slow={'yes' if scenario.slow else 'no'}"
    )
    if scenario.submission_mode == "single_fanout":
        print(
            f"  note: {scenario.batch_size} independent single-item invokes are submitted to phase 2 together; "
            f"Rust queue concurrency is capped at {_benchmark_max_concurrency()} to match the shared HTTP client pool."
        )
    elif scenario.name == "single":
        print("  note: microbenchmark at ~1 ms; headline speedup uses median because means are easily skewed by outliers.")
    lane_results: list[LaneResult] = []
    runners = [
        ("rust_batch", run_rust_lane),
        ("python_serial", run_python_serial_lane),
    ]

    for auth_enabled in scenario.auth_modes:
        for metrics_enabled in scenario.metrics_modes:
            print(
                f"  variant auth={'yes' if auth_enabled else 'no'} metrics={'yes' if metrics_enabled else 'no'}"
            )
            variant_results: list[LaneResult] = []
            for lane_name, runner in runners:
                print(f"    running {lane_name:<14}", end="", flush=True)
                result = await measure_lane(
                    scenario, lane_name, auth_enabled, metrics_enabled, runner
                )
                lane_results.append(result)
                variant_results.append(result)
                print(
                    f" median={result.median_ms:8.2f} ms  mean={result.mean_ms:8.2f} ms  p95={result.p95_ms:8.2f} ms"
                )

            serial = next(
                result for result in variant_results if result.lane == "python_serial"
            )
            rust = next(
                result for result in variant_results if result.lane == "rust_batch"
            )
            speedup = serial.median_ms / rust.median_ms
            print(f"    speedup vs python_serial (median): rust={speedup:6.2f}x")
    return lane_results


def _print_summary(results: list[LaneResult]) -> None:
    speedups = _build_speedups(results)
    scenarios_by_name = {scenario.name: scenario for scenario in SCENARIOS}
    print("\n" + "=" * 132)
    print(
        f"{'Scenario':<28} {'Mode':<12} {'Slow':>6} {'Auth':>6} {'Metrics':>8} {'Rust median':>12} "
        f"{'Python median':>14} {'Speedup':>10} {'Tier':>10} {'Rust p95':>10} {'Py p95':>10}"
    )
    print("-" * 132)
    for speedup in speedups:
        scenario = scenarios_by_name[speedup.scenario]
        print(
            f"{speedup.scenario:<28} {scenario.submission_mode:<12} {('yes' if scenario.slow else 'no'):>6} "
            f"{str(speedup.auth_enabled):>6} {str(speedup.metrics_enabled):>8} "
            f"{speedup.rust_median_ms:>12.2f} {speedup.python_median_ms:>14.2f} "
            f"{speedup.speedup_x:>9.2f}x {speedup.tier:>10} {speedup.rust_p95_ms:>10.2f} {speedup.python_p95_ms:>10.2f}"
        )
    print("=" * 132)

    print("\n" + "=" * 142)
    print(
        f"{'Scenario':<26} {'Mode':<12} {'Auth':>6} {'Metrics':>8} {'Lane':<16} {'Mean (ms)':>10} "
        f"{'P95 (ms)':>10} {'Median':>10} {'Min':>10} {'Max':>10} {'Upstream':>10}"
    )
    print("-" * 142)
    for result in results:
        scenario = scenarios_by_name[result.scenario]
        print(
            f"{result.scenario:<26} {scenario.submission_mode:<12} {str(result.auth_enabled):>6} {str(result.metrics_enabled):>8} {result.lane:<16} "
            f"{result.mean_ms:>10.2f} {result.p95_ms:>10.2f} "
            f"{result.median_ms:>10.2f} {result.min_ms:>10.2f} {result.max_ms:>10.2f} "
            f"{result.upstream_calls_per_iter:>10.2f}"
        )
    print("=" * 142)


async def _async_main(selected_scenarios: set[str], output: Path | None) -> int:
    _disable_a2a_logging()
    _setup_metrics_environment()
    real_settings = config_mod.get_settings()
    real_settings.auth_encryption_secret = SecretStr(AUTH_SECRET)
    config_mod.get_settings = lambda: real_settings  # type: ignore[assignment]
    max_concurrency = _benchmark_max_concurrency()
    rust_a2a.init_invoker(max_concurrency, 1)
    rust_a2a.init_queue(max_concurrency, None, AUTH_SECRET)

    results: list[LaneResult] = []
    try:
        for scenario in SCENARIOS:
            if selected_scenarios and scenario.name not in selected_scenarios:
                continue
            results.extend(await benchmark_scenario(scenario))
    finally:
        await SharedHttpClient.shutdown()
        if hasattr(rust_a2a, "shutdown_queue"):
            try:
                await rust_a2a.shutdown_queue(5.0)
            except Exception:
                pass

    _print_summary(results)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps([asdict(result) for result in results], indent=2),
            encoding="utf-8",
        )
        print(f"\nSaved JSON results to {output}")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark Rust vs Python A2A invoke performance"
    )
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Scenario name to run. Repeat to select multiple scenarios. Default: run all.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path for benchmark results.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print("A2A invoke performance comparison")
    print(f"Rust extension: available, max concurrency={_benchmark_max_concurrency()}")
    print("Lanes: rust_batch, python_serial")
    return asyncio.run(_async_main(set(args.scenario), args.output))


if __name__ == "__main__":
    raise SystemExit(main())
