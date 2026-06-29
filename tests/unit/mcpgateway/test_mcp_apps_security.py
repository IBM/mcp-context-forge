# -*- coding: utf-8 -*-
"""Security regression tests for MCP Apps."""

# Standard
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import orjson
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import MCPAppSession, Resource
from mcpgateway.common.models import TextContent, ToolResult
from mcpgateway.services.mcp_apps import (
    mcp_app_session_service,
    MCP_UI_EXTENSION,
    MCPAppsValidationError,
    validate_ui_resource,
)
from mcpgateway.services.resource_service import ResourceNotFoundError
from mcpgateway.services.tool_service import ToolError, ToolNotFoundError, ToolService


@pytest.fixture
def mock_db():
    """Mock database session."""
    return MagicMock(spec=Session)


@pytest.fixture
def valid_app_session(mock_db):
    """Create a valid AppBridge session."""
    session = MCPAppSession(
        id="test-session-id",
        mcp_session_id="mcp-session-123",
        user_email="user@example.com",
        server_id="server-123",
        resource_uri="ui://widgets/example",
        token_teams=["team1"],
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    return session


class TestUIResourceSecurity:
    """Security tests for ui:// resource access."""

    def _policy(self) -> dict:
        return {MCP_UI_EXTENSION: {"csp": {"default-src": ["'self'"]}, "sandbox": ["allow-scripts"]}}

    def test_unauthorized_ui_resource_read_when_disabled(self, monkeypatch):
        """ui:// resources should be rejected when MCP Apps are disabled."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", False)

        with pytest.raises(MCPAppsValidationError, match="MCP Apps UI resources are disabled"):
            validate_ui_resource("ui://widgets/example", "text/html", self._policy())

    def test_ui_resource_requires_text_html_mime(self, monkeypatch):
        """ui:// resources must use text/html MIME type."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

        with pytest.raises(MCPAppsValidationError, match="text/html MIME type"):
            validate_ui_resource("ui://widgets/example", "application/json", self._policy())

        with pytest.raises(MCPAppsValidationError, match="text/html MIME type"):
            validate_ui_resource("ui://widgets/example", None, self._policy())

    def test_ui_resource_requires_explicit_csp_and_sandbox(self, monkeypatch):
        """ui:// resources must carry explicit rendering policy."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

        with pytest.raises(MCPAppsValidationError, match="MCP Apps metadata"):
            validate_ui_resource("ui://widgets/example", "text/html", None)

        with pytest.raises(MCPAppsValidationError, match="CSP policy"):
            validate_ui_resource("ui://widgets/example", "text/html", {MCP_UI_EXTENSION: {"sandbox": ["allow-scripts"]}})

        with pytest.raises(MCPAppsValidationError, match="sandbox policy"):
            validate_ui_resource("ui://widgets/example", "text/html", {MCP_UI_EXTENSION: {"csp": {"default-src": ["'self'"]}}})

    def test_ui_resource_rejects_unsafe_csp(self, monkeypatch):
        """ui:// resources should reject unsafe CSP directives."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

        # Reject unsafe-inline for script-src
        with pytest.raises(MCPAppsValidationError, match="'unsafe-inline' is not allowed"):
            validate_ui_resource(
                "ui://widgets/example",
                "text/html",
                {MCP_UI_EXTENSION: {"csp": {"script-src": ["'unsafe-inline'"]}}},
            )

        # Reject wildcard sources
        with pytest.raises(MCPAppsValidationError, match="Wildcard CSP sources are not allowed"):
            validate_ui_resource(
                "ui://widgets/example",
                "text/html",
                {MCP_UI_EXTENSION: {"csp": {"default-src": ["*"]}}},
            )

        # Reject blocked source prefixes
        with pytest.raises(MCPAppsValidationError, match="Blocked MCP Apps CSP source"):
            validate_ui_resource(
                "ui://widgets/example",
                "text/html",
                {MCP_UI_EXTENSION: {"csp": {"script-src": ["javascript:alert(1)"]}}},
            )

        with pytest.raises(MCPAppsValidationError, match="'unsafe-eval' is not allowed"):
            validate_ui_resource(
                "ui://widgets/example",
                "text/html",
                {MCP_UI_EXTENSION: {"csp": {"script-src": ["'unsafe-eval'"]}, "sandbox": ["allow-scripts"]}},
            )

        with pytest.raises(MCPAppsValidationError, match="Unsupported MCP Apps sandbox token"):
            validate_ui_resource(
                "ui://widgets/example",
                "text/html",
                {MCP_UI_EXTENSION: {"csp": {"default-src": ["'self'"]}, "sandbox": ["allow-scripts", "allow-same-origin"]}},
            )


class FakeRequest:
    """Tiny request double for direct endpoint tests."""

    def __init__(self, body, headers: dict | None = None) -> None:
        self._body = body if isinstance(body, bytes) else orjson.dumps(body)
        self.headers = headers or {}
        self.query_params = {}
        self.state = SimpleNamespace()

    async def body(self) -> bytes:
        """Return the encoded request body."""
        return self._body


class TestAppBridgeEndpoints:
    """Endpoint-level AppBridge security tests."""

    def test_appbridge_routes_reject_unauthenticated_before_execution(self, monkeypatch):
        """Unauthenticated AppBridge requests should fail before resource or tool execution."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr(main_mod.settings, "auth_required", True)
        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", True)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_mcp_apps_enabled", True)
        monkeypatch.setattr("mcpgateway.middleware.rbac.settings.auth_required", True)
        monkeypatch.setattr("mcpgateway.middleware.rbac.settings.mcp_client_auth_enabled", True)
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

        route_app = FastAPI()
        route_app.include_router(main_mod.utility_router)
        client = TestClient(route_app, raise_server_exceptions=False)
        with (
            patch.object(main_mod.resource_service, "read_resource", new=AsyncMock()) as read_resource_mock,
            patch.object(main_mod.tool_service, "invoke_tool", new=AsyncMock()) as invoke_tool_mock,
        ):
            create_response = client.post(
                "/mcp/apps/sessions",
                json={"resourceUri": "ui://widgets/example", "serverId": "server-1"},
                headers={"mcp-session-id": "mcp-session-1"},
            )
            rpc_response = client.post(
                "/mcp/apps/sessions/app-session-1/rpc",
                json={"jsonrpc": "2.0", "id": "1", "method": "tools/call", "params": {"name": "helper"}},
                headers={"mcp-session-id": "mcp-session-1"},
            )
        client.close()

        assert create_response.status_code == 401
        assert rpc_response.status_code == 401
        read_resource_mock.assert_not_awaited()
        invoke_tool_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_execute_rpc_initialize_advertises_authorized_extensions(self, monkeypatch, mock_db):
        """Initialize should include extension capabilities for authorized callers."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        request = FakeRequest({})

        with patch.object(main_mod.session_registry, "handle_initialize_logic", new=AsyncMock(return_value={})):
            monkeypatch.setattr(main_mod.server_service, "get_server", AsyncMock(return_value=SimpleNamespace(id="server-1")))
            result = await main_mod._execute_rpc_initialize(
                request,
                mock_db,
                user={"email": "user@example.com"},
                params={},
                server_id="server-1",
                mcp_session_id="mcp-session-1",
            )

        assert MCP_UI_EXTENSION in result["capabilities"]["extensions"]

    @pytest.mark.asyncio
    async def test_execute_rpc_initialize_omits_extensions_for_unauthorized_server(self, monkeypatch, mock_db):
        """Initialize should not advertise MCP Apps for target servers the caller cannot see."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        monkeypatch.setattr(main_mod.server_service, "get_server", AsyncMock(side_effect=main_mod.ServerNotFoundError("not found")))
        request = FakeRequest({})

        with patch.object(main_mod.session_registry, "handle_initialize_logic", new=AsyncMock(return_value={"capabilities": {}})):
            result = await main_mod._execute_rpc_initialize(
                request,
                mock_db,
                user={"email": "user@example.com"},
                params={},
                server_id="server-1",
                mcp_session_id="mcp-session-1",
            )

        assert "extensions" not in result["capabilities"]

    @pytest.mark.asyncio
    async def test_execute_rpc_tools_call_requires_model_visible_tool(self, monkeypatch, mock_db):
        """Normal model-facing tools/call should pass the model-visible execution gate."""
        # First-Party
        from mcpgateway import main as main_mod

        request = FakeRequest({})
        request.state.plugin_context_table = None
        request.state.plugin_global_context = None
        monkeypatch.setattr(main_mod.settings, "mcpgateway_tool_cancellation_enabled", False)
        invoke_mock = AsyncMock(return_value={"content": []})
        monkeypatch.setattr(main_mod.tool_service, "invoke_tool", invoke_mock)

        await main_mod._execute_rpc_tools_call(
            request,
            mock_db,
            {"email": "user@example.com"},
            req_id="call-1",
            params={"name": "helper", "arguments": {}},
            lowered_request_headers={},
            server_id="server-1",
        )

        assert invoke_mock.await_args.kwargs["require_model_visible"] is True

    @pytest.mark.asyncio
    async def test_handle_rpc_mcp_prefix_methods_return_method_not_found(self, monkeypatch, mock_db):
        """MCP-prefixed methods should route through MCP method validation."""
        # First-Party
        from mcpgateway import main as main_mod

        request = FakeRequest({"jsonrpc": "2.0", "id": "ext-1", "method": "io.modelcontextprotocol/unknown", "params": {}})
        response = await main_mod._handle_rpc_authenticated(request, db=mock_db, user={"email": "user@example.com"})

        assert response["error"]["code"] == -32601
        assert response["id"] == "ext-1"

        request = FakeRequest({"jsonrpc": "2.0", "id": "ext-2", "method": "extensions/known", "params": {}})
        with patch("mcpgateway.services.mcp_method_registry.mcp_method_registry.is_known_method", return_value=True):
            response = await main_mod._handle_rpc_authenticated(request, db=mock_db, user={"email": "user@example.com"})

        assert response["error"]["code"] == -32601
        assert response["id"] == "ext-2"

    @pytest.mark.asyncio
    async def test_create_session_rejects_disabled_and_malformed_requests(self, monkeypatch, mock_db):
        """App session creation should reject disabled, malformed, and unbound requests."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", False)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.create_mcp_app_session.__wrapped__(request=FakeRequest({}), db=mock_db, user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        for request, expected_status in [
            (FakeRequest(b"{"), 400),
            (FakeRequest([]), 400),
            (FakeRequest({"resourceUri": "https://example.com/widget"}), 422),
            (FakeRequest({"resourceUri": "ui://widgets/example"}), 400),
        ]:
            with pytest.raises(HTTPException) as excinfo:
                await main_mod.create_mcp_app_session.__wrapped__(request=request, db=mock_db, user={"email": "user@example.com"})
            assert excinfo.value.status_code == expected_status

    @pytest.mark.asyncio
    async def test_create_session_requires_verified_mcp_session(self, monkeypatch, mock_db):
        """App sessions cannot be minted for arbitrary MCP session ids."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        request = FakeRequest(
            {"resourceUri": "ui://widgets/example", "serverId": "server-1"},
            headers={"mcp-session-id": "missing-session"},
        )

        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Session not found"))),
            patch.object(main_mod.resource_service, "read_resource", new=AsyncMock()) as read_mock,
        ):
            with pytest.raises(HTTPException) as excinfo:
                await main_mod.create_mcp_app_session.__wrapped__(request=request, db=mock_db, user={"email": "user@example.com"})
            read_mock.assert_not_awaited()

        assert excinfo.value.status_code == 404

    @pytest.mark.asyncio
    async def test_create_session_requires_server_id(self, monkeypatch, mock_db):
        """App sessions must be bound to a virtual server."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        request = FakeRequest({"resourceUri": "ui://widgets/example"}, headers={"mcp-session-id": "session-1"})

        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod.resource_service, "read_resource", new=AsyncMock()) as read_mock,
        ):
            with pytest.raises(HTTPException) as excinfo:
                await main_mod.create_mcp_app_session.__wrapped__(request=request, db=mock_db, user={"email": "user@example.com"})
            read_mock.assert_not_awaited()

        assert excinfo.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_session_uses_admin_bypass_scope_and_returns_payload(self, monkeypatch, mock_db):
        """Admin app sessions should use unrestricted resource lookup and return session metadata."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        expires_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        request = FakeRequest(
            {"resourceUri": "ui://widgets/example", "serverId": "server-1"},
            headers={"mcp-session-id": "mcp-session-1"},
        )
        app_session = SimpleNamespace(id="app-session-1", resource_uri="ui://widgets/example", server_id="server-1", expires_at=expires_at)

        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod, "get_rpc_filter_context", return_value=("admin@example.com", None, True)),
            patch.object(main_mod.resource_service, "read_resource", new=AsyncMock(return_value=SimpleNamespace())) as read_mock,
            patch.object(main_mod.mcp_app_session_service, "create_session", return_value=app_session) as create_mock,
        ):
            response = await main_mod.create_mcp_app_session.__wrapped__(request=request, db=mock_db, user={"email": "admin@example.com", "is_admin": True})

        read_mock.assert_awaited_once()
        assert read_mock.await_args.kwargs["user"] is None
        assert read_mock.await_args.kwargs["token_teams"] is None
        create_mock.assert_called_once()
        assert create_mock.call_args.kwargs["token_teams"] is None
        assert orjson.loads(response.body)["appSessionId"] == "app-session-1"

    @pytest.mark.asyncio
    async def test_create_session_rejects_user_without_email_after_resource_check(self, monkeypatch, mock_db):
        """App sessions require a concrete requester identity before persistence."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        request = FakeRequest(
            {"resourceUri": "ui://widgets/example", "serverId": "server-1"},
            headers={"mcp-session-id": "mcp-session-1"},
        )

        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod, "get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch.object(main_mod, "get_user_email", return_value=None),
            patch.object(main_mod.resource_service, "read_resource", new=AsyncMock(return_value=SimpleNamespace())),
            patch.object(main_mod.mcp_app_session_service, "create_session") as create_mock,
        ):
            with pytest.raises(HTTPException) as excinfo:
                await main_mod.create_mcp_app_session.__wrapped__(request=request, db=mock_db, user={})

        assert excinfo.value.status_code == 403
        create_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_session_denies_invisible_ui_resource_without_persisting(self, monkeypatch, mock_db):
        """Session creation should fail closed when the caller cannot read the UI resource."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        request = FakeRequest(
            {"resourceUri": "ui://widgets/private", "serverId": "server-1"},
            headers={"mcp-session-id": "mcp-session-1"},
        )

        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod, "get_rpc_filter_context", return_value=("user@example.com", ["team-1"], False)),
            patch.object(main_mod.resource_service, "read_resource", new=AsyncMock(side_effect=ResourceNotFoundError("Resource not found"))) as read_mock,
            patch.object(main_mod.mcp_app_session_service, "create_session") as create_mock,
        ):
            with pytest.raises(ResourceNotFoundError):
                await main_mod.create_mcp_app_session.__wrapped__(request=request, db=mock_db, user={"email": "user@example.com"})

        read_mock.assert_awaited_once()
        create_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_rpc_rejects_disabled_malformed_and_missing_session(self, monkeypatch, mock_db):
        """AppBridge RPC should reject disabled, malformed, unsupported, and unbound requests."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", False)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.handle_mcp_app_session_rpc.__wrapped__("app-session-1", request=FakeRequest({}), db=mock_db, user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.handle_mcp_app_session_rpc.__wrapped__("app-session-1", request=FakeRequest(b"{"), db=mock_db, user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.handle_mcp_app_session_rpc.__wrapped__("app-session-1", request=FakeRequest([]), db=mock_db, user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        result = await main_mod.handle_mcp_app_session_rpc.__wrapped__(
            "app-session-1",
            request=FakeRequest({"jsonrpc": "2.0", "id": "1", "method": "resources/read"}),
            db=mock_db,
            user={"email": "user@example.com"},
        )
        assert result["error"]["code"] == -32601

        result = await main_mod.handle_mcp_app_session_rpc.__wrapped__(
            "app-session-1",
            request=FakeRequest({"jsonrpc": "2.0", "id": "1", "method": "tools/call"}),
            db=mock_db,
            user={"email": "user@example.com"},
        )
        assert result["error"]["code"] == -32003

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("status_code", "jsonrpc_code"), [(404, -32002), (403, -32003)])
    async def test_rpc_maps_mcp_session_owner_failures_to_jsonrpc_errors(self, monkeypatch, mock_db, status_code, jsonrpc_code):
        """Session ownership failures should return JSON-RPC errors instead of invoking tools."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        request = FakeRequest(
            {"jsonrpc": "2.0", "id": "1", "method": "tools/call", "params": {"name": "helper"}},
            headers={"mcp-session-id": "mcp-session-1"},
        )

        with patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock(side_effect=HTTPException(status_code=status_code, detail="denied"))):
            result = await main_mod.handle_mcp_app_session_rpc.__wrapped__("app-session-1", request=request, db=mock_db, user={"email": "user@example.com"})

        assert result["error"]["code"] == jsonrpc_code
        assert result["error"]["message"] == "denied"

    @pytest.mark.asyncio
    async def test_rpc_rejects_missing_or_unusable_app_session_and_missing_tool_name(self, monkeypatch, mock_db, valid_app_session):
        """AppBridge RPC should reject missing app sessions, unbound sessions, and missing tool names."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        request = FakeRequest(
            {"jsonrpc": "2.0", "id": "1", "method": "tools/call", "params": {"name": "helper"}},
            headers={"mcp-session-id": "mcp-session-123"},
        )

        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod, "get_request_identity", return_value=("user@example.com", False)),
            patch.object(main_mod.mcp_app_session_service, "get_valid_session", return_value=None),
        ):
            result = await main_mod.handle_mcp_app_session_rpc.__wrapped__("missing", request=request, db=mock_db, user={"email": "user@example.com"})
        assert result["error"]["code"] == -32003

        unbound_session = SimpleNamespace(**{**valid_app_session.__dict__, "server_id": None})
        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod, "get_request_identity", return_value=("user@example.com", False)),
            patch.object(main_mod.mcp_app_session_service, "get_valid_session", return_value=unbound_session),
        ):
            result = await main_mod.handle_mcp_app_session_rpc.__wrapped__("app-session-1", request=request, db=mock_db, user={"email": "user@example.com"})
        assert result["error"]["code"] == -32003

        request = FakeRequest({"jsonrpc": "2.0", "id": "1", "method": "tools/call", "params": {}}, headers={"mcp-session-id": "mcp-session-123"})
        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod, "get_request_identity", return_value=("user@example.com", False)),
            patch.object(main_mod.mcp_app_session_service, "get_valid_session", return_value=valid_app_session),
        ):
            result = await main_mod.handle_mcp_app_session_rpc.__wrapped__("app-session-1", request=request, db=mock_db, user={"email": "user@example.com"})
        assert result["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_rpc_rejects_cross_server_request(self, monkeypatch, mock_db, valid_app_session):
        """AppBridge RPC cannot switch away from the session-bound server."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        request = FakeRequest(
            {"jsonrpc": "2.0", "id": "1", "method": "tools/call", "params": {"name": "helper", "serverId": "server-2"}},
            headers={"mcp-session-id": "mcp-session-123"},
        )

        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod, "get_request_identity", return_value=("user@example.com", False)),
            patch.object(main_mod.mcp_app_session_service, "get_valid_session", return_value=valid_app_session),
            patch.object(main_mod.tool_service, "invoke_tool", new=AsyncMock()) as invoke_mock,
        ):
            result = await main_mod.handle_mcp_app_session_rpc.__wrapped__("test-session-id", request=request, db=mock_db, user={"email": "user@example.com"})
            invoke_mock.assert_not_awaited()

        assert result["error"]["code"] == -32003

    @pytest.mark.asyncio
    async def test_rpc_invokes_bound_app_visible_tool_without_direct_proxy_header(self, monkeypatch, mock_db, valid_app_session):
        """AppBridge RPC uses the stored server id and requires app-visible resolution."""
        # First-Party
        from mcpgateway import main as main_mod

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        request = FakeRequest(
            {"jsonrpc": "2.0", "id": "1", "method": "tools/call", "params": {"name": "helper", "arguments": {"x": 1}}},
            headers={"mcp-session-id": "mcp-session-123", "X-Context-Forge-Gateway-Id": "gateway-1"},
        )

        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod, "get_request_identity", return_value=("user@example.com", False)),
            patch.object(main_mod.mcp_app_session_service, "get_valid_session", return_value=valid_app_session),
            patch.object(main_mod.tool_service, "invoke_tool", new=AsyncMock(return_value={"ok": True})) as invoke_mock,
        ):
            result = await main_mod.handle_mcp_app_session_rpc.__wrapped__("test-session-id", request=request, db=mock_db, user={"email": "user@example.com"})
            call_kwargs = invoke_mock.await_args.kwargs

        assert result["result"] == {"ok": True}
        assert call_kwargs["server_id"] == "server-123"
        assert call_kwargs["require_app_visible"] is True
        assert "x-context-forge-gateway-id" not in call_kwargs["request_headers"]

    @pytest.mark.asyncio
    async def test_rpc_serializes_model_dump_and_maps_tool_errors(self, monkeypatch, mock_db, valid_app_session):
        """AppBridge RPC should serialize Pydantic-like results and map tool failures."""
        # First-Party
        from cpex.framework.errors import PluginError, PluginViolationError
        from cpex.framework.models import PluginErrorModel, PluginViolation

        # First-Party
        from mcpgateway import main as main_mod

        class Dumpable:
            def model_dump(self, **kwargs):
                assert kwargs == {"by_alias": True, "exclude_none": True}
                return {"ok": True}

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        request = FakeRequest(
            {"jsonrpc": "2.0", "id": "1", "method": "tools/call", "params": {"name": "helper"}},
            headers={"mcp-session-id": "mcp-session-123"},
        )
        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod, "get_request_identity", return_value=("user@example.com", False)),
            patch.object(main_mod.mcp_app_session_service, "get_valid_session", return_value=valid_app_session),
            patch.object(main_mod.tool_service, "invoke_tool", new=AsyncMock(return_value=Dumpable())),
        ):
            result = await main_mod.handle_mcp_app_session_rpc.__wrapped__("app-session-1", request=request, db=mock_db, user={"email": "user@example.com"})
        assert result["result"] == {"ok": True}

        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod, "get_request_identity", return_value=("user@example.com", False)),
            patch.object(main_mod.mcp_app_session_service, "get_valid_session", return_value=valid_app_session),
            patch.object(main_mod.tool_service, "invoke_tool", new=AsyncMock(side_effect=ToolNotFoundError("missing"))),
        ):
            result = await main_mod.handle_mcp_app_session_rpc.__wrapped__("app-session-1", request=request, db=mock_db, user={"email": "user@example.com"})
        assert result["error"]["code"] == -32601

        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod, "get_request_identity", return_value=("user@example.com", False)),
            patch.object(main_mod.mcp_app_session_service, "get_valid_session", return_value=valid_app_session),
            patch.object(main_mod.tool_service, "invoke_tool", new=AsyncMock(side_effect=ToolError("tool failed"))),
        ):
            result = await main_mod.handle_mcp_app_session_rpc.__wrapped__("app-session-1", request=request, db=mock_db, user={"email": "user@example.com"})
        assert result["error"]["code"] == -32000

        violation = PluginViolation(reason="policy denied", description="blocked", code="DENIED", mcp_error_code=-32042)
        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod, "get_request_identity", return_value=("user@example.com", False)),
            patch.object(main_mod.mcp_app_session_service, "get_valid_session", return_value=valid_app_session),
            patch.object(main_mod.tool_service, "invoke_tool", new=AsyncMock(side_effect=PluginViolationError("blocked", violation=violation))),
        ):
            result = await main_mod.handle_mcp_app_session_rpc.__wrapped__("app-session-1", request=request, db=mock_db, user={"email": "user@example.com"})
        assert result["error"]["code"] == -32042

        plugin_error = PluginErrorModel(message="plugin crashed", plugin_name="test-plugin", code="CRASH", mcp_error_code=-32043)
        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod, "get_request_identity", return_value=("user@example.com", False)),
            patch.object(main_mod.mcp_app_session_service, "get_valid_session", return_value=valid_app_session),
            patch.object(main_mod.tool_service, "invoke_tool", new=AsyncMock(side_effect=PluginError(error=plugin_error))),
        ):
            result = await main_mod.handle_mcp_app_session_rpc.__wrapped__("app-session-1", request=request, db=mock_db, user={"email": "user@example.com"})
        assert result["error"]["code"] == -32043

        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod, "get_request_identity", return_value=("user@example.com", False)),
            patch.object(main_mod.mcp_app_session_service, "get_valid_session", return_value=valid_app_session),
            patch.object(main_mod.tool_service, "invoke_tool", new=AsyncMock(side_effect=ValueError("bad params"))),
        ):
            result = await main_mod.handle_mcp_app_session_rpc.__wrapped__("app-session-1", request=request, db=mock_db, user={"email": "user@example.com"})
        assert result["error"]["code"] == -32602

        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod, "get_request_identity", return_value=("user@example.com", False)),
            patch.object(main_mod.mcp_app_session_service, "get_valid_session", return_value=valid_app_session),
            patch.object(main_mod.tool_service, "invoke_tool", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            result = await main_mod.handle_mcp_app_session_rpc.__wrapped__("app-session-1", request=request, db=mock_db, user={"email": "user@example.com"})
        assert result["error"]["code"] == -32603


class TestAppBridgeSessionSecurity:
    """Security tests for AppBridge session validation."""

    def _persist_session(self, db, **overrides):
        """Persist an AppBridge session for predicate tests."""
        now = datetime.now(timezone.utc)
        values = {
            "id": "test-session-id",
            "mcp_session_id": "mcp-session-123",
            "user_email": "user@example.com",
            "server_id": "server-123",
            "resource_uri": "ui://widgets/example",
            "token_teams": ["team1"],
            "created_at": now,
            "expires_at": now + timedelta(minutes=15),
        }
        values.update(overrides)
        session = MCPAppSession(**values)
        db.add(session)
        db.commit()
        return session

    def test_session_lookup_returns_stored_token_scope(self, test_db):
        """Valid session lookup should return the stored token scope used by later tool authorization."""
        self._persist_session(test_db, id="scope-session", token_teams=["team1"])

        result = mcp_app_session_service.get_valid_session(
            test_db,
            app_session_id="scope-session",
            mcp_session_id="mcp-session-123",
            user_email="user@example.com",
            server_id="server-123",
            is_admin=False,
        )

        assert result is not None
        assert result.token_teams == ["team1"]

    def test_wrong_server_access_rejected(self, test_db):
        """AppBridge session should reject access from wrong server."""
        self._persist_session(test_db, id="wrong-server-session")

        result = mcp_app_session_service.get_valid_session(
            test_db,
            app_session_id="wrong-server-session",
            mcp_session_id="mcp-session-123",
            user_email="user@example.com",
            server_id="wrong-server-id",
            is_admin=False,
        )

        assert result is None

    def test_expired_session_rejected(self, test_db):
        """AppBridge session should reject expired sessions."""
        self._persist_session(
            test_db,
            id="expired-session",
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

        result = mcp_app_session_service.get_valid_session(
            test_db,
            app_session_id="expired-session",
            mcp_session_id="mcp-session-123",
            user_email="user@example.com",
            server_id="server-123",
            is_admin=False,
        )

        assert result is None

    def test_missing_session_rejected(self, test_db):
        """AppBridge session should reject missing session IDs."""
        result = mcp_app_session_service.get_valid_session(
            test_db,
            app_session_id="nonexistent-session",
            mcp_session_id="mcp-session-123",
            user_email="user@example.com",
            server_id="server-123",
            is_admin=False,
        )

        assert result is None

    def test_wrong_user_access_rejected(self, test_db):
        """AppBridge session should reject access from wrong user (non-admin)."""
        self._persist_session(test_db, id="wrong-user-session")

        result = mcp_app_session_service.get_valid_session(
            test_db,
            app_session_id="wrong-user-session",
            mcp_session_id="mcp-session-123",
            user_email="different-user@example.com",  # Wrong user
            server_id="server-123",
            is_admin=False,
        )

        assert result is None

    def test_admin_bypass_user_check(self, test_db):
        """Admin should be able to access any user's session."""
        self._persist_session(test_db, id="admin-bypass-session")

        result = mcp_app_session_service.get_valid_session(
            test_db,
            app_session_id="admin-bypass-session",
            mcp_session_id="mcp-session-123",
            user_email="different-user@example.com",  # Different user
            server_id="server-123",
            is_admin=True,  # Admin bypass
        )

        assert result is not None

    def test_create_session_rolls_back_on_commit_failure(self, mock_db):
        """Commit failures during session creation should be rolled back and surfaced."""
        mock_db.commit.side_effect = RuntimeError("commit failed")

        with pytest.raises(RuntimeError, match="commit failed"):
            mcp_app_session_service.create_session(
                mock_db,
                mcp_session_id="mcp-session-123",
                user_email="user@example.com",
                server_id="server-123",
                resource_uri="ui://widgets/example",
                token_teams=["team1"],
            )

        mock_db.rollback.assert_called_once()

    def test_cleanup_expired_sessions_deletes_only_expired_rows(self, test_db):
        """Expired AppBridge sessions should have an explicit cleanup path."""
        test_db.query(MCPAppSession).delete()
        test_db.commit()
        now = datetime.now(timezone.utc)
        self._persist_session(test_db, id="cleanup-expired", expires_at=now - timedelta(seconds=1))
        self._persist_session(test_db, id="cleanup-active", expires_at=now + timedelta(minutes=5))

        deleted_count = mcp_app_session_service.cleanup_expired_sessions(test_db, now=now)

        assert deleted_count == 1
        assert test_db.get(MCPAppSession, "cleanup-expired") is None
        assert test_db.get(MCPAppSession, "cleanup-active") is not None


class TestAppOnlyToolSecurity:
    """Security tests for app-only helper tool access."""

    def test_app_only_tool_hidden_from_model_context(self, monkeypatch):
        """App-only tools should not appear in model-facing tools/list."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

        # First-Party
        from mcpgateway.services.mcp_apps import filter_model_visible_tools

        model_tool = SimpleNamespace(
            name="model_tool",
            extension_metadata={MCP_UI_EXTENSION: {"audience": ["model"]}},
        )
        app_only_tool = SimpleNamespace(
            name="app_helper",
            extension_metadata={MCP_UI_EXTENSION: {"audience": ["app"]}},
        )
        both_tool = SimpleNamespace(
            name="both_tool",
            extension_metadata={MCP_UI_EXTENSION: {"audience": ["model", "app"]}},
        )

        tools = [model_tool, app_only_tool, both_tool]
        filtered = filter_model_visible_tools(tools)

        assert len(filtered) == 2
        assert model_tool in filtered
        assert both_tool in filtered
        assert app_only_tool not in filtered

    def test_app_only_tool_requires_valid_session(self, monkeypatch):
        """App-only tools should only be callable through valid AppBridge session."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

        # First-Party
        from mcpgateway.services.mcp_apps import is_app_visible_tool

        app_only_tool = SimpleNamespace(
            name="app_helper",
            extension_metadata={MCP_UI_EXTENSION: {"audience": ["app"]}},
        )

        # Tool is app-visible
        assert is_app_visible_tool(app_only_tool) is True

        # But actual invocation requires valid session (tested in integration tests)

    @pytest.mark.asyncio
    async def test_invoke_tool_require_app_visible_rejects_model_only_tool(self, monkeypatch, mock_db):
        """Service-layer AppBridge gate denies the actual resolved model-only tool."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        service = ToolService()
        model_only_tool = SimpleNamespace(
            id="tool-1",
            name="helper",
            original_name="helper",
            url=None,
            description="",
            original_description="",
            integration_type="MCP",
            request_type="SSE",
            headers={},
            input_schema={"type": "object"},
            output_schema=None,
            annotations={},
            extension_metadata={MCP_UI_EXTENSION: {"audience": ["model"]}},
            auth_type=None,
            jsonpath_filter=None,
            custom_name=None,
            custom_name_slug=None,
            display_name=None,
            gateway_id=None,
            grpc_service_id=None,
            enabled=True,
            deprecated=False,
            reachable=True,
            tags=[],
            team_id=None,
            owner_email="user@example.com",
            visibility="public",
            query_mapping=None,
            header_mapping=None,
            gateway=None,
        )
        cache = SimpleNamespace(enabled=False, set=AsyncMock(), set_negative=AsyncMock())

        monkeypatch.setattr("mcpgateway.services.tool_service._get_tool_lookup_cache", lambda: cache)
        monkeypatch.setattr(service, "_load_invocable_tools", lambda db, name, server_id=None: [model_only_tool])
        monkeypatch.setattr(service, "_check_tool_access", AsyncMock(return_value=True))

        with pytest.raises(ToolNotFoundError):
            await service.invoke_tool(mock_db, "helper", {}, user_email="user@example.com", server_id="server-1", require_app_visible=True)

    @pytest.mark.asyncio
    async def test_invoke_tool_require_model_visible_rejects_app_only_tool(self, monkeypatch, mock_db):
        """Service-layer model gate denies app-only helper tools outside AppBridge."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        service = ToolService()
        app_only_tool = SimpleNamespace(
            id="tool-1",
            name="helper",
            original_name="helper",
            url=None,
            description="",
            original_description="",
            integration_type="MCP",
            request_type="SSE",
            headers={},
            input_schema={"type": "object"},
            output_schema=None,
            annotations={},
            extension_metadata={MCP_UI_EXTENSION: {"audience": ["app"]}},
            auth_type=None,
            jsonpath_filter=None,
            custom_name=None,
            custom_name_slug=None,
            display_name=None,
            gateway_id=None,
            grpc_service_id=None,
            enabled=True,
            deprecated=False,
            reachable=True,
            tags=[],
            team_id=None,
            owner_email="user@example.com",
            visibility="public",
            query_mapping=None,
            header_mapping=None,
            gateway=None,
        )
        cache = SimpleNamespace(enabled=False, set=AsyncMock(), set_negative=AsyncMock())

        monkeypatch.setattr("mcpgateway.services.tool_service._get_tool_lookup_cache", lambda: cache)
        monkeypatch.setattr(service, "_load_invocable_tools", lambda db, name, server_id=None: [app_only_tool])
        monkeypatch.setattr(service, "_check_tool_access", AsyncMock(return_value=True))

        with pytest.raises(ToolNotFoundError):
            await service.invoke_tool(mock_db, "helper", {}, user_email="user@example.com", server_id="server-1", require_model_visible=True)

    @pytest.mark.asyncio
    async def test_app_only_tool_visibility_split_end_to_end(self, monkeypatch, mock_db, valid_app_session):
        """One app-only tool should be hidden from model discovery, denied normally, and accepted through AppBridge."""
        # First-Party
        from mcpgateway import main as main_mod
        from mcpgateway.main import _serialize_mcp_tool_definitions

        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
        app_only_tool = SimpleNamespace(
            id="tool-app-only",
            name="helper",
            original_name="helper",
            url=None,
            description="",
            original_description="",
            integration_type="MCP",
            request_type="SSE",
            headers={},
            input_schema={"type": "object"},
            output_schema=None,
            annotations={},
            extension_metadata={MCP_UI_EXTENSION: {"audience": ["app"]}},
            auth_type=None,
            jsonpath_filter=None,
            custom_name=None,
            custom_name_slug=None,
            display_name=None,
            gateway_id=None,
            grpc_service_id=None,
            enabled=True,
            deprecated=False,
            reachable=True,
            tags=[],
            team_id=None,
            owner_email="user@example.com",
            visibility="public",
            query_mapping=None,
            header_mapping=None,
            gateway=None,
        )

        assert _serialize_mcp_tool_definitions([app_only_tool]) == []

        service = ToolService()
        cache = SimpleNamespace(enabled=False, set=AsyncMock(), set_negative=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.tool_service._get_tool_lookup_cache", lambda: cache)
        monkeypatch.setattr(service, "_load_invocable_tools", lambda db, name, server_id=None: [app_only_tool])
        monkeypatch.setattr(service, "_check_tool_access", AsyncMock(return_value=True))
        with pytest.raises(ToolNotFoundError):
            await service.invoke_tool(mock_db, "helper", {}, user_email="user@example.com", server_id="server-1", require_model_visible=True)

        request = FakeRequest(
            {"jsonrpc": "2.0", "id": "1", "method": "tools/call", "params": {"name": "helper", "arguments": {}}},
            headers={"mcp-session-id": "mcp-session-123"},
        )
        with (
            patch.object(main_mod, "_assert_session_owner_or_admin", new=AsyncMock()),
            patch.object(main_mod, "get_request_identity", return_value=("user@example.com", False)),
            patch.object(main_mod.mcp_app_session_service, "get_valid_session", return_value=valid_app_session),
            patch.object(main_mod.tool_service, "invoke_tool", new=AsyncMock(return_value=ToolResult(content=[TextContent(type="text", text="ok")]))) as invoke_mock,
        ):
            result = await main_mod.handle_mcp_app_session_rpc.__wrapped__("app-session-1", request=request, db=mock_db, user={"email": "user@example.com"})

        assert result["result"]["content"][0]["text"] == "ok"
        assert invoke_mock.await_args.kwargs["require_app_visible"] is True
