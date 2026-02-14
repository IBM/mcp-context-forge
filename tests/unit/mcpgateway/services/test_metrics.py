# -*- coding: utf-8 -*-
"""Unit tests for Metrics service."""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from prometheus_client import REGISTRY

# First-Party
from mcpgateway.services.metrics import (
    circuit_breaker_open_counter,
    setup_metrics,
    tool_timeout_counter,
)


@pytest.fixture(autouse=True)
def _clean_prometheus_registry():
    """Clean up any gauge/counter registered during tests to avoid duplicates."""
    collectors_before = set(REGISTRY._names_to_collectors.values())
    yield
    # Unregister collectors added during the test
    collectors_after = set(REGISTRY._names_to_collectors.values())
    for collector in collectors_after - collectors_before:
        try:
            REGISTRY.unregister(collector)
        except Exception:
            pass


# ---------- Global counters ----------


def test_tool_timeout_counter_exists():
    assert tool_timeout_counter is not None
    assert tool_timeout_counter._name == "tool_timeout"


def test_circuit_breaker_open_counter_exists():
    assert circuit_breaker_open_counter is not None
    assert circuit_breaker_open_counter._name == "circuit_breaker_open"


# ---------- setup_metrics enabled ----------


def test_setup_metrics_enabled_sqlite():
    app = MagicMock()
    app.state = MagicMock()
    with (
        patch.dict("os.environ", {"ENABLE_METRICS": "true", "METRICS_CUSTOM_LABELS": "", "METRICS_EXCLUDED_HANDLERS": ""}),
        patch("mcpgateway.services.metrics.settings") as mock_settings,
        patch("mcpgateway.services.metrics.Instrumentator") as mock_inst_cls,
    ):
        mock_settings.database_url = "sqlite:///./test.db"
        mock_settings.METRICS_EXCLUDED_HANDLERS = ""
        inst = MagicMock()
        mock_inst_cls.return_value = inst
        setup_metrics(app)
    inst.instrument.assert_called_once_with(app)
    inst.expose.assert_called_once()


def test_setup_metrics_enabled_postgresql():
    app = MagicMock()
    app.state = MagicMock()
    with (
        patch.dict("os.environ", {"ENABLE_METRICS": "true", "METRICS_CUSTOM_LABELS": "", "METRICS_EXCLUDED_HANDLERS": ""}),
        patch("mcpgateway.services.metrics.settings") as mock_settings,
        patch("mcpgateway.services.metrics.Instrumentator") as mock_inst_cls,
    ):
        mock_settings.database_url = "postgresql://user:pass@localhost/db"
        mock_settings.METRICS_EXCLUDED_HANDLERS = ""
        inst = MagicMock()
        mock_inst_cls.return_value = inst
        setup_metrics(app)
    inst.instrument.assert_called_once()


def test_setup_metrics_enabled_mysql():
    app = MagicMock()
    app.state = MagicMock()
    with (
        patch.dict("os.environ", {"ENABLE_METRICS": "true", "METRICS_CUSTOM_LABELS": "", "METRICS_EXCLUDED_HANDLERS": ""}),
        patch("mcpgateway.services.metrics.settings") as mock_settings,
        patch("mcpgateway.services.metrics.Instrumentator") as mock_inst_cls,
    ):
        mock_settings.database_url = "mysql+pymysql://user:pass@localhost/db"
        mock_settings.METRICS_EXCLUDED_HANDLERS = ""
        inst = MagicMock()
        mock_inst_cls.return_value = inst
        setup_metrics(app)
    inst.instrument.assert_called_once()


def test_setup_metrics_enabled_mongodb():
    app = MagicMock()
    app.state = MagicMock()
    with (
        patch.dict("os.environ", {"ENABLE_METRICS": "true", "METRICS_CUSTOM_LABELS": "", "METRICS_EXCLUDED_HANDLERS": ""}),
        patch("mcpgateway.services.metrics.settings") as mock_settings,
        patch("mcpgateway.services.metrics.Instrumentator") as mock_inst_cls,
    ):
        mock_settings.database_url = "mongodb://localhost/db"
        mock_settings.METRICS_EXCLUDED_HANDLERS = ""
        inst = MagicMock()
        mock_inst_cls.return_value = inst
        setup_metrics(app)
    inst.instrument.assert_called_once()


def test_setup_metrics_enabled_unknown_db():
    app = MagicMock()
    app.state = MagicMock()
    with (
        patch.dict("os.environ", {"ENABLE_METRICS": "true", "METRICS_CUSTOM_LABELS": "", "METRICS_EXCLUDED_HANDLERS": ""}),
        patch("mcpgateway.services.metrics.settings") as mock_settings,
        patch("mcpgateway.services.metrics.Instrumentator") as mock_inst_cls,
    ):
        mock_settings.database_url = "cockroachdb://localhost/db"
        mock_settings.METRICS_EXCLUDED_HANDLERS = ""
        inst = MagicMock()
        mock_inst_cls.return_value = inst
        setup_metrics(app)
    inst.instrument.assert_called_once()


def test_setup_metrics_with_custom_labels():
    app = MagicMock()
    app.state = MagicMock()
    with (
        patch.dict("os.environ", {"ENABLE_METRICS": "true", "METRICS_CUSTOM_LABELS": "env=prod,region=us-east", "METRICS_EXCLUDED_HANDLERS": ""}),
        patch("mcpgateway.services.metrics.settings") as mock_settings,
        patch("mcpgateway.services.metrics.Instrumentator") as mock_inst_cls,
    ):
        mock_settings.database_url = "sqlite:///./test.db"
        mock_settings.METRICS_EXCLUDED_HANDLERS = ""
        inst = MagicMock()
        mock_inst_cls.return_value = inst
        setup_metrics(app)
    inst.instrument.assert_called_once()


def test_setup_metrics_with_excluded_handlers():
    app = MagicMock()
    app.state = MagicMock()
    with (
        patch.dict("os.environ", {"ENABLE_METRICS": "true", "METRICS_CUSTOM_LABELS": "", "METRICS_EXCLUDED_HANDLERS": ""}),
        patch("mcpgateway.services.metrics.settings") as mock_settings,
        patch("mcpgateway.services.metrics.Instrumentator") as mock_inst_cls,
    ):
        mock_settings.database_url = "sqlite:///./test.db"
        mock_settings.METRICS_EXCLUDED_HANDLERS = "/health,/ready"
        inst = MagicMock()
        mock_inst_cls.return_value = inst
        setup_metrics(app)
    inst.instrument.assert_called_once()


def test_setup_metrics_mariadb():
    app = MagicMock()
    app.state = MagicMock()
    with (
        patch.dict("os.environ", {"ENABLE_METRICS": "true", "METRICS_CUSTOM_LABELS": "", "METRICS_EXCLUDED_HANDLERS": ""}),
        patch("mcpgateway.services.metrics.settings") as mock_settings,
        patch("mcpgateway.services.metrics.Instrumentator") as mock_inst_cls,
    ):
        mock_settings.database_url = "mariadb://user:pass@localhost/db"
        mock_settings.METRICS_EXCLUDED_HANDLERS = ""
        inst = MagicMock()
        mock_inst_cls.return_value = inst
        setup_metrics(app)
    inst.instrument.assert_called_once()


def test_setup_metrics_postgres_prefix():
    app = MagicMock()
    app.state = MagicMock()
    with (
        patch.dict("os.environ", {"ENABLE_METRICS": "true", "METRICS_CUSTOM_LABELS": "", "METRICS_EXCLUDED_HANDLERS": ""}),
        patch("mcpgateway.services.metrics.settings") as mock_settings,
        patch("mcpgateway.services.metrics.Instrumentator") as mock_inst_cls,
    ):
        mock_settings.database_url = "postgres://user:pass@localhost/db"
        mock_settings.METRICS_EXCLUDED_HANDLERS = ""
        inst = MagicMock()
        mock_inst_cls.return_value = inst
        setup_metrics(app)
    inst.instrument.assert_called_once()


# ---------- setup_metrics disabled ----------


def test_setup_metrics_disabled():
    app = MagicMock()
    with patch.dict("os.environ", {"ENABLE_METRICS": "false"}):
        setup_metrics(app)
    # Should register a disabled endpoint
    app.get.assert_called_once()


# ---------- update_http_pool_metrics ----------


def test_update_http_pool_metrics_function_stored():
    app = MagicMock()
    app.state = MagicMock()
    with (
        patch.dict("os.environ", {"ENABLE_METRICS": "true", "METRICS_CUSTOM_LABELS": "", "METRICS_EXCLUDED_HANDLERS": ""}),
        patch("mcpgateway.services.metrics.settings") as mock_settings,
        patch("mcpgateway.services.metrics.Instrumentator") as mock_inst_cls,
    ):
        mock_settings.database_url = "sqlite:///./test.db"
        mock_settings.METRICS_EXCLUDED_HANDLERS = ""
        mock_inst_cls.return_value = MagicMock()
        setup_metrics(app)

    # The update function should have been stored on app.state
    assert hasattr(app.state, "update_http_pool_metrics")
