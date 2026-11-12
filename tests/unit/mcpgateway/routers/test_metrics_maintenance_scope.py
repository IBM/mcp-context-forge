# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_metrics_maintenance_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope enforcement for the metrics maintenance router (issue #6134).

This router guards at router level, so the guard is a dependency rather than
a decorator and carries no ``__mcpgateway_scope_class__`` marker.
"""

# Third-Party
from fastapi import Request
from fastapi.testclient import TestClient

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.routers.metrics_maintenance import router
from mcpgateway.utils.verify_credentials import require_admin_auth


def _dependency_names():
    """Return the names of the router-level dependency callables.

    Returns:
        list[str]: One name per dependency on the router.
    """
    return [getattr(getattr(dep, "dependency", None), "__name__", "") for dep in (router.dependencies or [])]


def test_router_carries_the_global_scope_dependency():
    """The scope guard must be mounted router-wide, covering all four routes."""
    assert "require_global_admin_scope_dep" in _dependency_names()


def test_existing_admin_auth_dependency_is_preserved():
    """The new guard is additive; it must not displace authentication."""
    assert "require_admin_auth" in _dependency_names()


def test_all_four_routes_are_covered():
    """Every endpoint on this router inherits the router-level guard."""
    paths = sorted({route.path for route in router.routes})
    assert paths == ["/api/metrics/cleanup", "/api/metrics/config", "/api/metrics/rollup", "/api/metrics/stats"]


def test_narrowed_admin_token_is_denied_by_the_real_dependency(app):
    """Drive a narrowed admin token through the real router-mounted dependency.

    Only ``require_admin_auth`` is overridden (authentication bypass); the
    Layer-1 ``require_global_admin_scope_dep`` guard runs for real, so this
    proves the dependency form denies narrowed tokens end-to-end rather than
    only asserting it is mounted (issue #6183 review).
    """

    def _narrowed_user(request: Request):
        request.state.token_teams = ["team-a"]
        return {"email": settings.platform_admin_email, "is_admin": True, "db": None}

    app.dependency_overrides[require_admin_auth] = lambda: settings.platform_admin_email
    app.dependency_overrides[get_current_user_with_permissions] = _narrowed_user
    client = TestClient(app)
    try:
        response = client.get("/api/metrics/config")
    finally:
        app.dependency_overrides.pop(require_admin_auth, None)
        app.dependency_overrides.pop(get_current_user_with_permissions, None)

    assert response.status_code == 403
    assert "unrestricted platform-admin token" in response.json()["detail"]


def test_unrestricted_admin_token_passes_the_real_dependency(app):
    """The same real dependency must let an unrestricted admin token through."""

    def _unrestricted_user(request: Request):
        request.state.token_teams = None
        return {"email": settings.platform_admin_email, "is_admin": True, "db": None}

    app.dependency_overrides[require_admin_auth] = lambda: settings.platform_admin_email
    app.dependency_overrides[get_current_user_with_permissions] = _unrestricted_user
    client = TestClient(app)
    try:
        response = client.get("/api/metrics/config")
    finally:
        app.dependency_overrides.pop(require_admin_auth, None)
        app.dependency_overrides.pop(get_current_user_with_permissions, None)

    assert response.status_code == 200
