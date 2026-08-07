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

### Acceptance-criteria coverage

| Issue AC | Where | Status |
|---|---|---|
| Identify admin-only routes managing records without team ownership | Appendix A | met — 84 routes over the 48 team-less models, plus the 26 root call sites |
| Classify each as global-only, or define a valid team-scoping model | Appendix A + §1 classes; §3.5 defines the team-scoping model for role assignments | met |
| Reuse a shared scope helper where behavior is equivalent | §2; §3.1 collapses 26 root call sites onto one helper | **partial** — the 64 deferred routes in A.2/A.4 have equivalent behaviour and keep their own guards until follow-up 1 |
| Add tests for unrestricted, team-scoped, and public-only admin contexts | §5 | **partial** — the three contexts are tested on the 13 changed routes; deferred routes get classification coverage only (§4), not per-context deny tests |
| Document exceptions where behavior intentionally differs | Appendix A.3, §4 `EXEMPT` | met |

**Identification and classification are complete; remediation is deliberately
partial.** This change fixes the four rule-divergent surfaces in A.1. The 64
deferred routes in A.2 and A.4 are identified, classified, and covered by the
drift guard, but their guards are changed in a follow-up — see *Out of scope*
and *Follow-up issues to file*.

Stated plainly: this PR **applies** the canonical rule to 13 of the 77
admin routes over global records. Two of the five acceptance criteria are
therefore only partially satisfied, as marked above. #5982 must stay open until
follow-up 1 lands. Anyone reviewing this change should read it as "establish the
rule, the shared helper, and the drift guard, then migrate the highest-risk
surfaces" — not as a complete discharge of the issue.

Scope creep to be aware of, both deliberate: §3.4's filtered reads are a
visibility change rather than a scope check, and §6's minting warning plus docs
sweep are remediation for a defect that predates this issue. Neither is
requested by #5982; both are justified in place.

Route counts by class: 13 changed here (A.1, plus the 26 root call sites which
are a refactor only), 64 deferred (A.2 + A.4), 7 exempt (A.3).

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

**Denials must be self-diagnosing.** Both raise paths emit one structured log
line before raising, carrying the caller email, the route, and the *resolved*
`token_teams` — the value the rule actually judged, not the raw claim — plus the
remediation. The `HTTPException` detail names the remediation too, without
leaking whether the record exists:

```
global-record scope denied: user=%s route=%s token_teams=%r
  (route requires an unrestricted platform-admin token; reissue with
   `--admin`, or create the token without selecting a team)
```

This is deliberate, not incidental. It is what makes immediate enforcement
tenable in place of a warn-then-enforce flag: an operator who is denied learns
why and how to fix it from a single line, which was the flag's real value. See
*Rejected alternatives*. Keep the log line on one code path so enforce-time
denials and any future audit of them can never disagree.

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
`@require_admin_permission()` to `@require_global_admin_permission()`.

**Signature changes are mandatory, not incidental.** The decorator reads Layer-1
narrowing from `request.state`, so every decorated endpoint needs a `request`
param — none of the five has one today. It also needs a DB session for
`check_platform_admin_permission()`: four endpoints have `db`, but
`list_frameworks` (line 126) has **neither** `request` nor `db`. The decorator
must therefore fall back to `fresh_db_session()` when no `db` kwarg is present,
mirroring how `require_admin_permission()` already resolves its session.

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

Trade-off accepted: a narrowed admin cannot read the definition of a global role
they may still hold.

**Correction to the original rationale.** This class was justified on the grounds
that a 403 would break the admin UI role picker. Verification found no such
consumer: `mcpgateway/admin_ui/` contains no request to `/rbac/roles` — the only
mention is static copy pointing users at the Teams tab — and `admin.py` exposes
no roles endpoints of its own. The filtered-read choice still stands on Layer-1
semantics (scoping controls visibility) and because it is strictly less breaking
than a deny, but not for the reason originally given.

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

**Do not swap the dependency.** `version_endpoint` (`version.py:1259`) keeps
`_user=Depends(require_admin_auth)`. The narrowing check moves inside the
handler, reading `request` (already a parameter) via the shared predicate:

```python
if not await is_unrestricted_platform_admin(request, _user, db):
    raise HTTPException(status_code=403, detail=_ACCESS_DENIED_MSG)
```

`_has_version_admin_access` is deleted along with its `normalize_token_teams`
import. A `db` session must be obtained — `/version` has no `db` param today, so
either add one or use `fresh_db_session()`.

**Why not the decorator.** `get_current_user_with_permissions`
(`middleware/rbac.py:238`) has **no HTTP Basic path** — `basic_security` /
`HTTPBasicCredentials` do not appear anywhere in that module. `require_admin_auth`
(`utils/verify_credentials.py:1623-1627`) accepts
`basic_credentials: Optional[HTTPBasicCredentials] = Depends(basic_security)`.
Swapping the dependency would turn every basic-auth call to `/version` into a
**401**, which is a strictly larger break than the 403 this change intends, and
it would hit exactly the monitoring callers that the breaking-change analysis
otherwise records as unaffected.

Keeping `require_admin_auth` also preserves its HTML login-redirect behavior for
browser requests for free.

`/version` begins rejecting narrowed and claim-less admin tokens, which is what
its docstring has claimed since it was written. Basic-auth callers keep working:
the non-JWT path in `auth_context.py:902` returns unrestricted semantics.

**Admin UI dependency:** `/version?partial=true` is fetched by
`admin_ui/initialization.js:846` and `admin_ui/tabs.js:728`. Those go through the
browser session cookie, so `resolve_session_teams()` resolves admin from the DB
and yields `None` (unrestricted). The diagnostics tab is unaffected, but it is
the one UI path crossing a changed route and must be covered in the test plan.

### §4 Drift guard

`tests/unit/mcpgateway/test_global_record_scope.py` holds five manifests keyed
on `(method, path_template)`:

```python
GLOBAL_ONLY          = {...}  # expects @require_global_admin_permission or the shared helper
GLOBAL_ONLY_DEFERRED = {...}  # same class, guard NOT yet migrated — see Appendix A.2/A.4
FILTERED_READ        = {...}  # global records, narrowing applied as Layer-1 filtering, not 403
TEAM_SCOPABLE        = {...}  # record carries a team association; documented per-record check
EXEMPT               = {...}  # documented non-admin surface, with a reason string
```

`GLOBAL_ONLY_DEFERRED` is load-bearing, not bookkeeping. Without it the manifest
would have to place the Appendix A.2/A.4 routes in `GLOBAL_ONLY`, and test 2
below — which asserts every `GLOBAL_ONLY` entry carries the guard — would fail
on day one for all 64 of them. Splitting the bucket lets test 1 cover the
deferred routes (so none can drift away unclassified) while test 2 only holds
the routes this change actually migrates. Follow-up 1 empties
`GLOBAL_ONLY_DEFERRED` into `GLOBAL_ONLY`; the day it is empty, delete it.

`FILTERED_READ` exists to resolve what would otherwise be a contradiction with
§1: `GET /rbac/roles` and `GET /rbac/roles/{role_id}` (§3.4) operate on global
records, yet do not 403 a narrowed admin. They are a distinct class — the record
is global-only, but Layer 1 is expressed as result filtering because a 403 on a
list route would break the admin UI. Any future route in this class must
document why filtering is correct in place of a hard deny.

Three tests:

1. `test_every_admin_route_is_classified` — walk `app.routes`, collect every
   route carrying an admin guard or an `admin.*` permission, assert the set is
   fully covered by the five manifests. A new unclassified route fails CI with
   a message pointing at `docs/docs/manage/rbac.md`.
2. `test_global_only_routes_carry_the_guard` — assert each `GLOBAL_ONLY` entry's
   endpoint has the decorator applied (detected via a marker attribute set by
   `require_global_admin_permission`, not by source inspection).
   `GLOBAL_ONLY_DEFERRED` is deliberately **excluded** from this assertion.
3. `test_manifests_are_disjoint` — no `(method, path)` appears in more than one
   manifest, so a route cannot be silently reclassified by adding it twice.
4. `test_deferred_bucket_only_shrinks` — assert `GLOBAL_ONLY_DEFERRED` has no
   more entries than the count recorded in Appendix A. A new route may not be
   added to the deferred bucket to dodge test 2; deferral is a record of
   existing debt, not an escape hatch for new code.

The decorator sets `wrapper.__mcpgateway_scope_class__ = "global_only"` so the
test inspects behavior-bearing metadata rather than parsing source.

`GLOBAL_ONLY` is seeded from **Appendix A.1**, `GLOBAL_ONLY_DEFERRED` from
**A.2 and A.4**, and `EXEMPT` from **A.3**. Recording the deferred routes rather
than omitting them is deliberate: it makes the drift guard useful from day one
and prevents a new LLM-config or observability route from landing unclassified
while the follow-up is pending.

**Guard detection must inspect dependencies, not just decorators.** Walk
`app.routes` and examine each route's resolved `dependencies` alongside its
endpoint attributes. A decorator-only check misreports
`routers/metrics_maintenance.py` — which guards all four of its routes through a
router-level `dependencies=[Depends(require_admin_auth)]` (Appendix A.4) — as
unguarded.

Of the five routers carrying no per-route permission decorator, `well_known.py`,
`server_well_known.py`, `search.py`, and `reverse_proxy.py` are expected to be
genuinely public and go to `EXEMPT` with a stated reason.
`metrics_maintenance.py` goes to `GLOBAL_ONLY` (deferred, with A.2).

### §5 Per-route deny tests

Every route changed in §3.2–§3.6 gets three cases, satisfying the issue's
fourth acceptance criterion:

- unrestricted admin (`teams` claim absent or `null`, `is_admin: true`) → success
- team-scoped admin (`teams: ["t1"]`) → 403 for global-only; scoped success/403 for team-scopable
- public-only admin (`teams: []`) → 403

Follow the existing fixtures in `tests/unit/mcpgateway/test_auth_context_root_admin.py`,
which already exercise these three contexts against the roots routes.

**Delivered in layers, not as one deny test per route.** Implementation planning
surfaced a constraint that makes the naive form unsound: router modules are
imported once per session, and 26 suites import them under
`tests/utils/rbac_mocks.patch_rbac_decorators`, which swaps the RBAC decorators
for no-ops. Whichever test module imports a router first decides whether its
decorators are real. A per-route deny test in a second module would pass or fail
on import order — an order-dependent flake presenting as coverage.

The three contexts are therefore covered as:

| Layer | Proves |
|-------|--------|
| Unit tests against the real decorator, all three contexts | what the guard does |
| `__mcpgateway_scope_class__` marker assertions + the §4 drift guard | that these routes use it |
| Direct handler calls | filtering (§3.4) and the assignment scope matrix (§3.5) |
| Existing roots suites | the conditional raise-helper call sites still fire |

Together these give the same guarantee. Do not "restore" per-route deny tests
for the decorated routes.

### §5.1 Existing tests must be reworked, not merely extended

The current unit suites authenticate by overriding
`get_current_user_with_permissions` with a bare dict, e.g.
`test_compliance_router.py:64` returns `{"email": "admin@example.com", "is_admin": True}`
and installs it at lines 325 and 349. That dict carries no
`request.state.token_teams`, so `get_rpc_filter_context()` falls back to
`normalize_token_teams()` on an absent verified payload and resolves to `[]` —
public-only. Under the canonical rule every one of those tests would receive a
403.

This is a structural incompatibility, not a handful of assertion updates. The
override must set `request.state.token_teams` (or the fixture must mint a real
JWT via `tests/helpers/auth.make_test_jwt(..., is_admin=True, teams=None)`,
which is the pattern `tests/populate/verify.py:56-61` already uses correctly).

Approximate scope: 17 tests in `tests/unit/mcpgateway/routers/test_compliance_router.py`,
35 in the rbac router tests, 28 in `tests/unit/mcpgateway/test_version.py`. Plan
for a shared fixture rather than per-test edits.

### §5.2 The pre-merge validation gate is not at risk

Verified against the live-gateway harnesses that gate #5 depends on:

- `tests/populate/verify.py:56-61` passes `teams=None, is_admin=True` → unrestricted.
- `tests/live_gateway/mcp/test_mcp_rbac_transport.py:211` mints `admin_api` with
  `is_admin=True, teams=None` → unrestricted. The role assignments at lines
  140-151 create *team-scoped* assignments but are performed **by** that
  unrestricted admin, so §3.5 does not reject them.

`make test-mcp-rbac`, `test-mcp-protocol-e2e`, and `test-protocol-compliance`
therefore pass unchanged. This was checked explicitly because a break here would
block the gate rather than merely inconvenience callers.

Separately, `Makefile:5979` (`compose-test-hardened`) mints a token with the
simple no-`--admin` form. It only curls `/tools`, so it does not break, but it is
the same anti-pattern the §6 docs fix must sweep up.

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
- `mcpgateway/utils/create_jwt_token.py` — when the username resolves to a DB
  admin and none of `--admin` / `--teams` / `--scopes` / `--full_name` was
  passed, print a warning: the token will carry no `teams` claim, that
  normalizes to public-only, and `--admin` is the fix. This is the minting-side
  half of the mitigation. The claim-less population are people who followed the
  docs, not people who chose narrowing, so the durable fix is to stop producing
  those tokens rather than to exempt them.
- Docs sweep — the simple form is presented as the way to mint an admin token
  at these known sites, all of which need `--admin`:
  `CLAUDE.md` *MCP Helpers*; `README.md` (7 occurrences, at lines 213, 245, 425,
  542, 626, 658, 949); `docs/docs/manage/export-import-reference.md:184`;
  `docs/docs/manage/export-import-tutorial.md:20`;
  `docs/docs/manage/sso-adfs-tutorial.md:60`. Also check `.env.example`.
  Note that `docs/docs/manage/api-usage.md` already gets this right and is the
  model to follow.
  The `export-import-*` sites are fixing **live** breakage — those flows touch
  roots, which Rule A already denies today.
- `Makefile:5979` (`compose-test-hardened`) uses the same simple form. It only
  curls `/tools` so it does not break, but it should be corrected alongside the
  docs.

## Follow-up issues to file

**File these after the implementation lands, not before** — the route counts and
file:line references below must be re-verified against the merged code, and the
§4 manifests are the authoritative source for the route lists by then.

### Follow-up 1 — apply the canonical rule to the deferred routes

- **Title:** `[BUG]: Team-narrowed admin tokens bypass Layer 1 on admin routes guarded by require_permission`
- **Labels:** `bug`, `security`, `rbac`, `api`, `triage`
- **Template:** `.github/ISSUE_TEMPLATE/bug-report-code.md`
- **Body should cover:**
  - `services/permission_service.py:125-132` suppresses admin bypass only for
    public-only tokens (`token_teams == []`); with a non-empty `token_teams` the
    `elif allow_admin_bypass and await self._is_user_admin(...)` branch returns
    `True` unconditionally, so a token narrowed to one team retains full admin
    authority.
  - This contradicts `is_unrestricted_platform_admin()`
    (`auth_context.py:788-799`), which rejects any non-`None` `token_teams`. The
    two are the codebase's two answers to the same question.
  - Affected surface: the 60 Rule D routes in Appendix A.2 plus the four
    router-level-guarded routes in A.4 — LLM config and admin, observability,
    SSO provider management, SIEM destinations, log search, runtime mode,
    toolops, metrics maintenance.
  - Note the ambiguity honestly: it is not self-evident whether the current
    behaviour is intended. Maintainers must decide whether Layer 1 narrowing
    binds admin bypass everywhere (making this a bug) or only on the routes that
    opt in (making it a design choice needing documentation). Frame it as a
    question, not an accusation.
  - Reference this spec and the PR that resolves the A.1 surfaces.
  - Note that #5982 should stay open until this lands.

### Follow-up 2 — align `/version` and `metrics_maintenance` on a single admin dependency

- **Title:** `[CHORE]: Consolidate require_admin_auth and get_current_user_with_permissions for admin-only routes`
- **Labels:** `chore`, `rbac`, `api`, `triage`
- **Template:** `.github/ISSUE_TEMPLATE/chore-task--devops--linting--maintenance-.md`
- **Body should cover:**
  - Two admin dependencies coexist with different capabilities:
    `require_admin_auth` (`utils/verify_credentials.py:1623`) supports HTTP
    Basic and browser login redirects but returns a bare email string and never
    consults `token_teams`; `get_current_user_with_permissions`
    (`middleware/rbac.py:238`) resolves full Layer-1 context but has no HTTP
    Basic path.
  - This forced §3.6 of the linked spec to keep `require_admin_auth` on
    `/version` and add the narrowing check inside the handler, because swapping
    the dependency would have turned basic-auth calls into 401.
    `metrics_maintenance` has the same shape at the router level.
  - The cleanup is to give one dependency both capabilities so admin-only routes
    stop choosing between basic-auth support and Layer-1 awareness.
  - Explicitly a maintenance item, not a security fix — no behaviour change is
    being requested, only the removal of the fork that makes correct usage
    awkward.

## Appendix A — Full classification of admin routes over global records

This appendix satisfies the issue's first two acceptance criteria. Every route
here manages a record whose ORM model has **no `team_id` column** (48 of the 66
models in `db.py` qualify), so all of them are global records by the issue's
definition.

Paths below are router-local plus the router's own `prefix`; a few routers are
mounted with an additional prefix at `include_router` time (e.g.
`llm_proxy_router` under `settings.llm_api_prefix`). The §4 manifests must key
on the **final mounted path**, resolved from `app.routes` rather than from
source.

### A.1 Changed in this PR — the four rule-divergent surfaces

| Method + path | Current guard | Class |
|---|---|---|
| roots — 26 call sites in `admin.py` / `main.py` | Rule A (duplicated helper) | global-only (dedupe only, §3.1) |
| `GET /compliance/frameworks` | `require_admin_permission()` | global-only (§3.2) |
| `POST /compliance/reports` | `require_admin_permission()` | global-only (§3.2) |
| `GET /compliance/reports` | `require_admin_permission()` | global-only (§3.2) |
| `GET /compliance/reports/{report_id}` | `require_admin_permission()` | global-only (§3.2) |
| `GET /compliance/reports/{report_id}/export` | `require_admin_permission()` | global-only (§3.2) |
| `POST /rbac/roles` | `require_admin_permission()` | global-only (§3.3) |
| `PUT /rbac/roles/{role_id}` | `require_admin_permission()` | global-only (§3.3) |
| `DELETE /rbac/roles/{role_id}` | `require_admin_permission()` | global-only (§3.3) |
| `GET /rbac/roles` | `require_permission("admin.user_management")` | filtered-read (§3.4) |
| `GET /rbac/roles/{role_id}` | `require_permission("admin.user_management")` | filtered-read (§3.4) |
| `GET /rbac/users/{user_email}/roles` | `require_permission("admin.user_management")` | team-scopable (§3.5) — added by Task 9's drift-guard audit; missing from this table in the original appendix despite carrying the identical guard and `UserRole.scope_id` record class as its POST/DELETE siblings below |
| `POST /rbac/users/{user_email}/roles` | `require_permission("admin.user_management")` | team-scopable (§3.5) |
| `DELETE /rbac/users/{user_email}/roles/{role_id}` | `require_permission("admin.user_management")` | team-scopable (§3.5) |
| `GET /version` | Rule C, unenforced | global-only (§3.6) |

### A.2 Classified, NOT changed in this PR — the Rule D surface

All of the following guard global records with
`@require_permission("admin.<something>")`. **Rule D is a fifth variant, and for
a team-narrowed admin token it behaves exactly like Rule B.**
`services/permission_service.py:125-132`:

```python
if token_teams is not None and len(token_teams) == 0:
    ...                       # public-only: bypass correctly suppressed
elif allow_admin_bypass and await self._is_user_admin(user_email):
    return True               # <-- token_teams == ["t1"] lands here
```

With a non-empty `token_teams` the `elif` fires and returns `True`
unconditionally, so a narrowed admin token receives full access. This is the
same divergence from Rule A that §3.2 fixes for compliance, across a much larger
surface.

| Router (prefix) | Routes | Guard | Records |
|---|---|---|---|
| `llm_config_router` | 13 | `admin.system_config` | `LLMProvider`, `LLMModel` |
| `llm_admin_router` | 13 | `admin.system_config` | `LLMProvider`, `LLMModel` |
| `observability` (`/observability`) | 8 | `admin.system_config` | `ObservabilityTrace/Span/SavedQuery` |
| `sso` (`/auth/sso`) | 7 | `admin.sso_providers:*`, `admin.user_management` | `SSOProvider`, `PendingUserApproval` |
| `siem` (`/admin/siem`) | 5 | `admin.security_audit` | `SecurityEvent`, destinations |
| `log_search` (`/api/logs`) | 5 | `logs:read`, `security:read`, `audit:read`, `metrics:read` | `StructuredLogEntry`, `SecurityEvent`, `PerformanceMetric` |
| `runtime_admin_router` | 4 | `admin.system_config` | global runtime mode |
| `toolops_router` (`/toolops`) | 3 | `admin.system_config` | `ToolOpsTestCases` |
| `rbac` (`/rbac`) | 2 | `admin.security_audit` | permission introspection |

**60 routes.** They are recorded in the §4 `GLOBAL_ONLY_DEFERRED` manifest so the
drift-guard test covers them immediately, but their guards are **not** changed
here — see *Out of scope* for why, and for the follow-up issue this requires.

### A.3 Exempt — documented non-admin surfaces

| Method + path | Reason |
|---|---|
| `GET /auth/sso/providers` | Login-page provider list; must be reachable pre-authentication |
| `GET /auth/sso/login/{provider_id}` | SSO initiation; pre-authentication by definition |
| `GET /auth/sso/callback/{provider_id}` | SSO callback; authenticated by the IdP handshake, not by a gateway token |
| `GET /rbac/permissions/available` | Static catalogue of permission strings; no record data |
| `GET /rbac/my/roles` | Self-scoped — returns only the caller's own assignments |
| `GET /rbac/my/permissions` | Self-scoped — same |
| `GET /llm/gateway/models` (`llm_config_router.py:597`) | Feeds the LLM Chat model selector. Guarded by `Depends(get_current_user)` — authenticated but deliberately not admin-scoped, since any user of LLM Chat needs the enabled-model list. Returns only enabled, chat-capable models from enabled providers. Path corrected by Task 9's drift-guard audit: this table originally listed the router-local path (`/gateway/models`) rather than the final mounted path under `llm_config_router`'s `/llm` include-time prefix, which this appendix's own rule ("manifests key on the final mounted path") requires |

### A.4 Router-level guard — a sixth pattern

`routers/metrics_maintenance.py` carries no *per-route* decorator, but the
router itself declares one at `metrics_maintenance.py:27`:

```python
router = APIRouter(..., dependencies=[Depends(require_admin_auth)])
```

| Method + path | Effective guard |
|---|---|
| `POST /api/metrics/cleanup` | router-level `require_admin_auth` |
| `POST /api/metrics/rollup` | router-level `require_admin_auth` |
| `GET /api/metrics/stats` | router-level `require_admin_auth` |
| `GET /api/metrics/config` | router-level `require_admin_auth` |

These routes **are** authenticated. They are, however, a sixth pattern:
`require_admin_auth` returns a plain email string and checks only the DB
`is_admin` flag — it never consults `token_teams`. A team-narrowed admin token
therefore passes, exactly as it does on the Rule D routes in A.2. Same
divergence class, expressed through a router-level dependency instead of a
decorator.

Classified as **global-only, deferred** alongside A.2.

**Design consequence for §4:** the drift-guard test cannot detect guards by
inspecting endpoint decorators alone. It must walk `app.routes` and examine each
route's resolved `dependencies` as well, or it will report these four routes —
and any future router using this pattern — as unguarded. A survey of the other
routers found no further router-level auth dependencies (`siem` receives an
include-time dependency, but it is `enforce_admin_csrf`, not authentication).

## Out of scope

- **Changing the 64 deferred routes in A.2 and A.4.** They are identified and
  classified here, which is what the issue's first two acceptance criteria ask
  for, but changing them is roughly 14× the blast radius and test rework of the
  four surfaces in A.1 and would make the PR unreviewable. They need a follow-up
  issue, and that issue is a prerequisite for calling #5982 fully resolved. The
  §4 drift-guard test covers them from day one, so nothing regresses in the
  interim.
- **Reconciling `check_permission()`'s admin-bypass semantics** with
  `is_unrestricted_platform_admin()`. The two disagree about whether a
  team-narrowed admin token retains bypass; resolving that is the substance of
  follow-up issue 1 below, not of this change.
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

### Measured blast radius — no known callers break

The repository was swept for callers that would actually hit the two rows above
on the four changed routes. Result: **none found.**

| Probe | Finding |
|-------|---------|
| `/compliance/*` callers outside the router and its tests | **zero** — nothing in `charts/`, `docs/`, `mcp-servers/`, `a2a-agents/`, or scripts |
| Shipped SDK or client library calling admin routes | none exists in-repo |
| In-repo harnesses hitting `/rbac/roles` and role assignment | all mint unrestricted: `tests/populate/populate.py:85-89` and `tests/loadtest/locustfile_mcp_isolation.py:224` pass `is_admin=True, teams=None`; `tests/loadtest/locustfile.py:610` sets `token_use: "session"`, which resolves through the DB |
| Helm chart `/version` smoke test (`charts/mcp-stack/values.yaml:1997`) | sends **no auth header at all** — not a narrowed-token caller |
| Documented `--teams` usage (`docs/docs/manage/api-usage.md:52`) | applies to `user@example.com`, a **non-admin**, labeled DEV/TEST ONLY. The admin example immediately above it already uses `--admin` |

Nothing in the repository documents or performs `--admin` combined with
`--teams`, which is the exact pairing that would break.

This measurement is what justifies enforcing immediately rather than shipping a
warn-then-enforce deprecation flag. A flag would add a permanent settings knob,
a second code path through security-critical helpers, and a sunset that requires
a human to honour — all to buy a deprecation window for a population the
codebase gives no evidence exists, while leaving the §3.5 privilege-escalation
path open for a release. See *Rejected alternatives*.

Caveat: this bounds what is **in the repository**. It cannot see a private
deployment wiring a narrowed admin token to `/compliance/*`. But there is no
first-party or documented pattern that would lead an operator there.

### The claim-less docs population is a pre-existing bug, not a new break

The simple `create_jwt_token` form appears in `README.md` (7 sites),
`docs/docs/manage/export-import-reference.md:184`,
`docs/docs/manage/export-import-tutorial.md:20`, and
`docs/docs/manage/sso-adfs-tutorial.md:60`:

```bash
python -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret KEY
```

It passes none of the rich-token flags, so it mints a **public-only** token.

Crucially, the `export-import-*` documents mint that token *for export/import,
which touches roots* — already Rule A today. **Those docs are already broken
before this change.** The remaining README sites cover `/tools`, `/servers`, and
`/gateways`, none of which this change touches.

So the docs defect is real and worth fixing, but it is largely orthogonal to
this change rather than caused by it. Two options were considered:

1. **Fix the minting side and the docs** — see §6. Preferred: it removes the
   footgun permanently instead of granting it an exemption, and it repairs
   breakage that is already live.
2. **Exempt claim-less tokens** — treat a missing `teams` key as unrestricted for
   admins. Rejected: it contradicts the secure-default in
   `normalize_token_teams()` (missing key → `[]`) that the whole Layer-1 model
   rests on, and would silently widen roots access as a side effect.

Fixing the minting side and the docs is the design's assumption.

## Rejected alternatives

**Warn-then-enforce deprecation flag.** A `GLOBAL_RECORD_SCOPE_ENFORCEMENT=warn|enforce`
setting defaulting to permissive for one minor, flipping at a sunset. Rejected
on measured blast radius: the sweep above found no callers the window would
protect. Its costs are concrete — a permanent config knob, duplicate code paths
through the security-critical helpers until removed, doubled deny-path tests,
and a sunset that no test can *actuate* (only detect, and the cheapest way to
green a failing sunset test is to bump the sunset constant). Most decisively, it
would leave the §3.5 privilege-escalation path — a narrowed admin assigning
themselves a global `*` role — open for an additional release.

The diagnostic value that motivated the flag is retained at near-zero cost by
the structured denial logging in §2.

**Scoping compliance reports by team instead of denying.** Rejected: reports are
FedRAMP / SOC 2 control attestations (`AC-2` account management, `AC-3` access
enforcement, `AC-6` least privilege) built from user inventory, role inventory,
audit logs, and config snapshot. An attestation scoped to one team is not an
attestation. The same reasoning rules it out for `/version`, which has no team
dimension to filter on. Filtering applies only where the data has a team axis —
`GET /rbac/roles*`, per §3.4.

## Risks

| Risk | Mitigation |
|------|------------|
| An unmeasured caller exists outside the repo using a narrowed admin token against a changed route | The sweep bounds only in-repo callers and found none. Mitigated by the §2 structured denial log and the remediation in the error detail, so an affected operator self-diagnoses in one line. This is the residual risk accepted by enforcing immediately |
| Users following `README.md` / `export-import-*` docs mint a token that is rejected | §6 minting warning + docs sweep in the same change. Note the `export-import-*` sites are **already** broken today under Rule A, so this repairs live breakage rather than creating it |
| `/version` 403s break JWT-authenticated monitoring scrapers | Release notes. Basic-auth scrapers are unaffected **only because §3.6 keeps `require_admin_auth`** — swapping to `get_current_user_with_permissions` would 401 them, since that dependency has no HTTP Basic path |
| Existing unit suites authenticate with bare dicts that resolve to public-only, so ~80 tests would 403 | §5.1: rework the fixtures to set `request.state.token_teams` or mint real JWTs; budget this as a task, not a cleanup |
| Decorated endpoints lack the `request`/`db` params the decorator needs | §3.2: add `request` to all five compliance endpoints; decorator falls back to `fresh_db_session()` when no `db` kwarg is present. The §4 drift-guard test catches a missing one at import time |
| ~~Admin UI role picker shows fewer roles for narrowed tokens~~ | Not a real risk — verification found no admin-UI consumer of `/rbac/roles`. See the correction in §3.4 |
| Manifest drifts out of date | That is what §4's first test prevents |
