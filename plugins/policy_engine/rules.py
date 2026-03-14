"""
rules.py - THE BUILDERS (Individual Rule Logic)

Defines HOW to check each individual rule.
Creates rule evaluators (one per rule type).
Each evaluator knows how to evaluate ONE specific rule.
"""

# Future
from __future__ import annotations

# Standard
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

# Local
from .models import RuleEvaluationResult, Severity  # type: ignore


class BaseRuleEvaluator(ABC):
    """Base class for rule evaluators."""

    @abstractmethod
    def evaluate(
        self,
        rule_value: Any,
        findings_data: Dict[str, Any],
    ) -> RuleEvaluationResult:
        """Evaluate the rule against findings.

        Args:
            rule_value: Threshold or expected value from policy
            findings_data: Scan findings data

        Returns:
            RuleEvaluationResult with pass/fail and details
        """
        pass


class MaxCriticalVulnerabilitiesEvaluator(BaseRuleEvaluator):
    """Evaluates max_critical_vulnerabilities rule.

    Checks if error count does not exceed threshold.
    """

    def evaluate(
        self,
        rule_value: int,
        findings_data: Dict[str, Any],
    ) -> RuleEvaluationResult:
        """Check critical vulnerability count.

        Args:
            rule_value: Maximum allowed critical vulnerabilities (errors)
            findings_data: Contains error_count from scan summary

        Returns:
            RuleEvaluationResult
        """
        error_count = findings_data.get("summary", {}).get("error_count", 0)
        if error_count <= rule_value:
            return RuleEvaluationResult(
                rule_name="max_critical_vulnerabilities",
                passed=True,
                message=f"Found {error_count} critical vulnerabilities, within the limit of {rule_value}.",
                severity=Severity.INFO,
                details={"error_count": error_count, "allowed": rule_value},
            )
        else:
            return RuleEvaluationResult(
                rule_name="max_critical_vulnerabilities",
                passed=False,
                message=f"Found {error_count} critical vulnerabilities, exceeding the limit of {rule_value}.",
                severity=Severity.ERROR,
                details={"error_count": error_count, "allowed": rule_value},
            )


class MaxHighVulnerabilitiesEvaluator(BaseRuleEvaluator):
    """Evaluates max_high_vulnerabilities rule.

    Checks if warning count does not exceed threshold.
    """

    def evaluate(
        self,
        rule_value: int,
        findings_data: Dict[str, Any],
    ) -> RuleEvaluationResult:
        """Check high vulnerability count.

        Args:
            rule_value: Maximum allowed high vulnerabilities (warnings)
            findings_data: Contains warning_count from scan summary

        Returns:
            RuleEvaluationResult
        """
        warning_count = findings_data.get("summary", {}).get("warning_count", 0)
        if warning_count <= rule_value:
            return RuleEvaluationResult(
                rule_name="max_high_vulnerabilities",
                passed=True,
                message=f"Found {warning_count} high vulnerabilities, within the limit of {rule_value}.",
                severity=Severity.INFO,
                details={"warning_count": warning_count, "allowed": rule_value},
            )
        else:
            return RuleEvaluationResult(
                rule_name="max_high_vulnerabilities",
                passed=False,
                message=f"Found {warning_count} high vulnerabilities, exceeding the limit of {rule_value}.",
                severity=Severity.ERROR,
                details={"warning_count": warning_count, "allowed": rule_value},
            )


class SbomRequiredEvaluator(BaseRuleEvaluator):
    """Evaluates sbom_required rule.

    Checks if Software Bill of Materials is present.
    """

    def evaluate(
        self,
        rule_value: bool,
        findings_data: Dict[str, Any],
    ) -> RuleEvaluationResult:
        """Check SBOM presence.

        Args:
            rule_value: Whether SBOM is required (True/False)
            findings_data: Contains sbom_present flag

        Returns:
            RuleEvaluationResult
        """
        sbom_present = findings_data.get("sbom_present", False)
        if rule_value:
            if not sbom_present:
                return RuleEvaluationResult(rule_name="sbom_required", passed=False, message="SBOM is required but not provided.", severity=Severity.ERROR, details={"sbom_present": sbom_present})
            else:
                return RuleEvaluationResult(rule_name="sbom_required", passed=True, message="SBOM is required and provided.", severity=Severity.INFO, details={"sbom_present": sbom_present})
        return RuleEvaluationResult(rule_name="sbom_required", passed=True, message="SBOM is not required.", severity=Severity.INFO, details={"sbom_present": sbom_present})


class MinTrustScoreEvaluator(BaseRuleEvaluator):
    """Evaluates min_trust_score rule.

    Checks if trust score meets minimum threshold (0-100).
    """

    def evaluate(
        self,
        rule_value: int,
        findings_data: Dict[str, Any],
    ) -> RuleEvaluationResult:
        """Check trust score threshold.

        Args:
            rule_value: Minimum trust score required (0-100)
            findings_data: Contains trust_score

        Returns:
            RuleEvaluationResult
        """
        trust_score = findings_data.get("trust_score", 0)
        if trust_score >= rule_value:
            return RuleEvaluationResult(
                rule_name="min_trust_score",
                passed=True,
                message=f"Trust score {trust_score} meets the minimum required of {rule_value}.",
                severity=Severity.INFO,
                details={"trust_score": trust_score, "required": rule_value},
            )
        else:
            return RuleEvaluationResult(
                rule_name="min_trust_score",
                passed=False,
                message=f"Trust score {trust_score} does not meet the minimum required of {rule_value}.",
                severity=Severity.ERROR,
                details={"trust_score": trust_score, "required": rule_value},
            )


class NoRootExecutionEvaluator(BaseRuleEvaluator):
    """Evaluates no_root_execution rule.

    Checks if container runs as non-root user.
    """

    def evaluate(
        self,
        rule_value: bool,
        findings_data: Dict[str, Any],
    ) -> RuleEvaluationResult:
        """Check root execution status.

        Args:
            rule_value: Whether to block root execution (True/False)
            findings_data: Contains runs_as_root flag

        Returns:
            RuleEvaluationResult
        """
        runs_as_root = findings_data.get("runs_as_root", False)
        if rule_value and runs_as_root:
            return RuleEvaluationResult(rule_name="no_root_execution", passed=False, message="Container runs as root (not allowed).", severity=Severity.ERROR, details={"runs_as_root": runs_as_root})
        else:
            return RuleEvaluationResult(rule_name="no_root_execution", passed=True, message="Container runs as non-root (OK).", severity=Severity.INFO, details={"runs_as_root": runs_as_root})


class RuleEvaluatorFactory:
    """Factory for creating rule evaluators."""

    EVALUATORS = {
        "max_critical_vulnerabilities": MaxCriticalVulnerabilitiesEvaluator,
        "max_high_vulnerabilities": MaxHighVulnerabilitiesEvaluator,
        "sbom_required": SbomRequiredEvaluator,
        "min_trust_score": MinTrustScoreEvaluator,
        "no_root_execution": NoRootExecutionEvaluator,
    }

    @classmethod
    def get_evaluator(cls, rule_name: str) -> Optional[BaseRuleEvaluator]:
        """Get evaluator for a rule.

        Args:
            rule_name: Name of the rule

        Returns:
            Evaluator instance or None if rule not found
        """
        # TODO: Log warning if rule not found
        evaluator_class = cls.EVALUATORS.get(rule_name)
        if evaluator_class:
            return evaluator_class()
        else:
            return None

    @classmethod
    def supports_rule(cls, rule_name: str) -> bool:
        """Check if rule is supported.

        Args:
            rule_name: Name of the rule

        Returns:
            True if evaluator exists for this rule
        """
        if rule_name in cls.EVALUATORS:
            return True
        else:
            return False
