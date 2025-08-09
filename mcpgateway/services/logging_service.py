# -*- coding: utf-8 -*-
"""Logging Service Implementation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module implements structured logging according to the MCP specification.
It supports RFC 5424 severity levels, log level management, and log event subscriptions.
"""

# Standard
import asyncio
from datetime import datetime, timezone
import logging
from logging.handlers import RotatingFileHandler
import os
from typing import Any, AsyncGenerator, Dict, List, Optional

# Third-Party
from pythonjsonlogger import jsonlogger  # You may need to install python-json-logger package

# First-Party
from mcpgateway.config import settings
from mcpgateway.models import LogLevel

# Create a text formatter
text_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Create a JSON formatter
json_formatter = jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Global handlers will be created lazily
_file_handler: Optional[RotatingFileHandler] = None
_text_handler: Optional[logging.StreamHandler] = None


def _get_file_handler() -> RotatingFileHandler:
    """Get or create the file handler.

    Returns:
        RotatingFileHandler: The file handler for JSON logging.

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

        _file_handler = RotatingFileHandler(log_path, maxBytes=1024 * 1024, backupCount=5)
        _file_handler.setFormatter(json_formatter)
    return _file_handler


def _get_text_handler() -> logging.StreamHandler:
    """Get or create the text handler.

    Returns:
        logging.StreamHandler: The stream handler for console logging.
    """
    global _text_handler  # pylint: disable=global-statement
    if _text_handler is None:
        _text_handler = logging.StreamHandler()
        _text_handler.setFormatter(text_formatter)
    return _text_handler


class LoggingService:
    """MCP logging service.

    Implements structured logging with:
    - RFC 5424 severity levels
    - Log level management
    - Log event subscriptions
    - Logger name tracking
    """

    def __init__(self):
        """Initialize logging service."""
        self._level = LogLevel.INFO
        self._subscribers: List[asyncio.Queue] = []
        self._loggers: Dict[str, logging.Logger] = {}

    async def initialize(self) -> None:
        """Initialize logging service.

        Examples:
            >>> from mcpgateway.services.logging_service import LoggingService
            >>> import asyncio
            >>> service = LoggingService()
            >>> asyncio.run(service.initialize())
        """
        self._loggers[""] = logging.getLogger()

        # Always add console/text handler for stdout/stderr
        self._loggers[""].addHandler(_get_text_handler())

        # Only add file handler if enabled
        if settings.log_to_file and settings.log_file:
            try:
                self._loggers[""].addHandler(_get_file_handler())
                logging.info(f"File logging enabled: {settings.log_folder or '.'}/{settings.log_file}")
            except Exception as e:
                logging.warning(f"Failed to initialize file logging: {e}")
        else:
            logging.info("File logging disabled - logging to stdout/stderr only")

        logging.info("Logging service initialized")

    async def shutdown(self) -> None:
        """Shutdown logging service.

        Examples:
            >>> from mcpgateway.services.logging_service import LoggingService
            >>> import asyncio
            >>> service = LoggingService()
            >>> asyncio.run(service.shutdown())
        """
        # Clear subscribers
        self._subscribers.clear()
        logging.info("Logging service shutdown")

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

            # Always add console/text handler for stdout/stderr
            logger.addHandler(_get_text_handler())

            # Only add file handler if enabled
            if settings.log_to_file and settings.log_file:
                try:
                    logger.addHandler(_get_file_handler())
                except Exception as e:
                    # Log the error but don't fail logger creation
                    # Use module-level logging to avoid circular reference
                    logging.getLogger(__name__).warning(f"Failed to add file handler to logger {name}: {e}")

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
            >>> from mcpgateway.models import LogLevel
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

    async def notify(self, data: Any, level: LogLevel, logger_name: Optional[str] = None) -> None:
        """Send log notification to subscribers.

        Args:
            data: Log message data
            level: Log severity level
            logger_name: Optional logger name

        Examples:
            >>> from mcpgateway.services.logging_service import LoggingService
            >>> from mcpgateway.models import LogLevel
            >>> import asyncio
            >>> service = LoggingService()
            >>> asyncio.run(service.notify('test', LogLevel.INFO))
        """
        # Skip if below current level
        if not self._should_log(level):
            return

        # Format notification message
        message = {
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
        log_func = getattr(logger, level.lower())
        log_func(data)

        # Notify subscribers
        for queue in self._subscribers:
            try:
                await queue.put(message)
            except Exception as e:
                logger.error(f"Failed to notify subscriber: {e}")

    async def subscribe(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Subscribe to log messages.

        Returns a generator yielding log message events.

        Yields:
            Log message events

        Examples:
            This example was removed to prevent the test runner from hanging on async generator consumption.
        """
        queue: asyncio.Queue = asyncio.Queue()
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
