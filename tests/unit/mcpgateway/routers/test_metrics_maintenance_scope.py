# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_metrics_maintenance_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope enforcement for the metrics maintenance router (issue #6134).

This router guards at router level, so the guard is a dependency rather than
a decorator and carries no ``__mcpgateway_scope_class__`` marker.
"""

# First-Party
from mcpgateway.routers.metrics_maintenance import router


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
