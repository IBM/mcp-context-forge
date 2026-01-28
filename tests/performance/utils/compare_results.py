#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Performance Results Comparison Utility

Compares performance test results across different configurations.
Supports baseline comparison, regression detection, and cost-benefit analysis.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Any


class ResultsComparator:
    """Compare performance test results"""

    def __init__(self, baseline_file: Path, current_file: Path):
        self.baseline = self._load_results(baseline_file)
        self.current = self._load_results(current_file)

    def _load_results(self, file_path: Path) -> Dict:
        """Load results from JSON file"""
        with open(file_path) as f:
            return json.load(f)

    def compare(self) -> Dict[str, Any]:
        """
        Compare current results against baseline

        Returns:
            Dictionary containing comparison results
        """
        comparison = {
            "baseline_info": self.baseline.get("metadata", {}),
            "current_info": self.current.get("metadata", {}),
            "test_comparisons": [],
            "summary": {},
            "regressions": [],
            "improvements": [],
            "verdict": None,
        }

        # Compare each test
        baseline_tests = self.baseline.get("results", {})
        current_tests = self.current.get("results", {})

        for test_name in set(list(baseline_tests.keys()) + list(current_tests.keys())):
            baseline_metrics = baseline_tests.get(test_name, {})
            current_metrics = current_tests.get(test_name, {})

            if not baseline_metrics or not current_metrics:
                continue

            test_comparison = self._compare_test(test_name, baseline_metrics, current_metrics)
            comparison["test_comparisons"].append(test_comparison)

            # Track regressions and improvements
            if test_comparison["has_regression"]:
                comparison["regressions"].append({"test": test_name, "metrics": test_comparison["regressed_metrics"]})

            if test_comparison["has_improvement"]:
                comparison["improvements"].append({"test": test_name, "metrics": test_comparison["improved_metrics"]})

        # Calculate summary statistics
        comparison["summary"] = self._calculate_summary(comparison["test_comparisons"])

        # Determine overall verdict
        comparison["verdict"] = self._determine_verdict(comparison)

        return comparison

    def _compare_test(self, test_name: str, baseline: Dict, current: Dict) -> Dict[str, Any]:
        """Compare metrics for a single test"""
        comparison = {"test_name": test_name, "metrics": {}, "has_regression": False, "has_improvement": False, "regressed_metrics": [], "improved_metrics": []}

        # Metrics to compare
        metric_comparisons = {
            "rps": {"higher_is_better": True, "threshold_pct": 10},
            "p50": {"higher_is_better": False, "threshold_pct": 15},
            "p95": {"higher_is_better": False, "threshold_pct": 15},
            "p99": {"higher_is_better": False, "threshold_pct": 15},
            "error_rate": {"higher_is_better": False, "threshold_pct": 5},
        }

        for metric, config in metric_comparisons.items():
            if metric not in baseline or metric not in current:
                continue

            baseline_val = baseline[metric]
            current_val = current[metric]

            if baseline_val == 0:
                continue

            change_pct = ((current_val - baseline_val) / baseline_val) * 100

            metric_info = {
                "baseline": baseline_val,
                "current": current_val,
                "change": current_val - baseline_val,
                "change_pct": change_pct,
                "threshold_pct": config["threshold_pct"],
                "status": "unchanged",
            }

            # Determine if regression or improvement
            if config["higher_is_better"]:
                if change_pct < -config["threshold_pct"]:
                    metric_info["status"] = "regression"
                    comparison["has_regression"] = True
                    comparison["regressed_metrics"].append(metric)
                elif change_pct > config["threshold_pct"]:
                    metric_info["status"] = "improvement"
                    comparison["has_improvement"] = True
                    comparison["improved_metrics"].append(metric)
            else:
                if change_pct > config["threshold_pct"]:
                    metric_info["status"] = "regression"
                    comparison["has_regression"] = True
                    comparison["regressed_metrics"].append(metric)
                elif change_pct < -config["threshold_pct"]:
                    metric_info["status"] = "improvement"
                    comparison["has_improvement"] = True
                    comparison["improved_metrics"].append(metric)

            comparison["metrics"][metric] = metric_info

        return comparison

    def _calculate_summary(self, test_comparisons: List[Dict]) -> Dict:
        """Calculate summary statistics across all tests"""
        summary = {
            "total_tests": len(test_comparisons),
            "tests_with_regressions": 0,
            "tests_with_improvements": 0,
            "avg_throughput_change_pct": 0,
            "avg_latency_change_pct": 0,
            "total_regressions": 0,
            "total_improvements": 0,
        }

        throughput_changes = []
        latency_changes = []

        for test in test_comparisons:
            if test["has_regression"]:
                summary["tests_with_regressions"] += 1
                summary["total_regressions"] += len(test["regressed_metrics"])

            if test["has_improvement"]:
                summary["tests_with_improvements"] += 1
                summary["total_improvements"] += len(test["improved_metrics"])

            # Collect throughput changes
            if "rps" in test["metrics"]:
                throughput_changes.append(test["metrics"]["rps"]["change_pct"])

            # Collect latency changes (average of p50, p95, p99)
            latency_metrics = ["p50", "p95", "p99"]
            test_latency_changes = [test["metrics"][m]["change_pct"] for m in latency_metrics if m in test["metrics"]]
            if test_latency_changes:
                latency_changes.append(sum(test_latency_changes) / len(test_latency_changes))

        # Calculate averages
        if throughput_changes:
            summary["avg_throughput_change_pct"] = sum(throughput_changes) / len(throughput_changes)

        if latency_changes:
            summary["avg_latency_change_pct"] = sum(latency_changes) / len(latency_changes)

        return summary

    def _determine_verdict(self, comparison: Dict) -> str:
        """Determine overall verdict (recommended, caution, not_recommended)"""
        summary = comparison["summary"]
        regressions = len(comparison["regressions"])

        # Critical regressions
        if regressions > 0:
            if summary["avg_throughput_change_pct"] < -20:
                return "not_recommended"
            if summary["avg_latency_change_pct"] > 25:
                return "not_recommended"
            if regressions >= 3:
                return "caution"

        # Significant improvements
        if summary["avg_throughput_change_pct"] > 15 and summary["avg_latency_change_pct"] < -10:
            return "recommended"

        # Mixed results
        if regressions > 0:
            return "caution"

        return "acceptable"

    def print_comparison(self, comparison: Dict, detailed: bool = True):
        """Print comparison results to console"""
        print("\n" + "=" * 80)
        print("PERFORMANCE COMPARISON REPORT")
        print("=" * 80)

        # Header
        print(f"\nBaseline: {comparison['baseline_info'].get('timestamp', 'Unknown')}")
        print(f"  Profile: {comparison['baseline_info'].get('profile', 'Unknown')}")
        print(f"  Config: {comparison['baseline_info'].get('config', {})}")

        print(f"\nCurrent: {comparison['current_info'].get('timestamp', 'Unknown')}")
        print(f"  Profile: {comparison['current_info'].get('profile', 'Unknown')}")
        print(f"  Config: {comparison['current_info'].get('config', {})}")

        # Summary
        print("\n" + "-" * 80)
        print("SUMMARY")
        print("-" * 80)
        summary = comparison["summary"]
        print(f"Total Tests: {summary['total_tests']}")
        print(f"Tests with Regressions: {summary['tests_with_regressions']}")
        print(f"Tests with Improvements: {summary['tests_with_improvements']}")
        print(f"\nAverage Throughput Change: {summary['avg_throughput_change_pct']:+.1f}%")
        print(f"Average Latency Change: {summary['avg_latency_change_pct']:+.1f}%")

        # Regressions
        if comparison["regressions"]:
            print("\n" + "-" * 80)
            print("⚠️  REGRESSIONS DETECTED")
            print("-" * 80)
            for regression in comparison["regressions"]:
                print(f"\n{regression['test']}:")
                for metric in regression["metrics"]:
                    print(f"  - {metric}")

        # Improvements
        if comparison["improvements"]:
            print("\n" + "-" * 80)
            print("✅ IMPROVEMENTS")
            print("-" * 80)
            for improvement in comparison["improvements"]:
                print(f"\n{improvement['test']}:")
                for metric in improvement["metrics"]:
                    print(f"  - {metric}")

        # Detailed comparison
        if detailed:
            print("\n" + "-" * 80)
            print("DETAILED METRICS")
            print("-" * 80)

            for test in comparison["test_comparisons"]:
                print(f"\n{test['test_name']}:")
                print(f"  {'Metric':<15} {'Baseline':>12} {'Current':>12} {'Change':>12} {'Status':<15}")
                print(f"  {'-' * 15} {'-' * 12} {'-' * 12} {'-' * 12} {'-' * 15}")

                for metric_name, metric_data in test["metrics"].items():
                    baseline_str = f"{metric_data['baseline']:.1f}"
                    current_str = f"{metric_data['current']:.1f}"
                    change_str = f"{metric_data['change_pct']:+.1f}%"

                    status_symbol = {"regression": "❌", "improvement": "✅", "unchanged": "➖"}.get(metric_data["status"], "?")

                    status_str = f"{status_symbol} {metric_data['status']}"

                    print(f"  {metric_name:<15} {baseline_str:>12} {current_str:>12} {change_str:>12} {status_str:<15}")

        # Verdict
        print("\n" + "=" * 80)
        print("VERDICT")
        print("=" * 80)

        verdict_messages = {
            "recommended": "✅ RECOMMENDED - Significant performance improvements detected",
            "acceptable": "✓ ACCEPTABLE - No major regressions, acceptable performance",
            "caution": "⚠️ CAUTION - Some regressions detected, review carefully",
            "not_recommended": "❌ NOT RECOMMENDED - Critical regressions detected",
        }

        print(f"\n{verdict_messages.get(comparison['verdict'], 'UNKNOWN')}\n")

    def save_comparison(self, comparison: Dict, output_file: Path):
        """Save comparison results to JSON file"""
        with open(output_file, "w") as f:
            json.dump(comparison, f, indent=2)
        print(f"✅ Comparison saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Compare performance test results")
    parser.add_argument("baseline", type=Path, help="Baseline results JSON file")
    parser.add_argument("current", type=Path, help="Current results JSON file")
    parser.add_argument("--output", type=Path, help="Output file for comparison results (JSON)")
    parser.add_argument("--brief", action="store_true", help="Show brief summary only")
    parser.add_argument("--fail-on-regression", action="store_true", help="Exit with error code if regressions detected")

    args = parser.parse_args()

    try:
        comparator = ResultsComparator(args.baseline, args.current)
        comparison = comparator.compare()

        # Print comparison
        comparator.print_comparison(comparison, detailed=not args.brief)

        # Save if requested
        if args.output:
            comparator.save_comparison(comparison, args.output)

        # Check for regressions
        if args.fail_on_regression and comparison["regressions"]:
            print("\n❌ Exiting with error due to detected regressions")
            return 1

        return 0

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
