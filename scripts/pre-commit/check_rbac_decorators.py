#!/usr/bin/env python3
"""Pre-commit hook: verify RBAC permission decorators and admin bypass settings.

Checks that:
- All expected permissions appear in ``@require_permission`` decorators in main.py and routers
- RBAC router uses ``@require_admin_permission()`` and expected permission strings
- admin.py uses ``allow_admin_bypass=False`` on all endpoints (never True)
- main.py has a minimum count of ``@require_permission`` decorators

Exit codes:
    0 - all checks pass
    1 - violations detected (printed to stderr)
"""

from __future__ import annotations

import sys
from pathlib import Path

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


def _read(rel_path: str) -> str | None:
    path = REPO_ROOT / rel_path
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _has_require_permission(source: str, permission: str) -> bool:
    return f'@require_permission("{permission}"' in source or f"@require_permission('{permission}'" in source


def main() -> int:
    violations: list[str] = []

    # --- main.py permissions ---
    main_source = _read("mcpgateway/main.py")
    if main_source is None:
        violations.append("mcpgateway/main.py: file not found")
    else:
        for perm in MAIN_PERMISSIONS:
            if not _has_require_permission(main_source, perm):
                violations.append(f'main.py: missing @require_permission("{perm}")')

        require_perm_count = main_source.count("@require_permission(")
        if require_perm_count < 30:
            violations.append(f"main.py: only {require_perm_count} @require_permission decorators (expected >30)")

    # --- Router permissions ---
    _source_cache: dict[str, str] = {}
    for rel_path, perm in ROUTER_PERMISSIONS:
        if rel_path not in _source_cache:
            source = _read(rel_path)
            if source is None:
                violations.append(f"{rel_path}: file not found")
                _source_cache[rel_path] = ""
                continue
            _source_cache[rel_path] = source
        source = _source_cache[rel_path]
        if source and not _has_require_permission(source, perm):
            violations.append(f'{rel_path}: missing @require_permission("{perm}")')

    # --- RBAC router specific checks ---
    rbac_source = _read("mcpgateway/routers/rbac.py") or ""
    if rbac_source:
        if "@require_admin_permission()" not in rbac_source:
            violations.append("rbac.py: missing @require_admin_permission()")
        if '"admin.user_management"' not in rbac_source:
            violations.append('rbac.py: missing "admin.user_management" permission')
        if '"admin.security_audit"' not in rbac_source:
            violations.append('rbac.py: missing "admin.security_audit" permission')

    # --- admin.py bypass checks ---
    admin_source = _read("mcpgateway/admin.py") or ""
    if admin_source:
        bypass_true = admin_source.count("allow_admin_bypass=True")
        bypass_false = admin_source.count("allow_admin_bypass=False")
        if bypass_true > 0:
            violations.append(f"admin.py: has {bypass_true} endpoints with allow_admin_bypass=True (should be 0)")
        if bypass_false < 20:
            violations.append(f"admin.py: only {bypass_false} endpoints with allow_admin_bypass=False (expected >20)")

    if violations:
        print("RBAC decorator policy violations:", file=sys.stderr)
        for v in sorted(violations):
            print(f"  {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
