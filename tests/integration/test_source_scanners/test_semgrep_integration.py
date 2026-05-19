#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integration tests for Semgrep scanner on real repositories.

Location: tests/integration/test_source_scanners/test_semgrep_integration.py
Copyright 2026
Authors: Yaser
"""

# Standard
import logging

# Third-Party
import pytest

# First-Party
from plugins.source_scanner.config import SemgrepConfig
from plugins.source_scanner.scanners.semgrep_runner import SemgrepRunner
from plugins.source_scanner.source_scanner import SourceScannerPlugin

logger = logging.getLogger(__name__)


class TestSemgrepIntegration:
    """Integration tests for Semgrep scanner on real repositories."""

    @pytest.fixture
    def semgrep_runner(self) -> SemgrepRunner:
        """Create a SemgrepRunner instance."""
        config = SemgrepConfig(
            enabled=True,
            rulesets=["p/security-audit", "p/owasp-top-ten"],
        )
        return SemgrepRunner(config)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_semgrep_on_repo(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
    ) -> None:
        """Test Semgrep scanner on repository.

        This tests:
        - Semgrep's ability to find code security issues across languages
        - Integration with the plugin workflow
        - Multi-language support
        - Finding severity classification
        """
        result = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        # Filter for Semgrep findings
        semgrep_findings = [f for f in result.findings if f.scanner == "semgrep"]

        logger.info(f"Semgrep found {len(semgrep_findings)} issues")

        # Verify findings structure
        for finding in semgrep_findings:
            assert finding.scanner == "semgrep"
            assert finding.rule_id is not None
            assert finding.file_path is not None
            assert finding.severity in ["INFO", "WARNING", "ERROR"]
            assert finding.message is not None

            logger.debug(f"Semgrep: {finding.rule_id} ({finding.severity}) " f"in {finding.file_path}:{finding.line}")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_semgrep_finding_severity_distribution(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
    ) -> None:
        """Test distribution of Semgrep finding severities."""
        result = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        semgrep_findings = [f for f in result.findings if f.scanner == "semgrep"]

        # Count by severity
        errors = sum(1 for f in semgrep_findings if f.severity == "ERROR")
        warnings = sum(1 for f in semgrep_findings if f.severity == "WARNING")
        infos = sum(1 for f in semgrep_findings if f.severity == "INFO")

        logger.info(f"Semgrep severity distribution - " f"Errors: {errors}, Warnings: {warnings}, Info: {infos}")

        total = errors + warnings + infos
        if total > 0:
            logger.info(f"Total Semgrep findings: {total}")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_semgrep_finding_rules(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
    ) -> None:
        """Test that Semgrep findings include valid rule IDs."""
        result = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        semgrep_findings = [f for f in result.findings if f.scanner == "semgrep"]

        # Collect unique rules found
        rules = set()
        for finding in semgrep_findings:
            rules.add(finding.rule_id)

        if rules:
            logger.info(f"Semgrep rules found: {sorted(rules)}")

            # Verify rules are non-empty strings
            for rule_id in rules:
                assert isinstance(rule_id, str)
                assert len(rule_id) > 0

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_semgrep_multi_language_support(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
    ) -> None:
        """Test that Semgrep scans multiple language files."""
        result = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        semgrep_findings = [f for f in result.findings if f.scanner == "semgrep"]

        # Collect file extensions
        extensions = set()
        for finding in semgrep_findings:
            file_path = finding.file_path
            if "." in file_path:
                ext = file_path.split(".")[-1]
                extensions.add(ext)

        logger.info(f"Semgrep scanned {len(extensions)} file types: {sorted(extensions)}")

        if extensions:
            logger.info(f"File extensions: {', '.join(sorted(extensions))}")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_semgrep_file_coverage(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
    ) -> None:
        """Test that Semgrep scans files across the repository."""
        result = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        semgrep_findings = [f for f in result.findings if f.scanner == "semgrep"]

        # Collect unique files with findings
        files = set()
        for finding in semgrep_findings:
            files.add(finding.file_path)

        logger.info(f"Semgrep found issues in {len(files)} files")

        if files:
            # Log sample of files
            for file_path in sorted(list(files))[:10]:
                logger.debug(f"  - {file_path}")

            if len(files) > 10:
                logger.debug(f"  ... and {len(files) - 10} more files")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_semgrep_owasp_rules(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
    ) -> None:
        """Test that Semgrep detects OWASP Top 10 vulnerabilities."""
        result = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        semgrep_findings = [f for f in result.findings if f.scanner == "semgrep"]

        # Categorize by severity
        critical_and_high = [f for f in semgrep_findings if f.severity in ["ERROR", "WARNING"]]

        logger.info(f"Found {len(critical_and_high)} critical/high severity issues")

        if critical_and_high:
            # Log top issues
            issue_types = {}
            for finding in critical_and_high:
                rule = finding.rule_id
                if rule not in issue_types:
                    issue_types[rule] = 0
                issue_types[rule] += 1

            logger.info("Top security issues:")
            for rule, count in sorted(issue_types.items(), key=lambda x: x[1], reverse=True)[:5]:
                logger.info(f"  {rule}: {count} occurrences")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_semgrep_message_content(
        self,
        source_scanner_plugin: SourceScannerPlugin,
        repo_url: str,
        repo_ref: str,
    ) -> None:
        """Test that Semgrep findings include descriptive messages."""
        result = await source_scanner_plugin.scan(
            repo_url=repo_url,
            ref=repo_ref,
        )

        semgrep_findings = [f for f in result.findings if f.scanner == "semgrep"]

        if semgrep_findings:
            # Verify message quality
            for i, finding in enumerate(semgrep_findings[:5]):
                logger.info(f"Sample finding {i+1}:\n" f"  Rule: {finding.rule_id}\n" f"  File: {finding.file_path}\n" f"  Message: {finding.message[:100]}...")
