"""
test_evaluator.py - Unit tests for policy evaluator

Tests the orchestrator that coordinates policy evaluation,
scoring, and decision making.
"""

# Third-Party
import pytest
# Local
from ..evaluator import PolicyEvaluator
from ..models import Policy
from ..waivers import WaiverManager


def _make_waiver_manager() -> WaiverManager:
    """Create an in-memory-only WaiverManager for tests."""
    return WaiverManager(storage_file=None)


@pytest.fixture
def sample_policy():
    """Create a sample policy for testing."""
    return Policy(
        name="Test Policy",
        environment="dev",
        rules={
            "max_critical_vulnerabilities": 5,
            "max_high_vulnerabilities": 10,
            "sbom_required": True,
            "min_trust_score": 70,
            "no_root_execution": True,
        },
    )


@pytest.fixture
def sample_assessment():
    """Create a sample assessment (scan results) for testing."""
    return {
        "findings": {
            "summary": {
                "error_count": 2,
                "warning_count": 5,
            },
            "sbom_present": True,
            "trust_score": 85,
            "runs_as_root": False,
        }
    }


@pytest.fixture
def failing_assessment():
    """Create an assessment with failing rules."""
    return {
        "findings": {
            "summary": {
                "error_count": 10,  # Exceeds limit of 5
                "warning_count": 15,  # Exceeds limit of 10
            },
            "sbom_present": False,  # Required but missing
            "trust_score": 50,  # Below minimum of 70
            "runs_as_root": True,  # Not allowed
        }
    }


class TestPolicyEvaluator:
    """Test policy evaluator orchestrator."""

    def test_evaluate_all_pass(self, sample_policy, sample_assessment):
        """Test evaluation when all rules pass."""
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(sample_assessment, sample_policy)

        assert result.passed is True
        assert result.compliance_status == "PASSED"
        assert result.score == 100.0
        assert all(r.passed for r in result.rule_results)

    def test_evaluate_all_fail(self, sample_policy, failing_assessment):
        """Test evaluation when all rules fail."""
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(failing_assessment, sample_policy)

        assert result.passed is False
        assert result.compliance_status == "BLOCKED"
        assert result.score == 0.0
        assert not any(r.passed for r in result.rule_results)

    def test_evaluate_partial_fail(self, sample_policy):
        """Test evaluation with mixed pass/fail rules."""
        evaluator = PolicyEvaluator()
        assessment = {
            "findings": {
                "summary": {
                    "error_count": 10,  # Fails (exceeds 5)
                    "warning_count": 5,  # Passes (within 10)
                },
                "sbom_present": True,  # Passes
                "trust_score": 85,  # Passes
                "runs_as_root": False,  # Passes
            }
        }
        result = evaluator.evaluate(assessment, sample_policy)

        assert result.passed is False
        assert result.score == 80.0  # 4 of 5 rules pass
        # 1 failed rule that is not waived
        assert sum(1 for r in result.rule_results if not r.passed and not r.waived) == 1

    def test_score_calculation(self, sample_policy):
        """Test compliance score calculation."""
        evaluator = PolicyEvaluator()

        # 3 rules pass, 2 rules fail = 60%
        assessment = {
            "findings": {
                "summary": {
                    "error_count": 10,  # Fails
                    "warning_count": 20,  # Fails
                },
                "sbom_present": True,  # Passes
                "trust_score": 85,  # Passes
                "runs_as_root": False,  # Passes
            }
        }
        result = evaluator.evaluate(assessment, sample_policy)
        assert result.score == 60.0

    def test_status_determination_passed(self, sample_policy, sample_assessment):
        """Test status is PASSED when all rules pass."""
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(sample_assessment, sample_policy)
        assert result.compliance_status == "PASSED"

    def test_status_determination_blocked(self, sample_policy, failing_assessment):
        """Test status is BLOCKED when error-level rules fail."""
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(failing_assessment, sample_policy)
        assert result.compliance_status == "BLOCKED"

    def test_waiver_overrides_failure(self, sample_policy):
        """Test that active waiver allows failed rule to pass."""
        waiver_manager = _make_waiver_manager()
        evaluator = PolicyEvaluator(waiver_manager)

        # Create and approve a waiver for max_critical_vulnerabilities
        waiver = waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="max_critical_vulnerabilities",
            reason="Known issue",
            requested_by="admin",
            approved=True,
            approved_by="security",
        )

        assessment = {
            "findings": {
                "summary": {
                    "error_count": 10,  # Exceeds limit
                    "warning_count": 5,
                },
                "sbom_present": True,
                "trust_score": 85,
                "runs_as_root": False,
            }
        }

        result = evaluator.evaluate(assessment, sample_policy, server_id="server-1")

        # Overall pass should be true because waiver covers the failure
        assert result.passed is True

        # Find the waived rule
        critical_rule = next(r for r in result.rule_results if r.rule_name == "max_critical_vulnerabilities")
        assert critical_rule.waived is True
        assert critical_rule.waiver_id == waiver["id"]
        assert waiver["id"] in result.waivers_applied

    def test_findings_extraction(self):
        """Test extraction of findings from various assessment structures."""
        evaluator = PolicyEvaluator()
        policy = Policy(
            name="Test",
            environment="dev",
            rules={"max_critical_vulnerabilities": 10},
        )

        # Test with 'findings' key
        assessment = {"findings": {"summary": {"error_count": 5}}}
        result = evaluator.evaluate(assessment, policy)
        assert result.passed is True

        # Test with 'results' key
        assessment = {"results": {"summary": {"error_count": 5}}}
        result = evaluator.evaluate(assessment, policy)
        assert result.passed is True

        # Test with direct structure
        assessment = {"summary": {"error_count": 5}}
        result = evaluator.evaluate(assessment, policy)
        assert result.passed is True

    def test_unsupported_rule_handling(self):
        """Test that unsupported rules are handled gracefully."""
        evaluator = PolicyEvaluator()
        policy = Policy(
            name="Test",
            environment="dev",
            rules={"unsupported_rule": "some_value"},
        )
        assessment = {"findings": {}}

        result = evaluator.evaluate(assessment, policy)

        # Should have one result for the unsupported rule
        assert len(result.rule_results) == 1
        unsupported_result = result.rule_results[0]
        assert unsupported_result.rule_name == "unsupported_rule"
        assert unsupported_result.passed is False
        assert "unsupported_rule" in unsupported_result.message.lower()

    def test_result_contains_all_data(self, sample_policy, sample_assessment):
        """Test that evaluation result contains all required fields."""
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(sample_assessment, sample_policy, server_id="server-1")

        assert result.policy_name == "Test Policy"
        assert isinstance(result.passed, bool)
        assert isinstance(result.score, float)
        assert isinstance(result.rule_results, list)
        assert result.compliance_status in ["PASSED", "BLOCKED", "WARNED"]
        assert isinstance(result.waivers_applied, list)


class TestPolicyCreatedAt:
    """Test that the Policy model handles created_at correctly."""

    def test_policy_created_at_defaults_to_none(self):
        """Test that created_at defaults to None when not provided."""
        policy = Policy(name="Test", environment="dev", rules={})
        assert policy.created_at is None

    def test_policy_created_at_can_be_set(self):
        """Test that created_at can be set on creation."""
        # Standard
        from datetime import datetime

        ts = datetime(2026, 3, 10, 12, 0, 0)
        policy = Policy(name="Test", environment="dev", rules={}, created_at=ts)
        assert policy.created_at == ts

    def test_policy_created_at_preserved_through_evaluation(self, sample_policy, sample_assessment):
        """Test that created_at on a policy is not mutated during evaluation."""
        # Standard
        from datetime import datetime

        ts = datetime(2026, 1, 1, 0, 0, 0)
        sample_policy.created_at = ts

        evaluator = PolicyEvaluator()
        evaluator.evaluate(sample_assessment, sample_policy)

        assert sample_policy.created_at == ts
