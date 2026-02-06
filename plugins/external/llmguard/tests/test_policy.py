# -*- coding: utf-8 -*-
"""Unit tests for GuardrailPolicy evaluator.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

"""

# Third-Party
import pytest

# First-Party
from llmguardplugin.policy import (
    GuardrailPolicy,
    ResponseGuardrailPolicy,
    get_policy_filters,
    word_wise_levenshtein_distance,
)


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


class TestGuardrailPolicyArithmetic:
    """Tests for arithmetic operations."""

    def test_addition(self, policy):
        """Addition should work."""
        result = policy.evaluate("1 + 2", {})
        assert result == 3

    def test_subtraction(self, policy):
        """Subtraction should work."""
        result = policy.evaluate("5 - 3", {})
        assert result == 2

    def test_multiplication(self, policy):
        """Multiplication should work."""
        result = policy.evaluate("3 * 4", {})
        assert result == 12

    def test_division(self, policy):
        """Division should work."""
        result = policy.evaluate("10 / 2", {})
        assert result == 5.0

    def test_floor_division(self, policy):
        """Floor division should work."""
        result = policy.evaluate("10 // 3", {})
        assert result == 3

    def test_modulo(self, policy):
        """Modulo should work."""
        result = policy.evaluate("10 % 3", {})
        assert result == 1

    def test_power(self, policy):
        """Power should work."""
        result = policy.evaluate("2 ** 3", {})
        assert result == 8


class TestGuardrailPolicyUnaryOps:
    """Tests for unary operations."""

    def test_unary_plus(self, policy):
        """Unary plus should work."""
        result = policy.evaluate("+5", {})
        assert result == 5

    def test_unary_minus(self, policy):
        """Unary minus should work."""
        result = policy.evaluate("-5", {})
        assert result == -5


class TestGuardrailPolicyComparisons:
    """Tests for comparison operations."""

    def test_equal(self, policy):
        """Equality comparison should work."""
        result = policy.evaluate("5 == 5", {})
        assert result is True

    def test_not_equal(self, policy):
        """Not equal comparison should work."""
        result = policy.evaluate("5 != 3", {})
        assert result is True

    def test_less_than(self, policy):
        """Less than comparison should work."""
        result = policy.evaluate("3 < 5", {})
        assert result is True

    def test_less_than_or_equal(self, policy):
        """Less than or equal comparison should work."""
        result = policy.evaluate("5 <= 5", {})
        assert result is True

    def test_greater_than(self, policy):
        """Greater than comparison should work."""
        result = policy.evaluate("5 > 3", {})
        assert result is True

    def test_greater_than_or_equal(self, policy):
        """Greater than or equal comparison should work."""
        result = policy.evaluate("5 >= 5", {})
        assert result is True

    def test_comparison_false(self, policy):
        """Comparison returning false should work."""
        result = policy.evaluate("5 < 3", {})
        assert result is False

    def test_unsupported_comparison_in_operator(self, policy):
        """Unsupported comparison operators should return Invalid expression."""
        result = policy.evaluate("5 in [1, 2, 3]", {})
        assert result == "Invalid expression"


class TestResponseGuardrailPolicy:
    """Tests for ResponseGuardrailPolicy enum."""

    def test_default_noresponse_guardrail(self):
        """Test DEFAULT_NORESPONSE_GUARDRAIL value."""
        assert ResponseGuardrailPolicy.DEFAULT_NORESPONSE_GUARDRAIL.value == "I'm sorry, I'm afraid I can't do that."

    def test_default_policy_denial_response(self):
        """Test DEFAULT_POLICY_DENIAL_RESPONSE value."""
        assert ResponseGuardrailPolicy.DEFAULT_POLICY_DENIAL_RESPONSE.value == "Request Forbidden"

    def test_default_policy_allow_response(self):
        """Test DEFAULT_POLICY_ALLOW_RESPONSE value."""
        assert ResponseGuardrailPolicy.DEFAULT_POLICY_ALLOW_RESPONSE.value == "Request Allowed"


class TestWordWiseLevenshteinDistance:
    """Tests for word_wise_levenshtein_distance function."""

    def test_identical_sentences(self):
        """Identical sentences should have distance 0."""
        distance = word_wise_levenshtein_distance("hello world", "hello world")
        assert distance == 0

    def test_completely_different_sentences(self):
        """Completely different sentences should have distance equal to max length."""
        distance = word_wise_levenshtein_distance("hello world", "foo bar")
        assert distance == 2

    def test_one_word_difference(self):
        """One word difference should have distance 1."""
        distance = word_wise_levenshtein_distance("hello world", "hello there")
        assert distance == 1

    def test_insertion(self):
        """Insertion should increase distance."""
        distance = word_wise_levenshtein_distance("hello", "hello world")
        assert distance == 1

    def test_deletion(self):
        """Deletion should increase distance."""
        distance = word_wise_levenshtein_distance("hello world", "hello")
        assert distance == 1

    def test_empty_sentences(self):
        """Empty sentences should have distance 0."""
        distance = word_wise_levenshtein_distance("", "")
        assert distance == 0

    def test_one_empty_sentence(self):
        """One empty sentence should have distance equal to other sentence length."""
        distance = word_wise_levenshtein_distance("hello world", "")
        assert distance == 2

    def test_multiple_word_changes(self):
        """Multiple word changes should accumulate distance."""
        distance = word_wise_levenshtein_distance("the quick brown fox", "a slow red dog")
        assert distance == 4


class TestGetPolicyFilters:
    """Tests for get_policy_filters function."""

    def test_string_policy_simple(self):
        """Simple string policy should extract filter names."""
        filters = get_policy_filters("PromptInjection and Toxicity")
        assert filters == ["PromptInjection", "Toxicity"]

    def test_string_policy_with_or(self):
        """String policy with 'or' should extract filter names."""
        filters = get_policy_filters("PromptInjection or Toxicity")
        assert filters == ["PromptInjection", "Toxicity"]

    def test_string_policy_with_not(self):
        """String policy with 'not' should extract filter names."""
        filters = get_policy_filters("not PromptInjection")
        assert filters == ["PromptInjection"]

    def test_string_policy_with_parentheses(self):
        """String policy with parentheses should extract filter names."""
        filters = get_policy_filters("(PromptInjection and Toxicity) or BanTopics")
        assert filters == ["PromptInjection", "Toxicity", "BanTopics"]

    def test_string_policy_complex(self):
        """Complex string policy should extract all filter names."""
        filters = get_policy_filters("(a and b) or (c and not d)")
        assert filters == ["a", "b", "c", "d"]

    def test_dict_policy_simple(self):
        """Simple dict policy should extract keys."""
        filters = get_policy_filters({"PromptInjection": True, "Toxicity": False})
        assert set(filters) == {"PromptInjection", "Toxicity"}

    def test_dict_policy_with_policy_key(self):
        """Dict policy with 'policy' key should exclude it."""
        filters = get_policy_filters({"PromptInjection": True, "policy": "some expression"})
        assert filters == ["PromptInjection"]

    def test_dict_policy_with_policy_message_key(self):
        """Dict policy with 'policy_message' key should exclude it."""
        filters = get_policy_filters({"PromptInjection": True, "policy_message": "Denied"})
        assert filters == ["PromptInjection"]

    def test_dict_policy_with_both_special_keys(self):
        """Dict policy with both special keys should exclude them."""
        filters = get_policy_filters({"PromptInjection": True, "Toxicity": False, "policy": "expression", "policy_message": "message"})
        assert set(filters) == {"PromptInjection", "Toxicity"}

    def test_none_policy(self):
        """None policy should return None."""
        filters = get_policy_filters(None)
        assert filters is None

    def test_int_policy(self):
        """Integer policy should return None."""
        filters = get_policy_filters(123)
        assert filters is None

    def test_list_policy(self):
        """List policy should return None."""
        filters = get_policy_filters(["PromptInjection", "Toxicity"])
        assert filters is None


class TestGuardrailPolicyUnsupportedOperations:
    """Tests for unsupported operations that should raise ValueError."""

    def test_unsupported_binop(self, policy):
        """Unsupported binary operation should return Invalid expression."""
        result = policy.evaluate("5 & 3", {})
        assert result == "Invalid expression"

    def test_unsupported_unaryop(self, policy):
        """Unsupported unary operation should return Invalid expression."""
        result = policy.evaluate("~5", {})
        assert result == "Invalid expression"


class TestGuardrailPolicyASTExpression:
    """Tests for AST Expression node handling."""

    def test_ast_expression_wrapper(self, policy):
        """Test that ast.Expression wrapper nodes are handled correctly."""
        # This tests the isinstance(node, ast.Expression) branch at line 76-77
        import ast

        # Create an Expression node explicitly and pass the whole tree (not just body)
        tree = ast.parse("True", mode="eval")
        # Call _safe_eval_impl directly with the Expression node
        result = policy._safe_eval_impl(tree, {})
        assert result is True


class TestGuardrailPolicyComparisonEdgeCases:
    """Tests for comparison edge cases."""

    def test_chained_comparison_with_failure(self, policy):
        """Test chained comparison that fails midway."""

    def test_unsupported_comparison_is_operator(self, policy):
        """Test that 'is' comparison operator raises ValueError."""
        # The 'is' operator is not in the supported operators list
        result = policy.evaluate("a is b", {"a": {"is_valid": True}, "b": {"is_valid": True}})
        assert result == "Invalid expression"

    def test_unsupported_comparison_is_not_operator(self, policy):
        """Test that 'is not' comparison operator raises ValueError."""
        result = policy.evaluate("a is not b", {"a": {"is_valid": True}, "b": {"is_valid": True}})
        assert result == "Invalid expression"
        # This should test the comparison chain logic more thoroughly
        result = policy.evaluate("1 < 2 < 1", {})
        assert result is False

    def test_multiple_chained_comparisons(self, policy):
        """Test multiple chained comparisons."""
        result = policy.evaluate("1 < 2 <= 2 < 3", {})
        assert result is True
