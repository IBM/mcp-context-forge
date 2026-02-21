# -*- coding: utf-8 -*-
"""Tests for the metrics buffer service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.metrics_buffer_service import MetricsBufferService


class TestMetricsBufferServiceInit:
    """Tests for MetricsBufferService initialization."""

    def test_init_defaults(self):
        """Test service initialization with defaults."""
        service = MetricsBufferService()

        assert service.enabled is True
        assert service.recording_enabled is not None
        assert service.flush_interval == 60
        assert service.max_buffer_size == 1000

    def test_init_custom_values(self):
        """Test service initialization with custom values."""
        service = MetricsBufferService(
            flush_interval=30,
            max_buffer_size=500,
            enabled=False,
        )

        assert service.enabled is False
        assert service.flush_interval == 30
        assert service.max_buffer_size == 500


class TestDbMetricsRecordingEnabled:
    @pytest.fixture(autouse=True)
    def enable_recording(self, monkeypatch):
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "db_metrics_recording_enabled", True)

    """Tests for DB_METRICS_RECORDING_ENABLED switch."""

    def test_recording_disabled_skips_tool_metric(self):
        """When recording_enabled=False, record_tool_metric is a no-op."""
        service = MetricsBufferService(enabled=True)
        service.recording_enabled = False

        service.record_tool_metric(
            tool_id="test-id",
            start_time=time.monotonic(),
            success=True,
        )

        # Buffer should remain empty
        assert len(service._tool_metrics) == 0

    def test_recording_disabled_skips_resource_metric(self):
        """When recording_enabled=False, record_resource_metric is a no-op."""
        service = MetricsBufferService(enabled=True)
        service.recording_enabled = False

        service.record_resource_metric(
            resource_id="test-id",
            start_time=time.monotonic(),
            success=True,
        )

        assert len(service._resource_metrics) == 0

    def test_recording_disabled_skips_prompt_metric(self):
        """When recording_enabled=False, record_prompt_metric is a no-op."""
        service = MetricsBufferService(enabled=True)
        service.recording_enabled = False

        service.record_prompt_metric(
            prompt_id="test-id",
            start_time=time.monotonic(),
            success=True,
        )

        assert len(service._prompt_metrics) == 0

    def test_recording_disabled_skips_server_metric(self):
        """When recording_enabled=False, record_server_metric is a no-op."""
        service = MetricsBufferService(enabled=True)
        service.recording_enabled = False

        service.record_server_metric(
            server_id="test-id",
            start_time=time.monotonic(),
            success=True,
        )

        assert len(service._server_metrics) == 0

    def test_recording_disabled_skips_a2a_metric(self):
        """When recording_enabled=False, record_a2a_agent_metric is a no-op."""
        service = MetricsBufferService(enabled=True)
        service.recording_enabled = False

        service.record_a2a_agent_metric(
            a2a_agent_id="test-id",
            start_time=time.monotonic(),
            success=True,
        )

        assert len(service._a2a_agent_metrics) == 0

    def test_recording_disabled_skips_a2a_metric_with_duration(self):
        """When recording_enabled=False, record_a2a_agent_metric_with_duration is a no-op."""
        service = MetricsBufferService(enabled=True)
        service.recording_enabled = False

        service.record_a2a_agent_metric_with_duration(
            a2a_agent_id="test-id",
            response_time=0.5,
            success=True,
        )

        assert len(service._a2a_agent_metrics) == 0

    def test_recording_disabled_immediate_write_skipped(self):
        """When recording_enabled=False and buffer disabled, immediate writes are also skipped."""
        service = MetricsBufferService(enabled=False)  # Buffer disabled = immediate writes
        service.recording_enabled = False

        # This would normally trigger immediate DB write, but should be skipped
        service.record_tool_metric(
            tool_id="test-id",
            start_time=time.monotonic(),
            success=True,
        )

        # No exception, no write attempted
        assert len(service._tool_metrics) == 0

    def test_recording_enabled_records_normally(self):
        """When recording_enabled=True (default), metrics are recorded."""
        service = MetricsBufferService(enabled=True)
        # recording_enabled defaults to True

        service.record_tool_metric(
            tool_id="test-id",
            start_time=time.monotonic(),
            success=True,
        )

        assert len(service._tool_metrics) == 1

    def test_get_stats_includes_recording_enabled(self):
        """get_stats() includes recording_enabled status."""
        service = MetricsBufferService(enabled=True)
        stats = service.get_stats()

        assert "recording_enabled" in stats
        assert stats["recording_enabled"] is True

    @pytest.mark.asyncio
    async def test_start_skipped_when_recording_disabled(self):
        """When recording_enabled=False, start() does not create flush task."""
        service = MetricsBufferService(enabled=True)
        service.recording_enabled = False

        await service.start()

        # Flush task should not be created
        assert service._flush_task is None

    @pytest.mark.asyncio
    async def test_start_skipped_when_buffer_disabled(self):
        """When buffering is disabled, start() should not create flush task."""
        service = MetricsBufferService(enabled=False)
        service.recording_enabled = True

        await service.start()

        assert service._flush_task is None


class TestImmediateWritesWhenDisabled:
    @pytest.fixture(autouse=True)
    def enable_recording(self, monkeypatch):
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "db_metrics_recording_enabled", True)

    """Tests for immediate write fallbacks when buffering is disabled."""

    def test_resource_metric_immediate_write_called(self):
        """record_resource_metric should call immediate write when disabled."""
        service = MetricsBufferService(enabled=False)

        with patch.object(service, "_write_resource_metric_immediately") as mock_write:
            service.record_resource_metric("res-1", time.monotonic(), True, None)

        mock_write.assert_called_once()

    def test_prompt_metric_immediate_write_called(self):
        """record_prompt_metric should call immediate write when disabled."""
        service = MetricsBufferService(enabled=False)

        with patch.object(service, "_write_prompt_metric_immediately") as mock_write:
            service.record_prompt_metric("prompt-1", time.monotonic(), True, None)

        mock_write.assert_called_once()

    def test_server_metric_immediate_write_called(self):
        """record_server_metric should call immediate write when disabled."""
        service = MetricsBufferService(enabled=False)

        with patch.object(service, "_write_server_metric_immediately") as mock_write:
            service.record_server_metric("server-1", time.monotonic(), True, None)

        mock_write.assert_called_once()

    def test_a2a_metric_immediate_write_called(self):
        """record_a2a_agent_metric should call immediate write when disabled."""
        service = MetricsBufferService(enabled=False)

        with patch.object(service, "_write_a2a_agent_metric_immediately") as mock_write:
            service.record_a2a_agent_metric("agent-1", time.monotonic(), True, interaction_type="invoke")

        mock_write.assert_called_once()

    def test_a2a_metric_with_duration_immediate_write(self, monkeypatch):
        """Immediate write with duration should persist metric via DB session."""
        # First-Party
        from mcpgateway.db import A2AAgentMetric

        service = MetricsBufferService(enabled=False)

        class DummySession:
            def __init__(self):
                self.added = None
                self.committed = False

            def add(self, obj):
                self.added = obj

            def commit(self):
                self.committed = True

        class DummyContext:
            def __init__(self, session):
                self._session = session

            def __enter__(self):
                return self._session

            def __exit__(self, exc_type, exc, tb):
                return False

        dummy_session = DummySession()

        monkeypatch.setattr("mcpgateway.services.metrics_buffer_service.fresh_db_session", lambda: DummyContext(dummy_session))

        service.record_a2a_agent_metric_with_duration(
            a2a_agent_id="agent-1",
            response_time=1.25,
            success=True,
            interaction_type="invoke",
        )

        assert isinstance(dummy_session.added, A2AAgentMetric)
        assert dummy_session.committed is True

    def test_a2a_metric_with_duration_immediate_write_error_is_swallowed(self, monkeypatch):
        service = MetricsBufferService(enabled=False)

        def _raise():
            raise RuntimeError("boom")

        monkeypatch.setattr("mcpgateway.services.metrics_buffer_service.fresh_db_session", _raise)

        # Should not raise.
        service._write_a2a_agent_metric_with_duration_immediately(
            a2a_agent_id="agent-1",
            response_time=1.25,
            success=True,
            interaction_type="invoke",
            error_message=None,
        )


class TestMetricsBufferServiceRecording:
    @pytest.fixture(autouse=True)
    def enable_recording(self, monkeypatch):
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "db_metrics_recording_enabled", True)

    """Tests for normal metrics recording."""

    def test_record_tool_metric_with_error(self):
        """Test recording a failed tool metric."""
        service = MetricsBufferService(enabled=True)

        service.record_tool_metric(
            tool_id="test-id",
            start_time=time.monotonic() - 0.5,  # 500ms ago
            success=False,
            error_message="Something went wrong",
        )

        assert len(service._tool_metrics) == 1
        metric = service._tool_metrics[0]
        assert metric.tool_id == "test-id"
        assert metric.is_success is False
        assert metric.error_message == "Something went wrong"
        assert metric.response_time >= 0.5

    def test_record_a2a_metric_with_interaction_type(self):
        """Test recording an A2A metric with custom interaction type."""
        service = MetricsBufferService(enabled=True)

        service.record_a2a_agent_metric(
            a2a_agent_id="agent-123",
            start_time=time.monotonic(),
            success=True,
            interaction_type="stream",
        )

        assert len(service._a2a_agent_metrics) == 1
        metric = service._a2a_agent_metrics[0]
        assert metric.a2a_agent_id == "agent-123"
        assert metric.interaction_type == "stream"

    def test_record_server_metric_buffers_when_enabled(self):
        service = MetricsBufferService(enabled=True)

        service.record_server_metric(
            server_id="server-123",
            start_time=time.monotonic() - 0.25,
            success=True,
        )

        assert len(service._server_metrics) == 1
        metric = service._server_metrics[0]
        assert metric.server_id == "server-123"
        assert metric.is_success is True
        assert metric.response_time >= 0.25

    def test_record_a2a_agent_metric_with_duration_buffers_when_enabled(self):
        service = MetricsBufferService(enabled=True)

        service.record_a2a_agent_metric_with_duration(
            a2a_agent_id="agent-123",
            response_time=1.25,
            success=False,
            interaction_type="invoke",
            error_message="boom",
        )

        assert len(service._a2a_agent_metrics) == 1
        metric = service._a2a_agent_metrics[0]
        assert metric.a2a_agent_id == "agent-123"
        assert metric.response_time == 1.25
        assert metric.is_success is False
        assert metric.error_message == "boom"

    def test_multiple_metrics_buffered(self):
        """Test that multiple metrics are buffered correctly."""
        service = MetricsBufferService(enabled=True)

        for i in range(5):
            service.record_tool_metric(
                tool_id=f"tool-{i}",
                start_time=time.monotonic(),
                success=True,
            )

        assert len(service._tool_metrics) == 5
        assert service._total_buffered == 5


@pytest.mark.asyncio
async def test_start_creates_flush_task(monkeypatch):
    service = MetricsBufferService(enabled=True)
    service.recording_enabled = True
    service._flush_loop = AsyncMock()

    created = {}

    def _fake_create_task(coro):
        created["coro"] = coro
        task = MagicMock()
        task.done.return_value = False
        return task

    monkeypatch.setattr(asyncio, "create_task", _fake_create_task)
    await service.start()

    assert service._flush_task is not None
    assert created["coro"] is not None
    created["coro"].close()


@pytest.mark.asyncio
async def test_shutdown_cancels_and_flushes(monkeypatch):
    service = MetricsBufferService(enabled=True)

    class DummyTask:
        def __init__(self):
            self.cancel_called = False

        def cancel(self):
            self.cancel_called = True

        def __await__(self):
            async def _noop():
                return None

            return _noop().__await__()

    task = DummyTask()
    service._flush_task = task
    service._flush_all = AsyncMock()

    await service.shutdown()

    assert task.cancel_called is True
    service._flush_all.assert_awaited()


@pytest.mark.asyncio
async def test_shutdown_flushes_without_task():
    service = MetricsBufferService(enabled=True)
    service._flush_all = AsyncMock()

    await service.shutdown()

    service._flush_all.assert_awaited()


@pytest.mark.asyncio
async def test_flush_loop_breaks_on_shutdown_signal(monkeypatch):
    service = MetricsBufferService(enabled=True, flush_interval=1)

    async def fake_wait_for(awaitable, timeout=None):
        service._shutdown_event.set()
        return await awaitable

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(service, "_flush_all", AsyncMock())

    await service._flush_loop()


@pytest.mark.asyncio
async def test_flush_loop_timeout_triggers_flush(monkeypatch):
    service = MetricsBufferService(enabled=True, flush_interval=1)
    flush_all = AsyncMock()

    async def fake_wait_for(awaitable, timeout=None):
        if hasattr(awaitable, "close"):
            awaitable.close()
        service._shutdown_event.set()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(service, "_flush_all", flush_all)

    await service._flush_loop()
    flush_all.assert_awaited()


@pytest.mark.asyncio
async def test_flush_loop_error_sleeps_and_continues(monkeypatch):
    service = MetricsBufferService(enabled=True, flush_interval=1)

    async def fake_wait_for(awaitable, timeout=None):
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise asyncio.TimeoutError()

    async def fake_sleep(_secs):
        service._shutdown_event.set()

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(service, "_flush_all", AsyncMock(side_effect=RuntimeError("boom")))

    await service._flush_loop()


@pytest.mark.asyncio
async def test_flush_all_batches_metrics(monkeypatch):
    from mcpgateway.config import settings

    monkeypatch.setattr(settings, "db_metrics_recording_enabled", True)
    service = MetricsBufferService(enabled=True)

    service.record_tool_metric("tool-1", start_time=time.monotonic() - 0.1, success=True)
    service.record_resource_metric("resource-1", start_time=time.monotonic() - 0.2, success=False)

    captured = {}

    async def _fake_to_thread(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    await service._flush_all()

    assert service._total_flushed == 2
    assert service._flush_count == 1
    assert captured["func"] == service._flush_to_db


def test_flush_to_db_writes_batches(monkeypatch):
    service = MetricsBufferService(enabled=True)

    holder = {}

    class DummyDB:
        def __init__(self):
            self.bulk_calls = []
            self.committed = False

        def bulk_insert_mappings(self, model, payload):
            self.bulk_calls.append((model, payload))

        def commit(self):
            self.committed = True

    class DummySession:
        def __enter__(self):
            holder["db"] = DummyDB()
            return holder["db"]

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("mcpgateway.services.metrics_buffer_service.fresh_db_session", lambda: DummySession())

    tool_metric = SimpleNamespace(tool_id="t1", timestamp=time.time(), response_time=0.1, is_success=True, error_message=None)
    resource_metric = SimpleNamespace(resource_id="r1", timestamp=time.time(), response_time=0.2, is_success=False, error_message="err")

    service._flush_to_db([tool_metric], [resource_metric], [], [], [])
    assert holder["db"].committed is True
    assert holder["db"].bulk_calls


def test_flush_to_db_writes_all_metric_types(monkeypatch):
    # First-Party
    from mcpgateway.db import A2AAgentMetric, PromptMetric, ResourceMetric, ServerMetric, ToolMetric

    service = MetricsBufferService(enabled=True)

    holder = {}

    class DummyDB:
        def __init__(self):
            self.bulk_calls = []
            self.committed = False

        def bulk_insert_mappings(self, model, payload):
            self.bulk_calls.append((model, payload))

        def commit(self):
            self.committed = True

    class DummySession:
        def __enter__(self):
            holder["db"] = DummyDB()
            return holder["db"]

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("mcpgateway.services.metrics_buffer_service.fresh_db_session", lambda: DummySession())

    tool_metric = SimpleNamespace(tool_id="t1", timestamp=time.time(), response_time=0.1, is_success=True, error_message=None)
    resource_metric = SimpleNamespace(resource_id="r1", timestamp=time.time(), response_time=0.2, is_success=False, error_message="err")
    prompt_metric = SimpleNamespace(prompt_id="p1", timestamp=time.time(), response_time=0.3, is_success=True, error_message=None)
    server_metric = SimpleNamespace(server_id="s1", timestamp=time.time(), response_time=0.4, is_success=True, error_message=None)
    a2a_metric = SimpleNamespace(a2a_agent_id="a1", timestamp=time.time(), response_time=0.5, is_success=True, interaction_type="invoke", error_message=None)

    service._flush_to_db([tool_metric], [resource_metric], [prompt_metric], [server_metric], [a2a_metric])

    assert holder["db"].committed is True
    models = [call[0] for call in holder["db"].bulk_calls]
    assert ToolMetric in models
    assert ResourceMetric in models
    assert PromptMetric in models
    assert ServerMetric in models
    assert A2AAgentMetric in models


def test_record_tool_metric_falls_back_to_immediate_write(monkeypatch):
    service = MetricsBufferService(enabled=False)
    service.recording_enabled = True
    service._write_tool_metric_immediately = MagicMock()

    service.record_tool_metric("tool-1", start_time=time.monotonic(), success=True)

    service._write_tool_metric_immediately.assert_called_once()


def test_get_metrics_buffer_service_singleton(monkeypatch):
    from mcpgateway.services import metrics_buffer_service as mbs

    mbs._metrics_buffer_service = None
    first = mbs.get_metrics_buffer_service()
    second = mbs.get_metrics_buffer_service()
    assert first is second


class TestMetricsSetup:
    """Tests for Prometheus metrics setup."""

    @pytest.mark.parametrize(
        "db_url, expected_engine",
        [
            ("mysql+pymysql://user@host/db", "mariadb"),
            ("postgresql://user@host/db", "postgresql"),
            ("mongodb://user@host/db", "mongodb"),
            ("oracle://user@host/db", "unknown"),
        ],
    )
    def test_setup_metrics_db_engine_detection(self, monkeypatch, db_url, expected_engine):
        """Database engine detection should map URLs to expected labels."""
        # Third-Party
        from fastapi import FastAPI

        # First-Party
        from mcpgateway.services import metrics as metrics_module

        created_gauges = []

        class DummyGauge:
            def __init__(self, name, _doc, labelnames=None, registry=None):  # noqa: ARG002
                self.name = name
                self.labelnames = labelnames or []
                self.labels_kwargs = None
                created_gauges.append(self)

            def labels(self, **kwargs):
                self.labels_kwargs = kwargs
                return self

            def set(self, _value):
                return None

        class DummyInstrumentator:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def instrument(self, _app):
                return self

            def expose(self, _app, **_kwargs):
                return None

        app = FastAPI()
        monkeypatch.setenv("ENABLE_METRICS", "true")
        monkeypatch.setenv("METRICS_CUSTOM_LABELS", "")
        monkeypatch.setattr(metrics_module.settings, "database_url", db_url)
        monkeypatch.setattr(metrics_module.settings, "METRICS_EXCLUDED_HANDLERS", "")
        monkeypatch.setattr(metrics_module, "Gauge", DummyGauge)
        monkeypatch.setattr(metrics_module, "Instrumentator", DummyInstrumentator)
        # Force fresh collector creation regardless of global REGISTRY state from
        # previously imported modules/tests (e.g., mcpgateway.main startup).
        monkeypatch.setattr(metrics_module, "_get_registry_collector", lambda _name: None)

        metrics_module.setup_metrics(app)

        db_gauge = next(g for g in created_gauges if g.name == "database_info")
        assert db_gauge.labels_kwargs["engine"] == expected_engine

    @pytest.mark.asyncio
    async def test_setup_metrics_disabled_registers_endpoint(self, monkeypatch):
        """Disabled metrics should add a 503 metrics endpoint."""
        # Third-Party
        from fastapi import FastAPI

        # First-Party
        from mcpgateway.services import metrics as metrics_module

        app = FastAPI()
        monkeypatch.setenv("ENABLE_METRICS", "false")

        metrics_module.setup_metrics(app)

        route = next(r for r in app.routes if getattr(r, "path", "") == "/metrics/prometheus")
        response = await route.endpoint()

        assert response.status_code == 503
        assert b"Metrics collection is disabled" in response.body

    def test_update_http_pool_metrics_handles_exceptions(self, monkeypatch):
        """update_http_pool_metrics should swallow errors from SharedHttpClient."""
        # Third-Party
        from fastapi import FastAPI

        # First-Party
        from mcpgateway.services import metrics as metrics_module
        from mcpgateway.services import http_client_service

        class DummyGauge:
            def __init__(self, _name, _doc, labelnames=None, registry=None):  # noqa: ARG002
                self.labels_kwargs = None

            def labels(self, **_kwargs):
                return self

            def set(self, _value):
                return None

        class DummyInstrumentator:
            def __init__(self, **_kwargs):
                pass

            def instrument(self, _app):
                return self

            def expose(self, _app, **_kwargs):
                return None

        app = FastAPI()
        monkeypatch.setenv("ENABLE_METRICS", "true")
        monkeypatch.setattr(metrics_module.settings, "database_url", "sqlite:///./test.db")
        monkeypatch.setattr(metrics_module.settings, "METRICS_EXCLUDED_HANDLERS", "")
        monkeypatch.setattr(metrics_module, "Gauge", DummyGauge)
        monkeypatch.setattr(metrics_module, "Instrumentator", DummyInstrumentator)

        metrics_module.setup_metrics(app)

        http_client_service.SharedHttpClient._instance = SimpleNamespace(_initialized=True, get_pool_stats=MagicMock(side_effect=RuntimeError("boom")))

        app.state.update_http_pool_metrics()


# --------------------------------------------------------------------------- #
# Coverage: _write_*_immediately methods (lines 560-738)                       #
# --------------------------------------------------------------------------- #
class TestImmediateWriteMethods:
    """Tests for all _write_*_immediately methods with actual DB mock."""

    def _make_session_context(self):
        """Create a mock fresh_db_session context manager."""
        mock_db = MagicMock()

        class Ctx:
            def __enter__(self_inner):
                return mock_db

            def __exit__(self_inner, *args):
                return False

        return Ctx(), mock_db

    def test_write_tool_metric_immediately_success(self, monkeypatch):
        ctx, mock_db = self._make_session_context()
        monkeypatch.setattr("mcpgateway.services.metrics_buffer_service.fresh_db_session", lambda: ctx)
        service = MetricsBufferService(enabled=False)
        service._write_tool_metric_immediately("t1", time.monotonic(), True, None)
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_write_tool_metric_immediately_error(self, monkeypatch):
        monkeypatch.setattr(
            "mcpgateway.services.metrics_buffer_service.fresh_db_session",
            MagicMock(side_effect=Exception("db error")),
        )
        service = MetricsBufferService(enabled=False)
        service._write_tool_metric_immediately("t1", time.monotonic(), False, "err")
        # Should not raise

    def test_write_resource_metric_immediately_success(self, monkeypatch):
        ctx, mock_db = self._make_session_context()
        monkeypatch.setattr("mcpgateway.services.metrics_buffer_service.fresh_db_session", lambda: ctx)
        service = MetricsBufferService(enabled=False)
        service._write_resource_metric_immediately("r1", time.monotonic(), True, None)
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_write_prompt_metric_immediately_success(self, monkeypatch):
        ctx, mock_db = self._make_session_context()
        monkeypatch.setattr("mcpgateway.services.metrics_buffer_service.fresh_db_session", lambda: ctx)
        service = MetricsBufferService(enabled=False)
        service._write_prompt_metric_immediately("p1", time.monotonic(), True, None)
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_write_server_metric_immediately_success(self, monkeypatch):
        ctx, mock_db = self._make_session_context()
        monkeypatch.setattr("mcpgateway.services.metrics_buffer_service.fresh_db_session", lambda: ctx)
        service = MetricsBufferService(enabled=False)
        service._write_server_metric_immediately("s1", time.monotonic(), True, None)
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_write_a2a_metric_immediately_success(self, monkeypatch):
        ctx, mock_db = self._make_session_context()
        monkeypatch.setattr("mcpgateway.services.metrics_buffer_service.fresh_db_session", lambda: ctx)
        service = MetricsBufferService(enabled=False)
        service._write_a2a_agent_metric_immediately("a1", time.monotonic(), True, "invoke", None)
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_write_a2a_metric_with_duration_immediately_success(self, monkeypatch):
        ctx, mock_db = self._make_session_context()
        monkeypatch.setattr("mcpgateway.services.metrics_buffer_service.fresh_db_session", lambda: ctx)
        service = MetricsBufferService(enabled=False)
        service._write_a2a_agent_metric_with_duration_immediately("a1", 1.5, True, "invoke", None)
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_write_resource_metric_immediately_error(self, monkeypatch):
        monkeypatch.setattr(
            "mcpgateway.services.metrics_buffer_service.fresh_db_session",
            MagicMock(side_effect=Exception("db error")),
        )
        service = MetricsBufferService(enabled=False)
        service._write_resource_metric_immediately("r1", time.monotonic(), False, "err")

    def test_write_prompt_metric_immediately_error(self, monkeypatch):
        monkeypatch.setattr(
            "mcpgateway.services.metrics_buffer_service.fresh_db_session",
            MagicMock(side_effect=Exception("db error")),
        )
        service = MetricsBufferService(enabled=False)
        service._write_prompt_metric_immediately("p1", time.monotonic(), False, "err")

    def test_write_server_metric_immediately_error(self, monkeypatch):
        monkeypatch.setattr(
            "mcpgateway.services.metrics_buffer_service.fresh_db_session",
            MagicMock(side_effect=Exception("db error")),
        )
        service = MetricsBufferService(enabled=False)
        service._write_server_metric_immediately("s1", time.monotonic(), False, "err")

    def test_write_a2a_metric_immediately_error(self, monkeypatch):
        monkeypatch.setattr(
            "mcpgateway.services.metrics_buffer_service.fresh_db_session",
            MagicMock(side_effect=Exception("db error")),
        )
        service = MetricsBufferService(enabled=False)
        service._write_a2a_agent_metric_immediately("a1", time.monotonic(), False, "invoke", "err")
