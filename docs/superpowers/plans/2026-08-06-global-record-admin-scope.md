# Global-Record Admin Scope Standardization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish one canonical scope rule for admin-only routes that manage records with no team association, apply it to the four rule-divergent surfaces, and add a drift guard so new global-record endpoints cannot land unclassified.

**Architecture:** Two shared helpers in `mcpgateway/middleware/rbac.py` — a raise-form function for conditional call sites and a decorator for whole-endpoint guards — both delegating to the existing `is_unrestricted_platform_admin()` predicate in `auth_context.py`. Route handlers stop reimplementing the check. A manifest-driven test walks `app.routes` and fails when an admin route is unclassified or a `GLOBAL_ONLY` route loses its guard.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy (sync sessions), pytest + pytest-asyncio, Ruff (line length 200).

**Spec:** `docs/superpowers/specs/2026-08-06-global-record-admin-scope-design.md`
**Issue:** [IBM/mcp-context-forge#5982](https://github.com/IBM/mcp-context-forge/issues/5982)

**This plan delivers the issue partially, by design.** It applies the canonical rule to 13 of the 77 admin routes over global records, and establishes the rule, the shared helpers and the drift guard. Two of the issue's five acceptance criteria — shared-helper reuse and per-context deny tests — remain partial, because 64 routes with equivalent behaviour keep their existing guards until follow-up issue 1 (Task 12). **#5982 must not be closed when this merges.**

## Global Constraints

- **Python >= 3.11**, type hints required, strict mypy.
- **Formatting:** Ruff, line length 200. Run `make pre-commit` after writing code.
- **Docstrings:** every public function needs one; `make interrogate` enforces 100% coverage. Include an `Args:`/`Returns:`/`Raises:` block.
- **Imports:** isort sections — stdlib, third-party, first-party `mcpgateway`, local. First-party imports inside functions must carry `# pylint: disable=import-outside-toplevel` and a `# First-Party` comment, matching the existing style in `middleware/rbac.py:512`.
- **Commits:** sign every commit with `git commit -s` (DCO). Conventional Commits prefixes (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`).
- **Never mention AI assistants** in commits, PRs, or code comments.
- **Do not push** until explicitly asked.
- **Do not pass `db=db` to `AuditTrailService.log_action()`** — see CLAUDE.md; not directly touched here but easy to trip over in `admin.py`.
- **Synchronous SQLAlchemy inside async handlers is deliberate.** Do not convert call sites to async.
- **`_ACCESS_DENIED_MSG`** (`middleware/rbac.py:48`) is intentionally vague to avoid leaking permission names. The new global-scope message adds *token-shape* remediation only — never a permission name, never whether a record exists.

## Route counts this plan touches

13 routes changed + 26 root call sites refactored. 64 routes are classified but deliberately **not** changed (spec Appendix A.2/A.4, follow-up issue 1). 7 routes are exempt (A.3).

---

### Task 1: Shared scope helpers in `middleware/rbac.py`

**Files:**
- Modify: `mcpgateway/middleware/rbac.py` (add after `require_admin_permission()`, which ends at line 1030)
- Test: `tests/unit/mcpgateway/middleware/test_global_scope_helpers.py` (create)

**Interfaces:**
- Consumes: `is_unrestricted_platform_admin(request, user, db) -> bool` from `mcpgateway.auth_context` (existing, unchanged); `_ACCESS_DENIED_MSG`, `fresh_db_session`, `logger` already in `middleware/rbac.py`.
- Produces:
  - `_GLOBAL_SCOPE_DENIED_MSG: str`
  - `async require_unrestricted_platform_admin(request, user, db) -> None` — raises `HTTPException(403)`
  - `require_global_admin_permission() -> Callable` — decorator; sets `wrapper.__mcpgateway_scope_class__ = "global_only"`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/mcpgateway/middleware/test_global_scope_helpers.py`:

```python
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_global_scope_helpers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared global-record scope helper tests.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.middleware.rbac import require_global_admin_permission, require_unrestricted_platform_admin


def _request(token_teams, path="/compliance/reports"):
    request = MagicMock()
    request.state = SimpleNamespace(token_teams=token_teams)
    request.url = SimpleNamespace(path=path)
    return request


@pytest.mark.asyncio
async def test_raise_helper_allows_unrestricted_admin(monkeypatch):
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=True))

    assert await require_unrestricted_platform_admin(_request(None), {"email": "a@x.com"}, MagicMock()) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("token_teams", [[], ["team-a"]])
async def test_raise_helper_denies_narrowed_and_public_only(monkeypatch, token_teams, caplog):
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as exc:
        await require_unrestricted_platform_admin(_request(token_teams), {"email": "a@x.com"}, MagicMock())

    assert exc.value.status_code == 403
    # Denial must be self-diagnosing: identity, route, resolved scope, remediation.
    assert "a@x.com" in caplog.text
    assert "/compliance/reports" in caplog.text
    assert repr(token_teams) in caplog.text
    assert "--admin" in caplog.text
    # Detail carries remediation but never a permission name.
    assert "--admin" in exc.value.detail


@pytest.mark.asyncio
async def test_decorator_allows_unrestricted_admin(monkeypatch):
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=True))

    @require_global_admin_permission()
    async def endpoint(request=None, user=None, db=None):
        return "ok"

    assert await endpoint(request=_request(None), user={"email": "a@x.com"}, db=MagicMock()) == "ok"


@pytest.mark.asyncio
async def test_decorator_denies_narrowed_admin(monkeypatch):
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=False))

    @require_global_admin_permission()
    async def endpoint(request=None, user=None, db=None):
        return "ok"

    with pytest.raises(HTTPException) as exc:
        await endpoint(request=_request(["team-a"]), user={"email": "a@x.com"}, db=MagicMock())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_decorator_rejects_missing_user_context():
    @require_global_admin_permission()
    async def endpoint(request=None, user=None, db=None):
        return "ok"

    with pytest.raises(HTTPException) as exc:
        await endpoint(request=_request(None), user=None, db=MagicMock())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_decorator_creates_session_when_endpoint_has_no_db(monkeypatch):
    """list_frameworks has neither request nor db today; the decorator must cope."""
    predicate = AsyncMock(return_value=True)
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", predicate)
    fake_cm = MagicMock()
    fake_cm.__enter__ = MagicMock(return_value="session")
    fake_cm.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("mcpgateway.middleware.rbac.fresh_db_session", lambda: fake_cm)

    @require_global_admin_permission()
    async def endpoint(request=None, user=None):
        return "ok"

    assert await endpoint(request=_request(None), user={"email": "a@x.com"}) == "ok"
    assert predicate.await_args.args[2] == "session"


def test_decorator_sets_scope_class_marker():
    """The drift guard inspects this marker instead of parsing source."""

    @require_global_admin_permission()
    async def endpoint(request=None, user=None, db=None):
        return "ok"

    assert endpoint.__mcpgateway_scope_class__ == "global_only"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/mcpgateway/middleware/test_global_scope_helpers.py -v`
Expected: FAIL — `ImportError: cannot import name 'require_global_admin_permission'`

- [ ] **Step 3: Implement the helpers**

In `mcpgateway/middleware/rbac.py`, add immediately after the `_ACCESS_DENIED_MSG` definition (line 48):

```python
# Global-record scope denial. Unlike _ACCESS_DENIED_MSG this names the required
# token *shape* so an operator can self-diagnose, but never a permission name
# and never whether the target record exists.
_GLOBAL_SCOPE_DENIED_MSG = "Access denied: this endpoint requires an unrestricted platform-admin token. Reissue the token with --admin, or create it without selecting a team."
```

Then append after `require_admin_permission()` (after line 1030):

```python
def _log_global_scope_denial(user_email: Optional[str], request: Any, token_teams: Any) -> None:
    """Emit the structured denial record for a failed global-record scope check.

    Kept on one code path so every denial — decorator or raise-helper — is
    logged identically.

    Args:
        user_email: Email of the caller whose request was denied.
        request: Incoming request, used only to resolve the route path.
        token_teams: The *resolved* Layer-1 scope the rule judged, not the raw claim.
    """
    logger.warning(
        "global-record scope denied: user=%s route=%s token_teams=%r (route requires an unrestricted platform-admin token; reissue with `--admin`, or create the token without selecting a team)",
        user_email,
        getattr(getattr(request, "url", None), "path", "unknown"),
        token_teams,
    )


async def _global_scope_denied(request: Any, user: Any, db: Any) -> bool:
    """Evaluate the canonical global-record rule.

    Single evaluation point shared by :func:`require_unrestricted_platform_admin`
    and :func:`require_global_admin_permission`, so the two can never disagree
    about who would be rejected.

    Args:
        request: Incoming request context.
        user: Authenticated user context.
        db: Database session for the platform-admin lookup.

    Returns:
        bool: ``True`` when the caller lacks unrestricted platform-admin authority.
    """
    # First-Party
    from mcpgateway.auth_context import is_unrestricted_platform_admin  # pylint: disable=import-outside-toplevel

    return not await is_unrestricted_platform_admin(request, user, db)


async def require_unrestricted_platform_admin(request: Any, user: Any, db: Any) -> None:
    """Require unrestricted platform-admin authority for a global record.

    Raise-form of :func:`mcpgateway.auth_context.is_unrestricted_platform_admin`,
    for conditional call sites where the guard fires only when the request
    payload touches a global record (roots inside export/import). Whole-endpoint
    guards should use :func:`require_global_admin_permission` instead.

    Args:
        request: Incoming request context.
        user: Authenticated user context.
        db: Database session.

    Raises:
        HTTPException: 403 when the caller is narrowed, public-only, or not a platform admin.
    """
    if await _global_scope_denied(request, user, db):
        # First-Party
        from mcpgateway.auth_context import get_token_teams_from_request  # pylint: disable=import-outside-toplevel

        resolved = get_token_teams_from_request(request) if request is not None else None
        _log_global_scope_denial(user.get("email") if isinstance(user, dict) else user, request, resolved)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_GLOBAL_SCOPE_DENIED_MSG)


def require_global_admin_permission():
    """Decorator requiring unrestricted platform-admin authority for the whole endpoint.

    Mirrors :func:`require_admin_permission` in shape. The decorated endpoint
    MUST accept a ``request`` kwarg, because Layer-1 narrowing is read from
    ``request.state``. A ``db`` kwarg is used when present; otherwise a
    short-lived session is opened.

    Returns:
        Callable: Decorator enforcing the global-record scope rule.
    """

    def decorator(func: Callable) -> Callable:
        """Wrap the endpoint with the global-record scope check.

        Args:
            func: The endpoint to decorate.

        Returns:
            Callable: The wrapped endpoint.
        """

        @wraps(func)
        async def wrapper(*args, **kwargs):
            """Enforce the global-record scope rule before invoking the endpoint.

            Args:
                *args: Positional arguments forwarded to the endpoint.
                **kwargs: Keyword arguments forwarded to the endpoint.

            Returns:
                Any: The endpoint's result when the check passes.

            Raises:
                HTTPException: 401 without a user context, 403 when the scope check fails.
            """
            # Named kwargs only (security: never pick up a request body dict)
            user_context = kwargs.get("user") or kwargs.get("_user") or kwargs.get("current_user") or kwargs.get("current_user_ctx")
            if not user_context or not isinstance(user_context, dict) or "email" not in user_context:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User authentication required")

            request = kwargs.get("request")
            db_session = kwargs.get("db") or user_context.get("db")
            if db_session:
                denied = await _global_scope_denied(request, user_context, db_session)
            else:
                with fresh_db_session() as db:
                    denied = await _global_scope_denied(request, user_context, db)

            if denied:
                # First-Party
                from mcpgateway.auth_context import get_token_teams_from_request  # pylint: disable=import-outside-toplevel

                resolved = get_token_teams_from_request(request) if request is not None else None
                _log_global_scope_denial(user_context["email"], request, resolved)
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_GLOBAL_SCOPE_DENIED_MSG)

            return await func(*args, **kwargs)

        wrapper.__mcpgateway_scope_class__ = "global_only"
        return wrapper

    return decorator
```

Ensure `Any` and `Optional` are in the `typing` import at the top of the file; add them if missing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/mcpgateway/middleware/test_global_scope_helpers.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Lint**

Run: `make pre-commit` then `make ruff interrogate`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add mcpgateway/middleware/rbac.py tests/unit/mcpgateway/middleware/test_global_scope_helpers.py
git commit -s -m "feat(rbac): add shared global-record admin scope helpers

Adds require_unrestricted_platform_admin() for conditional call sites and
@require_global_admin_permission() for whole-endpoint guards, both delegating to
the existing is_unrestricted_platform_admin() predicate through one evaluation
point so decorator and raise-helper can never disagree.

Denials emit a structured record carrying the caller, route, resolved token
scope and remediation, and the 403 detail names the required token shape without
leaking permission names or record existence.

Refs #5982"
```

---

### Task 2: Test infrastructure — decorator mock and scope fixtures

**Files:**
- Modify: `tests/utils/rbac_mocks.py` (add mock at line ~296, register in `patch_rbac_decorators` line 358 and `restore_rbac_decorators` line 384)
- Create: `tests/helpers/scope.py`
- Test: `tests/unit/mcpgateway/middleware/test_global_scope_helpers.py` (extend)

**Interfaces:**
- Consumes: nothing from Task 1 at runtime.
- Produces: `mock_require_global_admin_permission()`; `admin_user_context(token_teams, email="admin@example.com") -> dict`; `scoped_request(token_teams, path="/") -> MagicMock`.

**This task must land before any route task or 26 test files break.**

**How route tests actually work in this codebase — read this before writing any route test.** They do **not** use `TestClient`, `app`, or `dependency_overrides`. `tests/unit/mcpgateway/routers/test_compliance_router.py:18-24` does this at module import time:

```python
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators

_originals = patch_rbac_decorators()
from mcpgateway.routers import compliance_router as router_mod  # noqa: E402
restore_rbac_decorators(_originals)
```

The decorators are swapped for no-ops, the router is imported so its handlers are baked with those no-ops, then the originals are restored. Tests then call handlers directly: `await router_mod.list_frameworks(user=_mock_user())`.

Two consequences that shaped the rest of this plan:

1. **`patch_rbac_decorators` knows nothing about `require_global_admin_permission`.** Once a route carries it, the real guard survives the patch. `_mock_user()` supplies no `request` kwarg, so `request` is `None`, `is_unrestricted_platform_admin` fails closed, and every affected test gets a 403. That is why the mock is registered here, in the first task that touches tests.

2. **Route-level deny tests through direct calls are unreliable.** A router module is imported once per session; whichever test module imports it first decides whether its decorators are real or mocked. A deny test in a second module would silently pass or fail on import order. **So decorator behaviour is proven in Task 1 (unit tests against the real decorator) and route coverage is proven in Task 9 (the drift guard asserts each `GLOBAL_ONLY` route carries the marker).** Route-level tests are written only for handler-*body* logic — the filtering in Task 6 and the assignment authorizer in Task 7 — which is ordinary code unaffected by decorator mocking.

Do not "improve" this by adding TestClient-based deny tests for the decorated routes. They will appear to work and then rot into order-dependent flakes.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/mcpgateway/middleware/test_global_scope_helpers.py`:

```python
# First-Party
from tests.helpers.scope import admin_user_context, scoped_request
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators


def test_scope_fixture_shapes():
    unrestricted = admin_user_context(None)
    assert unrestricted["email"] == "admin@example.com"
    assert unrestricted["is_admin"] is True
    assert unrestricted["token_teams"] is None

    narrowed = admin_user_context(["team-a"], email="ops@example.com")
    assert narrowed["email"] == "ops@example.com"
    assert narrowed["token_teams"] == ["team-a"]

    req = scoped_request(["team-a"], path="/compliance/reports")
    assert req.state.token_teams == ["team-a"]
    assert req.url.path == "/compliance/reports"


@pytest.mark.asyncio
async def test_patch_rbac_decorators_covers_the_global_guard():
    """26 suites import routers under this patch; the new guard must be mocked too."""
    # First-Party
    import mcpgateway.middleware.rbac as rbac_module

    originals = patch_rbac_decorators()
    try:
        assert rbac_module.require_global_admin_permission is not None

        @rbac_module.require_global_admin_permission()
        async def endpoint(user=None):
            return "ok"

        # No request kwarg and no scope: the real guard would 403 here.
        assert await endpoint(user={"email": "a@x.com"}) == "ok"
    finally:
        restore_rbac_decorators(originals)

    # Restoration must put the real guard back, or later suites silently lose coverage.
    assert rbac_module.require_global_admin_permission.__module__ == "mcpgateway.middleware.rbac"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/mcpgateway/middleware/test_global_scope_helpers.py -k "fixture_shapes or patch_rbac" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.helpers.scope'`, and the patch test allows the real guard through

- [ ] **Step 3: Register the decorator mock**

In `tests/utils/rbac_mocks.py`, add after `mock_require_admin_permission` (ends line ~307):

```python
def mock_require_global_admin_permission():
    """Mock version of require_global_admin_permission that always allows access.

    Suites that import a router under :func:`patch_rbac_decorators` supply no
    ``request`` kwarg, so the real guard would fail closed and 403 every test.

    Returns:
        Callable: A decorator that performs no scope checking.
    """

    def decorator(func):
        # Return the function unchanged - no global-record scope checking
        return func

    return decorator
```

In `patch_rbac_decorators` (line 358), add to the `originals` dict and the replacement block:

```python
        "require_global_admin_permission": rbac_module.require_global_admin_permission,
```
```python
    rbac_module.require_global_admin_permission = mock_require_global_admin_permission
```

In `restore_rbac_decorators` (line 384), add:

```python
    rbac_module.require_global_admin_permission = originals["require_global_admin_permission"]
```

- [ ] **Step 4: Create the scope fixture module**

Create `tests/helpers/scope.py`:

```python
# -*- coding: utf-8 -*-
"""Location: ./tests/helpers/scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope fixtures for route-level tests.

Route tests that override ``get_current_user_with_permissions`` with a bare dict
resolve to public-only, because ``get_rpc_filter_context()`` falls back to
``normalize_token_teams()`` on an absent JWT payload. Use these helpers so the
three admin contexts the spec requires — unrestricted, team-scoped, public-only —
are constructed identically everywhere.
"""

# Standard
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock


def admin_user_context(token_teams: Optional[List[str]], email: str = "admin@example.com") -> Dict[str, Any]:
    """Build a user context dict for an admin at a given Layer-1 scope.

    Args:
        token_teams: ``None`` for unrestricted, ``[]`` for public-only, or a list of team IDs.
        email: Caller identity.

    Returns:
        Dict[str, Any]: User context in the shape route decorators expect.
    """
    return {"email": email, "full_name": "Test Admin", "is_admin": True, "token_teams": token_teams, "db": None}


def scoped_request(token_teams: Optional[List[str]], path: str = "/") -> MagicMock:
    """Build a request whose resolved Layer-1 scope is ``token_teams``.

    Args:
        token_teams: ``None`` for unrestricted, ``[]`` for public-only, or a list of team IDs.
        path: Route path, used by denial logging assertions.

    Returns:
        MagicMock: Request stub with ``state.token_teams`` and ``url.path`` set.
    """
    request = MagicMock()
    request.state = SimpleNamespace(token_teams=token_teams)
    request.url = SimpleNamespace(path=path)
    return request
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/mcpgateway/middleware/test_global_scope_helpers.py -v`
Expected: PASS (10 tests)

- [ ] **Step 6: Confirm no existing suite regressed**

Run: `pytest tests/unit/mcpgateway/routers/ -q`
Expected: same pass count as before Task 1. If anything 403s, the mock is not registered correctly.

- [ ] **Step 7: Commit**

```bash
git add tests/utils/rbac_mocks.py tests/helpers/scope.py tests/unit/mcpgateway/middleware/test_global_scope_helpers.py
git commit -s -m "test: mock the global-record guard and add Layer-1 scope fixtures

Twenty-six suites import routers under patch_rbac_decorators, which knew nothing
about require_global_admin_permission — the real guard would survive the patch,
find no request kwarg, fail closed and 403 every test on a guarded route. The
decorator now has a mock registered alongside the others.

Adds shared constructors for the three admin scope contexts so route tests build
them identically.

Refs #5982"
```

---

### Task 3: Deduplicate the roots helper (no behavior change)

**Files:**
- Modify: `mcpgateway/admin.py` — delete `_require_unrestricted_root_admin` (lines 14117-14120), update import at line 112
- Modify: `mcpgateway/main.py` — delete `_require_unrestricted_root_admin` (lines 7671-7674), update import at line 117
- Test: `tests/unit/mcpgateway/middleware/test_global_scope_helpers.py` (already covers the shared helper)

**Interfaces:**
- Consumes: `require_unrestricted_platform_admin` from Task 1.
- Produces: nothing new. All 26 root call sites keep identical semantics.

The two deleted bodies are equivalent — they differ only in `403` versus `status.HTTP_403_FORBIDDEN`. The one behavioral delta is the 403 *detail*: previously `_ACCESS_DENIED_MSG` ("Access denied"), now `_GLOBAL_SCOPE_DENIED_MSG`. That is intended (spec §2 makes denials self-diagnosing), but any test asserting the exact roots 403 body must be updated.

- [ ] **Step 1: Find tests asserting the old roots denial message**

Run:
```bash
grep -rn "Access denied" tests/unit/mcpgateway/test_admin.py tests/unit/mcpgateway/test_main.py tests/unit/mcpgateway/test_auth_context_root_admin.py tests/unit/mcpgateway/test_admin_import_export.py | head -20
```
Record every hit that relates to a roots route — these get updated in Step 4.

- [ ] **Step 2: Delete the duplicate in `admin.py`**

Remove lines 14117-14120 entirely:

```python
async def _require_unrestricted_root_admin(request: Optional[Request], user: Any, db: Session) -> None:
    """Require unrestricted platform-admin authority for global roots."""
    if not await is_unrestricted_platform_admin(request, user, db):
        raise HTTPException(status_code=403, detail=_ACCESS_DENIED_MSG)
```

Update the import on line 112 from:

```python
from mcpgateway.middleware.rbac import _ACCESS_DENIED_MSG, get_current_user_with_permissions, require_any_permission, require_permission
```

to:

```python
from mcpgateway.middleware.rbac import _ACCESS_DENIED_MSG, get_current_user_with_permissions, require_any_permission, require_permission, require_unrestricted_platform_admin
```

Then rename every call site. There are 10 in `admin.py` — lines 14156, 14200, 14276, 14314, 14381, 14436, 15655, 15733, 15806, 15867:

```bash
sed -i 's/await _require_unrestricted_root_admin(/await require_unrestricted_platform_admin(/g' mcpgateway/admin.py
```

Leave `admin.py:3847` alone — it calls the bool predicate `is_unrestricted_platform_admin` to compute a UI capability flag, not to authorize.

- [ ] **Step 3: Delete the duplicate in `main.py`**

Remove lines 7671-7674 (same body, `status.HTTP_403_FORBIDDEN` variant). Update the import on line 117 to add `require_unrestricted_platform_admin`, then:

```bash
sed -i 's/await _require_unrestricted_root_admin(/await require_unrestricted_platform_admin(/g' mcpgateway/main.py
```

Leave `main.py:8987`, `11323`, and `11528` alone — those call the bool predicate inline and raise `JSONRPCError`, not `HTTPException`.

- [ ] **Step 4: Update any roots tests asserting the old detail string**

For each hit recorded in Step 1 that covers a roots route, change the expected detail from `"Access denied"` to the new message. Import it rather than hardcoding:

```python
# First-Party
from mcpgateway.middleware.rbac import _GLOBAL_SCOPE_DENIED_MSG

assert response.json()["detail"] == _GLOBAL_SCOPE_DENIED_MSG
```

- [ ] **Step 5: Verify no references remain and tests pass**

Run:
```bash
grep -rn "_require_unrestricted_root_admin" mcpgateway/ && echo "STILL PRESENT - fix before continuing" || echo "clean"
pytest tests/unit/mcpgateway/test_auth_context_root_admin.py tests/unit/mcpgateway/test_admin_import_export.py -v
```
Expected: `clean`, then PASS

- [ ] **Step 6: Commit**

```bash
git add mcpgateway/admin.py mcpgateway/main.py tests/
git commit -s -m "refactor(rbac): collapse duplicated roots admin helper onto shared function

admin.py and main.py each carried a private _require_unrestricted_root_admin
differing only in how they spelled 403. Both now call the shared
require_unrestricted_platform_admin. All 26 root call sites keep identical
authorization semantics; only the 403 detail changes, to the self-diagnosing
message.

Refs #5982"
```

---

### Task 4: Compliance routes — global-only

**Files:**
- Modify: `mcpgateway/routers/compliance_router.py` lines 125, 144, 188, 229, 272
- Test: `tests/unit/mcpgateway/routers/test_compliance_router.py` (rework — 17 tests)

**Interfaces:**
- Consumes: `require_global_admin_permission` (Task 1), `admin_user_context` / `scoped_request` (Task 2).
- Produces: nothing consumed by later tasks.

**Why:** `ComplianceReport` (`services/compliance_service.py:105`) is a dataclass aggregating platform-wide state — user inventory, role inventory, audit logs, config snapshot — with no team column. Under `@require_admin_permission()` a token narrowed to one team can generate and read a report covering every team. That is a Layer-1 escape.

All five endpoints need a `request` parameter added; none has one. `list_frameworks` also has no `db` — Task 1's decorator opens its own session for that case.

- [ ] **Step 1: Update the existing suite for the new signatures**

The 17 tests in `tests/unit/mcpgateway/routers/test_compliance_router.py` call handlers directly — `await router_mod.list_frameworks(user=_mock_user())`. Adding a `request` parameter breaks none of them, because `request` will have a default of `None` only if we give it one, and we deliberately do **not**: FastAPI needs it as a required parameter to inject the real request.

So every call site in that file needs the kwarg. Update `_mock_user()` at line 62 to return the shared context, and add a request stub:

```python
# First-Party
from tests.helpers.scope import admin_user_context, scoped_request


def _mock_user():
    """Unrestricted admin context for handler-level calls."""
    return admin_user_context(None)


def _req(path="/compliance/frameworks"):
    """Request stub carrying unrestricted Layer-1 scope."""
    return scoped_request(None, path=path)
```

Then add `request=_req()` to all 17 handler invocations, e.g.:

```python
result = await router_mod.list_frameworks(request=_req(), user=_mock_user())
```

**Deny coverage is not written here** — see Task 2's explanation. This file imports the router under `patch_rbac_decorators`, so the guard is a no-op inside it by construction. The decorator's deny behaviour is proven in Task 1; the fact that *these specific routes* carry it is proven in Task 9.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/mcpgateway/routers/test_compliance_router.py -v`
Expected: FAIL — `TypeError: ... got an unexpected keyword argument 'request'`, because the handlers do not accept it yet

- [ ] **Step 3: Apply the guard and add `request` params**

In `mcpgateway/routers/compliance_router.py`, change the import on line 31:

```python
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_global_admin_permission
```

`require_admin_permission` is no longer used in this file — remove it from the import.

Then for each of the five endpoints, swap the decorator and add `request: Request`. Add `Request` to the FastAPI import on line 24. Example for the first:

```python
@router.get("/frameworks", response_model=List[FrameworkInfo])
@require_global_admin_permission()
async def list_frameworks(user=Depends(get_current_user_with_permissions), request: Request = None) -> List[FrameworkInfo]:  # pylint: disable=unused-argument
```

Append `request: Request = None` **last** in every signature — never first. FastAPI injects by annotation regardless of position, and appending with a default keeps existing positional test calls working. Apply the same two changes at lines 144, 188, 229, and 272. Each endpoint's docstring needs a `request` entry in its `Args:` block or `make interrogate` and pylint will complain:

```
        request: Incoming request, used to resolve Layer-1 token scope.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/mcpgateway/routers/test_compliance_router.py tests/unit/mcpgateway/test_global_record_scope.py -v`
Expected: PASS (17 existing tests; the drift guard arrives in Task 9 and will then assert these five routes carry the marker)

- [ ] **Step 5: Lint and commit**

```bash
make pre-commit
git add mcpgateway/routers/compliance_router.py tests/unit/mcpgateway/routers/test_compliance_router.py
git commit -s -m "fix(compliance): require unrestricted platform admin for compliance routes

ComplianceReport aggregates platform-wide state with no team column, so under
require_admin_permission a token narrowed to one team could generate and read a
report covering every team. All five routes now require an unrestricted
platform-admin token.

Adds the request parameter each endpoint needs for Layer-1 resolution, and
reworks the suite's auth fixtures, which previously resolved to public-only by
accident.

Refs #5982"
```

---

### Task 5: Role definition mutations — global-only

**Files:**
- Modify: `mcpgateway/routers/rbac.py` lines 81 (`create_role`), 212 (`update_role`), 259 (`delete_role`)
- Test: `tests/unit/mcpgateway/routers/test_rbac_scope.py` (create)

**Interfaces:**
- Consumes: `require_global_admin_permission` (Task 1), `admin_user_context` (Task 2).
- Produces: nothing consumed by later tasks.

**Why:** `Role` (`db.py:1154-1193`) has **no `team_id`**. `Role.scope` is `global | team | personal`, but a `scope='team'` role is an unbound template assignable platform-wide — the team binding lives on `UserRole.scope_id` at assignment time. So every role *definition* is a global record regardless of its `scope` value, and the guard applies unconditionally rather than switching on the payload.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/mcpgateway/routers/test_rbac_scope.py`. This file imports the router **without** `patch_rbac_decorators`, so handler bodies run for real. It does not attempt route-level deny assertions on the decorator — see Task 2.

```python
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

# Third-Party
import pytest

# First-Party
from mcpgateway.routers import rbac as rbac_router


def test_module_imports_with_real_decorators():
    """Guard against this file accidentally being imported under the mocks."""
    assert rbac_router.create_role.__mcpgateway_scope_class__ == "global_only"
    assert rbac_router.update_role.__mcpgateway_scope_class__ == "global_only"
    assert rbac_router.delete_role.__mcpgateway_scope_class__ == "global_only"
```

That marker assertion is the whole test for this task. It proves the three mutation routes carry the canonical guard, which — combined with Task 1's proof of what the guard does — is the coverage the spec asks for, without an order-dependent deny test.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/mcpgateway/routers/test_rbac_scope.py -v`
Expected: FAIL — `AttributeError: 'function' object has no attribute '__mcpgateway_scope_class__'`

- [ ] **Step 3: Apply the guard**

In `mcpgateway/routers/rbac.py`, update the import on line 12:

```python
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_global_admin_permission, require_permission
```

`require_admin_permission` is no longer used in this file after this task — remove it. Add `Request` to the FastAPI import on line 5.

Change line 81, 212, and 259 from `@require_admin_permission()` to `@require_global_admin_permission()`, and append a `request` parameter to each handler:

**`request` goes LAST, never first.** `tests/unit/mcpgateway/routers/test_rbac_router.py` binds a local named `request` to the Pydantic *body* and passes it positionally — `await rbac_router.create_role(request, user=..., db=...)` at lines 102, 114, 126, and `update_role("r1", request, ...)` at 186, 198. Inserting a `request: Request` parameter first would silently rebind the body into it. FastAPI injects by type annotation regardless of position, and the decorator reads `kwargs.get("request")`, so appending is both safe and sufficient.

```python
@router.post("/roles", response_model=RoleResponse)
@require_global_admin_permission()
async def create_role(role_data: RoleCreateRequest, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db), request: Request = None):
```

```python
@router.put("/roles/{role_id}", response_model=RoleResponse)
@require_global_admin_permission()
async def update_role(role_id: str, role_data: RoleUpdateRequest, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db), request: Request = None):
```

```python
@router.delete("/roles/{role_id}")
@require_global_admin_permission()
async def delete_role(role_id: str, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db), request: Request = None):
```

The `= None` default keeps existing positional test calls working. FastAPI still injects the real `Request` in production because the annotation drives injection, not the default. The guard fails closed when `request` is `None`, which is the correct behaviour for any caller that bypasses FastAPI.

Add a `request:` line to each handler's `Args:` docstring block.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/mcpgateway/routers/test_rbac_scope.py tests/unit/mcpgateway/routers/ -q`
Expected: PASS. Any existing rbac-router suite that calls these three handlers directly needs `request=` added to its invocations, the same change Task 4 made for compliance. Find them with `grep -rn "create_role(\|update_role(\|delete_role(" tests/`.

- [ ] **Step 5: Commit**

```bash
make pre-commit
git add mcpgateway/routers/rbac.py tests/unit/mcpgateway/routers/test_rbac_scope.py tests/
git commit -s -m "fix(rbac): require unrestricted platform admin for role definition changes

Role has no team_id — a scope='team' role is an unbound template assignable
platform-wide, with the team binding living on UserRole.scope_id at assignment
time. Every role definition is therefore a global record, so create, update and
delete require an unrestricted platform-admin token regardless of the submitted
scope value.

Refs #5982"
```

---

### Task 6: Role definition reads — Layer-1 filtering

**Files:**
- Modify: `mcpgateway/routers/rbac.py` lines 132 (`list_roles`), 173 (`get_role`)
- Test: `tests/unit/mcpgateway/routers/test_rbac_scope.py` (extend)

**Interfaces:**
- Consumes: `get_scoped_resource_access_context` from `mcpgateway.auth_context` (existing).
- Produces: nothing consumed by later tasks.

**Why filtering rather than 403:** these are the `filtered-read` class from spec §1. A 403 on a list route would break the admin UI role picker for narrowed tokens; returning a narrowed result set preserves the route while still honouring Layer 1. `list_roles` currently applies **no** filtering at all — it passes the optional `scope` query param straight to `RoleService.list_roles()` and returns everything.

Filtering goes in the router, not `RoleService`, so the service stays a plain data-access layer consistent with the rest of the codebase.

- [ ] **Step 1: Write the failing test**

These two handlers are **not** decorated with the new guard, so direct calls exercise the real filtering logic with no import-order hazard.

`list_roles` returns `[RoleResponse.model_validate(role) for role in roles]`, so mock rows must satisfy every `RoleResponse` field: `id`, `name`, `description`, `scope`, `permissions`, `effective_permissions`, `inherits_from`, `created_by`, `is_system_role`, `is_active`, `created_at`, `updated_at`. A bare `SimpleNamespace(id=..., scope=...)` will fail validation — build complete rows.

Append to `tests/unit/mcpgateway/routers/test_rbac_scope.py`:

```python
# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException

# First-Party
from tests.helpers.scope import admin_user_context, scoped_request

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _role_row(role_id, name, scope):
    """Build a row satisfying every RoleResponse field."""
    return SimpleNamespace(
        id=role_id,
        name=name,
        description="d",
        scope=scope,
        permissions=[],
        effective_permissions=[],
        inherits_from=None,
        created_by="admin@example.com",
        is_system_role=False,
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest.mark.asyncio
async def test_list_roles_hides_global_roles_from_narrowed_admin(monkeypatch):
    """Narrowed admins see non-global roles only — a 403 here would break the UI role picker."""
    rows = [_role_row("1", "platform_admin", "global"), _role_row("2", "team_admin", "team")]
    monkeypatch.setattr("mcpgateway.services.role_service.RoleService.list_roles", AsyncMock(return_value=rows))

    result = await rbac_router.list_roles(
        request=scoped_request(["team-a"], path="/rbac/roles"),
        user=admin_user_context(["team-a"]),
        db=MagicMock(),
    )

    assert {r.scope for r in result} == {"team"}


@pytest.mark.asyncio
async def test_list_roles_shows_everything_to_unrestricted_admin(monkeypatch):
    rows = [_role_row("1", "platform_admin", "global"), _role_row("2", "team_admin", "team")]
    monkeypatch.setattr("mcpgateway.services.role_service.RoleService.list_roles", AsyncMock(return_value=rows))

    result = await rbac_router.list_roles(
        request=scoped_request(None, path="/rbac/roles"),
        user=admin_user_context(None),
        db=MagicMock(),
    )

    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_global_role_returns_404_for_narrowed_admin(monkeypatch):
    """404, not 403 — do not confirm the existence of a role the caller may not enumerate."""
    monkeypatch.setattr(
        "mcpgateway.services.role_service.RoleService.get_role_by_id",
        AsyncMock(return_value=_role_row("1", "platform_admin", "global")),
    )

    with pytest.raises(HTTPException) as exc:
        await rbac_router.get_role(
            request=scoped_request(["team-a"], path="/rbac/roles/1"),
            role_id="1",
            user=admin_user_context(["team-a"]),
            db=MagicMock(),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Role not found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/mcpgateway/routers/test_rbac_scope.py -k "list_roles or get_global_role" -v`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'request'`

- [ ] **Step 3: Add the filtering**

In `mcpgateway/routers/rbac.py`, add to the first-party imports:

```python
from mcpgateway.auth_context import get_scoped_resource_access_context
```

Append `request: Request = None` **last** to `list_roles` and `get_role`, with a matching `Args:` docstring line. Never first — see the note in Task 5.

Unlike Tasks 4 and 5, these handlers read `request` in their **body**, so existing direct calls that omit it will fail. Update these four call sites in `tests/unit/mcpgateway/routers/test_rbac_router.py` to pass `request=scoped_request(None)`:

- line 137 — `rbac_router.list_roles(scope=None, active_only=True, user=..., db=...)`
- line 148 — `rbac_router.get_role("missing", user=..., db=...)`
- line 160 — `rbac_router.get_role("r1", user=..., db=db)`
- line 173 — `rbac_router.get_role("r1", user=..., db=...)`

`get_scoped_resource_access_context(None, user)` would raise, so guard the body against a missing request or always pass one from tests. Prefer passing one — a `None` request in production is impossible, and silently treating it as unrestricted would be a security hole.

In `list_roles`, replace:

```python
        roles = await role_service.list_roles(scope=scope)
```

with:

```python
        roles = await role_service.list_roles(scope=scope)

        # Layer 1: a narrowed or public-only admin must not enumerate global roles.
        # Filtered rather than denied — a 403 on this route would break the admin
        # UI role picker for every narrowed token.
        _, token_teams = get_scoped_resource_access_context(request, user)
        if token_teams is not None:
            roles = [role for role in roles if role.scope != "global"]
```

In `get_role`, replace:

```python
        role = await role_service.get_role_by_id(role_id)

        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

        db.commit()
```

with:

```python
        role = await role_service.get_role_by_id(role_id)

        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

        # 404 rather than 403: do not confirm the existence of a role the caller
        # is not permitted to enumerate. Same detail string as the genuine miss.
        _, token_teams = get_scoped_resource_access_context(request, user)
        if token_teams is not None and role.scope == "global":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

        db.commit()
```

`get_role` already has `except HTTPException: raise` ahead of its generic handler, so the 404 propagates rather than being converted to a 500. Do not remove that clause.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/mcpgateway/routers/test_rbac_scope.py -v`
Expected: PASS (all filtering tests plus the marker test from Task 5)

- [ ] **Step 5: Commit**

```bash
make pre-commit
git add mcpgateway/routers/rbac.py tests/unit/mcpgateway/routers/test_rbac_scope.py
git commit -s -m "fix(rbac): filter global roles from narrowed admin reads

list_roles applied no Layer-1 filtering at all, so any admin.user_management
holder could enumerate every global role and its permission set. Narrowed and
public-only admins now see non-global roles only, and the detail route returns
404 for a global role rather than confirming it exists.

Filtered rather than denied because a 403 on the list route would break the
admin UI role picker for every narrowed token.

Refs #5982"
```

---

### Task 7: Role assignments — team-scoping model

**Files:**
- Modify: `mcpgateway/routers/rbac.py` lines 308 (`assign_role_to_user`), 400 (`revoke_user_role`)
- Test: `tests/unit/mcpgateway/routers/test_rbac_scope.py` (extend)

**Interfaces:**
- Consumes: `require_unrestricted_platform_admin` (Task 1), `get_scoped_resource_access_context`, `UserRole` from `mcpgateway.db`.
- Produces: `_authorize_assignment_scope(request, user, db, scope, scope_id, target_email) -> None` — module-private to `routers/rbac.py`.

**Why this is the sharpest fix in the plan:** today a narrowed admin holding `admin.user_management` can assign a global role carrying `*` to any user, including themselves — a privilege-escalation path straight out of their Layer-1 narrowing.

Rules:

| Assignment scope | Requirement |
|---|---|
| `global` | unrestricted platform admin |
| `team` | `scope_id` present AND `scope_id ∈ token_teams` (unrestricted admin passes) |
| `personal` | unrestricted admin, or caller assigning to themselves |

On DELETE the scope comes from the **existing `UserRole` row**, never from client-supplied query params. `revoke_user_role` currently takes `scope` and `scope_id` from the request; trusting those would let a caller relabel a global assignment as team-scoped to get it deleted.

- [ ] **Step 1: Write the failing test**

These handlers keep `@require_permission("admin.user_management")` — the per-record check lives in the handler body, so direct calls exercise it. Test `_authorize_assignment_scope` directly for the matrix, plus one end-to-end revoke test proving the stored row wins over the request.

Append to `tests/unit/mcpgateway/routers/test_rbac_scope.py`:

```python
@pytest.mark.asyncio
async def test_narrowed_admin_cannot_authorize_global_assignment(monkeypatch):
    """The escalation path: a narrowed admin minting themselves a global '*' role."""
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as exc:
        await rbac_router._authorize_assignment_scope(
            scoped_request(["team-a"]), admin_user_context(["team-a"]), MagicMock(), "global", None, "victim@example.com"
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_unrestricted_admin_may_authorize_global_assignment(monkeypatch):
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=True))

    assert (
        await rbac_router._authorize_assignment_scope(
            scoped_request(None), admin_user_context(None), MagicMock(), "global", None, "victim@example.com"
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,scope_id,target,expected_denied",
    [
        ("team", "team-b", "victim@example.com", True),   # team not covered by the token
        ("team", None, "victim@example.com", True),        # team scope with no scope_id fails closed
        ("team", "team-a", "member@example.com", False),   # covered team
        ("personal", None, "victim@example.com", True),    # someone else's personal scope
        ("personal", None, "admin@example.com", False),    # self
        ("nonsense", None, "victim@example.com", True),    # unknown scope fails closed
    ],
)
async def test_assignment_scope_matrix(scope, scope_id, target, expected_denied):
    request = scoped_request(["team-a"])
    user = admin_user_context(["team-a"])

    if expected_denied:
        with pytest.raises(HTTPException) as exc:
            await rbac_router._authorize_assignment_scope(request, user, MagicMock(), scope, scope_id, target)
        assert exc.value.status_code == 403
    else:
        assert await rbac_router._authorize_assignment_scope(request, user, MagicMock(), scope, scope_id, target) is None


@pytest.mark.asyncio
async def test_revoke_reads_scope_from_the_stored_row_not_the_request(monkeypatch):
    """A client must not be able to relabel a global assignment to get it revoked."""
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(rbac_router, "_load_assignment", lambda db, email, role_id: SimpleNamespace(scope="global", scope_id=None))

    with pytest.raises(HTTPException) as exc:
        # Caller claims team scope; the stored row says global, so this must be denied.
        await rbac_router.revoke_user_role(
            request=scoped_request(["team-a"]),
            user_email="victim@example.com",
            role_id="r",
            scope="team",
            scope_id="team-a",
            user=admin_user_context(["team-a"]),
            db=MagicMock(),
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_revoke_returns_404_when_assignment_absent(monkeypatch):
    monkeypatch.setattr(rbac_router, "_load_assignment", lambda db, email, role_id: None)

    with pytest.raises(HTTPException) as exc:
        await rbac_router.revoke_user_role(
            request=scoped_request(None),
            user_email="nobody@example.com",
            role_id="r",
            scope="team",
            scope_id="team-a",
            user=admin_user_context(None),
            db=MagicMock(),
        )

    assert exc.value.status_code == 404
```

Confirm `revoke_user_role`'s real parameter names and order with `sed -n '399,412p' mcpgateway/routers/rbac.py` before writing the two revoke calls, and match them exactly.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/mcpgateway/routers/test_rbac_scope.py -k "assign or revoke or matrix" -v`
Expected: FAIL — `AttributeError: module has no attribute '_authorize_assignment_scope'`

- [ ] **Step 3: Add the scope authorizer and the row loader**

In `mcpgateway/routers/rbac.py`, add `UserRole` to the `mcpgateway.db` import on line 11, and add these two module-level helpers above `assign_role_to_user`:

```python
def _load_assignment(db: Session, user_email: str, role_id: str) -> Optional[UserRole]:
    """Load the active role assignment for a user, for authorization decisions.

    Args:
        db: Database session.
        user_email: Email of the user whose assignment is being acted on.
        role_id: Role identifier.

    Returns:
        Optional[UserRole]: The active assignment, or ``None`` when absent.
    """
    return db.query(UserRole).filter(UserRole.user_email == user_email, UserRole.role_id == role_id, UserRole.is_active.is_(True)).first()


async def _authorize_assignment_scope(request, user, db: Session, scope: str, scope_id: Optional[str], target_email: str) -> None:
    """Authorize a role assignment or revocation against the caller's Layer-1 scope.

    A narrowed admin may only act within the teams their token covers, and may
    never grant or revoke a global assignment — that is the escalation path this
    guards.

    Args:
        request: Incoming request context.
        user: Authenticated user context.
        db: Database session.
        scope: Assignment scope — ``global``, ``team`` or ``personal``.
        scope_id: Team identifier for team-scoped assignments.
        target_email: The user the assignment applies to.

    Raises:
        HTTPException: 403 when the caller's token does not cover the assignment.
    """
    if scope == "global":
        await require_unrestricted_platform_admin(request, user, db)
        return

    _, token_teams = get_scoped_resource_access_context(request, user)
    if token_teams is None:
        return  # Unrestricted platform admin.

    if scope == "team":
        if not scope_id or scope_id not in token_teams:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_MSG)
        return

    if scope == "personal":
        if target_email != user.get("email"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_MSG)
        return

    # Unknown scope values fail closed.
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_MSG)
```

Add `_ACCESS_DENIED_MSG` and `require_unrestricted_platform_admin` to the `mcpgateway.middleware.rbac` import, `Optional` to the `typing` import, and `Request` to the FastAPI import if Task 5 has not already added it.

- [ ] **Step 4: Wire the authorizer into both handlers**

Append `request: Request = None` **last** to both handlers — never first. `test_rbac_router.py` calls them positionally: `assign_role_to_user("user@example.com", assign_request, ...)` at lines 245, 260, 363 and `revoke_user_role("user@example.com", "r1", scope=..., scope_id=..., ...)` at 248, 284.

Those five call sites need `request=scoped_request(None)` added, because these handlers read `request` in their body. The two `revoke_user_role` calls additionally need `_load_assignment` patched — they currently mock only `RoleService.revoke_role_from_user`, so without a stored row they would now get a 404:

```python
monkeypatch.setattr(rbac_router, "_load_assignment", lambda db, email, role_id: SimpleNamespace(scope="global", scope_id=None))
```

In `assign_role_to_user`, insert before `role_service.assign_role_to_user(...)`:

```python
        await _authorize_assignment_scope(request, user, db, assignment_data.scope, assignment_data.scope_id, user_email)
```

In `revoke_user_role`, replace the opening of the `try` block so the stored row — not the query params — drives authorization:

```python
        existing = _load_assignment(db, user_email, role_id)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role assignment not found")

        # SECURITY: authorize against the stored assignment, never the client-supplied
        # scope/scope_id query params — otherwise a caller could relabel a global
        # assignment as team-scoped to get it revoked.
        await _authorize_assignment_scope(request, user, db, existing.scope, existing.scope_id, user_email)

        role_service = RoleService(db)
        success = await role_service.revoke_role_from_user(user_email=user_email, role_id=role_id, scope=existing.scope, scope_id=existing.scope_id)
```

`revoke_user_role` already has `except HTTPException: raise` ahead of its generic handler, so the 403 and 404 propagate correctly. Add a `request:` line to both `Args:` docstring blocks.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/mcpgateway/routers/test_rbac_scope.py -v`
Expected: PASS (marker, filtering, scope-matrix and revoke tests)

- [ ] **Step 6: Commit**

```bash
make pre-commit
git add mcpgateway/routers/rbac.py tests/unit/mcpgateway/routers/test_rbac_scope.py
git commit -s -m "fix(rbac): scope role assignments to the caller's teams

A narrowed admin holding admin.user_management could assign a global role
carrying '*' to any user, including themselves — an escalation straight out of
their Layer-1 narrowing. Assignments are now authorized per record: global
requires an unrestricted token, team requires the token to cover that team, and
personal is self-only.

Revocation reads scope and scope_id from the stored assignment rather than the
request, so a caller cannot relabel a global assignment as team-scoped to get it
revoked.

Refs #5982"
```

---

### Task 8: `/version` — close the enforcement gap

**Files:**
- Modify: `mcpgateway/version.py` — delete `_has_version_admin_access` (lines 1228-1255), modify `version_endpoint` (line 1259 onward), remove the `normalize_token_teams` import (line 72)
- Test: `tests/unit/mcpgateway/test_version_scope.py` (create)

**Interfaces:**
- Consumes: `is_unrestricted_platform_admin` from `mcpgateway.auth_context`, `_GLOBAL_SCOPE_DENIED_MSG` from `mcpgateway.middleware.rbac`.
- Produces: nothing consumed by later tasks.

**Why the dependency stays as-is — do not "improve" this:** `version_endpoint` keeps `_user=Depends(require_admin_auth)`. `get_current_user_with_permissions` (`middleware/rbac.py:238`) has **no HTTP Basic path** — `basic_security` and `HTTPBasicCredentials` appear nowhere in that module — whereas `require_admin_auth` (`utils/verify_credentials.py:1623-1627`) accepts them. Swapping the dependency would turn every basic-auth call to `/version` into a **401**, a strictly larger break than the 403 intended, hitting exactly the monitoring callers this change otherwise leaves alone. Keeping it also preserves the HTML login-redirect for browsers for free.

The current check is dead code: `_has_version_admin_access(_user)` receives a plain email string from `require_admin_auth`, hits `isinstance(user, str)` and returns `True`, so the `normalize_token_teams(user) is None` test never runs.

The Admin UI fetches `/version?partial=true` from `admin_ui/initialization.js:846` and `admin_ui/tabs.js:728` over the browser session cookie, which resolves through the DB to unrestricted — unaffected, but covered below because it is the one UI path crossing a changed route.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/mcpgateway/test_version_scope.py`:

```python
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_version_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope enforcement on the diagnostics endpoint.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.version import version_endpoint
from tests.helpers.scope import scoped_request


@pytest.mark.asyncio
@pytest.mark.parametrize("token_teams", [[], ["team-a"]])
async def test_narrowed_admin_denied(monkeypatch, token_teams):
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as exc:
        await version_endpoint(scoped_request(token_teams, path="/version"), _user="admin@example.com")

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_unrestricted_admin_allowed(monkeypatch):
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.version._build_payload", MagicMock(return_value={"ok": True}))

    response = await version_endpoint(scoped_request(None, path="/version"), _user="admin@example.com")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_basic_auth_string_identity_is_still_accepted(monkeypatch):
    """require_admin_auth returns a bare email for basic auth; that path must keep working."""
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.version._build_payload", MagicMock(return_value={"ok": True}))

    response = await version_endpoint(scoped_request(None, path="/version"), _user="basic-auth-user@example.com")

    assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/mcpgateway/test_version_scope.py -v`
Expected: FAIL — the narrowed cases return 200, because the current check is unreachable

- [ ] **Step 3: Replace the dead check**

In `mcpgateway/version.py`:

1. Delete the whole `_has_version_admin_access` function (lines 1228-1255).
2. Remove `from mcpgateway.auth import normalize_token_teams` (line 72) — it becomes unused.
3. Replace the guard at line 1359:

```python
    if not _has_version_admin_access(_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin permissions required")
```

with:

```python
    # First-Party
    from mcpgateway.auth_context import is_unrestricted_platform_admin  # pylint: disable=import-outside-toplevel
    from mcpgateway.db import fresh_db_session  # pylint: disable=import-outside-toplevel
    from mcpgateway.middleware.rbac import _GLOBAL_SCOPE_DENIED_MSG  # pylint: disable=import-outside-toplevel

    # require_admin_auth is kept as the dependency because it supports HTTP Basic
    # and the browser login redirect; get_current_user_with_permissions supports
    # neither. It returns a bare email string and never consults token_teams, so
    # the Layer-1 check happens here instead.
    with fresh_db_session() as _db:
        if not await is_unrestricted_platform_admin(request, _user, _db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_GLOBAL_SCOPE_DENIED_MSG)
```

Update the endpoint docstring's `Raises:` block to say the caller needs an unrestricted platform-admin token.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/mcpgateway/test_version_scope.py tests/unit/mcpgateway/test_version.py -v`
Expected: PASS. Several of the 28 existing tests in `test_version.py` will need their auth stubs updated — they currently rely on the string escape hatch. Patch `mcpgateway.auth_context.is_unrestricted_platform_admin` to return `True` in those, rather than weakening the guard.

- [ ] **Step 5: Verify the Admin UI diagnostics path**

Run:
```bash
grep -n "version?partial=true" mcpgateway/admin_ui/initialization.js mcpgateway/admin_ui/tabs.js
```
Expected: both hits present. Confirm manually or in an integration test that a browser session (cookie auth, DB-resolved admin) still renders the diagnostics tab rather than a 403.

- [ ] **Step 6: Commit**

```bash
make pre-commit
git add mcpgateway/version.py tests/unit/mcpgateway/test_version_scope.py tests/unit/mcpgateway/test_version.py
git commit -s -m "fix(version): enforce unrestricted admin scope on diagnostics

_has_version_admin_access received a bare email string from require_admin_auth,
hit its isinstance(user, str) branch and returned True, so the narrowing check it
documented was unreachable. The check now runs inside the handler against the
request.

Deliberately keeps require_admin_auth as the dependency: it supports HTTP Basic
and the browser login redirect, and get_current_user_with_permissions supports
neither, so swapping it would 401 basic-auth monitoring callers rather than
scoping them.

Refs #5982"
```

---

### Task 9: Drift guard

**Files:**
- Create: `tests/unit/mcpgateway/test_global_record_scope.py`

**Interfaces:**
- Consumes: `wrapper.__mcpgateway_scope_class__` marker (Task 1); `collect_routes` from `tests/helpers/router_helpers.py`.
- Produces: the five manifests, which become the authoritative route classification.

Seed the manifests from spec Appendix A: `GLOBAL_ONLY` from A.1, `GLOBAL_ONLY_DEFERRED` from A.2 and A.4, `FILTERED_READ` and `TEAM_SCOPABLE` from A.1, `EXEMPT` from A.3.

**`GLOBAL_ONLY_DEFERRED` is load-bearing.** Without it the 64 deferred routes would sit in `GLOBAL_ONLY`, and `test_global_only_routes_carry_the_guard` would fail on day one for every one of them. Splitting the bucket lets the classification test cover them while the guard test only holds routes this change actually migrated.

**Do not iterate `app.routes` directly — it does not contain leaf routes.** On FastAPI 0.137+, `include_router` stores lazy `_IncludedRouter` wrappers, so `app.routes` yields 26 wrapper/mount objects with empty paths, not the hundreds of real routes. A guard written against `app.routes` passes vacuously while checking nothing. Use the existing `collect_routes()` helper in `tests/helpers/router_helpers.py`, which descends the wrappers and returns `(full_path, route, include_deps)` triples. `tests/unit/mcpgateway/test_api_versioning_parity.py` is the working precedent.

`collect_routes` also solves guard detection: `include_deps` accumulates dependencies from every enclosing wrapper, which is how `routers/metrics_maintenance.py:27`'s router-level `dependencies=[Depends(require_admin_auth)]` becomes visible. A decorator-only check would report those four routes as unguarded.

**Every route is mounted twice.** `mcpgateway/api/v1/__init__.py` assembles the same sub-routers into a versioned router (prefix `/v1`, `build_v1_router`) and an unversioned legacy router (`build_legacy_router`), and `main.py:12797` mounts both. So `/compliance/reports` and `/v1/compliance/reports` are distinct entries. Manifests key on the **unversioned** path and the test strips a leading `/v1` before lookup, so one entry covers both mounts.

**Mounting is conditional.** The compliance router is included only when `settings.mcpgateway_admin_api_enabled` is true (`api/v1/__init__.py:265`), which defaults to `False` in `config.py`. The classification test therefore checks whatever is mounted; a dedicated presence test asserts the compliance routes appear when the flag is on, so the suite cannot silently lose coverage of them.

- [ ] **Step 1: Write the test**

Create `tests/unit/mcpgateway/test_global_record_scope.py`:

```python
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
# Populated in Step 3 from the mounted app; 64 entries.
GLOBAL_ONLY_DEFERRED = set()

# Global records read with Layer-1 filtering instead of a hard deny — spec §3.4.
FILTERED_READ = {
    ("GET", "/rbac/roles"),
    ("GET", "/rbac/roles/{role_id}"),
}

# Records carrying a team association via UserRole.scope_id — spec §3.5.
TEAM_SCOPABLE = {
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
    ("GET", "/gateway/models"): "Feeds the LLM Chat model selector; authenticated but deliberately not admin-scoped",
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

    Args:
        route: A leaf route.
        include_deps: Dependencies accumulated from enclosing routers.

    Returns:
        bool: ``True`` when any admin guard applies.
    """
    if _scope_class(route) is not None:
        return True
    deps = list(getattr(route, "dependencies", []) or []) + list(include_deps or [])
    return any("admin" in repr(dep).lower() for dep in deps)


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
```

- [ ] **Step 2: Run the test — expect the canary to pass and classification to fail**

Run: `pytest tests/unit/mcpgateway/test_global_record_scope.py -v`
Expected: `test_collect_routes_actually_finds_routes` PASSES (proving the helper reaches real routes), `test_every_admin_route_is_classified` FAILS listing the unclassified admin routes.

If the canary fails, stop — `collect_routes` is not reaching leaf routes and every other assertion here is meaningless.

- [ ] **Step 3: Populate `GLOBAL_ONLY_DEFERRED` from the failure output**

The failing assertion prints the exact `(method, path)` tuples. Generate the same list directly to cross-check against spec Appendix A.2/A.4:

```bash
./.venv/bin/python -c "
from mcpgateway.config import settings
from mcpgateway.main import app
from tests.helpers.router_helpers import collect_routes
seen=set()
for full_path, route, deps in collect_routes(app):
    p = full_path[3:] if full_path.startswith('/v1/') else full_path
    for m in sorted((getattr(route,'methods',set()) or set())-{'HEAD','OPTIONS'}):
        seen.add((m,p))
for m,p in sorted(seen, key=lambda x:(x[1],x[0])):
    print(f'    (\"{m}\", \"{p}\"),')
" > "$SCRATCH/all_routes.txt"
```

Set `MCPGATEWAY_ADMIN_API_ENABLED=true` and the required secrets (`JWT_SECRET_KEY`, `AUTH_ENCRYPTION_SECRET`, `BASIC_AUTH_PASSWORD`, `PLATFORM_ADMIN_PASSWORD` — each ≥32 chars) or the app will refuse to import.

Write the A.2/A.4 tuples into `GLOBAL_ONLY_DEFERRED`. Expect 64. Anything appearing in the failure output but absent from Appendix A is a route the spec's audit missed — add it to the appendix as well as the manifest, and say so in the commit.

- [ ] **Step 4: Run the full guard**

Run: `pytest tests/unit/mcpgateway/test_global_record_scope.py -v`
Expected: 6 PASS (or 5 PASS + 1 SKIP when `MCPGATEWAY_ADMIN_API_ENABLED` is false)

- [ ] **Step 5: Commit**

```bash
git add tests/unit/mcpgateway/test_global_record_scope.py
git commit -s -m "test: add drift guard for admin routes over global records

Manifest-driven test that fails when an admin route over a team-less record is
unclassified, when a migrated route loses its guard, when a manifest entry goes
stale, when a route is classified twice, or when the deferred bucket grows.

Routes are collected with tests/helpers/router_helpers.collect_routes rather than
by iterating app.routes, which on FastAPI 0.137+ holds lazy _IncludedRouter
wrappers instead of leaf routes — a guard written against it would pass while
checking nothing. A canary test asserts the collector actually finds routes.

Guard detection inspects the dependencies collect_routes accumulates from
enclosing routers as well as endpoint attributes, because metrics_maintenance
guards its routes through a router-level dependency that a decorator-only check
would miss.

Paths are normalized to their unversioned form, since every sub-router is mounted
both under /v1 and unversioned.

Refs #5982"
```

---

### Task 10: Minting-side warning and docs sweep

**Files:**
- Modify: `mcpgateway/utils/create_jwt_token.py` (around the rich-token branch at line 495)
- Modify: `CLAUDE.md`, `README.md` (lines 213, 245, 425, 542, 626, 658, 949), `docs/docs/manage/export-import-reference.md:184`, `docs/docs/manage/export-import-tutorial.md:20`, `docs/docs/manage/sso-adfs-tutorial.md:60`, `Makefile:5979`
- Test: `tests/unit/mcpgateway/utils/test_create_jwt_token_warning.py` (create)

**Interfaces:** none produced or consumed.

**Why this is in scope:** `create_jwt_token` stays in simple-token mode unless one of `--admin` / `--teams` / `--scopes` / `--full_name` is passed (line 495). In simple mode `teams` is `_TEAMS_UNSET`, so the claim is omitted (line 162), and `normalize_token_teams` maps a missing key to `[]` — public-only. The documented invocation therefore mints a token this change rejects.

The `export-import-*` docs mint that token *for export/import, which touches roots* — already Rule A today. **Those docs are already broken before this change**, so this repairs live breakage rather than creating it. `docs/docs/manage/api-usage.md` already gets it right and is the model to follow.

Do **not** "fix" this by exempting claim-less tokens. A missing `teams` key resolving to `[]` is the secure default the whole Layer-1 model rests on; changing it would silently widen roots access.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/mcpgateway/utils/test_create_jwt_token_warning.py`:

```python
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_create_jwt_token_warning.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Simple-token minting warning.
"""

# First-Party
from mcpgateway.utils.create_jwt_token import _warn_if_simple_token_for_admin


def test_warns_when_simple_token_requested_for_admin(capsys):
    _warn_if_simple_token_for_admin(username="admin@example.com", rich_mode=False, is_known_admin=True)
    err = capsys.readouterr().err
    assert "public-only" in err
    assert "--admin" in err


def test_silent_in_rich_mode(capsys):
    _warn_if_simple_token_for_admin(username="admin@example.com", rich_mode=True, is_known_admin=True)
    assert capsys.readouterr().err == ""


def test_silent_for_non_admin(capsys):
    _warn_if_simple_token_for_admin(username="user@example.com", rich_mode=False, is_known_admin=False)
    assert capsys.readouterr().err == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/mcpgateway/utils/test_create_jwt_token_warning.py -v`
Expected: FAIL — `ImportError: cannot import name '_warn_if_simple_token_for_admin'`

- [ ] **Step 3: Add the warning**

In `mcpgateway/utils/create_jwt_token.py`, add above the CLI entry point:

```python
def _warn_if_simple_token_for_admin(username: str, rich_mode: bool, is_known_admin: bool) -> None:
    """Warn when a simple token is minted for a user who is a platform admin.

    Simple-token mode omits the ``teams`` claim entirely, and a missing key
    normalizes to ``[]`` — public-only. A token minted this way for an admin does
    not carry admin authority and will be rejected by global-record routes.

    Args:
        username: Token subject.
        rich_mode: Whether one of ``--admin`` / ``--teams`` / ``--scopes`` / ``--full-name`` was passed.
        is_known_admin: Whether the subject resolves to a platform admin.
    """
    if rich_mode or not is_known_admin:
        return
    print(
        f"⚠️  WARNING: '{username}' is a platform admin, but this token omits the `teams` claim,\n"
        "   which normalizes to public-only scope. It will be rejected by routes that\n"
        "   manage global records. Pass --admin to mint an unrestricted admin token.",
        file=sys.stderr,
    )
```

Ensure `sys` is imported. Call it in the CLI path immediately after `rich_mode` is determined (the `if args.admin or args.teams or args.scopes or args.full_name:` condition at line 495), resolving `is_known_admin` by comparing `args.username` against `settings.platform_admin_email`, falling back to `False` if settings cannot be loaded.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/mcpgateway/utils/test_create_jwt_token_warning.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Sweep the docs**

Add `--admin` to every simple-form admin invocation. Locate them with:

```bash
grep -rn "create_jwt_token" README.md CLAUDE.md Makefile docs/docs/ | grep "admin@example.com"
```

Update each so it reads, adapting to the surrounding quoting style:

```bash
python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --admin --exp 10080 --secret "$JWT_SECRET_KEY"
```

Confirmed sites: `CLAUDE.md` *MCP Helpers*; `README.md` lines 213, 245, 425, 542, 626, 658, 949; `docs/docs/manage/export-import-reference.md:184`; `docs/docs/manage/export-import-tutorial.md:20`; `docs/docs/manage/sso-adfs-tutorial.md:60`; `Makefile:5979`. Leave `docs/docs/manage/api-usage.md` alone — its admin example is already correct and its `--teams` example is deliberately for a non-admin user.

- [ ] **Step 6: Commit**

```bash
make pre-commit
git add mcpgateway/utils/create_jwt_token.py tests/unit/mcpgateway/utils/test_create_jwt_token_warning.py README.md CLAUDE.md Makefile docs/docs/
git commit -s -m "fix(cli): warn when minting a public-only token for a platform admin

Simple-token mode omits the teams claim, which normalizes to public-only, so the
invocation documented across README and the export-import guides mints a token
without admin authority. Those guides cover export/import, which touches roots
and is already denied today, so this repairs live breakage rather than creating
it.

Adds --admin to every documented admin invocation and warns at mint time.

Refs #5982"
```

---

### Task 11: Documentation

**Files:**
- Modify: `docs/docs/manage/rbac.md` (new section)
- Modify: `CLAUDE.md` (Security Invariants block)

**Interfaces:** none.

- [ ] **Step 1: Document the four classes in `docs/docs/manage/rbac.md`**

Add a section titled *Scope rules for global records* containing: the four class definitions from spec §1 (global-only, filtered-read, team-scopable, exempt); the classification table from Appendix A.1; a pointer to `tests/unit/mcpgateway/test_global_record_scope.py` as the authoritative manifest; and a note that the A.2/A.4 routes are pending follow-up.

- [ ] **Step 2: Add the invariant to `CLAUDE.md`**

In the *Security Invariants (Required)* list, add:

```markdown
- Do not re-implement the global-record admin scope check. Use `require_global_admin_permission()` for whole-endpoint guards and `require_unrestricted_platform_admin()` for conditional call sites (both in `mcpgateway/middleware/rbac.py`). New admin routes over records with no team association must be classified in `tests/unit/mcpgateway/test_global_record_scope.py`; the drift guard fails the build otherwise.
```

- [ ] **Step 3: Verify docs build**

Run: `make docs-build` (skip if the target does not exist; then just confirm the Markdown renders in review)

- [ ] **Step 4: Commit**

```bash
git add docs/docs/manage/rbac.md CLAUDE.md
git commit -s -m "docs: document the global-record admin scope rule

Defines the four route classes, records the classification table, points at the
manifest test as the authoritative source, and adds the do-not-reimplement
invariant.

Refs #5982"
```

---

### Task 12: Pre-merge validation and follow-up issues

**Files:** none modified.

- [ ] **Step 1: Run the validation gate**

Run in order, from the worktree root. Each must pass or carry a documented waiver:

```bash
make ruff interrogate pylint
make test
make coverage diff-cover
make detect-secrets-scan
```

The Docker-based gates (`make docker-nuke docker-prod-rust testing-up RUST_MCP_MODE=` then `make test-mcp-protocol-e2e test-mcp-rbac test-protocol-compliance`) should also run. Those harnesses mint unrestricted tokens — `tests/populate/populate.py:85-89` and `tests/loadtest/locustfile_mcp_isolation.py:224` pass `is_admin=True, teams=None`, and `tests/loadtest/locustfile.py:610` sets `token_use: "session"` which resolves through the DB — so they are expected to pass unchanged. If any fails, that is a real regression, not a fixture problem.

- [ ] **Step 2: Write the release note**

Record the breaking change: callers using a team-narrowed or claim-less admin token now receive 403 on `/compliance/*`, role-definition mutation, global role assignment, and `/version`. Remediation is to reissue the token with `--admin`, or create it via the Admin UI without selecting a team. State explicitly that **omitting the `teams` claim is not a remediation** — a missing key normalizes to `[]`, which is public-only. Note that Admin UI sessions, basic auth, and proxy auth are unaffected.

- [ ] **Step 3: File follow-up issue 1**

Re-verify the route counts and line references against the merged code first, then file:

- **Title:** `[BUG]: Team-narrowed admin tokens bypass Layer 1 on admin routes guarded by require_permission`
- **Labels:** `bug`, `security`, `rbac`, `api`, `triage`
- **Template:** `.github/ISSUE_TEMPLATE/bug-report-code.md`
- **Body:** `services/permission_service.py:125-132` suppresses admin bypass only for public-only tokens; with a non-empty `token_teams` the `elif allow_admin_bypass and await self._is_user_admin(...)` branch returns `True` unconditionally, so a token narrowed to one team retains full admin authority. This contradicts `is_unrestricted_platform_admin()` (`auth_context.py:788-799`), which rejects any non-`None` `token_teams`. Affected surface: the 60 Rule D routes in spec Appendix A.2 plus the 4 router-level-guarded routes in A.4 — LLM config and admin, observability, SSO provider management, SIEM destinations, log search, runtime mode, toolops, metrics maintenance. **Frame this as a question, not an accusation:** it is not self-evident whether the current behaviour is intended, and maintainers must decide whether Layer 1 narrowing binds admin bypass everywhere (a bug) or only where routes opt in (a design choice needing documentation). Link this spec and the PR resolving the A.1 surfaces. Note that #5982 stays open until this lands.

- [ ] **Step 4: File follow-up issue 2**

- **Title:** `[CHORE]: Consolidate require_admin_auth and get_current_user_with_permissions for admin-only routes`
- **Labels:** `chore`, `rbac`, `api`, `triage`
- **Template:** `.github/ISSUE_TEMPLATE/chore-task--devops--linting--maintenance-.md`
- **Body:** Two admin dependencies coexist with disjoint capabilities. `require_admin_auth` (`utils/verify_credentials.py:1623`) supports HTTP Basic and browser login redirects but returns a bare email string and never consults `token_teams`. `get_current_user_with_permissions` (`middleware/rbac.py:238`) resolves full Layer-1 context but has no HTTP Basic path. This forced Task 8 to keep `require_admin_auth` on `/version` and add the narrowing check inside the handler, because swapping would have 401'd basic-auth callers; `metrics_maintenance` has the same shape at router level. The cleanup is to give one dependency both capabilities. Explicitly a maintenance item — no behaviour change requested.

- [ ] **Step 5: Update the spec status**

Change the spec header's `**Status:**` line to `Implemented — see PR <number>; follow-up 1 outstanding`.

```bash
git add docs/superpowers/specs/2026-08-06-global-record-admin-scope-design.md
git commit -s -m "docs: mark global-record scope spec as implemented

Refs #5982"
```

---

## Self-Review Notes

**Spec coverage:** §1 → Tasks 9, 11. §2 → Task 1. §3.1 → Task 3. §3.2 → Task 4. §3.3 → Task 5. §3.4 → Task 6. §3.5 → Task 7. §3.6 → Task 8. §4 → Task 9. §5 → Tasks 1, 6, 7, 8, 9 (see the testing-strategy note below). §5.1 → Task 2 plus the call-site updates in Tasks 4 and 5. §5.2 → Task 12 Step 1. §6 → Tasks 10, 11. Appendix A → Task 9 manifests. Follow-up issues → Task 12.

**Testing strategy, and why it is not one deny test per route.** Router modules are imported once per session, and 26 suites import them under `patch_rbac_decorators`, which swaps the RBAC decorators for no-ops. Whichever module imports a router first decides whether its decorators are real. A route-level deny test in a second module would pass or fail on import order — an order-dependent flake dressed up as coverage.

So the spec's three admin contexts (unrestricted / team-scoped / public-only) are covered in layers:

| Layer | Where | Proves |
|---|---|---|
| Decorator behaviour | Task 1 — real decorator, all three contexts, mocked predicate | What the guard does |
| Route carries the guard | Tasks 5, 9 — `__mcpgateway_scope_class__` marker assertions | That these routes use it |
| Handler-body logic | Tasks 6, 7 — direct calls, no decorator involvement | Filtering and the assignment scope matrix |
| Raise-helper call sites | Task 3 — roots suites | Conditional guards still fire |

Together these give the same guarantee as per-route deny tests, without the import-order hazard.

**Deliberately deferred:** the 64 A.2/A.4 routes are classified in Task 9 but not remediated — follow-up issue 1.

**Type consistency:** `require_unrestricted_platform_admin(request, user, db)` is used with that exact signature in Tasks 3, 7, and 8. `require_global_admin_permission()` takes no arguments in Tasks 1, 4, and 5. `admin_user_context(token_teams, email=...)` and `scoped_request(token_teams, path=...)` keep the same signatures across Tasks 2, 4, 5, 6, 7, and 8. `_authorize_assignment_scope(request, user, db, scope, scope_id, target_email)` and `_load_assignment(db, user_email, role_id)` are defined and used only within Task 7. The `__mcpgateway_scope_class__` marker is set in Task 1 and read in Task 9.
