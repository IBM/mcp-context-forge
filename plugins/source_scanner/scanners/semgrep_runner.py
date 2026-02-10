#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Semgrep scanner runner for Source Scanner.

Location: ./plugins/source_scanner/scanners/semgrep_runner.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

This module implements Semgrep CLI integration for static code analysis.
Parses SARIF output into normalized Finding objects.
"""

# Standard
import json
import subprocess
from typing import Any, Literal

# First-Party
from plugins.source_scanner.types import Finding


class SemgrepRunner:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.enabled = config.get("enabled", True)
        self.rulesets = config.get("rulesets", ["p/security-audit"])
        self.extra_args = config.get("extra_args", [])
        self.timeout = config.get("timeout", 300)

    def run(self, repo_url: str, temp_folder: str) -> list[Finding]:
        try:
            # Clone repository
            _clone_repo(repo_url, temp_folder)

            # Build and run semgrep command
            command = self.build_command(temp_folder)
            result = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout)

            # Parse output even if semgrep finds issues (return code 1 is normal)
            if result.returncode not in (0, 1):
                raise Exception(f"Semgrep failed: {result.stderr}")

            data: dict[str, Any] = json.loads(result.stdout) if result.stdout else {}
            findings = self.parse_sarif_output(data)

            # Print message based on findings
            if not findings:
                print("No findings detected.")
            else:
                print(f"Found {len(findings)} issue(s):")
                for f in findings:
                    print(f"  [{f.severity}] {f.rule_id} at {f.file_path}:{f.line}")

            return findings
        finally:
            self.delete_temp_repo(temp_folder)

    def build_command(self, repo_path: str) -> list[str]:
        """Build semgrep command with configured rulesets and arguments."""
        return self._build_command(repo_path)

    def parse_sarif_output(self, sarif_data: dict[str, Any]) -> list[Finding]:
        """Parse SARIF output into Finding objects."""
        return self._parse_sarif_output(sarif_data)

    def _build_command(self, repo_path: str) -> list[str]:
        command = ["semgrep", "scan"]

        # Add configured rulesets
        for ruleset in self.rulesets:
            command.extend(["--config", ruleset])

        # Add extra arguments
        command.extend(self.extra_args)

        # Add output format
        command.append("--json")

        # Add target repository path
        command.append(repo_path)
        return command

    def _parse_sarif_output(self, sarif_data: dict[str, Any]) -> list[Finding]:
        findings: list[Finding] = []

        # Handle error case
        if "error" in sarif_data:
            return findings

        # Parse results from semgrep JSON output
        results = sarif_data.get("results", [])

        for result in results:
            finding = Finding(
                scanner="semgrep",
                severity=_map_severity(result.get("severity", "INFO")),
                rule_id=result.get("check_id", "unknown"),
                message=result.get("extra", {}).get("message", result.get("message", "")),
                file_path=result.get("path", None),
                line=result.get("start", {}).get("line", None),
                column=result.get("start", {}).get("col", None),
                code_snippet=result.get("extra", {}).get("lines", None),
                help_url=result.get("extra", {}).get("doc_url", None),
            )
            findings.append(finding)

        return findings

    def delete_temp_repo(self, temp_folder: str) -> None:
        try:
            subprocess.run(["rm", "-rf", temp_folder], check=True)
        except Exception as e:
            print(f"Warning: Failed to delete temp folder {temp_folder}: {e}")


def _clone_repo(repo_url: str, temp_folder: str) -> None:
    """Clone repository to temporary folder."""
    subprocess.run(["git", "clone", "--depth", "1", repo_url, temp_folder], check=True)


Severity = Literal["ERROR", "WARNING", "INFO"]


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
    return severity_map.get(semgrep_severity.upper(), "INFO")
