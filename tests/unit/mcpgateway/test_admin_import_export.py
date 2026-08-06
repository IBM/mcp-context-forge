# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_import_export.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for admin import/export endpoints.
"""

# Standard
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway import admin
from mcpgateway.middleware.rbac import _GLOBAL_SCOPE_DENIED_MSG
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
    user = {"email": "admin@example.com", "username": "admin"}

    with patch.object(admin, "export_service") as mock_export, patch.object(admin, "is_unrestricted_platform_admin", new=AsyncMock(return_value=True)), patch(
        "mcpgateway.auth_context.is_unrestricted_platform_admin", new=AsyncMock(return_value=True)
    ):
        # admin_export_configuration enforces via require_unrestricted_platform_admin(), which
        # resolves is_unrestricted_platform_admin via its own deferred import from
        # mcpgateway.auth_context, not admin.py's module-level name, so both must be patched.
        mock_export.export_configuration = AsyncMock(return_value={"ok": True})
        response = await admin.admin_export_configuration(request, db=mock_db, user=user)
        assert response.media_type == "application/json"
        assert b"ok" in response.body


@pytest.mark.asyncio
async def test_admin_export_selective_success():
    request = _make_json_request({"entity_selections": {"tools": ["t1"]}, "include_dependencies": False})
    mock_db = MagicMock()
    user = {"email": "admin@example.com", "username": "admin"}

    with patch.object(admin, "export_service") as mock_export:
        mock_export.export_selective = AsyncMock(return_value={"tools": ["t1"]})
        response = await admin.admin_export_selective(request, db=mock_db, user=user)
        assert response.media_type == "application/json"
        assert b"tools" in response.body


@pytest.mark.asyncio
async def test_admin_export_selective_preserves_root_authorization_denial(monkeypatch):
    request = _make_json_request({"entity_selections": {"roots": ["https://example.com/root"]}})
    export_service = MagicMock()
    export_service.export_selective = AsyncMock()
    monkeypatch.setattr(admin, "export_service", export_service)
    monkeypatch.setattr(admin, "is_unrestricted_platform_admin", AsyncMock(return_value=False))
    # admin_export_selective enforces via require_unrestricted_platform_admin(), which resolves
    # is_unrestricted_platform_admin via its own deferred import from mcpgateway.auth_context.
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as excinfo:
        await admin.admin_export_selective(request, db=MagicMock(), user={"email": "admin@example.com"})

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == _GLOBAL_SCOPE_DENIED_MSG
    export_service.export_selective.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_import_preview_missing_data():
    request = _make_json_request({})
    with pytest.raises(HTTPException) as exc:
        await admin.admin_import_preview(request, db=MagicMock(), user={"email": "admin@example.com", "username": "admin"})
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_admin_import_preview_success():
    request = _make_json_request({"data": {"tools": []}})
    with patch.object(admin, "import_service") as mock_import:
        mock_import.preview_import = AsyncMock(return_value={"summary": {"total_items": 0}})
        response = await admin.admin_import_preview(request, db=MagicMock(), user={"email": "admin@example.com", "username": "admin"})
        assert b"preview" in response.body


@pytest.mark.asyncio
async def test_admin_import_preview_denies_root_payload_before_service(monkeypatch):
    request = _make_json_request({"data": {"entities": {"roots": [{"uri": "https://example.com/root"}]}}})
    preview_service = MagicMock(preview_import=AsyncMock())
    monkeypatch.setattr(admin, "import_service", preview_service)
    monkeypatch.setattr(admin, "is_unrestricted_platform_admin", AsyncMock(return_value=False))
    # admin_import_preview enforces via require_unrestricted_platform_admin(), which resolves
    # is_unrestricted_platform_admin via its own deferred import from mcpgateway.auth_context.
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as excinfo:
        await admin.admin_import_preview(request, db=MagicMock(), user={"email": "admin@example.com"})

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == _GLOBAL_SCOPE_DENIED_MSG
    preview_service.preview_import.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_import_preview_allows_root_free_payload_when_root_gate_denies(monkeypatch):
    request = _make_json_request({"data": {"entities": {"tools": []}}})
    preview_service = MagicMock(preview_import=AsyncMock(return_value={"summary": {"total_items": 0}}))
    monkeypatch.setattr(admin, "import_service", preview_service)
    monkeypatch.setattr(admin, "is_unrestricted_platform_admin", AsyncMock(return_value=False))

    response = await admin.admin_import_preview(request, db=MagicMock(), user={"email": "admin@example.com"})

    assert response.status_code == 200
    preview_service.preview_import.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_import_configuration_invalid_conflict_strategy():
    request = _make_json_request({"import_data": {"tools": []}, "conflict_strategy": "nope"})
    with pytest.raises(HTTPException) as exc:
        await admin.admin_import_configuration(request, db=MagicMock(), user={"email": "admin@example.com", "username": "admin"})
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_admin_import_configuration_success():
    class _Status:
        def to_dict(self):
            return {"status": "ok"}

    request = _make_json_request({"import_data": {"tools": []}, "conflict_strategy": "update"})
    with patch.object(admin, "import_service") as mock_import:
        mock_import.import_configuration = AsyncMock(return_value=_Status())
        response = await admin.admin_import_configuration(request, db=MagicMock(), user={"email": "admin@example.com", "username": "admin"})
        assert b"status" in response.body


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [True, False])
async def test_admin_import_configuration_denies_root_payload_before_service(monkeypatch, dry_run):
    request = _make_json_request(
        {"import_data": {"entities": {"roots": [{"uri": "https://example.com/root"}]}}, "conflict_strategy": "update", "dry_run": dry_run}
    )
    import_service = MagicMock(import_configuration=AsyncMock())
    monkeypatch.setattr(admin, "import_service", import_service)
    monkeypatch.setattr(admin, "is_unrestricted_platform_admin", AsyncMock(return_value=False))
    # admin_import_configuration enforces via require_unrestricted_platform_admin(), which
    # resolves is_unrestricted_platform_admin via its own deferred import from
    # mcpgateway.auth_context.
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as excinfo:
        await admin.admin_import_configuration(request, db=MagicMock(), user={"email": "admin@example.com"})

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == _GLOBAL_SCOPE_DENIED_MSG
    import_service.import_configuration.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [True, False])
async def test_admin_import_configuration_allows_root_free_payload_when_root_gate_denies(monkeypatch, dry_run):
    class _Status:
        def to_dict(self):
            return {"status": "ok"}

    request = _make_json_request({"import_data": {"entities": {"tools": []}}, "conflict_strategy": "update", "dry_run": dry_run})
    import_service = MagicMock(import_configuration=AsyncMock(return_value=_Status()))
    monkeypatch.setattr(admin, "import_service", import_service)
    monkeypatch.setattr(admin, "is_unrestricted_platform_admin", AsyncMock(return_value=False))

    response = await admin.admin_import_configuration(request, db=MagicMock(), user={"email": "admin@example.com"})

    assert response.status_code == 200
    import_service.import_configuration.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_import_configuration_error():
    request = _make_json_request({"import_data": {"tools": []}, "conflict_strategy": "update"})
    with patch.object(admin, "import_service") as mock_import:
        mock_import.import_configuration = AsyncMock(side_effect=ImportServiceError("boom"))
        with pytest.raises(HTTPException) as exc:
            await admin.admin_import_configuration(request, db=MagicMock(), user={"email": "admin@example.com", "username": "admin"})
        assert exc.value.status_code == 400
