# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_plugins.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for versioned plugin discovery API.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import APIRouter, HTTPException, Request
import pytest

# First-Party
from mcpgateway.api.v1 import build_legacy_router, build_v1_router
from mcpgateway.config import settings
from mcpgateway.routers.plugins import list_plugins
from tests.helpers.router_helpers import collect_routes


@pytest.fixture
def permission_service(monkeypatch):
    """Stub RBAC and plugin permission hooks."""
    service = MagicMock()
    service.check_permission = AsyncMock(return_value=True)
    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", lambda db: service)
    monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))
    return service


def _request() -> Request:
    """Build request with application state."""
    app = MagicMock()
    return Request({"type": "http", "method": "GET", "path": "/v1/plugins", "headers": [], "app": app})


def _empty_router_kwargs() -> dict[str, APIRouter]:
    """Return required empty inline routers."""
    return {
        name: APIRouter()
        for name in (
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
        )
    }


@pytest.mark.asyncio
async def test_list_plugins_requires_authenticated_user():
    """Missing user context returns 401."""
    with pytest.raises(HTTPException) as exc_info:
        await list_plugins(_request(), db=MagicMock())

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_list_plugins_rejects_missing_permission(permission_service):
    """Authenticated caller without plugins.read receives 403."""
    permission_service.check_permission.return_value = False
    db = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await list_plugins(_request(), db=db, user={"email": "reader@example.com", "db": db})

    assert exc_info.value.status_code == 403
    assert permission_service.check_permission.await_args.kwargs["permission"] == "plugins.read"


@pytest.mark.asyncio
async def test_list_plugins_filters_and_redacts_config(monkeypatch, permission_service):
    """Filtered plugin response never exposes configuration values."""
    service = MagicMock()
    service.search_plugins.return_value = [
        {
            "name": "SecurityPlugin",
            "description": "Security checks",
            "author": "ContextForge",
            "version": "1.0.0",
            "mode": "enforce",
            "priority": 10,
            "hooks": ["tool_pre_invoke"],
            "tags": ["security"],
            "status": "enabled",
            "config_summary": {"api_key": "must-not-leak"},  # pragma: allowlist secret
        }
    ]
    monkeypatch.setattr("mcpgateway.routers.plugins.get_plugin_service", lambda: service)
    monkeypatch.setattr("mcpgateway.routers.plugins.sync_plugin_service_from_runtime", AsyncMock())
    monkeypatch.setattr("mcpgateway.routers.plugins.are_plugins_enabled_shared", AsyncMock(return_value=True))
    db = MagicMock()

    response = await list_plugins(
        _request(),
        search="security",
        mode="enforce",
        hook="tool_pre_invoke",
        tag="security",
        db=db,
        user={"email": "reader@example.com", "db": db},
    )

    service.search_plugins.assert_called_once_with(query="security", mode="enforce", hook="tool_pre_invoke", tag="security")
    assert response.plugins[0].config_summary == {}
    assert response.total == 1
    assert response.enabled_count == 1
    assert response.disabled_count == 0


@pytest.mark.asyncio
async def test_list_plugins_disabled_returns_empty(monkeypatch, permission_service):
    """Disabled plugin subsystem returns explicit disabled state and empty list."""
    service = MagicMock()
    service.get_all_plugins.return_value = []
    monkeypatch.setattr("mcpgateway.routers.plugins.get_plugin_service", lambda: service)
    monkeypatch.setattr("mcpgateway.routers.plugins.sync_plugin_service_from_runtime", AsyncMock())
    monkeypatch.setattr("mcpgateway.routers.plugins.are_plugins_enabled_shared", AsyncMock(return_value=False))
    db = MagicMock()

    response = await list_plugins(_request(), db=db, user={"email": "reader@example.com", "db": db})

    assert response.plugins_globally_enabled is False
    assert response.plugins == []
    assert response.total == 0


@pytest.mark.asyncio
async def test_list_plugins_get_all_failure_returns_500(monkeypatch, permission_service):
    """Plugin service failures return a sanitized server error."""
    service = MagicMock()
    service.get_all_plugins.side_effect = RuntimeError("catalog unavailable")
    logger = MagicMock()
    monkeypatch.setattr("mcpgateway.routers.plugins.get_plugin_service", lambda: service)
    monkeypatch.setattr("mcpgateway.routers.plugins.sync_plugin_service_from_runtime", AsyncMock())
    monkeypatch.setattr("mcpgateway.routers.plugins.logger", logger)
    db = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await list_plugins(_request(), db=db, user={"email": "reader@example.com", "db": db})

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to list plugins"
    logger.exception.assert_called_once_with("Failed to list plugins")


def test_plugins_router_is_v1_only():
    """Plugin discovery has no unversioned legacy alias."""
    v1_paths = [path for path, *_ in collect_routes(build_v1_router(settings, **_empty_router_kwargs()))]
    legacy_paths = [path for path, *_ in collect_routes(build_legacy_router(settings, **_empty_router_kwargs()))]

    assert "/v1/plugins" in v1_paths
    assert "/plugins" not in legacy_paths
