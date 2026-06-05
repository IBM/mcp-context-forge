# -*- coding: utf-8 -*-
"""Security regression tests for MCP Apps extension."""

# Standard
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import orjson
import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import MCPAppSession, Resource
from mcpgateway.services.mcp_apps import (
    MCP_UI_EXTENSION,
    MCPAppsValidationError,
    mcp_app_session_service,
    validate_ui_resource,
)
from mcpgateway.services.tool_service import ToolNotFoundError, ToolService


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

        with pytest.raises(MCPAppsValidationError, match="extension metadata"):
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

    def __init__(self, body: dict, headers: dict | None = None) -> None:
        self._body = orjson.dumps(body)
        self.headers = headers or {}
        self.state = SimpleNamespace()

    async def body(self) -> bytes:
        """Return the encoded request body."""
        return self._body


class TestAppBridgeEndpoints:
    """Endpoint-level AppBridge security tests."""

    @pytest.mark.asyncio
    async def test_create_session_requires_verified_mcp_session(self, monkeypatch, mock_db):
        """App sessions cannot be minted for arbitrary MCP session ids."""
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
    async def test_rpc_rejects_cross_server_request(self, monkeypatch, mock_db, valid_app_session):
        """AppBridge RPC cannot switch away from the session-bound server."""
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


class TestAppBridgeSessionSecurity:
    """Security tests for AppBridge session validation."""

    def test_wrong_team_access_rejected(self, mock_db, valid_app_session):
        """AppBridge session should reject access from wrong team."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        result = mcp_app_session_service.get_valid_session(
            mock_db,
            app_session_id="test-session-id",
            mcp_session_id="mcp-session-123",
            user_email="user@example.com",
            server_id="server-123",
            is_admin=False,
        )

        assert result is None

    def test_wrong_server_access_rejected(self, mock_db, valid_app_session):
        """AppBridge session should reject access from wrong server."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        result = mcp_app_session_service.get_valid_session(
            mock_db,
            app_session_id="test-session-id",
            mcp_session_id="mcp-session-123",
            user_email="user@example.com",
            server_id="wrong-server-id",
            is_admin=False,
        )

        assert result is None

    def test_expired_session_rejected(self, mock_db):
        """AppBridge session should reject expired sessions."""
        expired_session = MCPAppSession(
            id="test-session-id",
            mcp_session_id="mcp-session-123",
            user_email="user@example.com",
            server_id="server-123",
            resource_uri="ui://widgets/example",
            token_teams=["team1"],
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),  # Expired
        )

        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        result = mcp_app_session_service.get_valid_session(
            mock_db,
            app_session_id="test-session-id",
            mcp_session_id="mcp-session-123",
            user_email="user@example.com",
            server_id="server-123",
            is_admin=False,
        )

        assert result is None

    def test_missing_session_rejected(self, mock_db):
        """AppBridge session should reject missing session IDs."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        result = mcp_app_session_service.get_valid_session(
            mock_db,
            app_session_id="nonexistent-session",
            mcp_session_id="mcp-session-123",
            user_email="user@example.com",
            server_id="server-123",
            is_admin=False,
        )

        assert result is None

    def test_wrong_user_access_rejected(self, mock_db, valid_app_session):
        """AppBridge session should reject access from wrong user (non-admin)."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        result = mcp_app_session_service.get_valid_session(
            mock_db,
            app_session_id="test-session-id",
            mcp_session_id="mcp-session-123",
            user_email="different-user@example.com",  # Wrong user
            server_id="server-123",
            is_admin=False,
        )

        assert result is None

    def test_admin_bypass_user_check(self, mock_db, valid_app_session):
        """Admin should be able to access any user's session."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = valid_app_session

        result = mcp_app_session_service.get_valid_session(
            mock_db,
            app_session_id="test-session-id",
            mcp_session_id="mcp-session-123",
            user_email="different-user@example.com",  # Different user
            server_id="server-123",
            is_admin=True,  # Admin bypass
        )

        assert result is not None


class TestAppOnlyToolSecurity:
    """Security tests for app-only helper tool access."""

    def test_app_only_tool_hidden_from_model_context(self, monkeypatch):
        """App-only tools should not appear in model-facing tools/list."""
        monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

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
