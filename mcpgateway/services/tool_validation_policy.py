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
after one retry for a sandbox that is busy or unavailable, so a failed check never
lets a tool through unchecked. The stored reason names the level; the log line carries the cause.

Setting or changing a policy requires the ``validation_policy.manage`` permission and
writes an audit trail entry.
"""

# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass
import json
import logging
from typing import Any, List, Optional

# Third-Party
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailTeam, Permissions
from mcpgateway.services.audit_trail_service import get_audit_trail_service
from mcpgateway.utils.cel_runner import CelError, CelEvaluationError, CelSyntaxError, evaluate_expression

logger = logging.getLogger(__name__)

__all__ = [
    "SOURCE_GATEWAY",
    "SOURCE_GLOBAL",
    "SOURCE_NONE",
    "SOURCE_TOOL",
    "PolicyDecision",
    "admit_stored_tool",
    "admit_tool",
    "apply_refusal",
    "descriptions_to_validate",
    "check_policy_permission",
    "evaluate_tool_policy",
    "global_policy_expression",
    "policy_changed",
    "policy_text",
    "record_policy_change",
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


def policy_text(value: Any) -> Optional[str]:
    """Return a stored policy as stripped text, or None when it is empty or not text.

    Args:
        value: A column value or schema field.

    Returns:
        The expression, or None when the level inherits.

    Examples:
        >>> policy_text("  true ")
        'true'
        >>> policy_text("   ") is None and policy_text(None) is None and policy_text(42) is None
        True
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def policy_changed(old: Any, new: Any) -> bool:
    """Tell whether a policy edit changes the effective policy.

    Args:
        old: The stored policy.
        new: The submitted policy.

    Returns:
        True when the two differ once normalised, so a form that resubmits the
        stored value unchanged does not count as a change.
    """
    return policy_text(old) != policy_text(new)


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
    tool_text = policy_text(tool_policy)
    if tool_text:
        return tool_text, SOURCE_TOOL
    gateway_text = policy_text(gateway_policy)
    if gateway_text:
        return gateway_text, SOURCE_GATEWAY
    global_text = global_policy_expression()
    if global_text:
        return global_text, SOURCE_GLOBAL
    return None, SOURCE_NONE


def _evaluate_with_retry(expression: str, variables: dict[str, str]) -> bool:
    """Evaluate an expression, retrying once when the sandbox itself fails.

    Args:
        expression: The policy.
        variables: The CEL variables.

    Returns:
        The boolean the expression evaluated to.

    Raises:
        CelError: If the expression is broken, or the sandbox fails on both attempts.
    """
    try:
        return evaluate_expression(expression, variables)
    except (CelSyntaxError, CelEvaluationError):
        raise
    except CelError as exc:
        logger.debug("CEL sandbox failure, retrying once: %s", exc)
        return evaluate_expression(expression, variables)


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
        allowed = _evaluate_with_retry(expression, variables)
    except CelError as exc:
        logger.warning("Tool validation policy (%s) could not be evaluated for tool %r: %s", source, tool_name, exc)
        return PolicyDecision(allowed=False, source=source, expression=expression, reason=f"could not be evaluated against the {_LEVEL_NAMES[source]} validation policy")
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


def descriptions_to_validate(tool: Any) -> List[Optional[str]]:
    """Return the description texts the policy evaluates on a stored tool: the served text, plus the upstream text when it differs.

    Args:
        tool: The stored tool.

    Returns:
        One or two texts, served description first.
    """
    texts: List[Optional[str]] = [tool.description]
    original = tool.original_description
    if isinstance(original, str) and original != tool.description:
        texts.append(original)
    return texts


def admit_stored_tool(tool: Any, gateway_policy: Any, context: str) -> Optional[str]:
    """Apply the effective policy to a stored tool, checking every description it carries.

    Args:
        tool: The stored tool, with ``original_name``, ``description``, ``original_description`` and ``tool_validation_policy``.
        gateway_policy: The policy of the tool's gateway, or None.
        context: Short label for the log line.

    Returns:
        The first refusal reason, or None when every description is allowed.
    """
    for text in descriptions_to_validate(tool):
        refusal = admit_tool(description=text, tool_name=tool.original_name, tool_policy=tool.tool_validation_policy, gateway_policy=gateway_policy, context=context)
        if refusal:
            return refusal
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


def _is_personal_team(db: Session, team_id: str) -> bool:
    """check whether a team is a user's personal team.

    Args:
        db: Database session.
        team_id: The team id.

    Returns:
        True for a personal team or an unknown team, False for a shared team.
    """
    is_personal = db.execute(select(EmailTeam.is_personal).where(EmailTeam.id == team_id)).scalar_one_or_none()
    return is_personal is not False


async def check_policy_permission(db: Session, user_email: Optional[str], *, resource_type: str, team_id: Optional[str]) -> None:
    """Refuse a policy change from a caller without the ``validation_policy.manage`` permission.

    Every user holds ``team_admin`` on their own personal team, so a role on a personal
    team never counts. A record owned by a personal team, or by no team, needs the
    permission through a global role.

    Args:
        db: Database session.
        user_email: The acting user. None means no authenticated actor is known.
        resource_type: ``tools`` or ``gateways``.
        team_id: The team that owns the record, or None.

    Raises:
        PermissionError: If the caller is unknown or lacks the permission.
    """
    # First-Party
    from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

    scope_team = team_id if team_id and not _is_personal_team(db, team_id) else None
    if user_email and await PermissionService(db).check_permission(user_email, Permissions.VALIDATION_POLICY_MANAGE, resource_type=resource_type, team_id=scope_team):
        return
    logger.info("Refused a tool validation policy change on %s by %r: missing %s", resource_type, user_email, Permissions.VALIDATION_POLICY_MANAGE)
    raise PermissionError(f"Setting a tool validation policy requires the {Permissions.VALIDATION_POLICY_MANAGE} permission")


def record_policy_change(*, resource_type: str, resource_id: Any, resource_name: Optional[str], team_id: Optional[str], user_email: Optional[str], old: Any, new: Any) -> None:
    """Write the audit trail entry for a policy change.

    Args:
        resource_type: ``tool`` or ``gateway``.
        resource_id: The record id.
        resource_name: The record name.
        team_id: The owning team, or None.
        user_email: The acting user.
        old: The policy before the change.
        new: The policy after the change.
    """
    before, after = policy_text(old), policy_text(new)
    get_audit_trail_service().log_action(
        user_id=user_email or "system",
        user_email=user_email,
        action=f"set_{resource_type}_validation_policy",
        resource_type=resource_type,
        resource_id=str(resource_id),
        resource_name=resource_name,
        team_id=team_id,
        old_values={"tool_validation_policy": before},
        new_values={"tool_validation_policy": after},
        changes={"tool_validation_policy": {"old": before, "new": after}},
    )
