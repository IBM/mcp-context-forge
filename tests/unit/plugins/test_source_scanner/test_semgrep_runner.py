#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_source_scanner/test_semgrep_runner.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Yasser
Unit tests for Semgrep runner.

Test coverage includes:
- Initialization with various configurations
- JSON output parsing (empty, single, multiple findings)
- Severity mapping (all severity levels)
- Finding object validation
"""

# Standard
from typing import Any
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from plugins.source_scanner.config import SemgrepConfig
from plugins.source_scanner.errors import ScannerError, ScannerTimeoutError
from plugins.source_scanner.models import Finding
from plugins.source_scanner.scanners.semgrep_runner import SemgrepRunner
from plugins.source_scanner.utils.exec import ExecResult


class TestSemgrepRunnerInitialization:
    """Test Semgrep runner initialization."""

    def test_init_with_default_config(self) -> None:
        """Test initialization uses defaults from SemgrepConfig."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        assert runner.enabled is True
        assert runner.rulesets == ["p/security-audit", "p/owasp-top-ten", "p/python", "p/javascript"]
        assert runner.extra_args == []

    def test_init_with_custom_config(self) -> None:
        """Test initialization with custom configuration."""
        config = SemgrepConfig(enabled=False, rulesets=["p/python", "p/security-audit"], extra_args=["--verbose", "--timeout=60"])
        runner = SemgrepRunner(config)

        assert runner.enabled is False
        assert runner.rulesets == ["p/python", "p/security-audit"]
        assert runner.extra_args == ["--verbose", "--timeout=60"]

    def test_init_stores_config_reference(self) -> None:
        """Test that runner stores reference to config."""
        config = SemgrepConfig(enabled=True)
        runner = SemgrepRunner(config)

        assert runner.config is config


class TestCommandBuilding:
    """Test Semgrep command construction."""

    def test_build_command_includes_semgrep_scan(self) -> None:
        """Test command starts with semgrep and scan."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        command = runner._build_command("/tmp/repo")

        assert command[0] == "semgrep"
        assert command[1] == "scan"

    def test_build_command_includes_json_format(self) -> None:
        """Test command includes --json output format."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        command = runner._build_command("/tmp/repo")

        assert "--json" in command

    def test_build_command_includes_repo_path(self) -> None:
        """Test command includes repository path."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        command = runner._build_command("/tmp/repo")

        assert "/tmp/repo" in command
        assert command[-1] == "/tmp/repo"  # Should be last argument

    def test_build_command_single_ruleset(self) -> None:
        """Test command with single ruleset."""
        config = SemgrepConfig(rulesets=["p/security-audit"])
        runner = SemgrepRunner(config)

        command = runner._build_command("/tmp/repo")

        assert "--config" in command
        config_idx = command.index("--config")
        assert command[config_idx + 1] == "p/security-audit"

    def test_build_command_multiple_rulesets(self) -> None:
        """Test command with multiple rulesets."""
        config = SemgrepConfig(rulesets=["p/security-audit", "p/python", "p/owasp-top-ten"])
        runner = SemgrepRunner(config)

        command = runner._build_command("/tmp/repo")

        # Count --config flags
        config_count = command.count("--config")
        assert config_count == 3

        # Check each ruleset is present
        assert "p/security-audit" in command
        assert "p/python" in command
        assert "p/owasp-top-ten" in command

    def test_build_command_includes_extra_args(self) -> None:
        """Test command includes extra arguments."""
        config = SemgrepConfig(extra_args=["--verbose", "--timeout=60", "--strict"])
        runner = SemgrepRunner(config)

        command = runner._build_command("/tmp/repo")

        assert "--verbose" in command
        assert "--timeout=60" in command
        assert "--strict" in command

    def test_build_command_empty_rulesets(self) -> None:
        """Test command with empty rulesets list."""
        config = SemgrepConfig(rulesets=[])
        runner = SemgrepRunner(config)

        command = runner._build_command("/tmp/repo")

        # Should still have semgrep, scan, json, and repo path
        assert "semgrep" in command
        assert "scan" in command
        assert "--json" in command
        assert "/tmp/repo" in command

    def test_build_command_no_extra_args(self) -> None:
        """Test command with no extra arguments."""
        config = SemgrepConfig(extra_args=[])
        runner = SemgrepRunner(config)

        command = runner._build_command("/tmp/repo")

        # Should only have expected parts, no random args
        assert "semgrep" in command
        assert "scan" in command
        assert "--json" in command

    def test_build_command_complex_repo_path(self) -> None:
        """Test command with complex repository path."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        complex_path = "/home/user/projects/my-project/src"
        command = runner._build_command(complex_path)

        assert complex_path in command
        assert command[-1] == complex_path

    def test_build_command_order(self) -> None:
        """Test that command arguments are in correct order."""
        config = SemgrepConfig(rulesets=["p/python"], extra_args=["--verbose"])
        runner = SemgrepRunner(config)

        command = runner._build_command("/tmp/repo")

        # Verify order: semgrep, scan, rulesets, extra_args, --json, repo_path
        semgrep_idx = command.index("semgrep")
        scan_idx = command.index("scan")
        json_idx = command.index("--json")
        repo_idx = command.index("/tmp/repo")

        assert semgrep_idx < scan_idx
        assert scan_idx < json_idx
        assert json_idx < repo_idx

    def test_build_command_returns_list(self) -> None:
        """Test that _build_command returns a list of strings."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        command = runner._build_command("/tmp/repo")

        assert isinstance(command, list)
        assert all(isinstance(arg, str) for arg in command)


class TestJsonOutputParsing:
    """Test JSON output parsing from Semgrep."""

    def test_parse_json_empty_results(self) -> None:
        """Test parsing empty results returns empty list."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        json_data: dict[str, Any] = {"results": []}
        findings = runner._parse_json_output(json_data)

        assert isinstance(findings, list)
        assert len(findings) == 0

    def test_parse_json_single_finding(self) -> None:
        """Test parsing single finding from output."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        json_data = {
            "results": [
                {
                    "check_id": "python.django.sql-injection",
                    "severity": "HIGH",
                    "message": "SQL injection",
                    "path": "app.py",
                    "start": {"line": 42, "col": 10},
                    "extra": {"message": "Parameterized query needed", "lines": "query = f'SELECT * FROM users'", "doc_url": "https://semgrep.dev/r/sql-injection"},
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert len(findings) == 1
        finding = findings[0]
        assert finding.scanner == "semgrep"
        assert finding.rule_id == "python.django.sql-injection"
        assert finding.severity == "ERROR"  # HIGH maps to ERROR
        assert finding.file_path == "app.py"
        assert finding.line == 42
        assert finding.column == 10

    def test_parse_json_multiple_findings(self) -> None:
        """Test parsing multiple findings."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        json_data = {
            "results": [
                {
                    "check_id": "rule.one",
                    "severity": "HIGH",
                    "message": "Issue 1",
                    "path": "file1.py",
                    "start": {"line": 10},
                },
                {
                    "check_id": "rule.two",
                    "severity": "MEDIUM",
                    "message": "Issue 2",
                    "path": "file2.py",
                    "start": {"line": 20},
                },
                {
                    "check_id": "rule.three",
                    "severity": "LOW",
                    "message": "Issue 3",
                    "path": "file3.py",
                    "start": {"line": 30},
                },
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert len(findings) == 3
        assert findings[0].rule_id == "rule.one"
        assert findings[1].rule_id == "rule.two"
        assert findings[2].rule_id == "rule.three"

    def test_parse_json_missing_optional_fields(self) -> None:
        """Test handling missing optional fields gracefully."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        json_data = {
            "results": [
                {
                    "check_id": "rule.minimal",
                    "severity": "LOW",
                    "message": "Minimal finding",
                    "path": "file.py",
                    "start": {"line": 5},
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert len(findings) == 1
        finding = findings[0]
        assert finding.column is None
        assert finding.code_snippet is None
        assert finding.help_url is None

    def test_parse_json_missing_start_line(self) -> None:
        """Test missing start.line field defaults to None."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        json_data = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "LOW",
                    "message": "Issue",
                    "path": "file.py",
                    "start": {},
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert findings[0].line is None

    def test_parse_json_empty_dict(self) -> None:
        """Test parsing empty dict returns empty findings."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        findings = runner._parse_json_output({})

        assert findings == []

    def test_parse_json_with_errors_field(self) -> None:
        """Test handling errors field in output."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        json_data = {
            "errors": [{"type": "ParseError", "message": "Some error occurred"}],
            "results": [
                {
                    "check_id": "rule",
                    "severity": "LOW",
                    "message": "Finding despite error",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ],
        }
        findings = runner._parse_json_output(json_data)

        # Should still parse results even if errors exist
        assert len(findings) == 1


class TestSeverityMapping:
    """Test severity level mapping."""

    def test_severity_error_stays_error(self) -> None:
        """Test ERROR severity stays ERROR."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        json_data = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "ERROR",
                    "message": "Error",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert findings[0].severity == "ERROR"

    def test_severity_warning_stays_warning(self) -> None:
        """Test WARNING severity stays WARNING."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        json_data = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "WARNING",
                    "message": "Warning",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert findings[0].severity == "WARNING"

    def test_severity_info_stays_info(self) -> None:
        """Test INFO severity stays INFO."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        json_data = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "INFO",
                    "message": "Info",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert findings[0].severity == "INFO"

    def test_severity_high_maps_to_error(self) -> None:
        """Test HIGH severity maps to ERROR."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        json_data = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "HIGH",
                    "message": "High",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert findings[0].severity == "ERROR"

    def test_severity_medium_maps_to_warning(self) -> None:
        """Test MEDIUM severity maps to WARNING."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        json_data = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "MEDIUM",
                    "message": "Medium",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert findings[0].severity == "WARNING"

    def test_severity_low_maps_to_info(self) -> None:
        """Test LOW severity maps to INFO."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        json_data = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "LOW",
                    "message": "Low",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert findings[0].severity == "INFO"

    def test_severity_unknown_defaults_to_info(self) -> None:
        """Test unknown severity defaults to INFO."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        json_data = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "UNKNOWN_SEVERITY",
                    "message": "Unknown",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert findings[0].severity == "INFO"

    def test_severity_case_insensitive(self) -> None:
        """Test severity mapping is case-insensitive."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        json_data = {
            "results": [
                {
                    "check_id": "rule",
                    "severity": "error",  # lowercase
                    "message": "Lowercase",
                    "path": "file.py",
                    "start": {"line": 1},
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert findings[0].severity == "ERROR"


class TestFindingObject:
    """Test Finding object validation."""

    def test_finding_has_scanner_field(self) -> None:
        """Test Finding object has semgrep as scanner."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        json_data = {
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
        findings = runner._parse_json_output(json_data)

        assert findings[0].scanner == "semgrep"

    def test_finding_has_all_attributes(self) -> None:
        """Test Finding object has all required attributes."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        json_data = {
            "results": [
                {
                    "check_id": "test.rule.id",
                    "severity": "HIGH",
                    "message": "Test message",
                    "path": "test/file.py",
                    "start": {"line": 99, "col": 42},
                    "extra": {"message": "Extra message", "lines": "code = vulnerable()", "doc_url": "https://docs.example.com"},
                }
            ]
        }
        findings = runner._parse_json_output(json_data)
        finding = findings[0]

        assert isinstance(finding, Finding)
        assert finding.scanner == "semgrep"
        assert finding.rule_id == "test.rule.id"
        assert finding.severity == "ERROR"
        assert finding.message == "Extra message"  # extra.message takes precedence
        assert finding.file_path == "test/file.py"
        assert finding.line == 99
        assert finding.column == 42


class TestRunMethod:
    """Test the async run() method."""

    @pytest.mark.asyncio
    async def test_run_returns_findings_list(self) -> None:
        """Test run method returns a list of Finding objects."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        mock_output = '{"results": [{"check_id": "rule1", "severity": "INFO", "message": "Test", "path": "file.py", "start": {"line": 1}}]}'

        with patch("plugins.source_scanner.scanners.semgrep_runner.run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = ExecResult(returncode=0, stdout=mock_output, stderr="", timed_out=False)
            findings = await runner.run("/tmp/repo", timeout_s=60)

            assert isinstance(findings, list)
            assert len(findings) == 1
            assert isinstance(findings[0], Finding)

    @pytest.mark.asyncio
    async def test_run_handles_timeout(self) -> None:
        """Test run method raises ScannerTimeoutError on timeout."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        with patch("plugins.source_scanner.scanners.semgrep_runner.run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = ExecResult(returncode=0, stdout="", stderr="", timed_out=True)

            with pytest.raises(ScannerTimeoutError):
                await runner.run("/tmp/repo", timeout_s=60)

    @pytest.mark.asyncio
    async def test_run_handles_execution_error(self) -> None:
        """Test run method raises ScannerError on execution failure."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        with patch("plugins.source_scanner.scanners.semgrep_runner.run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = ExecResult(returncode=2, stdout="", stderr="Semgrep error", timed_out=False)

            with pytest.raises(ScannerError):
                await runner.run("/tmp/repo", timeout_s=60)

    @pytest.mark.asyncio
    async def test_run_handles_invalid_json(self) -> None:
        """Test run method raises ScannerError on invalid JSON."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        with patch("plugins.source_scanner.scanners.semgrep_runner.run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = ExecResult(returncode=0, stdout="not valid json", stderr="", timed_out=False)

            with pytest.raises(ScannerError):
                await runner.run("/tmp/repo", timeout_s=60)

    @pytest.mark.asyncio
    async def test_run_accepts_exit_code_1(self) -> None:
        """Test run method accepts exit code 1 (normal when findings exist)."""
        config = SemgrepConfig()
        runner = SemgrepRunner(config)

        mock_output = '{"results": [{"check_id": "rule1", "severity": "INFO", "message": "Test", "path": "file.py", "start": {"line": 1}}]}'

        with patch("plugins.source_scanner.scanners.semgrep_runner.run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = ExecResult(returncode=1, stdout=mock_output, stderr="", timed_out=False)  # Normal exit code when findings exist
            findings = await runner.run("/tmp/repo", timeout_s=60)

            assert len(findings) == 1
