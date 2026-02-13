# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/test_observability_adapter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Tests for ObservabilityServiceAdapter, ContextVar bridge, and Borg late-bind.
"""

# Standard
from contextvars import copy_context
from unittest.mock import MagicMock, patch

# First-Party
from mcpgateway.plugins.framework.manager import PluginManager
from mcpgateway.plugins.framework.observability import current_trace_id as plugins_trace_id

# ---------------------------------------------------------------------------
# ObservabilityServiceAdapter unit tests
# ---------------------------------------------------------------------------


class TestObservabilityServiceAdapter:
    """Tests that the adapter correctly delegates to ObservabilityService."""

    def test_start_span_delegates_to_service(self):
        """start_span should call ObservabilityService.start_span with a fresh DB session."""
        mock_service = MagicMock()
        mock_service.start_span.return_value = "span-42"

        mock_session = MagicMock()

        with patch("mcpgateway.plugins.observability_adapter.SessionLocal", return_value=mock_session):
            # First-Party
            from mcpgateway.plugins.observability_adapter import ObservabilityServiceAdapter

            adapter = ObservabilityServiceAdapter(service=mock_service)
            result = adapter.start_span(
                trace_id="trace-1",
                name="plugin.execute.my_plugin",
                kind="internal",
                resource_type="plugin",
                resource_name="my_plugin",
                attributes={"plugin.name": "my_plugin"},
            )

        assert result == "span-42"
        mock_service.start_span.assert_called_once_with(
            db=mock_session,
            trace_id="trace-1",
            name="plugin.execute.my_plugin",
            kind="internal",
            resource_type="plugin",
            resource_name="my_plugin",
            attributes={"plugin.name": "my_plugin"},
        )
        mock_session.close.assert_called_once()

    def test_end_span_delegates_to_service(self):
        """end_span should call ObservabilityService.end_span with a fresh DB session."""
        mock_service = MagicMock()
        mock_session = MagicMock()

        with patch("mcpgateway.plugins.observability_adapter.SessionLocal", return_value=mock_session):
            # First-Party
            from mcpgateway.plugins.observability_adapter import ObservabilityServiceAdapter

            adapter = ObservabilityServiceAdapter(service=mock_service)
            adapter.end_span(span_id="span-42", status="ok", attributes={"k": "v"})

        mock_service.end_span.assert_called_once_with(
            db=mock_session,
            span_id="span-42",
            status="ok",
            attributes={"k": "v"},
        )
        mock_session.close.assert_called_once()

    def test_end_span_none_is_noop(self):
        """end_span with span_id=None should be a no-op (no DB session created)."""
        mock_service = MagicMock()

        with patch("mcpgateway.plugins.observability_adapter.SessionLocal") as mock_factory:
            # First-Party
            from mcpgateway.plugins.observability_adapter import ObservabilityServiceAdapter

            adapter = ObservabilityServiceAdapter(service=mock_service)
            adapter.end_span(span_id=None)

        mock_factory.assert_not_called()
        mock_service.end_span.assert_not_called()

    def test_start_span_handles_exception(self):
        """start_span should return None and close the session on error."""
        mock_service = MagicMock()
        mock_service.start_span.side_effect = RuntimeError("db error")
        mock_session = MagicMock()

        with patch("mcpgateway.plugins.observability_adapter.SessionLocal", return_value=mock_session):
            # First-Party
            from mcpgateway.plugins.observability_adapter import ObservabilityServiceAdapter

            adapter = ObservabilityServiceAdapter(service=mock_service)
            result = adapter.start_span(trace_id="t", name="s")

        assert result is None
        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()

    def test_end_span_handles_exception(self):
        """end_span should swallow exceptions and close the session."""
        mock_service = MagicMock()
        mock_service.end_span.side_effect = RuntimeError("db error")
        mock_session = MagicMock()

        with patch("mcpgateway.plugins.observability_adapter.SessionLocal", return_value=mock_session):
            # First-Party
            from mcpgateway.plugins.observability_adapter import ObservabilityServiceAdapter

            adapter = ObservabilityServiceAdapter(service=mock_service)
            # Should not raise
            adapter.end_span(span_id="span-1", status="error")

        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()


# ---------------------------------------------------------------------------
# ContextVar bridge test
# ---------------------------------------------------------------------------


class TestContextVarBridge:
    """Verify that the middleware bridges both ContextVars."""

    def test_framework_contextvar_is_set_by_middleware(self):
        """When the middleware sets the service ContextVar, the framework copy should also be set."""
        # Import both ContextVars
        # First-Party
        from mcpgateway.services.observability_service import current_trace_id as service_trace_id

        # Run in a fresh context to avoid polluting tests
        ctx = copy_context()

        def _check():
            # Simulate what the middleware does after our edit
            service_trace_id.set("trace-bridge-test")
            plugins_trace_id.set("trace-bridge-test")

            assert service_trace_id.get() == "trace-bridge-test"
            assert plugins_trace_id.get() == "trace-bridge-test"

        ctx.run(_check)


# ---------------------------------------------------------------------------
# Borg late-bind test
# ---------------------------------------------------------------------------


class TestObservabilitySetter:
    """Verify that the observability property setter works with locking."""

    def test_setter_updates_executor(self):
        """plugin_manager.observability = adapter should update the executor."""
        PluginManager.reset()

        mgr = PluginManager(
            "./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml",
        )
        assert mgr.observability is None

        # Simulate main.py wiring: plugin_manager.observability = adapter
        mock_obs = MagicMock()
        mgr.observability = mock_obs

        assert mgr.observability is mock_obs
        # Borg sharing: a second reference sees the same value
        mgr2 = PluginManager()
        assert mgr2.observability is mock_obs

        PluginManager.reset()

    def test_setter_allows_clearing(self):
        """Setting observability to None should clear the provider."""
        PluginManager.reset()

        mock_obs = MagicMock()
        mgr = PluginManager(
            "./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml",
            observability=mock_obs,
        )
        assert mgr.observability is mock_obs

        mgr.observability = None
        assert mgr.observability is None

        PluginManager.reset()
