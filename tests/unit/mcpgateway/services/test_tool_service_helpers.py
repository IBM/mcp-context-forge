# -*- coding: utf-8 -*-
"""Helper tests for tool_service schema and jq utilities."""

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
