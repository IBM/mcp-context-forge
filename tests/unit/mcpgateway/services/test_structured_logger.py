# -*- coding: utf-8 -*-
"""Unit tests for StructuredLogger service."""

# Standard
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.structured_logger import (
    ComponentLogger,
    LogCategory,
    LogEnricher,
    LogLevel,
    LogRouter,
    StructuredLogger,
    _should_log,
    get_structured_logger,
)


# ---------- _should_log ----------


def test_should_log_info_with_info_threshold():
    with patch("mcpgateway.services.structured_logger.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        assert _should_log(LogLevel.INFO) is True


def test_should_log_debug_below_info_threshold():
    with patch("mcpgateway.services.structured_logger.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        assert _should_log(LogLevel.DEBUG) is False


def test_should_log_error_above_info_threshold():
    with patch("mcpgateway.services.structured_logger.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        assert _should_log(LogLevel.ERROR) is True


def test_should_log_with_string_level():
    with patch("mcpgateway.services.structured_logger.settings") as mock_settings:
        mock_settings.log_level = "WARNING"
        assert _should_log("ERROR") is True
        assert _should_log("DEBUG") is False


def test_should_log_unknown_level_defaults_to_info():
    with patch("mcpgateway.services.structured_logger.settings") as mock_settings:
        mock_settings.log_level = "UNKNOWN"
        # Both unknown levels default to INFO (20), so INFO >= INFO is True
        assert _should_log("UNKNOWN") is True


def test_should_log_critical():
    with patch("mcpgateway.services.structured_logger.settings") as mock_settings:
        mock_settings.log_level = "CRITICAL"
        assert _should_log(LogLevel.CRITICAL) is True
        assert _should_log(LogLevel.ERROR) is False


# ---------- LogEnricher ----------


def test_enrich_adds_correlation_id():
    with patch("mcpgateway.services.structured_logger.get_correlation_id", return_value="corr-123"):
        entry = LogEnricher.enrich({"message": "test"})
    assert entry["correlation_id"] == "corr-123"


def test_enrich_no_correlation_id():
    with patch("mcpgateway.services.structured_logger.get_correlation_id", return_value=None):
        entry = LogEnricher.enrich({"message": "test"})
    assert "correlation_id" not in entry


def test_enrich_adds_hostname_and_pid():
    with patch("mcpgateway.services.structured_logger.get_correlation_id", return_value=None):
        entry = LogEnricher.enrich({})
    assert "hostname" in entry
    assert "process_id" in entry


def test_enrich_does_not_overwrite_existing_hostname():
    with patch("mcpgateway.services.structured_logger.get_correlation_id", return_value=None):
        entry = LogEnricher.enrich({"hostname": "custom-host", "process_id": 999})
    assert entry["hostname"] == "custom-host"
    assert entry["process_id"] == 999


def test_enrich_adds_timestamp():
    with patch("mcpgateway.services.structured_logger.get_correlation_id", return_value=None):
        entry = LogEnricher.enrich({})
    assert "timestamp" in entry
    assert isinstance(entry["timestamp"], datetime)


def test_enrich_does_not_overwrite_existing_timestamp():
    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    with patch("mcpgateway.services.structured_logger.get_correlation_id", return_value=None):
        entry = LogEnricher.enrich({"timestamp": ts})
    assert entry["timestamp"] == ts


def test_enrich_with_performance_tracker():
    mock_tracker = MagicMock()
    mock_tracker.get_current_operations.return_value = ["op1", "op2"]
    with (
        patch("mcpgateway.services.structured_logger.get_correlation_id", return_value="corr-1"),
        patch("mcpgateway.services.structured_logger.get_performance_tracker", return_value=mock_tracker),
    ):
        entry = LogEnricher.enrich({})
    assert entry["active_operations"] == 2


def test_enrich_perf_tracker_exception():
    with (
        patch("mcpgateway.services.structured_logger.get_correlation_id", return_value="corr-1"),
        patch("mcpgateway.services.structured_logger.get_performance_tracker", side_effect=RuntimeError("fail")),
    ):
        entry = LogEnricher.enrich({})
    # Should not crash, graceful degradation
    assert "active_operations" not in entry


def test_enrich_with_otel_trace_context():
    mock_span = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.is_valid = True
    mock_ctx.trace_id = 0x1234567890ABCDEF1234567890ABCDEF
    mock_ctx.span_id = 0x1234567890ABCDEF
    mock_span.get_span_context.return_value = mock_ctx

    with (
        patch("mcpgateway.services.structured_logger.get_correlation_id", return_value=None),
        patch("mcpgateway.services.structured_logger._OTEL_AVAILABLE", True),
        patch("mcpgateway.services.structured_logger.otel_trace") as mock_otel,
    ):
        mock_otel.get_current_span.return_value = mock_span
        entry = LogEnricher.enrich({})
    assert "trace_id" in entry
    assert "span_id" in entry


def test_enrich_otel_not_available():
    with (
        patch("mcpgateway.services.structured_logger.get_correlation_id", return_value=None),
        patch("mcpgateway.services.structured_logger._OTEL_AVAILABLE", False),
    ):
        entry = LogEnricher.enrich({})
    assert "trace_id" not in entry


def test_enrich_otel_exception():
    with (
        patch("mcpgateway.services.structured_logger.get_correlation_id", return_value=None),
        patch("mcpgateway.services.structured_logger._OTEL_AVAILABLE", True),
        patch("mcpgateway.services.structured_logger.otel_trace") as mock_otel,
    ):
        mock_otel.get_current_span.side_effect = RuntimeError("otel fail")
        entry = LogEnricher.enrich({})
    assert "trace_id" not in entry


# ---------- LogRouter ----------


def test_log_router_init():
    with patch("mcpgateway.services.structured_logger.settings") as mock_settings:
        mock_settings.structured_logging_database_enabled = True
        mock_settings.structured_logging_external_enabled = False
        router = LogRouter()
    assert router.database_enabled is True
    assert router.external_enabled is False


def test_log_to_python_logger():
    router = LogRouter.__new__(LogRouter)
    router.database_enabled = False
    router.external_enabled = False
    with patch("mcpgateway.services.structured_logger.logger") as mock_logger:
        router.route({"level": "INFO", "message": "test msg", "component": "test"})
    mock_logger.log.assert_called_once()


def test_log_to_python_logger_with_component():
    router = LogRouter.__new__(LogRouter)
    router.database_enabled = False
    router.external_enabled = False
    with patch("mcpgateway.services.structured_logger.logger") as mock_logger:
        router._log_to_python_logger({"level": "WARNING", "message": "hello", "component": "mycomp"})
    args = mock_logger.log.call_args
    assert "[mycomp] hello" in args[0][1]


def test_log_to_python_logger_no_component():
    router = LogRouter.__new__(LogRouter)
    router.database_enabled = False
    router.external_enabled = False
    with patch("mcpgateway.services.structured_logger.logger") as mock_logger:
        router._log_to_python_logger({"level": "INFO", "message": "bare msg"})
    args = mock_logger.log.call_args
    assert args[0][1] == "bare msg"


def test_persist_to_database_success():
    mock_db = MagicMock()
    router = LogRouter.__new__(LogRouter)
    router.database_enabled = True
    router.external_enabled = False
    with patch("mcpgateway.services.structured_logger.settings") as mock_settings:
        mock_settings.environment = "test"
        mock_settings.version = "1.0"
        router._persist_to_database({"level": "INFO", "message": "test"}, db=mock_db)
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


def test_persist_to_database_creates_session_when_none():
    mock_session = MagicMock()
    router = LogRouter.__new__(LogRouter)
    router.database_enabled = True
    router.external_enabled = False
    with (
        patch("mcpgateway.services.structured_logger.SessionLocal", return_value=mock_session),
        patch("mcpgateway.services.structured_logger.settings") as mock_settings,
    ):
        mock_settings.environment = "test"
        mock_settings.version = "1.0"
        router._persist_to_database({"level": "INFO", "message": "test"}, db=None)
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()
    mock_session.close.assert_called_once()


def test_persist_to_database_with_error_details():
    mock_db = MagicMock()
    router = LogRouter.__new__(LogRouter)
    with patch("mcpgateway.services.structured_logger.settings") as mock_settings:
        mock_settings.environment = "test"
        mock_settings.version = "1.0"
        router._persist_to_database(
            {
                "level": "ERROR",
                "message": "fail",
                "error_type": "ValueError",
                "error_message": "bad value",
                "error_stack_trace": "traceback...",
            },
            db=mock_db,
        )
    mock_db.add.assert_called_once()


def test_persist_to_database_with_performance_metrics():
    mock_db = MagicMock()
    router = LogRouter.__new__(LogRouter)
    with patch("mcpgateway.services.structured_logger.settings") as mock_settings:
        mock_settings.environment = "test"
        mock_settings.version = "1.0"
        router._persist_to_database(
            {"level": "INFO", "message": "perf", "database_query_count": 5, "cache_hits": 10},
            db=mock_db,
        )
    mock_db.add.assert_called_once()


def test_persist_to_database_with_security_fields():
    mock_db = MagicMock()
    router = LogRouter.__new__(LogRouter)
    with patch("mcpgateway.services.structured_logger.settings") as mock_settings:
        mock_settings.environment = "test"
        mock_settings.version = "1.0"
        router._persist_to_database(
            {"level": "WARNING", "message": "sec", "security_event_type": "intrusion", "is_security_event": True, "security_severity": "HIGH"},
            db=mock_db,
        )
    mock_db.add.assert_called_once()


def test_persist_to_database_exception_rollback():
    mock_db = MagicMock()
    mock_db.add.side_effect = Exception("DB error")
    router = LogRouter.__new__(LogRouter)
    with patch("mcpgateway.services.structured_logger.settings") as mock_settings:
        mock_settings.environment = "test"
        mock_settings.version = "1.0"
        router._persist_to_database({"level": "INFO", "message": "test"}, db=mock_db)
    mock_db.rollback.assert_called_once()


def test_persist_to_database_exception_closes_own_session():
    mock_session = MagicMock()
    mock_session.add.side_effect = Exception("DB error")
    router = LogRouter.__new__(LogRouter)
    with (
        patch("mcpgateway.services.structured_logger.SessionLocal", return_value=mock_session),
        patch("mcpgateway.services.structured_logger.settings") as mock_settings,
    ):
        mock_settings.environment = "test"
        mock_settings.version = "1.0"
        router._persist_to_database({"level": "INFO", "message": "test"}, db=None)
    mock_session.rollback.assert_called_once()
    mock_session.close.assert_called_once()


def test_route_with_database_and_external():
    router = LogRouter.__new__(LogRouter)
    router.database_enabled = True
    router.external_enabled = True
    with (
        patch.object(router, "_log_to_python_logger") as mock_py,
        patch.object(router, "_persist_to_database") as mock_db,
        patch.object(router, "_send_to_external") as mock_ext,
    ):
        router.route({"level": "INFO", "message": "test"})
    mock_py.assert_called_once()
    mock_db.assert_called_once()
    mock_ext.assert_called_once()


def test_route_database_disabled():
    router = LogRouter.__new__(LogRouter)
    router.database_enabled = False
    router.external_enabled = False
    with (
        patch.object(router, "_log_to_python_logger") as mock_py,
        patch.object(router, "_persist_to_database") as mock_db,
    ):
        router.route({"level": "INFO", "message": "test"})
    mock_py.assert_called_once()
    mock_db.assert_not_called()


# ---------- StructuredLogger ----------


def test_structured_logger_init():
    with patch("mcpgateway.services.structured_logger.settings"):
        sl = StructuredLogger("test-component")
    assert sl.component == "test-component"


def test_structured_logger_log_early_termination():
    with patch("mcpgateway.services.structured_logger.settings"):
        sl = StructuredLogger("comp")
    with patch("mcpgateway.services.structured_logger._should_log", return_value=False):
        with patch.object(sl.router, "route") as mock_route:
            sl.log(LogLevel.DEBUG, "should be skipped")
    mock_route.assert_not_called()


def test_structured_logger_log_with_error():
    with patch("mcpgateway.services.structured_logger.settings"):
        sl = StructuredLogger("comp")
    err = ValueError("test error")
    with (
        patch("mcpgateway.services.structured_logger._should_log", return_value=True),
        patch.object(sl.enricher, "enrich", side_effect=lambda e: e),
        patch.object(sl.router, "route") as mock_route,
    ):
        sl.log(LogLevel.ERROR, "error occurred", error=err)
    entry = mock_route.call_args[0][0]
    assert entry["error_type"] == "ValueError"
    assert entry["error_message"] == "test error"
    assert "error_stack_trace" in entry


def test_structured_logger_log_with_category_enum():
    with patch("mcpgateway.services.structured_logger.settings"):
        sl = StructuredLogger("comp")
    with (
        patch("mcpgateway.services.structured_logger._should_log", return_value=True),
        patch.object(sl.enricher, "enrich", side_effect=lambda e: e),
        patch.object(sl.router, "route") as mock_route,
    ):
        sl.log(LogLevel.INFO, "test", category=LogCategory.SECURITY)
    entry = mock_route.call_args[0][0]
    assert entry["category"] == "security"


def test_structured_logger_log_with_string_category():
    with patch("mcpgateway.services.structured_logger.settings"):
        sl = StructuredLogger("comp")
    with (
        patch("mcpgateway.services.structured_logger._should_log", return_value=True),
        patch.object(sl.enricher, "enrich", side_effect=lambda e: e),
        patch.object(sl.router, "route") as mock_route,
    ):
        sl.log(LogLevel.INFO, "test", category="custom_category")
    entry = mock_route.call_args[0][0]
    assert entry["category"] == "custom_category"


def test_structured_logger_log_with_kwargs():
    with patch("mcpgateway.services.structured_logger.settings"):
        sl = StructuredLogger("comp")
    with (
        patch("mcpgateway.services.structured_logger._should_log", return_value=True),
        patch.object(sl.enricher, "enrich", side_effect=lambda e: e),
        patch.object(sl.router, "route") as mock_route,
    ):
        sl.log(LogLevel.INFO, "test", user_id="u1", custom_fields={"k": "v"}, extra_field="val")
    entry = mock_route.call_args[0][0]
    assert entry["user_id"] == "u1"
    assert entry["custom_fields"] == {"k": "v"}
    assert entry["extra_field"] == "val"


def test_structured_logger_log_with_string_level():
    with patch("mcpgateway.services.structured_logger.settings"):
        sl = StructuredLogger("comp")
    with (
        patch("mcpgateway.services.structured_logger._should_log", return_value=True),
        patch.object(sl.enricher, "enrich", side_effect=lambda e: e),
        patch.object(sl.router, "route") as mock_route,
    ):
        sl.log("INFO", "test")
    entry = mock_route.call_args[0][0]
    assert entry["level"] == "INFO"


# ---------- Convenience methods ----------


def test_debug_method():
    with patch("mcpgateway.services.structured_logger.settings"):
        sl = StructuredLogger("comp")
    with patch.object(sl, "log") as mock_log:
        sl.debug("debug msg", user_id="u1")
    mock_log.assert_called_once_with(LogLevel.DEBUG, "debug msg", user_id="u1")


def test_info_method():
    with patch("mcpgateway.services.structured_logger.settings"):
        sl = StructuredLogger("comp")
    with patch.object(sl, "log") as mock_log:
        sl.info("info msg")
    mock_log.assert_called_once_with(LogLevel.INFO, "info msg")


def test_warning_method():
    with patch("mcpgateway.services.structured_logger.settings"):
        sl = StructuredLogger("comp")
    with patch.object(sl, "log") as mock_log:
        sl.warning("warn msg")
    mock_log.assert_called_once_with(LogLevel.WARNING, "warn msg")


def test_error_method():
    with patch("mcpgateway.services.structured_logger.settings"):
        sl = StructuredLogger("comp")
    err = RuntimeError("fail")
    with patch.object(sl, "log") as mock_log:
        sl.error("error msg", error=err, user_id="u1")
    mock_log.assert_called_once_with(LogLevel.ERROR, "error msg", error=err, user_id="u1")


def test_critical_method():
    with patch("mcpgateway.services.structured_logger.settings"):
        sl = StructuredLogger("comp")
    err = RuntimeError("critical fail")
    with patch.object(sl, "log") as mock_log:
        sl.critical("critical msg", error=err)
    mock_log.assert_called_once_with(LogLevel.CRITICAL, "critical msg", error=err)


# ---------- ComponentLogger ----------


def test_component_logger_get_logger():
    ComponentLogger.clear_loggers()
    with patch("mcpgateway.services.structured_logger.settings"):
        lg = ComponentLogger.get_logger("test-comp")
    assert isinstance(lg, StructuredLogger)
    assert lg.component == "test-comp"


def test_component_logger_caches():
    ComponentLogger.clear_loggers()
    with patch("mcpgateway.services.structured_logger.settings"):
        lg1 = ComponentLogger.get_logger("same-comp")
        lg2 = ComponentLogger.get_logger("same-comp")
    assert lg1 is lg2


def test_component_logger_clear():
    ComponentLogger.clear_loggers()
    with patch("mcpgateway.services.structured_logger.settings"):
        ComponentLogger.get_logger("comp1")
    assert len(ComponentLogger._loggers) > 0
    ComponentLogger.clear_loggers()
    assert len(ComponentLogger._loggers) == 0


# ---------- get_structured_logger ----------


def test_get_structured_logger_default():
    ComponentLogger.clear_loggers()
    with patch("mcpgateway.services.structured_logger.settings"):
        lg = get_structured_logger()
    assert isinstance(lg, StructuredLogger)
    assert lg.component == "mcpgateway"


def test_get_structured_logger_custom():
    ComponentLogger.clear_loggers()
    with patch("mcpgateway.services.structured_logger.settings"):
        lg = get_structured_logger("my-module")
    assert lg.component == "my-module"


# ---------- Persist to database context fields ----------


def test_persist_to_database_with_context_fields():
    mock_db = MagicMock()
    router = LogRouter.__new__(LogRouter)
    with patch("mcpgateway.services.structured_logger.settings") as mock_settings:
        mock_settings.environment = "test"
        mock_settings.version = "1.0"
        router._persist_to_database(
            {
                "level": "INFO",
                "message": "ctx",
                "team_id": "t1",
                "request_query": "q=1",
                "business_event_type": "login",
                "resource_type": "tool",
            },
            db=mock_db,
        )
    mock_db.add.assert_called_once()
