#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Concurrency Sweep Benchmark

Runs benchmarks across multiple concurrency levels to find optimal configuration.

Usage:
    python benchmark_sweep.py --help
    python benchmark_sweep.py --url http://localhost:8101/health
    python benchmark_sweep.py --url http://localhost:8101/health --duration 60
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from typing import List, Tuple

import httpx

from benchmark_httpx import BenchmarkConfig, BenchmarkResult, BenchmarkRunner


# Default concurrency levels to test
DEFAULT_LEVELS: List[Tuple[int, int]] = [
    # (concurrency, max_connections)
    (10, 50),
    (50, 100),
    (100, 100),
    (200, 200),
    (500, 200),
    (500, 500),
    (1000, 500),
    (1000, 1000),
    (2000, 1000),
    (3000, 1000),
]


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


async def run_sweep(
    url: str,
    duration: int,
    levels: List[Tuple[int, int]],
    output_format: str = "table",
) -> List[BenchmarkResult]:
    """Run benchmark sweep across concurrency levels."""
    results: List[BenchmarkResult] = []

    for i, (concurrency, max_connections) in enumerate(levels, 1):
        print(f"\n[{i}/{len(levels)}] Testing c={concurrency}, l={max_connections}")

        config = BenchmarkConfig(
            url=url,
            duration=duration,
            concurrency=concurrency,
            max_connections=max_connections,
            max_keepalive_connections=min(concurrency, max_connections) // 2,
        )

        runner = BenchmarkRunner(config)
        result = await runner.run_shared_with_limits()
        results.append(result)

        # Print intermediate result
        success_rate = (
            (result.successful_requests / result.total_requests * 100)
            if result.total_requests > 0
            else 0
        )
        print(
            f"  Result: {result.rps:,.1f} RPS, "
            f"P99={result.p99_latency_ms:.2f}ms, "
            f"{success_rate:.1f}% success"
        )

    return results


def print_sweep_table(results: List[BenchmarkResult]):
    """Print sweep results as table."""
    print("\n" + "=" * 120)
    print("CONCURRENCY SWEEP RESULTS")
    print("=" * 120)
    print(
        f"{'Pattern':<35} {'Requests':>12} {'RPS':>12} {'Avg(ms)':>10} "
        f"{'P50(ms)':>10} {'P99(ms)':>10} {'Max(ms)':>10} {'Success%':>10}"
    )
    print("-" * 120)

    for r in results:
        success_rate = (
            (r.successful_requests / r.total_requests * 100)
            if r.total_requests > 0
            else 0
        )
        print(
            f"{r.pattern:<35} {r.total_requests:>12,} {r.rps:>12,.1f} "
            f"{r.avg_latency_ms:>10.2f} {r.p50_latency_ms:>10.2f} "
            f"{r.p99_latency_ms:>10.2f} {r.max_latency_ms:>10.2f} {success_rate:>9.1f}%"
        )

    # Find best RPS
    best = max(results, key=lambda r: r.rps)
    print("\n" + "-" * 120)
    print(f"BEST: {best.pattern} with {best.rps:,.1f} RPS")


def save_csv(results: List[BenchmarkResult], filename: str):
    """Save results to CSV file."""
    with open(filename, "w", newline="") as f:
        if not results:
            return

        writer = csv.DictWriter(f, fieldnames=list(asdict(results[0]).keys()))
        writer.writeheader()
        for r in results:
            row = asdict(r)
            # Flatten config dict
            config = row.pop("config", {})
            row.update({f"config_{k}": v for k, v in config.items()})
            # Convert errors dict to string
            row["errors"] = json.dumps(row.get("errors", {}))
            writer.writerow(row)

    print(f"\nResults saved to: {filename}")


def save_json(results: List[BenchmarkResult], filename: str):
    """Save results to JSON file."""
    with open(filename, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    print(f"\nResults saved to: {filename}")


async def main():
    parser = argparse.ArgumentParser(
        description="Run benchmark sweep across concurrency levels",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --url http://localhost:8101/health
  %(prog)s --url http://localhost:8101/health --duration 60
  %(prog)s --levels "100:100,500:200,1000:500"
  %(prog)s --output results.csv
        """,
    )

    parser.add_argument(
        "--url",
        default=os.getenv("BENCHMARK_URL", "http://localhost:8101/health"),
        help="Target URL to benchmark",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=int(os.getenv("BENCHMARK_DURATION", "30")),
        help="Duration in seconds per level (default: 30)",
    )
    parser.add_argument(
        "--levels",
        help="Custom levels as 'c1:l1,c2:l2,...' (e.g., '100:100,500:200')",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file (csv or json based on extension)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick sweep with fewer levels",
    )

    args = parser.parse_args()

    # Parse custom levels or use defaults
    if args.levels:
        levels = []
        for level in args.levels.split(","):
            c, l = level.split(":")
            levels.append((int(c), int(l)))
    elif args.quick:
        levels = [
            (100, 100),
            (500, 200),
            (1000, 500),
        ]
    else:
        levels = DEFAULT_LEVELS

    print("=" * 80)
    print("HTTPX Concurrency Sweep Benchmark")
    print("=" * 80)
    print(f"Target URL:     {args.url}")
    print(f"Duration:       {args.duration}s per level")
    print(f"Levels:         {len(levels)} configurations")
    print(f"Estimated time: ~{len(levels) * args.duration // 60} minutes")
    print("=" * 80)
    print(f"Levels: {levels}")

    if not await verify_connection(args.url):
        sys.exit(1)

    results = await run_sweep(args.url, args.duration, levels)

    print_sweep_table(results)

    # Save results if output specified
    if args.output:
        if args.output.endswith(".csv"):
            save_csv(results, args.output)
        else:
            save_json(results, args.output)


if __name__ == "__main__":
    asyncio.run(main())
