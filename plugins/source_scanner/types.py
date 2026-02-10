#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/source_scanner/types.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi, Ayo

Data schemas for findings and scan results.
"""

# Future
from __future__ import annotations

# Standard
from typing import List, Literal, Optional

# Third-Party
from pydantic import BaseModel, Field


class Finding(BaseModel):
    """Unified finding schema from any scanner.

    Attributes:
        scanner: Source scanner tool name (e.g., "semgrep", "bandit").
        severity: Normalized severity level (ERROR|WARNING|INFO).
        rule_id: Rule identifier for deduplication.
        message: Human-readable description.
        file_path: Relative path to the problematic file.
        line: Line number where issue occurs.
        column: Column number where issue occurs.
        code_snippet: Code context around the issue.
        help_url: Link to rule documentation.
    """

    scanner: str
    severity: Literal["ERROR", "WARNING", "INFO"]  # ERROR | WARNING | INFO
    rule_id: str
    message: str
    file_path: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    code_snippet: Optional[str] = None
    help_url: Optional[str] = None

    def dedup_key(self) -> tuple[str, str, Optional[str], Optional[int], str]:
        """Generate deduplication key.

        Returns:
            Tuple of (scanner, rule_id, file_path, line, message).
        """
        return (
            self.scanner,
            self.rule_id,
            self.file_path,
            self.line,
            self.message,
        )


class ScanSummary(BaseModel):
    """Summary statistics for scan results.

    Attributes:
        error_count: Number of ERROR-level findings.
        warning_count: Number of WARNING-level findings.
        info_count: Number of INFO-level findings.
    """

    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0

    @property
    def total_findings(self) -> int:
        """Calculate total findings count."""
        return self.error_count + self.warning_count + self.info_count


class ScanResult(BaseModel):
    """Complete scan result contract.

    Attributes:
        repo_url: Repository URL that was scanned.
        ref: Branch/tag/commit reference requested.
        commit_sha: Resolved commit SHA after checkout.
        languages: Detected programming languages.
        findings: All normalized findings.
        summary: Aggregated statistics.
        blocked: Whether policy blocked the workflow.
        block_reason: Explanation if blocked.
    """

    repo_url: str
    ref: Optional[str] = None
    commit_sha: Optional[str] = None
    languages: List[str] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=lambda: [])
    summary: ScanSummary = Field(default_factory=ScanSummary)
    blocked: bool = False
    block_reason: Optional[str] = None


class PolicyDecision(BaseModel):
    """Result of policy evaluation.

    Attributes:
        blocked: Whether the workflow should be blocked.
        reason: Explanation for blocking, if applicable.
    """

    blocked: bool
    reason: Optional[str] = None
    scan_duration_seconds: Optional[float] = None
