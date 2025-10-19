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
from typing import Union


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
            A union of bool (if true or false). However, if the policy expression is invalid returns string with invalid expression
        """
        policy_variables = {key: value["is_valid"] for key, value in scan_result.items()}
        try:
            # Parse the policy expression into an abstract syntax tree
            tree = ast.parse(policy, mode="eval")
            # Check if the tree only contains allowed operations
            for node in ast.walk(tree):
                if isinstance(node, (ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)):
                    continue
                elif isinstance(node, (ast.Num, ast.UnaryOp)):
                    continue
                elif isinstance(node, (ast.Expression)):
                    continue
                elif isinstance(node, (ast.BoolOp, ast.Or, ast.And)):
                    continue
                elif isinstance(node, (ast.Name, ast.Eq, ast.Compare, ast.Load)):
                    continue
                else:
                    raise ValueError("Invalid operation")

            # Evaluate the expression
            return eval(compile(tree, "<string>", "eval"), {}, policy_variables)
        except (ValueError, SyntaxError, Exception):
            return "Invalid expression"


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
        sentence2: The second sentence

    Returns:
        None if no policy expression is defined, else a comma separated list of filters defined in the policy
    """
    if isinstance(policy_expression, str):
        pattern = r"\b(and|or|not)\b|[()]"
        filters = re.sub(pattern, "", policy_expression).strip()
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
