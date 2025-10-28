# -*- coding: utf-8 -*-
"""Location: ./tests/async/benchmarks.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Run async performance benchmarks and output results.
"""

# Standard
import argparse
import asyncio
import json
from pathlib import Path
import time
from typing import Any, Dict


class AsyncBenchmark:
    """Run async performance benchmarks."""

    def __init__(self, iterations: int):
        self.iterations = iterations
        self.results: Dict[str, Any] = {"iterations": self.iterations, "benchmarks": []}

    async def run_benchmarks(self) -> None:
        """Run all benchmarks."""

        # Example benchmarks
        await self._benchmark_example("Example Benchmark 1", self.example_benchmark_1)
        await self._benchmark_example("Example Benchmark 2", self.example_benchmark_2)

    async def _benchmark_example(self, name: str, benchmark_func) -> None:
        """Run a single benchmark and record its performance."""

        start_time = time.perf_counter()

        for _ in range(self.iterations):
            await benchmark_func()

        end_time = time.perf_counter()
        total_time = end_time - start_time
        avg_time = total_time / self.iterations

        self.results["benchmarks"].append({"name": name, "total_time": total_time, "average_time": avg_time})

    async def example_benchmark_1(self) -> None:
        """An example async benchmark function."""
        await asyncio.sleep(0.001)

    async def example_benchmark_2(self) -> None:
        """Another example async benchmark function."""
        await asyncio.sleep(0.002)

    def save_results(self, output_path: Path) -> None:
        """Save benchmark results to a file."""

        with open(output_path, "w") as f:
            json.dump(self.results, f, indent=4)

        print(f"Benchmark results saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run async performance benchmarks.")
    parser.add_argument("--output", type=Path, required=True, help="Path to the output benchmark results file.")
    parser.add_argument("--iterations", type=int, default=1000, help="Number of iterations to run each benchmark.")

    args = parser.parse_args()

    benchmark = AsyncBenchmark(args.iterations)
    asyncio.run(benchmark.run_benchmarks())
    benchmark.save_results(args.output)
