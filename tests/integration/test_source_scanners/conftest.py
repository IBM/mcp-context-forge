#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pytest fixtures for integration tests of source_scanner plugin.

Location: tests/integration/test_source_scanners/conftest.py
Copyright 2026
Authors: Yaser
"""

# Standard
from collections import defaultdict
from datetime import datetime
import os
from pathlib import Path
import sys
from typing import Any, Dict

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import PluginConfig
from plugins.source_scanner.source_scanner import SourceScannerPlugin

# Add plugin to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def plugin_config() -> PluginConfig:
    """Create a SourceScannerPlugin config for testing.

    Configuration can be customized via environment variables:
    - SCANNER_SEMGREP_ENABLED: Enable Semgrep (default: true)
    - SCANNER_BANDIT_ENABLED: Enable Bandit (default: true)
    - SCANNER_TIMEOUT: Scan timeout in seconds (default: 300)
    - SCANNER_CLONE_TIMEOUT: Clone timeout in seconds (default: 60)
    - SCANNER_MAX_SIZE_MB: Max repo size in MB (default: 1000)
    """
    return PluginConfig(
        name="test-source-scanner",
        kind="source_scanner",
        namespace="plugins",
        version="1.0.0",
        config={
            "semgrep": {
                "enabled": os.getenv("SCANNER_SEMGREP_ENABLED", "true").lower() == "true",
                "rulesets": ["p/security-audit", "p/owasp-top-ten"],
            },
            "bandit": {
                "enabled": os.getenv("SCANNER_BANDIT_ENABLED", "true").lower() == "true",
                "severity": "medium",
            },
            "severity_threshold": "INFO",
            "fail_on_critical": False,
            "scan_timeout_seconds": int(os.getenv("SCANNER_TIMEOUT", "300")),
            "clone_timeout_seconds": int(os.getenv("SCANNER_CLONE_TIMEOUT", "60")),
            "max_repo_size_mb": int(os.getenv("SCANNER_MAX_SIZE_MB", "1000")),
            "github_token_env": "GITHUB_TOKEN",
        },
    )


@pytest.fixture
def source_scanner_plugin(plugin_config: PluginConfig) -> SourceScannerPlugin:
    """Create and return a SourceScannerPlugin instance."""
    return SourceScannerPlugin(plugin_config)


@pytest.fixture
def repo_url() -> str:
    """Return the repository URL for testing.

    Set TEST_REPO_URL environment variable to change repository:

    Examples:
        # Test against damn-vulnerable-MCP-server (Python, JavaScript)
        TEST_REPO_URL=https://github.com/harishsg993010/damn-vulnerable-MCP-server.git

        # Test against WebGoat (Java, JavaScript)
        TEST_REPO_URL=https://github.com/WebGoat/WebGoat.git

        # Test against your own repo
        TEST_REPO_URL=https://github.com/your-org/your-repo.git
    """
    return os.getenv("TEST_REPO_URL", "https://github.com/harishsg993010/damn-vulnerable-MCP-server.git")


@pytest.fixture
def repo_ref() -> str:
    """Return the reference (branch/tag) for testing.

    Set TEST_REPO_REF environment variable to use different branch/tag:

    Examples:
        TEST_REPO_REF=main
        TEST_REPO_REF=develop
        TEST_REPO_REF=v1.2.3
    """
    return os.getenv("TEST_REPO_REF", "main")


@pytest.fixture(scope="session")
def summary_data() -> Dict[str, Any]:
    """Session-scoped fixture to collect summary data across all tests."""
    return {
        "start_time": datetime.now(),
        "total_findings": 0,
        "findings_by_scanner": defaultdict(int),  # {"semgrep": N, "bandit": M}
        "severity_distribution": defaultdict(int),  # {"ERROR": N, "WARNING": M, "INFO": K}
        "policy_decisions": [],  # List of policy decision dicts
        "scan_results": [],  # List of scan results
        "test_count": 0,
        "repo_url": "",
        "repo_ref": "",
    }


def pytest_sessionstart(session):
    """Initialize session data storage."""
    session.summary_data = {
        "start_time": datetime.now(),
        "total_findings": 0,
        "findings_by_scanner": defaultdict(int),
        "severity_distribution": defaultdict(int),
        "policy_decisions": [],
        "scan_results": [],
        "test_count": 0,
        "repo_url": "",
        "repo_ref": "",
    }


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: integration tests")


def pytest_runtest_makereport(item, call):
    """Capture test results for summary reporting."""
    if call.when == "call" and "integration" in item.keywords:
        # Increment test count on success
        if call.excinfo is None:
            if hasattr(item.session, "summary_data"):
                item.session.summary_data["test_count"] += 1


def pytest_sessionfinish(session, exitstatus):
    """Print summary report at end of test session."""
    # Access summary data if it exists
    if hasattr(session, "summary_data"):
        _print_summary_report(session.summary_data)


def _evaluate_policy(summary_data: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate security policy based on findings severity.

    Policy Rules:
    - BLOCKED if: errors > 0 (critical issues found)
    - ALLOWED if: only warnings and info (no critical issues)
    """
    error_count = summary_data["severity_distribution"].get("ERROR", 0)
    warning_count = summary_data["severity_distribution"].get("WARNING", 0)
    info_count = summary_data["severity_distribution"].get("INFO", 0)

    # Policy decision logic
    if error_count > 0:
        decision = "BLOCKED"
        reason = f"Found {error_count} critical error(s)"
    else:
        decision = "ALLOWED"
        reason = f"No critical errors (warnings: {warning_count}, info: {info_count})"

    return {
        "decision": decision,
        "reason": reason,
        "error_count": error_count,
        "warning_count": warning_count,
        "info_count": info_count,
    }


def _print_summary_report(summary_data: Dict[str, Any]) -> None:
    """Print comprehensive security scan summary report."""
    # Calculate execution time
    duration = datetime.now() - summary_data["start_time"]
    duration_str = f"{int(duration.total_seconds() // 60)}m {int(duration.total_seconds() % 60)}s"

    # Evaluate policy
    policy = _evaluate_policy(summary_data)

    # Build report
    print("\n" + "=" * 75)
    print("  SECURITY SCAN SUMMARY REPORT")
    print("=" * 75)
    print(f"Repository: {summary_data.get('repo_url', 'N/A')}")
    print(f"Branch/Ref: {summary_data.get('repo_ref', 'N/A')}")
    print(f"Execution Time: {duration_str}")

    print("\nFINDINGS SUMMARY:")
    print(f"  Total Findings: {summary_data['total_findings']}")
    print(f"  Semgrep Findings: {summary_data['findings_by_scanner'].get('semgrep', 0)}")
    print(f"  Bandit Findings: {summary_data['findings_by_scanner'].get('bandit', 0)}")

    # Add severity breakdown if findings exist
    if summary_data["total_findings"] > 0:
        print("\nSEVERITY BREAKDOWN:")
        severity_order = ["ERROR", "WARNING", "INFO"]
        for severity in severity_order:
            count = summary_data["severity_distribution"].get(severity, 0)
            if count > 0:
                print(f"  {severity}: {count}")

    # Add policy decision
    print("\nPOLICY DECISION:")
    print(f"  [{policy['decision']}] {policy['reason']}")

    print(f"\nTEST RESULTS: {summary_data.get('test_count', 0)} tests passed")
    print("=" * 75 + "\n")
