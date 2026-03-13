#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/source_scanner/config.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi, Ayo

Configuration models for Source Scanner Plugin.
"""

# Future
from __future__ import annotations

# Standard
from typing import Any, List, Literal, Optional

# Third-Party
from pydantic import BaseModel, Field


class SemgrepConfig(BaseModel):
    """Semgrep scanner configuration.

    Attributes:
        enabled: Whether Semgrep is enabled.
        rulesets: List of ruleset identifiers (e.g., p/security-audit).
        extra_args: Additional CLI arguments.
    """

    enabled: bool = True
    rulesets: List[str] = Field(
        default_factory=lambda: [
            "p/security-audit",
            "p/owasp-top-ten",
            "p/python",
            "p/javascript",
        ]
    )
    extra_args: List[str] = Field(default_factory=list)
    timeout_seconds: int = 600  # Default scan timeout of 10 minutes


class BanditConfig(BaseModel):
    """Bandit scanner configuration.

    Attributes:
        enabled: Whether Bandit is enabled.
        severity: Minimum severity level (low/medium/high).
        confidence: Minimum confidence level (low/medium/high).
    """

    enabled: bool = True
    severity: Literal["low", "medium", "high"] = "medium"
    confidence: Literal["low", "medium", "high"] = "medium"


class ScannersConfig(BaseModel):
    """Generic scanner configuration.

    Attributes:
        bandit: Bandit configuration.
        semgrep: Semgrep configuration.
    """

    semgrep: SemgrepConfig = Field(default_factory=SemgrepConfig)
    bandit: BanditConfig = Field(default_factory=BanditConfig)


class SourceScannerConfig(BaseModel):
    """Configuration for source scanner plugin.

    Attributes:
        scanners: Generic scanner configurations.
        semgrep: Semgrep configuration.
        bandit: Bandit configuration.
        severity_threshold: Minimum severity to block (ERROR|WARNING|INFO).
        fail_on_critical: Whether to block on threshold violations.
        clone_timeout_seconds: Timeout for git clone operations.
        scan_timeout_seconds: Timeout for scan operations.
        max_repo_size_mb: Maximum repository size in MB.
        github_token_env: Environment variable for GitHub token.
        cache_by_commit: Whether to cache results by commit SHA.
        cache_ttl_hours: Cache time-to-live in hours.
    """

    scanners: Optional[ScannersConfig] = None
    semgrep: SemgrepConfig = Field(default_factory=SemgrepConfig)
    bandit: BanditConfig = Field(default_factory=BanditConfig)

    severity_threshold: Literal["ERROR", "WARNING", "INFO"] = "WARNING"  # ERROR | WARNING | INFO
    fail_on_critical: bool = True
    clone_timeout_seconds: int = 120
    scan_timeout_seconds: int = 600
    max_repo_size_mb: Optional[int] = 500
    github_token_env: str = "GITHUB_TOKEN"
    cache_by_commit: bool = True
    cache_ttl_hours: int = 168  # 1 week

    def model_post_init(self, __context: Any) -> None:
        """Merge nested scanner configuration into top-level fields after validation."""
        # If user provides config.scanners.*, merge into top-level fields
        if self.scanners is not None:
            self.semgrep = self.scanners.semgrep
            self.bandit = self.scanners.bandit
