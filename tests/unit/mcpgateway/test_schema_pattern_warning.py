# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_schema_pattern_warning.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Registration warns about regex-bearing schemas. It never rejects them.
"""

# Standard
import logging
import re

# Third-Party
import pytest

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


@pytest.mark.parametrize("pattern", ["^a$", re.compile("^a$", re.IGNORECASE)], ids=["string", "compiled"])
def test_harmful_content_pattern_warns(pattern, caplog):
    """Operator patterns produce a warning in both supported forms.

    Args:
        pattern: An operator-supplied string or compiled pattern.
        caplog: Pytest fixture that captures log records.
    """
    # First-Party
    from plugins.harmful_content_detector.harmful_content_detector import HarmfulContentConfig

    with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.safe_jsonschema"):
        config = HarmfulContentConfig(categories={"custom": [pattern]})

    records = [record for record in caplog.records if getattr(record, "source", None) == "plugin:harmful_content_detector"]
    assert len(records) == 1
    assert records[0].pattern_length == len("^a$")
    assert config.categories["custom"][0].search("A") is not None
    if isinstance(pattern, re.Pattern):
        assert config.categories["custom"][0] is pattern


def test_tool_insert_listener_warns(caplog):
    """Flushing a regex-bearing Tool warns through the ``before_insert`` listener.

    Args:
        caplog: Pytest fixture that captures log records.
    """
    # Third-Party
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    # First-Party
    from mcpgateway.db import Base, Tool

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, caplog.at_level(logging.WARNING):
            session.add(Tool(original_name="weather", custom_name="weather", custom_name_slug="weather", input_schema=RISKY, integration_type="REST", request_type="GET", url="http://example.com"))
            session.flush()
            session.rollback()
    finally:
        engine.dispose()
    assert any(getattr(r, "source", None) == "tool:weather" for r in caplog.records)
