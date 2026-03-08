# Auth Context Consolidation Design

**Date:** 2026-03-08
**Scope:** Structural refactoring — same behavior, less duplication, easier to reason about, hard to bypass by mistake
**Status:** Draft v2

---

## Problem Statement

The RBAC and security permission system has grown by incremental addition. The same authorization logic is scattered across 10 distinct layers with significant duplication. The `token_teams is None` / `len(token_teams) == 0` pattern appears **~135 times** across `main.py`, `streamablehttp_transport.py`, 8+ services, `admin.py`, middleware, routers, and utilities.

### The ten overlapping layers (current state)

| Layer | File | What it checks |
|---|---|---|
| 1. `TokenScopingMiddleware` | `middleware/token_scoping.py` | Team membership, resource ownership, token restrictions (IP, time, server_id), permission enforcement |
| 2. `AdminAuthMiddleware` | `main.py:1676` | Admin status for `/admin/*` paths, JWT/cookie/API-hash/proxy auth |
| 3. `DocsAuthMiddleware` | `main.py:1596` | JWT + optional Basic Auth for `/docs`, `/redoc`, `/openapi.json` |
| 4. `AuthContextMiddleware` | `middleware/auth_middleware.py:65` | Early JWT extraction for observability/downstream (user lookup, revocation, active check) |
| 5. `HttpAuthMiddleware` | `middleware/http_auth_middleware.py:24` | Plugin hooks `HTTP_PRE_REQUEST` / `HTTP_POST_REQUEST` — can transform auth headers before JWT verify |
| 6. `get_current_user_with_permissions` | `middleware/rbac.py` | JWT decode + injects context (cookie, bearer, proxy, anonymous paths) |
| 7. `require_permission` decorator | `middleware/rbac.py` | RBAC role check per endpoint |
| 8. `PermissionService.check_permission` | `services/permission_service.py` | DB-backed role check |
| 9. Inline `token_teams is None` checks | `main.py`, `services/`, `transports/`, `utils/` | Admin bypass scattered everywhere |
| 10. Endpoint-level custom guards | e.g. `teams.py:549` | Ad-hoc authorization |

### DB calls per request (current worst case)

1. JWT verify (`AuthContextMiddleware`)
2. User lookup (`AuthContextMiddleware`) — sets `request.state.user`
3. Revocation check (`AuthContextMiddleware`)
4. JWT verify (`TokenScopingMiddleware`) — duplicate
5. Team membership check (`TokenScopingMiddleware`)
6. Resource ownership check (`TokenScopingMiddleware`)
7. JWT verify (`AdminAuthMiddleware`) — duplicate
8. User lookup (`AdminAuthMiddleware`) — duplicate
9. `has_admin_permission` (`AdminAuthMiddleware`)
10. JWT verify (`get_current_user_with_permissions`) — duplicate
11. `is_user_admin` (`PermissionService.check_permission`) — duplicate
12. `get_user_permissions` (`PermissionService`)
13. Team resolution in service (if session token) — duplicate
14. Team membership cache miss in `_auth_jwt` (transport path) — duplicate

### Existing key-name drift

The MCP StreamableHTTP transport stores teams as `"teams"` in `user_context_var`. The HTTP/RBAC layer stores it as `"token_teams"` in `request.state`. The same concept has two names in two parallel stacks.

---

## Root Cause

Multi-tenancy and RBAC were added incrementally after the core system. Each addition bolted auth logic onto existing code paths (services, transports, the 8000-line `main.py`) rather than centralizing in a dedicated layer. The result is correct behavior but very high maintenance cost: understanding one behavior requires tracing the same logic through 3+ files.

---

## Objective

Structural refactoring only — same security behavior, no new features:

- A developer adding a new service or endpoint cannot accidentally bypass auth by not knowing the intricacies
- The wrong path should be structurally difficult, not just undocumented
- Incremental — each tier ships as a separate PR, old path stays live until migration is complete

---

## Transport Landscape

Before proposing the fix, it is important to understand there are three distinct auth channels:

**Channel A: FastAPI HTTP routes** (REST API + SSE connection setup + WebSocket upgrade)
- Uses `request.state.token_teams` set by `get_current_user` in `auth.py`
- Read by `_get_token_teams_from_request` / `_get_rpc_filter_context` helpers in `main.py`
- SSE transport and WebSocket transport are data-transfer layers only — they have no auth logic. Auth for these happens in the FastAPI route handlers that initiate the connection.

**Channel B: MCP StreamableHTTP (`/mcp/*`)**
- Uses a Python `ContextVar`: `user_context_var: ContextVar[dict]` (defined at `streamablehttp_transport.py:98`)
- Auth is done by `_StreamableHttpAuthHandler._auth_jwt()` (~200 lines)
- Stores context as `{"teams": ..., "email": ..., "is_admin": ...}` — key name `"teams"`, not `"token_teams"`
- **Cannot use `request.state`** — MCP SDK tool call handlers read from `user_context_var`, not from HTTP request state

**Channel C: Services** (called by A or B)
- Receive `token_teams: Optional[List[str]]` as a parameter
- Perform inline auth checks themselves (`token_teams is None`, `len == 0`, etc.)

---

## Key Constraints Found During Analysis

### Constraint 1: The MCP transport is a separate ASGI layer
`_StreamableHttpAuthHandler` is an ASGI middleware, not a FastAPI route handler. Writing to `request.state` in a FastAPI middleware does not propagate into MCP SDK callbacks. These two mechanisms are genuinely separate and cannot be unified into one storage mechanism.

### Constraint 2: Session token admin bypass is NOT in `normalize_token_teams`
`normalize_token_teams` treats a missing `teams` key as `[]` (public-only). Session tokens have no `teams` key in the JWT — their teams are in the DB. The transport correctly special-cases admin session tokens (lines 2959–2960: `if is_admin_flag: final_teams = None`). If anything tried to apply `normalize_token_teams` uniformly to all tokens, admin session users would be locked out.

### Constraint 3: Team derivation from resource/payload must stay at decorator time
`_derive_team_from_resource` (rbac.py:387) looks up which team owns a specific resource using FastAPI-parsed URL params (`tool_id`, `server_id`). `_derive_team_from_payload` (rbac.py:414) reads the request body to find `team_id` in create operations. Both require values not available at middleware time. They must stay in `@require_permission` at route time.

### Constraint 4: `check_any_team` is per-permission, per-request
For session tokens, RBAC checks permission across ALL user teams (`check_any_team=True`) because session tokens have no embedded team scope. This flag is set inside `require_permission` based on `token_use == "session"` AND whether a team_id could be derived from the specific resource. It is per-permission-check logic, not per-request identity logic.

### Constraint 5: Plugin `HTTP_AUTH_CHECK_PERMISSION` hook is per-check
The plugin hook fires inside `require_permission` once per permission check with `(user_email, permission, team_id, is_admin)`. It is context-dependent (can inspect the specific permission being checked). Pre-resolving all permissions at middleware time is not possible. The hook must continue firing at decorator time.

### Constraint 6: `_get_rpc_filter_context` forces `is_admin=False` for public-only tokens
`main.py:391` has a critical security override: when `token_teams` is `[]` (public-only), it forces `is_admin = False` regardless of the JWT's `is_admin` claim. `AuthContext` must encode this rule in `is_admin_bypass` — not expose a raw `is_admin` that callers could misuse. The current `is_admin_bypass` property already handles this (`effective_teams is None and is_admin`), but this constraint must be tested explicitly.

### Constraint 7: Four distinct token extraction paths
`AuthResolver` must handle all four extraction paths the codebase currently supports:
1. **Bearer JWT** from `Authorization` header (primary path)
2. **Cookie JWT** from `jwt_token` / `access_token` cookies (admin UI, browser sessions)
3. **API token hash** lookup in DB (legacy fallback in `AdminAuthMiddleware` when JWT verify fails)
4. **Proxy auth** from `X-Authenticated-User` header (when `trust_proxy_auth=true`)

### Constraint 8: Plugin `HTTP_AUTH_RESOLVE_USER` hook can replace user resolution
`get_current_user` (auth.py) fires the `HTTP_AUTH_RESOLVE_USER` plugin hook, which can completely replace the built-in user resolution logic. `AuthResolver` must support this hook or plugins that rely on custom auth providers will break.

### Constraint 9: `_resolve_teams_from_db` is called from 4 files
The session-token team resolution function is used in `auth.py`, `main.py`, `token_scoping.py`, and `streamablehttp_transport.py`. All 4 call sites must be consolidated into `AuthResolver`, not just the transport.

### Constraint 10: Team membership validation has two separate caching strategies
The transport (`_auth_jwt`) uses a 60s TTL auth cache for team membership validation. The HTTP path does its own check in `TokenScopingMiddleware`. `AuthResolver` needs a unified caching strategy — the transport's `auth_cache` pattern is the more mature one and should be adopted.

---

## Proposed Design

### Core principle: one resolver, multiple carriers

The resolution logic is extracted into a single shared class. Each channel carries the result in its own natural storage mechanism. We do not fight the carriers — we standardize the resolver and the output shape.

```
┌────────────────────────────────────────────────────┐
│              AuthResolver (new, shared)             │
│                                                     │
│  resolve(request) → AuthContext                     │
│  resolve_from_token(token) → AuthContext            │
│  ─────────────────────────────────────────────      │
│  • Extract token from:                              │
│    - Authorization header (Bearer JWT)              │
│    - Cookies (jwt_token, access_token)              │
│    - API token hash DB lookup (legacy fallback)     │
│    - Proxy header (X-Authenticated-User)            │
│    - Anonymous (when auth_required=false)            │
│  • Fire HTTP_AUTH_RESOLVE_USER plugin hook           │
│  • Verify JWT once                                  │
│  • Check revocation (jti)                           │
│  • User active check                                │
│  • Session vs API token branch (one place)          │
│  • normalize_token_teams OR _resolve_teams_from_db  │
│  • Session admin bypass handled correctly           │
│  • Team membership validation (unified cache)       │
│  • Build AuthContext dataclass                      │
│  • Public-only override: is_admin forced false       │
│    when effective_teams == []                        │
└────────────────────────────────────────────────────┘
        ↙                           ↘
AuthGatewayMiddleware         _StreamableHttpAuthHandler
(Channel A)                   (Channel B)
  ↓                              ↓
request.state.auth_ctx        user_context_var.set(
                                auth_ctx.to_transport_dict())
        ↘                           ↙
    @require_permission decorator
    (reads pre-resolved auth_ctx; still lazy for team derivation,
     check_any_team, and plugin hooks)
              ↓
    services receive QueryScope
    (not token_teams)
```

---

### `AuthContext` dataclass

Frozen dataclass — canonical output of `AuthResolver.resolve()`. Lives in `mcpgateway/auth_context.py`.

```python
@dataclass(frozen=True)
class AuthContext:
    user_email: Optional[str]
    is_admin: bool
    effective_teams: Optional[List[str]]  # None=bypass, []=public, [ids]=scoped
    token_use: str                        # "session" | "api" | "anonymous"
    auth_method: str                      # "bearer_token" | "cookie" | "api_token_hash" | "proxy" | "anonymous"
    scoped_permissions: List[str]         # token-level permission caps
    is_active: bool                       # user account active status (checked once)

    @property
    def is_admin_bypass(self) -> bool:
        """Admin bypass requires BOTH is_admin AND teams=None.
        Public-only tokens (teams=[]) NEVER get admin bypass."""
        return self.effective_teams is None and self.is_admin

    @property
    def is_public_only(self) -> bool:
        return self.effective_teams is not None and len(self.effective_teams) == 0

    def allows_admin_paths(self) -> bool:
        return self.is_admin and not self.is_public_only

    def effective_is_admin(self) -> bool:
        """is_admin with the public-only override applied.
        Replaces the scattered `if token_teams == []: is_admin = False` pattern
        from _get_rpc_filter_context."""
        if self.is_public_only:
            return False
        return self.is_admin

    def to_query_scope(self) -> "QueryScope":
        return QueryScope(
            _effective_teams=self.effective_teams,
            _user_email=self.user_email,
            _is_unrestricted=self.is_admin_bypass,
        )

    def to_transport_dict(self) -> dict:
        # Bridge to user_context_var — also fixes the "teams" vs "token_teams" key drift
        return {
            "email": self.user_email,
            "teams": self.effective_teams,
            "is_admin": self.is_admin,
            "token_use": self.token_use,
            "scoped_permissions": self.scoped_permissions,
            "is_authenticated": True,
        }
```

`to_transport_dict()` is the bridge between Channel A and Channel B. It also standardizes the key name from `"token_teams"` (HTTP layer) to `"teams"` (transport layer), eliminating the existing drift by making the transport the canonical shape.

---

### `QueryScope` dataclass

Opaque auth scope passed to services. Cannot be constructed outside of `AuthContext.to_query_scope()`. Services never see `token_teams` directly.

```python
@dataclass(frozen=True)
class QueryScope:
    _effective_teams: Optional[List[str]]
    _user_email: Optional[str]
    _is_unrestricted: bool

    def apply_visibility_filter(self, query, model, *, visibility_col: str = "visibility", public_value: str = "public"):
        """Single function replacing 135+ inline checks.

        Handles column name differences across models:
        - Most models: model.visibility == "public"
        - Some models: model.is_public == True
        Use visibility_col/public_value to configure per-model.
        """
        if self._is_unrestricted:
            return query
        vis_attr = getattr(model, visibility_col, None)
        if vis_attr is None:
            # Fallback for models using is_public boolean
            is_public_attr = getattr(model, "is_public", None)
            if is_public_attr is not None:
                if not self._effective_teams:
                    return query.filter(is_public_attr == True)
                return query.filter(
                    or_(is_public_attr == True, model.team_id.in_(self._effective_teams))
                )
            # No visibility column at all — unrestricted (caller's problem)
            return query
        if not self._effective_teams:  # public-only
            return query.filter(vis_attr == public_value)
        return query.filter(
            or_(vis_attr == public_value, model.team_id.in_(self._effective_teams))
        )

    def apply_ownership_filter(self, query, model):
        """For ownership-based access (e.g., user's own resources)."""
        if self._is_unrestricted:
            return query
        owner_attr = getattr(model, "owner_email", None)
        if owner_attr is not None and self._user_email:
            return query.filter(
                or_(
                    owner_attr == self._user_email,
                    *([model.team_id.in_(self._effective_teams)] if self._effective_teams else []),
                )
            )
        return self.apply_visibility_filter(query, model)
```

---

### How each layer adopts

**`AuthGatewayMiddleware` (replaces AdminAuthMiddleware + TokenScopingMiddleware + DocsAuthMiddleware for HTTP):**

```python
auth_ctx = await AuthResolver.resolve(request)
request.state.auth_ctx = auth_ctx

# Replaces AdminAuthMiddleware
if is_admin_path and not auth_ctx.allows_admin_paths():
    return 403
# Replaces DocsAuthMiddleware
if is_docs_path and not auth_ctx.is_active:
    return 401
# Replaces TokenScopingMiddleware restriction checks
if not auth_ctx.check_token_restrictions(path, scopes):  # IP, time, server_id
    return 403
```

One middleware, no ordering dependency.

**`AuthContextMiddleware` (observability — simplified, not removed):**

```python
# Before: full JWT extraction, user lookup, revocation check (~170 lines)
# After: reads pre-resolved auth_ctx from request.state (set by AuthGatewayMiddleware)
auth_ctx = getattr(request.state, "auth_ctx", None)
if auth_ctx:
    request.state.user = ...  # populate for observability/logging
```

This middleware runs after `AuthGatewayMiddleware` in the stack and reads the already-resolved context. It no longer does its own JWT verification.

**`HttpAuthMiddleware` (plugin hooks — unchanged):**

The `HTTP_PRE_REQUEST` / `HTTP_POST_REQUEST` plugin hooks fire before and after `AuthGatewayMiddleware` respectively. They can still transform headers. No changes needed — but the middleware ordering must be preserved: `HttpAuthMiddleware` (pre-request hook) → `AuthGatewayMiddleware` → route → `HttpAuthMiddleware` (post-request hook).

**`_StreamableHttpAuthHandler._auth_jwt()` (MCP transport):**

```python
auth_ctx = await AuthResolver.resolve_from_token(token)
user_context_var.set(auth_ctx.to_transport_dict())
```

The transport still owns its ContextVar — that mechanism stays. But the ~200-line `_auth_jwt` resolution logic is replaced with one call to `AuthResolver`.

**`@require_permission` decorator (HTTP routes):**

The decorator is simplified but not eliminated. Pre-resolved fields from `auth_ctx` remove DB calls for identity. The lazy parts stay because they must:

- Team derivation from resource/payload (Tiers 1 and 3) — stays, requires URL params
- Plugin `HTTP_AUTH_CHECK_PERMISSION` hook — stays, per-check
- Plugin `HTTP_AUTH_RESOLVE_USER` hook — stays, fires via `AuthResolver`
- `check_any_team` decision for session tokens — stays, per-check

**Services:**

```python
# Before:
async def list_tools(self, db, token_teams=None, user_email=None, ...):
    if token_teams is None and user_email is None: ...
    is_public_only = token_teams is not None and len(token_teams) == 0
    ...

# After:
async def list_tools(self, db, scope: QueryScope, ...):
    query = scope.apply_visibility_filter(base_query, Tool)
```

The 135+ inline checks collapse to one method call. Services stop knowing about auth semantics.

---

## Testing Strategy

### Principle: existing tests are the behavioral equivalence oracle

The codebase already has **~836 auth-related test functions** across unit, integration, e2e, security, and playwright suites. These tests encode the current correct behavior. The refactoring must not change any observable behavior — so the existing tests, run unmodified, are the primary verification tool.

**Rule: if an existing test breaks, the refactoring has a bug — not the test.**

The only exception is tests that directly mock internal implementation details being replaced (e.g., mocking `_auth_jwt` internals). Those tests need migration but the behavioral assertions they encode must be preserved.

### Tier 0: Behavioral snapshot (before any code changes)

Before writing any `AuthContext` code, capture a baseline:

```bash
# Record full pass/fail state of every auth-related test
uv run pytest tests/unit/mcpgateway/test_auth.py \
    tests/unit/mcpgateway/test_token_scoping.py \
    tests/unit/mcpgateway/middleware/test_token_scoping.py \
    tests/unit/mcpgateway/middleware/test_rbac.py \
    tests/unit/mcpgateway/middleware/test_rbac_admin_bypass.py \
    tests/unit/mcpgateway/middleware/test_auth_middleware.py \
    tests/unit/mcpgateway/middleware/test_http_auth_headers.py \
    tests/unit/mcpgateway/middleware/test_http_auth_integration.py \
    tests/unit/mcpgateway/middleware/test_auth_method_propagation.py \
    tests/unit/mcpgateway/middleware/test_token_usage_middleware.py \
    tests/unit/mcpgateway/middleware/test_token_scoping_extra.py \
    tests/unit/mcpgateway/services/test_permission_service.py \
    tests/unit/mcpgateway/services/test_authorization_access.py \
    tests/unit/mcpgateway/transports/test_streamablehttp_transport.py \
    tests/unit/mcpgateway/transports/test_streamable_rpc_permission_fallback.py \
    tests/unit/mcpgateway/utils/test_proxy_auth.py \
    tests/unit/mcpgateway/cache/test_auth_cache_l1_l2.py \
    tests/unit/mcpgateway/routers/test_tokens.py \
    tests/integration/test_rbac_management_endpoints.py \
    tests/integration/test_rbac_ownership_http.py \
    tests/e2e/test_mcp_rbac_transport.py \
    tests/security/ \
    --tb=no -q 2>&1 | tee tests/auth_baseline.txt
```

This file is the contract. Every tier PR must produce the same pass/fail results (minus tests that were intentionally migrated, which must be tracked in the PR description).

### New test file: `tests/unit/mcpgateway/test_auth_context.py`

This is the TDD anchor for Tier 0. Written BEFORE any implementation. Tests define the `AuthContext` / `QueryScope` / `AuthResolver` contracts.

```python
"""Behavioral equivalence tests for AuthContext consolidation.

These tests encode the EXACT same decisions currently scattered across 10 layers.
Each test maps to a specific existing behavior with a comment citing the source.
If any test here contradicts an existing test, the existing test wins.
"""
import pytest
from mcpgateway.auth_context import AuthContext, AuthResolver, QueryScope


# ── AuthContext property truth table ──────────────────────────────────
# Encodes the rules from normalize_token_teams + _get_rpc_filter_context

class TestAuthContextProperties:
    """Maps to: test_token_scoping.py (normalize_token_teams truth table)
    and main.py:_get_rpc_filter_context (public-only admin override)."""

    @pytest.mark.parametrize("teams,is_admin,expect_bypass,expect_public,expect_effective_admin", [
        # Source: normalize_token_teams — admin bypass requires BOTH conditions
        (None,       True,  True,  False, True),   # admin + null teams = bypass
        (None,       False, False, False, False),   # non-admin + null teams = NOT bypass (normalize gives [])
        # Source: _get_rpc_filter_context — public-only forces is_admin=False
        ([],         True,  False, True,  False),   # admin + empty teams = public-only, admin OVERRIDDEN
        ([],         False, False, True,  False),   # non-admin + empty = public-only
        # Source: standard team-scoped behavior
        (["t1"],     True,  False, False, True),    # admin + teams = NOT bypass, still admin
        (["t1"],     False, False, False, False),   # non-admin + teams = scoped
        (["t1","t2"],False, False, False, False),   # multi-team
    ])
    def test_auth_context_property_matrix(self, teams, is_admin, expect_bypass, expect_public, expect_effective_admin):
        ctx = AuthContext(
            user_email="user@test.com", is_admin=is_admin,
            effective_teams=teams, token_use="api",
            auth_method="bearer_token", scoped_permissions=[], is_active=True,
        )
        assert ctx.is_admin_bypass == expect_bypass
        assert ctx.is_public_only == expect_public
        assert ctx.effective_is_admin() == expect_effective_admin

    def test_allows_admin_paths(self):
        """Source: AdminAuthMiddleware line 1842 — public-only tokens never get admin paths."""
        admin_bypass = AuthContext(user_email="a@b.com", is_admin=True, effective_teams=None,
                                  token_use="api", auth_method="bearer_token", scoped_permissions=[], is_active=True)
        admin_public = AuthContext(user_email="a@b.com", is_admin=True, effective_teams=[],
                                  token_use="api", auth_method="bearer_token", scoped_permissions=[], is_active=True)
        admin_scoped = AuthContext(user_email="a@b.com", is_admin=True, effective_teams=["t1"],
                                  token_use="api", auth_method="bearer_token", scoped_permissions=[], is_active=True)
        non_admin = AuthContext(user_email="a@b.com", is_admin=False, effective_teams=["t1"],
                                token_use="api", auth_method="bearer_token", scoped_permissions=[], is_active=True)
        assert admin_bypass.allows_admin_paths() is True
        assert admin_public.allows_admin_paths() is False  # critical
        assert admin_scoped.allows_admin_paths() is True
        assert non_admin.allows_admin_paths() is False


# ── AuthResolver token extraction ─────────────────────────────────────
# Encodes the 4 extraction paths from Constraint 7

class TestAuthResolverExtraction:
    """Maps to: get_current_user (auth.py), AdminAuthMiddleware (main.py),
    _auth_jwt (streamablehttp_transport.py), proxy auth (utils/verify_credentials.py)."""

    @pytest.mark.asyncio
    async def test_bearer_jwt_extraction(self):
        """Source: get_current_user — standard path."""
        ...

    @pytest.mark.asyncio
    async def test_cookie_jwt_extraction(self):
        """Source: AuthContextMiddleware + AdminAuthMiddleware — reads jwt_token cookie."""
        ...

    @pytest.mark.asyncio
    async def test_api_token_hash_fallback(self):
        """Source: AdminAuthMiddleware line 1810 — falls back to DB hash lookup."""
        ...

    @pytest.mark.asyncio
    async def test_proxy_auth_extraction(self):
        """Source: rbac.py:119-172 + verify_credentials.py — X-Authenticated-User header."""
        ...

    @pytest.mark.asyncio
    async def test_anonymous_when_auth_not_required(self):
        """Source: rbac.py anonymous path — returns public-only scope."""
        ...

    @pytest.mark.asyncio
    async def test_plugin_resolve_user_hook_fires(self):
        """Source: get_current_user — HTTP_AUTH_RESOLVE_USER hook can override resolution."""
        ...


# ── AuthResolver session vs API token ──────────────────────────────────
# Encodes the branching from Constraint 2

class TestAuthResolverSessionVsApi:
    """Maps to: _auth_jwt lines 2959-2987 (transport) and
    _get_rpc_filter_context (main.py)."""

    @pytest.mark.asyncio
    async def test_session_token_admin_gets_bypass(self):
        """Source: _auth_jwt line 2959 — session admin → teams=None."""
        ...

    @pytest.mark.asyncio
    async def test_session_token_non_admin_resolves_from_db(self):
        """Source: _auth_jwt line 2963 — session non-admin → DB team lookup."""
        ...

    @pytest.mark.asyncio
    async def test_session_token_no_email_gets_public_only(self):
        """Source: _auth_jwt line 2970 — no email → teams=[]."""
        ...

    @pytest.mark.asyncio
    async def test_api_token_uses_normalize_token_teams(self):
        """Source: _auth_jwt line 2974 — API token → normalize_token_teams()."""
        ...


# ── to_transport_dict bridge ──────────────────────────────────────────
# Encodes the key-name standardization

class TestTransportDictBridge:
    """Maps to: user_context_var.set() in _auth_jwt."""

    def test_transport_dict_uses_teams_key_not_token_teams(self):
        ctx = AuthContext(user_email="u@t.com", is_admin=False, effective_teams=["t1"],
                         token_use="api", auth_method="bearer_token", scoped_permissions=[], is_active=True)
        d = ctx.to_transport_dict()
        assert "teams" in d
        assert "token_teams" not in d
        assert d["teams"] == ["t1"]

    def test_transport_dict_admin_bypass_teams_none(self):
        ctx = AuthContext(user_email="a@t.com", is_admin=True, effective_teams=None,
                         token_use="session", auth_method="cookie", scoped_permissions=[], is_active=True)
        d = ctx.to_transport_dict()
        assert d["teams"] is None
        assert d["is_admin"] is True


# ── QueryScope filtering ─────────────────────────────────────────────
# Encodes the 3 distinct patterns from services

class TestQueryScopeFiltering:
    """Maps to: inline token_teams patterns in tool_service.py, resource_service.py,
    a2a_service.py, prompt_service.py, etc."""

    def test_unrestricted_returns_unfiltered(self):
        """Source: `if token_teams is None and user_email is None` in services."""
        ...

    def test_public_only_filters_to_public(self):
        """Source: `if token_teams is not None and len(token_teams) == 0` in services."""
        ...

    def test_team_scoped_filters_to_teams_plus_public(self):
        """Source: `query.filter(or_(visibility == 'public', team_id.in_(token_teams)))` in services."""
        ...

    def test_handles_is_public_boolean_column(self):
        """Source: some models use `is_public` instead of `visibility`."""
        ...

    def test_ownership_filter(self):
        """Source: owner_email-based access in some services."""
        ...


# ── Behavioral equivalence: Channel A vs Channel B ────────────────────
# The same AuthResolver should produce identical AuthContext for the same token
# whether called from HTTP middleware or StreamableHTTP transport

class TestCrossChannelEquivalence:
    """NEW — proves that AuthResolver.resolve(request) and
    AuthResolver.resolve_from_token(token) produce the same AuthContext
    for the same underlying credential."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("token_fixture", [
        "admin_api_token",
        "admin_session_token",
        "team_scoped_api_token",
        "public_only_token",
        "multi_team_token",
    ])
    async def test_same_token_same_context(self, token_fixture, request):
        """AuthResolver.resolve(http_request_with_token) must produce
        identical effective_teams, is_admin, token_use as
        AuthResolver.resolve_from_token(same_token)."""
        ...
```

### Per-tier TDD workflow

Every tier follows this cycle:

1. **Run baseline**: `uv run pytest <auth test files> --tb=no -q` — all green
2. **Write new tests** for the tier's new behavior (in `test_auth_context.py`)
3. **Run new tests** — they fail (red)
4. **Implement the tier**
5. **Run new tests** — they pass (green)
6. **Run baseline** — still all green (behavioral equivalence preserved)
7. **If any baseline test breaks**: the implementation has a bug. Fix the implementation, not the test.

### Tier-specific test expectations

| Tier | New tests written | Baseline tests expected to break | Action if baseline breaks |
|---|---|---|---|
| 0 | `TestAuthContextProperties`, `TestQueryScopeFiltering` | None | Fix implementation |
| 1 | `TestAuthResolverExtraction`, `TestCrossChannelEquivalence` | None (additive — old path still live) | Fix implementation |
| 2 | Tests that `AdminAuthMiddleware` reads from `request.state.auth_ctx` | None (reads new, falls back to old) | Fix implementation |
| 3 | Tests that transport uses `AuthResolver.resolve_from_token` | Transport-internal mock tests (mock `_auth_jwt` internals) | Migrate mock targets, preserve assertions |
| 4 | Tests that `require_permission` reads `auth_ctx` | RBAC mock tests that mock `get_current_user_with_permissions` | Migrate mock targets, preserve assertions |
| 5 | Per-service `QueryScope` tests | Service tests that pass `token_teams=` directly | Migrate parameter, preserve filter assertions |
| 6 | Removal confirmation tests | Tests that import removed middleware | Remove imports, assertions already migrated |

### Tests that need migration (not deletion)

Some existing tests mock implementation details that will change. These tests must be **migrated** — the mock target changes but the behavioral assertion is preserved:

**Tier 3 migrations (~20 tests):**
- `tests/unit/mcpgateway/transports/test_streamablehttp_transport.py` — tests that mock `_auth_jwt` internals or `verify_credentials` at the transport level. New mock target: `AuthResolver.resolve_from_token`.

**Tier 4 migrations (~24 tests):**
- `tests/unit/mcpgateway/middleware/test_rbac.py` — tests that mock `get_current_user_with_permissions` to inject auth state. New mock target: `request.state.auth_ctx`.

**Tier 5 migrations (~50+ tests across services):**
- All service tests that pass `token_teams=None/[]/["t1"]` as parameters. New parameter: `scope=QueryScope(...)`. The `QueryScope` construction replaces the raw parameter, but the test's assertion on what the query returns must be identical.

**Migration rule:** for each migrated test, the PR must include a comment showing the before/after and asserting the same behavioral outcome.

### Behavioral equivalence integration test

A new integration test that runs the SAME request through both the old and new paths and compares:

```python
# tests/integration/test_auth_context_equivalence.py

"""Dual-path behavioral equivalence test.

During Tiers 1-5, both old and new paths are live. This test runs
each auth scenario through both paths and asserts identical outcomes.
Removed in Tier 6 when old paths are deleted.
"""

AUTH_SCENARIOS = [
    # (description, token_factory, expected_teams, expected_admin)
    ("admin API token",           make_admin_api_token,      None,     True),
    ("admin session token",       make_admin_session_token,  None,     True),
    ("team-scoped API token",     make_team_token(["t1"]),   ["t1"],   False),
    ("multi-team API token",      make_team_token(["t1","t2"]), ["t1","t2"], False),
    ("public-only API token",     make_public_token,         [],       False),
    ("public-only admin token",   make_public_admin_token,   [],       True),  # is_admin=True but teams=[]
    ("session non-admin",         make_session_token,        ["t1"],   False),  # teams resolved from DB
    ("anonymous (no token)",      None,                      [],       False),
    ("proxy auth",                make_proxy_headers,        ...,      ...),
]

@pytest.mark.parametrize("desc,token_factory,expect_teams,expect_admin", AUTH_SCENARIOS)
async def test_old_path_matches_new_path(desc, token_factory, expect_teams, expect_admin, app_with_temp_db):
    """For each scenario:
    1. Call a test endpoint through the FULL middleware stack
    2. The endpoint returns both request.state.token_teams (old) and request.state.auth_ctx (new)
    3. Assert they agree on effective_teams, is_admin, user_email
    """
    ...
```

This test is the **kill switch**: if old and new paths disagree for any scenario, the tier cannot ship.

### Shadow-mode for Tiers 1-5

During the transition, `AuthGatewayMiddleware` runs alongside existing middleware. Both populate `request.state`. A debug-mode assertion (enabled in dev/test, disabled in prod) compares results:

```python
class AuthGatewayMiddleware:
    async def dispatch(self, request, call_next):
        auth_ctx = await AuthResolver.resolve(request)
        request.state.auth_ctx = auth_ctx

        if settings.auth_context_shadow_mode:
            # Old path still runs; compare results after response
            response = await call_next(request)
            old_teams = getattr(request.state, "token_teams", _SENTINEL)
            if old_teams is not _SENTINEL:
                new_teams = auth_ctx.effective_teams
                if old_teams != new_teams:
                    logger.error(
                        "AUTH SHADOW MISMATCH: old=%s new=%s path=%s",
                        old_teams, new_teams, request.url.path
                    )
            return response

        return await call_next(request)
```

`auth_context_shadow_mode` is a dev-only config flag (default `false`). It is NOT a production feature flag — it exists only to catch divergence during development. Removed in Tier 6.

---

## Adoption Tiers (incremental, no big-bang)

Each tier is a separate PR. The old path stays live until a tier completes. At no point does the old path break while the new path is being wired in.

| Tier | What changes | What is removed | Tests | Risk |
|---|---|---|---|---|
| 0 | Define `AuthContext`, `QueryScope`, `AuthResolver` in `mcpgateway/auth_context.py` — no callers yet. Write `test_auth_context.py` with full property matrix and QueryScope tests. | Nothing | New tests pass. Baseline unchanged. | None |
| 1 | `AuthGatewayMiddleware` calls `AuthResolver`, stores `request.state.auth_ctx`. Shadow mode enabled. | Nothing yet | Equivalence integration test added. Baseline unchanged. | Low — additive |
| 2 | `AdminAuthMiddleware` + `DocsAuthMiddleware` + `AuthContextMiddleware` read `request.state.auth_ctx` instead of re-parsing JWT | Duplicate JWT verify in 3 middlewares | Shadow mode catches any divergence. Baseline unchanged. | Low |
| 3 | `_StreamableHttpAuthHandler._auth_jwt()` calls `AuthResolver.resolve_from_token()`, uses `to_transport_dict()` | ~200 lines of duplicated resolution in transport | ~20 transport tests migrated (mock target changes). Baseline minus migrated tests unchanged. | Medium |
| 4 | `@require_permission` reads pre-resolved `auth_ctx.is_admin` / `effective_teams` from state | Duplicate DB calls for identity in decorator | ~24 RBAC tests migrated. Baseline minus migrated tests unchanged. | Low |
| 5 | Services: replace `token_teams` parameter with `QueryScope` (one service at a time) | Inline `token_teams is None` blocks in services | ~50+ service tests migrated per service. Each service is a sub-PR. | Medium, incremental |
| 6 | Remove `TokenScopingMiddleware`, `AdminAuthMiddleware`, `DocsAuthMiddleware`, shadow mode. Simplify `AuthContextMiddleware` to read-only. | Legacy middlewares, shadow mode | Remove equivalence integration test. Full suite green. | Low — cleanup |

---

## Middleware stack ordering (final state after Tier 6)

```python
# Execution order (last added = first to run in Starlette):
app.add_middleware(ObservabilityMiddleware, ...)      # reads request.state.auth_ctx
app.add_middleware(TokenUsageMiddleware)               # reads request.state.auth_ctx
app.add_middleware(AuthContextMiddleware)               # reads request.state.auth_ctx (no JWT work)
app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(ProxyHeadersMiddleware, ...)
app.add_middleware(AuthGatewayMiddleware)               # THE auth layer — calls AuthResolver
app.add_middleware(HttpAuthMiddleware, ...)             # plugin pre/post hooks (runs before AuthGateway)
app.add_middleware(MCPProtocolVersionMiddleware)
app.add_middleware(ValidationMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
```

Key ordering: `HttpAuthMiddleware` (plugin can transform headers) → `AuthGatewayMiddleware` (resolves auth) → `AuthContextMiddleware` (reads resolved auth for observability).

---

## What stays unchanged

- `normalize_token_teams()` — called by `AuthResolver`, still the single normalization function
- The `teams: null` vs `[]` semantic — preserved, evaluated once inside `AuthResolver`
- The RBAC role model and `PermissionService` — called by `@require_permission`, not by middleware
- The `@require_permission` decorator pattern — kept, simplified
- Team derivation from resource/payload (`_derive_team_from_resource` / `_derive_team_from_payload`)
- Plugin `HTTP_AUTH_CHECK_PERMISSION` hook — still fires per-check
- Plugin `HTTP_AUTH_RESOLVE_USER` hook — still fires via `AuthResolver`
- Plugin `HTTP_PRE_REQUEST` / `HTTP_POST_REQUEST` hooks — still fire via `HttpAuthMiddleware`
- `check_any_team` logic for session tokens — still at decorator time
- SSE transport and WebSocket transport — no changes (already HTTP routes)
- `user_context_var` ContextVar mechanism — stays, populated by `to_transport_dict()`
- `verify_credentials` utility — called by `AuthResolver` internally

---

## What this does NOT do

- No new security features
- No changes to the RBAC role model or permission definitions
- No changes to JWT token format or signing
- No changes to the `teams: null` / `[]` / `[ids]` semantic
- No changes to plugin hook interfaces
- No changes to public API contracts
- No changes to Basic Auth support (DocsAuthMiddleware's basic auth path moves into `AuthResolver`)

---

## Files affected (expected)

**New files:**
- `mcpgateway/auth_context.py` — `AuthContext`, `QueryScope`, `AuthResolver`
- `tests/unit/mcpgateway/test_auth_context.py` — TDD anchor tests
- `tests/integration/test_auth_context_equivalence.py` — dual-path equivalence tests (temporary, removed Tier 6)

**Modified:**
- `mcpgateway/middleware/token_scoping.py` — calls `AuthResolver`, then removed in Tier 6
- `mcpgateway/main.py` — `AdminAuthMiddleware` simplified (Tier 2), then removed (Tier 6); `DocsAuthMiddleware` simplified (Tier 2), then removed (Tier 6); `AuthGatewayMiddleware` added; middleware ordering updated
- `mcpgateway/middleware/auth_middleware.py` — `AuthContextMiddleware` simplified to read `request.state.auth_ctx` (Tier 2)
- `mcpgateway/transports/streamablehttp_transport.py` — `_auth_jwt()` replaced (Tier 3)
- `mcpgateway/middleware/rbac.py` — `require_permission` simplified (Tier 4)
- `mcpgateway/services/*.py` — `token_teams` → `QueryScope` (Tier 5, one service at a time)
- `mcpgateway/services/base_service.py` — shared filtering logic removed in favor of `QueryScope`
- `mcpgateway/utils/verify_credentials.py` — called by `AuthResolver` (no interface change)
- `mcpgateway/config.py` — `auth_context_shadow_mode` flag (dev-only, removed Tier 6)

**Removed (Tier 6):**
- `TokenScopingMiddleware` (or emptied to a pass-through)
- `AdminAuthMiddleware` (logic absorbed into `AuthGatewayMiddleware`)
- `DocsAuthMiddleware` (logic absorbed into `AuthGatewayMiddleware`)
- `AuthContextMiddleware` renamed to `AuthLoggingMiddleware` to avoid confusion with `AuthContext`
- Shadow mode config flag and comparison logic
- `tests/integration/test_auth_context_equivalence.py` (dual-path test no longer needed)
