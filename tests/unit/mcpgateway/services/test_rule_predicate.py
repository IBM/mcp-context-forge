# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_rule_predicate.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the CPEX APL predicate evaluator.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.services.rule_predicate import All, PredicateSyntaxError, evaluate_predicate, parse_predicate


def test_truthiness():
    assert evaluate_predicate("role.team_admin", {"role": {"team_admin": True}}) is True
    assert evaluate_predicate("role.team_admin", {"role": {}}) is False
    assert evaluate_predicate("authenticated", {"authenticated": True}) is True


def test_comparison_operators():
    attrs = {"delegation": {"depth": 3}, "client": {"trust_level": "trusted"}}
    assert evaluate_predicate("delegation.depth > 2", attrs) is True
    assert evaluate_predicate("delegation.depth >= 3", attrs) is True
    assert evaluate_predicate("delegation.depth < 2", attrs) is False
    assert evaluate_predicate("delegation.depth <= 3", attrs) is True
    assert evaluate_predicate("client.trust_level == 'trusted'", attrs) is True
    assert evaluate_predicate("client.trust_level != 'untrusted'", attrs) is True


def test_comparison_missing_attribute_is_false():
    assert evaluate_predicate("delegation.depth > 2", {}) is False


def test_comparison_type_mismatch_is_false():
    assert evaluate_predicate("client.trust_level > 2", {"client": {"trust_level": "trusted"}}) is False


def test_membership_and_negation():
    attrs = {"subject": {"id": "u1"}, "allowed": ["u1"], "banned": ["u2"]}
    assert evaluate_predicate("subject.id in allowed", attrs) is True
    assert evaluate_predicate("subject.id not in banned", attrs) is True
    assert evaluate_predicate("subject.id in banned", attrs) is False


def test_membership_missing_collection_is_false():
    assert evaluate_predicate("subject.id in allowed", {"subject": {"id": "u1"}}) is False


def test_existence():
    assert evaluate_predicate("exists(delegation.origin_subject_id)", {"delegation": {"origin_subject_id": "x"}}) is True
    assert evaluate_predicate("exists(delegation.origin_subject_id)", {"delegation": {}}) is False
    assert evaluate_predicate("exists(delegation.origin_subject_id)", {}) is False


def test_conjunction_disjunction_grouping():
    attrs = {"role": {"hr": True, "auditor": False}, "perm": {"view_ssn": True}}
    assert evaluate_predicate("role.hr & perm.view_ssn", attrs) is True
    assert evaluate_predicate("role.hr & role.auditor", attrs) is False
    assert evaluate_predicate("role.hr | role.auditor", attrs) is True
    assert evaluate_predicate("role.auditor | role.hr", attrs) is True
    assert evaluate_predicate("(role.hr | role.auditor) & perm.view_ssn", attrs) is True
    assert evaluate_predicate("role.hr & (role.auditor | perm.view_ssn)", attrs) is True


def test_require_forms():
    attrs = {"role": {"hr": True}, "perm": {"view_ssn": True}}
    assert evaluate_predicate("require(role.hr, perm.view_ssn)", attrs) is True
    assert evaluate_predicate("require(role.hr, role.auditor)", attrs) is False
    assert evaluate_predicate("require(role.hr | role.auditor)", attrs) is True


def test_syntax_error_on_injection():
    with pytest.raises(PredicateSyntaxError):
        evaluate_predicate("role.hr; DROP TABLE", {})
    with pytest.raises(PredicateSyntaxError):
        evaluate_predicate("role.hr and perm.view_ssn", {})


def test_syntax_error_on_deep_path():
    with pytest.raises(PredicateSyntaxError):
        parse_predicate("a.b.c")


def test_syntax_error_on_empty_and_trailing():
    with pytest.raises(PredicateSyntaxError):
        parse_predicate("")
    with pytest.raises(PredicateSyntaxError):
        parse_predicate("role.hr)")
    with pytest.raises(PredicateSyntaxError):
        parse_predicate("role.hr 'unterminated")


def test_parse_returns_node_tree():
    node = parse_predicate("role.hr & perm.view_ssn")
    assert isinstance(node, All)
    assert [type(c).__name__ for c in node.children] == ["Truthiness", "Truthiness"]


def test_args_truthiness():
    assert evaluate_predicate("args.customer_id", {"args": {"customer_id": "abc"}}) is True
    assert evaluate_predicate("args.customer_id", {"args": {}}) is False


def test_args_comparison():
    assert evaluate_predicate("args.tenant == 'acme'", {"args": {"tenant": "acme"}}) is True
    assert evaluate_predicate("args.level > 5", {"args": {"level": 10}}) is True
    assert evaluate_predicate("args.level > 5", {"args": {}}) is False


def test_args_membership():
    assert evaluate_predicate("args.region in allowed_regions", {"args": {"region": "us"}, "allowed_regions": ["us", "eu"]}) is True


def test_args_exists():
    assert evaluate_predicate("exists(args.optional)", {"args": {"optional": "x"}}) is True
    assert evaluate_predicate("exists(args.optional)", {"args": {}}) is False


def test_args_combined_with_role():
    attrs = {"role": {"admin": True}, "args": {"tenant": "prod"}}
    assert evaluate_predicate("role.admin & args.tenant == 'prod'", attrs) is True
    assert evaluate_predicate("role.admin & args.tenant == 'dev'", attrs) is False
