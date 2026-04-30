# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_rbac_decorator_coverage.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Static-source coverage checks for RBAC permission decorators.

These assertions guard against a specific regression mode: a refactor
silently dropping a ``@require_permission(...)`` decorator from an
endpoint. The code is analyzed as source text rather than imported,
so the test runs without standing up the FastAPI app.

Paired with runtime auth tests (``tests/security/``) which verify the
decorators actually deny in the expected scenarios — this file only
verifies the decorators are *present*.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


MAIN_PERMISSIONS = [
    "servers.read",
    "servers.create",
    "servers.update",
    "servers.delete",
    "servers.use",
    "tools.read",
    "tools.create",
    "tools.update",
    "tools.delete",
    "tools.execute",
    "resources.read",
    "resources.create",
    "resources.update",
    "resources.delete",
    "prompts.read",
    "prompts.create",
    "prompts.update",
    "prompts.delete",
    "gateways.read",
    "gateways.create",
    "gateways.update",
    "gateways.delete",
    "a2a.read",
    "a2a.create",
    "a2a.update",
    "a2a.delete",
    "a2a.invoke",
    "admin.system_config",
    "admin.metrics",
    "admin.export",
    "admin.import",
    "tags.read",
]

ROUTER_PERMISSIONS = [
    ("mcpgateway/routers/teams.py", "teams.create"),
    ("mcpgateway/routers/teams.py", "teams.read"),
    ("mcpgateway/routers/teams.py", "teams.update"),
    ("mcpgateway/routers/teams.py", "teams.delete"),
    ("mcpgateway/routers/teams.py", "teams.manage_members"),
    ("mcpgateway/routers/tokens.py", "tokens.create"),
    ("mcpgateway/routers/tokens.py", "tokens.read"),
    ("mcpgateway/routers/tokens.py", "tokens.update"),
    ("mcpgateway/routers/tokens.py", "tokens.revoke"),
    ("mcpgateway/routers/email_auth.py", "admin.user_management"),
    ("mcpgateway/routers/sso.py", "admin.sso_providers:create"),
    ("mcpgateway/routers/sso.py", "admin.sso_providers:read"),
    ("mcpgateway/routers/sso.py", "admin.sso_providers:update"),
    ("mcpgateway/routers/sso.py", "admin.sso_providers:delete"),
    ("mcpgateway/routers/sso.py", "admin.user_management"),
    ("mcpgateway/routers/llm_config_router.py", "admin.system_config"),
    ("mcpgateway/routers/llm_admin_router.py", "admin.system_config"),
    ("mcpgateway/routers/llm_proxy_router.py", "llm.read"),
    ("mcpgateway/routers/llm_proxy_router.py", "llm.invoke"),
    ("mcpgateway/routers/observability.py", "admin.system_config"),
    ("mcpgateway/routers/log_search.py", "logs:read"),
    ("mcpgateway/routers/log_search.py", "security:read"),
    ("mcpgateway/routers/log_search.py", "audit:read"),
    ("mcpgateway/routers/log_search.py", "metrics:read"),
    ("mcpgateway/routers/toolops_router.py", "admin.system_config"),
    ("mcpgateway/routers/cancellation_router.py", "admin.system_config"),
]


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _has_require_permission(source: str, permission: str) -> bool:
    return f'@require_permission("{permission}"' in source or f"@require_permission('{permission}'" in source


@pytest.mark.parametrize("permission", MAIN_PERMISSIONS)
def test_main_has_require_permission(permission: str) -> None:
    assert _has_require_permission(_read("mcpgateway/main.py"), permission), f'main.py: missing @require_permission("{permission}")'


def test_main_has_minimum_require_permission_count() -> None:
    count = _read("mcpgateway/main.py").count("@require_permission(")
    assert count >= 30, f"main.py: only {count} @require_permission decorators (expected >=30)"


@pytest.mark.parametrize("rel_path,permission", ROUTER_PERMISSIONS)
def test_router_has_require_permission(rel_path: str, permission: str) -> None:
    assert _has_require_permission(_read(rel_path), permission), f'{rel_path}: missing @require_permission("{permission}")'


def test_rbac_router_uses_admin_permission_decorator() -> None:
    source = _read("mcpgateway/routers/rbac.py")
    assert "@require_admin_permission()" in source
    assert '"admin.user_management"' in source
    assert '"admin.security_audit"' in source


def test_admin_py_never_allows_admin_bypass() -> None:
    source = _read("mcpgateway/admin.py")
    bypass_true = source.count("allow_admin_bypass=True")
    bypass_false = source.count("allow_admin_bypass=False")
    assert bypass_true == 0, f"admin.py: {bypass_true} endpoints with allow_admin_bypass=True (should be 0)"
    assert bypass_false >= 20, f"admin.py: only {bypass_false} endpoints with allow_admin_bypass=False (expected >=20)"
