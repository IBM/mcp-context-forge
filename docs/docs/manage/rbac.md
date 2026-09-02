# RBAC Configuration

Role-based access control (RBAC) defines which actions users or teams can perform in ContextForge. This document covers the two-layer security model, token scoping semantics, permission system, and best practices for access control.

---

## Overview

ContextForge implements a **two-layer security model**:

1. **Token Scoping (Layer 1)**: Controls what resources a user CAN SEE (data filtering)
2. **RBAC (Layer 2)**: Controls what actions a user CAN DO (action authorization)

Both layers must pass for an operation to succeed.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Two-Layer Security Model                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Request → Authentication → Token Scoping → RBAC Check → Operation        │
│                              (Can See?)       (Can Do?)                     │
│                                                                             │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐ │
│   │   JWT    │   │  User    │   │ Resource │   │Permission│   │ Execute  │ │
│   │  Token   │──▶│ Identity │──▶│  Access  │──▶│  Check   │──▶│ Operation│ │
│   │          │   │          │   │          │   │          │   │          │ │
│   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Authentication Methods

| Method | Priority | Description |
|--------|----------|-------------|
| JWT Token | 1 (Primary) | Signature verified, supports teams/scopes claims |
| Plugin Auth | 0 (Before JWT) | `HTTP_AUTH_RESOLVE_USER` hook can provide custom auth |
| API Token (DB) | 2 (Fallback) | Legacy database-stored tokens |
| Proxy Header | 3 | When `MCP_CLIENT_AUTH_ENABLED=false` AND `TRUST_PROXY_AUTH=true` |
| Anonymous | 4 | When `AUTH_REQUIRED=false` (development only) |

---

## Core Concepts

### Subjects
Users authenticated via:

- JWT tokens (session or API)
- SSO providers (OAuth 2.0/OIDC)
- Basic authentication (development only)

### Teams
Logical groups that:

- Organize users for access boundaries
- Own resources (tools, prompts, resources)
- Map from external identity providers (SSO groups)

### Built-in RBAC Roles

| Role | Scope | Permissions |
|------|-------|-------------|
| `platform_admin` | global | `["*"]` (all permissions) |
| `team_admin` | team | admin.dashboard, admin.overview, gateways.read, gateways.create, gateways.update, gateways.delete, servers.read, servers.use, servers.create, servers.update, servers.delete, teams.read, teams.update, teams.join, teams.delete, teams.manage_members, tools.read, tools.create, tools.update, tools.delete, tools.execute, plugins.read, resources.read, resources.create, resources.update, resources.delete, prompts.read, prompts.create, prompts.update, prompts.delete, a2a.read, a2a.create, a2a.update, a2a.delete, a2a.invoke, llm.read, llm.invoke, tokens.create, tokens.read, tokens.update, tokens.revoke |
| `developer` | team | admin.dashboard, admin.overview, gateways.read, gateways.create, gateways.update, gateways.delete, servers.read, servers.use, servers.create, servers.update, servers.delete, teams.read, teams.join, tools.read, tools.create, tools.update, tools.delete, tools.execute, plugins.read, resources.read, resources.create, resources.update, resources.delete, prompts.read, prompts.create, prompts.update, prompts.delete, a2a.read, a2a.create, a2a.update, a2a.delete, a2a.invoke, llm.read, llm.invoke, tokens.create, tokens.read, tokens.update, tokens.revoke |
| `viewer` | team | admin.dashboard, admin.overview, gateways.read, servers.read, servers.use, teams.read, teams.join, tools.read, tools.execute, resources.read, prompts.read, a2a.read, llm.read, tokens.create, tokens.read, tokens.update, tokens.revoke |
| `platform_viewer` | global | admin.dashboard, admin.overview, gateways.read, servers.read, servers.use, teams.read, teams.join, tools.read, resources.read, prompts.read, a2a.read, llm.read, metrics:read, tokens.create, tokens.read, tokens.update, tokens.revoke |

!!! info "Default Role Assignment"
    **New users automatically receive up to two roles upon creation:**

    **Admin users** (`is_admin: true`) receive:

    1. `platform_admin` role with **global scope** (`scope_id` = None)
       - Grants unrestricted access to all platform resources
    2. `team_admin` role with **team scope** (`scope_id` = personal team ID)
       - Grants full management of their personal team resources
       - Only assigned if personal team creation succeeds

    **Non-admin users** (`is_admin: false`) receive:

    1. `platform_viewer` role with **global scope** (`scope_id` = None)
       - Grants read-only access to all platform resources
    2. `team_admin` role with **team scope** (`scope_id` = personal team ID)
       - Grants full management of their personal team resources
       - Only assigned if personal team creation succeeds

    This dual-role approach ensures:
    - Users always have appropriate global visibility (via `platform_admin` or `platform_viewer`)
    - Users can fully manage their personal team resources (via team-scoped `team_admin`, when available)
    - Clear separation between team-level and platform-level permissions

    The `granted_by` field tracks which admin created the user for audit purposes.

!!! note "Existing Users Migration"
    An Alembic migration (`v1a2b3c4d5e6`) automatically updates existing users without roles:

    **Previous behavior (before migration):**
    - Admin users: Only `platform_admin` with global scope (`scope_id` = None)
    - Non-admin users: Only `viewer` with team scope (`scope_id` = None)

    **After migration:**

    **Admin users** receive:

    1. `team_admin` role with **team scope**
       - `scope_id` = user's personal team ID (from `email_team_members` table)
       - Enables management of personal team resources
    2. `platform_admin` role with **global scope**
       - `scope_id` = None
       - Maintains unrestricted platform access

    **Non-admin users** receive:

    1. `team_admin` role with **team scope**
       - `scope_id` = user's personal team ID (from `email_team_members` table)
       - Enables management of personal team resources
    2. `platform_viewer` role with **global scope**
       - `scope_id` = None
       - Provides read-only access to platform resources

    **Migration behavior:**
    - Only affects users without existing role assignments
    - Users without a personal team still receive their global role (team_admin is skipped)
    - The platform admin (configured via `PLATFORM_ADMIN_EMAIL`) is excluded to preserve bootstrap configuration
    - Migration is idempotent and safe to run multiple times

### Resources
Protected entities:

- Servers (MCP gateways and virtual servers)
- Tools, Prompts, Resources (MCP primitives)
- System configuration and audit logs

---

## Token Scoping Model

Token scoping controls what resources a token can access based on the `teams` claim in the JWT payload. The `normalize_token_teams()` function is the **single source of truth** for interpreting JWT team claims into a canonical form. For session tokens, `resolve_session_teams()` is the **single policy point** — it resolves teams from the database first (so revoked memberships take effect immediately), then narrows the result to the intersection with any JWT-embedded `teams` claim (so callers can scope a session to a subset of their memberships). If the intersection is empty (e.g. all JWT-claimed teams have been revoked), an empty list is returned, demoting the session to public-only scope — the user can still access public resources and their own private resources, but loses access to all team-scoped resources. An explicit `teams: []` in a session JWT is treated as "no restriction requested" and returns the full DB membership.

### Token Scoping Contract

The `teams` claim in JWT tokens determines resource visibility. The system follows a **secure-first design**: when in doubt, access is denied.

**API tokens and legacy tokens** — JWT `teams` claim is the sole authority:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   API / Legacy Token Teams Claim Handling                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  JWT Claim State          │  is_admin: true       │  is_admin: false        │
├───────────────────────────┼───────────────────────┼─────────────────────────┤
│  No "teams" key           │  PUBLIC-ONLY []       │  PUBLIC-ONLY []         │
│  teams: null              │  ADMIN BYPASS (None)  │  PUBLIC-ONLY []         │
│  teams: []                │  PUBLIC-ONLY []       │  PUBLIC-ONLY []         │
│  teams: ["team-id"]       │  Team + Public        │  Team + Public          │
│  teams: ["t1", "t2"]      │  Both Teams + Public  │  Both Teams + Public    │
└───────────────────────────┴───────────────────────┴─────────────────────────┘
```

**Session tokens** — DB is the authority; JWT `teams` only narrows (never broadens):

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                     Session Token Teams Resolution                               │
├──────────────────────────────────────────────────────────────────────────────────┤
│  JWT Claim State       │  DB Teams          │  Result           │ Access Level   │
├────────────────────────┼────────────────────┼───────────────────┼────────────────┤
│  Missing / null / []   │  ["t1", "t2"]      │  ["t1", "t2"]     │ Full DB scope  │
│  ["t1"]                │  ["t1", "t2"]      │  ["t1"]           │ Narrowed       │
│  ["revoked"]           │  ["t1", "t2"]      │  []               │ Public-only    │
│  any                   │  None (admin)      │  None             │ Admin bypass   │
└────────────────────────┴────────────────────┴───────────────────┴────────────────┘
```

!!! note "Session Token Staleness"
    Session tokens skip `_check_team_membership` re-validation in the token scoping middleware because `resolve_session_teams()` already resolved membership from the database. Membership staleness is bounded by the `auth_cache` TTL. The cache stores the full DB membership (not the per-session narrowed intersection) so that multiple sessions for the same user narrow independently.

!!! warning "Admin Bypass Requirements"
    **API / legacy tokens:** Admin bypass requires **BOTH** `teams: null` (explicit null, not missing key) and `is_admin: true`. A missing `teams` key or `teams: []` results in public-only access, even for admins.

    **Session tokens:** Admin bypass is determined by the **database** `is_admin` flag, not the JWT `teams` claim. If the DB user is admin, `resolve_session_teams()` returns `None` (admin bypass) regardless of the JWT `teams` state. The JWT `teams` claim cannot narrow an admin session — it only narrows non-admin sessions.

!!! note "External IdP tokens use session semantics"
    Access tokens accepted from trusted external SSO providers (`SSO_API_TOKEN_AUTH_ENABLED`, see [SSO documentation](sso.md#machine-to-machine-api-auth-with-external-idp-tokens)) are provisioned to a `token_use="session"` identity. `is_admin` and `teams` are resolved exactly as in the **Session tokens** row above — from the persisted local user record via `resolve_session_teams()` — never from claims inside the external token itself.

### `is_admin`, `teams`, and `token_use` (Mental Model)

These three values are related, but they control different things:

| Field | Purpose | Where It Is Enforced |
|-------|---------|----------------------|
| `is_admin` | User/admin identity flag | RBAC permission checks (`PermissionService`) |
| `teams` | Visibility/data scope (`None`, `[]`, or team list) | Token scoping and service query filtering |
| `token_use` | Token interpretation mode (`session` vs `api`) | Auth pipeline (`get_current_user`) |

Key points:

1. `is_admin` does **not** automatically mean "see everything".
2. Visibility comes from normalized `token_teams`:
   - `None` = admin bypass scope
   - `[]` = public-only scope
   - `["t1", ...]` = team-scoped visibility
3. `token_use` decides where teams come from:
   - `session`: teams are resolved from DB/cache on each request
   - `api`/legacy: teams come from JWT claim via `normalize_token_teams()`

### End-to-End Authorization Pipeline

1. **Authenticate token and resolve user**
   - Verify JWT/API token.
   - Resolve `token_use`.
2. **Normalize/resolve teams**
   - `token_use=session` → resolve from DB and optionally narrow by JWT claim (`resolve_session_teams()`).
   - `token_use!=session` → normalize JWT `teams` (`normalize_token_teams()`).
3. **Layer 1: Token scoping**
   - Filter accessible resources by `token_teams`.
   - Public-only tokens cannot access team/private resources.
4. **Layer 2: RBAC permission check**
   - Validate action permission (`tools.read`, `admin.system_config`, etc.).
   - Public-only guard: `admin.*` permissions are denied when `token_teams=[]`.

!!! info "Why Public-Only Admin Tokens Can Still Be Useful"
    A token can represent an admin identity (`is_admin=true`) while still being visibility-restricted (`teams=[]`).
    This allows controlled automation tokens with reduced blast radius.

### Return Value Semantics

| Return Value | Meaning | Query Behavior |
|--------------|---------|----------------|
| `None` | Admin bypass | Skip ALL visibility filtering (requires `user_email=None` in the service layer) |
| `[]` (empty list) | Public-only | Filter to `visibility='public'` ONLY — owner and team access are both suppressed |
| `["t1", "t2"]` | Team-scoped | Filter to team resources + public + user's own private resources |

!!! note "Owner Access is Scoped to Private Visibility"
    Owner-based access (`owner_email` matching) grants visibility **only** for resources with `visibility='private'`. Resource owners cannot use ownership to bypass team scoping — a team-visibility resource is only visible if the user's `token_teams` includes that team.

### Security Design Principles

1. **Secure-First Defaults**

   - API/legacy tokens: missing `teams` key always returns `[]` (public-only access), preventing accidental exposure when tokens are misconfigured
   - Session tokens: missing/null/empty `teams` returns full DB membership (no narrowing requested); the DB is the authority

2. **Explicit Admin Bypass**

   - API/legacy tokens: admin bypass requires explicit `teams: null` AND `is_admin: true`
   - Session tokens: admin bypass is DB-derived (DB `is_admin` flag); JWT `teams` only narrows non-admin sessions
   - Empty teams `[]` disables bypass even for admins (API/legacy tokens)

3. **Scoped Automation Tokens**

   - Tokens with `teams: []` are intentionally restricted to public resources
   - Use case: CI/CD pipelines, monitoring systems, public API clients

### Token Scoping Flow

```
                                 ┌──────────────────┐
                                 │   JWT Token      │
                                 │   Received       │
                                 └────────┬─────────┘
                                          │
                                          ▼
                              ┌───────────────────────┐
                              │  Extract "teams"      │
                              │  claim from JWT       │
                              └───────────┬───────────┘
                                          │
                          ┌───────────────┴───────────────┐
                          │                               │
                          ▼                               ▼
               ┌─────────────────────┐       ┌─────────────────────┐
               │ "teams" key EXISTS  │       │ "teams" key MISSING │
               └──────────┬──────────┘       └──────────┬──────────┘
                          │                             │
                          ▼                             ▼
               ┌─────────────────────┐       ┌─────────────────────┐
               │ Check teams value   │       │ Return []           │
               └──────────┬──────────┘       │ PUBLIC-ONLY         │
                          │                  │ (secure default)    │
          ┌───────────────┼───────────────┐  └─────────────────────┘
          │               │               │
          ▼               ▼               ▼
  ┌───────────────┐ ┌───────────┐ ┌───────────────┐
  │ teams: null   │ │ teams: [] │ │ teams: [...]  │
  └───────┬───────┘ └─────┬─────┘ └───────┬───────┘
          │               │               │
          ▼               │               ▼
  ┌───────────────┐       │       ┌───────────────┐
  │ Check is_admin│       │       │ Return [...]  │
  └───────┬───────┘       │       │ TEAM-SCOPED   │
          │               │       └───────────────┘
    ┌─────┴─────┐         │
    │           │         │
    ▼           ▼         ▼
┌────────┐ ┌────────┐ ┌────────┐
│ Admin  │ │Non-Adm │ │ Empty  │
│ true   │ │ false  │ │ list   │
├────────┤ ├────────┤ ├────────┤
│ Return │ │ Return │ │ Return │
│ None   │ │ []     │ │ []     │
│ BYPASS │ │ PUBLIC │ │ PUBLIC │
└────────┘ └────────┘ └────────┘
```

!!! note "Key Insight"
    The difference between `teams: null` and missing `teams` key is critical:

    - **Missing key**: Always `[]` (public-only) - secure default
    - **Explicit null**: Admin bypass when `is_admin: true`, otherwise `[]`

### Visibility Levels

Resources in ContextForge have three visibility levels:

| Visibility | Description | Who Can See |
|------------|-------------|-------------|
| `public` | Accessible to all authenticated users | Everyone with valid token |
| `team` | Accessible to team members only | Team members + admins (with bypass) |
| `private` | Accessible to owner only | Resource owner only — **never** admin bypass |

### Access Matrix by Token Type

| Token Type | Public Resources | Team Resources | Private Resources |
|------------|-----------------|----------------|-------------------|
| Admin Bypass (`teams=null`, `is_admin=true`) | ✅ | ✅ (all teams) | ❌ (owner-only, see note) |
| Team-Scoped (`teams=["t1"]`) | ✅ | ✅ (own team) | ✅ (own only) |
| Public-Only (`teams=[]`) | ✅ | ❌ | ❌ |

!!! warning "Admin Bypass Does Not Include Other Users' Private Resources"
    Since [#4341](https://github.com/IBM/mcp-context-forge/pull/4341), admin bypass **cannot** read, list, update, or delete another user's private resources. Private resources (visibility=`private`) are strictly owner-scoped. If cross-user access is intentional, prefer `team` visibility or a scoped token over relying on bypass. See `docs/architecture/multitenancy.md` for the canonical multi-tenancy model.

!!! warning "Public-Only Token Limitations"
    **Public-only tokens (`teams=[]`) cannot access private resources, even if the resource is owned by the token's user.**

    This is intentional security behavior - public-only tokens are designed for limited-scope access to public resources only. To access private resources, users must use a team-scoped token that includes their personal team.

    ```
    # Public-only token behavior:
    # ✅ Can access: visibility='public' resources
    # ❌ Cannot access: visibility='team' resources (any team)
    # ❌ Cannot access: visibility='private' resources (even if owned by user)
    ```

### Enforcement Points

Token scoping is enforced consistently across all access paths:

| Location | Token Scoping | RBAC | Description |
|----------|--------------|------|-------------|
| Token Scoping Middleware | ✅ | N/A | Request-level data filtering |
| REST API Endpoints | ✅ | ✅ | `@require_permission` decorators |
| RPC Handler (`/rpc`) | ✅ | Varies | Method-specific permission checks |
| Admin UI | ✅ | ✅ | Permission-based UI rendering |
| Service Layer | ✅ | N/A | Database query filtering |
| WebSocket | ✅ | ✅ | Forwards auth to /rpc |
| MCP Transport | ✅ | N/A | Streamable HTTP protocol filtering |

### Method-Level RBAC Examples

The `/rpc` endpoint applies method-level authorization for sensitive operations.
These checks are aligned with equivalent REST endpoints.

| Method / Endpoint | Required Permission | Notes |
|-------------------|---------------------|-------|
| JSON-RPC `logging/setLevel` (`POST /rpc`) | `admin.system_config` | Same permission as `POST /logging/setLevel` |
| Utility SSE (`GET /sse`) | `servers.use` | Transport access. Tokens holding an MCP method permission (`tools.*`, `resources.*`, `prompts.*`) satisfy this implicitly — see [Token Scope Semantics](#token-scope-semantics). |
| Utility message relay (`POST /message`) | `tools.execute` | Canonical tool execution permission |
| `GET`/`PATCH /admin/runtime/mcp-mode` | `admin.system_config` | Runtime override of public `/mcp` ingress (`shadow ↔ edge`); see [Rust MCP Runtime](../architecture/rust-mcp-runtime.md#runtime-mode-override). |
| `GET`/`PATCH /admin/runtime/a2a-mode` | `admin.system_config` | Runtime override of registered-A2A invocation path (`shadow ↔ edge`). |

---

## Token Types and Use Cases

### Session Tokens (UI Login)

Generated when users log in via the Admin UI:

```json
{
  "sub": "admin@example.com",
  "user": {
    "email": "admin@example.com",
    "is_admin": true
  },
  "token_use": "session",
  "iss": "mcpgateway",
  "aud": "mcpgateway-api",
  "exp": 1234567890
}
```

**Behavior**: Session tokens resolve teams server-side per request. For admin users, resolved teams become `None` (admin bypass). For non-admin users, resolved teams become their DB membership list (or `[]` if none).

### API Tokens (Programmatic Access)

Generated via the Admin UI or API for automation:

```json
{
  "sub": "service-account@example.com",
  "is_admin": false,
  "teams": ["team-uuid-1", "team-uuid-2"],
  "iss": "mcpgateway",
  "aud": "mcpgateway-api",
  "exp": 1234567890
}
```

**Behavior**: Access restricted to public resources plus resources owned by specified teams.

### Scoped Automation Tokens

For CI/CD, monitoring, or public API access:

```json
{
  "sub": "ci-pipeline@example.com",
  "is_admin": true,
  "teams": [],  // Explicitly empty = public-only
  "iss": "mcpgateway",
  "aud": "mcpgateway-api",
  "exp": 1234567890
}
```

**Behavior**: Even admin tokens with `teams: []` are restricted to public resources only. This enables creating limited-scope tokens for automation that shouldn't access team-internal resources.

---

## Generating Scoped Tokens

### Using the CLI Tool

```bash
# Unrestricted admin-bypass API token (explicit teams=null + is_admin=true)
python3 -m mcpgateway.utils.create_jwt_token \
  --data '{"sub":"admin@example.com","is_admin":true,"teams":null,"token_use":"api"}' \
  --exp 60 \
  --secret $JWT_SECRET_KEY

# Team-scoped token
python3 -m mcpgateway.utils.create_jwt_token \
  --data '{"sub":"user@example.com","is_admin":false,"teams":["team-uuid-1"],"token_use":"api"}' \
  --exp 60 \
  --secret $JWT_SECRET_KEY

# Public-only scoped token (for automation)
python3 -m mcpgateway.utils.create_jwt_token \
  --data '{"sub":"ci@example.com","is_admin":false,"teams":[],"token_use":"api"}' \
  --exp 60 \
  --secret $JWT_SECRET_KEY
```

### Using the Admin UI

1. Navigate to **Admin UI → Tokens**
2. Click **Create Token**
3. Select team scope:

   - **No team selected**: Public resources only (secure default)
   - **Specific team(s)**: Team + public resources

4. Configure additional restrictions (IP, permissions, expiry)

!!! warning "Token Scope Warning"
    Tokens created without selecting a team will have access to **public resources only**.
    This is the secure default to prevent accidental exposure of team resources.

---

## Permission System

### Permission Categories

Permissions are defined in the `Permissions` class and control what actions users can perform:

| Category | Permissions |
|----------|-------------|
| **Users** | users.create, users.read, users.update, users.delete, users.invite |
| **Teams** | teams.create, teams.read, teams.update, teams.delete, teams.join, teams.manage_members |
| **Tools** | tools.create, tools.read, tools.update, tools.delete, tools.execute |
| **Plugins** | plugins.read |
| **Resources** | resources.create, resources.read, resources.update, resources.delete, resources.share |
| **Gateways** | gateways.create, gateways.read, gateways.update, gateways.delete |
| **Prompts** | prompts.create, prompts.read, prompts.update, prompts.delete, prompts.execute |
| **Servers** | servers.create, servers.read, servers.use, servers.update, servers.delete, servers.manage |
| **Tokens** | tokens.create, tokens.read, tokens.update, tokens.revoke |
| **Admin** | admin.system_config, admin.user_management, admin.security_audit, admin.overview, admin.dashboard, admin.events, admin.grpc, admin.plugins, admin.oauth_clients:read, admin.oauth_clients:delete |
| **A2A** | a2a.create, a2a.read, a2a.update, a2a.delete, a2a.invoke |
| **Tags** | tags.read, tags.create, tags.update, tags.delete |
| **Wildcard** | `*` (all permissions) |

!!! note "Registered OAuth clients require un-narrowed admin scope"
    `admin.oauth_clients:read` and `admin.oauth_clients:delete` gate the DCR management routes
    (`GET /oauth/registered-clients`, `GET /oauth/registered-clients/{gateway_id}`,
    `DELETE /oauth/registered-clients/{client_id}`). Registered clients are stored globally with no
    team column, so these routes additionally require an admin identity whose token is **not**
    team-narrowed — a constraint that cannot be expressed as a permission. Admin bypass is disabled
    on these routes, so the caller's roles must carry the permission — directly, via `*`, or through
    role inheritance. The DB `is_admin` flag alone is not sufficient.

    Scoped API tokens cannot yet carry `admin.oauth_clients:read` / `admin.oauth_clients:delete`:
    `TokenScopeRequest`'s permission-format validator only accepts plain `resource.action` or `*` —
    colon-form and wildcard-suffix permissions are rejected at token-creation time. So today only
    session tokens and `*`-scoped tokens reach these routes via Layer 1; the Layer 1 mapping for the
    colon-form permissions is defensive rather than reachable today, matching the existing
    `<category>.*` wildcard delegation precedent described in `token_scope_grants()`'s docstring in
    `mcpgateway/middleware/rbac.py`.

    Grant `admin.oauth_clients:read` / `admin.oauth_clients:delete` via a **global**-scope role
    (such as `platform_admin`) rather than a team-scoped role. Registered OAuth clients are global
    resources with no team ownership, so all three routes pass `global_only=True` to
    `require_permission()`: team derivation is skipped entirely and only global/personal roles
    (plus team roles with `scope_id=NULL`, i.e. roles that apply to every team) are evaluated. A
    role granted on a specific team does **not** satisfy the permission on any of these routes,
    even for a gateway owned by that team.

### Token Scope Semantics

An API token carries its own permission list (Layer 1), evaluated *before* the RBAC role
check (Layer 2). Both must allow the operation. `token_scope_grants()` in
`mcpgateway/middleware/rbac.py` is the single policy point for these rules.

| Token scopes | Meaning | Layer 1 result |
|--------------|---------|----------------|
| No `scopes` claim | Legacy token predating the claim | No restriction — RBAC alone applies |
| `[]` (empty) | **"Inherit from RBAC at runtime"** — the default for tokens created without an explicit scope | No restriction — RBAC alone applies |
| `["*"]` | Full access | Allowed |
| `["tools.read"]` | Exact grant | Allowed only for `tools.read` |

!!! warning "Empty scopes are not deny-all"
    A token created without an explicit scope is issued with `permissions: []`, which means
    *defer to RBAC*, **not** *deny everything*. Such a token can do whatever its user's roles
    allow. To restrict a token, grant it an explicit, minimal permission list.

!!! note "Changing a token's scope requires reissuing it"
    Layer 1 reads the permissions embedded in the token's signed claim. Updating a token's
    scope records the change in the database but does not re-sign the existing token, so a
    token already in circulation keeps the scopes it was issued with. Issue a new token to
    apply a scope change.

**Category wildcards (`tools.*`)** are *not* accepted when creating a token — the token API
requires each entry to be either `*` or an exact `resource.action` pair. Category wildcards
are meaningful only for RBAC *role* permissions, where they are used to decide what a caller
may delegate into a new token.

**Transport access:** a token holding any MCP method permission (`tools.*`, `resources.*`,
`prompts.*`) implicitly satisfies `servers.use`, which guards the MCP transport endpoints.
Without this, an execute-only token could not open the transport it needs. New tokens receive
`servers.use` explicitly at creation; the implicit grant covers tokens issued earlier.

### Permission Checking Flow

```
@require_permission("resource.action")
    │
    ▼
┌─────────────────────────────┐
│ Extract user_context        │ ← From request/kwargs
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│ Plugin Permission Hook      │ ← HTTP_AUTH_CHECK_PERMISSION can override
└─────────────────────────────┘
    │ (no plugin decision)
    ▼
┌─────────────────────────────┐
│ Admin Bypass Check          │ ← If allow_admin_bypass=True AND user.is_admin
└─────────────────────────────┘
    │ (not admin or bypass disabled)
    ▼
┌─────────────────────────────┐
│ Role Collection             │ ← Get all active roles for user
│ - Global scope roles        │
│ - Personal scope roles      │
│ - Team scope roles          │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│ Permission Aggregation      │ ← Collect permissions from roles
│ - Include inherited perms   │   (role inheritance supported)
│ - Check for wildcard (*)    │
└─────────────────────────────┘
    │
    ▼
  GRANT or DENY
```

### Explicit Team/Token Defaults

Team and token management behavior is now controlled through explicit role permissions, not implicit fallback checks.

| Role | Explicit Baseline Grants |
|------|--------------------------|
| `team_admin` | `teams.read`, `tokens.create`, `tokens.read`, `tokens.update`, `tokens.revoke` |
| `developer` | `teams.read`, `tokens.create`, `tokens.read`, `tokens.update`, `tokens.revoke` |
| `viewer` | `teams.read`, `tokens.create`, `tokens.read`, `tokens.update`, `tokens.revoke` |
| `platform_viewer` | `teams.read`, `tokens.create`, `tokens.read`, `tokens.update`, `tokens.revoke` |

Users without role assignments do not receive implicit team/token permissions.

### Admin API RBAC

The Admin API enforces **strict RBAC** where even users with `is_admin: true` must have explicit permissions granted. This enables **delegated administration** - granting specific admin capabilities without full superuser access.

**Key behaviors:**

| Aspect | Behavior |
|--------|----------|
| Admin bypass | `allow_admin_bypass=False` on all admin routes |
| `is_admin` flag | Does NOT bypass permission checks |
| UI entry | Requires any `admin.*` permission via `has_admin_permission()` |
| Route protection | All 177 admin routes use `@require_permission` decorators |

**Example: Delegated Server Management**

```json
{
  "role": "server-manager",
  "permissions": [
    "servers.read",
    "servers.create",
    "servers.update",
    "servers.delete"
  ]
}
```

A user with this role can:

- ✅ Access `/admin/servers/*` endpoints
- ✅ View the Admin UI (has `servers.*` which satisfies `has_admin_permission()`)
- ❌ Access `/admin/tools/*` endpoints (no `tools.*` permissions)
- ❌ Access `/admin/gateways/*` endpoints (no `gateways.*` permissions)

!!! warning "Platform Admin Role"
    The built-in `platform_admin` role has `["*"]` (wildcard) permissions, which grants access to all operations. For delegated administration, create custom roles with specific permission sets.

---

## Configuration Safety

### Development vs Production Settings

The following configuration combinations require careful consideration:

| Setting | Value | Impact | Recommended Use |
|---------|-------|--------|-----------------|
| `AUTH_REQUIRED` | `false` | All requests granted admin access | Development only |
| `TRUST_PROXY_AUTH` | `true` + `MCP_CLIENT_AUTH_ENABLED=false` | Trust `X-Forwarded-User` header without verification | Behind trusted reverse proxy only |

### Proxy Authentication Mode

When `MCP_CLIENT_AUTH_ENABLED=false` and `TRUST_PROXY_AUTH=true`:

- The gateway trusts the `X-Forwarded-User` header from upstream proxy
- No JWT validation or database verification is performed
- **Only use** when deployed behind a trusted reverse proxy that handles authentication

!!! danger "Security Warning"
    Proxy authentication mode should only be used in trusted network environments where the reverse proxy is the only entry point to the gateway. Exposing the gateway directly to untrusted networks with this configuration allows header injection attacks.

### Anonymous Mode (AUTH_REQUIRED=false)

When `AUTH_REQUIRED=false`:

- All unauthenticated requests receive platform-admin context
- **Never use in production** - all users have full admin access
- Intended only for local development and testing

!!! danger "Production Warning"
    Setting `AUTH_REQUIRED=false` in production grants administrative access to all requests. This completely bypasses authentication and authorization.

---

## Best Practices

### Token Lifecycle

1. **Use short expiration times** for interactive sessions (hours)
2. **Use longer expiration** for service accounts with IP restrictions
3. **Rotate tokens regularly** (recommended: 90 days for long-lived tokens)
4. **Revoke tokens immediately** when access should be removed

### Team Organization

1. **Create purpose-specific teams**:

   - `platform-admins` - Full administrative access
   - `developers` - Development and testing resources
   - `ci-automation` - CI/CD pipeline access
   - `monitoring` - Read-only observability access

2. **Map SSO groups to teams** for automatic membership management
3. **Use personal teams** for individual resource ownership

### Scoping Strategy

| Use Case | Recommended Token Scope |
|----------|------------------------|
| Admin UI access | Session token (admin bypass is DB-derived; no `teams` claim needed) |
| Public-only CI/CD pipeline | `teams: []` (public resources only) |
| Team-scoped CI/CD pipeline | Team-scoped token provisioned by an un-narrowed platform admin |
| Service integration | Specific team(s) |
| Developer access | Personal team + project teams |
| Monitoring/alerting | `teams: []` with read permissions |
| Service account provisioning | Un-narrowed platform admin (`is_admin: true`, `teams: null`) can create and list team tokens without joining the team |

**Service Account Provisioning**: Un-narrowed platform admins (tokens with `is_admin: true` and `teams: null`) can create and list team-scoped tokens without being active team members. This enables:

- Centralized token provisioning for CI/CD pipelines
- Emergency access scenarios without joining teams
- Automated service account management across teams
- Cross-team token auditing and lifecycle management

Narrowed admin sessions and regular users still require active team membership to create or list team tokens.

---

## Troubleshooting

### Token Not Seeing Expected Resources

1. **Check token claims**: Decode the JWT to verify `teams` claim
   ```bash
   # Decode JWT payload (middle section)
   echo "$TOKEN" | cut -d. -f2 | base64 -d | jq .
   ```

2. **Verify resource visibility**: Check the resource's `visibility` and `team_id`
   ```bash
   curl -H "Authorization: Bearer $ADMIN_TOKEN" /tools/{id} | jq '{visibility, teamId}'
   ```

3. **Check user admin status**: Non-admin users without teams get public-only access

### Admin Token Being Restricted

If an admin token is unexpectedly restricted:

1. **Check for explicit `teams` claim**: `teams: []` restricts even admins
2. **Verify `is_admin` flag**: Must be `true` in JWT or database user
3. **Check middleware logs**: Look for "token_teams" in debug output

### Registered OAuth Client Routes Return 403 After Upgrade

The `/oauth/registered-clients*` routes require `admin.oauth_clients:read` /
`admin.oauth_clients:delete` with admin bypass disabled, so the DB `is_admin` flag alone no longer
grants access — the caller's roles must carry the permission (directly, via `*`, or through role
inheritance).

Every supported path to `is_admin = true` also assigns `DEFAULT_ADMIN_ROLE` (default
`platform_admin`, permissions `["*"]`), so most deployments are unaffected. Two cases are not
covered: an `is_admin` flag set by direct SQL, and a custom `DEFAULT_ADMIN_ROLE` with no inherited
path to `*`.

This query lists every affected admin. It expands role inheritance, so a custom role inheriting
`platform_admin` is correctly excluded. A user is **excluded** from the affected list only if they
hold `*` outright, or hold **both** `:read` and `:delete` (possibly from two different role
assignments) — holding only one of the two still leaves them 403'd on the route gated by the other,
so they must stay on the list. Because all three routes now enforce `global_only=True` (team
derivation skipped; see the note above), a role is only counted if it's global, personal, or a
team role with no specific team (`scope_id IS NULL`) — a role scoped to one specific team no longer
satisfies the permission on these routes and must not count toward compatibility here either:

```sql
WITH RECURSIVE effective(role_id, cur_id, perms) AS (
    SELECT r.id, r.id, r.permissions FROM roles r WHERE r.is_active
    UNION ALL
    SELECT e.role_id, p.id, p.permissions
    FROM effective e
    JOIN roles c ON c.id = e.cur_id
    JOIN roles p ON p.id = c.inherits_from AND p.is_active
),
user_perm_flags AS (
    SELECT
        ur.user_email,
        MAX(CASE WHEN e.perms LIKE '%"*"%' THEN 1 ELSE 0 END) AS has_wildcard,
        MAX(CASE WHEN e.perms LIKE '%admin.oauth_clients:read%' THEN 1 ELSE 0 END) AS has_read,
        MAX(CASE WHEN e.perms LIKE '%admin.oauth_clients:delete%' THEN 1 ELSE 0 END) AS has_delete
    FROM user_roles ur
    JOIN effective e ON e.role_id = ur.role_id
    WHERE ur.is_active
      AND (ur.expires_at IS NULL OR ur.expires_at > CURRENT_TIMESTAMP)
      AND (ur.scope IN ('global', 'personal') OR (ur.scope = 'team' AND ur.scope_id IS NULL))
    GROUP BY ur.user_email
)
SELECT u.email
FROM email_users u
LEFT JOIN user_perm_flags f ON f.user_email = u.email
WHERE u.is_admin
  AND COALESCE(f.has_wildcard, 0) = 0
  AND NOT (COALESCE(f.has_read, 0) = 1 AND COALESCE(f.has_delete, 0) = 1);
```

The query above targets SQLite (the default `DATABASE_URL=sqlite:///./mcp.db`) — bare boolean
columns (`r.is_active`, `u.is_admin`, ...) work identically on SQLite and PostgreSQL, so no `= 1`
comparisons are needed. `Role.permissions` is a plain `json` column (not `jsonb`) on PostgreSQL, so
the `?` containment operator does **not** apply here. On PostgreSQL, add a `::text` cast around
every `e.perms` reference instead: `e.perms::text LIKE '%"*"%'`,
`e.perms::text LIKE '%admin.oauth_clients:read%'`, and
`e.perms::text LIKE '%admin.oauth_clients:delete%'` (SQLite does not understand `::text`, so keep
the bare `LIKE` form above for SQLite). The recursion terminates because role creation rejects
inheritance cycles.

An empty result means no user loses access. For each row returned, either assign a role carrying
the permissions or add `admin.oauth_clients:read` and `admin.oauth_clients:delete` to the role the
user already holds.

One case the query cannot report, because it has no `email_users` row: a development gateway
running with `AUTH_REQUIRED=false` and `ALLOW_UNAUTHENTICATED_ADMIN=true` where
`PLATFORM_ADMIN_EMAIL` was never seeded. That identity resolves to no roles and receives 403.

### Inconsistent Results Between Endpoints

If REST and RPC endpoints return different results:

1. **Check for caching**: REST list endpoints may have cached data
2. **Wait for cache TTL**: Default is 60 seconds for registry cache
3. **Use direct GET**: `/tools/{id}` bypasses list cache

---

## Bootstrap Custom Roles

ContextForge allows you to define custom roles that are automatically created during database bootstrap. This is useful for organizations that need to pre-configure roles before deployment.

### Configuration

Enable custom role bootstrapping with these environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_ENABLED` | `false` | Enable loading additional roles from file |
| `MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_FILE` | `additional_roles_in_db.json` | Path to the JSON file containing role definitions |

### Role Definition Format

Create a JSON file containing an array of role definitions:

```json
[
  {
    "name": "data_analyst",
    "description": "Read-only access for data analysis",
    "scope": "team",
    "permissions": ["tools.read", "resources.read", "prompts.read"],
    "is_system_role": true
  },
  {
    "name": "auditor",
    "description": "Compliance audit access",
    "scope": "global",
    "permissions": ["tools.read", "resources.read", "prompts.read", "servers.read", "gateways.read"],
    "is_system_role": true
  }
]
```

**Required fields:**

- `name` - Unique role name
- `scope` - Either `team` (team-level access) or `global` (system-wide access)
- `permissions` - Array of permission strings (e.g., `tools.read`, `resources.create`)

**Optional fields:**

- `description` - Human-readable description
- `is_system_role` - Set to `true` to prevent users from modifying/deleting the role

### Available Permissions

| Resource | Permissions |
|----------|-------------|
| Tools | `tools.create`, `tools.read`, `tools.update`, `tools.delete`, `tools.execute` |
| Resources | `resources.create`, `resources.read`, `resources.update`, `resources.delete` |
| Prompts | `prompts.create`, `prompts.read`, `prompts.update`, `prompts.delete` |
| Servers | `servers.create`, `servers.read`, `servers.use`, `servers.update`, `servers.delete`, `servers.manage` |
| Gateways | `gateways.create`, `gateways.read`, `gateways.update`, `gateways.delete` |
| OAuth clients | `admin.oauth_clients:read`, `admin.oauth_clients:delete` |
| Teams | `teams.create`, `teams.read`, `teams.update`, `teams.delete`, `teams.join` |

### Docker Compose Example

```yaml
services:
  gateway:
    environment:
      - MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_ENABLED=true
      - MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_FILE=/app/custom_roles.json
    volumes:
      - ./custom_roles.json:/app/custom_roles.json:ro
```

### Kubernetes/Helm Example

```yaml
# values.yaml
mcpContextForge:
  env:
    MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_ENABLED: "true"
    MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_FILE: "/config/custom_roles.json"

  # Mount ConfigMap with role definitions
  extraVolumes:
    - name: custom-roles
      configMap:
        name: mcp-gateway-roles
  extraVolumeMounts:
    - name: custom-roles
      mountPath: /config
```

### Error Handling

- **File not found**: Bootstrap continues with default roles only; warning logged
- **Invalid JSON**: Bootstrap continues with default roles only; error logged
- **Malformed entries**: Invalid role entries are skipped with warnings; valid entries are processed

!!! tip "Idempotent Bootstrap"
    Bootstrap is idempotent - running it multiple times won't duplicate roles. Existing roles are detected and skipped.

---

## Related Documentation

- [Team Management](teams.md) - Setting up teams and SSO mapping
- [Security Features](securing.md) - Comprehensive security configuration
- [Configuration Reference](configuration.md) - Environment variables
- [API Usage](api-usage.md) - Token usage in API calls
