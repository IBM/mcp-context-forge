# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_server_create_tool_assignment_bug.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test for bug fix: Tool assignment when creating virtual servers via API.

This test verifies that the fix for the bug where tools were not being assigned
when creating a virtual server via API (POST /servers) works correctly.

The bug was that when sending tool IDs as a JSON array (API), the validator
would accept tool names instead of UUIDs, causing the association to fail silently.
"""

import pytest
from pydantic import ValidationError

from mcpgateway.schemas import ServerCreate, ServerUpdate


class TestServerToolAssignmentBugFix:
    """Test cases for the server tool assignment bug fix."""

    def test_server_create_with_valid_uuid_list(self):
        """Test that ServerCreate accepts a list of valid UUIDs."""
        valid_uuid = "550e8400e29b41d4a716446655440000"  # pragma: allowlist secret
        server = ServerCreate(
            name="Test Server",
            associated_tools=[valid_uuid],
        )
        assert server.associated_tools == [valid_uuid]

    def test_server_create_with_valid_hyphenated_uuid_list(self):
        """Test that ServerCreate normalizes hyphenated UUIDs to hex form."""
        hyphenated_uuid = "550e8400-e29b-41d4-a716-446655440000"
        normalized_uuid = "550e8400e29b41d4a716446655440000"  # pragma: allowlist secret
        server = ServerCreate(
            name="Test Server",
            associated_tools=[hyphenated_uuid],
        )
        assert server.associated_tools == [normalized_uuid]

    def test_server_create_with_valid_uuid_string(self):
        """Test that ServerCreate accepts comma-separated UUID string (UI format)."""
        valid_uuid = "550e8400e29b41d4a716446655440000"  # pragma: allowlist secret
        server = ServerCreate(
            name="Test Server",
            associated_tools=valid_uuid,
        )
        assert server.associated_tools == [valid_uuid]

    def test_server_create_with_multiple_valid_uuids(self):
        """Test that ServerCreate accepts multiple valid UUIDs."""
        uuid1 = "550e8400e29b41d4a716446655440000"  # pragma: allowlist secret
        uuid2 = "6ba7b8109dad11d180b400c04fd430c8"  # pragma: allowlist secret
        server = ServerCreate(
            name="Test Server",
            associated_tools=[uuid1, uuid2],
        )
        assert server.associated_tools == [uuid1, uuid2]

    def test_server_create_rejects_tool_names(self):
        """Test that ServerCreate rejects tool names (non-UUID strings)."""
        with pytest.raises(ValidationError) as exc_info:
            ServerCreate(
                name="Test Server",
                associated_tools=["my-tool-name"],  # This should fail
            )

        error_msg = str(exc_info.value)
        assert "Invalid ID format" in error_msg
        assert "my-tool-name" in error_msg
        assert "UUID" in error_msg

    def test_server_create_rejects_tool_names_as_string(self):
        """Test that ServerCreate rejects comma-separated tool names passed as string."""
        with pytest.raises(ValidationError) as exc_info:
            ServerCreate(
                name="Test Server",
                associated_tools="my-tool-name,another-tool",  # This should fail
            )

        error_msg = str(exc_info.value)
        assert "Invalid ID format" in error_msg
        assert "my-tool-name" in error_msg

    def test_server_create_with_32_char_hex_uuid(self):
        """Test that ServerCreate accepts 32-character hex UUIDs (no hyphens)."""
        uuid_no_hyphens = "550e8400e29b41d4a716446655440000"  # pragma: allowlist secret
        server = ServerCreate(
            name="Test Server",
            associated_tools=[uuid_no_hyphens],
        )
        assert server.associated_tools == [uuid_no_hyphens]

    def test_server_update_with_valid_uuid_list(self):
        """Test that ServerUpdate accepts a list of valid UUIDs."""
        valid_uuid = "550e8400e29b41d4a716446655440000"  # pragma: allowlist secret
        server = ServerUpdate(
            associated_tools=[valid_uuid],
        )
        assert server.associated_tools == [valid_uuid]

    def test_server_update_rejects_tool_names(self):
        """Test that ServerUpdate rejects tool names (non-UUID strings)."""
        with pytest.raises(ValidationError) as exc_info:
            ServerUpdate(
                associated_tools=["my-tool-name"],  # This should fail
            )

        error_msg = str(exc_info.value)
        assert "Invalid ID format" in error_msg
        assert "my-tool-name" in error_msg

    def test_server_create_with_empty_list(self):
        """Test that ServerCreate handles empty lists correctly."""
        server = ServerCreate(
            name="Test Server",
            associated_tools=[],
        )
        assert server.associated_tools == []

    def test_server_create_with_none(self):
        """Test that ServerCreate handles None correctly."""
        server = ServerCreate(
            name="Test Server",
            associated_tools=None,
        )
        assert server.associated_tools is None

    def test_server_create_filters_empty_strings(self):
        """Test that ServerCreate filters out empty strings from lists."""
        valid_uuid = "550e8400e29b41d4a716446655440000"  # pragma: allowlist secret
        server = ServerCreate(
            name="Test Server",
            associated_tools=[valid_uuid, "", "  "],
        )
        assert server.associated_tools == [valid_uuid]

    def test_error_message_content(self):
        """Test that error messages guide users correctly."""
        with pytest.raises(ValidationError) as exc_info:
            ServerCreate(
                name="Test Server",
                associated_tools=["tool-name"],
            )

        error_msg = str(exc_info.value)
        # Should mention the invalid value
        assert "tool-name" in error_msg
        # Should mention UUID requirement
        assert "UUID" in error_msg

    def test_all_association_fields_validated(self):
        """Test that all association fields (tools, resources, prompts, agents) are validated."""
        # Test resources
        with pytest.raises(ValidationError) as exc_info:
            ServerCreate(
                name="Test Server",
                associated_resources=["resource-name"],
            )
        assert "Invalid ID format" in str(exc_info.value)

        # Test prompts
        with pytest.raises(ValidationError) as exc_info:
            ServerCreate(
                name="Test Server",
                associated_prompts=["prompt-name"],
            )
        assert "Invalid ID format" in str(exc_info.value)

        # Test A2A agents
        with pytest.raises(ValidationError) as exc_info:
            ServerCreate(
                name="Test Server",
                associated_a2a_agents=["agent-name"],
            )
        assert "Invalid ID format" in str(exc_info.value)
