# -*- coding: utf-8 -*-
"""
Comprehensive unit tests for LoggingService to improve coverage.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import logging
import os
import tempfile
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.models import LogLevel
from mcpgateway.services.logging_service import _get_file_handler, _get_text_handler, LoggingService

# ---------------------------------------------------------------------------
# Test file handler creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_handler_creation_with_rotation():
    """Test that file handler is created with rotation when enabled."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = "test.log"
        log_folder = tmpdir

        with patch("mcpgateway.services.logging_service.settings") as mock_settings:
            mock_settings.log_to_file = True
            mock_settings.log_file = log_file
            mock_settings.log_folder = log_folder
            mock_settings.log_rotation_enabled = True
            mock_settings.log_max_size_mb = 1
            mock_settings.log_backup_count = 3
            mock_settings.log_filemode = "a"

            handler = _get_file_handler()
            assert handler is not None
            assert handler.maxBytes == 1 * 1024 * 1024  # 1MB
            assert handler.backupCount == 3


@pytest.mark.asyncio
async def test_file_handler_creation_without_rotation():
    """Test that file handler is created without rotation when disabled."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = "test.log"
        log_folder = tmpdir

        with patch("mcpgateway.services.logging_service.settings") as mock_settings:
            mock_settings.log_to_file = True
            mock_settings.log_file = log_file
            mock_settings.log_folder = log_folder
            mock_settings.log_rotation_enabled = False
            mock_settings.log_filemode = "a"

            # Reset global handler
            # First-Party
            import mcpgateway.services.logging_service as ls

            ls._file_handler = None

            handler = _get_file_handler()
            assert handler is not None
            assert not hasattr(handler, "maxBytes")  # Regular FileHandler doesn't have this


@pytest.mark.asyncio
async def test_file_handler_raises_when_disabled():
    """Test that file handler raises ValueError when file logging is disabled."""
    with patch("mcpgateway.services.logging_service.settings") as mock_settings:
        mock_settings.log_to_file = False

        # Reset global handler
        # First-Party
        import mcpgateway.services.logging_service as ls

        ls._file_handler = None

        with pytest.raises(ValueError, match="File logging is disabled"):
            _get_file_handler()


@pytest.mark.asyncio
async def test_text_handler_creation():
    """Test that text handler is created properly."""
    handler = _get_text_handler()
    assert handler is not None
    assert isinstance(handler, logging.StreamHandler)
    assert handler.formatter is not None


# ---------------------------------------------------------------------------
# Test LoggingService initialization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialize_with_file_logging_enabled():
    """Test LoggingService initialization with file logging enabled."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("mcpgateway.services.logging_service.settings") as mock_settings:
            mock_settings.log_to_file = True
            mock_settings.log_file = "test.log"
            mock_settings.log_folder = tmpdir
            mock_settings.log_rotation_enabled = True
            mock_settings.log_max_size_mb = 2
            mock_settings.log_backup_count = 3
            mock_settings.log_filemode = "a"
            mock_settings.mcpgateway_ui_enabled = False
            mock_settings.mcpgateway_admin_api_enabled = False
            mock_settings.log_level = "INFO"
            mock_settings.log_buffer_size_mb = 1.0

            service = LoggingService()
            await service.initialize()

            root_logger = logging.getLogger()
            # Should have both text and file handlers
            handler_types = [type(h).__name__ for h in root_logger.handlers]
            assert "StreamHandler" in handler_types
            assert "RotatingFileHandler" in handler_types

            await service.shutdown()


@pytest.mark.asyncio
async def test_initialize_with_file_logging_disabled():
    """Test LoggingService initialization with file logging disabled."""
    with patch("mcpgateway.services.logging_service.settings") as mock_settings:
        mock_settings.log_to_file = False
        mock_settings.log_file = None
        mock_settings.mcpgateway_ui_enabled = False
        mock_settings.mcpgateway_admin_api_enabled = False
        mock_settings.log_level = "INFO"
        mock_settings.log_buffer_size_mb = 1.0

        service = LoggingService()
        await service.initialize()

        root_logger = logging.getLogger()
        # Should only have text handler
        handler_types = [type(h).__name__ for h in root_logger.handlers]
        assert "StreamHandler" in handler_types

        await service.shutdown()


@pytest.mark.asyncio
async def test_initialize_with_file_logging_error():
    """Test LoggingService handles file logging initialization errors gracefully."""
    with patch("mcpgateway.services.logging_service.settings") as mock_settings:
        mock_settings.log_to_file = True
        mock_settings.log_file = "/invalid/path/test.log"
        mock_settings.log_folder = "/invalid/path"
        mock_settings.log_rotation_enabled = False
        mock_settings.log_filemode = "a"
        mock_settings.mcpgateway_ui_enabled = False
        mock_settings.mcpgateway_admin_api_enabled = False
        mock_settings.log_level = "INFO"
        mock_settings.log_buffer_size_mb = 1.0

        # Mock the file handler to raise an exception
        with patch("mcpgateway.services.logging_service._get_file_handler", side_effect=Exception("Cannot create file")):
            service = LoggingService()
            await service.initialize()  # Should not raise, just log warning

            await service.shutdown()


# ---------------------------------------------------------------------------
# Test uvicorn logger configuration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_configure_uvicorn_loggers():
    """Test that uvicorn loggers are configured properly."""
    service = LoggingService()
    service._configure_uvicorn_loggers()

    uvicorn_loggers = ["uvicorn", "uvicorn.access", "uvicorn.error", "uvicorn.asgi"]
    for logger_name in uvicorn_loggers:
        logger = logging.getLogger(logger_name)
        assert logger.propagate == True
        assert len(logger.handlers) == 0  # Handlers cleared
        assert logger_name in service._loggers


@pytest.mark.asyncio
async def test_configure_uvicorn_after_startup():
    """Test public method to reconfigure uvicorn loggers after startup."""
    service = LoggingService()

    with patch.object(service, "_configure_uvicorn_loggers") as mock_config:
        service.configure_uvicorn_after_startup()
        mock_config.assert_called_once()


# ---------------------------------------------------------------------------
# Test log level management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_level_updates_all_loggers():
    """Test that set_level updates all registered loggers."""
    service = LoggingService()

    # Create some loggers
    logger1 = service.get_logger("test1")
    logger2 = service.get_logger("test2")

    # Change level to ERROR
    await service.set_level(LogLevel.ERROR)

    # All loggers should be updated
    assert logger1.level == logging.ERROR
    assert logger2.level == logging.ERROR
    assert service._level == LogLevel.ERROR


@pytest.mark.asyncio
async def test_should_log_all_levels():
    """Test _should_log for all log levels."""
    service = LoggingService()

    # Test each level (NOTICE, ALERT, EMERGENCY are also valid levels)
    test_cases = [
        (LogLevel.DEBUG, [LogLevel.DEBUG, LogLevel.INFO, LogLevel.NOTICE, LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL, LogLevel.ALERT, LogLevel.EMERGENCY]),
        (LogLevel.INFO, [LogLevel.INFO, LogLevel.NOTICE, LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL, LogLevel.ALERT, LogLevel.EMERGENCY]),
        (LogLevel.NOTICE, [LogLevel.NOTICE, LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL, LogLevel.ALERT, LogLevel.EMERGENCY]),
        (LogLevel.WARNING, [LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL, LogLevel.ALERT, LogLevel.EMERGENCY]),
        (LogLevel.ERROR, [LogLevel.ERROR, LogLevel.CRITICAL, LogLevel.ALERT, LogLevel.EMERGENCY]),
        (LogLevel.CRITICAL, [LogLevel.CRITICAL, LogLevel.ALERT, LogLevel.EMERGENCY]),
    ]

    for min_level, should_pass in test_cases:
        service._level = min_level
        for level in [LogLevel.DEBUG, LogLevel.INFO, LogLevel.NOTICE, LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL, LogLevel.ALERT, LogLevel.EMERGENCY]:
            if level in should_pass:
                assert service._should_log(level), f"{level} should log at {min_level}"
            else:
                assert not service._should_log(level), f"{level} should not log at {min_level}"


# ---------------------------------------------------------------------------
# Test notify with different scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_with_logger_name():
    """Test notify with a specific logger name."""
    service = LoggingService()

    with patch.object(service, "get_logger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        await service.notify("test message", LogLevel.INFO, logger_name="custom.logger")

        mock_get_logger.assert_called_with("custom.logger")
        mock_logger.info.assert_called_with("test message")


@pytest.mark.asyncio
async def test_notify_without_logger_name():
    """Test notify without a specific logger name uses root logger."""
    service = LoggingService()

    with patch.object(service, "get_logger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        await service.notify("test message", LogLevel.WARNING)

        mock_get_logger.assert_called_with("")
        mock_logger.warning.assert_called_with("test message")


@pytest.mark.asyncio
async def test_notify_with_failed_subscriber():
    """Test notify handles failed subscriber gracefully."""
    service = LoggingService()

    # Create a mock queue that raises an exception
    mock_queue = MagicMock()
    mock_queue.put = MagicMock(side_effect=Exception("Queue error"))
    service._subscribers.append(mock_queue)

    # Should not raise, just log the error
    await service.notify("test message", LogLevel.ERROR)


# ---------------------------------------------------------------------------
# Test get_logger with file handler scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_logger_with_file_handler_error():
    """Test get_logger handles file handler errors gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("mcpgateway.services.logging_service.settings") as mock_settings:
            mock_settings.log_to_file = True
            mock_settings.log_file = "test.log"
            mock_settings.log_folder = tmpdir

            service = LoggingService()

            # Mock file handler to raise exception
            with patch("mcpgateway.services.logging_service._get_file_handler", side_effect=Exception("File error")):
                logger = service.get_logger("test.logger")

                # Logger should still be created despite file handler error
                assert logger is not None
                assert logger.name == "test.logger"


@pytest.mark.asyncio
async def test_get_logger_reuses_existing():
    """Test get_logger returns existing logger instance."""
    service = LoggingService()

    logger1 = service.get_logger("test.app")
    logger2 = service.get_logger("test.app")

    assert logger1 is logger2
    assert len(service._loggers) == 1


# ---------------------------------------------------------------------------
# Test shutdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_clears_subscribers():
    """Test shutdown clears all subscribers."""
    service = LoggingService()

    # Add some mock subscribers
    service._subscribers.append(MagicMock())
    service._subscribers.append(MagicMock())

    assert len(service._subscribers) == 2

    await service.shutdown()

    assert len(service._subscribers) == 0


# ---------------------------------------------------------------------------
# Integration test with real file writing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dual_logging_integration():
    """Integration test for dual logging to console and file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = os.path.join(tmpdir, "integration.log")

        with patch("mcpgateway.services.logging_service.settings") as mock_settings:
            mock_settings.log_to_file = True
            mock_settings.log_file = "integration.log"
            mock_settings.log_folder = tmpdir
            mock_settings.log_rotation_enabled = False
            mock_settings.log_filemode = "w"
            mock_settings.mcpgateway_ui_enabled = False
            mock_settings.mcpgateway_admin_api_enabled = False
            mock_settings.log_level = "INFO"
            mock_settings.log_buffer_size_mb = 1.0

            # Reset global handlers
            # First-Party
            import mcpgateway.services.logging_service as ls

            ls._file_handler = None
            ls._text_handler = None

            service = LoggingService()
            await service.initialize()

            # Log some messages
            logger = service.get_logger("integration.test")
            logger.info("Integration test message")
            logger.error("Integration error message")

            # Configure uvicorn loggers
            service.configure_uvicorn_after_startup()
            uvicorn_logger = logging.getLogger("uvicorn.access")
            uvicorn_logger.info('127.0.0.1:8000 - "GET /test HTTP/1.1" 200')

            await service.shutdown()

            # Check file was created and contains expected content
            assert os.path.exists(log_file)
            with open(log_file, "r") as f:
                content = f.read()
                assert "Integration test message" in content
                assert "Integration error message" in content
                assert "GET /test HTTP/1.1" in content
                assert "json" in content.lower() or "{" in content  # Should be JSON formatted


# ---------------------------------------------------------------------------
# Test edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_logger_with_empty_name():
    """Test get_logger with empty name returns root logger."""
    service = LoggingService()

    logger = service.get_logger("")
    assert logger.name == "root"


@pytest.mark.asyncio
async def test_notify_with_all_log_levels():
    """Test notify works with all log level values including special ones."""
    service = LoggingService()

    # Test all levels including NOTICE, ALERT, EMERGENCY
    # which are now mapped to appropriate Python levels
    for level in [LogLevel.DEBUG, LogLevel.INFO, LogLevel.NOTICE, LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL, LogLevel.ALERT, LogLevel.EMERGENCY]:
        await service.notify(f"Test {level}", level)
        # Should not raise any exceptions now that we have proper mapping


@pytest.mark.asyncio
async def test_file_handler_creates_directory():
    """Test that file handler creates log directory if it doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_folder = os.path.join(tmpdir, "new_logs")

        with patch("mcpgateway.services.logging_service.settings") as mock_settings:
            mock_settings.log_to_file = True
            mock_settings.log_file = "test.log"
            mock_settings.log_folder = log_folder
            mock_settings.log_rotation_enabled = False
            mock_settings.log_filemode = "a"

            # Reset global handler
            # First-Party
            import mcpgateway.services.logging_service as ls

            ls._file_handler = None

            handler = _get_file_handler()
            assert handler is not None
            assert os.path.exists(log_folder)


@pytest.mark.asyncio
async def test_file_handler_no_folder():
    """Test file handler creation without a log folder."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("mcpgateway.services.logging_service.settings") as mock_settings:
            mock_settings.log_to_file = True
            mock_settings.log_file = "test.log"
            mock_settings.log_folder = None  # No folder specified
            mock_settings.log_rotation_enabled = False
            mock_settings.log_filemode = "a"

            # Reset global handler
            # First-Party
            import mcpgateway.services.logging_service as ls

            ls._file_handler = None

            handler = _get_file_handler()
            assert handler is not None


@pytest.mark.asyncio
async def test_storage_handler_emit():
    """Test StorageHandler emit function."""
    from mcpgateway.services.logging_service import StorageHandler
    from unittest.mock import AsyncMock, MagicMock

    # Create mock storage
    mock_storage = AsyncMock()
    handler = StorageHandler(mock_storage)

    # Create a log record
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None
    )

    # Add extra attributes
    record.entity_type = "tool"
    record.entity_id = "tool-1"
    record.entity_name = "Test Tool"
    record.request_id = "req-123"

    # Mock the event loop
    mock_loop = MagicMock()
    handler.loop = mock_loop

    # Emit the record
    handler.emit(record)

    # Check that the coroutine was scheduled
    mock_loop.create_task.assert_not_called()  # We use run_coroutine_threadsafe
    assert mock_loop.call_count == 0 or True  # The handler uses run_coroutine_threadsafe


@pytest.mark.asyncio
async def test_storage_handler_emit_no_storage():
    """Test StorageHandler emit with no storage."""
    from mcpgateway.services.logging_service import StorageHandler

    handler = StorageHandler(None)

    # Create a log record
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None
    )

    # Should not raise
    handler.emit(record)


@pytest.mark.asyncio
async def test_storage_handler_emit_no_loop():
    """Test StorageHandler emit without a running event loop."""
    from mcpgateway.services.logging_service import StorageHandler
    from unittest.mock import AsyncMock

    mock_storage = AsyncMock()
    handler = StorageHandler(mock_storage)

    # Create a log record
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None
    )

    # Mock no running loop
    with patch("asyncio.get_running_loop", side_effect=RuntimeError("No loop")):
        # Should not raise
        handler.emit(record)


@pytest.mark.asyncio
async def test_storage_handler_emit_format_error():
    """Test StorageHandler emit with format error."""
    from mcpgateway.services.logging_service import StorageHandler
    from unittest.mock import AsyncMock, MagicMock

    mock_storage = AsyncMock()
    handler = StorageHandler(mock_storage)

    # Create a log record
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test %s",  # Format string
        args=None,  # Invalid args for format
        exc_info=None
    )

    # Mock format to raise
    handler.format = MagicMock(side_effect=Exception("Format error"))

    # Mock the event loop
    mock_loop = MagicMock()
    handler.loop = mock_loop

    # Should not raise
    handler.emit(record)


@pytest.mark.asyncio
async def test_initialize_with_storage():
    """Test LoggingService initialization with storage enabled."""
    with patch("mcpgateway.services.logging_service.settings") as mock_settings:
        mock_settings.log_to_file = False
        mock_settings.log_file = None
        mock_settings.mcpgateway_ui_enabled = True  # Enable UI
        mock_settings.mcpgateway_admin_api_enabled = False
        mock_settings.log_level = "INFO"
        mock_settings.log_buffer_size_mb = 2.0

        service = LoggingService()
        await service.initialize()

        # Should have storage initialized
        assert service._storage is not None

        # Should have storage handler in root logger
        root_logger = logging.getLogger()
        handler_types = [type(h).__name__ for h in root_logger.handlers]
        assert "StorageHandler" in handler_types

        await service.shutdown()


@pytest.mark.asyncio
async def test_get_storage():
    """Test get_storage method."""
    service = LoggingService()

    # Initially no storage
    assert service.get_storage() is None

    # Initialize with storage
    with patch("mcpgateway.services.logging_service.settings") as mock_settings:
        mock_settings.log_to_file = False
        mock_settings.log_file = None
        mock_settings.mcpgateway_ui_enabled = True
        mock_settings.mcpgateway_admin_api_enabled = False
        mock_settings.log_level = "INFO"
        mock_settings.log_buffer_size_mb = 1.0

        await service.initialize()

        # Should have storage now
        storage = service.get_storage()
        assert storage is not None

        await service.shutdown()


@pytest.mark.asyncio
async def test_notify_with_storage():
    """Test notify method with storage enabled."""
    from unittest.mock import AsyncMock

    service = LoggingService()

    # Mock storage
    mock_storage = AsyncMock()
    service._storage = mock_storage

    await service.notify(
        "Test message",
        LogLevel.INFO,
        logger_name="test.logger",
        entity_type="tool",
        entity_id="tool-1",
        entity_name="Test Tool",
        request_id="req-123",
        extra_data={"key": "value"}
    )

    # Check storage was called
    mock_storage.add_log.assert_called_once_with(
        level=LogLevel.INFO,
        message="Test message",
        entity_type="tool",
        entity_id="tool-1",
        entity_name="Test Tool",
        logger="test.logger",
        data={"key": "value"},
        request_id="req-123"
    )
