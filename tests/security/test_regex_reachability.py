# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_regex_reachability.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Prove no validation path reaches an unbounded regex engine in this process.

A grep over first-party code cannot establish this: the escape found in review lived in
site-packages. This module verifies by execution instead, in three layers.

1. A positive routing assertion. It spies on the sandbox pool and asserts each call site
   submits a regex-bearing schema to the sandbox, and submits nothing for a schema without
   one. Only this layer can prove routing happened.
2. An in-process pattern tripwire. It replaces the ``pattern`` and ``patternProperties``
   keyword implementations in every stock draft with a function that raises. Any pattern
   evaluated in this process fails the test by name.
3. A direct-call tripwire. It makes ``jsonschema.validate`` raise. Nothing calls that
   function today, so this layer guards against a future regression that reintroduces one.

The sandbox worker is a separate process, so none of these in-process patches reach it. A
correctly routed validation therefore still succeeds while the tripwires are armed. That
asymmetry is the whole design: a path that validates in-process fails, a path that routes
to the sandbox passes.

Each layer has a self-test that proves the layer can fail.
"""

# Standard
from contextlib import ExitStack
from unittest.mock import patch

# Third-Party
import jsonschema
import pytest

# First-Party
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.services.tool_service import _validate_tool_input_arguments, _validate_with_cached_schema
from mcpgateway.utils import safe_jsonschema
from mcpgateway.utils.safe_jsonschema import shutdown_validation_pool, start_validation_pool

REGEX_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"q": {"type": "string", "pattern": "^[a-z]+$"}},
}

PLAIN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"q": {"type": "string"}},
}

# Every stock draft the sandbox can reproduce. Each one holds its own keyword table.
_DRAFTS = (
    jsonschema.Draft4Validator,
    jsonschema.Draft6Validator,
    jsonschema.Draft7Validator,
    jsonschema.Draft201909Validator,
    jsonschema.Draft202012Validator,
)

# Both keywords whose values are regular expressions, matching the router in
# ``safe_jsonschema._REGEX_KEYWORDS``.
_REGEX_KEYWORDS = ("pattern", "patternProperties")


class _Tripwire(Exception):
    """Raised when a guarded entry point is reached in-process."""


def _boom(*args, **kwargs):
    """Raise when called.

    Args:
        *args: Ignored.
        **kwargs: Ignored.

    Raises:
        _Tripwire: Always.
    """
    raise _Tripwire("unbounded validation reached in-process")


@pytest.fixture(autouse=True)
def _pool():
    """Start and stop the validation pool around each test.

    Yields:
        None.
    """
    start_validation_pool()
    yield
    shutdown_validation_pool()


@pytest.fixture(name="tripwire")
def _tripwire():
    """Make every in-process unbounded validation entry point raise.

    Patching ``jsonschema._keywords.pattern`` does not work: each draft's ``VALIDATORS``
    table captured the function object at import time, so the module attribute is never
    read again. The keyword tables are patched instead, which was verified to fire.

    The sandbox worker is a separate process and is unaffected by these patches, so a
    correctly routed validation still succeeds.

    Yields:
        None.
    """
    with ExitStack() as stack:
        for draft in _DRAFTS:
            stack.enter_context(patch.dict(draft.VALIDATORS, {keyword: _boom for keyword in _REGEX_KEYWORDS}))
        stack.enter_context(patch("jsonschema.validate", side_effect=_boom))
        yield


@pytest.fixture(name="submit")
def _submit():
    """Spy on the validation sandbox without changing what it does.

    Yields:
        unittest.mock.MagicMock: The wrapped ``SandboxPool.submit``, carrying the call count.
    """
    original = safe_jsonschema._SANDBOX.submit  # pylint: disable=protected-access
    with patch.object(safe_jsonschema._SANDBOX, "submit", wraps=original) as spy:  # pylint: disable=protected-access
        yield spy


# --------------------------------------------------------------------------------------
# Layer self-tests. A tripwire that cannot fire is indistinguishable from one that proves
# everything, so each layer proves it can fail before it is trusted below.
# --------------------------------------------------------------------------------------


@pytest.mark.timeout(30)
@pytest.mark.parametrize("draft", _DRAFTS, ids=[draft.__name__ for draft in _DRAFTS])
def test_pattern_tripwire_fires_for_every_draft(draft):
    """Layer 2 self-test: the patched keyword table must actually be consulted.

    Args:
        draft: A stock jsonschema draft validator class.
    """
    with patch.dict(draft.VALIDATORS, {"pattern": _boom}):
        with pytest.raises(_Tripwire):
            draft({"type": "object", "properties": {"q": {"type": "string", "pattern": "^[a-z]+$"}}}).validate({"q": "abc"})


@pytest.mark.timeout(30)
def test_direct_call_tripwire_fires():
    """Layer 3 self-test: the ``jsonschema.validate`` patch must be capable of failing."""
    with patch("jsonschema.validate", side_effect=_boom):
        with pytest.raises(_Tripwire):
            jsonschema.validate(instance={}, schema={})


@pytest.mark.timeout(30)
def test_routing_spy_fires(submit):
    """Layer 1 self-test: the spy must count a real submission.

    A spy that never records would make every routing assertion below vacuous.

    Args:
        submit: The sandbox submission spy.
    """
    safe_jsonschema.validate_safely({"q": "abc"}, REGEX_SCHEMA, jsonschema.Draft202012Validator)
    assert submit.call_count == 1


# --------------------------------------------------------------------------------------
# Layer 1: positive routing assertion, per call site.
# --------------------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_tool_input_path_routes_regex_schema_to_the_sandbox(submit):
    """Site 1 must submit a regex-bearing schema to the sandbox.

    Args:
        submit: The sandbox submission spy.
    """
    assert _validate_tool_input_arguments({"q": "abc"}, REGEX_SCHEMA) is None
    assert submit.call_count == 1, "the tool input path validated a regex-bearing schema in-process"


@pytest.mark.timeout(30)
def test_tool_output_path_routes_regex_schema_to_the_sandbox(submit):
    """Site 2 must submit a regex-bearing schema to the sandbox.

    Args:
        submit: The sandbox submission spy.
    """
    _validate_with_cached_schema({"q": "abc"}, REGEX_SCHEMA)
    assert submit.call_count == 1, "the tool output path validated a regex-bearing schema in-process"


@pytest.mark.timeout(30)
def test_prompt_path_routes_regex_schema_to_the_sandbox(submit):
    """Site 3 must submit a regex-bearing schema to the sandbox.

    Args:
        submit: The sandbox submission spy.
    """
    DbPrompt(name="p", template="hi {q}", argument_schema=REGEX_SCHEMA).validate_arguments({"q": "abc"})
    assert submit.call_count == 1, "the prompt path validated a regex-bearing schema in-process"


@pytest.mark.timeout(30)
def test_schema_without_a_regex_keyword_never_reaches_the_sandbox(submit):
    """No call site may pay for the sandbox when the schema carries no regex keyword.

    Args:
        submit: The sandbox submission spy.
    """
    assert _validate_tool_input_arguments({"q": "abc"}, PLAIN_SCHEMA) is None
    _validate_with_cached_schema({"q": "abc"}, PLAIN_SCHEMA)
    DbPrompt(name="p", template="hi {q}", argument_schema=PLAIN_SCHEMA).validate_arguments({"q": "abc"})
    assert submit.call_count == 0, "a schema with no regex keyword must be validated inline"


# --------------------------------------------------------------------------------------
# Layers 2 and 3: tripwires armed, per call site.
# --------------------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_tool_input_path_does_not_validate_in_process(tripwire):
    """Site 1 must reach no unbounded regex engine in this process.

    Args:
        tripwire: The armed in-process tripwires.
    """
    assert _validate_tool_input_arguments({"q": "abc"}, REGEX_SCHEMA) is None


@pytest.mark.timeout(30)
def test_tool_output_path_does_not_validate_in_process(tripwire):
    """Site 2 shares the same helper and must behave the same.

    Args:
        tripwire: The armed in-process tripwires.
    """
    _validate_with_cached_schema({"q": "abc"}, REGEX_SCHEMA)


@pytest.mark.timeout(30)
def test_prompt_path_does_not_validate_in_process(tripwire):
    """Site 3 previously called stock ``jsonschema.validate`` directly.

    Args:
        tripwire: The armed in-process tripwires.
    """
    DbPrompt(name="p", template="hi {q}", argument_schema=REGEX_SCHEMA).validate_arguments({"q": "abc"})


# --------------------------------------------------------------------------------------
# The sandbox still reports a real failure, so a passing path above is not a silent skip.
# --------------------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_sandbox_still_reports_an_invalid_instance(tripwire):
    """An instance that breaks the pattern must fail, proving the pattern was evaluated.

    Without this, every test above would also pass if the sandbox ignored the schema.

    Args:
        tripwire: The armed in-process tripwires.
    """
    assert _validate_tool_input_arguments({"q": "ABC"}, REGEX_SCHEMA) is not None
    with pytest.raises(jsonschema.exceptions.ValidationError):
        _validate_with_cached_schema({"q": "ABC"}, REGEX_SCHEMA)
    with pytest.raises(ValueError):
        DbPrompt(name="p", template="hi {q}", argument_schema=REGEX_SCHEMA).validate_arguments({"q": "ABC"})
