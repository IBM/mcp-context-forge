#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Location: tests/unit/plugins/test_source_scanner/test_test_scanner.py
Copyright: 2026
Authors: Yasser
Unit tests for the test_scanner.py helper script
"""

# Standard
import logging
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from plugins.source_scanner.models import Finding, ScanResult, ScanSummary


@pytest.fixture
def sample_scan_result() -> ScanResult:
    """Create a sample ScanResult for testing."""
    return ScanResult(
        repo_url="https://github.com/example/repo",
        ref="main",
        commit_sha="abc123",
        languages=["Python"],
        findings=[
            Finding(
                scanner="semgrep",
                severity="ERROR",
                rule_id="rule-001",
                message="SQL Injection",
                file_path="src/db.py",
                line=42,
            ),
            Finding(
                scanner="bandit",
                severity="WARNING",
                rule_id="B607",
                message="Partial path",
                file_path="src/utils.py",
                line=15,
            ),
        ],
        summary=ScanSummary(error_count=1, warning_count=1, info_count=0),
        blocked=False,
    )


class TestCleanFormatter:
    """Test CleanFormatter logging formatter."""

    def test_info_formatting(self) -> None:
        """Test INFO level formatting."""
        # First-Party
        from plugins.source_scanner.test_scanner import CleanFormatter

        formatter = CleanFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test",
            args=(),
            exc_info=None,
        )
        assert formatter.format(record) == "Test"

    def test_error_formatting(self) -> None:
        """Test ERROR level formatting."""
        # First-Party
        from plugins.source_scanner.test_scanner import CleanFormatter

        formatter = CleanFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Error",
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        assert "ERROR:" in result


class TestTestRepository:
    """Test test_repository function."""

    @pytest.mark.asyncio
    async def test_success(self, sample_scan_result: ScanResult) -> None:
        """Test successful scan."""
        # First-Party
        from plugins.source_scanner.test_scanner import test_repository

        with patch("plugins.source_scanner.test_scanner.SourceScannerPlugin") as mock_cls:
            mock_plugin = AsyncMock()
            mock_plugin.scan.return_value = sample_scan_result
            mock_cls.return_value = mock_plugin

            with pytest.raises(SystemExit) as exc:
                await test_repository("https://github.com/example/repo")

            # Success exits with code 0
            assert exc.value.code == 0
            # Verify scanner was called with correct URL
            mock_plugin.scan.assert_called_once()

    @pytest.mark.asyncio
    async def test_error(self) -> None:
        """Test scan error."""
        # First-Party
        from plugins.source_scanner.test_scanner import test_repository

        with patch("plugins.source_scanner.test_scanner.SourceScannerPlugin") as mock_cls:
            mock_plugin = AsyncMock()
            mock_plugin.scan.side_effect = Exception("Network error")
            mock_cls.return_value = mock_plugin

            with pytest.raises(SystemExit) as exc:
                await test_repository("https://github.com/example/repo")

            # Error exits with code 1
            assert exc.value.code == 1


class TestMainFunction:
    """Test main function."""

    def test_with_repo(self) -> None:
        """Test main with repo argument."""
        with patch(
            "sys.argv",
            ["test_scanner.py", "--repo", "https://github.com/test/repo"],
        ):
            with patch("asyncio.run"):
                # First-Party
                from plugins.source_scanner.test_scanner import main

                main()  # Should not raise

    def test_without_repo(self) -> None:
        """Test main without repo argument."""
        with patch("sys.argv", ["test_scanner.py"]):
            # First-Party
            from plugins.source_scanner.test_scanner import main

            with pytest.raises(SystemExit):
                main()
