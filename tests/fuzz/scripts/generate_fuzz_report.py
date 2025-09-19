#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/fuzz/scripts/generate_fuzz_report.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Generate comprehensive fuzzing report for MCP Gateway.
"""
# Standard
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional


def collect_hypothesis_stats() -> Dict[str, Any]:
    """Collect Hypothesis test statistics."""
    stats = {
        "tool": "hypothesis",
        "status": "unknown",
        "tests_run": 0,
        "examples_generated": 0,
        "failures": 0,
        "errors": []
    }

    # Look for pytest output or hypothesis database
    hypothesis_db = Path(".hypothesis")
    if hypothesis_db.exists():
        stats["status"] = "completed"
        stats["database_exists"] = True

        # Count database entries
        db_files = list(hypothesis_db.rglob("*.json"))
        stats["database_entries"] = len(db_files)

    return stats


def collect_atheris_results() -> Dict[str, Any]:
    """Collect Atheris fuzzing results."""
    results = {
        "tool": "atheris",
        "status": "unknown",
        "fuzzers_run": 0,
        "total_executions": 0,
        "crashes_found": 0,
        "artifacts": []
    }

    # Use relative path from script location to project root
    project_root = Path(__file__).parent.parent.parent.parent
    artifacts_dir = project_root / "tests/fuzz/fuzzers/results"

    if artifacts_dir.exists():
        results["status"] = "completed"

        # Count artifacts (crashes, hangs, etc.)
        artifact_files = list(artifacts_dir.glob("*"))
        results["artifacts"] = [str(f.name) for f in artifact_files]
        results["crashes_found"] = len([f for f in artifact_files if "crash" in f.name.lower()])

        # Count fuzzer types
        fuzzer_files = list((project_root / "tests/fuzz/fuzzers").glob("fuzz_*.py"))
        results["fuzzers_run"] = len(fuzzer_files)
        results["fuzzer_list"] = [f.stem for f in fuzzer_files]

    return results


def collect_schemathesis_results() -> Dict[str, Any]:
    """Collect Schemathesis API fuzzing results."""
    results = {
        "tool": "schemathesis",
        "status": "unknown",
        "endpoints_tested": 0,
        "total_requests": 0,
        "failures": 0,
        "checks_passed": 0
    }

    # Use relative path from script location to project root
    project_root = Path(__file__).parent.parent.parent.parent
    report_file = project_root / "reports/schemathesis-report.json"

    if report_file.exists():
        try:
            with open(report_file) as f:
                data = json.load(f)
                results["status"] = "completed"
                results["raw_report"] = data

                # Extract key metrics
                if "results" in data:
                    results["endpoints_tested"] = len(data["results"])

                # Count total requests and failures
                total_requests = 0
                failures = 0
                for result in data.get("results", []):
                    if "checks" in result:
                        for check in result["checks"]:
                            total_requests += check.get("count", 0)
                            if not check.get("success", True):
                                failures += 1

                results["total_requests"] = total_requests
                results["failures"] = failures
                results["checks_passed"] = total_requests - failures

        except (json.JSONDecodeError, KeyError) as e:
            results["status"] = "error"
            results["error"] = str(e)

    return results


def collect_security_test_results() -> Dict[str, Any]:
    """Collect security fuzzing test results."""
    results = {
        "tool": "security_tests",
        "status": "unknown",
        "test_categories": [
            "sql_injection",
            "xss_prevention",
            "path_traversal",
            "command_injection",
            "header_injection",
            "authentication_bypass"
        ],
        "tests_run": 0,
        "vulnerabilities_found": 0
    }

    # This would be populated by pytest results
    # For now, return basic structure
    results["status"] = "available"

    return results


def collect_corpus_stats() -> Dict[str, Any]:
    """Collect corpus statistics."""
    stats = {
        "total_files": 0,
        "categories": {}
    }

    # Use relative path from script location to project root
    project_root = Path(__file__).parent.parent.parent.parent
    corpus_dir = project_root / "corpus"

    if corpus_dir.exists():
        for category_dir in corpus_dir.iterdir():
            if category_dir.is_dir():
                files = list(category_dir.glob("*"))
                stats["categories"][category_dir.name] = len(files)
                stats["total_files"] += len(files)

    return stats


def collect_coverage_info() -> Dict[str, Any]:
    """Collect code coverage information."""
    coverage_info = {
        "available": False,
        "percentage": 0,
        "lines_covered": 0,
        "lines_total": 0
    }

    # Look for coverage files
    coverage_files = [
        ".coverage",
        "coverage.xml",
        "htmlcov/index.html"
    ]

    for coverage_file in coverage_files:
        if Path(coverage_file).exists():
            coverage_info["available"] = True
            break

    return coverage_info


def generate_summary(report_data: Dict[str, Any]) -> Dict[str, Any]:
    """Generate executive summary of fuzzing results."""
    summary = {
        "total_tools": 0,
        "tools_completed": 0,
        "critical_issues": 0,
        "recommendations": [],
        "overall_status": "unknown"
    }

    tools = ["hypothesis", "atheris", "schemathesis", "security_tests"]
    summary["total_tools"] = len(tools)

    completed_tools = 0
    critical_issues = 0

    for tool in tools:
        if tool in report_data and report_data[tool].get("status") == "completed":
            completed_tools += 1

        # Check for critical issues
        if tool == "atheris" and report_data.get(tool, {}).get("crashes_found", 0) > 0:
            critical_issues += 1
            summary["recommendations"].append(f"🚨 Atheris found {report_data[tool]['crashes_found']} crashes - investigate immediately")

        if tool == "schemathesis" and report_data.get(tool, {}).get("failures", 0) > 0:
            critical_issues += 1
            summary["recommendations"].append(f"⚠️ API fuzzing found {report_data[tool]['failures']} failures")

    summary["tools_completed"] = completed_tools
    summary["critical_issues"] = critical_issues

    # Determine overall status
    if completed_tools == len(tools) and critical_issues == 0:
        summary["overall_status"] = "✅ PASS"
    elif critical_issues > 0:
        summary["overall_status"] = "❌ CRITICAL ISSUES FOUND"
    elif completed_tools > 0:
        summary["overall_status"] = "⚠️ PARTIAL"
    else:
        summary["overall_status"] = "❓ NO RESULTS"

    # Add general recommendations
    if not summary["recommendations"]:
        summary["recommendations"].append("✅ No critical issues found in fuzzing")
        summary["recommendations"].append("🔄 Continue regular fuzzing as part of CI/CD")

    summary["recommendations"].append("📊 Review detailed results below for optimization opportunities")

    return summary


def generate_markdown_report(report_data: Dict[str, Any]) -> str:
    """Generate markdown version of the report."""
    timestamp = report_data["metadata"]["timestamp"]
    summary = report_data["summary"]

    md = f"""# 🎯 MCP Gateway Fuzz Testing Report

**Generated:** {timestamp}
**Overall Status:** {summary["overall_status"]}

## 📋 Executive Summary

- **Tools Run:** {summary["tools_completed"]}/{summary["total_tools"]}
- **Critical Issues:** {summary["critical_issues"]}

### 🎯 Recommendations

"""

    for rec in summary["recommendations"]:
        md += f"- {rec}\n"

    md += "\n## 🧪 Tool Results\n\n"

    # Hypothesis results
    if "hypothesis" in report_data:
        hyp = report_data["hypothesis"]
        md += f"""### Hypothesis Property-Based Testing
- **Status:** {hyp["status"]}
- **Tests Run:** {hyp["tests_run"]}
- **Examples Generated:** {hyp["examples_generated"]}
- **Database Entries:** {hyp.get("database_entries", "N/A")}

"""

    # Atheris results
    if "atheris" in report_data:
        ath = report_data["atheris"]
        md += f"""### Atheris Coverage-Guided Fuzzing
- **Status:** {ath["status"]}
- **Fuzzers Run:** {ath["fuzzers_run"]}
- **Crashes Found:** {ath["crashes_found"]} {'🚨' if ath["crashes_found"] > 0 else '✅'}
- **Artifacts:** {len(ath["artifacts"])}

"""
        if ath["artifacts"]:
            md += "**Artifacts Found:**\n"
            for artifact in ath["artifacts"]:
                md += f"- `{artifact}`\n"
            md += "\n"

    # Schemathesis results
    if "schemathesis" in report_data:
        sch = report_data["schemathesis"]
        md += f"""### Schemathesis API Fuzzing
- **Status:** {sch["status"]}
- **Endpoints Tested:** {sch["endpoints_tested"]}
- **Total Requests:** {sch["total_requests"]}
- **Failures:** {sch["failures"]} {'⚠️' if sch["failures"] > 0 else '✅'}
- **Checks Passed:** {sch["checks_passed"]}

"""

    # Security tests
    if "security_tests" in report_data:
        sec = report_data["security_tests"]
        md += f"""### Security Fuzzing Tests
- **Status:** {sec["status"]}
- **Test Categories:** {len(sec["test_categories"])}
- **Tests Available:** {", ".join(sec["test_categories"])}

"""

    # Corpus stats
    if "corpus" in report_data:
        corpus = report_data["corpus"]
        md += f"""## 📚 Test Corpus
- **Total Files:** {corpus["total_files"]}
- **Categories:** {len(corpus["categories"])}

"""
        for category, count in corpus["categories"].items():
            md += f"- **{category}:** {count} files\n"

    md += f"\n---\n*Report generated by MCP Gateway Fuzz Testing Suite*"

    return md


def main():
    """Generate comprehensive fuzzing report."""
    print("📊 Generating fuzzing report...")

    # Collect data from all fuzzing tools
    report_data = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "version": "1.0",
            "generator": "MCP Gateway Fuzz Report"
        },
        "hypothesis": collect_hypothesis_stats(),
        "atheris": collect_atheris_results(),
        "schemathesis": collect_schemathesis_results(),
        "security_tests": collect_security_test_results(),
        "corpus": collect_corpus_stats(),
        "coverage": collect_coverage_info()
    }

    # Generate summary
    report_data["summary"] = generate_summary(report_data)

    # Ensure reports directory exists (relative to project root)
    project_root = Path(__file__).parent.parent.parent.parent
    reports_dir = project_root / "reports"
    reports_dir.mkdir(exist_ok=True)

    # Write JSON report
    json_report_file = reports_dir / "fuzz-report.json"
    with open(json_report_file, "w") as f:
        json.dump(report_data, f, indent=2)

    # Write Markdown report
    md_report = generate_markdown_report(report_data)
    md_report_file = reports_dir / "fuzz-report.md"
    with open(md_report_file, "w") as f:
        f.write(md_report)

    # Print summary to console
    summary = report_data["summary"]
    print(f"\n🎯 Fuzzing Report Summary:")
    print(f"📊 Overall Status: {summary['overall_status']}")
    print(f"🔧 Tools Completed: {summary['tools_completed']}/{summary['total_tools']}")
    print(f"🚨 Critical Issues: {summary['critical_issues']}")

    if summary["recommendations"]:
        print(f"\n💡 Key Recommendations:")
        for rec in summary["recommendations"][:3]:  # Show first 3
            print(f"   {rec}")

    print(f"\n📁 Reports saved:")
    print(f"   📄 JSON: {json_report_file}")
    print(f"   📝 Markdown: {md_report_file}")

    # Exit with appropriate code
    if summary["critical_issues"] > 0:
        print(f"\n❌ Exiting with error code due to critical issues")
        sys.exit(1)
    elif summary["tools_completed"] == 0:
        print(f"\n⚠️ Exiting with warning - no tools completed")
        sys.exit(2)
    else:
        print(f"\n✅ Fuzzing report generation completed successfully")
        sys.exit(0)


if __name__ == "__main__":
    main()
