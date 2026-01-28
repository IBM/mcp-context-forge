# -*- coding: utf-8 -*-
"""Location: ./tests/async/profile_compare.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Compare async performance profiles between builds.
"""

# Standard
import argparse
import json
from pathlib import Path
import pstats
from typing import Any, Dict


class ProfileComparator:
    """Compare performance profiles and detect regressions."""

    def compare_profiles(self, baseline_path: Path, current_path: Path) -> Dict[str, Any]:
        """Compare two performance profiles."""

        baseline_stats = pstats.Stats(str(baseline_path))
        current_stats = pstats.Stats(str(current_path))

        comparison: Dict[str, Any] = {"baseline_file": str(baseline_path), "current_file": str(current_path), "regressions": [], "improvements": [], "summary": {}}

        # Compare overall performance
        baseline_total_time = baseline_stats.total_tt
        current_total_time = current_stats.total_tt

        total_time_change = (current_total_time - baseline_total_time) / baseline_total_time * 100

        comparison["summary"]["total_time_change"] = total_time_change

        # Compare function-level performance
        baseline_functions = self._extract_function_stats(baseline_stats)
        current_functions = self._extract_function_stats(current_stats)

        for func_name, baseline_time in baseline_functions.items():
            if func_name in current_functions:
                current_time: float = current_functions[func_name]
                change_percent = (current_time - baseline_time) / baseline_time * 100

                if change_percent > 20:  # 20% regression threshold
                    comparison["regressions"].append({"function": func_name, "baseline_time": baseline_time, "current_time": current_time, "change_percent": change_percent})
                elif change_percent < -10:  # 10% improvement
                    comparison["improvements"].append({"function": func_name, "baseline_time": baseline_time, "current_time": current_time, "change_percent": change_percent})

        return comparison

    def _extract_function_stats(self, stats: pstats.Stats) -> Dict[str, float]:
        """Extract function-level statistics from pstats.Stats."""

        functions = {}

        for func, stat in stats.stats.items():
            func_name = f"{func[0]}:{func[1]}:{func[2]}"
            tottime = stat[2]  # Extract the 'tottime' (total time spent in the given function)
            functions[func_name] = tottime

        return functions


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare performance profiles.")
    parser.add_argument("--baseline", type=Path, required=True, help="Path to the baseline profile.")
    parser.add_argument("--current", type=Path, required=True, help="Path to the current profile.")
    parser.add_argument("--output", type=Path, required=True, help="Path to the output comparison report.")

    args = parser.parse_args()

    comparator = ProfileComparator()
    comparison = comparator.compare_profiles(args.baseline, args.current)

    with open(args.output, "w") as f:
        json.dump(comparison, f, indent=4)

    print(f"Comparison report saved to {args.output}")
