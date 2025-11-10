import json

import pytest

from mcpgateway.services.tool_service import ToolService
from mcpgateway.models import TextContent


class DummyToolResult:
    def __init__(self, content=None):
        self.content = content or []
        self.structured_content = None
        self.is_error = False


def make_tool(output_schema):
    return type("T", (object,), {"output_schema": output_schema, "name": "dummy"})()


def test_no_schema_returns_true_and_unchanged():
    service = ToolService()
    tool = make_tool(None)
    # content is a JSON text but no schema -> nothing to validate
    tr = DummyToolResult(content=[{"type": "text", "text": json.dumps({"a": 1})}])
    ok = service._extract_and_validate_structured_content(tool, tr)
    assert ok is True
    assert tr.structured_content is None
    assert tr.is_error is False


def test_valid_candidate_attaches_structured_content():
    service = ToolService()
    tool = make_tool({"type": "object", "properties": {"foo": {"type": "string"}}, "required": ["foo"]})
    tr = DummyToolResult(content=[])
    ok = service._extract_and_validate_structured_content(tool, tr, candidate={"foo": "bar"})
    assert ok is True
    assert tr.structured_content == {"foo": "bar"}
    assert tr.is_error is False


def test_invalid_candidate_marks_error_and_emits_details():
    service = ToolService()
    tool = make_tool({"type": "object", "properties": {"foo": {"type": "string"}}, "required": ["foo"]})
    tr = DummyToolResult(content=[])
    ok = service._extract_and_validate_structured_content(tool, tr, candidate={"foo": 123})
    assert ok is False
    assert tr.is_error is True
    # content should be replaced with a TextContent describing the error
    assert isinstance(tr.content, list) and len(tr.content) == 1
    tc = tr.content[0]
    # The function attempts to set a TextContent instance; if it's a model-like object, inspect text
    text = tc.text if hasattr(tc, "text") else str(tc)
    details = json.loads(text)
    assert "received" in details


def test_parse_textcontent_json_and_validate_object_schema():
    service = ToolService()
    tool = make_tool({"type": "object", "properties": {"foo": {"type": "string"}}, "required": ["foo"]})
    payload = {"foo": "baz"}
    tr = DummyToolResult(content=[{"type": "text", "text": json.dumps(payload)}])
    ok = service._extract_and_validate_structured_content(tool, tr)
    assert ok is True
    assert tr.structured_content == payload


def test_unwrap_single_element_list_wrapper_with_textcontent_inner():
    service = ToolService()
    # Schema expects an object
    tool = make_tool({"type": "object", "properties": {"foo": {"type": "string"}}, "required": ["foo"]})
    inner = {"type": "text", "text": json.dumps({"foo": "inner"})}
    wrapped_list = [inner]
    # The first TextContent contains JSON encoding of the list with inner TextContent-like dict
    tr = DummyToolResult(content=[{"type": "text", "text": json.dumps(wrapped_list)}])
    ok = service._extract_and_validate_structured_content(tool, tr)
    assert ok is True
    assert tr.structured_content == {"foo": "inner"}


def test_wrap_primitive_into_result_when_schema_expects_object():
    service = ToolService()
    # Schema expects object with 'result' integer
    tool = make_tool({
        "type": "object",
        "properties": {"result": {"type": "integer"}},
        "required": ["result"],
    })
    # Provide primitive JSON in the first text content
    tr = DummyToolResult(content=[{"type": "text", "text": json.dumps(42)}])
    ok = service._extract_and_validate_structured_content(tool, tr)
    assert ok is True
    assert tr.structured_content == {"result": 42}
