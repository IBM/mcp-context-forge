#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Semgrep scanner runner for Source Scanner.

Location: ./plugins/source_scanner/scanners/semgrep_runner.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha, Ayo

This module implements Semgrep CLI integration for static code analysis.
Parses Semgrep JSON output into normalized Finding objects.
"""

# Standard
import json
import logging
import os
from typing import Any

# Local
from ..config import SemgrepConfig
from ..errors import ScannerError, ScannerTimeoutError
from ..models import Finding, Severity
from ..utils.exec import run_command

logger = logging.getLogger(__name__)


class SemgrepRunner:
    """Runs Semgrep scans and parses results into Finding objects."""

    def __init__(self, config: SemgrepConfig):
        """Initialize the Semgrep runner from configuration."""
        self.config = config
        self.enabled = config.enabled
        self.rulesets = config.rulesets
        self.extra_args = config.extra_args

    async def run(self, repo_path: str, timeout_s: int) -> list[Finding]:
        """Run Semgrep against the checked-out repository.

        Args:
            repo_path: Path to the repository being scanned.
            timeout_s: Timeout in seconds for the scan.

        Returns:
            List of findings produced by Semgrep.

        Raises:
            ScannerTimeoutError: If scan exceeds timeout.
            ScannerError: If scan fails.
        """
        logger.info(f"Running Semgrep on {repo_path}")

        # Build and run semgrep command
        command = self._build_command(repo_path)
        result = await run_command(command, cwd=None, env=os.environ.copy(), timeout_seconds=timeout_s)

        # Check for timeout
        if result.timed_out:
            raise ScannerTimeoutError(f"Semgrep scan exceeded {timeout_s}s timeout")

        # Parse output even if semgrep finds issues (return code 1 is normal)
        if result.returncode not in (0, 1):
            raise ScannerError(f"Semgrep failed (code {result.returncode}): {result.stderr}")

        # Parse JSON output
        try:
            data: dict[str, Any] = json.loads(result.stdout) if result.stdout else {}
        except json.JSONDecodeError as e:
            raise ScannerError(f"Failed to parse Semgrep output: {e}")

        findings = self._parse_json_output(data)

        # Log results
        if not findings:
            logger.info("Semgrep: No findings detected")
        else:
            logger.info(f"Semgrep: Found {len(findings)} issue(s)")
            for f in findings:
                logger.debug(f"  [{f.severity}] {f.rule_id} at {f.file_path}:{f.line}")

        return findings

    def _build_command(self, repo_path: str) -> list[str]:
        """Build semgrep command with configured rulesets and arguments."""
        command = ["semgrep", "scan"]

        # Add configured rulesets
        for ruleset in self.rulesets:
            command.extend(["--config", ruleset])

        # Add extra arguments
        command.extend(self.extra_args)

        # Add output format (JSON)
        command.append("--json")

        # Add target repository path
        command.append(repo_path)

        logger.debug(f"Semgrep command: {' '.join(command)}")
        return command

    def _parse_json_output(self, json_data: dict[str, Any]) -> list[Finding]:
        """Parse Semgrep JSON output into Finding objects."""
        findings: list[Finding] = []

        if "errors" in json_data and json_data["errors"]:
            errors = json_data["errors"]
            error_count = len(errors)

            error_types: dict[str, int] = {}
            for error in errors:
                error_type: str = error.get("type", "Unknown")
                if isinstance(error_type, list):
                    error_type = error_type[0] if error_type else "Unknown"
                error_types[error_type] = error_types.get(error_type, 0) + 1
            logger.warning(f"Semgrep reported {error_count} non-critical errors:")
            for error_type, count in error_types.items():
                logger.warning(f"  - {error_type}: {count}")

            # Only log details at DEBUG level
            for i, error in enumerate(errors[:3]):
                logger.debug(f"Error {i+1}: {error.get('message', 'No message')[:100]}")

        # if "error" in json_data or "errors" in json_data:
        # logger.warning(f"Semgrep returned errors: {json_data.get('errors', json_data.get('error'))}")

        results = json_data.get("results", [])

        for result in results:
            # Extract message
            message = result.get("extra", {}).get("message") or result.get("message") or f"{result.get('check_id', 'unknown')} detected"

            # Try multiple fields for severity
            severity_value = result.get("extra", {}).get("severity") or result.get("severity") or "INFO"

            # Map certain rule patterns to ERROR
            rule_id = result.get("check_id", "unknown")
            if any(pattern in rule_id.lower() for pattern in ["sqli", "sql-injection", "command-injection", "hardcoded-secret", "hardcoded-password", "unsafe-deserialization", "xxe"]):
                severity = "ERROR"  # Force critical issues to ERROR
            else:
                severity = _map_severity(severity_value)

            finding = Finding(
                scanner="semgrep",
                severity=severity,
                rule_id=rule_id,
                message=message,
                file_path=result.get("path"),
                line=result.get("start", {}).get("line"),
                column=result.get("start", {}).get("col"),
                code_snippet=result.get("extra", {}).get("lines"),
                help_url=result.get("extra", {}).get("doc_url"),
            )
            findings.append(finding)

        return findings


def _map_severity(semgrep_severity: str) -> Severity:
    """Map semgrep severity to normalized severity level."""
    severity_map: dict[str, Severity] = {
        "ERROR": "ERROR",
        "WARNING": "WARNING",
        "INFO": "INFO",
        "HIGH": "ERROR",
        "MEDIUM": "WARNING",
        "LOW": "INFO",
    }
    normalized = severity_map.get(semgrep_severity.upper(), "INFO")
    if not semgrep_severity or semgrep_severity.strip() == "":
        return "WARNING"
    return normalized