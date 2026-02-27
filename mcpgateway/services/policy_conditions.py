# -*- coding: utf-8 -*-
"""
Phase 2 policy condition evaluator for ABAC rules.

This module provides a JSON-based expression language supporting:
- Logical combinations: all (AND), any (OR), not (NOT)
- Attribute-based comparisons across subject/resource/context
- Variable references in condition values
"""

# Standard
from dataclasses import asdict, is_dataclass
from datetime import datetime
from ipaddress import ip_address, ip_network
from typing import Any, Dict, Mapping, Optional


def _to_mapping(value: Any) -> Mapping[str, Any]:
    """Normalize objects/dataclasses/dicts into a mapping.

    Args:
        value: Input object that may be a mapping, dataclass, or object instance.

    Returns:
        A mapping view of the input value, or an empty mapping when unsupported.
    """
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return vars(value)
    return {}


def _resolve_path(path: str, subject: Any, resource: Any, context: Any) -> Any:
    """Resolve dotted paths like subject.email or resource.visibility.

    Args:
        path: Dotted variable path to resolve.
        subject: Subject object or mapping.
        resource: Resource object or mapping.
        context: Context object or mapping.

    Returns:
        The resolved value when found, otherwise ``None``.
    """
    roots = {
        "subject": _to_mapping(subject),
        "resource": _to_mapping(resource),
        "context": _to_mapping(context),
    }

    parts = path.split(".")
    if len(parts) < 2:
        return None

    current: Any = roots.get(parts[0])
    for part in parts[1:]:
        if current is None:
            return None
        if isinstance(current, Mapping):
            if part in current:
                current = current.get(part)
            elif part == "team" and "team_id" in current:
                current = current.get("team_id")
            elif part == "tags":
                attrs = current.get("attributes", {}) if isinstance(current.get("attributes"), Mapping) else {}
                current = attrs.get("tags")
            else:
                attrs = current.get("attributes", {}) if isinstance(current.get("attributes"), Mapping) else {}
                current = attrs.get(part)
        else:
            current = getattr(current, part, None)
    return current


def _resolve_value(value: Any, subject: Any, resource: Any, context: Any) -> Any:
    """Resolve a value literal or variable reference.

    Args:
        value: Literal value or variable expression.
        subject: Subject object or mapping.
        resource: Resource object or mapping.
        context: Context object or mapping.

    Returns:
        The resolved value or the original literal.
    """
    if isinstance(value, Mapping) and "var" in value:
        return _resolve_path(str(value["var"]), subject, resource, context)
    if isinstance(value, str):
        if value.startswith("subject.") or value.startswith("resource.") or value.startswith("context."):
            return _resolve_path(value, subject, resource, context)
    return value


def _to_datetime(value: Any) -> Optional[datetime]:
    """Convert value to datetime if possible.

    Args:
        value: Candidate datetime value (datetime or ISO-8601 string).

    Returns:
        A datetime object when conversion succeeds, otherwise ``None``.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _evaluate_operator(op: str, left: Any, right: Any) -> bool:
    """Evaluate atomic condition operator.

    Args:
        op: Operator name such as ``eq`` or ``ip_in_cidr``.
        left: Left operand value.
        right: Right operand value.

    Returns:
        ``True`` when the condition evaluates as satisfied, otherwise ``False``.

    Raises:
        ValueError: If the operator is unsupported.
    """
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if op == "in":
        return left in right if isinstance(right, (list, tuple, set)) else False
    if op == "not_in":
        return left not in right if isinstance(right, (list, tuple, set)) else True
    if op == "contains":
        return right in left if isinstance(left, (list, tuple, set, str)) else False
    if op == "not_contains":
        return right not in left if isinstance(left, (list, tuple, set, str)) else True
    if op in {"gt", "gte", "lt", "lte"}:
        left_dt = _to_datetime(left)
        right_dt = _to_datetime(right)
        if left_dt and right_dt:
            left = left_dt
            right = right_dt
        if op == "gt":
            return left > right
        if op == "gte":
            return left >= right
        if op == "lt":
            return left < right
        return left <= right
    if op == "ip_in_cidr":
        try:
            return ip_address(str(left)) in ip_network(str(right), strict=False)
        except ValueError:
            return False
    raise ValueError(f"Unsupported operator: {op}")


def evaluate_policy_condition(condition: Dict[str, Any], subject: Any, resource: Any, context: Any) -> bool:
    """Evaluate a JSON policy expression against subject/resource/context.

    Args:
        condition: Condition tree in JSON-like dictionary form.
        subject: Subject object or mapping used by variable lookups.
        resource: Resource object or mapping used by variable lookups.
        context: Context object or mapping used by variable lookups.

    Returns:
        ``True`` if the condition matches, otherwise ``False``.

    Raises:
        ValueError: If the condition node format or operator is invalid.
    """
    if not condition:
        return True

    if "all" in condition:
        children = condition.get("all", [])
        return all(evaluate_policy_condition(child, subject, resource, context) for child in children)

    if "any" in condition:
        children = condition.get("any", [])
        return any(evaluate_policy_condition(child, subject, resource, context) for child in children)

    if "not" in condition:
        return not evaluate_policy_condition(condition["not"], subject, resource, context)

    if "op" in condition:
        op = str(condition["op"])
        left = _resolve_value(condition.get("left"), subject, resource, context)
        right = _resolve_value(condition.get("right"), subject, resource, context)
        return _evaluate_operator(op, left, right)

    raise ValueError("Invalid policy condition node. Expected one of: all, any, not, op.")
