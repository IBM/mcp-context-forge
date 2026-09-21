# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_service_regex_safety.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tool input and output validation must be bounded.
"""

# Standard
import time

# Third-Party
import jsonschema
import pytest

# First-Party
from mcpgateway.services.tool_service import _validate_tool_input_arguments, _validate_with_cached_schema
from mcpgateway.utils.safe_jsonschema import shutdown_validation_pool, start_validation_pool

CATASTROPHIC_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"q": {"type": "string", "pattern": "^(a+)+$"}},
}


@pytest.fixture(autouse=True)
def _pool():
    """Start and stop the validation pool around each test.

    Yields:
        None.
    """
    start_validation_pool()
    yield
    shutdown_validation_pool()


def test_input_validation_is_bounded_and_fails_closed():
    """A hostile subject must not run unbounded, and must not be reported as valid."""
    start = time.perf_counter()
    error = _validate_tool_input_arguments({"q": "a" * 40 + "b"}, CATASTROPHIC_SCHEMA)
    elapsed = time.perf_counter() - start
    assert elapsed < 10.0, f"validation took {elapsed:.1f}s; the sandbox did not bound it"
    assert error is not None, "a truncated validation must fail closed"


def test_output_validation_is_bounded():
    """Site 2: output schemas come from a remote server and need the same bound."""
    start = time.perf_counter()
    with pytest.raises(jsonschema.exceptions.ValidationError):
        _validate_with_cached_schema({"q": "a" * 40 + "b"}, CATASTROPHIC_SCHEMA)
    assert time.perf_counter() - start < 10.0


def test_valid_subject_still_validates():
    """A matching subject keeps working."""
    assert _validate_tool_input_arguments({"q": "aaaa"}, CATASTROPHIC_SCHEMA) is None


def test_schema_without_regex_is_unaffected():
    """A schema with no regex keyword behaves exactly as before."""
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    assert _validate_tool_input_arguments({"n": 1}, schema) is None
    assert _validate_tool_input_arguments({}, schema) is not None


def test_non_local_ref_guard_still_applies():
    """The SSRF guard must survive the change."""
    with pytest.raises(jsonschema.exceptions.SchemaError):
        _validate_with_cached_schema({}, {"$ref": "https://evil.example/schema.json"})
