#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_container_scanner/test_policy_evaluator.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Unit tests for PolicyEvaluator.
"""

from __future__ import annotations

import pytest

from plugins.container_scanner.config import ScannerConfig
from plugins.container_scanner.policy.policy_evaluator import PolicyDecision, PolicyEvaluator
from plugins.container_scanner.types import Vulnerability


def make_vuln(severity="HIGH", cve_id="CVE-2023-0001", fixed_version="1.0.1") -> Vulnerability:
    return Vulnerability(
        scanner="trivy",
        cve_id=cve_id,
        severity=severity,
        package_name="libfoo",
        installed_version="1.0.0",
        fixed_version=fixed_version,
    )


def make_config(**kwargs) -> ScannerConfig:
    defaults = dict(scanner="trivy", mode="enforce", severity_threshold="HIGH", fail_on_unfixed=False)
    defaults.update(kwargs)
    return ScannerConfig(**defaults)


class TestPolicyEvaluatorEnforceMode:
    evaluator = PolicyEvaluator()

    def test_no_violations_not_blocked(self):
        cfg = make_config(mode="enforce", severity_threshold="HIGH")
        # LOW vuln is below HIGH threshold
        vulns = [make_vuln(severity="LOW")]
        decision = self.evaluator.evaluate(vulns, cfg)
        assert decision.blocked is False
        assert decision.reason is None

    def test_violations_cause_block(self):
        cfg = make_config(mode="enforce", severity_threshold="HIGH")
        vulns = [make_vuln(severity="CRITICAL"), make_vuln(severity="HIGH", cve_id="CVE-2023-0002")]
        decision = self.evaluator.evaluate(vulns, cfg)
        assert decision.blocked is True
        assert decision.reason is not None
        assert "Blocked" in decision.reason

    def test_violations_list_populated(self):
        cfg = make_config(mode="enforce", severity_threshold="HIGH")
        vulns = [make_vuln(severity="HIGH")]
        decision = self.evaluator.evaluate(vulns, cfg)
        assert len(decision.violations) == 1

    def test_empty_vulns_not_blocked(self):
        cfg = make_config(mode="enforce")
        decision = self.evaluator.evaluate([], cfg)
        assert decision.blocked is False

    def test_critical_threshold_blocks_only_critical(self):
        cfg = make_config(mode="enforce", severity_threshold="CRITICAL")
        vulns = [make_vuln(severity="HIGH"), make_vuln(severity="CRITICAL", cve_id="CVE-2023-X")]
        decision = self.evaluator.evaluate(vulns, cfg)
        # Only CRITICAL triggers block, HIGH is below threshold
        assert decision.blocked is True
        assert len(decision.violations) == 1
        assert decision.violations[0].severity == "CRITICAL"


class TestPolicyEvaluatorAuditMode:
    evaluator = PolicyEvaluator()

    def test_violations_not_blocked_in_audit(self):
        cfg = make_config(mode="audit", severity_threshold="HIGH")
        vulns = [make_vuln(severity="CRITICAL")]
        decision = self.evaluator.evaluate(vulns, cfg)
        assert decision.blocked is False

    def test_audit_sets_reason_when_violations(self):
        cfg = make_config(mode="audit", severity_threshold="HIGH")
        vulns = [make_vuln(severity="HIGH")]
        decision = self.evaluator.evaluate(vulns, cfg)
        assert decision.reason is not None
        assert "Audit" in decision.reason

    def test_audit_no_reason_when_no_violations(self):
        cfg = make_config(mode="audit", severity_threshold="HIGH")
        vulns = [make_vuln(severity="LOW")]
        decision = self.evaluator.evaluate(vulns, cfg)
        assert decision.reason is None


class TestPolicyEvaluatorDisabledMode:
    evaluator = PolicyEvaluator()

    def test_disabled_never_blocks(self):
        cfg = make_config(mode="disabled")
        vulns = [make_vuln(severity="CRITICAL")]
        decision = self.evaluator.evaluate(vulns, cfg)
        assert decision.blocked is False
        assert decision.reason == 'scan skipped'


class TestPolicyEvaluatorFilters:
    evaluator = PolicyEvaluator()

    def test_ignore_cves_drops_matching(self):
        cfg = make_config(mode="enforce", severity_threshold="HIGH", ignore_cves=["CVE-2023-0001"])
        vulns = [make_vuln(severity="CRITICAL", cve_id="CVE-2023-0001")]
        decision = self.evaluator.evaluate(vulns, cfg)
        assert decision.blocked is False

    def test_ignore_cves_does_not_drop_others(self):
        cfg = make_config(mode="enforce", severity_threshold="HIGH", ignore_cves=["CVE-2023-0001"])
        vulns = [make_vuln(severity="HIGH", cve_id="CVE-2023-9999")]
        decision = self.evaluator.evaluate(vulns, cfg)
        assert decision.blocked is True

    def test_fail_on_unfixed_false_drops_unfixed(self):
        cfg = make_config(mode="enforce", severity_threshold="HIGH", fail_on_unfixed=False)
        # Vuln with no fix available (fixed_version=None)
        unfixed = make_vuln(severity="CRITICAL", fixed_version=None)
        decision = self.evaluator.evaluate([unfixed], cfg)
        assert decision.blocked is False

    def test_fail_on_unfixed_true_keeps_unfixed(self):
        cfg = make_config(mode="enforce", severity_threshold="HIGH", fail_on_unfixed=True)
        unfixed = make_vuln(severity="HIGH", fixed_version=None)
        decision = self.evaluator.evaluate([unfixed], cfg)
        assert decision.blocked is True


class TestFormatReason:
    evaluator = PolicyEvaluator()

    def test_blocked_prefix(self):
        vulns = [make_vuln(severity="HIGH")]
        reason = self.evaluator._format_reason(vulns, "HIGH", blocked=True)
        assert reason.startswith("Blocked:")

    def test_audit_prefix(self):
        vulns = [make_vuln(severity="CRITICAL")]
        reason = self.evaluator._format_reason(vulns, "HIGH", blocked=False)
        assert reason.startswith("Audit:")

    def test_counts_by_severity(self):
        vulns = [
            make_vuln(severity="CRITICAL", cve_id="CVE-1"),
            make_vuln(severity="CRITICAL", cve_id="CVE-2"),
            make_vuln(severity="HIGH", cve_id="CVE-3"),
        ]
        reason = self.evaluator._format_reason(vulns, "HIGH", blocked=True)
        assert "2 CRITICAL" in reason
        assert "1 HIGH" in reason
