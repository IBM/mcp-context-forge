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


class TestMaxCriticalVulnerabilitiesEvaluatorComprehensive:
    """Extended comprehensive tests for max_critical_vulnerabilities."""

    def test_zero_errors_with_zero_limit(self):
        """Test zero errors against zero limit."""
        evaluator = MaxCriticalVulnerabilitiesEvaluator()
        findings = {"summary": {"error_count": 0}}
        result = evaluator.evaluate(0, findings)
        assert result.passed is True

    def test_large_error_counts(self):
        """Test with large error counts."""
        evaluator = MaxCriticalVulnerabilitiesEvaluator()
        findings = {"summary": {"error_count": 1000}}
        result = evaluator.evaluate(500, findings)
        assert result.passed is False
        assert result.details["error_count"] == 1000

    def test_empty_summary_dict(self):
        """Test with completely empty findings."""
        evaluator = MaxCriticalVulnerabilitiesEvaluator()
        findings = {}
        result = evaluator.evaluate(5, findings)
        assert result.passed is True
        assert result.details["error_count"] == 0

    def test_severity_is_error_on_failure(self):
        """Test that severity is ERROR when rule fails."""
        evaluator = MaxCriticalVulnerabilitiesEvaluator()
        findings = {"summary": {"error_count": 10}}
        result = evaluator.evaluate(5, findings)
        assert result.severity == Severity.ERROR

    def test_severity_is_info_on_pass(self):
        """Test that severity is INFO when rule passes."""
        evaluator = MaxCriticalVulnerabilitiesEvaluator()
        findings = {"summary": {"error_count": 2}}
        result = evaluator.evaluate(10, findings)
        assert result.severity == Severity.INFO


class TestMaxHighVulnerabilitiesEvaluatorComprehensive:
    """Extended comprehensive tests for max_high_vulnerabilities."""

    def test_at_limit_exactly(self):
        """Test warning count exactly at limit."""
        evaluator = MaxHighVulnerabilitiesEvaluator()
        findings = {"summary": {"warning_count": 10}}
        result = evaluator.evaluate(10, findings)
        assert result.passed is True

    def test_far_exceeds_limit(self):
        """Test warning count far exceeding limit."""
        evaluator = MaxHighVulnerabilitiesEvaluator()
        findings = {"summary": {"warning_count": 100}}
        result = evaluator.evaluate(5, findings)
        assert result.passed is False
        assert result.severity == Severity.ERROR
        assert "exceeding" in result.message

    def test_missing_warning_count_defaults_to_zero(self):
        """Test that missing warning_count defaults to 0."""
        evaluator = MaxHighVulnerabilitiesEvaluator()
        findings = {"summary": {}}
        result = evaluator.evaluate(5, findings)
        assert result.passed is True
        assert result.details["warning_count"] == 0

    def test_rule_name_in_result(self):
        """Test that rule_name is set correctly."""
        evaluator = MaxHighVulnerabilitiesEvaluator()
        findings = {"summary": {"warning_count": 3}}
        result = evaluator.evaluate(10, findings)
        assert result.rule_name == "max_high_vulnerabilities"


class TestSbomRequiredEvaluatorComprehensive:
    """Extended comprehensive tests for sbom_required."""

    def test_sbom_present_required_true(self):
        """Test SBOM present when required=True."""
        evaluator = SbomRequiredEvaluator()
        findings = {"sbom_present": True}
        result = evaluator.evaluate(True, findings)
        assert result.passed is True
        assert result.severity == Severity.INFO

    def test_sbom_missing_required_true(self):
        """Test SBOM missing when required=True."""
        evaluator = SbomRequiredEvaluator()
        findings = {"sbom_present": False}
        result = evaluator.evaluate(True, findings)
        assert result.passed is False
        assert result.severity == Severity.ERROR

    def test_sbom_present_required_false(self):
        """Test SBOM present when required=False."""
        evaluator = SbomRequiredEvaluator()
        findings = {"sbom_present": True}
        result = evaluator.evaluate(False, findings)
        assert result.passed is True

    def test_sbom_missing_required_false(self):
        """Test SBOM missing when required=False."""
        evaluator = SbomRequiredEvaluator()
        findings = {"sbom_present": False}
        result = evaluator.evaluate(False, findings)
        assert result.passed is True

    def test_missing_sbom_present_flag_defaults_to_false(self):
        """Test that missing sbom_present flag defaults to False."""
        evaluator = SbomRequiredEvaluator()
        findings = {}
        result = evaluator.evaluate(True, findings)
        assert result.passed is False

    def test_message_contains_sbom_requirement_status(self):
        """Test that message conveys SBOM requirement status."""
        evaluator = SbomRequiredEvaluator()
        
        # Required and provided
        findings = {"sbom_present": True}
        result = evaluator.evaluate(True, findings)
        assert "required" in result.message.lower()
        assert "provided" in result.message.lower()
        
        # Required but missing
        findings = {"sbom_present": False}
        result = evaluator.evaluate(True, findings)
        assert "required" in result.message.lower()


class TestMinTrustScoreEvaluatorComprehensive:
    """Extended comprehensive tests for min_trust_score."""

    def test_score_exactly_at_minimum(self):
        """Test trust score exactly at minimum threshold."""
        evaluator = MinTrustScoreEvaluator()
        findings = {"trust_score": 50}
        result = evaluator.evaluate(50, findings)
        assert result.passed is True

    def test_zero_minimum_threshold(self):
        """Test with zero as minimum threshold."""
        evaluator = MinTrustScoreEvaluator()
        findings = {"trust_score": 0}
        result = evaluator.evaluate(0, findings)
        assert result.passed is True

    def test_max_score_values(self):
        """Test with max score values (0-100 scale)."""
        evaluator = MinTrustScoreEvaluator()
        findings = {"trust_score": 100}
        result = evaluator.evaluate(100, findings)
        assert result.passed is True

    def test_score_one_below_minimum(self):
        """Test score one point below minimum."""
        evaluator = MinTrustScoreEvaluator()
        findings = {"trust_score": 69}
        result = evaluator.evaluate(70, findings)
        assert result.passed is False

    def test_missing_trust_score_assumption(self):
        """Test behavior when trust_score is completely missing."""
        evaluator = MinTrustScoreEvaluator()
        findings = {}
        result = evaluator.evaluate(50, findings)
        assert result.passed is False
        assert result.details["trust_score"] == 0

    def test_negative_trust_scores(self):
        """Test with negative trust scores."""
        evaluator = MinTrustScoreEvaluator()
        findings = {"trust_score": -10}
        result = evaluator.evaluate(0, findings)
        assert result.passed is False

    def test_message_shows_threshold_difference(self):
        """Test that message shows score and required values."""
        evaluator = MinTrustScoreEvaluator()
        findings = {"trust_score": 45}
        result = evaluator.evaluate(80, findings)
        assert "45" in result.message
        assert "80" in result.message


class TestNoRootExecutionEvaluatorComprehensive:
    """Extended comprehensive tests for no_root_execution."""

    def test_root_execution_enforced_and_running_as_root(self):
        """Test enforced no-root but running as root."""
        evaluator = NoRootExecutionEvaluator()
        findings = {"runs_as_root": True}
        result = evaluator.evaluate(True, findings)
        assert result.passed is False
        assert result.severity == Severity.ERROR

    def test_root_execution_enforced_and_running_as_non_root(self):
        """Test enforced no-root and running as non-root."""
        evaluator = NoRootExecutionEvaluator()
        findings = {"runs_as_root": False}
        result = evaluator.evaluate(True, findings)
        assert result.passed is True
        assert result.severity == Severity.INFO

    def test_root_execution_not_enforced_but_running_as_root(self):
        """Test not enforced but running as root anyway."""
        evaluator = NoRootExecutionEvaluator()
        findings = {"runs_as_root": True}
        result = evaluator.evaluate(False, findings)
        assert result.passed is True

    def test_root_execution_not_enforced_and_running_as_non_root(self):
        """Test not enforced and running as non-root."""
        evaluator = NoRootExecutionEvaluator()
        findings = {"runs_as_root": False}
        result = evaluator.evaluate(False, findings)
        assert result.passed is True

    def test_missing_runs_as_root_flag_defaults_to_false(self):
        """Test that missing runs_as_root flag defaults to False."""
        evaluator = NoRootExecutionEvaluator()
        findings = {}
        result = evaluator.evaluate(True, findings)
        assert result.passed is True  # Default is non-root

    def test_message_indicates_execution_context(self):
        """Test message indicates whether running as root or non-root."""
        evaluator = NoRootExecutionEvaluator()
        
        # Running as root
        findings = {"runs_as_root": True}
        result = evaluator.evaluate(True, findings)
        assert "root" in result.message.lower()
        
        # Running as non-root
        findings = {"runs_as_root": False}
        result = evaluator.evaluate(True, findings)
        assert "non-root" in result.message.lower()


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

    def test_factory_returns_new_instance_each_time(self):
        """Test that factory returns independent evaluator instances."""
        eval1 = RuleEvaluatorFactory.get_evaluator("max_critical_vulnerabilities")
        eval2 = RuleEvaluatorFactory.get_evaluator("max_critical_vulnerabilities")
        assert eval1 is not eval2
        assert type(eval1) is type(eval2)

    def test_factory_has_all_five_evaluators(self):
        """Test that factory has exactly 5 supported rules."""
        assert len(RuleEvaluatorFactory.EVALUATORS) == 5

    def test_factory_evaluators_are_correct_classes(self):
        """Test that factory maps rules to correct evaluator classes."""
        assert RuleEvaluatorFactory.EVALUATORS["max_critical_vulnerabilities"] == MaxCriticalVulnerabilitiesEvaluator
        assert RuleEvaluatorFactory.EVALUATORS["max_high_vulnerabilities"] == MaxHighVulnerabilitiesEvaluator
        assert RuleEvaluatorFactory.EVALUATORS["sbom_required"] == SbomRequiredEvaluator
        assert RuleEvaluatorFactory.EVALUATORS["min_trust_score"] == MinTrustScoreEvaluator
        assert RuleEvaluatorFactory.EVALUATORS["no_root_execution"] == NoRootExecutionEvaluator
