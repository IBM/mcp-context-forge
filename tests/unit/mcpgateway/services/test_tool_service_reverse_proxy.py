# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_service_reverse_proxy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for PROXIED gateway dispatch in ToolService.invoke_tool() (reverse-proxy Phase 3).

A PROXIED gateway persists no auth material and no reachable URL: tool dispatch
resolves the process-local reverse-proxy WebSocket connection for the persisted
stable gateway ID and sends a ``tools/call`` JSON-RPC request using the persisted
``original_name`` (never the namespaced public name). All failure modes fail
closed through the existing MCP-path error taxonomy.
"""

# Standard
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from urllib.parse import urlparse

# Third-Party
import pytest
from pydantic import ValidationError

# First-Party
from mcpgateway.cache.tool_lookup_cache import tool_lookup_cache
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Tool as DbTool
from mcpgateway.services.reverse_proxy_protocol import JsonRpcErrorResponse, JsonRpcSuccessResponse, ResponseMessage
from mcpgateway.services.reverse_proxy_sessions import ConnectionClosedError, ConnectionId, ConnectionNotFoundError
from mcpgateway.services.tool_service import TextContent, ToolInvocationError, ToolNotFoundError, ToolResult, ToolService, ToolTimeoutError

PROXIED_TOOL_NAME = "proxied-gateway-upstream-echo"
PROXIED_ORIGINAL_NAME = "upstream_echo"
PROXIED_RESULT = {"content": [{"type": "text", "text": "proxied ok"}], "isError": False}


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes during tests."""
    with patch("mcpgateway.services.tool_service.audit_trail") as mock_audit, patch("mcpgateway.services.tool_service.structured_logger") as mock_logger:
        mock_audit.log_action = MagicMock(return_value=None)
        mock_logger.log = MagicMock(return_value=None)
        yield {"audit_trail": mock_audit, "structured_logger": mock_logger}


@pytest.fixture(autouse=True)
def mock_fresh_db_session():
    """Mock fresh_db_session so invoke_tool metrics recording never touches a real DB."""

    @contextmanager
    def mock_fresh_session():
        yield MagicMock()

    with patch("mcpgateway.services.tool_service.fresh_db_session", mock_fresh_session):
        yield


@pytest.fixture(autouse=True)
def reset_tool_lookup_cache():
    """Clear tool lookup cache between tests to avoid cross-test pollution."""
    tool_lookup_cache.invalidate_all_local()
    yield
    tool_lookup_cache.invalidate_all_local()


@pytest.fixture
def tool_service(monkeypatch):
    """Create a tool service instance with SSRF pinning disabled (mirrors test_tool_service.py)."""

    async def validate_without_pinning(value: str, _field_name: str = "URL"):
        parsed = urlparse(value)
        return {
            "validated_url": value,
            "hostname": parsed.hostname,
            "original_authority": parsed.netloc,
            "resolved_ip": None,
        }

    monkeypatch.setattr("mcpgateway.services.tool_service.SecurityValidator.validate_url_for_connection_pinning", validate_without_pinning)
    monkeypatch.setattr("mcpgateway.services.tool_service.settings.ssrf_protection_enabled", False)
    service = ToolService()
    service._http_client = AsyncMock()
    return service


@pytest.fixture
def proxied_gateway():
    """Create a PROXIED gateway model: no auth material, transport is the dispatch authority."""
    gateway = MagicMock(spec=DbGateway)
    gateway.id = "proxied-gw-1"
    gateway.name = "proxied_gateway"
    gateway.slug = "proxied-gateway"
    gateway.url = "reverse-proxy://local"
    gateway.description = "Reverse-proxied gateway"
    gateway.transport = "PROXIED"
    gateway.capabilities = {"tools": {"listChanged": True}}
    gateway.passthrough_headers = []
    gateway.auth_type = None
    gateway.auth_value = None
    gateway.auth_query_params = None
    gateway.oauth_config = None
    gateway.ca_certificate = None
    gateway.ca_certificate_sig = None
    gateway.client_cert = None
    gateway.client_key = None
    gateway.signing_algorithm = None
    gateway.team_id = None
    gateway.owner_email = "admin@example.com"
    gateway.visibility = "public"
    gateway.tags = []
    gateway.enabled = True
    gateway.reachable = True
    return gateway


@pytest.fixture
def proxied_tool(proxied_gateway):
    """Create an MCP tool synced from a PROXIED gateway (request_type stays the D7 placeholder)."""
    tool = MagicMock(spec=DbTool)
    tool.id = "tool-1"
    tool.original_name = PROXIED_ORIGINAL_NAME
    tool.name = PROXIED_TOOL_NAME
    tool.custom_name = PROXIED_ORIGINAL_NAME
    tool.custom_name_slug = "upstream-echo"
    tool.display_name = None
    tool.url = "reverse-proxy://local/tools/upstream_echo"
    tool.description = "Proxied tool"
    tool.original_description = "Proxied tool"
    tool.integration_type = "MCP"
    tool.request_type = "SSE"  # D7: schema-valid placeholder; dispatch keys off gateway transport
    tool.headers = {}
    tool.input_schema = {"type": "object", "properties": {"param": {"type": "string"}}}
    tool.output_schema = None
    tool.annotations = {}
    tool.extension_metadata = None
    tool.jsonpath_filter = ""
    tool.auth_type = None
    tool.auth_value = None
    tool.gateway_id = proxied_gateway.id
    tool.gateway = proxied_gateway
    tool.gateway_slug = proxied_gateway.slug
    tool.grpc_service_id = None
    tool.team_id = None
    tool.owner_email = "admin@example.com"
    tool.visibility = "public"
    tool.tags = []
    tool.enabled = True
    tool.deprecated = False
    tool.reachable = True
    tool.query_mapping = None
    tool.header_mapping = None
    tool.created_via = "reverse_proxy"
    return tool


def _stub_db_execute(test_db, *values):
    """Point test_db.execute at canned rows, mirroring test_tool_service.py invoke fixtures."""
    returns = list(values)

    def execute_side_effect(*_args, **_kwargs):
        value = returns.pop(0) if returns else None
        result = Mock()
        result.scalar_one_or_none.return_value = value
        result.scalars.return_value = result
        result.all.return_value = [] if value is None else [value]
        return result

    test_db.execute = Mock(side_effect=execute_side_effect)


def _success_response(request_id: str, result: dict) -> ResponseMessage:
    """Build a JSON-RPC success response frame carrying a CallToolResult payload."""
    return ResponseMessage(type="response", payload=JsonRpcSuccessResponse.model_validate({"jsonrpc": "2.0", "id": request_id, "result": result}))


def _error_response(request_id: str, code: int, message: str) -> ResponseMessage:
    """Build a JSON-RPC error response frame."""
    return ResponseMessage(type="response", payload=JsonRpcErrorResponse.model_validate({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}))


def _manager_mock(connection_id=ConnectionId("conn-1"), send_return=None, send_side_effect=None):
    """Build a reverse-proxy session manager mock with a fixed stable-ID resolution."""
    manager = MagicMock()
    manager.resolve_connection_id = Mock(return_value=connection_id)
    if send_side_effect is not None:
        manager.send_request = AsyncMock(side_effect=send_side_effect)
    else:
        manager.send_request = AsyncMock(return_value=send_return)
    return manager


def _structured_log_events(mock_logger):
    """Index structured-log metadata by event name for assertion."""
    return {logged_call.kwargs["metadata"].get("event"): logged_call.kwargs["metadata"] for logged_call in mock_logger.log.call_args_list if isinstance(logged_call.kwargs.get("metadata"), dict)}


def _structured_log_call_kwargs(mock_logger, event_name):
    """Return kwargs for the first matching structured-log event, or None."""
    for logged_call in mock_logger.log.call_args_list:
        metadata = logged_call.kwargs.get("metadata")
        if isinstance(metadata, dict) and metadata.get("event") == event_name:
            return logged_call.kwargs
    return None


class TestInvokeToolReverseProxied:
    """PROXIED gateway dispatch through the reverse-proxy session manager."""

    @pytest.mark.asyncio
    async def test_dispatch_uses_original_name_and_shared_normalization(self, tool_service, proxied_tool, test_db, mock_logging_services):
        """tools/call must carry the persisted original_name and normalize via the shared MCP path."""
        _stub_db_execute(test_db, proxied_tool, proxied_tool.gateway, proxied_tool.gateway)
        manager = _manager_mock(send_return=_success_response("req-1", PROXIED_RESULT))

        with (
            patch("mcpgateway.services.tool_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            result = await tool_service.invoke_tool(test_db, PROXIED_TOOL_NAME, {"param": "value"}, request_headers=None)

        manager.resolve_connection_id.assert_called_once_with("proxied-gw-1")
        manager.send_request.assert_awaited_once()
        sent_connection_id, sent_request = manager.send_request.await_args.args
        assert sent_connection_id == "conn-1"
        assert sent_request.method == "tools/call"
        assert sent_request.params["name"] == PROXIED_ORIGINAL_NAME  # not the namespaced public name
        assert sent_request.params["arguments"] == {"param": "value"}
        assert "_meta" not in sent_request.params
        assert manager.send_request.await_args.kwargs["timeout_seconds"] == settings.tool_timeout

        assert result.content[0].text == "proxied ok"
        assert result.is_error is False

        events = _structured_log_events(mock_logging_services["structured_logger"])
        assert events["mcp_call_started"]["transport"] == "proxied"
        assert events["mcp_call_completed"]["transport"] == "proxied"
        assert events["mcp_call_completed"]["success"] is True
        assert "mcp_call_failed" not in events

    @pytest.mark.asyncio
    async def test_dispatch_forwards_meta_and_propagates_result_envelope(self, tool_service, proxied_tool, test_db):
        """_meta rides in params; structuredContent and response _meta survive normalization."""
        _stub_db_execute(test_db, proxied_tool, proxied_tool.gateway)
        upstream_result = {
            "content": [{"type": "text", "text": '{"answer": 42}'}],
            "structuredContent": {"answer": 42},
            "isError": False,
            "_meta": {"origin": "proxied"},
        }
        manager = _manager_mock(send_return=_success_response("req-1", upstream_result))

        with (
            patch("mcpgateway.services.tool_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            result = await tool_service.invoke_tool(test_db, PROXIED_TOOL_NAME, {"param": "value"}, request_headers=None, meta_data={"traceparent": "00-abc"})

        sent_request = manager.send_request.await_args.args[1]
        assert sent_request.params["_meta"] == {"traceparent": "00-abc"}
        assert result.structured_content == {"answer": 42}
        assert result.meta == {"origin": "proxied"}
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_dispatch_propagates_upstream_is_error(self, tool_service, proxied_tool, test_db):
        """An upstream isError=true CallToolResult propagates through the shared path unchanged."""
        _stub_db_execute(test_db, proxied_tool, proxied_tool.gateway)
        upstream_result = {"content": [{"type": "text", "text": "upstream broke"}], "isError": True}
        manager = _manager_mock(send_return=_success_response("req-1", upstream_result))

        with (
            patch("mcpgateway.services.tool_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            result = await tool_service.invoke_tool(test_db, PROXIED_TOOL_NAME, {"param": "value"}, request_headers=None)

        assert result.is_error is True
        assert result.content[0].text == "upstream broke"

    @pytest.mark.asyncio
    async def test_absent_stable_id_mapping_fails_closed(self, tool_service, proxied_tool, test_db):
        """No live connection for the stable gateway ID: fail closed, never send, name the gateway."""
        _stub_db_execute(test_db, proxied_tool, proxied_tool.gateway)
        manager = _manager_mock(connection_id=None)

        with patch("mcpgateway.services.tool_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            with pytest.raises(ToolInvocationError, match=r"No active reverse-proxy connection for gateway 'proxied-gw-1'"):
                await tool_service.invoke_tool(test_db, PROXIED_TOOL_NAME, {"param": "value"}, request_headers=None)

        manager.send_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_session_timeout_maps_to_tool_timeout_error(self, tool_service, proxied_tool, test_db, mock_logging_services):
        """A session-level timeout surfaces as ToolTimeoutError with a proxied tool_timeout log event."""
        _stub_db_execute(test_db, proxied_tool, proxied_tool.gateway)
        manager = _manager_mock(send_side_effect=TimeoutError("slow downstream"))

        with (
            patch("mcpgateway.services.tool_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(ToolTimeoutError, match="Tool invocation timed out after"),
        ):
            await tool_service.invoke_tool(test_db, PROXIED_TOOL_NAME, {"param": "value"}, request_headers=None)

        events = _structured_log_events(mock_logging_services["structured_logger"])
        assert events["tool_timeout"]["transport"] == "proxied"
        assert events["tool_timeout"]["tool_name"] == PROXIED_ORIGINAL_NAME
        assert "mcp_call_failed" not in events

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "connection_error",
        [
            ConnectionClosedError(connection_id=ConnectionId("conn-1")),
            ConnectionNotFoundError(connection_id=ConnectionId("conn-1")),
        ],
        ids=["connection_closed", "connection_not_found"],
    )
    async def test_connection_failure_maps_to_invocation_error(self, tool_service, proxied_tool, test_db, connection_error):
        """Dropped or stale connections surface as ToolInvocationError, never raw session errors."""
        _stub_db_execute(test_db, proxied_tool, proxied_tool.gateway)
        manager = _manager_mock(send_side_effect=connection_error)

        with (
            patch("mcpgateway.services.tool_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(ToolInvocationError, match=r"Reverse-proxy connection for gateway 'proxied-gw-1'"),
        ):
            await tool_service.invoke_tool(test_db, PROXIED_TOOL_NAME, {"param": "value"}, request_headers=None)

    @pytest.mark.asyncio
    async def test_mcp_error_response_maps_to_invocation_error(self, tool_service, proxied_tool, test_db):
        """A JSON-RPC error response surfaces the MCP error code only; peer free text never escapes."""
        _stub_db_execute(test_db, proxied_tool, proxied_tool.gateway)
        manager = _manager_mock(send_return=_error_response("req-1", code=-32001, message="upstream exploded"))

        with (
            patch("mcpgateway.services.tool_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(ToolInvocationError, match=r"MCP error -32001") as exc_info,
        ):
            await tool_service.invoke_tool(test_db, PROXIED_TOOL_NAME, {"param": "value"}, request_headers=None)

        assert "upstream exploded" not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_mcp_error_response_emits_mcp_call_failed(self, tool_service, proxied_tool, test_db, mock_logging_services):
        """A JSON-RPC error response raises code-only and leaks no peer text to any structured-log sink."""
        _stub_db_execute(test_db, proxied_tool, proxied_tool.gateway)
        manager = _manager_mock(send_return=_error_response("req-1", code=-32001, message="upstream exploded"))

        with patch("mcpgateway.services.tool_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            with pytest.raises(ToolInvocationError) as direct_exc:
                await tool_service._invoke_reverse_proxied_tool("proxied-gw-1", PROXIED_ORIGINAL_NAME, {"param": "value"}, None, 30.0)
        assert str(direct_exc.value) == "MCP error -32001"

        with (
            patch("mcpgateway.services.tool_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(ToolInvocationError),
        ):
            await tool_service.invoke_tool(test_db, PROXIED_TOOL_NAME, {"param": "value"}, request_headers=None)

        events = _structured_log_events(mock_logging_services["structured_logger"])
        assert "mcp_call_failed" in events
        failed_call = _structured_log_call_kwargs(mock_logging_services["structured_logger"], "mcp_call_failed")
        assert failed_call is not None
        assert failed_call["level"] == "ERROR"
        assert failed_call["error_details"]["error_type"] == "JsonRpcErrorResponse"
        assert failed_call["error_details"]["error_message"] == f"MCP error {-32001}"

        # Peer-controlled free text must reach no telemetry sink: the outer
        # invoke_tool handler copies the raised message into spans, metrics,
        # plugin results, and the structured_logger.error call, so scan every
        # structured-logger call at any level for the peer message.
        all_logged_calls = " ".join(repr(logged_call) for logged_call in mock_logging_services["structured_logger"].mock_calls)
        assert "upstream exploded" not in all_logged_calls

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "connection_error, expected_error_type",
        [
            (ConnectionClosedError(connection_id=ConnectionId("conn-1")), "ConnectionClosedError"),
            (ConnectionNotFoundError(connection_id=ConnectionId("conn-1")), "ConnectionNotFoundError"),
        ],
        ids=["connection_closed", "connection_not_found"],
    )
    async def test_connection_failure_emits_mcp_call_failed(self, tool_service, proxied_tool, test_db, mock_logging_services, connection_error, expected_error_type):
        """Dropped or stale connections log mcp_call_failed once with the connection error type."""
        _stub_db_execute(test_db, proxied_tool, proxied_tool.gateway)
        manager = _manager_mock(send_side_effect=connection_error)

        with (
            patch("mcpgateway.services.tool_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(ToolInvocationError, match=r"Reverse-proxy connection for gateway 'proxied-gw-1'"),
        ):
            await tool_service.invoke_tool(test_db, PROXIED_TOOL_NAME, {"param": "value"}, request_headers=None)

        events = _structured_log_events(mock_logging_services["structured_logger"])
        assert "mcp_call_failed" in events
        assert events["mcp_call_failed"]["transport"] == "proxied"
        assert events["mcp_call_failed"]["tool_name"] == PROXIED_ORIGINAL_NAME
        failed_call = _structured_log_call_kwargs(mock_logging_services["structured_logger"], "mcp_call_failed")
        assert failed_call is not None
        assert failed_call["level"] == "ERROR"
        assert failed_call["error_details"]["error_type"] == expected_error_type

    @pytest.mark.asyncio
    async def test_dispatch_occurs_inside_gateway_call_span(self, tool_service, proxied_tool, test_db):
        """The session-manager send happens while the tool.gateway_call span is active."""
        _stub_db_execute(test_db, proxied_tool, proxied_tool.gateway)
        active_spans: list[str] = []

        @contextmanager
        def recording_span(span_name, _attributes=None):
            active_spans.append(span_name)
            try:
                yield None
            finally:
                active_spans.remove(span_name)

        async def send_and_assert_in_span(_connection_id, _payload, *, timeout_seconds):
            del timeout_seconds
            assert "tool.gateway_call" in active_spans
            return _success_response("req-1", PROXIED_RESULT)

        manager = _manager_mock()
        manager.send_request = send_and_assert_in_span

        with (
            patch("mcpgateway.services.tool_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            patch("mcpgateway.services.tool_service.create_child_span", recording_span),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            result = await tool_service.invoke_tool(test_db, PROXIED_TOOL_NAME, {"param": "value"}, request_headers=None)

        assert result.content[0].text == "proxied ok"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "transport, client_patch, stream_size",
        [("SSE", "sse_client", 2), ("STREAMABLEHTTP", "streamablehttp_client", 3)],
        ids=["sse_gateway", "streamablehttp_gateway"],
    )
    async def test_non_proxied_gateways_never_touch_session_manager(self, tool_service, proxied_tool, test_db, transport, client_patch, stream_size):
        """Regression: SSE/streamablehttp gateways keep their existing dispatch, no proxy lookup."""
        gateway = proxied_tool.gateway
        gateway.transport = transport
        gateway.url = "http://fake-mcp:8080/mcp"
        proxied_tool.request_type = transport

        _stub_db_execute(test_db, proxied_tool, gateway, gateway)

        expected = ToolResult(content=[TextContent(type="text", text=f"{transport} ok")])
        session_mock = AsyncMock()
        session_mock.initialize = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected)
        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        @asynccontextmanager
        async def mock_client(*_args, **_kwargs):
            yield tuple(["read", "write", None][:stream_size])

        with (
            patch(f"mcpgateway.services.tool_service.{client_patch}", mock_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
            patch("mcpgateway.services.tool_service.inject_trace_context_headers", side_effect=lambda headers: headers),
            patch("mcpgateway.services.tool_service._downstream_session_id_from_request", return_value=None),
            patch("mcpgateway.services.tool_service.get_reverse_proxy_session_manager") as manager_factory,
        ):
            result = await tool_service.invoke_tool(test_db, PROXIED_TOOL_NAME, {"param": "value"}, request_headers=None)

        session_mock.call_tool.assert_awaited_once()
        manager_factory.assert_not_called()
        assert result.content[0].text == f"{transport} ok"

    @pytest.mark.asyncio
    async def test_team_scoped_proxied_tool_denied_to_other_team(self, tool_service, proxied_tool, test_db):
        """Layer-1 regression: a team-scoped proxied tool is invisible to another team's caller."""
        proxied_tool.visibility = "team"
        proxied_tool.team_id = "team-a"
        _stub_db_execute(test_db, proxied_tool)

        with (
            patch("mcpgateway.services.tool_service.get_reverse_proxy_session_manager") as manager_factory,
            pytest.raises(ToolNotFoundError, match="Tool not found"),
        ):
            await tool_service.invoke_tool(
                test_db,
                PROXIED_TOOL_NAME,
                {"param": "value"},
                request_headers=None,
                user_email="outsider@example.com",
                token_teams=["team-b"],
            )

        manager_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_malformed_upstream_result_emits_mcp_call_failed(self, tool_service, mock_logging_services):
        """A malformed upstream CallToolResult logs mcp_call_failed with ValidationError and no completed event."""
        manager = _manager_mock(send_return=_success_response("req-1", {"isError": False}))  # missing required content

        with (
            patch("mcpgateway.services.tool_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(ValidationError),
        ):
            await tool_service._invoke_reverse_proxied_tool("proxied-gw-1", PROXIED_ORIGINAL_NAME, {"param": "value"}, None, 30.0)

        events = _structured_log_events(mock_logging_services["structured_logger"])
        assert events["mcp_call_started"]["transport"] == "proxied"
        assert "mcp_call_completed" not in events
        assert "mcp_call_failed" in events
        failed_call = _structured_log_call_kwargs(mock_logging_services["structured_logger"], "mcp_call_failed")
        assert failed_call is not None
        assert failed_call["level"] == "ERROR"
        assert failed_call["error_details"]["error_type"] == "ValidationError"
        assert failed_call["error_details"]["error_message"] == "malformed upstream tools/call result"


class TestPrepareRustMcpToolExecutionReverseProxied:
    """PROXIED tools must never be planned for Rust direct execution (gateway transport is the authority)."""

    @staticmethod
    def _proxied_cache_payload():
        """Cache payload for a PROXIED-synced tool: SSE placeholder request_type, PROXIED gateway transport."""
        return {
            "status": "active",
            "tool": {
                "id": "tool-1",
                "name": PROXIED_TOOL_NAME,
                "original_name": PROXIED_ORIGINAL_NAME,
                "enabled": True,
                "reachable": True,
                "integration_type": "MCP",
                "request_type": "SSE",  # D7: schema-valid placeholder; dispatch keys off gateway transport
                "gateway_id": "proxied-gw-1",
                "jsonpath_filter": None,
                "timeout_ms": None,
            },
            "gateway": {
                "id": "proxied-gw-1",
                "name": "proxied_gateway",
                "url": "reverse-proxy://local",
                "transport": "PROXIED",
                "auth_type": None,
                "auth_value": None,
                "auth_query_params": None,
                "oauth_config": None,
                "ca_certificate": None,
                "ca_certificate_sig": None,
                "passthrough_headers": [],
            },
        }

    @staticmethod
    def _cache_mock(payload):
        """Enabled tool-lookup cache mock returning a fixed payload."""
        mock_cache = AsyncMock()
        mock_cache.enabled = True
        mock_cache.get = AsyncMock(return_value=payload)
        mock_cache.set = AsyncMock()
        mock_cache.set_negative = AsyncMock()
        return mock_cache

    @pytest.mark.asyncio
    async def test_proxied_gateway_transport_is_ineligible_for_rust_direct_execution(self, tool_service):
        """A persisted PROXIED gateway transport forces fallback to the Python PROXIED seam."""
        cache = self._cache_mock(self._proxied_cache_payload())

        with patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache):
            plan = await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), PROXIED_TOOL_NAME)

        assert plan == {"eligible": False, "fallbackReason": "reverse-proxy-transport"}

    @pytest.mark.asyncio
    async def test_non_proxied_gateway_transport_remains_eligible(self, tool_service):
        """Regression guard: non-PROXIED MCP gateways keep their Rust direct-execution eligibility."""
        payload = self._proxied_cache_payload()
        payload["tool"]["request_type"] = "streamablehttp"
        payload["gateway"]["transport"] = "STREAMABLEHTTP"
        payload["gateway"]["url"] = "http://gateway.example/mcp"
        cache = self._cache_mock(payload)
        tool_service._plugin_manager = None

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), PROXIED_TOOL_NAME)

        assert plan["eligible"] is True
        assert plan["transport"] == "streamablehttp"
