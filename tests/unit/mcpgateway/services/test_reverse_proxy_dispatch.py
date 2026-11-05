# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_reverse_proxy_dispatch.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the shared proxied-RPC dispatch helper (reverse_proxy_dispatch).

The helper owns the single state machine every PROXIED-gateway dispatch walks:
resolve the process-local connection for a stable gateway ID, emit
``mcp_call_started`` telemetry, send the JSON-RPC request, then map timeouts
(re-raised), connection loss, and JSON-RPC error responses onto the caller's
typed exception via ``error_factory`` — never leaking credential material or
peer free text into exceptions or telemetry (MCP error code only).
"""

# Standard
import dataclasses
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.reverse_proxy_dispatch import dispatch_proxied_rpc, ProxiedCallTelemetry
from mcpgateway.services.reverse_proxy_protocol import DownstreamAuth, JsonRpcErrorResponse, JsonRpcRequest, JsonRpcSuccessResponse, ResponseMessage
from mcpgateway.services.reverse_proxy_sessions import ConnectionClosedError, ConnectionId, ConnectionNotFoundError, StableGatewayId

PROXIED_STABLE_ID = StableGatewayId("proxied-gw-1")


class SampleDispatchError(Exception):
    """Stand-in for a caller's typed dispatch error (ToolInvocationError/PromptError/ResourceError)."""


def _request(method: str = "tools/call") -> JsonRpcRequest:
    """Build a minimal outbound JSON-RPC request frame."""
    return JsonRpcRequest(jsonrpc="2.0", id="req-1", method=method, params={"name": "upstream_echo", "arguments": {}})


def _success_response(request_id: str = "req-1", result: dict | None = None) -> ResponseMessage:
    """Build a JSON-RPC success response frame."""
    return ResponseMessage(type="response", payload=JsonRpcSuccessResponse.model_validate({"jsonrpc": "2.0", "id": request_id, "result": result or {"ok": True}}))


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


def _telemetry(noun: str = "tool", name: str = "upstream_echo") -> ProxiedCallTelemetry:
    """Build telemetry labels for one proxied call."""
    return ProxiedCallTelemetry(component="sample_service", noun=noun, name=name, gateway_id=str(PROXIED_STABLE_ID))


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


@pytest.fixture
def mock_structured_logger():
    """Capture the dispatch module's structured telemetry without touching real sinks."""
    with patch("mcpgateway.services.reverse_proxy_dispatch.structured_logger") as mock_logger:
        mock_logger.log = MagicMock(return_value=None)
        yield mock_logger


class TestDispatchProxiedRpcHappyPath:
    """Local-session happy path: resolve, log started, send, return the response."""

    @pytest.mark.asyncio
    async def test_resolves_sends_and_returns_response(self, mock_structured_logger):
        """The response frame comes back untouched; send uses positional conn/request and kwarg timeout/auth."""
        manager = _manager_mock(send_return=_success_response())
        request = _request()

        with patch("mcpgateway.services.reverse_proxy_dispatch.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            response = await dispatch_proxied_rpc(PROXIED_STABLE_ID, request, timeout_seconds=30.0, error_factory=SampleDispatchError, telemetry=_telemetry())

        manager.resolve_connection_id.assert_called_once_with("proxied-gw-1")
        manager.send_request.assert_awaited_once()
        sent_connection_id, sent_request = manager.send_request.await_args.args
        assert sent_connection_id == "conn-1"
        assert sent_request is request
        assert manager.send_request.await_args.kwargs["timeout_seconds"] == 30.0
        assert manager.send_request.await_args.kwargs["auth"] is None
        assert response.payload.result == {"ok": True}

    @pytest.mark.asyncio
    async def test_started_event_precedes_send_and_carries_proxied_transport(self, mock_structured_logger):
        """mcp_call_started (INFO) is emitted before the send and names the item, gateway, and transport."""
        manager = _manager_mock(send_return=_success_response())

        async def send_and_assert_started(*_args, **_kwargs):
            assert "mcp_call_started" in _structured_log_events(mock_structured_logger)
            return _success_response()

        manager.send_request = send_and_assert_started

        with patch("mcpgateway.services.reverse_proxy_dispatch.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            await dispatch_proxied_rpc(PROXIED_STABLE_ID, _request(), timeout_seconds=30.0, error_factory=SampleDispatchError, telemetry=_telemetry())

        events = _structured_log_events(mock_structured_logger)
        assert events["mcp_call_started"]["transport"] == "proxied"
        assert events["mcp_call_started"]["tool_name"] == "upstream_echo"
        assert events["mcp_call_started"]["gateway_id"] == "proxied-gw-1"
        started_call = _structured_log_call_kwargs(mock_structured_logger, "mcp_call_started")
        assert started_call is not None
        assert started_call["level"] == "INFO"
        assert "mcp_call_failed" not in events

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "noun, expected_key",
        [("tool", "tool_name"), ("prompt", "prompt_name"), ("resource", "resource_uri")],
        ids=["tool", "prompt", "resource"],
    )
    async def test_name_metadata_key_follows_noun(self, mock_structured_logger, noun, expected_key):
        """Each caller family gets its conventional name metadata key (tool_name/prompt_name/resource_uri)."""
        manager = _manager_mock(send_return=_success_response())

        with patch("mcpgateway.services.reverse_proxy_dispatch.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            await dispatch_proxied_rpc(PROXIED_STABLE_ID, _request(), timeout_seconds=30.0, error_factory=SampleDispatchError, telemetry=_telemetry(noun=noun, name="upstream-item"))

        events = _structured_log_events(mock_structured_logger)
        assert events["mcp_call_started"][expected_key] == "upstream-item"


class TestDispatchProxiedRpcFailures:
    """Failure mapping: no connection, timeout, connection loss, JSON-RPC error."""

    @pytest.mark.asyncio
    async def test_no_active_connection_raises_typed_error_without_send(self, mock_structured_logger):
        """An unresolvable stable ID fails closed through error_factory and never sends."""
        manager = _manager_mock(connection_id=None)

        with (
            patch("mcpgateway.services.reverse_proxy_dispatch.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(SampleDispatchError) as exc_info,
        ):
            await dispatch_proxied_rpc(PROXIED_STABLE_ID, _request(), timeout_seconds=30.0, error_factory=SampleDispatchError, telemetry=_telemetry())

        assert str(exc_info.value) == "No active reverse-proxy connection for gateway 'proxied-gw-1'"
        manager.send_request.assert_not_awaited()
        assert "mcp_call_started" not in _structured_log_events(mock_structured_logger)

    @pytest.mark.asyncio
    async def test_timeout_re_raises_and_emits_noun_timeout_warning(self, mock_structured_logger):
        """A session timeout re-raises TimeoutError after a WARNING {noun}_timeout event; no mcp_call_failed."""
        manager = _manager_mock(send_side_effect=TimeoutError("slow downstream"))

        with (
            patch("mcpgateway.services.reverse_proxy_dispatch.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(TimeoutError),
        ):
            await dispatch_proxied_rpc(PROXIED_STABLE_ID, _request(), timeout_seconds=30.0, error_factory=SampleDispatchError, telemetry=_telemetry())

        events = _structured_log_events(mock_structured_logger)
        assert "tool_timeout" in events
        assert events["tool_timeout"]["transport"] == "proxied"
        assert events["tool_timeout"]["tool_name"] == "upstream_echo"
        assert events["tool_timeout"]["timeout_seconds"] == 30.0
        timeout_call = _structured_log_call_kwargs(mock_structured_logger, "tool_timeout")
        assert timeout_call is not None
        assert timeout_call["level"] == "WARNING"
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
    async def test_connection_failure_maps_via_error_factory(self, mock_structured_logger, connection_error):
        """Connection loss raises error_factory chained from the session error, with one mcp_call_failed."""
        manager = _manager_mock(send_side_effect=connection_error)

        with (
            patch("mcpgateway.services.reverse_proxy_dispatch.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(SampleDispatchError, match=r"Reverse-proxy connection for gateway 'proxied-gw-1' failed") as exc_info,
        ):
            await dispatch_proxied_rpc(PROXIED_STABLE_ID, _request(), timeout_seconds=30.0, error_factory=SampleDispatchError, telemetry=_telemetry())

        assert exc_info.value.__cause__ is connection_error
        events = _structured_log_events(mock_structured_logger)
        assert "mcp_call_failed" in events
        assert events["mcp_call_failed"]["tool_name"] == "upstream_echo"
        failed_call = _structured_log_call_kwargs(mock_structured_logger, "mcp_call_failed")
        assert failed_call is not None
        assert failed_call["level"] == "ERROR"
        assert failed_call["error_details"]["error_type"] == type(connection_error).__name__

    @pytest.mark.asyncio
    async def test_jsonrpc_error_raises_code_only(self, mock_structured_logger):
        """A JSON-RPC error response raises the MCP error code only; peer free text escapes nowhere."""
        manager = _manager_mock(send_return=_error_response("req-1", code=-32001, message="upstream exploded"))

        with (
            patch("mcpgateway.services.reverse_proxy_dispatch.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(SampleDispatchError) as exc_info,
        ):
            await dispatch_proxied_rpc(PROXIED_STABLE_ID, _request(), timeout_seconds=30.0, error_factory=SampleDispatchError, telemetry=_telemetry())

        assert str(exc_info.value) == "MCP error -32001"
        assert "upstream exploded" not in str(exc_info.value)
        failed_call = _structured_log_call_kwargs(mock_structured_logger, "mcp_call_failed")
        assert failed_call is not None
        assert failed_call["level"] == "ERROR"
        assert failed_call["error_details"]["error_type"] == "JsonRpcErrorResponse"
        assert failed_call["error_details"]["error_message"] == "MCP error -32001"
        all_logged_calls = " ".join(repr(logged_call) for logged_call in mock_structured_logger.mock_calls)
        assert "upstream exploded" not in all_logged_calls


class TestDispatchProxiedRpcAuth:
    """Downstream auth forwarding: the material rides the send and reaches no telemetry sink."""

    @pytest.mark.asyncio
    async def test_auth_forwarded_and_never_logged(self, mock_structured_logger):
        """DownstreamAuth reaches send_request verbatim; its secret appears in no structured-log call."""
        manager = _manager_mock(send_return=_success_response())
        auth = DownstreamAuth(auth_type="bearer", headers={"Authorization": "Bearer dispatch-secret"})

        with patch("mcpgateway.services.reverse_proxy_dispatch.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            await dispatch_proxied_rpc(PROXIED_STABLE_ID, _request(), timeout_seconds=30.0, error_factory=SampleDispatchError, telemetry=_telemetry(), auth=auth)

        assert manager.send_request.await_args.kwargs["auth"] is auth
        all_logged_calls = " ".join(repr(logged_call) for logged_call in mock_structured_logger.mock_calls)
        assert "dispatch-secret" not in all_logged_calls


class TestProxiedCallTelemetry:
    """Telemetry label value object."""

    def test_telemetry_is_frozen(self):
        """Labels are immutable once built."""
        telemetry = _telemetry()
        with pytest.raises(dataclasses.FrozenInstanceError):
            telemetry.noun = "prompt"
