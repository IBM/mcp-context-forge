import asyncio
import argparse
import json
from pathlib import Path
from unittest.mock import patch
import statistics
import sys
import time
from typing import Any, Literal
from mcpgateway.plugins.framework import (
    PluginConfig,
    ResourceHookType,
)

# Try to import Rust implementation
try:
    from url_reputation_rust import URLReputationPlugin as RustPlugin
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    print("Rust implementation not available.")


# Add plugins directory to path to import Python implementation
plugins_path = Path(__file__).parent.parent.parent / "plugins" / "url_reputation"
if plugins_path.exists():
    sys.path.insert(0, str(plugins_path))
else:
    print(f"Warning: Python implementation path not found: {plugins_path}")
    print("Benchmark will only test Rust implementation if available.")


class Payload:
    def __init__(self, url):
        self.uri = url


def load_bench_config(config_path: str = "bench_config.json"):
    """Load benchmark configuration from JSON file."""
    config_file = Path(__file__).parent / config_path
    if not config_file.exists():
        raise FileNotFoundError(f"Benchmark config file not found: {config_file}")

    with open(config_file, 'r') as f:
        return json.load(f)


def generate_payloads(size: int, urls: list[str], url_multiplier: int = 1):
    """Return a list of urls to be used in the benchmark"""
    # Apply url_multiplier to expand the URL list
    expanded_urls = urls * url_multiplier
    url_count = len(expanded_urls)
    repeated = expanded_urls * (size // url_count)
    remaining = expanded_urls[:(size % url_count)]

    return [Payload(url) for url in repeated + remaining]


async def run_benchmark(language: Literal["python", "rust"], config: PluginConfig, iterations: int, urls: list[str], url_multiplier: int = 1, warmup: int = 5):
    """Run benchmark for specified language implementation."""
    if language == "rust" and not RUST_AVAILABLE:
        return [], 0

    if language == "python":
        try:
            import url_reputation
            with patch.object(url_reputation, '_RUST_AVAILABLE', False):
                from url_reputation import URLReputationPlugin
                plugin = URLReputationPlugin(config)
                
                # Warmup phase
                for payload in generate_payloads(warmup, urls, url_multiplier):
                    await plugin.resource_pre_fetch(payload, None)

                # Actual benchmark
                times = []
                for payload in generate_payloads(iterations, urls, url_multiplier):
                    start = time.perf_counter()
                    await plugin.resource_pre_fetch(payload, None)
                    times.append(time.perf_counter() - start)

                return times, len(times)
        except ImportError as e:
            print(f"Warning: Could not import Python implementation: {e}")
            return [], 0
    else:
        try:
            import url_reputation
            with patch.object(url_reputation, '_RUST_AVAILABLE', True):
                from url_reputation import URLReputationPlugin
                plugin = URLReputationPlugin(config)
                
                # Warmup phase
                for payload in generate_payloads(warmup, urls, url_multiplier):
                    await plugin.resource_pre_fetch(payload, None)

                # Actual benchmark
                times = []
                for payload in generate_payloads(iterations, urls, url_multiplier):
                    start = time.perf_counter()
                    await plugin.resource_pre_fetch(payload, None)
                    times.append(time.perf_counter() - start)

                return times, len(times)
        except ImportError as e:
            print(f"Warning: Could not import url_reputation wrapper: {e}")
            return [], 0


async def run_scenario(name: str, config: PluginConfig, iterations: int, urls: list[str], url_multiplier: int = 1, warmup: int = 5):
    """Run benchmark scenario and return results."""
    print(f"Running scenario: {name}...", end=" ", flush=True)

    results = {}
    for language in ["python", "rust"]:
        benchmark_result = await run_benchmark(language, config, iterations, urls, url_multiplier, warmup)
        
        if benchmark_result is None or len(benchmark_result) != 2:
            if language == "rust":
                print("✗ (Rust not available)")
                return None
            continue
            
        times, count = benchmark_result

        if not times:
            if language == "rust":
                print("✗ (Rust not available)")
                return None
            continue

        mean = statistics.mean(times) * 1_000_000
        median = statistics.median(times) * 1_000_000
        stdev = statistics.stdev(times) * 1_000_000 if len(times) > 1 else 0
        results[language] = {"mean": mean, "median": median, "stdev": stdev, "count": count}

    if len(results) < 2:
        print("✗ (incomplete)")
        return None

    speedup = results["python"]["mean"] / results["rust"]["mean"] if results["rust"]["mean"] > 0 else 0
    print(f"✓ (speedup: {speedup:.2f}x)")

    return {
        "name": name,
        "python": results["python"],
        "rust": results["rust"],
        "speedup": speedup
    }


async def main():
    parser = argparse.ArgumentParser(description="Rust vs Python benchmark for URL reputation plugin")
    parser.add_argument("--iterations", type=int, default=500_000, help="Iterations per scenario")
    parser.add_argument("--warmup", type=int, default=1000, help="Warmup iterations")
    parser.add_argument("--config", type=str, default="bench_config.json", help="Path to benchmark config file")
    args = parser.parse_args()

    print("🔍 URL Reputation benchmark (Native Python Objects)")
    print(f"Iterations: {args.iterations} (+ {args.warmup} warmup)")
    print(f"Rust available: {'✓' if RUST_AVAILABLE else '✗'}")

    # Load benchmark configuration
    try:
        bench_config = load_bench_config(args.config)
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Error parsing config file: {e}")
        sys.exit(1)

    # Extract configuration
    urls = bench_config.get("urls", [])
    blocked_patterns = bench_config.get("blocked_patterns", [])
    blocked_domains = bench_config.get("blocked_domains", [])
    url_multiplier = bench_config.get("url_multiplier", 1)

    if not urls:
        print("❌ Error: No URLs found in config file")
        sys.exit(1)

    print(f"Loaded {len(urls)} URLs, {len(blocked_patterns)} patterns, {len(blocked_domains)} domains")
    print(f"URL multiplier: {url_multiplier}x")

    # Create plugin configuration
    plugin_config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "blocked_domains": blocked_domains,
            "blocked_patterns": blocked_patterns,
        },
    )

    # Run benchmark
    result = await run_scenario(
        "URL Reputation Benchmark",
        plugin_config,
        args.iterations,
        urls,
        url_multiplier,
        args.warmup
    )

    # Print results
    print(f"\n{'=' * 100}")
    print("📊 BENCHMARK RESULTS")
    print(f"{'=' * 100}")

    if not result:
        print("❌ No results to display")
        return

    # Detailed results
    print(f"\n{'Metric':<30} {'Python':<25} {'Rust':<25}")
    print(f"{'-' * 30} {'-' * 25} {'-' * 25}")

    python_mean = result["python"]["mean"]
    python_median = result["python"]["median"]
    python_stdev = result["python"]["stdev"]
    rust_mean = result["rust"]["mean"]
    rust_median = result["rust"]["median"]
    rust_stdev = result["rust"]["stdev"]
    speedup = result["speedup"]

    print(f"{'Mean (μs/iter)':<30} {python_mean:>20.2f}    {rust_mean:>20.2f}")
    print(f"{'Median (μs/iter)':<30} {python_median:>20.2f}    {rust_median:>20.2f}")
    print(f"{'Std Dev (μs/iter)':<30} {python_stdev:>20.2f}    {rust_stdev:>20.2f}")
    print(f"{'Iterations':<30} {result['python']['count']:>20}    {result['rust']['count']:>20}")

    print(f"\n{'-' * 100}")
    print(f"🚀 Speedup: {speedup:.2f}x faster with Rust")
    print(f"{'=' * 100}")
    print("✅ Benchmark complete!")
    print(f"{'=' * 100}\n")


if __name__ == "__main__":
    asyncio.run(main())
