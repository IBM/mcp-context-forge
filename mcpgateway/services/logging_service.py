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
from typing import Any, AsyncGenerator, Dict, List, Optional

# First-Party
from mcpgateway.types import LogLevel


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
        """Initialize logging service."""
        # Configure root logger
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        self._loggers[""] = logging.getLogger()
        logging.info("Logging service initialized")

    async def shutdown(self) -> None:
        """Shutdown logging service."""
        # Clear subscribers
        self._subscribers.clear()
        logging.info("Logging service shutdown")

    def get_logger(self, name: str) -> logging.Logger:
        """Get or create logger instance.

        Args:
            name: Logger name

        Returns:
            Logger instance
        """
        if name not in self._loggers:
            logger = logging.getLogger(name)

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
