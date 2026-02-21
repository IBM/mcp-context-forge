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
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Add plugins directory to path to import Python implementation
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "plugins" / "regex_filter"))

from search_replace import SearchReplaceConfig, SearchReplace, _process_container  # noqa: E402

# Try to import Rust implementation
try:
    from regex_filter import SearchReplacePluginRust

    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    print("⚠️  Rust implementation not available. Build it with:")
    print("   cd plugins_rust/regex_filter && maturin develop --release")
    print()


def generate_test_data(size_kb: int, with_patterns: bool) -> Dict[str, Any]:
    """Generate test data with optional pattern matches - realistic LLM conversation format."""
    # Clean LLM responses without patterns to match
    clean_messages = [
        "I can help you design a scalable microservices architecture. Let's start by discussing your requirements for service discovery and load balancing.",
        "For monitoring distributed systems, I recommend implementing observability with metrics, logs, and traces. Consider using Prometheus for metrics collection and Grafana for visualization.",
        "The deployment pipeline should include automated testing, security scanning, and gradual rollout strategies. Blue-green deployments minimize downtime during updates.",
        "Your gateway layer should handle cross-cutting concerns like rate limiting, authentication, request routing, and protocol translation between clients and backend services.",
        "Database design is crucial for performance. Consider using connection pooling, read replicas, and caching strategies to optimize query performance at scale.",
        "Container orchestration with Kubernetes provides automated deployment, scaling, and management of containerized applications across clusters of hosts.",
    ]

    # LLM responses containing patterns that need filtering/replacement
    # Focus on: content moderation, terminology standardization, brand normalization
    pattern_messages = [
        # Content moderation - profanity replacement
        "This legacy codebase is crap and needs refactoring. The damn architecture makes it hard to maintain and extend functionality.",
        "I'm frustrated with this buggy implementation. It's a piece of crap that crashes constantly. Damn, we need to rewrite this module completely.",
        "The documentation is crap and outdated. Damn it, nobody can understand how to use this API without better examples and explanations.",
        # Terminology standardization - AI expansion for clarity
        "The AI model uses deep learning for natural language processing. Our AI system can analyze sentiment and extract entities from text using AI algorithms.",
        "Modern AI applications leverage neural networks. The AI pipeline includes data preprocessing, model training, and inference optimization for AI deployment.",
        "This AI solution provides real-time predictions. The AI framework supports multiple AI models running in parallel for improved throughput.",
        # Brand name standardization - consistent formatting
        "Microsoft Azure and IBM Cloud are leading providers. Microsoft offers Office 365 while IBM provides Watson services for enterprise customers.",
        "The solution integrates with Microsoft Teams and IBM Db2 databases. Microsoft's cloud platform complements IBM's enterprise software offerings.",
        "We're evaluating Microsoft SQL Server versus IBM Db2. Both Microsoft and IBM offer robust enterprise database solutions with different strengths.",
        # Mixed patterns - realistic technical discussion with issues
        "The damn AI integration keeps failing. This crap code needs a complete rewrite. Microsoft's documentation doesn't help much either.",
        "I'm working on the AI pipeline but it's crap. The damn performance is terrible. We should consider IBM's solution instead of this mess.",
        "The AI model training is slow as hell. This damn implementation is crap. Microsoft Azure ML might be faster than our current setup.",
    ]

    # Build conversation array to reach target size
    messages = []
    current_size = 0
    target_size = size_kb * 1024

    base_messages = pattern_messages if with_patterns else clean_messages

    while current_size < target_size:
        for msg in base_messages:
            conversation_entry = {"role": "user" if len(messages) % 2 == 0 else "assistant", "content": msg, "timestamp": "2024-01-01T00:00:00Z"}
            messages.append(conversation_entry)
            current_size += len(str(conversation_entry))
            if current_size >= target_size:
                break

    return {"messages": messages, "metadata": {"size": size_kb, "count": len(messages)}}


def benchmark_python(data: Any, config: SearchReplaceConfig, patterns: List[Tuple[re.Pattern[str], str]], iterations: int, warmup: int = 5) -> Tuple[List[float], bool]:
    """Benchmark Python implementation (pure Python, no Rust)."""
    for _ in range(warmup):
        _process_container(data, config, patterns, use_rust=False)

    times = []
    modified = False
    for _ in range(iterations):
        start = time.perf_counter()
        m, _ = _process_container(data, config, patterns, use_rust=False)
        times.append(time.perf_counter() - start)
        modified = m

    return times, modified


def benchmark_rust(data: Any, config: SearchReplaceConfig, iterations: int, warmup: int = 5) -> Tuple[List[float], bool]:
    """Benchmark Rust implementation with native Python objects."""
    if not RUST_AVAILABLE:
        return [], False

    # Create Rust plugin instance
    rust_plugin = SearchReplacePluginRust({"words": [{"search": w.search, "replace": w.replace} for w in config.words]})

    for _ in range(warmup):
        rust_plugin.process_nested(data)

    times = []
    modified = False
    for _ in range(iterations):
        start = time.perf_counter()
        m, _ = rust_plugin.process_nested(data)
        times.append(time.perf_counter() - start)
        modified = m

    return times, modified


def run_scenario(name: str, data: Any, config: SearchReplaceConfig, patterns: List[Tuple[re.Pattern[str], str]], iterations: int, warmup: int = 5):
    """Run benchmark scenario."""
    print(f"\n{'=' * 70}")
    print(f"Scenario: {name}")
    print(f"{'=' * 70}")

    # Python
    print("Running Python...", end=" ", flush=True)
    py_times, py_modified = benchmark_python(data, config, patterns, iterations, warmup)
    py_mean = statistics.mean(py_times) * 1000
    py_median = statistics.median(py_times) * 1000
    py_stdev = statistics.stdev(py_times) * 1000 if len(py_times) > 1 else 0
    print(f"✓ ({py_mean:.3f} ms/iter, modified={py_modified})")

    if RUST_AVAILABLE:
        # Rust
        print("Running Rust...", end=" ", flush=True)
        rust_times, rust_modified = benchmark_rust(data, config, iterations, warmup)
        rust_mean = statistics.mean(rust_times) * 1000
        rust_median = statistics.median(rust_times) * 1000
        rust_stdev = statistics.stdev(rust_times) * 1000 if len(rust_times) > 1 else 0
        speedup = py_mean / rust_mean if rust_mean > 0 else 0
        print(f"✓ ({rust_mean:.3f} ms/iter, modified={rust_modified})")

        print("\n📊 Results:")
        print(f"  Python:                {py_mean:.3f} ms ±{py_stdev:.3f} (median: {py_median:.3f})")
        print(f"  Rust:                  {rust_mean:.3f} ms ±{rust_stdev:.3f} (median: {rust_median:.3f}) - {speedup:.2f}x faster 🚀")

        if py_modified != rust_modified:
            print(f"\n  ⚠️  WARNING: Different modification status! Python={py_modified}, Rust={rust_modified}")
    else:
        print("\n📊 Results:")
        print(f"  Python: {py_mean:.3f} ms ±{py_stdev:.3f} (median: {py_median:.3f})")
        print("  Rust: Not available")


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments for benchmark configuration."""
    parser = argparse.ArgumentParser(description="Native Python object performance comparison")
    parser.add_argument("--iterations", type=int, default=10000, help="Iterations per scenario")
    parser.add_argument("--warmup", type=int, default=100, help="Warmup iterations")
    return parser.parse_args()


def create_benchmark_config() -> SearchReplaceConfig:
    """Create search/replace configuration for benchmark scenarios.

    Patterns focus on:
    - Content moderation (profanity filtering)
    - Terminology standardization (abbreviation expansion)
    - Brand name normalization (consistent formatting)
    """
    return SearchReplaceConfig(
        words=[
            # Content moderation - profanity filtering
            SearchReplace(search=r"\bcrap\b", replace="crud"),
            SearchReplace(search=r"\bdamn\b", replace="darn"),
            SearchReplace(search=r"\bhell\b", replace="heck"),
            # Terminology standardization - expand abbreviations for clarity
            SearchReplace(search=r"\bAI\b", replace="artificial intelligence"),
            # Brand name normalization - consistent formatting
            SearchReplace(search=r"\bMicrosoft\b", replace="MS"),
            SearchReplace(search=r"\bIBM\b", replace="International Business Machines"),
        ]
    )


def compile_patterns(config: SearchReplaceConfig) -> List[Tuple[re.Pattern[str], str]]:
    """Compile regex patterns from configuration, skipping invalid patterns.

    Args:
        config: Search/replace configuration with pattern definitions

    Returns:
        List of (compiled_pattern, replacement) tuples
    """
    patterns = []
    for word in config.words:
        try:
            compiled_pattern = re.compile(word.search)
            patterns.append((compiled_pattern, word.replace))
        except re.error:
            # Silently skip invalid patterns (matches current behavior)
            pass
    return patterns


def get_benchmark_scenarios() -> List[Tuple[int, bool, str]]:
    """Define benchmark scenarios as (size_kb, with_patterns, name) tuples."""
    return [
        (1, False, "1KB (no patterns)"),
        (1, True, "1KB (with patterns)"),
        (5, False, "5KB (no patterns)"),
        (5, True, "5KB (with patterns)"),
    ]


def print_benchmark_header(iterations: int, warmup: int) -> None:
    """Print benchmark configuration header."""
    print("🔍 Regex Filter Performance (Native Python Objects)")
    print(f"Iterations: {iterations} (+ {warmup} warmup)")
    print(f"Rust available: {'✓' if RUST_AVAILABLE else '✗'}")


def print_benchmark_footer() -> None:
    """Print benchmark completion footer."""
    print(f"\n{'=' * 70}")
    print("✅ Benchmark complete!")
    print(f"{'=' * 70}\n")


def main():
    """Run performance comparison benchmarks for regex filter."""
    # Parse arguments
    args = parse_arguments()

    # Display configuration
    print_benchmark_header(args.iterations, args.warmup)

    # Setup benchmark configuration
    config = create_benchmark_config()
    patterns = compile_patterns(config)

    # Run all scenarios
    for size_kb, with_patterns, name in get_benchmark_scenarios():
        data = generate_test_data(size_kb, with_patterns)
        run_scenario(name, data, config, patterns, args.iterations, args.warmup)

    # Display completion
    print_benchmark_footer()


if __name__ == "__main__":
    main()
