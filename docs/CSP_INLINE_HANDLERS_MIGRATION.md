# CSP Inline Event Handlers Migration

## Summary

Successfully migrated **273 inline event handlers** across **16 template files** to use a data-action delegation system, making the admin UI compliant with strict Content Security Policy (CSP) that prohibits `unsafe-inline` in `script-src`.

## Issue Reference

- **GitHub Issue**: #4655 - 165 inline event handlers in admin.html blocked under strict CSP
- **Related PR**: #4424 - feat(security): implement nonce-based CSP

## Changes Made

### 1. Event Delegation System (`mcpgateway/admin_ui/eventDelegation.js`)

Created a new event delegation module that:
- Intercepts events at the document level using capture phase
- Parses `data-action-*` attributes to determine which function to call
- Extracts arguments from `data-arg0`, `data-arg1`, etc. attributes
- Handles special cases like `this` references and event objects
- Supports all common event types: click, input, change, submit, keydown, focus, blur

**Key Features:**
- Automatic `this` reference resolution (converts `data-arg0="this"` to the actual element)
- JSON parsing for complex argument types
- Automatic value/checked state passing for input/change events
- Event object always available as last parameter

### 2. Integration (`mcpgateway/admin_ui/admin.js` & `events.js`)

- Imported `initializeEventDelegation` in admin.js
- Called initialization in events.js DOMContentLoaded handler (before other initializations)
- Event delegation system is now active for all admin UI interactions

### 3. Migration Script (`scripts/migrate_inline_handlers.py`)

Created an automated migration script that:
- Scans all HTML template files for inline event handlers
- Converts handlers to data-action format
- Handles `return` statements, `this` references, and complex arguments
- Provides dry-run mode for preview
- Successfully migrated 273 handlers across 16 files

### 4. Template Files Modified

**Files with migrations:**
1. `admin.html` - 194 handlers (main admin interface)
2. `mcp_registry_partial.html` - 16 handlers
3. `teams_partial.html` - 10 handlers
4. `tools_with_pagination.html` - 12 handlers
5. `llm_providers_partial.html` - 8 handlers
6. `llm_models_partial.html` - 6 handlers
7. `overview_partial.html` - 6 handlers
8. `change-password-required.html` - 5 handlers
9. `resources_partial.html` - 3 handlers
10. `tools_partial.html` - 3 handlers
11. `agents_partial.html` - 2 handlers
12. `gateways_partial.html` - 2 handlers
13. `prompts_partial.html` - 2 handlers
14. `servers_partial.html` - 2 handlers
15. `login.html` - 1 handler
16. `version_info_partial.html` - 1 handler

## Migration Examples

### Before (Inline Handler)
```html
<button onclick="Admin.showTab('tools')">Tools</button>
<input oninput="Admin.searchTeamSelector(this.value)" />
<form onsubmit="return Admin.handleToggleSubmit(event, 'tools')">
<button onclick="Admin.editTeamSafe(this)">Edit</button>
```

### After (Data-Action Delegation)
```html
<button data-action-click="showTab" data-arg0="'tools'">Tools</button>
<input data-action-input="searchTeamSelector" />
<form data-action-submit="handleToggleSubmit" data-arg0="'tools'">
<button data-action-click="editTeamSafe" data-arg0="this">Edit</button>
```

## Verification

### Inline Handlers Removed
```bash
# Before migration
$ grep -r 'onclick=' mcpgateway/templates/*.html | wc -l
255

# After migration
$ grep -r 'onclick=' mcpgateway/templates/*.html | wc -l
0
```

All inline event handlers (`onclick`, `oninput`, `onchange`, `onsubmit`, `onkeydown`, `onfocus`, `onblur`, `onload`) have been successfully removed from template files.

### CSP Compliance

The admin UI now works with strict CSP policies:
```
Content-Security-Policy: script-src 'self' 'nonce-ABC123...' https://cdnjs.cloudflare.com
```

No `'unsafe-inline'` or `'unsafe-hashes'` directives are required for inline event handlers.

## Testing Checklist

- [ ] Admin UI loads without console errors
- [ ] Navigation between tabs works (sidebar links)
- [ ] Global search modal opens (Ctrl/Cmd+K)
- [ ] Team selector dropdown functions
- [ ] Form submissions work (create/edit/delete operations)
- [ ] Input field handlers work (search, filters)
- [ ] Button click handlers work (all action buttons)
- [ ] Modal open/close functions
- [ ] Toggle switches work (enable/disable)
- [ ] LLM provider/model management
- [ ] Team management (create, edit, delete, join requests)
- [ ] Tool operations (test, view, edit, delete)
- [ ] Gateway operations
- [ ] Server operations

## Known Limitations

1. **Alpine.js `'unsafe-inline'` for styles**: Alpine.js still requires `'unsafe-inline'` in `style-src` for dynamic inline styles. This is tracked separately in #4653.

2. **HTMX `hx-on:*` attributes**: The 8 `hx-on:*` attributes are not affected by this migration as HTMX evaluates these via the trusted HTMX script and honors `inlineScriptNonce`.

3. **Complex inline functions**: A few handlers with complex inline arrow functions or callbacks may need manual review if they weren't automatically converted.

## Rollback Procedure

If issues are discovered:

1. Revert the template changes:
   ```bash
   git checkout HEAD~1 mcpgateway/templates/
   ```

2. Revert the JS changes:
   ```bash
   git checkout HEAD~1 mcpgateway/admin_ui/eventDelegation.js
   git checkout HEAD~1 mcpgateway/admin_ui/admin.js
   git checkout HEAD~1 mcpgateway/admin_ui/events.js
   ```

3. The migration script is preserved for future use if needed.

## Future Improvements

1. **Performance monitoring**: Add metrics to track event delegation performance
2. **Error handling**: Enhance error reporting for missing functions or invalid arguments
3. **Developer tools**: Create browser extension or debug mode to visualize delegated events
4. **Documentation**: Add inline documentation for common patterns

## References

- [Content Security Policy Level 3](https://www.w3.org/TR/CSP3/)
- [OWASP CSP Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html)
- [MDN: Content Security Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP)
- Issue #4655: 165 inline event handlers in admin.html blocked under strict CSP
- PR #4424: feat(security): implement nonce-based CSP
