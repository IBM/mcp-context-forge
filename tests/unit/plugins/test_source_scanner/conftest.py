#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Location: tests/unit/plugins/test_source_scanner/__init__.py
Copyright: 2025
SPDX-License-Identifier: Apache-2.0
Authors: Yaser
Unit tests for MCP Source Scanner Plugin.
Shared pytest fixtures and configuration for source scanner tests."""

# Standard
from pathlib import Path
from typing import Any, Dict

# Third-Party
import pytest
from pytest import TestReport


def pytest_configure(config: pytest.Config) -> None:
    """Register custom pytest markers."""
    config.addinivalue_line("markers", "requires_semgrep: marks tests that require semgrep installed")
    config.addinivalue_line("markers", "requires_bandit: marks tests that require bandit installed")
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")


# ===== Directory Fixtures =====


@pytest.fixture
def python_project_dir(tmp_path: Path) -> Path:
    """Create mock Python project directory with pyproject.toml."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'test-project'\n")
    return tmp_path


@pytest.fixture
def js_project_dir(tmp_path: Path) -> Path:
    """Create mock JavaScript project directory with package.json."""
    package_json = tmp_path / "package.json"
    package_json.write_text('{"name": "test-app", "version": "1.0.0"}\n')
    return tmp_path


@pytest.fixture
def go_project_dir(tmp_path: Path) -> Path:
    """Create mock Go project directory with go.mod."""
    go_mod = tmp_path / "go.mod"
    go_mod.write_text("module github.com/org/project\n\ngo 1.21\n")
    return tmp_path


@pytest.fixture
def java_maven_project_dir(tmp_path: Path) -> Path:
    """Create mock Java Maven project directory with pom.xml."""
    pom = tmp_path / "pom.xml"
    pom.write_text(
        '<?xml version="1.0"?>\n'
        "<project>\n"
        "  <modelVersion>4.0.0</modelVersion>\n"
        "  <groupId>com.example</groupId>\n"
        "  <artifactId>test-app</artifactId>\n"
        "  <version>1.0.0</version>\n"
        "</project>\n"
    )
    return tmp_path


@pytest.fixture
def ruby_project_dir(tmp_path: Path) -> Path:
    """Create mock Ruby project directory with Gemfile."""
    gemfile = tmp_path / "Gemfile"
    gemfile.write_text("source 'https://rubygems.org'\n\ngem 'rails'\n")
    return tmp_path


@pytest.fixture
def php_project_dir(tmp_path: Path) -> Path:
    """Create mock PHP project directory with composer.json."""
    composer = tmp_path / "composer.json"
    composer.write_text('{"name": "org/project", "type": "library"}\n')
    return tmp_path


@pytest.fixture
def mixed_project_dir(tmp_path: Path) -> Path:
    """Create project with multiple languages."""
    # Python
    (tmp_path / "script.py").write_text("print('hello')")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")

    # JavaScript
    (tmp_path / "index.js").write_text("console.log('hello');")
    (tmp_path / "package.json").write_text('{"name": "test"}\n')

    return tmp_path


@pytest.fixture
def empty_directory(tmp_path: Path) -> Path:
    """Create empty directory (no project markers)."""
    return tmp_path


# ===== Scanner Configuration Fixtures =====


@pytest.fixture
def semgrep_scanner_config() -> Dict[str, Any]:
    """Configuration for Semgrep scanner."""
    return {"enabled": True, "rulesets": ["p/security-audit", "p/owasp-top-ten"], "extra_args": []}


@pytest.fixture
def bandit_scanner_config() -> Dict[str, Any]:
    """Configuration for Bandit scanner."""
    return {"enabled": True, "severity": "medium", "confidence": "medium"}


@pytest.fixture
def plugin_config() -> Dict[str, Any]:
    """Configuration for SourceScannerPlugin."""
    return {
        "scanners": {"semgrep": {"enabled": True, "rulesets": ["p/security-audit", "p/owasp-top-ten"], "extra_args": []}, "bandit": {"enabled": True, "severity": "medium", "confidence": "medium"}},
        "severity_threshold": "WARNING",
        "fail_on_critical": True,
        "clone_timeout_seconds": 120,
        "scan_timeout_seconds": 600,
        "max_repo_size_mb": 500,
        "cache_by_commit": True,
        "cache_ttl_hours": 168,
    }


# ===== Mock Output Fixtures =====


@pytest.fixture
def mock_semgrep_sarif_output() -> Dict[str, Any]:
    """Mock SARIF output from Semgrep."""
    return {
        "version": "2.1.0",
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "runs": [
            {
                "tool": {"driver": {"name": "Semgrep", "version": "1.45.0", "informationUri": "https://semgrep.dev"}},
                "results": [
                    {
                        "ruleId": "python.django.security.sql-injection",
                        "level": "error",
                        "message": {"text": "SQL injection vulnerability detected"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": "handlers.py"},
                                    "region": {"startLine": 45, "startColumn": 20, "endLine": 45, "endColumn": 63, "snippet": {"text": 'query = f"SELECT * FROM users WHERE id = {user_id}"'}},
                                }
                            }
                        ],
                    }
                ],
            }
        ],
    }


@pytest.fixture
def mock_semgrep_sarif_empty() -> Dict[str, Any]:
    """Mock empty SARIF output from Semgrep (no findings)."""
    return {
        "version": "2.1.0",
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "runs": [{"tool": {"driver": {"name": "Semgrep", "version": "1.45.0"}}, "results": []}],
    }


@pytest.fixture
def mock_bandit_json_output() -> Dict[str, Any]:
    """Mock JSON output from Bandit."""
    return {
        "metrics": {"_totals": {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 0, "LOW": 0}},
        "results": [
            {
                "test_id": "B201",
                "test_name": "flask_debug_true",
                "issue_severity": "HIGH",
                "issue_confidence": "MEDIUM",
                "issue_text": "Flask debug mode is on",
                "line_number": 10,
                "filename": "app.py",
                "line_range": [10, 11],
            },
            {
                "test_id": "B301",
                "test_name": "pickle",
                "issue_severity": "CRITICAL",
                "issue_confidence": "HIGH",
                "issue_text": "Possible deserialization using the pickle module detected",
                "line_number": 25,
                "filename": "app.py",
                "line_range": [25, 26],
            },
        ],
    }


@pytest.fixture
def mock_bandit_json_empty() -> Dict[str, Any]:
    """Mock empty JSON output from Bandit (no findings)."""
    return {"metrics": {"_totals": {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}}, "results": []}


# ===== Sample Object Fixtures =====


@pytest.fixture
def sample_finding() -> Dict[str, Any]:
    """Create sample Finding object."""
    return {
        "rule_id": "B201",
        "rule_name": "Flask debug enabled",
        "severity": "HIGH",
        "file_path": "app.py",
        "line_number": 10,
        "column_number": 1,
        "message": "Flask debug mode is enabled",
        "code_snippet": "app.run(debug=True)",
        "remediation": "Set debug=False in production",
        "documentation_url": "https://bandit.readthedocs.io/",
    }


@pytest.fixture
def critical_finding() -> Dict[str, Any]:
    """Create sample CRITICAL severity finding."""
    return {
        "rule_id": "B301",
        "rule_name": "Pickle vulnerability",
        "severity": "CRITICAL",
        "file_path": "app.py",
        "line_number": 25,
        "column_number": 5,
        "message": "Possible deserialization using pickle module",
        "code_snippet": "data = pickle.loads(user_input)",
        "remediation": "Use json instead of pickle",
        "documentation_url": "https://bandit.readthedocs.io/",
    }


@pytest.fixture
def sample_findings_list() -> list[Dict[str, Any]]:
    """Create list of sample findings with different severities."""
    return [
        {"rule_id": "B201", "severity": "HIGH", "file_path": "app.py", "line_number": 10},
        {"rule_id": "B301", "severity": "CRITICAL", "file_path": "app.py", "line_number": 25},
        {"rule_id": "B601", "severity": "MEDIUM", "file_path": "database.py", "line_number": 42},
        {"rule_id": "B602", "severity": "LOW", "file_path": "utils.py", "line_number": 5},
    ]


@pytest.fixture
def sample_sarif_result() -> Dict[str, Any]:
    """Sample SARIF result structure."""
    return {
        "ruleId": "python.django.security.sql-injection",
        "level": "error",
        "message": {"text": "SQL injection via string concatenation"},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": "handlers.py"},
                    "region": {"startLine": 45, "startColumn": 20, "snippet": {"text": 'query = f"SELECT * FROM users WHERE id = {user_id}"'}},
                }
            }
        ],
    }


@pytest.fixture
def sample_bandit_result() -> Dict[str, Any]:
    """Sample Bandit result structure."""
    return {
        "test_id": "B201",
        "test_name": "flask_debug_true",
        "issue_severity": "HIGH",
        "issue_confidence": "MEDIUM",
        "issue_text": "Flask debug mode is on",
        "line_number": 10,
        "filename": "app.py",
        "line_range": [10, 11],
    }


# ===== Vulnerable Code Fixtures =====


@pytest.fixture
def vulnerable_python_code(tmp_path: Path) -> Path:
    """Create Python file with security vulnerabilities."""
    code = tmp_path / "app.py"
    code.write_text(
        "import pickle\n"
        "from flask import Flask, request\n\n"
        "app = Flask(__name__)\n\n"
        "@app.route('/process')\n"
        "def process():\n"
        "    user_id = request.args.get('id')\n"
        "    # SQL Injection vulnerability\n"
        "    query = f'SELECT * FROM users WHERE id = {user_id}'\n"
        "    # Result: SQL injection possible\n"
        "    return query\n\n"
        "if __name__ == '__main__':\n"
        "    # Flask debug mode enabled\n"
        "    app.run(debug=True)\n"
    )
    return tmp_path


@pytest.fixture
def vulnerable_javascript_code(tmp_path: Path) -> Path:
    """Create JavaScript file with security vulnerabilities."""
    code = tmp_path / "app.js"
    code.write_text(
        "const express = require('express');\n"
        "const app = express();\n\n"
        "app.get('/eval', (req, res) => {\n"
        "    const userInput = req.query.code;\n"
        "    // Code injection vulnerability\n"
        "    eval(userInput);\n"
        "    res.send('OK');\n"
        "});\n"
    )
    return tmp_path


# ===== Git Fixtures =====


@pytest.fixture
def mock_git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create mock Git repository."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    (repo_path / "README.md").write_text("# Test Repository\n")
    return repo_path


# ===== Duplicate Findings Fixtures =====


@pytest.fixture
def duplicate_findings() -> list[Dict[str, Any]]:
    """Create list of findings with duplicates."""
    return [
        {"rule_id": "B201", "file_path": "app.py", "line_number": 10, "severity": "HIGH", "message": "Flask debug enabled"},
        {"rule_id": "B201", "file_path": "app.py", "line_number": 10, "severity": "HIGH", "message": "Flask debug enabled"},
        {"rule_id": "B301", "file_path": "app.py", "line_number": 25, "severity": "CRITICAL", "message": "Pickle vulnerability"},
    ]


@pytest.fixture
def no_duplicate_findings() -> list[Dict[str, Any]]:
    """Create list of unique findings."""
    return [
        {"rule_id": "B201", "file_path": "app.py", "line_number": 10, "severity": "HIGH"},
        {"rule_id": "B301", "file_path": "app.py", "line_number": 25, "severity": "CRITICAL"},
        {"rule_id": "B601", "file_path": "database.py", "line_number": 42, "severity": "MEDIUM"},
    ]


# ===== Server Request Fixtures =====


@pytest.fixture
def mock_server_request() -> Dict[str, Any]:
    """Mock server registration request with GitHub source."""
    return {"name": "test-mcp-server", "source": {"type": "github", "repo": "org/mcp-server", "branch": "main"}, "enabled": True}


@pytest.fixture
def mock_server_request_with_tag() -> Dict[str, Any]:
    """Mock server registration request with git tag."""
    return {"name": "test-mcp-server", "source": {"type": "github", "repo": "org/mcp-server", "tag": "v1.0.0"}, "enabled": True}


@pytest.fixture
def mock_server_request_with_commit() -> Dict[str, Any]:
    """Mock server registration request with commit SHA."""
    return {"name": "test-mcp-server", "source": {"type": "github", "repo": "org/mcp-server", "commit_sha": "abc123def456"}, "enabled": True}


# Dictionary to store test results
test_results: Dict[str, list[tuple[str, str]]] = {}


def pytest_runtest_logreport(report: TestReport) -> None:
    """Hook to capture test results."""
    if report.when == "call":
        test_class = report.nodeid.split("::")[0].split("/")[-1]
        test_name = report.nodeid.split("::")[-1]
        if test_class not in test_results:
            test_results[test_class] = []
        test_results[test_class].append((test_name, report.outcome))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Hook to print custom summary at the end of the test session."""
    print("\n\nCustom Test Summary:")
    for test_class, results in test_results.items():
        passed_tests = [test for test, outcome in results if outcome == "passed"]
        failed_tests = [test for test, outcome in results if outcome == "failed"]
        print(f"\n{test_class} - {len(passed_tests)} tests PASSED")
        for test in passed_tests:
            print(f"✅ {test}")
        if failed_tests:
            print(f"\n❌ FAILED: {len(failed_tests)} tests")
            for test in failed_tests:
                print(f"❌ {test}")
