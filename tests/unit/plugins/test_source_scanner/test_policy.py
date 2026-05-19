#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Location: tests/unit/plugins/test_source_scanner/test_policy.py
Copyright: 2026
SPDX-License-Identifier: Apache-2.0
Authors: Yaser
"""

# First-Party
from plugins.source_scanner.policy import PolicyChecker
from plugins.source_scanner.types import Finding


def _finding(severity: str) -> Finding:
    return Finding(
        scanner="semgrep",
        severity=severity,  # type: ignore[arg-type]
        rule_id="rule",
        message="issue",
        file_path="app.py",
        line=1,
    )


def test_policy_blocks_on_threshold_violation() -> None:
    checker = PolicyChecker()
    findings = [_finding("ERROR"), _finding("WARNING"), _finding("INFO")]

    decision = checker.evaluate(findings, threshold="WARNING", fail_on_critical=True)

    assert decision.blocked is True
    assert decision.reason is not None
    assert "Policy threshold WARNING violated" in decision.reason
    assert "1 ERROR" in decision.reason
    assert "1 WARNING" in decision.reason
    assert "1 INFO" in decision.reason


def test_policy_allows_when_no_violations() -> None:
    checker = PolicyChecker()
    findings = [_finding("WARNING"), _finding("INFO")]

    decision = checker.evaluate(findings, threshold="ERROR", fail_on_critical=True)

    assert decision.blocked is False
    assert decision.reason is None


def test_policy_audit_mode_never_blocks() -> None:
    checker = PolicyChecker()
    findings = [_finding("ERROR")]

    decision = checker.evaluate(findings, threshold="ERROR", fail_on_critical=False)

    assert decision.blocked is False


def test_policy_unknown_threshold_defaults_to_warning() -> None:
    checker = PolicyChecker()
    findings = [_finding("WARNING")]

    decision = checker.evaluate(findings, threshold="unknown", fail_on_critical=True)

    assert decision.blocked is True
    assert decision.reason is not None


def test_policy_info_threshold_includes_info() -> None:
    checker = PolicyChecker()
    findings = [_finding("INFO")]

    decision = checker.evaluate(findings, threshold="INFO", fail_on_critical=True)

    assert decision.blocked is True
