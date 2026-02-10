#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/source_scanner/policy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi, Ayo

Policy evaluation for scan findings.
"""

# Standard
from typing import List

# Local
from .types import Finding, PolicyDecision


class PolicyChecker:
    """Evaluates findings against policy thresholds."""

    # Severity ordering: ERROR > WARNING > INFO
    _SEVERITY_ORDER = {"ERROR": 3, "WARNING": 2, "INFO": 1}

    def evaluate(
        self,
        findings: List[Finding],
        threshold: str,
        fail_on_critical: bool,
    ) -> PolicyDecision:
        """Evaluate findings against policy."""

        # Normalize/validate threshold
        thr = threshold.upper()
        if thr not in self._SEVERITY_ORDER:
            # Default safe behavior: treat unknown threshold as WARNING
            thr = "WARNING"

        thr_value = self._SEVERITY_ORDER[thr]

        # Findings that meet or exceed threshold
        violating = [f for f in findings if self._SEVERITY_ORDER.get(f.severity, 0) >= thr_value]

        # Audit mode: never block, just report
        if not fail_on_critical:
            return PolicyDecision(blocked=False)

        # Enforce mode: block if any violations exist
        if violating:
            error_count = sum(1 for f in findings if f.severity == "ERROR")
            warning_count = sum(1 for f in findings if f.severity == "WARNING")
            info_count = sum(1 for f in findings if f.severity == "INFO")

            reason = f"Policy threshold {thr} violated: " f"{error_count} ERROR, {warning_count} WARNING, {info_count} INFO findings."
            return PolicyDecision(blocked=True, reason=reason)

        return PolicyDecision(blocked=False)
