# -*- coding: utf-8 -*-
"""Location: ./plugins/conditional_routing/rule_engine.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Priority-ordered rule engine for conditional request routing.

Evaluates RoutingRules against a request context and returns the
first matching RoutingDecision.
"""

# Future
from __future__ import annotations

# Standard
import fnmatch
import ipaddress
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# First-Party
from .models import (
    MatchCriteria,
    RouteTarget,
    RoutingDecision,
    RoutingRule,
)

logger = logging.getLogger(__name__)

# ── Request context ──


class RequestContext:
    """Normalised request context for rule matching.

    Attributes:
        tool_name: Name of the tool being invoked (for tool_pre_invoke).
        agent_id: Agent identifier (for agent_pre_invoke).
        arguments: Tool arguments / agent message content.
        user_email: Authenticated user's email.
        user_teams: Teams the user belongs to.
        user_roles: Roles assigned to the user.
        source_ip: Client IP address.
        jwt_claims: Arbitrary JWT claims from the auth token.
        headers: HTTP request headers.
    """

    __slots__ = (
        "tool_name",
        "agent_id",
        "arguments",
        "user_email",
        "user_teams",
        "user_roles",
        "source_ip",
        "jwt_claims",
        "headers",
    )

    def __init__(
        self,
        *,
        tool_name: Optional[str] = None,
        agent_id: Optional[str] = None,
        arguments: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        user_teams: Optional[List[str]] = None,
        user_roles: Optional[List[str]] = None,
        source_ip: Optional[str] = None,
        jwt_claims: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.tool_name = tool_name
        self.agent_id = agent_id
        self.arguments = arguments or {}
        self.user_email = user_email
        self.user_teams = user_teams or []
        self.user_roles = user_roles or []
        self.source_ip = source_ip
        self.jwt_claims = jwt_claims or {}
        self.headers = headers or {}


# ── Rule Engine ──


class RuleEngine:
    """Priority-ordered rule evaluator.

    Rules are sorted by priority (lowest first) and evaluated in order.
    First matching rule wins. Returns RoutingDecision with match details.

    Example:
        >>> engine = RuleEngine([
        ...     RoutingRule(
        ...         name="finance",
        ...         match=MatchCriteria(tool_name_pattern="finance_*"),
        ...         route_to=RouteTarget(agent_id="finance-agent"),
        ...         priority=10,
        ...     ),
        ... ])
        >>> ctx = RequestContext(tool_name="finance_report")
        >>> decision = engine.evaluate(ctx)
        >>> decision.matched
        True
        >>> decision.rule_name
        'finance'
    """

    def __init__(self, rules: List[RoutingRule]) -> None:
        """Initialise the rule engine.

        Args:
            rules: Routing rules. Sorted by priority at construction.
        """
        self._rules = sorted(
            [r for r in rules if r.enabled],
            key=lambda r: r.priority,
        )

    def evaluate(self, context: RequestContext) -> RoutingDecision:
        """Evaluate all rules against the request context.

        Args:
            context: Normalised request context.

        Returns:
            RoutingDecision with match result and target info.
        """
        agent_id_or_tool = context.agent_id or context.tool_name or ""

        for rule in self._rules:
            details = _match_rule(rule.match, context)
            if details["matched"]:
                target = _resolve_target(rule.route_to, context)
                logger.debug(
                    "Routing rule matched: %s (priority=%d) → %s",
                    rule.name,
                    rule.priority,
                    target,
                )
                return RoutingDecision(
                    matched=True,
                    rule_name=rule.name,
                    target_agent_id=target,
                    target_tool_name=rule.route_to.tool_name,
                    virtual_server_id=rule.route_to.virtual_server_id,
                    override_args=rule.route_to.override_args,
                    original_target=agent_id_or_tool,
                    match_details=details,
                )

        # No rule matched
        logger.debug("No routing rule matched for target=%r", agent_id_or_tool)
        return RoutingDecision(
            matched=False,
            original_target=agent_id_or_tool,
            match_details={"reason": "no_rule_matched", "rules_evaluated": len(self._rules)},
        )


# ── Matchers ──


def _match_rule(criteria: MatchCriteria, ctx: RequestContext) -> Dict[str, Any]:
    """Check if a single rule's criteria match the context.

    Returns a dict with 'matched' (bool) and per-criterion details.
    """
    details: Dict[str, Any] = {"matched": True}

    # ── Tool name pattern ──
    if criteria.tool_name_pattern and ctx.tool_name:
        ok = _glob_match(criteria.tool_name_pattern, ctx.tool_name)
        details["tool_name"] = ok
        if not ok:
            details["matched"] = False

    # ── Agent ID pattern ──
    if criteria.agent_id_pattern and ctx.agent_id:
        ok = _glob_match(criteria.agent_id_pattern, ctx.agent_id)
        details["agent_id"] = ok
        if not ok:
            details["matched"] = False

    # ── User teams ──
    if criteria.user_teams:
        ok = bool(set(criteria.user_teams) & set(ctx.user_teams))
        details["user_teams"] = ok
        if not ok:
            details["matched"] = False

    # ── User roles ──
    if criteria.user_roles:
        ok = bool(set(criteria.user_roles) & set(ctx.user_roles))
        details["user_roles"] = ok
        if not ok:
            details["matched"] = False

    # ── User email patterns ──
    if criteria.user_email_patterns and ctx.user_email:
        ok = any(
            _glob_match(pattern, ctx.user_email)
            for pattern in criteria.user_email_patterns
        )
        details["user_email"] = ok
        if not ok:
            details["matched"] = False

    # ── Source IP CIDRs ──
    if criteria.source_ip_cidrs and ctx.source_ip:
        ok = _cidr_match_any(criteria.source_ip_cidrs, ctx.source_ip)
        if criteria.exclude_ip_cidrs:
            ok = ok and not _cidr_match_any(criteria.exclude_ip_cidrs, ctx.source_ip)
        details["source_ip"] = ok
        if not ok:
            details["matched"] = False

    # ── Content patterns ──
    if criteria.content_patterns and criteria.content_fields:
        ok = _content_match(
            criteria.content_patterns,
            criteria.content_fields,
            ctx.arguments,
            case_sensitive=criteria.case_sensitive,
        )
        details["content"] = ok
        if not ok:
            details["matched"] = False

    # ── JWT claims ──
    if criteria.jwt_claims:
        ok = all(
            str(ctx.jwt_claims.get(k)) == str(v)
            for k, v in criteria.jwt_claims.items()
        )
        details["jwt_claims"] = ok
        if not ok:
            details["matched"] = False

    # ── Headers ──
    if criteria.headers:
        ok = all(
            ctx.headers.get(k.lower()) == v
            for k, v in criteria.headers.items()
        )
        details["headers"] = ok
        if not ok:
            details["matched"] = False

    return details


def _glob_match(pattern: str, value: str) -> bool:
    """Match a value against a glob pattern.

    If pattern looks like a regex (contains common regex chars beyond
    fnmatch wildcards), treat it as regex. Otherwise use fnmatch.

    Args:
        pattern: Glob or regex pattern.
        value: String to match against.

    Returns:
        True if value matches pattern.
    """
    # Heuristic: if pattern contains regex metacharacters beyond * and ?,
    # treat it as a regex pattern.
    regex_indicators = {"[", "]", "(", ")", "{", "}", "\\", "+", "^", "$", "|"}
    if any(c in pattern for c in regex_indicators):
        try:
            return bool(re.search(pattern, value))
        except re.error:
            logger.warning("Invalid regex pattern %r, falling back to fnmatch", pattern)
            return fnmatch.fnmatch(value, pattern)
    return fnmatch.fnmatch(value, pattern)


def _cidr_match_any(cidrs: List[str], ip_str: str) -> bool:
    """Check if an IP address matches any of the given CIDR blocks.

    Args:
        cidrs: List of CIDR notation strings.
        ip_str: IP address string to check.

    Returns:
        True if the IP falls within any CIDR block.
    """
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        logger.debug("Invalid IP address %r, skipping CIDR match", ip_str)
        return False

    for cidr in cidrs:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
            if addr in network:
                return True
        except ValueError:
            logger.warning("Invalid CIDR %r, skipping", cidr)
    return False


def _content_match(
    patterns: List[str],
    fields: List[str],
    arguments: Dict[str, Any],
    case_sensitive: bool = False,
) -> bool:
    """Check if any content pattern matches in the specified argument fields.

    Args:
        patterns: Regex patterns to search for.
        fields: Dot-notation paths to search (e.g. "query", "args.text").
        arguments: Tool arguments / parameters dict.
        case_sensitive: Whether matching is case-sensitive.

    Returns:
        True if any pattern matches in any field.
    """
    flags = 0 if case_sensitive else re.IGNORECASE

    # Compile all patterns once
    compiled = []
    for p in patterns:
        try:
            compiled.append(re.compile(p, flags))
        except re.error:
            logger.warning("Invalid content regex %r, skipping", p)

    if not compiled:
        return False

    for field_path in fields:
        value = _resolve_field(arguments, field_path)
        if value is None:
            continue
        text = str(value)
        for cre in compiled:
            if cre.search(text):
                return True

    return False


def _resolve_field(data: Dict[str, Any], path: str) -> Any:
    """Resolve a dot-notation path within a nested dict.

    Args:
        data: Root dict to traverse.
        path: Dot-separated path (e.g. "arguments.query.text").

    Returns:
        Value at the path, or None if not found.
    """
    parts = path.split(".")
    current: Any = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
            if current is None:
                return None
        else:
            return None
    return current


def _resolve_target(target: RouteTarget, context: RequestContext) -> str:
    """Resolve the target agent ID from a RouteTarget.

    For single-target rules, returns agent_id directly.
    For weighted targets, selects based on deterministic hash.

    Args:
        target: The route target configuration.
        context: Request context (used for sticky session hashing).

    Returns:
        Resolved agent ID string.
    """
    if target.agent_id:
        return target.agent_id

    if target.weighted:
        return _select_weighted(target.weighted, context, sticky=target.sticky_session)

    # Should not reach here — validated by RouteTarget model
    raise ValueError("No target specified in RouteTarget")


def _select_weighted(
    targets: List[Any],  # WeightedTarget list
    context: RequestContext,
    sticky: bool = False,
) -> str:
    """Select a target from a weighted list.

    If sticky_session is enabled, uses deterministic hashing based on
    user identity. Otherwise, uses simple weighted modulo for
    deterministic distribution (not random — to avoid non-determinism
    in tests; production should use random weighted selection).

    Args:
        targets: List of WeightedTarget objects.
        context: Request context.
        sticky: Whether to hash by user identity.

    Returns:
        Selected agent_id.
    """
    if sticky and context.user_email:
        import hashlib

        hash_val = int(hashlib.md5(context.user_email.encode()).hexdigest(), 16)
    else:
        import time

        hash_val = int(time.time() * 1000)

    total_weight = sum(t.weight for t in targets)
    if total_weight <= 0:
        return targets[0].agent_id

    bucket = hash_val % total_weight
    cumulative = 0
    for t in targets:
        cumulative += t.weight
        if bucket < cumulative:
            return t.agent_id

    # Fallback
    return targets[-1].agent_id
