# -*- coding: utf-8 -*-
"""Location: ./tests/integration/plugins/test_output_length_guard_integration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Integration tests for output_length_guard plugin metrics consumption.

Mirrors test_plugin_metrics_consumer_integration.py: constructs fake
result.metadata directly (no HTTP, no plugin manager) and asserts that
record_plugin_metrics() writes the correct span attributes and metric rows
to a real in-memory SQLite DB.

Prerequisites:
    pip install cpex-output-length-guard  (or install from source per the guide)
"""

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base, ObservabilityMetric, ObservabilitySpan
from mcpgateway.plugins.utils import record_plugin_metrics
from mcpgateway.services.observability_service import ObservabilityService


@pytest.fixture
def test_db_engine():
    """Create in-memory SQLite engine with all tables."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(test_db_engine):
    """Provide a transactional DB session for testing."""
    test_session_local = sessionmaker(bind=test_db_engine)
    session = test_session_local()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def patch_session_local(test_db_engine, monkeypatch):
    """Patch SessionLocal to use test_db_engine."""
    test_session_local = sessionmaker(bind=test_db_engine)
    monkeypatch.setattr("mcpgateway.db.SessionLocal", test_session_local)
    monkeypatch.setattr("mcpgateway.services.observability_service.SessionLocal", test_session_local)


@pytest.fixture
def observability_service():
    """ObservabilityService instance."""
    return ObservabilityService()


class TestOutputLengthGuardMetricsIntegration:
    """record_plugin_metrics() correctly persists output_length_guard metadata."""

    def test_truncate_event_records_span_and_metrics(
        self, db_session, observability_service: ObservabilityService
    ):
        """Truncation metadata -> span attributes + numeric metric rows."""
        trace_id = observability_service.start_trace(name="test_olg_truncate")

        result_metadata = {
            "output_length_guard": {
                "chars_seen": 32000,
                "truncated_count": 3,
                "blocked": False,
                "limit_mode": "character",
                "strategy": "truncate",
                "stage": "tool_post_invoke",
            }
        }

        record_plugin_metrics(trace_id, result_metadata)

        # Span assertions
        span = db_session.query(ObservabilitySpan).filter_by(
            trace_id=trace_id, name="plugin.metrics.output_length_guard"
        ).one()
        assert span.resource_type == "plugin"
        assert span.resource_name == "output_length_guard"
        assert span.status == "ok"
        assert span.attributes["chars_seen"] == 32000
        assert span.attributes["truncated_count"] == 3
        assert span.attributes["blocked"] is False
        assert span.attributes["limit_mode"] == "character"
        assert span.attributes["strategy"] == "truncate"
        assert span.attributes["stage"] == "tool_post_invoke"

        # Metric row assertions (numeric fields only — bool/str do not become rows)
        metrics = db_session.query(ObservabilityMetric).filter_by(trace_id=trace_id).all()
        metrics_by_name = {m.name: m for m in metrics}
        assert set(metrics_by_name) == {
            "plugin.output_length_guard.chars_seen",
            "plugin.output_length_guard.truncated_count",
        }
        assert metrics_by_name["plugin.output_length_guard.chars_seen"].value == 32000.0
        assert metrics_by_name["plugin.output_length_guard.truncated_count"].value == 3.0
        for metric in metrics_by_name.values():
            assert metric.resource_type == "plugin"
            assert metric.resource_id == "output_length_guard"

        observability_service.end_trace(trace_id)

    def test_block_event_records_span_with_blocked_true(
        self, db_session, observability_service: ObservabilityService
    ):
        """Block metadata -> span with blocked=True, no chars_seen/truncated_count metrics."""
        trace_id = observability_service.start_trace(name="test_olg_block")

        result_metadata = {
            "output_length_guard": {
                "chars_seen": 0,
                "truncated_count": 0,
                "blocked": True,
                "limit_mode": "character",
                "strategy": "block",
                "stage": "tool_post_invoke",
            }
        }

        record_plugin_metrics(trace_id, result_metadata)

        span = db_session.query(ObservabilitySpan).filter_by(
            trace_id=trace_id, name="plugin.metrics.output_length_guard"
        ).one()
        assert span.attributes["blocked"] is True
        assert span.attributes["strategy"] == "block"
        assert span.attributes["chars_seen"] == 0
        assert span.attributes["truncated_count"] == 0

        observability_service.end_trace(trace_id)

    def test_no_metrics_without_trace_id(self, db_session):
        """No DB rows written when trace_id is absent."""
        before = db_session.query(ObservabilitySpan).count()
        record_plugin_metrics(
            None,
            {"output_length_guard": {"chars_seen": 100, "truncated_count": 1}},
        )
        assert db_session.query(ObservabilitySpan).count() == before

    def test_plugin_instantiates_with_rust_backend(self):
        """Smoke test: the Rust-backed plugin can be imported and instantiated."""
        from cpex_output_length_guard.output_length_guard import OutputLengthGuardPlugin
        from cpex.framework import PluginConfig, ToolHookType

        config = PluginConfig(
            name="output_length_guard",
            kind="cpex_output_length_guard.output_length_guard.OutputLengthGuardPlugin",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
            config={"max_chars": 5000, "strategy": "truncate"},
        )
        plugin = OutputLengthGuardPlugin(config)
        assert plugin is not None

    def test_truncate_hook_fires_on_oversized_string(self):
        """End-to-end: plugin truncates a plain oversized string result."""
        import asyncio
        from cpex_output_length_guard.output_length_guard import OutputLengthGuardPlugin
        from cpex.framework import GlobalContext, PluginConfig, PluginContext, ToolHookType, ToolPostInvokePayload

        config = PluginConfig(
            name="output_length_guard",
            kind="cpex_output_length_guard.output_length_guard.OutputLengthGuardPlugin",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
            config={"max_chars": 100, "strategy": "truncate"},
        )
        plugin = OutputLengthGuardPlugin(config)
        payload = ToolPostInvokePayload(name="test_tool", result="A" * 500)
        gc = GlobalContext(request_id="req-1", user=None, tenant_id="t1", server_id="gw1")
        context = PluginContext(global_context=gc)
        result = asyncio.run(plugin.tool_post_invoke(payload, context))
        assert result.modified_payload is not None
        assert len(result.modified_payload.result) <= 100  # ellipsis fits within the 100-char budget

    def test_block_hook_fires_on_oversized_string(self):
        """End-to-end: plugin blocks and returns continue_processing=False."""
        import asyncio
        from cpex_output_length_guard.output_length_guard import OutputLengthGuardPlugin
        from cpex.framework import GlobalContext, PluginConfig, PluginContext, ToolHookType, ToolPostInvokePayload

        config = PluginConfig(
            name="output_length_guard",
            kind="cpex_output_length_guard.output_length_guard.OutputLengthGuardPlugin",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
            config={"max_chars": 100, "strategy": "block"},
        )
        plugin = OutputLengthGuardPlugin(config)
        payload = ToolPostInvokePayload(name="test_tool", result="A" * 500)
        gc = GlobalContext(request_id="req-1", user=None, tenant_id="t1", server_id="gw1")
        context = PluginContext(global_context=gc)
        result = asyncio.run(plugin.tool_post_invoke(payload, context))
        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "OUTPUT_LENGTH_VIOLATION"
