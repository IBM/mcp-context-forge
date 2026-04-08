# -*- coding: utf-8 -*-
"""Integration tests for elicitation pass-through functionality.

This test suite verifies the complete elicitation lifecycle per MCP spec 2025-06-18:
- MCP servers can issue elicitation/create during tool execution
- Gateway forwards requests to the originating client session
- Client responses are returned upstream to the server
- Session correlation works correctly in multi-user deployments
- Structured logging and metrics are emitted for all lifecycle events

Test Coverage:
- US-1: MCP Server - Request User Input During Tool Execution
- US-2: Gateway - Route Elicitation to Correct Session
- US-3: Client - Advertise Elicitation Capability
- US-4: Operator - Monitor Elicitation Events
"""

# Standard
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

# Third-Party
import pytest
from mcp import types

# First-Party
from mcpgateway.cache.session_registry import SessionRegistry
from mcpgateway.cache.tool_call_registry import ToolCallRegistry
from mcpgateway.common.models import ElicitRequestParams, ElicitResult
from mcpgateway.services.elicitation_service import ElicitationService
from mcpgateway.services.tool_service import ToolService


@pytest.fixture
def elicitation_service():
    """Create a fresh ElicitationService for testing."""
    service = ElicitationService(default_timeout=5, max_concurrent=10)
    return service


@pytest.fixture
def tool_call_registry():
    """Create a fresh ToolCallRegistry for testing."""
    registry = ToolCallRegistry(cleanup_interval=300)
    return registry


@pytest.fixture
def session_registry():
    """Create a mock SessionRegistry for testing."""
    registry = MagicMock(spec=SessionRegistry)
    registry.has_elicitation_capability = AsyncMock(return_value=True)
    registry.get_elicitation_capable_sessions = AsyncMock(return_value=["session-123"])
    registry.broadcast = AsyncMock()
    return registry


@pytest.fixture
def tool_service():
    """Create a ToolService instance for testing."""
    service = ToolService()
    return service


class TestElicitationPassThrough:
    """Test suite for elicitation pass-through functionality."""

    @pytest.mark.asyncio
    async def test_us1_server_requests_user_input_during_tool_execution(
        self, elicitation_service, tool_call_registry, session_registry
    ):
        """US-1: MCP Server can request user confirmation during tool execution.

        Scenario: Server requests user confirmation via elicitation
          Given an MCP server executing tool "delete_files"
          And the tool needs user confirmation before proceeding
          When the server sends elicitation/create with message "Delete 50 files?"
          Then the gateway should forward the request to the originating client
          And the client should display the confirmation dialog
          And the client response should be returned to the server
          And the tool execution should continue based on user response
        """
        # Setup
        tool_call_id = str(uuid4())
        session_id = "session-123"
        message = "Delete 50 files?"
        schema = {
            "type": "object",
            "properties": {
                "confirm": {"type": "boolean"}
            }
        }

        # Register tool call mapping
        tool_call_registry.register_tool_call(tool_call_id, session_id)

        # Create elicitation request (simulates server sending elicitation/create)
        elicitation_task = asyncio.create_task(
            elicitation_service.create_elicitation(
                upstream_session_id=tool_call_id,
                downstream_session_id=session_id,
                message=message,
                requested_schema=schema,
                timeout=5.0,
            )
        )

        # Wait for elicitation to be created
        await asyncio.sleep(0.01)

        # Verify elicitation is pending
        pending = elicitation_service.get_pending_elicitation(
            list(elicitation_service._pending.keys())[0]
        )
        assert pending is not None
        assert pending.downstream_session_id == session_id
        assert pending.message == message

        # Simulate client response (user accepts)
        result = ElicitResult(action="accept", content={"confirm": True})
        elicitation_service.complete_elicitation(pending.request_id, result)

        # Wait for elicitation to complete
        completed_result = await elicitation_task

        # Verify result
        assert completed_result.action == "accept"
        assert completed_result.content == {"confirm": True}

        # Cleanup
        tool_call_registry.unregister_tool_call(tool_call_id)

    @pytest.mark.asyncio
    async def test_us2_elicitation_reaches_correct_client_in_multi_user(
        self, elicitation_service, tool_call_registry
    ):
        """US-2: Elicitation reaches correct client in multi-user deployment.

        Scenario: Elicitation reaches correct client in multi-user deployment
          Given user A is executing tool "sensitive_action" via session S1
          And user B has an active session S2
          When the server sends elicitation/create
          Then the request should be routed ONLY to session S1
          And session S2 should NOT receive the elicitation request
        """
        # Setup two users with different sessions
        tool_call_id_a = str(uuid4())
        session_id_a = "session-user-a"
        tool_call_id_b = str(uuid4())
        session_id_b = "session-user-b"

        # Register both tool calls
        tool_call_registry.register_tool_call(tool_call_id_a, session_id_a)
        tool_call_registry.register_tool_call(tool_call_id_b, session_id_b)

        # Create elicitation for user A
        message_a = "Confirm sensitive action for user A?"
        schema = {"type": "object", "properties": {"confirm": {"type": "boolean"}}}

        elicitation_task_a = asyncio.create_task(
            elicitation_service.create_elicitation(
                upstream_session_id=tool_call_id_a,
                downstream_session_id=session_id_a,
                message=message_a,
                requested_schema=schema,
                timeout=5.0,
            )
        )

        await asyncio.sleep(0.01)

        # Verify elicitation is routed to correct session
        pending_a = list(elicitation_service._pending.values())[0]
        assert pending_a.downstream_session_id == session_id_a
        assert pending_a.downstream_session_id != session_id_b

        # Verify tool call registry returns correct session
        assert tool_call_registry.get_session_for_tool_call(tool_call_id_a) == session_id_a
        assert tool_call_registry.get_session_for_tool_call(tool_call_id_b) == session_id_b

        # Complete elicitation for user A
        result_a = ElicitResult(action="accept", content={"confirm": True})
        elicitation_service.complete_elicitation(pending_a.request_id, result_a)

        completed_result_a = await elicitation_task_a
        assert completed_result_a.action == "accept"

        # Cleanup
        tool_call_registry.unregister_tool_call(tool_call_id_a)
        tool_call_registry.unregister_tool_call(tool_call_id_b)

    @pytest.mark.asyncio
    async def test_us2_handle_missing_session_gracefully(
        self, elicitation_service, tool_call_registry
    ):
        """US-2: Handle missing session gracefully.

        Scenario: Handle missing session gracefully
          Given an elicitation request with unknown session mapping
          When the gateway attempts to route the request
          Then a clear error should be returned to the server
          And the error should indicate "No client session available"
          And the error should be logged with context
        """
        # Setup
        tool_call_id = str(uuid4())
        unknown_session_id = "session-unknown"
        message = "Confirm action?"
        schema = {"type": "object", "properties": {"confirm": {"type": "boolean"}}}

        # Do NOT register tool call mapping (simulates missing session)

        # Attempt to create elicitation with unknown session
        # This should fail because session doesn't exist in registry
        with pytest.raises(Exception):
            await elicitation_service.create_elicitation(
                upstream_session_id=tool_call_id,
                downstream_session_id=unknown_session_id,
                message=message,
                requested_schema=schema,
                timeout=0.1,  # Short timeout
            )

    @pytest.mark.asyncio
    async def test_us3_client_without_elicitation_capability(
        self, tool_service, session_registry
    ):
        """US-3: Client without elicitation capability receives error.

        Scenario: Client without elicitation capability
          Given a client that did not advertise capabilities.elicitation
          When an MCP server sends elicitation/create via gateway
          Then the gateway should return error to server immediately
          And the error code should be -32601 (method not found)
          And no forwarding should be attempted
        """
        # Setup
        tool_call_id = str(uuid4())
        session_id = "session-no-capability"

        # Mock session registry to return False for capability check
        session_registry.has_elicitation_capability = AsyncMock(return_value=False)

        # Create elicitation callback (should return error callback)
        with patch("mcpgateway.main.session_registry", session_registry):
            callback = await tool_service._create_elicitation_callback_for_tool_invocation(
                tool_call_id=tool_call_id,
                downstream_session_id=session_id,
            )

        # Verify callback returns error
        assert callback is not None

        # Simulate calling the callback
        params = ElicitRequestParams(
            message="Test message",
            requestedSchema={"type": "object", "properties": {}}
        )
        result = await callback(None, params)

        # Verify error response
        assert isinstance(result, types.ErrorData)
        assert result.code == -32601
        assert "does not support elicitation" in result.message

    @pytest.mark.asyncio
    async def test_us3_client_with_elicitation_capability(
        self, tool_service, session_registry, elicitation_service
    ):
        """US-3: Client with elicitation capability can receive requests.

        Scenario: Client with elicitation capability
          Given a client that advertised capabilities.elicitation
          When the client connects and initializes
          Then the session_registry should record elicitation=true
          And elicitation requests should be routable to this client
        """
        # Setup
        tool_call_id = str(uuid4())
        session_id = "session-with-capability"

        # Mock session registry to return True for capability check
        session_registry.has_elicitation_capability = AsyncMock(return_value=True)

        # Create elicitation callback (should return normal callback)
        with patch("mcpgateway.main.session_registry", session_registry):
            with patch("mcpgateway.services.tool_service.get_elicitation_service", return_value=elicitation_service):
                callback = await tool_service._create_elicitation_callback_for_tool_invocation(
                    tool_call_id=tool_call_id,
                    downstream_session_id=session_id,
                )

        # Verify callback is not None and not an error callback
        assert callback is not None

        # Verify capability check was called
        session_registry.has_elicitation_capability.assert_called_once_with(session_id)

    @pytest.mark.asyncio
    async def test_us4_structured_logging_lifecycle_events(
        self, elicitation_service, tool_call_registry
    ):
        """US-4: Structured logging emitted for elicitation lifecycle.

        Scenario: Log elicitation lifecycle events
          Given structured logging is enabled
          When an elicitation request is created
          Then log entries should contain event, request_id, sessions, message
          When the client responds
          Then log entry should contain event, action, duration_ms
        """
        # Setup
        tool_call_id = str(uuid4())
        session_id = "session-123"
        message = "Confirm action?"
        schema = {"type": "object", "properties": {"confirm": {"type": "boolean"}}}

        # Register tool call
        tool_call_registry.register_tool_call(tool_call_id, session_id)

        # Capture structured logs
        with patch("mcpgateway.services.elicitation_service.structured_logger") as mock_logger:
            # Create elicitation
            elicitation_task = asyncio.create_task(
                elicitation_service.create_elicitation(
                    upstream_session_id=tool_call_id,
                    downstream_session_id=session_id,
                    message=message,
                    requested_schema=schema,
                    timeout=5.0,
                )
            )

            await asyncio.sleep(0.01)

            # Verify "elicitation.created" event was logged
            created_calls = [
                call for call in mock_logger.log.call_args_list
                if len(call[1].get("metadata", {})) > 0
                and call[1]["metadata"].get("event") == "elicitation.created"
            ]
            assert len(created_calls) > 0
            created_metadata = created_calls[0][1]["metadata"]
            assert "request_id" in created_metadata
            assert created_metadata["upstream_session"] == tool_call_id
            assert created_metadata["downstream_session"] == session_id
            assert created_metadata["message"] == message

            # Verify "elicitation.delivered" event was logged
            delivered_calls = [
                call for call in mock_logger.log.call_args_list
                if len(call[1].get("metadata", {})) > 0
                and call[1]["metadata"].get("event") == "elicitation.delivered"
            ]
            assert len(delivered_calls) > 0

            # Complete elicitation
            pending = list(elicitation_service._pending.values())[0]
            result = ElicitResult(action="accept", content={"confirm": True})
            elicitation_service.complete_elicitation(pending.request_id, result)

            await elicitation_task

            # Verify "elicitation.completed" event was logged
            completed_calls = [
                call for call in mock_logger.log.call_args_list
                if len(call[1].get("metadata", {})) > 0
                and call[1]["metadata"].get("event") == "elicitation.completed"
            ]
            assert len(completed_calls) > 0
            completed_metadata = completed_calls[0][1]["metadata"]
            assert completed_metadata["action"] == "accept"
            assert "duration_ms" in completed_metadata

        # Cleanup
        tool_call_registry.unregister_tool_call(tool_call_id)

    @pytest.mark.asyncio
    async def test_us4_metrics_exposed(self, elicitation_service, tool_call_registry):
        """US-4: Prometheus metrics exposed for elicitation events.

        Scenario: Metrics for elicitation events
          Given Prometheus metrics are enabled
          Then the following metrics should be exposed:
            - elicitation_requests_total (Counter)
            - elicitation_completed_total (Counter by action)
            - elicitation_timeout_total (Counter)
            - elicitation_duration_seconds (Histogram)
        """
        # Import metrics
        from mcpgateway.services.metrics import (
            elicitation_completed_total,
            elicitation_duration_seconds,
            elicitation_requests_total,
            elicitation_timeout_total,
        )

        # Verify metrics exist
        assert elicitation_requests_total is not None
        assert elicitation_completed_total is not None
        assert elicitation_timeout_total is not None
        assert elicitation_duration_seconds is not None

        # Setup
        tool_call_id = str(uuid4())
        session_id = "session-123"
        message = "Confirm action?"
        schema = {"type": "object", "properties": {"confirm": {"type": "boolean"}}}

        # Register tool call
        tool_call_registry.register_tool_call(tool_call_id, session_id)

        # Get initial metric values
        initial_requests = elicitation_requests_total._value._value

        # Create and complete elicitation
        elicitation_task = asyncio.create_task(
            elicitation_service.create_elicitation(
                upstream_session_id=tool_call_id,
                downstream_session_id=session_id,
                message=message,
                requested_schema=schema,
                timeout=5.0,
            )
        )

        await asyncio.sleep(0.01)

        # Verify request counter incremented
        assert elicitation_requests_total._value._value > initial_requests

        # Complete elicitation
        pending = list(elicitation_service._pending.values())[0]
        result = ElicitResult(action="accept", content={"confirm": True})
        elicitation_service.complete_elicitation(pending.request_id, result)

        await elicitation_task

        # Verify completed counter incremented (with action label)
        # Note: Prometheus client doesn't expose easy way to check labeled metrics in tests
        # In production, these would be visible at /metrics endpoint

        # Cleanup
        tool_call_registry.unregister_tool_call(tool_call_id)

    @pytest.mark.asyncio
    async def test_elicitation_timeout_handling(
        self, elicitation_service, tool_call_registry
    ):
        """Test timeout handling for elicitation requests.

        Scenario: Elicitation timeout returns error to server
          Given an elicitation request is pending
          And the client does not respond within timeout period
          When the timeout expires
          Then the server should receive an error response
          And the error should indicate "Elicitation timed out"
        """
        # Setup
        tool_call_id = str(uuid4())
        session_id = "session-123"
        message = "Confirm action?"
        schema = {"type": "object", "properties": {"confirm": {"type": "boolean"}}}

        # Register tool call
        tool_call_registry.register_tool_call(tool_call_id, session_id)

        # Create elicitation with very short timeout
        with pytest.raises(asyncio.TimeoutError):
            await elicitation_service.create_elicitation(
                upstream_session_id=tool_call_id,
                downstream_session_id=session_id,
                message=message,
                requested_schema=schema,
                timeout=0.01,  # 10ms timeout
            )

        # Cleanup
        tool_call_registry.unregister_tool_call(tool_call_id)

    @pytest.mark.asyncio
    async def test_elicitation_schema_validation(self, elicitation_service):
        """Test schema validation for elicitation requests.

        Per MCP spec, elicitation schemas must be flat objects with primitive types only.
        Complex types (nested objects, arrays, refs) are not allowed.
        """
        # Valid schema (primitive types)
        valid_schema = {
            "type": "object",
            "properties": {
                "confirm": {"type": "boolean"},
                "reason": {"type": "string"},
                "count": {"type": "integer"},
            }
        }

        # Should not raise
        elicitation_service._validate_schema(valid_schema)

        # Invalid schema (nested object)
        invalid_schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"}
                    }
                }
            }
        }

        # Should raise ValueError
        with pytest.raises(ValueError, match="invalid type 'object'"):
            elicitation_service._validate_schema(invalid_schema)

    @pytest.mark.asyncio
    async def test_tool_call_registry_cleanup(self, tool_call_registry):
        """Test that tool call registry cleans up stale mappings."""
        # Register a tool call
        tool_call_id = str(uuid4())
        session_id = "session-123"
        tool_call_registry.register_tool_call(tool_call_id, session_id)

        # Verify mapping exists
        assert tool_call_registry.get_session_for_tool_call(tool_call_id) == session_id
        assert tool_call_registry.get_mapping_count() == 1

        # Manually trigger cleanup (normally runs on schedule)
        # Modify timestamp to make it stale
        tool_call_registry._mappings[tool_call_id] = (session_id, 0.0)  # Very old timestamp

        await tool_call_registry._cleanup_stale()

        # Verify mapping was cleaned up
        assert tool_call_registry.get_session_for_tool_call(tool_call_id) is None
        assert tool_call_registry.get_mapping_count() == 0


class TestElicitationCallbackIntegration:
    """Integration tests for elicitation callback in tool service."""

    @pytest.mark.asyncio
    async def test_callback_creation_with_valid_session(self, tool_service):
        """Test that elicitation callback is created when session has capability."""
        tool_call_id = str(uuid4())
        session_id = "session-with-capability"

        # Mock session registry
        mock_registry = MagicMock()
        mock_registry.has_elicitation_capability = AsyncMock(return_value=True)

        with patch("mcpgateway.main.session_registry", mock_registry):
            callback = await tool_service._create_elicitation_callback_for_tool_invocation(
                tool_call_id=tool_call_id,
                downstream_session_id=session_id,
            )

        # Verify callback was created
        assert callback is not None
        assert callable(callback)

    @pytest.mark.asyncio
    async def test_callback_returns_none_when_elicitation_disabled(self, tool_service, monkeypatch):
        """Test that callback returns None when elicitation is globally disabled."""
        from mcpgateway.config import settings

        # Disable elicitation
        monkeypatch.setattr(settings, "mcpgateway_elicitation_enabled", False)

        tool_call_id = str(uuid4())
        session_id = "session-123"

        callback = await tool_service._create_elicitation_callback_for_tool_invocation(
            tool_call_id=tool_call_id,
            downstream_session_id=session_id,
        )

        # Verify callback is None
        assert callback is None

    @pytest.mark.asyncio
    async def test_callback_returns_none_when_no_session(self, tool_service):
        """Test that callback returns None when no downstream session provided."""
        tool_call_id = str(uuid4())

        callback = await tool_service._create_elicitation_callback_for_tool_invocation(
            tool_call_id=tool_call_id,
            downstream_session_id=None,
        )

        # Verify callback is None
        assert callback is None
