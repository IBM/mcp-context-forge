# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_rbac_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope behavior in the RBAC role handler bodies.

Imported WITHOUT patch_rbac_decorators so handler-body logic runs for real.
Decorator behaviour itself is covered by
tests/unit/mcpgateway/middleware/test_global_scope_helpers.py, and the fact that
specific routes carry the guard is covered by
tests/unit/mcpgateway/test_global_record_scope.py.
"""

# Standard
import importlib
import sys

# `test_rbac_router.py` (and any other suite using patch_rbac_decorators) imports
# this same module while `mcpgateway.middleware.rbac.require_global_admin_permission`
# is monkeypatched to a no-op. Because Python caches modules in sys.modules, if that
# import happens first in the test session (e.g. collected alphabetically ahead of
# this file), `create_role`/`update_role`/`delete_role` end up permanently decorated
# with the mock — restoring the patched attribute afterwards can't retroactively
# re-decorate functions already bound at import time. Drop any cached entry and
# re-import so this file always exercises freshly-applied, real decorators,
# regardless of collection order. This intentionally does NOT reuse
# `importlib.reload`, which would mutate the *same* module object other test
# files (e.g. test_rbac_router.py) already hold a reference to and corrupt their
# mocked state; popping + re-importing rebinds `sys.modules` to a brand new
# module object instead, leaving any existing references untouched.
sys.modules.pop("mcpgateway.routers.rbac", None)

# First-Party
rbac_router = importlib.import_module("mcpgateway.routers.rbac")


def test_module_imports_with_real_decorators():
    """Guard against this file accidentally being imported under the mocks."""
    assert rbac_router.create_role.__mcpgateway_scope_class__ == "global_only"
    assert rbac_router.update_role.__mcpgateway_scope_class__ == "global_only"
    assert rbac_router.delete_role.__mcpgateway_scope_class__ == "global_only"
