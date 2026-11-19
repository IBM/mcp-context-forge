# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_siem_export_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for SIEM export service.
"""

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


class TestApplyRedaction:
    """``_apply_redaction`` masks configured field names in any letter case, at any depth."""

    @pytest.fixture
    def service(self):
        return svc.SIEMExportService()

    @pytest.mark.parametrize(
        "name",
        ["x-amz-security-token", "X-Amz-Security-Token", "x-amz-signature", "X-Amz-Signature", "x-amz-credential", "X-AMZ-CREDENTIAL", "secret_access_key", "Secret_Access_Key", "Session_Token"],
    )
    def test_default_fields_redact_sigv4_credentials_in_any_case(self, service, name):
        event = {"details": {"headers": {name: "credential-value", "x-amz-date": "20260101T000000Z"}}}

        redacted = service._apply_redaction({}, event)  # pylint: disable=protected-access

        assert redacted["details"]["headers"][name] == "***REDACTED***"
        assert redacted["details"]["headers"]["x-amz-date"] == "20260101T000000Z"

    def test_redacts_inside_lists_and_leaves_the_input_event_unchanged(self, service):
        event = {"items": [{"Session_Token": "token-value"}, {"region": "us-east-1"}]}

        redacted = service._apply_redaction({}, event)  # pylint: disable=protected-access

        assert redacted["items"] == [{"Session_Token": "***REDACTED***"}, {"region": "us-east-1"}]
        assert event["items"][0]["Session_Token"] == "token-value"

    def test_configured_fields_match_case_insensitively(self, monkeypatch):
        monkeypatch.setattr(svc.settings, "siem_export_redact_fields", ["Custom_Field"])

        redacted = svc.SIEMExportService()._apply_redaction({}, {"custom_field": "a", "CUSTOM_FIELD": "b", "other": "c"})  # pylint: disable=protected-access

        assert redacted == {"custom_field": "***REDACTED***", "CUSTOM_FIELD": "***REDACTED***", "other": "c"}

    def test_destination_fields_match_case_insensitively(self, service):
        redacted = service._apply_redaction({"redact_fields": ["Tenant_Key"]}, {"tenant_key": "a", "other": "b"})  # pylint: disable=protected-access

        assert redacted == {"tenant_key": "***REDACTED***", "other": "b"}
