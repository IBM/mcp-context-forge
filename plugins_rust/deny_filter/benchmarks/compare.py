#!/usr/bin/env python3
"""
Benchmark comparison between Python and Rust deny list implementations.
This module provides the core benchmarking functionality that can be used
both as a standalone script and within pytest tests.
"""

import json
import logging
import statistics
from pathlib import Path
from typing import List, Dict, Any, Type, Protocol, runtime_checkable, Optional

from mcpgateway.plugins.framework import PluginConfig, PluginContext
from mcpgateway.plugins.framework.hooks.prompts import (
    PromptHookType,
    PromptPrehookPayload,
    PromptPrehookResult,
)
from mcpgateway.plugins.framework.models import GlobalContext
from mcpgateway.services.logging_service import LoggingService

from plugins.deny_filter.deny import DenyListPlugin
from plugins.deny_filter.deny_ac import DenyListAcPlugin
from plugins.deny_filter.deny_rust import DenyListPluginRust
from plugins.deny_filter.deny_rust_rs import DenyListPluginRustRs

WARMUP_RUNS = 3000
BENCHMARK_RUNS = 10000
CONFIG_FILES = [
    "tests/data/deny_check_config_10.json",
    "tests/data/deny_check_config_100.json",
    "tests/data/deny_check_config_200.json",
]
ALL_IMPLS: List[Type["PromptPreFetchPlugin"]] = [
    DenyListPlugin,
    DenyListAcPlugin,
    DenyListPluginRust,
    DenyListPluginRustRs,
]

loggingSvc = LoggingService()
loggingSvc.get_logger("plugins.deny_filter.deny").setLevel(logging.ERROR)
loggingSvc.get_logger("plugins.deny_filter.deny_rust").setLevel(logging.ERROR)
loggingSvc.get_logger("plugins.deny_filter.deny_rust_rs").setLevel(logging.ERROR)
loggingSvc.get_logger("plugins.deny_filter.deny_rust_daac").setLevel(logging.ERROR)
loggingSvc.get_logger("plugins.deny_filter.deny_ac").setLevel(logging.ERROR)

@runtime_checkable
class PromptPreFetchPlugin(Protocol):
    """Protocol for plugins that implement prompt_pre_fetch hook."""

    def __init__(
        self,
        config: PluginConfig,
    ) -> None: ...

    async def prompt_pre_fetch(
        self, payload: PromptPrehookPayload, _context: PluginContext
    ) -> PromptPrehookResult:
        """The plugin hook run before a prompt is retrieved and rendered."""
        ...


def load_config(config_path: str) -> Dict[str, Any]:
    """Load the deny check configuration from JSON file."""
    config_file = Path(config_path)
    if not config_file.exists():
        config_file = Path(__file__).parent.parent / "tests" / "data" / Path(config_path).name

    with open(config_file, "r") as f:
        return json.load(f)


def create_plugin_instances(
    config: Dict[str, Any], plugin_type: Type[PromptPreFetchPlugin]
) -> List[tuple[str, PromptPreFetchPlugin]]:
    """Create plugin instances for each deny word list."""
    plugins: List[tuple[str, PromptPreFetchPlugin]] = []

    for deny_list in config["deny_word_lists"]:
        plugin_config = PluginConfig(
            name=f"deny_filter_{deny_list['name']}",
            kind=f"{plugin_type.__module__}.{plugin_type.__name__}",
            hooks=[PromptHookType.PROMPT_PRE_FETCH],
            priority=100,
            config={"words": deny_list["words"]},
        )

        plugin = plugin_type(config=plugin_config)
        plugins.append((deny_list["name"], plugin))

    return plugins


async def benchmark_plugin(
    plugins: List[tuple[str, PromptPreFetchPlugin]],
    sample_texts: List[Dict[str, Any]],
    config: Dict[str, Any],
    warmup_runs: int = WARMUP_RUNS,
    benchmark_runs: int = BENCHMARK_RUNS,
) -> Dict[str, Any]:
    """Benchmark prompt_pre_fetch execution for all combinations."""
    import time

    gctx = GlobalContext(request_id="deny-benchmark")
    ctx = PluginContext(global_context=gctx)

    results: Dict[str, Any] = {
        "total_combinations": len(plugins) * len(sample_texts),
        "warmup_runs": warmup_runs,
        "benchmark_runs": benchmark_runs,
        "total_time_us": 0.0,
        "combinations": [],
    }

    for plugin_name, plugin in plugins:
        for deny_list in config["deny_word_lists"]:
            if deny_list["name"] == plugin_name:
                break

        for sample in sample_texts:
            should_block = sample.get("should_block", False)

            payload = PromptPrehookPayload(
                prompt_id="benchmark_test",
                args={
                    "text": sample["text"],
                    "system": sample["text"],
                    "other": sample["text"],
                },
            )

            for _ in range(warmup_runs):
                await plugin.prompt_pre_fetch(payload, ctx)

            timings_us = []
            actual_blocked = None

            for i in range(benchmark_runs):
                start = time.perf_counter()
                result = await plugin.prompt_pre_fetch(payload, ctx)
                elapsed = time.perf_counter() - start
                timings_us.append(elapsed * 1_000_000)

                if i == 0:
                    actual_blocked = result.violation is not None

            timings_us.sort()
            median = statistics.median(timings_us)
            p99 = statistics.quantiles(timings_us, n=100)[-1]
            mean = statistics.mean(timings_us)
            min_time = min(timings_us)
            total_time_combination = sum(timings_us)

            combination_result: Dict[str, Any] = {
                "plugin_name": plugin_name,
                "sample_name": sample["name"],
                "sample_text_length": len(sample["text"]),
                "expected_block": should_block,
                "actual_blocked": actual_blocked,
                "matches_expected": actual_blocked == should_block,
                "timings": {
                    "median_us": round(median, 2),
                    "p99_us": round(p99, 2),
                    "mean_us": round(mean, 2),
                    "min_us": round(min_time, 2),
                    "total_us": round(total_time_combination, 2),
                },
            }

            results["combinations"].append(combination_result)
            results["total_time_us"] += total_time_combination

    return results


def get_cpu_info() -> str:
    """Get CPU model information."""
    try:
        import cpuinfo
        return cpuinfo.get_cpu_info().get('brand_raw', "CPU info unavailable")
    except Exception:
        return "CPU info unavailable"


def print_markdown_table(
    all_config_results: List[Dict[str, Any]],
    impls: List[Type[PromptPreFetchPlugin]],
):
    """Print results in Markdown table format similar to README.

    Args:
        all_config_results: Aggregated benchmark results per config.
        impls: List of implementation classes. First impl is used as baseline for speedup calculations.
    """
    print("\nMARKDOWN TABLE OUTPUT (for README)")
    impl_names = [impl.__name__ for impl in impls]

    header_parts = ["Config<br>Size"]
    separator_parts = [":----------"]
    for i, name in enumerate(impl_names):
        if i == 0:
            header_parts.append(f"{name}<br>Median")
            separator_parts.append(":---------------")
        else:
            header_parts.append(f"{name}<br>Median")
            header_parts.append("Speedup")
            separator_parts.append(":------------------")
            separator_parts.append(":---------")

    print("\n### Performance Comparison\n")

    cpu_info = get_cpu_info()
    print(f"**CPU:** {cpu_info}\n")

    print("| " + " | ".join(header_parts) + " |")
    print("| " + " | ".join(separator_parts) + " |")

    for config_result in all_config_results:
        word_count = config_result["word_count"]
        results = config_result["results"]

        all_impl_medians = {}

        for impl in impls:
            impl_name = impl.__name__
            impl_results = results[impl_name]
            medians = [
                c["timings"]["median_us"] for c in impl_results["combinations"]
            ]
            all_impl_medians[impl_name] = statistics.median(medians)

        avg_medians = all_impl_medians
        baseline_median = avg_medians[impl_names[0]]

        row_parts = [f"{word_count:<11}"]
        for i, name in enumerate(impl_names):
            if i == 0:
                row_parts.append(f"{avg_medians[name]:>14.2f}μs")
            else:
                speedup = (
                    baseline_median / avg_medians[name] if avg_medians[name] > 0 else 0
                )
                row_parts.append(f"{avg_medians[name]:>14.2f}μs")
                row_parts.append(f"{speedup:>8.2f}x")

        print("| " + " | ".join(row_parts) + " |")

    print()


async def run_benchmark(
    config_files: Optional[List[str]] = None,
    impls: Optional[List[Type[PromptPreFetchPlugin]]] = None,
    warmup_runs: int = 0,
    benchmark_runs: int = 0,
) -> Dict[str, Any]:
    """Run the full benchmark comparison.

    Args:
        config_files: List of config file paths. Defaults to CONFIG_FILES.
        impls: List of implementation classes. Defaults to ALL_IMPLS.
        warmup_runs: Number of warmup runs. Defaults to WARMUP_RUNS.
        benchmark_runs: Number of benchmark runs. Defaults to BENCHMARK_RUNS.

    Returns:
        Dictionary containing all benchmark results and metadata.
    """
    if config_files is None:
        config_files = CONFIG_FILES
    if impls is None:
        impls = ALL_IMPLS
    if not warmup_runs:
        warmup_runs = WARMUP_RUNS
    if not benchmark_runs:
        benchmark_runs = BENCHMARK_RUNS

    impl_names = [impl.__name__ for impl in impls]

    print(f"DENY CHECK BENCHMARK - {len(impl_names)} Implementation Comparison")
    print(f"Configs: {len(config_files)} files")
    print(f"Warmup Runs: {warmup_runs}")
    print(f"Benchmark Runs: {benchmark_runs}")
    print(f"Implementations: {', '.join(impl_names)}")

    all_config_results: list[dict[str, Any]] = []

    for config_path in config_files:
        config = load_config(config_path)

        word_count = sum(
            len(deny_list["words"]) for deny_list in config["deny_word_lists"]
        )

        print(f"\nCONFIG: {config_path} ({word_count} words)")

        run_results: Dict[str, Any] = {}

        for impl in impls:
            impl_name = impl.__name__
            print(f"\nBenchmarking {impl_name} implementation...")
            plugins = create_plugin_instances(config, impl)
            results = await benchmark_plugin(
                plugins,
                config["sample_texts"],
                config,
                warmup_runs=warmup_runs,
                benchmark_runs=benchmark_runs,
            )
            run_results[impl_name] = results

        all_config_results.append(
            {
                "config_path": config_path,
                "word_count": word_count,
                "config": config,
                "results": run_results,
            }
        )

    print("\nFINAL SUMMARY - ALL CONFIGURATIONS")

    for config_result in all_config_results:
        word_count: int = config_result["word_count"]
        config: Dict[str, Any] = config_result["config"]
        results: Dict[str, Any] = config_result["results"]

        print(f"\nConfiguration: {word_count} words")

        sample_text_sizes = [len(sample["text"]) for sample in config["sample_texts"]]
        if sample_text_sizes:
            print(
                f"Sample Text Sizes: min={min(sample_text_sizes)}, max={max(sample_text_sizes)}, avg={sum(sample_text_sizes) // len(sample_text_sizes)}"
            )
            print("-" * 80)

        all_impl_medians: Dict[str, float] = {}
        all_impl_p99s: Dict[str, float] = {}
        all_impl_totals: Dict[str, float] = {}

        for impl in impls:
            impl_name = impl.__name__
            impl_results: Dict[str, Any] = results[impl_name]

            medians = [
                c["timings"]["median_us"] for c in impl_results["combinations"]
            ]
            p99s = [c["timings"]["p99_us"] for c in impl_results["combinations"]]

            all_impl_medians[impl_name] = statistics.median(medians)
            all_impl_p99s[impl_name] = statistics.median(p99s)
            all_impl_totals[impl_name] = impl_results["total_time_us"]

        avg_medians = all_impl_medians
        avg_p99s = all_impl_p99s
        avg_totals = all_impl_totals

        metric_col_width = 20
        impl_col_widths = []
        for name in impl_names:
            formatted_median = f"{avg_medians[name]:.2f}μs"
            formatted_p99 = f"{avg_p99s[name]:.2f}μs"
            formatted_total = f"{avg_totals[name] / 1_000_000:.6f}s"
            impl_col_widths.append(
                max(
                    len(name),
                    len(formatted_median),
                    len(formatted_p99),
                    len(formatted_total),
                )
            )

        header = f"{'Metric':<{metric_col_width}}"
        for i, name in enumerate(impl_names):
            header += f" {name:<{impl_col_widths[i]}}"
        print(header)
        separator_width = metric_col_width + sum(impl_col_widths) + len(impl_names)
        print("-" * separator_width)

        median_row = f"{'Avg Median':<{metric_col_width}}"
        for i, name in enumerate(impl_names):
            median_row += f" {avg_medians[name]:>{impl_col_widths[i]}.2f}μs"
        print(median_row)

        p99_row = f"{'Avg P99':<{metric_col_width}}"
        for i, name in enumerate(impl_names):
            p99_row += f" {avg_p99s[name]:>{impl_col_widths[i]}.2f}μs"
        print(p99_row)

        total_row = f"{'Avg Total Time':<{metric_col_width}}"
        for i, name in enumerate(impl_names):
            total_row += f" {avg_totals[name] / 1_000_000:>{impl_col_widths[i]}.6f}s"
        print(total_row)

        first_name = impl_names[0]
        print(f"\nSpeedup vs {first_name}:")
        for name in impl_names[1:]:
            median_speedup = (
                avg_medians[first_name] / avg_medians[name]
                if avg_medians[name] > 0
                else 0
            )
            p99_speedup = (
                avg_p99s[first_name] / avg_p99s[name] if avg_p99s[name] > 0 else 0
            )
            total_speedup = (
                avg_totals[first_name] / avg_totals[name] if avg_totals[name] > 0 else 0
            )
            print(
                f"  {name}: {median_speedup:.2f}x (median), {p99_speedup:.2f}x (p99), {total_speedup:.2f}x (total)"
            )

    print_markdown_table(all_config_results, impls)

    return {
        "config_files": config_files,
        "impls": impl_names,
        "warmup_runs": warmup_runs,
        "benchmark_runs": benchmark_runs,
        "all_config_results": all_config_results,
    }


def validate_results(benchmark_results: Dict[str, Any]) -> None:
    """Validate benchmark results and raise assertions if mismatches found.

    Args:
        benchmark_results: Results dictionary from run_benchmark().

    Raises:
        AssertionError: If any implementation has mismatches.
    """
    all_config_results = benchmark_results["all_config_results"]
    impl_names = benchmark_results["impls"]

    for config_result in all_config_results:
        results = config_result["results"]
        for impl_name in impl_names:
            mismatches = [
                c
                for c in results[impl_name]["combinations"]
                if not c.get("matches_expected", True)
            ]

            assert (
                len(mismatches) == 0
            ), f"{impl_name} implementation has {len(mismatches)} mismatches in {config_result['config_path']}"


if __name__ == "__main__":
    import asyncio

    async def main():
        results = await run_benchmark()
        validate_results(results)
        print("\nAll validations passed!")

    asyncio.run(main())
