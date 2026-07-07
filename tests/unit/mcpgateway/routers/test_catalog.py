"""Unit tests for the v1 catalog API router."""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import APIRouter, HTTPException, Request
import pytest

# First-Party
from mcpgateway.api.v1 import build_legacy_router, build_v1_router
from mcpgateway.config import settings
from mcpgateway.routers.catalog import list_catalog_servers
from mcpgateway.schemas import CatalogListResponse
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
    assert "/v1/catalog/" in v1_paths
    assert "/catalog" not in legacy_paths
    assert "/catalog/" not in legacy_paths
