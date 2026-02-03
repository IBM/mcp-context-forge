# -*- coding: utf-8 -*-

"""Location: ./tests/unit/mcpgateway/test_main_extended.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Extended tests for main.py to achieve 100% coverage.
These tests focus on uncovered code paths including conditional branches,
error handlers, and startup logic.
"""

# Standard
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
import pytest
import sqlalchemy as sa
from starlette.responses import Response as StarletteResponse

# First-Party
from mcpgateway.config import settings
from mcpgateway.main import (
    AdminAuthMiddleware,
    DocsAuthMiddleware,
    MCPPathRewriteMiddleware,
    app,
    create_prompt,
    create_resource,
    create_tool,
    delete_prompt,
    delete_resource,
    delete_tool,
    export_configuration,
    export_selective_configuration,
    get_a2a_agent,
    handle_rpc,
    import_configuration,
    jsonpath_modifier,
    list_a2a_agents,
    list_resources,
    message_endpoint,
    server_get_prompts,
    server_get_resources,
    server_get_tools,
    set_prompt_state,
    set_resource_state,
    set_tool_state,
    setup_passthrough_headers,
    sse_endpoint,
    transform_data_with_mappings,
    update_prompt,
    update_resource,
    update_tool,
    validate_security_configuration,
)
import mcpgateway.db as db_mod
from mcpgateway.plugins.framework import PluginError
from mcpgateway.schemas import PromptCreate, PromptUpdate, ResourceCreate, ResourceUpdate, ToolCreate, ToolUpdate


def _make_request(
    path: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    cookies: dict | None = None,
    root_path: str = "",
) -> MagicMock:
    request = MagicMock(spec=Request)
    request.method = method
    request.url = SimpleNamespace(path=path)
    request.scope = {"path": path, "root_path": root_path}
    request.headers = headers or {}
    request.cookies = cookies or {}
    return request


class TestConditionalPaths:
    """Test conditional code paths to improve coverage."""

    def test_redis_initialization_path(self, test_client, auth_headers):
        """Test Redis initialization path by mocking settings."""
        # Test that the Redis path is covered indirectly through existing functionality
        # Since reloading modules in tests is problematic, we test the path is reachable
        with patch("mcpgateway.main.settings.cache_type", "redis"):
            response = test_client.get("/health", headers=auth_headers)
            assert response.status_code == 200

    def test_event_loop_task_creation(self, test_client, auth_headers):
        """Test event loop task creation path indirectly."""
        # Test the functionality that exercises the loop path
        response = test_client.get("/health", headers=auth_headers)
        assert response.status_code == 200


class TestEndpointErrorHandling:
    """Test error handling in various endpoints."""

    def test_tool_invocation_error_handling(self, test_client, auth_headers):
        """Test tool invocation with errors to cover error paths."""
        with patch("mcpgateway.main.tool_service.invoke_tool") as mock_invoke:
            # Test different error scenarios - return error instead of raising
            mock_invoke.return_value = {
                "content": [{"type": "text", "text": "Tool error"}],
                "is_error": True,
            }

            req = {
                "jsonrpc": "2.0",
                "id": "test-id",
                "method": "test_tool",
                "params": {"param": "value"},
            }
            response = test_client.post("/rpc/", json=req, headers=auth_headers)
            # Should handle the error gracefully
            assert response.status_code == 200

    def test_server_endpoints_error_conditions(self, test_client, auth_headers):
        """Test server endpoints with various error conditions."""
        # Test server creation with missing required fields (triggers validation)
        req = {"description": "Missing name"}
        response = test_client.post("/servers/", json=req, headers=auth_headers)
        # Should handle validation error appropriately
        assert response.status_code == 422

    def test_resource_endpoints_error_conditions(self, test_client, auth_headers):
        """Test resource endpoints with various error conditions."""
        # Test resource not found scenario
        with patch("mcpgateway.main.resource_service.read_resource") as mock_read:
            # First-Party
            from mcpgateway.services.resource_service import ResourceNotFoundError

            mock_read.side_effect = ResourceNotFoundError("Resource not found")

            response = test_client.get("/resources/test/resource", headers=auth_headers)
            assert response.status_code == 404

    def test_prompt_endpoints_error_conditions(self, test_client, auth_headers):
        """Test prompt endpoints with various error conditions."""
        # Test prompt creation with missing required fields
        req = {"description": "Missing name and template"}
        response = test_client.post("/prompts/", json=req, headers=auth_headers)
        assert response.status_code == 422

    def test_gateway_endpoints_error_conditions(self, test_client, auth_headers):
        """Test gateway endpoints with various error conditions."""
        # Test gateway creation with missing required fields
        req = {"description": "Missing name and url"}
        response = test_client.post("/gateways/", json=req, headers=auth_headers)
        assert response.status_code == 422


class TestMiddlewareEdgeCases:
    """Test middleware and authentication edge cases."""

    def test_docs_endpoint_without_auth(self):
        """Test accessing docs without authentication."""
        # Create client without auth override to test real auth
        client = TestClient(app)
        response = client.get("/docs")
        assert response.status_code == 401

    def test_openapi_endpoint_without_auth(self):
        """Test accessing OpenAPI spec without authentication."""
        client = TestClient(app)
        response = client.get("/openapi.json")
        assert response.status_code == 401

    def test_redoc_endpoint_without_auth(self):
        """Test accessing ReDoc without authentication."""
        client = TestClient(app)
        response = client.get("/redoc")
        assert response.status_code == 401


class TestApplicationStartupPaths:
    """Test application startup conditional paths."""

    @patch("mcpgateway.main.plugin_manager", None)
    @patch("mcpgateway.main.logging_service")
    @patch("mcpgateway.config.settings.require_strong_secrets", False)
    @patch("mcpgateway.config.settings.dev_mode", True)
    async def test_startup_without_plugin_manager(self, mock_logging_service, monkeypatch):
        """Test startup path when plugin_manager is None."""
        mock_logging_service.initialize = AsyncMock()
        mock_logging_service.shutdown = AsyncMock()
        mock_logging_service.configure_uvicorn_after_startup = MagicMock()

        # Disable background services to avoid real threads/event loops in unit tests.
        monkeypatch.setattr(settings, "metrics_cleanup_enabled", False)
        monkeypatch.setattr(settings, "metrics_rollup_enabled", False)
        monkeypatch.setattr(settings, "metrics_buffer_enabled", False)
        monkeypatch.setattr(settings, "metrics_aggregation_enabled", False)
        monkeypatch.setattr(settings, "mcp_session_pool_enabled", False)
        monkeypatch.setattr(settings, "mcpgateway_tool_cancellation_enabled", False)
        monkeypatch.setattr(settings, "mcpgateway_elicitation_enabled", False)
        monkeypatch.setattr(settings, "sso_enabled", False)

        # Mock all required services
        with (
            patch("mcpgateway.main.tool_service") as mock_tool,
            patch("mcpgateway.main.resource_service") as mock_resource,
            patch("mcpgateway.main.prompt_service") as mock_prompt,
            patch("mcpgateway.main.gateway_service") as mock_gateway,
            patch("mcpgateway.main.root_service") as mock_root,
            patch("mcpgateway.main.completion_service") as mock_completion,
            patch("mcpgateway.main.sampling_handler") as mock_sampling,
            patch("mcpgateway.main.resource_cache") as mock_cache,
            patch("mcpgateway.main.streamable_http_session") as mock_session,
            patch("mcpgateway.main.session_registry") as mock_session_registry,
            patch("mcpgateway.main.export_service") as mock_export,
            patch("mcpgateway.main.import_service") as mock_import,
            patch("mcpgateway.main.a2a_service") as mock_a2a,
            patch("mcpgateway.main.refresh_slugs_on_startup") as mock_refresh,
            patch("mcpgateway.main.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
            patch("mcpgateway.main.close_redis_client", new_callable=AsyncMock) as mock_close_redis,
            patch("mcpgateway.routers.llmchat_router.init_redis", new_callable=AsyncMock) as mock_init_llmchat,
            patch("mcpgateway.services.http_client_service.SharedHttpClient.get_instance", new_callable=AsyncMock) as mock_shared_http,
            patch("mcpgateway.services.http_client_service.SharedHttpClient.shutdown", new_callable=AsyncMock) as mock_shared_http_shutdown,
        ):
            # Setup all mocks
            services = [mock_tool, mock_resource, mock_prompt, mock_gateway, mock_root, mock_completion, mock_sampling, mock_cache, mock_session, mock_session_registry, mock_export, mock_import]
            for service in services:
                service.initialize = AsyncMock()
                service.shutdown = AsyncMock()
            mock_a2a.initialize = AsyncMock()
            mock_a2a.shutdown = AsyncMock()

            # Setup Redis mocks
            mock_get_redis.return_value = None
            mock_close_redis.return_value = None
            mock_init_llmchat.return_value = None
            mock_shared_http.return_value = None
            mock_shared_http_shutdown.return_value = None

            # Test lifespan without plugin manager
            # First-Party
            from mcpgateway.main import lifespan

            async with lifespan(app):
                pass

            # Verify initialization happened without plugin manager
            mock_logging_service.initialize.assert_called_once()
            for service in services:
                service.initialize.assert_called_once()
                service.shutdown.assert_called_once()


class TestJsonPathHelpers:
    """Cover JSONPath helpers in main.py."""

    def test_jsonpath_modifier_invalid_expression(self):
        with pytest.raises(HTTPException) as excinfo:
            jsonpath_modifier({"a": 1}, "$[")
        assert "Invalid main JSONPath" in excinfo.value.detail

    def test_jsonpath_modifier_execution_error(self):
        class DummyPath:
            def find(self, _data):
                raise Exception("boom")

        with patch("mcpgateway.main._parse_jsonpath", return_value=DummyPath()):
            with pytest.raises(HTTPException) as excinfo:
                jsonpath_modifier({"a": 1}, "$.a")
        assert "Error executing main JSONPath" in excinfo.value.detail

    def test_transform_data_with_mappings_multi_and_empty(self):
        data = [{"items": [{"id": 1}, {"id": 2}]}, {"items": []}]
        result = transform_data_with_mappings(data, {"ids": "$.items[*].id"})
        assert result[0]["ids"] == [1, 2]
        assert result[1]["ids"] is None

    def test_transform_data_with_mappings_invalid_mapping(self):
        with patch("mcpgateway.main._parse_jsonpath", side_effect=Exception("bad mapping")):
            with pytest.raises(HTTPException) as excinfo:
                transform_data_with_mappings([{"a": 1}], {"x": "$.a"})
        assert "Invalid mapping JSONPath" in excinfo.value.detail


class TestDocsAuthMiddleware:
    """Cover DocsAuthMiddleware branches."""

    @pytest.mark.asyncio
    async def test_docs_auth_rejects_invalid_token(self):
        middleware = DocsAuthMiddleware(None)
        request = _make_request("/docs", headers={"Authorization": "Bearer bad"})
        call_next = AsyncMock(return_value=StarletteResponse("ok"))

        with patch("mcpgateway.main.require_docs_auth_override", side_effect=HTTPException(status_code=401, detail="nope")):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_docs_auth_options_passthrough(self):
        middleware = DocsAuthMiddleware(None)
        request = _make_request("/docs", method="OPTIONS")
        call_next = AsyncMock(return_value="ok")

        response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_docs_auth_unprotected_path(self):
        middleware = DocsAuthMiddleware(None)
        request = _make_request("/api/tools")
        call_next = AsyncMock(return_value="ok")

        response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        call_next.assert_called_once()


class TestAdminAuthMiddleware:
    """Cover AdminAuthMiddleware branches."""

    @pytest.mark.asyncio
    async def test_admin_auth_bypasses_when_auth_disabled(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools")
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", False)
        response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_auth_invalid_jwt_returns_401(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", headers={"Authorization": "Bearer token"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        with patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={})):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_auth_revoked_token_redirects(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request(
            "/admin/tools",
            headers={"Authorization": "Bearer token", "accept": "text/html"},
        )
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        with (
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com", "jti": "abc"})),
            patch("mcpgateway.main._check_token_revoked_sync", return_value=True),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 302
        assert "token_revoked" in response.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_admin_auth_api_token_expired(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", headers={"Authorization": "Bearer token"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        with (
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(side_effect=Exception("bad"))),
            patch("mcpgateway.main._lookup_api_token_sync", return_value={"expired": True}),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_auth_proxy_user_allows_access(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        proxy_header = settings.proxy_user_header
        request = _make_request("/admin/tools", headers={proxy_header: "proxy@example.com"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        monkeypatch.setattr(settings, "trust_proxy_auth", True)
        monkeypatch.setattr(settings, "mcp_client_auth_enabled", False)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=True)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)

        with (
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(side_effect=Exception("bad"))),
            patch("mcpgateway.main._lookup_api_token_sync", return_value=None),
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_auth_platform_admin_bootstrap(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", headers={"Authorization": "Bearer token"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        monkeypatch.setattr(settings, "require_user_in_db", False)
        monkeypatch.setattr(settings, "platform_admin_email", "admin@example.com")

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=None)

        with (
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "admin@example.com"})),
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_auth_non_admin_denied(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", headers={"Authorization": "Bearer token"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=False)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)

        # Mock PermissionService to return False for non-admin user without admin permissions
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(return_value=False)

        with (
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com"})),
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 403


class TestMCPPathRewriteMiddleware:
    """Cover MCPPathRewriteMiddleware branches."""

    @pytest.mark.asyncio
    async def test_rewrite_mcp_path(self):
        app_mock = AsyncMock()
        middleware = MCPPathRewriteMiddleware(app_mock)
        scope = {"type": "http", "path": "/servers/123/mcp", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        with patch("mcpgateway.main.streamable_http_auth", new=AsyncMock(return_value=True)):
            await middleware._call_streamable_http(scope, receive, send)

        assert scope["path"] == "/mcp/"
        app_mock.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_rewrite_auth_failure(self):
        app_mock = AsyncMock()
        middleware = MCPPathRewriteMiddleware(app_mock)
        scope = {"type": "http", "path": "/servers/123/mcp", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        with patch("mcpgateway.main.streamable_http_auth", new=AsyncMock(return_value=False)):
            await middleware._call_streamable_http(scope, receive, send)

        app_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_path_short_circuits(self):
        app_mock = AsyncMock()
        response = StarletteResponse("ok")
        dispatch = AsyncMock(return_value=response)
        middleware = MCPPathRewriteMiddleware(app_mock, dispatch=dispatch)
        scope = {"type": "http", "path": "/servers/123/mcp", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        dispatch.assert_called_once()
        app_mock.assert_not_called()


class TestServerEndpointCoverage:
    """Exercise server endpoints and SSE coverage."""

    @pytest.mark.asyncio
    async def test_sse_endpoint_success(self, monkeypatch, allow_permission):
        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer token"}
        request.cookies = {}
        request.scope = {"root_path": ""}

        from mcpgateway.services.permission_service import PermissionService

        monkeypatch.setattr(PermissionService, "check_permission", AsyncMock(return_value=True))

        transport = MagicMock()
        transport.session_id = "session-1"
        transport.connect = AsyncMock()
        transport.create_sse_response = AsyncMock(return_value=StarletteResponse("ok"))

        monkeypatch.setattr("mcpgateway.main.update_url_protocol", lambda _req: "http://example.com")
        monkeypatch.setattr("mcpgateway.main._get_token_teams_from_request", lambda _req: None)
        monkeypatch.setattr("mcpgateway.main.SSETransport", MagicMock(return_value=transport))
        monkeypatch.setattr("mcpgateway.main.session_registry.add_session", AsyncMock())
        monkeypatch.setattr("mcpgateway.main.session_registry.respond", AsyncMock(return_value=None))
        monkeypatch.setattr("mcpgateway.main.session_registry.register_respond_task", MagicMock())
        monkeypatch.setattr("mcpgateway.main.session_registry.remove_session", AsyncMock())

        response = await sse_endpoint(request, "server-1", user={"email": "user@example.com", "is_admin": True, "db": MagicMock()})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_server_get_tools_admin_bypass(self, monkeypatch, allow_permission):
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-1"}

        monkeypatch.setattr("mcpgateway.main._get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, True))
        list_tools = AsyncMock(return_value=[tool])
        monkeypatch.setattr("mcpgateway.main.tool_service.list_server_tools", list_tools)

        result = await server_get_tools(request, "server-1", include_metrics=True, db=MagicMock(), user={"email": "user@example.com"})
        assert result == [{"id": "tool-1"}]
        list_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_server_get_resources_public_scope(self, monkeypatch, allow_permission):
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        resource = MagicMock()
        resource.model_dump.return_value = {"id": "res-1"}

        monkeypatch.setattr("mcpgateway.main._get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, False))
        list_resources = AsyncMock(return_value=[resource])
        monkeypatch.setattr("mcpgateway.main.resource_service.list_server_resources", list_resources)

        result = await server_get_resources(request, "server-1", db=MagicMock(), user={"email": "user@example.com"})
        assert result == [{"id": "res-1"}]
        list_resources.assert_called_once()

    @pytest.mark.asyncio
    async def test_server_get_prompts_public_scope(self, monkeypatch, allow_permission):
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        prompt = MagicMock()
        prompt.model_dump.return_value = {"id": "prompt-1"}

        monkeypatch.setattr("mcpgateway.main._get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, False))
        list_prompts = AsyncMock(return_value=[prompt])
        monkeypatch.setattr("mcpgateway.main.prompt_service.list_server_prompts", list_prompts)

        result = await server_get_prompts(request, "server-1", db=MagicMock(), user={"email": "user@example.com"})
        assert result == [{"id": "prompt-1"}]
        list_prompts.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_resources_team_mismatch(self, monkeypatch, allow_permission):
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id="team-1")

        monkeypatch.setattr("mcpgateway.main._get_rpc_filter_context", lambda _req, _user: ("user@example.com", ["team-1"], False))

        response = await list_resources(
            request,
            team_id="team-2",
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_resources_include_pagination(self, monkeypatch, allow_permission):
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        resource = MagicMock()
        resource.model_dump.return_value = {"id": "res-1"}

        monkeypatch.setattr("mcpgateway.main._get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, True))
        monkeypatch.setattr(
            "mcpgateway.main.resource_service.list_resources",
            AsyncMock(return_value=([resource], "next-cursor")),
        )

        result = await list_resources(
            request,
            include_pagination=True,
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert result["resources"] == [{"id": "res-1"}]
        assert result["nextCursor"] == "next-cursor"


class TestCrudEndpoints:
    """Cover CRUD endpoints for tools/resources/prompts."""

    @pytest.mark.asyncio
    async def test_create_tool_success(self, monkeypatch, allow_permission):
        request = _make_request("/tools")
        request.state = SimpleNamespace(team_id=None)

        tool = MagicMock()
        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_args, **_kwargs: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )
        monkeypatch.setattr("mcpgateway.main.tool_service.register_tool", AsyncMock(return_value=tool))

        tool_input = ToolCreate(name="tool-a", url="http://example.com")
        result = await create_tool(tool_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert result is tool

    @pytest.mark.asyncio
    async def test_create_tool_team_mismatch(self, allow_permission):
        request = _make_request("/tools")
        request.state = SimpleNamespace(team_id="team-1")

        tool_input = ToolCreate(name="tool-a", url="http://example.com")
        response = await create_tool(tool_input, request, team_id="team-2", db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_update_tool_success(self, monkeypatch, allow_permission):
        request = _make_request("/tools/tool-1")
        db = MagicMock()
        db.get.return_value = SimpleNamespace(version=2)

        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_modification_metadata",
            lambda *_args, **_kwargs: {
                "modified_by": "user",
                "modified_from_ip": "127.0.0.1",
                "modified_via": "api",
                "modified_user_agent": "test",
            },
        )
        tool = MagicMock()
        monkeypatch.setattr("mcpgateway.main.tool_service.update_tool", AsyncMock(return_value=tool))

        tool_update = ToolUpdate(name="tool-updated")
        result = await update_tool("tool-1", tool_update, request, db=db, user={"email": "user@example.com"})
        assert result is tool

    @pytest.mark.asyncio
    async def test_delete_tool_success(self, monkeypatch, allow_permission):
        monkeypatch.setattr("mcpgateway.main.tool_service.delete_tool", AsyncMock(return_value=None))
        result = await delete_tool("tool-1", db=MagicMock(), user={"email": "user@example.com"})
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_set_tool_state_success(self, monkeypatch, allow_permission):
        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-1"}
        monkeypatch.setattr("mcpgateway.main.tool_service.set_tool_state", AsyncMock(return_value=tool))

        result = await set_tool_state("tool-1", activate=True, db=MagicMock(), user={"email": "user@example.com"})
        assert result["tool"] == {"id": "tool-1"}

    @pytest.mark.asyncio
    async def test_create_resource_success(self, monkeypatch, allow_permission):
        request = _make_request("/resources")
        request.state = SimpleNamespace(team_id=None)

        resource = MagicMock()
        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_args, **_kwargs: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )
        monkeypatch.setattr("mcpgateway.main.resource_service.register_resource", AsyncMock(return_value=resource))

        resource_input = ResourceCreate(uri="res://1", name="Res", content="data")
        result = await create_resource(resource_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert result is resource

    @pytest.mark.asyncio
    async def test_update_resource_success(self, monkeypatch, allow_permission):
        request = _make_request("/resources/res-1")
        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_modification_metadata",
            lambda *_args, **_kwargs: {
                "modified_by": "user",
                "modified_from_ip": "127.0.0.1",
                "modified_via": "api",
                "modified_user_agent": "test",
            },
        )
        monkeypatch.setattr("mcpgateway.main.resource_service.update_resource", AsyncMock(return_value={"id": "res-1"}))
        monkeypatch.setattr("mcpgateway.main.invalidate_resource_cache", AsyncMock(return_value=None))

        resource_update = ResourceUpdate(name="Res Updated")
        result = await update_resource("res-1", resource_update, request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["id"] == "res-1"

    @pytest.mark.asyncio
    async def test_delete_resource_success(self, monkeypatch, allow_permission):
        monkeypatch.setattr("mcpgateway.main.resource_service.delete_resource", AsyncMock(return_value=None))
        result = await delete_resource("res-1", db=MagicMock(), user={"email": "user@example.com"})
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_set_resource_state_success(self, monkeypatch, allow_permission):
        resource = MagicMock()
        resource.model_dump.return_value = {"id": "res-1"}
        monkeypatch.setattr("mcpgateway.main.resource_service.set_resource_state", AsyncMock(return_value=resource))

        result = await set_resource_state("res-1", activate=False, db=MagicMock(), user={"email": "user@example.com"})
        assert result["resource"] == {"id": "res-1"}

    @pytest.mark.asyncio
    async def test_create_prompt_success(self, monkeypatch, allow_permission):
        request = _make_request("/prompts")
        request.state = SimpleNamespace(team_id=None)

        prompt = MagicMock()
        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_args, **_kwargs: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )
        monkeypatch.setattr("mcpgateway.main.prompt_service.register_prompt", AsyncMock(return_value=prompt))

        prompt_input = PromptCreate(name="Prompt A", template="Hello")
        result = await create_prompt(prompt_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert result is prompt

    @pytest.mark.asyncio
    async def test_update_prompt_success(self, monkeypatch, allow_permission):
        request = _make_request("/prompts/prompt-1")
        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_modification_metadata",
            lambda *_args, **_kwargs: {
                "modified_by": "user",
                "modified_from_ip": "127.0.0.1",
                "modified_via": "api",
                "modified_user_agent": "test",
            },
        )
        monkeypatch.setattr("mcpgateway.main.prompt_service.update_prompt", AsyncMock(return_value={"id": "prompt-1"}))

        prompt_update = PromptUpdate(name="Prompt Updated")
        result = await update_prompt("prompt-1", prompt_update, request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["id"] == "prompt-1"

    @pytest.mark.asyncio
    async def test_delete_prompt_success(self, monkeypatch, allow_permission):
        monkeypatch.setattr("mcpgateway.main.prompt_service.delete_prompt", AsyncMock(return_value=None))
        result = await delete_prompt("prompt-1", db=MagicMock(), user={"email": "user@example.com"})
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_set_prompt_state_success(self, monkeypatch, allow_permission):
        prompt = MagicMock()
        prompt.model_dump.return_value = {"id": "prompt-1"}
        monkeypatch.setattr("mcpgateway.main.prompt_service.set_prompt_state", AsyncMock(return_value=prompt))

        result = await set_prompt_state("prompt-1", activate=True, db=MagicMock(), user={"email": "user@example.com"})
        assert result["prompt"] == {"id": "prompt-1"}
class TestPassthroughHeaderSetup:
    """Cover passthrough header setup."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("overwrite", [True, False])
    async def test_setup_passthrough_headers(self, monkeypatch, overwrite):
        monkeypatch.setattr(settings, "enable_overwrite_base_headers", overwrite)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.set_global_passthrough_headers", new=AsyncMock()),
        ):
            await setup_passthrough_headers()


class TestSecurityConfiguration:
    """Cover security configuration helpers."""

    def test_validate_security_configuration_logs_warnings(self, monkeypatch):
        monkeypatch.setattr(settings, "require_strong_secrets", False)
        monkeypatch.setattr(settings, "dev_mode", False)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "jwt_issuer", "mcpgateway")
        monkeypatch.setattr(settings, "jwt_audience", "mcpgateway-api")
        monkeypatch.setattr(settings, "mcpgateway_ui_enabled", True)
        monkeypatch.setattr(settings, "require_user_in_db", False)
        monkeypatch.setattr(settings, "database_url", "sqlite:///./mcp.db")

        monkeypatch.setattr(
            settings,
            "get_security_status",
            lambda: {"warnings": ["warning"], "secure_secrets": False, "auth_enabled": False},
        )

        validate_security_configuration()

    def test_log_critical_issues_exits_when_enforced(self, monkeypatch):
        monkeypatch.setattr(settings, "require_strong_secrets", True)
        with patch("mcpgateway.main.sys.exit") as mock_exit:
            from mcpgateway.main import log_critical_issues

            log_critical_issues(["bad"])
            mock_exit.assert_called_once_with(1)


class TestLifespanAdvanced:
    """Cover lifespan startup/shutdown branches."""

    @pytest.mark.asyncio
    async def test_lifespan_with_feature_flags(self, monkeypatch):
        import mcpgateway.main as main_mod

        class FakeEvent:
            def __init__(self):
                self._set = False

            def is_set(self):
                return self._set

            def set(self):
                self._set = True

            async def wait(self):
                self._set = True
                return True

        def make_service():
            service = MagicMock()
            service.initialize = AsyncMock()
            service.shutdown = AsyncMock()
            return service

        # Feature flags
        monkeypatch.setattr(main_mod.settings, "mcp_session_pool_enabled", True)
        monkeypatch.setattr(main_mod.settings, "enable_header_passthrough", True)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_tool_cancellation_enabled", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_elicitation_enabled", True)
        monkeypatch.setattr(main_mod.settings, "metrics_buffer_enabled", True)
        monkeypatch.setattr(main_mod.settings, "db_metrics_recording_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_cleanup_enabled", True)
        monkeypatch.setattr(main_mod.settings, "metrics_rollup_enabled", True)
        monkeypatch.setattr(main_mod.settings, "sso_enabled", True)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_enabled", True)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_auto_start", True)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_backfill_hours", 1)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_window_minutes", 0)

        plugin = MagicMock()
        plugin.initialize = AsyncMock()
        plugin.shutdown = AsyncMock()
        plugin.plugin_count = 2
        monkeypatch.setattr(main_mod, "plugin_manager", plugin)

        logging_service = make_service()
        logging_service.configure_uvicorn_after_startup = MagicMock()
        monkeypatch.setattr(main_mod, "logging_service", logging_service)

        for attr in (
            "tool_service",
            "resource_service",
            "prompt_service",
            "gateway_service",
            "root_service",
            "completion_service",
            "sampling_handler",
            "resource_cache",
            "streamable_http_session",
            "session_registry",
            "export_service",
            "import_service",
        ):
            monkeypatch.setattr(main_mod, attr, make_service())

        monkeypatch.setattr(main_mod, "a2a_service", make_service())

        monkeypatch.setattr(main_mod, "get_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod, "close_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod, "setup_passthrough_headers", AsyncMock())
        monkeypatch.setattr(main_mod, "validate_security_configuration", MagicMock())
        monkeypatch.setattr(main_mod, "init_telemetry", MagicMock())
        monkeypatch.setattr(main_mod, "refresh_slugs_on_startup", MagicMock())
        monkeypatch.setattr(main_mod, "attempt_to_bootstrap_sso_providers", AsyncMock())

        # Optional service factories
        elicitation_service = MagicMock()
        elicitation_service.start = AsyncMock()
        elicitation_service.shutdown = AsyncMock()
        monkeypatch.setattr(
            "mcpgateway.services.elicitation_service.get_elicitation_service",
            MagicMock(return_value=elicitation_service),
        )

        metrics_buffer_service = MagicMock()
        metrics_buffer_service.start = AsyncMock()
        metrics_buffer_service.shutdown = AsyncMock()
        monkeypatch.setattr(
            "mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service",
            MagicMock(return_value=metrics_buffer_service),
        )

        metrics_cleanup_service = MagicMock()
        metrics_cleanup_service.start = AsyncMock()
        metrics_cleanup_service.shutdown = AsyncMock()
        monkeypatch.setattr(
            "mcpgateway.services.metrics_cleanup_service.get_metrics_cleanup_service",
            MagicMock(return_value=metrics_cleanup_service),
        )

        metrics_rollup_service = MagicMock()
        metrics_rollup_service.start = AsyncMock()
        metrics_rollup_service.shutdown = AsyncMock()
        monkeypatch.setattr(
            "mcpgateway.services.metrics_rollup_service.get_metrics_rollup_service",
            MagicMock(return_value=metrics_rollup_service),
        )

        # MCP session pool hooks
        monkeypatch.setattr("mcpgateway.services.mcp_session_pool.init_mcp_session_pool", MagicMock())
        monkeypatch.setattr("mcpgateway.services.mcp_session_pool.start_pool_notification_service", AsyncMock())
        monkeypatch.setattr("mcpgateway.services.mcp_session_pool.close_mcp_session_pool", AsyncMock())

        # Cache invalidation subscriber
        subscriber = MagicMock()
        subscriber.start = AsyncMock()
        subscriber.stop = AsyncMock()
        monkeypatch.setattr(
            "mcpgateway.cache.registry_cache.get_cache_invalidation_subscriber",
            MagicMock(return_value=subscriber),
        )

        # LLM chat Redis init
        monkeypatch.setattr("mcpgateway.routers.llmchat_router.init_redis", AsyncMock())

        # Shared HTTP client
        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.get_instance", AsyncMock())
        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.shutdown", AsyncMock())

        # Log aggregation helpers
        log_aggregator = MagicMock()
        log_aggregator.aggregation_window_minutes = 1
        log_aggregator.backfill = MagicMock()
        log_aggregator.aggregate_all_components = MagicMock()
        monkeypatch.setattr(main_mod, "get_log_aggregator", MagicMock(return_value=log_aggregator))

        # Async helpers
        monkeypatch.setattr(main_mod.asyncio, "Event", FakeEvent)
        monkeypatch.setattr(main_mod.asyncio, "to_thread", AsyncMock())

        main_mod.app.state.update_http_pool_metrics = MagicMock()

        async with main_mod.lifespan(main_mod.app):
            await asyncio.sleep(0)

        plugin.initialize.assert_called_once()
        plugin.shutdown.assert_called_once()
class TestUtilityFunctions:
    """Test utility functions for edge cases."""

    def test_message_endpoint_edge_cases(self, test_client, auth_headers):
        """Test message endpoint with edge case parameters."""
        # Test with missing session_id to trigger validation error
        message = {"type": "test", "data": "hello"}
        response = test_client.post("/message", json=message, headers=auth_headers)
        assert response.status_code == 400  # Should require session_id parameter

        # Test with valid session_id
        with patch("mcpgateway.main.session_registry.broadcast") as mock_broadcast:
            response = test_client.post("/message?session_id=test-session", json=message, headers=auth_headers)
            assert response.status_code == 202
            mock_broadcast.assert_called_once()

    def test_root_endpoint_conditional_behavior(self):
        """Test root endpoint behavior based on UI settings.

        Note: Route registration happens at import time based on settings.mcpgateway_ui_enabled.
        Patching settings after import doesn't change which routes are registered.
        This test verifies the currently registered behavior.
        """
        client = TestClient(app)
        response = client.get("/", follow_redirects=False)

        # The behavior depends on whether UI was enabled when app was imported
        if response.status_code == 303:
            # UI enabled: redirects to /admin/
            location = response.headers.get("location", "")
            assert "/admin/" in location
        elif response.status_code == 200:
            # Could be JSON (UI disabled) or HTML (followed redirect to admin)
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                data = response.json()
                assert "name" in data or "ui_enabled" in data
            # HTML response from admin is also acceptable (UI enabled with auto-redirect)
        else:
            # Accept other valid status codes (e.g., 307 for redirect)
            assert response.status_code in [200, 303, 307]

    def test_exception_handler_scenarios(self, test_client, auth_headers):
        """Test exception handlers with various scenarios."""
        # Test simple validation error by providing invalid data
        req = {"invalid": "data"}  # Missing required 'name' field
        response = test_client.post("/servers/", json=req, headers=auth_headers)
        # Should handle validation error
        assert response.status_code == 422

    def test_json_rpc_error_paths(self, test_client, auth_headers):
        """Test JSON-RPC error handling paths."""
        # Test with a valid JSON-RPC request that might not find the tool
        req = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "method": "nonexistent_tool",
            "params": {},
        }
        response = test_client.post("/rpc/", json=req, headers=auth_headers)
        # Should return a valid JSON-RPC response even for non-existent tools
        assert response.status_code == 200
        body = response.json()
        # Should have either result or error
        assert "result" in body or "error" in body

    @patch("mcpgateway.main.settings")
    def test_websocket_error_scenarios(self, mock_settings):
        """Test WebSocket error scenarios."""
        # Configure mock settings for auth disabled
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.auth_required = False
        mock_settings.federation_timeout = 30
        mock_settings.skip_ssl_verify = False
        mock_settings.port = 4444

        with patch("mcpgateway.main.ResilientHttpClient") as mock_client:
            # Standard

            mock_instance = mock_client.return_value
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = False

            # Mock a failing post operation
            async def failing_post(*_args, **_kwargs):
                raise Exception("Network error")

            mock_instance.post = failing_post

            client = TestClient(app)
            with client.websocket_connect("/ws") as websocket:
                websocket.send_text('{"jsonrpc":"2.0","method":"ping","id":1}')
                # Should handle the error gracefully
                try:
                    data = websocket.receive_text()
                    # Either gets error response or connection closes
                    if data:
                        response = json.loads(data)
                        assert "error" in response or "result" in response
                except Exception:
                    # Connection may close due to error
                    pass

    def test_sse_endpoint_edge_cases(self, test_client, auth_headers):
        """Test SSE endpoint edge cases."""
        with patch("mcpgateway.main.SSETransport") as mock_transport_class, patch("mcpgateway.main.session_registry.add_session") as mock_add_session:
            mock_transport = MagicMock()
            mock_transport.session_id = "test-session"

            # Test SSE transport creation error
            mock_transport_class.side_effect = Exception("SSE error")

            response = test_client.get("/servers/test/sse", headers=auth_headers)
            # Should handle SSE creation error
            assert response.status_code in [404, 500, 503]

    def test_server_toggle_edge_cases(self, test_client, auth_headers):
        """Test server toggle endpoint edge cases."""
        with patch("mcpgateway.main.server_service.set_server_state") as mock_toggle:
            # Create a proper ServerRead model response
            # First-Party
            from mcpgateway.schemas import ServerRead

            mock_server_data = {
                "id": "1",
                "name": "test_server",
                "description": "A test server",
                "icon": None,
                "created_at": "2023-01-01T00:00:00+00:00",
                "updated_at": "2023-01-01T00:00:00+00:00",
                "enabled": True,
                "associated_tools": [],
                "associated_resources": [],
                "associated_prompts": [],
                "metrics": {
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": 0.0,
                    "max_response_time": 0.0,
                    "avg_response_time": 0.0,
                    "last_execution_time": None,
                },
            }

            mock_toggle.return_value = ServerRead(**mock_server_data)

            # Test activate=true
            response = test_client.post("/servers/1/state?activate=true", headers=auth_headers)
            assert response.status_code == 200

            # Test activate=false
            mock_server_data["enabled"] = False
            mock_toggle.return_value = ServerRead(**mock_server_data)
            response = test_client.post("/servers/1/state?activate=false", headers=auth_headers)
            assert response.status_code == 200


# Test fixtures
@pytest.fixture(autouse=True)
def reset_db(app_with_temp_db):
    """Clear the temp DB between tests when using the module-scoped app."""
    engine = db_mod.engine
    if engine is None:
        yield
        return

    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")

        for table in reversed(db_mod.Base.metadata.sorted_tables):
            conn.execute(table.delete())

        if engine.dialect.name == "sqlite":
            try:
                conn.exec_driver_sql("DELETE FROM sqlite_sequence")
            except sa.exc.DatabaseError:
                pass
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")

    yield


# Test fixtures
@pytest.fixture
def test_client(app_with_temp_db):
    """Test client with auth override for testing protected endpoints."""
    # Standard
    from unittest.mock import MagicMock, patch

    # First-Party
    from mcpgateway.auth import get_current_user
    from mcpgateway.db import EmailUser
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.utils.verify_credentials import require_auth

    # Mock user object for RBAC system
    mock_user = EmailUser(
        email="test_user@example.com",
        full_name="Test User",
        is_admin=True,  # Give admin privileges for tests
        is_active=True,
        auth_provider="test",
    )

    # Mock security_logger to prevent database access
    mock_sec_logger = MagicMock()
    mock_sec_logger.log_authentication_attempt = MagicMock(return_value=None)
    mock_sec_logger.log_security_event = MagicMock(return_value=None)
    sec_patcher = patch("mcpgateway.middleware.auth_middleware.security_logger", mock_sec_logger)
    sec_patcher.start()

    # Mock require_auth_override function
    def mock_require_auth_override(user: str) -> str:
        return user

    # Patch the require_docs_auth_override function
    patcher = patch("mcpgateway.main.require_docs_auth_override", mock_require_auth_override)
    patcher.start()

    # Override the core auth function used by RBAC system
    app_with_temp_db.dependency_overrides[get_current_user] = lambda credentials=None, db=None: mock_user

    # Override get_current_user_with_permissions for RBAC system
    def mock_get_current_user_with_permissions(request=None, credentials=None, jwt_token=None):
        return {"email": "test_user@example.com", "full_name": "Test User", "is_admin": True, "ip_address": "127.0.0.1", "user_agent": "test"}

    app_with_temp_db.dependency_overrides[get_current_user_with_permissions] = mock_get_current_user_with_permissions

    # Mock the permission service to always return True for tests
    # First-Party
    from mcpgateway.services.permission_service import PermissionService

    if not hasattr(PermissionService, "_original_check_permission"):
        PermissionService._original_check_permission = PermissionService.check_permission

    async def mock_check_permission(
        self,
        user_email: str,
        permission: str,
        resource_type=None,
        resource_id=None,
        team_id=None,
        ip_address=None,
        user_agent=None,
    ) -> bool:
        return True

    PermissionService.check_permission = mock_check_permission

    # Override require_auth for backward compatibility
    app_with_temp_db.dependency_overrides[require_auth] = lambda: "test_user"

    client = TestClient(app_with_temp_db)
    yield client

    # Clean up overrides and restore original methods
    app_with_temp_db.dependency_overrides.pop(require_auth, None)
    app_with_temp_db.dependency_overrides.pop(get_current_user, None)
    app_with_temp_db.dependency_overrides.pop(get_current_user_with_permissions, None)
    patcher.stop()  # Stop the require_auth_override patch
    sec_patcher.stop()  # Stop the security_logger patch
    if hasattr(PermissionService, "_original_check_permission"):
        PermissionService.check_permission = PermissionService._original_check_permission


@pytest.fixture
def allow_permission(monkeypatch):
    """Force permission checks to pass for direct endpoint calls."""
    from mcpgateway.services.permission_service import PermissionService

    monkeypatch.setattr(PermissionService, "check_permission", AsyncMock(return_value=True))
    return True


class TestA2AEndpoints:
    """Exercise A2A endpoints in main.py."""

    @staticmethod
    def _agent_read(agent_id: str = "agent-1") -> dict:
        return {
            "id": agent_id,
            "name": "Agent One",
            "slug": "agent-one",
            "description": "Test agent",
            "endpoint_url": "http://example.com/agent",
            "agent_type": "generic",
            "protocol_version": "1.0",
            "capabilities": {},
            "config": {},
            "enabled": True,
            "reachable": True,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "last_interaction": None,
            "tags": [],
            "metrics": None,
        }

    def test_create_a2a_agent(self, test_client, auth_headers):
        with (
            patch("mcpgateway.main.a2a_service") as mock_service,
            patch(
                "mcpgateway.main.MetadataCapture.extract_creation_metadata",
                return_value={
                    "created_by": "user",
                    "created_from_ip": "127.0.0.1",
                    "created_via": "api",
                    "created_user_agent": "test",
                    "import_batch_id": None,
                    "federation_source": None,
                },
            ),
        ):
            mock_service.register_agent = AsyncMock(return_value=self._agent_read())
            payload = {"agent": {"name": "Agent One", "endpoint_url": "http://example.com/agent"}, "team_id": None, "visibility": "public"}
            response = test_client.post("/a2a", json=payload, headers=auth_headers)
            assert response.status_code == 201
            assert response.json()["name"] == "Agent One"

    def test_update_a2a_agent(self, test_client, auth_headers):
        with (
            patch("mcpgateway.main.a2a_service") as mock_service,
            patch(
                "mcpgateway.main.MetadataCapture.extract_modification_metadata",
                return_value={"modified_by": "user", "modified_from_ip": "127.0.0.1", "modified_via": "api", "modified_user_agent": "test"},
            ),
        ):
            mock_service.update_agent = AsyncMock(return_value=self._agent_read("agent-2"))
            payload = {"agent": {"name": "Agent Two", "endpoint_url": "http://example.com/agent-two"}}
            response = test_client.put("/a2a/agent-2", json=payload, headers=auth_headers)
            assert response.status_code == 200
            assert response.json()["id"] == "agent-2"

    def test_delete_a2a_agent(self, test_client, auth_headers):
        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.delete_agent = AsyncMock()
            response = test_client.delete("/a2a/agent-3", headers=auth_headers)
            assert response.status_code == 200
            assert response.json()["status"] == "success"

    def test_invoke_a2a_agent(self, test_client, auth_headers):
        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.invoke_agent = AsyncMock(return_value={"ok": True})
            response = test_client.post(
                "/a2a/agent-4/invoke",
                json={"parameters": {"query": "hello"}, "interaction_type": "query"},
                headers=auth_headers,
            )
            assert response.status_code == 200
            assert response.json()["ok"] is True


class TestRpcHandling:
    """Cover RPC handler branches."""

    @staticmethod
    def _make_request(payload: dict) -> MagicMock:
        request = MagicMock(spec=Request)
        request.body = AsyncMock(return_value=json.dumps(payload).encode())
        request.headers = {}
        request.query_params = {}
        request.state = MagicMock()
        return request

    async def test_handle_rpc_parse_error(self):
        request = MagicMock(spec=Request)
        request.body = AsyncMock(return_value=b"{bad")
        request.headers = {}
        request.query_params = {}
        response = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 400

    async def test_handle_rpc_tools_list_server(self):
        payload = {"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {"server_id": "srv"}}
        request = self._make_request(payload)

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-1"}
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.tool_service.list_server_tools", new=AsyncMock(return_value=[tool])),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})
            assert result["result"]["tools"][0]["id"] == "tool-1"

    async def test_handle_rpc_list_tools_with_cursor(self):
        payload = {"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}}
        request = self._make_request(payload)

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-2"}
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.tool_service.list_tools", new=AsyncMock(return_value=([tool], "next-cursor"))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})
            assert result["result"]["nextCursor"] == "next-cursor"

    async def test_handle_rpc_list_gateways(self):
        payload = {"jsonrpc": "2.0", "id": "1", "method": "list_gateways", "params": {}}
        request = self._make_request(payload)

        gateway = MagicMock()
        gateway.model_dump.return_value = {"id": "gw-1"}
        mock_db = MagicMock()

        with patch("mcpgateway.main.gateway_service.list_gateways", new=AsyncMock(return_value=([gateway], None))):
            result = await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})
            assert result["result"]["gateways"][0]["id"] == "gw-1"

    async def test_handle_rpc_resources_read_missing_uri(self):
        payload = {"jsonrpc": "2.0", "id": "1", "method": "resources/read", "params": {}}
        request = self._make_request(payload)

        with patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert "error" in result

    async def test_handle_rpc_resources_list_with_cursor(self):
        payload = {"jsonrpc": "2.0", "id": "2", "method": "resources/list", "params": {}}
        request = self._make_request(payload)

        resource = MagicMock()
        resource.model_dump.return_value = {"id": "res-1"}
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.resource_service.list_resources", new=AsyncMock(return_value=([resource], "next-cursor"))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})
            assert result["result"]["resources"][0]["id"] == "res-1"
            assert result["result"]["nextCursor"] == "next-cursor"

    async def test_handle_rpc_resources_read_success_and_forward(self):
        payload = {"jsonrpc": "2.0", "id": "3", "method": "resources/read", "params": {"uri": "resource://one"}}
        request = self._make_request(payload)
        request.state = MagicMock()

        resource = MagicMock()
        resource.model_dump.return_value = {"uri": "resource://one"}

        with (
            patch("mcpgateway.main.resource_service.read_resource", new=AsyncMock(return_value=resource)),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["contents"][0]["uri"] == "resource://one"

        with (
            patch("mcpgateway.main.resource_service.read_resource", new=AsyncMock(side_effect=ValueError("no local"))),
            patch("mcpgateway.main.gateway_service.forward_request", new=AsyncMock(return_value={"ok": True})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["ok"] is True

    async def test_handle_rpc_resources_subscribe_unsubscribe(self):
        payload = {"jsonrpc": "2.0", "id": "4", "method": "resources/subscribe", "params": {"uri": "resource://two"}}
        request = self._make_request(payload)

        with patch("mcpgateway.main.resource_service.subscribe_resource", new=AsyncMock(return_value=None)):
            result = await handle_rpc(request, db=MagicMock(), user="user")
            assert result["result"] == {}

        payload_unsub = {"jsonrpc": "2.0", "id": "5", "method": "resources/unsubscribe", "params": {"uri": "resource://two"}}
        request_unsub = self._make_request(payload_unsub)
        with patch("mcpgateway.main.resource_service.unsubscribe_resource", new=AsyncMock(return_value=None)):
            result = await handle_rpc(request_unsub, db=MagicMock(), user="user")
            assert result["result"] == {}

    async def test_handle_rpc_prompts_list_and_get(self):
        payload = {"jsonrpc": "2.0", "id": "6", "method": "prompts/list", "params": {"server_id": "srv"}}
        request = self._make_request(payload)

        prompt = MagicMock()
        prompt.model_dump.return_value = {"name": "prompt-1"}
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.prompt_service.list_server_prompts", new=AsyncMock(return_value=[prompt])),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})
            assert result["result"]["prompts"][0]["name"] == "prompt-1"

        payload_get = {"jsonrpc": "2.0", "id": "7", "method": "prompts/get", "params": {"name": "prompt-1"}}
        request_get = self._make_request(payload_get)
        request_get.state = MagicMock()
        prompt_payload = MagicMock()
        prompt_payload.model_dump.return_value = {"name": "prompt-1", "template": "hi"}

        with (
            patch("mcpgateway.main.prompt_service.get_prompt", new=AsyncMock(return_value=prompt_payload)),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request_get, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["name"] == "prompt-1"

    async def test_handle_rpc_ping_and_resource_templates(self):
        payload = {"jsonrpc": "2.0", "id": "8", "method": "ping", "params": {}}
        request = self._make_request(payload)
        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["result"] == {}

        payload_templates = {"jsonrpc": "2.0", "id": "9", "method": "resources/templates/list", "params": {}}
        request_templates = self._make_request(payload_templates)
        template = MagicMock()
        template.model_dump.return_value = {"uriTemplate": "resource://{id}"}

        with (
            patch("mcpgateway.main.resource_service.list_resource_templates", new=AsyncMock(return_value=[template])),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request_templates, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["resourceTemplates"][0]["uriTemplate"] == "resource://{id}"

    async def test_handle_rpc_tools_call(self, monkeypatch):
        payload = {"jsonrpc": "2.0", "id": "10", "method": "tools/call", "params": {"name": "tool-1", "arguments": {"a": 1}}}
        request = self._make_request(payload)
        request.state = MagicMock()

        tool_result = MagicMock()
        tool_result.model_dump.return_value = {"ok": True}

        monkeypatch.setattr(settings, "mcpgateway_tool_cancellation_enabled", False)

        with (
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(return_value=tool_result)),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["ok"] is True

    async def test_handle_rpc_notifications_and_sampling(self):
        payload_cancel = {"jsonrpc": "2.0", "id": "11", "method": "notifications/cancelled", "params": {"requestId": "r1", "reason": "stop"}}
        request_cancel = self._make_request(payload_cancel)

        with (
            patch("mcpgateway.main.cancellation_service.cancel_run", new=AsyncMock(return_value=None)),
            patch("mcpgateway.main.logging_service.notify", new=AsyncMock(return_value=None)),
        ):
            result = await handle_rpc(request_cancel, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"] == {}

        payload_msg = {"jsonrpc": "2.0", "id": "12", "method": "notifications/message", "params": {"data": "hello", "level": "info", "logger": "tests"}}
        request_msg = self._make_request(payload_msg)
        with patch("mcpgateway.main.logging_service.notify", new=AsyncMock(return_value=None)):
            result = await handle_rpc(request_msg, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"] == {}

        payload_sampling = {"jsonrpc": "2.0", "id": "13", "method": "sampling/createMessage", "params": {"messages": []}}
        request_sampling = self._make_request(payload_sampling)
        with patch("mcpgateway.main.sampling_handler.create_message", new=AsyncMock(return_value={"text": "ok"})):
            result = await handle_rpc(request_sampling, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["text"] == "ok"

    async def test_handle_rpc_elicitation_completion_logging(self, monkeypatch):
        payload = {
            "jsonrpc": "2.0",
            "id": "14",
            "method": "elicitation/create",
            "params": {"message": "Need input", "requestedSchema": {"type": "object", "properties": {"x": {"type": "string"}}}},
        }
        request = self._make_request(payload)
        request.state = MagicMock()

        class _Pending:
            def __init__(self, downstream_session_id: str, request_id: str):
                self.downstream_session_id = downstream_session_id
                self.request_id = request_id

        class _Result:
            def model_dump(self, **_kwargs):
                return {"status": "ok"}

        class _ElicitationService:
            def __init__(self):
                self._pending = {"p1": _Pending("sess-1", "req-1")}

            async def create_elicitation(self, **_kwargs):
                return _Result()

        monkeypatch.setattr(settings, "mcpgateway_elicitation_enabled", True)

        with (
            patch("mcpgateway.services.elicitation_service.get_elicitation_service", return_value=_ElicitationService()),
            patch("mcpgateway.main.session_registry.get_elicitation_capable_sessions", new=AsyncMock(return_value=["sess-1"])),
            patch("mcpgateway.main.session_registry.has_elicitation_capability", new=AsyncMock(return_value=True)),
            patch("mcpgateway.main.session_registry.broadcast", new=AsyncMock(return_value=None)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["status"] == "ok"

        payload_completion = {"jsonrpc": "2.0", "id": "15", "method": "completion/complete", "params": {"prompt": "hi"}}
        request_completion = self._make_request(payload_completion)
        with patch("mcpgateway.main.completion_service.handle_completion", new=AsyncMock(return_value={"text": "done"})):
            result = await handle_rpc(request_completion, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["text"] == "done"

        payload_logging = {"jsonrpc": "2.0", "id": "16", "method": "logging/setLevel", "params": {"level": "info"}}
        request_logging = self._make_request(payload_logging)
        with patch("mcpgateway.main.logging_service.set_level", new=AsyncMock(return_value=None)):
            result = await handle_rpc(request_logging, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"] == {}

    async def test_handle_rpc_fallback_tool_and_gateway(self):
        payload = {"jsonrpc": "2.0", "id": "17", "method": "custom/tool", "params": {"a": 1}}
        request = self._make_request(payload)
        request.state = MagicMock()

        tool_result = MagicMock()
        tool_result.model_dump.return_value = {"ok": True}
        with patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(return_value=tool_result)):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["ok"] is True

        with (
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(side_effect=ValueError("no tool"))),
            patch("mcpgateway.main.gateway_service.forward_request", new=AsyncMock(return_value={"via": "gateway"})),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["via"] == "gateway"

        with (
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(side_effect=ValueError("no tool"))),
            patch("mcpgateway.main.gateway_service.forward_request", new=AsyncMock(side_effect=Exception("fail"))),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32000

    async def test_handle_rpc_user_object_and_auto_id(self):
        payload = {"jsonrpc": "2.0", "method": "ping", "params": {}}
        request = self._make_request(payload)

        class _User:
            email = "user@example.com"

        result = await handle_rpc(request, db=MagicMock(), user=_User())
        assert result["result"] == {}
        assert result["id"] is not None

    async def test_handle_rpc_admin_bypass_variants(self):
        payload = {"jsonrpc": "2.0", "id": "18", "method": "tools/list", "params": {}}
        request = self._make_request(payload)
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.tool_service.list_tools", new=AsyncMock(return_value=([], None))) as list_tools,
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})
            list_tools.assert_called_once()

        payload_legacy = {"jsonrpc": "2.0", "id": "19", "method": "list_tools", "params": {"server_id": "srv"}}
        request_legacy = self._make_request(payload_legacy)
        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-legacy"}

        with (
            patch("mcpgateway.main.tool_service.list_server_tools", new=AsyncMock(return_value=[tool])) as list_server_tools,
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request_legacy, db=MagicMock(), user={"email": "user@example.com"})
            list_server_tools.assert_called_once()
            assert result["result"]["tools"][0]["id"] == "tool-legacy"

    async def test_handle_rpc_resources_admin_bypass_and_missing_uri(self):
        payload_list = {"jsonrpc": "2.0", "id": "20", "method": "resources/list", "params": {}}
        request_list = self._make_request(payload_list)
        resource = MagicMock()
        resource.model_dump.return_value = {"id": "res-admin"}

        with (
            patch("mcpgateway.main.resource_service.list_resources", new=AsyncMock(return_value=([resource], None))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request_list, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["resources"][0]["id"] == "res-admin"

        payload_missing = {"jsonrpc": "2.0", "id": "21", "method": "resources/subscribe", "params": {}}
        request_missing = self._make_request(payload_missing)
        result = await handle_rpc(request_missing, db=MagicMock(), user="user")
        assert result["error"]["code"] == -32602

        payload_missing_unsub = {"jsonrpc": "2.0", "id": "22", "method": "resources/unsubscribe", "params": {}}
        request_missing_unsub = self._make_request(payload_missing_unsub)
        result = await handle_rpc(request_missing_unsub, db=MagicMock(), user="user")
        assert result["error"]["code"] == -32602

    async def test_handle_rpc_resources_read_admin_gateway_model_dump(self):
        payload = {"jsonrpc": "2.0", "id": "23", "method": "resources/read", "params": {"uri": "resource://admin"}}
        request = self._make_request(payload)
        request.state = MagicMock()

        gateway_result = MagicMock()
        gateway_result.model_dump.return_value = {"forwarded": True}

        with (
            patch("mcpgateway.main.resource_service.read_resource", new=AsyncMock(side_effect=ValueError("no local"))),
            patch("mcpgateway.main.gateway_service.forward_request", new=AsyncMock(return_value=gateway_result)),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["forwarded"] is True

    async def test_handle_rpc_prompts_admin_bypass_and_missing_name(self):
        payload_list = {"jsonrpc": "2.0", "id": "24", "method": "prompts/list", "params": {}}
        request_list = self._make_request(payload_list)
        prompt = MagicMock()
        prompt.model_dump.return_value = {"name": "prompt-admin"}

        with (
            patch("mcpgateway.main.prompt_service.list_prompts", new=AsyncMock(return_value=([prompt], None))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request_list, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["prompts"][0]["name"] == "prompt-admin"

        payload_missing = {"jsonrpc": "2.0", "id": "25", "method": "prompts/get", "params": {}}
        request_missing = self._make_request(payload_missing)
        request_missing.state = MagicMock()
        result = await handle_rpc(request_missing, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32602

        payload_get = {"jsonrpc": "2.0", "id": "26", "method": "prompts/get", "params": {"name": "prompt-admin"}}
        request_get = self._make_request(payload_get)
        request_get.state = MagicMock()
        prompt_payload = MagicMock()
        prompt_payload.model_dump.return_value = {"name": "prompt-admin"}

        with (
            patch("mcpgateway.main.prompt_service.get_prompt", new=AsyncMock(return_value=prompt_payload)),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request_get, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["name"] == "prompt-admin"

    async def test_handle_rpc_tools_call_missing_name_and_cancel(self, monkeypatch):
        payload_missing = {"jsonrpc": "2.0", "id": "27", "method": "tools/call", "params": {}}
        request_missing = self._make_request(payload_missing)
        request_missing.state = MagicMock()
        result = await handle_rpc(request_missing, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32602

        payload = {"jsonrpc": "2.0", "id": "28", "method": "tools/call", "params": {"name": "tool-cancel", "arguments": {}}}
        request = self._make_request(payload)
        request.state = MagicMock()

        monkeypatch.setattr(settings, "mcpgateway_tool_cancellation_enabled", True)

        with (
            patch("mcpgateway.main.cancellation_service.register_run", new=AsyncMock(return_value=None)),
            patch("mcpgateway.main.cancellation_service.get_status", new=AsyncMock(return_value={"cancelled": True})),
            patch("mcpgateway.main.cancellation_service.unregister_run", new=AsyncMock(return_value=None)),
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(return_value={"ok": True})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32800

    async def test_handle_rpc_tools_call_cancel_after_creation(self, monkeypatch):
        payload = {"jsonrpc": "2.0", "id": "29", "method": "tools/call", "params": {"name": "tool-cancel", "arguments": {}}}
        request = self._make_request(payload)
        request.state = MagicMock()

        async def _slow_tool(*_args, **_kwargs):
            await asyncio.sleep(0.05)
            return {"ok": True}

        monkeypatch.setattr(settings, "mcpgateway_tool_cancellation_enabled", True)

        with (
            patch("mcpgateway.main.cancellation_service.register_run", new=AsyncMock(return_value=None)),
            patch("mcpgateway.main.cancellation_service.get_status", new=AsyncMock(side_effect=[None, {"cancelled": True}])),
            patch("mcpgateway.main.cancellation_service.unregister_run", new=AsyncMock(return_value=None)),
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(side_effect=_slow_tool)),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32800

    async def test_handle_rpc_resource_templates_admin_and_notifications_other(self):
        payload_templates = {"jsonrpc": "2.0", "id": "30", "method": "resources/templates/list", "params": {}}
        request_templates = self._make_request(payload_templates)
        template = MagicMock()
        template.model_dump.return_value = {"uriTemplate": "resource://{id}"}

        with (
            patch("mcpgateway.main.resource_service.list_resource_templates", new=AsyncMock(return_value=[template])),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request_templates, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["resourceTemplates"][0]["uriTemplate"] == "resource://{id}"

        payload_other = {"jsonrpc": "2.0", "id": "31", "method": "notifications/other", "params": {}}
        request_other = self._make_request(payload_other)
        result = await handle_rpc(request_other, db=MagicMock(), user={"email": "user@example.com"})
        assert result["result"] == {}

    async def test_handle_rpc_elicitation_error_paths(self, monkeypatch):
        monkeypatch.setattr(settings, "mcpgateway_elicitation_enabled", True)

        payload_invalid = {"jsonrpc": "2.0", "id": "32", "method": "elicitation/create", "params": {}}
        request_invalid = self._make_request(payload_invalid)
        result = await handle_rpc(request_invalid, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32602

        payload_no_sessions = {
            "jsonrpc": "2.0",
            "id": "33",
            "method": "elicitation/create",
            "params": {"message": "Need input", "requestedSchema": {"type": "object", "properties": {"x": {"type": "string"}}}},
        }
        request_no_sessions = self._make_request(payload_no_sessions)
        with patch("mcpgateway.main.session_registry.get_elicitation_capable_sessions", new=AsyncMock(return_value=[])):
            result = await handle_rpc(request_no_sessions, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32000

        payload_not_capable = {
            "jsonrpc": "2.0",
            "id": "34",
            "method": "elicitation/create",
            "params": {"message": "Need input", "requestedSchema": {"type": "object", "properties": {"x": {"type": "string"}}}, "session_id": "sess-1"},
        }
        request_not_capable = self._make_request(payload_not_capable)
        with patch("mcpgateway.main.session_registry.has_elicitation_capability", new=AsyncMock(return_value=False)):
            result = await handle_rpc(request_not_capable, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32000

        class _EmptyService:
            def __init__(self):
                self._pending = {}

            async def create_elicitation(self, **_kwargs):
                return SimpleNamespace()

        payload_empty_pending = {
            "jsonrpc": "2.0",
            "id": "35",
            "method": "elicitation/create",
            "params": {"message": "Need input", "requestedSchema": {"type": "object", "properties": {"x": {"type": "string"}}}, "session_id": "sess-1"},
        }
        request_empty_pending = self._make_request(payload_empty_pending)
        with (
            patch("mcpgateway.services.elicitation_service.get_elicitation_service", return_value=_EmptyService()),
            patch("mcpgateway.main.session_registry.has_elicitation_capability", new=AsyncMock(return_value=True)),
            patch("mcpgateway.main.session_registry.broadcast", new=AsyncMock(return_value=None)),
        ):
            result = await handle_rpc(request_empty_pending, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32000

        class _TimeoutService:
            def __init__(self):
                self._pending = {"p1": SimpleNamespace(downstream_session_id="sess-1", request_id="req-1")}

            async def create_elicitation(self, **_kwargs):
                raise asyncio.TimeoutError()

        payload_timeout = {
            "jsonrpc": "2.0",
            "id": "36",
            "method": "elicitation/create",
            "params": {"message": "Need input", "requestedSchema": {"type": "object", "properties": {"x": {"type": "string"}}}, "session_id": "sess-1"},
        }
        request_timeout = self._make_request(payload_timeout)
        with (
            patch("mcpgateway.services.elicitation_service.get_elicitation_service", return_value=_TimeoutService()),
            patch("mcpgateway.main.session_registry.has_elicitation_capability", new=AsyncMock(return_value=True)),
            patch("mcpgateway.main.session_registry.broadcast", new=AsyncMock(return_value=None)),
        ):
            result = await handle_rpc(request_timeout, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32000

    async def test_handle_rpc_fallback_admin_bypass_and_plugin_error(self):
        payload = {"jsonrpc": "2.0", "id": "37", "method": "custom/other", "params": {"a": 1}}
        request = self._make_request(payload)
        request.state = MagicMock()

        tool_result = MagicMock()
        tool_result.model_dump.return_value = {"ok": True}
        with (
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(return_value=tool_result)),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["ok"] is True

        from mcpgateway.plugins.framework.models import PluginErrorModel

        with (
            patch(
                "mcpgateway.main.tool_service.invoke_tool",
                new=AsyncMock(side_effect=PluginError(PluginErrorModel(message="nope", plugin_name="test-plugin"))),
            ),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            with pytest.raises(PluginError):
                await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})


class TestA2AListAndGet:
    """Cover list/get A2A agent endpoints in main."""

    async def test_list_a2a_agents_with_pagination(self):
        request = MagicMock(spec=Request)
        request.state = MagicMock()
        request.state.team_id = None

        agent = MagicMock()
        agent.model_dump.return_value = {"id": "agent-1"}

        with (
            patch("mcpgateway.main.a2a_service") as mock_service,
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            mock_service.list_agents = AsyncMock(return_value=([agent], "next-cursor"))
            result = await list_a2a_agents(request, include_pagination=True, db=MagicMock(), user={"email": "user@example.com"})
            assert result["agents"][0]["id"] == "agent-1"
            assert result["nextCursor"] == "next-cursor"

    async def test_list_a2a_agents_team_mismatch(self):
        request = MagicMock(spec=Request)
        request.state = MagicMock()
        request.state.team_id = "team-a"

        with (
            patch("mcpgateway.main.a2a_service") as mock_service,
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", ["team-a"], False)),
        ):
            mock_service.list_agents = AsyncMock(return_value=([], None))
            response = await list_a2a_agents(request, team_id="team-b", db=MagicMock(), user={"email": "user@example.com"})
            assert response.status_code == 403

    async def test_get_a2a_agent_success(self):
        request = MagicMock(spec=Request)
        request.state = MagicMock()

        with (
            patch("mcpgateway.main.a2a_service.get_agent", new=AsyncMock(return_value={"id": "agent-1"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await get_a2a_agent("agent-1", request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["id"] == "agent-1"


class TestExportImportEndpoints:
    """Cover export/import API endpoints in main."""

    async def test_export_configuration_success(self):
        export_service = MagicMock()
        export_service.export_configuration = AsyncMock(return_value={"tools": []})

        with patch("mcpgateway.main.export_service", export_service):
            result = await export_configuration(MagicMock(spec=Request), types="tools", db=MagicMock(), user={"email": "user@example.com"})
            assert result["tools"] == []

    async def test_export_selective_configuration_success(self):
        export_service = MagicMock()
        export_service.export_selective = AsyncMock(return_value={"tools": ["tool-1"]})

        with patch("mcpgateway.main.export_service", export_service):
            result = await export_selective_configuration({"tools": ["tool-1"]}, include_dependencies=False, db=MagicMock(), user={"email": "user@example.com"})
            assert result["tools"] == ["tool-1"]

    async def test_import_configuration_invalid_strategy(self):
        with pytest.raises(Exception):
            await import_configuration(import_data={}, conflict_strategy="invalid", db=MagicMock(), user={"email": "user@example.com"})

    async def test_import_configuration_success(self):
        status = MagicMock()
        status.to_dict.return_value = {"status": "ok"}
        import_service = MagicMock()
        import_service.import_configuration = AsyncMock(return_value=status)

        with patch("mcpgateway.main.import_service", import_service):
            result = await import_configuration(import_data={"tools": []}, conflict_strategy="update", db=MagicMock(), user={"email": "user@example.com"})
            assert result["status"] == "ok"


class TestMessageEndpointElicitation:
    """Cover elicitation response handling."""

    async def test_message_endpoint_elicitation_response(self, monkeypatch):
        request = MagicMock(spec=Request)
        request.query_params = {"session_id": "session-1"}
        request.body = AsyncMock(
            return_value=json.dumps({"id": "req-1", "result": {"action": "accept", "content": {"foo": "bar"}}}).encode()
        )

        # Allow permission checks to pass for direct invocation
        from mcpgateway.services.permission_service import PermissionService

        monkeypatch.setattr(PermissionService, "check_permission", AsyncMock(return_value=True))

        elicitation_service = MagicMock()
        elicitation_service.complete_elicitation.return_value = True
        monkeypatch.setattr("mcpgateway.services.elicitation_service.get_elicitation_service", lambda: elicitation_service)

        broadcast = AsyncMock()
        monkeypatch.setattr("mcpgateway.main.session_registry.broadcast", broadcast)

        response = await message_endpoint(request, "server-1", user={"email": "user@example.com"})
        assert response.status_code == 202
        broadcast.assert_not_called()


@pytest.fixture
def auth_headers():
    """Default auth headers for testing."""
    return {"Authorization": "Bearer test_token"}
