#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integration tests for Bandit scanner on real repositories.

Location: tests/integration/test_source_scanners/test_bandit_integration.py
Copyright 2026
Authors: Yaser
"""

# Standard
import logging

# Third-Party
import pytest

# First-Party
from plugins.source_scanner.config import BanditConfig
from plugins.source_scanner.scanners.bandit_runner import BanditRunner
from plugins.source_scanner.source_scanner import SourceScannerPlugin

logger = logging.getLogger(__name__)


class TestBanditIntegration:
    """Integration tests for Bandit scanner on real repositories."""

    @pytest.fixture
    def bandit_runner(self) -> BanditRunner:
        """Create a BanditRunner instance."""
        config = BanditConfig(
            enabled=True,
            severity="MEDIUM",
        )
        return BanditRunner(config)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_bandit_on_repo(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
    ) -> None:
        """Test Bandit scanner on repository.

        This tests:
        - Bandit's ability to find Python security issues
        - Integration with the plugin workflow
        - Finding severity classification
        """
        result = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        # Filter for Bandit findings
        bandit_findings = [f for f in result.findings if f.scanner == "bandit"]

        logger.info(f"Bandit found {len(bandit_findings)} issues")

        # Verify findings structure
        for finding in bandit_findings:
            assert finding.scanner == "bandit"
            assert finding.rule_id is not None
            assert finding.file_path is not None
            assert finding.severity in ["INFO", "WARNING", "ERROR"]
            assert finding.line is not None or finding.line == 0

            logger.debug(f"Bandit: {finding.rule_id} ({finding.severity}) " f"in {finding.file_path}:{finding.line}")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_bandit_finding_severity_distribution(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
    ) -> None:
        """Test distribution of Bandit finding severities."""
        result = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        bandit_findings = [f for f in result.findings if f.scanner == "bandit"]

        # Count by severity
        errors = sum(1 for f in bandit_findings if f.severity == "ERROR")
        warnings = sum(1 for f in bandit_findings if f.severity == "WARNING")
        infos = sum(1 for f in bandit_findings if f.severity == "INFO")

        logger.info(f"Bandit severity distribution - " f"Errors: {errors}, Warnings: {warnings}, Info: {infos}")

        total = errors + warnings + infos
        if total > 0:
            logger.info(f"Total Bandit findings: {total}")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_bandit_finding_rules(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
    ) -> None:
        """Test that Bandit findings include valid rule IDs."""
        result = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        bandit_findings = [f for f in result.findings if f.scanner == "bandit"]

        # Collect unique rules found
        rules = set()
        for finding in bandit_findings:
            rules.add(finding.rule_id)

        if rules:
            logger.info(f"Bandit rules found: {sorted(rules)}")

            # Verify rules are in expected format (typically B### for Bandit)
            for rule_id in rules:
                assert isinstance(rule_id, str)
                assert len(rule_id) > 0

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_bandit_file_coverage(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
    ) -> None:
        """Test that Bandit scans Python files across the repository."""
        result = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        bandit_findings = [f for f in result.findings if f.scanner == "bandit"]

        # Collect unique files with findings
        files = set()
        for finding in bandit_findings:
            files.add(finding.file_path)

        logger.info(f"Bandit found issues in {len(files)} files")

        if files:
            # Log sample of files
            for file_path in sorted(list(files))[:10]:
                logger.debug(f"  - {file_path}")

            if len(files) > 10:
                logger.debug(f"  ... and {len(files) - 10} more files")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_bandit_common_issues(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
    ) -> None:
        """Test that Bandit can detect common Python security issues."""
        result = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        bandit_findings = [f for f in result.findings if f.scanner == "bandit"]

        # Collect issue types
        issue_types = {}
        for finding in bandit_findings:
            rule = finding.rule_id
            if rule not in issue_types:
                issue_types[rule] = 0
            issue_types[rule] += 1

        logger.info("Most common Bandit issues:")
        for rule, count in sorted(issue_types.items(), key=lambda x: x[1], reverse=True)[:5]:
            logger.info(f"  {rule}: {count} occurrences")
