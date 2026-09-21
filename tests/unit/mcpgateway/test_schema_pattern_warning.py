# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_schema_pattern_warning.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Registration warns about regex-bearing schemas. It never rejects them.
"""

# Standard
import logging

# First-Party
from mcpgateway.utils.safe_jsonschema import warn_unprovable_patterns

RISKY = {"type": "object", "properties": {"q": {"type": "string", "pattern": "^(a+)+$"}}}
PLAIN = {"type": "object", "properties": {"q": {"type": "string"}}}


def test_regex_schema_warns(caplog):
    """A regex-bearing schema produces one warning naming its source.

    Args:
        caplog: Pytest fixture that captures log records.
    """
    with caplog.at_level(logging.WARNING):
        warn_unprovable_patterns(RISKY, source="tool:weather")
    assert any(getattr(r, "source", None) == "tool:weather" for r in caplog.records)


def test_plain_schema_is_silent(caplog):
    """A schema with no regex keyword produces no warning.

    Args:
        caplog: Pytest fixture that captures log records.
    """
    with caplog.at_level(logging.WARNING):
        warn_unprovable_patterns(PLAIN, source="tool:weather")
    assert not caplog.records


def test_warning_never_raises():
    """Registration must not fail because of this check."""
    warn_unprovable_patterns(None, source="tool:none")
    warn_unprovable_patterns({"pattern": "("}, source="tool:broken")
    warn_unprovable_patterns([1, 2, 3], source="tool:list")
