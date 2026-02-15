# -*- coding: utf-8 -*-

"""Defines Policy Class for Guardrails.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

"""

# Standard
import ast
from enum import Enum
import re
import time
from typing import Union

# Third-Party
from prometheus_client import Histogram

# Precompiled regex pattern for performance
_POLICY_OPERATORS_RE = re.compile(r"\b(and|or|not)\b|[()]")

# Prometheus metrics
llm_guard_policy_compile_duration_seconds = Histogram(
    "llm_guard_policy_compile_duration_seconds",
    "Duration of policy compilation/evaluation in seconds",
    buckets=(0.0001, 0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)


class ResponseGuardrailPolicy(Enum):
    """Class to create custom messages responded by your guardrails"""

    DEFAULT_NORESPONSE_GUARDRAIL = "I'm sorry, I'm afraid I can't do that."
    DEFAULT_POLICY_DENIAL_RESPONSE = "Request Forbidden"
    DEFAULT_POLICY_ALLOW_RESPONSE = "Request Allowed"


class GuardrailPolicy:
    """Class to apply and evaluate guardrail policies on results produced by scanners (example: LLMGuard)"""

    def evaluate(self, policy: str, scan_result: dict) -> Union[bool, str]:
        """Class to create custom messages responded by your guardrails

        Args:
            policy: The policy expression to evaluate the scan results on
            scan_result: The result of scanners applied

        Returns:
            Union[bool, str]: A union of bool (if true or false). However, if the policy expression is invalid returns string with invalid expression

        Raises:
            ValueError: If the policy expression contains invalid operations.
        """
        policy_variables = {key: value["is_valid"] for key, value in scan_result.items()}
        try:
            # Parse the policy expression into an abstract syntax tree
            tree = ast.parse(policy, mode="eval")
            return self._safe_eval(tree.body, policy_variables)
        except (ValueError, SyntaxError, Exception):
            return "Invalid expression"

    def _safe_eval(self, node, variables):
        """Recursively evaluates an AST node safely."""
        start_time = time.time()
        try:
            result = self._safe_eval_impl(node, variables)
            return result
        finally:
            duration = time.time() - start_time
            llm_guard_policy_compile_duration_seconds.observe(duration)

    def _safe_eval_impl(self, node, variables):
        """Internal implementation of safe evaluation."""
        if isinstance(node, ast.Expression):
            return self._safe_eval_impl(node.body, variables)
        elif isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.Name):
            if node.id in variables:
                return variables[node.id]
            raise ValueError(f"Unknown variable: {node.id}")
        elif isinstance(node, ast.BinOp):
            left = self._safe_eval_impl(node.left, variables)
            right = self._safe_eval_impl(node.right, variables)
            operators = {
                ast.Add: lambda a, b: a + b,
                ast.Sub: lambda a, b: a - b,
                ast.Mult: lambda a, b: a * b,
                ast.Div: lambda a, b: a / b,
                ast.FloorDiv: lambda a, b: a // b,
                ast.Mod: lambda a, b: a % b,
                ast.Pow: lambda a, b: a**b,
            }
            if type(node.op) in operators:
                return operators[type(node.op)](left, right)
        elif isinstance(node, ast.UnaryOp):
            operand = self._safe_eval_impl(node.operand, variables)
            operators = {
                ast.UAdd: lambda a: +a,
                ast.USub: lambda a: -a,
                ast.Not: lambda a: not a,
            }
            if type(node.op) in operators:
                return operators[type(node.op)](operand)
        elif isinstance(node, ast.BoolOp):
            # Use lazy evaluation to preserve short-circuit semantics
            if isinstance(node.op, ast.And):
                for v in node.values:
                    if not self._safe_eval_impl(v, variables):
                        return False
                return True
            elif isinstance(node.op, ast.Or):
                for v in node.values:
                    if self._safe_eval_impl(v, variables):
                        return True
                return False
        elif isinstance(node, ast.Compare):
            left = self._safe_eval_impl(node.left, variables)
            for op, right_node in zip(node.ops, node.comparators):
                right = self._safe_eval_impl(right_node, variables)
                operators = {
                    ast.Eq: lambda a, b: a == b,
                    ast.NotEq: lambda a, b: a != b,
                    ast.Lt: lambda a, b: a < b,
                    ast.LtE: lambda a, b: a <= b,
                    ast.Gt: lambda a, b: a > b,
                    ast.GtE: lambda a, b: a >= b,
                }
                if type(op) in operators:
                    if not operators[type(op)](left, right):
                        return False
                    left = right
                else:
                    raise ValueError("Unsupported comparison")
            return True

        raise ValueError("Unsupported operation")


def word_wise_levenshtein_distance(sentence1, sentence2):
    """A helper function to calculate word wise levenshtein distance

    Args:
        sentence1: The first sentence
        sentence2: The second sentence

    Returns:
        distance between the two sentences
    """
    words1 = sentence1.split()
    words2 = sentence2.split()

    n, m = len(words1), len(words2)
    dp = [[0] * (m + 1) for _ in range(n + 1)]

    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if words1[i - 1] == words2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]) + 1

    return dp[n][m]


def get_policy_filters(policy_expression) -> Union[list, None]:
    """A helper function to get filters defined in the policy expression

    Args:
        policy_expression: The expression of policy

    Returns:
        Union[list, None]: None if no policy expression is defined, else a comma separated list of filters defined in the policy
    """
    if isinstance(policy_expression, str):
        filters = _POLICY_OPERATORS_RE.sub("", policy_expression).strip()
        return filters.split()
    elif isinstance(policy_expression, dict):
        filters = list(policy_expression.keys())
        if "policy_message" in filters:
            filters.remove("policy_message")
        if "policy" in filters:
            filters.remove("policy")
        return filters
    else:
        return None
