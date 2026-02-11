# -*- coding: utf-8 -*-
"""Tests for siem_export_service."""

# Standard
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
