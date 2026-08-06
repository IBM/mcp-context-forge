# Standardize scope checks for admin endpoints managing global records

**Issue:** [IBM/mcp-context-forge#5982](https://github.com/IBM/mcp-context-forge/issues/5982)
**Follow-up to:** internal issue 460 / GHSA-gj7g-7r6g-jc8v
**Date:** 2026-08-06
**Status:** Design approved, ready for implementation planning

## Problem

Admin-only routes that manage records with no team association apply four
different scope rules. Equivalent admin credentials therefore behave
differently depending on which route is called, and there is no mechanical
signal when a new global-record endpoint picks the wrong rule.

### Current rules

| Rule | Implementation | Team-scoped admin token (`teams: ["t1"]`) | Public-only admin token (`teams: []`) |
|------|----------------|-------------------------------------------|----------------------------------------|
| **A** — strict | `is_unrestricted_platform_admin()` (`auth_context.py:788`): `token_teams is None` AND `check_platform_admin_permission()` | 403 | 403 |
| **B** — loose | `@require_admin_permission()` (`middleware/rbac.py:951`) → `check_admin_permission()` (`permission_service.py:404`). With non-empty `token_teams` the `_is_user_admin(email)` short-circuit at line 430 returns `True` before any narrowing is applied. | allowed | allowed only via one of the four `admin.*` permissions |
| **C** — local reimplementation | `version.py:_has_version_admin_access()` (line 1228) | *unreachable* — see below | *unreachable* |
| **D** — plain permission | `@require_permission("admin.user_management")` | allowed | depends on token scope |

### Where each rule is used

- **Roots** (global, no team column) — Rule A, at 26 call sites: `admin.py:3847,14156,14200,14276,14314,14381,14436,15655,15733,15806,15867` and `main.py:7701,7730,7789,7828,7863,7899,7933,8987,11323,11528,12534,12608,12683`. The raise-helper `_require_unrestricted_root_admin` is **duplicated** in `admin.py:14117` and `main.py:7671`; the two bodies differ only in `403` vs `status.HTTP_403_FORBIDDEN`.
- **Compliance** — Rule B, at `routers/compliance_router.py:125,144,188,229,272` (prefix `/compliance`).
- **RBAC roles** — Rules B and D mixed within one file: `routers/rbac.py:81,212,259` (B) and `132,173,308,357,400` (D) (prefix `/rbac`).
- **Diagnostics** — Rule C, at `version.py:1359`.

### Two live defects this surfaces

1. **`ComplianceReport` is a dataclass** (`services/compliance_service.py:105`), not a
   DB model — it aggregates platform-wide state on demand and carries no team
   column. Under Rule B, an admin token narrowed to one team can generate and
   read a report covering every team. That is a Layer-1 scope escape.

2. **`/version` does not enforce what it documents.** `version.py:1359` calls
   `_has_version_admin_access(_user)` where `_user` comes from
   `Depends(require_admin_auth)`. `require_admin_auth`
   (`utils/verify_credentials.py:1623`) is annotated `-> str` and returns an
   email string. `_has_version_admin_access` short-circuits on
   `isinstance(user, str)` and returns `True`, so the
   `normalize_token_teams(user) is None` check at line 1244 is dead code in
   production. The docstring claims unrestricted admin scope is required; it is
   not.

### Correction to the initial reading of roles

`Role` (`db.py:1154-1193`) has **no `team_id` column**. `Role.scope` is one of
`global | team | personal`, but a `scope='team'` role is an unbound *template* —
it is not attached to any specific team and is assignable platform-wide. The
team binding lives on `UserRole.scope_id`, set at assignment time
(`UserRoleAssignRequest.scope_id`, `schemas.py:7630`).

Consequently:

- **Role definitions** (`/rbac/roles*`) are global records regardless of their
  `scope` value.
- **Role assignments** (`/rbac/users/{email}/roles`) are the genuinely
  team-scopable records, and are where the escalation path sits: today a
  narrowed admin holding `admin.user_management` can assign a global role
  carrying `*` to any user, including themselves.

## Goal

One documented rule per class of record, one shared implementation per rule,
applied deliberately at every admin-only global-record route, with a test that
fails when a new route is added without a classification.

## Design

### §1 Vocabulary

Four classes, defined once in `docs/docs/manage/rbac.md` and referenced from
the Security Invariants block in `CLAUDE.md`:

- **global-only** — the record has no team association. Requires *unrestricted
  platform admin*: `token_teams is None` AND `check_platform_admin_permission()`.
  A narrowed (`teams: ["t1"]`) or public-only (`teams: []`) admin token receives
  403.
- **filtered-read** — the record is global-only, but the route is a read whose
  narrowing is expressed as result filtering rather than a 403. Permitted only
  where a hard deny would break a legitimate caller, and each instance must state
  why. See §3.4.
- **team-scopable** — the record carries a team association. A narrowed admin is
  permitted when the token covers that team; the global variant of the same
  operation requires unrestricted platform admin.
- **exempt** — a documented non-admin surface (`/.well-known`, health probes).
  Recorded with a stated reason, never left implicit.

The global-only rule is Rule A as it exists today. Rule A is the canonical rule
because it is the only one of the four that honours Layer-1 narrowing, and
because widening to Rule B would contradict the existing invariant that
public-only tokens suppress admin bypass.

### §2 Helper surface

```
mcpgateway/auth_context.py
    is_unrestricted_platform_admin(request, user, db) -> bool       # existing, unchanged

mcpgateway/middleware/rbac.py
    require_unrestricted_platform_admin(request, user, db) -> None  # NEW, raises 403
    @require_global_admin_permission()                              # NEW, whole-endpoint decorator

mcpgateway/admin.py    - _require_unrestricted_root_admin   # deleted, import shared helper
mcpgateway/main.py     - _require_unrestricted_root_admin   # deleted, import shared helper
mcpgateway/version.py  - _has_version_admin_access          # deleted, see §3.6
```

Both new symbols live in `middleware/rbac.py` rather than `auth_context.py`, for
two reasons: `_ACCESS_DENIED_MSG` (`rbac.py:48`) is defined there and is already
imported from there by `admin.py:112` and `main.py:117`, and it keeps the import
direction one-way. `auth_context.py` imports only `config` and `db` at module
level; `middleware/rbac.py` already reaches into first-party modules with
deferred imports (e.g. `rbac.py:512`), so `is_unrestricted_platform_admin` is
imported there the same way. Putting the raise-helper in `auth_context.py`
instead would make it depend on `middleware.rbac` for the message constant and
invert that direction.

`require_global_admin_permission()` mirrors the existing
`require_admin_permission()` decorator shape (kwargs-based user-context
extraction, `db` from the endpoint's `db` param or `user_context["db"]`) and
raises 403 with `_ACCESS_DENIED_MSG`. It requires a `request` kwarg on the
decorated endpoint, since Layer-1 narrowing is read from `request.state`.

`require_unrestricted_platform_admin()` — the raise-form of the
`is_unrestricted_platform_admin` predicate — exists for the **conditional** call
sites, where the guard fires only when the request payload touches a global
record. These cannot use a decorator: `admin.py:15655,15733,15806,15867` and
`main.py:12534,12608,12683` check roots inside export/import handlers, gated on
`configuration_export_includes_roots()` / `import_envelope_includes_roots()`.
The bool predicate stays exported for `admin.py:3847`, which uses it to compute
a UI capability flag rather than to authorize.

### §3 Route changes

#### §3.1 Roots — no behavior change

Delete both copies of `_require_unrestricted_root_admin`; import
`require_unrestricted_platform_admin` from `auth_context` in `admin.py` and
`main.py`. All 26 call sites keep identical semantics. This is the
deduplication half of the issue's "reuse a shared scope helper" criterion.

#### §3.2 Compliance — tightened (breaking)

`routers/compliance_router.py:125,144,188,229,272` move from
`@require_admin_permission()` to `@require_global_admin_permission()`. Each of
the five endpoints requires a `request` param added to its signature.

Closes the cross-team aggregate leak. Breaking for callers using narrowed admin
tokens against `/compliance/*`.

#### §3.3 Role definitions — tightened (breaking)

`POST /rbac/roles` (line 81), `PUT /rbac/roles/{role_id}` (line 212),
`DELETE /rbac/roles/{role_id}` (line 259) move from
`@require_admin_permission()` to `@require_global_admin_permission()`.

Applies regardless of the submitted `role_data.scope`, per the correction
above: a `scope='team'` role definition is still an unbound platform-wide
template.

#### §3.4 Role definition reads — filtered

`GET /rbac/roles` (line 132) and `GET /rbac/roles/{role_id}` (line 173) keep
`@require_permission("admin.user_management")` and gain Layer-1 filtering:

- unrestricted admin (`token_teams is None`) — unchanged, sees all roles
- narrowed or public-only admin — sees `scope != 'global'` roles only;
  `GET /rbac/roles/{role_id}` on a global role returns 404

404 rather than 403 on the detail route, to avoid confirming the existence of a
role the caller may not enumerate.

`list_roles` currently applies **no** filtering at all — it passes the optional
`scope` query param straight to `RoleService.list_roles()` and returns
everything. Filtering is added in the router, not the service, so the service
stays a plain data-access layer consistent with the rest of the codebase.

Trade-off accepted: admin UI role pickers show fewer entries for narrowed
tokens, and a narrowed admin cannot read the definition of a global role they
may still hold.

#### §3.5 Role assignments — team-scoping model (breaking)

`POST /rbac/users/{user_email}/roles` (line 308) and
`DELETE /rbac/users/{user_email}/roles/{role_id}` (line 400) keep
`@require_permission("admin.user_management")` and gain a per-record check:

| Assignment | Requirement |
|------------|-------------|
| `scope='global'` | unrestricted platform admin |
| `scope='team'` | `scope_id` present AND `scope_id ∈ token_teams` (unrestricted admin passes) |
| `scope='personal'` | unrestricted admin, or caller assigning to themselves |

For `DELETE`, the existing `UserRole` row supplies `scope`/`scope_id`; the
request body does not. Never trust a client-supplied scope on delete.

This is the escalation fix: a narrowed admin can no longer assign a global
`*`-carrying role to themselves.

#### §3.6 `/version` — enforcement gap closed (breaking)

Replace `_user=Depends(require_admin_auth)` with
`user=Depends(get_current_user_with_permissions)` on `version_endpoint`, apply
`@require_global_admin_permission()`, and delete `_has_version_admin_access`
along with its now-unused `normalize_token_teams` import.

`/version` begins rejecting narrowed admin tokens, which is what its docstring
has claimed since it was written. Note in the release notes that `/version` is
a monitoring surface: any scraper authenticating with a narrowed admin token
will start receiving 403 and must switch to an unrestricted admin token.

The HTML login-redirect behavior of `require_admin_auth` for browser requests
must be preserved — verify the admin UI diagnostics page still redirects rather
than rendering a raw 403 when unauthenticated.

### §4 Drift guard

`tests/unit/mcpgateway/test_global_record_scope.py` holds three manifests keyed
on `(method, path_template)`:

```python
GLOBAL_ONLY    = {...}  # expects @require_global_admin_permission or the shared helper
FILTERED_READ  = {...}  # global records, but narrowing is applied as Layer-1 filtering, not 403
TEAM_SCOPABLE  = {...}  # record carries a team association; expects a documented per-record check
EXEMPT         = {...}  # documented non-admin surface, with a reason string
```

`FILTERED_READ` exists to resolve what would otherwise be a contradiction with
§1: `GET /rbac/roles` and `GET /rbac/roles/{role_id}` (§3.4) operate on global
records, yet do not 403 a narrowed admin. They are a distinct class — the record
is global-only, but Layer 1 is expressed as result filtering because a 403 on a
list route would break the admin UI. Any future route in this class must
document why filtering is correct in place of a hard deny.

Three tests:

1. `test_every_admin_route_is_classified` — walk `app.routes`, collect every
   route carrying an admin guard or an `admin.*` permission, assert the set is
   fully covered by the four manifests. A new unclassified route fails CI with
   a message pointing at `docs/docs/manage/rbac.md`.
2. `test_global_only_routes_carry_the_guard` — assert each `GLOBAL_ONLY` entry's
   endpoint has the decorator applied (detected via a marker attribute set by
   `require_global_admin_permission`, not by source inspection).
3. `test_manifests_are_disjoint` — no `(method, path)` appears in more than one
   manifest, so a route cannot be silently reclassified by adding it twice.

The decorator sets `wrapper.__mcpgateway_scope_class__ = "global_only"` so the
test inspects behavior-bearing metadata rather than parsing source.

As part of this task, triage the five routers that currently carry no
permission decorator at all — `metrics_maintenance.py`, `search.py`,
`server_well_known.py`, `well_known.py`, `reverse_proxy.py` — into `EXEMPT`
with a stated reason, or into a manifest if they need a guard. `well_known` and
`server_well_known` are expected to be genuinely public;
`metrics_maintenance` is the one to look at closely.

### §5 Per-route deny tests

Every route changed in §3.2–§3.6 gets three cases, satisfying the issue's
fourth acceptance criterion:

- unrestricted admin (`teams` claim absent or `null`, `is_admin: true`) → success
- team-scoped admin (`teams: ["t1"]`) → 403 for global-only; scoped success/403 for team-scopable
- public-only admin (`teams: []`) → 403

Follow the existing fixtures in `tests/unit/mcpgateway/test_auth_context_root_admin.py`,
which already exercise these three contexts against the roots routes.

### §6 Documentation

- `docs/docs/manage/rbac.md` — new section defining the three classes, the
  canonical rule, and the full classification table.
- `CLAUDE.md` Security Invariants — one line: global-record admin routes use
  `require_global_admin_permission()` / `require_unrestricted_platform_admin()`;
  do not re-implement the check.
- Release notes — the per-caller breaking-change table from the
  *Breaking-change analysis* section, with the remediation (reissue the token
  using `--admin`, or create it via the Admin UI without selecting a team).
  Note that omitting the `teams` claim is **not** a remediation: a missing key
  normalizes to `[]`, which is public-only.
- `CLAUDE.md` *MCP Helpers* — add `--admin` to the documented
  `create_jwt_token` invocation, and audit `README.md`, `docs/docs/`, and
  `.env.example` for other places the simple form is presented as the way to
  mint an admin token.

## Out of scope

- The full audit of every router under `mcpgateway/routers/`. This change covers
  the four divergent surfaces plus the drift guard; other routers are classified
  into manifests but not behaviorally changed.
- Merging `check_admin_permission()` and `check_platform_admin_permission()` in
  `permission_service.py`. Both remain; the difference is now expressed at the
  route layer by which decorator is chosen.
- Any change to `@require_permission()` or `@require_admin_permission()`
  semantics. Existing routes that legitimately use them are untouched.

## Breaking-change analysis

This is a breaking change. The affected population is determined entirely by
what the caller's JWT `teams` claim normalizes to, so the boundary runs through
token *minting* paths, not through caller type.

### Callers that break

| Caller | Why | Effect |
|--------|-----|--------|
| **Team-narrowed admin tokens** | Admin UI token created with a team selected emits `teams: [team_id]` (`services/token_catalog_service.py:274`); CLI `--teams` does the same (`utils/create_jwt_token.py:509-510`). Normalizes to `["t1"]`. | 403 on `/compliance/*`, role-definition mutation, global role assignment, `/version` |
| **Simple CLI tokens** | `create_jwt_token` stays in simple-token mode unless one of `--admin` / `--teams` / `--scopes` / `--full_name` is passed (line 495). In simple mode `teams` is `_TEAMS_UNSET`, so the claim is **omitted** (line 162). Omitted → `normalize_token_teams` → `[]` (public-only). | Same 403s |

The second row is the larger population and the less obvious one. These tokens
pass Rule B **today**: `check_admin_permission()` with `token_teams=[]` calls
`get_user_permissions(email, token_teams=[])`, and `_get_user_roles()` always
includes global roles regardless of narrowing, so a platform admin's global `*`
role is found and the check returns `True`. Under Rule A they are rejected.

### Callers that do not break

| Caller | Why |
|--------|-----|
| Admin UI browser sessions | Session token → `resolve_session_teams()` → DB is the authority → `None` → unrestricted |
| Admin UI API tokens created **without** a team | `teams = [team_id] if team_id else None` → explicit `null` + `is_admin` → unrestricted |
| CLI tokens created with `--admin` | Rich-token mode sets `teams = None` explicitly (line 508), which serializes as `"teams": null` |
| Basic auth / dev mode | Non-JWT path keeps unrestricted semantics (`auth_context.py:902`) |

### What softens the impact

Simple CLI tokens are **already** denied by Rule A today at all 26 root call
sites — `is_unrestricted_platform_admin` returns `False` for `token_teams == []`
(`auth_context.py:793`). So this change extends an existing, already-shipped
denial to more routes rather than introducing a new failure class. Anyone whose
tooling already works against `/roots` will be unaffected everywhere else.

For `/version` specifically, monitoring scrapers using **basic auth** are
unaffected; only JWT-authenticated scrapers with a narrowed or claim-less token
break.

### What sharpens it — the documented CLI path produces a breaking token

The command documented in `CLAUDE.md` under *MCP Helpers*:

```bash
python -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret KEY
```

passes none of the rich-token flags, so it mints a **public-only** token.
Following the project's own documentation to create an admin token yields one
that this change starts rejecting.

This must be resolved before implementation, not discovered after. Two options:

1. **Fix the docs** — add `--admin` to the documented invocation in `CLAUDE.md`
   and anywhere else the simple form is shown as the way to mint an admin token,
   and note in the release notes that existing tokens minted the old way need
   reissuing. Preferred: it keeps Rule A uniform and surfaces a docs bug that
   already misleads users about roots access.
2. **Exempt claim-less tokens** — treat a missing `teams` key as unrestricted for
   admins. Rejected: it contradicts the secure-default in
   `normalize_token_teams()` (missing key → `[]`) that the whole Layer-1 model
   rests on, and would silently widen roots access as a side effect.

Option 1 is the design's assumption. Implementation must include the docs fix
and an audit of other places the simple form is documented.

## Risks

| Risk | Mitigation |
|------|------------|
| Callers above lose access to `/compliance/*`, role mutation, `/version` | Release notes with the per-caller table and the reissue instructions |
| Users following `CLAUDE.md` mint a token this change rejects | Docs fix shipped in the same change; see above |
| `/version` 403s break JWT-authenticated monitoring scrapers | Called out explicitly in release notes; basic-auth scrapers unaffected; the HTML redirect path for browsers is preserved |
| Admin UI role picker shows fewer roles for narrowed tokens | Accepted per §3.4; verify the UI degrades gracefully rather than erroring |
| Decorator requires a `request` kwarg that some endpoints lack | Add the param; the drift-guard test catches a missing one at import time |
| Manifest drifts out of date | That is what §4's first test prevents |
