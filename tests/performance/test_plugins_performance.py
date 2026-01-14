# -*- coding: utf-8 -*-
"""Location: ./tests/performance/test_plugins_performance.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Performance profiling for plugins using cProfile.

This script profiles each plugin's hooks individually using the plugin manager
and cProfile. It generates detailed performance profiles and a summary table
showing average execution times per hook type per plugin.

Usage:
    python tests/performance/test_plugins_performance.py [--details]

Options:
    --details    Print detailed profile for each plugin-hook combination

Output:
    - Individual .prof files in prof/ directory for each plugin-hook combination
    - Summary table printed to stdout showing average times per plugin per hook
    - Detailed profiles (if --details is specified)
"""

# Standard
import argparse
import asyncio
from collections import defaultdict
import cProfile
import io
import logging
import os
import pstats
import sys
from pstats import SortKey
from typing import Any, Dict, Tuple

# Disable security warnings
logging.getLogger("mcpgateway.config").setLevel(logging.ERROR)
logging.getLogger("mcpgateway.observability").setLevel(logging.ERROR)

# Add repo root to PYTHONPATH
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(SCRIPT_DIR, "..", "..")
sys.path.insert(0, ROOT_DIR)

# First-Party
from mcpgateway.common.models import Message, PromptResult, ResourceContent, Role, TextContent  # noqa: E402
from mcpgateway.plugins.framework import (  # noqa: E402
    GlobalContext,
    PluginManager,
    PromptHookType,
    PromptPosthookPayload,
    PromptPrehookPayload,
    ResourceHookType,
    ResourcePostFetchPayload,
    ResourcePreFetchPayload,
    ToolHookType,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)

# Configuration
CONFIG_PATH = os.path.join(SCRIPT_DIR, "plugins", "config.yaml")
PROFILE_OUTPUT_DIR = os.path.join(SCRIPT_DIR, "plugins", "prof")
ITERATIONS = 1000  # Number of iterations per hook


def ensure_profile_dir() -> None:
    """Ensure the profile output directory exists."""
    os.makedirs(PROFILE_OUTPUT_DIR, exist_ok=True)


def create_sample_payloads() -> Dict[str, Any]:
    """Create sample payloads for each hook type.

    Returns:
        Dictionary mapping hook type names to sample payload objects
    """
    # Prompt pre-fetch payload
    prompt_pre = PromptPrehookPayload(
        prompt_id="test_prompt",
        args={
            "user": "test_user",
            "query": "What is the capital of France? My email is test@example.com",
            "context": "Additional context with SSN: 123-45-6789 and credit card: 4111-1111-1111-1111",
        },
    )

    # Prompt post-fetch payload
    message = Message(
        content=TextContent(type="text", text="The capital of France is Paris. Contact me at admin@test.com or call 555-123-4567."),
        role=Role.ASSISTANT,
    )
    prompt_result = PromptResult(messages=[message])
    prompt_post = PromptPosthookPayload(prompt_id="test_prompt", result=prompt_result)

    # Tool pre-invoke payload
    tool_pre = ToolPreInvokePayload(
        name="search_tool",
        args={
            "query": "search for crap information",
            "limit": 10,
            "filter": "type:document",
            "user_email": "user@example.com",
        },
    )

    # Tool post-invoke payload
    tool_post = ToolPostInvokePayload(
        name="search_tool",
        result={
            "status": "success",
            "results": [
                {"title": "Result 1", "snippet": "This is crap content with crud data"},
                {"title": "Result 2", "snippet": "Another crud result with sensitive info"},
            ],
            "count": 2,
            "metadata": {"query_time": 0.123, "source": "database"},
        },
    )

    # Resource pre-fetch payload
    resource_pre = ResourcePreFetchPayload(uri="https://example.com/document.txt", metadata={"version": "1.0", "encoding": "utf-8"})

    # Resource post-fetch payload
    resource_content = ResourceContent(
        type="resource",
        id="res-1",
        uri="https://example.com/document.txt",
        text="This document contains crap information and crud data. Contact admin@example.com for more details.",
    )
    resource_post = ResourcePostFetchPayload(uri="https://example.com/document.txt", content=resource_content)

    return {
        "prompt_pre_fetch": prompt_pre,
        "prompt_post_fetch": prompt_post,
        "tool_pre_invoke": tool_pre,
        "tool_post_invoke": tool_post,
        "resource_pre_fetch": resource_pre,
        "resource_post_fetch": resource_post,
    }


async def profile_plugin_hook(manager: PluginManager, plugin_name: str, hook_type: str, payload: Any, global_context: GlobalContext, iterations: int = ITERATIONS) -> Tuple[float, str]:
    """Profile a specific plugin's hook invocation.

    Args:
        manager: Plugin manager instance
        plugin_name: Name of the plugin to profile
        hook_type: Hook type (e.g., "prompt_pre_fetch")
        payload: Payload to pass to the hook
        global_context: Global context for hook invocation
        iterations: Number of iterations to run

    Returns:
        Tuple of (average_time_ms, profile_file_path)
    """
    # Map hook type strings to enum values
    hook_type_map = {
        "prompt_pre_fetch": PromptHookType.PROMPT_PRE_FETCH,
        "prompt_post_fetch": PromptHookType.PROMPT_POST_FETCH,
        "tool_pre_invoke": ToolHookType.TOOL_PRE_INVOKE,
        "tool_post_invoke": ToolHookType.TOOL_POST_INVOKE,
        "resource_pre_fetch": ResourceHookType.RESOURCE_PRE_FETCH,
        "resource_post_fetch": ResourceHookType.RESOURCE_POST_FETCH,
    }

    hook_enum = hook_type_map[hook_type]

    # Create profiler
    profiler = cProfile.Profile()

    # Profile the hook invocations
    profiler.enable()
    for _ in range(iterations):
        await manager.invoke_hook_for_plugin(plugin_name, hook_enum, payload, context=global_context)
    profiler.disable()

    # Save profile to file
    profile_filename = f"{plugin_name}_{hook_type}.prof"
    profile_path = os.path.join(PROFILE_OUTPUT_DIR, profile_filename)
    profiler.dump_stats(profile_path)

    # Calculate average time from stats
    stats = pstats.Stats(profiler)
    stats.strip_dirs()

    # Get cumulative time for invoke_hook_for_plugin calls
    # Note: ct (cumulative time) is in SECONDS
    # We need to find the invoke_hook_for_plugin function and get its average time
    avg_time_ms = 0.0
    for func_info, (cc, nc, tt, ct, callers) in stats.stats.items():
        # func_info is a tuple: (filename, line_number, function_name)
        filename, line_num, func_name = func_info
        if func_name == "invoke_hook_for_plugin":
            # ct is cumulative time in SECONDS for ALL calls
            # cc is the actual number of calls to this function
            # Average time per call = ct / cc (in seconds)
            # Convert to milliseconds by multiplying by 1000
            avg_time_ms = (ct / cc) * 1000 if cc > 0 else 0.0
            break

    return avg_time_ms, profile_path


async def profile_all_plugins(manager: PluginManager, show_details: bool = False) -> Dict[str, Dict[str, float]]:
    """Profile all enabled plugins and their hooks.

    Args:
        manager: Initialized plugin manager
        show_details: If True, print detailed profile for each plugin-hook combination

    Returns:
        Dictionary mapping plugin names to dictionaries of hook types to average times in ms
    """
    # Create sample payloads
    payloads = create_sample_payloads()

    # Create global context
    global_context = GlobalContext(request_id="perf-test-request", server_id="perf-test-server")

    # Results storage: plugin_name -> hook_type -> avg_time_ms
    results: Dict[str, Dict[str, float]] = defaultdict(dict)

    # Get all plugins from manager
    plugins_info = []
    for plugin_config in manager.config.plugins:
        if plugin_config.mode != "disabled":
            plugins_info.append((plugin_config.name, plugin_config.hooks))

    print(f"\nProfiling {len(plugins_info)} enabled plugins...")
    print(f"Iterations per hook: {ITERATIONS}")
    print("=" * 80)

    # Profile each plugin's hooks
    for plugin_name, hooks in plugins_info:
        print(f"\nProfiling plugin: {plugin_name}")
        print(f"  Hooks: {', '.join(hooks)}")

        for hook_type in hooks:
            if hook_type not in payloads:
                print(f"  ⚠ Skipping {hook_type} - no sample payload defined")
                continue

            try:
                print(f"  • Profiling {hook_type}...", end=" ", flush=True)
                avg_time_ms, profile_path = await profile_plugin_hook(manager, plugin_name, hook_type, payloads[hook_type], global_context, ITERATIONS)
                results[plugin_name][hook_type] = avg_time_ms
                print(f"✓ {avg_time_ms:.3f}ms avg (saved to {os.path.relpath(profile_path, ROOT_DIR)})")

                # Print detailed profile if requested
                if show_details:
                    print_detailed_profile(profile_path, limit=20)
            except Exception as e:
                print(f"✗ Error: {e}")
                results[plugin_name][hook_type] = -1.0

    return dict(results)


def print_summary_table(results: Dict[str, Dict[str, float]]) -> None:
    """Print a formatted summary table of profiling results.

    Args:
        results: Dictionary mapping plugin names to hook type to average times
    """
    # Get all unique hook types
    all_hooks = set()
    for plugin_hooks in results.values():
        all_hooks.update(plugin_hooks.keys())
    hook_types = sorted(all_hooks)

    # Calculate column widths
    plugin_col_width = max(len(name) for name in results.keys()) + 2
    hook_col_width = 12  # Fixed width for hook columns

    # Print header
    print("\n" + "=" * 80)
    print("PERFORMANCE SUMMARY TABLE")
    print("=" * 80)
    print(f"\n{'Plugin':<{plugin_col_width}}", end="")
    for hook_type in hook_types:
        # Abbreviate hook names for table
        abbrev = hook_type.replace("prompt_", "P:").replace("tool_", "T:").replace("resource_", "R:").replace("_fetch", "").replace("_invoke", "")
        print(f"{abbrev:>{hook_col_width}}", end="")
    print()

    # Print separator
    print("-" * plugin_col_width, end="")
    for _ in hook_types:
        print("-" * hook_col_width, end="")
    print()

    # Print data rows
    for plugin_name in sorted(results.keys()):
        print(f"{plugin_name:<{plugin_col_width}}", end="")
        for hook_type in hook_types:
            avg_time = results[plugin_name].get(hook_type)
            if avg_time is None:
                print(f"{'—':>{hook_col_width}}", end="")  # Not implemented
            elif avg_time < 0:
                print(f"{'ERROR':>{hook_col_width}}", end="")  # Error
            else:
                print(f"{avg_time:>{hook_col_width - 2}.3f}ms", end="")
        print()

    # Print legend
    print("\n" + "=" * 80)
    print("LEGEND:")
    print("  P: = Prompt hooks   T: = Tool hooks   R: = Resource hooks")
    print("  pre/post = Hook timing   — = Not implemented   ERROR = Profiling failed")
    print(f"  All times are average per invocation over {ITERATIONS} iterations")
    print("=" * 80)


def print_detailed_profile(profile_path: str, limit: int = 20) -> None:
    """Print detailed statistics from a profile file.

    Args:
        profile_path: Path to the .prof file
        limit: Number of top functions to display
    """
    print(f"\n{'=' * 80}")
    print(f"Detailed Profile: {os.path.basename(profile_path)}")
    print("=" * 80)

    stats = pstats.Stats(profile_path)
    stats.strip_dirs()
    stats.sort_stats(SortKey.CUMULATIVE)

    # Create a string buffer to capture output
    s = io.StringIO()
    ps = pstats.Stats(profile_path, stream=s)
    ps.strip_dirs()
    ps.sort_stats(SortKey.CUMULATIVE)
    ps.print_stats(limit)

    print(s.getvalue())


async def main():
    """Main execution function."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Profile plugin performance using cProfile",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with summary table only
  python tests/performance/test_plugins_performance.py

  # Run with detailed profiles for each plugin-hook
  python tests/performance/test_plugins_performance.py --details
        """,
    )
    parser.add_argument("--details", action="store_true", help="Print detailed profile for each plugin-hook combination")
    args = parser.parse_args()

    print("=" * 80)
    print("MCP GATEWAY PLUGIN PERFORMANCE PROFILER")
    print("=" * 80)
    print(f"Config: {CONFIG_PATH}")
    print(f"Output: {PROFILE_OUTPUT_DIR}/")
    if args.details:
        print("Mode: Detailed profiles enabled")

    # Ensure output directory exists
    ensure_profile_dir()

    # Initialize plugin manager (do NOT profile this)
    print("\nInitializing plugin manager...")
    manager = PluginManager(CONFIG_PATH)
    await manager.initialize()

    if not manager.initialized:
        print("✗ Plugin manager failed to initialize")
        return

    print(f"✓ Plugin manager initialized with {manager.plugin_count} plugins")

    # Profile all plugins
    results = await profile_all_plugins(manager, show_details=args.details)

    # Print summary table
    print_summary_table(results)

    # Shutdown manager
    await manager.shutdown()
    print("\n✓ Performance profiling complete")
    print(f"✓ Profile files saved to: {os.path.relpath(PROFILE_OUTPUT_DIR, ROOT_DIR)}/")


if __name__ == "__main__":
    asyncio.run(main())
