# -*- coding: utf-8 -*-
"""Location: ./mcp_reverse_proxy/logging_config.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Standalone logging configuration for reverse proxy.
This module provides a simplified logging setup that doesn't depend on the parent mcpgateway package.
"""

# Standard
import logging
import os
import socket
from typing import Any, Dict

# Third-Party
from pythonjsonlogger import jsonlogger

# Standard log format
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

# Cache static values
_CACHED_HOSTNAME: str = socket.gethostname()
_CACHED_PID: int = os.getpid()


class CorrelationIdJsonFormatter(jsonlogger.JsonFormatter):
    """JSON formatter with hostname and PID."""

    def add_fields(self, log_record: dict, record: logging.LogRecord, message_dict: dict) -> None:
        """Add custom fields to the log record.

        Args:
            log_record: The log record dictionary to modify.
            record: The original LogRecord object.
            message_dict: Additional message fields.
        """
        super().add_fields(log_record, record, message_dict)
        
        # Add standard fields
        log_record["timestamp"] = self.formatTime(record, self.datefmt)
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["hostname"] = _CACHED_HOSTNAME
        log_record["pid"] = _CACHED_PID
        
        # Add exception info if present
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)


# Create formatters
text_formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
json_formatter = CorrelationIdJsonFormatter(
    "%(timestamp)s %(level)s %(logger)s %(message)s",
    datefmt=LOG_DATE_FORMAT
)


class LoggingService:
    """Simplified logging service for reverse proxy."""

    def __init__(self) -> None:
        """Initialize logging service."""
        self._loggers: Dict[str, logging.Logger] = {}

    def get_logger(self, name: str) -> logging.Logger:
        """Get or create a logger with the given name.

        Args:
            name: Logger name.

        Returns:
            Configured logger instance.
        """
        if name not in self._loggers:
            logger = logging.getLogger(name)
            self._loggers[name] = logger
        return self._loggers[name]

# Made with Bob
