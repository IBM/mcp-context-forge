# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_service_helpers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Helper tests for tool_service schema and jq utilities.
"""

# Third-Party
import jsonschema
import pytest

# First-Party
from mcpgateway.services import tool_service


def test_validate_with_cached_schema_success_and_error():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    tool_service._validate_with_cached_schema({"a": "ok"}, schema)

    with pytest.raises(jsonschema.exceptions.ValidationError):
        tool_service._validate_with_cached_schema({"a": 1}, schema)


def test_get_validator_fallback_draft4():
    schema = {
        "$schema": "http://json-schema.org/draft-04/schema#",
        "type": "number",
        "minimum": 0,
        "exclusiveMinimum": True,
    }
    schema_json = tool_service._canonicalize_schema(schema)
    validator_cls, parsed = tool_service._get_validator_class_and_check(schema_json)
    assert parsed["type"] == "number"
    assert validator_cls is not None


def test_extract_using_jq_edge_cases():
    assert tool_service.extract_using_jq({"a": 1}, "") == {"a": 1}
    assert tool_service.extract_using_jq("not json", ".a") == ["Invalid JSON string provided."]
    assert tool_service.extract_using_jq(123, ".a") == ["Input data must be a JSON string, dictionary, or list."]


def test_extract_using_jq_rejects_restricted_builtin():
    """A stored hostile filter is refused at invoke time, not executed."""
    # First-Party
    from mcpgateway.common.models import TextContent
    from mcpgateway.services import tool_service

    result = tool_service.extract_using_jq({"a": 1}, "$ENV")
    assert result == [TextContent(type="text", text="jsonpath filter uses a restricted jq builtin")]


def test_extract_using_jq_does_not_echo_engine_errors(monkeypatch):
    """Filter engine detail goes to the log, never to the caller."""
    # First-Party
    from mcpgateway.common.models import TextContent
    from mcpgateway.services import tool_service
    from mcpgateway.utils.jq_runner import JqFilterError

    monkeypatch.setattr(tool_service, "run_jq_filter", lambda *_args: (_ for _ in ()).throw(JqFilterError("secret path /etc/app/x")))
    result = tool_service.extract_using_jq({"a": 1}, ".a")
    assert result == [TextContent(type="text", text="Error applying jsonpath filter")]
    assert "secret path" not in result[0].text


def test_extract_using_jq_reports_timeout_distinctly(monkeypatch):
    """A timed-out filter is distinguishable from a malformed one."""
    # First-Party
    from mcpgateway.common.models import TextContent
    from mcpgateway.services import tool_service
    from mcpgateway.utils.jq_runner import JqFilterTimeout

    monkeypatch.setattr(tool_service, "run_jq_filter", lambda *_args: (_ for _ in ()).throw(JqFilterTimeout("too slow")))
    result = tool_service.extract_using_jq({"a": 1}, ".a")
    assert result == [TextContent(type="text", text="jsonpath filter exceeded the execution time limit")]


def test_extract_using_jq_reports_busy_distinctly_from_timeout(monkeypatch):
    """A full pool with no free worker is distinguishable from a genuine timeout."""
    # First-Party
    from mcpgateway.common.models import TextContent
    from mcpgateway.services import tool_service
    from mcpgateway.utils.jq_runner import JqFilterBusy

    monkeypatch.setattr(tool_service, "run_jq_filter", lambda *_args: (_ for _ in ()).throw(JqFilterBusy("no free worker")))
    result = tool_service.extract_using_jq({"a": 1}, ".a")
    assert result == [TextContent(type="text", text="jsonpath filter sandbox is busy, try again")]
