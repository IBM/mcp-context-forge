# -*- coding: utf-8 -*-
"""ToolService helper function tests."""

# Third-Party
import pytest

# First-Party
from mcpgateway.services import tool_service


def test_schema_canonicalization_and_validation():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    canonical = tool_service._canonicalize_schema(schema)
    assert canonical.startswith("{")

    tool_service._validate_with_cached_schema({"a": "ok"}, schema)

    with pytest.raises(Exception):
        tool_service._validate_with_cached_schema({"a": 1}, schema)


def test_get_validator_class_and_check():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    schema_json = tool_service._canonicalize_schema(schema)
    validator_cls, checked_schema = tool_service._get_validator_class_and_check(schema_json)
    assert validator_cls is not None
    assert checked_schema["type"] == "object"


def test_extract_using_jq_variants():
    assert tool_service.extract_using_jq('{"a": 1}', ".a") == [1]
    assert tool_service.extract_using_jq({"a": 2}, ".a") == [2]
    assert tool_service.extract_using_jq('[{"a": 1}, {"a": 2}]', ".[].a") == [1, 2]
    assert tool_service.extract_using_jq("not json", ".a") == ["Invalid JSON string provided."]
    assert tool_service.extract_using_jq(123, ".a") == ["Input data must be a JSON string, dictionary, or list."]
    assert tool_service.extract_using_jq({"a": 1}, "") == {"a": 1}
