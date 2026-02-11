# -*- coding: utf-8 -*-
"""Compare two Locust CSV stats exports and print latency/throughput deltas.

Usage:
    python tests/loadtest/compare_locust_runs.py \
        --baseline reports/locust_python_stats.csv \
        --candidate reports/locust_rust_stats.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def _load_aggregate_row(path: Path) -> dict[str, float]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("Name") == "Aggregated":
                return {
                    "requests": float(row.get("Request Count") or 0),
                    "failures": float(row.get("Failure Count") or 0),
                    "rps": float(row.get("Requests/s") or 0),
                    "p50": float(row.get("50%") or 0),
                    "p95": float(row.get("95%") or 0),
                    "p99": float(row.get("99%") or 0),
                }
    raise ValueError(f"No 'Aggregated' row found in {path}")


def _delta(candidate: float, baseline: float) -> float:
    if baseline == 0:
        return 0.0
    return ((candidate - baseline) / baseline) * 100.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path, help="Baseline Locust *_stats.csv")
    parser.add_argument("--candidate", required=True, type=Path, help="Candidate Locust *_stats.csv")
    args = parser.parse_args()

    baseline = _load_aggregate_row(args.baseline)
    candidate = _load_aggregate_row(args.candidate)

    print("# Locust Comparison (Aggregated)")
    print("")
    print("| Metric | Baseline | Candidate | Delta |")
    print("|---|---:|---:|---:|")
    for metric in ("rps", "p50", "p95", "p99", "requests", "failures"):
        b = baseline[metric]
        c = candidate[metric]
        d = _delta(c, b)
        print(f"| {metric} | {b:.2f} | {c:.2f} | {d:+.2f}% |")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())