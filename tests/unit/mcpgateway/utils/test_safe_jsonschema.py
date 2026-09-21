# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_safe_jsonschema.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Routing and fail-closed tests for bounded schema validation.

The corpus covers every category that broke the v1 design: nested quantifiers, quantified
alternation, adjacent unbounded repeats, negated classes, dot-based polynomial patterns,
and patterns reachable only through additionalProperties.
"""

# Standard
import logging
import time
from unittest.mock import patch

# Third-Party
import jsonschema
import pytest

# First-Party
from mcpgateway.utils import safe_jsonschema
from mcpgateway.utils.safe_jsonschema import sandbox_unavailable, schema_uses_regex, shutdown_validation_pool, start_validation_pool, validate_safely

DRAFT = jsonschema.Draft202012Validator

# Every one of these froze a gateway worker under the v1 design.
HOSTILE = [
    ("nested quantifier", r"^(a+)+$", "a" * 40 + "b"),
    ("quantified alternation", r"^(a|aa)+$", "a" * 40 + "b"),
    ("adjacent repeats", r"^(a+)(a+)(a+)(a+)(a+)(a+)(a+)(a+)(a+)(a+)$", "a" * 45 + "b"),
    ("negated class", r"^[^,]*[^,]*[^,]*[^,]*[^,]*[^,]*[^,]*[^,]*[^,]*[^,]*$", "a" * 40 + ","),
    ("dot polynomial", r"^.*a.*a.*a$", "a" * 3000 + "!"),
]

# The wording validate_safely produces when the sandbox stopped the work. A pattern that
# merely fails to match produces a jsonschema mismatch message instead, so this phrase tells
# "the budget bounded it" apart from "it happened to reject quickly".
BOUNDED = "could not be completed safely"


@pytest.fixture(autouse=True)
def _pool():
    """Start and stop the validation pool around each test.

    Yields:
        None.
    """
    start_validation_pool()
    yield
    shutdown_validation_pool()


def test_schema_without_regex_is_detected():
    """A schema with no regex keyword takes the inline path."""
    assert schema_uses_regex({"type": "object", "properties": {"a": {"type": "string"}}}) is False


@pytest.mark.parametrize(
    "schema",
    [
        {"pattern": "^a$"},
        {"properties": {"x": {"pattern": "^a$"}}},
        {"patternProperties": {"^a$": {"type": "string"}}},
        {"$defs": {"d": {"pattern": "^a$"}}},
        {"items": [{"anyOf": [{"pattern": "^a$"}]}]},
    ],
)
def test_regex_keyword_is_detected_at_any_depth(schema):
    """Any regex keyword anywhere routes the whole validation to the sandbox.

    Args:
        schema: A JSON Schema that carries a regex keyword at some depth.
    """
    assert schema_uses_regex(schema) is True


def test_regex_schema_is_submitted_to_the_sandbox_and_plain_schema_is_not():
    """The regex keyword, and only the regex keyword, puts a validation in the sandbox.

    A timing test can only ever be circumstantial about routing. This asserts the
    submission itself, so a change that validates a regex schema inline fails here even
    when every elapsed-time ceiling still holds.
    """
    original = safe_jsonschema._SANDBOX.submit  # pylint: disable=protected-access
    with patch.object(safe_jsonschema._SANDBOX, "submit", wraps=original) as submit:  # pylint: disable=protected-access
        validate_safely({"n": 1}, {"type": "object", "properties": {"n": {"type": "integer"}}}, DRAFT)
        assert submit.call_count == 0, "a schema with no regex keyword must not reach the sandbox"

        validate_safely({"q": "abc"}, {"type": "object", "properties": {"q": {"type": "string", "pattern": "^[a-z]+$"}}}, DRAFT)
        assert submit.call_count == 1, "a schema carrying a regex keyword must be validated in the sandbox, never inline"


@pytest.mark.parametrize("label,pattern,subject", HOSTILE, ids=[c[0] for c in HOSTILE])
def test_hostile_pattern_is_bounded_and_fails_closed(label, pattern, subject):
    """Every category that broke v1 must now be bounded and reported as a failure.

    Elapsed time alone cannot prove this. A pattern that rejects quickly also finishes
    under the ceiling, so the message must show the safety budget stopped the work.

    Args:
        label: Short name of the hostile category, used in the failure message.
        pattern: The regex the schema carries.
        subject: The instance value that drives the pattern into backtracking.
    """
    schema = {"type": "object", "properties": {"q": {"type": "string", "pattern": pattern}}}
    start = time.perf_counter()
    with pytest.raises(jsonschema.exceptions.ValidationError) as excinfo:
        validate_safely({"q": subject}, schema, DRAFT)
    elapsed = time.perf_counter() - start
    assert elapsed < 10.0, f"{label} took {elapsed:.1f}s; the sandbox did not bound it"
    assert BOUNDED in str(excinfo.value), f"{label} failed for another reason, so nothing proves the sandbox bounded it: {excinfo.value}"


def test_additional_properties_bypass_is_bounded():
    """jsonschema reaches stock re through additionalProperties, not the pattern keyword.

    This is the escape that defeated the v1 keyword override.
    """
    schema = {
        "type": "object",
        "patternProperties": {r"^(a+)+$": {"type": "string"}},
        "additionalProperties": False,
    }
    start = time.perf_counter()
    try:
        validate_safely({"a" * 40 + "b": "x"}, schema, DRAFT)
    except jsonschema.exceptions.ValidationError:
        pass
    assert time.perf_counter() - start < 10.0


def test_unevaluated_properties_bypass_is_bounded():
    """Same escape, via unevaluatedProperties."""
    schema = {
        "type": "object",
        "patternProperties": {r"^(a+)+$": {"type": "string"}},
        "unevaluatedProperties": False,
    }
    start = time.perf_counter()
    try:
        validate_safely({"a" * 40 + "b": "x"}, schema, DRAFT)
    except jsonschema.exceptions.ValidationError:
        pass
    assert time.perf_counter() - start < 10.0


def test_valid_subject_still_validates():
    """A matching subject keeps working and stays fast."""
    schema = {"type": "object", "properties": {"q": {"type": "string", "pattern": "^(a+)+$"}}}
    start = time.perf_counter()
    validate_safely({"q": "a" * 5000}, schema, DRAFT)
    assert time.perf_counter() - start < 5.0


def test_ordinary_schema_behaves_as_before():
    """A normal regex schema still accepts and rejects correctly."""
    schema = {"type": "object", "properties": {"name": {"type": "string", "pattern": "^[a-z]+$"}}}
    validate_safely({"name": "alice"}, schema, DRAFT)
    with pytest.raises(jsonschema.exceptions.ValidationError):
        validate_safely({"name": "Alice"}, schema, DRAFT)


def test_oversized_instance_fails_closed():
    """An instance above the cap is refused rather than submitted."""
    schema = {"type": "object", "properties": {"q": {"type": "string", "pattern": "^a+$"}}}
    with pytest.raises(jsonschema.exceptions.ValidationError):
        validate_safely({"q": "a" * (512 * 1024)}, schema, DRAFT)


def test_broken_pool_fails_closed():
    """A pool failure surfaces an error; it never reports success."""
    # First-Party
    from mcpgateway.utils.sandbox_pool import SandboxError

    schema = {"type": "object", "properties": {"q": {"type": "string", "pattern": "^a+$"}}}
    with patch("mcpgateway.utils.safe_jsonschema._SANDBOX.submit", side_effect=SandboxError("boom")):
        with pytest.raises(jsonschema.exceptions.ValidationError):
            validate_safely({"q": "aaa"}, schema, DRAFT)


def test_no_sandbox_refuses_regex_schema():
    """With no sandbox, a regex-bearing schema is refused, never executed inline."""
    schema = {"type": "object", "properties": {"q": {"type": "string", "pattern": "^(a+)+$"}}}
    with patch("mcpgateway.utils.safe_jsonschema.sandbox_unavailable", return_value=True):
        with pytest.raises(jsonschema.exceptions.ValidationError):
            validate_safely({"q": "aaa"}, schema, DRAFT)


def test_start_failure_names_its_cause(caplog):
    """A start failure names the real cause, rather than blaming the platform.

    A configuration fault and an unsupported platform both stop the sandbox. An operator
    reading only "unavailable on this platform" investigates the wrong thing.

    Args:
        caplog: The pytest log capture fixture.
    """
    with patch.object(safe_jsonschema._SANDBOX, "start", side_effect=RuntimeError("settings rejected a placeholder")):  # pylint: disable=protected-access
        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.safe_jsonschema"):
            start_validation_pool()

    assert sandbox_unavailable() is True
    assert "RuntimeError: settings rejected a placeholder" in caplog.text
    start_validation_pool()


def test_no_sandbox_still_validates_schema_without_regex():
    """A schema with no regex keyword is unaffected by sandbox availability."""
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
    with patch("mcpgateway.utils.safe_jsonschema.sandbox_unavailable", return_value=True):
        validate_safely({"n": 1}, schema, DRAFT)
