# -*- coding: utf-8 -*-
"""Location: ./plugins/policy_templates/test_runner.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Security Team

Template test runner for the Policy Templates Library plugin.

Executes the test cases embedded in a PolicyTemplate and produces a TestReport
summarising which tests passed and which failed.  Test evaluation is performed
by a mock evaluator that simulates policy decisions based on the template's
rendered policy content combined with the test's input context — no live policy
engine is required.
"""

# Standard
import logging
import re
from typing import Any, Dict, Optional

# Local
from .instantiator import TemplateInstantiator
from .models import (
    InstantiatedPolicy,
    PolicyEngine,
    PolicyTemplate,
    TestExpectation,
    TestGiven,
    TestReport,
    TestResult,
)

logger = logging.getLogger(__name__)


class TemplateTestRunner:
    """Runs the embedded test cases for a PolicyTemplate.

    Uses a lightweight mock evaluator to derive an allow/deny decision for
    each test case without requiring a real Cedar or OPA engine.  The mock
    evaluator parses ALLOW and DENY patterns from the rendered Cedar or OPA
    policy text and matches them against the test's principal, action, and
    resource fields.

    Typical usage::

        runner = TemplateTestRunner()
        report = runner.run_tests(template)
        if not report.success:
            for r in report.results:
                if not r.passed:
                    print(r.test_name, r.reason)
    """

    def __init__(self, instantiator: Optional[TemplateInstantiator] = None) -> None:
        """Initialize the test runner with an optional instantiator.

        Args:
            instantiator: Instantiator used to render the template before
                evaluation.  A default TemplateInstantiator is created when
                None is supplied.
        """
        self._instantiator = instantiator or TemplateInstantiator(validate_on_instantiate=False)

    def run_tests(self, template: PolicyTemplate, parameters: Optional[Dict[str, Any]] = None) -> TestReport:
        """Execute all test cases embedded in the template.

        Instantiates the template (using defaults for any un-supplied parameters)
        then evaluates each test case against the rendered policy using the mock
        evaluator.

        Args:
            template: The PolicyTemplate whose tests should be executed.
            parameters: Optional parameter overrides for instantiation.

        Returns:
            TestReport containing per-case results and summary statistics.
        """
        tests = template.spec.tests
        if not tests:
            logger.debug("Template '%s' has no test cases", template.metadata.name)
            return TestReport(
                template_name=template.metadata.name,
                total=0,
                passed=0,
                failed=0,
                results=[],
            )

        # Instantiate the template to obtain the rendered policy body
        try:
            policy = self._instantiator.instantiate(template, parameters or {})
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Could not instantiate template '%s' for testing: %s", template.metadata.name, exc)
            # Fall back to an unrendered policy so tests can still run
            policy = InstantiatedPolicy(
                template_name=template.metadata.name,
                template_version=template.metadata.version,
                engine=template.spec.engine,
                parameters={},
                policy_content=template.spec.template,
            )

        results = []
        passed = 0
        for test in tests:
            result = self._evaluate_test(test.name, test.given, test.expect, policy)
            results.append(result)
            if result.passed:
                passed += 1

        return TestReport(
            template_name=template.metadata.name,
            total=len(tests),
            passed=passed,
            failed=len(tests) - passed,
            results=results,
        )

    # ------------------------------------------------------------------
    # Private: mock evaluation logic
    # ------------------------------------------------------------------

    def _evaluate_test(
        self,
        test_name: str,
        given: TestGiven,
        expect: TestExpectation,
        policy: InstantiatedPolicy,
    ) -> TestResult:
        """Evaluate a single test case and return a TestResult.

        Args:
            test_name: Human-readable name of the test case.
            given: Input context (principal, action, resource) for evaluation.
            expect: Expected policy decision for this test.
            policy: Rendered policy to evaluate against.

        Returns:
            TestResult indicating whether the test passed.
        """
        actual = self._mock_evaluate(given, policy)
        passed = actual == expect
        reason = (
            f"Expected '{expect.value}', got '{actual.value}'"
            if not passed
            else f"Policy correctly returned '{actual.value}'"
        )
        return TestResult(
            test_name=test_name,
            passed=passed,
            expected=expect,
            actual=actual,
            reason=reason,
        )

    def _mock_evaluate(self, given: TestGiven, policy: InstantiatedPolicy) -> TestExpectation:
        """Simulate a policy decision for the given test context.

        The mock evaluator uses heuristic pattern matching against the rendered
        policy content to derive a decision without a live engine.

        For Cedar policies:
        - Looks for ``permit(...)`` or ``forbid(...)`` blocks and checks whether
          the principal role and action appear together in a permit/forbid clause.
        - Honour ``when { principal.has_X == true }`` conditions against the
          principal attributes provided in the test.

        For OPA policies:
        - Looks for ``allow`` and ``deny`` assignments.

        The result falls back to ``deny`` (secure default) when the evaluation
        is inconclusive.

        Args:
            given: Test input containing principal attributes, action, resource.
            policy: Instantiated policy containing the rendered policy text.

        Returns:
            TestExpectation.ALLOW or TestExpectation.DENY.
        """
        content = policy.policy_content
        engine = policy.engine
        principal = given.principal
        action = given.action
        resource = given.resource

        if engine == PolicyEngine.CEDAR:
            return self._eval_cedar(content, principal, action, resource)
        if engine == PolicyEngine.OPA:
            return self._eval_opa(content, principal, action, resource)
        # Native / unknown — simple keyword heuristic
        return self._eval_simple(content, principal, action, resource)

    def _eval_cedar(self, content: str, principal: Any, action: str, resource: str) -> TestExpectation:
        """Mock evaluation for Cedar policy syntax.

        Scans for ``permit`` and ``forbid`` statements and applies simple
        role/action matching.  Condition blocks (``when { ... }``) are
        evaluated for common boolean attribute patterns.

        Args:
            content: Rendered Cedar policy text.
            principal: TestPrincipal with role and extra attributes.
            action: Requested action string.
            resource: Target resource identifier.

        Returns:
            TestExpectation.ALLOW if a permit clause matches, DENY otherwise.
        """
        role = getattr(principal, "role", "")
        attrs = {k: v for k, v in (principal.model_extra or {}).items()}
        # Also check model fields beyond role
        for field_name in principal.model_fields_set:
            if field_name != "role":
                attrs[field_name] = getattr(principal, field_name)

        # Find all permit/forbid blocks
        permit_pattern = re.compile(r"permit\s*\(([^)]*)\)(\s*when\s*\{([^}]*)\})?", re.DOTALL | re.IGNORECASE)
        forbid_pattern = re.compile(r"forbid\s*\(([^)]*)\)(\s*when\s*\{([^}]*)\})?", re.DOTALL | re.IGNORECASE)

        # Check forbid first (deny-wins on overlap)
        for match in forbid_pattern.finditer(content):
            clause = match.group(1)
            when_block = match.group(3) or ""
            if self._cedar_clause_matches(clause, role, action, resource) and self._cedar_when_matches(when_block, attrs):
                return TestExpectation.DENY

        # Check permit
        for match in permit_pattern.finditer(content):
            clause = match.group(1)
            when_block = match.group(3) or ""
            if self._cedar_clause_matches(clause, role, action, resource) and self._cedar_when_matches(when_block, attrs):
                return TestExpectation.ALLOW

        return TestExpectation.DENY

    @staticmethod
    def _cedar_clause_matches(clause: str, role: str, action: str, resource: str) -> bool:
        """Check whether a Cedar clause body matches the given role/action/resource.

        Args:
            clause: The text inside a ``permit(...)`` or ``forbid(...)`` block.
            role: Principal role to match.
            action: Action string to match.
            resource: Resource identifier to match.

        Returns:
            True when the clause is consistent with the given inputs.
        """
        # All resources match when clause is empty or uses "action, resource"
        if not clause.strip():
            return True

        # Check principal: role must appear (quoted or as identifier)
        role_quoted = f'"{role}"'
        if role and role_quoted not in clause and role not in clause:
            return False

        # Check action — it should appear somewhere in the clause
        action_quoted = f'"{action}"'
        if action and action_quoted not in clause and action not in clause:
            return False

        return True

    @staticmethod
    def _cedar_when_matches(when_block: str, attrs: Dict[str, Any]) -> bool:
        """Evaluate a Cedar ``when { ... }`` condition block against principal attributes.

        Recognises the pattern ``principal.attr_name == value`` and evaluates it
        against the provided attribute dictionary.

        Args:
            when_block: The text inside a Cedar ``when { ... }`` block.
            attrs: Principal attribute dictionary.

        Returns:
            True when all conditions are satisfied (or the block is empty).
        """
        if not when_block.strip():
            return True

        # Parse simple boolean equality checks: principal.attr == value
        cond_pattern = re.compile(r"principal\.(\w+)\s*==\s*(true|false|\"[^\"]*\"|\d+)", re.IGNORECASE)
        for m in cond_pattern.finditer(when_block):
            attr_name = m.group(1)
            raw_value = m.group(2).strip()

            # Determine expected value
            if raw_value.lower() == "true":
                expected: Any = True
            elif raw_value.lower() == "false":
                expected = False
            elif raw_value.startswith('"') and raw_value.endswith('"'):
                expected = raw_value[1:-1]
            else:
                try:
                    expected = int(raw_value)
                except ValueError:
                    expected = raw_value

            actual = attrs.get(attr_name)
            if actual != expected:
                return False

        return True

    @staticmethod
    def _eval_opa(content: str, principal: Any, action: str, resource: str) -> TestExpectation:
        """Mock evaluation for OPA/Rego policy syntax.

        Checks for ``allow = true`` or ``deny = true`` literal assignments in
        the rendered Rego policy.  If the policy contains ``allow`` it returns
        ALLOW, otherwise DENY.

        Args:
            content: Rendered Rego policy text.
            principal: TestPrincipal (not used in this simple heuristic).
            action: Requested action string.
            resource: Target resource identifier.

        Returns:
            TestExpectation derived from the OPA policy structure.
        """
        _ = (principal, action, resource)  # unused in simple heuristic
        if re.search(r"\bdefault\s+allow\s*=\s*true\b", content, re.IGNORECASE):
            return TestExpectation.ALLOW
        if re.search(r"\ballow\s*=\s*true\b", content) or re.search(r"\ballow\s*\{", content):
            return TestExpectation.ALLOW
        return TestExpectation.DENY

    @staticmethod
    def _eval_simple(content: str, principal: Any, action: str, resource: str) -> TestExpectation:
        """Simple heuristic evaluation for unknown engine policies.

        Args:
            content: Rendered policy text.
            principal: TestPrincipal.
            action: Requested action string.
            resource: Target resource identifier.

        Returns:
            TestExpectation based on keyword presence in the policy body.
        """
        _ = (principal, action, resource)
        allow_keywords = ["allow", "permit", "grant"]
        for kw in allow_keywords:
            if kw in content.lower():
                return TestExpectation.ALLOW
        return TestExpectation.DENY
