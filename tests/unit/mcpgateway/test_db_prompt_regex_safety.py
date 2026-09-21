# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_db_prompt_regex_safety.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Prompt argument validation must be bounded like tool argument validation.
"""

# Standard
import time

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.utils.safe_jsonschema import shutdown_validation_pool, start_validation_pool

REGEX_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"q": {"type": "string", "pattern": "^(a+)+$"}},
}
PLAIN_SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}


@pytest.fixture(autouse=True)
def _pool():
    """Start and stop the validation pool around each test.

    Yields:
        None.
    """
    start_validation_pool()
    yield
    shutdown_validation_pool()


@pytest.mark.timeout(30)
def test_prompt_validation_is_bounded():
    """A catastrophic argument_schema must not freeze prompt rendering."""
    prompt = DbPrompt(name="p", template="hi {q}", argument_schema=REGEX_SCHEMA)
    start = time.perf_counter()
    with pytest.raises(ValueError):
        prompt.validate_arguments({"q": "a" * 40 + "b"})
    assert time.perf_counter() - start < 10.0


def test_prompt_validation_still_accepts_valid_arguments():
    """Existing behavior for valid arguments is unchanged."""
    DbPrompt(name="p", template="hi {name}", argument_schema=PLAIN_SCHEMA).validate_arguments({"name": "Alice"})


def test_prompt_validation_still_rejects_missing_required():
    """Existing rejection behavior is unchanged."""
    with pytest.raises(ValueError):
        DbPrompt(name="p", template="hi {name}", argument_schema=PLAIN_SCHEMA).validate_arguments({})
