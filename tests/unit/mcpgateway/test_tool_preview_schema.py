# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_tool_preview_schema.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for ToolPreviewRequest schema with server_id field (#6743).

Tests schema validation, field coercion, and edge cases for the optional
server_id parameter added to support server-scoped tool preview.
"""

import pytest
from pydantic import ValidationError

from mcpgateway.schemas import ToolPreviewRequest


class TestToolPreviewRequestSchema:
    """Test suite for ToolPreviewRequest schema validation."""

    def test_default_initialization(self):
        """Test default initialization with no arguments."""
        req = ToolPreviewRequest()
        assert req.arguments == {}
        assert req.server_id is None

    def test_arguments_only(self):
        """Test initialization with arguments but no server_id."""
        req = ToolPreviewRequest(arguments={"key": "value"})
        assert req.arguments == {"key": "value"}
        assert req.server_id is None

    def test_server_id_only(self):
        """Test initialization with server_id but no arguments."""
        server_id = "550e8400-e29b-41d4-a716-446655440000"
        req = ToolPreviewRequest(server_id=server_id)
        assert req.arguments == {}
        assert req.server_id == server_id

    def test_both_fields(self):
        """Test initialization with both arguments and server_id."""
        server_id = "550e8400-e29b-41d4-a716-446655440000"
        args = {"param1": "value1", "param2": 42}
        req = ToolPreviewRequest(arguments=args, server_id=server_id)
        assert req.arguments == args
        assert req.server_id == server_id

    def test_arguments_null_coercion(self):
        """Test that explicit null for arguments is coerced to empty dict."""
        req = ToolPreviewRequest(arguments=None)
        assert req.arguments == {}
        assert req.server_id is None

    def test_server_id_null_preserved(self):
        """Test that explicit null for server_id is preserved as None."""
        req = ToolPreviewRequest(server_id=None)
        assert req.arguments == {}
        assert req.server_id is None

    def test_server_id_whitespace_stripped(self):
        """Test that server_id with leading/trailing whitespace is stripped."""
        server_id = "  550e8400-e29b-41d4-a716-446655440000  "
        req = ToolPreviewRequest(server_id=server_id)
        assert req.server_id == "550e8400-e29b-41d4-a716-446655440000"

    def test_server_id_empty_string_rejected(self):
        """Test that empty string for server_id raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ToolPreviewRequest(server_id="")

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("server_id",)
        assert errors[0]["type"] == "string_too_short"

    def test_server_id_whitespace_only_rejected(self):
        """Test that whitespace-only server_id raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ToolPreviewRequest(server_id="   ")

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("server_id",)
        assert errors[0]["type"] == "string_too_short"

    def test_server_id_tab_only_rejected(self):
        """Test that tab-only server_id raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ToolPreviewRequest(server_id="\t\t")

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("server_id",)
        assert errors[0]["type"] == "string_too_short"

    @pytest.mark.parametrize("length", [1, 32, 36])
    def test_server_id_length_boundary_accepted(self, length):
        """Server IDs fit the database limit after surrounding whitespace is stripped."""
        server_id = "a" * length
        assert ToolPreviewRequest(server_id=f"  {server_id}\t").server_id == server_id

    @pytest.mark.parametrize("length", [37, 100_000])
    def test_server_id_over_database_limit_rejected(self, length):
        """Overlong IDs are rejected before reaching server lookup."""
        with pytest.raises(ValidationError) as exc_info:
            ToolPreviewRequest(server_id="a" * length)

        assert exc_info.value.errors()[0]["loc"] == ("server_id",)
        assert exc_info.value.errors()[0]["type"] == "string_too_long"

    def test_server_id_various_formats(self):
        """Test that various server_id formats are accepted."""
        # UUID format
        req1 = ToolPreviewRequest(server_id="550e8400-e29b-41d4-a716-446655440000")
        assert req1.server_id == "550e8400-e29b-41d4-a716-446655440000"

        # Short alphanumeric
        req2 = ToolPreviewRequest(server_id="server123")
        assert req2.server_id == "server123"

        # With underscores
        req3 = ToolPreviewRequest(server_id="my_server_01")
        assert req3.server_id == "my_server_01"

        # With hyphens
        req4 = ToolPreviewRequest(server_id="my-server-01")
        assert req4.server_id == "my-server-01"

    def test_complex_arguments_with_server_id(self):
        """Test complex nested arguments with server_id."""
        server_id = "550e8400-e29b-41d4-a716-446655440000"
        args = {
            "nested": {
                "key1": "value1",
                "key2": [1, 2, 3],
            },
            "list": ["a", "b", "c"],
            "number": 42,
            "boolean": True,
        }
        req = ToolPreviewRequest(arguments=args, server_id=server_id)
        assert req.arguments == args
        assert req.server_id == server_id

    def test_model_dump(self):
        """Test that model_dump includes server_id field."""
        server_id = "550e8400-e29b-41d4-a716-446655440000"
        args = {"key": "value"}
        req = ToolPreviewRequest(arguments=args, server_id=server_id)

        dumped = req.model_dump()
        assert dumped["arguments"] == args
        assert dumped["server_id"] == server_id

    def test_model_dump_exclude_none(self):
        """Test that model_dump with exclude_none omits null server_id."""
        req = ToolPreviewRequest(arguments={"key": "value"})

        dumped = req.model_dump(exclude_none=True)
        assert dumped["arguments"] == {"key": "value"}
        assert "server_id" not in dumped

    def test_json_serialization(self):
        """Test JSON serialization with server_id."""
        server_id = "550e8400-e29b-41d4-a716-446655440000"
        args = {"key": "value"}
        req = ToolPreviewRequest(arguments=args, server_id=server_id)

        json_str = req.model_dump_json()
        assert server_id in json_str
        assert "key" in json_str
        assert "value" in json_str

    def test_backwards_compatibility(self):
        """Test that existing code without server_id still works."""
        # Old-style usage: only arguments
        req1 = ToolPreviewRequest(arguments={"key": "value"})
        assert req1.arguments == {"key": "value"}
        assert req1.server_id is None

        # Old-style usage: no arguments
        req2 = ToolPreviewRequest()
        assert req2.arguments == {}
        assert req2.server_id is None
