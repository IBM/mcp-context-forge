# -*- coding: utf-8 -*-
"""Tests for siem_export_service."""

# Standard
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services import siem_export_service as siem_mod
from mcpgateway.services.siem_export_service import (
    ElasticsearchExporter,
    SIEMBatchProcessor,
    SplunkHECExporter,
    WebhookExporter,
    create_siem_service,
)


class FakePolicyDecision:
    """Minimal stand-in for PolicyDecision ORM object."""

    def __init__(self, id="dec-1"):
        self.id = id

    def to_splunk_hec(self):
        return {"time": 1700000000, "host": "gw-1", "source": "mcp", "sourcetype": "pd", "event": {"id": self.id}}

    def to_elasticsearch(self):
        return {"id": self.id, "@timestamp": "2026-01-01T00:00:00", "event_type": "policy_decision"}

    def to_webhook(self):
        return {"event_type": "policy.decision", "timestamp": "2026-01-01T00:00:00", "data": {"id": self.id}}


class FakeSettings:
    """Fake settings object for create_siem_service factory tests."""

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


# Alias for tests that use FakeRecord as a minimal policy decision stand-in
FakeRecord = FakePolicyDecision


class FakeResponse:
    """Fake aiohttp response."""

    def __init__(self, status, text="", json_data=None):
        self.status = status
        self._text = text
        self._json = json_data

    async def text(self):
        return self._text

    async def json(self):
        return self._json

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class FakeSession:
    """Fake aiohttp session."""

    def __init__(self, response):
        self._response = response
        self.closed = False

    def post(self, url, **kwargs):
        return self._response

    def put(self, url, **kwargs):
        return self._response

    def get(self, url, **kwargs):
        return self._response

    def head(self, url, **kwargs):
        return self._response

    async def close(self):
        self.closed = True


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


# --- SplunkHECExporter tests ---


@pytest.mark.asyncio
async def test_splunk_send_single_delegates_to_batch():
    """send() delegates to send_batch()."""
    exporter = SplunkHECExporter("http://splunk:8088/services/collector", "SPLUNK_TOKEN", 10, 1)
    exporter.send_batch = AsyncMock(return_value=True)
    record = FakePolicyDecision()
    result = await exporter.send(record)
    assert result is True
    exporter.send_batch.assert_called_once_with([record])


@pytest.mark.asyncio
async def test_splunk_send_batch_success():
    """send_batch returns True on 200."""
    exporter = SplunkHECExporter("http://splunk:8088/services/collector", "SPLUNK_TOKEN", 10, 1)
    fake_resp = FakeResponse(200)
    exporter.session = FakeSession(fake_resp)
    result = await exporter.send_batch([FakePolicyDecision()])
    assert result is True


@pytest.mark.asyncio
async def test_splunk_send_batch_empty():
    """send_batch returns True for empty list."""
    exporter = SplunkHECExporter("http://splunk:8088/services/collector", "SPLUNK_TOKEN", 10, 1)
    result = await exporter.send_batch([])
    assert result is True


@pytest.mark.asyncio
async def test_splunk_send_batch_auth_failure():
    """send_batch returns False on 403."""
    exporter = SplunkHECExporter("http://splunk:8088/services/collector", "SPLUNK_TOKEN", 10, 1)
    fake_resp = FakeResponse(403)
    exporter.session = FakeSession(fake_resp)
    result = await exporter.send_batch([FakePolicyDecision()])
    assert result is False


@pytest.mark.asyncio
async def test_splunk_send_batch_server_error():
    """send_batch returns False on non-200/403."""
    exporter = SplunkHECExporter("http://splunk:8088/services/collector", "SPLUNK_TOKEN", 10, 1)
    fake_resp = FakeResponse(500, text="server error")
    exporter.session = FakeSession(fake_resp)
    result = await exporter.send_batch([FakePolicyDecision()])
    assert result is False


@pytest.mark.asyncio
async def test_splunk_send_batch_exception_retries():
    """send_batch retries on exception."""
    exporter = SplunkHECExporter("http://splunk:8088/services/collector", "SPLUNK_TOKEN", 10, 2)
    call_count = 0

    class FailSession:
        closed = False

        def post(self, url, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ConnectionError("fail")

    exporter.session = FailSession()
    result = await exporter.send_batch([FakePolicyDecision()])
    assert result is False
    # retry_attempts=2 → total_attempts = max(1, 2+1) = 3
    assert call_count == 3


@pytest.mark.asyncio
async def test_splunk_health_check_success():
    """health_check returns True on 200."""
    exporter = SplunkHECExporter("http://splunk:8088/services/collector", "SPLUNK_TOKEN", 10, 1)
    fake_resp = FakeResponse(200)
    exporter.session = FakeSession(fake_resp)
    result = await exporter.health_check()
    assert result is True


@pytest.mark.asyncio
async def test_splunk_health_check_failure():
    """health_check returns False on exception."""
    exporter = SplunkHECExporter("http://splunk:8088/services/collector", "SPLUNK_TOKEN", 10, 1)

    class FailSession:
        closed = False

        def get(self, url, **kwargs):
            raise ConnectionError("fail")

    exporter.session = FailSession()
    result = await exporter.health_check()
    assert result is False


@pytest.mark.asyncio
async def test_splunk_close():
    """close() closes the session."""
    exporter = SplunkHECExporter("http://splunk:8088/services/collector", "SPLUNK_TOKEN", 10, 1)
    session = FakeSession(FakeResponse(200))
    exporter.session = session
    await exporter.close()
    assert session.closed is True


# --- ElasticsearchExporter tests ---


@pytest.mark.asyncio
async def test_es_send_success():
    """send single record to Elasticsearch returns True on 201."""
    exporter = ElasticsearchExporter("http://es:9200", "ES_TOKEN", 10, 1)
    fake_resp = FakeResponse(201)
    exporter.session = FakeSession(fake_resp)
    result = await exporter.send(FakePolicyDecision())
    assert result is True


@pytest.mark.asyncio
async def test_es_send_failure():
    """send returns False on error status."""
    exporter = ElasticsearchExporter("http://es:9200", "ES_TOKEN", 10, 1)
    fake_resp = FakeResponse(400, text="bad request")
    exporter.session = FakeSession(fake_resp)
    result = await exporter.send(FakePolicyDecision())
    assert result is False


@pytest.mark.asyncio
async def test_es_send_exception():
    """send returns False on exception."""
    exporter = ElasticsearchExporter("http://es:9200", "ES_TOKEN", 10, 1)

    class FailSession:
        closed = False

        def put(self, url, **kwargs):
            raise ConnectionError("fail")

    exporter.session = FailSession()
    result = await exporter.send(FakePolicyDecision())
    assert result is False


@pytest.mark.asyncio
async def test_es_send_batch_success():
    """send_batch returns True on 200 with no errors."""
    exporter = ElasticsearchExporter("http://es:9200", "ES_TOKEN", 10, 1)
    fake_resp = FakeResponse(200, json_data={"errors": False})
    exporter.session = FakeSession(fake_resp)
    result = await exporter.send_batch([FakePolicyDecision()])
    assert result is True


@pytest.mark.asyncio
async def test_es_send_batch_empty():
    """send_batch returns True for empty list."""
    exporter = ElasticsearchExporter("http://es:9200", "ES_TOKEN", 10, 1)
    result = await exporter.send_batch([])
    assert result is True


@pytest.mark.asyncio
async def test_es_send_batch_partial_errors():
    """send_batch returns False when some items failed."""
    exporter = ElasticsearchExporter("http://es:9200", "ES_TOKEN", 10, 1)
    fake_resp = FakeResponse(200, json_data={"errors": True})
    exporter.session = FakeSession(fake_resp)
    result = await exporter.send_batch([FakePolicyDecision()])
    assert result is False


@pytest.mark.asyncio
async def test_es_send_batch_server_error():
    """send_batch returns False on non-200."""
    exporter = ElasticsearchExporter("http://es:9200", "ES_TOKEN", 10, 1)
    fake_resp = FakeResponse(500, text="error")
    exporter.session = FakeSession(fake_resp)
    result = await exporter.send_batch([FakePolicyDecision()])
    assert result is False


@pytest.mark.asyncio
async def test_es_send_batch_exception():
    """send_batch returns False on exception."""
    exporter = ElasticsearchExporter("http://es:9200", "ES_TOKEN", 10, 1)

    class FailSession:
        closed = False

        def post(self, url, **kwargs):
            raise ConnectionError("fail")

    exporter.session = FailSession()
    result = await exporter.send_batch([FakePolicyDecision()])
    assert result is False


@pytest.mark.asyncio
async def test_es_health_check_success():
    """health_check returns True on 200."""
    exporter = ElasticsearchExporter("http://es:9200", "ES_TOKEN", 10, 1)
    fake_resp = FakeResponse(200)
    exporter.session = FakeSession(fake_resp)
    result = await exporter.health_check()
    assert result is True


@pytest.mark.asyncio
async def test_es_health_check_failure():
    """health_check returns False on exception."""
    exporter = ElasticsearchExporter("http://es:9200", "ES_TOKEN", 10, 1)

    class FailSession:
        closed = False

        def get(self, url, **kwargs):
            raise ConnectionError("fail")

    exporter.session = FailSession()
    result = await exporter.health_check()
    assert result is False


@pytest.mark.asyncio
async def test_es_close():
    """close() closes the session."""
    exporter = ElasticsearchExporter("http://es:9200", "ES_TOKEN", 10, 1)
    session = FakeSession(FakeResponse(200))
    exporter.session = session
    await exporter.close()
    assert session.closed is True


# --- WebhookExporter tests ---


@pytest.mark.asyncio
async def test_webhook_send_delegates_to_batch():
    """send() delegates to send_batch()."""
    exporter = WebhookExporter("http://hook:9090/events", "HOOK_TOKEN", 10, 1)
    exporter.send_batch = AsyncMock(return_value=True)
    record = FakePolicyDecision()
    result = await exporter.send(record)
    assert result is True
    exporter.send_batch.assert_called_once_with([record])


@pytest.mark.asyncio
async def test_webhook_send_batch_success():
    """send_batch returns True on 202."""
    exporter = WebhookExporter("http://hook:9090/events", "HOOK_TOKEN", 10, 1)
    fake_resp = FakeResponse(202)
    exporter.session = FakeSession(fake_resp)
    result = await exporter.send_batch([FakePolicyDecision()])
    assert result is True


@pytest.mark.asyncio
async def test_webhook_send_batch_empty():
    """send_batch returns True for empty list."""
    exporter = WebhookExporter("http://hook:9090/events", "HOOK_TOKEN", 10, 1)
    result = await exporter.send_batch([])
    assert result is True


@pytest.mark.asyncio
async def test_webhook_send_batch_failure():
    """send_batch returns False on 500."""
    exporter = WebhookExporter("http://hook:9090/events", "HOOK_TOKEN", 10, 1)
    fake_resp = FakeResponse(500, text="error")
    exporter.session = FakeSession(fake_resp)
    result = await exporter.send_batch([FakePolicyDecision()])
    assert result is False


@pytest.mark.asyncio
async def test_webhook_send_batch_exception():
    """send_batch returns False on exception."""
    exporter = WebhookExporter("http://hook:9090/events", "HOOK_TOKEN", 10, 1)

    class FailSession:
        closed = False

        def post(self, url, **kwargs):
            raise ConnectionError("fail")

    exporter.session = FailSession()
    result = await exporter.send_batch([FakePolicyDecision()])
    assert result is False


@pytest.mark.asyncio
async def test_webhook_health_check_success():
    """health_check returns True when status < 500."""
    exporter = WebhookExporter("http://hook:9090/events", "HOOK_TOKEN", 10, 1)
    fake_resp = FakeResponse(200)
    exporter.session = FakeSession(fake_resp)
    result = await exporter.health_check()
    assert result is True


@pytest.mark.asyncio
async def test_webhook_health_check_failure():
    """health_check returns False on exception."""
    exporter = WebhookExporter("http://hook:9090/events", "HOOK_TOKEN", 10, 1)

    class FailSession:
        closed = False

        def head(self, url, **kwargs):
            raise ConnectionError("fail")

    exporter.session = FailSession()
    result = await exporter.health_check()
    assert result is False


@pytest.mark.asyncio
async def test_webhook_close():
    """close() closes the session."""
    exporter = WebhookExporter("http://hook:9090/events", "HOOK_TOKEN", 10, 1)
    session = FakeSession(FakeResponse(200))
    exporter.session = session
    await exporter.close()
    assert session.closed is True


# --- SIEMBatchProcessor tests ---


@pytest.mark.asyncio
async def test_batch_processor_add_and_flush():
    """Adding records and flushing sends batch."""
    mock_exporter = AsyncMock()
    mock_exporter.send_batch = AsyncMock(return_value=True)
    mock_exporter.close = AsyncMock()

    processor = SIEMBatchProcessor(mock_exporter, batch_size=2, flush_interval_seconds=60)
    await processor.add(FakePolicyDecision("d1"))
    assert len(processor.queue) == 1

    # Adding second record triggers batch (batch_size=2)
    await processor.add(FakePolicyDecision("d2"))
    mock_exporter.send_batch.assert_called_once()


@pytest.mark.asyncio
async def test_batch_processor_failed_flush_requeues():
    """Failed flush re-queues records."""
    mock_exporter = AsyncMock()
    mock_exporter.send_batch = AsyncMock(return_value=False)
    mock_exporter.close = AsyncMock()

    processor = SIEMBatchProcessor(mock_exporter, batch_size=10, flush_interval_seconds=60)
    await processor.add(FakePolicyDecision("d1"))
    await processor._flush()
    assert len(processor.queue) == 1


@pytest.mark.asyncio
async def test_batch_processor_flush_empty():
    """Flushing empty queue is a no-op."""
    mock_exporter = AsyncMock()
    processor = SIEMBatchProcessor(mock_exporter, batch_size=10, flush_interval_seconds=60)
    await processor._flush()
    mock_exporter.send_batch.assert_not_called()


@pytest.mark.asyncio
async def test_batch_processor_start_stop():
    """start() and stop() manage the flush loop."""
    mock_exporter = AsyncMock()
    mock_exporter.send_batch = AsyncMock(return_value=True)
    mock_exporter.close = AsyncMock()

    processor = SIEMBatchProcessor(mock_exporter, batch_size=10, flush_interval_seconds=0.01)
    await processor.start()
    assert processor._running is True

    # Start again should be a no-op
    await processor.start()

    await processor.stop()
    assert processor._running is False
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
