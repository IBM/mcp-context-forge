# Global-Record Admin Scope Standardization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish one canonical scope rule for admin-only routes that manage records with no team association, apply it to the four rule-divergent surfaces, and add a drift guard so new global-record endpoints cannot land unclassified.

**Architecture:** Two shared helpers in `mcpgateway/middleware/rbac.py` — a raise-form function for conditional call sites and a decorator for whole-endpoint guards — both delegating to the existing `is_unrestricted_platform_admin()` predicate in `auth_context.py`. Route handlers stop reimplementing the check. A manifest-driven test walks `app.routes` and fails when an admin route is unclassified or a `GLOBAL_ONLY` route loses its guard.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy (sync sessions), pytest + pytest-asyncio, Ruff (line length 200).

**Spec:** `docs/superpowers/specs/2026-08-06-global-record-admin-scope-design.md`
**Issue:** [IBM/mcp-context-forge#5982](https://github.com/IBM/mcp-context-forge/issues/5982)

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

### Task 2: Shared test fixture for route-level scope contexts

**Files:**
- Create: `tests/helpers/scope.py`
- Test: `tests/unit/mcpgateway/middleware/test_global_scope_helpers.py` (extend — verify the fixture itself)

**Interfaces:**
- Consumes: nothing from Task 1 at runtime.
- Produces: `admin_user_context(token_teams, email="admin@example.com") -> dict` and `scoped_request(token_teams, path="/") -> MagicMock`, used by every route task (3–8).

**Why this exists:** spec §5.1. The existing suites override `get_current_user_with_permissions` with a bare dict such as `{"email": "admin@example.com", "is_admin": True}` (`tests/unit/mcpgateway/routers/test_compliance_router.py:64`). That dict carries no `request.state.token_teams`, so `get_rpc_filter_context()` falls back to `normalize_token_teams()` on an absent payload and resolves to `[]` — public-only. Every such test would 403 once the guard lands. One shared fixture prevents 80 individual fixes from drifting apart.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/mcpgateway/middleware/test_global_scope_helpers.py`:

```python
# First-Party
from tests.helpers.scope import admin_user_context, scoped_request


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/mcpgateway/middleware/test_global_scope_helpers.py::test_scope_fixture_shapes -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.helpers.scope'`

- [ ] **Step 3: Create the fixture module**

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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/mcpgateway/middleware/test_global_scope_helpers.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/helpers/scope.py tests/unit/mcpgateway/middleware/test_global_scope_helpers.py
git commit -s -m "test: add shared Layer-1 scope fixtures for route tests

Route suites that override the auth dependency with a bare dict resolve to
public-only, because the scope resolver falls back to normalize_token_teams() on
an absent JWT payload. One shared constructor for the three admin contexts keeps
the ~80 affected tests from drifting apart as they are migrated.

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

- [ ] **Step 1: Write the failing tests**

Replace the auth fixtures in `tests/unit/mcpgateway/routers/test_compliance_router.py` and add scope coverage. Add near the top:

```python
# First-Party
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from tests.helpers.scope import admin_user_context

COMPLIANCE_ROUTES = [
    ("GET", "/compliance/frameworks"),
    ("POST", "/compliance/reports"),
    ("GET", "/compliance/reports"),
    ("GET", "/compliance/reports/some-id"),
    ("GET", "/compliance/reports/some-id/export"),
]


@pytest.mark.parametrize("method,path", COMPLIANCE_ROUTES)
@pytest.mark.parametrize("token_teams", [[], ["team-a"]])
def test_narrowed_and_public_only_admins_are_denied(app, client, method, path, token_teams):
    """Compliance reports aggregate every team; a narrowed token must not read them."""
    app.dependency_overrides[get_current_user_with_permissions] = lambda: admin_user_context(token_teams)
    try:
        response = client.request(method, path, json={} if method == "POST" else None)
        assert response.status_code == 403
        assert "--admin" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_current_user_with_permissions, None)


@pytest.mark.parametrize("method,path", COMPLIANCE_ROUTES)
def test_unrestricted_admin_is_not_denied_by_scope(app, client, method, path):
    """Unrestricted admins pass the scope gate; any non-403 status is acceptable here."""
    app.dependency_overrides[get_current_user_with_permissions] = lambda: admin_user_context(None)
    try:
        response = client.request(method, path, json={} if method == "POST" else None)
        assert response.status_code != 403
    finally:
        app.dependency_overrides.pop(get_current_user_with_permissions, None)
```

Then update the two existing overrides so they no longer resolve to public-only:
- line 64: replace the returned dict with `admin_user_context(None)`
- line 325 (`no_auth`) and line 349 (`non_admin_user`): keep their intent, but build them from `admin_user_context([])` / a non-admin dict so the resolved scope is explicit rather than accidental.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/mcpgateway/routers/test_compliance_router.py -v`
Expected: the new deny tests FAIL with 200/404 instead of 403

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
async def list_frameworks(request: Request, user=Depends(get_current_user_with_permissions)) -> List[FrameworkInfo]:  # pylint: disable=unused-argument
```

Apply the same two changes at lines 144, 188, 229, and 272. Each endpoint's docstring needs a `request` entry in its `Args:` block or `make interrogate` and pylint will complain:

```
        request: Incoming request, used to resolve Layer-1 token scope.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/mcpgateway/routers/test_compliance_router.py -v`
Expected: PASS (all, including the 10 new deny cases and 5 allow cases)

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

Create `tests/unit/mcpgateway/routers/test_rbac_scope.py`:

```python
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_rbac_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope behavior for the RBAC role routes.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from tests.helpers.scope import admin_user_context

ROLE_MUTATIONS = [
    ("POST", "/rbac/roles", {"name": "r", "description": "d", "scope": "team", "permissions": []}),
    ("PUT", "/rbac/roles/some-id", {"description": "d"}),
    ("DELETE", "/rbac/roles/some-id", None),
]


@pytest.mark.parametrize("method,path,body", ROLE_MUTATIONS)
@pytest.mark.parametrize("token_teams", [[], ["team-a"]])
def test_role_definition_mutations_deny_narrowed_admin(app, client, method, path, body, token_teams):
    """Role definitions are global records even when scope='team' — the row has no team_id."""
    app.dependency_overrides[get_current_user_with_permissions] = lambda: admin_user_context(token_teams)
    try:
        response = client.request(method, path, json=body)
        assert response.status_code == 403
        assert "--admin" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_current_user_with_permissions, None)


@pytest.mark.parametrize("method,path,body", ROLE_MUTATIONS)
def test_role_definition_mutations_allow_unrestricted_admin(app, client, method, path, body):
    app.dependency_overrides[get_current_user_with_permissions] = lambda: admin_user_context(None)
    try:
        assert client.request(method, path, json=body).status_code != 403
    finally:
        app.dependency_overrides.pop(get_current_user_with_permissions, None)
```

If `app` and `client` fixtures are not already available at this path, reuse the pattern from `tests/unit/mcpgateway/routers/test_compliance_router.py` — copy its fixture definitions rather than inventing new ones.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/mcpgateway/routers/test_rbac_scope.py -v`
Expected: FAIL — narrowed admin gets a non-403 status

- [ ] **Step 3: Apply the guard**

In `mcpgateway/routers/rbac.py`, update the import on line 12:

```python
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_global_admin_permission, require_permission
```

`require_admin_permission` is no longer used in this file after this task — remove it. Add `Request` to the FastAPI import on line 5.

Change line 81, 212, and 259 from `@require_admin_permission()` to `@require_global_admin_permission()`, and add `request: Request` as the first parameter of each handler:

```python
@router.post("/roles", response_model=RoleResponse)
@require_global_admin_permission()
async def create_role(request: Request, role_data: RoleCreateRequest, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
```

```python
@router.put("/roles/{role_id}", response_model=RoleResponse)
@require_global_admin_permission()
async def update_role(request: Request, role_id: str, role_data: RoleUpdateRequest, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
```

```python
@router.delete("/roles/{role_id}")
@require_global_admin_permission()
async def delete_role(request: Request, role_id: str, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
```

Add a `request:` line to each handler's `Args:` docstring block.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/mcpgateway/routers/test_rbac_scope.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
make pre-commit
git add mcpgateway/routers/rbac.py tests/unit/mcpgateway/routers/test_rbac_scope.py
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

Append to `tests/unit/mcpgateway/routers/test_rbac_scope.py`:

```python
def test_list_roles_hides_global_roles_from_narrowed_admin(app, client, monkeypatch):
    """Narrowed admins see non-global roles only — a 403 here would break the UI role picker."""
    # Standard
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    rows = [
        SimpleNamespace(id="1", name="platform_admin", scope="global"),
        SimpleNamespace(id="2", name="team_admin", scope="team"),
    ]
    monkeypatch.setattr("mcpgateway.services.role_service.RoleService.list_roles", AsyncMock(return_value=rows))

    app.dependency_overrides[get_current_user_with_permissions] = lambda: admin_user_context(["team-a"])
    try:
        response = client.get("/rbac/roles")
        assert response.status_code == 200
        scopes = {r["scope"] for r in response.json()}
        assert "global" not in scopes
    finally:
        app.dependency_overrides.pop(get_current_user_with_permissions, None)


def test_list_roles_shows_everything_to_unrestricted_admin(app, client, monkeypatch):
    # Standard
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    rows = [
        SimpleNamespace(id="1", name="platform_admin", scope="global"),
        SimpleNamespace(id="2", name="team_admin", scope="team"),
    ]
    monkeypatch.setattr("mcpgateway.services.role_service.RoleService.list_roles", AsyncMock(return_value=rows))

    app.dependency_overrides[get_current_user_with_permissions] = lambda: admin_user_context(None)
    try:
        response = client.get("/rbac/roles")
        assert response.status_code == 200
        assert len(response.json()) == 2
    finally:
        app.dependency_overrides.pop(get_current_user_with_permissions, None)


def test_get_global_role_returns_404_for_narrowed_admin(app, client, monkeypatch):
    """404, not 403 — do not confirm the existence of a role the caller may not enumerate."""
    # Standard
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "mcpgateway.services.role_service.RoleService.get_role_by_id",
        AsyncMock(return_value=SimpleNamespace(id="1", name="platform_admin", scope="global")),
    )

    app.dependency_overrides[get_current_user_with_permissions] = lambda: admin_user_context(["team-a"])
    try:
        assert client.get("/rbac/roles/1").status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user_with_permissions, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/mcpgateway/routers/test_rbac_scope.py -k "list_roles or get_global_role" -v`
Expected: FAIL — global role is present in the narrowed list, and the detail route returns 200

- [ ] **Step 3: Add the filtering**

In `mcpgateway/routers/rbac.py`, add to the first-party imports:

```python
from mcpgateway.auth_context import get_scoped_resource_access_context
```

Add `request: Request` as the first parameter of `list_roles` and `get_role`, with a matching `Args:` docstring line.

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
Expected: PASS (11 tests)

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

Append to `tests/unit/mcpgateway/routers/test_rbac_scope.py`:

```python
def test_narrowed_admin_cannot_assign_global_role(app, client):
    """The escalation path: a narrowed admin minting themselves a global '*' role."""
    app.dependency_overrides[get_current_user_with_permissions] = lambda: admin_user_context(["team-a"])
    try:
        response = client.post(
            "/rbac/users/victim@example.com/roles",
            json={"role_id": "platform-admin-role", "scope": "global", "scope_id": None},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user_with_permissions, None)


def test_narrowed_admin_cannot_assign_into_uncovered_team(app, client):
    app.dependency_overrides[get_current_user_with_permissions] = lambda: admin_user_context(["team-a"])
    try:
        response = client.post(
            "/rbac/users/victim@example.com/roles",
            json={"role_id": "r", "scope": "team", "scope_id": "team-b"},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user_with_permissions, None)


def test_narrowed_admin_may_assign_within_covered_team(app, client):
    app.dependency_overrides[get_current_user_with_permissions] = lambda: admin_user_context(["team-a"])
    try:
        response = client.post(
            "/rbac/users/member@example.com/roles",
            json={"role_id": "r", "scope": "team", "scope_id": "team-a"},
        )
        assert response.status_code != 403
    finally:
        app.dependency_overrides.pop(get_current_user_with_permissions, None)


def test_revoke_reads_scope_from_the_stored_row_not_the_request(app, client, monkeypatch):
    """A client must not be able to relabel a global assignment to get it revoked."""
    # Standard
    from types import SimpleNamespace

    stored = SimpleNamespace(scope="global", scope_id=None)
    monkeypatch.setattr("mcpgateway.routers.rbac._load_assignment", lambda db, email, role_id: stored)

    app.dependency_overrides[get_current_user_with_permissions] = lambda: admin_user_context(["team-a"])
    try:
        # Client claims team scope; the stored row says global, so this must be denied.
        response = client.delete("/rbac/users/victim@example.com/roles/r?scope=team&scope_id=team-a")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user_with_permissions, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/mcpgateway/routers/test_rbac_scope.py -k "assign or revoke" -v`
Expected: FAIL — assignments succeed and `_load_assignment` does not exist

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

In `assign_role_to_user`, add `request: Request` as the first parameter and insert before `role_service.assign_role_to_user(...)`:

```python
        await _authorize_assignment_scope(request, user, db, assignment_data.scope, assignment_data.scope_id, user_email)
```

In `revoke_user_role`, add `request: Request` as the first parameter and replace the opening of the `try` block so the stored row — not the query params — drives authorization:

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
Expected: PASS (15 tests)

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
- Consumes: `wrapper.__mcpgateway_scope_class__` marker (Task 1); the FastAPI `app` from `mcpgateway.main`.
- Produces: the five manifests, which become the authoritative route classification.

Seed the manifests from spec Appendix A: `GLOBAL_ONLY` from A.1, `GLOBAL_ONLY_DEFERRED` from A.2 and A.4, `FILTERED_READ` and `TEAM_SCOPABLE` from A.1, `EXEMPT` from A.3.

**`GLOBAL_ONLY_DEFERRED` is load-bearing.** Without it the 64 deferred routes would sit in `GLOBAL_ONLY`, and `test_global_only_routes_carry_the_guard` would fail on day one for every one of them. Splitting the bucket lets the classification test cover them while the guard test only holds routes this change actually migrated.

**Guard detection must inspect dependencies, not just decorators.** `routers/metrics_maintenance.py:27` guards all four of its routes through a router-level `dependencies=[Depends(require_admin_auth)]`. A decorator-only check reports them as unguarded.

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
from mcpgateway.main import app

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
GLOBAL_ONLY_DEFERRED_COUNT = 64

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


def _routes():
    """Yield (method, path, route) for every mounted API route.

    Yields:
        tuple: ``(method, path, route)`` for each HTTP method a route serves.
    """
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set():
            if method in {"HEAD", "OPTIONS"}:
                continue
            yield method, route.path, route


def _scope_class(route):
    """Return the scope-class marker set by require_global_admin_permission.

    Args:
        route: A mounted route.

    Returns:
        Optional[str]: The marker, or ``None`` when the guard is absent.
    """
    return getattr(getattr(route, "endpoint", None), "__mcpgateway_scope_class__", None)


def test_global_only_routes_carry_the_guard():
    """Every migrated route must actually carry the decorator, not just be listed."""
    missing = {(m, p) for m, p, route in _routes() if (m, p) in GLOBAL_ONLY and _scope_class(route) != "global_only"}
    assert not missing, f"GLOBAL_ONLY routes missing @require_global_admin_permission: {sorted(missing)}\nSee docs/docs/manage/rbac.md"


def test_manifests_are_disjoint():
    """A route must not be silently reclassified by appearing in two buckets."""
    buckets = [GLOBAL_ONLY, FILTERED_READ, TEAM_SCOPABLE, set(EXEMPT)]
    seen = set()
    for bucket in buckets:
        overlap = seen & bucket
        assert not overlap, f"Route classified twice: {sorted(overlap)}"
        seen |= bucket


def test_deferred_bucket_only_shrinks():
    """Deferral records existing debt; it is not an escape hatch for new routes."""
    assert GLOBAL_ONLY_DEFERRED_COUNT <= 64, "GLOBAL_ONLY_DEFERRED grew. New global-record routes must use the canonical rule, not join the deferred set. See docs/docs/manage/rbac.md"


@pytest.mark.xfail(reason="Enable once the A.2/A.4 routes are enumerated route-by-route in the manifest", strict=False)
def test_every_admin_route_is_classified():
    """No admin route over a global record may be left unclassified.

    Guard detection inspects resolved route dependencies as well as endpoint
    attributes: metrics_maintenance guards its routes through a router-level
    dependencies=[Depends(require_admin_auth)], which a decorator-only check
    would report as unguarded.
    """
    classified = GLOBAL_ONLY | FILTERED_READ | TEAM_SCOPABLE | set(EXEMPT)
    unclassified = set()
    for method, path, route in _routes():
        if (method, path) in classified:
            continue
        has_dep_guard = any("admin" in repr(dep).lower() for dep in getattr(route, "dependencies", []) or [])
        has_endpoint_guard = _scope_class(route) is not None
        if has_dep_guard or has_endpoint_guard:
            unclassified.add((method, path))
    assert not unclassified, f"Unclassified admin routes: {sorted(unclassified)}\nClassify each in tests/unit/mcpgateway/test_global_record_scope.py per docs/docs/manage/rbac.md"
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/unit/mcpgateway/test_global_record_scope.py -v`
Expected: 3 PASS, 1 XFAIL

`test_every_admin_route_is_classified` starts as `xfail` because enumerating all 64 deferred routes as literal `(method, path)` tuples is mechanical work best done against the mounted app. Complete it in Step 3 rather than leaving it xfail permanently.

- [ ] **Step 3: Enumerate the deferred routes and drop the xfail**

Generate the literal set from the running app:

```bash
python3 -c "
from mcpgateway.main import app
for r in app.routes:
    for m in sorted((getattr(r,'methods',set()) or set()) - {'HEAD','OPTIONS'}):
        print(f'    (\"{m}\", \"{r.path}\"),')
" | sort -u > /tmp/claude-1000/-home-suresh-dev-issue-block2-mcp-context-forge/d0d4c6f1-70ba-4c16-8734-7cc1d0cb94a6/scratchpad/all_routes.txt
```

Cross-reference against spec Appendix A.2 and A.4, write the resulting tuples into a `GLOBAL_ONLY_DEFERRED` set, replace `GLOBAL_ONLY_DEFERRED_COUNT` with `len(GLOBAL_ONLY_DEFERRED)`, add it to both `classified` and the disjointness check, and remove the `@pytest.mark.xfail` decorator.

- [ ] **Step 4: Run the full guard**

Run: `pytest tests/unit/mcpgateway/test_global_record_scope.py -v`
Expected: 4 PASS, 0 XFAIL

- [ ] **Step 5: Commit**

```bash
git add tests/unit/mcpgateway/test_global_record_scope.py
git commit -s -m "test: add drift guard for admin routes over global records

Manifest-driven test that fails when an admin route over a team-less record is
unclassified, when a migrated route loses its guard, when a route is classified
twice, or when the deferred bucket grows.

Guard detection inspects resolved route dependencies as well as endpoint
attributes, because metrics_maintenance guards its routes through a router-level
dependency that a decorator-only check would miss.

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

**Spec coverage:** §1 → Tasks 9, 11. §2 → Task 1. §3.1 → Task 3. §3.2 → Task 4. §3.3 → Task 5. §3.4 → Task 6. §3.5 → Task 7. §3.6 → Task 8. §4 → Task 9. §5 → Tasks 4–8. §5.1 → Task 2 plus the fixture rework inside Tasks 4 and 8. §5.2 → Task 12 Step 1. §6 → Tasks 10, 11. Appendix A → Task 9 manifests. Follow-up issues → Task 12.

**Deliberately deferred:** the 64 A.2/A.4 routes are classified in Task 9 but not remediated — follow-up issue 1.

**Type consistency:** `require_unrestricted_platform_admin(request, user, db)` is used with that exact signature in Tasks 3, 7, and 8. `require_global_admin_permission()` takes no arguments in Tasks 1, 4, and 5. `admin_user_context(token_teams, email=...)` and `scoped_request(token_teams, path=...)` keep the same signatures across Tasks 2, 4, 5, 6, 7, and 8. `_authorize_assignment_scope(request, user, db, scope, scope_id, target_email)` and `_load_assignment(db, user_email, role_id)` are defined and used only within Task 7. The `__mcpgateway_scope_class__` marker is set in Task 1 and read in Task 9.
