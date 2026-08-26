# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_catalog.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the v1 catalog API router.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import APIRouter, HTTPException, Request
import pydantic
import pytest

# First-Party
from mcpgateway.api.v1 import build_legacy_router, build_v1_router
from mcpgateway.config import settings
from mcpgateway.routers.catalog import list_catalog_servers, register_catalog_server
from mcpgateway.services.catalog_service import CatalogRegistrationPermissionError
from mcpgateway.schemas import CatalogListResponse, CatalogServerRegisterBody, CatalogServerRegisterRequest, CatalogServerRegisterResponse
from mcpgateway.services.catalog_service import CATALOG_REGISTER_ALREADY_REGISTERED_MSG, CATALOG_REGISTER_NOT_FOUND_MSG
from tests.helpers.router_helpers import collect_routes


@pytest.fixture
def allow_permission(monkeypatch):
    """Allow RBAC permission checks to pass for decorator-wrapped handlers."""
    mock_perm_service = MagicMock()
    mock_perm_service.check_permission = AsyncMock(return_value=True)
    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", lambda db: mock_perm_service)
    monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))
    return mock_perm_service


def _empty_router_kwargs() -> dict[str, APIRouter]:
    """Return the full set of inline-router kwargs as empty APIRouters."""
    names = [
        "protocol_router",
        "tool_router",
        "resource_router",
        "prompt_router",
        "gateway_router",
        "root_router",
        "server_router",
        "metrics_router",
        "tag_router",
        "export_import_router",
        "a2a_router",
    ]
    return {name: APIRouter() for name in names}


@pytest.mark.asyncio
async def test_list_catalog_requires_authenticated_user():
    """Calling the router without an authenticated user returns 401."""
    request = MagicMock(spec=Request)

    with pytest.raises(HTTPException) as exc_info:
        await list_catalog_servers(request, db=MagicMock())

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_list_catalog_disabled_returns_404(monkeypatch, allow_permission):
    """The v1 catalog endpoint returns 404 when the catalog feature is disabled."""
    monkeypatch.setattr("mcpgateway.routers.catalog.settings.mcpgateway_catalog_enabled", False, raising=False)
    request = MagicMock(spec=Request)
    db = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await list_catalog_servers(request, db=db, user={"email": "user@example.com", "db": db})

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Catalog feature is disabled"


@pytest.mark.asyncio
async def test_list_catalog_success_forwards_filters_and_scope(monkeypatch, allow_permission):
    """The v1 catalog endpoint forwards filters and scoped visibility context."""
    monkeypatch.setattr("mcpgateway.routers.catalog.settings.mcpgateway_catalog_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.routers.catalog.get_scoped_resource_access_context", MagicMock(return_value=("user@example.com", ["team-a"])))
    mock_response = CatalogListResponse(servers=[], total=0, categories=[], auth_types=[], providers=[], all_tags=[])
    mock_get_catalog = AsyncMock(return_value=mock_response)
    monkeypatch.setattr("mcpgateway.routers.catalog.catalog_service.get_catalog_servers", mock_get_catalog)
    request = MagicMock(spec=Request)
    db = MagicMock()

    result = await list_catalog_servers(
        request,
        category="Development",
        auth_type="OAuth2.1",
        provider="IBM",
        search="github",
        tags=["git", "repo"],
        show_registered_only=True,
        show_available_only=False,
        limit=25,
        offset=50,
        db=db,
        user={"email": "user@example.com", "db": db, "token_teams": ["team-a"]},
    )

    assert result == mock_response
    catalog_request = mock_get_catalog.await_args.args[0]
    assert catalog_request.category == "Development"
    assert catalog_request.auth_type == "OAuth2.1"
    assert catalog_request.provider == "IBM"
    assert catalog_request.search == "github"
    assert catalog_request.tags == ["git", "repo"]
    assert catalog_request.show_registered_only is True
    assert catalog_request.show_available_only is False
    assert catalog_request.limit == 25
    assert catalog_request.offset == 50
    assert mock_get_catalog.await_args.args[1] is db
    assert mock_get_catalog.await_args.kwargs == {"user_email": "user@example.com", "token_teams": ["team-a"]}


def test_catalog_router_is_v1_only():
    """Catalog is exposed at /v1/catalog without creating a legacy /catalog alias."""
    v1_paths = [path for path, *_ in collect_routes(build_v1_router(settings, **_empty_router_kwargs()))]
    legacy_paths = [path for path, *_ in collect_routes(build_legacy_router(settings, **_empty_router_kwargs()))]

    assert "/v1/catalog" in v1_paths
    assert "/v1/catalog/" not in v1_paths
    assert "/catalog" not in legacy_paths
    assert "/catalog/" not in legacy_paths
    assert "/v1/catalog/{catalog_id}/register" in v1_paths
    assert "/catalog/{catalog_id}/register" not in legacy_paths


@pytest.mark.asyncio
async def test_register_requires_authenticated_user():
    """Calling the register endpoint without an authenticated user returns 401."""
    request = MagicMock(spec=Request)

    with pytest.raises(HTTPException) as exc_info:
        await register_catalog_server("asana", request, db=MagicMock())

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_register_rbac_denied_returns_403(monkeypatch):
    """A caller without the required permissions is rejected with 403 before the service runs."""
    mock_perm_service = MagicMock()
    mock_perm_service.check_permission = AsyncMock(return_value=False)
    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", lambda db: mock_perm_service)
    monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))
    mock_register = AsyncMock()
    monkeypatch.setattr("mcpgateway.routers.catalog.catalog_service.register_catalog_server", mock_register)
    db = MagicMock()
    request = MagicMock(spec=Request)

    with pytest.raises(HTTPException) as exc_info:
        await register_catalog_server("asana", request, db=db, user={"email": "user@example.com", "db": db})

    assert exc_info.value.status_code == 403
    assert mock_register.await_count == 0


@pytest.mark.parametrize("denied", ["servers.create", "gateways.create"])
@pytest.mark.asyncio
async def test_register_requires_both_permissions(monkeypatch, denied):
    """Registration needs servers.create AND gateways.create; denying either yields 403."""
    monkeypatch.setattr("mcpgateway.routers.catalog.settings.mcpgateway_catalog_enabled", True, raising=False)

    async def check_permission(**kwargs):
        return kwargs["permission"] != denied

    mock_perm_service = MagicMock()
    mock_perm_service.check_permission = AsyncMock(side_effect=check_permission)
    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", lambda db: mock_perm_service)
    monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))
    mock_register = AsyncMock()
    monkeypatch.setattr("mcpgateway.routers.catalog.catalog_service.register_catalog_server", mock_register)
    db = MagicMock()
    request = MagicMock(spec=Request)

    with pytest.raises(HTTPException) as exc_info:
        await register_catalog_server("asana", request, db=db, user={"email": "user@example.com", "db": db})

    assert exc_info.value.status_code == 403
    assert mock_register.await_count == 0


def test_register_disables_admin_bypass():
    """Platform admins must hold the permissions explicitly: no admin bypass on this route."""
    assert register_catalog_server._allow_admin_bypass is False


@pytest.mark.asyncio
async def test_register_disabled_returns_404(monkeypatch, allow_permission):
    """The register endpoint returns 404 without touching the service when the feature is disabled."""
    monkeypatch.setattr("mcpgateway.routers.catalog.settings.mcpgateway_catalog_enabled", False, raising=False)
    mock_register = AsyncMock()
    monkeypatch.setattr("mcpgateway.routers.catalog.catalog_service.register_catalog_server", mock_register)
    db = MagicMock()
    request = MagicMock(spec=Request)

    with pytest.raises(HTTPException) as exc_info:
        await register_catalog_server("asana", request, db=db, user={"email": "user@example.com", "db": db})

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Catalog feature is disabled"
    assert mock_register.await_count == 0


@pytest.mark.asyncio
async def test_register_open_one_click_no_body(monkeypatch, allow_permission):
    """Registering without a body delegates with request=None and returns the envelope."""
    monkeypatch.setattr("mcpgateway.routers.catalog.settings.mcpgateway_catalog_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.routers.catalog.get_scoped_resource_access_context", MagicMock(return_value=("user@example.com", [])))
    mock_response = CatalogServerRegisterResponse(success=True, server_id="gw-1", message="Successfully registered X", error=None)
    mock_register = AsyncMock(return_value=mock_response)
    monkeypatch.setattr("mcpgateway.routers.catalog.catalog_service.register_catalog_server", mock_register)
    db = MagicMock()
    request = MagicMock(spec=Request)

    result = await register_catalog_server("asana", request, db=db, user={"email": "user@example.com", "db": db})

    assert result == mock_response
    assert mock_register.await_args.kwargs == {
        "catalog_id": "asana",
        "request": None,
        "db": db,
        "created_by": "user@example.com",
        "owner_email": "user@example.com",
        "token_teams": [],
    }


@pytest.mark.asyncio
async def test_register_with_api_key_builds_request(monkeypatch, allow_permission):
    """A body with overrides is mapped onto the service request with the path id."""
    monkeypatch.setattr("mcpgateway.routers.catalog.settings.mcpgateway_catalog_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.routers.catalog.get_scoped_resource_access_context", MagicMock(return_value=("user@example.com", [])))
    mock_register = AsyncMock(return_value=CatalogServerRegisterResponse(success=True, server_id="gw-1", message="Successfully registered Custom", error=None))
    monkeypatch.setattr("mcpgateway.routers.catalog.catalog_service.register_catalog_server", mock_register)
    db = MagicMock()
    request = MagicMock(spec=Request)

    await register_catalog_server(
        "asana",
        request,
        body=CatalogServerRegisterBody(name="Custom", api_key="sk-123"),  # pragma: allowlist secret
        db=db,
        user={"email": "user@example.com", "db": db},
    )

    service_request = mock_register.await_args.kwargs["request"]
    assert isinstance(service_request, CatalogServerRegisterRequest)
    assert service_request.server_id == "asana"
    assert service_request.name == "Custom"
    assert service_request.api_key == "sk-123"


@pytest.mark.asyncio
async def test_register_duplicate_returns_409(monkeypatch, allow_permission):
    """An already-registered catalog server maps to HTTP 409."""
    monkeypatch.setattr("mcpgateway.routers.catalog.settings.mcpgateway_catalog_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.routers.catalog.get_scoped_resource_access_context", MagicMock(return_value=("user@example.com", [])))
    mock_response = CatalogServerRegisterResponse(
        success=False,
        server_id="existing-id",
        message=CATALOG_REGISTER_ALREADY_REGISTERED_MSG,
        error="This server is already registered in the system",
    )
    monkeypatch.setattr("mcpgateway.routers.catalog.catalog_service.register_catalog_server", AsyncMock(return_value=mock_response))
    db = MagicMock()
    request = MagicMock(spec=Request)

    with pytest.raises(HTTPException) as exc_info:
        await register_catalog_server("asana", request, db=db, user={"email": "user@example.com", "db": db})

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Server already registered"


@pytest.mark.asyncio
async def test_register_unknown_id_returns_404(monkeypatch, allow_permission):
    """An unknown catalog id maps to HTTP 404."""
    monkeypatch.setattr("mcpgateway.routers.catalog.settings.mcpgateway_catalog_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.routers.catalog.get_scoped_resource_access_context", MagicMock(return_value=("user@example.com", [])))
    mock_response = CatalogServerRegisterResponse(
        success=False,
        server_id="",
        message=CATALOG_REGISTER_NOT_FOUND_MSG,
        error="Invalid catalog server ID",
    )
    monkeypatch.setattr("mcpgateway.routers.catalog.catalog_service.register_catalog_server", AsyncMock(return_value=mock_response))
    db = MagicMock()
    request = MagicMock(spec=Request)

    with pytest.raises(HTTPException) as exc_info:
        await register_catalog_server("asana", request, db=db, user={"email": "user@example.com", "db": db})

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Catalog server not found"


@pytest.mark.asyncio
async def test_register_failure_envelope_scrubs_error(monkeypatch, allow_permission):
    """Connectivity failures stay a 200 envelope but drop the raw exception text."""
    monkeypatch.setattr("mcpgateway.routers.catalog.settings.mcpgateway_catalog_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.routers.catalog.get_scoped_resource_access_context", MagicMock(return_value=("user@example.com", [])))
    mock_response = CatalogServerRegisterResponse(
        success=False,
        server_id="",
        message="Server is offline or unreachable",
        error="Traceback (most recent call last): ConnectionRefusedError: [Errno 61] Connection refused",
    )
    monkeypatch.setattr("mcpgateway.routers.catalog.catalog_service.register_catalog_server", AsyncMock(return_value=mock_response))
    db = MagicMock()
    request = MagicMock(spec=Request)

    result = await register_catalog_server("asana", request, db=db, user={"email": "user@example.com", "db": db})

    assert result.success is False
    assert result.message == "Server is offline or unreachable"
    assert result.error is None


@pytest.mark.asyncio
async def test_register_forwards_identity_and_team(monkeypatch, allow_permission):
    """The caller's identity and team are stamped onto the registered gateway."""
    monkeypatch.setattr("mcpgateway.routers.catalog.settings.mcpgateway_catalog_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.routers.catalog.get_scoped_resource_access_context", MagicMock(return_value=("user@example.com", ["team-a"])))
    mock_register = AsyncMock(return_value=CatalogServerRegisterResponse(success=True, server_id="gw-1", message="Successfully registered X", error=None))
    monkeypatch.setattr("mcpgateway.routers.catalog.catalog_service.register_catalog_server", mock_register)
    db = MagicMock()
    request = MagicMock(spec=Request)
    request.state.team_id = "team-a"

    await register_catalog_server("asana", request, db=db, user={"email": "user@example.com", "db": db, "token_teams": ["team-a"]})

    kwargs = mock_register.await_args.kwargs
    assert kwargs["created_by"] == "user@example.com"
    assert kwargs["owner_email"] == "user@example.com"
    assert kwargs["token_teams"] == ["team-a"]


@pytest.mark.asyncio
async def test_register_public_only_token_gets_no_team(monkeypatch, allow_permission):
    """A public-only token registers without a team even if request state carries one."""
    monkeypatch.setattr("mcpgateway.routers.catalog.settings.mcpgateway_catalog_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.routers.catalog.get_scoped_resource_access_context", MagicMock(return_value=("user@example.com", [])))
    mock_register = AsyncMock(return_value=CatalogServerRegisterResponse(success=True, server_id="gw-1", message="Successfully registered X", error=None))
    monkeypatch.setattr("mcpgateway.routers.catalog.catalog_service.register_catalog_server", mock_register)
    db = MagicMock()
    request = MagicMock(spec=Request)
    request.state.team_id = "team-a"

    await register_catalog_server("asana", request, db=db, user={"email": "user@example.com", "db": db, "token_teams": []})

    kwargs = mock_register.await_args.kwargs
    assert kwargs["owner_email"] == "user@example.com"
    assert kwargs["token_teams"] == []


def test_register_body_rejects_unsafe_name():
    """The register body validates the name override like other named resources."""
    with pytest.raises(pydantic.ValidationError):
        CatalogServerRegisterBody(name="<script>alert(1)</script>")


def test_register_body_rejects_oversized_api_key():
    """The register body caps api_key length."""
    with pytest.raises(pydantic.ValidationError):
        CatalogServerRegisterBody(api_key="x" * 5000)  # pragma: allowlist secret


def test_register_body_allows_empty_payload():
    """Both overrides are optional."""
    body = CatalogServerRegisterBody()

    assert body.name is None
    assert body.api_key is None


@pytest.mark.asyncio
async def test_register_permission_error_returns_403(monkeypatch, allow_permission):
    """A CatalogRegistrationPermissionError maps to HTTP 403."""
    monkeypatch.setattr("mcpgateway.routers.catalog.settings.mcpgateway_catalog_enabled", True, raising=False)
    monkeypatch.setattr("mcpgateway.routers.catalog.get_scoped_resource_access_context", MagicMock(return_value=("user@example.com", [])))
    monkeypatch.setattr("mcpgateway.routers.catalog.catalog_service.register_catalog_server", AsyncMock(side_effect=CatalogRegistrationPermissionError("denied")))
    db = MagicMock()
    request = MagicMock(spec=Request)

    with pytest.raises(HTTPException) as exc_info:
        await register_catalog_server("asana", request, db=db, user={"email": "user@example.com", "db": db})

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "denied"
