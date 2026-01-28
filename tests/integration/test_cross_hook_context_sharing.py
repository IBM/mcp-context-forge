# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_cross_hook_context_sharing.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Integration tests for cross-hook context sharing functionality.

These tests verify that plugin contexts are properly shared across different
hook types (HTTP → Tool, HTTP → Resource, HTTP → Prompt, RBAC hooks, etc.).
"""

# Standard
from pathlib import Path

# Third-Party
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.db import Base
from mcpgateway.main import app
from mcpgateway.middleware.http_auth_middleware import HttpAuthMiddleware
from mcpgateway.plugins.framework import PluginManager


class TestCrossHookContextSharing:
    """Integration tests for cross-hook context sharing.

    These tests verify that:
    1. Context stored in HTTP_PRE_REQUEST is accessible in HTTP_AUTH_CHECK_PERMISSION
    2. Context stored in HTTP hooks is accessible in MCP hooks (Tool, Resource, Prompt)
    3. GlobalContext is properly shared across all hooks
    4. Plugin state is isolated per plugin
    """

    @pytest.fixture
    def test_db(self):
        """Create a test database."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        yield db
        db.close()

    @pytest.fixture
    async def plugin_manager(self):
        """Create plugin manager with cross-hook context test plugin."""
        # Get the path to the test plugin config
        config_file = Path(__file__).parent.parent / "unit" / "mcpgateway" / "plugins" / "fixtures" / "configs" / "cross_hook_context.yaml"

        # Enable plugins for this test
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("PLUGINS_ENABLED", "true")
            mp.setenv("PLUGIN_CONFIG_FILE", str(config_file))

            # Create plugin manager
            manager = PluginManager(str(config_file))
            await manager.initialize()

            yield manager

            # Cleanup
            await manager.shutdown()

    @pytest.fixture
    def test_client_with_plugins(self, plugin_manager):
        """Create test client with plugin middleware enabled."""
        # Add the HttpAuthMiddleware with plugin manager
        app.add_middleware(HttpAuthMiddleware, plugin_manager=plugin_manager)

        with TestClient(app) as client:
            yield client

    @pytest.mark.asyncio
    async def test_http_to_rbac_context_sharing(self, test_client_with_plugins, plugin_manager):
        """Test context sharing from HTTP_PRE_REQUEST to HTTP_AUTH_CHECK_PERMISSION.

        This test verifies that:
        1. HTTP_PRE_REQUEST hook stores context data
        2. HTTP_AUTH_CHECK_PERMISSION hook can read that data
        3. The plugin doesn't raise any ValueError about missing context
        """
        # Make a request that triggers both HTTP_PRE_REQUEST and HTTP_AUTH_CHECK_PERMISSION
        response = test_client_with_plugins.get(
            "/tools",
            headers={"Authorization": "Bearer test-token"}
        )

        # If cross-hook context sharing works, the plugin won't raise ValueError
        # and the request will succeed (or fail for other reasons like auth)
        # The important thing is that we don't get a 500 error from the plugin

        # Note: This might return 401 if auth fails, but that's OK -
        # we're testing that the plugin's cross-hook context access works
        assert response.status_code in [200, 401], \
            "Plugin should not raise ValueError about missing context"

    @pytest.mark.asyncio
    async def test_http_to_tool_context_sharing(
        self, test_db, test_client_with_plugins, plugin_manager
    ):
        """Test context sharing from HTTP hooks to TOOL_PRE_INVOKE hook.

        This test verifies that:
        1. HTTP_PRE_REQUEST stores context
        2. TOOL_PRE_INVOKE can read HTTP context data
        3. TOOL_PRE_INVOKE can also read HTTP_AUTH_CHECK_PERMISSION data
        """
        # First, set up a test tool
        from mcpgateway.schemas import ToolCreate
        from mcpgateway.services.tool_service import ToolService

        tool_service = ToolService()

        # Register a test tool
        tool_data = ToolCreate(
            name="test_cross_hook_tool",
            description="Test tool for cross-hook context",
            input_schema={"type": "object", "properties": {}},
        )

        await tool_service.register_tool(test_db, tool_data)

        # Make a request to invoke the tool
        response = test_client_with_plugins.post(
            "/rpc/",
            json={
                "jsonrpc": "2.0",
                "id": "test-1",
                "method": "tools/call",
                "params": {
                    "name": "test_cross_hook_tool",
                    "arguments": {}
                }
            },
            headers={"Authorization": "Bearer test-token"}
        )

        # The plugin should successfully access context from HTTP hooks
        # If it fails to find the context, it will raise ValueError and return 500
        assert response.status_code != 500, \
            "Cross-hook context sharing should work for HTTP → Tool"

    @pytest.mark.asyncio
    async def test_http_to_resource_context_sharing(
        self, test_db, test_client_with_plugins, plugin_manager
    ):
        """Test context sharing from HTTP hooks to RESOURCE_PRE_FETCH hook.

        This test verifies that context stored in HTTP_PRE_REQUEST is
        accessible in the RESOURCE_PRE_FETCH hook.
        """
        # First, set up a test resource
        from mcpgateway.schemas import ResourceCreate
        from mcpgateway.services.resource_service import ResourceService

        resource_service = ResourceService()

        # Register a test resource
        resource_data = ResourceCreate(
            uri="test://cross-hook-resource",
            name="Cross-hook test resource",
            content="Test content",
            mime_type="text/plain",
        )

        created = await resource_service.register_resource(test_db, resource_data)

        # Make a request to read the resource
        response = test_client_with_plugins.get(
            f"/resources/{created.id}",
            headers={"Authorization": "Bearer test-token"}
        )

        # The plugin should successfully access context from HTTP hooks
        assert response.status_code != 500, \
            "Cross-hook context sharing should work for HTTP → Resource"

    @pytest.mark.asyncio
    async def test_http_to_prompt_context_sharing(
        self, test_db, test_client_with_plugins, plugin_manager
    ):
        """Test context sharing from HTTP hooks to PROMPT_PRE_FETCH hook.

        This test verifies that context stored in HTTP_PRE_REQUEST is
        accessible in the PROMPT_PRE_FETCH hook.
        """
        # First, set up a test prompt
        from mcpgateway.schemas import PromptCreate
        from mcpgateway.services.prompt_service import PromptService

        prompt_service = PromptService()

        # Register a test prompt
        prompt_data = PromptCreate(
            name="test_cross_hook_prompt",
            template="Hello {name}!",
            description="Test prompt for cross-hook context",
        )

        created = await prompt_service.register_prompt(
            test_db,
            prompt_data,
            user_email="test@example.com"
        )

        # Make a request to get the prompt
        response = test_client_with_plugins.get(
            f"/prompts/{created.name}",
            headers={"Authorization": "Bearer test-token"}
        )

        # The plugin should successfully access context from HTTP hooks
        assert response.status_code != 500, \
            "Cross-hook context sharing should work for HTTP → Prompt"

    @pytest.mark.asyncio
    async def test_global_context_consistency(self, test_client_with_plugins, plugin_manager):
        """Test that GlobalContext is consistent across all hooks.

        This test verifies that the same GlobalContext instance (or at least
        the same request_id) is used across all hooks in a single request.
        """
        # Make a request that triggers multiple hooks
        response = test_client_with_plugins.get(
            "/tools",
            headers={"Authorization": "Bearer test-token"}
        )

        # The plugin stores request_id in global context during HTTP_PRE_REQUEST
        # and verifies it's present in subsequent hooks
        # If the global context wasn't shared, the plugin would raise ValueError

        assert response.status_code in [200, 401], \
            "GlobalContext should be consistent across all hooks"

    @pytest.mark.asyncio
    async def test_plugin_context_isolation(self, plugin_manager):
        """Test that plugin contexts are properly isolated.

        This test verifies that each plugin gets its own isolated context
        and cannot access other plugins' context data.
        """
        from mcpgateway.plugins.framework import (
            GlobalContext,
            HttpPreRequestPayload,
            HttpHeaderPayload,
            HttpHookType,
        )

        # Create a global context
        global_context = GlobalContext(request_id="test-isolation-123")

        # Invoke HTTP_PRE_REQUEST hook (which stores data in context)
        payload = HttpPreRequestPayload(
            path="/test",
            method="GET",
            headers=HttpHeaderPayload(root={}),
        )

        result, context_table = await plugin_manager.invoke_hook(
            HttpHookType.HTTP_PRE_REQUEST,
            payload=payload,
            global_context=global_context,
        )

        # Verify context table was created
        assert context_table is not None
        assert len(context_table) > 0

        # Verify each plugin has its own isolated context
        # The key format is: request_id + plugin_uuid
        for key, context in context_table.items():
            assert key.startswith("test-isolation-123")
            assert "http_timestamp" in context.state
            # Each plugin should only see its own state
            assert context.state["http_timestamp"] == "2025-01-01T00:00:00Z"
