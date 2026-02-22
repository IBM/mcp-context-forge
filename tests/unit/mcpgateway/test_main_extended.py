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
import builtins
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

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


def _import_fresh_main_module(
    monkeypatch: pytest.MonkeyPatch,
    *,
    overrides: dict[str, object] | None = None,
    env: dict[str, str] | None = None,
    force_import_error: set[str] | None = None,
):
    """Import mcpgateway/main.py under a unique module name for module-level branch coverage."""

    # First-Party
    from mcpgateway.config import settings as settings_mod

    if overrides:
        for key, value in overrides.items():
            monkeypatch.setattr(settings_mod, key, value, raising=False)

    if env:
        for key, value in env.items():
            monkeypatch.setenv(key, value)

    # Use in-memory session registry to avoid dependence on SQLALCHEMY_AVAILABLE
    # module-level state which can be polluted by other tests that reload session_registry.
    monkeypatch.setattr(settings_mod, "cache_type", "memory", raising=False)

    # Avoid import-time side effects (DB/Redis readiness + bootstrap).
    monkeypatch.setattr("mcpgateway.utils.db_isready.wait_for_db_ready", lambda *_a, **_k: None)

    async def _noop_async(*_a, **_k):  # noqa: ANN001, D401 - internal test helper
        return None

    monkeypatch.setattr("mcpgateway.bootstrap_db.main", _noop_async)
    monkeypatch.setattr("mcpgateway.utils.redis_isready.wait_for_redis_ready", lambda *_a, **_k: None)

    # Keep module-level router/middleware wiring lightweight.
    monkeypatch.setattr("mcpgateway.middleware.db_query_logging.setup_query_logging", lambda *_a, **_k: None, raising=False)
    monkeypatch.setattr("mcpgateway.services.metrics.setup_metrics", lambda *_a, **_k: None, raising=False)

    class _PluginService:
        def set_plugin_manager(self, _pm):  # noqa: ANN001
            return None

    monkeypatch.setattr("mcpgateway.services.plugin_service.get_plugin_service", lambda: _PluginService(), raising=False)

    class _DummyPluginManager:
        def __init__(self, *_a, **_k):  # noqa: ANN001
            self.plugin_count = 0

        async def initialize(self):  # noqa: D401 - trivial
            return None

        async def shutdown(self):  # noqa: D401 - trivial
            return None

    monkeypatch.setattr("mcpgateway.plugins.framework.PluginManager", _DummyPluginManager)

    # Force selected module imports to fail to cover defensive ImportError paths.
    if force_import_error:
        original_import = builtins.__import__

        def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
            if name in force_import_error:
                raise ImportError(f"Forced ImportError for {name}")
            return original_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", _guarded_import)

    module_name = f"mcpgateway._main_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, Path("mcpgateway/main.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Make module importable during exec_module and ensure it is cleaned up after the test.
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


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

    @pytest.mark.asyncio
    async def test_startup_without_plugin_manager(self, monkeypatch):
        """Test startup path when plugin_manager is None."""
        # NOTE: This test previously used a single giant parenthesized `with (...)` statement
        # with many context managers. On Python 3.12.3 that reliably triggered a compiler
        # segfault when compiling this file. Keep patches explicit via ExitStack instead.
        from contextlib import ExitStack

        import mcpgateway.main as main_mod

        mock_logging_service = MagicMock()
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

        monkeypatch.setattr(settings, "require_strong_secrets", False, raising=False)
        monkeypatch.setattr(settings, "dev_mode", True, raising=False)
        monkeypatch.setattr(main_mod, "plugin_manager", None, raising=False)

        with ExitStack() as stack:
            stack.enter_context(patch("mcpgateway.main.logging_service", mock_logging_service))
            mock_tool = stack.enter_context(patch("mcpgateway.main.tool_service"))
            mock_resource = stack.enter_context(patch("mcpgateway.main.resource_service"))
            mock_prompt = stack.enter_context(patch("mcpgateway.main.prompt_service"))
            mock_gateway = stack.enter_context(patch("mcpgateway.main.gateway_service"))
            mock_root = stack.enter_context(patch("mcpgateway.main.root_service"))
            mock_completion = stack.enter_context(patch("mcpgateway.main.completion_service"))
            mock_sampling = stack.enter_context(patch("mcpgateway.main.sampling_handler"))
            mock_cache = stack.enter_context(patch("mcpgateway.main.resource_cache"))
            mock_session = stack.enter_context(patch("mcpgateway.main.streamable_http_session"))
            mock_session_registry = stack.enter_context(patch("mcpgateway.main.session_registry"))
            mock_export = stack.enter_context(patch("mcpgateway.main.export_service"))
            mock_import = stack.enter_context(patch("mcpgateway.main.import_service"))
            mock_a2a = stack.enter_context(patch("mcpgateway.main.a2a_service"))
            stack.enter_context(patch("mcpgateway.main.refresh_slugs_on_startup"))
            mock_get_redis = stack.enter_context(patch("mcpgateway.main.get_redis_client", new_callable=AsyncMock))
            mock_close_redis = stack.enter_context(patch("mcpgateway.main.close_redis_client", new_callable=AsyncMock))
            mock_init_llmchat = stack.enter_context(patch("mcpgateway.routers.llmchat_router.init_redis", new_callable=AsyncMock))
            mock_shared_http = stack.enter_context(patch("mcpgateway.services.http_client_service.SharedHttpClient.get_instance", new_callable=AsyncMock))
            mock_shared_http_shutdown = stack.enter_context(patch("mcpgateway.services.http_client_service.SharedHttpClient.shutdown", new_callable=AsyncMock))

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

    @pytest.mark.asyncio
    async def test_docs_auth_normalizes_prefixed_scope_path(self):
        """When proxy forwards full path, scope_path includes root_path prefix and must be stripped."""
        middleware = DocsAuthMiddleware(None)
        request = _make_request("/qa/gateway/docs", root_path="/qa/gateway")
        call_next = AsyncMock(return_value=StarletteResponse("ok"))

        with patch("mcpgateway.main.require_docs_auth_override", side_effect=HTTPException(status_code=401, detail="nope")):
            response = await middleware.dispatch(request, call_next)

        # After normalization the path matches /docs, so auth is enforced
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_docs_auth_prefixed_unprotected_path_passes_through(self):
        """An unprotected path with root_path prefix must still pass through after normalization."""
        middleware = DocsAuthMiddleware(None)
        request = _make_request("/qa/gateway/health", root_path="/qa/gateway")
        call_next = AsyncMock(return_value="ok")

        response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_docs_auth_root_path_slash_does_not_break_paths(self):
        """root_path of '/' must be ignored to avoid stripping leading slash from every path."""
        middleware = DocsAuthMiddleware(None)
        request = _make_request("/docs", root_path="/")
        call_next = AsyncMock(return_value=StarletteResponse("ok"))

        with patch("mcpgateway.main.require_docs_auth_override", side_effect=HTTPException(status_code=401, detail="nope")):
            response = await middleware.dispatch(request, call_next)

        # /docs is still recognized as protected (leading slash not stripped)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_docs_auth_partial_prefix_not_stripped(self):
        """root_path='/app' must not strip from '/application/docs' (partial segment match)."""
        middleware = DocsAuthMiddleware(None)
        request = _make_request("/application/docs", root_path="/app")
        call_next = AsyncMock(return_value="ok")

        response = await middleware.dispatch(request, call_next)

        # "/application/docs" is not a protected path, so it passes through
        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_docs_auth_trailing_slash_root_path(self):
        """root_path with trailing slash must still strip prefix correctly."""
        middleware = DocsAuthMiddleware(None)
        request = _make_request("/qa/gateway/docs", root_path="/qa/gateway/")
        call_next = AsyncMock(return_value=StarletteResponse("ok"))

        with patch("mcpgateway.main.require_docs_auth_override", side_effect=HTTPException(status_code=401, detail="nope")):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401


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
    async def test_admin_auth_htmx_request_returns_hx_redirect(self, monkeypatch):
        """HTMX partial requests must receive HX-Redirect header instead of 302 redirect (issue #2874)."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request(
            "/admin/tools",
            headers={"Authorization": "Bearer token", "accept": "text/html", "hx-request": "true"},
        )
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        with (
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com", "jti": "abc"})),
            patch("mcpgateway.main._check_token_revoked_sync", return_value=True),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        assert "/admin/login" in response.headers.get("hx-redirect", "")
        assert "token_revoked" in response.headers.get("hx-redirect", "")

    @pytest.mark.asyncio
    async def test_admin_auth_htmx_no_auth_returns_hx_redirect(self, monkeypatch):
        """HTMX requests without valid auth must get HX-Redirect, not 302 (issue #2874)."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request(
            "/admin/tools",
            headers={"hx-request": "true"},
        )
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        with patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={})):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        assert "/admin/login" in response.headers.get("hx-redirect", "")

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

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/admin/login",
            "/admin/logout",
            "/admin/forgot-password",
            "/admin/reset-password/token-123",
            "/admin/static/app.css",
        ],
    )
    async def test_admin_auth_exempt_paths_call_next_when_auth_required(self, monkeypatch, path):
        """Cover exempt path short-circuit for public admin routes and static assets."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request(path, headers={"accept": "application/json"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        response = await middleware.dispatch(request, call_next)
        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/qa/gateway/admin/login",
            "/qa/gateway/admin/forgot-password",
            "/qa/gateway/admin/reset-password/token-123",
        ],
    )
    async def test_admin_auth_exempt_path_with_prefixed_scope_path(self, monkeypatch, path):
        """When proxy forwards full paths, exempt admin auth routes must remain public."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request(path, root_path="/qa/gateway")
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        response = await middleware.dispatch(request, call_next)
        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_auth_root_path_slash_does_not_break_paths(self, monkeypatch):
        """root_path of '/' must be ignored so /admin routes are still detected."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/login", root_path="/")
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        response = await middleware.dispatch(request, call_next)
        # /admin/login is exempt; leading slash must not be stripped
        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_auth_prefixed_non_exempt_path_enforces_auth(self, monkeypatch):
        """A non-exempt prefixed admin path must be detected as admin and require auth."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/qa/gateway/admin/tools", root_path="/qa/gateway", headers={"accept": "text/html"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        response = await middleware.dispatch(request, call_next)
        # No credentials: should redirect to login (302), not pass through
        assert response.status_code == 302
        assert "/admin/login" in response.headers.get("location", "")
        call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_admin_auth_trailing_slash_root_path(self, monkeypatch):
        """root_path with trailing slash must still normalize correctly."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/qa/gateway/admin/tools", root_path="/qa/gateway/", headers={"accept": "text/html"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 302
        assert "/admin/login" in response.headers.get("location", "")
        call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_admin_auth_cookie_token_revocation_check_failure_still_allows(self, monkeypatch):
        """Cover cookie token extraction + revocation check failure path."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", cookies={"jwt_token": "token"}, headers={"accept": "application/json"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=True)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(return_value=True)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com", "jti": "jti-1"})),
            patch("mcpgateway.main._check_token_revoked_sync", side_effect=RuntimeError("revocation backend down")),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_auth_api_token_revoked_and_success(self, monkeypatch):
        """Cover API token revoked and valid branches (when JWT validation fails)."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", cookies={"jwt_token": "token"}, headers={"accept": "application/json"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        with (
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(side_effect=Exception("bad"))),
            patch("mcpgateway.main._lookup_api_token_sync", return_value={"revoked": True}),
        ):
            response = await middleware.dispatch(request, call_next)
            assert response.status_code == 401

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=True)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(return_value=True)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(side_effect=Exception("bad"))),
            patch("mcpgateway.main._lookup_api_token_sync", return_value={"user_email": "admin@example.com"}),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)
            assert response == "ok"

    @pytest.mark.asyncio
    async def test_admin_auth_user_not_found_returns_401(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", cookies={"jwt_token": "token"}, headers={"accept": "application/json"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        monkeypatch.setattr(settings, "require_user_in_db", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=None)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com"})),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_auth_user_not_found_browser_redirects_to_login(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", cookies={"jwt_token": "token"}, headers={"accept": "text/html"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        monkeypatch.setattr(settings, "require_user_in_db", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=None)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com"})),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 302
        assert "/admin/login" in response.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_admin_auth_disabled_user_returns_403(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", cookies={"jwt_token": "token"}, headers={"accept": "application/json"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=False, is_admin=True)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com"})),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_auth_http_exception_and_general_exception_paths(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", cookies={"jwt_token": "token"}, headers={"accept": "application/json"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(side_effect=HTTPException(status_code=401, detail="boom"))

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com"})),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
        ):
            response = await middleware.dispatch(request, call_next)
            assert response.status_code == 401

        # Generic exception (e.g., permission check failure) -> 500 Authentication error
        mock_user = SimpleNamespace(is_active=True, is_admin=True)
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(side_effect=RuntimeError("perm backend down"))

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com"})),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)
            assert response.status_code == 500


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

    @pytest.mark.asyncio
    async def test_list_resources_tags_and_public_only_default(self, monkeypatch, allow_permission):
        """Cover tags parsing + token_teams None -> [] public-only default."""
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        monkeypatch.setattr("mcpgateway.main._get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, False))
        monkeypatch.setattr(
            "mcpgateway.main.resource_service.list_resources",
            AsyncMock(return_value=([], None)),
        )

        result = await list_resources(
            request,
            tags="a, b",
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert result["resources"] == []


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

    @pytest.mark.asyncio
    async def test_create_tool_public_only_token_blocks_team_private_visibility(self, monkeypatch, allow_permission):
        request = _make_request("/tools")
        request.state = SimpleNamespace(team_id=None, token_teams=[])

        tool_input = ToolCreate(name="tool-a", url="http://example.com", visibility="team")
        response = await create_tool(tool_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_tool_public_only_token_forces_team_id_none(self, monkeypatch, allow_permission):
        request = _make_request("/tools")
        request.state = SimpleNamespace(team_id="team-1", token_teams=[])

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

        register_tool = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr("mcpgateway.main.tool_service.register_tool", register_tool)

        tool_input = ToolCreate(name="tool-a", url="http://example.com", visibility="public")
        await create_tool(tool_input, request, team_id="team-1", db=MagicMock(), user={"email": "user@example.com"})
        assert register_tool.await_args.kwargs["team_id"] is None

    @pytest.mark.asyncio
    async def test_create_tool_name_conflict_inactive_suggests_activation(self, monkeypatch, allow_permission):
        request = _make_request("/tools")
        request.state = SimpleNamespace(team_id=None, token_teams=None)

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

        from mcpgateway.services.tool_service import ToolNameConflictError

        monkeypatch.setattr("mcpgateway.main.tool_service.register_tool", AsyncMock(side_effect=ToolNameConflictError("tool-a", enabled=False, tool_id=123)))

        tool_input = ToolCreate(name="tool-a", url="http://example.com", visibility="public")
        with pytest.raises(HTTPException) as excinfo:
            await create_tool(tool_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 409
        assert "activating" in str(excinfo.value.detail).lower()

    @pytest.mark.asyncio
    async def test_create_tool_tool_error_and_unexpected_error(self, monkeypatch, allow_permission):
        request = _make_request("/tools")
        request.state = SimpleNamespace(team_id=None, token_teams=None)

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

        from mcpgateway.services.tool_service import ToolError

        monkeypatch.setattr("mcpgateway.main.tool_service.register_tool", AsyncMock(side_effect=ToolError("bad")))
        tool_input = ToolCreate(name="tool-a", url="http://example.com", visibility="public")
        with pytest.raises(HTTPException) as excinfo:
            await create_tool(tool_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        monkeypatch.setattr("mcpgateway.main.tool_service.register_tool", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(HTTPException) as excinfo:
            await create_tool(tool_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 500

    @pytest.mark.asyncio
    async def test_update_tool_tool_error_and_unexpected_error(self, monkeypatch, allow_permission):
        request = _make_request("/tools/tool-1")
        db = MagicMock()
        db.get.return_value = SimpleNamespace(version=0)

        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_modification_metadata",
            lambda *_args, **_kwargs: {
                "modified_by": "user",
                "modified_from_ip": "127.0.0.1",
                "modified_via": "api",
                "modified_user_agent": "test",
            },
        )

        from mcpgateway.services.tool_service import ToolError

        monkeypatch.setattr("mcpgateway.main.tool_service.update_tool", AsyncMock(side_effect=ToolError("bad")))
        tool_update = ToolUpdate(name="tool-updated")
        with pytest.raises(HTTPException) as excinfo:
            await update_tool("tool-1", tool_update, request, db=db, user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        monkeypatch.setattr("mcpgateway.main.tool_service.update_tool", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(HTTPException) as excinfo:
            await update_tool("tool-1", tool_update, request, db=db, user={"email": "user@example.com"})
        assert excinfo.value.status_code == 500

    @pytest.mark.asyncio
    async def test_set_tool_state_lock_conflict_and_generic_error(self, monkeypatch, allow_permission):
        from mcpgateway.services.tool_service import ToolLockConflictError

        monkeypatch.setattr("mcpgateway.main.tool_service.set_tool_state", AsyncMock(side_effect=ToolLockConflictError("locked")))
        with pytest.raises(HTTPException) as excinfo:
            await set_tool_state("tool-1", activate=True, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 409

        monkeypatch.setattr("mcpgateway.main.tool_service.set_tool_state", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(HTTPException) as excinfo:
            await set_tool_state("tool-1", activate=True, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_resource_public_only_token_team_visibility_forbidden(self, monkeypatch, allow_permission):
        request = _make_request("/resources")
        request.state = SimpleNamespace(team_id=None, token_teams=[])

        resource_input = ResourceCreate(uri="res://1", name="Res", content="data")
        response = await create_resource(resource_input, request, visibility="team", db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_resource_team_mismatch_returns_403(self, allow_permission):
        request = _make_request("/resources")
        request.state = SimpleNamespace(team_id="team-1", token_teams=["team-1"])

        resource_input = ResourceCreate(uri="res://1", name="Res", content="data")
        response = await create_resource(resource_input, request, team_id="team-2", visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_resource_public_only_token_forces_team_id_none(self, monkeypatch, allow_permission):
        request = _make_request("/resources")
        request.state = SimpleNamespace(team_id="team-1", token_teams=[])

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

        register_resource = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr("mcpgateway.main.resource_service.register_resource", register_resource)

        resource_input = ResourceCreate(uri="res://1", name="Res", content="data")
        await create_resource(resource_input, request, team_id="team-1", visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert register_resource.await_args.kwargs["team_id"] is None

    @pytest.mark.asyncio
    async def test_create_resource_validation_error_and_integrity_error(self, monkeypatch, allow_permission):
        request = _make_request("/resources")
        request.state = SimpleNamespace(team_id=None, token_teams=None)

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

        # Build a real pydantic ValidationError instance
        from pydantic import BaseModel, ValidationError

        class _DummyModel(BaseModel):
            x: int

        try:
            _DummyModel.model_validate({"x": "bad"})
        except ValidationError as err:
            validation_err = err

        monkeypatch.setattr("mcpgateway.main.ErrorFormatter.format_validation_error", lambda _e: "formatted")
        monkeypatch.setattr("mcpgateway.main.resource_service.register_resource", AsyncMock(side_effect=validation_err))

        resource_input = ResourceCreate(uri="res://1", name="Res", content="data")
        with pytest.raises(HTTPException) as excinfo:
            await create_resource(resource_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 422

        from sqlalchemy.exc import IntegrityError

        monkeypatch.setattr("mcpgateway.main.ErrorFormatter.format_database_error", lambda _e: "db-error")
        monkeypatch.setattr("mcpgateway.main.resource_service.register_resource", AsyncMock(side_effect=IntegrityError("stmt", "params", Exception("orig"))))
        with pytest.raises(HTTPException) as excinfo:
            await create_resource(resource_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 409

    @pytest.mark.asyncio
    async def test_update_resource_uri_conflict_maps_to_409(self, monkeypatch, allow_permission):
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
        from mcpgateway.services.resource_service import ResourceURIConflictError

        monkeypatch.setattr("mcpgateway.main.resource_service.update_resource", AsyncMock(side_effect=ResourceURIConflictError("conflict")))
        with pytest.raises(HTTPException) as excinfo:
            await update_resource("res-1", ResourceUpdate(name="Res Updated"), request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 409

    @pytest.mark.asyncio
    async def test_delete_resource_permission_not_found_and_error(self, monkeypatch, allow_permission):
        from mcpgateway.services.resource_service import ResourceError, ResourceNotFoundError

        monkeypatch.setattr("mcpgateway.main.resource_service.delete_resource", AsyncMock(side_effect=PermissionError("nope")))
        with pytest.raises(HTTPException) as excinfo:
            await delete_resource("res-1", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 403

        monkeypatch.setattr("mcpgateway.main.resource_service.delete_resource", AsyncMock(side_effect=ResourceNotFoundError("missing")))
        with pytest.raises(HTTPException) as excinfo:
            await delete_resource("res-1", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

        monkeypatch.setattr("mcpgateway.main.resource_service.delete_resource", AsyncMock(side_effect=ResourceError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await delete_resource("res-1", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_prompt_public_only_and_error_branches(self, monkeypatch, allow_permission):
        request = _make_request("/prompts")
        request.state = SimpleNamespace(team_id="team-1", token_teams=[])

        prompt_input = PromptCreate(name="Prompt A", template="Hello")
        response = await create_prompt(prompt_input, request, visibility="team", db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

        request2 = _make_request("/prompts")
        request2.state = SimpleNamespace(team_id="team-1", token_teams=["team-1"])
        response = await create_prompt(prompt_input, request2, team_id="team-2", visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

        request3 = _make_request("/prompts")
        request3.state = SimpleNamespace(team_id="team-1", token_teams=[])
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
        register_prompt = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr("mcpgateway.main.prompt_service.register_prompt", register_prompt)
        await create_prompt(prompt_input, request3, team_id="team-1", visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert register_prompt.await_args.kwargs["team_id"] is None

        from mcpgateway.services.prompt_service import PromptError, PromptNameConflictError

        monkeypatch.setattr("mcpgateway.main.prompt_service.register_prompt", AsyncMock(side_effect=PromptNameConflictError("dup")))
        with pytest.raises(HTTPException) as excinfo:
            await create_prompt(prompt_input, request3, visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 409

        monkeypatch.setattr("mcpgateway.main.prompt_service.register_prompt", AsyncMock(side_effect=PromptError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await create_prompt(prompt_input, request3, visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        from pydantic import BaseModel, ValidationError

        class _DummyModel(BaseModel):
            x: int

        try:
            _DummyModel.model_validate({"x": "bad"})
        except ValidationError as err:
            validation_err = err

        monkeypatch.setattr("mcpgateway.main.ErrorFormatter.format_validation_error", lambda _e: "formatted")
        monkeypatch.setattr("mcpgateway.main.prompt_service.register_prompt", AsyncMock(side_effect=validation_err))
        with pytest.raises(HTTPException) as excinfo:
            await create_prompt(prompt_input, request3, visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 422

        monkeypatch.setattr("mcpgateway.main.prompt_service.register_prompt", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(HTTPException) as excinfo:
            await create_prompt(prompt_input, request3, visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 500

    @pytest.mark.asyncio
    async def test_update_prompt_name_conflict_prompt_error_and_unexpected(self, monkeypatch, allow_permission):
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
        prompt_update = PromptUpdate(name="Prompt Updated")

        from mcpgateway.services.prompt_service import PromptError, PromptNameConflictError

        monkeypatch.setattr("mcpgateway.main.prompt_service.update_prompt", AsyncMock(side_effect=PromptNameConflictError("dup")))
        with pytest.raises(HTTPException) as excinfo:
            await update_prompt("prompt-1", prompt_update, request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 409

        monkeypatch.setattr("mcpgateway.main.prompt_service.update_prompt", AsyncMock(side_effect=PromptError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await update_prompt("prompt-1", prompt_update, request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        monkeypatch.setattr("mcpgateway.main.prompt_service.update_prompt", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(HTTPException) as excinfo:
            await update_prompt("prompt-1", prompt_update, request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 500

    @pytest.mark.asyncio
    async def test_delete_prompt_permission_prompt_error_and_unexpected(self, monkeypatch, allow_permission):
        from mcpgateway.services.prompt_service import PromptError

        monkeypatch.setattr("mcpgateway.main.prompt_service.delete_prompt", AsyncMock(side_effect=PermissionError("nope")))
        with pytest.raises(HTTPException) as excinfo:
            await delete_prompt("prompt-1", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 403

        monkeypatch.setattr("mcpgateway.main.prompt_service.delete_prompt", AsyncMock(side_effect=PromptError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await delete_prompt("prompt-1", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        monkeypatch.setattr("mcpgateway.main.prompt_service.delete_prompt", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(HTTPException) as excinfo:
            await delete_prompt("prompt-1", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 500


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


class TestSecurityHealthEndpoint:
    """Cover /health/security endpoint branches in main.py."""

    @pytest.mark.asyncio
    async def test_security_health_requires_auth_when_enabled(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {}

        monkeypatch.setattr(main_mod.settings, "auth_required", True)

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.security_health(request)
        assert excinfo.value.status_code == 401

    @pytest.mark.asyncio
    async def test_security_health_includes_warnings_in_dev_mode(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer token"}

        monkeypatch.setattr(main_mod.settings, "auth_required", False)
        monkeypatch.setattr(main_mod.settings, "dev_mode", True)
        monkeypatch.setattr(
            main_mod.settings,
            "get_security_status",
            lambda: {
                "security_score": 80,
                "auth_enabled": True,
                "secure_secrets": True,
                "ssl_verification": True,
                "debug_disabled": True,
                "cors_restricted": True,
                "ui_protected": True,
                "warnings": ["w1"],
            },
        )

        result = await main_mod.security_health(request)
        assert result["status"] == "healthy"
        assert result["warnings"] == ["w1"]

    @pytest.mark.asyncio
    async def test_security_health_omits_warnings_outside_dev_mode(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer token"}

        monkeypatch.setattr(main_mod.settings, "auth_required", False)
        monkeypatch.setattr(main_mod.settings, "dev_mode", False)
        monkeypatch.setattr(
            main_mod.settings,
            "get_security_status",
            lambda: {
                "security_score": 10,
                "auth_enabled": False,
                "secure_secrets": False,
                "ssl_verification": False,
                "debug_disabled": False,
                "cors_restricted": False,
                "ui_protected": False,
                "warnings": ["w1", "w2"],
            },
        )

        result = await main_mod.security_health(request)
        assert result["status"] == "unhealthy"
        assert "warnings" not in result


class TestRootEndpointsCoverage:
    """Cover export_root + root lookup/update error branches."""

    @pytest.mark.asyncio
    async def test_export_root_success_and_username_extraction(self, monkeypatch):
        import mcpgateway.main as main_mod

        root = SimpleNamespace(uri="root://example", name="Root Name")
        monkeypatch.setattr(main_mod.root_service, "get_root_by_uri", AsyncMock(return_value=root))

        result = await main_mod.export_root(uri="root://example", user=SimpleNamespace(email="user@example.com"))
        assert result["export_type"] == "root"
        assert result["exported_by"] == "user@example.com"
        assert result["root"]["uri"] == "root://example"

    @pytest.mark.asyncio
    async def test_export_root_not_found_and_generic_error(self, monkeypatch):
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.root_service, "get_root_by_uri", AsyncMock(side_effect=main_mod.RootServiceNotFoundError("nope")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.export_root(uri="root://missing", user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

        monkeypatch.setattr(main_mod.root_service, "get_root_by_uri", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.export_root(uri="root://err", user="user")
        assert excinfo.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_root_by_uri_success_and_errors(self, monkeypatch):
        import mcpgateway.main as main_mod

        root = SimpleNamespace(uri="root://example", name="Root Name")
        monkeypatch.setattr(main_mod.root_service, "get_root_by_uri", AsyncMock(return_value=root))
        assert await main_mod.get_root_by_uri("root://example", user={"email": "user@example.com"}) == root

        monkeypatch.setattr(main_mod.root_service, "get_root_by_uri", AsyncMock(side_effect=main_mod.RootServiceNotFoundError("nope")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_root_by_uri("root://missing", user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

        monkeypatch.setattr(main_mod.root_service, "get_root_by_uri", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            await main_mod.get_root_by_uri("root://err", user={"email": "user@example.com"})

    @pytest.mark.asyncio
    async def test_update_root_success_and_errors(self, monkeypatch):
        import mcpgateway.main as main_mod

        updated = SimpleNamespace(uri="root://example", name="Updated")
        monkeypatch.setattr(main_mod.root_service, "update_root", AsyncMock(return_value=updated))
        root_payload = SimpleNamespace(name="Updated")
        assert await main_mod.update_root("root://example", root_payload, user={"email": "user@example.com"}) == updated

        monkeypatch.setattr(main_mod.root_service, "update_root", AsyncMock(side_effect=main_mod.RootServiceNotFoundError("nope")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.update_root("root://missing", root_payload, user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

        monkeypatch.setattr(main_mod.root_service, "update_root", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            await main_mod.update_root("root://err", root_payload, user={"email": "user@example.com"})


class TestToolListEndpointCoverage:
    """Cover list_tools() branches (tags parsing, scoping, pagination, mismatch)."""

    @pytest.mark.asyncio
    async def test_list_tools_parses_tags_and_paginates(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)
        db = MagicMock()

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-1"}
        list_tools_mock = AsyncMock(return_value=([tool], "next"))
        monkeypatch.setattr(main_mod.tool_service, "list_tools", list_tools_mock)
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", ["team-1"], False))

        result = await main_mod.list_tools(
            request,
            cursor=None,
            tags="a, b",
            include_pagination=True,
            limit=None,
            include_inactive=False,
            team_id=None,
            visibility=None,
            gateway_id=None,
            db=db,
            apijsonpath=None,
            user={"email": "user@example.com"},
        )
        assert result["tools"][0]["id"] == "tool-1"
        assert result["nextCursor"] == "next"
        assert list_tools_mock.await_args.kwargs["tags"] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_list_tools_admin_bypass_and_public_only_default(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)
        db = MagicMock()

        list_tools_mock = AsyncMock(return_value=([], None))
        monkeypatch.setattr(main_mod.tool_service, "list_tools", list_tools_mock)

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, True))
        await main_mod.list_tools(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            gateway_id=None,
            db=db,
            apijsonpath=None,
            user={"email": "user@example.com"},
        )
        assert list_tools_mock.await_args.kwargs["user_email"] is None
        assert list_tools_mock.await_args.kwargs["token_teams"] is None

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, False))
        await main_mod.list_tools(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            gateway_id=None,
            db=db,
            apijsonpath=None,
            user={"email": "user@example.com"},
        )
        assert list_tools_mock.await_args.kwargs["token_teams"] == []

    @pytest.mark.asyncio
    async def test_list_tools_team_mismatch_returns_403(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id="team-1")
        db = MagicMock()

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", ["team-1"], False))
        response = await main_mod.list_tools(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id="team-2",
            visibility=None,
            gateway_id=None,
            db=db,
            apijsonpath=None,
            user={"email": "user@example.com"},
        )
        assert response.status_code == 403


class TestPromptListEndpointCoverage:
    """Cover list_prompts() branches (tags parsing, scoping, pagination, mismatch)."""

    @pytest.mark.asyncio
    async def test_list_prompts_parses_tags_and_paginates(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)
        db = MagicMock()

        prompt = MagicMock()
        prompt.model_dump.return_value = {"id": "prompt-1"}
        list_prompts_mock = AsyncMock(return_value=([prompt], "next"))
        monkeypatch.setattr(main_mod.prompt_service, "list_prompts", list_prompts_mock)
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", ["team-1"], False))

        result = await main_mod.list_prompts(
            request,
            cursor=None,
            tags="a, b",
            include_pagination=True,
            limit=None,
            include_inactive=False,
            team_id=None,
            visibility=None,
            db=db,
            user={"email": "user@example.com"},
        )
        assert result["prompts"][0]["id"] == "prompt-1"
        assert result["nextCursor"] == "next"
        assert list_prompts_mock.await_args.kwargs["tags"] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_list_prompts_team_mismatch_returns_403(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id="team-1")
        db = MagicMock()

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", ["team-1"], False))
        response = await main_mod.list_prompts(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id="team-2",
            visibility=None,
            db=db,
            user={"email": "user@example.com"},
        )
        assert response.status_code == 403


class TestReadResourceEndpointCoverage:
    """Cover read_resource() serialization branches."""

    @pytest.mark.asyncio
    async def test_read_resource_serializes_text_bytes_and_str(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {"X-Request-ID": "rid", "X-Server-ID": "sid"}
        request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None)

        db = MagicMock()
        monkeypatch.setattr(db, "commit", MagicMock())
        monkeypatch.setattr(db, "close", MagicMock())

        from mcpgateway.common.models import TextContent

        class TextWithUri(TextContent):
            uri: str

        monkeypatch.setattr(main_mod.resource_service, "read_resource", AsyncMock(return_value=TextWithUri(type="text", text="hello", uri="res://1")))
        result = await main_mod.read_resource("res-1", request=request, db=db, user={"email": "user@example.com", "is_admin": False})
        assert result["text"] == "hello"
        assert result["uri"] == "res://1"

        class BytesWithUri(bytes):
            def __new__(cls, value: bytes, uri: str):  # noqa: D401
                obj = super().__new__(cls, value)
                obj._uri = uri
                return obj

            @property
            def uri(self):  # noqa: D401
                return self._uri

        monkeypatch.setattr(main_mod.resource_service, "read_resource", AsyncMock(return_value=BytesWithUri(b"abc", "res://2")))
        result = await main_mod.read_resource("res-2", request=request, db=db, user={"email": "user@example.com", "is_admin": False})
        assert result["blob"] == "abc"
        assert result["uri"] == "res://2"

        class StrWithUri(str):
            def __new__(cls, value: str, uri: str):  # noqa: D401
                obj = super().__new__(cls, value)
                obj._uri = uri
                return obj

            @property
            def uri(self):  # noqa: D401
                return self._uri

        monkeypatch.setattr(main_mod.resource_service, "read_resource", AsyncMock(return_value=StrWithUri("hi", "res://3")))
        result = await main_mod.read_resource("res-3", request=request, db=db, user={"email": "user@example.com", "is_admin": False})
        assert result["text"] == "hi"
        assert result["uri"] == "res://3"


class TestGetPromptEndpointCoverage:
    """Cover get_prompt() exception mapping branches."""

    @pytest.mark.asyncio
    async def test_get_prompt_maps_common_errors_to_422(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None)

        # PluginViolationError -> 422 with plugin message.
        from mcpgateway.plugins.framework.errors import PluginViolationError

        monkeypatch.setattr(main_mod.prompt_service, "get_prompt", AsyncMock(side_effect=PluginViolationError("blocked", violation=SimpleNamespace(code="c"))))
        response = await main_mod.get_prompt(request, "prompt-1", args={}, db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 422

        # ValueError -> 422 with message.
        monkeypatch.setattr(main_mod.prompt_service, "get_prompt", AsyncMock(side_effect=ValueError("bad args")))
        response = await main_mod.get_prompt(request, "prompt-1", args={}, db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 422

        # PromptError -> 422 with message.
        from mcpgateway.services.prompt_service import PromptError

        monkeypatch.setattr(main_mod.prompt_service, "get_prompt", AsyncMock(side_effect=PromptError("bad prompt")))
        response = await main_mod.get_prompt(request, "prompt-1", args={}, db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 422


class TestGatewayEndpointsCoverage:
    """Cover gateway endpoint error mapping + refresh manual path."""

    @pytest.mark.asyncio
    async def test_delete_gateway_error_mappings(self, monkeypatch):
        import mcpgateway.main as main_mod

        db = MagicMock()
        monkeypatch.setattr(db, "commit", MagicMock())
        monkeypatch.setattr(db, "close", MagicMock())

        monkeypatch.setattr(main_mod.gateway_service, "get_gateway", AsyncMock(side_effect=PermissionError("nope")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_gateway("gw-1", db=db, user={"email": "user@example.com"})
        assert excinfo.value.status_code == 403

        from mcpgateway.services.gateway_service import GatewayNotFoundError, GatewayError

        monkeypatch.setattr(main_mod.gateway_service, "get_gateway", AsyncMock(side_effect=GatewayNotFoundError("missing")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_gateway("gw-1", db=db, user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

        monkeypatch.setattr(main_mod.gateway_service, "get_gateway", AsyncMock(side_effect=GatewayError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_gateway("gw-1", db=db, user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_gateway_success_invalidates_resource_cache_when_needed(self, monkeypatch):
        import mcpgateway.main as main_mod

        db = MagicMock()
        monkeypatch.setattr(db, "commit", MagicMock())
        monkeypatch.setattr(db, "close", MagicMock())

        current = SimpleNamespace(capabilities={"resources": True})
        monkeypatch.setattr(main_mod.gateway_service, "get_gateway", AsyncMock(return_value=current))
        monkeypatch.setattr(main_mod.gateway_service, "delete_gateway", AsyncMock(return_value=None))
        invalidate = AsyncMock(return_value=None)
        monkeypatch.setattr(main_mod, "invalidate_resource_cache", invalidate)

        result = await main_mod.delete_gateway("gw-1", db=db, user={"email": "user@example.com"})
        assert result["status"] == "success"
        invalidate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_refresh_gateway_tools_success_and_errors(self, monkeypatch):
        import mcpgateway.main as main_mod

        from datetime import datetime, timezone
        from mcpgateway.services.gateway_service import GatewayError, GatewayNotFoundError

        request = MagicMock(spec=Request)
        request.headers = {"x-test": "1"}

        result_payload = {
            "duration_ms": 1.0,
            "refreshed_at": datetime.now(timezone.utc),
            "tools_added": 1,
        }
        monkeypatch.setattr(main_mod.gateway_service, "refresh_gateway_manually", AsyncMock(return_value=result_payload))
        response = await main_mod.refresh_gateway_tools(
            "gw-1",
            request,
            include_resources=True,
            include_prompts=False,
            user={"email": "user@example.com"},
        )
        assert response.gateway_id == "gw-1"
        assert response.tools_added == 1

        monkeypatch.setattr(main_mod.gateway_service, "refresh_gateway_manually", AsyncMock(side_effect=GatewayNotFoundError("missing")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.refresh_gateway_tools(
                "gw-1",
                request,
                include_resources=False,
                include_prompts=False,
                user={"email": "user@example.com"},
            )
        assert excinfo.value.status_code == 404

        monkeypatch.setattr(main_mod.gateway_service, "refresh_gateway_manually", AsyncMock(side_effect=GatewayError("conflict")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.refresh_gateway_tools(
                "gw-1",
                request,
                include_resources=False,
                include_prompts=False,
                user={"email": "user@example.com"},
            )
        assert excinfo.value.status_code == 409


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
        monkeypatch.setattr(main_mod.settings, "mcpgateway_session_affinity_enabled", True)
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
        plugin.shutdown = AsyncMock(side_effect=Exception("boom"))
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
        pool = SimpleNamespace(start_rpc_listener=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", MagicMock(return_value=pool))

        # Cache invalidation subscriber
        subscriber = MagicMock()
        subscriber.start = AsyncMock()
        subscriber.stop = AsyncMock(side_effect=Exception("stop fail"))
        # `mcpgateway.cache` uses lazy `__getattr__` which returns a `registry_cache`
        # instance, so string-based patching can resolve to the wrong object under xdist.
        import mcpgateway.cache.registry_cache as registry_cache_mod

        monkeypatch.setattr(registry_cache_mod, "get_cache_invalidation_subscriber", MagicMock(return_value=subscriber))

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

    @pytest.mark.asyncio
    async def test_lifespan_exits_on_plugin_initialization_failed(self, monkeypatch):
        """Cover lifespan startup exception branch that raises SystemExit on plugin init failure."""
        import mcpgateway.main as main_mod

        def make_service():  # noqa: ANN001 - local test helper
            service = MagicMock()
            service.initialize = AsyncMock()
            service.shutdown = AsyncMock()
            return service

        # Keep startup/shutdown lightweight.
        for flag, value in (
            ("mcp_session_pool_enabled", False),
            ("mcpgateway_session_affinity_enabled", False),
            ("enable_header_passthrough", False),
            ("mcpgateway_tool_cancellation_enabled", False),
            ("mcpgateway_elicitation_enabled", False),
            ("metrics_buffer_enabled", False),
            ("metrics_cleanup_enabled", False),
            ("metrics_rollup_enabled", False),
            ("sso_enabled", False),
            ("metrics_aggregation_enabled", False),
        ):
            monkeypatch.setattr(main_mod.settings, flag, value)

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
        monkeypatch.setattr(main_mod, "a2a_service", None)

        monkeypatch.setattr(main_mod, "get_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod, "close_redis_client", AsyncMock())
        monkeypatch.setattr("mcpgateway.routers.llmchat_router.init_redis", AsyncMock())
        monkeypatch.setattr(main_mod, "init_telemetry", MagicMock())
        monkeypatch.setattr(main_mod, "validate_security_configuration", MagicMock())

        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.get_instance", AsyncMock())
        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.shutdown", AsyncMock())

        subscriber = MagicMock()
        subscriber.start = AsyncMock()
        subscriber.stop = AsyncMock()
        import mcpgateway.cache.registry_cache as registry_cache_mod

        monkeypatch.setattr(registry_cache_mod, "get_cache_invalidation_subscriber", MagicMock(return_value=subscriber))

        plugin = MagicMock()
        plugin.initialize = AsyncMock(side_effect=Exception("Plugin initialization failed"))
        plugin.shutdown = AsyncMock()
        plugin.plugin_count = 1
        monkeypatch.setattr(main_mod, "plugin_manager", plugin)

        with pytest.raises(SystemExit) as excinfo:
            async with main_mod.lifespan(main_mod.app):
                pass

        assert excinfo.value.code == 1
        plugin.shutdown.assert_awaited()

    @pytest.mark.asyncio
    async def test_shutdown_services_continues_on_exception(self):
        """Cover shutdown_services exception logging branch."""
        import mcpgateway.main as main_mod

        bad = MagicMock()
        bad.shutdown = AsyncMock(side_effect=Exception("boom"))
        good = MagicMock()
        good.shutdown = AsyncMock()

        await main_mod.shutdown_services([bad, good])

        good.shutdown.assert_awaited_once()


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
        mock_settings.mcpgateway_ws_relay_enabled = True
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

    @pytest.mark.asyncio
    async def test_websocket_feature_disabled_closes(self, monkeypatch):
        """WebSocket relay should reject connections when feature flag is disabled."""
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcpgateway_ws_relay_enabled", False)
        websocket = MagicMock()
        websocket.close = AsyncMock()
        websocket.accept = AsyncMock()

        await main_mod.websocket_endpoint(websocket)

        websocket.close.assert_awaited_once_with(code=1008, reason="WebSocket relay is disabled")
        websocket.accept.assert_not_called()

    def test_get_websocket_bearer_token_accepts_lowercase_scheme(self):
        """Bearer scheme parsing should be case-insensitive for WebSocket auth headers."""
        import mcpgateway.main as main_mod

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {"authorization": "bearer test-token"}

        assert main_mod._get_websocket_bearer_token(websocket) == "test-token"

    @pytest.mark.asyncio
    async def test_authenticate_websocket_user_wraps_unexpected_auth_errors(self, monkeypatch):
        """Unexpected auth backend errors should be normalized to HTTP 401."""
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", True)
        monkeypatch.setattr(main_mod.settings, "auth_required", True)

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {"authorization": "Bearer token"}
        websocket.client = SimpleNamespace(host="127.0.0.1")
        websocket.state = SimpleNamespace(team_id=None, token_teams=None, token_use=None)

        monkeypatch.setattr(main_mod, "get_current_user", AsyncMock(side_effect=RuntimeError("db down")))

        with pytest.raises(HTTPException) as exc_info:
            await main_mod._authenticate_websocket_user(websocket)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Authentication failed"

    @pytest.mark.asyncio
    async def test_websocket_bearer_auth_invalid_token_closes(self, monkeypatch):
        """Cover Bearer token extraction + invalid token close path."""
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", True)
        monkeypatch.setattr(main_mod.settings, "auth_required", True)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_ws_relay_enabled", True)

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {"authorization": "Bearer bad-token"}
        websocket.accept = AsyncMock()
        websocket.close = AsyncMock()

        monkeypatch.setattr(main_mod, "_authenticate_websocket_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Invalid authentication")))

        await main_mod.websocket_endpoint(websocket)

        websocket.close.assert_awaited_once_with(code=1008, reason="Invalid authentication")
        websocket.accept.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_proxy_auth_required_closes(self, monkeypatch):
        """Cover proxy-auth required branch when trust_proxy_auth is enabled."""
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", False)
        monkeypatch.setattr(main_mod.settings, "trust_proxy_auth", True)
        monkeypatch.setattr(main_mod.settings, "auth_required", True)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_ws_relay_enabled", True)

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {}
        websocket.accept = AsyncMock()
        websocket.close = AsyncMock()
        monkeypatch.setattr(main_mod, "_authenticate_websocket_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Authentication required")))

        await main_mod.websocket_endpoint(websocket)

        websocket.close.assert_awaited_once_with(code=1008, reason="Authentication required")
        websocket.accept.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_jsonrpc_error_sends_error_text(self, monkeypatch):
        """Cover JSONRPCError branch inside the websocket relay loop."""
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", False)
        monkeypatch.setattr(main_mod.settings, "auth_required", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_ws_relay_enabled", True)
        monkeypatch.setattr(main_mod.settings, "federation_timeout", 1)
        monkeypatch.setattr(main_mod.settings, "skip_ssl_verify", False)
        monkeypatch.setattr(main_mod.settings, "port", 4444)
        monkeypatch.setattr(main_mod.settings, "app_root_path", "")

        err = main_mod.JSONRPCError(-32000, "boom", {})

        class DummyClient:
            async def __aenter__(self):  # noqa: D401
                return self

            async def __aexit__(self, *_args):  # noqa: D401, ANN001
                return False

            async def post(self, *_args, **_kwargs):  # noqa: ANN001
                raise err

        monkeypatch.setattr(main_mod, "ResilientHttpClient", lambda *_a, **_k: DummyClient())
        monkeypatch.setattr(main_mod, "_authenticate_websocket_user", AsyncMock(return_value=(None, None)))

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {}
        websocket.accept = AsyncMock()
        websocket.close = AsyncMock()
        websocket.send_text = AsyncMock()
        websocket.receive_text = AsyncMock(side_effect=['{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}', Exception("stop")])

        await main_mod.websocket_endpoint(websocket)

        assert websocket.send_text.await_count >= 1

    @pytest.mark.asyncio
    async def test_websocket_invalid_json_sends_parse_error(self, monkeypatch):
        """Cover orjson.JSONDecodeError -> JSON-RPC parse error response."""
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", False)
        monkeypatch.setattr(main_mod.settings, "auth_required", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_ws_relay_enabled", True)
        monkeypatch.setattr(main_mod, "_authenticate_websocket_user", AsyncMock(return_value=(None, None)))

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {}
        websocket.accept = AsyncMock()
        websocket.close = AsyncMock()
        websocket.send_text = AsyncMock()
        websocket.receive_text = AsyncMock(side_effect=["{", Exception("stop")])

        await main_mod.websocket_endpoint(websocket)

        sent = websocket.send_text.await_args.args[0]
        parsed = json.loads(sent)
        assert parsed["error"]["code"] == -32700

    @pytest.mark.asyncio
    async def test_websocket_outer_exception_close_failure_is_caught(self, monkeypatch):
        """Cover outer exception handler when websocket.close itself fails."""
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", False)
        monkeypatch.setattr(main_mod.settings, "auth_required", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_ws_relay_enabled", True)
        monkeypatch.setattr(main_mod, "_authenticate_websocket_user", AsyncMock(return_value=(None, None)))

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {}
        websocket.accept = AsyncMock(side_effect=RuntimeError("accept failed"))
        websocket.close = AsyncMock(side_effect=Exception("close failed"))

        await main_mod.websocket_endpoint(websocket)

        assert websocket.close.await_count == 1

    def test_sse_endpoint_edge_cases(self, test_client, auth_headers):
        """Test SSE endpoint edge cases."""
        with patch("mcpgateway.main.SSETransport") as mock_transport_class, patch("mcpgateway.main.session_registry.add_session"):
            mock_transport = MagicMock()
            mock_transport.session_id = "test-session"

            # Test SSE transport creation error
            mock_transport_class.side_effect = Exception("SSE error")

            response = test_client.get("/servers/test/sse", headers=auth_headers)
            # Should handle SSE creation error
            assert response.status_code in [404, 500, 503]

    @pytest.mark.asyncio
    async def test_utility_sse_bearer_token_and_disconnect_cleanup(self, monkeypatch, allow_permission):
        """Cover /sse auth token extraction + defensive disconnect cleanup callback."""
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer token"}
        request.cookies = {}
        request.scope = {"root_path": ""}

        user = SimpleNamespace(email="user@example.com", is_admin=True)

        monkeypatch.setattr(main_mod, "update_url_protocol", lambda _req: "http://example.com")
        monkeypatch.setattr(main_mod, "_get_token_teams_from_request", lambda _req: None)

        monkeypatch.setattr(main_mod.session_registry, "add_session", AsyncMock())
        remove_session = AsyncMock()
        monkeypatch.setattr(main_mod.session_registry, "remove_session", remove_session)
        respond = AsyncMock(return_value=None)
        monkeypatch.setattr(main_mod.session_registry, "respond", respond)
        monkeypatch.setattr(main_mod.session_registry, "register_respond_task", MagicMock())
        monkeypatch.setattr(main_mod.asyncio, "create_task", MagicMock(return_value=MagicMock()))

        transport = SimpleNamespace(session_id="session-1", connect=AsyncMock())
        captured: dict[str, object] = {}

        async def _create_sse_response(_request, *, on_disconnect_callback=None):  # noqa: ANN001
            captured["callback"] = on_disconnect_callback
            return StarletteResponse("ok")

        transport.create_sse_response = AsyncMock(side_effect=_create_sse_response)
        monkeypatch.setattr(main_mod, "SSETransport", MagicMock(return_value=transport))

        # Bypass RBAC wrapper so we can pass a non-dict user object and exercise
        # the `hasattr(user, "is_admin")` branch inside the endpoint.
        response = await main_mod.utility_sse_endpoint.__wrapped__(request, user=user)
        assert response.status_code == 200
        assert response.background is not None

        assert callable(captured.get("callback"))
        await captured["callback"]()
        remove_session.assert_awaited_once_with("session-1")

    @pytest.mark.asyncio
    async def test_utility_sse_cookie_token_and_cleanup_warning(self, monkeypatch, allow_permission):
        """Cover cookie token extraction + cleanup exception branch."""
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {}
        request.cookies = {"jwt_token": "cookie-token"}
        request.scope = {"root_path": ""}

        user = {"email": "user@example.com", "is_admin": False}

        monkeypatch.setattr(main_mod, "update_url_protocol", lambda _req: "http://example.com")
        monkeypatch.setattr(main_mod, "_get_token_teams_from_request", lambda _req: [])

        monkeypatch.setattr(main_mod.session_registry, "add_session", AsyncMock())
        monkeypatch.setattr(main_mod.session_registry, "respond", AsyncMock(return_value=None))
        monkeypatch.setattr(main_mod.session_registry, "register_respond_task", MagicMock())
        monkeypatch.setattr(main_mod.asyncio, "create_task", MagicMock(return_value=MagicMock()))

        remove_session = AsyncMock(side_effect=Exception("boom"))
        monkeypatch.setattr(main_mod.session_registry, "remove_session", remove_session)

        transport = SimpleNamespace(session_id="session-2", connect=AsyncMock())
        captured: dict[str, object] = {}

        async def _create_sse_response(_request, *, on_disconnect_callback=None):  # noqa: ANN001
            captured["callback"] = on_disconnect_callback
            return StarletteResponse("ok")

        transport.create_sse_response = AsyncMock(side_effect=_create_sse_response)
        monkeypatch.setattr(main_mod, "SSETransport", MagicMock(return_value=transport))

        response = await main_mod.utility_sse_endpoint(request, user=user)
        assert response.status_code == 200

        # Cleanup callback should swallow errors from session_registry.remove_session.
        await captured["callback"]()

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


class TestA2ABranchCoverage:
    """Cover A2A branches that aren't hit via happy-path API tests."""

    @pytest.mark.asyncio
    async def test_create_a2a_agent_rejects_public_only_token_for_team_visibility(self, monkeypatch):
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import A2AAgentCreate

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None, token_teams=[])

        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_a, **_k: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )

        agent = A2AAgentCreate(name="agent", endpoint_url="http://example.com/agent")
        response = await main_mod.create_a2a_agent(agent, request, team_id=None, visibility="team", db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_a2a_agent_team_mismatch_and_service_unavailable(self, monkeypatch):
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import A2AAgentCreate

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id="team-1", token_teams=["team-1"])

        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_a, **_k: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )

        agent = A2AAgentCreate(name="agent", endpoint_url="http://example.com/agent")
        response = await main_mod.create_a2a_agent(agent, request, team_id="team-2", visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

        monkeypatch.setattr(main_mod, "a2a_service", None)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.create_a2a_agent(agent, request, team_id=None, visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 503

    @pytest.mark.asyncio
    async def test_create_a2a_agent_validation_and_integrity_errors(self, monkeypatch):
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import A2AAgentCreate
        from pydantic import BaseModel, ValidationError
        from sqlalchemy.exc import IntegrityError

        class _Tmp(BaseModel):
            value: int

        try:
            _Tmp.model_validate({})
        except ValidationError as e:
            validation_error = e

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None, token_teams=["team-1"])

        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_a, **_k: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )
        monkeypatch.setattr(main_mod.ErrorFormatter, "format_validation_error", lambda _e: "bad")
        monkeypatch.setattr(main_mod.ErrorFormatter, "format_database_error", lambda _e: "db")

        agent = A2AAgentCreate(name="agent", endpoint_url="http://example.com/agent")
        svc = MagicMock()
        svc.register_agent = AsyncMock(side_effect=validation_error)
        monkeypatch.setattr(main_mod, "a2a_service", svc)

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.create_a2a_agent(agent, request, team_id=None, visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 422

        svc.register_agent = AsyncMock(side_effect=IntegrityError("stmt", {}, Exception("orig")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.create_a2a_agent(agent, request, team_id=None, visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 409

    @pytest.mark.asyncio
    async def test_delete_a2a_agent_error_mappings(self, monkeypatch):
        import mcpgateway.main as main_mod
        from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNotFoundError

        monkeypatch.setattr(main_mod, "a2a_service", None)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_a2a_agent("agent-1", purge_metrics=False, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 503

        svc = MagicMock()
        svc.delete_agent = AsyncMock(side_effect=PermissionError("nope"))
        monkeypatch.setattr(main_mod, "a2a_service", svc)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_a2a_agent("agent-1", purge_metrics=False, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 403

        svc.delete_agent = AsyncMock(side_effect=A2AAgentNotFoundError("missing"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_a2a_agent("agent-1", purge_metrics=False, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

        svc.delete_agent = AsyncMock(side_effect=A2AAgentError("bad"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_a2a_agent("agent-1", purge_metrics=False, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

    @pytest.mark.asyncio
    async def test_invoke_a2a_agent_branches_and_errors(self, monkeypatch):
        import mcpgateway.main as main_mod
        from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNotFoundError

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        monkeypatch.setattr(main_mod, "a2a_service", None)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.invoke_a2a_agent("agent", request, parameters={}, interaction_type="query", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 503

        svc = MagicMock()
        svc.invoke_agent = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(main_mod, "a2a_service", svc)
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, False))
        result = await main_mod.invoke_a2a_agent("agent", request, parameters={}, interaction_type="query", db=MagicMock(), user={"email": "user@example.com"})
        assert result["ok"] is True
        assert svc.invoke_agent.await_args.kwargs["token_teams"] == []

        svc.invoke_agent = AsyncMock(side_effect=A2AAgentNotFoundError("missing"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.invoke_a2a_agent("agent", request, parameters={}, interaction_type="query", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

        svc.invoke_agent = AsyncMock(side_effect=A2AAgentError("bad"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.invoke_a2a_agent("agent", request, parameters={}, interaction_type="query", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        # Cover user_id=str(user) branch by bypassing RBAC wrapper.
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, True))
        svc.invoke_agent = AsyncMock(return_value={"ok": True})
        result = await main_mod.invoke_a2a_agent.__wrapped__("agent", request, parameters={}, interaction_type="query", db=MagicMock(), user="basic-user")
        assert result["ok"] is True
        assert svc.invoke_agent.await_args.kwargs["user_id"] == "basic-user"

    @pytest.mark.asyncio
    async def test_list_and_get_a2a_agents_branches(self, monkeypatch):
        import mcpgateway.main as main_mod
        from mcpgateway.services.a2a_service import A2AAgentNotFoundError

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)
        db = MagicMock()

        monkeypatch.setattr(main_mod, "a2a_service", None)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.list_a2a_agents(
                request,
                include_inactive=False,
                tags="a, b",
                team_id=None,
                visibility=None,
                cursor=None,
                include_pagination=False,
                limit=None,
                db=db,
                user={"email": "user@example.com"},
            )
        assert excinfo.value.status_code == 503

        agent = MagicMock()
        agent.model_dump.return_value = {"id": "agent-1"}
        svc = MagicMock()
        svc.list_agents = AsyncMock(return_value=([agent], "next"))
        svc.get_agent = AsyncMock(side_effect=A2AAgentNotFoundError("missing"))
        monkeypatch.setattr(main_mod, "a2a_service", svc)
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, True))

        result = await main_mod.list_a2a_agents(
            request,
            include_inactive=False,
            tags="a, b",
            team_id=None,
            visibility=None,
            cursor=None,
            include_pagination=True,
            limit=None,
            db=db,
            user={"email": "user@example.com"},
        )
        assert result["agents"][0]["id"] == "agent-1"
        assert result["nextCursor"] == "next"

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_a2a_agent("agent-1", request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404


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

    async def test_handle_rpc_resources_read_success_and_error(self):
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

        # Gateway forwarding is removed, so missing resource returns error
        with (
            patch("mcpgateway.main.resource_service.read_resource", new=AsyncMock(side_effect=ValueError("no local"))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert "error" in result
            assert result["error"]["code"] == -32002

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
            patch("mcpgateway.main.cancellation_service.get_status", new=AsyncMock(return_value={"owner_email": "user@example.com", "owner_team_ids": []})),
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

    async def test_handle_rpc_fallback_tool_error(self):
        payload = {"jsonrpc": "2.0", "id": "17", "method": "custom/tool", "params": {"a": 1}}
        request = self._make_request(payload)
        request.state = MagicMock()

        tool_result = MagicMock()
        tool_result.model_dump.return_value = {"ok": True}
        with patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(return_value=tool_result)):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["ok"] is True

        # Gateway forwarding is removed, so missing tool returns error
        with patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(side_effect=ValueError("no tool"))):
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

    async def test_handle_rpc_resources_read_admin_error_on_missing(self):
        payload = {"jsonrpc": "2.0", "id": "23", "method": "resources/read", "params": {"uri": "resource://admin"}}
        request = self._make_request(payload)
        request.state = MagicMock()

        # Gateway forwarding is removed, so missing resource returns error
        with (
            patch("mcpgateway.main.resource_service.read_resource", new=AsyncMock(side_effect=ValueError("no local"))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert "error" in result
            assert result["error"]["code"] == -32002

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

    async def test_handle_rpc_session_affinity_invalid_session_executes_locally(self, monkeypatch):
        """Cover session affinity branch when the MCP session id is invalid."""
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)
        payload = {"jsonrpc": "2.0", "id": "aff-1", "method": "ping", "params": {}}
        request = self._make_request(payload)
        request.headers = {"mcp-session-id": "not-valid"}

        with patch("mcpgateway.services.mcp_session_pool.MCPSessionPool.is_valid_mcp_session_id", return_value=False):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"] == {}

    async def test_handle_rpc_session_affinity_forwarded_response_success_and_error(self, monkeypatch):
        """Cover forwarding path for session affinity (success and error responses)."""
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)

        payload = {"jsonrpc": "2.0", "id": "aff-2", "method": "tools/list", "params": {}}
        request = self._make_request(payload)
        request.headers = {"mcp-session-id": "sess-123"}

        pool = MagicMock()
        pool.forward_request_to_owner = AsyncMock(return_value={"result": {"via": "other-worker"}})

        with (
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool.is_valid_mcp_session_id", return_value=True),
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=pool),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["via"] == "other-worker"

        pool.forward_request_to_owner = AsyncMock(return_value={"error": {"code": -32001, "message": "nope"}})
        with (
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool.is_valid_mcp_session_id", return_value=True),
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=pool),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32001

    async def test_handle_rpc_session_affinity_pool_not_initialized(self, monkeypatch):
        """Cover RuntimeError branch when pool isn't initialized."""
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)
        payload = {"jsonrpc": "2.0", "id": "aff-3", "method": "ping", "params": {}}
        request = self._make_request(payload)
        request.headers = {"mcp-session-id": "sess-123"}

        with (
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool.is_valid_mcp_session_id", return_value=True),
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", side_effect=RuntimeError("no pool")),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"] == {}

    async def test_handle_rpc_session_affinity_internal_forwarded_executes_locally(self, monkeypatch):
        """Cover internally forwarded header branch."""
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)
        payload = {"jsonrpc": "2.0", "id": "aff-4", "method": "ping", "params": {}}
        request = self._make_request(payload)
        request.headers = {"mcp-session-id": "sess-123", "x-forwarded-internally": "true"}

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["result"] == {}

    async def test_handle_rpc_initialize_registers_session_owner_success_and_failure(self, monkeypatch):
        """Cover initialize ownership registration paths."""
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)
        payload = {"jsonrpc": "2.0", "id": "aff-init", "method": "initialize", "params": {"session_id": "init-1"}}
        request = self._make_request(payload)
        request.headers = {"mcp-session-id": "sess-123"}

        init_result = MagicMock()
        init_result.model_dump.return_value = {"capabilities": {}}
        monkeypatch.setattr("mcpgateway.main.session_registry.handle_initialize_logic", AsyncMock(return_value=init_result))

        pool = MagicMock()
        pool.register_pool_session_owner = AsyncMock(return_value=None)

        with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=pool):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["capabilities"] == {}
            pool.register_pool_session_owner.assert_awaited_once()

        pool.register_pool_session_owner = AsyncMock(side_effect=Exception("boom"))
        with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=pool):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["capabilities"] == {}

    async def test_handle_rpc_list_tools_legacy_token_teams_none_becomes_public_only(self):
        """Cover legacy list_tools branch when token_teams is explicitly None for non-admin."""
        payload = {"jsonrpc": "2.0", "id": "legacy-1", "method": "list_tools", "params": {}}
        request = self._make_request(payload)
        request.state.token_teams = None

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-1"}
        mock_db = MagicMock()

        with patch("mcpgateway.main.tool_service.list_tools", new=AsyncMock(return_value=([tool], None))):
            result = await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})
            assert result["result"]["tools"][0]["id"] == "tool-1"

    async def test_handle_rpc_list_gateways_admin_bypass_and_next_cursor(self):
        """Cover list_gateways scoping branches and nextCursor injection."""
        payload = {"jsonrpc": "2.0", "id": "gw-1", "method": "list_gateways", "params": {}}
        request = self._make_request(payload)
        request.state._jwt_verified_payload = ("token", {"teams": None, "is_admin": True})

        gateway = MagicMock()
        gateway.model_dump.return_value = {"id": "gw-1"}
        mock_db = MagicMock()

        with patch("mcpgateway.main.gateway_service.list_gateways", new=AsyncMock(return_value=([gateway], "next"))):
            result = await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})
            assert result["result"]["gateways"][0]["id"] == "gw-1"
            assert result["result"]["nextCursor"] == "next"

        request2 = self._make_request(payload)
        request2.state.token_teams = None  # Explicitly None but no admin flag in token -> public-only
        with patch("mcpgateway.main.gateway_service.list_gateways", new=AsyncMock(return_value=([], None))) as list_gateways:
            result = await handle_rpc(request2, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["gateways"] == []
            assert list_gateways.await_count == 1

    async def test_handle_rpc_elicitation_value_error_and_catch_all(self, monkeypatch):
        """Cover elicitation ValueError mapping and method catch-all."""
        monkeypatch.setattr(settings, "mcpgateway_elicitation_enabled", True)

        class _Pending:
            def __init__(self, downstream_session_id: str, request_id: str):
                self.downstream_session_id = downstream_session_id
                self.request_id = request_id

        class _BadElicitationService:
            def __init__(self):
                self._pending = {"p1": _Pending("sess-1", "req-1")}

            async def create_elicitation(self, **_kwargs):
                raise ValueError("bad elicit")

        payload = {
            "jsonrpc": "2.0",
            "id": "elic-1",
            "method": "elicitation/create",
            "params": {"message": "Need input", "requestedSchema": {"type": "object", "properties": {"x": {"type": "string"}}}, "session_id": "sess-1"},
        }
        request = self._make_request(payload)
        request.state = MagicMock()

        with (
            patch("mcpgateway.services.elicitation_service.get_elicitation_service", return_value=_BadElicitationService()),
            patch("mcpgateway.main.session_registry.has_elicitation_capability", new=AsyncMock(return_value=True)),
            patch("mcpgateway.main.session_registry.broadcast", new=AsyncMock(return_value=None)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32000

        payload_other = {"jsonrpc": "2.0", "id": "elic-2", "method": "elicitation/other", "params": {}}
        request_other = self._make_request(payload_other)
        result = await handle_rpc(request_other, db=MagicMock(), user={"email": "user@example.com"})
        assert result["result"] == {}

    async def test_handle_rpc_fallback_method_not_found_and_internal_error(self):
        """Cover fallback error when tool not found (gateway forwarding removed) and generic internal error."""
        payload = {"jsonrpc": "2.0", "id": "fallback-1", "method": "custom/forward", "params": {"a": 1}}
        request = self._make_request(payload)
        request.state = MagicMock()

        # Gateway forwarding is removed, so missing tool returns error
        with patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(side_effect=ValueError("no tool"))):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32000

        payload_missing_method = {"jsonrpc": "2.0", "id": "err-1", "params": {}}
        request_missing_method = self._make_request(payload_missing_method)
        result = await handle_rpc(request_missing_method, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["message"] == "Internal error"

    async def test_handle_rpc_tools_call_cancel_callback_cancels_task(self, monkeypatch):
        """Cover inner cancel_tool_task() callback cancelling a live asyncio task."""
        monkeypatch.setattr(settings, "mcpgateway_tool_cancellation_enabled", True)

        payload = {"jsonrpc": "2.0", "id": "cb-1", "method": "tools/call", "params": {"name": "tool-long", "arguments": {}}}
        request = self._make_request(payload)
        request.state = MagicMock()

        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow_invoke(*_args, **_kwargs):
            started.set()
            await release.wait()
            return {"ok": True}

        cancel_callback_holder: dict[str, object] = {}

        async def _capture_register_run(run_id, *, name, cancel_callback, owner_email=None, owner_team_ids=None):  # noqa: ANN001, ARG001
            cancel_callback_holder["cb"] = cancel_callback
            return None

        with (
            patch("mcpgateway.main.cancellation_service.register_run", new=AsyncMock(side_effect=_capture_register_run)),
            patch("mcpgateway.main.cancellation_service.get_status", new=AsyncMock(return_value={"cancelled": False})),
            patch("mcpgateway.main.cancellation_service.unregister_run", new=AsyncMock(return_value=None)),
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(side_effect=_slow_invoke)),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            rpc_task = asyncio.create_task(handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"}))
            await asyncio.wait_for(started.wait(), timeout=2.0)
            await cancel_callback_holder["cb"](reason="test")  # type: ignore[misc]
            release.set()

            result = await rpc_task
            assert result["error"]["code"] == -32800

    @pytest.mark.asyncio
    async def test_handle_rpc_notifications_cancelled_denies_non_owner(self):
        payload_cancel = {"jsonrpc": "2.0", "id": "32", "method": "notifications/cancelled", "params": {"requestId": "r1", "reason": "stop"}}
        request_cancel = self._make_request(payload_cancel)

        with (
            patch("mcpgateway.main.cancellation_service.get_status", new=AsyncMock(return_value={"owner_email": "owner@example.com", "owner_team_ids": []})),
            patch("mcpgateway.main.logging_service.notify", new=AsyncMock(return_value=None)),
        ):
            result = await handle_rpc(request_cancel, db=MagicMock(), user={"email": "user@example.com"})

        assert result["error"]["message"] == "Not authorized to cancel this run"


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

    async def test_export_configuration_parsing_and_error_mappings(self, monkeypatch):
        import mcpgateway.main as main_mod
        from mcpgateway.services.export_service import ExportError

        request = MagicMock(spec=Request)
        svc = MagicMock()
        svc.export_configuration = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(main_mod, "export_service", svc)

        user_obj = SimpleNamespace(email="user@example.com")
        result = await main_mod.export_configuration.__wrapped__(
            request,
            types="tools,gateways",
            exclude_types="servers",
            tags="a, b",
            include_inactive=True,
            include_dependencies=False,
            db=MagicMock(),
            user=user_obj,
        )
        assert result["ok"] is True
        kwargs = svc.export_configuration.await_args.kwargs
        assert kwargs["include_types"] == ["tools", "gateways"]
        assert kwargs["exclude_types"] == ["servers"]
        assert kwargs["tags"] == ["a", "b"]
        assert kwargs["exported_by"] == "user@example.com"

        svc.export_configuration = AsyncMock(side_effect=ExportError("bad"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.export_configuration.__wrapped__(request, types="tools", db=MagicMock(), user="basic-user")
        assert excinfo.value.status_code == 400

        svc.export_configuration = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.export_configuration.__wrapped__(request, types="tools", db=MagicMock(), user="basic-user")
        assert excinfo.value.status_code == 500

    async def test_export_selective_configuration_success(self):
        export_service = MagicMock()
        export_service.export_selective = AsyncMock(return_value={"tools": ["tool-1"]})

        with patch("mcpgateway.main.export_service", export_service):
            result = await export_selective_configuration({"tools": ["tool-1"]}, include_dependencies=False, db=MagicMock(), user={"email": "user@example.com"})
            assert result["tools"] == ["tool-1"]

    async def test_export_selective_configuration_error_mappings(self, monkeypatch):
        import mcpgateway.main as main_mod
        from mcpgateway.services.export_service import ExportError

        svc = MagicMock()
        svc.export_selective = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(main_mod, "export_service", svc)

        result = await main_mod.export_selective_configuration.__wrapped__(
            {"tools": ["tool-1"]},
            include_dependencies=False,
            db=MagicMock(),
            user=SimpleNamespace(email="user@example.com"),
        )
        assert result["ok"] is True

        svc.export_selective = AsyncMock(side_effect=ExportError("bad"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.export_selective_configuration.__wrapped__({"tools": ["tool-1"]}, include_dependencies=False, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        svc.export_selective = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.export_selective_configuration.__wrapped__({"tools": ["tool-1"]}, include_dependencies=False, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 500

    async def test_import_configuration_invalid_strategy(self):
        import mcpgateway.main as main_mod

        with pytest.raises(HTTPException) as excinfo:
            # NOTE: main.py raises HTTPException(400) for invalid strategies, but
            # immediately wraps it in the outer Exception handler (500).
            await main_mod.import_configuration.__wrapped__(import_data={}, conflict_strategy="invalid", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 500
        assert "Invalid conflict strategy" in str(excinfo.value.detail)

    async def test_import_configuration_success(self):
        status = MagicMock()
        status.to_dict.return_value = {"status": "ok"}
        import_service = MagicMock()
        import_service.import_configuration = AsyncMock(return_value=status)

        with patch("mcpgateway.main.import_service", import_service):
            result = await import_configuration(import_data={"tools": []}, conflict_strategy="update", db=MagicMock(), user={"email": "user@example.com"})
            assert result["status"] == "ok"

    async def test_import_configuration_error_mappings(self, monkeypatch):
        import mcpgateway.main as main_mod
        from mcpgateway.services.import_service import ImportConflictError, ImportError as ImportServiceError, ImportValidationError

        request_import_status = MagicMock()
        request_import_status.to_dict.return_value = {"status": "ok"}

        svc = MagicMock()
        svc.import_configuration = AsyncMock(return_value=request_import_status)
        monkeypatch.setattr(main_mod, "import_service", svc)

        # Cover username=None branch by bypassing wrapper and using non-dict user.
        result = await main_mod.import_configuration.__wrapped__(import_data={"tools": []}, conflict_strategy="update", db=MagicMock(), user="basic-user")
        assert result["status"] == "ok"

        svc.import_configuration = AsyncMock(side_effect=ImportValidationError("bad"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.import_configuration.__wrapped__(import_data={"tools": []}, conflict_strategy="update", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 422

        svc.import_configuration = AsyncMock(side_effect=ImportConflictError("conflict"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.import_configuration.__wrapped__(import_data={"tools": []}, conflict_strategy="update", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 409

        svc.import_configuration = AsyncMock(side_effect=ImportServiceError("bad"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.import_configuration.__wrapped__(import_data={"tools": []}, conflict_strategy="update", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        svc.import_configuration = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.import_configuration.__wrapped__(import_data={"tools": []}, conflict_strategy="update", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 500


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

    async def test_message_endpoint_missing_session_id_raises_400(self):
        request = MagicMock(spec=Request)
        request.query_params = {}

        with pytest.raises(HTTPException) as excinfo:
            await message_endpoint(request, "server-1", user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

    async def test_message_endpoint_value_error_maps_to_400(self, monkeypatch):
        request = MagicMock(spec=Request)
        request.query_params = {"session_id": "session-1"}

        monkeypatch.setattr("mcpgateway.main._read_request_json", AsyncMock(side_effect=ValueError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await message_endpoint(request, "server-1", user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

    async def test_message_endpoint_elicitation_processing_error_falls_back_to_broadcast(self, monkeypatch):
        request = MagicMock(spec=Request)
        request.query_params = {"session_id": "session-1"}
        request.body = AsyncMock(return_value=json.dumps({"id": "req-1", "result": {"action": "accept", "content": ["not-a-dict"]}}).encode())

        elicitation_service = MagicMock()
        elicitation_service.complete_elicitation.return_value = True
        monkeypatch.setattr("mcpgateway.services.elicitation_service.get_elicitation_service", lambda: elicitation_service)

        broadcast = AsyncMock()
        monkeypatch.setattr("mcpgateway.main.session_registry.broadcast", broadcast)

        response = await message_endpoint(request, "server-1", user={"email": "user@example.com"})
        assert response.status_code == 202
        broadcast.assert_awaited_once()

    async def test_message_endpoint_elicitation_complete_false_broadcasts(self, monkeypatch):
        request = MagicMock(spec=Request)
        request.query_params = {"session_id": "session-1"}
        request.body = AsyncMock(return_value=json.dumps({"id": "req-1", "result": {"action": "accept", "content": {"foo": "bar"}}}).encode())

        elicitation_service = MagicMock()
        elicitation_service.complete_elicitation.return_value = False
        monkeypatch.setattr("mcpgateway.services.elicitation_service.get_elicitation_service", lambda: elicitation_service)

        broadcast = AsyncMock()
        monkeypatch.setattr("mcpgateway.main.session_registry.broadcast", broadcast)

        response = await message_endpoint(request, "server-1", user={"email": "user@example.com"})
        assert response.status_code == 202
        broadcast.assert_awaited_once()


class TestRemainingCoverageGaps:
    """Targeted unit tests for remaining uncovered main.py branches (per HTML coverage report)."""

    def test_get_db_invalidates_when_rollback_fails(self, monkeypatch):
        import mcpgateway.main as main_mod

        class FakeSession:  # noqa: D401 - test helper
            def __init__(self):
                self.is_active = True
                self.committed = False
                self.rolled_back = False
                self.invalidated = False
                self.closed = False

            def commit(self):  # noqa: D401 - test helper
                self.committed = True

            def rollback(self):  # noqa: D401 - test helper
                self.rolled_back = True
                raise RuntimeError("rollback failed")

            def invalidate(self):  # noqa: D401 - test helper
                self.invalidated = True
                raise RuntimeError("invalidate failed")

            def close(self):  # noqa: D401 - test helper
                self.closed = True

        sess = FakeSession()
        monkeypatch.setattr(main_mod, "SessionLocal", lambda: sess)

        gen = main_mod.get_db()
        assert next(gen) is sess
        with pytest.raises(RuntimeError, match="boom"):
            gen.throw(RuntimeError("boom"))

        assert sess.rolled_back is True
        assert sess.invalidated is True
        assert sess.closed is True

    def test_healthcheck_invalidate_failure_is_best_effort(self, monkeypatch):
        import mcpgateway.main as main_mod

        class FakeSession:  # noqa: D401 - test helper
            def __init__(self):
                self.closed = False

            def execute(self, _stmt):  # noqa: ANN001
                raise RuntimeError("db down")

            def commit(self):
                return None

            def rollback(self):
                raise RuntimeError("rollback failed")

            def invalidate(self):
                raise RuntimeError("invalidate failed")

            def close(self):
                self.closed = True

        sess = FakeSession()
        monkeypatch.setattr(main_mod, "SessionLocal", lambda: sess)

        result = main_mod.healthcheck()
        assert result["status"] == "unhealthy"
        assert "db down" in result["error"]
        assert sess.closed is True

    async def test_readiness_check_invalidate_failure_is_best_effort(self, monkeypatch):
        import mcpgateway.main as main_mod

        class FakeSession:  # noqa: D401 - test helper
            def execute(self, _stmt):  # noqa: ANN001
                raise RuntimeError("db down")

            def commit(self):
                return None

            def rollback(self):
                raise RuntimeError("rollback failed")

            def invalidate(self):
                raise RuntimeError("invalidate failed")

            def close(self):
                return None

        monkeypatch.setattr(main_mod, "SessionLocal", lambda: FakeSession())

        async def _to_thread(func, *args, **kwargs):  # noqa: ANN001
            return func(*args, **kwargs)

        monkeypatch.setattr(main_mod.asyncio, "to_thread", _to_thread)

        response = await main_mod.readiness_check()
        assert response.status_code == 503
        payload = json.loads(response.body.decode())
        assert payload["status"] == "not ready"

    async def test_sse_endpoint_cookie_auth_and_disconnect_cleanup(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {}  # no bearer
        request.cookies = {"jwt_token": "cookie-token"}
        request.scope = {"root_path": ""}

        transport = MagicMock()
        transport.session_id = "session-1"
        transport.connect = AsyncMock()

        async def _create_sse_response(_req, on_disconnect_callback=None):  # noqa: ANN001
            if on_disconnect_callback:
                await on_disconnect_callback()
            return StarletteResponse("ok")

        transport.create_sse_response = AsyncMock(side_effect=_create_sse_response)

        monkeypatch.setattr(main_mod, "update_url_protocol", lambda _req: "http://example.com")
        monkeypatch.setattr(main_mod, "_get_token_teams_from_request", lambda _req: [])
        monkeypatch.setattr(main_mod, "SSETransport", MagicMock(return_value=transport))
        monkeypatch.setattr(main_mod.session_registry, "add_session", AsyncMock())
        monkeypatch.setattr(main_mod.session_registry, "respond", AsyncMock(return_value=None))
        monkeypatch.setattr(main_mod.session_registry, "register_respond_task", MagicMock())
        remove_session = AsyncMock(return_value=None)
        monkeypatch.setattr(main_mod.session_registry, "remove_session", remove_session)

        # Cover user.is_admin attribute branch (cookie-authenticated user object).
        user = SimpleNamespace(email="user@example.com", is_admin=True)
        response = await main_mod.sse_endpoint.__wrapped__(request, "server-1", user=user)
        assert response.status_code == 200
        remove_session.assert_awaited_once()

    async def test_sse_endpoint_disconnect_cleanup_warns_on_failure(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {}  # no bearer
        request.cookies = {"access_token": "cookie-token"}
        request.scope = {"root_path": ""}

        transport = MagicMock()
        transport.session_id = "session-2"
        transport.connect = AsyncMock()

        async def _create_sse_response(_req, on_disconnect_callback=None):  # noqa: ANN001
            if on_disconnect_callback:
                await on_disconnect_callback()
            return StarletteResponse("ok")

        transport.create_sse_response = AsyncMock(side_effect=_create_sse_response)

        monkeypatch.setattr(main_mod, "update_url_protocol", lambda _req: "http://example.com")
        monkeypatch.setattr(main_mod, "_get_token_teams_from_request", lambda _req: [])
        monkeypatch.setattr(main_mod, "SSETransport", MagicMock(return_value=transport))
        monkeypatch.setattr(main_mod.session_registry, "add_session", AsyncMock())
        monkeypatch.setattr(main_mod.session_registry, "respond", AsyncMock(return_value=None))
        monkeypatch.setattr(main_mod.session_registry, "register_respond_task", MagicMock())
        monkeypatch.setattr(main_mod.session_registry, "remove_session", AsyncMock(side_effect=RuntimeError("fail")))

        user = SimpleNamespace(email="user@example.com", is_admin=False)
        response = await main_mod.sse_endpoint.__wrapped__(request, "server-1", user=user)
        assert response.status_code == 200

    async def test_list_servers_tags_team_mismatch_and_pagination(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id="team-1", token_teams=["team-1"])

        # Team mismatch path
        response = await main_mod.list_servers.__wrapped__(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id="team-2",
            visibility=None,
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert response.status_code == 403

        # Tags parsing + pagination payload
        request.state = SimpleNamespace(team_id=None, token_teams=["team-1"])
        server = MagicMock()
        server.model_dump.return_value = {"id": "srv-1"}
        list_servers = AsyncMock(return_value=([server], "next"))
        monkeypatch.setattr(main_mod.server_service, "list_servers", list_servers)

        result = await main_mod.list_servers.__wrapped__(
            request,
            cursor=None,
            include_pagination=True,
            limit=None,
            include_inactive=False,
            tags=" a, b ,,",
            team_id=None,
            visibility=None,
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert result["servers"] == [{"id": "srv-1"}]
        assert result["nextCursor"] == "next"
        assert list_servers.call_args.kwargs["tags"] == ["a", "b"]

    async def test_list_gateways_team_mismatch_and_pagination(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id="team-1", token_teams=["team-1"])

        response = await main_mod.list_gateways.__wrapped__(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            team_id="team-2",
            visibility=None,
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert response.status_code == 403

        request.state = SimpleNamespace(team_id=None, token_teams=["team-1"])
        gateway = MagicMock()
        gateway.model_dump.return_value = {"id": "gw-1"}
        list_gateways = AsyncMock(return_value=([gateway], "next"))
        monkeypatch.setattr(main_mod.gateway_service, "list_gateways", list_gateways)

        db = MagicMock()
        result = await main_mod.list_gateways.__wrapped__(
            request,
            cursor=None,
            include_pagination=True,
            limit=None,
            include_inactive=False,
            team_id=None,
            visibility=None,
            db=db,
            user={"email": "user@example.com"},
        )
        assert result["gateways"] == [{"id": "gw-1"}]
        assert result["nextCursor"] == "next"
        db.commit.assert_called()
        db.close.assert_called()

    async def test_read_resource_fallback_serialization_branches(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None)

        db = MagicMock()

        class DummyContent:  # noqa: D401 - test helper
            def __init__(self, uri, text=None):  # noqa: ANN001
                self.uri = uri
                if text is not None:
                    self.text = text

            def __str__(self):
                return "dummy"

        # Force ResourceContent/TextContent import to fail to hit fallback block.
        original_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
            if name == "mcpgateway.common.models":
                raise ImportError("forced")
            return original_import(name, globals, locals, fromlist, level)

        # 1) hasattr(content, "text") branch
        monkeypatch.setattr(builtins, "__import__", guarded_import)
        monkeypatch.setattr(main_mod.resource_service, "read_resource", AsyncMock(return_value=DummyContent("uri:1", text="hi")))
        result = await main_mod.read_resource.__wrapped__("res-1", request, db=db, user={"email": "user@example.com"})
        assert result["text"] == "hi"

        # 2) final fallback branch
        monkeypatch.setattr(main_mod.resource_service, "read_resource", AsyncMock(return_value=DummyContent("uri:2")))
        result = await main_mod.read_resource.__wrapped__("res-2", request, db=db, user={"email": "user@example.com"})
        assert result["text"] == "dummy"

    async def test_get_resource_info_success_and_not_found(self, monkeypatch):
        import mcpgateway.main as main_mod
        from mcpgateway.services.resource_service import ResourceNotFoundError

        ok = MagicMock()
        monkeypatch.setattr(main_mod.resource_service, "get_resource_by_id", AsyncMock(return_value=ok))
        result = await main_mod.get_resource_info.__wrapped__("res-1", include_inactive=False, db=MagicMock(), user={"email": "user@example.com"})
        assert result is ok

        monkeypatch.setattr(main_mod.resource_service, "get_resource_by_id", AsyncMock(side_effect=ResourceNotFoundError("missing")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_resource_info.__wrapped__("res-1", include_inactive=False, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

    async def test_get_import_status_found_and_not_found(self, monkeypatch):
        import mcpgateway.main as main_mod

        status_obj = MagicMock()
        status_obj.to_dict.return_value = {"status": "ok"}
        monkeypatch.setattr(main_mod.import_service, "get_import_status", MagicMock(return_value=status_obj))
        result = await main_mod.get_import_status.__wrapped__("import-1", user={"email": "user@example.com"})
        assert result["status"] == "ok"

        monkeypatch.setattr(main_mod.import_service, "get_import_status", MagicMock(return_value=None))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_import_status.__wrapped__("import-2", user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

    async def test_list_and_cleanup_import_statuses(self, monkeypatch):
        import mcpgateway.main as main_mod

        s1 = MagicMock()
        s1.to_dict.return_value = {"id": "1"}
        s2 = MagicMock()
        s2.to_dict.return_value = {"id": "2"}
        monkeypatch.setattr(main_mod.import_service, "list_import_statuses", MagicMock(return_value=[s1, s2]))
        result = await main_mod.list_import_statuses.__wrapped__(user={"email": "user@example.com"})
        assert result == [{"id": "1"}, {"id": "2"}]

        monkeypatch.setattr(main_mod.import_service, "cleanup_completed_imports", MagicMock(return_value=2))
        result = await main_mod.cleanup_import_statuses.__wrapped__(max_age_hours=1, user={"email": "user@example.com"})
        assert result["removed_count"] == 2

    async def test_create_server_public_only_restrictions_and_team_id(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = _make_request("/servers")
        request.state = SimpleNamespace(team_id="team-1", token_teams=[])
        server_obj = MagicMock()

        response = await main_mod.create_server.__wrapped__(
            server_obj,
            request,
            team_id=None,
            visibility="team",
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert response.status_code == 403

        request.state = SimpleNamespace(team_id="team-1", token_teams=["team-1"])
        response = await main_mod.create_server.__wrapped__(
            server_obj,
            request,
            team_id="team-2",
            visibility="team",
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert response.status_code == 403

        request.state = SimpleNamespace(team_id="team-1", token_teams=[])
        monkeypatch.setattr(
            main_mod.MetadataCapture,
            "extract_creation_metadata",
            lambda *_a, **_k: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )
        register = AsyncMock(return_value=server_obj)
        monkeypatch.setattr(main_mod.server_service, "register_server", register)
        db = MagicMock()
        _ = await main_mod.create_server.__wrapped__(
            server_obj,
            request,
            team_id="team-1",
            visibility="public",
            db=db,
            user={"email": "user@example.com"},
        )
        assert register.call_args.kwargs["team_id"] is None

    async def test_register_gateway_public_only_restrictions_and_validation_error(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = _make_request("/gateways")
        request.state = SimpleNamespace(team_id="team-1", token_teams=[])

        gateway_obj = SimpleNamespace(team_id="team-1", visibility="team")
        response = await main_mod.register_gateway.__wrapped__(gateway_obj, request, db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

        request.state = SimpleNamespace(team_id="team-1", token_teams=["team-1"])
        gateway_obj = SimpleNamespace(team_id="team-2", visibility="team")
        response = await main_mod.register_gateway.__wrapped__(gateway_obj, request, db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

        request.state = SimpleNamespace(team_id="team-1", token_teams=[])
        gateway_obj = SimpleNamespace(team_id="team-1", visibility="public")
        monkeypatch.setattr(
            main_mod.MetadataCapture,
            "extract_creation_metadata",
            lambda *_a, **_k: {"created_by": "user", "created_from_ip": "127.0.0.1", "created_via": "api", "created_user_agent": "test"},
        )
        register = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(main_mod.gateway_service, "register_gateway", register)
        _ = await main_mod.register_gateway.__wrapped__(gateway_obj, request, db=MagicMock(), user={"email": "user@example.com"})
        assert register.call_args.kwargs["team_id"] is None

        class FakeValidationError(Exception):
            """ValidationError branch in register_gateway is unreachable for pydantic.ValidationError (subclasses ValueError)."""

        monkeypatch.setattr(main_mod, "ValidationError", FakeValidationError)
        monkeypatch.setattr(main_mod.gateway_service, "register_gateway", AsyncMock(side_effect=FakeValidationError("bad")))
        monkeypatch.setattr(main_mod.ErrorFormatter, "format_validation_error", MagicMock(return_value={"detail": "bad"}))
        response = await main_mod.register_gateway.__wrapped__(gateway_obj, request, db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 422
        assert json.loads(response.body.decode()) == {"detail": "bad"}

    async def test_state_endpoints_error_branches(self, monkeypatch):
        import mcpgateway.main as main_mod
        from mcpgateway.services.gateway_service import GatewayNotFoundError
        from mcpgateway.services.prompt_service import PromptLockConflictError
        from mcpgateway.services.resource_service import ResourceLockConflictError
        from mcpgateway.services.server_service import ServerError, ServerLockConflictError

        monkeypatch.setattr(main_mod.server_service, "set_server_state", AsyncMock(side_effect=ServerLockConflictError("locked")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.set_server_state.__wrapped__("s1", activate=True, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 409

        monkeypatch.setattr(main_mod.server_service, "set_server_state", AsyncMock(side_effect=ServerError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.set_server_state.__wrapped__("s1", activate=True, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 400

        monkeypatch.setattr(main_mod.resource_service, "set_resource_state", AsyncMock(side_effect=ResourceLockConflictError("locked")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.set_resource_state.__wrapped__("r1", activate=True, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 409

        monkeypatch.setattr(main_mod.resource_service, "set_resource_state", AsyncMock(side_effect=RuntimeError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.set_resource_state.__wrapped__("r1", activate=True, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 400

        monkeypatch.setattr(main_mod.prompt_service, "set_prompt_state", AsyncMock(side_effect=PromptLockConflictError("locked")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.set_prompt_state.__wrapped__("p1", activate=True, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 409

        monkeypatch.setattr(main_mod.prompt_service, "set_prompt_state", AsyncMock(side_effect=RuntimeError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.set_prompt_state.__wrapped__("p1", activate=True, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 400

        monkeypatch.setattr(main_mod.gateway_service, "get_gateway", AsyncMock(side_effect=GatewayNotFoundError("missing")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_gateway.__wrapped__("gw-1", db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 404

        monkeypatch.setattr(main_mod.gateway_service, "set_gateway_state", AsyncMock(side_effect=RuntimeError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.set_gateway_state.__wrapped__("gw-1", activate=True, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 400

    async def test_delete_server_error_mappings(self, monkeypatch):
        import mcpgateway.main as main_mod
        from mcpgateway.services.server_service import ServerError

        monkeypatch.setattr(main_mod.server_service, "get_server", AsyncMock(return_value=None))
        monkeypatch.setattr(main_mod.server_service, "delete_server", AsyncMock(side_effect=PermissionError("nope")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_server.__wrapped__("s1", purge_metrics=False, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 403

        monkeypatch.setattr(main_mod.server_service, "delete_server", AsyncMock(side_effect=ServerError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_server.__wrapped__("s1", purge_metrics=False, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 400

    async def test_message_endpoints_generic_exception_mapping(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.query_params = {"session_id": "session-1"}

        monkeypatch.setattr(main_mod, "_read_request_json", AsyncMock(return_value={"hello": "world"}))
        monkeypatch.setattr(main_mod.session_registry, "broadcast", AsyncMock(side_effect=RuntimeError("boom")))

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.message_endpoint.__wrapped__(request, "server-1", user={"email": "u"})
        assert excinfo.value.status_code == 500

        request = MagicMock(spec=Request)
        request.query_params = {"session_id": "session-1"}
        monkeypatch.setattr(main_mod, "_read_request_json", AsyncMock(return_value={"hello": "world"}))
        monkeypatch.setattr(main_mod.session_registry, "broadcast", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.utility_message_endpoint.__wrapped__(request, user={"email": "u"})
        assert excinfo.value.status_code == 500

    async def test_list_tools_and_get_tool_jsonpath_modifier(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        tool = MagicMock()
        tool.to_dict.return_value = {"id": "t1"}
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", [], False))
        monkeypatch.setattr(main_mod.tool_service, "list_tools", AsyncMock(return_value=([tool], None)))
        monkeypatch.setattr(main_mod, "jsonpath_modifier", MagicMock(return_value={"filtered": True}))

        apijsonpath = SimpleNamespace(jsonpath="$", mapping={})
        result = await main_mod.list_tools.__wrapped__(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            gateway_id=None,
            db=MagicMock(),
            apijsonpath=apijsonpath,
            user={"email": "user@example.com"},
        )
        assert result == {"filtered": True}

        data = MagicMock()
        data.to_dict.return_value = {"id": "t1"}
        monkeypatch.setattr(main_mod.tool_service, "get_tool", AsyncMock(return_value=data))
        result = await main_mod.get_tool.__wrapped__("tool-1", request=request, db=MagicMock(), user={"email": "u"}, apijsonpath=apijsonpath)
        assert result == {"filtered": True}

    async def test_deprecated_toggle_endpoints(self, monkeypatch):
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod, "set_server_state", AsyncMock(return_value={"ok": True}))
        with pytest.warns(DeprecationWarning):
            assert await main_mod.toggle_server_status.__wrapped__("s1", True, MagicMock(), {"email": "u"}) == {"ok": True}

        monkeypatch.setattr(main_mod, "set_tool_state", AsyncMock(return_value={"ok": True}))
        with pytest.warns(DeprecationWarning):
            assert await main_mod.toggle_tool_status.__wrapped__("t1", True, MagicMock(), {"email": "u"}) == {"ok": True}

        monkeypatch.setattr(main_mod, "set_resource_state", AsyncMock(return_value={"ok": True}))
        with pytest.warns(DeprecationWarning):
            assert await main_mod.toggle_resource_status.__wrapped__("r1", True, MagicMock(), {"email": "u"}) == {"ok": True}

        monkeypatch.setattr(main_mod, "set_prompt_state", AsyncMock(return_value={"ok": True}))
        with pytest.warns(DeprecationWarning):
            assert await main_mod.toggle_prompt_status.__wrapped__("p1", True, MagicMock(), {"email": "u"}) == {"ok": True}

        monkeypatch.setattr(main_mod, "set_gateway_state", AsyncMock(return_value={"ok": True}))
        with pytest.warns(DeprecationWarning):
            assert await main_mod.toggle_gateway_status.__wrapped__("gw1", True, MagicMock(), {"email": "u"}) == {"ok": True}

        monkeypatch.setattr(main_mod, "set_a2a_agent_state", AsyncMock(return_value={"ok": True}))
        with pytest.warns(DeprecationWarning):
            assert await main_mod.toggle_a2a_agent_status.__wrapped__("a1", True, MagicMock(), {"email": "u"}) == {"ok": True}

    async def test_reset_metrics_a2a_agent_enabled_and_disabled(self, monkeypatch):
        import mcpgateway.main as main_mod

        a2a = MagicMock()
        a2a.reset_metrics = AsyncMock()
        monkeypatch.setattr(main_mod, "a2a_service", a2a)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_a2a_metrics_enabled", True)
        result = await main_mod.reset_metrics.__wrapped__(entity="a2a_agent", entity_id=123, db=MagicMock(), user={"email": "u"})
        assert result["status"] == "success"
        a2a.reset_metrics.assert_awaited_once()

        monkeypatch.setattr(main_mod, "a2a_service", None)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.reset_metrics.__wrapped__(entity="a2a_agent", entity_id=123, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 400

    async def test_get_prompt_no_args_not_found_and_permission(self, monkeypatch):
        import mcpgateway.main as main_mod
        from mcpgateway.services.prompt_service import PromptNotFoundError

        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None)

        monkeypatch.setattr(main_mod.prompt_service, "get_prompt", AsyncMock(side_effect=PromptNotFoundError("missing")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_prompt_no_args.__wrapped__(request, "p1", db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 404

        monkeypatch.setattr(main_mod.prompt_service, "get_prompt", AsyncMock(side_effect=PermissionError("nope")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_prompt_no_args.__wrapped__(request, "p1", db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 403

    async def test_list_resource_templates_token_teams_normalization(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        monkeypatch.setattr(main_mod.resource_service, "list_resource_templates", AsyncMock(return_value=[]))

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", None, True))
        result = await main_mod.list_resource_templates.__wrapped__(request, db=MagicMock(), include_inactive=False, tags="a, b", visibility=None, user={"email": "u"})
        assert result.resource_templates == []

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", None, False))
        result = await main_mod.list_resource_templates.__wrapped__(request, db=MagicMock(), include_inactive=False, tags=None, visibility=None, user={"email": "u"})
        assert result.resource_templates == []

    async def test_list_prompts_token_teams_normalization(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        list_prompts = AsyncMock(return_value=([], None))
        monkeypatch.setattr(main_mod.prompt_service, "list_prompts", list_prompts)

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", None, True))
        await main_mod.list_prompts.__wrapped__(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            db=MagicMock(),
            user={"email": "u"},
        )
        assert list_prompts.call_args.kwargs["user_email"] is None
        assert list_prompts.call_args.kwargs["token_teams"] is None

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", None, False))
        await main_mod.list_prompts.__wrapped__(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            db=MagicMock(),
            user={"email": "u"},
        )
        assert list_prompts.call_args.kwargs["token_teams"] == []

    async def test_server_get_resources_and_prompts_admin_bypass(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        resource = MagicMock()
        resource.model_dump.return_value = {"id": "r1"}
        monkeypatch.setattr(main_mod.resource_service, "list_server_resources", AsyncMock(return_value=[resource]))

        prompt = MagicMock()
        prompt.model_dump.return_value = {"id": "p1"}
        monkeypatch.setattr(main_mod.prompt_service, "list_server_prompts", AsyncMock(return_value=[prompt]))

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", None, True))
        result = await main_mod.server_get_resources.__wrapped__(request, "srv", include_inactive=False, db=MagicMock(), user={"email": "u"})
        assert result == [{"id": "r1"}]

        result = await main_mod.server_get_prompts.__wrapped__(request, "srv", include_inactive=False, db=MagicMock(), user={"email": "u"})
        assert result == [{"id": "p1"}]

    async def test_update_a2a_agent_service_unavailable_and_validation(self, monkeypatch):
        import mcpgateway.main as main_mod
        from pydantic import ValidationError

        request = _make_request("/a2a/a1")
        monkeypatch.setattr(
            main_mod.MetadataCapture,
            "extract_modification_metadata",
            lambda *_a, **_k: {"modified_by": "u", "modified_from_ip": "127.0.0.1", "modified_via": "api", "modified_user_agent": "test"},
        )

        monkeypatch.setattr(main_mod, "a2a_service", None)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.update_a2a_agent.__wrapped__("a1", MagicMock(), request, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 503

        validation = ValidationError.from_exception_data("A2AAgentUpdate", [{"type": "missing", "loc": ("name",), "msg": "Field required", "input": {}}])
        svc = MagicMock()
        svc.update_agent = AsyncMock(side_effect=validation)
        monkeypatch.setattr(main_mod, "a2a_service", svc)
        monkeypatch.setattr(main_mod.ErrorFormatter, "format_validation_error", MagicMock(return_value="bad"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.update_a2a_agent.__wrapped__("a1", MagicMock(), request, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 422

    async def test_module_level_router_registration_branches(self, monkeypatch):
        """Import main.py under unique name to cover module-level wiring branches."""
        from types import ModuleType

        from fastapi import APIRouter

        # Provide lightweight router modules to avoid importing heavy optional dependencies.
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.observability", ModuleType("mcpgateway.routers.observability"))
        sys.modules["mcpgateway.routers.observability"].router = APIRouter()

        # Force ImportError branches for optional routers.
        force_error = {
            "mcpgateway.routers.oauth_router",
            "mcpgateway.routers.reverse_proxy",
            "mcpgateway.routers.llmchat_router",
            "mcpgateway.routers.llm_admin_router",
            "mcpgateway.routers.llm_config_router",
            "mcpgateway.routers.llm_proxy_router",
            "mcpgateway.routers.toolops_router",
        }

        overrides = {
            "environment": "production",
            "allowed_origins": [],
            "compression_enabled": False,
            "validation_middleware_enabled": False,
            "email_auth_enabled": False,
            "security_logging_enabled": True,
            "observability_enabled": True,
            "db_query_log_enabled": True,
            "cache_type": "redis",
            "redis_url": "redis://localhost:6379",
            "structured_logging_enabled": False,
            "mcpgateway_a2a_enabled": False,
            "mcpgateway_tool_cancellation_enabled": False,
            "mcpgateway_admin_api_enabled": False,
            "mcpgateway_ui_enabled": False,
            "llmchat_enabled": True,
            "toolops_enabled": True,
        }

        mod = _import_fresh_main_module(monkeypatch, overrides=overrides, env={"PLUGINS_ENABLED": "true"}, force_import_error=force_error)

        # Allow the import-time bootstrap_db create_task (running-loop branch) to complete.
        await asyncio.sleep(0)

        # root_info exists only when UI is disabled.
        info = await mod.root_info()
        assert info["ui_enabled"] is False

    def test_jsonpath_modifier_defaults_when_jsonpath_missing(self):
        # jsonpath_modifier(None/""/0) should fall back to default "$[*]".
        assert jsonpath_modifier([{"a": 1}], jsonpath="") == {"a": 1}

    async def test_import_configuration_uses_user_email_attribute(self, monkeypatch):
        import mcpgateway.main as main_mod

        status_obj = MagicMock()
        status_obj.to_dict.return_value = {"status": "ok"}
        svc = MagicMock()
        svc.import_configuration = AsyncMock(return_value=status_obj)
        monkeypatch.setattr(main_mod, "import_service", svc)

        user = SimpleNamespace(email="obj@example.com")
        result = await main_mod.import_configuration.__wrapped__(
            import_data={"tools": []},
            conflict_strategy="update",
            dry_run=False,
            rekey_secret=None,
            selected_entities=None,
            db=MagicMock(),
            user=user,
        )
        assert result["status"] == "ok"
        assert svc.import_configuration.call_args.kwargs["imported_by"] == "obj@example.com"

    async def test_initialize_maps_orjson_decode_error(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        monkeypatch.setattr(main_mod, "_read_request_json", AsyncMock(side_effect=main_mod.orjson.JSONDecodeError("bad", "{}", 1)))

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.initialize(request, user="user@example.com")
        assert excinfo.value.status_code == 400

    async def test_update_server_name_conflict_maps_to_409(self, monkeypatch):
        import mcpgateway.main as main_mod
        from mcpgateway.services.server_service import ServerNameConflictError

        request = _make_request("/servers/s1")
        monkeypatch.setattr(
            main_mod.MetadataCapture,
            "extract_modification_metadata",
            lambda *_a, **_k: {"modified_by": "u", "modified_from_ip": "127.0.0.1", "modified_via": "api", "modified_user_agent": "test"},
        )
        monkeypatch.setattr(main_mod.server_service, "update_server", AsyncMock(side_effect=ServerNameConflictError("conflict")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.update_server.__wrapped__("s1", MagicMock(), request, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 409

    async def test_server_get_tools_public_only_default(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "t1"}

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", None, False))
        monkeypatch.setattr(main_mod.tool_service, "list_server_tools", AsyncMock(return_value=[tool]))

        result = await main_mod.server_get_tools.__wrapped__(request, "srv", include_inactive=False, include_metrics=False, db=MagicMock(), user={"email": "u"})
        assert result == [{"id": "t1"}]

    async def test_tag_endpoints_parse_entity_types(self, monkeypatch):
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.tag_service, "get_all_tags", AsyncMock(return_value=[]))
        _ = await main_mod.list_tags.__wrapped__("Tools, Servers", include_entities=False, db=MagicMock(), user={"email": "u"})

        monkeypatch.setattr(main_mod.tag_service, "get_entities_by_tag", AsyncMock(return_value=[]))
        _ = await main_mod.get_entities_by_tag.__wrapped__("tag-1", entity_types="Tools", db=MagicMock(), user={"email": "u"})

    async def test_get_a2a_agent_service_unavailable(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = _make_request("/a2a/a1")
        monkeypatch.setattr(main_mod, "a2a_service", None)

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_a2a_agent.__wrapped__("a1", request, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 503

    async def test_create_a2a_agent_public_only_sets_team_id_none(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = _make_request("/a2a")
        request.state = SimpleNamespace(team_id="team-1", token_teams=[])

        monkeypatch.setattr(
            main_mod.MetadataCapture,
            "extract_creation_metadata",
            lambda *_a, **_k: {
                "created_by": "u",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )
        svc = MagicMock()
        svc.register_agent = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(main_mod, "a2a_service", svc)

        _ = await main_mod.create_a2a_agent.__wrapped__(
            MagicMock(),
            request,
            team_id="team-1",
            visibility="public",
            db=MagicMock(),
            user={"email": "u"},
        )
        assert svc.register_agent.call_args.kwargs["team_id"] is None

    async def test_set_a2a_agent_state_service_unavailable(self, monkeypatch):
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod, "a2a_service", None)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.set_a2a_agent_state.__wrapped__("a1", activate=True, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 503

    async def test_delete_tool_not_found_maps_to_404(self, monkeypatch):
        import mcpgateway.main as main_mod
        from mcpgateway.services.tool_service import ToolNotFoundError

        monkeypatch.setattr(main_mod.tool_service, "delete_tool", AsyncMock(side_effect=ToolNotFoundError("missing")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_tool.__wrapped__("t1", purge_metrics=False, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 404

    async def test_create_resource_resource_error_maps_to_400(self, monkeypatch):
        import mcpgateway.main as main_mod
        from mcpgateway.services.resource_service import ResourceError

        request = _make_request("/resources")
        request.state = SimpleNamespace(team_id=None, token_teams=["team-1"])

        monkeypatch.setattr(
            main_mod.MetadataCapture,
            "extract_creation_metadata",
            lambda *_a, **_k: {
                "created_by": "u",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )
        monkeypatch.setattr(main_mod.resource_service, "register_resource", AsyncMock(side_effect=ResourceError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.create_resource.__wrapped__(MagicMock(), request, team_id=None, visibility="public", db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 400

    async def test_get_prompt_reraises_unhandled_exception(self, monkeypatch):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None)

        monkeypatch.setattr(main_mod.prompt_service, "get_prompt", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(RuntimeError, match="boom"):
            await main_mod.get_prompt.__wrapped__(request, "p1", args={}, db=MagicMock(), user={"email": "u"})

    def test_log_security_recommendations_skip_ssl_verify_line(self, monkeypatch):
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "skip_ssl_verify", True, raising=False)
        main_mod.log_security_recommendations({"secure_secrets": False, "auth_enabled": False})

    async def test_request_validation_exception_handler_ctx_non_dict(self):
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.url = SimpleNamespace(path="/tools")

        exc = MagicMock()
        exc.errors.return_value = [{"loc": ["body"], "msg": "bad", "ctx": "ctx-not-a-dict", "type": "value_error"}]

        response = await main_mod.request_validation_exception_handler(request, exc)
        assert response.status_code == 422

    async def test_update_gateway_validation_error_branch(self, monkeypatch):
        import mcpgateway.main as main_mod

        class FakeValidationError(Exception):
            """ValidationError branch in update_gateway is unreachable for pydantic.ValidationError (subclasses ValueError)."""

        request = _make_request("/gateways/gw1")
        monkeypatch.setattr(
            main_mod.MetadataCapture,
            "extract_modification_metadata",
            lambda *_a, **_k: {"modified_by": "u", "modified_from_ip": "127.0.0.1", "modified_via": "api", "modified_user_agent": "test"},
        )
        monkeypatch.setattr(main_mod, "ValidationError", FakeValidationError)
        monkeypatch.setattr(main_mod.gateway_service, "update_gateway", AsyncMock(side_effect=FakeValidationError("bad")))
        monkeypatch.setattr(main_mod.ErrorFormatter, "format_validation_error", MagicMock(return_value={"detail": "bad"}))

        response = await main_mod.update_gateway.__wrapped__("gw1", MagicMock(), request, db=MagicMock(), user={"email": "u"})
        assert response.status_code == 422
        assert json.loads(response.body.decode()) == {"detail": "bad"}

    async def test_lifespan_log_aggregation_timeout_and_cancellation(self, monkeypatch):
        import mcpgateway.main as main_mod

        def make_service():  # noqa: ANN001 - local test helper
            service = MagicMock()
            service.initialize = AsyncMock()
            service.shutdown = AsyncMock()
            return service

        # Minimal startup config: only metrics aggregation auto-start.
        monkeypatch.setattr(main_mod.settings, "mcp_session_pool_enabled", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_session_affinity_enabled", False)
        monkeypatch.setattr(main_mod.settings, "enable_header_passthrough", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_tool_cancellation_enabled", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_elicitation_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_buffer_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_cleanup_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_rollup_enabled", False)
        monkeypatch.setattr(main_mod.settings, "sso_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_enabled", True)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_auto_start", True)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_backfill_hours", 0)  # triggers early return in run_log_backfill
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_window_minutes", 0)

        # Patch services to keep startup/shutdown lightweight.
        monkeypatch.setattr(main_mod, "logging_service", make_service())
        monkeypatch.setattr(main_mod.logging_service, "configure_uvicorn_after_startup", MagicMock())
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
        monkeypatch.setattr(main_mod, "a2a_service", None)

        # External dependencies
        monkeypatch.setattr(main_mod, "get_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod, "close_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod, "validate_security_configuration", MagicMock())
        monkeypatch.setattr(main_mod, "init_telemetry", MagicMock())
        monkeypatch.setattr(main_mod, "refresh_slugs_on_startup", MagicMock())
        monkeypatch.setattr("mcpgateway.routers.llmchat_router.init_redis", AsyncMock())

        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.get_instance", AsyncMock())
        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.shutdown", AsyncMock())

        # Cache invalidation subscriber
        subscriber = MagicMock()
        subscriber.start = AsyncMock()
        subscriber.stop = AsyncMock()
        import mcpgateway.cache.registry_cache as registry_cache_mod

        monkeypatch.setattr(registry_cache_mod, "get_cache_invalidation_subscriber", MagicMock(return_value=subscriber))

        # Log aggregator
        log_aggregator = MagicMock()
        log_aggregator.aggregation_window_minutes = 1
        log_aggregator.backfill = MagicMock()
        log_aggregator.aggregate_all_components = MagicMock()
        monkeypatch.setattr(main_mod, "get_log_aggregator", MagicMock(return_value=log_aggregator))

        # Force TimeoutError in wait_for and ensure the coroutine is closed to avoid warnings.
        async def fake_wait_for(awaitable, timeout=None):  # noqa: ANN001
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise asyncio.TimeoutError()

        async def fake_to_thread(_func, *args, **kwargs):  # noqa: ANN001
            # Yield control so task cancellation hits an await point.
            await asyncio.sleep(0.05)
            return None

        monkeypatch.setattr(main_mod.asyncio, "wait_for", fake_wait_for)
        monkeypatch.setattr(main_mod.asyncio, "to_thread", fake_to_thread)

        async with main_mod.lifespan(main_mod.app):
            await asyncio.sleep(0)

    async def test_lifespan_log_aggregation_timeout_branch(self, monkeypatch):
        """Specifically hit the TimeoutError -> continue branch in run_log_aggregation_loop."""
        import mcpgateway.main as main_mod

        def make_service():  # noqa: ANN001 - local test helper
            service = MagicMock()
            service.initialize = AsyncMock()
            service.shutdown = AsyncMock()
            return service

        monkeypatch.setattr(main_mod.settings, "mcp_session_pool_enabled", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_session_affinity_enabled", False)
        monkeypatch.setattr(main_mod.settings, "enable_header_passthrough", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_tool_cancellation_enabled", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_elicitation_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_buffer_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_cleanup_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_rollup_enabled", False)
        monkeypatch.setattr(main_mod.settings, "sso_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_enabled", True)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_auto_start", True)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_backfill_hours", 0)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_window_minutes", 0)

        monkeypatch.setattr(main_mod, "logging_service", make_service())
        monkeypatch.setattr(main_mod.logging_service, "configure_uvicorn_after_startup", MagicMock())
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
        monkeypatch.setattr(main_mod, "a2a_service", None)

        monkeypatch.setattr(main_mod, "get_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod, "close_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod, "validate_security_configuration", MagicMock())
        monkeypatch.setattr(main_mod, "init_telemetry", MagicMock())
        monkeypatch.setattr(main_mod, "refresh_slugs_on_startup", MagicMock())
        monkeypatch.setattr("mcpgateway.routers.llmchat_router.init_redis", AsyncMock())

        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.get_instance", AsyncMock())
        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.shutdown", AsyncMock())

        subscriber = MagicMock()
        subscriber.start = AsyncMock()
        subscriber.stop = AsyncMock()
        import mcpgateway.cache.registry_cache as registry_cache_mod

        monkeypatch.setattr(registry_cache_mod, "get_cache_invalidation_subscriber", MagicMock(return_value=subscriber))

        log_aggregator = MagicMock()
        log_aggregator.aggregation_window_minutes = 1
        log_aggregator.backfill = MagicMock()
        log_aggregator.aggregate_all_components = MagicMock()
        monkeypatch.setattr(main_mod, "get_log_aggregator", MagicMock(return_value=log_aggregator))

        monkeypatch.setattr(main_mod.asyncio, "to_thread", AsyncMock(return_value=None))

        state = {"calls": 0}

        async def fake_wait_for(awaitable, timeout=None):  # noqa: ANN001
            state["calls"] += 1
            if hasattr(awaitable, "close"):
                awaitable.close()
            if state["calls"] == 1:
                raise asyncio.TimeoutError()
            await asyncio.sleep(0.01)
            return None

        monkeypatch.setattr(main_mod.asyncio, "wait_for", fake_wait_for)

        async with main_mod.lifespan(main_mod.app):
            # Give the aggregation loop a chance to hit wait_for at least once.
            await asyncio.sleep(0.05)

    async def test_lifespan_reraises_unexpected_startup_error(self, monkeypatch):
        import mcpgateway.main as main_mod

        # Keep startup/shutdown lightweight.
        monkeypatch.setattr(main_mod, "logging_service", MagicMock(initialize=AsyncMock(), shutdown=AsyncMock(), configure_uvicorn_after_startup=MagicMock()))
        monkeypatch.setattr(main_mod, "get_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod, "close_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod.settings, "mcp_session_pool_enabled", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_session_affinity_enabled", False)
        monkeypatch.setattr("mcpgateway.routers.llmchat_router.init_redis", AsyncMock())
        monkeypatch.setattr(main_mod, "init_telemetry", MagicMock())

        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.get_instance", AsyncMock())
        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.shutdown", AsyncMock())

        import mcpgateway.cache.registry_cache as registry_cache_mod

        subscriber = MagicMock()
        subscriber.stop = AsyncMock()
        monkeypatch.setattr(registry_cache_mod, "get_cache_invalidation_subscriber", MagicMock(return_value=subscriber))

        monkeypatch.setattr(main_mod, "shutdown_services", AsyncMock())
        monkeypatch.setattr(main_mod, "validate_security_configuration", MagicMock(side_effect=RuntimeError("boom")))

        with pytest.raises(RuntimeError, match="boom"):
            async with main_mod.lifespan(main_mod.app):
                pass

    async def test_module_level_structured_logging_and_static_mount_errors(self, monkeypatch):
        from types import ModuleType

        from fastapi import APIRouter

        # Keep router imports light.
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.observability", ModuleType("mcpgateway.routers.observability"))
        sys.modules["mcpgateway.routers.observability"].router = APIRouter()

        overrides = {
            "structured_logging_enabled": True,
            "mcpgateway_tool_cancellation_enabled": True,
            "mcpgateway_ui_enabled": True,
            "static_dir": "/tmp/definitely-missing-static-dir",
        }
        force_error = {
            "mcpgateway.routers.log_search",
            "mcpgateway.routers.cancellation_router",
        }

        mod = _import_fresh_main_module(monkeypatch, overrides=overrides, force_import_error=force_error)
        await asyncio.sleep(0)

        # Cover favicon redirect logic (only registered when UI is enabled).
        resp = await mod.favicon_redirect()
        assert resp.status_code == 301

    async def test_module_level_llm_and_toolops_router_success_paths(self, monkeypatch):
        from types import ModuleType

        from fastapi import APIRouter

        # Stub router modules so include_router executes without importing heavy deps.
        llmchat_mod = ModuleType("mcpgateway.routers.llmchat_router")
        llmchat_mod.llmchat_router = APIRouter()
        llmchat_mod.init_redis = AsyncMock()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.llmchat_router", llmchat_mod)

        llm_admin_mod = ModuleType("mcpgateway.routers.llm_admin_router")
        llm_admin_mod.llm_admin_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.llm_admin_router", llm_admin_mod)

        llm_config_mod = ModuleType("mcpgateway.routers.llm_config_router")
        llm_config_mod.llm_config_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.llm_config_router", llm_config_mod)

        llm_proxy_mod = ModuleType("mcpgateway.routers.llm_proxy_router")
        llm_proxy_mod.llm_proxy_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.llm_proxy_router", llm_proxy_mod)

        toolops_mod = ModuleType("mcpgateway.routers.toolops_router")
        toolops_mod.toolops_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.toolops_router", toolops_mod)

        overrides = {
            "llmchat_enabled": True,
            "toolops_enabled": True,
        }
        _ = _import_fresh_main_module(monkeypatch, overrides=overrides)

    async def test_module_level_email_auth_and_sso_success_and_error(self, monkeypatch):
        from types import ModuleType

        from fastapi import APIRouter

        auth_mod = ModuleType("mcpgateway.routers.auth")
        auth_mod.auth_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.auth", auth_mod)

        email_auth_mod = ModuleType("mcpgateway.routers.email_auth")
        email_auth_mod.email_auth_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.email_auth", email_auth_mod)

        sso_mod = ModuleType("mcpgateway.routers.sso")
        sso_mod.sso_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.sso", sso_mod)

        overrides = {"email_auth_enabled": True, "sso_enabled": True}
        _ = _import_fresh_main_module(monkeypatch, overrides=overrides)

        # Force ImportError for SSO router to hit error logging branch.
        _ = _import_fresh_main_module(monkeypatch, overrides=overrides, force_import_error={"mcpgateway.routers.sso"})

    async def test_module_level_auth_and_team_token_rbac_import_errors(self, monkeypatch):
        overrides = {"email_auth_enabled": True}
        force_error = {
            "mcpgateway.routers.auth",
            "mcpgateway.routers.teams",
            "mcpgateway.routers.tokens",
            "mcpgateway.routers.rbac",
        }
        _ = _import_fresh_main_module(monkeypatch, overrides=overrides, force_import_error=force_error)


@pytest.fixture
def auth_headers():
    """Default auth headers for testing."""
    return {"Authorization": "Bearer test_token"}
