#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Benchmark middleware chain performance before/after optimization.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

This script benchmarks middleware performance by measuring response times
for various endpoints. Run against a live server to compare before/after
optimization results.

Usage:
    # Start the server first
    make dev

    # Run benchmark
    python scripts/benchmark_middleware.py

    # With authentication for protected endpoints
    export MCPGATEWAY_BEARER_TOKEN="your-jwt-token"
    python scripts/benchmark_middleware.py
"""

import asyncio
import os
import statistics
import sys
import time

try:
    from httpx import AsyncClient, ConnectError
except ImportError:
    print("Error: httpx is required. Install with: pip install httpx")
    sys.exit(1)


async def benchmark_endpoint(
    client: AsyncClient,
    path: str,
    headers: dict = None,
    iterations: int = 1000,
) -> dict:
    """Measure average response time for an endpoint.

    Args:
        client: HTTP client
        path: Endpoint path
        headers: Optional headers (e.g., Authorization)
        iterations: Number of requests to make

    Returns:
        Dict with timing statistics
    """
    times = []

    # Warmup (10 requests)
    for _ in range(10):
        try:
            await client.get(path, headers=headers)
        except Exception:
            pass

    # Actual benchmark
    for _ in range(iterations):
        start = time.perf_counter()
        try:
            await client.get(path, headers=headers)
            times.append((time.perf_counter() - start) * 1000)
        except Exception as e:
            print(f"  Warning: Request failed: {e}")
            continue

    if not times:
        return {
            "path": path,
            "iterations": 0,
            "error": "All requests failed",
        }

    return {
        "path": path,
        "iterations": len(times),
        "mean_ms": statistics.mean(times),
        "median_ms": statistics.median(times),
        "stdev_ms": statistics.stdev(times) if len(times) > 1 else 0,
        "min_ms": min(times),
        "max_ms": max(times),
        "p95_ms": sorted(times)[int(len(times) * 0.95)] if len(times) > 20 else max(times),
        "p99_ms": sorted(times)[int(len(times) * 0.99)] if len(times) > 100 else max(times),
    }


def print_result(result: dict) -> None:
    """Print benchmark result in formatted output."""
    if "error" in result:
        print(f"\n{result['path']}: ERROR - {result['error']}")
        return

    print(f"\n{result['path']} ({result['iterations']} requests):")
    print(f"  Mean:   {result['mean_ms']:7.3f}ms")
    print(f"  Median: {result['median_ms']:7.3f}ms")
    print(f"  Stdev:  {result['stdev_ms']:7.3f}ms")
    print(f"  Min:    {result['min_ms']:7.3f}ms")
    print(f"  Max:    {result['max_ms']:7.3f}ms")
    print(f"  P95:    {result['p95_ms']:7.3f}ms")
    print(f"  P99:    {result['p99_ms']:7.3f}ms")


async def main():
    """Run middleware performance benchmark."""
    base_url = os.getenv("MCPGATEWAY_URL", "http://localhost:4444")
    iterations = int(os.getenv("BENCHMARK_ITERATIONS", "1000"))

    # Get auth token if available
    token = os.getenv("MCPGATEWAY_BEARER_TOKEN")
    auth_headers = {"Authorization": f"Bearer {token}"} if token else None

    # Public endpoints (no auth required)
    # NOTE: Gateway app has /health and /ready (not /healthz)
    # /healthz is only in translate.py, not the main gateway
    public_endpoints = ["/health", "/ready"]

    # Protected endpoints (require auth)
    # These will be skipped if no token is provided
    protected_endpoints = ["/openapi.json", "/docs", "/metrics", "/tools", "/gateways"]

    print("=" * 60)
    print("Middleware Chain Performance Benchmark")
    print("=" * 60)
    print(f"Base URL: {base_url}")
    print(f"Iterations: {iterations}")
    print(f"Auth: {'Enabled' if auth_headers else 'Disabled'}")
    print("=" * 60)

    try:
        async with AsyncClient(base_url=base_url, timeout=30.0) as client:
            # Test connectivity
            try:
                await client.get("/health")
            except ConnectError:
                print(f"\nError: Cannot connect to {base_url}")
                print("Make sure the server is running (make dev)")
                sys.exit(1)

            print("\n>>> Public endpoints (no auth):")
            for endpoint in public_endpoints:
                result = await benchmark_endpoint(client, endpoint, iterations=iterations)
                print_result(result)

            if auth_headers:
                print("\n" + "=" * 60)
                print(">>> Protected endpoints (with auth):")
                for endpoint in protected_endpoints:
                    result = await benchmark_endpoint(
                        client,
                        endpoint,
                        headers=auth_headers,
                        iterations=iterations,
                    )
                    print_result(result)
            else:
                print("\n" + "-" * 60)
                print("Skipping protected endpoints (no MCPGATEWAY_BEARER_TOKEN set)")
                print("\nTo benchmark protected endpoints:")
                print("  export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token ...)")
                print("  python scripts/benchmark_middleware.py")

            print("\n" + "=" * 60)
            print("Benchmark complete")
            print("=" * 60)

    except Exception as e:
        print(f"\nError during benchmark: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
