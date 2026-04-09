"""
evaluator.py - THE ORCHESTRATOR

Coordinates the policy evaluation process:
1. Takes an assessment (scan results) and a policy
2. Extracts findings data from assessment
3. Loops through each rule in the policy
4. Gets appropriate rule evaluator from factory
5. Runs each rule evaluator
6. Collects results
7. Applies waivers
8. Calculates overall compliance score
9. Returns PolicyEvaluationResult
"""

# Standard
from typing import Any, Dict, List, Optional

# Local
from .models import Policy, PolicyEvaluationResult, RuleEvaluationResult, Severity
from .rules import RuleEvaluatorFactory
from .waivers import WaiverManager


class PolicyEvaluator:
    """Orchestrates policy evaluation against assessment findings."""

    def __init__(self, waiver_manager: Optional[WaiverManager] = None):
        """Initialize the evaluator.

        Args:
            waiver_manager: Optional WaiverManager for handling waivers.
                           If None, no waivers will be applied.
        """
        self.waiver_manager = waiver_manager if waiver_manager is not None else WaiverManager(storage_file=None)
        self.factory = RuleEvaluatorFactory()

    def evaluate(
        self,
        assessment: Dict[str, Any],
        policy: Policy,
        server_id: Optional[str] = None,
    ) -> PolicyEvaluationResult:
        """Evaluate an assessment against a policy.

        Args:
            assessment: Assessment/scan results with findings data
            policy: Policy object containing rules to evaluate
            server_id: Optional server ID for waiver checking

        Returns:
            PolicyEvaluationResult with scores and details
        """
        rule_results: List[RuleEvaluationResult] = []
        waivers_applied: List[str] = []

        # Extract findings data - support various assessment structures
        findings_data = self._extract_findings(assessment)

        # Evaluate each rule in the policy
        for rule_name, rule_value in policy.rules.items():
            # Get the evaluator for this rule
            evaluator = self.factory.get_evaluator(rule_name)

            if evaluator is None:
                # Rule not supported, mark as skipped
                rule_result = RuleEvaluationResult(
                    rule_name=rule_name, passed=False, message=f"Rule evaluator not found: {rule_name}", severity=Severity.WARNING, details={"error": "unsupported_rule"}
                )
            else:
                # Run the rule evaluator
                rule_result = evaluator.evaluate(rule_value, findings_data)

                # Check for waivers if rule failed and server_id provided
                if not rule_result.passed and server_id:
                    waiver = self.waiver_manager.get_active_waiver(server_id, rule_name)
                    if waiver:
                        rule_result.waived = True
                        rule_result.waiver_id = waiver.get("id")
                        waivers_applied.append(waiver.get("id", ""))

            rule_results.append(rule_result)

        # Calculate compliance score
        score = self._calculate_score(rule_results)

        # Determine compliance status
        compliance_status = self._determine_status(rule_results)

        # Return result
        return PolicyEvaluationResult(
            policy_name=policy.name,
            passed=all(r.passed or r.waived for r in rule_results),
            score=score,
            rule_results=rule_results,
            compliance_status=compliance_status,
            waivers_applied=waivers_applied,
        )

    def _extract_findings(self, assessment: Dict[str, Any]) -> Dict[str, Any]:
        """Extract findings data from various assessment formats.

        Ensures the returned dict has 'summary' key with error_count/warning_count
        for rule evaluators to use.

        Args:
            assessment: Assessment object with findings

        Returns:
            Dictionary with findings data including summary
        """
        # If assessment already has summary (from CLI scan), use it as-is
        if "summary" in assessment and "error_count" in assessment.get("summary", {}):
            return assessment

        # Unwrap nested findings/results key
        for key in ("findings", "results"):
            nested = assessment.get(key)
            if isinstance(nested, dict):
                return nested

        # Fallback: use assessment as-is
        return assessment

    def _calculate_score(self, rule_results: List[RuleEvaluationResult]) -> float:
        """Calculate overall compliance score (0-100).

        Scoring logic:
        - Passed rules: 100% of weight
        - Waived rules: 100% of weight (exception granted)
        - Failed rules: 0% of weight

        Args:
            rule_results: List of rule evaluation results

        Returns:
            Compliance score 0-100
        """
        if not rule_results:
            return 100.0

        passed_count = sum(1 for r in rule_results if r.passed or r.waived)
        total_count = len(rule_results)

        score = (passed_count / total_count) * 100.0
        return round(score, 2)

    def _determine_status(self, rule_results: List[RuleEvaluationResult]) -> str:
        """Determine overall compliance status.

        Rules:
        - PASSED: All rules passed
        - WARNED: All rules passed or waived, but some warnings exist
        - BLOCKED: At least one error severity rule failed

        Args:
            rule_results: List of rule evaluation results

        Returns:
            Compliance status string
        """
        # Check for unwaived errors
        errors = [r for r in rule_results if not r.passed and not r.waived and r.severity == Severity.ERROR]
        if errors:
            return "BLOCKED"

        # Check for warnings
        warnings = [r for r in rule_results if r.severity == Severity.WARNING]
        if warnings:
            return "WARNED"

        return "PASSED"
