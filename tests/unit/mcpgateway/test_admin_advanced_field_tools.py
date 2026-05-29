# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_advanced_fields.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Test coverage for advanced tool configuration fields in admin edit form.
Tests the optional fields: timeout_ms, title, REST passthrough fields,
plugin chains, and team_id reassignment.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcpgateway.admin import admin_edit_tool
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.services.tool_service import ToolService
from mcpgateway.utils.orjson_response import ORJSONResponse


class FakeForm:
    """Fake form data for testing."""

    def __init__(self, data: dict):
        self._data = data

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def __contains__(self, key: str):
        return key in self._data


@pytest.fixture
def mock_request():
    """Mock FastAPI Request object."""
    request = MagicMock()
    request.headers = {}
    return request


@pytest.fixture
def mock_db():
    """Mock database session."""
    return MagicMock()


@pytest.mark.asyncio
class TestAdminEditToolAdvancedFields:
    """Test advanced configuration fields in admin_edit_tool endpoint."""

    @patch.object(ToolService, "update_tool")
    async def test_edit_tool_with_timeout_ms(self, mock_update_tool, mock_request, mock_db):
        """Test editing tool with timeout_ms field."""
        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "timeout_ms": "5000",
                "requestType": "GET",
                "integrationType": "REST",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert isinstance(result, (ORJSONResponse, type(result)))
        assert result.status_code == 200

        # Verify timeout_ms was included in the update call
        call_args = mock_update_tool.call_args[0]
        tool_update = call_args[2]
        assert tool_update.timeout_ms == 5000

    @patch.object(ToolService, "update_tool")
    async def test_edit_tool_with_title(self, mock_update_tool, mock_request, mock_db):
        """Test editing tool with title field (MCP BaseMetadata)."""
        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "title": "My Tool Title",
                "requestType": "GET",
                "integrationType": "REST",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert result.status_code == 200

        # Verify title was included in the update call
        call_args = mock_update_tool.call_args[0]
        tool_update = call_args[2]
        assert tool_update.title == "My Tool Title"

    @patch.object(ToolService, "update_tool")
    async def test_edit_tool_with_rest_passthrough_fields(self, mock_update_tool, mock_request, mock_db):
        """Test editing tool with all REST passthrough fields."""
        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "base_url": "https://api.example.com",
                "path_template": "/v1/{resource}",
                "query_mapping": '{"param1": "field1"}',
                "header_mapping": '{"X-Custom": "field2"}',
                "expose_passthrough": "true",
                "allowlist": "GET, POST, PUT",
                "requestType": "GET",
                "integrationType": "REST",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert result.status_code == 200

        # Verify all passthrough fields were included
        call_args = mock_update_tool.call_args[0]
        tool_update = call_args[2]
        assert tool_update.base_url == "https://api.example.com"
        assert tool_update.path_template == "/v1/{resource}"
        assert tool_update.query_mapping == {"param1": "field1"}
        assert tool_update.header_mapping == {"X-Custom": "field2"}
        assert tool_update.expose_passthrough is True
        assert tool_update.allowlist == ["GET", "POST", "PUT"]

    @patch.object(ToolService, "update_tool")
    async def test_edit_tool_with_invalid_query_mapping_json(self, mock_update_tool, mock_request, mock_db):
        """Test editing tool with invalid JSON in query_mapping."""
        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "query_mapping": "{invalid json}",
                "requestType": "GET",
                "integrationType": "REST",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert result.status_code == 422
        payload = json.loads(result.body.decode())
        assert payload["success"] is False
        assert "Invalid JSON in query_mapping field" in payload["message"]

    @patch.object(ToolService, "update_tool")
    async def test_edit_tool_with_invalid_header_mapping_json(self, mock_update_tool, mock_request, mock_db):
        """Test editing tool with invalid JSON in header_mapping."""
        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "header_mapping": "{invalid json}",
                "requestType": "GET",
                "integrationType": "REST",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert result.status_code == 422
        payload = json.loads(result.body.decode())
        assert payload["success"] is False
        assert "Invalid JSON in header_mapping field" in payload["message"]

    @patch.object(ToolService, "update_tool")
    async def test_edit_tool_with_plugin_chains(self, mock_update_tool, mock_request, mock_db):
        """Test editing tool with plugin_chain_pre and plugin_chain_post."""
        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "plugin_chain_pre": "rate_limit, pii_filter",
                "plugin_chain_post": "response_shape, deny_filter",
                "requestType": "GET",
                "integrationType": "REST",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert result.status_code == 200

        # Verify plugin chains were included
        call_args = mock_update_tool.call_args[0]
        tool_update = call_args[2]
        assert tool_update.plugin_chain_pre == ["rate_limit", "pii_filter"]
        assert tool_update.plugin_chain_post == ["response_shape", "deny_filter"]

    @patch.object(ToolService, "update_tool")
    async def test_edit_tool_with_allowlist_parsing(self, mock_update_tool, mock_request, mock_db):
        """Test that allowlist field is correctly parsed from comma-separated string."""
        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "allowlist": "  GET ,  POST  , DELETE  ",  # With extra spaces
                "requestType": "GET",
                "integrationType": "REST",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert result.status_code == 200

        # Verify allowlist was parsed and trimmed correctly
        call_args = mock_update_tool.call_args[0]
        tool_update = call_args[2]
        assert tool_update.allowlist == ["GET", "POST", "DELETE"]

    @patch.object(ToolService, "update_tool")
    async def test_edit_tool_expose_passthrough_false(self, mock_update_tool, mock_request, mock_db):
        """Test that expose_passthrough false is handled correctly."""
        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "expose_passthrough": "false",
                "requestType": "GET",
                "integrationType": "REST",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert result.status_code == 200

        # Verify expose_passthrough is False
        call_args = mock_update_tool.call_args[0]
        tool_update = call_args[2]
        assert tool_update.expose_passthrough is False

    @patch.object(ToolService, "update_tool")
    async def test_edit_tool_without_optional_fields(self, mock_update_tool, mock_request, mock_db):
        """Test that optional fields are not included when not present in form."""
        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "requestType": "GET",
                "integrationType": "REST",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert result.status_code == 200

        # Verify optional fields are NOT included (should be None or extracted defaults)
        # Note: base_url and path_template are auto-extracted from url for REST tools
        call_args = mock_update_tool.call_args[0]
        tool_update = call_args[2]
        assert tool_update.timeout_ms is None
        assert tool_update.title is None
        assert tool_update.query_mapping is None
        assert tool_update.header_mapping is None
        assert tool_update.plugin_chain_pre is None
        assert tool_update.plugin_chain_post is None

    @patch.object(ToolService, "update_tool")
    async def test_edit_tool_with_all_advanced_fields(self, mock_update_tool, mock_request, mock_db):
        """Test editing tool with all advanced fields together."""
        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "timeout_ms": "30000",
                "title": "Advanced Tool",
                "jsonpath_filter": "$.data[*]",
                "base_url": "https://api.example.com",
                "path_template": "/v2/{id}",
                "query_mapping": '{"q": "searchField"}',
                "header_mapping": '{"Authorization": "tokenField"}',
                "expose_passthrough": "true",
                "allowlist": "GET,POST",
                "plugin_chain_pre": "rate_limit,regex_filter",
                "plugin_chain_post": "resource_filter,pii_filter",
                "requestType": "GET",
                "integrationType": "REST",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert result.status_code == 200

        # Verify all fields were included
        call_args = mock_update_tool.call_args[0]
        tool_update = call_args[2]
        assert tool_update.timeout_ms == 30000
        assert tool_update.title == "Advanced Tool"
        assert tool_update.jsonpath_filter == "$.data[*]"
        assert tool_update.base_url == "https://api.example.com"
        assert tool_update.path_template == "/v2/{id}"
        assert tool_update.query_mapping == {"q": "searchField"}
        assert tool_update.header_mapping == {"Authorization": "tokenField"}
        assert tool_update.expose_passthrough is True
        assert tool_update.allowlist == ["GET", "POST"]
        assert tool_update.plugin_chain_pre == ["rate_limit", "regex_filter"]
        assert tool_update.plugin_chain_post == ["resource_filter", "pii_filter"]

    @patch.object(TeamManagementService, "verify_team_for_user")
    @patch.object(ToolService, "update_tool")
    async def test_edit_tool_with_team_reassignment(self, mock_update_tool, mock_verify_team, mock_request, mock_db):
        """Test editing tool with team_id reassignment."""
        # Mock verify_team_for_user to return the team_id (user is member of team)
        mock_verify_team.return_value = "team-456"

        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "team_id": "team-456",
                "requestType": "GET",
                "integrationType": "REST",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert result.status_code == 200

        # Verify team_id was included and verify_team_for_user was called
        mock_verify_team.assert_called_once_with("test@example.com", "team-456")
        call_args = mock_update_tool.call_args[0]
        tool_update = call_args[2]
        assert tool_update.team_id == "team-456"

    @patch.object(TeamManagementService, "verify_team_for_user")
    @patch.object(ToolService, "update_tool")
    async def test_edit_tool_with_invalid_team_reassignment(self, mock_update_tool, mock_verify_team, mock_request, mock_db):
        """Test editing tool with team_id when user is not member of that team."""
        # Mock verify_team_for_user to return empty list (user is not member)
        mock_verify_team.return_value = []

        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "team_id": "team-999",
                "requestType": "GET",
                "integrationType": "REST",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        # Should return 422 validation error because team_id becomes []
        assert result.status_code == 422
        payload = json.loads(result.body.decode())
        assert payload["success"] is False
        assert "team_id" in payload["message"].lower()

    @patch.object(TeamManagementService, "verify_team_for_user")
    @patch.object(ToolService, "update_tool")
    async def test_edit_tool_without_team_reassignment(self, mock_update_tool, mock_verify_team, mock_request, mock_db):
        """Test editing tool without providing team_id (no reassignment)."""
        # Mock verify_team_for_user to return None (no team_id provided, user has no personal team)
        mock_verify_team.return_value = None

        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "requestType": "GET",
                "integrationType": "REST",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert result.status_code == 200

        # Verify verify_team_for_user was called with None team_id
        mock_verify_team.assert_called_once_with("test@example.com", None)
        call_args = mock_update_tool.call_args[0]
        tool_update = call_args[2]
        assert tool_update.team_id is None

    @patch.object(TeamManagementService, "verify_team_for_user")
    @patch.object(ToolService, "update_tool")
    async def test_expose_passthrough_checkbox_checked(self, mock_update_tool, mock_verify_team, mock_request, mock_db):
        """Bug fix: Verify expose_passthrough=True when checkbox is checked (value='true')."""
        mock_verify_team.return_value = None  # No team_id in form

        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "requestType": "GET",
                "integrationType": "REST",
                "expose_passthrough": "true",  # Checked state
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert result.status_code == 200
        call_args = mock_update_tool.call_args[0]
        tool_update = call_args[2]
        assert tool_update.expose_passthrough is True

    @patch.object(TeamManagementService, "verify_team_for_user")
    @patch.object(ToolService, "update_tool")
    async def test_expose_passthrough_checkbox_unchecked(self, mock_update_tool, mock_verify_team, mock_request, mock_db):
        """Bug fix: Verify expose_passthrough=False when checkbox is unchecked (field absent)."""
        mock_verify_team.return_value = None  # No team_id in form

        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "requestType": "GET",
                "integrationType": "REST",
                # expose_passthrough NOT in form = unchecked
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert result.status_code == 200
        call_args = mock_update_tool.call_args[0]
        tool_update = call_args[2]
        assert tool_update.expose_passthrough is False

    @patch.object(TeamManagementService, "verify_team_for_user")
    @patch.object(ToolService, "update_tool")
    async def test_clear_allowlist_to_empty(self, mock_update_tool, mock_verify_team, mock_request, mock_db):
        """Bug fix: Verify allowlist can be cleared to empty list with empty string."""
        mock_verify_team.return_value = None  # No team_id in form

        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "requestType": "GET",
                "integrationType": "REST",
                "allowlist": "",  # Empty string to clear
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert result.status_code == 200
        call_args = mock_update_tool.call_args[0]
        tool_update = call_args[2]
        assert tool_update.allowlist == []

    @patch.object(TeamManagementService, "verify_team_for_user")
    @patch.object(ToolService, "update_tool")
    async def test_clear_plugin_chains_to_empty(self, mock_update_tool, mock_verify_team, mock_request, mock_db):
        """Bug fix: Verify plugin_chain_pre and plugin_chain_post can be cleared to empty lists."""
        mock_verify_team.return_value = None  # No team_id in form

        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "requestType": "GET",
                "integrationType": "REST",
                "plugin_chain_pre": "",  # Clear
                "plugin_chain_post": "",  # Clear
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert result.status_code == 200
        call_args = mock_update_tool.call_args[0]
        tool_update = call_args[2]
        assert tool_update.plugin_chain_pre == []
        assert tool_update.plugin_chain_post == []

    @patch.object(TeamManagementService, "verify_team_for_user")
    @patch.object(ToolService, "update_tool")
    async def test_timeout_ms_invalid_input(self, mock_update_tool, mock_verify_team, mock_request, mock_db):
        """Bug fix: Verify timeout_ms rejects non-numeric input with clear error."""
        mock_verify_team.return_value = None  # No team_id in form

        form_data = FakeForm(
            {
                "name": "test_tool",
                "customName": "test_tool",
                "url": "http://example.com",
                "description": "Test tool",
                "requestType": "GET",
                "integrationType": "REST",
                "timeout_ms": "10seconds",  # Invalid non-numeric
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool(
            "550e8400e29b41d4a7164466554400b1",  # pragma: allowlist secret
            mock_request,
            mock_db,
            user={"email": "test@example.com", "db": mock_db},
        )

        assert result.status_code == 422
        payload = json.loads(result.body.decode())
        assert payload["success"] is False
        assert "must be a positive integer" in payload["message"]
