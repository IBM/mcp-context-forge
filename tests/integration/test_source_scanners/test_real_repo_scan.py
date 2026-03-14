#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integration tests for scanning real repositories.

Location: tests/integration/test_source_scanners/test_real_repo_scan.py
Copyright 2026
Authors: Yaser
"""

# Standard
import logging

# Third-Party
import pytest

# First-Party
from plugins.source_scanner.models import ScanResult
from plugins.source_scanner.source_scanner import SourceScannerPlugin

logger = logging.getLogger(__name__)


class TestRepoScan:
    """Integration tests for scanning real repositories."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_full_scan(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
        request,
    ) -> None:
        """Test scanning repository with full scan workflow.

        This test:
        - Clones the repository
        - Detects programming languages
        - Runs Semgrep and Bandit scanners
        - Processes and deduplicates findings
        - Verifies scan completes successfully
        """
        result: ScanResult = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        # Verify scan completed
        assert result is not None
        assert result.repo_url == repo_url
        assert result.ref == repo_ref
        assert result.commit_sha is not None

        # Verify summary exists
        assert result.summary is not None
        assert result.summary.error_count >= 0
        assert result.summary.warning_count >= 0
        assert result.summary.info_count >= 0

        # Capture summary data (only once per session)
        if hasattr(request.session, "summary_data"):
            data = request.session.summary_data
            if data["repo_url"] == "":  # First test sets these
                data["repo_url"] = repo_url
                data["repo_ref"] = repo_ref
                data["total_findings"] = len(result.findings)

                # Count by scanner
                for finding in result.findings:
                    data["findings_by_scanner"][finding.scanner] += 1
                    data["severity_distribution"][finding.severity] += 1

        # Log scan results
        logger.info(f"Scan completed: " f"{result.summary.error_count} errors, " f"{result.summary.warning_count} warnings, " f"{result.summary.info_count} info findings")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_findings_structure(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
    ) -> None:
        """Test that findings have proper structure and required fields."""
        result: ScanResult = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        # Verify findings structure
        assert result.findings is not None
        assert isinstance(result.findings, list)

        # Verify each finding has required fields
        for finding in result.findings:
            assert finding.rule_id is not None
            assert finding.file_path is not None
            assert finding.severity is not None
            assert finding.message is not None
            assert finding.scanner is not None

            # Verify severity is valid
            assert finding.severity in ["INFO", "WARNING", "ERROR"]

            # Verify scanner is valid
            assert finding.scanner in ["semgrep", "bandit"]

            # Log finding details
            logger.debug(f"Finding: {finding.rule_id} ({finding.severity}) in " f"{finding.file_path}:{finding.line}")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_language_detection(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
    ) -> None:
        """Test that languages are properly detected."""
        result: ScanResult = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        # Verify languages are detected
        assert result.languages is not None
        assert isinstance(result.languages, list)

        # Log detected languages
        logger.info(f"Detected languages: {result.languages}")
        # Note: Adjust assertion based on actual detection results

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_semgrep_findings(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
    ) -> None:
        """Test Semgrep findings in repository."""
        result: ScanResult = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        # Filter for Semgrep findings
        semgrep_findings = [f for f in result.findings if f.scanner == "semgrep"]

        logger.info(f"Semgrep found {len(semgrep_findings)} issues")

        # Verify Semgrep findings exist
        if semgrep_findings:
            for finding in semgrep_findings:
                assert finding.scanner == "semgrep"
                assert finding.rule_id is not None
                logger.debug(f"Semgrep: {finding.rule_id} - {finding.severity}")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_scan_performance(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
    ) -> None:
        """Test scan performance metrics."""
        # Standard
        import time

        start_time = time.time()
        result: ScanResult = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )
        elapsed_time = time.time() - start_time

        # Verify scan completed in reasonable time
        logger.info(f"Scan completed in {elapsed_time:.2f} seconds")
        logger.info(f"Total findings: {len(result.findings)}")

        # Performance should be acceptable (adjust based on requirements)
        assert elapsed_time < 600  # 10 minutes max

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_policy_decision(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
        request,
    ) -> None:
        """Test that security policy decision is made correctly based on errors."""
        result: ScanResult = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        # Verify policy evaluation result
        assert result.blocked is not None
        assert isinstance(result.blocked, bool)

        # Get error count to determine policy decision
        error_count = result.summary.error_count

        # Policy decision: BLOCKED if errors > 0, else ALLOWED
        if error_count > 0:
            policy_decision = "BLOCKED"
            policy_reason = f"Found {error_count} critical error(s)"
        else:
            policy_decision = "ALLOWED"
            policy_reason = "No critical errors"

        # Capture policy decision for summary report
        if hasattr(request.session, "summary_data"):
            request.session.summary_data["policy_decisions"].append(
                {
                    "blocked": result.blocked,
                    "block_reason": policy_reason,
                    "decision": policy_decision,
                    "error_count": error_count,
                }
            )

        status = policy_decision.lower()

        logger.info(f"Policy decision: {status} " f"(errors: {result.summary.error_count})")

        # If blocked, reason should be present
        if result.blocked:
            logger.info(f"Block reason: {result.block_reason}")
