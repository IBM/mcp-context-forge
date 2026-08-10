# Admin UI import request headers — design

**Issue:** [#5964](https://github.com/IBM/mcp-context-forge/issues/5964) — "Import/export config writes vulnerable to same missing-CSRF-header pattern as #5739"
**Related:** #5739, #5780 (`0d6aef010`)
**Date:** 2026-08-10

## Problem

Three Admin UI call sites build request headers by hand:

| File | Line | Request |
|------|------|---------|
| `mcpgateway/admin_ui/selectiveImport.js` | 288-298 | `POST /admin/import/configuration` |
| `mcpgateway/admin_ui/fileTransfer.js` | 342-352 | `POST /admin/import/preview` |
| `mcpgateway/admin_ui/fileTransfer.js` | 398-408 | `POST /admin/import/configuration` |

All three do:

```js
headers: {
  "Content-Type": "application/json",
  Authorization: `Bearer ${await getAuthToken()}`,
},
```

Two defects in that shape:

1. No `X-CSRF-Token` header. `/admin/*` routes enforce CSRF through the per-route
   `enforce_admin_csrf` dependency (`mcpgateway/admin.py:1845`, wired at
   `admin.py:1892`), which does a double-submit comparison of the
   `mcpgateway_csrf_token` cookie against the `x-csrf-token` header and raises
   403 when the header is absent.
2. `Authorization` is set unconditionally. Session-cookie logins have no
   JS-readable bearer token, so `getAuthToken()` returns `""` and the request
   carries a malformed `Authorization: Bearer ` header instead of omitting it.

## Current runtime impact: latent, not a live 403

The issue reports live CSRF 403s. Investigation shows neither defect is
reachable through the shipped Admin UI today. Both are masked:

**CSRF header is injected by a template-level `fetch` monkey patch.**
`mcpgateway/templates/admin.html:88-116` wraps `window.fetch` and, for unsafe
same-origin methods, sets `X-CSRF-Token` from the `mcpgateway_csrf_token` cookie
(non-httponly, so JS-readable). All three call sites use relative URLs and
`method: "POST"`, so the wrapper fires and the header lands. The wrapper only
sets `Authorization` when the header is *not already present* — so it does not
repair the malformed value, but it does supply the CSRF header.

**The empty bearer token is guarded at every layer on this route's path.**

- `ConfigurableHTTPBearer` is constructed with `auto_error=False`
  (`mcpgateway/utils/verify_credentials.py:223`, `mcpgateway/middleware/rbac.py:139`),
  so `Bearer ` yields `HTTPAuthorizationCredentials(credentials="")` rather than a 403.
- `get_current_user_with_permissions` gates on truthiness:
  `if credentials and credentials.credentials` (`mcpgateway/middleware/rbac.py:424`),
  so it falls through to the `jwt_token` cookie.
- `AuthContextMiddleware` reads cookies first and gates the header branch on
  `if scheme.lower() == "bearer" and credentials_value`
  (`mcpgateway/middleware/auth_middleware.py:150-160`).
- The header-first resolver in `verify_credentials.py:1602-1603` gates on
  `if scheme.lower() == "bearer" and param`.

So this change is **defense in depth**, not a live bug fix. It is still worth
making:

- The `fetch` wrapper is an inline script in one template. Any code path that
  does not execute inside a rendered `admin.html` — unit tests, a future
  extraction of these modules, a different host page — loses the header
  silently.
- The wrapper no-ops when neither the CSRF nor the JWT cookie is readable.
- A malformed `Authorization` header is a latent trap: any future auth path that
  treats "header present" as "header authoritative" turns it into a 401.

The spec deliberately does not claim to fix an observed 403.

## Design

### 1. Reuse the existing shared helper

The issue proposes extracting `llmRequestHeaders()` from `llmModels.js` into
`utils.js`. Two corrections:

- An equivalent helper already exists: `getAuthHeaders(includeJsonContentType)`
  at `mcpgateway/admin_ui/auth.js:191-208`. It applies exactly the wanted
  semantics — optional `Content-Type`, `Authorization` only when the token is
  truthy, `X-CSRF-Token` from `getCookie("mcpgateway_csrf_token")` when present.
  It is already consumed by `a2aAgents.js:841`, `auth.js:412`, and
  `tokens.js:652,685`.
- `utils.js` is the wrong home. It currently imports nothing, and the helper
  needs `getAuthToken` from `tokens.js`, which already imports `utils.js`. Adding
  it there introduces a `utils.js ↔ tokens.js` cycle.

So: no new helper, no new module. Route the call sites through
`getAuthHeaders(true)`.

### 2. Convert the three call sites

Each becomes:

```js
const response = await fetch(url, {
  method: "POST",
  headers: await getAuthHeaders(true),
  body: JSON.stringify(requestData),
});
```

with `import { getAuthHeaders } from "./auth.js";` added. Remove the
`getAuthToken` import from a module only if no other site in that module still
uses it — `fileTransfer.js` retains it at lines 41 and 558 (both GET, out of
scope), so its import stays.

### 3. Collapse the duplicate helper

`llmRequestHeaders()` (`mcpgateway/admin_ui/llmModels.js:18-32`) is a
byte-equivalent reimplementation of `getAuthHeaders`, differing only in the
option shape (`{ json = true }` vs a positional boolean). Replace its body with a
delegation to `getAuthHeaders`, keeping the existing call signature so the
module's internal call sites and `tests/unit/js/admin-llm-csrf.test.js` are
unaffected. This leaves one canonical implementation, which is what the issue
actually asks for.

### 4. Tests — JS unit only

Home: `tests/unit/js/`, following `admin-llm-csrf.test.js`.

Existing tests assert the exact header object and will fail:

- `tests/unit/js/fileTransfer.test.js` — `previewImport` (~line 803) and
  `handleImport` header assertions
- `tests/unit/js/selectiveImport.test.js` — `handleSelectiveImport` assertions

Update those, and add per-site coverage:

- `X-CSRF-Token` equals the `mcpgateway_csrf_token` cookie value when the cookie
  is set
- `Authorization` is **absent** from the header object when `getAuthToken()`
  resolves to `""`
- `Authorization` is `Bearer <token>` when a token is available
- `Content-Type: application/json` is retained

No backend test. The backend enforcement path (`enforce_admin_csrf`) is already
covered by `tests/unit/mcpgateway/middleware/test_admin_csrf_binding.py`, and
this change touches no Python.

## Scope

**In scope:** the three call sites named in the issue, plus the
`llmRequestHeaders` deduplication, plus the JS unit tests above.

**Out of scope** (same manual-header pattern, deserves a follow-up issue):

- `mcpgateway/admin_ui/teams.js` — 5 POST sites (222, 358, 414, 468, 524)
- `mcpgateway/admin_ui/tokens.js:462`
- `mcpgateway/admin_ui/llmChat.js`
- `mcpgateway/admin_ui/fileTransfer.js:41,558` — GET requests; CSRF is not
  applicable and `enforce_admin_csrf` short-circuits on safe methods, but the
  unconditional `Authorization` is the same latent trap

**Not changed:** the `admin.html` `fetch` wrapper stays as the outer safety net.
Removing it is a separate decision with a much wider blast radius.

## Verification

- `make test-js` (vitest) green, including the updated `fileTransfer.test.js`,
  `selectiveImport.test.js`, and `admin-llm-csrf.test.js`
- `make build-ui` succeeds (the Admin UI bundle rebuilds cleanly)
- No Python touched, so the Python gates are unaffected; run `make pre-commit`
  for formatting/lint hygiene on the JS
