# -*- coding: utf-8 -*-
"""Unit tests for SIEM export service."""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services import siem_export_service as svc


@pytest.mark.asyncio
async def test_initialize_uses_local_queue_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr(svc.settings, "siem_export_enabled", True)
    monkeypatch.setattr(svc.settings, "siem_destinations", [{"name": "webhook-1", "type": "webhook", "url": "https://example.com/hook"}])
    monkeypatch.setattr(svc.settings, "siem_export_event_sources", ["security"])
    monkeypatch.setattr(svc.settings, "siem_export_url_allowlist", [])
    monkeypatch.setattr(svc, "get_redis_client", AsyncMock(return_value=None))

    service = svc.SIEMExportService()
    await service.initialize()

    assert service._queue_backend == "local"  # pylint: disable=protected-access
    assert service._worker_task is not None  # pylint: disable=protected-access

    await service.shutdown()


@pytest.mark.asyncio
async def test_enqueue_event_source_filter(monkeypatch):
    monkeypatch.setattr(svc.settings, "siem_export_enabled", True)
    monkeypatch.setattr(svc.settings, "siem_destinations", [{"name": "webhook-1", "type": "webhook", "url": "https://example.com/hook"}])
    monkeypatch.setattr(svc.settings, "siem_export_event_sources", ["security"])
    monkeypatch.setattr(svc.settings, "siem_export_url_allowlist", [])
    monkeypatch.setattr(svc, "get_redis_client", AsyncMock(return_value=None))

    service = svc.SIEMExportService()
    await service.initialize()

    # auth source disabled, should not enqueue
    auth_result = await service.enqueue_event({"event_type": "authentication_failure"}, source="auth")
    assert auth_result is False

    security_result = await service.enqueue_event({"event_type": "authentication_failure"}, source="security")
    assert security_result is True

    await service.shutdown()


def test_cef_and_leef_formatting(monkeypatch):
    monkeypatch.setattr(svc.settings, "siem_export_enabled", False)
    service = svc.SIEMExportService()

    event = {
        "event_type": "authentication_failure",
        "severity": "HIGH",
        "category": "authentication",
        "description": "Authentication failed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": {"client_ip": "192.168.1.10", "user_email": "alice@example.com"},
        "threat": {"score": 0.85, "failed_attempts": 5},
        "context": {"correlation_id": "corr-1"},
    }

    cef = service._to_cef(event)  # pylint: disable=protected-access
    leef = service._to_leef(event)  # pylint: disable=protected-access

    assert cef.startswith("CEF:0|")
    assert "Authentication failed" in cef
    assert leef.startswith("LEEF:2.0|")
    assert "correlationId=corr-1" in leef


@pytest.mark.asyncio
async def test_add_destination_respects_allowlist(monkeypatch):
    monkeypatch.setattr(svc.settings, "siem_export_enabled", False)
    monkeypatch.setattr(svc.settings, "siem_destinations", [])
    monkeypatch.setattr(svc.settings, "siem_export_url_allowlist", ["allowed.example.com"])
    monkeypatch.setattr(svc, "get_redis_client", AsyncMock(return_value=None))

    service = svc.SIEMExportService()

    with pytest.raises(ValueError, match="allowlist"):
        await service.add_destination({"name": "bad", "type": "webhook", "url": "https://blocked.example.com/hook"})


@pytest.mark.asyncio
async def test_dead_letter_on_retry_exhaustion(monkeypatch):
    monkeypatch.setattr(svc.settings, "siem_export_enabled", False)
    monkeypatch.setattr(svc.settings, "siem_destinations", [])
    monkeypatch.setattr(svc.settings, "siem_export_max_retries", 0)

    service = svc.SIEMExportService()
    event = {"event_type": "test", "severity": "LOW", "_meta": {"attempt": 0}}

    await service._schedule_retry_or_dead_letter(event=event, failed_destinations=["d1"])  # pylint: disable=protected-access

    assert len(service._local_dead_letter) == 1  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_webhook_send_uses_template(monkeypatch):
    monkeypatch.setattr(svc.settings, "siem_export_enabled", False)
    service = svc.SIEMExportService()

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client.request = AsyncMock(return_value=mock_response)

    monkeypatch.setattr(svc, "get_http_client", AsyncMock(return_value=mock_client))

    destination = {
        "name": "webhook-1",
        "type": "webhook",
        "url": "https://example.com/hook",
        "template": '{"summary": "{{ event.description }}"}',
        "format": "json",
    }
    event = service._build_event_envelope(  # pylint: disable=protected-access
        event={"event_type": "security_test", "description": "SIEM test"},
        source="security",
    )

    await service._send_webhook(destination=destination, event=event)  # pylint: disable=protected-access

    mock_client.request.assert_awaited_once()
