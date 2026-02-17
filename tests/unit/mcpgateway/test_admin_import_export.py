# -*- coding: utf-8 -*-
"""Tests for admin import/export endpoints."""

# Standard
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway import admin
from mcpgateway.services.import_service import ImportError as ImportServiceError
from mcpgateway.services.permission_service import PermissionService


def _make_json_request(payload: dict) -> MagicMock:
    request = MagicMock()
    request.body = AsyncMock(return_value=json.dumps(payload).encode())
    request.json = AsyncMock(return_value=payload)
    request.headers = {}
    request.scope = {"root_path": ""}
    request.app = SimpleNamespace(state=SimpleNamespace(templates=MagicMock()))
    return request


@pytest.fixture(autouse=True)
def _allow_permissions(monkeypatch):
    async def _ok(self, **_kwargs):  # type: ignore[no-self-use]
        return True

    monkeypatch.setattr(PermissionService, "check_permission", _ok)


@pytest.mark.asyncio
async def test_admin_export_configuration_success():
    request = MagicMock()
    mock_db = MagicMock()
    user = {"email": "admin@example.com", "username": "admin", "permissions": ["*"]}

    with patch.object(admin, "export_service") as mock_export:
        mock_export.export_configuration = AsyncMock(return_value={"ok": True})
        response = await admin.admin_export_configuration(request, db=mock_db, user=user)
        assert response.media_type == "application/json"
        assert b"ok" in response.body


@pytest.mark.asyncio
async def test_admin_export_selective_success():
    request = _make_json_request({"entity_selections": {"tools": ["t1"]}, "include_dependencies": False})
    mock_db = MagicMock()
    user = {"email": "admin@example.com", "username": "admin", "permissions": ["*"]}

    with patch.object(admin, "export_service") as mock_export:
        mock_export.export_selective = AsyncMock(return_value={"tools": ["t1"]})
        response = await admin.admin_export_selective(request, db=mock_db, user=user)
        assert response.media_type == "application/json"
        assert b"tools" in response.body


@pytest.mark.asyncio
async def test_admin_import_preview_missing_data():
    request = _make_json_request({})
    with pytest.raises(HTTPException) as exc:
        await admin.admin_import_preview(request, db=MagicMock(), user={"email": "admin@example.com", "username": "admin", "permissions": ["*"]})
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_admin_import_preview_success():
    request = _make_json_request({"data": {"tools": []}})
    with patch.object(admin, "import_service") as mock_import:
        mock_import.preview_import = AsyncMock(return_value={"summary": {"total_items": 0}})
        response = await admin.admin_import_preview(request, db=MagicMock(), user={"email": "admin@example.com", "username": "admin", "permissions": ["*"]})
        assert b"preview" in response.body


@pytest.mark.asyncio
async def test_admin_import_configuration_invalid_conflict_strategy():
    request = _make_json_request({"import_data": {"tools": []}, "conflict_strategy": "nope"})
    with pytest.raises(HTTPException) as exc:
        await admin.admin_import_configuration(request, db=MagicMock(), user={"email": "admin@example.com", "username": "admin", "permissions": ["*"]})
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_admin_import_configuration_success():
    class _Status:
        def to_dict(self):
            return {"status": "ok"}

    request = _make_json_request({"import_data": {"tools": []}, "conflict_strategy": "update"})
    with patch.object(admin, "import_service") as mock_import:
        mock_import.import_configuration = AsyncMock(return_value=_Status())
        response = await admin.admin_import_configuration(request, db=MagicMock(), user={"email": "admin@example.com", "username": "admin", "permissions": ["*"]})
        assert b"status" in response.body


@pytest.mark.asyncio
async def test_admin_import_configuration_error():
    request = _make_json_request({"import_data": {"tools": []}, "conflict_strategy": "update"})
    with patch.object(admin, "import_service") as mock_import:
        mock_import.import_configuration = AsyncMock(side_effect=ImportServiceError("boom"))
        with pytest.raises(HTTPException) as exc:
            await admin.admin_import_configuration(request, db=MagicMock(), user={"email": "admin@example.com", "username": "admin", "permissions": ["*"]})
        assert exc.value.status_code == 400
