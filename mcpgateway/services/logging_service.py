# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/logging_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Logging Service Implementation.
This module implements structured logging according to the MCP specification.
It supports RFC 5424 severity levels, log level management, and log event subscriptions.
"""

# Standard
import asyncio
from asyncio.events import AbstractEventLoop
from datetime import datetime, timezone
import logging
from logging.handlers import RotatingFileHandler
import os
import socket
from typing import Any, AsyncGenerator, Dict, List, NotRequired, Optional, TextIO, TypedDict

# Third-Party
from pythonjsonlogger import json as jsonlogger  # You may need to install python-json-logger package

# First-Party
from mcpgateway.common.models import LogLevel
from mcpgateway.config import settings
from mcpgateway.services.log_storage_service import LogStorageService
from mcpgateway.utils.correlation_id import get_correlation_id

# Optional OpenTelemetry support (Third-Party)
try:
    # Third-Party
    from opentelemetry import trace  # type: ignore[import-untyped]
except ImportError:
    trace = None  # type: ignore[assignment]

AnyioClosedResourceError: Optional[type]  # pylint: disable=invalid-name
try:
    # Optional import; only used for filtering a known benign upstream error (Third-Party)
    # Third-Party
    from anyio import ClosedResourceError as AnyioClosedResourceError  # pylint: disable=invalid-name
except Exception:  # pragma: no cover - environment without anyio
    AnyioClosedResourceError = None  # pylint: disable=invalid-name

# First-Party
# Create a text formatter
text_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")


class CorrelationIdJsonFormatter(jsonlogger.JsonFormatter):
    """JSON formatter that includes correlation ID and OpenTelemetry trace context."""

    def add_fields(self, log_record: dict, record: logging.LogRecord, message_dict: dict) -> None:  # pylint: disable=arguments-renamed
        """Add custom fields to the log record.

        Args:
            log_record: The dictionary that will be logged as JSON
            record: The original LogRecord
            message_dict: Additional message fields

        """
        super().add_fields(log_record, record, message_dict)

        # Add timestamp in ISO 8601 format with 'Z' suffix for UTC
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        log_record["@timestamp"] = dt.isoformat().replace("+00:00", "Z")

        # Add hostname and process ID for log aggregation
        log_record["hostname"] = socket.gethostname()
        log_record["process_id"] = os.getpid()

        # Add correlation ID from context
        correlation_id = get_correlation_id()
        if correlation_id:
            log_record["request_id"] = correlation_id

        # Add OpenTelemetry trace context if available
        if trace is not None:
            try:
                span = trace.get_current_span()
                if span and span.is_recording():
                    span_context = span.get_span_context()
                    if span_context.is_valid:
                        # Format trace_id and span_id as hex strings
                        log_record["trace_id"] = format(span_context.trace_id, "032x")
                        log_record["span_id"] = format(span_context.span_id, "016x")
                        log_record["trace_flags"] = format(span_context.trace_flags, "02x")
            except Exception:  # nosec B110 - intentionally catching all exceptions for optional tracing
                # Error accessing span context, continue without trace fields
                pass


# Create a JSON formatter with correlation ID support
json_formatter = CorrelationIdJsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")

# Note: Don't use basicConfig here as it conflicts with our custom dual logging setup
# The LoggingService.initialize() method will properly configure all handlers

# Global handlers will be created lazily
_file_handler: Optional[logging.Handler] = None
_text_handler: Optional[logging.StreamHandler[TextIO]] = None


def _get_file_handler() -> logging.Handler:
    """Get or create the file handler.

    Returns:
        logging.Handler: Either a RotatingFileHandler or regular FileHandler for JSON logging.

    Raises:
        ValueError: If file logging is disabled or no log file specified.

    """
    global _file_handler  # pylint: disable=global-statement
    if _file_handler is None:
        # Only create if file logging is enabled and file is specified
        if not settings.log_to_file or not settings.log_file:
            raise ValueError("File logging is disabled or no log file specified")

        # Ensure log folder exists
        if settings.log_folder:
            os.makedirs(settings.log_folder, exist_ok=True)
            log_path = os.path.join(settings.log_folder, settings.log_file)
        else:
            log_path = settings.log_file

        # Create appropriate handler based on rotation settings
        if settings.log_rotation_enabled:
            max_bytes = settings.log_max_size_mb * 1024 * 1024  # Convert MB to bytes
            _file_handler = RotatingFileHandler(log_path, maxBytes=max_bytes, backupCount=settings.log_backup_count, mode=settings.log_filemode)
        else:
            _file_handler = logging.FileHandler(log_path, mode=settings.log_filemode)

        _file_handler.setFormatter(json_formatter)
    return _file_handler


def _get_text_handler() -> logging.StreamHandler[TextIO]:
    """Get or create the text handler.

    Returns:
        logging.StreamHandler: The stream handler for console logging.

    """
    global _text_handler  # pylint: disable=global-statement
    if _text_handler is None:
        _text_handler = logging.StreamHandler()
        _text_handler.setFormatter(text_formatter)
    return _text_handler


class StorageHandler(logging.Handler):
    """Custom logging handler that stores logs in LogStorageService."""

    def __init__(self, storage_service: LogStorageService):
        """Initialize the storage handler.

        Args:
            storage_service: The LogStorageService instance to store logs in

        """
        super().__init__()
        self.storage = storage_service
        self.loop: AbstractEventLoop | None = None

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record to storage.

        Args:
            record: The LogRecord to emit

        """
        if not self.storage:
            return

        # Map Python log levels to MCP LogLevel
        level_map = {
            "DEBUG": LogLevel.DEBUG,
            "INFO": LogLevel.INFO,
            "WARNING": LogLevel.WARNING,
            "ERROR": LogLevel.ERROR,
            "CRITICAL": LogLevel.CRITICAL,
        }

        log_level = level_map.get(record.levelname, LogLevel.INFO)

        # Extract entity context from record if available
        entity_type = getattr(record, "entity_type", None)
        entity_id = getattr(record, "entity_id", None)
        entity_name = getattr(record, "entity_name", None)
        request_id = getattr(record, "request_id", None)

        # Format the message
        try:
            message = self.format(record)
        except Exception:
            message = record.getMessage()

        # Store the log asynchronously
        try:
            # Get or create event loop
            if not self.loop:
                try:
                    self.loop = asyncio.get_running_loop()
                except RuntimeError:
                    # No running loop, can't store
                    return

            # Schedule the coroutine and store the future (fire-and-forget)
            future = asyncio.run_coroutine_threadsafe(
                self.storage.add_log(
                    level=log_level,
                    message=message,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    entity_name=entity_name,
                    logger=record.name,
                    request_id=request_id,
                ),
                self.loop,
            )
            # Add a done callback to catch any exceptions without blocking
            future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        except Exception:
            # Silently fail to avoid logging recursion
            pass  # nosec B110 - Intentional to prevent logging recursion


class _LogMessageData(TypedDict):
    """Log message data structure."""

    level: LogLevel
    data: Any
    timestamp: str
    logger: NotRequired[str]


class _LogMessage(TypedDict):
    """Log message event structure."""

    type: str
    data: _LogMessageData


class LoggingService:
    """MCP logging service.

    Implements structured logging with:
    - RFC 5424 severity levels
    - Log level management
    - Log event subscriptions
    - Logger name tracking
    """

    def __init__(self) -> None:
        """Initialize logging service."""
        self._level = LogLevel.INFO
        self._subscribers: List[asyncio.Queue[_LogMessage]] = []
        self._loggers: Dict[str, logging.Logger] = {}
        self._storage: LogStorageService | None = None  # Will be initialized if admin UI is enabled
        self._storage_handler: Optional[StorageHandler] = None  # Track the storage handler for cleanup

    async def initialize(self) -> None:
        """Initialize logging service.

        Examples:
            >>> from mcpgateway.services.logging_service import LoggingService
            >>> import asyncio
            >>> service = LoggingService()
            >>> asyncio.run(service.initialize())

        """
        # Update service log level from settings BEFORE configuring loggers
        self._level = LogLevel[settings.log_level.upper()]

        root_logger = logging.getLogger()
        self._loggers[""] = root_logger

        # Clear existing handlers to avoid duplicates
        root_logger.handlers.clear()

        # Always add console/text handler for stdout/stderr
        root_logger.addHandler(_get_text_handler())

        # Only add file handler if enabled
        if settings.log_to_file and settings.log_file:
            try:
                root_logger.addHandler(_get_file_handler())
                if settings.log_rotation_enabled:
                    logging.info(f"File logging enabled with rotation: {settings.log_folder or '.'}/{settings.log_file} (max: {settings.log_max_size_mb}MB, backups: {settings.log_backup_count})")
                else:
                    logging.info(f"File logging enabled (no rotation): {settings.log_folder or '.'}/{settings.log_file}")
            except Exception as e:
                logging.warning(f"Failed to initialize file logging: {e}")
        else:
            logging.info("File logging disabled - logging to stdout/stderr only")

        # Configure uvicorn loggers to use our handlers (for access logs)
        # Note: This needs to be done both at init and dynamically as uvicorn creates loggers later
        self._configure_uvicorn_loggers()

        # Initialize log storage if admin UI is enabled
        if settings.mcpgateway_ui_enabled or settings.mcpgateway_admin_api_enabled:
            self._storage = LogStorageService()

            # Add storage handler to capture all logs
            self._storage_handler = StorageHandler(self._storage)
            self._storage_handler.setFormatter(text_formatter)
            self._storage_handler.setLevel(getattr(logging, settings.log_level.upper()))
            root_logger.addHandler(self._storage_handler)

            logging.info(f"Log storage initialized with {settings.log_buffer_size_mb}MB buffer")

        logging.info("Logging service initialized")

        # Suppress noisy upstream logs for normal stream closures in MCP streamable HTTP
        self._install_closedresourceerror_filter()

    async def shutdown(self) -> None:
        """Shutdown logging service.

        Examples:
            >>> from mcpgateway.services.logging_service import LoggingService
            >>> import asyncio
            >>> service = LoggingService()
            >>> asyncio.run(service.shutdown())

        """
        # Remove storage handler from root logger if it was added
        if self._storage_handler:
            root_logger = logging.getLogger()
            root_logger.removeHandler(self._storage_handler)
            self._storage_handler = None

        # Clear subscribers
        self._subscribers.clear()
        logging.info("Logging service shutdown")

    def _install_closedresourceerror_filter(self) -> None:
        """Install a filter to drop benign ClosedResourceError logs from upstream MCP.

        The MCP streamable HTTP server logs an ERROR when the in-memory channel is
        closed during normal client disconnects, raising ``anyio.ClosedResourceError``.
        This filter suppresses those specific records to keep logs clean.

        Examples:
            >>> # Initialize service (installs filter)
            >>> import asyncio, logging, anyio
            >>> service = LoggingService()
            >>> asyncio.run(service.initialize())
            >>> # Locate the installed filter on the target logger
            >>> target = logging.getLogger('mcp.server.streamable_http')
            >>> flts = [f for f in target.filters if f.__class__.__name__.endswith('SuppressClosedResourceErrorFilter')]
            >>> len(flts) >= 1
            True
            >>> filt = flts[0]
            >>> # Non-target logger should pass through even if message matches
            >>> rec_other = logging.makeLogRecord({'name': 'other.logger', 'msg': 'ClosedResourceError'})
            >>> filt.filter(rec_other)
            True
            >>> # Target logger with message containing ClosedResourceError should be suppressed
            >>> rec_target_msg = logging.makeLogRecord({'name': 'mcp.server.streamable_http', 'msg': 'ClosedResourceError in normal shutdown'})
            >>> filt.filter(rec_target_msg)
            False
            >>> # Target logger with ClosedResourceError in exc_info should be suppressed
            >>> try:
            ...     raise anyio.ClosedResourceError
            ... except anyio.ClosedResourceError as e:
            ...     rec_target_exc = logging.makeLogRecord({
            ...         'name': 'mcp.server.streamable_http',
            ...         'msg': 'Error in message router',
            ...         'exc_info': (e.__class__, e, None),
            ...     })
            >>> filt.filter(rec_target_exc)
            False
            >>> # Cleanup
            >>> asyncio.run(service.shutdown())

        """

        class _SuppressClosedResourceErrorFilter(logging.Filter):
            """Filter to suppress ClosedResourceError exceptions from MCP streamable HTTP logger.

            This filter prevents noisy ClosedResourceError exceptions from the upstream
            MCP streamable HTTP implementation from cluttering the logs. These errors
            are typically harmless connection cleanup events.
            """

            def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
                """Filter log records to suppress ClosedResourceError exceptions.

                Args:
                    record: The log record to evaluate

                Returns:
                    True to allow the record through, False to suppress it

                """
                # Apply only to upstream MCP streamable HTTP logger
                if not record.name.startswith("mcp.server.streamable_http"):
                    return True

                # If exception info is present, check its type
                exc_info = getattr(record, "exc_info", None)
                if exc_info and AnyioClosedResourceError is not None:
                    exc_type, exc, _tb = exc_info
                    try:
                        if isinstance(exc, AnyioClosedResourceError) or (getattr(exc_type, "__name__", "") == "ClosedResourceError"):
                            return False
                    except Exception:
                        # Be permissive if anything goes wrong, don't drop logs accidentally
                        return True

                # Fallback: drop if message text clearly indicates ClosedResourceError
                try:
                    msg = record.getMessage()
                    if "ClosedResourceError" in msg:
                        return False
                except Exception:
                    pass  # nosec B110 - Intentional to prevent logging recursion
                return True

        target_logger = logging.getLogger("mcp.server.streamable_http")
        target_logger.addFilter(_SuppressClosedResourceErrorFilter())

    def get_logger(self, name: str) -> logging.Logger:
        """Get or create logger instance.

        Args:
            name: Logger name

        Returns:
            Logger instance

        Examples:
            >>> from mcpgateway.services.logging_service import LoggingService
            >>> service = LoggingService()
            >>> logger = service.get_logger('test')
            >>> import logging
            >>> isinstance(logger, logging.Logger)
            True

        """
        if name not in self._loggers:
            logger = logging.getLogger(name)

            # Don't add handlers to child loggers - let them inherit from root
            # This prevents duplicate logging while maintaining dual output (console + file)
            logger.propagate = True

            # Set level to match service level
            log_level = getattr(logging, self._level.upper())
            logger.setLevel(log_level)

            self._loggers[name] = logger

        return self._loggers[name]

    async def set_level(self, level: LogLevel) -> None:
        """Set minimum log level.

        This updates the level for all registered loggers.

        Args:
            level: New log level

        Examples:
            >>> from mcpgateway.services.logging_service import LoggingService
            >>> from mcpgateway.common.models import LogLevel
            >>> import asyncio
            >>> service = LoggingService()
            >>> asyncio.run(service.set_level(LogLevel.DEBUG))

        """
        self._level = level

        # Update all loggers
        log_level = getattr(logging, level.upper())
        for logger in self._loggers.values():
            logger.setLevel(log_level)

        await self.notify(f"Log level set to {level}", LogLevel.INFO, "logging")

    async def notify(  # pylint: disable=too-many-positional-arguments
        self,
        data: Any,
        level: LogLevel,
        logger_name: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_name: Optional[str] = None,
        request_id: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send log notification to subscribers.

        Args:
            data: Log message data
            level: Log severity level
            logger_name: Optional logger name
            entity_type: Type of entity (tool, resource, server, gateway)
            entity_id: ID of the related entity
            entity_name: Name of the related entity
            request_id: Associated request ID for tracing
            extra_data: Additional structured data

        Examples:
            >>> from mcpgateway.services.logging_service import LoggingService
            >>> from mcpgateway.common.models import LogLevel
            >>> import asyncio
            >>> service = LoggingService()
            >>> asyncio.run(service.notify('test', LogLevel.INFO))

        """
        # Skip if below current level
        if not self._should_log(level):
            return

        # Format notification message
        message: _LogMessage = {
            "type": "log",
            "data": {
                "level": level,
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
        if logger_name:
            message["data"]["logger"] = logger_name

        # Log through standard logging
        logger = self.get_logger(logger_name or "")

        # Map MCP log levels to Python logging levels
        # NOTICE, ALERT, and EMERGENCY don't have direct Python equivalents
        level_map = {
            LogLevel.DEBUG: "debug",
            LogLevel.INFO: "info",
            LogLevel.NOTICE: "info",  # Map NOTICE to INFO
            LogLevel.WARNING: "warning",
            LogLevel.ERROR: "error",
            LogLevel.CRITICAL: "critical",
            LogLevel.ALERT: "critical",  # Map ALERT to CRITICAL
            LogLevel.EMERGENCY: "critical",  # Map EMERGENCY to CRITICAL
        }

        log_method = level_map.get(level, "info")
        log_func = getattr(logger, log_method)
        log_func(data)

        # Store in log storage if available
        if self._storage:
            await self._storage.add_log(
                level=level,
                message=str(data),
                entity_type=entity_type,
                entity_id=entity_id,
                entity_name=entity_name,
                logger=logger_name,
                data=extra_data,
                request_id=request_id,
            )

        # Notify subscribers
        for queue in self._subscribers:
            try:
                await queue.put(message)
            except Exception as e:
                logger.error(f"Failed to notify subscriber: {e}")

    async def subscribe(self) -> AsyncGenerator[_LogMessage, None]:
        """Subscribe to log messages.

        Returns a generator yielding log message events.

        Yields:
            Log message events

        Examples:
            This example was removed to prevent the test runner from hanging on async generator consumption.

        """
        queue: asyncio.Queue[_LogMessage] = asyncio.Queue()
        self._subscribers.append(queue)
        try:
            while True:
                message = await queue.get()
                yield message
        finally:
            self._subscribers.remove(queue)

    def _should_log(self, level: LogLevel) -> bool:
        """Check if level meets minimum threshold.

        Args:
            level: Log level to check

        Returns:
            True if should log

        Examples:
            >>> from mcpgateway.common.models import LogLevel
            >>> service = LoggingService()
            >>> service._level = LogLevel.WARNING
            >>> service._should_log(LogLevel.ERROR)
            True
            >>> service._should_log(LogLevel.INFO)
            False
            >>> service._should_log(LogLevel.WARNING)
            True
            >>> service._should_log(LogLevel.DEBUG)
            False

        """
        level_values = {
            LogLevel.DEBUG: 0,
            LogLevel.INFO: 1,
            LogLevel.NOTICE: 2,
            LogLevel.WARNING: 3,
            LogLevel.ERROR: 4,
            LogLevel.CRITICAL: 5,
            LogLevel.ALERT: 6,
            LogLevel.EMERGENCY: 7,
        }

        return level_values[level] >= level_values[self._level]

    def _configure_uvicorn_loggers(self) -> None:
        """Configure uvicorn loggers to use our dual logging setup.

        This method handles uvicorn's logging setup which can happen after our initialization.
        Uvicorn creates its own loggers and handlers, so we need to redirect them to our setup.
        """
        uvicorn_loggers = ["uvicorn", "uvicorn.access", "uvicorn.error", "uvicorn.asgi"]

        for logger_name in uvicorn_loggers:
            uvicorn_logger = logging.getLogger(logger_name)

            # Clear any handlers that uvicorn may have added
            uvicorn_logger.handlers.clear()

            # Make sure they propagate to root (which has our dual handlers)
            uvicorn_logger.propagate = True

            # Set level to match our logging service level
            if hasattr(self, "_level"):
                log_level = getattr(logging, self._level.upper())
                uvicorn_logger.setLevel(log_level)

            # Track the logger
            self._loggers[logger_name] = uvicorn_logger

    def configure_uvicorn_after_startup(self) -> None:
        """Public method to reconfigure uvicorn loggers after server startup.

        Call this after uvicorn has started to ensure access logs go to dual output.
        This handles the case where uvicorn creates loggers after our initialization.
        """
        self._configure_uvicorn_loggers()
        logging.info("Uvicorn loggers reconfigured for dual logging")

    def get_storage(self) -> Optional[LogStorageService]:
        """Get the log storage service if available.

        Returns:
            LogStorageService instance or None if not initialized

        """
        return self._storage
