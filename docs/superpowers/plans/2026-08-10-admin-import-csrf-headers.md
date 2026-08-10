# Admin UI Import Request Headers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the three `/admin/import/*` POST call sites in the Admin UI through the existing `getAuthHeaders()` helper so they attach `X-CSRF-Token` and omit `Authorization` when no bearer token is available, and collapse the duplicate `llmRequestHeaders()` implementation into that same helper.

**Architecture:** No new modules and no new helper. `mcpgateway/admin_ui/auth.js:191` already exports `getAuthHeaders(includeJsonContentType)` with exactly the wanted semantics — optional `Content-Type`, `Authorization` only when the token is truthy, `X-CSRF-Token` from the `mcpgateway_csrf_token` cookie when readable. Three call sites swap their hand-built header object for `await getAuthHeaders(true)`, and `llmModels.js`'s private `llmRequestHeaders()` becomes a thin delegation to it.

**Tech Stack:** Vanilla ES modules (`mcpgateway/admin_ui/*.js`, bundled by Vite), Vitest + jsdom for unit tests (`tests/unit/js/`), `make test-js` / `make build-ui` for verification.

**Spec:** `docs/superpowers/specs/2026-08-10-admin-import-csrf-headers-design.md`
**Issue:** [#5964](https://github.com/IBM/mcp-context-forge/issues/5964)

## Global Constraints

- This change is **defense in depth, not a live 403 fix**. `mcpgateway/templates/admin.html:88-116` wraps `window.fetch` and already injects `X-CSRF-Token` on unsafe same-origin requests, and the empty `Bearer ` token is guarded at every backend layer this route touches. Do not write commit messages or PR text claiming to fix an observed 403.
- Do **not** put the helper in `mcpgateway/admin_ui/utils.js` (which is what the issue text suggests). `utils.js` currently imports nothing, and the helper needs `getAuthToken` from `tokens.js`, which already imports `utils.js` — that placement creates a `utils.js ↔ tokens.js` cycle. Use the existing `auth.js` helper.
- Do **not** touch the `admin.html` fetch wrapper. It stays as the outer safety net.
- Do **not** convert out-of-scope sites: `teams.js` (5 sites), `tokens.js:462`, `llmChat.js`, `fileTransfer.js:41`, `fileTransfer.js:558`. They belong to a follow-up issue.
- No Python is modified by this plan.
- The CSRF cookie name is exactly `mcpgateway_csrf_token` and the header name is exactly `X-CSRF-Token`. Both are hardcoded in `getAuthHeaders`; never introduce a second spelling.
- Sign every commit: `git commit -s` (DCO requirement).
- Never mention AI assistants in commits, PRs, or diffs.

## Background an implementer needs

`getAuthHeaders` in `mcpgateway/admin_ui/auth.js:191-208` is the canonical helper:

```js
export async function getAuthHeaders(includeJsonContentType = false) {
  const headers = {};
  if (includeJsonContentType) {
    headers["Content-Type"] = "application/json";
  }

  const token = await getAuthToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const csrfToken = getCookie("mcpgateway_csrf_token");
  if (csrfToken) {
    headers["X-CSRF-Token"] = csrfToken;
  }

  return headers;
}
```

`auth.js` imports `MASKED_AUTH_VALUE` from `./constants.js`, `getAuthToken` from `./tokens.js`, and `getCookie, safeGetElement, showSuccessMessage, showErrorMessage` from `./utils.js`.

**This is the trap in every task below.** Each test file mocks `utils.js` with a partial factory listing only the two or three names the module under test used to need. The moment the module under test imports `auth.js`, Vitest resolves `auth.js`'s own `utils.js` imports against that same partial mock and throws at module-load time:

```
Error: [vitest] No "showSuccessMessage" export is defined on the "../../../mcpgateway/admin_ui/utils.js" mock.
```

The fix in every case is to spread the real module into the mock factory:

```js
vi.mock("../../../mcpgateway/admin_ui/utils.js", async (importOriginal) => ({
  ...(await importOriginal()),
  showNotification: vi.fn(),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));
```

That also restores the real `getCookie`, which reads jsdom's `document.cookie` — the exact mechanism the new CSRF assertions exercise. `tests/unit/js/admin-llm-csrf.test.js:69-71` already makes this choice deliberately and documents why.

`tokens.js` stays mocked in all three test files, so the pre-existing `auth.js ↔ tokens.js` import cycle never materializes in the test graph.

## Prerequisite: work on a feature branch

The spec and this plan were committed on `main`. Before Task 1, confirm the
implementation work is on its own branch — the repo convention is a `fix/`
prefix (e.g. the recent `fix/global-record-admin-scope`):

```bash
git rev-parse --abbrev-ref HEAD          # if this prints "main", branch first
git switch -c fix/admin-import-csrf-headers
```

Task 4 Step 5 compares against `main...HEAD`, which is empty and therefore
useless if the work itself lands on `main`.

## File Structure

| File | Change | Responsibility after the change |
|------|--------|----------------------------------|
| `mcpgateway/admin_ui/fileTransfer.js` | Modify (imports, `:342-352`, `:398-408`) | Export/import UI actions. Two POST sites use `getAuthHeaders(true)`; the two GET sites at `:41` and `:558` keep `getAuthToken` untouched, so the `tokens.js` import stays. |
| `mcpgateway/admin_ui/selectiveImport.js` | Modify (imports, `:288-298`) | Selective-import UI actions. Its single POST site uses `getAuthHeaders(true)`; the now-unused `getAuthToken` import is removed. |
| `mcpgateway/admin_ui/llmModels.js` | Modify (imports, `:18-32`) | LLM settings UI. `llmRequestHeaders({ json })` keeps its signature and all 16 call sites, but delegates to `getAuthHeaders`; the now-unused `getAuthToken` and `getCookie` imports are removed. |
| `tests/unit/js/fileTransfer.test.js` | Modify (mock factory + new describe block) | Covers header shape for `previewImport` and `handleImport`. |
| `tests/unit/js/selectiveImport.test.js` | Modify (mock factory + new describe block) | Covers header shape for `handleSelectiveImport`. |
| `tests/unit/js/llmModels.test.js` | Modify (mock factory only) | Existing behavior coverage; only needs to survive the new `auth.js` edge. |

No files are created. No files are deleted.

---

### Task 1: Route `fileTransfer.js` import POSTs through `getAuthHeaders`

**Files:**
- Modify: `mcpgateway/admin_ui/fileTransfer.js:1-5` (imports), `:342-352` (`previewImport`), `:398-408` (`handleImport`)
- Test: `tests/unit/js/fileTransfer.test.js:52-55` (mock factory), plus a new describe block appended to the end of the file

**Interfaces:**
- Consumes: `getAuthHeaders(includeJsonContentType?: boolean): Promise<Record<string, string>>` from `mcpgateway/admin_ui/auth.js`
- Produces: nothing new. `previewImport()` and `handleImport(dryRun)` keep their existing exported signatures.

- [ ] **Step 1: Widen the `utils.js` mock factory so `auth.js` can load**

In `tests/unit/js/fileTransfer.test.js`, replace this block (currently at lines 52-55):

```js
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  showNotification: vi.fn(),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));
```

with:

```js
vi.mock("../../../mcpgateway/admin_ui/utils.js", async (importOriginal) => ({
  ...(await importOriginal()),
  showNotification: vi.fn(),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));
```

This keeps the two stubs the existing tests assert against while exposing the
real `getCookie`, `showSuccessMessage`, and `showErrorMessage` that `auth.js`
imports.

- [ ] **Step 2: Write the failing tests**

Append this block to the end of `tests/unit/js/fileTransfer.test.js`:

```js
// ---------------------------------------------------------------------------
// Request headers for /admin/import/* writes (issue #5964)
// ---------------------------------------------------------------------------
describe("import request headers", () => {
  const CSRF_COOKIE_VALUE = "test-csrf-value";

  function setCsrfCookie(value = CSRF_COOKIE_VALUE) {
    document.cookie = `mcpgateway_csrf_token=${value}`;
  }

  function clearCsrfCookie() {
    // jsdom has no wildcard clear; expire the single cookie we set.
    document.cookie = "mcpgateway_csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  }

  let fetchSpy;

  beforeEach(() => {
    window.ROOT_PATH = "";
    window.currentImportData = { version: "1.0", entities: {} };
    // updateImportCounts() (fileTransfer.js:464-467) dereferences these four
    // elements WITHOUT a null guard, so handleImport's success path throws
    // into its own catch block without them. Every other DOM lookup on this
    // path is guarded.
    document.body.innerHTML = `
      <span id="import-total"></span>
      <span id="import-created"></span>
      <span id="import-updated"></span>
      <span id="import-failed"></span>
    `;
    fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          preview: {},
          status: "completed",
          progress: { total: 0, processed: 0, created: 0, updated: 0, failed: 0 },
          errors: [],
          warnings: [],
        }),
    });
  });

  afterEach(() => {
    clearCsrfCookie();
    fetchSpy.mockRestore();
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.currentImportData;
    vi.clearAllMocks();
  });

  test("previewImport sends X-CSRF-Token from the cookie", async () => {
    setCsrfCookie();

    await previewImport();

    const headers = fetchSpy.mock.calls[0][1].headers;
    expect(headers["X-CSRF-Token"]).toBe(CSRF_COOKIE_VALUE);
    expect(headers["Content-Type"]).toBe("application/json");
  });

  test("previewImport omits X-CSRF-Token when no cookie is set", async () => {
    clearCsrfCookie();

    await previewImport();

    const headers = fetchSpy.mock.calls[0][1].headers;
    expect(headers).not.toHaveProperty("X-CSRF-Token");
  });

  test("previewImport omits Authorization when no bearer token is available", async () => {
    setCsrfCookie();
    getAuthToken.mockResolvedValueOnce("");

    await previewImport();

    const headers = fetchSpy.mock.calls[0][1].headers;
    expect(headers).not.toHaveProperty("Authorization");
    expect(headers["X-CSRF-Token"]).toBe(CSRF_COOKIE_VALUE);
  });

  test("previewImport sends Authorization when a bearer token is available", async () => {
    setCsrfCookie();

    await previewImport();

    const headers = fetchSpy.mock.calls[0][1].headers;
    expect(headers.Authorization).toBe("Bearer test-token");
  });

  test("handleImport sends X-CSRF-Token and Content-Type", async () => {
    setCsrfCookie();

    await handleImport(true);

    const headers = fetchSpy.mock.calls[0][1].headers;
    expect(headers["X-CSRF-Token"]).toBe(CSRF_COOKIE_VALUE);
    expect(headers["Content-Type"]).toBe("application/json");
  });

  test("handleImport omits Authorization when no bearer token is available", async () => {
    setCsrfCookie();
    getAuthToken.mockResolvedValueOnce("");

    await handleImport(true);

    const headers = fetchSpy.mock.calls[0][1].headers;
    expect(headers).not.toHaveProperty("Authorization");
  });
});
```

`getAuthToken` is already imported into this test file at line 31 and is the
`vi.fn()` from the `tokens.js` mock factory, so `mockResolvedValueOnce` works
directly on it. The real `getAuthHeaders` in `auth.js` calls that same mocked
function.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `npx vitest run tests/unit/js/fileTransfer.test.js -t "import request headers"`

Expected: the four `X-CSRF-Token` / `Authorization`-absent assertions FAIL —
`expected undefined to be 'test-csrf-value'` and
`expected { ... Authorization: 'Bearer ' } not to have property "Authorization"`.
The `Content-Type` and `Bearer test-token` assertions already pass.

- [ ] **Step 4: Add the `auth.js` import**

In `mcpgateway/admin_ui/fileTransfer.js`, change the import block at lines 1-5
from:

```js
import { escapeHtml } from "./security.js";
import { displayImportPreview } from "./selectiveImport.js";
import { getAuthToken } from "./tokens.js";
import { loadTools } from "./tools.js";
import { showNotification, safeGetElement } from "./utils.js";
```

to:

```js
import { getAuthHeaders } from "./auth.js";
import { escapeHtml } from "./security.js";
import { displayImportPreview } from "./selectiveImport.js";
import { getAuthToken } from "./tokens.js";
import { loadTools } from "./tools.js";
import { showNotification, safeGetElement } from "./utils.js";
```

Keep the `getAuthToken` import — `handleExportAll` (line 41) and
`loadRecentImports` (line 558) still use it and are out of scope.

- [ ] **Step 5: Convert the `previewImport` call site**

In `previewImport`, replace:

```js
    const response = await fetch(
      (window.ROOT_PATH || "") + "/admin/import/preview",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${await getAuthToken()}`,
        },
        body: JSON.stringify({ data: window.currentImportData }),
      },
    );
```

with:

```js
    const response = await fetch(
      (window.ROOT_PATH || "") + "/admin/import/preview",
      {
        method: "POST",
        headers: await getAuthHeaders(true),
        body: JSON.stringify({ data: window.currentImportData }),
      },
    );
```

- [ ] **Step 6: Convert the `handleImport` call site**

In `handleImport`, replace:

```js
    const response = await fetch(
      (window.ROOT_PATH || "") + "/admin/import/configuration",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${await getAuthToken()}`,
        },
        body: JSON.stringify(requestData),
      },
    );
```

with:

```js
    const response = await fetch(
      (window.ROOT_PATH || "") + "/admin/import/configuration",
      {
        method: "POST",
        headers: await getAuthHeaders(true),
        body: JSON.stringify(requestData),
      },
    );
```

- [ ] **Step 7: Run the new tests to verify they pass**

Run: `npx vitest run tests/unit/js/fileTransfer.test.js -t "import request headers"`

Expected: all 6 tests PASS.

- [ ] **Step 8: Run the whole file to confirm no regression**

Run: `npx vitest run tests/unit/js/fileTransfer.test.js`

Expected: every test PASSES, including the pre-existing
`expect.objectContaining` header assertions at lines 150, 809, and 1365 — the
first and last cover GET sites that were not touched, and the middle one still
sees `Authorization: "Bearer test-token"` because `getAuthToken` is mocked to
return a token by default.

- [ ] **Step 9: Commit**

```bash
git add mcpgateway/admin_ui/fileTransfer.js tests/unit/js/fileTransfer.test.js
git commit -s -m "fix(admin-ui): attach CSRF header to import preview and configuration writes

previewImport and handleImport built request headers by hand: no
X-CSRF-Token, and an unconditional Authorization header that becomes a
malformed 'Bearer ' for session-cookie logins where getAuthToken()
returns an empty string. Route both through the existing getAuthHeaders()
helper, which attaches the CSRF token and omits Authorization when no
bearer token is readable.

Refs #5964"
```

---

### Task 2: Route `selectiveImport.js` import POST through `getAuthHeaders`

**Files:**
- Modify: `mcpgateway/admin_ui/selectiveImport.js:6` (import), `:288-298` (`handleSelectiveImport`)
- Test: `tests/unit/js/selectiveImport.test.js:33-36` (mock factory), `:30-32` (tokens mock), plus a new describe block appended to the end of the file

**Interfaces:**
- Consumes: `getAuthHeaders(includeJsonContentType?: boolean): Promise<Record<string, string>>` from `mcpgateway/admin_ui/auth.js`
- Produces: nothing new. `handleSelectiveImport(dryRun)` keeps its existing exported signature.

- [ ] **Step 1: Widen the `utils.js` mock factory so `auth.js` can load**

In `tests/unit/js/selectiveImport.test.js`, replace this block (currently at
lines 33-36):

```js
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showNotification: vi.fn(),
}));
```

with:

```js
vi.mock("../../../mcpgateway/admin_ui/utils.js", async (importOriginal) => ({
  ...(await importOriginal()),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showNotification: vi.fn(),
}));
```

- [ ] **Step 2: Import `beforeEach` and expose the mocked `getAuthToken`**

Line 7 of this file imports `{ describe, test, expect, vi, afterEach }` — no
`beforeEach`. `vitest.config.js` sets `globals: true`, so the bare identifier
would resolve anyway, but the file's style is explicit imports. Change line 7
to:

```js
import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
```


Then handle the `getAuthToken` override. The `tokens.js` mock at lines 30-32 is
never imported into the test body, so there is no handle to override it
per-test. Replace:

```js
vi.mock("../../../mcpgateway/admin_ui/tokens.js", () => ({
  getAuthToken: vi.fn().mockResolvedValue("test-token"),
}));
```

with:

```js
vi.mock("../../../mcpgateway/admin_ui/tokens.js", () => ({
  getAuthToken: vi.fn().mockResolvedValue("test-token"),
}));

// Handle for per-test overrides (e.g. the httponly session-cookie case where
// getAuthToken() resolves to "").
import { getAuthToken } from "../../../mcpgateway/admin_ui/tokens.js";
```

Vitest hoists `vi.mock` above imports, so the import placement below the factory
is safe and keeps the mock and its handle adjacent.

- [ ] **Step 3: Write the failing tests**

Append this block to the end of `tests/unit/js/selectiveImport.test.js`:

```js
// ---------------------------------------------------------------------------
// Request headers for /admin/import/configuration writes (issue #5964)
// ---------------------------------------------------------------------------
describe("selective import request headers", () => {
  const CSRF_COOKIE_VALUE = "test-csrf-value";

  function setCsrfCookie(value = CSRF_COOKIE_VALUE) {
    document.cookie = `mcpgateway_csrf_token=${value}`;
  }

  function clearCsrfCookie() {
    document.cookie = "mcpgateway_csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  }

  let fetchSpy;

  beforeEach(() => {
    window.ROOT_PATH = "";
    window.Admin = { currentImportData: { tools: [] } };
    // addCheckboxes() appends UNCHECKED boxes; collectUserSelections() then
    // returns {} and handleSelectiveImport bails out before fetch. Check one,
    // matching the existing "sends import request when items are selected"
    // test at line 227.
    const { item1 } = addCheckboxes();
    item1.checked = true;
    fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: "ok" }),
    });
  });

  afterEach(() => {
    clearCsrfCookie();
    fetchSpy.mockRestore();
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.Admin;
    vi.clearAllMocks();
  });

  test("sends X-CSRF-Token from the cookie", async () => {
    setCsrfCookie();

    await handleSelectiveImport(true);

    const headers = fetchSpy.mock.calls[0][1].headers;
    expect(headers["X-CSRF-Token"]).toBe(CSRF_COOKIE_VALUE);
    expect(headers["Content-Type"]).toBe("application/json");
  });

  test("omits X-CSRF-Token when no cookie is set", async () => {
    clearCsrfCookie();

    await handleSelectiveImport(true);

    const headers = fetchSpy.mock.calls[0][1].headers;
    expect(headers).not.toHaveProperty("X-CSRF-Token");
  });

  test("omits Authorization when no bearer token is available", async () => {
    setCsrfCookie();
    getAuthToken.mockResolvedValueOnce("");

    await handleSelectiveImport(true);

    const headers = fetchSpy.mock.calls[0][1].headers;
    expect(headers).not.toHaveProperty("Authorization");
    expect(headers["X-CSRF-Token"]).toBe(CSRF_COOKIE_VALUE);
  });

  test("sends Authorization when a bearer token is available", async () => {
    setCsrfCookie();

    await handleSelectiveImport(true);

    const headers = fetchSpy.mock.calls[0][1].headers;
    expect(headers.Authorization).toBe("Bearer test-token");
  });
});
```

`addCheckboxes()` is the existing helper at line 39 of this test file. It
returns `{ gw1, gw2, item1, item2 }` and leaves every box **unchecked**;
`handleSelectiveImport` calls `collectUserSelections()` and returns early with a
"select at least one item" warning when the result is empty, so `item1.checked =
true` is mandatory or `fetch` is never reached.

- [ ] **Step 4: Run the tests to verify they fail**

Run: `npx vitest run tests/unit/js/selectiveImport.test.js -t "selective import request headers"`

Expected: the `X-CSRF-Token` and `Authorization`-absent assertions FAIL. If
instead every test errors with "fetch was not called", fix the checkbox setup
per the note in Step 3 before continuing — a test that never reaches `fetch`
proves nothing.

- [ ] **Step 5: Swap the import**

In `mcpgateway/admin_ui/selectiveImport.js`, replace line 6:

```js
import { getAuthToken } from "./tokens.js";
```

with:

```js
import { getAuthHeaders } from "./auth.js";
```

`getAuthToken` has exactly one use in this module (the call site converted in
Step 6), so leaving the import would be dead code.

- [ ] **Step 6: Convert the call site**

In `handleSelectiveImport`, replace:

```js
    const response = await fetch(
      (window.ROOT_PATH || "") + "/admin/import/configuration",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${await getAuthToken()}`,
        },
        body: JSON.stringify(requestData),
      }
    );
```

with:

```js
    const response = await fetch(
      (window.ROOT_PATH || "") + "/admin/import/configuration",
      {
        method: "POST",
        headers: await getAuthHeaders(true),
        body: JSON.stringify(requestData),
      }
    );
```

- [ ] **Step 7: Run the new tests to verify they pass**

Run: `npx vitest run tests/unit/js/selectiveImport.test.js -t "selective import request headers"`

Expected: all 4 tests PASS.

- [ ] **Step 8: Run both affected files to confirm no regression**

Run: `npx vitest run tests/unit/js/selectiveImport.test.js tests/unit/js/fileTransfer.test.js`

Expected: every test PASSES. `fileTransfer.test.js` is included because
`selectiveImport.js` and `fileTransfer.js` import each other, so a broken mock
graph in one surfaces in the other.

- [ ] **Step 9: Commit**

```bash
git add mcpgateway/admin_ui/selectiveImport.js tests/unit/js/selectiveImport.test.js
git commit -s -m "fix(admin-ui): attach CSRF header to selective import writes

handleSelectiveImport built its request headers by hand, omitting
X-CSRF-Token and sending a malformed 'Bearer ' Authorization header for
session-cookie logins. Route it through getAuthHeaders(), which is the
same helper the rest of the Admin UI already uses.

Refs #5964"
```

---

### Task 3: Collapse `llmRequestHeaders` into `getAuthHeaders`

**Files:**
- Modify: `mcpgateway/admin_ui/llmModels.js:1-32` (imports and helper)
- Test: `tests/unit/js/llmModels.test.js:59-63` (mock factory)

**Interfaces:**
- Consumes: `getAuthHeaders(includeJsonContentType?: boolean): Promise<Record<string, string>>` from `mcpgateway/admin_ui/auth.js`
- Produces: `llmRequestHeaders({ json = true } = {}): Promise<Record<string, string>>` — unchanged private signature, still called from 16 sites inside `llmModels.js` (lines 101, 208, 375, 417, 455, 571, 614, 643, 667, 737, 813, 855, 933, 968, 996, 1111). Do not change the option shape; changing it would touch all 16 sites for no benefit.

- [ ] **Step 1: Widen the `utils.js` mock factory so `auth.js` can load**

In `tests/unit/js/llmModels.test.js`, replace this block (currently at lines
59-63):

```js
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showToast: vi.fn(),
  getCookie: vi.fn(() => ""),
}));
```

with:

```js
vi.mock("../../../mcpgateway/admin_ui/utils.js", async (importOriginal) => ({
  ...(await importOriginal()),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showToast: vi.fn(),
  getCookie: vi.fn(() => ""),
}));
```

The `getCookie` stub returning `""` is kept deliberately: these tests assert
LLM behavior, not CSRF headers, and a no-cookie environment is what they were
written against. CSRF coverage for this module already lives in
`tests/unit/js/admin-llm-csrf.test.js`, which does not mock `utils.js` at all.

- [ ] **Step 2: Run the LLM test files to establish a green baseline**

Run: `npx vitest run tests/unit/js/llmModels.test.js tests/unit/js/admin-llm-csrf.test.js`

Expected: all tests PASS. This is a refactor with existing coverage — record
the passing counts so Step 5 can be compared against them.

- [ ] **Step 3: Replace the helper body with a delegation**

In `mcpgateway/admin_ui/llmModels.js`, replace lines 1-32:

```js
import { AppState } from "./appState.js";
import { showCopyableModal } from "./modals.js";
import { parseErrorResponse } from "./security.js";
import { getAuthToken } from "./tokens.js";
import { getCookie, safeGetElement, showToast } from "./utils.js";

// ===================================================================
// LLM SETTINGS FUNCTIONS
// ===================================================================

/**
 * Build headers for state-changing LLM settings requests.
 * - Authorization is only attached when a real bearer token is available
 *   (session logins use an httponly cookie, so getAuthToken() returns "").
 * - X-CSRF-Token satisfies both CSRFMiddleware (/llm/*) and
 *   enforce_admin_csrf (/admin/llm/*), which share the same cookie/header names.
 */
async function llmRequestHeaders({ json = true } = {}) {
  const headers = {};
  if (json) {
    headers["Content-Type"] = "application/json";
  }
  const token = await getAuthToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const csrfToken = getCookie("mcpgateway_csrf_token");
  if (csrfToken) {
    headers["X-CSRF-Token"] = csrfToken;
  }
  return headers;
}
```

with:

```js
import { AppState } from "./appState.js";
import { getAuthHeaders } from "./auth.js";
import { showCopyableModal } from "./modals.js";
import { parseErrorResponse } from "./security.js";
import { safeGetElement, showToast } from "./utils.js";

// ===================================================================
// LLM SETTINGS FUNCTIONS
// ===================================================================

/**
 * Build headers for state-changing LLM settings requests.
 *
 * Thin adapter over the shared getAuthHeaders() helper, kept so the 16 call
 * sites below can keep their `{ json: false }` option shape:
 * - Authorization is only attached when a real bearer token is available
 *   (session logins use an httponly cookie, so getAuthToken() returns "").
 * - X-CSRF-Token satisfies both CSRFMiddleware (/llm/*) and
 *   enforce_admin_csrf (/admin/llm/*), which share the same cookie/header names.
 */
async function llmRequestHeaders({ json = true } = {}) {
  return getAuthHeaders(json);
}
```

Both the `getAuthToken` and `getCookie` imports become unused once the body is
delegated — that is why they are dropped from the import block.

- [ ] **Step 4: Verify no stale references remain**

Run: `grep -n "getAuthToken\|getCookie" mcpgateway/admin_ui/llmModels.js`

Expected: only the two mentions inside the JSDoc comment. Zero code references.
If a code reference appears, it is a call site that was missed — convert it to
`llmRequestHeaders` rather than re-adding the import.

- [ ] **Step 5: Run the LLM test files to verify behavior is unchanged**

Run: `npx vitest run tests/unit/js/llmModels.test.js tests/unit/js/admin-llm-csrf.test.js`

Expected: the same passing counts as Step 2, zero failures.
`admin-llm-csrf.test.js` is the real proof here: it exercises the CSRF header
behavior through the public functions, so it fails loudly if the delegation
changed semantics.

- [ ] **Step 6: Commit**

```bash
git add mcpgateway/admin_ui/llmModels.js tests/unit/js/llmModels.test.js
git commit -s -m "refactor(admin-ui): delegate llmRequestHeaders to the shared helper

llmRequestHeaders() was a byte-equivalent reimplementation of
getAuthHeaders() in auth.js, differing only in its option shape. Keep the
option shape for the 16 internal call sites and delegate the body, so
there is one canonical header builder in the Admin UI.

Refs #5964"
```

---

### Task 4: Full verification gate

**Files:**
- Modify: none (verification only; fix-ups land in whichever file fails)

**Interfaces:**
- Consumes: the converted call sites from Tasks 1-3
- Produces: nothing

- [ ] **Step 1: Run the whole JS suite**

Run: `make test-js`

Expected: the full Vitest run PASSES. If a test file unrelated to this change
fails, check whether it mocks `utils.js` with a partial factory and imports a
module that now reaches `auth.js` — that is the same trap described in the
Background section, and the same `importOriginal` spread fixes it.

- [ ] **Step 2: Confirm the Admin UI bundle still builds**

Run: `make build-ui`

Expected: the Vite build succeeds with no unresolved-import errors. This is the
check that catches a wrong relative path or a circular-import regression that
Vitest's mocked graph would hide.

- [ ] **Step 3: Confirm no out-of-scope site was converted**

Run: `grep -rn 'Authorization: \`Bearer \${await getAuthToken()}\`' mcpgateway/admin_ui/`

Expected: exactly 8 hits, down from 11 before this work, all out of scope —
`fileTransfer.js:41`, `fileTransfer.js:558`, `teams.js` (5 sites),
`tokens.js:462`. Zero hits in `selectiveImport.js`. `llmChat.js` does not match
this pattern (it interpolates a local `jwtToken` variable, not
`await getAuthToken()`), so it must not appear.

- [ ] **Step 4: Run the repo's pre-commit hygiene chain**

Run: `make pre-commit`

Expected: PASS. This normalizes whitespace and trailing newlines across the
touched JS files.

Watch for one false positive: the `detect-secrets` hook raises `Secret Keyword`
on an assignment whose left-hand side is a credential-ish word (`credentials`,
`token`, `secret`, `password`) and whose right-hand side is a quoted string
literal. The new tests can trip this if a header value is written that way. Per
the repo convention in
`CLAUDE.md`, Python files take an inline `# pragma: allowlist secret` and every
other file type is handled by regenerating the baseline with
`make detect-secrets-scan`. For a JS test, prefer rewording the literal (e.g.
assert on a constant named `CSRF_COOKIE_VALUE`, which the plan's tests already
do) over adding a baseline entry.

If `make pre-commit` rewrites files, amend the affected commit rather than
adding a fixup:

```bash
git add -A && git commit -s --amend --no-edit
```

- [ ] **Step 5: Confirm no Python was touched**

Run: `git diff --name-only main...HEAD -- '*.py'`

Expected: empty output. This change is JS-only by design; a Python file in the
diff means scope drift and needs to be justified or reverted.

---

## Notes for the PR description

- Link the issue with `Closes #5964`.
- State plainly that the change is defense in depth: the `admin.html` fetch
  wrapper and the backend's empty-token guards mean no live 403 was reproducible
  at these call sites. Do not claim a fixed outage.
- Mention the out-of-scope sites (`teams.js`, `tokens.js:462`, `llmChat.js`,
  the two `fileTransfer.js` GET sites) and that they warrant a follow-up issue.
- No test plans or effort estimates in the PR body (repo convention).
