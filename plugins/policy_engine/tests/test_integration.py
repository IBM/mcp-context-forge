"""
test_integration.py - Integration tests for policy evaluation

Tests the full evaluation flow with all components working together:
- PolicyEvaluator orchestrating rule evaluation
- Multiple rules evaluated in a single policy
- Waiver application and exemptions
- Compliance scoring
- Complex assessment scenarios
"""

# Standard
from datetime import datetime, timedelta
# Local
from ..evaluator import PolicyEvaluator
from ..models import Policy, Severity
from ..waivers import WaiverManager


class TestPolicyEvaluationIntegration:
    """Integration tests for full policy evaluation flow."""

    def test_evaluate_single_rule_pass(self):
        """Test evaluating a single rule that passes."""
        evaluator = PolicyEvaluator()
        assessment = {"summary": {"error_count": 2}}
        policy = Policy(name="security_policy", environment="production", rules={"max_critical_vulnerabilities": 5})

        result = evaluator.evaluate(assessment, policy)

        assert result.passed is True
        assert result.policy_name == "security_policy"
        assert len(result.rule_results) == 1
        assert result.rule_results[0].passed is True

    def test_evaluate_single_rule_fail(self):
        """Test evaluating a single rule that fails."""
        evaluator = PolicyEvaluator()
        assessment = {"summary": {"error_count": 10}}
        policy = Policy(name="security_policy", environment="production", rules={"max_critical_vulnerabilities": 5})

        result = evaluator.evaluate(assessment, policy)

        assert result.passed is False
        assert result.rule_results[0].passed is False
        assert result.compliance_status == "BLOCKED"

    def test_evaluate_multiple_rules_all_pass(self):
        """Test evaluating multiple rules that all pass."""
        evaluator = PolicyEvaluator()
        assessment = {
            "summary": {"error_count": 2, "warning_count": 5},
            "sbom_present": True,
            "trust_score": 85,
            "runs_as_root": False,
        }
        policy = Policy(
            name="comprehensive_policy",
            environment="production",
            rules={
                "max_critical_vulnerabilities": 5,
                "max_high_vulnerabilities": 10,
                "sbom_required": True,
                "min_trust_score": 70,
                "no_root_execution": True,
            },
        )

        result = evaluator.evaluate(assessment, policy)

        assert result.passed is True
        assert len(result.rule_results) == 5
        assert all(r.passed for r in result.rule_results)
        assert result.score == 100.0

    def test_evaluate_multiple_rules_mixed_pass_fail(self):
        """Test evaluating multiple rules with mixed pass/fail results."""
        evaluator = PolicyEvaluator()
        assessment = {
            "summary": {"error_count": 10, "warning_count": 5},
            "sbom_present": False,
            "trust_score": 45,
            "runs_as_root": False,
        }
        policy = Policy(
            name="strict_policy",
            environment="production",
            rules={
                "max_critical_vulnerabilities": 5,  # FAIL: 10 > 5
                "max_high_vulnerabilities": 10,  # PASS: 5 <= 10
                "sbom_required": True,  # FAIL: not present
                "min_trust_score": 70,  # FAIL: 45 < 70
                "no_root_execution": True,  # PASS: not root
            },
        )

        result = evaluator.evaluate(assessment, policy)

        assert result.passed is False
        assert result.compliance_status == "BLOCKED"
        assert sum(1 for r in result.rule_results if r.passed) == 2
        assert sum(1 for r in result.rule_results if not r.passed) == 3

    def test_score_calculation_all_pass(self):
        """Test that score is 100 when all rules pass."""
        evaluator = PolicyEvaluator()
        assessment = {
            "summary": {"error_count": 0, "warning_count": 0},
            "sbom_present": True,
            "trust_score": 100,
            "runs_as_root": False,
        }
        policy = Policy(
            name="policy",
            environment="production",
            rules={
                "max_critical_vulnerabilities": 5,
                "max_high_vulnerabilities": 10,
                "sbom_required": True,
                "min_trust_score": 70,
                "no_root_execution": True,
            },
        )

        result = evaluator.evaluate(assessment, policy)

        assert result.score == 100.0

    def test_score_calculation_partial_pass(self):
        """Test that score is calculated correctly for partial passes."""
        evaluator = PolicyEvaluator()
        assessment = {
            "summary": {"error_count": 10, "warning_count": 5},
            "sbom_present": True,
            "trust_score": 85,
            "runs_as_root": False,
        }
        policy = Policy(
            name="policy",
            environment="production",
            rules={
                "max_critical_vulnerabilities": 5,  # FAIL
                "max_high_vulnerabilities": 10,  # PASS
                "sbom_required": True,  # PASS
                "min_trust_score": 70,  # PASS
                "no_root_execution": True,  # PASS
            },
        )

        result = evaluator.evaluate(assessment, policy)

        assert result.score == 80.0  # 4 out of 5 rules pass

    def test_unsupported_rule_handling(self):
        """Test that unsupported rules are marked with warning."""
        evaluator = PolicyEvaluator()
        assessment = {"summary": {"error_count": 2}}
        policy = Policy(
            name="policy",
            environment="production",
            rules={
                "max_critical_vulnerabilities": 5,
                "unsupported_rule": "some_value",
            },
        )

        result = evaluator.evaluate(assessment, policy)

        assert len(result.rule_results) == 2
        unsupported = [r for r in result.rule_results if r.rule_name == "unsupported_rule"][0]
        assert unsupported.passed is False
        assert unsupported.severity == Severity.WARNING
        assert "not found" in unsupported.message

    def test_empty_assessment_handling(self):
        """Test evaluation with minimal assessment data."""
        evaluator = PolicyEvaluator()
        assessment = {}
        policy = Policy(
            name="policy",
            environment="production",
            rules={
                "max_critical_vulnerabilities": 0,
                "sbom_required": True,
                "min_trust_score": 50,
            },
        )

        result = evaluator.evaluate(assessment, policy)

        # All rules should fail or pass based on defaults
        assert isinstance(result.score, float)
        assert 0 <= result.score <= 100

    def test_various_assessment_structures(self):
        """Test evaluation with different assessment data structures."""
        evaluator = PolicyEvaluator()

        # Assessment with nested structure
        assessment = {"scan_results": {"summary": {"error_count": 1, "warning_count": 2}}, "sbom": {"present": True}, "metadata": {"trust_score": 90}}
        policy = Policy(
            name="policy",
            environment="production",
            rules={
                "max_critical_vulnerabilities": 5,
                "sbom_required": True,
            },
        )

        result = evaluator.evaluate(assessment, policy)
        assert len(result.rule_results) == 2


class TestPolicyEvaluationWithWaivers:
    """Integration tests for policy evaluation with waiver application."""

    def test_waiver_changes_failed_rule_to_waived(self):
        """Test that active waiver marks a failed rule as waived."""
        waiver_manager = WaiverManager(storage_file=None)
        evaluator = PolicyEvaluator(waiver_manager=waiver_manager)

        # Create an active waiver for max_critical_vulnerabilities
        waiver_manager.create_waiver(
            server_id="test_server",
            rule_name="max_critical_vulnerabilities",
            reason="Temporary exception for testing",
            requested_by="user@example.com",
            duration_days=7,
            approved=True,
            approved_by="admin@example.com",
        )

        assessment = {"summary": {"error_count": 10}}
        policy = Policy(name="policy", environment="production", rules={"max_critical_vulnerabilities": 5})

        result = evaluator.evaluate(assessment, policy, server_id="test_server")

        assert result.rule_results[0].passed is False
        assert result.rule_results[0].waived is True
        assert result.passed is True  # Overall passes due to waiver
        assert len(result.waivers_applied) == 1

    def test_expired_waiver_not_applied(self):
        """Test that expired waivers are not applied."""
        waiver_manager = WaiverManager(storage_file=None)
        evaluator = PolicyEvaluator(waiver_manager=waiver_manager)

        # Create a waiver and manually expire it by setting it directly
        waiver_manager.create_waiver(
            server_id="test_server",
            rule_name="max_critical_vulnerabilities",
            reason="Temporary exception",
            requested_by="user@example.com",
            duration_days=1,
            approved=True,
            approved_by="admin@example.com",
        )

        # Manually expire the waiver by modifying its expiration
        waiver_id = list(waiver_manager._waivers.keys())[0]
        waiver_manager._waivers[waiver_id]["expires_at"] = datetime.now() - timedelta(days=1)

        assessment = {"summary": {"error_count": 10}}
        policy = Policy(name="policy", environment="production", rules={"max_critical_vulnerabilities": 5})

        result = evaluator.evaluate(assessment, policy, server_id="test_server")

        assert result.rule_results[0].passed is False
        assert result.rule_results[0].waived is False
        assert result.passed is False
        assert len(result.waivers_applied) == 0

    def test_multiple_waivers_applied(self):
        """Test that multiple waivers can be applied to one evaluation."""
        waiver_manager = WaiverManager(storage_file=None)
        evaluator = PolicyEvaluator(waiver_manager=waiver_manager)

        # Create waivers for two different rules
        waiver_manager.create_waiver(
            server_id="test_server",
            rule_name="max_critical_vulnerabilities",
            reason="Waiver 1",
            requested_by="user@example.com",
            duration_days=7,
            approved=True,
            approved_by="admin@example.com",
        )
        waiver_manager.create_waiver(
            server_id="test_server",
            rule_name="sbom_required",
            reason="Waiver 2",
            requested_by="user@example.com",
            duration_days=7,
            approved=True,
            approved_by="admin@example.com",
        )

        assessment = {
            "summary": {"error_count": 10},
            "sbom_present": False,
        }
        policy = Policy(
            name="policy",
            environment="production",
            rules={
                "max_critical_vulnerabilities": 5,
                "sbom_required": True,
            },
        )

        result = evaluator.evaluate(assessment, policy, server_id="test_server")

        assert result.passed is True
        assert len(result.waivers_applied) == 2
        assert all(r.waived for r in result.rule_results if not r.passed)

    def test_waiver_without_server_id_not_applied(self):
        """Test that waivers are not applied when server_id is not provided."""
        waiver_manager = WaiverManager(storage_file=None)
        evaluator = PolicyEvaluator(waiver_manager=waiver_manager)

        waiver_manager.create_waiver(
            server_id="test_server",
            rule_name="max_critical_vulnerabilities",
            reason="Test waiver",
            requested_by="user@example.com",
            duration_days=7,
            approved=True,
            approved_by="admin@example.com",
        )

        assessment = {"summary": {"error_count": 10}}
        policy = Policy(name="policy", environment="production", rules={"max_critical_vulnerabilities": 5})

        # Evaluate without providing server_id
        result = evaluator.evaluate(assessment, policy, server_id=None)

        assert result.rule_results[0].waived is False
        assert len(result.waivers_applied) == 0


class TestEnvironmentSpecificEvaluation:
    """Test policy evaluation in different environments."""

    def test_production_policy_strict(self):
        """Test production policies are strict."""
        evaluator = PolicyEvaluator()
        assessment = {
            "summary": {"error_count": 0, "warning_count": 0},
            "sbom_present": True,
            "trust_score": 95,
            "runs_as_root": False,
        }

        prod_policy = Policy(
            name="prod_security",
            environment="production",
            rules={
                "max_critical_vulnerabilities": 0,
                "max_high_vulnerabilities": 5,
                "sbom_required": True,
                "min_trust_score": 90,
                "no_root_execution": True,
            },
        )

        result = evaluator.evaluate(assessment, prod_policy)
        assert result.score == 100.0

    def test_staging_policy_moderate(self):
        """Test staging policies are moderately strict."""
        evaluator = PolicyEvaluator()
        assessment = {
            "summary": {"error_count": 2, "warning_count": 10},
            "sbom_present": True,
            "trust_score": 70,
            "runs_as_root": False,
        }

        staging_policy = Policy(
            name="staging_security",
            environment="staging",
            rules={
                "max_critical_vulnerabilities": 5,
                "max_high_vulnerabilities": 20,
                "sbom_required": True,
                "min_trust_score": 60,
                "no_root_execution": False,
            },
        )

        result = evaluator.evaluate(assessment, staging_policy)
        assert result.score == 100.0

    def test_dev_policy_permissive(self):
        """Test dev policies are permissive."""
        evaluator = PolicyEvaluator()
        assessment = {
            "summary": {"error_count": 10, "warning_count": 20},
            "sbom_present": False,
            "trust_score": 50,
            "runs_as_root": True,
        }

        dev_policy = Policy(
            name="dev_security",
            environment="dev",
            rules={
                "max_critical_vulnerabilities": 50,
                "max_high_vulnerabilities": 100,
                "sbom_required": False,
                "min_trust_score": 30,
                "no_root_execution": False,
            },
        )

        result = evaluator.evaluate(assessment, dev_policy)
        assert result.score == 100.0


class TestComplexAssessmentScenarios:
    """Test evaluation with complex real-world assessment scenarios."""

    def test_assessment_with_many_vulnerabilities(self):
        """Test assessment with high vulnerability counts."""
        evaluator = PolicyEvaluator()
        assessment = {
            "summary": {
                "error_count": 15,
                "warning_count": 45,
                "info_count": 200,
            },
            "sbom_present": True,
            "trust_score": 65,
            "runs_as_root": False,
        }

        policy = Policy(
            name="policy",
            environment="production",
            rules={
                "max_critical_vulnerabilities": 20,
                "max_high_vulnerabilities": 50,
                "sbom_required": True,
                "min_trust_score": 70,
                "no_root_execution": True,
            },
        )

        result = evaluator.evaluate(assessment, policy)

        # Passes critical/high counts and no_root, but fails min_trust_score
        assert result.score == 80.0  # 4 out of 5 pass

    def test_assessment_with_extreme_values(self):
        """Test with extreme boundary values."""
        evaluator = PolicyEvaluator()
        assessment = {
            "summary": {"error_count": 1000, "warning_count": 5000},
            "sbom_present": True,
            "trust_score": 0,
            "runs_as_root": True,
        }

        policy = Policy(
            name="policy",
            environment="production",
            rules={
                "max_critical_vulnerabilities": 10,
                "max_high_vulnerabilities": 100,
                "sbom_required": True,
                "min_trust_score": 50,
                "no_root_execution": True,
            },
        )

        result = evaluator.evaluate(assessment, policy)

        # Only sbom_required passes
        assert result.score == 20.0  # 1 out of 5 pass
        assert result.passed is False

    def test_assessment_missing_all_optional_fields(self):
        """Test assessment with only required fields."""
        evaluator = PolicyEvaluator()
        assessment = {"summary": {}}

        policy = Policy(
            name="minimal_policy",
            environment="production",
            rules={
                "max_critical_vulnerabilities": 0,
            },
        )

        result = evaluator.evaluate(assessment, policy)

        assert len(result.rule_results) == 1
        assert result.rule_results[0].passed is True

    def test_policy_with_single_rule_only(self):
        """Test minimal policy with single rule."""
        evaluator = PolicyEvaluator()
        assessment = {"trust_score": 75}

        policy = Policy(name="single_rule_policy", environment="production", rules={"min_trust_score": 70})

        result = evaluator.evaluate(assessment, policy)

        assert len(result.rule_results) == 1
        assert result.rule_results[0].passed is True
        assert result.score == 100.0


class TestComplianceStatusDetermination:
    """Test compliance status determination logic."""

    def test_status_passed_all_rules_pass(self):
        """Test PASSED status when all rules pass."""
        evaluator = PolicyEvaluator()
        assessment = {
            "summary": {"error_count": 0, "warning_count": 0},
            "sbom_present": True,
            "trust_score": 100,
            "runs_as_root": False,
        }
        policy = Policy(
            name="policy",
            environment="production",
            rules={
                "max_critical_vulnerabilities": 5,
                "sbom_required": True,
                "min_trust_score": 70,
                "no_root_execution": True,
            },
        )

        result = evaluator.evaluate(assessment, policy)
        assert result.compliance_status == "PASSED"

    def test_status_blocked_rules_fail(self):
        """Test BLOCKED status when rules fail."""
        evaluator = PolicyEvaluator()
        assessment = {
            "summary": {"error_count": 10, "warning_count": 0},
            "sbom_present": True,
            "trust_score": 100,
            "runs_as_root": False,
        }
        policy = Policy(
            name="policy",
            environment="production",
            rules={
                "max_critical_vulnerabilities": 5,
            },
        )

        result = evaluator.evaluate(assessment, policy)
        assert result.compliance_status == "BLOCKED"

    def test_status_indicated_in_result(self):
        """Test that compliance status is properly reflected."""
        evaluator = PolicyEvaluator()
        assessment = {
            "summary": {"error_count": 3, "warning_count": 8},
        }
        policy = Policy(
            name="policy",
            environment="production",
            rules={
                "max_critical_vulnerabilities": 5,
                "max_high_vulnerabilities": 10,
            },
        )

        result = evaluator.evaluate(assessment, policy)
        assert result.compliance_status in ["PASSED", "BLOCKED", "WARNED"]
