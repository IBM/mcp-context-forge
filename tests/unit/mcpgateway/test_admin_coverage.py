# -*- coding: utf-8 -*-
"""Additional tests for admin module to improve coverage.

These tests focus on untested functions and edge cases in the admin module.
"""

# Standard
from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

# First-Party
from mcpgateway.admin import (
    get_user_email,
    serialize_datetime,
    set_logging_service,
)


class TestUtilityFunctions:
    """Test utility functions in admin module."""

    def test_serialize_datetime_with_datetime(self):
        """Test serialize_datetime with datetime object."""
        from mcpgateway.admin import serialize_datetime

        dt = datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
        result = serialize_datetime(dt)
        assert result == "2024-01-15T10:30:45+00:00"

    def test_serialize_datetime_with_none(self):
        """Test serialize_datetime with None."""
        from mcpgateway.admin import serialize_datetime

        result = serialize_datetime(None)
        assert result is None

    def test_serialize_datetime_with_string(self):
        """Test serialize_datetime with string."""
        from mcpgateway.admin import serialize_datetime

        result = serialize_datetime("2024-01-15")
        assert result == "2024-01-15"

    def test_serialize_datetime_with_number(self):
        """Test serialize_datetime with number."""
        from mcpgateway.admin import serialize_datetime

        result = serialize_datetime(12345)
        assert result == 12345

    def test_get_user_email_with_string(self):
        """Test get_user_email with string input."""
        from mcpgateway.admin import get_user_email

        email = get_user_email("user@example.com")
        assert email == "user@example.com"

    def test_get_user_email_with_dict(self):
        """Test get_user_email with dict input."""
        from mcpgateway.admin import get_user_email

        user_dict = {"email": "user@example.com", "name": "Test User"}
        email = get_user_email(user_dict)
        assert email == "user@example.com"

    def test_get_user_email_with_object(self):
        """Test get_user_email with object input."""
        from mcpgateway.admin import get_user_email

        class MockUser:
            email = "user@example.com"

        user = MockUser()
        email = get_user_email(user)
        assert email == "user@example.com"

    def test_get_user_email_with_none(self):
        """Test get_user_email with None."""
        from mcpgateway.admin import get_user_email

        email = get_user_email(None)
        assert email == "unknown"

    def test_get_user_email_with_object_no_email(self):
        """Test get_user_email with object without email."""
        from mcpgateway.admin import get_user_email

        class NoEmailUser:
            name = "Test User"

        user = NoEmailUser()
        email = get_user_email(user)
        assert "NoEmailUser" in email

    def test_set_logging_service(self):
        """Test set_logging_service function."""
        from mcpgateway.admin import set_logging_service
        from mcpgateway.services.logging_service import LoggingService

        mock_service = MagicMock(spec=LoggingService)
        mock_service.get_logger = MagicMock(return_value=MagicMock())

        set_logging_service(mock_service)
        mock_service.get_logger.assert_called_once_with("mcpgateway.admin")


class TestRateLimiting:
    """Test rate limiting functionality."""

    def test_rate_limit_decorator(self):
        """Test rate_limit decorator."""
        from mcpgateway.admin import rate_limit

        # Test with specific limit
        decorator = rate_limit(10)
        assert callable(decorator)

        # Test with None (uses default)
        decorator = rate_limit(None)
        assert callable(decorator)

        # Test decorating a function
        @decorator
        async def test_func():
            return "success"

        assert callable(test_func)


class TestAdminUIFunctions:
    """Test admin UI rendering functions."""

    async def test_admin_ui_renders(self):
        """Test admin_ui function."""
        from mcpgateway.admin import admin_ui

        mock_request = MagicMock(spec=Request)
        mock_request.app = MagicMock()
        mock_request.app.state = MagicMock()
        mock_request.app.state.templates = MagicMock()

        mock_response = MagicMock()
        mock_request.app.state.templates.TemplateResponse = MagicMock(return_value=mock_response)

        mock_db = MagicMock()
        mock_user = "test-user"

        with patch("mcpgateway.admin.server_service") as mock_server_service:
            with patch("mcpgateway.admin.tool_service") as mock_tool_service:
                with patch("mcpgateway.admin.resource_service") as mock_resource_service:
                    with patch("mcpgateway.admin.prompt_service") as mock_prompt_service:
                        with patch("mcpgateway.admin.gateway_service") as mock_gateway_service:
                            # Mock all service methods
                            mock_server_service.list_servers = AsyncMock(return_value=[])
                            mock_tool_service.list_tools = AsyncMock(return_value=[])
                            mock_resource_service.list_resources = AsyncMock(return_value=[])
                            mock_prompt_service.list_prompts = AsyncMock(return_value=[])
                            mock_gateway_service.list_gateways = AsyncMock(return_value=[])

                            result = await admin_ui(mock_request, mock_db, mock_user)

                            # Verify template was called
                            mock_request.app.state.templates.TemplateResponse.assert_called_once()
                            call_args = mock_request.app.state.templates.TemplateResponse.call_args
                            assert call_args[0][0] == "admin.html"
                            assert "servers" in call_args[0][1]
                            assert "tools" in call_args[0][1]


class TestAdminListFunctions:
    """Test admin list functions."""

    async def test_admin_list_servers(self):
        """Test admin_list_servers function."""
        from mcpgateway.admin import admin_list_servers
        from mcpgateway.schemas import ServerRead

        mock_db = MagicMock()
        mock_user = "test-user"

        mock_servers = [
            ServerRead(
                id="srv1",
                name="Server 1",
                url="http://example.com",
                headers={},
                root_path="",
                api_key="",
                auth_type="none",
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        ]

        with patch("mcpgateway.admin.server_service") as mock_service:
            mock_service.list_servers_for_user = AsyncMock(return_value=mock_servers)

            result = await admin_list_servers(
                search=None,
                sort_by="name",
                sort_order="asc",
                page=1,
                page_size=10,
                db=mock_db,
                user=mock_user,
            )

            assert "servers" in result
            assert "total" in result
            assert "page" in result
            assert result["servers"] == mock_servers

    async def test_admin_list_tools(self):
        """Test admin_list_tools function."""
        from mcpgateway.admin import admin_list_tools
        from mcpgateway.schemas import ToolRead

        mock_db = MagicMock()
        mock_user = "test-user"

        mock_tools = [
            ToolRead(
                id="tool1",
                name="Tool 1",
                description="Test tool",
                input_schema={},
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        ]

        with patch("mcpgateway.admin.tool_service") as mock_service:
            mock_service.list_tools = AsyncMock(return_value=mock_tools)

            result = await admin_list_tools(
                search=None,
                sort_by="name",
                sort_order="asc",
                page=1,
                page_size=10,
                db=mock_db,
                user=mock_user,
            )

            assert result == mock_tools

    async def test_admin_list_resources(self):
        """Test admin_list_resources function."""
        from mcpgateway.admin import admin_list_resources
        from mcpgateway.schemas import ResourceRead

        mock_db = MagicMock()
        mock_user = "test-user"

        mock_resources = [
            ResourceRead(
                id="res1",
                name="Resource 1",
                uri="file:///test.txt",
                mime_type="text/plain",
                description="Test resource",
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        ]

        with patch("mcpgateway.admin.resource_service") as mock_service:
            mock_service.list_resources = AsyncMock(return_value=mock_resources)

            result = await admin_list_resources(
                search=None,
                sort_by="name",
                sort_order="asc",
                page=1,
                page_size=10,
                db=mock_db,
                user=mock_user,
            )

            assert result == mock_resources

    async def test_admin_list_prompts(self):
        """Test admin_list_prompts function."""
        from mcpgateway.admin import admin_list_prompts
        from mcpgateway.schemas import PromptRead

        mock_db = MagicMock()
        mock_user = "test-user"

        mock_prompts = [
            PromptRead(
                id="prompt1",
                name="Prompt 1",
                description="Test prompt",
                content="Test content",
                arguments=[],
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        ]

        with patch("mcpgateway.admin.prompt_service") as mock_service:
            mock_service.list_prompts = AsyncMock(return_value=mock_prompts)

            result = await admin_list_prompts(
                search=None,
                sort_by="name",
                sort_order="asc",
                page=1,
                page_size=10,
                db=mock_db,
                user=mock_user,
            )

            assert result == mock_prompts

    async def test_admin_list_gateways(self):
        """Test admin_list_gateways function."""
        from mcpgateway.admin import admin_list_gateways
        from mcpgateway.schemas import GatewayRead

        mock_db = MagicMock()
        mock_user = "test-user"

        mock_gateways = [
            GatewayRead(
                id="gw1",
                name="Gateway 1",
                url="http://gateway.example.com",
                headers={},
                auth_type="none",
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        ]

        with patch("mcpgateway.admin.gateway_service") as mock_service:
            mock_service.list_gateways = AsyncMock(return_value=mock_gateways)

            result = await admin_list_gateways(
                search=None,
                sort_by="name",
                sort_order="asc",
                page=1,
                page_size=10,
                db=mock_db,
                user=mock_user,
            )

            assert result == mock_gateways


class TestAdminGetFunctions:
    """Test admin get functions."""

    async def test_admin_get_server(self):
        """Test admin_get_server function."""
        from mcpgateway.admin import admin_get_server
        from mcpgateway.schemas import ServerRead

        mock_db = MagicMock()
        mock_user = "test-user"

        mock_server = ServerRead(
            id="srv1",
            name="Server 1",
            url="http://example.com",
            headers={},
            root_path="",
            api_key="",
            auth_type="none",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.admin.server_service") as mock_service:
            mock_service.get_server = AsyncMock(return_value=mock_server)

            result = await admin_get_server("srv1", mock_db, mock_user)

            assert isinstance(result, dict)
            assert result["server"] == mock_server

    async def test_admin_get_tool(self):
        """Test admin_get_tool function."""
        from mcpgateway.admin import admin_get_tool
        from mcpgateway.schemas import ToolRead

        mock_db = MagicMock()
        mock_user = "test-user"

        mock_tool = ToolRead(
            id="tool1",
            name="Tool 1",
            description="Test tool",
            input_schema={},
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.admin.tool_service") as mock_service:
            mock_service.get_tool = AsyncMock(return_value=mock_tool)

            result = await admin_get_tool("tool1", mock_db, mock_user)

            assert result == mock_tool

    async def test_admin_get_resource(self):
        """Test admin_get_resource function."""
        from mcpgateway.admin import admin_get_resource
        from mcpgateway.schemas import ResourceRead

        mock_db = MagicMock()
        mock_user = "test-user"

        mock_resource = ResourceRead(
            id="res1",
            name="Resource 1",
            uri="file:///test.txt",
            mime_type="text/plain",
            description="Test resource",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.admin.resource_service") as mock_service:
            mock_service.get_resource = AsyncMock(return_value=mock_resource)

            result = await admin_get_resource("res1", mock_db, mock_user)

            assert result == mock_resource

    async def test_admin_get_prompt(self):
        """Test admin_get_prompt function."""
        from mcpgateway.admin import admin_get_prompt
        from mcpgateway.schemas import PromptRead

        mock_db = MagicMock()
        mock_user = "test-user"

        mock_prompt = PromptRead(
            id="prompt1",
            name="Prompt 1",
            description="Test prompt",
            content="Test content",
            arguments=[],
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.admin.prompt_service") as mock_service:
            mock_service.get_prompt_details = AsyncMock(return_value=mock_prompt)

            result = await admin_get_prompt("prompt1", mock_db, mock_user)

            assert result == mock_prompt

    async def test_admin_get_gateway(self):
        """Test admin_get_gateway function."""
        from mcpgateway.admin import admin_get_gateway
        from mcpgateway.schemas import GatewayRead

        mock_db = MagicMock()
        mock_user = "test-user"

        mock_gateway = GatewayRead(
            id="gw1",
            name="Gateway 1",
            url="http://gateway.example.com",
            headers={},
            auth_type="none",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.admin.gateway_service") as mock_service:
            mock_service.get_gateway = AsyncMock(return_value=mock_gateway)

            result = await admin_get_gateway("gw1", mock_db, mock_user)

            assert result == mock_gateway
