# -*- coding: utf-8 -*-
"""Analyze database query logs for N+1 patterns and performance issues.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

Usage:
    python -m mcpgateway.utils.analyze_query_log [--json logs/db-queries.jsonl]
    make query-log-analyze
"""

# Standard
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import sys
from typing import Any, Dict, List

# Third-Party
import orjson


def load_json_log(filepath: Path) -> List[Dict[str, Any]]:
    """Load JSON Lines log file.

    Args:
        filepath: Path to the JSONL file

    Returns:
        List of log entries
    """
    entries = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(orjson.loads(line))
                except orjson.JSONDecodeError:
                    continue
    return entries


def analyze_logs(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze log entries for patterns and issues.

    Args:
        entries: List of log entries

    Returns:
        Analysis results
    """
    total_requests = len(entries)
    total_queries = sum(e.get("query_count", 0) for e in entries)

    # Find requests with N+1 issues
    n1_requests = [e for e in entries if e.get("n1_issues")]

    # Group by endpoint
    endpoint_stats: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "total_queries": 0,
            "total_query_ms": 0,
            "n1_count": 0,
            "max_queries": 0,
        }
    )

    for e in entries:
        key = f"{e.get('method', '?')} {e.get('path', '?')}"
        stats = endpoint_stats[key]
        stats["count"] += 1
        stats["total_queries"] += e.get("query_count", 0)
        stats["total_query_ms"] += e.get("total_query_ms", 0)
        if e.get("n1_issues"):
            stats["n1_count"] += 1
        stats["max_queries"] = max(stats["max_queries"], e.get("query_count", 0))

    # Calculate averages
    for stats in endpoint_stats.values():
        if stats["count"] > 0:
            stats["avg_queries"] = round(stats["total_queries"] / stats["count"], 1)
            stats["avg_query_ms"] = round(stats["total_query_ms"] / stats["count"], 1)

    # Sort by total queries (most queries first)
    sorted_endpoints = sorted(endpoint_stats.items(), key=lambda x: x[1]["total_queries"], reverse=True)

    # Find most common N+1 patterns
    n1_patterns: Counter = Counter()
    for e in entries:
        for issue in e.get("n1_issues") or []:
            pattern = issue.get("pattern", "")[:100]
            table = issue.get("table", "unknown")
            n1_patterns[f"{table}: {pattern}"] += issue.get("count", 1)

    return {
        "total_requests": total_requests,
        "total_queries": total_queries,
        "avg_queries_per_request": round(total_queries / total_requests, 1) if total_requests else 0,
        "requests_with_n1": len(n1_requests),
        "n1_percentage": round(len(n1_requests) / total_requests * 100, 1) if total_requests else 0,
        "endpoint_stats": sorted_endpoints,
        "top_n1_patterns": n1_patterns.most_common(10),
    }


def print_report(analysis: Dict[str, Any]) -> None:
    """Print analysis report to stdout.

    Args:
        analysis: Analysis results from analyze_logs()
    """
    print("\n" + "=" * 80)
    print("DATABASE QUERY LOG ANALYSIS")
    print("=" * 80)

    print("\n📊 SUMMARY")
    print(f"   Total requests analyzed: {analysis['total_requests']}")
    print(f"   Total queries executed:  {analysis['total_queries']}")
    print(f"   Avg queries per request: {analysis['avg_queries_per_request']}")
    print(f"   Requests with N+1:       {analysis['requests_with_n1']} ({analysis['n1_percentage']}%)")

    if analysis["requests_with_n1"] > 0:
        print("\n⚠️  N+1 ISSUES DETECTED")
        print(f"   {analysis['requests_with_n1']} requests have potential N+1 query patterns")

    if analysis["top_n1_patterns"]:
        print("\n🔴 TOP N+1 PATTERNS")
        for pattern, count in analysis["top_n1_patterns"]:
            print(f"   {count:4}x  {pattern[:70]}...")

    print("\n📈 ENDPOINTS BY QUERY COUNT (top 15)")
    print(f"   {'Endpoint':<40} {'Reqs':>6} {'Queries':>8} {'Avg':>6} {'Max':>5} {'N+1':>4}")
    print("   " + "-" * 75)

    for endpoint, stats in analysis["endpoint_stats"][:15]:
        n1_marker = "⚠️" if stats["n1_count"] > 0 else "  "
        print(f"   {endpoint:<40} {stats['count']:>6} {stats['total_queries']:>8} " f"{stats['avg_queries']:>6} {stats['max_queries']:>5} {n1_marker}{stats['n1_count']:>2}")

    # Recommendations
    print("\n💡 RECOMMENDATIONS")

    high_query_endpoints = [(ep, s) for ep, s in analysis["endpoint_stats"] if s["avg_queries"] > 10]
    if high_query_endpoints:
        print(f"   • {len(high_query_endpoints)} endpoints average >10 queries - consider eager loading")
        for ep, stats in high_query_endpoints[:3]:
            print(f"     - {ep} (avg: {stats['avg_queries']} queries)")

    if analysis["requests_with_n1"] > 0:
        print("   • Review N+1 patterns above and add joinedload/selectinload")
        print("   • See: docs/docs/development/db-performance.md")

    print("\n" + "=" * 80 + "\n")


def main() -> int:
    """Main entry point for the analysis script.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    parser = argparse.ArgumentParser(description="Analyze database query logs for N+1 patterns")
    parser.add_argument("--json", default="logs/db-queries.jsonl", help="Path to JSON Lines log file (default: logs/db-queries.jsonl)")
    args = parser.parse_args()

    log_path = Path(args.json)

    if not log_path.exists():
        print(f"❌ Log file not found: {log_path}")
        print("   Start the server with 'make dev-query-log' to generate logs")
        return 1

    if log_path.stat().st_size == 0:
        print(f"❌ Log file is empty: {log_path}")
        print("   Make some API requests to generate query logs")
        return 1

    print(f"📊 Loading {log_path}...")
    entries = load_json_log(log_path)

    if not entries:
        print(f"❌ No valid entries found in {log_path}")
        return 1

    print(f"   Loaded {len(entries)} request entries")

    analysis = analyze_logs(entries)
    print_report(analysis)

    # Return non-zero if N+1 issues found (useful for CI)
    return 1 if analysis["requests_with_n1"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
