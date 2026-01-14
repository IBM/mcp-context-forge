#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Location: ./tests/performance/utils/analyze_profiles.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Helper script to analyze and compare plugin performance profiles.

Usage:
    # Analyze a single profile
    python utils/analyze_profiles.py prof/PIIFilterPlugin_tool_pre_invoke.prof

    # Compare two profiles
    python utils/analyze_profiles.py prof/baseline.prof prof/current.prof --compare

    # Compare all matching profiles between two directories
    python utils/analyze_profiles.py prof_baseline prof_current --compare-all

    # Generate CSV report
    python utils/analyze_profiles.py --all --csv results.csv
"""

# Standard
import argparse
import csv
import glob
import os
import pstats
import sys
from typing import Any, Dict


def analyze_profile(profile_path: str, limit: int = 20) -> Dict[str, Any]:
    """Analyze a single profile file.

    Args:
        profile_path: Path to .prof file
        limit: Number of top functions to analyze

    Returns:
        Dictionary with analysis results
    """
    stats = pstats.Stats(profile_path)
    stats.strip_dirs()
    stats.sort_stats("cumulative")

    # Get top functions
    top_functions = []
    for idx, (func_info, (cc, nc, tt, ct, callers)) in enumerate(stats.stats.items()):
        if idx >= limit:
            break

        filename, line, func_name = func_info
        top_functions.append(
            {
                "function": f"{filename}:{line}({func_name})",
                "calls": cc,
                "total_time": tt,
                "cumulative_time": ct,
                "per_call_time": ct / cc if cc > 0 else 0,
            }
        )

    # Calculate total stats
    total_calls = sum(cc for cc, nc, tt, ct, callers in stats.stats.values())
    total_time = sum(tt for cc, nc, tt, ct, callers in stats.stats.values())

    return {
        "profile_path": profile_path,
        "total_calls": total_calls,
        "total_time": total_time,
        "top_functions": top_functions,
    }


def compare_profiles(baseline_path: str, current_path: str) -> None:
    """Compare two profile files and show differences.

    Args:
        baseline_path: Path to baseline .prof file
        current_path: Path to current .prof file
    """
    baseline = pstats.Stats(baseline_path)
    current = pstats.Stats(current_path)

    baseline.strip_dirs()
    current.strip_dirs()

    # Get total times
    baseline_total = sum(tt for cc, nc, tt, ct, callers in baseline.stats.values())
    current_total = sum(tt for cc, nc, tt, ct, callers in current.stats.values())

    print(f"\n{'=' * 80}")
    print("PROFILE COMPARISON")
    print("=" * 80)
    print(f"\nBaseline: {os.path.basename(baseline_path)}")
    print(f"Current:  {os.path.basename(current_path)}")
    print("\nTotal Time:")
    print(f"  Baseline: {baseline_total:.6f}s")
    print(f"  Current:  {current_total:.6f}s")

    time_diff = current_total - baseline_total
    pct_diff = (time_diff / baseline_total * 100) if baseline_total > 0 else 0

    if time_diff > 0:
        print(f"  Change:   +{time_diff:.6f}s (+{pct_diff:.1f}%) ⚠️  SLOWER")
    else:
        print(f"  Change:   {time_diff:.6f}s ({pct_diff:.1f}%) ✓ FASTER")

    # Compare top functions
    print(f"\n{'Function':<50} {'Baseline':>12} {'Current':>12} {'Change':>12}")
    print("-" * 90)

    # Get top 15 functions from baseline
    baseline_sorted = sorted(baseline.stats.items(), key=lambda x: x[1][3], reverse=True)[:15]

    for func_info, (b_cc, b_nc, b_tt, b_ct, b_callers) in baseline_sorted:
        filename, line, func_name = func_info
        func_str = f"{filename}:{func_name}"[:48]

        # Find corresponding function in current
        c_ct = 0
        if func_info in current.stats:
            c_cc, c_nc, c_tt, c_ct, c_callers = current.stats[func_info]

        diff = c_ct - b_ct
        if b_ct > 0:
            pct = (diff / b_ct * 100)
            diff_str = f"{diff:+.6f}s ({pct:+.0f}%)"
        else:
            diff_str = "N/A"

        print(f"{func_str:<50} {b_ct:>10.6f}s {c_ct:>10.6f}s {diff_str:>15}")


def compare_all_profiles(baseline_dir: str, current_dir: str) -> None:
    """Compare all matching profile files between two directories.

    Args:
        baseline_dir: Directory containing baseline .prof files
        current_dir: Directory containing current .prof files
    """
    # Get all .prof files from baseline directory
    baseline_pattern = os.path.join(baseline_dir, "*.prof")
    baseline_files = glob.glob(baseline_pattern)

    if not baseline_files:
        print(f"No .prof files found in baseline directory: {baseline_dir}")
        return

    # Track comparison statistics and times
    compared = 0
    missing = 0
    comparison_results = []

    for baseline_path in sorted(baseline_files):
        baseline_name = os.path.basename(baseline_path)
        current_path = os.path.join(current_dir, baseline_name)

        if os.path.exists(current_path):
            # Get total times for summary
            baseline_stats = pstats.Stats(baseline_path)
            current_stats = pstats.Stats(current_path)

            baseline_total = sum(tt for cc, nc, tt, ct, callers in baseline_stats.stats.values())
            current_total = sum(tt for cc, nc, tt, ct, callers in current_stats.stats.values())

            comparison_results.append({
                'name': baseline_name,
                'baseline_time': baseline_total,
                'current_time': current_total
            })

            # Show detailed comparison
            compare_profiles(baseline_path, current_path)
            compared += 1
        else:
            print(f"\n⚠️  Warning: No matching file found for {baseline_name} in {current_dir}")
            missing += 1

    # Summary table
    print(f"\n{'=' * 100}")
    print("COMPARISON SUMMARY")
    print("=" * 100)
    print(f"{'Test':<50} {'Baseline (s)':>15} {'Current (s)':>15} {'Change':>15}")
    print("-" * 100)

    total_baseline = 0
    total_current = 0

    for result in comparison_results:
        baseline_time = result['baseline_time']
        current_time = result['current_time']
        total_baseline += baseline_time
        total_current += current_time

        time_diff = current_time - baseline_time
        pct_diff = (time_diff / baseline_time * 100) if baseline_time > 0 else 0

        change_str = f"{pct_diff:+.1f}%"
        print(f"{result['name']:<50} {baseline_time:>15.6f} {current_time:>15.6f} {change_str:>15}")

    # Overall change
    print("-" * 100)
    overall_diff = total_current - total_baseline
    overall_pct = (overall_diff / total_baseline * 100) if total_baseline > 0 else 0

    print(f"{'TOTAL':<50} {total_baseline:>15.6f} {total_current:>15.6f} {overall_pct:+.1f}%")
    print("=" * 100)

    if overall_pct > 0:
        print(f"\n⚠️  Overall Performance: {overall_pct:+.1f}% SLOWER")
    elif overall_pct < 0:
        print(f"\n✓ Overall Performance: {abs(overall_pct):.1f}% FASTER")
    else:
        print("\n= Overall Performance: No change")

    print(f"\nFiles compared: {compared}")
    print(f"Files missing:  {missing}")


def generate_csv_report(output_path: str) -> None:
    """Generate CSV report of all profiles in prof/ directory.

    Args:
        output_path: Path to output CSV file
    """
    profile_files = glob.glob("prof/*.prof")

    with open(output_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Plugin", "Hook", "Total_Time_s", "Total_Calls", "Avg_Time_ms", "Top_Function", "Top_Function_Time_s"])

        for profile_path in sorted(profile_files):
            basename = os.path.basename(profile_path)
            if "_" not in basename:
                continue

            # Parse plugin name and hook from filename
            parts = basename.replace(".prof", "").split("_")
            if len(parts) < 2:
                continue

            # Handle multi-word plugin names (e.g., PIIFilterPlugin)
            # Find the hook type (should be last 2-3 parts joined by _)
            hook_parts = []
            plugin_parts = []
            found_hook = False

            for part in reversed(parts):
                if not found_hook and part in ["pre", "post", "fetch", "invoke"]:
                    hook_parts.insert(0, part)
                elif not found_hook:
                    hook_parts.insert(0, part)
                    found_hook = True
                else:
                    plugin_parts.insert(0, part)

            plugin_name = "_".join(plugin_parts)
            hook_type = "_".join(hook_parts)

            # Analyze profile
            analysis = analyze_profile(profile_path, limit=1)

            # Get top function
            top_func = analysis["top_functions"][0] if analysis["top_functions"] else {}
            top_func_name = top_func.get("function", "N/A")
            top_func_time = top_func.get("cumulative_time", 0)

            # Calculate average time (assuming 1000 iterations)
            avg_time_ms = (analysis["total_time"] / 1000) * 1000

            writer.writerow(
                [
                    plugin_name,
                    hook_type,
                    f"{analysis['total_time']:.6f}",
                    analysis["total_calls"],
                    f"{avg_time_ms:.3f}",
                    top_func_name,
                    f"{top_func_time:.6f}",
                ]
            )

    print(f"✓ CSV report generated: {output_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Analyze plugin performance profiles")
    parser.add_argument("profiles", nargs="*", help="Profile file(s) or directories to analyze")
    parser.add_argument("--compare", action="store_true", help="Compare two profiles (requires exactly 2 profile arguments)")
    parser.add_argument("--compare-all", action="store_true", help="Compare all matching profiles between two directories (requires exactly 2 directory arguments)")
    parser.add_argument("--all", action="store_true", help="Analyze all profiles in prof/ directory")
    parser.add_argument("--csv", type=str, help="Generate CSV report (use with --all)")
    parser.add_argument("--limit", type=int, default=20, help="Number of top functions to show (default: 20)")

    args = parser.parse_args()

    if args.compare_all:
        if len(args.profiles) != 2:
            print("Error: --compare-all requires exactly 2 directory arguments")
            sys.exit(1)
        compare_all_profiles(args.profiles[0], args.profiles[1])

    elif args.compare:
        if len(args.profiles) != 2:
            print("Error: --compare requires exactly 2 profile files")
            sys.exit(1)
        compare_profiles(args.profiles[0], args.profiles[1])

    elif args.all and args.csv:
        generate_csv_report(args.csv)

    elif args.all:
        profile_files = glob.glob("plugins/prof/*.prof")
        for profile_path in sorted(profile_files):
            analysis = analyze_profile(profile_path, limit=args.limit)
            print(f"\n{'=' * 80}")
            print(f"Profile: {os.path.basename(analysis['profile_path'])}")
            print("=" * 80)
            print(f"Total calls: {analysis['total_calls']:,}")
            print(f"Total time:  {analysis['total_time']:.6f}s")
            print(f"\nTop {args.limit} functions:")
            print(f"{'Function':<60} {'Calls':>10} {'Time':>12} {'Cumul':>12}")
            print("-" * 100)
            for func in analysis["top_functions"]:
                print(
                    f"{func['function']:<60} {func['calls']:>10} {func['total_time']:>12.6f} {func['cumulative_time']:>12.6f}"
                )

    elif len(args.profiles) == 1:
        analysis = analyze_profile(args.profiles[0], limit=args.limit)
        print(f"\n{'=' * 80}")
        print(f"Profile: {os.path.basename(analysis['profile_path'])}")
        print("=" * 80)
        print(f"Total calls: {analysis['total_calls']:,}")
        print(f"Total time:  {analysis['total_time']:.6f}s")
        print(f"\nTop {args.limit} functions by cumulative time:")
        print(f"{'Function':<60} {'Calls':>10} {'Total':>12} {'Cumul':>12} {'Per Call':>12}")
        print("-" * 110)
        for func in analysis["top_functions"]:
            print(
                f"{func['function']:<60} {func['calls']:>10} "
                f"{func['total_time']:>12.6f} {func['cumulative_time']:>12.6f} "
                f"{func['per_call_time']:>12.9f}"
            )

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
