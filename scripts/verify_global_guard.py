# -*- coding: utf-8 -*-
"""Location: ./scripts/verify_global_guard.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Report migration progress for issue #6134.

Prints, per router, which permission-guarded endpoints still lack the stacked
``@require_global_admin_permission()`` decorator or a ``request`` kwarg.
Exits non-zero while any remain.
"""

# Standard
import ast
import pathlib
import sys

ROUTERS = [
    "llm_config_router.py",
    "llm_admin_router.py",
    "observability.py",
    "sso.py",
    "siem.py",
    "log_search.py",
    "runtime_admin_router.py",
    "toolops_router.py",
    "rbac.py",
]
# rbac.py holds seven guarded endpoints; only these two are in GLOBAL_ONLY_DEFERRED.
# The rest were migrated by #6132 and must not be touched here.
RBAC_IN_SCOPE = {"check_permission", "get_user_permissions"}
USER_KWARGS = {"user", "_user", "current_user", "current_user_ctx"}


def audit():
    """Yield (router, function, line, has_guard, has_request, user_kwarg) for in-scope endpoints.

    Yields:
        tuple: One row per permission-guarded, in-scope endpoint.
    """
    for fname in ROUTERS:
        path = pathlib.Path("mcpgateway/routers") / fname
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = [ast.unparse(d) for d in node.decorator_list]
            if not any(d.startswith(("require_permission(", "require_any_permission(")) for d in decorators):
                continue
            if fname == "rbac.py" and node.name not in RBAC_IN_SCOPE:
                continue
            args = [a.arg for a in node.args.args + node.args.kwonlyargs]
            user_kwarg = next((a for a in args if a in USER_KWARGS), None)
            has_guard = any(d.startswith("require_global_admin_permission(") for d in decorators)
            yield fname, node.name, node.lineno, has_guard, "request" in args, user_kwarg


def main() -> int:
    """Print the audit table and return a process exit code.

    Returns:
        int: 0 when every in-scope endpoint is fully migrated, 1 otherwise.
    """
    rows = list(audit())
    missing_guard = [r for r in rows if not r[3]]
    missing_request = [r for r in rows if not r[4]]
    missing_user = [r for r in rows if r[5] is None]

    print(f"in-scope endpoints: {len(rows)} (expected 60)")
    print(f"missing @require_global_admin_permission(): {len(missing_guard)}")
    print(f"missing request kwarg:                     {len(missing_request)}")
    print(f"missing user kwarg (must always be 0):     {len(missing_user)}")

    for label, group in (("NO GUARD", missing_guard), ("NO REQUEST", missing_request), ("NO USER KWARG", missing_user)):
        for router, fn, line, _guard, _req, _user in group:
            print(f"  {label:<14} {router}:{line} {fn}")

    return 0 if not (missing_guard or missing_request or missing_user) else 1


if __name__ == "__main__":
    sys.exit(main())
