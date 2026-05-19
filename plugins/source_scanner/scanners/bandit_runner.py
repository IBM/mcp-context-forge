#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bandit scanner runner for Source Scanner.

Location: ./plugins/source_scanner/scanners/bandit_runner.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn Gavin

This module implements Bandit CLI integration for Python static security analysis.
Parses JSON output into normalized Finding objects.
"""

# Standard
import json
import logging
import os
from typing import Any

# Local
from ..config import BanditConfig
from ..errors import ScannerError, ScannerTimeoutError
from ..models import Finding, Severity
from ..utils.exec import run_command

logger = logging.getLogger(__name__)


class BanditRunner:
    """Runs Bandit scans on Python code."""

    def __init__(self, config: BanditConfig):
        """Initialize Bandit runner from configuration."""
        self.config = config
        self.enabled = config.enabled  # ← Fixed: Pydantic field access
        self.severity = config.severity
        self.confidence = config.confidence

    async def run(self, repo_path: str, timeout_s: int) -> list[Finding]:
        """Run Bandit against Python files in repository.

        Args:
            repo_path: Path to the repository being scanned.
            timeout_s: Timeout in seconds for the scan.

        Returns:
            List of findings produced by Bandit.

        Raises:
            ScannerTimeoutError: If scan exceeds timeout.
            ScannerError: If scan fails.
        """
        logger.info(f"Running Bandit on {repo_path}")

        # Build and run bandit command
        command = self._build_command(repo_path)
        result = await run_command(command, cwd=None, env=os.environ.copy(), timeout_seconds=timeout_s)

        # Check for timeout
        if result.timed_out:
            raise ScannerTimeoutError(f"Bandit scan exceeded {timeout_s}s timeout")

        # Bandit returns exit code 1 when issues are found — that's normal
        if result.returncode not in (0, 1):
            raise ScannerError(f"Bandit failed (code {result.returncode}): {result.stderr}")

        # Parse JSON output
        try:
            data: dict[str, Any] = json.loads(result.stdout) if result.stdout else {}
        except json.JSONDecodeError as e:
            raise ScannerError(f"Failed to parse Bandit output: {e}")

        findings = self._parse_json_output(data)

        # Log results
        if not findings:
            logger.info("Bandit: No findings detected")
        else:
            logger.info(f"Bandit: Found {len(findings)} issue(s)")
            for f in findings:
                logger.debug(f"  [{f.severity}] {f.rule_id} at {f.file_path}:{f.line}")

        return findings

    def _build_command(self, repo_path: str) -> list[str]:
        """Build bandit command with configured arguments."""
        command = ["bandit", "-r", repo_path, "-f", "json"]

        # Add severity filter
        # command.extend(["-l", self.severity.upper()])

        # Add confidence filter
        # command.extend(["-i", self.confidence.upper()])

        logger.debug(f"Bandit command: {' '.join(command)}")
        return command

    def _parse_json_output(self, bandit_data: dict[str, Any]) -> list[Finding]:
        """Parse Bandit JSON output into Finding objects."""
        findings: list[Finding] = []

        # Handle empty or error case
        if not bandit_data:
            return findings

        if "errors" in bandit_data and bandit_data["errors"]:
            logger.warning(f"Bandit returned errors: {bandit_data['errors']}")
            # Continue parsing results if they exist

        results = bandit_data.get("results", [])

        for result in results:
            finding = Finding(
                scanner="bandit",
                severity=_map_severity(result.get("issue_severity", "LOW")),
                rule_id=result.get("test_id", "unknown"),
                message=result.get("issue_text", "No description provided"),
                file_path=result.get("filename"),
                line=result.get("line_number"),
                column=result.get("col_offset"),
                code_snippet=result.get("code", "").strip() or None,
                help_url=result.get("more_info"),
            )
            findings.append(finding)

        return findings


def _map_severity(bandit_severity: str) -> Severity:
    """Map Bandit severity to normalized severity level."""
    severity_map: dict[str, Severity] = {
        "HIGH": "ERROR",
        "MEDIUM": "WARNING",
        "LOW": "INFO",
    }
    return severity_map.get(bandit_severity.upper(), "INFO")
