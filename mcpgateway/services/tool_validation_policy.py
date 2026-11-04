# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/tool_validation_policy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Decide whether a tool may be stored, using the CEL tool validation policy.

A policy is a CEL expression that evaluates to true when the tool is acceptable.
Three places can hold one, and the most specific wins: the tool record, then its gateway record, then the global
``TOOL_DESCRIPTION_FORBIDDEN_PATTERNS`` settings, which are compiled into a
``!(description.contains(...) || ...)`` expression. An empty value at any level
inherits the next one up.

``VALIDATION_STRICT`` keeps its meaning: a denied tool is refused when strict and
stored with a warning otherwise. A policy that cannot be evaluated counts as a denial,
so a sandbox failure never lets a tool through unchecked.
"""

# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass
import json
import logging
from typing import Any, Optional

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.cel_runner import CelError, evaluate_expression

logger = logging.getLogger(__name__)

__all__ = [
    "SOURCE_GATEWAY",
    "SOURCE_GLOBAL",
    "SOURCE_NONE",
    "SOURCE_TOOL",
    "PolicyDecision",
    "admit_tool",
    "apply_refusal",
    "evaluate_tool_policy",
    "global_policy_expression",
    "resolve_policy",
]

SOURCE_TOOL = "tool"
SOURCE_GATEWAY = "gateway"
SOURCE_GLOBAL = "global"
SOURCE_NONE = "none"

_LEVEL_NAMES = {SOURCE_TOOL: "tool-level", SOURCE_GATEWAY: "gateway-level", SOURCE_GLOBAL: "global"}


@dataclass(frozen=True)
class PolicyDecision:
    """The outcome of checking one tool against its effective policy.

    Attributes:
        allowed: True when the tool may be stored.
        source: Which level supplied the policy: tool, gateway, global, or none.
        expression: The CEL expression that was evaluated, or None when no policy applies.
        reason: Why the tool was refused, or None when it was allowed.
    """

    allowed: bool
    source: str
    expression: Optional[str]
    reason: Optional[str] = None


def _policy_text(value: Any) -> Optional[str]:
    """Return a stored policy as stripped text, or None when it is empty or not text.

    Args:
        value: A column value or schema field.

    Returns:
        The expression, or None when the level inherits.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def global_policy_expression() -> Optional[str]:
    """Compile the global forbidden-pattern settings into one CEL expression.

    Returns:
        The expression, or None when the global check is disabled or has no patterns.
    """
    if not settings.tool_description_forbidden_patterns_enabled:
        return None
    patterns = [pattern for pattern in settings.tool_description_forbidden_patterns if isinstance(pattern, str) and pattern.strip()]
    if not patterns:
        return None
    checks = " || ".join(f"description.contains({json.dumps(pattern, ensure_ascii=False)})" for pattern in patterns)
    return f"!({checks})"


def resolve_policy(tool_policy: Any, gateway_policy: Any) -> tuple[Optional[str], str]:
    """Pick the effective policy: tool, then gateway, then global.

    Args:
        tool_policy: The tool record's policy, or None.
        gateway_policy: The gateway record's policy, or None.

    Returns:
        The expression to evaluate and the level it came from. The expression is None,
        with source ``none``, when no level holds a policy.
    """
    tool_text = _policy_text(tool_policy)
    if tool_text:
        return tool_text, SOURCE_TOOL
    gateway_text = _policy_text(gateway_policy)
    if gateway_text:
        return gateway_text, SOURCE_GATEWAY
    global_text = global_policy_expression()
    if global_text:
        return global_text, SOURCE_GLOBAL
    return None, SOURCE_NONE


def evaluate_tool_policy(*, description: Any, tool_name: Any, tool_policy: Any = None, gateway_policy: Any = None) -> PolicyDecision:
    """Check one tool against its effective policy.

    Args:
        description: The tool description. Anything that is not text counts as empty.
        tool_name: The tool's upstream name. Anything that is not text counts as empty.
        tool_policy: The tool record's policy, or None.
        gateway_policy: The gateway record's policy, or None.

    Returns:
        The decision, including which level decided and why a tool was refused.
    """
    expression, source = resolve_policy(tool_policy, gateway_policy)
    if expression is None:
        return PolicyDecision(allowed=True, source=SOURCE_NONE, expression=None)

    variables = {"description": description if isinstance(description, str) else "", "tool_name": tool_name if isinstance(tool_name, str) else ""}
    try:
        allowed = evaluate_expression(expression, variables)
    except CelError as exc:
        return PolicyDecision(allowed=False, source=source, expression=expression, reason=f"could not be checked against the {_LEVEL_NAMES[source]} validation policy: {exc}")
    if allowed:
        return PolicyDecision(allowed=True, source=source, expression=expression)
    return PolicyDecision(allowed=False, source=source, expression=expression, reason=f"denied by the {_LEVEL_NAMES[source]} validation policy")


def admit_tool(*, description: Any, tool_name: Any, tool_policy: Any = None, gateway_policy: Any = None, context: str) -> Optional[str]:
    """Apply the effective policy and the strict setting to one tool.

    Args:
        description: The tool description. Anything that is not text counts as empty.
        tool_name: The tool's upstream name. Anything that is not text counts as empty.
        tool_policy: The tool record's policy, or None.
        gateway_policy: The gateway record's policy, or None.
        context: Short label for the log line, such as ``register_tool``.

    Returns:
        None when the tool may be stored. Otherwise the reason it was refused, such as
        ``denied by the gateway-level validation policy``, which only happens when
        ``VALIDATION_STRICT`` is on; when it is off a refused tool is logged as a
        warning and allowed.
    """
    decision = evaluate_tool_policy(description=description, tool_name=tool_name, tool_policy=tool_policy, gateway_policy=gateway_policy)
    if decision.allowed:
        logger.debug("Tool validation policy (%s) allowed tool %r during %s", decision.source, tool_name, context)
        return None

    if settings.validation_strict:
        logger.info("Tool validation policy (%s) refused tool %r during %s: %s", decision.source, tool_name, context, decision.reason)
        return decision.reason
    logger.warning("Tool %r %s (VALIDATION_STRICT=false, proceeding) during %s", tool_name, decision.reason, context)
    return None


def apply_refusal(tool: Any, reason: Optional[str]) -> None:
    """Record a policy decision on a stored tool row.

    A refusal disables the tool and stores why. An allow decision re-enables a tool
    that an earlier refusal disabled, and leaves any other tool alone, so a tool an
    operator switched off by hand stays off.

    Args:
        tool: The tool row, with ``enabled`` and ``validation_refusal`` attributes.
        reason: The refusal reason from ``admit_tool``, or None when the tool is allowed.

    Examples:
        >>> from types import SimpleNamespace
        >>> row = SimpleNamespace(enabled=True, validation_refusal=None)
        >>> apply_refusal(row, "denied by the global validation policy")
        >>> (row.enabled, row.validation_refusal)
        (False, 'denied by the global validation policy')
        >>> apply_refusal(row, None)
        >>> (row.enabled, row.validation_refusal)
        (True, None)
        >>> off_by_hand = SimpleNamespace(enabled=False, validation_refusal=None)
        >>> apply_refusal(off_by_hand, None)
        >>> off_by_hand.enabled
        False
    """
    if reason:
        tool.enabled = False
        tool.validation_refusal = reason
    elif isinstance(getattr(tool, "validation_refusal", None), str):
        tool.validation_refusal = None
        tool.enabled = True
