# -*- coding: utf-8 -*-
"""Location: ./plugins/conditional_routing/models.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Pydantic models for the Conditional Routing Plugin.

Defines MatchCriteria, RouteTarget, and RoutingRule schemas —
the declarative contract for content-based and attribute-based
agent/tool dispatch.
"""

# Standard
from enum import Enum
from typing import Any, Dict, List, Optional, Union

# Third-Party
from pydantic import BaseModel, Field, model_validator


class DefaultAction(str, Enum):
    """Behaviour when no routing rule matches a request."""

    PASSTHROUGH = "passthrough"
    DENY = "deny"


class MatchCriteria(BaseModel):
    """Criteria for matching a request to a routing rule.

    ALL specified fields must match (AND logic). Empty/None fields
    are treated as "match anything" for that dimension.

    Attributes:
        tool_name_pattern: Glob or regex pattern for tool name (fnmatch).
        agent_id_pattern: Glob or regex pattern for agent ID (fnmatch).
        user_teams: List of team IDs; matches if user belongs to any.
        user_roles: List of role names; matches if user has any.
        user_email_patterns: Glob patterns for user email addresses.
        source_ip_cidrs: CIDR blocks to include (e.g. 10.0.0.0/8).
        exclude_ip_cidrs: CIDR blocks to exclude (takes precedence).
        content_patterns: Regex patterns to match against content_fields.
        content_fields: Dot-notation paths in arguments to search (e.g. "arguments.query").
        jwt_claims: Arbitrary JWT claim key-value pairs to match.
        headers: HTTP header key-value patterns to match.
        case_sensitive: Whether content_patterns matching is case-sensitive.
    """

    tool_name_pattern: Optional[str] = None
    agent_id_pattern: Optional[str] = None
    user_teams: Optional[List[str]] = None
    user_roles: Optional[List[str]] = None
    user_email_patterns: Optional[List[str]] = None
    source_ip_cidrs: Optional[List[str]] = None
    exclude_ip_cidrs: Optional[List[str]] = None
    content_patterns: Optional[List[str]] = None
    content_fields: Optional[List[str]] = None
    jwt_claims: Optional[Dict[str, Any]] = None
    headers: Optional[Dict[str, str]] = None
    case_sensitive: bool = False

    @model_validator(mode="after")
    def _validate_content_requires_fields(self) -> "MatchCriteria":
        """content_patterns requires content_fields to be specified."""
        if self.content_patterns and not self.content_fields:
            raise ValueError("content_patterns requires content_fields to be specified")
        return self


class WeightedTarget(BaseModel):
    """A weighted routing target for canary/A/B testing.

    Attributes:
        agent_id: Target agent identifier.
        weight: Relative weight (e.g. 90 vs 10 for 90/10 split).
    """

    agent_id: str
    weight: int = Field(ge=1)


class RouteTarget(BaseModel):
    """Where to send a request when a rule matches.

    Exactly one of agent_id or weighted must be specified.

    Attributes:
        agent_id: Target agent identifier (single target).
        tool_name: Override tool name on the forwarded request.
        virtual_server_id: Virtual server to scope the request.
        override_args: Arguments to merge into the request.
        weighted: Weighted target list for traffic splitting.
        sticky_session: Whether to consistently route the same user to the same target.
        fallback: Ordered list of fallback agent IDs.
    """

    agent_id: Optional[str] = None
    tool_name: Optional[str] = None
    virtual_server_id: Optional[str] = None
    override_args: Dict[str, Any] = Field(default_factory=dict)
    weighted: Optional[List[WeightedTarget]] = None
    sticky_session: bool = False
    fallback: Optional[List[str]] = None

    @model_validator(mode="after")
    def _validate_target(self) -> "RouteTarget":
        """Ensure at least one target is specified."""
        if not self.agent_id and not self.weighted:
            raise ValueError("Either agent_id or weighted must be specified")
        if self.agent_id and self.weighted:
            raise ValueError("Cannot specify both agent_id and weighted")
        if self.sticky_session and not self.weighted:
            raise ValueError("sticky_session requires weighted targets")
        return self


class RoutingRule(BaseModel):
    """A single routing rule.

    Rules are evaluated in priority order (lowest first). First match wins.

    Attributes:
        name: Human-readable rule name (used in logs/metrics).
        match: Criteria for matching requests.
        route_to: Where to send matched requests.
        priority: Evaluation order (lower = evaluated first).
        enabled: Whether this rule is active.
    """

    name: str
    match: MatchCriteria
    route_to: RouteTarget
    priority: int = Field(default=100)
    enabled: bool = True


class ConditionalRoutingConfig(BaseModel):
    """Top-level configuration for the Conditional Routing Plugin.

    Attributes:
        routing_rules: Ordered list of routing rules.
        default_action: What to do when no rule matches.
        audit_routing_decisions: Whether to emit structured logs.
    """

    routing_rules: List[RoutingRule] = Field(default_factory=list)
    default_action: DefaultAction = DefaultAction.PASSTHROUGH
    audit_routing_decisions: bool = True


class RoutingDecision(BaseModel):
    """Result of evaluating the rule engine against a request.

    Attributes:
        matched: Whether a rule was matched.
        rule_name: Name of the matched rule (if any).
        target_agent_id: Resolved target agent ID.
        target_tool_name: Override tool name (if any).
        virtual_server_id: Target virtual server (if any).
        override_args: Arguments to merge (if any).
        original_target: Original agent_id or tool_name before routing.
        match_details: Debug info about which criteria matched.
    """

    matched: bool = False
    rule_name: Optional[str] = None
    target_agent_id: Optional[str] = None
    target_tool_name: Optional[str] = None
    virtual_server_id: Optional[str] = None
    override_args: Dict[str, Any] = Field(default_factory=dict)
    original_target: Optional[str] = None
    match_details: Dict[str, Any] = Field(default_factory=dict)
