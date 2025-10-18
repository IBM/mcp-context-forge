#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Baseline Manager

Utilities for saving and loading performance test baselines.
Converts test results to standardized JSON format for comparison.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime


class BaselineManager:
    """Manage performance test baselines"""

    @staticmethod
    def parse_hey_results(results_dir: Path) -> Dict[str, Dict]:
        """
        Parse all hey output files in results directory

        Args:
            results_dir: Directory containing hey output .txt files

        Returns:
            Dictionary mapping test names to their metrics
        """
        results = {}

        for txt_file in results_dir.glob("*.txt"):
            # Skip non-hey output files
            if "system_metrics" in txt_file.name or "docker_stats" in txt_file.name:
                continue
            if "prometheus" in txt_file.name or "logs" in txt_file.name:
                continue

            # Extract test name from filename
            # Format: {category}_{test_name}_{profile}_{timestamp}.txt
            parts = txt_file.stem.split("_")
            if len(parts) >= 2:
                test_name = "_".join(parts[:-2])  # Remove profile and timestamp
            else:
                test_name = txt_file.stem

            # Parse hey output
            metrics = BaselineManager._parse_hey_output(txt_file)
            if metrics:
                results[test_name] = metrics

        return results

    @staticmethod
    def _parse_hey_output(file_path: Path) -> Optional[Dict]:
        """Parse hey output file to extract metrics"""
        try:
            with open(file_path) as f:
                content = f.read()

            metrics = {}

            # Extract summary metrics
            if match := re.search(r"Requests/sec:\s+([\d.]+)", content):
                metrics["rps"] = float(match.group(1))

            if match := re.search(r"Average:\s+([\d.]+)\s+secs", content):
                metrics["avg"] = float(match.group(1)) * 1000  # Convert to ms

            if match := re.search(r"Slowest:\s+([\d.]+)\s+secs", content):
                metrics["max"] = float(match.group(1)) * 1000

            if match := re.search(r"Fastest:\s+([\d.]+)\s+secs", content):
                metrics["min"] = float(match.group(1)) * 1000

            # Extract percentiles
            latency_section = re.search(r"Latency distribution:(.*?)(?=\n\n|\Z)", content, re.DOTALL)
            if latency_section:
                latency_text = latency_section.group(1)

                if match := re.search(r"10%\s+in\s+([\d.]+)\s+secs", latency_text):
                    metrics["p10"] = float(match.group(1)) * 1000

                if match := re.search(r"25%\s+in\s+([\d.]+)\s+secs", latency_text):
                    metrics["p25"] = float(match.group(1)) * 1000

                if match := re.search(r"50%\s+in\s+([\d.]+)\s+secs", latency_text):
                    metrics["p50"] = float(match.group(1)) * 1000

                if match := re.search(r"75%\s+in\s+([\d.]+)\s+secs", latency_text):
                    metrics["p75"] = float(match.group(1)) * 1000

                if match := re.search(r"90%\s+in\s+([\d.]+)\s+secs", latency_text):
                    metrics["p90"] = float(match.group(1)) * 1000

                if match := re.search(r"95%\s+in\s+([\d.]+)\s+secs", latency_text):
                    metrics["p95"] = float(match.group(1)) * 1000

                if match := re.search(r"99%\s+in\s+([\d.]+)\s+secs", latency_text):
                    metrics["p99"] = float(match.group(1)) * 1000

            # Extract status codes
            status_codes = {}
            status_section = re.search(r"Status code distribution:(.*?)(?=\n\n|\Z)", content, re.DOTALL)
            if status_section:
                for line in status_section.group(1).strip().split("\n"):
                    if match := re.search(r"\[(\d+)\]\s+(\d+)\s+responses", line):
                        status_codes[int(match.group(1))] = int(match.group(2))

            metrics["status_codes"] = status_codes

            # Calculate error rate
            total_responses = sum(status_codes.values())
            error_responses = sum(count for code, count in status_codes.items() if code >= 400)
            metrics["error_rate"] = (error_responses / total_responses * 100) if total_responses > 0 else 0
            metrics["total_requests"] = total_responses

            return metrics

        except Exception as e:
            print(f"Warning: Failed to parse {file_path}: {e}", file=sys.stderr)
            return None

    @staticmethod
    def save_baseline(results_dir: Path, output_file: Path, metadata: Optional[Dict] = None) -> Dict:
        """
        Save test results as baseline

        Args:
            results_dir: Directory containing test result files
            output_file: Path to save baseline JSON
            metadata: Optional metadata to include

        Returns:
            Baseline data dictionary
        """
        # Parse results
        results = BaselineManager.parse_hey_results(results_dir)

        # Create baseline structure
        baseline = {
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "metadata": metadata or {},
            "results": results,
            "summary": {
                "total_tests": len(results),
                "avg_rps": sum(r.get("rps", 0) for r in results.values()) / len(results) if results else 0,
                "avg_p95": sum(r.get("p95", 0) for r in results.values()) / len(results) if results else 0,
            },
        }

        # Save to file
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w") as f:
            json.dump(baseline, f, indent=2)

        print(f"✅ Baseline saved: {output_file}")
        print(f"   Tests: {baseline['summary']['total_tests']}")
        print(f"   Average RPS: {baseline['summary']['avg_rps']:.1f}")
        print(f"   Average p95: {baseline['summary']['avg_p95']:.1f}ms")

        return baseline

    @staticmethod
    def load_baseline(file_path: Path) -> Dict:
        """Load baseline from JSON file"""
        with open(file_path) as f:
            baseline = json.load(f)

        print(f"✅ Loaded baseline: {file_path}")
        print(f"   Created: {baseline.get('created', 'Unknown')}")
        print(f"   Tests: {baseline.get('summary', {}).get('total_tests', 0)}")

        return baseline

    @staticmethod
    def list_baselines(baselines_dir: Path):
        """List all available baselines"""
        print(f"\nAvailable baselines in {baselines_dir}:")
        print("-" * 80)

        baselines = sorted(baselines_dir.glob("*.json"))
        if not baselines:
            print("No baselines found")
            return

        for baseline_file in baselines:
            try:
                with open(baseline_file) as f:
                    data = json.load(f)

                created = data.get("created", "Unknown")
                metadata = data.get("metadata", {})
                profile = metadata.get("profile", "Unknown")
                tests = data.get("summary", {}).get("total_tests", 0)

                print(f"\n{baseline_file.name}")
                print(f"  Created: {created}")
                print(f"  Profile: {profile}")
                print(f"  Tests: {tests}")

                # Show configuration if available
                config = metadata.get("config", {})
                if config:
                    print("  Config:")
                    for key, value in config.items():
                        print(f"    {key}: {value}")

            except Exception as e:
                print(f"\n{baseline_file.name} - Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Manage performance test baselines")

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Save baseline
    save_parser = subparsers.add_parser("save", help="Save results as baseline")
    save_parser.add_argument("results_dir", type=Path, help="Directory containing test results")
    save_parser.add_argument("--output", type=Path, required=True, help="Output baseline file")
    save_parser.add_argument("--profile", help="Test profile name")
    save_parser.add_argument("--server-profile", help="Server profile name")
    save_parser.add_argument("--infrastructure", help="Infrastructure profile name")
    save_parser.add_argument("--metadata", type=json.loads, help="Additional metadata as JSON string")

    # Load baseline
    load_parser = subparsers.add_parser("load", help="Load and display baseline")
    load_parser.add_argument("baseline_file", type=Path, help="Baseline JSON file")

    # List baselines
    list_parser = subparsers.add_parser("list", help="List available baselines")
    list_parser.add_argument("--dir", type=Path, default=Path("baselines"), help="Baselines directory")

    args = parser.parse_args()

    try:
        if args.command == "save":
            # Build metadata
            metadata = args.metadata or {}
            if args.profile:
                metadata["profile"] = args.profile
            if args.server_profile:
                metadata["server_profile"] = args.server_profile
            if args.infrastructure:
                metadata["infrastructure"] = args.infrastructure
            metadata["timestamp"] = datetime.now().isoformat()

            BaselineManager.save_baseline(args.results_dir, args.output, metadata)

        elif args.command == "load":
            baseline = BaselineManager.load_baseline(args.baseline_file)

            # Print summary
            print("\nResults:")
            for test_name, metrics in baseline.get("results", {}).items():
                rps = metrics.get("rps", 0)
                p95 = metrics.get("p95", 0)
                print(f"  {test_name:40} {rps:8.1f} rps  {p95:6.1f}ms p95")

        elif args.command == "list":
            BaselineManager.list_baselines(args.dir)

        else:
            parser.print_help()
            return 1

        return 0

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
