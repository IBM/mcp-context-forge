"""
test_rules.py - Unit tests for rule evaluators

Tests individual rule evaluators to ensure they correctly
evaluate findings against thresholds.
"""

import pytest
from ..rules import (
    MaxCriticalVulnerabilitiesEvaluator,
    MaxHighVulnerabilitiesEvaluator,
    SbomRequiredEvaluator,
    MinTrustScoreEvaluator,
    NoRootExecutionEvaluator,
    RuleEvaluatorFactory,
)
from ..models import Severity


class TestMaxCriticalVulnerabilitiesEvaluator:
    """Test max_critical_vulnerabilities rule evaluator."""

    def test_pass_when_under_limit(self):
        """Test that rule passes when error count is under limit."""
        evaluator = MaxCriticalVulnerabilitiesEvaluator()
        findings = {"summary": {"error_count": 2}}
        result = evaluator.evaluate(5, findings)

        assert result.passed is True
        assert result.rule_name == "max_critical_vulnerabilities"
        assert result.details["error_count"] == 2
        assert result.details["allowed"] == 5

    def test_pass_when_at_limit(self):
        """Test that rule passes when error count equals limit."""
        evaluator = MaxCriticalVulnerabilitiesEvaluator()
        findings = {"summary": {"error_count": 5}}
        result = evaluator.evaluate(5, findings)

        assert result.passed is True

    def test_fail_when_over_limit(self):
        """Test that rule fails when error count exceeds limit."""
        evaluator = MaxCriticalVulnerabilitiesEvaluator()
        findings = {"summary": {"error_count": 10}}
        result = evaluator.evaluate(5, findings)

        assert result.passed is False
        assert result.severity == Severity.ERROR
        assert "exceeding" in result.message

    def test_default_zero_errors(self):
        """Test that missing error_count defaults to 0."""
        evaluator = MaxCriticalVulnerabilitiesEvaluator()
        findings = {"summary": {}}
        result = evaluator.evaluate(0, findings)

        assert result.passed is True
        assert result.details["error_count"] == 0


class TestMaxHighVulnerabilitiesEvaluator:
    """Test max_high_vulnerabilities rule evaluator."""

    def test_pass_when_under_limit(self):
        """Test that rule passes when warning count is under limit."""
        evaluator = MaxHighVulnerabilitiesEvaluator()
        findings = {"summary": {"warning_count": 3}}
        result = evaluator.evaluate(10, findings)

        assert result.passed is True
        assert result.details["warning_count"] == 3

    def test_fail_when_over_limit(self):
        """Test that rule fails when warning count exceeds limit."""
        evaluator = MaxHighVulnerabilitiesEvaluator()
        findings = {"summary": {"warning_count": 15}}
        result = evaluator.evaluate(10, findings)

        assert result.passed is False
        assert result.severity == Severity.ERROR


class TestSbomRequiredEvaluator:
    """Test sbom_required rule evaluator."""

    def test_pass_when_sbom_provided(self):
        """Test that rule passes when SBOM is provided and required."""
        evaluator = SbomRequiredEvaluator()
        findings = {"sbom_present": True}
        result = evaluator.evaluate(True, findings)

        assert result.passed is True
        assert "provided" in result.message

    def test_fail_when_sbom_missing(self):
        """Test that rule fails when SBOM is required but not provided."""
        evaluator = SbomRequiredEvaluator()
        findings = {"sbom_present": False}
        result = evaluator.evaluate(True, findings)

        assert result.passed is False
        assert result.severity == Severity.ERROR
        assert "required" in result.message

    def test_pass_when_sbom_not_required(self):
        """Test that rule passes when SBOM is not required."""
        evaluator = SbomRequiredEvaluator()
        findings = {"sbom_present": False}
        result = evaluator.evaluate(False, findings)

        assert result.passed is True
        assert "not required" in result.message


class TestMinTrustScoreEvaluator:
    """Test min_trust_score rule evaluator."""

    def test_pass_when_score_meets_requirement(self):
        """Test that rule passes when trust score meets minimum."""
        evaluator = MinTrustScoreEvaluator()
        findings = {"trust_score": 75}
        result = evaluator.evaluate(70, findings)

        assert result.passed is True
        assert result.details["trust_score"] == 75

    def test_pass_when_score_exceeds_requirement(self):
        """Test that rule passes when trust score exceeds minimum."""
        evaluator = MinTrustScoreEvaluator()
        findings = {"trust_score": 95}
        result = evaluator.evaluate(70, findings)

        assert result.passed is True

    def test_fail_when_score_below_requirement(self):
        """Test that rule fails when trust score is below minimum."""
        evaluator = MinTrustScoreEvaluator()
        findings = {"trust_score": 50}
        result = evaluator.evaluate(70, findings)

        assert result.passed is False
        assert result.severity == Severity.ERROR

    def test_default_zero_score(self):
        """Test that missing trust_score defaults to 0."""
        evaluator = MinTrustScoreEvaluator()
        findings = {}
        result = evaluator.evaluate(50, findings)

        assert result.passed is False
        assert result.details["trust_score"] == 0


class TestNoRootExecutionEvaluator:
    """Test no_root_execution rule evaluator."""

    def test_pass_when_non_root(self):
        """Test that rule passes when container runs as non-root."""
        evaluator = NoRootExecutionEvaluator()
        findings = {"runs_as_root": False}
        result = evaluator.evaluate(True, findings)

        assert result.passed is True
        assert "non-root" in result.message

    def test_fail_when_runs_as_root(self):
        """Test that rule fails when container runs as root."""
        evaluator = NoRootExecutionEvaluator()
        findings = {"runs_as_root": True}
        result = evaluator.evaluate(True, findings)

        assert result.passed is False
        assert result.severity == Severity.ERROR
        assert "root" in result.message

    def test_pass_when_root_not_enforced(self):
        """Test that rule passes when root check is disabled."""
        evaluator = NoRootExecutionEvaluator()
        findings = {"runs_as_root": True}
        result = evaluator.evaluate(False, findings)

        assert result.passed is True


class TestRuleEvaluatorFactory:
    """Test rule evaluator factory."""

    def test_get_evaluator_returns_correct_instance(self):
        """Test that factory returns correct evaluator instance."""
        evaluator = RuleEvaluatorFactory.get_evaluator("max_critical_vulnerabilities")
        assert isinstance(evaluator, MaxCriticalVulnerabilitiesEvaluator)

    def test_get_evaluator_returns_none_for_unknown_rule(self):
        """Test that factory returns None for unknown rule."""
        evaluator = RuleEvaluatorFactory.get_evaluator("unknown_rule")
        assert evaluator is None

    def test_supports_rule_returns_true_for_known_rules(self):
        """Test that factory recognizes all known rules."""
        known_rules = [
            "max_critical_vulnerabilities",
            "max_high_vulnerabilities",
            "sbom_required",
            "min_trust_score",
            "no_root_execution",
        ]
        for rule in known_rules:
            assert RuleEvaluatorFactory.supports_rule(rule) is True

    def test_supports_rule_returns_false_for_unknown_rules(self):
        """Test that factory rejects unknown rules."""
        assert RuleEvaluatorFactory.supports_rule("unknown_rule") is False
