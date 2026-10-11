# ADR-0056: CSP Hardening — No eval, No Inline Handlers, Nonce-Only Scripts

- _Status:_ Accepted
- _Date:_ 2026-10-01
- _Deciders:_ Core Engineering Team
- _Supersedes:_ [ADR-0014](014-security-headers-cors-middleware.md)
- _Issues:_ [#1110](https://github.ibm.com/contextforge-org/internal_issues/issues/1110)
- _Related:_ [PR #7076](https://github.com/IBM/mcp-context-forge/pull/7076)

## Context

ADR-0014 established the `SecurityHeadersMiddleware` and documented several trade-offs in the initial
Content Security Policy, including `'unsafe-inline'` in `script-src` and `'unsafe-eval'` in
`script-src` to support HTMX `hx-vals="js:{...}"` and `hx-on:*` attribute evaluation:

```
"'unsafe-eval'": Still required — HTMX evaluates hx-vals="js:{...}" and hx-on:* attributes
via htmx.config.allowEval. Tracked in issue #4655.
```

This left two attack surfaces:

1. **`on*` handler injection**: A crafted redirect link (`/admin?error=<payload>`) could reach
   `innerHTML` and execute code if the old flash-banner rendered user-controlled text directly.
   `script-src-attr 'unsafe-inline'` permitted that execution path.
2. **HTMX code evaluation**: `htmx.config.allowEval = true` (the library default) allowed
   injected `hx-vals="js:{...}"`, `hx-vars`, and trigger-filter expressions to reach `eval`.

Both issues were mitigated by other controls at the time (no user text in flash banners, input
validation), but a defence-in-depth gap remained: removing either mitigation could silently open
an XSS path. This ADR closes that gap at the CSP and JS configuration layers.

## Decision

### 1. Disable HTMX code evaluation

Set `htmx.config.allowEval = false` in `mcpgateway/admin_ui/admin.js` immediately after the
existing `inlineScriptNonce` configuration:

```js
// Injected markup must not reach htmx code evaluation (hx-on, hx-vals="js:", hx-vars, trigger filters).
htmx.config.allowEval = false;
```

All `hx-vals="js:{...}"` usages have been migrated to `htmx:configRequest` event handlers.
All `hx-on:*` attributes have been migrated to `addEventListener` calls.

### 2. Change `script-src-attr` from `'unsafe-inline'` to `'none'`

Update `mcpgateway/middleware/security_headers.py`:

```python
# Before (ADR-0014):
"script-src-attr 'unsafe-inline'",

# After (ADR-0056):
"script-src-attr 'none'",
```

This directive governs inline `on*` event-handler attributes (`onclick=`, `onload=`, etc.).
Setting it to `'none'` means injected markup can never become script execution, regardless of
what reaches `innerHTML`.

### 3. Replace the hand-rolled HTML sanitizer with DOMPurify

The previous `sanitizeHtmlForInsertion()` in `mcpgateway/admin_ui/security.js` used a manual
`<template>` walk. That walk was correct but did not handle all mXSS re-serialisation patterns.

Replace it with a DOMPurify call using a guard config that:

- Keeps htmx, Alpine, data-*, and aria-* attributes the UI depends on.
- Removes all `hx-on*` / `data-hx-on*` attributes via a `uponSanitizeAttribute` hook (these
  are the attributes HTMX would evaluate as code if `allowEval` were re-enabled).
- Forbids `<iframe>`, `<object>`, `<embed>`, `<meta>`, and `<base>`.
- Uses `FORCE_BODY` to prevent `<template>` / `<style>` hoisting.

The hook is global, so it also covers any other caller of `window.DOMPurify`.

### 4. Replace user-controlled flash-banner text with a server-side code allowlist

The admin redirect helpers now emit opaque error codes (`permission_denied`, `conflict`, etc.)
instead of user-visible exception strings. The flash-banner IIFE in `admin.html` maps those
codes to display text through a hardcoded `ERROR_MESSAGES` / `INFO_MESSAGES` lookup:

```js
const ERROR_MESSAGES = {
  permission_denied: 'You do not have permission to perform this action.',
  conflict: 'This item is being modified by another request. Please try again.',
  // … all codes …
};
text.textContent = `❌ ${Object.hasOwn(ERROR_MESSAGES, errorCode) ? ERROR_MESSAGES[errorCode] : GENERIC_ERROR}`;
```

`textContent` assignment is used, not `innerHTML`, so no markup can be injected regardless of
what arrives in the URL parameter. Unknown codes show a generic message.

### 5. Remove inline `on*` attributes from templates

Remaining `onclick=`, `onchange=`, and `onsubmit=` attributes in partial templates
(`a2a_agent_plugin_bindings_partial.html` and `admin.html`) are replaced with
`data-action="…"` attributes wired via event-delegation scripts that run with the
per-request nonce.

## Consequences

### ✅ Benefits

- **Defence in depth**: `script-src-attr 'none'` closes the inline-handler execution path
  independently of input validation and sanitiser correctness.
- **eval eliminated**: `htmx.config.allowEval = false` removes HTMX as an eval vector.
- **mXSS hardened**: DOMPurify handles the full spectrum of parser-mismatch payloads that the
  previous hand-rolled sanitiser did not address.
- **Reflected-text XSS closed**: Flash-banner codes are allowlisted server-side; attacker-
  chosen wording and markup are impossible even with a crafted link.
- **Stale URL params cleaned immediately**: `history.replaceState` now runs synchronously
  before the banner renders, so the URL is clean on first display and there is no 5-second
  auto-dismiss race.

### ❌ Trade-offs

- **`htmx.config.allowEval = false`** removes support for `hx-vals="js:{...}"`, `hx-vars`,
  and trigger-filter expressions. All existing usages have been migrated; new Admin UI code
  must not rely on eval-based HTMX features.
- **DOMPurify bundle size**: Adding DOMPurify to the bundle increases the JS payload by ~18 KB
  (minified, pre-gzip). This is an acceptable trade-off given the security benefit.
- **`style-src 'unsafe-inline'`**: Kept from ADR-0014 for Tailwind inline style attributes.
  This is a known residual risk; migrating to style nonces is tracked as a future enhancement.

### 🔄 Maintenance

- **New error codes**: When adding admin redirect paths, add the new code to both
  `_build_admin_redirect` callers in `admin.py` and the `ERROR_MESSAGES` map in `admin.html`.
  The JS unit test `admin-flash-message-xss.test.js` enforces sync between the two files.
- **HTMX eval migration**: Any new feature that would require `htmx.config.allowEval = true`
  must go through an ADR update; re-enabling eval silently removes the DOMPurify backstop for
  `hx-on` attributes.
- **DOMPurify version**: Pin the DOMPurify version in `package.json` and review the changelog
  on each update for changes to `ADD_ATTR` callback semantics.

## Alternatives Considered

| Alternative | Why Not Chosen |
|---|---|
| Keep `'unsafe-inline'` in `script-src-attr` | Does not close the inline-handler path; requires trusting all future input-validation and sanitiser changes to be flawless |
| Nonce `script-src-attr` instead of `'none'` | No browser supports per-attribute nonces; the only safe values are `'none'` and `'unsafe-inline'` |
| Keep hand-rolled sanitiser | Does not handle mXSS re-serialisation patterns; DOMPurify is the maintained industry standard |
| Server-side HTML escaping of flash text only | Does not prevent future regressions if another path reaches `innerHTML`; defence in depth requires the CSP layer |

## Testing

- **Unit** (`tests/unit/js/admin-flash-message-xss.test.js`): JSDOM execution of the flash
  IIFE with mXSS payloads, unknown codes, known codes, dismissal, and URL cleanup.
- **Unit** (`tests/unit/js/innerhtml-guard.test.js`): `installInnerHtmlGuard` with mXSS and
  `data-action` preservation.
- **Unit** (`tests/unit/js/security.test.js`): DOMPurify-backed `sanitizeHtmlForInsertion`
  with all known mXSS payload patterns.
- **Unit** (`tests/unit/mcpgateway/middleware/test_security_headers_middleware.py`): Asserts
  `script-src-attr 'none'` is present and `'unsafe-inline'` is absent.
- **Unit** (`tests/unit/mcpgateway/test_admin.py`): All redirect error handlers emit opaque
  codes; exception text never reaches the URL.
- **E2E** (`tests/live_gateway/e2e/test_admin_csp_inline_handlers.py`): Live gateway CSP header
  check on `/admin/login`.
- **Playwright** (`tests/playwright/security/test_admin_flash_message_xss.py`): Full browser
  execution check — `window.__flashXss` must remain `undefined` after crafted-link navigation.

## Status

Accepted and implemented as part of the validation and escaping tightening work (issue #1110).
Supersedes the CSP directives and trade-off notes originally recorded in ADR-0014.
