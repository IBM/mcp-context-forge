# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/tbac_policy_engine.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Task-based access control policy evaluation for MCP tools/call requests.
"""

# Standard
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Dict, Optional, Tuple

# First-Party
from mcpgateway.schemas_tbac import TBACClaims, TBACTransactionConstraint


_TEMPLATE_PATTERN = re.compile(r"^\$\{(?P<expr>[^{}]+)\}$")


class TBACPolicyError(Exception):
    """Raised when a TBAC policy check fails."""

    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.data = data or {}


class TBACPolicyEngine:
    """Evaluate TBAC authorization for MCP JSON-RPC tools/call requests."""

    def evaluate(self, claims: TBACClaims, rpc_request: Dict[str, Any]) -> None:
        """Evaluate task/tool/transaction checks.

        Args:
            claims: Parsed TBAC claims from JWT.
            rpc_request: JSON-RPC request body.

        Raises:
            TBACPolicyError: If any TBAC check fails.
        """
        params = rpc_request.get("params")
        if not isinstance(params, dict):
            raise TBACPolicyError("Invalid JSON-RPC params for tools/call", {"field": "params"})

        tool_name = params.get("name")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise TBACPolicyError("Missing tool name in tools/call params", {"field": "params.name"})

        self._check_task_access(claims, params)
        self._check_tool_access(claims, tool_name.strip(), params)
        self._check_transaction_constraints(claims, rpc_request)

    def _check_task_access(self, claims: TBACClaims, params: Dict[str, Any]) -> None:
        if not claims.authorized_tasks:
            return

        objective = self._extract_objective(params)
        if not objective:
            raise TBACPolicyError(
                "TBAC task check failed: missing business objective",
                {"required_claim": "authorized_tasks", "accepted_fields": ["params.task", "params.arguments.task", "params.arguments.objective", "params.arguments.goal"]},
            )

        allowed = {task.strip() for task in claims.authorized_tasks if isinstance(task, str) and task.strip()}
        if objective not in allowed:
            raise TBACPolicyError(
                "TBAC task check failed: objective not authorized",
                {"objective": objective, "authorized_tasks": sorted(allowed)},
            )

    @staticmethod
    def _extract_objective(params: Dict[str, Any]) -> Optional[str]:
        direct = params.get("task")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()

        args = params.get("arguments")
        if not isinstance(args, dict):
            return None

        for key in ("task", "objective", "goal", "business_objective"):
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _check_tool_access(self, claims: TBACClaims, tool_name: str, params: Dict[str, Any]) -> None:
        if not claims.allowed_tools and not claims.tools:
            return

        if tool_name in claims.allowed_tools:
            return

        server_name, action = self._infer_server_and_action(tool_name, params)
        if server_name and server_name in claims.tools:
            policy = claims.tools[server_name]
            if tool_name in policy.tools:
                return
            if action and action in policy.actions:
                return

        raise TBACPolicyError(
            "TBAC tool check failed: tool not authorized",
            {
                "tool": tool_name,
                "allowed_tools": claims.allowed_tools,
                "servers": sorted(claims.tools.keys()),
            },
        )

    @staticmethod
    def _infer_server_and_action(tool_name: str, params: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        for separator in (".", "/", ":"):
            if separator in tool_name:
                left, right = tool_name.split(separator, 1)
                if left and right:
                    return left, right

        server_id = params.get("server_id")
        if isinstance(server_id, str) and server_id.strip():
            return server_id.strip(), tool_name

        return None, None

    def _check_transaction_constraints(self, claims: TBACClaims, rpc_request: Dict[str, Any]) -> None:
        if not claims.transaction_constraints:
            return

        context = {
            "jwt": claims.model_dump(mode="python"),
            "mcp": {
                "jsonrpc": rpc_request.get("jsonrpc"),
                "method": rpc_request.get("method"),
                "id": rpc_request.get("id"),
                "params": rpc_request.get("params", {}),
            },
        }

        for constraint in claims.transaction_constraints:
            self._evaluate_constraint(constraint, context)

    def _evaluate_constraint(self, constraint: TBACTransactionConstraint, context: Dict[str, Any]) -> None:
        left = self._resolve_value(constraint.left, context)
        right = self._resolve_value(constraint.right, context)
        passed = self._compare_values(left, right, constraint.operator)
        if not passed:
            raise TBACPolicyError(
                constraint.message,
                {
                    "constraint": {
                        "left": constraint.left,
                        "operator": constraint.operator,
                        "right": constraint.right,
                    },
                    "resolved": {"left": left, "right": right},
                },
            )

    def _resolve_value(self, expression: str, context: Dict[str, Any]) -> Any:
        match = _TEMPLATE_PATTERN.match(expression)
        if not match:
            return expression

        path = match.group("expr").strip()
        value = self._resolve_path(context, path)
        if value is None:
            raise TBACPolicyError("TBAC constraint reference could not be resolved", {"expression": expression})
        return value

    @staticmethod
    def _resolve_path(payload: Any, path: str) -> Any:
        current = payload
        for segment in path.split("."):
            if isinstance(current, dict):
                if segment not in current:
                    return None
                current = current[segment]
                continue
            if isinstance(current, list):
                try:
                    index = int(segment)
                except ValueError:
                    return None
                if index < 0 or index >= len(current):
                    return None
                current = current[index]
                continue
            return None
        return current

    def _compare_values(self, left: Any, right: Any, operator: str) -> bool:
        if operator in {"<", "<=", ">", ">="}:
            left_num = self._to_decimal(left)
            right_num = self._to_decimal(right)
            if left_num is None or right_num is None:
                return False
            if operator == "<":
                return left_num < right_num
            if operator == "<=":
                return left_num <= right_num
            if operator == ">":
                return left_num > right_num
            return left_num >= right_num

        if operator == "==":
            return left == right
        if operator == "!=":
            return left != right
        if operator == "in":
            return left in right if isinstance(right, (list, tuple, set, str)) else False
        if operator == "contains":
            return right in left if isinstance(left, (list, tuple, set, str)) else False
        if operator == "startswith":
            return str(left).startswith(str(right))
        if operator == "endswith":
            return str(left).endswith(str(right))
        if operator == "regex":
            return re.search(str(right), str(left)) is not None
        return False

    @staticmethod
    def _to_decimal(value: Any) -> Optional[Decimal]:
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
