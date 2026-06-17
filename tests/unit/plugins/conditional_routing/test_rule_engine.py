# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/conditional_routing/test_rule_engine.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for the Conditional Routing Plugin — Rule Engine.
"""

# Third-Party
import pytest

# First-Party (plugins live outside the mcpgateway package)
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))  # repo root

from plugins.conditional_routing.models import (
    ConditionalRoutingConfig,
    DefaultAction,
    MatchCriteria,
    RouteTarget,
    RoutingRule,
)
from plugins.conditional_routing.rule_engine import RequestContext, RuleEngine, _select_weighted


@pytest.fixture
def finance_rule():
    return RoutingRule(
        name="finance",
        match=MatchCriteria(tool_name_pattern="finance_*", user_teams=["accounting"]),
        route_to=RouteTarget(agent_id="finance-agent"),
        priority=10,
    )


@pytest.fixture
def code_rule():
    return RoutingRule(
        name="code_review",
        match=MatchCriteria(tool_name_pattern="code_*"),
        route_to=RouteTarget(agent_id="code-review-agent"),
        priority=20,
    )


@pytest.fixture
def default_rule():
    return RoutingRule(
        name="default",
        match=MatchCriteria(tool_name_pattern="*"),
        route_to=RouteTarget(agent_id="general-agent"),
        priority=999,
    )


class TestRuleEngineBasics:

    def test_first_match_wins_by_priority(self, finance_rule, code_rule, default_rule):
        engine = RuleEngine([default_rule, finance_rule, code_rule])
        ctx = RequestContext(tool_name="finance_report", user_teams=["accounting"])
        d = engine.evaluate(ctx)
        assert d.matched
        assert d.rule_name == "finance"
        assert d.target_agent_id == "finance-agent"

    def test_falls_through_to_default(self, code_rule, default_rule):
        engine = RuleEngine([code_rule, default_rule])
        ctx = RequestContext(tool_name="unknown_tool")
        d = engine.evaluate(ctx)
        assert d.matched
        assert d.rule_name == "default"
        assert d.target_agent_id == "general-agent"

    def test_no_match(self, finance_rule):
        engine = RuleEngine([finance_rule])
        ctx = RequestContext(tool_name="hr_tool", user_teams=["hr"])
        d = engine.evaluate(ctx)
        assert not d.matched

    def test_disabled_rules_skipped(self, finance_rule, default_rule):
        finance_rule.enabled = False
        engine = RuleEngine([finance_rule, default_rule])
        ctx = RequestContext(tool_name="finance_report", user_teams=["accounting"])
        d = engine.evaluate(ctx)
        assert d.matched
        assert d.rule_name == "default"  # not finance (disabled)


class TestToolNameMatching:

    def test_glob_match(self):
        rule = RoutingRule(
            name="t", match=MatchCriteria(tool_name_pattern="search_*"),
            route_to=RouteTarget(agent_id="a"), priority=1,
        )
        engine = RuleEngine([rule])
        assert engine.evaluate(RequestContext(tool_name="search_docs")).matched
        assert not engine.evaluate(RequestContext(tool_name="translate_text")).matched

    def test_regex_match(self):
        rule = RoutingRule(
            name="t", match=MatchCriteria(tool_name_pattern=r"^(search|find)_.*"),
            route_to=RouteTarget(agent_id="a"), priority=1,
        )
        engine = RuleEngine([rule])
        assert engine.evaluate(RequestContext(tool_name="search_docs")).matched
        assert engine.evaluate(RequestContext(tool_name="find_items")).matched

    def test_match_none_tool_name(self):
        rule = RoutingRule(
            name="t", match=MatchCriteria(tool_name_pattern="*"),
            route_to=RouteTarget(agent_id="a"), priority=1,
        )
        engine = RuleEngine([rule])
        # When tool_name is None, the pattern check is skipped
        d = engine.evaluate(RequestContext(agent_id="agent-001"))
        assert d.matched


class TestAgentIdMatching:

    def test_agent_id_glob(self):
        rule = RoutingRule(
            name="t", match=MatchCriteria(agent_id_pattern="translator-*"),
            route_to=RouteTarget(agent_id="specialized-translator"), priority=1,
        )
        engine = RuleEngine([rule])
        assert engine.evaluate(RequestContext(agent_id="translator-generic")).matched
        assert not engine.evaluate(RequestContext(agent_id="finance-agent")).matched


class TestUserTeamMatching:

    def test_user_in_team(self):
        rule = RoutingRule(
            name="t", match=MatchCriteria(user_teams=["finance", "exec"]),
            route_to=RouteTarget(agent_id="a"), priority=1,
        )
        engine = RuleEngine([rule])
        assert engine.evaluate(RequestContext(user_teams=["finance"])).matched
        assert not engine.evaluate(RequestContext(user_teams=["hr"])).matched
        # Multiple teams — one match is enough
        assert engine.evaluate(RequestContext(user_teams=["hr", "finance"])).matched


class TestContentMatching:

    def test_content_pattern_in_field(self):
        rule = RoutingRule(
            name="pii",
            match=MatchCriteria(
                content_patterns=[r"\bSSN\b"],
                content_fields=["query"],
            ),
            route_to=RouteTarget(agent_id="pii-agent"), priority=1,
        )
        engine = RuleEngine([rule])
        assert engine.evaluate(RequestContext(arguments={"query": "Look up SSN for user"})).matched
        assert not engine.evaluate(RequestContext(arguments={"query": "Hello world"})).matched

    def test_content_case_insensitive(self):
        rule = RoutingRule(
            name="t",
            match=MatchCriteria(
                content_patterns=[r"password"],
                content_fields=["text"],
                case_sensitive=False,
            ),
            route_to=RouteTarget(agent_id="a"), priority=1,
        )
        engine = RuleEngine([rule])
        assert engine.evaluate(RequestContext(arguments={"text": "PASSWORD reset"})).matched

    def test_content_requires_fields(self):
        with pytest.raises(ValueError, match="content_patterns requires content_fields"):
            MatchCriteria(content_patterns=[r"test"])


class TestCIDRMatching:

    def test_cidr_include(self):
        rule = RoutingRule(
            name="t",
            match=MatchCriteria(source_ip_cidrs=["10.0.0.0/8"]),
            route_to=RouteTarget(agent_id="a"), priority=1,
        )
        engine = RuleEngine([rule])
        assert engine.evaluate(RequestContext(source_ip="10.1.2.3")).matched
        assert not engine.evaluate(RequestContext(source_ip="192.168.1.1")).matched

    def test_cidr_exclude(self):
        rule = RoutingRule(
            name="t",
            match=MatchCriteria(
                source_ip_cidrs=["0.0.0.0/0"],
                exclude_ip_cidrs=["10.0.0.0/8"],
            ),
            route_to=RouteTarget(agent_id="a"), priority=1,
        )
        engine = RuleEngine([rule])
        assert engine.evaluate(RequestContext(source_ip="192.168.1.1")).matched
        assert not engine.evaluate(RequestContext(source_ip="10.1.2.3")).matched


class TestWeightedTarget:

    def test_weighted_selection(self):
        """Weighted target should return a valid agent from the list."""
        from plugins.conditional_routing.models import WeightedTarget
        target = RouteTarget(weighted=[
            WeightedTarget(agent_id="v1", weight=90),
            WeightedTarget(agent_id="v2", weight=10),
        ])
        
        ctx = RequestContext(user_email="test@example.com")
        result = _select_weighted(target.weighted, ctx, sticky=False)
        assert result in ("v1", "v2")

    def test_weighted_sticky_session(self):
        from plugins.conditional_routing.models import WeightedTarget
        target = RouteTarget(weighted=[
            WeightedTarget(agent_id="v1", weight=90),
            WeightedTarget(agent_id="v2", weight=10),
        ])
        
        ctx = RequestContext(user_email="test@example.com")
        # Same user should always get same agent
        results = {_select_weighted(target.weighted, ctx, sticky=True) for _ in range(20)}
        assert len(results) == 1
        # Different user may get different agent
        ctx2 = RequestContext(user_email="other@example.com")
        results2 = {_select_weighted(target.weighted, ctx2, sticky=True) for _ in range(20)}
        assert len(results2) == 1


class TestRoutingConfig:

    def test_default_action_passthrough(self):
        cfg = ConditionalRoutingConfig(default_action=DefaultAction.PASSTHROUGH)
        assert cfg.default_action == DefaultAction.PASSTHROUGH

    def test_default_action_deny(self):
        cfg = ConditionalRoutingConfig(default_action=DefaultAction.DENY)
        assert cfg.default_action == DefaultAction.DENY

    def test_audit_enabled_by_default(self):
        cfg = ConditionalRoutingConfig()
        assert cfg.audit_routing_decisions is True


class TestRouteTargetValidation:

    def test_cannot_specify_both_agent_id_and_weighted(self):
        from plugins.conditional_routing.models import WeightedTarget
        with pytest.raises(ValueError, match="Cannot specify both"):
            RouteTarget(
                agent_id="a",
                weighted=[WeightedTarget(agent_id="v1", weight=100)],
            )

    def test_must_specify_target(self):
        with pytest.raises(ValueError, match="must be specified"):
            RouteTarget()

    def test_sticky_requires_weighted(self):
        with pytest.raises(ValueError, match="sticky_session requires weighted"):
            RouteTarget(agent_id="a", sticky_session=True)
