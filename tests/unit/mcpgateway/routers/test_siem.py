# -*- coding: utf-8 -*-
"""Tests for SIEM admin router."""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
from fastapi import HTTPException

# First-Party
from mcpgateway.routers import siem


@pytest.mark.asyncio
async def test_get_siem_health(monkeypatch):
    mock_service = MagicMock()
    mock_service.get_health = AsyncMock(return_value={"status": "healthy"})
    monkeypatch.setattr(siem, "get_siem_export_service", lambda: mock_service)

    response = await siem.get_siem_health(_user={"email": "admin@example.com"})
    assert response["status"] == "healthy"


@pytest.mark.asyncio
async def test_get_siem_destinations(monkeypatch):
    mock_service = MagicMock()
    mock_service.enabled = True
    mock_service.list_destinations.return_value = [{"name": "dest-1"}]
    monkeypatch.setattr(siem, "get_siem_export_service", lambda: mock_service)

    response = await siem.get_siem_destinations(_user={"email": "admin@example.com"})
    assert response["enabled"] is True
    assert response["destinations"][0]["name"] == "dest-1"


@pytest.mark.asyncio
async def test_add_siem_destination_success(monkeypatch):
    mock_service = MagicMock()
    mock_service.add_destination = AsyncMock(return_value={"name": "dest-1", "type": "webhook"})
    monkeypatch.setattr(siem, "get_siem_export_service", lambda: mock_service)

    payload = siem.DestinationUpsertRequest(name="dest-1", type="webhook", url="https://example.com/hook")
    response = await siem.add_siem_destination(payload=payload, _user={"email": "admin@example.com"})

    assert response["status"] == "ok"
    assert response["destination"]["name"] == "dest-1"


@pytest.mark.asyncio
async def test_add_siem_destination_validation_error(monkeypatch):
    mock_service = MagicMock()
    mock_service.add_destination = AsyncMock(side_effect=ValueError("invalid destination"))
    monkeypatch.setattr(siem, "get_siem_export_service", lambda: mock_service)

    payload = siem.DestinationUpsertRequest(name="dest-1", type="webhook", url="https://example.com/hook")

    with pytest.raises(HTTPException) as exc_info:
        await siem.add_siem_destination(payload=payload, _user={"email": "admin@example.com"})

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_add_siem_destination_internal_error(monkeypatch):
    mock_service = MagicMock()
    mock_service.add_destination = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(siem, "get_siem_export_service", lambda: mock_service)

    payload = siem.DestinationUpsertRequest(name="dest-1", type="webhook", url="https://example.com/hook")

    with pytest.raises(HTTPException) as exc_info:
        await siem.add_siem_destination(payload=payload, _user={"email": "admin@example.com"})

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_replace_siem_destinations_success(monkeypatch):
    mock_service = MagicMock()
    mock_service.replace_destinations = AsyncMock(return_value=[{"name": "dest-1", "type": "webhook"}])
    monkeypatch.setattr(siem, "get_siem_export_service", lambda: mock_service)

    payload = siem.DestinationBulkReplaceRequest(destinations=[siem.DestinationUpsertRequest(name="dest-1", type="webhook", url="https://example.com/hook")])
    response = await siem.replace_siem_destinations(payload=payload, _user={"email": "admin@example.com"})

    assert response["status"] == "ok"
    assert response["destinations"][0]["name"] == "dest-1"


@pytest.mark.asyncio
async def test_replace_siem_destinations_validation_error(monkeypatch):
    mock_service = MagicMock()
    mock_service.replace_destinations = AsyncMock(side_effect=ValueError("invalid destination"))
    monkeypatch.setattr(siem, "get_siem_export_service", lambda: mock_service)

    payload = siem.DestinationBulkReplaceRequest(destinations=[siem.DestinationUpsertRequest(name="dest-1", type="webhook", url="https://example.com/hook")])

    with pytest.raises(HTTPException) as exc_info:
        await siem.replace_siem_destinations(payload=payload, _user={"email": "admin@example.com"})

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_replace_siem_destinations_internal_error(monkeypatch):
    mock_service = MagicMock()
    mock_service.replace_destinations = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(siem, "get_siem_export_service", lambda: mock_service)

    payload = siem.DestinationBulkReplaceRequest(destinations=[siem.DestinationUpsertRequest(name="dest-1", type="webhook", url="https://example.com/hook")])

    with pytest.raises(HTTPException) as exc_info:
        await siem.replace_siem_destinations(payload=payload, _user={"email": "admin@example.com"})

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_test_siem_destination_not_found(monkeypatch):
    mock_service = MagicMock()
    mock_service.test_destination = AsyncMock(side_effect=KeyError("Unknown destination"))
    monkeypatch.setattr(siem, "get_siem_export_service", lambda: mock_service)

    with pytest.raises(HTTPException) as exc_info:
        await siem.test_siem_destination(destination_name="missing", _user={"email": "admin@example.com"})

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_test_siem_destination_internal_error(monkeypatch):
    mock_service = MagicMock()
    mock_service.test_destination = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(siem, "get_siem_export_service", lambda: mock_service)

    with pytest.raises(HTTPException) as exc_info:
        await siem.test_siem_destination(destination_name="dest-1", _user={"email": "admin@example.com"})

    assert exc_info.value.status_code == 500
