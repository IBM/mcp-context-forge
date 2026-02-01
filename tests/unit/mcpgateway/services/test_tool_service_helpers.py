# -*- coding: utf-8 -*-
"""ToolService helper function tests."""

# Standard
from unittest.mock import MagicMock

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


def test_get_validator_class_and_check_fallback():
    tool_service._get_validator_class_and_check.cache_clear()
    legacy_schema = {"type": "number", "minimum": 1, "exclusiveMinimum": True}
    schema_json = tool_service._canonicalize_schema(legacy_schema)
    validator_cls, _ = tool_service._get_validator_class_and_check(schema_json)
    assert validator_cls is not None


def test_extract_using_jq_error_paths():
    assert tool_service.extract_using_jq({"a": 1}, ".missing") == "Error applying jsonpath filter"
    message = tool_service.extract_using_jq({"a": 1}, ".[")
    assert isinstance(message, str)
    assert message.startswith("Error applying jsonpath filter:")


def test_pydantic_payload_helpers_return_none_on_error():
    service = tool_service.ToolService()
    assert service._pydantic_tool_from_payload({"bad": "payload"}) is None
    assert service._pydantic_gateway_from_payload({"bad": "payload"}) is None


@pytest.mark.asyncio
async def test_get_top_tools_cache_hit(monkeypatch):
    service = tool_service.ToolService()
    monkeypatch.setattr("mcpgateway.cache.metrics_cache.is_cache_enabled", lambda: True)
    monkeypatch.setattr("mcpgateway.cache.metrics_cache.metrics_cache.get", lambda key: ["cached"])
    def _fail(*_args, **_kwargs):
        raise AssertionError("should not run")

    monkeypatch.setattr("mcpgateway.services.tool_service.get_top_performers_combined", _fail)
    result = await service.get_top_tools(MagicMock())
    assert result == ["cached"]
