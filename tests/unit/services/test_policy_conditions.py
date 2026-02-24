# -*- coding: utf-8 -*-
"""Unit tests for Phase 2 policy condition evaluator."""

# Standard
from dataclasses import dataclass
from datetime import datetime, timezone

# Third-Party
import pytest

# First-Party
from mcpgateway.services.policy_conditions import evaluate_policy_condition


@dataclass
class Dummy:
    email: str = "user@example.com"
    roles: list[str] = None
    teams: list[str] = None
    is_admin: bool = False
    attributes: dict = None

    def __post_init__(self):
        if self.roles is None:
            self.roles = ["developer"]
        if self.teams is None:
            self.teams = ["team-alpha"]
        if self.attributes is None:
            self.attributes = {"department": "eng"}


def test_atomic_eq():
    subject = Dummy()
    resource = {"visibility": "team"}
    context = {}
    condition = {"op": "eq", "left": "resource.visibility", "right": "team"}
    assert evaluate_policy_condition(condition, subject, resource, context) is True


def test_and_or_not_combination():
    subject = Dummy()
    resource = {"visibility": "team", "team_id": "team-alpha"}
    context = {"ip_address": "10.10.0.1"}
    condition = {
        "all": [
            {"op": "eq", "left": "resource.visibility", "right": "team"},
            {
                "any": [
                    {"op": "contains", "left": "subject.teams", "right": {"var": "resource.team"}},
                    {"op": "eq", "left": "subject.is_admin", "right": True},
                ]
            },
            {"not": {"op": "eq", "left": "context.ip_address", "right": "0.0.0.0"}},
        ]
    }
    assert evaluate_policy_condition(condition, subject, resource, context) is True


def test_subject_custom_attribute():
    subject = Dummy(attributes={"department": "security"})
    condition = {"op": "eq", "left": "subject.department", "right": "security"}
    assert evaluate_policy_condition(condition, subject, {}, {}) is True


def test_resource_tags_contains():
    subject = Dummy()
    resource = {"attributes": {"tags": ["confidential", "internal"]}}
    condition = {"op": "contains", "left": "resource.tags", "right": "internal"}
    assert evaluate_policy_condition(condition, subject, resource, {}) is True


def test_time_comparison():
    subject = Dummy()
    now = datetime.now(timezone.utc)
    earlier = datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat()
    condition = {"op": "gt", "left": {"var": "context.timestamp"}, "right": earlier}
    assert evaluate_policy_condition(condition, subject, {}, {"timestamp": now}) is True


def test_ip_in_cidr():
    subject = Dummy()
    condition = {"op": "ip_in_cidr", "left": "context.ip_address", "right": "10.0.0.0/8"}
    assert evaluate_policy_condition(condition, subject, {}, {"ip_address": "10.1.2.3"}) is True


def test_invalid_node_raises():
    with pytest.raises(ValueError, match="Invalid policy condition node"):
        evaluate_policy_condition({"foo": "bar"}, Dummy(), {}, {})


def test_invalid_operator_raises():
    with pytest.raises(ValueError, match="Unsupported operator"):
        evaluate_policy_condition({"op": "unknown", "left": 1, "right": 2}, Dummy(), {}, {})
