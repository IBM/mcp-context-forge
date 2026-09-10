# Implementation Plan — Canonical User ID (#5884) and JWT-Trust Mode (#5885)

Status: draft for team review.
Repo: IBM/mcp-context-forge. Base: `main` tip at planning time (`13d549371`).
Executors: fast models. Every work order is self-contained.

## 1. Purpose

ContextForge identifies users by e-mail string today. This plan implements two epics:

- Epic 1, #5884: give every user a stable, opaque user ID. The e-mail becomes a changeable attribute.
- Epic 2, #5885: add a mode where a signed JWT alone proves identity, roles, and teams. No local user record is read on the request path.

The plan splits the work into 24 pull requests (PRs). Each PR closes one story issue. The PRs form two stacks.

## 2. Fixed decisions

| # | Decision |
|---|----------|
| D1 | Semantic re-keying only. No foreign key is re-pointed in Epic 1. Column names stay. |
| D2 | Phase A (stories #5886-#5891) changes code only. No migration. No behavior change. |
| D3 | Phase B (stories #5892-#5894) adds one nullable `user_id` column and populates it. The uniqueness constraint is a deferred follow-up. |
| D4 | One PR per story. Stacks: Stack A (Epic 1, 10 PRs), Stack B (Epic 2, 14 PRs). Stack B starts after Stack A merges. |
| D5 | One external group maps to one CF team and, optionally, one role. Unique key: (issuer, tenant, external_group_id). `cf_role` lives in the same row. |
| D6 | All pushes and PR actions go through the `gh` tool (`gh stack submit`, `gh pr ...`). Never raw `git push`. |
| D7 | ASD-STE100 Simplified English for all writing: plan, commits, PR bodies, docs. |

## 3. Stack map

Stack A (Epic 1) — order is fixed; each branch cuts from the previous story's branch:

| PR | Story | Title |
|----|-------|-------|
| A.1 | #5886 | Identifier-domain doc + get_user_id helper |
| A.2 | #5887 | Principal shape carries user_id |
| A.3 | #5888 | Audit/observability identity semantics |
| A.4 | #5889 | Permission path consumes user_id |
| A.5 | #5890 | Team resolution consumes user_id |
| A.6 | #5891 | Auth cache re-keyed by user_id |
| A.7 | #5892 | user_id column migration + backfill |
| A.8 | #5893 | Population + writer-side re-keying |
| A.9 | #5894 | Diverged-ID separation suite |
| A.10 | #5895 | Epic 1 gate + docs sweep |

Stack B (Epic 2) — starts from `main` after Stack A merges:

| PR | Story | Title |
|----|-------|-------|
| B.1 | #5896 | Token-dispatch rule doc + deny matrix |
| B.2 | #5897 | Feature-by-mode matrix doc |
| B.3 | #5898 | Config surface (trust mode, claims, overage, revocation claim) |
| B.4 | #5976 | external_group_mappings table + resolver + admin CRUD |
| B.5 | #6272 | Group-to-role wiring (cf_role) |
| B.6 | #5899 | trusted_claims module + virtual principal |
| B.7 | #5977 | Entra overage Graph client + cache |
| B.8 | #5900 | Trust branch in get_current_user |
| B.9 | #5901 | revoked_by FK relax + revocation semantics |
| B.10 | #5902 | Admin claim feeds both tracks + parity |
| B.11 | #5903 | External IdP trust root, no provisioning |
| B.12 | #5904 | Trust-token minting + choke points |
| B.13 | #5905 | Acceptance suite |
| B.14 | #5906 | Docs sweep + Epic 2 gate |

## 4. Bootstrap (run once, before story A.1)

1. `cd mcpgateway && alembic heads` — record the head. The output must show exactly one head. A.7 and B.9 re-verify and target the head they see at their start time.
2. `make test` — record a green baseline. A failing baseline stops the run. Report it; do not fix unrelated failures.
3. `gh stack --help` — confirm the gh-stack extension answers.
4. `git status --porcelain` — the tree must be clean before each story starts.

## 5. Execution protocol (every story)

1. Read the work order. Read the story issue (`issue://NNNN`). The issue wins if the plan and the issue disagree; report the disagreement.
2. Cut the branch: `git checkout -b <type>/<issue-num>-<slug>` from the previous story branch (Stack A first story: from `main`).
3. Follow the steps in order. TDD is mandatory where the order says so. Run each command. Compare each result with the expected result.
4. Run the gates listed in the order. All must pass.
5. Commit: `git commit -s` with the message given in the order.
6. Submit: `gh stack submit`. PR body comes from the order.
7. If any pre-existing test fails, stop. Report. Never weaken a test.
8. After a PR lands (merge), `gh stack rebase` keeps the rest of the stack current. If a story no longer applies cleanly, re-read its work order and the changed files, then adapt. Report every adaptation.

## 6. Writing and evidence rules

- STE for every sentence that enters a commit, PR, or doc.
- Never mention AI assistants in PRs or diffs.
- Every PR body records: the commands run and their results (gate evidence), and the risk to existing users. Write "none" only when true.
- Never print secret values in evidence. Test secrets come from tests/conftest.py.
- Commit subjects are verbatim from the story issue. When an order's scope exceeds its subject, add a commit body that lists the extra scope: `git commit -s -m '<subject>' -m '<body>'.`
- Where a PR body is given as instructions ("State what changed: ..."), compose the body in STE. Follow the quoted-skeleton pattern of WO-A.1: what changed, how tested, acceptance met, risk.

---

# Stack A — Work Orders (Epic 1, #5884)

Ten self-contained orders. Each closes one story issue. Orders run in sequence A.1 through A.10; each branch cuts from the previous order branch.

## WO-A.1 — #5886 canonical get_user_id helper + identifier-domain doc

- **Branch:** `feat/5886-get-user-id-helper` cut from `main`.
- **Goal:** Add `get_user_id()` next to `get_user_email()` and write the identifier-domain mapping doc. No call site changes.
- **Read first:** `issue://5886` (the story contract). Then `mcpgateway/auth_context.py` — find `def get_user_email` and read its body and doctests. Then `tests/unit/mcpgateway/test_auth_context.py` (exists; classes `TestScopedResourceAccessContext`, `TestMalformedJwtPayload`, `TestRequestScopedMemoization`).
- **Context you may assume:** Nothing prior; this is the first story of Stack A. `EmailUser` (class in `mcpgateway/db.py`) has a UUID primary key `id` and a unique `email`. It has no `user_id` column. WARNING: `mcpgateway/admin.py` already defines its own `get_user_id` (JWT payload helper). It is a different function in a different module. Do not import it, alias it, or reuse it.

### Steps
1. Cut the branch from `main` tip.
2. Open `mcpgateway/auth_context.py`. Find `def get_user_email`. Read the full function and its doctest cases. Do not change it.
3. Write failing tests first. In `tests/unit/mcpgateway/test_auth_context.py`, add a new class `TestGetUserId` with these cases:
   - dict with both keys `{"user_id": "u-1", "email": "e@x"}` → `"u-1"` (explicit `user_id` wins).
   - dict with e-mail only `{"email": "e@x"}` → `"e@x"`.
   - dict with sub only `{"sub": "e@x"}` → `"e@x"`.
   - empty dict `{}` → `"unknown"`.
   - `None` → `"unknown"`.
   - object with `user_id` attribute set to `"u-1"` and `email` attribute set to `"e@x"` (use `MagicMock`) → `"u-1"`.
   - object with only `email` attribute `"e@x"` → `"e@x"`.
   - legacy string `"legacy_user"` → `"legacy_user"`; empty string `""` → `"unknown"`.
4. Run the fast gate (Tests below). Expect FAIL with `ImportError: cannot import name 'get_user_id'`.
5. Implement. In `mcpgateway/auth_context.py`, directly below `get_user_email`, add `def get_user_id(user: Any) -> str:` with this exact precedence:
   - `user is None` → `"unknown"`.
   - dict: `"user_id"` key if it is a non-empty string → return it; else `"email"` key if non-empty string → return it; else `"sub"` key if non-empty string → return it; else `"unknown"`.
   - other object: attribute `user_id` if it is a non-empty string → return it; else attribute `email` if it is a string → return it when non-empty; else fall through.
   - everything else: `str(user) if user else "unknown"`.
6. Add doctests inside the new function's docstring. Mirror the `get_user_email` doctest cases (dict both keys, e-mail only, sub only, `{}`, `None`, `''`, object with `user_id`). Keep each example one line of output.
7. Run the fast gate again. Expect PASS.
8. Run the import check: `uv run python -c "from mcpgateway.auth_context import get_user_id"`. Expect no output, exit 0.
9. Create `docs/docs/architecture/identity-domains.md`. Write a table with one row per token type and columns: token type, `sub` content, resolution layer, canonical user_id (phase 1). Rows:
   - session token (`token_use="session"`): `sub` = UUID (`EmailUser.id`); resolution layer = `_get_email_by_id_sync` and `get_user_email_from_token` in `mcpgateway/auth.py`, plus `resolve_jwt_user_email_from_payload` in `mcpgateway/auth_context.py`; canonical user_id = e-mail (phase 1).
   - API token: `sub` = UUID, signed metadata carries e-mail; resolution layer = `resolve_jwt_user_email_from_payload`; canonical user_id = e-mail (phase 1).
   - legacy token (no `token_use`): `sub` = e-mail; resolution layer = none (direct); canonical user_id = e-mail (phase 1).
   - future trust token: `sub` = opaque; resolution layer = trusted-claims module (not built yet, Epic #5885); canonical user_id = to be defined by Stack B.
   Below the table, state: `get_user_email()` is the e-mail-attribute accessor. `get_user_id()` is the identity accessor. Phase 1 populates both with the same value. The old assumption "the e-mail is the identity" (see the comment in `mcpgateway/middleware/auth_middleware.py`) is abolished by later stories.
10. Run `make doctest`. Expect green. The new doctests in `auth_context.py` run as part of it.
11. Run `make ruff`. Expect green.
12. Verify no schema drift: `cd mcpgateway && alembic heads`. Expect one head, unchanged from before the story. Then `cd` back to the repo root and run `git diff --name-only`. Expect no files under `mcpgateway/migrations/`.

### Files
- `mcpgateway/auth_context.py` — modify (add `get_user_id` below `get_user_email`).
- `tests/unit/mcpgateway/test_auth_context.py` — modify (add `TestGetUserId`).
- `docs/docs/architecture/identity-domains.md` — create.

### Tests (exact commands)
- Fast gate: `uv run pytest tests/unit/mcpgateway/test_auth_context.py -q` — expect FAIL at step 4, PASS at step 7.
- Import check: `uv run python -c "from mcpgateway.auth_context import get_user_id"` — expect exit 0.
- Checkpoint gate: `make doctest` — expect green. `make ruff` — expect green.
- Schema check: `cd mcpgateway && alembic heads` — expect the same single head as before the story.

### Guardrails (do NOT)
- Do not change any call site. `get_user_id` ships unused in this story.
- Do not change any schema or add a migration file.
- Do not change `get_user_email()` behavior, return values, or doctest outputs.
- Do not import, alias, or reuse `get_user_id` from `mcpgateway/admin.py`.
- Do not weaken or delete an existing test. If a pre-existing test fails, STOP and report.

### Done when
- `uv run pytest tests/unit/mcpgateway/test_auth_context.py -q` is green including the new `get_user_id` cases (dict, ORM-like object, legacy string, `"unknown"` fallback).
- `uv run python -c "from mcpgateway.auth_context import get_user_id"` succeeds.
- `docs/docs/architecture/identity-domains.md` exists and names all four token types.
- `cd mcpgateway && alembic heads` output is unchanged.

### Commit
`git commit -s` with message: `feat(auth): add canonical get_user_id helper and identifier-domain mapping doc`

### PR
- Title: `feat(auth): add canonical get_user_id helper and identifier-domain mapping doc`
- Body (STE skeleton): "This PR adds `get_user_id()` to `mcpgateway/auth_context.py`. The helper reads an explicit `user_id` first, then the e-mail value, then falls back to `unknown`. This PR adds `docs/docs/architecture/identity-domains.md` with the token-type mapping table. No call site, schema, or behavior changed. Tested with <commands>. Acceptance criteria of #5886 are met. Risk to existing users: none."
- Footer: `Closes #5886`
- Submit: `gh stack submit` (never raw `git push`).

---

## WO-A.2 — #5887 every principal carries user_id

- **Branch:** `refactor/5887-principal-user-id` cut from `feat/5886-get-user-id-helper`.
- **Goal:** Every principal and user-dict construction site emits `user_id` equal to the e-mail. Zero behavior change otherwise.
- **Read first:** `issue://5887` (the story contract). Then READ `tests/helpers/auth.py` COMPLETELY before you edit anything — two scouts disagree on whether its fixtures set `token_use` today. Do not assume; read the file and extend what is actually there. Then locate each site below by SYMBOL NAME with grep.
- **Context you may assume:** WO-A.1 landed: `from mcpgateway.auth_context import get_user_id` works. `UserContext` (class defined in `cpex.framework`, re-exported from `mcpgateway/transports/context.py`) already has a `user_id` field. If you open `transports/context.py` you find only the re-export; that is correct. The six construction sites, by symbol:
  1. `UserContext` construction inside `get_current_user` — `mcpgateway/auth.py` (grep `UserContext(`). Two more `UserContext(` sites exist (`mcpgateway/middleware/rbac.py` proxy path, `mcpgateway/transports/streamablehttp_transport.py` stateful-session path); both already set `user_id` — verify, do not redesign.
  2. `_normalize_jwt_payload` — `mcpgateway/transports/streamablehttp_transport.py` (grep `def _normalize_jwt_payload`). It builds the `user_ctx` dict literal with keys `email, teams, is_admin, is_authenticated, token_use`, and two cached user-dict literals passed to `set_auth_context`.
  3. `_bootstrap_platform_admin_user` — `mcpgateway/auth.py` (grep `def _bootstrap_platform_admin_user`). Returns a synthesized `EmailUser`.
  4. `_user_from_cached_dict` — `mcpgateway/auth.py` (grep `def _user_from_cached_dict`). Rebuilds `EmailUser` from a cached dict. Its dict producer `_get_auth_context_batched_sync` builds `result["user"] = {"email": user.email, ...}` (grep `"email": user.email` in `mcpgateway/auth.py` — exactly one hit today).
  5. `_authenticate_proxy_user` — `mcpgateway/utils/verify_credentials.py` (grep `def _authenticate_proxy_user`). Builds two payload dict literals with keys `sub, source, token, is_admin, teams, email, token_use`.
  6. `build_external_identity` — `mcpgateway/utils/verify_credentials.py` (grep `def build_external_identity`). Builds a synthesized `payload: dict` with `"email": email`.

### Steps
1. Cut the branch from the previous story's branch.
2. Read `tests/helpers/auth.py` in full. Extend `make_test_jwt` with two optional keyword params: `token_use: str | None = None` and `user_id: str | None = None`. When passed, add `"token_use": token_use` and `"user_id": user_id` to the payload. When not passed, emit exactly the same token as today. Do not change any other helper in the file.
3. Write failing tests first. Add one contract test per site:
   - `tests/unit/mcpgateway/test_auth.py` (extend; grep this file for `_bootstrap_platform_admin_user` and `_user_from_cached_dict` to find the existing test classes):
     - `test_bootstrap_platform_admin_user_carries_user_id`: call `_bootstrap_platform_admin_user("admin@x.test")`; assert `getattr(user, "user_id", None) == "admin@x.test"` and `user.email == "admin@x.test"`.
     - `test_user_from_cached_dict_carries_user_id`: call `_user_from_cached_dict({"email": "a@x.test", "user_id": "a@x.test", ...minimal keys...})`; assert `user.user_id == "a@x.test"`. Also call it without the `user_id` key; assert it falls back to the e-mail.
     - `test_batched_auth_context_user_dict_carries_user_id`: patch the DB session used by `_get_auth_context_batched_sync` (copy the existing mock pattern from this file); assert `result["user"]["user_id"] == result["user"]["email"]`.
   - `tests/unit/mcpgateway/transports/test_streamablehttp_transport.py` (extend; grep `_normalize_jwt_payload` in this file for the existing test class): `test_normalize_jwt_payload_carries_user_id`: call `_normalize_jwt_payload` with a payload fixture built by `make_test_jwt` decoded, or the plain dict used by the existing tests; assert `user_ctx["user_id"] == user_ctx["email"]`.
   - `tests/unit/mcpgateway/utils/test_verify_credentials.py` (extend): `test_proxy_payload_carries_user_id` and `test_external_identity_payload_carries_user_id`: build each payload through the existing fixtures in this file; assert `payload["user_id"] == payload["email"]`.
4. Run the fast gate (Tests below). Expect FAIL: each new test fails because `user_id` is absent.
5. Implement, one site at a time:
   - `UserContext` in `get_current_user` (`mcpgateway/auth.py`): it already sets `user_id=user.email`. Change nothing in the value. Update the adjacent comment to: canonical user_id, phase-1 value = e-mail.
   - `_normalize_jwt_payload`: add `"user_id": email` to the `user_ctx` dict literal. Add `"user_id": ...` (same value as the `"email"` entry) to both cached user-dict literals passed to `set_auth_context`.
   - `_bootstrap_platform_admin_user`: assign the `EmailUser(...)` result to a local `user`, then set `user.user_id = email` (a transient instance attribute — NOT a column), then return `user`. The attribute is not persisted and does not survive ORM serialization. That is intentional: the bootstrap user is synthetic and is never cached.
   - `_get_auth_context_batched_sync`: add `"user_id": user.email` to the `result["user"]` dict literal.
   - `_user_from_cached_dict`: assign the `EmailUser(...)` result to `user`, then set `user.user_id = user_dict.get("user_id") or user_dict["email"]`, then return `user`.
   - `_authenticate_proxy_user`: add `"user_id": proxy_user` to BOTH payload dict literals.
   - `build_external_identity`: add `"user_id": email` to the synthesized `payload` dict literal.
6. Update the stale comment in `mcpgateway/middleware/auth_middleware.py`. Grep `CSRF/logging identity is the email`. Rewrite the note: the canonical identity comes from `get_user_id()`; the e-mail stays the e-mail attribute; phase-1 values are equal. Change the comment only. Do not change the code lines around it.
7. Run the fast gate again. Expect PASS.
8. Prove the six sites by grep (each must show a `user_id` at the construction site): `grep -n "user_id" mcpgateway/auth.py mcpgateway/transports/streamablehttp_transport.py mcpgateway/utils/verify_credentials.py`.
9. Run `make ruff`. Expect green.
10. Run `make test` (checkpoint story). Expect green, with no test modified outside your new cases.

### Files
- `tests/helpers/auth.py` — modify (extend `make_test_jwt`; read before editing).
- `mcpgateway/auth.py` — modify (four sites: `UserContext` comment, `_bootstrap_platform_admin_user`, `_user_from_cached_dict`, `_get_auth_context_batched_sync`).
- `mcpgateway/transports/streamablehttp_transport.py` — modify (`_normalize_jwt_payload`).
- `mcpgateway/utils/verify_credentials.py` — modify (`_authenticate_proxy_user`, `build_external_identity`).
- `mcpgateway/middleware/auth_middleware.py` — modify (comment only).
- `tests/unit/mcpgateway/test_auth.py`, `tests/unit/mcpgateway/transports/test_streamablehttp_transport.py`, `tests/unit/mcpgateway/utils/test_verify_credentials.py` — modify (new tests).

### Tests (exact commands)
- Fast gate: `uv run pytest tests/unit/mcpgateway -k "principal or jwt_payload or user_context" -q` plus the three files you extended: `uv run pytest tests/unit/mcpgateway/test_auth.py tests/unit/mcpgateway/transports/test_streamablehttp_transport.py tests/unit/mcpgateway/utils/test_verify_credentials.py -q` — expect FAIL at step 4, PASS at step 7.
- Checkpoint gate: `make ruff` — green. `make test` — green.

### Guardrails (do NOT)
- Do not remove or rename the `email` key at any site.
- Do not change the `EmailUser` ORM: no column, no migration, no model edit. `user.user_id` is a transient attribute only.
- Do not change the return type of `get_current_user` (still `EmailUser` in default mode).
- Do not change `get_user_email()`.
- Do not alter `make_test_jwt` default output when the new kwargs are not passed.
- Do not weaken or delete an existing test. If a pre-existing test fails, STOP and report.

### Done when
- Grep shows `user_id` present at all six construction sites.
- `uv run pytest tests/unit/mcpgateway -k "principal or jwt_payload or user_context" -q` is green.
- Full `make test` is green, unmodified elsewhere.

### Commit
`git commit -s` with message: `refactor(auth): carry user_id alongside email in all principal construction sites`

### PR
- Title: `refactor(auth): carry user_id alongside email in all principal construction sites`
- Body (STE skeleton): "This PR adds a `user_id` entry to every principal and user-dict construction site. The phase-1 value equals the e-mail. The six sites are: `UserContext` in `get_current_user`, `_normalize_jwt_payload`, `_bootstrap_platform_admin_user`, `_user_from_cached_dict` plus its producer `_get_auth_context_batched_sync`, `_authenticate_proxy_user`, and `build_external_identity`. The stale identity comment in `auth_middleware.py` is corrected. Test fixtures in `tests/helpers/auth.py` gained optional `token_use` and `user_id` kwargs. Tested with <commands> and `make test`. Acceptance criteria of #5887 are met. Risk to existing users: none; values are unchanged."
- Footer: `Closes #5887`
- Submit: `gh stack submit` (never raw `git push`).

---

## WO-A.3 — #5888 audit and observability record canonical user_id

- **Branch:** `refactor/5888-audit-user-id` cut from the previous story's branch (`refactor/5887-principal-user-id`).
- **Goal:** Audit and observability identity fields record the canonical user_id. Column names, schemas, and values stay unchanged.
- **Read first:** `issue://5888` (the story contract). Then `mcpgateway/auth_context.py` (`def get_user_email` docstring), `mcpgateway/services/audit_trail_service.py` (grep `def log_action`), `mcpgateway/db.py` (classes `AuditTrail`, `ObservabilityTrace`), and the `AGENTS.md` section `User Identity Extraction`.
- **Context you may assume:** WO-A.1 and WO-A.2 landed. Principals carry `user_id == email`. The audit capture in services goes through `audit_trail.log_action(user_id=..., user_email=...)`. In `mcpgateway/services/tool_service.py` and `mcpgateway/services/gateway_service.py`, grep `audit_trail.log_action(` — every call passes an identity string as `user_id=<expr> or "system"`.

### Steps
1. Cut the branch from `refactor/5887-principal-user-id`.
2. Write failing tests first:
   - In `tests/unit/mcpgateway/test_auth.py`, add `test_user_context_identity_uses_get_user_id`: build a mock `EmailUser` with `user_id = "u-1"` and `email = "e@x.test"` (values diverge on purpose). Drive the code path in `get_current_user` that sets `global_context.user_context = UserContext(...)` (grep `UserContext(` in `mcpgateway/auth.py`; reuse the existing test fixtures in this file for the auth stack). Assert `global_context.user_context.user_id == "u-1"`. Before the change this records `"e@x.test"`, so the test fails.
   - In `tests/unit/mcpgateway/services/test_audit_trail_service.py`, add a class `TestAuditIdentity` with two tests: (a) a principal `{"user_id": "u-1", "email": "e@x.test"}` resolves to identity `"u-1"` through `get_user_id`, and an audit entry built with that identity stores `user_id == "u-1"`; (b) a principal `{"user_id": "u-1"}` (e-mail absent) still records `"u-1"`; a principal `{}` records `"unknown"`.
3. Run the fast gate (Tests below). Expect FAIL on the new `UserContext` test.
4. Implement:
   - `mcpgateway/auth.py`, at the `UserContext(...)` construction inside `get_current_user`: change the identity argument to `user_id=get_user_id(user)` (import it from `mcpgateway.auth_context`). With real `EmailUser` objects the value is unchanged, because the e-mail attribute is the fallback.
   - `mcpgateway/services/tool_service.py` and `mcpgateway/services/gateway_service.py`: at every `audit_trail.log_action(` call, replace `user_id=<param> or "system"` with `user_id=get_user_id(<param>) if <param> else "system"`. Use the exact guard: when the parameter is empty, keep `"system"` — do NOT let `get_user_id(None)` turn the value into `"unknown"` here. Import `get_user_id` from `mcpgateway.auth_context` in both files.
   - `mcpgateway/db.py`: in class `AuditTrail`, extend the `user_id` column comment: holds the canonical user_id; phase-1 value = e-mail; name kept for compatibility. In class `ObservabilityTrace`, extend the `user_email` column comment with the same statement. Comments only.
   - `mcpgateway/auth_context.py`: extend the `get_user_email` docstring. State: this function is the e-mail-attribute accessor; `get_user_id` is the identity accessor; the e-mail-over-sub order stays for the ATTRIBUTE in phase 1. Do not change its code or any existing doctest output.
   - `AGENTS.md`, section `User Identity Extraction`: add the two-accessor rule (e-mail attribute vs canonical identity) and state that audit and observability identity fields hold the canonical user_id. Same commit.
5. Run the fast gate again. Expect PASS.
6. Run `make doctest`. Expect green — `get_user_email` doctest outputs are unchanged.
7. Run `make ruff`. Expect green.
8. Run `git diff --name-only`. Expect no alembic files and no file under `mcpgateway/migrations/`.

### Files
- `mcpgateway/auth.py` — modify (`UserContext` identity argument).
- `mcpgateway/services/tool_service.py`, `mcpgateway/services/gateway_service.py` — modify (`log_action` identity expressions).
- `mcpgateway/db.py` — modify (column comments only).
- `mcpgateway/auth_context.py` — modify (docstring only).
- `AGENTS.md` — modify (`User Identity Extraction` section).
- `tests/unit/mcpgateway/test_auth.py`, `tests/unit/mcpgateway/services/test_audit_trail_service.py` — modify (new tests).

### Tests (exact commands)
- Fast gate: `uv run pytest tests/unit/mcpgateway/test_auth.py tests/unit/mcpgateway/services/test_audit_trail_service.py -q` — expect FAIL at step 3, PASS at step 5.
- Checkpoint gate: `make doctest` — green. `make ruff` — green.
- Diff check: `git diff --name-only` — no alembic or migration files.

### Guardrails (do NOT)
- Do not rename any column or change any schema.
- Do not alter `get_user_email()` return values or doctest outputs.
- Do not let empty identity become `"unknown"` at the `log_action` sites; keep the `"system"` fallback.
- Do not weaken or delete an existing test. If a pre-existing test fails, STOP and report.

### Done when
- `make doctest` is green.
- The new audit-identity unit tests are green.
- `AGENTS.md` is updated in the same commit.
- `git diff --name-only` shows no alembic files.

### Commit
`git commit -s` with message: `refactor(auth): record canonical user_id in audit and observability identity fields`

### PR
- Title: `refactor(auth): record canonical user_id in audit and observability identity fields`
- Body (STE skeleton): "This PR routes audit and observability identity capture through `get_user_id()`. The `UserContext` identity now comes from `get_user_id(user)`. Audit calls in tool and gateway services derive the identity the same way. Column comments in `AuditTrail` and `ObservabilityTrace` state the new semantics. `get_user_email` keeps its behavior and gains a role statement. `AGENTS.md` documents the two-accessor rule. Tested with <commands> and `make doctest`. Acceptance criteria of #5888 are met. Risk to existing users: none; phase-1 values are identical."
- Footer: `Closes #5888`
- Submit: `gh stack submit` (never raw `git push`).

---

## WO-A.4 — #5889 permission path resolves identity via get_user_id

- **Branch:** `refactor/5889-rbac-user-id` cut from the previous story's branch (`refactor/5888-audit-user-id`).
- **Goal:** The permission path reads identity through `get_user_id()`. Phase-1 values stay e-mail strings, so the role queries are unchanged.
- **Read first:** `issue://5889` (the story contract). Then, by symbol: `mcpgateway/services/permission_service.py` (class `PermissionService`; methods `check_permission`, `get_user_permissions`, `_get_user_roles`; the admin-bypass block that suppresses bypass for public-only tokens), `mcpgateway/middleware/rbac.py` (functions `get_current_user_with_permissions`, `check_permission_inline`, `_resolve_team_and_check_mode`, `require_permission`, `require_admin_permission`; class with `self.user_context["email"]` at its `check_permission` calls), `mcpgateway/utils/admin_check.py` (functions `is_user_admin`, `should_apply_admin_bypass`).
- **Context you may assume:** WO-A.1–A.3 landed. Principals carry `user_id == email`. All `PermissionService` role queries run against `user_roles.user_email` (model `UserRole` in `mcpgateway/db.py`); phase-1 identity values are e-mail strings, so those queries keep working unchanged.

### Steps
1. Cut the branch from `refactor/5888-audit-user-id`.
2. Write failing tests first. In `tests/unit/mcpgateway/middleware/test_rbac.py`, add a class `TestUserIdKeyedPermissionChecks`:
   - `test_check_permission_inline_uses_canonical_user_id`: build `user_context = {"user_id": "u-1", "email": "e@x.test", "db": object()}`. Patch `mcpgateway.middleware.rbac.PermissionService` with a spy class (copy the `DummyPS` pattern from the `require_permission` doctest). Call `check_permission_inline(user_context, "tools.read")`. Assert the spy received `user_email="u-1"`. Before the change it receives `"e@x.test"`, so the test fails.
   - `test_require_permission_denies_without_identity`: a user context without `email` and without `user_id` still raises 401 (unchanged behavior).
   - `test_permission_checker_class_uses_canonical_user_id`: same spy pattern against the `PermissionChecker`-style class in `rbac.py` (grep `self.user_context["email"]`).
   Keep every existing deny-path test untouched, including those in `tests/unit/mcpgateway/middleware/test_rbac_admin_bypass.py`.
3. Run the fast gate (Tests below). Expect FAIL on the two new spy tests.
4. Implement:
   - `mcpgateway/middleware/rbac.py`, in `check_permission_inline`: compute `identity = get_user_id(user_context)` once at the top (import from `mcpgateway.auth_context`). Classify every `user_context["email"]` occurrence in this file by its USE, then replace only identity uses with `identity`: (i) arguments passed to `PermissionService` methods (`user_email=...` or positional) and to `HttpAuthCheckPermissionPayload(user_email=...)` — replace; (ii) values passed to plugin audit callbacks — replace; (iii) text inside logger f-strings — keep as the e-mail attribute. At planning time the file held about 20 occurrences: 5 logging-only, the rest identity or audit uses. Re-derive the split by pattern at execution time; do not trust the count. Leave the `team_id`/`check_any_team` logic untouched.
   - Same replacement inside the `require_permission` and `require_admin_permission` wrapper paths and the class methods that call `self.user_context["email"]` (grep `user_context["email"]` in this file; replace each identity use with the precomputed `identity`).
   - Keep the 401 guard `"email" not in user_context` exactly as it is. Do not widen it in this story.
   - `mcpgateway/services/permission_service.py`: in `check_permission`, `get_user_permissions`, and `_get_user_roles`, update the docstrings: the `user_email` parameter carries the canonical user_id; phase-1 value = e-mail; queries are unchanged. No query edits.
   - `mcpgateway/utils/admin_check.py`: update the `is_user_admin` docstring the same way (the parameter carries the canonical user_id; phase-1 value = e-mail). No logic edits.
5. Run the fast gate again. Expect PASS.
6. Run `make ruff`. Expect green.

### Files
- `mcpgateway/middleware/rbac.py` — modify (identity extraction via `get_user_id`).
- `mcpgateway/services/permission_service.py` — modify (docstrings only).
- `mcpgateway/utils/admin_check.py` — modify (docstring only).
- `tests/unit/mcpgateway/middleware/test_rbac.py` — modify (new tests).

### Tests (exact commands)
- Fast gate: `uv run pytest tests/unit/mcpgateway/middleware/test_rbac.py tests/unit/mcpgateway/middleware/test_rbac_admin_bypass.py tests/unit/mcpgateway/services -k "permission or rbac" -q` — expect FAIL at step 3, PASS at step 5. Then the issue's full selection: `uv run pytest tests -k "permission or rbac" -q` — expect green including the new user_id-keyed cases.
- Checkpoint gate: `make ruff` — green.

### Guardrails (do NOT)
- Do not change the `user_roles` schema or any role seeding.
- Do not change admin-bypass semantics: public-only tokens (`token_teams == []`) still suppress admin bypass (the block in `permission_service.py` stays as is).
- Do not rename the `user_email` parameter of `PermissionService` methods in this story.
- Do not modify any existing deny-path test (insufficient permissions, public-only admin suppression).
- Do not weaken or delete an existing test. If a pre-existing test fails, STOP and report.

### Done when
- `uv run pytest tests -k "permission or rbac" -q` is green, including the new user_id-keyed cases.
- The deny-path tests (insufficient permissions, public-only admin suppression) pass unmodified.

### Commit
`git commit -s` with message: `refactor(rbac): resolve identity via canonical user_id in permission path`

### PR
- Title: `refactor(rbac): resolve identity via canonical user_id in permission path`
- Body (STE skeleton): "This PR resolves the caller identity through `get_user_id()` in the RBAC middleware. `check_permission_inline`, the `require_permission` decorator paths, and the permission-checker class now pass the canonical user_id to `PermissionService`. Phase-1 values are e-mail strings, so role queries and admin-bypass semantics are unchanged. Docstrings in `permission_service.py` and `admin_check.py` state the new parameter meaning. Tested with <commands>. Acceptance criteria of #5889 are met. Risk to existing users: none; values are identical in phase 1."
- Footer: `Closes #5889`
- Submit: `gh stack submit` (never raw `git push`).

---

## WO-A.5 — #5890 team resolution keys on canonical user_id

- **Branch:** `refactor/5890-team-user-id` cut from the previous story's branch (`refactor/5889-rbac-user-id`).
- **Goal:** Session team resolution keys on the canonical user_id. The DB-authority contract and `normalize_token_teams()` behavior stay unchanged.
- **Read first:** `issue://5890` (the story contract). Then, by symbol in `mcpgateway/auth.py`: `resolve_session_teams`, `_resolve_teams_from_db`, `_get_user_team_ids_sync`, `_narrow_by_jwt_teams`, `normalize_token_teams`. Then the call sites: `mcpgateway/middleware/token_scoping.py` (grep `resolve_session_teams(`), `mcpgateway/transports/streamablehttp_transport.py` (grep `resolve_session_teams(`), and `mcpgateway/services/team_management_service.py` (methods `add_member_to_team`, `remove_member_from_team`, `get_member`). Then the `AGENTS.md` Token Scoping tables.
- **Context you may assume:** WO-A.1–A.4 landed. Principals carry `user_id == email`. Team membership queries run against `email_team_members.user_email` (model `EmailTeamMember`); phase-1 identity values are e-mail strings, so those queries are unchanged. Cache keys for teams use `f"{identity}:True"` (grep `set_user_teams(` and `get_user_teams(` in `mcpgateway/auth.py`).

### Steps
1. Cut the branch from `refactor/5889-rbac-user-id`.
2. Write failing tests first. In `tests/unit/mcpgateway/middleware/test_token_scoping.py`, add a class `TestUserIdKeyedTeamResolution` (duplicate the existing truth-table tests with user_id-keyed payloads):
   - `test_resolve_session_teams_uses_canonical_user_id`: build `payload = {"user_id": "u-1", "sub": "e@x.test", "token_use": "session"}`. Patch `_resolve_teams_from_db` (or `_get_user_team_ids_sync`) with a spy. Call `resolve_session_teams(payload, "e@x.test", {"is_admin": False})`. Assert the spy was called with `"u-1"`. Before the change it is called with `"e@x.test"`, so the test fails.
   - `test_revoked_membership_fails_closed`: spy returns `[]` for the identity; assert the result is `[]` (public-only), not `None` (no admin bypass).
   - `test_jwt_teams_intersect`: payload carries `teams=["t1"]`, spy returns `["t1","t2"]`; assert the result is `["t1"]`.
   - `test_missing_identity_falls_back_to_email_param`: payload without `user_id`/`email`/`sub`; the e-mail argument `"e@x.test"` is used (unchanged behavior).
3. Run the fast gate (Tests below). Expect FAIL on the first test.
4. Implement, in `mcpgateway/auth.py`:
   - In `resolve_session_teams`, at the top of the body, compute `identity = get_user_id(payload)` (import from `mcpgateway.auth_context`). If `identity == "unknown"` and the `email` argument is a non-empty string, set `identity = email`. Pass `identity` (not the raw `email` argument) into `_resolve_teams_from_db`, `_get_user_team_ids_sync`, and the team-cache key expressions `f"{identity}:True"`. Keep the function signature and the admin-bypass logic exactly as they are.
   - In `_resolve_teams_from_db` and `_get_user_team_ids_sync`, update the docstrings: the parameter carries the canonical user_id; phase-1 value = e-mail; the `EmailTeamMember.user_email` queries are unchanged.
   - Read `_narrow_by_jwt_teams`. It takes the payload and the DB teams only; it uses no identity. Change nothing. Note this in the PR body.
   - In `team_management_service.py`, update the docstrings of `add_member_to_team`, `remove_member_from_team`, and `get_member`: the `user_email` parameter carries the canonical user_id; phase-1 value = e-mail. No query edits.
   - Call sites in `token_scoping.py` and `streamablehttp_transport.py`: no code change is needed — they pass the e-mail argument, which stays the fallback. Verify each site still compiles and its tests pass.
5. Run the fast gate again. Expect PASS.
6. Run the full team selection (Tests below). Expect green.
7. Run `make ruff`. Expect green.

### Files
- `mcpgateway/auth.py` — modify (`resolve_session_teams` identity derivation; docstrings of `_resolve_teams_from_db`, `_get_user_team_ids_sync`).
- `mcpgateway/services/team_management_service.py` — modify (docstrings only).
- `tests/unit/mcpgateway/middleware/test_token_scoping.py` — modify (new tests).

### Tests (exact commands)
- Fast gate: `uv run pytest tests/unit/mcpgateway/middleware/test_token_scoping.py tests/unit/mcpgateway/test_auth.py -q` — expect FAIL at step 3, PASS at step 5.
- Issue selection: `uv run pytest tests -k "team or scoping" -q` — expect green, with the truth tables (missing/null/`[]`/`["t1"]` × admin) covered by existing tests plus the new user_id-keyed duplicates.
- Checkpoint gate: `make ruff` — green.

### Guardrails (do NOT)
- Do not change the DB-authority contract for session tokens: session team membership always resolves from the DB.
- Do not change `normalize_token_teams()` behavior.
- Do not change any `email_team_members` query or the `EmailTeamMember` model.
- Do not modify the AGENTS.md truth-table outcomes; only add the user_id note if the issue requires it.
- Do not weaken or delete an existing test. If a pre-existing test fails, STOP and report.

### Done when
- `uv run pytest tests -k "team or scoping" -q` is green.
- The AGENTS.md token-scoping truth tables (missing/null/`[]`/`["t1"]` × admin) pass via existing tests plus the new user_id-keyed duplicates.

### Commit
`git commit -s` with message: `refactor(auth): key session team resolution on canonical user_id`

### PR
- Title: `refactor(auth): key session team resolution on canonical user_id`
- Body (STE skeleton): "This PR keys session team resolution on the canonical user_id. `resolve_session_teams` derives the identity with `get_user_id()` and keeps the e-mail argument as fallback. Team membership queries are unchanged because phase-1 values are e-mail strings. `_narrow_by_jwt_teams` needs no change; it uses no identity. Docstrings state the new parameter meaning. Tested with <commands>. Acceptance criteria of #5890 are met. Risk to existing users: none; values are identical in phase 1."
- Footer: `Closes #5890`
- Submit: `gh stack submit` (never raw `git push`).

---

## WO-A.6 — #5891 auth caches re-keyed by user_id with mode namespace

- **Branch:** `refactor/5891-cache-user-id` cut from the previous story's branch (`refactor/5890-team-user-id`).
- **Goal:** Auth cache keys use the canonical user_id and a namespace/version prefix. A namespace bump makes old keys unreachable. TTLs, backends, and eviction stay unchanged.
- **Read first:** `issue://5891` (the story contract). Then `mcpgateway/cache/auth_cache.py` — NOTE: the path is `cache/`, NOT `services/`. Read class `AuthCache`: `__init__` (where `self._cache_prefix` is set from settings), `_get_redis_key` (the single Redis key builder, with a doctest), `get_auth_context`/`set_auth_context` (context cache key `f"{email}:{jti or 'no-jti'}"`), `get_user`/`set_user`, `get_user_teams`/`set_user_teams` (key format `f"{identity}:True"`), and `set_not_revoked` (the 30-second negative-revocation window). Then `mcpgateway/auth.py` call sites (grep `auth_cache.`).
- **Context you may assume:** WO-A.1–A.5 landed. `get_user_id` exists; principals carry `user_id == email`. Redis persists across restarts, so a mode flip must never read stale cross-mode keys. The real mode flip cannot be tested until #5898/#5905; this story uses a synthetic version bump only.

### Steps
1. Cut the branch from `refactor/5890-team-user-id`.
2. Write failing tests first:
   - In `tests/unit/mcpgateway/cache/test_auth_cache_l1_l2.py`, add a class `TestCacheKeyNamespace`:
     - `test_redis_key_contains_version_segment`: `AuthCache()._get_redis_key("user", "test@example.com")` starts with `mcpgw:auth:v1:user:`. Before the change it is `mcpgw:auth:user:...`, so the test fails.
     - `test_version_bump_makes_old_keys_unreachable`: build two `AuthCache` instances that share one mocked Redis client (copy the `mock_redis` fixture pattern from this file). Force different versions on them (for example `cache_b._key_version = "v2"`). Call `set_auth_context` on the first, then `get_auth_context` on the second with the same identity and jti. Assert the second returns `None` (cold start).
   - In `tests/unit/mcpgateway/cache/test_auth_cache_user.py`, add `test_auth_context_key_uses_user_id_identity`: spy on the cache method; drive the auth path in `tests/unit/mcpgateway/test_auth.py` style with a principal whose explicit `user_id` is `"u-1"` and e-mail is `"e@x.test"`; assert the cache was keyed with `"u-1"`.
3. Run the fast gate (Tests below). Expect FAIL on all three new tests.
4. Implement:
   - `mcpgateway/cache/auth_cache.py`, in `AuthCache.__init__`: in the settings branch add `self._key_version = getattr(settings, "auth_cache_key_version", "v1")`; in the `ImportError` fallback branch add `self._key_version = "v1"`. Also add the setting itself: in `mcpgateway/config.py`, in the auth settings neighborhood, add `auth_cache_key_version: str = "v1"` with the description "Redis key version prefix for auth cache namespace isolation". Add `AUTH_CACHE_KEY_VERSION=v1` with a one-line comment to `.env.example`.
   - Change `_get_redis_key` to return `f"{self._cache_prefix}auth:{self._key_version}:{key_type}:{identifier}"`. Update its doctest expected output to `'mcpgw:auth:v1:user:test@example.com'`.
   - Do NOT touch any TTL (`_revocation_ttl` stays 30 by default), any backend choice, or any eviction logic.
   - `mcpgateway/auth.py`, at every `auth_cache.` call site inside `get_current_user` and helpers: compute the identity once with `user_id = get_user_id(payload.get("user") or {"email": email})` (import from `mcpgateway.auth_context`) and pass `user_id` — not the raw `email` variable — to `get_auth_context`, `set_auth_context`, `get_user`, and `set_user`. For team cache keys, use `f"{user_id}:True"`. The fallback dict keeps the value equal to the resolved e-mail in phase 1, so behavior is unchanged. Apply the same identity switch at the `set_user_teams(f"...")` call sites. The variable that holds the user payload differs at each call site. Read the surrounding code first; do not paste the expression blindly.
   - Docstrings: state in `get_auth_context`, `set_auth_context`, `get_user`, `set_user`, `set_user_teams` that the identifier is the canonical user_id and the key carries the version prefix.
5. Run the fast gate again. Expect PASS.
6. Run `make doctest`. Expect green — the updated `_get_redis_key` doctest output matches the new key shape.
7. Run `make ruff`. Expect green.
8. Run `make test` (checkpoint story). Expect green.

### Files
- `mcpgateway/cache/auth_cache.py` — modify (version in `_get_redis_key`; `_key_version` in `__init__`; docstrings).
- `mcpgateway/auth.py` — modify (cache call sites keyed by `get_user_id` identity).
- `tests/unit/mcpgateway/cache/test_auth_cache_l1_l2.py`, `tests/unit/mcpgateway/cache/test_auth_cache_user.py` — modify (new tests).

### Tests (exact commands)
- Fast gate: `uv run pytest tests/unit/mcpgateway/cache/test_auth_cache_l1_l2.py tests/unit/mcpgateway/cache/test_auth_cache_user.py -q` — expect FAIL at step 3, PASS at step 5.
- Checkpoint gate: `make doctest` — green. `make ruff` — green. `make test` — green.
- Namespace proof: the `test_version_bump_makes_old_keys_unreachable` test is the synthetic namespace-bump check; the real mode-flip test lives in #5905.

### Guardrails (do NOT)
- Do not change any cache TTL. The 30-second negative-revocation window stays as documented.
- Do not change cache backends or eviction policy.
- Do not write a real auth-mode flip test; the auth mode does not exist until #5898.
- Do not key the cache with a raw JWT `sub` when it is a UUID: always derive the identity through `get_user_id` with the e-mail fallback, so phase-1 keys keep today's value.
- Do not weaken or delete an existing test. If a pre-existing test fails, STOP and report.

### Done when
- The new cache-key unit tests are green.
- A test that populates the cache under one version and reads under a bumped version asserts the old keys are unreachable (cold start).
- `make test` is green.

### Commit
`git commit -s` with message: `refactor(auth): re-key auth caches by canonical user_id with mode namespace`

### PR
- Title: `refactor(auth): re-key auth caches by canonical user_id with mode namespace`
- Body (STE skeleton): "This PR re-keys the auth caches by canonical user_id. Redis keys gain a version segment through `_get_redis_key`, so a future auth-mode change cannot serve stale cross-mode context. The version comes from a setting with default `v1`; a synthetic bump test proves old keys turn cold. TTLs, backends, and eviction are unchanged. The negative-revocation 30-second window is untouched. Tested with <commands>, `make doctest`, and `make test`. Acceptance criteria of #5891 are met. Risk to existing users: one cold cache start after deploy; no other effect. The 30-second negative-revocation cache also cold-starts: revocation checks fall through to the DB/blocklist for the first request per identity after deploy. No security gap — the check still runs."
- Footer: `Closes #5891`
- Submit: `gh stack submit` (never raw `git push`).

---

## WO-A.7 — #5892 Additive user_id column migration on email_users + backfill

- **Branch:** `feat/5892-email-users-user-id-column` cut from `refactor/5891-cache-user-id` (the WO-A.6 / #5891 branch).
- **Goal:** Add a nullable `user_id` String(255) column to `email_users`, backfill it with the e-mail value, and index it (non-unique) — one idempotent Alembic migration.
- **Read first:** `issue://5892`; AGENTS.md section "Alembic Database Migrations"; `mcpgateway/alembic/versions/12d4a0c7789c_add_team_id_to_oauth_states.py` (inspector-guard pattern); `mcpgateway/alembic/versions/0a089912b5f0_add_numeric_id_to_email_users.py` (precedent for this table).
- **Context you may assume:** Stories #5886–#5891 landed code-only changes; `alembic heads` is unchanged by them. The scout recorded head `12d4a0c7789c` on 2026-09-09. Re-verify now; another migration may have landed since. The `EmailUser` model is `class EmailUser` in `mcpgateway/db.py`. A hermetic migration-test pattern exists in `tests/unit/mcpgateway/db/test_oauth_tokens_constraint_migration.py` (MigrationContext + Operations, in-memory SQLite, StaticPool).

### Steps
1. Record the current head BEFORE writing anything: `cd mcpgateway && alembic heads`. Confirm exactly ONE head. Note the revision id. If it is not `12d4a0c7789c`, the new migration's `down_revision` is the recorded head. Never assume, never guess.
2. Write the failing migration test FIRST. Create `tests/unit/mcpgateway/db/test_email_users_user_id_migration.py` modeled on `test_oauth_tokens_constraint_migration.py`:
   - Helper `_make_engine()`: in-memory SQLite, `StaticPool`, one shared connection.
   - Helper `_create_pre_migration_schema(conn)`: hand-create a minimal `email_users` table (columns `id`, `email`, `password_hash`); insert three rows with distinct e-mails.
   - Run the version module's `upgrade()`/`downgrade()` through `MigrationContext.configure(conn, opts={"as_sql": False})` and `with Operations.context(ctx):`, importing the module by name `mcpgateway.alembic.versions.<new_revision>_add_user_id_to_email_users`.
   - Assert: (a) column `user_id` exists after upgrade; (b) every row has `user_id == email` (backfill); (c) an index named `ix_email_users_user_id` exists on the column and `unique` is False; (d) after downgrade the column AND the index are gone; (e) running `upgrade()` a second time raises no error and changes no row; (f) `upgrade()` on a database where `email_users` does not exist is a no-op.
3. Run `uv run pytest tests/unit/mcpgateway/db/test_email_users_user_id_migration.py -q`. See it FAIL (ImportError: module not found). This is the TDD red step.
4. Generate the revision file: `cd mcpgateway && alembic revision -m "add_user_id_to_email_users"`. Set `down_revision` to the head recorded in step 1.
5. Write `upgrade()`: copy the guard style of `12d4a0c7789c`:
   - `bind = op.get_bind()`; `inspector = sa.inspect(bind)`.
   - Return early if `"email_users"` is not in `inspector.get_table_names()`.
   - Guard the add: if `"user_id"` is already in `inspector.get_columns("email_users")`, skip the add. Still run the backfill and the index steps below.
   - Add the column with `op.batch_alter_table("email_users")` → `batch_op.add_column(sa.Column("user_id", sa.String(255), nullable=True))`.
   - Backfill on both dialects: `bind.execute(text("UPDATE email_users SET user_id = email WHERE user_id IS NULL"))`. The `WHERE` clause makes re-runs safe.
   - Create a NON-unique index `ix_email_users_user_id` on `email_users.user_id`, guarded by a check of `inspector.get_indexes("email_users")`.
6. Write `downgrade()`: drop the index if it exists (inspector guard); drop the column if it exists (inspector guard, `batch_alter_table`).
7. Run the migration test. See it pass.
8. Add the column to the ORM. In `class EmailUser` (`mcpgateway/db.py`), beside `email`, add: `user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)`. Add one line to the class docstring `Attributes` list.
9. Scratch-database cycle (satisfies the acceptance criterion): from the repo root run
   `cd mcpgateway && DATABASE_URL=sqlite:////tmp/wo5892_scratch.db uv run alembic upgrade head && DATABASE_URL=sqlite:////tmp/wo5892_scratch.db uv run alembic downgrade -1 && DATABASE_URL=sqlite:////tmp/wo5892_scratch.db uv run alembic upgrade head && rm /tmp/wo5892_scratch.db`.
   All three alembic commands must exit 0.
10. Re-run `cd mcpgateway && alembic heads`. Exactly ONE head: the new revision.

### Files
- `mcpgateway/alembic/versions/<new_revision>_add_user_id_to_email_users.py` — create.
- `mcpgateway/db.py` — modify `class EmailUser` only.
- `tests/unit/mcpgateway/db/test_email_users_user_id_migration.py` — create.

### Tests (exact commands)
- `uv run pytest tests/unit/mcpgateway/db/test_email_users_user_id_migration.py -q` → pass.
- `uv run pytest tests/unit/mcpgateway/db -q` → pass (no sibling regression).
- Scratch cycle in step 9 → exit 0.
- Checkpoint gate (shared schema code): `make ruff` → pass; `make test` → pass.

### Guardrails (do NOT)
- Do not make `user_id` unique. Uniqueness is a deferred follow-up.
- Do not touch any foreign key.
- Do not guess `down_revision`. Use the head recorded in step 1.
- Do not modify any existing migration file.
- Do not change any writer. Writers land in #5893.
- Do not use `op.execute` without `text()`; keep the repo import style.

### Done when
- `cd mcpgateway && alembic heads` shows exactly one head.
- The upgrade/downgrade/upgrade cycle on the scratch SQLite DB exits 0.
- The migration test passes: column exists, backfill correct, index non-unique, downgrade clean, double-run idempotent, missing-table no-op.
- `make test` green.

### Commit
`git commit -s` with message: `feat(db): add nullable user_id column to email_users with email backfill`

### PR
- Title: `feat(db): add nullable user_id column to email_users with email backfill`
- Body: State what changed: one idempotent migration adds nullable `user_id` to `email_users`, backfills `user_id = email`, and adds a non-unique index; the `EmailUser` ORM model gains the column. State how tested: new migration unit test (column, backfill, index, downgrade, idempotency), scratch SQLite up/down/up cycle, `make test`. State acceptance met. State risk to existing users: none — the change is additive and nullable; existing rows receive `user_id = email`.
- Footer: `Closes #5892`
- Submit: `gh stack submit` (never raw `git push`).

## WO-A.8 — #5893 Population mechanisms + writer-side canonical-ID re-keying

- **Branch:** `feat/5893-populate-user-id-writers` cut from `feat/5892-email-users-user-id-column` (the WO-A.7 branch).
- **Goal:** Populate `user_id` at every user-creation path and re-key all five writer sites through one shared resolver so diverged users never lose rows.
- **Read first:** `issue://5893`; then the files named in Steps — locate every site by SYMBOL NAME. Verify the enumeration first (step 1).
- **Context you may assume:** #5892 landed the `user_id` column (backfilled = email). #5886 landed `get_user_id` in `mcpgateway/auth_context.py`. The writer enumeration is code-verified and EXACT: ONE `UserRole(` site — `role_service.assign_role_to_user`; FOUR `EmailTeamMember(` sites — `team_management_service._upsert_membership` (it serves `add_member_to_team`; SSO `_apply_team_mapping` routes through it), `team_management_service.approve_join_request`, `personal_team_service.create_personal_team`, `team_invitation_service.accept_invitation`. Issue line numbers drifted; the symbols above are current. `email_auth_service.create_user` constructs the `EmailUser(...)` row for local registration, SSO provisioning, and bootstrap (via `create_platform_admin`).

### Steps
1. Verify the enumeration before editing: `grep -n "UserRole(" mcpgateway/services/*.py` → exactly one hit (role_service). `grep -n "EmailTeamMember(" mcpgateway/services/*.py` → exactly four hits (two in team_management_service, one in personal_team_service, one in team_invitation_service). If the count differs, STOP and report.
2. Add the shared resolver. In `mcpgateway/auth_context.py`, directly beside `get_user_id`, add `resolve_canonical_user_id(email: str, db: Session) -> str`: query `EmailUser` by `email` (strip and lower the input, the same rule `create_user` uses); return `user.user_id` when it is a non-empty string; return the input e-mail otherwise. Import `EmailUser` and `Session` at module top — `mcpgateway/db.py` does not import `auth_context`, so no cycle forms. Document the function with a short docstring; mark any doctest example `# doctest: +SKIP`.
3. Write the failing provisioning tests (extend the existing files):
   - `tests/unit/mcpgateway/services/test_email_auth_service.py`: `create_user` stores `user_id == email` by default; an explicit `user_id="idp-123"` is stored verbatim.
   - `tests/unit/mcpgateway/services/test_sso_user_normalization.py`: a provider whose `provider_metadata` sets `user_id_claim` extracts `provider_id` from that claim; default is `sub`; a configured claim missing from the token marks the login failed; an invalid setting (empty or non-string) is rejected by the provider save path with a clear error.
   - `tests/unit/mcpgateway/services/test_sso_service.py`: `authenticate_or_create_user` with `sub="idp-123"`, `email="a@b.c"` creates a user with `user_id="idp-123"` (diverged case).
   - `tests/unit/mcpgateway/services/test_email_auth_service.py`: `create_platform_admin` yields `user_id == settings.platform_admin_email`.
   Run each; see it fail.
4. Implement provisioning:
   - `email_auth_service.create_user`: add keyword param `user_id: Optional[str] = None`. Pass `user_id=(user_id or email)` into the `EmailUser(...)` construction. Local registration omits the param, so the default is the e-mail.
   - `create_platform_admin`: no code change for the value (its `create_user` call defaults to the e-mail, which equals `platform_admin_email`); the step-3 test proves it.
   - `sso_service.authenticate_or_create_user`, new-user branch: pass `user_id=str(user_info.get("provider_id") or email)` to `create_user`. The existing-user branch must NOT rewrite `user.user_id`.
   - Per-provider claim setting: in `_normalize_user_info`, refactor the provider branches to assign one `normalized` dict and exit in ONE place (keep each branch's mapping unchanged). Then: `user_id_claim = str((provider.provider_metadata or {}).get("user_id_claim") or "sub")`. If `user_id_claim != "sub"`: when the claim key is absent from `user_data`, log an actionable error naming the provider and the claim and set `normalized["user_id_claim_missing"] = user_id_claim`; otherwise set `normalized["provider_id"] = user_data.get(user_id_claim)`. At the top of `authenticate_or_create_user`, if `user_info.get("user_id_claim_missing")` is set, log and return `None` (fail closed, never fall back to e-mail).
   - Validate the setting at save time: in the provider create/update path of `mcpgateway/services/sso_service.py` (around the `SSOProvider(**filtered_data)` construction), reject `user_id_claim` values that are empty, whitespace, or non-string; raise `ValueError` naming the provider and the setting.
5. Write the failing writer tests. Create the diverged user THROUGH the writer path in every test: `await auth_service.create_user(email="dev@example.com", password=..., user_id="idp-123")`. Hand-written `EmailUser`/`UserRole`/`EmailTeamMember` fixture rows are FORBIDDEN (they mask writer bugs). Extend the existing per-service files and assert the stored row's `user_email` column equals `"idp-123"`:
   - `tests/unit/mcpgateway/services/test_role_service.py`: `assign_role_to_user` stores the role under `idp-123`; a second call dedupes against the canonical-keyed row.
   - `tests/unit/mcpgateway/services/test_team_management_service.py`: `add_member_to_team` and `approve_join_request` store membership under `idp-123`; re-adding the member reactivates the SAME row (no duplicate).
   - `tests/unit/mcpgateway/services/test_personal_team_service.py`: `create_personal_team` stores the owner membership under `idp-123`.
   - `tests/unit/mcpgateway/services/test_team_invitation_service.py`: `accept_invitation` stores membership under `idp-123`.
   - One SSO end-to-end case in `test_sso_service.py`: provisioning with role sync AND team mapping writes both row types under the SSO subject.
   Run each; see it fail.
6. Implement the writer re-keying. In each of the five sites, resolve ONCE at the top: `canonical = resolve_canonical_user_id(<email>, self.db)`. Use `canonical` for BOTH the existing-row lookup AND the constructed row's `user_email` field (a lookup keyed on the raw e-mail would miss diverged rows and create duplicates — this is the bug class the story prevents). Column names stay unchanged (decision D1):
   - `role_service.assign_role_to_user`: use `canonical` for the existing-assignment lookup(s), the `UserRole(...)` construction, and the conflict-refetch path.
   - `team_management_service._upsert_membership` and its caller `add_member_to_team`: use `canonical` for the membership lookup and the `EmailTeamMember(...)` construction.
   - `team_management_service.approve_join_request`: resolve `join_request.user_email`; use `canonical` in the `EmailTeamMember(...)` construction.
   - `personal_team_service.create_personal_team`: resolve `user.email`; use `canonical` in the `EmailTeamMember(...)` construction.
   - `team_invitation_service.accept_invitation`: resolve `invitation.email`; use `canonical` for the existing-membership lookup and the `EmailTeamMember(...)` construction.
   Callers (bootstrap_db, admin UI, SSO sync) keep passing the e-mail; they inherit the boundary.
7. Add the grep-audit test: `tests/unit/mcpgateway/test_writer_resolver_audit.py`. Walk `mcpgateway/services/*.py` with the `ast` module. For every `ast.Call` that constructs `UserRole` or `EmailTeamMember`, assert the enclosing function's source contains `resolve_canonical_user_id`. Keep an empty allow-list; the audit must pass with zero exceptions.
8. Run the full story selection (the issue's acceptance command): `uv run pytest tests -k "sso or provisioning or create_user or assign_role or invitation or personal_team" -q` → green including every diverged-ID case.
9. Checkpoint gate (shared services code): `make ruff` → pass; `make test` → pass.

### Files
- `mcpgateway/auth_context.py` — add `resolve_canonical_user_id`.
- `mcpgateway/services/email_auth_service.py` — `create_user` param + value.
- `mcpgateway/services/sso_service.py` — provisioning, claim setting, save validation.
- `mcpgateway/services/role_service.py`, `mcpgateway/services/team_management_service.py`, `mcpgateway/services/personal_team_service.py`, `mcpgateway/services/team_invitation_service.py` — re-key the five sites.
- `tests/unit/mcpgateway/services/test_email_auth_service.py`, `test_sso_service.py`, `test_sso_user_normalization.py`, `test_role_service.py`, `test_team_management_service.py`, `test_personal_team_service.py`, `test_team_invitation_service.py` — extend.
- `tests/unit/mcpgateway/test_writer_resolver_audit.py` — create.

### Tests (exact commands)
- `uv run pytest tests/unit/mcpgateway/test_writer_resolver_audit.py -q` → pass.
- `uv run pytest tests -k "sso or provisioning or create_user or assign_role or invitation or personal_team" -q` → pass.
- `uv run pytest tests/unit/mcpgateway/services -q` → pass.
- Checkpoint gate: `make ruff` → pass; `make test` → pass.

### Guardrails (do NOT)
- Do not re-implement the resolution per call site. Every site calls `resolve_canonical_user_id`. One resolver, five call sites.
- Do not change SSO role/team sync semantics: the same roles and teams are granted; only the stored key changes.
- Do not rewrite existing rows beyond #5892's backfill.
- Do not add a uniqueness constraint on `user_id`.
- Do not change `granted_by` or `invited_by` values; they stay attribution e-mails.
- Do not rename the `user_email` columns (D1: semantic re-keying, no FK re-pointing).
- Do not create diverged users in tests with hand-written DB rows; use the writer paths.

### Done when
- The story selection is green including all diverged-ID cases.
- The new claim setting is validated at save; a missing claim fails the login closed with an actionable log.
- The audit test confirms every `UserRole`/`EmailTeamMember` construction site calls the shared resolver.
- `make test` green.

### Commit
`git commit -s` with message: `feat(auth): populate user_id from SSO subject and provisioning defaults`. Add a commit body listing the extra scope: `git commit -s -m '<subject>' -m 'Re-key the UserRole and EmailTeamMember writer sites through resolve_canonical_user_id.'`

### PR
- Title: `feat(auth): populate user_id from SSO subject and provisioning defaults`
- Body: State what changed: SSO provisioning stores the IdP subject as `user_id` (per-provider claim setting, default `sub`); local registration and bootstrap default `user_id` to the e-mail; all five verified writer sites store the canonical `user_id` through one shared resolver. State how tested: per-site diverged-ID tests through real writer paths, an AST audit test, the issue's selection, `make test`. State acceptance met. State risk to existing users: for e-mail-equal IDs (all pre-existing rows) the stored values are byte-identical.
- Footer: `Closes #5893`
- Submit: `gh stack submit` (never raw `git push`).

## WO-A.9 — #5894 Diverged-ID separation suite + rolling-deploy matrix part 1

- **Branch:** `test/5894-diverged-identity-separation-suite` cut from `feat/5893-populate-user-id-writers` (the WO-A.8 branch).
- **Goal:** Prove RBAC, team resolution, audit, and cache all key on the canonical `user_id` when `user_id != email`, across three token formats, plus one fail-closed row.
- **Read first:** `issue://5894`; `tests/helpers/auth.py` (READ it first — #5887 extended it; do not assume its current shape); `docs/docs/architecture/identity-domains.md` (the #5886 mapping contract); `tests/conftest.py` test-secret block.
- **Context you may assume:** #5886–#5893 landed: `get_user_id` (auth_context), user_id-carrying principals (#5887), audit/observability identity semantics (#5888), permission path on `user_id` (#5889: `check_permission`, `get_user_permissions` in permission_service; `require_permission`, `get_current_user_with_permissions` in middleware/rbac), team resolution on `user_id` (#5890: `resolve_session_teams` in auth.py), cache keys on `user_id` (#5891: builders in `mcpgateway/cache/auth_cache.py`, plus `get_auth_context` and `set_user_teams` in auth.py), the `user_id` column (#5892), and population/writers (#5893). The token→identity mapping seam today: `get_jwt_user_email_from_payload` and `resolve_jwt_user_email_from_payload` (auth_context), and `get_user_email_from_token` (auth.py), which resolves UUID subjects through the DB. The issue's line reference for the UUID seam drifted; these symbols are current.

### Steps
1. Read `tests/helpers/auth.py` end to end. List which helper builds each token shape. The matrix needs three shapes: UUID-sub session token (`sub` = the user's UUID `id`, `token_use="session"`), e-mail-sub API token, legacy token with no `token_use`. Extend the helpers ONLY if a shape is missing; keep every existing helper signature working.
2. Create the fixture factory in the new test module: one session-scoped fixture creates a diverged user THROUGH the writer path — `await auth_service.create_user(email="dev@example.com", password=<conftest user password>, user_id="idp-123")` — then grants a role via `role_service.assign_role_to_user` and a team membership via `add_member_to_team` (or the SSO sync path). Hand-written identity rows are FORBIDDEN.
3. Create `tests/unit/mcpgateway/test_identity_separation.py` (convention-neighbor of `test_auth_context.py`; there is no `tests/unit/mcpgateway/auth/` directory and the unit tree mirrors source).
4. Build the matrix: parametrize the three token formats. For each format, resolve the principal through the mapping seam, then assert the SAME principal `user_id == "idp-123"` in all four columns:
   - RBAC: the permission path returns the diverged user's permissions (exercise `get_user_permissions` with the principal; assert the granted role's permission appears).
   - Teams: `resolve_session_teams` returns the diverged user's DB team.
   - Audit: verify the identity attribute name first — `grep -n "user.id" mcpgateway/observability.py` — use the name #5888 landed; assert the recorded identity equals `idp-123` and the e-mail attribute stays `dev@example.com`.
   - Cache: verify the builder names first — `grep -n "def " mcpgateway/cache/auth_cache.py` — then assert the keys built for this principal contain `idp-123` and not the e-mail (exercise the #5891 builders, `get_auth_context`, `set_user_teams`).
5. Add the fail-closed row: a trust-style token with an opaque `sub` (not an e-mail, not a known UUID — for example `entraopaque987`). Assert the identity resolution REJECTS it: no user resolves, and the flow never maps it onto another user. This is the pre-Epic-2 state: opaque subjects are rejected, not trusted.
6. If any matrix cell fails, fix the wiring bug in the same commit. A failing cell is a bug, not a test to weaken.
7. Checkpoint gate (#5894 is a full-suite checkpoint): `make test`, `make doctest`, `make ruff`.

### Files
- `tests/unit/mcpgateway/test_identity_separation.py` — create (matrix + fixture factory + fail-closed row).
- `tests/helpers/auth.py` — extend ONLY if a token shape is missing.
- Production files — touch ONLY if a wiring bug is found and fixed.

### Tests (exact commands)
- `uv run pytest tests/unit/mcpgateway/test_identity_separation.py -q` → pass (3 rows × 4 columns + fail-closed row).
- Checkpoint gate: `make test` → pass; `make doctest` → pass; `make ruff` → pass.

### Guardrails (do NOT)
- Do not change default-mode behavior to make a test pass. A failing cell means a wiring bug; fix the bug.
- Do not create the diverged fixture with hand-written DB rows.
- Do not weaken or delete an existing test.
- Do not add trust-mode acceptance: this suite proves opaque subjects are REJECTED before Epic 2.

### Done when
- The 3×4 matrix is green: UUID-sub session, e-mail-sub API, legacy no-`token_use` — each yields principal `user_id == "idp-123"` across RBAC, teams, audit, cache.
- The fail-closed row is green: the opaque-sub token is rejected, never silently mapped.
- `make test` and `make doctest` green.

### Commit
`git commit -s` with message: `test(auth): add diverged-identity separation suite and token-format matrix`

### PR
- Title: `test(auth): add diverged-identity separation suite and token-format matrix`
- Body: State what changed: a new suite proving RBAC, teams, audit, and cache key on the canonical `user_id` for a diverged user, across three token formats, plus a fail-closed row for opaque subjects. State how tested: the suite itself, `make test`, `make doctest`. State acceptance met. State risk to existing users: none — tests only; list any production wiring fix forced by a cell.
- Footer: `Closes #5894`
- Submit: `gh stack submit` (never raw `git push`).

## WO-A.10 — #5895 Epic 1 gate + identity documentation sweep

- **Branch:** `docs/5895-epic1-gate-identity-docs` cut from `test/5894-diverged-identity-separation-suite` (the WO-A.9 branch).
- **Goal:** Run the full Epic 1 gate, capture evidence, and update the identity documentation to the canonical `user_id` model.
- **Read first:** `issue://5895`; AGENTS.md sections "User Identity Extraction" and "Alembic Database Migrations"; `docs/docs/manage/rbac.md`; `docs/docs/architecture/multitenancy.md`; `docs/docs/architecture/identity-domains.md` (the #5886 contract).
- **Context you may assume:** All Stack A stories #5886–#5894 landed on this branch's history. Makefile targets verified to exist: `test`, `doctest`, `ruff`, `interrogate`, `pylint`, `coverage`, `diff-cover`. The #5892 migration is the only migration this epic added.

### Steps
1. Re-read `issue://5895`. This story changes docs and records evidence; it adds no product code.
2. Run the gate in order. Capture each command's exit code and tail output into `gate-evidence/` scratch notes (do not commit scratch files; the PR body carries the summary):
   - `cd mcpgateway && alembic heads` → exactly ONE head, and it is the revision created by #5892 (verify: `ls mcpgateway/alembic/versions/ | grep <that revision>`).
   - `make test` → exit 0.
   - `make doctest` → exit 0.
   - `make ruff interrogate pylint` → exit 0.
   - `make coverage diff-cover` → exit 0.
   If ANY item is red: STOP. Fix forward. Re-run the FULL gate from the top. No partial pass, no waived item without a written note.
3. Write the behavior-identity note. Run `git diff main...HEAD --stat -- tests/`. Classify every test file as ADDED or MODIFIED. Target: zero modified pre-existing files. Each modified file gets one justification line in the PR body and in the commit body.
4. Docs sweep:
   - AGENTS.md "User Identity Extraction": replace the e-mail-over-sub precedence statement with the canonical contract: `get_user_id` returns the identity; e-mail is a mutable attribute; `get_user_email` remains the e-mail accessor. Link `docs/docs/architecture/identity-domains.md` as the mapping contract.
   - `docs/docs/manage/rbac.md`: state that permissions and role assignments key on the canonical `user_id`.
   - `docs/docs/architecture/multitenancy.md`: state that team membership keys on the canonical `user_id`.
   - Sweep for stale claims: `grep -rn "email IS the ID" --include="*.md" .` and `grep -rn "email-over-sub" --include="*.md" .` — fix every hit that states the old model (code comments in `auth_middleware.py` are out of scope here; docs only).
5. Commit docs + evidence summary. The commit body lists the gate results and the behavior-identity note.

### Files
- `AGENTS.md` — modify the "User Identity Extraction" section.
- `docs/docs/manage/rbac.md` — modify identity references.
- `docs/docs/architecture/multitenancy.md` — modify identity references.

### Tests (exact commands)
- The gate IS the test list (step 2). All five commands exit 0.
- No new unit tests in this story.

### Guardrails (do NOT)
- Do not proceed to Epic 2 with any gate item red or waived without a note.
- Do not modify a test to make the gate green.
- Do not delete a failing test.
- Do not change product code in this story; a red gate means fix forward in the owning story's commit, then re-run the gate.

### Done when
- Every gate command exits 0 with output captured.
- `alembic heads` shows one head: the #5892 revision.
- The three docs state the canonical `user_id` model and reference the identity-domains contract.
- The behavior-identity note lists every modified pre-existing test (target: zero) with a justification each.
- The PR body carries the gate evidence summary.

### Commit
`git commit -s` with message: `docs(auth): document canonical user_id identity model and Epic 1 gate evidence`

### PR
- Title: `docs(auth): document canonical user_id identity model and Epic 1 gate evidence`
- Body: State what changed: AGENTS.md, rbac.md, and multitenancy.md now document the canonical `user_id` identity model and reference the identity-domains contract. State the gate evidence: each command with its exit code. State the behavior-identity note: modified pre-existing tests listed with justification (target zero). State risk to existing users: none — documentation and evidence only.
- Footer: `Closes #5895`
- Submit: `gh stack submit` (never raw `git push`).

---

# Stack B — Work Orders (Epic 2, #5885)

Fourteen self-contained orders. Stack B starts after Stack A merges. Orders run in sequence B.1 through B.14; each branch cuts from the previous order branch.
---

## WO-B.1 — #5896 Token dispatch rule doc + deny matrix

- **Branch:** `docs/5896-token-dispatch-rule` cut from `main` (after Stack A merges).
- **Goal:** Pin the trust-eligibility dispatch rule in architecture docs and land the executable deny-test matrix.
- **Read first:** `issue://5896` (the story contract), then the files named in Steps — locate code by SYMBOL NAME (grep), never by line number.
- **Context you may assume:** Stack A merged. No trust-mode code exists yet. The word "trusted" appears in the codebase (e.g. `trusted_for_api_auth`, `is_trusted_internal_mcp_request`), but the `token_use` claim carries only `"session"` or `"api"` — no `"trusted"` marker value exists anywhere in `mcpgateway/`. Session tokens carry no `teams` or `is_admin` claims (`create_access_token` in `mcpgateway/routers/email_auth.py`). API tokens embed `user_data.is_admin` and `teams` (`_generate_token` in `mcpgateway/services/token_catalog_service.py`).

### Steps
1. Create `docs/docs/architecture/auth-token-dispatch.md` with the following content:
   - **Eligibility rule (disjunctive):** A token is trust-eligible when trust mode is ON AND one of:
     - (a) Gateway-signed: `token_use == "trusted"` AND the required mapped claim set (sub, teams, roles per #5899) AND a configured revocation claim (default `jti`).
     - (b) External IdP: issuer is a configured trust root (`trusted_for_api_auth` + `api_audience` per `SSOProvider` in `mcpgateway/db.py`) AND the required mapped claims AND a configured revocation claim.
   - **Tokens carrying `token_use == "trusted"` get HTTP 401 when trust mode is OFF.** They never enter the default funnel — the default funnel's UUID heuristic (`resolve_uuid_subject` in `mcpgateway/auth.py`) could silently re-attribute a UUID-shaped sub to a different local user, and `normalize_token_teams` (in `mcpgateway/auth_context.py`) would honor embedded teams under default semantics.
   - **All other tokens** route through the default funnel even with trust mode enabled.
   - **Six mode-x-token combinations table:**
     | Mode | Token type | Expected result |
     |------|-----------|-----------------|
     | Default | Session token | Default-semantics (server-side team resolution) |
     | Default | API token | Default-semantics (embedded teams honored) |
     | Trust | Default session token | Default-semantics (not trust-eligible; no `token_use=="trusted"` marker, issuer not a trust root) |
     | Trust | Default API token | Default-semantics (same reason) |
     | Trust | Gateway-signed trust token (`token_use=="trusted"`) | Trust-semantics (post-#5900); 401 before #5900 lands |
     | Trust | External IdP token (trusted issuer) | Trust-semantics via issuer branch (post-#5900); provisioning behavior pre-#5900 |
   - State the operative fact: "No `token_use` value other than `session` or `api` exists in `mcpgateway/` today. The `trusted` marker is introduced by #5904."

2. Create the deny-test matrix at `tests/unit/mcpgateway/test_token_dispatch_matrix.py` (flat layout matches existing `test_auth*.py` convention).
   - Rows whose expectation holds today land green immediately:
     - External-IdP token in default mode → default provisioning behavior (current code path through `verify_external_idp_token` in `mcpgateway/utils/verify_credentials.py`).
     - Session token in trust mode → default funnel (not trust-eligible).
     - API token in trust mode → default funnel (not trust-eligible).
   - Rows requiring un-landed behavior use `pytest.mark.xfail(strict=True, reason=...)`:
     - Gateway-signed trust token (`token_use=="trusted"`) in trust mode → trust-semantics. `reason="Flipped by #5900"`, pointer comment `# Flipped by #5900 (trust branch in get_current_user)`.
     - Gateway-signed trust token in default mode → 401. Same reason and pointer as above.
     - External IdP token (trusted issuer) in trust mode → trust-semantics. `reason="Flipped by #5903"`, pointer comment `# Flipped by #5903 (external IdP trust root)`.
   - Use `strict=True` so that any row that XPASSes before its flip story lands causes a suite failure.

3. Run the test file and confirm: expect-pass rows pass; xfail rows show as `xfail` (not `XPASS`).

### Files
- `docs/docs/architecture/auth-token-dispatch.md` — create
- `tests/unit/mcpgateway/test_token_dispatch_matrix.py` — create

### Tests (exact commands)
- Fast gate: `uv run pytest tests/unit/mcpgateway/test_token_dispatch_matrix.py -q`
- Expected: all rows green (pass or xfail, zero failures, zero XPASS).
- Checkpoint gate (this story also runs): `make ruff` — must pass clean.

### Guardrails (do NOT)
- Do not implement the funnel branch — artifact and tests only.
- Do not claim "zero occurrences of the word trusted in mcpgateway/" — that is false (the word appears in `trusted_for_api_auth`, `is_trusted_internal_mcp_request`, etc.). State only the operative fact about `token_use` values.
- Do not blanket-xfail expect-pass rows — `strict=True` would red the suite on XPASS.

### Done when
- [ ] `docs/docs/architecture/auth-token-dispatch.md` exists with the dispatch rule and all six combinations.
- [ ] `tests/unit/mcpgateway/test_token_dispatch_matrix.py` exists and exits green.
- [ ] `make ruff` passes.

### Commit
`git commit -s` with message: `docs(auth): define trust-mode token dispatch rule and cross-mode deny matrix`

### PR
- Title: `docs(auth): define trust-mode token dispatch rule and cross-mode deny matrix`
- Body: Architecture doc pins the disjunctive trust-eligibility rule (gateway-signed marker OR external-IdP trusted issuer). Deny-test matrix covers all six mode-x-token combinations. Expect-pass rows (current behavior) land green. Un-landed rows are strict-xfail with pointers to #5900. No behavior change. Tested with `uv run pytest tests/unit/mcpgateway/test_token_dispatch_matrix.py -q` and `make ruff`. Acceptance criteria of #5896 are met. Risk to existing users: none (doc + tests only).
- Footer: `Closes #5896`
- Submit: `gh stack submit` (never raw `git push`).

---

## WO-B.2 — #5897 Feature-by-mode matrix doc

- **Branch:** `docs/5897-feature-mode-matrix` cut from B.1's branch.
- **Goal:** Document every user-dependent feature's behavior under default mode and trust mode.
- **Read first:** `issue://5897` (the story contract), then the files named in Steps — locate code by SYMBOL NAME (grep), never by line number.
- **Context you may assume:** WO-B.1 landed (dispatch rule doc exists).

### Steps
1. Create `docs/docs/architecture/auth-feature-mode-matrix.md` with a table covering nine surfaces. Each entry states one of: **works**, **disabled-with-clear-error** (HTTP status + message), **degraded**, or **N/A**. Every entry carries a `file:symbol` citation. Use these current locations:

   | Surface | Default mode | Trust mode | Citation |
   |---------|-------------|------------|----------|
   | Password login/register/reset | Works | Disabled (401, "Password authentication disabled in trust mode") | `mcpgateway/routers/email_auth.py` — login handler, register handler, reset-password handler |
   | Invitations | Works | Disabled (403, "Invitations require local user records") | `mcpgateway/services/team_invitation_service.py` — inviter/owner checks |
   | Team membership writes | Works (raises `UserNotFoundError` when user absent) | Disabled (403, "Team membership writes require local user records") | `mcpgateway/services/team_management_service.py` — `add_member_to_team` |
   | SSO browser login | Works (provisions user + issues session token) | Disabled (401, "SSO browser login disabled in trust mode") | `mcpgateway/services/sso_service.py` — `authenticate_or_create_user` |
   | Personal-team auto-creation | Works | N/A (trust mode has no local user to create teams for) | `mcpgateway/services/email_auth_service.py` — `auto_create_personal_teams` |
   | Import ownership | Works (queries `EmailUser` for personal-team lookup) | Degraded (import ownership requires local user record) | `mcpgateway/services/import_service.py` — `_get_user_context`, `_add_multitenancy_context` |
   | Admin UI user CRUD | Works | Disabled (403, "User management disabled in trust mode") | `mcpgateway/admin.py` — admin user CRUD handlers; `mcpgateway/routers/email_auth.py` — API CRUD endpoints |
   | API-token catalog | Works (requires `EmailUser` row) | DB-backed principals: works. Trust-only principals: disabled with explicit error ("Token minting is disabled for trust-only principals. Create a local user account first.") | `mcpgateway/services/token_catalog_service.py` — `create_token` |
   | Session-token refresh | Works (`POST /auth/refresh`, session-only guard) | Disabled (401, "Session refresh disabled in trust mode") | `mcpgateway/routers/auth.py` — refresh handler |

2. Add a self-check list at the bottom: every surface must have a decision; any "undefined" entry blocks #5906.

3. Verify every `file:symbol` citation resolves to a real symbol (grep each one).
4. These decisions are binding for WO-B.12 (choke-point implementation) and WO-B.14 (matrix error-path tests); any change to a cell requires editing all three work orders.

### Files
- `docs/docs/architecture/auth-feature-mode-matrix.md` — create

### Tests (exact commands)
- Fast gate: `uv run pytest tests/unit/mcpgateway/test_token_dispatch_matrix.py -q` (re-run B.1's matrix to confirm no regression).
- Expected: green.
- Checkpoint gate (this story also runs): `make ruff` — must pass clean.

### Guardrails (do NOT)
- Do not implement behavior changes — artifact only.
- Do not leave any surface as "undefined" — every cell must have a decision.
- Do not use stale line numbers from the issue — navigate by symbol name only.

### Done when
- [ ] `docs/docs/architecture/auth-feature-mode-matrix.md` exists with all nine surfaces and a decision each.
- [ ] Every entry has a `file:symbol` citation that resolves to real code.
- [ ] Self-check list present at the bottom.

### Commit
`git commit -s` with message: `docs(auth): define feature-by-mode behavior matrix`

### PR
- Title: `docs(auth): define feature-by-mode behavior matrix`
- Body: Documents nine user-dependent features under default mode and trust mode. Each entry states works/disabled/degraded/N-A with file:symbol citations. Self-check list ensures no surface is left undefined. No behavior change. Tested with `uv run pytest tests/unit/mcpgateway/test_token_dispatch_matrix.py -q` (re-run) and `make ruff`. Acceptance criteria of #5897 are met. Risk to existing users: none.
- Footer: `Closes #5897`
- Submit: `gh stack submit` (never raw `git push`).

---

## WO-B.3 — #5898 Config surface (trust mode + claim mapping + overage policy + revocation claim)

- **Branch:** `feat/5898-jwt-trust-config` cut from B.2's branch.
- **Goal:** Add all trust-mode settings to `mcpgateway/config.py` with startup validators.
- **Read first:** `issue://5898` (the story contract), then the files named in Steps — locate code by SYMBOL NAME (grep), never by line number.
- **Context you may assume:** WO-B.1 and WO-B.2 landed (docs exist). `Literal` precedent at `mcpgateway/config.py` — `identity_propagation_mode` field. Auth settings neighborhood: session lifecycle block near `session_max_lifetime`, `require_jti` (default `True`), `require_user_in_db`. SSO settings block near `sso_entra_*`.

### Steps
1. **Write failing config tests first.** Create `tests/unit/mcpgateway/test_jwt_trust_config.py`:
   - Test: default values — `jwt_trust_mode == "db"`, all claim mappings at defaults, overage policy `"fail_closed"`.
   - Test: trust mode `"jwt-trust"` with valid config boots cleanly.
   - Test: empty `jwt_claim_user_id` (empty string) rejected at startup with actionable error.
   - Test: unknown claim name (e.g. `jwt_claim_user_id = ""`) rejected with message naming the setting.
   - Test: trust mode enabled without revocation claim enforcement → rejected at startup.
   - Run: `uv run pytest tests/unit/mcpgateway/test_jwt_trust_config.py -q` — confirm all tests FAIL (red).

2. **Add settings to `mcpgateway/config.py`** in the auth-settings neighborhood (after `require_user_in_db`, near the session lifecycle block). Follow the `Literal` pattern from `identity_propagation_mode`:
   - `jwt_trust_mode: Literal["db", "jwt-trust"] = "db"` — trust mode toggle.
   - `jwt_claim_user_id: str = "sub"` — claim name for user identifier.
   - `jwt_claim_email: str = "email"` — claim name for email.
   - `jwt_claim_teams: str = "teams"` — claim name for team memberships.
   - `jwt_claim_roles: str = "roles"` — claim name for role names.
   - `jwt_claim_admin: str = "is_admin"` — claim name for admin flag.
   - `jwt_trust_overage_policy: Literal["fail_closed", "graph_lookup", "proceed_without_groups"] = "fail_closed"` — overage handling.
   - `jwt_trust_revocation_claim: str = "jti"` — per-trust-root revocation identifier claim (default `"jti"`; `"uti"` for Entra roots).

3. **Add field validators** (Pydantic `@model_validator` or `@field_validator`):
   - Trust mode `"jwt-trust"` requires `jwt_trust_revocation_claim` to be non-empty.
   - All `jwt_claim_*` settings reject empty strings with: `"Setting {name} must not be empty when jwt_trust_mode is enabled."`.
   - A trust-eligible token without the configured revocation claim is rejected 401 (document this contract; enforcement lands in #5900).

4. **Update `.env.example`** — add every new variable with a comment explaining its purpose and default.

5. **Update `docs/docs/manage/configuration.md`** — add a "JWT Trust Mode" section documenting each setting, its default, and the validation rules.

6. Run tests again: `uv run pytest tests/unit/mcpgateway/test_jwt_trust_config.py -q` — confirm all tests PASS (green).

### Files
- `mcpgateway/config.py` — modify (add settings + validators)
- `tests/unit/mcpgateway/test_jwt_trust_config.py` — create
- `.env.example` — modify (add new variables)
- `docs/docs/manage/configuration.md` — modify (add JWT Trust Mode section)

### Tests (exact commands)
- Fast gate: `uv run pytest tests/unit/mcpgateway/test_jwt_trust_config.py -q`
- Expected: all tests green.
- Broader gate: `uv run pytest tests/unit/mcpgateway/ -k "config or settings" -q` — must remain green (no regressions).
- Checkpoint gate (this story also runs): `make ruff` and `make test` — config validators can break startup globally; the full suite must prove they do not.

### Guardrails (do NOT)
- Do not change any existing setting's default.
- Do not wire the new settings into the auth funnel (that is #5900).
- Do not change `require_jti` or any other existing setting.
- Do not skip the TDD cycle — failing tests must exist before implementation.

### Done when
- [ ] All new settings exist in `mcpgateway/config.py` with correct types and defaults.
- [ ] Validators reject empty claim names and trust mode without revocation claim at startup.
- [ ] `.env.example` documents every new variable.
- [ ] `docs/docs/manage/configuration.md` has a JWT Trust Mode section.
- [ ] `uv run pytest tests/unit/mcpgateway/test_jwt_trust_config.py -q` green.
- [ ] `make ruff` passes.

### Commit
`git commit -s` with message: `feat(config): add JWT-trust mode and claim-mapping settings`

### PR
- Title: `feat(config): add JWT-trust mode and claim-mapping settings`
- Body: Adds trust-mode toggle, claim-mapping settings, overage policy, and per-trust-root revocation claim to config. Startup validators reject empty claim names and trust mode without revocation enforcement. TDD: failing tests written first. No funnel wiring. Tested with `uv run pytest tests/unit/mcpgateway/test_jwt_trust_config.py -q`, the broader config selection, `make ruff`, and `make test`. Acceptance criteria of #5898 are met. Risk to existing users: none (all defaults preserve current behavior; trust mode defaults to "db").
- Footer: `Closes #5898`
- Submit: `gh stack submit` (never raw `git push`).

---

## WO-B.4 — #5976 External group mappings table + resolver + admin CRUD

- **Branch:** `feat/5976-external-group-mappings` cut from B.3's branch.
- **Goal:** Add the `external_group_mappings` table, the `resolve_external_groups_to_teams` resolver, and RBAC-scoped admin CRUD.
- **Read first:** `issue://5976` (the story contract), then the files named in Steps — locate code by SYMBOL NAME (grep), never by line number.
- **Context you may assume:** WO-B.1 through WO-B.3 landed. Config settings from WO-B.3 exist. Alembic head: re-verify with `cd mcpgateway && alembic heads` before writing the migration (scout reports `12d4a0c7789c` as current head; confirm at execution time). Existing migration pattern: idempotent inspector-guard (see `12d4a0c7789c_add_team_id_to_oauth_states.py`). Existing 404-not-403 convention: `_check_agent_access` in `mcpgateway/services/a2a_service.py`. Agent visibility values: `public`, `team`, `private` (`A2AAgent.visibility` in `mcpgateway/db.py`).

### Steps
0. **Re-verify FK targets by symbol.** Before writing the migration, confirm the primary key columns:
   - Teams table: grep `class EmailTeam` in `mcpgateway/db.py`; record `__tablename__` and the primary key column. Scout reports `__tablename__ = "email_teams"`, PK = `id` (String(36)). If this changed, update `cf_team_id` FK accordingly.
   - Roles table: grep `class Role` in `mcpgateway/db.py`; record `__tablename__` and the primary key column. Scout reports `__tablename__ = "roles"`, PK = `id` (String(36)), `name` is String(255) with only a partial unique index on `(name, scope)`. **`name` alone cannot be an FK target.** The `cf_role` column stores the role name as plain String(255) with no FK constraint; application-level validation queries the `roles` table by name.
   - If either table name or PK column differs from the scout report, update the column definitions in step 3 before proceeding.
1. **Re-verify alembic head.** Run `cd mcpgateway && alembic heads` and record the current single head. Use it as `down_revision` in the new migration.

2. **Write failing tests first.** Create test files:
   - `tests/unit/mcpgateway/db/test_external_group_mapping_model.py` — ORM model instantiation, unique constraint, FK references.
   - `tests/unit/mcpgateway/services/test_external_group_mapping_resolver.py` — resolver unit tests:
     - Mapped groups → returns correct `(team_ids, role_names)`.
     - Unmapped groups → fail-closed (empty lists, no error).
     - Mixed mapped/unmapped → only mapped groups contribute.
   - `tests/unit/mcpgateway/routers/test_external_group_mapping_admin.py` — CRUD deny-path tests:
     - Unauthenticated → 401.
     - Insufficient permissions → 403.
     - Invalid `cf_team_id` (nonexistent team) → 400.
     - Valid create/update/list/delete → 200.
   - Run: `uv run pytest tests/unit/mcpgateway/ -k "group_mapping or external_group" -q` — confirm all FAIL (red).

3. **Create the Alembic migration** at `mcpgateway/alembic/versions/<new_rev>_add_external_group_mappings.py`:
   - Table `external_group_mappings` with columns:
     - `id` — Integer, primary key, autoincrement.
     - `issuer` — String(512), not null.
     - `tenant` — String(512), nullable.
     - `external_group_id` — String(512), not null.
     - `cf_team_id` — String(255), ForeignKey("email_teams.id"), not null.
    - `cf_role` — String(255), nullable, **no FK constraint** (the `roles` table PK is `id` UUID; `name` alone has no unique index). Application-level validation in step 6 queries `roles` by name.
     - `validation_status` — String(50), default `"valid"`.
     - `last_validated_at` — DateTime, nullable.
     - `created_at`, `updated_at` — DateTime with server defaults.
   - Unique constraint on `(issuer, tenant, external_group_id)`.
   - Migration comment documents the uniqueness decision: "One group maps to exactly one CF team. The unique constraint on (issuer, tenant, external_group_id) enforces this. If future requirements need one group to grant membership in multiple teams, relax this constraint or add a separate join table."
   - Use the idempotent inspector-guard pattern: check table existence before create; check column existence before add.
   - `down_revision` = verified head from step 1.

4. **Add the ORM model** `ExternalGroupMapping` in `mcpgateway/db.py` (near the other mapping tables):
   - Mirror the migration schema exactly.
   - Add `__table_args__` for the unique constraint.

5. **Implement the resolver** `resolve_external_groups_to_teams` in `mcpgateway/utils/trusted_claims.py` (new file):
   - Module docstring: `"Trusted claims extraction and group-to-team resolution. This module will also host extract_trusted_principal (added by #5899)."`
   - Signature: `resolve_external_groups_to_teams(issuer: str, tenant: str | None, groups: list[str], db: Session) -> tuple[list[str], list[str]]`
   - Query `external_group_mappings` for matching rows.
   - Return `(team_ids, role_names)` from matched rows.
   - Unmapped groups contribute nothing (fail-closed).

6. **Implement admin CRUD router** under `/admin` prefix, RBAC-scoped:
   - `POST /admin/external-group-mappings` — create mapping.
   - `PUT /admin/external-group-mappings/{id}` — update mapping.
   - `GET /admin/external-group-mappings` — list mappings.
   - `DELETE /admin/external-group-mappings/{id}` — delete mapping.
   - Validate `cf_team_id` exists in `email_teams` table (400 if not).
   - Validate `cf_role` (if provided) by querying `roles` table where `name = cf_role` (400 if no matching row). No FK constraint — validated at application level only.
   - **Graph existence validation seam:** Accept an injectable validator callable `group_exists_validator: Callable[[str, str, str], str]` (returns `validation_status`). Ship with default = disabled (always returns `"valid"`). When Graph client lands in WO-B.7, wire the real validator. WARN-AND-ALLOW when Graph is unreachable (`validation_status="unknown"`, audit-logged).

7. **Add visibility-gate integration tests** (strict-xfail pointing at #5900):
   - `tests/unit/mcpgateway/test_visibility_gate.py`:
     - Team-visibility isolation: Agent-A (`visibility=team`, team=CF-Team-A) and Agent-B (`visibility=team`, team=CF-Team-B). Caller token maps only to CF-Team-A. `POST /a2a/agent-a/invoke` → 200; `POST /a2a/agent-b/invoke` → 404 (404-not-403 per `_check_agent_access` in `mcpgateway/services/a2a_service.py`).
     - Public-visibility baseline: Both agents set `visibility=public`. Both invocations → 200.
   - Mark with `pytest.mark.xfail(strict=True, reason="Requires trust branch from #5900")`.

8. **Add e2e team-isolation test** (strict-xfail pointing at #5900):
   - Full flow: create teams, register agents, insert mapping row, mint trust-mode JWT, invoke agents.
   - Mark with `pytest.mark.xfail(strict=True, reason="Requires trust branch from #5900")`.

9. **Add e2e no-mapping test** (strict-xfail pointing at #5900):
   - Trust-mode JWT with unmapped group → `token_teams = []` → team-visibility agent → 404; public agent → 200.
   - Mark with `pytest.mark.xfail(strict=True, reason="Requires trust branch from #5900")`.

10. Run all tests: `uv run pytest tests/unit/mcpgateway/ -k "group_mapping or external_group or visibility_gate" -q` — confirm green (pass + expected xfails).

### Files
- `mcpgateway/alembic/versions/<new_rev>_add_external_group_mappings.py` — create
- `mcpgateway/db.py` — modify (add `ExternalGroupMapping` model)
- `mcpgateway/utils/trusted_claims.py` — create (resolver function)
- `mcpgateway/routers/admin_external_group_mappings.py` — create (CRUD router)
- `tests/unit/mcpgateway/db/test_external_group_mapping_model.py` — create
- `tests/unit/mcpgateway/services/test_external_group_mapping_resolver.py` — create
- `tests/unit/mcpgateway/routers/test_external_group_mapping_admin.py` — create
- `tests/unit/mcpgateway/test_visibility_gate.py` — create

### Tests (exact commands)
- Fast gate: `uv run pytest tests/unit/mcpgateway/ -k "group_mapping or external_group or visibility_gate" -q`
- Expected: all green (pass + xfail, zero failures).
- Migration gate: `cd mcpgateway && alembic upgrade head && alembic downgrade -1 && alembic upgrade head` — clean up/down/up.
- Checkpoint gate (this story also runs): `make ruff` and `make test` — schema, ORM, resolver, and router land together.

### Guardrails (do NOT)
- Do not redesign the two-layer model — mapping feeds Layer-1 `token_teams`; Layer-2 RBAC untouched.
- Do not add periodic background group-metadata sync.
- Raw external group IDs must never reach `token_teams` — always map through the table.
- Do not hard-code the Graph validator — ship the seam with it disabled-by-default.
- Do not use `make test-protocol-compliance` — it does not exist.

### Done when
- [ ] Single alembic head; migration up/down/up clean on SQLite and Postgres.
- [ ] `ExternalGroupMapping` ORM model exists with correct schema.
- [ ] `resolve_external_groups_to_teams` returns `(team_ids, role_names)`, fail-closed on unmapped.
- [ ] Admin CRUD API works with RBAC scoping and deny-path tests.
- [ ] Graph validator seam exists, disabled-by-default, with stub tests.
- [ ] Visibility-gate tests exist (strict-xfail pointing at #5900).
- [ ] `uv run pytest tests/unit/mcpgateway/ -k "group_mapping or external_group or visibility_gate" -q` green.
- [ ] `make ruff` passes.

### Commit
`git commit -s` with message: `feat(auth): add external group mappings table, resolver, and admin CRUD`

### PR
- Title: `feat(auth): add external group mappings table, resolver, and admin CRUD`
- Body: Adds `external_group_mappings` table (issuer, tenant, external_group_id → cf_team_id, cf_role) with unique constraint. Resolver `resolve_external_groups_to_teams` returns (team_ids, role_names), fail-closed on unmapped groups. Admin CRUD API under /admin prefix, RBAC-scoped. Graph validator seam shipped disabled-by-default. Visibility-gate and e2e isolation tests added as strict-xfail pointing at #5900. Migration tested up/down/up on SQLite and Postgres. Risk to existing users: none (new table, no changes to existing tables).
- Footer: `Closes #5976`
- Submit: `gh stack submit` (never raw `git push`).

---

## WO-B.5 — #6272 Group-to-role mapping (cf_role wiring into claims)

- **Branch:** `feat/6272-group-role-mapping` cut from B.4's branch.
- **Goal:** Wire `cf_role` into admin CRUD validation and add trust-path merge tests.
- **Read first:** `issue://6272` (the story contract), then the files named in Steps — locate code by SYMBOL NAME (grep), never by line number.
- **Context you may assume:** WO-B.1 through WO-B.4 landed. `external_group_mappings` table exists with `cf_role` column. `resolve_external_groups_to_teams` already returns `(team_ids, role_names)`. Admin CRUD endpoints exist from WO-B.4. The `roles` table exists in `mcpgateway/db.py` (model `Role`). The `require_permission` decorator is in `mcpgateway/middleware/rbac.py`. The permission `a2a.invoke` exists in bootstrap roles (`team_admin` and `developer` in `mcpgateway/bootstrap_db.py`).

### Steps
1. **Write failing tests first.** Create `tests/unit/mcpgateway/routers/test_external_group_mapping_role.py`:
   - Test: `POST /admin/external-group-mappings` with `cf_role="developer"` → row created, 200.
   - Test: `POST /admin/external-group-mappings` with `cf_role="nonexistent"` → 400 validation error.
   - Test: `PUT /admin/external-group-mappings/{id}` with `cf_role="team_admin"` → updated, 200.
   - Test: `PUT /admin/external-group-mappings/{id}` with `cf_role="nonexistent"` → 400.
   - Run: `uv run pytest tests/unit/mcpgateway/routers/test_external_group_mapping_role.py -q` — confirm all FAIL (red).

2. **Wire `cf_role` validation into admin CRUD** in the router from WO-B.4 (`mcpgateway/routers/admin_external_group_mappings.py`):
   - On create/update: if `cf_role` is provided, query the `roles` table to confirm the role name exists.
   - Return 400 with message `"Role not found: {cf_role}"` if the role does not exist.
   - Same pattern as `cf_team_id` validation (query the `email_teams` table).

3. **Add trust-path merge tests** (strict-xfail pointing at #5899/#5900):
   - Create `tests/unit/mcpgateway/test_trust_role_merge.py`:
     - Test: trust-mode request with mapping row `cf_role=developer` + no `roles` claim → `@require_permission("a2a.invoke")` passes.
     - Test: trust-mode request with mapping row `cf_role=NULL` → 403 (no role granted).
     - Test: trust-mode request with `cf_role=developer` + token `roles=["viewer"]` → merged set `["developer", "viewer"]`.
   - Mark all with `pytest.mark.xfail(strict=True, reason="Requires trusted_claims module from #5899 and trust branch from #5900")`.

4. **Add AC-e2e-group-role-grant test** (strict-xfail pointing at #5900):
   - Mapping row: Entra-Group-GUID-1 → CF-Team-A, `cf_role=developer`.
   - Trust-mode JWT with `groups=[Entra-Group-GUID-1]`, no `roles` claim.
   - `POST /a2a/agent-a/invoke` (Agent-A: `visibility=team`, team=CF-Team-A) → 200.
   - Token with `groups=[Entra-Group-GUID-2]` (no mapping) → 403 (no role) or 404 (no team visibility).
   - Mark with `pytest.mark.xfail(strict=True, reason="Requires trust branch from #5900")`.

5. **Document the uniqueness decision** — add a comment to the WO-B.4 migration file (if not already present): "The unique constraint on (issuer, tenant, external_group_id) means one group maps to exactly one CF team and one role. This co-location is intentional: a single Entra group can grant both team membership and invocation role in one admin operation. If future requirements need one group to grant membership in multiple teams, relax the unique constraint or add a separate `cf_role_overrides` table."

6. Run all tests: `uv run pytest tests/unit/mcpgateway/ -k "group_role or trust_role" -q` — confirm green (pass + expected xfails).

### Files
- `mcpgateway/routers/admin_external_group_mappings.py` — modify (add `cf_role` validation)
- `tests/unit/mcpgateway/routers/test_external_group_mapping_role.py` — create
- `tests/unit/mcpgateway/test_trust_role_merge.py` — create

### Tests (exact commands)
- Fast gate: `uv run pytest tests/unit/mcpgateway/ -k "group_role or trust_role" -q`
- Expected: all green (pass + xfail, zero failures).
- Checkpoint gate (this story also runs): `make ruff` — must pass clean.

### Guardrails (do NOT)
- Do not embed permissions in the JWT or read permissions from the token.
- Do not bypass the server-side `roles` table resolution — role names from the mapping resolver are subject to the same unknown-role-ignored rule.
- Do not affect the SSO browser-flow path (`sso_entra_role_mappings` remains unchanged).
- Do not introduce a separate `external_group_role_mappings` table — use the `cf_role` column on `external_group_mappings`.

### Done when
- [ ] Admin CRUD validates `cf_role` against the `roles` table (400 on unknown role).
- [ ] Trust-path merge tests exist as strict-xfail pointing at #5899/#5900.
- [ ] AC-e2e-group-role-grant test exists as strict-xfail pointing at #5900.
- [ ] Migration comment documents the uniqueness decision.
- [ ] `uv run pytest tests/unit/mcpgateway/ -k "group_role or trust_role" -q` green.
- [ ] `make ruff` passes.

### Commit
`git commit -s` with message: `feat(auth): wire group-to-role mapping into claims resolution`

### PR
- Title: `feat(auth): wire group-to-role mapping into claims resolution`
- Body: Wires `cf_role` validation into admin CRUD (400 on unknown role, same pattern as `cf_team_id`). Trust-path merge tests and AC-e2e-group-role-grant test added as strict-xfail pointing at #5899/#5900. Migration comment documents the one-group-one-team-one-role uniqueness decision. No SSO browser-flow changes. Tested with `uv run pytest tests/unit/mcpgateway/ -k "group_role or trust_role" -q` and `make ruff`. Acceptance criteria of #6272 are met. Risk to existing users: none (additive validation on new endpoints only).
- Footer: `Closes #6272`
- Submit: `gh stack submit` (never raw `git push`).

---

## WO-B.6 — #5899 Claims extraction module + trust-mode virtual principal contract

- **Branch:** `feat/5899-trusted-claims-module` cut from `feat/6272-group-role-mapping`.
- **Goal:** Add a configurable claims-extraction module that returns a virtual principal matching the pinned contract.
- **Read first:** `issue://5899` (the story contract), then the files named in Steps — locate code by SYMBOL NAME (grep), never by line number.
- **Context you may assume:** Config settings from B.3 land (`jwt_claim_*`, `jwt_trust_overage_policy`, per-trust-root revocation-claim setting). The resolver `resolve_external_groups_to_teams(issuer, tenant, groups, db)` from B.4/B.5 returns `(team_ids, role_names)`.

### Steps
1. Write a failing test in `tests/unit/mcpgateway/test_trusted_claims.py` asserting: missing `user_id`-mapped claim raises; email absent yields principal with `email=None`; `AuditTrail` write uses sentinel `"unknown"` (never None); `ObservabilityTrace.user_email` accepts None; nested dotted path `realm_access.roles` resolves; overage marker detected; unknown role name ignored with WARNING; resolver-supplied `cf_role=developer` with no `roles` claim yields developer permission set.
2. Run: `uv run pytest tests/unit/mcpgateway/test_trusted_claims.py -q`. See it fail.
3. Extend `mcpgateway/utils/trusted_claims.py` (WO-B.4 created it; it already hosts `resolve_external_groups_to_teams`). Add `extract_trusted_principal(payload, settings, db) -> VirtualPrincipal`.
4. Implement claim readers honoring dotted paths (e.g. `realm_access.roles`). Document support level in module docstring.
5. Implement `VirtualPrincipal` dataclass: `user_id` (required opaque string), `email` (optional, None allowed), `full_name` (optional), `teams` (normalized list-of-strings OR list-of-{id,name} mirroring `normalize_token_teams` in `auth_context.py`), `roles` (list[str]), `is_admin` (bool, default False), `auth_provider` (str), `token_use="trusted"`.
6. Add `detect_overage_marker(payload) -> bool` helper. Refactor `sso_service.py` overage detection (near `sso_service.py` symbol `_claim_names` / `hasgroups` / `groups:src*`) to call the shared helper. SSO tests must pass unmodified.
7. Add revocation-claim extractor honoring per-trust-root setting (default `jti`; `uti` supported). Token without configured claim -> 401.
8. For external IdP payloads: call `resolve_external_groups_to_teams(issuer, tenant, external_groups, db)`. External group IDs NEVER enter `token_teams` directly. Merge returned `role_names` into the `roles` list before server-side `roles`-table resolution. Unknown names log WARNING and are skipped (fail-closed). When ALL external groups are unmapped, `token_teams` is the empty list `[]` (public-only access): the principal authenticates but sees no team resources.
9. Implement audit sentinel: when `email` is absent, `AuditTrail`-path writes string `"unknown"`; `ObservabilityTrace.user_email` accepts None.
10. Run: `uv run pytest tests/unit/mcpgateway/test_trusted_claims.py tests/unit/mcpgateway/test_sso*.py -q`. See all pass.

### Files
- `mcpgateway/utils/trusted_claims.py` (modify — add `extract_trusted_principal` and `VirtualPrincipal`; `resolve_external_groups_to_teams` is already present from WO-B.4)
- `mcpgateway/services/sso_service.py` (modify — overage-helper refactor)
- `tests/unit/mcpgateway/test_trusted_claims.py` (create)

### Tests (exact commands)
- Fast gate: `uv run pytest tests/unit/mcpgateway/test_trusted_claims.py -q` — all pass.
- SSO regression: `uv run pytest tests -k "sso" -q` — green, behavior-identical.
- Checkpoint gate: `make ruff` and `make test` — the overage-helper refactor touches the shared SSO path.

### Guardrails (do NOT)
- Do NOT touch `get_current_user`.
- Do NOT default `user_id` to email; missing mapped claim is an error.
- Do NOT embed permissions in tokens; roles resolve via the server-side `roles` table only.
- Do NOT place external group IDs into `token_teams`.
- Do NOT write None to `AuditTrail.user_id` (nullable=False).

### Done when
- `extract_trusted_principal` contract doc-comment enumerates every field and optionality.
- Nested-claim path tested and documented.
- Resolver `cf_role=developer` + no `roles` claim -> developer permission set (test asserts).
- SSO tests green, unmodified.

### Commit
`git commit -s` with message: `feat(auth): add configurable claims extraction and virtual principal contract`

### PR
- Title: `feat(auth): add configurable claims extraction and virtual principal contract`
- Body: Adds `mcpgateway/utils/trusted_claims.py` with `extract_trusted_principal` returning a `VirtualPrincipal` per the pinned contract. Claim readers support dotted paths (Keycloak `realm_access.roles`); overage-marker detection is shared with the SSO enrichment path (SSO behavior unchanged). External group IDs feed the resolver and never reach `token_teams`; resolver-supplied role names merge before server-side roles-table resolution. Audit-trail writes the `"unknown"` sentinel when email is absent. Tested via `test_trusted_claims.py` covering every mapping, nested paths, and resolver-supplied roles; SSO suite green unmodified. Acceptance: extraction contract doc-comment complete; resolver `cf_role=developer` + no roles claim resolves to developer permission set. Risk to existing users: none (SSO refactor behavior-identical; `get_current_user` untouched).
- Footer: `Closes #5899`
- Submit: `gh stack submit` (never raw `git push`).

---

## WO-B.7 — #5977 Entra group-overage app-only Graph client + cache

- **Branch:** `feat/5977-entra-graph-overage` cut from `feat/5899-trusted-claims-module`.
- **Goal:** Add an app-only Microsoft Graph client for trust-mode overage resolution with oid-keyed Redis cache.
- **Read first:** `issue://5977` (the story contract), then the files named in Steps — locate code by SYMBOL NAME (grep), never by line number.
- **Context you may assume:** `detect_overage_marker` helper from B.6. `sso_entra_graph_api_*` settings (config.py: enabled, timeout, max_groups). SSO provider record stores encrypted client credentials (`SSOProvider.client_secret_encrypted`).

### Steps
1. Write failing tests in `tests/unit/mcpgateway/test_entra_graph_client.py`: three-policy matrix (`fail_closed` -> 401; `graph_lookup` -> resolves; `proceed_without_groups` -> empty groups + WARNING log with oid); cache-hit single-call assertion (second request served from cache, Graph called once); AC-extra-1 Redis `ConnectionError` + Graph success -> authorized, Redis error + Graph fail -> 401; AC-extra-2 WARNING log carries oid.
2. Run: `uv run pytest tests/unit/mcpgateway/test_entra_graph_client.py -q`. See it fail.
3. Create `mcpgateway/utils/entra_graph_client.py`. Client-credentials token acquisition using the SSO provider's stored encrypted client secret (decrypt at call time). Call `POST https://graph.microsoft.com/v1.0/users/{oid}/getMemberObjects` with body `{"securityEnabledOnly": true}`. Bound by `sso_entra_graph_api_timeout` and `sso_entra_graph_api_max_groups`.
4. Implement oid-keyed Redis cache. Build keys with the shared `AuthCache._get_redis_key` helper from A.6/B.8 (key type `graph`, identifier = oid), so the key carries the version and mode segments: `mcpgw:auth:{version}:{mode}:graph:{oid}`. TTL bounded by presenting token's `exp`. On Redis read error: treat as cache miss, attempt live Graph call.
5. Wire policy dispatch in `trusted_claims.py`: `fail_closed` (default) -> 401 with actionable error; `graph_lookup` -> invoke client (cached); `proceed_without_groups` -> empty groups + WARNING log carrying oid.
6. NEVER use the inbound bearer token for Graph calls.
7. Run: `uv run pytest tests/unit/mcpgateway/test_entra_graph_client.py tests -k "overage or graph" -q`. See all pass.
8. Run SSO enrichment tests: `uv run pytest tests -k "sso" -q`. See green (no behavior change).

### Files
- `mcpgateway/utils/entra_graph_client.py` (create)
- `mcpgateway/utils/trusted_claims.py` (modify — policy dispatch)
- `tests/unit/mcpgateway/test_entra_graph_client.py` (create)

### Tests (exact commands)
- Fast gate: `uv run pytest tests -k "overage or graph" -q` — all pass, including three-policy matrix and cache assertions.
- SSO regression: `uv run pytest tests -k "sso" -q` — green, unmodified.
- Checkpoint gate: `make ruff`.

### Guardrails (do NOT)
- Do NOT use the inbound bearer token for Graph calls.
- Do NOT issue unbounded Graph queries.
- Do NOT change default-mode or SSO browser-flow behavior.
- Do NOT copy the delegated auth style from `sso_service.py` `_fetch_entra_groups_from_graph_api`; use client-credentials only.

### Done when
- Three-policy matrix tests green.
- Cache-hit test asserts single Graph call across two identical requests.
- AC-extra-1: Redis error -> cache miss -> live Graph attempt (test asserts both branches).
- AC-extra-2: `proceed_without_groups` emits WARNING log carrying oid (test asserts).
- Graph acquisition failure under `graph_lookup` -> 401.

### Commit
`git commit -s` with message: `feat(auth): add app-only Graph client for Entra group overage in trust mode`

### PR
- Title: `feat(auth): add app-only Graph client for Entra group overage in trust mode`
- Body: Adds `mcpgateway/utils/entra_graph_client.py` — an app-only client-credentials Graph client for trust-mode overage resolution. Reuses the SSO provider's stored encrypted client secret; never uses the inbound bearer token. OID-keyed Redis cache with TTL bounded by token exp; cache namespace derives from `auth_cache_key_version` and `jwt_trust_mode` so a mode flip cold-starts the cache. Policy dispatch wired into `trusted_claims.py`: `fail_closed` (default), `graph_lookup`, `proceed_without_groups`. Tested via `test_entra_graph_client.py`: three-policy matrix, cache-hit single-call, Redis-error fallback, WARNING-log assertion. Acceptance: all ACs green including AC-extra-1 cache-error and AC-extra-2 warning log. Risk to existing users: none (SSO browser flow untouched; default-mode path unchanged).
- Footer: `Closes #5977`
- Submit: `gh stack submit` (never raw `git push`).

---

## WO-B.8 — #5900 Trust-mode branch in get_current_user

- **Branch:** `feat/5900-trust-branch` cut from `feat/5977-entra-graph-overage`.
- **Goal:** Wire the trust-eligible funnel branch in `get_current_user` to extract a virtual principal, skip user lookup, keep revocation check.
- **Read first:** `issue://5900` (the story contract), then the files named in Steps — locate code by SYMBOL NAME (grep), never by line number.
- **Context you may assume:** `extract_trusted_principal` from B.6; resolver from B.4/B.5; Graph client from B.7; dispatch rule doc from B.1; `auth_cache_key_version` from A.6/B.3 (a mode flip cold-starts the cache — step 9).

### Steps
1. READ `tests/helpers/auth.py` first. Extend `make_test_jwt` (or add a new helper) to mint tokens with `token_use="trusted"` and the mapped claims. Do NOT assume existing helpers support `token_use`; verify.
2. Locate `get_current_user` by symbol in `mcpgateway/auth.py`. Locate funnel landmarks by symbol: plugin hook, UUID seam, dispatch, idle+revocation, user lookup, platform-admin bootstrap, is_active check.
3. Insert the trust-eligible branch BEFORE the user-lookup step. Eligibility is disjunctive per B.1: (a) gateway-signed: trust mode ON AND `token_use=="trusted"` AND required mapped claims AND configured revocation claim; (b) external IdP: trust mode ON AND issuer is a configured trust root AND required mapped claims AND configured revocation claim. Tokens with `token_use=="trusted"` and trust mode OFF -> 401.
4. On the trust branch: call `extract_trusted_principal(payload, settings, db)`. Then call `_check_token_revoked_sync` keyed by the CONFIGURED revocation claim (default `jti`; `uti` where configured). Revoked -> 401. Return the virtual principal.
5. SKIP: user lookup, `is_active` check, UUID->email seam, DB team resolution. `token_teams` for external tokens comes from the resolver; for gateway-signed tokens comes from claims.
6. Set `request.state` fields: `token_teams`, `token_use="trusted"`, `auth_method`, `jti` — same shape as default mode.
7. Add a code comment documenting the accepted posture change: no per-user `is_active` kill-switch in trust mode. Add a docs reference in `docs/docs/manage/configuration.md` (or the trust-mode doc from B.1/B.2).
8. Flip B.1 matrix branch-(a) rows from `xfail` to green. ALSO remove the strict-xfail markers from the WO-B.4 tests (`test_visibility_gate.py`, the e2e team-isolation test, the e2e no-mapping test) and the WO-B.5 tests (`test_trust_role_merge.py`, the AC-e2e-group-role-grant test): these now exercise the landed trust branch and must pass green. Keep ONLY the B.1 branch-(b) rows `strict=True, xfail` with pointer comment to `#5903`. After this step, grep the five affected test files for `xfail`: the only remaining markers are the B.1 branch-(b) rows.
9. Extend the auth-cache key with the auth mode. In `mcpgateway/cache/auth_cache.py`, `AuthCache.__init__` also reads `self._key_mode = getattr(settings, "jwt_trust_mode", "db")`. Change `_get_redis_key` to `f"{self._cache_prefix}auth:{self._key_version}:{self._key_mode}:{key_type}:{identifier}"`. A mode flip (`db` <-> `jwt-trust`) changes the prefix, cold-starting all auth caches automatically; no manual version bump. This is the second key-shape change in the stack (A.6 added the version segment); after this order the format is `mcpgw:auth:{version}:{mode}:{key_type}:{identifier}`. The A.6 test `test_redis_key_contains_version_segment` must change its expected prefix from `mcpgw:auth:v1:user:` to `mcpgw:auth:v1:db:user:` (mode defaults to `db`). The `_get_redis_key` doctest must change from `'mcpgw:auth:v1:user:test@example.com'` to `'mcpgw:auth:v1:db:user:test@example.com'`. Document the mechanism in a code comment in `mcpgateway/config.py` next to `auth_cache_key_version` and `jwt_trust_mode`.
10. Add smoke-level SQL-listener test asserting zero `email_users` reads on the trust path (full proof is B.13).
11. Run live-gateway obligation: `make test-mcp-rbac` with trust mode OFF, then ON. Tests pass both.
12. Run: `make test`. See green.

### Files
- `mcpgateway/auth.py` (modify — funnel branch)
- `tests/helpers/auth.py` (modify — trust-token minting helper)
- `tests/unit/mcpgateway/test_auth_trust_mode.py` (create or extend existing)
- `tests/live_gateway/test_trust_mode_rbac.py` (create — `pytest.mark.e2e`, `skip_no_gateway`)
- `docs/docs/manage/configuration.md` (modify — posture note)

### Tests (exact commands)
- Fast gate: `uv run pytest tests -k "trust" -q` — branch-(a) rows green; branch-(b) rows strict-xfail with pointer.
- Smoke SQL: `uv run pytest tests/unit/mcpgateway/test_auth_trust_mode.py -q` — zero user-table reads asserted.
- Live gate: `make test-mcp-rbac` — passes with trust mode OFF and ON.
- Checkpoint gate: `make test` and `make ruff`.

### Guardrails (do NOT)
- Do NOT alter the default-mode path.
- Do NOT skip the revocation check.
- Do NOT log raw tokens.
- Do NOT weaken the strict-xfail protocol on branch-(b) rows.

### Done when
- B.1 matrix branch-(a) rows fully green, and every strict-xfail test from WO-B.4 and WO-B.5 is flipped and green.
- B.1 branch-(b) rows remain strict-xfail pointing at #5903.
- `make test-mcp-rbac` passes both modes.
- Posture change documented in code and docs.

### Commit
`git commit -s` with message: `feat(auth): add JWT-trust verification path with claims-derived identity`

### PR
- Title: `feat(auth): add JWT-trust verification path with claims-derived identity`
- Body: Wires the trust-eligible funnel branch in `get_current_user` per #5896's dispatch rule. Trust-eligible tokens call `extract_trusted_principal` and `_check_token_revoked_sync` (keyed by configured revocation claim); user lookup, `is_active`, and DB team resolution are skipped. Auth-cache namespace derives from `jwt_trust_mode` so a mode flip cold-starts the cache automatically. Test fixtures in `tests/helpers/auth.py` mint `token_use="trusted"` tokens; B.1 matrix branch-(a) rows flipped from xfail to green; branch-(b) rows stay strict-xfail pointing at #5903. Live-gateway `make test-mcp-rbac` passes with trust mode both off and on. Posture change documented: no per-user `is_active` kill-switch in trust mode. Risk to existing users: none when trust mode is off (default-mode path unaltered).
- Footer: `Closes #5900`
- Submit: `gh stack submit` (never raw `git push`).

---

## WO-B.9 — #5901 TokenRevocation.revoked_by FK migration + trust-mode revocation semantics

- **Branch:** `fix/5901-revocation-fk-migration` cut from `feat/5900-trust-branch`.
- **Goal:** Relax the `revoked_by` FK so trust-mode principals can write revocation rows, and persist revocations across all insert sites.
- **Read first:** `issue://5901` (the story contract), then the files named in Steps — locate code by SYMBOL NAME (grep), never by line number.
- **Context you may assume:** `TokenRevocation.revoked_by` is `String(255)`, FK `email_users.email`, `nullable=False`, no `ondelete` (db.py `TokenRevocation` class). The idle-revoke handler at `auth.py` catches broad `Exception` (not just `IntegrityError`). Revocation insert sites: `routers/auth.py` (logout), `admin.py` (admin logout), `token_catalog_service.py` (revoke + admin_revoke_token), `token_blocklist_service.py`, `auth.py` (idle-revoke).

### Steps
1. Run `cd mcpgateway && alembic heads` to verify the current head. Record it.
2. Write failing tests in `tests/unit/mcpgateway/test_revocation_trust.py`: trust-mode logout writes a revocation row; same jti then yields 401; idle-timeout revoke persists (no swallowed exception). Write migration test in `tests/migration/test_revoked_by_nullable.py`: up/down/up clean on SQLite AND Postgres.
3. Run: `uv run pytest tests/unit/mcpgateway/test_revocation_trust.py tests/migration/test_revoked_by_nullable.py -q`. See fail.
4. Create an alembic migration. Use the idempotent inspector-guard pattern. Target the verified head. Inside `with op.batch_alter_table("token_revocations") as batch_op:` do BOTH: (a) `batch_op.drop_constraint(<fk_name>, type_="foreignkey")` where `<fk_name>` comes from `sa.inspect(bind).get_foreign_keys("token_revocations")` (typically `token_revocations_revoked_by_fkey`); (b) `batch_op.alter_column("revoked_by", existing_type=sa.String(255), nullable=True)`. Guard both with inspector checks. Never call `op.drop_constraint` outside batch mode — it fails on SQLite.
5. Update ALL insert sites to store the canonical `user_id` (from the virtual principal or the DB user) or one of these EXACT sentinel strings when no canonical user_id is available: `"system:idle-timeout"` (idle-revoke in `auth.py`), `"system:logout"` (logout in `routers/auth.py`), `"system:admin-logout"` (admin logout in `admin.py`). Do not invent other sentinels. Sites: `routers/auth.py` (logout, near line 322-323), `admin.py` (admin logout), `token_catalog_service.py` (revoke near `:953` + `admin_revoke_token` near `:978-1020`), `token_blocklist_service.py` (near `:116` and `:131`), `auth.py` (idle-revoke near `:1976`).
6. Fix the idle-revoke handler: narrow the broad `except Exception` at `auth.py` near `:1977-1978` to a dedicated try/except around the revocation insert only. On insert failure, log at ERROR level with the jti and the error detail, then continue the request. Do NOT re-raise: revocation persistence is best-effort, but failures must be visible in logs, never swallowed silently.
7. Run migration test: `uv run pytest tests/migration/test_revoked_by_nullable.py -q` — up/down/up clean on both engines.
8. Run: `uv run pytest tests/unit/mcpgateway/test_revocation_trust.py -q` — green.
9. Run: `make test`. See green.

### Files
- `mcpgateway/alembic/versions/<new>_relax_revoked_by_fk.py` (create)
- `mcpgateway/routers/auth.py` (modify — logout insert)
- `mcpgateway/admin.py` (modify — admin logout insert)
- `mcpgateway/services/token_catalog_service.py` (modify — revoke inserts)
- `mcpgateway/services/token_blocklist_service.py` (modify — revoke inserts)
- `mcpgateway/auth.py` (modify — idle-revoke handler + insert)
- `tests/migration/test_revoked_by_nullable.py` (create)
- `tests/unit/mcpgateway/test_revocation_trust.py` (create)

### Tests (exact commands)
- Fast gate: `uv run pytest tests/unit/mcpgateway/test_revocation_trust.py -q` — trust-mode logout writes row; same jti -> 401; idle revoke persists.
- Migration gate: `uv run pytest tests/migration/test_revoked_by_nullable.py -q` — up/down/up clean on SQLite and Postgres.
- Checkpoint gate: `make test` and `make ruff`.

### Guardrails (do NOT)
- Do NOT change revocation CHECK semantics (jti lookup unchanged).
- Do NOT make `revoked_by` non-string.
- Do NOT drop any existing FK beyond `revoked_by`.
- Do NOT swallow the idle-revoke exception silently.

### Done when
- Single alembic head.
- Migration up/down/up clean on SQLite AND Postgres.
- Trust-mode logout -> same jti -> 401 (test).
- Idle-timeout revoke persists (test).
- All insert sites store canonical user_id or system sentinel.

### Commit
`git commit -s` with message: `fix(auth): relax revoked_by FK and persist revocations for trust-mode principals`

### PR
- Title: `fix(auth): relax revoked_by FK and persist revocations for trust-mode principals`
- Body: Alembic migration (batch_alter_table for SQLite) makes `TokenRevocation.revoked_by` nullable and drops the FK to `email_users.email`. All six revocation insert sites updated to store canonical user_id or a system sentinel string. Idle-revoke handler no longer swallows revocation errors; revocations persist under broad Exception. Migration test verifies up/down/up clean on SQLite and Postgres. Trust-mode logout test writes a revocation row; same jti yields 401 on next request. Risk to existing users: existing default-mode revocation rows retain their user_id values; migration is additive-nullable only.
- Footer: `Closes #5901`
- Submit: `gh stack submit` (never raw `git push`).

---

## WO-B.10 — #5902 Admin claim feeds both admin tracks atomically + parity tests

- **Branch:** `feat/5902-admin-claim-parity` cut from `fix/5901-revocation-fk-migration`.
- **Goal:** Wire the mapped admin claim into both `is_admin` and the effective-roles set atomically, with parity tests against DB platform_admin.
- **Read first:** `issue://5902` (the story contract), then the files named in Steps — locate code by SYMBOL NAME (grep), never by line number.
- **Context you may assume:** `PermissionService.check_permission` (permission_service.py); `public-only token_teams=[]` suppression block at `:121-132`; `default_roles` in `bootstrap_db.py` (built-in roles: platform_admin, team_admin, developer, viewer, platform_viewer); platform_admin assignment in `bootstrap_db.py` near `:583-602`; email-match bootstrap path at `auth.py` symbol `_bootstrap_platform_admin_user` stays default-mode-only.

### Steps
1. Write failing parity tests in `tests/unit/mcpgateway/test_admin_claim_parity.py`: (a) admin-claim trust token vs DB platform_admin — permission-for-permission parity across a sample matrix of built-in role permissions from `bootstrap_db.py`; (b) non-admin: `roles=["developer"]` + `teams=["t1"]` trust token yields exactly the developer permission set; (c) deny: `is_admin=false` or absent + admin attempt -> 403; (d) `token_teams=[]` + admin claim -> no bypass; (e) unknown role name ignored with WARNING log, no permissions from it.
2. Run: `uv run pytest tests/unit/mcpgateway/test_admin_claim_parity.py -q`. See fail.
3. In `trusted_claims.py`: the mapped admin claim populates BOTH `VirtualPrincipal.is_admin=True` AND adds `"platform_admin"` to the `roles` list as ONE atomic mapping. No intermediate state.
4. In `PermissionService.check_permission` (permission_service.py): honor claims-derived admin without a DB user row. The `public-only token_teams=[]` suppression block must still suppress bypass — an admin-claim token with empty teams gets no bypass.
5. Ensure the email-match bootstrap path (`_bootstrap_platform_admin_user` and call sites) stays default-mode-only. Trust mode uses claim-only bootstrap.
6. Run: `uv run pytest tests/unit/mcpgateway/test_admin_claim_parity.py -q`. See all pass.
7. Run: `make test`. See green.

### Files
- `mcpgateway/utils/trusted_claims.py` (modify — atomic admin mapping)
- `mcpgateway/services/permission_service.py` (modify — honor claims-derived admin)
- `tests/unit/mcpgateway/test_admin_claim_parity.py` (create)

### Tests (exact commands)
- Fast gate: `uv run pytest tests/unit/mcpgateway/test_admin_claim_parity.py -q` — all parity and deny tests green.
- Checkpoint gate: `make test` and `make ruff`.

### Guardrails (do NOT)
- Do NOT grant admin from any unmapped or unknown claim.
- Do NOT weaken the public-only suppression rule.
- Do NOT modify the email-match bootstrap path.
- Do NOT allow `token_teams=[]` + admin claim to bypass restrictions.

### Done when
- Admin-claim token yields permission-for-permission parity with DB platform_admin (test matrix).
- Non-admin `roles=["developer"]` trust token yields exactly the developer permission set (test).
- Deny tests: is_admin false/absent + admin attempt -> 403; `token_teams=[]` + admin claim -> no bypass; unknown role ignored with warning.
- `make test` green.

### Commit
`git commit -s` with message: `feat(auth): honor mapped admin claim across both admin tracks in trust mode`

### PR
- Title: `feat(auth): honor mapped admin claim across both admin tracks in trust mode`
- Body: Maps the `is_admin` claim to both `VirtualPrincipal.is_admin` and the `"platform_admin"` entry in the roles list as one atomic mapping. `PermissionService.check_permission` honors claims-derived admin without a DB user row; `public-only token_teams=[]` suppression remains intact. Parity tests compare an admin-claim trust token against a DB platform_admin across the built-in role permission matrix from `bootstrap_db.py`. Non-admin test: `roles=["developer"]` + `teams=["t1"]` trust token yields exactly the developer permission set. Deny tests: is_admin false/absent + admin attempt -> 403; `token_teams=[]` + admin claim -> no bypass; unknown role name -> WARNING, no permissions. Risk to existing users: none (email-match bootstrap path unchanged; default-mode admin semantics untouched).
- Footer: `Closes #5902`
- Submit: `gh stack submit` (never raw `git push`).

---

## WO-B.11 — #5903 External IdP trust root without provisioning

- **Branch:** `feat/5903-external-idp-trust-root` cut from the WO-B.10 / #5902 branch.
- **Goal:** Accept trusted IdP tokens without local user provisioning when trust mode is enabled, building the identity from token claims alone.
- **Read first:** `issue://5903` (the story contract), then the files named in Steps — locate code by SYMBOL NAME (grep), never by line number.
- **Context you may assume:** WO-B.3 (#5898) landed the trust-mode settings (`jwt_trust_mode`, claim mapping, overage policy, revocation-claim setting). WO-B.4 (#5976) landed the `external_group_mappings` table and `resolve_external_groups_to_teams`. WO-B.5 (#6272) added `cf_role` to the resolver's return. WO-B.6 (#5899) landed `mcpgateway/utils/trusted_claims.py` with `extract_trusted_principal(payload, settings, db)`. WO-B.7 (#5977) landed the app-only Graph client for overage resolution. WO-B.8 (#5900) landed the trust branch in `get_current_user` (gateway-signed path). The existing `build_external_identity` function at `mcpgateway/utils/verify_credentials.py` (def at line 2207) provisions users via `authenticate_or_create_user` and reads `is_admin` from the DB row. The existing `verify_external_idp_token` (def at line 2072) resolves a provider by unverified `iss`, checks `trusted_for_api_auth` + `api_audience` fail-closed (lines 2103-2112), then delegates to `verify_oauth_access_token`. The external identity cache uses token-hash keys (lines 482-586, `invalidate_external_identity_cache` at line 518).

### Steps
1. Write the failing trust-mode external-IdP test. Create `tests/unit/mcpgateway/utils/test_external_idp_trust_mode.py`:
   - Mock an SSOProvider with `trusted_for_api_auth=True` and a valid `api_audience`.
   - Mock JWKS verification so the token passes `verify_oauth_access_token`.
   - Set `settings.jwt_trust_mode = "jwt-trust"`.
   - Set the configured revocation-claim setting to `"jti"`. Provide a token with `jti` present.
   - Attach a SQLAlchemy event listener on `select` against `email_users` that records every emitted statement.
   - Call the trust-mode branch of `build_external_identity`. Assert: (a) zero INSERTs into `email_users`; (b) zero SELECTs against `email_users`; (c) the returned payload has `token_use == "trusted"`; (d) `teams` and `roles` derive from `resolve_external_groups_to_teams` (not the DB user); (e) `is_admin` derives from the mapped claims (not a DB row).
   - Run the test. See it fail.
2. Write the failing revocation-claim test. In the same file:
   - Configure revocation claim `"jti"`. Provide a token with NO `jti` claim. Assert the function returns `None` (or raises 401-equivalent) with a log message naming the missing claim.
   - Configure revocation claim `"uti"`. Provide a token with `uti` present, `jti` absent. Assert success.
   - Configure revocation claim `"uti"`. Provide a token with neither `uti` nor `jti`. Assert rejection.
   - Run. See it fail.
3. Write the failing overage-policy tests:
   - `fail_closed`: token has overage markers (`_claim_names`, `hasgroups`, `groups:srcN` per `sso_service.py:1444-1453`), policy is `fail_closed`. Assert 401 rejection.
   - `graph_lookup`: same overage markers, policy is `graph_lookup`. Mock the WO-B.7 Graph client to return groups. Assert groups resolve via the client and map through `resolve_external_groups_to_teams`.
   - `proceed_without_groups`: same overage markers, policy is `proceed_without_groups`. Assert `token_teams=[]`, a WARNING log with the token's `oid`, and a successful (degraded) return.
   - Run. See them fail.
4. Branch `build_external_identity` on trust mode. In `mcpgateway/utils/verify_credentials.py`, at the top of `build_external_identity`:
   - Check `settings.jwt_trust_mode == "jwt-trust"`. When true AND the provider is a configured trust root (`trusted_for_api_auth=True` + `api_audience` set), enter the trust-mode branch.
   - In the trust-mode branch: extract the configured revocation claim from the verified claims. If absent, log and return `None` (the caller maps this to 401). Call `extract_trusted_principal(verified_claims, settings, db)` from `mcpgateway/utils/trusted_claims.py`. The returned principal carries `sub` (mapped user_id), `email`, `teams`, `roles`, `is_admin` — all from claims, not the DB.
   - Set `token_use = "trusted"` on the payload (not `"session"`).
   - Do NOT call `authenticate_or_create_user`. Do NOT call `get_user_by_email`. Do NOT read `is_admin` from any DB row.
   - Map external groups: call `resolve_external_groups_to_teams(issuer, tenant, groups, db)` and assign the returned `(team_ids, role_names)` to the payload's `teams` and `roles`.
   - Detect overage (same markers as `sso_service.py:1444-1453`). Apply the policy: `fail_closed` → return None; `graph_lookup` → call the WO-B.7 Graph client, re-map groups; `proceed_without_groups` → set `teams=[]`, log WARNING with `oid`.
   - Default mode (`jwt_trust_mode == "db"`): leave the existing provisioning path unchanged.
5. Extend `invalidate_external_identity_cache`. The claims-derived path uses the same token-hash cache key. Verify the existing `invalidate_external_identity_cache` clears both paths (it already clears `_external_identity_cache` entirely). Add a test that puts a trust-mode entry, invalidates, and confirms the entry is gone.
6. Flip the B.1 dispatch-matrix branch-(b) rows. In the xfail-marked tests from WO-B.1 (#5896), find the external-IdP trust rows marked `strict-xfail`. Remove the xfail marker; the tests must now pass green with the trust-mode implementation.
7. Run the story's acceptance command: `uv run pytest tests -k "external_idp or sso_token" -q` → green including the trust-mode no-provisioning assertion.
8. Checkpoint gate: `make ruff` → pass.

### Files
- `mcpgateway/utils/verify_credentials.py` — modify `build_external_identity` (add trust-mode branch).
- `tests/unit/mcpgateway/utils/test_external_idp_trust_mode.py` — create.
- Tests from WO-B.1 (#5896) — flip xfail markers on branch-(b) rows.

### Tests (exact commands)
- Fast gate: `uv run pytest tests -k "external_idp or sso_token" -q` → pass.
- Fast gate: `uv run pytest tests/unit/mcpgateway/utils/test_external_idp_trust_mode.py -q` → pass.
- Checkpoint gate (this story also runs): `make ruff` and `make test` → pass. `build_external_identity` is a critical auth function and B.1 rows flip in this commit.
- Expected result: all green. Zero INSERTs into `email_users` asserted via SQL listener.

### Guardrails (do NOT)
- Do not change JWKS validation or iss/aud checks.
- Do not change default-mode provisioning behavior.
- Do not introduce sid-keyed revocation. The revocation claim is configurable (default `jti`, fallback `uti`); nothing else.
- Do not skip the overage-policy tests. All three policies must have executable tests.

### Done when
- Trust-mode external-IdP token authorizes without any INSERT or SELECT against `email_users`.
- External trust token lacking the configured revocation claim → 401 with clear log.
- Overage policies (`fail_closed`, `graph_lookup`, `proceed_without_groups`) all have passing tests.
- Branch-(b) dispatch-matrix rows flipped from strict-xfail to green in this commit.
- `make ruff` passes.

### Commit
`git commit -s` with message: `feat(auth): accept trusted IdP tokens without local provisioning in trust mode`

### PR
- Title: `feat(auth): accept trusted IdP tokens without local provisioning in trust mode`
- Body: State what changed: `build_external_identity` branches on trust mode — when enabled and the issuer is a configured trust root, identity builds from claims via `extract_trusted_principal` with zero DB provisioning. State how tested: SQL listener asserts zero `email_users` access; revocation-claim tests for `jti` and `uti`; three overage-policy tests; B.1 matrix rows flipped from xfail. State acceptance met. State risk to existing users: none — default mode is unchanged.
- Footer: `Closes #5903`
- Submit: `gh stack submit` (never raw `git push`).

## WO-B.12 — #5904 Trust-token minting + catalog + choke points

- **Branch:** `feat/5904-trust-token-minting` cut from `feat/5903-external-idp-trust-root` (the WO-B.11 branch).
- **Goal:** Stamp `token_use="trusted"` plus mapped claims at the token catalog mint path; align `validate_token_user` and the `HTTP_AUTH_RESOLVE_USER` plugin hook with trust mode.
- **Read first:** `issue://5904` (the story contract), then the files named in Steps — locate code by SYMBOL NAME (grep), never by line number.
- **Context you may assume:** WO-B.11 landed the external-IdP trust branch. WO-B.8 landed the trust branch in `get_current_user`. WO-B.3 landed `jwt_trust_mode` and all claim-mapping settings. The `_generate_token` method in `mcpgateway/services/token_catalog_service.py` (def at line 221, body lines 221-310) mints API tokens with `token_use: "api"`, `user_data.is_admin` from the `EmailUser` row, and `teams` from the team_id param. The `create_token` method (line 456-460) hard-requires an `EmailUser` row — it raises `ValueError("User not found: ...")` when absent. `validate_token_user` (def at `mcpgateway/auth.py:1325`) wraps `get_current_user` and returns an `EmailUser`. The `HTTP_AUTH_RESOLVE_USER` plugin hook (lines 1553-1674 in `mcpgateway/auth.py`) resolves users via plugins before falling through to standard auth.

### Steps
1. Write the failing mint-path test. Create `tests/unit/mcpgateway/services/test_token_catalog_trust_mode.py`:
   - **Test A (trust-only principal, no EmailUser row):** Call `create_token` for a principal whose `sub` has no `email_users` row. Assert a clear, documented error (not a 500/IntegrityError). The error message names the disabled surface.
   - **Test B (DB-backed principal, claims from server authority):** Create an `EmailUser` row. Call `create_token` for that user. Assert the minted JWT carries `token_use: "api"` (unchanged for catalog-minted tokens — the catalog mints API tokens, not trust tokens). Assert `is_admin` derives from the DB row, never from caller-supplied claims. Assert `sub` equals the inbound verified `user_id`.
   - **Test C (no act-as):** Call `create_token` with a `sub` that differs from the authenticated caller's `user_id`. Assert rejection with a clear error.
   - **Test D (caller-supplied claims ignored):** Call `create_token` where the request body includes `teams` or `is_admin` values. Assert the minted token's claims derive from server-side authority only — caller-supplied values are ignored.
   - Run. See them fail.
2. Implement the mint-path decision. In `mcpgateway/services/token_catalog_service.py`:
   - In `create_token` (around line 456-460): when `settings.jwt_trust_mode == "jwt-trust"` AND the requesting principal is trust-only (no `email_users` row), raise `ValueError("Token minting is disabled for trust-only principals. Create a local user account first.")`. This is the fail-closed default.
   - For DB-backed principals: `_generate_token` stays unchanged. Claims derive from the `EmailUser` row and server-side team resolution. Caller-supplied `teams`, `is_admin`, or `roles` in the request body are never embedded in the token.
   - Assert `sub` in the minted token equals the inbound verified `user_id` (the `user.id` UUID from the DB row). Reject any request where the caller asks to mint a token for a different `sub`.
3. Write the failing trust-token minting test. Create `tests/unit/mcpgateway/services/test_trust_token_minting.py`:
   - This tests a NEW minting path for gateway-signed trust tokens (`token_use="trusted"`).
   - Create a helper or new method `mint_trust_token(payload, settings)` that stamps `token_use="trusted"`, `sub` from the trust principal's `user_id`, `teams`/`roles`/`is_admin` from `extract_trusted_principal` output.
   - Assert the minted token passes the B.1 dispatch rule's eligibility check.
   - Assert `sub` in the minted token equals the inbound verified user_id — no act-as.
   - Run. See it fail.
4. Implement the trust-token minting helper. Add `mint_trust_token` as a method on the token catalog service class in `mcpgateway/services/token_catalog_service.py`, alongside `_generate_token`. The helper:
   - Takes a verified principal (from `extract_trusted_principal`) and `settings`.
   - Calls `create_jwt_token` with `data={"sub": principal.user_id, "jti": <generated>, "token_use": "trusted"}`, `user_data={"email": principal.email, "is_admin": principal.is_admin, "auth_provider": "trust"}`, `teams=principal.teams`.
   - Returns the signed token string.
   - Does NOT insert into `email_api_tokens` (trust tokens are ephemeral, catalog-tracked only if the deployment opts in later).
   - Operational mint path: add `POST /admin/tokens/trust` to the router that exposes the token-catalog endpoints (grep for the route that calls `create_token`). The endpoint requires an admin permission, accepts only a target user identifier, derives ALL claims from server-side authority (DB roles, DB teams, DB admin flag), sets `sub` to the target's canonical user_id, and rejects trust-only targets (no `email_users` row) with 403. Tests: admin mints for a DB-backed user → 200 and the JWT carries `token_use="trusted"` with server-derived claims; non-admin → 403; trust-only target → 403; caller-supplied claim fields in the request body are ignored.
5. Align `validate_token_user` with trust mode. In `mcpgateway/auth.py`, at `validate_token_user` (def at line 1325):
   - When trust mode is ON and `get_current_user` returns a trust-mode principal (identified by `token_use == "trusted"` in the request state or payload), wrap the result in a virtual `EmailUser`-compatible object or return it directly.
   - Document the trust-mode return type in the docstring.
   - Write a test: trust-mode token passes `validate_token_user` and returns the expected principal.
6. Align the `HTTP_AUTH_RESOLVE_USER` plugin hook with trust mode. In `mcpgateway/auth.py` (hook code at lines 1553-1674):
   - Decision: **fail-closed default — hook DISABLED in trust mode** with a clear log message.
   - When `settings.jwt_trust_mode == "jwt-trust"`, skip the plugin hook invocation. Log: `"HTTP_AUTH_RESOLVE_USER hook disabled in trust mode"`.
   - Write a test: trust-mode request with a registered plugin hook → hook is NOT called; the trust-mode path handles authentication directly. Log message is present.
7. Write deny tests for every matrix row. For each disabled surface in the B.2 matrix:
   - Trust-only principal hits `create_token` → documented error (401 or 400 with clear message), never 500.
   - Trust-mode principal hits the plugin hook → documented behavior (hook skipped, clear log).
   - Run. See them pass.
8. Checkpoint gate: `make ruff` → pass; `make test` → pass.

### Files
- `mcpgateway/services/token_catalog_service.py` — modify `create_token` (trust-only guard), add the `mint_trust_token` method; add the `POST /admin/tokens/trust` admin endpoint on the router that hosts catalog endpoints.
- `mcpgateway/auth.py` — modify `validate_token_user` (trust-mode return), modify `HTTP_AUTH_RESOLVE_USER` hook region (disable in trust mode).
- `tests/unit/mcpgateway/services/test_token_catalog_trust_mode.py` — create.
- `tests/unit/mcpgateway/services/test_trust_token_minting.py` — create.
- `tests/unit/mcpgateway/test_auth_trust_choke_points.py` — create (validate_token_user + plugin hook tests).

### Tests (exact commands)
- Fast gate: `uv run pytest tests -k "trust_token or token_catalog_trust or auth_trust_choke" -q` → pass.
- Checkpoint gate (this story also runs): `make ruff` → pass; `make test` → pass.
- Expected result: all green. Trust-only principal gets documented error, never 500/IntegrityError.

### Guardrails (do NOT)
- Do not let any choke point silently bypass the B.1 dispatch rule.
- Do not allow caller-supplied claims to override server-side authority in minted tokens.
- Do not allow `sub` in a minted token to differ from the inbound verified `user_id`.
- Do not enable the plugin hook in trust mode without explicit opt-in (fail-closed default).

### Done when
- Every B.2 matrix row for these surfaces has an executable test matching the documented behavior.
- Trust-only principal hitting `create_token` gets a documented error, never 500.
- `validate_token_user` handles trust-mode principals correctly.
- `HTTP_AUTH_RESOLVE_USER` hook is disabled in trust mode with clear log.
- `make test` green.

### Commit
`git commit -s` with message: `feat(auth): align token catalog and secondary auth choke points with trust mode`

### PR
- Title: `feat(auth): align token catalog and secondary auth choke points with trust mode`
- Body: State what changed: token catalog rejects trust-only principals with explicit error; trust-token minting helper stamps `token_use="trusted"` with claims from server authority; `validate_token_user` handles trust-mode principals; plugin hook disabled in trust mode with clear log. State how tested: four mint-path tests, trust-token minting test, deny tests for every matrix row, admin mint-endpoint tests. State acceptance met. Trust tokens are not tracked in the token catalog: revocation is via the jti-based blocklist only; the catalog revoke endpoint does not apply to them. State risk to existing users: none — default mode is unchanged.
- Footer: `Closes #5904`
- Submit: `gh stack submit` (never raw `git push`).

## WO-B.13 — #5905 Trust-mode acceptance suite

- **Branch:** `feat/5905-trust-mode-acceptance-suite` cut from `feat/5904-trust-token-minting` (the WO-B.12 branch).
- **Goal:** Deliver six acceptance suites that prove trust mode works end-to-end: no-DB proof, multi-worker revocation, config-flip, UAID propagation, overage-degraded path, and cross-gateway UAID trust mode.
- **Read first:** `issue://5905` (the story contract), then the files named in Steps — locate code by SYMBOL NAME (grep), never by line number.
- **Context you may assume:** All prior Stack B stories landed. Trust mode is fully implemented: dispatch rule (B.1), config surface (B.3), external group mappings (B.4), role mapping (B.5), trusted claims (B.6), Graph client (B.7), trust branch in `get_current_user` (B.8), revocation FK (B.9), admin claim (B.10), external IdP (B.11), minting (B.12). The Redis blocklist lives in `mcpgateway/services/token_blocklist_service.py` (revoke at line 82, Redis setex at line 146, read at line 164). The multi-instance runner exists at `tests/live_gateway/run_primary_worker_multiinstance.sh`. Agent visibility has three values: public/team/private (`A2AAgent.visibility` at `mcpgateway/db.py:4987`; access check `_check_agent_access` at `mcpgateway/services/a2a_service.py:471`).

### Steps
1. **Suite (a): NO-DB PROOF.** Create `tests/unit/mcpgateway/test_trust_mode_no_db_proof.py`:
   - Use a SQLAlchemy event listener on the `select` event for the `email_users` table.
   - Send 50+ authenticated trust-mode requests through `get_current_user` (use `httpx.AsyncClient` against the test app, or call `get_current_user` directly with mocked credentials).
   - Assert ZERO `SELECT` statements emitted against `email_users` across all 50+ requests.
   - Record p99 latency for trust-mode requests and default-mode requests (informational). Assert no regression greater than 2x (the assertion is `trust_p99 <= default_p99 * 2.0`).
   - This test MUST be CI-eligible: runs in `uv run pytest` without Docker or external services.
   - Run. See it fail (before trust mode is wired, the default path queries `email_users`).
2. **Suite (b): Multi-worker live e2e.** Create `tests/live_gateway/test_trust_mode_multi_worker.py`:
   - Reuse the pattern from `tests/live_gateway/run_primary_worker_multiinstance.sh`.
   - Launch 2 gateway workers sharing a Redis blocklist.
   - Issue a trust-mode token with a known `jti`.
   - Revoke the token on worker A (via the blocklist service or admin endpoint).
   - Within the documented negative-cache TTL window, send the same `jti` to worker B. Assert 401 (revoked).
   - Mark with `@pytest.mark.e2e` and `skip_no_gateway`.
   - This test runs via the live-gateway runner, not in CI unit tests.
3. **Suite (c): Config-flip.** Create `tests/unit/mcpgateway/test_trust_mode_config_flip.py`:
   - Issue tokens in default mode (`jwt_trust_mode="db"`).
   - Flip to trust mode (`jwt_trust_mode="jwt-trust"`). Assert the same tokens behave per the B.1 dispatch doc: tokens with `token_use=="trusted"` pass the trust eligibility check; tokens without it follow the default funnel.
   - Flip back to default mode. Assert tokens with `token_use=="trusted"` get 401 (trust marker rejected when trust mode is OFF).
   - Run. See it fail (before implementation, the flip has no effect).
4. **Suite (d): UAID propagation.** Create `tests/unit/mcpgateway/test_trust_mode_uaid.py`:
   - Document that trust-mode claims propagate as forwarded bearer tokens per existing UAID rules.
   - Assert `UAID_ALLOWED_DOMAINS` semantics are unchanged (fail-closed allowlist).
   - Test: a trust-mode token forwarded cross-gateway carries the original claims; the remote gateway re-evaluates against its own `external_group_mappings`.
5. **Suite (e): Overage-degraded e2e.** Create `tests/unit/mcpgateway/test_trust_mode_overage_degraded.py`:
   - Issue a trust-mode JWT with overage markers (`_claim_names`, `hasgroups`, `groups:srcN`).
   - Set `jwt_trust_overage_policy=proceed_without_groups`.
   - Assert: `token_teams=[]` in the resolved principal.
   - Assert: `visibility=team` agents return 404 (via `_check_agent_access` at `a2a_service.py:471`).
   - Assert: `visibility=public` agents return 200.
   - Assert: WARNING-level log with `oid` is emitted.
   - Run. See it fail.
6. **Suite (f): Cross-gateway UAID trust-mode.** Create `tests/unit/mcpgateway/test_trust_mode_cross_gateway.py`:
   - Mock a remote gateway that evaluates against its own `external_group_mappings` table.
   - Caller is mapped to Team-A only on the remote gateway.
   - Target agent belongs to Team-B on the remote gateway.
   - Assert: cross-gateway call returns 404.
   - Run. See it fail.
7. Implement any remaining wiring needed for the suites to pass (typically none — the suites exercise already-implemented code).
8. Run the full suite selection: `uv run pytest tests -k "trust_mode" -q` → all six suites green.
9. Checkpoint gate (this story runs the full gate): `make ruff` → pass; `make test` → pass.

### Files
- `tests/unit/mcpgateway/test_trust_mode_no_db_proof.py` — create.
- `tests/live_gateway/test_trust_mode_multi_worker.py` — create.
- `tests/unit/mcpgateway/test_trust_mode_config_flip.py` — create.
- `tests/unit/mcpgateway/test_trust_mode_uaid.py` — create.
- `tests/unit/mcpgateway/test_trust_mode_overage_degraded.py` — create.
- `tests/unit/mcpgateway/test_trust_mode_cross_gateway.py` — create.

### Tests (exact commands)
- Fast gate: `uv run pytest tests -k "trust_mode" -q` → pass (suites a, c, d, e, f).
- CI-eligible: suite (a) `uv run pytest tests/unit/mcpgateway/test_trust_mode_no_db_proof.py -q` → pass.
- Live gate: suite (b) runs via `tests/live_gateway/run_primary_worker_multiinstance.sh` (mark `@pytest.mark.e2e` + `skip_no_gateway`).
- Checkpoint gate (this story also runs): `make ruff` → pass; `make test` → pass.
- Expected result: all green. No-DB proof asserts on executed SQL, not grep.

### Guardrails (do NOT)
- Do not weaken suite (a) to a grep check — it MUST assert on executed SQL via the SQLAlchemy event listener.
- Do not skip any of the six suites.
- Do not relax the 2x latency budget in suite (a) without documenting the reason.
- Do not let overage-degraded (suite e) silently bypass security — the WARNING log is mandatory.

### Done when
- All six suites green with outputs captured.
- No-DB assertion runs in CI-eligible form (unit/integration, not manual).
- Overagedegraded path emits WARNING with `oid`; visibility=team agents return 404; visibility=public agents return 200.
- Cross-gateway test: caller mapped to Team-A, agent on Team-B → 404.
- `make test` green.

### Commit
`git commit -s` with message: `test(auth): add trust-mode acceptance suite (no-DB, multi-worker, config-flip)`. Add a commit body listing all six suites: `git commit -s -m '<subject>' -m 'Suites: no-DB proof; multi-worker revocation; config-flip; UAID propagation; overage-degraded; cross-gateway UAID.'`

### PR
- Title: `test(auth): add trust-mode acceptance suite (no-DB, multi-worker, config-flip)`
- Body: State what changed: six acceptance suites prove trust mode end-to-end. No-DB proof asserts zero `email_users` queries across 50+ requests via SQLAlchemy event listener. Multi-worker revocation proves Redis blocklist propagation. Config-flip proves dispatch-rule behavior across mode transitions. UAID, overage-degraded, and cross-gateway suites prove edge cases. State how tested: all six suites green; no-DB proof CI-eligible. State acceptance met. State risk to existing users: none — tests only.
- Footer: `Closes #5905`
- Submit: `gh stack submit` (never raw `git push`).

## WO-B.14 — #5906 Docs sweep + Epic 2 validation gate

- **Branch:** `docs/5906-trust-mode-docs-gate` cut from `feat/5905-trust-mode-acceptance-suite` (the WO-B.13 branch).
- **Goal:** Document JWT-trust mode in every user-facing doc surface, update AGENTS.md invariants, land tests for every disabled-with-clear-error matrix row, and run the full validation gate with trust mode OFF and ON.
- **Read first:** `issue://5906` (the story contract), then the files named in Steps — locate code by SYMBOL NAME (grep), never by line number.
- **Context you may assume:** All prior Stack B stories landed. Every trust-mode feature and test is in place. The B.2 matrix documents every surface's trust-mode behavior. The AGENTS.md Pre-Merge Validation Gate (lines 113-126) defines the required gate commands. `make test-protocol-compliance` does NOT exist; it is dropped from this gate. `normalize_token_teams` lives in `mcpgateway/auth_context.py:246-288`, NOT in `mcpgateway/auth.py` — AGENTS.md currently points at the wrong file.

### Steps
1. Write the failing tests for every "disabled-with-clear-error" row of the B.2 matrix. Create `tests/unit/mcpgateway/test_trust_mode_disabled_surfaces.py`:
   - For each disabled surface documented in the B.2 matrix: trust-only principal hits the surface → documented status code + clear error message, never 500 or IntegrityError.
   - Run. See them fail.
2. Implement any remaining error-path wiring to make the tests pass. If all surfaces already return the documented error (from prior stories), the tests pass immediately.
3. Docs sweep — configuration reference. VERIFY `.env.example`: WO-B.3 added every trust-mode variable and WO-A.6 added `AUTH_CACHE_KEY_VERSION=v1`. Confirm each entry exists and matches the final implementation. Add only entries that are missing:
   - Add `JWT_TRUST_MODE=db` with a comment explaining `"db"` (default, local user lookup) and `"jwt-trust"` (authorize from signed tokens).
   - Add `JWT_CLAIM_USER_ID=sub`, `JWT_CLAIM_EMAIL=email`, `JWT_CLAIM_TEAMS=teams`, `JWT_CLAIM_ROLES=roles`, `JWT_CLAIM_ADMIN=is_admin`.
   - Add `JWT_TRUST_OVERAGE_POLICY=fail_closed` with the three options documented.
   - Add `JWT_REVOCATION_CLAIM=jti` with a note that Entra trust roots may use `uti`.
4. Docs sweep — `docs/docs/manage/configuration.md`: WO-B.3 added the "JWT Trust Mode" section. Review it. Update it to reflect the final implementation: the posture change, the disabled surfaces, and the `POST /admin/tokens/trust` mint endpoint.
5. Docs sweep — `docs/docs/manage/rbac.md`:
   - Add a "Trust Mode" section describing how trust-mode principals get teams and roles from mapped claims, not from DB rows.
6. Docs sweep — `docs/docs/architecture/multitenancy.md`:
   - Add a paragraph describing how `external_group_mappings` enables cross-tenant group-to-team mapping in trust mode.
7. Docs sweep — `docs/docs/architecture/oauth-design.md`:
   - Add a section describing the trust-mode dispatch rule (disjunctive eligibility: gateway-signed OR external IdP), the revocation guarantee (configured revocation claim required), and the overage policy.
8. Docs sweep — `AGENTS.md` Security Invariants section (around line 187). Add these trust-mode invariants:
   - **Dispatch rule:** Trust-mode tokens are eligible when (a) gateway-signed: `token_use=="trusted"` AND trust mode ON AND required mapped claims present AND configured revocation claim present; or (b) external IdP: trust mode ON AND issuer is a configured trust root AND required mapped claims AND configured revocation claim. All other tokens follow the default funnel.
   - **Revocation guarantee:** A trust-eligible token without the configured revocation claim is rejected 401. Revocation is jti-keyed (or uti-keyed if configured); no sid-keyed revocation.
   - **Admin-claim posture:** `is_admin` in trust mode derives from mapped claims, never from a DB row. The admin-claim trust posture is fail-closed: missing admin claim → non-admin.
   - **is_active loss:** Trust-mode principals have no `is_active` DB field. Deactivation is handled at the IdP level (token not issued) or via the revocation blocklist.
9. Fix the AGENTS.md pointer for `normalize_token_teams`. At line 171 and line 194, change `mcpgateway/auth.py` to `mcpgateway/auth_context.py`. The function lives at `auth_context.py:246-288`; `auth.py` merely calls it.
10. Final `.env.example` check: confirm every new setting from step 3 is present, documented, and has a sensible default.
11. Run the full pre-merge validation gate with trust mode OFF (`JWT_TRUST_MODE=db`):
    - `make ruff interrogate pylint` → exit 0.
    - `make test` → exit 0.
    - `make coverage diff-cover` → exit 0.
    - `make detect-secrets-scan` → exit 0.
    - `make docker-nuke docker-prod-rust testing-up RUST_MCP_MODE=` → exit 0.
    - `make test-mcp-protocol-e2e test-mcp-rbac` → exit 0.
12. Run the full pre-merge validation gate with trust mode ON (`JWT_TRUST_MODE=jwt-trust`):
    - Repeat every command from step 11. All must exit 0.
13. Capture evidence: for each gate command in both modes, record the exit code and a short output summary in the PR body.

### Files
- `tests/unit/mcpgateway/test_trust_mode_disabled_surfaces.py` — create.
- `.env.example` — modify (add trust-mode settings).
- `docs/docs/manage/configuration.md` — modify (add JWT Trust Mode section).
- `docs/docs/manage/rbac.md` — modify (add Trust Mode section).
- `docs/docs/architecture/multitenancy.md` — modify (add trust-mode paragraph).
- `docs/docs/architecture/oauth-design.md` — modify (add trust-mode section).
- `AGENTS.md` — modify (add trust-mode invariants, fix `normalize_token_teams` pointer).

### Tests (exact commands)
- Fast gate: `uv run pytest tests/unit/mcpgateway/test_trust_mode_disabled_surfaces.py -q` → pass.
- Full validation gate (trust mode OFF, `JWT_TRUST_MODE=db`):
  - `make ruff interrogate pylint` → exit 0.
  - `make test` → exit 0.
  - `make coverage diff-cover` → exit 0.
  - `make detect-secrets-scan` → exit 0.
  - `make docker-nuke docker-prod-rust testing-up RUST_MCP_MODE=` → exit 0.
  - `make test-mcp-protocol-e2e test-mcp-rbac` → exit 0.
- Full validation gate (trust mode ON, `JWT_TRUST_MODE=jwt-trust`): same commands, all exit 0.
- Expected result: every gate command exits 0 with evidence captured in the PR body.

### Guardrails (do NOT)
- Do not declare done with any gate command red or any B.2 matrix row untested.
- Do not run `make test-protocol-compliance` — it does not exist; it is dropped from this gate.
- Do not weaken any disabled-surface test to a status-code-only check; assert the error message content.
- Do not leave the `normalize_token_teams` AGENTS.md pointer wrong — it must point at `auth_context.py`.

### Done when
- Every B.2 matrix "disabled-with-clear-error" row has an executable test.
- Configuration reference documents all new settings.
- `rbac.md`, `multitenancy.md`, `oauth-design.md` updated with trust-mode sections.
- AGENTS.md Security Invariants lists the four trust-mode invariants.
- AGENTS.md `normalize_token_teams` pointer corrected to `mcpgateway/auth_context.py`.
- `.env.example` final check complete.
- Every gate command exits 0 in both modes, evidence captured in the PR body.

### Commit
`git commit -s` with message: `docs(auth): document JWT-trust mode and complete validation gate`

### PR
- Title: `docs(auth): document JWT-trust mode and complete validation gate`
- Body: State what changed: docs sweep covers configuration reference, rbac.md, multitenancy.md, oauth-design.md, AGENTS.md invariants, and `.env.example`. Fixed the AGENTS.md `normalize_token_teams` pointer (`auth_context.py`, not `auth.py`). Tests cover every disabled-with-clear-error matrix row. State how tested: full validation gate run with trust mode OFF and ON — all commands exit 0. The protocol-compliance target does not exist; it is dropped from this gate. State acceptance met. State risk to existing users: docs only; no behavior change.
- Footer: `Closes #5906`
- Submit: `gh stack submit` (never raw `git push`).

---

## Appendix A — Verified code anchors (as of 2026-09-09, main `13d549371`)

Work orders navigate by symbol. This table records the verified current locations of the seams the issues cite. Re-verify by symbol at execution time.

| Anchor | Current location | Note |
|---|---|---|
| `get_current_user` funnel | `mcpgateway/auth.py` 1385-2151 | file is ~2301 lines |
| plugin hook `HTTP_AUTH_RESOLVE_USER` | `mcpgateway/auth.py` 1553-1674 | |
| UUID-to-email seam | `mcpgateway/auth.py` 1695-1703 | |
| `token_use` dispatch branches | `mcpgateway/auth.py` 1744-1767 / 1820-1842 / 2010-2036 | |
| idle-revoke + revocation | `mcpgateway/auth.py` 1928-2008 | idle handler catches broad `Exception` (~1977-1978) |
| user lookup / is_active | `mcpgateway/auth.py` 2107 / 2139-2144 | |
| platform-admin bootstrap | `mcpgateway/auth.py` 2122-2131 (batched twin 1898-1904) | |
| `validate_token_user` | `mcpgateway/auth.py` 1325 | |
| `_check_token_revoked_sync` | `mcpgateway/auth.py` 768 | |
| revocation INSERT sites | `routers/auth.py:323`, `admin.py:5027`, `token_catalog_service.py:953` (+978-1020), `token_blocklist_service.py:116/131`, `auth.py:1976` | all six re-key in WO-B.9 |
| `normalize_token_teams` | `mcpgateway/auth_context.py` 246-288 | AGENTS.md points at `auth.py` — fixed in WO-B.14 |
| `build_external_identity` | `mcpgateway/utils/verify_credentials.py` def ~2207 | |
| `verify_external_idp_token` | `mcpgateway/utils/verify_credentials.py` | api_audience fail-closed check ~2103-2112 |
| `trusted_for_api_auth` | `SSOProvider` column, `mcpgateway/db.py` 5769 | default False |
| overage detection | `mcpgateway/services/sso_service.py` 1444-1453 | Graph fallback 331-462 is delegated-bearer; B.7 is app-only |
| `sso_entra_graph_api_*` | `mcpgateway/config.py` 551-553 | enabled=True, timeout=10, max_groups=0 |
| admin user CRUD | `mcpgateway/admin.py` 7743-8714 + `routers/email_auth.py` 593-877 | issue cited stale lines |
| session refresh | `POST /auth/refresh`, `routers/auth.py` 538-562 | session-only guard at 561 |
| `create_token` requires EmailUser | `token_catalog_service.py` 456-460 | the WO-B.12 decision point |
| `_check_agent_access` | `mcpgateway/services/a2a_service.py` 471 | 404-not-403; visibility public/team/private (`A2AAgent` db.py 4987) |
| `TokenRevocation.revoked_by` | `mcpgateway/db.py` 5694 | String(255), FK `email_users.email`, NOT NULL |
| `EmailApiToken` CASCADE | `mcpgateway/db.py` 5490 | |
| roles table | `mcpgateway/db.py` ~1167 (`Role`) | `name` has only a partial unique index `(name, scope)` — NOT a valid FK target |
| teams table | `email_teams`, PK `id` String(36) | `cf_team_id` FK target; `cf_role` is a plain validated string |
| alembic head | `12d4a0c7789c` (single) | re-verify before every migration |
| writer sites (exact) | `UserRole(`: role_service ~684 (one). `EmailTeamMember(`: team_management_service two (~1154, ~2144), personal_team_service ~129, team_invitation_service ~411 | AST audit in WO-A.8 enforces |

## Appendix B — Known deviations and follow-ups

- **`cf_role` is not a foreign key.** The `roles.name` partial unique index `(name, scope)` forbids an FK. The plan stores `cf_role` as `String(255)` and validates existence against the `roles` table at write time (400 on unknown role). Issues #5976/#6272 were corrected to match on 2026-09-09.
- **Token catalog in trust mode.** The feature matrix records: DB-backed principals mint tokens normally; trust-only principals get an explicit error. This matches #5904's option (i) fail-closed default.
- **`make test-protocol-compliance` does not exist.** WO-B.14 drops it from the gate.
- **Deferred by design:** `user_id` uniqueness constraint (epic decision D3); periodic group revalidation via the CEL seam (#6408); cpex-plugin mapping mechanism (contextforge-org/cpex#140).
