# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_prompt_service_reverse_proxy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for PROXIED gateway dispatch in PromptService._fetch_gateway_prompt_result()
(reverse-proxy Phase 4).

A PROXIED gateway persists no auth material and no reachable URL: prompt fetch
resolves the process-local reverse-proxy WebSocket connection for the persisted
stable gateway ID and sends a ``prompts/get`` JSON-RPC request using the
persisted ``original_name`` (never the namespaced public name). All failure
modes fail closed through the existing prompt-service error taxonomy.
"""

# Standard
from contextlib import asynccontextmanager
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
from mcp import types
import pytest
from pydantic import ValidationError

# First-Party
from mcpgateway.common.models import PromptResult, Role
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.services.prompt_service import PromptError, PromptNotFoundError, PromptService
from mcpgateway.services.reverse_proxy_protocol import JsonRpcErrorResponse, JsonRpcSuccessResponse, ResponseMessage
from mcpgateway.services.reverse_proxy_sessions import ConnectionClosedError, ConnectionId, ConnectionNotFoundError

PROXIED_PROMPT_NAME = "proxied-gateway-upstream-prompt"
PROXIED_ORIGINAL_NAME = "upstream_prompt"
PROXIED_RESULT = {
    "description": "Rendered upstream",
    "messages": [
        {"role": "user", "content": {"type": "text", "text": "proxied user"}},
        {"role": "assistant", "content": {"type": "text", "text": "proxied assistant"}},
    ],
}


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes during tests."""
    with patch("mcpgateway.services.prompt_service.audit_trail") as mock_audit, patch("mcpgateway.services.prompt_service.structured_logger") as mock_logger:
        mock_audit.log_action = MagicMock(return_value=None)
        mock_logger.log = MagicMock(return_value=None)
        yield {"audit_trail": mock_audit, "structured_logger": mock_logger}


@pytest.fixture
def prompt_service():
    """Create a prompt service instance."""
    return PromptService()


@pytest.fixture
def proxied_gateway():
    """Create a PROXIED gateway model: no auth material, transport is the dispatch authority."""
    gateway = MagicMock(spec=DbGateway)
    gateway.id = "proxied-gw-1"
    gateway.name = "proxied_gateway"
    gateway.url = "reverse-proxy://local"
    gateway.transport = "PROXIED"
    gateway.auth_type = None
    gateway.auth_value = None
    gateway.auth_query_params = None
    return gateway


@pytest.fixture
def proxied_prompt(proxied_gateway):
    """Create a gateway-backed prompt synced from a PROXIED gateway (blank local template)."""
    prompt = MagicMock(spec=DbPrompt)
    prompt.id = "prompt-1"
    prompt.name = PROXIED_PROMPT_NAME
    prompt.original_name = PROXIED_ORIGINAL_NAME
    prompt.description = "Proxied prompt"
    prompt.template = ""  # gateway-backed: blank template forces upstream fetch
    prompt.gateway_id = proxied_gateway.id
    prompt.gateway = proxied_gateway
    prompt.visibility = "public"
    prompt.team_id = None
    prompt.owner_email = "admin@example.com"
    return prompt


def _make_execute_result(*, scalar: Any = None) -> MagicMock:
    """Return a MagicMock mimicking the SQLAlchemy Result object (mirrors test_prompt_service.py)."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    result.scalar.return_value = scalar
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = [] if scalar is None else [scalar]
    result.scalars.return_value = scalars_proxy
    return result


def _stub_lookup(prompt_service, test_db, prompt: Optional[MagicMock]) -> None:
    """Grant access and point the prompt lookup at the canned row (or nothing when None)."""
    prompt_service._apply_access_control = AsyncMock(side_effect=lambda q, *args, **kwargs: q)
    test_db.execute = Mock(return_value=_make_execute_result(scalar=prompt))
    test_db.commit = Mock()


def _success_response(request_id: str, result: dict) -> ResponseMessage:
    """Build a JSON-RPC success response frame carrying a GetPromptResult payload."""
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


class TestFetchGatewayPromptResultReverseProxied:
    """PROXIED gateway dispatch through the reverse-proxy session manager."""

    @pytest.mark.asyncio
    async def test_dispatch_uses_original_name_and_shared_normalization(self, prompt_service, proxied_prompt, test_db, mock_logging_services):
        """prompts/get must carry the persisted original_name and normalize via the shared path."""
        _stub_lookup(prompt_service, test_db, proxied_prompt)
        manager = _manager_mock(send_return=_success_response("req-1", PROXIED_RESULT))

        with patch("mcpgateway.services.prompt_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            result = await prompt_service.get_prompt(test_db, PROXIED_PROMPT_NAME, {"question": "what"})

        manager.resolve_connection_id.assert_called_once_with("proxied-gw-1")
        manager.send_request.assert_awaited_once()
        sent_connection_id, sent_request = manager.send_request.await_args.args
        assert sent_connection_id == "conn-1"
        assert sent_request.method == "prompts/get"
        assert sent_request.params["name"] == PROXIED_ORIGINAL_NAME  # not the namespaced public name
        assert sent_request.params["arguments"] == {"question": "what"}  # member present when arguments are supplied
        assert "_meta" not in sent_request.params
        assert manager.send_request.await_args.kwargs["timeout_seconds"] == float(settings.health_check_timeout)

        assert isinstance(result, PromptResult)
        assert result.description == "Rendered upstream"
        assert [message.role for message in result.messages] == [Role.USER, Role.ASSISTANT]
        assert result.messages[0].content.text == "proxied user"
        assert result.messages[1].content.text == "proxied assistant"

        events = _structured_log_events(mock_logging_services["structured_logger"])
        assert events["mcp_call_started"]["transport"] == "proxied"
        assert events["mcp_call_completed"]["transport"] == "proxied"
        assert events["mcp_call_completed"]["success"] is True
        assert "mcp_call_failed" not in events

    @pytest.mark.asyncio
    async def test_dispatch_forwards_meta(self, prompt_service, proxied_prompt, test_db):
        """_meta rides in the prompts/get params when meta_data is supplied."""
        _stub_lookup(prompt_service, test_db, proxied_prompt)
        manager = _manager_mock(send_return=_success_response("req-1", PROXIED_RESULT))

        with patch("mcpgateway.services.prompt_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            await prompt_service.get_prompt(test_db, PROXIED_PROMPT_NAME, {"question": "what"}, _meta_data={"traceparent": "00-abc"})

        sent_request = manager.send_request.await_args.args[1]
        assert sent_request.params["_meta"] == {"traceparent": "00-abc"}

    @pytest.mark.asyncio
    async def test_description_falls_back_to_prompt_description(self, prompt_service, proxied_prompt, test_db):
        """No-arguments call omits the ``arguments`` member entirely; an upstream result without a description keeps the catalog description."""
        _stub_lookup(prompt_service, test_db, proxied_prompt)
        upstream_result = {"messages": [{"role": "user", "content": {"type": "text", "text": "body"}}]}
        manager = _manager_mock(send_return=_success_response("req-1", upstream_result))

        with patch("mcpgateway.services.prompt_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            result = await prompt_service.get_prompt(test_db, PROXIED_PROMPT_NAME, {})

        sent_request = manager.send_request.await_args.args[1]
        assert sent_request.params["name"] == PROXIED_ORIGINAL_NAME
        assert "arguments" not in sent_request.params  # omitted entirely, never an explicit null
        assert result.description == "Proxied prompt"
        assert result.messages[0].content.text == "body"

    @pytest.mark.asyncio
    async def test_absent_stable_id_mapping_fails_closed(self, prompt_service, proxied_prompt, test_db):
        """No live connection for the stable gateway ID: fail closed, never send, name the gateway."""
        _stub_lookup(prompt_service, test_db, proxied_prompt)
        manager = _manager_mock(connection_id=None)

        with patch("mcpgateway.services.prompt_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            with pytest.raises(PromptError, match=r"No active reverse-proxy connection for gateway 'proxied-gw-1'"):
                await prompt_service.get_prompt(test_db, PROXIED_PROMPT_NAME, {"question": "what"})

        manager.send_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_session_timeout_maps_to_prompt_error(self, prompt_service, proxied_prompt, test_db, mock_logging_services):
        """A session-level timeout surfaces as PromptError with a proxied prompt_timeout log event."""
        _stub_lookup(prompt_service, test_db, proxied_prompt)
        manager = _manager_mock(send_side_effect=TimeoutError("slow downstream"))

        with (
            patch("mcpgateway.services.prompt_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(PromptError, match="Prompt fetch timed out after"),
        ):
            await prompt_service.get_prompt(test_db, PROXIED_PROMPT_NAME, {"question": "what"})

        events = _structured_log_events(mock_logging_services["structured_logger"])
        assert events["prompt_timeout"]["transport"] == "proxied"
        assert events["prompt_timeout"]["prompt_name"] == PROXIED_ORIGINAL_NAME
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
    async def test_connection_failure_maps_to_prompt_error(self, prompt_service, proxied_prompt, test_db, mock_logging_services, connection_error):
        """Dropped or stale connections surface as PromptError, never raw session errors."""
        _stub_lookup(prompt_service, test_db, proxied_prompt)
        manager = _manager_mock(send_side_effect=connection_error)

        with (
            patch("mcpgateway.services.prompt_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(PromptError, match=r"Reverse-proxy connection for gateway 'proxied-gw-1' failed"),
        ):
            await prompt_service.get_prompt(test_db, PROXIED_PROMPT_NAME, {"question": "what"})

        events = _structured_log_events(mock_logging_services["structured_logger"])
        assert events["mcp_call_failed"]["transport"] == "proxied"
        failed_call = _structured_log_call_kwargs(mock_logging_services["structured_logger"], "mcp_call_failed")
        assert failed_call is not None
        assert failed_call["level"] == "ERROR"
        assert failed_call["error_details"]["error_type"] == type(connection_error).__name__

    @pytest.mark.asyncio
    async def test_mcp_error_response_maps_code_only(self, prompt_service, proxied_prompt, test_db, mock_logging_services):
        """A JSON-RPC error response surfaces the MCP error code only; peer free text never escapes."""
        _stub_lookup(prompt_service, test_db, proxied_prompt)
        manager = _manager_mock(send_return=_error_response("req-1", code=-32001, message="upstream exploded"))

        with (
            patch("mcpgateway.services.prompt_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(PromptError, match=r"MCP error -32001") as exc_info,
        ):
            await prompt_service.get_prompt(test_db, PROXIED_PROMPT_NAME, {"question": "what"})

        assert "upstream exploded" not in str(exc_info.value)
        failed_call = _structured_log_call_kwargs(mock_logging_services["structured_logger"], "mcp_call_failed")
        assert failed_call is not None
        assert failed_call["error_details"]["error_type"] == "JsonRpcErrorResponse"
        assert failed_call["error_details"]["error_message"] == "MCP error -32001"
        all_logged_calls = " ".join(repr(logged_call) for logged_call in mock_logging_services["structured_logger"].mock_calls)
        assert "upstream exploded" not in all_logged_calls

    @pytest.mark.asyncio
    async def test_mcp_error_response_direct_helper_exact_message(self, prompt_service, proxied_prompt):
        """Direct helper invocation raises the code-only message verbatim (tool-service parity)."""
        manager = _manager_mock(send_return=_error_response("req-1", code=-32001, message="upstream exploded"))

        with (
            patch("mcpgateway.services.prompt_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(PromptError) as exc_info,
        ):
            await prompt_service._get_reverse_proxied_prompt("proxied-gw-1", PROXIED_ORIGINAL_NAME, {"question": "what"}, None, proxied_prompt)

        assert str(exc_info.value) == "MCP error -32001"

    @pytest.mark.asyncio
    async def test_malformed_upstream_result_raises_validation_error(self, prompt_service, proxied_prompt, mock_logging_services):
        """A malformed upstream GetPromptResult logs mcp_call_failed and raises ValidationError."""
        manager = _manager_mock(send_return=_success_response("req-1", {"description": "no messages member"}))

        with (
            patch("mcpgateway.services.prompt_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(ValidationError),
        ):
            await prompt_service._get_reverse_proxied_prompt("proxied-gw-1", PROXIED_ORIGINAL_NAME, {"question": "what"}, None, proxied_prompt)

        events = _structured_log_events(mock_logging_services["structured_logger"])
        assert "mcp_call_completed" not in events
        failed_call = _structured_log_call_kwargs(mock_logging_services["structured_logger"], "mcp_call_failed")
        assert failed_call is not None
        assert failed_call["error_details"]["error_type"] == "ValidationError"
        assert failed_call["error_details"]["error_message"] == "malformed upstream prompts/get result"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "transport, client_patch, stream_size",
        [("SSE", "sse_client", 2), ("STREAMABLE_HTTP", "streamablehttp_client", 3)],
        ids=["sse_gateway", "streamable_http_gateway"],
    )
    async def test_non_proxied_gateways_never_touch_session_manager(self, prompt_service, proxied_prompt, test_db, transport, client_patch, stream_size):
        """Regression: SSE/streamable-HTTP gateways keep their existing dispatch, no proxy lookup."""
        proxied_prompt.gateway.transport = transport
        proxied_prompt.gateway.url = "http://fake-mcp:8080/mcp"
        _stub_lookup(prompt_service, test_db, proxied_prompt)

        remote_result = types.GetPromptResult(
            description=f"{transport} ok",
            messages=[types.PromptMessage(role="user", content=types.TextContent(type="text", text="rendered"))],
        )
        session_mock = AsyncMock()
        session_mock.initialize = AsyncMock()
        session_mock.get_prompt = AsyncMock(return_value=remote_result)
        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        @asynccontextmanager
        async def mock_client(*_args, **_kwargs):
            """Yield a fake transport stream tuple of the right arity for the client under test."""
            yield tuple(["read", "write", None][:stream_size])

        with (
            patch(f"mcpgateway.services.prompt_service.{client_patch}", mock_client),
            patch("mcpgateway.services.prompt_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.prompt_service.get_reverse_proxy_session_manager") as manager_factory,
        ):
            result = await prompt_service.get_prompt(test_db, PROXIED_PROMPT_NAME, {"question": "what"})

        session_mock.get_prompt.assert_awaited_once()
        manager_factory.assert_not_called()
        assert result.description == f"{transport} ok"
        assert result.messages[0].content.text == "rendered"

    @pytest.mark.asyncio
    async def test_team_scoped_proxied_prompt_denied_to_other_team(self, prompt_service, proxied_prompt, test_db):
        """Layer-1 regression: a team-scoped proxied prompt is invisible to another team's caller."""

        async def mock_apply_access_control(query, *_args, **_kwargs):
            """Return a query that matches nothing, simulating Layer-1 access denial."""
            return query.where(DbPrompt.id == "nonexistent")

        proxied_prompt.visibility = "team"
        proxied_prompt.team_id = "team-a"
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))

        with (
            patch.object(prompt_service, "_apply_access_control", side_effect=mock_apply_access_control),
            patch("mcpgateway.services.prompt_service.get_reverse_proxy_session_manager") as manager_factory,
            pytest.raises(PromptNotFoundError, match="Prompt not found"),
        ):
            await prompt_service.get_prompt(
                test_db,
                PROXIED_PROMPT_NAME,
                {"question": "what"},
                user="outsider@example.com",
                token_teams=["team-b"],
            )

        manager_factory.assert_not_called()
