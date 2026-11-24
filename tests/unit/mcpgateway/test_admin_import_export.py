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
from mcpgateway.services.import_service import ImportError as ImportServiceError
from mcpgateway.services.import_service import ImportConflictError, ImportValidationError
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

    with patch.object(admin, "export_service") as mock_export, patch.object(admin, "is_unrestricted_platform_admin", new=AsyncMock(return_value=True)):
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

    with pytest.raises(HTTPException) as excinfo:
        await admin.admin_export_selective(request, db=MagicMock(), user={"email": "admin@example.com"})

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == admin._ACCESS_DENIED_MSG
    export_service.export_selective.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_import_preview_missing_data():
    request = _make_json_request({})
    with pytest.raises(HTTPException) as exc:
        await admin.admin_import_preview(request, db=MagicMock(), user={"email": "admin@example.com", "username": "admin"})
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_admin_import_preview_success():
    selection = {"tools": ["local-tool"]}
    request = _make_json_request({"data": {"entities": {"tools": []}}, "team_name": "Operations", "selected_entities": selection, "conflict_strategy": "skip"})
    with patch.object(admin, "import_service") as mock_import, patch.object(admin, "get_import_request_scope", AsyncMock(return_value=("admin@example.com", ["team-ops"], False))):
        mock_import.preview_import = AsyncMock(return_value={"summary": {"total_items": 0}})
        response = await admin.admin_import_preview(request, db=MagicMock(), user={"email": "admin@example.com", "username": "admin"})
        assert b"preview" in response.body
        options = mock_import.preview_import.await_args.kwargs
        assert (options["team_name"], options["selected_entities"], options["conflict_strategy"]) == ("Operations", selection, admin.ConflictStrategy.SKIP)
        assert (options["imported_by"], options["token_teams"], options["unrestricted_admin"]) == ("admin@example.com", ["team-ops"], False)


@pytest.mark.asyncio
async def test_admin_import_preview_denies_root_payload_before_service(monkeypatch):
    request = _make_json_request({"data": {"entities": {"roots": [{"uri": "https://example.com/root"}]}}})
    preview_service = MagicMock(preview_import=AsyncMock())
    monkeypatch.setattr(admin, "import_service", preview_service)
    monkeypatch.setattr(admin, "is_unrestricted_platform_admin", AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as excinfo:
        await admin.admin_import_preview(request, db=MagicMock(), user={"email": "admin@example.com"})

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == admin._ACCESS_DENIED_MSG
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
        {"import_data": {"entities": {"roots": [{"uri": "https://example.com/root"}]}}, "conflict_strategy": "update", "dry_run": dry_run, "selected_entities": {"tools": []}}
    )
    import_service = MagicMock(import_configuration=AsyncMock())
    monkeypatch.setattr(admin, "import_service", import_service)
    monkeypatch.setattr(admin, "is_unrestricted_platform_admin", AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as excinfo:
        await admin.admin_import_configuration(request, db=MagicMock(), user={"email": "admin@example.com"})

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == admin._ACCESS_DENIED_MSG
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


@pytest.mark.asyncio
@pytest.mark.parametrize(("handler", "field"), [(admin.admin_import_configuration, "import_data"), (admin.admin_import_preview, "data")])
@pytest.mark.parametrize("value", [None, "obsolete"])
async def test_admin_import_rejects_rekey_option(handler, field, value, monkeypatch):
    """Reject the retired option even when its value is null."""
    service = MagicMock(import_configuration=AsyncMock(), preview_import=AsyncMock())
    monkeypatch.setattr(admin, "import_service", service)
    request = _make_json_request({field: {"entities": {"tools": []}}, "rekey_secret": value})

    with pytest.raises(HTTPException) as exc:
        await handler(request, db=MagicMock(), user={"email": "admin@example.com"})

    assert exc.value.status_code == 400
    assert "python -m mcpgateway.scripts.migrate_enc_secret" in exc.value.detail
    service.import_configuration.assert_not_awaited()
    service.preview_import.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_import_fail_conflict_returns_409(monkeypatch):
    """Return a conflict for an aborted import."""
    service = MagicMock(import_configuration=AsyncMock(side_effect=admin.ImportConflictError("conflict")))
    monkeypatch.setattr(admin, "import_service", service)
    monkeypatch.setattr(admin, "get_import_request_scope", AsyncMock(return_value=("admin@example.com", [], False)))
    request = _make_json_request({"import_data": {"entities": {"tools": []}}, "conflict_strategy": "fail"})

    with pytest.raises(HTTPException) as exc:
        await admin.admin_import_configuration(request, db=MagicMock(), user={"email": "admin@example.com"})

    assert exc.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", [admin.admin_import_configuration, admin.admin_import_preview])
async def test_admin_import_rejects_malformed_json(handler, monkeypatch):
    """Reject malformed JSON before starting an import or a preview."""
    service = MagicMock(import_configuration=AsyncMock(), preview_import=AsyncMock())
    monkeypatch.setattr(admin, "import_service", service)
    request = _make_json_request({})
    request.body.return_value = b'{"import_data":'

    with pytest.raises(HTTPException) as exc:
        await handler(request, db=MagicMock(), user={"email": "admin@example.com"})

    assert (exc.value.status_code, exc.value.detail) == (400, "Invalid JSON in request body")
    service.import_configuration.assert_not_awaited()
    service.preview_import.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "detail"),
    [
        ({"team_name": []}, "team_name must be a string"),
        ({"selected_entities": {"tools": [3]}}, "selected_entities must map entity types to lists of names or IDs"),
        ({"dry_run": "false"}, "dry_run must be a boolean"),
    ],
)
async def test_admin_import_rejects_invalid_options(options, detail, monkeypatch):
    """Reject malformed options before they can reach the write path."""
    service = AsyncMock()
    monkeypatch.setattr(admin.import_service, "import_configuration", service)
    request = _make_json_request({"import_data": {"entities": {"tools": []}}, **options})

    with pytest.raises(HTTPException) as exc:
        await admin.admin_import_configuration(request, db=MagicMock(), user={"email": "admin@example.com"})

    assert (exc.value.status_code, exc.value.detail) == (400, detail)
    service.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "error", "expected"),
    [
        ("preview", PermissionError, (403, admin._ACCESS_DENIED_MSG)),
        ("preview", ImportConflictError, (409, "Import conflict detected")),
        ("preview", ImportValidationError, (400, "Invalid import data")),
        ("preview", RuntimeError, (500, "Preview failed")),
        ("apply", PermissionError, (403, admin._ACCESS_DENIED_MSG)),
        ("apply", RuntimeError, (500, "Import failed")),
    ],
)
async def test_admin_import_errors_do_not_disclose_internal_details(operation, error, expected, caplog, monkeypatch):
    """Report the public error and omit the internal service message from logs."""
    handler, service_method, field = (
        (admin.admin_import_preview, "preview_import", "data") if operation == "preview" else (admin.admin_import_configuration, "import_configuration", "import_data")
    )
    internal_detail = "internal downstream diagnostic"
    service = AsyncMock(side_effect=error(internal_detail))
    monkeypatch.setattr(admin.import_service, service_method, service)
    monkeypatch.setattr(admin, "get_import_request_scope", AsyncMock(return_value=("admin@example.com", ["team-ops"], False)))
    request = _make_json_request({field: {"entities": {"tools": []}}})

    with pytest.raises(HTTPException) as exc:
        await handler(request, db=MagicMock(), user={"email": "admin@example.com"})

    service.assert_awaited_once()
    assert (exc.value.status_code, exc.value.detail) == expected
    assert internal_detail not in caplog.text
