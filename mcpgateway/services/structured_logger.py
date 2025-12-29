# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/structured_logger.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Structured Logger Service.

This module provides comprehensive structured logging with component-based loggers,
automatic enrichment, intelligent routing, and database persistence.
"""

# Standard
from datetime import datetime, timezone
from enum import Enum
import logging
import os
import socket
import traceback
from typing import Any, Dict, List, Optional, Union

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import SessionLocal, StructuredLogEntry
from mcpgateway.services.performance_tracker import get_performance_tracker
from mcpgateway.utils.correlation_id import get_correlation_id

# Optional OpenTelemetry support - import once at module level for performance
try:
    # Third-Party
    from opentelemetry import trace as otel_trace

    _OTEL_AVAILABLE = True
except ImportError:
    otel_trace = None  # type: ignore[assignment]
    _OTEL_AVAILABLE = False

logger = logging.getLogger(__name__)

# Cache static values at module load - these don't change during process lifetime
_CACHED_HOSTNAME: str = socket.gethostname()
_CACHED_PID: int = os.getpid()


class LogLevel(str, Enum):
    """Log levels matching Python logging."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogCategory(str, Enum):
    """Log categories for classification."""

    APPLICATION = "application"
    REQUEST = "request"
    SECURITY = "security"
    PERFORMANCE = "performance"
    DATABASE = "database"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    EXTERNAL_SERVICE = "external_service"
    BUSINESS_LOGIC = "business_logic"
    SYSTEM = "system"


# Log level numeric values for comparison (matches Python logging module)
_LOG_LEVEL_VALUES: Dict[str, int] = {
    "DEBUG": logging.DEBUG,  # 10
    "INFO": logging.INFO,  # 20
    "WARNING": logging.WARNING,  # 30
    "ERROR": logging.ERROR,  # 40
    "CRITICAL": logging.CRITICAL,  # 50
}


def _should_log(level: Union[LogLevel, str]) -> bool:
    """Check if a log level should be processed based on settings.log_level.

    This enables early termination of log processing to avoid expensive
    enrichment and database operations for messages below the configured threshold.

    Args:
        level: The log level to check (LogLevel enum or string)

    Returns:
        True if the level meets or exceeds the configured threshold
    """
    # Get string value from enum if needed
    level_str = level.value if isinstance(level, LogLevel) else str(level).upper()

    # Get numeric values for comparison
    entry_level = _LOG_LEVEL_VALUES.get(level_str, logging.INFO)
    config_level = _LOG_LEVEL_VALUES.get(settings.log_level.upper(), logging.INFO)

    return entry_level >= config_level


class LogEnricher:
    """Enriches log entries with contextual information."""

    @staticmethod
    def enrich(entry: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich log entry with system and context information.

        Args:
            entry: Base log entry

        Returns:
            Enriched log entry
        """
        # Get correlation ID
        correlation_id = get_correlation_id()
        if correlation_id:
            entry["correlation_id"] = correlation_id

        # Add hostname and process info - use cached values for performance
        entry.setdefault("hostname", _CACHED_HOSTNAME)
        entry.setdefault("process_id", _CACHED_PID)

        # Add timestamp if not present
        if "timestamp" not in entry:
            entry["timestamp"] = datetime.now(timezone.utc)

        # Add performance metrics if available (skip if tracker not initialized)
        try:
            perf_tracker = get_performance_tracker()
            if correlation_id and perf_tracker and hasattr(perf_tracker, "get_current_operations"):
                current_ops = perf_tracker.get_current_operations(correlation_id)  # pylint: disable=no-member
                if current_ops:
                    entry["active_operations"] = len(current_ops)
        except Exception:  # nosec B110 - Graceful degradation if performance tracker unavailable
            pass

        # Add OpenTelemetry trace context if available (uses module-level import)
        if _OTEL_AVAILABLE:
            try:
                span = otel_trace.get_current_span()
                if span and span.get_span_context().is_valid:
                    ctx = span.get_span_context()
                    entry["trace_id"] = format(ctx.trace_id, "032x")
                    entry["span_id"] = format(ctx.span_id, "016x")
            except Exception:  # nosec B110 - Graceful degradation
                pass

        return entry


class LogRouter:
    """Routes log entries to appropriate destinations."""

    def __init__(self):
        """Initialize log router."""
        self.database_enabled = getattr(settings, "structured_logging_database_enabled", True)
        self.external_enabled = getattr(settings, "structured_logging_external_enabled", False)

    def route(self, entry: Dict[str, Any], db: Optional[Session] = None) -> None:
        """Route log entry to configured destinations.

        Args:
            entry: Log entry to route
            db: Optional database session
        """
        # Always log to standard Python logger
        self._log_to_python_logger(entry)

        # Persist to database if enabled
        if self.database_enabled:
            self._persist_to_database(entry, db)

        # Send to external systems if enabled
        if self.external_enabled:
            self._send_to_external(entry)

    def _log_to_python_logger(self, entry: Dict[str, Any]) -> None:
        """Log to standard Python logger.

        Args:
            entry: Log entry
        """
        level_str = entry.get("level", "INFO")
        level = getattr(logging, level_str, logging.INFO)

        message = entry.get("message", "")
        component = entry.get("component", "")

        log_message = f"[{component}] {message}" if component else message

        # Build extra dict for structured logging
        extra = {k: v for k, v in entry.items() if k not in ["message", "level"]}

        logger.log(level, log_message, extra=extra)

    def _persist_to_database(self, entry: Dict[str, Any], db: Optional[Session] = None) -> None:
        """Persist log entry to database.

        Args:
            entry: Log entry
            db: Optional database session
        """
        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            # Build error_details JSON from error-related fields
            error_details = None
            if any([entry.get("error_type"), entry.get("error_message"), entry.get("error_stack_trace"), entry.get("error_context")]):
                error_details = {
                    "error_type": entry.get("error_type"),
                    "error_message": entry.get("error_message"),
                    "error_stack_trace": entry.get("error_stack_trace"),
                    "error_context": entry.get("error_context"),
                }

            # Build performance_metrics JSON from performance-related fields
            performance_metrics = None
            perf_fields = {
                "database_query_count": entry.get("database_query_count"),
                "database_query_duration_ms": entry.get("database_query_duration_ms"),
                "cache_hits": entry.get("cache_hits"),
                "cache_misses": entry.get("cache_misses"),
                "external_api_calls": entry.get("external_api_calls"),
                "external_api_duration_ms": entry.get("external_api_duration_ms"),
                "memory_usage_mb": entry.get("memory_usage_mb"),
                "cpu_usage_percent": entry.get("cpu_usage_percent"),
            }
            if any(v is not None for v in perf_fields.values()):
                performance_metrics = {k: v for k, v in perf_fields.items() if v is not None}

            # Build threat_indicators JSON from security-related fields
            threat_indicators = None
            security_fields = {
                "security_event_type": entry.get("security_event_type"),
                "security_threat_score": entry.get("security_threat_score"),
                "security_action_taken": entry.get("security_action_taken"),
            }
            if any(v is not None for v in security_fields.values()):
                threat_indicators = {k: v for k, v in security_fields.items() if v is not None}

            # Build context JSON from remaining fields
            context_fields = {
                "team_id": entry.get("team_id"),
                "request_query": entry.get("request_query"),
                "request_headers": entry.get("request_headers"),
                "request_body_size": entry.get("request_body_size"),
                "response_status_code": entry.get("response_status_code"),
                "response_body_size": entry.get("response_body_size"),
                "response_headers": entry.get("response_headers"),
                "business_event_type": entry.get("business_event_type"),
                "business_entity_type": entry.get("business_entity_type"),
                "business_entity_id": entry.get("business_entity_id"),
                "resource_type": entry.get("resource_type"),
                "resource_id": entry.get("resource_id"),
                "resource_action": entry.get("resource_action"),
                "category": entry.get("category"),
                "custom_fields": entry.get("custom_fields"),
                "tags": entry.get("tags"),
                "metadata": entry.get("metadata"),
            }
            context = {k: v for k, v in context_fields.items() if v is not None}

            # Determine if this is a security event
            is_security_event = entry.get("is_security_event", False) or bool(threat_indicators)
            security_severity = entry.get("security_severity")

            log_entry = StructuredLogEntry(
                timestamp=entry.get("timestamp", datetime.now(timezone.utc)),
                level=entry.get("level", "INFO"),
                component=entry.get("component"),
                message=entry.get("message", ""),
                correlation_id=entry.get("correlation_id"),
                request_id=entry.get("request_id"),
                trace_id=entry.get("trace_id"),
                span_id=entry.get("span_id"),
                user_id=entry.get("user_id"),
                user_email=entry.get("user_email"),
                client_ip=entry.get("client_ip"),
                user_agent=entry.get("user_agent"),
                request_method=entry.get("request_method"),
                request_path=entry.get("request_path"),
                duration_ms=entry.get("duration_ms"),
                operation_type=entry.get("operation_type"),
                is_security_event=is_security_event,
                security_severity=security_severity,
                threat_indicators=threat_indicators,
                context=context if context else None,
                error_details=error_details,
                performance_metrics=performance_metrics,
                hostname=entry.get("hostname"),
                process_id=entry.get("process_id"),
                thread_id=entry.get("thread_id"),
                environment=entry.get("environment", getattr(settings, "environment", "development")),
                version=entry.get("version", getattr(settings, "version", "unknown")),
            )

            db.add(log_entry)
            db.commit()

        except Exception as e:
            logger.error(f"Failed to persist log entry to database: {e}", exc_info=True)
            # Also print to console for immediate visibility
            print(f"ERROR persisting log to database: {e}")
            traceback.print_exc()
            if db:
                db.rollback()

        finally:
            if should_close:
                db.close()  # Commit/rollback already handled above

    def _send_to_external(self, entry: Dict[str, Any]) -> None:
        """Send log entry to external systems.

        Args:
            entry: Log entry
        """
        # Placeholder for external logging integration
        # Will be implemented in log exporters


class StructuredLogger:
    """Main structured logger with enrichment and routing."""

    def __init__(self, component: str):
        """Initialize structured logger.

        Args:
            component: Component name for log entries
        """
        self.component = component
        self.enricher = LogEnricher()
        self.router = LogRouter()

    def log(
        self,
        level: Union[LogLevel, str],
        message: str,
        category: Optional[Union[LogCategory, str]] = None,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        team_id: Optional[str] = None,
        error: Optional[Exception] = None,
        duration_ms: Optional[float] = None,
        custom_fields: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        db: Optional[Session] = None,
        **kwargs: Any,
    ) -> None:
        """Log a structured message.

        Args:
            level: Log level
            message: Log message
            category: Log category
            user_id: User identifier
            user_email: User email
            team_id: Team identifier
            error: Exception object
            duration_ms: Operation duration
            custom_fields: Additional custom fields
            tags: Log tags
            db: Optional database session
            **kwargs: Additional fields to include
        """
        # Early termination if log level is below configured threshold
        # This avoids expensive enrichment and database operations for filtered messages
        if not _should_log(level):
            return

        # Build base entry
        entry: Dict[str, Any] = {
            "level": level.value if isinstance(level, LogLevel) else level,
            "component": self.component,
            "message": message,
            "category": category.value if isinstance(category, LogCategory) and category else category if category else None,
            "user_id": user_id,
            "user_email": user_email,
            "team_id": team_id,
            "duration_ms": duration_ms,
            "custom_fields": custom_fields,
            "tags": tags,
        }

        # Add error information if present
        if error:
            entry["error_type"] = type(error).__name__
            entry["error_message"] = str(error)
            entry["error_stack_trace"] = "".join(traceback.format_exception(type(error), error, error.__traceback__))

        # Add any additional kwargs
        entry.update(kwargs)

        # Enrich entry with context
        entry = self.enricher.enrich(entry)

        # Route to destinations
        self.router.route(entry, db)

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message.

        Args:
            message: Log message
            **kwargs: Additional context fields
        """
        self.log(LogLevel.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message.

        Args:
            message: Log message
            **kwargs: Additional context fields
        """
        self.log(LogLevel.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message.

        Args:
            message: Log message
            **kwargs: Additional context fields
        """
        self.log(LogLevel.WARNING, message, **kwargs)

    def error(self, message: str, error: Optional[Exception] = None, **kwargs: Any) -> None:
        """Log error message.

        Args:
            message: Log message
            error: Exception object if available
            **kwargs: Additional context fields
        """
        self.log(LogLevel.ERROR, message, error=error, **kwargs)

    def critical(self, message: str, error: Optional[Exception] = None, **kwargs: Any) -> None:
        """Log critical message.

        Args:
            message: Log message
            error: Exception object if available
            **kwargs: Additional context fields
        """
        self.log(LogLevel.CRITICAL, message, error=error, **kwargs)


class ComponentLogger:
    """Logger factory for component-specific loggers."""

    _loggers: Dict[str, StructuredLogger] = {}

    @classmethod
    def get_logger(cls, component: str) -> StructuredLogger:
        """Get or create a logger for a specific component.

        Args:
            component: Component name

        Returns:
            StructuredLogger instance for the component
        """
        if component not in cls._loggers:
            cls._loggers[component] = StructuredLogger(component)
        return cls._loggers[component]

    @classmethod
    def clear_loggers(cls) -> None:
        """Clear all cached loggers (useful for testing)."""
        cls._loggers.clear()


# Global structured logger instance for backward compatibility
def get_structured_logger(component: str = "mcpgateway") -> StructuredLogger:
    """Get a structured logger instance.

    Args:
        component: Component name

    Returns:
        StructuredLogger instance
    """
    return ComponentLogger.get_logger(component)
