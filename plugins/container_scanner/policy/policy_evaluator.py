#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/container_scanner/policy/policy_evaluator.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Evaluates a list of Vulnerability objects against a ScannerConfig and returns
a PolicyDecision indicating whether deployment should be blocked.
"""

# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass, field
from typing import List, Optional
from collections import Counter

# Local
from plugins.container_scanner.config import ScannerConfig
from plugins.container_scanner.types import Vulnerability

_SEVERITY_ORDER: dict[str, int] = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "UNKNOWN": 0,
}


@dataclass
class PolicyDecision:
    """Result of a policy evaluation pass.

    Attributes:
        blocked: Whether deployment should be blocked.
        reason: Human-readable explanation (set even in audit mode).
        violations: Filtered vulnerabilities that triggered the decision.
    """

    blocked: bool
    reason: Optional[str] = None
    violations: List[Vulnerability] = field(default_factory=list)


class PolicyEvaluator:
    """Applies configured policy rules to a list of vulnerabilities."""

    def _format_reason(self, violations: List[Vulnerability], threshold: str, blocked: bool) -> str:
        """Build a human-readable summary of policy violations.

        Args:
            violations: The filtered list of violating vulnerabilities.
            threshold: The configured severity threshold label.
            blocked: Whether the decision is a hard block.

        Returns:
            A string like "Blocked: 2 CRITICAL, 3 HIGH vulnerabilities exceed threshold HIGH"
            or the equivalent prefixed with "Audit:" when not blocking.
        """
        counts: Counter[str] = Counter(v.severity for v in violations)
        severity_parts = [
            f"{counts[sev]} {sev}"
            for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
            if counts[sev]
        ]
        prefix = "Blocked" if blocked else "Audit"
        return f"{prefix}: {', '.join(severity_parts)} vulnerabilities exceed threshold {threshold}"

    def evaluate(self, vulnerabilities: List[Vulnerability], config: ScannerConfig) -> PolicyDecision:
        """Evaluate vulnerabilities against policy and return a decision.
        1. Severity filter  — drop vulns below config.severity_threshold
        2. Ignore list      — drop vulns in config.ignore_cves
        3. Unfixed filter   — when fail_on_unfixed=False, drop unfixed vulns
        4. Mode decision    — enforce → block if violations exist; audit → allow but surface

        Args:
            vulnerabilities: Normalized list from the scanner adapter.
            config: Active ScannerConfig for this evaluation.

        Returns:
            PolicyDecision with blocked flag, optional reason, and violation list.
        """
        threshold_rank = _SEVERITY_ORDER[config.severity_threshold]
        violations = [v for v in vulnerabilities if _SEVERITY_ORDER.get(v.severity, 0) >= threshold_rank]
        ignore_set = set(config.ignore_cves)
        violations = [v for v in violations if v.cve_id not in ignore_set]
        if not config.fail_on_unfixed:
            violations = [v for v in violations if v.fixed_version is not None]
        if config.mode == "disabled":
            return PolicyDecision(blocked=False, reason="scan skipped")
        elif config.mode == "enforce":
            blocked = bool(violations)
            reason = self._format_reason(violations, config.severity_threshold, blocked=True) if blocked else None
            return PolicyDecision(blocked=blocked, reason=reason, violations=violations)
        else:  # "audit"
            reason = self._format_reason(violations, config.severity_threshold, blocked=False) if violations else None
            return PolicyDecision(blocked=False, reason=reason, violations=violations)
