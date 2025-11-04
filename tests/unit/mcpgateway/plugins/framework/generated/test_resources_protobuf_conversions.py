# -*- coding: utf-8 -*-
"""Tests for Resource hook Pydantic to Protobuf conversions.

This module tests the model_dump_pb() and model_validate_pb() methods
for resource hook payload classes.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import ResourceContent
from mcpgateway.plugins.framework.hooks.resources import (
    ResourcePostFetchPayload,
    ResourcePreFetchPayload,
)

# Check if protobuf is available
try:
    import google.protobuf  # noqa: F401

    PROTOBUF_AVAILABLE = True
except ImportError:
    PROTOBUF_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PROTOBUF_AVAILABLE, reason="protobuf not installed")


class TestResourcePreFetchPayloadConversion:
    """Test ResourcePreFetchPayload Pydantic <-> Protobuf conversion."""

    def test_basic_conversion(self):
        """Test basic ResourcePreFetchPayload conversion to protobuf and back."""
        payload = ResourcePreFetchPayload(uri="file:///data.txt")

        # Convert to protobuf
        proto_payload = payload.model_dump_pb()

        # Verify protobuf fields
        assert proto_payload.uri == "file:///data.txt"

        # Convert back to Pydantic
        restored = ResourcePreFetchPayload.model_validate_pb(proto_payload)

        # Verify restoration
        assert restored.uri == payload.uri
        assert restored.metadata == {}

    def test_with_metadata(self):
        """Test ResourcePreFetchPayload with metadata."""
        payload = ResourcePreFetchPayload(
            uri="http://api/data",
            metadata={"Accept": "application/json", "version": "1.0"},
        )

        proto_payload = payload.model_dump_pb()
        restored = ResourcePreFetchPayload.model_validate_pb(proto_payload)

        assert restored.uri == "http://api/data"
        assert restored.metadata["Accept"] == "application/json"
        assert restored.metadata["version"] == "1.0"

    def test_with_nested_metadata(self):
        """Test ResourcePreFetchPayload with nested metadata."""
        payload = ResourcePreFetchPayload(
            uri="file:///docs/readme.md",
            metadata={
                "version": "1.0",
                "auth": {"type": "bearer", "token": "abc123"},
                "cache": {"ttl": 3600, "enabled": True},
            },
        )

        proto_payload = payload.model_dump_pb()
        restored = ResourcePreFetchPayload.model_validate_pb(proto_payload)

        assert restored.uri == "file:///docs/readme.md"
        assert "auth" in restored.metadata
        assert "cache" in restored.metadata

    def test_with_various_uri_schemes(self):
        """Test ResourcePreFetchPayload with various URI schemes."""
        uris = [
            "file:///path/to/file.txt",
            "http://example.com/resource",
            "https://api.example.com/v1/data",
            "s3://bucket/key",
            "custom://resource/path",
        ]

        for uri in uris:
            payload = ResourcePreFetchPayload(uri=uri)
            proto_payload = payload.model_dump_pb()
            restored = ResourcePreFetchPayload.model_validate_pb(proto_payload)
            assert restored.uri == uri

    def test_roundtrip_conversion(self):
        """Test that multiple roundtrips maintain data integrity."""
        original = ResourcePreFetchPayload(
            uri="test://resource",
            metadata={"key": "value", "count": 42},
        )

        proto1 = original.model_dump_pb()
        restored1 = ResourcePreFetchPayload.model_validate_pb(proto1)
        proto2 = restored1.model_dump_pb()
        restored2 = ResourcePreFetchPayload.model_validate_pb(proto2)

        assert original.uri == restored2.uri
        assert "key" in restored2.metadata


class TestResourcePostFetchPayloadConversion:
    """Test ResourcePostFetchPayload Pydantic <-> Protobuf conversion."""

    def test_basic_conversion_with_resource_content(self):
        """Test basic ResourcePostFetchPayload with ResourceContent."""
        content = ResourceContent(
            type="resource",
            id="res-1",
            uri="file:///data.txt",
            text="Hello World",
        )
        payload = ResourcePostFetchPayload(uri="file:///data.txt", content=content)

        proto_payload = payload.model_dump_pb()
        assert proto_payload.uri == "file:///data.txt"

        restored = ResourcePostFetchPayload.model_validate_pb(proto_payload)
        assert restored.uri == "file:///data.txt"
        assert restored.content["text"] == "Hello World"
        assert restored.content["type"] == "resource"

    def test_with_dict_content(self):
        """Test ResourcePostFetchPayload with dict content."""
        content = {"data": "test data", "size": 1024, "encoding": "utf-8"}
        payload = ResourcePostFetchPayload(uri="test://resource", content=content)

        proto_payload = payload.model_dump_pb()
        restored = ResourcePostFetchPayload.model_validate_pb(proto_payload)

        assert restored.content["data"] == "test data"
        assert restored.content["size"] == 1024
        assert restored.content["encoding"] == "utf-8"

    def test_with_string_content(self):
        """Test ResourcePostFetchPayload with string content."""
        payload = ResourcePostFetchPayload(uri="file:///text.txt", content="Plain text content")

        proto_payload = payload.model_dump_pb()
        restored = ResourcePostFetchPayload.model_validate_pb(proto_payload)

        # String content is wrapped in "value" key
        assert restored.content == "Plain text content"

    def test_with_binary_like_content(self):
        """Test ResourcePostFetchPayload with binary-like content."""
        content = ResourceContent(
            type="resource",
            id="res-binary",
            uri="file:///image.png",
            blob="base64encodeddata",
            mime_type="image/png",
        )
        payload = ResourcePostFetchPayload(uri="file:///image.png", content=content)

        proto_payload = payload.model_dump_pb()
        restored = ResourcePostFetchPayload.model_validate_pb(proto_payload)

        assert restored.content["blob"] == "base64encodeddata"
        # Note: mime_type field name is preserved
        assert restored.content["mime_type"] == "image/png"

    def test_with_nested_content_structure(self):
        """Test ResourcePostFetchPayload with nested content."""
        content = {
            "metadata": {"author": "Alice", "created": "2024-01-01"},
            "data": {"sections": [{"title": "Intro", "content": "..."}]},
        }
        payload = ResourcePostFetchPayload(uri="doc://complex", content=content)

        proto_payload = payload.model_dump_pb()
        restored = ResourcePostFetchPayload.model_validate_pb(proto_payload)

        assert "metadata" in restored.content
        assert "data" in restored.content

    def test_with_none_content(self):
        """Test ResourcePostFetchPayload with None content."""
        payload = ResourcePostFetchPayload(uri="empty://resource", content=None)

        proto_payload = payload.model_dump_pb()
        restored = ResourcePostFetchPayload.model_validate_pb(proto_payload)

        assert restored.uri == "empty://resource"
        # Note: protobuf Struct converts None to empty dict {}
        assert restored.content == {} or restored.content is None

    def test_roundtrip_conversion(self):
        """Test that multiple roundtrips maintain data integrity."""
        content = ResourceContent(
            type="resource",
            id="res-roundtrip",
            uri="test://data",
            text="Test content",
        )
        original = ResourcePostFetchPayload(uri="test://data", content=content)

        proto1 = original.model_dump_pb()
        restored1 = ResourcePostFetchPayload.model_validate_pb(proto1)
        proto2 = restored1.model_dump_pb()
        restored2 = ResourcePostFetchPayload.model_validate_pb(proto2)

        assert original.uri == restored2.uri
        assert restored2.content["text"] == "Test content"


class TestResourcePayloadEdgeCases:
    """Test edge cases for resource payload conversions."""

    def test_empty_uri(self):
        """Test with empty URI."""
        payload = ResourcePreFetchPayload(uri="")

        proto_payload = payload.model_dump_pb()
        restored = ResourcePreFetchPayload.model_validate_pb(proto_payload)

        assert restored.uri == ""

    def test_very_long_uri(self):
        """Test with very long URI."""
        long_uri = "http://example.com/" + "a" * 1000
        payload = ResourcePreFetchPayload(uri=long_uri)

        proto_payload = payload.model_dump_pb()
        restored = ResourcePreFetchPayload.model_validate_pb(proto_payload)

        assert restored.uri == long_uri

    def test_uri_with_special_characters(self):
        """Test URI with special characters."""
        uri = "file:///path/with spaces/and-special_chars#fragment?query=value"
        payload = ResourcePreFetchPayload(uri=uri)

        proto_payload = payload.model_dump_pb()
        restored = ResourcePreFetchPayload.model_validate_pb(proto_payload)

        assert restored.uri == uri

    def test_large_metadata_dict(self):
        """Test with large metadata dictionary."""
        large_metadata = {f"meta_{i}": f"value_{i}" for i in range(100)}
        payload = ResourcePreFetchPayload(uri="test://bulk", metadata=large_metadata)

        proto_payload = payload.model_dump_pb()
        restored = ResourcePreFetchPayload.model_validate_pb(proto_payload)

        assert len(restored.metadata) == 100
        assert restored.metadata["meta_50"] == "value_50"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
