# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_jq_guard.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the static jq filter safety gate.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.utils.jq_guard import assert_safe_jq_filter, scan_jq_tokens

DENIED = [
    "$ENV",
    "env",
    "env.CANARY",
    '$ENV["CANARY"]',
    "$ENV|keys",
    ".a|env",
    "[.[]|env]",
    ".a as $x|env",
    "{k:$ENV}",
    "env # trailing comment",
    "$ENV # trailing comment",
    '"\\(env)"',
    '"\\($ENV.CANARY)"',
    '"\\("\\(env)")"',
    "{$ENV}",
    'include "evil"; leak',
    'import "evil" as e; e::leak',
    '"evil"|modulemeta',
    "input",
    "inputs",
    "input_filename",
    "input_line_number",
    "$__loc__",
    "debug",
    "stderr",
]

ALLOWED = [
    ".env",
    ".environment",
    ".inputs",
    '."env"',
    '.["env"]',
    '"env"',
    '"this mentions env and inputs"',
    "# env\n.a",
    ".a.b[].c",
    ".a|select(.b==1)|map(.c)",
    "to_entries|from_entries",
    '{"env": .a}',
    '{"input": .a}',
    "  .a  ",
    "",
    "halt",
    "halt_error",
]

# Harmless constructs the guard rejects anyway. Object-construction keys are
# scanned as code positions, so an unquoted key named after a restricted
# built-in is refused. Quoting the key is the workaround, and the guard stays
# simple rather than growing a context rule that would widen bypass surface.
ACCEPTED_FALSE_POSITIVES = ["{env: .a}", "{env}", "{input: .a}"]


@pytest.mark.parametrize("jq_filter", DENIED)
def test_denied_filters_raise(jq_filter):
    """Every environment, IO, or module-loading construct is rejected."""
    with pytest.raises(ValueError, match="restricted"):
        assert_safe_jq_filter(jq_filter)


@pytest.mark.parametrize("jq_filter", ALLOWED)
def test_allowed_filters_pass(jq_filter):
    """Legitimate field access and string content are not rejected."""
    assert_safe_jq_filter(jq_filter) is None


def test_string_literals_are_not_scanned_as_code():
    """A denied name inside a string literal is data, not a built-in."""
    assert scan_jq_tokens('"env" + "inputs"') == set()


def test_interpolation_is_scanned_as_code():
    """Interpolation holds executable code and must be descended into."""
    assert "env" in scan_jq_tokens('"\\(env)"')


def test_field_access_is_not_a_builtin():
    """An identifier directly after a dot is a field name."""
    assert scan_jq_tokens(".env.inputs") == set()


def test_error_names_the_offending_token():
    """Operators need to know which construct was rejected."""
    with pytest.raises(ValueError, match=r"\$ENV"):
        assert_safe_jq_filter("$ENV")


@pytest.mark.parametrize("jq_filter", ACCEPTED_FALSE_POSITIVES)
def test_unquoted_object_keys_are_refused(jq_filter):
    """Documented false positive: quote an object key named after a built-in."""
    with pytest.raises(ValueError, match="restricted"):
        assert_safe_jq_filter(jq_filter)


def test_quoted_object_key_is_the_workaround():
    """The quoted form of the same filter is accepted."""
    assert assert_safe_jq_filter('{"env": .a}') is None


def test_plain_string_escape_is_not_interpolation():
    """A backslash escape that is not '\\(' stays inside the string, not code."""
    assert scan_jq_tokens('"a\\tb\\"c"') == set()
    assert assert_safe_jq_filter('"a\\tb\\"c"') is None


def test_lone_dollar_advances_without_forming_a_token():
    """A '$' not followed by an identifier is not valid jq and yields no token."""
    assert scan_jq_tokens("$") == set()
    assert scan_jq_tokens("$)") == set()
    assert assert_safe_jq_filter("$)") is None
