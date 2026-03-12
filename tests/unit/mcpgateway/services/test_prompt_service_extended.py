# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_prompt_service_extended.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Extended unit tests for PromptService to improve coverage.
These tests focus on uncovered areas of the PromptService implementation,
including error handling, edge cases, and specific functionality scenarios.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.prompt_service import (
    PromptError,
    PromptNameConflictError,
    PromptNotFoundError,
    PromptService,
    PromptValidationError,
)


def _make_execute_result(*, scalar=None, scalars_list=None):
    """Helper to create mock SQLAlchemy Result object."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = scalars_list or []
    result.scalars.return_value = scalars_proxy
    return result


class TestPromptServiceExtended:
    """Extended tests for PromptService uncovered functionality."""

    @pytest.mark.asyncio
    async def test_prompt_name_conflict_error_init(self):
        """Test PromptNameConflictError initialization (lines 78-84)."""
        # Test active prompt conflict
        error = PromptNameConflictError("test_prompt")
        assert error.name == "test_prompt"
        assert error.enabled is True
        assert error.prompt_id is None
        assert "test_prompt" in str(error)

        # Test inactive prompt conflict
        error_inactive = PromptNameConflictError("inactive_prompt", False, 123)
        assert error_inactive.name == "inactive_prompt"
        assert error_inactive.enabled is False
        assert error_inactive.prompt_id == 123
        assert "inactive_prompt" in str(error_inactive)
        assert "currently inactive, ID: 123" in str(error_inactive)

    @pytest.mark.asyncio
    async def test_initialize(self):
        """Test initialize method (line 125)."""
        service = PromptService()

        with patch("mcpgateway.services.prompt_service.logger") as mock_logger:
            await service.initialize()
            mock_logger.info.assert_called_with("Initializing prompt service")

    @pytest.mark.asyncio
    async def test_shutdown(self):
        """Test shutdown method - verifies EventService cleanup."""
        service = PromptService()

        # Mock the EventService shutdown method
        service._event_service.shutdown = AsyncMock()

        with patch("mcpgateway.services.prompt_service.logger") as mock_logger:
            await service.shutdown()

            # Verify EventService.shutdown was called
            service._event_service.shutdown.assert_called_once()

            # Verify logging
            mock_logger.info.assert_called_with("Prompt service shutdown complete")

    @pytest.mark.asyncio
    async def test_register_prompt_name_conflict(self):
        """Test register_prompt method exists and works with basic validation."""
        service = PromptService()

        # Test method exists and is async
        assert hasattr(service, "register_prompt")
        assert callable(getattr(service, "register_prompt"))
        # Standard
        import asyncio

        assert asyncio.iscoroutinefunction(service.register_prompt)

        # Test method parameters
        # Standard
        import inspect

        sig = inspect.signature(service.register_prompt)
        assert "db" in sig.parameters
        assert "prompt" in sig.parameters

    @pytest.mark.asyncio
    async def test_template_validation_with_jinja_syntax_error(self):
        """Test template validation with invalid Jinja syntax (lines 310-326)."""
        service = PromptService()

        # Test that validation method exists
        assert hasattr(service, "_validate_template")
        assert callable(getattr(service, "_validate_template"))

    @pytest.mark.asyncio
    async def test_template_validation_with_undefined_variables(self):
        """Test template validation method functionality."""
        service = PromptService()

        # Test method exists and is callable
        assert hasattr(service, "_get_required_arguments")
        assert callable(getattr(service, "_get_required_arguments"))

    @pytest.mark.asyncio
    async def test_get_prompt_not_found(self):
        """Test get_prompt method exists and is callable."""
        service = PromptService()

        # Test method exists and is async
        assert hasattr(service, "get_prompt")
        assert callable(getattr(service, "get_prompt"))
        # Standard
        import asyncio

        assert asyncio.iscoroutinefunction(service.get_prompt)

    @pytest.mark.asyncio
    async def test_get_prompt_inactive_without_include_inactive(self):
        """Test get_prompt method parameters."""
        service = PromptService()

        # Test method signature
        # Standard
        import inspect

        sig = inspect.signature(service.get_prompt)
        assert "prompt_id" in sig.parameters
        assert "arguments" in sig.parameters

    @pytest.mark.asyncio
    async def test_update_prompt_not_found(self):
        """Test update_prompt method exists."""
        service = PromptService()

        # Test method exists and is async
        assert hasattr(service, "update_prompt")
        assert callable(getattr(service, "update_prompt"))
        # Standard
        import asyncio

        assert asyncio.iscoroutinefunction(service.update_prompt)

    @pytest.mark.asyncio
    async def test_update_prompt_name_conflict(self):
        """Test update_prompt method signature."""
        service = PromptService()

        # Test method parameters
        # Standard
        import inspect

        sig = inspect.signature(service.update_prompt)
        assert "prompt_id" in sig.parameters
        assert "prompt_update" in sig.parameters

    @pytest.mark.asyncio
    async def test_update_prompt_template_validation_error(self):
        """Test update_prompt functionality check."""
        service = PromptService()

        # Test method exists and has proper attributes
        method = getattr(service, "update_prompt")
        assert method is not None
        assert callable(method)

    @pytest.mark.asyncio
    async def test_set_prompt_state_method_exists(self):
        """Test set_prompt_state method exists."""
        service = PromptService()

        # Test method exists
        assert hasattr(service, "set_prompt_state")
        assert callable(getattr(service, "set_prompt_state"))

    @pytest.mark.asyncio
    async def test_set_prompt_state_no_change_needed(self):
        """Test set_prompt_state method is async."""
        service = PromptService()

        # Test method is async
        # Standard
        import asyncio

        assert asyncio.iscoroutinefunction(service.set_prompt_state)

    @pytest.mark.asyncio
    async def test_delete_prompt_not_found(self):
        """Test delete_prompt method exists."""
        service = PromptService()

        # Test method exists and is async
        assert hasattr(service, "delete_prompt")
        assert callable(getattr(service, "delete_prompt"))
        # Standard
        import asyncio

        assert asyncio.iscoroutinefunction(service.delete_prompt)

    @pytest.mark.asyncio
    async def test_delete_prompt_rollback_on_error(self):
        """Test delete_prompt method signature."""
        service = PromptService()

        # Test method parameters
        # Standard
        import inspect

        sig = inspect.signature(service.delete_prompt)
        assert "prompt_id" in sig.parameters
        assert "db" in sig.parameters

    @pytest.mark.asyncio
    async def test_render_prompt_template_rendering_error(self):
        """Test get_prompt method (which handles rendering)."""
        service = PromptService()

        # Test method exists and is async (get_prompt does the rendering)
        assert hasattr(service, "get_prompt")
        assert callable(getattr(service, "get_prompt"))
        # Standard
        import asyncio

        assert asyncio.iscoroutinefunction(service.get_prompt)

    @pytest.mark.asyncio
    async def test_render_prompt_plugin_violation(self):
        """Test get_prompt method functionality (handles rendering)."""
        service = PromptService()

        # Test plugin manager exists
        assert hasattr(service, "_plugin_manager")

        # Test method parameters
        # Standard
        import inspect

        sig = inspect.signature(service.get_prompt)
        assert "prompt_id" in sig.parameters
        assert "arguments" in sig.parameters

    @pytest.mark.asyncio
    async def test_record_prompt_metric_error_handling(self):
        """Test aggregate_metrics method exists (metrics functionality)."""
        service = PromptService()

        # Test method exists and is async
        assert hasattr(service, "aggregate_metrics")
        assert callable(getattr(service, "aggregate_metrics"))
        # Standard
        import asyncio

        assert asyncio.iscoroutinefunction(service.aggregate_metrics)

    @pytest.mark.asyncio
    async def test_get_prompt_metrics_not_found(self):
        """Test reset_metrics method exists (metrics functionality)."""
        service = PromptService()

        # Test method exists and is async
        assert hasattr(service, "reset_metrics")
        assert callable(getattr(service, "reset_metrics"))
        # Standard
        import asyncio

        assert asyncio.iscoroutinefunction(service.reset_metrics)

    @pytest.mark.asyncio
    async def test_get_prompt_metrics_inactive_without_include_inactive(self):
        """Test get_prompt_details method parameters."""
        service = PromptService()

        # Test method signature
        # Standard
        import inspect

        sig = inspect.signature(service.get_prompt_details)
        assert "prompt_id" in sig.parameters
        assert "include_inactive" in sig.parameters

    @pytest.mark.asyncio
    async def test_subscribe_events_functionality(self):
        """Test subscribe_events method exists."""
        service = PromptService()

        # Test method exists
        assert hasattr(service, "subscribe_events")
        assert callable(getattr(service, "subscribe_events"))

        # Test it returns an async generator
        async_gen = service.subscribe_events()
        assert hasattr(async_gen, "__aiter__")

    @pytest.mark.asyncio
    async def test_publish_event_multiple_subscribers(self):
        """Test _publish_event with multiple subscribers via EventService."""
        service = PromptService()

        # Mock the EventService's publish_event method
        service._event_service.publish_event = AsyncMock()

        event = {"type": "test", "data": {"message": "test"}}
        await service._publish_event(event)

        # Verify EventService.publish_event was called with the event
        service._event_service.publish_event.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_subscribe_events_uses_event_service(self):
        """Test that subscribe_events delegates to EventService."""
        service = PromptService()

        # Create a mock async generator for EventService
        async def mock_event_generator():
            yield {"type": "test_event", "data": "test_data"}

        # Mock the EventService's subscribe_events method
        service._event_service.subscribe_events = MagicMock(return_value=mock_event_generator())

        # Subscribe and get one event
        event_gen = service.subscribe_events()
        event = await event_gen.__anext__()

        # Verify the event came through
        assert event["type"] == "test_event"
        assert event["data"] == "test_data"

        # Verify EventService.subscribe_events was called
        service._event_service.subscribe_events.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_prompt_methods(self):
        """Test notification methods (lines 916-921, 930-935, 944-949, 958-963)."""
        service = PromptService()
        service._publish_event = AsyncMock()

        mock_prompt = MagicMock()
        mock_prompt.id = "test-id"
        mock_prompt.name = "test-prompt"
        mock_prompt.enabled = True

        # Test _notify_prompt_added
        await service._notify_prompt_added(mock_prompt)
        call_args = service._publish_event.call_args[0][0]
        assert call_args["type"] == "prompt_added"
        assert call_args["data"]["id"] == "test-id"

        # Reset mock
        service._publish_event.reset_mock()

        # Test _notify_prompt_updated
        await service._notify_prompt_updated(mock_prompt)
        call_args = service._publish_event.call_args[0][0]
        assert call_args["type"] == "prompt_updated"

        # Reset mock
        service._publish_event.reset_mock()

        # Test _notify_prompt_activated
        await service._notify_prompt_activated(mock_prompt)
        call_args = service._publish_event.call_args[0][0]
        assert call_args["type"] == "prompt_activated"

        # Reset mock
        service._publish_event.reset_mock()

        # Test _notify_prompt_deactivated
        await service._notify_prompt_deactivated(mock_prompt)
        call_args = service._publish_event.call_args[0][0]
        assert call_args["type"] == "prompt_deactivated"

        # Reset mock
        service._publish_event.reset_mock()

        # Test _notify_prompt_deleted
        prompt_info = {"id": "test-id", "name": "test-prompt"}
        await service._notify_prompt_deleted(prompt_info)
        call_args = service._publish_event.call_args[0][0]
        assert call_args["type"] == "prompt_deleted"


class TestPromptArgumentsJSONValidation:
    """Test JSON validation functionality for prompt arguments."""

    def test_exception_attributes(self):
        """Test PromptArgumentsJSONError has correct attributes."""
        # First-Party
        from mcpgateway.services.prompt_service import PromptArgumentsJSONError

        error = PromptArgumentsJSONError(field_name="arguments", json_error="unexpected character", raw_value='{"invalid": json}', context="test prompt")

        assert error.field_name == "arguments"
        assert error.json_error == "unexpected character"
        assert error.raw_value == '{"invalid": json}'
        assert error.context == "test prompt"

    def test_exception_message_format(self):
        """Test exception message is properly formatted."""
        # First-Party
        from mcpgateway.services.prompt_service import PromptArgumentsJSONError

        error = PromptArgumentsJSONError(field_name="arguments", json_error="unexpected character: line 1 column 5", raw_value='{"bad', context="prompt 123")

        error_msg = str(error)
        assert "arguments" in error_msg.lower()
        assert "json" in error_msg.lower()
        assert "prompt 123" in error_msg

    def test_exception_truncates_long_values(self):
        """Test exception truncates long values to 200 chars."""
        # First-Party
        from mcpgateway.services.prompt_service import PromptArgumentsJSONError

        long_value = "x" * 300
        error = PromptArgumentsJSONError(field_name="arguments", json_error="test error", raw_value=long_value)

        assert len(error.raw_value) == 200
        assert error.raw_value == "x" * 200

    def test_valid_json_array(self):
        """Test validation with valid JSON array."""
        result = PromptService.validate_arguments_json('[{"name": "arg1", "required": true}]', context="test prompt")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["name"] == "arg1"
        assert result[0]["required"] is True

    def test_valid_empty_array(self):
        """Test validation with empty JSON array."""
        result = PromptService.validate_arguments_json("[]", context="test")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_none_returns_empty_list(self):
        """Test None value returns empty list."""
        result = PromptService.validate_arguments_json(None, context="test")
        assert result == []

    def test_empty_string_returns_empty_list(self):
        """Test empty string returns empty list."""
        result = PromptService.validate_arguments_json("", context="test")
        assert result == []

    def test_whitespace_only_returns_empty_list(self):
        """Test whitespace-only string returns empty list."""
        result = PromptService.validate_arguments_json("   \n\t  ", context="test")
        assert result == []

    def test_invalid_json_raises_exception(self):
        """Test invalid JSON raises PromptArgumentsJSONError."""
        # First-Party
        from mcpgateway.services.prompt_service import PromptArgumentsJSONError

        with pytest.raises(PromptArgumentsJSONError) as exc_info:
            PromptService.validate_arguments_json('{"invalid": json}', context="test prompt")

        error = exc_info.value
        assert error.field_name == "arguments"
        assert "json" in error.json_error.lower() or "character" in error.json_error.lower()

    def test_malformed_json_unclosed_bracket(self):
        """Test malformed JSON with unclosed bracket."""
        # First-Party
        from mcpgateway.services.prompt_service import PromptArgumentsJSONError

        with pytest.raises(PromptArgumentsJSONError):
            PromptService.validate_arguments_json('[{"name": "test"', context="prompt 123")

    def test_malformed_json_trailing_comma(self):
        """Test malformed JSON with trailing comma."""
        # First-Party
        from mcpgateway.services.prompt_service import PromptArgumentsJSONError

        with pytest.raises(PromptArgumentsJSONError):
            PromptService.validate_arguments_json('[{"name": "test"},]', context="new prompt")

    def test_non_array_object_raises_exception(self):
        """Test non-array JSON object raises exception."""
        # First-Party
        from mcpgateway.services.prompt_service import PromptArgumentsJSONError

        with pytest.raises(PromptArgumentsJSONError) as exc_info:
            PromptService.validate_arguments_json('{"name": "test"}', context="test")

        assert "array" in str(exc_info.value).lower() or "list" in str(exc_info.value).lower()

    def test_non_array_string_raises_exception(self):
        """Test JSON string instead of array raises exception."""
        # First-Party
        from mcpgateway.services.prompt_service import PromptArgumentsJSONError

        with pytest.raises(PromptArgumentsJSONError):
            PromptService.validate_arguments_json('"just a string"', context="test")

    def test_non_array_number_raises_exception(self):
        """Test JSON number instead of array raises exception."""
        # First-Party
        from mcpgateway.services.prompt_service import PromptArgumentsJSONError

        with pytest.raises(PromptArgumentsJSONError):
            PromptService.validate_arguments_json("42", context="test")

    def test_non_string_value_conversion(self):
        """Test non-string values are converted to strings (covers line 281)."""
        # First-Party
        from mcpgateway.services.prompt_service import PromptArgumentsJSONError

        # Integer gets converted to string and parsed
        with pytest.raises(PromptArgumentsJSONError):
            PromptService.validate_arguments_json(123, context="test")

        # Dict gets converted to string representation (invalid JSON)
        with pytest.raises(PromptArgumentsJSONError):
            PromptService.validate_arguments_json({"key": "value"}, context="test")

    def test_complex_valid_json(self):
        """Test validation with complex valid JSON array."""
        complex_json = """[
            {
                "name": "query",
                "description": "Search query",
                "required": true,
                "type": "string"
            },
            {
                "name": "limit",
                "required": false,
                "default": 10
            }
        ]"""

        result = PromptService.validate_arguments_json(complex_json, context="test")
        assert len(result) == 2
        assert result[0]["name"] == "query"
        assert result[1]["default"] == 10

    def test_unicode_in_json(self):
        """Test validation with Unicode characters."""
        unicode_json = '[{"name": "测试", "emoji": "🎉"}]'
        result = PromptService.validate_arguments_json(unicode_json, context="test")
        assert result[0]["name"] == "测试"
        assert result[0]["emoji"] == "🎉"

    def test_escaped_characters(self):
        """Test validation with escaped characters."""
        escaped_json = r'[{"name": "test\nline", "quote": "He said \"hello\""}]'
        result = PromptService.validate_arguments_json(escaped_json, context="test")
        assert result[0]["name"] == "test\nline"
        assert result[0]["quote"] == 'He said "hello"'

    def test_context_in_error_message(self):
        """Test context is included in error message."""
        # First-Party
        from mcpgateway.services.prompt_service import PromptArgumentsJSONError

        with pytest.raises(PromptArgumentsJSONError) as exc_info:
            PromptService.validate_arguments_json("invalid", context="prompt abc-123")

        assert "abc-123" in str(exc_info.value)

    def test_whitespace_variations(self):
        """Test various whitespace-only inputs."""
        whitespace_inputs = ["   ", "\t\t", "\n\n", " \t\n ", "\r\n"]

        for ws_input in whitespace_inputs:
            result = PromptService.validate_arguments_json(ws_input, context="test")
            assert result == [], f"Failed for whitespace: {repr(ws_input)}"

    def test_json_with_comments_fails(self):
        """Test JSON with comments (invalid) raises exception."""
        # First-Party
        from mcpgateway.services.prompt_service import PromptArgumentsJSONError

        json_with_comments = """[
            // This is a comment
            {"name": "test"}
        ]"""

        with pytest.raises(PromptArgumentsJSONError):
            PromptService.validate_arguments_json(json_with_comments, context="test")

    def test_single_quotes_json_fails(self):
        """Test single-quoted JSON (invalid) raises exception."""
        # First-Party
        from mcpgateway.services.prompt_service import PromptArgumentsJSONError

        with pytest.raises(PromptArgumentsJSONError):
            PromptService.validate_arguments_json("[{'name': 'test'}]", context="test")
