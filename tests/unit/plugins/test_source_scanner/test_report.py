#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Location: tests/unit/plugins/test_source_scanner/test_report.py
Copyright: 2026
Authors:Yaser
Unit tests for the Report class from source_scanner/report.py
"""

# Third-Party
import pytest

# First-Party
from plugins.source_scanner.models import Finding
from plugins.source_scanner.report import Report


@pytest.fixture
def sample_findings() -> list[Finding]:
    """Create a list of sample findings for testing."""
    return [
        Finding(
            scanner="semgrep",
            severity="ERROR",
            rule_id="rule-001",
            message="SQL Injection vulnerability detected",
            file_path="src/db.py",
            line=42,
            column=10,
            code_snippet="query = f'SELECT * FROM users WHERE id={id}'",
            help_url="https://example.com/rule-001",
        ),
        Finding(
            scanner="bandit",
            severity="WARNING",
            rule_id="B607",
            message="Starting a process with a partial executable path",
            file_path="src/utils.py",
            line=15,
            column=5,
            code_snippet="subprocess.call('ls')",
            help_url="https://bandit.readthedocs.io/en/latest/blacklists/blacklist_calls.html#b607-partial-paramiko-call-with-shell-equals-true",
        ),
        Finding(
            scanner="semgrep",
            severity="ERROR",
            rule_id="rule-002",
            message="Hardcoded password detected",
            file_path="src/config.py",
            line=8,
            column=15,
            code_snippet="password = 'admin123'",
            help_url="https://example.com/rule-002",
        ),
        Finding(
            scanner="semgrep",
            severity="WARNING",
            rule_id="rule-003",
            message="Weak random used for security",
            file_path="src/crypto.py",
            line=25,
            column=8,
            code_snippet="token = random.randint(0, 1000)",
            help_url="https://example.com/rule-003",
        ),
        Finding(
            scanner="bandit",
            severity="INFO",
            rule_id="B303",
            message="Use of insecure MD2, MD4, MD5, or SHA1 hash function",
            file_path="src/hash.py",
            line=5,
            column=12,
            code_snippet="hashlib.md5(data)",
            help_url="https://bandit.readthedocs.io",
        ),
        Finding(
            scanner="semgrep",
            severity="ERROR",
            rule_id="rule-001",
            message="Another SQL Injection in different location",
            file_path="src/models.py",
            line=100,
            column=20,
            code_snippet="execute(f'DELETE FROM {table}')",
            help_url="https://example.com/rule-001",
        ),
        Finding(
            scanner="bandit",
            severity="INFO",
            rule_id="B303",
            message="Use of insecure hash function in another file",
            file_path="src/utils/hashers.py",
            line=32,
            column=8,
            code_snippet="hashlib.sha1(password)",
            help_url="https://bandit.readthedocs.io",
        ),
    ]


class TestReportInitialization:
    """Test Report class initialization."""

    def test_report_init_with_findings(self, sample_findings: list[Finding]) -> None:
        """Test Report initialization with findings list."""
        report = Report(sample_findings)
        assert report.findings == sample_findings
        assert len(report.findings) == 7

    def test_report_init_empty_findings(self) -> None:
        """Test Report initialization with empty findings list."""
        findings: list[Finding] = []
        report = Report(findings)
        assert report.findings == []
        assert len(report.findings) == 0


class TestReportSummary:
    """Test Report.summary() method."""

    def test_summary_with_multiple_findings(self, sample_findings: list[Finding]) -> None:
        """Test summary generation with various severity levels."""
        report = Report(sample_findings)
        summary = report.summary()

        assert "total_issues" in summary
        assert "ERROR" in summary
        assert "WARNING" in summary
        assert "INFO" in summary
        assert summary["ERROR"] == 3
        assert summary["WARNING"] == 2
        assert summary["INFO"] == 2
        assert summary["total_issues"] == 7

    def test_summary_with_no_findings(self) -> None:
        """Test summary with empty findings list."""
        report = Report([])
        summary = report.summary()

        assert summary["ERROR"] == 0
        assert summary["WARNING"] == 0
        assert summary["INFO"] == 0
        assert summary["total_issues"] == 0

    def test_summary_only_errors(self) -> None:
        """Test summary with only ERROR level findings."""
        findings = [
            Finding(scanner="semgrep", severity="ERROR", rule_id="rule-1", message="Error 1"),
            Finding(scanner="semgrep", severity="ERROR", rule_id="rule-2", message="Error 2"),
            Finding(scanner="semgrep", severity="ERROR", rule_id="rule-3", message="Error 3"),
        ]
        report = Report(findings)
        summary = report.summary()

        assert summary["ERROR"] == 3
        assert summary["WARNING"] == 0
        assert summary["INFO"] == 0
        assert summary["total_issues"] == 3

    def test_summary_only_warnings(self) -> None:
        """Test summary with only WARNING level findings."""
        findings = [
            Finding(scanner="bandit", severity="WARNING", rule_id="w-1", message="Warning 1"),
            Finding(scanner="bandit", severity="WARNING", rule_id="w-2", message="Warning 2"),
        ]
        report = Report(findings)
        summary = report.summary()

        assert summary["ERROR"] == 0
        assert summary["WARNING"] == 2
        assert summary["INFO"] == 0
        assert summary["total_issues"] == 2

    def test_summary_only_info(self) -> None:
        """Test summary with only INFO level findings."""
        findings = [
            Finding(scanner="semgrep", severity="INFO", rule_id="i-1", message="Info 1"),
        ]
        report = Report(findings)
        summary = report.summary()

        assert summary["ERROR"] == 0
        assert summary["WARNING"] == 0
        assert summary["INFO"] == 1
        assert summary["total_issues"] == 1

    def test_summary_returns_dict(self, sample_findings: list[Finding]) -> None:
        """Test that summary returns a dictionary."""
        report = Report(sample_findings)
        summary = report.summary()
        assert isinstance(summary, dict)


class TestReportOrdered:
    """Test Report.ordered() method."""

    def test_ordered_with_multiple_findings(self, sample_findings: list[Finding]) -> None:
        """Test ordered grouping with multiple findings."""
        report = Report(sample_findings)
        ordered = report.ordered()

        assert "ERROR" in ordered
        assert "WARNING" in ordered
        assert "INFO" in ordered

        # Check ERROR severity grouping
        assert "rule-001" in ordered["ERROR"]
        assert "rule-002" in ordered["ERROR"]
        assert ordered["ERROR"]["rule-001"] == 2  # Two SQL injection findings
        assert ordered["ERROR"]["rule-002"] == 1  # One hardcoded password

        # Check WARNING severity grouping
        assert "rule-003" in ordered["WARNING"]
        assert ordered["WARNING"]["rule-003"] == 1

        # Check INFO severity grouping
        assert "B303" in ordered["INFO"]
        assert ordered["INFO"]["B303"] == 2  # Two insecure hash findings

    def test_ordered_with_no_findings(self) -> None:
        """Test ordered with empty findings list."""
        report = Report([])
        ordered = report.ordered()

        assert ordered["ERROR"] == {}
        assert ordered["WARNING"] == {}
        assert ordered["INFO"] == {}

    def test_ordered_counts_duplicates(self) -> None:
        """Test that ordered correctly counts rule occurrences."""
        findings = [
            Finding(scanner="semgrep", severity="ERROR", rule_id="sql-001", message="SQL Injection 1"),
            Finding(scanner="semgrep", severity="ERROR", rule_id="sql-001", message="SQL Injection 2"),
            Finding(scanner="semgrep", severity="ERROR", rule_id="sql-001", message="SQL Injection 3"),
        ]
        report = Report(findings)
        ordered = report.ordered()

        assert ordered["ERROR"]["sql-001"] == 3

    def test_ordered_separates_by_severity(self) -> None:
        """Test that ordered properly separates findings by severity."""
        findings = [
            Finding(scanner="semgrep", severity="ERROR", rule_id="rule-1", message="Error"),
            Finding(scanner="semgrep", severity="WARNING", rule_id="rule-1", message="Warning"),
            Finding(scanner="semgrep", severity="INFO", rule_id="rule-1", message="Info"),
        ]
        report = Report(findings)
        ordered = report.ordered()

        # Same rule_id should appear once in each severity group
        assert "rule-1" in ordered["ERROR"]
        assert "rule-1" in ordered["WARNING"]
        assert "rule-1" in ordered["INFO"]
        assert ordered["ERROR"]["rule-1"] == 1
        assert ordered["WARNING"]["rule-1"] == 1
        assert ordered["INFO"]["rule-1"] == 1

    def test_ordered_returns_dict_of_dicts(self, sample_findings: list[Finding]) -> None:
        """Test that ordered returns the correct nested structure."""
        report = Report(sample_findings)
        ordered = report.ordered()

        assert isinstance(ordered, dict)
        assert isinstance(ordered["ERROR"], dict)
        assert isinstance(ordered["WARNING"], dict)
        assert isinstance(ordered["INFO"], dict)

    def test_ordered_all_rule_ids_in_correct_severity(self, sample_findings: list[Finding]) -> None:
        """Test that each rule_id appears only in its severity group."""
        report = Report(sample_findings)
        ordered = report.ordered()

        # B607 should only be in WARNING
        for severity in ["ERROR", "INFO"]:
            assert "B607" not in ordered[severity]
        assert "B607" in ordered["WARNING"]

        # rule-003 should only be in WARNING
        for severity in ["ERROR", "INFO"]:
            assert "rule-003" not in ordered[severity]
        assert "rule-003" in ordered["WARNING"]


class TestReportIntegration:
    """Integration tests for Report class."""

    def test_summary_and_ordered_consistency(self, sample_findings: list[Finding]) -> None:
        """Test that summary and ordered methods are consistent."""
        report = Report(sample_findings)
        summary = report.summary()
        ordered = report.ordered()

        # Total from ordered should match summary
        error_count = sum(ordered["ERROR"].values())
        warning_count = sum(ordered["WARNING"].values())
        info_count = sum(ordered["INFO"].values())

        assert error_count == summary["ERROR"]
        assert warning_count == summary["WARNING"]
        assert info_count == summary["INFO"]
        assert error_count + warning_count + info_count == summary["total_issues"]

    def test_report_with_single_finding(self) -> None:
        """Test Report with a single finding."""
        finding = Finding(scanner="semgrep", severity="ERROR", rule_id="rule-001", message="Single issue")
        report = Report([finding])

        summary = report.summary()
        assert summary["total_issues"] == 1
        assert summary["ERROR"] == 1

        ordered = report.ordered()
        assert "rule-001" in ordered["ERROR"]
        assert ordered["ERROR"]["rule-001"] == 1

    def test_report_with_many_unique_rules(self) -> None:
        """Test Report with many unique rules."""
        findings = [Finding(scanner="semgrep", severity="ERROR", rule_id=f"rule-{i}", message=f"Issue {i}") for i in range(10)]
        report = Report(findings)

        summary = report.summary()
        assert summary["total_issues"] == 10
        assert len(report.ordered()["ERROR"]) == 10

    def test_report_preserves_findings_order(self) -> None:
        """Test that Report preserves the original findings list."""
        findings = [Finding(scanner="semgrep", severity="ERROR", rule_id=f"r{i}", message=f"msg{i}") for i in range(5)]
        report = Report(findings)

        assert report.findings == findings
        assert len(report.findings) == 5
        for i, finding in enumerate(report.findings):
            assert finding.rule_id == f"r{i}"
