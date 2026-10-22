# -*- coding: utf-8 -*-
"""Unit tests for the CEL rule-predicate evaluator."""

# First-Party
from mcpgateway.services.rule_predicate import PredicateSyntaxError, collect_args_references, evaluate_predicate


def test_comparison():
    assert evaluate_predicate("args.tenant == 'acme'", {"args": {"tenant": "acme"}}) is True
    assert evaluate_predicate("args.tenant == 'acme'", {"args": {"tenant": "other"}}) is False


def test_numeric_body_argument():
    assert evaluate_predicate("args.level > 5", {"args": {"level": 6}}) is True
    assert evaluate_predicate("args.level > 5", {"args": {"level": 5}}) is False


def test_numeric_header_string_needs_int():
    assert evaluate_predicate("int(args.level) > 5", {"args": {"level": "6"}}) is True


def test_logical_operators():
    assert evaluate_predicate("args.a == 'x' && args.b == 'y'", {"args": {"a": "x", "b": "y"}}) is True
    assert evaluate_predicate("args.a == 'x' || args.b == 'y'", {"args": {"a": "x", "b": "z"}}) is True
    assert evaluate_predicate("args.a == 'x' && args.b == 'y'", {"args": {"a": "x", "b": "z"}}) is False


def test_membership_in_list_literal():
    assert evaluate_predicate("subject.id in ['a@x.com', 'b@x.com']", {"subject": {"id": "b@x.com"}}) is True
    assert evaluate_predicate("subject.id in ['a@x.com']", {"subject": {"id": "b@x.com"}}) is False


def test_string_functions():
    assert evaluate_predicate("args.timezone.startsWith('America/')", {"args": {"timezone": "America/Denver"}}) is True
    assert evaluate_predicate("args.timezone.startsWith('America/')", {"args": {"timezone": "Europe/Paris"}}) is False
    assert evaluate_predicate("args.uri.endsWith('.internal')", {"args": {"uri": "db.internal"}}) is True
    assert evaluate_predicate("args.tz.matches('^America/.*')", {"args": {"tz": "America/Chicago"}}) is True
    assert evaluate_predicate("args.tz.size() > 3", {"args": {"tz": "US"}}) is False


def test_contains_rejected():
    try:
        evaluate_predicate("args.tz.contains('America')", {"args": {"tz": "America/Chicago"}})
        raise AssertionError("contains must be rejected")
    except PredicateSyntaxError:
        pass


def test_missing_attribute_is_false():
    assert evaluate_predicate("args.timezone != ''", {"args": {}}) is False
    assert evaluate_predicate("role.team_admin", {"role": {}}) is False


def test_family_truthiness():
    assert evaluate_predicate("role.developer", {"role": {"developer": True}}) is True


def test_combined_families():
    attrs = {"role": {"team_admin": True}, "args": {"tenant": "prod"}, "subject": {"id": "b@x.com"}}
    assert evaluate_predicate("role.team_admin && args.tenant == 'prod'", attrs) is True
    assert evaluate_predicate("role.team_admin && args.tenant == 'dev'", attrs) is False


def test_syntax_errors_rejected():
    for bad in ["", "   ", "args.x ==", "wat.x == 1", "undeclared_root", "args.<<<"]:
        try:
            evaluate_predicate(bad, {})
            raise AssertionError(f"accepted {bad!r}")
        except PredicateSyntaxError:
            pass


def test_evaluation_errors_are_false():
    # int() on a non-numeric string is an evaluation error: no match.
    assert evaluate_predicate("int(args.level) > 5", {"args": {"level": "NaN"}}) is False


def test_collect_args_references():
    assert collect_args_references("subject.id == 'b' && args.timezone.startsWith('America/')") == {"timezone"}
    assert collect_args_references("args['target_timezone'] == 'US/Eastern'") == {"target_timezone"}
    # String literals never count as references.
    assert collect_args_references("'args.fake' == args.timezone") == {"timezone"}
    # Invalid predicates contribute nothing.
    assert collect_args_references("args.<<<") == set()
