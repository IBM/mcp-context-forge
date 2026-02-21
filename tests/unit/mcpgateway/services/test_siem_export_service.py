# -*- coding: utf-8 -*-
"""Tests for siem_export_service."""

# Standard
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.siem_export_service import (
    SIEMBatchProcessor,
    SplunkHECExporter,
    ElasticsearchExporter,
    WebhookExporter,
    create_siem_service,
)


class FakeRecord:
    """Minimal stand-in for PolicyDecision with serialization methods."""

    def __init__(self, record_id="test-1"):
        self.id = record_id

    def to_splunk_hec(self):
        return {"time": 0, "host": "test", "source": "test", "sourcetype": "test", "event": {}}

    def to_elasticsearch(self):
        return {"@timestamp": "2026-01-01T00:00:00", "id": self.id}

    def to_webhook(self):
        return {"event_type": "policy.decision", "timestamp": "2026-01-01T00:00:00", "data": {}}


class FakeSettings:
    """Minimal settings object for create_siem_service."""

    def __init__(self, **kwargs):
        self.siem_enabled = kwargs.get("siem_enabled", True)
        self.siem_type = kwargs.get("siem_type", "splunk")
        self.siem_endpoint = kwargs.get("siem_endpoint", "https://splunk:8088/services/collector")
        self.siem_token_env = kwargs.get("siem_token_env", "SIEM_TOKEN")
        self.siem_batch_size = kwargs.get("siem_batch_size", 100)
        self.siem_max_queue_size = kwargs.get("siem_max_queue_size", 10000)
        self.siem_flush_interval_seconds = kwargs.get("siem_flush_interval_seconds", 5)
        self.siem_timeout_seconds = kwargs.get("siem_timeout_seconds", 30)
        self.siem_retry_attempts = kwargs.get("siem_retry_attempts", 3)


def test_create_siem_service_disabled():
    """Returns None when SIEM is disabled."""
    settings = FakeSettings(siem_enabled=False)
    assert create_siem_service(settings) is None


def test_create_siem_service_no_endpoint():
    """Returns None when no endpoint is configured."""
    settings = FakeSettings(siem_endpoint="")
    assert create_siem_service(settings) is None


def test_create_siem_service_splunk():
    """Creates SplunkHECExporter for 'splunk' type."""
    settings = FakeSettings(siem_type="splunk")
    processor = create_siem_service(settings)
    assert processor is not None
    assert isinstance(processor.exporter, SplunkHECExporter)


def test_create_siem_service_elasticsearch():
    """Creates ElasticsearchExporter for 'elasticsearch' type."""
    settings = FakeSettings(siem_type="elasticsearch")
    processor = create_siem_service(settings)
    assert processor is not None
    assert isinstance(processor.exporter, ElasticsearchExporter)


def test_create_siem_service_webhook():
    """Creates WebhookExporter for 'webhook' type."""
    settings = FakeSettings(siem_type="webhook")
    processor = create_siem_service(settings)
    assert processor is not None
    assert isinstance(processor.exporter, WebhookExporter)


def test_create_siem_service_applies_max_queue_size():
    """Propagates max queue size into batch processor."""
    settings = FakeSettings(siem_type="webhook", siem_max_queue_size=77)
    processor = create_siem_service(settings)
    assert processor is not None
    assert processor.max_queue_size == 77


def test_create_siem_service_unknown_type():
    """Returns None for unknown SIEM type."""
    settings = FakeSettings(siem_type="unknown")
    assert create_siem_service(settings) is None


@pytest.mark.asyncio
async def test_batch_processor_flush_threshold():
    """Flush is triggered when queue reaches batch_size."""
    mock_exporter = AsyncMock()
    mock_exporter.send_batch = AsyncMock(return_value=True)

    processor = SIEMBatchProcessor(exporter=mock_exporter, batch_size=2, flush_interval_seconds=300)

    await processor.add(FakeRecord("r1"))
    mock_exporter.send_batch.assert_not_called()

    await processor.add(FakeRecord("r2"))
    mock_exporter.send_batch.assert_called_once()
    assert len(mock_exporter.send_batch.call_args[0][0]) == 2


@pytest.mark.asyncio
async def test_batch_processor_requeue_on_failure():
    """Failed records are re-queued."""
    mock_exporter = AsyncMock()
    mock_exporter.send_batch = AsyncMock(return_value=False)
    mock_exporter.close = AsyncMock()

    processor = SIEMBatchProcessor(exporter=mock_exporter, batch_size=1, flush_interval_seconds=300)

    await processor.add(FakeRecord("r1"))
    # The batch failed, records should be back in the queue
    assert len(processor.queue) == 1


@pytest.mark.asyncio
async def test_batch_processor_stop_flushes():
    """Stop flushes remaining records and closes exporter."""
    mock_exporter = AsyncMock()
    mock_exporter.send_batch = AsyncMock(return_value=True)
    mock_exporter.close = AsyncMock()

    processor = SIEMBatchProcessor(exporter=mock_exporter, batch_size=100, flush_interval_seconds=300)
    processor.queue.append(FakeRecord("r1"))

    await processor.stop()
    mock_exporter.send_batch.assert_called_once()
    mock_exporter.close.assert_called_once()


@pytest.mark.asyncio
async def test_batch_processor_stop_flushes_all_queued_batches():
    """Stop drains the full queue, including multiple batches."""
    mock_exporter = AsyncMock()
    mock_exporter.send_batch = AsyncMock(return_value=True)
    mock_exporter.close = AsyncMock()

    processor = SIEMBatchProcessor(exporter=mock_exporter, batch_size=2, flush_interval_seconds=300)
    processor.queue.extend([FakeRecord("r1"), FakeRecord("r2"), FakeRecord("r3"), FakeRecord("r4"), FakeRecord("r5")])

    await processor.stop()

    assert mock_exporter.send_batch.call_count == 3
    sent_batch_sizes = [len(call.args[0]) for call in mock_exporter.send_batch.call_args_list]
    assert sent_batch_sizes == [2, 2, 1]
    assert len(processor.queue) == 0
    mock_exporter.close.assert_called_once()


@pytest.mark.asyncio
async def test_batch_processor_stop_does_not_hang_when_flush_fails():
    """Stop exits if flush cannot make progress."""
    mock_exporter = AsyncMock()
    mock_exporter.send_batch = AsyncMock(return_value=False)
    mock_exporter.close = AsyncMock()

    processor = SIEMBatchProcessor(exporter=mock_exporter, batch_size=2, flush_interval_seconds=300)
    processor.queue.extend([FakeRecord("r1"), FakeRecord("r2"), FakeRecord("r3")])

    await processor.stop()

    # One failed attempt, then shutdown exits via no-progress guard.
    mock_exporter.send_batch.assert_called_once()
    assert len(processor.queue) == 3
    mock_exporter.close.assert_called_once()


@pytest.mark.asyncio
async def test_batch_processor_drops_oldest_when_queue_is_full():
    """Queue size is bounded and oldest records are dropped when full."""
    mock_exporter = AsyncMock()
    mock_exporter.send_batch = AsyncMock(return_value=False)

    processor = SIEMBatchProcessor(exporter=mock_exporter, batch_size=100, flush_interval_seconds=300, max_queue_size=3)

    await processor.add(FakeRecord("r1"))
    await processor.add(FakeRecord("r2"))
    await processor.add(FakeRecord("r3"))
    await processor.add(FakeRecord("r4"))

    assert len(processor.queue) == 3
    assert [record.id for record in processor.queue] == ["r2", "r3", "r4"]


@pytest.mark.asyncio
async def test_splunk_send_batch_with_zero_retries_still_attempts_once():
    """retry_attempts=0 still performs the initial send attempt."""

    class DummyResponse:
        def __init__(self, status: int):
            self.status = status

        async def text(self):
            return "error"

    class DummyRequestContextManager:
        def __init__(self, response):
            self.response = response

        async def __aenter__(self):
            return self.response

        async def __aexit__(self, exc_type, exc, tb):
            return False

    exporter = SplunkHECExporter(endpoint="https://splunk.example/services/collector", token_env="SIEM_TOKEN", timeout_seconds=1, retry_attempts=0)
    mock_session = MagicMock()
    mock_session.post.return_value = DummyRequestContextManager(DummyResponse(500))
    exporter._get_session = AsyncMock(return_value=mock_session)

    success = await exporter.send_batch([FakeRecord("r1")])

    assert success is False
    mock_session.post.assert_called_once()


@pytest.mark.asyncio
async def test_batch_processor_stop_waits_for_in_flight_flush():
    """Stop waits for in-flight periodic flush to complete."""
    mock_exporter = AsyncMock()
    mock_exporter.close = AsyncMock()
    send_started = asyncio.Event()
    allow_send_to_finish = asyncio.Event()

    async def slow_send(_batch):
        send_started.set()
        await allow_send_to_finish.wait()
        return True

    mock_exporter.send_batch = AsyncMock(side_effect=slow_send)
    processor = SIEMBatchProcessor(exporter=mock_exporter, batch_size=100, flush_interval_seconds=0.01)
    processor.queue.append(FakeRecord("r1"))

    await processor.start()
    await asyncio.wait_for(send_started.wait(), timeout=1)

    stop_task = asyncio.create_task(processor.stop())
    await asyncio.sleep(0)
    assert not stop_task.done()

    allow_send_to_finish.set()
    await asyncio.wait_for(stop_task, timeout=1)

    assert len(processor.queue) == 0
    mock_exporter.send_batch.assert_called_once()
    mock_exporter.close.assert_called_once()
