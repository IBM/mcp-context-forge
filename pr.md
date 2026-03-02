# Bug-fix PR

## Summary
`installInnerHtmlGuard()` (PR #3129) strips all inline `on*` event attributes from HTML set via `innerHTML` for XSS protection. This breaks every dynamically loaded UI element that relied on inline `onclick`/`onchange` handlers.

Most visible symptom: team selector dropdown items in the admin header are unclickable.

## Root Cause
The innerHTML sanitizer guard overrides `Element.prototype.innerHTML` and removes all `on*` attributes. Any code path that builds HTML with inline handlers and assigns it via `innerHTML` silently loses those handlers.

## Fix Description
Converted all affected inline `onclick`/`onchange` attributes to `data-action` attributes, then attached event listeners via `addEventListener` after each innerHTML assignment. Uses event delegation where appropriate (tables, lists).

### Affected locations (all fixed):
1. **Team selector dropdown** — event delegation on `#team-selector-items`
2. **Team selector search error retry** — addEventListener after innerHTML
3. **Team selector loadTeams error retry** (admin.html) — addEventListener after innerHTML
4. **Metrics error/retry buttons** — data-action + addEventListener
5. **Metrics empty state retry** — data-action + addEventListener
6. **Tag filter clear button** — data-action + addEventListener
7. **Auth header toggle/remove buttons** — data-action + addEventListener
8. **Import file chooser reset** — data-action + addEventListener
9. **Token list error retry** — data-action + addEventListener
10. **Token usage stats modal close** — data-action + addEventListener
11. **Bulk import selection controls** — data-action + addEventListener (select all/none/custom, reset, preview, import, checkbox onchange)
12. **Tool table action buttons** — event delegation on `#toolBody` (enrich, generate tests, validate, view, edit)
13. **Global search results** — addEventListener after innerHTML
14. **Public team join buttons** — addEventListener after innerHTML
15. **Chat server selection** — addEventListener after innerHTML
16. **Log viewer rows + correlation trace** — event delegation on tbody
17. **Security events correlation trace** — addEventListener after innerHTML
18. **Audit trail correlation trace** — addEventListener after innerHTML

## Verification

| Check | Status |
|-------|--------|
| Playwright regression test (`TestTeamSelectorDropdown`) | Pass |
| No remaining inline onclick in innerHTML strings | Verified via grep |

## Checklist
- [x] Root cause identified and verified with Playwright
- [x] All innerHTML+onclick paths converted to data-action + addEventListener
- [x] Regression test added
- [x] No secrets/credentials committed
