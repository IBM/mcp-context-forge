# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_logging_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit-tests for the LoggingService.
Key details
-----------
`LoggingService.subscribe()` registers the subscriber *inside* the first
iteration of the coroutine.  If we fire `notify()` immediately after calling
`asyncio.create_task(subscriber())`, the subscriber's coroutine may not have
run yet, so no queue is registered and the message is lost.

The fix is a single `await asyncio.sleep(0)` (one event-loop tick) after
`create_task(...)` in the two tests that wait for a message.  This guarantees
the subscriber is fully set up before we emit the first log event.
"""

# Standard
import asyncio
from datetime import datetime
import logging
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import LogLevel
from mcpgateway.services.logging_service import CorrelationIdJsonFormatter, LoggingService, StorageHandler

# ---------------------------------------------------------------------------
# Basic behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_log_default_levels():
    service = LoggingService()
    # Default level is INFO
    assert not service._should_log(LogLevel.DEBUG)
    assert service._should_log(LogLevel.INFO)
    assert service._should_log(LogLevel.ERROR)


@pytest.mark.asyncio
async def test_get_logger_sets_level_and_reuses_instance():
    service = LoggingService()

    # First call - default level INFO
    logger1 = service.get_logger("test")
    assert logger1.level == logging.INFO

    # Same logger object returned on second call
    logger2 = service.get_logger("test")
    assert logger1 is logger2

    # After raising service level to DEBUG a *new* logger inherits that level
    await service.set_level(LogLevel.DEBUG)
    logger3 = service.get_logger("newlogger")
    assert logger3.level == logging.DEBUG


# ---------------------------------------------------------------------------
# notify() when nobody is listening
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_without_subscribers_logs_via_standard_logging(caplog):
    service = LoggingService()
    caplog.set_level(logging.INFO)

    # No subscribers → should simply log via stdlib logging
    await service.notify("standalone message", LogLevel.INFO)
    assert "standalone message" in caplog.text


# ---------------------------------------------------------------------------
# notify() below threshold is ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_below_threshold_does_not_send_to_subscribers():
    service = LoggingService()
    events = []

    async def subscriber():
        async for msg in service.subscribe():
            events.append(msg)

    task = asyncio.create_task(subscriber())
    await asyncio.sleep(0)  # ensure subscriber registered

    # DEBUG is below default INFO → should be ignored
    await service.notify("debug msg", LogLevel.DEBUG)
    await asyncio.sleep(0.1)  # allow any unexpected deliveries

    assert events == []

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ---------------------------------------------------------------------------
# Race-condition-safe tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_and_subscribe_receive_message_with_metadata():
    """
    Verify a subscriber receives a message together with metadata.

    The tiny ``await asyncio.sleep(0)`` after creating the task ensures the
    subscriber has entered its coroutine and registered its queue before
    ``notify`` is called - otherwise the message could be lost.
    """
    service = LoggingService()
    events = []

    async def subscriber():
        async for msg in service.subscribe():
            events.append(msg)
            break  # stop after first event

    task = asyncio.create_task(subscriber())
    await asyncio.sleep(0)  # <─ critical: let the subscriber register

    await service.notify("hello world", LogLevel.INFO, logger_name="mylogger")
    await asyncio.wait_for(task, timeout=1.0)

    # Validate structure
    assert len(events) == 1
    evt = events[0]
    assert evt["type"] == "log"
    data = evt["data"]
    assert data["level"] == LogLevel.INFO
    assert data["data"] == "hello world"
    datetime.fromisoformat(data["timestamp"])  # no exception
    assert data["logger"] == "mylogger"

    await service.shutdown()


@pytest.mark.asyncio
async def test_set_level_updates_all_loggers_and_sends_info_notification():
    """
    After raising the service level to WARNING an INFO-level notification
    is *below* the new threshold, so no event is delivered.  We therefore
    assert that the subscriber receives nothing and that existing loggers
    have been updated.
    """
    service = LoggingService()
    events = []

    async def subscriber():
        async for msg in service.subscribe():
            events.append(msg)

    task = asyncio.create_task(subscriber())
    await asyncio.sleep(0)  # ensure subscriber is registered

    # Change level to WARNING
    await service.set_level(LogLevel.WARNING)
    await asyncio.sleep(0.1)  # allow any unexpected deliveries

    # No events should have been delivered
    assert events == []

    # Root logger level must reflect the change
    root_logger = service.get_logger("")
    assert root_logger.level == logging.WARNING

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ---------------------------------------------------------------------------
# subscribe() cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_cleanup_removes_queue_on_cancel():
    service = LoggingService()

    # No subscribers initially
    assert len(service._subscribers) == 0

    agen = service.subscribe()
    task = asyncio.create_task(agen.__anext__())

    # Subscriber should now be registered
    await asyncio.sleep(0)
    assert len(service._subscribers) == 1

    # Cancel the pending receive to trigger ``finally`` block cleanup
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(service._subscribers) == 0


# ---------------------------------------------------------------------------
# httpx URL sanitize filter
# ---------------------------------------------------------------------------


class TestHttpxUrlSanitizeFilter:
    """Tests for the httpx/httpcore URL sanitization filter."""

    @staticmethod
    def _get_filter():
        """Install the filter and return it."""
        LoggingService._install_httpx_url_sanitize_filter()
        httpx_logger = logging.getLogger("httpx")
        return [f for f in httpx_logger.filters if f.__class__.__name__ == "_HttpxUrlSanitizeFilter"][-1]

    def test_redacts_api_key_in_httpx_message(self):
        filt = self._get_filter()
        record = logging.makeLogRecord(
            {
                "name": "httpx",
                "msg": 'HTTP Request: GET https://example.mcp.server.com/sse?api_key=secret-value "HTTP/1.1 200 OK"',
            }
        )
        result = filt.filter(record)
        assert result is True
        assert "secret-value" not in record.getMessage()
        assert "api_key=REDACTED" in record.getMessage()

    def test_redacts_token_in_httpx_message(self):
        filt = self._get_filter()
        record = logging.makeLogRecord(
            {
                "name": "httpx",
                "msg": "HTTP Request: GET https://api.example.com/path?token=my-secret&q=search \"HTTP/1.1 200 OK\"",
            }
        )
        filt.filter(record)
        assert "my-secret" not in record.getMessage()
        assert "token=REDACTED" in record.getMessage()
        assert "q=search" in record.getMessage()

    def test_no_modification_when_no_sensitive_params(self):
        filt = self._get_filter()
        original_msg = 'HTTP Request: GET https://example.mcp.server.com/sse?page=1&limit=10 "HTTP/1.1 200 OK"'
        record = logging.makeLogRecord({"name": "httpx", "msg": original_msg})
        filt.filter(record)
        assert record.getMessage() == original_msg

    def test_no_modification_when_no_url(self):
        filt = self._get_filter()
        original_msg = "Connection pool established"
        record = logging.makeLogRecord({"name": "httpx", "msg": original_msg})
        filt.filter(record)
        assert record.getMessage() == original_msg

    def test_filter_installed_on_httpcore(self):
        LoggingService._install_httpx_url_sanitize_filter()
        httpcore_logger = logging.getLogger("httpcore")
        filter_names = [f.__class__.__name__ for f in httpcore_logger.filters]
        assert "_HttpxUrlSanitizeFilter" in filter_names

    def test_handles_format_args_gracefully(self):
        filt = self._get_filter()
        record = logging.makeLogRecord(
            {
                "name": "httpx",
                "msg": "Request to %s completed with status %d",
                "args": ("https://example.mcp.server.com/sse?api_key=secret123", 200),
            }
        )
        filt.filter(record)
        msg = record.getMessage()
        assert "secret123" not in msg
        assert "api_key=REDACTED" in msg

    def test_filter_survives_getMessage_exception(self):
        """Cover the except-Exception branch (lines 531-532): getMessage() raises TypeError."""
        filt = self._get_filter()
        # "%s %s" with only one arg causes TypeError in getMessage()
        record = logging.makeLogRecord(
            {
                "name": "httpx",
                "msg": "Request to %s with status %d",
                "args": ("only-one-arg",),  # too few args → TypeError
            }
        )
        # Must not raise; filter always returns True even when sanitization fails
        result = filt.filter(record)
        assert result is True


# ---------------------------------------------------------------------------
# CorrelationIdJsonFormatter – lines 119, 123-134
# ---------------------------------------------------------------------------


class TestCorrelationIdJsonFormatter:
    """Tests for CorrelationIdJsonFormatter.add_fields (correlation ID and OTEL trace context)."""

    def _make_record(self) -> logging.LogRecord:
        return logging.LogRecord(name="test", level=logging.INFO, pathname="", lineno=0, msg="hello", args=(), exc_info=None)

    def test_adds_correlation_id_when_present(self):
        """Line 119: correlation_id is truthy → request_id is added."""
        formatter = CorrelationIdJsonFormatter()
        record = self._make_record()
        log_record: dict = {}
        with patch("mcpgateway.services.logging_service.get_correlation_id", return_value="req-abc-123"):
            formatter.add_fields(log_record, record, {})
        assert log_record["request_id"] == "req-abc-123"

    def test_no_correlation_id_when_absent(self):
        """Line 117-118: correlation_id is falsy → request_id is not added."""
        formatter = CorrelationIdJsonFormatter()
        record = self._make_record()
        log_record: dict = {}
        with patch("mcpgateway.services.logging_service.get_correlation_id", return_value=None):
            formatter.add_fields(log_record, record, {})
        assert "request_id" not in log_record

    def test_adds_otel_trace_context(self):
        """Lines 123-131: span is recording and valid → trace_id, span_id, trace_flags added."""
        formatter = CorrelationIdJsonFormatter()
        record = self._make_record()
        log_record: dict = {}

        mock_span_context = MagicMock()
        mock_span_context.is_valid = True
        mock_span_context.trace_id = 0x0A0B0C0D0E0F1011121314151617181A
        mock_span_context.span_id = 0x0102030405060708
        mock_span_context.trace_flags = 1

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        mock_span.get_span_context.return_value = mock_span_context

        mock_trace = MagicMock()
        mock_trace.get_current_span.return_value = mock_span

        with patch("mcpgateway.services.logging_service.get_correlation_id", return_value=None):
            with patch("mcpgateway.services.logging_service.trace", mock_trace):
                formatter.add_fields(log_record, record, {})

        assert log_record["trace_id"] == format(mock_span_context.trace_id, "032x")
        assert log_record["span_id"] == format(mock_span_context.span_id, "016x")
        assert log_record["trace_flags"] == "01"

    def test_otel_span_not_recording(self):
        """Lines 125: span is not recording → no trace fields."""
        formatter = CorrelationIdJsonFormatter()
        record = self._make_record()
        log_record: dict = {}

        mock_span = MagicMock()
        mock_span.is_recording.return_value = False

        mock_trace = MagicMock()
        mock_trace.get_current_span.return_value = mock_span

        with patch("mcpgateway.services.logging_service.get_correlation_id", return_value=None):
            with patch("mcpgateway.services.logging_service.trace", mock_trace):
                formatter.add_fields(log_record, record, {})

        assert "trace_id" not in log_record

    def test_otel_exception_is_swallowed(self):
        """Lines 132-134: exception in span access → silently caught, no trace fields."""
        formatter = CorrelationIdJsonFormatter()
        record = self._make_record()
        log_record: dict = {}

        mock_trace = MagicMock()
        mock_trace.get_current_span.side_effect = RuntimeError("otel broken")

        with patch("mcpgateway.services.logging_service.get_correlation_id", return_value=None):
            with patch("mcpgateway.services.logging_service.trace", mock_trace):
                formatter.add_fields(log_record, record, {})

        assert "trace_id" not in log_record


# ---------------------------------------------------------------------------
# StorageHandler.emit – lines 260-264
# ---------------------------------------------------------------------------


class TestStorageHandlerEmitFallback:
    """Tests for StorageHandler.emit fallback paths (no running loop, outer exception)."""

    def test_emit_schedules_on_known_loop_when_no_running_loop(self):
        """Lines 260-261: no running loop but self.loop is set and running → run_coroutine_threadsafe."""
        mock_storage = MagicMock()
        mock_coro = AsyncMock()()
        mock_storage.add_log = MagicMock(return_value=mock_coro)

        handler = StorageHandler(mock_storage)

        # Simulate a previously cached running loop
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        handler.loop = mock_loop

        mock_future = MagicMock()

        record = logging.makeLogRecord({"name": "test", "msg": "hello", "levelname": "INFO"})

        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            with patch("asyncio.run_coroutine_threadsafe", return_value=mock_future) as mock_rcts:
                handler.emit(record)

        mock_rcts.assert_called_once()
        mock_future.add_done_callback.assert_called_once()

    def test_emit_outer_exception_is_swallowed(self):
        """Lines 262-264: outer exception in emit → silently caught."""
        mock_storage = MagicMock()
        mock_storage.add_log = MagicMock(side_effect=RuntimeError("storage broken"))

        handler = StorageHandler(mock_storage)
        record = logging.makeLogRecord({"name": "test", "msg": "hello", "levelname": "INFO"})

        # Should not raise
        handler.emit(record)


# ---------------------------------------------------------------------------
# LoggingService.initialize – lines 330-331 (JSON console handler)
# ---------------------------------------------------------------------------


class TestInitializeJsonConsoleHandler:
    """Test that initialize() creates a JSON console handler when log_format is 'json'."""

    @pytest.mark.asyncio
    async def test_initialize_json_log_format(self):
        """Lines 330-331: settings.log_format == 'json' → StreamHandler with json_formatter."""
        service = LoggingService()

        with patch("mcpgateway.services.logging_service.settings") as mock_settings:
            mock_settings.log_level = "INFO"
            mock_settings.log_format = "json"
            mock_settings.log_to_file = False
            mock_settings.log_file = None
            mock_settings.mcpgateway_ui_enabled = False
            mock_settings.mcpgateway_admin_api_enabled = False

            await service.initialize()

        root_logger = logging.getLogger()
        # Find a handler using the json_formatter
        from mcpgateway.services.logging_service import json_formatter

        json_handlers = [h for h in root_logger.handlers if h.formatter is json_formatter]
        assert len(json_handlers) >= 1

        await service.shutdown()


# ---------------------------------------------------------------------------
# _SuppressClosedResourceErrorFilter – lines 457-478
# ---------------------------------------------------------------------------


class TestSuppressClosedResourceErrorFilter:
    """Tests for the ClosedResourceError suppression filter installed by LoggingService."""

    @staticmethod
    def _get_filter():
        """Install the filter and return it."""
        service = LoggingService()
        service._install_closedresourceerror_filter()
        target = logging.getLogger("mcp.server.streamable_http")
        return [f for f in target.filters if f.__class__.__name__.endswith("SuppressClosedResourceErrorFilter")][-1]

    def test_non_target_logger_passes_through(self):
        """Line 457-458: record from a different logger → returns True."""
        filt = self._get_filter()
        record = logging.makeLogRecord({"name": "some.other.logger", "msg": "ClosedResourceError"})
        assert filt.filter(record) is True

    def test_target_logger_with_closedresourceerror_in_message(self):
        """Lines 472-473: target logger, message contains ClosedResourceError → returns False."""
        filt = self._get_filter()
        record = logging.makeLogRecord({"name": "mcp.server.streamable_http", "msg": "ClosedResourceError in normal shutdown"})
        assert filt.filter(record) is False

    def test_target_logger_with_closedresourceerror_exc_info(self):
        """Lines 462-465: target logger, exc_info with ClosedResourceError → returns False."""
        filt = self._get_filter()
        try:
            # Third-Party
            from anyio import ClosedResourceError

            exc = ClosedResourceError()
            record = logging.makeLogRecord(
                {
                    "name": "mcp.server.streamable_http",
                    "msg": "Error in message router",
                    "exc_info": (ClosedResourceError, exc, None),
                }
            )
            assert filt.filter(record) is False
        except ImportError:
            pytest.skip("anyio not installed")

    def test_target_logger_with_exc_type_name_match(self):
        """Lines 464-465: exc_type.__name__ == 'ClosedResourceError' but not isinstance → returns False."""
        filt = self._get_filter()

        class ClosedResourceError(Exception):
            pass

        exc = ClosedResourceError()
        record = logging.makeLogRecord(
            {
                "name": "mcp.server.streamable_http",
                "msg": "Error occurred",
                "exc_info": (ClosedResourceError, exc, None),
            }
        )
        with patch("mcpgateway.services.logging_service.AnyioClosedResourceError", Exception):
            assert filt.filter(record) is False

    def test_target_logger_normal_message_passes(self):
        """Line 478: target logger, no exc_info, normal message → returns True."""
        filt = self._get_filter()
        record = logging.makeLogRecord({"name": "mcp.server.streamable_http", "msg": "Normal operation"})
        assert filt.filter(record) is True

    def test_target_logger_getMessage_exception_is_swallowed(self):
        """Lines 474-477: getMessage() raises → exception caught, returns True."""
        filt = self._get_filter()
        record = logging.makeLogRecord({"name": "mcp.server.streamable_http", "msg": "format %s %d", "args": ("only-one",)})
        # Should not raise; returns True because the fallback catches the exception
        assert filt.filter(record) is True

    def test_exc_info_exception_returns_true(self):
        """Lines 467-469: exception during isinstance check → returns True (permissive)."""
        filt = self._get_filter()
        # Create a mock exc_type that raises on __name__ access and isinstance
        bad_exc_type = MagicMock()
        bad_exc_type.__name__ = property(lambda self: (_ for _ in ()).throw(RuntimeError("broken")))

        bad_exc = MagicMock()
        bad_exc.__class__ = bad_exc_type

        record = logging.makeLogRecord(
            {
                "name": "mcp.server.streamable_http",
                "msg": "Error occurred",
                "exc_info": (bad_exc_type, bad_exc, None),
            }
        )

        with patch("mcpgateway.services.logging_service.AnyioClosedResourceError", bad_exc_type):
            # isinstance will match (same type), so this may return False.
            # Use a type whose isinstance raises.
            pass

        # Use a different approach: make isinstance raise
        class BadMeta(type):
            def __instancecheck__(cls, instance):
                raise RuntimeError("isinstance broken")

        class BadType(metaclass=BadMeta):
            pass

        record2 = logging.makeLogRecord(
            {
                "name": "mcp.server.streamable_http",
                "msg": "No ClosedResource here",
                "exc_info": (BadType, "not-a-real-exc", None),
            }
        )
        with patch("mcpgateway.services.logging_service.AnyioClosedResourceError", BadType):
            result = filt.filter(record2)
        assert result is True
