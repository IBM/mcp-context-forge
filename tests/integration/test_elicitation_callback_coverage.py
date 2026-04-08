# -*- coding: utf-8 -*-
"""Additional coverage tests for elicitation callback implementation.

These tests focus on covering the actual code paths in tool_service.py
that weren't covered by the main integration tests.
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
    return registry


@pytest.fixture
def tool_service():
    """Create a ToolService instance for testing."""
    service = ToolService()
    return service


class TestElicitationCallbackCoverage:
    """Tests to improve coverage of elicitation callback code paths."""

    @pytest.mark.asyncio
    async def test_capability_error_callback_execution(self, tool_service):
        """Test that capability error callback actually executes and returns error."""
        tool_call_id = str(uuid4())
        session_id = "session-no-capability"

        # Mock session registry to return False
        mock_registry = MagicMock()
        mock_registry.has_elicitation_capability = AsyncMock(return_value=False)

        with patch("mcpgateway.main.session_registry", mock_registry):
            # Create callback
            callback = await tool_service._create_elicitation_callback_for_tool_invocation(
                tool_call_id=tool_call_id,
                downstream_session_id=session_id,
            )

        # Execute the callback with actual params
        params = ElicitRequestParams(
            message="Test elicitation message",
            requestedSchema={"type": "object", "properties": {"confirm": {"type": "boolean"}}}
        )
        
        # Call the callback
        result = await callback(None, params)

        # Verify error response
        assert isinstance(result, types.ErrorData)
        assert result.code == -32601
        assert "does not support elicitation" in result.message
        assert session_id in result.message

    @pytest.mark.asyncio
    async def test_elicitation_callback_with_real_service(
        self, tool_service, elicitation_service, tool_call_registry
    ):
        """Test elicitation callback with real ElicitationService."""
        tool_call_id = str(uuid4())
        session_id = "session-with-capability"

        # Register tool call
        tool_call_registry.register_tool_call(tool_call_id, session_id)

        # Mock session registry to return True
        mock_registry = MagicMock()
        mock_registry.has_elicitation_capability = AsyncMock(return_value=True)

        with patch("mcpgateway.main.session_registry", mock_registry):
            with patch("mcpgateway.services.tool_service.get_elicitation_service", return_value=elicitation_service):
                with patch("mcpgateway.services.tool_service.get_tool_call_registry", return_value=tool_call_registry):
                    # Create callback
                    callback = await tool_service._create_elicitation_callback_for_tool_invocation(
                        tool_call_id=tool_call_id,
                        downstream_session_id=session_id,
                    )

        # Execute callback in background
        params = ElicitRequestParams(
            message="Confirm action?",
            requestedSchema={"type": "object", "properties": {"confirm": {"type": "boolean"}}}
        )

        # Start callback execution
        callback_task = asyncio.create_task(callback(None, params))

        # Wait for elicitation to be created
        await asyncio.sleep(0.01)

        # Complete the elicitation
        pending = list(elicitation_service._pending.values())[0]
        result = ElicitResult(action="accept", content={"confirm": True})
        elicitation_service.complete_elicitation(pending.request_id, result)

        # Wait for callback to complete
        callback_result = await callback_task

        # Verify result
        assert callback_result.action == "accept"
        assert callback_result.content == {"confirm": True}

        # Cleanup
        tool_call_registry.unregister_tool_call(tool_call_id)

    @pytest.mark.asyncio
    async def test_elicitation_callback_timeout_path(
        self, tool_service, elicitation_service, tool_call_registry
    ):
        """Test elicitation callback timeout error path."""
        tool_call_id = str(uuid4())
        session_id = "session-with-capability"

        # Register tool call
        tool_call_registry.register_tool_call(tool_call_id, session_id)

        # Mock session registry
        mock_registry = MagicMock()
        mock_registry.has_elicitation_capability = AsyncMock(return_value=True)

        with patch("mcpgateway.main.session_registry", mock_registry):
            with patch("mcpgateway.services.tool_service.get_elicitation_service", return_value=elicitation_service):
                with patch("mcpgateway.services.tool_service.get_tool_call_registry", return_value=tool_call_registry):
                    # Create callback
                    callback = await tool_service._create_elicitation_callback_for_tool_invocation(
                        tool_call_id=tool_call_id,
                        downstream_session_id=session_id,
                    )

        # Execute callback with very short timeout
        params = ElicitRequestParams(
            message="Confirm action?",
            requestedSchema={"type": "object", "properties": {"confirm": {"type": "boolean"}}}
        )

        # Mock create_elicitation to timeout
        async def timeout_elicitation(*args, **kwargs):
            raise asyncio.TimeoutError("Elicitation timed out")

        with patch.object(elicitation_service, "create_elicitation", side_effect=timeout_elicitation):
            result = await callback(None, params)

        # Verify timeout error
        assert isinstance(result, types.ErrorData)
        assert result.code == -32000
        assert "timed out" in result.message.lower()

        # Cleanup
        tool_call_registry.unregister_tool_call(tool_call_id)

    @pytest.mark.asyncio
    async def test_elicitation_callback_exception_path(
        self, tool_service, elicitation_service, tool_call_registry
    ):
        """Test elicitation callback exception handling."""
        tool_call_id = str(uuid4())
        session_id = "session-with-capability"

        # Register tool call
        tool_call_registry.register_tool_call(tool_call_id, session_id)

        # Mock session registry
        mock_registry = MagicMock()
        mock_registry.has_elicitation_capability = AsyncMock(return_value=True)

        with patch("mcpgateway.main.session_registry", mock_registry):
            with patch("mcpgateway.services.tool_service.get_elicitation_service", return_value=elicitation_service):
                with patch("mcpgateway.services.tool_service.get_tool_call_registry", return_value=tool_call_registry):
                    # Create callback
                    callback = await tool_service._create_elicitation_callback_for_tool_invocation(
                        tool_call_id=tool_call_id,
                        downstream_session_id=session_id,
                    )

        # Execute callback with exception
        params = ElicitRequestParams(
            message="Confirm action?",
            requestedSchema={"type": "object", "properties": {"confirm": {"type": "boolean"}}}
        )

        # Mock create_elicitation to raise exception
        async def raise_exception(*args, **kwargs):
            raise ValueError("Test exception")

        with patch.object(elicitation_service, "create_elicitation", side_effect=raise_exception):
            result = await callback(None, params)

        # Verify error response
        assert isinstance(result, types.ErrorData)
        assert result.code == -32603
        assert "internal error" in result.message.lower()

        # Cleanup
        tool_call_registry.unregister_tool_call(tool_call_id)

    @pytest.mark.asyncio
    async def test_callback_with_disabled_elicitation(self, tool_service, monkeypatch):
        """Test callback returns None when elicitation is disabled."""
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
    async def test_callback_with_no_downstream_session(self, tool_service):
        """Test callback returns None when no downstream session."""
        tool_call_id = str(uuid4())

        callback = await tool_service._create_elicitation_callback_for_tool_invocation(
            tool_call_id=tool_call_id,
            downstream_session_id=None,
        )

        # Verify callback is None
        assert callback is None

    @pytest.mark.asyncio
    async def test_callback_with_empty_downstream_session(self, tool_service):
        """Test callback returns None when downstream session is empty string."""
        tool_call_id = str(uuid4())

        callback = await tool_service._create_elicitation_callback_for_tool_invocation(
            tool_call_id=tool_call_id,
            downstream_session_id="",
        )

        # Verify callback is None
        assert callback is None
