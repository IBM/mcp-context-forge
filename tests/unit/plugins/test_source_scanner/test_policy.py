#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Location: tests/unit/plugins/test_source_scanner/test_policy.py
Copyright: 2026
SPDX-License-Identifier: Apache-2.0
Authors: Yaser
Unit tests for Policy evaluation logic.
"""

# First-Party
from plugins.source_scanner.models import Finding, PolicyDecision
from plugins.source_scanner.policy import PolicyChecker


def _finding(severity: str) -> Finding:
    """Helper function to create a Finding object."""
    return Finding(
        scanner="semgrep",
        severity=severity,  # type: ignore[arg-type]
        rule_id="test-rule",
        message="Test finding",
        file_path="app.py",
        line=1,
    )


class TestPolicyEvaluation:
    """Test suite for PolicyChecker.evaluate() method."""

    def test_policy_blocks_on_error_threshold_violation(self) -> None:
        """Test that ERROR findings block when threshold is ERROR and fail_on_critical=True."""
        checker = PolicyChecker()
        findings = [_finding("ERROR")]

        decision = checker.evaluate(findings, threshold="ERROR", fail_on_critical=True)

        assert isinstance(decision, PolicyDecision)
        assert decision.blocked is True
        assert decision.reason is not None
        assert "ERROR" in decision.reason

    def test_policy_blocks_on_warning_threshold_violation(self) -> None:
        """Test that WARNING findings block when threshold is WARNING."""
        checker = PolicyChecker()
        findings = [_finding("ERROR"), _finding("WARNING"), _finding("INFO")]

        decision = checker.evaluate(findings, threshold="WARNING", fail_on_critical=True)

        assert decision.blocked is True
        assert "1 ERROR" in decision.reason or "ERROR" in decision.reason
        assert "1 WARNING" in decision.reason or "WARNING" in decision.reason

    def test_policy_allows_when_no_violations(self) -> None:
        """Test that no findings block when below threshold."""
        checker = PolicyChecker()
        findings = [_finding("INFO")]

        decision = checker.evaluate(findings, threshold="WARNING", fail_on_critical=True)

        assert decision.blocked is False
        assert decision.reason is None

    def test_policy_audit_mode_never_blocks(self) -> None:
        """Test that audit mode (fail_on_critical=False) never blocks."""
        checker = PolicyChecker()
        findings = [_finding("ERROR"), _finding("WARNING"), _finding("INFO")]

        decision = checker.evaluate(findings, threshold="INFO", fail_on_critical=False)

        assert decision.blocked is False
        assert decision.reason is None

    def test_policy_info_threshold_includes_info_findings(self) -> None:
        """Test that INFO threshold blocks on INFO findings."""
        checker = PolicyChecker()
        findings = [_finding("INFO")]

        decision = checker.evaluate(findings, threshold="INFO", fail_on_critical=True)

        assert decision.blocked is True
        assert decision.reason is not None

    def test_policy_error_threshold_ignores_warnings(self) -> None:
        """Test that ERROR threshold allows WARNING/INFO findings."""
        checker = PolicyChecker()
        findings = [_finding("WARNING"), _finding("INFO")]

        decision = checker.evaluate(findings, threshold="ERROR", fail_on_critical=True)

        assert decision.blocked is False

    def test_policy_unknown_threshold_defaults_to_warning(self) -> None:
        """Test that unknown threshold defaults to WARNING behavior."""
        checker = PolicyChecker()
        findings = [_finding("WARNING")]

        # Use an unknown/invalid threshold
        decision = checker.evaluate(findings, threshold="INVALID", fail_on_critical=True)

        # Should default to WARNING and block
        assert decision.blocked is True

    def test_policy_reason_includes_all_severity_counts(self) -> None:
        """Test that block reason includes counts of all severity levels."""
        checker = PolicyChecker()
        findings = [
            _finding("ERROR"),
            _finding("ERROR"),
            _finding("WARNING"),
            _finding("INFO"),
            _finding("INFO"),
        ]

        decision = checker.evaluate(findings, threshold="INFO", fail_on_critical=True)

        assert decision.blocked is True
        assert "2 ERROR" in decision.reason
        assert "1 WARNING" in decision.reason
        assert "2 INFO" in decision.reason

    def test_policy_empty_findings_list(self) -> None:
        """Test policy evaluation with no findings."""
        checker = PolicyChecker()
        findings = []

        decision = checker.evaluate(findings, threshold="WARNING", fail_on_critical=True)

        assert decision.blocked is False
        assert decision.reason is None

    def test_policy_decision_dataclass_fields(self) -> None:
        """Test that PolicyDecision has correct fields."""
        decision = PolicyDecision(blocked=True, reason="Test reason")

        assert decision.blocked is True
        assert decision.reason == "Test reason"

    def test_policy_decision_reason_can_be_none(self) -> None:
        """Test that PolicyDecision reason can be None."""
        decision = PolicyDecision(blocked=False)

        assert decision.blocked is False
        assert decision.reason is None
