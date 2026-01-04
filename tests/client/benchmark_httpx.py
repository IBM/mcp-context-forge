#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTPX Client Benchmark Suite

Benchmarks different HTTPX client patterns to measure throughput, latency,
and connection pool behavior under various concurrency levels.

Usage:
    python benchmark_httpx.py --help
    python benchmark_httpx.py --url http://localhost:8101/health
    python benchmark_httpx.py --url http://localhost:8101/health --duration 60 --concurrency 500
    python benchmark_httpx.py --url http://localhost:8101/api/v1/time --pattern all

Environment Variables:
    BENCHMARK_URL          Target URL (default: http://localhost:8101/health)
    BENCHMARK_DURATION     Duration in seconds (default: 30)
    BENCHMARK_CONCURRENCY  Number of concurrent workers (default: 100)
    BENCHMARK_MAX_CONNECTIONS  Max connections in pool (default: 100)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, List, Optional

import httpx


class BenchmarkPattern(str, Enum):
    """Available benchmark patterns."""

    PER_REQUEST = "per_request"
    SHARED_NO_LIMITS = "shared_no_limits"
    SHARED_WITH_LIMITS = "shared_with_limits"
    HTTP2 = "http2"
    ALL = "all"


@dataclass
class BenchmarkConfig:
    """Configuration for a benchmark run."""

    url: str = "http://localhost:8101/health"
    method: str = "GET"
    duration: int = 30  # seconds
    concurrency: int = 100
    max_connections: int = 100
    max_keepalive_connections: int = 50
    keepalive_expiry: float = 30.0
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    pool_timeout: float = 30.0
    http2: bool = False
    warmup_seconds: int = 5
    pattern: BenchmarkPattern = BenchmarkPattern.SHARED_WITH_LIMITS
    request_body: Optional[dict] = None
    headers: dict = field(default_factory=dict)
    output_format: str = "table"  # table, json, csv

    @classmethod
    def from_env(cls) -> "BenchmarkConfig":
        """Create config from environment variables."""
        return cls(
            url=os.getenv("BENCHMARK_URL", cls.url),
            duration=int(os.getenv("BENCHMARK_DURATION", str(cls.duration))),
            concurrency=int(os.getenv("BENCHMARK_CONCURRENCY", str(cls.concurrency))),
            max_connections=int(os.getenv("BENCHMARK_MAX_CONNECTIONS", str(cls.max_connections))),
            max_keepalive_connections=int(
                os.getenv("BENCHMARK_MAX_KEEPALIVE", str(cls.max_keepalive_connections))
            ),
        )


@dataclass
class BenchmarkResult:
    """Results from a benchmark run."""

    pattern: str
    config: dict
    total_requests: int
    successful_requests: int
    failed_requests: int
    total_time: float
    rps: float
    avg_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    p50_latency_ms: float
    p75_latency_ms: float
    p90_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    errors: dict
    timestamp: str = field(default_factory=lambda: datetime.now().astimezone().isoformat())


class BenchmarkRunner:
    """Runs HTTPX benchmarks with configurable patterns."""

    def __init__(self, config: BenchmarkConfig):
        self.config = config
        self.latencies: List[float] = []
        self.errors: dict = {}
        self.successful = 0
        self.failed = 0
        self.stop_event = asyncio.Event()

    def _get_limits(self) -> httpx.Limits:
        """Create httpx.Limits from config."""
        return httpx.Limits(
            max_connections=self.config.max_connections,
            max_keepalive_connections=self.config.max_keepalive_connections,
            keepalive_expiry=self.config.keepalive_expiry,
        )

    def _get_timeout(self) -> httpx.Timeout:
        """Create httpx.Timeout from config."""
        return httpx.Timeout(
            connect=self.config.connect_timeout,
            read=self.config.read_timeout,
            write=self.config.read_timeout,
            pool=self.config.pool_timeout,
        )

    async def _make_request(self, client: httpx.AsyncClient) -> float:
        """Make a single request and return latency."""
        start = time.perf_counter()
        if self.config.method.upper() == "POST" and self.config.request_body:
            response = await client.post(
                self.config.url,
                json=self.config.request_body,
                headers=self.config.headers,
            )
        else:
            response = await client.get(self.config.url, headers=self.config.headers)
        response.raise_for_status()
        return time.perf_counter() - start

    async def _worker_per_request(self, worker_id: int):
        """Worker that creates new client per request (anti-pattern)."""
        while not self.stop_event.is_set():
            try:
                async with httpx.AsyncClient(timeout=self._get_timeout()) as client:
                    latency = await self._make_request(client)
                    self.latencies.append(latency)
                    self.successful += 1
            except Exception as e:
                self.failed += 1
                err_type = type(e).__name__
                self.errors[err_type] = self.errors.get(err_type, 0) + 1

    async def _worker_shared(self, client: httpx.AsyncClient, worker_id: int):
        """Worker that uses shared client."""
        while not self.stop_event.is_set():
            try:
                latency = await self._make_request(client)
                self.latencies.append(latency)
                self.successful += 1
            except Exception as e:
                self.failed += 1
                err_type = type(e).__name__
                self.errors[err_type] = self.errors.get(err_type, 0) + 1

    async def _progress_reporter(self, start_time: float):
        """Report progress every 10 seconds."""
        interval = 10
        while not self.stop_event.is_set():
            await asyncio.sleep(interval)
            elapsed = time.perf_counter() - start_time
            current_rps = self.successful / elapsed if elapsed > 0 else 0
            print(
                f"  [{elapsed:.0f}s] {self.successful:,} requests, "
                f"{current_rps:,.0f} req/s, {self.failed} errors",
                flush=True,
            )

    async def run_per_request(self) -> BenchmarkResult:
        """Run benchmark with per-request client pattern."""
        self._reset()
        print(f"Running per-request pattern (c={self.config.concurrency})...")

        start = time.perf_counter()
        progress_task = asyncio.create_task(self._progress_reporter(start))

        tasks = [
            asyncio.create_task(self._worker_per_request(i))
            for i in range(self.config.concurrency)
        ]

        await asyncio.sleep(self.config.duration)
        self.stop_event.set()
        progress_task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        total_time = time.perf_counter() - start

        return self._create_result("per_request", total_time)

    async def run_shared_no_limits(self) -> BenchmarkResult:
        """Run benchmark with shared client, no limits."""
        self._reset()
        print(f"Running shared (no limits) pattern (c={self.config.concurrency})...")

        start = time.perf_counter()

        async with httpx.AsyncClient(timeout=self._get_timeout()) as client:
            progress_task = asyncio.create_task(self._progress_reporter(start))
            tasks = [
                asyncio.create_task(self._worker_shared(client, i))
                for i in range(self.config.concurrency)
            ]

            await asyncio.sleep(self.config.duration)
            self.stop_event.set()
            progress_task.cancel()

            await asyncio.gather(*tasks, return_exceptions=True)

        total_time = time.perf_counter() - start
        return self._create_result("shared_no_limits", total_time)

    async def run_shared_with_limits(self) -> BenchmarkResult:
        """Run benchmark with shared client and connection limits."""
        self._reset()
        print(
            f"Running shared (limits={self.config.max_connections}) pattern "
            f"(c={self.config.concurrency})..."
        )

        start = time.perf_counter()

        async with httpx.AsyncClient(
            timeout=self._get_timeout(),
            limits=self._get_limits(),
        ) as client:
            progress_task = asyncio.create_task(self._progress_reporter(start))
            tasks = [
                asyncio.create_task(self._worker_shared(client, i))
                for i in range(self.config.concurrency)
            ]

            await asyncio.sleep(self.config.duration)
            self.stop_event.set()
            progress_task.cancel()

            await asyncio.gather(*tasks, return_exceptions=True)

        total_time = time.perf_counter() - start
        return self._create_result(
            f"shared_c{self.config.concurrency}_l{self.config.max_connections}",
            total_time,
        )

    async def run_http2(self) -> BenchmarkResult:
        """Run benchmark with HTTP/2 enabled."""
        self._reset()
        print(
            f"Running HTTP/2 pattern (c={self.config.concurrency}, "
            f"limits={self.config.max_connections})..."
        )

        start = time.perf_counter()

        async with httpx.AsyncClient(
            timeout=self._get_timeout(),
            limits=self._get_limits(),
            http2=True,
        ) as client:
            progress_task = asyncio.create_task(self._progress_reporter(start))
            tasks = [
                asyncio.create_task(self._worker_shared(client, i))
                for i in range(self.config.concurrency)
            ]

            await asyncio.sleep(self.config.duration)
            self.stop_event.set()
            progress_task.cancel()

            await asyncio.gather(*tasks, return_exceptions=True)

        total_time = time.perf_counter() - start
        return self._create_result(
            f"http2_c{self.config.concurrency}_l{self.config.max_connections}",
            total_time,
        )

    def _reset(self):
        """Reset state for new benchmark run."""
        self.latencies = []
        self.errors = {}
        self.successful = 0
        self.failed = 0
        self.stop_event = asyncio.Event()

    def _create_result(self, pattern: str, total_time: float) -> BenchmarkResult:
        """Create result from collected metrics."""
        if self.latencies:
            sorted_latencies = sorted(self.latencies)
            n = len(sorted_latencies)
            return BenchmarkResult(
                pattern=pattern,
                config={
                    "url": self.config.url,
                    "duration": self.config.duration,
                    "concurrency": self.config.concurrency,
                    "max_connections": self.config.max_connections,
                    "max_keepalive": self.config.max_keepalive_connections,
                },
                total_requests=self.successful + self.failed,
                successful_requests=self.successful,
                failed_requests=self.failed,
                total_time=total_time,
                rps=self.successful / total_time if total_time > 0 else 0,
                avg_latency_ms=statistics.mean(self.latencies) * 1000,
                min_latency_ms=min(self.latencies) * 1000,
                max_latency_ms=max(self.latencies) * 1000,
                p50_latency_ms=sorted_latencies[n // 2] * 1000,
                p75_latency_ms=sorted_latencies[int(n * 0.75)] * 1000,
                p90_latency_ms=sorted_latencies[int(n * 0.90)] * 1000,
                p95_latency_ms=sorted_latencies[int(n * 0.95)] * 1000,
                p99_latency_ms=sorted_latencies[int(n * 0.99)] * 1000,
                errors=self.errors,
            )
        return BenchmarkResult(
            pattern=pattern,
            config={},
            total_requests=0,
            successful_requests=0,
            failed_requests=self.failed,
            total_time=total_time,
            rps=0,
            avg_latency_ms=0,
            min_latency_ms=0,
            max_latency_ms=0,
            p50_latency_ms=0,
            p75_latency_ms=0,
            p90_latency_ms=0,
            p95_latency_ms=0,
            p99_latency_ms=0,
            errors=self.errors,
        )


def print_result_table(result: BenchmarkResult):
    """Print result in table format."""
    print(f"\n{'='*80}")
    print(f"RESULT: {result.pattern}")
    print(f"{'='*80}")
    print(f"  Total Requests:      {result.total_requests:,}")
    print(f"  Successful:          {result.successful_requests:,}")
    print(f"  Failed:              {result.failed_requests:,}")
    print(f"  Duration:            {result.total_time:.2f}s")
    print(f"  Throughput:          {result.rps:,.1f} req/s")
    print(f"  Avg Latency:         {result.avg_latency_ms:.2f}ms")
    print(f"  Min Latency:         {result.min_latency_ms:.2f}ms")
    print(f"  P50 Latency:         {result.p50_latency_ms:.2f}ms")
    print(f"  P75 Latency:         {result.p75_latency_ms:.2f}ms")
    print(f"  P90 Latency:         {result.p90_latency_ms:.2f}ms")
    print(f"  P95 Latency:         {result.p95_latency_ms:.2f}ms")
    print(f"  P99 Latency:         {result.p99_latency_ms:.2f}ms")
    print(f"  Max Latency:         {result.max_latency_ms:.2f}ms")
    if result.errors:
        print(f"  Errors:              {result.errors}")


def print_summary_table(results: List[BenchmarkResult]):
    """Print summary comparison table."""
    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print(
        f"{'Pattern':<40} {'Total':>12} {'RPS':>12} {'P50(ms)':>10} "
        f"{'P99(ms)':>10} {'Success%':>10}"
    )
    print("-" * 100)

    for r in results:
        success_rate = (
            (r.successful_requests / r.total_requests * 100)
            if r.total_requests > 0
            else 0
        )
        print(
            f"{r.pattern:<40} {r.total_requests:>12,} {r.rps:>12,.1f} "
            f"{r.p50_latency_ms:>10.2f} {r.p99_latency_ms:>10.2f} {success_rate:>9.1f}%"
        )


def print_comparison(results: List[BenchmarkResult], baseline_pattern: str = "per_request"):
    """Print performance comparison vs baseline."""
    baseline = next((r for r in results if baseline_pattern in r.pattern), None)
    if not baseline or baseline.rps == 0:
        return

    print("\n" + "=" * 80)
    print(f"PERFORMANCE VS BASELINE ({baseline.pattern})")
    print("=" * 80)

    for r in results:
        if r.pattern != baseline.pattern:
            improvement = ((r.rps / baseline.rps) - 1) * 100
            print(f"  {r.pattern}: {improvement:+,.1f}% ({r.rps:,.1f} vs {baseline.rps:,.1f} RPS)")


async def verify_connection(url: str) -> bool:
    """Verify target URL is reachable."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            print(f"Connection test: {response.status_code}")
            return response.status_code < 400
    except Exception as e:
        print(f"ERROR: Cannot connect to {url}: {e}")
        return False


async def main():
    parser = argparse.ArgumentParser(
        description="HTTPX Client Benchmark Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --url http://localhost:8101/health
  %(prog)s --url http://localhost:8101/health --duration 60 --concurrency 500
  %(prog)s --pattern all --duration 120
  %(prog)s --pattern shared_with_limits --concurrency 1000 --max-connections 500
        """,
    )

    parser.add_argument(
        "--url",
        default=os.getenv("BENCHMARK_URL", "http://localhost:8101/health"),
        help="Target URL to benchmark (default: $BENCHMARK_URL or http://localhost:8101/health)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=int(os.getenv("BENCHMARK_DURATION", "30")),
        help="Duration in seconds per pattern (default: 30)",
    )
    parser.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=int(os.getenv("BENCHMARK_CONCURRENCY", "100")),
        help="Number of concurrent workers (default: 100)",
    )
    parser.add_argument(
        "--max-connections",
        "-l",
        type=int,
        default=int(os.getenv("BENCHMARK_MAX_CONNECTIONS", "100")),
        help="Max connections in pool (default: 100)",
    )
    parser.add_argument(
        "--max-keepalive",
        type=int,
        default=int(os.getenv("BENCHMARK_MAX_KEEPALIVE", "50")),
        help="Max keepalive connections (default: 50)",
    )
    parser.add_argument(
        "--pattern",
        "-p",
        choices=[p.value for p in BenchmarkPattern],
        default="shared_with_limits",
        help="Benchmark pattern to run (default: shared_with_limits)",
    )
    parser.add_argument(
        "--output",
        "-o",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )
    parser.add_argument(
        "--http2",
        action="store_true",
        help="Enable HTTP/2 for shared patterns",
    )

    args = parser.parse_args()

    config = BenchmarkConfig(
        url=args.url,
        duration=args.duration,
        concurrency=args.concurrency,
        max_connections=args.max_connections,
        max_keepalive_connections=args.max_keepalive,
        http2=args.http2,
        output_format=args.output,
    )

    print("=" * 80)
    print("HTTPX Client Benchmark Suite")
    print("=" * 80)
    print(f"Target URL:     {config.url}")
    print(f"Duration:       {config.duration}s per pattern")
    print(f"Concurrency:    {config.concurrency}")
    print(f"Max Connections: {config.max_connections}")
    print(f"Pattern:        {args.pattern}")
    print("=" * 80)

    if not await verify_connection(config.url):
        sys.exit(1)

    runner = BenchmarkRunner(config)
    results: List[BenchmarkResult] = []

    pattern = BenchmarkPattern(args.pattern)

    if pattern == BenchmarkPattern.ALL:
        # Run all patterns
        print("\n[1/4] Per-request client (limited to c=100)...")
        config.concurrency = min(100, args.concurrency)  # Limit for per-request
        runner = BenchmarkRunner(config)
        results.append(await runner.run_per_request())
        print_result_table(results[-1])

        config.concurrency = args.concurrency  # Restore
        runner = BenchmarkRunner(config)

        print("\n[2/4] Shared client (no limits)...")
        results.append(await runner.run_shared_no_limits())
        print_result_table(results[-1])

        print("\n[3/4] Shared client (with limits)...")
        results.append(await runner.run_shared_with_limits())
        print_result_table(results[-1])

        print("\n[4/4] HTTP/2 shared client...")
        results.append(await runner.run_http2())
        print_result_table(results[-1])

    elif pattern == BenchmarkPattern.PER_REQUEST:
        config.concurrency = min(100, args.concurrency)
        runner = BenchmarkRunner(config)
        results.append(await runner.run_per_request())
        print_result_table(results[-1])

    elif pattern == BenchmarkPattern.SHARED_NO_LIMITS:
        results.append(await runner.run_shared_no_limits())
        print_result_table(results[-1])

    elif pattern == BenchmarkPattern.SHARED_WITH_LIMITS:
        results.append(await runner.run_shared_with_limits())
        print_result_table(results[-1])

    elif pattern == BenchmarkPattern.HTTP2:
        results.append(await runner.run_http2())
        print_result_table(results[-1])

    # Print summary
    if len(results) > 1:
        print_summary_table(results)
        print_comparison(results)

    # JSON output
    if args.output == "json":
        print("\n" + json.dumps([asdict(r) for r in results], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
