# -*- coding: utf-8 -*-
"""Unit tests for GuardrailPolicy evaluator.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

"""

# Third-Party
import pytest

# First-Party
from llmguardplugin.policy import GuardrailPolicy


@pytest.fixture
def policy():
    """Create a GuardrailPolicy instance."""
    return GuardrailPolicy()


class TestGuardrailPolicyShortCircuit:
    """Tests for short-circuit evaluation semantics."""

    def test_and_short_circuit_false_first(self, policy):
        """False and MissingFilter should return False without evaluating MissingFilter."""
        result = policy.evaluate("PromptInjection and MissingFilter", {"PromptInjection": {"is_valid": False}})
        assert result is False

    def test_or_short_circuit_true_first(self, policy):
        """True or MissingFilter should return True without evaluating MissingFilter."""
        result = policy.evaluate("PromptInjection or MissingFilter", {"PromptInjection": {"is_valid": True}})
        assert result is True

    def test_and_no_short_circuit_when_first_true(self, policy):
        """True and MissingFilter should fail because MissingFilter must be evaluated."""
        result = policy.evaluate("PromptInjection and MissingFilter", {"PromptInjection": {"is_valid": True}})
        assert result == "Invalid expression"

    def test_or_no_short_circuit_when_first_false(self, policy):
        """False or MissingFilter should fail because MissingFilter must be evaluated."""
        result = policy.evaluate("PromptInjection or MissingFilter", {"PromptInjection": {"is_valid": False}})
        assert result == "Invalid expression"


class TestGuardrailPolicyBooleanOps:
    """Tests for boolean operations."""

    def test_and_true_true(self, policy):
        """True and True should return True."""
        result = policy.evaluate("a and b", {"a": {"is_valid": True}, "b": {"is_valid": True}})
        assert result is True

    def test_and_true_false(self, policy):
        """True and False should return False."""
        result = policy.evaluate("a and b", {"a": {"is_valid": True}, "b": {"is_valid": False}})
        assert result is False

    def test_or_true_false(self, policy):
        """True or False should return True."""
        result = policy.evaluate("a or b", {"a": {"is_valid": True}, "b": {"is_valid": False}})
        assert result is True

    def test_or_false_false(self, policy):
        """False or False should return False."""
        result = policy.evaluate("a or b", {"a": {"is_valid": False}, "b": {"is_valid": False}})
        assert result is False

    def test_not_true(self, policy):
        """not True should return False."""
        result = policy.evaluate("not a", {"a": {"is_valid": True}})
        assert result is False

    def test_not_false(self, policy):
        """not False should return True."""
        result = policy.evaluate("not a", {"a": {"is_valid": False}})
        assert result is True

    def test_complex_nested_expression(self, policy):
        """Complex nested expression should evaluate correctly."""
        result = policy.evaluate("(a and b) or c", {"a": {"is_valid": True}, "b": {"is_valid": False}, "c": {"is_valid": True}})
        assert result is True

    def test_complex_nested_with_not(self, policy):
        """Complex nested expression with not should evaluate correctly."""
        result = policy.evaluate("(a or b) and not c", {"a": {"is_valid": False}, "b": {"is_valid": True}, "c": {"is_valid": False}})
        assert result is True


class TestGuardrailPolicyConstants:
    """Tests for constant handling."""

    def test_constant_true(self, policy):
        """Policy 'True' should return True."""
        result = policy.evaluate("True", {})
        assert result is True

    def test_constant_false(self, policy):
        """Policy 'False' should return False."""
        result = policy.evaluate("False", {})
        assert result is False


class TestGuardrailPolicySecurity:
    """Tests for security - ensure dangerous operations are blocked."""

    def test_reject_function_call(self, policy):
        """Function calls should be rejected."""
        result = policy.evaluate('os.system("ls")', {})
        assert result == "Invalid expression"

    def test_reject_import(self, policy):
        """Import expressions should be rejected."""
        result = policy.evaluate('__import__("os")', {})
        assert result == "Invalid expression"

    def test_reject_attribute_access(self, policy):
        """Attribute access should be rejected."""
        result = policy.evaluate("a.__class__", {"a": {"is_valid": True}})
        assert result == "Invalid expression"

    def test_reject_subscript(self, policy):
        """Subscript access should be rejected."""
        result = policy.evaluate("a[0]", {"a": {"is_valid": True}})
        assert result == "Invalid expression"

    def test_reject_lambda(self, policy):
        """Lambda expressions should be rejected."""
        result = policy.evaluate("lambda: 1", {})
        assert result == "Invalid expression"

    def test_reject_list_comprehension(self, policy):
        """List comprehensions should be rejected."""
        result = policy.evaluate("[x for x in range(10)]", {})
        assert result == "Invalid expression"


class TestGuardrailPolicyEdgeCases:
    """Tests for edge cases."""

    def test_empty_expression(self, policy):
        """Empty expression should return Invalid expression."""
        result = policy.evaluate("", {})
        assert result == "Invalid expression"

    def test_unknown_variable(self, policy):
        """Unknown variable should return Invalid expression."""
        result = policy.evaluate("unknown_var", {"a": {"is_valid": True}})
        assert result == "Invalid expression"

    def test_chained_comparison(self, policy):
        """Chained comparisons should work."""
        result = policy.evaluate("1 < 2 < 3", {})
        assert result is True

    def test_chained_comparison_false(self, policy):
        """Chained comparisons returning false should work."""
        result = policy.evaluate("1 < 2 > 3", {})
        assert result is False
