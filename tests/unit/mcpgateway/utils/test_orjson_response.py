# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_orjson_response.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Full-coverage unit tests for **mcpgateway.utils.orjson_response**

Tests the ORJSONResponse class for high-performance JSON serialization using orjson.

Running:
    pytest -q --cov=mcpgateway.utils.orjson_response --cov-report=term-missing
Should show **100 %** statement coverage for the target module.
"""

# Standard
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

# Third-Party
import orjson
import pytest
from pydantic import BaseModel

# First-Party
from mcpgateway.utils.orjson_response import ORJSONResponse


class SampleModel(BaseModel):
    """Sample Pydantic model for testing."""

    id: int
    name: str
    active: bool


class TestORJSONResponseBasicSerialization:
    """Test basic serialization of common Python types."""

    def test_serialize_dict(self):
        """Test serialization of a simple dictionary."""
        content = {"message": "Hello World", "status": "ok"}
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        assert result == b'{"message":"Hello World","status":"ok"}'

    def test_serialize_list(self):
        """Test serialization of a list."""
        content = [1, 2, 3, 4, 5]
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        assert result == b"[1,2,3,4,5]"

    def test_serialize_string(self):
        """Test serialization of a string."""
        content = "test string"
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        assert result == b'"test string"'

    def test_serialize_integer(self):
        """Test serialization of an integer."""
        content = 42
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        assert result == b"42"

    def test_serialize_float(self):
        """Test serialization of a float."""
        content = 3.14159
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        assert result == b"3.14159"

    def test_serialize_boolean(self):
        """Test serialization of boolean values."""
        # Test True
        response = ORJSONResponse(content=True)
        result = response.render(True)
        assert result == b"true"

        # Test False
        response = ORJSONResponse(content=False)
        result = response.render(False)
        assert result == b"false"

    def test_serialize_none(self):
        """Test serialization of None."""
        response = ORJSONResponse(content=None)
        result = response.render(None)

        assert isinstance(result, bytes)
        assert result == b"null"


class TestORJSONResponseComplexTypes:
    """Test serialization of complex Python types."""

    def test_serialize_nested_dict(self):
        """Test serialization of nested dictionaries."""
        content = {
            "user": {"id": 1, "name": "Alice", "roles": ["admin", "user"]},
            "metadata": {"created": "2025-01-01", "updated": "2025-01-19"},
        }
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        # orjson produces compact output without spaces
        assert b'"user"' in result
        assert b'"metadata"' in result
        assert b'"admin"' in result

    def test_serialize_datetime(self):
        """Test serialization of datetime objects."""
        dt = datetime(2025, 1, 19, 12, 30, 45, tzinfo=timezone.utc)
        content = {"timestamp": dt}
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        # orjson serializes datetime to RFC 3339 format
        assert b'"timestamp":"2025-01-19T12:30:45+00:00"' in result

    def test_serialize_uuid(self):
        """Test serialization of UUID objects."""
        test_uuid = uuid4()
        content = {"id": test_uuid}
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        # UUID should be serialized as string
        uuid_str = str(test_uuid).encode()
        assert uuid_str in result

    def test_serialize_pydantic_model(self):
        """Test serialization of Pydantic models."""
        model = SampleModel(id=1, name="test", active=True)
        # Pydantic models need to be converted to dict first
        content = {"data": model.model_dump()}
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        assert b'"id":1' in result
        assert b'"name":"test"' in result
        assert b'"active":true' in result

    def test_serialize_empty_list(self):
        """Test serialization of an empty list."""
        content = []
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        assert result == b"[]"

    def test_serialize_empty_dict(self):
        """Test serialization of an empty dictionary."""
        content = {}
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        assert result == b"{}"


class TestORJSONResponseEdgeCases:
    """Test edge cases and special scenarios."""

    def test_serialize_unicode(self):
        """Test serialization of Unicode characters."""
        content = {"message": "Hello 世界 🌍"}
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        # orjson preserves Unicode characters
        decoded = result.decode("utf-8")
        assert "世界" in decoded
        assert "🌍" in decoded

    def test_serialize_large_string(self):
        """Test serialization of a large string."""
        large_string = "x" * 10000
        content = {"data": large_string}
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        assert len(result) > 10000

    def test_serialize_deeply_nested(self):
        """Test serialization of deeply nested structures."""
        # Create a deeply nested structure (10 levels)
        content = {"level1": {"level2": {"level3": {"level4": {"level5": {"level6": {"level7": {"level8": {"level9": {"level10": "deep value"}}}}}}}}}}
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        assert b'"deep value"' in result

    def test_serialize_non_str_keys(self):
        """Test serialization with non-string dict keys (enabled by OPT_NON_STR_KEYS)."""
        # orjson with OPT_NON_STR_KEYS allows integer keys
        content = {1: "one", 2: "two", 3: "three"}
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        # Integer keys are serialized as strings in JSON
        assert b'"1":"one"' in result or b'"1":"one"' in result

    def test_serialize_special_float_values(self):
        """Test serialization of special float values."""
        # Note: orjson does not support NaN or Infinity by default
        # This test verifies that normal floats work
        content = {"pi": 3.14159, "e": 2.71828, "zero": 0.0}
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        assert b"3.14159" in result
        assert b"2.71828" in result
        assert b"0.0" in result or b"0" in result

    def test_serialize_mixed_types(self):
        """Test serialization of mixed types in a single structure."""
        test_uuid = UUID("12345678-1234-5678-1234-567812345678")
        test_datetime = datetime(2025, 1, 19, 12, 0, 0, tzinfo=timezone.utc)

        content = {
            "string": "value",
            "integer": 42,
            "float": 3.14,
            "boolean": True,
            "null": None,
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
            "uuid": test_uuid,
            "datetime": test_datetime,
        }
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        # Verify all types are present in output
        assert b'"string":"value"' in result
        assert b'"integer":42' in result
        assert b'"float":3.14' in result
        assert b'"boolean":true' in result
        assert b'"null":null' in result
        assert b'"list":[1,2,3]' in result


class TestORJSONResponseMediaType:
    """Test media type configuration."""

    def test_media_type_is_json(self):
        """Test that media type is set to application/json."""
        response = ORJSONResponse(content={})
        assert response.media_type == "application/json"


class TestORJSONResponseOptions:
    """Test orjson serialization options."""

    def test_opt_non_str_keys_enabled(self):
        """Test that OPT_NON_STR_KEYS option is enabled."""
        # Integer keys should work
        content = {1: "one", 2: "two"}
        response = ORJSONResponse(content=content)
        result = response.render(content)

        # Should not raise an error
        assert isinstance(result, bytes)

    def test_compact_output(self):
        """Test that orjson produces compact output (no extra whitespace)."""
        content = {"key1": "value1", "key2": "value2"}
        response = ORJSONResponse(content=content)
        result = response.render(content)

        # Compact output should not have extra spaces
        assert b" : " not in result  # No spaces around colons
        assert b", " not in result  # No spaces after commas


class TestORJSONResponsePerformance:
    """Test performance characteristics (relative)."""

    def test_serialize_large_list(self):
        """Test serialization of a large list."""
        # Create a list with 1000 items
        content = [{"id": i, "name": f"item_{i}", "value": i * 1.5} for i in range(1000)]
        response = ORJSONResponse(content=content)
        result = response.render(content)

        assert isinstance(result, bytes)
        # Verify it contains expected data
        assert b'"id":0' in result
        assert b'"id":999' in result

    def test_returns_bytes_not_string(self):
        """Test that render() returns bytes, not string."""
        content = {"test": "value"}
        response = ORJSONResponse(content=content)
        result = response.render(content)

        # Should return bytes, not string
        assert isinstance(result, bytes)
        assert not isinstance(result, str)


class TestORJSONResponseIntegration:
    """Integration tests with FastAPI concepts."""

    def test_response_initialization(self):
        """Test that ORJSONResponse can be initialized with content."""
        content = {"message": "test"}
        response = ORJSONResponse(content=content)

        assert response is not None
        assert hasattr(response, "render")

    def test_response_with_status_code(self):
        """Test that ORJSONResponse can be initialized with status code."""
        content = {"message": "test"}
        response = ORJSONResponse(content=content, status_code=201)

        assert response.status_code == 201

    def test_response_with_headers(self):
        """Test that ORJSONResponse can be initialized with headers."""
        content = {"message": "test"}
        headers = {"X-Custom-Header": "value"}
        response = ORJSONResponse(content=content, headers=headers)

        assert "X-Custom-Header" in response.headers
        assert response.headers["X-Custom-Header"] == "value"


class TestORJSONResponseErrorHandling:
    """Test error handling for invalid inputs."""

    def test_serialize_circular_reference_raises_error(self):
        """Test that circular references raise an error."""
        # Create a circular reference
        content = {"key": "value"}
        content["self"] = content  # Circular reference

        # orjson should raise an error for circular references during initialization
        with pytest.raises(TypeError):
            ORJSONResponse(content=content)

    def test_serialize_custom_object_without_serializer(self):
        """Test serialization of custom object without default serializer."""

        # Custom class without __dict__ or serialization support
        class CustomObject:
            pass

        obj = CustomObject()
        content = {"obj": obj}

        # Should raise TypeError during initialization
        with pytest.raises(TypeError):
            ORJSONResponse(content=content)
