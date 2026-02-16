#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Performance comparison using native Python objects (no JSON serialization).

This benchmark provides a fair apples-to-apples comparison by using native
Python objects for both implementations, eliminating JSON serialization overhead.

Measurements:
- Python (native): Baseline Python implementation
- Rust (native): High-performance Rust implementation via PyO3

Usage:
    python compare_performance.py
    python compare_performance.py --iterations 100 --warmup 10
"""

import argparse
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Add plugins directory to path to import Python implementation
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "plugins" / "secrets_detection"))

from secrets_detection import SecretsDetectionConfig, _scan_container  # noqa: E402

# Try to import Rust implementation
try:
    import secret_detection as rust_secret_detection

    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    print("⚠️  Rust implementation not available. Build it with:")
    print("   cd plugins_rust/secrets_detection && maturin develop --release")
    print()


def generate_test_data(size_kb: int, with_secrets: bool) -> Dict[str, Any]:
    """Generate test data with optional secrets - realistic conversation format."""
    # Realistic conversation messages (matching Rust benchmark)
    clean_messages = [
        "I'm setting up a microservices architecture on Kubernetes. What are the best practices for service discovery?",
        "For monitoring our services, I recommend using Prometheus with Grafana dashboards and Jaeger for distributed tracing.",
        "Let's discuss the deployment pipeline. We should implement blue-green deployments with automated rollback capabilities.",
        "The API gateway should handle rate limiting, authentication, and request routing to backend services.",
    ]

    secret_messages = [
        "Here are my AWS credentials: AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE AWS_SECRET_ACCESS_KEY=FAKESecretAccessKeyForTestingEXAMPLE0000",
        "Our Slack bot token is xoxr-fake-000000000-fake000000000-fakefakefakefake for notifications",
        "The Google API key is AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345 for our maps integration",
        "JWT token: eyJfake_header_12345.eyJfake_payload_1234.fake_signature_12345678",
        "Database encryption key: 00face00dead00beef00cafe00fade0000000000000000000000000000000000",
        "Service account key: dGhpcyBpcyBhIGJhc2U2NCBlbmNvZGVkIHNlY3JldCBrZXkgZm9yIHRlc3RpbmcgcHVycG9zZXM=",
    ]

    # Build conversation array to reach target size
    messages = []
    current_size = 0
    target_size = size_kb * 1024

    base_messages = secret_messages if with_secrets else clean_messages

    while current_size < target_size:
        for msg in base_messages:
            conversation_entry = {"role": "user" if len(messages) % 2 == 0 else "assistant", "content": msg, "timestamp": "2024-01-01T00:00:00Z"}
            messages.append(conversation_entry)
            current_size += len(str(conversation_entry))
            if current_size >= target_size:
                break

    return {"messages": messages, "metadata": {"size": size_kb, "count": len(messages)}}


def benchmark_python(data: Any, config: SecretsDetectionConfig, iterations: int, warmup: int = 5) -> Tuple[List[float], int]:
    """Benchmark Python implementation (pure Python, no Rust)."""
    for _ in range(warmup):
        _scan_container(data, config, use_rust=False)

    times = []
    count = 0
    for _ in range(iterations):
        start = time.perf_counter()
        c, _, _ = _scan_container(data, config, use_rust=False)
        times.append(time.perf_counter() - start)
        count = c

    return times, count


def benchmark_rust(data: Any, config: SecretsDetectionConfig, iterations: int, warmup: int = 5) -> Tuple[List[float], int]:
    """Benchmark Rust implementation with native Python objects."""
    if not RUST_AVAILABLE:
        return [], 0

    for _ in range(warmup):
        rust_secret_detection.py_scan_container(data, config)

    times = []
    count = 0
    for _ in range(iterations):
        start = time.perf_counter()
        c, _, _ = rust_secret_detection.py_scan_container(data, config)
        times.append(time.perf_counter() - start)
        count = c

    return times, count


def run_scenario(name: str, data: Any, config: SecretsDetectionConfig, iterations: int, warmup: int = 5):
    """Run benchmark scenario."""
    print(f"\n{'=' * 70}")
    print(f"Scenario: {name}")
    print(f"{'=' * 70}")

    # Python
    print("Running Python...", end=" ", flush=True)
    py_times, py_count = benchmark_python(data, config, iterations, warmup)
    py_mean = statistics.mean(py_times) * 1000
    py_median = statistics.median(py_times) * 1000
    py_stdev = statistics.stdev(py_times) * 1000 if len(py_times) > 1 else 0
    print(f"✓ ({py_mean:.3f} ms/iter, {py_count} secrets)")

    if RUST_AVAILABLE:
        # Rust
        print("Running Rust...", end=" ", flush=True)
        rust_times, rust_count = benchmark_rust(data, config, iterations, warmup)
        rust_mean = statistics.mean(rust_times) * 1000
        rust_median = statistics.median(rust_times) * 1000
        rust_stdev = statistics.stdev(rust_times) * 1000 if len(rust_times) > 1 else 0
        speedup = py_mean / rust_mean if rust_mean > 0 else 0
        print(f"✓ ({rust_mean:.3f} ms/iter, {rust_count} secrets)")

        print("\n📊 Results:")
        print(f"  Python:                {py_mean:.3f} ms ±{py_stdev:.3f} (median: {py_median:.3f})")
        print(f"  Rust:                  {rust_mean:.3f} ms ±{rust_stdev:.3f} (median: {rust_median:.3f}) - {speedup:.2f}x faster 🚀")

        if py_count != rust_count:
            print(f"\n  ⚠️  WARNING: Different counts! Python={py_count}, Rust={rust_count}")
    else:
        print("\n📊 Results:")
        print(f"  Python: {py_mean:.3f} ms ±{py_stdev:.3f} (median: {py_median:.3f})")
        print("  Rust: Not available")


def main():
    """Run performance comparison benchmarks for secrets detection."""
    parser = argparse.ArgumentParser(description="Native Python object performance comparison")
    parser.add_argument("--iterations", type=int, default=10000, help="Iterations per scenario")
    parser.add_argument("--warmup", type=int, default=100, help="Warmup iterations")
    args = parser.parse_args()

    print("🔍 Secrets Detection Performance (Native Python Objects)")
    print(f"Iterations: {args.iterations} (+ {args.warmup} warmup)")
    print(f"Rust available: {'✓' if RUST_AVAILABLE else '✗'}")

    config = SecretsDetectionConfig()

    # Test scenarios
    for size_kb in [1, 5]:
        for with_secrets in [False, True]:
            name = f"{size_kb}KB ({'with' if with_secrets else 'no'} secrets)"
            data = generate_test_data(size_kb, with_secrets)
            run_scenario(name, data, config, args.iterations, args.warmup)

    print(f"\n{'=' * 70}")
    print("✅ Benchmark complete!")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
