#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./benchmarks/compare_pii_filter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Performance comparison tool: Python vs Rust PII Filter implementations

Usage:
    python benchmarks/compare_pii_filter.py
    python benchmarks/compare_pii_filter.py --sizes 100 500 1000
    python benchmarks/compare_pii_filter.py --output results.json
"""

import argparse
import json
import time
import sys
import os
import statistics
from typing import Dict, List, Tuple
from dataclasses import dataclass, asdict

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.pii_filter.pii_filter import PIIDetector as PythonPIIDetector, PIIFilterConfig

try:
    from plugins.pii_filter.pii_filter_rust import RustPIIDetector, RUST_AVAILABLE
except ImportError:
    RUST_AVAILABLE = False
    RustPIIDetector = None


@dataclass
class BenchmarkResult:
    """Results from a single benchmark run."""

    name: str
    implementation: str
    duration_ms: float
    throughput_mb_s: float
    operations: int
    text_size_bytes: int
    # Latency statistics
    min_ms: float = 0.0
    max_ms: float = 0.0
    median_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    stddev_ms: float = 0.0
    # Additional metrics
    ops_per_sec: float = 0.0


class BenchmarkSuite:
    """Comprehensive benchmark suite comparing Python and Rust implementations."""

    def __init__(self):
        self.config = PIIFilterConfig()
        self.python_detector = PythonPIIDetector(self.config)
        self.rust_detector = RustPIIDetector(self.config) if RUST_AVAILABLE else None
        self.results: List[BenchmarkResult] = []

    def measure_time(self, func, *args, iterations=100):
        """Measure execution time of a function over multiple iterations.

        Returns:
            Tuple of (average_duration, latencies_list)
        """
        # Warmup
        for _ in range(10):
            func(*args)

        # Measure individual iterations
        latencies = []
        for _ in range(iterations):
            start = time.perf_counter()
            func(*args)
            latencies.append(time.perf_counter() - start)

        return statistics.mean(latencies), latencies

    def bench_single_detection(self, text: str, name: str, iterations=1000):
        """Benchmark single text detection."""
        text_size = len(text.encode("utf-8"))

        # Python benchmark
        py_time, py_latencies = self.measure_time(self.python_detector.detect, text, iterations=iterations)
        py_latencies_ms = [l * 1000 for l in py_latencies]
        py_result = BenchmarkResult(
            name=f"{name}_python",
            implementation="Python",
            duration_ms=py_time * 1000,
            throughput_mb_s=(text_size / py_time) / (1024 * 1024),
            operations=iterations,
            text_size_bytes=text_size,
            min_ms=min(py_latencies_ms),
            max_ms=max(py_latencies_ms),
            median_ms=statistics.median(py_latencies_ms),
            p95_ms=statistics.quantiles(py_latencies_ms, n=20)[18] if len(py_latencies_ms) > 20 else max(py_latencies_ms),
            p99_ms=statistics.quantiles(py_latencies_ms, n=100)[98] if len(py_latencies_ms) > 100 else max(py_latencies_ms),
            stddev_ms=statistics.stdev(py_latencies_ms) if len(py_latencies_ms) > 1 else 0.0,
            ops_per_sec=1.0 / py_time,
        )
        self.results.append(py_result)

        # Rust benchmark
        if self.rust_detector:
            rust_time, rust_latencies = self.measure_time(self.rust_detector.detect, text, iterations=iterations)
            rust_latencies_ms = [l * 1000 for l in rust_latencies]
            rust_result = BenchmarkResult(
                name=f"{name}_rust",
                implementation="Rust",
                duration_ms=rust_time * 1000,
                throughput_mb_s=(text_size / rust_time) / (1024 * 1024),
                operations=iterations,
                text_size_bytes=text_size,
                min_ms=min(rust_latencies_ms),
                max_ms=max(rust_latencies_ms),
                median_ms=statistics.median(rust_latencies_ms),
                p95_ms=statistics.quantiles(rust_latencies_ms, n=20)[18] if len(rust_latencies_ms) > 20 else max(rust_latencies_ms),
                p99_ms=statistics.quantiles(rust_latencies_ms, n=100)[98] if len(rust_latencies_ms) > 100 else max(rust_latencies_ms),
                stddev_ms=statistics.stdev(rust_latencies_ms) if len(rust_latencies_ms) > 1 else 0.0,
                ops_per_sec=1.0 / rust_time,
            )
            self.results.append(rust_result)

            speedup = py_time / rust_time
            return py_result, rust_result, speedup

        return py_result, None, 1.0

    def bench_detection_and_masking(self, text: str, name: str, iterations=500):
        """Benchmark combined detection + masking."""
        text_size = len(text.encode("utf-8"))

        # Python benchmark
        def python_full(txt):
            detections = self.python_detector.detect(txt)
            return self.python_detector.mask(txt, detections)

        py_time, py_latencies = self.measure_time(python_full, text, iterations=iterations)
        py_latencies_ms = [l * 1000 for l in py_latencies]
        py_result = BenchmarkResult(
            name=f"{name}_full_python",
            implementation="Python",
            duration_ms=py_time * 1000,
            throughput_mb_s=(text_size / py_time) / (1024 * 1024),
            operations=iterations,
            text_size_bytes=text_size,
            min_ms=min(py_latencies_ms),
            max_ms=max(py_latencies_ms),
            median_ms=statistics.median(py_latencies_ms),
            p95_ms=statistics.quantiles(py_latencies_ms, n=20)[18] if len(py_latencies_ms) > 20 else max(py_latencies_ms),
            p99_ms=statistics.quantiles(py_latencies_ms, n=100)[98] if len(py_latencies_ms) > 100 else max(py_latencies_ms),
            stddev_ms=statistics.stdev(py_latencies_ms) if len(py_latencies_ms) > 1 else 0.0,
            ops_per_sec=1.0 / py_time,
        )
        self.results.append(py_result)

        # Rust benchmark
        if self.rust_detector:

            def rust_full(txt):
                detections = self.rust_detector.detect(txt)
                return self.rust_detector.mask(txt, detections)

            rust_time, rust_latencies = self.measure_time(rust_full, text, iterations=iterations)
            rust_latencies_ms = [l * 1000 for l in rust_latencies]
            rust_result = BenchmarkResult(
                name=f"{name}_full_rust",
                implementation="Rust",
                duration_ms=rust_time * 1000,
                throughput_mb_s=(text_size / rust_time) / (1024 * 1024),
                operations=iterations,
                text_size_bytes=text_size,
                min_ms=min(rust_latencies_ms),
                max_ms=max(rust_latencies_ms),
                median_ms=statistics.median(rust_latencies_ms),
                p95_ms=statistics.quantiles(rust_latencies_ms, n=20)[18] if len(rust_latencies_ms) > 20 else max(rust_latencies_ms),
                p99_ms=statistics.quantiles(rust_latencies_ms, n=100)[98] if len(rust_latencies_ms) > 100 else max(rust_latencies_ms),
                stddev_ms=statistics.stdev(rust_latencies_ms) if len(rust_latencies_ms) > 1 else 0.0,
                ops_per_sec=1.0 / rust_time,
            )
            self.results.append(rust_result)

            speedup = py_time / rust_time
            return py_result, rust_result, speedup

        return py_result, None, 1.0

    def bench_nested_processing(self, data: dict, name: str, iterations=100):
        """Benchmark nested data structure processing."""
        data_str = json.dumps(data)
        data_size = len(data_str.encode("utf-8"))

        # Python benchmark
        py_time = self.measure_time(self.python_detector.process_nested, data, "", iterations=iterations)
        py_result = BenchmarkResult(
            name=f"{name}_nested_python",
            implementation="Python",
            duration_ms=py_time * 1000,
            throughput_mb_s=(data_size / py_time) / (1024 * 1024),
            operations=iterations,
            text_size_bytes=data_size,
        )
        self.results.append(py_result)

        # Rust benchmark
        if self.rust_detector:
            rust_time = self.measure_time(self.rust_detector.process_nested, data, "", iterations=iterations)
            rust_result = BenchmarkResult(
                name=f"{name}_nested_rust",
                implementation="Rust",
                duration_ms=rust_time * 1000,
                throughput_mb_s=(data_size / rust_time) / (1024 * 1024),
                operations=iterations,
                text_size_bytes=data_size,
            )
            self.results.append(rust_result)

            speedup = py_time / rust_time
            return py_result, rust_result, speedup

        return py_result, None, 1.0

    def run_all_benchmarks(self, sizes: List[int] = None):
        """Run comprehensive benchmark suite."""
        if sizes is None:
            sizes = [100, 500, 1000, 5000]

        print("=" * 80)
        print("PII Filter Performance Comparison: Python vs Rust")
        print("=" * 80)
        print()

        # Benchmark 1: Single SSN
        print("1. Single SSN Detection")
        print("-" * 80)
        text = "My SSN is 123-45-6789"
        py, rust, speedup = self.bench_single_detection(text, "single_ssn")
        self.print_comparison(py, rust, speedup)
        print()

        # Benchmark 2: Single Email
        print("2. Single Email Detection")
        print("-" * 80)
        text = "Contact me at john.doe@example.com for more information"
        py, rust, speedup = self.bench_single_detection(text, "single_email")
        self.print_comparison(py, rust, speedup)
        print()

        # Benchmark 3: Multiple PII Types
        print("3. Multiple PII Types Detection")
        print("-" * 80)
        text = "SSN: 123-45-6789, Email: john@example.com, Phone: (555) 123-4567, IP: 192.168.1.100"
        py, rust, speedup = self.bench_single_detection(text, "multiple_types")
        self.print_comparison(py, rust, speedup)
        print()

        # Benchmark 4: No PII Text
        print("4. No PII Detection (Best Case)")
        print("-" * 80)
        text = "This is just normal text without any sensitive information whatsoever. " * 5
        py, rust, speedup = self.bench_single_detection(text, "no_pii")
        self.print_comparison(py, rust, speedup)
        print()

        # Benchmark 5: Detection + Masking
        print("5. Detection + Masking (Full Workflow)")
        print("-" * 80)
        text = "User: SSN 123-45-6789, Email john@example.com, Credit Card 4111-1111-1111-1111"
        py, rust, speedup = self.bench_detection_and_masking(text, "full_workflow")
        self.print_comparison(py, rust, speedup)
        print()

        # Benchmark 6: Nested Structure (Rust only - Python has different API)
        print("6. Nested Data Structure Processing (Rust-only)")
        print("-" * 80)
        if self.rust_detector:
            data = {
                "users": [
                    {"ssn": "123-45-6789", "email": "alice@example.com", "name": "Alice"},
                    {"ssn": "987-65-4321", "email": "bob@example.com", "name": "Bob"},
                ],
                "contact": {"email": "admin@example.com", "phone": "555-1234"},
            }
            data_str = json.dumps(data)
            data_size = len(data_str.encode("utf-8"))

            import time

            start = time.time()
            for _ in range(100):
                self.rust_detector.process_nested(data, "")
            duration = (time.time() - start) / 100

            print(f"   Rust:   {duration * 1000:.3f} ms ({(data_size / duration) / (1024 * 1024):.2f} MB/s)")
        else:
            print("   Rust:   Not available")
        print()

        # Benchmark 7: Large Text (Variable Sizes)
        print("7. Large Text Performance (Variable Sizes)")
        print("-" * 80)
        for size in sizes:
            print(f"\n   Size: {size} PII instances")
            text = self.generate_large_text(size)
            py, rust, speedup = self.bench_single_detection(text, f"large_{size}", iterations=max(10, 100 // (size // 100)))
            self.print_comparison(py, rust, speedup, indent="   ")
        print()

        # Benchmark 8: Realistic API Payload
        print("8. Realistic API Payload")
        print("-" * 80)
        text = """{
            "user": {
                "ssn": "123-45-6789",
                "email": "john.doe@example.com",
                "phone": "(555) 123-4567",
                "address": "123 Main St, Anytown, USA",
                "credit_card": "4111-1111-1111-1111"
            },
            "metadata": {
                "ip_address": "192.168.1.100",
                "timestamp": "2025-01-15T10:30:00Z"
            }
        }"""
        py, rust, speedup = self.bench_detection_and_masking(text, "realistic_payload", iterations=500)
        self.print_comparison(py, rust, speedup)
        print()

        # Summary
        self.print_summary()

    def generate_large_text(self, num_instances: int) -> str:
        """Generate large text with N PII instances."""
        lines = []
        for i in range(num_instances):
            lines.append(f"User {i}: SSN {i % 1000:03d}-45-6789, Email user{i}@example.com, Phone: (555) {i % 1000:03d}-{i % 10000:04d}")
        return "\n".join(lines)

    def print_comparison(self, py_result: BenchmarkResult, rust_result: BenchmarkResult = None, speedup: float = 1.0, indent: str = ""):
        """Print comparison between Python and Rust results."""
        print(f"{indent}Python:")
        print(f"{indent}  Avg:    {py_result.duration_ms:.3f} ms | Median: {py_result.median_ms:.3f} ms")
        print(f"{indent}  p95:    {py_result.p95_ms:.3f} ms | p99:    {py_result.p99_ms:.3f} ms")
        print(f"{indent}  Min:    {py_result.min_ms:.3f} ms | Max:    {py_result.max_ms:.3f} ms")
        print(f"{indent}  StdDev: {py_result.stddev_ms:.3f} ms")
        print(f"{indent}  Throughput: {py_result.throughput_mb_s:.2f} MB/s | {py_result.ops_per_sec:,.0f} ops/sec")

        if rust_result:
            print(f"{indent}Rust:")
            print(f"{indent}  Avg:    {rust_result.duration_ms:.3f} ms | Median: {rust_result.median_ms:.3f} ms")
            print(f"{indent}  p95:    {rust_result.p95_ms:.3f} ms | p99:    {rust_result.p99_ms:.3f} ms")
            print(f"{indent}  Min:    {rust_result.min_ms:.3f} ms | Max:    {rust_result.max_ms:.3f} ms")
            print(f"{indent}  StdDev: {rust_result.stddev_ms:.3f} ms")
            print(f"{indent}  Throughput: {rust_result.throughput_mb_s:.2f} MB/s | {rust_result.ops_per_sec:,.0f} ops/sec")
            print(f"{indent}Speedup: {speedup:.1f}x faster (latency improvement: {py_result.median_ms / rust_result.median_ms:.1f}x)")
        else:
            print(f"{indent}Rust:   Not available")

    def print_summary(self):
        """Print summary statistics."""
        print("=" * 80)
        print("Summary")
        print("=" * 80)
        print()

        if not self.rust_detector:
            print("⚠ Rust implementation not available")
            print("  Install with: pip install mcpgateway[rust]")
            return

        # Calculate average speedup
        python_results = [r for r in self.results if r.implementation == "Python"]
        rust_results = [r for r in self.results if r.implementation == "Rust"]

        if len(python_results) == len(rust_results):
            total_speedup = 0
            count = 0
            for py_r, rust_r in zip(python_results, rust_results):
                if py_r.name.replace("_python", "") == rust_r.name.replace("_rust", ""):
                    speedup = py_r.duration_ms / rust_r.duration_ms
                    total_speedup += speedup
                    count += 1

            if count > 0:
                avg_speedup = total_speedup / count
                print(f"Average Speedup: {avg_speedup:.1f}x")
                print()
                print(f"Rust implementation is {avg_speedup:.1f}x faster on average")
                print()

                # Performance category
                if avg_speedup >= 10:
                    print("🚀 EXCELLENT: >10x speedup - Highly recommended")
                elif avg_speedup >= 5:
                    print("✓ GREAT: 5-10x speedup - Recommended for production")
                elif avg_speedup >= 3:
                    print("✓ GOOD: 3-5x speedup - Noticeable improvement")
                elif avg_speedup >= 2:
                    print("✓ MODERATE: 2-3x speedup - Worthwhile upgrade")
                else:
                    print("⚠ MINIMAL: <2x speedup - May not justify complexity")

    def save_results(self, output_path: str):
        """Save benchmark results to JSON file."""
        results_dict = [asdict(r) for r in self.results]
        with open(output_path, "w") as f:
            json.dump(results_dict, f, indent=2)
        print(f"\n✓ Results saved to: {output_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Compare Python vs Rust PII filter performance")
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 500, 1000, 5000], help="Sizes for large text benchmark")
    parser.add_argument("--output", type=str, help="Save results to JSON file")
    parser.add_argument("--detailed", action="store_true", help="Show detailed latency statistics")
    args = parser.parse_args()

    if not RUST_AVAILABLE:
        print("⚠ WARNING: Rust implementation not available")
        print("Install with: pip install mcpgateway[rust]")
        print("Running Python-only benchmarks...\n")

    suite = BenchmarkSuite()
    suite.run_all_benchmarks(sizes=args.sizes)

    if args.output:
        suite.save_results(args.output)


if __name__ == "__main__":
    main()
