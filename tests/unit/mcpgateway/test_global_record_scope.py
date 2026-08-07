# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_global_record_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Drift guard for admin routes over global records.

Every admin route that manages a record with no team association must appear in
exactly one manifest below. See
docs/superpowers/specs/2026-08-06-global-record-admin-scope-design.md Appendix A
and docs/docs/manage/rbac.md.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.main import app
from tests.helpers.router_helpers import collect_routes

# Paths below are the UNVERSIONED form. Every sub-router is mounted twice — under
# /v1 and unversioned — so _normalize() strips the /v1 prefix before lookup and a
# single entry covers both mounts.

# Migrated to the canonical rule by this change.
GLOBAL_ONLY = {
    ("GET", "/compliance/frameworks"),
    ("POST", "/compliance/reports"),
    ("GET", "/compliance/reports"),
    ("GET", "/compliance/reports/{report_id}"),
    ("GET", "/compliance/reports/{report_id}/export"),
    ("POST", "/rbac/roles"),
    ("PUT", "/rbac/roles/{role_id}"),
    ("DELETE", "/rbac/roles/{role_id}"),
}

# Same class, guard NOT yet migrated — spec Appendix A.2 and A.4, follow-up issue 1.
# This set may only shrink. Adding a new route here to dodge the guard assertion
# is exactly what test_deferred_bucket_only_shrinks prevents.
# Populated from the mounted app with every optional router flag enabled (see
# task-9-report.md); 64 entries, matching spec Appendix A.2 (60) + A.4 (4).
GLOBAL_ONLY_DEFERRED = {
    # --- llm_config_router (prefix /llm) — 13, admin.system_config ---
    ("GET", "/llm/models"),
    ("POST", "/llm/models"),
    ("DELETE", "/llm/models/{model_id}"),
    ("GET", "/llm/models/{model_id}"),
    ("PATCH", "/llm/models/{model_id}"),
    ("POST", "/llm/models/{model_id}/state"),
    ("GET", "/llm/providers"),
    ("POST", "/llm/providers"),
    ("DELETE", "/llm/providers/{provider_id}"),
    ("GET", "/llm/providers/{provider_id}"),
    ("PATCH", "/llm/providers/{provider_id}"),
    ("POST", "/llm/providers/{provider_id}/health"),
    ("POST", "/llm/providers/{provider_id}/state"),
    # --- llm_admin_router (prefix /admin/llm) — 13, admin.system_config ---
    ("GET", "/admin/llm/api-info/html"),
    ("GET", "/admin/llm/models/html"),
    ("DELETE", "/admin/llm/models/{model_id}"),
    ("POST", "/admin/llm/models/{model_id}/state"),
    ("GET", "/admin/llm/provider-configs"),
    ("GET", "/admin/llm/provider-defaults"),
    ("GET", "/admin/llm/providers/html"),
    ("DELETE", "/admin/llm/providers/{provider_id}"),
    ("POST", "/admin/llm/providers/{provider_id}/fetch-models"),
    ("POST", "/admin/llm/providers/{provider_id}/health"),
    ("POST", "/admin/llm/providers/{provider_id}/state"),
    ("POST", "/admin/llm/providers/{provider_id}/sync-models"),
    ("POST", "/admin/llm/test"),
    # --- observability (prefix /observability) — 8, admin.system_config ---
    ("GET", "/observability/analytics/query-performance"),
    ("GET", "/observability/spans"),
    ("GET", "/observability/stats"),
    ("GET", "/observability/traces"),
    ("DELETE", "/observability/traces/cleanup"),
    ("POST", "/observability/traces/export"),
    ("POST", "/observability/traces/query"),
    ("GET", "/observability/traces/{trace_id}"),
    # --- sso (prefix /auth/sso) — 7, admin.sso_providers:*/admin.user_management ---
    ("GET", "/auth/sso/admin/providers"),
    ("POST", "/auth/sso/admin/providers"),
    ("DELETE", "/auth/sso/admin/providers/{provider_id}"),
    ("GET", "/auth/sso/admin/providers/{provider_id}"),
    ("PUT", "/auth/sso/admin/providers/{provider_id}"),
    ("GET", "/auth/sso/pending-approvals"),
    ("POST", "/auth/sso/pending-approvals/{approval_id}/action"),
    # --- siem (prefix /admin/siem) — 5, admin.security_audit ---
    ("GET", "/admin/siem/destinations"),
    ("POST", "/admin/siem/destinations"),
    ("PUT", "/admin/siem/destinations"),
    ("GET", "/admin/siem/health"),
    ("POST", "/admin/siem/test/{destination_name}"),
    # --- log_search (prefix /api/logs) — 5, logs:read/security:read/audit:read/metrics:read ---
    ("GET", "/api/logs/audit-trails"),
    ("GET", "/api/logs/performance-metrics"),
    ("POST", "/api/logs/search"),
    ("GET", "/api/logs/security-events"),
    ("GET", "/api/logs/trace/{correlation_id}"),
    # --- runtime_admin_router (prefix /admin/runtime) — 4, admin.system_config ---
    ("GET", "/admin/runtime/a2a-mode"),
    ("PATCH", "/admin/runtime/a2a-mode"),
    ("GET", "/admin/runtime/mcp-mode"),
    ("PATCH", "/admin/runtime/mcp-mode"),
    # --- toolops_router (prefix /toolops) — 3, admin.system_config ---
    ("POST", "/toolops/enrichment/enrich_tool"),
    ("POST", "/toolops/validation/execute_tool_nl_testcases"),
    ("POST", "/toolops/validation/generate_testcases"),
    # --- rbac (prefix /rbac) — 2, admin.security_audit — permission introspection ---
    ("POST", "/rbac/permissions/check"),
    ("GET", "/rbac/permissions/user/{user_email}"),
    # --- metrics_maintenance (Appendix A.4) — 4, router-level require_admin_auth ---
    ("POST", "/api/metrics/cleanup"),
    ("POST", "/api/metrics/rollup"),
    ("GET", "/api/metrics/stats"),
    ("GET", "/api/metrics/config"),
}

# Global records read with Layer-1 filtering instead of a hard deny — spec §3.4.
FILTERED_READ = {
    ("GET", "/rbac/roles"),
    ("GET", "/rbac/roles/{role_id}"),
}

# Records carrying a team association via UserRole.scope_id — spec §3.5.
# GET /rbac/users/{user_email}/roles is not in spec Appendix A.1's table (which
# lists only the POST and DELETE siblings), but it carries the identical
# require_permission("admin.user_management") guard and reads the same
# UserRole.scope_id-bearing record — the appendix's audit missed it. Added here
# and flagged in the Task 9 commit rather than silently dropped.
TEAM_SCOPABLE = {
    ("GET", "/rbac/users/{user_email}/roles"),
    ("POST", "/rbac/users/{user_email}/roles"),
    ("DELETE", "/rbac/users/{user_email}/roles/{role_id}"),
}

# Documented non-admin surfaces — spec Appendix A.3.
EXEMPT = {
    ("GET", "/auth/sso/providers"): "Login-page provider list; must be reachable pre-authentication",
    ("GET", "/auth/sso/login/{provider_id}"): "SSO initiation; pre-authentication by definition",
    ("GET", "/auth/sso/callback/{provider_id}"): "SSO callback; authenticated by the IdP handshake",
    ("GET", "/rbac/permissions/available"): "Static permission catalogue; no record data",
    ("GET", "/rbac/my/roles"): "Self-scoped — the caller's own assignments only",
    ("GET", "/rbac/my/permissions"): "Self-scoped — the caller's own permissions only",
    # Spec Appendix A.3 lists this as "/gateway/models", the router-local path
    # before llm_config_router's include-time prefix; the final mounted path is
    # /llm/gateway/models (mcpgateway/routers/llm_config_router.py:597) and the
    # appendix's own rule ("manifests key on the final mounted path") requires
    # the prefixed form here.
    ("GET", "/llm/gateway/models"): "Feeds the LLM Chat model selector; authenticated but deliberately not admin-scoped",
}


def _normalize(path: str) -> str:
    """Strip the /v1 mount prefix so one manifest entry covers both mounts.

    Every sub-router is assembled twice — under /v1 by build_v1_router and
    unversioned by build_legacy_router (mcpgateway/api/v1/__init__.py).

    Args:
        path: Fully-qualified route path.

    Returns:
        str: The unversioned form of the path.
    """
    return path[3:] if path.startswith("/v1/") else path


def _routes():
    """Yield (method, unversioned_path, route, include_deps) for every leaf route.

    Uses collect_routes because app.routes holds lazy _IncludedRouter wrappers on
    FastAPI 0.137+, not leaf routes — iterating it directly makes these tests
    vacuous.

    Yields:
        tuple: ``(method, path, route, include_deps)`` per HTTP method served.
    """
    for full_path, route, include_deps in collect_routes(app):
        for method in sorted((getattr(route, "methods", set()) or set()) - {"HEAD", "OPTIONS"}):
            yield method, _normalize(full_path), route, include_deps


def _scope_class(route):
    """Return the scope-class marker set by require_global_admin_permission.

    Args:
        route: A leaf route.

    Returns:
        Optional[str]: The marker, or ``None`` when the guard is absent.
    """
    return getattr(getattr(route, "endpoint", None), "__mcpgateway_scope_class__", None)


def _has_admin_guard(route, include_deps) -> bool:
    """Whether a route is admin-guarded by decorator or by an enclosing dependency.

    ``enforce_admin_csrf`` (mcpgateway/admin.py) is a CSRF check applied
    router-wide to the entire Admin UI, not an authorization guard — spec
    Appendix A.4 makes this distinction explicitly for the identical pattern
    on the siem router ("it is enforce_admin_csrf, not authentication"). It is
    excluded here by name so it isn't mistaken for a global-record admin
    guard. Without this exclusion, any test session where another test file's
    session-scoped ``main_app_with_admin_api`` fixture has already mounted
    ``admin_router`` onto the shared ``main.app`` (its per-route CSRF
    dependency name also matches the substring "admin") would flood this
    assertion with hundreds of unrelated, mostly team-scoped Admin UI routes
    (``/admin/tools``, ``/admin/teams``, etc.) that are out of scope for this
    guard.

    Args:
        route: A leaf route.
        include_deps: Dependencies accumulated from enclosing routers.

    Returns:
        bool: ``True`` when any admin guard applies.
    """
    if _scope_class(route) is not None:
        return True
    deps = list(getattr(route, "dependencies", []) or []) + list(include_deps or [])
    for dep in deps:
        if getattr(getattr(dep, "dependency", None), "__name__", "") == "enforce_admin_csrf":
            continue
        if "admin" in repr(dep).lower():
            return True
    return False


def test_collect_routes_actually_finds_routes():
    """Canary: if this returns almost nothing, every other test here is vacuous."""
    assert len(list(_routes())) > 100, "collect_routes found almost no routes — the drift guard is not actually inspecting the app"


def test_global_only_routes_carry_the_guard():
    """Every migrated route must actually carry the decorator, not just be listed."""
    seen = {(m, p) for m, p, _route, _deps in _routes()}
    missing = {(m, p) for m, p, route, _deps in _routes() if (m, p) in GLOBAL_ONLY and _scope_class(route) != "global_only"}
    assert not missing, f"GLOBAL_ONLY routes missing @require_global_admin_permission: {sorted(missing)}\nSee docs/docs/manage/rbac.md"
    # A manifest entry that matches no mounted route is stale, not passing.
    stale = {entry for entry in GLOBAL_ONLY if entry not in seen and not entry[1].startswith("/compliance")}
    assert not stale, f"GLOBAL_ONLY entries match no mounted route: {sorted(stale)}"


@pytest.mark.skipif(not settings.mcpgateway_admin_api_enabled, reason="compliance router is only mounted when MCPGATEWAY_ADMIN_API_ENABLED is true")
def test_compliance_routes_are_mounted_and_guarded():
    """Compliance mounting is flag-gated; assert it explicitly rather than skipping silently."""
    seen = {(m, p) for m, p, _route, _deps in _routes()}
    expected = {entry for entry in GLOBAL_ONLY if entry[1].startswith("/compliance")}
    assert expected <= seen, f"Compliance routes missing from the app: {sorted(expected - seen)}"


def test_manifests_are_disjoint():
    """A route must not be silently reclassified by appearing in two buckets."""
    buckets = [GLOBAL_ONLY, GLOBAL_ONLY_DEFERRED, FILTERED_READ, TEAM_SCOPABLE, set(EXEMPT)]
    seen = set()
    for bucket in buckets:
        overlap = seen & bucket
        assert not overlap, f"Route classified twice: {sorted(overlap)}"
        seen |= bucket


def test_deferred_bucket_only_shrinks():
    """Deferral records existing debt; it is not an escape hatch for new routes."""
    assert len(GLOBAL_ONLY_DEFERRED) <= 64, "GLOBAL_ONLY_DEFERRED grew. New global-record routes must use the canonical rule, not join the deferred set. See docs/docs/manage/rbac.md"


def test_every_admin_route_is_classified():
    """No admin route over a global record may be left unclassified."""
    classified = GLOBAL_ONLY | GLOBAL_ONLY_DEFERRED | FILTERED_READ | TEAM_SCOPABLE | set(EXEMPT)
    unclassified = {(m, p) for m, p, route, deps in _routes() if (m, p) not in classified and _has_admin_guard(route, deps)}
    assert not unclassified, f"Unclassified admin routes: {sorted(unclassified)}\nClassify each in tests/unit/mcpgateway/test_global_record_scope.py per docs/docs/manage/rbac.md"
