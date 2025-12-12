# -*- coding: utf-8 -*-
"""Tests for correlation ID JSON formatter."""

import json
import logging
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import Mock, patch

import pytest

from mcpgateway.services.logging_service import CorrelationIdJsonFormatter
from mcpgateway.utils.correlation_id import set_correlation_id, clear_correlation_id


@pytest.fixture
def formatter():
    """Create a test JSON formatter."""
    return CorrelationIdJsonFormatter()


@pytest.fixture
def logger_with_formatter(formatter):
    """Create a test logger with JSON formatter."""
    logger = logging.getLogger("test_correlation_logger")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # Add string stream handler
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger, stream


def test_formatter_includes_correlation_id(logger_with_formatter):
    """Test that formatter includes correlation ID in log records."""
    logger, stream = logger_with_formatter

    # Set correlation ID
    test_id = "test-correlation-123"
    set_correlation_id(test_id)

    # Log a message
    logger.info("Test message")

    # Get the logged output
    output = stream.getvalue()
    log_record = json.loads(output.strip())

    # Should include correlation ID
    assert "request_id" in log_record
    assert log_record["request_id"] == test_id

    clear_correlation_id()


def test_formatter_without_correlation_id(logger_with_formatter):
    """Test formatter when correlation ID is not set."""
    logger, stream = logger_with_formatter

    # Clear any existing correlation ID
    clear_correlation_id()

    # Log a message
    logger.info("Test message without correlation ID")

    # Get the logged output
    output = stream.getvalue()
    log_record = json.loads(output.strip())

    # request_id should not be present
    assert "request_id" not in log_record or log_record.get("request_id") is None


def test_formatter_includes_standard_fields(logger_with_formatter):
    """Test that formatter includes standard log fields."""
    logger, stream = logger_with_formatter

    # Log a message
    logger.info("Standard fields test")

    # Get the logged output
    output = stream.getvalue()
    log_record = json.loads(output.strip())

    # Check for standard fields
    assert "message" in log_record
    assert log_record["message"] == "Standard fields test"
    assert "@timestamp" in log_record
    assert "hostname" in log_record
    assert "process_id" in log_record
    # Note: levelname is included by the JsonFormatter format string if specified


def test_formatter_includes_opentelemetry_trace_context(logger_with_formatter):
    """Test that formatter includes OpenTelemetry trace context when available."""
    logger, stream = logger_with_formatter

    # Mock OpenTelemetry span
    mock_span_context = Mock()
    mock_span_context.trace_id = 0x1234567890abcdef1234567890abcdef
    mock_span_context.span_id = 0x1234567890abcdef
    mock_span_context.trace_flags = 0x01
    mock_span_context.is_valid = True

    mock_span = Mock()
    mock_span.is_recording.return_value = True
    mock_span.get_span_context.return_value = mock_span_context

    with patch("mcpgateway.services.logging_service.trace") as mock_trace:
        mock_trace.get_current_span.return_value = mock_span

        # Log a message
        logger.info("Test with trace context")

        # Get the logged output
        output = stream.getvalue()
        log_record = json.loads(output.strip())

        # Should include trace context
        assert "trace_id" in log_record
        assert "span_id" in log_record
        assert "trace_flags" in log_record

        # Verify hex formatting
        assert log_record["trace_id"] == "1234567890abcdef1234567890abcdef"
        assert log_record["span_id"] == "1234567890abcdef"
        assert log_record["trace_flags"] == "01"


def test_formatter_handles_missing_opentelemetry(logger_with_formatter):
    """Test that formatter gracefully handles missing OpenTelemetry."""
    logger, stream = logger_with_formatter

    # Simulate ImportError for opentelemetry
    import sys
    with patch.dict(sys.modules, {"opentelemetry.trace": None}):
        # Log a message
        logger.info("Test without OpenTelemetry")

        # Get the logged output
        output = stream.getvalue()
        log_record = json.loads(output.strip())

        # Should not fail, just exclude trace fields
        assert "trace_id" not in log_record
        assert "span_id" not in log_record
        assert "message" in log_record


def test_formatter_timestamp_format(logger_with_formatter):
    """Test that timestamp is in ISO 8601 format with 'Z' suffix."""
    logger, stream = logger_with_formatter

    # Log a message
    logger.info("Timestamp test")

    # Get the logged output
    output = stream.getvalue()
    log_record = json.loads(output.strip())

    # Check timestamp format
    assert "@timestamp" in log_record
    timestamp = log_record["@timestamp"]

    # Should end with 'Z' (Zulu/UTC time)
    assert timestamp.endswith("Z")

    # Should be parseable as ISO 8601
    # Remove 'Z' and parse
    datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def test_formatter_with_extra_fields(logger_with_formatter):
    """Test that formatter includes extra fields from log record."""
    logger, stream = logger_with_formatter

    # Log with extra fields
    logger.info("Extra fields test", extra={"user_id": "user-123", "action": "login"})

    # Get the logged output
    output = stream.getvalue()
    log_record = json.loads(output.strip())

    # Should include extra fields
    assert log_record.get("user_id") == "user-123"
    assert log_record.get("action") == "login"


def test_formatter_correlation_id_with_trace_context(logger_with_formatter):
    """Test that both correlation ID and trace context coexist."""
    logger, stream = logger_with_formatter

    # Set correlation ID
    set_correlation_id("both-test-id")

    # Mock OpenTelemetry span
    mock_span_context = Mock()
    mock_span_context.trace_id = 0xabcdef
    mock_span_context.span_id = 0x123456
    mock_span_context.trace_flags = 0x01
    mock_span_context.is_valid = True

    mock_span = Mock()
    mock_span.is_recording.return_value = True
    mock_span.get_span_context.return_value = mock_span_context

    with patch("mcpgateway.services.logging_service.trace") as mock_trace:
        mock_trace.get_current_span.return_value = mock_span

        # Log a message
        logger.info("Test with both IDs")

        # Get the logged output
        output = stream.getvalue()
        log_record = json.loads(output.strip())

        # Should include both correlation ID and trace context
        assert log_record.get("request_id") == "both-test-id"
        assert "trace_id" in log_record
        assert "span_id" in log_record

    clear_correlation_id()


def test_formatter_multiple_log_entries(logger_with_formatter):
    """Test that formatter handles multiple log entries correctly."""
    logger, stream = logger_with_formatter

    # Log multiple messages with different correlation IDs
    set_correlation_id("first-id")
    logger.info("First message")

    set_correlation_id("second-id")
    logger.info("Second message")

    clear_correlation_id()
    logger.info("Third message")

    # Get all logged output
    output = stream.getvalue()
    log_lines = output.strip().split("\n")

    assert len(log_lines) == 3

    # Parse each line
    first_record = json.loads(log_lines[0])
    second_record = json.loads(log_lines[1])
    third_record = json.loads(log_lines[2])

    # Verify correlation IDs
    assert first_record.get("request_id") == "first-id"
    assert second_record.get("request_id") == "second-id"
    assert "request_id" not in third_record or third_record.get("request_id") is None


def test_formatter_process_id_and_hostname(logger_with_formatter):
    """Test that formatter includes process ID and hostname."""
    logger, stream = logger_with_formatter

    # Log a message
    logger.info("Process info test")

    # Get the logged output
    output = stream.getvalue()
    log_record = json.loads(output.strip())

    # Check process_id and hostname
    assert "process_id" in log_record
    assert isinstance(log_record["process_id"], int)
    assert log_record["process_id"] > 0

    assert "hostname" in log_record
    assert isinstance(log_record["hostname"], str)
    assert len(log_record["hostname"]) > 0


def test_formatter_handles_invalid_span_context(logger_with_formatter):
    """Test that formatter handles invalid span context gracefully."""
    logger, stream = logger_with_formatter

    # Mock span with invalid context
    mock_span_context = Mock()
    mock_span_context.is_valid = False

    mock_span = Mock()
    mock_span.is_recording.return_value = True
    mock_span.get_span_context.return_value = mock_span_context

    with patch("mcpgateway.services.logging_service.trace") as mock_trace:
        mock_trace.get_current_span.return_value = mock_span

        # Log a message
        logger.info("Test with invalid span")

        # Get the logged output
        output = stream.getvalue()
        log_record = json.loads(output.strip())

        # Should not include trace context when invalid
        assert "trace_id" not in log_record
        assert "span_id" not in log_record
        # But message should still be logged
        assert log_record["message"] == "Test with invalid span"
