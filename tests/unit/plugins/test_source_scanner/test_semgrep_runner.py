#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_source_scanner/test_semgrep_runner.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0 
Authors: Yasser
Unit tests for Semgrep runner integration.

Test coverage includes:
- Initialization with various configurations
- Command building with different rulesets and arguments
- SARIF output parsing (empty, single, multiple findings)
- Severity mapping (all severity levels)
- Finding object validation
- Error handling
"""

# Standard
from tempfile import mkdtemp
from typing import Any
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from plugins.source_scanner.scanners.semgrep_runner import SemgrepRunner
from plugins.source_scanner.types import Finding
from plugins.source_scanner.utils.exec import ExecResult


class TestSemgrepRunnerInitialization:

    def test_init_with_default_config(self) -> None:
        """Test initialization uses defaults when config is minimal."""
        config = {"enabled": True}
        runner = SemgrepRunner(config)

        assert runner.enabled is True, "enabled should be True from config"
        assert runner.rulesets == ["p/security-audit"], f"Expected default ruleset ['p/security-audit'], got {runner.rulesets}"
        assert runner.extra_args == [], f"Expected empty extra_args, got {runner.extra_args}"
        assert runner.timeout == 300, f"Expected default timeout 300, got {runner.timeout}"

    def test_init_with_custom_config(self) -> None:
        """Test initialization with all custom configuration values."""
        config = {
            "enabled": True,
            "rulesets": ["p/security-audit", "p/python", "p/javascript"],
            "extra_args": ["--verbose", "--timeout=60"],
            "timeout": 600,
        }
        runner = SemgrepRunner(config)

        assert runner.enabled is True, "enabled should match config"
        assert len(runner.rulesets) == 3, f"Expected 3 rulesets, got {len(runner.rulesets)}"
        assert "p/python" in runner.rulesets, "p/python should be in rulesets"
        assert runner.extra_args == ["--verbose", "--timeout=60"], f"extra_args mismatch: {runner.extra_args}"
        assert runner.timeout == 600, f"Expected timeout 600, got {runner.timeout}"

    def test_init_disabled_scanner(self) -> None:
        """Test initialization when scanner is disabled."""
        config = {"enabled": False}
        runner = SemgrepRunner(config)

        assert runner.enabled is False, "enabled should be False"


class TestCommandBuilding:
    """Test suite for Semgrep command construction."""

    def test_build_command_basic_structure(self) -> None:
        """Test basic command includes all required parts."""
        config = {"rulesets": ["p/security-audit"]}
        runner = SemgrepRunner(config)

        command = runner.build_command("/tmp/repo")

        assert "semgrep" in command, f"Command should start with 'semgrep': {command}"
        assert "scan" in command, f"Command should include 'scan': {command}"
        assert "--config" in command, f"Command should include '--config' flag: {command}"
        assert "p/security-audit" in command, f"Command should include ruleset: {command}"
        assert "--json" in command, f"Command should include '--json' output format: {command}"
        assert "/tmp/repo" in command, f"Command should include repo path: {command}"

    def test_build_command_multiple_rulesets(self) -> None:
        """Test command building with multiple rulesets."""
        config = {"rulesets": ["p/security-audit", "p/python", "p/owasp-top-ten"]}
        runner = SemgrepRunner(config)

        command = runner.build_command("/tmp/repo")

        config_count = command.count("--config")
        assert config_count == 3, f"Expected 3 '--config' flags, got {config_count}"
        assert "p/security-audit" in command, "p/security-audit not in command"
        assert "p/python" in command, "p/python not in command"
        assert "p/owasp-top-ten" in command, "p/owasp-top-ten not in command"

    def test_build_command_with_extra_arguments(self) -> None:
        """Test command building includes extra arguments."""
        config = {"extra_args": ["--verbose", "--timeout=30", "--strict"]}
        runner = SemgrepRunner(config)

        command = runner.build_command("/tmp/repo")

        assert "--verbose" in command, f"--verbose not in command: {command}"
        assert "--timeout=30" in command, f"--timeout=30 not in command: {command}"
        assert "--strict" in command, f"--strict not in command: {command}"

    def test_build_command_empty_rulesets(self) -> None:
        """Test command building with empty rulesets list."""
        config: dict[str, Any] = {"rulesets": []}
        runner = SemgrepRunner(config)

        command = runner.build_command("/tmp/repo")

        assert "semgrep" in command, "Command should still be valid"
        assert "--json" in command, "JSON output should still be included"


class TestSARIFParsing:
    """Test suite for Semgrep SARIF output parsing."""

    def test_parse_empty_results(self) -> None:
        """Test parsing empty results returns empty list."""
        config: dict[str, Any] = {}
        runner = SemgrepRunner(config)

        sarif: dict[str, Any] = {"results": []}
        findings = runner.parse_sarif_output(sarif)

        assert isinstance(findings, list), f"Expected list, got {type(findings)}"
        assert len(findings) == 0, f"Expected empty list, got {len(findings)} findings"

    def test_parse_single_finding(self) -> None:
        """Test parsing single finding from output."""
        config: dict[str, Any] = {}
        runner = SemgrepRunner(config)

        sarif = {
            "results": [
                {
                    "check_id": "python.django.sql-injection",
                    "severity": "ERROR",
                    "message": "SQL injection",
                    "path": "app.py",
                    "start": {"line": 42, "col": 10},
                    "extra": {"message": "Parameterized query needed", "lines": "query = f'SELECT * FROM users WHERE id={uid}'", "doc_url": "https://semgrep.dev/r/sql-injection"},
                }
            ]
        }
        findings = runner.parse_sarif_output(sarif)

        assert len(findings) == 1, f"Expected 1 finding, got {len(findings)}"
        finding = findings[0]
        assert finding.scanner == "semgrep", f"scanner should be 'semgrep', got {finding.scanner}"
        assert finding.rule_id == "python.django.sql-injection", f"rule_id mismatch: {finding.rule_id}"
        assert finding.severity == "ERROR", f"severity should be ERROR, got {finding.severity}"
        assert finding.file_path == "app.py", f"file_path mismatch: {finding.file_path}"
        assert finding.line == 42, f"line should be 42, got {finding.line}"
        assert finding.column == 10, f"column should be 10, got {finding.column}"

    def test_parse_multiple_findings(self) -> None:
        """Test parsing multiple findings."""
        config: dict[str, Any] = {}
        runner = SemgrepRunner(config)

        sarif = {
            "results": [
                {
                    "check_id": "rule.one",
                    "severity": "ERROR",
                    "message": "Issue 1",
                    "path": "file1.py",
                    "start": {"line": 10},
                },
                {
                    "check_id": "rule.two",
                    "severity": "WARNING",
                    "message": "Issue 2",
                    "path": "file2.py",
                    "start": {"line": 20},
                },
                {
                    "check_id": "rule.three",
                    "severity": "INFO",
                    "message": "Issue 3",
                    "path": "file3.py",
                    "start": {"line": 30},
                },
            ]
        }
        findings = runner.parse_sarif_output(sarif)

        assert len(findings) == 3, f"Expected 3 findings, got {len(findings)}"
        assert findings[0].rule_id == "rule.one", f"First finding rule_id mismatch"
        assert findings[1].rule_id == "rule.two", f"Second finding rule_id mismatch"
        assert findings[2].rule_id == "rule.three", f"Third finding rule_id mismatch"

    def test_parse_error_in_sarif(self) -> None:
        """Test handling error field in output."""
        config: dict[str, Any] = {}
        runner = SemgrepRunner(config)

        sarif = {"error": "Semgrep execution failed"}
        findings = runner.parse_sarif_output(sarif)

        assert len(findings) == 0, f"Expected empty list on error, got {len(findings)}"

    def test_parse_missing_optional_fields(self) -> None:
        """Test handling missing optional fields gracefully."""
        config: dict[str, Any] = {}
        runner = SemgrepRunner(config)

        sarif = {
            "results": [
                {
                    "check_id": "rule.minimal",
                    "severity": "INFO",
                    "message": "Minimal finding",
                    "path": "file.py",
                    "start": {"line": 5},
                }
            ]
        }
        findings = runner.parse_sarif_output(sarif)

        assert len(findings) == 1, "Should parse minimal finding"
        finding = findings[0]
        assert finding.column is None, f"column should be None, got {finding.column}"
        assert finding.code_snippet is None, f"code_snippet should be None, got {finding.code_snippet}"
        assert finding.help_url is None, f"help_url should be None, got {finding.help_url}"

    def test_parse_missing_start_line_defaults_to_none(self) -> None:
        """Test missing start.line field defaults to None."""
        config: dict[str, Any] = {}
        runner = SemgrepRunner(config)

        sarif: dict[str, Any] = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "INFO",
                    "message": "Issue",
                    "path": "file.py",
                    "start": {},
                }
            ]
        }
        findings = runner.parse_sarif_output(sarif)

        assert findings[0].line is None, f"line should be None when missing, got {findings[0].line}"


class TestSeverityMapping:
    """Test suite for severity level mapping."""

    def test_severity_error_stays_error(self) -> None:
        """Test ERROR severity maps to ERROR."""
        config: dict[str, Any] = {}
        runner = SemgrepRunner(config)

        sarif: dict[str, Any] = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "ERROR",
                    "message": "Error msg",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner.parse_sarif_output(sarif)

        assert findings[0].severity == "ERROR", f"ERROR should map to ERROR, got {findings[0].severity}"

    def test_severity_warning_stays_warning(self) -> None:
        """Test WARNING severity maps to WARNING."""
        config: dict[str, Any] = {}
        runner = SemgrepRunner(config)

        sarif: dict[str, Any] = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "WARNING",
                    "message": "Warn msg",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner.parse_sarif_output(sarif)

        assert findings[0].severity == "WARNING", f"WARNING should map to WARNING, got {findings[0].severity}"

    def test_severity_info_stays_info(self) -> None:
        """Test INFO severity maps to INFO."""
        config: dict[str, Any] = {}
        runner = SemgrepRunner(config)

        sarif: dict[str, Any] = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "INFO",
                    "message": "Info msg",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner.parse_sarif_output(sarif)

        assert findings[0].severity == "INFO", f"INFO should map to INFO, got {findings[0].severity}"

    def test_severity_high_maps_to_error(self) -> None:
        """Test HIGH severity maps to ERROR."""
        config: dict[str, Any] = {}
        runner = SemgrepRunner(config)

        sarif: dict[str, Any] = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "HIGH",
                    "message": "High severity",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner.parse_sarif_output(sarif)

        assert findings[0].severity == "ERROR", f"HIGH should map to ERROR, got {findings[0].severity}"

    def test_severity_medium_maps_to_warning(self) -> None:
        """Test MEDIUM severity maps to WARNING."""
        config: dict[str, Any] = {}
        runner = SemgrepRunner(config)

        sarif: dict[str, Any] = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "MEDIUM",
                    "message": "Medium severity",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner.parse_sarif_output(sarif)

        assert findings[0].severity == "WARNING", f"MEDIUM should map to WARNING, got {findings[0].severity}"

    def test_severity_low_maps_to_info(self) -> None:
        """Test LOW severity maps to INFO."""
        config: dict[str, Any] = {}
        runner = SemgrepRunner(config)

        sarif: dict[str, Any] = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "LOW",
                    "message": "Low severity",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner.parse_sarif_output(sarif)

        assert findings[0].severity == "INFO", f"LOW should map to INFO, got {findings[0].severity}"

    def test_severity_unknown_defaults_to_info(self) -> None:
        """Test unknown severity defaults to INFO."""
        config: dict[str, Any] = {}
        runner = SemgrepRunner(config)

        sarif: dict[str, Any] = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "CRITICAL",  # not in mapping
                    "message": "Unknown severity",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner.parse_sarif_output(sarif)

        assert findings[0].severity == "INFO", f"Unknown severity should default to INFO, got {findings[0].severity}"

    def test_severity_case_insensitive(self) -> None:
        """Test severity mapping is case-insensitive."""
        config: dict[str, Any] = {}
        runner = SemgrepRunner(config)

        sarif: dict[str, Any] = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "error",  # lowercase
                    "message": "Lowercase error",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner.parse_sarif_output(sarif)

        assert findings[0].severity == "ERROR", f"Lowercase 'error' should map to ERROR, got {findings[0].severity}"


class TestFindingObject:
    """Test suite for Finding object validation."""

    def test_finding_object_scanner_field(self) -> None:
        """Test Finding object has correct scanner field."""
        config: dict[str, Any] = {}
        runner = SemgrepRunner(config)

        sarif: dict[str, Any] = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "INFO",
                    "message": "Test",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner.parse_sarif_output(sarif)

        assert findings[0].scanner == "semgrep", f"scanner should be 'semgrep', got {findings[0].scanner}"

    def test_finding_object_all_attributes(self) -> None:
        """Test Finding object has all required attributes."""
        config: dict[str, Any] = {}
        runner = SemgrepRunner(config)

        sarif: dict[str, Any] = {
            "results": [
                {
                    "check_id": "test.rule.id",
                    "severity": "ERROR",
                    "message": "Test message",
                    "path": "test/file.py",
                    "start": {"line": 99, "col": 42},
                    "extra": {"message": "Detailed message", "lines": "code = vulnerable()", "doc_url": "https://docs.example.com/rule"},
                }
            ]
        }
        findings = runner.parse_sarif_output(sarif)
        finding = findings[0]

        assert hasattr(finding, "scanner"), "Finding should have 'scanner' attribute"
        assert hasattr(finding, "rule_id"), "Finding should have 'rule_id' attribute"
        assert hasattr(finding, "severity"), "Finding should have 'severity' attribute"
        assert hasattr(finding, "message"), "Finding should have 'message' attribute"
        assert hasattr(finding, "file_path"), "Finding should have 'file_path' attribute"
        assert hasattr(finding, "line"), "Finding should have 'line' attribute"
        assert hasattr(finding, "column"), "Finding should have 'column' attribute"
        assert hasattr(finding, "code_snippet"), "Finding should have 'code_snippet' attribute"
        assert hasattr(finding, "help_url"), "Finding should have 'help_url' attribute"


@pytest.mark.requires_semgrep
class TestIntegration:
    """Integration tests requiring actual semgrep installation."""

    @pytest.mark.asyncio
    async def test_run_returns_list(self) -> None:
        """Test run method returns a list."""
        config: dict[str, Any] = {"rulesets": ["p/security-audit"]}
        runner = SemgrepRunner(config)

        with patch("plugins.source_scanner.scanners.semgrep_runner.run_command", new_callable=AsyncMock) as mock_run_command:
            mock_run_command.side_effect = [
                ExecResult(returncode=0, stdout="", stderr="", timed_out=False),
                ExecResult(returncode=0, stdout='{"results": []}', stderr="", timed_out=False),
            ]
            findings = await runner.run("https://github.com/test/repo.git", mkdtemp())

            assert isinstance(findings, list), f"run() should return list, got {type(findings)}"

    @pytest.mark.asyncio
    async def test_run_returns_findings_list(self) -> None:
        """Test run method returns list of Finding objects."""
        config: dict[str, Any] = {"rulesets": ["p/security-audit"]}
        runner = SemgrepRunner(config)

        mock_output = '{"results": [{"check_id": "rule1", "severity": "INFO", "message": "Test", "path": "file.py", "start": {"line": 1}}]}'

        with patch("plugins.source_scanner.scanners.semgrep_runner.run_command", new_callable=AsyncMock) as mock_run_command:
            mock_run_command.side_effect = [
                ExecResult(returncode=0, stdout="", stderr="", timed_out=False),
                ExecResult(returncode=0, stdout=mock_output, stderr="", timed_out=False),
            ]
            findings = await runner.run("https://github.com/test/repo.git", mkdtemp())

            assert all(isinstance(f, Finding) for f in findings), "All items should be Finding objects"
