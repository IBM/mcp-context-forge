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


# ---------------------------------------------------------------------------
# Deny-path regression tests (unauthenticated, insufficient permissions, feature disabled)
# ---------------------------------------------------------------------------
class TestSIEMRBACDenyPaths:
    """Verify SIEM endpoints reject requests without proper auth/permissions.

    Per AGENTS.md: 'Security-sensitive changes must include deny-path regression
    tests (unauthenticated, wrong team, insufficient permissions, feature disabled).'
    """

    @pytest.mark.asyncio
    async def test_health_endpoint_has_require_permission_decorator(self):
        """GET /admin/siem/health must be wrapped by @require_permission."""
        assert hasattr(siem.get_siem_health, "__wrapped__"), "get_siem_health() is missing @require_permission decorator"

    @pytest.mark.asyncio
    async def test_destinations_endpoint_has_require_permission_decorator(self):
        """GET /admin/siem/destinations must be wrapped by @require_permission."""
        assert hasattr(siem.get_siem_destinations, "__wrapped__"), "get_siem_destinations() is missing @require_permission decorator"

    @pytest.mark.asyncio
    async def test_add_destination_endpoint_has_require_permission_decorator(self):
        """POST /admin/siem/destinations must be wrapped by @require_permission."""
        assert hasattr(siem.add_siem_destination, "__wrapped__"), "add_siem_destination() is missing @require_permission decorator"

    @pytest.mark.asyncio
    async def test_replace_destinations_endpoint_has_require_permission_decorator(self):
        """PUT /admin/siem/destinations must be wrapped by @require_permission."""
        assert hasattr(siem.replace_siem_destinations, "__wrapped__"), "replace_siem_destinations() is missing @require_permission decorator"

    @pytest.mark.asyncio
    async def test_test_destination_endpoint_has_require_permission_decorator(self):
        """POST /admin/siem/test/{name} must be wrapped by @require_permission."""
        assert hasattr(siem.test_siem_destination, "__wrapped__"), "test_siem_destination() is missing @require_permission decorator"

    @pytest.mark.asyncio
    async def test_health_denies_insufficient_permissions(self, monkeypatch):
        """GET /admin/siem/health must return 403 when permission check fails."""

        class DenyPermissionService:
            def __init__(self, _db):
                pass

            async def check_permission(self, **kwargs):
                return False

        monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", DenyPermissionService)
        with pytest.raises(HTTPException) as exc:
            await siem.get_siem_health(
                _user={"id": "viewer1", "email": "viewer@test.com", "db": MagicMock()},
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_add_destination_denies_insufficient_permissions(self, monkeypatch):
        """POST /admin/siem/destinations must return 403 when permission check fails."""

        class DenyPermissionService:
            def __init__(self, _db):
                pass

            async def check_permission(self, **kwargs):
                return False

        monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", DenyPermissionService)
        payload = siem.DestinationUpsertRequest(name="dest-1", type="webhook", url="https://example.com/hook")
        with pytest.raises(HTTPException) as exc:
            await siem.add_siem_destination(
                payload=payload,
                _user={"id": "viewer1", "email": "viewer@test.com", "db": MagicMock()},
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_health_denies_unauthenticated(self, monkeypatch):
        """GET /admin/siem/health must return 401 when no user is provided."""

        class DenyPermissionService:
            def __init__(self, _db):
                pass

            async def check_permission(self, **kwargs):
                return False

        monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", DenyPermissionService)
        with pytest.raises(HTTPException) as exc:
            await siem.get_siem_health(_user=None)
        assert exc.value.status_code == 401
