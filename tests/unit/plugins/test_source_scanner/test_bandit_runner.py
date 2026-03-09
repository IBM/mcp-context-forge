#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_source_scanner/test_bandit_runner.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Yaser
Unit tests for Bandit scanner runner.

Test coverage includes:
- Initialization with various configurations
- JSON output parsing
- Severity mapping
- Finding object validation
"""

# Standard
from typing import Any
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from plugins.source_scanner.config import BanditConfig
from plugins.source_scanner.errors import ScannerError, ScannerTimeoutError
from plugins.source_scanner.models import Finding
from plugins.source_scanner.scanners.bandit_runner import BanditRunner
from plugins.source_scanner.utils.exec import ExecResult


class TestBanditRunnerInitialization:
    """Test Bandit runner initialization."""

    def test_init_with_default_config(self) -> None:
        """Test initialization uses defaults from BanditConfig."""
        config = BanditConfig()
        runner = BanditRunner(config)

        assert runner.enabled is True
        assert runner.severity == "medium"
        assert runner.confidence == "medium"

    def test_init_with_custom_config(self) -> None:
        """Test initialization with custom configuration."""
        config = BanditConfig(enabled=False, severity="high", confidence="low")
        runner = BanditRunner(config)

        assert runner.enabled is False
        assert runner.severity == "high"
        assert runner.confidence == "low"

    def test_init_stores_config_reference(self) -> None:
        """Test that runner stores reference to config."""
        config = BanditConfig(enabled=True)
        runner = BanditRunner(config)

        assert runner.config is config


class TestJsonOutputParsing:
    """Test JSON output parsing from Bandit."""

    def test_parse_json_empty_results(self) -> None:
        """Test parsing empty results returns empty list."""
        config = BanditConfig()
        runner = BanditRunner(config)

        json_data: dict[str, Any] = {"results": []}
        findings = runner._parse_json_output(json_data)

        assert isinstance(findings, list)
        assert len(findings) == 0

    def test_parse_json_empty_dict(self) -> None:
        """Test parsing empty dict returns empty findings."""
        config = BanditConfig()
        runner = BanditRunner(config)

        findings = runner._parse_json_output({})

        assert findings == []

    def test_parse_json_single_finding(self) -> None:
        """Test parsing single finding from output."""
        config = BanditConfig()
        runner = BanditRunner(config)

        json_data = {
            "results": [
                {
                    "test_id": "B201",
                    "test_name": "flask_debug_true",
                    "issue_severity": "HIGH",
                    "issue_confidence": "MEDIUM",
                    "issue_text": "Flask debug mode is on",
                    "filename": "app.py",
                    "line_number": 10,
                    "col_offset": 5,
                    "code": "app.run(debug=True)",
                    "more_info": "https://bandit.readthedocs.io/en/latest/b201_flask_debug.html",
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert len(findings) == 1
        finding = findings[0]
        assert finding.scanner == "bandit"
        assert finding.rule_id == "B201"
        assert finding.severity == "ERROR"  # HIGH maps to ERROR
        assert finding.message == "Flask debug mode is on"
        assert finding.file_path == "app.py"
        assert finding.line == 10
        assert finding.column == 5

    def test_parse_json_multiple_findings(self) -> None:
        """Test parsing multiple findings."""
        config = BanditConfig()
        runner = BanditRunner(config)

        json_data = {
            "results": [
                {
                    "test_id": "B201",
                    "issue_severity": "HIGH",
                    "issue_text": "Issue 1",
                    "filename": "file1.py",
                    "line_number": 10,
                },
                {
                    "test_id": "B301",
                    "issue_severity": "MEDIUM",
                    "issue_text": "Issue 2",
                    "filename": "file2.py",
                    "line_number": 20,
                },
                {
                    "test_id": "B401",
                    "issue_severity": "LOW",
                    "issue_text": "Issue 3",
                    "filename": "file3.py",
                    "line_number": 30,
                },
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert len(findings) == 3
        assert findings[0].rule_id == "B201"
        assert findings[1].rule_id == "B301"
        assert findings[2].rule_id == "B401"

    def test_parse_json_missing_optional_fields(self) -> None:
        """Test handling missing optional fields gracefully."""
        config = BanditConfig()
        runner = BanditRunner(config)

        json_data = {
            "results": [
                {
                    "test_id": "B101",
                    "issue_severity": "LOW",
                    "issue_text": "Assert detected",
                    "filename": "tests.py",
                    "line_number": 42,
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert len(findings) == 1
        finding = findings[0]
        assert finding.column is None
        assert finding.code_snippet is None
        assert finding.help_url is None

    def test_parse_json_with_errors_field(self) -> None:
        """Test handling errors field in output."""
        config = BanditConfig()
        runner = BanditRunner(config)

        json_data = {
            "errors": ["Some error occurred"],
            "results": [
                {
                    "test_id": "B201",
                    "issue_severity": "HIGH",
                    "issue_text": "Finding despite error",
                    "filename": "file.py",
                    "line_number": 1,
                }
            ],
        }
        findings = runner._parse_json_output(json_data)

        # Should still parse results even if errors exist
        assert len(findings) == 1


class TestSeverityMapping:
    """Test severity level mapping."""

    def test_severity_high_maps_to_error(self) -> None:
        """Test HIGH severity maps to ERROR."""
        config = BanditConfig()
        runner = BanditRunner(config)

        json_data = {
            "results": [
                {
                    "test_id": "B201",
                    "issue_severity": "HIGH",
                    "issue_text": "High severity issue",
                    "filename": "app.py",
                    "line_number": 1,
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert findings[0].severity == "ERROR"

    def test_severity_medium_maps_to_warning(self) -> None:
        """Test MEDIUM severity maps to WARNING."""
        config = BanditConfig()
        runner = BanditRunner(config)

        json_data = {
            "results": [
                {
                    "test_id": "B301",
                    "issue_severity": "MEDIUM",
                    "issue_text": "Medium severity issue",
                    "filename": "app.py",
                    "line_number": 1,
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert findings[0].severity == "WARNING"

    def test_severity_low_maps_to_info(self) -> None:
        """Test LOW severity maps to INFO."""
        config = BanditConfig()
        runner = BanditRunner(config)

        json_data = {
            "results": [
                {
                    "test_id": "B401",
                    "issue_severity": "LOW",
                    "issue_text": "Low severity issue",
                    "filename": "app.py",
                    "line_number": 1,
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert findings[0].severity == "INFO"

    def test_severity_unknown_defaults_to_info(self) -> None:
        """Test unknown severity defaults to INFO."""
        config = BanditConfig()
        runner = BanditRunner(config)

        json_data = {
            "results": [
                {
                    "test_id": "B999",
                    "issue_severity": "UNKNOWN_SEVERITY",
                    "issue_text": "Unknown severity",
                    "filename": "app.py",
                    "line_number": 1,
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert findings[0].severity == "INFO"

    def test_severity_case_insensitive(self) -> None:
        """Test severity mapping is case-insensitive."""
        config = BanditConfig()
        runner = BanditRunner(config)

        json_data = {
            "results": [
                {
                    "test_id": "B201",
                    "issue_severity": "high",  # lowercase
                    "issue_text": "High severity",
                    "filename": "app.py",
                    "line_number": 1,
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert findings[0].severity == "ERROR"


class TestFindingObject:
    """Test Finding object validation."""

    def test_finding_has_scanner_field(self) -> None:
        """Test Finding object has bandit as scanner."""
        config = BanditConfig()
        runner = BanditRunner(config)

        json_data = {
            "results": [
                {
                    "test_id": "B201",
                    "issue_severity": "LOW",
                    "issue_text": "Test",
                    "filename": "file.py",
                    "line_number": 1,
                }
            ]
        }
        findings = runner._parse_json_output(json_data)

        assert findings[0].scanner == "bandit"

    def test_finding_has_all_attributes(self) -> None:
        """Test Finding object has all required attributes."""
        config = BanditConfig()
        runner = BanditRunner(config)

        json_data = {
            "results": [
                {
                    "test_id": "B201",
                    "test_name": "flask_debug_true",
                    "issue_severity": "HIGH",
                    "issue_confidence": "MEDIUM",
                    "issue_text": "Flask debug is on",
                    "filename": "src/app.py",
                    "line_number": 25,
                    "col_offset": 10,
                    "code": "app.run(debug=True)",
                    "more_info": "https://bandit.readthedocs.io",
                }
            ]
        }
        findings = runner._parse_json_output(json_data)
        finding = findings[0]

        assert isinstance(finding, Finding)
        assert finding.scanner == "bandit"
        assert finding.rule_id == "B201"
        assert finding.severity == "ERROR"
        assert finding.message == "Flask debug is on"
        assert finding.file_path == "src/app.py"
        assert finding.line == 25
        assert finding.column == 10


class TestRunMethod:
    """Test the async run() method."""

    @pytest.mark.asyncio
    async def test_run_returns_findings_list(self) -> None:
        """Test run method returns a list of Finding objects."""
        config = BanditConfig()
        runner = BanditRunner(config)

        mock_output = '{"results": [{"test_id": "B201", "issue_severity": "HIGH", "issue_text": "Test", "filename": "file.py", "line_number": 1}]}'

        with patch("plugins.source_scanner.scanners.bandit_runner.run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = ExecResult(returncode=0, stdout=mock_output, stderr="", timed_out=False)
            findings = await runner.run("/tmp/repo", timeout_s=60)

            assert isinstance(findings, list)
            assert len(findings) == 1
            assert isinstance(findings[0], Finding)

    @pytest.mark.asyncio
    async def test_run_handles_timeout(self) -> None:
        """Test run method raises ScannerTimeoutError on timeout."""
        config = BanditConfig()
        runner = BanditRunner(config)

        with patch("plugins.source_scanner.scanners.bandit_runner.run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = ExecResult(returncode=0, stdout="", stderr="", timed_out=True)

            with pytest.raises(ScannerTimeoutError):
                await runner.run("/tmp/repo", timeout_s=60)

    @pytest.mark.asyncio
    async def test_run_handles_execution_error(self) -> None:
        """Test run method raises ScannerError on execution failure."""
        config = BanditConfig()
        runner = BanditRunner(config)

        with patch("plugins.source_scanner.scanners.bandit_runner.run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = ExecResult(returncode=2, stdout="", stderr="Bandit error", timed_out=False)

            with pytest.raises(ScannerError):
                await runner.run("/tmp/repo", timeout_s=60)

    @pytest.mark.asyncio
    async def test_run_handles_invalid_json(self) -> None:
        """Test run method raises ScannerError on invalid JSON."""
        config = BanditConfig()
        runner = BanditRunner(config)

        with patch("plugins.source_scanner.scanners.bandit_runner.run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = ExecResult(returncode=0, stdout="not valid json", stderr="", timed_out=False)

            with pytest.raises(ScannerError):
                await runner.run("/tmp/repo", timeout_s=60)

    @pytest.mark.asyncio
    async def test_run_accepts_exit_code_1(self) -> None:
        """Test run method accepts exit code 1 (normal when findings exist)."""
        config = BanditConfig()
        runner = BanditRunner(config)

        mock_output = '{"results": [{"test_id": "B201", "issue_severity": "HIGH", "issue_text": "Test", "filename": "file.py", "line_number": 1}]}'

        with patch("plugins.source_scanner.scanners.bandit_runner.run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = ExecResult(returncode=1, stdout=mock_output, stderr="", timed_out=False)  # Normal exit code when findings exist
            findings = await runner.run("/tmp/repo", timeout_s=60)

            assert len(findings) == 1
